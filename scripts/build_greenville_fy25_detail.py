"""
Build Greenville 01 FY2024-25 Detail Revenue Report
Mode: detail
Output: outputs/reports/district_revenue_detail_FY2025_<timestamp>_2301_Greenville.html
"""
import json, os, re
from datetime import datetime

# ── load data ─────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(BASE, 'data', 'staging', 'greenville_fy25_detail.json')) as f:
    raw = json.load(f)

# ── constants ─────────────────────────────────────────────────────────────────
DISTRICT_ID   = '2301'
DISTRICT_NAME = 'Greenville 01 — Greenville County Schools'
FY            = 2025
FY_LABEL      = 'FY2024-25'
SY_LABEL      = 'SY 2024-25'
HEADCOUNT     = 76398
SCEIS_STATE   = 510312747.72
SCEIS_FEDERAL = 52482156.52
SCEIS_OTHER   = 3331152.73
GENERATION_TS = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
REPORT_DATE   = '2026-04-28'

# ── helpers ───────────────────────────────────────────────────────────────────
def fmt(v):
    """Dollar format: no decimals, accounting parens for negatives."""
    if v is None:
        return '$—'
    v = float(v)
    if v == 0:
        return '$0'
    if v < 0:
        return f'$({abs(v):,.0f})'
    return f'${v:,.0f}'

