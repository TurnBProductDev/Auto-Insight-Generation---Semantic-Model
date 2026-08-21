# Prompt — make the Inventory pipeline produce a daily AI summary, alerts and insights

Paste everything below the line into a fresh chat in this repository. It is written to be
self-contained: it states what exists, what is missing, what is authoritative, what is
forbidden, and how the work will be judged.

---

## Your task

Bring the **Inventory Management** report to the same end-to-end daily footing the
**Target Tracker** report already has: a scheduled run that scans the live semantic model,
builds a deterministic model, writes an LLM-authored but deterministically-validated
summary page in the approved format, emits ranked KPI alert cards into the shared insight
feed, and publishes to blob storage.

Work in `powerbi-summary-agent/`. Read `CLAUDE.md` first — it is the repository guide and
its non-negotiables (especially the concurrency and token rules) override anything here.

## The three authoritative sources

1. **`C:\Users\TURNRETAIL\Downloads\business_rules_Inventory.md`** — the authority for KPI
   names, inventory classifications, definitions and business language. BR-03 is the
   terminology table; BR-31 is the fourteen Recommended Action states; BR-08 defines the
   measures. **These rules win** over the agent's normal phrasing.
2. **`docs/dashboard-reference/reference_inventory_management_standardised.html`** — the
   approved output format, carrying the real live figures as at 19 Aug 2026. This is the
   design target for the generated page.
3. **`docs/dashboard-reference/README.md`** — explains why that page is shaped as it is,
   the terminology decisions, the rule conflicts already resolved, and a numbered gap table
   between the reference and what `src/domains/inventory/dashboard_html.py` currently emits.

Do not invent terminology or layout decisions that these three already settle.

## What already exists (verified, do not rebuild)

| Piece | Where | State |
|---|---|---|
| Deterministic model from a scan | `src/domains/inventory/reports/stock_health.py::build`, `.../ageing.py::build` | Working, pure functions |
| Page renderers | `src/domains/inventory/dashboard_html.py`, `ageing_html.py`, `charts.py` | Working; 16 gaps vs the reference |
| Ordinal age buckets | `src/domains/inventory/buckets.py` | Working |
| Inventory spine | `src/domains/inventory/spines.py::SnapshotVsPolicySpine` | Working |
| Inventory vocabulary | `src/domains/inventory/families.py` | Working |
| Chain runner + pooling | `src/kernel/chain.py`, `scripts/run_inventory_chain.py` | Working, but **offline over saved scans** |
| State novelty (no period) | `src/kernel/state_novelty.py` | Written, unused by inventory |
| Replays | `scripts/replay_ageing.py`, `replay_stock_health.py`, `replay_inventory_chain.py` | Passing |
| Artifact auditors | `scripts/audit_ageing.py`, `audit_stock_health.py` | Passing |
| Chain config | `config/chains/inventory.json` | Exists — **but see the discrepancy below** |

## What is missing (this is the work)

The gap is best understood by diffing against Target Tracker, which does all of this today.
Read `scripts/run_target_tracker.py` end to end before writing anything — it is the
template, and copying its shape is the intended solution.

| Stage | Target Tracker (works) | Inventory (missing) |
|---|---|---|
| Live scan | `target_tracker.scan(execute, ...)` | **No live scan exists.** `build()` takes a saved scan dict; the committed scans have no provenance and were produced ad hoc. |
| LLM prose + validation | `target_tracker_author.py` — authors 4 slots, validates, one repair, deterministic fallback | **None.** Inventory prose is hard-coded in `_narrative()`. |
| Ranked KPI signals | `target_tracker_signals.py::detect` | **None.** Phase 5.3 was deferred. |
| KPI feed cards | `api_payloads.generate_kpi_insights_payload` + `ai_content_multi_report_feed` | Not wired for inventory. |
| Blob publish | `target_tracker_publish.py` | **None.** |
| Per-report config | `config/targettracker/config.json` + `summary_business_rules.md` | **No `config/inventory/` exists.** |
| Daily runner | `scripts/run_target_tracker.py` | Only `run_inventory_chain.py`, which is offline. |

## Facts you will need, already verified against the live model

- Report `ea29c0ea-2b15-4b29-b506-82afa92b4240`, dataset
  **`16d47b06-f48c-4a50-9d61-3fc91791ad73`**, workspace
  `2829a4af-2e07-4b43-b913-0a829a06bef4`. The Ageing report in the same workspace is
  dataset `3cd81c72-585b-4be9-9c8c-c56235c577b6`.
- **`config/chains/inventory.json` is stale.** It names datasets `84212fd9-…` and
  `64eefa4b-…`, which are not the datasets above. Resolve which environment is current
  before wiring anything, and fix the config rather than working around it.
- The model implements the Retail Inventory Health Score exactly as documented:
  `_HEALTH SCORE MEASURES` publishes `Inventory Health Score` (58.5 today), built from six
  risks each capped at 25 points, each rebuilt from Value Impact / SKU Breadth / Duration
  or Severity weighted 50-30-20 (70-30 for Damage). All six reconcile to the published
  score.
