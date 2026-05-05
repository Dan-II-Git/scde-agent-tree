"""HTML rendering for the internal budget vs actuals dashboard."""
from __future__ import annotations

import html
from typing import Any


# ─────────────────────────── formatters ───────────────────────────

def fmt_money(v: float | int | None) -> str:
    if v is None:
        return "n/a"
    n = round(float(v))
    if n == 0:
        return "$0"
    if n < 0:
        return f"$({abs(n):,})"
    return f"${n:,}"


def fmt_money_si(v: float | int | None) -> str:
    if v is None:
        return "n/a"
    a = abs(float(v))
    if a >= 1e9:
        s = f"${a/1e9:.2f}B"
    elif a >= 1e6:
        s = f"${a/1e6:.1f}M"
    elif a >= 1e3:
        s = f"${a/1e3:.0f}K"
    else:
        s = f"${a:.0f}"
    if v < 0:
        return f"$({s[1:]})"
    return s


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v*100:.1f}%"


# ─────────────────────────── color logic ─────────────────────────────

def consumption_class(pct: float | None) -> str:
    """Map percent-consumed to a status color class. Used both on KPIs
    and the per-row badge."""
    if pct is None:
        return "consumed-unknown"
    if pct < 0:
        return "consumed-negative"          # over-budget (Available < 0)
    if pct >= 1.0:
        return "consumed-overspent"
    if pct >= 0.85:
        return "consumed-warning"
    if pct >= 0.5:
        return "consumed-on-track"
    return "consumed-light"


# ─────────────────────────── budget vs actuals ─────────────────────

