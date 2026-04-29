#!/usr/bin/env python3
"""
build_funding_projection_report.py — single-district funding projection
HTML dashboard.

Owned by the report-funding-projection agent. See
.claude/agents/report-funding-projection.md.

Reads from mart_funding_projections (must be built first by
scripts/build_funding_projections.py) and lea_revenues (history). Emits a
single self-contained HTML file styled per SCDE Finance design system.

Run:
  python3 scripts/build_funding_projection_report.py --district "Aiken 01"
  python3 scripts/build_funding_projection_report.py --district 0201
"""

import argparse
import datetime as dt
import html
import json
import os
import sys

import duckdb

DB_PATH = "db/scde.duckdb"
OUTPUT_DIR = "outputs/reports"
DEFAULT_SCENARIO = "baseline"

# Style tokens lifted from docs/style/scde-design/style-guide.md §1.4 / §5.1
COLORS = {
    "brand_primary": "#2F3D4C",
    "brand_secondary": "#234058",
    "brand_tertiary": "#43718B",
    "brand_accent": "#F1BA55",
    "danger": "#B3261E",
    "warning": "#8A5A00",
    "neutral_fg": "#454C56",
    "neutral_bg": "#F5F6F7",
    "border_subtle": "#E1E3E6",
    "projection_historical": "#234058",
    "projection_projected": "#43718B",
    "projection_band_fill": "rgba(67, 113, 139, 0.20)",
    "insufficient_hatch": "rgba(126, 140, 158, 0.35)",
}

PARTIAL_FY25_DISTRICTS = {
    "Beaufort 01", "Lancaster 01", "Greenwood 50", "Saluda 01",
    "Laurens 55", "Barnwell 45", "Barnwell 48", "Clarendon 06",
}

CHARTER_AUTHORIZER_IDS = {"4701", "4801", "4901"}

METHOD_TOOLTIPS = {
    "trend_ols": "Linear OLS regression on >=3 FYs of history with 80% prediction interval.",
    "trend_ols_2fy": "Linear extrapolation from 2 FYs of history; bounds use a 15% heuristic (no residual SE).",
    "sunset_zero": "Program sunset detected from inventory note; projected to $0 from the year after last paid FY.",
    "insufficient_history": "Fewer than 2 FYs of usable history; rendered as a hatch band — no projection produced.",
    "formula_sac": "SAC formula: (district_WPU / statewide_WPU) * sac_total_state_share.",
}


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--district", required=True,
                   help="District_ID (e.g. 0201) or District_Name (e.g. 'Aiken 01')")
    p.add_argument("--scenario", default=DEFAULT_SCENARIO)
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--output-dir", default=OUTPUT_DIR)
    return p.parse_args()


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


def fetch_history(con, district_id):
    """Per-FY totals by stream + per-code rows for FY23-FY25.
    Filters statewide-dormant codes per CLAUDE.md convention."""
    by_stream = con.execute("""
        SELECT r.FY, c.Stream_Type,
               CAST(SUM(r.Amount) AS BIGINT) AS total
        FROM lea_revenues r
        LEFT JOIN code_district_funding_streams c ON c.REV_Code = r.Revenue_Code
        JOIN vw_revenue_code_status v ON v.REV_Code = r.Revenue_Code
        WHERE r.District_ID = ?
          AND r.Reported_Flag = TRUE
          AND r.Amount IS NOT NULL AND r.Amount != 0
          AND r.Revenue_Code NOT LIKE '5%'
          AND c.Stream_Type IS NOT NULL
          AND v.Is_Statewide_Dormant = FALSE
        GROUP BY r.FY, c.Stream_Type
        ORDER BY r.FY, c.Stream_Type
    """, [district_id]).fetchall()
    return by_stream


def fetch_projections(con, district_id, scenario):
    """Per-FY totals by stream + per-code rows for the projection horizon."""
    by_stream = con.execute("""
        SELECT FY, Stream_Type,
               CAST(SUM(Amount) AS BIGINT) AS total,
               CAST(SUM(Lower_80) AS BIGINT) AS lo,
               CAST(SUM(Upper_80) AS BIGINT) AS hi
        FROM mart_funding_projections
        WHERE District_ID = ? AND Scenario = ?
          AND Method NOT IN ('insufficient_history')
        GROUP BY FY, Stream_Type
        ORDER BY FY, Stream_Type
    """, [district_id, scenario]).fetchall()
    return by_stream


