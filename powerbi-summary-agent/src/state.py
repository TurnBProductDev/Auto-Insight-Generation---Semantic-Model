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
    summary_visual_enabled: bool
    summary_candidates_max: int
    summary_temporal_batch_share: float
    summary_delayed_after_periods: int
    summary_stale_after_periods: int
    summary_memory_enabled: bool
    summary_memory_root: str
    summary_memory_policy: str
    summary_memory_cooldown_days: int
    summary_resurface_change_pct: float
    summary_history_enabled: bool
    summary_now_override: str                 # optional ISO 'today' for deterministic offline tests

    # --- daily focus + deep dive (summary R1) ---
    summary_focus_enabled: bool
    summary_focus_timezone: str
    summary_focus_policy: str
    summary_focus_cooldown_days: int
    summary_focus_same_dimension_gap_days: int
    summary_focus_members_per_dimension: int
    summary_focus_material_change_pct: float
    summary_focus_deep_dive_enabled: bool
    summary_focus_max_queries: int
    summary_focus_max_child_dimensions: int
    summary_focus_max_rows_per_breakdown: int
    summary_focus_reconciliation_tolerance_pct: float
    summary_focus_include_driver_bridge: bool
    summary_focus_include_trend: bool
    summary_focus_daily_trend_enabled: bool
    summary_focus_daily_trend_min_days: int
    summary_focus_hierarchy_overrides: Dict[str, Any]
    # --- R2 editorial rhythm ---
    summary_focus_schedule: Dict[str, Any]        # weekday -> role(s) soft prior
    summary_focus_schedule_weight: float
    summary_focus_override_change_pct: float      # override lane: magnitude threshold
    summary_focus_override_min_impact_share_pct: float  # override lane: materiality threshold
    # --- R3 advanced novelty ---
    summary_focus_fact_overlap_threshold: float   # suppress a focus that repeats a recent story
    summary_focus_overlap_window_days: int        # recency window for overlap suppression
    summary_focus_public_metadata: bool           # expose dailyFocus in the API payload
    summary_recent_focus: List[Dict[str, Any]]    # novelty_filter -> deep dive signature compare
    summary_selected_focus: Dict[str, Any]    # novelty_filter -> deep dive + commit (R4: alias -> first focus)
    summary_focus_evidence: Dict[str, Any]    # deep-dive node artifact (R4: alias -> first focus evidence)
    # --- R4 balanced business summary (multi-focus portfolio) ---
    summary_r4_enabled: bool                       # master switch; false reproduces R1-R3 single-focus
    summary_focus_allowed_roles: List[str]         # canonical roles that may be a primary focus
    summary_focus_role_aliases: Dict[str, Any]     # model role/dimension name -> canonical role
    summary_focus_candidate_pool_per_role: int     # rotation breadth (>= display rows)
    summary_focus_target_count: int                # target number of focus areas (not a minimum)
    summary_focus_min_movement_impact_pct: float   # materiality gate: sibling movement impact
    summary_focus_min_business_share_pct: float    # materiality gate: business share
    summary_focus_min_change_pct: float            # materiality gate: meaningful movement
    summary_focus_rotation_window_days: int        # weekly coverage window
    summary_focus_min_repeat_gap_days: int         # short exact-area repeat gap
    summary_focus_universe_max_queries: int        # pre-selection breadth budget
    summary_overall_trend_enabled: bool
    summary_overall_trend_max_queries: int
    summary_focus_total_deep_dive_queries: int     # post-selection depth budget (shared)
    summary_focus_max_queries_per_focus: int
    summary_focus_max_replacements_per_slot: int
    summary_required_delivery_channels: List[str]  # channels that must succeed before memory commit
    summary_focus_universe: Dict[str, Any]         # deterministic per-role universe scans + diagnostics
    summary_overall_performance: Dict[str, Any]    # deterministic overall business package
    summary_selected_focuses: List[Dict[str, Any]] # ordered portfolio (R4)
    summary_focus_evidence_by_key: Dict[str, Any]  # per-focus deep-dive evidence keyed by focus_key
    summary_weekly_coverage: Dict[str, Any]        # weekly rotation audit surfaced to generator
    summary_portfolio_reserves: List[Dict[str, Any]]  # ranked reserve candidates for slot replacement
    summary_pending_area_keys: List[str]           # committed after validated delivery
    summary_pending_focus_keys: List[str]
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
    insight_stat_z_cutoff: float
    insight_stat_concentration_pct: float
    insight_stat_recon_tolerance_pct: float
    insight_stat_trend_window: int
    insight_stat_max_candidates: int
    # rate-outlier lens (peer growth-rate detection): off | shadow | report
    insight_rate_outlier_mode: str
    insight_peer_max_dimensions: int
    insight_peer_max_rows: int
    insight_rate_z_cutoff: float
    insight_rate_min_peers: int
    insight_rate_prior_share_floor_pct: float
    insight_rate_exposure_floor_pct: float
    insight_rate_min_abs_impact_pct: float
    insight_rate_flat_min_pct: float
    insight_rate_min_ordinal_peers: int
    # cross-signal thesis linking (Phase 9): connect findings that may share one event
    insight_thesis_linking_enabled: bool
    insight_thesis_max_links: int
    insight_thesis_min_shared: int
    insight_thesis_interaction_tol: float
    insight_thesis_min_impact: float
    metadata_scope_max_entities: int
    insight_metadata_max_dimensions: int
    insight_cross_dimensions: int          # entity x category cross scans (top-N category dims)
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
    insight_peer_coverage: Dict[str, Any]   # Phase 1: per-dimension rate-outlier evidence eligibility
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
    insight_rate_shadow_candidates: List[Dict[str, Any]]  # Phase 5: shadow-mode rate findings (not reported)
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
    insight_theses: List[Dict[str, Any]]          # Phase 9: cross-signal thesis links (hedged)
    insight_report: str

    # --- control / diagnostics ---
    errors: Annotated[List[str], operator.add]
    logs: Annotated[List[str], operator.add]
    fatal: bool           # pre-fork stages only (load_config / read_metadata)
    summary_fatal: bool   # summary branch short-circuit (validate_dax)
    insight_fatal: bool   # insight branch short-circuit (insight_scan_validator)
