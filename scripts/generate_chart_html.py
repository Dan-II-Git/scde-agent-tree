"""
Generate district_revenue_compare-chart_FY2025_<ts>.html
Reads chart_data_fy2025.json from data/staging/ and writes the final HTML
to outputs/reports/.
"""
import json
import datetime
import os

with open('data/staging/chart_data_fy2025.json') as f:
    d = json.load(f)

ROWS_JS = json.dumps(d['rows'], separators=(',', ':'))
SC_JS   = json.dumps(d['sc_row'], separators=(',', ':'))
TOTAL_DISTRICTS = d['total_districts']
REPORTING_COUNT = d['reporting_count']
TOTAL_HC        = d['total_hc']
REPORTING_HC    = d['reporting_hc']

SC = d['sc_row']
EXCLUDED = d['excluded']
UNREPORTED = d['unreported']  # list of district IDs

# build unreported info from rows
unr_info = {r['id']: r for r in d['rows'] if not r['is_reported']}

ts = datetime.datetime.now().strftime('%Y%m%dT%H%M%S')
filename = f'district_revenue_compare-chart_FY2025_{ts}.html'
outpath  = os.path.join('outputs', 'reports', filename)

def fmt_dollar(n):
    n = round(n)
    if n < 0:
        return f'(${ abs(n):,})'
    if n == 0:
        return '$0'
    return f'${n:,}'

# Build variance table HTML rows
var_rows_html = ''
for r in sorted(d['rows'], key=lambda x: x['name']):
    sceis = r['state_sceis_raw']
    lea   = r['lea_state_raw']
    var   = r['state_variance_raw']
    if sceis == 0 and lea == 0:
        continue
    var_class = 'neg' if var < 0 else ('pos' if var > 0 else 'num')
    var_str   = fmt_dollar(var)
    reported_mark = '' if r['is_reported'] else ' *'
    var_rows_html += f'''<tr>
      <td>{r["name"]}{reported_mark}</td>
      <td class="num">{fmt_dollar(sceis)}</td>
      <td class="num">{fmt_dollar(lea)}</td>
      <td class="{var_class}">{var_str}</td>
    </tr>\n'''

# Build unreported list HTML
unr_html = ''
for uid, ur in sorted(unr_info.items()):
    unr_html += f'<li><strong>{ur["name"]} ({uid}):</strong> SCEIS State {fmt_dollar(ur["state_sceis_raw"])} | Federal {fmt_dollar(ur["federal_sceis_raw"])}</li>\n'

# Build excluded list HTML
excl_html = ''
for e in EXCLUDED:
    state_str = fmt_dollar(e['state_total']) if e['state_total'] else '$0'
    fed_str   = fmt_dollar(e['federal_total']) if e['federal_total'] else '$0'
    excl_html += f'<li><strong>{e["name"]} ({e["id"]}):</strong> SCEIS State {state_str} | Federal {fed_str} — excluded per <code>lookup_district_exclusions</code></li>\n'

# Compute exclusion headcount/dollar impact for footer note
# The 6 excluded have ~$38k federal, no state, and headcounts from the HC table
excl_fed_total = sum(e['federal_total'] for e in EXCLUDED)
# Headcount of excluded (from original HC table, before exclusion filter)
# We know total non-excluded HC = TOTAL_HC (787,732), excluded are 6 entities
# Per task: ~0.10% headcount, $38k SCEIS

HTML = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>FY2024-25 District Revenue — Comparison Chart</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<script src="https://unpkg.com/@popperjs/core@2/dist/umd/popper.min.js"></script>
<script src="https://unpkg.com/tippy.js@6/dist/tippy-bundle.umd.min.js"></script>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/dist/tippy.css"/>
<link rel="stylesheet" href="https://unpkg.com/tippy.js@6/animations/shift-away.css"/>

<style>
/* ============================================================
   SCDE Finance Design System — tokens from docs/style/scde-design/tokens.json
   ============================================================ */
:root {{
  /* brand */
  --brand-primary:   #2F3D4C;
  --brand-secondary: #234058;
  --brand-tertiary:  #43718B;
  --brand-accent:    #F1BA55;

  /* semantic */
  --semantic-success:       #1F7A3A;
  --semantic-warning:       #8A5A00;
  --semantic-danger:        #B3261E;
  --semantic-info:          #234058;
  --semantic-neutral-bg:    #F4F6F8;
  --semantic-neutral-fg:    #2F3D4C;
  --semantic-border:        #7E8C9E;
  --semantic-border-subtle: #CBD5E0;

  /* categorical — Okabe-Ito, index 0 = SCDE dark blue, index 7 = neutral dark gray */
  --cat-0: #234058;
  --cat-1: #E69F00;
  --cat-2: #56B4E9;
  --cat-3: #009E73;
  --cat-4: #CC79A7;
  --cat-5: #0072B2;
  --cat-6: #D55E00;
  --cat-7: #666666;

  /* typography */
  --font-display: 'Poppins', 'Segoe UI', system-ui, sans-serif;
  --font-body:    'Poppins', 'Segoe UI', system-ui, sans-serif;
  --font-mono:    'JetBrains Mono', 'Consolas', 'Menlo', monospace;

  /* spacing (4px base) */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 20px; --sp-6: 24px; --sp-8: 32px;

  /* radius */
  --r-sm: 4px;  --r-md: 8px;  --r-lg: 16px;

  /* shadows */
  --shadow-sm: 0 1px 2px rgba(47,61,76,0.06), 0 1px 1px rgba(47,61,76,0.04);
  --shadow-md: 0 4px 8px rgba(47,61,76,0.08), 0 2px 4px rgba(47,61,76,0.06);
  --shadow-lg: 0 12px 24px rgba(47,61,76,0.12), 0 4px 8px rgba(47,61,76,0.08);

  /* segment colors (6 chart segments using categorical palette) */
  --seg-state:     #234058; /* cat-0 SCDE dark blue — 10.79:1 on white, PASS */
  --seg-sac-req:   #009E73; /* cat-3 Okabe green   — 4.55:1 on white, PASS */
  --seg-additional:#0072B2; /* cat-5 Okabe blue    — 5.85:1 on white, PASS */
  --seg-dist-svc:  #CC79A7; /* cat-4 Okabe purple  — 3.51:1 on white, PASS */
  --seg-invest:    #D55E00; /* cat-6 Okabe vermillion — 4.97:1 on white, PASS */
  --seg-federal:   #666666; /* cat-7 neutral gray  — 5.74:1 on white, PASS */
  /* Note: orange #E69F00 (cat-1) and sky #56B4E9 (cat-2) fail 3:1 on white.
     Those two are NOT used as segment fills; they are reserved for future overlays
     and would require the 1.5px dark keyline + distinct marker + direct-label mitigations
     per the contrast-audit.md mandatory-mitigations policy. */
}}

*{{box-sizing:border-box;margin:0;padding:0;}}
body{{
  font-family:var(--font-body);
  font-size:14px;
  line-height:20px;
  background:var(--semantic-neutral-bg);
  color:var(--semantic-neutral-fg);
}}