def fetch_top_codes(con, district_id, scenario, limit=12):
    """Top codes by FY26 projected amount, with history + projection rows."""
    horizon_anchor = con.execute("""
        SELECT MIN(FY) FROM mart_funding_projections
        WHERE District_ID = ? AND Scenario = ?
    """, [district_id, scenario]).fetchone()[0]

    top_codes = [r[0] for r in con.execute("""
        SELECT Revenue_Code
        FROM mart_funding_projections
        WHERE District_ID = ? AND Scenario = ? AND FY = ?
          AND Method NOT IN ('insufficient_history')
        ORDER BY Amount DESC NULLS LAST
        LIMIT ?
    """, [district_id, scenario, horizon_anchor, limit]).fetchall()]

    rows = []
    for code in top_codes:
        meta = con.execute("""
            SELECT c.Display_Title, c.Stream_Type, c.Allocation_Basis,
                   COALESCE(a.Short_Description, h.Short_Description) AS short_desc,
                   COALESCE(a.Full_Description, h.Full_Description) AS full_desc
            FROM code_district_funding_streams c
            LEFT JOIN code_accounting_codes a ON a.Code = c.REV_Code AND a.Type = 'Revenue'
            LEFT JOIN code_historical_revenue_codes h ON h.Code = c.REV_Code AND h.Type = 'Revenue'
            WHERE c.REV_Code = ?
        """, [code]).fetchone()
        if meta is None:
            meta = (code, None, None, None, None)
        title, stream, alloc, short_desc, full_desc = meta

        history = {fy: amt for fy, amt in con.execute("""
            SELECT FY, CAST(Amount AS BIGINT) FROM lea_revenues
            WHERE District_ID = ? AND Revenue_Code = ?
              AND Reported_Flag = TRUE AND Amount IS NOT NULL
        """, [district_id, code]).fetchall()}

        projection = {fy: (amt, lo, hi, method) for fy, amt, lo, hi, method in con.execute("""
            SELECT FY, CAST(Amount AS BIGINT), CAST(Lower_80 AS BIGINT),
                   CAST(Upper_80 AS BIGINT), Method
            FROM mart_funding_projections
            WHERE District_ID = ? AND Scenario = ? AND Revenue_Code = ?
            ORDER BY FY
        """, [district_id, scenario, code]).fetchall()}

        rows.append({
            "code": code, "title": title or code, "stream": stream,
            "allocation_basis": alloc, "short_desc": short_desc,
            "full_desc": full_desc,
            "history": history, "projection": projection,
        })
    return rows


def fetch_methodology(con, district_id, scenario):
    """Counts of insufficient_history, sunset_zero rows for the district."""
    counts = dict(con.execute("""
        SELECT Method, COUNT(*) FROM mart_funding_projections
        WHERE District_ID = ? AND Scenario = ?
        GROUP BY Method
    """, [district_id, scenario]).fetchall())
    return counts


def fetch_local_composition(con, district_id, top_n=5):
    """
    Top-N Local revenue codes for the latest historical FY where the district
    has reported Local activity. Returns dict with the FY, total, and a list
    of (code, title, amount, pct) tuples.

    Filters statewide-dormant codes per CLAUDE.md convention.
    """
    latest_fy = con.execute("""
        SELECT MAX(r.FY)
        FROM lea_revenues r
        LEFT JOIN code_district_funding_streams c ON c.REV_Code = r.Revenue_Code
        JOIN vw_revenue_code_status v ON v.REV_Code = r.Revenue_Code
        WHERE r.District_ID = ?
          AND r.Reported_Flag = TRUE
          AND r.Amount IS NOT NULL AND r.Amount != 0
          AND c.Stream_Type = 'Local'
          AND v.Is_Statewide_Dormant = FALSE
    """, [district_id]).fetchone()[0]
    if latest_fy is None:
        return None

    rows = con.execute("""
        SELECT r.Revenue_Code, c.Display_Title, CAST(r.Amount AS BIGINT),
               COALESCE(a.Short_Description, h.Short_Description) AS short_desc,
               COALESCE(a.Full_Description, h.Full_Description) AS full_desc
        FROM lea_revenues r
        LEFT JOIN code_district_funding_streams c ON c.REV_Code = r.Revenue_Code
        JOIN vw_revenue_code_status v ON v.REV_Code = r.Revenue_Code
        LEFT JOIN code_accounting_codes a ON a.Code = r.Revenue_Code AND a.Type = 'Revenue'
        LEFT JOIN code_historical_revenue_codes h ON h.Code = r.Revenue_Code AND h.Type = 'Revenue'
        WHERE r.District_ID = ? AND r.FY = ?
          AND r.Reported_Flag = TRUE
          AND r.Amount IS NOT NULL AND r.Amount != 0
          AND c.Stream_Type = 'Local'
          AND v.Is_Statewide_Dormant = FALSE
        ORDER BY r.Amount DESC
    """, [district_id, latest_fy]).fetchall()
    if not rows:
        return None

    total = sum(r[2] for r in rows)
    top = rows[:top_n]
    other_total = sum(r[2] for r in rows[top_n:])

    items = [
        {"code": code, "title": title or code, "amount": amount,
         "short_desc": short_desc, "full_desc": full_desc,
         "pct": (amount / total * 100) if total else 0}
        for code, title, amount, short_desc, full_desc in top
    ]
    if other_total > 0:
        items.append({
            "code": "—", "title": f"Other ({len(rows) - top_n} codes)",
            "amount": other_total, "short_desc": None, "full_desc": None,
            "pct": (other_total / total * 100) if total else 0,
        })

    return {"fy": latest_fy, "total": total, "items": items}


