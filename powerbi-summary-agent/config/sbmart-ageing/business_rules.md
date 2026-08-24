# SB Mart Ageing insight rules

- Treat the report as one stock position as at the semantic model snapshot date.
- Use USD (`ageing_currency`) and the model's Stock Value exposure only.
- Aged means over 9 months; high risk means over 12 months; oldest means over 24
  months. Aged is summed from the `NEW AGE` bands, never read from
  `AGE_ABOVE_9` - that column returns `N` for the 24+ month band and so omits
  the oldest stock (see `summary_business_rules.md` for the measured gap).
- Never add aged and non-moving totals because they overlap.
- Do not claim YoY, trend, causality, write-off amount, or recommended provision
  from one snapshot.
- Prioritize absolute USD exposure before extreme percentages on immaterial
  members.

## Comparing against an earlier position

- An earlier position exists (`REP_SSR_SAG_HIST`, plus this pipeline's own kept
  scans), so movement findings are allowed - but only as **shares, counts and
  units**, and only while the valuation-basis check passes.
- **Never state a change in stock value between two dates unless the basis check
  cleared it.** The check is arithmetic, not a judgement: a location whose
  quantity is unchanged while its value per unit moves is proof the valuation
  changed, not the stock.
- Always name both dates and the number of days between them. Never describe the
  window as "since yesterday" unless it is one day.
- The two lanes - the source model's frozen reference position and this
  pipeline's last kept scan - are reported separately and never combined.
