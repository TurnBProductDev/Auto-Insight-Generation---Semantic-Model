"""Deterministic cross-signal thesis linker (Phase 9).

Two marginal findings are only promoted to one possible business thesis when
they describe different dimensions of the same metric and direction, and a
single bounded Power BI query verifies that their *intersection* moved beyond
what the two marginal movements independently predict.

For positive levels the interaction is evaluated in log-growth space:

    residual = growth(intersection) - growth(facet A)
               - growth(facet B) + growth(overall)

That is the planned ``cell - A - B + overall`` second difference.  A residual
near zero is consistent with independent main effects and is NOT called one
event.  A material residual in the shared movement direction is reported as
``same_movement`` (carefully hedged, never causal). Sparse/non-positive cells
fall back to ``related``.
"""

from __future__ import annotations

import math
import re
from itertools import combinations

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger
from . import insight_scan_templates as tpl
from .dax_validator import validate_one
from .evidence_contract import dax_hash
from .scope_validator import validate_comparable_scope


def _norm(value) -> str:
    return " ".join(str(value if value is not None else "").split()).strip().casefold()


def _sign(value) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return (value > 0) - (value < 0)
    return 0


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _cell(row: dict, alias: str):
    if alias in row:
        return row[alias]
    for key, value in row.items():
        if key.split(".")[-1].strip("[]") == alias:
            return value
    return None


def _all_dimensions(profile: dict) -> list[dict]:
    raw = ([profile.get("entity_dimension")] if profile.get("entity_dimension") else []) \
        + list(profile.get("dimensions", []) or []) \
        + list(profile.get("time_dimensions", []) or [])
    seen, out = set(), []
    for dim in raw:
        ref = (dim or {}).get("reference")
        if ref and ref not in seen:
            seen.add(ref)
            out.append(dim)
    return out


def _metric_key(signal: dict, contracts: dict) -> str | None:
    if signal.get("bundle_id"):
        return _norm(signal["bundle_id"])
    contract = contracts.get(signal.get("evidence_query"), {}) or {}
    roles = contract.get("metric_roles") or {}
    role = roles.get(signal.get("metric")) or {}
    canon = role.get("bundle_id") or role.get("family") or signal.get("metric")
    return _norm(canon) if canon else None


def _bundle(signal: dict, contracts: dict, profile: dict) -> dict | None:
    wanted = _metric_key(signal, contracts)
    bundles = list(profile.get("measure_bundles", []) or [])
    primary = profile.get("primary_value_bundle")
    if primary:
        bundles.insert(0, primary)
    for bundle in bundles:
        if wanted in {_norm(bundle.get("id")), _norm(bundle.get("family"))}:
            return bundle
    return None


def _period(signal: dict) -> str:
    for key in ("period_anchor", "week_start", "anchor", "episode_start"):
        if signal.get(key):
            return _norm(signal[key])
    return ""


def _members(signal: dict) -> set[str]:
    raw = signal.get("segment_members") or [signal.get("affected_segment")]
    return {_norm(v) for v in raw if v}


def _attrs(signal: dict, contracts: dict) -> dict:
    direction = _sign(signal.get("impact_value"))
    if not direction:
        direction = _sign(signal.get("reported_growth_pct"))
    return {"metric": _metric_key(signal, contracts), "direction": direction,
            "members": _members(signal), "period": _period(signal)}


def _shared(a: dict, b: dict) -> list[str]:
    shared = []
    if a["metric"] and a["metric"] == b["metric"]:
        shared.append("metric")
    if a["direction"] and a["direction"] == b["direction"]:
        shared.append("direction")
    if a["members"] & b["members"]:
        shared.append("member")
    if a["period"] and a["period"] == b["period"]:
        shared.append("period")
    return shared


