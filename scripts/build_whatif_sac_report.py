#!/usr/bin/env python3
"""
build_whatif_sac_report.py — Single-file HTML report builder for the
State Aid to Classrooms What-If scenario tool.

Embeds per-district inputs (category ADM, ITA, hold-harmless floor,
base-FY actuals) plus a JS port of app/whatif_sac.run_scenario so the
user can dial appropriation $ and statute weights and see district-level
allocation impacts live, without a server round-trip.

Run:
  python3 scripts/build_whatif_sac_report.py
  python3 scripts/build_whatif_sac_report.py --base-fy 2024 --output outputs/whatif_sac.html
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sys
from pathlib import Path

# Allow `from app.whatif_sac import ...` when run from repo root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import whatif_sac  # noqa: E402
from app.db import fetchall  # noqa: E402

DEFAULT_OUTPUT = "outputs/reports/whatif_sac.html"

# Token lifts from docs/style/scde-design/tokens.json
TOK = {
    "brand_primary":  "#2F3D4C",
    "brand_secondary":"#234058",
    "brand_tertiary": "#43718B",
    "brand_accent":   "#F1BA55",
    "success":        "#1F7A3A",
    "warning":        "#8A5A00",
    "danger":         "#B3261E",
    "neutral_bg":     "#F4F6F8",
    "neutral_fg":     "#2F3D4C",
    "border":         "#7E8C9E",
    "border_subtle":  "#CBD5E0",
}

# Categorical chart palette — Okabe-Ito; index 0=SCDE blue, index 7=neutral gray
CAT_PALETTE = [
    "#234058", "#E69F00", "#56B4E9", "#009E73",
    "#CC79A7", "#0072B2", "#D55E00", "#666666",
]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--base-fy", type=int, default=whatif_sac.DEFAULT_BASE_FY,
                   help="FY whose 135-day WPU + actuals are used as the input baseline.")
    p.add_argument("--appropriation", type=float, default=whatif_sac.FY26_APPROPRIATION_DEFAULT,
                   help="Initial appropriation $ shown on the slider.")
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args()


def _fetch_headcounts(base_fy: int) -> dict[str, int]:
    """45-day Total_Active_Enrollment per District_ID for SY=base_fy.
    Applies the Barnwell consolidation rule for FY24+ (sum 0645+0648 into
    0601) so the universe matches `whatif_sac._fetch_inputs`. Districts
    with no headcount row are returned as 0."""
    rows = fetchall(
        "SELECT District_ID, Total_Active_Enrollment FROM lea_headcounts "
        "WHERE SY = ? AND Report_Cycle = 45",
        [base_fy],
    )
    hc: dict[str, int] = {did: int(n or 0) for did, n in rows}
    if base_fy >= whatif_sac.BARNWELL_CONSOLIDATION_FROM_FY:
        merged = whatif_sac.BARNWELL_MERGED_ID
        for legacy in whatif_sac.BARNWELL_LEGACY_IDS:
            if legacy in hc:
                hc[merged] = hc.get(merged, 0) + hc.pop(legacy)
    return hc


def _slim_inputs(base_fy: int) -> list[dict]:
    """Shape engine inputs for the embedded JS clone. Emits the same
    universe of districts as `whatif_sac._fetch_inputs` and uses full
    float precision (no rounding) so the JS engine reproduces Python
    output to the cent — see tests/test_whatif_sac_parity.py.

    Headcount is presentation-only (chart Y axis and circle area). The
    formula does not consume it; it is carried through alongside the
    formula inputs so the embedded JS can render `$ aid per pupil`."""
    raw = whatif_sac._fetch_inputs(base_fy)
    headcounts = _fetch_headcounts(base_fy)
    out: list[dict] = []
    for did, rec in raw.items():
        out.append({
            "id": did,
            "name": rec["district_name"],
            "isCharter": rec["is_charter"],
            "ita": float(rec["ita"]),
            "adm": {k: float(v) for k, v in rec["category_adm"].items()},
            "floor": float(rec["hold_harmless_floor"]),
            "actualBaseFY": float(rec["actual_sac_base_fy"]),
            "headcount": headcounts.get(did, 0),
        })
    out.sort(key=lambda r: r["name"])
    return out


# ──────────────────────────────────────────────────────────────────────
# HTML build
# ──────────────────────────────────────────────────────────────────────


def build_html(inputs: list[dict], base_fy: int, init_appropriation: float) -> str:
    inputs_json = json.dumps(inputs, separators=(",", ":"))
    weights_json = json.dumps(whatif_sac.DEFAULT_WEIGHTS)
    floor_codes = ", ".join(whatif_sac.HOLD_HARMLESS_REVENUE_CODES)
    today = dt.date.today().isoformat()

    # Detect total-only mode: source file lacked the Financial Requirements
    # sheet so we only have a TOTAL category per district. Per-category
    # weight dialing is meaningless in this mode and the UI greys it out.
    is_total_only = bool(inputs) and all(
        set(d.get("adm", {}).keys()) <= {"TOTAL"} for d in inputs
    )
    mode_banner = (
        f'<div class="mode-banner">FY{base_fy} source file (WPU 13525.xlsx) only carries district-total WPU — '
        f'the Financial Requirements sheet was not published. Per-category weight dials are disabled. '
        f'Switch to FY24 in the dashboard for full categorical control.</div>'
        if is_total_only else ""
    )

    css = _css()
    js = _js()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SCDE What-If: State Aid to Classrooms</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="report">
  <header class="report-header">
    <div>
      <div class="eyebrow">Strict-formula scenario · FY26 Funding Manual pp. 11–13</div>
      <h1>State Aid to Classrooms — What-If</h1>
      <div class="meta">Inputs: 135-day WPU and FY{base_fy} actuals · ITA Index Year 2025 · generated {today}</div>
    </div>
    <div class="legend-box">
      <div><span class="dot" style="background:{TOK['success']}"></span> Above FY{base_fy} actual</div>
      <div><span class="dot" style="background:{TOK['danger']}"></span> Below FY{base_fy} actual</div>
      <div><span class="dot" style="background:{TOK['brand_accent']}"></span> Hold-harmless floor active</div>
    </div>
  </header>
  {mode_banner}

  <main class="layout">
    <aside class="controls">
      <h2>Scenario Dials</h2>

      <div class="ctrl-group">
        <label class="ctrl-label">
          <span>Total appropriation</span>
          <input type="text" id="in-appropriation" class="ctrl-text"
                 value="${int(init_appropriation):,}"
                 inputmode="numeric" autocomplete="off" spellcheck="false"
                 aria-label="Total appropriation amount in dollars">
        </label>
        <input type="range" id="appropriation"
               min="2000000000" max="6000000000" step="10000000"
               value="{int(init_appropriation)}">
        <div class="ctrl-hint">Slider $2B–$6B · type any positive $ in the box · FY26 enacted $3.81B</div>
      </div>

      <div class="ctrl-group">
        <label class="ctrl-label">
          <span>State share of total program</span>
          <output id="out-state-share">75%</output>
        </label>
        <input type="range" id="state-share" min="0.50" max="1.00" step="0.01" value="0.75">
        <div class="ctrl-hint">Statute = 75%; 1.00 means no local share</div>
      </div>

      <h3>Statute Weights (p.13)</h3>
      <div id="weight-sliders"></div>

      <h3>Toggles</h3>
      <label class="ctrl-toggle">
        <input type="checkbox" id="apply-hh" checked>
        <span>Apply FY{whatif_sac.HOLD_HARMLESS_BASELINE_FY} hold-harmless floor</span>
      </label>
      <label class="ctrl-toggle">
        <input type="checkbox" id="apply-charter" checked>
        <span>Charter authorizers receive 100% state (no local offset)</span>
      </label>

      <button class="btn-reset" id="btn-reset">Reset to statute defaults</button>
    </aside>

    <section class="results">
      <div class="kpi-row">
        <div class="kpi"><div class="kpi-label">Appropriation</div><div class="kpi-value" id="kpi-appropriation"></div></div>
        <div class="kpi"><div class="kpi-label">Total Aid to Classrooms</div><div class="kpi-value" id="kpi-tac"></div><div class="kpi-sub">= appropriation / state share</div></div>
        <div class="kpi"><div class="kpi-label">Statewide WPU</div><div class="kpi-value" id="kpi-wpu"></div></div>
        <div class="kpi"><div class="kpi-label">$/WPU (state share)</div><div class="kpi-value" id="kpi-perwpu"></div></div>
        <div class="kpi"><div class="kpi-label">Hold-harmless inflation</div><div class="kpi-value" id="kpi-hh"></div><div class="kpi-sub" id="kpi-hh-count"></div></div>
        <div class="kpi"><div class="kpi-label">Δ vs FY{base_fy} actual</div><div class="kpi-value" id="kpi-delta"></div></div>
      </div>

      <h2>District Allocations</h2>
      <div class="chart-container">
        <svg id="chart-scatter" viewBox="0 0 720 340" preserveAspectRatio="xMinYMin meet" role="img" aria-label="Per-pupil state aid vs ITA scatter, sized by headcount"></svg>
        <figcaption>X = ITA (relative property wealth) · Y = state aid per active student (45-day headcount, SY=base FY) · circle area ∝ district headcount. Charter authorizers (ITA = 0) cluster at left.</figcaption>
      </div>

      <div class="table-wrap">
        <table id="dist-table">
          <thead>
            <tr>
              <th data-sort="name">District</th>
              <th data-sort="wpu" class="num">WPU</th>
              <th data-sort="ita" class="num">ITA</th>
              <th data-sort="tac" class="num">District TAC</th>
              <th data-sort="local" class="num">Local Share</th>
              <th data-sort="formula" class="num">Formula Aid</th>
              <th data-sort="floor" class="num">FY{whatif_sac.HOLD_HARMLESS_BASELINE_FY} Floor</th>
              <th data-sort="final" class="num">Final Aid</th>
              <th data-sort="delta" class="num">Δ vs FY{base_fy}</th>
            </tr>
          </thead>
          <tbody id="dist-tbody"></tbody>
        </table>
      </div>
    </section>
  </main>

  <footer class="footer">
    <strong>Methodology</strong>
    <p>Strict application of the SAC formula from the FY26 Funding Manual (pp. 11–13):
       TAC = appropriation / state-share %; district TAC = TAC × (district WPU / statewide WPU);
       district local share = total local share × district ITA (zero for charter authorizers);
       final aid = max(formula aid, FY{whatif_sac.HOLD_HARMLESS_BASELINE_FY} hold-harmless floor) when toggle on.</p>
    <p>WPU base: 135-day FY{base_fy} from <code>lea_wpu_category</code>; charter B&amp;M / virtual back-derived from <code>lea_wpu_allocations</code> 45-day rows.
       ITA: Index Year 2025 (Tax Year 2023) from <code>lea_ita</code>; same ITA applied to every base FY.
       Hold-harmless baseline: sum of FY{whatif_sac.HOLD_HARMLESS_BASELINE_FY} actuals across revenue codes {floor_codes} per Funding Manual p.12.</p>
    <p>Caveats: RTF residual (~770 statewide WPU equivalents) flows through a separate channel and is not in 135-day source — engine treats RTF ADM as 0.
       Special districts / career centers / alternative schools are not modeled separately; their FY{whatif_sac.HOLD_HARMLESS_BASELINE_FY} amounts catch them via the hold-harmless floor.
       Proviso overrides and supplemental weights from the appropriation act are NOT modeled.</p>
    <p>Charter authorizer rows show the district total first (bold, with the <code>charter</code> badge), then indented Brick &amp; Mortar and Virtual sub-rows
       beneath it. The sub-rows roll up to exactly the parent total. The split is proportional by additional-charter-weight WPU
       (CHARTER_BM_WPU / (CHARTER_BM_WPU + CHARTER_VIRT_WPU)). The source data does not carry a mode-by-category breakdown — base, SPED, and personalized-instruction
       ADM are not tagged B&amp;M-vs-Virtual — so the proportional split is an approximation, not a statute-prescribed allocation. The parent total is exact.</p>
    <p>Negatives are rendered with accounting parentheses: $(1,234).</p>
  </footer>
</div>

<script>
const INPUTS = {inputs_json};
const DEFAULT_WEIGHTS = {weights_json};
const BASE_FY = {base_fy};
const HH_BASELINE_FY = {whatif_sac.HOLD_HARMLESS_BASELINE_FY};
{js}
</script>
</body>
</html>"""


