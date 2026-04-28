# Mockup 03 — Line-Item Drilldown Table

Per-code (Object or Function or Revenue source) drilldown with Method column shown in analyst view only.

## Layout — Public view

```
+------------------------------------------------------------------------------------+
|  Greenville 01 › Expenditure › by Object                      [Back to overview]   |
|                                                                                    |
|  Filter: [All Objects ▾]   Sort: [Dollar impact ▾]                                 |
|                                                                                    |
|  +------+-------------------------+-----------+-----------+-----------+---------+  |
|  | Obj  | Name                    |  FY23-24  |  FY24-25  |  FY25-26  |  Flag   |  |
|  | Code |                         |  actual   | actual/est|  proj.    |         |  |
|  +------+-------------------------+-----------+-----------+-----------+---------+  |
|  | 0100 | Salaries - Teachers     | $210,453K | $219,101K | $228,720K |         |  |
|  |      |                         |           |           | ($217-240K)|        |  |
|  +------+-------------------------+-----------+-----------+-----------+---------+  |
|  | 0200 | Employee Benefits       | $74,892K  | $77,800K  | $80,930K  |         |  |
|  |      |                         |           |           | ($76-86K)  |        |  |
|  +------+-------------------------+-----------+-----------+-----------+---------+  |
|  | 0300 | Purch. Services         | $18,114K  | $17,905K  | $17,760K  | ⚠ partial|  |
|  |      |                         |           |           | ($14-22K)  |        |  |
|  +------+-------------------------+-----------+-----------+-----------+---------+  |
|  | 0199 | Other Regular Instr.    | $0        | $0        |   —       | no data |  |
|  +------+-------------------------+-----------+-----------+-----------+---------+  |
|                                                                                    |
|  Showing 24 of 133 object codes. [Load more] [Export to PDF]                      |
+------------------------------------------------------------------------------------+
```

## Layout — Analyst view (adds Method + MAPE columns)

```
+------+-----------------+----------+----------+----------+--------+----------+--------+
| Obj  | Name            | FY23-24  | FY24-25  | FY25-26  | Method | wRMSE    | MAPE[?]|
+------+-----------------+----------+----------+----------+--------+----------+--------+
| 0100 | Salaries-Teach. | $210,453K| $219,101K| $228,720K| Linear | $4.1M    | 1.8%   |
| 0200 | Emp. Benefits   | $74,892K | $77,800K | $80,930K | Linear | $1.8M    | 2.3%   |
| 0300 | Purch. Svcs     | $18,114K | $17,905K | $17,760K | Growth | $2.1M    | 12.4%* |
| 0199 | Other Reg.Instr.| $0       | $0       |  —       |   —    |    —     |  —     |
+------+-----------------+----------+----------+----------+--------+----------+--------+

  [?] on MAPE header shows tooltip: "MAPE is inflated by small-dollar denominator
      lines (|actual| < $1,000). Use wRMSE as the primary quality gauge."
  * = MAPE may be misleading for this series; see note above.
```

## Elements

| Label | Description |
|---|---|
| Breadcrumb | District › Statement type › Breakdown. Clickable. |
| Filter | Restrict to a specific code or group. |
| Sort | Default "Dollar impact" (abs $ of projection delta). |
| Table header | Sticky on scroll; `<th scope="col">`. |
| Confidence range | Second line under projection cell, `type.scale.xs`, `color.brand.tertiary`. |
| Flag column (public) | Three states: blank (ok), ⚠ partial (gold badge), "no data" (subtle gray). |
| Method column (analyst only) | Linear / Log-linear / Growth / Flat / — |
| wRMSE column (analyst only) | Dollar-weighted RMSE from backtest. |
| MAPE column (analyst only) | Percent with `[?]` tooltip explaining caveat. |

## Interactions

- Clicking a row opens mockup 02 filtered to that specific (district, statement_type, code) series.
- Clicking the "⚠ partial" badge opens the same explanation popover as in mockup 02.
- MAPE `[?]` opens tooltip with the exact caveat text from Verifier 3's notes.
- Column sort indicators use arrow icon + `aria-sort` on the `<th>`.
- Hovering the "no data" row shows tooltip "Insufficient historical data — need 4 FYs, have N."

## Token references

- Table background: `#FFFFFF`
- Row stripe: `color.semantic.neutral_bg` (alternating)
- Row hover: `color.brand.tertiary` @ 8% opacity
- Row border: `color.semantic.border_subtle` (decorative only)
- Partial badge: `color.data.projection.partial_fy_badge` bg / `color.brand.primary` fg
- No-data pill: `color.semantic.border` bg / `color.semantic.neutral_fg` fg
- Method column text: `color.brand.secondary`
- Negative currency: `color.semantic.danger` in parentheses
- Column header typography: `type.scale.sm` bold
- Body cell typography: `type.scale.sm` in mono for numeric columns, Poppins for name columns

## Accessibility

- Full `<table>` semantics with `<caption>`, `<thead>`, `<tbody>`, `<th scope="col">` on headers and `<th scope="row">` on the Obj-code first cell.
- `aria-sort` reflects current sort state.
- Method column has visible text label (not icon alone), so screen-reader users get the method name directly.
- Badge text is plain text inside a styled span; no aria-label needed beyond the visible text.
- Numeric cells right-aligned visually but left-to-right in DOM so screen readers read "two hundred ten million ..." naturally.
- The `[?]` MAPE tooltip is keyboard-focusable and activated by Enter/Space/Esc-to-dismiss.
- Sticky header does not trap focus; focus moves through rows top-to-bottom.
