> ## 🚀 KICKOFF PROMPT — paste this as your first message to the new chat
>
> You're working in the `powerbi-summary-agent` repo. **Read this entire file
> (`PHASE_ROADMAP.md`) and `CLAUDE.md` first**, then implement **Phase 3 — daily
> anomaly incidents** exactly as specified in §3. Phases 1–2 are DONE and must keep
> working; respect every guardrail in §5. Build it behind the temporal grain gate,
> prove each deterministic piece with **synthetic offline fixtures** in
> `scripts/replay_stat_detector.py` (no live run is needed to validate the logic),
> and confirm the gate correctly keeps the daily level **DISABLED** on the current
> dataset — its only day column `UPDATED_DATE` is a batch/load date, so daily
> analysis on it is invalid by design. Keep `CLAUDE.md` and `AGENTS.md` identical and
> updated. **Show me your implementation plan before writing any code.**

---

# Layered Insight Agent — Phase Roadmap & Phase 3 Implementation Guide

> Hand this whole file to a fresh chat. It is self-contained: it explains the repo,
> what Phases 1–2 already built, the **detailed Phase 3 plan to implement**, and the
> guardrails to respect. Your job (new chat) is **Phase 3**; Phases 1–2 are DONE and
> must keep working; Phase 4 is described for context only.

---

## 0. Orientation

**Repo:** `powerbi-summary-agent/` — a LangGraph + LangChain multi-agent pipeline that
reads a Power BI semantic model, auto-generates DAX, and writes two reports per run:
`report_summary.md` (*what* the numbers are) and `insight_report.md` (*why*). Two
branches (summary + insight) run concurrently and re-join at `save_outputs`.

**Run it (from the project dir):**
```
cd powerbi-summary-agent
python -m src.main                 # full live run (needs auth + LLM); ~3 min
```
Auth is headless MSAL with a cached refresh token (`repo-root/.pbi_token_cache.json`) —
already set up; runs are silent. Post-fork nodes must NOT fetch tokens; they use
`state["pbi_token"]`.

**Deterministic components are offline-testable (no auth/LLM):**
```
python scripts/replay_stat_detector.py        # stat detector, incl. Phase 2 period fixture
python scripts/replay_novelty_filter.py        # memory + novelty filter
```
Always add offline replay coverage for new deterministic logic — that is the primary
test surface. A full live run is the acceptance test.

**Read `CLAUDE.md` / `AGENTS.md` at repo root** — they are the authoritative
architecture docs and are kept identical. Update BOTH when you change behavior.

---

## 1. The insight branch (what your work plugs into)

Node order (insight branch), after the fork:
```
insight_normalize → insight_temporal → insight_evidence_catalog → insight_stat_detector
  → insight_novelty_filter → insight_signal_detector → insight_evidence_assembler
  → insight_gap_scan → insight_investigator → insight_synthesizer → insight_branch_done
```
Key idea: **deterministic detection happens BEFORE the LLM.** The LLM only *selects and
phrases* from a pre-computed, pre-filtered candidate list.

### Cross-run memory (Phase 1) — `src/tools/insight_memory.py`
- One JSON store per dataset: `insight_memory/<dataset_id>/memory.json`
  `{schema_version, watermark, records{story_key→record}, journal{day→entries}}`.
  Written atomically (temp file + `os.replace`). `daily_insights.md` is derived from it.
- **`story_key`** = stable, level-prefixed SHA-256 of canonical JSON that **excludes
  mutable fields** (direction, impact, episode_end) so Phase 4 can re-alert without the
  key changing. Built by `story_components(candidate, dataset_id, scope_hash, contract,
  period_anchor)`. **It currently has two branches: `high` and `period`. Phase 3 must add
  a `daily` branch** (see §3.4).
- `suppressed(records, policy, cooldown_days)` — `never_repeat` (default) or `cooldown`.
- `commit(state, reported_signals)` — upserts only reported signals, marks ALL
  `covered_story_keys` (merged candidates) seen, merges `journal[today]` by story_key,
  advances `watermark`.

