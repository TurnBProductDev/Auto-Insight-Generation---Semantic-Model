# Daily Sales - business rules

This report compares one day's Bills and Margin against a **normal band**:
the P20 (floor) to P80 (ceiling) range built from past days matching the
SAME weekday and the SAME week-of-month (e.g. "past Wednesdays in week 2
of the month"). It is never a comparison with last year, and never a
comparison with yesterday specifically - only with the matching-weekday
history the model has built.

## Verdicts

- **Below the P20 floor -> Underperforming.**
- **Above the P80 ceiling -> Outperforming.**
- **Between the floor and ceiling -> In band** - this is normal for that
  weekday, not a move worth reporting.

## What is trustworthy, and what is not

- **Bills and Margin** - actual, P20/P50/P80, verdict - are trustworthy at
  every level: the whole business, each store, each department, section
  and category.
- **Net Sales and Basket Value** are trustworthy ONLY as a plain actual
  figure for the whole business and for each store. They are never shown,
  and never banded, at department/section/category level, because the
  source figures at that grain do not currently total correctly (a
  verified ~3.7x inflation). Never invent or estimate a Net Sales figure
  at those levels.

## Non-additivity

- **Bills cannot be added up** across departments, sections or categories.
  One basket touching bread, shampoo and a shirt is one Bill for the store
  but counts once under each department, section and category it touched.
  A sum or a "share of baskets" at these levels is a guide, not an exact
  total.
- **A band at one level does not add up to the band at the level above
  it.** Each level's band is computed independently.

## Duplicate names

- Several department/section/category names cover more than one distinct
  underlying group in the source data (the source carries no code to tell
  them apart). Bills is safely summed across a shared name; Margin is
  reported as a Bills-weighted average across the merged groups, and is
  stated as such - never presented as an unweighted or a sales-weighted
  figure, since no reliable sales figure exists at that level.

## Language

- Never assert a cause for a movement - concentration only ("the shortfall
  concentrates in X"), never "because of X".
- Never compare to last year or to a forecast - this report has neither.
- Never use "traffic", "footfall" or "shoppers" for Bills - it is a count
  of completed transactions.
- No emojis.
