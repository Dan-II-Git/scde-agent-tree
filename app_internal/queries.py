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
    """All Funds Centers for the FY with budget/actuals/available/pct."""
    rows = fetchall(
        """
        SELECT Funds_Center, Total_Budget, Estimated_Revenue, Actuals,
               Available, Pct_Consumed
        FROM vw_budget_vs_actuals_by_funds_center
        WHERE Fiscal_Year = ?
        ORDER BY Total_Budget DESC
        """,
        [fy],
    )
    out = []
    for fc, tb, er, ac, av, pc in rows:
        out.append({
            "funds_center": fc,
            "total_budget": float(tb or 0),
            "estimated_revenue": float(er or 0),
            "actuals": float(ac or 0),
            "available": float(av or 0),
            "pct_consumed": float(pc) if pc is not None else None,
        })
    return out


def get_funds_center_summary(funds_center: str, fy: int) -> dict[str, Any] | None:
    row = fetchone(
        """
        SELECT Funds_Center, Total_Budget, Estimated_Revenue, Actuals,
               Available, Pct_Consumed
        FROM vw_budget_vs_actuals_by_funds_center
        WHERE Funds_Center = ? AND Fiscal_Year = ?
        """,
        [funds_center, fy],
    )
    if row is None:
        return None
    fc, tb, er, ac, av, pc = row
    return {
        "funds_center": fc,
        "total_budget": float(tb or 0),
        "estimated_revenue": float(er or 0),
        "actuals": float(ac or 0),
        "available": float(av or 0),
        "pct_consumed": float(pc) if pc is not None else None,
    }


def get_commitment_item_breakdown(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """Drill-down: per-Commitment-Item budget/actuals/available within one
    Funds Center. Mirrors the view's pivot logic but at finer grain."""
    rows = fetchall(
        """
        SELECT
            Commitment_Item,
            SUM(CASE
                WHEN Budget_Type IN (
                    'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
                    'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
                    'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
                    'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
                ) THEN Amount ELSE 0
            END) AS Total_Budget,
            SUM(CASE WHEN Budget_Type='GM Budget Doc Type' AND Process='Receive'
                     THEN Amount ELSE 0 END) AS Actuals
        FROM sceis_fmeddw
        WHERE Funds_Center = ? AND Fiscal_Year = ? AND Is_Rollup = FALSE
        GROUP BY Commitment_Item
        HAVING Total_Budget != 0 OR Actuals != 0
        ORDER BY Total_Budget DESC
        """,
        [funds_center, fy],
    )
    out = []
    for ci, tb, ac in rows:
        tb_f = float(tb or 0)
        ac_f = float(ac or 0)
        out.append({
            "commitment_item": ci,
            "total_budget": tb_f,
            "actuals": ac_f,
            "available": tb_f - ac_f,
            "pct_consumed": (ac_f / tb_f) if tb_f > 0 else None,
        })
    return out


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
