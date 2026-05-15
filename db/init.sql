-- SCDE Financial Data canonical schema
-- Run via: duckdb db/scde.duckdb < db/init.sql
-- Idempotent — safe to re-run

-- ============================================================
-- Dimensions
-- ============================================================

CREATE TABLE IF NOT EXISTS dim_district (
    District_ID         VARCHAR PRIMARY KEY,
    District_Name       VARCHAR NOT NULL,
    normalized_name     VARCHAR NOT NULL,
    short_name          VARCHAR,        -- "Abbeville" form
    long_name           VARCHAR,        -- "Abbeville 60" form
    source_files        VARCHAR[]       -- which files this district appears in
);

CREATE TABLE IF NOT EXISTS dim_fiscal_year (
    FY                  SMALLINT PRIMARY KEY,
    start_date          DATE NOT NULL,
    end_date            DATE NOT NULL,
    sy_label            VARCHAR NOT NULL  -- "2024-25"
);

-- ============================================================
-- Code catalog (owned by code-catalog agent)
-- ============================================================

CREATE TABLE IF NOT EXISTS code_accounting_codes (
    Code                VARCHAR NOT NULL,
    Type                VARCHAR NOT NULL,  -- Revenue / Function / Object
    Full_Name           VARCHAR,
    Display_Name        VARCHAR,
    Short_Description   VARCHAR,
    Full_Description    VARCHAR,
    PRIMARY KEY (Code, Type)
);

CREATE TABLE IF NOT EXISTS code_district_funding_streams (
    REV_Code            VARCHAR PRIMARY KEY,
    Stream_Type         VARCHAR,            -- Local / State / Federal
    Rollup_Level        SMALLINT,
    Category            VARCHAR,
    Display_Title       VARCHAR,
    Program_Office      VARCHAR,
    Source_System       VARCHAR
    -- Allocation_Basis and Sunset_Note added below via ALTER TABLE
);

-- Added for funding-projections agent: Allocation_Basis routes each REV_Code
-- to the correct projection method; Sunset_Note forces projected amount to
-- zero after the named fiscal year. NULL is correct for Federal/Local rows
-- that have no Allocation Data column in the source inventory.
ALTER TABLE code_district_funding_streams
    ADD COLUMN IF NOT EXISTS Allocation_Basis VARCHAR;  -- 'PowerSchool ADM' | 'PS ADM' | 'Categorical' | 'District FTEs' | NULL
ALTER TABLE code_district_funding_streams
    ADD COLUMN IF NOT EXISTS Sunset_Note VARCHAR;       -- e.g. 'Closed, last paid FY23'; NULL when no sunset applies

CREATE TABLE IF NOT EXISTS code_handbook_definitions (
    Term                VARCHAR PRIMARY KEY,
    Definition          VARCHAR,
    Category            VARCHAR
);

-- Annual policy-rate inputs for funding-projection formulas.
-- Owned by code-catalog agent. Seeded manually from the SC Appropriations Act;
-- do not auto-populate from the projection pipeline.
CREATE TABLE IF NOT EXISTS policy_rate_assumptions (
    FY                  SMALLINT NOT NULL,
    parameter           VARCHAR  NOT NULL,      -- e.g. 'sac_base_per_wpu', 'sac_health_insurance_per_wpu'
    scenario            VARCHAR  NOT NULL,      -- 'baseline' for v1; future: 'flat_funding', 'bsc_+3pct'
    value               DECIMAL(18, 4) NOT NULL, -- per-pupil dollars; 4 decimals for fractional rates
    source              VARCHAR,                -- e.g. 'SC Appropriations Act 2024-25, Part IB §1A.1'
    notes               VARCHAR,
    PRIMARY KEY (FY, parameter, scenario)
);

CREATE TABLE IF NOT EXISTS lookup_gl_account (
    GL_Account          VARCHAR PRIMARY KEY,
    SAP_Category        VARCHAR,
    Handbook_Code       VARCHAR,
    Handbook_Type       VARCHAR,
    Handbook_Name       VARCHAR,
    Bridge_Type         VARCHAR,
    Source              VARCHAR,
    Confidence          VARCHAR,
    Notes               VARCHAR,
    Source_Row_Count    INTEGER
);

