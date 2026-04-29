"""HTML rendering for the four report flavors. SCDE design tokens; no JS frameworks except the YTD chart's inline Recharts."""
from __future__ import annotations

import html
from datetime import date
from typing import Any

# ──────────────────────────────────────────────────────────────────────
# Currency / number formatting
# ──────────────────────────────────────────────────────────────────────


def fmt_money(v: float | int | None, *, zero_dash: bool = False) -> str:
    """Accounting-parentheses negatives. Zero is $0 (or em-dash if zero_dash)."""
    if v is None:
        return "n/a"
    n = round(float(v))
    if n == 0:
        return "—" if zero_dash else "$0"
    if n < 0:
        return f"$({abs(n):,})"
    return f"${n:,}"


def fmt_pp(v: float | int | None) -> str:
    """Per-pupil currency, no decimals."""
    return fmt_money(v)


def fmt_int(v: int | None) -> str:
    return f"{v:,}" if v is not None else "n/a"


def fmt_money_si(v: float | int | None) -> str:
    """SI-suffix currency for chart axis ticks. Negatives in accounting parens."""
    if v is None:
        return "n/a"
    n = float(v)
    if n == 0:
        return "$0"
    a = abs(n)
    if a >= 1e9:
        s = f"{a/1e9:.1f}B"
    elif a >= 1e6:
        s = f"{a/1e6:.1f}M"
    elif a >= 1e3:
        s = f"{a/1e3:.0f}K"
    else:
        s = f"{a:.0f}"
    return f"$({s})" if n < 0 else f"${s}"


def fmt_fy(fy: int) -> str:
    """Two-year format per style-guide §5.6 (e.g. FY2024 -> 'FY23-24')."""
    return f"FY{(fy-1)%100:02d}-{fy%100:02d}"


# ──────────────────────────────────────────────────────────────────────
# Categorical chart palette — Okabe-Ito (style-guide §1.3 / tokens.json)
# Index 0 swapped to SCDE dark blue, index 7 swapped from yellow to gray.
# Gold (#F1BA55, brand.accent) is decorative-only and NEVER appears here.
# ──────────────────────────────────────────────────────────────────────

CATEGORICAL_PALETTE = [
    "#234058",  # 0 SCDE dark blue
    "#E69F00",  # 1 Okabe-Ito orange
    "#56B4E9",  # 2 Okabe-Ito sky
    "#009E73",  # 3 Okabe-Ito green
    "#CC79A7",  # 4 Okabe-Ito reddish-purple
    "#0072B2",  # 5 Okabe-Ito blue
    "#D55E00",  # 6 Okabe-Ito vermillion
    "#666666",  # 7 Neutral dark gray (replaces failing-AA yellow)
]
GRIDLINE_COLOR = "#CBD5E0"  # border_subtle
GRIDLINE_OPACITY = "0.5"
DANGER_FG = "#B3261E"  # semantic.danger


def _legend_html(items: list[tuple[str, str]]) -> str:
    """HTML legend below an SVG chart — uses inline styles so it renders
    correctly even if the report's class-based CSS is absent. items =
    [(color_hex, label), ...]."""
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;font:11px/1 Poppins,system-ui,sans-serif;color:#2F3D4C">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;background:{c};border:1px solid rgba(47,61,76,0.15);flex-shrink:0"></span>'
        f'{html.escape(l)}</span>'
        for c, l in items
    )
    return f'<div style="display:flex;flex-wrap:wrap;gap:12px 18px;padding:8px 4px 0">{chips}</div>'


def _wrap(body: str) -> str:
    """Wrap a rendered report body with the inline <style> block so reports
    are self-contained and don't depend on the dashboard's CSS."""
    return f"<style>{REPORT_CSS}</style>{body}{TIPPY_BUNDLE}"


def code_info_button(code: str, title: str | None,
                     short_desc: str | None, full_desc: str | None,
                     max_full_chars: int = 600) -> str:
    """
    Render a small "i" button next to a Revenue_Code that surfaces
    Short_Description on click via Tippy.js, with a "Show full" toggle
    that expands to Full_Description (truncated at max_full_chars).
    Returns inline HTML; the Tippy init script reads data-* attributes.
    """
    if not short_desc and not full_desc:
        return ""
    full_part = html.escape(full_desc or "")
    if full_part and len(full_part) > max_full_chars:
        full_part = full_part[:max_full_chars].rsplit(" ", 1)[0] + "…"
    return (
        f'<button class="info-btn" '
        f'data-code="{html.escape(code)}" '
        f'data-title="{html.escape(title or code)}" '
        f'data-short="{html.escape(short_desc or "")}" '
        f'data-full="{full_part}" '
        f'aria-label="Show description for code {html.escape(code)}">i</button>'
    )


