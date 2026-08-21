# Inventory Management daily pipeline — findings

**Status:** environment resolved and the live scan accepted, 2026-08-21. This document
records what was measured, because two of the findings contradict the brief that
commissioned the work and one of them changes the design.

Supersedes `docs/inventory-daily-summary-prompt.md` on the dataset question, and
`docs/domain-verticals-findings.md` §1 on which model the inventory reports mean.

---

## 1. The dataset discrepancy: two clients, not a stale config

`docs/inventory-daily-summary-prompt.md` states that `config/chains/inventory.json` is
stale because it names datasets that are not the ones the reference design was built
from. Both halves of that are true; the conclusion is not. **The chain config is
correct.** It names a different *client*.

| | **CITYFLOWER** `6d383900` | **SB Mart** `2829a4af` |
|---|---|---|
| Inventory Management | `64eefa4b` — the chain config | `16d47b06` — the reference design |
| Stock Age Analysis | `84212fd9` — the chain config | `3cd81c72` |
| IM tables | 23 | 30 |
| `_HEALTH SCORE MEASURES`, `FCT SKU HEALTH`, `LOC_CATEGORY_HEALTH` | **absent** | present |
| `[Inventory Health Score]` | query fails, HTTP 400 | 43.54 |
| IM fact rows | 139,839 | 139,732 |
| `UPDATED_ON` on 2026-08-21 | 2026-08-20 | 2026-08-19 |
| Divisions | 10 | 4 |

Both models hold the same estate a day apart — the Recommended Action counts agree within
about 1% (`NON MOVING` 34,622 vs 34,594; `OVERSTOCK` 29,902 vs 29,774) — so these are
parallel environments for one business, not two businesses.

**The decision, and why.** The approved reference is built around the Inventory Health
Score as its story spine, and that measure exists only on SB Mart, so the reference is
unbuildable against CityFlower. SB Mart is also a live, provisioned client: it has its own
blob container, four users in `agent-config/client_mapping.json`, and **two reports already
publishing daily** (YoY Sales Performance and Target Tracker, both at ~05:35–06:00 UTC).
Its configs live as container-job secrets, which is why no `config/sbmart/` exists in the
repo and why its absence is not evidence of anything.

`config/inventory/config.json` therefore targets SB Mart. The chain config is left alone:
it correctly describes CityFlower, and rewriting it would break `replay_inventory_chain.py`
and lose a working record of that environment.

**What SB Mart's conventions already are**, followed by the new config rather than invented:

- `azure_blob_prefix` is `sb-mart/<report-slug>` — the live prefixes are `sb-mart/sales-yoy`
  and `sb-mart/target-tracker`, so inventory takes `sb-mart/inventory-management`. A bare
  `inventory` prefix would sit at the `insightgen` container root beside CityFlower's own
  payloads.
- `ai_content_client` is `sb-mart`.
- **`ai_content_multi_report_feed` is already ON for this client.** Its published cards
  carry `reportId` (`sales_yoy`, `target_tracker`) and hashed `stable_card_id`s rather than
  `1..N`, so the app has already shipped the multi-report contract here. That materially
  de-risks step 6 — the concern about the flag being off applies to CityFlower, not to this
  client.

**Consequence to accept, not work around.** Every committed inventory artifact, replay and
golden snapshot is pinned to CityFlower's scan (`outputs_stock_health/`, as at 2026-08-12,
140,113 Loc-SKUs). Those stay as they are: they are a valid fixture for the *shape* tests,
and re-recording them against SB Mart would be a deliberate act with its own review, not a
side effect of this work.

---

## 2. The as-at stamp does not identify a business position

This is the finding that changes the design, and it was measured rather than reasoned.

On 2026-08-21 the SB Mart model still stamped `UPDATED_ON = 2026-08-19` — exactly the stamp
the approved reference design carries — while reading materially different data:

| | reference, 19 Aug | live, 21 Aug | |
|---|---|---|---|
| scored Loc-SKUs (`FCT SKU HEALTH`) | 120,897 | **139,732** | +15.6% |
| Inventory Health Score | 58.53 | **43.54** | **−15.0 points** |

Two separate things had happened under one unchanged stamp:

1. **Warehouse scoring landed.** `FCT SKU HEALTH` restricted to stores returns exactly
   120,897 rows — the reference's own figure. The README's note that "warehouses are not
   scored… warehouse scoring is planned" is now out of date: it has shipped, and the scored
   population grew from stores-only to every Location. Worth about 5.3 of the 15 points.
