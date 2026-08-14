"""LangGraph workflow wiring for the Power BI Report Summary Agent.

Fan-out / fan-in: after understand_report the graph forks into two branches
that run concurrently (LangGraph executes independent nodes of the same
superstep on a thread pool) and reconverge at save_outputs:

START -> load_config -> read_metadata -> semantic_profile -> baseline_scope
      -> baseline_coverage -> understand_report
    +-> plan_dax -> generate_dax -> validate_dax -> execute_dax
    |       -> normalize_results -> summary_period_resolver
    |       -> summary_candidate_builder -> summary_novelty_filter
    |       -> summary_focus_evidence -> fresh_summary_generator
    |       -> fresh_summary_validator -> summary_branch_done --------------+
    +-> insight_normalize -> insight_temporal -> insight_business_day_source
            -> insight_recent_week -> insight_daily -> insight_evidence_catalog
            -> insight_stat_detector -> insight_novelty_filter
            -> insight_signal_detector -> insight_evidence_assembler -> insight_gap_scan
            -> insight_investigator -> insight_thesis_linker -> insight_synthesizer
            -> insight_branch_done ----------------------------------------------+
                                                                                   |
                                             both barriers -> save_outputs -> END -+

Conditional edges:
  * metadata missing (pre-fork `fatal`)        -> save_outputs (stop everything)
  * no valid summary DAX (`summary_fatal`)     -> fresh summary uses shared baseline evidence

The join is an explicit barrier: only summary_branch_done and
insight_branch_done edge into save_outputs (via a joined edge that waits for
both), plus the single pre-fork fatal edge - never a mix of mid-branch edges.
"""

from langgraph.graph import END, START, StateGraph

from .state import SummaryAgentState
from .tools import file_io
from .tools import html_report
from .tools import insight_memory
from .tools import powerbi_executor as pbi
from .utils.logger import RunLogger

from .agents import (
    metadata_reader,
    semantic_profiler,
    baseline_scope,
    baseline_coverage,
    report_understanding,
    dax_planner,
    dax_generator,
    dax_validator,
    result_normalizer,
    summary_generator,
    summary_period_resolver,
    summary_focus_universe,
    summary_candidate_builder,
    summary_overall_performance,
    summary_novelty_filter,
    summary_focus_evidence,
    summary_multi_focus_evidence,
    fresh_summary_generator,
    summary_dashboard_builder,
    fresh_summary_validator,
    insight_result_normalizer,
    insight_temporal,
    insight_business_day_source,
    insight_recent_week,
    insight_daily,
    insight_stat_detector,
    insight_novelty_filter,
    insight_signal_detector,
    evidence_contract,
    evidence_assembler,
    insight_gap_scan,
    insight_investigator,
    insight_thesis_linker,
    insight_synthesizer,
)