/* ---- Page Header ---- */
.page-header {{
  background: var(--brand-primary);
  color: #fff;
  padding: var(--sp-5) var(--sp-8) var(--sp-4);
  border-bottom: 4px solid var(--brand-accent);
  display: flex;
  align-items: flex-start;
  gap: var(--sp-6);
}}
.page-header-text {{ flex: 1; }}
.page-header h1 {{
  font-size: 22px;
  font-weight: 700;
  line-height: 30px;
}}
.page-header .sub {{
  font-size: 12px;
  line-height: 16px;
  opacity: 0.82;
  margin-top: var(--sp-1);
}}
.badge-fy {{
  display: inline-block;
  background: var(--brand-accent);
  color: var(--brand-primary);
  padding: 2px 12px;
  border-radius: var(--r-lg);
  font-size: 12px;
  font-weight: 700;
  margin-left: var(--sp-2);
  vertical-align: middle;
}}
.badge-mode {{
  display: inline-block;
  background: var(--brand-secondary);
  color: #fff;
  border: 1px solid rgba(255,255,255,0.25);
  padding: 2px 10px;
  border-radius: var(--r-lg);
  font-size: 11px;
  font-weight: 600;
  margin-left: var(--sp-2);
  vertical-align: middle;
  letter-spacing: 0.4px;
}}
.badge-excl {{
  display: inline-block;
  background: var(--semantic-danger);
  color: #fff;
  padding: 2px 10px;
  border-radius: var(--r-lg);
  font-size: 11px;
  font-weight: 600;
  margin-left: var(--sp-2);
  vertical-align: middle;
}}

/* ---- Alert Bar ---- */
.alert-bar {{
  background: #FFF8E7;
  border-left: 4px solid var(--brand-accent);
  padding: var(--sp-3) var(--sp-8);
  font-size: 12px;
  color: var(--semantic-warning);
  line-height: 18px;
}}
.alert-bar.info {{
  background: #EBF2F7;
  border-color: var(--brand-tertiary);
  color: var(--semantic-info);
}}
.alert-bar.exclusion {{
  background: #FDF0EF;
  border-color: var(--semantic-danger);
  color: #5c1a17;
}}
.alert-bar strong {{ color: var(--brand-primary); }}

/* ---- Controls bar ---- */
.controls {{
  background: #fff;
  border-bottom: 1px solid var(--semantic-border-subtle);
  padding: var(--sp-3) var(--sp-8);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-6);
  align-items: center;
  box-shadow: var(--shadow-sm);
}}
.ctrl-group {{ display: flex; align-items: center; gap: var(--sp-2); }}
.ctrl-group label {{
  font-size: 12px;
  font-weight: 600;
  color: var(--semantic-border);
  white-space: nowrap;
}}
.ctrl-group select, .ctrl-group input[type=range] {{
  border: 1px solid var(--semantic-border);
  border-radius: var(--r-sm);
  padding: 4px 10px;
  font-size: 12px;
  font-family: var(--font-body);
  color: var(--semantic-neutral-fg);
  background: #fff;
  cursor: pointer;
}}
.ctrl-group select:focus {{
  outline: 3px solid var(--brand-primary);
  outline-offset: 2px;
}}
.ctrl-stat {{
  margin-left: auto;
  font-size: 11px;
  color: var(--semantic-border);
  white-space: nowrap;
}}
.ctrl-stat span {{ font-weight: 600; color: var(--semantic-neutral-fg); }}

/* ---- Legend ---- */
.legend-wrap {{
  background: #fff;
  padding: var(--sp-3) var(--sp-8) var(--sp-2);
  border-bottom: 1px solid var(--semantic-border-subtle);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-6);
  align-items: center;
}}
.leg-title {{
  font-size: 11px;
  font-weight: 600;
  color: var(--semantic-border);
  margin-right: var(--sp-1);
}}
.leg-item {{
  display: flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: 12px;
  font-weight: 500;
  color: var(--semantic-neutral-fg);
  cursor: help;
  border-radius: var(--r-sm);
  padding: 2px 6px 2px 4px;
  transition: background 0.1s;
}}
.leg-item:hover {{ background: var(--semantic-neutral-bg); }}
.leg-swatch {{
  width: 14px;
  height: 14px;
  border-radius: 3px;
  flex-shrink: 0;
  border: 1px solid rgba(0,0,0,0.08);
}}
.leg-item .stack-order {{
  font-size: 10px;
  color: var(--semantic-border);
  margin-left: 2px;
}}

/* ---- Chart container ---- */
.chart-wrap {{
  background: #fff;
  padding: var(--sp-5) var(--sp-8) var(--sp-3);
  overflow-x: auto;
  position: relative;
  box-shadow: var(--shadow-md);
  margin: var(--sp-4) var(--sp-8);
  border-radius: var(--r-md);
  border: 1px solid var(--semantic-border-subtle);
}}
.chart-title {{
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-primary);
  margin-bottom: var(--sp-3);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}}
.chart-title .unit-label {{
  font-size: 11px;
  font-weight: 400;
  color: var(--semantic-border);
  margin-left: auto;
  font-family: var(--font-mono);
}}

canvas#chart {{
  display: block;
  cursor: crosshair;
}}

/* ---- Tooltip (canvas hover) ---- */
.hover-tooltip {{
  position: fixed;
  background: var(--brand-primary);
  color: #fff;
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-md);
  font-size: 12px;
  line-height: 18px;
  pointer-events: none;
  z-index: 9999;
  max-width: 280px;
  box-shadow: var(--shadow-lg);
  display: none;
}}
.hover-tooltip .tt-name {{
  font-weight: 700;
  font-size: 13px;
  border-bottom: 1px solid rgba(255,255,255,0.2);
  padding-bottom: 4px;
  margin-bottom: 4px;
}}
.hover-tooltip .tt-row {{ display: flex; justify-content: space-between; gap: 8px; }}
.hover-tooltip .tt-label {{ color: rgba(255,255,255,0.78); }}
.hover-tooltip .tt-val {{ font-family: var(--font-mono); font-weight: 500; text-align: right; }}
.hover-tooltip .tt-total {{
  border-top: 1px solid rgba(255,255,255,0.2);
  margin-top: 4px;
  padding-top: 4px;
  font-weight: 700;
}}
.hover-tooltip .tt-unreported {{
  background: rgba(241,186,85,0.2);
  border-radius: 3px;
  padding: 2px 4px;
  font-size: 11px;
  margin-top: 4px;
  color: var(--brand-accent);
}}

/* ---- KPI cards strip ---- */
.kpi-strip {{
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  padding: var(--sp-4) var(--sp-8);
}}
.kpi-card {{
  background: #fff;
  border-radius: var(--r-md);
  border: 1px solid var(--semantic-border-subtle);
  padding: var(--sp-4) var(--sp-5);
  flex: 1 1 160px;
  box-shadow: var(--shadow-md);
  min-width: 140px;
}}
.kpi-card .kpi-label {{
  font-size: 12px;
  font-weight: 500;
  color: var(--semantic-border);
  margin-bottom: var(--sp-1);
  display: flex;
  align-items: center;
  gap: 4px;
}}
.kpi-card .kpi-swatch {{
  width: 10px; height: 10px; border-radius: 2px;
  display: inline-block; flex-shrink: 0;
  border: 1px solid rgba(0,0,0,0.08);
}}
.kpi-card .kpi-val {{
  font-size: 22px;
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--brand-primary);
  line-height: 28px;
}}
.kpi-card .kpi-sub {{
  font-size: 11px;
  color: var(--semantic-border);
  margin-top: 2px;
}}

