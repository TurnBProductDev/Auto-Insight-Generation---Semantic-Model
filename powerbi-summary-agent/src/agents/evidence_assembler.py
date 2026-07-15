"""Evidence Assembler (deterministic, no LLM).

Turns the broad scan into a per-signal *investigation brief*: what is already
known and reusable, what is only good enough to hint, and what genuinely has
to be queried. It replaces the old loose handoff (the investigator used to get
one ``evidence_query`` and a 9-probe budget and re-derived the rest).

The core move is REUSE-BEFORE-DAX with provenance. For each signal it:

  1. gathers every scan record about the signal's segment (its own row and any
     cross-slice that breaks the segment down by another dimension);
  2. classifies each as a ``known_fact`` carrying its contract's provenance and
     a deterministic ``safe_to_reuse`` verdict;
  3. walks the candidate drill dimensions and decides, per dimension, whether
     the scan already answers it (``already_answered``) or a probe is needed
     (``recommended_probes``);
  4. emits a ``stop_condition`` and a per-signal ``reuse_summary`` for cost
     accounting.

The reuse gate is the safety-critical part and is pure code, not a prompt
instruction:

  * ``safe_to_reuse`` requires completeness == complete AND (for a comparable
    finding) population_status == comparable AND, where a grand total exists,
    the breakdown reconciles to it within tolerance.
  * anything partial, truncated, scope_ambiguous, unfiltered, includes_excluded
    or non-reconciling is ``verification_required``: it may SUPPORT a
    hypothesis but can never suppress a verification probe.

This is what preserves the error-catching robustness the old re-query path had
for free - e.g. a new/excluded-entity scope leak is ``unfiltered`` and so can never be
silently reused to close a comparable finding.
"""

from . import evidence_contract
from ..utils.logger import RunLogger
from ..tools import file_io

_EPS = 1e-9


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _table_rows(clean: dict, name: str) -> list:
    for q in clean.get("queries", []):
        if q.get("query_name") == name:
            return q.get("rows") or []
    return []


def _label_values(rows: list, dims: list) -> set:
    """All values seen across the given label columns (as strings)."""
    out = set()
    for r in rows:
        for d in dims:
            v = r.get(d)
            if v is None:
                # normalized rows may key by bare name; try any key ending in the dim
                for k in r:
                    if k == d or k.endswith("." + d):
                        v = r.get(k)
                        break
            if v is not None:
                out.add(str(v))
    return out


def _reconciles(state: dict, candidates: dict, metric: str, table_sum: float) -> bool:
    """True when a breakdown sum matches the metric's scanned grand total within
    tolerance. Unknown totals return True (no evidence against reuse) - the
    completeness/population gates still guard truncation and scope."""
    totals = (candidates or {}).get("grand_totals_seen", {})
    additive = set((candidates or {}).get("additive_metrics", []))
    g = totals.get(metric)
    if metric not in additive or not isinstance(g, (int, float)) or abs(g) <= _EPS:
        return True
    tol = float(state.get("insight_stat_recon_tolerance_pct", 2.0)) / 100.0
    return abs(table_sum - g) <= tol * max(abs(g), 1.0)


def _scope_type(signal: dict, candidate: dict) -> str:
    ctype = candidate.get("type")
    if ctype == "new_entity_current_only":
        return "current_only"
    if ctype == "prior_only_entity":
        return "prior_only"
    if signal.get("kind") == "data_quality":
        return "data_quality"
    return "comparable"


def _scope_ok(contract: dict, scope_type: str) -> bool:
    status = contract.get("population_status")
    if scope_type == "comparable":
        return status == "comparable"
    if scope_type in ("current_only", "prior_only"):
        return status in ("unfiltered_discovery", scope_type, "entity_specific")
    return status not in ("includes_excluded", "scope_ambiguous", "unknown")


def _safe_fact_reuse(contract: dict, scope_type: str) -> bool:
    """A returned row may be quoted even when its table is a ranked tail.

    Partial coverage cannot prove exhaustive decomposition, but an exact row
    from a construction-time, correctly-scoped query is still a computed fact.
    """
    return bool(contract and _scope_ok(contract, scope_type)
                and contract.get("contract_source") not in (None, "parsed_dax_and_rows")
                and contract.get("completeness") != "unknown")


def _safe_coverage_reuse(contract: dict, scope_type: str, reconciles: bool) -> bool:
    return bool(contract.get("completeness") == "complete"
                and _scope_ok(contract, scope_type) and reconciles)


