> ## 🚀 KICKOFF PROMPT — paste this as your first message to the new chat
>
> You're working in the `powerbi-summary-agent` repo. **Read this entire file
> (`PHASE_ROADMAP.md`) and `CLAUDE.md` first**, then implement **Phase 4 — general
> re-alerting** for the high/period/daily levels, exactly as specified in §4. Phases
> 1–3b are DONE and must keep working; respect every guardrail in §5. Rolling-week's
> own unconditional resurface logic (§3) is already a working reference
> implementation for the comparison logic you need, just gated by
> `insight_re_alert_enabled` instead of being structural. Prove each deterministic
> piece with **synthetic offline fixtures** in `scripts/replay_novelty_filter.py` (no
> live run is needed to validate the logic), and confirm the flag defaults to
> `false` so nothing changes for existing runs until explicitly enabled. Keep
> `CLAUDE.md` and `AGENTS.md` identical and updated. **Show me your implementation
> plan before writing any code.**

---

# Layered Insight Agent — Phase Roadmap & Phase 4 Implementation Guide

> Hand this whole file to a fresh chat. It is self-contained: it explains the repo,
> what Phases 1–3b already built, the **detailed Phase 4 plan to implement**, and the
> guardrails to respect. Your job (new chat) is **Phase 4**; Phases 1–3b are DONE and
> must keep working.

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
- `commit_run(state, reported_signals)` — advances the daily per-axis cursor and the
  rolling observation/activity snapshot **unconditionally** whenever the underlying gate
  validated an axis this run (independent of whether anything was reported), and
  additionally upserts reported signals, marks ALL `covered_story_keys` (merged
  candidates) seen, merges `journal[today]` by story_key, and advances `watermark` — but
  only when `reported_signals` is non-empty. "Observed" and "reported" are different
  things: a synthesizer failure (only a stub report written) must still let observations
  advance, but must never mark a story as seen that the user never actually received.

### Cascade levels
Findings are tagged a **level**: `high` (current-vs-prior by dimension), `period`
(Phase 2 sub-annual), `recent_week` (Phase 3 — the most recently completed Mon–Sun week,
or a rolling 7-day window when `insight_week_mode: "rolling"`, tagged
`recent_week_rolling`), `daily` (Phase 3b — individual/merged daily anomaly incidents).
The novelty filter caps eligible candidates **per level**; the signal detector ranks
**purely by materiality score** — **there is no `_LEVEL_RANK` and never has been in
code** (an earlier draft of this doc described one; `insight_signal_detector.py`'s
`_rank_and_cap`/`_backfill_uncovered` have always sorted by score alone, with
`_backfill_uncovered` only backstopping a whole level the LLM's response touched not at
all — never a priority ordering).
- `insight_novelty_filter.py::_level_for(candidate, contract)` / `insight_stat_detector.py`'s
  `_Detector._level` map a candidate's scan `coverage_kind` to its level. The more
  specific `recent_week_rolling`/`daily` checks must come before the generic
  `recent_week` one, since `"recent_week_rolling_history".startswith("recent_week")` is
  `True`.
- Per-level candidate caps: `insight_candidates_{high,period,daily}` +
  `insight_candidates_weekly` (shared by `recent_week` and `recent_week_rolling`, which
  never coexist in one run since `insight_week_mode` selects one).

### Temporal grain gate (Phase 2) — `src/agents/insight_temporal.py`
Runs before the evidence catalog. Judges each time axis and, if valid, appends one series
scan to `insight_clean_data` so it flows through the catalog + stat detector. **This is
the file you extend most for Phase 3.**

---

## 2. Phases 1, 2 & 3 — DONE (do not break)

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
date, not business activity** (a single month-end bucket holds >50% of revenue) — and the
data is also ~2.5 years stale. The gate **correctly rejects it** and uses the month column
`DOC_MONTH` for the period level instead. **Recent-week, rolling-week, and daily anomaly
incidents therefore all stay DISABLED on this dataset** (same underlying gate, same
reason) — and that is correct behavior, not a bug. They activate the moment a model
exposes a genuine, current business-**day** column.

---