-- ============================================================
-- SCEIS (owned by sceis-data agent)
-- ============================================================

CREATE TABLE IF NOT EXISTS sceis_agency_master (
    Cost_Center             VARCHAR PRIMARY KEY,
    Name                    VARCHAR,
    Functional_Area         VARCHAR,
    Functional_Area_Desc    VARCHAR,
    Mini_Code               VARCHAR,
    State_Funded_Program    VARCHAR,
    AGY_Funded_Program      VARCHAR,
    AGY_Funded_Program_Name VARCHAR,
    Valid_From              DATE,
    Valid_To                DATE
);

CREATE TABLE IF NOT EXISTS sceis_detail_transaction (
    Doc_Number              VARCHAR NOT NULL,
    Doc_Item                INTEGER NOT NULL,
    Business_Area           VARCHAR,
    Fund                    VARCHAR,
    Funds_Cost_Center       VARCHAR,
    Functional_Area         VARCHAR,
    Agency_Appropriation    VARCHAR,
    State_Appropriation     VARCHAR,
    GL_Account              VARCHAR,
    Posting_Date            DATE,
    Posting_Period          SMALLINT,
    Fiscal_Year             SMALLINT,
    Document_Type           VARCHAR,
    Ref_Doc_Number          VARCHAR,
    Posting_Key             VARCHAR,
    Debit_Credit_Ind        VARCHAR,        -- H or S
    Debit_Credit_Amount     DECIMAL(18, 2),
    PRIMARY KEY (Doc_Number, Doc_Item)
);

-- Reference -> (Funding_Stream, Program_Tag) classifier rules.
-- Lowest Rule_Order wins on multi-match. Pattern is a DuckDB regex
-- evaluated against UPPER(regexp_replace(Reference, '^\d{4}[\s\-_]*', ''))
-- — i.e. the Reference with the District_ID prefix stripped, uppercased.
CREATE TABLE IF NOT EXISTS lookup_sceis_program_classification (
    Rule_Order      SMALLINT NOT NULL,
    Pattern         VARCHAR  NOT NULL,
    Funding_Stream  VARCHAR  NOT NULL,        -- 'State' | 'Federal' | 'Other'
    Program_Tag     VARCHAR  NOT NULL,        -- e.g. 'EIA', 'ESSER', 'Title I-IV'
    Description     VARCHAR,
    Source          VARCHAR,
    PRIMARY KEY (Rule_Order)
);

CREATE TABLE IF NOT EXISTS sceis_fi_payments (
    Doc_Number              VARCHAR NOT NULL,
    Item                    INTEGER NOT NULL,
    Business_Area           VARCHAR,
    Vendor                  VARCHAR,
    Vendor_Name             VARCHAR,
    Document_Date           DATE,
    Posting_Date            DATE,
    Document_Type           VARCHAR,
    GL_Account              VARCHAR,
    Clearing_Doc_Number     VARCHAR,
    Fiscal_Period           VARCHAR,
    Fiscal_Year             SMALLINT,
    Reference               VARCHAR,
    District_ID             VARCHAR,        -- validated 4-digit prefix from Reference; NULL when prefix is not in dim_district
    Source_File             VARCHAR,
    Amount                  DECIMAL(18, 2),
    PRIMARY KEY (Doc_Number, Item)
);

-- ============================================================
-- SCEIS Funds Management (owned by internal-budget agent)
-- ============================================================