def render_budget_vs_actuals(fy: int, totals: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    """Top-level page: agency KPIs + table of Funds Centers."""
    pct_class = consumption_class(totals.get("pct_consumed"))
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Total Budget</div>
        <div class="kpi-value">{fmt_money(totals.get('total_budget'))}</div></div>
      <div class="kpi"><div class="kpi-label">Actuals (consumed)</div>
        <div class="kpi-value">{fmt_money(totals.get('actuals'))}</div></div>
      <div class="kpi"><div class="kpi-label">Available</div>
        <div class="kpi-value">{fmt_money(totals.get('available'))}</div></div>
      <div class="kpi {pct_class}"><div class="kpi-label">% Consumed</div>
        <div class="kpi-value">{fmt_pct(totals.get('pct_consumed'))}</div></div>
      <div class="kpi"><div class="kpi-label">Funds Centers</div>
        <div class="kpi-value">{totals.get('leaf_count', 0)}</div></div>
    </div>
    """

    body_rows = []
    prev_dept = None
    for r in rows:
        cls = consumption_class(r["pct_consumed"])
        bar_pct = max(0.0, min(1.0, r["pct_consumed"] or 0)) * 100
        # Visual department divider: a thicker top-border between groups.
        dept_change = (r["department"] != prev_dept)
        prev_dept = r["department"]
        row_class = "dept-divider" if dept_change else ""
        if r["is_bus_child"]:
            row_class = (row_class + " bus-child").strip()
            name_cell = (
                f'<span class="ib-subrow-marker">↳</span>'
                f'<span class="ib-name-text">{html.escape(r["name"])}</span>'
            )
        else:
            name_cell = f'<span class="ib-name-text">{html.escape(r["name"])}</span>'
        body_rows.append(f"""
          <tr class="{row_class}" data-fc="{html.escape(r['funds_center'])}">
            <td class="ib-name-cell">{name_cell}</td>
            <td class="mono">{html.escape(r['funds_center'])}</td>
            <td class="num">{fmt_money(r['total_budget'])}</td>
            <td class="num">{fmt_money(r['actuals'])}</td>
            <td class="num">{fmt_money(r['available'])}</td>
            <td class="pct-cell">
              <div class="pct-track"><div class="pct-bar {cls}" style="width:{bar_pct:.1f}%"></div></div>
              <span class="pct-label {cls}">{fmt_pct(r['pct_consumed'])}</span>
            </td>
          </tr>
        """)

    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>FY{fy} Budget vs Actuals — All Funds Centers</h2>
        <p class="ib-report-meta">Sorted by department; click any row to drill into Commitment Items.
          Bus shops are nested under Transportation.
          Source: latest FMEDDW extract · GM-module actuals only.</p>
      </header>
      {kpi_html}
      <table class="ib-table ib-fc-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Funds Center</th>
            <th class="num">Total Budget</th>
            <th class="num">Actuals</th>
            <th class="num">Available</th>
            <th>% Consumed</th>
          </tr>
        </thead>
        <tbody>
          {''.join(body_rows)}
        </tbody>
      </table>
    </div>
    """


def _render_ci_block(title: str, total: float, items: list[dict[str, Any]],
                     amount_col: str, *, show_source: bool) -> str:
    """Render one of the two side-by-side Commitment Item tables."""
    if not items:
        body = f'<p class="ib-empty">No {title.lower()} recorded.</p>'
    else:
        rows = []
        for it in items:
            amt = it["amount"]
            share = (amt / total) if total else None
            share_pct = max(0.0, min(1.0, share or 0)) * 100
            source_cell = (
                f'<td class="ci-source">{html.escape(it.get("dominant_source") or "")}</td>'
                if show_source else ""
            )
            rows.append(f"""
              <tr>
                <td class="mono">{html.escape(it['commitment_item'] or '')}</td>
                <td class="num">{fmt_money(amt)}</td>
                {source_cell}
                <td class="pct-cell">
                  <div class="pct-track"><div class="pct-bar consumed-on-track" style="width:{share_pct:.1f}%"></div></div>
                  <span class="pct-label">{fmt_pct(share)}</span>
                </td>
              </tr>
            """)
        source_th = '<th>Source</th>' if show_source else ""
        body = f"""
          <table class="ib-table ib-ci-table">
            <thead>
              <tr>
                <th>Commitment Item</th>
                <th class="num">{amount_col}</th>
                {source_th}
                <th>Share</th>
              </tr>
            </thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        """
    return f"""
      <section class="ib-ci-block">
        <h3>{title}<span class="ib-ci-total">{fmt_money(total)}</span></h3>
        {body}
      </section>
    """


def render_funds_center_detail(funds_center: str, fy: int,
                               summary: dict[str, Any] | None,
                               budget_items: list[dict[str, Any]],
                               actuals_items: list[dict[str, Any]]) -> str:
    if summary is None:
        return f"""<div class="ib-report"><h2>{html.escape(funds_center)}</h2>
        <p class="ib-empty">No FMEDDW activity for this Funds Center in FY{fy}.</p></div>"""

    pct_class = consumption_class(summary.get("pct_consumed"))
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Total Budget</div>
        <div class="kpi-value">{fmt_money(summary.get('total_budget'))}</div></div>
      <div class="kpi"><div class="kpi-label">Actuals</div>
        <div class="kpi-value">{fmt_money(summary.get('actuals'))}</div></div>
      <div class="kpi"><div class="kpi-label">Available</div>
        <div class="kpi-value">{fmt_money(summary.get('available'))}</div></div>
      <div class="kpi {pct_class}"><div class="kpi-label">% Consumed</div>
        <div class="kpi-value">{fmt_pct(summary.get('pct_consumed'))}</div></div>
    </div>
    """

    budget_block = _render_ci_block(
        "Budget allocations",
        summary.get("total_budget", 0),
        budget_items,
        "Budget",
        show_source=True,
    )
    actuals_block = _render_ci_block(
        "Actuals consumed",
        summary.get("actuals", 0),
        actuals_items,
        "Actuals",
        show_source=False,
    )

    methodology = (
        '<p class="ib-methodology">'
        'Budget and actuals are shown as two separate ledgers because SAP FM '
        'allocates budget to parent Commitment Items (e.g., AID TO DISTRICTS) '
        'while the GM module derives actuals against finer-grained child items '
        'at posting time. The Funds Center totals above reconcile; per-Commitment-Item '
        'totals will not line up one-to-one between the two tables. This is by design.'
        '</p>'
    )

    name = summary.get("name") or funds_center
    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>{html.escape(name)} <span class="ib-fc-code">{html.escape(funds_center)}</span> — FY{fy}</h2>
        <p class="ib-report-meta">Drill-down to Commitment Item.</p>
      </header>
      {kpi_html}
      <div class="ib-split-grid">
        {budget_block}
        {actuals_block}
      </div>
      {methodology}
    </div>
    """
