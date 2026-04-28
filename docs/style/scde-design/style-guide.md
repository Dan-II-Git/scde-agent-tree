# SCDE Finance Dashboard — Style Guide

Authoritative brand source: `SCDE Brand Guidelines (1).pdf` (pages 3–8). Every token below is either (a) copied directly from that PDF or (b) synthesized to meet WCAG 2.1 AA while staying visually consistent with the SCDE palette. Deviations are explicitly marked.

## 1. Palette

### 1.1 Brand (sourced from SCDE PDF p.7)

| Swatch | Name | Hex | Pantone | Contrast vs white | Contrast vs brand.primary |
|---|---|---|---|---|---|
| ▮ | brand.primary | `#2F3D4C` | 432 C | 11.10:1 | 1.00:1 |
| ▮ | brand.secondary | `#234058` | 7546 C | 10.79:1 | 1.03:1 |
| ▮ | brand.tertiary | `#43718B` | 5405 C | 5.28:1 | 2.10:1 |
| ▮ | brand.accent (gold) | `#F1BA55` | 142 C | 1.77:1 — decorative only | 6.28:1 |

**Accent-gold usage rule:** gold fails AA against white for text (1.77:1). It is valid only as (a) a fill/stroke element on a dark background, (b) a chart line with a dark keyline outline, or (c) a badge background paired with `brand.primary` text (6.28:1, AA pass).

### 1.2 Semantic (synthesized — marked non-PDF)

| Swatch | Token | Hex | Contrast vs white | Use |
|---|---|---|---|---|
| ▮ | semantic.success | `#1F7A3A` | 5.38:1 | Budget-utilization healthy, under-budget deltas |
| ▮ | semantic.warning | `#8A5A00` | 5.93:1 | Partial-FY data, low-confidence projections |
| ▮ | semantic.danger | `#B3261E` | 6.54:1 | Over-budget, destructive actions |
| ▮ | semantic.info | `#234058` | 10.79:1 | Informational callouts (aliased to brand.secondary) |
| ▮ | semantic.neutral_bg | `#F4F6F8` | n/a | Page background |
| ▮ | semantic.neutral_fg | `#2F3D4C` | 11.10:1 | Body text |
| ▮ | semantic.border | `#7E8C9E` | 3.42:1 | Perceivable borders (form fields, table grid) |

### 1.3 Data categorical (colorblind-safe, up to 8 districts)

Based on the Okabe-Ito palette, with index 0 swapped to SCDE dark blue and index 7 swapped from Okabe yellow to neutral dark gray (yellow fails 3:1 on white). See `contrast-audit.md` for per-color ratios and mitigation policy when a color falls below 3:1.

### 1.4 Projection-specific tokens

- `projection.historical` — `#234058` solid line, filled markers.
- `projection.projected` — `#43718B` dashed line (6-4 dash), hollow markers.
- `projection.band_fill` — `#43718B` @ 20% opacity between upper/lower 80% CI.
- `projection.partial_fy_badge` — `#F1BA55` background, `#2F3D4C` foreground.
- `projection.partial_fy_band` — `#F1BA55` @ 22% opacity, wider than normal band.
- `projection.insufficient_gap` — `#7E8C9E` @ 35% opacity, diagonal hatch + "No projection — 4 FYs of history required" label.

## 2. Typography

Font family: **Poppins** (SCDE PDF p.8) with system-ui fallbacks so missing-font scenarios still resemble the brand.

| Token | Size | Line-height | Usage |
|---|---|---|---|
| type.scale.xs | 12px | 16px | Axis ticks, footnotes, caption rows |
| type.scale.sm | 14px | 20px | Table body, secondary labels |
| type.scale.base | 16px | 24px | Body paragraphs, default UI |
| type.scale.lg | 18px | 28px | Card titles, KPI captions |
| type.scale.xl | 22px | 30px | Section titles (h3) |
| type.scale.2xl | 28px | 36px | Page section headings (h2) |
| type.scale.3xl | 34px | 42px | Page title (h1), KPI dollar values |

**Weights:** 400 (body), 500 (emphasized body), 600 (sub-headers), 700 (page titles). Poppins supports all four. The SCDE PDF shows Poppins in Regular + Bold — we use the intermediate 500/600 weights only where needed for hierarchy, staying within the Poppins family.

**Monospace** (`JetBrains Mono` → `Consolas` → `Menlo`, fallback-safe) — used ONLY for tabular currency columns and COA code cells so digits align on decimal. Not in the SCDE PDF; synthesized for data-display legibility.

## 3. Logo usage (per SCDE PDF pages 4–6)

- Two primary versions: **Seal** and **Horizontal Stacked**. One secondary: **Text Only**.
- **Horizontal Stacked is preferred when space allows.** (PDF p.5.)
- The dashboard header uses Horizontal Stacked at 40px height, with 24px of clear space on all sides.
- The Seal variant is reserved for the PDF export cover page and the print header (top-right, 36px square).
- Logo must sit on a **solid background** (PDF p.7 rule 1). The dashboard header uses `brand.primary` dark bg so the light logo variant is used; cards on `neutral_bg` use the dark logo variant.
- Do **not** manipulate, rotate, apply effects, or place the logo on a conflicting background (PDF p.7 rules 2–5).
- Design questions per PDF p.7: Nicole Arndt, Visual/Digital Media Director, nmarndt@ed.sc.gov.