-- FMEDDW = SAP Funds Management Drilldown Reporting transaction.
-- Document-level FM postings: budget appropriations, transfers,
-- carryforward, allocations, and GM-module actuals consumption.
-- One row = one FM document line. Budget vs actuals is derived
-- via vw_budget_vs_actuals_by_funds_center.
CREATE TABLE IF NOT EXISTS sceis_fmeddw (
    Entry_Document          VARCHAR NOT NULL,
    Entry_Document_Line     VARCHAR NOT NULL,
    Document_Date           DATE,
    Document_Year           VARCHAR,
    Version                 VARCHAR,
    Entry_Document_Type     VARCHAR,           -- APPR, TRFW, GM01, BDAJ, CFWD, SUPP, IATR, ALOC, CFGF, OSB2
    Process                 VARCHAR,           -- Enter / Receive / Send / Supplement / Carry For. Recv / Return
    Created_On              DATE,
    Fiscal_Year             SMALLINT,
    Budget_Type             VARCHAR,           -- ORIGINAL APPROPRIATIONS, TRANSFER OF APPROPRIATIONS, GM Budget Doc Type, etc.
    Fund                    VARCHAR,
    Funds_Center            VARCHAR,           -- FM org object; 10-char = leaf cost center, 8-char = rollup parent
    Commitment_Item         VARCHAR,
    Functional_Area         VARCHAR,
    Grant                   VARCHAR,
    Document_Status         VARCHAR,           -- 'Posted' | 'Preposted Posted'
    Document_Status_Code    SMALLINT,          -- 1 = Posted, 3 = Preposted Posted
    Funded_Program          VARCHAR,
    Amount                  DECIMAL(18, 2),    -- "Total of Transactions in Local Currency"; signed (Send -, Receive/Enter +)
    Currency                VARCHAR,
    Is_Rollup               BOOLEAN,           -- TRUE when LEN(Funds_Center)=8; exclude from per-center aggregations
    Source_File             VARCHAR,
    PRIMARY KEY (Entry_Document, Entry_Document_Line)
);

-- ============================================================
-- LEA (owned by lea-data agent)
-- ============================================================

CREATE TABLE IF NOT EXISTS lea_revenues (
    District_ID             VARCHAR NOT NULL,
    Revenue_Code            VARCHAR NOT NULL,
    FY                      SMALLINT NOT NULL,
    Amount                  DECIMAL(18, 2),
    Reported_Flag           BOOLEAN,           -- TRUE if district reported any nonzero leaf row in this FY; FALSE = template-zero (not submitted, OR structurally correct e.g. Barnwell 45/48 post-merger). Derived per (District_ID, FY).
    PRIMARY KEY (District_ID, Revenue_Code, FY)
);

CREATE TABLE IF NOT EXISTS lea_expenditures (
    District_ID             VARCHAR NOT NULL,
    Function_Code           VARCHAR NOT NULL,
    FY                      SMALLINT NOT NULL,
    Amount                  DECIMAL(18, 2),
    Reported_Flag           BOOLEAN,           -- TRUE if district reported any nonzero leaf row in this FY; FALSE = template-zero. Populate per (District_ID, FY) at load time, same convention as lea_revenues.
    PRIMARY KEY (District_ID, Function_Code, FY)
);

CREATE TABLE IF NOT EXISTS lea_adm_counts (
    District_ID             VARCHAR NOT NULL,
    School_Code             VARCHAR NOT NULL,
    SY                      SMALLINT NOT NULL,
    Report_Cycle            SMALLINT NOT NULL,  -- 135
    PK_count                INTEGER,
    K_count                 INTEGER,
    Grade_01                INTEGER,
    Grade_02                INTEGER,
    Grade_03                INTEGER,
    Grade_04                INTEGER,
    Grade_05                INTEGER,
    Grade_06                INTEGER,
    Grade_07                INTEGER,
    Grade_08                INTEGER,
    Grade_09                INTEGER,
    Grade_10                INTEGER,
    Grade_11                INTEGER,
    Grade_12                INTEGER,
    Total_Membership        INTEGER,
    PRIMARY KEY (District_ID, School_Code, SY, Report_Cycle)
);

CREATE TABLE IF NOT EXISTS lea_headcounts (
    District_ID             VARCHAR NOT NULL,
    SY                      SMALLINT NOT NULL,
    Report_Cycle            SMALLINT NOT NULL,  -- 45
    Source_System           VARCHAR,
    Total_Active_Enrollment INTEGER,
    PK_count                INTEGER,
    K5_count                INTEGER,
    Grade_01                INTEGER,
    Grade_02                INTEGER,
    Grade_03                INTEGER,
    Grade_04                INTEGER,
    Grade_05                INTEGER,
    Grade_06                INTEGER,
    Grade_07                INTEGER,
    Grade_08                INTEGER,
    Grade_09                INTEGER,
    Grade_10                INTEGER,
    Grade_11                INTEGER,
    Grade_12                INTEGER,
    PRIMARY KEY (District_ID, SY, Report_Cycle)
);