def fetch_charter_breakdown(con, district_id):
    """
    For the 3 charter authorizers, return per-mode (B&M vs Virtual) WPU and
    ADM by FY, plus the implied per-WPU rate from historical SAC actuals.
    Returns None for non-charter districts.
    """
    if district_id not in CHARTER_AUTHORIZER_IDS:
        return None

    modes = con.execute("""
        SELECT FY, Category,
               CAST(ADM_135_Day AS BIGINT) AS adm,
               CAST(Weighted_Pupils AS DECIMAL(12,2)) AS wpu
        FROM lea_wpu_allocations
        WHERE District_ID = ? AND Category IN ('Charter_BM', 'Charter_VIRT')
        ORDER BY FY, Category
    """, [district_id]).fetchall()

    # Authorizer's effective per-WPU rate from historical SAC actuals.
    # SAC = sum(3103, 3503, 3541) / total WPU for each FY.
    rates = {}
    for fy, sac, total_wpu in con.execute("""
        WITH sac AS (
          SELECT FY, SUM(Amount) AS dollars FROM lea_revenues
          WHERE District_ID = ? AND Revenue_Code IN ('3103','3503','3541')
            AND Reported_Flag = TRUE GROUP BY FY
        ),
        wpu AS (
          SELECT FY, Weighted_Pupils FROM lea_wpu_allocations
          WHERE District_ID = ? AND Category = 'Total' AND Report_Cycle = 135
        )
        SELECT s.FY, CAST(s.dollars AS BIGINT),
               CAST(w.Weighted_Pupils AS DECIMAL(12,2))
        FROM sac s LEFT JOIN wpu w USING (FY)
    """, [district_id, district_id]).fetchall():
        if total_wpu and total_wpu > 0:
            rates[fy] = float(sac) / float(total_wpu)

    # Pick most-recent reliable rate (FY24 is the cleanest)
    effective_rate = rates.get(2024) or rates.get(2023) or 3366.0

    # Build per-FY-per-mode display rows
    breakdown = []
    for fy, mode, adm, wpu in modes:
        wpu_f = float(wpu) if wpu is not None else 0.0
        wpu_per_adm = wpu_f / adm if adm else None
        implied_state_aid = wpu_f * effective_rate if wpu_f else 0
        per_pupil = implied_state_aid / adm if adm else None
        breakdown.append({
            "fy": fy, "mode": mode, "adm": adm, "wpu": int(wpu_f),
            "wpu_per_adm": wpu_per_adm,
            "implied_state_aid": int(implied_state_aid),
            "per_pupil": int(per_pupil) if per_pupil else None,
        })

    return {
        "rows": breakdown,
        "effective_rate": int(effective_rate),
        "rate_source_fy": max(rates.keys()) if rates else None,
        "historical_rates": {fy: int(r) for fy, r in rates.items()},
    }


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


def fmt_currency(n):
    if n is None:
        return "n/a"
    if n < 0:
        return f"$({-int(n):,})"
    return f"${int(n):,}"


def fmt_currency_color(n):
    if n is None or n >= 0:
        return ""
    return f"color: {COLORS['danger']};"


def render_html(district_id, district_name, scenario,
                history, projections, top_codes, methodology, partial_fy25,
                charter_breakdown=None, local_composition=None):
    """Return the full HTML document string."""
    fys_history = sorted({fy for fy, _, _ in history})
    fys_proj = sorted({fy for fy, _, _, _, _ in projections})

    # Per-FY totals for KPI band
    history_totals = {}
    for fy, _, total in history:
        history_totals[fy] = history_totals.get(fy, 0) + (total or 0)
    projection_totals = {}
    projection_bounds = {}
    for fy, _, total, lo, hi in projections:
        projection_totals[fy] = projection_totals.get(fy, 0) + (total or 0)
        prev_lo, prev_hi = projection_bounds.get(fy, (0, 0))
        projection_bounds[fy] = (prev_lo + (lo or 0), prev_hi + (hi or 0))

    latest_hist_fy = max(fys_history) if fys_history else None
    next_proj_fy = min(fys_proj) if fys_proj else None
    latest_hist_total = history_totals.get(latest_hist_fy)
    next_proj_total = projection_totals.get(next_proj_fy)
    next_proj_bounds = projection_bounds.get(next_proj_fy, (None, None))
    yoy_delta = None
    if latest_hist_total is not None and next_proj_total is not None:
        yoy_delta = next_proj_total - latest_hist_total

    # Chart data — per-stream historical + projected series
    streams = sorted({s for _, s, _ in history} | {s for _, s, _, _, _ in projections})
    chart_data = {"history": {}, "projection": {}}
    for stream in streams:
        chart_data["history"][stream] = {fy: 0 for fy in fys_history}
        chart_data["projection"][stream] = {fy: {"point": 0, "lo": 0, "hi": 0} for fy in fys_proj}
    for fy, stream, total in history:
        chart_data["history"][stream][fy] = total or 0
    for fy, stream, total, lo, hi in projections:
        chart_data["projection"][stream][fy] = {
            "point": total or 0, "lo": lo or 0, "hi": hi or 0,
        }

    chart_payload = {
        "history_fys": fys_history,
        "projection_fys": fys_proj,
        "streams": streams,
        "history": {s: [chart_data["history"][s][fy] for fy in fys_history] for s in streams},
        "projection_point": {s: [chart_data["projection"][s][fy]["point"] for fy in fys_proj] for s in streams},
        "projection_lo": {s: [chart_data["projection"][s][fy]["lo"] for fy in fys_proj] for s in streams},
        "projection_hi": {s: [chart_data["projection"][s][fy]["hi"] for fy in fys_proj] for s in streams},
    }

    is_partial_fy25 = district_name in partial_fy25
    timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return _HTML_TEMPLATE.format(
        district_name=html.escape(district_name),
        district_id=html.escape(district_id),
        scenario=html.escape(scenario),
        timestamp=timestamp,
        partial_badge=_partial_badge(is_partial_fy25),
        kpi_history=fmt_currency(latest_hist_total),
        kpi_history_label=f"Historical FY{latest_hist_fy % 100}" if latest_hist_fy else "Historical",
        kpi_projection=fmt_currency(next_proj_total),
        kpi_projection_label=f"Projected FY{next_proj_fy % 100}" if next_proj_fy else "Projected",
        kpi_bounds=f"80% PI: {fmt_currency(next_proj_bounds[0])} - {fmt_currency(next_proj_bounds[1])}" if next_proj_total else "",
        kpi_delta=fmt_currency(yoy_delta),
        kpi_delta_color=fmt_currency_color(yoy_delta),
        chart_payload=json.dumps(chart_payload),
        colors_payload=json.dumps(COLORS),
        codes_table=_render_codes_table(top_codes, fys_history, fys_proj),
        charter_panel=_render_charter_panel(charter_breakdown),
        local_composition=_render_local_composition(local_composition),
        methodology_summary=_render_methodology(methodology, is_partial_fy25, district_name),
        sunset_count=methodology.get("sunset_zero", 0),
        insufficient_count=methodology.get("insufficient_history", 0),
        trend_count=methodology.get("trend_ols", 0) + methodology.get("trend_ols_2fy", 0),
    )


