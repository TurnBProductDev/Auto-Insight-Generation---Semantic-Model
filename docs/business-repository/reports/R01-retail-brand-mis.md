# R01 — Retail Brand MIS (Monthly Brand Performance)

| Field | Value |
|---|---|
| **Report ID** | R01 |
| **Domain** | Retail — sales and brand performance |
| **Primary fact table** | `MIS_BASE_FILE_MONTHLY_BRAND_TB` |
| **Reporting grain** | Month x Store x Division x Category x Product group x Brand |
| **Current period** | Jan–Jul 2026 YTD vs Jan–Jul 2025 |
| **Data through** | 2026-07-27 (model refreshed 2026-07-28 04:31) |
| **Business owner** | *unassigned — required* |
| **Technical owner** | *unassigned — required* |
| **Status** | Active — **live-verified 2026-07-28** |
| **Profile version** | 2.0 (2026-07-28) |

> **Verification status.** Version 2.0 was verified against the live semantic model over
> the Power BI REST API on 2026-07-28. Version 1.0 was compiled from committed repo
> artifacts and **contained material errors**, corrected here and listed in §11.
> Remaining **[UNVERIFIED]** items are in §9.

---

## 1. Purpose

Monthly management information on brand-level retail trading performance across a
five-store estate, comparing the current year against the prior year. It answers:

1. Is the business growing, and by how much?
2. Is growth coming from more customers, bigger baskets, or higher prices?
3. Is growth broad across the range, or concentrated?