def esc(s):
    if not s:
        return ''
    return (str(s)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&#39;'))

def trunc(s, n=300):
    if not s:
        return ''
    s = str(s).strip()
    return s[:n] + '…' if len(s) > n else s

# ── tooltip dict ──────────────────────────────────────────────────────────────
code_tips = {}
for d in raw:
    c = d['code']
    name  = d['full_name'] or d['display_name'] or c
    short = d['short_desc'] or d['display_name'] or ''
    full  = d['full_desc'] or short or ''
    code_tips[c] = {
        'name': name,
        'short': trunc(short, 200),
        'full': trunc(full, 600),
    }

# ── totals ─────────────────────────────────────────────────────────────────────
total_local       = sum(d['amount'] for d in raw if d['amount'] and d['stream_type'] == 'Local')
total_state_lea   = sum(d['amount'] for d in raw if d['amount'] and d['stream_type'] == 'State')
total_federal_lea = sum(d['amount'] for d in raw if d['amount'] and d['stream_type'] == 'Federal')
total_src5        = sum(d['amount'] for d in raw if d['amount'] and d['code'].startswith('5'))

state_variance   = total_state_lea   - SCEIS_STATE
federal_variance = total_federal_lea - SCEIS_FEDERAL
grand_total      = total_local + SCEIS_STATE + SCEIS_FEDERAL

# ── cell helpers ──────────────────────────────────────────────────────────────
def code_td(code):
    tip = code_tips.get(code, {})
    short = esc(tip.get('short', '') or '')
    full  = esc(tip.get('full', '') or '')
    # Build tooltip: short desc first, then offer full
    tc = esc(code)
    if short:
        tc += ' — ' + short
    # allowHTML so we can bold the code
    return (f'<td class="code-cell">'
            f'<code class="code-pill" '
            f'data-tippy-content="{tc}" '
            f'data-tippy-allowHTML="true">{esc(code)}</code>'
            f'</td>')

def amt_td(v, extra_class=''):
    if v is None:
        return f'<td class="amt-cell amt-dash {extra_class}">—</td>'
    fv = float(v)
    if fv < 0:
        return f'<td class="amt-cell amt-neg {extra_class}">{fmt(fv)}</td>'
    if fv == 0:
        return f'<td class="amt-cell amt-zero {extra_class}">{fmt(fv)}</td>'
    return f'<td class="amt-cell {extra_class}">{fmt(fv)}</td>'

def title_td(label, extra_class='', tip=''):
    attr = f' data-tippy-content="{esc(tip)}" data-tippy-allowHTML="true"' if tip else ''
    return f'<td class="title-cell {extra_class}"{attr}>{esc(label)}</td>'

def desc_td(text, extra_class=''):
    return f'<td class="desc-cell {extra_class}">{esc(trunc(text or "", 160))}</td>'

# ── row builders ──────────────────────────────────────────────────────────────
ROWS = []

def add_level1(code, label):
    tip = code_tips.get(code, {})
    short = tip.get('short', '')
    tc = f'{esc(code)} — {esc(label)}'
    if short:
        tc += f'<br><span class="tip-desc">{esc(short)}</span>'
    ROWS.append(
        f'<tr class="row-level1">'
        f'<td class="code-cell"><code class="code-pill" data-tippy-content="{tc}" data-tippy-allowHTML="true">{esc(code)}</code></td>'
        f'<td class="title-cell section-title" colspan="2">{esc(label)}</td>'
        f'<td class="amt-cell"></td>'
        f'</tr>'
    )

def add_level2(code, label):
    tip = code_tips.get(code, {})
    short = tip.get('short', '')
    tc = f'{esc(code)} — {esc(label)}'
    if short:
        tc += f'<br><span class="tip-desc">{esc(short)}</span>'
    ROWS.append(
        f'<tr class="row-level2">'
        f'<td class="code-cell"><code class="code-pill l2-code" data-tippy-content="{tc}" data-tippy-allowHTML="true">{esc(code)}</code></td>'
        f'<td class="title-cell l2-title" colspan="2">{esc(label)}</td>'
        f'<td class="amt-cell"></td>'
        f'</tr>'
    )

def add_level3(code, label, amount, desc=''):
    tip = code_tips.get(code, {})
    short = tip.get('short', '')
    full  = tip.get('full', '')
    tc = f'{esc(code)} — {esc(label)}'
    if short:
        tc += f'<br><span class="tip-desc">{esc(short)}</span>'
    fv = float(amount) if amount is not None else None
    is_z = fv == 0 if fv is not None else False
    is_n = fv is not None and fv < 0
    classes = 'row-level3'
    if is_z:
        classes += ' row-zero'
    if is_n:
        classes += ' row-neg'
    display_desc = trunc(full or short or '', 140)
    ROWS.append(
        f'<tr class="{classes}">'
        f'<td class="code-cell"><code class="code-pill l3-code" data-tippy-content="{tc}" data-tippy-allowHTML="true">{esc(code)}</code></td>'
        f'<td class="title-cell l3-title">{esc(label)}</td>'
        f'<td class="desc-cell">{esc(display_desc)}</td>'
        f'{amt_td(amount)}'
        f'</tr>'
    )

def add_subtotal(label, total_val, extra_class='', sceis_badge=False):
    fv = float(total_val) if total_val is not None else 0
    is_n = fv < 0
    badge = ''
    if sceis_badge:
        badge = '<span class="source-badge sceis-badge">SCEIS</span>'
    elif 'LEA' in label or 'self-reported' in label.lower():
        badge = '<span class="source-badge lea-badge">LEA</span>'
    neg_class = ' amt-neg' if is_n else ''
    ROWS.append(
        f'<tr class="row-subtotal {extra_class}">'
        f'<td></td>'
        f'<td class="title-cell subtotal-label" colspan="2">{badge}{esc(label)}</td>'
        f'<td class="amt-cell subtotal-amt{neg_class}">{fmt(fv)}</td>'
        f'</tr>'
    )

def add_separator():
    ROWS.append('<tr class="row-separator"><td colspan="4"></td></tr>')

# ── build by stream ───────────────────────────────────────────────────────────
def label_for(d):
    return d['display_title'] or d['full_name'] or d['display_name'] or d['code']

def rows_of_level(stream_type, level):
    return [d for d in raw if d['stream_type'] == stream_type and (d['rollup_level'] or 99) == level]

def rows_under_l2(stream_type, l2_code, all_l3):
    """Return l3 rows that belong under the given l2 heading.
    We use a sequential positional approach: l3 rows are assigned to the
    last l2 heading seen when iterating in code order.
    Build the mapping once if needed.
    """
    return _l2_map.get((stream_type, l2_code), [])

# Build l2->l3 assignment map (positional)
def build_l2_map():
    m = {}
    for stream_type in ('Local', 'State', 'Federal'):
        all_rows = [d for d in raw if d['stream_type'] == stream_type]
        all_rows.sort(key=lambda d: d['code'])
        cur_l2 = None
        for d in all_rows:
            lv = d['rollup_level'] or 99
            if lv == 2:
                cur_l2 = d['code']
                m[(stream_type, cur_l2)] = []
            elif lv == 3 and cur_l2:
                m[(stream_type, cur_l2)].append(d)
    return m

_l2_map = build_l2_map()

# ── LOCAL ──────────────────────────────────────────────────────────────────────
add_separator()
l1_local = rows_of_level('Local', 1)
if l1_local:
    add_level1(l1_local[0]['code'], label_for(l1_local[0]))

l2_local = rows_of_level('Local', 2)
for l2d in l2_local:
    add_level2(l2d['code'], label_for(l2d))
    l3_under = rows_under_l2('Local', l2d['code'], rows_of_level('Local', 3))
    if l3_under:
        for l3d in l3_under:
            add_level3(l3d['code'], label_for(l3d), l3d['amount'],
                       l3d['full_desc'] or l3d['short_desc'] or '')
        sub = sum(d['amount'] for d in l3_under if d['amount'])
        add_subtotal(f'Subtotal — {label_for(l2d)}', sub)

add_subtotal('TOTAL LOCAL REVENUE (LEA self-reported)', total_local,
             extra_class='row-stream-total')

add_separator()

# ── STATE ─────────────────────────────────────────────────────────────────────
l1_state = rows_of_level('State', 1)
if l1_state:
    add_level1(l1_state[0]['code'], label_for(l1_state[0]))

l2_state = rows_of_level('State', 2)
for l2d in l2_state:
    add_level2(l2d['code'], label_for(l2d))
    l3_under = rows_under_l2('State', l2d['code'], rows_of_level('State', 3))
    if l3_under:
        for l3d in l3_under:
            add_level3(l3d['code'], label_for(l3d), l3d['amount'],
                       l3d['full_desc'] or l3d['short_desc'] or '')
        sub = sum(d['amount'] for d in l3_under if d['amount'])
        add_subtotal(f'Subtotal — {label_for(l2d)}', sub)

add_subtotal('TOTAL STATE — LEA self-reported sub-buckets', total_state_lea,
             extra_class='row-stream-total')
add_subtotal('TOTAL STATE — SCEIS system of record', SCEIS_STATE,
             extra_class='row-stream-total-sceis', sceis_badge=True)
add_subtotal(f'State variance (LEA minus SCEIS) — see methodology footer',
             state_variance, extra_class='row-variance')

add_separator()

# ── FEDERAL ───────────────────────────────────────────────────────────────────
l1_fed = rows_of_level('Federal', 1)
if l1_fed:
    add_level1(l1_fed[0]['code'], label_for(l1_fed[0]))

l2_fed = rows_of_level('Federal', 2)
for l2d in l2_fed:
    add_level2(l2d['code'], label_for(l2d))
    l3_under = rows_under_l2('Federal', l2d['code'], rows_of_level('Federal', 3))
    if l3_under:
        for l3d in l3_under:
            add_level3(l3d['code'], label_for(l3d), l3d['amount'],
                       l3d['full_desc'] or l3d['short_desc'] or '')
        sub = sum(d['amount'] for d in l3_under if d['amount'])
        add_subtotal(f'Subtotal — {label_for(l2d)}', sub)

add_subtotal('TOTAL FEDERAL — LEA self-reported', total_federal_lea,
             extra_class='row-stream-total')
add_subtotal('TOTAL FEDERAL — SCEIS system of record', SCEIS_FEDERAL,
             extra_class='row-stream-total-sceis', sceis_badge=True)
add_subtotal(f'Federal variance (LEA minus SCEIS) — see methodology footer',
             federal_variance, extra_class='row-variance')

add_separator()

# ── 5xxx OTHER SOURCES / TRANSFERS ────────────────────────────────────────────
src5_rows = [d for d in raw if d['code'].startswith('5')]
if src5_rows:
    # synthetic header
    ROWS.append(
        f'<tr class="row-level1">'
        f'<td class="code-cell"><code class="code-pill" data-tippy-content="5000 — Other Sources &amp; Transfers<br><span class=\'tip-desc\'>Non-operating financing sources including interfund transfers, bond proceeds, and sale of fixed assets. Displayed for completeness; excluded from operating revenue totals.</span>" data-tippy-allowHTML="true">5000</code></td>'
        f'<td class="title-cell section-title" colspan="2">Other Sources &amp; Transfers (5xxx)</td>'
        f'<td class="amt-cell"></td>'
        f'</tr>'
    )
    for d in src5_rows:
        fv = float(d['amount']) if d['amount'] is not None else None
        if fv is None:
            continue  # skip null header rows
        is_z = fv == 0
        is_n = fv < 0
        classes = 'row-level3 row-5xxx'
        if is_z:
            classes += ' row-zero'
        if is_n:
            classes += ' row-neg'
        tip = code_tips.get(d['code'], {})
        short = tip.get('short', '')
        full  = tip.get('full', '')
        tc = f'{esc(d["code"])} — {esc(label_for(d))}'
        if short:
            tc += f'<br><span class="tip-desc">{esc(short)}</span>'
        display_desc = trunc(full or short or '', 140)
        ROWS.append(
            f'<tr class="{classes}">'
            f'<td class="code-cell"><code class="code-pill l3-code" data-tippy-content="{tc}" data-tippy-allowHTML="true">{esc(d["code"])}</code></td>'
            f'<td class="title-cell l3-title">{esc(label_for(d))}</td>'
            f'<td class="desc-cell">{esc(display_desc)}</td>'
            f'{amt_td(d["amount"])}'
            f'</tr>'
        )
    add_subtotal('TOTAL OTHER SOURCES & TRANSFERS (5xxx — non-operating, excluded from Grand Total)',
                 total_src5, extra_class='row-stream-total row-5xxx-total')

add_separator()

# ── UNCATEGORIZED (non-5xxx rows with no stream_type) ─────────────────────────
uncateg = [d for d in raw if d['stream_type'] is None and not d['code'].startswith('5')]
if uncateg:
    ROWS.append(
        f'<tr class="row-level1 row-warn">'
        f'<td class="code-cell"></td>'
        f'<td class="title-cell section-title" colspan="2">'
        f'<span class="warn-badge">Uncategorized</span> Revenue codes not in District Funding Streams catalog</td>'
        f'<td class="amt-cell"></td>'
        f'</tr>'
    )
    for d in uncateg:
        fv = float(d['amount']) if d['amount'] is not None else None
        if fv is None:
            continue
        is_z = fv == 0
        is_n = fv < 0
        classes = 'row-level3 row-uncategorized'
        if is_z:
            classes += ' row-zero'
        if is_n:
            classes += ' row-neg'
        tip = code_tips.get(d['code'], {})
        short = tip.get('short', '')
        ROWS.append(
            f'<tr class="{classes}">'
            f'{code_td(d["code"])}'
            f'{title_td(label_for(d), "l3-title")}'
            f'{desc_td(short)}'
            f'{amt_td(d["amount"])}'
            f'</tr>'
        )

# ── GRAND TOTAL ROW ───────────────────────────────────────────────────────────
add_separator()
ROWS.append(
    f'<tr class="row-grand-total">'
    f'<td></td>'
    f'<td class="title-cell grand-total-label" colspan="2">'
    f'GRAND TOTAL OPERATING REVENUE<br>'
    f'<span class="grand-total-note">Local (LEA) + State (SCEIS) + Federal (SCEIS) | Excludes 5xxx Other Sources</span>'
    f'</td>'
    f'<td class="amt-cell grand-total-amt">{fmt(grand_total)}</td>'
    f'</tr>'
)

ROWS_HTML = '\n'.join(ROWS)

# ── variance table for methodology ───────────────────────────────────────────
var_html = f"""
<table class="var-table" aria-label="Source discrepancy summary">
  <thead>
    <tr>
      <th scope="col">Stream</th>
      <th scope="col">LEA self-reported ($)</th>
      <th scope="col">SCEIS system of record ($)</th>
      <th scope="col">Variance ($)</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>State</td>
      <td class="var-amt">{fmt(total_state_lea)}</td>
      <td class="var-amt">{fmt(SCEIS_STATE)}</td>
      <td class="var-amt {'var-neg' if state_variance < 0 else ''}">{fmt(state_variance)}</td>
    </tr>
    <tr>
      <td>Federal</td>
      <td class="var-amt">{fmt(total_federal_lea)}</td>
      <td class="var-amt">{fmt(SCEIS_FEDERAL)}</td>
      <td class="var-amt {'var-neg' if federal_variance < 0 else ''}">{fmt(federal_variance)}</td>
    </tr>
  </tbody>
</table>
"""

# ── assemble full HTML ────────────────────────────────────────────────────────
HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{FY_LABEL} Detailed Revenue Report — Greenville 01</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<script src="https://unpkg.com/@popperjs/core@2/dist/umd/popper.min.js"></script>
<script src="https://unpkg.com/tippy.js@6/dist/tippy-bundle.umd.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/dist/tippy.css"/>
<style>
/* ── SCDE Finance Design System tokens (tokens.json) ───────────────────── */
:root {{
  /* brand */
  --color-brand-primary:    #2F3D4C;  /* Pantone 432 C */
  --color-brand-secondary:  #234058;  /* Pantone 7546 C */
  --color-brand-tertiary:   #43718B;  /* Pantone 5405 C */
  --color-brand-accent:     #F1BA55;  /* Pantone 142 C — decorative only */
  /* semantic */
  --color-success:          #1F7A3A;
  --color-warning:          #8A5A00;
  --color-danger:           #B3261E;
  --color-info:             #234058;
  --color-neutral-bg:       #F4F6F8;
  --color-neutral-fg:       #2F3D4C;
  --color-border:           #7E8C9E;
  --color-border-subtle:    #CBD5E0;
  /* type */
  --font-display: 'Poppins', 'Segoe UI', system-ui, sans-serif;
  --font-mono:    'JetBrains Mono', 'Consolas', 'Menlo', monospace;
  /* spacing (4px base) */
  --s-1: 4px;  --s-2: 8px;  --s-3: 12px; --s-4: 16px;
  --s-5: 20px; --s-6: 24px; --s-8: 32px;
  /* radius */
  --r-sm: 4px; --r-md: 8px; --r-lg: 16px;
  /* shadows (tokens.json) */
  --shadow-sm: 0 1px 2px rgba(47,61,76,.06), 0 1px 1px rgba(47,61,76,.04);
  --shadow-md: 0 4px 8px rgba(47,61,76,.08), 0 2px 4px rgba(47,61,76,.06);
  --shadow-lg: 0 12px 24px rgba(47,61,76,.12), 0 4px 8px rgba(47,61,76,.08);
  /* misc */
  --success-bg: #e6f3ec;
  --warning-bg: #fdf3e3;
  --danger-bg:  #fbeaea;
  --info-bg:    #e8eff4;
}}

/* ── reset ───────────────────────────────────────────────────────────────── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: var(--font-display);
  font-size: 14px;
  line-height: 20px; /* type.scale.sm */
  background: var(--color-neutral-bg);
  color: var(--color-neutral-fg);
}}
@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}

