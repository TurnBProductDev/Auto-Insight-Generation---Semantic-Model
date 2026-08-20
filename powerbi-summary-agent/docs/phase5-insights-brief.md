# Phase 5 — multi-report insights: implementation prompt

Copy everything below the line into a new chat to start implementation.

---

You are working on the **Auto Insights Generation** repo (`powerbi-summary-agent/`). Read
`CLAUDE.md` first — it is long but it is the map, and its "Non-negotiables" and the WP0–WP9
sections carry findings that will save you from re-deriving them.

## What you are building

The KPI insight/alert feed currently carries findings from **one** report. Four reports now
exist. Make the insight pipeline produce and publish insights from all of them, with each
insight carrying the report it came from.

**Do not break the existing Sales YoY insight output.** It is in production and its cards
are what the app renders today.

## Verify before you trust

Every claim below was verified on 2026-08-18 against the live models and the live blob
account. Re-check anything you are about to depend on — the repo's own rule is that a
figure you did not measure is a figure you do not have. Live Power BI auth works from the
cached MSAL token at repo-root `.pbi_token_cache.json`; `POWERBI_TENANT_ID` must be set or
read from the config.

## Current state

| Report | Runs via | Dataset | Client | Summary | Insights |
|---|---|---|---|---|---|
| Sales YoY | `python -m src.main` (LangGraph) | `b3458a38…` | cityflower | yes | **yes** |
| Sales YoY (scanb) | `python -m src.main --config config/scanb/config.json` | `643336e7…` | scanb | yes | **yes** |
| Target Tracker | `scripts/run_target_tracker.py` | `f34c5654…` | cityflower | yes | **no** |
| Stock Age Analysis | `scripts/replay_ageing.py` / saved scan | inventory model | — | yes | **no** |
| Inventory Management | `scripts/replay_stock_health.py` / saved scan | inventory model | — | yes | **no** |

The insight branch only exists inside the LangGraph. The three newer reports are
deterministic scan → model → render pipelines that never enter it.

## Problem 1 — the KPI feed has no report identity

```
ai-content/report-summaries/client/{report_id}.{json,html}   ← per report, safe
ai-content/kpi/client/insights.json                          ← ONE per client
ai-content/kpi/client/alerts.json                            ← ONE per client
```

`KpiCard` in `src/tools/api_payloads.py` has fields `id, severity, category, metric, value,
delta, deltaDirection, description, displayTime, isoDate, comparisonLabel, insight`. There
is **no report id on the card**, and `model_config = ConfigDict(extra="forbid")`.

So two reports in the same client container overwrite each other's feed, and nothing
downstream can tell which report a card came from.

**The agreed approach is to put the report id on each card.** Design the exact shape, but
it must let one feed carry cards from several reports and let a consumer filter by report.

### Trap: `merge_alerts` will silently drop the other report's cards

`src/tools/ai_content_publisher.py::merge_alerts(previous, today, run_date, days)` keeps
previous cards whose date **≠ run_date**, then appends today's. If Sales YoY publishes and
then Target Tracker publishes on the same day, the second run discards the first run's
same-day cards. The seven-day retention has the same problem across reports.

Fix the merge to be report-aware: a run replaces only *its own* report's cards for that
date. `_upload_alerts` already does etag optimistic concurrency with three retries, so the
write race is handled — this is a semantic bug, not a concurrency one.

## Problem 2 — the detectors assume a year-on-year spine

`insight_stat_detector` is built around current/prior/change triples. Two of the three new
reports cannot supply that:

- **Target Tracker** holds **2026 only**. Columns `LY_SALES`, `LY_SAME_DAY_SALES`,
  `LYLY_SALES` do not exist; ~30 model measures referencing them **fail at query time**.
  Its comparison is actual vs **target**.
- **The two inventory reports** hold **one snapshot** (a single `UPDATED_ON` value), so
  there is no prior state to difference against. Their comparison is stock vs **policy**.

`src/kernel/spine.py` already names this: `PeriodOverPeriodSpine` (sales) and
`SnapshotVsPolicySpine` (inventory) exist, with `delta_kind` including `distance` and
separate `delta_unit` / `exposure_unit`. **Target Tracker has no spine yet — write one**
(`TargetVsActualSpine`), and route detection through the spine rather than adding a branch
to the existing detector.

`src/kernel/state_novelty.py` already exists for the change-free case: novelty anchored on
a **state** rather than a period, re-reported when the state changes, materially worsens,
or crosses a duration milestone (7/14/30/60/90 days). Use it for inventory.

## Reuse WP8 rather than reinventing it

`src/kernel/chain.py` was built for exactly this and is already tested:

- `tag_evidence(items, report_id, dataset_id)` — stamps provenance without mutating the source
- `fair_share(candidates, …)` — guarantees every contributing report a slot **before** the
  list is truncated. The slot must be reserved first; appending then truncating by score
  discards the quiet report every time, because an injected candidate is by definition the
  weakest thing in the list.
- `uncovered_reports(...)`, `attribution(finding, ...)` → "From Stock Age Analysis."
- `run(spec, ...)` — runs a chain's reports **sequentially in one process**, because
  `get_powerbi_token()` does an unlocked read-modify-write and `commit_run` takes a
  best-effort lock. Do not parallelise reports.

