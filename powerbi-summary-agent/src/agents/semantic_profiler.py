"""Deterministic semantic-model profiler.

The profiler is the metadata-driven control plane for the pipeline.  It turns
the raw INFO.VIEW/TMSL metadata into one auditable description of:

* coherent current/prior/change measure families;
* the primary additive value family and compatible volume drivers;
* the fact table those measures actually read;
* entity, categorical drill, and time dimensions that can safely filter it.

No model-specific object name is encoded here.  Generic semantic tokens are
only scoring hints; measure expressions, formats, data types, hidden flags and
the relationship graph are the stronger evidence.  A low-confidence choice is
reported as a warning instead of being presented as certain.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict, deque

from ..tools import file_io
from ..utils.logger import RunLogger


_TABLE_COL = re.compile(r"'([^']+)'\[([^\]]+)\]|([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]")
_MEASURE_REF = re.compile(r"(?<![\w'])\[([^\]]+)\]")
_WORDS = re.compile(r"[a-z0-9]+")

_CURRENT = {"current", "curr", "cy", "actual", "this", "ty"}
_PRIOR = {"past", "prior", "previous", "prev", "ly", "py", "last"}
_CHANGE = {"growth", "grwth", "change", "chg", "variance", "var", "delta", "difference", "diff", "yoy"}

_FAMILY_TOKENS = {
    "revenue": {"revenue", "rev", "sales", "sale", "turnover", "gmv", "value", "amount"},
    "profit": {"profit", "contribution", "earnings", "ebit", "ebitda"},
    "cost": {"cost", "expense", "spend"},
    "quantity": {"quantity", "qty", "units", "unit", "volume"},
    "transactions": {"transactions", "transaction", "bills", "bill", "orders", "order", "visits", "visit"},
    "customers": {"customers", "customer", "clients", "client", "shoppers", "shopper"},
    "margin": {"margin", "rate", "ratio", "percent", "percentage", "price", "average", "avg"},
}
_VALUE_FAMILIES = {"revenue", "profit", "cost"}
_VOLUME_FAMILIES = {"quantity", "transactions", "customers"}
_FAMILY_PRIORITY = {
    "revenue": 100,
    "profit": 90,
    "cost": 70,
    "quantity": 60,
    "transactions": 55,
    "customers": 50,
    "margin": 20,
    "other": 0,
}

_ENTITY_TOKENS = {
    "store", "branch", "outlet", "shop", "site", "location", "warehouse",
    "region", "country", "office", "facility", "entity", "businessunit",
}
_TIME_TOKENS = {
    "date", "day", "week", "month", "quarter", "year", "period", "fiscal",
}
_TECH_TOKENS = {
    "key", "id", "code", "rownumber", "row", "hash", "guid", "uuid", "index",
    "sort", "refresh", "timestamp", "ods",
}


def _tokens(*values) -> set[str]:
    return set(_WORDS.findall(" ".join(str(v or "") for v in values).lower()))


def _column_refs(expression: str) -> list[dict]:
    out = []
    for quoted_table, quoted_col, bare_table, bare_col in _TABLE_COL.findall(expression or ""):
        table, column = quoted_table or bare_table, quoted_col or bare_col
        if table and column:
            out.append({"table": table, "column": column})
    return out


def _source_tables(expression: str) -> list[str]:
    return [r["table"] for r in _column_refs(expression)]


def _phase(measure: dict) -> tuple[str | None, int]:
    text_tokens = _tokens(measure.get("name"), measure.get("description"),
                          measure.get("display_folder"))
    expr = (measure.get("expression") or "").lower()
    if text_tokens & _CHANGE:
        return "change", 100
    if text_tokens & _PRIOR:
        return "prior", 90
    if text_tokens & _CURRENT:
        return "current", 90
    # Formula evidence is weaker but useful for anonymous measures.
    if "-" in expr and ("sum(" in expr or "calculate(" in expr):
        return "change", 35
    return None, 0


def _family(measure: dict) -> tuple[str, int]:
    refs = _column_refs(measure.get("expression") or "")
    primary = _tokens(measure.get("name"), measure.get("description"),
                      measure.get("display_folder"))
    lineage = _tokens(" ".join(r["column"] for r in refs))
    # The semantic name/description is stronger than incidental lineage.  This
    # prevents a quantity measure over a column named ``net_sales_qty`` from
    # being classified as revenue merely because both "sales" and "qty" occur.
    scores = {
        family: 3 * len(primary & hints) + len(lineage & hints)
        for family, hints in _FAMILY_TOKENS.items()
    }
    best = max(scores, key=lambda k: (scores[k], _FAMILY_PRIORITY.get(k, 0)))
    return (best, scores[best] * 20) if scores[best] else ("other", 0)


def _ratioish(measure: dict) -> bool:
    expr = (measure.get("expression") or "").upper()
    fmt = str(measure.get("format_string") or "")
    toks = _tokens(measure.get("name"), measure.get("description"))
    return (
        "DIVIDE(" in expr or "/" in expr or "AVERAGE(" in expr or "DISTINCTCOUNT(" in expr
        or "%" in fmt or bool(toks & _FAMILY_TOKENS["margin"])
    )


def _additive(measure: dict, phase: str | None) -> bool:
    expr = (measure.get("expression") or "").upper()
    if _ratioish(measure):
        return False
    if any(fn in expr for fn in ("AVERAGE(", "DISTINCTCOUNT(", "MIN(", "MAX(")):
        return False
    if "SUM(" in expr or "SUMX(" in expr:
        return True
    # A change measure that subtracts already-additive measures will be checked
    # numerically later; metadata calls it a candidate, not proven additive.
    return bool(phase == "change" and "-" in expr)


def _reachable_tables(metadata: dict, start: str) -> dict[str, int]:
    graph: dict[str, set[str]] = defaultdict(set)
    for rel in metadata.get("relationships", []):
        if not rel.get("is_active", True):
            continue
        a, b = rel.get("from_table"), rel.get("to_table")
        if a and b:
            graph[a].add(b)
            graph[b].add(a)
    dist = {start: 0}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        if dist[cur] >= 2:  # conservative: avoid distant ambiguous filter paths
            continue
        for nxt in graph.get(cur, set()):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist


def _ref(table: str, column: str) -> str:
    return "'" + str(table).replace("'", "''") + f"'[{column}]"


def bundle_phase(bundle: dict, phase: str) -> dict | None:
    """Return ``{alias, expression, source, phase}`` for one bundle phase.

    The expression is a real measure reference when metadata exposes it, or a
    deterministic identity derived from two real measures (for example prior =
    current - change).  Callers never need to guess names themselves.
    """
    name = (bundle.get("measures") or {}).get(phase)
    if name:
        return {"alias": name, "expression": f"[{name}]", "source": "measure", "phase": phase}
    d = (bundle.get("derived") or {}).get(phase)
    if d:
        return {"alias": d["alias"], "expression": d["expression"],
                "source": "metadata_identity", "phase": phase}
    return None


def _dimension_score(col: dict, fact: str, distance: int) -> int:
    toks = _tokens(col.get("column"), col.get("description"), col.get("data_category"))
    score = 50 if col.get("table") == fact else max(5, 30 - distance * 10)
    name = str(col.get("column") or "").lower()
    if name.endswith("_name") or name.endswith(" name"):
        score += 35
    if toks & _ENTITY_TOKENS:
        score += 20
    if toks & _TIME_TOKENS:
        score -= 20  # time is ranked separately
    if toks & _TECH_TOKENS or any(x in name for x in ("rownumber", "uuid", "guid")):
        score -= 100
    if col.get("is_key"):
        score -= 80
    return score


def build_profile(metadata: dict) -> dict:
    measures = []
    for raw in metadata.get("measures", []):
        if raw.get("is_hidden"):
            continue
        phase, phase_conf = _phase(raw)
        family, family_conf = _family(raw)
        tables = Counter(_source_tables(raw.get("expression") or ""))
        source_table = tables.most_common(1)[0][0] if tables else raw.get("table", "")
        measures.append({
            "name": raw.get("name"),
            "home_table": raw.get("table", ""),
            "source_table": source_table,
            "source_tables": sorted(tables),
            "column_refs": _column_refs(raw.get("expression") or ""),
            "measure_refs": sorted(set(_MEASURE_REF.findall(raw.get("expression") or ""))),
            "phase": phase,
            "phase_confidence": phase_conf,
            "family": family,
            "family_confidence": family_conf,
            "ratio_like": _ratioish(raw),
            "additive_candidate": _additive(raw, phase),
            "format_string": raw.get("format_string", ""),
            "description": raw.get("description", ""),
            "definition_available": bool(raw.get("expression")),
        })

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for m in measures:
        if m["phase"] and m["family"] != "margin" and m.get("source_table"):
            grouped[(m["source_table"], m["family"])].append(m)

    bundles = []
    for (source_table, family), members in grouped.items():
        phases = {}
        for phase in ("current", "prior", "change"):
            candidates = [m for m in members if m["phase"] == phase]
            if candidates:
                candidates.sort(key=lambda m: (
                    not m["ratio_like"], m["additive_candidate"], m["phase_confidence"],
                    m["family_confidence"], m["definition_available"]
                ), reverse=True)
                phases[phase] = candidates[0]["name"]
        if "current" not in phases:
            continue
        derived = {}
        family_label = re.sub(r"[^a-z0-9]+", "_", family.lower()).strip("_") or "metric"
        if "prior" not in phases and "change" in phases:
            derived["prior"] = {
                "alias": f"{family_label}_prior_derived",
                "expression": f"[{phases['current']}] - [{phases['change']}]",
            }
        if "change" not in phases and "prior" in phases:
            derived["change"] = {
                "alias": f"{family_label}_change_derived",
                "expression": f"[{phases['current']}] - [{phases['prior']}]",
            }
        score = _FAMILY_PRIORITY.get(family, 0)
        score += 45 if "prior" in phases else 0
        score += 30 if "change" in phases else 0
        score += 15 if any(m["additive_candidate"] for m in members) else 0
        score += 10 if all(m["definition_available"] for m in members) else 0
        bundles.append({
            "id": f"{source_table}::{family}",
            "family": family,
            "source_table": source_table,
            "measures": phases,
            "derived": derived,
            "score": score,
            "additive_candidate": any(m["additive_candidate"] for m in members),
            "evidence": [m for m in members if m["name"] in phases.values()],
        })
    bundles.sort(key=lambda b: (b["score"], b["family"]), reverse=True)

    value_bundles = [b for b in bundles if b["family"] in _VALUE_FAMILIES
                     and ("prior" in b["measures"] or "prior" in b["derived"])]
    primary = value_bundles[0] if value_bundles else None
    fact = primary.get("source_table") if primary else ""

    reachable = _reachable_tables(metadata, fact) if fact else {}
    dimensions, time_dimensions = [], []
    for col in metadata.get("columns", []):
        if col.get("is_hidden") or col.get("table") not in reachable:
            continue
        table, column = col.get("table", ""), col.get("column", "")
        distance = reachable[table]
        toks = _tokens(column, col.get("description"), col.get("data_category"))
        rec = {
            "table": table,
            "column": column,
            "reference": _ref(table, column),
            "data_type": col.get("data_type", ""),
            "category": col.get("category", ""),
            "relationship_distance": distance,
        }
        if col.get("category") == "date" or toks & _TIME_TOKENS:
            rec["score"] = (100 if col.get("category") == "date" else 50) + (20 if table == fact else 0)
            time_dimensions.append(rec)
            continue
        if col.get("category") != "categorical":
            continue
        rec["score"] = _dimension_score(col, fact, distance)
        if rec["score"] > 0:
            dimensions.append(rec)

    dimensions.sort(key=lambda d: (d["score"], -d["relationship_distance"], d["reference"]), reverse=True)
    time_dimensions.sort(key=lambda d: (d["score"], d["reference"]), reverse=True)

    entity_candidates = []
    for dim in dimensions:
        toks = _tokens(dim["column"])
        score = dim["score"] + (100 if toks & _ENTITY_TOKENS else 0)
        if toks & _ENTITY_TOKENS:
            entity_candidates.append({**dim, "entity_score": score})
    entity_candidates.sort(key=lambda d: (d["entity_score"], d["reference"]), reverse=True)
    entity = entity_candidates[0] if entity_candidates else None

    volume = [b for b in bundles if b["family"] in _VOLUME_FAMILIES
              and b.get("additive_candidate")
              and ("prior" in b["measures"] or "prior" in b["derived"])]
    if primary:
        # Same-fact quantity is the strongest economic driver; related-table
        # transaction/customer measures remain available but lower ranked.
        volume.sort(key=lambda b: (
            b["source_table"] == primary["source_table"],
            b["family"] == "quantity", b["score"]
        ), reverse=True)

    warnings = []
    if not primary:
        warnings.append("No current+prior additive value family could be identified from metadata.")
    if primary and not entity:
        warnings.append("No high-confidence entity/location dimension was identified from metadata.")
    if any(not m["definition_available"] for m in measures):
        warnings.append("Some measure definitions are unavailable; those measures have lower semantic confidence.")

    return {
        "source": "semantic model metadata only",
        "primary_value_bundle": primary,
        "value_bundles": value_bundles,
        "volume_driver_bundles": volume,
        "measure_bundles": bundles,
        "measure_roles": {m["name"]: m for m in measures if m.get("name")},
        "fact_table": fact,
        "entity_dimension": entity,
        "dimensions": dimensions,
        "time_dimensions": time_dimensions,
        "warnings": warnings,
    }


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Metadata profile: deriving measures, dimensions and relationships...")
    profile = build_profile(state.get("model_metadata", {}))
    file_io.write_json(state, "semantic_model_profile.json", profile)
    primary = profile.get("primary_value_bundle") or {}
    entity = profile.get("entity_dimension") or {}
    log.info(
        "Metadata profile: primary=%s; fact=%s; entity=%s; %d drill dimensions; %d time dimensions."
        % (primary.get("family", "unresolved"), profile.get("fact_table") or "unresolved",
           entity.get("reference", "unresolved"), len(profile.get("dimensions", [])),
           len(profile.get("time_dimensions", [])))
    )
    for warning in profile.get("warnings", []):
        log.info(f"  metadata profile caveat: {warning}")
    return {"semantic_model_profile": profile, **log.updates()}
