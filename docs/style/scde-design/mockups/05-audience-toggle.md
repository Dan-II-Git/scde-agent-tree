# Mockup 05 — Audience Toggle (Public vs Analyst)

Public view is the default. Analyst view is opt-in via the header toggle and adds technical columns, tooltips, and caveats.

## Layout — Header toggle

```
+------------------------------------------------------------------------------------+
| [LOGO]  SCDE Finance Dashboard                      View: (●) Public  ( ) Analyst  |
+------------------------------------------------------------------------------------+
```

## Side-by-side — chart differences

### Public (default)

```
+------------------------------------------------------------------+
|  Revenue vs Expenditure — Greenville 01                          |
|                                                                  |
|  [chart with solid/dashed lines + 80% CI bands]                  |
|                                                                  |
|  Legend:                                                         |
|   ━● Revenue (historical)   - -○ Revenue (projected, 80% CI)     |
|                                                                  |
|   Projection quality: ±3.5% of total (dollar-weighted RMSE)      |
+------------------------------------------------------------------+
```

### Analyst

```
+------------------------------------------------------------------+
|  Revenue vs Expenditure — Greenville 01           [Analyst view] |
|                                                                  |
|  [same chart, PLUS hover tooltip shows method name]              |
|                                                                  |
|  Legend:                                                         |
|   ━● Revenue (historical)   - -○ Revenue (projected, 80% CI)     |
|                                                                  |
|   Projection quality:                                            |
|     • wRMSE: $25.6M (3.5% of FY23-24 total) — primary gauge      |
|     • MAPE: 8.1% [?] — inflated by small-dollar lines            |
|     • Method-mix: Linear 58%, Log-linear 14%, Growth 23%, Flat 5%|
|     • Backtest coverage: 94% of series                           |
|                                                                  |
|   [Download methodology PDF]                                     |
+------------------------------------------------------------------+
```

## Side-by-side — drilldown-table differences

| Column | Public | Analyst |
|---|---|---|
| Obj Code | ✓ | ✓ |
| Name | ✓ | ✓ |
| FY23-24 actual | ✓ | ✓ |
| FY24-25 actual | ✓ | ✓ |
| FY25-26 projection | ✓ | ✓ |
| Flag (partial / no data) | ✓ | ✓ |
| Method (Linear / Log-linear / Growth / Flat) |  | ✓ |
| wRMSE |  | ✓ |
| MAPE with `[?]` caveat tooltip |  | ✓ |
| Backtest-coverage note |  | ✓ |

## Side-by-side — KPI card differences

| KPI | Public shows | Analyst adds |
|---|---|---|
| Total Revenue | Dollar value | Projection confidence interval as subtitle |
| Total Expenditure | Dollar value | Projection confidence interval as subtitle |
| Net Position | Delta with up/down icon | Method used for the delta forecast |
| Budget Utilization | Percent with bar | n/a — actual data, no projection |

## Interactions

- Toggle persists in `localStorage` so a returning analyst doesn't need to re-enable.
- When Analyst is active, a subtle gold band labeled "Analyst view" is shown under the header so exported PDFs and screenshots cannot be confused with the public summary.
- The toggle is keyboard-focusable and uses ARIA radiogroup semantics.
- Switching views animates neither the chart nor the table (instant swap) to avoid implying a data transition.
- Analyst-view tooltips (Method `[?]`, MAPE `[?]`) include the exact caveat text from Verifier 3.

## Token references

- Public view header band: none
- Analyst view header band: `color.data.projection.partial_fy_badge` bg (`#F1BA55`) with `color.brand.primary` fg text "Analyst view" (6.28:1 AA PASS)
- Toggle track: `color.semantic.border`
- Toggle thumb (active): `color.brand.secondary`
- Toggle text labels: `color.semantic.neutral_fg`
- Disclosure icon `[?]`: `color.brand.tertiary` default, `color.brand.primary` on hover

## Accessibility

- Toggle implemented as `<fieldset>` + two `<input type="radio">` with `role="radiogroup"` and an accessible group name ("View mode").
- When view changes, an `aria-live="polite"` region announces "Switched to analyst view. Method, RMSE, and MAPE columns now visible."
- Nothing in the analyst view relies on color alone:
  - Added columns have textual headers.
  - "Analyst view" band is a text label (not just color).
  - `[?]` icons are focusable buttons with textual tooltips.
- Toggle setting persisted to `localStorage` but never read from or sent to any external source; all audience-level adjustments are client-side and deterministic.
- Public-view-by-default respects the requirement: "public default + analyst toggle" (requirements.md).