CREATE TABLE IF NOT EXISTS lea_wpu_allocations (
    District_ID             VARCHAR NOT NULL,
    FY                      SMALLINT NOT NULL,
    Category                VARCHAR NOT NULL,   -- Kindergarten, Primary, ...
    Report_Cycle            SMALLINT NOT NULL,  -- 45 (preliminary) or 135 (funding-final)
    ADM_135_Day             DECIMAL(12, 2),
    Weighted_Pupils         DECIMAL(12, 2),
    State_Allocation        DECIMAL(18, 2),     -- nullable for FY23+
    Local_Required_Support  DECIMAL(18, 2),     -- nullable for FY23+
    Audit_Standard          DECIMAL(18, 2),     -- nullable for FY23+
    PRIMARY KEY (District_ID, FY, Category, Report_Cycle)
);

-- ============================================================
-- Marts (populated by report agents as needed)
-- ============================================================

-- mart_district_revenue_rollup: one row per (District_ID, FY, Revenue_Code).
-- Owned by report-district-revenue. Built by joining lea_revenues (Reported_Flag=TRUE)
-- to code_district_funding_streams, with INNER JOIN to vw_revenue_code_status to
-- enforce Is_Statewide_Dormant = FALSE (dormancy mask applied at build time).
-- Rebuilt whenever lea_revenues or code_district_funding_streams changes.
CREATE TABLE IF NOT EXISTS mart_district_revenue_rollup (
    District_ID     VARCHAR     NOT NULL,
    FY              SMALLINT    NOT NULL,
    Revenue_Code    VARCHAR     NOT NULL,
    Stream_Type     VARCHAR,
    Category        VARCHAR,
    Display_Title   VARCHAR,
    Rollup_Level    SMALLINT,
    Amount          DECIMAL(18, 2),
    PRIMARY KEY (District_ID, FY, Revenue_Code)
);

-- Funding-projection output mart. Owned by the funding-projections agent
-- (not yet implemented). Rebuilt by that agent's pipeline SQL. Stores
-- point estimates and 80% prediction-interval bounds per district + revenue
-- code + scenario. PRIMARY KEY enforces one row per district/FY/code/scenario.
CREATE TABLE IF NOT EXISTS mart_funding_projections (
    District_ID         VARCHAR      NOT NULL,
    FY                  SMALLINT     NOT NULL,
    Revenue_Code        VARCHAR      NOT NULL,
    Stream_Type         VARCHAR,                    -- 'State' | 'Federal' | 'Local'
    Allocation_Basis    VARCHAR,                    -- copied from code_district_funding_streams.Allocation_Basis
    Amount              DECIMAL(18, 2),             -- point estimate
    Lower_80            DECIMAL(18, 2),             -- 80% prediction-interval lower bound
    Upper_80            DECIMAL(18, 2),             -- 80% prediction-interval upper bound
    Method              VARCHAR,                    -- 'formula_sac' | 'trend_ols' | 'sunset_zero' | 'insufficient_history'
    Scenario            VARCHAR      NOT NULL,      -- matches policy_rate_assumptions.scenario; 'baseline' for v1
    Built_At            TIMESTAMP,
    PRIMARY KEY (District_ID, FY, Revenue_Code, Scenario)
);

-- ============================================================
-- Seed data — lookup_sceis_program_classification
-- ============================================================
--
-- 22 curated regex rules driving the State / Federal / Other split in
-- vw_sceis_fi_payments_classified. The view applies them to UPPER(reference
-- with district prefix stripped). Rules are upserted by Rule_Order so this
-- block is idempotent — re-running init.sql restores the canonical ruleset
-- without touching unrelated rows the user may have added with other
-- Rule_Order values.
--
-- Coverage (as of 2026-04-28): ~98% of district-attributed dollars classified;
-- ~2% land in 'Other' (mostly Reference-field truncation in source files).

INSERT INTO lookup_sceis_program_classification
    (Rule_Order, Pattern, Funding_Stream, Program_Tag, Description, Source)
