"""
Generate FY2025 compare-table district revenue report.
Applies lookup_district_exclusions, Barnwell merger, Reported_Flag filter.
"""
import duckdb
from datetime import datetime

DB_PATH = "db/scde.duckdb"
OUT_DIR = "outputs/reports"

con = duckdb.connect(DB_PATH, read_only=True)


def fmt(v):
    """Format currency per SCDE convention: accounting parens for negatives, no decimals."""
    if v is None:
        return "n/a"
    v = float(v)
    if v < 0:
        return f'<span class="neg">$({abs(v):,.0f})</span>'
    return f"${v:,.0f}"


def fmt_plain(v):
    if v is None:
        return "n/a"
    v = float(v)
    if v < 0:
        return f"$({abs(v):,.0f})"
    return f"${v:,.0f}"


# ---------------------------------------------------------------------------
# Pull per-district data
# ---------------------------------------------------------------------------
EXCL_SUBQ = """
    SELECT District_ID FROM lookup_district_exclusions
    WHERE Exclude_Scope = 'all_reports'
      AND (Effective_FY_From IS NULL OR Effective_FY_From <= 2025)
      AND (Effective_FY_To   IS NULL OR Effective_FY_To   >= 2025)
"""

rows = con.execute(f"""
WITH lea_bucketed AS (
    SELECT
        CASE WHEN lr.District_ID IN ('0645','0648') THEN '0601'
             ELSE lr.District_ID END AS District_ID,
        SUM(CASE WHEN cdf.Stream_Type = 'Local'
                      AND COALESCE(cdf.Category, parent_cdf.Category) = 'Taxes & Fees'
                 THEN lr.Amount ELSE 0 END) AS local_sac,
        SUM(CASE WHEN cdf.Stream_Type = 'Local'
                      AND COALESCE(cdf.Category, parent_cdf.Category) IS NULL
                 THEN lr.Amount ELSE 0 END) AS local_add,
        SUM(CASE WHEN cdf.Stream_Type = 'Local'
                      AND COALESCE(cdf.Category, parent_cdf.Category) = 'District Services'
                 THEN lr.Amount ELSE 0 END) AS local_ds,
        SUM(CASE WHEN cdf.Stream_Type = 'Local'
                      AND COALESCE(cdf.Category, parent_cdf.Category)
                          = 'Investments, Donations & Other'
                 THEN lr.Amount ELSE 0 END) AS local_inv
    FROM lea_revenues lr
    LEFT JOIN code_district_funding_streams cdf
        ON lr.Revenue_Code = cdf.REV_Code
    LEFT JOIN code_district_funding_streams parent_cdf
        ON (LEFT(lr.Revenue_Code, 2) || '00') = parent_cdf.REV_Code
        AND parent_cdf.Rollup_Level = 2
    WHERE lr.FY = 2025
      AND lr.Reported_Flag = TRUE
      AND lr.District_ID NOT IN ({EXCL_SUBQ})
    GROUP BY 1
),
sceis_state AS (
    SELECT CASE WHEN District_ID IN ('0645','0648') THEN '0601'
                ELSE District_ID END AS District_ID,
           SUM(Amount) AS state_sceis
    FROM vw_sceis_fi_payments_classified
    WHERE Fiscal_Year = 2025 AND Funding_Stream = 'State'
      AND District_ID NOT IN ({EXCL_SUBQ})
    GROUP BY 1
),
sceis_fed AS (
    SELECT CASE WHEN District_ID IN ('0645','0648') THEN '0601'
                ELSE District_ID END AS District_ID,
           SUM(Amount) AS fed_sceis
    FROM vw_sceis_fi_payments_classified
    WHERE Fiscal_Year = 2025 AND Funding_Stream = 'Federal'
      AND District_ID NOT IN ({EXCL_SUBQ})
    GROUP BY 1
),
reported_flag AS (
    SELECT District_ID,
           MAX(CASE WHEN Reported_Flag THEN 1 ELSE 0 END) AS is_reported
    FROM lea_revenues
    WHERE FY = 2025
      AND District_ID NOT IN ({EXCL_SUBQ})
    GROUP BY 1
)
SELECT
    d.District_ID,
    d.District_Name,
    COALESCE(lb.local_sac, 0),
    COALESCE(lb.local_add, 0),
    COALESCE(lb.local_ds,  0),
    COALESCE(lb.local_inv, 0),
    COALESCE(ss.state_sceis, 0),
    COALESCE(sf.fed_sceis,   0),
    h.Total_Active_Enrollment,
    COALESCE(rf.is_reported, 0)
FROM dim_district d
LEFT JOIN lea_bucketed lb  ON d.District_ID = lb.District_ID
LEFT JOIN sceis_state ss   ON d.District_ID = ss.District_ID
LEFT JOIN sceis_fed   sf   ON d.District_ID = sf.District_ID
LEFT JOIN lea_headcounts h
       ON d.District_ID = h.District_ID
      AND h.SY = 2025 AND h.Report_Cycle = 45
LEFT JOIN reported_flag rf ON d.District_ID = rf.District_ID
WHERE d.District_ID NOT IN ({EXCL_SUBQ})
  AND d.District_ID NOT IN ('0645', '0648')
ORDER BY d.District_ID
""").fetchall()