# --- Node 1: Config Loader ---------------------------------------------------
def load_config(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 1: config loaded.")
    log.info(
        f"  workspace={state.get('workspace_id')} dataset={state.get('dataset_id')} "
        f"provider={state.get('ai_provider')} model={state.get('model')} "
        f"exec_mode={state.get('execution_mode')}"
    )
    # Load the company business rules here (not in main.py) so that any direct
    # graph caller - app.invoke(state) without going through main - still picks
    # them up and can't accidentally bypass them.
    rules = file_io.read_business_rules(state.get("config_path")).strip()
    # Always (over)write the snapshot so a previous run's snapshot can't linger
    # as stale once the rules file is removed or emptied.
    if rules:
        file_io.write_text(state, "business_rules_snapshot.md", rules + "\n")
        log.info(f"  business rules loaded and snapshotted ({len(rules.splitlines())} lines).")
    else:
        file_io.write_text(state, "business_rules_snapshot.md", "No business rules loaded.\n")
        log.info("  no business rules file found (config/business_rules.md); snapshot notes none in force.")
    return {"fatal": False, "business_rules": rules, **log.updates()}


# --- Shared repair/execute helper ---------------------------------------------
def _repair_and_execute(state: dict, md: dict, entry: dict, error_text: str) -> dict:
    """One-shot repair: ask the LLM to fix DAX that failed validation or execution,
    re-validate it, and run it once more if it now checks out."""
    fixed_dax = dax_generator.repair(state, entry, error_text)
    reasons = dax_validator.validate_one(fixed_dax, md)
    from .agents.scope_validator import validate_comparable_scope
    reasons += validate_comparable_scope(fixed_dax, state, entry.get("contract_hint"))
    if reasons:
        return {
            "status": "failed",
            "purpose": entry.get("purpose", ""),
            "query": fixed_dax,
            "error": (
                f"still invalid after repair attempt: {'; '.join(reasons)} "
                f"(original: {error_text})"
            ),
        }
    one = pbi.execute_python(
        state["workspace_id"], state["dataset_id"],
        [{"name": entry["name"], "dax": fixed_dax, "purpose": entry.get("purpose", "")}],
        token=state.get("pbi_token"),
    )
    return one[entry["name"]]


def _run_with_repairs(state: dict, log: RunLogger, raw: dict,
                      queries: list, skipped: list, label: str) -> dict:
    """Apply the one-shot repair loop to validator-skipped and executor-failed queries."""
    md = state["model_metadata"]

    skipped_names = {e["name"] for e in skipped}
    for entry in skipped:
        if entry.get("generation") == "metadata_template" or entry.get("contract_hint"):
            raw[entry["name"]] = {
                "status": "failed", "purpose": entry.get("purpose", ""),
                "query": entry.get("dax", ""),
                "error": "metadata template failed validation; not LLM-repaired because that would invalidate provenance",
            }
            log.error(f"  {label}: metadata template '{entry['name']}' was not repaired (provenance guard).")
            continue
        log.info(f"  {label}: attempting repair for skipped query '{entry['name']}'...")
        raw[entry["name"]] = _repair_and_execute(state, md, entry, entry.get("reason", ""))
        log.info(f"  {label}: repair for '{entry['name']}': {raw[entry['name']]['status']}")

    for name, v in list(raw.items()):
        if v.get("status") == "success" or name in skipped_names:
            continue
        entry = next((q for q in queries if q["name"] == name), None)
        if entry is None:
            continue
        if entry.get("generation") == "metadata_template" or entry.get("contract_hint"):
            log.error(f"  {label}: metadata template '{name}' failed execution; not LLM-repaired (provenance guard).")
            continue
        log.info(f"  {label}: attempting repair for failed query '{name}'...")
        raw[name] = _repair_and_execute(
            state, md, {**entry, "dax": v.get("query", entry.get("dax"))}, str(v.get("error", "")))
        log.info(f"  {label}: repair for '{name}': {raw[name]['status']}")

    return raw


# --- Node 7: DAX Execution (summary branch) -----------------------------------
def execute_dax(state: dict) -> dict:
    log = RunLogger(state)
    mode = state.get("execution_mode", "python")
    queries = state.get("validated_dax_queries", [])
    skipped = state.get("skipped_dax_queries", [])
    log.info(f"Node 7: executing {len(queries)} DAX queries (mode={mode})...")

    if mode == "powershell":
        try:
            raw = pbi.execute_powershell(state, queries, file_io.write_json, file_io.output_path)
        except Exception as exc:  # noqa: BLE001
            log.error(f"PowerShell execution failed ({exc}); falling back to Python REST.")
            raw = pbi.execute_python(state["workspace_id"], state["dataset_id"], queries,
                                     token=state.get("pbi_token"))
    else:
        raw = pbi.execute_python(state["workspace_id"], state["dataset_id"], queries,
                                 token=state.get("pbi_token"))

    raw = _run_with_repairs(state, log, raw, queries, skipped, "summary")

    file_io.write_json(state, "raw_pbi_results.json", raw)
    ok = sum(1 for v in raw.values() if v.get("status") == "success")
    log.info(f"Executed queries: {ok}/{len(raw)} succeeded.")
    for name, v in raw.items():
        if v.get("status") != "success":
            log.error(f"  query '{name}' failed: {str(v.get('error'))[:200]}")
    return {"raw_pbi_results": raw, **log.updates()}


# --- Branch barriers -----------------------------------------------------------
# Each branch's happy path AND its own fatal short-circuit funnel through its
# barrier node; only the barriers edge into save_outputs. Their log lines also
# timestamp each branch's finish, which run_log.txt uses to prove real overlap.
def summary_branch_done(state: dict) -> dict:
    log = RunLogger(state)
    log.info("=== summary branch finished ===")
    return log.updates()


def insight_branch_done(state: dict) -> dict:
    log = RunLogger(state)
    log.info("=== insight branch finished ===")
    return log.updates()


# --- Save Outputs ------------------------------------------------------------
def save_outputs(state: dict) -> dict:
    log = RunLogger(state)
    memory_commit = {"status": "skipped", "reason": "memory_disabled_or_unhealthy"}

    # Ensure both report files exist even on an early stop.
    reason = "; ".join(state.get("errors", [])) or "pipeline stopped early"
    if not state.get("report_summary"):
        stub = (
            "# Summary\n\nThe report summary could not be generated.\n\n"
            "# Data Limitations\n\n- " + reason + "\n"
        )
        file_io.write_text(state, "report_summary.md", stub)
        file_io.write_text(state, "report_summary.html",
                           html_report.render(stub, title="Report Summary", eyebrow="Power BI Report Summary"))
        log.error("Wrote stub report_summary.md/.html due to early stop.")
    if not state.get("insight_report"):
        stub = (
            "# Key Insights\n\nThe insight report could not be generated.\n\n"
            "# Confidence & Caveats\n\n- " + reason + "\n"
        )
        file_io.write_text(state, "insight_report.md", stub)
        file_io.write_text(state, "insight_report.html",
                           html_report.render(stub, title="Insight Report", eyebrow="Power BI Insight Report"))
        log.error("Wrote stub insight_report.md/.html due to early stop.")

    # Commit observations + reported insights to persistent memory in a single
    # transaction. Observations (the daily per-axis cursor, the rolling
    # observation/activity snapshot) advance whenever the insight branch is
    # healthy - memory enabled, not fatal, store not corrupt - regardless of
    # whether anything was reported. Reported story records + journal are
    # written only when a real report was generated AND signals exist:
    # "observed" and "reported" are different things, so a synthesizer failure
    # (only a stub report written) must never mark a story as seen that the
    # user never actually received. On corruption we keep the damaged store
    # untouched (novelty guarantee already flagged in the report).
    novelty = state.get("insight_novelty", {}) or {}
    signals = state.get("insight_signals", [])
    if (state.get("insight_memory_enabled", True) and not state.get("fatal")
            and novelty.get("memory_status") != "corrupt"):
        reported = signals if state.get("insight_report") else []
        try:
            res = insight_memory.commit_run(state, reported)
            memory_commit = res
            if res.get("status") == "ok":
                log.info(f"Insight memory: committed {res.get('committed')} new "
                         f"finding(s); watermark={res.get('watermark')}.")
            else:
                log.error(f"Insight memory: commit skipped (status={res.get('status')}).")
        except Exception as exc:  # noqa: BLE001 - memory must never fail the run
            memory_commit = {"status": "failed", "error": str(exc)}
            log.error(f"Insight memory: commit failed ({type(exc).__name__}: {exc}).")

    run_log = "\n".join(state.get("logs", []) + [f"[save] wrote outputs to /{state.get('output_folder','outputs')}"])
    if state.get("errors"):
        run_log += "\n\nERRORS:\n" + "\n".join("- " + e for e in state["errors"])
    file_io.write_text(state, "run_log.txt", run_log)

    log.info("Outputs saved.")
    return {"insight_memory_commit": memory_commit, **log.updates()}


# --- Routers -----------------------------------------------------------------
def _after_metadata(state: dict) -> str:
    return "save_outputs" if state.get("fatal") else "semantic_profile"


def _after_validation(state: dict) -> str:
    if state.get("summary_fatal"):
        # Fresh-summary mode can still produce an honest descriptive view from
        # the pre-fork baseline portfolio. Legacy mode keeps its old shortcut.
        return "summary_period_resolver" if state.get("fresh_summary_enabled", True) else "summary_branch_done"
    return "execute_dax"


def _after_normalize(state: dict) -> str:
    return "summary_period_resolver" if state.get("fresh_summary_enabled", True) else "generate_summary"


def _after_novelty(state: dict) -> str:
    return "summary_multi_focus_evidence" if state.get("summary_r4_enabled") else "summary_focus_evidence"


# --- Node registry and chain specs (WP3) --------------------------------------
# A report declares which nodes it runs; the fork/join topology does not change.
# Only the LINEAR stretches are data. The fan-out, the conditional routers and
# the join barrier stay explicit code below, because they are the concurrency
# contract (Non-negotiables 4 and 5) rather than a configurable detail - an
# ad-hoc edge into save_outputs can fire it twice.

#: name -> the callable that runs it. A report may only name nodes from here.
#: Order is the order today's fixed graph registers them.
NODE_FACTORIES: dict = {
    # Pre-fork
    "load_config": load_config,
    "read_metadata": metadata_reader.run,
    "semantic_profile": semantic_profiler.run,
    "baseline_scope": baseline_scope.run,
    "baseline_coverage": baseline_coverage.run,
    "understand_report": report_understanding.run,
    # Summary branch
    "plan_dax": dax_planner.run,
    "generate_dax": dax_generator.run,
    "validate_dax": dax_validator.run,
    "execute_dax": execute_dax,
    "normalize_results": result_normalizer.run,
    "generate_summary": summary_generator.run,
    "summary_period_resolver": summary_period_resolver.run,
    "summary_focus_universe": summary_focus_universe.run,
    "summary_candidate_builder": summary_candidate_builder.run,
    "summary_overall_performance": summary_overall_performance.run,
    "summary_novelty_filter": summary_novelty_filter.run,
    "summary_focus_evidence": summary_focus_evidence.run,
    "summary_multi_focus_evidence": summary_multi_focus_evidence.run,
    "fresh_summary_generator": fresh_summary_generator.run,
    "summary_dashboard_build": summary_dashboard_builder.run,
    "fresh_summary_validator": fresh_summary_validator.run,
    "summary_branch_done": summary_branch_done,
    # Insight branch
    "insight_normalize": insight_result_normalizer.run,
    "insight_temporal": insight_temporal.run,
    "insight_business_day_source": insight_business_day_source.run,
    "insight_recent_week": insight_recent_week.run,
    "insight_daily": insight_daily.run,
    "insight_evidence_catalog": evidence_contract.run,
    "insight_stat_detector": insight_stat_detector.run,
    "insight_novelty_filter": insight_novelty_filter.run,
    "insight_signal_detector": insight_signal_detector.run,
    "insight_evidence_assembler": evidence_assembler.run,
    "insight_gap_scan": insight_gap_scan.run,
    "insight_investigator": insight_investigator.run,
    "insight_thesis_linker": insight_thesis_linker.run,
    "insight_synthesizer": insight_synthesizer.run,
    "insight_branch_done": insight_branch_done,
    # Join
    "save_outputs": save_outputs,
}

#: The linear stretch from the summary branch head to the novelty router.
SUMMARY_PRE_NOVELTY = (
    "summary_period_resolver", "summary_focus_universe",
    "summary_candidate_builder", "summary_overall_performance",
    "summary_novelty_filter",
)
#: The linear stretch after the deep-dive router, ending at the barrier.
SUMMARY_POST_EVIDENCE = (
    "fresh_summary_generator", "summary_dashboard_build",
    "fresh_summary_validator", "summary_branch_done",
)
#: The insight branch is linear end to end.
INSIGHT_CHAIN = (
    "insight_normalize", "insight_temporal", "insight_business_day_source",
    "insight_recent_week", "insight_daily", "insight_evidence_catalog",
    "insight_stat_detector", "insight_novelty_filter", "insight_signal_detector",
    "insight_evidence_assembler", "insight_gap_scan", "insight_investigator",
    "insight_thesis_linker", "insight_synthesizer", "insight_branch_done",
)

#: Nodes every report must run: the pre-fork spine, both branch heads, both
#: barriers and the join. Omitting any of these would break the topology rather
#: than shorten the report, so a spec that drops one is rejected.
REQUIRED_NODES = frozenset({
    "load_config", "read_metadata", "semantic_profile", "baseline_scope",
    "baseline_coverage", "understand_report",
    "plan_dax", "generate_dax", "validate_dax", "execute_dax",
    "normalize_results", "generate_summary",
    "summary_period_resolver", "summary_novelty_filter",
    "summary_focus_evidence", "summary_multi_focus_evidence",
    "fresh_summary_generator", "fresh_summary_validator", "summary_branch_done",
    "insight_normalize", "insight_branch_done", "save_outputs",
})


def _chain(g, names, present) -> None:
    """Wire an ordered run of nodes, skipping the ones this report omits.

    Skipping re-links across the gap rather than leaving a dangling edge, so a
    report that drops an optional node still produces a connected branch.
    """
    active = [name for name in names if name in present]
    for earlier, later in zip(active, active[1:]):
        g.add_edge(earlier, later)


def default_node_names() -> tuple[str, ...]:
    """Every node today's fixed graph runs."""
    return tuple(NODE_FACTORIES)


def resolve_node_names(report=None) -> tuple[str, ...]:
    """Which nodes this report runs, in registry order.

    No report, or a report naming no nodes, means today's full graph - which is
    what keeps every existing invocation identical.
    """
    requested = getattr(report, "nodes", None) if report is not None else None
    if not requested:
        return default_node_names()
    requested = set(requested)
    unknown = sorted(requested - set(NODE_FACTORIES))
    if unknown:
        raise ValueError(
            f"report names node(s) with no factory: {', '.join(unknown)}; "
            f"known: {', '.join(sorted(NODE_FACTORIES))}")
    missing = sorted(REQUIRED_NODES - requested)
    if missing:
        raise ValueError(
            "a report cannot omit the nodes that form the topology itself "
            f"(fork, routers, barriers, join): {', '.join(missing)}")
    return tuple(name for name in NODE_FACTORIES if name in requested)


# --- Build -------------------------------------------------------------------
def build_graph(report=None):
    """Assemble the graph. ``report`` is optional; without it this is today's
    fixed graph, node for node and edge for edge."""
    g = StateGraph(SummaryAgentState)

    present = set(resolve_node_names(report))
    for name, factory in NODE_FACTORIES.items():
        if name in present:
            g.add_node(name, factory)

    # Pre-fork
    g.add_edge(START, "load_config")
    g.add_edge("load_config", "read_metadata")
    g.add_conditional_edges("read_metadata", _after_metadata,
                            {"semantic_profile": "semantic_profile", "save_outputs": "save_outputs"})
    g.add_edge("semantic_profile", "baseline_scope")
    g.add_edge("baseline_scope", "baseline_coverage")
    g.add_edge("baseline_coverage", "understand_report")

    # Fan-out: both branch heads become runnable in the same superstep.
    g.add_edge("understand_report", "plan_dax")
    g.add_edge("understand_report", "insight_normalize")

    # Summary branch
    g.add_edge("plan_dax", "generate_dax")
    g.add_edge("generate_dax", "validate_dax")
    g.add_conditional_edges("validate_dax", _after_validation,
                            {
                                "execute_dax": "execute_dax",
                                "summary_period_resolver": "summary_period_resolver",
                                "summary_branch_done": "summary_branch_done",
                            })
    g.add_edge("execute_dax", "normalize_results")
    g.add_conditional_edges("normalize_results", _after_normalize,
                            {
                                "summary_period_resolver": "summary_period_resolver",
                                "generate_summary": "generate_summary",
                            })
    g.add_edge("generate_summary", "summary_branch_done")
    _chain(g, SUMMARY_PRE_NOVELTY, present)
    # R4 routes the portfolio through the multi-focus deep dive; the single-focus
    # path keeps the original deep-dive node unchanged.
    g.add_conditional_edges("summary_novelty_filter", _after_novelty,
                            {
                                "summary_focus_evidence": "summary_focus_evidence",
                                "summary_multi_focus_evidence": "summary_multi_focus_evidence",
                            })
    g.add_edge("summary_focus_evidence", SUMMARY_POST_EVIDENCE[0])
    g.add_edge("summary_multi_focus_evidence", SUMMARY_POST_EVIDENCE[0])
    # R6 dashboard: a no-op pass-through when summary_r6_enabled is false, so the
    # R1-R5 chain is unchanged. Placed after the generator because it reads the
    # same deep-dive evidence, and before the validator because the validator is
    # the single point where every summary artifact is written.
    _chain(g, SUMMARY_POST_EVIDENCE, present)

    # Insight branch
    _chain(g, INSIGHT_CHAIN, present)

    # Fan-in: save_outputs waits for BOTH barriers (joined edge). The only other
    # way in is the single pre-fork fatal edge above.
    g.add_edge(["summary_branch_done", "insight_branch_done"], "save_outputs")
    g.add_edge("save_outputs", END)

    return g.compile()
