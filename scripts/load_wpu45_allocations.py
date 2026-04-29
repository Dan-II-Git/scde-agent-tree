"""
load_wpu45_allocations.py
Load 5 WPU 45-day files (FY22-FY26) into lea_wpu_allocations.

Three file shapes:
  Shape A (FY22):        Sheet=WPU,  2-col: District | FY22 45-Day Weighted Pupils
  Shape B (FY23):        Sheet varies, 6-col wide with TOTAL WEIGHT in col F (index 5), data rows=4+
  Shape C (FY24):        Sheet=FY24 Student Counts, 38-col, Total WPU = col 37 (index 37), data rows=3+
  Shape D (FY25):        Sheet=FY25 45th day WPU, 3-col: District ID | District | 45th Day Weighted Pupils
  Shape E (FY26):        Sheet=FY26 45th Day WPU, 41-col, Total WPU = col 40 (index 40), data rows=2+
"""

import sys
import os
import re
import duckdb
import openpyxl
from decimal import Decimal

DB_PATH = r"C:\Users\Dan's Test Device\Finance Dazzle\scde-agent-tree\db\scde.duckdb"

# ── helpers ────────────────────────────────────────────────────────────────────

def clean_name(s):
    """Strip leading/trailing whitespace and normalise internal spaces."""
    if s is None:
        return None
    # collapse multiple spaces (handles 'AIKEN     01')
    return re.sub(r'\s+', ' ', str(s).strip())


def build_name_lookup(con):
    """Return dict of normalised_name -> District_ID from dim_district."""
    rows = con.execute(
        "SELECT District_ID, District_Name, normalized_name FROM dim_district"
    ).fetchall()
    lkp = {}
    for did, dname, norm in rows:
        lkp[norm.lower()] = did
        # also index by the raw District_Name stripped
        lkp[dname.strip().lower()] = did

    # ── Extra aliases for name-variant entries that appear in 45-day files ──────
    # These are one-to-one mappings where the file uses a shortened or
    # non-standard name that doesn't match any dim_district entry after
    # normalisation.
    ALIASES = {
        # FY22/23 charter / special school short names
        'scpcsd':                              '4701',
        'sc public charter school district':   '4701',
        'erskine':                             '4801',
        'charter institute at erskine':        '4801',
        'charter institute of erskine':        '4801',
        'limestone charter':                   '4901',
        'limestone charter association':       '4901',
        'palmetto unified':                    '5209',
        'deaf & blind':                        '5207',
        'sc school for the deaf and the blind': '5207',
        'djj':                                 '5208',
        'department of juvenile justice':      '5208',
        # FY23 name-only districts — compressed form (no numeric suffix)
        'dillon 4':                            '1704',
        'hampton':                             '2503',   # only Hampton 03 exists
        'marion':                              '3410',   # only Marion 10 exists
        'marlboro 10':                         '3501',   # Marlboro 01 mislabelled
        'marlboro':                            '3501',
        'orangeburg 9':                        '3809',
        'orangeburg09':                        '3809',
        'sumter':                              '4301',   # only Sumter 01 exists
        'union':                               '4401',
        'barnwell':                            '0601',
    }
    for alias, did in ALIASES.items():
        lkp.setdefault(alias.lower(), did)

    return lkp


def normalise_for_lookup(raw_name):
    """Apply the same normalisation as build_name_lookup."""
    if raw_name is None:
        return None
    s = clean_name(raw_name).lower()
    # collapse spaces again just in case
    return re.sub(r'\s+', ' ', s)


def lookup_district(raw_name, name_lkp, synthetic_map):
    """
    Resolve a raw name string to a District_ID.
    Returns (district_id, was_synthetic: bool).
    Raises ValueError if unresolvable and not a footer row.
    """
    if raw_name is None:
        return None, False
    key = normalise_for_lookup(raw_name)
    if key in name_lkp:
        return name_lkp[key], False
    # maybe the synthetic map already covers it
    if key in synthetic_map:
        return synthetic_map[key], True
    return None, False   # caller decides