### Cascade levels
Findings are tagged a **level**: `high` (current-vs-prior by dimension), `period`
(Phase 2 sub-annual), `daily` (Phase 3 — you). The novelty filter caps eligible
candidates **per level** and the signal detector fills the run's slots in priority order
**high → period → daily** (`_LEVEL_RANK = {"high":0, "period":1, "weekly":1, "daily":2}` in
`insight_signal_detector.py` — `weekly` is a legacy alias for the `period` tier).
- `insight_novelty_filter.py::_level_for(candidate, contract)` maps a candidate's scan
  `coverage_kind` to its level. **`daily`* coverage_kinds already map to the `daily`
  level** — scaffolding is in place; you just need to produce daily candidates.
- Per-level candidate caps: `insight_candidates_{high,period,daily}` (daily cap already
  wired in `_cap_for` and the stat detector's `level_caps`).

### Temporal grain gate (Phase 2) — `src/agents/insight_temporal.py`
Runs before the evidence catalog. Judges each time axis and, if valid, appends one series
scan to `insight_clean_data` so it flows through the catalog + stat detector. **This is
the file you extend most for Phase 3.**

---

## 2. Phases 1 & 2 — DONE (do not break)

- **Phase 1 (memory):** each run surfaces only findings not reported before; capped at
  `insight_max_new_per_run` (default 3). Verified by `replay_novelty_filter.py`.
- **Phase 2 (period/monthly level):** the gate validates a business time axis and scans a
  `period_series`; `insight_stat_detector.period()` emits reconciled `%`-of-change month
  movers with human labels ("October, 37%"), a bounded **drill** by the metadata primary
  dimension ("concentrated in LED TV"), and patterns (`period_sustained_decline/growth`,
  `period_reversal`, `period_value_volume_divergence`). Verified by the period fixture in
  `replay_stat_detector.py`.

### ⚠️ The load-bearing data fact
On the working model, the only day-grained column `UPDATED_DATE` is a **load/posting
date, not business activity** (a single month-end bucket holds >50% of revenue). The gate
**correctly rejects it** and uses the month column `DOC_MONTH` instead. **Therefore Phase 3
(daily) will stay DISABLED on this dataset** — and that is correct behavior. Phase 3 must
be built + tested with **synthetic offline fixtures**, and it must *only* activate when a
genuine clean business-day axis exists. Do not force daily analysis onto `UPDATED_DATE`.

---

## 3. PHASE 3 — Daily anomaly incidents (IMPLEMENT THIS)

**Goal:** when a genuine business-**day** axis exists, answer *"which exact days were
abnormal?"* — e.g. *"revenue on 2024-03-14 fell 45% below the trailing norm; a 3-day dip
Mar 14–16."* Feed the same memory/novelty/cascade as `daily`-level findings. On models
without a clean day axis (like the current one), it self-disables via the gate.

### 3.1 Grain gate: detect & validate a business-DAY axis (`insight_temporal.py`)
The gate already: judges date axes for batch/load concentration using the metadata
**primary value metric**, detects grain, excludes nulls, reconciles vs the grand total,
caps probes (`insight_temporal_max_probes`), honors `insight_temporal_grain_column`.

Add: when a **date-category** axis **passes** the batch test (i.e. it is NOT a
load/posting date), treat it as a candidate **daily** axis and build a `daily_series`
scan (below). Validate it with day-specific checks before trusting it:
- **Business-activity, not load-time:** reject if one period-boundary bucket dominates
  (already have `_max_bucket_share` vs `insight_temporal_batch_share`).
- **Adequate daily density / sensible missing dates:** enough distinct days over the
  window; not mostly-empty.
- **Month-end buckets don't carry consolidated monthly totals** (same batch check).
- **Weekday comparisons are semantically valid** (both weekdays and weekends present, so
  same-weekday baselines mean something).
Emit the verdict + checks into `insight_temporal_verdict.json` (extend the existing dict);
if no valid day axis, leave the daily level disabled (the report already carries a caveat).

### 3.2 Daily series scan (`insight_scan_templates.py`)
Add `build_daily_series_scan(profile, state, day_dim)` — mirror the existing
`build_temporal_scan` (which produces `period_series`) but:
- group by the **day** column, over the last `insight_daily_days` **complete** days
  (default ~84; a `TOPN` wrap keeps rows bounded and satisfies the row-limit validator —
  see how `build_temporal_scan` uses `TOPN`).
- comparable-population filtered (reuse `_population_filter`).
- carry `contract_hint` with `coverage_kind: "daily_series"` and the full
  current/prior/change metric bundle (reuse `_metric_specs`, `_contract`).
- **Exclude today if the refresh is incomplete** (`insight_daily_exclude_today`): drop the
  latest date when it is the data max and looks partial.
The temporal node executes this scan (via `state["pbi_token"]`), validates it, and appends
the table to `insight_clean_data` exactly like it does the `period_series` today.

### 3.3 Daily detection (`insight_stat_detector.py`)
Add a `daily(self, t)` method that runs only when `t["contract"]["coverage_kind"] ==
"daily_series"` (mirror the structure of the existing `period()` method):
- For each recent day, compute a **robust z-score** (median/MAD — reuse the existing
  `_robust_z` helper) of the day's primary value against BOTH:
  (a) a trailing **rolling median** (e.g. last 28 days), and
  (b) the **same weekday's** median over the window (handles weekend seasonality).
  Flag a day as abnormal only if it clears `insight_stat_z_cutoff` on the robust measure —
  never raw % swings.
- **Incident grouping:** merge consecutive abnormal same-direction days into ONE incident
  `{episode_start, episode_end, peak_z, cumulative_impact}`. This is the key step — a 3-day
  dip must be ONE candidate, not three.
- Emit `daily_incident` candidates: `metric`, `segment`/`anchor = episode_start` (RAW ISO
  date; keep it raw for the fingerprint), a human detail, `impact_value = cumulative`,
  `impact_share` if it reconciles, and `episode_end` as a field (mutable — for Phase 4).
  Set the candidate's `table` to the `daily_series` query name so `_level_for` tags it
  `daily`. Keep each incident a distinct `_add` key (episode_start differs).
- Optionally reuse the Phase-2 **drill** idea: attach a bounded primary-dimension
  breakdown of the worst incident ("the Mar-14 dip was concentrated in [segment]").

### 3.4 Daily story_key + recency (`insight_memory.py`)
Add a `daily` branch to `story_components` (next to `period`):
```
daily canon = {level:"daily", dataset, scope, metric, segment, anchor: episode_start}
```
`anchor = episode_start` is the stable identity → a new incident (new start date) is a
new story; the SAME incident re-scanned is suppressed; an incident that *extends* keeps
its key (its `episode_end` moves — that's Phase 4's re-alert trigger). Direction, impact,
`episode_end` stay **out** of the key (mutable record fields).

**Recency gating (important):** scanning ~84 days would otherwise dump a backlog of old
anomalies that then rotate as fake "new" insights. Use the stored `watermark` (max
business date at last commit): a daily incident is eligible only if it **touches
post-watermark dates** OR **ends within `insight_daily_recent_days`** (default 3). On the
first run (no watermark), seed it to `max_date − recent_window` so history doesn't dump.
Implement this as a filter in `insight_novelty_filter.py` (it already has the store and
watermark) OR when emitting candidates in `daily()`.

### 3.5 Config knobs (`config.json` + `main.py::build_initial_state` + `src/state.py`)
Add, mirroring the `insight_period_*` pattern:
`insight_daily_enabled` (true), `insight_daily_days` (84), `insight_daily_exclude_today`
(true), `insight_daily_recent_days` (3), `insight_daily_rolling_window` (28),
`insight_candidates_daily` (already exists, 10).

### 3.6 Files to touch (Phase 3)
- **Modify:** `src/agents/insight_temporal.py` (day-axis validation + daily scan exec/append),
  `src/agents/insight_scan_templates.py` (`build_daily_series_scan`),
  `src/agents/insight_stat_detector.py` (`daily()` method),
  `src/tools/insight_memory.py` (`daily` story_key branch + recency helper),
  `src/agents/insight_novelty_filter.py` (recency gating for `daily`),
  `config.json`, `src/main.py`, `src/state.py`, `CLAUDE.md`, `AGENTS.md`,
  `scripts/replay_stat_detector.py` (+ synthetic daily fixtures).
- No graph rewiring needed — the temporal node already runs and the `daily` level is
  already scaffolded in the novelty filter, signal detector, and stat-detector caps.

### 3.7 Verification (Phase 3)
1. **Offline** (`replay_stat_detector.py`): synthetic daily series with (a) one anomalous
   day, (b) a 3-day incident, (c) a weekend pattern that must NOT false-flag → expect ONE
   `daily_incident` per incident with correct date ranges; weekends not flagged.
2. **Offline gate:** a synthetic clean daily series PASSES; the real `UPDATED_DATE` batch
   pattern FAILS (daily stays disabled).
3. **Recency:** a historical incident outside the recency window is NOT eligible; a new-day
   incident is reported once then suppressed on re-run.
4. **Live run:** confirm on the current model the gate keeps daily disabled (correct), and
   nothing regresses in Phases 1–2. (A real demo needs a model with a clean day column.)

---

## 4. Phase 4 — Re-alerting (context only, not required now)

Once reported, a story is suppressed forever under `never_repeat`. Phase 4 makes a story
**resurface** when its mutable observation changes materially vs the stored record:
direction reversal (`sign(now) != stored.direction`), material growth
(`abs(now) ≥ (1+pct)·abs(stored)`), or a daily/period incident **extension**
(`now.episode_end > stored.episode_end`). This is exactly why `story_key` excludes those
mutable fields. It's an eligibility layer in `insight_novelty_filter` + comparison logic
in `insight_memory`, gated by `insight_re_alert_enabled` (default false),
`insight_re_alert_growth_pct` (default 50). **Follow-on after that: automation** — trigger
`python -m src.main` daily (Windows Task Scheduler or a cloud cron); the memory lock +
atomic write make an accidental double-run safe.

---

## 5. Guardrails every phase must respect

- **Deterministic before the LLM.** Detect + fingerprint + filter in code; the LLM only
  selects/phrases from the eligible list. Never trust the LLM to enforce caps or novelty.
- **Stable `story_key`.** Exclude direction / impact / episode_end. Never use candidate ids
  (their ranking-based numbering drifts between runs). Normalize segments (NFKC + casefold
  + collapse-whitespace + sorted members).
- **Concurrency contract.** The insight branch is single-writer per state key per superstep.
  The only memory *write* is `commit()` inside the post-join `save_outputs` barrier. Do not
  add a second store writer. Post-fork nodes use `state["pbi_token"]` — never fetch a token.
- **Fail-loud memory.** A corrupt store is never treated as empty; warn, refuse to
  overwrite, and flag the report. Everything memory/temporal/upload-related is
  **best-effort and must never crash a run** (wrap in try/except like the existing nodes).
- **Honest grain.** Never analyze a load/posting-date axis as if it were business activity.
  When in doubt, disable the level and say so in the report caveat.
- **Keep one merged story.** Don't emit N repetitive per-period/per-day insights; let the
  LLM merge (`related_candidate_ids` → `covered_story_keys`), and fold key context
  (steepest periods, the drill "where") INTO the merged candidate's detail so it survives.
- **Keep `CLAUDE.md` and `AGENTS.md` identical** and update them with any behavior change.
- **Bound live probes** (`insight_temporal_max_probes`) — the gate/drill/daily scans each
  cost a REST round-trip.

---

## 6. One-line status
**Done:** Phase 1 (memory / unseen-only), Phase 2 (monthly "when + where + %"), plus
auto-upload of `outputs/api/*.json` to Azure Blob. **Left:** Phase 3 (daily incidents —
this doc; stays disabled until a clean business-day column exists), Phase 4 (re-alerting),
and scheduled automation.
