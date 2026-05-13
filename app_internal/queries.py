"""Read helpers for app_internal — three parallel views of agency money:

- FM Budget vs Actuals by Fund (vw_budget_vs_actuals_by_fund).
  Grain: Fund x FY. Authoritative for budget (BEx Budget v Actual).
  Actuals and encumbrances from BEx FM Expense and BEx Open Encumbrances.
  Covers FY25 and FY26.

- FM Budget vs Actuals by Funds Center (vw_budget_vs_actuals_by_funds_center).
  Grain: Funds Center x FY. Actuals and encumbrances from BEx sources.
  Budget is NULL (tracked at Fund level) except for FY26 FMEDDW entries.
  Covers FY25 and FY26.

- FI Ledger Expenditures (sceis_detail_transaction filtered to 5xxx GL +
  lookup_gl_account for handbook-category attribution). Measures full
  ledger spend including clearing/accruals/payroll postings the FM
  module excludes. Will NOT reconcile to FM Actuals — see CLAUDE.md
  and the internal-budget agent for why.

Data-quality caveats respected in this module:
  #1  FY26 is partial through 2026-05-08. FY_Status and As_Of_Date are
      columns on both views; callers should expose them in the UI.
  #2  bex_fm_expense.FY_Total is negative-for-expense; negation is done
      in the view (Actuals = SUM(-FY_Total)).
  #3  Encumbrance scope is H630 FM-area only.
  #6  11 unmapped CIs — lookup_gl_account may return NULL description;
      callers must handle gracefully.
  #7  Negative Remaining_Balance floored at 0 in the view;
      Over_Invoiced_Amount exposed separately for UI.
"""
from __future__ import annotations

from typing import Any

from app_internal.db import fetchall, fetchone


# ─────────────────────────────────────────────────────────────────────
# FY helpers
# ─────────────────────────────────────────────────────────────────────

def list_fiscal_years() -> list[int]:
    """All FYs with FM budget or actuals data (union of BEx + FMEDDW).
    Returns sorted ascending so the default is the latest year."""
    rows = fetchall(
        """
        SELECT DISTINCT Fiscal_Year FROM bex_fm_expense
        UNION
        SELECT DISTINCT Fiscal_Year FROM sceis_fmeddw
        ORDER BY 1
        """
    )
    return [r[0] for r in rows]


def get_fiscal_year_status(fy: int) -> dict[str, Any]:
    """Return status metadata for a fiscal year.

    Returns {'fy': <int>, 'status': 'Partial'|'Complete', 'as_of_date': <str|None>}.
    'Partial' = the most recent FY loaded in bex_fi_vendor_invoice (still
    accumulating data). 'Complete' = prior years where all postings are final.
    """
    row = fetchone(
        "SELECT FY_Status, As_Of_Date FROM vw_fy_status WHERE Fiscal_Year = ?",
        [fy],
    )
    if row is None:
        # FY not in bex_fi_vendor_invoice — treat as complete (no partial indicator)
        return {"fy": fy, "status": "Complete", "as_of_date": None}
    status, as_of = row
    return {
        "fy": fy,
        "status": status,
        "as_of_date": as_of.isoformat() if as_of else None,
    }


# ─────────────────────────────────────────────────────────────────────
# Fund-grain view (new — authoritative for budget)
# ─────────────────────────────────────────────────────────────────────

def get_budget_vs_actuals_by_fund(fy: int) -> list[dict[str, Any]]:
    """Fund x FY grain. Authoritative for budget/actuals/encumbrances.

    Columns: fund_code, fund_name, current_budget, actuals,
             open_encumbrances, over_invoiced_amount, true_available,
             pct_spent, fy_status, as_of_date.

    Data-quality caveat #8: True_Available = Current_Budget - Actuals
    - Open_Encumbrances (encumbrances already floored at 0 per caveat #7).
    """
    rows = fetchall(
        """
        SELECT
            Fund_Code,
            Fund_Name,
            Fiscal_Year,
            Current_Budget,
            Actuals,
            Open_Encumbrances,
            Over_Invoiced_Amount,
            True_Available,
            Pct_Spent,
            FY_Status,
            As_Of_Date
        FROM vw_budget_vs_actuals_by_fund
        WHERE Fiscal_Year = ?
        ORDER BY Current_Budget DESC NULLS LAST
        """,
        [fy],
    )
    out = []
    for (fund_code, fund_name, fiscal_year, budget, actuals,
         enc, over_inv, true_avail, pct, fy_status, as_of) in rows:
        out.append({
            "fund_code":           fund_code,
            "fund_name":           fund_name or fund_code,
            "fiscal_year":         fiscal_year,
            "current_budget":      float(budget or 0),
            "actuals":             float(actuals or 0),
            "open_encumbrances":   float(enc or 0),
            "over_invoiced_amount": float(over_inv or 0),
            "true_available":      float(true_avail or 0),
            "pct_spent":           float(pct) if pct is not None else None,
            "fy_status":           fy_status,
            "as_of_date":          as_of.isoformat() if as_of else None,
        })
    return out


