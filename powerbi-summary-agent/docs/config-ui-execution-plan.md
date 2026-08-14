# Client Onboarding UI — Execution Plan

A self-contained brief for building a web UI that configures a new Power BI
dashboard/client for this agent, runs the live probe cycle, and deploys the
scheduled job. **This document is written to be pasted into a fresh chat as the
complete context for implementation.**

> **Status (2026-08-12): Phases 0, 1 and 2 are built, plus the Phase 3
> containerisation.** See [`config-ui.md`](config-ui.md) for what exists and how
> to run it. This file stays as the design brief and the record of *why*.
>
> | Phase | State |
> |---|---|
> | 0 - Foundation | Done. `src/config_schema.py` (202 keys), `main.py` reads its defaults from it, `scripts/replay_config_schema.py` guards the drift, `src/services/probe.py`, `src/services/validate.py`. |
> | 1 - Local UI | Done. `src/api/` - FastAPI, in-process job runner, dependency-free wizard, probe screen, rulebook editor, validation panel, writes `config/<client>/`. |
> | 2 - Deployment | Code done (`src/services/deploy.py`, ARM secret merge + job upsert + run-now + executions), tested offline. **Not yet exercised against live ARM.** 2.5 (versioned config records in blob) not built - `config/<client>/` plus git is the store. |
> | 3 - Hosting | `Dockerfile.ui` + `requirements-ui.txt` only. Nothing deployed; Entra ID auth, internal ingress and the least-privilege ARM role are still to do. |
> | 4 - Nice to have | Not built, except the config diff (`GET /api/diff`) and clone-a-client. |
>
> Two corrections to Part 2 found while building: the "Default" column below
> records the **committed config values**, not the code defaults - the schema
> carries the code defaults, which is what a config missing the key actually
> does (e.g. `insight_max_signals` is 5 in code, 15 in the committed config).
> And `insight_now_override` is not settable from a config at all: it is a
> state-only test hook, so it is deliberately absent from the schema.

---

## PART 0 — Context the implementer needs

### What this repository is

`powerbi-summary-agent/` is a LangGraph multi-agent pipeline that reads a Power BI
semantic model, auto-generates DAX (the user never writes any), executes it, and
produces two outputs per run from two concurrent branches:

- `report_summary.md/.html` — descriptive ("what the numbers are")
- `insight_report.md/.html` — investigative ("why they look that way")
- `report_dashboard.html` — a four-layer interactive briefing (feature level "R6")

It runs today for two clients, both as Azure Container Apps Jobs:

| Job | Client | Workspace | Dataset | Cron (UTC) |
|---|---|---|---|---|
| `insightgen-daily-job` | cityflower | `6d383900-b84d-4bce-afb4-b95453bee00a` | `b3458a38-ad83-4e9a-b2f2-39d15c6aa22c` | `30 3 * * *` |
| `insightgen-scanb-daily-job` | scanb | `7111406b-1fff-4a8b-bd52-fa6131682262` | `643336e7-4360-4b56-82f8-7b72cefad3ed` | `0 4 * * *` |

Shared Azure resources:

- Resource group `Summary_generator_PBI`, subscription `0300da4d-3a63-4241-a129-42b4f8b0c5cc`
- ACR `insightgenacr.azurecr.io`, image `insightgen-agent:<YYYYMMDD-HHMM>`
- Container Apps environment `insightgen-container-env` (East US 2)
- User-assigned managed identity `insightgen-mi`
  (clientId `8eeb4a99-90f5-4793-af93-0c955e2e861e`, principalId `bb12e86b-660e-4364-aa34-c7a1fc36f4ba`)
- Storage account `turnbtestblobstorage`; containers `insightgen` (API payloads),
  `insightstate` (cross-run memory), plus one container **per client** (`cityflower`, `scanb`)
- Azure OpenAI `https://test-agentpbi-resource.cognitiveservices.azure.com`, deployment `gpt-5.4`

### How a client is defined today (the thing the UI replaces)

A client is a directory:

```
config/<client>/
├── config.json                  # ~135 keys actually set; 200 keys are settable
├── business_rules.md            # 39–45 KB, injected into EVERY insight/DAX LLM prompt
└── summary_business_rules.md    # 3–4 KB, injected into the summary generator only
```

`file_io.read_business_rules(config_path)` and `read_summary_business_rules(config_path)`
resolve both rulebooks as **siblings of the active config file**. So
`python -m src.main --config config/<client>/config.json` picks everything up with no
code change.

In the container the three files arrive as base64 environment variables and are
materialized by `src/container_entrypoint.py` into `/app/outputs/runtime-config/`:

| Env var | Becomes | Secret name on the job |
|---|---|---|
| `AGENT_CONFIG_B64` | `config.json` | `agent-config-b64` |
| `AGENT_RULES_B64` | `business_rules.md` | `agent-rules-b64` |
| `AGENT_SUMMARY_RULES_B64` | `summary_business_rules.md` | `agent-summary-rules-b64` |

### Facts that will bite the implementer

1. **Env vars override config.** `src/main.py` (~line 60) maps ~25 env names onto config
   keys (`POWERBI_WORKSPACE_ID` → `workspace_id`, `AI_CONTENT_CLIENT` → `ai_content_client`,
   `AGENT_OUTPUT_FOLDER` → `output_folder`, …). Env wins. The UI must either write env vars
   or config, and be explicit about which — **setting both and letting them disagree is the
   most likely bug in this whole project.**
2. **`/app` is root-owned in the image.** Only `/app/outputs` is writable by the `agent`
   user. `output_folder` must be `outputs` in the cloud; anything else fails with permission
   denied. Verified directly against the image.
