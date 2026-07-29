"""Pre-fork metadata-driven coverage scan shared by both report branches."""

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger
from .dax_validator import validate_one
from .scope_validator import validate_comparable_scope
from .insight_scan_templates import build_metadata_scans
from .evidence_contract import assess_peer_eligibility


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Shared baseline: executing metadata-driven diagnostic coverage pre-fork...")
    queries = build_metadata_scans(state.get("semantic_model_profile", {}), state)
    plan = {"source": "semantic_model_profile", "queries": queries,
            "query_budget": int(state.get("insight_max_scan_queries", 10))}
    generated, validated, audit = [], [], []
    for query in queries:
        entry = {**query, "generation": "metadata_template"}
        generated.append(entry)
        reasons = validate_one(entry.get("dax"), state.get("model_metadata", {}))
        reasons += validate_comparable_scope(entry.get("dax", ""), state,
                                             entry.get("contract_hint"))
        audit.append({**entry, "status": "valid" if not reasons else "skipped",
                      **({"reason": "; ".join(reasons)} if reasons else {})})
        if reasons:
            log.error(f"  baseline template '{entry['name']}' rejected: {'; '.join(reasons)}")
        else:
            validated.append(entry)

    raw = {}
    if validated:
        try:
            raw = pbi.execute_python(state["workspace_id"], state["dataset_id"], validated,
                                     token=state.get("pbi_token"))
        except Exception as exc:  # noqa: BLE001
            log.error(f"  shared baseline execution failed: {exc}")
            raw = {q["name"]: {"status": "failed", "purpose": q.get("purpose", ""),
                                "query": q["dax"], "error": str(exc)} for q in validated}

    source = {q["name"]: q for q in validated}
    clean_queries, success = [], 0
    for name, item in raw.items():
        q = source.get(name, {})
        if item.get("status") == "success":
            rows = clean_rows(pbi.extract_rows(item.get("result", {})))
            clean_queries.append({
                "query_name": name, "purpose": q.get("purpose", ""), "status": "success",
                "rows": rows, "dax": q.get("dax", ""),
                "contract_hint": q.get("contract_hint", {}), "shared_pre_fork": True,
            })
            success += 1
        else:
            clean_queries.append({
                "query_name": name, "purpose": q.get("purpose", ""), "status": "failed",
                "error": item.get("error", "unknown error"), "dax": q.get("dax", ""),
                "contract_hint": q.get("contract_hint", {}), "shared_pre_fork": True,
            })

    clean = {"query_count": len(clean_queries), "successful": success,
             "failed": len(clean_queries) - success, "queries": clean_queries}

    # Phase 1 rate-outlier lens: decide, pre-fork, which peer distributions are
    # honest enough (complete, comparable, reconciled) to carry rate-outlier
    # detection. Never fatal, and a no-op when insight_rate_outlier_mode is off
    # (no full_dimension_breakdown scans were planned).
    peer_coverage = assess_peer_eligibility(clean_queries, state)

    file_io.write_json(state, "insight_dax_plan.json", plan)
    file_io.write_json(state, "insight_generated_dax_queries.json", generated)
    file_io.write_json(state, "insight_validated_dax_queries.json", audit)
    file_io.write_json(state, "insight_raw_results.json", raw)
    file_io.write_json(state, "baseline_coverage_clean_data.json", clean)
    file_io.write_json(state, "insight_peer_coverage.json", peer_coverage)
    log.info(f"Shared metadata coverage: {success}/{len(validated)} queries succeeded pre-fork.")
    if peer_coverage:
        eligible = sum(1 for v in peer_coverage.values() if v.get("eligible"))
        log.info(f"Peer evidence: {eligible}/{len(peer_coverage)} dimension(s) eligible "
                 f"for rate-outlier detection.")
    return {
        "insight_dax_plan": plan,
        "insight_generated_dax_queries": generated,
        "insight_validated_dax_queries": validated,
        "insight_skipped_dax_queries": [a for a in audit if a.get("status") == "skipped"],
        "insight_raw_results": raw,
        "baseline_coverage_clean_data": clean,
        "insight_peer_coverage": peer_coverage,
        "insight_fatal": not validated,
        **log.updates(),
    }