`scripts/run_inventory_chain.py` already produces a pooled artifact from both inventory
reports into `outputs_inventory_chain/insight_inventory_chain.{md,json}`. It is local only
and is not published — that is a useful starting point, not a finished path.

Memory scoping is already correct and must not regress: summary memory is **per report**
(`<dataset>/reports/<report_id>/memory.json`), insight memory is **per chain**
(`kernel/scoping.chain_dir` — deliberately *not* nested under a dataset, because the two
inventory reports live in different models and the one chain must share one store).
`insight_memory.story_key` includes the dataset, so a finding in one model stays distinct
from a finding in another.

## The work

Break this into packages and get each one's exit criterion green before starting the next.
Propose the split yourself; a reasonable shape is:

**P5.1 — report identity on the card.** Add the report id to `KpiCard` (mind
`extra="forbid"` on both sides of the wire), thread it from the signal through
`_assemble_kpi_card`, make `merge_alerts` report-aware, and decide whether `id: int` stays a
per-run sequence or becomes stable. Exit: the existing Sales YoY run publishes an unchanged
card set apart from the new field, and a synthetic two-report merge keeps both reports'
same-day cards.

**P5.2 — a target-vs-actual detector.** `TargetVsActualSpine` plus detectors that produce
findings this data actually supports: a run of consecutive days below target, a branch
below target across every period, the catch-up requirement crossing 100%, a month's surplus
being spent at a rate that exhausts it before month end, a department below target while
its parent is above. Reuse `src/domains/sales/target_tracker.py` — it already computes all
of these deterministically; the work is turning them into scored signals, not recomputing
them. Exit: Target Tracker emits ranked signals offline from a committed scan.

**P5.3 — state-based detectors for inventory.** Wire `state_novelty` to the ageing and
stock-health models so an exception is reported when it appears, worsens, clears, or hits a
duration milestone. Exit: two consecutive synthetic runs produce a sensible
appear → persist → clear sequence with no duplicate reporting.

**P5.4 — pooling and publish.** Run the reports, tag and pool their candidates through
`fair_share`, and publish one feed per client carrying cards from several reports.
Exit: `cityflower/ai-content/kpi/client/insights.json` holds cards from both Sales YoY and
Target Tracker, each attributable, with neither overwriting the other.

## Non-negotiables

1. **Never invent a cause.** No model here holds promotions, stock movement, staffing,
   weather or footfall. State where and how large, never why.
2. **No prior-year comparison for Target Tracker.** The data does not exist.
3. **Every figure in a card must exist in the evidence and be rounded.** Grounding alone is
   not sufficient — see the next point.
4. **Check claims against the figures, not just the figures.** A live authored draft wrote
   "No branch missed today" while a branch sat at 91.3% of target. Every number was real;
   the claim was false. `src/domains/sales/target_tracker_author.py::validate` shows the
   pattern: assertions derived from the model, not only figure lookup.
5. **The LangGraph concurrency contract** (CLAUDE.md): one writer per state key per
   superstep, `logs`/`errors` are reducer-backed, no post-fork node may call
   `get_powerbi_token()`, and `save_outputs` is reached only through the joined barrier.
6. **Plain language.** The audience has no retail or analytics background. See
   `config/targettracker/summary_business_rules.md` §5 for the banned-vocabulary table.

## Verification

The commit gate is both halves, offline, ~30s:

```
python scripts/replay_all.py      # discovers scripts/replay_*.py by glob; a new replay joins automatically
python scripts/golden_master.py   # must stay byte-identical
```

Add a replay for every new detector, and extend `scripts/audit_*.py` for anything that
produces an artifact. Mutation-test what you add: an auditor that passes everything is
worthless — corrupt a figure and confirm it fails with a precise message.

Two failures already in the repo's history that you should not repeat: a golden-master
snapshot that embedded a generation date and went red on the calendar rather than on a code
change; and layout faults on a page whose every number was correct, invisible to string
assertions. **Render pages and look at them** —
`chrome --headless=new --disable-gpu --no-sandbox --screenshot=out.png --window-size=1500,2400 file:///<abs path>`.

## Decide these before writing code

1. **Can the app tolerate a new field on the KPI card?** `KpiCard` is `extra="forbid"` on
   our side; if the consumer is equally strict, adding `reportId` is a breaking change and
   needs coordinating. Ask, do not assume.
2. **One feed with report-tagged cards, or a feed per report?**
   (`kpi/client/insights.json` with a `reportId` field, versus
   `kpi/client/{report_id}/insights.json`.) The first needs no new app path but changes the
   card contract; the second is additive but needs the app to know where to look. The
   decision was leaning toward the first — confirm it.
3. **How many cards should a client's feed carry, and how are they shared between reports?**
   `insight_max_new_per_run` currently caps one report's output. With four reports the cap
   is a budget to divide — `fair_share` exists for this, but the total is a product call.
4. **Do the inventory reports publish to a client container at all today?** They currently
   write local artifacts only. Publishing them is in scope for the feed but may need a
   client/report-id mapping that does not exist yet.

Ask these before implementing. Where a question is genuinely blocking, stop and ask rather
than assuming — a wrong assumption here produces a report that looks right and is wrong.