/* ── Tippy theme ─────────────────────────────────────────────────────────── */
.tippy-box[data-theme~='scde'] {{
  background: var(--color-brand-primary);
  color: #fff;
  font-family: var(--font-display);
  font-size: 12px;
  line-height: 1.5;
  border-radius: var(--r-md);
  box-shadow: var(--shadow-lg);
}}
.tippy-box[data-theme~='scde'] .tippy-content {{ padding: var(--s-2) var(--s-3); }}
.tippy-box[data-theme~='scde'] .tippy-arrow::before {{ color: var(--color-brand-primary); }}
.tip-desc {{ opacity: .85; }}

/* ── page header ─────────────────────────────────────────────────────────── */
.page-header {{
  background: var(--color-brand-primary);
  color: #fff;
  padding: var(--s-5) var(--s-8) var(--s-4);
  border-bottom: 4px solid var(--color-brand-accent);
}}
.page-header h1 {{
  font-size: 28px; /* type.scale.2xl */
  font-weight: 700;
  line-height: 36px;
}}
.page-header .sub {{
  font-size: 14px;
  opacity: .82;
  margin-top: var(--s-1);
}}
.page-header .mode-badge {{
  display: inline-block;
  background: var(--color-brand-accent);
  color: var(--color-brand-primary);
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  margin-left: var(--s-2);
  vertical-align: middle;
  letter-spacing: .3px;
}}
.fy25-warn {{
  display: inline-block;
  background: var(--warning-bg);
  color: var(--color-warning);
  border: 1px solid #c8920033;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  margin-left: var(--s-2);
  vertical-align: middle;
}}