3. **`azure_blob_prefix` collisions destroy data.** cityflower uses `""` (container root).
   Any new client that leaves it empty **overwrites cityflower's `api/*.json`**. The UI must
   enforce uniqueness.
4. **`ai_content_client` names an existing blob container.** It is not created automatically.
5. **A report ID is not a dataset ID.** Resolve with
   `GET /v1.0/myorg/groups/{workspaceId}/reports/{reportId}` → `datasetId`.
6. **Secrets exceed the Windows command line.** A 45 KB rulebook base64s to ~61 KB, past the
   32,767-char limit, so `az containerapp job secret set` fails. Use the ARM REST API with a
   request-body file (`az rest --body @file` or a direct HTTPS PATCH).
7. **No JSON schema exists in the repo.** `main.py` only hard-requires `tenant_id`,
   `workspace_id`, `dataset_id` and rejects `PASTE_`-prefixed values. Everything else is
   `state.get(key, default)` scattered across ~40 modules. The UI must own a schema, and that
   schema **will drift from the code unless generated** (see Task 1.1).
8. **`config/agent_settings.json` is dead.** No code reads it. Ignore it.
9. **`fastapi_backend/` at the repo root is an empty skeleton** (one `kpi_snapshot.py`). It is
   not a foundation; treat it as unrelated.

---

## PART 1 — What the UI must do

Five jobs, in this order. **The order is the product**: several config values cannot be
sensibly chosen before the probe has reported what the model actually exposes.

1. **Connect** — tenant/workspace/report; resolve the dataset; verify permissions.
2. **Probe** — run the live metadata/profile/scope/universe scan; show what the model exposes.
3. **Configure** — fill the 200 keys, with probe results driving the ones that matter.
4. **Author rulebooks** — upload or edit the two markdown documents.
5. **Deploy** — write the three secrets and create/update the Container Apps Job.

### Why probe-first is non-negotiable

These keys are unanswerable before the probe, and wrong values silently degrade output
rather than failing loudly:

- `summary_focus_allowed_roles`, `summary_coverage_roles` — depend on which hierarchy
  levels the model actually exposes (Division/Department/Section/Category…)
- `summary_focus_role_aliases` — needed when a client names a level something the generic
  patterns don't match (e.g. "Merchandise Group")
- `summary_dashboard_entity_role`, `summary_dashboard_exposure_role` — on scanb the entity
  dimension did not resolve (`LOC_CODE` matched no entity pattern) and had to be pinned to
  `department`
- `insight_comparable_population`, `insight_excluded_entities` — must be picked from the
  entities the model actually returns
- `insight_temporal_grain_column`, `insight_business_date_override` — depend on whether a
  genuine business date axis exists (on cityflower `UPDATED_DATE` is a month-end **batch**
  date, so day/week/daily analysis is correctly disabled)

So the UI is a **wizard**, not a settings page.

---

## PART 2 — Complete input inventory

**200 configurable keys.** Grouped by wizard step. Column "PC" = varies per client
(observed by diffing the two live configs — 120 of 135 shared keys are identical).

### Step 1 — Connection (17 keys)

| Key | Type | Default | PC | Explanation |
|---|---|---|---|---|
| `tenant_id` | GUID | — | | Azure AD tenant. Overridden by `POWERBI_TENANT_ID`. Required; rejects `PASTE_*`. |
| `workspace_id` | GUID | — | ✔ | Power BI workspace (group) ID. Required. |
| `dataset_id` | GUID | — | ✔ | Semantic model ID. **Not** the report ID — resolve it. Required. |
| `output_folder` | string | `outputs` | ✔ | Local artifact dir. **Must be `outputs` in the container.** |
| `ai_provider` | enum | `azure_openai` | | `azure_openai` \| `anthropic` \| `openai`. |
| `model` | string | `claude-sonnet-5` | | Model name. **For Azure the `AZURE_OPENAI_DEPLOYMENT` env var routes, not this string.** |
| `max_tokens` | int | `8192` | | Output ceiling per LLM call. |
| `azure_openai_api_key_env` | string | `AZURE_OPENAI_API_KEY` | | Name of the env var holding the key — not the key itself. |
| `openai_api_key_env` | string | `OPENAI_API_KEY` | | As above. |
| `anthropic_api_key_env` | string | `ANTHROPIC_API_KEY` | | As above. |
| `execution_mode` | enum | `python` | | `python` (REST) or `powershell`. PowerShell applies to the summary branch only and exists for legacy reasons — keep `python`. |
| `fabric_definitions` | bool | `true` | | Best-effort Fabric/TMSL enrichment to recover measure expressions (`executeQueries` returns them blank). Never fatal. |
| `powerbi_auth_mode` | enum | `auto` | | `auto` \| `interactive` \| `managed_identity` \| `service_principal`. `auto` = managed identity in Azure, interactive locally. |
| `powerbi_query_api` | enum | `auto` | | `auto` \| `json` \| `arrow`. Arrow for headless; JSON for interactive. |
| `powerbi_effective_username` | string | `""` | | RLS impersonation. Leave empty unless RLS is required. |
| `powerbi_rls_roles` | list | `[]` | | RLS roles. Leave empty unless required. |
| `dataset_client_map` | object | — | | Multi-dataset→client mapping. Advanced; leave unset for one dataset per job. |

### Step 2 — Scope and population (2 keys, probe-driven)

| Key | Type | Default | PC | Explanation |
|---|---|---|---|---|
| `insight_comparable_population` | list | `[]` | ✔ | Entity codes forming the comparable (like-for-like) population. **Machine-enforced** by `baseline_scope` + `scope_validator`, and audited against data-derived classification. Empty = derive from data. UI must offer multi-select from probe results. |
| `insight_excluded_entities` | list | `[]` | ✔ | Entities excluded from year-on-year comparison (e.g. a branch that closed). Queries using prior/change metrics that include these are rejected. |

