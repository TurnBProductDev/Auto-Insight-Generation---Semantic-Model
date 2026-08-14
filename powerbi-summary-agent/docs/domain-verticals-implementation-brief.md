# Domain Verticals — Implementation Brief (Inventory first)

**Purpose of this file:** a self-contained handoff for a fresh coding session. It assumes no
prior conversation context. Read Part 0 first and in order.

**What we are building:** domain verticals over one shared kernel. **Inventory is built
first** (Ageing, then Inventory Management), then the Sales additions (Target Tracker, Daily
Sales). Report summaries stay separate per report; insight extraction is shared per domain
chain.

**Related docs:** `report-agnostic-execution-plan.md` (the fully generic alternative — this
brief deliberately takes a narrower, faster path), `report-agnostic-plan-plain-english.md`,
`config-ui.md`, `CLAUDE.md` / `AGENTS.md` (architecture of record).

---

## PART 0 — Orientation: read these before writing any code

### 0.1 Read in this order

| # | File | Why |
|---|---|---|
| 1 | `CLAUDE.md` (repo root) | The architecture of record. Long, but the concurrency contract and the DAX guardrails in it are the two things a fresh session most reliably breaks |
| 2 | `src/graph.py` | The whole topology in 120 lines of wiring. `build_graph()` is a fixed graph today — WP3 makes it assembled |
| 3 | `src/agents/semantic_profiler.py` | The control plane. The `(current, prior, change)` triple originates at `:228-277`; `_additive()` at `:128-138` returns a plain bool, which is the single biggest inventory blocker |
| 4 | `src/tools/summary_focus_queries.py` | Every deterministic DAX builder. `universe_scan` at `:114` is where the three-phase assumption reaches the query layer |
| 5 | `src/tools/summary_materiality.py` + `summary_coverage.py` | The ranking and banding math. `is_comparable` at `summary_coverage.py:89` is the gate that fails for every snapshot report |
| 6 | `src/tools/summary_memory.py` + `src/tools/insight_memory.py` | Cross-run memory. **Both key on `dataset_id` alone** — `summary_memory.py:49`, `insight_memory.py:53-57`. Two reports on one dataset collide today |
| 7 | `src/config_schema.py` (skim the top 300 lines) | How settings are catalogued, and the anti-drift discipline any new setting must follow |
| 8 | `docs/report-agnostic-execution-plan.md` Parts 1 and 2 | The full YoY coupling inventory with line numbers, and the measurement-spine design this brief reuses |

### 0.2 Verify the tooling works before changing anything

```bash
cd powerbi-summary-agent
python scripts/replay_summary_coverage.py
python scripts/replay_summary_dashboard.py
python scripts/replay_config_schema.py
python scripts/replay_summary_portfolio.py
python scripts/replay_summary_r4_isolation.py
python scripts/replay_novelty_filter.py
python scripts/replay_stat_detector.py
```

All offline, no auth, no LLM. If any fails on a clean checkout, **stop and report it** — do
not start work on a red baseline.

### 0.3 There is zero inventory prior art in this repo

Verified: the only occurrence of the words stock / inventory / ageing / reorder anywhere in
`src/`, `config/` or `docs/` is the refusal message at `services/probe.py:255` and an
unrelated "stock-up promotion" row in the lever state matrix. **Nothing has been started, and
nothing needs unpicking.** Everything inventory is new build on a clean slate.

### 0.4 What already exists and must not be rebuilt

The pipeline runs daily against a live model and produces two reports plus an interactive
dashboard. Out of scope for reimplementation:

auth and token reuse · metadata scan + Fabric measure-definition recovery · DAX assembly and
the model guardrails · query validation and scope gating · budgeted execution with caching ·
reconciliation arithmetic · the ranking blend · rotation and novelty · prose grounding
validation with a passing deterministic fallback · self-contained HTML rendering ·
three-destination publishing · the onboarding UI (probe → validate → deploy).

---

## PART 1 — Feasibility assessment

### 1.1 Verdict on the vertical structure

**Adopt it.** It is a better delivery strategy than the fully generic framework in
`report-agnostic-execution-plan.md`: it ships a working new report far sooner, it matches how
the business documents are organised, and each domain's analytical logic gets built
deliberately from a real document instead of guessed at in advance.

**Four things need correcting, or it fails.** Each is addressed by a work package below.

### 1.2 Correction 1 — "branch" must mean *domain package*, not a new LangGraph fork

The word is already taken in this codebase: the graph forks into a **summary branch** and an
**insight branch** that run concurrently and rejoin at a barrier (`graph.py:353-354`, join at
`save_outputs`).

Adding Sales and Inventory as *further concurrent branches of one graph* breaks three things:

- **The concurrency contract.** Every state key except `logs`/`errors` is single-writer per
  superstep. Several reports' nodes in one superstep collide — LangGraph raises
  `InvalidUpdateError`, or worse, silently interleaves.
- **The token rule.** `get_powerbi_token()` does an unlocked read-modify-write of the cache
  file. Today exactly one pre-fork fetch happens and both branches reuse it. More parallel
  branches means more pressure on that rule for no benefit.
- **Failure isolation.** The barrier waits for *both* branches. Make it wait for ten and one
  stalled inventory scan holds up a sales report that was ready twenty minutes ago.

**The correct shape:**

```
one report  = one graph run  (summary branch ‖ insight branch → join → save)
one chain   = one job running its reports SEQUENTIALLY in one process
one domain  = a Python package supplying spines, evidence builders, layouts, rules
```

The fork/join shape stays exactly as it is.

### 1.3 Correction 2 — copy-pasted verticals will rot inside one release

Not hypothetical. The codebase **already** contains two independent copies of the retail
measure-family vocabulary — `semantic_profiler._FAMILY_TOKENS` (`:34-42`) and
`summary_candidate_builder._family()` (`:56-68`) — which can disagree with nothing to catch
it.