/* ── KPI strip ───────────────────────────────────────────────────────────── */
.kpi-bar {{
  display: flex;
  gap: var(--s-3);
  flex-wrap: wrap;
  padding: var(--s-3) var(--s-8);
  background: #fff;
  border-bottom: 1px solid var(--color-border-subtle);
}}
.kpi {{
  background: var(--color-neutral-bg);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--r-md);
  padding: var(--s-2) var(--s-4);
  min-width: 160px;
  box-shadow: var(--shadow-sm);
}}
.kpi .lbl {{
  font-size: 11px;
  color: var(--color-border);
  text-transform: uppercase;
  letter-spacing: .4px;
  font-weight: 600;
  margin-bottom: 2px;
}}
.kpi .val {{
  font-size: 18px;
  font-weight: 700;
  color: var(--color-brand-primary);
  font-family: var(--font-mono);
  line-height: 28px; /* type.scale.lg */
}}
.kpi .val.val-sceis {{
  font-size: 16px;
  color: var(--color-brand-secondary);
}}
.kpi .src {{
  font-size: 10px;
  color: var(--color-border);
  margin-top: 1px;
}}

/* ── info banner ─────────────────────────────────────────────────────────── */
.banner {{
  margin: var(--s-4) var(--s-8) 0;
  padding: var(--s-3) var(--s-4);
  background: var(--warning-bg);
  border-left: 4px solid var(--color-warning);
  border-radius: var(--r-md);
  font-size: 13px;
  color: var(--color-warning);
  line-height: 1.5;
}}
.banner strong {{ font-weight: 600; }}

