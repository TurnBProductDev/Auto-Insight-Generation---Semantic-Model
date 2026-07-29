# Suggested additions to `config/business_rules.md`

**This file is NOT read by the pipeline.** It's a reference doc only — nothing
here affects any run until you deliberately copy a section into
`config/business_rules.md` yourself. Nothing in the code or config was
changed to produce this; it's the write-up of what I found inspecting the
live model via `pbi-cli` (16 tables, 142 columns, 56 measures, cross-checked
against the last run's `outputs/model_metadata.json` and `insight_report.md`).

Each section below is written the way it would need to look if pasted into
`business_rules.md` (plain business English, imperative, no code changes
implied) — you can lift any of them as-is.

---

## 1. Authoritative source table for revenue and quantity

`MIS_DEEP_DIVE2` is the single source of truth for revenue, quantity, and
category/division breakdowns. Always plan and generate DAX against
`MIS_DEEP_DIVE2` (`net_sale_val_current`, `net_sale_val_ly`,
`net_sales_qty_current`, `net_sales_qty_ly`) and its measures (`net revenue
CURRENT`, `net revenue PAST`, `revenue Growth`, `net qty CURRENT`, `net qty
PAST`, `QTY Growth`).

`MIS_BASE_FILE_MONTHLY_BRAND_TB` and `CAT_TABLE` hold their own duplicate
current/prior revenue columns (`REV_CURRENT`/`REV_PREV` on the brand table,
`CURRENTREV`/`PREVIOUS` on `CAT_TABLE`). These are separate, brand/category-level
cuts of the same underlying sales, not additional evidence. Never mix them with
`MIS_DEEP_DIVE2` totals in the same calculation, never sum across them, and
never treat agreement or disagreement between them as a finding — it is a
grain difference, not a business signal. Only fall back to them if
`MIS_DEEP_DIVE2` cannot answer a question at all.

Transactions/bills come from `CAT_TRANSACTIONS` (`dist_bill_curr`,
`dist_bill_ly`, and the measures `net bills CURRENT`, `bills growth`).
`CAT_TRANSACTIONS`, `CAT_TABLE`, and `MIS_DEEP_DIVE2` share the same grain
(store x month x product breakdown) and join 1:1 on `KEY`, so bills can be
safely combined with revenue/quantity from `MIS_DEEP_DIVE2` for spend-per-bill
and quantity-per-bill analysis.

**Why this matters:** the DAX-generating LLM node sees all of these as
equally valid, existing measures — nothing in the validator stops it from
picking `MIS_BASE_FILE_MONTHLY_BRAND_TB[REV_CURRENT]` over `MIS_DEEP_DIVE2`'s
`net revenue CURRENT` for a given question, since both resolve successfully.
Only an explicit rule closes that ambiguity.

## 2. Category and branch hierarchy

Product/category dimensions on `MIS_DEEP_DIVE2` nest in this order, broadest
to narrowest: `division_name` -> `item_category_name` -> `product_group_name`
-> `special_product_group_name`. When drilling into a decline or growth
pocket, follow this order (division, then category, then product group, then
special product group) rather than jumping straight to the narrowest cut —
this keeps findings traceable back to a broader, reconciled total.

`store_no` (values like `CFH014`, `CFH017`, ..., `CFH022`) is the branch/entity
dimension — see the existing comparable-branch scope rule for which stores
count in YoY comparisons.

*(Confirmed from the actual last insight run: FMCG FOOD -> CF-CONFECTIONERY ->
CF-CHOCOLATE -> CHOCOLATE COATED BARS was exactly the drill path the
investigator used to explain the quantity decline.)*

## 3. Measures to ignore — report-formatting plumbing, not business metrics

The model has **no hidden measures** (`Hidden: ... 0 measures` in the raw
scan), so every measure below is fully visible to the agent and must be
deliberately excluded rather than filtered by a hidden flag. None of the
following are business KPIs. They should never be selected as a primary
metric, a driver, or a finding, and their movement should never be described
in a report:

- Any measure named `IND ...` or `IND` (e.g. `IND REVENUE DEEP DIVE`, `IND QTY
  DEEP DIVE`, `IND TRANSACTIONS DEEP DIVE`, `IND RETAIL PRICE DEEP DIVE`, `IND
  SPEND PER TRANS DEEP DIVE`, `IND SPEND PER TRANS DEEP DIVE NEW`, `IND QTY PER
  TRANS DEEP DIVE`) — these only return an up/down/flat icon character for a
  report visual.
- `ShowButton_CF022_v1` and `CF022_AccessText` — these only control whether a
  "new location" button/text shows on the report for branch CFH022; they are
  not sales data.
- `Last Refresh` — a technical data-refresh timestamp, not a business figure.
- On `CAT_TABLE`: `Measure`, `Measure 0`, `Measure 100`, `Measure 1-contr`,
  `COUNT`, `COUNT_TOTAL`, `COUNT_PLUS`, `COUNT %`, `sum deg cur rev`, `sum deg
  past rev`, `contribution cur`, `contribution past`. These form one
  self-contained "share of revenue in currently-declining categories" widget
  built around an internal `Measure` classification flag — they are report
  plumbing for that one visual, not independent, reusable business metrics.
- `CATEGORY_NO` (distinct count of product groups) is a structural
  assortment-breadth count, not a performance metric. Fine to cite as context
  ("N product groups sold") but never report its period-over-period change as
  a business finding.

### Known broken measure

`Measure 2` (on `CAT_TABLE`) references a table/column that do not exist in
this model — its DAX is:
```
(SUM(MIS_DEEP_DIVE[NET_SALE_VAL_CURRENT])-SUM(MIS_DEEP_DIVE[CURRENT_YR_REVENUE]))/SUM(MIS_DEEP_DIVE[NET_SALE_VAL_CURRENT])
```
There is no table called `MIS_DEEP_DIVE` in this model (only `MIS_DEEP_DIVE2`
exists), and `MIS_DEEP_DIVE2` has no `CURRENT_YR_REVENUE` column. This measure
will fail whenever evaluated. If a query referencing it errors out, that's
expected model behavior, not an agent/validator bug.

## 4. Time grain — monthly only, no daily/weekly cadence exists

This model's only genuine business time grain is `MIS_DEEP_DIVE2[month]`
(integer 1-12, representing month-of-year within the current-vs-prior-year
comparison window already embedded in the `_current`/`_ly` measure pairs).
`month` is the finest grain available for any trend, period, or
sustained-decline/growth analysis.

`max_date` (on `MIS_DEEP_DIVE2` and `MIS_BASE_FILE_MONTHLY_BRAND_TB`) and the
`UPDATED_DATE` measure are a load/batch marker, not a business activity date —
the last live run's own temporal gate measured over half of all tracked
revenue landing on a single date bucket (a month-end batch load), which is why
it's rejected in favor of `month`. No table in this model captures individual
transaction dates, so there is no daily or weekly cadence to recover here —
this is a data-shape fact, not a config bug. (`insight_recent_week_enabled`
and `insight_daily_enabled` are correctly `false` in `config.json` for this
reason and don't need to change unless a real daily-grain table is added to
the model later.)

## 5. Rate and price measures are ratios — never sum them

`retail price current year`, `retail price past year`, `RETAIL PRICE GROWTH`,
`CURR_PRICE_BR`, `PAST_YEAR_RP`, `PRICE DIFFERENCE`, `QUANTITY PER TRANSACTION
CURRENT YEAR`/`PAST YEAR`/`GROWTH`, and `SPEND PER TRANSACTION CURRENT
YEAR`/`PAST YEAR`/`GROWTH` are all derived ratios (revenue/quantity or
revenue/bills or quantity/bills). Never sum or average these across stores,
months, or categories — always recompute them from the summed numerator and
denominator at the grain being reported, and always describe a movement in
one of these as a rate/mix effect, never automatically as "price" alone
(volume mix inside a category can move the blended rate without any list
price changing).

## 6. Tables outside the sales domain — ignore for business analysis

`Users`, `ODS`, `UserOdsMapping`, `RefreshTimeStamp`, and
`Latest_Refresh_Table` are Power BI app/access-administration tables (portal
user accounts and data-refresh bookkeeping), not sales data. Never treat them
as business dimensions or metrics in a report. `AA_MEASURE_TABLE` is an empty
measure-holding table (its one column, `Column1`, carries no business meaning)
used only to organize the measures listed above under one folder.

---

## Separately — worth checking, not a business rule

The model has one RLS role, `User`:
- `Users[email] = userprincipalname()`
- `MIS_DEEP_DIVE2`: no filter expression of its own, but it's reachable from
  `Users` via `Users -> UserOdsMapping -> ODS -> CAT_TABLE -> MIS_DEEP_DIVE2`,
  and those relationships are bidirectional.

The agent authenticates as your own delegated Power BI user (headless MSAL,
not app-only), so if that role is actually assigned to your account in the
service, `executeQueries` could silently return a filtered subset of
stores/categories rather than the full model. Worth a quick confirmation that
your connected identity isn't scoped by this role before trusting a run's
totals as complete — this isn't something `business_rules.md` can fix, since
it happens before any query the agent writes even runs.

---

## 7. How to take insights — the methodology (candidate for `business_rules.md`)

This is a plain-English generalization of exactly what happened in the last
real run, turned into a rule. It's written so it could be pasted into
`business_rules.md` as-is.

1. Start from the reconciled comparable population (see the comparable-branch
   scope rule) — never a total that mixes in excluded/new entities.
2. Rank movements by materiality — size of the change **and** its share of
   the total change — not by which one is largest in absolute terms or which
   one happens to get noticed first.
3. Split every revenue movement into how much came from more/fewer units (or
   more/fewer transactions) versus how much came from a higher/lower rate per
   unit. The two must add back exactly to the total change. Never call the
   rate effect "price" outright — at this grain it can include mix (a shift
   toward higher- or lower-value items), not only a list-price change.
4. A contribution share above 100% (or below 0%) is a real, valid result — it
   means other segments partly offset the mover. Describe it as "more than
   offsetting declines elsewhere," never treat it as an error.
5. When drilling into where a movement concentrates, follow the category
   hierarchy top-down (division -> item category -> product group -> special
   product group) and stop once the picture is clear — either genuine
   concentration in a few segments, or a broad/even spread. Never present a
   single top-N slice as the complete picture; say when it's a partial
   ranking.
6. Cross-check the finding along more than one driver where possible — does
   quantity **and** transaction count move the same direction as revenue, or
   does one move while the other doesn't? The latter usually means a
   basket-size/mix story, not a "more shoppers" story.
7. Keep language hedged and evidence-based throughout — "consistent with,"
   "associated with," "worth validating further" — never assert a definitive
   root cause, and always end with a concrete next check a human could run.
8. Only surface a finding that is genuinely new or has materially changed
   since it was last reported. A repeat of an already-reported story should
   be suppressed, not re-announced.

## 8. Worked example — how one real finding was actually reached

An end-to-end walk-through of an actual signal from the last run, real
numbers included, so the methodology above isn't abstract.

**The question the data raised:** comparable revenue rose +3.46M in total.
Which store explains most of that?

**Step 1 — deterministic detection (no LLM).** The stat detector ranked every
store's contribution to the total revenue change. CFH021 came out on top:
+4.25M, which is 122.7% of the total +3.46M comparable increase (other
stores' declines ate into the total — this is exactly rule 4 above: a >100%
contributor is valid, not an error).

**Step 2 — deterministic decomposition (no LLM), cross-checked two ways:**
- Via quantity: of CFH021's +4.25M, +950K came from more units sold and
  +3.30M from a higher blended revenue-per-unit (both reconcile exactly to
  +4.25M).
- Via transactions: +2.94M came from more bills and +1.30M from higher spend
  per bill.

**Step 3 — the memory/novelty gate (no LLM).** This story's fingerprint
(`story_key`) was checked against prior runs; memory was empty this run, so
it was eligible. It was one of 8 signals selected out of 101 raw candidates
(50 eligible after the per-level cap).

**Step 4 — the LLM investigator's one question:** "What categories or
product groups within CFH021 drove this, especially where bills and quantity
also rose?" It ran exactly one DAX probe — `item_category_name` for
`store_no = CFH021`, filtered to the same comparable-store population, top 20
by revenue Growth.

**Step 5 — what came back:** growth was spread across many categories, not
one — CF-MENS FASHION +805K, CF-GROCERY FOOD +590K, CF-ELECTRONICS +568K,
CF-PERSONAL CARE +524K, CF-TOYS +302K, plus a longer tail. One category
(CF-CHILLED & DAIRY) grew in revenue and quantity but had *fewer* bills —
flagged as a likely basket-size/mix effect rather than more shoppers, exactly
per rule 6 above.

**Step 6 — the hedged conclusion actually written:** "This looks more like
broad category expansion at CFH021 than a one-off pocket, and is worth
validating further in the largest winning categories" — never "CFH021 grew
*because of* X," always association plus a concrete next check (drill
CF-MENS FASHION and CF-GROCERY FOOD into `product_group_name` next).