Fork a whole vertical and you get two copies of the materiality formulas, the coverage
ranking blend, the severity bands, the memory transaction logic, the validation primitives,
the HTML renderer, and the artifact auditor. A correctness fix landed in one is not landed in
the other — and this product's entire value is that its numbers are trustworthy. Two of the
bugs already fixed here (contributions summing to −38.13 points against a −51.98% move; an
excluded branch contaminating a prior-year denominator) were found only because one auditor
existed to find them.

**So a shared kernel is mandatory.** But — see 1.5 — building inventory first lets the kernel
be *smaller* and better shaped than it would otherwise be.

### 1.4 Correction 3 — Daily Sales is a go/no-go, not a schedule item

The existing shared business-day gate (`insight_business_day_source.py`) already answers
whether a genuine business-**day** axis exists, and on the working model **it says no**:
`UPDATED_DATE` fails the batch/load-date test (~all revenue lands on month-end; one bucket
held 0.53 of the total) *and* the data is ~2.5 years stale. Both
`insight_recent_week_verdict.json` and `insight_daily_verdict.json` record this.

Verify on the actual target model in WP0. If no genuine, current, calendar-day business date
exists, **do not build Daily Sales** — a batch/load date produces plausible daily numbers
that are wrong, which is worse than no daily report. That is a Power BI model change, not a
code change.

### 1.5 Correction 4 (revised) — inventory first is the right call, and it improves the kernel

An earlier draft of this brief recommended building Target Tracker first, on the grounds that
it is the cheapest possible second report and therefore the cheapest validation of the
architecture. **That advice was wrong in one important respect, and inventory-first is
better.**

Why: Target Tracker still has two measures and a signed variance. It exercises the spine
abstraction only shallowly — it would validate that the plumbing was rewired, not that the
abstraction is the right one. A kernel shaped by Sales YoY plus a near-identical second
report would then have to be reshaped when inventory arrived anyway.

Building the **hardest consumer first** means the kernel is shaped by the hardest real
requirement rather than retrofitted to it. Concretely, inventory forces four things into the
open that Target Tracker would let us keep deferring:

| Forced into the open by inventory | Would stay hidden by Target Tracker |
|---|---|
| A number that does not add up over time (semi-additive) | Everything stays additive |
| "As at a date" vs "over a period" (snapshot semantics) | Both are periods |
| Ranking with no signed change | Signed variance exists |
| Novelty as a *state with a duration*, not a period | Period anchor works |

There is a second, practical argument: the business documents and live report access are in
hand **now**. Domain knowledge is perishable.

**And it lets the kernel be smaller.** Because inventory is the first consumer, WP2 extracts
only what inventory would otherwise copy, and leaves genuinely Sales-specific machinery where
it is:

| Extract to the kernel (inventory needs it) | Leave in the Sales domain (inventory does not) |
|---|---|
| Coverage ranking + materiality, spine-parameterized | The three-lever spine (`summary_levers.py`) |
| Aggregation semantics + numeric verification | The volume/rate-mix bridge |
| Memory transactions, scoping, migration | The calendar/comparator-drift check |
| Ranking blend registry | The period resolver's YoY-specific anchoring |
| DAX builders, validator, scope gate, budgets | Retail measure families |

**The honest cost of this ordering:** first visible report slips from ~week 9 to ~week 11, and
the first phase carries more unknowns (Q3, Q4, Q5). Both are managed by WP0 plus the spike in
1.7 — do not skip either.

### 1.6 Correction 5 — Ageing before Inventory Management (keep this order)

These are not two flavours of one report.

| | Ageing | Inventory Management |
|---|---|---|
| Shape | Value distributed across ordered age buckets | Current position vs a policy band |
| Has a comparison? | **Yes** — this period's distribution vs last period's | **No** — there is no prior, only a rule |
| Movement means | Value migrating between buckets | Distance outside the band |
| Ranking needs | A signed change (already exists) | A change-free blend (new) |
| Novelty needs | Period anchor (already exists) | State + duration (new) |
| Needs semi-additive | Yes | Yes |
| Needs snapshot-date semantics | Yes | Yes |

Ageing needs the two *shared* foundations but **not** the two hardest inventory-specific
capabilities. It is strictly less work and it de-risks Inventory Management by proving the
foundations on a report that can still be checked against a signed comparison.

**If business priority demands Inventory Management first**, it is possible, at a cost: you
would need the policy-band spine, the change-free ranking blend and state+duration novelty
all before the first delivery, pushing first visible report to roughly week 14. A cheaper
variant is to ship Inventory Management without duration-aware novelty in v1 — but it will
then re-report the same exception every morning, which users hate and which undermines trust
in the whole agent. **Not recommended.** Say so if asked.

### 1.7 Do this three-day spike before committing to seven weeks of kernel work

Inventory-first concentrates risk into one unknown that is cheap to test and expensive to be
wrong about: **can a semi-additive stock measure be read correctly from this model at all?**

Write a throwaway script (not part of the architecture) using the existing
`powerbi_executor.execute_python` and a hand-written DAX query. Prove, on the live inventory
model:

1. A stock-on-hand measure returns a sensible total **at a single snapshot date**.
2. Summing that measure across several snapshot dates returns a total that is
   **wrong by roughly the number of snapshots** — this is the positive evidence that it is
   semi-additive, and the test WP4 automates.
3. Members at one snapshot **add up to the total** at that snapshot (the reconciliation the
   whole product depends on).
4. There is a date column that behaves as an as-of stamp, and it is distinguishable from a
   transaction date.

**Three days, no architecture, no commitment.** If any of these fails, the plan changes
materially and you have learned it in week one instead of week nine. Record the findings in
the WP0 findings document.

### 1.8 Assessment of "insight extraction can be clubbed"

**The strongest idea in the plan, and simpler than the alternative.**

Two readings:

- **(a) Shared memory, separate extraction** — each report runs its own insight branch but
  reads/writes one chain memory so they do not repeat each other. Needs cross-report
  suppression, per-report delivery tracking, deterministic run order. *More* complex.
- **(b) Shared extraction** — the insight branch runs **once per chain** over pooled evidence
  from every report in the chain, producing **one** investigative report plus separate
  descriptive summaries.

