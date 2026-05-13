"""HTML rendering for the internal budget vs actuals dashboard.

Design system: SCDE Finance design tokens from docs/style/scde-design/tokens.json.
Typography: Poppins (display), JetBrains Mono (tabular currency + codes).
Tooltips: Tippy.js (loaded inline where needed) for Commitment Item descriptions.
Negatives: accounting parentheses $(1,234), colored with --semantic-danger.
"""
from __future__ import annotations

import html
from typing import Any


# ─────────────────────────── formatters ───────────────────────────

def fmt_money(v: float | int | None, *, danger_class: bool = True) -> str:
    """Format currency with accounting parentheses for negatives.
    Returns an HTML span with danger color for negatives."""
    if v is None:
        return "n/a"
    n = round(float(v))
    if n == 0:
        return "$0"
    if n < 0:
        text = f"$({abs(n):,})"
        if danger_class:
            return f'<span class="num-neg">{text}</span>'
        return text
    return f"${n:,}"


def fmt_money_plain(v: float | int | None) -> str:
    """Plain-text money (no HTML span) for title/data attributes."""
    if v is None:
        return "n/a"
    n = round(float(v))
    if n == 0:
        return "$0"
    if n < 0:
        return f"$({abs(n):,})"
    return f"${n:,}"


def fmt_int(v: int | float | None) -> str:
    if v is None:
        return "n/a"
    return f"{int(v):,}"


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
        return f'<span class="num-neg">$({s[1:]})</span>'
    return s


def fmt_pct(v: float | None) -> str:
    if v is None:
        return "n/a"
    return f"{v*100:.1f}%"


def fmt_date(d: str | None) -> str:
    if not d:
        return ""
    # ISO date → human-readable
    try:
        from datetime import date
        p = date.fromisoformat(d)
        return p.strftime("%B %-d, %Y")
    except Exception:
        return d


# ─────────────────────────── partial-FY badge ─────────────────────────────

def partial_badge(fy_meta: dict[str, Any] | None) -> str:
    """Returns an HTML badge if the FY is partial, else empty string.
    MUST appear next to every FY26 number per data-quality caveat #1."""
    if not fy_meta or fy_meta.get("status") != "Partial":
        return ""
    as_of = fy_meta.get("as_of_date") or ""
    label = f"Through {as_of}" if as_of else "Partial Year"
    return f'<span class="fy-partial-badge" title="Data through {as_of}">YTD · {label}</span>'


# ─────────────────────────── color logic ─────────────────────────────

def consumption_class(pct: float | None) -> str:
    if pct is None:
        return "consumed-unknown"
    if pct < 0:
        return "consumed-negative"
    if pct >= 1.0:
        return "consumed-overspent"
    if pct >= 0.85:
        return "consumed-warning"
    if pct >= 0.5:
        return "consumed-on-track"
    return "consumed-light"


# ─────────────────────────── Tippy tooltip helper ─────────────────────────────

_TIPPY_CDN = (
    '<script src="https://unpkg.com/@popperjs/core@2/dist/umd/popper.min.js"></script>'
    '<script src="https://unpkg.com/tippy.js@6/dist/tippy-bundle.umd.min.js"></script>'
    '<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/dist/tippy.css" />'
)


def ci_tooltip_attrs(description: str | None) -> str:
    """Return data-tippy-content attribute for a Commitment Item cell.
    Gracefully handles NULL descriptions (caveat #6)."""
    label = html.escape(description) if description else "Description unavailable"
    return f'data-tippy-content="{label}"'


# ─────────────────────────── budget vs actuals (FC grain) ─────────────────────