def get_fund_agency_totals(fy: int) -> dict[str, Any]:
    """Agency-wide KPIs from the Fund-grain view for the given FY."""
    row = fetchone(
        """
        SELECT
            SUM(Current_Budget)      AS budget,
            SUM(Actuals)             AS actuals,
            SUM(Open_Encumbrances)   AS encumbrances,
            SUM(True_Available)      AS true_avail,
            COUNT(*)                 AS fund_count,
            MAX(FY_Status)           AS fy_status,
            MAX(As_Of_Date)          AS as_of_date
        FROM vw_budget_vs_actuals_by_fund
        WHERE Fiscal_Year = ?
        """,
        [fy],
    )
    if row is None:
        return {}
    budget, actuals, enc, true_avail, fund_count, fy_status, as_of = row
    budget = float(budget or 0)
    actuals = float(actuals or 0)
    return {
        "current_budget":    budget,
        "actuals":           actuals,
        "open_encumbrances": float(enc or 0),
        "true_available":    float(true_avail or 0),
        "pct_spent":         (actuals / budget) if budget > 0 else None,
        "fund_count":        int(fund_count or 0),
        "fy_status":         fy_status,
        "as_of_date":        as_of.isoformat() if as_of else None,
    }


# ─────────────────────────────────────────────────────────────────────
# Encumbrances — FC x Detail_Type breakdown
# ─────────────────────────────────────────────────────────────────────

def get_encumbrances_by_funds_center(fy: int) -> list[dict[str, Any]]:
    """H630 open commitments at Funds Center x Detail_Type grain.

    Data-quality caveat #3: scope is H630 FM-area only.
    Data-quality caveat #7: negative Remaining_Balance rows are floored at 0
    in the view aggregate; this query surfaces Over_Invoiced_Amount separately.

    Returns rows sorted by total Open_Encumbrances descending, then by
    Detail_Type so PO / Funds Reservation / Parked FI Document are grouped.
    """
    rows = fetchall(
        """
        SELECT
            Funds_Center,
            Detail_Type,
            COUNT(*)                                    AS line_count,
            SUM(GREATEST(Remaining_Balance, 0))         AS open_amount,
            SUM(CASE WHEN Remaining_Balance < 0
                     THEN Remaining_Balance ELSE 0 END) AS over_invoiced
        FROM bex_open_encumbrances
        WHERE Fiscal_Year = ?
          AND Funds_Center LIKE 'H630%'
        GROUP BY Funds_Center, Detail_Type
        ORDER BY SUM(GREATEST(Remaining_Balance, 0)) DESC, Funds_Center, Detail_Type
        """,
        [fy],
    )
    return [
        {
            "funds_center": fc,
            "detail_type":  dt,
            "line_count":   int(n or 0),
            "open_amount":  float(oa or 0),
            "over_invoiced": float(oi or 0),
        }
        for fc, dt, n, oa, oi in rows
    ]


