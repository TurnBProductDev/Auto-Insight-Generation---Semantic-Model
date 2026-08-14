# Domain Verticals — WP0 Findings

**Status:** WP0 investigation complete. Q1–Q7 answered against the live models on **2026-08-13**.
The spike of brief §1.7 is complete and **passed with one plan-changing result**.

**Method.** `scripts/probe_summary_universe.py --config <path> --deep` against each model, plus
four rounds of hand-written read-only DAX through `powerbi_executor.execute_python` (the throwaway
spike §1.7 asks for — not architecture, not committed). Probe configs forced
`azure_blob_upload`, `ai_content_publish_enabled`, both `*_history_enabled` off and both
`*_memory_storage` to `local`, so nothing was published and no production memory was touched.

**Headline.** Both inventory reports are **buildable**, and neither needs the 1.10 fallback. But
the brief's central assumption about *how* is wrong: **neither model holds a prior snapshot of its
main fact**, so there is no snapshot-over-snapshot comparison to build on. This changes the work
package order — see §9.

---

## 1. The three models

| Report | Dataset ID | Fact table | Rows | Tables / cols / measures |
|---|---|---|---|---|
| Sales YoY (existing) | `b3458a38-ad83-4e9a-b2f2-39d15c6aa22c` | `MIS_BASE_FILE_MONTHLY_BRAND_TB` | — | 17 / 150 / 47 |
| Inventory Management | `64eefa4b-d82f-41bd-a841-fc1cfbd7a88a` | `REP_SSR_STOCK_STATUS_REPORTV2` | 140,113 | 23 / 199 / 65 |
| Stock Age Analysis | `84212fd9-6504-4b22-a46b-e64109a1ab89` | `REP_SSR_SAG` | 158,446 | 7 / 73 / 16 |

All three share workspace `6d383900-b84d-4bce-afb4-b95453bee00a` and tenant
`315642c5-e14a-4c12-bf77-41ee070def79`.

---

## 2. Q1 — Same semantic model, or different? **DIFFERENT. All three.**

**Critical, and it breaks the chain design as WP1 implemented it.**

WP1 files insight memory at `<root>/<dataset_id>/chains/<chain_id>/memory.json`. Because the two
inventory reports live in **different datasets**, an `inventory` chain spanning them resolves to
two different files:

```
64eefa4b…/chains/inventory/memory.json     <- Inventory Management
84212fd9…/chains/inventory/memory.json     <- Stock Age Analysis
```

They would not share a memory, so WP8's "one investigative report across the chain" would not
work. Two consequences:

1. **Chain memory must be scoped by chain alone, not nested under a dataset.** The dataset is a
   property of a *report*, not of a chain. This is a WP8 change to `kernel/scoping.chain_dir`, and
   it is exactly the kind of thing WP0 exists to find before WP8 is written.
2. `insight_memory.story_key` includes `dataset` and `scope_hash(state)`, so story identities stay
   distinct per model even once the file is shared. That is **correct** — a finding in the ageing
   model is genuinely a different finding from one in the stock-health model — and it means pooling
   needs no cross-report suppression, which is the §1.8(b) argument holding up.

Cross-*domain* clubbing (inventory with sales) remains not meaningful, as the brief predicted.

**Cross-model consistency is excellent**, which supports pooling: total stock value is
SAR 50,831,646.81 in the ageing model and SAR 50,831,641.03 in the stock-health model — a
difference of **SAR 5.78 on SAR 50.8M** (0.00001%).

---

## 3. Q3 — Is there a snapshot date, distinguishable from a transaction date? **YES, cleanly.**

Both facts carry `UPDATED_ON` with **exactly one distinct value: 2026-08-12**.

```
ageing : rows=158,446  distinct_UPDATED_ON=1  min=max=2026-08-12
IM     : rows=140,113  distinct_UPDATED_ON=1  min=max=2026-08-12
```

The discriminator is mechanical, not a guess. In the same table the event dates have hundreds of
distinct values:

| Column | Distinct values | What it is |
|---|---|---|
| `UPDATED_ON` | **1** | the as-of stamp — correct filter is "latest" |
| `doc_date1purch` | 180 | purchase document date (event) |
| `DOC_DATE2` | 165 | document date (event) |
| `DOC_DATE3` | 1,443 | document date (event) |
| `REP_SSR_SAG[sortdate]` | 14 | **not a snapshot** — the batch purchase period, i.e. the age axis |