### Step 3 — Roles and hierarchy (probe-driven)

| Key | Type | Default | PC | Explanation |
|---|---|---|---|---|
| `summary_focus_allowed_roles` | list | `["division","department","category"]` | ✔ | Which hierarchy levels may consume a narrative focus slot. Canonical vocabulary and depth: division 10, department 20, section 25, category 30, subcategory 35, product_group 40, special_product_group 50, brand 60, product/item/sku 70. |
| `summary_focus_role_aliases` | object | `{}` | | Maps a client's naming onto canonical roles, e.g. `{"merchandise group":"department"}`. **The escape hatch when the generic patterns don't match.** |
| `summary_focus_hierarchy_overrides` | object | `{}` | | Role-matched deep-dive child-level overrides. Validated against metadata; fails loudly if invalid. |
| `summary_coverage_roles` | list | `["store","division","department","section","category"]` | ✔ | Levels that get a full ranked line-per-member table (R5). Superset of focus roles. `store` is coverage-only and can never enter the focus rotation. |
| `summary_dashboard_entity_role` | string | `""` | ✔ | Entity level for the R6 dashboard's per-entity cards and three-lever split. Empty = auto-resolve from the profile's entity dimension. **Pin it if the profile logs `entity=unresolved`.** |
| `summary_dashboard_exposure_role` | string | `""` | ✔ | Level used for the "revenue exposed to declining areas" signal. |

### Step 4 — Feature levels

| Key | Type | Default | PC | Explanation |
|---|---|---|---|---|
| `fresh_summary_enabled` | bool | `true` | | Master switch for the modern summary path. `false` reverts to the legacy `generate_summary` node. |
| `summary_focus_enabled` | bool | `true` | | R1–R3 daily-focus selection. `false` reproduces the old `summary_key` rotation exactly. |
| `summary_r4_enabled` | bool | **`false`** | | Balanced page: mandatory Overall Performance + up to N areas. **Code default false — a config missing this key silently reproduces R1–R3.** This is exactly how production drifted. |
| `summary_r6_enabled` | bool | `false` in code | | Four-layer interactive dashboard. Same trap as R4. |
| `summary_visual_enabled` | bool | `true` | | Interactive charts in the summary HTML. |
| `summary_llm_authoring_enabled` | bool | `true` | | LLM authors the page; `false` forces the grounded deterministic draft. |
| `summary_dashboard_entity_levers` | bool | `true` | | Spend one query to read revenue/units/bills per entity for the three-lever split. |
| `summary_dashboard_period_view` | bool | `true` | | Offer the "latest complete period" second view. |
| `summary_dashboard_period_scan` | bool | `true` | | One extra query so the period view owns real breakdowns. Without it that view defers and says so. |
| `summary_dashboard_replaces_summary_html` | bool | `false` | ✔ | Also overwrite `report_summary.html` with the dashboard, so the existing publish path picks it up. **Flip only after a clean acceptance run.** |
| `summary_overall_trend_enabled` | bool | `true` | | Summary-owned reconciled overall trend. |
| `summary_focus_deep_dive_enabled` | bool | `true` | | Deterministic per-focus deep dive. |
| `summary_focus_daily_trend_enabled` | bool | `false` | | Daily trend inside the deep dive; gated by its own axis validation. |
| `insight_temporal_enabled` | bool | `true` | | Sub-annual period level. |
| `insight_recent_week_enabled` | bool | `true` | | Weekly monitoring. Needs a genuine business **date** axis. |
| `insight_daily_enabled` | bool | `true` | | Daily anomaly incidents. Same requirement. |
| `insight_memory_enabled` | bool | `true` | | Cross-run novelty suppression. |
| `summary_memory_enabled` | bool | `true` | | Summary focus rotation memory. |
| `insight_history_enabled` | bool | `true` | | Dated history records. |
| `summary_history_enabled` | bool | `true` | | As above for summary. |
| `insight_tiles_enabled` | bool | `false` | | Legacy tile board. The artifact no longer exists — leave false. |
| `insight_thesis_linking_enabled` | bool | `false` | | Experimental signal linking. Leave false. |
| `insight_rate_outlier_mode` | enum | `off` | | Experimental rate-outlier detection. Leave `off`. |
| `summary_focus_public_metadata` | bool | `false` | | Emit the public `dailyFocus`/`dailyFocuses` field on `report_summary.json`. **Coordinated UI/API opt-in** — only enable when the consuming app expects it. |

### Step 5 — Publishing and storage (18 keys)

