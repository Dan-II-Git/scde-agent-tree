import duckdb
from decimal import Decimal
import json
import sys

con = duckdb.connect('db/scde.duckdb')

# --- Get district names ---
dist_names = {r[0]: r[1] for r in con.execute("SELECT District_ID, District_Name FROM dim_district ORDER BY District_ID").fetchall()}

# --- Headcounts (SY2025, 45-day, non-excluded) ---
hc_dict = {r[0]: r[1] for r in con.execute("""
    SELECT District_ID, Total_Active_Enrollment
    FROM lea_headcounts
    WHERE SY = 2025 AND Report_Cycle = 45
    AND District_ID NOT IN (
        SELECT District_ID FROM lookup_district_exclusions
        WHERE Exclude_Scope = 'all_reports'
          AND (Effective_FY_From IS NULL OR Effective_FY_From <= 2025)
          AND (Effective_FY_To   IS NULL OR Effective_FY_To   >= 2025)
    )
""").fetchall()}

# --- SCEIS State+Federal with Barnwell merge ---
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

# --- LEA revenue by category ---
lea_raw = con.execute("""
    SELECT
        CASE WHEN lr.District_ID IN ('0645','0648') THEN '0601' ELSE lr.District_ID END AS dist_id,
        cdfs.Stream_Type,
        cdfs.Category,
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
    GROUP BY 1, cdfs.Stream_Type, cdfs.Category
""").fetchall()

lea_dict = {}
for dist, stream_type, category, amt in lea_raw:
    if dist not in lea_dict:
        lea_dict[dist] = {'taxes_fees': 0.0, 'dist_svc': 0.0, 'invest': 0.0, 'additional': 0.0, 'state': 0.0, 'federal': 0.0, 'other_sources': 0.0}
    v = float(amt) if amt else 0.0
    if stream_type == 'Local':
        if category == 'Taxes & Fees':
            lea_dict[dist]['taxes_fees'] += v
        elif category == 'District Services':
            lea_dict[dist]['dist_svc'] += v
        elif category == 'Investments, Donations & Other':
            lea_dict[dist]['invest'] += v
        elif category is None:
            lea_dict[dist]['additional'] += v
    elif stream_type == 'State':
        lea_dict[dist]['state'] += v
    elif stream_type == 'Federal':
        lea_dict[dist]['federal'] += v
    elif stream_type is None and category is None:
        lea_dict[dist]['other_sources'] += v

# --- Reported districts ---
reported_raw = con.execute("""
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
""").fetchall()
reported_set = set(r[0] for r in reported_raw)

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
all_dists = sorted(set(sceis_dict.keys()) | set(hc_dict.keys()))
print(f"Total districts for report: {len(all_dists)}", file=sys.stderr)

rows = []
for d in all_dists:
    name = dist_names.get(d, 'District ' + d)
    hc = hc_dict.get(d)
    is_reported = d in reported_set
    sc = sceis_dict.get(d, {})
    la = lea_dict.get(d, {})

    state_raw = sc.get('State', 0.0)
    fed_raw = sc.get('Federal', 0.0)
    lea_state_raw = la.get('state', 0.0)

    if hc and hc > 0:
        state_pp = round(state_raw / hc)
        fed_pp = round(fed_raw / hc)
        sac_pp = round(la.get('taxes_fees', 0.0) / hc)
        additional_pp = round(la.get('additional', 0.0) / hc)
        dist_svc_pp = round(la.get('dist_svc', 0.0) / hc)
        invest_pp = round(la.get('invest', 0.0) / hc)
        other_pp = round(la.get('other_sources', 0.0) / hc)
    else:
        state_pp = fed_pp = sac_pp = additional_pp = dist_svc_pp = invest_pp = other_pp = None

    # For unreported districts: local segments are 0
    grand_total = (state_pp or 0) + (fed_pp or 0)
    if is_reported:
        grand_total += (sac_pp or 0) + (additional_pp or 0) + (dist_svc_pp or 0) + (invest_pp or 0)

    state_variance = round(state_raw - lea_state_raw)

    rows.append({
        'name': name,
        'id': d,
        'headcount': hc,
        'is_reported': is_reported,
        'state_total_sceis': state_pp,
        'local_sac_req': (sac_pp if is_reported else 0),
        'local_additional': (additional_pp if is_reported else 0),
        'local_dist_svc': (dist_svc_pp if is_reported else 0),
        'local_investments': (invest_pp if is_reported else 0),
        'federal_total_sceis': fed_pp,
        'grand_total_pp': grand_total,
        'other_sources_pp': (other_pp if is_reported else 0),
        'state_sceis_raw': round(state_raw),
        'federal_sceis_raw': round(fed_raw),
        'lea_state_raw': round(lea_state_raw),
        'state_variance_raw': state_variance,
    })