Consumers are commercial and category management. The report recommends checks, never
actions (see [global standards §4.2](../00-global-standards.md#42-language)).

---

## 2. Semantic model map

**19 tables — 11 business, 8 auto-generated date tables.**

### 2.1 Business tables

| Table | Role | Key content |
|---|---|---|
| `MIS_BASE_FILE_MONTHLY_BRAND_TB` | **Primary fact** — monthly brand sales | `net_sale_val_current`/`_ly`, `net_sales_qty_current`/`_ly`, `DIST_SKUS_CY`/`_LY`, `store_no`, `month`, `MONTH_NAME`, `max_date`, division / category / product-group / family hierarchy |
| `CAT_TRANSACTIONS` | **Footfall fact** — bill counts | `dist_bill_curr`, `dist_bill_ly`, `store_no`, `month`, category keys |
| `CAT_TABLE` | Category performance + breadth measures | `CURRENTREV`, `PREVIOUS`, `ABS1`, `store_no`, `month`, `special_product_group_name`, `dep`, `sec` |
| `MIS_DEEP_DIVE2` | Deep-dive fact, same shape as primary | Mirrors the primary fact's value/qty/SKU columns |
| `rep_dept_wise_perf_eval_rpt` | **Daily department/section bills** | `TY_DATE`, `DOC_DAY`, `DOC_MONTH`, `DOC_YR`, `WEEK`, `DAY_OF_WEEK`, `DEP_BILLS`, `LOC_BILLS`, `SEC_BILLS`, `LOC_CODE` |
| `AA_MEASURE_TABLE` | Measure host (disconnected) | 28 growth measures |
| `ODS`, `Users`, `UserOdsMapping` | **Row-level security infrastructure** | `azureAdUserId`, `email`, `roleId`, `customerId`, `odsId` |
| `RefreshTimeStamp`, `Latest_Refresh_Table` | Data currency | `RefreshTimeStamp`, `MaxRefreshDate` |

**Measure count: 45** (28 on `AA_MEASURE_TABLE`, the rest on `CAT_TABLE` and others) —
not the 56 recorded in repo notes, which described a different model state.

### 2.2 Row-level security — governance flag

`Users` / `UserOdsMapping` / `ODS` form a user-to-ODS RLS chain keyed on
`azureAdUserId` and `email`. **RLS is not currently applied by the agent** —
`powerbi_effective_username` and `powerbi_rls_roles` are both empty in `config.json`,
so runs execute with the signed-in identity's full visibility.

That is correct for a head-office analytical run, but it means **agent output is not
automatically safe to distribute to a store-scoped audience**. `ai_content_publish_enabled`
is `true` for client `cityflower` — confirm the destination audience is entitled to
all-store data. **[UNVERIFIED — needs a business answer, see §9.]**

### 2.3 The prior-year pattern — read before writing any DAX

This model does **not** use a date dimension with time intelligence. Prior-year values
are held as **separate physical columns on the fact row** (`net_sale_val_current`
alongside `net_sale_val_ly`).

- `SAMEPERIODLASTYEAR`, `DATEADD`, `PARALLELPERIOD` are **not** how this model computes
  prior year. Do not introduce them.
- A row is self-contained for YoY; comparison needs no date filter context.
- Filtering to a period filters both years at once, keeping the comparison aligned.

### 2.4 Auto date/time hierarchies are ON

Eight auto-generated tables (`LocalDateTable_*`, `DateTableTemplate_*`) exist for the
`Date` columns. They inflate model size and serve no analytical purpose here, since the
model does not use time intelligence (§2.3). Candidate for removal —
**[UNVERIFIED]**, needs a BI-developer decision.

### 2.5 Column drift — resolved

The published dataset uses **lowercase** fact columns and **has no `CATEGORY_NAME`**:

| Concept | Published dataset (authoritative) |
|---|---|
| Current / prior revenue | `net_sale_val_current` / `net_sale_val_ly` |
| Current / prior quantity | `net_sales_qty_current` / `net_sales_qty_ly` |
| Current / prior bills | `CAT_TRANSACTIONS[dist_bill_curr]` / `[dist_bill_ly]` |
| Category | `special_product_group_name`, `product_group_name`, `item_category_name` |

The Desktop-file names (`NET_SALE_VAL_CURRENT`, `CAT_TABLE[CATEGORY_NAME]`) **do not
exist here**. Bind to measure names wherever a measure encodes the logic.

### 2.6 Key columns

| Column | Role |
|---|---|
| `store_no` | Entity key. Present on `MIS_BASE_FILE_MONTHLY_BRAND_TB`, `CAT_TRANSACTIONS`, `CAT_TABLE`, `MIS_DEEP_DIVE2` — the comparable filter must be applied to **all four** |
| `month` | Business month 1–12 on all monthly facts. **The validated grain for this report** |
| `max_date` | Last transaction date within the month — the true data watermark |
| `LOC_CODE` | Store key on the daily table (distinct from `store_no`) |

**There is no `UPDATED_DATE` column in this model.** `UPDATED_DATE` exists only as a
*measure* on `AA_MEASURE_TABLE`. The batch/load-date hazard recorded in earlier repo
notes does not apply to this dataset — see §11.

---

## 3. Entity master — store estate

**Live-verified 2026-07-28.** Exactly five stores; no others exist.

| Store | Classification | Prior-year revenue | Data through | Treatment |
|---|---|---|---|---|
| `CFH014` | Comparable | 39,000,626 | 2026-07-27 | Full like-for-like |
| `CFH017` | Comparable | 22,060,077 | 2026-07-27 | Full like-for-like |
| `CFH018` | Comparable | 24,388,524 | 2026-07-27 | Full like-for-like |
| `CFH021` | Comparable | 36,520,839 | 2026-07-27 | Full like-for-like |
| `CFH022` | **Current-only (new)** | **0 — exactly zero in every month** | **2026-06-13** | Excluded from all comparable calculations |

**Comparable population: `CFH014`, `CFH017`, `CFH018`, `CFH021`.**

The business rule is **confirmed by the data**: `CFH022` carries `net_sale_val_ly = 0`
and `dist_bill_ly = 0` in all months, so it has no prior-year basis of any kind. It is
excluded from every comparable total, YoY change, growth percentage, ranking,
concentration calculation, contribution share, and comparable denominator — across
summary queries, insight scans, investigation probes, repaired queries, and final
report statements.

It is **not** removed from overall current-period actuals: `CFH022` contributed
**11,906,056** in the current period, **8.7% of total current revenue**, reported
separately as new-store contribution.

### 3.1 CFH022 data stops 2026-06-13 — open issue

`CFH022`'s data ends six weeks before the rest of the estate, and its June revenue
collapses to **427,159** against a ~2.1M monthly run rate — a partial month, not a
trading collapse. Either the feed broke or the store ceased trading.
**Unresolved — see §9 item 3.** Until answered, `CFH022`'s current-period contribution
is understated and must not be presented as a full-period figure.

### 3.2 Estate materiality

Four comparable stores. A single store is roughly a quarter of the comparable base, and
§5.4 shows one store currently drives the entire group result. Store-level detail
belongs in every group-level explanation.

### 3.3 Configuration mirror — verified in sync

```json
"insight_comparable_population": ["CFH014", "CFH017", "CFH018", "CFH021"],
"insight_excluded_entities":     ["CFH022"]
```

Confirmed present and correct in the active `config.json` on 2026-07-28.

---

## 4. KPI framework

Eight KPIs from `fastapi_backend/app/kpi_thresholds.json`. All eight measures were
executed successfully against the live model.

| # | KPI | Bound measure | Direction | Red | Amber | Green |
|---|---|---|---|---|---|---|
| 1 | Revenue Growth % | `[revenue growth %]` | Higher better | < -3% | -3% to 0% | >= 0% |
| 2 | Volume Growth % | `[QTY GROWTH %]` | Higher better | < 0% | 0% to 2% | >= 2% |
| 3 | Footfall Growth % | `[bills growth %]` | Higher better | < -3% | -3% to 0% | >= 0% |
| 4 | ASP Growth % | `[retail price current year]` / `[retail price past year]` | Higher better | < -3% | -3% to 0% | >= 0% |
| 5 | ATV Growth % | `[SPEND PER TRANSACTION CURRENT YEAR]` / `...PAST YEAR` | Higher better | < -3% | -3% to 0% | >= 0% |
| 6 | UPT Growth % | `[QUANTITY PER TRANSACTION CURRENT YEAR]` / `...PAST YEAR` | Higher better | < 0% | 0% to 2% | >= 2% |
| 7 | Category Decline Breadth % | `[COUNT %]` | **Lower better** | > 55% | 40% to 55% | < 40% |
| 8 | At-Risk Revenue Concentration Delta | `[sum deg cur rev]` / `[sum total cur rev]` vs prior | **Lower better** | > +3pp | -3pp to +3pp | <= -3pp |

Definitions and reconciliation identities:
[global standards §2](../00-global-standards.md#2-metric-dictionary).

### 4.1 Threshold philosophy

Volume and UPT hold the tightest bars — **flat is already Red**. Deliberate: units are
the inflation-free signal of real demand, and UPT measures range effectiveness. Revenue,
footfall, ASP, and ATV tolerate a 3% decline before Red because all are exposed to price
and mix effects that move without real demand changing.

### 4.2 Measure coverage notes

- KPIs 4, 5, 6 are **not materialised as percentages** in the model — only absolute
  deltas exist (`[RETAIL PRICE GROWTH]`, `[SPEND PER TRANSACTION GROWTH]`,
  `[QUANTITY PER TRANSACTION GROWTH]`). The rates are computed by the KPI layer.
- KPI 8 is **bound to no visual** — invisible to dashboard readers, reaching the
  business only through this agent.
- `[contribution cur]` / `[contribution past]` use unsafe raw division; the KPI
  definition wraps both in `DIVIDE`. Prefer the KPI form.
- **Footfall comes from `CAT_TRANSACTIONS`, not the primary fact.** The primary fact
  has no bill-count column. Any footfall-derived metric spans two tables, so the
  comparable filter must be applied to both.

---

## 5. Measured position — Jan–Jul 2026 YTD

**Live-verified 2026-07-28.** Both columns use the model's own measures; the only
difference is scope.

| # | KPI | Unfiltered (as dashboarded) | **Comparable (correct)** | Delta |
|---|---|---|---|---|
| 1 | Revenue Growth % | +12.61% Green | **+2.84%** Green | **-9.76pp** |
| 2 | Volume Growth % | +9.98% Green | **-1.27% Red** | **-11.25pp** |
| 3 | Footfall Growth % | +12.87% Green | **+3.03%** Green | **-9.85pp** |
| 4 | ASP Growth % | +2.39% Green | **+4.17%** Green | +1.78pp |
| 5 | ATV Growth % | -0.24% Amber | **-0.18%** Amber | +0.06pp |
| 6 | UPT Growth % | -2.56% Red | **-4.17% Red** | -1.60pp |
| 7 | Category Decline Breadth % | 33.30% Green | **48.19% Amber** | **+14.89pp** |
| 8 | At-Risk Concentration Delta | -4.59% Green | **-6.51%** Green | -1.92pp |

Scorecard: unfiltered **6 Green / 1 Amber / 1 Red** → comparable **4 Green / 2 Amber /
2 Red**.

> **July is a partial month** — data runs to 2026-07-27, 27 of 31 days. Whether
> `net_sale_val_ly` is day-aligned to the same 27 days is **[UNVERIFIED]** (§9 item 2).
> If it is not, every figure above is understated.

### 5.1 The identities reconcile exactly

| Identity | Computed | Reported | Match |
|---|---|---|---|
| Footfall x ATV | 1.0303 x 0.9982 = **+2.84%** | Revenue +2.84% | Exact |
| Footfall x UPT | 1.0303 x 0.9583 = **-1.27%** | Volume -1.27% | Exact |
| Volume x ASP | 0.9873 x 1.0417 = **+2.85%** | Revenue +2.84% | Exact |

The measure set is arithmetically sound. Any future break outranks commercial
interpretation.

### 5.2 The scoping defect, now quantified

The dashboard and `benchmark_results.json` execute each KPI **unfiltered**, so
`CFH022` — a store with 11.9M of current revenue and **exactly zero** prior-year
revenue — is inside the growth calculation. Dividing new-store revenue by a prior-year
base it never contributed to inflates every growth metric.

**The headline overstates like-for-like revenue growth by 9.8 percentage points:
+12.61% reported against +2.84% actual.**

Two KPIs change status once corrected:

- **Volume Growth flips Green to Red.** Reported +9.98%; actual **-1.27%**. Real unit
  demand is *contracting*, not growing at ten percent.
- **Category Decline Breadth flips Green to Amber**, 33.30% to **48.19%**. Nearly half
  of all categories are declining — not a third.

This is not a rounding matter. It is the difference between a business growing strongly
and one whose volumes are shrinking behind price increases.

### 5.3 Commercial reading

**Revenue growth is almost entirely price-driven, and real demand is contracting.**

On a like-for-like basis, revenue grew **+2.84%** while units fell **-1.27%**. The gap
is ASP at **+4.17%**: customers paid more per unit and bought fewer. Strip price out and
the trading position is negative.

**The basket is deteriorating faster than the headline suggests.** UPT at **-4.17%** is
the worst KPI on the board — 63% worse than the unfiltered view implied. Shoppers visit
slightly more often (footfall +3.03%) but take materially less each time. ATV is flat at
-0.18% *only* because higher prices offset the smaller basket almost exactly.

**Growth is narrow, not broad.** Corrected decline breadth of **48.19%** means nearly
half of categories are going backwards, in a business reporting positive revenue growth.
The one genuinely encouraging signal is At-Risk Concentration at **-6.51pp**: declining
categories account for a materially smaller share of revenue than a year ago, so the
weak half is also the smaller half. Exposure is shrinking even as breadth widens.

**Composition risk.** Of +2.84% revenue growth, roughly +3.03pp is traffic and -0.18pp
is basket value, with the unit decline masked by price. This is only durable while price
increases hold and traffic keeps growing. If either stalls, revenue turns negative
quickly — there is no volume contribution underneath.

**What the arithmetic cannot settle.** ASP +4.17% against UPT -4.17% is almost perfectly
symmetric, admitting two readings: *price-led* (prices rose, shoppers trimmed baskets in
response) or *mix-led* (a shift toward higher-priced, lower-count categories). The first
is a demand problem; the second may be a deliberate margin strategy working as intended.
**Only a category-level decomposition separates them**, and that is the single most
valuable open question on this report (§9 item 1).

### 5.4 Store-level detail — one store carries the group

| Store | Revenue YoY | Volume YoY | Read |
|---|---|---|---|
| `CFH014` | **-0.1%** | -2.3% | Flat revenue, units eroding |
| `CFH017` | **-5.5%** | -6.5% | **Declining on both** |
| `CFH018` | **+1.8%** | -1.4% | Revenue up on price only |
| `CFH021` | **+11.8%** | +2.5% | Carrying the group |
| `CFH022` | n/a (new) | n/a | 11.9M current-only, data ends 13 Jun |

Two findings management should see:

**`CFH021` is the entire comparable growth story.** Without it the other three stores
sum to a revenue *decline*. Its +11.8% revenue against +2.5% units means even the
strongest store is largely price-driven. Its monthly pattern is volatile — Jan +22.0%,
Feb +29.6%, then Mar -7.8% — which is worth understanding before treating the run rate
as a baseline.

**`CFH017` is deteriorating and needs attention.** Revenue -5.5%, units -6.5%, negative
in five of seven months with the trend worsening through the second quarter
(May -10.3%, Jun -13.9%, Jul -8.8%). **Volume is falling faster than revenue**, meaning
price is masking an accelerating demand problem at this store.

### 5.5 March was weak everywhere — almost certainly Ramadan timing

Every comparable store declined sharply in March: `CFH014` -8.6%, `CFH017` -15.4%,
`CFH018` -10.2%, `CFH021` -7.8%. Meanwhile February was positive at every store, and
strongly so at `CFH021` (+29.6%).

This is the classic signature of **Ramadan moving between months**. Ramadan follows the
Hijri calendar and falls roughly 11 days earlier each Gregorian year, so a substantial
part of the Ramadan and pre-Eid trading peak shifted from March last year into February
this year. February gains what March loses.

Four independently managed stores falling by a similar amount in the same month, having
all risen the month before, is far more consistent with the calendar than with
simultaneous trading failure.

**Do not read March as a performance failure**, and do not read February as a genuine
surge, until the Hijri dates for both years are matched against the monthly figures.
The honest comparison for a moving-feast business is Ramadan-period against
Ramadan-period, not March against March (§9 item 5).

---

## 6. Data quality register

### 6.1 No trading-date column on the monthly facts

The monthly facts carry `month` (1–12) and `max_date` (last transaction date in that
month). `month` is the finest validated grain for this report. No day-of-week analysis,
no promotional-period isolation, no true weekly trend from these tables.

**There is no batch/load-date hazard in this model** — `UPDATED_DATE` is a measure, not
a column, and does not appear on any fact table. Earlier repo notes describing a
month-end-concentrated load date describe a different dataset (§11).

### 6.2 A genuine daily table exists — but cannot support YoY

`rep_dept_wise_perf_eval_rpt` holds real daily data: `TY_DATE` from **2026-01-01 to
2026-07-31**, 48,435 rows, 5 locations, with `DOC_DAY` / `WEEK` / `DAY_OF_WEEK`.

Three limits before anyone enables daily analysis:

1. **Current year only** (`DOC_YR` = 2026 exclusively) — no prior-year basis, so no YoY.
2. **Bills only** (`DEP_BILLS`, `LOC_BILLS`, `SEC_BILLS`) — no revenue or quantity.
3. **`max(TY_DATE)` is 2026-07-31**, four days beyond the 2026-07-27 watermark —
   future-dated or padded rows that would corrupt a trailing-window calculation.

`insight_recent_week_enabled` and `insight_daily_enabled` are correctly `false`. Enabling
them is a real opportunity for **current-year trend and day-of-week patterns**, but
requires handling all three limits (§9 item 6).

### 6.3 Data is current — not stale

`max_date` = **2026-07-27**; model refreshed **2026-07-28 04:31**. The dataset is fresh
to within a day. The "~2.5 years stale" claim in earlier repo notes is **wrong for this
dataset** (§11).

### 6.4 July is a partial month

Data covers 27 of 31 July days. Whether the prior-year column is day-aligned is
**[UNVERIFIED]** and material to every figure in §5 (§9 item 2).

### 6.5 CFH022 data ends 2026-06-13

Six weeks behind the estate, with a partial final month. Feed failure or store closure —
unresolved (§3.1).

### 6.6 Auto date/time hierarchies

Eight auto-generated date tables inflate the model without serving any analysis (§2.4).

### 6.7 KPI 8 has no visual

At-Risk Revenue Concentration Delta appears nowhere on the canvas.

---

## 7. Deviations from global standards

| Standard | Deviation | Reason |
|---|---|---|
| Daily / weekly analysis available | **Disabled** | Daily table is current-year and bills-only (§6.2) |
| Trading date named | **Monthly facts have none**; a daily table exists but is unusable for YoY | Model design |
| Conventional date dimension | **Not used** | Prior year held as physical columns (§2.3) |

No deviation from the comparability doctrine, metric dictionary, or reporting standards.

---

## 8. Trading geography and calendar

**Saudi Arabia** **[BUSINESS-STATED, 2026-07-28]**. Currency SAR. Timezone
`Asia/Riyadh` (UTC+3, no daylight saving). Weekend **Friday–Saturday**; working week
Sunday–Thursday.

`month` runs 1–12 and the current period is months 1–7 of 2026, so the reporting year
appears to be the **Gregorian calendar year** with January as month 1. **[INFERRED]** —
a 4-4-5 or retail-calendar convention would change month comparability.

**The Hijri calendar drives trade.** Ramadan and the two Eids move roughly 11 days
earlier each Gregorian year, shifting peak trade between calendar months. Monthly YoY
comparisons are structurally distorted by this, which is why §5.5 exists. A
Ramadan-aligned comparison would be more honest than March-versus-March, though the
model offers no mechanism for one today.

### 8.1 Config corrections applied 2026-07-28

`insight_history_timezone` and `summary_history_timezone` were both `Asia/Kolkata` and
have been corrected to `Asia/Riyadh`. History and memory entries written before this
date are stamped 2.5 hours off.

### 8.2 Known code limitation — week folding is hardcoded Monday–Sunday

`insight_week_start` is accepted as a config value and passed through
`pick_target_week()` and `fold_weeks()`, **but neither honours it** — both hardcode
Monday–Sunday via `_monday()` and a fixed 6-day offset. Setting it to `sunday` would
have no effect.

For a Saudi estate this matters: a Monday–Sunday week splits the Friday–Saturday
weekend across two buckets, so weekly figures would mix a weekend day into each week and
week-over-week comparisons would be distorted.

Currently harmless — `insight_recent_week_enabled` is `false` (§6.2) — but this must be
fixed before weekly monitoring is ever switched on (§9 item 6).

### 8.3 VAT **[UNVERIFIED]**

Saudi VAT is 15%. Whether `net_sale_val_current` is gross or net of VAT is unconfirmed
and affects how every revenue figure should be described (§9 item 14).

---

## 9. Open items

| # | Item | Type | Owner |
|---|---|---|---|
| 1 | **Decompose ASP +4.17% against UPT -4.17% by category** to separate price-led from mix-led (§5.3) | Commercial — highest value | Business |
| 2 | **Confirm prior-year day alignment for partial July** (§6.4) — affects every figure in §5 | Data quality — blocking | Technical |
| 3 | **Resolve CFH022's 2026-06-13 cutoff** — feed failure or closure? (§3.1) | Data quality | Technical |
| 4 | **Fix the dashboard's unfiltered KPIs** — they overstate growth by ~9.8pp (§5.2) | Governance — blocking | Technical |
| 5 | **Match Hijri dates to the monthly figures** to confirm the March decline is Ramadan timing (§5.5) | Commercial | Business |
| 6 | Decide whether to enable current-year daily/weekly analysis (§6.2). **Blocked on the Monday–Sunday folding bug** (§8.2) — a Saudi week is Sunday–Thursday | Capability | Technical |
| 14 | **Confirm whether revenue is gross or net of 15% VAT** (§8.3) | Definition | Business |
| 7 | **Confirm the `cityflower` publishing audience is entitled to all-store data** (§2.2) | Governance — blocking | Business |
| 8 | Investigate CFH017's accelerating decline (§5.4) | Commercial | Business |
| 9 | Confirm the fiscal calendar (§8) | Definition | Business |
| 10 | Assign business and technical owners | Governance | Management |
| 11 | Decide whether to remove auto date/time hierarchies (§2.4) | Technical debt | Technical |
| 12 | Decide whether KPI 8 gets a visual (§6.7) | Reporting | Business |
| 13 | Confirm footfall is transaction count, not door-counter traffic | Definition | Business |

---

## 10. Verified reference — comparable-scope DAX

Applies the comparable population to all four `store_no` tables. Uses `TREATAS` (never
`KEEPFILTERS`) and runs one measure per query.

```dax
EVALUATE
CALCULATETABLE (
    ROW ( "Result", [revenue growth %] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'MIS_BASE_FILE_MONTHLY_BRAND_TB'[store_no] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'CAT_TRANSACTIONS'[store_no] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'CAT_TABLE'[store_no] ),
    TREATAS ( { "CFH014", "CFH017", "CFH018", "CFH021" }, 'MIS_DEEP_DIVE2'[store_no] )
)
```

Verified working against all eight KPI measures on 2026-07-28.

---

## 11. Corrections from version 1.0

Version 1.0 was compiled from repo artifacts, principally `CLAUDE.md`, which describes a
**different dataset**. Live verification overturned five claims:

| v1.0 claim | Reality | Impact |
|---|---|---|
| Data ~2.5 years stale (through 2023-12-31) | **Current to 2026-07-27**, refreshed daily | Reversed |
| `UPDATED_DATE` is a batch/load date holding 0.53 of revenue | **No such column** — `UPDATED_DATE` is a measure | Hazard does not exist here |
| `DOC_MONTH` is the validated grain | `DOC_MONTH` is on the daily table only; monthly facts use `month` | Corrected |
| Three business tables | **Eleven**, incl. a daily table, a second fact, and RLS infrastructure | Materially understated |
| CFH022 inflates growth by "several points" | **9.76pp** on revenue, **11.25pp** on volume | Far larger |

**Lesson for this repository:** `CLAUDE.md` is engineering documentation about the
codebase, not a verified description of any particular dataset. Treat it as
**[UNVERIFIED]** for business facts. Only live queries or committed run artifacts
promote a claim to **[VERIFIED]**.

---

## 12. Change log

| Date | Version | Change | Author |
|---|---|---|---|
| 2026-07-28 | 2.0 | Live-verified against the semantic model. Corrected five material errors (§11). Added RLS, daily table, second fact table, footfall source. Quantified the scoping defect at 9.76pp and recomputed all eight KPIs under comparable scope. Added store-level analysis. | Claude |
| 2026-07-28 | 1.0 | Initial profile from committed repo artifacts. **Superseded — contained material errors.** | Claude |