| Key | Type | Default | PC | Explanation |
|---|---|---|---|---|
| `azure_blob_upload` | bool | `false` | | Push `outputs/api/*.json` to blob after the run. Best-effort; never fails the run. |
| `azure_blob_account` | string | — | | Storage account name. |
| `azure_blob_container` | string | `insightgen` | | Container for API payloads/history. |
| `azure_blob_prefix` | string | `""` | ✔ | **CRITICAL.** Path prefix inside that container. Not dataset-scoped — two clients sharing `insightgen` with the same prefix overwrite each other. cityflower `""`, scanb `"scanb"`. **UI must enforce uniqueness.** |
| `azure_blob_history_prefix` | string | `history` | | Immutable dated insight history. |
| `azure_blob_history_feed` | string | `insight_history.json` | | Single app-facing newest-first feed. |
| `azure_blob_summary_history_prefix` | string | `summary-history` | | As above for summary. |
| `azure_blob_summary_history_feed` | string | `summary_history.json` | | As above. |
| `azure_blob_memory_container` | string | `insightstate` | | Private container for cross-run memory. |
| `azure_blob_memory_prefix` | string | `""` | | Prefix before `{dataset-id}/memory.json`. Memory already keys on dataset ID, so collisions are impossible here. |
| `azure_blob_summary_memory_prefix` | string | `summary-memory` | | As above for summary memory. |
| `insight_memory_storage` | enum | `local` | | `local` \| `azure_blob`. Cloud runs must use `azure_blob` or rotation resets every run. |
| `summary_memory_storage` | enum | `local` | | As above. |
| `insight_memory_runtime_folder` | string | `outputs/.runtime/insight_memory` | | Local hydration scratch. |
| `summary_memory_runtime_folder` | string | `outputs/.runtime/summary_memory` | | As above. |
| `ai_content_publish_enabled` | bool | `false` | | Project outputs into the per-client app-serving container. |
| `ai_content_client` | string | `""` | ✔ | **Names an existing blob container.** Creates `ai-content/kpi/client/*` and `ai-content/report-summaries/client/*`. |
| `ai_content_report_ids` | list | `[]` | ✔ | Report GUIDs to publish under. Empty = discover matching report IDs from Power BI. |
| `ai_content_ttl_hours` | int | `24` | | Envelope freshness lifetime. |
| `ai_content_alert_days` | int | `7` | | Rolling alert retention. |
| `api_summary_title` | string | — | ✔ | Title shown on the published summary, e.g. "Sales vs Previous Year". |
| `summary_required_delivery_channels` | list | `["local_report","history"]` | | Channels that must succeed before memory rotation advances. Optional API/blob failures stay visible but don't freeze rotation unless listed here. |

### Step 6 — Summary tuning (advanced; defaults are good)

| Key | Default | Explanation |
|---|---|---|
| `summary_word_limit` | `800` | Legacy summary target. |
| `fresh_summary_max_words` | `420` | Fresh summary target length. |
| `fresh_summary_metric_tiles` | `6` | KPI tile count. |
| `summary_candidates_max` | `12` | Max summary perspectives considered. |
| `summary_focus_target_count` | `3` | Number of narrative areas after Overall Performance. |
| `summary_focus_candidate_pool_per_role` | `30` | Members scanned per role. |
| `summary_focus_universe_max_queries` | `4` | Budget for focus universe scans (one per role). |
| `summary_coverage_max_queries` | `3` | **Separate budget** for coverage-only scans, so coverage can never starve the focus rotation. |
| `summary_focus_total_deep_dive_queries` | `15` | Shared deep-dive budget across all focuses. |
| `summary_focus_max_queries_per_focus` | `5` | Per-focus cap within that shared budget. |
| `summary_focus_max_queries` | `4` | Single-focus (R1) deep-dive budget. |
| `summary_focus_max_child_dimensions` | `2` | Child levels explored per deep dive. |
| `summary_focus_max_rows_per_breakdown` | `12` | TOPN bound per breakdown. |
| `summary_focus_members_per_dimension` | `10` | Member candidates re-sliced per breakdown (no new DAX). |
| `summary_dashboard_max_queries` | `2` | R6 lever-scan budget. |
| `summary_dashboard_period_scan_rows` | `400` | Row cap for the period×member scan. |
| `summary_dashboard_entity_rows` | `40` | Entity cards shown. |
| `summary_dashboard_movers` | `5` | Top growth/de-growth rows. |
| `summary_dashboard_tldr` | `5` | TL;DR bullet count. |
| `summary_dashboard_eyebrow` | `"AI Insights"` | Page eyebrow text. |
| `summary_coverage_display_rows` | `8` | Rows shown per level before "Show the remaining N". **Every member is always in the document** — this only truncates display. |
| `summary_coverage_material_change_pct` | `10` | Material movement threshold for severity bands. |
| `summary_coverage_material_share_pct` | `5` | Material business-share threshold. |
| `summary_focus_material_change_pct` | `20` | Materiality floor for focus selection. |
| `summary_focus_min_movement_impact_pct` | `5` | Portfolio eligibility floor. |
| `summary_focus_min_business_share_pct` | `5` | Portfolio share floor. |
| `summary_focus_min_change_pct` | `3` | Minimum change to be eligible. |
| `summary_focus_override_change_pct` | `20` | Magnitude override threshold (**and** the share below). |
| `summary_focus_override_min_impact_share_pct` | `2` | Dual-threshold partner — share measured only against a complete overall total. |
| `summary_focus_fact_overlap_threshold` | `0.6` | Featured-entity overlap above which a story is suppressed as a repeat. |
| `summary_focus_overlap_window_days` | `7` | Window for that comparison. Expired history cannot suppress forever. |
| `summary_focus_rotation_window_days` | `7` | Rotation window. |
| `summary_focus_min_repeat_gap_days` | `2` | Minimum gap before an area repeats. |
| `summary_focus_same_dimension_gap_days` | `2` | Gap before the same dimension repeats. |
| `summary_focus_cooldown_days` | `14` | Focus cooldown. |
| `summary_focus_policy` | `cooldown` | `cooldown` \| `never_repeat`. |
| `summary_focus_schedule` | `{}` | Optional weekday→role prior. Both `{weekday: role}` and `{role: weekday}` accepted. |
| `summary_focus_schedule_weight` | `0.5` | Strength of that soft prior. |
| `summary_focus_timezone` | `Asia/Kolkata` | Timezone for "today". **An unsupported IANA name is rejected loudly.** |
| `summary_focus_reconciliation_tolerance_pct` | `2` | Reconciliation tolerance in the deep dive. |
| `summary_focus_include_driver_bridge` | `true` | Emit the volume vs rate/mix bridge. |
| `summary_focus_include_trend` | `true` | Emit the reconciled business-period trend. |
| `summary_focus_daily_trend_min_days` | `14` | Minimum history for a daily trend. |
| `summary_focus_max_replacements_per_slot` | `1` | Reserve substitutions for duplicate signatures. |
| `summary_memory_policy` | `never_repeat` | Summary memory policy. |
| `summary_memory_cooldown_days` | `14` | Cooldown when policy is `cooldown`. |
| `summary_resurface_change_pct` | `20` | Change needed to resurface a stored summary story. |
| `summary_history_timezone` | `Asia/Kolkata` | Timezone for dated history. |
| `summary_temporal_batch_share` | `0.5` | Batch-date rejection threshold for the summary period resolver. |
| `summary_delayed_after_periods` | `1` | Periods before data is "delayed". |
| `summary_stale_after_periods` | `2` | Periods before data is "stale". |
| `summary_overall_trend_max_queries` | `1` | Overall trend budget. |
| `summary_now_override` | — | Test hook to fix "now". Never set in production. |