**Recommend (b).** It is what "clubbed" naturally means, it produces a better artifact (one
coherent "why" narrative that can connect a stock-cover problem to an ageing build-up), and
it avoids cross-report suppression entirely because there is only one memory consumer.

Three requirements, addressed in WP8:

1. **The chain runs as one process.** Non-negotiable: `get_powerbi_token()`'s unlocked
   read-modify-write and `insight_memory.commit_run`'s best-effort lock both assume a single
   writer. Separate container jobs writing one chain memory will race.
2. **Per-report representation must be guaranteed.** Pooling reports multiplies the candidate
   list; `insight_max_new_per_run` would let the loudest report crowd the others out. The fix
   already exists as a pattern — `_backfill_uncovered` in `insight_signal_detector.py`
   guarantees a whole *level* cannot go silently invisible to LLM bias. Extend the same
   mechanism per report in the chain: inject its single best candidate, then let it compete on
   the same materiality `score`, **never ahead of it**. Do not introduce priority ordering
   between reports; there deliberately is none between levels today.
3. **Evidence contracts carry `report_id`** so provenance survives pooling and the reader
   knows which dashboard to open.

**Inventory is the better first chain**: two reports over the same stock position is a
simpler and more meaningful pooling test than three sales reports, and the machinery is
identical, so the sales chain becomes configuration afterwards.

### 1.9 Open questions that must be answered before coding

WP0 exists to answer these. The first four are now **critical path**, because the whole first
phase depends on them.

| # | Question | Why it changes the plan | Priority |
|---|---|---|---|
| Q1 | Are Inventory Management and Ageing in the **same** semantic model as the sales reports, or different? | Same → one metadata scan, chain can share pre-fork nodes. Different → separate scans, and cross-*domain* insight clubbing is not meaningful because `story_key` includes `dataset` | **Critical** |
| Q2 | Do **policy measures** exist (reorder point, min/max, safety stock), or only current balances? | No policy measure ⇒ Inventory Management has no baseline. See the fallback tree in 1.10 | **Critical** |
| Q3 | Is there a **snapshot date**, and is it distinguishable from a transaction date? | Filtering a snapshot with a date *range* instead of "latest" produces a confidently wrong number | **Critical** |
| Q4 | Are **ageing buckets** pre-computed (a column or measure per bucket), or must they be derived from a receipt date? | Pre-computed → an ordinal axis, straightforward. Derived → date arithmetic in DAX, a wider scan, and a day-count definition that must come from the document | **Critical** |
| Q5 | Which stock measures are **semi-additive**, and does each reconcile at a snapshot? | The 30×-too-big failure. Answered by the spike in 1.7 | **Critical** |
| Q6 | What is each report's **cadence** (daily / weekly / monthly)? | Changes the memory window, freshness thresholds and rotation | High |
| Q7 | For each report: **who reads it and what do they decide?** | Determines the layout and what counts as material. Comes from the business documents | High |
| Q8 | Do **target/budget/plan measures** exist? | Blocks Target Tracker (WP9), not the inventory phase | Deferrable |
| Q9 | Does a genuine, current, calendar-day **business date** exist? | Go/no-go for Daily Sales (WP11) | Deferrable |

### 1.10 Fallback tree if Q2 comes back "no policy measures"

Do not fabricate a policy band. If the model has only current balances:

1. **Preferred:** ask whether reorder point / min / max can be added to the Power BI model.
   It is a model change, usually small, and it is what makes the report possible.
2. **If not available soon:** ship Ageing (WP5) as planned — it does not need policy — and
   re-scope Inventory Management as a **composition and concentration** report: where stock
   value sits, how concentrated it is, how it shifted since the last snapshot. That is a
   genuinely useful report and it needs no policy baseline. Update the rulebook to say
   explicitly that it does not assess whether stock levels are *correct*.
3. **Never:** infer a policy band from observed averages and present it as a standard. It
   would look authoritative and be invented.

State whichever path is taken in the WP0 findings document before WP6 begins.

### 1.11 Revised sequence and sizing

| WP | Work package | Size | Visible outcome |
|---|---|---|---|
| **spike** | Semi-additive read proof (1.7) | 3 days | A go/no-go answer |
| **WP0** | Safety net + answer Q1–Q7 | 1.5 wk | None (a findings document) |
| **WP1** | Report identity and run scoping | 1.5 wk | None (byte-identical output) |
| **WP2** | Kernel-lite: spine, aggregation, blends | 2.5 wk | None (byte-identical output) |
| **WP3** | Domain packages + assembled graph | 1.5 wk | None (byte-identical output) |
| **WP4** | Snapshot foundations (semi-additive, snapshot date) | 2 wk | None (enabling work) |
| **WP5** | **Ageing report** | 2 wk | **First new report — first inventory value** |
| **WP6** | Policy-band spine, change-free ranking, state novelty | 2.5 wk | None (enabling work) |
| **WP7** | **Inventory Management report** | 2 wk | Second inventory report |
| **WP8** | **Inventory chain** with clubbed insight extraction | 1.5 wk | One "why" report across both inventory reports |
| **WP9** | **Target Tracker report** | 2 wk | First sales addition |
| **WP10** | Sales chain (3 reports) | 1.5 wk | One "why" report across the sales chain |
| **WP11** | **Daily Sales report** (conditional on Q9) | 2 wk | Third sales report |

**Total ≈ 23 weeks / ~5.5 months.** WP0–WP4 are ~9 weeks with no visible feature; first
inventory report lands around **week 11**, second around **week 15.5**, inventory chain
complete around **week 17**. Sales additions follow.

Cost of inventory-first versus the earlier sales-first draft: **~2 weeks later to first
delivery**, in exchange for a kernel shaped by the hardest requirement and inventory value
delivered ~9 weeks earlier than it otherwise would be.

---

## PART 2 — Non-negotiables

Violating any of these produces a subtly broken agent that still appears to work. They are
drawn from failures this codebase has already had.

### 2.1 Authentication and concurrency