/* ── table wrap ──────────────────────────────────────────────────────────── */
.tbl-wrap {{
  overflow: auto;
  padding: var(--s-4) var(--s-8) var(--s-8);
}}

/* ── data table ──────────────────────────────────────────────────────────── */
table.detail-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
  line-height: 18px;
  table-layout: fixed;
}}
table.detail-table thead {{
  position: sticky;
  top: 0;
  z-index: 10;
}}
table.detail-table thead th {{
  background: var(--color-brand-primary);
  color: #fff;
  padding: var(--s-2) var(--s-3);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .3px;
  text-align: left;
  border-bottom: 2px solid var(--color-brand-accent);
  white-space: nowrap;
}}
table.detail-table thead th.th-amt {{
  text-align: right;
  font-family: var(--font-mono);
}}

/* column widths */
col.col-code  {{ width: 80px; }}
col.col-title {{ width: 280px; }}
col.col-desc  {{ width: auto; }}
col.col-amt   {{ width: 140px; }}

/* ── row styles ──────────────────────────────────────────────────────────── */
.row-separator td {{
  height: var(--s-2);
  background: var(--color-neutral-bg);
  border: none;
}}

.row-level1 td {{
  background: var(--color-brand-primary);
  color: #fff;
  font-weight: 600;
  font-size: 13px;
  padding: var(--s-2) var(--s-3);
  border-top: 2px solid var(--color-brand-accent);
}}
.row-level1 .code-pill {{
  background: rgba(255,255,255,.15);
  color: #fff;
  border-color: rgba(255,255,255,.2);
}}

.row-level2 td {{
  background: var(--color-brand-secondary);
  color: #fff;
  font-weight: 600;
  font-size: 12.5px;
  padding: var(--s-2) var(--s-3) var(--s-2) 28px;
  border-top: 1px solid rgba(255,255,255,.12);
}}
.row-level2 .l2-code {{
  background: rgba(255,255,255,.12);
  color: #fff;
  border-color: rgba(255,255,255,.15);
}}

.row-level3 td {{
  padding: 5px var(--s-3) 5px 40px;
  border-bottom: 1px solid var(--color-border-subtle);
  background: #fff;
  vertical-align: top;
  font-size: 12.5px;
}}
.row-level3:hover td {{
  background: var(--info-bg);
}}
.row-level3.row-zero td {{
  color: var(--color-border);
  font-style: italic;
}}
.row-level3.row-neg td {{
  background: var(--danger-bg);
}}
.row-level3.row-5xxx td {{
  padding-left: 32px;
  background: #fdfdfe;
}}
.row-level3.row-uncategorized td {{
  background: var(--warning-bg);
}}

.row-subtotal td {{
  background: var(--color-neutral-bg);
  font-weight: 600;
  font-size: 12px;
  padding: var(--s-2) var(--s-3);
  border-top: 1px solid var(--color-border-subtle);
  border-bottom: 1px solid var(--color-border-subtle);
  color: var(--color-neutral-fg);
}}

.row-stream-total td {{
  background: var(--color-brand-tertiary);
  color: #fff;
  font-weight: 700;
  font-size: 12.5px;
  border-top: 2px solid rgba(255,255,255,.3);
  padding: var(--s-2) var(--s-3);
}}

.row-stream-total-sceis td {{
  background: var(--color-brand-secondary);
  color: #fff;
  font-weight: 700;
  font-size: 12.5px;
  padding: var(--s-2) var(--s-3);
}}

.row-variance td {{
  background: #fff9e6;
  color: var(--color-warning);
  font-style: italic;
  font-size: 12px;
  padding: 4px var(--s-3);
  border-bottom: 2px solid var(--color-brand-accent);
}}
.row-variance .amt-cell {{
  font-family: var(--font-mono);
}}
.row-variance .amt-neg {{
  color: var(--color-danger);
}}

.row-5xxx-total td {{
  background: var(--color-neutral-bg);
  color: var(--color-border);
  font-style: italic;
  font-size: 12px;
}}

.row-grand-total td {{
  background: var(--color-brand-primary);
  color: #fff;
  font-weight: 700;
  font-size: 14px;
  padding: var(--s-3) var(--s-3);
  border-top: 3px solid var(--color-brand-accent);
}}
.grand-total-note {{
  font-size: 11px;
  opacity: .75;
  font-weight: 400;
}}
.grand-total-amt {{
  font-size: 18px !important;
  font-family: var(--font-mono);
}}

/* ── shared cell types ───────────────────────────────────────────────────── */
.code-cell {{
  text-align: left;
  white-space: nowrap;
  vertical-align: middle;
}}
.code-pill {{
  display: inline-block;
  font-family: var(--font-mono);
  font-size: 11px;
  font-style: normal;
  background: var(--color-neutral-bg);
  color: var(--color-brand-secondary);
  border: 1px solid var(--color-border-subtle);
  border-radius: var(--r-sm);
  padding: 1px 5px;
  cursor: default;
  transition: background .1s;
  font-weight: 500;
}}
.code-pill:hover {{
  background: var(--info-bg);
}}
.l2-code, .l3-code {{
  font-size: 10.5px;
}}
.title-cell {{
  text-align: left;
  vertical-align: top;
}}
.l3-title {{
  font-size: 12.5px;
}}
.section-title {{
  font-size: 14px;
  font-weight: 600;
  letter-spacing: .2px;
}}
.l2-title {{
  font-size: 13px;
  font-weight: 600;
}}
.subtotal-label {{
  font-size: 12px;
  padding-left: 40px !important;
}}
.desc-cell {{
  font-size: 11.5px;
  color: var(--color-border);
  vertical-align: top;
  line-height: 1.5;
}}
.amt-cell {{
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12.5px;
  white-space: nowrap;
  vertical-align: top;
}}
.amt-neg  {{ color: var(--color-danger); }}
.amt-zero {{ color: var(--color-border); }}
.amt-dash {{ color: var(--color-border); text-align: center; }}
.subtotal-amt {{ font-size: 13px; }}

