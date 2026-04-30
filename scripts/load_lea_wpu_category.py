"""
Load WPU13524.xlsx Financial Requirements sheet into lea_wpu_category.

Category mapping (source label -> canonical Category):
  BASE_K12     : KINDERGARTEN, PRIMARY, ELEMENTARY, HIGH SCHOOL, HB
  SPED         : AUT, EH, EM H, HH, SP H, LD, OH, TM, VH
  RTF          : not present in this file -> NULL rows
  CTE          : CTE
  CHARTER_BM   : B&M  (135-day file: always 0)
  CHARTER_VIRT : VIRT (135-day file: always 0)
  GIFTED       : HIAC
  ACAD_ASSIST  : ACAS
  LEP          : LEP
  POVERTY      : PIP

Rows skipped (not canonical): DUAL, MembershipTotals:, Add-OnTotals:, Grand Totals:
"""

import openpyxl
import duckdb
import pandas as pd
from decimal import Decimal

DB_PATH = r"C:\Users\Dan's Test Device\Finance Dazzle\scde-agent-tree\db\scde.duckdb"
XLSX_PATH = r"C:\Users\Dan's Test Device\Finance Dazzle\scde-agent-tree\data\uploads\WPU13524.xlsx"

FISCAL_YEAR = 2024
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
               "MembershipTotal"}  # truncated label in charter rows

def parse_sheet():
    wb = openpyxl.load_workbook(XLSX_PATH, read_only=True, data_only=True)
    ws = wb["Financial Requirements"]
    rows = list(ws.iter_rows(values_only=True))

    records = []
    current_district_name = None

    for row in rows[1:]:  # skip header
        raw_dist, raw_cat, raw_adm, raw_wp = row[0], row[1], row[2], row[3]

        # Update current district when a name cell is present
        if raw_dist and str(raw_dist).strip():
            current_district_name = str(raw_dist).strip()

        if not raw_cat or not str(raw_cat).strip():
            continue

        cat_label = str(raw_cat).strip()

        if cat_label in SKIP_LABELS:
            continue

        canonical = CATEGORY_MAP.get(cat_label)
        if canonical is None:
            print(f"  WARN: unmapped label {cat_label!r} for {current_district_name!r}")
            continue

        adm_val = float(str(raw_adm)) if raw_adm not in (None, "", "None") else 0.0
        wp_val  = float(str(raw_wp))  if raw_wp  not in (None, "", "None") else 0.0

        records.append({
            "District_Name_Raw": current_district_name,
            "Source_Label":      cat_label,
            "Category":          canonical,
            "ADM":               adm_val,
            "Weighted_Pupils":   wp_val,
        })

    return records

def main():
    print("Parsing WPU13524.xlsx Financial Requirements ...")
    records = parse_sheet()
    print(f"  Raw records parsed: {len(records)}")

    df = pd.DataFrame(records)

    # --- Join to dim_district on long_name (stripped) ---
    con = duckdb.connect(DB_PATH)
    dim = con.execute("SELECT District_ID, long_name FROM dim_district").fetchdf()

    # Normalize join keys
    df["name_norm"] = df["District_Name_Raw"].str.strip()
    dim["name_norm"] = dim["long_name"].str.strip()

    merged = df.merge(dim[["District_ID","name_norm"]], on="name_norm", how="left")
    no_match = merged[merged["District_ID"].isna()]["District_Name_Raw"].unique()
    if len(no_match):
        print(f"  WARN: {len(no_match)} district names unmatched in dim_district:")
        for n in no_match:
            print(f"    {n!r}")

    # Aggregate by (District_ID, Category): sum ADM and Weighted_Pupils, collect source labels
    merged["Fiscal_Year"]    = FISCAL_YEAR
    merged["Report_Cycle"]   = REPORT_CYCLE

    agg = (merged.groupby(["District_ID","Fiscal_Year","Report_Cycle","Category"], sort=False)
           .agg(
               ADM             =("ADM",             "sum"),
               Weighted_Pupils =("Weighted_Pupils",  "sum"),
               Source_Row_Labels=("Source_Label",   lambda s: ", ".join(sorted(set(x.strip() for x in s)))),
           )
           .reset_index()
    )

    # Round to 2dp
    agg["ADM"]             = agg["ADM"].round(2)
    agg["Weighted_Pupils"] = agg["Weighted_Pupils"].round(2)

    print(f"  Aggregated rows: {len(agg)}")
    print(f"  Distinct districts: {agg['District_ID'].nunique()}")
    print(f"  Categories: {sorted(agg['Category'].unique())}")

    # --- Verification against lea_wpu_allocations ---
    alloc = con.execute(
        "SELECT District_ID, Weighted_Pupils AS Alloc_WPU "
        "FROM lea_wpu_allocations "
        "WHERE FY=2024 AND Report_Cycle=135 AND Category='Total'"
    ).fetchdf()

    cat_totals = agg.groupby("District_ID")["Weighted_Pupils"].sum().reset_index()
    cat_totals.columns = ["District_ID","Sum_WPU"]

    check = cat_totals.merge(alloc, on="District_ID", how="outer")
    check["Delta"] = (check["Sum_WPU"] - check["Alloc_WPU"]).round(2)
    mismatches = check[check["Delta"].abs() > 0.05]
    print(f"\nVerification vs lea_wpu_allocations (FY2024 135-day Total):")
    print(f"  Districts matched: {len(check[check['Delta'].abs() <= 0.05])}")
    if len(mismatches):
        print(f"  Mismatches (delta > $0.05): {len(mismatches)}")
        print(mismatches.to_string(index=False))
    else:
        print("  All districts within $0.05 rounding tolerance.")

    # --- Write to DB ---
    print("\nDropping and recreating lea_wpu_category ...")
    con.execute("DROP TABLE IF EXISTS lea_wpu_category")
    con.execute("""
        CREATE TABLE lea_wpu_category (
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

    con.register("_staging", agg)
    con.execute("""
        INSERT INTO lea_wpu_category
        SELECT District_ID, Fiscal_Year, Report_Cycle, Category,
               ADM, Weighted_Pupils, Source_Row_Labels
        FROM _staging
        WHERE District_ID IS NOT NULL
    """)

    final_count = con.execute("SELECT COUNT(*) FROM lea_wpu_category").fetchone()[0]
    print(f"  Rows inserted: {final_count}")

    # Sample check
    print("\nSample (Abbeville 60):")
    print(con.execute(
        "SELECT Category, ADM, Weighted_Pupils, Source_Row_Labels "
        "FROM lea_wpu_category WHERE District_ID='0160' ORDER BY Category"
    ).fetchdf().to_string(index=False))

    con.close()
    print("\nDone.")

if __name__ == "__main__":
    main()
