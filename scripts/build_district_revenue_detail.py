#!/usr/bin/env python3
"""
build_district_revenue_detail.py — single-district hierarchical revenue
detail HTML dashboard.

Owned by the report-district-revenue agent (detail mode). See
.claude/agents/report-district-revenue.md.

Reads from mart_district_revenue_rollup (already filtered for
Reported_Flag=TRUE and dormancy mask applied), supplemented by a
LEFT JOIN to the full code_district_funding_streams handbook so that
every non-dormant code appears even if its amount is $0.

Emits a single self-contained HTML file styled per SCDE Finance design
system (docs/style/scde-design/).

Run:
  python3 scripts/build_district_revenue_detail.py --district "Aiken 01" --fy 2024
  python3 scripts/build_district_revenue_detail.py --district 0201 --fy 2023
"""

import argparse
import datetime as dt
import html
import os
import sys
from decimal import Decimal

import duckdb

DB_PATH = "db/scde.duckdb"
OUTPUT_DIR = "outputs/reports"

# Style tokens from docs/style/scde-design/tokens.json / style-guide.md
COLORS = {
    "brand_primary":    "#2F3D4C",
    "brand_secondary":  "#234058",
    "brand_tertiary":   "#43718B",
    "brand_accent":     "#F1BA55",
    "danger":           "#B3261E",
    "warning":          "#8A5A00",
    "neutral_fg":       "#454C56",
    "neutral_bg":       "#F5F6F7",
    "border_subtle":    "#E1E3E6",
}

# Stream display ordering
STREAM_ORDER = {"Local": 0, "State": 1, "Federal": 2}


# ---------------------------------------------------------------------------
# Canonical info-button pattern (lifted from build_funding_projection_report.py)
# ---------------------------------------------------------------------------

def code_info_button(code, title, short_desc, full_desc, max_full_chars=600):
    """
    Render a small "i" button next to a Revenue_Code that surfaces
    Short_Description on hover and Full_Description on click via Tippy.js.
    Returns inline HTML; the Tippy init script reads data-* attributes.
    """
    if not short_desc and not full_desc:
        return ""  # no description available — don't show a button at all
    short_part = html.escape(short_desc or "")
    full_part = html.escape(full_desc or "")
    # Truncate Full_Description for the popup body
    if full_part and len(full_part) > max_full_chars:
        full_part = full_part[:max_full_chars].rsplit(" ", 1)[0] + "…"
    title_part = html.escape(title or code)
    code_part = html.escape(code)
    return (
        f'<button class="info-btn" '
        f'data-code="{code_part}" '
        f'data-title="{title_part}" '
        f'data-short="{short_part}" '
        f'data-full="{full_part}" '
        f'aria-label="Show description for code {code_part}">i</button>'
    )


# ---------------------------------------------------------------------------
# Currency formatting
# ---------------------------------------------------------------------------

def fmt_currency(n):
    """Format as $X,XXX. Negatives use accounting parentheses: $(1,234)."""
    if n is None:
        return "n/a"
    n = int(n)
    if n < 0:
        return f"$({-n:,})"
    return f"${n:,}"


def fmt_currency_style(n):
    """Return inline style string for negative amounts."""
    if n is None or int(n) >= 0:
        return ""
    return f"color: {COLORS['danger']};"


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def resolve_district(con, ident):
    """Accepts District_ID or District_Name; returns (district_id, district_name)."""
    row = con.execute("""
        SELECT District_ID, District_Name FROM dim_district
        WHERE District_ID = ? OR District_Name = ?
        LIMIT 1
    """, [ident, ident]).fetchone()
    if row is None:
        sys.exit(f"District not found: {ident!r}")
    return row[0], row[1]


def fetch_reported_flag(con, district_id, fy):
    """Check whether the district reported for this FY."""
    row = con.execute("""
        SELECT MAX(CAST(Reported_Flag AS INTEGER))
        FROM lea_revenues
        WHERE District_ID = ? AND FY = ?
    """, [district_id, fy]).fetchone()
    if row is None or row[0] is None:
        return None   # no rows at all
    return bool(row[0])


