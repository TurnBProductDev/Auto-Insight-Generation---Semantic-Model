# Cost and AI-Tiering: implementation brief

**Status:** plan of record, not yet started.
**Written:** 2026-09-08.
**Read this whole file before touching code.** It is written to be handed to a
fresh session that has none of the conversation that produced it.

---

## 0. How to use this document

This is a set of instructions, not a discussion. Work the phases **in order**.
Each phase has an *exit criterion*; do not begin a phase until the previous
phase's exit criterion is met. That rule is copied deliberately from
`docs/domain-verticals-implementation-brief.md`, where it worked.

Every phase's exit criterion includes:

```bash
cd powerbi-summary-agent
python scripts/replay_all.py --with-golden
```

If that is not clean and byte-identical, the phase is not done. The golden
master exists to prove a refactor changed no arithmetic; this whole brief is a
refactor, so it is the primary safety net throughout.

---

## 1. What you need to know before starting

### The repo in one paragraph

This repo turns Power BI dashboards into written daily analysis. Six reports
ship today: Sales Year-on-Year, Target Tracker, Stock Age Analysis, Inventory
Management, SKU Overview, Daily Sales. Each runs nightly against a client's
semantic model, asks it questions in DAX, works out what is interesting, writes
it in business English, and publishes an HTML page the client's app reads.
`CLAUDE.md` (identical twin `AGENTS.md`) is the engineering logbook and is
authoritative on everything not covered here.

### The two routes that exist today

**Route A — the LangGraph pipeline.** One report uses it: Sales YoY. Entry is
`python -m src.main`. The flowchart is `src/graph.py`: 39 nodes, a fork into two
concurrent branches (a descriptive *summary* branch and an investigative
*insight* branch), and a join barrier at `save_outputs`.

**Route B — standalone runners.** The other five: `scripts/run_target_tracker.py`,
`run_inventory.py`, `run_ageing.py`, `run_sku_overview.py`, `run_daily_sales.py`.
Selected in a container by the `AGENT_RUNNER` env var
(`src/container_entrypoint.py`). None of them imports LangGraph. They share the
token cache, the executor, the validators, `src/kernel/`, and the page renderer.

### Why the split exists, and why it is wrong

Route A was built first, for Sales YoY, and its machinery assumes a
**year-on-year comparison**: the focus rotation, the memory/novelty gate and the
insight branch all exist to answer "which of last year's comparisons should I
talk about today?".

When Target Tracker arrived, its model held 2026 only — no prior year at all,
about 30 measures fail at query time — so it was built *alongside* the pipeline
rather than into it. Inventory did the same, for the same reason (a stock
position has no prior period).

So the dividing line today is **"does this report have a prior year?"**. That is
a fact about the *data*. It should decide which comparison you make. It should
**not** decide how much AI the report is allowed. Right now it does, and the
result is upside-down:

- Sales YoY — the simplest report in business terms — gets a full investigative
  agent, follow-up probes and free-form prose.
- Inventory Management — comparably large in code (14,525 lines in
  `src/domains/inventory/` versus 15,881 for `graph.py` plus all 40 agents) and
  far richer in business rules (15 action states, a six-dimension health score,
  a policy band in days against exposure in money, two value bases, snapshot
  archiving) — ships with `inventory_llm_authoring_enabled = False`. Entirely
  deterministic prose. No investigation.

### What a run costs — measured, not estimated

Four live runs are recorded in `outputs_bench_results/bench_results.json`
(a 2x2: cold/warm cache against baseline/optimized config). Per-node spend is in
each run's `token_usage.json`.

| Cell | LLM calls | Seconds | USD |
|---|---|---|---|
| A baseline cold | 24 | 379 | 1.33 |
| B baseline warm | 26 | 324 | **1.54** |
| D optimized cold | 22 | 326 | 1.20 |
| C optimized warm | **14** | **216** | **0.68** |

At $1.54, six reports per client per day is roughly **$3,370 per client per
year**; twenty clients is about **$67,000 a year**. That is the problem.

Where the optimized run's remaining money goes — two nodes are 74% of it:

