import duckdb, os, json
from decimal import Decimal
from collections import defaultdict

db_path = os.path.join(os.path.expanduser('~'), 'Finance Dazzle', 'scde-agent-tree', 'db', 'scde.duckdb')
con = duckdb.connect(db_path, read_only=True)

def bucket_code(code, stream_type):
    c = str(code)
    if stream_type == 'Federal':
        return 'federal'
    if stream_type == 'State':
        if c in ('3103', '3103H', '3503'):
            return 'state_sac'
        if c.startswith('38'):
            return 'state_proptax'
        return 'state_other'
    if stream_type == 'Local':
        if c.startswith('11'):
            return 'local_sac_req'
        if c.startswith('12') or c.startswith('2'):
            return 'local_additional'
        if c in ('1920', '1950', '1990', '1993', '1994', '1999'):
            return 'local_additional'
        if c.startswith('13') or c.startswith('14') or c.startswith('16') or c.startswith('17'):
            return 'local_dist_svc'
        if c in ('1910', '1930', '1931', '1992'):
            return 'local_dist_svc'
        if c.startswith('15'):
            return 'local_investments'
        return 'local_additional'
    if c.startswith('5'):
        return 'other_sources'
    if c.startswith('2'):
        return 'local_additional'
    return 'other_sources'

# Pull ALL FY2024 data with Reported_Flag=TRUE
r = con.execute("""
    SELECT r.District_ID, r.Revenue_Code,
           COALESCE(f.Stream_Type, 'Unclassified') as Stream_Type,
           r.Amount
    FROM lea_revenues r
    LEFT JOIN code_district_funding_streams f ON r.Revenue_Code = f.REV_Code
    WHERE r.FY=2024 AND r.Reported_Flag=TRUE
    AND r.District_ID NOT IN ('5208','5209','5364','5395')
""").fetchall()

BARNWELL_MERGE = {'0645': '0601', '0648': '0601'}

buckets = defaultdict(lambda: defaultdict(float))
for district_id, code, stream_type, amount in r:
    did = BARNWELL_MERGE.get(district_id, district_id)
    bkt = bucket_code(code, stream_type)
    amt = float(amount) if amount is not None else 0.0
    buckets[did][bkt] += amt

hc_rows = con.execute("""
    SELECT District_ID, Total_Active_Enrollment
    FROM lea_headcounts WHERE SY=2024
""").fetchall()
headcounts = {row[0]: row[1] for row in hc_rows}

districts_raw = con.execute("""
    SELECT District_ID, District_Name FROM dim_district
    WHERE District_ID NOT IN ('5208','5209','5364','5395')
    ORDER BY District_Name
""").fetchall()

display_districts = [(did, name) for did, name in districts_raw if did not in ('0645', '0648')]

sceis_rows = con.execute("""
    SELECT District_ID, Funding_Stream, SUM(Amount) as total
    FROM vw_sceis_fi_payments_classified
    WHERE Fiscal_Year = 2024 AND Funding_Stream IN ('State','Federal')
    GROUP BY District_ID, Funding_Stream
""").fetchall()
sceis = defaultdict(lambda: defaultdict(float))
for did, stream, total in sceis_rows:
    if did:
        # Apply Barnwell merger: consolidate 0645+0648 SCEIS into 0601
        target = BARNWELL_MERGE.get(did, did)
        sceis[target][stream] += float(total)

data_rows = []
for did, name in display_districts:
    b = buckets[did]
    hc = headcounts.get(did)
    local_sac_req = b.get('local_sac_req', 0)
    local_additional = b.get('local_additional', 0)
    local_dist_svc = b.get('local_dist_svc', 0)
    local_investments = b.get('local_investments', 0)
    local_total = local_sac_req + local_additional + local_dist_svc + local_investments
    state_sac = b.get('state_sac', 0)
    state_proptax = b.get('state_proptax', 0)
    state_other = b.get('state_other', 0)
    state_total_sceis = sceis.get(did, {}).get('State', 0)
    federal_total_sceis = sceis.get(did, {}).get('Federal', 0)
    other_sources = b.get('other_sources', 0)
    grand_total = local_total + state_total_sceis + federal_total_sceis + other_sources
    lea_state_sum = state_sac + state_proptax + state_other
    state_variance = state_total_sceis - lea_state_sum
    data_rows.append({
        'name': name, 'id': did, 'headcount': hc,
        'local_sac_req': local_sac_req, 'local_additional': local_additional,
        'local_dist_svc': local_dist_svc, 'local_investments': local_investments,
        'local_total': local_total,
        'state_sac': state_sac, 'state_proptax': state_proptax, 'state_other': state_other,
        'state_total_sceis': state_total_sceis,
        'federal_total_sceis': federal_total_sceis,
        'other_sources': other_sources, 'grand_total': grand_total,
        'lea_state_sum': lea_state_sum, 'state_variance': state_variance
    })

valid_rows = [d for d in data_rows if d['headcount'] and d['headcount'] > 0]
sc_hc = sum(d['headcount'] for d in valid_rows)
sc_cols = ['local_sac_req','local_additional','local_dist_svc','local_investments',
           'local_total','state_sac','state_proptax','state_other',
           'state_total_sceis','federal_total_sceis','other_sources','grand_total',
           'lea_state_sum','state_variance']
sc_sums = {col: sum(d[col] for d in valid_rows) for col in sc_cols}
SC = {'name': 'South Carolina Total', 'id': 'SC', 'headcount': sc_hc}
SC.update(sc_sums)

print("=== Sanity check ===")
print(f"Districts displayed: {len(data_rows)}")
print(f"SC headcount: {sc_hc:,}")
print(f"SC grand total: {SC['grand_total']:,.0f}")
print(f"SC per-pupil grand: ${SC['grand_total']/sc_hc:,.0f}")

print("\n=== Top 5 state variance (SCEIS minus LEA sub-buckets) ===")
sorted_var = sorted(data_rows, key=lambda d: abs(d['state_variance']), reverse=True)
for d in sorted_var[:5]:
    pct = (d['state_variance'] / d['state_total_sceis'] * 100) if d['state_total_sceis'] else 0
    print(f"  {d['name']} ({d['id']}): SCEIS_State={d['state_total_sceis']:,.0f} LEA_sub={d['lea_state_sum']:,.0f} var={d['state_variance']:,.0f} ({pct:+.1f}%)")

print("\n=== Dillon 04 detail ===")
for d in data_rows:
    if d['id'] == '1704':
        pct = (d['state_variance'] / d['state_total_sceis'] * 100) if d['state_total_sceis'] else 0
        print(d)
        print(f"  SCEIS_state={d['state_total_sceis']:,.0f} LEA_sub={d['lea_state_sum']:,.0f} var={d['state_variance']:,.0f} ({pct:+.1f}%)")

output_data = {'data_rows': data_rows, 'SC': SC}
import tempfile
tmp = os.path.join(tempfile.gettempdir(), 'fy2024_revenue_data.json')
with open(tmp, 'w') as f:
    json.dump(output_data, f)
print(f"\nData saved to {tmp}")

con.close()