def fetch_revenue_rows(con, district_id, fy):
    """
    Pull the full hierarchical revenue listing for a district + FY.

    Strategy:
      - Use mart_district_revenue_rollup as the primary source (already
        filtered for Reported_Flag=TRUE and dormancy mask applied).
      - Add any non-dormant handbook codes absent from the mart with Amount=0
        so the requirement "show every code even if $0" is satisfied.
      - Join code_accounting_codes for Full_Name / Display_Name / descriptions.

    Returns a list of dicts with keys:
        Revenue_Code, Stream_Type, Rollup_Level, Category, Display_Title,
        Amount, Full_Name, Display_Name, Short_Description, Full_Description
    """
    # Fetch all mart rows for this district+FY (includes rollup headers with NULL amount)
    mart_rows = con.execute("""
        SELECT
            m.Revenue_Code,
            m.Stream_Type,
            m.Rollup_Level,
            m.Category,
            m.Display_Title,
            m.Amount,
            a.Full_Name,
            a.Display_Name,
            a.Short_Description,
            a.Full_Description
        FROM mart_district_revenue_rollup m
        LEFT JOIN code_accounting_codes a
            ON a.Code = m.Revenue_Code AND a.Type = 'Revenue'
        WHERE m.District_ID = ? AND m.FY = ?
        ORDER BY m.Stream_Type, m.Rollup_Level, m.Revenue_Code
    """, [district_id, fy]).fetchall()

    # Build a set of codes already present
    mart_codes = {r[0] for r in mart_rows}

    # Fetch non-dormant handbook codes NOT in the mart for this district+FY
    # (only leaf codes — Rollup_Level 3 and 4)
    gap_rows = con.execute("""
        SELECT
            fs.REV_Code,
            fs.Stream_Type,
            fs.Rollup_Level,
            fs.Category,
            fs.Display_Title,
            CAST(0 AS DECIMAL(18,2)) AS Amount,
            a.Full_Name,
            a.Display_Name,
            a.Short_Description,
            a.Full_Description
        FROM code_district_funding_streams fs
        LEFT JOIN code_accounting_codes a
            ON a.Code = fs.REV_Code AND a.Type = 'Revenue'
        JOIN vw_revenue_code_status v ON v.REV_Code = fs.REV_Code
        WHERE v.Is_Statewide_Dormant = FALSE
          AND v.Is_Rollup = FALSE
          AND fs.REV_Code NOT IN (
              SELECT Revenue_Code FROM mart_district_revenue_rollup
              WHERE District_ID = ? AND FY = ?
          )
        ORDER BY fs.Stream_Type, fs.Rollup_Level, fs.REV_Code
    """, [district_id, fy]).fetchall()

    col_names = [
        "Revenue_Code", "Stream_Type", "Rollup_Level", "Category",
        "Display_Title", "Amount", "Full_Name", "Display_Name",
        "Short_Description", "Full_Description",
    ]

    def row_to_dict(r):
        d = dict(zip(col_names, r))
        d["Amount"] = float(d["Amount"]) if d["Amount"] is not None else None
        return d

    all_rows = [row_to_dict(r) for r in mart_rows] + [row_to_dict(r) for r in gap_rows]

    # Sort: Stream by STREAM_ORDER, then Rollup_Level, then Revenue_Code
    def sort_key(d):
        stream_rank = STREAM_ORDER.get(d["Stream_Type"] or "", 99)
        rl = d["Rollup_Level"] or 99
        code = d["Revenue_Code"] or ""
        return (stream_rank, rl, code)

    all_rows.sort(key=sort_key)

    warnings = []
    if gap_rows:
        gap_codes = [r[0] for r in gap_rows]
        warnings.append(
            f"{len(gap_codes)} non-dormant handbook code(s) absent from mart "
            f"(padded with $0): {', '.join(gap_codes)}"
        )

    return all_rows, warnings


# ---------------------------------------------------------------------------
# Hierarchy builder
# ---------------------------------------------------------------------------