### Step 7 — RAG bands and calendar (R6)

| Key | Default | Explanation |
|---|---|---|
| `summary_rag_bands` | object | Band definitions keyed by set name, each declaring a `direction` (`higher_is_better` / `higher_is_worse`) and thresholds. **Merged per set**, so overriding `standard` alone leaves the others intact. |
| `summary_rag_measure_bands` | object | Maps a measure to a band set, e.g. `{"units":"tough","basket_size":"tough"}`. Units and basket size use the tougher band deliberately: standing still on real demand while revenue rises on price is already a problem. |
| `summary_rag_cautions` | object | Caution text per measure/status. |
| `summary_calendar_events` | list | Named events with `current`/`prior` dates, e.g. Eid. **The only way the agent can attribute a broad shift to the calendar** — with none configured it still detects the signature and says "check the calendar" rather than guessing. |
| `summary_calendar_min_members` | `3` | Minimum members before an estate-wide pattern can be called. Two is too few. |
| `summary_calendar_uniform_count_share_pct` | `80` | Share of members moving the same way to count as uniform. |
| `summary_calendar_uniform_business_share_pct` | `80` | Same, weighted by business share. |
| `summary_calendar_cluster_spread_pct` | `8` | Clustering tightness; a scattered move does not fire. |
| `summary_calendar_exception_deviation_pct` | `3` | Deviation beyond which an area is named as *not* explained by the calendar. |

### Step 8 — Insight tuning (77 keys)

**Signals and budgets**

| Key | Default | Explanation |
|---|---|---|
| `insight_max_signals` | `15` | Signal cap outside memory mode. |
| `insight_max_new_per_run` | `4` | Cap in memory mode ("unseen findings"). |
| `insight_max_dq_signals` | `2` | Data-quality sub-cap, so reconciliation noise can't crowd out business findings. |
| `insight_materiality_pct` | `1.0` | Signal materiality floor. |
| `insight_max_scan_queries` | `20` | Shared pre-fork coverage-query cap. |
| `insight_metadata_max_dimensions` | `5` | High-value dimensions selected for broad coverage. |
| `insight_total_gap_scan_budget` | `30` | Global deterministic gap-query cap. |
| `insight_max_gap_dimensions_per_signal` | `3` | Drill dimensions per signal. |
| `insight_max_investigation_rounds` | `9` | Hard per-signal ceiling on gap + investigator REST calls. Normal adaptive path is 0–3. |
| `insight_probe_max_rows` | `20` | Targeted result row cap. |
| `insight_cross_dimensions` | `4` | Cross-dimension scan breadth. |
| `insight_peer_max_dimensions` | `5` | Peer-comparison breadth. |
| `insight_peer_max_rows` | `200` | Peer row cap. |
| `metadata_scope_max_entities` | `500` | Entity discovery cap. |
| `max_rows_per_query` | `15` | Broad-scan truncation heuristic. |

**Statistics**

| Key | Default | Explanation |
|---|---|---|
| `insight_stat_z_cutoff` | `3.0` | Robust-z outlier cutoff. |
| `insight_stat_concentration_pct` | `50.0` | Top-N concentration threshold. |
| `insight_stat_recon_tolerance_pct` | `2.0` | Reconciliation tolerance. |
| `insight_stat_trend_window` | `3` | Trend slope window. |
| `insight_stat_max_candidates` | `20` | Shortlist cap applied **after** story-key suppression. |

**Memory**

| Key | Default | Explanation |
|---|---|---|
| `insight_memory_policy` | `never_repeat` | `never_repeat` \| `cooldown`. Applies to high/period/recent_week/daily only — rolling-week never consults it. |
| `insight_memory_cooldown_days` | `14` | Cooldown length. |
| `insight_reporting_grain` | `month` | Period bucket for the `period_anchor` in story keys, so a new period resurfaces its stories. |
| `insight_candidates_high` | `50` | Per-level candidate cap. |
| `insight_candidates_period` | `10` | As above. |
| `insight_candidates_weekly` | `10` | Caps **both** `recent_week` and `recent_week_rolling`. |
| `insight_candidates_daily` | `10` | As above. |
| `insight_re_alert_growth_pct` | `50` | Growth that resurfaces a stored story. |
| `insight_rolling_report_delta_pct` | `5.0` | Rolling-only drift floor for resurfacing. |
| `insight_history_timezone` | `Asia/Kolkata` | Timezone for dated history. |
| `insight_now_override` | — | Test hook. Never set in production. |

**Temporal (period) level**

| Key | Default | Explanation |
|---|---|---|
| `insight_temporal_batch_share` | `0.5` | If one bucket holds more than this share of the primary metric, the axis is a **load/posting date** and is rejected. This is what correctly disables day-grain on cityflower. |
| `insight_temporal_min_periods` | `6` | Minimum periods for a valid series. |
| `insight_temporal_recon_tolerance_pct` | `2.0` | Series-vs-total reconciliation tolerance. |
| `insight_temporal_max_probes` | `3` | Live axis probes before self-disabling. |
| `insight_temporal_grain_column` | `""` | Force a specific time column. |
| `insight_period_top_movers` | `4` | Period contribution candidates emitted. |
| `insight_period_recent_window` | `12` | Recent-period window. |
| `insight_period_drill` | `true` | One bounded drill on the worst period. |
| `insight_period_drill_top` | `3` | Rows in that drill. |

