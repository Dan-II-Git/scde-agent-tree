"""
WPU allocations loader for lea_wpu_allocations.
Loads WPU13521-WPU13525 xlsx files into lea_wpu_allocations.

Schema drift note:
- All 5 files: only District + WPU value. No ADM_135_Day, State_Allocation,
  Local_Required_Support, Audit_Standard present in any file.
  All other numeric columns inserted as NULL; Category = 'Total'.
- FY2024 file has an extra District_ID column (col A) before District Name.
- FY2021 column header: '135-Day Weighted Pupils' (no FY prefix);
  FY confirmed from filename only.
- FY2022-2025: header includes 'FY22'/'FY23'/'FY24'/'FY25' --
  verified against expected FY.

Pre-merger orphans (FY21, FY22):
  Inserted with synthetic District_ID prefixed 'H' (e.g. 'HBAMBER1').
  These are real historical districts that pre-date the current dim_district,
  which was built from headcount files starting FY22. They are NOT silently
  dropped; the synthetic ID makes them queryable.
"""

import openpyxl
import duckdb
import re
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "db", "scde.duckdb")

FILES = [
    (os.path.join(BASE_DIR, "data", "uploads", "WPU13521.xlsx"),  2021, False),
    (os.path.join(BASE_DIR, "data", "uploads", "WPU13522.xlsx"),  2022, False),
    (os.path.join(BASE_DIR, "data", "uploads", "WPU13523.xlsx"),  2023, False),
    (os.path.join(BASE_DIR, "data", "uploads", "WPU13524.xlsx"),  2024, True),
    (os.path.join(BASE_DIR, "data", "uploads", "WPU 13525.xlsx"), 2025, False),
]

# Manual alias: stripped-and-lowercased source name -> District_ID
ALIASES = {
    "scpcsd":                              "4701",
    "erskine":                             "4801",
    "deaf & blind":                        "5207",
    "djj":                                 "5208",
    "palmetto unified":                    "5209",
    "sc public charter school district*":  "4701",
    "charter institute at erskine*":       "4801",
    "limestone charter association*":      "4901",
}

# Substrings that identify aggregate/summary rows -- skip these
SKIP_PATTERNS = [
    "state totals",
    " totals",
    "overall state-wide",
    "special school district totals",
    "special schools totals",
    "traditional & charter district totals",
]

# Exact names that are summary rows (catches bare "Total" in FY23)
SKIP_EXACT = {"total", "state total"}


def is_summary_row(name_lower):
    if name_lower.strip() in SKIP_EXACT:
        return True
    return any(p in name_lower for p in SKIP_PATTERNS)


def extract_fy_from_header(header_str):
    """Pull two-digit FY from strings like 'FY22 135-Day Weighted Pupils'."""
    m = re.search(r"FY(\d{2})", str(header_str), re.IGNORECASE)
    if m:
        yy = int(m.group(1))
        return 2000 + yy
    return None


def make_orphan_id(name):
    """Create a stable unique synthetic District_ID for pre-merger districts.
    Format: 'H' + alphanumeric chars from name, up to 15 chars total.
    e.g. 'Clarendon 01' -> 'HCLARENDON01', 'Clarendon 02' -> 'HCLARENDON02'
    """
    code = re.sub(r"[^a-zA-Z0-9]", "", name)[:14].upper()
    return f"H{code}"


con = duckdb.connect(DB_PATH)

# Build normalized_name -> District_ID lookup from dim_district
dim_by_norm = {
    r[0]: r[1]
    for r in con.execute(
        "SELECT normalized_name, District_ID FROM dim_district"
    ).fetchall()
}

dim_ids = set(
    r[0] for r in con.execute("SELECT District_ID FROM dim_district").fetchall()
)

all_rows = []   # (district_id_final, stripped_name, fy, wpu_float)
report = {}

for fpath, expected_fy, has_id_col in FILES:
    wb = openpyxl.load_workbook(fpath, data_only=True)
    ws = wb["WPU"]

    rows_iter = list(ws.iter_rows(values_only=True))
    header = rows_iter[0]

    wpu_col_header = header[2] if has_id_col else header[1]
    detected_fy = extract_fy_from_header(wpu_col_header)
    if detected_fy is None:
        detected_fy = expected_fy
        fy_source = "filename"
    else:
        fy_source = "header"

    fy_ok = detected_fy == expected_fy
    fy_tag = "OK" if fy_ok else f"MISMATCH header={detected_fy} expected={expected_fy}"
    print(
        f"FY{expected_fy} ({os.path.basename(fpath)}): "
        f"wpu_header='{wpu_col_header}' | FY={fy_tag} via {fy_source}"
    )

    inserted_this_fy = 0
    skipped_summary = []
    orphans = []
    barnwell_rows = []

    for row in rows_iter[1:]:
        if has_id_col:
            src_id_raw, name_raw, wpu_val = row[0], row[1], row[2]
        else:
            name_raw, wpu_val = row[0], row[1]
            src_id_raw = None

        if name_raw is None:
            continue

        stripped = str(name_raw).strip()
        norm = stripped.lower()

        if is_summary_row(norm):
            skipped_summary.append(stripped)
            continue

        if wpu_val is None:
            continue

        wpu_float = float(wpu_val)

        # --- Resolve District_ID ---
        district_id = None

        if norm in dim_by_norm:
            district_id = dim_by_norm[norm]
        elif norm in ALIASES:
            district_id = ALIASES[norm]
        elif src_id_raw is not None and str(src_id_raw).zfill(4) in dim_ids:
            district_id = str(src_id_raw).zfill(4)
        else:
            # Historical pre-merger district not in current dim_district
            orphans.append((stripped, wpu_float))
            district_id = make_orphan_id(stripped)

        if "barnwell" in norm:
            barnwell_rows.append((stripped, district_id, wpu_float))

        all_rows.append((district_id, stripped, expected_fy, wpu_float))
        inserted_this_fy += 1

    report[expected_fy] = {
        "inserted": inserted_this_fy,
        "skipped_summary": skipped_summary,
        "orphans": orphans,
        "barnwell": barnwell_rows,
    }
    print(f"  => district rows={inserted_this_fy}, "
          f"summary rows skipped={len(skipped_summary)}, "
          f"orphans(synthetic ID)={len(orphans)}")
    if orphans:
        for name, wpu in orphans:
            print(f"     ORPHAN '{name}' -> ID='{make_orphan_id(name)}' wpu={wpu:.2f}")
    if barnwell_rows:
        for name, did, wpu in barnwell_rows:
            print(f"     BARNWELL '{name}' -> District_ID='{did}' wpu={wpu:.3f}")
    print()