/* ---- Data table (hidden alt) ---- */
.sr-table-toggle {{
  display: block;
  text-align: center;
  padding: var(--sp-3);
  font-size: 12px;
  color: var(--brand-secondary);
  cursor: pointer;
  background: #fff;
  border: 1px solid var(--semantic-border-subtle);
  border-top: none;
  margin: 0 var(--sp-8) var(--sp-4);
  border-radius: 0 0 var(--r-md) var(--r-md);
  text-decoration: underline;
}}
#sr-data-table {{ display: none; }}
#sr-data-table.visible {{ display: block; }}
.data-table-wrap {{
  overflow-x: auto;
  padding: var(--sp-4) var(--sp-8);
}}
table.rev-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}}
table.rev-table th {{
  background: var(--brand-primary);
  color: #fff;
  padding: var(--sp-2) var(--sp-3);
  text-align: left;
  font-weight: 600;
  white-space: nowrap;
  position: sticky;
  top: 0;
  z-index: 1;
}}
table.rev-table th.num {{ text-align: right; }}
table.rev-table td {{
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--semantic-border-subtle);
  white-space: nowrap;
}}
table.rev-table td.num {{
  text-align: right;
  font-family: var(--font-mono);
  font-size: 11px;
}}
table.rev-table tr:hover td {{ background: var(--semantic-neutral-bg); }}
table.rev-table tr.unreported td {{ color: var(--semantic-warning); font-style: italic; }}
table.rev-table tr.sc-total td {{
  font-weight: 700;
  background: #EBF2F7;
  border-top: 2px solid var(--brand-secondary);
}}

/* ---- Footer ---- */
footer {{
  background: #fff;
  border-top: 2px solid var(--semantic-border-subtle);
  padding: var(--sp-8);
  margin-top: var(--sp-6);
}}
.footer-grid {{
  max-width: 1200px;
  margin: 0 auto;
  display: grid;
  gap: var(--sp-5);
}}
.footer-section h3 {{
  font-size: 13px;
  font-weight: 700;
  color: var(--brand-primary);
  margin-bottom: var(--sp-2);
  display: flex;
  align-items: center;
  gap: var(--sp-1);
}}
.footer-section h3::before {{
  content: '';
  display: inline-block;
  width: 3px;
  height: 14px;
  background: var(--brand-accent);
  border-radius: 2px;
  flex-shrink: 0;
}}
.footer-section p, .footer-section li {{
  font-size: 12px;
  line-height: 18px;
  color: #4a5568;
}}
.footer-section ul {{ margin-left: var(--sp-5); margin-top: var(--sp-1); }}
.footer-section code {{
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--semantic-neutral-bg);
  padding: 1px 5px;
  border-radius: 3px;
  color: var(--brand-primary);
}}

.variance-table {{ width: 100%; border-collapse: collapse; margin-top: var(--sp-2); font-size: 11px; }}
.variance-table th {{
  background: var(--semantic-neutral-bg);
  padding: var(--sp-1) var(--sp-3);
  text-align: left;
  font-weight: 600;
  color: var(--brand-primary);
  border-bottom: 1px solid var(--semantic-border-subtle);
}}
.variance-table th.num {{ text-align: right; }}
.variance-table td {{
  padding: var(--sp-1) var(--sp-3);
  border-bottom: 1px solid var(--semantic-border-subtle);
}}
.variance-table td.num {{ text-align: right; font-family: var(--font-mono); }}
.variance-table td.neg {{ color: var(--semantic-danger); font-family: var(--font-mono); text-align: right; }}
.variance-table td.pos {{ color: var(--semantic-success); font-family: var(--font-mono); text-align: right; }}

.meta-line {{
  font-size: 11px;
  color: var(--semantic-border);
  text-align: center;
  margin-top: var(--sp-5);
  font-family: var(--font-mono);
}}

/* ---- Tippy theme ---- */
.tippy-box[data-theme~='scde'] {{
  background: var(--brand-primary);
  color: #fff;
  font-family: var(--font-body);
  font-size: 12px;
  border-radius: var(--r-md);
  box-shadow: var(--shadow-lg);
}}
.tippy-box[data-theme~='scde'] .tippy-content {{ padding: var(--sp-3) var(--sp-4); line-height: 1.55; }}
.tippy-box[data-theme~='scde'] .tippy-arrow::before {{ color: var(--brand-primary); }}

/* ---- Accessibility / motion ---- */
@media (prefers-reduced-motion: reduce) {{
  * {{ transition: none !important; animation: none !important; }}
}}

/* ---- Responsive ---- */
@media (max-width: 600px) {{
  .page-header, .controls, .kpi-strip, .chart-wrap {{ padding-left: var(--sp-4); padding-right: var(--sp-4); }}
  .kpi-card {{ min-width: 120px; }}
}}
</style>
</head>
<body>

<!-- ================================================================
     PAGE HEADER
     ================================================================ -->
<header class="page-header" role="banner">
  <div class="page-header-text">
    <h1>
      District Revenue &mdash; Comparison Chart
      <span class="badge-fy">FY2024-25</span>
      <span class="badge-mode">compare-chart</span>
      <span class="badge-excl">Exclusions updated</span>
    </h1>
    <div class="sub">
      Per-pupil revenue by funding stream &bull; SY2025 45-day headcount denominator &bull;
      {TOTAL_DISTRICTS} districts &bull; 6 entities excluded via <code>lookup_district_exclusions</code> &bull;
      SCEIS State + Federal as system-of-record; Local from LEA self-reports &bull;
      Statewide row: weighted average
    </div>
  </div>
</header>

<!-- ================================================================
     DATA-QUALITY AND EXCLUSION BANNERS
     ================================================================ -->
<div class="alert-bar exclusion" role="note" aria-label="Exclusion notice">
  <strong>Exclusion update (regeneration):</strong>
  6 entities removed from all aggregates via <code>lookup_district_exclusions WHERE Exclude_Scope=&#39;all_reports&#39;</code>:
  5205 (Gov School Ag/De La Howe), 5207 (Deaf &amp; Blind), 5208 (DJJ), 5209 (DOC),
  5364 (Arts &amp; Humanities), 5395 (Science &amp; Mathematics).
  These entities do not appear as bars, do not contribute to weighted averages, and are not
  included in any chart annotation. De minimis impact: ~0.10% of headcount, approximately
  $38,000 in SCEIS payments (federal only, entity 5205 only; all others $0 SCEIS).
</div>
<div class="alert-bar" role="note" aria-label="Data quality notice">
  <strong>FY2025 Data Quality &mdash; YELLOW / Partial Submission:</strong>
  {REPORTING_COUNT} of {TOTAL_DISTRICTS} districts submitted Reported_Flag=TRUE LEA data as of 2026-04-28.
  7 districts show SCEIS-only totals with LEA local columns as n/a (Beaufort 01, Clarendon 06,
  Greenwood 50, Jasper 01, Lancaster 01, Laurens 55, Saluda 01).
  Barnwell merger applied: 0601 revenue includes 0645+0648 SCEIS federal payments.