## 3. Phase 3b — Daily anomaly incidents + rolling-week mode — DONE

**Goal (delivered):** when a genuine business-**day** axis exists, flag an individual
abnormal day (or a merged run of consecutive abnormal days) the moment it lands
(`daily` level), and/or compare a trailing 7-day window to the 7 before it, refreshed
daily (`recent_week_rolling` level, selected via `insight_week_mode: "rolling"`), instead
of only Mon–Sun calendar weeks. Both reuse the exact same validated daily fetch Phase 3
already made — no new REST calls.

- **`src/agents/insight_business_day_source.py`** (new node) — the validation/fetch this
  guide originally sketched as part of `insight_temporal.py` was extracted into its own
  node instead: it owns the one REST fetch and all axis validation (timezone gate,
  additive-metric gate, batch/load-date rejection, staleness), and resolves
  `effective_data_as_of` (the true `data_as_of` rolled back to the previous operating day
  when a still-loading "today" row would otherwise leak into a rolling window or a daily
  incident's last day — calendar folding always keeps the TRUE `data_as_of`). Runs if
  either `insight_recent_week_enabled` or `insight_daily_enabled` is true, so disabling
  one consumer never starves the other of the fetch it needs. Graph order:
  `insight_temporal → insight_business_day_source → insight_recent_week → insight_daily
  → insight_evidence_catalog`.
- **`src/agents/insight_recent_week.py`** shrank to folding only (reads the shared
  source); `insight_week_mode: "calendar"` (default) folds Mon–Sun weeks unchanged,
  `"rolling"` folds non-overlapping 7-day windows counting back from
  `effective_data_as_of` (`coverage_kind: "recent_week_rolling_history"` — NOT a 1-day
  slide, which would overlap 6/7 with its neighbor and break the stat detector's
  week-over-week comparison).
- **`src/agents/insight_daily.py`** (new node) — `flag_abnormal_days` tests each day
  against a trailing rolling reference AND (when enough prior history exists) the same
  weekday's own history; combining them is **AND, not OR** (both must clear their own
  test — z-cutoff + materiality if variable, materiality alone if flat — and agree in
  direction), which is what stops a systematic weekend low from being flagged.
  `merge_incidents` collapses consecutive same-direction abnormal days (bridging a closed
  weekend via operating-day adjacency) into ONE incident. A recency filter, applied once
  before rows reach the stat detector, keeps the first run for an axis from dumping the
  whole fetched window as new.
