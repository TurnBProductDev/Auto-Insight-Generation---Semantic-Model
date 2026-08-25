# SB Mart sales reporting rules

These rules govern the SB Mart Sales vs Previous Year report. They override generic
agent assumptions. The model was probed live on 20 August 2026 before onboarding.

## Scope

- Compare only stores with valid current and prior-period activity. Let the agent
  rediscover this population each run so openings and closures are handled from data.
- The onboarding probe found ST1, ST2, ST3, ST4 and ST5 comparable. No store was
  current-only or prior-only at the time of the probe.
- Never include a current-only store in a year-on-year percentage. Show its current
  contribution separately if one appears later.

## Measures

- Use the semantic model's named measures rather than rebuilding them from raw columns.
- Revenue: `net revenue CURRENT`, `net revenue PAST`, `revenue Growth`.
- Quantity: `net qty CURRENT`, `net qty PAST`, `QTY Growth`.
- Transaction comparisons must use the model's transaction measures and must pass the
  normal reconciliation checks before being reported.
- Report all monetary figures in the units supplied by the model. Do not invent a tax,
  margin or currency conversion.

## Time

- This is a monthly year-on-year report. Lead with the latest complete month and keep
  the broader period as context.
- `MIS_DEEP_DIVE2[max_date]` and
  `MIS_BASE_FILE_MONTHLY_BRAND_TB[max_date]` behave as batch/load dates. Never use them
  for daily, weekly or day-of-week trading analysis.
- The business month axis is `MIS_DEEP_DIVE2[Month]`. Display month numbers as names.
- At onboarding, data was loaded through 18 August 2026 and July 2026 was the latest
  complete reporting month. Re-evaluate this every run.

## Hierarchy

- Store is `MIS_DEEP_DIVE2[store_no]`.
- Division and Section are the distinct merchandise levels suitable for complete
  coverage.
- Department currently mirrors Division, and Category currently mirrors Section.
  Collapse these mirrored levels rather than repeating the same findings.

## Writing

- State the period and store scope for every comparison.
- Put a number on every movement and distinguish current value, prior value and change.
- Do not claim a cause that sales data cannot prove. Say where and when a change sits;
  do not invent promotions, stock, staffing, weather or competitor explanations.
- Keep the Summary descriptive and the Insight report investigative, with every figure
  traceable to executed evidence.