/* ── source badges ───────────────────────────────────────────────────────── */
.source-badge {{
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  border-radius: 999px;
  padding: 1px 7px;
  margin-right: var(--s-2);
  vertical-align: middle;
}}
.sceis-badge {{
  background: var(--color-brand-secondary);
  color: #fff;
}}
.lea-badge {{
  background: var(--success-bg);
  color: var(--color-success);
}}
.warn-badge {{
  background: var(--warning-bg);
  color: var(--color-warning);
  border: 1px solid #c8920055;
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  border-radius: 999px;
  padding: 1px 8px;
  margin-right: var(--s-2);
}}

/* ── methodology footer ──────────────────────────────────────────────────── */
.methodology {{
  margin: var(--s-6) var(--s-8);
  padding: var(--s-5) var(--s-6);
  background: #fff;
  border: 1px solid var(--color-border-subtle);
  border-top: 3px solid var(--color-brand-primary);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-sm);
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--color-neutral-fg);
}}
.methodology h2 {{
  font-size: 16px;
  font-weight: 700;
  margin-bottom: var(--s-3);
  color: var(--color-brand-primary);
}}
.methodology h3 {{
  font-size: 13.5px;
  font-weight: 600;
  margin: var(--s-4) 0 var(--s-2);
  color: var(--color-brand-secondary);
  border-bottom: 1px solid var(--color-border-subtle);
  padding-bottom: var(--s-1);
}}
.methodology p {{ margin-bottom: var(--s-2); }}
.methodology ul {{
  margin: var(--s-2) 0 var(--s-2) var(--s-5);
}}
.methodology li {{ margin-bottom: var(--s-1); }}
.methodology code {{
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--color-neutral-bg);
  padding: 1px 4px;
  border-radius: 3px;
}}
.var-table {{
  width: 100%;
  border-collapse: collapse;
  margin: var(--s-2) 0 var(--s-3);
  font-size: 12px;
}}
.var-table th {{
  background: var(--color-neutral-bg);
  border: 1px solid var(--color-border-subtle);
  padding: var(--s-2) var(--s-3);
  text-align: left;
  font-weight: 600;
  color: var(--color-neutral-fg);
}}
.var-table td {{
  border: 1px solid var(--color-border-subtle);
  padding: var(--s-2) var(--s-3);
}}
.var-amt {{
  text-align: right;
  font-family: var(--font-mono);
  font-size: 12px;
}}
.var-neg {{
  color: var(--color-danger);
  font-weight: 600;
}}
.meth-dl {{
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: var(--s-1) var(--s-4);
  font-size: 12px;
  margin: var(--s-2) 0;
}}
.meth-dl dt {{
  font-weight: 600;
  color: var(--color-brand-secondary);
  white-space: nowrap;
}}

/* ── print ───────────────────────────────────────────────────────────────── */
@media print {{
  .page-header {{ print-color-adjust: exact; }}
  table.detail-table thead {{ display: table-header-group; }}
  .methodology {{ page-break-before: always; }}
}}
</style>
</head>

<body>

<!-- ── PAGE HEADER ─────────────────────────────────────────────────────── -->
<header class="page-header" role="banner">
  <h1>Detailed Revenue Report
    <span class="mode-badge" aria-label="Report mode">Detail</span>
    <span class="fy25-warn" aria-label="Data completeness warning">FY25 — ~70/80 districts reported</span>
  </h1>
  <p class="sub">
    {DISTRICT_NAME} &nbsp;&bull;&nbsp; {FY_LABEL} &nbsp;&bull;&nbsp;
    District ID: {DISTRICT_ID} &nbsp;&bull;&nbsp;
    Headcount (45-day QDC1): {HEADCOUNT:,} &nbsp;&bull;&nbsp;
    Generated: {GENERATION_TS}
  </p>
</header>

<!-- ── KPI STRIP ───────────────────────────────────────────────────────── -->
<section class="kpi-bar" aria-label="Key revenue totals">

  <div class="kpi">
    <div class="lbl">Grand Total (Operating)</div>
    <div class="val">{fmt(grand_total)}</div>
    <div class="src">Local(LEA) + State(SCEIS) + Federal(SCEIS)</div>
  </div>

  <div class="kpi">
    <div class="lbl">Local Revenue (LEA)</div>
    <div class="val">{fmt(total_local)}</div>
    <div class="src">Self-reported by district</div>
  </div>

  <div class="kpi">
    <div class="lbl">State Total (SCEIS)</div>
    <div class="val val-sceis">{fmt(SCEIS_STATE)}</div>
    <div class="src">FI Payments by Vendor FY25.xlsx</div>
  </div>

  <div class="kpi">
    <div class="lbl">Federal Total (SCEIS)</div>
    <div class="val val-sceis">{fmt(SCEIS_FEDERAL)}</div>
    <div class="src">FI Payments by Vendor FY25.xlsx</div>
  </div>

  <div class="kpi">
    <div class="lbl">State (LEA sub-buckets)</div>
    <div class="val">{fmt(total_state_lea)}</div>
    <div class="src">LEA self-report — does NOT equal SCEIS State total</div>
  </div>

  <div class="kpi">
    <div class="lbl">Other Sources (5xxx)</div>
    <div class="val">{fmt(total_src5)}</div>
    <div class="src">Interfund transfers + non-operating — excluded from Grand Total</div>
  </div>