**Recent-week / daily levels** — all require a genuine, current business **date** axis. On
cityflower these stay disabled by design (batch date + stale data), and the verdict files say so.

| Key | Default | Explanation |
|---|---|---|
| `insight_business_date_override` | `null` | Force a specific date column instead of probing. |
| `insight_week_max_date_probes` | `3` | Date dimensions tried. |
| `insight_week_max_data_lag_days` | `7` | Beyond this the axis is **stale** and the level disables with an honest caveat. |
| `insight_business_timezone` | `naive` | Day-granularity timezone. `"auto"`/unsupported is **rejected loudly**, never silently naive. |
| `insight_week_start` | `monday` | Calendar-week start. |
| `insight_week_mode` | `calendar` | `calendar` (Mon–Sun) or `rolling` (non-overlapping 7-day windows back from today). |
| `insight_week_history_weeks` | `13` | Trailing norm length. |
| `insight_week_materiality_pct` | `2.0` | Must clear this **and** the z-cutoff. |
| `insight_week_z_cutoff` | `2.0` | As above. |
| `insight_week_driver_rows` | `30` | Driver breakdown rows. |
| `insight_daily_rolling_window` | `28` | Trailing reference length. |
| `insight_daily_recent_days` | `3` | Recency window for eligibility. |
| `insight_daily_exclude_today` | `true` | Roll back to the previous operating day so a still-loading day never leaks in. |
| `insight_daily_z_cutoff` | `3.0` | Daily anomaly z. |
| `insight_daily_materiality_pct` | `3.0` | Daily materiality. |
| `insight_daily_min_weekday_occurrences` | `3` | Prior same-weekday points before the weekday test applies. Combined with the trailing test as **AND**, which is what stops a systematic weekend low being flagged. |

**Experimental — leave at defaults**

`insight_rate_outlier_mode` (`off`), `insight_rate_z_cutoff` (3.0),
`insight_rate_min_peers` (8), `insight_rate_min_ordinal_peers` (3),
`insight_rate_exposure_floor_pct` (2.0), `insight_rate_flat_min_pct` (10.0),
`insight_rate_min_abs_impact_pct` (1.0), `insight_rate_prior_share_floor_pct` (0.5),
`insight_thesis_linking_enabled` (false), `insight_thesis_max_links` (2),
`insight_thesis_min_shared` (2), `insight_thesis_min_impact` (0.0),
`insight_thesis_interaction_tol` (0.15).

### Step 9 — Rulebooks (not form fields)

| Artifact | Size | Consumed by | UI treatment |
|---|---|---|---|
| `business_rules.md` | 39–45 KB | Injected via `business_rules_block(state)` into **every** insight/DAX LLM prompt | Markdown editor + file upload; start from `config/business_rules.example.md` |
| `summary_business_rules.md` | 3–4 KB | `summary_business_rules_block(state)`, summary generator + dashboard builder only | Same |

**Must be per-client documents, never one shared file.** They are injected into every prompt,
so one client's scope policy would leak into another's DAX generation. Keeping them separate is
also why `.dockerignore` excludes `config/*/`.

### Step 10 — Deployment inputs (not in `config.json`)

| Input | Explanation |
|---|---|
| Job name | e.g. `insightgen-<client>-daily-job`. |
| Cron (UTC) | Stagger clients — existing jobs use `30 3` and `0 4`. |
| CPU / memory | Existing jobs: 1.0 CPU / 2Gi. |
| `replicaTimeout` | 3600 s today; a run takes ~4–5 min. |
| `replicaRetryLimit` | 1. |
| `AZURE_OPENAI_ENDPOINT` / `_DEPLOYMENT` / `_API_VERSION` | Env vars. Deployment routes the model for Azure. |
| `AZURE_OPENAI_API_KEY` | Job secret. |
| `AZURE_MANAGED_IDENTITY_CLIENT_ID` | `insightgen-mi` client ID. |
| `POWERBI_AUTH_MODE=managed_identity`, `POWERBI_QUERY_API=arrow` | Headless run settings. |
| `AGENT_OUTPUT_FOLDER=outputs` | **Required** if the config says otherwise. |

---

## PART 3 — The probe cycle in the UI

`scripts/probe_summary_universe.py` runs only the pre-fork nodes plus
`summary_focus_universe`, into a **temporary** output + memory location. No LLM, no writes to
production memory/history, no published output. That makes it safe to run repeatedly from a UI.

```
load_config → read_metadata → semantic_profile → baseline_scope → summary_focus_universe
```

**Do not shell out to the script.** Refactor its body into
`src/services/probe.py::run_probe(config: dict) -> ProbeResult` and have both the CLI and the
API call that. Subprocess invocation makes progress streaming and error handling far worse.

### What the probe must surface (this is the UI's most valuable screen)

| Finding | Source | Why the user needs it |
|---|---|---|
| Primary value metric, fact table | `semantic_model_profile.json` | Confirms the model was understood. |
| Entity dimension, or **`entity=unresolved`** | profile | Decides whether `summary_dashboard_entity_role` must be pinned. |
| Measure families (current/prior/change) | profile | A family with no prior measure is reconstructed as `prior = current − change`. |
| Candidate time axes + verdict per axis | temporal gate | Reveals batch/load dates and staleness — decides whether weekly/daily levels can ever work. |
| Data freshness (`data_as_of`) | period resolver | Stale data disables levels. |
| Resolved hierarchy roles + depth | `summary_roles` | Drives focus/coverage role pickers. |
| Members per role, `reconciled`, `pool_capped` | universe scan | **`reconciled=false` means the level's numbers don't add up — do not ship it.** |
| Mirrored roles | `level_signature` | Byte-identical levels are collapsed; the UI should show which. |
| Entity classification (comparable / current-only / prior-only / inactive) | `baseline_scope` | **Populates the comparable/excluded multi-selects.** |