def _provenance(contract: dict) -> dict:
    return {
        "source_query": contract.get("query_name"),
        "population_status": contract.get("population_status"),
        "completeness": contract.get("completeness"),
        "truncated": contract.get("truncated"),
        "topn": contract.get("topn"),
        "dax_hash": contract.get("dax_hash"),
        "parse_confidence": contract.get("filters", {}).get("parse_confidence"),
        "coverage_kind": contract.get("coverage_kind"),
        "contract_source": contract.get("contract_source"),
    }


def _match_candidate(signal: dict, candidates: dict) -> dict:
    """Find the stat candidate this signal was selected from (segment + closest
    impact_value); the candidate's numbers are the computed facts to reuse."""
    candidate_id = signal.get("candidate_id")
    for c in ((candidates or {}).get("business_candidates", [])
              + (candidates or {}).get("data_quality_candidates", [])):
        if candidate_id and c.get("id") == candidate_id:
            return c
    seg = signal.get("affected_segment")
    want = _num(signal.get("impact_value"))
    best, best_gap = None, None
    for c in (candidates or {}).get("business_candidates", []):
        if str(c.get("segment")) != str(seg):
            continue
        cv = _num(c.get("impact_value"))
        gap = abs(cv - want) if (cv is not None and want is not None) else 0.0
        if best is None or gap < best_gap:
            best, best_gap = c, gap
    return best or {}


