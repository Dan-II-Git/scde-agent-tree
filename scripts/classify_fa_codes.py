"""
Classify Functional Area codes for dim_functional_area.json
Stage only — do NOT load into DB.
"""
import json, re
from collections import defaultdict
from pathlib import Path

RAW_PATH = Path(r"C:\Users\Dan's Test Device\Finance Dazzle\scde-agent-tree\scripts\fa_codes_raw.json")
OUT_PATH = Path(r"C:\Users\Dan's Test Device\Finance Dazzle\scde-agent-tree\db\dim_functional_area.json")

# -----------------------------------------------------------------------
# Pull raw data from DB
# -----------------------------------------------------------------------
import duckdb

DB = r"C:\Users\Dan's Test Device\Finance Dazzle\scde-agent-tree\db\scde.duckdb"
con = duckdb.connect(DB, read_only=True)

raw_rows = con.execute("""
    WITH all_codes AS (
        SELECT DISTINCT Functional_Area
        FROM (
            SELECT Functional_Area FROM sceis_agency_master WHERE Functional_Area IS NOT NULL AND Functional_Area != ''
            UNION SELECT Functional_Area FROM sceis_detail_transaction WHERE Functional_Area IS NOT NULL AND Functional_Area != ''
            UNION SELECT Functional_Area FROM sceis_fmeddw WHERE Functional_Area IS NOT NULL AND Functional_Area != ''
            UNION SELECT Functional_Area FROM bex_fi_vendor_invoice WHERE Functional_Area IS NOT NULL AND Functional_Area != ''
        ) t
    ),
    master_desc AS (
        SELECT Functional_Area, Functional_Area_Desc as master_desc
        FROM sceis_agency_master
        WHERE Functional_Area IS NOT NULL AND Functional_Area_Desc IS NOT NULL AND Functional_Area_Desc != ''
        QUALIFY ROW_NUMBER() OVER (PARTITION BY Functional_Area ORDER BY Functional_Area) = 1
    ),
    bex_desc AS (
        SELECT Functional_Area, Functional_Area_Desc as bex_desc
        FROM bex_fi_vendor_invoice
        WHERE Functional_Area IS NOT NULL AND Functional_Area_Desc IS NOT NULL AND Functional_Area_Desc != ''
        QUALIFY ROW_NUMBER() OVER (PARTITION BY Functional_Area ORDER BY Functional_Area) = 1
    ),
    fy26_spend AS (
        SELECT Functional_Area,
               CAST(SUM(Debit_Credit_Amount) AS DOUBLE) AS fy26_spend
        FROM sceis_detail_transaction
        WHERE GL_Account LIKE '5%' AND Fiscal_Year = 2026
          AND Functional_Area IS NOT NULL AND Functional_Area != ''
        GROUP BY Functional_Area
    )
    SELECT
        ac.Functional_Area,
        COALESCE(md.master_desc, '') as master_desc,
        COALESCE(bd.bex_desc, '') as bex_desc,
        COALESCE(NULLIF(bd.bex_desc,''), NULLIF(md.master_desc,''), '') as canonical_desc,
        CAST(COALESCE(fs.fy26_spend, 0.0) AS DOUBLE) as fy26_spend
    FROM all_codes ac
    LEFT JOIN master_desc md ON ac.Functional_Area = md.Functional_Area
    LEFT JOIN bex_desc bd ON ac.Functional_Area = bd.Functional_Area
    LEFT JOIN fy26_spend fs ON ac.Functional_Area = fs.Functional_Area
    ORDER BY ABS(CAST(COALESCE(fs.fy26_spend, 0.0) AS DOUBLE)) DESC
""").fetchall()

raw = [{'code': r[0], 'master_desc': r[1], 'bex_desc': r[2],
        'canonical_desc': r[3], 'fy26_spend': r[4]}
       for r in raw_rows]

con.close()
print(f"Pulled {len(raw)} distinct Functional_Area codes from DB")