# ──────────────────────────────────────────────────────────────────────
# Shared CSS — SCDE tokens
# ──────────────────────────────────────────────────────────────────────

REPORT_CSS = """
:root {
  --brand-primary: #2F3D4C;
  --brand-secondary: #234058;
  --brand-tertiary: #43718B;
  --brand-accent: #F1BA55;
  --semantic-success: #1F7A3A;
  --semantic-warning: #8A5A00;
  --semantic-danger: #B3261E;
  --semantic-info: #234058;
  --neutral-bg: #F4F6F8;
  --neutral-fg: #2F3D4C;
  --border: #7E8C9E;
  --border-subtle: #CBD5E0;
  --font-display: 'Poppins', 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Consolas', monospace;
}
.scde-report {
  font-family: var(--font-display);
  color: var(--neutral-fg);
  background: #fff;
  padding: 24px;
  font-size: 14px;
  line-height: 1.4;
}
.scde-report h1 { font-size: 22px; margin: 0 0 4px 0; color: var(--brand-primary); }
.scde-report h2 { font-size: 16px; margin: 16px 0 8px 0; color: var(--brand-secondary); border-bottom: 1px solid var(--border-subtle); padding-bottom: 4px; }
.scde-report .meta { color: var(--brand-tertiary); font-size: 12px; margin-bottom: 16px; }
.scde-report table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }
.scde-report th, .scde-report td { padding: 6px 10px; border-bottom: 1px solid var(--border-subtle); text-align: left; vertical-align: top; }
.scde-report th { background: var(--neutral-bg); color: var(--brand-primary); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.04em; position: sticky; top: 0; }
.scde-report td.num, .scde-report th.num { text-align: right; font-family: var(--font-mono); white-space: nowrap; }
.scde-report tr.subtotal td, .scde-report tr.statewide td { font-weight: 600; background: var(--neutral-bg); border-top: 2px solid var(--brand-secondary); }
.scde-report tr.statewide td { background: var(--brand-primary); color: #fff; }
.scde-report tr.statewide td.num { color: var(--brand-accent); }
.scde-report .neg { color: var(--semantic-danger); }
.scde-report .stream-local { background: rgba(86, 180, 233, 0.08); }
.scde-report .stream-state { background: rgba(243, 186, 85, 0.08); }
.scde-report .stream-federal { background: rgba(204, 121, 167, 0.08); }
.scde-report .footer { margin-top: 24px; padding: 12px; background: var(--neutral-bg); border-left: 3px solid var(--brand-tertiary); font-size: 12px; color: var(--brand-tertiary); }
.scde-report .footer p { margin: 4px 0; }
.scde-report .badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-family: var(--font-mono); margin-left: 6px; }
.scde-report .badge.warn { background: #FBEFD9; color: var(--semantic-warning); border: 1px solid var(--semantic-warning); }
.scde-report .badge.info { background: #E5EAF0; color: var(--semantic-info); border: 1px solid var(--semantic-info); }
.scde-report .badge.danger { background: #F8E2E0; color: var(--semantic-danger); border: 1px solid var(--semantic-danger); }
.scde-report .kpi-row { display: flex; gap: 16px; margin: 12px 0; flex-wrap: wrap; }
.scde-report .kpi { background: var(--neutral-bg); padding: 12px 16px; border-radius: 8px; min-width: 140px; }
.scde-report .kpi-label { font-size: 11px; text-transform: uppercase; color: var(--brand-tertiary); letter-spacing: 0.04em; }
.scde-report .kpi-value { font-size: 22px; font-family: var(--font-mono); font-weight: 600; color: var(--brand-primary); margin-top: 2px; }
.scde-report figure { margin: 0; }
.scde-report .chart-legend { display: flex; flex-wrap: wrap; gap: 12px 18px; padding: 8px 4px 0; font-size: 11px; color: var(--neutral-fg); }
.scde-report .chart-legend .legend-item { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-display); }
.scde-report .chart-legend .swatch { display: inline-block; width: 12px; height: 12px; border-radius: 2px; border: 1px solid rgba(47,61,76,0.15); flex-shrink: 0; }
.scde-report .code-cell { white-space: nowrap; }
.scde-report .info-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; margin-left: 4px; padding: 0;
  border: 1px solid var(--brand-tertiary); background: white;
  color: var(--brand-tertiary); border-radius: 50%;
  font-family: var(--font-display); font-size: 10px; font-weight: 700;
  font-style: italic; cursor: pointer; line-height: 1; vertical-align: middle;
  transition: background 120ms ease, color 120ms ease;
}
.scde-report .info-btn:hover, .scde-report .info-btn:focus {
  background: var(--brand-tertiary); color: white; outline: none;
}
.tippy-content .code-tip-header { font-weight: 600; color: var(--brand-primary); margin-bottom: 6px; font-size: 13px; }
.tippy-content .code-tip-short { font-size: 12px; color: var(--neutral-fg); margin-bottom: 8px; line-height: 1.4; }
.tippy-content .code-tip-full { font-size: 11px; color: var(--neutral-fg); line-height: 1.45; border-top: 1px solid var(--border-subtle); padding-top: 6px; max-height: 180px; overflow-y: auto; }
.tippy-content .code-tip-full-toggle { font-size: 11px; color: var(--brand-tertiary); cursor: pointer; text-decoration: underline; background: none; border: none; padding: 0; font-family: inherit; }
"""