# Build district dicts
districts = []
for r in rows:
    did, dname, sac, add_, ds, inv, state_s, fed_s, hc, reported = r
    sac     = float(sac     or 0)
    add_    = float(add_    or 0)
    ds      = float(ds      or 0)
    inv     = float(inv     or 0)
    state_s = float(state_s or 0)
    fed_s   = float(fed_s   or 0)

    if not reported:
        status = "unreported"
    elif did in ("1001", "4001"):
        status = "partial"
    else:
        status = "reported"

    is_charter = did in ("4701", "4801", "4901")
    grand = sac + add_ + ds + inv + state_s + fed_s

    districts.append({
        "id": did, "name": dname,
        "sac": sac, "add": add_, "ds": ds, "inv": inv,
        "state": state_s, "fed": fed_s, "grand": grand,
        "hc": hc, "status": status, "is_charter": is_charter,
    })

# ---------------------------------------------------------------------------
# Statewide weighted averages (only districts that have headcount)
# ---------------------------------------------------------------------------
thc  = sum(d["hc"]    for d in districts if d["hc"])
tsac = sum(d["sac"]   for d in districts if d["hc"])
tadd = sum(d["add"]   for d in districts if d["hc"])
tds  = sum(d["ds"]    for d in districts if d["hc"])
tinv = sum(d["inv"]   for d in districts if d["hc"])
tst  = sum(d["state"] for d in districts if d["hc"])
tfd  = sum(d["fed"]   for d in districts if d["hc"])
tgr  = tsac + tadd + tds + tinv + tst + tfd

wsac = round(tsac / thc);  wadd = round(tadd / thc);  wds  = round(tds  / thc)
winv = round(tinv / thc);  wst  = round(tst  / thc);  wfd  = round(tfd  / thc)
wgr  = round(tgr  / thc)

num_reported = sum(1 for d in districts if d["status"] == "reported")
num_total    = len(districts)
unr = [d for d in districts if d["status"] == "unreported"]
prt = [d for d in districts if d["status"] == "partial"]


# ---------------------------------------------------------------------------
# Variance data for methodology footer
# ---------------------------------------------------------------------------
var_rows = con.execute(f"""
WITH lea_state_sum AS (
    SELECT lr.District_ID, SUM(lr.Amount) AS state_lea
    FROM lea_revenues lr
    JOIN code_district_funding_streams cdf ON lr.Revenue_Code = cdf.REV_Code
    WHERE lr.FY = 2025 AND lr.Reported_Flag = TRUE AND cdf.Stream_Type = 'State'
      AND lr.District_ID NOT IN ({EXCL_SUBQ})
    GROUP BY lr.District_ID
),
sceis_state AS (
    SELECT CASE WHEN District_ID IN ('0645','0648') THEN '0601'
                ELSE District_ID END AS District_ID,
           SUM(Amount) AS state_sceis
    FROM vw_sceis_fi_payments_classified
    WHERE Fiscal_Year = 2025 AND Funding_Stream = 'State'
      AND District_ID NOT IN ({EXCL_SUBQ})
    GROUP BY 1
)
SELECT d.District_ID, d.District_Name,
       COALESCE(ls.state_lea,    0),
       COALESCE(ss.state_sceis,  0),
       COALESCE(ss.state_sceis, 0) - COALESCE(ls.state_lea, 0) AS variance
FROM dim_district d
LEFT JOIN lea_state_sum ls ON d.District_ID = ls.District_ID
LEFT JOIN sceis_state   ss ON d.District_ID = ss.District_ID
WHERE d.District_ID NOT IN ({EXCL_SUBQ})
  AND d.District_ID NOT IN ('0645', '0648')
ORDER BY ABS(COALESCE(ss.state_sceis, 0) - COALESCE(ls.state_lea, 0)) DESC
LIMIT 20
""").fetchall()


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
def pp(dollars, hc):
    if not hc:
        return None
    return dollars / hc


def pp_cell(dollars, hc, extra=""):
    val = pp(dollars, hc)
    cls = ("num " + extra).strip()
    if val is None:
        return f'<td class="{cls}"><span class="na">n/a</span></td>'
    return f'<td class="{cls}">{fmt(val)}</td>'


def build_row(d):
    hc = d["hc"]
    status = d["status"]

    row_cls = ""
    if status == "unreported":
        row_cls = ' class="row-unreported"'
    elif status == "partial":
        row_cls = ' class="row-partial"'

    badge = ""
    if d["is_charter"]:
        badge += (
            ' <span class="badge-charter"'
            ' data-tippy-content="Charter/consortium entity '
            '&#x2014; not a traditional LEA. Receives funding and reports independently."'
            ">Charter</span>"
        )
    if status == "unreported":
        badge += (
            ' <span class="badge-unreported"'
            ' data-tippy-content="Reported_Flag=FALSE for FY2025. LEA self-report not submitted.'
            ' LEA-sourced columns show n/a. SCEIS State and Federal shown from audited ledger."'
            ">Not Reported</span>"
        )
    elif status == "partial":
        badge += (
            ' <span class="badge-partial"'
            ' data-tippy-content="Reported_Flag=TRUE but LEA total anomalously low vs. SCEIS.'
            ' Local columns are provisional pending full resubmission."'
            ">Partial</span>"
        )

    hc_display = f"{hc:,}" if hc else "n/a"

    if status == "unreported":
        sac_td = '<td class="num"><span class="na">n/a</span></td>'
        add_td = '<td class="num"><span class="na">n/a</span></td>'
        ds_td  = '<td class="num"><span class="na">n/a</span></td>'
        inv_td = '<td class="num"><span class="na">n/a</span></td>'
    else:
        sac_td = pp_cell(d["sac"], hc)
        add_td = pp_cell(d["add"], hc)
        ds_td  = pp_cell(d["ds"],  hc)
        inv_td = pp_cell(d["inv"], hc)

    st_td = pp_cell(d["state"], hc, "sceis-col")
    fd_td = pp_cell(d["fed"],   hc, "fed-col")

    gr_pp = pp(d["grand"], hc)
    if gr_pp is not None:
        gr_td = f'<td class="num grand-total-col">{fmt(gr_pp)}</td>'
    else:
        gr_td = '<td class="num grand-total-col"><span class="na">n/a</span></td>'

    return (
        f'    <tr{row_cls}>\n'
        f'      <td class="name-cell">{d["name"]}{badge}<br>'
        f'<span class="district-sub">{d["id"]} &bull; {hc_display} pupils</span></td>\n'
        f'      {sac_td}{add_td}{ds_td}{inv_td}\n'
        f'      {st_td}\n'
        f'      {fd_td}\n'
        f'      {gr_td}\n'
        f'    </tr>'
    )