- `LOC_CATEGORY_HEALTH` and `P90 CATEGORY STORE` carry **no relationships**. Slicing the
  score by `LOC_CATEGORY_HEALTH[DEPARTMENT]` returns the company total. Every roll-up must
  be built from `REP_SSR_STOCK_STATUS_REPORTV2`, which propagates correctly.
- **`LOC_CODE` is a display alias; `locsku` embeds the real location code.** `ST1…ST5` map
  to `CFH014, CFH017, CFH018, CFH021, CFH022` and `WH1/WH2` to `CDC010/CFW001`. Anything
  that surfaces `locsku` — a drill-through, an evidence row, a SKU detail table — will leak
  the real codes into published output. Treat that as a defect.
- `ST5` is `CFH022`, which `config/targettracker/config.json` already excludes from its
  population. It is winding down: stock fell 815,718 → 62,478 since 1 June, it carries no
  Excess Stock and no Non-Moving Stock, and its Out of Stock risk sits at the 25-point cap.
  That is expected, not an availability failure.
- `ST3` is `CFH018`, the nearby store, which BR-18 gives shorter Lead Days. That changes
  its On the Verge of Stockout trigger.

## The snapshot-history problem, and how to solve it

`docs/phase5-inventory-deferred.md` blocks Phase 5.3 on two preconditions. Re-checked on
the live model today:

- **Blocker 1 — more than one retained snapshot: STILL FAILING.** `UPDATED_ON` has exactly
  one distinct value (2026-08-19). The semantic model replaces rather than retains.
- **Blocker 2 — durable item identity: PASSING.** `locsku` is `LOC_CODE + sku_code`, a
  business key, not a regenerated surrogate.

**Do not wait for the model to retain history.** The pipeline can retain its own: archive
each day's scan to a dated file and compare today against the most recent archive. That
unblocks day-over-day alerts, state novelty (appeared / persisted / cleared) and the "up
from…" phrasing, without any change to Power BI. Design for this from the start:

- write `scan_YYYY-MM-DD.json` alongside the current scan on every run;
- on day one there is no prior, so the page must degrade honestly — the reference already
  shows how, with a dashed shape-only line and an explicit "no past values are implied";
- never fabricate a prior. If there is no archive, say so and omit the comparison.

## What to build, in order

Each step has an exit criterion. Do not start a step before the previous one passes.

**1. `config/inventory/`** — `config.json` plus `summary_business_rules.md` (a copy of
`business_rules_Inventory.md`, which `file_io.read_business_rules` resolves as a sibling of
the config). Mirror `config/targettracker/config.json`. It must set `report_id`,
`report_name`, `report_domain: inventory`, `report_cadence: daily`, `chain_id: inventory`,
the workspace/dataset ids, `output_folder`, `ai_content_client`, `ai_content_report_ids`,
and a **distinct `azure_blob_prefix`** — Sales YoY uses an empty prefix in the same
container and an inventory run with no prefix would overwrite its `api/*.json`.
*Exit: `python scripts/replay_config_schema.py` passes; every key is catalogued.*

**2. A live scan.** Add `scan(execute, cfg, log)` to
`src/domains/inventory/reports/stock_health.py`, shaped like `target_tracker.scan`. It must
produce exactly the dict `build()` already consumes, so the existing replays and auditors
keep working unchanged. Bounded, `TREATAS`-scoped, validator-gated, using the pre-fetched
token. Archive the dated copy here.
*Exit: `stock_health.build(scan(...))` equals the committed model for the same as-at date;
`replay_stock_health.py` still passes.*

**3. Bring the renderer up to the approved format.** Work the numbered gap table in
`docs/dashboard-reference/README.md`. The reference is six tabs — Overview, Inventory Health
Score, Where to focus, Locations, Divisions, Recommended Actions — in two views.
*Exit: the generated page and the reference agree on structure; render it headless and look
at it, because layout faults do not surface in tests.*

**4. LLM prose with deterministic validation.** Copy the `target_tracker_author.py` shape:
the model fills a small number of named prose slots and nothing else — it cannot add a
section, drop a tab, choose a chart or reorder the page. Validation must reject, at minimum:
a figure not present in the model; more than one decimal place; any BR-03 banned synonym;
any BR-33 jargon (`velocity`, `carry cost`, `coverage ratio`, `materiality`, …); an asserted
cause; a comparison with no number (BR-33); and any of the excluded client-specific content
below. One repair attempt, then the deterministic fallback — and assert the fallback itself
passes validation, so strict validation cannot dead-end.
*Exit: a new replay covering every rejection as a named test, plus a clean draft passing and
the fallback passing.*

