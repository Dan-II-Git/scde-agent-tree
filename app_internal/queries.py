"""Read helpers for app_internal — Funds-Management budget vs actuals.

Backed by sceis_fmeddw + vw_budget_vs_actuals_by_funds_center, owned by
the internal-budget agent. See .claude/agents/internal-budget.md for
the FM-module semantics this depends on.
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