TIPPY_BUNDLE = """
<script src="https://unpkg.com/@popperjs/core@2"></script>
<script src="https://unpkg.com/tippy.js@6"></script>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/themes/light-border.css">
<script>
(function() {
  if (typeof tippy === 'undefined') return;
  if (window.__scdeInfoTippyInit) { window.__scdeInfoTippyInit(); return; }
  window.__scdeInfoTippyInit = function() {
    document.querySelectorAll('.info-btn').forEach(function(el) {
      if (el._tippy) return;
      tippy(el, {
        theme: 'light-border',
        allowHTML: true, interactive: true, trigger: 'click',
        appendTo: function() { return document.body; },
        placement: 'top', maxWidth: 360,
        content: function(node) {
          var code = node.dataset.code || '';
          var title = node.dataset.title || '';
          var short = node.dataset.short || '';
          var full = node.dataset.full || '';
          var html = '<div class="code-tip-header">' + code + ' — ' + title + '</div>';
          if (short) html += '<div class="code-tip-short">' + short + '</div>';
          if (full && full !== short) {
            html += '<button class="code-tip-full-toggle">Show full description</button>';
            html += '<div class="code-tip-full" style="display:none;">' + full + '</div>';
          }
          return html;
        },
        onShown: function(instance) {
          var btn = instance.popper.querySelector('.code-tip-full-toggle');
          if (!btn) return;
          btn.addEventListener('click', function() {
            var full = instance.popper.querySelector('.code-tip-full');
            if (full.style.display === 'none') {
              full.style.display = 'block';
              btn.textContent = 'Hide full description';
            } else {
              full.style.display = 'none';
              btn.textContent = 'Show full description';
            }
          });
        },
      });
    });
  };
  window.__scdeInfoTippyInit();
})();
</script>
"""


def _money_cell(v: float | int | None) -> str:
    s = fmt_money(v)
    cls = " neg" if (v is not None and v < 0) else ""
    return f'<td class="num{cls}">{html.escape(s)}</td>'


def _pp_cell(v: float | int | None) -> str:
    return _money_cell(v)


def _stream_class(bucket: str) -> str:
    if bucket.startswith("Local"):
        return "stream-local"
    if "State" in bucket:
        return "stream-state"
    if "Federal" in bucket:
        return "stream-federal"
    return ""


# ──────────────────────────────────────────────────────────────────────
# Detail report
# ──────────────────────────────────────────────────────────────────────


