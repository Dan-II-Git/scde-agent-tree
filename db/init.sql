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
);

CREATE TABLE IF NOT EXISTS code_handbook_definitions (
    Term                VARCHAR PRIMARY KEY,
    Definition          VARCHAR,
    Category            VARCHAR
);

CREATE TABLE IF NOT EXISTS lookup_gl_account (
    GL_Account          VARCHAR PRIMARY KEY,
    SAP_Category        VARCHAR,
    Handbook_Code       VARCHAR,
    Handbook_Type       VARCHAR,
    Handbook_Name       VARCHAR
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
    ADM_135_Day             DECIMAL(12, 2),
    Weighted_Pupils         DECIMAL(12, 2),
    State_Allocation        DECIMAL(18, 2),     -- nullable for FY23+
    Local_Required_Support  DECIMAL(18, 2),     -- nullable for FY23+
    Audit_Standard          DECIMAL(18, 2),     -- nullable for FY23+
    PRIMARY KEY (District_ID, FY, Category)
);

-- ============================================================
-- Marts (populated by report agents as needed)
-- ============================================================

-- Reserved namespace; populated lazily.

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