# footer / subtotal row names to skip
SKIP_NAMES = {
    'local district', 'total', 'state totals', 'total traditional',
    'total charter', 'total special schools', 'total statewide',
    'charter', 'special schools',
}

def is_footer(raw):
    if raw is None:
        return True
    k = normalise_for_lookup(raw)
    if k in SKIP_NAMES:
        return True
    # catch generic 'total *' patterns
    if k.startswith('total '):
        return True
    return False


# ── per-file loaders ────────────────────────────────────────────────────────────

def load_shape_a(path, fy, name_lkp, synthetic_map):
    """FY22: 2-column, sheet WPU."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb['WPU']
    rows_out = []
    orphans = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        raw_name, wpu_val = row[0], row[1]
        if raw_name is None or is_footer(raw_name):
            continue
        if wpu_val is None:
            continue
        did, synth = lookup_district(raw_name, name_lkp, synthetic_map)
        if did is None:
            orphans.append(clean_name(raw_name))
            continue
        rows_out.append((did, fy, 'Total', 45, None, float(wpu_val),
                         None, None, None))
    wb.close()
    return rows_out, orphans


def load_shape_b(path, fy, name_lkp, synthetic_map):
    """FY23: 6-column, TOTAL WEIGHT in col index 5. Data starts row 4."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active   # only one sheet
    rows_out = []
    orphans = []
    for row in ws.iter_rows(min_row=4, values_only=True):
        raw_name, wpu_val = row[0], row[5]
        if raw_name is None or is_footer(raw_name):
            continue
        if wpu_val is None:
            continue
        did, synth = lookup_district(raw_name, name_lkp, synthetic_map)
        if did is None:
            orphans.append(clean_name(raw_name))
            continue
        rows_out.append((did, fy, 'Total', 45, None, float(wpu_val),
                         None, None, None))
    wb.close()
    return rows_out, orphans


def load_shape_c(path, fy, name_lkp, synthetic_map):
    """FY24: 38-column; data starts row 3; District name col 0, Total WPU col 37."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_out = []
    orphans = []
    for row in ws.iter_rows(min_row=3, values_only=True):
        raw_name, wpu_val = row[0], row[37]
        if raw_name is None or is_footer(raw_name):
            continue
        if wpu_val is None:
            continue
        did, synth = lookup_district(raw_name, name_lkp, synthetic_map)
        if did is None:
            orphans.append(clean_name(raw_name))
            continue
        rows_out.append((did, fy, 'Total', 45, None, float(wpu_val),
                         None, None, None))
    wb.close()
    return rows_out, orphans


def load_shape_d(path, fy, name_lkp, synthetic_map):
    """FY25: 3-column with District ID in col 0."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_out = []
    orphans = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        did_raw, raw_name, wpu_val = row[0], row[1], row[2]
        if did_raw is None and raw_name is None:
            continue
        # Only call is_footer on did_raw if it is non-None (None did_raw = name-only row,
        # e.g. special schools in FY25 that lack a numeric ID column)
        if is_footer(raw_name) or (did_raw is not None and is_footer(did_raw)):
            continue
        if wpu_val is None:
            continue
        # Prefer the explicit District_ID column
        if did_raw is not None:
            did = str(did_raw).strip().zfill(4)
            # verify it exists in dim_district
            if did not in {v for v in name_lkp.values()}:
                # fall back to name lookup
                did2, synth = lookup_district(raw_name, name_lkp, synthetic_map)
                if did2 is None:
                    orphans.append(f"{did_raw} / {clean_name(raw_name)}")
                    continue
                did = did2
        else:
            did2, synth = lookup_district(raw_name, name_lkp, synthetic_map)
            if did2 is None:
                orphans.append(clean_name(raw_name))
                continue
            did = did2
        rows_out.append((did, fy, 'Total', 45, None, float(wpu_val),
                         None, None, None))
    wb.close()
    return rows_out, orphans