def render_detail(data: dict[str, Any]) -> str:
    d = data["district"]
    fy = data["fy"]
    items = data["items"]
    hc = data["headcount"]
    state_sceis = data["sceis_state_total"]
    federal_sceis = data["sceis_federal_total"]

    if not data["reported"]:
        body = f"""
        <div class="kpi-row">
          <div class="kpi"><div class="kpi-label">SCEIS State Total</div><div class="kpi-value">{html.escape(fmt_money(state_sceis))}</div></div>
          <div class="kpi"><div class="kpi-label">SCEIS Federal Total</div><div class="kpi-value">{html.escape(fmt_money(federal_sceis))}</div></div>
          <div class="kpi"><div class="kpi-label">Headcount (SY{fy})</div><div class="kpi-value">{html.escape(fmt_int(hc))}</div></div>
        </div>
        <p class="badge danger">Not reported by district in LEA self-report. SCEIS state-side totals shown above.</p>
        """
    else:
        # Group items by Stream → Category for nesting
        grouped: dict[str, dict[str, list[dict]]] = {}
        for it in items:
            stream = it["stream"] or "Uncategorized"
            cat = it["category"] or "—"
            grouped.setdefault(stream, {}).setdefault(cat, []).append(it)

        rows_html = []
        grand_total = 0.0
        for stream in ("Local", "State", "Federal", "Uncategorized"):
            if stream not in grouped:
                continue
            stream_total = 0.0
            for cat, leaves in grouped[stream].items():
                for it in leaves:
                    grand_total += it["amount"]
                    stream_total += it["amount"]
                    cls = _stream_class((it["bucket"] or stream))
                    desc = html.escape(it["full_name"] or it["display_title"] or "")
                    code = html.escape(it["code"])
                    cat_label = html.escape(cat)
                    info_btn = code_info_button(
                        it["code"],
                        it["full_name"] or it["display_title"],
                        it["short_description"],
                        it.get("full_description"),
                    )
                    rows_html.append(
                        f'<tr class="{cls}">'
                        f'<td class="code-cell"><span class="badge info">{code}</span> {info_btn}</td>'
                        f'<td>{cat_label}</td>'
                        f'<td>{desc}</td>'
                        f'{_money_cell(it["amount"])}'
                        f'</tr>'
                    )
                rows_html.append(
                    f'<tr class="subtotal"><td colspan="3">{html.escape(stream)} subtotal</td>'
                    f'{_money_cell(stream_total)}</tr>'
                ) if False else None  # subtotals per stream below instead
            rows_html.append(
                f'<tr class="subtotal"><td colspan="3">Subtotal — {html.escape(stream)} (LEA)</td>'
                f'{_money_cell(stream_total)}</tr>'
            )

        rows_html.append(
            f'<tr class="statewide"><td colspan="3">Grand Total (LEA self-report)</td>'
            f'{_money_cell(grand_total)}</tr>'
        )

        body = f"""
        <div class="kpi-row">
          <div class="kpi"><div class="kpi-label">Grand Total (LEA)</div><div class="kpi-value">{html.escape(fmt_money(grand_total))}</div></div>
          <div class="kpi"><div class="kpi-label">SCEIS State Total</div><div class="kpi-value">{html.escape(fmt_money(state_sceis))}</div></div>
          <div class="kpi"><div class="kpi-label">SCEIS Federal Total</div><div class="kpi-value">{html.escape(fmt_money(federal_sceis))}</div></div>
          <div class="kpi"><div class="kpi-label">Headcount (SY{fy})</div><div class="kpi-value">{html.escape(fmt_int(hc))}</div></div>
          <div class="kpi"><div class="kpi-label">Per-Pupil (LEA)</div><div class="kpi-value">{html.escape(fmt_pp(grand_total/hc) if hc else 'n/a')}</div></div>
        </div>
        <table>
          <thead>
            <tr><th>Code</th><th>Category</th><th>Description</th><th class="num">Amount</th></tr>
          </thead>
          <tbody>
            {''.join(r for r in rows_html if r)}
          </tbody>
        </table>
        """

    footer = _methodology_footer(
        single_district=True,
        notes=[
            "LEA self-report rows are filtered to <code>Reported_Flag = TRUE</code>.",
            "SCEIS State Total and Federal Total come from <code>vw_sceis_fi_payments_classified</code> and may not equal the LEA-sourced subtotals (no GL→Revenue_Code bridge yet).",
            f"Headcount denominator is <code>lea_headcounts.Total_Active_Enrollment</code> for SY {fy} (latest Report_Cycle).",
        ],
    )

    return _wrap(f"""
    <div class="scde-report">
      <h1>{html.escape(d['name'])} — Detail Revenue, {fmt_fy(fy)}</h1>
      <div class="meta">District {html.escape(d['id'])} · generated {date.today().isoformat()}</div>
      {body}
      {footer}
    </div>
    """)


# ──────────────────────────────────────────────────────────────────────
# Single-FY comparison
# ──────────────────────────────────────────────────────────────────────