## 4. Accessibility (WCAG 2.1 AA checkpoints)

The dashboard commits to the following:

- **1.4.3 Contrast (Minimum):** All foreground-on-background text pairs pass 4.5:1 (or 3:1 for large text). See `contrast-audit.md`.
- **1.4.11 Non-text Contrast:** Form-field borders, focus indicators, and essential chart elements pass 3:1. Categorical chart colors below 3:1 use mandatory keyline + marker-shape + direct-label mitigations.
- **2.1.1 Keyboard:** All interactive controls (district selector, audience toggle, export buttons, table sort) reachable via Tab; activation via Enter/Space. Custom `<select>` replacements use ARIA-combobox pattern.
- **2.4.7 Focus Visible:** 3px `brand.primary` outline offset 2px on focused controls; never `outline: none` without an equivalent replacement.
- **1.4.1 Use of Color:** Color is never the sole cue. Projection uses dash-pattern + hollow markers; partial-FY adds a badge; insufficient-data adds a hatch pattern + text message.
- **2.3.3 Animation from Interactions:** `prefers-reduced-motion` disables chart enter-animations and reduces transitions to instant state-swap. No parallax, no auto-play.
- **1.4.10 Reflow:** Layout reflows cleanly at 320 CSS px (mobile) with no horizontal scroll on non-table content. Tables scroll horizontally on narrow viewports with sticky row headers.
- **1.3.1 Info and Relationships:** Tables use `<th scope>` and captions; charts have an associated `<figcaption>` and a visually-hidden data-table alternative toggled by a "Show data table" link for screen readers.

## 5. Data visualization rules

### 5.1 Historical vs projected line treatment

- **Historical segment:** `projection.historical` (`#234058`), solid stroke 2.5px, filled circle markers 4px radius.
- **Projected segment:** `projection.projected` (`#43718B`), dashed stroke 2px (dash-array `6 4`), hollow circle markers 4px radius with 1.5px stroke.
- Transition point between historical and projected is marked with a vertical light-gray gridline and the label "FY24-25 | FY25-26 →".

### 5.2 Confidence band

- Filled area between upper and lower 80% bounds at **20% opacity** of the projection line color.
- Bounds themselves are NOT stroked — the shaded fill communicates the range; the projected line sits on top.
- When hovering, tooltip shows `point value (lower – upper)` and the method used (`Linear`, `Log-linear`, `Growth-rate`, `Flat`).

### 5.3 Partial-FY series

- Apply `projection.partial_fy_band` (gold at 22% opacity) instead of the normal blue band.
- Add a gold badge "FY24-25 data incomplete — projection uses FY21-22 … FY23-24" at the top-right of the chart title.
- Tooltip on affected series also includes the badge as a second line, so the caveat is visible even when the chart title is off-screen during table-view drilldowns.
- Affects Charleston 01 (rev+exp), Richland 01 (rev+exp), SC Public Charter (rev) per Phase 3 verification.

### 5.4 Insufficient-data series

- Render the projection horizon as a diagonal-hatch shaded band (`projection.insufficient_gap`).
- Overlay centered text "No projection — insufficient historical data (need 4 FYs; have N)" using `type.scale.sm` + `neutral_fg`.
- Do NOT default to zero or blank space — zero implies a real projection of $0 which is false.

### 5.5 Analyst vs public-view differences

- **Public view (default):** shows chart, confidence band, partial-FY badge where applicable, and dollar-weighted RMSE summary. Method and MAPE are hidden.
- **Analyst view (toggle):** adds a "Method" column in the drilldown table (Linear / Log-linear / Growth-rate / Flat), a MAPE tooltip with the caveat "MAPE inflated by small-dollar denominator lines; wRMSE is the primary quality gauge," and per-series backtest-coverage footnote.

### 5.6 Chart axes and grids

- Y-axis: currency-formatted with SI suffixes (K, M, B). Right-aligned.
- X-axis: fiscal-year label "FY22-23". Tilted 0° when ≤6 ticks, 45° when more.
- Gridlines: horizontal only, `border_subtle` at 50% opacity. No vertical gridlines (they compete with the historical→projected marker).

### 5.7 Number formatting

- Always right-aligned in tables.
- Negative values in parentheses with `semantic.danger` color (e.g., `($1,245)` in red).
- Full-precision on hover/tooltip; SI-compacted in chart tick labels.

## 6. Motion

- Chart enter: 250ms ease-out, disabled by `prefers-reduced-motion: reduce`.
- Tooltip fade: 120ms.
- Filter-selection updates: instant (no animation) to avoid implying a transition between FY values.

## 7. Cross-reference to tokens file

Every rule above references a token key that exists in `design/tokens.json`. If a component reaches for a color that is not in `tokens.json`, it is out of spec and Phase 5 should escalate.
