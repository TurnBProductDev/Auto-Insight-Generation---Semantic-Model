# Implementation prompt: cut the cost of narrated Sales vs Previous Year

**Hand this whole file to a fresh session.** It assumes no memory of the
conversation that produced it. Every number below was measured on 2026-09-11.

---

## 0. Branch rule - check this before touching anything

All work happens on **`cost/sales-yoy-narrated-summary`**, created from
`final/version11` at commit `8b25a18` ("Add the narrated tier: code decides, the
model only writes the sentences").

```bash
git branch --show-current          # must print: cost/sales-yoy-narrated-summary
git switch cost/sales-yoy-narrated-summary   # if it does not
```

- Never commit to `final/version11` or `main`. Never push unless asked.
- **Nothing is deployed from this work.** Do not rebuild container images, do not
  change any Azure Container Apps job, secret or schedule.
- The working tree carries **someone else's uncommitted work**: edits in
  `src/config_schema.py`, `src/tools/api_payloads.py`, `src/tools/azure_blob.py`,
  the `config/sbmart-*/config.json` files, `src/domains/inventory/*`, several
  `scripts/run_*.py` and `scripts/replay_*.py`, `CLAUDE.md` / `AGENTS.md`, and
  more. **Never stage, revert, reformat or "tidy" them.** When a file you change
  also holds their edits, commit only your own hunks:

  ```bash
  git diff -U0 HEAD -- <file>            # find your hunks
  # write a patch holding only yours, then:
  git apply --cached --unidiff-zero --check your.patch && git apply --cached --unidiff-zero your.patch
  git diff --cached                      # confirm no foreign line is staged
  ```

  Zero context matters: a normal-context hunk can merge your change with an
  adjacent line of theirs. Check the staged diff for their markers before every
  commit (for example `inventory_archive_storage`, `scan_archive_prefix`,
  `kpi_card_evidence`).

---

## 1. What you need to know first

Read, in this order: `CLAUDE.md` ("Concurrency contract", "Balanced business
summary (summary R4)", "Interactive four-layer dashboard (summary R6)",
"Gotchas"); `docs/cost-and-tiering-implementation-brief.md` section 3 (ground
rules); `src/tools/ai_tier.py` in full.

### The dial this builds on

`report_ai_tier` has three values. Only **narrated** is in scope here.

| tier | model decides (plan, select, investigate) | model writes |
|---|---|---|
| investigated | yes | per-report flag |
| **narrated** | no | yes, every prose slot |
| deterministic | no | no |

Helpers: `ai_tier.tier / investigates / narrated / deterministic /
prose_allowed(state, flag) / authoring_allowed(state)`. The tier is read from
`state` then `state["config"]`; standalone runners pass the config itself.

### Where narrated Sales YoY spends its money - measured

One narrated run, from the per-call receipt `<output_folder>/token_usage.json`
(written by `src/tools/token_usage.py`, labelled by calling module):

| call | input | cached | output | USD |
|---|---|---|---|---|
| `fresh_summary_generator` attempt 1 | 19,859 | 0 | 721 | 0.0605 |
| `fresh_summary_generator` attempt 2 | 22,769 | 19,968 | 756 | 0.0233 |
| `fresh_summary_generator` attempt 3 | 25,748 | 22,784 | 750 | 0.0244 |
| `summary_dashboard_builder` | 8,210 | 0 | 971 | 0.0351 |
| `insight_deterministic` (Key Insights) | 2,033 | 0 | 501 | 0.0126 |
| `api_payloads` (KPI card text) | 4,256 | 0 | 540 | 0.0187 |
| **total** | | | | **0.1746** |

Input is 64% of cost, output 36%. The other five SB Mart reports cost
USD 0.014-0.030 each narrated, because each fills a few short slots from a
2,000-7,000 token prompt.

### Why the summary writer is the problem - three causes

1. **It sends the whole evidence set.** Of the 19,859-token first prompt, about
   2,760 tokens are instructions (`prompts/_global_rules.md`,
   `prompts/fresh_summary_prompt.md`, the two client rulebooks) and about
   **17,100 tokens (86%) are evidence and chart data**: `_perspective_context` for
   Overall plus three focus areas, and every entry from `_chart_sources`.
2. **It designs the page, not just the words.** `FreshSummaryDraft` is `headline`
   + a free list of `FreshSummaryBlock` (`kind` paragraph/bullets/chart, `heading`,
   `text`, `points`, `chart_source_id`, `chart_type`) + `covered_candidate_ids`. To
   choose blocks and charts the model needs everything. Compare
   `summary_dashboard_builder.DashboardDraft`: fixed slots only (`hero`, one
   `story` per entity, `headline` / `connect` per area) - 8,210 tokens.
3. **It retried twice.** `fresh_summary_generator._invoke` allows three attempts;
   every failed draft and its `validate_draft` errors are appended and the whole
   conversation resent. **The rejection reasons are never logged**, so nobody
   knows what failed.

Prompt caching cannot rescue a once-a-day job: the cache expires between runs.

### The five levers, and what each was estimated to save

Estimates from the receipt above, not yet measured:

| # | Lever | Sales YoY USD/run | saving |
|---|---|---|---|
| - | as measured | 0.175 | - |
| 1 | summary passes first time (fix the retry cause) | 0.127 | 27% |
| 2 | summary on code-owned layout, prose slots only | ~0.06-0.08 | ~55-65% |
| 3 | summary writer on `gpt-5.4-mini` | 0.099 | 43% |
| 4 | summary wording by code, other slots narrated | 0.066 | 62% |
| 5 | every narrated Sales YoY call on `gpt-5.4-mini` | 0.052 | 70% |

Rates used (USD per 1M tokens, in `token_usage.RATES`): `gpt-5.4` 2.50 in /
0.25 cached / 15.00 out; `gpt-5.4-mini` 0.75 / 0.075 / 4.50.

---

## 2. Ground rules - breaking one produces a report that looks right and is wrong

1. **Off by default.** Every new key's code default reproduces today's behaviour.
   The investigated and deterministic tiers must be byte-for-byte unchanged.
2. **`src/config_schema.py` is the single catalogue.** New key: type, default,
   plain `label`, plain `help` (what happens, and what happens if wrong), `detail`,
   `tier`. `scripts/replay_config_schema.py` must pass.
3. **Declare state keys on `SummaryAgentState` in `src/state.py`.** LangGraph
   drops undeclared keys silently; `report_id` once put publish and hydrate in two
   different folders because of it. Read new keys through state *and* config.
4. **Never weaken a validator to make a saving.** If a change makes
   `validate_draft`, `dashboard_rules`, `_clarity_issues` or `_grounded_summary`
   pass more often, that is a regression. Fix the writer or the context instead.
5. **A cheaper model only where a deterministic gate catches a worse answer** -
   every narrated slot qualifies, because every slot has a validator and a
   grounded fallback. Quality is still a human judgement: produce side-by-side
   output, do not decide on cost alone.
6. **Never touch the concurrency contract** (fork, routers, the joined barrier
   into `save_outputs`). `logs`/`errors` are reducer-backed: return deltas only.
7. **Every new module or behaviour gets replay coverage.** New
   `scripts/replay_*.py` files join `replay_all.py` by glob; raise `MIN_EXPECTED`.
   Extending `scripts/replay_ai_tier.py` is preferred for tier behaviour.
8. **Measure, do not assume.** Every cost claim in a commit message comes from a
   `token_usage.json` receipt of a live run.
9. **Write code with the Write/Edit tools, not shell heredocs.** A heredoc once
   turned a regex's `\b` into a literal backspace byte in this repo.

The commit gate, every phase:

```bash
cd powerbi-summary-agent
python scripts/replay_all.py --with-golden     # must end: REPLAY GATE GREEN, golden byte-identical
```

---

## 3. How to run Sales YoY live without touching production

The live Sales YoY job is `insightgen-sbmart-yoy-daily` in resource group
`Summary_generator_PBI`. Its config and rulebooks are job secrets. Build an
isolated copy **outside the repo** (for example in your scratchpad):

```bash
for S in agent-config-b64:config.json agent-rules-b64:business_rules.md agent-summary-rules-b64:summary_business_rules.md; do
  az containerapp job secret show -n insightgen-sbmart-yoy-daily -g Summary_generator_PBI \
     --secret-name ${S%%:*} -o tsv --query value | python -c "import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read().strip()))" > "$DIR/${S##*:}"
done
```

The rulebooks must stay **siblings** of `config.json` - they are resolved from the
config's folder. Then override, in `config.json`:

```json
"report_ai_tier": "narrated",
"output_folder": "outputs_bench_narrated/<experiment>",
"azure_blob_upload": false,
"ai_content_publish_enabled": false,
"insight_memory_storage": "local",
"summary_memory_storage": "local",
"insight_memory_runtime_folder": "outputs_bench_narrated/<experiment>/.runtime/insight_memory",
"summary_memory_runtime_folder": "outputs_bench_narrated/<experiment>/.runtime/summary_memory",
"insight_history_enabled": false,
"summary_history_enabled": false,
"plan_cache_enabled": false,
"adaptive_investigation_enabled": false
```

Without these, a local run advances production memory and the next scheduled
report withholds findings as already reported. `outputs_bench_*/` is gitignored.

```bash
cd powerbi-summary-agent
python -m src.main --config "$DIR/config.json"
python scripts/audit_summary_dashboard.py outputs_bench_narrated/<experiment>
```

- The receipt is `outputs_bench_narrated/<experiment>/token_usage.json`. Trust it
  over Azure's per-minute metric, which lags about a minute.
- Run live reports **one at a time**: they share the MSAL token cache, which is
  not safe for concurrent writers.
- A run starts from empty local memory, so every finding is new. Compare
  experiments against each other on the same day, not against production spend.
- Local runs use `.env` credentials and the repo-root `.pbi_token_cache.json`.

---

## 4. The work - phases in order, each with an exit criterion

Do not start a phase until the previous one's exit criterion is met. At the end
of each phase report: what changed, what the gate said, the measured cost, and
what you could not verify.

### Phase 0 - make the rejections visible (no behaviour change)

1. In `fresh_summary_generator._invoke`, record every attempt: attempt number and
   the `validate_draft` errors of each rejected draft. Write them to the run log
   and to a new artifact `summary_authoring_attempts.json`. Do the same for the
   dashboard narratives (`summary_dashboard_builder._narratives`) and KPI card
   text if they retry.
2. Keep it purely observational: no prompt, context or validator change.
3. Two live narrated runs as in section 3.

**Exit:** gate green and golden byte-identical; the rejection reasons for every
failed summary attempt are captured; measured Sales YoY cost within about 15% of
USD 0.175.

### Phase 1 - lever 1: make the summary pass first time

1. Read the captured reasons. Typical classes to look for: a figure not copied as
   an exact display value, a chart source or chart type not in the allowed list,
   a headline without the required figure, a banned word ("comparable" in manager
   prose), a focus segment missing from its block.
2. Fix the **cause** in what the model is given: the prompt, the order and form of
   supported display values, the chart-source list. Do not relax
   `summary_validation`.
3. Bring the narrated summary in line with every other narrated writer: **two
   attempts** (one repair carrying the errors), then the grounded `_r4_fallback`.
   Leave the investigated tier's three attempts unchanged.
4. Replay: a fixture reproducing each rejection class now passes on attempt 1; the
   narrated path stops after one repair and falls back; the investigated path
   still allows three; existing `replay_fresh_summary.py`,
   `replay_summary_portfolio.py` and `replay_summary_r4_isolation.py` unchanged.

**Exit:** gate green; three consecutive live narrated runs with the summary passing
on attempt 1, or the residual failure rate stated with its reasons; measured
Sales YoY at or below about USD 0.13.

### Phase 2 - lever 2: code owns the summary layout, the model writes slots

This is the structural fix and the largest saving that keeps model wording.

1. Add a narrated-only path in `fresh_summary_generator` (`_run_r4`), gated on
   `ai_tier.narrated(state)`. The investigated path keeps `_invoke` untouched.
2. **Code builds the whole page plan first**, reusing the grounded fallback
   machinery - `_r4_fallback`, `_overall_group`, `_grounded_points`,
   `_chart_blocks`, `_fallback_chart_sources`. Code decides the blocks, their
   order, headings, bullet facts and charts. The model can never add, drop or
   reorder a block, or choose a chart.
3. Then define **prose slots**, the way `DashboardDraft` does: the page
   `headline`, and one `text` per paragraph block (and, if worthwhile, the wording
   of bullet points without changing which facts they carry). Each slot gets an id.
4. **Send the model only each slot's own supported facts** - the display values
   and statements that slot's grounded text already uses - plus that grounded
   text as a baseline. Not `_perspective_context`, not chart data.
5. Assemble the final draft from code's plan plus the returned slot text and run
   `validate_draft(..., mode="balanced_multi_focus", require_chart=...)` on it.
   Where a slot fails, put that slot back to its grounded text and validate again,
   so one bad slot never costs the whole page and strict validation cannot
   dead-end. One repair round with the errors, as in Phase 1.
6. `authoring_mode` should say what happened (for example `llm_slots` with counts
   of model-written and fallback slots). `report_summary.json` from
   `api_payloads.generate_fresh_report_summary_payload` must still validate.
7. Replay: the model cannot change block count, order, kinds, headings or chart
   ids; an invented figure in one slot is rejected and only that slot falls back;
   a failed call keeps the grounded page; the investigated path is byte-for-byte
   unchanged; the deterministic path is unchanged.

**Exit:** gate green, golden byte-identical; live narrated run with summary input
under about 8,000 tokens and summary cost at or below about USD 0.04;
`audit_summary_dashboard.py` clean; `report_dashboard.html` rendered and looked at
(`chrome --headless=new --screenshot=out.png --window-size=1500,2400
file:///<path>`); the new summary read side by side with the Phase 1 one, and any
loss of quality written down.

### Phase 3 - levers 3 and 5: a cheaper model per narrated slot

1. Routing already exists: `node_model_overrides` in config maps a calling-module
   label to an Azure deployment (`src/tools/llm.py`, Azure provider only). The
   narrated labels are `fresh_summary_generator`, `summary_dashboard_builder`,
   `insight_deterministic` (Key Insights - it calls `get_llm` itself) and
   `api_payloads` (KPI card text). Confirm each label from a receipt; do not assume.
2. `gpt-5.4-mini` is a deployed model on the resource the job uses
   (`test-agentpbi-resource`).
3. Run experiments, same day, same isolated setup:
   - A: all four on `gpt-5.4`;
   - B: summary slots on mini;
   - C: all four on mini.
4. For each: receipt cost, rejection and fallback counts per slot (Phase 0
   logging), and a side-by-side document of the summary, dashboard stories, Key
   Insights and KPI cards, for a human to judge.
5. If a replay is useful, prove the override routes each narrated label without a
   network call.
6. Do **not** enable mini in `config/sbmart-yoy/config.json` yourself. Present the
   measured table and the side-by-side output and let the user choose. A negative
   result (mini writes noticeably worse, or falls back so often it saves nothing)
   is worth recording in the commit message.

**Exit:** measured cost table for A/B/C; rejection and fallback rates; the
side-by-side output saved under `outputs_bench_narrated/` for review.

### Phase 4 - lever 4: a per-slot switch back to code wording

1. Add one catalogued key, for example `narrated_code_slots` (list, default `[]`,
   which is today's behaviour), accepting `summary`, `dashboard`, `key_insights`,
   `kpi_cards`. Under the narrated tier, a listed slot uses its grounded text and
   makes no model call; unlisted slots stay narrated. It has no effect on the
   other two tiers.
2. Add a single helper in `src/tools/ai_tier.py` (for example
   `slot_narrated(state, slot)`), read through state then config, and use it in the
   four writers. Declare the key on `SummaryAgentState`.
3. Replay: each listed slot makes zero model calls while the others still do; an
   unknown slot name is rejected by the catalogue rather than silently ignored;
   `replay_config_schema.py` passes.

**Exit:** gate green, golden byte-identical; a live narrated run with
`["summary"]` listed, measured near USD 0.07 with the summary written by code and
every other slot model-written.

### Phase 5 - measure the combinations and recommend

1. Live runs, same day, of at least:
   - (a) narrated with Phases 1-2;
   - (b) (a) plus the Phase 3 winner;
   - (c) (a) with `narrated_code_slots: ["summary"]`.
2. Record them in a new `tests/bench/narrated_2026-09.json` (per-call receipts,
   totals, run seconds, fallback counts) beside the existing
   `tests/bench/baseline_2026-09.json`.
3. Report per run, per year for one client, and per year for 20 clients.
4. Recommend one configuration for `config/sbmart-yoy/config.json`, with the
   quality evidence. Change the config only if the user agrees.

**Exit:** gate green; the bench file committed; a written recommendation.

---

## 5. Commits

- One commit per phase, on `cost/sales-yoy-narrated-summary` only, in this repo's
  style: an imperative headline saying what changed; a body saying why, what
  defect or cost it closes, the measured result from a receipt, and what was not
  verified. End every commit message with:

  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  ```

- Stage only your own hunks (section 0). Before each commit run
  `git diff --cached --stat` and grep the staged diff for the other work's markers.
- Optionally prove a commit stands alone in a clean worktree. On Windows use
  `git -c core.longpaths=true worktree add --detach <dir> HEAD`. Eleven replays
  fail on any clean checkout because they read gitignored local files - compare
  against the parent commit's clean checkout rather than expecting zero.

## 6. Things not to do

- Do not deploy, rebuild images, or edit job secrets.
- Do not change the investigated or deterministic tiers' behaviour.
- Do not loosen `validate_draft`, `dashboard_rules`, `_clarity_issues`, the KPI
  grounding, or any auditor to make a saving.
- Do not let the model choose charts, blocks or findings on the narrated tier.
- Do not run live reports concurrently, or with production memory, history or
  publishing switched on.
- Do not enable `gpt-5.4-mini` for a client without the user's decision.
- Do not touch the other session's uncommitted files.

## 7. First actions

1. `git branch --show-current` - confirm `cost/sales-yoy-narrated-summary`.
2. `cd powerbi-summary-agent && python scripts/replay_all.py --with-golden` - the
   tree must be green before you change anything (57 checks at the time of writing).
3. Read `fresh_summary_generator._invoke`, `_run_r4`, `_r4_fallback`,
   `summary_dashboard_builder._narratives` and `src/tools/ai_tier.py`.
4. Build the isolated Sales YoY config (section 3) and start Phase 0.