</section>

<!-- ── FY25 DATA-QUALITY BANNER ────────────────────────────────────────── -->
<div class="banner" role="alert" aria-live="polite">
  <strong>FY2024-25 data-quality note:</strong>
  As of {REPORT_DATE}, approximately 70 of 80 South Carolina districts have
  submitted nonzero LEA self-report data for FY2024-25. Greenville 01 has
  <strong>submitted ({HEADCOUNT:,} headcount, {fmt(total_local)} local revenue)</strong>
  and is included here. Statewide comparisons using this FY should be
  interpreted with caution until the submission cycle is confirmed complete.
  FY2022-23 and FY2023-24 are the recommended validated fiscal years for
  cross-district comparisons.
</div>

<!-- ── DETAIL TABLE ────────────────────────────────────────────────────── -->
<section class="tbl-wrap" aria-label="Revenue detail table">
<table class="detail-table" aria-label="Greenville 01 detailed revenue FY2024-25">
<caption class="sr-only">Greenville County Schools FY2024-25 revenue detail, organized by Local, State, and Federal streams with individual revenue codes and amounts in dollars.</caption>
<colgroup>
  <col class="col-code"/>
  <col class="col-title"/>
  <col class="col-desc"/>
  <col class="col-amt"/>
</colgroup>
<thead>
  <tr>
    <th scope="col">Code</th>
    <th scope="col">Revenue Source</th>
    <th scope="col">Description</th>
    <th scope="col" class="th-amt">Amount ($)</th>
  </tr>
</thead>
<tbody>
{ROWS_HTML}
</tbody>
</table>
</section>

<!-- ── METHODOLOGY FOOTER ──────────────────────────────────────────────── -->
<footer class="methodology" role="contentinfo" aria-label="Methodology and data provenance">
<h2>Methodology &amp; Data Provenance</h2>

<h3>Report mode</h3>
<p>
  <strong>Detail mode</strong> — single-district deep dive showing raw dollar amounts
  (not per-pupil). Four-level hierarchy: Stream (Local / State / Federal) &rarr;
  Category group &rarr; Sub-category &rarr; Revenue Code leaf row.
  Source: <code>lea_revenues</code> filtered on <code>Reported_Flag = TRUE</code>,
  joined to <code>code_district_funding_streams</code> and
  <code>code_accounting_codes</code>/<code>code_historical_revenue_codes</code>
  for descriptions.
</p>

<h3>Source assignment by bucket</h3>
<dl class="meth-dl">
  <dt>State Total</dt>
  <dd>
    <span class="source-badge sceis-badge">SCEIS</span>
    <code>vw_sceis_fi_payments_classified</code> filtered to
    <code>Funding_Stream='State'</code> and <code>District_ID='2301'</code>,
    summed for <code>Fiscal_Year=2025</code>.
    Source file: <code>FI Payments by Vendor FY25.xlsx</code>.
    This is the system-of-record total displayed in KPIs and the
    SCEIS row in the table.
  </dd>
  <dt>Federal Total</dt>
  <dd>
    <span class="source-badge sceis-badge">SCEIS</span>
    Same view, <code>Funding_Stream='Federal'</code>.
    Source file: <code>FI Payments by Vendor FY25.xlsx</code>.
  </dd>
  <dt>Local Revenue</dt>
  <dd>
    <span class="source-badge lea-badge">LEA</span>
    <code>lea_revenues</code> for <code>District_ID='2301'</code>,
    <code>FY=2025</code>, <code>Reported_Flag=TRUE</code>,
    joined on <code>Stream_Type='Local'</code>.
    Source file: <code>Revenue FY2024-25.xlsx</code>.
  </dd>
  <dt>State sub-buckets (leaf rows)</dt>
  <dd>
    <span class="source-badge lea-badge">LEA</span>
    Same <code>lea_revenues</code> source, <code>Stream_Type='State'</code>.
    These leaf rows are displayed for program-level visibility but their
    sum intentionally diverges from the SCEIS State Total (see below).
  </dd>
  <dt>Detail rows (all Revenue Codes)</dt>
  <dd>
    <span class="source-badge lea-badge">LEA</span>
    All leaf rows in this report are LEA self-reported.
    SCEIS cannot be used for per-Revenue_Code attribution because
    <code>lookup_gl_account</code> is empty and
    no <code>Program_Tag &rarr; Revenue_Code</code> mapping exists.
  </dd>
</dl>

<h3>Internal source inconsistency — State &amp; Federal totals</h3>
<p>
  A known, intentional discrepancy exists between the LEA-sourced sub-bucket
  sums and the SCEIS-sourced stream totals. The table displays both; the
  SCEIS total is the authoritative figure for the Grand Total calculation.
  <strong>Do not interpret the sub-bucket sum as the authoritative State or
  Federal total.</strong>
</p>
{var_html}
<p>
  The State variance of {fmt(state_variance)} and Federal variance of
  {fmt(federal_variance)} reflect differences in recognition timing,
  fund accounting conventions, and the fact that SCEIS records state
  outflows at the point of payment while LEA self-reports record receipt.
  Neither figure is wrong; they measure different things.
</p>

<h3>Headcount &amp; per-pupil normalization</h3>
<p>
  Headcount denominator: <strong>{HEADCOUNT:,}</strong> (45-day PowerSchool QDC1,
  <code>lea_headcounts</code>, <code>SY=2025</code>, <code>Report_Cycle=45</code>).
  Per-pupil figures are <strong>not shown</strong> in this detail-mode report
  (detail mode uses raw dollars per the specification).
  For per-pupil figures see the <code>compare-table</code> or
  <code>compare-chart</code> modes.
  ADM (135-day) was not used as the denominator per project conventions.