def get_encumbrance_lines(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """PO/Reservation detail rows for a single Funds Center.

    Returns one row per commitment document line, with negative
    Remaining_Balance preserved (not floored) so the UI can display
    over-invoiced POs explicitly.
    """
    rows = fetchall(
        """
        SELECT
            Detail_Type,
            Reference_Doc_No,
            Document_Date,
            Vendor_Number,
            Vendor_Name,
            Original_Amount,
            Invoiced_Amount,
            Remaining_Balance
        FROM bex_open_encumbrances
        WHERE Funds_Center = ? AND Fiscal_Year = ?
          AND Remaining_Balance != 0
        ORDER BY Remaining_Balance DESC
        """,
        [funds_center, fy],
    )
    return [
        {
            "detail_type":      dt,
            "reference_doc_no": ref,
            "document_date":    doc_date.isoformat() if doc_date else None,
            "vendor_number":    vnum,
            "vendor_name":      vname,
            "original_amount":  float(orig or 0),
            "invoiced_amount":  float(inv or 0),
            "remaining_balance": float(rem or 0),
        }
        for dt, ref, doc_date, vnum, vname, orig, inv, rem in rows
    ]


# ─────────────────────────────────────────────────────────────────────
# FM Expense drill-down — CI / GL / Vendor / Quarter breakdown
# ─────────────────────────────────────────────────────────────────────

def get_expense_detail_by_commitment_item(
    funds_center: str, fy: int
) -> list[dict[str, Any]]:
    """BEx FM Expense drill-down for one Funds Center.

    Returns rows grouped by 10-char Commitment_Item and GL_Account,
    with per-quarter and FY totals. Actuals are negated (positive = spend).

    Data-quality caveat #6: 11 unmapped CIs — Description from
    lookup_gl_account may be NULL; callers must handle gracefully
    (display 'Description unavailable').

    Data-quality caveat #4: CI is at leaf level (10-char). The 6-char
    parent is included as CI_Parent for grouping.
    """
    rows = fetchall(
        """
        SELECT
            e.Commitment_Item,
            SUBSTR(e.Commitment_Item, 1, 6)          AS CI_Parent,
            e.GL_Account,
            COALESCE(g.Handbook_Name, NULL)          AS CI_Description,
            SUM(-e.Qtr_01)                           AS Qtr_01,
            SUM(-e.Qtr_02)                           AS Qtr_02,
            SUM(-e.Qtr_03)                           AS Qtr_03,
            SUM(-e.Qtr_04)                           AS Qtr_04,
            SUM(-e.YE_Adj)                           AS YE_Adj,
            SUM(-e.FY_Total)                         AS FY_Total
        FROM bex_fm_expense e
        LEFT JOIN lookup_gl_account g ON g.GL_Account = e.GL_Account
        WHERE e.Funds_Cost_Center = ? AND e.Fiscal_Year = ?
        GROUP BY e.Commitment_Item, CI_Parent, e.GL_Account, CI_Description
        HAVING SUM(-e.FY_Total) != 0
        ORDER BY SUM(-e.FY_Total) DESC
        """,
        [funds_center, fy],
    )
    return [
        {
            "commitment_item": ci,
            "ci_parent":       ci6,
            "gl_account":      gl,
            "ci_description":  desc,  # may be None — caveat #6
            "qtr_01":          float(q1 or 0),
            "qtr_02":          float(q2 or 0),
            "qtr_03":          float(q3 or 0),
            "qtr_04":          float(q4 or 0),
            "ye_adj":          float(ya or 0),
            "fy_total":        float(fyt or 0),
        }
        for ci, ci6, gl, desc, q1, q2, q3, q4, ya, fyt in rows
    ]


# ─────────────────────────────────────────────────────────────────────
# FI Vendor Invoice drill-down
# ─────────────────────────────────────────────────────────────────────

def get_vendor_invoice_detail(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """BEx FI Vendor Invoice rows for one Funds Center, joined to
    sceis_fi_payments for vendor and district attribution.

    Data-quality caveat #5: FI drill scoped to H630 FM-area only;
    51% of fi_payments doc-numbers are out-of-scope. This join is
    best-effort — unmatched FI docs return NULL District_ID/Vendor_Name.

    Returns rows sorted by Amount_FM descending.
    """
    rows = fetchall(
        """
        SELECT
            v.FI_Doc_Number,
            v.Vendor_Number,
            COALESCE(v.Vendor_Name, p.Vendor_Name) AS Vendor_Name,
            v.Document_Type_Desc,
            v.GL_Account,
            v.GL_Account_Name,
            v.Posting_Date,
            v.Fund,
            v.Amount_FM,
            p.District_ID,
            p.Reference
        FROM bex_fi_vendor_invoice v
        LEFT JOIN sceis_fi_payments p
               ON p.Doc_Number = v.FI_Doc_Number
        WHERE v.Funds_Center = ? AND v.Fiscal_Year = ?
        ORDER BY ABS(v.Amount_FM) DESC
        LIMIT 500
        """,
        [funds_center, fy],
    )
    return [
        {
            "fi_doc_number":    doc,
            "vendor_number":    vnum,
            "vendor_name":      vname,
            "doc_type_desc":    dtype,
            "gl_account":       gl,
            "gl_account_name":  glname,
            "posting_date":     pd.isoformat() if pd else None,
            "fund":             fund,
            "amount_fm":        float(amt or 0),
            "district_id":      did,
            "reference":        ref,
        }
        for doc, vnum, vname, dtype, gl, glname, pd, fund, amt, did, ref in rows
    ]


# ─────────────────────────────────────────────────────────────────────
# Funds Center view (existing — extended for BEx era)
# ─────────────────────────────────────────────────────────────────────

def list_funds_centers(fy: int) -> list[dict[str, Any]]:
    """Funds Centers with actuals activity in this FY, ordered by Actuals desc.
    Now uses BEx-sourced Actuals column (FY25 + FY26)."""
    rows = fetchall(
        """
        SELECT Funds_Center, Actuals
        FROM vw_budget_vs_actuals_by_funds_center
        WHERE Fiscal_Year = ?
        ORDER BY Actuals DESC
        """,
        [fy],
    )
    return [{"funds_center": fc, "total_budget": float(ac or 0)} for fc, ac in rows]


def get_budget_vs_actuals(fy: int) -> list[dict[str, Any]]:
    """All Funds Centers for the FY with actuals/encumbrances/available/pct,
    enriched with the agency-master Name and a derived Department.

    Department rule: cost centers whose code starts with 'H630BU' roll up to
    a 'TRANSPORTATION' department. Every other cost center has
    Department = Name.

    Uses BEx-sourced Actuals (both FY25 and FY26). Budget (Total_Budget) is
    available for FY26 (from FMEDDW) and NULL for FY25. Open_Encumbrances
    and True_Available are from BEx.
    """
    rows = fetchall(
        """
        SELECT
            v.Funds_Center,
            COALESCE(am.Name, v.Funds_Center) AS Name,
            CASE
                WHEN v.Funds_Center LIKE 'H630BU%' THEN 'Transportation'
                ELSE COALESCE(am.Name, v.Funds_Center)
            END AS Department,
            v.Total_Budget,
            v.Estimated_Revenue,
            v.Actuals,
            v.Available,
            v.Pct_Consumed,
            v.Open_Encumbrances,
            v.True_Available,
            v.FY_Status,
            v.As_Of_Date
        FROM vw_budget_vs_actuals_by_funds_center v
        LEFT JOIN sceis_agency_master am ON am.Cost_Center = v.Funds_Center
        WHERE v.Fiscal_Year = ?
        ORDER BY Department, v.Funds_Center
        """,
        [fy],
    )
    out = []
    for (fc, name, dept, tb, er, ac, av, pc,
         enc, true_avail, fy_status, as_of) in rows:
        is_bus_child = fc.startswith("H630BUS")
        out.append({
            "funds_center":       fc,
            "name":               name,
            "department":         dept,
            "is_bus_child":       is_bus_child,
            "total_budget":       float(tb) if tb is not None else None,
            "estimated_revenue":  float(er or 0),
            "actuals":            float(ac or 0),
            "available":          float(av) if av is not None else None,
            "pct_consumed":       float(pc) if pc is not None else None,
            "open_encumbrances":  float(enc or 0),
            "true_available":     float(true_avail) if true_avail is not None else None,
            "fy_status":          fy_status,
            "as_of_date":         as_of.isoformat() if as_of else None,
        })
    return out


def get_funds_center_summary(funds_center: str, fy: int) -> dict[str, Any] | None:
    row = fetchone(
        """
        SELECT v.Funds_Center, am.Name, v.Total_Budget, v.Estimated_Revenue,
               v.Actuals, v.Available, v.Pct_Consumed,
               v.Open_Encumbrances, v.True_Available, v.FY_Status, v.As_Of_Date
        FROM vw_budget_vs_actuals_by_funds_center v
        LEFT JOIN sceis_agency_master am ON am.Cost_Center = v.Funds_Center
        WHERE v.Funds_Center = ? AND v.Fiscal_Year = ?
        """,
        [funds_center, fy],
    )
    if row is None:
        return None
    fc, name, tb, er, ac, av, pc, enc, true_avail, fy_status, as_of = row
    return {
        "funds_center":      fc,
        "name":              name or fc,
        "total_budget":      float(tb) if tb is not None else None,
        "estimated_revenue": float(er or 0),
        "actuals":           float(ac or 0),
        "available":         float(av) if av is not None else None,
        "pct_consumed":      float(pc) if pc is not None else None,
        "open_encumbrances": float(enc or 0),
        "true_available":    float(true_avail) if true_avail is not None else None,
        "fy_status":         fy_status,
        "as_of_date":        as_of.isoformat() if as_of else None,
    }


def get_agency_totals(fy: int) -> dict[str, Any]:
    """Top-line KPI: agency-wide actuals/encumbrances for the FY.

    Budget sums are unreliable at the FC level (NULL for FY25). For
    authoritative budget totals, use get_fund_agency_totals() instead.
    """
    row = fetchone(
        """
        SELECT
            SUM(Total_Budget)        AS Total_Budget,
            SUM(Estimated_Revenue)   AS Estimated_Revenue,
            SUM(Actuals)             AS Actuals,
            SUM(Available)           AS Available,
            SUM(Open_Encumbrances)   AS Open_Encumbrances,
            SUM(True_Available)      AS True_Available,
            MAX(FY_Status)           AS FY_Status,
            MAX(As_Of_Date)          AS As_Of_Date,
            COUNT(*)                 AS leaf_count
        FROM vw_budget_vs_actuals_by_funds_center
        WHERE Fiscal_Year = ?
        """,
        [fy],
    )
    if row is None:
        return {}
    tb, er, ac, av, enc, true_avail, fy_status, as_of, lc = row
    ac = float(ac or 0)
    tb_f = float(tb) if tb is not None else None
    return {
        "total_budget":      tb_f,
        "estimated_revenue": float(er or 0),
        "actuals":           ac,
        "available":         float(av) if av is not None else None,
        "open_encumbrances": float(enc or 0),
        "true_available":    float(true_avail) if true_avail is not None else None,
        "pct_consumed":      (ac / tb_f) if tb_f and tb_f > 0 else None,
        "fy_status":         fy_status,
        "as_of_date":        as_of.isoformat() if as_of else None,
        "leaf_count":        int(lc or 0),
    }


def get_budget_by_commitment_item(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """Where budget was APPROPRIATED in this Funds Center, by Commitment
    Item. Reads from sceis_fmeddw (FY26 only; no FMEDDW data for FY25).

    Per the internal-budget agent: budget allocations and GM actuals
    sit on different Commitment Items in SAP FM, so this list is NOT
    one-to-one with get_actuals_by_commitment_item. They are
    deliberately exposed as separate views."""
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
            "amount":          float(amt or 0),
            "dominant_source": src,
        }
        for ci, amt, src in rows
    ]


def get_actuals_by_commitment_item(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """Where money was ACTUALLY SPENT in this Funds Center, by Commitment
    Item. Reads from sceis_fmeddw GM Budget Doc Type Receive rows (FY26 only).
    For BEx-sourced actuals use get_expense_detail_by_commitment_item()."""
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


# ─────────────────────────────────────────────────────────────────────
# FI-ledger view: expenditures by Cost Center x handbook category
# ─────────────────────────────────────────────────────────────────────

# 5xxx GL accounts are expenditures per the SAP convention. The
# Bridge_Type filter ensures we only attribute to handbook codes for
# rows where lookup_gl_account actually has a mapping; ~99% of FY26
# 5xxx dollars are mapped, the remainder lands in the "(unmapped)"
# bucket of the drill-down.


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
        "total":             float(total or 0),
        "row_count":         int(n or 0),
        "cost_center_count": int(cc or 0),
        "mapped":            float(mapped or 0),
        "unmapped":          float(unmapped or 0),
        "mapped_pct":        (float(mapped or 0) / float(total)) if total else None,
    }


def get_cost_center_handbook_breakdown(cost_center: str, fy: int) -> dict[str, Any]:
    """Drill-down: per-handbook-category breakdown of FI ledger spend
    within one cost center. Returns the cost-center summary plus the
    per-Handbook-Code rows, with unmapped rows lumped into a single
    '(unmapped)' bucket."""
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