1. **Never** shell out to PowerShell for interactive login. An earlier attempt hung, because
   interactive login cannot surface through a captured subprocess.
2. **One** `get_powerbi_token()` call per run, pre-fork, into `state["pbi_token"]`. Every
   post-fork node takes the token as an argument. The cache write is unlocked and unsafe from
   two branches at once.
3. `logs` and `errors` are reducer-backed (`Annotated[List[str], operator.add]`). `RunLogger`
   returns **only the current node's new lines**. Never seed a logger from prior state and
   never return accumulated lists — the reducer would double-count.
4. Every other state key is **single-writer per superstep**. A node in one branch must never
   write a key a node in the other branch writes.
5. The join is a **barrier**, not loose edges: each branch funnels through its
   `*_branch_done` node, and one joined edge waits for both. Ad-hoc edges into `save_outputs`
   can fire it twice.

### 2.2 DAX

6. **Never** `KEEPFILTERS('Table'[Col] = "value")` — it reliably fails on this model with
   "single value for column cannot be determined". Use `TREATAS({...}, 'T'[col])`.
7. Every `SUMMARIZECOLUMNS` breakdown carries a `TOPN` row limit.
8. `executeQueries` can return **HTTP 200 with a per-query error embedded in the body**
   (`results[0].error`). `execute_python` reclassifies these as `"failed"`. Preserve that
   check — trusting `resp.ok` turns real DAX errors into fabricated zero-row successes.
9. Deterministic template DAX is **never** LLM-repaired. A rewrite invalidates the
   construction-time provenance the evidence contract depends on.
10. When removing a member filter to compute an "overall" diagnostic, **re-apply the
    population filters**. A bare `REMOVEFILTERS(store)` inside a comparable-store population
    strips the population too — this is exactly how an excluded branch's prior-year revenue
    got into a denominator and made contributions sum to −38.13 points against a −51.98%
    move.
11. **New, and critical for inventory:** a semi-additive measure is **never** aggregated
    across snapshot dates. Filter to a single snapshot, or use an explicit
    last-non-blank pattern. A sum across snapshots is the 30×-too-big failure.

### 2.3 Correctness and honesty

12. **Withhold rather than publish wrong.** An unreconciled breakdown is dropped with a
    stated reason, never published with numbers that do not add up.
13. **Unmeasurable is not zero and not green.** A member with no baseline goes in its own
    bucket, labelled, ranked last. It can never be `critical` and never reads as on-track.
14. **Never rank on raw percentage.** Sorting on percent change reproduces the exact failure
    the blended score exists to prevent (`CF-FRESH BAKES +2166.79%` on a near-zero base).
15. **Every deterministic fallback must itself pass strict validation.** Otherwise validation
    can dead-end and the run ships nothing. This is currently tested; keep it tested for every
    new rule pack.
16. **A quoted figure must exist in the model**, and be rounded — the raw floats let
    `+2.7147647284841927%` through a live draft once.
17. No forecasting, no asserted causation, no emojis, no invented figures. Contribution and
    correlation language stays hedged.
18. **New, for inventory:** a period label for a snapshot measure says **"as at <date>"**,
    never a span. Labelling a snapshot with a range tells the reader it covers a period it
    does not.

### 2.4 Process

19. Run `python scripts/audit_summary_dashboard.py <output_dir>` after **every** live run, and
    write an equivalent auditor for every new report. It caught both the derived-period
    contribution bug and the contaminated-denominator bug. A replay proves the *code* is
    right; the auditor proves a *produced artifact* is right.
20. `AGENTS.md` and `CLAUDE.md` must remain **byte-identical**. Update both.
21. Any new config key goes in `src/config_schema.py` with `label`, `help`, `detail` and
    `tier`, or `scripts/replay_config_schema.py` fails. That test is load-bearing: it has
    already caught a key read from state but never copied out of config.
22. New feature flags default to **false in code** and are enabled in the committed config —
    the precedent set by `summary_r4_enabled` / `summary_r6_enabled`, so a config missing the
    key reproduces prior behaviour exactly.

---

## PART 3 — Target structure

```
src/
  kernel/                          # NEW — domain-agnostic, shared by every domain
    __init__.py
    spine.py                       # MeasurementSpine protocol + SPINE_REGISTRY
    aggregation.py                 # AggregationClass enum + numeric verification
    ranking.py                     # BLEND_REGISTRY
    report.py                      # ReportSpec, ResolvedReport, node-set assembly
    chain.py                       # ChainSpec, sequential runner, pooled evidence
    scoping.py                     # report/chain-scoped paths for memory, history, outputs

  domains/                         # NEW — one package per business domain
    __init__.py                    # DOMAIN_REGISTRY
    inventory/                     # BUILT FIRST
      __init__.py
      families.py                  # stock / cover / value / ageing vocabulary
      spines.py                    # SnapshotVsSnapshotSpine, SnapshotVsPolicySpine
      decompositions.py            # stock_value = units x cost; cover = units / daily_sales
      buckets.py                   # ordinal age-bucket axis + migration math
      reports/
        ageing.py
        stock_health.py
      layouts/*.json
      rules/*.json
    sales/                         # BUILT SECOND (existing behaviour moves here)
      __init__.py
      families.py                  # revenue / units / transactions (moved from profiler)
      spines.py                    # PeriodOverPeriodSpine, ActualVsTargetSpine
      decompositions.py            # three-lever + volume/rate (wrap existing modules)
      reports/
        yoy_performance.py         # today's behaviour, byte-identical
        target_tracker.py
        daily_sales.py
      layouts/*.json
      rules/*.json

  agents/  tools/  utils/  api/  services/     # unchanged locations
```

**Migration philosophy: extend, do not move.** In WP2/WP3 the kernel modules are thin
parameterized wrappers over the existing `src/tools/` implementations, with defaults that
reproduce today's behaviour. Nothing is physically relocated until the golden master has been
green across several work packages. A large file move plus a semantic change in one commit is
how a byte-comparison net stops being able to tell you which one broke.

