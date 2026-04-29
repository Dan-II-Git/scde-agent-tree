# Canonical DB Schema

Single-file DuckDB at `db/scde.duckdb`. Tables are namespaced by source layer.
Each layer's specialist agent owns its tables; `db-warehouse` owns the file.

## Two-file documentation pattern

This file is the **human-readable** schema overview — table list, layout
conventions, where to make changes. The **machine-readable** version is
`db/schema.json`, which is the source of truth for column descriptions
and is applied to the live DB via `python3 db/apply_comments.py`.

Once applied, descriptions are queryable as standard DuckDB column
comments:

```sql
SELECT column_name, comment FROM duckdb_columns()
WHERE table_name = 'sceis_detail_transaction';
```

This means **any agent — report, schema-explorer, or otherwise — can
fetch tooltip-friendly descriptions for any table or column with a
single SQL query**. No custom parsers, no markdown scraping.

When schema changes, update both files: schema.json holds the
descriptions; init.sql holds the DDL. Re-run `apply_comments.py`
after either changes.

## Conventions

- All amount columns are `DECIMAL(18, 2)` unless otherwise noted
- All date columns are `DATE`; timestamps are `TIMESTAMP`
- All FY/SY columns are `SMALLINT` (e.g., 2025 not "2024-25")
- Primary keys are explicit even on staging tables
- Stored procedures live in `db/procs/`

## Tables (current)

### Dimensions
- `dim_district` (District_ID PK, District_Name, normalized_name, source_files[])
- `dim_fiscal_year` (FY PK, start_date, end_date, sy_label)
- `dim_district_geometry` (District_ID PK, GEOID, District_Name_Normalized, GeoJSON_Name, LSAD, Geometry_GeoJSON, Has_Geometry, Centroid_Lon, Centroid_Lat, Match_Method, Match_Confidence, Notes, Source_File, Loaded_At) — 83 rows; 72 with Census TIGER polygons, 11 without (statewide charters, special schools, Barnwell merger remnants). Florence 01 includes unioned pre-2013 Florence 4 territory. Source: `data/geo/sc_districts.geojson`.

### sceis_*  — owned by `sceis-data`
- `sceis_agency_master` (Cost_Center PK, Name, Functional_Area, Mini_Code FK, ...)
- `sceis_detail_transaction` (Doc_Number, Doc_Item PK, ...)
- `sceis_fi_payments` (Doc_Number, Item PK, Vendor, Clearing_Doc_Number FK, ...)

### lea_*  — owned by `lea-data`
- `lea_revenues` (District_ID, Revenue_Code, FY PK, Amount)
- `lea_expenditures` (District_ID, Function_Code, FY PK, Amount)
- `lea_adm_counts` (District_ID, School_Code, SY PK, Report_Cycle, Total_Membership, ...)
- `lea_headcounts` (District_ID, SY PK, Report_Cycle, Total_Active_Enrollment, ...)
- `lea_wpu_allocations` (District_ID, FY, Category, Report_Cycle PK — composite; Weighted_Pupils, ...) — `Report_Cycle` is 45 (preliminary/early-year) or 135 (funding-final). Both cycles can coexist for the same (district, FY). Existing rows are 135-day; 45-day rows come from WPU04522–WPU04526.xlsx uploads.

### code_*  — owned by `code-catalog`
- `code_accounting_codes` (Code, Type PK, Full_Name, Display_Name, ...)

  **Load-time caveat — excluded sub-items.** The table holds one row per
  `(Code, Type)`. Four handbook sub-items were excluded at load time because
  the source xlsx does not assign them distinct codes; fabricating suffix codes
  was rejected in favor of documenting the gap (option c). Downstream joins
  must use `(Code, Type)` and must not assume sub-item granularity.

  Excluded sub-items:
  - `(4310, Revenue)` — "Title I, Part C — Education of Migratory Children".
    Note: `4310C` exists in `code_district_funding_streams` and resolves to
    the parent via the regex join. The parent's `Full_Description` explicitly
    names all sub-programs, so tooltip lookups still surface the relevant
    definition.
  - `(4310, Revenue)` — "Title I, Part D — Neglected and Delinquent Program"
  - `(4310, Revenue)` — "Title I, Section 1003(A) — School Improvement"
  - `(420, Function)` — "Transfer to General Fund (Exclude Indirect Cost)"