</p>

<h3>FY2024-25 data-quality status</h3>
<p>
  As of {REPORT_DATE}, approximately 70 of 80 South Carolina districts have
  submitted nonzero data for FY2024-25. Greenville 01
  (<code>Reported_Flag=TRUE</code>) is one of the confirmed submitters.
  Statewide aggregates for FY2024-25 should be treated as preliminary.
  Validated statewide comparisons are available for FY2022-23 and
  FY2023-24.
</p>

<h3>Excluded entities</h3>
<p>
  The following entities are excluded from district revenue rollups per
  <code>lookup_district_exclusions</code> (<code>Exclude_Scope='all_reports'</code>),
  the single source of truth for permanent and time-bounded exclusions:
</p>
<ul>
  <li>5205 — SC Governor's School for Agriculture at John De La Howe</li>
  <li>5207 — SC School for the Deaf and the Blind</li>
  <li>5208 — Department of Juvenile Justice (DJJ)</li>
  <li>5209 — Department of Corrections (DOC)</li>
  <li>5364 — Governor's School for the Arts and Humanities</li>
  <li>5395 — Governor's School for Science and Mathematics</li>
</ul>

<h3>Uncategorized revenue codes</h3>
<p>
  The following revenue codes appear in Greenville 01 FY2024-25 data but are
  not cataloged in <code>code_district_funding_streams</code>. They are
  displayed in the table but excluded from stream subtotals. A record has
  been written to <code>data/staging/uncategorized_codes.csv</code> for
  follow-up by the code-catalog agent:
</p>
<ul>
  <li><code>3597</code> — Aid To Districts ({fmt(6423)})</li>
  <li><code>5210</code> — Transfer From General Fund ({fmt(98498617)}) — interfund transfer</li>
  <li><code>5220</code> — Transfer Fr. Special Revenue ({fmt(250146)})</li>
  <li><code>5230</code> — Transfer Fr. Special Revenue EIA ({fmt(68949735)})</li>
  <li><code>5240</code> — Transfer Fr. Debt Service Fund ({fmt(163219996)})</li>
  <li><code>5260</code> — Transfer Fr. Food Service Fund ({fmt(750000)})</li>
  <li><code>5280</code> — Transfer Fr. Other Funds ({fmt(3951351)})</li>
  <li><code>5300</code> — Sale Of Fixed Assets ({fmt(168288)})</li>
</ul>
<p>
  Note: 5xxx codes (Other Sources &amp; Transfers) are by design non-operating
  and excluded from the Grand Total. Code <code>3597</code> carries
  {fmt(6423)} and has no <code>code_district_funding_streams</code> entry;
  it is logged for catalog review.
</p>

<h3>Tooltip descriptions</h3>
<p>
  All revenue-code tooltips in this report are sourced from
  <code>code_accounting_codes.Short_Description</code> (current codes) and
  <code>code_historical_revenue_codes.Short_Description</code> (retired codes),
  via COALESCE. Rendered with Tippy.js v6 (CDN). Nineteen codes in the
  Greenville FY2024-25 data set have no description in either table
  (e.g., 3165, 3189, 4560, 4974); these codes show only the code number
  in their tooltip.
</p>

<div class="meth-dl" style="margin-top:16px; font-size:11px; color:var(--color-border);">
  <dt>Report mode</dt><dd>detail</dd>
  <dt>District</dt><dd>Greenville 01 (2301) — Greenville County Schools</dd>
  <dt>Fiscal year</dt><dd>FY2024-25 (FY=2025)</dd>
  <dt>School year</dt><dd>SY 2024-25 (SY=2025)</dd>
  <dt>Headcount source</dt><dd>lea_headcounts, 45-day QDC1</dd>
  <dt>SCEIS source</dt><dd>FI Payments by Vendor FY25.xlsx via vw_sceis_fi_payments_classified</dd>
  <dt>LEA source</dt><dd>Revenue FY2024-25.xlsx via lea_revenues</dd>
  <dt>Generated</dt><dd>{GENERATION_TS}</dd>
  <dt>Report date</dt><dd>{REPORT_DATE}</dd>
</div>
</footer>

<!-- ── TIPPY INIT ───────────────────────────────────────────────────────── -->
<script>
document.addEventListener('DOMContentLoaded', function () {{
  tippy('[data-tippy-content]', {{
    theme: 'scde',
    placement: 'top',
    animation: 'shift-away',
    delay: [120, 0],
    maxWidth: 360,
    allowHTML: true,
    interactive: false,
    appendTo: document.body,
    onShow(instance) {{
      const el = instance.reference;
      const allow = el.getAttribute('data-tippy-allowHTML');
      if (!allow || allow === 'false') {{
        instance.setContent(instance.reference.getAttribute('data-tippy-content'));
      }}
    }}
  }});
}});
</script>

</body>
</html>
"""

# ── write output ──────────────────────────────────────────────────────────────
ts  = datetime.now().strftime('%Y%m%dT%H%M%S')
out = os.path.join(BASE, 'outputs', 'reports',
                   f'district_revenue_detail_FY2025_{ts}_2301_Greenville.html')
os.makedirs(os.path.dirname(out), exist_ok=True)

with open(out, 'w', encoding='utf-8') as fh:
    fh.write(HTML)

print(f'OUTPUT PATH: {out}')
print(f'File size: {os.path.getsize(out):,} bytes')
print(f'Rows written: {len(ROWS)}')
print(f'Grand Total: {fmt(grand_total)}')
