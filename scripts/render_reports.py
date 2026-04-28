"""
FY2024 District Revenue Reports — all five modes.
Renders: compare-table, compare-chart, detail Greenville, detail Jasper, detail Dillon 04.
"""
import json, os, tempfile, duckdb
from collections import defaultdict
from datetime import datetime

TIMESTAMP = "20260427T150000"
DB_PATH = os.path.join(os.path.expanduser('~'), 'Finance Dazzle', 'scde-agent-tree', 'db', 'scde.duckdb')
OUT_DIR = os.path.join(os.path.expanduser('~'), 'Finance Dazzle', 'scde-agent-tree', 'outputs', 'reports')
DATA_FILE = os.path.join(tempfile.gettempdir(), 'fy2024_revenue_data.json')

with open(DATA_FILE) as f:
    payload = json.load(f)

DATA_ROWS = payload['data_rows']
SC = payload['SC']

# ─────────────────────────────────────────────────────────────
# SHARED DESIGN TOKENS & CDN LINKS (Look Deeper design system)
# ─────────────────────────────────────────────────────────────

TOKENS_CSS = """
:root {
  --brand-navy:      #2F3D4C;
  --brand-navy-deep: #234058;
  --brand-slate:     #43718B;
  --brand-gold:      #F1BA55;
  --navy-100: #eef1f4;
  --navy-200: #d5dce3;
  --navy-300: #a9b6c1;
  --navy-600: #3d5364;
  --navy-700: #2F3D4C;
  --navy-800: #223040;
  --gold-100: #fdf4e0;
  --gold-500: #F1BA55;
  --gold-600: #c79842;
  --white:    #ffffff;
  --ink-50:   #f7f8f9;
  --ink-100:  #eef0f2;
  --ink-200:  #dde1e5;
  --ink-300:  #bbc3cb;
  --ink-400:  #8a96a3;
  --ink-500:  #5f6c7a;
  --ink-700:  #394756;
  --ink-900:  #0f1820;
  --success-bg: #e6f3ec;
  --success-fg: #1b6b43;
  --danger-bg:  #fbeaea;
  --danger-fg:  #a3261f;
  --danger-line:#c65651;
  --warning-bg: #fdf4e0;
  --warning-fg: #8f6b2a;
  --info-bg:    #e8eff4;
  --info-fg:    #234058;
  --font-sans:  'Poppins', system-ui, sans-serif;
  --font-mono:  'JetBrains Mono', ui-monospace, monospace;
  --s-1:4px; --s-2:8px; --s-3:12px; --s-4:16px; --s-5:24px; --s-6:32px;
  --r-sm:4px; --r-md:6px; --r-lg:10px; --r-xl:14px; --r-full:999px;
  --shadow-1: 0 1px 2px rgba(15,24,32,.04),0 1px 1px rgba(15,24,32,.03);
  --shadow-2: 0 2px 6px rgba(15,24,32,.06),0 1px 2px rgba(15,24,32,.04);
  --shadow-3: 0 8px 24px rgba(15,24,32,.08),0 2px 4px rgba(15,24,32,.04);
}
"""

TIPPY_CDN = """
<script src="https://unpkg.com/@popperjs/core@2/dist/umd/popper.min.js"></script>
<script src="https://unpkg.com/tippy.js@6/dist/tippy-bundle.umd.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/dist/tippy.css"/>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/animations/shift-away.css"/>
"""

GOOGLE_FONTS = '<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">'

TIPPY_INIT = """
setTimeout(()=>{
  tippy('[data-tippy-content]',{theme:'scde',animation:'shift-away',allowHTML:true,
    trigger:'mouseenter focus',touch:['hold',500],maxWidth:360,
    content(r){return r.dataset.tippyContent;}
  });
},80);
"""

TIPPY_THEME_CSS = """
.tippy-box[data-theme~='scde']{
  background:var(--navy-800);color:#fff;font-family:var(--font-sans);font-size:12px;
  border-radius:var(--r-md);padding:2px;box-shadow:var(--shadow-3);
}
.tippy-box[data-theme~='scde'] .tippy-content{padding:8px 12px;line-height:1.5;}
.tippy-box[data-theme~='scde'] .tippy-arrow::before{color:var(--navy-800);}
"""

FOOTER_COMMON = """
<footer style="background:var(--ink-100);border-top:1px solid var(--ink-200);padding:var(--s-5) var(--s-6);font-size:11px;color:var(--ink-500);line-height:1.7;margin-top:var(--s-6);">
  <div style="max-width:1200px;margin:0 auto;display:grid;gap:var(--s-4);">
    <div>
      <strong style="color:var(--ink-700);">Data Provenance</strong><br>
      Local sub-buckets (SAC Required, Additional, District Services, Investments): <code>lea_revenues</code> filtered <code>Reported_Flag=TRUE</code>, joined to <code>code_district_funding_streams</code> for bucket assignment.<br>
      <strong>State Total &amp; Federal Total: SCEIS-sourced</strong> from <code>vw_sceis_fi_payments_classified</code> (<code>Funding_Stream IN ('State','Federal')</code>, FY=2024).<br>
      State sub-buckets (SAC, PropTax, Other) are LEA-sourced and <em>will not sum to the SCEIS State Total</em> — this is the documented internal inconsistency; no adjustment has been applied.<br>
      Other Sources (5xxx): LEA-sourced bond proceeds and interfund transfers.
    </div>
    <div>
      <strong style="color:var(--ink-700);">Internal Inconsistency — State Bucket</strong><br>
      SCEIS FI Payment totals (State column) do not equal the sum of LEA-reported State sub-buckets. This occurs because SCEIS captures cash disbursements at the state level, while LEA LARS self-reports classify by program code. The variance is disclosed per district in the methodology disclosure. <strong>Do not interpret the sub-bucket total as an independent cross-check of the SCEIS figure.</strong>
    </div>
    <div>
      <strong style="color:var(--ink-700);">Districts with Reported_Flag=FALSE (FY2024)</strong><br>
      <strong>Jasper 01 (2701):</strong> All 263 revenue rows have <code>Reported_Flag=FALSE</code>. LEA self-report data unavailable. SCEIS-sourced totals: State $15,840,593 | Federal $11,037,318.<br>
      <strong>Barnwell 01 (0601):</strong> Had Reported_Flag=FALSE for its own rows; revenue consolidated from legacy IDs Barnwell 45 (0645) + Barnwell 48 (0648) per FY2024+ merger rule. Headcount: Barnwell 01 SY2024 headcount (3,123) used as denominator.
    </div>
    <div>
      <strong style="color:var(--ink-700);">Excluded Entities</strong><br>
      Per <code>lookup_district_exclusions</code> (<code>Exclude_Scope='all_reports'</code>): SC Governor's School for Agriculture at John De La Howe (5205), SC School for the Deaf and the Blind (5207), DJJ (5208), DOC (5209), Governor's School for the Arts and Humanities (5364), and Governor's School for Science and Mathematics (5395). State-agency schools (DJJ, DOC) and special-purpose schools receive direct appropriations not routed through the standard LEA revenue ledger; the lookup table is the single source of truth for this list.
    </div>
    <div>
      <strong style="color:var(--ink-700);">Methodology</strong><br>
      Per-pupil denominator: 45-day PowerSchool QDC1 headcount (<code>lea_headcounts.Total_Active_Enrollment</code>, SY=2024, Report_Cycle=45). ADM is not used.<br>
      Statewide row: weighted average = SUM(dollars) / SUM(headcount) across all reporting districts with valid headcount. Not the arithmetic mean of district per-pupil rates.<br>
      Negative amounts displayed as $(X,XXX) in <span style="color:var(--danger-fg);font-weight:600;">red</span>. Zero shown as $0.
    </div>
    <div>
      <strong style="color:var(--ink-700);">Data Quality Verdict</strong><br>
      Reference: <code>outputs/reports/sceis_vs_lea_reconciliation_20260427T120000.md</code> &mdash;
      <span style="background:var(--warning-bg);color:var(--warning-fg);padding:2px 8px;border-radius:var(--r-full);font-weight:600;">YELLOW — FY2024: Proceed with caveats</span><br>
      FY2025 data is on HOLD (~70 of 80 districts submitted; this report does not include FY2025.
    </div>
    <div style="color:var(--ink-400);font-size:10px;">
      FY2024 (fiscal year ending June 2024) &bull; SY2024 headcount &bull;
      Generated: 2026-04-27T15:00:00 &bull;
      Source DB: db/scde.duckdb
    </div>
  </div>
</footer>
"""

def fmt_dollars(v, parens=True):
    """Format as $X,XXX with accounting parens for negatives."""
    if v is None:
        return 'n/a'
    n = round(float(v))
    if n == 0:
        return '$0'
    if n < 0 and parens:
        return f'$({abs(n):,})'
    return f'${n:,}'