def load_shape_e(path, fy, name_lkp, synthetic_map):
    """FY26: 41-column; District ID col 0; Total WPU col 40; data starts row 2."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb['FY26 45th Day WPU']
    rows_out = []
    orphans = []
    all_district_ids = {v for v in name_lkp.values()}
    for row in ws.iter_rows(min_row=2, values_only=True):
        did_raw, raw_name, wpu_val = row[0], row[1], row[40]
        if did_raw is None and raw_name is None:
            continue
        # skip section-header rows like 'CHARTER', 'Special Schools'
        if is_footer(did_raw) or is_footer(raw_name):
            continue
        if wpu_val is None:
            continue
        # district ID may be numeric (special schools)
        if did_raw is not None:
            did = str(int(did_raw)).zfill(4) if isinstance(did_raw, (int, float)) else str(did_raw).strip().zfill(4)
            if did not in all_district_ids:
                did2, synth = lookup_district(raw_name, name_lkp, synthetic_map)
                if did2 is None:
                    orphans.append(f"{did_raw} / {clean_name(raw_name)}")
                    continue
                did = did2
        else:
            did2, synth = lookup_district(raw_name, name_lkp, synthetic_map)
            if did2 is None:
                orphans.append(clean_name(raw_name))
                continue
            did = did2
        rows_out.append((did, fy, 'Total', 45, None, float(wpu_val),
                         None, None, None))
    wb.close()
    return rows_out, orphans


# ── main ────────────────────────────────────────────────────────────────────────

def main():
    base = r"C:\Users\Dan's Test Device\Finance Dazzle\scde-agent-tree\data\uploads"

    files = [
        (os.path.join(base, 'WPU04522.xlsx'), 2022, 'A'),
        (os.path.join(base, 'WPU04523.xlsx'), 2023, 'B'),
        (os.path.join(base, 'WPU04524.xlsx'), 2024, 'C'),
        (os.path.join(base, 'WPU04525.xlsx'), 2025, 'D'),
        (os.path.join(base, 'WPU04526.xlsx'), 2026, 'E'),
    ]

    loaders = {'A': load_shape_a, 'B': load_shape_b, 'C': load_shape_c,
               'D': load_shape_d, 'E': load_shape_e}

    con = duckdb.connect(DB_PATH)
    name_lkp = build_name_lookup(con)
    # Build set of valid IDs for fast membership test
    valid_ids = set(name_lkp.values())

    # synthetic_map: keyed by normalised name -> synthetic District_ID
    # Pre-merger entities that appear in FY22 and FY23 45-day files use the
    # same H-prefix IDs as the 135-day loader.  These districts do not appear
    # in dim_district; we store them directly in lea_wpu_allocations.
    synthetic_map = {
        # Bamberg pre-merger (merged into Bamberg 03 by FY24)
        'bamberg 01':  'HBAMBERG01',
        'bamberg01':   'HBAMBERG01',
        'bamberg 02':  'HBAMBERG02',
        'bamberg02':   'HBAMBERG02',
        # Barnwell pre-merger (19 and 29 merged into 01 by FY25)
        'barnwell 19': 'HBARNWELL19',
        'barnwell19':  'HBARNWELL19',
        'barnwell 29': 'HBARNWELL29',
        'barnwell29':  'HBARNWELL29',
        # Clarendon pre-merger (02/03/04 merged into 06 by FY24)
        'clarendon 02': 'HCLARENDON02',
        'clarendon02':  'HCLARENDON02',
        'clarendon 04': 'HCLARENDON04',
        'clarendon04':  'HCLARENDON04',
        # Florence 04 (merged into Florence 03 by FY24)
        'florence 04':  'HFLORENCE04',
        'florence04':   'HFLORENCE04',
    }

    total_inserted = 0
    per_fy_counts = {}
    all_orphans = {}
    all_rows = []

    for path, fy, shape in files:
        loader = loaders[shape]
        rows, orphans = loader(path, fy, name_lkp, synthetic_map)
        per_fy_counts[fy] = len(rows)
        all_orphans[fy] = orphans
        all_rows.extend(rows)
        print(f"FY{fy} ({shape}): {len(rows)} data rows parsed, "
              f"{len(orphans)} orphan(s): {orphans}")

    # Insert into DB
    print("\nInserting into lea_wpu_allocations ...")
    inserted = 0
    skipped_dup = 0
    skipped_zero = 0
    zero_flag_rows = []

    for r in all_rows:
        did, fy, cat, rc, adm, wpu, sa, lrs, aus_ = r
        if wpu is None or wpu == 0:
            skipped_zero += 1
            zero_flag_rows.append(r)
            continue
        if wpu < 0:
            zero_flag_rows.append(r)   # flag negatives too
        try:
            con.execute("""
                INSERT INTO lea_wpu_allocations
                  (District_ID, FY, Category, Report_Cycle,
                   ADM_135_Day, Weighted_Pupils,
                   State_Allocation, Local_Required_Support, Audit_Standard)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [did, fy, cat, rc, adm, wpu, sa, lrs, aus_])
            inserted += 1
        except duckdb.ConstraintException:
            skipped_dup += 1
            print(f"  DUP skipped: ({did}, {fy}, {cat}, {rc})")

    con.close()
    total_inserted = inserted

    print(f"\n=== LOAD SUMMARY ===")
    print(f"Rows inserted:       {inserted}")
    print(f"Duplicates skipped:  {skipped_dup}")
    print(f"Zero/null WPU skipped: {skipped_zero}")
    print()
    for fy, cnt in sorted(per_fy_counts.items()):
        print(f"  FY{fy}: {cnt} rows parsed")
    print()
    for fy, orph in sorted(all_orphans.items()):
        if orph:
            print(f"  FY{fy} orphans: {orph}")
    if zero_flag_rows:
        print(f"\n  WARNING: {len(zero_flag_rows)} zero/negative WPU rows flagged:")
        for r in zero_flag_rows:
            print(f"    {r}")


    # Post-load validation
    print("\n=== POST-LOAD VALIDATION ===")
    con2 = duckdb.connect(DB_PATH)

    total_rows = con2.execute("SELECT COUNT(*) FROM lea_wpu_allocations").fetchone()[0]
    print(f"Total rows in table: {total_rows}  (expected ~800)")

    breakdown = con2.execute("""
        SELECT Report_Cycle, FY, COUNT(*) as cnt
        FROM lea_wpu_allocations
        GROUP BY Report_Cycle, FY
        ORDER BY Report_Cycle, FY
    """).fetchdf()
    print("\nBreakdown by Report_Cycle x FY:")
    print(breakdown.to_string(index=False))

    # Spot-check: Aiken FY25 45-day
    aiken = con2.execute("""
        SELECT District_ID, FY, Report_Cycle, Weighted_Pupils
        FROM lea_wpu_allocations
        WHERE District_ID = '0201' AND FY = 2025 AND Report_Cycle = 45
    """).fetchone()
    print(f"\nSpot-check Aiken 01 FY25 45-day: {aiken}")
    if aiken:
        wp = float(aiken[3])
        if abs(wp - 35672) < 100:
            print(f"  OK: {wp:.2f} is within $100 of expected ~35,672")
        else:
            print(f"  WARNING: {wp:.2f} deviates from expected ~35,672")

    # Verify all 45-day rows have Report_Cycle=45
    bad_rc = con2.execute(
        "SELECT COUNT(*) FROM lea_wpu_allocations WHERE Report_Cycle = 45 AND Category != 'Total'"
    ).fetchone()[0]
    print(f"\nRows with Report_Cycle=45 but Category != 'Total': {bad_rc}  (expected 0)")

    # Verify 135-day rows are untouched
    orig_135 = con2.execute(
        "SELECT COUNT(*) FROM lea_wpu_allocations WHERE Report_Cycle = 135"
    ).fetchone()[0]
    print(f"135-day rows still present: {orig_135}  (expected 399)")

    con2.close()
    print("\nDone.")


if __name__ == '__main__':
    main()