```
config/<client>/
  config.json                      # connection, storage, budgets, provider  (unchanged)
  client_business_rules.md          # NEW — company-wide facts only
  chains/
    inventory.json                  # chain: report order, shared-insight settings
    sales.json
  reports/
    inventory_ageing/
      report.json                   # spine, KPIs, axes, thresholds, layout
      business_rules.md             # from the Ageing document
    inventory_stock_health/
      report.json
      business_rules.md             # from the Inventory Management document
    sales_yoy/
    sales_target_tracker/
    sales_daily/
```

```
insightstate/<dataset_id>/
  chains/<chain_id>/memory.json     # NEW — chain-scoped insight memory
  reports/<report_id>/memory.json   # NEW — report-scoped summary memory
  memory.json                       # EXISTING — migrated in WP1
outputs/
  <chain_id>/insight_report.md      # one investigative report per chain
  <chain_id>/<report_id>/report_summary.md, report_dashboard.html, ...
```

---

## PART 4 — Work packages

Each has a goal, the files it touches, the concrete changes, and an exit criterion. **Do not
start a work package until the previous one's exit criterion is met.**

### Spike — semi-additive read proof *(3 days, throwaway code)*

Per 1.7. Prove on the live inventory model that a stock measure reads correctly at one
snapshot, sums wrongly across snapshots, reconciles across members at one snapshot, and that
an as-of date column exists and is distinguishable from a transaction date. Record findings.
**No architecture, no commitment.** If it fails, stop and re-plan.

---

### WP0 — Safety net and facts *(1.5 weeks, no pipeline changes)*

**Goal:** make regression detectable, and answer Q1–Q7 with evidence rather than assumption.

**Build:**

1. `scripts/golden_master.py` — byte-compare the deterministic artifacts of every committed
   acceptance run. At minimum: `summary_focus_universe.json`, `summary_coverage.json`,
   `summary_overall_performance.json`, `summary_dashboard.json`,
   `summary_focus_evidence_by_key.json`, `resolved_entity_scope.json`,
   `semantic_model_profile.json`. Sources: `outputs_r4_acceptance/`,
   `outputs_r4_acceptance_20260730_fix/`, `outputs_scanb/`. Normalise only timestamps and
   absolute paths — nothing else.
2. `scripts/replay_all.py` — one gate running every existing replay, non-zero exit on any
   failure.
3. **Fixture models** — synthetic `model_metadata` JSON committed under
   `tests/fixtures/models/`. Inventory-first means build these first and in this order:
   a **stock-snapshot** model, an **ageing-bucket** model, then today's retail YoY model,
   then a target-attainment model. Hand-written, offline, no auth. These are what let WP4–WP7
   be developed and tested with no live connection.

**Investigate (this is the deliverable, not a side task):**

4. Run `python scripts/probe_summary_universe.py --config <path> --deep` against **every**
   target model — the inventory model(s) first, then the sales model. Capture output verbatim.
   Expect the inventory probe to **fail** with the refusal at `probe.py:255`; that is correct
   current behaviour and the failure output still contains the measure and dimension
   inventory you need.
5. Read both business documents (Inventory Management, Ageing) and extract, per report: the
   question it answers, its audience and decisions, its KPIs with exact definitions, its
   levels, its thresholds, its exclusions, its cadence, and any calculation rules. **Record
   what the documents do not say** — those become the stop-and-ask list.
6. Open the live Power BI reports and record: which measures exist for policy bands and
   ageing buckets; whether a snapshot date column exists; what each date column actually is;
   how ageing days are counted.

**Exit criteria:**

- `replay_all.py` green; `golden_master.py` zero differences on a clean checkout.
- `docs/domain-verticals-findings.md` written, answering Q1–Q7 with probe output quoted as
  evidence, stating explicitly whether Ageing and Inventory Management are **buildable,
  degraded, or blocked on a model change**, and recording which branch of the 1.10 fallback
  tree applies.
- Four fixture models committed and loadable.

---

### WP1 — Report identity and run scoping *(1.5 weeks, output must not change)*

**Goal:** the pipeline knows which report it is running, and two reports on one dataset cannot
collide.

**Changes:**

1. `src/kernel/report.py` — `ReportSpec` dataclass: `report_id`, `report_name`, `domain`,
   `chain_id`, `dataset`, `cadence`, plus sections filled in by later work packages
   (`spine`, `kpis`, `axes`, `thresholds`, `layout`, `rules`, `knowledge`).
2. `src/kernel/scoping.py` — the single authority for every previously dataset-scoped path:
   - summary memory: `<root>/<dataset_id>/reports/<report_id>/memory.json`
   - insight memory: `<root>/<dataset_id>/chains/<chain_id>/memory.json`
   - history, outputs, API payloads: same pattern.
3. `src/tools/summary_memory.py:store_path` and `src/tools/insight_memory.py:_dataset_dir`
   call into `scoping.py`. **Add a non-destructive migration**: an existing
   `<dataset_id>/memory.json` moves into `reports/sales_yoy/` (summary) and `chains/sales/`
   (insight) on first run, following the established v1→v2→v3 pattern in
   `summary_memory._migrate`. Bump `SCHEMA_VERSION` to 4.
4. `src/main.py` — add `--report <report_id>` (optional). Absent ⇒ resolve the single report
   in the config, so every existing invocation keeps working unchanged.
5. `src/container_entrypoint.py` — accept `AGENT_REPORT_ID` and pass it through.
6. `src/config_schema.py` — catalogue any new keys with label/help/detail/tier.

**Exit criteria:**

- `golden_master.py` byte-identical; `replay_all.py` green.
- New `scripts/replay_report_scoping.py`: two report ids on one dataset get separate stores;
  the migration is non-destructive and idempotent; a config with no report id behaves exactly
  as before.
- A live run with `--report sales_yoy` produces artifacts identical to a run without the flag
  (modulo output path).

---

### WP2 — Kernel-lite: spine, aggregation, ranking *(2.5 weeks, output must not change)*