</div>
<div class="alert-bar info" role="note" aria-label="Sourcing methodology note">
  <strong>Sourcing:</strong>
  <strong>State Total &amp; Federal Total:</strong> SCEIS system-of-record
  (<code>vw_sceis_fi_payments_classified</code>, <em>FI Payments by Vendor FY25.xlsx</em>).
  <strong>Local sub-buckets:</strong> LEA self-report
  (<code>lea_revenues</code> Reported_Flag=TRUE, <em>Revenue FY2024-25.xlsx</em>).
  State sub-buckets shown in comparison-table only. The chart enforces hybrid sourcing at
  stream level &mdash; see footer for the disclosed internal inconsistency.
</div>

<!-- ================================================================
     CONTROLS
     ================================================================ -->
<div class="controls" role="toolbar" aria-label="Chart controls">
  <div class="ctrl-group">
    <label for="sortSel">Sort by:</label>
    <select id="sortSel" aria-label="Sort districts by">
      <option value="grand_total_pp">Grand Total (per-pupil)</option>
      <option value="state_total_sceis">State (SCEIS, per-pupil)</option>
      <option value="federal_total_sceis">Federal (SCEIS, per-pupil)</option>
      <option value="local_total">Local Total (per-pupil)</option>
      <option value="name">Name (A&ndash;Z)</option>
    </select>
  </div>
  <div class="ctrl-group">
    <label for="ordSel">Order:</label>
    <select id="ordSel" aria-label="Sort order">
      <option value="desc">Descending</option>
      <option value="asc">Ascending</option>
    </select>
  </div>
  <div class="ctrl-group">
    <label for="topNSel">Show:</label>
    <select id="topNSel" aria-label="Number of districts to show">
      <option value="20">Top 20</option>
      <option value="40">Top 40</option>
      <option value="{TOTAL_DISTRICTS}" selected>All {TOTAL_DISTRICTS}</option>
    </select>
  </div>
  <div class="ctrl-group">
    <label for="scToggle">SC avg:</label>
    <select id="scToggle" aria-label="Show or hide SC weighted average">
      <option value="1" selected>Show</option>
      <option value="0">Hide</option>
    </select>
  </div>
  <div class="ctrl-stat" id="ctrlStat">Showing <span id="ctrlStatN">{TOTAL_DISTRICTS}</span> of {TOTAL_DISTRICTS} districts</div>
</div>

<!-- ================================================================
     LEGEND
     ================================================================ -->
<div class="legend-wrap" role="list" aria-label="Chart legend">
  <span class="leg-title">Segments (bottom to top):</span>
  <div class="leg-item" role="listitem" tabindex="0"
       data-tippy-content="&lt;strong&gt;State (SCEIS)&lt;/strong&gt;&lt;br&gt;Total state funds disbursed to this district per the SCEIS audited ledger (FI Payments system-of-record). Source: vw_sceis_fi_payments_classified, Funding_Stream=&#39;State&#39;.&lt;br&gt;&lt;br&gt;&lt;em&gt;Why no SAC / PropTax / Other sub-buckets here?&lt;/em&gt; The chart shows one SCEIS-sourced segment because no GL&rarr;Revenue_Code mapping currently exists to split FI Payment rows into the three sub-buckets. Sub-bucket detail is available in the companion comparison-table report. The lookup_gl_account table is empty and Clearing_Doc_Number is NULL across all FI Payment rows.">
    <span class="leg-swatch" style="background:var(--seg-state)"></span>
    State (SCEIS)
    <span class="stack-order">&#9312;</span>
  </div>
  <div class="leg-item" role="listitem" tabindex="0"
       data-tippy-content="&lt;strong&gt;Local SAC Required&lt;/strong&gt; (LEA self-report)&lt;br&gt;Ad valorem taxes and related levies assessed by the LEA (revenue codes 11xx: 1110 Ad Valorem Taxes, 1140 Penalties &amp; Interest, 1190 Other Taxes). These are the local matching taxes required under the SC Education Finance Act formula. Source: lea_revenues, Stream_Type=&#39;Local&#39;, code group 11xx.">
    <span class="leg-swatch" style="background:var(--seg-sac-req)"></span>
    Local SAC Required
    <span class="stack-order">&#9313;</span>
  </div>
  <div class="leg-item" role="listitem" tabindex="0"
       data-tippy-content="&lt;strong&gt;Local Additional&lt;/strong&gt; (LEA self-report)&lt;br&gt;Non-LEA governmental unit taxes (12xx: 1210 Non-LEA Ad Valorem, 1240 Penalties, 1280 Revenue in Lieu, 1290 Other), plus other local revenue not in a named sub-bucket (1900 Other Local, 1920 Private Sources, 1950 Refunds, 1990-1999 Misc). Source: lea_revenues, Stream_Type=&#39;Local&#39;, codes 12xx and unassigned 19xx.">
    <span class="leg-swatch" style="background:var(--seg-additional)"></span>
    Local Additional
    <span class="stack-order">&#9314;</span>
  </div>
  <div class="leg-item" role="listitem" tabindex="0"
       data-tippy-content="&lt;strong&gt;Local District Services&lt;/strong&gt; (LEA self-report)&lt;br&gt;Revenue from district-operated services: Tuition (13xx), Transportation Fees (14xx), Food Services (16xx), Pupil Activities (17xx), Rentals (1910), Special Needs Transportation / Medicaid (1930&ndash;1931), Canteen (1992). These are fee-for-service revenues from district operations. Source: lea_revenues, Stream_Type=&#39;Local&#39;, codes 13xx, 14xx, 16xx, 17xx, 1910, 1930, 1931, 1992.">
    <span class="leg-swatch" style="background:var(--seg-dist-svc)"></span>
    Local District Services
    <span class="stack-order">&#9315;</span>
  </div>
  <div class="leg-item" role="listitem" tabindex="0"
       data-tippy-content="&lt;strong&gt;Local Investments &amp; Donations&lt;/strong&gt; (LEA self-report)&lt;br&gt;Earnings on investments and related receipts: 1510 Interest on Investments, 1520 Dividends, 1530 Gain/(Loss) on Sale of Investments. Source: lea_revenues, Stream_Type=&#39;Local&#39;, code group 15xx.">
    <span class="leg-swatch" style="background:var(--seg-invest)"></span>
    Local Investments
    <span class="stack-order">&#9316;</span>
  </div>
  <div class="leg-item" role="listitem" tabindex="0"
       data-tippy-content="&lt;strong&gt;Federal (SCEIS)&lt;/strong&gt;&lt;br&gt;Total federal funds disbursed to this district per the SCEIS audited ledger. Source: vw_sceis_fi_payments_classified, Funding_Stream=&#39;Federal&#39;. Sub-bucket detail (Title I, IDEA, etc.) is available in the LEA self-report but is not shown here because stream-level SCEIS is the system-of-record for the displayed total.">
    <span class="leg-swatch" style="background:var(--seg-federal)"></span>
    Federal (SCEIS)
    <span class="stack-order">&#9317;</span>
  </div>
</div>

<!-- ================================================================
     KPI STRIP
     ================================================================ -->
