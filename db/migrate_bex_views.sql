-- BEx integration: view migration
-- Applied: 2026-05-13
-- Run via: duckdb db/scde.duckdb < db/migrate_bex_views.sql
--
-- Data-quality caveats honoured:
--   #1  FY26 partial through 2026-05-08: vw_fy_status carries FY_Status + As_Of_Date
--   #2  bex_fm_expense.FY_Total is negative-for-expense: Actuals = SUM(-FY_Total)
--   #3  Encumbrance scope is H630 FM-area only
--   #4  BvA budget at CI_Level=6; actuals at CI_Level=10 (agg to SUBSTR(CI,1,6) when joining)
--   #7  11 FY26 POs have negative Remaining_Balance: floored via GREATEST(.,0)
--   #8  True_Available = Current_Budget + SUM(FY_Total) - GREATEST(SUM(enc),0)
--       = Current_Budget - Actuals - Open_Encumbrances (after sign conventions applied)

-- ── vw_fy_status ────────────────────────────────────────────────────

CREATE OR REPLACE VIEW vw_fy_status AS
WITH max_fy AS (
    SELECT MAX(Fiscal_Year) AS max_fy FROM bex_fi_vendor_invoice
),
fy_dates AS (
    SELECT
        Fiscal_Year,
        MAX(Posting_Date) AS as_of_date
    FROM bex_fi_vendor_invoice
    GROUP BY Fiscal_Year
)
SELECT
    fd.Fiscal_Year,
    CASE
        WHEN fd.Fiscal_Year = (SELECT max_fy FROM max_fy) THEN 'Partial'
        ELSE 'Complete'
    END AS FY_Status,
    fd.as_of_date AS As_Of_Date
FROM fy_dates fd;

-- ── vw_budget_vs_actuals_by_fund ────────────────────────────────────
-- Grain: Fund_Code x Fiscal_Year. Authoritative for budget.

CREATE OR REPLACE VIEW vw_budget_vs_actuals_by_fund AS
WITH budget AS (
    SELECT
        Fund_Code,
        MAX(Fund_Name)      AS Fund_Name,
        Fiscal_Year,
        SUM(Current_Budget) AS Current_Budget
    FROM bex_budget_vs_actuals
    WHERE CI_Level = 6
      AND Fund_Code IS NOT NULL
    GROUP BY Fund_Code, Fiscal_Year
),
actuals AS (
    SELECT
        Fund,
        Fiscal_Year,
        SUM(-FY_Total) AS Actuals
    FROM bex_fm_expense
    WHERE Fund IS NOT NULL
    GROUP BY Fund, Fiscal_Year
),
encumbrances AS (
    SELECT
        Fund,
        Fiscal_Year,
        SUM(GREATEST(Remaining_Balance, 0))                         AS Open_Encumbrances,
        SUM(CASE WHEN Remaining_Balance < 0 THEN Remaining_Balance ELSE 0 END)
                                                                    AS Over_Invoiced_Amount
    FROM bex_open_encumbrances
    WHERE Fund IS NOT NULL
    GROUP BY Fund, Fiscal_Year
)
SELECT
    b.Fund_Code,
    b.Fund_Name,
    b.Fiscal_Year,
    b.Current_Budget,
    COALESCE(a.Actuals,           0) AS Actuals,
    COALESCE(e.Open_Encumbrances, 0) AS Open_Encumbrances,
    COALESCE(e.Over_Invoiced_Amount, 0)                             AS Over_Invoiced_Amount,
    b.Current_Budget
        - COALESCE(a.Actuals,           0)
        - COALESCE(e.Open_Encumbrances, 0)                         AS True_Available,
    CASE WHEN b.Current_Budget > 0
         THEN COALESCE(a.Actuals, 0) / b.Current_Budget
    END                                                             AS Pct_Spent,
    s.FY_Status,
    s.As_Of_Date
FROM budget b
LEFT JOIN actuals      a ON a.Fund = b.Fund_Code AND a.Fiscal_Year = b.Fiscal_Year
LEFT JOIN encumbrances e ON e.Fund = b.Fund_Code AND e.Fiscal_Year = b.Fiscal_Year
LEFT JOIN vw_fy_status s ON s.Fiscal_Year = b.Fiscal_Year;

-- ── vw_budget_vs_actuals_by_funds_center ────────────────────────────
-- Grain: Funds_Center x Fiscal_Year.
-- Actuals from BEx (FY25+26). Budget from FMEDDW (FY26 only — NULL for FY25).
-- Encumbrances from BEx Open Encumbrances (H630 scope).
-- Legacy columns (Total_Budget, Estimated_Revenue, Available, Pct_Consumed)
-- retained for backward compatibility with existing queries.py callers.