# -----------------------------------------------------------------------
# CLASSIFICATION FUNCTION
# -----------------------------------------------------------------------
FEDERAL_KWS = ['federal', 'title i', 'title ii', 'title iii', 'title iv', 'idea',
               'esea', 'esser', 'essr', 'arp ', 'arp homeless', 'cares act',
               'cares fed', 'covid', 'coronavirus', 'subgrant', 'consolidated esea',
               'sc cares', 'essr iii', 'american rescue']

STATE_PROGRAM_KWS = ['summer reading', 'reading coach', 'literacy', 'instruction',
                     'assessment', 'cte', 'virtual', 'e-learning', 'special ed',
                     'gifted', 'career', 'adult ed', 'early childhood', 'cdep',
                     'teacher', 'leader', 'accountability', 'educator', 'eia',
                     'academic', 'standards', 'math resources', 'reading', 'stem',
                     'curriculum', 'professional dev', 'school improvement', 'abcd',
                     'teacher of year', 'teacher quality', 'adept', 'eeda', 'eaa',
                     'bus purchase', 'bus lease', 'school bus', 'transportation op',
                     'bus shop', 'innovation', 'special alloc', 'student learning',
                     'gateway academy', 'k12 initiative', 'wbl activities', 'gateway']

DIRECT_AID_KWS = ['direct aid', 'teacher salary', 'distribution to sub',
                  'state employer', 'employer contribution', 'state aid to',
                  'aid to school', 'aid to classrooms', 'scholarship', 'lottery',
                  'cap. funding', 'capital funding for']

ADMIN_KWS = ['admin', 'cfo', 'finance', 'procurement', 'information tech',
             'chief information', 'ciso', 'superintendent', 'board of trustees',
             'board of ed', 'general counsel', 'internal audit', 'audit',
             'policy', 'communications', 'research admin', 'data mgmt',
             'technology', 'facilities', 'human res', 'hr admin',
             'agency oper', 'operations', 'implementation', 'support operations',
             'strategic engagement', 'governmental affairs', 'innovation grants',
             'grants committee', 'cfr', 'office of finance', 'printing', 'relocation']

OPS_KWS = ['bus shop', 'transportation', 'nutrition', 'food serv', 'summer feed',
           'medicaid', 'babynet', 'health', 'school facilit', 'clean school bus']

EXTERNAL_KWS = ['gssm', 'gsah', 'governor', "governor's school", 'first steps',
                'charter school', 'endowment', 'public charter', 'sc public',
                'board of education', 'state board', 'sc public school district']


def kwmatch(text, kw_list):
    t = text.lower()
    return any(kw in t for kw in kw_list)