# --- Statewide weighted average ---
total_hc = sum(r['headcount'] for r in rows if r['headcount'])
total_state = sum(r['state_sceis_raw'] for r in rows if r['headcount'])
total_fed = sum(r['federal_sceis_raw'] for r in rows if r['headcount'])

rep_hc = sum(r['headcount'] for r in rows if r['headcount'] and r['is_reported'])
rep_sac = sum((r['local_sac_req'] or 0) * r['headcount'] for r in rows if r['headcount'] and r['is_reported'])
rep_add = sum((r['local_additional'] or 0) * r['headcount'] for r in rows if r['headcount'] and r['is_reported'])
rep_svc = sum((r['local_dist_svc'] or 0) * r['headcount'] for r in rows if r['headcount'] and r['is_reported'])
rep_inv = sum((r['local_investments'] or 0) * r['headcount'] for r in rows if r['headcount'] and r['is_reported'])

sc_state_pp = round(total_state / total_hc) if total_hc else 0
sc_fed_pp = round(total_fed / total_hc) if total_hc else 0
sc_sac_pp = round(rep_sac / rep_hc) if rep_hc else 0
sc_add_pp = round(rep_add / rep_hc) if rep_hc else 0
sc_svc_pp = round(rep_svc / rep_hc) if rep_hc else 0
sc_inv_pp = round(rep_inv / rep_hc) if rep_hc else 0
sc_grand = sc_state_pp + sc_fed_pp + sc_sac_pp + sc_add_pp + sc_svc_pp + sc_inv_pp

print(f"SC state_pp={sc_state_pp}, fed_pp={sc_fed_pp}, sac={sc_sac_pp}, add={sc_add_pp}, svc={sc_svc_pp}, inv={sc_inv_pp}, grand={sc_grand}", file=sys.stderr)
print(f"Total HC: {total_hc}, Reporting HC: {rep_hc}", file=sys.stderr)
reporting_count = sum(1 for r in rows if r['is_reported'])
print(f"Reporting districts: {reporting_count} of {len(rows)}", file=sys.stderr)

sc_row = {
    "name": "South Carolina (Weighted Avg)",
    "id": "SC",
    "headcount": total_hc,
    "is_reported": True,
    "state_total_sceis": sc_state_pp,
    "local_sac_req": sc_sac_pp,
    "local_additional": sc_add_pp,
    "local_dist_svc": sc_svc_pp,
    "local_investments": sc_inv_pp,
    "federal_total_sceis": sc_fed_pp,
    "grand_total_pp": sc_grand,
    "other_sources_pp": 0
}

# Print unreported
print("\nUnreported districts:", file=sys.stderr)
for r in rows:
    if not r['is_reported']:
        print(f"  {r['id']} {r['name']}: SCEIS State ${r['state_sceis_raw']:,} | Fed ${r['federal_sceis_raw']:,}", file=sys.stderr)

print("\nExcluded entities:", file=sys.stderr)
for row in excluded_sceis:
    print(f"  {row[0]} {row[1]}: State ${float(row[2] or 0):,.0f} | Fed ${float(row[3] or 0):,.0f}", file=sys.stderr)

# Output JSON to stdout
output = {
    "rows": rows,
    "sc_row": sc_row,
    "excluded": [{"id": r[0], "name": r[1], "state_total": float(r[2] or 0), "federal_total": float(r[3] or 0)} for r in excluded_sceis],
    "unreported": [r['id'] for r in rows if not r['is_reported']],
    "total_districts": len(rows),
    "reporting_count": reporting_count,
    "total_hc": total_hc,
    "reporting_hc": rep_hc,
}
print(json.dumps(output))