def build_hierarchy(rows):
    """
    Organise rows into a nested structure:
      streams → list of:
        {stream, level1_code, level1_title, groups: [
            {level2_code, level2_title, category, leaves: [
                {code, title, amount, full_name, display_name, short_desc, full_desc,
                 sub_leaves: [...]}
            ]}
        ]}

    The mart includes Rollup_Level 1/2 header rows (Amount=None) and
    Rollup_Level 3/4 leaf rows (Amount=float, possibly 0.0).
    """
    # Partition by stream
    streams_seen = []
    by_stream = {}
    for r in rows:
        s = r["Stream_Type"] or "Other"
        if s not in by_stream:
            streams_seen.append(s)
            by_stream[s] = []
        by_stream[s].append(r)

    result = []
    for stream in streams_seen:
        stream_rows = by_stream[stream]

        level1 = next(
            (r for r in stream_rows if r["Rollup_Level"] == 1), None
        )
        level1_code  = level1["Revenue_Code"] if level1 else ""
        level1_title = level1["Display_Title"] if level1 else stream

        # Collect level-2 groups
        groups = []
        current_group = None

        for r in stream_rows:
            if r["Rollup_Level"] == 1:
                continue
            elif r["Rollup_Level"] == 2:
                current_group = {
                    "level2_code":  r["Revenue_Code"],
                    "level2_title": r["Display_Title"],
                    "category":     r["Category"],
                    "leaves":       [],
                }
                groups.append(current_group)
            elif r["Rollup_Level"] == 3:
                leaf = {
                    "code":       r["Revenue_Code"],
                    "title":      r["Display_Title"],
                    "amount":     r["Amount"],
                    "full_name":  r["Full_Name"],
                    "display_name": r["Display_Name"],
                    "short_desc": r["Short_Description"],
                    "full_desc":  r["Full_Description"],
                    "sub_leaves": [],
                }
                if current_group is not None:
                    current_group["leaves"].append(leaf)
                else:
                    # Orphan leaf — create an implicit group
                    implicit = {
                        "level2_code":  None,
                        "level2_title": "Other",
                        "category":     None,
                        "leaves":       [leaf],
                    }
                    groups.append(implicit)
                    current_group = implicit
            elif r["Rollup_Level"] == 4:
                # Sub-leaf: attach to the last level-3 leaf
                sub = {
                    "code":       r["Revenue_Code"],
                    "title":      r["Display_Title"],
                    "amount":     r["Amount"],
                    "full_name":  r["Full_Name"],
                    "display_name": r["Display_Name"],
                    "short_desc": r["Short_Description"],
                    "full_desc":  r["Full_Description"],
                }
                if current_group and current_group["leaves"]:
                    current_group["leaves"][-1]["sub_leaves"].append(sub)
                # else: orphan sub-leaf (unusual) — skip silently

        result.append({
            "stream":      stream,
            "level1_code": level1_code,
            "level1_title": level1_title,
            "groups":      groups,
        })

    return result


# ---------------------------------------------------------------------------
# KPI computation
# ---------------------------------------------------------------------------

