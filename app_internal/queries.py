"""Read helpers for app_internal — three parallel views of agency money:
   Plus the new Office-grain drill-down (get_office_detail, get_office_fc_rows,
   get_fc_primary_funds) that backs /api/report/office.

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


def get_vendor_payments_summary(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """Aggregated FI vendor invoice activity for one Funds Center, FY.

    One row per vendor: invoice count, total paid, top GL account by $.
    Sorted by total paid desc. Joins to sceis_fi_payments only for the
    vendor-name fallback when bex carries a number-only vendor identifier.
    """
    rows = fetchall(
        """
        WITH lines AS (
          SELECT
            COALESCE(v.Vendor_Number, 'UNKNOWN')           AS Vendor_Number,
            COALESCE(v.Vendor_Name, p.Vendor_Name, '(Unattributed)') AS Vendor_Name,
            v.GL_Account,
            v.GL_Account_Name,
            v.Amount_FM,
            v.FI_Doc_Number
          FROM bex_fi_vendor_invoice v
          LEFT JOIN sceis_fi_payments p
                 ON p.Doc_Number = v.FI_Doc_Number
          WHERE v.Funds_Center = ? AND v.Fiscal_Year = ?
        ),
        gl_rank AS (
          SELECT Vendor_Number, GL_Account, GL_Account_Name,
                 SUM(Amount_FM) AS gl_amt,
                 ROW_NUMBER() OVER (PARTITION BY Vendor_Number ORDER BY SUM(Amount_FM) DESC) AS rn
          FROM lines
          GROUP BY 1, 2, 3
        )
        SELECT
          l.Vendor_Number,
          l.Vendor_Name,
          COUNT(DISTINCT l.FI_Doc_Number) AS invoice_count,
          SUM(l.Amount_FM)                AS total_paid,
          MAX(CASE WHEN g.rn = 1 THEN g.GL_Account     END) AS top_gl,
          MAX(CASE WHEN g.rn = 1 THEN g.GL_Account_Name END) AS top_gl_name
        FROM lines l
        LEFT JOIN gl_rank g
               ON g.Vendor_Number = l.Vendor_Number AND g.rn = 1
        GROUP BY 1, 2
        ORDER BY total_paid DESC
        """,
        [funds_center, fy],
    )
    return [
        {
            "vendor_number": vnum,
            "vendor_name":   vname,
            "invoice_count": int(cnt or 0),
            "total_paid":    float(amt or 0),
            "top_gl":        gl,
            "top_gl_name":   glname,
        }
        for vnum, vname, cnt, amt, gl, glname in rows
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
    enriched with org-chart grouping from dim_cost_center_office.

    Returns one dict per Funds Center with the following org-chart fields:
      - division   : top-level division (e.g. "College, Career, & Military Readiness")
      - sub_division: only populated for CCMR rows ("Teaching & Learning" /
                      "Talent & Continuous Improvement"); NULL elsewhere
      - office     : leaf office (e.g. "Career Readiness", "Transportation")
      - sub_category: "Depot" / "Bus Shop" for H630JG* / H630BU* rows; NULL elsewhere
      - department : alias for office — kept for any callers that still reference it

    Rows are ordered Division → Office → Funds_Center for the three-level
    hierarchy rendered by render_budget_vs_actuals.

    Uses BEx-sourced Actuals (both FY25 and FY26). Budget (Total_Budget) is
    available for FY26 (from FMEDDW) and NULL for FY25. Open_Encumbrances
    and True_Available are from BEx.
    """
    rows = fetchall(
        """
        SELECT
            v.Funds_Center,
            COALESCE(d.Cost_Center_Name, am.Name, v.Funds_Center) AS Name,
            COALESCE(d.Division, 'Unknown')                        AS Division,
            d.Sub_Division,
            COALESCE(d.Office, 'Unknown')                          AS Office,
            d.Sub_Category,
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
        LEFT JOIN dim_cost_center_office d  ON d.Cost_Center  = v.Funds_Center
        LEFT JOIN sceis_agency_master    am ON am.Cost_Center = v.Funds_Center
        WHERE v.Fiscal_Year = ?
        ORDER BY Division, Office, v.Funds_Center
        """,
        [fy],
    )
    out = []
    for (fc, name, division, sub_division, office, sub_category,
         tb, er, ac, av, pc, enc, true_avail, fy_status, as_of) in rows:
        out.append({
            "funds_center":       fc,
            "name":               name,
            "division":           division,
            "sub_division":       sub_division,
            "office":             office,
            "sub_category":       sub_category,
            "department":         office,   # legacy alias
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


def get_fc_fa_breakdown(fy: int) -> dict[str, list[dict[str, Any]]]:
    """Return Funds_Center -> list of Functional_Area dicts for FY.

    One pass over sceis_detail_transaction (the only source with both
    Funds_Cost_Center AND Functional_Area), joined to dim_functional_area
    for Category + Name. Used by render_budget_vs_actuals to inject FA
    sub-rows under each FC row.

    Caveat: FI ledger 5xxx GL is the source. These rows will NOT sum to
    the FC parent row's BEx FM Actuals due to clearing/accrual postings
    FI includes that FM excludes.
    """
    rows = fetchall(
        """
        SELECT
          d.Funds_Cost_Center                     AS Funds_Center,
          d.Functional_Area,
          COALESCE(f.Name, d.Functional_Area)     AS Name,
          COALESCE(f.Category, 'Unknown')         AS Category,
          SUM(d.Debit_Credit_Amount)              AS Actuals
        FROM sceis_detail_transaction d
        LEFT JOIN dim_functional_area f ON f.Functional_Area = d.Functional_Area
        WHERE d.Fiscal_Year = ? AND d.GL_Account LIKE '5%'
        GROUP BY 1, 2, 3, 4
        HAVING SUM(d.Debit_Credit_Amount) != 0
        ORDER BY 1, 5 DESC
        """,
        [fy],
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for fc, fa, name, cat, amt in rows:
        out.setdefault(fc, []).append({
            "functional_area": fa,
            "name":            name,
            "category":        cat,
            "actuals":         float(amt or 0),
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
# Functional Area grouping (parallel to Funds Center)
# ─────────────────────────────────────────────────────────────────────
# IMPORTANT: actuals here are sourced from sceis_detail_transaction (FI
# ledger, 5xxx GL), NOT bex_fm_expense — only the FI ledger carries
# Functional_Area on every row. Consequence: these actuals will NOT
# reconcile to the Funds Center view's FM Actuals (BEx FM Expense),
# because FI includes clearing/accrual/payroll postings that FM excludes,
# and FM negates the sign whereas FI is signed natively. The caveat note
# in render_budget_vs_actuals_by_fa explains this to the user.
#
# Budget is from sceis_fmeddw (FY26 only) — same source as the FC view.
# Open Encumbrances are NOT shown: bex_open_encumbrances has no
# Functional_Area column. Users who need commitments must pivot back
# to the Funds Center grouping.

def get_budget_vs_actuals_by_functional_area(fy: int) -> list[dict[str, Any]]:
    """Functional Area twin of get_budget_vs_actuals.

    Aggregates FI ledger 5xxx actuals and FMEDDW budget by Functional_Area,
    enriched with Category + Name + Confidence from dim_functional_area.
    Returns rows ordered Category -> Actuals desc so the rendered table
    groups by Category naturally.
    """
    rows = fetchall(
        """
        WITH fi_actuals AS (
          SELECT Functional_Area, SUM(Debit_Credit_Amount) AS Actuals
          FROM sceis_detail_transaction
          WHERE Fiscal_Year = ? AND GL_Account LIKE '5%'
          GROUP BY 1
        ),
        fmeddw_budget AS (
          SELECT
            Functional_Area,
            SUM(CASE WHEN Budget_Type IN (
                'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
                'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
                'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
                'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
              ) THEN Amount ELSE 0 END) AS Total_Budget
          FROM sceis_fmeddw
          WHERE Fiscal_Year = ? AND Is_Rollup = FALSE
          GROUP BY 1
        ),
        all_fa AS (
          SELECT Functional_Area FROM fi_actuals
          UNION
          SELECT Functional_Area FROM fmeddw_budget
        )
        SELECT
          f.Functional_Area,
          COALESCE(d.Name, f.Functional_Area)        AS Name,
          COALESCE(d.Category, 'Unknown')            AS Category,
          d.Confidence,
          d.Note,
          fb.Total_Budget,
          COALESCE(ba.Actuals, 0)                    AS Actuals,
          CASE WHEN fb.Total_Budget IS NOT NULL
               THEN fb.Total_Budget - COALESCE(ba.Actuals, 0)
               ELSE NULL END                         AS Available,
          CASE WHEN fb.Total_Budget > 0
               THEN COALESCE(ba.Actuals, 0) / fb.Total_Budget
               ELSE NULL END                         AS Pct_Consumed
        FROM all_fa f
        LEFT JOIN fi_actuals      ba ON ba.Functional_Area = f.Functional_Area
        LEFT JOIN fmeddw_budget   fb ON fb.Functional_Area = f.Functional_Area
        LEFT JOIN dim_functional_area d ON d.Functional_Area = f.Functional_Area
        WHERE COALESCE(ba.Actuals, 0) != 0 OR fb.Total_Budget IS NOT NULL
        ORDER BY Category, Actuals DESC NULLS LAST
        """,
        [fy, fy],
    )
    out = []
    for fa, name, cat, conf, note, tb, ac, av, pc in rows:
        out.append({
            "functional_area": fa,
            "name":            name,
            "category":        cat,
            "confidence":      conf,
            "note":            note,
            "total_budget":    float(tb) if tb is not None else None,
            "actuals":         float(ac or 0),
            "available":       float(av) if av is not None else None,
            "pct_consumed":    float(pc) if pc is not None else None,
        })
    return out


def get_fa_agency_totals(fy: int) -> dict[str, Any]:
    """Top-line KPIs for the FA grouping. Actuals from FI ledger 5xxx."""
    row = fetchone(
        """
        WITH agg AS (
          SELECT
            SUM(CASE WHEN Budget_Type IN (
                'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
                'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
                'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
                'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
              ) THEN Amount ELSE 0 END) AS Total_Budget
          FROM sceis_fmeddw
          WHERE Fiscal_Year = ? AND Is_Rollup = FALSE
        ),
        ba AS (
          SELECT SUM(Debit_Credit_Amount) AS Actuals,
                 COUNT(DISTINCT Functional_Area) AS fa_count
          FROM sceis_detail_transaction
          WHERE Fiscal_Year = ? AND GL_Account LIKE '5%'
        )
        SELECT agg.Total_Budget, ba.Actuals, ba.fa_count FROM agg, ba
        """,
        [fy, fy],
    )
    if row is None:
        return {}
    tb, ac, fa_count = row
    ac = float(ac or 0)
    tb_f = float(tb) if tb is not None else None
    return {
        "total_budget":  tb_f,
        "actuals":       ac,
        "available":     (tb_f - ac) if tb_f is not None else None,
        "pct_consumed":  (ac / tb_f) if tb_f and tb_f > 0 else None,
        "fa_count":      int(fa_count or 0),
    }


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
    enriched with org-chart grouping from dim_cost_center_office.

    Returns one dict per Cost Center with the same org-chart fields as
    get_budget_vs_actuals (division, sub_division, office, sub_category,
    department) so the FI Ledger view uses the same grouping logic.
    """
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
            COALESCE(d.Cost_Center_Name, am.Name, s.Funds_Cost_Center) AS Name,
            COALESCE(d.Division, 'Unknown')                             AS Division,
            d.Sub_Division,
            COALESCE(d.Office, 'Unknown')                               AS Office,
            d.Sub_Category,
            s.amt,
            s.row_count
        FROM spend s
        LEFT JOIN dim_cost_center_office d  ON d.Cost_Center  = s.Funds_Cost_Center
        LEFT JOIN sceis_agency_master    am ON am.Cost_Center = s.Funds_Cost_Center
        WHERE s.amt != 0
        ORDER BY Division, Office, s.Funds_Cost_Center
        """,
        [fy],
    )
    out = []
    for fc, name, division, sub_division, office, sub_category, amt, n in rows:
        out.append({
            "cost_center":  fc,
            "name":         name,
            "division":     division,
            "sub_division": sub_division,
            "office":       office,
            "sub_category": sub_category,
            "department":   office,   # legacy alias
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


# ─────────────────────────────────────────────────────────────────────
# Office-grain drill-down (new — backs /api/report/office)
# ─────────────────────────────────────────────────────────────────────

def get_office_fc_rows(division: str, office: str, fy: int) -> list[dict[str, Any]]:
    """All Funds Centers in a given Division/Office for the given FY.

    Returns one dict per Funds Center, same field set as get_budget_vs_actuals
    rows but scoped to a single office.  Ordered by Funds_Center for stability.
    """
    rows = fetchall(
        """
        SELECT
            v.Funds_Center,
            COALESCE(d.Cost_Center_Name, am.Name, v.Funds_Center) AS Name,
            COALESCE(d.Division, 'Unknown')                        AS Division,
            COALESCE(d.Office, 'Unknown')                          AS Office,
            d.Sub_Division,
            d.Sub_Category,
            v.Total_Budget,
            v.Actuals,
            v.Open_Encumbrances,
            v.True_Available,
            v.Pct_Consumed,
            v.FY_Status,
            v.As_Of_Date
        FROM vw_budget_vs_actuals_by_funds_center v
        LEFT JOIN dim_cost_center_office d  ON d.Cost_Center  = v.Funds_Center
        LEFT JOIN sceis_agency_master    am ON am.Cost_Center = v.Funds_Center
        WHERE v.Fiscal_Year = ?
          AND COALESCE(d.Division, 'Unknown') = ?
          AND COALESCE(d.Office,   'Unknown') = ?
        ORDER BY v.Funds_Center
        """,
        [fy, division, office],
    )
    out = []
    for (fc, name, div, off, sub_div, sub_cat,
         tb, ac, enc, true_avail, pc, fy_status, as_of) in rows:
        out.append({
            "funds_center":      fc,
            "name":              name,
            "division":          div,
            "office":            off,
            "sub_division":      sub_div,
            "sub_category":      sub_cat,
            "total_budget":      float(tb) if tb is not None else None,
            "actuals":           float(ac or 0),
            "open_encumbrances": float(enc or 0),
            "true_available":    float(true_avail) if true_avail is not None else None,
            "pct_consumed":      float(pc) if pc is not None else None,
            "fy_status":         fy_status,
            "as_of_date":        as_of.isoformat() if as_of else None,
        })
    return out


def get_office_totals(division: str, office: str, fy: int) -> dict[str, Any]:
    """Aggregate KPIs for one Office in a given Division for the given FY."""
    row = fetchone(
        """
        SELECT
            SUM(v.Total_Budget)        AS Total_Budget,
            SUM(v.Actuals)             AS Actuals,
            SUM(v.Open_Encumbrances)   AS Open_Encumbrances,
            SUM(v.True_Available)      AS True_Available,
            COUNT(*)                   AS fc_count,
            MAX(v.FY_Status)           AS FY_Status,
            MAX(v.As_Of_Date)          AS As_Of_Date
        FROM vw_budget_vs_actuals_by_funds_center v
        LEFT JOIN dim_cost_center_office d ON d.Cost_Center = v.Funds_Center
        WHERE v.Fiscal_Year = ?
          AND COALESCE(d.Division, 'Unknown') = ?
          AND COALESCE(d.Office,   'Unknown') = ?
        """,
        [fy, division, office],
    )
    if row is None:
        return {}
    tb, ac, enc, true_avail, fc_count, fy_status, as_of = row
    ac_f  = float(ac or 0)
    tb_f  = float(tb) if tb is not None else None
    return {
        "total_budget":      tb_f,
        "actuals":           ac_f,
        "open_encumbrances": float(enc or 0),
        "true_available":    float(true_avail) if true_avail is not None else None,
        "pct_consumed":      (ac_f / tb_f) if tb_f and tb_f > 0 else None,
        "fc_count":          int(fc_count or 0),
        "fy_status":         fy_status,
        "as_of_date":        as_of.isoformat() if as_of else None,
    }


def get_fc_primary_funds(funds_center: str, fy: int, top_n: int = 3) -> list[dict[str, Any]]:
    """Return the top N funds by actuals for a given Funds Center / FY.

    Used to populate the ⓘ tooltip fund-restriction text for each FC row.
    Reads from bex_fm_expense (column Funds_Cost_Center).
    """
    rows = fetchall(
        """
        SELECT
            Fund,
            SUM(-FY_Total) AS actuals
        FROM bex_fm_expense
        WHERE Funds_Cost_Center = ? AND Fiscal_Year = ?
        GROUP BY Fund
        HAVING SUM(-FY_Total) > 0
        ORDER BY actuals DESC
        LIMIT ?
        """,
        [funds_center, fy, top_n],
    )
    return [
        {"fund_code": fund, "actuals": float(act or 0)}
        for fund, act in rows
    ]


def get_encumbrance_lines(funds_center: str, fy: int) -> list[dict[str, Any]]:
    """PO/Reservation detail rows for a single Funds Center.

    Returns one row per commitment document line, with negative
    Remaining_Balance preserved (not floored) so the UI can display
    over-invoiced POs explicitly.  Includes consumed_pct for the
    side-panel commitments view.
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
    out = []
    for dt, ref, doc_date, vnum, vname, orig, inv, rem in rows:
        orig_f = float(orig or 0)
        inv_f  = float(inv or 0)
        consumed_pct = abs(inv_f) / orig_f if orig_f != 0 else None
        out.append({
            "detail_type":      dt,
            "reference_doc_no": ref,
            "document_date":    doc_date.isoformat() if doc_date else None,
            "vendor_number":    vnum,
            "vendor_name":      vname,
            "original_amount":  orig_f,
            "invoiced_amount":  inv_f,
            "remaining_balance": float(rem or 0),
            "consumed_pct":     consumed_pct,
        })
    return out


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


# ─────────────────────────────────────────────────────────────────────
# Rollup view — Org > Fund > FA > CI (backs /api/report/rollup)
# ─────────────────────────────────────────────────────────────────────
# Returns leaf rows at the (Division, Office, Funds_Center, Fund, FA, CI)
# grain so the frontend can build either the tree or the pivot layout
# from a single payload.
#
# ── Actuals (FY26) ──
# FM-authoritative actuals come from bex_fm_expense (SUM(-FY_Total)) at
# FC x Fund x CI grain — these reconcile to vw_budget_vs_actuals_by_fund.
# bex_fm_expense has no Functional_Area, so to fill the FA leaf level
# we apportion each cell's actuals across FA in proportion to
# bex_fi_vendor_invoice's share of FI activity for the same FC x Fund x CI.
# Cells with no FI Vendor Invoice counterpart (mostly payroll-routed
# 5010xx / 5130xx, ~3.4% of FY26 FM dollars) land in an "(unallocated FA)"
# bucket; the agency total still reconciles to the authoritative $6.02B.
#
# NOTE: FMEDDW GM Budget Doc Type rows look superficially like actuals
# but are a budget-transfer mechanism (Receive + Send net to zero on
# every cell). They are NOT spend and are not used here.
#
# ── Budget (FY26) ──
# From sceis_fmeddw at FC x Fund x FA x CI grain (the only source with
# all four dimensions).
#
# ── FY25 ──
# Same bex_fm_expense source for actuals at FC x Fund x CI; FA is not
# available before FY26 (bex_fi_vendor_invoice has FA for both years
# but FMEDDW has none for FY25, and the FA share bridge requires both).
# Leaf rows return Functional_Area = NULL and the endpoint flags
# fa_supported = false. Budget at the FC grain is absent in FY25 (lives
# only at Fund x CI on bex_budget_vs_actuals) so leaf budgets are NULL
# and the agency-wide budget total comes from vw_budget_vs_actuals_by_fund.
#
# ── Encumbrances ──
# Intentionally NOT attached to leaf rows: bex_open_encumbrances has no
# Functional_Area, and attaching at FC x Fund x CI would double-count
# across FA. The endpoint returns agency-wide encumbrance totals
# separately so the dashboard surfaces them as a top-line KPI.

def _ci_name_lookup(fy: int) -> dict[str, str]:
    """Best-effort Commitment_Item -> readable name map.

    FMEDDW uses 6-char CIs (e.g. '501058') while bex_fm_expense and
    lookup_gl_account use 10-char (e.g. '5010580000'). We build the
    name map at both grains so callers can lookup either form.
    Picks the highest-|$| GL per CI to break ties. Returns {} on any
    failure so callers can degrade gracefully (caveat #6).
    """
    rows = fetchall(
        """
        WITH gl_per_ci AS (
          SELECT
            e.Commitment_Item,
            g.Handbook_Name                          AS Name,
            SUM(ABS(e.FY_Total))                     AS w
          FROM bex_fm_expense e
          LEFT JOIN lookup_gl_account g ON g.GL_Account = e.GL_Account
          WHERE e.Fiscal_Year = ?
          GROUP BY e.Commitment_Item, g.Handbook_Name
        ),
        ranked AS (
          SELECT
            Commitment_Item,
            Name,
            ROW_NUMBER() OVER (PARTITION BY Commitment_Item ORDER BY w DESC) AS rn
          FROM gl_per_ci
          WHERE Name IS NOT NULL
        ),
        ci10 AS (
          SELECT Commitment_Item, Name FROM ranked WHERE rn = 1
        ),
        ci6 AS (
          SELECT SUBSTR(Commitment_Item, 1, 6) AS Commitment_Item,
                 ANY_VALUE(Name)               AS Name
          FROM ci10
          GROUP BY 1
        )
        SELECT Commitment_Item, Name FROM ci10
        UNION ALL
        SELECT Commitment_Item, Name FROM ci6
        """,
        [fy],
    )
    return {ci: name for ci, name in rows if ci and name}


def get_rollup_rows(fy: int) -> dict[str, Any]:
    """Org > Fund > FA > CI rollup payload for one fiscal year.

    Returns a dict:
      {
        "fy":            int,
        "fy_status":     "Partial" | "Complete",
        "as_of_date":    str | None,
        "fa_supported":  bool,            # False for FY < 2026
        "fc_budget":     bool,            # Budget broken to FC grain (False for FY25)
        "rows":          [ leaf dicts ],
        "totals":        { current_budget, actuals, open_encumbrances,
                           true_available, pct_spent },
        "caveats":       [ str ],
      }

    Each leaf row dict has:
      division, sub_division, office, sub_category,
      funds_center, fc_name,
      fund_code, fund_name,
      functional_area, fa_name, fa_category,          # None for FY25
      commitment_item, ci_name,
      current_budget, actuals
    """
    fa_supported = fy >= 2026
    fc_budget    = fy >= 2026

    # CI name lookup (best effort)
    ci_names = _ci_name_lookup(fy)

    # Fund-code -> readable Fund_Name from BEx if available, else code
    fund_rows = fetchall(
        """
        SELECT DISTINCT Fund_Code, Fund_Name
        FROM bex_budget_vs_actuals
        WHERE Fiscal_Year = ? AND Fund_Name IS NOT NULL
        """,
        [fy],
    )
    fund_names = {fc: fn for fc, fn in fund_rows}

    if fa_supported:
        # FY26+ — actuals from bex_fm_expense (FM-authoritative) apportioned
        # across FA via bex_fi_vendor_invoice shares within each
        # (FC, Fund, CI) cell. Budget from FMEDDW at the FA grain.
        #
        # NOTE on grain mismatch: FMEDDW CI is 6-char ('501058') while
        # bex_fm_expense and bex_fi_vendor_invoice CI/GL are 10-char
        # ('5010580000'). We bridge by stripping FMEDDW's budget CI to
        # 10-char by appending '0000' (the leaf form) — works because every
        # FMEDDW 6-char CI rolls up at least one 10-char leaf in the FM/FI
        # tables. Cells where the bridge produces no FM-actuals match
        # surface with Actuals = 0; cells with FM actuals but no budget
        # entry surface with Current_Budget = NULL.
        rows = fetchall(
            """
            WITH
            -- 1. FM-authoritative actuals at FC x Fund x CI(10) grain
            fm_actuals AS (
              SELECT
                Funds_Cost_Center AS Funds_Center,
                Fund,
                Commitment_Item   AS CI10,
                SUM(-FY_Total)    AS Actuals
              FROM bex_fm_expense
              WHERE Fiscal_Year = ?
              GROUP BY 1,2,3
              HAVING SUM(-FY_Total) <> 0
            ),
            -- 2. FI Vendor Invoice shares — provides the FA breakdown
            vi_shares AS (
              SELECT
                Funds_Center,
                Fund,
                GL_Account        AS CI10,
                Functional_Area,
                SUM(ABS(Amount_FM)) AS Weight
              FROM bex_fi_vendor_invoice
              WHERE Fiscal_Year = ?
              GROUP BY 1,2,3,4
              HAVING SUM(ABS(Amount_FM)) > 0
            ),
            vi_totals AS (
              SELECT Funds_Center, Fund, CI10, SUM(Weight) AS Total_Weight
              FROM vi_shares
              GROUP BY 1,2,3
            ),
            -- 3. Apportion FM actuals across FA using VI shares; cells with no
            --    VI counterpart get a single "(unallocated FA)" row.
            apportioned AS (
              SELECT
                fm.Funds_Center, fm.Fund, fm.CI10,
                vs.Functional_Area,
                fm.Actuals * (vs.Weight / vt.Total_Weight) AS Actuals
              FROM fm_actuals fm
              JOIN vi_totals vt USING (Funds_Center, Fund, CI10)
              JOIN vi_shares vs USING (Funds_Center, Fund, CI10)
              UNION ALL
              SELECT
                fm.Funds_Center, fm.Fund, fm.CI10,
                CAST(NULL AS VARCHAR) AS Functional_Area,
                fm.Actuals
              FROM fm_actuals fm
              LEFT JOIN vi_totals vt USING (Funds_Center, Fund, CI10)
              WHERE vt.Total_Weight IS NULL
            ),
            -- 4. Budget from FMEDDW at FC x Fund x FA x CI grain. Bridge the
            --    6-char FMEDDW CI to 10-char by appending '0000'.
            fmeddw_budget AS (
              SELECT
                Funds_Center,
                Fund,
                Functional_Area,
                Commitment_Item || '0000' AS CI10,
                SUM(CASE WHEN Budget_Type IN (
                  'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
                  'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
                  'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
                  'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
                ) THEN Amount ELSE 0 END) AS Current_Budget
              FROM sceis_fmeddw
              WHERE Fiscal_Year = ? AND Is_Rollup = FALSE
              GROUP BY 1,2,3,4
              HAVING SUM(CASE WHEN Budget_Type IN (
                  'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
                  'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
                  'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
                  'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
                ) THEN Amount ELSE 0 END) <> 0
            ),
            -- 5. Full-outer join budget to apportioned actuals at FA leaf grain.
            joined AS (
              SELECT
                COALESCE(b.Funds_Center,    a.Funds_Center)    AS Funds_Center,
                COALESCE(b.Fund,            a.Fund)            AS Fund,
                COALESCE(b.Functional_Area, a.Functional_Area) AS Functional_Area,
                COALESCE(b.CI10,            a.CI10)            AS CI10,
                b.Current_Budget,
                SUM(a.Actuals)                                  AS Actuals
              FROM fmeddw_budget b
              FULL OUTER JOIN apportioned a
                ON  a.Funds_Center      = b.Funds_Center
                AND a.Fund              = b.Fund
                AND a.CI10              = b.CI10
                AND COALESCE(a.Functional_Area,'__NULL__')
                  = COALESCE(b.Functional_Area,'__NULL__')
              GROUP BY 1,2,3,4, b.Current_Budget
            )
            SELECT
              COALESCE(d.Division, 'Unknown')                   AS Division,
              d.Sub_Division,
              COALESCE(d.Office,   'Unknown')                   AS Office,
              d.Sub_Category,
              j.Funds_Center,
              COALESCE(d.Cost_Center_Name, am.Name, j.Funds_Center) AS FC_Name,
              j.Fund                                            AS Fund_Code,
              j.Functional_Area,
              COALESCE(fa.Name,     j.Functional_Area, '(unallocated FA)') AS FA_Name,
              COALESCE(fa.Category, 'Unknown')                  AS FA_Category,
              j.CI10                                            AS Commitment_Item,
              j.Current_Budget,
              j.Actuals
            FROM joined j
            LEFT JOIN dim_cost_center_office d  ON d.Cost_Center      = j.Funds_Center
            LEFT JOIN sceis_agency_master    am ON am.Cost_Center     = j.Funds_Center
            LEFT JOIN dim_functional_area    fa ON fa.Functional_Area = j.Functional_Area
            WHERE COALESCE(j.Current_Budget, 0) <> 0 OR COALESCE(j.Actuals, 0) <> 0
            ORDER BY Division, Office, j.Funds_Center, j.Fund, j.Functional_Area,
                     j.CI10
            """,
            [fy, fy, fy],
        )
    else:
        # FY25 — actuals only at FC x Fund x CI, no FA
        rows = fetchall(
            """
            WITH spend AS (
              SELECT
                e.Funds_Cost_Center  AS Funds_Center,
                e.Fund               AS Fund_Code,
                e.Commitment_Item,
                SUM(-e.FY_Total)     AS Actuals
              FROM bex_fm_expense e
              WHERE e.Fiscal_Year = ?
              GROUP BY 1,2,3
              HAVING SUM(-e.FY_Total) != 0
            )
            SELECT
              COALESCE(d.Division,    'Unknown')                AS Division,
              d.Sub_Division,
              COALESCE(d.Office,      'Unknown')                AS Office,
              d.Sub_Category,
              s.Funds_Center,
              COALESCE(d.Cost_Center_Name, am.Name, s.Funds_Center) AS FC_Name,
              s.Fund_Code,
              CAST(NULL AS VARCHAR)                             AS Functional_Area,
              CAST(NULL AS VARCHAR)                             AS FA_Name,
              CAST(NULL AS VARCHAR)                             AS FA_Category,
              s.Commitment_Item,
              CAST(NULL AS DOUBLE)                              AS Current_Budget,
              s.Actuals
            FROM spend s
            LEFT JOIN dim_cost_center_office d  ON d.Cost_Center  = s.Funds_Center
            LEFT JOIN sceis_agency_master    am ON am.Cost_Center = s.Funds_Center
            ORDER BY Division, Office, s.Funds_Center, s.Fund_Code, s.Commitment_Item
            """,
            [fy],
        )

    leaf: list[dict[str, Any]] = []
    for (division, sub_division, office, sub_category, fc, fc_name,
         fund_code, fa, fa_name, fa_cat, ci, budget, actuals) in rows:
        leaf.append({
            "division":         division,
            "sub_division":     sub_division,
            "office":           office,
            "sub_category":     sub_category,
            "funds_center":     fc,
            "fc_name":          fc_name,
            "fund_code":        fund_code,
            "fund_name":        fund_names.get(fund_code, fund_code),
            "functional_area":  fa,
            "fa_name":          fa_name,
            "fa_category":      fa_cat,
            "commitment_item":  ci,
            "ci_name":          ci_names.get(ci),
            "current_budget":   float(budget) if budget is not None else None,
            "actuals":          float(actuals or 0),
        })

    # Agency-level totals — pull from authoritative views, not leaf sums,
    # so encumbrances and FY25 budget are accurate.
    fund_totals = fetchone(
        """
        SELECT
            SUM(Current_Budget)      AS budget,
            SUM(Actuals)             AS actuals,
            SUM(Open_Encumbrances)   AS enc,
            SUM(True_Available)      AS true_avail
        FROM vw_budget_vs_actuals_by_fund
        WHERE Fiscal_Year = ?
        """,
        [fy],
    )
    if fund_totals:
        tb, ta, te, tav = fund_totals
        budget_f  = float(tb)  if tb  is not None else None
        actuals_f = float(ta or 0)
        totals = {
            "current_budget":    budget_f,
            "actuals":           actuals_f,
            "open_encumbrances": float(te or 0),
            "true_available":    float(tav) if tav is not None else None,
            "pct_spent":         (actuals_f / budget_f) if budget_f else None,
        }
    else:
        totals = {
            "current_budget": None, "actuals": 0.0,
            "open_encumbrances": 0.0, "true_available": None, "pct_spent": None,
        }

    # Leaf-level totals — used to surface the budget reconciliation gap
    # honestly in the caveats (FMEDDW under-reports agency budget by ~23%
    # in FY26 because some appropriations are posted at Fund x CI only).
    leaf_budget_sum  = sum((r["current_budget"] or 0) for r in leaf)
    leaf_actuals_sum = sum((r["actuals"]        or 0) for r in leaf)

    meta = get_fiscal_year_status(fy)
    caveats: list[str] = []
    if not fa_supported:
        caveats.append(
            "Functional Area grain not available before FY26 — the FA level "
            "has been collapsed on this view."
        )
    if not fc_budget:
        caveats.append(
            "FY25 budget is posted only at Fund x CI grain (no Funds Center). "
            "Leaf rows show actuals only; agency-wide budget total is "
            "authoritative from vw_budget_vs_actuals_by_fund."
        )
    # Actuals reconciliation note (FA apportionment + unallocated bucket)
    if fa_supported:
        unalloc = sum((r["actuals"] or 0) for r in leaf
                      if r["functional_area"] is None)
        if abs(unalloc) > 0:
            pct = (abs(unalloc) / abs(leaf_actuals_sum) * 100) if leaf_actuals_sum else 0
            caveats.append(
                f"Actuals at the FA level are apportioned across FA using "
                f"FI Vendor Invoice shares within each (FC, Fund, CI) cell. "
                f"${abs(unalloc):,.0f} ({pct:.1f}%) of FM actuals have no FI "
                f"Vendor Invoice counterpart (mostly payroll-routed salaries "
                f"and benefits) and land in the '(unallocated FA)' bucket."
            )
    # Budget reconciliation gap — leaf sums use FMEDDW which doesn't carry
    # federal funds at the FC x FA grain
    if (totals.get("current_budget") is not None
            and abs(totals["current_budget"]) > 0
            and abs(totals["current_budget"] - leaf_budget_sum) > 1000):
        gap = totals["current_budget"] - leaf_budget_sum
        pct = abs(gap) / abs(totals["current_budget"]) * 100
        caveats.append(
            f"Leaf budget rows sum to ${leaf_budget_sum:,.0f} but the agency "
            f"appropriated budget is ${totals['current_budget']:,.0f} (gap "
            f"${gap:,.0f}, {pct:.1f}%). Federal funds (50000000 'FEDERAL FUNDS' "
            f"plus the smaller 30000000/40000000/50380000/50550000/51C70007/"
            f"55320000 federal/restricted funds) are appropriated at the fund "
            f"aggregate level in bex_budget_vs_actuals but carry no FC x FA x CI "
            f"rows in FMEDDW, accounting for ~99% of this gap. The remaining "
            f"~1% is timing/rounding noise in General Fund, EIA, Lottery and "
            f"Operating Revenue. Apportionment of federal appropriations to "
            f"FC x FA is a planned follow-up."
        )
    caveats.append(
        "Open Encumbrances are tracked at Fund x Funds_Center x CI grain "
        "(no Functional Area). They appear in the agency total but are not "
        "broken out at the FA leaf level."
    )

    return {
        "fy":            fy,
        "fy_status":     meta.get("status"),
        "as_of_date":    meta.get("as_of_date"),
        "fa_supported":  fa_supported,
        "fc_budget":     fc_budget,
        "rows":          leaf,
        "totals":        totals,
        "caveats":       caveats,
    }