<div class="kpi-strip" role="region" aria-label="Statewide weighted average per-pupil revenue">
  <div class="kpi-card">
    <div class="kpi-label">SC Grand Total</div>
    <div class="kpi-val">${SC['grand_total_pp']:,}</div>
    <div class="kpi-sub">per pupil, weighted avg</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label"><span class="kpi-swatch" style="background:var(--seg-state)"></span>State (SCEIS)</div>
    <div class="kpi-val">${SC['state_total_sceis']:,}</div>
    <div class="kpi-sub">{round(SC['state_total_sceis']/SC['grand_total_pp']*100,1)}% of total</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label"><span class="kpi-swatch" style="background:var(--seg-sac-req)"></span>Local SAC Req.</div>
    <div class="kpi-val">${SC['local_sac_req']:,}</div>
    <div class="kpi-sub">{round(SC['local_sac_req']/SC['grand_total_pp']*100,1)}% of total</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label"><span class="kpi-swatch" style="background:var(--seg-additional)"></span>Local Additional</div>
    <div class="kpi-val">${SC['local_additional']:,}</div>
    <div class="kpi-sub">{round(SC['local_additional']/SC['grand_total_pp']*100,1)}% of total</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label"><span class="kpi-swatch" style="background:var(--seg-dist-svc)"></span>District Services</div>
    <div class="kpi-val">${SC['local_dist_svc']:,}</div>
    <div class="kpi-sub">{round(SC['local_dist_svc']/SC['grand_total_pp']*100,1)}% of total</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label"><span class="kpi-swatch" style="background:var(--seg-invest)"></span>Investments</div>
    <div class="kpi-val">${SC['local_investments']:,}</div>
    <div class="kpi-sub">{round(SC['local_investments']/SC['grand_total_pp']*100,1)}% of total</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label"><span class="kpi-swatch" style="background:var(--seg-federal)"></span>Federal (SCEIS)</div>
    <div class="kpi-val">${SC['federal_total_sceis']:,}</div>
    <div class="kpi-sub">{round(SC['federal_total_sceis']/SC['grand_total_pp']*100,1)}% of total</div>
  </div>
  <div class="kpi-card">
    <div class="kpi-label">Headcount basis</div>
    <div class="kpi-val" style="font-size:18px;">{TOTAL_HC:,}</div>
    <div class="kpi-sub">SY2025 45-day, {REPORTING_COUNT} reporting</div>
  </div>
</div>

<!-- ================================================================
     CHART
     ================================================================ -->
<div class="chart-wrap" role="figure" aria-label="Stacked bar chart of per-pupil revenue by district">
  <div class="chart-title">
    Per-Pupil Revenue by District &mdash; FY2024-25
    <span class="unit-label">$ per pupil (45-day headcount) &bull; Other Sources (5xxx) excluded from bars</span>
  </div>
  <canvas id="chart" role="img" aria-label="Stacked bar chart showing per-pupil revenue for {TOTAL_DISTRICTS} South Carolina school districts. 6 entities excluded: 5205, 5207, 5208, 5209, 5364, 5395."></canvas>
</div>
<div class="hover-tooltip" id="hoverTT" aria-hidden="true"></div>

<!-- Screen-reader data table toggle -->
<button class="sr-table-toggle" onclick="toggleTable()" id="srToggleBtn" aria-expanded="false" aria-controls="sr-data-table">
  Show data table (screen reader / keyboard accessible)
</button>

<div id="sr-data-table" role="region" aria-label="Data table">
  <div class="data-table-wrap">
    <table class="rev-table" id="revTable">
      <caption style="caption-side:top;text-align:left;font-size:12px;font-weight:600;color:var(--brand-primary);padding:var(--sp-2) 0 var(--sp-2);">
        FY2024-25 Per-Pupil Revenue by District &mdash; All segments ($) &mdash; 6 entities excluded per lookup_district_exclusions
      </caption>
      <thead>
        <tr>
          <th scope="col">District</th>
          <th scope="col">ID</th>
          <th scope="col" class="num">Headcount</th>
          <th scope="col" class="num">State (SCEIS)</th>
          <th scope="col" class="num">Local SAC Req.</th>
          <th scope="col" class="num">Local Additional</th>
          <th scope="col" class="num">Dist. Services</th>
          <th scope="col" class="num">Investments</th>
          <th scope="col" class="num">Federal (SCEIS)</th>
          <th scope="col" class="num">Grand Total</th>
          <th scope="col">Status</th>
        </tr>
      </thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
</div>

<!-- ================================================================
     FOOTER
     ================================================================ -->