def classify(code, desc):
    """Return (category, confidence, note)"""
    d = desc.lower() if desc else ''

    # ---- System / Interface placeholders ----
    if code in ('0000000000000000', 'HRPAY', 'OSB', 'H630'):
        notes = {
            '0000000000000000': 'All-zero placeholder; posted on rows with no FA assigned',
            'HRPAY': 'HR/Payroll system interface code; not a real appropriation activity',
            'OSB': 'Office of State Budget interface or placeholder',
            'H630': 'Bare agency prefix; truncated/unresolved FA value',
        }
        return 'System / Interface', 'high', notes.get(code, 'System-generated placeholder')

    if code == 'H630_CAFR':
        return 'System / Interface', 'high', 'CAFR / unbudgeted interface code (matches dim_cost_center H63000CAFR)'

    # ---- H630_N* — Child Nutrition ----
    if re.match(r'^H630_N', code):
        return 'Child Nutrition', 'high', (
            'H630_N* prefix = USDA Child Nutrition program activities '
            '(National School Lunch, Breakfast, CACFP, SFSP, etc.)')

    # ---- H630_FS* and H630XFS* — SC First Steps ----
    if re.match(r'^H630_FS', code) or re.match(r'^H630XFS', code):
        return 'SC First Steps', 'high', (
            'H630_FS*/H630XFS* prefix = SC First Steps early-childhood programs '
            '(local partnerships, Private 4-K, Board of Trustees operations)')

    # ---- Z-suffix rollup nodes ----
    if re.match(r'^H630_', code) and code.endswith('Z'):
        return 'Appropriation Z-Rollup', 'high', (
            'Z-suffix codes are SAP FM hierarchical rollup nodes; '
            'not posted individually on real transactions')

    # ---- H630X[3-9]DDD and H630X97xx — Legislative earmarks / external orgs ----
    if re.match(r'^H630X[3-9]\d{3}', code):
        # A handful are agency-internal (not third-party org names)
        INTERNAL_EXCEPTIONS = {
            'H630X3601': 'AI Pilot',
            'H630X4601': 'Agency Tech Equip',
            'H630X4720': 'Dynamic Report Card',
            'H630X5640': 'Efficiency Study',
            'H630X6101': 'SCDE Agency Systems',
            'H630X9501': 'School Safety Mapping',
        }
        if code in INTERNAL_EXCEPTIONS:
            return 'State Appropriation Activity', 'medium', (
                f'H630X[3-9]DDD but appears SCDE-internal ({INTERNAL_EXCEPTIONS[code]}); '
                'not an external-org earmark')
        return 'Legislative Earmark / External Org Grant', 'high', (
            'H630X[3-9]DDD pattern = legislative earmarks payable to named '
            'external organizations (foundations, community orgs, school districts)')

    # ---- H630X[alpha] — mixed small set ----
    if re.match(r'^H630X[A-Z]', code):
        if re.match(r'^H630XCS', code):
            return 'SC First Steps', 'medium', 'H630XCS* linked to charter-school / SC First Steps early-childhood programs'
        if re.match(r'^H630XAS', code):
            return 'State Appropriation Activity', 'medium', 'H630XAS* — verify against appropriation docs'
        if code in ('H630XNR01', 'H630XCR01'):
            return 'State Appropriation Activity', 'medium', 'School Bus / Facilities program code'
        if code == 'H630XSDCI':
            return 'State Appropriation Activity', 'low', 'Abbreviated code; no description available — review needed'
        if code == 'H630XS19C':
            return 'Federal Grant / Pass-Through', 'low', 'Suffix S19C suggests federal COVID/stimulus; no description — review needed'
        return 'State Appropriation Activity', 'low', 'H630X[alpha] — pattern unclear; review needed'

    # ---- H630X0DDD, H630X1DDD, H630X2DDD: EIA/state program or federal ----
    if re.match(r'^H630X[012]', code):
        if code == 'H630X2034':
            return 'State Aid to Districts (Direct)', 'high', (
                '$2.84B largest single code; "State Aid to Classrooms" — '
                'main BSC direct-aid pass-through to districts')
        if kwmatch(d, DIRECT_AID_KWS):
            return 'State Aid to Districts (Direct)', 'high', 'Name signals direct-aid distribution'
        if kwmatch(d, FEDERAL_KWS):
            return 'Federal Grant / Pass-Through', 'high', 'Name signals federal grant program'
        if kwmatch(d, OPS_KWS):
            return 'District Operations Support', 'high', 'Transportation / nutrition district-support activity'
        if kwmatch(d, STATE_PROGRAM_KWS):
            return 'State Appropriation Activity', 'high', 'EIA/state-funded program activity (H630X0*/X1*/X2* series)'
        if kwmatch(d, ADMIN_KWS):
            return 'Agency Administration', 'high', 'Agency admin activity within EIA program group'
        if desc:
            return 'State Appropriation Activity', 'medium', 'H630X[0-2]DDD with description — assumed state/EIA program'
        return 'State Appropriation Activity', 'low', 'H630X[0-2]DDD no description — review needed'

    # ---- H630_ pure 4-digit numeric ----
    if re.match(r'^H630_\d{4}$', code):
        if kwmatch(d, DIRECT_AID_KWS):
            return 'State Aid to Districts (Direct)', 'high', 'Direct-Aid or employer-contribution distribution'
        if kwmatch(d, FEDERAL_KWS):
            return 'Federal Grant / Pass-Through', 'high', 'Name signals federal program'
        if kwmatch(d, EXTERNAL_KWS):
            return 'External Entity (Administered)', 'high', 'Governor\'s School, Charter District, or other SCDE-administered external entity'
        if kwmatch(d, OPS_KWS):
            return 'District Operations Support', 'high', 'Transportation, nutrition, or health support'
        if kwmatch(d, STATE_PROGRAM_KWS):
            return 'State Appropriation Activity', 'high', 'H630_DDDD named program — state-funded activity'
        if kwmatch(d, ADMIN_KWS):
            return 'Agency Administration', 'high', 'Agency admin/overhead functional area'
        if desc:
            return 'State Appropriation Activity', 'medium', 'H630_DDDD with description — assumed state appropriation'
        return 'State Appropriation Activity', 'low', 'H630_DDDD no description — assumed state appropriation; review needed'

    # ---- H630_ alpha (non-Z, non-FS, non-N, non-CAFR) ----
    if re.match(r'^H630_', code):
        if kwmatch(d, FEDERAL_KWS):
            return 'Federal Grant / Pass-Through', 'high', 'Name signals federal grant program'
        if kwmatch(d, EXTERNAL_KWS):
            return 'External Entity (Administered)', 'high', 'External entity administered by SCDE'
        if kwmatch(d, DIRECT_AID_KWS):
            return 'State Aid to Districts (Direct)', 'high', 'Direct distribution to districts/entities'
        if kwmatch(d, OPS_KWS):
            return 'District Operations Support', 'high', 'Transportation, nutrition, or health support'
        if kwmatch(d, STATE_PROGRAM_KWS):
            return 'State Appropriation Activity', 'high', 'Named program — state/EIA-funded activity'
        if kwmatch(d, ADMIN_KWS):
            return 'Agency Administration', 'high', 'Agency admin / overhead'
        if desc:
            return 'State Appropriation Activity', 'medium', 'H630_[alpha] with description — likely EIA/state program activity'
        return 'State Appropriation Activity', 'low', 'H630_[alpha] no description — review needed'

    return 'Unclassified', 'low', 'Pattern not recognized; manual review required'


