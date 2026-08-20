# Deferred: wiring the inventory reports into the insight feed (P5.3)

**Status: paused on purpose.** The inventory semantic model is being changed. This
document is the guide for picking the work back up once those changes land, and the
checklist for deciding whether they landed correctly.

Everything below was verified against the repo on 2026-08-18. Nothing here is
speculative about *our* code; the speculative part is the model, which is exactly why the
work is paused.

---

## Why this is paused rather than half-built

The two inventory reports hold **one snapshot each** - a single `UPDATED_ON` value - so
there is no prior state to difference against. Their comparison is stock vs **policy**, and
`SnapshotVsPolicySpine` already exists for it. What does not exist is any way to say "this
exception is new", "this one got worse", "this one cleared", because that needs **two
observations of the same item at different times**.

`src/kernel/state_novelty.py` is built and tested for exactly that, and it is the piece
that cannot be finished today: with one snapshot, every run sees `first_seen` forever.
Building the detectors now would mean testing them only against synthetic data and
discovering on the first real second-snapshot day whether the identity was right. The
identity is the part that is expensive to get wrong - a wrong `state_key` either
re-announces every exception daily or silently suppresses real ones.

---

## What must be true of the model before restarting

Check these in order. The first two are blocking; the rest change the design.

### 1. More than one snapshot is retained (BLOCKING)

```
EVALUATE ROW("distinct_asof", DISTINCTCOUNT('<fact>'[UPDATED_ON]))
```

This must return **> 1**, and the values must be different calendar days. One value means
nothing below is buildable. Two or more means the whole package unblocks.

Also confirm snapshots are *retained*, not *replaced*: run it again a day later and check
the count went up. A model that overwrites `UPDATED_ON` in place still reads as one
snapshot no matter how long you wait.

### 2. An item keeps a stable identity across snapshots (BLOCKING)

The novelty key is only as good as the identity underneath it. Confirm the location-SKU
key is the same string on both snapshot dates for an item that did not change:

```
EVALUATE
TOPN(20,
  SUMMARIZECOLUMNS('<fact>'[LOC_CODE], '<fact>'[SKU], '<fact>'[UPDATED_ON],
    "cover", [Days Cover]))
```

If the key is a surrogate that is regenerated per load, state novelty cannot work and the
model needs a durable business key first. This is the single most likely thing to be wrong.

### 3. The policy band is still on the row

`SnapshotVsPolicySpine` reads `EXCESS_THRESHOLD_DAYS` and `Reorder_Level` from the fact
row. If the model change moves policy to a separate table, the spine needs a relationship
path rather than a column read, and `band_of` is the only place that changes.

### 4. The `COVER_SENTINEL = 1000` convention still holds

A cover of 1000 means "no velocity", not "well stocked for three years". It is handled in
`cover_of`. If the model change replaces the sentinel with a real NULL, that is an
improvement - but `families.COVER_SENTINEL` must be updated or a genuine 1000-day cover
will be read as unmeasurable.

---

## The work, once those pass

### Step 1 - state identity

Write `state_components()` for each report and pin it in a replay before anything else.

* **Duration must be excluded from the key.** If it is included, every day mints a new
  identity and nothing is ever suppressed. `state_novelty` computes duration separately
  from `first_seen`.
* Include: dataset, report, location, SKU, and the **kind** of exception
  (`overstock`, `stock_out`, `non_moving`, `aged`). Exclude: the measured distance, the
  exposure, the date, and anything that moves while the exception persists.
* `insight_memory.story_key` already includes the dataset, which is what keeps a finding in
  the ageing model distinct from one in the stock-health model. Those are genuinely
  different findings even for the same SKU.

### Step 2 - wire `state_novelty.judge`

```python
verdict = state_novelty.judge(stored_record, current_state, observed_at=as_of)
```

`judge` returns a `StateVerdict` whose `kind` is one of
`first_seen | onset | cleared | changed | escalated | milestone | unchanged`. Report on
everything except `unchanged`. Note that **`cleared` is a reportable event** - a report
that only ever announces problems and never closes one is not trusted for long.

Durations are counted from observation dates, not calendar days, so a weekend with no run
does not reset the clock.

### Step 3 - the exit criterion

Two consecutive synthetic runs must produce a sensible
**appear → persist → clear** sequence with no duplicate reporting. Concretely:

