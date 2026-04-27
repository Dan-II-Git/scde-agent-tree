# SCDE Financial Data — Agent Tree

This project provides a hybrid agent tree for analysis and reporting against
South Carolina Department of Education financial data. The tree is organized
in three tiers:

```
                    ┌──────────────────────────┐
                    │  Orchestrator (you)      │
                    └──────────────┬───────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
   ┌────▼─────┐              ┌─────▼──────┐             ┌─────▼──────┐
   │  Layer   │              │   Cross-   │             │   Report   │
   │ agents   │              │  cutting   │             │   agents   │
   └────┬─────┘              └─────┬──────┘             └─────┬──────┘
        │                          │                          │
   sceis-data                 data-quality              report-<name>
   code-catalog               db-warehouse              ...
   lea-data
```

Layer agents own the file-format quirks for their slice of the ERD.
Cross-cutting agents enforce data-quality rules and manage the canonical DB.
Report agents consume layer outputs and emit HTML dashboards.

## Data sources

See `db/schema.md` for the full ERD reference. Files live in `data/uploads/`
once dropped from SCDE; canonical tables live in `db/scde.duckdb`.

Two parallel views of district money exist in the uploads:

- **System of record (SCEIS, state-side):** `FI_Payments_by_Vendor_FY*.xlsx`
  and `Detail_Transaction_Report_SCDE_*.xlsx`. Owned by `sceis-data`.
  Audited ledger of state-side outflows and transactions.
- **Self-reported (district-side):** `Revenue_FY*.xlsx` and
  `Expenditure_FY*.xlsx`. Owned by `lea-data`. Collected from districts;
  known accuracy and timing limitations.

Prefer SCEIS where the question is about a flow that touches the state
ledger. Fall back to LEA self-reports only for flows that never reach
SCEIS (local taxes/fees, district-side operational detail). See the
"System of record preferred" convention below.

## Conventions

- **Currency in caveats.** The ERD PDF (`docs/SCDE_Financial_Data_ERD.pdf`)
  is the source of truth for entity definitions and join semantics. Layer
  agents must respect every caveat in section 4 of that doc.
- **District identity.** Always prefer `District_ID` for joins where
  available. Fall back to normalized `District_Name` (strip whitespace,
  unify suffix conventions) only when no ID is present.
- **Signed amounts.** `DETAIL_TRANSACTION.Debit_Credit_Amount` is signed
  (H = negative, S = positive). Never abs() before aggregation.
- **System of record preferred.** When the same flow is covered by both
  the SCEIS files (`sceis_fi_payments`, `sceis_detail_transaction`) and
  the LEA self-reports (`lea_revenues`, `lea_expenditures`), use SCEIS.
  Self-reports are only authoritative for flows that never appear on
  the state ledger — local taxes/fees, district-side operational detail,
  some federal pass-through. When both sources cover a flow and disagree,
  surface the discrepancy as a data-quality caveat rather than picking
  one silently. Report agents that mix sources must document which
  bucket came from which source in the methodology footer.
- **Per-pupil normalization.** Reports default to 45-day Headcount
  (PowerSchool QDC1) as the denominator, NOT 135-day ADM. ADM is the
  funding metric; Headcount is the operational/policy view, which is
  what the comparison reports use.
- **Statewide aggregates** are weighted averages (sum of dollars over
  sum of pupils), not the arithmetic mean of district per-pupil rates.
- **Negatives use accounting parentheses.** Render negative currency as
  `$(1,234)`, not `-$1,234` or `$−1,234`. Applies to every numeric cell,
  KPI, footnote, chart axis label, and tooltip in HTML reports, and to
  any prose total quoted by a layer agent (e.g. "7 rows total $(228,269)").
  Zero is `$0`, never `$(0)`. The minus glyph and the `-` prefix should
  not appear next to dollar amounts in user-facing output. Style negatives
  with `var(--danger-fg)` from the Look Deeper tokens so they read at a
  glance.
- **HTML dashboards.** Report outputs default to single-file HTML using
  the **Look Deeper design system** at `docs/style/look-deeper-design-system.html`
  as the canonical reference. Lift its `:root` design tokens (SCDE
  palette, Poppins/JetBrains Mono typography, 4px spacing scale, radius,
  shadows) and component patterns (cards, tables, badges, KPI tiles)
  rather than reinventing styling per report. Charts use Recharts via
  inline ES modules and should consume the same brand tokens
  (`--brand-navy`, `--brand-gold`, `--brand-slate`) for series colors.
- **Tooltips on codes.** Every accounting code rendered in a report
  must have a hover/tap tooltip showing its handbook description, with
  a way to expand to the full definition. Use Tippy.js, not native
  `title` attributes. Source: `code_accounting_codes.Short_Description`
  and `Full_Description`.
- **Data dictionary.** Schema descriptions live in two places:
  `db/schema.json` (source of truth) and DuckDB column comments
  (queryable via `duckdb_columns()`). Any agent rendering a column
  name in a UI should pull the description from the live DB rather
  than hardcoding it. Run `python3 db/apply_comments.py` after any
  schema.json edit to keep them in sync.

## Delegation rules

For ANY user request involving data:

1. If the request names a specific report → invoke `report-<name>` directly
2. If the request is exploratory → invoke the relevant layer agent
3. If the request crosses layers → invoke layer agents in parallel,
   synthesize in the orchestrator
4. Before writing to the canonical DB → invoke `data-quality` to validate

For requests that update reference data (handbook, GL lookup):

1. Invoke `code-catalog` to stage the change
2. Invoke `data-quality` to validate impact on dependent tables
3. Apply the change only after both report success