**Goal:** the three-phase measure triple stops being the type system, without any behaviour
changing. **Scope is set by what inventory needs** (per 1.5) — do not extract Sales-specific
machinery.

**Changes:**

1. `src/kernel/spine.py` — the protocol:

```python
class MeasurementSpine(Protocol):
    kind: str
    baseline_label: str            # manager-facing, e.g. "the same period last year", "the agreed stock policy"

    def measures(self) -> dict           # slot -> measure name/expression
    def delta_expr(self) -> str          # DAX fragment for the movement
    def delta_kind(self) -> str          # absolute | points | distance | none
    def pct(self, current, baseline) -> float | None
    def classify(self, row: dict) -> str # comparable | baseline_missing | current_only | inactive
    def population_filter(self, scope: dict) -> str | None
    def denominator(self, rows: list[dict]) -> float | None
    def rank_components(self, member: dict, level: dict) -> dict
    def novelty_key(self, member: dict, context: dict) -> dict
    def caveats(self) -> list[str]
```

2. `src/domains/sales/spines.py::PeriodOverPeriodSpine` — implements the protocol by
   delegating to the existing `semantic_profiler` bundle logic. The only spine in WP2, and it
   must reproduce today exactly.
3. `src/kernel/aggregation.py` — `AggregationClass` with five values: `ADDITIVE`,
   `SEMI_ADDITIVE_LAST`, `ADDITIVE_WITHIN_LEVEL`, `NON_ADDITIVE_RATIO`, `DURATION`. Plus
   `verify(class_, measure, executor)` which **proves** the claim numerically rather than
   trusting it. Wire the classification into `semantic_profiler` alongside — not replacing —
   the existing `additive_candidate` boolean, so nothing downstream changes yet.
4. `src/kernel/ranking.py` — `BLEND_REGISTRY`. Register the existing blend as
   `impact_magnitude_unexpectedness`, implemented by calling the current
   `summary_coverage.rank_scores` code path.
5. **Parameterize on the spine, with today's behaviour as the default:**
   - `summary_focus_queries.universe_scan(...)` — accept a `spine`, derive
     `current/prior/change` from it, keep the existing keyword signature working.
   - `summary_materiality.compute_facts(...)` — take the spine for `area_change` and the
     percentage denominator.
   - `summary_coverage.is_comparable` → `spine.classify(member) == "comparable"`.
   - `summary_coverage.rank_scores` → dispatch through `BLEND_REGISTRY`.
   - `summary_focus_universe.run` — build the spine from the report spec; the `no_metric` hard
     stop at `:190` becomes a spine-resolution failure carrying the spine's own reason.

**Exit criteria:**

- `golden_master.py` **byte-identical**. This is the critical gate of the whole programme — if
  it is not byte-identical, the refactor changed arithmetic and must be reverted, not patched.
- `replay_all.py` green.
- New `scripts/replay_kernel_spine.py`: the period-over-period spine against the retail
  fixture reproduces the committed universe/coverage artifacts exactly; each aggregation class
  verifies correctly against a purpose-built fixture — in particular **a semi-additive measure
  must fail the additive verification**.

---

### WP3 — Domain packages and assembled graph *(1.5 weeks, output must not change)*

**Goal:** a report declares its node sequence; a domain supplies its vocabulary.

**Changes:**

1. `src/domains/__init__.py` — `DOMAIN_REGISTRY: dict[str, Domain]`. A `Domain` supplies:
   measure families, available spines, decompositions, default layouts, default rule packs,
   default thresholds.
2. `src/domains/sales/families.py` — the retail vocabulary moved out of
   `semantic_profiler._FAMILY_TOKENS`/`_VALUE_FAMILIES`/`_FAMILY_PRIORITY`. **Delete the
   duplicate copy** in `summary_candidate_builder._family()` and re-source it here — the drift
   risk from 1.3, fixed.
3. `src/domains/inventory/__init__.py` + `families.py` — the inventory domain skeleton, with
   stock / cover / value / ageing vocabulary, correct aggregation classes and directions. No
   spine yet; that is WP4.
4. `src/graph.py` — `build_graph()` becomes `build_graph(report: ResolvedReport)`, assembling
   from a registry of node factories keyed by name. `build_graph()` with no argument keeps
   working and yields today's fixed graph. **The fork/join topology is unchanged**: one
   summary branch, one insight branch, one joined-edge barrier, one pre-fork fatal edge.
5. `src/domains/sales/reports/yoy_performance.py` — a `ReportSpec` declaring today's node
   sequence, spine, KPIs, axes, thresholds, layout and rule pack. Derived from the existing
   `config.json` so no config needs rewriting.
6. `src/kernel/report.py` — `resolve(spec, profile, metadata) -> ResolvedReport`. **Frozen and
   read-only** after pre-fork resolution, so both branches read it with no writer conflict.

**Exit criteria:**

- `golden_master.py` byte-identical; `replay_all.py` green.
- New `scripts/replay_domain_assembly.py`: the assembled Sales-YoY graph has the same nodes
  and edges as the fixed graph; a report spec omitting a node produces a valid graph that
  still forks and joins correctly; two specs in one process do not share mutable state.

---

### WP4 — Snapshot foundations *(2 weeks, enabling work)*

**Goal:** the agent can handle a number that does not add up over time, and knows what "as
of" means.

**This is the highest-risk work package in the programme.** A stock figure summed across 30
snapshots is 30× too big, and every existing internal reconciliation check would *pass*,
because both the parts and the whole were summed the same wrong way. Treat every test here as
load-bearing.

**Changes:**

1. **Semi-additive end to end.**
   - DAX: a last-non-blank / single-snapshot filter pattern in `summary_focus_queries.py` for
     `SEMI_ADDITIVE_LAST` measures. Obeys Non-negotiable 11.
   - Reconciliation: for a semi-additive measure the check is *"members at the latest snapshot
     sum to the total at the latest snapshot"* — **never** a sum across snapshots. Refuse a
     report whose semi-additive claim fails WP2's `verify`.
   - Display and prose: the period label says **"as at <date>"** (Non-negotiable 18).
