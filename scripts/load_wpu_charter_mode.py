#!/usr/bin/env python3
"""
load_wpu_charter_mode.py — load charter authorizer per-mode (B&M vs Virtual)
WPU rows into lea_wpu_allocations.

Source files (45-day cycle, columns vary by year):
  - WPU04524.xlsx (FY24): "Charter Brick WPU" + "Charter Virtual WPU" + ADM cols
  - WPU04526.xlsx (FY26): "B&M WPU" + "VIRT WPU" + "Charter B&M" / "Charter VIRT" ADM

Inserts with Category='Charter_BM' or 'Charter_VIRT', Report_Cycle=45.
Total rows added: 3 authorizers x 2 modes x 2 FYs = 12 (idempotent on PK).
"""

import sys

import duckdb
import openpyxl

DB_PATH = "db/scde.duckdb"
CHARTER_AUTHORIZERS = {"4701", "4801", "4901"}

# (filename, fy, sheet_hint, header_row_idx, name_only)
# - header_row_idx: 0 (FY26 style) or 1 (FY24 style)
# - name_only: True if there's no District ID column; match by name
SOURCES = [
    ("data/uploads/WPU04524.xlsx", 2024, "Student Counts", 1, True),
    ("data/uploads/WPU04526.xlsx", 2026, "FY26 45th Day WPU", 0, False),
]

CHARTER_NAMES = {
    "4701": "SC Public Charter School District",
    "4801": "Charter Institute at Erskine",
    "4901": "Limestone Charter Association",
}

# Header keywords (lowercased) for column detection. Order matters — first match wins.
HEADER_KEYS = {
    "district_id": ["district id"],
    "district_name": ["district"],
    "bm_adm": ["charter b&m", "charter brick adm", "charter brick"],
    "bm_wpu": ["b&m wpu", "charter brick wpu"],
    "virt_adm": ["charter virt adm", "charter virtual adm", "charter virt", "charter virtual"],
    "virt_wpu": ["virt wpu", "charter virtual wpu"],
}


def find_col(headers, keys):
    for j, h in enumerate(headers):
        if h is None:
            continue
        hl = str(h).strip().lower()
        for k in keys:
            if hl == k or hl.startswith(k):
                return j
    return None


def parse_file(path, sheet_hint, header_row_idx, name_only):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet_name = next(
        (s for s in wb.sheetnames if sheet_hint.lower() in s.lower()),
        wb.sheetnames[0],
    )
    ws = wb[sheet_name]
    rows = list(ws.iter_rows(values_only=True))
    headers = rows[header_row_idx]
    cols = {k: find_col(headers, v) for k, v in HEADER_KEYS.items()}
    if name_only:
        # FY24 style — no District ID column; District NAME is in column 0
        cols["district_name"] = 0
        cols["district_id"] = None
    out = []
    for row in rows[header_row_idx + 1:]:
        # Resolve district by id or by name
        did = None
        if cols["district_id"] is not None:
            raw = row[cols["district_id"]]
            if raw is not None:
                did = str(raw).zfill(4)
        else:
            raw = row[cols["district_name"]] if cols["district_name"] is not None else None
            if raw is None:
                continue
            name = str(raw).strip()
            for cid, cname in CHARTER_NAMES.items():
                if cname.lower() in name.lower():
                    did = cid
                    break
        if did not in CHARTER_AUTHORIZERS:
            continue
        out.append({
            "District_ID": did,
            "BM_ADM": row[cols["bm_adm"]] if cols["bm_adm"] is not None else None,
            "BM_WPU": row[cols["bm_wpu"]] if cols["bm_wpu"] is not None else None,
            "VIRT_ADM": row[cols["virt_adm"]] if cols["virt_adm"] is not None else None,
            "VIRT_WPU": row[cols["virt_wpu"]] if cols["virt_wpu"] is not None else None,
        })
    return out


def main():
    con = duckdb.connect(DB_PATH)
    insert_rows = []
    for path, fy, sheet_hint, header_row_idx, name_only in SOURCES:
        print(f"Reading {path} (FY{fy})...")
        rows = parse_file(path, sheet_hint, header_row_idx, name_only)
        for r in rows:
            if r["BM_WPU"] is not None:
                insert_rows.append((
                    r["District_ID"], fy, "Charter_BM", 45,
                    float(r["BM_ADM"]) if r["BM_ADM"] is not None else None,
                    float(r["BM_WPU"]),
                    None, None, None,
                ))
            if r["VIRT_WPU"] is not None:
                insert_rows.append((
                    r["District_ID"], fy, "Charter_VIRT", 45,
                    float(r["VIRT_ADM"]) if r["VIRT_ADM"] is not None else None,
                    float(r["VIRT_WPU"]),
                    None, None, None,
                ))
        print(f"  found {len(rows)} authorizer rows")

    print(f"\nInserting {len(insert_rows)} (Mode, FY) rows...")
    con.execute("BEGIN")
    # Idempotent: clear any prior load first
    con.execute("""
        DELETE FROM lea_wpu_allocations
        WHERE Category IN ('Charter_BM', 'Charter_VIRT')
    """)
    con.executemany(
        """
        INSERT INTO lea_wpu_allocations
          (District_ID, FY, Category, Report_Cycle,
           ADM_135_Day, Weighted_Pupils,
           State_Allocation, Local_Required_Support, Audit_Standard)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        insert_rows,
    )
    con.execute("COMMIT")

    # Verify
    print("\nVerification:")
    for r in con.execute("""
        SELECT a.District_ID, d.District_Name, a.FY, a.Category,
               CAST(a.ADM_135_Day AS BIGINT) AS adm,
               CAST(a.Weighted_Pupils AS BIGINT) AS wpu,
               CAST(a.Weighted_Pupils / NULLIF(a.ADM_135_Day, 0) AS DECIMAL(5,3)) AS wpu_per_adm
        FROM lea_wpu_allocations a
        LEFT JOIN dim_district d USING (District_ID)
        WHERE a.Category IN ('Charter_BM', 'Charter_VIRT')
        ORDER BY a.District_ID, a.FY, a.Category
    """).fetchall():
        print(f"  {r}")
    con.close()


if __name__ == "__main__":
    sys.exit(main())
