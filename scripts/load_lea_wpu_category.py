"""
Load 135-day WPU files into lea_wpu_category, one row per
(District_ID, Fiscal_Year, Report_Cycle, Category).

Coverage:
  - FY21-FY24: parsed from the 'Financial Requirements' sheet which
    carries per-category ADM and Weighted_Pupils. Source row labels
    are mapped to canonical Categories via CATEGORY_MAP below.
  - FY25: Financial Requirements sheet was not published for FY25.
    The 'WPU' sheet only has district-level totals. Loaded as a
    single Category='TOTAL' row per district; the engine treats this
    as a degraded "total-only" mode (per-category weight dialing is
    disabled in the UI).

Source label → canonical Category mapping:
  BASE_K12     : KINDERGARTEN, PRIMARY, ELEMENTARY, HIGH SCHOOL, HB
  SPED         : AUT, EH, EM H, HH, SP H, LD, OH, TM, VH
  CTE          : CTE
  CHARTER_BM   : B&M  (135-day: always 0; real values come from 45-day file)
  CHARTER_VIRT : VIRT (135-day: always 0)
  GIFTED       : HIAC
  ACAD_ASSIST  : ACAS
  LEP          : LEP
  POVERTY      : PIP
  TOTAL        : (FY25 only — district-total WPU passthrough)

Rows skipped: DUAL, MembershipTotals:, Add-OnTotals:, Grand Totals:.

Run:
  python scripts/load_lea_wpu_category.py            # all available FYs
  python scripts/load_lea_wpu_category.py --fy 2024  # one FY
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import openpyxl
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "db" / "scde.duckdb"
UPLOADS = Path(__file__).resolve().parent.parent / "data" / "uploads"

# Source files keyed by FY. FY25 has a different shape — see _parse_fy25_totals.
FY_SOURCES = {
    2021: UPLOADS / "WPU13521.xlsx",
    2022: UPLOADS / "WPU13522.xlsx",
    2023: UPLOADS / "WPU13523.xlsx",
    2024: UPLOADS / "WPU13524.xlsx",
    2025: UPLOADS / "WPU 13525.xlsx",  # space in filename is intentional
}

REPORT_CYCLE = 135

# Source label -> canonical category
CATEGORY_MAP = {
    "KINDERGARTEN": "BASE_K12",
    "PRIMARY":      "BASE_K12",
    "ELEMENTARY":   "BASE_K12",
    "HIGH SCHOOL":  "BASE_K12",
    "HB":           "BASE_K12",   # Homebound, weight=1.0, blends into base
    "AUT":          "SPED",
    "EH":           "SPED",
    "EM H":         "SPED",
    "HH":           "SPED",
    "SP H":         "SPED",
    "LD":           "SPED",
    "OH":           "SPED",
    "TM":           "SPED",
    "VH":           "SPED",
    "CTE":          "CTE",
    "B&M":          "CHARTER_BM",
    "VIRT":         "CHARTER_VIRT",
    "HIAC":         "GIFTED",
    "ACAS":         "ACAD_ASSIST",
    "LEP":          "LEP",
    "PIP":          "POVERTY",
}

SKIP_LABELS = {"MembershipTotals:", "Add-OnTotals:", "Grand Totals:", "DUAL",
               "MembershipTotal"}


def _find_financial_sheet(wb: openpyxl.Workbook) -> str | None:
    """Pick the Financial Requirements sheet — name has drifted between
    'Financial Requirements' (FY22-24) and 'FinancialRequirementsExcel'
    (FY21). FY25 has neither."""
    for s in wb.sheetnames:
        n = s.lower().replace(" ", "")
        if n.startswith("financialrequirement"):
            return s
    return None


def _parse_financial_requirements(xlsx_path: Path, fiscal_year: int) -> list[dict]:
    """Parse FY21-FY24-shape files. Header row position varies (FY21 has
    headers at row 0, FY23 has a blank row 0 and headers at row 1)."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    sheet = _find_financial_sheet(wb)
    if sheet is None:
        return []
    ws = wb[sheet]
    rows = list(ws.iter_rows(values_only=True))

    # Find first data row by scanning past 'District' header
    header_idx = next(
        (i for i, r in enumerate(rows) if r and any(str(c or "").strip() == "District" for c in r)),
        0,
    )
    data_rows = rows[header_idx + 1:]

    records: list[dict] = []
    current_district_name = None
    for row in data_rows:
        raw_dist = row[0] if len(row) > 0 else None
        raw_cat  = row[1] if len(row) > 1 else None
        raw_adm  = row[2] if len(row) > 2 else None
        raw_wp   = row[3] if len(row) > 3 else None

        if raw_dist and str(raw_dist).strip():
            current_district_name = str(raw_dist).strip()
        if not raw_cat or not str(raw_cat).strip():
            continue

        cat_label = str(raw_cat).strip()
        if cat_label in SKIP_LABELS:
            continue

        canonical = CATEGORY_MAP.get(cat_label)
        if canonical is None:
            print(f"  WARN FY{fiscal_year}: unmapped label {cat_label!r} for {current_district_name!r}")
            continue

        adm_val = float(raw_adm) if raw_adm not in (None, "") else 0.0
        wp_val  = float(raw_wp)  if raw_wp  not in (None, "") else 0.0

        records.append({
            "District_Name_Raw": current_district_name,
            "Fiscal_Year":       fiscal_year,
            "Source_Label":      cat_label,
            "Category":          canonical,
            "ADM":               adm_val,
            "Weighted_Pupils":   wp_val,
        })

    return records