- **`src/agents/insight_stat_detector.py`** — `recent_week()` widened to accept both
  calendar and rolling coverage kinds (one method, a `window_mode` field, not a
  duplicate); always emits `insight_rolling_observation` for rolling mode (even when the
  reading isn't significant) so memory can later learn an incident recovered; `daily(t)`
  turns each already-merged incident row into a `daily_incident` candidate, dispatched
  **exclusively** (never alongside `concentration`/`outliers`, which could otherwise
  misread an incident row's numeric fields as a segment breakdown).
- **`src/tools/insight_memory.py`** — `story_components` gained `daily` (anchor =
  `episode_start`, no `period_anchor`) and `recent_week_rolling` (deliberately **no
  anchor** — a rolling window's only natural anchor changes every day, so an anchor-based
  key would defeat suppression entirely; one key exists per axis+metric+segment forever).
  `commit()` was replaced by **`commit_run(state, reported_signals)`**: the daily cursor
  and the rolling observation/activity snapshot advance unconditionally whenever the
  gate validated an axis this run (forward-only, monotonic guard), independent of
  whether `reported_signals` is non-empty — "observed" and "reported" are different
  things. New `resurface_check` compares a stored record against a fresh reading
  (reversal / growth-multiple / rolling's own delta-pct drift floor).
- **`src/agents/insight_novelty_filter.py`** — rolling-week gets its own eligibility path
  that **never** consults `never_repeat`/`cooldown`: unknown key → eligible; known +
  inactive→active transition → eligible; known + `resurface_check` fires → eligible;
  otherwise suppressed. If memory is disabled or corrupt, rolling candidates are dropped
  outright (the level is meaningless without persisted state) rather than reported every
  run. The rolling story_key is computed in exactly one place — here — for both a real
  candidate and the observation-only case, so the two can never drift apart.

**Config knobs added:** `insight_daily_enabled`, `insight_daily_rolling_window`,
`insight_daily_recent_days`, `insight_daily_exclude_today`, `insight_daily_z_cutoff`,
`insight_daily_materiality_pct`, `insight_daily_min_weekday_occurrences`,
`insight_week_mode`, `insight_re_alert_growth_pct` (rolling's own growth trigger),
`insight_rolling_report_delta_pct`.

**Verified by:** `replay_stat_detector.py` (fold shape, per-reference AND-gate, weekend
veto, warm-up, operating-day-adjacency merge, flat-baseline fallback, exclusive dispatch,
always-emitted rolling observation) and `replay_novelty_filter.py` (recency clauses,
`commit_run` observed-vs-reported separation + monotonic guard, rolling
unknown/transition/resurface/suppressed/unavailable paths, single story-key authority).

**Deferred, not silently dropped:** general Phase-4 re-alerting (below) for the
high/period/daily levels, and daily-incident *extension* re-alerting — `episode_end`/
`peak_z` are persisted now purely as scaffolding for that later change.

---

## 4. Phase 4 — General re-alerting (context only, not required now)

Once reported, a story is suppressed forever under `never_repeat`. Rolling-week's own
narrow resurface logic (§3, `insight_novelty_filter.py` + `insight_memory.resurface_check`)
is already done and unconditional for that one level. General Phase 4 extends the same
idea to the **high/period/daily** levels: a story **resurfaces** when its mutable
observation changes materially vs the stored record — direction reversal
(`sign(now) != stored.direction`), material growth (`abs(now) ≥ (1+pct)·abs(stored)`), or
a daily incident **extension** (`now.episode_end > stored.episode_end`, using the
`episode_end`/`peak_z` fields `insight_memory.py`'s `daily` story branch already persists
as scaffolding). This is exactly why `story_key` excludes those mutable fields. It needs a
general eligibility layer in `insight_novelty_filter.py` (mirroring the rolling-specific
one, but gated by config rather than unconditional), gated by `insight_re_alert_enabled`
(default false) and reusing `insight_re_alert_growth_pct` (already added for rolling).
**Follow-on after that: automation** — trigger `python -m src.main` daily (Windows Task
Scheduler or a cloud cron); the memory lock + atomic write make an accidental double-run
safe.

---

## 5. Guardrails every phase must respect

- **Deterministic before the LLM.** Detect + fingerprint + filter in code; the LLM only
  selects/phrases from the eligible list. Never trust the LLM to enforce caps or novelty.
- **Stable `story_key`.** Exclude direction / impact / episode_end. Never use candidate ids
  (their ranking-based numbering drifts between runs). Normalize segments (NFKC + casefold
  + collapse-whitespace + sorted members).
- **Concurrency contract.** The insight branch is single-writer per state key per superstep.
  The only memory *write* is `commit_run()` inside the post-join `save_outputs` barrier —
  one lock, one atomic transaction covering observations AND reported signals. Do not add
  a second store writer. Post-fork nodes use `state["pbi_token"]` — never fetch a token.
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
**Done:** Phase 1 (memory / unseen-only), Phase 2 (monthly "when + where + %"), Phase 3
(**previous-complete-week monitoring** — the most recently completed Mon–Sun week vs its
13-week norm, with a capability + freshness gate), Phase 3b (**daily anomaly incidents +
rolling-week mode** — individual/merged abnormal days via a dual trailing/same-weekday
test, and an optional trailing-7-day rolling window with its own structural resurface
logic; both share Phase 3's validated daily fetch via the new
`insight_business_day_source` node). All three date-grained levels stay disabled on the
working model because `UPDATED_DATE` is a batch/load date and the data is stale — correct
by design. Plus auto-upload of `outputs/api/*.json` to Azure Blob.
**Left:** general Phase 4 re-alerting for the high/period/daily levels (rolling-week
already has its own unconditional version; the `recent_week`/`daily`/`period`/`high`
story_keys already exclude the mutable fields it would need), and scheduled automation.
