"""Parity test: the standalone HTML report has its own JS port of the SAC
formula engine, separate from app/whatif_sac.py. This test reproduces the
JS engine literally in Python, runs both engines on the same inputs, and
asserts per-district outputs match — catching drift between the two
implementations.

If this test fails after a Python-engine edit, the JS engine in
scripts/build_whatif_sac_report.py needs the matching change.

Run:
    .venv/Scripts/python tests/test_whatif_sac_parity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import whatif_sac
from scripts.build_whatif_sac_report import _slim_inputs


# ──────────────────────────────────────────────────────────────────────
# Python clone of the JS runScenario in scripts/build_whatif_sac_report.py
# Mirrors the JS function structurally so drift is easy to spot during
# code review. Keep this in sync by visual inspection.
# ──────────────────────────────────────────────────────────────────────


def js_run_scenario_clone(inputs: list[dict], state: dict) -> dict:
    """Literal port of the JS runScenario(state) in build_whatif_sac_report._js()."""
    districts = []
    for d in inputs:
        cat_wpu = {}
        total_wpu = 0.0
        for cat, adm in d["adm"].items():
            w = state["weights"].get(cat, 0.0)
            wpu = adm * w
            cat_wpu[cat] = wpu
            total_wpu += wpu
        districts.append({
            "id": d["id"], "name": d["name"], "isCharter": d["isCharter"], "ita": d["ita"],
            "totalWpu": total_wpu, "catWpu": cat_wpu,
            "floor": d["floor"], "actualBaseFY": d["actualBaseFY"],
        })

    statewide_wpu = sum(r["totalWpu"] for r in districts)
    if statewide_wpu == 0:
        return None

    state_share = state["stateSharePct"]
    tac = state["appropriation"] / state_share
    local_share_total = tac * (1.0 - state_share)

    sum_formula = 0.0
    sum_final = 0.0
    floor_count = 0
    for r in districts:
        wpu_share = r["totalWpu"] / statewide_wpu
        r["wpuShare"] = wpu_share
        r["districtTac"] = tac * wpu_share
        if state["applyCharter"] and r["isCharter"]:
            r["localShare"] = 0.0
        else:
            r["localShare"] = local_share_total * r["ita"]
        r["formulaAid"] = r["districtTac"] - r["localShare"]
        if state["applyHH"]:
            r["finalAid"] = max(r["formulaAid"], r["floor"])
        else:
            r["finalAid"] = r["formulaAid"]
        r["floorKicked"] = state["applyHH"] and r["floor"] > r["formulaAid"]
        r["delta"] = r["finalAid"] - r["actualBaseFY"]
        sum_formula += r["formulaAid"]
        sum_final += r["finalAid"]
        if r["floorKicked"]:
            floor_count += 1

    return {
        "districts": districts,
        "rollup": {
            "appropriation":      state["appropriation"],
            "tac":                tac,
            "localShareTotal":    local_share_total,
            "statewideWpu":       statewide_wpu,
            "stateShare":         state_share,
            "perWpuStateShare":   state["appropriation"] / statewide_wpu,
            "sumFormula":         sum_formula,
            "sumFinal":           sum_final,
            "hhInflation":        sum_final - sum_formula,
            "floorCount":         floor_count,
            "actualBaseFYTotal":  sum(r["actualBaseFY"] for r in districts),
        },
    }


# ──────────────────────────────────────────────────────────────────────
# Test scenarios: stress different parts of the formula
# ──────────────────────────────────────────────────────────────────────

SCENARIOS = [
    ("defaults", {}),
    ("higher_appropriation", {"appropriation": 4_500_000_000}),
    ("lower_appropriation",  {"appropriation": 3_000_000_000}),
    ("state_share_80pct",    {"state_share_pct": 0.80}),
    ("sped_weight_up",       {"weights": {"SPED": 2.75}}),
    ("poverty_weight_up",    {"weights": {"POVERTY": 0.60}}),
    ("hh_off",               {"apply_hold_harmless": False}),
    ("charter_offset_on",    {"apply_charter_full_state": False}),
]

# Match keys: (Python field, JS field)
ROLLUP_KEY_MAP = [
    ("appropriation",        "appropriation"),
    ("tac_total",            "tac"),
    ("local_share_total",    "localShareTotal"),
    ("statewide_wpu",        "statewideWpu"),
    ("state_share_pct",      "stateShare"),
    ("statewide_per_wpu_state_share", "perWpuStateShare"),
    ("sum_formula_aid",      "sumFormula"),
    ("sum_final_aid",        "sumFinal"),
    ("hold_harmless_inflation", "hhInflation"),
    ("districts_with_floor_kicked_in", "floorCount"),
    ("actual_sac_base_fy_total", "actualBaseFYTotal"),
]

DISTRICT_KEY_MAP = [
    ("total_wpu",        "totalWpu"),
    ("ita",              "ita"),
    ("district_tac",     "districtTac"),
    ("district_local_share", "localShare"),
    ("formula_aid",      "formulaAid"),
    ("final_aid",        "finalAid"),
    ("delta_vs_actual",  "delta"),
]


def scenario_to_js_state(py_overrides: dict, py_defaults) -> dict:
    """Translate Python kwargs into the JS state dict shape."""
    return {
        "appropriation":  py_overrides.get("appropriation", py_defaults.appropriation),
        "stateSharePct":  py_overrides.get("state_share_pct", py_defaults.state_share_pct),
        "weights":        {**py_defaults.weights, **py_overrides.get("weights", {})},
        "applyHH":        py_overrides.get("apply_hold_harmless", py_defaults.apply_hold_harmless),
        "applyCharter":   py_overrides.get("apply_charter_full_state", py_defaults.apply_charter_full_state),
    }


def assert_close(py_val, js_val, tol, label):
    if py_val is None and js_val is None:
        return
    if py_val is None or js_val is None:
        raise AssertionError(f"{label}: one side is None ({py_val=}, {js_val=})")
    py_f = float(py_val)
    js_f = float(js_val)
    if abs(py_f - js_f) > tol:
        raise AssertionError(f"{label}: drift py={py_f:,.4f} js={js_f:,.4f} delta={py_f-js_f:.4f}")


def run_one(name: str, overrides: dict, base_fy: int) -> None:
    py_scenario = whatif_sac.Scenario.from_dict(overrides)
    py_scenario.base_fy = base_fy
    js_state = scenario_to_js_state(overrides, py_scenario)

    py_result = whatif_sac.run_scenario(py_scenario)
    js_inputs = _slim_inputs(base_fy)
    js_result = js_run_scenario_clone(js_inputs, js_state)

    # Rollup parity (loose tolerance because of float vs Decimal arithmetic)
    for py_key, js_key in ROLLUP_KEY_MAP:
        assert_close(
            py_result["rollup"].get(py_key),
            js_result["rollup"].get(js_key),
            tol=1.0,  # within $1 / 1 unit of WPU
            label=f"[{name}] rollup.{py_key}",
        )

    # District parity — index by ID
    py_by_id = {r["district_id"]: r for r in py_result["districts"]}
    js_by_id = {r["id"]: r for r in js_result["districts"]}
    if set(py_by_id) != set(js_by_id):
        only_py = set(py_by_id) - set(js_by_id)
        only_js = set(js_by_id) - set(py_by_id)
        raise AssertionError(f"[{name}] district set drift: only_py={only_py} only_js={only_js}")

    for did, py_row in py_by_id.items():
        js_row = js_by_id[did]
        for py_key, js_key in DISTRICT_KEY_MAP:
            assert_close(
                py_row.get(py_key), js_row.get(js_key),
                tol=1.0,
                label=f"[{name}] {did} {py_row['district_name'][:25]} .{py_key}",
            )
        # floor flag
        if bool(py_row["floor_kicked_in"]) != bool(js_row["floorKicked"]):
            raise AssertionError(
                f"[{name}] {did} floor flag drift py={py_row['floor_kicked_in']} js={js_row['floorKicked']}"
            )

    print(f"  PASS  {name:<24s}  rollup + {len(py_by_id)} districts aligned")


def main() -> int:
    base_fys = sorted({whatif_sac.DEFAULT_BASE_FY})
    # If multiple FYs are loaded, also test against the most recent
    try:
        from app.db import fetchall
        rows = fetchall("SELECT DISTINCT Fiscal_Year FROM lea_wpu_category ORDER BY Fiscal_Year DESC")
        base_fys = sorted({r[0] for r in rows} | set(base_fys), reverse=True)
    except Exception:
        pass

    failures = 0
    for fy in base_fys:
        print(f"\n=== base_fy = {fy} ===")
        for name, overrides in SCENARIOS:
            try:
                run_one(name, overrides, fy)
            except AssertionError as e:
                print(f"  FAIL  {name:<24s}  {e}")
                failures += 1
            except Exception as e:
                print(f"  ERROR {name:<24s}  {type(e).__name__}: {e}")
                failures += 1
    print()
    if failures:
        print(f"FAIL: {failures} parity drift(s) detected — Python and JS engines have diverged.")
        return 1
    print(f"OK: all scenarios aligned across base FYs {base_fys}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