def render_budget_vs_actuals(
    fy: int,
    totals: dict[str, Any],
    rows: list[dict[str, Any]],
    fy_meta: dict[str, Any] | None = None,
) -> str:
    """Top-level page: agency KPIs + table of Funds Centers.
    Extends original with: partial-FY badge, Open Encumbrances column,
    True_Available column, FY25+26 coverage note.
    """
    badge = partial_badge(fy_meta)
    pct_class = consumption_class(totals.get("pct_consumed"))

    # Budget KPI: may be NULL for FY25 (BEx actuals-only year)
    budget_val = totals.get("total_budget")
    budget_display = fmt_money(budget_val) if budget_val is not None else '<span class="na-note">tracked at Fund level</span>'

    # True_Available preferred; fall back to Available
    ta_val = totals.get("true_available")
    avail_display = fmt_money(ta_val) if ta_val is not None else fmt_money(totals.get("available"))

    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Total Budget {badge}</div>
        <div class="kpi-value">{budget_display}</div>
        <div class="kpi-sub">FMEDDW (FY26 only)</div></div>
      <div class="kpi"><div class="kpi-label">Actuals (BEx)</div>
        <div class="kpi-value">{fmt_money(totals.get('actuals'))}</div>
        <div class="kpi-sub">FM Expense, negated</div></div>
      <div class="kpi"><div class="kpi-label">Open Encumbrances</div>
        <div class="kpi-value">{fmt_money(totals.get('open_encumbrances'))}</div>
        <div class="kpi-sub">H630 POs · floored $0</div></div>
      <div class="kpi"><div class="kpi-label">True Available</div>
        <div class="kpi-value">{avail_display}</div>
        <div class="kpi-sub">Budget &minus; Actuals &minus; Enc.</div></div>
      <div class="kpi {pct_class}"><div class="kpi-label">% Spent</div>
        <div class="kpi-value">{fmt_pct(totals.get('pct_consumed'))}</div></div>
      <div class="kpi"><div class="kpi-label">Funds Centers</div>
        <div class="kpi-value">{totals.get('leaf_count', 0)}</div></div>
    </div>
    """

    body_rows = []
    prev_dept = None
    for row in rows:
        cls = consumption_class(row["pct_consumed"])
        bar_pct = max(0.0, min(1.0, row["pct_consumed"] or 0)) * 100
        dept_change = (row["department"] != prev_dept)
        prev_dept = row["department"]
        row_class = "dept-divider" if dept_change else ""
        if row["is_bus_child"]:
            row_class = (row_class + " bus-child").strip()
            name_cell = (
                f'<span class="ib-subrow-marker">&#8618;</span>'
                f'<span class="ib-name-text">{html.escape(row["name"])}</span>'
            )
        else:
            name_cell = f'<span class="ib-name-text">{html.escape(row["name"])}</span>'

        # Partial badge on the actuals cell
        row_badge = partial_badge(fy_meta) if fy_meta and fy_meta.get("status") == "Partial" else ""

        # True_Available preferred per caveat #8
        ta = row.get("true_available")
        avail_cell = fmt_money(ta) if ta is not None else fmt_money(row.get("available"))

        budget_cell = fmt_money(row["total_budget"]) if row.get("total_budget") is not None else '<span class="na-note">—</span>'
        enc_cell = fmt_money(row["open_encumbrances"])

        body_rows.append(f"""
          <tr class="{row_class}" data-fc="{html.escape(row['funds_center'])}">
            <td class="ib-name-cell">{name_cell}</td>
            <td class="mono">{html.escape(row['funds_center'])}</td>
            <td class="num">{budget_cell}</td>
            <td class="num">{fmt_money(row['actuals'])}{row_badge}</td>
            <td class="num">{enc_cell}</td>
            <td class="num">{avail_cell}</td>
            <td class="pct-cell">
              <div class="pct-track"><div class="pct-bar {cls}" style="width:{bar_pct:.1f}%"></div></div>
              <span class="pct-label {cls}">{fmt_pct(row['pct_consumed'])}</span>
            </td>
          </tr>
        """)

    budget_note = (
        '<div class="ib-caveat-note">'
        'Budget column is from FMEDDW (FY26 only). '
        'For FY25 or authoritative budget figures, see the '
        '<strong>Agency Budget by Fund</strong> view. '
        'Actuals sourced from BEx FM Expense (both FY25 and FY26). '
        'Encumbrances scoped to H630 FM-area only.'
        '</div>'
    )

    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>FY{fy} Budget vs Actuals — All Funds Centers {badge}</h2>
        <p class="ib-report-meta">Sorted by department · click any row to drill into Commitment Items.
          Bus shops nested under Transportation.
          Source: BEx FM Expense (actuals) + BEx Open Encumbrances + FMEDDW (FY26 budget).</p>
      </header>
      {budget_note}
      {kpi_html}
      <table class="ib-table ib-fc-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Funds Center</th>
            <th class="num">Budget <span class="th-note">(FY26 only)</span></th>
            <th class="num">Actuals</th>
            <th class="num">Open Enc.</th>
            <th class="num">True Available</th>
            <th>% Spent</th>
          </tr>
        </thead>
        <tbody>
          {''.join(body_rows)}
        </tbody>
      </table>
    </div>
    """