| Node | USD | Share | Shape |
|---|---|---|---|
| `insight_investigator` | 0.287 | 42% | 6 calls, 203k input tokens |
| `insight_synthesizer` | 0.216 | 32% | 3 calls, 10k **output** tokens |
| `fresh_summary_generator` | 0.061 | 9% | |
| `insight_signal_detector` | 0.053 | 8% | already on `gpt-5.4-mini` |
| `summary_dashboard_builder` | 0.046 | 7% | |
| `api_payloads` | 0.015 | 2% | |

And the root cause of the per-call price: **the prompts are enormous**.
`model_metadata.json` is 82 KB. `insight_stat_candidates.json` is 124 KB.
`insight_clean_data.json` is 128 KB. The signal detector sends about **65,000
input tokens to get 735 tokens back** — a 90:1 ratio. You are paying to re-read
the model description and the full scan results on every call.

### The state of the cost tooling — READ THIS, it changes Phase 0

Three modules already exist that between them produced the $1.54 -> $0.68
result. **All three are untracked (never committed) and have no replay test:**

```
?? powerbi-summary-agent/src/tools/plan_cache.py
?? powerbi-summary-agent/src/tools/escalation.py
?? powerbi-summary-agent/src/tools/token_usage.py
?? powerbi-summary-agent/config/bench/
```

They *are* fully wired into the graph — `plan_cache.load/save` is called from
`report_understanding.py`, `dax_planner.py` and `dax_generator.py`, with
`record_execution` in `graph.py`; `escalation.decide` is called from
`insight_novelty_filter.py` and read by `insight_signal_detector.py`;
`token_usage` attaches a recorder inside `llm.get_llm`. And all three are off by
default, so the committed behaviour is unchanged.

But untested, uncommitted code is not shippable, and this brief's whole first
phase depends on them. **Do not skip to enabling the flags.**

What each does, plainly:

- **`plan_cache.py`** — three LLM steps (`report_understanding`, `dax_planner`,
  `dax_generator`) read the model's *structure*, not today's rows, so they
  produce the same answer every morning until the schema changes. This stores
  and reuses that. Keyed on dataset, report, the model's shape, the business
  rules, the prompt files and a version constant. A cached plan is **still**
  put through `dax_validator` and `scope_validator`, and is dropped when its
  queries stop executing. This is the 12-of-26-calls saving.
- **`escalation.py`** — budgets are fixed numbers in config today, so a quiet
  Tuesday costs the same as a dramatic Monday. The pipeline already knows how
  eventful the day was before it spends anything (the stat detector counted
  everything; the novelty filter removed what was already reported). This turns
  that count into the budget: *quiet* buys no investigation, *ordinary* a
  reduced one, *eventful* the configured one. It only ever **lowers** a budget
  (`min()` against config), and the descriptive report still publishes in full.
- **`token_usage.py`** — records per-call tokens and USD to `token_usage.json`
  beside the other artifacts, labelled by calling module. It can never break a
  run (every entry point swallows its own exceptions) and never holds model
  output, only integers.

---

## 2. The reframe — the idea the whole plan rests on

Today there is one dial, and it decides everything:

```
"Does this report have a prior year?"
   yes -> LangGraph, full AI, $1.54/day
   no  -> standalone script, ~no AI
```

There should be two dials that move independently:

**Dial A — what am I comparing against?** A fact about the data. Already solved:
`src/kernel/spine.py` names it (year-on-year, versus target, versus policy,
versus its own normal band). Nothing else should depend on this.

**Dial B — how much thinking do I buy today?** A business decision. Must be free
to vary per report, per client, and **per day**.

Dial B is currently welded to Dial A. Unwelding them is the job.

### The three tiers

**Tier 0 — Deterministic.** Code writes every sentence. $0. What Ageing,
Inventory and Daily Sales do today.

**Tier 1 — Narrated.** Code owns the page structure completely; the model fills
a fixed set of named prose slots; a deterministic validator checks every claim
against the numbers. Target Tracker already works exactly this way — four slots
(`headline`, `narrative`, `today_note`, `month_note`), and it cannot add a
section, drop a period, choose a chart or reorder the page. Target: **$0.05-0.10**.

**Tier 2 — Investigated.** Tier 1 plus: choose which findings matter, ask the
data follow-up questions, write a "why" narrative. Today $0.35-0.68; target half.

**The key move: Tier 2 is not a property of a report. It is bought per-day,
per-report, when the day earns it.** That is exactly what `escalation.py` already
implements.

