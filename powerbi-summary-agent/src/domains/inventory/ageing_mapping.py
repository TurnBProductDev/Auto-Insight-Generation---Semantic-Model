"""Fail-closed semantic mapping for arbitrary ageing models.

The resolver does not require object-name equality.  It scores names,
descriptions, types, measure lineage and table co-location, preserves the full
candidate audit, and accepts explicit overrides.  A plausible guess is never a
usable mapping: required roles need sufficient confidence and the business's
high-risk boundary must be supplied or observed explicitly.

Pure: metadata in, mapping recommendation out.  Sampling/reconciliation is a
separate execution step because this module never opens a Power BI connection.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

_WORDS = re.compile(r"[a-z0-9]+")

_HINTS = {
    "exposure": {
        "strong": {"stockvalue", "inventoryvalue", "balance", "outstanding",
                   "exposure", "carryingvalue", "netvalue"},
        "weak": {"stock", "inventory", "value", "amount", "cost", "receivable"},
    },
    "aged": {
        "strong": {"agedvalue", "agingvalue", "ageingvalue", "overduevalue",
                   "oldstock", "agingstock", "ageingstock"},
        "weak": {"aged", "aging", "ageing", "overdue", "old"},
    },
    "bucket": {
        "strong": {"agebucket", "agingbucket", "ageingbucket", "ageband",
                   "agingband", "ageingband", "overduebucket"},
        "weak": {"age", "aging", "ageing", "bucket", "band", "tenure", "overdue"},
    },
    "snapshot": {
        "strong": {"snapshotdate", "asatdate", "asofdate", "updatedon",
                   "refreshdate", "positiondate"},
        "weak": {"snapshot", "asat", "asof", "updated", "refresh", "position"},
    },
    "non_moving": {
        "strong": {"nonmovingstatus", "nosalesstatus", "movementstatus"},
        "weak": {"nonmoving", "nosales", "inactive", "stalled", "movement"},
    },
}

_TECH = {"id", "key", "code", "sort", "index", "rownumber", "guid", "uuid"}
_DIMENSION_HINTS = {
    "location": {"location", "loc", "store", "branch", "site", "warehouse", "outlet"},
    "division": {"division", "department", "businessunit"},
    "category": {"category", "section", "class", "brand", "productgroup"},
    "customer": {"customer", "account", "debtor", "client"},
    "supplier": {"supplier", "vendor", "creditor"},
    "product": {"product", "item", "sku", "material"},
}


def _tokens(*values: Any) -> set[str]:
    token_set: set[str] = set()
    for value in values:
        words = _WORDS.findall(str(value or "").lower())
        token_set.update(words)
        if words:
            token_set.add("".join(words))
    return token_set


def _reference(item: dict) -> str:
    if item.get("kind") == "measure":
        return f"[{item.get('name')}]"
    table = str(item.get("table") or "").replace("'", "''")
    return f"'{table}'[{item.get('column')}]"


def _items(metadata: dict) -> list[dict]:
    out = []
    for col in metadata.get("columns", []) or []:
        if not col.get("is_hidden"):
            out.append({**col, "kind": "column", "name": col.get("column")})
    for measure in metadata.get("measures", []) or []:
        if not measure.get("is_hidden"):
            out.append({**measure, "kind": "measure", "column": None})
    return out


def _type_ok(item: dict, role: str) -> bool:
    dtype = str(item.get("data_type") or "").lower()
    category = str(item.get("category") or item.get("data_category") or "").lower()
    if role in {"exposure", "aged"}:
        return item.get("kind") == "measure" or any(
            word in dtype for word in ("int", "decimal", "double", "number", "currency"))
    if role in {"bucket", "non_moving"}:
        return any(word in dtype for word in ("text", "string")) or category == "categorical"
    if role == "snapshot":
        return "date" in dtype or category == "date"
    return True


def _score(item: dict, role: str) -> tuple[int, list[str]]:
    if not _type_ok(item, role):
        return -1000, ["incompatible data type"]
    toks = _tokens(item.get("name"), item.get("description"), item.get("display_folder"),
                   item.get("source_column"), item.get("expression"))
    hints = _HINTS[role]
    strong, weak = toks & hints["strong"], toks & hints["weak"]
    score = 80 * len(strong) + 18 * len(weak)
    why = []
    if strong:
        why.append("strong semantic token: " + ", ".join(sorted(strong)))
    if weak:
        why.append("supporting token: " + ", ".join(sorted(weak)))
    if item.get("kind") == "measure" and role in {"exposure", "aged"}:
        score += 15
        why.append("model measure")
    expression = str(item.get("expression") or "").lower()
    if role in {"exposure", "aged"} and any(x in expression for x in ("sum(", "sumx(")):
        score += 12
        why.append("additive expression")
    if role in {"exposure", "aged"} and any(x in expression for x in ("divide(", "average(")):
        score -= 60
        why.append("ratio/average penalty")
    if toks & {"share", "percent", "percentage", "ratio", "pct"}:
        score -= 70
        why.append("ratio-name penalty")
    return score, why


def _rank(metadata: dict, role: str) -> list[dict]:
    ranked = []
    for item in _items(metadata):
        score, evidence = _score(item, role)
        if score > 0:
            ranked.append({"reference": _reference(item), "table": item.get("table"),
                           "kind": item.get("kind"), "score": score,
                           "evidence": evidence})
    ranked.sort(key=lambda x: (-x["score"], x["reference"]))
    return ranked


def _confidence(candidates: list[dict]) -> str:
    if not candidates:
        return "none"
    top = candidates[0]["score"]
    margin = top - (candidates[1]["score"] if len(candidates) > 1 else 0)
    if top >= 80 and margin >= 20:
        return "high"
    if top >= 45 and margin >= 10:
        return "medium"
    return "low"


def _reachable(metadata: dict, origins: set[str]) -> dict[str, int]:
    graph: dict[str, set[str]] = defaultdict(set)
    for rel in metadata.get("relationships", []) or []:
        if rel.get("is_active", True) is False:
            continue
        left, right = rel.get("from_table"), rel.get("to_table")
        if left and right:
            graph[str(left)].add(str(right))
            graph[str(right)].add(str(left))
    distance = {table: 0 for table in origins if table}
    frontier = list(distance)
    while frontier:
        table = frontier.pop(0)
        if distance[table] >= 2:
            continue
        for linked in graph.get(table, set()):
            if linked not in distance:
                distance[linked] = distance[table] + 1
                frontier.append(linked)
    return distance


def _dimensions(metadata: dict, excluded: set[str], origins: set[str]) -> dict[str, list[dict]]:
    roles: dict[str, list[dict]] = defaultdict(list)
    distance = _reachable(metadata, origins)
    for item in _items(metadata):
        if item.get("kind") != "column" or not _type_ok(item, "bucket"):
            continue
        table = str(item.get("table") or "")
        if table not in distance:
            continue
        reference = _reference(item)
        if reference in excluded:
            continue
        toks = _tokens(item.get("name"), item.get("description"))
        for role, hints in _DIMENSION_HINTS.items():
            overlap = toks & hints
            if overlap:
                # A semantic field such as LOC_CODE remains valid despite the
                # technical suffix; a bare ID/code with no role token does not.
                table_bonus = 40 if distance[table] == 0 else max(0, 20 - distance[table] * 10)
                roles[role].append({"reference": reference, "table": item.get("table"),
                                    "score": 30 + 20 * len(overlap) + table_bonus,
                                    "relationship_distance": distance[table],
                                    "evidence": sorted(overlap)})
    for values in roles.values():
        values.sort(key=lambda x: (-x["score"], x["reference"]))
    return dict(roles)


def resolve(metadata: dict, *, overrides: dict | None = None,
            observed: dict | None = None) -> dict:
    """Recommend an ageing mapping and state exactly what remains unresolved.

    ``observed`` is populated by a bounded sampler and may contain
    ``bucket_order``, ``high_risk_bands``, ``snapshot_cardinality`` and
    ``reconciled``.  These measured facts outrank naming hints.
    """
    overrides, observed = overrides or {}, observed or {}
    required = ("exposure", "bucket", "snapshot")
    optional = ("aged", "non_moving")
    roles = {}
    issues, warnings = [], []
    all_references = {_reference(item) for item in _items(metadata)}

    for role in required + optional:
        candidates = _rank(metadata, role)
        measured = observed.get(f"{role}_reference")
        derived = role == "aged" and observed.get("aged_derived") is True
        chosen = (None if derived else
                  overrides.get(role) or measured or (candidates[0]["reference"] if candidates else None))
        confidence = ("derived" if derived else
                      "override" if overrides.get(role) else
                      "measured" if measured else _confidence(candidates))
        if overrides.get(role) and chosen not in all_references:
            issues.append(f"Configured {role} reference does not exist: {chosen}")
            chosen, confidence = None, "none"
        if measured and chosen not in all_references:
            issues.append(f"Measured {role} reference does not exist in metadata: {chosen}")
            chosen, confidence = None, "none"
        roles[role] = {"reference": chosen, "confidence": confidence,
                       "candidates": candidates[:5]}
        if role in required and (not chosen or confidence in {"none", "low"}):
            issues.append(f"{role} mapping is missing or ambiguous")
        elif role in optional and confidence == "low":
            warnings.append(f"Optional {role} mapping is ambiguous and will not be used automatically")

    # A date-looking field is not enough: one current position needs one as-at
    # value. The sampler must establish this before execution is safe.
    cardinality = observed.get("snapshot_cardinality")
    if cardinality is None:
        issues.append("snapshot role requires a bounded cardinality check")
    elif int(cardinality) != 1:
        issues.append(f"snapshot role returned {cardinality} values; one current position was expected")

    high_risk = overrides.get("high_risk_bands") or observed.get("high_risk_bands")
    bucket_order = overrides.get("bucket_order") or observed.get("bucket_order")
    if not bucket_order:
        issues.append("age-bucket order has not been observed or configured")
    if not high_risk:
        issues.append("the business high-risk bucket boundary has not been observed or configured")
    if observed.get("reconciled") is False:
        issues.append("sampled bucket values did not reconcile to total exposure")

    excluded = {v["reference"] for v in roles.values() if v.get("reference")}
    reference_tables = {
        _reference(item): str(item.get("table") or "") for item in _items(metadata)
    }
    origins = {reference_tables.get(ref, "") for ref in excluded}
    dimensions = _dimensions(metadata, excluded, origins)
    configured_dimensions = overrides.get("dimensions")
    if configured_dimensions:
        dimensions = {str(role): [{"reference": ref, "score": 999,
                                   "evidence": ["configured"]}]
                      for role, ref in configured_dimensions.items()}
    if not dimensions:
        warnings.append("No business breakdown dimensions were identified; overall ageing still works")

    status = "ready" if not issues else "review"
    return {
        "status": status,
        "method": "ageing_semantic_mapping_v1",
        "roles": roles,
        "dimensions": dimensions,
        "bucket_order": bucket_order or [],
        "high_risk_bands": high_risk or [],
        "issues": issues,
        "warnings": warnings,
        "requires_configuration": status != "ready",
    }