def assemble_brief(signal: dict, contracts: dict, candidates: dict,
                   clean: dict, state: dict) -> dict:
    """Build one signal's investigation brief with deterministic reuse gates."""
    seg = str(signal.get("affected_segment"))
    matched = _match_candidate(signal, candidates)
    scope_type = _scope_type(signal, matched)

    # The signal's own dimension = the grouping of its evidence_query; drilling
    # means slicing the segment by OTHER dimensions.
    ev_name = signal.get("evidence_query")
    ev_contract = contracts.get(ev_name, {})
    seg_dims = ev_contract.get("grouping_dimensions", []) or []

    # Candidate drill dimensions: every grouping dimension seen anywhere in the
    # scan portfolio, minus the segment's own dimension.
    all_dims = {}
    for name, c in contracts.items():
        for d in c.get("grouping_dimensions", []):
            all_dims.setdefault(d, []).append(name)
    # The scan portfolio is selected from metadata.  Include compatible profile
    # dimensions even when the broad scan budget did not reach them; those are
    # genuine gaps, not invisible dimensions.
    profile = state.get("semantic_model_profile", {})
    dimension_specs = {}
    for d in profile.get("dimensions", []):
        dimension_specs.setdefault(d.get("column"), d)
    for d in profile.get("time_dimensions", [])[:1]:
        dimension_specs.setdefault(d.get("column"), d)
    max_dims = max(1, int(state.get("insight_metadata_max_dimensions", 5))) + 1
    available_dims = [d for d in dimension_specs if d not in seg_dims][:max_dims]
    # Legacy contracts may expose a dimension absent from the new profile.
    for d in all_dims:
        if d not in seg_dims and d not in available_dims:
            available_dims.append(d)
    # Focus the adaptive plan on the highest-information dimensions: entity,
    # strongest business dimensions, then time.  The full metadata universe is
    # still disclosed in available_dimensions without issuing one probe per
    # cell.
    gap_cap = max(1, int(state.get("insight_max_gap_dimensions_per_signal", 3)))
    entity_name = (profile.get("entity_dimension") or {}).get("column")
    time_name = ((profile.get("time_dimensions") or [{}])[0]).get("column")
    priority = []
    if entity_name in available_dims:
        priority.append(entity_name)
    priority += [d for d in available_dims if d not in (entity_name, time_name)]
    if time_name in available_dims:
        priority.append(time_name)
    drill_dims = priority[:gap_cap]

    known_facts, supporting_queries = [], []
    if matched:
        c = contracts.get(matched.get("table"), {})
        known_facts.append({
            "fact": matched.get("detail", ""),
            "metric": matched.get("metric"),
            "impact_value": matched.get("impact_value"),
            "impact_share": matched.get("impact_share"),
            "share_basis": matched.get("share_basis"),
            "provenance": _provenance(c) if c else {"source_query": matched.get("table")},
            "safe_to_reuse": _safe_fact_reuse(c, scope_type) if c else False,
            "verification_required": not _safe_fact_reuse(c, scope_type) if c else True,
        })
        if matched.get("table"):
            supporting_queries.append(matched["table"])

    # Walk each drill dimension: is it already answered by a scan cross-slice
    # scoped to this segment, or is it a gap?
    already_answered, unanswered, probes = [], [], []
    for d in sorted(drill_dims):
        covering = None
        for name in all_dims.get(d, []):
            c = contracts[name]
            if d not in c.get("grouping_dimensions", []):
                continue
            rows = _table_rows(clean, name)
            # Does this table actually contain the segment (as a cross-slice on
            # the segment's own dimension, or filtered to it)?
            seg_filter = c.get("segment_filter") or {}
            segment_members = {str(v) for v in (signal.get("segment_members") or [])}
            seg_present = (
                str(seg_filter.get("value")) == seg
                or bool(segment_members.intersection(
                    {str(v) for v in seg_filter.get("values", [])}))
                or seg in _label_values(rows, c.get("grouping_dimensions", []))
                or bool(segment_members.intersection(
                    _label_values(rows, c.get("grouping_dimensions", []))))
                or seg in set(c.get("population", {}).get("codes", []))
            )
            if not seg_present:
                continue
            rows_sum_ok = True
            for metric in c.get("metrics", []):
                vals = [_num(r.get(metric)) for r in rows]
                vals = [v for v in vals if v is not None]
                if vals and not _reconciles(state, candidates, metric, sum(vals)):
                    rows_sum_ok = False
                    break
            covering = {**c, "reconciles": rows_sum_ok}
            if _safe_coverage_reuse(c, scope_type, rows_sum_ok):
                break  # a fully-reusable cross-slice wins; keep looking otherwise

        if covering is None:
            unanswered.append(f"How does {seg} decompose by {d}?")
            probes.append({
                "dimension": d,
                "dimension_spec": dimension_specs.get(d),
                "segment": seg,
                "reason": "no scan cross-slice breaks this segment down by this dimension",
                "template": "segment_by_dimension_change",
            })
        elif _safe_coverage_reuse(covering, scope_type, covering.get("reconciles", True)):
            already_answered.append({
                "dimension": d,
                "dimension_spec": dimension_specs.get(d),
                "source_query": covering.get("query_name"),
                "provenance": _provenance(covering),
            })
            if covering.get("query_name") not in supporting_queries:
                supporting_queries.append(covering.get("query_name"))
        else:
            # Present but not trustworthy: informs, does not close.
            unanswered.append(
                f"How does {seg} decompose by {d}? (a scan slice exists but is "
                f"{covering.get('completeness')}/{covering.get('population_status')} "
                f"- verification required)")
            probes.append({
                "dimension": d,
                "dimension_spec": dimension_specs.get(d),
                "segment": seg,
                "reason": f"existing slice not reusable "
                          f"({covering.get('completeness')}/{covering.get('population_status')})",
                "verify_source": covering.get("query_name"),
                "template": "segment_by_dimension_change",
            })
            if covering.get("query_name") not in supporting_queries:
                supporting_queries.append(covering.get("query_name"))

    n_reusable = len(already_answered) + sum(1 for f in known_facts if f["safe_to_reuse"])
    n_verify = len(probes)

    coverage_label = "complete + comparable" if scope_type == "comparable" else "scope-correct complete"
    stop_condition = (
        f"Stop once {seg}'s movement is decomposed across at least one drill "
        f"dimension with {coverage_label} coverage, or the shared probe "
        f"budget is exhausted. Facts flagged verification_required may inform "
        f"the explanation but must not, on their own, end the investigation.")

    return {
        "signal_id": signal.get("id"),
        "segment": seg,
        "scope_type": scope_type,
        "comparable_finding": scope_type == "comparable",
        "known_facts": known_facts,
        "supporting_queries": supporting_queries,
        "already_answered": already_answered,
        "unanswered_questions": unanswered,
        "recommended_probes": probes,
        "available_dimensions": sorted(available_dims),
        "stop_condition": stop_condition,
        "reuse_summary": {
            "drill_dimensions": len(drill_dims),
            "answered_by_reuse": len(already_answered),
            "facts_reusable": n_reusable,
            "gaps_needing_probe": n_verify,
        },
    }


