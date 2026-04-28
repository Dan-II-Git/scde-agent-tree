# Mockup 04 — Export Controls (PDF / Print / PNG)

Export affordances on every chart and on the page-level export bar.

## Layout — Page-level export bar (top of any chart)

```
+------------------------------------------------------------------------------------+
|  Revenue vs Expenditure — Greenville 01          [📄 PDF] [🖨 Print] [🖼 PNG]      |
+------------------------------------------------------------------------------------+
```

## Layout — PDF export confirmation dialog

```
+----------------------------------------------------------+
|  Export to PDF                                       [×] |
+----------------------------------------------------------+
|                                                          |
|   What to include:                                       |
|     [✓] Cover page (SCDE logo + title + run date)        |
|     [✓] KPI summary                                      |
|     [✓] Revenue vs Expenditure chart                     |
|     [ ] Line-item drilldown tables (24 pages est.)       |
|     [✓] Methodology note + caveats                       |
|                                                          |
|   Audience view:   (●) Public    ( ) Analyst             |
|                                                          |
|   Paper size:  [Letter ▾]       Orientation: [Portrait ▾]|
|                                                          |
|                              [Cancel]   [ Export PDF ]   |
+----------------------------------------------------------+
```

## Layout — Print preview (activated by [🖨 Print])

Print CSS transforms the current page into a printable document:

```
+------------------------------+
|  [SEAL-logo]   SCDE          |  <- print-header with Seal variant
|  Finance Dashboard           |
|  Greenville 01 — FY25-26     |
+------------------------------+
|                              |
|  KPI strip (4 cards)         |
|                              |
+------------------------------+
|                              |
|  Revenue vs Expenditure      |
|  (chart rendered at 180 DPI) |
|                              |
+------------------------------+
|                              |
|  Methodology caveats:        |
|  - wRMSE is primary gauge    |
|  - Partial-FY adjustments... |
|  - ...                       |
+------------------------------+
|  Generated 2026-04-19  | 1/N |  <- print-footer
+------------------------------+
```

## Layout — PNG snapshot confirmation

```
+----------------------------------------------------------+
|  Download chart as PNG                              [×]  |
+----------------------------------------------------------+
|                                                          |
|   Filename:  [Greenville-01_RevExp_FY25-26.png]         |
|   Resolution:  ( ) 1x   (●) 2x (retina)   ( ) 3x (print) |
|   Include legend:  (●) Yes   ( ) No                     |
|   Include partial-FY badge (if applicable):  (●) Yes    |
|                                                          |
|                                   [Cancel]   [Download]  |
+----------------------------------------------------------+
```

## Elements

| Label | Description |
|---|---|
| PDF button | Triggers the PDF dialog above. |
| Print button | Triggers the native browser print dialog with print CSS applied. |
| PNG button | Triggers the PNG snapshot dialog. |
| Cover page | Per SCDE PDF p.5, uses Seal + Horizontal-Stacked, white bg. |
| Dialog dismiss | × icon top-right + Esc key + clicking backdrop. |

## Interactions

- All three exports are opt-in — a dialog confirms the action before any download starts.
- PDF includes a cover page mirroring the Seal variant on a white background. Body pages use Horizontal-Stacked logo in the header.
- Print CSS sets `@page { size: letter portrait; margin: 0.5in; }` by default, hides the filter bar and audience toggle, and forces charts to render with `print-color-adjust: exact` so the projection dashes survive printing.
- PNG is captured from the live SVG chart — NOT a screenshot. It includes embedded metadata: "SCDE Finance Dashboard · <district> · <statement_type> · generated <ISO date>".
- Analyst-view exports include a footer note "Analyst view: includes method and MAPE columns" so an exported PDF can't be confused for the public summary.

## Token references

- Export-button background: `color.brand.secondary` (#234058)
- Export-button text: `#FFFFFF` (10.79:1 AA)
- Export-button hover: `color.brand.primary` (#2F3D4C)
- Dialog backdrop: `rgba(47,61,76,0.55)` (reads as translucent-primary)
- Dialog surface: `#FFFFFF`, `shadow.lg`, `radius.lg`
- Dialog heading: `type.scale.xl`, `color.brand.primary`
- Cancel button: ghost style, `color.brand.secondary` text on white, 1px `color.semantic.border`
- Primary button (Export / Download): filled `color.brand.secondary` bg, white text
- Checkbox/radio focus ring: 3px `color.brand.primary` outline offset 2px

## Accessibility

- Dialog implements ARIA modal pattern: `role="dialog" aria-modal="true" aria-labelledby="<title-id>"`.
- Focus is trapped inside the dialog and returns to the triggering button on close.
- Esc key dismisses. Tab cycles through only the dialog's controls.
- All form controls have `<label>` elements.
- Download file name is announced ("Download chart as PNG, filename Greenville-01_RevExp_FY25-26.png") when the dialog opens, via `aria-describedby`.
- Print CSS preserves contrast and does not use color-only cues (the projection dash-pattern survives black-and-white printing).
- Explicit user confirmation before any file leaves the browser, per the explicit-permission requirement in the host environment's safety rules — translated here into an in-app pattern so the dashboard user is always opting in to export actions.
