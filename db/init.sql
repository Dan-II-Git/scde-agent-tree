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