---

## 3. Ground rules that apply to every phase

These are the repo's existing non-negotiables. Breaking one silently produces a
report that looks right and is wrong.

1. **Off by default.** Every new setting's *code* default reproduces today's
   behaviour exactly. A config that predates your change must behave identically.
   This is how `summary_r4_enabled`, `summary_r6_enabled` and
   `plan_cache_enabled` were all shipped.
2. **`src/config_schema.py` is the single catalogue.** Every new key goes there
   with a type, a default, a plain `label`, plain `help` (what happens, and what
   happens if it is wrong), a `detail` for the engineering note, and a `tier`
   (`essential`/`standard`/`expert`). `scripts/replay_config_schema.py` fails if
   the catalogue and the code disagree. Never hand-edit a default into `main.py`.
3. **The kernel never imports from domains.** `src/kernel/` is domain-agnostic;
   the dependency runs one way.
4. **Never touch the concurrency contract.** The fork, the four conditional
   routers and the joined-edge barrier into `save_outputs` are explicit code, not
   data. An ad-hoc edge into `save_outputs` can fire it twice. `logs`/`errors`
   are reducer-backed: return only the current node's delta.
5. **A cheaper model is allowed only where a deterministic gate catches it.**
   DAX generation is validated; prose is validated by `summary_validation` /
   the per-report authors. Do not route a node to a cheaper model unless
   something downstream would reject a worse answer.
6. **Never make a saving by weakening a validator.** If a change makes a
   validator pass more often, that is a regression, not a win.
7. **Every new module gets a `scripts/replay_*.py`.** `replay_all.py` finds them
   by glob so a new one joins the gate automatically; raise `MIN_EXPECTED`
   (currently 30) when you add one.
8. **Measure, do not assume.** Every claim in this brief came from a file in the
   repo. Hold your own changes to that standard: re-run the benchmark, do not
   estimate.

---

## 4. Phase 0 — Land and switch on what already exists

**Goal:** $1.54 -> $0.68 per run, with test coverage. No new features.

### 0.1 Review the three untracked modules

Read `src/tools/plan_cache.py`, `escalation.py`, `token_usage.py` in full. They
are complete and documented, but nobody has reviewed them. Look specifically at:

