"""Shared LangGraph state for the Power BI Report Summary Agent.

`logs`/`errors` are reducer-backed (operator.add) so the two post-fork
branches (summary + insight) can both append in the same superstep without
tripping LangGraph's single-writer InvalidUpdateError. Each node therefore
returns only its OWN new lines (see RunLogger) and LangGraph concatenates.
"""

import operator
from typing import Annotated, Any, Dict, List, TypedDict


class SummaryAgentState(TypedDict, total=False):
    # --- config (Node 1) ---
    tenant_id: str
    workspace_id: str
    dataset_id: str
    output_folder: str
    summary_word_limit: int
    fresh_summary_enabled: bool
    fresh_summary_max_words: int
    summary_visual_enabled: bool
    summary_candidates_max: int
    summary_temporal_batch_share: float
    summary_delayed_after_periods: int
    summary_stale_after_periods: int
    summary_memory_enabled: bool
    summary_memory_root: str
    summary_memory_policy: str
    summary_memory_cooldown_days: int
    summary_history_enabled: bool
    max_rows_per_query: int
    ai_provider: str
    model: str
    max_tokens: int
    execution_mode: str
    fabric_definitions: bool
    config_path: str                        # active config file; Node 1 finds business_rules.md beside it
    business_rules: str                     # config/business_rules.md text (loaded by Node 1)
    config: Dict[str, Any]

    # --- insight branch config ---
    insight_max_signals: int
    insight_max_investigation_rounds: int
    insight_max_scan_queries: int
    insight_probe_max_rows: int
    insight_materiality_pct: float
    insight_max_dq_signals: int
    insight_tiles_enabled: bool
    insight_stat_z_cutoff: float
    insight_stat_concentration_pct: float
    insight_stat_recon_tolerance_pct: float
    insight_stat_trend_window: int
    insight_stat_max_candidates: int
    metadata_scope_max_entities: int
    insight_metadata_max_dimensions: int
    insight_total_gap_scan_budget: int
    insight_max_gap_dimensions_per_signal: int
    # business-rule scope (mirrors config/business_rules.md); drives the
    # evidence-contract population classifier and the reuse gate
    insight_comparable_population: List[str]
    insight_excluded_entities: List[str]

    # --- cross-run insight memory (Phase 1) ---
    insight_memory_enabled: bool
    insight_memory_root: str                  # cloud mode: isolated hydrated runtime directory
    insight_memory_policy: str               # "never_repeat" | "cooldown"
    insight_memory_cooldown_days: int
    insight_max_new_per_run: int
    insight_reporting_grain: str             # period-anchor grain: "month" | "year" | "day"
    insight_candidates_high: int
    insight_candidates_weekly: int
    insight_candidates_daily: int

    # --- temporal (Phase 2): validated sub-annual level ---
    insight_temporal_enabled: bool
    insight_temporal_batch_share: float
    insight_temporal_min_periods: int
    insight_candidates_period: int
    insight_period_top_movers: int
    insight_period_recent_window: int
    insight_temporal_recon_tolerance_pct: float
    insight_temporal_max_probes: int
    insight_temporal_grain_column: str
    insight_period_drill: bool
    insight_period_drill_top: int
    insight_temporal_verdict: Dict[str, Any]      # grain gate verdict (report caveat)
    insight_temporal_gated_tables: List[str]      # date tables the gate rejected (skip trend)
    insight_temporal_drill: Dict[str, Any]        # worst-period x primary-dimension attribution

    # --- recent-week (Phase 3): previous-complete-week monitoring ---
    insight_recent_week_enabled: bool
    insight_business_date_override: str
    insight_week_max_date_probes: int
    insight_week_start: str
    insight_business_timezone: str
    insight_week_max_data_lag_days: int
    insight_week_history_weeks: int
    insight_week_materiality_pct: float
    insight_week_z_cutoff: float
    insight_week_driver_rows: int
    insight_now_override: str                      # optional ISO 'today' for deterministic offline tests
    insight_recent_week_verdict: Dict[str, Any]   # capability/freshness gate verdict (report caveat)
    insight_recent_week_drivers: Dict[str, Any]   # target-vs-previous week x primary-dimension drivers
    insight_week_mode: str                          # "calendar" | "rolling"

    # --- business-day source (Phase 3b): shared validated fetch, consumed by
    # both insight_recent_week (folding) and insight_daily (incident detection) ---
    insight_business_day_source: Dict[str, Any]   # axis/rows/operating_days/data_as_of, post-validation
    insight_business_day_verdict: Dict[str, Any]  # capability/freshness gate verdict (report caveat)

    # --- daily anomaly incidents (Phase 3b) ---
    insight_daily_enabled: bool
    insight_daily_rolling_window: int
    insight_daily_recent_days: int
    insight_daily_exclude_today: bool
    insight_daily_z_cutoff: float
    insight_daily_materiality_pct: float
    insight_daily_min_weekday_occurrences: int
    insight_daily_verdict: Dict[str, Any]         # capability/freshness gate verdict (report caveat)

    # --- rolling-week re-alerting (Phase 3b) ---
    insight_re_alert_growth_pct: float
    insight_rolling_report_delta_pct: float
    insight_rolling_observation: Dict[str, Any]   # always-emitted raw reading, even when inactive

    # --- shared pre-fork artifacts ---
    model_metadata: Dict[str, Any]          # Node 2
    pbi_token: str                          # Node 2 (shared by both branches)
    semantic_model_profile: Dict[str, Any]  # deterministic metadata interpretation
    baseline_scope_evidence: Dict[str, Any] # pre-fork entity current/prior rows
    baseline_coverage_clean_data: Dict[str, Any] # pre-fork metadata coverage shared by branches
    resolved_entity_scope: Dict[str, Any]   # automatic scope + business-rule override
    report_understanding: Dict[str, Any]    # Node 3

    # --- summary branch artifacts ---
    dax_plan: Dict[str, Any]                # Node 4
    generated_dax_queries: List[Dict[str, Any]]   # Node 5
    validated_dax_queries: List[Dict[str, Any]]   # Node 6
    skipped_dax_queries: List[Dict[str, Any]]     # Node 6 (invalid; eligible for repair)
    raw_pbi_results: Dict[str, Any]         # Node 7
    clean_summary_data: Dict[str, Any]      # Node 8
    report_summary: str                     # Node 9
    summary_period_context: Dict[str, Any]
    summary_candidates: List[Dict[str, Any]]
    summary_eligible_candidates: List[Dict[str, Any]]
    summary_novelty: Dict[str, Any]
    summary_memory_hydration: Dict[str, Any]
    fresh_summary: Dict[str, Any]
    summary_pending_keys: List[str]
    summary_memory_commit: Dict[str, Any]

    # --- insight branch artifacts ---
    insight_dax_plan: Dict[str, Any]
    insight_generated_dax_queries: List[Dict[str, Any]]
    insight_validated_dax_queries: List[Dict[str, Any]]
    insight_skipped_dax_queries: List[Dict[str, Any]]
    insight_raw_results: Dict[str, Any]
    insight_clean_data: Dict[str, Any]
    insight_stat_candidates: Dict[str, Any]
    insight_evidence_contracts: Dict[str, Any]    # evidence_assembler: per-scan-table provenance
    insight_evidence_briefs: Dict[str, Any]       # evidence_assembler: per-signal reuse/gap brief
    insight_coverage_matrix: Dict[str, Any]       # evidence_assembler: per-dimension coverage quality
    insight_gap_evidence: Dict[str, Any]          # insight_gap_scan: templated fills for brief gaps
    insight_query_cache: Dict[str, Any]           # shared sequential cache: gap scan -> investigator
    insight_eligible_candidates: Dict[str, Any]   # novelty_filter: unseen candidates only
    insight_novelty: Dict[str, Any]               # novelty_filter/signal_detector: run summary
    insight_memory_commit: Dict[str, Any]         # save_outputs result; gates cloud publication
    insight_signals: List[Dict[str, Any]]
    insight_investigations: List[Dict[str, Any]]
    insight_report: str

    # --- control / diagnostics ---
    errors: Annotated[List[str], operator.add]
    logs: Annotated[List[str], operator.add]
    fatal: bool           # pre-fork stages only (load_config / read_metadata)
    summary_fatal: bool   # summary branch short-circuit (validate_dax)
    insight_fatal: bool   # insight branch short-circuit (insight_scan_validator)