def render_compare_table(data: dict[str, Any]) -> str:
    fy = data["fy"]
    rows = data["rows"]
    buckets = data["buckets"]
    sw = data["statewide"]

    head = (
        '<tr><th>District</th><th class="num">Headcount</th>'
        + ''.join(f'<th class="num">{html.escape(b)}</th>' for b in buckets)
        + '<th class="num">Total</th><th class="num">Per Pupil</th></tr>'
    )

    body_rows = []
    for r in rows:
        hc = r["headcount"]
        cells = [
            f'<td>{html.escape(r["district_name"] or r["district_id"])}</td>',
            f'<td class="num">{fmt_int(hc)}</td>',
        ]
        for b in buckets:
            cells.append(_money_cell(r["buckets"][b]))
        cells.append(_money_cell(r["grand_total"]))
        cells.append(_pp_cell(r["per_pupil_total"]))
        body_rows.append(f'<tr>{"".join(cells)}</tr>')

    sw_cells = [
        '<td>South Carolina (weighted)</td>',
        f'<td class="num">{fmt_int(sw["headcount"])}</td>',
    ]
    for b in buckets:
        sw_cells.append(_money_cell(sw["buckets"][b]))
    sw_cells.append(_money_cell(sw["grand_total"]))
    sw_cells.append(_pp_cell(sw["per_pupil_total"]))
    body_rows.append(f'<tr class="statewide">{"".join(sw_cells)}</tr>')

    footer = _methodology_footer(
        single_district=False,
        notes=[
            "LEA-sourced sub-buckets are filtered to <code>Reported_Flag = TRUE</code>.",
            "State and Federal totals come from SCEIS (<code>vw_sceis_fi_payments_classified</code>); LEA-sourced State/Federal may not equal these (no GL→Revenue_Code bridge yet).",
            "Statewide totals use weighted averages (sum of dollars / sum of pupils), not arithmetic means.",
        ],
    )

    return _wrap(f"""
    <div class="scde-report">
      <h1>District Revenue Comparison — {fmt_fy(fy)}</h1>
      <div class="meta">All districts · generated {date.today().isoformat()}</div>
      <table>
        <thead>{head}</thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
      {footer}
    </div>
    """)


def render_compare_chart(data: dict[str, Any]) -> str:
    """Stacked-bar view of compare-table data. SVG; no library."""
    fy = data["fy"]
    rows = data["rows"]
    buckets = data["buckets"]
    # Order rows by per-pupil total desc, drop districts with no headcount
    plot_rows = [r for r in rows if r.get("per_pupil_total") is not None]
    plot_rows.sort(key=lambda r: r["per_pupil_total"] or 0, reverse=True)

    if not plot_rows:
        return _wrap(f'<div class="scde-report"><h1>{fmt_fy(fy)} Comparison Chart</h1><p>No data.</p></div>')

    color_for = {b: CATEGORICAL_PALETTE[i % len(CATEGORICAL_PALETTE)] for i, b in enumerate(buckets)}

    max_pp = max((r["per_pupil_total"] or 0) for r in plot_rows)
    bar_h = 14
    gap = 4
    label_w = 240
    chart_w = 700
    top_pad = 20
    bot_pad = 20
    h = top_pad + (bar_h + gap) * len(plot_rows) + bot_pad
    w = label_w + chart_w + 80

    bars_svg = []
    for i, r in enumerate(plot_rows):
        y = top_pad + i * (bar_h + gap)
        x0 = label_w
        bars_svg.append(
            f'<text x="{label_w-8}" y="{y+bar_h-3}" text-anchor="end" font-size="11" fill="#2F3D4C">{html.escape(r["district_name"][:30])}</text>'
        )
        for b in buckets:
            v_pp = (r["buckets"][b] / r["headcount"]) if r["headcount"] else 0
            seg_w = (v_pp / max_pp) * chart_w if max_pp > 0 else 0
            if seg_w > 0:
                bars_svg.append(
                    f'<rect x="{x0:.1f}" y="{y}" width="{seg_w:.1f}" height="{bar_h}" fill="{color_for[b]}"><title>{html.escape(b)}: {fmt_money(v_pp)}/pupil</title></rect>'
                )
                x0 += seg_w
        # Total label at end of bar — SI-suffixed, danger color if negative
        v = r["per_pupil_total"] or 0
        lbl_fill = DANGER_FG if v < 0 else "#2F3D4C"
        bars_svg.append(
            f'<text x="{x0+4:.1f}" y="{y+bar_h-3}" font-size="10" font-family="JetBrains Mono,monospace" fill="{lbl_fill}">{html.escape(fmt_money_si(v))}</text>'
        )

    legend_html = _legend_html([(color_for[b], b) for b in buckets])

    footer = _methodology_footer(
        single_district=False,
        notes=[
            "Bars are revenue per pupil (weighted by headcount).",
            "State and Federal segments use SCEIS; Local sub-buckets use LEA self-report (filtered Reported_Flag=TRUE).",
            "Sorted descending by total per-pupil revenue.",
        ],
    )

    return _wrap(f"""
    <div class="scde-report">
      <h1>{fmt_fy(fy)} District Revenue Comparison</h1>
      <div class="meta">Per-pupil, all reporting districts · generated {date.today().isoformat()}</div>
      <figure>
        <svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMinYMin meet" style="max-width:1100px;display:block" role="img" aria-labelledby="cmpcap">
          {''.join(bars_svg)}
        </svg>
        {legend_html}
        <figcaption id="cmpcap" style="font-size:12px;color:#43718B;margin-top:4px">Stacked horizontal bars; revenue per pupil; sorted desc.</figcaption>
      </figure>
      {footer}
    </div>
    """)