VALUES
    ( 10, '\bESSER\b', 'Federal', 'ESSER',
        'Elementary and Secondary School Emergency Relief (CARES/CRRSA/ARP)',
        'curated 2026-04-27'),
    ( 20, '\bARP\b', 'Federal', 'ARP',
        'American Rescue Plan',
        'curated 2026-04-27'),
    ( 30, '\bCARES?\b', 'Federal', 'CARES',
        'Coronavirus Aid, Relief, and Economic Security Act',
        'curated 2026-04-27'),
    ( 40, '\bGEER\b', 'Federal', 'GEER',
        'Governor''s Emergency Education Relief',
        'curated 2026-04-27'),
    ( 50, '\bTITLE\b', 'Federal', 'Title I-IV',
        'ESEA Title I/II/III/IV (Improving Basic Programs, Educator Effectiveness, ELL, Student Support)',
        'curated 2026-04-27'),
    ( 60, '\bIDEA\b', 'Federal', 'IDEA',
        'Individuals with Disabilities Education Act',
        'curated 2026-04-27'),
    ( 70, '\bMCKINNE', 'Federal', 'McKinney-Vento',
        'McKinney-Vento Homeless Education Assistance',
        'curated 2026-04-27'),
    ( 80, '\bCCLC\b', 'Federal', '21st CCLC',
        '21st Century Community Learning Centers',
        'curated 2026-04-27'),
    ( 90, '\bREAP\b', 'Federal', 'REAP',
        'Rural Education Achievement Program',
        'curated 2026-04-27'),
    (100, '\bNSLP\b|\bSBP\b|\bSFSP\b|\bNSLE\b', 'Federal', 'USDA NSLP/SBP/SFSP',
        'USDA child nutrition: National School Lunch / School Breakfast / Summer Food Service',
        'curated 2026-04-27'),
    (110, '\bESY\b', 'Federal', 'ESY',
        'Extended School Year (IDEA-related)',
        'curated 2026-04-27'),
    (120, '\bFED\b', 'Federal', 'FED-tagged',
        'Generic federal-source flag in Reference',
        'curated 2026-04-27'),
    (200, '\bEIA\b', 'State', 'EIA',
        'Education Improvement Act (1984)',
        'curated 2026-04-27'),
    (210, '\bARTS\b', 'State', 'Arts in BC',
        'Arts in Basic Curriculum',
        'curated 2026-04-27'),
    (220, '\bSAC\b|STATE\s+AID|\bCLASSROOMS?\b', 'State', 'SAC',
        'State Aid to Classrooms (per-pupil base aid)',
        'curated 2026-04-27'),
    (230, '\bEFA\b', 'State', 'EFA',
        'Education Finance Act',
        'curated 2026-04-27'),
    (240, 'PROP\s*TAX|REIMB.*PROP|PT\s*REIMB', 'State', 'Property Tax Reimb',
        'Property Tax Reimbursement to LEAs',
        'curated 2026-04-27'),
    (250, '\bLOTTERY\b', 'State', 'Lottery',
        'Lottery-funded state programs',
        'curated 2026-04-27'),
    (900, '^S\d{6}', 'Federal', 'S-period (USDA Nutrition)',
        'Period-coded USDA federal nutrition disbursement (NSLP/SBP/SFSP) routed through SC Dept of Education',
        'curated 2026-04-28 (corrected from SAC default)'),
    (910, '^F\d{6}', 'Federal', 'F-period (federal default)',
        'Period-coded federal disbursement (no explicit program acronym)',
        'curated 2026-04-27'),
    (920, '^U\d{6}', 'Federal', 'U-period (Prior-yr Nutrition payable)',
        'Prior-year payable of federal nutrition (timing-shifted S-period payment)',
        'curated 2026-04-28 (corrected from uncategorized)'),
    (930, '^X\d{6}', 'Other', 'X-period (uncategorized)',
        'Period-coded reference with X prefix; provenance unclear',
        'curated 2026-04-27')
ON CONFLICT (Rule_Order) DO UPDATE SET
    Pattern        = excluded.Pattern,
    Funding_Stream = excluded.Funding_Stream,
    Program_Tag    = excluded.Program_Tag,
    Description    = excluded.Description,
    Source         = excluded.Source;

