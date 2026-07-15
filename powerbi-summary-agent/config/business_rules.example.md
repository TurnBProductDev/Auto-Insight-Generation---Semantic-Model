# Company Business Rules

Company-specific calculation and reporting logic that the agent must follow when
planning DAX, generating/repairing queries, scanning for insights, investigating,
and writing the final reports.

These rules are **authoritative**: they override the agent's generic defaults and
assumptions. Keep them in plain business English. A snapshot of this file is written
to the outputs folder on every run (`business_rules_snapshot.md`) so each report is
auditable against the exact rules that were in force.

This file is intentionally separate from `prompts/_global_rules.md`:

- `_global_rules.md` = permanent system / reporting guardrails (scope, tone, safety).
- `business_rules.md` = your evolving company and calculation logic (this file).

> Copy this file to `config/business_rules.md` and replace the example entity
> codes below with your own. This file is optional — if `business_rules.md` is
> absent, the agent runs with no company overrides. Any comparable-population
> codes you list here must also be mirrored in `insight_comparable_population`
> / `insight_excluded_entities` in `config.json`.

Add, edit, or remove rules below as the business logic evolves.

---

## Comparable-entity YoY

For YoY analysis, include only entities with actual data in both the current
and prior-year periods.

Calculate all comparable YoY totals, percentages, contribution shares, and
rankings using only this same comparable population. Never use an overall total
that includes new entities as the denominator for a comparable finding.

Report new entities and their current-period contribution separately. If a
valid comparable denominator is unavailable, report the absolute movement and
omit the percentage.

### Authoritative branch scope (EXAMPLE — replace with your own codes)

`STORE_NEW` is a new/current-only branch and has no valid prior-year comparison.
Never include `STORE_NEW` in like-for-like or comparable YoY calculations.

Exclude `STORE_NEW` from all comparable current and prior totals, YoY changes and
growth percentages, rankings, concentration calculations, contribution shares,
and denominators used to describe comparable performance. Apply this exclusion
consistently to summary queries, insight scans, investigation probes, repaired
queries, and final report statements.

For the current model, the comparable branch population is `STORE_A`, `STORE_B`,
`STORE_C`, and `STORE_D`. Use this same population on the applicable `store_no`
column in every fact table involved in a comparable calculation.

Do not remove `STORE_NEW` from overall current-period actuals. Report its current
revenue and other current-period contributions separately and label them as
new-store/current-only contribution, never as comparable YoY growth.