# ─────────────────────────── FC detail ─────────────────────────────

def _render_ci_block(title: str, total: float, items: list[dict[str, Any]],
                     amount_col: str, *, show_source: bool) -> str:
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


def _render_bex_expense_block(
    title: str, total: float, items: list[dict[str, Any]]
) -> str:
    """BEx FM Expense drill-down block with CI tooltips (Tippy.js).
    Data-quality caveat #6: description may be NULL → show 'Description unavailable'.
    """
    if not items:
        return f'<section class="ib-ci-block"><h3>{title}<span class="ib-ci-total">$0</span></h3><p class="ib-empty">No BEx expense rows.</p></section>'

    rows_html = []
    for it in items:
        amt = it["fy_total"]
        share = (amt / total) if total else None
        share_pct = max(0.0, min(1.0, share or 0)) * 100
        desc = it.get("ci_description")
        tt = ci_tooltip_attrs(desc)
        ci_label = html.escape(it["commitment_item"] or "")
        gl_label = html.escape(it["gl_account"] or "")
        q1 = fmt_money(it["qtr_01"])
        q2 = fmt_money(it["qtr_02"])
        q3 = fmt_money(it["qtr_03"])
        q4 = fmt_money(it["qtr_04"])
        rows_html.append(f"""
          <tr>
            <td class="mono tippy-ci" {tt}>{ci_label}</td>
            <td class="mono">{gl_label}</td>
            <td class="num">{q1}</td>
            <td class="num">{q2}</td>
            <td class="num">{q3}</td>
            <td class="num">{q4}</td>
            <td class="num"><strong>{fmt_money(amt)}</strong></td>
            <td class="pct-cell">
              <div class="pct-track"><div class="pct-bar consumed-on-track" style="width:{share_pct:.1f}%"></div></div>
              <span class="pct-label">{fmt_pct(share)}</span>
            </td>
          </tr>
        """)

    body = f"""
      <table class="ib-table ib-ci-table">
        <thead>
          <tr>
            <th>CI <span class="th-note">(hover for desc.)</span></th>
            <th>GL Account</th>
            <th class="num">Q1</th>
            <th class="num">Q2</th>
            <th class="num">Q3</th>
            <th class="num">Q4</th>
            <th class="num">FY Total</th>
            <th>Share</th>
          </tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
      <script>tippy('.tippy-ci', {{theme: 'light-border', placement: 'top', maxWidth: 320}});</script>
    """
    return f"""
      <section class="ib-ci-block ib-ci-block-wide">
        <h3>{title}<span class="ib-ci-total">{fmt_money(total)}</span></h3>
        {body}
      </section>
    """


def _render_encumbrance_lines_block(lines: list[dict[str, Any]]) -> str:
    """PO/Reservation lines for the FC detail view."""
    if not lines:
        return '<p class="ib-empty">No open commitments for this Funds Center.</p>'

    rows_html = []
    for ln in lines:
        rb = ln["remaining_balance"]
        neg_class = " enc-over-invoiced" if rb < 0 else ""
        rows_html.append(f"""
          <tr class="{neg_class.strip()}">
            <td>{html.escape(ln['detail_type'] or '')}</td>
            <td class="mono">{html.escape(ln['reference_doc_no'] or '')}</td>
            <td>{html.escape(ln['document_date'] or '')}</td>
            <td>{html.escape(ln['vendor_name'] or '')}</td>
            <td class="num">{fmt_money(ln['original_amount'])}</td>
            <td class="num">{fmt_money(ln['invoiced_amount'])}</td>
            <td class="num">{fmt_money(rb)}</td>
          </tr>
        """)

    return f"""
      <table class="ib-table ib-enc-table">
        <thead>
          <tr>
            <th>Type</th>
            <th>Doc #</th>
            <th>Date</th>
            <th>Vendor</th>
            <th class="num">Original</th>
            <th class="num">Invoiced</th>
            <th class="num">Remaining</th>
          </tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
    """