def _facet(signal: dict, contracts: dict, profile: dict) -> dict | None:
    """Resolve one exact metadata dimension/member filter from deterministic facts."""
    contract = contracts.get(signal.get("evidence_query"), {}) or {}
    ref = signal.get("dimension")
    refs = contract.get("grouping_references") or []
    if len(refs) != 1:
        # A combined label from a 2-D table cannot be safely assigned to only one
        # of its dimensions. Wait for an explicit structured facet instead of
        # constructing a fake TREATAS value.
        return None
    if not ref and len(refs) == 1:
        ref = refs[0]
    dim = next((d for d in _all_dimensions(profile) if d.get("reference") == ref), None)
    if not dim:
        return None

    # A single-period contribution carries the raw typed anchor. Other findings
    # use the detector's raw member, never the LLM-humanized label.
    if signal.get("candidate_type") == "period_change_contribution" and signal.get("anchor"):
        values = [signal["anchor"]]
    else:
        raw = signal.get("segment_members") or signal.get("evidence_segment")
        values = list(raw) if isinstance(raw, (list, tuple, set)) else [raw]
    values = [v for v in values if v is not None and _norm(v) not in ("", "overall")]
    if not values:
        return None
    return {"dimension": dim, "values": values}


def _log_growth(pair) -> float | None:
    if not pair:
        return None
    current, prior = pair
    if _finite(current) and _finite(prior) and current > 0 and prior > 0:
        return math.log(current / prior)
    return None


def interaction_verdict(cells: dict | None, direction: int, tol: float) -> dict:
    """Evaluate ``intersection - A - B + overall`` in log-growth space."""
    if not cells:
        return {"verdict": "related", "basis": "sparse_evidence",
                "interaction": None, "confidence": "low"}
    growth = {name: _log_growth(cells.get(name))
              for name in ("intersection", "facet_a", "facet_b", "overall")}
    if any(value is None for value in growth.values()):
        return {"verdict": "related", "basis": "sparse_evidence",
                "interaction": None, "confidence": "low"}
    residual = round(growth["intersection"] - growth["facet_a"]
                     - growth["facet_b"] + growth["overall"], 6)
    facts = {"interaction": residual, "confidence": "low",
             "log_growth": {k: round(v, 6) for k, v in growth.items()}}
    if abs(residual) < tol:
        return {"verdict": "related", "basis": "independence_consistent", **facts}
    if direction and _sign(residual) == direction:
        return {"verdict": "same_movement",
                "basis": "interaction_exceeds_independence",
                **{**facts, "confidence": "moderate"}}
    return {"verdict": "related", "basis": "interaction_opposes_movement", **facts}


def _query_name(a: dict, b: dict) -> str:
    raw = f"thesis_{a.get('id', 'a')}_{b.get('id', 'b')}"
    return re.sub(r"[^a-zA-Z0-9_]+", "_", raw)[:100]


def _cells_from_rows(rows: list) -> dict | None:
    if not rows:
        return None
    row = rows[0]
    aliases = {
        "intersection": ("cell_current", "cell_prior"),
        "facet_a": ("facet_a_current", "facet_a_prior"),
        "facet_b": ("facet_b_current", "facet_b_prior"),
        "overall": ("overall_current", "overall_prior"),
    }
    return {name: (_cell(row, cur), _cell(row, prior))
            for name, (cur, prior) in aliases.items()}


def _execute_pair(state: dict, a: dict, b: dict, facet_a: dict, facet_b: dict,
                  bundle: dict, shape: dict, population: list[str], cache: dict) -> dict:
    built = tpl.build_thesis_interaction_scan(
        shape, bundle, facet_a, facet_b, population)
    if not built:
        return {"status": "unavailable", "basis": "unresolved_joint_shape",
                "cells": None, "cache_hit": False}
    dax, hint = built["dax"], built["contract_hint"]
    reasons = validate_one(dax, state.get("model_metadata", {}))
    reasons += validate_comparable_scope(dax, state, hint)
    if reasons:
        return {"status": "rejected", "basis": "; ".join(reasons),
                "cells": None, "cache_hit": False, "dax_hash": dax_hash(dax)}

    key = dax_hash(dax)
    cached = cache.get(key)
    if cached:
        status, rows, error = (cached.get("status"), cached.get("rows", []),
                               cached.get("error", ""))
    else:
        name = _query_name(a, b)
        try:
            item = pbi.execute_python(
                state["workspace_id"], state["dataset_id"],
                [{"name": name, "dax": dax,
                  "purpose": "bounded cross-signal interaction test"}],
                token=state.get("pbi_token"),
            )[name]
            status = item.get("status", "failed")
            rows = (clean_rows(pbi.extract_rows(item.get("result", {})))
                    if status == "success" else [])
            error = "" if status == "success" else str(item.get("error", "unknown error"))
        except Exception as exc:  # noqa: BLE001 - a thesis probe never kills the branch
            status, rows, error = "failed", [], str(exc)
        cache[key] = {"status": status, "rows": rows[:1], "error": error,
                      "dax": dax, "contract_hint": hint, "source": "thesis_linker"}
    return {"status": status, "basis": error or "joint_query",
            "cells": _cells_from_rows(rows) if status == "success" else None,
            "cache_hit": bool(cached), "dax_hash": key}