- `code_district_funding_streams` (REV_Code PK, Stream_Type, Rollup_Level, ...,
  `Allocation_Basis` VARCHAR — allocation method from the State sheet "Allocation Data"
  column: `'PowerSchool ADM'`, `'PS ADM'`, `'Categorical'`, `'District FTEs'`, or NULL
  (NULL is correct for Federal/Local rows). Used by `funding-projections` to route
  each REV_Code to the SAC formula or trend method;
  `Sunset_Note` VARCHAR — notes from the inventory for time-limited streams, e.g.
  `"Closed, last paid FY23"`. Both columns added for the funding-projections agent.)
- `code_historical_revenue_codes` (Code, Type PK, Full_Name, Display_Name,
  Short_Description, Full_Description, Last_Active_FY, Program_Authority)

  Retired or time-limited revenue codes no longer in the current handbook but
  present in historical `lea_revenues` rows. Current seed rows: 3143 (GEER
  CERDEP Summer, CARES Act Sec. 18002) and 3995 (CRF Per Pupil Funding, CARES
  Act Sec. 5001), both with `Last_Active_FY = 2025`.

  **Mart join pattern.** When building `mart_district_revenue_rollup` or any
  mart that joins `lea_revenues` to a description table, use a LEFT JOIN to
  both `code_accounting_codes` (current) and `code_historical_revenue_codes`
  (retired), then COALESCE the description columns in that order:

  ```sql
  LEFT JOIN code_accounting_codes      c  ON r.Revenue_Code = c.Code  AND c.Type = 'Revenue'
  LEFT JOIN code_historical_revenue_codes h ON r.Revenue_Code = h.Code AND h.Type = 'Revenue'
  -- then in SELECT:
  COALESCE(c.Short_Description, h.Short_Description) AS Short_Description
  ```

  This ensures both current and historical codes surface descriptions without
  modifying the authoritative handbook table.

- `code_handbook_definitions` (Term PK, Definition, Category)

### policy_*  — owned by `code-catalog`
- `policy_rate_assumptions` (FY, parameter, scenario PK — composite; value DECIMAL(18,4),
  source, notes) — annual per-pupil rate inputs for funding-projection formulas. Seeded
  manually from the SC Appropriations Act. Scenarios: `'baseline'` (v1), with future
  scenarios (`'flat_funding'`, `'bsc_+3pct'`) anticipated. The `funding-projections`
  agent reads this table when computing SAC formula projections. Do not auto-populate
  from the projection pipeline; changes require a `code-catalog` agent task.

### lookup_*  — owned by `code-catalog`
- `lookup_gl_account` (GL_Account PK, SAP_Category, Handbook_Code FK, Handbook_Type)

### mart_*  — owned by report agents (denormalized for HTML dashboards)
- `mart_district_revenue_rollup` (District_ID, FY, Revenue_Code, Stream_Type,
   Category, Display_Title, Rollup_Level, Amount) — owned by
   `report-district-revenue`. Joins lea_revenues to
   code_district_funding_streams + code_accounting_codes; rebuilt
   when either source changes.
- `mart_funding_projections` (District_ID, FY, Revenue_Code, Scenario PK —
   composite; Stream_Type, Allocation_Basis, Amount, Lower_80, Upper_80,
   Method, Built_At) — owned by `funding-projections` agent (not yet
   implemented). Point estimates and 80% prediction-interval bounds per
   district + revenue code + projection scenario. Method values:
   `'formula_sac'` (SAC per-WPU formula using policy_rate_assumptions),
   `'trend_ols'` (ordinary least-squares trend), `'sunset_zero'` (forced
   to zero after sunset year from code_district_funding_streams.Sunset_Note),
   `'insufficient_history'` (fewer than 3 data points). Rebuilt by the
   agent's pipeline SQL; do not manually INSERT.

## Schema changes

Any agent proposing a schema change must:
1. Edit this file with the proposed change
2. Invoke `data-quality` to validate
3. Invoke `db-warehouse` to apply with snapshot

Never modify schema directly via `bash duckdb` calls — go through the warehouse agent.
