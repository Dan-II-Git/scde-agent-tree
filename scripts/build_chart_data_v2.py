"""
Build per-district FY2025 revenue data for compare-chart report.
Local bucket assignment uses revenue code prefix ranges per chart spec:
  - SAC Required (11xx)  : Ad valorem taxes levied/assessed by LEA
  - Additional (12xx, 19xx not in District Services)  : non-LEA gov units + other local
  - District Services (13xx, 14xx, 16xx, 17xx, 1910, 1930, 1931, 1992) : fee-for-service revenue
  - Investments (15xx) : earnings on investments
"""
import duckdb
from decimal import Decimal
import json
import sys

con = duckdb.connect('db/scde.duckdb', read_only=True)

# --- Get district names ---
dist_names = {r[0]: r[1] for r in con.execute(
    "SELECT District_ID, District_Name FROM dim_district ORDER BY District_ID"
).fetchall()}

# --- 135-day Membership ADM (FY2025, BASE_K12+SPED+CTE; Barnwell consolidated) ---
adm_dict = {r[0]: int(round(float(r[1]))) for r in con.execute("""
    SELECT
      CASE WHEN District_ID IN ('0645','0648') THEN '0601' ELSE District_ID END AS District_ID,
      SUM(ADM) AS adm
    FROM lea_wpu_category
    WHERE Fiscal_Year = 2025 AND Report_Cycle = 135
      AND Category IN ('BASE_K12','SPED','CTE')
      AND District_ID NOT IN (
          SELECT District_ID FROM lookup_district_exclusions
          WHERE Exclude_Scope = 'all_reports'
            AND (Effective_FY_From IS NULL OR Effective_FY_From <= 2025)
            AND (Effective_FY_To   IS NULL OR Effective_FY_To   >= 2025)
      )
    GROUP BY 1
""").fetchall() if r[1] is not None}

# --- SCEIS State+Federal with Barnwell merge (0645+0648 -> 0601) ---
sceis_raw = con.execute("""
    SELECT
        CASE WHEN District_ID IN ('0645','0648') THEN '0601' ELSE District_ID END AS dist_id,
        Funding_Stream,
        SUM(Amount) as total
    FROM vw_sceis_fi_payments_classified
    WHERE Fiscal_Year = 2025
    AND Funding_Stream IN ('State','Federal')
    AND District_ID NOT IN (
        SELECT District_ID FROM lookup_district_exclusions
        WHERE Exclude_Scope = 'all_reports'
          AND (Effective_FY_From IS NULL OR Effective_FY_From <= 2025)
          AND (Effective_FY_To   IS NULL OR Effective_FY_To   >= 2025)
    )
    AND District_ID IS NOT NULL
    GROUP BY 1, Funding_Stream
""").fetchall()

sceis_dict = {}
for dist, stream, amt in sceis_raw:
    if dist not in sceis_dict:
        sceis_dict[dist] = {'State': 0.0, 'Federal': 0.0}
    sceis_dict[dist][stream] = float(amt)

# --- LEA revenue at leaf level (per Revenue_Code) ---
# We apply our own bucket assignment based on code prefix ranges
lea_leaf = con.execute("""
    SELECT
        CASE WHEN lr.District_ID IN ('0645','0648') THEN '0601' ELSE lr.District_ID END AS dist_id,
        lr.Revenue_Code,
        cdfs.Stream_Type,
        SUM(lr.Amount) as total
    FROM lea_revenues lr
    LEFT JOIN code_district_funding_streams cdfs ON lr.Revenue_Code = cdfs.REV_Code
    WHERE lr.FY = 2025 AND lr.Reported_Flag = TRUE
    AND lr.District_ID NOT IN (
        SELECT District_ID FROM lookup_district_exclusions
        WHERE Exclude_Scope = 'all_reports'
          AND (Effective_FY_From IS NULL OR Effective_FY_From <= 2025)
          AND (Effective_FY_To   IS NULL OR Effective_FY_To   >= 2025)
    )
    GROUP BY 1, lr.Revenue_Code, cdfs.Stream_Type
""").fetchall()

# District-services code set for exact matching on 4-digit codes
DIST_SVC_EXACT = {'1910', '1930', '1931', '1992'}

