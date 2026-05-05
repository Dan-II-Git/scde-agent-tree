"""
ingest_detail_transaction.py
-----------------------------
Ingestion script for Detail Transaction Report SCDE *.xlsx files into the
canonical `sceis_detail_transaction` table in db/scde.duckdb.

IDEMPOTENCY STRATEGY: TRUNCATE-then-INSERT.
  - The natural candidate key is (Doc_Number, Doc_Item), but Doc_Item is a
    line number that resets per document and is not globally unique across
    fiscal years when Doc_Numbers collide across years (rare but observed
    for BI batch documents).  An upsert on (Doc_Number, Doc_Item) would
    silently drop FY-crossing collisions.
  - TRUNCATE-then-INSERT is simpler, faster for ~2.7M rows, and avoids the
    composite-key collision edge case.  Re-running always produces a clean
    load from the current set of source files.

SOURCE → SCHEMA COLUMN MAPPING (20 source columns → 17 schema columns):
  Dropped (not in schema):
    Grant            – always 'NOT RELEVANT' or a secondary identifier; no
                       schema column; confirmed redundant with Functional_Area
    Cost Element     – equals G/L Account when not '#'; '#' means the row is
                       a balance-sheet posting where no cost element applies.
                       G/L Account is always the authoritative 10-digit SAP
                       account.  Cost Element is dropped.
    Ref Doc Item     – line item within the originating document; no schema
                       column; not needed for any current join.

  Mapped:
    Business Area      → Business_Area   (VARCHAR)
    Fund               → Fund            (VARCHAR)
    Funds/Cost Center  → Funds_Cost_Center (VARCHAR)
    State Appropriation → State_Appropriation (VARCHAR)
    Agency Appropriation → Agency_Appropriation (VARCHAR)
    Functional area    → Functional_Area (VARCHAR)
    Posting Period     → Posting_Period  (SMALLINT)
    Fiscal year        → Fiscal_Year     (SMALLINT)
    Posting Date       → Posting_Date    (DATE)
    Document Type      → Document_Type  (VARCHAR)
    Doc Number         → Doc_Number     (VARCHAR)  – cast to str, strip
    Doc Item           → Doc_Item       (INTEGER)  – FY26 zero-padded str → int
    Ref Doc Number     → Ref_Doc_Number  (VARCHAR)
    G/L Account        → GL_Account     (VARCHAR)
    Posting Key        → Posting_Key    (VARCHAR)
    Debit/Credit Ind.  → Debit_Credit_Ind (VARCHAR)
    Debit/Credit Amount → Debit_Credit_Amount (DECIMAL 18,2)

SIGN CONVENTION (per CLAUDE.md):
  H (Haben/credit) rows carry NEGATIVE amounts in Debit_Credit_Amount.
  S (Soll/debit)   rows carry POSITIVE amounts.
  This script preserves the sign as-is from the source — never abs().

FY26 QUIRK: The YTD 4-16-26 file stores nearly every cell as a string
(the file was apparently exported as text).  Parsing explicitly handles
date strings like '7/1/2025' → datetime.date, numeric strings → int/float,
and zero-padded Doc_Item strings like '000507' → integer 507.

Usage:
    python scripts/ingest_detail_transaction.py [--dry-run]

    --dry-run  Parse and report counts without writing to the database.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Any

import duckdb
import openpyxl

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
UPLOADS_DIR = REPO_ROOT / "data" / "uploads"
DB_PATH = REPO_ROOT / "db" / "scde.duckdb"

# Glob pattern to discover source files
SOURCE_GLOB = "Detail Transaction Report SCDE*.xlsx"

# Target table
TABLE_NAME = "sceis_detail_transaction"

# Source column positions (0-based index in the 20-column header row)
#   0  Business Area
#   1  Fund
#   2  Funds/Cost Center
#   3  Grant                ← DROPPED
#   4  State Appropriation
#   5  Agency Appropriation
#   6  Functional area
#   7  Cost Element         ← DROPPED (use G/L Account at index 16)
#   8  Posting Period
#   9  Fiscal year
#  10  Posting Date
#  11  Document Type
#  12  Doc Number
#  13  Doc Item
#  14  Ref Doc Number
#  15  Ref Doc Item         ← DROPPED
#  16  G/L Account
#  17  Posting Key
#  18  Debit/Credit Ind.
#  19  Debit/Credit Amount

EXPECTED_HEADER = (
    "Business Area",
    "Fund",
    "Funds/Cost Center",
    "Grant",
    "State Appropriation",
    "Agency Appropriation",
    "Functional area",
    "Cost Element",
    "Posting Period",
    "Fiscal year",
    "Posting Date",
    "Document Type",
    "Doc Number",
    "Doc Item",
    "Ref Doc Number",
    "Ref Doc Item",
    "G/L Account",
    "Posting Key",
    "Debit/Credit Ind.",
    "Debit/Credit Amount",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_str(v: Any) -> str | None:
    """Coerce a cell value to a stripped string, or None if blank/null."""
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _to_str_nohash(v: Any) -> str | None:
    """Like _to_str but treat '#' as None (placeholder in SAP exports)."""
    s = _to_str(v)
    return None if s == "#" else s


def _to_int(v: Any, field: str, row_num: int, drop_log: list) -> int | None:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v:  # NaN
            return None
        return int(v)
    s = str(v).strip()
    if not s or s == "#":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        drop_log.append((row_num, field, repr(v), "cannot parse as int"))
        return None


def _to_decimal(v: Any, field: str, row_num: int, drop_log: list) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if v != v:
            return None
        return float(v)
    s = str(v).strip().replace(",", "")
    if not s or s == "#":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        drop_log.append((row_num, field, repr(v), "cannot parse as decimal"))
        return None


# Multiple date formats seen in the wild
_DATE_PATTERNS = [
    re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$"),   # M/D/YYYY  (FY26)
    re.compile(r"^(\d{4})-(\d{2})-(\d{2})"),          # YYYY-MM-DD
]


def _to_date(v: Any, field: str, row_num: int, drop_log: list) -> datetime.date | None:
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        return v.date()
    if isinstance(v, datetime.date):
        return v
    s = str(v).strip()
    if not s or s == "#":
        return None
    # M/D/YYYY
    m = _DATE_PATTERNS[0].match(s)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    # YYYY-MM-DD
    m = _DATE_PATTERNS[1].match(s)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    drop_log.append((row_num, field, repr(v), "unrecognised date format"))
    return None


def parse_row(
    row: tuple,
    row_num: int,
    source_file: str,
    sheet_name: str,
    drop_log: list,
) -> dict | None:
    """
    Parse one data row (20 source columns) into a dict keyed by schema column
    names.  Returns None if the row is entirely blank or lacks Doc_Number.
    """
    if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
        return None  # blank sentinel row

    doc_number = _to_str(row[12])
    if doc_number is None or doc_number == "#":
        drop_log.append((
            row_num, "Doc_Number", repr(row[12]),
            f"{source_file}/{sheet_name}: blank/hash Doc_Number",
        ))
        return None

    doc_item = _to_int(row[13], "Doc_Item", row_num, drop_log)

    posting_date = _to_date(row[10], "Posting_Date", row_num, drop_log)
    fiscal_year = _to_int(row[9], "Fiscal_Year", row_num, drop_log)
    posting_period = _to_int(row[8], "Posting_Period", row_num, drop_log)
    amount = _to_decimal(row[19], "Debit_Credit_Amount", row_num, drop_log)

    dc_ind = _to_str(row[18])

    # Sign-consistency check: H should be negative, S positive
    # Surface as caveat but do NOT alter the value.
    if dc_ind and amount is not None:
        if dc_ind == "H" and amount > 0:
            drop_log.append((
                row_num, "sign_check", f"H but amount={amount}",
                f"{source_file}/{sheet_name}: H indicator with positive amount — stored as-is",
            ))
        elif dc_ind == "S" and amount < 0:
            drop_log.append((
                row_num, "sign_check", f"S but amount={amount}",
                f"{source_file}/{sheet_name}: S indicator with negative amount — stored as-is",
            ))

    return {
        "Doc_Number": doc_number,
        "Doc_Item": doc_item,
        "Business_Area": _to_str(row[0]),
        "Fund": _to_str(row[1]),
        "Funds_Cost_Center": _to_str(row[2]),
        "Functional_Area": _to_str_nohash(row[6]),
        "Agency_Appropriation": _to_str(row[5]),
        "State_Appropriation": _to_str(row[4]),
        "GL_Account": _to_str(row[16]),
        "Posting_Date": posting_date,
        "Posting_Period": posting_period,
        "Fiscal_Year": fiscal_year,
        "Document_Type": _to_str(row[11]),
        "Ref_Doc_Number": _to_str(row[14]),
        "Posting_Key": _to_str(row[17]),
        "Debit_Credit_Ind": dc_ind,
        "Debit_Credit_Amount": amount,
    }


# ---------------------------------------------------------------------------
# Sheet loading
# ---------------------------------------------------------------------------

def load_workbook_sheets(xlsx_path: Path, drop_log: list) -> list[dict]:
    """
    Read all sheets from one workbook.  Returns a flat list of parsed row dicts.
    Validates headers, logs drift, and skips rows that fail parsing.
    """
    rows_out: list[dict] = []
    fname = xlsx_path.name

    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    sheets = wb.sheetnames

    for sheet_name in sheets:
        ws = wb[sheet_name]
        sheet_rows = ws.iter_rows(values_only=True)

        # Row 1: header
        try:
            header_raw = next(sheet_rows)
        except StopIteration:
            drop_log.append((0, "header", "", f"{fname}/{sheet_name}: empty sheet"))
            continue

        header = tuple(str(c).strip() if c is not None else "" for c in header_raw)

        # Check header length
        if len(header) != len(EXPECTED_HEADER):
            drop_log.append((
                1, "header_drift", str(header),
                f"{fname}/{sheet_name}: expected {len(EXPECTED_HEADER)} columns, got {len(header)}",
            ))
            # Try to continue if it's close enough by position
            if len(header) < 17:
                drop_log.append((1, "header_fatal", "", f"{fname}/{sheet_name}: too few columns — sheet skipped"))
                continue

        # Check for unexpected column name changes
        for i, (expected, actual) in enumerate(zip(EXPECTED_HEADER, header)):
            if expected.lower() != actual.lower():
                drop_log.append((
                    1, "header_drift",
                    f"col {i}: expected={expected!r} actual={actual!r}",
                    f"{fname}/{sheet_name}: column name mismatch",
                ))

        # Data rows
        for row_num, row in enumerate(sheet_rows, start=2):
            parsed = parse_row(row, row_num, fname, sheet_name, drop_log)
            if parsed is not None:
                rows_out.append(parsed)

    wb.close()
    return rows_out


# ---------------------------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------------------------

def run(dry_run: bool = False) -> None:
    # Discover source files
    source_files = sorted(UPLOADS_DIR.glob(SOURCE_GLOB))
    if not source_files:
        print(f"ERROR: No files matching '{SOURCE_GLOB}' found in {UPLOADS_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(source_files)} source file(s):")
    for f in source_files:
        print(f"  {f.name}")
    print()

    all_rows: list[dict] = []
    drop_log: list[tuple] = []

    for xlsx_path in source_files:
        print(f"Reading {xlsx_path.name} ...", flush=True)
        file_rows = load_workbook_sheets(xlsx_path, drop_log)
        print(f"  -> {len(file_rows):,} rows parsed")
        all_rows.extend(file_rows)

    print(f"\nTotal parsed rows: {len(all_rows):,}")

    # ---------------------------------------------------------------------------
    # Audit / diagnostics
    # ---------------------------------------------------------------------------

    # Breakdown by Fiscal_Year
    from collections import Counter
    fy_counts: Counter = Counter()
    gl_4xxx = 0
    gl_5xxx = 0
    gl_other: Counter = Counter()
    blank_doc = 0
    date_min = None
    date_max = None

    for r in all_rows:
        fy = r["Fiscal_Year"]
        if fy:
            fy_counts[fy] += 1

        gl = r["GL_Account"]
        if gl:
            if gl.startswith("4"):
                gl_4xxx += 1
            elif gl.startswith("5"):
                gl_5xxx += 1
            else:
                prefix = gl[0] if gl else "?"
                gl_other[prefix] += 1

        if not r["Doc_Number"]:
            blank_doc += 1

        pd = r["Posting_Date"]
        if pd:
            if date_min is None or pd < date_min:
                date_min = pd
            if date_max is None or pd > date_max:
                date_max = pd

    print("\n--- Breakdown by Fiscal_Year ---")
    for fy in sorted(fy_counts):
        print(f"  FY{fy}: {fy_counts[fy]:>10,} rows")

    print(f"\n--- Posting_Date range ---")
    print(f"  Min: {date_min}  Max: {date_max}")

    print(f"\n--- GL Account prefixes ---")
    print(f"  4xxx (revenue):     {gl_4xxx:>10,}")
    print(f"  5xxx (expenditure): {gl_5xxx:>10,}")
    for prefix, cnt in sorted(gl_other.items()):
        print(f"  {prefix}xxx (other):     {cnt:>10,}")

    if blank_doc:
        print(f"\nWARNING: {blank_doc} rows with blank Doc_Number were DROPPED (not in all_rows).")

    # Drop log summary
    print(f"\n--- Drop / caveat log ({len(drop_log)} entries) ---")
    # Summarize by reason
    reason_counts: Counter = Counter()
    sign_issues = []
    header_issues = []
    parse_issues = []
    for entry in drop_log:
        reason = entry[3] if len(entry) > 3 else "unknown"
        reason_counts[reason[:80]] += 1
        if "sign_check" in str(entry):
            sign_issues.append(entry)
        elif "header" in str(entry[1]):
            header_issues.append(entry)
        else:
            parse_issues.append(entry)

    if header_issues:
        print(f"\n  Header issues ({len(header_issues)}):")
        for e in header_issues[:10]:
            print(f"    {e}")

    if parse_issues:
        print(f"\n  Parse failures ({len(parse_issues)}):")
        for e in parse_issues[:20]:
            print(f"    {e}")
        if len(parse_issues) > 20:
            print(f"    ... and {len(parse_issues) - 20} more")

    if sign_issues:
        print(f"\n  Sign-convention anomalies ({len(sign_issues)}):")
        for e in sign_issues[:10]:
            print(f"    {e}")
        if len(sign_issues) > 10:
            print(f"    ... and {len(sign_issues) - 10} more")

    if not (header_issues or parse_issues or sign_issues) and not drop_log:
        print("  (none)")

    if dry_run:
        print("\n[DRY RUN] — no database writes performed.")
        return

    # ---------------------------------------------------------------------------
    # Stage to parquet (always) then write to DuckDB
    # ---------------------------------------------------------------------------
    staging_dir = REPO_ROOT / "data" / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = staging_dir / "sceis_detail_transaction.parquet"

    print(f"\nStaging {len(all_rows):,} rows to {parquet_path} ...")
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    df = pd.DataFrame(all_rows)
    # Ensure correct types
    df["Doc_Number"] = df["Doc_Number"].astype("string")
    df["Doc_Item"] = pd.to_numeric(df["Doc_Item"], errors="coerce").astype("Int32")
    df["Business_Area"] = df["Business_Area"].astype("string")
    df["Fund"] = df["Fund"].astype("string")
    df["Funds_Cost_Center"] = df["Funds_Cost_Center"].astype("string")
    df["Functional_Area"] = df["Functional_Area"].astype("string")
    df["Agency_Appropriation"] = df["Agency_Appropriation"].astype("string")
    df["State_Appropriation"] = df["State_Appropriation"].astype("string")
    df["GL_Account"] = df["GL_Account"].astype("string")
    df["Posting_Date"] = pd.to_datetime(df["Posting_Date"], errors="coerce").dt.date
    df["Posting_Period"] = pd.to_numeric(df["Posting_Period"], errors="coerce").astype("Int16")
    df["Fiscal_Year"] = pd.to_numeric(df["Fiscal_Year"], errors="coerce").astype("Int16")
    df["Document_Type"] = df["Document_Type"].astype("string")
    df["Ref_Doc_Number"] = df["Ref_Doc_Number"].astype("string")
    df["Posting_Key"] = df["Posting_Key"].astype("string")
    df["Debit_Credit_Ind"] = df["Debit_Credit_Ind"].astype("string")
    df["Debit_Credit_Amount"] = pd.to_numeric(df["Debit_Credit_Amount"], errors="coerce")

    df.to_parquet(str(parquet_path), index=False, engine="pyarrow")
    print(f"  Parquet written: {parquet_path.stat().st_size / 1024 / 1024:.1f} MB")

    # ---------------------------------------------------------------------------
    # Write to DuckDB
    # ---------------------------------------------------------------------------
    print(f"\nConnecting to {DB_PATH} ...")
    try:
        con = duckdb.connect(str(DB_PATH))
    except Exception as e:
        print(f"\nERROR: Cannot open database for writing: {e}", file=sys.stderr)
        print(
            f"\nThe app server (or another process) has the database open.\n"
            f"Parsed data has been staged to:\n"
            f"  {parquet_path}\n\n"
            f"To complete the load after closing the server, run:\n"
            f"  python scripts/ingest_detail_transaction.py --load-from-parquet",
            file=sys.stderr,
        )
        sys.exit(2)

    _write_to_db(con, parquet_path, len(all_rows))
    con.close()
    print("\nDone.")


def _write_to_db(con: duckdb.DuckDBPyConnection, parquet_path: Path, expected_rows: int) -> None:
    """Truncate sceis_detail_transaction and load from the staged parquet file."""
    # Verify target table exists
    tables = [r[0] for r in con.execute("SHOW TABLES").fetchall()]
    if TABLE_NAME not in tables:
        print(f"ERROR: Table '{TABLE_NAME}' does not exist in the database.", file=sys.stderr)
        sys.exit(1)

    print(f"TRUNCATING {TABLE_NAME} ...")
    con.execute(f"TRUNCATE TABLE {TABLE_NAME}")

    # Register the parquet as an arrow table to avoid path/SQL injection issues
    # (apostrophes in path would break read_parquet('literal') syntax).
    import pyarrow.parquet as pq
    arrow_table = pq.read_table(str(parquet_path))
    con.register("_dt_stage", arrow_table)

    print(f"Inserting from parquet ({expected_rows:,} rows) ...")
    con.execute(f"""
        INSERT INTO {TABLE_NAME} (
            Doc_Number, Doc_Item, Business_Area, Fund, Funds_Cost_Center,
            Functional_Area, Agency_Appropriation, State_Appropriation,
            GL_Account, Posting_Date, Posting_Period, Fiscal_Year,
            Document_Type, Ref_Doc_Number, Posting_Key,
            Debit_Credit_Ind, Debit_Credit_Amount
        )
        SELECT
            Doc_Number,
            Doc_Item,
            Business_Area,
            Fund,
            Funds_Cost_Center,
            Functional_Area,
            Agency_Appropriation,
            State_Appropriation,
            GL_Account,
            Posting_Date::DATE,
            Posting_Period::SMALLINT,
            Fiscal_Year::SMALLINT,
            Document_Type,
            Ref_Doc_Number,
            Posting_Key,
            Debit_Credit_Ind,
            Debit_Credit_Amount::DECIMAL(18,2)
        FROM _dt_stage
    """)

    db_count = con.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0]
    print(f"\nVerification: {TABLE_NAME} now contains {db_count:,} rows")

    if db_count != expected_rows:
        print(f"WARNING: expected {expected_rows:,} but DB reports {db_count:,} — possible constraint violation drop")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing to DB")
    parser.add_argument(
        "--load-from-parquet",
        action="store_true",
        help=(
            "Skip xlsx parsing; load directly from the previously staged parquet at "
            "data/staging/sceis_detail_transaction.parquet. "
            "Use this after stopping the app server if the first run failed with a lock error."
        ),
    )
    args = parser.parse_args()

    if args.load_from_parquet:
        parquet_path = REPO_ROOT / "data" / "staging" / "sceis_detail_transaction.parquet"
        if not parquet_path.exists():
            print(f"ERROR: Staged parquet not found at {parquet_path}", file=sys.stderr)
            print("Run without --load-from-parquet first to parse and stage the data.", file=sys.stderr)
            sys.exit(1)
        import pyarrow.parquet as pq
        expected = pq.read_metadata(str(parquet_path)).num_rows
        print(f"Loading from staged parquet: {parquet_path}")
        print(f"Expected rows: {expected:,}")
        print(f"\nConnecting to {DB_PATH} ...")
        con = duckdb.connect(str(DB_PATH))
        _write_to_db(con, parquet_path, expected)
        con.close()
        print("\nDone.")
    else:
        run(dry_run=args.dry_run)