# -----------------------------------------------------------------------
# BUILD MAPPING DICT
# -----------------------------------------------------------------------
mapping = {}
total_positive_spend = sum(r['fy26_spend'] for r in raw if r['fy26_spend'] > 0)

for r in raw:
    code = r['code']
    desc = r['canonical_desc']
    cat, conf, note = classify(code, desc)

    entry = {
        'name': desc if desc else None,
        'category': cat,
        'confidence': conf,
        'fy26_5xxx_spend': round(r['fy26_spend'], 2),
    }
    if note:
        entry['note'] = note
    mapping[code] = entry


# -----------------------------------------------------------------------
# REVIEW NEEDED LIST
# Tier 1 (priority): low confidence WITH FY26 spend, or no-description WITH spend
# Tier 2 (low priority): low confidence with zero spend, or no-desc zero spend
# Z-rollup codes with no description but with spend are also flagged (high conf,
# but Dan may want to verify the rollup label)
# -----------------------------------------------------------------------
review_needed = []
for code, entry in mapping.items():
    has_spend = abs(entry['fy26_5xxx_spend']) > 0
    no_desc = entry['name'] is None
    low_conf = entry['confidence'] == 'low'
    is_zrollup_no_desc = entry['category'] == 'Appropriation Z-Rollup' and no_desc and has_spend

    if low_conf or (no_desc and has_spend):
        priority = 'high' if (has_spend and (low_conf or no_desc)) else 'low'
        review_needed.append({
            'code': code,
            'name': entry['name'],
            'category_proposed': entry['category'],
            'confidence': entry['confidence'],
            'fy26_5xxx_spend': entry['fy26_5xxx_spend'],
            'priority': priority,
            'reason': (
                'no description + has FY26 spend' if no_desc and has_spend else
                'low confidence + has FY26 spend' if low_conf and has_spend else
                'low confidence + zero spend (historical/dormant)'
            ),
            'note': entry.get('note', ''),
        })

review_needed.sort(key=lambda x: (
    0 if x['priority'] == 'high' else 1,
    -abs(x['fy26_5xxx_spend'])
))