def assign_local_bucket(rev_code):
    """Return bucket name for a local revenue code."""
    c = str(rev_code).strip()
    # 11xx — SAC Required (taxes levied by LEA)
    if c.startswith('11') and len(c) == 4:
        return 'local_sac_req'
    # 12xx — Additional (non-LEA gov unit taxes)
    if c.startswith('12') and len(c) == 4:
        return 'local_additional'
    # 13xx, 14xx, 16xx, 17xx — District services (tuition, transport, food, activities)
    if (c.startswith('13') or c.startswith('14') or c.startswith('16') or c.startswith('17')) and len(c) == 4:
        return 'local_dist_svc'
    # 15xx — Investments
    if c.startswith('15') and len(c) == 4:
        return 'local_investments'
    # 1910, 1930, 1931, 1992 — District services (rentals, SNT, Medicaid, canteen)
    if c in DIST_SVC_EXACT:
        return 'local_dist_svc'
    # Anything else in 1xxx Local — Additional
    if c.startswith('1') and len(c) == 4:
        return 'local_additional'
    # Summary roll-up codes (e.g., '1000', '1100', '1300' etc. — 4-digit, already covered)
    # Non-local codes that leaked in — ignore here
    return None

lea_dict = {}
for dist, rev_code, stream_type, amt in lea_leaf:
    if dist not in lea_dict:
        lea_dict[dist] = {
            'local_sac_req': 0.0,
            'local_dist_svc': 0.0,
            'local_investments': 0.0,
            'local_additional': 0.0,
            'state': 0.0,
            'federal': 0.0,
            'other_sources': 0.0,
        }
    v = float(amt) if amt else 0.0
    if stream_type == 'Local':
        bucket = assign_local_bucket(rev_code)
        if bucket:
            lea_dict[dist][bucket] += v
        # else: uncategorized local code — log but include in additional to not lose it
    elif stream_type == 'State':
        lea_dict[dist]['state'] += v
    elif stream_type == 'Federal':
        lea_dict[dist]['federal'] += v
    elif stream_type is None:
        # Revenue codes not mapped in code_district_funding_streams
        # Check if it's a 5xxx (Other Sources / bond proceeds / transfers) code
        c = str(rev_code).strip()
        if c.startswith('5'):
            lea_dict[dist]['other_sources'] += v
        # else silently skip (should be rare)

# --- Reported districts ---
reported_set = set(r[0] for r in con.execute("""
    SELECT DISTINCT
        CASE WHEN District_ID IN ('0645','0648') THEN '0601' ELSE District_ID END AS dist_id
    FROM lea_revenues
    WHERE FY = 2025 AND Reported_Flag = TRUE
    AND District_ID NOT IN (
        SELECT District_ID FROM lookup_district_exclusions
        WHERE Exclude_Scope = 'all_reports'
          AND (Effective_FY_From IS NULL OR Effective_FY_From <= 2025)
          AND (Effective_FY_To   IS NULL OR Effective_FY_To   >= 2025)
    )
""").fetchall())

# --- Excluded districts for footer annotation ---
excluded_sceis = con.execute("""
    SELECT
        e.District_ID,
        d.District_Name,
        SUM(CASE WHEN v.Funding_Stream='State' THEN v.Amount ELSE 0 END) as state_total,
        SUM(CASE WHEN v.Funding_Stream='Federal' THEN v.Amount ELSE 0 END) as fed_total
    FROM lookup_district_exclusions e
    LEFT JOIN dim_district d ON e.District_ID = d.District_ID
    LEFT JOIN vw_sceis_fi_payments_classified v
        ON v.District_ID = e.District_ID AND v.Fiscal_Year = 2025
        AND v.Funding_Stream IN ('State','Federal')
    WHERE e.Exclude_Scope = 'all_reports'
      AND (e.Effective_FY_From IS NULL OR e.Effective_FY_From <= 2025)
      AND (e.Effective_FY_To   IS NULL OR e.Effective_FY_To   >= 2025)
    GROUP BY e.District_ID, d.District_Name
    ORDER BY e.District_ID
""").fetchall()

con.close()

# --- Build per-district rows ---
all_dists = sorted(set(sceis_dict.keys()) | set(adm_dict.keys()))
print(f"Total districts for report: {len(all_dists)}", file=sys.stderr)

rows = []
for d in all_dists:
    name = dist_names.get(d, 'District ' + d)
    adm = adm_dict.get(d)
    is_reported = d in reported_set
    sc = sceis_dict.get(d, {})
    la = lea_dict.get(d, {})

    state_raw = sc.get('State', 0.0)
    fed_raw = sc.get('Federal', 0.0)
    lea_state_raw = la.get('state', 0.0)

    if adm and adm > 0:
        state_pp = round(state_raw / adm)
        fed_pp = round(fed_raw / adm)
        if is_reported:
            sac_pp       = round(la.get('local_sac_req', 0.0)    / adm)
            additional_pp= round(la.get('local_additional', 0.0) / adm)
            dist_svc_pp  = round(la.get('local_dist_svc', 0.0)   / adm)
            invest_pp    = round(la.get('local_investments', 0.0) / adm)
            other_pp     = round(la.get('other_sources', 0.0)     / adm)
        else:
            sac_pp = additional_pp = dist_svc_pp = invest_pp = other_pp = 0
    else:
        state_pp = fed_pp = sac_pp = additional_pp = dist_svc_pp = invest_pp = other_pp = None

    grand_total = (state_pp or 0) + (fed_pp or 0) + sac_pp + additional_pp + dist_svc_pp + invest_pp

    state_variance = round(state_raw - lea_state_raw)

    rows.append({
        'name': name,
        'id': d,
        'adm': adm,
        'is_reported': is_reported,
        'state_total_sceis':  state_pp,
        'local_sac_req':      sac_pp,
        'local_additional':   additional_pp,
        'local_dist_svc':     dist_svc_pp,
        'local_investments':  invest_pp,
        'federal_total_sceis':fed_pp,
        'grand_total_pp':     grand_total,
        'other_sources_pp':   other_pp,
        'state_sceis_raw':    round(state_raw),
        'federal_sceis_raw':  round(fed_raw),
        'lea_state_raw':      round(lea_state_raw),
        'state_variance_raw': state_variance,
    })