CREATE OR REPLACE VIEW vw_budget_vs_actuals_by_funds_center AS
WITH bex_actuals AS (
    SELECT
        Funds_Cost_Center AS Funds_Center,
        Fiscal_Year,
        SUM(-FY_Total)    AS Actuals
    FROM bex_fm_expense
    GROUP BY Funds_Cost_Center, Fiscal_Year
),
bex_encumbrances AS (
    SELECT
        Funds_Center,
        Fiscal_Year,
        SUM(GREATEST(Remaining_Balance, 0))                         AS Open_Encumbrances,
        SUM(CASE WHEN Remaining_Balance < 0 THEN Remaining_Balance ELSE 0 END)
                                                                    AS Over_Invoiced_Amount
    FROM bex_open_encumbrances
    WHERE Funds_Center LIKE 'H630%'
    GROUP BY Funds_Center, Fiscal_Year
),
fmeddw_budget AS (
    SELECT
        Funds_Center,
        Fiscal_Year,
        SUM(CASE WHEN Budget_Type IN (
            'ORIGINAL APPROPRIATIONS','SUPPLEMENTAL APPROPRIATIONS','BUDGET ADJUSTMENTS',
            'Carryforward Gen Fund','Carryforward Special Items','2% APPROPRIATION BUDGET',
            'TRANSFER OF APPROPRIATIONS','TRANSFER OF SALARY/FRINGE',
            'INTER-AGENCY TRANSFER','ALLOCATIONS-TRSFRS FR EMPL BEN'
        ) THEN Amount ELSE 0 END)                                   AS Total_Budget,
        SUM(CASE WHEN Budget_Type = 'ESTIMATED REVENUE'
                 THEN Amount ELSE 0 END)                            AS Estimated_Revenue,
        SUM(CASE WHEN Budget_Type = 'GM Budget Doc Type'
                      AND Process = 'Receive'
                 THEN Amount ELSE 0 END)                            AS FMEDDW_Actuals
    FROM sceis_fmeddw
    WHERE Is_Rollup = FALSE
    GROUP BY Funds_Center, Fiscal_Year
),
all_fcs AS (
    SELECT DISTINCT Funds_Center, Fiscal_Year FROM bex_actuals
    UNION
    SELECT DISTINCT Funds_Center, Fiscal_Year FROM bex_encumbrances
    UNION
    SELECT DISTINCT Funds_Center, Fiscal_Year FROM fmeddw_budget
)
SELECT
    f.Funds_Center,
    f.Fiscal_Year,
    -- Legacy budget column (FY26 from FMEDDW; NULL for FY25)
    fb.Total_Budget,
    fb.Estimated_Revenue,
    -- Authoritative actuals from BEx FM Expense
    COALESCE(ba.Actuals,           0)  AS Actuals,
    -- FMEDDW GM-Receive actuals for reconciliation
    COALESCE(fb.FMEDDW_Actuals,    0)  AS FMEDDW_Actuals,
    COALESCE(be.Open_Encumbrances, 0)  AS Open_Encumbrances,
    COALESCE(be.Over_Invoiced_Amount, 0) AS Over_Invoiced_Amount,
    -- True_Available uses BEx actuals; NULL when budget is unavailable (FY25)
    CASE WHEN fb.Total_Budget IS NOT NULL
         THEN fb.Total_Budget
                - COALESCE(ba.Actuals, 0)
                - COALESCE(be.Open_Encumbrances, 0)
    END                                AS True_Available,
    -- Legacy Pct_Consumed for existing callers
    CASE WHEN fb.Total_Budget > 0
         THEN COALESCE(ba.Actuals, 0) / fb.Total_Budget
    END                                AS Pct_Consumed,
    -- Legacy Available (no encumbrance deduction) for existing callers
    CASE WHEN fb.Total_Budget IS NOT NULL
         THEN fb.Total_Budget - COALESCE(ba.Actuals, 0)
    END                                AS Available,
    s.FY_Status,
    s.As_Of_Date,
    'Budget tracked at Fund level - see vw_budget_vs_actuals_by_fund.'
        AS Budget_Note
FROM all_fcs f
LEFT JOIN bex_actuals     ba ON ba.Funds_Center = f.Funds_Center AND ba.Fiscal_Year = f.Fiscal_Year
LEFT JOIN bex_encumbrances be ON be.Funds_Center = f.Funds_Center AND be.Fiscal_Year = f.Fiscal_Year
LEFT JOIN fmeddw_budget   fb ON fb.Funds_Center = f.Funds_Center AND fb.Fiscal_Year = f.Fiscal_Year
LEFT JOIN vw_fy_status     s  ON s.Fiscal_Year  = f.Fiscal_Year;