def _render_local_composition(comp):
    """Render a small horizontal-bar composition of the top Local codes."""
    if not comp or not comp["items"]:
        return ""

    bar_rows = []
    for item in comp["items"]:
        pct = item["pct"]
        info = code_info_button(item["code"], item["title"],
                                item.get("short_desc"), item.get("full_desc"))
        bar_rows.append(f"""
        <tr>
          <td class="mono small code-cell">{html.escape(item['code'])} {info}</td>
          <td>{html.escape(item['title'])}</td>
          <td class="num">{fmt_currency(item['amount'])}</td>
          <td class="num small">{pct:.0f}%</td>
          <td class="bar-cell">
            <div class="bar-track"><div class="bar-fill" style="width: {pct:.1f}%"></div></div>
          </td>
        </tr>
        """)

    return f"""
    <section class="composition-card">
      <h2>Local Revenue Composition — FY{comp['fy'] % 100}</h2>
      <p class="composition-context">
        Top {len(comp['items'])} contributors to this district's <strong>{fmt_currency(comp['total'])}</strong>
        in Local revenue. Traditional districts are dominated by ad valorem (1110)
        and other property-tax codes (1100s/1200s); charter authorizers, which lack
        a property tax base, are dominated by donations (1920), pupil fees (1700s),
        food sales (1600s), and investment income (1500s).
      </p>
      <table class="composition-table">
        <thead>
          <tr><th>Code</th><th>Title</th><th>Amount</th><th>Share</th><th></th></tr>
        </thead>
        <tbody>
          {''.join(bar_rows)}
        </tbody>
      </table>
    </section>
    """


