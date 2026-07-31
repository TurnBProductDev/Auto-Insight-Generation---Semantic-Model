"""Overall Performance node (summary-only, R4).

Builds the deterministic ``summary_overall_performance`` package from the
overall_performance candidate, and attaches one best-effort summary-owned period
trend (never Insight's temporal state). Gated behind ``summary_r4_enabled`` so it
is a no-op on the single-focus path. Non-fatal: a failed trend degrades to the
package without a trend. Executes any trend query with the pre-fetched token.
"""

from __future__ import annotations

from ..tools import file_io
from ..tools import summary_focus_queries as q
from ..tools import summary_overall
from ..utils.logger import RunLogger
from .summary_focus_evidence import (
    _alias,
    _families,
    _run_query,
    _select_trend_dimension,
    _strip_diagnostics,
    _trend_direction,
    _trend_reconciled,
)


def _overall_trend(state: dict, package: dict) -> dict | None:
    """One best-effort summary-owned overall period-trend query (§16)."""
    profile = state.get("semantic_model_profile") or {}
    families = _families(profile)
    if not families:
        return None
    revenue = families[0]
    trend_dim, _note = _select_trend_dimension(state, profile, revenue)
    if not trend_dim or not trend_dim.get("reference"):
        return None
    measures = [(_alias(revenue["family"], phase), measure) for phase, measure in revenue["phases"].items()]
    if not measures:
        return None
    entity = profile.get("entity_dimension") or {}
    comparable = [
        str(item) for item in
        (state.get("resolved_entity_scope") or {}).get("active_comparable_population") or []
    ]
    filters = []
    if entity.get("reference") and comparable:
        filters = [q.treatas(entity["reference"], comparable)]
    query = q.period_trend(
        "summary_overall_trend",
        "Overall business period trend",
        trend_dim["reference"],
        filters,
        measures,
        int(state.get("summary_focus_max_rows_per_breakdown", 15)),
        {"population_status": "comparable", "population_codes": comparable} if comparable else {},
    )
    budget = {"used": 0, "max": max(0, int(state.get("summary_overall_trend_max_queries", 1)))}
    result = _run_query(state, query, budget, {})
    if result.get("status") != "success" or not result.get("rows"):
        return None
    raw_rows = result["rows"]
    primary = str(package.get("primary_family") or revenue.get("family") or "")
    focus_total = ((package.get("families") or {}).get(primary) or {}).get("current")
    tolerance = float(state.get("summary_focus_reconciliation_tolerance_pct", 2))
    completeness = _trend_reconciled(raw_rows, focus_total, tolerance)
    rows = _strip_diagnostics(raw_rows)
    if completeness != "complete" or len(rows) < 3:
        return None
    current_alias = _alias(revenue["family"], "current")
    return {
        "dimension": trend_dim.get("column"),
        "grain": trend_dim.get("grain") or trend_dim.get("column"),
        "rows": rows,
        "completeness": completeness,
        "direction": _trend_direction(rows, current_alias),
        "value_aliases": {phase: _alias(revenue["family"], phase) for phase in revenue["phases"]},
    }


def _contribution_label(state: dict, candidate: dict) -> str:
    """Name the current-only contribution from the excluded (new) entities."""
    excluded = [
        str(item).strip()
        for item in (state.get("resolved_entity_scope") or {}).get("excluded_from_comparison", []) or []
        if str(item).strip()
    ]
    if excluded:
        head = ", ".join(excluded[:3])
        return f"{head} and others" if len(excluded) > 3 else head
    return str(candidate.get("segment") or "").strip() or "New-branch contribution"


def run(state: dict) -> dict:
    log = RunLogger(state)
    if not state.get("summary_r4_enabled", False):
        return {**log.updates()}

    candidates = state.get("summary_candidates") or []
    # The comparison-capable company total is the mandatory Overall Performance
    # view. A current-only total (e.g. a newly opened branch) is classified as
    # ``overall_contribution`` upstream so it can never seize this slot.
    overall = next((c for c in candidates if c.get("angle") == "overall_performance"), None)
    package = summary_overall.build_overall(overall, state.get("summary_period_context"))

    if package.get("status") == "ok" and state.get("summary_overall_trend_enabled", True):
        try:
            trend = _overall_trend(state, package)
            if trend:
                package["trend"] = trend
        except Exception as exc:  # noqa: BLE001 - trend is best-effort, never fatal
            log.error(f"Overall trend skipped ({type(exc).__name__}: {exc}).")

    # Current-only contribution shown separately (never blended into the
    # like-for-like comparison). Attached to the package as a supporting note.
    contribution_candidate = next(
        (c for c in candidates if c.get("angle") == "overall_contribution"), None
    )
    contribution = (
        summary_overall.contribution_note(
            contribution_candidate, _contribution_label(state, contribution_candidate)
        )
        if contribution_candidate
        else None
    )
    if contribution:
        package["contribution"] = contribution

    file_io.write_json(state, "summary_overall_performance.json", package)
    updates: dict = {"summary_overall_performance": package}

    # Promote both sides of the revenue bridge to supported facts on the overall
    # candidate so the summary can quantify volume AND rate/mix, not just name the
    # dominant side. The separate current-only contribution is added as supported
    # (copyable) facts too, so the summary may cite it once as a note without the
    # figure failing number validation. Derived values only; a re-run replaces
    # any prior bridge/contribution facts.
    bridge_facts = summary_overall.bridge_facts(
        package.get("bridge"), str(package.get("comparison") or "the comparison period")
    )
    extra_facts = list(bridge_facts)
    if contribution:
        extra_facts += list(contribution.get("facts") or [])
    if extra_facts and overall is not None:
        enriched = dict(overall)
        evidence = dict(enriched.get("evidence") or {})
        facts = [
            fact for fact in (evidence.get("facts") or [])
            if fact.get("fact_kind") not in ("bridge", "contribution")
        ]
        evidence["facts"] = facts + extra_facts
        enriched["evidence"] = evidence
        updates["summary_candidates"] = [enriched if c is overall else c for c in candidates]

    log.info(
        "Overall Performance: status=%s bridge=%s trend=%s contribution=%s."
        % (package.get("status"), "yes" if package.get("bridge") else "no",
           "yes" if package.get("trend") else "no", "yes" if contribution else "no")
    )
    return {**updates, **log.updates()}
