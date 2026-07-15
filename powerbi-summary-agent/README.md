# Power BI Report Summary Agent

A LangGraph pipeline that reads a Power BI semantic model, chooses the
measures and dimensions from metadata, executes its own DAX, and creates two
outputs in one run:

- `report_summary.md`: descriptive reporting — what the numbers are.
- `insight_report.md`: investigative reporting — what contributed to the
  movements, with evidence, confidence, and follow-up questions.

The user never supplies DAX or a model-specific scan list. Company calculation
and reporting policy comes from `config/business_rules.md`.

## Pipeline

The structural choices happen before the graph forks. `semantic_profile`
derives measure families, current/prior/change roles, the fact table, entity
grain, drill dimensions, and time fields from semantic-model metadata.
`baseline_scope` then discovers entity lifecycle from actual current/prior
activity, while configured business-rule scope—when present—remains the
authoritative override and is validated against the data. `baseline_coverage`
executes a bounded metadata-templated diagnostic portfolio once and shares it
with both branches.

```text
load_config -> read_metadata -> semantic_profile -> baseline_scope
    -> baseline_coverage -> understand_report
    |-> plan_dax -> generate_dax -> validate_dax -> execute_dax
    |     -> normalize_results -> generate_summary -> summary_branch_done ----|
    `-> insight_normalize -> insight_evidence_catalog -> insight_stat_detector
          -> insight_signal_detector -> insight_evidence_assembler
          -> insight_gap_scan -> insight_investigator -> insight_synthesizer
          -> insight_branch_done ---------------------------------------------|
                                                        save_outputs -> END
```

After `understand_report`, both branches run concurrently and meet at a joined
barrier. A post-fork failure in one branch does not block the other report.

### Shared metadata scanner

| Stage | Type | Responsibility |
|---|---|---|
| Metadata reader | REST + deterministic | Reads tables, columns, measures, relationships, descriptions, types, formats, categories, hidden flags, and sanitized measure expressions |
| Semantic profiler | Deterministic | Builds coherent value/volume measure bundles and ranks compatible entity, business, and time dimensions from metadata |
| Scope baseline | Deterministic DAX | Finds comparable, current-only, and prior-only entities using metadata-selected measures; validates business-rule overrides |
| Coverage baseline | Deterministic DAX | Builds bounded totals, mover tails, concentration, trend, and cross-slice queries with construction-time provenance |
| Scope validator | Deterministic | Rejects any prior/change query that cannot prove the correct comparable entity filter or that includes excluded/current-only entities |

### Summary branch

The LLM understands the report, plans summary intents, and generates DAX. Each
query is checked against metadata and the resolved entity scope. Invalid or
failed LLM-generated DAX gets one repair attempt; metadata templates are never
LLM-repaired because doing so would invalidate their provenance. The final
summary also receives the shared scope and diagnostic baseline.

### Insight branch

| Stage | Type | Responsibility |
|---|---|---|
| Evidence catalog | Deterministic | Records population, grouping, metric roles, completeness, TOPN/truncation, filters, and DAX hash for every table |
| Stat detector | Deterministic | Contribution bridges, concentration, robust-z outliers, trends/change-points, reconciliation, lifecycle findings, and exact price/volume decomposition |
| Signal detector | Structured LLM | Selects material candidates while code copies the exact computed values and enforces business/data-quality caps |
| Evidence assembler | Deterministic | Reuses safe facts, refuses partial evidence as complete coverage, and identifies only genuine drill gaps |
| Gap scan | Deterministic DAX | Runs metadata-compatible targeted queries under per-signal and global budgets, with shared DAX-hash caching |
| Investigator | Tool-calling LLM | Uses already assembled evidence first, then spends only the remaining 0–3 normal-path probe allowance; every attempt is audited |
| Synthesizer | LLM | Writes the insight report using hedged contribution/correlation language, never asserted root cause |

For a revenue change `R1 - R0` with volume `Q`, the exact decomposition is:

```text
volume effect = (Q1 - Q0) * (R0 / Q0)
rate effect   = Q1 * ((R1 / Q1) - (R0 / Q0))
```

The rate effect can include price, mix, and other revenue-per-unit effects; it
is not presented as pure price unless the model provides evidence for that.

## Setup and run

The repo ships templates instead of real credentials/config. On a fresh clone,
first create your own copies (these three files are gitignored):

```bash
cd powerbi-summary-agent

# 1. LLM + Power BI credentials
cp .env.example .env
#    then edit .env: set LLM_PROVIDER and the matching API key/endpoint.

# 2. Target model (tenant/workspace/dataset GUIDs) + tunable knobs
cp config/config.example.json config/config.json
#    then edit config/config.json: replace the PASTE_ GUIDs with your own.
#    (main.py refuses to run while any PASTE_ placeholder remains.)