- `plan_cache`: what is in the cache key, and what invalidates it. Confirm
  values (today's data) are **not** in the key and the model's shape **is**.
- `escalation`: confirm every budget is floored with `min()` against config, so
  enabling it can never *increase* spend.
- `token_usage`: confirm every entry point swallows its own exceptions.

### 0.2 Write the missing replays

Three new files, offline, no auth and no LLM:

**`scripts/replay_plan_cache.py`** must prove:
- a hit returns the stored plan and makes no LLM call;
- changing a table/column/measure name **misses** (this is the invalidation
  that matters — a renamed column makes yesterday's DAX wrong);
- changing a *value* still **hits** (data changes daily; keying on it would
  make the cache useless);
- editing a business rule or a prompt file misses;
- bumping `PLAN_CACHE_VERSION` misses everything;
- a cached plan still goes through `dax_validator` and `scope_validator`
  unchanged — assert this explicitly, it is the safety property;
- `record_execution` drops the entry when the success rate falls below the
  floor, and the age limit expires it regardless.

**`scripts/replay_escalation.py`** must prove:
- 0 eligible findings -> quiet -> zero investigation budget;
- 1-5 -> ordinary -> reduced;
- 6+ -> eventful -> the configured budget, unchanged;
- **budgets are never raised above config** — the load-bearing guarantee. Test
  it with a config smaller than a tier's number;
- the materiality floor counts a candidate carrying **no** score rather than
  dropping it (discarding unknowns would let the gate silence a story it merely
  could not measure);
- the summary branch is untouched on a quiet day.

**`scripts/replay_token_usage.py`** must prove:
- a raised exception inside the recorder does not propagate;
- cached tokens are recorded separately from uncached (they bill at a tenth; a
  total that folds them together cannot be priced);
- the dumped record holds no model output;
- the calling-module label is correct.

Raise `MIN_EXPECTED` in `scripts/replay_all.py` from 30 to 33.

### 0.3 Commit

One commit per module plus its replay, following the repo's message style (say
what changed and why, in the imperative, naming the defect it closes). Include
`config/bench/`. Add `outputs_bench_*/` to `.gitignore` if not already covered —
they are run artifacts, not source. Keep `bench_results.json` and the four
`token_usage.json` files somewhere durable; they are the baseline every later
phase measures against. Suggest `tests/bench/baseline_2026-09.json`.

### 0.4 Enable, one client at a time

Add to `config/sbmart-yoy/config.json` first (it is the only pipeline report):

```json
"plan_cache_enabled": true,
"plan_cache_folder": "outputs/.runtime/plan_cache",
"plan_cache_max_age_days": 7,
"adaptive_investigation_enabled": true,
"adaptive_investigation_min_score": 0.0,
"node_model_overrides": { "insight_signal_detector": "gpt-5.4-mini" }
```

Run live twice — the first run is cold (populates the cache), the second is
warm. Compare `token_usage.json` against the benchmark. Then run
`python scripts/audit_summary_dashboard.py <output_dir>` — the artifact auditor,
which is what catches a saving that quietly broke a number.

**Two honest caveats to state in the commit message:** the saving is a *warm-run*
saving (cold is $1.20, and a schema change forces a re-plan), and on genuinely
eventful days adaptive investigation saves nothing, which is correct behaviour.

### 0.5 Watch for a week

`token_usage.json` lands in every output folder. Confirm the cache is hitting,
the escalation tier looks sane against the day's news, and the pages did not get
worse. Only then roll to other configs.

**Exit criterion:** `replay_all.py --with-golden` clean; three new replays
passing; two live runs at or below $0.70 warm; the audit clean.

---

## 5. Phase 1 — Cut the context

**Goal:** $0.68 -> ~$0.32. No architectural change. This is the highest
value-per-hour work in the brief because the 90:1 input-to-output ratio is pure
waste.

### 1.1 Stop sending the scan results to the signal detector

`src/agents/insight_signal_detector.py` builds:

```python
context = {
    "report_understanding": understanding,
    "stat_candidates": eligible,
    "scan_results": clean,        # <- this is insight_clean_data, ~128 KB
}
```

The candidates **already carry** their computed facts — `impact_value`,
`impact_share`, `score`, `segment`, the structured `recent_week` payload. The
node's job is to *select and merge* from candidates, and in memory mode binding
is exact-`candidate_id`-only, so it cannot reference a raw row anyway.

Remove `scan_results`, or reduce it to a small named summary. Then verify:
`replay_all.py` clean, and a live run produces the same signals. If signal
quality drops, put back the *smallest* thing that restores it and record what
that was — do not restore the whole blob.

Expected: roughly 65k -> 15k input tokens on that call.

### 1.2 Give each node the narrowest model context that works

`src/utils/model_context.py::llm_model_context` returns the **full** structural
view — every column with its details, every measure, every relationship — and
four nodes call it: `report_understanding`, `dax_planner`, `dax_generator`,
`insight_investigator`.

`dax_generator` writes one query for one intent. It does not need every column in
the model. Add an optional narrowing parameter (default: today's full view, so
nothing changes unless a caller opts in), then opt `dax_generator` in.

**Be careful here.** The validator rejects any table or column not in metadata,
so an over-narrowed context makes the generator write DAX that fails validation
and burns a repair round — spending *more*. Move in one step, measure, and keep
the repair-rate in view. If repairs rise, widen back.

### 1.3 Make the prompt prefix stable

Cached input tokens bill at a tenth. The optimized run already caches 176k of
383k. Ordering the message so the unchanging parts come **first** (global rules,
business rules, task prompt, model schema) and the variable parts **last**
(today's candidates, today's rows) should push that well past half.

This is a pure reordering — no content change — so `replay_all.py` must stay
byte-identical. Any diff means you changed content, not order.

### 1.4 Stop the investigator re-sending the full brief every round

`insight_investigator` is 6 calls at ~34k input tokens each, and much of that is
the same brief repeated. Send the brief once and let subsequent rounds carry only
the new result plus a short running state. Combined with 1.3 this is the single
biggest line item.

Do not reduce the *number* of probes here — that is `escalation.py`'s job, and it
is already handled by day. This step is about not paying twice for the same text.

### 1.5 Try the synthesizer on a cheaper model

`insight_synthesizer` is the biggest **output** spender (10k completion tokens).
It writes prose, and prose is what the reader sees, so ground rule 5 applies:
only do this because `summary_validation` and the synthesizer's own hedged-
language rules already reject ungrounded output.

Add `"insight_synthesizer": "gpt-5.4-mini"` to `node_model_overrides` and read
the resulting report **as a document**, side by side with the flagship version.
This is a judgement call, not a test. If the writing is worse, revert and say so
in the commit — a recorded negative result is worth keeping.

**Exit criterion:** `replay_all.py --with-golden` clean; a warm live run at or
below $0.35; the artifact auditor clean; the published pages reviewed by eye and
no worse.

---

## 6. Phase 2 — One narrator for all six reports

**Goal:** make Tier 1 something you can switch on for *any* report in one line.

There are currently **three** implementations of "the model fills prose slots and
code validates them":

- `src/agents/fresh_summary_generator.py` (+ `tools/summary_validation.py`)
- `src/domains/sales/target_tracker_author.py`
- `src/domains/inventory/stock_health_author.py`

They have already drifted. Each has its own banned-vocabulary list, its own
figure-grounding check, its own repair loop, its own fallback. The repo has been
here before: the two measure-family vocabularies drifted and the fix was to put
them side by side in one file and *pin the divergence*, because merging them
would have changed live behaviour.

**Apply the same discipline. Do not blind-merge.**

### 2.1 Extract the shape, not the rules

Create `src/kernel/narrate.py` owning only what is genuinely common:

- the slot contract (named slots in, filled slots out — the model can never add
  a section, drop one, or reorder);
- the call-validate-repair-once-then-fallback loop;
- figure grounding: every number in the prose must exist in the page model and
  be rounded to at most `MAX_QUOTED_DECIMALS`;
- the shared bans: emojis, placeholders, forecasting language, asserted cause;
- the guarantee that **the deterministic fallback passes the same validator**,
  so strict validation can never dead-end.

Each report keeps its **own** rules module — its own banned vocabulary, its own
assertions. Those are business rules, and they genuinely differ. `narrate.py`
takes them as an argument.

### 2.2 Migrate one report at a time

Order: Target Tracker (smallest, four slots, already the right shape), then Stock
Health, then `fresh_summary_generator` last (it is the biggest and the only one
whose output is under golden master).

After each migration, `replay_all.py --with-golden` must be byte-identical. If it
is not, you moved a rule, not just the shape — put the rule back.

### 2.3 Pin the divergence

Add `scripts/replay_narrate.py` asserting that each report's rule set is still
distinct where it must be — the way `replay_domain_assembly.py` pins the family
divergence, so the differences cannot be quietly "tidied" into a behaviour change.

**Exit criterion:** all three reports on `narrate.py`; golden master byte-identical;
`replay_narrate.py` in the gate; `MIN_EXPECTED` raised.

---

## 7. Phase 3 — Unweld the dials

**Goal:** any report can be at any tier, independent of its spine.

### 3.1 Make the tier explicit

Add to `config_schema.py`:

```
report_ai_tier : string, default "deterministic"   # deterministic | narrated | investigated
```

Default `"deterministic"` so nothing changes on first read. Then set each live
config to what it does **today** — `sales_yoy: investigated`,
`target_tracker: narrated`, the rest `deterministic` — and prove with the golden
master that naming the current state changed nothing.

Then retire the per-report `*_llm_authoring_enabled` flags in favour of it,
keeping them as accepted aliases so existing configs keep working.

### 3.2 Give Inventory Management Tier 2

This is the payoff. Inventory Management is the most complex report in the system
and has no investigation today. The pieces already exist:

- `src/domains/inventory/snapshot_investigator.py` — the investigator
- `src/domains/inventory/stock_health_signals.py` — ranked signals
- `src/kernel/state_novelty.py` — novelty anchored on a **state**, not a period,
  which is exactly right for a stock exception that has no period
- `escalation.py` — the by-day budget

Wire them together in `scripts/run_inventory.py` behind `report_ai_tier`.
**It does not join LangGraph.** Route B stays Route B; it just gets a bigger
Dial B.

Two things to respect that the pipeline learned the hard way:

- Every signal must carry an explicit `comparison_label`. Without it a stock
  signal falls through `_assemble_kpi_card` to the year-on-year branch and
  publishes against "the prior period" — a comparison this data does not
  contain. This bug shipped live once, as *"STOCK OUT - PLACE ORDER performance
  increased by 17.8K"*, where nothing increased and the figure was a row count.
- Rank by exposure, not percentage. A large percentage on a trivial slice must
  never outrank a small percentage on a large one. `kernel/ranking.py` has the
  blends; use them, do not write a new one.

### 3.3 Run the reverse experiment

Ask whether Sales YoY needs Tier 2 **every** day. With `escalation.py` on, look
at a fortnight of `insight_escalation.json`: how often is the tier *quiet*?
Expect YoY to sit at Tier 1 most days and buy Tier 2 perhaps twice a week. If
that holds, make it the default and let the day promote it.

**Exit criterion:** `report_ai_tier` in the schema and in every live config with
today's behaviour named; golden master byte-identical; Inventory Management
producing an investigated page that passes `scripts/audit_stock_health.py`; a
fortnight of escalation tiers reviewed.

---

## 8. Phase 4 — Make budget a first-class control

**Goal:** cost becomes something a code change can break, and therefore
something a test can catch.

- **Per-client daily ceiling.** A new `daily_cost_ceiling_usd` (default `0`,
  meaning no ceiling, so nothing changes). When a run would exceed it, drop that
  report to the next tier down and **say so in the log and on the page's
  limitations**. A silently cheaper report is the same class of failure as a
  silently wrong one.
- **Cost regression in the gate.** Add the recorded baseline to
  `tests/bench/` and a check that fails when a run's projected token count rises
  materially. Cost is now a guaranteed property, like the arithmetic the golden
  master guards.
- **Report it.** Cost per client per month, from `token_usage.json`. That is what
  determines pricing, so it should not require a spreadsheet.

**Exit criterion:** ceiling enforced and visible when it fires; cost regression
check in `replay_all.py`.

---

## 9. What this adds up to

Per client, six daily reports:

| | Per run | Per client/yr | 20 clients/yr |
|---|---|---|---|
| Today, if all six were on the pipeline | $1.54 | ~$3,370 | ~$67,000 |
| After Phase 0 | $0.68 | ~$1,490 | ~$30,000 |
| After Phase 1 | ~$0.32 | ~$700 | ~$14,000 |
| After Phase 3 | ~$0.12 | ~$260 | ~$5,300 |

**Only the first two rows are measured.** The last two are projections from where
the spend currently sits, and should be replaced with measurements as each phase
lands.

---

## 10. Do not do these

- **Do not move the five standalone reports into LangGraph.** They are outside it
  for a good reason and the brief does not change that. The goal is to give them
  more AI, not more graph.
- **Do not put values in the plan cache key.** Data changes daily; that is the
  point of the product. Keying on it makes the cache never hit.
- **Do not let a cheaper model reach an unvalidated surface.**
- **Do not weaken a validator to make a saving.**
- **Do not merge the three prose validators' *rules*.** Extract the shape only.
- **Do not skip the artifact auditors.** `audit_summary_dashboard.py`,
  `audit_stock_health.py`, `audit_ageing.py`, `audit_target_tracker.py` prove a
  *produced* artifact, not the code. A replay proves the code is right; an audit
  proves this morning's page is right. They have caught two live arithmetic bugs
  that no replay saw.
- **Do not trust a screenshot-free dashboard change.** Every rendering fault this
  repo has hit was invisible to string assertions and obvious to the eye. Render
  the page and look at it.

---

## 11. First actions for the session picking this up

1. Read `CLAUDE.md` sections "Agent architecture", "Concurrency contract" and
   "Gotchas". Read this file's Phase 0 again.
2. `cd powerbi-summary-agent && python scripts/replay_all.py --with-golden` —
   establish that the tree is green **before** you change anything.
3. Read the three untracked modules in `src/tools/`.
4. Open `outputs_bench_results/bench_results.json` and the two
   `token_usage.json` files, and confirm the numbers in section 1 for yourself.
5. Start at 0.2 — write the replays.

Report at the end of each phase: what changed, what the gate said, what the live
run cost, and what you could not verify.
