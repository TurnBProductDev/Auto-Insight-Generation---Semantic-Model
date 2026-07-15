"""Insight branch - Result Normalizer (deterministic).

Mirrors result_normalizer over the insight scan results.
"""

from ..tools import file_io
from ..tools.powerbi_executor import extract_rows
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: normalizing raw scan results...")

    raw = state.get("insight_raw_results", {})
    shared = state.get("baseline_coverage_clean_data", {})
    queries_out = [dict(q) for q in shared.get("queries", [])]
    success = int(shared.get("successful", 0))
    source_by_name = {q.get("name"): q for q in state.get("insight_validated_dax_queries", [])}

    # Reuse the pre-fork scope discovery as shared evidence.  It is not
    # executed again in the insight branch and retains its construction-time
    # contract.
    baseline = state.get("baseline_scope_evidence", {})
    if baseline.get("status") == "success" and baseline.get("rows"):
        queries_out.append({
            "query_name": baseline.get("query_name", "baseline_entity_scope"),
            "purpose": baseline.get("purpose", ""),
            "status": "success",
            "rows": baseline.get("rows", []),
            "dax": baseline.get("dax", ""),
            "contract_hint": baseline.get("contract_hint", {}),
            "shared_pre_fork": True,
        })
        success += 1
        scope = state.get("resolved_entity_scope", {})
        entity = scope.get("entity_dimension") or {}
        comparable = {str(v) for v in scope.get("active_comparable_population", [])}
        if entity.get("column") and comparable and not scope.get("truncated"):
            def entity_value(row):
                if entity["column"] in row:
                    return row.get(entity["column"])
                return next((v for k, v in row.items()
                             if k.split(".")[-1].strip("[]") == entity["column"]), None)
            filtered = [r for r in baseline.get("rows", [])
                        if str(entity_value(r)) in comparable]
            hint = dict(baseline.get("contract_hint", {}))
            hint.update({
                "source": "pre_fork_baseline_in_memory_filter",
                "coverage_kind": "full_entity_breakdown",
                "population_status": "comparable",
                "population_codes": sorted(comparable),
                "topn": None,
            })
            queries_out.append({
                "query_name": "baseline_comparable_entities",
                "purpose": "Complete comparable-entity breakdown derived from the shared scope baseline.",
                "status": "success",
                "rows": filtered,
                "dax": baseline.get("dax", ""),
                "contract_hint": hint,
                "shared_pre_fork": True,
                "derived_in_memory": True,
            })
            success += 1

    existing_names = {q.get("query_name") for q in queries_out}
    for name, item in raw.items():
        if name in existing_names:
            continue
        if item.get("status") == "success":
            source = source_by_name.get(name, {})
            rows = clean_rows(extract_rows(item.get("result", {})))
            queries_out.append({
                "query_name": name,
                "purpose": item.get("purpose", ""),
                "status": "success",
                "rows": rows,
                "dax": source.get("dax", item.get("query", "")),
                "contract_hint": source.get("contract_hint", {}),
            })
            success += 1
        else:
            source = source_by_name.get(name, {})
            queries_out.append({
                "query_name": name,
                "purpose": item.get("purpose", ""),
                "status": "failed",
                "error": item.get("error", "unknown error"),
                "dax": source.get("dax", item.get("query", "")),
                "contract_hint": source.get("contract_hint", {}),
            })

    clean = {
        "query_count": len(queries_out),
        "successful": success,
        "failed": len(queries_out) - success,
        "queries": queries_out,
    }
    file_io.write_json(state, "insight_clean_data.json", clean)
    log.info(f"Insight scan normalized {len(queries_out)} results ({success} successful).")
    return {"insight_clean_data": clean, **log.updates()}
