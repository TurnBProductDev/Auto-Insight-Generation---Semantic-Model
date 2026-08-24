# SB Mart Target Tracker summary rules

## Purpose and order

Explain actual performance against target in this order: Day, week to date, month to
date, then year to date. The nearer period leads; the year is context.

## Scope and anchor

- Population: ST1, ST2, ST3 and ST4.
- Excluded: ST5, because it has no current target or current-period sales.
- The anchor is the latest date carrying a target inside the included population.
- At onboarding, all four included stores carried sales and targets through 31 July
  2026. Resolve the anchor again every run.
- Weeks run Monday to Sunday.

## Arithmetic

- Percent of target = actual divided by elapsed target, multiplied by 100.
- Above/below target = actual minus elapsed target.
- Needed to close = full-period target minus actual so far.
- Needed vs target = needed to close divided by the remaining-days target.
- Calculate targets by summing `ACTUAL_SALES_TARGET` over the required date range.
- Do not use the model's `MTD_TARGET` or `WTD_TARGET` measures for scoped totals.
- Every displayed figure must trace to the deterministic page model and pass its
  reconciliation checks.

## Currency and language

- All money is shown in USD (the model's own figures are labelled QAR, but this
  report publishes in USD by configuration - never restate the model's own label).
- Always pair a percentage with its actual and target values or its value gap.
- Prefer plain phrases such as `this week`, `this month` and `% of target`.
- Do not use forecasting language. A projection is only arithmetic carrying a stated
  rate forward.
- Do not compare with last year in this product, even when the semantic model contains
  prior-year columns. The separate YoY report owns prior-year performance.
- Do not invent promotions, stock, staffing, weather, footfall or competitor causes.

## Ranking and missing data

- Rank target gaps by value first, then share of the total gap, distance from target,
  persistence and recency. Never rank on percentage alone.
- If no target exists, show actual sales and state that no target is set. Never turn a
  missing target into zero.
- Use the same bands everywhere: at least 100% is On target, 95–99.9% is Watch, and
  below 95% is Below target.

## Required outputs

- `report_target_tracker.html`: self-contained interactive report.
- `report_target_tracker.md`: matching business document.
- `report_target_tracker.json`: reconciled page model.
- Target Tracker findings publish as report-aware cards in the shared SB Mart insight
  and alert feeds.