# ──────────────────────────────────────────────────────────────────────
# Multi-FY for one district
# ──────────────────────────────────────────────────────────────────────


def render_multi_fy(data: dict[str, Any]) -> str:
    d = data["district"]
    rows = data["rows"]
    buckets = data["buckets"]

    head = (
        '<tr><th>FY</th><th class="num">Headcount</th>'
        + ''.join(f'<th class="num">{html.escape(b)}</th>' for b in buckets)
        + '<th class="num">Total</th><th class="num">Per Pupil</th></tr>'
    )
    body_rows = []
    for r in rows:
        cells = [
            f'<td>{fmt_fy(r["fy"])}</td>',
            f'<td class="num">{fmt_int(r["headcount"])}</td>',
        ]
        for b in buckets:
            cells.append(_money_cell(r["buckets"][b]))
        cells.append(_money_cell(r["grand_total"]))
        cells.append(_pp_cell(r["per_pupil_total"]))
        cls = "" if r["reported"] else ' class="subtotal"'
        body_rows.append(f'<tr{cls}>{"".join(cells)}</tr>')

    # YoY chart — simple line per bucket
    chart_svg = _multi_fy_chart_svg(rows, buckets)

    footer = _methodology_footer(
        single_district=True,
        notes=[
            "Each row = one FY. Buckets and per-pupil rules match the single-FY comparison.",
            "Rows where the district did not submit LEA data (Reported_Flag=FALSE everywhere) are flagged.",
        ],
    )

    return _wrap(f"""
    <div class="scde-report">
      <h1>{html.escape(d['name'])} — Multi-Year Revenue</h1>
      <div class="meta">District {html.escape(d['id'])} · generated {date.today().isoformat()}</div>
      <table>
        <thead>{head}</thead>
        <tbody>{''.join(body_rows)}</tbody>
      </table>
      <h2>Per-pupil trend</h2>
      {chart_svg}
      {footer}
    </div>
    """)


def _multi_fy_chart_svg(rows: list[dict], buckets: list[str]) -> str:
    if not rows:
        return "<p>No data.</p>"
    w, h = 720, 280
    pad_l, pad_r, pad_t, pad_b = 70, 16, 20, 40

    fys = [r["fy"] for r in rows]
    if not fys:
        return "<p>No data.</p>"
    x_step = (w - pad_l - pad_r) / max(1, len(fys) - 1) if len(fys) > 1 else 0
    max_pp = max(
        (r["per_pupil"][b] or 0) for r in rows for b in buckets if r["per_pupil"]
    ) or 1
    y_scale = (h - pad_t - pad_b) / max_pp

    def x_for(i): return pad_l + i * x_step if len(fys) > 1 else (w - pad_l - pad_r) / 2 + pad_l
    def y_for(v): return h - pad_b - (v or 0) * y_scale

    tilt = len(fys) > 6
    grid = [f'<line x1="{pad_l}" y1="{h-pad_b}" x2="{w-pad_r}" y2="{h-pad_b}" stroke="{GRIDLINE_COLOR}" stroke-opacity="{GRIDLINE_OPACITY}"/>']
    for i, fy in enumerate(fys):
        x = x_for(i)
        label = fmt_fy(fy)
        if tilt:
            grid.append(f'<text x="{x}" y="{h-pad_b+14}" font-size="11" text-anchor="end" fill="#43718B" transform="rotate(-45 {x} {h-pad_b+14})">{label}</text>')
        else:
            grid.append(f'<text x="{x}" y="{h-pad_b+14}" font-size="11" text-anchor="middle" fill="#43718B">{label}</text>')
    # Y-axis ticks (4) with SI-suffix labels
    for k in range(5):
        v = max_pp * k / 4
        y = y_for(v)
        grid.append(
            f'<line x1="{pad_l}" y1="{y}" x2="{w-pad_r}" y2="{y}" stroke="{GRIDLINE_COLOR}" stroke-opacity="{GRIDLINE_OPACITY}" stroke-dasharray="2 4"/>'
            f'<text x="{pad_l-6}" y="{y+3}" text-anchor="end" font-size="10" font-family="JetBrains Mono,monospace" fill="#43718B">{html.escape(fmt_money_si(v))}</text>'
        )

    lines = []
    legend_pairs: list[tuple[str, str]] = []
    for bi, b in enumerate(buckets):
        col = CATEGORICAL_PALETTE[bi % len(CATEGORICAL_PALETTE)]
        pts = []
        for i, r in enumerate(rows):
            v = (r["per_pupil"] or {}).get(b, 0) or 0
            pts.append(f"{x_for(i):.1f},{y_for(v):.1f}")
        if pts:
            lines.append(f'<polyline fill="none" stroke="{col}" stroke-width="2" points="{" ".join(pts)}"/>')
            for p in pts:
                x, y = p.split(",")
                lines.append(f'<circle cx="{x}" cy="{y}" r="3" fill="{col}"/>')
        legend_pairs.append((col, b))

    svg = (
        f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:900px;display:block" '
        f'role="img" aria-label="Multi-year per-pupil revenue trend by bucket">'
        f'{"".join(grid)}{"".join(lines)}</svg>'
    )
    return svg + _legend_html(legend_pairs)


