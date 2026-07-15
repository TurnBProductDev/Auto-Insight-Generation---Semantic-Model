"""Pre-fork entity-scope discovery and shared baseline evidence.

Metadata can identify the entity column and the current/prior measures, but it
cannot contain member values.  This node therefore performs one metadata-built
query to discover which entities have current and prior activity.  Explicit
configured business-rule populations remain authoritative overrides; the
automatic result audits them and supplies a safe fallback for other models.
"""

from __future__ import annotations

import math

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger
from .dax_validator import validate_one
from .semantic_profiler import bundle_phase


def _finite_nonzero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and abs(v) > 1e-9


def _row_value(row: dict, wanted: str):
    if wanted in row:
        return row[wanted]
    for key, value in row.items():
        if key.split(".")[-1].strip("[]") == wanted:
            return value
    return None


def build_query(profile: dict, max_entities: int) -> dict | None:
    entity = profile.get("entity_dimension") or {}
    bundle = profile.get("primary_value_bundle") or {}
    current = bundle_phase(bundle, "current")
    prior = bundle_phase(bundle, "prior")
    if not entity.get("reference") or not current or not prior:
        return None
    metrics = []
    for candidate_bundle in [bundle, *profile.get("volume_driver_bundles", [])[:2]]:
        for phase in ("current", "prior", "change"):
            metric = bundle_phase(candidate_bundle, phase)
            if metric:
                metrics.append({**metric, "family": candidate_bundle.get("family"),
                                "bundle_id": candidate_bundle.get("id"),
                                "semantic_role": ("value" if candidate_bundle is bundle else "volume"),
                                "additive_candidate": bool(candidate_bundle.get("additive_candidate"))})
    selects = ",\n        ".join(
        f'"{m["alias"]}", {m["expression"]}' for m in metrics
    )
    score = f'ABS([{current["alias"]}]) + ABS([{prior["alias"]}])'
    dax = (
        "EVALUATE\n"
        f"TOPN(\n    {max_entities},\n"
        "    SUMMARIZECOLUMNS(\n"
        f"        {entity['reference']},\n"
        f"        {selects}\n"
        "    ),\n"
        f"    {score}, DESC\n)\n"
        f"ORDER BY [{current['alias']}] DESC"
    )
    return {
        "name": "baseline_entity_scope",
        "purpose": "Discover comparable, current-only and prior-only entities from metadata-selected measures.",
        "dax": dax,
        "contract_hint": {
            "source": "metadata_template",
            "coverage_kind": "entity_scope_discovery",
            "grouping": [entity],
            "metrics": metrics,
            "population_status": "unfiltered_discovery",
            "topn": max_entities,
            "sort": {"alias": current["alias"], "direction": "DESC"},
            "time_window": "all_available",
        },
    }