def _render_charter_panel(breakdown):
    """Render the B&M-vs-Virtual breakdown panel for charter authorizers."""
    if not breakdown or not breakdown["rows"]:
        return ""

    # Group rows by FY for side-by-side display
    by_fy = {}
    for r in breakdown["rows"]:
        by_fy.setdefault(r["fy"], {})[r["mode"]] = r

    rate = breakdown["effective_rate"]
    rate_fy = breakdown["rate_source_fy"]

    fy_blocks = []
    for fy in sorted(by_fy.keys()):
        bm = by_fy[fy].get("Charter_BM")
        vt = by_fy[fy].get("Charter_VIRT")
        bm_per = bm["per_pupil"] if bm else None
        vt_per = vt["per_pupil"] if vt else None
        bm_aid = bm["implied_state_aid"] if bm else None
        vt_aid = vt["implied_state_aid"] if vt else None
        bm_weight = bm["wpu_per_adm"] if bm and bm["wpu_per_adm"] else None
        vt_weight = vt["wpu_per_adm"] if vt and vt["wpu_per_adm"] else None
        # Discount: virtual per-pupil as % of B&M per-pupil
        discount = None
        if bm_per and vt_per:
            discount = round(100 * (1 - vt_per / bm_per))

        fy_blocks.append(f"""
        <div class="charter-fy-card">
          <h3>FY{fy % 100}</h3>
          <table class="charter-table">
            <thead>
              <tr><th>Mode</th><th>ADM</th><th>WPU</th><th>Weight</th>
                  <th>Implied State Aid</th><th>$ / pupil</th></tr>
            </thead>
            <tbody>
              <tr>
                <td><strong>B&amp;M</strong></td>
                <td class="num">{bm['adm'] if bm else '—':,}</td>
                <td class="num">{bm['wpu'] if bm else '—':,}</td>
                <td class="num">{f"{bm_weight:.3f}" if bm_weight else '—'}</td>
                <td class="num">{fmt_currency(bm_aid)}</td>
                <td class="num">{fmt_currency(bm_per)}</td>
              </tr>
              <tr>
                <td><strong>Virtual</strong></td>
                <td class="num">{vt['adm'] if vt else '—':,}</td>
                <td class="num">{vt['wpu'] if vt else '—':,}</td>
                <td class="num">{f"{vt_weight:.3f}" if vt_weight else '—'}</td>
                <td class="num">{fmt_currency(vt_aid)}</td>
                <td class="num">{fmt_currency(vt_per)}</td>
              </tr>
            </tbody>
          </table>
          {f'<p class="discount-note">Virtual pupils receive ~<strong>{discount}%</strong> less state aid per pupil than B&amp;M pupils.</p>' if discount else ''}
        </div>
        """)

    rate_note = (
        f"Implied state aid uses the authorizer's effective per-WPU rate of "
        f"<code>{fmt_currency(rate)}</code> derived from FY{rate_fy % 100} actual SAC payments "
        f"(codes 3103, 3503, 3541) divided by 135-day total WPU. "
        if rate_fy else ""
    )

    return f"""
    <section class="charter-card">
      <h2>Charter Authorizer — B&amp;M vs Virtual Breakdown</h2>
      <p class="charter-context">
        SC sets a 1.250 weight for brick-and-mortar charter pupils and a reduced
        weight for virtual charter pupils (0.650 in FY24, lowered to 0.500 in FY26).
        Funding is distributed by WPU, so virtual pupils receive a smaller share
        per head than B&amp;M pupils within the same authorizer.
      </p>
      <div class="charter-fy-row">
        {''.join(fy_blocks)}
      </div>
      <p class="charter-context small">
        {rate_note}
        Source: <code>lea_wpu_allocations</code> rows where <code>Category IN ('Charter_BM', 'Charter_VIRT')</code>
        loaded from <code>WPU04524.xlsx</code> (FY24) and <code>WPU04526.xlsx</code> (FY26).
        FY24 file uses column names "Charter Brick WPU" / "Charter Virtual WPU"; FY26 uses "B&amp;M WPU" / "VIRT WPU".
      </p>
    </section>
    """


def _partial_badge(is_partial):
    if not is_partial:
        return ""
    return (
        f'<span style="display:inline-block;background:{COLORS["brand_accent"]};'
        f'color:{COLORS["brand_primary"]};font-size:11px;font-weight:600;'
        f'padding:3px 8px;border-radius:4px;margin-left:8px;">'
        f'FY25 PARTIAL — projection may overshoot</span>'
    )


def _render_codes_table(top_codes, fys_history, fys_proj):
    if not top_codes:
        return "<p>No codes available.</p>"
    rows = []
    head_fys = "".join(f'<th>FY{fy % 100}</th>' for fy in fys_history)
    head_proj = "".join(f'<th>FY{fy % 100} (proj)</th>' for fy in fys_proj)
    rows.append(
        f'<thead><tr><th>Code</th><th>Title</th><th>Stream</th>'
        f'{head_fys}{head_proj}<th>80% PI ({fys_proj[0] % 100 if fys_proj else "n/a"})</th>'
        f'<th>Method</th></tr></thead>'
    )
    rows.append("<tbody>")
    for r in top_codes:
        info = code_info_button(r["code"], r["title"], r.get("short_desc"), r.get("full_desc"))
        cells = [
            f'<td class="mono code-cell">{html.escape(r["code"])} {info}</td>',
            f'<td>{html.escape(r["title"])}</td>',
            f'<td>{html.escape(r["stream"] or "")}</td>',
        ]
        for fy in fys_history:
            v = r["history"].get(fy)
            cells.append(f'<td class="num" style="{fmt_currency_color(v)}">{fmt_currency(v) if v is not None else "—"}</td>')
        # For projection columns, use the first projection FY's data
        for fy in fys_proj:
            proj = r["projection"].get(fy)
            v = proj[0] if proj else None
            cells.append(f'<td class="num" style="{fmt_currency_color(v)}">{fmt_currency(v) if v is not None else "—"}</td>')
        # 80% PI for first projection FY
        first_proj = r["projection"].get(fys_proj[0]) if fys_proj else None
        if first_proj and first_proj[1] is not None and first_proj[2] is not None:
            cells.append(f'<td class="num small">{fmt_currency(first_proj[1])} – {fmt_currency(first_proj[2])}</td>')
        else:
            cells.append('<td class="num small">—</td>')
        method = first_proj[3] if first_proj else "—"
        method_tip = METHOD_TOOLTIPS.get(method, "")
        cells.append(f'<td title="{html.escape(method_tip)}" class="mono small">{html.escape(method)}</td>')
        rows.append(f'<tr>{"".join(cells)}</tr>')
    rows.append("</tbody>")
    return f'<table class="codes-table">{"".join(rows)}</table>'