**5. KPI alerts and insights.** Add `src/domains/inventory/stock_health_signals.py`,
shaped like `target_tracker_signals.py`. It **recomputes nothing** — it reads the model
`build()` already produced. Candidate detectors, all grounded in the rules:
   - a **double-warning** Recommended Action state (BR-31): `NON MOVING - ORDER PLACED`, and
     `STOCK OUT - PLACE ORDER` — report these first;
   - **Unwanted SKUs** (BR-28): in Pending Orders *and* carrying Excess Stock;
   - Excess Stock Value crossing a material share of Stock Value (BR-34: only report what is
     big enough to matter);
   - Non-Moving Stock moving into the `>180` bucket (BR-25);
   - Out of Stock among **Critical SKUs** (BR-07) with its Opportunity Loss (BR-16 — an
     estimate, stores only, never for a warehouse or an OVERSEAS SKU);
   - a Damage Value spike against the monthly trend (BR-29);
   - once an archive exists: a state that **appeared**, **persisted past a duration
     milestone**, or **cleared** — via `src/kernel/state_novelty.py`.

   Score every signal as **exposure-weighted share**, not raw magnitude, so a large
   percentage on a trivial slice cannot outrank a small percentage on a large one. Every
   signal must carry an explicit `comparison_label`; without one it falls through
   `_assemble_kpi_card` to the share branch and publishes against "the prior period", which
   this snapshot data does not have.
*Exit: a replay pinning the ranking order and asserting every signal passes the prose guards.*

**6. Publish.** Reuse `ai_content_publisher.publish_kpi_feed` — it is the single
implementation and is already report-aware. Confirm `ai_content_multi_report_feed` handling:
with it off the payload must stay byte-identical to what the app renders today, and with it
on each card must carry `reportId` and a `stable_card_id`, or two reports will emit
duplicate ids and the feed will mis-render.
*Exit: `python scripts/replay_multi_report_feed.py` passes with inventory added.*

**7. Schedule it.** Follow the container/job path the other reports use.

## Non-negotiables

- **Terminology is BR-03, everywhere.** SKU (never product or item), Loc-SKU for one SKU at
  one Location, Store, Location, Division (never Department), Section, Stock Value, Excess
  Stock (never overstock or surplus), Non-Moving (never dead stock), Burn-Out Days,
  Opportunity Loss, Pending Orders, Damage, Transfer, Critical SKU. Recommended Action state
  names appear **in full and never abbreviated** (BR-31). Where the health-score model's own
  measure name differs — it calls Non-Moving "Dead Stock" — use the business term and state
  the clash rather than hiding it, as the reference does.
- **BR-08 separates `#SKUs` from `#Loc-SKUs`.** 120,897 rows are Loc-SKUs covering 44,504
  distinct SKUs. Say which one every count is. Where a classification is reported across
  Locations, BR-26 requires unique SKUs.
- **Exclude client-specific content** from anything published: Saudi/SAR/riyal references,
  the seven location codes, the nine named Divisions and the named Sections from the rules
  document, the lead-day and excess-threshold tables, and the buying team's name. The rules,
  definitions and vocabulary are carried over; the client's data is not. The page reads
  Location, Division and Section names from the semantic model, which is correct.
- **Currency is USD** and is currently hard-coded as SAR in `ageing_html.py`, `charts.py`
  and `buckets.py` (`HIGH_RISK_CALL_OUT_SAR`). Make it a config key, as
  `target_tracker_currency` already is.
- **Never fabricate history.** No "up from…" without an archived prior.
- **Concurrency:** `get_powerbi_token()` does an unlocked read-modify-write and
  `commit_run` takes a best-effort lock. Reports in a chain run **sequentially in one
  process**. Never let a post-fork node call `get_powerbi_token()`.
- **Do not modify** `reference_inventory_management.html`,
  `reference_inventory_management_standardised.html`, or their builders and auditors. They
  are the design target and must stay reproducible.

## How this will be judged

1. `python scripts/replay_all.py --with-golden` passes — this is the commit gate, and
   `golden_master.py` byte-identical is what proves no arithmetic moved.
2. New replays exist for the author, the signals and the scan, and each rejection is a
   named test.
3. `python scripts/audit_stock_health.py <output_dir>` passes on a **produced** artifact,
   not just on the code.
4. A terminology check asserts both directions: banned synonyms absent, **and** the approved
   names plus all fourteen BR-31 state names present — so "standardise" cannot silently
   become "delete the vocabulary".
5. The page has been **rendered and looked at**. Layout faults are invisible to tests:
   `chrome --headless=new --screenshot=out.png --window-size=1500,2500 "file:///…#all/overview"`

## Start here

Before writing code, report back with: the resolved dataset discrepancy in
`config/chains/inventory.json`; a confirmation of whether the Ageing report is in scope for
this work or whether Inventory Management goes first alone; and your proposed
`config/inventory/config.json`. Ask about anything the three authoritative sources do not
settle rather than guessing — a fabricated threshold or classification produces a report
that looks right and is wrong.