def _resolve(rows: list, query: dict | None, state: dict) -> dict:
    configured_comparable = [str(v) for v in state.get("insight_comparable_population", []) or []]
    configured_excluded = [str(v) for v in state.get("insight_excluded_entities", []) or []]
    if not query:
        return {
            "entity_dimension": None,
            "active_comparable_population": configured_comparable,
            "excluded_from_comparison": configured_excluded,
            "new_entities": [], "prior_only_entities": [],
            "source": "business_rule_config" if configured_comparable else "unresolved",
            "truncated": False,
            "warnings": ["Metadata could not identify an entity/current/prior scope query."],
        }

    hint = query["contract_hint"]
    entity = hint["grouping"][0]
    current = next(m for m in hint["metrics"] if m["phase"] == "current")
    prior = next(m for m in hint["metrics"] if m["phase"] == "prior")
    auto_comparable, new, prior_only, inactive = [], [], [], []
    for row in rows:
        code = _row_value(row, entity["column"])
        if code is None:
            continue
        code = str(code)
        has_current = _finite_nonzero(_row_value(row, current["alias"]))
        has_prior = _finite_nonzero(_row_value(row, prior["alias"]))
        if has_current and has_prior:
            auto_comparable.append(code)
        elif has_current:
            new.append(code)
        elif has_prior:
            prior_only.append(code)
        else:
            inactive.append(code)

    max_entities = int(hint.get("topn") or 0)
    truncated = bool(rows) and max_entities and len(rows) >= max_entities
    warnings = []
    if truncated:
        warnings.append("Entity scope query reached its cap; automatic population may be incomplete.")

    auto_set = set(auto_comparable)
    if configured_comparable:
        active = configured_comparable
        source = "business_rule_config_validated_by_data"
        missing = [v for v in configured_comparable if v not in auto_set]
        unexpected = [v for v in auto_comparable if v not in set(configured_comparable)]
        if missing:
            warnings.append(f"Configured comparable entities without current+prior activity: {missing}")
        if unexpected:
            warnings.append(f"Automatically comparable entities omitted by business rules: {unexpected}")
    else:
        active = auto_comparable if not truncated else []
        source = "automatic_current_prior_activity" if active else "unresolved"

    excluded = list(dict.fromkeys(configured_excluded + new + prior_only))
    return {
        "entity_dimension": entity,
        "active_comparable_population": active,
        "automatically_comparable": auto_comparable,
        "excluded_from_comparison": excluded,
        "configured_exclusions": configured_excluded,
        "new_entities": new,
        "prior_only_entities": prior_only,
        "inactive_entities": inactive,
        "source": source,
        "truncated": bool(truncated),
        "warnings": warnings,
    }


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Baseline: discovering entity comparison scope from metadata-selected objects...")
    max_entities = max(10, int(state.get("metadata_scope_max_entities", 500)))
    query = build_query(state.get("semantic_model_profile", {}), max_entities)
    rows, status, error = [], "skipped", ""
    if query:
        reasons = validate_one(query["dax"], state.get("model_metadata", {}))
        if reasons:
            status, error = "failed", "; ".join(reasons)
        else:
            try:
                result = pbi.execute_python(
                    state["workspace_id"], state["dataset_id"],
                    [{"name": query["name"], "dax": query["dax"], "purpose": query["purpose"]}],
                    token=state.get("pbi_token"),
                )[query["name"]]
                status = result.get("status", "failed")
                if status == "success":
                    rows = clean_rows(pbi.extract_rows(result.get("result", {})))
                else:
                    error = str(result.get("error", "unknown error"))
            except Exception as exc:  # noqa: BLE001 - baseline is best effort
                status, error = "failed", str(exc)

    scope = _resolve(rows, query, state)
    evidence = {
        "query_name": query.get("name") if query else "baseline_entity_scope",
        "purpose": query.get("purpose", "") if query else "",
        "status": status,
        "rows": rows,
        "error": error,
        "dax": query.get("dax", "") if query else "",
        "contract_hint": query.get("contract_hint", {}) if query else {},
    }
    file_io.write_json(state, "baseline_scope_evidence.json", evidence)
    file_io.write_json(state, "resolved_entity_scope.json", scope)
    log.info(
        f"Baseline scope: {len(scope.get('active_comparable_population', []))} comparable, "
        f"{len(scope.get('new_entities', []))} current-only, "
        f"{len(scope.get('prior_only_entities', []))} prior-only; source={scope.get('source')}."
    )
    if error:
        log.error(f"  baseline scope query: {error[:200]}")
    for warning in scope.get("warnings", []):
        log.info(f"  scope caveat: {warning}")
    return {
        "baseline_scope_evidence": evidence,
        "resolved_entity_scope": scope,
        # Downstream compatibility: these now hold the resolved policy, not a
        # hardcoded model assumption.
        "insight_comparable_population": scope.get("active_comparable_population", []),
        "insight_excluded_entities": scope.get("excluded_from_comparison", []),
        **log.updates(),
    }