# --- Statewide weighted average (all districts with headcount for SCEIS; reported only for local) ---
total_adm    = sum(r['adm'] for r in rows if r['adm'])
total_state = sum(r['state_sceis_raw'] for r in rows if r['adm'])
total_fed   = sum(r['federal_sceis_raw'] for r in rows if r['adm'])

rep_adm  = sum(r['adm'] for r in rows if r['adm'] and r['is_reported'])
rep_sac = sum((r['local_sac_req'] or 0)    * r['adm'] for r in rows if r['adm'] and r['is_reported'])
rep_add = sum((r['local_additional'] or 0) * r['adm'] for r in rows if r['adm'] and r['is_reported'])
rep_svc = sum((r['local_dist_svc'] or 0)   * r['adm'] for r in rows if r['adm'] and r['is_reported'])
rep_inv = sum((r['local_investments'] or 0) * r['adm'] for r in rows if r['adm'] and r['is_reported'])

sc_state_pp = round(total_state / total_adm) if total_adm else 0
sc_fed_pp   = round(total_fed   / total_adm) if total_adm else 0
sc_sac_pp   = round(rep_sac / rep_adm) if rep_adm else 0
sc_add_pp   = round(rep_add / rep_adm) if rep_adm else 0
sc_svc_pp   = round(rep_svc / rep_adm) if rep_adm else 0
sc_inv_pp   = round(rep_inv / rep_adm) if rep_adm else 0
sc_grand    = sc_state_pp + sc_fed_pp + sc_sac_pp + sc_add_pp + sc_svc_pp + sc_inv_pp

reporting_count = sum(1 for r in rows if r['is_reported'])
print(f"Reporting: {reporting_count} of {len(rows)} districts", file=sys.stderr)
print(f"Total HC: {total_adm:,}  |  Reporting HC: {rep_adm:,}", file=sys.stderr)
print(f"SC weighted avg: State=${sc_state_pp:,} SAC=${sc_sac_pp:,} Add=${sc_add_pp:,} Svc=${sc_svc_pp:,} Inv=${sc_inv_pp:,} Fed=${sc_fed_pp:,} Grand=${sc_grand:,}", file=sys.stderr)

print("\nUnreported districts:", file=sys.stderr)
for r in rows:
    if not r['is_reported']:
        print(f"  {r['id']} {r['name']}: SCEIS State ${r['state_sceis_raw']:,} | Fed ${r['federal_sceis_raw']:,}", file=sys.stderr)

print("\nExcluded entities:", file=sys.stderr)
for row in excluded_sceis:
    print(f"  {row[0]} {row[1]}: State ${float(row[2] or 0):,.0f} | Fed ${float(row[3] or 0):,.0f}", file=sys.stderr)

sc_row = {
    "name": "South Carolina (Weighted Avg)",
    "id": "SC",
    "adm": total_adm,
    "is_reported": True,
    "state_total_sceis":  sc_state_pp,
    "local_sac_req":      sc_sac_pp,
    "local_additional":   sc_add_pp,
    "local_dist_svc":     sc_svc_pp,
    "local_investments":  sc_inv_pp,
    "federal_total_sceis":sc_fed_pp,
    "grand_total_pp":     sc_grand,
    "other_sources_pp":   0
}

output = {
    "rows":             rows,
    "sc_row":           sc_row,
    "excluded":         [{"id": r[0], "name": r[1],
                          "state_total":   float(r[2] or 0),
                          "federal_total": float(r[3] or 0)} for r in excluded_sceis],
    "unreported":       [r['id'] for r in rows if not r['is_reported']],
    "total_districts":  len(rows),
    "reporting_count":  reporting_count,
    "total_adm":         total_adm,
    "reporting_hc":     rep_adm,
}
print(json.dumps(output))