# ──────────────────────────────────────────────────────────────────────
# YTD monthly
# ──────────────────────────────────────────────────────────────────────


def render_ytd_chart(data: dict[str, Any]) -> str:
    d = data["district"]
    fy = data["fy"]
    rows = data["rows"]

    if not rows:
        return _wrap(f'<div class="scde-report"><h1>{html.escape(d["name"])} — {fmt_fy(fy)} YTD</h1><p>No SCEIS data for this district + FY.</p></div>')

    # Stream → palette index. State=0 (SCDE blue, primary), Federal=1 (orange,
    # high-contrast against blue), Other=7 (neutral gray).
    stream_idx = {"State": 0, "Federal": 1, "Other": 7}
    streams = sorted({s for r in rows for s in r["streams"]})
    palette = {s: CATEGORICAL_PALETTE[stream_idx.get(s, 4)] for s in streams}

    w, h = 760, 320
    pad_l, pad_r, pad_t, pad_b = 70, 16, 20, 64
    n = len(rows)
    bar_w = (w - pad_l - pad_r) / n * 0.7
    step = (w - pad_l - pad_r) / n
    tilt = n > 6

    max_total = max((r["total"] for r in rows), default=1) or 1
    y_scale = (h - pad_t - pad_b) / max_total
    def y_for(v): return h - pad_b - (v or 0) * y_scale

    bars = []
    for i, r in enumerate(rows):
        x = pad_l + i * step + (step - bar_w) / 2
        y_cursor = h - pad_b
        for s in streams:
            v = r["streams"].get(s, 0) or 0
            seg_h = v * y_scale
            color = palette.get(s, "#999999")
            bars.append(
                f'<rect x="{x:.1f}" y="{(y_cursor-seg_h):.1f}" width="{bar_w:.1f}" height="{seg_h:.1f}" fill="{color}">'
                f'<title>{html.escape(s)} {r["year"]}-{r["month"]:02d}: {fmt_money(v)}</title></rect>'
            )
            y_cursor -= seg_h
        # Month label — tilt 45° when >6 ticks per style-guide §5.6
        cx = x + bar_w / 2
        m_lbl = f'{r["year"]}-{r["month"]:02d}'
        if tilt:
            bars.append(
                f'<text x="{cx:.1f}" y="{h-pad_b+14}" font-size="10" text-anchor="end" fill="#43718B" transform="rotate(-45 {cx:.1f} {h-pad_b+14})">{m_lbl}</text>'
            )
        else:
            bars.append(
                f'<text x="{cx:.1f}" y="{h-pad_b+14}" font-size="10" text-anchor="middle" fill="#43718B">{m_lbl}</text>'
            )
        # Total above bar — SI-suffix; danger color if negative
        v_total = r["total"] or 0
        lbl_fill = DANGER_FG if v_total < 0 else "#2F3D4C"
        bars.append(
            f'<text x="{cx:.1f}" y="{(y_for(v_total)-3):.1f}" font-size="9" text-anchor="middle" font-family="JetBrains Mono,monospace" fill="{lbl_fill}">{html.escape(fmt_money_si(v_total))}</text>'
        )

    # Y-axis ticks — SI-suffixed
    grid = []
    for k in range(5):
        v = max_total * k / 4
        y = y_for(v)
        grid.append(
            f'<line x1="{pad_l}" y1="{y}" x2="{w-pad_r}" y2="{y}" stroke="{GRIDLINE_COLOR}" stroke-opacity="{GRIDLINE_OPACITY}" stroke-dasharray="2 4"/>'
            f'<text x="{pad_l-6}" y="{y+3}" text-anchor="end" font-size="10" font-family="JetBrains Mono,monospace" fill="#43718B">{html.escape(fmt_money_si(v))}</text>'
        )

    legend_html = _legend_html([(palette.get(s, "#999"), s) for s in streams])

    grand = sum(r["total"] for r in rows)
    txn_count = sum(r["count"] for r in rows)

    footer = _methodology_footer(
        single_district=True,
        notes=[
            f"Source: <code>vw_sceis_fi_payments_classified</code> · {html.escape(str(data.get('data_through','')))} latest posting date",
            "State / Federal split is via the classification view's regex rules (~22 patterns).",
            "Months shown are calendar months; SC fiscal year runs July 1 – June 30.",
        ],
    )

    return _wrap(f"""
    <div class="scde-report">
      <h1>{html.escape(d['name'])} — {fmt_fy(fy)} Year-to-Date by Month</h1>
      <div class="meta">District {html.escape(d['id'])} · {fmt_int(txn_count)} SCEIS transactions · grand total {html.escape(fmt_money(grand))}</div>
      <figure>
        <svg viewBox="0 0 {w} {h}" width="100%" style="max-width:1000px;display:block" role="img" aria-labelledby="ytdcap">
          {''.join(grid)}
          {''.join(bars)}
        </svg>
        {legend_html}
        <figcaption id="ytdcap" style="font-size:12px;color:#43718B;margin-top:4px">Stacked monthly SCEIS payments by funding stream.</figcaption>
      </figure>
      {footer}
    </div>
    """)


