"""Metadata-templated targeted gap scan.

Only genuine gaps from the provenance-aware brief are queried.  Dimensions
come from the semantic profile, scope is baked into the template, and one
global plus one per-signal budget bounds serial REST latency.
"""

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger
from .dax_validator import validate_one
from .evidence_contract import dax_hash
from .scope_validator import validate_comparable_scope
from . import insight_scan_templates as tpl


def _all_dimensions(profile: dict) -> list[dict]:
    return ([profile.get("entity_dimension")] if profile.get("entity_dimension") else []) \
        + list(profile.get("dimensions", [])) + list(profile.get("time_dimensions", [])[:1])


def _segment_dimension(signal: dict, contracts: dict, profile: dict) -> dict | None:
    contract = contracts.get(signal.get("evidence_query"), {})
    refs = contract.get("grouping_references") or []
    names = contract.get("grouping_dimensions") or []
    dimensions = _all_dimensions(profile)
    for dim in dimensions:
        if dim.get("reference") in refs or dim.get("column") in names:
            return dim
    return None


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: targeted gap scan from metadata-compatible dimensions...")
    signals = state.get("insight_signals", [])
    briefs = state.get("insight_evidence_briefs", {})
    contracts = state.get("insight_evidence_contracts", {})
    profile = state.get("semantic_model_profile", {})
    population = [str(v) for v in state.get("insight_comparable_population", []) or []]
    max_rows = int(state.get("insight_probe_max_rows", 20))
    per_signal_ceiling = int(state.get("insight_max_investigation_rounds", 3))
    global_remaining = int(state.get("insight_total_gap_scan_budget", 20))
    shape = tpl.shape_from_profile(profile, state)
    cache = dict(state.get("insight_query_cache", {}) or {})
    if not shape:
        log.info("  gap scan skipped: metadata profile has no coherent primary value shape.")
        return {"insight_gap_evidence": {}, "insight_query_cache": cache, **log.updates()}

    gap_evidence, total = {}, 0
    # Signals arrive in materiality order; the global cap therefore naturally
    # preserves the most important gaps first.
    for signal in signals:
        if global_remaining <= 0:
            break
        sid = signal.get("id")
        brief = briefs.get(sid, {})
        # Ambiguous existing evidence must be explicitly verified by the
        # investigator; the deterministic gap stage only fills genuinely absent
        # combinations.
        gaps = [p for p in brief.get("recommended_probes", [])
                if not p.get("verify_source") and p.get("dimension_spec")]
        if not gaps:
            continue
        seg_dim = _segment_dimension(signal, contracts, profile)
        seg_val = signal.get("segment_members") or signal.get("affected_segment")
        if not seg_dim or seg_val is None:
            continue
        budget = min(len(gaps), per_signal_ceiling, global_remaining)
        filled, used = {}, 0
        for probe in gaps[:budget]:
            drill_spec = probe.get("dimension_spec")
            if not drill_spec or drill_spec.get("reference") == seg_dim.get("reference"):
                continue
            built = tpl.build_gap_probe(
                shape, seg_dim, seg_val, drill_spec, population, max_rows,
                scope_type=brief.get("scope_type", "comparable"),
            )
            dax, hint = built["dax"], built["contract_hint"]
            reasons = validate_one(dax, state.get("model_metadata", {}))
            reasons += validate_comparable_scope(dax, state, hint)
            if reasons:
                log.error(f"  gap template rejected for '{sid}/{probe.get('dimension')}': {'; '.join(reasons)}")
                continue
            key = dax_hash(dax)
            cached = cache.get(key)
            if cached:
                rows, status, error = cached.get("rows", []), cached.get("status"), cached.get("error", "")
            else:
                name = f"gap_{sid}_{probe.get('dimension')}"
                try:
                    item = pbi.execute_python(
                        state["workspace_id"], state["dataset_id"],
                        [{"name": name, "dax": dax, "purpose": "metadata-targeted gap"}],
                        token=state.get("pbi_token"),
                    )[name]
                    status = item.get("status", "failed")
                    rows = clean_rows(pbi.extract_rows(item.get("result", {}))) if status == "success" else []
                    error = "" if status == "success" else str(item.get("error", "unknown error"))
                except Exception as exc:  # noqa: BLE001
                    status, rows, error = "failed", [], str(exc)
                cache[key] = {"status": status, "rows": rows[:max_rows], "error": error,
                              "dax": dax, "contract_hint": hint, "source": "gap_scan"}
                used += 1
                total += 1
                global_remaining -= 1
            if status == "success":
                rows = rows[:max_rows]
                completeness = "partial" if len(rows) >= max_rows else "complete"
                filled[probe["dimension"]] = {
                    "rows": rows, "row_count": len(rows), "dax": dax,
                    "contract_hint": hint, "population_status": hint.get("population_status"),
                    "completeness": completeness, "cache_hit": bool(cached),
                }
            else:
                log.info(f"  gap probe '{sid}/{probe.get('dimension')}' failed: {error[:120]}")

        if used or filled:
            gap_evidence[sid] = {
                "segment": signal.get("affected_segment"),
                "segment_members": signal.get("segment_members"),
                "segment_dimension": seg_dim,
                "filled_dimensions": sorted(filled), "evidence": filled,
                "gap_probes_used": used,
            }
            log.info(f"  gap scan '{sid}': {used} REST calls, filled {sorted(filled)}.")

    file_io.write_json(state, "insight_gap_evidence.json", gap_evidence)
    log.info(f"Gap scan complete: {total} REST calls; global budget remaining={global_remaining}.")
    return {"insight_gap_evidence": gap_evidence, "insight_query_cache": cache, **log.updates()}