table_rows_html = "\n".join(build_row(d) for d in districts)

sc_total_row = (
    '    <tr class="row-total">\n'
    f'      <td class="name-cell">South Carolina Total<br>'
    f'<span class="district-sub">Weighted average &bull; {thc:,} pupils</span></td>\n'
    f'      <td class="num">{fmt(wsac)}</td>'
    f'<td class="num">{fmt(wadd)}</td>'
    f'<td class="num">{fmt(wds)}</td>'
    f'<td class="num">{fmt(winv)}</td>\n'
    f'      <td class="num sceis-col">{fmt(wst)}</td>\n'
    f'      <td class="num fed-col">{fmt(wfd)}</td>\n'
    f'      <td class="num grand-total-col">{fmt(wgr)}</td>\n'
    '    </tr>'
)

# Variance table rows
var_html_rows = ""
for vr in var_rows:
    vid, vname, vlea, vsceis, vvar = vr
    vlea = float(vlea); vsceis = float(vsceis); vvar = float(vvar)
    if vvar < -1_000_000:
        vcls = ' style="color:var(--sem-danger)"'
    elif vvar > 1_000_000:
        vcls = ' style="color:var(--sem-success)"'
    else:
        vcls = ""
    var_html_rows += (
        f"<tr><td>{vid}</td><td>{vname}</td>"
        f'<td class="num">{fmt_plain(vlea)}</td>'
        f'<td class="num">{fmt_plain(vsceis)}</td>'
        f'<td class="num"{vcls}>{fmt_plain(vvar)}</td></tr>\n'
    )

# Non-reporter table rows
unr_html = ""
for u in unr:
    unr_html += (
        f'<tr><td>{u["id"]}</td><td>{u["name"]}</td>'
        f'<td class="num">{fmt_plain(u["state"])}</td>'
        f'<td class="num">{fmt_plain(u["fed"])}</td></tr>\n'
    )

ts = datetime.now().strftime("%Y%m%dT%H%M%S")
ts_display = datetime.now().strftime("%B %d, %Y at %H:%M")

# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------
html = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>FY2024-25 District Revenue Comparison &#x2014; South Carolina</title>

  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />

  <script src="https://unpkg.com/@popperjs/core@2/dist/umd/popper.min.js"></script>
  <script src="https://unpkg.com/tippy.js@6/dist/tippy-bundle.umd.min.js"></script>
  <link rel="stylesheet" href="https://unpkg.com/tippy.js@6/dist/tippy.css" />

  <style>
    /* =========================================================
       SCDE Finance Design Tokens
       Source: docs/style/scde-design/tokens.json
       ========================================================= */
    :root {
      --brand-primary:     #2F3D4C;   /* Pantone 432 C */
      --brand-secondary:   #234058;   /* Pantone 7546 C */
      --brand-tertiary:    #43718B;   /* Pantone 5405 C */
      --brand-accent:      #F1BA55;   /* Pantone 142 C  — decorative only on dark bg */

      --sem-success:       #1F7A3A;
      --sem-warning:       #8A5A00;
      --sem-danger:        #B3261E;
      --sem-info:          #234058;
      --sem-neutral-bg:    #F4F6F8;
      --sem-neutral-fg:    #2F3D4C;
      --sem-border:        #7E8C9E;
      --sem-border-subtle: #CBD5E0;

      --font-display: 'Poppins', 'Segoe UI', system-ui, sans-serif;
      --font-mono:    'JetBrains Mono', 'Consolas', 'Menlo', monospace;

      --sp1: 4px;  --sp2: 8px;  --sp3: 12px; --sp4: 16px;
      --sp5: 20px; --sp6: 24px; --sp8: 32px;

      --radius-sm: 4px;  --radius-md: 8px;  --radius-lg: 16px;

      --shadow-sm: 0 1px 2px rgba(47,61,76,0.06), 0 1px 1px rgba(47,61,76,0.04);
      --shadow-md: 0 4px 8px rgba(47,61,76,0.08), 0 2px 4px rgba(47,61,76,0.06);
      --shadow-lg: 0 12px 24px rgba(47,61,76,0.12), 0 4px 8px rgba(47,61,76,0.08);
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; }
    body {
      font-family: var(--font-display);
      font-size: 15px;
      line-height: 22px;
      color: var(--sem-neutral-fg);
      background: var(--sem-neutral-bg);
    }
    a { color: var(--brand-secondary); text-decoration: underline; }
    a:hover { color: var(--brand-tertiary); }

    /* ── Page Header ── */
    .page-header {
      background: var(--brand-primary);
      color: #fff;
      padding: var(--sp6) var(--sp8);
      display: flex;
      align-items: center;
      gap: var(--sp6);
    }
    .logo-text  { font-size: 22px; font-weight: 700; color: #fff; line-height: 1.1; }
    .logo-sub   { font-size: 11px; color: rgba(255,255,255,0.65);
                  letter-spacing: 0.07em; text-transform: uppercase; }
    .header-meta { margin-left: auto; text-align: right;
                   font-size: 13px; color: rgba(255,255,255,0.75); }
    .header-fy  { font-size: 19px; font-weight: 600; color: #fff; }

    /* ── Layout ── */
    .container { max-width: 1600px; margin: 0 auto; padding: var(--sp6) var(--sp8); }

    /* ── KPI Cards ── */
    .kpi-row  { display: flex; gap: var(--sp4); margin-bottom: var(--sp6); flex-wrap: wrap; }
    .kpi-card {
      background: #fff;
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-md);
      padding: var(--sp4) var(--sp5);
      min-width: 150px;
      flex: 1;
    }
    .kpi-label { font-size: 11px; font-weight: 600; color: var(--sem-border);
                 text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: var(--sp1); }
    .kpi-value { font-size: 26px; font-weight: 700; color: var(--brand-primary);
                 font-family: var(--font-mono); line-height: 1.15; }
    .kpi-sub   { font-size: 11px; color: var(--sem-border); margin-top: var(--sp1); }

    /* ── Data-quality banner ── */
    .dq-banner {
      background: #FFF8E1;
      border-left: 4px solid var(--brand-accent);
      border-radius: var(--radius-sm);
      padding: var(--sp3) var(--sp4);
      margin-bottom: var(--sp6);
      font-size: 13px;
      line-height: 20px;
    }
    .dq-banner strong { color: var(--sem-warning); }

    /* ── Table wrapper ── */
    .table-wrap {
      background: #fff;
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-md);
      overflow-x: auto;
      margin-bottom: var(--sp8);
    }

    /* ── Comparison Table ── */
    table.compare {
      border-collapse: collapse;
      width: 100%;
      font-size: 12px;
      table-layout: fixed;
    }
    table.compare th,
    table.compare td {
      border: 1px solid var(--sem-border-subtle);
      padding: var(--sp2) var(--sp3);
      white-space: nowrap;
    }
    table.compare thead th {
      position: sticky;
      top: 0;
      z-index: 10;
      background: var(--brand-primary);
      color: #fff;
      font-weight: 600;
      font-size: 11px;
      text-align: center;
      vertical-align: bottom;
      line-height: 14px;
    }
    table.compare thead th.name-head {
      text-align: left; font-size: 12px;
      vertical-align: middle;
      min-width: 235px; width: 235px;
    }
    table.compare thead tr.group-row th {
      background: var(--brand-secondary);
      font-size: 10px; font-weight: 700;
      text-transform: uppercase; letter-spacing: 0.05em;
      border-bottom: 2px solid rgba(255,255,255,0.3);
    }
    .local-group { background: var(--brand-secondary) !important; }
    .state-group { background: var(--brand-primary)   !important; }
    .fed-group   { background: #1a5c3a !important; }
    .gt-group    { background: #1e1e2e !important; }

    table.compare td.num {
      text-align: right;
      font-family: var(--font-mono);
      font-size: 12px;
    }
    .neg { color: var(--sem-danger); }
    .na  { color: var(--sem-border); font-style: italic; }

    table.compare td.name-cell {
      font-weight: 500;
      text-align: left;
      white-space: normal;
      min-width: 235px; width: 235px;
      vertical-align: middle;
    }
    .district-sub { font-size: 10px; color: var(--sem-border); font-weight: 400; }

    table.compare td.sceis-col { background: rgba(47,61,76,0.04); }
    table.compare td.fed-col   { background: rgba(26,92,58,0.04); }
    table.compare td.grand-total-col { background: rgba(47,61,76,0.08); font-weight: 600; }
    table.compare th.sceis-col { background: var(--brand-primary) !important; }
    table.compare th.fed-col   { background: #1a5c3a !important; }
    table.compare th.gt-col    { background: #1e1e2e !important; }

    table.compare tbody tr:nth-child(even) { background: var(--sem-neutral-bg); }
    table.compare tbody tr:hover { background: rgba(67,113,139,0.10); transition: background 0.12s; }

    tr.row-total td {
      background: var(--brand-primary) !important;
      color: #fff !important;
      font-weight: 700;
      border-top: 2px solid var(--brand-secondary);
    }
    tr.row-total td .neg { color: #ffaaaa !important; }
    tr.row-total td .na  { color: rgba(255,255,255,0.50) !important; }
    tr.row-total td.sceis-col,
    tr.row-total td.grand-total-col { background: var(--brand-secondary) !important; }

    tr.row-unreported td        { opacity: 0.75; }
    tr.row-unreported td.name-cell { opacity: 1; }
    tr.row-partial td           { opacity: 0.88; }

    /* ── Badges ── */
    .badge-unreported, .badge-partial, .badge-charter {
      display: inline-block;
      font-size: 9px; font-weight: 700;
      letter-spacing: 0.04em; text-transform: uppercase;
      padding: 1px 5px; border-radius: var(--radius-sm);
      margin-left: 4px; vertical-align: middle;
    }
    .badge-unreported { background: #FFE0E0; color: var(--sem-danger);
                        border: 1px solid var(--sem-danger); }
    .badge-partial    { background: #FFF3CD; color: var(--sem-warning);
                        border: 1px solid var(--sem-warning); }
    .badge-charter    { background: #E3F2FD; color: var(--brand-tertiary);
                        border: 1px solid var(--brand-tertiary); }

    [data-tippy-content]    { cursor: help; }
    th[data-tippy-content]  { border-bottom: 2px dashed rgba(255,255,255,0.40); }

    /* ── Footer ── */
    .report-footer { font-size: 13px; line-height: 20px; }
    .footer-section {
      background: #fff;
      border-radius: var(--radius-md);
      box-shadow: var(--shadow-sm);
      padding: var(--sp5) var(--sp6);
      margin-bottom: var(--sp4);
    }
    .footer-section h3 {
      font-size: 13px; font-weight: 700; color: var(--brand-primary);
      margin-bottom: var(--sp3); text-transform: uppercase; letter-spacing: 0.05em;
      padding-bottom: var(--sp2); border-bottom: 2px solid var(--sem-border-subtle);
    }
    .footer-section p  { margin-bottom: var(--sp2); }
    .footer-section ul { margin: var(--sp2) 0 var(--sp2) var(--sp5); }
    .footer-section li { margin-bottom: var(--sp1); }

    .var-table { border-collapse: collapse; font-size: 12px; width: 100%; margin-top: var(--sp3); }
    .var-table th, .var-table td { border: 1px solid var(--sem-border-subtle); padding: var(--sp1) var(--sp2); }
    .var-table th { background: var(--sem-neutral-bg); font-weight: 600; }
    .var-table td.num { text-align: right; font-family: var(--font-mono); }

    /* Sortable column headers — click to sort, click again to reverse.
       Visual cue: pointer cursor on hover, ▲/▼ glyph on the active column. */
    table.compare thead th.sortable {
      cursor: pointer;
      user-select: none;
    }
    table.compare thead th.sortable:hover {
      background: rgba(255,255,255,0.08);
    }
    table.compare thead th.sortable[data-sort="asc"]::after  { content: " \25B2"; font-size: 0.7em; opacity: 0.85; }
    table.compare thead th.sortable[data-sort="desc"]::after { content: " \25BC"; font-size: 0.7em; opacity: 0.85; }

    @media print {
      .page-header, table.compare thead th, tr.row-total td { print-color-adjust: exact; }
    }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
    @media (max-width: 900px) {
      .container { padding: var(--sp4); }
      .page-header { padding: var(--sp4); }
    }
  </style>
</head>
<body>

<header class="page-header" role="banner">
  <div class="logo-block">
    <div class="logo-text">SCDE Finance</div>
    <div class="logo-sub">South Carolina Dept. of Education</div>
  </div>
  <div class="header-meta">
    <div class="header-fy">FY 2024&#x2013;25</div>
    <div>Summary District Revenue Comparison</div>
    <div style="font-size:11px;margin-top:4px;color:rgba(255,255,255,0.50)">
      Per Pupil &#x2014; 45-day Headcount &#x2014; Operating Revenue &#x2014; compare-table mode
    </div>
  </div>
</header>

<main class="container" role="main">
"""

html += f"""
  <!-- Data-quality banner -->
  <div class="dq-banner" role="alert">
    <strong>FY2024-25 Data Quality Notice:</strong>
    LEA self-report submission is incomplete.
    Of {num_total} included districts, <strong>{len(unr)} districts</strong>
    have <code>Reported_Flag = FALSE</code> (shown as &#8220;Not Reported&#8221;) and
    <strong>{len(prt)} districts</strong> (Charleston 01, Richland 01) have
    <code>Reported_Flag = TRUE</code> but anomalously low LEA totals consistent with a partial upload
    (shown as &#8220;Partial&#8221;).
    SCEIS State and Federal columns are complete from the audited ledger.
    <strong>6 entities excluded per <code>lookup_district_exclusions</code>:</strong>
    5205 SC Governor&#x2019;s School for Agriculture, 5207 SC School for the Deaf and the Blind,
    5208 DJJ, 5209 DOC, 5364 Governor&#x2019;s School for Arts &amp; Humanities,
    5395 Governor&#x2019;s School for Science &amp; Mathematics.
  </div>

  <!-- KPI row -->
  <div class="kpi-row" role="region" aria-label="Statewide summary statistics">
    <div class="kpi-card">
      <div class="kpi-label">SC Grand Total (PP)</div>
      <div class="kpi-value">{fmt(wgr)}</div>
      <div class="kpi-sub">Weighted avg &#x2022; {thc:,} pupils</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">State Total PP (SCEIS)</div>
      <div class="kpi-value">{fmt(wst)}</div>
      <div class="kpi-sub">Audited ledger &#x2022; system of record</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Federal Total PP (SCEIS)</div>
      <div class="kpi-value">{fmt(wfd)}</div>
      <div class="kpi-sub">Audited ledger &#x2022; system of record</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Local Taxes &amp; Fees PP</div>
      <div class="kpi-value">{fmt(wsac)}</div>
      <div class="kpi-sub">LEA self-report &#x2022; reported districts only</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Districts Reporting</div>
      <div class="kpi-value">{num_reported}/{num_total}</div>
      <div class="kpi-sub">Full LEA submission &#x2022; FY2024-25</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Statewide Headcount</div>
      <div class="kpi-value">{thc:,}</div>
      <div class="kpi-sub">45-day enrollment &#x2022; SY2025</div>
    </div>
  </div>

  <!-- Comparison Table -->
  <div class="table-wrap" role="region" aria-label="District revenue comparison table">
    <table class="compare" aria-label="FY2024-25 district revenue per pupil by revenue bucket">
      <thead>
        <tr class="group-row">
          <th class="name-head local-group" rowspan="2">District</th>
          <th colspan="4" class="local-group"
              data-tippy-content="Local revenue from LEA self-report (Revenue FY2024-25.xlsx), filtered Reported_Flag=TRUE. Per-pupil using 45-day headcount (SY2025). Bucket assignment from code_district_funding_streams.Category with parent-level fallback.">
            Local Revenue (LEA Self-Report)
          </th>
          <th colspan="1" class="state-group"
              data-tippy-content="State Total from SCEIS FI Payments (system of record). Source: vw_sceis_fi_payments_classified, Funding_Stream=State, Fiscal_Year=2025. This is the authoritative audited figure. LEA-reported State sub-buckets will not sum to this figure — see Methodology footer for per-district variances.">
            State (SCEIS SOR)
          </th>
          <th colspan="1" class="fed-group"
              data-tippy-content="Federal Total from SCEIS FI Payments (system of record). Source: vw_sceis_fi_payments_classified, Funding_Stream=Federal, Fiscal_Year=2025. Includes Barnwell 45 and 48 federal SCEIS receipts merged into Barnwell 01 per FY24+ consolidation rule.">
            Federal (SCEIS SOR)
          </th>
          <th colspan="1" class="gt-group">&nbsp;</th>
        </tr>
        <tr>
          <th data-tippy-content="Local Taxes and Fees (SAC Required): Revenue codes 1110 Ad Valorem Taxes, 1140 Penalties and Interest on Taxes, 1190 Other Taxes — children of code 1100 Taxes Levied/Assessed by the LEA. Resolved category: Taxes and Fees. Source: LEA self-report.">
            Local Taxes &amp; Fees<br>
            <span style="font-weight:400;opacity:0.75">(SAC Req.)</span>
          </th>
          <th data-tippy-content="Local Additional: Revenue from non-LEA local government units (1200-series: 1210, 1240, 1280, 1290) and other miscellaneous local sources (1900-series: 1920 Private Sources, 1950 Refund of Prior Year Expenditures, 1993 Insurance Proceeds, 1994 Legal Settlements, 1999 Other). These codes have no Category assignment in code_district_funding_streams. Source: LEA self-report.">
            Local Additional
          </th>
          <th data-tippy-content="Local District Services: Revenues from district-provided services. Includes Tuition (1300-series), Transportation Fees (1400-series), Food Services (1600-series), Pupil Activities (1700-series), Rentals (1910), Special Needs Transportation and Medicaid (1930, 1931), Canteen Operations (1992). Category: District Services. Source: LEA self-report.">
            Local Dist. Services
          </th>
          <th data-tippy-content="Local Investments, Donations and Other: Earnings on investments including Interest (1510), Dividends (1520), Gain/Loss on Sale (1530). Revenue code 1500-series, parent code 1500 Earnings on Investments. Category: Investments, Donations and Other. Source: LEA self-report.">
            Local Invest. &amp; Donations
          </th>
          <th class="sceis-col"
              data-tippy-content="State Total from SCEIS (system of record). Sum of all FI Payment amounts where Funding_Stream=State, Fiscal_Year=2025. District_ID derived from first 4 characters of the SCEIS Reference field (~92% attribution rate). Sub-bucket detail not available at Revenue_Code level from SCEIS; see LEA columns for sub-bucket estimates. Note: SCEIS total will differ from LEA-reported State sum for most districts.">
            State Total<br>
            <span style="font-weight:400;opacity:0.75">(SCEIS SOR)</span>
          </th>
          <th class="fed-col"
              data-tippy-content="Federal Total from SCEIS (system of record). Sum of all FI Payment amounts where Funding_Stream=Federal, Fiscal_Year=2025. Includes Barnwell 45 (0645) and Barnwell 48 (0648) federal SCEIS receipts rolled into Barnwell 01 per FY24+ consolidation rule.">
            Federal Total<br>
            <span style="font-weight:400;opacity:0.75">(SCEIS SOR)</span>
          </th>
          <th class="gt-col"
              data-tippy-content="Grand Total per pupil: Local Taxes and Fees + Local Additional + Local District Services + Local Investments + State Total (SCEIS) + Federal Total (SCEIS), divided by 45-day enrollment headcount.">
            Grand Total<br>Per Pupil
          </th>
        </tr>
      </thead>
      <tbody>
""" + table_rows_html + """
      </tbody>
      <tfoot>
""" + sc_total_row + """
      </tfoot>
    </table>
  </div>

  <!-- Footer -->
  <footer class="report-footer" role="contentinfo">
"""

html += (
    "    <!-- Provenance -->\n"
    "    <div class=\"footer-section\">"
)
html += f"""
      <h3>Data Provenance</h3>
      <p><strong>State Total / Federal Total columns:</strong>
      SCEIS system of record via <code>vw_sceis_fi_payments_classified</code>,
      <code>Fiscal_Year = 2025</code>, <code>Funding_Stream IN (&#x27;State&#x27;, &#x27;Federal&#x27;)</code>.
      Source file: <em>FI Payments by Vendor FY25.xlsx</em>. These are audited ledger figures and
      constitute the system of record for state and federal flows.</p>

      <p><strong>Local Revenue columns (Taxes &amp; Fees, Additional, District Services, Investments/Donations):</strong>
      LEA self-report via <code>lea_revenues</code>, joined to <code>code_district_funding_streams</code>
      on <code>Revenue_Code = REV_Code</code>, filtered <code>Reported_Flag = TRUE</code>, <code>FY = 2025</code>.
      Source file: <em>Revenue FY2024-25.xlsx</em>. Bucket assignment uses <code>Category</code> from
      <code>code_district_funding_streams</code>; leaf-level codes with NULL Category are resolved to
      their Level-2 parent&#x2019;s Category using <code>LEFT(Revenue_Code, 2) || &#x27;00&#x27;</code> lookup.</p>

      <p><strong>Headcount denominator:</strong>
      <code>lea_headcounts.Total_Active_Enrollment</code>, <code>SY = 2025</code>,
      <code>Report_Cycle = 45</code> (45-day count, not 135-day ADM).</p>

      <p><strong>Barnwell consolidation (effective FY2024+):</strong>
      Districts 0645 (Barnwell 45) and 0648 (Barnwell 48) are consolidated into 0601 (Barnwell 01).
      Their SCEIS federal receipts ($2,839,253 and $682,601 respectively) are summed into the
      Barnwell 01 row. Their LEA revenue data shows <code>Reported_Flag = FALSE</code> for FY25;
      Barnwell 01 headcount (3,088 pupils) is used as the per-pupil denominator.</p>

      <p><strong>District exclusion filter:</strong>
      Applied via <code>lookup_district_exclusions WHERE Exclude_Scope = &#x27;all_reports&#x27;</code>
      with effective FY range check
      (<code>Effective_FY_From &lt;= 2025 AND Effective_FY_To &gt;= 2025</code>, NULLs treated as unbounded).
      Filter applied to all data pulls: LEA aggregation, SCEIS aggregation,
      <code>dim_district</code> district list, and statewide weighted averages.</p>
    </div>

    <!-- Methodology: SCEIS vs LEA variance -->
    <div class="footer-section">
      <h3>Methodology Note: LEA-Reported State Sub-Buckets vs. SCEIS State Total</h3>
      <p>The <strong>State Total</strong> column is sourced from SCEIS (system of record) and
      represents the audited ledger value of state payments to each district for FY2025.
      The local-revenue columns (including any State-stream detail) are sourced from LEA self-report.
      These two sources <strong>will not agree</strong> for most districts.</p>
      <p>The discrepancy reflects timing differences (SCEIS records at payment date; LEA records at
      receipt date), accrual adjustments, prior-year true-ups, unsettled pass-through flows, and
      differences in what each system classifies as &#8220;state&#8221; revenue.
      The variance is expected and informative &#x2014; do not pro-rate or silently adjust either
      figure to force agreement. The discrepancy is disclosed below.</p>
      <p><strong>Charter entities</strong> (4701 SC Public Charter School District,
      4801 Charter Institute at Erskine, 4901 Limestone Charter Association) report $0 in
      LEA State revenue because they do not submit LARS state-revenue line detail;
      all their state funding is captured by SCEIS. This is the expected pattern.</p>
      <table class="var-table">
        <thead>
          <tr>
            <th>ID</th><th>District</th>
            <th style="text-align:right">LEA State ($)</th>
            <th style="text-align:right">SCEIS State ($)</th>
            <th style="text-align:right">Variance ($)</th>
          </tr>
        </thead>
        <tbody>{var_html_rows}</tbody>
      </table>
    </div>

    <!-- Excluded districts -->
    <div class="footer-section">
      <h3>Excluded Districts (Source: lookup_district_exclusions)</h3>
      <p>Six entities are excluded from this report per
      <code>lookup_district_exclusions</code> (<code>Exclude_Scope = &#x27;all_reports&#x27;</code>).
      They do not appear as rows, do not contribute to statewide weighted averages,
      and are not listed among non-reporters.</p>
      <ul>
        <li><strong>5205</strong> &#x2014; SC Governor&#x2019;s School for Agriculture at John De La Howe
          (special-purpose school; not a traditional LEA)</li>
        <li><strong>5207</strong> &#x2014; SC School for the Deaf and the Blind
          (special-purpose school; not a traditional LEA)</li>
        <li><strong>5208</strong> &#x2014; Department of Juvenile Justice (DJJ)
          (state-agency school; receives direct agency appropriations)</li>
        <li><strong>5209</strong> &#x2014; Department of Corrections (DOC)
          (state-agency school; receives direct agency appropriations)</li>
        <li><strong>5364</strong> &#x2014; Governor&#x2019;s School for the Arts and Humanities
          (special-purpose school; not a traditional LEA)</li>
        <li><strong>5395</strong> &#x2014; Governor&#x2019;s School for Science and Mathematics
          (special-purpose school; not a traditional LEA)</li>
      </ul>
      <p><strong>Impact of exclusion (per data-quality validation):</strong>
      approximately 782 pupils excluded (0.10% of statewide 45-day headcount);
      $0 LEA-reported revenue across all 6 entities for FY25;
      $38,010 in SCEIS-attributed payments (0.0006% of district-attributed SCEIS payments for FY25).
      The previous run of this report incorrectly included 5205 and 5207 in the non-reporter list;
      this run correctly excludes them from all output sections.</p>
    </div>

    <!-- Non-reporters -->
    <div class="footer-section">
      <h3>Non-Reporter and Partial-Reporter Status (FY2024-25)</h3>
      <p>The following {len(unr)} districts have <code>Reported_Flag = FALSE</code> in
      <code>lea_revenues</code> for FY2025. Their LEA-sourced local columns display &#8220;n/a.&#8221;
      SCEIS State and Federal totals are shown from the audited ledger.
      These districts are excluded from statewide LEA-sourced weighted averages;
      their SCEIS amounts are included in statewide SCEIS totals.</p>
      <table class="var-table">
        <thead>
          <tr>
            <th>ID</th><th>District</th>
            <th style="text-align:right">SCEIS State ($)</th>
            <th style="text-align:right">SCEIS Federal ($)</th>
          </tr>
        </thead>
        <tbody>{unr_html}</tbody>
      </table>
      <p style="margin-top:var(--sp3)"><strong>Partial reporters</strong>
      (<code>Reported_Flag = TRUE</code> but anomalously low LEA totals):</p>
      <ul>
        <li><strong>1001 Charleston 01:</strong>
          LEA total $41,605,188 vs. SCEIS State $217,881,309.
          Local columns flagged as provisional. Do not cite in external reports
          without confirmation of a full resubmission.</li>
        <li><strong>4001 Richland 01:</strong>
          LEA total $195,191 vs. SCEIS State $149,872,059.
          Local columns flagged as provisional. Do not cite in external reports
          without confirmation of a full resubmission.</li>
      </ul>
      <p style="margin-top:var(--sp2)">FY2025 LEA submission cycle was incomplete as of {ts_display}.
      Build FY25 external publications only after a data-quality pass confirms the submission
      is complete (all {num_total} included districts with <code>Reported_Flag = TRUE</code>
      and non-trivial totals).</p>
    </div>

    <!-- Generation metadata -->
    <div class="footer-section" style="font-size:12px;color:var(--sem-border)">
      <p>
        <strong>Report:</strong> compare-table &nbsp;&#x2022;&nbsp;
        <strong>FY:</strong> 2024-25 (SY2025) &nbsp;&#x2022;&nbsp;
        <strong>Districts displayed:</strong> {num_total} &nbsp;&#x2022;&nbsp;
        <strong>Generated:</strong> {ts_display} &nbsp;&#x2022;&nbsp;
        <strong>DB:</strong> <code>db/scde.duckdb</code>
      </p>
      <p>
        <strong>Exclusion source:</strong>
        <code>lookup_district_exclusions</code> (Exclude_Scope=all_reports, FY range 2025) &nbsp;&#x2022;&nbsp;
        <strong>Currency:</strong> accounting parentheses for negatives, no decimals &nbsp;&#x2022;&nbsp;
        <strong>Denominator:</strong> 45-day headcount (not 135-day ADM) &nbsp;&#x2022;&nbsp;
        <strong>Statewide row:</strong> weighted average (sum dollars / sum pupils, not arithmetic mean)
      </p>
      <p>
        <strong>Column sources:</strong>
        Local SAC Req., Local Additional, Local Dist. Services, Local Investments: LEA self-report.
        State Total, Federal Total: SCEIS system of record.
      </p>
    </div>

  </footer>
</main>
"""

TIPPY_SCRIPT = """
<script>
  document.addEventListener('DOMContentLoaded', function() {
    if (typeof tippy !== 'undefined') {
      tippy('[data-tippy-content]', {
        theme: 'light-border',
        placement: 'top',
        arrow: true,
        maxWidth: 380,
        allowHTML: false,
        trigger: 'mouseenter focus',
        interactive: false,
      });
    }

    // ── Sortable comparison table ──────────────────────────────────────
    // The table has a two-row thead: row 0 has the District header
    // (rowspan=2) plus group headers, row 1 has the seven actual column
    // heads. Wire click-to-sort on District (col 0) and on each row-1 th
    // (cols 1–7). Numeric cells contain currency strings like "$1,234"
    // or accounting parens "$(1,234)" or "n/a" — parseValue handles all.
    (function() {
      var table = document.querySelector('table.compare');
      if (!table) return;
      var headRows = table.querySelectorAll('thead tr');
      if (headRows.length < 2) return;
      var tbody = table.querySelector('tbody');
      if (!tbody) return;

      // Build the sortable header set: District first, then row-1 columns.
      var sortable = [];
      var districtTh = headRows[0].querySelector('th.name-head');
      if (districtTh) sortable.push({ th: districtTh, col: 0, numeric: false });
      Array.prototype.forEach.call(headRows[1].children, function(th, i) {
        sortable.push({ th: th, col: i + 1, numeric: true });
      });

      function parseValue(td, numeric) {
        var text = (td.textContent || '').trim();
        if (text === '' || /^n\\/a$/i.test(text) || text === '—') return null;
        if (!numeric) return text.toLowerCase();
        var isNeg = /\\(.*\\)/.test(text);
        var num = parseFloat(text.replace(/[$,()—\\s]/g, '')) || 0;
        return isNeg ? -num : num;
      }

      var current = { col: -1, dir: 1 };

      sortable.forEach(function(entry) {
        entry.th.classList.add('sortable');
        entry.th.setAttribute('role', 'button');
        entry.th.setAttribute('tabindex', '0');
        var handler = function() {
          var dir = (current.col === entry.col)
            ? -current.dir
            : (entry.numeric ? -1 : 1);  // numeric defaults desc, text asc
          current = { col: entry.col, dir: dir };

          var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
          rows.sort(function(a, b) {
            var av = parseValue(a.cells[entry.col], entry.numeric);
            var bv = parseValue(b.cells[entry.col], entry.numeric);
            if (av === null && bv === null) return 0;
            if (av === null) return 1;
            if (bv === null) return -1;
            if (av < bv) return -1 * dir;
            if (av > bv) return  1 * dir;
            return 0;
          });
          rows.forEach(function(r) { tbody.appendChild(r); });

          sortable.forEach(function(s) { s.th.removeAttribute('data-sort'); });
          entry.th.setAttribute('data-sort', dir > 0 ? 'asc' : 'desc');
        };
        entry.th.addEventListener('click', handler);
        entry.th.addEventListener('keydown', function(e) {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); handler(); }
        });
      });
    })();
  });
</script>

</body>
</html>
"""

html += TIPPY_SCRIPT

out_path = f"{OUT_DIR}/district_revenue_compare-table_FY2025_{ts}.html"
with open(out_path, "w", encoding="utf-8") as fh:
    fh.write(html)

print(f"OUTPUT_PATH={out_path}")
print(f"DISTRICTS={num_total}")
print(f"REPORTED={num_reported}  UNREPORTED={len(unr)}  PARTIAL={len(prt)}")
print(f"GRAND_PP={wgr}  STATE_PP={wst}  FED_PP={wfd}  SAC_PP={wsac}")
print(f"TIMESTAMP={ts}")
