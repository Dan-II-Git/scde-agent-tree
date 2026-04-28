# Mockup 01 — Landing Page

## Layout

```
+------------------------------------------------------------------------------------+
| [LOGO-horiz-light]  SCDE Finance Dashboard                    [Public ▾] [? Help] | <-- A
+------------------------------------------------------------------------------------+
|                                                                                    |
|  Select district(s):  [Greenville 01 ▾] [+ Add district]        FY: [FY25-26 ▾]   | <-- B
|                                                                                    |
+------------------------------------------------------------------------------------+
|  +-------------------+  +-------------------+  +-------------------+  +----------+ |
|  | TOTAL REVENUE     |  | TOTAL EXPENDITURE |  | NET POSITION      |  | BUDGET   | | <-- C
|  |                   |  |                   |  |                   |  | UTIL %   | |
|  |  $742.3M          |  |  $735.8M          |  |  +$6.5M           |  | 94%      | |
|  |  FY23-24 actual   |  |  FY23-24 actual   |  |                   |  | ▮▮▮▮▮▮▯  | |
|  +-------------------+  +-------------------+  +-------------------+  +----------+ |
|                                                                                    |
+------------------------------------------------------------------------------------+
|                                                                                    |
|  Revenue vs Expenditure — Greenville 01                      [PDF] [Print] [PNG]  | <-- D
|                                                                                    |
|  800M |                                           ○----○----○                      |
|       |                              ●----●----● . ░░░░░░░░░                       | <-- E
|  600M |                ●-------●----●          . ░░░░░░░░░░░                       |
|       |  ●-------●----●                         ░░░░░░░░░░░░░                      |
|  400M |                                                                            |
|       +--+--------+--------+--------+--------+--------+--------+-----              |
|         FY21-22 FY22-23 FY23-24 FY24-25 | FY25-26 FY26-27 FY27-28                  |
|                                    historical→projected                            |
|                                                                                    |
|   ━ Revenue (historical)    - - Revenue (projected, 80% CI)                        |
|   ━ Expenditure (historical) - - Expenditure (projected, 80% CI)                   |
|                                                                                    |
+------------------------------------------------------------------------------------+
|  Footer: Data through FY24-25. Projections generated 2026-04-19. [Methodology]    | <-- F
+------------------------------------------------------------------------------------+
```

## Elements

| Label | Region | Description |
|---|---|---|
| A | Header | SCDE horizontal-stacked logo (light variant) on `brand.primary` bar; title; audience-toggle dropdown; help icon. |
| B | Filter bar | District multiselect (up to 8), "+ Add district" button, FY selector. |
| C | KPI strip | Four cards: Revenue, Expenditure, Net Position, Budget Utilization. Each card: caption (type.scale.sm) + value (type.scale.3xl). |
| D | Chart header | Chart title (type.scale.xl) + export controls (right-aligned). |
| E | Chart body | Historical/projected line chart with confidence bands. See mockup 02. |
| F | Footer | Data freshness, projection-run date, methodology link. |

## Interactions

- District multiselect: chip-based; "+ Add district" opens a searchable list. Selected chips are removable with the keyboard (Backspace from focus).
- KPI cards: clicking a card drills into the corresponding view (Revenue card → mockup 03 filtered to Revenue statement_type).
- Export buttons: see mockup 04.
- Audience toggle: see mockup 05.

## Token references

- Header bar background: `color.brand.primary` (`#2F3D4C`)
- Header text: `#FFFFFF`
- Page background: `color.semantic.neutral_bg` (`#F4F6F8`)
- Card background: `#FFFFFF` with `shadow.md` and 1px `color.semantic.border` on 3-sides
- KPI value color: `color.semantic.neutral_fg`
- KPI caption color: `color.brand.tertiary`
- Chart historical line: `color.data.projection.historical` (`#234058`)
- Chart projected line: `color.data.projection.projected` (`#43718B`)
- Confidence band: `color.data.projection.band_fill` @ 20% opacity
- Budget utilization bar fill: `color.semantic.success` (green when <100%), switches to `color.semantic.danger` when ≥100%
- Footer text: `color.brand.tertiary` at `type.scale.xs`
- Typography: all labels `type.scale.sm`; headings `type.scale.xl` / `type.scale.3xl`

## Accessibility

- Tab order: audience-toggle → help → district multiselect → FY selector → KPI cards (in read order) → export buttons → chart → footer links. Logical top-to-bottom, left-to-right.
- KPI cards are `<article>` elements with an accessible name ("Total Revenue, 742.3 million dollars, FY23-24 actual").
- Chart has a visually-hidden `<table>` alternative and a "Show data table" link immediately below the chart.
- Budget utilization bar is not color-only: percentage text is always displayed and read by the accessible name.
- Focus ring: 3px `brand.primary` outline offset 2px.
- All interactive controls reachable and operable with keyboard only.