def render_ytd_detail(data: dict[str, Any]) -> str:
    d = data["district"]
    fy = data["fy"]
    rows = data["rows"]

    if not rows:
        return _wrap(f'<div class="scde-report"><h1>{html.escape(d["name"])} — {fmt_fy(fy)} YTD Detail</h1><p>No SCEIS data.</p></div>')

    streams = sorted({s for r in rows for s in r["streams"]})
    head = (
        '<tr><th>Month</th><th class="num">Txns</th>'
        + ''.join(f'<th class="num">{html.escape(s)}</th>' for s in streams)
        + '<th class="num">Total</th></tr>'
    )
    body = []
    totals_by_stream = {s: 0.0 for s in streams}
    grand = 0.0
    txn_total = 0
    for r in rows:
        cells = [
            f'<td>{r["year"]}-{r["month"]:02d}</td>',
            f'<td class="num">{fmt_int(r["count"])}</td>',
        ]
        for s in streams:
            v = r["streams"].get(s, 0) or 0
            cells.append(_money_cell(v))
            totals_by_stream[s] += v
        cells.append(_money_cell(r["total"]))
        body.append(f'<tr>{"".join(cells)}</tr>')
        grand += r["total"]
        txn_total += r["count"]

    foot_cells = [
        '<td>Total</td>',
        f'<td class="num">{fmt_int(txn_total)}</td>',
    ]
    for s in streams:
        foot_cells.append(_money_cell(totals_by_stream[s]))
    foot_cells.append(_money_cell(grand))
    body.append(f'<tr class="statewide">{"".join(foot_cells)}</tr>')

    footer = _methodology_footer(
        single_district=True,
        notes=[
            f"Source: <code>vw_sceis_fi_payments_classified</code> · data through {html.escape(str(data.get('data_through','')))}",
        ],
    )

    return _wrap(f"""
    <div class="scde-report">
      <h1>{html.escape(d['name'])} — {fmt_fy(fy)} YTD Monthly Detail</h1>
      <div class="meta">District {html.escape(d['id'])} · generated {date.today().isoformat()}</div>
      <table>
        <thead>{head}</thead>
        <tbody>{''.join(body)}</tbody>
      </table>
      {footer}
    </div>
    """)


# ──────────────────────────────────────────────────────────────────────
# Methodology footer
# ──────────────────────────────────────────────────────────────────────


def _methodology_footer(*, single_district: bool, notes: list[str]) -> str:
    lis = "".join(f"<p>· {n}</p>" for n in notes)
    return f"""
    <div class="footer">
      <strong>Methodology</strong>
      {lis}
      <p>· Excluded entities (special schools / state-agency schools): 5205, 5207, 5208, 5209, 5364, 5395 (per <code>lookup_district_exclusions</code>).</p>
      <p>· Negatives are rendered with accounting parentheses, e.g. $(1,234).</p>
    </div>
    """