def compute_kpis(hierarchy):
    """Return (grand_total, by_stream_dict) from hierarchy."""
    by_stream = {}
    for block in hierarchy:
        s = block["stream"]
        total = 0.0
        for grp in block["groups"]:
            for leaf in grp["leaves"]:
                a = leaf["amount"]
                if a is not None:
                    total += a
                for sub in leaf["sub_leaves"]:
                    sa = sub["amount"]
                    if sa is not None:
                        total += sa
        by_stream[s] = total
    grand = sum(by_stream.values())
    return grand, by_stream


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_hierarchy_rows(hierarchy):
    """Return HTML <tbody> rows for the hierarchical revenue table."""
    parts = []

    for block in hierarchy:
        stream = block["stream"]
        level1_title = block["level1_title"]

        # Stream header row
        parts.append(
            f'<tr class="stream-header">'
            f'<td colspan="2" class="stream-label">{html.escape(level1_title)}</td>'
            f'<td class="num stream-label"></td>'
            f'</tr>'
        )

        stream_total = 0.0

        for grp in block["groups"]:
            grp_code  = grp["level2_code"]
            grp_title = grp["level2_title"] or "Other"

            # Group sub-header row
            parts.append(
                f'<tr class="group-header">'
                f'<td class="group-label" colspan="2">{html.escape(grp_title)}</td>'
                f'<td class="num group-label"></td>'
                f'</tr>'
            )

            grp_total = 0.0

            for leaf in grp["leaves"]:
                amt = leaf["amount"]
                leaf_total = amt if amt is not None else 0.0

                # Accumulate sub-leaf totals into leaf
                for sub in leaf["sub_leaves"]:
                    sa = sub["amount"]
                    if sa is not None:
                        leaf_total += sa

                grp_total += leaf_total
                amt_display = amt if amt is not None else 0.0

                info = code_info_button(
                    leaf["code"],
                    leaf["title"] or leaf["code"],
                    leaf.get("short_desc"),
                    leaf.get("full_desc"),
                )

                # Display_Name from code_accounting_codes is the canonical short label
                desc_label = (
                    leaf.get("display_name")
                    or leaf.get("full_name")
                    or leaf["title"]
                    or leaf["code"]
                )

                style = fmt_currency_style(amt_display)
                parts.append(
                    f'<tr class="leaf-row">'
                    f'<td class="code-cell mono">{html.escape(leaf["code"])} {info}</td>'
                    f'<td class="desc-cell">{html.escape(desc_label)}</td>'
                    f'<td class="num" style="{style}">{fmt_currency(amt_display)}</td>'
                    f'</tr>'
                )

                # Sub-leaf rows (Level 4)
                for sub in leaf["sub_leaves"]:
                    sa = sub["amount"] if sub["amount"] is not None else 0.0
                    sub_info = code_info_button(
                        sub["code"],
                        sub["title"] or sub["code"],
                        sub.get("short_desc"),
                        sub.get("full_desc"),
                    )
                    sub_desc = (
                        sub.get("display_name")
                        or sub.get("full_name")
                        or sub["title"]
                        or sub["code"]
                    )
                    sub_style = fmt_currency_style(sa)
                    parts.append(
                        f'<tr class="subleaf-row">'
                        f'<td class="code-cell mono sub-indent">'
                        f'{html.escape(sub["code"])} {sub_info}</td>'
                        f'<td class="desc-cell sub-indent">{html.escape(sub_desc)}</td>'
                        f'<td class="num" style="{sub_style}">{fmt_currency(sa)}</td>'
                        f'</tr>'
                    )

            stream_total += grp_total

            # Group subtotal row
            grp_style = fmt_currency_style(grp_total)
            parts.append(
                f'<tr class="subtotal-row">'
                f'<td colspan="2" class="subtotal-label">'
                f'Subtotal — {html.escape(grp_title)}</td>'
                f'<td class="num subtotal-amt" style="{grp_style}">'
                f'{fmt_currency(grp_total)}</td>'
                f'</tr>'
            )

        # Stream total row
        stream_style = fmt_currency_style(stream_total)
        parts.append(
            f'<tr class="stream-total-row">'
            f'<td colspan="2" class="stream-total-label">'
            f'Total — {html.escape(level1_title)}</td>'
            f'<td class="num stream-total-amt" style="{stream_style}">'
            f'{fmt_currency(stream_total)}</td>'
            f'</tr>'
        )

    return "\n".join(parts)


def render_kpi_cards(grand_total, by_stream):
    """Return HTML for the KPI card row."""
    cards = []
    for stream in ["Local", "State", "Federal"]:
        val = by_stream.get(stream, 0.0)
        style = fmt_currency_style(val)
        cards.append(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">{html.escape(stream)} Revenue</div>'
            f'<div class="kpi-value" style="{style}">{fmt_currency(val)}</div>'
            f'</div>'
        )
    gt_style = fmt_currency_style(grand_total)
    cards.append(
        f'<div class="kpi-card kpi-grand">'
        f'<div class="kpi-label">Grand Total</div>'
        f'<div class="kpi-value" style="{gt_style}">{fmt_currency(grand_total)}</div>'
        f'</div>'
    )
    return "\n".join(cards)


