"""Read helpers for app_internal — two parallel views of agency money:

- FM Budget vs Actuals (sceis_fmeddw + vw_budget_vs_actuals_by_funds_center).
  Owned by the internal-budget agent. Measures BUDGET AUTHORITY and
  budget consumed via the GM module.

- FI Ledger Expenditures (sceis_detail_transaction filtered to 5xxx GL +
  lookup_gl_account for handbook-category attribution). Measures full
  ledger spend including clearing/accruals/payroll postings the GM
  module excludes. Will NOT reconcile to FM Actuals — see CLAUDE.md
  and the internal-budget agent for why.

The two views share the same Funds Center / Cost Center grouping logic
(BUS shops nested under Transportation, friendly names from
sceis_agency_master).
"""
from __future__ import annotations

from typing import Any

from app_internal.db import fetchall, fetchone


def list_fiscal_years() -> list[int]:
    rows = fetchall("SELECT DISTINCT Fiscal_Year FROM sceis_fmeddw ORDER BY 1")
    return [r[0] for r in rows]


def list_funds_centers(fy: int) -> list[dict[str, Any]]:
    """Funds Centers (leaf level only) with non-trivial activity in this FY,
    ordered by Total_Budget descending."""
    rows = fetchall(
        """
        SELECT Funds_Center, Total_Budget
        FROM vw_budget_vs_actuals_by_funds_center
        WHERE Fiscal_Year = ?
        ORDER BY Total_Budget DESC
        """,
        [fy],
    )
    return [{"funds_center": fc, "total_budget": float(tb or 0)} for fc, tb in rows]


def get_budget_vs_actuals(fy: int) -> list[dict[str, Any]]:
    """All Funds Centers for the FY with budget/actuals/available/pct,
    enriched with the agency-master Name and a derived Department.

    Department rule: cost centers whose code starts with 'H630BU' (i.e.
    H630BU0010 'Transportation' and the H630BUS001..H630BUS049+ bus-shop
    series) all roll up to a 'TRANSPORTATION' department so the bus shops
    sit visually under their parent Transportation cost center. Every
    other cost center has Department = Name (one cost center per dept).
    Rows are returned in the display order: Department, then Funds_Center
    so the Transportation block lands contiguously with H630BU0010 first."""
    rows = fetchall(
        """
        SELECT
            v.Funds_Center,
            COALESCE(am.Name, v.Funds_Center) AS Name,
            CASE
                WHEN v.Funds_Center LIKE 'H630BU%' THEN 'Transportation'
                ELSE COALESCE(am.Name, v.Funds_Center)
            END AS Department,
            v.Total_Budget, v.Estimated_Revenue, v.Actuals,
            v.Available,    v.Pct_Consumed
        FROM vw_budget_vs_actuals_by_funds_center v
        LEFT JOIN sceis_agency_master am ON am.Cost_Center = v.Funds_Center
        WHERE v.Fiscal_Year = ?
        ORDER BY Department, v.Funds_Center
        """,
        [fy],
    )
    out = []
    for fc, name, dept, tb, er, ac, av, pc in rows:
        is_bus_child = fc.startswith("H630BUS")
        out.append({
            "funds_center":     fc,
            "name":             name,
            "department":       dept,
            "is_bus_child":     is_bus_child,
            "total_budget":     float(tb or 0),
            "estimated_revenue": float(er or 0),
            "actuals":          float(ac or 0),
            "available":        float(av or 0),
            "pct_consumed":     float(pc) if pc is not None else None,
        })
    return out


def get_funds_center_summary(funds_center: str, fy: int) -> dict[str, Any] | None:
    row = fetchone(
        """
        SELECT v.Funds_Center, am.Name, v.Total_Budget, v.Estimated_Revenue,
               v.Actuals, v.Available, v.Pct_Consumed
        FROM vw_budget_vs_actuals_by_funds_center v
        LEFT JOIN sceis_agency_master am ON am.Cost_Center = v.Funds_Center
        WHERE v.Funds_Center = ? AND v.Fiscal_Year = ?
        """,
        [funds_center, fy],
    )
    if row is None:
        return None
    fc, name, tb, er, ac, av, pc = row
    return {
        "funds_center": fc,
        "name": name or fc,
        "total_budget": float(tb or 0),
        "estimated_revenue": float(er or 0),
        "actuals": float(ac or 0),
        "available": float(av or 0),
        "pct_consumed": float(pc) if pc is not None else None,
    }