def _css() -> str:
    return f"""
:root {{
  --brand-primary: {TOK['brand_primary']};
  --brand-secondary: {TOK['brand_secondary']};
  --brand-tertiary: {TOK['brand_tertiary']};
  --brand-accent: {TOK['brand_accent']};
  --success: {TOK['success']};
  --warning: {TOK['warning']};
  --danger: {TOK['danger']};
  --neutral-bg: {TOK['neutral_bg']};
  --neutral-fg: {TOK['neutral_fg']};
  --border: {TOK['border']};
  --border-subtle: {TOK['border_subtle']};
  --font-display: 'Poppins', 'Segoe UI', system-ui, sans-serif;
  --font-mono: 'JetBrains Mono', 'Consolas', monospace;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; padding: 0; background: var(--neutral-bg); color: var(--neutral-fg); font-family: var(--font-display); font-size: 14px; line-height: 1.45; }}
.report {{ max-width: 1400px; margin: 0 auto; padding: 24px; }}

.report-header {{ display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; margin-bottom: 20px; }}
.eyebrow {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--brand-tertiary); font-weight: 600; }}
.report-header h1 {{ font-size: 28px; margin: 4px 0; color: var(--brand-primary); }}
.meta {{ font-size: 12px; color: var(--brand-tertiary); }}
.legend-box {{ display: flex; flex-direction: column; gap: 4px; font-size: 11px; }}
.legend-box .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }}

.layout {{ display: grid; grid-template-columns: 320px 1fr; gap: 20px; align-items: start; }}
@media (max-width: 1100px) {{ .layout {{ grid-template-columns: 1fr; }} }}

.controls {{
  background: #fff; border: 1px solid var(--border-subtle); border-radius: 8px;
  padding: 18px; box-shadow: 0 1px 2px rgba(47,61,76,0.06);
  position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y: auto;
}}
.controls h2 {{ font-size: 16px; margin: 0 0 12px 0; color: var(--brand-secondary); }}
.controls h3 {{ font-size: 13px; margin: 18px 0 8px 0; color: var(--brand-secondary); text-transform: uppercase; letter-spacing: 0.04em; border-bottom: 1px solid var(--border-subtle); padding-bottom: 4px; }}
.ctrl-group {{ margin-bottom: 14px; }}
.ctrl-label {{ display: flex; justify-content: space-between; align-items: center; font-size: 12px; font-weight: 600; color: var(--brand-primary); margin-bottom: 4px; }}
.ctrl-label output {{ font-family: var(--font-mono); font-weight: 500; color: var(--brand-secondary); }}
.ctrl-hint {{ font-size: 11px; color: var(--brand-tertiary); margin-top: 2px; }}
input[type="range"] {{ width: 100%; accent-color: var(--brand-secondary); }}
.ctrl-toggle {{ display: flex; align-items: center; gap: 8px; font-size: 12px; margin: 8px 0; cursor: pointer; }}
.ctrl-toggle input {{ accent-color: var(--brand-secondary); }}
.ctrl-text {{
  font-family: var(--font-mono); font-weight: 500;
  color: var(--brand-secondary); background: #fff;
  border: 1px solid var(--border-subtle); border-radius: 3px;
  padding: 2px 6px; width: 140px; text-align: right; font-size: 12px;
}}
.ctrl-text:focus {{ outline: none; border-color: var(--brand-tertiary); }}
.ctrl-text.invalid {{ border-color: var(--danger); background: rgba(179, 38, 30, 0.05); color: var(--danger); }}
.btn-reset {{
  margin-top: 16px; width: 100%; padding: 8px 12px; font-family: var(--font-display); font-size: 12px;
  background: var(--neutral-bg); color: var(--brand-primary); border: 1px solid var(--border-subtle);
  border-radius: 4px; cursor: pointer; font-weight: 600;
}}
.btn-reset:hover {{ background: var(--brand-primary); color: #fff; border-color: var(--brand-primary); }}

.results {{ min-width: 0; }}
.kpi-row {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 16px; }}
@media (max-width: 1300px) {{ .kpi-row {{ grid-template-columns: repeat(3, 1fr); }} }}
@media (max-width: 700px) {{ .kpi-row {{ grid-template-columns: repeat(2, 1fr); }} }}
.kpi {{ background: #fff; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 12px 14px; box-shadow: 0 1px 2px rgba(47,61,76,0.06); }}
.kpi-label {{ font-size: 11px; text-transform: uppercase; color: var(--brand-tertiary); letter-spacing: 0.04em; }}
.kpi-value {{ font-size: 20px; font-family: var(--font-mono); font-weight: 600; color: var(--brand-primary); margin-top: 4px; }}
.kpi-value.neg {{ color: var(--danger); }}
.kpi-value.pos {{ color: var(--success); }}
.kpi-sub {{ font-size: 11px; color: var(--brand-tertiary); margin-top: 2px; }}

.results h2 {{ font-size: 16px; margin: 16px 0 8px 0; color: var(--brand-secondary); border-bottom: 1px solid var(--border-subtle); padding-bottom: 4px; }}

.chart-container {{ background: #fff; border: 1px solid var(--border-subtle); border-radius: 8px; padding: 14px; box-shadow: 0 1px 2px rgba(47,61,76,0.06); margin-bottom: 16px; }}
.chart-container svg {{ width: 100%; height: auto; display: block; }}
.chart-container figcaption {{ font-size: 11px; color: var(--brand-tertiary); margin-top: 6px; text-align: center; }}

.table-wrap {{ background: #fff; border: 1px solid var(--border-subtle); border-radius: 8px; overflow: auto; max-height: 600px; }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th, td {{ padding: 6px 10px; border-bottom: 1px solid var(--border-subtle); text-align: left; vertical-align: top; }}
th {{ background: var(--neutral-bg); color: var(--brand-primary); font-weight: 600; font-size: 10px; text-transform: uppercase; letter-spacing: 0.04em; position: sticky; top: 0; cursor: pointer; user-select: none; }}
th:hover {{ background: var(--brand-tertiary); color: #fff; }}
th.sort-asc::after {{ content: " ▲"; }}
th.sort-desc::after {{ content: " ▼"; }}
td.num, th.num {{ text-align: right; font-family: var(--font-mono); white-space: nowrap; }}
td.neg {{ color: var(--danger); }}
td.pos {{ color: var(--success); }}
tr.floor-row td {{ background: rgba(241, 186, 85, 0.08); }}
tr.charter-row {{ font-weight: 500; }}
tr.sub-row td {{ background: rgba(35, 64, 88, 0.03); font-style: italic; color: var(--brand-tertiary); }}
tr.sub-row td:first-child {{ padding-left: 24px; border-left: 2px solid var(--border-subtle); }}
tr.parent-row td {{ font-weight: 600; border-top: 2px solid var(--brand-secondary); }}
tr.total-row td {{ font-weight: 600; border-top: 2px solid var(--brand-secondary); }}

.mode-banner {{
  background: rgba(241, 186, 85, 0.18);
  border: 1px solid var(--brand-accent);
  color: var(--brand-primary);
  padding: 10px 14px;
  border-radius: 6px;
  font-size: 12px;
  margin-bottom: 14px;
}}
.ctrl-group.disabled {{ opacity: 0.45; pointer-events: none; }}
.badge {{ display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 999px; font-family: var(--font-mono); }}
.badge.floor {{ background: rgba(241, 186, 85, 0.20); color: var(--warning); border: 1px solid var(--warning); }}
.badge.charter {{ background: rgba(35, 64, 88, 0.10); color: var(--brand-secondary); border: 1px solid var(--brand-secondary); }}

.footer {{ margin-top: 24px; padding: 14px; background: var(--neutral-bg); border-left: 3px solid var(--brand-tertiary); font-size: 12px; color: var(--brand-tertiary); border-radius: 4px; }}
.footer p {{ margin: 6px 0; }}
.footer code {{ background: #fff; padding: 1px 4px; border-radius: 3px; font-family: var(--font-mono); font-size: 11px; }}
"""