# --- Insert ---
print("Clearing any existing rows and inserting...")
con.execute("DELETE FROM lea_wpu_allocations")

insert_sql = """
INSERT INTO lea_wpu_allocations
    (District_ID, FY, Category, Weighted_Pupils,
     ADM_135_Day, State_Allocation, Local_Required_Support, Audit_Standard)
VALUES (?, ?, 'Total', ?, NULL, NULL, NULL, NULL)
"""

total_inserted = 0
orphan_insert_count = 0

for district_id, stripped, fy, wpu_float in all_rows:
    if district_id.startswith("H"):
        orphan_insert_count += 1
    con.execute(insert_sql, [district_id, fy, round(wpu_float, 6)])
    total_inserted += 1

con.commit()

print(f"Insert complete.")
print(f"  Total rows inserted: {total_inserted}")
print(f"  Of which synthetic-ID orphans: {orphan_insert_count}")
print()

# --- Validation queries ---
print("=== VALIDATION ===")

# Per-FY row counts
print("Per-FY row counts:")
fy_counts = con.execute(
    "SELECT FY, COUNT(*) as n FROM lea_wpu_allocations GROUP BY FY ORDER BY FY"
).fetchall()
for fy, n in fy_counts:
    print(f"  FY{fy}: {n} rows")

total_rows = con.execute("SELECT COUNT(*) FROM lea_wpu_allocations").fetchone()[0]
print(f"  TOTAL: {total_rows} rows")
print()

# Check for zero or negative WPU
zero_neg = con.execute(
    "SELECT District_ID, FY, Weighted_Pupils "
    "FROM lea_wpu_allocations WHERE Weighted_Pupils <= 0"
).fetchall()
if zero_neg:
    print(f"WARNING: {len(zero_neg)} rows with Weighted_Pupils <= 0:")
    for r in zero_neg:
        print(f"  {r}")
else:
    print("Zero/negative WPU check: PASS (none found)")

# Aiken FY25 spot-check
aiken_fy25 = con.execute(
    "SELECT Weighted_Pupils FROM lea_wpu_allocations "
    "WHERE District_ID = '0201' AND FY = 2025"
).fetchone()
if aiken_fy25:
    val = float(aiken_fy25[0])
    status = "PASS" if val > 30000 else "FAIL"
    print(f"Aiken 01 FY25 WPU spot-check: {val:,.3f} [{status} -- expected >30,000]")
else:
    print("Aiken 01 FY25 WPU spot-check: NOT FOUND")
print()

# Districts present in some FYs but not others (dim-mapped only)
print("Districts present in some FYs but not all 5:")
coverage = con.execute("""
    SELECT District_ID, COUNT(DISTINCT FY) as fy_count,
           STRING_AGG(CAST(FY AS VARCHAR), ',' ORDER BY FY) as fys
    FROM lea_wpu_allocations
    WHERE NOT District_ID LIKE 'H%'
    GROUP BY District_ID
    HAVING COUNT(DISTINCT FY) < 5
    ORDER BY District_ID
""").fetchall()
for row in coverage:
    name_row = con.execute(
        "SELECT District_Name FROM dim_district WHERE District_ID = ?", [row[0]]
    ).fetchone()
    name = name_row[0] if name_row else row[0]
    print(f"  {row[0]} {name}: {row[1]} FYs present ({row[2]})")
print()

# Synthetic-ID orphan summary
orphan_rows = con.execute(
    "SELECT District_ID, FY, Weighted_Pupils "
    "FROM lea_wpu_allocations WHERE District_ID LIKE 'H%' "
    "ORDER BY FY, District_ID"
).fetchall()
if orphan_rows:
    print(f"Synthetic-ID orphan rows ({len(orphan_rows)} total):")
    for r in orphan_rows:
        print(f"  {r[0]} | FY{r[1]} | WPU={float(r[2]):.2f}")
else:
    print("No synthetic-ID orphan rows.")

con.close()
print()
print("Done.")
