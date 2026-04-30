"""SAC What-If formula engine — strict statute application.

Implements the State Aid to Classrooms allocation formula from the
2025-26 Funding Manual (pp. 11–13) so a user can dial appropriation
total and category weights and see district-level impacts.

Formula (Funding Manual p.11):
    TAC          = appropriation / state_share_pct          (default state share = 75%)
    LocalShare   = TAC × (1 − state_share_pct)
    DistrictTAC  = TAC × (district_WPU / statewide_WPU)
    DistrictLocal = LocalShare × district_ITA               (0 for charter authorizers)
    DistrictAid  = DistrictTAC − DistrictLocal
    Final        = max(DistrictAid, hold_harmless_floor)    (per p.12 floor clause)

Weights (Funding Manual p.13):
    Base K-12         1.00      Gifted & Talented   +0.15
    SPED (IEP)        2.60      Academic Assistance +0.15
    CTE              1.20       LEP                 +0.20
    RTF               2.10      Poverty             +0.50
    Charter B&M      +1.25 (authorizer-only, additional on top of base/SPED)
    Charter Virtual  +0.50 (authorizer-only)

Hold-harmless floor (FY22-23 actuals across SAC + EIA codes per p.12):
    3103, 3503, 3538, 3550, 3555, 3583
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.db import fetchall

# ──────────────────────────────────────────────────────────────────────
# Statute defaults
# ──────────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS: dict[str, float] = {
    "BASE_K12": 1.00,
    "SPED": 2.60,
    "CTE": 1.20,
    "RTF": 2.10,
    "GIFTED": 0.15,
    "ACAD_ASSIST": 0.15,
    "LEP": 0.20,
    "POVERTY": 0.50,
    "CHARTER_BM": 1.25,
    "CHARTER_VIRT": 0.50,
}

DEFAULT_STATE_SHARE_PCT = 0.75
CHARTER_AUTHORIZER_IDS = {"4701", "4801", "4901"}
HOLD_HARMLESS_BASELINE_FY = 2023
HOLD_HARMLESS_REVENUE_CODES = ["3103", "3503", "3538", "3550", "3555", "3583"]
DEFAULT_BASE_FY = 2024
FY26_APPROPRIATION_DEFAULT = 3_810_127_536.0  # Funding Manual p.10


# ──────────────────────────────────────────────────────────────────────
# Scenario container
# ──────────────────────────────────────────────────────────────────────


@dataclass
class Scenario:
    appropriation: float = FY26_APPROPRIATION_DEFAULT
    state_share_pct: float = DEFAULT_STATE_SHARE_PCT
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    base_fy: int = DEFAULT_BASE_FY
    apply_hold_harmless: bool = True
    apply_charter_full_state: bool = True

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Scenario":
        s = cls()
        if "appropriation" in d and d["appropriation"] is not None:
            s.appropriation = float(d["appropriation"])
        if "state_share_pct" in d and d["state_share_pct"] is not None:
            s.state_share_pct = float(d["state_share_pct"])
        if "base_fy" in d and d["base_fy"] is not None:
            s.base_fy = int(d["base_fy"])
        if "apply_hold_harmless" in d:
            s.apply_hold_harmless = bool(d["apply_hold_harmless"])
        if "apply_charter_full_state" in d:
            s.apply_charter_full_state = bool(d["apply_charter_full_state"])
        if "weights" in d and isinstance(d["weights"], dict):
            for k, v in d["weights"].items():
                if k in s.weights and v is not None:
                    s.weights[k] = float(v)
        return s


# ──────────────────────────────────────────────────────────────────────
# Input fetch — one composite query per FY
# ──────────────────────────────────────────────────────────────────────


def _fetch_inputs(base_fy: int) -> dict[str, dict[str, Any]]:
    """Pull category-level ADM, ITA, charter B&M/Virtual ADM, prior-year
    actuals, and hold-harmless floor for every district. Returns
    {District_ID: {...}} keyed inputs the engine can sum/scale."""
    excl = fetchall(
        "SELECT District_ID FROM lookup_district_exclusions WHERE Exclude_Scope = 'all_reports'"
    )
    excluded = {r[0] for r in excl}

    # 1. Category-level ADM (raw, pre-weight) per district
    cat_rows = fetchall(
        """
        SELECT District_ID, Category, ADM
        FROM lea_wpu_category
        WHERE Fiscal_Year = ? AND Report_Cycle = 135
        """,
        [base_fy],
    )

    # 2. Charter B&M and Virtual ADM (only present for the 3 authorizers, 45-day)
    #    The 135-day file zeros these; pull from lea_wpu_allocations Report_Cycle=45.
    #    Weighted_Pupils there = ADM × statute weight, so back-derive ADM.
    charter_rows = fetchall(
        """
        SELECT District_ID, Category, Weighted_Pupils
        FROM lea_wpu_allocations
        WHERE FY = ? AND Report_Cycle = 45
          AND Category IN ('Charter_BM','Charter_VIRT')
        """,
        [base_fy],
    )

    # 3. ITA (Index Year 2025 is what we have loaded; one row per district)
    ita_rows = fetchall(
        """
        SELECT District_ID, Index_of_Taxpaying_Ability
        FROM lea_ita
        """
    )

    # 4. District names
    name_rows = fetchall("SELECT District_ID, District_Name FROM dim_district")

    # 5. FY23 hold-harmless floor (sum across SAC + EIA codes per Funding Manual p.12)
    placeholders = ",".join("?" * len(HOLD_HARMLESS_REVENUE_CODES))
    floor_rows = fetchall(
        f"""
        SELECT District_ID, SUM(Amount) AS floor_amt
        FROM lea_revenues
        WHERE FY = ? AND Reported_Flag = TRUE
          AND Revenue_Code IN ({placeholders})
        GROUP BY District_ID
        """,
        [HOLD_HARMLESS_BASELINE_FY] + HOLD_HARMLESS_REVENUE_CODES,
    )

    # 6. Actual SAC for the base FY (for delta column) — codes 3103+3503+3541
    actual_rows = fetchall(
        """
        SELECT District_ID, SUM(Amount) AS actual_sac
        FROM lea_revenues
        WHERE FY = ? AND Reported_Flag = TRUE
          AND Revenue_Code IN ('3103','3503','3541')
        GROUP BY District_ID
        """,
        [base_fy],
    )

    # Assemble per-district records
    by_district: dict[str, dict[str, Any]] = {}

    for did, name in name_rows:
        if did in excluded:
            continue
        by_district[did] = {
            "district_id": did,
            "district_name": name,
            "is_charter": did in CHARTER_AUTHORIZER_IDS,
            "ita": 0.0,
            "category_adm": {},
            "hold_harmless_floor": 0.0,
            "actual_sac_base_fy": 0.0,
        }

    for did, cat, adm in cat_rows:
        if did in by_district:
            by_district[did]["category_adm"][cat] = float(adm)

    for did, cat, wpu in charter_rows:
        # Back-derive ADM from Weighted_Pupils using statute weight
        if did not in by_district or float(wpu) == 0:
            continue
        if cat == "Charter_BM":
            by_district[did]["category_adm"]["CHARTER_BM"] = float(wpu) / DEFAULT_WEIGHTS["CHARTER_BM"]
        elif cat == "Charter_VIRT":
            by_district[did]["category_adm"]["CHARTER_VIRT"] = float(wpu) / DEFAULT_WEIGHTS["CHARTER_VIRT"]

    for did, ita in ita_rows:
        if did in by_district:
            by_district[did]["ita"] = float(ita)

    for did, floor_amt in floor_rows:
        if did in by_district and floor_amt is not None:
            by_district[did]["hold_harmless_floor"] = float(floor_amt)

    for did, actual in actual_rows:
        if did in by_district and actual is not None:
            by_district[did]["actual_sac_base_fy"] = float(actual)

    return by_district


# ──────────────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────────────


def run_scenario(scenario: Scenario) -> dict[str, Any]:
    inputs = _fetch_inputs(scenario.base_fy)

    # Step 1: per-district WPU using the user's dialed weights
    rows: list[dict[str, Any]] = []
    for did, rec in inputs.items():
        category_wpu: dict[str, float] = {}
        total_wpu = 0.0
        for cat, adm in rec["category_adm"].items():
            w = scenario.weights.get(cat, 0.0)
            wpu = adm * w
            category_wpu[cat] = wpu
            total_wpu += wpu
        rows.append({
            "district_id": did,
            "district_name": rec["district_name"],
            "is_charter": rec["is_charter"],
            "ita": rec["ita"],
            "total_wpu": total_wpu,
            "category_wpu": category_wpu,
            "hold_harmless_floor": rec["hold_harmless_floor"],
            "actual_sac_base_fy": rec["actual_sac_base_fy"],
        })

    # Step 2: statewide totals
    statewide_wpu = sum(r["total_wpu"] for r in rows)
    if statewide_wpu == 0:
        raise ValueError("Statewide WPU computed as 0 — no inputs available for base_fy")

    state_share = scenario.state_share_pct
    if state_share <= 0 or state_share > 1:
        raise ValueError("state_share_pct must be in (0, 1]")

    tac_total = scenario.appropriation / state_share
    local_share_total = tac_total * (1.0 - state_share)

    # Step 3: per-district allocation
    sum_formula = 0.0
    sum_final = 0.0
    sum_floor_kicked = 0.0
    for r in rows:
        wpu_share = r["total_wpu"] / statewide_wpu
        district_tac = tac_total * wpu_share

        if scenario.apply_charter_full_state and r["is_charter"]:
            district_local = 0.0
        else:
            district_local = local_share_total * r["ita"]

        formula_aid = district_tac - district_local
        if scenario.apply_hold_harmless:
            final_aid = max(formula_aid, r["hold_harmless_floor"])
        else:
            final_aid = formula_aid

        floor_kicked_in = scenario.apply_hold_harmless and r["hold_harmless_floor"] > formula_aid
        delta_vs_actual = final_aid - r["actual_sac_base_fy"]

        r.update({
            "wpu_share_pct": wpu_share,
            "district_tac": district_tac,
            "district_local_share": district_local,
            "formula_aid": formula_aid,
            "final_aid": final_aid,
            "floor_kicked_in": floor_kicked_in,
            "delta_vs_actual": delta_vs_actual,
        })
        sum_formula += formula_aid
        sum_final += final_aid
        if floor_kicked_in:
            sum_floor_kicked += (final_aid - formula_aid)

    rows.sort(key=lambda r: r["final_aid"], reverse=True)

    # Statewide rollup
    rollup = {
        "appropriation": scenario.appropriation,
        "state_share_pct": state_share,
        "tac_total": tac_total,
        "local_share_total": local_share_total,
        "statewide_wpu": statewide_wpu,
        "statewide_per_wpu_state_share": scenario.appropriation / statewide_wpu,
        "statewide_per_wpu_total_program": tac_total / statewide_wpu,
        "sum_formula_aid": sum_formula,
        "sum_final_aid": sum_final,
        "hold_harmless_inflation": sum_final - sum_formula,
        "districts_with_floor_kicked_in": sum(1 for r in rows if r["floor_kicked_in"]),
        "base_fy": scenario.base_fy,
        "actual_sac_base_fy_total": sum(r["actual_sac_base_fy"] for r in rows),
    }

    return {
        "scenario": {
            "appropriation": scenario.appropriation,
            "state_share_pct": scenario.state_share_pct,
            "weights": scenario.weights,
            "base_fy": scenario.base_fy,
            "apply_hold_harmless": scenario.apply_hold_harmless,
            "apply_charter_full_state": scenario.apply_charter_full_state,
        },
        "rollup": rollup,
        "districts": rows,
        "caveats": [
            "Strict-formula application of the FY26 Funding Manual SAC formula (pp. 11–13).",
            "WPU input is 135-day from FY{} (`lea_wpu_category`). Charter B&M/Virtual back-derived from 45-day Charter rows in `lea_wpu_allocations`.".format(scenario.base_fy),
            "ITA from Index Year 2025 (Tax Year 2023). The same ITA is applied to every base FY since older ITA snapshots are not loaded.",
            "RTF is not in the 135-day source file; engine treats RTF ADM as 0 statewide. Real RTF allocations flow through a separate channel (~770 statewide WPU residual).",
            "Hold-harmless floor uses FY23 actuals across codes {} per Funding Manual p.12. Reported_Flag=TRUE filter applied.".format(",".join(HOLD_HARMLESS_REVENUE_CODES)),
            "Special districts/career centers/alternative schools (per p.13: receive prior-FY frozen amount) are not modeled separately — their floor catches them via hold-harmless.",
            "Result is 'pure formula' — proviso overrides and supplemental weights from the appropriation act are NOT modeled.",
        ],
    }