### UX requirements

- Probe is **async** — 30–120 s and 10–20 REST calls. Return a job ID; stream progress.
- Show the live log lines; they are already human-readable
  (`Focus universe: category -> 30 member(s), reconciled=True, pool_capped=True`).
- **Block deployment on a failed probe.** Reconciliation failures must be a hard stop.
- Allow re-probe after changing roles/aliases — this is an iterative loop, not one shot.

---

## PART 4 — Architecture

```
Browser (React SPA or HTMX)
        │  HTTPS + Entra ID (OIDC)
        ▼
FastAPI backend  ── src/services/probe.py     (in-process, reuses agent code)
        │        ── src/services/schema.py    (generated key catalogue)
        │        ── src/services/deploy.py    (ARM: secrets + job upsert)
        │        └─ src/services/validate.py  (prefix uniqueness, container existence…)
        ▼
Azure: Power BI REST · ARM · Blob Storage · ACR
```

Run the API **in the agent image** (or one built `FROM` it) so `src/` imports work directly and
the probe cannot drift from the pipeline it is meant to predict.

### Config storage

Do **not** treat the container-app secret as the source of truth. Store the per-client record
(config JSON + both rulebooks + probe history + who changed what) in the existing
`agent-config` blob container, versioned. Deployment then becomes "render record → write three
secrets → upsert job", and is repeatable and auditable. Today the only copy of a client's live
config is a base64 secret, which is how production silently ran a config 23 keys out of date.

---

## PART 5 — Hosting

| Option | Fit | Notes |
|---|---|---|
| **Azure Container Apps** (same env `insightgen-container-env`) | **Recommended** | Managed identity already has ACR pull, blob data contributor and Power BI workspace access. No request-timeout ceiling. Can run the agent image directly. Add Entra ID auth + internal ingress. |
| Azure App Service (Linux container) | Good | Similar; separate identity/networking to set up. Easy built-in Entra auth. |
| Azure Static Web Apps + Functions | **Avoid** | Managed-function timeout (~45 s on consumption) is shorter than a probe. You'd need Durable Functions — added complexity for no gain. |
| AKS | Overkill | No benefit at this scale. |
| **Local-only (Streamlit / FastAPI on localhost)** | **Best first step** | Uses the existing interactive MSAL token cache, so the hardest blocker (headless Power BI auth) disappears. Single user, no hosting cost, no new attack surface. |

**Recommendation: build local-first, then host.** The local tool delivers most of the value in a
fraction of the time, and every service module you write is reused verbatim by the hosted version.

---

## PART 6 — Major blockers

Ranked by how likely they are to stop the project.

### 1. Headless Power BI authentication — the real blocker

Locally the agent uses **interactive MSAL with a persisted refresh token** at repo-root
`.pbi_token_cache.json`. A server cannot open a browser. Worse, `get_powerbi_token()` does an
**unlocked read-modify-write** of that cache file, so two concurrent probes corrupt it.

Options:
- **Managed identity** — works if the UI is hosted in Azure. `insightgen-mi` already has
  Contributor on both workspaces. Simplest hosted path.
- **Service principal** — needs an app registration, the Power BI tenant setting *"Allow service
  principals to use Power BI APIs"*, and workspace membership. Tenant-admin action.
- **Local-only** — sidesteps it entirely.

Whatever you choose: **never use the interactive cache from a multi-user server.**

### 2. Tenant settings you cannot fix from the UI

- **Execute Queries** must be enabled for the tenant.
- The identity needs **read/build** on the dataset and workspace membership.
- Service principals need explicit tenant enablement.

The UI must **detect and explain** these (a clear "ask your Power BI admin to enable X" screen),
not fail with a raw 401.

### 3. Privileged ARM writes

Creating/updating a Container Apps Job needs Contributor on `Summary_generator_PBI`. A UI holding
that can create arbitrary jobs. Mitigations: Entra ID auth with a restricted group; a
purpose-scoped custom role; server-side allow-list of job-name patterns and images; audit every
deploy. **Do not ship the deploy step without authentication.**

### 4. Schema drift

200 keys read via `state.get(key, default)` across ~40 modules, with **no schema and no
validation**. A hand-written UI schema will silently diverge — and a missing key doesn't error,
it changes behaviour (exactly how R4/R6 stayed off in production for weeks).

**Mitigation (do this first):** add `src/config_schema.py` as the single source of truth —
key, type, default, group, help text, per-client flag. Have `main.py` read defaults from it, the
UI render from it, and a CI test assert that every `state.get("…")` literal in `src/` exists in
the schema. Without this the UI becomes a second source of truth and the drift problem gets worse.

### 5. Long-running, partially-failing operations

The probe is 30–120 s; a full acceptance run is 4–5 min and needs an LLM key. Needs async jobs,
progress streaming, cancellation, and honest partial-failure reporting. Don't model these as
plain request/response.

### 6. Secret handling

Rulebooks base64 to 52–61 KB — past the 32,767-char Windows command-line limit, so the CLI path
fails; use ARM REST with a body file. Never log or echo secret values. Prefer Key Vault
references over inline secrets for the OpenAI key.

### 7. Rulebook authoring is not a form

These are 39–45 KB human-authored documents encoding company calculation policy. A UI can offer
an editor, a diff, a template and a size check — it cannot generate them. Budget for a markdown
editor, not a form. Semantic correctness cannot be validated automatically.