def _render_methodology(counts, is_partial, district_name):
    notes = []
    if is_partial:
        notes.append(
            f"<strong>FY25 history for {html.escape(district_name)} is incomplete.</strong> "
            "OLS may anchor on the FY24 peak and overstate FY26+ projections. "
            "Treat this district's projection as an upper-bound estimate until "
            "complete FY25 actuals load."
        )
    notes.append(
        "Projection method: hybrid SAC formula + OLS trend with 80% prediction "
        "intervals. SAC codes (3103, 3103H, 3503, 3541) currently fall back to "
        "trend because forward-year <code>sac_total_state_share</code> is not "
        "yet seeded into <code>policy_rate_assumptions</code>. Once the GA's "
        "FY26 (H.4025) and FY27 (H.5126) appropriations totals are seeded, "
        "the formula path activates automatically."
    )
    notes.append(
        f"<strong>Source filters applied:</strong> Reported_Flag = TRUE; "
        "5xxx codes (bond sales, transfers, lease purchase) excluded; "
        "unclassified codes (NULL Stream_Type) excluded; State and Federal "
        "projections floored at $0; sunset notes ('Closed, last paid FYNN') "
        "force $0 from FY+1 onward."
    )
    return "".join(f"<p>{n}</p>" for n in notes)


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Funding Projection — {district_name} ({scenario})</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://unpkg.com/@popperjs/core@2"></script>
<script src="https://unpkg.com/tippy.js@6"></script>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/themes/light-border.css">
<style>
  :root {{
    --brand-primary: #2F3D4C;
    --brand-secondary: #234058;
    --brand-tertiary: #43718B;
    --brand-accent: #F1BA55;
    --danger: #B3261E;
    --warning: #8A5A00;
    --neutral-bg: #F5F6F7;
    --neutral-fg: #454C56;
    --border-subtle: #E1E3E6;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: 'Poppins', sans-serif;
    margin: 0;
    padding: 24px;
    background: var(--neutral-bg);
    color: var(--brand-primary);
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  header {{ margin-bottom: 24px; }}
  h1 {{
    font-size: 28px; font-weight: 700; margin: 0 0 4px;
    color: var(--brand-primary);
  }}
  .subtitle {{ color: var(--neutral-fg); font-size: 14px; }}
  .kpi-row {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin: 24px 0;
  }}
  .kpi-card {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 20px;
  }}
  .kpi-label {{
    font-size: 12px;
    text-transform: uppercase;
    color: var(--neutral-fg);
    letter-spacing: 0.5px;
    margin-bottom: 8px;
  }}
  .kpi-value {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 28px;
    font-weight: 600;
    color: var(--brand-primary);
  }}
  .kpi-bounds {{
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
    color: var(--neutral-fg);
    margin-top: 6px;
  }}
  .chart-card {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .chart-card h2 {{ margin: 0 0 16px; font-size: 18px; }}
  canvas {{ max-height: 380px; }}
  .codes-card {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .codes-card h2 {{ margin: 0 0 16px; font-size: 18px; }}
  table.codes-table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  table.codes-table th {{
    text-align: left;
    background: var(--brand-secondary);
    color: white;
    padding: 8px 10px;
    font-weight: 500;
    position: sticky;
    top: 0;
  }}
  table.codes-table td {{
    padding: 8px 10px;
    border-bottom: 1px solid var(--border-subtle);
  }}
  table.codes-table tr:nth-child(even) td {{ background: rgba(67, 113, 139, 0.04); }}
  .mono {{ font-family: 'JetBrains Mono', monospace; }}
  .num {{ text-align: right; font-family: 'JetBrains Mono', monospace; }}
  .small {{ font-size: 11px; }}
  footer {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 20px;
    font-size: 13px;
    color: var(--neutral-fg);
    margin-top: 24px;
  }}
  footer h2 {{ font-size: 16px; color: var(--brand-primary); margin: 0 0 12px; }}
  footer p {{ margin: 0 0 10px; line-height: 1.5; }}
  footer code {{
    background: var(--neutral-bg);
    padding: 2px 5px;
    border-radius: 3px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 12px;
  }}
  .legend-note {{
    display: flex;
    gap: 16px;
    margin-top: 12px;
    font-size: 12px;
    color: var(--neutral-fg);
  }}
  .legend-swatch {{
    display: inline-block;
    width: 16px;
    height: 4px;
    margin-right: 4px;
    vertical-align: middle;
  }}
  .legend-swatch.solid {{ background: var(--brand-secondary); }}
  .legend-swatch.dashed {{
    background: linear-gradient(to right, var(--brand-tertiary) 60%, transparent 60%);
    background-size: 8px 4px;
  }}
  .legend-swatch.band {{ background: rgba(67, 113, 139, 0.20); height: 12px; }}
  .charter-card {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .charter-card h2 {{ margin: 0 0 12px; font-size: 18px; }}
  .charter-context {{ color: var(--neutral-fg); font-size: 13px; line-height: 1.5; margin: 0 0 16px; }}
  .charter-context.small {{ font-size: 12px; margin-top: 16px; }}
  .charter-fy-row {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 16px; }}
  .charter-fy-card {{
    background: var(--neutral-bg);
    border-radius: 6px;
    padding: 14px;
  }}
  .charter-fy-card h3 {{
    margin: 0 0 8px;
    font-size: 14px;
    color: var(--brand-secondary);
    font-weight: 600;
  }}
  table.charter-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.charter-table th {{
    text-align: left;
    background: var(--brand-tertiary);
    color: white;
    padding: 6px 8px;
    font-weight: 500;
  }}
  table.charter-table td {{ padding: 6px 8px; border-bottom: 1px solid white; }}
  table.charter-table .num {{ text-align: right; font-family: 'JetBrains Mono', monospace; }}
  .discount-note {{
    margin: 10px 0 0;
    padding: 8px 12px;
    background: var(--brand-accent);
    color: var(--brand-primary);
    font-size: 12px;
    border-radius: 4px;
  }}
  .discount-note strong {{ font-weight: 700; }}
  .composition-card {{
    background: white;
    border: 1px solid var(--border-subtle);
    border-radius: 8px;
    padding: 20px;
    margin-bottom: 24px;
  }}
  .composition-card h2 {{ margin: 0 0 8px; font-size: 18px; }}
  .composition-context {{ color: var(--neutral-fg); font-size: 13px; line-height: 1.5; margin: 0 0 16px; }}
  table.composition-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table.composition-table th {{
    text-align: left;
    background: var(--brand-secondary);
    color: white;
    padding: 6px 10px;
    font-weight: 500;
  }}
  table.composition-table td {{ padding: 6px 10px; border-bottom: 1px solid var(--border-subtle); }}
  table.composition-table .bar-cell {{ width: 35%; }}
  .bar-track {{
    background: var(--neutral-bg);
    border-radius: 3px;
    height: 14px;
    overflow: hidden;
  }}
  .bar-fill {{
    background: linear-gradient(90deg, var(--brand-secondary), var(--brand-tertiary));
    height: 100%;
    border-radius: 3px;
  }}
  .code-cell {{ white-space: nowrap; }}
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
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Funding Projection — {district_name} {partial_badge}</h1>
    <div class="subtitle">
      District {district_id} &middot; Scenario: <strong>{scenario}</strong> &middot;
      Built {timestamp}
    </div>
  </header>

  <section class="kpi-row">
    <div class="kpi-card">
      <div class="kpi-label">{kpi_history_label}</div>
      <div class="kpi-value">{kpi_history}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">{kpi_projection_label}</div>
      <div class="kpi-value">{kpi_projection}</div>
      <div class="kpi-bounds">{kpi_bounds}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">YoY Change</div>
      <div class="kpi-value" style="{kpi_delta_color}">{kpi_delta}</div>
    </div>
  </section>

  <section class="chart-card">
    <h2>Revenue by Stream — Historical &amp; Projected</h2>
    <canvas id="streamChart"></canvas>
    <div class="legend-note">
      <span><span class="legend-swatch solid"></span>Historical</span>
      <span><span class="legend-swatch dashed"></span>Projected (point)</span>
      <span><span class="legend-swatch band"></span>80% prediction interval</span>
    </div>
  </section>

  {charter_panel}

  {local_composition}

  <section class="codes-card">
    <h2>Top Revenue Codes — Historical &amp; Projected</h2>
    {codes_table}
  </section>

  <footer>
    <h2>Methodology &amp; Caveats</h2>
    {methodology_summary}
    <p>
      <strong>Row counts:</strong> {trend_count} trend projections &middot;
      {sunset_count} sunset zeros &middot; {insufficient_count} insufficient-history codes (rendered as hatch).
      Hover any code or method label for definitions.
    </p>
  </footer>
</div>

<script type="application/json" id="chart-data">
{chart_payload}
</script>
<script type="application/json" id="colors">
{colors_payload}
</script>
<script>
(function() {{
  const data = JSON.parse(document.getElementById('chart-data').textContent);
  const colors = JSON.parse(document.getElementById('colors').textContent);

  const streamColor = {{
    'State': colors.brand_secondary,
    'Federal': colors.brand_tertiary,
    'Local': '#5C7C8A',
  }};

  const allFYs = [...data.history_fys, ...data.projection_fys];
  const labels = allFYs.map(fy => 'FY' + (fy % 100));

  const datasets = [];
  data.streams.forEach(stream => {{
    const color = streamColor[stream] || colors.brand_primary;
    // Historical solid line
    const histData = data.history_fys.map((fy, i) => data.history[stream][i]);
    const projPoint = data.projection_point[stream];
    // Concatenate for continuous x-axis with NULLs for non-overlap
    const fullHist = histData.concat(data.projection_fys.map(() => null));
    const fullProj = data.history_fys.map(() => null).concat(projPoint);
    // Bridge: include the last historical point in the projection series
    if (histData.length > 0 && projPoint.length > 0) {{
      fullProj[data.history_fys.length - 1] = histData[histData.length - 1];
    }}
    datasets.push({{
      label: stream + ' (historical)',
      data: fullHist,
      borderColor: color,
      backgroundColor: color,
      borderWidth: 2.5,
      pointRadius: 4,
      pointBackgroundColor: color,
      tension: 0,
      spanGaps: false,
    }});
    datasets.push({{
      label: stream + ' (projected)',
      data: fullProj,
      borderColor: color,
      backgroundColor: 'transparent',
      borderWidth: 2,
      borderDash: [6, 4],
      pointRadius: 4,
      pointStyle: 'circle',
      pointBackgroundColor: 'white',
      pointBorderColor: color,
      pointBorderWidth: 1.5,
      tension: 0,
      spanGaps: false,
    }});
    // 80% PI band — fill between lo and hi
    const projLo = data.projection_lo[stream];
    const projHi = data.projection_hi[stream];
    const fullLo = data.history_fys.map(() => null).concat(projLo);
    const fullHi = data.history_fys.map(() => null).concat(projHi);
    datasets.push({{
      label: stream + ' upper 80%',
      data: fullHi,
      borderColor: 'transparent',
      backgroundColor: 'transparent',
      pointRadius: 0,
      tension: 0,
      fill: '+1',
      hidden: false,
      legendIgnore: true,
    }});
    datasets.push({{
      label: stream + ' lower 80%',
      data: fullLo,
      borderColor: 'transparent',
      backgroundColor: color + '33',  // ~20% opacity
      pointRadius: 0,
      tension: 0,
      fill: false,
      legendIgnore: true,
    }});
  }});

  const ctx = document.getElementById('streamChart').getContext('2d');
  new Chart(ctx, {{
    type: 'line',
    data: {{ labels: labels, datasets: datasets }},
    options: {{
      responsive: true,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{
          labels: {{
            filter: function(item) {{
              const d = item.text || '';
              return !d.includes('upper 80%') && !d.includes('lower 80%');
            }},
            font: {{ family: 'Poppins' }},
          }}
        }},
        tooltip: {{
          callbacks: {{
            label: function(ctx) {{
              const v = ctx.parsed.y;
              if (v == null) return '';
              const formatted = v < 0
                ? '$(' + Math.abs(v).toLocaleString() + ')'
                : '$' + v.toLocaleString();
              return ctx.dataset.label + ': ' + formatted;
            }}
          }}
        }}
      }},
      scales: {{
        y: {{
          ticks: {{
            callback: function(v) {{
              if (v < 0) return '$(' + Math.abs(v / 1e6).toFixed(0) + 'M)';
              return '$' + (v / 1e6).toFixed(0) + 'M';
            }},
            font: {{ family: 'JetBrains Mono' }}
          }}
        }},
        x: {{
          ticks: {{ font: {{ family: 'JetBrains Mono' }} }}
        }}
      }}
    }}
  }});
}})();