2. **The stores-only position itself deteriorated**, 58.53 → 48.84. The remaining ~9.7
   points are a real change in the underlying data, still stamped 2026-08-19.

The dataset had refreshed six times between the two readings (once scheduled at 05:01 on
21 Aug, five on-demand on 20 Aug).

**So the archive keys on the run date, never on the as-at stamp.** Keying on the stamp
would have written both of those positions to the same filename, silently discarding one;
a later comparison would then have reported the difference between two loads of "the same
day" as a day of trading. `archive.compare_window` additionally refuses to state any
movement unless the stamp actually advanced between two kept files, and returns which of
four reasons blocked it so the page can print it. `AS_AT_UNCHANGED` is not a hypothetical
guard — it is this exact case.

---

## 3. Opportunity Loss: three figures, one publishable

Measured live, all three from the same model:

| | |
|---|---|
| `OPP_LOSS_DUE_TO_STOCKOUT`, unscoped | 313,038 |
| the model's own `OPPORTUNITY LOSS` column | 59,051 |
| BR-16's scope applied to the first | **49,076** |

BR-16 names `OPP_LOSS_DUE_TO_STOCKOUT` and states three hard limits — critical segments
(SEG_A/B), local procurement, stores only. Applying all three gives the smallest figure and
that is what the report publishes. The model's own pre-scoped column is 20% higher, so it
does not apply all three; the scan returns it as `opp_loss_model_column` purely so a caveat
can name the gap rather than leave a reader to find two different numbers for one measure.

Publishing the unscoped figure would overstate the measure 6.4-fold — the same ratio the
CityFlower model showed (292,771 against 45,944).

---

## 4. BR-31's own count is wrong, and one urgent state has no data

- **BR-31 says "all 14 states"; its table lists 15.** The heading and the table disagree in
  the rulebook itself.
- **Live data holds 15 distinct `RECOMMENDED_ACTION` values**, of which 14 match BR-31's
  table and one — `STOCK AVAILABLE - REORDER LEVEL UNKNOW` (truncated at source, no final
  `N`) — is not documented in BR-31 at all.
- **`NON MOVING - ORDER PLACED` has zero rows on both models.** It is one of the two
  double-warning states BR-31 says to report first. `stock_health.absent_states` already
  surfaces this as `states_absent_urgent` and the report carries a caveat, which is the
  right handling: an empty double-warning state is a question for whoever owns the source
  system, not a clean bill of health.

**Consequence for the terminology check.** "All fourteen BR-31 state names present" can only
mean present as *vocabulary* — in the guidance table and the legend — never as queue rows,
because one of them cannot have any. The check asserts the names appear, not that the states
have data.

---

## 5. Smaller live corrections to the reference README

- The table the README calls `P90 CATEGORY STORE` is now named **`P90 CATEGORY LOCATION`**.
- SB Mart's Inventory Management model **embeds the entire ageing fact** (`REP_SSR_SAG`,
  174,863 rows — the same count as the standalone SB Mart ageing dataset), alongside
  `SAG AGE BY SKU STORE`. One scan could serve both inventory reports on this client, which
  is worth knowing before the Ageing report is brought onto the same footing.
- SB Mart has **4 Divisions and 20 Sections**, against CityFlower's 10 Divisions. Anything
  that assumes ten rows will render wrongly here.

---

## 6. What was built against these findings

| Piece | Where |
|---|---|
| Per-report config and rulebook | `config/inventory/config.json`, `config/inventory/summary_business_rules.md` |
| Eight catalogued config keys | `src/config_schema.py` |
| Live scan, 11 bounded queries | `stock_health.scan` |
| Run-date-keyed snapshot archive | `src/domains/inventory/archive.py` |
| Daily runner | `scripts/run_inventory.py` |
| Offline proof | `scripts/replay_inventory_scan.py` |

`currency` is now threaded through `stock_health.build(scan, currency=...)`, defaulting to
the value the report shipped with so every committed artifact still reproduces
byte-for-byte, and set from `inventory_currency` by the runner.

**First live run, 2026-08-21** against SB Mart, as at 2026-08-19: 11/25 queries, all three
reconciliation checks pass, Stock Value USD 13,966,417, Excess Stock USD 5,900,413 (42.2%),
Pending Orders USD 850,218, Opportunity Loss USD 49,076/day scoped, 139,732 Loc-SKUs
covering 45,864 SKUs at 7 Locations, and `NON MOVING - ORDER PLACED` correctly reported as
an urgent state with no rows.