**A rule that generalises:** an as-of stamp has one distinct value per load; an event date has
many. WP4 can use cardinality-against-the-fact as the primary test rather than name matching,
which is what failed on `LOC_CODE` in the sales model.

`sortdate` is a trap worth naming: it is a Date column that varies per row, so a name- or
type-based scan would read it as a time axis. It is the *age* dimension (2024-08-01 → 2026-08-01,
mapping 1:1 to `PURCHASE_PERIOD` labels like `Dec-25`, `Aug-24 TO Jul-25`), not a series of
observations.

---

## 4. Q5 — Which measures are semi-additive, and does each reconcile? **Both answered.**

### 4a. The semi-additive trap is real — proven at 4.03×

The main facts hold one snapshot, so nothing can be summed across snapshots *there*. `SSR TREND`
holds **four**, and it behaves exactly as the brief predicted:

```
2026-06-01   SAR      51,677,750.96
2026-07-01   SAR      52,479,645.71
2026-08-01   SAR      49,775,351.19
2026-08-12   SAR      50,833,557.23
SUM of all snapshots  SAR 204,766,305.10   <- what a naive SUM returns
LATEST snapshot       SAR  50,833,557.23   <- the true current position
overstatement factor: 4.03x across 4 snapshots
```

This is brief §1.7 test #2, passed. `SSR TREND[sku_stock_value]` is `SEMI_ADDITIVE_LAST` and must
never be summed across `dates`. It is the only table in either model where the failure is
reachable, and it is the fixture WP4's `verify()` must refuse.

### 4b. Reconciliation passes on both models

Members at the snapshot add to the total **exactly**, which is the guarantee the whole product
rests on:

| Model | Sum of 7 locations | Overall (`REMOVEFILTERS`) | Difference |
|---|---|---|---|
| Ageing | 50,831,646.81 | 50,831,646.81 | **0.00** |
| Stock health | 50,831,641.03 | 50,831,641.03 | **0.00** |

The age axis also reconciles exactly, at both granularities: the 8 `AGE` buckets sum to
50,831,646.81, and the 3 finest of them (20,034,784.93 + 7,960,297.39 + 3,583,111.84) sum to
31,578,194.16 — precisely the consolidated `NEW AGE` "0-03 MONTHS" figure. BR-11's consolidation is
verified numerically.

### 4c. One real inconsistency to record

`SSR TREND` at its latest date is **SAR 50,833,557.23** against the main fact's
**SAR 50,831,641.03** — a gap of **SAR 1,916.20** on the same day. Small (0.004%) but non-zero, so
the two must never be presented as the same number, and a trend panel built from `SSR TREND`
should say it comes from the trend table.

---

## 5. Q2 — Do policy measures exist? **YES — richly, and materialised per row.**

**The 1.10 fallback tree does not apply.** No policy needs inventing. WP6/WP7 proceed as specified.

Three dedicated policy tables exist, and their contents match the rulebook:

| Table | Grain | Contents | Verified |
|---|---|---|---|
| `LEAD DAYS TABLE` | location × section | `LEAD_DAYS`, `SAFETY_DAYS` | 266 rows; `SAFETY_DAYS` uniformly **2** ✓ BR-19 |
| `EXCESS THRESHOLD` | location × section | `EXCESS_DAYS`, `EXCESS_MONTHS` | **280 rows = 40 sections × 7 locations** ✓ BR-21 |
| `RP TABLE` | location × SKU | `RP` (reorder point) | genuine per-SKU spread: 2,3,4,5,6,7,8,9,10,12,14,15,18,20,24 |

`EXCESS_DAYS` spread — 0, 6, 12, 15, 30, 45, 60, 75, 90, 105, 120, 180 — matches BR-21's table
value-for-value.

**Better still, the band is already on the fact row.** `EXCESS_THRESHOLD_DAYS` and `Reorder_Level`
are columns of `REP_SSR_STOCK_STATUS_REPORTV2`, so `SnapshotVsPolicySpine` reads a column rather
than joining a policy table — simpler and cheaper than the brief assumed.

**Note the shape of the baseline.** The policy is expressed in **days of cover**, not units: a SKU
is excess when `Burn-Out Days > EXCESS_THRESHOLD_DAYS`, and on the verge of stockout when
`BD < LEAD_DAYS + SAFETY_DAYS`. So `delta_kind = "distance"` measured in days, and the exposure
being ranked is SAR value. Two different units in one finding — the spine must keep them apart.

### The exception queue is large and complete

`RECOMMENDED_ACTION` covers all 140,113 rows with no gap (the 15 values sum exactly to the row
count), which is what WP7's `exception_list` layout ranks:

| Action | Location-SKUs | Stock value (SAR) |
|---|---|---|
| NON MOVING | 36,377 | 6,411,196 |
| OVERSTOCK | 29,932 | 26,887,690 |
| STOCK AVAILABLE | 19,037 | 10,131,473 |
| STOCK OUT - PLACE ORDER | 17,717 | 0 |
| IN STOCK BUT NO SALES | 9,007 | 852,303 |
| NA | 8,260 | 3,665,937 |
| NOT ACTIVE | 6,746 | 0 |
| STOCK OUT - AVAILABLE IN WAREHOUSE | 6,042 | 0 |
| ON THE VERGE OF STOCK OUT - PLACE ORDER | 2,566 | 733,478 |
| IN STOCK BUT NO TRANSFERS | 1,541 | 894,631 |
| NEW LISTED SKU | 1,042 | 753,171 |
| ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE | 848 | 82,605 |
| STOCK AVAILABLE - REORDER LEVEL UNKNOW | 798 | 252,180 |
| STOCK OUT - ORDER PLACED | 125 | 0 |
| ON THE VERGE OF STOCK OUT - ORDER PLACED | 75 | 166,976 |

Excess stock is **SAR 21,126,060 — 41.6% of all stock value.** Note this is the surplus portion
(`EXCESS_STOCK_VALUE`), not the SAR 26.9M full stock value of overstocked SKUs; BR-20 explicitly
warns against confusing them, and the two numbers are both present, so the report must label which
it means.

---

## 6. Q4 — Are ageing buckets pre-computed or derived? **PRE-COMPUTED. No date arithmetic needed.**

This removes the brief's harder branch for WP5 entirely. The model carries:

- `AGE` — 8 granular bands (`0-01` … `24+ MONTHS`)
- `NEW AGE` — 6 display bands, consolidating the first three ✓ BR-11
- `AGE_ABOVE_3/6/9/12/24` — five cumulative Y/N flags ✓ BR-14
- `PURCHASE_PERIOD` + `sortdate` — the batch label and its ordinal sort key ✓ BR-13
- `agingstock` — the aged value, with the division-sensitive threshold already applied

**The division-sensitive threshold (BR-16) is verified numerically**, which is the most useful
single result in this section:

| NEW AGE | Stock value | `agingstock` | Reading |
|---|---|---|---|
| 0-03 MONTHS | 31,578,194.16 | *null* | never aged ✓ |
| 03-06 MONTHS | 7,954,826.48 | *null* | never aged ✓ |
| 06-09 MONTHS | 4,720,840.48 | **547,530.08** | **partial — FMCG FOOD only** ✓ |
| 09-12 MONTHS | 2,721,538.94 | 2,721,538.94 | fully aged ✓ |
| 12-24 MONTHS | 3,068,609.18 | 3,068,609.18 | fully aged ✓ |
| 24+ MONTHS | 787,637.57 | 787,637.57 | fully aged ✓ |

The four aged figures sum to **7,125,315.77**, exactly the model's total `agingstock`. The 06-09
band being *partially* aged is the fingerprint of the FMCG-FOOD-at-6-months rule, confirmed from
the data alone.

`CANNOT BE DETERMINED` (BR-12) has **no rows in the current data** — the edge case is real in the
DAX but currently empty, so it must be handled without being assumed present.

The high-risk overlay (BR-17) is directly computable: 12-24 plus 24+ = **SAR 3,856,246.75**, of
which the 24+ tier alone is **SAR 787,637.57**.