def pp_cell(raw, hc, cls=''):
    """Render a per-pupil cell; n/a if no headcount."""
    if hc is None or hc == 0:
        return f'<td class="na {cls}">n/a</td>'
    v = raw / hc
    n = round(v)
    if n == 0:
        return f'<td class="{cls} z">$0</td>'
    if n < 0:
        return f'<td class="{cls} neg" style="color:var(--danger-fg);">$({abs(n):,})</td>'
    return f'<td class="{cls}">${n:,}</td>'


# ═══════════════════════════════════════════════════════════════
# REPORT 1 — compare-table
# ═══════════════════════════════════════════════════════════════

def build_compare_table():
    rows_js = json.dumps(DATA_ROWS)
    sc_js = json.dumps(SC)

    # Top 5 variance for footer
    sorted_var = sorted(DATA_ROWS, key=lambda d: abs(d['state_variance']), reverse=True)
    var_rows = ''
    for d in sorted_var[:5]:
        pct = (d['state_variance'] / d['state_total_sceis'] * 100) if d['state_total_sceis'] else 0
        sign = '+' if d['state_variance'] >= 0 else ''
        var_rows += f"<tr><td>{d['name']} ({d['id']})</td><td>${d['state_total_sceis']:,.0f}</td><td>${d['lea_state_sum']:,.0f}</td><td style='color:var(--danger-fg)'>${d['state_variance']:,.0f} ({sign}{pct:.1f}%)</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>FY2024 District Revenue — Summary Comparison Table</title>
{GOOGLE_FONTS}
{TIPPY_CDN}
<style>
{TOKENS_CSS}
{TIPPY_THEME_CSS}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--font-sans);font-size:12.5px;background:var(--ink-50);color:var(--ink-900);line-height:1.4}}
.page-header{{background:linear-gradient(135deg,var(--brand-navy) 0%,var(--brand-slate) 100%);color:#fff;padding:20px 28px 16px;border-bottom:4px solid var(--brand-gold)}}
.page-header h1{{font-size:20px;font-weight:700;letter-spacing:-.2px}}
.page-header .sub{{font-size:12px;opacity:.82;margin-top:4px}}
.badge{{display:inline-block;background:var(--brand-gold);color:var(--ink-900);padding:2px 10px;border-radius:var(--r-full);font-size:11px;font-weight:700;margin-left:8px;vertical-align:middle}}
.summary-bar{{display:flex;gap:12px;flex-wrap:wrap;padding:10px 28px;background:#fff;border-bottom:1px solid var(--ink-200)}}
.chip{{background:var(--ink-50);border:1px solid var(--ink-200);border-radius:var(--r-lg);padding:7px 13px}}
.chip .val{{font-size:17px;font-weight:700;color:var(--brand-navy)}}
.chip .val.warn{{color:var(--warning-fg)}}
.chip .lbl{{font-size:10px;color:var(--ink-400);text-transform:uppercase;letter-spacing:.3px}}
.controls{{background:#fff;border-bottom:1px solid var(--ink-200);padding:9px 28px;display:flex;gap:14px;align-items:center;flex-wrap:wrap}}
.controls label{{font-size:11.5px;color:var(--ink-400);margin-right:4px}}
.controls input,.controls select{{border:1px solid var(--ink-200);border-radius:var(--r-sm);padding:4px 9px;font-size:12px;outline:none;background:#fff;font-family:var(--font-sans)}}
.btn-reset{{background:none;border:1px solid var(--ink-200);border-radius:var(--r-sm);padding:4px 11px;font-size:12px;cursor:pointer;color:var(--ink-400);font-family:var(--font-sans)}}
.hint{{color:var(--ink-400);font-size:11px;margin-left:auto}}
.table-wrap{{overflow:auto;max-height:calc(100vh - 200px);padding:0 0 28px}}
table{{width:100%;border-collapse:separate;border-spacing:0;font-size:11.5px;min-width:1350px}}
thead th{{position:sticky;top:0;z-index:8;background:var(--brand-navy);color:#fff;padding:7px 5px;text-align:center;font-weight:600;font-size:10.5px;border-right:1px solid rgba(255,255,255,.12);cursor:pointer;white-space:nowrap;font-family:var(--font-sans)}}
thead th:first-child{{text-align:left;min-width:200px;z-index:20;left:0;position:sticky}}
thead th.th-local{{background:#2d5a4b}}
thead th.th-state{{background:#1d3d6b}}
thead th.th-fed{{background:#4a2060}}
thead th.th-other{{background:var(--ink-600,#394756)}}
thead th.th-grand{{background:var(--brand-navy-deep)}}
thead tr:first-child th{{top:0;height:34px}}
thead tr:second-child th{{top:34px}}
thead tr:nth-child(2) th{{position:sticky;top:34px;z-index:7;font-size:10px;padding:4px 5px}}
td{{padding:5px 6px;border-bottom:1px solid var(--ink-100);text-align:right;font-family:var(--font-mono);font-size:11px}}
td.pin{{text-align:left;font-family:var(--font-sans);position:sticky;left:0;background:inherit;z-index:5;min-width:200px;border-right:2px solid var(--ink-200)}}
tr:hover td{{background:var(--gold-100)}}
tr.sc-row td{{background:var(--navy-100)!important;font-weight:700;border-top:2px solid var(--brand-navy)}}
tr.sc-row:hover td{{background:var(--navy-200)!important}}
td.na{{color:var(--ink-300);font-style:italic}}
td.z{{color:var(--ink-300)}}
td.neg{{color:var(--danger-fg)!important}}
td.c-local{{background:rgba(45,90,75,.04)}}
td.c-ltot{{background:rgba(45,90,75,.10);font-weight:700}}
td.c-state{{background:rgba(29,61,107,.04)}}
td.c-stot{{background:rgba(29,61,107,.10);font-weight:700}}
td.c-fed{{background:rgba(74,32,96,.06)}}
td.c-other{{background:rgba(57,71,86,.05)}}
td.c-grand{{background:var(--gold-100);font-weight:700}}
.dname{{font-weight:600;font-size:12px}}
.did{{font-size:10px;color:var(--ink-400)}}
.cbadge{{display:inline-block;font-size:9px;padding:1px 6px;border-radius:var(--r-full);margin-left:5px;font-weight:700;vertical-align:middle}}
.cb-warn{{background:var(--warning-bg);color:var(--warning-fg)}}
.cb-jasp{{background:var(--danger-bg);color:var(--danger-fg)}}
.cb-note{{background:var(--info-bg);color:var(--info-fg)}}
.sort-ic{{font-size:9px;margin-left:3px;opacity:.7}}
.var-tbl{{width:100%;border-collapse:collapse;font-size:11px;margin-top:8px}}
.var-tbl th,.var-tbl td{{padding:4px 8px;text-align:right;border:1px solid var(--ink-200)}}
.var-tbl th{{background:var(--ink-100);font-weight:600;text-align:left}}
.var-tbl td:first-child{{text-align:left}}
</style>
</head>
<body>

<div class="page-header">
  <h1>FY2024 District Revenue Comparison <span class="badge">compare-table</span></h1>
  <div class="sub">South Carolina Department of Education &bull; Fiscal Year 2024 &bull; SY2024 Headcount &bull; Per-Pupil Values</div>
</div>

<div class="summary-bar" id="summaryBar"></div>

<div class="controls">
  <div><label>Search:</label><input id="srch" placeholder="District name or ID" style="width:180px"/></div>
  <div><label>Sort by:</label>
    <select id="sortSel">
      <option value="name">Name</option>
      <option value="headcount">Headcount</option>
      <option value="grand_total">Grand Total</option>
      <option value="state_total_sceis">State Total (SCEIS)</option>
      <option value="federal_total_sceis">Federal Total (SCEIS)</option>
      <option value="local_total">Local Total</option>
      <option value="local_sac_req">Local SAC Required</option>
    </select>
  </div>
  <div><label>Order:</label>
    <select id="ordSel"><option value="asc">Ascending</option><option value="desc">Descending</option></select>
  </div>
  <div><label>Values:</label>
    <select id="ppSel"><option value="pp">Per-Pupil ($)</option><option value="raw">Raw Dollars ($)</option></select>
  </div>
  <button class="btn-reset" onclick="reset()">Reset</button>
  <span class="hint">Click column headers to sort &bull; Hover column/bucket names for definitions</span>
</div>

<div class="table-wrap">
<table id="tbl">
<thead>
<tr>
  <th rowspan="2" class="pin" onclick="sortBy('name')" style="text-align:left;z-index:20;min-width:210px">
    District <span class="sort-ic" id="si-name">&#9650;</span>
  </th>
  <th rowspan="2" onclick="sortBy('headcount')" style="min-width:72px">
    SY2024<br>Headcount<br><span class="sort-ic" id="si-headcount"></span>
  </th>
  <th colspan="4" class="th-local"
    data-tippy-content="LOCAL REVENUE (LEA-sourced, Reported_Flag=TRUE): Taxes levied by the LEA (11xx), payments from non-LEA governmental units (12xx), tuition &amp; transport fees, food services, pupil activities, investments (15xx), and miscellaneous local sources. Revenue codes 1xxx and 2xxx. Sub-bucket definitions: SAC Required = 11xx | Additional = 12xx + misc 1900s | District Services = 13xx/14xx/16xx/17xx/191x/1930-31/1992 | Investments = 15xx.">
    Local Revenue (LEA-sourced)
  </th>
  <th colspan="4" class="th-state"
    data-tippy-content="STATE REVENUE: Sub-buckets (SAC, PropTax, Other) are LEA-sourced from lea_revenues. State TOTAL column is SCEIS-sourced from vw_sceis_fi_payments_classified (Funding_Stream='State'). Sub-buckets will not sum to SCEIS Total — this is the disclosed internal inconsistency. See footer.">
    State Revenue
  </th>
  <th rowspan="2" class="th-fed" onclick="sortBy('federal_total_sceis')" style="min-width:90px"
    data-tippy-content="FEDERAL TOTAL (SCEIS-sourced): Sum of all FI Payment rows with Funding_Stream='Federal' for this district in FY2024. Includes ESEA/ESSA (Title I-IV), IDEA, USDA Child Nutrition, ARP/ESSER programs. Per-Revenue_Code SCEIS attribution not available (lookup_gl_account is empty). Sub-bucket detail available from LEA lea_revenues (4xxx codes).">
    Federal Total<br>(SCEIS)<br><span class="sort-ic" id="si-federal_total_sceis"></span>
  </th>
  <th rowspan="2" class="th-other" onclick="sortBy('other_sources')" style="min-width:90px"
    data-tippy-content="OTHER SOURCES (LEA-sourced, 5xxx codes): Bond proceeds, interfund transfers, proceeds of long-term notes, capital leases. Not operational revenue. Included in Grand Total per LARS/SCEIS reporting convention.">
    Other Sources<br>(5xxx)<br><span class="sort-ic" id="si-other_sources"></span>
  </th>
  <th rowspan="2" class="th-grand" onclick="sortBy('grand_total')" style="min-width:95px"
    data-tippy-content="GRAND TOTAL = Local Total (LEA) + State Total (SCEIS) + Federal Total (SCEIS) + Other Sources (LEA). Mixed sourcing as disclosed. Statewide row is weighted average.">
    Grand Total<br><span class="sort-ic" id="si-grand_total"></span>
  </th>
</tr>
<tr>
  <th class="th-local" onclick="sortBy('local_sac_req')" style="min-width:88px"
    data-tippy-content="LOCAL SAC REQUIRED (LEA-sourced): Ad valorem taxes levied by the school district as required by the State Aid to Classrooms formula. Revenue codes 1110 (Ad Valorem), 1140 (Penalties &amp; Interest on Taxes), 1190 (Other Taxes). Fiscally independent districts only.">
    SAC Req.<br>(11xx)<br><span class="sort-ic" id="si-local_sac_req"></span>
  </th>
  <th class="th-local" onclick="sortBy('local_additional')" style="min-width:88px"
    data-tippy-content="LOCAL ADDITIONAL (LEA-sourced): Taxes from non-LEA governmental units (12xx), intergovernmental revenue (2xxx), private sources (1920), refunds of prior-year expenditures (1950), miscellaneous local (1990, 1999) and insurance/legal settlement proceeds (1993, 1994). Fiscally dependent districts typically report all local taxes here.">
    Additional<br>(12xx+misc)<br><span class="sort-ic" id="si-local_additional"></span>
  </th>
  <th class="th-local" onclick="sortBy('local_dist_svc')" style="min-width:88px"
    data-tippy-content="LOCAL DISTRICT SERVICES (LEA-sourced): Revenue from tuition (13xx), transportation fees (14xx), food services (16xx), pupil activities (17xx), rentals (1910), special needs transportation/Medicaid (1930-31), and canteen operations (1992).">
    District Svcs<br>(fees/food/activ.)<br><span class="sort-ic" id="si-local_dist_svc"></span>
  </th>
  <th class="th-local" onclick="sortBy('local_investments')" style="min-width:82px"
    data-tippy-content="LOCAL INVESTMENTS (LEA-sourced): Interest on investments (1510), dividends (1520), gain/loss on sale of investments (1530). Revenue codes 15xx.">
    Investments<br>(15xx)<br><span class="sort-ic" id="si-local_investments"></span>
  </th>
  <th class="th-state" onclick="sortBy('state_sac')" style="min-width:88px"
    data-tippy-content="STATE AID TO CLASSROOMS (LEA-sourced sub-bucket): Revenue codes 3103 (State Aid GF), 3103H (Health Insurance component), 3503 (State Aid EIA). This sub-bucket is LEA-reported and may not equal what SCEIS disbursed. See State Total column for SCEIS figure.">
    SAC<br>(3103/3503)<br><span class="sort-ic" id="si-state_sac"></span>
  </th>
  <th class="th-state" onclick="sortBy('state_proptax')" style="min-width:88px"
    data-tippy-content="STATE PROPERTY TAX REIMBURSEMENTS (LEA-sourced sub-bucket): Revenue codes 38xx — Local Residential Property Tax Relief (3810), Homestead Exemption (3820), Property Tax Relief (3825), $2.5M Tax Bonus (3827), Merchant's Inventory Tax (3830), Manufacturer's Depreciation (3840), Other State Property Tax (3890). LEA-sourced.">
    Prop. Tax<br>Reimb. (38xx)<br><span class="sort-ic" id="si-state_proptax"></span>
  </th>
  <th class="th-state" onclick="sortBy('state_other')" style="min-width:88px"
    data-tippy-content="STATE OTHER (LEA-sourced sub-bucket): All other 3xxx state revenue codes — restricted grants (31xx), unrestricted state (32xx), EIA programs (35xx), lottery (36xx), and other state sources (39xx). Excludes SAC (3103/3503) and PropTax (38xx). LEA-sourced.">
    Other<br>(3xxx rem.)<br><span class="sort-ic" id="si-state_other"></span>
  </th>
  <th class="th-state" onclick="sortBy('state_total_sceis')" style="min-width:90px;font-weight:800;background:#1a3560"
    data-tippy-content="STATE TOTAL (SCEIS-sourced): Sum of all FI Payment rows with Funding_Stream='State' from vw_sceis_fi_payments_classified for this district in FY2024. This is the authoritative figure for State revenue. The three sub-buckets to the left are LEA-sourced and will not sum to this total — the gap is the disclosed internal inconsistency.">
    TOTAL<br>(SCEIS)<br><span class="sort-ic" id="si-state_total_sceis"></span>
  </th>
</tr>
</thead>
<tbody id="tbody"></tbody>
</table>
</div>

<div style="background:#fff;border-top:1px solid var(--ink-200);padding:var(--s-4) var(--s-6);">
  <strong style="color:var(--ink-700);font-size:12px;">Top 5 Districts by Absolute State-Bucket Variance (SCEIS State Total minus LEA Sub-bucket Sum)</strong>
  <table class="var-tbl" style="margin-top:8px;max-width:800px">
    <thead><tr><th>District</th><th>SCEIS State Total</th><th>LEA Sub-bucket Sum</th><th>Variance (neg = LEA &gt; SCEIS)</th></tr></thead>
    <tbody>{var_rows}</tbody>
  </table>
  <p style="font-size:10px;color:var(--ink-400);margin-top:6px;">Negative variance means LEA self-reported sub-bucket sum exceeds SCEIS disbursements. Common causes: timing differences, on-behalf payments booked by SCEIS differently than LEA recognizes them, and reclassification of PEBA/retiree insurance amounts.</p>
</div>

{FOOTER_COMMON}

<script>
const DATA = {rows_js};
const SC = {sc_js};
const COLS = ['local_sac_req','local_additional','local_dist_svc','local_investments',
              'state_sac','state_proptax','state_other','state_total_sceis',
              'federal_total_sceis','other_sources','grand_total'];
const CCLS = {{
  local_sac_req:'c-local',local_additional:'c-local',local_dist_svc:'c-local',local_investments:'c-local',
  state_sac:'c-state',state_proptax:'c-state',state_other:'c-state',state_total_sceis:'c-stot',
  federal_total_sceis:'c-fed',other_sources:'c-other',grand_total:'c-grand'
}};
let sortCol='name',sortAsc=true,ppMode=true;
function $(id){{return document.getElementById(id);}}
function fmt(v){{
  if(v===null||v===undefined)return '<span class="na">n/a</span>';
  const n=Math.round(v);
  if(n===0)return '<span class="z">$0</span>';
  if(n<0)return '<span style="color:var(--danger-fg);">$('+Math.abs(n).toLocaleString('en-US')+')</span>';
  return '$'+n.toLocaleString('en-US');
}}
function pp(raw,hc){{return(hc&&hc>0)?raw/hc:null;}}
function renderCell(d,col){{
  const cls=CCLS[col]||'';
  if(ppMode&&!d.headcount)return`<td class="${{cls}} na">n/a</td>`;
  const val=ppMode?pp(d[col],d.headcount):d[col];
  if(val===null)return`<td class="${{cls}} na">n/a</td>`;
  const n=Math.round(val);
  if(n===0)return`<td class="${{cls}} z">$0</td>`;
  if(n<0)return`<td class="${{cls}} neg" style="color:var(--danger-fg);">$(${{Math.abs(n).toLocaleString('en-US')}})</td>`;
  return`<td class="${{cls}}">$${{n.toLocaleString('en-US')}}</td>`;
}}
function badge(d){{
  if(d.id==='2701')return' <span class="cbadge cb-jasp" data-tippy-content="Jasper 01: Reported_Flag=FALSE for all FY2024 rows. LEA data unavailable. SCEIS totals: State $15,840,593 | Federal $11,037,318. Only SCEIS-sourced columns show values; sub-buckets are $0.">NOT REPORTED</span>';
  if(d.id==='0601')return' <span class="cbadge cb-note" data-tippy-content="Barnwell 01: FY2024 revenue consolidated from Barnwell 45 (0645) + Barnwell 48 (0648) per merger rule. Headcount: Barnwell 01 SY2024 (3,123).">MERGED</span>';
  return'';
}}
function renderSCRow(){{
  const hc=SC.headcount;
  let h='<tr class="sc-row"><td class="pin"><span class="dname">South Carolina Total</span><br><span class="did">Weighted Average &mdash; '+hc.toLocaleString('en-US')+' students</span></td>';
  h+='<td style="text-align:right">'+hc.toLocaleString('en-US')+'</td>';
  for(const col of COLS){{
    const cls=CCLS[col]||'';
    const val=ppMode?pp(SC[col],hc):SC[col];
    if(val===null){{h+=`<td class="${{cls}} na">n/a</td>`;continue;}}
    const n=Math.round(val);
    if(n===0){{h+=`<td class="${{cls}} z">$0</td>`;continue;}}
    if(n<0){{h+=`<td class="${{cls}} neg" style="color:var(--danger-fg);">$(${{Math.abs(n).toLocaleString('en-US')}})</td>`;continue;}}
    h+=`<td class="${{cls}}">$${{n.toLocaleString('en-US')}}</td>`;
  }}
  return h+'</tr>';
}}
function render(){{
  const q=$('srch').value.toLowerCase().trim();
  let rows=[...DATA];
  if(q)rows=rows.filter(d=>d.name.toLowerCase().includes(q)||d.id.includes(q));
  const col=sortCol,asc=sortAsc;
  rows.sort((a,b)=>{{
    let va,vb;
    if(col==='name'){{va=a.name;vb=b.name;return asc?va.localeCompare(vb):vb.localeCompare(va);}}
    if(col==='headcount'){{va=a.headcount??-1;vb=b.headcount??-1;}}
    else{{va=a[col]??-1;vb=b[col]??-1;}}
    return asc?va-vb:vb-va;
  }});
  let html=renderSCRow();
  for(const d of rows){{
    html+=`<tr data-id="${{d.id}}"><td class="pin"><span class="dname">${{d.name}}</span>${{badge(d)}}<br><span class="did">${{d.id}}</span></td>`;
    const hcD=d.headcount!==null?d.headcount.toLocaleString('en-US'):'<span class="na">n/a</span>';
    html+=`<td style="text-align:right">${{hcD}}</td>`;
    for(const col of COLS)html+=renderCell(d,col);
    html+='</tr>';
  }}
  $('tbody').innerHTML=html;
  {TIPPY_INIT}
}}
function sortBy(col){{
  if(sortCol===col)sortAsc=!sortAsc;else{{sortCol=col;sortAsc=(col==='name');}}
  $('sortSel').value=col;$('ordSel').value=sortAsc?'asc':'desc';updateIcons();render();
}}
function updateIcons(){{
  ['name','headcount','local_sac_req','local_additional','local_dist_svc','local_investments',
   'state_sac','state_proptax','state_other','state_total_sceis','federal_total_sceis','other_sources','grand_total']
  .forEach(id=>{{const e=$('si-'+id);if(e)e.innerHTML='';}} );
  const e=$('si-'+sortCol);if(e)e.innerHTML=sortAsc?'&#9650;':'&#9660;';
}}
function reset(){{
  $('srch').value='';$('sortSel').value='name';$('ordSel').value='asc';$('ppSel').value='pp';
  sortCol='name';sortAsc=true;ppMode=true;updateIcons();render();buildSummary();
}}
function buildSummary(){{
  const hc=SC.headcount;
  const f=v=>'$'+Math.round(v/hc).toLocaleString('en-US');
  $('summaryBar').innerHTML=`
    <div class="chip"><div class="val">${{(SC.grand_total/1e9).toFixed(3)}}B</div><div class="lbl">FY2024 Total Revenue</div></div>
    <div class="chip"><div class="val">${{hc.toLocaleString('en-US')}}</div><div class="lbl">SY2024 Valid Headcount</div></div>
    <div class="chip"><div class="val">${{f(SC.grand_total)}}</div><div class="lbl">Wtd Avg Per-Pupil Total</div></div>
    <div class="chip"><div class="val">${{f(SC.local_total)}}</div><div class="lbl">Per-Pupil Local (LEA)</div></div>
    <div class="chip"><div class="val">${{f(SC.state_total_sceis)}}</div><div class="lbl">Per-Pupil State (SCEIS)</div></div>
    <div class="chip"><div class="val">${{f(SC.federal_total_sceis)}}</div><div class="lbl">Per-Pupil Federal (SCEIS)</div></div>
    <div class="chip"><div class="val warn">${{f(SC.other_sources)}}</div><div class="lbl">Per-Pupil Other (5xxx)</div></div>
    <div class="chip"><div class="val">77</div><div class="lbl">Districts (excl. excl. entities)</div></div>`;
}}
$('srch').addEventListener('input',render);
$('sortSel').addEventListener('change',function(){{sortCol=this.value;render();}});
$('ordSel').addEventListener('change',function(){{sortAsc=this.value==='asc';render();}});
$('ppSel').addEventListener('change',function(){{ppMode=this.value==='pp';render();}});
buildSummary();updateIcons();render();
</script>
</body></html>"""
    return html


# ═══════════════════════════════════════════════════════════════
# REPORT 2 — compare-chart (stacked bar)
# ═══════════════════════════════════════════════════════════════

def build_compare_chart():
    # Prepare chart data — filter to districts with valid headcount, sort by grand_total pp desc
    chart_rows = [d for d in DATA_ROWS if d['headcount'] and d['headcount'] > 0]
    chart_rows.sort(key=lambda d: d['grand_total']/d['headcount'], reverse=True)

    # Build per-pupil segment data for each district
    segments = ['state_sac','state_proptax','state_other',
                'local_sac_req','local_additional','local_dist_svc','local_investments',
                'federal_total_sceis']
    seg_labels = {
        'state_sac': 'State Aid to Classrooms',
        'state_proptax': 'State Prop. Tax Reimb.',
        'state_other': 'State Other',
        'local_sac_req': 'Local SAC Required',
        'local_additional': 'Local Additional',
        'local_dist_svc': 'Local District Services',
        'local_investments': 'Local Investments',
        'federal_total_sceis': 'Federal (SCEIS)'
    }
    seg_colors = {
        'state_sac': '#1d3d6b',
        'state_proptax': '#2a5aa0',
        'state_other': '#4478c4',
        'local_sac_req': '#1b6b43',
        'local_additional': '#2e9e65',
        'local_dist_svc': '#52c490',
        'local_investments': '#90dfc0',
        'federal_total_sceis': '#6b2d6b'
    }
    seg_tips = {
        'state_sac': 'State Aid to Classrooms (LEA-sourced sub-bucket): codes 3103, 3103H, 3503. LEA-reported; may differ from SCEIS total.',
        'state_proptax': 'State Property Tax Reimbursements (LEA-sourced sub-bucket): codes 38xx. Homestead, PTR, Merchant&apos;s Inv., Manufacturer&apos;s Depreciation.',
        'state_other': 'State Other (LEA-sourced sub-bucket): all other 3xxx codes. Restricted grants, EIA, Lottery, PEBA, transportation.',
        'local_sac_req': 'Local SAC Required (LEA-sourced): Ad valorem and related taxes levied by the district. Codes 11xx.',
        'local_additional': 'Local Additional (LEA-sourced): Non-LEA govt taxes (12xx), intergovernmental (2xxx), private sources, misc local.',
        'local_dist_svc': 'Local District Services (LEA-sourced): Tuition, transport fees, food services, pupil activities, Medicaid/SNT. Codes 13xx/14xx/16xx/17xx/191x/193x.',
        'local_investments': 'Local Investments (LEA-sourced): Interest, dividends, investment gain/loss. Codes 15xx.',
        'federal_total_sceis': 'Federal Total (SCEIS-sourced): All FI Payment rows with Funding_Stream=&apos;Federal&apos;. Sub-bucket detail available from LEA 4xxx codes.'
    }

    # Build JS data array
    chart_data = []
    for d in chart_rows[:80]:  # all districts
        hc = d['headcount']
        row = {
            'name': d['name'], 'id': d['id'], 'headcount': hc,
            'grand_total_pp': round(d['grand_total'] / hc),
            'other_sources_pp': round(d['other_sources'] / hc)
        }
        for seg in segments:
            # For state total: use SCEIS but show note
            val = d[seg]
            row[seg + '_pp'] = round(val / hc) if hc else 0
        chart_data.append(row)

    # SC weighted avg
    sc_hc = SC['headcount']
    sc_row = {'name': 'SC Weighted Avg', 'id': 'SC', 'headcount': sc_hc,
              'grand_total_pp': round(SC['grand_total'] / sc_hc),
              'other_sources_pp': round(SC['other_sources'] / sc_hc)}
    for seg in segments:
        sc_row[seg + '_pp'] = round(SC[seg] / sc_hc)

    chart_data_js = json.dumps(chart_data)
    sc_row_js = json.dumps(sc_row)
    seg_labels_js = json.dumps(seg_labels)
    seg_colors_js = json.dumps(seg_colors)
    seg_tips_js = json.dumps(seg_tips)
    segments_js = json.dumps(segments)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>FY2024 District Revenue — Comparison Chart</title>
{GOOGLE_FONTS}
{TIPPY_CDN}
<style>
{TOKENS_CSS}
{TIPPY_THEME_CSS}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--font-sans);font-size:13px;background:var(--ink-50);color:var(--ink-900)}}
.page-header{{background:linear-gradient(135deg,var(--brand-navy) 0%,var(--brand-slate) 100%);color:#fff;padding:20px 28px 16px;border-bottom:4px solid var(--brand-gold)}}
.page-header h1{{font-size:20px;font-weight:700}}
.page-header .sub{{font-size:12px;opacity:.82;margin-top:4px}}
.badge{{display:inline-block;background:var(--brand-gold);color:var(--ink-900);padding:2px 10px;border-radius:var(--r-full);font-size:11px;font-weight:700;margin-left:8px;vertical-align:middle}}
.controls{{background:#fff;border-bottom:1px solid var(--ink-200);padding:10px 28px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}}
.controls label{{font-size:11.5px;color:var(--ink-400);margin-right:4px}}
.controls select{{border:1px solid var(--ink-200);border-radius:var(--r-sm);padding:4px 9px;font-size:12px;font-family:var(--font-sans)}}
.chart-area{{padding:24px 28px;background:#fff;overflow-x:auto}}
.chart-canvas{{position:relative}}
.legend{{display:flex;flex-wrap:wrap;gap:8px 16px;padding:10px 28px;background:#fff;border-top:1px solid var(--ink-100)}}
.leg-item{{display:flex;align-items:center;gap:6px;font-size:11px;cursor:help}}
.leg-swatch{{width:13px;height:13px;border-radius:2px;flex-shrink:0}}
.tooltip-box{{position:absolute;background:var(--navy-800);color:#fff;padding:8px 12px;border-radius:var(--r-md);font-size:11px;pointer-events:none;z-index:100;max-width:220px;line-height:1.5;box-shadow:var(--shadow-3);display:none}}
.note-bar{{background:var(--warning-bg);border-left:4px solid var(--gold-500);padding:10px 20px;font-size:11.5px;color:var(--warning-fg);margin:0 28px 0}}
</style>
</head>
<body>
<div class="page-header">
  <h1>FY2024 District Revenue — Stacked Bar Chart <span class="badge">compare-chart</span></h1>
  <div class="sub">Per-pupil revenue by bucket &bull; SY2024 Headcount denominator &bull; Districts with valid headcount only (77 of 77)</div>
</div>
<div class="note-bar" style="margin-top:0;border-top:none;padding:8px 28px;">
  <strong>Sourcing note:</strong> State sub-buckets (SAC, PropTax, Other) are <em>LEA-sourced</em> from LARS self-reports. Federal Total is <em>SCEIS-sourced</em>. State sub-buckets will not sum to SCEIS State Total — the gap is the disclosed internal inconsistency. Other Sources (5xxx bond proceeds) excluded from chart for clarity.
</div>
<div class="controls">
  <div><label>Sort:</label>
    <select id="sortSel">
      <option value="grand_total_pp">Grand Total (pp)</option>
      <option value="state_total_pp">State Total (LEA sub-buckets, pp)</option>
      <option value="federal_total_sceis_pp">Federal (SCEIS, pp)</option>
      <option value="local_total_pp">Local Total (pp)</option>
      <option value="name">Name (A-Z)</option>
    </select>
  </div>
  <div><label>Order:</label>
    <select id="ordSel"><option value="desc">Descending</option><option value="asc">Ascending</option></select>
  </div>
  <div><label>Top N:</label>
    <select id="topNSel">
      <option value="20">Top 20</option>
      <option value="40">Top 40</option>
      <option value="77" selected>All 77</option>
    </select>
  </div>
</div>
<div class="legend" id="legend"></div>
<div class="chart-area">
  <div class="tooltip-box" id="ttBox"></div>
  <canvas id="chart" style="cursor:crosshair"></canvas>
</div>
{FOOTER_COMMON}
<script>
const DATA = {chart_data_js};
const SC_ROW = {sc_row_js};
const SEGS = {segments_js};
const SEG_LABELS = {seg_labels_js};
const SEG_COLORS = {seg_colors_js};
const SEG_TIPS = {seg_tips_js};

function buildLegend(){{
  const el=document.getElementById('legend');
  el.innerHTML='';
  [...SEGS].reverse().forEach(seg=>{{
    const div=document.createElement('div');
    div.className='leg-item';
    div.setAttribute('data-tippy-content',SEG_TIPS[seg]||'');
    div.innerHTML=`<span class="leg-swatch" style="background:${{SEG_COLORS[seg]}}"></span><span>${{SEG_LABELS[seg]}}</span>`;
    el.appendChild(div);
  }});
}}

let sortKey='grand_total_pp',sortAsc=false,topN=77;

function getRows(){{
  let rows=[...DATA];
  rows.forEach(d=>{{
    d.local_total_pp=(SEGS.slice(3,7).reduce((s,seg)=>s+d[seg+'_pp'],0));
    d.state_total_pp=(SEGS.slice(0,3).reduce((s,seg)=>s+d[seg+'_pp'],0));
  }});
  if(sortKey==='name'){{rows.sort((a,b)=>sortAsc?a.name.localeCompare(b.name):b.name.localeCompare(a.name));}}
  else{{rows.sort((a,b)=>sortAsc?a[sortKey]-b[sortKey]:b[sortKey]-a[sortKey]);}}
  return rows.slice(0,topN);
}}

function drawChart(){{
  const rows=getRows();
  const canvas=document.getElementById('chart');
  const BAR_W=Math.max(10,Math.min(40,Math.floor((window.innerWidth-80)/rows.length)-2));
  const H=440,PAD_L=60,PAD_B=120,PAD_T=20,PAD_R=20;
  const W=PAD_L+rows.length*(BAR_W+2)+PAD_R;
  canvas.width=W;canvas.height=H;
  const ctx=canvas.getContext('2d');
  ctx.clearRect(0,0,W,H);

  // Find max
  const maxVal=Math.max(...rows.map(d=>d.grand_total_pp),1);
  const chartH=H-PAD_B-PAD_T;
  const scale=chartH/maxVal;

  // Grid lines
  ctx.strokeStyle='#e5e7eb';ctx.lineWidth=1;
  const ticks=5;
  for(let i=0;i<=ticks;i++){{
    const y=PAD_T+chartH-(i/ticks*chartH);
    ctx.beginPath();ctx.moveTo(PAD_L,y);ctx.lineTo(W-PAD_R,y);ctx.stroke();
    ctx.fillStyle='#8a96a3';ctx.font='10px Poppins,sans-serif';ctx.textAlign='right';
    ctx.fillText('$'+Math.round(maxVal*i/ticks).toLocaleString('en-US'),PAD_L-4,y+3);
  }}

  // Bars
  rows.forEach((d,i)=>{{
    const x=PAD_L+i*(BAR_W+2);
    let y=PAD_T+chartH;
    [...SEGS].forEach(seg=>{{
      const ppv=d[seg+'_pp']||0;
      if(ppv<=0)return;
      const bh=Math.max(1,ppv*scale);
      y-=bh;
      ctx.fillStyle=SEG_COLORS[seg];
      ctx.fillRect(x,y,BAR_W,bh);
    }});
    // Label
    ctx.save();ctx.translate(x+BAR_W/2,PAD_T+chartH+6);ctx.rotate(-Math.PI/3);
    ctx.fillStyle='#394756';ctx.font='9px Poppins,sans-serif';ctx.textAlign='right';
    ctx.fillText(d.name.replace(' ',' ').slice(0,18),0,0);ctx.restore();
  }});

  // Hover detection
  canvas.onmousemove=function(e){{
    const rect=canvas.getBoundingClientRect();
    const mx=e.clientX-rect.left,my=e.clientY-rect.top;
    const tt=document.getElementById('ttBox');
    let found=false;
    rows.forEach((d,i)=>{{
      const x=PAD_L+i*(BAR_W+2);
      if(mx>=x&&mx<=x+BAR_W&&my>=PAD_T&&my<=PAD_T+chartH){{
        found=true;
        let html='<strong>'+d.name+'</strong><br>';
        html+='Headcount: '+d.headcount.toLocaleString('en-US')+'<br>';
        [...SEGS].reverse().forEach(seg=>{{
          const ppv=d[seg+'_pp']||0;
          if(ppv>0)html+=SEG_LABELS[seg]+': $'+ppv.toLocaleString('en-US')+'/pp<br>';
        }});
        html+='<strong>Grand Total: $'+d.grand_total_pp.toLocaleString('en-US')+'/pp</strong>';
        tt.innerHTML=html;
        tt.style.display='block';
        tt.style.left=(x+BAR_W+4)+'px';
        tt.style.top=Math.max(PAD_T,(my-60))+'px';
      }}
    }});
    if(!found)tt.style.display='none';
  }};
  canvas.onmouseleave=function(){{document.getElementById('ttBox').style.display='none';}};
}}

function $(id){{return document.getElementById(id);}}
$('sortSel').addEventListener('change',function(){{sortKey=this.value;drawChart();}});
$('ordSel').addEventListener('change',function(){{sortAsc=this.value==='asc';drawChart();}});
$('topNSel').addEventListener('change',function(){{topN=parseInt(this.value);drawChart();}});

buildLegend();
drawChart();
window.addEventListener('resize',drawChart);
setTimeout(()=>{{
  tippy('.leg-item',{{theme:'scde',animation:'shift-away',allowHTML:true,
    trigger:'mouseenter focus',touch:['hold',500],maxWidth:320}});
}},100);
</script>
</body></html>"""
    return html


# ═══════════════════════════════════════════════════════════════
# REPORT 3,4,5 — detail mode
# ═══════════════════════════════════════════════════════════════

def build_detail_report(district_id, district_name, detail_rows, headcount,
                        sceis_state, sceis_federal, reported_flag_ok, is_jasper=False):
    """Build a single detail report HTML."""

    # Organize rows by stream hierarchy
    # Stream order: Local, State, Federal, Other/Unclassified
    stream_order = ['Local', 'State', 'Federal', 'Unclassified']

    # Group rows
    by_stream = defaultdict(list)
    for row in detail_rows:
        stream = row[1]  # Stream_Type
        if stream not in stream_order:
            stream = 'Unclassified'
        by_stream[stream].append(row)

    # Compute totals from LEA rows (Reported_Flag=TRUE only)
    def sum_stream(stream_rows, filter_reported=True):
        total = 0
        for row in stream_rows:
            rf = row[6]  # Reported_Flag
            if filter_reported and not rf:
                continue
            amt = row[5]
            if amt:
                total += float(amt)
        return total

    lea_local = sum_stream(by_stream['Local'])
    lea_state = sum_stream(by_stream['State'])
    lea_federal = sum_stream(by_stream['Federal'])
    lea_other = sum_stream(by_stream['Unclassified'])
    lea_grand = lea_local + lea_state + lea_federal + lea_other

    # State sub-bucket sums (LEA)
    state_sac_total = 0.0
    state_proptax_total = 0.0
    state_other_total = 0.0
    for row in by_stream['State']:
        if not row[6]:
            continue
        code = row[0]
        amt = float(row[5]) if row[5] else 0.0
        if code in ('3103','3103H','3503'):
            state_sac_total += amt
        elif code.startswith('38'):
            state_proptax_total += amt
        else:
            state_other_total += amt

    state_variance = sceis_state - lea_state
    fed_variance = sceis_federal - lea_federal
    state_pct = (state_variance / sceis_state * 100) if sceis_state else 0

    def fmt(v):
        if v is None:
            return '$0'
        n = round(float(v))
        if n == 0:
            return '$0'
        if n < 0:
            return f'$({abs(n):,})'
        return f'${n:,}'

    def fmt_row_amt(v, reported):
        if not reported:
            return '<td class="amt not-reported">—</td>'
        if v is None:
            return '<td class="amt zero">$0</td>'
        n = round(float(v))
        if n == 0:
            return '<td class="amt zero">$0</td>'
        if n < 0:
            return f'<td class="amt neg" style="color:var(--danger-fg);">${{abs(n):,}}</td>'.replace('{{','').replace('}}','')
        return f'<td class="amt">${n:,}</td>'

    # Build table rows HTML
    table_rows_html = ''

    if is_jasper:
        # Jasper: show "Not reported" body, then SCEIS summary
        table_rows_html += f"""
<tr class="stream-hdr"><td colspan="4">LOCAL REVENUE (1xxx / 2xxx)</td></tr>
<tr class="not-reported-msg"><td colspan="4">
  <span class="badge-warn">NOT REPORTED</span>
  Jasper 01 has <code>Reported_Flag=FALSE</code> for all FY2024 revenue rows. LEA LARS self-report data is unavailable for this district and fiscal year. Local sub-bucket detail cannot be shown.
</td></tr>
<tr class="stream-hdr"><td colspan="4">STATE REVENUE (3xxx) — SCEIS Aggregate Only</td></tr>
<tr class="not-reported-msg"><td colspan="4">
  <span class="badge-warn">NOT REPORTED</span>
  LEA state sub-bucket detail unavailable (Reported_Flag=FALSE). SCEIS-sourced State Total shown below.
</td></tr>
<tr class="subtotal-row">
  <td colspan="3" class="subtotal-lbl">State Total (SCEIS-sourced, vw_sceis_fi_payments_classified)</td>
  <td class="amt">{fmt(sceis_state)}</td>
</tr>
<tr class="stream-hdr"><td colspan="4">FEDERAL REVENUE (4xxx) — SCEIS Aggregate Only</td></tr>
<tr class="not-reported-msg"><td colspan="4">
  <span class="badge-warn">NOT REPORTED</span>
  LEA federal sub-bucket detail unavailable. SCEIS-sourced Federal Total shown below.
</td></tr>
<tr class="subtotal-row">
  <td colspan="3" class="subtotal-lbl">Federal Total (SCEIS-sourced, vw_sceis_fi_payments_classified)</td>
  <td class="amt">{fmt(sceis_federal)}</td>
</tr>
<tr class="grand-total-row">
  <td colspan="3" class="subtotal-lbl">GRAND TOTAL (SCEIS State + SCEIS Federal — no local/other data)</td>
  <td class="amt">{fmt(sceis_state + sceis_federal)}</td>
</tr>"""
    else:
        # Normal: render full hierarchy
        for stream in ['Local', 'State', 'Federal', 'Unclassified']:
            rows = by_stream[stream]
            if not rows:
                continue
            stream_label = {'Local': 'LOCAL REVENUE (1xxx / 2xxx)',
                            'State': 'STATE REVENUE (3xxx)',
                            'Federal': 'FEDERAL REVENUE (4xxx)',
                            'Unclassified': 'OTHER SOURCES & TRANSFERS (5xxx / Historical)'}[stream]
            table_rows_html += f'<tr class="stream-hdr"><td colspan="4">{stream_label}</td></tr>\n'

            # Group by Rollup_Level
            current_level2 = None
            current_level1 = None
            stream_total = 0.0

            for row in rows:
                code = row[0]
                rl = row[2]  # Rollup_Level
                title = row[3]
                short_desc = row[4] or ''
                amt = row[5]
                reported = row[6]
                amt_f = float(amt) if amt else 0.0

                # Escape for HTML attribute
                tip_content = short_desc.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')[:300]
                if not tip_content:
                    tip_content = title.replace('"', '&quot;') if title else code

                if rl == 1:
                    current_level1 = code
                    table_rows_html += f'<tr class="level1-hdr"><td class="code-col"><span class="code-badge" data-tippy-content="{tip_content}">{code}</span></td><td colspan="3" class="title-col">{title or code}</td></tr>\n'
                elif rl == 2:
                    current_level2 = code
                    table_rows_html += f'<tr class="level2-hdr"><td class="code-col"><span class="code-badge" data-tippy-content="{tip_content}">{code}</span></td><td colspan="3" class="title-col">{title or code}</td></tr>\n'
                elif rl == 3:
                    stream_total += amt_f if reported else 0
                    table_rows_html += f'<tr class="level3-row"><td class="code-col"><span class="code-badge" data-tippy-content="{tip_content}">{code}</span></td><td class="title-col">{title or code}</td><td class="desc-col">{short_desc[:80]}</td>{fmt_row_amt(amt, reported)}</tr>\n'
                elif rl == 4:
                    stream_total += amt_f if reported else 0
                    table_rows_html += f'<tr class="level4-row"><td class="code-col"><span class="code-badge" data-tippy-content="{tip_content}">{code}</span></td><td class="title-col">{title or code}</td><td class="desc-col">{short_desc[:80]}</td>{fmt_row_amt(amt, reported)}</tr>\n'
                else:
                    # Unclassified / level 99
                    if amt_f != 0 or amt is not None:
                        stream_total += amt_f if reported else 0
                        table_rows_html += f'<tr class="level3-row unclass"><td class="code-col"><span class="code-badge" data-tippy-content="{tip_content}">{code}</span></td><td class="title-col">{title or code}</td><td class="desc-col">{short_desc[:80]}</td>{fmt_row_amt(amt, reported)}</tr>\n'

            # Stream subtotal
            stream_label_short = {'Local': 'Local', 'State': 'State (LEA sub-buckets)',
                                   'Federal': 'Federal (LEA)', 'Unclassified': 'Other Sources'}[stream]
            table_rows_html += f'<tr class="subtotal-row"><td colspan="3" class="subtotal-lbl">Subtotal — {stream_label_short}</td><td class="amt">{fmt(stream_total)}</td></tr>\n'

            # For State: also show SCEIS total and variance
            if stream == 'State':
                var_cls = 'neg' if state_variance < 0 else 'pos'
                var_note = 'LEA sub-bucket sum exceeds SCEIS (over-report by LEA)' if state_variance < 0 else 'SCEIS exceeds LEA sub-bucket sum'
                table_rows_html += f"""<tr class="sceis-row">
  <td colspan="3" class="subtotal-lbl">State Total — SCEIS-sourced (vw_sceis_fi_payments_classified)</td>
  <td class="amt">{fmt(sceis_state)}</td>
</tr>
<tr class="variance-row">
  <td colspan="3" class="subtotal-lbl" style="color:var(--danger-fg);font-style:italic;">
    Internal inconsistency: SCEIS minus LEA sub-bucket sum ({var_note})
  </td>
  <td class="amt {var_cls}" style="color:var(--danger-fg);">{fmt(state_variance)}</td>
</tr>\n"""

            # For Federal: also show SCEIS total
            if stream == 'Federal':
                table_rows_html += f"""<tr class="sceis-row">
  <td colspan="3" class="subtotal-lbl">Federal Total — SCEIS-sourced (vw_sceis_fi_payments_classified)</td>
  <td class="amt">{fmt(sceis_federal)}</td>
</tr>\n"""

        # Grand total
        grand_sceis = lea_local + sceis_state + sceis_federal + lea_other
        table_rows_html += f'<tr class="grand-total-row"><td colspan="3" class="subtotal-lbl">GRAND TOTAL (Local LEA + State SCEIS + Federal SCEIS + Other LEA)</td><td class="amt">{fmt(grand_sceis)}</td></tr>\n'

    # Build state variance note for footer
    if not is_jasper:
        var_note_html = f"""
<div class="var-box">
  <strong>State-Bucket Internal Inconsistency for {district_name}</strong><br>
  LEA sub-bucket sum (3xxx codes): {fmt(lea_state)}<br>
  SCEIS State Total (FI Payments, Funding_Stream=&apos;State&apos;): {fmt(sceis_state)}<br>
  Variance (SCEIS minus LEA): <span style="color:var(--danger-fg);">{fmt(state_variance)}</span>
  ({state_pct:+.1f}% of SCEIS State Total)<br>
  <em>Common causes: timing differences, PEBA on-behalf recognition, reclassification of retiree insurance, and ESSER close-out adjustments.</em>
</div>"""
    else:
        var_note_html = f"""
<div class="var-box">
  <strong>Jasper 01 — SCEIS-Only Totals</strong><br>
  SCEIS State Total: {fmt(sceis_state)}<br>
  SCEIS Federal Total: {fmt(sceis_federal)}<br>
  LEA self-report: Unavailable (Reported_Flag=FALSE for all FY2024 rows)
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>FY2024 Detail Report — {district_name}</title>
{GOOGLE_FONTS}
{TIPPY_CDN}
<style>
{TOKENS_CSS}
{TIPPY_THEME_CSS}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:var(--font-sans);font-size:12.5px;background:var(--ink-50);color:var(--ink-900);line-height:1.5}}
.page-header{{background:linear-gradient(135deg,var(--brand-navy) 0%,var(--brand-slate) 100%);color:#fff;padding:20px 32px 16px;border-bottom:4px solid var(--brand-gold)}}
.page-header h1{{font-size:22px;font-weight:700}}
.page-header .sub{{font-size:12px;opacity:.82;margin-top:4px}}
.badge{{display:inline-block;background:var(--brand-gold);color:var(--ink-900);padding:2px 10px;border-radius:var(--r-full);font-size:11px;font-weight:700;margin-left:8px;vertical-align:middle}}
.badge-warn{{display:inline-block;background:var(--warning-bg);color:var(--warning-fg);padding:2px 10px;border-radius:var(--r-full);font-size:11px;font-weight:700;margin-right:8px}}
.kpi-bar{{display:flex;gap:12px;flex-wrap:wrap;padding:12px 32px;background:#fff;border-bottom:1px solid var(--ink-200)}}
.kpi{{background:var(--ink-50);border:1px solid var(--ink-200);border-radius:var(--r-lg);padding:8px 16px}}
.kpi .val{{font-size:18px;font-weight:700;color:var(--brand-navy);font-family:var(--font-mono)}}
.kpi .lbl{{font-size:10px;color:var(--ink-400);text-transform:uppercase;letter-spacing:.3px}}
.tbl-wrap{{overflow:auto;max-height:calc(100vh - 220px);padding:16px 32px 32px}}
table{{width:100%;border-collapse:collapse;font-size:11.5px}}
.code-col{{width:88px;white-space:nowrap}}
.title-col{{width:260px}}
.desc-col{{color:var(--ink-500);font-size:10.5px}}
.amt{{text-align:right;font-family:var(--font-mono);font-size:11.5px;white-space:nowrap;width:120px}}
td,th{{padding:4px 8px;border-bottom:1px solid var(--ink-100)}}
.stream-hdr td{{background:var(--brand-navy);color:#fff;font-weight:700;font-size:12px;padding:8px 10px;letter-spacing:.3px;text-transform:uppercase}}
.level1-hdr td{{background:var(--ink-200);font-weight:700;font-size:11.5px;color:var(--ink-700);padding:5px 10px}}
.level2-hdr td{{background:var(--ink-100);font-weight:600;font-size:11px;color:var(--ink-700);padding:4px 14px}}
.level3-row td{{padding:3px 14px}}
.level3-row:hover td{{background:var(--gold-100)}}
.level4-row td{{padding:2px 20px;font-size:11px;color:var(--ink-500)}}
.level4-row:hover td{{background:var(--gold-100)}}
.unclass td{{color:var(--ink-400)}}
.subtotal-row td{{background:var(--navy-100);font-weight:700;border-top:2px solid var(--navy-300);border-bottom:2px solid var(--navy-300);padding:5px 10px}}
.subtotal-lbl{{font-size:11.5px;color:var(--brand-navy)}}
.sceis-row td{{background:var(--info-bg);font-weight:600;border-top:1px solid var(--info-fg);color:var(--info-fg)}}
.variance-row td{{background:var(--danger-bg);font-style:italic;font-size:11px}}
.grand-total-row td{{background:var(--gold-100);font-weight:800;font-size:13px;border-top:3px solid var(--brand-gold);border-bottom:3px solid var(--brand-gold)}}
.not-reported-msg td{{background:var(--warning-bg);color:var(--warning-fg);padding:12px 16px;font-size:12px}}
.zero{{color:var(--ink-300)}}
.not-reported{{color:var(--ink-300);font-style:italic}}
.code-badge{{display:inline-block;background:var(--ink-100);border:1px solid var(--ink-200);border-radius:var(--r-sm);padding:1px 6px;font-family:var(--font-mono);font-size:10px;cursor:help;color:var(--ink-700)}}
.var-box{{background:var(--danger-bg);border-left:4px solid var(--danger-line);padding:12px 16px;border-radius:0 var(--r-md) var(--r-md) 0;margin-bottom:12px;font-size:11.5px;color:var(--danger-fg)}}
</style>
</head>
<body>
<div class="page-header">
  <h1>{district_name} <span class="badge">detail</span> <span class="badge" style="background:var(--brand-slate)">FY2024</span></h1>
  <div class="sub">District ID: {district_id} &bull; Raw Dollars (not per-pupil) &bull; Hierarchical Revenue Detail &bull; SY2024 Headcount: {headcount:,}</div>
</div>
<div class="kpi-bar">
  <div class="kpi"><div class="val">{fmt(lea_local) if not is_jasper else 'N/A'}</div><div class="lbl">Local Revenue (LEA)</div></div>
  <div class="kpi"><div class="val" style="color:var(--info-fg)">{fmt(sceis_state)}</div><div class="lbl">State Total (SCEIS)</div></div>
  <div class="kpi"><div class="val" style="color:#6b2d6b">{fmt(sceis_federal)}</div><div class="lbl">Federal Total (SCEIS)</div></div>
  <div class="kpi"><div class="val" style="color:var(--warning-fg)">{fmt(lea_other) if not is_jasper else 'N/A'}</div><div class="lbl">Other Sources (5xxx)</div></div>
  <div class="kpi"><div class="val" style="color:var(--brand-gold);background:var(--brand-navy);padding:4px 12px;border-radius:var(--r-md)">{fmt(sceis_state + sceis_federal + (lea_local if not is_jasper else 0) + (lea_other if not is_jasper else 0))}</div><div class="lbl">Grand Total</div></div>
  {'<div class="kpi" style="border-color:var(--danger-line)"><div class="val" style="color:var(--danger-fg);font-size:14px">NOT REPORTED</div><div class="lbl">LEA Data Status</div></div>' if is_jasper else ''}
</div>

{var_note_html}

<div class="tbl-wrap">
<table>
<thead>
  <tr style="background:var(--ink-700);color:#fff">
    <th class="code-col">Code</th>
    <th class="title-col">Title</th>
    <th class="desc-col">Description</th>
    <th class="amt">Amount</th>
  </tr>
</thead>
<tbody>
{table_rows_html}
</tbody>
</table>
</div>

{FOOTER_COMMON}

<script>
setTimeout(()=>{{
  tippy('[data-tippy-content]',{{
    theme:'scde',animation:'shift-away',allowHTML:true,
    trigger:'mouseenter focus',touch:['hold',500],maxWidth:360,
    content(r){{return r.getAttribute('data-tippy-content');}}
  }});
}},80);
</script>
</body></html>"""
    return html


# ═══════════════════════════════════════════════════════════════
# MAIN — fetch detail data and render all 5 reports
# ═══════════════════════════════════════════════════════════════

def get_detail_rows(con, district_id):
    r = con.execute("""
        SELECT r.Revenue_Code,
               COALESCE(f.Stream_Type, 'Unclassified') as Stream_Type,
               COALESCE(f.Rollup_Level, 99) as Rollup_Level,
               COALESCE(f.Display_Title, c.Full_Name, h.Full_Name, r.Revenue_Code) as Title,
               COALESCE(c.Short_Description, h.Short_Description, '') as Short_Desc,
               r.Amount,
               r.Reported_Flag
        FROM lea_revenues r
        LEFT JOIN code_district_funding_streams f ON r.Revenue_Code = f.REV_Code
        LEFT JOIN code_accounting_codes c ON r.Revenue_Code = c.Code AND c.Type='Revenue'
        LEFT JOIN code_historical_revenue_codes h ON r.Revenue_Code = h.Code AND h.Type='Revenue'
        WHERE r.District_ID=? AND r.FY=2024
        ORDER BY COALESCE(f.Stream_Type,'Z'), COALESCE(f.Rollup_Level,99), r.Revenue_Code
    """, [district_id]).fetchall()
    return r


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    con = duckdb.connect(DB_PATH, read_only=True)

    # SCEIS totals lookup (Barnwell merger: 0645+0648 → 0601)
    BARNWELL_MERGE_SCEIS = {'0645': '0601', '0648': '0601'}
    sceis_rows = con.execute("""
        SELECT District_ID, Funding_Stream, SUM(Amount) as total
        FROM vw_sceis_fi_payments_classified
        WHERE Fiscal_Year = 2024 AND Funding_Stream IN ('State','Federal')
        GROUP BY District_ID, Funding_Stream
    """).fetchall()
    sceis = defaultdict(lambda: defaultdict(float))
    for did, stream, total in sceis_rows:
        if did:
            target = BARNWELL_MERGE_SCEIS.get(did, did)
            sceis[target][stream] += float(total)

    headcount_rows = con.execute("""
        SELECT District_ID, Total_Active_Enrollment FROM lea_headcounts WHERE SY=2024
    """).fetchall()
    headcounts = {row[0]: row[1] for row in headcount_rows}

    out_files = {}

    # ── Report 1: compare-table ──
    print("Building compare-table...")
    html = build_compare_table()
    p = os.path.join(OUT_DIR, f'district_revenue_compare-table_FY2024_{TIMESTAMP}.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)
    out_files['compare-table'] = p
    print(f"  Written: {p} ({len(html)//1024}KB)")

    # ── Report 2: compare-chart ──
    print("Building compare-chart...")
    html = build_compare_chart()
    p = os.path.join(OUT_DIR, f'district_revenue_compare-chart_FY2024_{TIMESTAMP}.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)
    out_files['compare-chart'] = p
    print(f"  Written: {p} ({len(html)//1024}KB)")

    # ── Report 3: detail Greenville 01 (2301) ──
    print("Building detail Greenville 01...")
    detail_rows = get_detail_rows(con, '2301')
    html = build_detail_report(
        '2301', 'Greenville 01', detail_rows,
        headcounts.get('2301', 0),
        sceis.get('2301',{}).get('State', 0),
        sceis.get('2301',{}).get('Federal', 0),
        reported_flag_ok=True, is_jasper=False
    )
    p = os.path.join(OUT_DIR, f'district_revenue_detail_FY2024_{TIMESTAMP}_2301_Greenville.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)
    out_files['detail-greenville'] = p
    print(f"  Written: {p} ({len(html)//1024}KB)")

    # ── Report 4: detail Jasper 01 (2701) ──
    print("Building detail Jasper 01...")
    detail_rows = get_detail_rows(con, '2701')
    html = build_detail_report(
        '2701', 'Jasper 01', detail_rows,
        headcounts.get('2701', 0),
        sceis.get('2701',{}).get('State', 0),
        sceis.get('2701',{}).get('Federal', 0),
        reported_flag_ok=False, is_jasper=True
    )
    p = os.path.join(OUT_DIR, f'district_revenue_detail_FY2024_{TIMESTAMP}_2701_Jasper.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)
    out_files['detail-jasper'] = p
    print(f"  Written: {p} ({len(html)//1024}KB)")

    # ── Report 5: detail Dillon 04 (1704) ──
    print("Building detail Dillon 04...")
    detail_rows = get_detail_rows(con, '1704')
    html = build_detail_report(
        '1704', 'Dillon 04', detail_rows,
        headcounts.get('1704', 0),
        sceis.get('1704',{}).get('State', 0),
        sceis.get('1704',{}).get('Federal', 0),
        reported_flag_ok=True, is_jasper=False
    )
    p = os.path.join(OUT_DIR, f'district_revenue_detail_FY2024_{TIMESTAMP}_1704_Dillon04.html')
    with open(p, 'w', encoding='utf-8') as f:
        f.write(html)
    out_files['detail-dillon'] = p
    print(f"  Written: {p} ({len(html)//1024}KB)")

    con.close()

    print("\n=== ALL REPORTS COMPLETE ===")
    for mode, path in out_files.items():
        size = os.path.getsize(path)
        print(f"  {mode}: {path} ({size//1024}KB)")

    return out_files

if __name__ == '__main__':
    main()