def render_methodology(district_id, district_name, fy, reported_flag,
                       gap_warnings, row_count, grand_total):
    """Return the methodology footer HTML."""
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if reported_flag is True:
        reported_note = (
            f"<strong>Reported_Flag = TRUE</strong> for {html.escape(district_name)} "
            f"FY{fy}. All displayed amounts are district self-reported."
        )
    elif reported_flag is False:
        reported_note = (
            f'<span style="color:{COLORS["danger"]}"><strong>Reported_Flag = FALSE</strong> '
            f"for {html.escape(district_name)} FY{fy}. This district did not submit "
            f"revenue data for this fiscal year. All amounts are zero-filled template "
            f"values and do not represent actual receipts.</span>"
        )
    else:
        reported_note = (
            f"No <code>lea_revenues</code> rows found for "
            f"{html.escape(district_name)} FY{fy}."
        )

    gap_html = ""
    if gap_warnings:
        gap_html = "<p><strong>Handbook gap-fill:</strong> " + html.escape("; ".join(gap_warnings)) + "</p>"

    return f"""
    <h2>Methodology &amp; Caveats</h2>
    <p>
      <strong>Source:</strong> <code>mart_district_revenue_rollup</code> — a pre-built
      mart derived from <code>lea_revenues</code> filtered on
      <code>Reported_Flag = TRUE</code>, joined to
      <code>code_district_funding_streams</code> for hierarchy metadata.
      Amounts are LEA self-reported district revenue, raw dollars (not per-pupil).
    </p>
    <p>
      <strong>Dormancy filter:</strong> Codes flagged
      <code>Is_Statewide_Dormant = TRUE</code> in
      <code>vw_revenue_code_status</code> are excluded from the mart and from
      this report. As of the current mart build, 39 codes are statewide-dormant
      (zero across all districts for all available FYs). Dormant codes are
      suppressed per CLAUDE.md dormancy-mask convention.
    </p>
    <p>
      <strong>Handbook completeness:</strong> Every non-dormant code in
      <code>code_district_funding_streams</code> is displayed even if its
      reported amount is $0, per the detail-mode specification. Rollup header
      codes (Rollup_Level 1 and 2) are shown as section headers only.
    </p>
    <p>{reported_note}</p>
    {gap_html}
    <p>
      <strong>SCEIS variance section:</strong> Omitted in v1. The full agent
      definition specifies showing per-bucket SCEIS-vs-LEA variance (State Total
      and Federal Total from <code>vw_sceis_fi_payments_classified</code> vs
      LEA sub-bucket sums). This is a v2 feature pending SCEIS GL-to-Revenue_Code
      mapping availability.
    </p>
    <p>
      <strong>Excluded districts:</strong> Entities in
      <code>lookup_district_exclusions</code> with
      <code>Exclude_Scope = 'all_reports'</code> are excluded from statewide
      aggregations (currently 6 entities: Governor's School for Agriculture,
      SCSDB, DJJ, DOC, Governor's School for Arts, Governor's School for
      Science). District-level detail reports are not affected.
    </p>
    <p>
      <strong>Report rows:</strong> {row_count} revenue lines rendered &middot;
      Grand Total: {fmt_currency(grand_total)} &middot;
      FY{fy} &middot; District {html.escape(district_id)} ({html.escape(district_name)})
    </p>
    <p>
      <strong>Built:</strong> {timestamp}
    </p>
    """


