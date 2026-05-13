"""
ingest_bex_reports.py
---------------------
Ingestion script for the four SAP BEx report exports from
  data/uploads/Dan's Reports.xlsx

into db/scde.duckdb as four tables:

    bex_fm_expense          -- Funds Management Expense BEx
    bex_open_encumbrances   -- Open Encumbrance BEx
    bex_budget_vs_actuals   -- Budget v Actual BEx
    bex_fi_vendor_invoice   -- FI Vendor Invoice BEx

IDEMPOTENCY STRATEGY: CREATE OR REPLACE TABLE.
  Each run drops-and-recreates all four tables from scratch.
  Safe to re-run when source xlsx is refreshed.

SIGN CONVENTIONS:
  bex_fm_expense.Qtr_*/FY_Total  -- negative = expense (SAP BEx convention).
    Keep as-is; do NOT flip. Views that consume this table apply ABS() or
    negation explicitly per their use case.
  bex_fi_vendor_invoice.Amount_FM -- positive = expense, occasional negatives
    are within-doc credits/reversals (~2.5% of rows). Keep as-is.

FOOTER STRIPPING:
  bex_fm_expense      -- drops rows where Funds_Cost_Center is NULL,
                         empty string, or equals 'Result' / 'Overall Result'.
  bex_open_encumbs    -- drops rows where the first cell equals 'Overall Result'
                         (the SAP grand-total footer row).
  bex_budget_vs_actuals -- no SAP grand-total footer row in source; no strip
                           needed (last data rows are genuine zero-budget lines).
  bex_fi_vendor_invoice -- drops rows where FI_Doc_Number IS NULL (those are
                           'Overall Result' footers that would double the total).

FISCAL YEAR STAMPING:
  Fiscal_Year is stamped from the sheet name prefix (2025 / 2026), NOT from
  row-level date math. Sheet names follow the pattern: '{FY} {Report Name}'.

FUND CODE MAPPING (bex_budget_vs_actuals only):
  Fund_Code is looked up from db/dim_fund_mapping.json. The 28th fund
  'HR PAYROLL TEMP FUND' has no reliable mapping and is loaded as Fund_Code=NULL.

Usage:
    python scripts/ingest_bex_reports.py [--dry-run]

    --dry-run  Parse and report counts / totals without writing to the DB.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import duckdb
import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "db" / "scde.duckdb"
SOURCE_FILE = REPO_ROOT / "data" / "uploads" / "Dan's Reports.xlsx"
FUND_MAP_FILE = REPO_ROOT / "db" / "dim_fund_mapping.json"

# ---------------------------------------------------------------------------
# Type coercions
# ---------------------------------------------------------------------------

def to_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    return s if s else None


def to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("$", "").strip()
    return float(s) if s else None


def to_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unparseable date: {v!r}")


def to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    s = str(v).strip()
    return int(s) if s else None


# ---------------------------------------------------------------------------
# Sheet loader helpers
# ---------------------------------------------------------------------------

def load_sheet_rows(wb: openpyxl.Workbook, sheet_name: str) -> tuple[list[str], list[tuple]]:
    """Return (header_list, data_rows) for the named sheet."""
    ws = wb[sheet_name]
    it = ws.iter_rows(values_only=True)
    header = list(next(it))
    data = [row for row in it if row is not None and not all(c is None for c in row)]
    return header, data


# ---------------------------------------------------------------------------
# Table 1: bex_fm_expense
# ---------------------------------------------------------------------------

FM_EXPENSE_SHEETS = [
    ("2025 Funds Mgmt Expense BEx", 2025),
    ("2026 Funds Mgmt Expense BEx", 2026),
]

# Column layout (0-indexed from header inspection):
# [0]  Business area (code)
# [1]  Business area (name) -- blank header, always 'EDUCATION DEPARTMENT'
# [2]  Fund/Cost Center  -> Funds_Cost_Center
# [3]  Fund
# [4]  Grant
# [5]  State Appropriation
# [6]  Agency Appropriation
# [7]  Commitment Item
# [8]  G/L Account
# [9]  Vendor (number) -- blank header
# [10] Vendor name     -- blank header
# [11] Qtr 01
# [12] Qtr 02
# [13] Qtr 03
# [14] Qtr 04
# [15] Year End Adjustments
# [16] FY Total


def parse_fm_expense(wb: openpyxl.Workbook) -> list[dict]:
    rows_out = []
    for sheet_name, fy in FM_EXPENSE_SHEETS:
        _, data = load_sheet_rows(wb, sheet_name)
        for row in data:
            fcc = to_str(row[2])
            # Drop footer rows: NULL, empty, or SAP subtotal labels
            if fcc is None or fcc == "" or fcc in ("Result", "Overall Result"):
                continue
            rows_out.append({
                "Business_Area":       to_str(row[0]),
                "Funds_Cost_Center":   fcc,
                "Fund":                to_str(row[3]),
                "Grant":               to_str(row[4]),
                "State_Appropriation": to_str(row[5]),
                "Agency_Appropriation":to_str(row[6]),
                "Commitment_Item":     to_str(row[7]),
                "GL_Account":          to_str(row[8]),
                "Vendor_Number":       to_str(row[9]),
                "Vendor_Name":         to_str(row[10]),
                "Qtr_01":              to_float(row[11]),
                "Qtr_02":              to_float(row[12]),
                "Qtr_03":              to_float(row[13]),
                "Qtr_04":              to_float(row[14]),
                "YE_Adj":              to_float(row[15]),
                "FY_Total":            to_float(row[16]),
                "Fiscal_Year":         fy,
            })
    return rows_out


# ---------------------------------------------------------------------------
# Table 2: bex_open_encumbrances
# ---------------------------------------------------------------------------

OPEN_ENC_SHEETS = [
    ("2025 Open Encumbrance BEx", 2025),
    ("2026 Open Encumbrance BEx", 2026),
]

# Column layout:
# [0]  Business area (code)
# [1]  Business area (name) -- blank header
# [2]  Fund
# [3]  Funded Program
# [4]  Funds Center
# [5]  Commitment item
# [6]  Commt/Actual Detail -> Detail_Type
# [7]  Reference Doc. No.
# [8]  Document Date
# [9]  Vendor (number)  -- blank header
# [10] Vendor name      -- blank header
# [11] Order num
# [12] (blank) Order num description -- drop
# [13] WBS Element
# [14] (blank) WBS description      -- drop
# [15] Original Amount
# [16] Adjustments
# [17] Invoiced Amount
# [18] Goods Receipt Valuated
# [19] Remaining Balance


def parse_open_encumbrances(wb: openpyxl.Workbook) -> list[dict]:
    rows_out = []
    for sheet_name, fy in OPEN_ENC_SHEETS:
        _, data = load_sheet_rows(wb, sheet_name)
        for row in data:
            # Footer row: Business area code is 'Overall Result'
            if to_str(row[0]) in ("Overall Result", "Result"):
                continue
            rows_out.append({
                "Business_Area":          to_str(row[0]),
                "Fund":                   to_str(row[2]),
                "Funded_Program":         to_str(row[3]),
                "Funds_Center":           to_str(row[4]),
                "Commitment_Item":        to_str(row[5]),
                "Detail_Type":            to_str(row[6]),
                "Reference_Doc_No":       to_str(row[7]),
                "Document_Date":          to_date(row[8]),
                "Vendor_Number":          to_str(row[9]),
                "Vendor_Name":            to_str(row[10]),
                "Order_Num":              to_str(row[11]),
                "WBS_Element":            to_str(row[13]),
                "Original_Amount":        to_float(row[15]),
                "Adjustments":            to_float(row[16]),
                "Invoiced_Amount":        to_float(row[17]),
                "Goods_Receipt_Valuated": to_float(row[18]),
                "Remaining_Balance":      to_float(row[19]),
                "Fiscal_Year":            fy,
            })
    return rows_out


# ---------------------------------------------------------------------------
# Table 3: bex_budget_vs_actuals
# ---------------------------------------------------------------------------

BVA_SHEETS = [
    ("2025 Budget v Actual BEx", 2025),
    ("2026 Budget v Actual BEx", 2026),
]

# Column layout:
# [0]  Fund           -> Fund_Name
# [1]  Commitment Items -> Commitment_Item (6-char = parent, 10-char = leaf)
# [2]  Original Budget
# [3]  Budget Adjustments
# [4]  Current Budget
# [5]  MTD Actual Expense
# [6]  YTD Actual Expense
# [7]  Balance Before Commitments
# [8]  Commitments and Other Transactions -> Open_Commitments
# [9]  Remaining Balance


def parse_budget_vs_actuals(wb: openpyxl.Workbook, fund_map: dict) -> list[dict]:
    rows_out = []
    for sheet_name, fy in BVA_SHEETS:
        _, data = load_sheet_rows(wb, sheet_name)
        for row in data:
            fund_name = to_str(row[0])
            # No SAP grand-total footer in BvA sheets; all rows are data rows.
            # Fund name is always non-null in this sheet.
            if fund_name is None:
                continue
            ci_raw = to_str(row[1])
            ci_len = len(ci_raw) if ci_raw else 0
            ci_level = 6 if ci_len == 6 else (10 if ci_len == 10 else None)
            # Fund_Code from mapping (NULL for unmapped funds)
            fund_code = fund_map.get(fund_name)  # already None for HR PAYROLL TEMP FUND
            rows_out.append({
                "Fund_Name":                  fund_name,
                "Fund_Code":                  fund_code,
                "Commitment_Item":            ci_raw,
                "CI_Level":                   ci_level,
                "Original_Budget":            to_float(row[2]),
                "Budget_Adjustments":         to_float(row[3]),
                "Current_Budget":             to_float(row[4]),
                "MTD_Actual_Expense":         to_float(row[5]),
                "YTD_Actual_Expense":         to_float(row[6]),
                "Balance_Before_Commitments": to_float(row[7]),
                "Open_Commitments":           to_float(row[8]),
                "Remaining_Balance":          to_float(row[9]),
                "Fiscal_Year":                fy,
            })
    return rows_out


# ---------------------------------------------------------------------------
# Table 4: bex_fi_vendor_invoice
# ---------------------------------------------------------------------------

FI_VENDOR_SHEETS = [
    ("2025 FI Vendor Invoice BEx", 2025),
    ("2026 FI Vendor Invoice BEx", 2026),
]

# Column layout:
# [0]  Vendor (number)   -- blank header
# [1]  Vendor name       -- blank header
# [2]  FI doc.number
# [3]  Purch Order (if appl) -> Purchase_Order
# [4]  Document type
# [5]  (blank) Document type description
# [6]  G/L Account       -- blank header
# [7]  (blank) G/L account name
# [8]  Posting date
# [9]  Funds Center
# [10] Functional area   -- blank header
# [11] (blank) Functional area description
# [12] Grant
# [13] Fund
# [14] Amnt in FM area crcy -> Amount_FM


def parse_fi_vendor_invoice(wb: openpyxl.Workbook) -> list[dict]:
    rows_out = []
    for sheet_name, fy in FI_VENDOR_SHEETS:
        _, data = load_sheet_rows(wb, sheet_name)
        for row in data:
            fi_doc = to_str(row[2])
            # Critical: drop rows where FI_Doc_Number IS NULL -- those are
            # 'Overall Result' footer rows and would double the total.
            if fi_doc is None:
                continue
            rows_out.append({
                "Vendor_Number":       to_str(row[0]),
                "Vendor_Name":         to_str(row[1]),
                "FI_Doc_Number":       fi_doc,
                "Purchase_Order":      to_str(row[3]),
                "Document_Type":       to_str(row[4]),
                "Document_Type_Desc":  to_str(row[5]),
                "GL_Account":          to_str(row[6]),
                "GL_Account_Name":     to_str(row[7]),
                "Posting_Date":        to_date(row[8]),
                "Funds_Center":        to_str(row[9]),
                "Functional_Area":     to_str(row[10]),
                "Functional_Area_Desc":to_str(row[11]),
                "Grant":               to_str(row[12]),
                "Fund":                to_str(row[13]),
                "Amount_FM":           to_float(row[14]),
                "Fiscal_Year":         fy,
            })
    return rows_out


# ---------------------------------------------------------------------------
# DDL + COMMENT helpers
# ---------------------------------------------------------------------------

DDL_FM_EXPENSE = """
CREATE OR REPLACE TABLE bex_fm_expense (
    Business_Area        VARCHAR,
    Funds_Cost_Center    VARCHAR,
    Fund                 VARCHAR,
    Grant                VARCHAR,
    State_Appropriation  VARCHAR,
    Agency_Appropriation VARCHAR,
    Commitment_Item      VARCHAR,
    GL_Account           VARCHAR,
    Vendor_Number        VARCHAR,
    Vendor_Name          VARCHAR,
    Qtr_01               DOUBLE,
    Qtr_02               DOUBLE,
    Qtr_03               DOUBLE,
    Qtr_04               DOUBLE,
    YE_Adj               DOUBLE,
    FY_Total             DOUBLE,
    Fiscal_Year          INTEGER
);
"""

DDL_OPEN_ENC = """
CREATE OR REPLACE TABLE bex_open_encumbrances (
    Business_Area          VARCHAR,
    Fund                   VARCHAR,
    Funded_Program         VARCHAR,
    Funds_Center           VARCHAR,
    Commitment_Item        VARCHAR,
    Detail_Type            VARCHAR,
    Reference_Doc_No       VARCHAR,
    Document_Date          DATE,
    Vendor_Number          VARCHAR,
    Vendor_Name            VARCHAR,
    Order_Num              VARCHAR,
    WBS_Element            VARCHAR,
    Original_Amount        DOUBLE,
    Adjustments            DOUBLE,
    Invoiced_Amount        DOUBLE,
    Goods_Receipt_Valuated DOUBLE,
    Remaining_Balance      DOUBLE,
    Fiscal_Year            INTEGER
);
"""

DDL_BVA = """
CREATE OR REPLACE TABLE bex_budget_vs_actuals (
    Fund_Name                  VARCHAR,
    Fund_Code                  VARCHAR,
    Commitment_Item            VARCHAR,
    CI_Level                   INTEGER,
    Original_Budget            DOUBLE,
    Budget_Adjustments         DOUBLE,
    Current_Budget             DOUBLE,
    MTD_Actual_Expense         DOUBLE,
    YTD_Actual_Expense         DOUBLE,
    Balance_Before_Commitments DOUBLE,
    Open_Commitments           DOUBLE,
    Remaining_Balance          DOUBLE,
    Fiscal_Year                INTEGER
);
"""

DDL_FI_VENDOR = """
CREATE OR REPLACE TABLE bex_fi_vendor_invoice (
    Vendor_Number        VARCHAR,
    Vendor_Name          VARCHAR,
    FI_Doc_Number        VARCHAR,
    Purchase_Order       VARCHAR,
    Document_Type        VARCHAR,
    Document_Type_Desc   VARCHAR,
    GL_Account           VARCHAR,
    GL_Account_Name      VARCHAR,
    Posting_Date         DATE,
    Funds_Center         VARCHAR,
    Functional_Area      VARCHAR,
    Functional_Area_Desc VARCHAR,
    Grant                VARCHAR,
    Fund                 VARCHAR,
    Amount_FM            DOUBLE,
    Fiscal_Year          INTEGER
);
"""

# Non-obvious column comments applied via COMMENT ON COLUMN after CREATE.
COLUMN_COMMENTS: list[tuple[str, str, str]] = [
    # bex_fm_expense
    ("bex_fm_expense", "Funds_Cost_Center",
     "SAP Funds Management cost center. Joins to sceis_agency_master.Cost_Center. "
     "Footer rows where this is NULL or 'Result' are stripped at load."),
    ("bex_fm_expense", "Qtr_01",
     "Expenditure for fiscal quarter 1 (Jul-Sep). NEGATIVE = expense per SAP BEx "
     "convention. Do NOT flip sign — views apply negation/ABS explicitly."),
    ("bex_fm_expense", "Qtr_02",
     "Expenditure for fiscal quarter 2 (Oct-Dec). NEGATIVE = expense. Keep as-is."),
    ("bex_fm_expense", "Qtr_03",
     "Expenditure for fiscal quarter 3 (Jan-Mar). NEGATIVE = expense. Keep as-is."),
    ("bex_fm_expense", "Qtr_04",
     "Expenditure for fiscal quarter 4 (Apr-Jun). NEGATIVE = expense. Keep as-is."),
    ("bex_fm_expense", "YE_Adj",
     "Year-end adjustment amount. NEGATIVE = expense. Keep as-is."),
    ("bex_fm_expense", "FY_Total",
     "Full-year expenditure total (sum of Qtr_01..Qtr_04 + YE_Adj). NEGATIVE = expense. "
     "This is the expense-leg side of FI documents; matches sceis_fi_payments totals "
     "once the SAP Overall Result footer is stripped."),
    ("bex_fm_expense", "Fiscal_Year",
     "SC fiscal year (Jul-Jun ending year). Stamped from sheet name, not row dates."),
    # bex_open_encumbrances
    ("bex_open_encumbrances", "Detail_Type",
     "Commitment category: 'Purchase Order', 'Funds Reservation', or 'Parked FI Document'."),
    ("bex_open_encumbrances", "Reference_Doc_No",
     "Source document number (PO number, funds reservation number, or parked FI doc number)."),
    ("bex_open_encumbrances", "Original_Amount",
     "Original committed amount at document creation. POSITIVE."),
    ("bex_open_encumbrances", "Adjustments",
     "Net adjustments to the original commitment since creation. Signed; typically negative "
     "as invoices arrive and consume the PO budget."),
    ("bex_open_encumbrances", "Invoiced_Amount",
     "Amount invoiced against this commitment. NEGATIVE (consumed/paid out)."),
    ("bex_open_encumbrances", "Goods_Receipt_Valuated",
     "Goods receipt valuation amount for POs with GR/IV processing. Often NULL for "
     "service POs."),
    ("bex_open_encumbrances", "Remaining_Balance",
     "Uncommitted balance remaining: Original_Amount + Adjustments + Invoiced_Amount + "
     "Goods_Receipt_Valuated. Zero = fully consumed. The SAP Overall Result footer row "
     "is stripped at load to prevent double-counting."),
    ("bex_open_encumbrances", "Fiscal_Year",
     "SC fiscal year (Jul-Jun ending year). Stamped from sheet name, not row dates."),
    # bex_budget_vs_actuals
    ("bex_budget_vs_actuals", "Fund_Name",
     "SAP fund display name as it appears in BEx (e.g., 'GENERAL FUND', 'FEDERAL'). "
     "Join key to Fund_Code via dim_fund_mapping.json."),
    ("bex_budget_vs_actuals", "Fund_Code",
     "8-character SAP fund code mapped from Fund_Name via db/dim_fund_mapping.json "
     "(27-of-28 funds mapped; NULL for HR PAYROLL TEMP FUND which has zero budget and "
     "zero actuals in both FY25 and FY26)."),
    ("bex_budget_vs_actuals", "Commitment_Item",
     "SAP Commitment Item code. 6-character codes are parent rollup nodes (CI_Level=6); "
     "10-character codes are leaf items (CI_Level=10). Do not mix levels in aggregations."),
    ("bex_budget_vs_actuals", "CI_Level",
     "Derived from Commitment_Item string length: 6 = parent rollup, 10 = leaf item. "
     "Filter CI_Level=10 for leaf-level budget analysis to avoid double-counting."),
    ("bex_budget_vs_actuals", "Original_Budget",
     "Budget as originally appropriated at fiscal year start."),
    ("bex_budget_vs_actuals", "Budget_Adjustments",
     "Net budget adjustments (transfers, supplements, carryforward) posted after "
     "the original appropriation. Signed; positive = budget added, negative = budget reduced."),
    ("bex_budget_vs_actuals", "Current_Budget",
     "Effective current budget: Original_Budget + Budget_Adjustments."),
    ("bex_budget_vs_actuals", "MTD_Actual_Expense",
     "Month-to-date actual expenditure at the time of BEx extract. Signed per BEx "
     "convention (negative = expense for most extract flavors; verify sign before use)."),
    ("bex_budget_vs_actuals", "YTD_Actual_Expense",
     "Year-to-date actual expenditure at the time of BEx extract. NEGATIVE for expense "
     "rows (SAP BEx convention). Use ABS() when comparing to budget figures."),
    ("bex_budget_vs_actuals", "Balance_Before_Commitments",
     "Remaining budget before open commitments (POs, reservations) are deducted: "
     "Current_Budget + YTD_Actual_Expense (signs cancel)."),
    ("bex_budget_vs_actuals", "Open_Commitments",
     "Sum of outstanding purchase orders, funds reservations, and parked documents "
     "that have not yet been invoiced. NEGATIVE (reduces available budget)."),
    ("bex_budget_vs_actuals", "Remaining_Balance",
     "Final remaining budget after commitments: Balance_Before_Commitments + "
     "Open_Commitments."),
    ("bex_budget_vs_actuals", "Fiscal_Year",
     "SC fiscal year (Jul-Jun ending year). Stamped from sheet name, not row dates."),
    # bex_fi_vendor_invoice
    ("bex_fi_vendor_invoice", "FI_Doc_Number",
     "SAP FI document number. Join key to sceis_fi_payments.Doc_Number (AP-leg) — "
     "these are the expense-leg side of the same documents. Rows where this is NULL "
     "are SAP Overall Result footer rows and are dropped at load."),
    ("bex_fi_vendor_invoice", "Amount_FM",
     "Amount in FM area currency (USD). POSITIVE = expense (income/credits are "
     "negative, ~2.5% of rows). Keep as-is; do NOT abs() before aggregation. "
     "FY25 sum ~$7.319B matches sceis_fi_payments FY25 total after footer strip."),
    ("bex_fi_vendor_invoice", "Purchase_Order",
     "Purchase order number linked to this invoice, if applicable. '#' = no PO "
     "(direct FI invoice)."),
    ("bex_fi_vendor_invoice", "Document_Type",
     "SAP FI document type (e.g., KI = vendor invoice, RE = invoice gross, "
     "ZP = payment)."),
    ("bex_fi_vendor_invoice", "GL_Account",
     "10-digit SAP G/L account. Joins to lookup_gl_account for handbook-level grouping."),
    ("bex_fi_vendor_invoice", "Functional_Area",
     "SAP CO functional area in H630_XXXX format. Joins to "
     "sceis_agency_master.Functional_Area."),
    ("bex_fi_vendor_invoice", "Fiscal_Year",
     "SC fiscal year (Jul-Jun ending year). Stamped from sheet name, not row dates."),
]


def apply_column_comments(con: duckdb.DuckDBPyConnection) -> None:
    for table, col, comment in COLUMN_COMMENTS:
        escaped = comment.replace("'", "''")
        con.execute(f"COMMENT ON COLUMN {table}.{col} IS '{escaped}'")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _fy_totals(rows: list[dict], amount_col: str) -> dict[int, float]:
    totals: dict[int, float] = {}
    for r in rows:
        fy = r["Fiscal_Year"]
        v = r.get(amount_col) or 0.0
        totals[fy] = totals.get(fy, 0.0) + v
    return totals


def _fy_counts(rows: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for r in rows:
        fy = r["Fiscal_Year"]
        counts[fy] = counts.get(fy, 0) + 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="parse only; do not write to DB")
    args = ap.parse_args()

    if not SOURCE_FILE.exists():
        sys.exit(f"Source file not found: {SOURCE_FILE}")
    if not FUND_MAP_FILE.exists():
        sys.exit(f"Fund mapping file not found: {FUND_MAP_FILE}")

    print(f"Source: {SOURCE_FILE.name}")
    print(f"Fund map: {FUND_MAP_FILE.name}")
    print()

    # Load fund mapping (Fund_Name -> Fund_Code or None)
    with FUND_MAP_FILE.open(encoding="utf-8") as f:
        raw_map = json.load(f)
    fund_map: dict[str, str | None] = {
        name: entry["Fund_Code"]
        for name, entry in raw_map["mapping"].items()
    }

    # Open workbook once
    print("Opening workbook (read_only)...")
    wb = openpyxl.load_workbook(str(SOURCE_FILE), read_only=True, data_only=True)

    # --- Parse all four tables ---
    print("Parsing bex_fm_expense...")
    fm_rows = parse_fm_expense(wb)
    print(f"  {len(fm_rows):,} rows  |  FY counts: {_fy_counts(fm_rows)}")
    fm_totals = _fy_totals(fm_rows, "FY_Total")
    for fy, total in sorted(fm_totals.items()):
        print(f"  FY{fy} FY_Total sum: {total:,.2f}")

    print()
    print("Parsing bex_open_encumbrances...")
    enc_rows = parse_open_encumbrances(wb)
    print(f"  {len(enc_rows):,} rows  |  FY counts: {_fy_counts(enc_rows)}")
    enc_totals = _fy_totals(enc_rows, "Remaining_Balance")
    for fy, total in sorted(enc_totals.items()):
        print(f"  FY{fy} Remaining_Balance sum: {total:,.2f}")

    print()
    print("Parsing bex_budget_vs_actuals...")
    bva_rows = parse_budget_vs_actuals(wb, fund_map)
    print(f"  {len(bva_rows):,} rows  |  FY counts: {_fy_counts(bva_rows)}")
    unmapped = sum(1 for r in bva_rows if r["Fund_Code"] is None)
    print(f"  Unmapped Fund_Code (NULL): {unmapped} rows (expected: HR PAYROLL TEMP FUND only)")
    bva_totals = _fy_totals(bva_rows, "Current_Budget")
    for fy, total in sorted(bva_totals.items()):
        print(f"  FY{fy} Current_Budget sum: {total:,.2f}")

    print()
    print("Parsing bex_fi_vendor_invoice...")
    fi_rows = parse_fi_vendor_invoice(wb)
    print(f"  {len(fi_rows):,} rows  |  FY counts: {_fy_counts(fi_rows)}")
    fi_totals = _fy_totals(fi_rows, "Amount_FM")
    for fy, total in sorted(fi_totals.items()):
        print(f"  FY{fy} Amount_FM sum: {total:,.2f}  (expected FY25 ~$7.319B)")

    wb.close()

    if args.dry_run:
        print()
        print("DRY RUN — not writing to DB.")
        return

    # --- Write to DuckDB ---
    if not DB_PATH.exists():
        sys.exit(f"DB not found: {DB_PATH}")

    print()
    print(f"Writing to {DB_PATH.name}...")
    con = duckdb.connect(str(DB_PATH))

    def insert_table(ddl: str, table_name: str, rows: list[dict]) -> None:
        con.execute(ddl)
        if not rows:
            print(f"  {table_name}: 0 rows (table created empty)")
            return
        cols = list(rows[0].keys())
        placeholders = ", ".join("?" * len(cols))
        sql = f"INSERT INTO {table_name} ({', '.join(cols)}) VALUES ({placeholders})"
        con.executemany(sql, [[r[c] for c in cols] for r in rows])
        count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"  {table_name}: {count:,} rows loaded")

    insert_table(DDL_FM_EXPENSE, "bex_fm_expense", fm_rows)
    insert_table(DDL_OPEN_ENC,   "bex_open_encumbrances", enc_rows)
    insert_table(DDL_BVA,        "bex_budget_vs_actuals", bva_rows)
    insert_table(DDL_FI_VENDOR,  "bex_fi_vendor_invoice", fi_rows)

    print()
    print("Applying column comments...")
    apply_column_comments(con)

    con.close()
    print("Done.")


if __name__ == "__main__":
    main()