| Run | Item state | Expected verdict | Reported? |
|---|---|---|---|
| 1 | overstock, 9 days over | `first_seen` | yes |
| 2 (same) | overstock, 9 days over | `unchanged` | **no** |
| 3 | overstock, 31 days over | `escalated` | yes |
| 4 | overstock, day 7 in state | `milestone` | yes |
| 5 | within band | `cleared` | yes |
| 6 | within band | `unchanged` | **no** |

Mutation-test it: make `judge` always return `report=True` and confirm the "no duplicate
reporting" checks fail with a precise message.

### Step 4 - publishing

This is the part that needs **you**, not the model. There is currently **no inventory
config anywhere** - `config/*invent*` is empty. To publish, each report needs:

| Setting | Why it matters |
|---|---|
| `report_id` | `stock_age_analysis` / `inventory_management`. Stamped on every card. |
| `ai_content_client` | The client container the app reads. Is inventory `cityflower` or its own? |
| `ai_content_report_ids` | The Power BI report GUID(s). **A report id is not a dataset id** - resolve with `GET /v1.0/myorg/groups/{ws}/reports/{id}`. |
| `azure_blob_prefix` | **Load-bearing.** Sales YoY uses an empty prefix in the `insightgen` container. Two reports sharing an empty prefix overwrite each other's `api/*.json`. |
| `chain_id` | `inventory`, so both reports share one insight memory via `kernel.scoping.chain_dir`. |

Once those exist, publishing reuses what P5.4 already built:
`ai_content_publisher.publish_kpi_feed(...)` is the single shared implementation of the
report-aware merge. Do **not** write a second one - the thing a copy would drift on is
precisely the report-awareness that stops one report erasing another's cards.

---

## What is already done and waiting

These are built, tested and need no further work:

* **`SnapshotVsPolicySpine`** - policy band in days, exposure in SAR, declared separately
  because collapsing them prints "SAR 9". `baseline_missing` for an item with no policy.
* **`kernel/state_novelty.py`** - `judge`, `advance`, `state_key`, milestones at
  7/14/30/60/90 days, escalation thresholds on distance and exposure.
* **`kernel/chain.py`** - `tag_evidence`, `fair_share`, `attribution`, sequential `run`.
  `fair_share` guarantees a quiet report a slot **before** truncation.
* **`kernel/scoping.chain_dir`** - chain memory is deliberately *not* nested under a
  dataset, because the two inventory reports live in different models and the one chain
  must share one store.
* **`scripts/run_inventory_chain.py`** - already pools both reports into
  `outputs_inventory_chain/insight_inventory_chain.{md,json}`. Local only, not published.
* **The whole P5.1/P5.4 feed layer** - `reportId` on the card, collision-free stable ids,
  report-aware merge, `fair_share` cap at 10. Inventory plugs into it by supplying cards.

---

## Two traps specific to inventory

**Aged and non-moving must never be summed.** They overlap. On the live data the overlap -
aged **and** non-moving, the write-off candidate - is **SAR 2.76M**, and adding the two
totals double-counts exactly that. `replay_ageing.py` and `audit_ageing.py` both assert the
naive sum exceeds the true union by that amount. Any new signal that combines the two must
respect it.

**Opportunity Loss is scoped, and the unscoped number is 6.4x larger.** BR-16 restricts it
to critical SKUs at stores (SEG_A/B, LOCAL, `loc_type = SH`): **SAR 45,944 scoped against
SAR 292,771 unscoped**. Both numbers are in the model, so publishing the wrong one is one
filter away. A signal quoting opportunity loss must quote the scoped figure and say so.

---

## Restart checklist

1. Run the two blocking queries above. If either fails, stop - the model is not ready.
2. `python scripts/replay_all.py` and `python scripts/golden_master.py` must be green
   before you change anything, so a later failure is attributable.
3. Build `state_components()` and pin it in a replay first.
4. Wire `judge`, prove the appear → persist → clear sequence, mutation-test it.
5. Ask for the four config values in Step 4 and write `config/inventory/`.
6. Publish through `publish_kpi_feed` - do not write a second merge.
7. Render the pages and look at them. Layout faults are invisible to string assertions:
   `chrome --headless=new --disable-gpu --no-sandbox --screenshot=out.png --window-size=1500,2400 file:///<abs path>`