# -----------------------------------------------------------------------
# COVERAGE BLOCK
# -----------------------------------------------------------------------
cat_totals = defaultdict(lambda: {'count': 0, 'spend': 0.0})
for code, entry in mapping.items():
    cat = entry['category']
    cat_totals[cat]['count'] += 1
    cat_totals[cat]['spend'] += max(entry['fy26_5xxx_spend'], 0)

codes_with_spend = sum(1 for e in mapping.values() if e['fy26_5xxx_spend'] != 0)
high_conf_spend = sum(
    max(e['fy26_5xxx_spend'], 0) for e in mapping.values()
    if e['confidence'] == 'high' and e['fy26_5xxx_spend'] > 0
)

coverage = {
    'total_distinct_codes': len(mapping),
    'codes_with_fy26_5xxx_spend': codes_with_spend,
    'total_fy26_5xxx_positive_spend': round(total_positive_spend, 2),
    'high_confidence_fy26_spend': round(high_conf_spend, 2),
    'high_confidence_pct_of_spend': round(high_conf_spend / total_positive_spend * 100, 1) if total_positive_spend else 0,
    'review_needed_count': len(review_needed),
    'by_category': {
        cat: {
            'count': info['count'],
            'fy26_positive_spend': round(info['spend'], 2),
            'pct_of_spend': round(info['spend'] / total_positive_spend * 100, 2) if total_positive_spend else 0
        }
        for cat, info in sorted(cat_totals.items(), key=lambda x: x[1]['spend'], reverse=True)
    }
}


# -----------------------------------------------------------------------
# PREFIX RULES
# -----------------------------------------------------------------------
prefix_rules = {
    'H630_N': {
        'category': 'Child Nutrition',
        'confidence': 'high',
        'note': ('All H630_N* codes (36 total) represent USDA Child Nutrition '
                 'program activities (NSLP, SBP, CACFP, SFSP). Codes H630_N020-N900 '
                 'appear to correspond to individual USDA program components. '
                 'None have FY26 5xxx spend individually, suggesting funds flow '
                 'through aggregate codes.')
    },
    'H630_FS': {
        'category': 'SC First Steps',
        'confidence': 'high',
        'note': ('All H630_FS* codes (30+) represent SC First Steps program '
                 'activities — local partnerships, Private 4-K, administration, '
                 'Board of Trustees, donations. Zero FY26 5xxx spend; likely '
                 'excluded from sceis_detail_transaction or use non-5xxx GL.')
    },
    'H630XFS': {
        'category': 'SC First Steps',
        'confidence': 'high',
        'note': 'H630XFS* codes also represent SC First Steps programs (4 known codes).'
    },
    'H630X[3-9]DDD': {
        'category': 'Legislative Earmark / External Org Grant',
        'confidence': 'high',
        'note': ('H630X[3-9]DDD range (71 codes) holds legislative earmarks '
                 'payable to named external organizations — community groups, '
                 'foundations, local school programs. Most have $0 FY26 5xxx spend '
                 '(suggesting disbursed via non-5xxx GL or appropriated but not yet spent). '
                 'Six exceptions reclassified as State Appropriation Activity.')
    }
}