2. **Snapshot-date semantics.** Extend the profiler and probe to distinguish a *snapshot* date
   (an as-of stamp; correct filter is "latest") from a *transaction* date (an event; correct
   filter is a range). This is Q3.
3. `src/domains/inventory/spines.py::SnapshotVsSnapshotSpine` — baseline is the same measure at
   a prior snapshot; delta is absolute and signed, so the **existing** ranking blend applies
   unchanged. This is deliberate: it lets WP5 ship without a new blend.
4. `services/probe.py` — report the aggregation class per measure with its verification
   verdict, and the snapshot-vs-transaction date verdict, in plain language. Replace the blanket
   refusal at `:248-257` with a contract-aware check: a snapshot model is no longer refused
   outright, but a *sales* report over it still is.

**Exit criteria:**

- `golden_master.py` byte-identical.
- New `scripts/replay_snapshot_foundations.py` against the stock fixture. **Must include a
  test that a semi-additive measure summed across snapshots is detected and refused** — that
  test is the entire point of this work package.
- The probe run against the live inventory model correctly classifies every stock measure and
  correctly identifies the snapshot date.

---

### WP5 — Ageing report *(2 weeks — first new report, first inventory value)*

**Prerequisites:** WP4 complete; Q4 answered.

**Changes:**

1. `src/domains/inventory/buckets.py` — **ordinal bucket axis**: ordered, non-hierarchical,
   where the *order* carries meaning (0–30 → 31–60 → 61–90 → 90+). Adjacency and direction
   matter; the parent/child diversity rules do not apply and must not be reused here.
2. **Bucket-migration math** — how much value moved rightward (ageing) versus leftward
   (cleared) between snapshots, reconciling to the total change. This is the report's core
   finding and it is domain-specific arithmetic, not kernel work.
3. If Q4 says buckets must be **derived**: a bounded DAX pattern computing age from a receipt
   date against the snapshot date. **The day-count definition comes from the business document,
   not from assumption** — record it in the rulebook with the `[B]` mark. If the document is
   silent, stop and ask (Part 6).
4. `src/domains/inventory/layouts/ageing.json` + `rules/ageing_prose.json`. Compose the rule
   pack from the **existing** primitives in `summary_validation.py`; verify the deterministic
   fallback passes it (Non-negotiable 15).
5. `src/domains/inventory/reports/ageing.py` + `config/<client>/reports/inventory_ageing/`
   (`report.json` + `business_rules.md` from the Ageing document).
6. `scripts/audit_ageing.py` — an artifact auditor: bucket values sum to the total, migration
   reconciles to the change, every covered member appears in the HTML, prose figures are
   grounded, the page is self-contained and escaped.

**Exit criteria:**

- `golden_master.py` still byte-identical (Sales YoY untouched).
- New `scripts/replay_ageing.py`: bucket migration reconciles; ordinal ordering respected; a
  bucket with no prior handled as `baseline_missing`; fallback passes validation.
- One live run + `audit_ageing.py` clean + **someone who uses the existing Ageing report reads
  it and recognises it**.

---

### WP6 — Policy-band spine, change-free ranking, state novelty *(2.5 weeks, enabling)*

**Prerequisite:** Q2 answered. If no policy measures exist, apply the 1.10 fallback tree and
re-scope before starting.

**Changes:**

1. `src/domains/inventory/spines.py::SnapshotVsPolicySpine` — baseline is a band (lower =
   reorder point, upper = max stock); `delta_kind = "distance"`; `classify` returns
   `baseline_missing` when no policy is set (**excluded** — an item with no policy is not an
   exception); `denominator` is value at risk.
2. `src/kernel/ranking.py` — register `severity_exposure_persistence`: how far outside the band
   × how much value is exposed × how long it has been in that state. Reuse the existing
   normalization and winsorization primitives; do not write new ones.
3. **State novelty** in `src/tools/insight_memory.py` and `summary_memory.py`: a novelty key
   for a *state and its duration* rather than a period. Resurface rules: the state changes, the
   state escalates, or a duration milestone is crossed. Schema v5, non-destructive migration.
   **The behaviour to get right:** *"below reorder point, day 9"* must not be re-announced as
   brand new every morning, but must speak up when it worsens or clears.

**Exit criteria:**

- `golden_master.py` byte-identical.
- New `scripts/replay_state_novelty.py`: a persisting state is not re-reported daily;
  escalation resurfaces; clearing resurfaces; duration counts correctly across a gap in
  snapshots; migration is non-destructive.

---

### WP7 — Inventory Management report *(2 weeks)*

**Changes:** an `exception_list` layout (a prioritised queue, not a hero verdict); rule pack;
report spec; `config/<client>/reports/inventory_stock_health/` with `report.json` and
`business_rules.md` from the Inventory Management document; probe recognition of policy
measures; `scripts/audit_stock_health.py`.

**Exit criteria:** replay against the stock fixture; one live run audited clean; read and
confirmed by an existing user of the report.

---

### WP8 — Inventory chain with clubbed insight extraction *(1.5 weeks)*

**Goal:** one investigative report across both inventory reports, two separate summaries.
Inventory is the first chain because two reports over the same stock position is the simplest
meaningful pooling test.

**Changes:**

1. `src/kernel/chain.py` — `ChainSpec` (`chain_id`, ordered `report_ids`, shared-insight flag)
   and a runner executing reports **sequentially in one process** (Non-negotiable 2 and 1.8).
   Chain-level commit writes the chain memory once.
2. **Evidence pooling.** Each report run contributes normalized evidence to a chain-level
   accumulator; the insight branch runs once at the end over the pooled set. Every evidence
   contract gains a `report_id` field so provenance survives pooling.
3. **Per-report representation.** Extend `_backfill_uncovered` in
   `insight_signal_detector.py`: if a report in the chain has eligible material candidates and
   the LLM's response touched none, inject its single best candidate. It then competes on the
   same materiality `score` — **never ahead of it**. Do not introduce priority ordering between
   reports.