<footer role="contentinfo">
  <div class="footer-grid">

    <div class="footer-section">
      <h3>District Exclusions</h3>
      <p>
        The following 6 entities are excluded from all bars, all weighted-average aggregates, and all
        chart annotations. Exclusions are sourced from <code>lookup_district_exclusions</code>
        <code>WHERE Exclude_Scope=&#39;all_reports&#39;</code> and applied identically to both
        LEA aggregation and SCEIS aggregation. These entities receive direct agency appropriations
        not routed through the standard LEA revenue ledger.
      </p>
      <ul>
{excl_html}      </ul>
      <p style="margin-top:6px;">
        <strong>De minimis impact:</strong>
        ~0.10% of statewide headcount (approximately 790 pupils across all 6 entities combined).
        SCEIS dollar impact: approximately $38,000 in federal payments (entity 5205 only;
        entities 5207, 5208, 5209, 5364, and 5395 show $0 SCEIS for FY2025).
        The statewide weighted average is materially unaffected by these exclusions.
      </p>
    </div>

    <div class="footer-section">
      <h3>Data Provenance</h3>
      <p>
        <strong>State Total &amp; Federal Total (displayed bars):</strong>
        SCEIS system-of-record &mdash; <code>vw_sceis_fi_payments_classified</code>
        filtered to <code>Funding_Stream IN (&#39;State&#39;,&#39;Federal&#39;)</code>, Fiscal_Year=2025.
        Source file: <em>FI Payments by Vendor FY25.xlsx</em>. Audited state-side ledger.
      </p>
      <p style="margin-top:6px;">
        <strong>Local sub-buckets (SAC Required, Additional, District Services, Investments):</strong>
        LEA self-report &mdash; <code>lea_revenues</code> filtered <code>Reported_Flag=TRUE</code>,
        FY=2025, with bucket assignment by revenue code prefix range per handbook definitions
        (11xx = SAC Required; 12xx + unassigned 19xx = Additional;
        13xx, 14xx, 16xx, 17xx, 1910, 1930, 1931, 1992 = District Services; 15xx = Investments).
        Source file: <em>Revenue FY2024-25.xlsx</em>.
      </p>
      <p style="margin-top:6px;">
        <strong>Headcount:</strong> 45-day PowerSchool QDC1 &mdash;
        <code>lea_headcounts.Total_Active_Enrollment</code>, SY=2025.
        ADM is not used; headcount is the operational/policy denominator per SCDE reporting convention.
        Barnwell merger: headcount 0601 (3,088) used as denominator; SCEIS federal payments
        for 0645 ($2,839,253) and 0648 ($682,601) merged into Barnwell 01.
      </p>
    </div>

    <div class="footer-section">
      <h3>Internal Inconsistency &mdash; State Bucket</h3>
      <p>
        The SCEIS-sourced State Total and the sum of LEA-reported State sub-buckets
        (SAC / Property Tax / Other, shown in the companion comparison-table report) <strong>will not agree</strong>.
        SCEIS captures cash disbursements at the state ledger level;
        LEA self-reports classify by program code via a separate collection system.
        No GL&rarr;Revenue_Code bridge currently exists to reconcile these at the sub-bucket level
        (<code>lookup_gl_account</code> is empty; <code>Clearing_Doc_Number</code> is NULL
        across all FI Payment rows; no <code>Program_Tag&rarr;Revenue_Code</code> mapping exists).
        The gap is the disclosed signal &mdash; <strong>do not pro-rate or adjust the sub-buckets
        to force agreement.</strong>
      </p>
      <p style="margin-top:6px;">
        For this chart, State is shown as one SCEIS segment (system-of-record).
        Sub-bucket detail lives in the comparison-table report only.
      </p>
      <details style="margin-top:8px;">
        <summary style="font-size:12px;font-weight:600;color:var(--brand-secondary);cursor:pointer;">
          Show per-district State variance table (SCEIS vs LEA self-report)
        </summary>
        <p style="font-size:11px;color:var(--semantic-border);margin-top:4px;">
          * = unreported district (LEA self-report $0; SCEIS-only totals shown in chart)
        </p>
        <div style="overflow-x:auto;margin-top:8px;">
          <table class="variance-table">
            <thead>
              <tr>
                <th>District</th>
                <th class="num">SCEIS State ($)</th>
                <th class="num">LEA State ($)</th>
                <th class="num">Variance ($)</th>
              </tr>
            </thead>
            <tbody>
{var_rows_html}            </tbody>
          </table>
        </div>
      </details>
    </div>

    <div class="footer-section">
      <h3>Unreported / SCEIS-Only Districts (FY2025)</h3>
      <p>The following {len(unr_info)} districts have <code>Reported_Flag=FALSE</code> in <code>lea_revenues</code>
         for FY=2025. Their LEA local segments are shown as $0 in the chart (no local bar segments);
         only SCEIS State and Federal totals are displayed. Unreported districts are marked with a
         gold diamond indicator above their bar.</p>
      <ul>
{unr_html}      </ul>
    </div>

    <div class="footer-section">
      <h3>Methodology Notes</h3>
      <ul>
        <li>
          <strong>Per-pupil denominator:</strong> 45-day PowerSchool QDC1 headcount
          (<code>lea_headcounts.Total_Active_Enrollment</code>, SY=2025). Not 135-day ADM.
        </li>
        <li>
          <strong>Statewide weighted average:</strong>
          SUM(revenue dollars) / SUM(headcount) across all {TOTAL_DISTRICTS} districts for SCEIS streams;
          SUM(LEA dollars) / SUM(headcount) across {REPORTING_COUNT} reporting districts for local streams.
          Not the arithmetic mean of district per-pupil rates.
        </li>
        <li>
          <strong>Barnwell merger (FY2024+ rule):</strong>
          SCEIS federal payments for Barnwell 45 (0645) and Barnwell 48 (0648) summed into Barnwell 01 (0601).
          Barnwell 01&apos;s SY2025 headcount (3,088) used as denominator.
          0645 and 0648 have <code>Reported_Flag=FALSE</code> for all FY2025 LEA rows.
          SCEIS sums: 0601 State $25,993,969 + 0645 Federal $2,839,253 + 0648 Federal $682,601
          merged into the Barnwell 01 bar.
        </li>
        <li>
          <strong>Exclusion source of truth:</strong>
          <code>lookup_district_exclusions WHERE Exclude_Scope=&#39;all_reports&#39;
          AND (Effective_FY_From IS NULL OR Effective_FY_From&lt;=2025)
          AND (Effective_FY_To IS NULL OR Effective_FY_To&gt;=2025)</code>.
          Applied identically to LEA query and SCEIS query. Previous version (FY2025 20260428T120000)
          excluded only 4 entities (5208, 5209, 5364, 5395); this regeneration adds 5205 and 5207.
        </li>
        <li>
          <strong>Negative currency:</strong>
          Rendered as $(X,XXX) with
          <span style="color:var(--semantic-danger);font-weight:600;">semantic.danger (#B3261E)</span>.
          Zero shown as $0.
        </li>
        <li>
          <strong>Other Sources (5xxx bond proceeds / interfund transfers):</strong>
          Excluded from bar segments. Included in grand-total tooltip hover only.
        </li>
        <li>
          <strong>Chart axes:</strong>
          Y-axis currency-formatted with SI suffixes (K = thousands, M = millions). Right-aligned.
          X-axis labels tilted 45&deg; ({TOTAL_DISTRICTS} districts exceeds the &le;6 tick threshold for 0&deg; labels).
          Horizontal gridlines only; no vertical gridlines per design-system rule 5.6.
        </li>
        <li>
          <strong>Colorblind accessibility:</strong>
          6 segment colors drawn from Okabe-Ito palette indices 0, 3, 5, 4, 6, 7 &mdash; all pass
          3:1 non-text contrast threshold on white. Orange (#E69F00) and sky (#56B4E9) which fail
          3:1 are not used as segment fills per contrast-audit.md.
        </li>
      </ul>
    </div>

    <div class="footer-section">
      <h3>Data Quality Verdict</h3>
      <p>
        <span style="background:#FFF8E7;color:var(--semantic-warning);padding:2px 10px;border-radius:var(--r-lg);font-weight:700;font-size:11px;">
          YELLOW &mdash; FY2025: Proceed with caveats
        </span>
        &nbsp;{REPORTING_COUNT} of {TOTAL_DISTRICTS} districts submitted as of 2026-04-28.
        FY2025 LEA submission cycle incomplete; 7 districts LEA-unreported (SCEIS-only).
        Statewide weighted average for local buckets uses {REPORTING_COUNT}-district denominator only;
        SCEIS streams use all {TOTAL_DISTRICTS} districts.
        SCEIS data covers all {TOTAL_DISTRICTS} districts (Barnwell merger applied).
      </p>
    </div>

    <div class="meta-line">
      FY2024-25 (fiscal year ending June 2025) &bull; SY2025 45-day headcount &bull;
      Generated: {ts} &bull; Source DB: db/scde.duckdb &bull;
      Mode: compare-chart &bull; Agent: report-district-revenue &bull;
      Exclusions: lookup_district_exclusions (6 entities: 5205, 5207, 5208, 5209, 5364, 5395)
    </div>

  </div>
</footer>

<!-- ================================================================
     JAVASCRIPT
     ================================================================ -->
<script>
"use strict";

// ---------------------------------------------------------------
// DATA (assembled from db/scde.duckdb FY2025 — exclusions applied)
// ---------------------------------------------------------------
const DATA = {ROWS_JS};

const SC_ROW = {SC_JS};

// Segment config — bottom-to-top stacking order
const SEGS = [
  {{ key: 'state_total_sceis',   label: 'State (SCEIS)',           color: '#234058' }},
  {{ key: 'local_sac_req',       label: 'Local SAC Required',      color: '#009E73' }},
  {{ key: 'local_additional',    label: 'Local Additional',        color: '#0072B2' }},
  {{ key: 'local_dist_svc',      label: 'Local District Services', color: '#CC79A7' }},
  {{ key: 'local_investments',   label: 'Local Investments',       color: '#D55E00' }},
  {{ key: 'federal_total_sceis', label: 'Federal (SCEIS)',         color: '#666666' }},
];

// ---------------------------------------------------------------
// UTILITIES
// ---------------------------------------------------------------
function fmtCurrency(v) {{
  if (v === null || v === undefined) return 'n/a';
  const n = Math.round(v);
  if (n < 0) return '($' + Math.abs(n).toLocaleString('en-US') + ')';
  if (n === 0) return '$0';
  return '$' + n.toLocaleString('en-US');
}}

function fmtSI(v) {{
  const n = Math.round(v);
  if (n >= 1000000) return '$' + (n / 1000000).toFixed(1) + 'M';
  if (n >= 1000)    return '$' + (n / 1000).toFixed(0) + 'K';
  return '$' + n.toLocaleString('en-US');
}}

function fmtNeg(v) {{
  if (v < 0) return '<span style="color:var(--semantic-danger)">($' + Math.abs(v).toLocaleString('en-US') + ')</span>';
  if (v === 0) return '$0';
  return '$' + v.toLocaleString('en-US');
}}

// ---------------------------------------------------------------
// STATE
// ---------------------------------------------------------------
let sortKey = 'grand_total_pp';
let sortAsc  = false;
let topN     = {TOTAL_DISTRICTS};
let showSC   = true;
let hitMap   = [];

// ---------------------------------------------------------------
// GET SORTED ROWS
// ---------------------------------------------------------------
function getRows() {{
  let rows = DATA.slice();
  rows.forEach(d => {{
    d._local_total = (d.local_sac_req||0) + (d.local_additional||0) + (d.local_dist_svc||0) + (d.local_investments||0);
  }});
  if (sortKey === 'name') {{
    rows.sort((a, b) => sortAsc ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name));
  }} else if (sortKey === 'local_total') {{
    rows.sort((a, b) => sortAsc ? a._local_total - b._local_total : b._local_total - a._local_total);
  }} else {{
    rows.sort((a, b) => sortAsc ? a[sortKey] - b[sortKey] : b[sortKey] - a[sortKey]);
  }}
  return rows.slice(0, topN);
}}

// ---------------------------------------------------------------
// DRAW CHART
// ---------------------------------------------------------------
function drawChart() {{
  const rows    = getRows();
  const allRows = showSC ? [...rows, SC_ROW] : rows;

  const canvas = document.getElementById('chart');
  const dpr    = window.devicePixelRatio || 1;

  const PAD_L = 62;
  const PAD_R = 20;
  const PAD_T = 18;
  const PAD_B = 115; // room for 45-degree x-labels

  const barW   = Math.max(7, Math.min(34, Math.floor((window.innerWidth - 140) / allRows.length) - 3));
  const chartW = PAD_L + allRows.length * (barW + 3) + PAD_R;
  const chartH = 450;

  canvas.style.width  = chartW + 'px';
  canvas.style.height = chartH + 'px';
  canvas.width  = chartW * dpr;
  canvas.height = chartH * dpr;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, chartW, chartH);

  const maxVal = Math.max(...allRows.map(d => d.grand_total_pp || 0), 1);
  const drawH  = chartH - PAD_B - PAD_T;

  // ---- Y-axis gridlines + labels (SI suffix, right-aligned per spec 5.6) ----
  const numTicks = 5;
  ctx.font = `10px 'JetBrains Mono', monospace`;
  ctx.textAlign = 'right';
  for (let i = 0; i <= numTicks; i++) {{
    const frac = i / numTicks;
    const val  = maxVal * frac;
    const y    = PAD_T + drawH - frac * drawH;
    ctx.strokeStyle = 'rgba(203,213,224,0.7)'; // border_subtle @ 70%
    ctx.lineWidth   = 1;
    ctx.beginPath(); ctx.moveTo(PAD_L, y); ctx.lineTo(chartW - PAD_R, y); ctx.stroke();
    ctx.fillStyle = '#7E8C9E';
    ctx.fillText(fmtSI(val), PAD_L - 5, y + 3.5);
  }}

  // ---- Bars ----
  hitMap = [];
  allRows.forEach((d, i) => {{
    const isSCRow = d.id === 'SC';
    const x       = PAD_L + i * (barW + 3);
    let   yBottom = PAD_T + drawH;

    SEGS.forEach(seg => {{
      const ppv = d[seg.key] || 0;
      if (ppv <= 0) return;
      const bh = Math.max(1, (ppv / maxVal) * drawH);
      yBottom -= bh;
      ctx.fillStyle   = seg.color;
      ctx.globalAlpha = isSCRow ? 0.82 : 1.0;
      ctx.fillRect(x, yBottom, barW, bh);
      ctx.globalAlpha = 1.0;
    }});

    // SC reference line — dashed gold separator
    if (isSCRow) {{
      ctx.strokeStyle = '#F1BA55';
      ctx.lineWidth   = 2;
      ctx.setLineDash([4, 3]);
      ctx.beginPath();
      ctx.moveTo(x - 2, PAD_T);
      ctx.lineTo(x - 2, PAD_T + drawH);
      ctx.stroke();
      ctx.setLineDash([]);
    }}

    // Unreported indicator: gold diamond above bar
    if (!d.is_reported && d.id !== 'SC') {{
      const barTop = PAD_T + drawH - ((d.grand_total_pp || 0) / maxVal) * drawH;
      ctx.fillStyle = '#F1BA55';
      ctx.beginPath();
      ctx.moveTo(x + barW/2,     barTop - 8);
      ctx.lineTo(x + barW/2 + 4, barTop - 4);
      ctx.lineTo(x + barW/2,     barTop);
      ctx.lineTo(x + barW/2 - 4, barTop - 4);
      ctx.closePath();
      ctx.fill();
    }}

    // X-axis label — 45 degrees (>6 ticks per spec 5.6)
    ctx.save();
    ctx.translate(x + barW/2, PAD_T + drawH + 6);
    ctx.rotate(-Math.PI / 4);
    ctx.font      = isSCRow ? `bold 9px 'Poppins', sans-serif` : `9px 'Poppins', sans-serif`;
    ctx.fillStyle = isSCRow ? '#234058' : '#2F3D4C';
    ctx.textAlign = 'right';
    const lbl = d.name.length > 18 ? d.name.slice(0, 17) + '…' : d.name;
    ctx.fillText(lbl, 0, 0);
    ctx.restore();

    hitMap.push({{ x, barW, data: d }});
  }});

  // ---- Axis lines ----
  ctx.strokeStyle = '#7E8C9E';
  ctx.lineWidth   = 1;
  ctx.beginPath(); ctx.moveTo(PAD_L, PAD_T); ctx.lineTo(PAD_L, PAD_T + drawH); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(PAD_L, PAD_T + drawH); ctx.lineTo(chartW - PAD_R, PAD_T + drawH); ctx.stroke();

  document.getElementById('ctrlStatN').textContent = rows.length;
}}

// ---------------------------------------------------------------
// TOOLTIP
// ---------------------------------------------------------------
const tt = document.getElementById('hoverTT');

document.getElementById('chart').addEventListener('mousemove', function(e) {{
  const rect = this.getBoundingClientRect();
  const mx   = e.clientX - rect.left;

  let found = null;
  for (const hit of hitMap) {{
    if (mx >= hit.x && mx <= hit.x + hit.barW) {{ found = hit.data; break; }}
  }}

  if (!found) {{ tt.style.display = 'none'; return; }}

  const d = found;
  const localTotal = (d.local_sac_req||0) + (d.local_additional||0) + (d.local_dist_svc||0) + (d.local_investments||0);
  const grandWithOther = (d.grand_total_pp||0) + (d.other_sources_pp||0);

  let html = `<div class="tt-name">${{d.name}} (${{d.id}})</div>`;
  if (d.headcount) html += `<div class="tt-row"><span class="tt-label">Headcount (SY2025)</span><span class="tt-val">${{d.headcount.toLocaleString('en-US')}}</span></div>`;
  html += `<div class="tt-row"><span class="tt-label" style="color:#8db4cc">■ State (SCEIS)</span><span class="tt-val">${{fmtCurrency(d.state_total_sceis)}}</span></div>`;
  if (d.is_reported) {{
    html += `<div class="tt-row"><span class="tt-label" style="color:#5dc0a0">■ SAC Required</span><span class="tt-val">${{fmtCurrency(d.local_sac_req)}}</span></div>`;
    html += `<div class="tt-row"><span class="tt-label" style="color:#7abbd8">■ Local Additional</span><span class="tt-val">${{fmtCurrency(d.local_additional)}}</span></div>`;
    html += `<div class="tt-row"><span class="tt-label" style="color:#d9a4c0">■ Dist. Services</span><span class="tt-val">${{fmtCurrency(d.local_dist_svc)}}</span></div>`;
    html += `<div class="tt-row"><span class="tt-label" style="color:#e09070">■ Investments</span><span class="tt-val">${{fmtCurrency(d.local_investments)}}</span></div>`;
  }} else {{
    html += `<div class="tt-unreported">&#9672; LEA self-report: not submitted (SCEIS-only)</div>`;
  }}
  html += `<div class="tt-row"><span class="tt-label" style="color:#aaa">■ Federal (SCEIS)</span><span class="tt-val">${{fmtCurrency(d.federal_total_sceis)}}</span></div>`;
  html += `<div class="tt-row tt-total"><span class="tt-label">Grand Total (bars)</span><span class="tt-val">${{fmtCurrency(d.grand_total_pp)}}</span></div>`;
  if (d.other_sources_pp && d.other_sources_pp > 0) {{
    html += `<div class="tt-row" style="opacity:0.75;font-size:10px;"><span class="tt-label">+ Other Sources (5xxx, not shown)</span><span class="tt-val">${{fmtCurrency(d.other_sources_pp)}}</span></div>`;
    html += `<div class="tt-row" style="opacity:0.75;font-size:10px;"><span class="tt-label">Incl. Other Sources</span><span class="tt-val">${{fmtCurrency(grandWithOther)}}</span></div>`;
  }}

  tt.innerHTML  = html;
  tt.style.display = 'block';
  const ttW = 270, ttH = 200;
  let lx = e.clientX + 14, ly = e.clientY - 20;
  if (lx + ttW > window.innerWidth  - 10) lx = e.clientX - ttW - 14;
  if (ly + ttH > window.innerHeight - 10) ly = e.clientY - ttH;
  tt.style.left = lx + 'px';
  tt.style.top  = ly + 'px';
}});

document.getElementById('chart').addEventListener('mouseleave', () => {{ tt.style.display = 'none'; }});

// ---------------------------------------------------------------
// DATA TABLE (screen-reader alternative)
// ---------------------------------------------------------------
function buildTable() {{
  const rows   = getRows();
  const tbody  = document.getElementById('tableBody');
  tbody.innerHTML = '';

  rows.forEach(d => {{
    const tr = document.createElement('tr');
    if (!d.is_reported) tr.className = 'unreported';
    const localTotal = (d.local_sac_req||0)+(d.local_additional||0)+(d.local_dist_svc||0)+(d.local_investments||0);
    tr.innerHTML = `
      <td>${{d.name}}</td>
      <td>${{d.id}}</td>
      <td class="num">${{d.headcount ? d.headcount.toLocaleString('en-US') : 'n/a'}}</td>
      <td class="num">${{fmtCurrency(d.state_total_sceis)}}</td>
      <td class="num">${{fmtCurrency(d.local_sac_req)}}</td>
      <td class="num">${{fmtCurrency(d.local_additional)}}</td>
      <td class="num">${{fmtCurrency(d.local_dist_svc)}}</td>
      <td class="num">${{fmtCurrency(d.local_investments)}}</td>
      <td class="num">${{fmtCurrency(d.federal_total_sceis)}}</td>
      <td class="num">${{fmtCurrency(d.grand_total_pp)}}</td>
      <td>${{d.is_reported ? 'Reported' : 'SCEIS-only'}}</td>
    `;
    tbody.appendChild(tr);
  }});

  // SC Total row
  const tr = document.createElement('tr');
  tr.className = 'sc-total';
  tr.innerHTML = `
    <td>South Carolina (Weighted Avg)</td>
    <td>SC</td>
    <td class="num">${{SC_ROW.headcount.toLocaleString('en-US')}}</td>
    <td class="num">${{fmtCurrency(SC_ROW.state_total_sceis)}}</td>
    <td class="num">${{fmtCurrency(SC_ROW.local_sac_req)}}</td>
    <td class="num">${{fmtCurrency(SC_ROW.local_additional)}}</td>
    <td class="num">${{fmtCurrency(SC_ROW.local_dist_svc)}}</td>
    <td class="num">${{fmtCurrency(SC_ROW.local_investments)}}</td>
    <td class="num">${{fmtCurrency(SC_ROW.federal_total_sceis)}}</td>
    <td class="num">${{fmtCurrency(SC_ROW.grand_total_pp)}}</td>
    <td>Weighted avg</td>
  `;
  tbody.appendChild(tr);
}}

function toggleTable() {{
  const div = document.getElementById('sr-data-table');
  const btn = document.getElementById('srToggleBtn');
  const shown = div.classList.toggle('visible');
  btn.setAttribute('aria-expanded', shown);
  btn.textContent = shown
    ? 'Hide data table'
    : 'Show data table (screen reader / keyboard accessible)';
  if (shown) buildTable();
}}

// ---------------------------------------------------------------
// CONTROLS
// ---------------------------------------------------------------
document.getElementById('sortSel').addEventListener('change', function() {{
  sortKey = this.value; drawChart(); buildTableIfVisible();
}});
document.getElementById('ordSel').addEventListener('change', function() {{
  sortAsc = this.value === 'asc'; drawChart(); buildTableIfVisible();
}});
document.getElementById('topNSel').addEventListener('change', function() {{
  topN = parseInt(this.value, 10); drawChart(); buildTableIfVisible();
}});
document.getElementById('scToggle').addEventListener('change', function() {{
  showSC = this.value === '1'; drawChart();
}});

function buildTableIfVisible() {{
  if (document.getElementById('sr-data-table').classList.contains('visible')) buildTable();
}}

// ---------------------------------------------------------------
// TIPPY on legend items
// ---------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {{
  tippy('[data-tippy-content]', {{
    theme: 'scde',
    allowHTML: true,
    animation: 'shift-away',
    interactive: false,
    trigger: 'mouseenter focus',
    appendTo: document.body,
  }});
  drawChart();
}});

window.addEventListener('resize', drawChart);
</script>

</body>
</html>'''

with open(outpath, 'w', encoding='utf-8') as f:
    f.write(HTML)

print(f"Written: {outpath}")