---

## Does adding this to `business_rules.md` make the agent go "only" that direction?

Partially — and it matters which steps of the example above we're talking
about:

- **Steps 1–3 are pure Python** (`insight_stat_detector.py`,
  `insight_novelty_filter.py`) — contribution ranking, the volume/rate split,
  story-key fingerprinting, materiality scoring. None of that reads
  `business_rules.md`. Adding prose there cannot change what candidates get
  detected or how they're scored — that only changes if the code changes.
- **Steps 4–6 are where an LLM actually reasons** (the investigator choosing
  what to probe, the synthesizer choosing how to write it up) — these are
  exactly the nodes `business_rules_block()` injects into (see `graph.py` /
  each agent module). Adding the methodology above would make the
  investigator's drill choices and the synthesizer's phrasing *more
  consistently* follow this pattern run over run.
- But "authoritative" in `business_rules.md`'s own framing means "should
  override the agent's generic defaults" — it's a strong instruction to the
  LLM, not a hard constraint the way the DAX validator or `scope_validator`
  are. An LLM can still deviate on a given run. If something needs to be
  *guaranteed* every time (like the CFH022 exclusion, which is also
  machine-enforced by `scope_validator.py`, not just prompted), that has to
  be built into code — `business_rules.md` alone can't guarantee it.

Net: yes, pasting sections 1–8 into `business_rules.md` should measurably
improve the *consistency* of the insight branch's reasoning and prose. It
will not change the deterministic detection engine, and it's a strong nudge
to the LLM steps, not an unbreakable rule.