def _js() -> str:
    """JS engine that mirrors app/whatif_sac.run_scenario exactly."""
    return r"""
// ─── Formatting helpers ────────────────────────────────────────────────
const fmtMoney = v => {
  if (v == null || !Number.isFinite(v)) return '—';
  const n = Math.round(v);
  if (n === 0) return '$0';
  if (n < 0) return `$(${Math.abs(n).toLocaleString()})`;
  return `$${n.toLocaleString()}`;
};
const fmtMoneySi = v => {
  if (v == null || !Number.isFinite(v)) return '—';
  const a = Math.abs(v);
  let s;
  if (a >= 1e9) s = (a/1e9).toFixed(2) + 'B';
  else if (a >= 1e6) s = (a/1e6).toFixed(1) + 'M';
  else if (a >= 1e3) s = (a/1e3).toFixed(0) + 'K';
  else s = a.toFixed(0);
  return v < 0 ? `$(${s})` : `$${s}`;
};
const fmtInt = v => v == null ? '—' : Math.round(v).toLocaleString();
const fmtPct = v => v == null ? '—' : (v*100).toFixed(1) + '%';
const fmtIta = v => v == null ? '—' : v.toFixed(4);

// ─── Engine ────────────────────────────────────────────────────────────
function runScenario(state) {
  const districts = INPUTS.map(d => {
    const catWpu = {};
    let totalWpu = 0;
    for (const cat in d.adm) {
      const w = state.weights[cat] || 0;
      const wpu = d.adm[cat] * w;
      catWpu[cat] = wpu;
      totalWpu += wpu;
    }
    return {
      id: d.id, name: d.name, isCharter: d.isCharter, ita: d.ita,
      totalWpu, catWpu, floor: d.floor, actualBaseFY: d.actualBaseFY,
      headcount: d.headcount || 0,
    };
  });

  const statewideWpu = districts.reduce((a, r) => a + r.totalWpu, 0);
  if (statewideWpu === 0) return null;

  const stateShare = state.stateSharePct;
  const tac = state.appropriation / stateShare;
  const localShareTotal = tac * (1 - stateShare);

  let sumFormula = 0, sumFinal = 0, floorCount = 0;
  for (const r of districts) {
    const wpuShare = r.totalWpu / statewideWpu;
    r.wpuShare = wpuShare;
    r.districtTac = tac * wpuShare;
    r.localShare = (state.applyCharter && r.isCharter) ? 0 : localShareTotal * r.ita;
    r.formulaAid = r.districtTac - r.localShare;
    r.finalAid = state.applyHH ? Math.max(r.formulaAid, r.floor) : r.formulaAid;
    r.floorKicked = state.applyHH && r.floor > r.formulaAid;
    r.delta = r.finalAid - r.actualBaseFY;
    r.perWpuFinal = r.totalWpu > 0 ? r.finalAid / r.totalWpu : 0;
    r.perHeadcount = r.headcount > 0 ? r.finalAid / r.headcount : null;
    sumFormula += r.formulaAid;
    sumFinal += r.finalAid;
    if (r.floorKicked) floorCount++;
  }

  return {
    districts,
    rollup: {
      appropriation: state.appropriation,
      tac, localShareTotal, statewideWpu, stateShare,
      perWpuStateShare: state.appropriation / statewideWpu,
      sumFormula, sumFinal,
      hhInflation: sumFinal - sumFormula,
      floorCount,
      actualBaseFYTotal: districts.reduce((a, r) => a + r.actualBaseFY, 0),
    },
  };
}

// ─── State + DOM ───────────────────────────────────────────────────────
const STATE = {
  appropriation: parseFloat(document.getElementById('appropriation').value),
  stateSharePct: 0.75,
  weights: { ...DEFAULT_WEIGHTS },
  applyHH: true,
  applyCharter: true,
};

const WEIGHT_LABELS = {
  BASE_K12: 'Base K-12 / homebound',
  SPED: 'SPED (IEP)',
  CTE: 'CTE',
  RTF: 'RTF (residential treatment)',
  GIFTED: 'Gifted & Talented (add-on)',
  ACAD_ASSIST: 'Academic Assistance (add-on)',
  LEP: 'LEP (add-on)',
  POVERTY: 'Poverty (add-on)',
  CHARTER_BM: 'Charter B&M (authorizer-only)',
  CHARTER_VIRT: 'Charter Virtual (authorizer-only)',
  TOTAL: 'Total WPU multiplier (FY25 only)',
};

function buildWeightSliders() {
  const root = document.getElementById('weight-sliders');
  root.innerHTML = '';
  // Detect total-only mode (FY25): every district has only the TOTAL category
  const isTotalOnly = INPUTS.length > 0 &&
    INPUTS.every(d => Object.keys(d.adm).every(k => k === 'TOTAL'));
  for (const key of Object.keys(DEFAULT_WEIGHTS)) {
    // In total-only mode, hide non-TOTAL sliders entirely (they have no effect).
    // In categorical mode, hide TOTAL (it has no effect since there are no TOTAL categories).
    if (isTotalOnly && key !== 'TOTAL') continue;
    if (!isTotalOnly && key === 'TOTAL') continue;
    const def = DEFAULT_WEIGHTS[key];
    const max = Math.max(def * 2, def + 1);
    const wrap = document.createElement('div');
    wrap.className = 'ctrl-group';
    wrap.innerHTML = `
      <label class="ctrl-label">
        <span>${WEIGHT_LABELS[key] || key}</span>
        <output id="out-w-${key}">${def.toFixed(2)}</output>
      </label>
      <input type="range" data-weight="${key}" min="0" max="${max.toFixed(2)}" step="0.05" value="${def}">
      <div class="ctrl-hint">Statute: ${def.toFixed(2)}</div>
    `;
    root.appendChild(wrap);
  }
}

// Strip $, commas, spaces; accept scientific (e.g. "3.8e9") or bare digits.
// Returns NaN for non-positive or non-finite — the caller flags the input.
function parseAppropriation(str) {
  if (str == null) return NaN;
  const cleaned = String(str).replace(/[$,\s_]/g, '');
  if (cleaned === '') return NaN;
  const v = parseFloat(cleaned);
  return (Number.isFinite(v) && v > 0) ? v : NaN;
}

// Single source of truth for "the appropriation changed". Updates state,
// syncs both the slider (clamped to its visual range) and the text input
// (formatted with commas), then re-renders.
function setAppropriation(v) {
  STATE.appropriation = v;
  const slider = document.getElementById('appropriation');
  const txt    = document.getElementById('in-appropriation');
  const sMin = parseFloat(slider.min), sMax = parseFloat(slider.max);
  slider.value = Math.max(sMin, Math.min(sMax, v));
  txt.value = '$' + Math.round(v).toLocaleString();
  txt.classList.remove('invalid');
  rerender();
}

function bindControls() {
  document.getElementById('appropriation').addEventListener('input', e => {
    setAppropriation(parseFloat(e.target.value));
  });
  const txtInp = document.getElementById('in-appropriation');
  txtInp.addEventListener('focus', e => e.target.select());
  txtInp.addEventListener('change', e => {
    const v = parseAppropriation(e.target.value);
    if (Number.isNaN(v)) { e.target.classList.add('invalid'); return; }
    setAppropriation(v);
  });
  // Enter key commits without losing focus
  txtInp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
  });
  document.getElementById('state-share').addEventListener('input', e => {
    STATE.stateSharePct = parseFloat(e.target.value);
    document.getElementById('out-state-share').textContent = (STATE.stateSharePct*100).toFixed(0) + '%';
    rerender();
  });
  document.querySelectorAll('input[data-weight]').forEach(el => {
    el.addEventListener('input', e => {
      const k = e.target.dataset.weight;
      const v = parseFloat(e.target.value);
      STATE.weights[k] = v;
      document.getElementById(`out-w-${k}`).textContent = v.toFixed(2);
      rerender();
    });
  });
  document.getElementById('apply-hh').addEventListener('change', e => {
    STATE.applyHH = e.target.checked;
    rerender();
  });
  document.getElementById('apply-charter').addEventListener('change', e => {
    STATE.applyCharter = e.target.checked;
    rerender();
  });
  document.getElementById('btn-reset').addEventListener('click', () => {
    STATE.stateSharePct = 0.75;
    STATE.weights = { ...DEFAULT_WEIGHTS };
    STATE.applyHH = true;
    STATE.applyCharter = true;
    document.getElementById('state-share').value = STATE.stateSharePct;
    document.getElementById('out-state-share').textContent = '75%';
    document.querySelectorAll('input[data-weight]').forEach(el => {
      const k = el.dataset.weight;
      el.value = DEFAULT_WEIGHTS[k];
      document.getElementById(`out-w-${k}`).textContent = DEFAULT_WEIGHTS[k].toFixed(2);
    });
    document.getElementById('apply-hh').checked = true;
    document.getElementById('apply-charter').checked = true;
    setAppropriation(3810127536);  // also re-renders
  });
}

// ─── Render ────────────────────────────────────────────────────────────
let SORT_KEY = 'final';
let SORT_DIR = 'desc';

function renderKpis(rollup) {
  const baseFyTotal = rollup.actualBaseFYTotal;
  const delta = rollup.sumFinal - baseFyTotal;
  document.getElementById('kpi-appropriation').textContent = fmtMoneySi(rollup.appropriation);
  document.getElementById('kpi-tac').textContent = fmtMoneySi(rollup.tac);
  document.getElementById('kpi-wpu').textContent = fmtInt(rollup.statewideWpu);
  document.getElementById('kpi-perwpu').textContent = '$' + Math.round(rollup.perWpuStateShare).toLocaleString();
  const hhEl = document.getElementById('kpi-hh');
  hhEl.textContent = fmtMoneySi(rollup.hhInflation);
  hhEl.className = 'kpi-value' + (rollup.hhInflation > 0 ? ' pos' : '');
  document.getElementById('kpi-hh-count').textContent = `${rollup.floorCount} districts at floor`;
  const dEl = document.getElementById('kpi-delta');
  dEl.textContent = (delta >= 0 ? '+' : '') + fmtMoneySi(delta);
  dEl.className = 'kpi-value ' + (delta >= 0 ? 'pos' : 'neg');
}

function renderTable(rows) {
  const tbody = document.getElementById('dist-tbody');
  // sort
  const sorters = {
    name: r => r.name, wpu: r => r.totalWpu, ita: r => r.ita,
    tac: r => r.districtTac, local: r => r.localShare,
    formula: r => r.formulaAid, floor: r => r.floor, final: r => r.finalAid,
    delta: r => r.delta,
  };
  const get = sorters[SORT_KEY];
  rows = rows.slice().sort((a, b) => {
    const va = get(a), vb = get(b);
    if (va < vb) return SORT_DIR === 'asc' ? -1 : 1;
    if (va > vb) return SORT_DIR === 'asc' ? 1 : -1;
    return 0;
  });

  const out = [];
  for (const r of rows) {
    const bmW = (r.catWpu && r.catWpu.CHARTER_BM) || 0;
    const vW  = (r.catWpu && r.catWpu.CHARTER_VIRT) || 0;
    const splitable = r.isCharter && (bmW + vW) > 0;
    if (splitable) {
      const sumW = bmW + vW;
      const bmShare = bmW / sumW;
      const vShare  = vW / sumW;
      // Parent/total row first, then sub-rows indented beneath it — outliner
      // order avoids the orphan-sub-row ambiguity when sorted (the prior
      // sub-rows-first layout made the breakdown look like it belonged to
      // the previous, regular district).
      out.push(renderRow(r, 'parent-row charter-row' + (r.floorKicked ? ' floor-row' : '')));
      out.push(renderRow(scaleRow(r, bmShare, '↳ Brick & Mortar'), 'sub-row'));
      out.push(renderRow(scaleRow(r, vShare,  '↳ Virtual'),         'sub-row'));
    } else {
      const cls = (r.floorKicked ? 'floor-row ' : '') + (r.isCharter ? 'charter-row' : '');
      out.push(renderRow(r, cls));
    }
  }
  tbody.innerHTML = out.join('');

  // sort indicators
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.sort === SORT_KEY) th.classList.add(SORT_DIR === 'asc' ? 'sort-asc' : 'sort-desc');
  });
}

function scaleRow(r, share, label) {
  return {
    ...r,
    name: label,
    totalWpu:    r.totalWpu * share,
    districtTac: r.districtTac * share,
    localShare:  r.localShare * share,
    formulaAid:  r.formulaAid * share,
    floor:       r.floor * share,
    finalAid:    r.finalAid * share,
    delta:       r.delta * share,
    floorKicked: false,  // floor flag belongs only on the rollup row
    isSubRow: true,
  };
}

function renderRow(r, trCls) {
  const dCls = r.delta < 0 ? 'neg' : 'pos';
  const isParent = trCls.includes('parent-row');
  const badges = [];
  if (r.floorKicked && !r.isSubRow) badges.push('<span class="badge floor">floor</span>');
  if (r.isCharter && !r.isSubRow) badges.push('<span class="badge charter">charter</span>');
  return `<tr class="${trCls}">
    <td>${r.name} ${badges.join(' ')}</td>
    <td class="num">${fmtInt(r.totalWpu)}</td>
    <td class="num">${fmtIta(r.ita)}</td>
    <td class="num">${fmtMoney(r.districtTac)}</td>
    <td class="num">${fmtMoney(r.localShare)}</td>
    <td class="num">${fmtMoney(r.formulaAid)}</td>
    <td class="num">${fmtMoney(r.floor)}</td>
    <td class="num"><strong>${fmtMoney(r.finalAid)}</strong></td>
    <td class="num ${dCls}">${(r.delta >= 0 ? '+' : '') + fmtMoney(r.delta)}</td>
  </tr>`;
}

function bindSort() {
  document.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
      const k = th.dataset.sort;
      if (SORT_KEY === k) SORT_DIR = SORT_DIR === 'asc' ? 'desc' : 'asc';
      else { SORT_KEY = k; SORT_DIR = (k === 'name') ? 'asc' : 'desc'; }
      rerender();
    });
  });
}

function renderChart(rows) {
  const svg = document.getElementById('chart-scatter');
  const W = 720, H = 340;
  const padL = 60, padR = 24, padT = 16, padB = 44;
  const plotW = W - padL - padR, plotH = H - padT - padB;

  const xMax = 0.18; // most ITA values are < 0.15; cap for readability
  // Y axis = state aid per active student (45-day headcount). Districts
  // with headcount=0 (none currently in the FY25 universe) drop out of
  // the y-scaling but are still drawn at y=0 with a hollow marker.
  const yVals = rows.map(r => r.perHeadcount).filter(v => Number.isFinite(v) && v > 0);
  if (yVals.length === 0) { svg.innerHTML = ''; return; }
  const yMax = Math.max(...yVals) * 1.05;
  const hcMax = Math.max(...rows.map(r => r.headcount || 0));

  const x = v => padL + Math.min(v, xMax) / xMax * plotW;
  const y = v => padT + plotH - (v / yMax) * plotH;
  const radius = h => hcMax > 0 ? 2 + Math.sqrt(h / hcMax) * 14 : 4;

  const parts = [];
  // axes
  parts.push(`<line x1="${padL}" y1="${padT+plotH}" x2="${padL+plotW}" y2="${padT+plotH}" stroke="${'""" + TOK['border'] + r"""'}" />`);
  parts.push(`<line x1="${padL}" y1="${padT}" x2="${padL}" y2="${padT+plotH}" stroke="${'""" + TOK['border'] + r"""'}" />`);
  // y ticks
  for (let k = 0; k <= 4; k++) {
    const v = yMax * k / 4;
    const yy = y(v);
    parts.push(`<line x1="${padL}" y1="${yy}" x2="${padL+plotW}" y2="${yy}" stroke="${'""" + TOK['border_subtle'] + r"""'}" stroke-dasharray="2 4"/>`);
    parts.push(`<text x="${padL-6}" y="${yy+3}" text-anchor="end" font-size="10" font-family="JetBrains Mono,monospace" fill="${'""" + TOK['brand_tertiary'] + r"""'}">${fmtMoneySi(v)}</text>`);
  }
  // x ticks
  for (let k = 0; k <= 4; k++) {
    const v = xMax * k / 4;
    const xx = x(v);
    parts.push(`<line x1="${xx}" y1="${padT}" x2="${xx}" y2="${padT+plotH}" stroke="${'""" + TOK['border_subtle'] + r"""'}" stroke-dasharray="2 4"/>`);
    parts.push(`<text x="${xx}" y="${padT+plotH+14}" text-anchor="middle" font-size="10" font-family="JetBrains Mono,monospace" fill="${'""" + TOK['brand_tertiary'] + r"""'}">${v.toFixed(3)}</text>`);
  }
  // axis titles
  parts.push(`<text x="${padL+plotW/2}" y="${H-6}" text-anchor="middle" font-size="11" fill="${'""" + TOK['brand_secondary'] + r"""'}">ITA (Index of Taxpaying Ability)</text>`);
  parts.push(`<text x="14" y="${padT+plotH/2}" transform="rotate(-90 14 ${padT+plotH/2})" text-anchor="middle" font-size="11" fill="${'""" + TOK['brand_secondary'] + r"""'}">State aid per pupil (45-day headcount)</text>`);

  // dots
  for (const r of rows) {
    if (!Number.isFinite(r.perHeadcount) || r.perHeadcount <= 0) continue;
    const cx = x(r.ita);
    const cy = y(r.perHeadcount);
    const rr = radius(r.headcount);
    const fill = r.delta >= 0 ? '""" + TOK['success'] + r"""' : '""" + TOK['danger'] + r"""';
    const stroke = r.floorKicked ? '""" + TOK['brand_accent'] + r"""' : 'rgba(47,61,76,0.4)';
    const sw = r.floorKicked ? 2 : 1;
    const tip = `${r.name} · Headcount ${fmtInt(r.headcount)} · ITA ${fmtIta(r.ita)} · Final ${fmtMoney(r.finalAid)} (${fmtMoney(r.perHeadcount)}/pupil · Δ ${(r.delta>=0?'+':'')+fmtMoney(r.delta)})`;
    parts.push(`<circle cx="${cx.toFixed(1)}" cy="${cy.toFixed(1)}" r="${rr.toFixed(1)}" fill="${fill}" fill-opacity="0.55" stroke="${stroke}" stroke-width="${sw}"><title>${tip.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</title></circle>`);
  }
  svg.innerHTML = parts.join('');
}

function rerender() {
  const result = runScenario(STATE);
  if (!result) return;
  renderKpis(result.rollup);
  renderTable(result.districts);
  renderChart(result.districts);
}

buildWeightSliders();
bindControls();
bindSort();
setAppropriation(STATE.appropriation);  // initial sync of text input + slider + render
"""


def main():
    args = parse_args()
    inputs = _slim_inputs(args.base_fy)
    if not inputs:
        print(f"ERROR: no input data for FY{args.base_fy}", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_html(inputs, args.base_fy, args.appropriation), encoding="utf-8")

    print(f"Wrote {out_path}")
    print(f"  base FY: {args.base_fy}")
    print(f"  initial appropriation: ${args.appropriation:,.0f}")
    print(f"  districts in scenario: {len(inputs)}")
    print(f"  size: {out_path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
