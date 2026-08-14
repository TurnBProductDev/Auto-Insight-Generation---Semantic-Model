"""Sales vs Previous Year - today's report, written down.

This declares what the pipeline already does. It is the reference a second
report of the same kind is copied from, and the proof that the assembly path
reproduces the fixed graph: `replay_domain_assembly.py` builds from this spec
and compares node for node and edge for edge against `build_graph()`.

`nodes` is deliberately the **full** default set. Sales YoY runs everything, so
listing it explicitly is what makes the comparison meaningful - a spec that said
"use the defaults" would prove nothing.
"""

from __future__ import annotations

from ....kernel.report import ReportSpec

#: Today's node sequence, in graph-registration order. Derived from
#: `graph.NODE_FACTORIES`; the replay asserts the two cannot drift apart.
NODES: tuple[str, ...] = (
    # Pre-fork
    "load_config", "read_metadata", "semantic_profile", "baseline_scope",
    "baseline_coverage", "understand_report",
    # Summary branch
    "plan_dax", "generate_dax", "validate_dax", "execute_dax",
    "normalize_results", "generate_summary", "summary_period_resolver",
    "summary_focus_universe", "summary_candidate_builder",
    "summary_overall_performance", "summary_novelty_filter",
    "summary_focus_evidence", "summary_multi_focus_evidence",
    "fresh_summary_generator", "summary_dashboard_build",
    "fresh_summary_validator", "summary_branch_done",
    # Insight branch
    "insight_normalize", "insight_temporal", "insight_business_day_source",
    "insight_recent_week", "insight_daily", "insight_evidence_catalog",
    "insight_stat_detector", "insight_novelty_filter", "insight_signal_detector",
    "insight_evidence_assembler", "insight_gap_scan", "insight_investigator",
    "insight_thesis_linker", "insight_synthesizer", "insight_branch_done",
    # Join
    "save_outputs",
)

SPEC = ReportSpec(
    report_id="sales_yoy",
    report_name="Sales vs Previous Year",
    domain="sales",
    chain_id="sales",
    cadence="daily",
    spine="period_over_period",
    kpis=("revenue", "quantity", "transactions"),
    axes=("division", "department", "section", "category", "store"),
    layout="balanced_multi_focus",
    rules=("summary_business_rules",),
    thresholds={
        # The R5 coverage bands, as the committed config sets them.
        "material_change_pct": 10.0,
        "material_share_pct": 5.0,
    },
)