4. **Attribution in the synthesizer.** Each finding names the report and dashboard it came
   from. Add to `insight_synthesizer_prompt.md` and enforce in the rule pack.
5. `config/<client>/chains/inventory.json`.

**Exit criteria:**

- `golden_master.py` byte-identical for a single-report chain (a chain of one must equal
  today's run).
- New `scripts/replay_inventory_chain.py`: pooled evidence keeps `report_id`; a loud report
  cannot starve a quiet one; a chain of one is identical to a standalone run; chain memory
  commits once and is forward-only.
- A live chain run producing one `insight_report.md` and two `report_summary.md`, audited.

---

### WP9 — Target Tracker report *(2 weeks — first sales addition)*

**Prerequisite:** Q8 answered yes (target/budget measures exist).

**Changes:**

1. `src/domains/sales/spines.py::ActualVsTargetSpine` — baseline is a target measure;
   `delta_kind = "absolute"`; `pct` is attainment against target; `classify` returns
   `baseline_missing` for a member with no target (own bucket, never green); `denominator` is
   `overall_target`; population strategy is `has_target`.
2. `src/kernel/ranking.py` — register `variance_attainment_share`.
3. `src/domains/sales/layouts/scorecard_grid.json` + `rules/target_prose.json`.
4. `src/domains/sales/reports/target_tracker.py` + config + rulebook.
5. `services/probe.py` — recognise target/budget/plan/forecast measures as **baseline**
   candidates rather than value candidates.
6. `scripts/audit_target_tracker.py`.

**Exit criteria:** `golden_master.py` byte-identical; `replay_target_tracker.py` green; one
live run audited; a human reads the report and confirms it says something a manager would act
on.

---

### WP10 — Sales chain *(1.5 weeks)*

The chain machinery already exists from WP8, so this is mostly configuration:
`config/<client>/chains/sales.json` listing Sales YoY, Target Tracker and (if built) Daily
Sales, plus a `replay_sales_chain.py` mirroring the inventory chain replay.

---

### WP11 — Daily Sales report *(2 weeks — conditional on Q9)*

**Only if WP0 confirmed a genuine, current, calendar-day business date exists.**

A `PeriodOverPeriodSpine` at day grain; period-to-date pacing; enable the existing Phase 3/3b
daily cascade (`insight_business_day_source` → `insight_recent_week` → `insight_daily`), which
is already built and currently self-disabled by the data; a compact daily layout; report spec,
config, rulebook, auditor.

**Note:** most of this report's machinery already exists and is switched off by the data, not
by the code. If Q9 is yes, this is mostly configuration and a layout. If Q9 is no, **do not
build it** — say the model needs a business-date column.

---

## PART 5 — Testing strategy

| Layer | Tool | When |
|---|---|---|
| No regression in existing reports | `scripts/golden_master.py` | Every commit, every WP |
| Component logic | `scripts/replay_all.py` | Every commit |
| Kernel correctness | `replay_kernel_spine.py`, `replay_domain_assembly.py`, `replay_report_scoping.py` | Every commit |
| **The dangerous cases** | `replay_snapshot_foundations.py`, `replay_state_novelty.py` | Every commit |
| Per-report logic | `replay_ageing.py`, `replay_target_tracker.py`, … | Every commit |
| Delivered artifact | `audit_ageing.py`, `audit_stock_health.py`, … | **After every live run** |
| Human judgement | A user of the existing report reads the new one | Once per new report |

Two disciplines from the current codebase that must carry over:

- **Replays prove the code is right; auditors prove a produced artifact is right.** Both are
  needed. The auditor is what caught the two real bugs.
- **Every deterministic fallback is itself tested against strict validation**, so validation
  can never dead-end and leave a run with nothing to publish.

All replays are offline: no auth, no LLM, no network. If a new test needs a live connection,
the design is wrong — add a fixture.

---

## PART 6 — Stop-and-ask points

Do not guess at any of these.

1. **The spike in 1.7 fails.** The plan changes materially. Stop and re-plan.
2. **Any Q1–Q7 answer is unclear after probing.** Especially Q2 and Q4 — a fabricated policy
   band or bucket definition produces a report that looks right and is wrong.
3. **The golden master shows a difference in WP1, WP2, WP3, WP4 or WP6.** These must not change
   behaviour. A difference means the refactor changed arithmetic. Revert and diagnose; **do not
   adjust the expected values.**
4. **A business document is silent on a definition** the report needs — how a day of ageing is
   counted, what "cover" divides by, whether a policy band is per store or global, whether a
   target is monthly or cumulative. Ask, then record the answer in the rulebook with the `[B]`
   mark.
5. **A required measure does not exist in the model.** That is a Power BI change, not a code
   change. Say so; do not synthesise it from something adjacent. In particular, **never infer a
   policy band from observed averages** (1.10).
6. **A level's parts do not add up to its whole.** Hard stop, as today. Do not publish it.
7. **Semi-additive verification fails on a measure the report needs.** Stop. This is the
   30×-too-big failure and it is invisible downstream.
8. **The report would ship with no charts, no covered members, or an empty section** and the
   reason is not stated. The existing product's rule is to state the limitation, not to render
   blank.

---

## PART 7 — Definition of done

1. `golden_master.py` byte-identical for Sales YoY, from WP1 through WP11.
2. Four to five reports run: Ageing, Inventory Management, Sales YoY, Target Tracker, and
   Daily Sales (or a recorded reason it cannot be built).
3. Two chains run: Inventory (two reports, one shared investigative report) and Sales.
4. Every report has a rulebook following the standard template, with every rule marked
   checked / business decision / assumption.
5. Every report has an offline replay **and** an artifact auditor, both green.
6. Adding a further report of an **existing** kind requires **no `.py` change** — demonstrate
   it.
7. `CLAUDE.md` and `AGENTS.md` updated, identical, describing the domain/chain/kernel
   structure with the same specificity they currently describe R1–R6.
8. `scripts/replay_config_schema.py` green — every new setting catalogued with plain-language
   label, help, detail and tier.