// Tippy tooltips on .info-btn — short description by default, expands to full on click.
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
      const code = el.dataset.code || '';
      const title = el.dataset.title || '';
      const short = el.dataset.short || '';
      const full = el.dataset.full || '';
      let html = '<div class="code-tip-header">' + code + ' — ' + title + '</div>';
      if (short) html += '<div class="code-tip-short">' + short + '</div>';
      if (full && full !== short) {{
        html += '<button class="code-tip-full-toggle">Show full description</button>';
        html += '<div class="code-tip-full" style="display:none;">' + full + '</div>';
      }}
      return html;
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


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    con = duckdb.connect(args.db, read_only=True)
    district_id, district_name = resolve_district(con, args.district)
    print(f"[report-funding-projection] district={district_id} ({district_name}) "
          f"scenario={args.scenario}")

    history = fetch_history(con, district_id)
    projections = fetch_projections(con, district_id, args.scenario)
    top_codes = fetch_top_codes(con, district_id, args.scenario)
    methodology = fetch_methodology(con, district_id, args.scenario)
    charter_breakdown = fetch_charter_breakdown(con, district_id)
    local_composition = fetch_local_composition(con, district_id)

    if not projections:
        sys.exit(f"No projections found for {district_name} ({district_id}) "
                 f"under scenario={args.scenario}. Run "
                 "scripts/build_funding_projections.py first.")

    html_content = render_html(
        district_id, district_name, args.scenario,
        history, projections, top_codes, methodology, PARTIAL_FY25_DISTRICTS,
        charter_breakdown=charter_breakdown,
        local_composition=local_composition,
    )

    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(
        args.output_dir,
        f"funding_projection_{district_id}_{args.scenario}_{timestamp}.html",
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"[report-funding-projection] wrote {output_path}")
    print(f"[report-funding-projection] {len(top_codes)} top codes, "
          f"{methodology.get('trend_ols', 0) + methodology.get('trend_ols_2fy', 0)} trend rows, "
          f"{methodology.get('sunset_zero', 0)} sunset zeros, "
          f"{methodology.get('insufficient_history', 0)} insufficient")
    if district_name in PARTIAL_FY25_DISTRICTS:
        print(f"[report-funding-projection] WARNING: {district_name} is in the "
              "partial-FY25 list; projection may overshoot.")

    con.close()


if __name__ == "__main__":
    sys.exit(main())
