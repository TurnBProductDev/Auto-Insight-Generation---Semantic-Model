# Global Business Standards

Cross-report doctrine. Everything here applies to **every** report profile in this
repository unless that profile records an explicit, reasoned deviation.

Confidence tiers per the [README](README.md#conventions): **[VERIFIED]**,
**[INFERRED]**, **[UNVERIFIED]**.

---

## 1. Comparability doctrine

The single most important rule in retail reporting, and the one most often broken
silently.

### 1.1 The like-for-like principle

A growth figure is only meaningful when the same trading units contributed to both
periods. Mixing a new store into a year-on-year comparison does not measure growth; it
measures expansion, and labelling it growth overstates commercial performance.

**Standard:** every comparable (like-for-like, LFL, YoY) figure — totals, percentages,
contribution shares, rankings, concentration measures, and every denominator used to
describe comparable performance — is computed over the **comparable population only**:
entities with genuine trading data in *both* the current and the prior period.

### 1.2 Three populations, never merged

| Population | Definition | Valid uses | Invalid uses |
|---|---|---|---|
| **Comparable** | Traded in both current and prior period | LFL growth, YoY %, contribution to change, rankings, concentration | — |
| **Current-only** | New, opened or acquired within the current period | Total current actuals, absolute contribution, expansion narrative | Any YoY %, any comparable denominator, any growth ranking |
| **Prior-only** | Closed or divested during the period | Prior-period actuals, attrition narrative | Any current-period figure, any comparable denominator |

Current-only contribution is **reported separately and labelled as such** — as
new-entity or expansion contribution, never as comparable growth. It is not deleted
from overall current-period actuals; total revenue is still total revenue.

### 1.3 When the comparable denominator is unavailable

Report the **absolute movement** and **omit the percentage**. A percentage over a wrong
denominator is worse than no percentage, because it looks authoritative.

### 1.4 Enforcement

This doctrine is enforced in three places, and all three must agree:

1. **Deterministic** — `baseline_scope` classifies every entity from actual data as
   comparable / current-only / prior-only / inactive; `scope_validator` rejects any
   query using prior or change metrics that does not prove the comparable population.
2. **Configuration** — `insight_comparable_population` and `insight_excluded_entities`
   in the active `config.json`.
3. **Prose** — the compiled `business_rules.md`, injected into every LLM prompt.

Configured populations are treated as business-rule overrides and are **audited against
the data-derived classification**. A disagreement is a finding, not a silent override:
if the data says an entity traded in both periods but the configuration excludes it,
someone needs to explain why.

---

## 2. Metric dictionary

The shared retail metric definitions. A report profile may bind these to different
measure names, but **not** to different meanings.

### 2.1 The core identity

Retail performance decomposes along two complementary chains that must both reconcile:

```
Revenue  =  Footfall  x  ATV          (transaction chain)
Revenue  =  Volume    x  ASP          (unit chain)
Volume   =  Footfall  x  UPT          (basket chain)
```

These are identities, not approximations. If a report's measures do not reconcile
across all three within tolerance, that is a data-quality finding and must be raised
before any commercial interpretation is offered.

### 2.2 Definitions

| Metric | Definition | Direction | Business meaning |
|---|---|---|---|
| **Revenue** | Net sale value, after returns and discounts | Higher is better | The headline outcome |
| **Volume** | Units sold | Higher is better | Real demand, inflation-free |
| **Footfall** | Transaction (bill) count | Higher is better | Traffic — customers converted |
| **ASP** (Average Selling Price) | Revenue / Volume | Context-dependent | Price and mix per unit |
| **ATV** (Average Transaction Value) | Revenue / Footfall | Higher is better | Value extracted per visit |
| **UPT** (Units Per Transaction) | Volume / Footfall | Higher is better | Basket size — attach and cross-sell |

**Footfall caveat [VERIFIED]:** in this repository footfall means **transaction count**,
not door-counter traffic. It therefore excludes non-buying visitors and cannot be used
to discuss conversion rate. Any report claiming a conversion metric needs a genuine
door-count source recorded in its profile.

**ASP direction:** rising ASP is not automatically good. It is favourable when driven by
premium mix, and unfavourable when driven by price increases that suppress units. The
two are indistinguishable without category-level decomposition, so ASP movement is
always reported **with** UPT movement, never alone.

### 2.3 Breadth and concentration

| Metric | Definition | Direction | Business meaning |
|---|---|---|---|
| **Category Decline Breadth** | Declining categories / total categories | Lower is better | Is growth broad or narrow? |
| **At-Risk Revenue Concentration** | Declining categories' revenue share, current minus prior | Lower is better | Is exposure to weak categories rising? |

Breadth is the check on a healthy headline. Strong total growth with high decline
breadth means growth is concentrated in a few categories and is more fragile than the
headline suggests. Always read the two together.

### 2.4 Value / volume decomposition

When explaining a revenue change, the agent carries an exact decomposition:

```
volume effect  =  (Q1 - Q0) * (R0 / Q0)
rate   effect  =  Q1 * ((R1 / Q1) - (R0 / Q0))
```

**The rate effect is not price.** It contains price *and* mix, and the two cannot be
separated without a category-level breakdown. Reporting the rate effect as a price
change is a factual error. In manager-facing prose, describe it as the change in
average value per unit, and say plainly that it may reflect what was sold as much as
what it was sold for.

---

## 3. Calendar and period conventions

- **Fiscal year** — **[UNVERIFIED]** across the business. Each profile must state its
  own fiscal calendar and year-start month. Do not assume January.
- **Comparison basis** — the default is prior year, same period (YoY). A profile using
  prior period, budget, or forecast as its basis must say so explicitly.
- **Trading geography** — Saudi Arabia **[BUSINESS-STATED, 2026-07-28]**. Currency SAR,
  timezone `Asia/Riyadh` (UTC+3, no daylight saving), weekend **Friday–Saturday**,
  working week Sunday–Thursday.
- **Moving religious calendar** — Ramadan and the two Eids follow the Hijri calendar and
  fall roughly 11 days earlier each Gregorian year. Trade therefore shifts between
  calendar months year on year. **Any month-on-month or year-on-year monthly comparison
  must check the Hijri calendar before attributing a movement to performance.** This is
  the single most common cause of a month looking anomalous in this estate.
- **Reporting timezone** — `Asia/Riyadh`, set in `insight_history_timezone` and
  `summary_history_timezone`. Corrected from `Asia/Kolkata` on 2026-07-28; runs before
  that date stamped history in IST and are offset by 2.5 hours.
- **Trading date vs load date** — the distinction is critical and is a recurring trap in
  this estate. A date column populated by the ETL (a load, posting, or update stamp) is
  **not** a trading date and must never be used for daily, weekly, or seasonal analysis.
  The tell is concentration: if a single bucket holds an outsized share of the value
  metric, it is a batch stamp. The agent tests for this automatically and disables the
  affected analysis levels rather than producing plausible nonsense.
  Every profile must name its trading date column, or state that it has none.

---

## 4. Reporting standards

### 4.1 Materiality

A finding is only worth a manager's attention if it is material. Default gate: at least
**1.0%** of the relevant total **[VERIFIED]** (`insight_materiality_pct`). A large
statistical deviation on a commercially trivial base is not a finding.

Both size and share matter. Findings are ranked by materiality — absolute impact
weighted by share of total change — and no analysis level receives priority ordering
purely for being more granular.

### 4.2 Language

- **Contribution, not causation.** The data shows association. Say "likely contributor"
  or "associated with", never "caused by". Insight agents may investigate contributing
  factors; they may not assert proven root cause.
- **No forecasting, no alerting.** Anywhere. The agent describes what happened and what
  is worth checking. It does not predict, and it does not raise thresholds as alarms.
- **Recommendations propose checks, never actions.** A recommended action must open with
  a safe verb — Assess, Compare, Confirm, Investigate, Monitor, Prioritise, Review,
  Segment, Validate. The agent may recommend *examining* pricing; it may never
  prescribe a price, a staffing level, or an operational change. Commercial decisions
  belong to the business.
- **Manager-facing prose is plain.** No analyst shorthand in the key-insights section:
  no "volume effect", "rate effect", "share of total change", "materiality",
  "reconciliation", "z-score", "probe", "signal". State what changed, by how much, and
  what to check. Technical appendices remain fully technical and auditable.
- **No emojis or decorative symbols.**

### 4.3 Honesty about gaps

Missing data is stated, never smoothed over. If a query failed, the report says so and
continues with what is available. If evidence is partial, the finding stays flagged as
verification-required rather than being presented as closed. A report that quietly omits
what it could not compute is not auditable.

---

## 5. Semantic model standards

Constraints that apply to any Power BI model this agent reads.

### 5.1 Bind to measures, not raw columns

Column names in this estate have already drifted between Desktop files and published
datasets **[VERIFIED]**. Measure names have proven far more stable. Every KPI, rule, and
threshold binds to the **measure name**. Where a measure encodes correct internal logic,
call it rather than reconstructing the calculation from raw columns — reconstruction
requires guessing which column generation applies.

### 5.2 DAX constraints

- **Never** filter with `KEEPFILTERS('Table'[Col] = "value")` — it reliably fails
  against these models with a "single value for column cannot be determined" error
  **[VERIFIED]**. Use `FILTER(SUMMARIZECOLUMNS(...), ...)` or `TREATAS`.
- Multi-member filters use a genuine multi-value `TREATAS`, never a comma-joined
  pseudo-member.
- A grand-total `EVALUATE ROW(...)` packing several measures **fails as a whole** if any
  single measure throws. Prefer isolated queries where partial results have value.
- `executeQueries` can return **HTTP 200 with a per-query error embedded in the body**.
  A successful HTTP status is not a successful query.

### 5.3 Measure expressions

Measure expressions are redacted over `executeQueries` but recoverable through the
Fabric semantic-model definition API. Enrichment is best-effort: when it fails,
expressions stay blank and analysis proceeds without them. A profile should note how
many of its measures resolved.

---

## 6. Governance

### 6.1 Ownership

Every report profile names a **business owner** (accountable for whether the rules are
commercially correct) and a **technical owner** (accountable for whether they are
faithfully implemented). A profile without both is provisional.

### 6.2 Change control

1. Amend the profile or this file, with a dated change-log entry and a stated reason.
2. Re-compile the affected `business_rules.md`.
3. Mirror any entity-scope change into that report's `config.json` **in the same
   commit**.
4. Run once and read `outputs/business_rules_snapshot.md` to confirm what actually
   loaded.

### 6.3 Audit

Every run snapshots the rules in force to `outputs/business_rules_snapshot.md`. Any
report can therefore be reconciled against the exact rulebook that produced it. Preserve
these snapshots for any output that reaches a board pack or an external party.

### 6.4 What counts as verification

A claim is **[VERIFIED]** only when it comes from a live query against the model in
question, or from a committed artifact produced by one. Nothing else qualifies.

In particular, **engineering documentation is not a source of business fact.**
`CLAUDE.md` and `AGENTS.md` describe how the codebase behaves and cite examples from
whichever dataset was in front of the author at the time. Those examples go stale, and
they may describe a different model entirely. Treat every business claim in them as
**[UNVERIFIED]** until a live query confirms it.

This is not hypothetical: R01's first profile inherited five material errors from
`CLAUDE.md`, including a two-and-a-half-year staleness claim about a dataset that
refreshes daily, and a data-quality hazard on a column that does not exist in the model.
See [R01 §11](reports/R01-retail-brand-mis.md#11-corrections-from-version-10).

When a profile is verified, record the date. When a live check contradicts an earlier
claim, correct it in place and log what changed — a silently corrected error teaches
nobody which sources to distrust.

### 6.5 Precedence

When sources conflict, this order settles it:

1. Safety, scope, and the permanent guardrails in `prompts/_global_rules.md`
2. The semantic model schema — only real tables, columns, and measures exist
3. **Business rules** (this repository, as compiled)
4. Generic analytical defaults

Business rules beat generic defaults. They never beat a guardrail, and they can never
conjure a column that does not exist. A rule that conflicts with a higher tier is
ignored in the conflicting part only.