Aged × non-moving (BR-19's highest-risk intersection) is also available and reconciles:

| non_moving_status | Stock value | Aged |
|---|---|---|
| YES | 5,995,662.52 | **2,760,784.20** |
| NO | 44,835,984.29 | 4,364,531.57 |
| total | 50,831,646.81 ✓ | 7,125,315.77 ✓ |

---

## 7. Q6 and Q7 — Cadence and audience

**Q6 — cadence.** The snapshot is dated 2026-08-12 and both models refresh together. `SSR TREND`
holds month-starts plus a mid-month point (2026-06-01, 07-01, 08-01, 08-12); `DAMAGE DATA` holds
four months (2026-05 → 2026-08, August partial at 302 rows against ~3–4.5k). A **daily** run is
viable — the data is current, unlike the sales model's 2.5-year-stale axis — but see §8: there is
no history to compare a daily run against, so novelty must come from state, not from a period.

**Q7 — audience and decisions.** The **buying team**, per both rulebooks. The decisions are named
explicitly in BR-31: initiate an internal transfer, place or expedite a purchase order, cancel or
defer an open order, mark down / promote / transfer excess, clear non-moving stock. This is a
worklist, which is why WP7's layout is an `exception_list` and not a hero verdict — and the
ageing report's BR-28 gives a fixed ranking order rather than asking for a rotation.

---

## 8. THE PLAN-CHANGING RESULT: there is no prior snapshot

**Every main-fact measure in both models exists at exactly one point in time.**

The brief's §1.6 table asserts that Ageing "Has a comparison? **Yes** — this period's distribution
vs last period's", and builds the whole ordering argument on it: Ageing first *because* its signed
change lets the existing ranking blend and period-anchored novelty work unchanged. **That is false
for this model.** With one snapshot there is no prior distribution, so:

- `SnapshotVsSnapshotSpine` (WP4 item 3) has **no baseline available**. It cannot be the spine that
  lets WP5 ship.
- WP5's stated core finding — "bucket-migration math: how much value moved rightward (ageing)
  versus leftward (cleared) between snapshots, reconciling to the total change" — **is not
  buildable.**
- Ageing therefore needs the **change-free ranking blend** and **state-based novelty** that the
  brief deferred to WP6.

**Crucially, this is not a blocker, because the business never asked for a comparison.** Both
rulebooks specify cross-sectional reports:

- Ageing BR-04: *"The report answers: how old is our stock, and which aged stock is also not
  selling? It does not answer: why stock is aging, or what to do about it."*
- Ageing BR-28 ranks findings by **risk tier then SAR value** — 24+ months first, then 12-24, then
  aged-and-non-moving. No period comparison anywhere.
- Inventory Management is entirely current-state-versus-policy.

So the reports are buildable as specified. What must change is the *order in which the kernel
capabilities are built*.

### Recommended revision to the work package order

| Brief | Revised | Why |
|---|---|---|
| WP4 = semi-additive + snapshot date + `SnapshotVsSnapshotSpine` | WP4 = semi-additive + snapshot date + **snapshot-vs-policy** spine | The vs-snapshot spine has no baseline; the vs-policy one has a rich, verified baseline available on the fact row |
| WP6 = change-free blend + state novelty (after Ageing ships) | **Move both into WP4/WP5** | Ageing cannot rank or rotate without them |
| WP5 = bucket migration between snapshots | WP5 = **bucket distribution + aged/non-moving intersection** | Matches BR-04/BR-17/BR-19/BR-28, and is what the data supports |

Ageing-first is still the right call, and §1.5's argument holds even more strongly: inventory
forces "ranking with no signed change" and "novelty as a state with a duration" into the open
immediately, rather than letting them be deferred.

**If a snapshot-over-snapshot comparison is wanted**, that is a Power BI change, not a code change
(brief Part 6.5): the model would need to retain history of the main fact, as `SSR TREND` already
does at section grain. Worth asking — but do not build a comparison against a single snapshot.

---

## 9. Verdict per report

| Report | Verdict | Conditions |
|---|---|---|
| **Stock Age Analysis** | **Buildable** | As a distribution report. Needs change-free ranking + state novelty earlier than planned. No comparison, no bucket migration. |
| **Inventory Management** | **Buildable** | As an exception queue against a verified policy band. Needs the BD sentinel handled (§10). |
| **Inventory chain (WP8)** | **Buildable, with a fix** | Chain memory must be chain-scoped independent of dataset (§2). |
| **Sales YoY** | Unaffected | Golden master byte-identical throughout WP1. |

Neither report is blocked on a model change. Neither takes the 1.10 fallback.

---

## 10. Traps found in the data that the rulebooks do not fully cover

These are the WP0 equivalent of the fixture `BLOCKER` checks — real, verified, and each one able to
produce a confident wrong answer.

1. **The BD sentinel is worse than documented, and unbounded above.** BR-11 says a SKU with stock
   but no sales gets `BD = 1000`. True — **22,784 rows (16.3%), SAR 2.55M**. But `max BD = 63,044`
   (≈172 years), so 1000 is *not* the ceiling. Reading BD as a number inflates the naive average
   from **187.3 to 326.5 — a 74% overstatement**. Any BD ranking or banding must exclude the
   sentinel *and* winsorize the tail, which is the R5 "never rank on raw percentage" lesson again.
2. **Ten divisions in the data, nine in both rulebooks.** `FOOTWEAR` (SAR 2,025,611.09, aged
   504,124.67) is absent from the documented list of nine. The ten sum exactly to the total, so it
   is real data, not a duplicate.
3. **An undocumented lead time.** `LEAD_DAYS` includes a **5-day** value (6 rows). BR-18's table
   lists only 7, 3, 2 and 1.
4. **A fifteenth recommended action, misspelled.** `STOCK AVAILABLE - REORDER LEVEL UNKNOW` (sic,
   798 rows, SAR 252,180) is not among BR-31's 14 states.
5. **A misspelled twin column.** `SKUSEGMENT` and `SKU_SEGEMENT` both exist and agree perfectly
   (SEG_A 16,158 / SEG_B 22,903 / SEG_C 29,514 / SEG_D 71,538). Harmless today, but a metadata scan
   could bind either, so pin the correctly spelled one.
6. **`DEPARTMENT` means Division.** BR-02 in both rulebooks. This collides head-on with
   `summary_roles.HIERARCHY_LEVELS`, where `division` is depth 10 and `department` is depth 20 —
   so an unaliased scan would place the top level at the wrong depth and find no division at all.
   Must be fixed by `summary_focus_role_aliases` config, not code. `DEPARTMENT` also appears on
   *both* `REP_SSR_SAG` and `LINK TABLE`, so the R5 mirrored-level collapse will be exercised.
7. **`Brand` is a hierarchy level the vocabulary lacks.** Both rulebooks specify Division > Section
   > Category > Brand > SKU. `HIERARCHY_LEVELS` has no `brand`.
8. **"Non-Moving" means two different things across the chain.** Ageing BR-18: zero sales since
   receipt, flagged from day one. Inventory Management BR-24: 30 consecutive days of zero sales with
   stock continuously available. The ageing rulebook flags the discrepancy itself. For WP8's pooled
   extraction this is a landmine — one word, two definitions, one narrative.
9. **The probe inherited the sales comparable population.** Both probes reported
   `comparable=4 excluded=1 source=business_rule_config` and recommended
   `["CFH014","CFH017","CFH018","CFH021"]` — that is the *sales* config's store list leaking in.
   The inventory models have **7 locations** including two warehouses. A real inventory config must
   set its own population, or drop the concept: like-for-like comparison is meaningless with one
   snapshot.
10. **CFH022 is not empty.** The ageing rulebook's open question 1 asks whether CFH022 shows "zero
    aging value". It does not — SAR 231,380.33 stock, **SAR 79,445.36 aged**. It is simply much
    smaller than the other six.
11. **`--deep` reported freshness as unmeasured.** Both probes printed "How up to date this
    dashboard is has not been measured, because that needs the thorough check" *despite* `--deep`
    being passed. The deep pass did run and produced `0/0 queries`, because diagnostics are built
    from a primary metric that never resolved. The message is misleading and should distinguish
    "not run" from "ran and produced nothing".

---

## 11. What the fixtures got right, and what to correct

`tests/fixtures/models/stock_snapshot.json` predicted the live behaviour exactly. Both probes
returned:

```
Metadata profile: primary=unresolved; fact=unresolved; entity=unresolved;
                  0 drill dimensions; 0 time dimensions
metadata profile caveat: No current+prior additive value family could be identified from metadata.
BLOCKING: ... A stock or inventory snapshot with only current balances cannot be used.
```

That is the total collapse the fixture pins — no primary bundle, so no fact table, so no dimension
walk, so zero dimensions. The fixture's `BLOCKER` checks are validated against reality.

Two corrections to make before WP4:

- **`stock_snapshot.json` gives its ageing fixture a prior snapshot measure.** The real models have
  none. Add a fixture variant with a **single** snapshot so the no-baseline path is tested, and keep
  `SSR TREND`'s four-date shape as the semi-additive positive control (4.03× is now a real,
  measured expectation, not a hypothetical).
- **Add the BD sentinel to a fixture.** A measure where 16% of rows hold a magic 1000 and the max is
  63,044 is a ranking hazard no current fixture covers.

---

## 12. Evidence

Probe output, artifacts and the four spike rounds were captured under the session scratchpad:
`probe_ageing.json`, `probe_im.json`, `artifacts_ageing/`, `artifacts_im/`,
`spike_semi_additive.py`, `spike_round2.py`, `spike_round3.py`, `spike_round4.py`. The probe
configs are *not* committed — they carry real dataset GUIDs and were built read-only for this
investigation.

Every figure quoted above came from a live `EVALUATE` on 2026-08-13 and is reproducible by
re-running the probe with the same dataset IDs.