-- ============================================================
-- Views
-- ============================================================

-- vw_sceis_fi_payments_classified: sceis_fi_payments joined to
-- lookup_sceis_program_classification; exposes Funding_Stream and
-- Program_Tag.  Use this view (not the raw table) for any
-- State/Federal split or per-program analysis.
CREATE OR REPLACE VIEW vw_sceis_fi_payments_classified AS
SELECT
    f.*,
    COALESCE(c.Funding_Stream, 'Other')     AS Funding_Stream,
    COALESCE(c.Program_Tag,    'unmatched') AS Program_Tag,
    c.Rule_Order                            AS Classification_Rule_Order
FROM sceis_fi_payments AS f
LEFT JOIN (
    SELECT Rule_Order, Funding_Stream, Program_Tag
    FROM   lookup_sceis_program_classification
    WHERE  regexp_matches(
               upper(regexp_replace(COALESCE(f.Reference, ''), '^\d{4}[\s\-_]*', '')),
               Pattern
           )
    ORDER BY Rule_Order
    LIMIT 1
) AS c ON TRUE;

-- vw_revenue_code_status: global statewide-dormancy mask for Revenue
-- codes.  Owned by code-catalog (computed from code_district_funding_streams
-- + lea_revenues).  Consumers must filter on Is_Statewide_Dormant = FALSE
-- unless explicitly auditing the catalog.
--
-- Dormancy rule: leaf-level code (Rollup_Level >= 3) with statewide $0
-- in each of the last 3 reported FYs (Reported_Flag=TRUE) and no Sunset_Note.
-- The view auto-refreshes from lea_revenues on every query.
CREATE OR REPLACE VIEW vw_revenue_code_status AS
WITH max_fy AS (
    SELECT MAX(FY) AS max_fy FROM lea_revenues WHERE Reported_Flag = TRUE
),
yearly_totals AS (
    SELECT Revenue_Code, FY, SUM(COALESCE(Amount, 0)) AS total
    FROM   lea_revenues
    WHERE  Reported_Flag = TRUE
    GROUP BY 1, 2
),
last_active AS (
    SELECT Revenue_Code, MAX(FY) FILTER (WHERE total != 0) AS last_active_fy
    FROM   yearly_totals
    GROUP BY 1
),
recent_window AS (
    SELECT
        yt.Revenue_Code,
        SUM(yt.total) FILTER (WHERE yt.FY >= (SELECT max_fy FROM max_fy) - 2) AS recent_3fy_total
    FROM yearly_totals yt
    GROUP BY 1
)
SELECT
    c.REV_Code,
    c.Stream_Type,
    c.Rollup_Level,
    c.Display_Title,
    c.Sunset_Note,
    la.last_active_fy                                           AS Last_Active_FY,
    (c.Rollup_Level <= 2)                                       AS Is_Rollup,
    (c.Sunset_Note IS NOT NULL)                                 AS Has_Sunset,
    (c.Rollup_Level >= 3
     AND c.Sunset_Note IS NULL
     AND COALESCE(rw.recent_3fy_total, 0) = 0)                 AS Is_Statewide_Dormant
FROM  code_district_funding_streams  c
LEFT JOIN last_active  la ON la.Revenue_Code = c.REV_Code
LEFT JOIN recent_window rw ON rw.Revenue_Code = c.REV_Code;

