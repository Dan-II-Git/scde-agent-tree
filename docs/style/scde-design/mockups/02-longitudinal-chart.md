# Mockup 02 — Longitudinal Chart with Projection

Shows the Revenue vs Expenditure chart with all known-limitations affordances: historical/projected treatment, 80% confidence bands, partial-FY badge, method tooltip.

## Layout — normal (well-calibrated) series

```
+------------------------------------------------------------------------------------+
|  Revenue vs Expenditure — Greenville 01           [View: ● Public  ○ Analyst]      |
|                                                                                    |
|  800M |                                           ○----○----○                      |
|       |                                         ░░░░░░░░░░░░░  <- projected band   |
|  700M |                                 ●-----●-○                                  |
|       |                               ●                                            |
|  600M |                    ●-------●-●                                             |
|       |       ●-------●---●                                                        |
|  500M |  ●---●                                                                     |
|       |                                                                            |
|  400M +--+--------+--------+--------+--------+--------+--------+----                |
|         FY21-22  FY22-23  FY23-24  FY24-25 |FY25-26 FY26-27  FY27-28               |
|                                         ^^^^^                                      |
|                                 historical | projected                             |
|                                                                                    |
|   Legend:  ━● Revenue (historical)   - -○ Revenue (projected, 80% CI)              |
|            ━● Expenditure (historical) - -○ Expenditure (projected, 80% CI)        |
|                                                                                    |
|   [Show data table ▾]   Method: Linear regression (auto-selected) [?]              |
+------------------------------------------------------------------------------------+

Tooltip on hover of projected point FY26-27:
    +--------------------------------+
    | FY26-27 Revenue                |
    | $714.2M (range $671M – $757M)  |
    | Method: Linear regression      |
    | 80% confidence band            |
    +--------------------------------+
```

## Layout — partial-FY series (Charleston 01, Richland 01, SC Public Charter)

```
+------------------------------------------------------------------------------------+
|  Revenue vs Expenditure — Charleston 01                                            |
|  ┌─────────────────────────────────────────────────────────────────┐              |
|  │ ⚠ FY24-25 data incomplete — projection uses FY21-22 … FY23-24   │ <- A badge   |
|  └─────────────────────────────────────────────────────────────────┘              |
|                                                                                    |
|  800M |                                      ○─ ─ ─○─ ─ ─○                        |
|       |                                   ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ <- wider gold band    |
|  700M |                    ●───●   (FY24-25 dropped)                              |
|       |           ●───●                                                            |
|  600M |   ●───●                                                                    |
|       +--+--------+--------+---(gap)---+--------+--------+--------+----             |
|          FY21-22  FY22-23  FY23-24   FY24-25* FY25-26  FY26-27  FY27-28            |
|                                      ^partial                                      |
|                                                                                    |
|   * Partial-FY — dropped from training, shown as light marker only                |
+------------------------------------------------------------------------------------+
```

## Layout — insufficient-data series

```
+------------------------------------------------------------------------------------+
|  Object 0199 Other Regular Instr. — Abbeville 60                                   |
|                                                                                    |
|   2K  |                                                                            |
|       |         ●                                                                  |
|   1K  |                    ●                                                       |
|       |  ●                               ╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱                |
|   0K  +--●-----------●-------●---+-------╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱╱-----              |
|          FY21-22 FY22-23 FY23-24         No projection — insufficient historical    |
|                                           data (need 4 FYs; have 3)                |
+------------------------------------------------------------------------------------+
```

## Elements

| Label | Description |
|---|---|
| Chart title | Statement-type + district name, `type.scale.xl` |
| View toggle | Public / Analyst radio, top-right (see mockup 05) |
| Y-axis | Currency, SI-suffixed ticks, right-aligned |
| X-axis | Fiscal-year labels |
| Historical line | Solid 2.5px, filled 4px markers |
| Projected line | Dashed 2px (dash-array 6 4), hollow markers |
| Confidence band | 20% opacity fill of projection line color, no stroke |
| Partial-FY badge | Gold pill with primary-color text, top of chart |
| Partial-FY band | 22% opacity gold, wider than normal band |
| Insufficient-data region | Diagonal hatch + inline message |
| Legend | Below chart, shows both historical (solid+filled) and projected (dashed+hollow) for each series |
| Method footer | Method name + `[?]` tooltip (analyst view only; collapsed to just name in public view) |

## Interactions

- Hover any marker → tooltip with exact value, 80% CI range, and chosen method.
- Hover the legend swatch → highlights that series; dims the others to 40% opacity.
- Click the badge → opens an explanation popover: "Why is this flagged?"
- `[?]` next to Method → opens a tooltip explaining Linear / Log-linear / Growth-rate / Flat (analyst view only).
- Keyboard: Left/Right arrow cycles between data points when chart is focused, announcing value via live region.

## Token references

- Historical: `color.data.projection.historical` (`#234058`)
- Projected: `color.data.projection.projected` (`#43718B`)
- Normal band: `color.data.projection.band_fill` @ 20%
- Partial-FY badge bg: `color.data.projection.partial_fy_badge` (`#F1BA55`); fg: `color.brand.primary` (6.28:1 PASS)
- Partial-FY band: `color.data.projection.partial_fy_band` @ 22%
- Insufficient hatch: `color.data.projection.insufficient_gap` @ 35%
- Insufficient text: `color.semantic.neutral_fg` (AA PASS on both white and hatch overlay)
- Gridlines: `color.semantic.border_subtle` @ 50%
- Chart container border: 1px `color.semantic.border` (3:1 AA PASS)

## Accessibility

- Chart wrapped in `<figure>` with `<figcaption>` that reads "Revenue vs Expenditure for Greenville 01 from FY21-22 through FY27-28. Three years of projections with 80% confidence intervals."
- "Show data table" link renders a visually-hidden `<table>` with one row per (series, FY) including lower/upper CI columns for projected points.
- Partial-FY badge has `role="status"` so it is announced when appearing after filter changes.
- Insufficient-data message is real text (not an image), so it is read by screen readers.
- Color is never the sole cue:
  - Historical vs projected distinguished by line-style + marker-fill (not color alone).
  - Partial-FY distinguished by badge text + wider band (not color alone).
  - Insufficient-data distinguished by hatch pattern + text (not color alone).
- Band fills do not trap focus; only markers and legend items are in the tab sequence.