def get_budget_by_commitment_item(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """Where budget was APPROPRIATED in this Funds Center, by Commitment
    Item. Returns one row per CI with non-zero budget, plus the dominant
    Budget_Type as a 'source' hint (e.g. 'TRANSFER OF APPROPRIATIONS').

    Per the internal-budget agent: budget allocations and GM actuals
    sit on different Commitment Items in SAP FM, so this list is NOT
    one-to-one with `get_actuals_by_commitment_item`. They are
    deliberately exposed as separate views — the FC-level totals
    reconcile, but per-item budget vs actuals does not."""
    rows = fetchall(
        """
        WITH agg AS (
          SELECT
            Commitment_Item,
            Budget_Type,
            SUM(Amount) AS amt
          FROM sceis_fmeddw
          WHERE Funds_Center = ? AND Fiscal_Year = ? AND Is_Rollup = FALSE
            AND Budget_Type IN (
              'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
              'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
              'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
              'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
            )
          GROUP BY 1, 2
        ),
        per_ci AS (
          SELECT
            Commitment_Item,
            SUM(amt) AS total_amt,
            ARG_MAX(Budget_Type, ABS(amt)) AS dominant_source
          FROM agg
          GROUP BY 1
          HAVING SUM(amt) != 0
        )
        SELECT Commitment_Item, total_amt, dominant_source
        FROM per_ci
        ORDER BY total_amt DESC
        """,
        [funds_center, fy],
    )
    return [
        {
            "commitment_item": ci,
            "amount": float(amt or 0),
            "dominant_source": src,
        }
        for ci, amt, src in rows
    ]


def get_actuals_by_commitment_item(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """Where money was ACTUALLY SPENT in this Funds Center, by Commitment
    Item. Sums GM Budget Doc Type rows where Process='Receive'; the
    matching Send rows are intentionally ignored."""
    rows = fetchall(
        """
        SELECT
            Commitment_Item,
            SUM(Amount) AS amt
        FROM sceis_fmeddw
        WHERE Funds_Center = ? AND Fiscal_Year = ? AND Is_Rollup = FALSE
          AND Budget_Type = 'GM Budget Doc Type'
          AND Process     = 'Receive'
        GROUP BY 1
        HAVING SUM(Amount) != 0
        ORDER BY amt DESC
        """,
        [funds_center, fy],
    )
    return [{"commitment_item": ci, "amount": float(amt or 0)} for ci, amt in rows]


def get_agency_totals(fy: int) -> dict[str, Any]:
    """Top-line KPI: agency-wide budget/actuals/available/pct for the FY,
    summed across leaf Funds Centers."""
    row = fetchone(
        """
        SELECT
            SUM(Total_Budget)      AS Total_Budget,
            SUM(Estimated_Revenue) AS Estimated_Revenue,
            SUM(Actuals)           AS Actuals,
            SUM(Available)         AS Available
        FROM vw_budget_vs_actuals_by_funds_center
        WHERE Fiscal_Year = ?
        """,
        [fy],
    )
    if row is None:
        return {}
    tb, er, ac, av = (float(x or 0) for x in row)
    return {
        "total_budget": tb,
        "estimated_revenue": er,
        "actuals": ac,
        "available": av,
        "pct_consumed": (ac / tb) if tb > 0 else None,
        "leaf_count": fetchone(
            "SELECT COUNT(*) FROM vw_budget_vs_actuals_by_funds_center WHERE Fiscal_Year = ?",
            [fy],
        )[0],
    }


# ────────────────────────────────────────────────────────────────────
# FI-ledger view: expenditures by Cost Center × handbook category
# ────────────────────────────────────────────────────────────────────

# 5xxx GL accounts are expenditures per the SAP convention. The
# Bridge_Type filter ensures we only attribute to handbook codes for
# rows where lookup_gl_account actually has a mapping; ~99% of FY26
# 5xxx dollars are mapped, the remainder lands in the "(unmapped)"
# bucket of the drill-down. Joining on Bridge_Type IN (...) implicitly
# filters out rows where Handbook_Type would be NULL anyway, so no
# Handbook_Type/Type-equality clause is needed here — but every
# downstream query that joins lookup_gl_account to code_accounting_codes
# DOES need that filter (see schema.json table-level note).


def list_fi_fiscal_years() -> list[int]:
    """FYs with 5xxx ledger spend in sceis_detail_transaction. Currently
    co-extensive with FMEDDW (only FY26 loaded for both), but kept
    separate so that future detail-transaction back-loads of older FYs
    do not silently appear in the FM dropdown."""
    rows = fetchall(
        """
        SELECT DISTINCT Fiscal_Year
        FROM sceis_detail_transaction
        WHERE GL_Account LIKE '5%'
        ORDER BY 1
        """
    )
    return [r[0] for r in rows]


def get_fi_expenditures_by_cost_center(fy: int) -> list[dict[str, Any]]:
    """Top-level FI ledger expenditures (5xxx GL only) per Cost Center,
    enriched with friendly Name from agency master and the same
    Department-grouping rule (BUS shops under Transportation) used by
    the FM-side view."""
    rows = fetchall(
        """
        WITH spend AS (
            SELECT
                Funds_Cost_Center,
                SUM(Debit_Credit_Amount) AS amt,
                COUNT(*)                 AS row_count
            FROM sceis_detail_transaction
            WHERE Fiscal_Year = ? AND GL_Account LIKE '5%'
            GROUP BY 1
        )
        SELECT
            s.Funds_Cost_Center,
            COALESCE(am.Name, s.Funds_Cost_Center) AS Name,
            CASE
                WHEN s.Funds_Cost_Center LIKE 'H630BU%' THEN 'Transportation'
                ELSE COALESCE(am.Name, s.Funds_Cost_Center)
            END AS Department,
            s.amt,
            s.row_count
        FROM spend s
        LEFT JOIN sceis_agency_master am ON am.Cost_Center = s.Funds_Cost_Center
        WHERE s.amt != 0
        ORDER BY Department, s.Funds_Cost_Center
        """,
        [fy],
    )
    out = []
    for fc, name, dept, amt, n in rows:
        out.append({
            "cost_center":  fc,
            "name":         name,
            "department":   dept,
            "is_bus_child": fc.startswith("H630BUS"),
            "amount":       float(amt or 0),
            "row_count":    int(n or 0),
        })
    return out


def get_fi_agency_totals(fy: int) -> dict[str, Any]:
    """Top-line KPIs for the FI ledger expenditure view."""
    row = fetchone(
        """
        SELECT
            SUM(Debit_Credit_Amount)              AS total,
            COUNT(*)                              AS rows,
            COUNT(DISTINCT Funds_Cost_Center)     AS cost_centers
        FROM sceis_detail_transaction
        WHERE Fiscal_Year = ? AND GL_Account LIKE '5%'
        """,
        [fy],
    )
    if row is None:
        return {}
    total, n, cc = row
    coverage = fetchone(
        """
        SELECT
            SUM(CASE WHEN g.Bridge_Type IN ('mechanical','pdf_crosswalk')
                     THEN d.Debit_Credit_Amount ELSE 0 END) AS mapped,
            SUM(CASE WHEN g.Bridge_Type IN ('mechanical','pdf_crosswalk')
                     THEN 0 ELSE d.Debit_Credit_Amount END) AS unmapped
        FROM sceis_detail_transaction d
        LEFT JOIN lookup_gl_account g ON g.GL_Account = d.GL_Account
        WHERE d.Fiscal_Year = ? AND d.GL_Account LIKE '5%'
        """,
        [fy],
    )
    mapped, unmapped = coverage if coverage else (0, 0)
    return {
        "total":           float(total or 0),
        "row_count":       int(n or 0),
        "cost_center_count": int(cc or 0),
        "mapped":          float(mapped or 0),
        "unmapped":        float(unmapped or 0),
        "mapped_pct":      (float(mapped or 0) / float(total)) if total else None,
    }


def get_cost_center_handbook_breakdown(cost_center: str, fy: int) -> dict[str, Any]:
    """Drill-down: per-handbook-category breakdown of FI ledger spend
    within one cost center. Returns the cost-center summary plus the
    per-Handbook-Code rows, with unmapped rows lumped into a single
    "(unmapped)" bucket."""
    summary_row = fetchone(
        """
        SELECT
            d.Funds_Cost_Center,
            COALESCE(am.Name, d.Funds_Cost_Center) AS Name,
            SUM(d.Debit_Credit_Amount)             AS total,
            COUNT(*)                               AS rows
        FROM sceis_detail_transaction d
        LEFT JOIN sceis_agency_master am ON am.Cost_Center = d.Funds_Cost_Center
        WHERE d.Funds_Cost_Center = ? AND d.Fiscal_Year = ? AND d.GL_Account LIKE '5%'
        GROUP BY 1, 2
        """,
        [cost_center, fy],
    )
    if summary_row is None:
        return {"summary": None, "rows": []}
    fc, name, total, n = summary_row
    summary = {
        "cost_center": fc,
        "name":        name or fc,
        "amount":      float(total or 0),
        "row_count":   int(n or 0),
    }

    rows = fetchall(
        """
        SELECT
            COALESCE(g.Handbook_Code, '(unmapped)') AS handbook_code,
            COALESCE(g.Handbook_Name, '(no handbook mapping)') AS handbook_name,
            SUM(d.Debit_Credit_Amount)              AS amt,
            COUNT(*)                                AS rows
        FROM sceis_detail_transaction d
        LEFT JOIN lookup_gl_account g
               ON g.GL_Account = d.GL_Account
              AND g.Bridge_Type IN ('mechanical','pdf_crosswalk')
        WHERE d.Funds_Cost_Center = ? AND d.Fiscal_Year = ? AND d.GL_Account LIKE '5%'
        GROUP BY 1, 2
        ORDER BY amt DESC
        """,
        [cost_center, fy],
    )
    return {
        "summary": summary,
        "rows": [
            {
                "handbook_code": hc,
                "handbook_name": hn,
                "amount":        float(amt or 0),
                "row_count":     int(rc or 0),
            }
            for hc, hn, amt, rc in rows
        ],
    }