def build_coverage_matrix(contracts: dict, state: dict | None = None) -> dict:
    """Disclose coverage QUALITY per dimension (it cannot prove absence of blind
    spots - only that nothing truncated is passed off as complete). Each cell
    records which metrics were scanned, at what completeness/population, and
    whether any COMPLETE + COMPARABLE coverage exists there."""
    matrix = {}
    for name, c in contracts.items():
        dims = c.get("grouping_references") or c.get("grouping_dimensions") or ["(grand total)"]
        for dim in dims:
            cell = matrix.setdefault(dim, {"queries": [], "metrics": set(),
                                           "completeness": set(), "population": set(),
                                           "coverage_kinds": set()})
            cell["queries"].append(name)
            if c.get("metric_roles"):
                cell["metrics"].update(
                    f"{m.get('bundle_id')}:{m.get('phase')}:{alias}"
                    for alias, m in c["metric_roles"].items())
            else:
                cell["metrics"].update(c.get("metrics", []))
            cell["completeness"].add(c.get("completeness"))
            cell["population"].add(c.get("population_status"))
            cell["coverage_kinds"].add(c.get("coverage_kind"))
    # Metadata is the coverage universe: an unqueried compatible dimension is
    # an explicit gap rather than an absent row in the artifact.
    profile = (state or {}).get("semantic_model_profile", {})
    metadata_dims = []
    if profile.get("entity_dimension"):
        metadata_dims.append(profile["entity_dimension"])
    metadata_dims += profile.get("dimensions", []) + profile.get("time_dimensions", [])[:1]
    for dim in metadata_dims:
        matrix.setdefault(dim.get("reference"), {"queries": [], "metrics": set(),
                                                  "completeness": set(), "population": set(),
                                                  "coverage_kinds": set()})
    out = {}
    for dim, cell in matrix.items():
        has_trusted = any(
            contracts[q].get("completeness") == "complete"
            and contracts[q].get("population_status") == "comparable"
            for q in cell["queries"])
        out[dim] = {
            "queries": cell["queries"],
            "metrics": sorted(cell["metrics"]),
            "completeness_seen": sorted(x for x in cell["completeness"] if x),
            "population_seen": sorted(x for x in cell["population"] if x),
            "coverage_kinds": sorted(x for x in cell["coverage_kinds"] if x),
            # the Phase-5 honesty criterion: truthfully report whether this cell
            # has trustworthy (complete + comparable) coverage, or only partial.
            "trusted_coverage": has_trusted,
        }
    return out


def run(state: dict) -> dict:
    """Node: contract every scan table, then build a brief per signal. Read-only
    over scan artifacts; writes evidence contracts + briefs for the investigator
    and for audit."""
    log = RunLogger(state)
    log.info("Insight branch: assembling evidence briefs (deterministic reuse pass)...")

    contracts = state.get("insight_evidence_contracts") or evidence_contract.build_contracts(state)
    candidates = state.get("insight_stat_candidates", {})
    clean = state.get("insight_clean_data", {"queries": []})
    signals = state.get("insight_signals", [])

    briefs = {}
    total_reuse = total_gap = 0
    for signal in signals:
        try:
            brief = assemble_brief(signal, contracts, candidates, clean, state)
        except Exception as exc:  # noqa: BLE001 - assembly must never kill the branch
            log.error(f"  brief assembly for '{signal.get('id')}' failed ({exc}); "
                      "investigator will fall back to the raw evidence query.")
            brief = {"signal_id": signal.get("id"), "error": str(exc),
                     "recommended_probes": [], "already_answered": []}
        briefs[signal.get("id")] = brief
        total_reuse += brief.get("reuse_summary", {}).get("answered_by_reuse", 0)
        total_gap += brief.get("reuse_summary", {}).get("gaps_needing_probe", 0)

    coverage = build_coverage_matrix(contracts, state)
    file_io.write_json(state, "insight_evidence_contracts.json", contracts)
    file_io.write_json(state, "insight_evidence_briefs.json", briefs)
    file_io.write_json(state, "insight_coverage_matrix.json", coverage)
    trusted = sum(1 for c in coverage.values() if c["trusted_coverage"])
    log.info(f"Evidence briefs: {len(briefs)} signals; "
             f"{total_reuse} drill-dimensions answered by reuse, "
             f"{total_gap} gaps flagged for probing.")
    log.info(f"Coverage matrix: {len(coverage)} dimensions, "
             f"{trusted} with trusted (complete+comparable) coverage.")
    return {"insight_evidence_contracts": contracts,
            "insight_evidence_briefs": briefs,
            "insight_coverage_matrix": coverage, **log.updates()}