# 3. Optional: company calculation/reporting rules
cp config/business_rules.example.md config/business_rules.md
#    edit or delete. If absent, the agent runs with no company overrides.
#    Keep any comparable/excluded entity codes in sync with the
#    insight_comparable_population / insight_excluded_entities in config.json.
```

Then install and run:

```bash
pip install -r requirements.txt
python -m src.main
python -m src.main --config path/to/config.json
```

Run from the `powerbi-summary-agent` directory. Authentication uses the shared
repo-root `.pbi_token_cache.json` (also gitignored — created on first login).
The first login may open a browser; later runs use the cached refresh token
silently. The Power BI Execute Queries tenant setting and dataset read/build
permission are required.

> Offline replay scripts (`scripts/replay_*.py`) read fixtures from `outputs/`,
> which is gitignored. On a fresh clone those artifacts don't exist yet — do one
> live `python -m src.main` run first to populate `outputs/`, then replay.

The provider is a three-way switch: `azure_openai`, `anthropic`, or `openai`.
For Azure, `AZURE_OPENAI_DEPLOYMENT` selects the deployed model. DAX execution
defaults to Python/MSAL REST; the optional PowerShell mode applies only to the
summary branch.

## Outputs

Artifacts are written per node so partial progress survives an early stop.
Important files include:

```text
business_rules_snapshot.md       model_metadata.json
semantic_model_profile.json      baseline_scope_evidence.json
resolved_entity_scope.json       baseline_coverage_clean_data.json

generated_dax_plan.json          generated_dax_queries.json
validated_dax_queries.json       raw_pbi_results.json
clean_summary_data.json          report_summary.md / .html

insight_evidence_contracts.json  insight_stat_candidates.json
insight_signals.json             insight_evidence_briefs.json
insight_coverage_matrix.json     insight_gap_evidence.json
insight_investigations.json      insight_report.md / .html

run_log.txt
```

## Configuration

Operational settings live in `config/config.json`; `config/agent_settings.json`
is not read.

| Key | Meaning |
|---|---|
| `tenant_id`, `workspace_id`, `dataset_id` | Target tenant, workspace, and semantic model |
| `ai_provider`, `model`, `max_tokens` | LLM routing and output ceiling |
| `execution_mode` | `python` or `powershell` for summary DAX |
| `fabric_definitions` | Best-effort Fabric/TMSL measure-expression enrichment |
| `summary_word_limit`, `max_rows_per_query` | Report target and broad-query row cap |
| `metadata_scope_max_entities` | Entity discovery cap |
| `insight_max_scan_queries` | Shared metadata coverage-query cap |
| `insight_metadata_max_dimensions` | Number of high-value metadata dimensions selected for broad coverage |
| `insight_max_signals`, `insight_max_dq_signals` | Signal caps |
| `insight_max_gap_dimensions_per_signal` | Targeted drill dimensions considered per signal |
| `insight_total_gap_scan_budget` | Global deterministic gap-query cap |
| `insight_max_investigation_rounds` | Hard per-signal combined gap/investigation ceiling; the normal adaptive investigator path is 0–3 |
| `insight_probe_max_rows` | Targeted result row cap |
| `insight_materiality_pct` | Signal materiality floor |
| `insight_stat_*` | Outlier, concentration, reconciliation, trend, and candidate limits |
| `insight_comparable_population`, `insight_excluded_entities` | Optional machine-enforced business-rule scope; data discovery audits it |

## Business rules

`config/business_rules.md` is authoritative company logic and is separate from
permanent guardrails in `prompts/_global_rules.md`.

- Node 1 reads the file beside the active config and snapshots the exact text to
  `outputs/business_rules_snapshot.md`.
- Every LLM prompt receives the rules as authoritative guidance.
- Comparable-population rules are additionally enforced in code: shared
  metadata templates, summary validation and repair, gap probes, and
  investigator probes all pass through the deterministic scope validator.
- New/current-only entities remain available for current-period contribution
  reporting but cannot leak into comparable YoY totals or denominators.

## Offline verification

These commands require no authentication or LLM call:

```bash
python -m compileall -q src scripts
python scripts/replay_metadata_scanner.py
python scripts/replay_stat_detector.py
python scripts/replay_stat_detector.py --synthetic
python scripts/replay_evidence_assembler.py
```

The metadata replay validates generated object references, comparable-scope
leak rejection, provenance completeness, multi-member filters, exact
price/volume reconciliation, and adaptive budgets. The detector replay checks
saved data plus NaN/Infinity, empty, zero-spread, and level-shift edge cases.
Replay artifacts go to `outputs_replay/`.

For a focused live REST acceptance check of only the metadata-built baseline
and coverage portfolio:

```bash
python scripts/check_metadata_scan_live.py
```