def render_funds_center_detail(
    funds_center: str,
    fy: int,
    summary: dict[str, Any] | None,
    budget_items: list[dict[str, Any]],
    actuals_items: list[dict[str, Any]],
    bex_items: list[dict[str, Any]] | None = None,
    enc_lines: list[dict[str, Any]] | None = None,
) -> str:
    if summary is None:
        return (
            f'<div class="ib-report"><h2>{html.escape(funds_center)}</h2>'
            f'<p class="ib-empty">No FM activity for this Funds Center in FY{fy}.</p></div>'
        )

    badge = partial_badge({"status": summary.get("fy_status"), "as_of_date": summary.get("as_of_date")})
    pct_class = consumption_class(summary.get("pct_consumed"))

    budget_val = summary.get("total_budget")
    budget_display = fmt_money(budget_val) if budget_val is not None else '<span class="na-note">tracked at Fund level</span>'
    ta_val = summary.get("true_available")
    avail_display = fmt_money(ta_val) if ta_val is not None else fmt_money(summary.get("available"))

    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Budget (FMEDDW)</div>
        <div class="kpi-value">{budget_display}</div></div>
      <div class="kpi"><div class="kpi-label">Actuals (BEx) {badge}</div>
        <div class="kpi-value">{fmt_money(summary.get('actuals'))}</div></div>
      <div class="kpi"><div class="kpi-label">Open Enc.</div>
        <div class="kpi-value">{fmt_money(summary.get('open_encumbrances'))}</div></div>
      <div class="kpi"><div class="kpi-label">True Available</div>
        <div class="kpi-value">{avail_display}</div></div>
      <div class="kpi {pct_class}"><div class="kpi-label">% Spent</div>
        <div class="kpi-value">{fmt_pct(summary.get('pct_consumed'))}</div></div>
    </div>
    """

    budget_block = _render_ci_block(
        "Budget allocations (FMEDDW)",
        budget_val or 0,
        budget_items,
        "Budget",
        show_source=True,
    )
    actuals_block = _render_ci_block(
        "FMEDDW Actuals (GM Receive)",
        summary.get("actuals", 0),
        actuals_items,
        "Actuals",
        show_source=False,
    )

    # BEx expense block (preferred actuals source)
    bex_total = sum(it["fy_total"] for it in (bex_items or []))
    bex_block = _render_bex_expense_block(
        "BEx FM Expense by CI/GL",
        bex_total,
        bex_items or [],
    )

    # Encumbrance lines
    enc_block_inner = _render_encumbrance_lines_block(enc_lines or [])
    enc_block = f"""
      <section class="ib-enc-section">
        <h3 class="ib-collapsible-header" data-target="enc-lines-{html.escape(funds_center)}">
          H630 Open Commitments
          <span class="ib-collapsible-toggle">&#9660;</span>
        </h3>
        <div id="enc-lines-{html.escape(funds_center)}" class="ib-collapsible-body">
          {enc_block_inner}
        </div>
      </section>
    """

    methodology = (
        '<p class="ib-methodology">'
        'Budget and FMEDDW Actuals are two separate ledger views — SAP FM allocates budget '
        'to parent Commitment Items while the GM module records actuals at finer-grained child '
        'items. The BEx FM Expense rows (above) are the authoritative actuals source for both '
        'FY25 and FY26. FMEDDW actuals are shown for reconciliation only. '
        'Encumbrances are H630 FM-area only (caveat #3).'
        '</p>'
    )

    name = summary.get("name") or funds_center
    return f"""
    {_TIPPY_CDN}
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>{html.escape(name)} <span class="ib-fc-code">{html.escape(funds_center)}</span> — FY{fy} {badge}</h2>
        <p class="ib-report-meta">Drill-down to Commitment Item · BEx FM Expense + FMEDDW sources.</p>
      </header>
      {kpi_html}
      <div class="ib-ci-block-wide-wrap">
        {bex_block}
      </div>
      {enc_block}
      <div class="ib-split-grid">
        {budget_block}
        {actuals_block}
      </div>
      {methodology}
    </div>
    <script>
    document.querySelectorAll('.ib-collapsible-header').forEach(h => {{
      h.addEventListener('click', () => {{
        const target = document.getElementById(h.dataset.target);
        if (target) {{
          const open = target.style.display !== 'none';
          target.style.display = open ? 'none' : '';
          h.querySelector('.ib-collapsible-toggle').textContent = open ? '\\u25BA' : '\\u25BC';
        }}
      }});
    }});
    </script>
    """


# ─────────────────────────── Agency Budget by Fund (new panel) ─────────────

def render_budget_by_fund(
    fy: int,
    totals: dict[str, Any],
    rows: list[dict[str, Any]],
    fy_meta: dict[str, Any] | None = None,
) -> str:
    """Agency Budget by Fund panel — Fund x FY grain.
    Authoritative for budget per data-quality discussion.
    Data-quality caveat #1: partial-FY badge on every FY26 number.
    Data-quality caveat #7: Over-Invoiced PO total shown separately.
    """
    badge = partial_badge(fy_meta)
    pct_class = consumption_class(totals.get("pct_spent"))

    over_inv_total = sum(r.get("over_invoiced_amount", 0) for r in rows)
    over_inv_note = ""
    if over_inv_total < 0:
        over_inv_note = (
            f'<div class="ib-caveat-note ib-caveat-warn">'
            f'Over-invoiced POs: {fmt_money(over_inv_total)} '
            f'(11 POs where invoice exceeds PO amount; excluded from Open Encumbrances floor per caveat #7).'
            f'</div>'
        )

    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Current Budget {badge}</div>
        <div class="kpi-value">{fmt_money(totals.get('current_budget'))}</div>
        <div class="kpi-sub">BEx Budget vs Actuals · CI level 6</div></div>
      <div class="kpi"><div class="kpi-label">Actuals {badge}</div>
        <div class="kpi-value">{fmt_money(totals.get('actuals'))}</div>
        <div class="kpi-sub">BEx FM Expense (negated)</div></div>
      <div class="kpi"><div class="kpi-label">Open Enc. (H630)</div>
        <div class="kpi-value">{fmt_money(totals.get('open_encumbrances'))}</div>
        <div class="kpi-sub">POs + Reservations · floored $0</div></div>
      <div class="kpi"><div class="kpi-label">True Available {badge}</div>
        <div class="kpi-value">{fmt_money(totals.get('true_available'))}</div>
        <div class="kpi-sub">Budget &minus; Actuals &minus; Enc.</div></div>
      <div class="kpi {pct_class}"><div class="kpi-label">% Spent</div>
        <div class="kpi-value">{fmt_pct(totals.get('pct_spent'))}</div></div>
      <div class="kpi"><div class="kpi-label">Funds</div>
        <div class="kpi-value">{totals.get('fund_count', 0)}</div></div>
    </div>
    """

    body_rows = []
    for row in rows:
        pct = row.get("pct_spent")
        cls = consumption_class(pct)
        bar_pct = max(0.0, min(1.0, pct or 0)) * 100
        status_badge = partial_badge({"status": row.get("fy_status"), "as_of_date": row.get("as_of_date")})
        body_rows.append(f"""
          <tr>
            <td class="mono">{html.escape(row['fund_code'])}</td>
            <td>{html.escape(row['fund_name'])}</td>
            <td class="num">{fmt_money(row['current_budget'])}{status_badge}</td>
            <td class="num">{fmt_money(row['actuals'])}</td>
            <td class="num">{fmt_money(row['open_encumbrances'])}</td>
            <td class="num">{fmt_money(row['true_available'])}</td>
            <td class="pct-cell">
              <div class="pct-track"><div class="pct-bar {cls}" style="width:{bar_pct:.1f}%"></div></div>
              <span class="pct-label {cls}">{fmt_pct(pct)}</span>
            </td>
          </tr>
        """)

    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>FY{fy} Agency Budget by Fund {badge}</h2>
        <p class="ib-report-meta">
          Fund x FY grain · authoritative for budget · source: BEx Budget vs Actuals (CI level 6 rolled to Fund) +
          BEx FM Expense (actuals) + BEx Open Encumbrances.
          True Available = Current Budget &minus; Actuals &minus; Open Encumbrances (enc. floored at $0).
        </p>
      </header>
      {over_inv_note}
      {kpi_html}
      <table class="ib-table">
        <thead>
          <tr>
            <th>Fund Code</th>
            <th>Fund Name</th>
            <th class="num">Current Budget</th>
            <th class="num">Actuals</th>
            <th class="num">Open Enc. (H630)</th>
            <th class="num">True Available</th>
            <th>% Spent</th>
          </tr>
        </thead>
        <tbody>
          {''.join(body_rows)}
        </tbody>
      </table>
      <p class="ib-methodology">
        Encumbrances rolled up from H630 Funds Centers only (caveat #3).
        Funds with zero actuals and zero encumbrances may still show budget from BEx.
        Over-invoiced PO balances (negative Remaining_Balance) are excluded from
        the Open Encumbrances total and shown in the note above when present.
      </p>
    </div>
    """


# ─────────────────────────── Open Commitments panel (new) ─────────────────────

def render_open_commitments(
    fy: int,
    rows: list[dict[str, Any]],
    fy_meta: dict[str, Any] | None = None,
) -> str:
    """H630 Open POs panel — FC x Detail_Type grain.
    Data-quality caveat #3: label says 'H630 Open POs', not 'All Agency Commitments'.
    Data-quality caveat #7: over-invoiced amounts shown separately.
    """
    badge = partial_badge(fy_meta)

    # Aggregate by FC for the collapsible card headers
    from collections import defaultdict
    by_fc: dict[str, dict] = defaultdict(lambda: {
        "open_amount": 0.0, "over_invoiced": 0.0, "types": []
    })
    for row in rows:
        fc = row["funds_center"]
        by_fc[fc]["open_amount"] += row["open_amount"]
        by_fc[fc]["over_invoiced"] += row["over_invoiced"]
        by_fc[fc]["types"].append(row)

    total_open = sum(v["open_amount"] for v in by_fc.values())
    total_neg  = sum(v["over_invoiced"] for v in by_fc.values())

    over_inv_note = ""
    if total_neg < 0:
        over_inv_note = (
            f'<div class="ib-caveat-note ib-caveat-warn">'
            f'Over-invoiced POs: {fmt_money(total_neg)} across '
            f'{sum(1 for v in by_fc.values() if v["over_invoiced"] < 0)} Funds Centers. '
            f'These are excluded from the Open Encumbrances total (floored at $0).'
            f'</div>'
        )

    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">H630 Open POs {badge}</div>
        <div class="kpi-value">{fmt_money(total_open)}</div>
        <div class="kpi-sub">Remaining Balance &gt; $0</div></div>
      <div class="kpi"><div class="kpi-label">Funds Centers</div>
        <div class="kpi-value">{len(by_fc)}</div></div>
    </div>
    """

    cards = []
    for fc, agg in sorted(by_fc.items(), key=lambda x: -x[1]["open_amount"]):
        card_id = f"enc-fc-{fc.replace(' ', '_')}"
        over = f' <span class="enc-over-badge">{fmt_money_plain(agg["over_invoiced"])} over-inv.</span>' if agg["over_invoiced"] < 0 else ""
        type_rows = "".join(
            f"""<tr>
                  <td>{html.escape(t['detail_type'])}</td>
                  <td class="num">{fmt_int(t['line_count'])}</td>
                  <td class="num">{fmt_money(t['open_amount'])}</td>
                  <td class="num">{fmt_money(t['over_invoiced']) if t['over_invoiced'] < 0 else '—'}</td>
                </tr>"""
            for t in sorted(agg["types"], key=lambda x: -x["open_amount"])
        )
        cards.append(f"""
          <div class="ib-enc-card">
            <div class="ib-enc-card-header" data-target="{card_id}">
              <span class="ib-enc-fc mono">{html.escape(fc)}</span>
              <span class="ib-enc-total">{fmt_money(agg['open_amount'])}{over}</span>
              <span class="ib-collapsible-toggle">&#9660;</span>
            </div>
            <div id="{card_id}" class="ib-enc-card-body" style="display:none">
              <table class="ib-table ib-enc-type-table">
                <thead><tr>
                  <th>Type</th><th class="num">Lines</th>
                  <th class="num">Open Balance</th><th class="num">Over-Inv.</th>
                </tr></thead>
                <tbody>{type_rows}</tbody>
              </table>
            </div>
          </div>
        """)

    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>FY{fy} H630 Open POs &amp; Commitments {badge}</h2>
        <p class="ib-report-meta">
          Scope: H630 FM-area Funds Centers only (caveat #3) ·
          Detail types: Purchase Order, Funds Reservation, Parked FI Document ·
          Negative Remaining_Balance floored at $0 for totals (caveat #7) ·
          Click any card to expand by Detail Type.
        </p>
      </header>
      {over_inv_note}
      {kpi_html}
      <div class="ib-enc-card-list">
        {''.join(cards)}
      </div>
    </div>
    <script>
    document.querySelectorAll('.ib-enc-card-header').forEach(h => {{
      h.addEventListener('click', () => {{
        const target = document.getElementById(h.dataset.target);
        if (target) {{
          const open = target.style.display !== 'none';
          target.style.display = open ? 'none' : '';
          h.querySelector('.ib-collapsible-toggle').textContent = open ? '\\u25BA' : '\\u25BC';
        }}
      }});
    }});
    </script>
    """


def render_encumbrance_lines(
    funds_center: str,
    fy: int,
    lines: list[dict[str, Any]],
) -> str:
    """PO detail lines for a single Funds Center (for any future drill-through use)."""
    total_open = sum(ln["remaining_balance"] for ln in lines if ln["remaining_balance"] > 0)
    total_neg  = sum(ln["remaining_balance"] for ln in lines if ln["remaining_balance"] < 0)
    body = _render_encumbrance_lines_block(lines)
    over_note = (
        f'<div class="ib-caveat-note ib-caveat-warn">Over-invoiced: {fmt_money(total_neg)}</div>'
        if total_neg < 0 else ""
    )
    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>{html.escape(funds_center)} — Open Commitments FY{fy}</h2>
        <p class="ib-report-meta">
          Open Remaining Balance: {fmt_money(total_open)}
          {(' · Over-invoiced: ' + fmt_money_plain(total_neg)) if total_neg < 0 else ''}
        </p>
      </header>
      {over_note}
      {body}
    </div>
    """


# ────────────────────────────────────────────────────────────────────
# FI-ledger view (5xxx GL expenditures) — unchanged from prior version
# ────────────────────────────────────────────────────────────────────


def render_fi_expenditures(fy: int, totals: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    coverage_note = ""
    if totals.get("unmapped", 0) > 0:
        coverage_note = (
            f' · {fmt_money(totals.get("unmapped"))} unmapped to handbook '
            f"({(1 - (totals.get('mapped_pct') or 0))*100:.1f}% of rows)"
        )

    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Total Expenditures (FI)</div>
        <div class="kpi-value">{fmt_money(totals.get('total'))}</div></div>
      <div class="kpi"><div class="kpi-label">Mapped to handbook</div>
        <div class="kpi-value">{fmt_money(totals.get('mapped'))}</div></div>
      <div class="kpi"><div class="kpi-label">Cost Centers</div>
        <div class="kpi-value">{totals.get('cost_center_count', 0)}</div></div>
      <div class="kpi"><div class="kpi-label">Ledger rows</div>
        <div class="kpi-value">{fmt_int(totals.get('row_count', 0))}</div></div>
    </div>
    """

    body_rows = []
    prev_dept = None
    grand_total = totals.get("total") or 0
    for row in rows:
        dept_change = (row["department"] != prev_dept)
        prev_dept = row["department"]
        row_class = "dept-divider" if dept_change else ""
        if row["is_bus_child"]:
            row_class = (row_class + " bus-child").strip()
            name_cell = (
                f'<span class="ib-subrow-marker">&#8618;</span>'
                f'<span class="ib-name-text">{html.escape(row["name"])}</span>'
            )
        else:
            name_cell = f'<span class="ib-name-text">{html.escape(row["name"])}</span>'
        share = (row["amount"] / grand_total) if grand_total else None
        bar_pct = max(0.0, min(1.0, share or 0)) * 100
        body_rows.append(f"""
          <tr class="{row_class}" data-cc="{html.escape(row['cost_center'])}">
            <td class="ib-name-cell">{name_cell}</td>
            <td class="mono">{html.escape(row['cost_center'])}</td>
            <td class="num">{fmt_money(row['amount'])}</td>
            <td class="num">{fmt_int(row['row_count'])}</td>
            <td class="pct-cell">
              <div class="pct-track"><div class="pct-bar consumed-on-track" style="width:{bar_pct:.1f}%"></div></div>
              <span class="pct-label">{fmt_pct(share)}</span>
            </td>
          </tr>
        """)

    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>FY{fy} Expenditures by Cost Center — FI Ledger</h2>
        <p class="ib-report-meta">5xxx GL postings from <code>sceis_detail_transaction</code>.
          Includes payroll / clearing / accruals that FM Actuals exclude — totals will not match the
          Budget vs Actuals view.{coverage_note}
          Click any row to drill into the handbook-category breakdown.</p>
      </header>
      {kpi_html}
      <table class="ib-table ib-fc-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Cost Center</th>
            <th class="num">Expenditures</th>
            <th class="num">Ledger Rows</th>
            <th>Share of agency</th>
          </tr>
        </thead>
        <tbody>
          {''.join(body_rows)}
        </tbody>
      </table>
    </div>
    """


def render_cost_center_handbook_detail(cost_center: str, fy: int, data: dict[str, Any]) -> str:
    summary = data.get("summary")
    rows = data.get("rows") or []
    if summary is None:
        return (
            f'<div class="ib-report"><h2>{html.escape(cost_center)}</h2>'
            f'<p class="ib-empty">No 5xxx ledger activity for this Cost Center in FY{fy}.</p></div>'
        )

    name = summary.get("name") or cost_center
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">Total Expenditures (FI)</div>
        <div class="kpi-value">{fmt_money(summary.get('amount'))}</div></div>
      <div class="kpi"><div class="kpi-label">Ledger rows</div>
        <div class="kpi-value">{fmt_int(summary.get('row_count'))}</div></div>
    </div>
    """

    if not rows:
        body = '<p class="ib-empty">No handbook breakdown available.</p>'
    else:
        total = summary.get("amount") or 0
        body_rows = []
        for row in rows:
            share = (row["amount"] / total) if total else None
            bar_pct = max(0.0, min(1.0, share or 0)) * 100
            unmapped_class = "ci-unmapped" if row["handbook_code"] == "(unmapped)" else ""
            body_rows.append(f"""
              <tr class="{unmapped_class}">
                <td class="mono">{html.escape(row['handbook_code'])}</td>
                <td>{html.escape(row['handbook_name'])}</td>
                <td class="num">{fmt_money(row['amount'])}</td>
                <td class="num">{fmt_int(row['row_count'])}</td>
                <td class="pct-cell">
                  <div class="pct-track"><div class="pct-bar consumed-on-track" style="width:{bar_pct:.1f}%"></div></div>
                  <span class="pct-label">{fmt_pct(share)}</span>
                </td>
              </tr>
            """)
        body = f"""
          <table class="ib-table">
            <thead>
              <tr>
                <th>Handbook</th>
                <th>Category</th>
                <th class="num">Expenditures</th>
                <th class="num">Rows</th>
                <th>Share</th>
              </tr>
            </thead>
            <tbody>{''.join(body_rows)}</tbody>
          </table>
        """

    return f"""
    <div class="ib-report">
      <header class="ib-report-header">
        <h2>{html.escape(name)} <span class="ib-fc-code">{html.escape(cost_center)}</span> — FY{fy}</h2>
        <p class="ib-report-meta">FI ledger expenditures grouped by handbook Object code.
          Rows where <code>lookup_gl_account</code> has no mapping land in the <code>(unmapped)</code> bucket.</p>
      </header>
      {kpi_html}
      {body}
    </div>
    """