def _parse_fy25_totals(xlsx_path: Path, fiscal_year: int) -> list[dict]:
    """FY25 source has a 'WPU' sheet with two columns: District + total
    WPU. Emit one Category='TOTAL' row per district. ADM is unknowable
    so we set ADM = Weighted_Pupils (i.e., implied weight=1.0)."""
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    if "WPU" not in wb.sheetnames:
        return []
    ws = wb["WPU"]
    rows = list(ws.iter_rows(values_only=True))
    # row 0 is the header
    records = []
    for row in rows[1:]:
        raw_dist = row[0] if len(row) > 0 else None
        raw_wpu  = row[1] if len(row) > 1 else None
        if not raw_dist or raw_wpu in (None, ""):
            continue
        records.append({
            "District_Name_Raw": str(raw_dist).strip(),
            "Fiscal_Year":       fiscal_year,
            "Source_Label":      "FY25 135-day WPU (total only)",
            "Category":          "TOTAL",
            "ADM":               float(raw_wpu),
            "Weighted_Pupils":   float(raw_wpu),
        })
    return records


def _ensure_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS lea_wpu_category (
            District_ID        VARCHAR(4)    NOT NULL,
            Fiscal_Year        INTEGER       NOT NULL,
            Report_Cycle       INTEGER       NOT NULL,
            Category           VARCHAR       NOT NULL,
            ADM                DECIMAL(12,2),
            Weighted_Pupils    DECIMAL(12,2),
            Source_Row_Labels  VARCHAR,
            PRIMARY KEY (District_ID, Fiscal_Year, Report_Cycle, Category)
        )
    """)


def _load_fy(con: duckdb.DuckDBPyConnection, fy: int, xlsx_path: Path,
             dim: pd.DataFrame) -> int:
    if fy == 2025:
        records = _parse_fy25_totals(xlsx_path, fy)
        verify = False  # no Total category in lea_wpu_allocations 135-day for FY25 anyway
    else:
        records = _parse_financial_requirements(xlsx_path, fy)
        verify = True

    if not records:
        print(f"  FY{fy}: no records parsed — skipping")
        return 0

    df = pd.DataFrame(records)
    df["name_norm"] = df["District_Name_Raw"].str.strip()
    merged = df.merge(dim[["District_ID", "name_norm"]], on="name_norm", how="left")

    no_match = merged[merged["District_ID"].isna()]["District_Name_Raw"].unique()
    if len(no_match):
        print(f"  WARN FY{fy}: {len(no_match)} unmatched district names: {list(no_match)[:5]}")

    merged = merged.dropna(subset=["District_ID"]).copy()
    merged["Report_Cycle"] = REPORT_CYCLE

    agg = (
        merged.groupby(["District_ID", "Fiscal_Year", "Report_Cycle", "Category"], sort=False)
        .agg(
            ADM=("ADM", "sum"),
            Weighted_Pupils=("Weighted_Pupils", "sum"),
            Source_Row_Labels=("Source_Label", lambda s: ", ".join(sorted(set(x.strip() for x in s)))),
        )
        .reset_index()
    )
    agg["ADM"] = agg["ADM"].round(2)
    agg["Weighted_Pupils"] = agg["Weighted_Pupils"].round(2)

    if verify:
        alloc = con.execute(
            "SELECT District_ID, Weighted_Pupils AS Alloc_WPU "
            "FROM lea_wpu_allocations "
            "WHERE FY=? AND Report_Cycle=135 AND Category='Total'",
            [fy],
        ).fetchdf()
        if not alloc.empty:
            cat_totals = agg.groupby("District_ID")["Weighted_Pupils"].sum().reset_index()
            cat_totals.columns = ["District_ID", "Sum_WPU"]
            check = cat_totals.merge(alloc, on="District_ID", how="outer")
            check["Delta"] = (check["Sum_WPU"].fillna(0) - check["Alloc_WPU"].fillna(0)).round(2)
            mismatches = check[check["Delta"].abs() > 0.05]
            print(f"  FY{fy}: {len(check) - len(mismatches)}/{len(check)} districts match lea_wpu_allocations within $0.05; {len(mismatches)} larger deltas")

    # Replace this FY only (preserve other FYs)
    con.execute("DELETE FROM lea_wpu_category WHERE Fiscal_Year = ?", [fy])
    con.register("_staging", agg)
    con.execute("""
        INSERT INTO lea_wpu_category
        SELECT District_ID, Fiscal_Year, Report_Cycle, Category,
               ADM, Weighted_Pupils, Source_Row_Labels
        FROM _staging
    """)
    n = con.execute(
        "SELECT COUNT(*) FROM lea_wpu_category WHERE Fiscal_Year = ?", [fy]
    ).fetchone()[0]
    print(f"  FY{fy}: {n} rows · {agg['District_ID'].nunique()} districts · {sorted(agg['Category'].unique())}")
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fy", type=int, action="append", default=None,
                   help="FY to (re)load. Repeat for multiple. Default: all available.")
    args = p.parse_args()

    fys = sorted(args.fy) if args.fy else sorted(FY_SOURCES.keys())

    con = duckdb.connect(str(DB_PATH))
    _ensure_table(con)
    dim = con.execute("SELECT District_ID, long_name FROM dim_district").fetchdf()
    dim["name_norm"] = dim["long_name"].str.strip()

    total = 0
    for fy in fys:
        path = FY_SOURCES.get(fy)
        if not path or not path.exists():
            print(f"  FY{fy}: source file not available — skipping ({path})")
            continue
        total += _load_fy(con, fy, path, dim)

    final = con.execute(
        "SELECT Fiscal_Year, COUNT(*) FROM lea_wpu_category GROUP BY Fiscal_Year ORDER BY Fiscal_Year"
    ).fetchall()
    con.close()
    print(f"\nFinal lea_wpu_category coverage:")
    for fy, n in final:
        print(f"  FY{fy}: {n} rows")


if __name__ == "__main__":
    main()