# -----------------------------------------------------------------------
# ASSEMBLE FINAL JSON
# -----------------------------------------------------------------------
output = {
    'version': 'v1',
    'as_of': '2026-05-14',
    'source': (
        'Derived from sceis_agency_master (83 codes + descriptions), '
        'bex_fi_vendor_invoice (291 codes + descriptions, preferred over master where both present — '
        'zero conflicts found), sceis_detail_transaction (659 codes), sceis_fmeddw (240 codes). '
        'FY26 spend signal computed as SUM(Debit_Credit_Amount) WHERE GL_Account LIKE "5%" '
        'AND Fiscal_Year=2026 from sceis_detail_transaction. '
        'STAGED ONLY — not yet loaded into canonical DB. Pending data-quality sign-off.'
    ),
    'pattern_hypothesis': {
        'verified': True,
        'H630_XXXX': (
            'State appropriation activity code. Underscore separator indicates '
            'a direct SC state appropriation activity (General Fund, EIA, lottery, etc.). '
            '4-digit numeric suffix = specific line item in the H630 appropriation structure. '
            'Alpha suffix = named program variant or rollup (e.g. H630_CAFR, H630_K206). '
            'Z-suffix = FM hierarchical rollup node, not a posting-level code.'
        ),
        'H630XNNNN': (
            'Non-appropriation or special activity code. No underscore = federal grant, '
            'pass-through to districts/external orgs, or legislative earmark. '
            'Sub-patterns: H630X0DDD/X1DDD/X2DDD = EIA/state program activities '
            'or specific disbursements (H630X2034 = $2.84B State Aid to Classrooms). '
            'H630X[3-9]DDD = legislative earmarks to external organizations. '
            'H630XFS* = SC First Steps. H630XCS* = public charter school programs.'
        ),
    },
    'prefix_rules': prefix_rules,
    'mapping': mapping,
    'coverage': coverage,
    'review_needed': review_needed,
    'data_quality_flags': [
        {
            'flag': 'description_conflict',
            'detail': 'Zero conflicts found between sceis_agency_master.Functional_Area_Desc and bex_fi_vendor_invoice.Functional_Area_Desc for any code present in both sources.',
            'severity': 'none'
        },
        {
            'flag': 'codes_not_in_agency_master',
            'detail': f'613 of 696 distinct Functional_Area values appear in transaction tables but NOT in sceis_agency_master. This is expected: agency master holds ~83 budgeted activity lines; the full transaction universe includes historical codes, First Steps codes, Child Nutrition codes, and legislative earmarks that were never added to the FM master.',
            'severity': 'informational'
        },
        {
            'flag': 'no_description_with_spend',
            'detail': '22 codes have FY26 5xxx spend but no description from either source. Top priority for manual lookup: H630X2609 ($15.0M), H630_1ASZ ($1.6M), H630_ALTF ($1.6M). Full list in review_needed.',
            'severity': 'medium'
        },
        {
            'flag': 'zero_dollar_codes_volume',
            'detail': f'{696 - codes_with_spend} of 696 codes have $0 FY26 5xxx spend. Most are historical codes (pre-FY26 programs), First Steps codes (different GL range), Child Nutrition placeholders, or legislative earmarks not yet disbursed.',
            'severity': 'informational'
        },
        {
            'flag': 'system_placeholders_in_transactions',
            'detail': 'Codes 0000000000000000, HRPAY, OSB, and bare H630 appear in sceis_detail_transaction. These should not appear on real expenditure rows and indicate unresolved postings or interface transactions. Treat as unattributable.',
            'severity': 'medium'
        }
    ],
    'usage': (
        'Load into DuckDB as dim_functional_area (functional_area, name, category, confidence, note). '
        'Join from sceis_detail_transaction, sceis_fmeddw, and bex_fi_vendor_invoice via '
        'Functional_Area to enable grouping by category in the internal Budget vs Actuals dashboard. '
        'Replaces ad-hoc string-matching on Functional_Area_Desc in queries.py.'
    )
}

# -----------------------------------------------------------------------
# WRITE
# -----------------------------------------------------------------------
with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\nWrote {OUT_PATH}")
print(f"Total codes: {len(mapping)}")
print(f"Review needed: {len(review_needed)}")

# Print summary table
print("\n=== CATEGORY SUMMARY ===")
print(f"  {'Category':<45} {'Count':>6} {'FY26 Spend':>18} {'% Spend':>8}")
print("  " + "-" * 83)
for cat, info in coverage['by_category'].items():
    print(f"  {cat:<45} {info['count']:>6} {info['fy26_positive_spend']:>18,.0f} {info['pct_of_spend']:>7.1f}%")

print(f"\n=== REVIEW NEEDED (top 25 by spend) ===")
for r in review_needed[:25]:
    name_str = (r['name'] or 'NO DESC')[:35]
    print(f"  {r['code']!r:22s} | ${r['fy26_5xxx_spend']:>14,.0f} | {r['confidence']:6} | {name_str}")