def _label(signal: dict) -> str:
    return str(signal.get("affected_segment") or signal.get("id") or "finding")


def run(state: dict) -> dict:
    log = RunLogger(state)
    cache = dict(state.get("insight_query_cache", {}) or {})
    if not state.get("insight_thesis_linking_enabled", False):
        log.info("Thesis linker: disabled (insight_thesis_linking_enabled=false).")
        return {"insight_theses": [], "insight_query_cache": cache, **log.updates()}

    signals = [s for s in state.get("insight_signals", []) or []
               if s.get("kind") != "data_quality"]
    if len(signals) < 2:
        log.info("Thesis linker: fewer than two business findings - nothing to link.")
        return {"insight_theses": [], "insight_query_cache": cache, **log.updates()}

    contracts = state.get("insight_evidence_contracts", {}) or {}
    profile = state.get("semantic_model_profile", {}) or {}
    shape = tpl.shape_from_profile(profile, state)
    population = [str(v) for v in (
        (state.get("resolved_entity_scope", {}) or {}).get("active_comparable_population")
        or state.get("insight_comparable_population", []) or [])]
    min_shared = max(2, int(state.get("insight_thesis_min_shared", 2)))
    max_links = max(0, int(state.get("insight_thesis_max_links", 2)))
    tol = max(0.0, float(state.get("insight_thesis_interaction_tol", 0.15)))
    min_impact = max(0.0, float(state.get("insight_thesis_min_impact", 0.0)))

    material = [s for s in signals if abs(s.get("impact_value") or 0.0) >= min_impact]
    attrs = {id(s): _attrs(s, contracts) for s in material}
    facets = {id(s): _facet(s, contracts, profile) for s in material}
    bundles = {id(s): _bundle(s, contracts, profile) for s in material}

    candidates = []
    for a, b in combinations(material, 2):
        aa, bb = attrs[id(a)], attrs[id(b)]
        fa, fb = facets[id(a)], facets[id(b)]
        shared = _shared(aa, bb)
        # Same metric + same direction are mandatory, and the two findings must
        # supply complementary dimensions. Same-dimension peers are not a thesis.
        if ("metric" not in shared or "direction" not in shared
                or len(shared) < min_shared or not fa or not fb
                or fa["dimension"].get("reference") == fb["dimension"].get("reference")):
            continue
        ba, bbundle = bundles[id(a)], bundles[id(b)]
        if not ba or not bbundle or _norm(ba.get("id")) != _norm(bbundle.get("id")):
            continue
        weight = abs(a.get("impact_value") or 0.0) + abs(b.get("impact_value") or 0.0)
        candidates.append((len(shared), weight, shared, a, b, fa, fb, ba))
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

    theses = []
    for _n, _weight, shared, a, b, fa, fb, bundle in candidates[:max_links]:
        evidence = _execute_pair(state, a, b, fa, fb, bundle, shape, population, cache)
        direction = attrs[id(a)]["direction"]
        result = interaction_verdict(evidence.get("cells"), direction, tol)
        theses.append({
            "members": [_label(a), _label(b)],
            "signal_ids": [a.get("id"), b.get("id")],
            "shared_attributes": shared,
            "facets": [fa, fb],
            "evidence_source": "joint_query" if evidence.get("cells") else "unavailable",
            "query_status": evidence.get("status"),
            "query_basis": evidence.get("basis"),
            "query_hash": evidence.get("dax_hash"),
            "cache_hit": evidence.get("cache_hit", False),
            "cells": evidence.get("cells"),
            **result,
        })

    file_io.write_json(state, "insight_theses.json", theses)
    same = sum(1 for thesis in theses if thesis["verdict"] == "same_movement")
    log.info(f"Thesis linker: {len(candidates)} candidate link(s), evaluated "
             f"{len(theses)} bounded joint query(s), {same} interaction-supported.")
    return {"insight_theses": theses, "insight_query_cache": cache, **log.updates()}