# ---------------------------------------------------------------------------
# Full HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Revenue Detail — {district_name} FY{fy}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://unpkg.com/@popperjs/core@2"></script>
<script src="https://unpkg.com/tippy.js@6"></script>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/themes/light-border.css">
<style>
  :root {{
    --brand-primary:   #2F3D4C;
    --brand-secondary: #234058;
    --brand-tertiary:  #43718B;
    --brand-accent:    #F1BA55;
    --danger:          #B3261E;
    --warning:         #8A5A00;
    --neutral-fg:      #454C56;
    --neutral-bg:      #F5F6F7;
    --border-subtle:   #E1E3E6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Poppins', sans-serif;
    margin: 0;
    padding: 24px;
    background: var(--neutral-bg);
    color: var(--brand-primary);
    font-size: 14px;
  }}
  .container {{ max-width: 1100px; margin: 0 auto; }}

  /* ---- Header ---- */
  header {{ margin-bottom: 24px; border-bottom: 3px solid var(--brand-accent); padding-bottom: 16px; }}
  h1 {{ font-size: 26px; font-weight: 700; margin: 0 0 4px; color: var(--brand-primary); }}
  .subtitle {{ color: var(--neutral-fg); font-size: 13px; margin-top: 4px; }}
  .subtitle strong {{ color: var(--brand-primary); }}

  /* ---- KPI row ---- */
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 24px;
  }}
  .kpi-card {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 16px 20px;
  }}
  .kpi-card.kpi-grand {{
    border-color: var(--brand-tertiary);
    border-width: 2px;
  }}
  .kpi-label {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--neutral-fg);
    margin-bottom: 6px;
  }}
  .kpi-value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 22px;
    font-weight: 600;
    color: var(--brand-primary);
    white-space: nowrap;
  }}

  /* ---- Revenue table card ---- */
  .table-card {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 0;
    margin-bottom: 24px;
    overflow: hidden;
  }}
  .table-card-header {{
    background: var(--brand-primary);
    color: white;
    padding: 14px 20px;
    font-weight: 600;
    font-size: 15px;
    display: flex;
    align-items: center;
    gap: 12px;
  }}
  .table-scroll {{
    overflow-x: auto;
  }}
  table.revenue-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  table.revenue-table thead th {{
    background: var(--brand-secondary);
    color: white;
    padding: 8px 12px;
    text-align: left;
    font-weight: 500;
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  table.revenue-table thead th.num {{ text-align: right; }}
  table.revenue-table td {{ padding: 5px 12px; }}

  /* ---- Stream header (Level 1) ---- */
  tr.stream-header td {{
    background: var(--brand-secondary);
    color: white;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 12px;
    letter-spacing: 0.3px;
  }}

  /* ---- Group header (Level 2) ---- */
  tr.group-header td {{
    background: #E8EDF2;
    color: var(--brand-secondary);
    font-weight: 600;
    font-size: 12px;
    padding: 6px 12px 6px 20px;
    border-bottom: 1px solid var(--border-subtle);
  }}

  /* ---- Leaf rows (Level 3) ---- */
  tr.leaf-row td {{
    padding: 5px 12px 5px 28px;
    border-bottom: 1px solid #F0F2F4;
  }}
  tr.leaf-row:hover td {{ background: #F7F9FA; }}

  /* ---- Sub-leaf rows (Level 4) ---- */
  tr.subleaf-row td {{
    padding: 4px 12px 4px 44px;
    border-bottom: 1px solid #F0F2F4;
    font-size: 12px;
    color: var(--neutral-fg);
  }}
  tr.subleaf-row:hover td {{ background: #F7F9FA; }}
  .sub-indent {{ padding-left: 44px !important; }}

  /* ---- Subtotal rows ---- */
  tr.subtotal-row td {{
    background: #F0F4F8;
    padding: 6px 12px;
    font-weight: 600;
    font-size: 12px;
    border-top: 1px solid #D0D8E0;
    border-bottom: 2px solid #C0CBD6;
    color: var(--brand-secondary);
  }}
  td.subtotal-label {{ padding-left: 20px !important; }}
  td.subtotal-amt {{
    font-family: 'JetBrains Mono', monospace;
    text-align: right;
  }}

  /* ---- Stream total rows ---- */
  tr.stream-total-row td {{
    background: var(--brand-primary);
    color: white;
    padding: 8px 12px;
    font-weight: 700;
    font-size: 13px;
    border-top: 2px solid var(--brand-secondary);
  }}
  td.stream-total-label {{ padding-left: 12px !important; }}
  td.stream-total-amt {{
    font-family: 'JetBrains Mono', monospace;
    text-align: right;
  }}
  tr.stream-total-row td[style*="color: #B3261E"] {{
    color: #FF8080 !important;
  }}

  /* ---- Grand total row ---- */
  tr.grand-total-row td {{
    background: var(--brand-accent);
    color: var(--brand-primary);
    padding: 10px 12px;
    font-weight: 700;
    font-size: 14px;
    border-top: 3px solid var(--brand-secondary);
  }}
  td.grand-total-label {{ padding-left: 12px !important; }}
  td.grand-total-amt {{
    font-family: 'JetBrains Mono', monospace;
    text-align: right;
  }}

  /* ---- Code / desc cells ---- */
  .code-cell {{
    white-space: nowrap;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--brand-tertiary);
    width: 140px;
  }}
  .desc-cell {{ color: var(--brand-primary); }}
  .num {{
    text-align: right;
    font-family: 'JetBrains Mono', monospace;
    white-space: nowrap;
    width: 140px;
  }}
  .mono {{ font-family: 'JetBrains Mono', monospace; }}
  .small {{ font-size: 11px; }}

  /* ---- Info button (lifted from build_funding_projection_report.py) ---- */
  .info-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    margin-left: 4px;
    border: 1px solid var(--brand-tertiary);
    background: white;
    color: var(--brand-tertiary);
    border-radius: 50%;
    font-family: 'Poppins', sans-serif;
    font-size: 10px;
    font-weight: 700;
    font-style: italic;
    cursor: pointer;
    line-height: 1;
    padding: 0;
    transition: background 120ms ease, color 120ms ease;
    vertical-align: middle;
  }}
  .info-btn:hover, .info-btn:focus {{
    background: var(--brand-tertiary);
    color: white;
    outline: none;
  }}
  .tippy-content .code-tip-header {{
    font-weight: 600;
    color: var(--brand-primary);
    margin-bottom: 6px;
    font-size: 13px;
  }}
  .tippy-content .code-tip-short {{
    font-size: 12px;
    color: var(--neutral-fg);
    margin-bottom: 8px;
    line-height: 1.4;
  }}
  .tippy-content .code-tip-full {{
    font-size: 11px;
    color: var(--neutral-fg);
    line-height: 1.45;
    border-top: 1px solid var(--border-subtle);
    padding-top: 6px;
    max-height: 180px;
    overflow-y: auto;
  }}
  .tippy-content .code-tip-full-toggle {{
    font-size: 11px;
    color: var(--brand-tertiary);
    cursor: pointer;
    text-decoration: underline;
    background: none;
    border: none;
    padding: 0;
    font-family: inherit;
  }}

  /* ---- Footer ---- */
  footer {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 20px 24px;
    font-size: 12px;
    color: var(--neutral-fg);
    margin-top: 24px;
    line-height: 1.6;
  }}
  footer h2 {{ font-size: 15px; color: var(--brand-primary); margin: 0 0 14px; }}
  footer p {{ margin: 0 0 10px; }}
  footer code {{
    background: var(--neutral-bg);
    padding: 1px 5px;
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
  }}

  /* ---- Responsive ---- */
  @media (max-width: 700px) {{
    .kpi-row {{ grid-template-columns: 1fr 1fr; }}
  }}
  @media (max-width: 400px) {{
    .kpi-row {{ grid-template-columns: 1fr; }}
  }}
</style>
</head>
<body>
<div class="container">

  <header>
    <h1>Revenue Detail &mdash; {district_name}</h1>
    <div class="subtitle">
      District <strong>{district_id}</strong> &middot;
      Fiscal Year <strong>FY{fy}</strong> &middot;
      Mode: <strong>detail</strong> (raw dollars, not per-pupil)
    </div>
  </header>

  <section class="kpi-row">
    {kpi_cards}
  </section>

  <section class="table-card">
    <div class="table-card-header">
      Revenue Listing &mdash; All Handbook Codes
      <span style="font-weight:400; font-size:12px; opacity:0.8;">
        ({row_count} line items &middot; hover any code for handbook description)
      </span>
    </div>
    <div class="table-scroll">
      <table class="revenue-table">
        <thead>
          <tr>
            <th>Code</th>
            <th>Description</th>
            <th class="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {hierarchy_rows}
          <tr class="grand-total-row">
            <td colspan="2" class="grand-total-label">Grand Total</td>
            <td class="num grand-total-amt" style="{grand_total_style}">{grand_total_fmt}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>

  <footer>
    {methodology}
  </footer>

</div>

<!-- Tippy tooltips (lifted from build_funding_projection_report.py) -->
<script>
(function() {{
  if (typeof tippy === 'undefined') return;
  tippy('.info-btn', {{
    theme: 'light-border',
    allowHTML: true,
    interactive: true,
    trigger: 'click',
    appendTo: () => document.body,
    placement: 'top',
    maxWidth: 360,
    content: function(el) {{
      const code  = el.dataset.code  || '';
      const title = el.dataset.title || '';
      const short = el.dataset.short || '';
      const full  = el.dataset.full  || '';
      let h = '<div class="code-tip-header">' + code + ' — ' + title + '</div>';
      if (short) h += '<div class="code-tip-short">' + short + '</div>';
      if (full && full !== short) {{
        h += '<button class="code-tip-full-toggle">Show full description</button>';
        h += '<div class="code-tip-full" style="display:none;">' + full + '</div>';
      }}
      return h;
    }},
    onShown: function(instance) {{
      const btn = instance.popper.querySelector('.code-tip-full-toggle');
      if (!btn) return;
      btn.addEventListener('click', function() {{
        const full = instance.popper.querySelector('.code-tip-full');
        if (full.style.display === 'none') {{
          full.style.display = 'block';
          btn.textContent = 'Hide full description';
        }} else {{
          full.style.display = 'none';
          btn.textContent = 'Show full description';
        }}
      }});
    }},
  }});
}})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Build a single-district hierarchical revenue detail HTML report."
    )
    p.add_argument(
        "--district", required=True,
        help="District_ID (e.g. 0201) or District_Name (e.g. 'Aiken 01')",
    )
    p.add_argument(
        "--fy", required=True, type=int,
        help="Fiscal year (e.g. 2024)",
    )
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--output-dir", default=OUTPUT_DIR)
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    con = duckdb.connect(args.db, read_only=True)

    district_id, district_name = resolve_district(con, args.district)
    print(f"[district-revenue-detail] district={district_id} ({district_name}) FY={args.fy}")

    # Reported_Flag check
    reported_flag = fetch_reported_flag(con, district_id, args.fy)
    if reported_flag is False:
        print(
            f"[district-revenue-detail] WARNING: {district_name} FY{args.fy} "
            "has Reported_Flag=FALSE — amounts are template zeros, not real receipts."
        )
    elif reported_flag is None:
        print(
            f"[district-revenue-detail] WARNING: No lea_revenues rows found for "
            f"{district_name} FY{args.fy}."
        )

    # Fetch revenue rows
    rows, gap_warnings = fetch_revenue_rows(con, district_id, args.fy)
    for w in gap_warnings:
        print(f"[district-revenue-detail] WARNING: {w}")

    con.close()

    # Build hierarchy
    hierarchy = build_hierarchy(rows)

    # KPIs
    grand_total, by_stream = compute_kpis(hierarchy)

    # Count leaf rows for display
    leaf_count = sum(
        1 + len(leaf["sub_leaves"])
        for block in hierarchy
        for grp in block["groups"]
        for leaf in grp["leaves"]
    )

    # Render
    kpi_html  = render_kpi_cards(grand_total, by_stream)
    hier_html = render_hierarchy_rows(hierarchy)
    method    = render_methodology(
        district_id, district_name, args.fy,
        reported_flag, gap_warnings, leaf_count, grand_total,
    )

    html_content = _HTML_TEMPLATE.format(
        district_name   = html.escape(district_name),
        district_id     = html.escape(district_id),
        fy              = args.fy,
        kpi_cards       = kpi_html,
        hierarchy_rows  = hier_html,
        grand_total_fmt = fmt_currency(grand_total),
        grand_total_style = fmt_currency_style(grand_total),
        row_count       = leaf_count,
        methodology     = method,
    )

    # Write output
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"district_revenue_detail_{district_id}_{args.fy}_{timestamp}.html"
    out_path  = os.path.join(args.output_dir, filename)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(html_content)

    file_size_kb = os.path.getsize(out_path) // 1024
    print(f"[district-revenue-detail] wrote {out_path} ({file_size_kb} KB)")
    print(f"[district-revenue-detail] {leaf_count} leaf rows | grand total: {fmt_currency(grand_total)}")

    if gap_warnings:
        print(f"[district-revenue-detail] {len(gap_warnings)} gap-fill warning(s) — see above")

    return 0


if __name__ == "__main__":
    sys.exit(main())