-- vw_budget_vs_actuals_by_funds_center: pivots sceis_fmeddw document
-- rows into (Funds_Center, Fiscal_Year) -> Total_Budget,
-- Estimated_Revenue, Actuals, Available, Pct_Consumed.
--
-- See internal-budget agent definition for the Budget_Type taxonomy.
-- Excludes Is_Rollup rows (8-char parent nodes) so per-center totals
-- do not double-count the agency rollup. ESTIMATED REVENUE is held
-- separate from Total_Budget because it is revenue-side budget, not
-- expenditure authority.
CREATE OR REPLACE VIEW vw_budget_vs_actuals_by_funds_center AS
SELECT
    Funds_Center,
    Fiscal_Year,
    SUM(CASE
        WHEN Budget_Type IN (
            'ORIGINAL APPROPRIATIONS',
            'SUPPLEMENTAL APPROPRIATIONS',
            'BUDGET ADJUSTMENTS',
            'Carryforward Gen Fund',
            'Carryforward Special Items',
            '2% APPROPRIATION BUDGET',
            'TRANSFER OF APPROPRIATIONS',
            'TRANSFER OF SALARY/FRINGE',
            'INTER-AGENCY TRANSFER',
            'ALLOCATIONS-TRSFRS FR EMPL BEN'
        ) THEN Amount ELSE 0
    END)                                                            AS Total_Budget,
    SUM(CASE WHEN Budget_Type = 'ESTIMATED REVENUE' THEN Amount ELSE 0 END)
                                                                    AS Estimated_Revenue,
    SUM(CASE
        WHEN Budget_Type = 'GM Budget Doc Type' AND Process = 'Receive' THEN Amount
        ELSE 0
    END)                                                            AS Actuals,
    SUM(CASE
        WHEN Budget_Type IN (
            'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
            'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
            'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
            'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
        ) THEN Amount ELSE 0
    END)
    -
    SUM(CASE WHEN Budget_Type='GM Budget Doc Type' AND Process='Receive' THEN Amount ELSE 0 END)
                                                                    AS Available,
    CASE WHEN
        SUM(CASE WHEN Budget_Type IN (
            'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
            'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
            'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
            'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
        ) THEN Amount ELSE 0 END) > 0
    THEN
        SUM(CASE WHEN Budget_Type='GM Budget Doc Type' AND Process='Receive' THEN Amount ELSE 0 END)
        / SUM(CASE WHEN Budget_Type IN (
            'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
            'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
            'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
            'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
        ) THEN Amount ELSE 0 END)
    END                                                             AS Pct_Consumed
FROM sceis_fmeddw
WHERE Is_Rollup = FALSE
GROUP BY Funds_Center, Fiscal_Year;

-- ============================================================
-- Org-chart and classifier dimensions (loaded from JSON by scripts)
-- ============================================================

-- dim_cost_center_office: maps every SAP cost center (H630*) to its
-- SCDE org-chart division and office.  Loaded by scripts/load_dim_cost_center_office.py
-- (or equivalent) from db/dim_cost_center_office.json.
-- 117 explicit entries + prefix rules for H630JG* / H630BU* covering all
-- 225 active cost centers.  Join on Cost_Center = Funds_Cost_Center /
-- Funds_Center in bex_fm_expense / vw_budget_vs_actuals_by_funds_center.
CREATE TABLE IF NOT EXISTS dim_cost_center_office (
    Cost_Center      VARCHAR PRIMARY KEY,
    Cost_Center_Name VARCHAR,
    Division         VARCHAR NOT NULL,
    Sub_Division     VARCHAR,
    Office           VARCHAR NOT NULL,
    Sub_Category     VARCHAR,
    Confidence       VARCHAR NOT NULL,  -- high / medium / low
    Note             VARCHAR
);

-- dim_functional_area: maps every SAP Functional Area code appearing in
-- any H630 transaction to a category (State Aid to Districts, State
-- Appropriation Activity, Federal Grant / Pass-Through, etc.).
-- 696 codes union'd across sceis_agency_master, sceis_detail_transaction,
-- sceis_fmeddw, bex_fi_vendor_invoice — 100% join coverage validated
-- 2026-05-14.  Loaded from db/dim_functional_area.json by
-- scripts/load_dim_functional_area.py.
-- NOTE: 6 Z-suffix rollup codes (H630_1ASZ, _660Z, _633Z, _573Z, _624Z,
-- _639Z) carry real FI-ledger postings (~$16.5M FY26) despite being FM
-- hierarchy nodes — exclude when aggregating with child codes (see Note).
CREATE TABLE IF NOT EXISTS dim_functional_area (
    Functional_Area  VARCHAR PRIMARY KEY,
    Name             VARCHAR,
    Category         VARCHAR NOT NULL,
    Confidence       VARCHAR NOT NULL,  -- high / medium / low
    FY26_5xxx_Spend  DOUBLE,
    Note             VARCHAR
);