### 8. Destructive-default traps the UI must guard

- `azure_blob_prefix` collision → silently overwrites another client's payloads. **Hard-block.**
- `ai_content_client` naming a container that doesn't exist → publish fails. **Pre-check.**
- `output_folder` ≠ `outputs` in cloud → permission denied. **Force or warn.**
- `summary_r4_enabled` / `summary_r6_enabled` absent → silently reverts to R1–R3.
  **Always write them explicitly.**
- `summary_dashboard_replaces_summary_html` → changes what the live app serves. **Confirm.**

---

## PART 7 — Execution plan

### Phase 0 — Foundation (do this before any UI)

- **0.1** `src/config_schema.py`: catalogue all 200 keys (key, type, default, group, help,
  per-client, advanced). Seed from `config/config.example.json` plus the tables in Part 2.
- **0.2** Refactor `main.py` to read defaults from the schema.
- **0.3** CI test: every `state.get("<literal>")` in `src/` exists in the schema (guards drift).
- **0.4** `src/services/probe.py::run_probe(config) -> ProbeResult` — lift the body of
  `scripts/probe_summary_universe.py`; make the script a thin caller.
- **0.5** `src/services/validate.py` — prefix uniqueness, container existence, output-folder
  rule, R4/R6 explicitness, timezone validity, role-vs-probe consistency.

*Exit:* `run_probe()` callable in-process; schema test green.

### Phase 1 — Local UI (highest value, no auth blocker)

- **1.1** FastAPI app + async job runner (in-memory queue is fine locally).
- **1.2** `POST /api/probe` → job ID; `GET /api/probe/{id}` → status + streamed log; `ProbeResult` JSON.
- **1.3** Wizard UI, steps 1–10 from Part 2, rendered from the schema. Advanced keys behind
  "Show advanced".
- **1.4** Probe results screen (Part 3 table), with **comparable/excluded multi-selects populated
  from the actual entity classification** and role pickers from resolved roles.
- **1.5** Rulebook editor (two tabs, upload, template, size indicator).
- **1.6** Validation panel — blocking errors vs warnings.
- **1.7** Write `config/<client>/` (three files) and offer a download bundle.

*Exit:* a new client can be configured end-to-end locally and run with
`python -m src.main --config config/<client>/config.json`.

### Phase 2 — Deployment automation

- **2.1** `src/services/deploy.py`: base64 the three files, PATCH/PUT the job via ARM REST with a
  body file, poll provisioning state.
- **2.2** Upsert semantics: create if absent, update if present; never silently drop unrelated
  secrets (read existing, merge, write).
- **2.3** "Run now" → `az containerapp job start` equivalent; stream execution status.
- **2.4** Post-run verification: execution status, blob timestamps under the client's prefix,
  and `scripts/audit_summary_dashboard.py` when R6 is on.
- **2.5** Config-record store in the `agent-config` blob container, versioned with author + timestamp.

*Exit:* a client goes from blank form to a scheduled, verified job.

### Phase 3 — Hosting and hardening

- **3.1** Containerize the API `FROM` the agent image; push to `insightgenacr`.
- **3.2** Deploy to `insightgen-container-env` with internal ingress.
- **3.3** Entra ID auth; restrict to an onboarding group.
- **3.4** Switch Power BI auth to managed identity (`POWERBI_AUTH_MODE=managed_identity`);
  confirm the interactive cache path is never reached server-side.
- **3.5** Least-privilege ARM role; server-side allow-list of job names/images.
- **3.6** Audit log of every probe and deploy.

*Exit:* the team onboards a client without touching a terminal.

### Phase 4 — Nice to have

Live preview via `scripts/preview_summary_dashboard.py`; config diff between clients;
clone-a-client; probe history; scheduled re-probe to catch model drift.

---

## PART 8 — Acceptance criteria

1. A new client can be onboarded end-to-end with no terminal use.
2. The UI refuses to deploy when: prefix collides, `ai_content_client` container is missing,
   probe reconciliation failed, or R4/R6 flags are unset.
3. Every one of the 200 keys is settable, with help text, and defaults match `config_schema.py`.
4. Re-onboarding scanb through the UI reproduces `config/scanb/config.json` **byte-identically**
   — the regression test that proves the UI models the real surface.
5. The probe never writes to production memory, history, or published output.
6. Deploying never drops or corrupts an existing secret.
7. The schema-drift CI test is green.

---

## Appendix — Reference commands

```bash
# Resolve dataset from a report ID
GET https://api.powerbi.com/v1.0/myorg/groups/{workspaceId}/reports/{reportId}   # -> datasetId

# Probe (safe, no LLM, no writes)
python scripts/probe_summary_universe.py --config config/<client>/config.json

# Full local run
python -m src.main --config config/<client>/config.json

# Audit a delivered R6 artifact
python scripts/audit_summary_dashboard.py outputs_<client>

# Offline replays (no auth/LLM) - all must pass
python scripts/replay_summary_dashboard.py
python scripts/replay_summary_coverage.py
python scripts/replay_summary_portfolio.py
python scripts/replay_summary_r4_isolation.py
python scripts/replay_summary_rotation.py
python scripts/replay_metadata_scanner.py
python scripts/replay_stat_detector.py
python scripts/replay_novelty_filter.py
python scripts/replay_evidence_assembler.py

# Deploy a job (secrets exceed the CLI arg limit - use a body file)
az rest --method PATCH \
  --uri "https://management.azure.com/subscriptions/{sub}/resourceGroups/Summary_generator_PBI/providers/Microsoft.App/jobs/{job}?api-version=2024-03-01" \
  --headers "Content-Type=application/json" --body @patch.json
```
