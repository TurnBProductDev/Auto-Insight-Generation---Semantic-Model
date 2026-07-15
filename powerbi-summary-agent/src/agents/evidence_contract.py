"""Evidence Contract extractor (deterministic, no LLM).

Every scan/probe result becomes an *evidence record* with a structured
contract describing exactly what it is and how far it can be trusted. The
investigator's reuse path (see evidence_assembler) reads these contracts so it
never re-derives a fact the scan already holds - and, critically, never
reuses a fact that is truncated, wrongly scoped, or unverifiable.

The load-bearing rule is CONSERVATISM: a property is only asserted when the
evidence proves it. Structure (grouping columns, metrics) is read from the
returned rows - the ground truth of what the query produced. Scope (store
population, period window, TOPN, sort) is parsed from the DAX text, reusing
the validator's reference regexes. Where the DAX cannot be parsed with
confidence, the property is marked ``unknown`` / ``scope_ambiguous`` - never
inferred optimistically (an unrecognised filter is not "no filter").

Business-rule scope is first-class: ``population_status`` reports whether an
evidence record is confined to the comparable entity population, silently
includes an excluded/new entity (the new/excluded-entity leak failure mode), or cannot be
determined. The comparable population and excluded entities come from config
(``insight_comparable_population`` / ``insight_excluded_entities``), mirroring
config/business_rules.md - keep the two in sync.

Contract fields per record::

    query_name, purpose, metrics[], grouping_columns[], grouping_dimensions[],
    filters{store, period, parse_confidence}, population_status, population{},
    time_window, sort{}, topn, row_count, completeness, completeness_reason,
    dax_hash

``completeness`` is one of complete | partial | unknown and is the single flag
the reuse gate keys on together with ``population_status``.
"""

import hashlib
import re

from .dax_validator import _ALIAS_DEF, _extract_refs
from .insight_stat_detector import _classify_columns, _coerce_sentinels
from ..tools import file_io
from ..utils.logger import RunLogger

# String literals in DAX: "value". Alias names (the "Name" slot of
# ADDCOLUMNS/SUMMARIZECOLUMNS/ROW) are also quoted, so intersecting literals
# with the *known* entity-code universe naturally excludes them.
_STRING_LIT = re.compile(r'"([^"]*)"')
_TOPN = re.compile(r"\bTOPN\s*\(\s*([0-9]+)", re.IGNORECASE)
_ORDERBY = re.compile(r"\bORDER\s+BY\b(.+?)(?:$)", re.IGNORECASE | re.DOTALL)
# Period/date filter hints: a comparison or a date function anywhere in the DAX.
_PERIOD_HINT = re.compile(
    r"\[(?:month|period|week|year|date)[^\]]*\]|\b(?:DATESBETWEEN|DATESINPERIOD|"
    r"CALENDAR|MAX\s*\(\s*'?[^)]*date|TODAY|NOW)\b",
    re.IGNORECASE,
)


def normalize_dax(dax: str) -> str:
    """Whitespace-collapsed form for stable hashing/equality of two DAX strings."""
    return re.sub(r"\s+", " ", (dax or "").strip())


def dax_hash(dax: str) -> str:
    """Exact-match signature only (not semantic equivalence): two queries that
    differ solely by whitespace collide; anything else does not."""
    return hashlib.sha256(normalize_dax(dax).encode("utf-8")).hexdigest()[:16]


def _string_literals(dax: str) -> set:
    return set(_STRING_LIT.findall(dax or ""))


def _alias_names(dax: str) -> set:
    return set(_ALIAS_DEF.findall(dax or ""))


def _topn(dax: str):
    m = _TOPN.search(dax or "")
    return int(m.group(1)) if m else None


def _order_by(dax: str):
    m = _ORDERBY.search(dax or "")
    return m.group(1).strip()[:200] if m else None


def _grouping_and_metrics(rows: list, roles: dict) -> tuple:
    """Grouping = label columns actually present in the output; metrics = numeric
    columns. Read from the rows (ground truth) rather than parsed from the DAX -
    the query's real shape, not its intended one."""
    grouping = list(roles.get("labels", []))
    if roles.get("date"):
        grouping.append(roles["date"])
    if roles.get("period"):
        grouping.append(roles["period"])
    metrics = list(roles.get("numerics", []))
    return grouping, metrics


def _detect_population(dax: str, rows: list, label_cols: list,
                       comparable: set, excluded: set, truncated: bool) -> dict:
    """Classify an evidence record's entity scope against the business-rule
    comparable population. Combines DAX filter literals with the entity values
    that actually appear in the rows, so a record is only called ``comparable``
    when it is *provably* confined to the comparable set."""
    universe = comparable | excluded
    if not universe:
        return {"status": "unknown", "codes": [], "store_column": None,
                "reason": "no comparable population configured"}

    lits = _string_literals(dax) & universe

    # The store dimension is the label column whose values overlap the known
    # entity-code universe (model-agnostic: no reliance on the column's name).
    store_col, store_vals = None, set()
    for c in label_cols:
        vals = {str(r.get(c)) for r in rows if r.get(c) is not None}
        if vals & universe:
            store_col, store_vals = c, vals
            break

    found_excl = (lits & excluded) | (store_vals & excluded)
    if found_excl:
        return {"status": "includes_excluded", "codes": sorted(lits | store_vals),
                "store_column": store_col,
                "reason": f"excluded entity present: {sorted(found_excl)}"}

    # Explicit comparable filter: the DAX pins every comparable code (and no
    # excluded one, handled above).
    if lits and comparable and lits >= comparable:
        return {"status": "comparable", "codes": sorted(lits),
                "store_column": store_col, "reason": "explicit comparable filter"}

    # Enumerated comparable: a by-entity breakdown whose returned entities are a
    # subset of the comparable set - but only trustworthy when NOT truncated
    # (a top-N cut could simply have dropped the excluded entity off the tail).
    if store_vals and store_vals <= comparable and not truncated:
        return {"status": "comparable", "codes": sorted(store_vals),
                "store_column": store_col,
                "reason": "returned entities are all within the comparable set"}

    if lits and comparable and lits < comparable:
        return {"status": "partial_population", "codes": sorted(lits),
                "store_column": store_col,
                "reason": f"only part of the comparable set filtered: {sorted(lits)}"}

    if store_col is not None:
        # Grouped by entity but scope not provably comparable (truncated, or
        # values not a clean subset) - cannot suppress a check.
        return {"status": "scope_ambiguous", "codes": sorted(store_vals),
                "store_column": store_col,
                "reason": "entity breakdown not provably confined to comparable set"}

    # No entity filter and no entity grouping: the record silently spans every
    # entity, including excluded ones. This is exactly the new/excluded-entity leak shape.
    return {"status": "unfiltered", "codes": [], "store_column": None,
            "reason": "no entity scope detected; may span all entities incl. excluded"}


def _completeness(rows: list, roles: dict, topn, truncated: bool) -> tuple:
    """complete | partial | unknown, with a reason. Truncated (row_count hit the
    TOPN/row cap), date/period-windowed, or single-total tables are *not*
    'complete' breakdowns for reuse purposes."""
    n = len(rows)
    if truncated:
        return "partial", f"row count ({n}) reached the query's TOPN/row cap"
    if roles.get("date") or roles.get("period"):
        return "partial", "date/period-windowed: covers a time slice, not the full population"
    if not roles.get("labels"):
        return "complete", "single grand-total row" if n == 1 else "unlabelled aggregate"
    if n == 0:
        return "unknown", "empty result"
    return "complete", "full labelled breakdown, not truncated"


def _hint_contract(query: dict, dax: str, hint: dict, rows: list, roles: dict) -> dict:
    grouping_specs = hint.get("grouping", []) or []
    metric_specs = hint.get("metrics", []) or []
    grouping_columns = [g.get("column") or g.get("reference") for g in grouping_specs]
    grouping_refs = [g.get("reference") for g in grouping_specs if g.get("reference")]
    metrics = [m.get("alias") for m in metric_specs if m.get("alias")]
    topn = hint.get("topn")
    truncated = bool(rows) and topn is not None and len(rows) >= int(topn)
    kind = hint.get("coverage_kind", "unknown")
    intrinsically_partial = kind in {
        "paired_change_tails", "top_concentration", "recent_time_window",
        "top_cross_dimension", "targeted_gap",
    }
    if kind == "grand_total":
        completeness, reason = "complete", "single scoped grand total by construction"
    elif truncated or intrinsically_partial:
        completeness = "partial"
        reason = ("query reached its row limit" if truncated else
                  f"{kind} intentionally covers only a ranked/windowed slice")
    elif not rows:
        completeness, reason = "unknown", "empty result"
    else:
        completeness, reason = "complete", "construction-time contract and returned count indicate full coverage"

    population_status = hint.get("population_status", "unknown")
    population_codes = [str(v) for v in hint.get("population_codes", []) or []]
    if kind == "entity_scope_discovery":
        population_status = "unfiltered_discovery"
    return {
        "query_name": query.get("query_name") or query.get("name") or "?",
        "purpose": query.get("purpose", ""),
        "metrics": metrics,
        "metric_roles": {m.get("alias"): m for m in metric_specs if m.get("alias")},
        "grouping_columns": grouping_columns,
        "grouping_references": grouping_refs,
        "grouping_dimensions": grouping_columns,
        "filters": {
            "store": {"detected": bool(population_codes), "codes": population_codes,
                      "column": (hint.get("entity_dimension") or {}).get("column")},
            "period": {"detected": kind == "recent_time_window"},
            "parse_confidence": "construction",
        },
        "population_status": population_status,
        "population": {
            "status": population_status,
            "codes": population_codes,
            "store_column": (hint.get("entity_dimension") or {}).get("column"),
            "reason": "metadata template contract",
        },
        "time_window": hint.get("time_window", "all_available"),
        "sort": hint.get("sort") or {"detected": False, "raw": None},
        "topn": topn,
        "row_count": len(rows),
        "truncated": bool(truncated),
        "coverage_kind": kind,
        "completeness": completeness,
        "completeness_reason": reason,
        "segment_filter": hint.get("segment_filter"),
        "contract_source": hint.get("source", "metadata_template"),
        "dax_hash": dax_hash(dax),
    }


def extract_contract(query: dict, dax: str, metadata: dict, state: dict,
                     contract_hint: dict | None = None) -> dict:
    """Build the structured contract for one evidence record.

    ``query`` is a normalized scan/probe result ({query_name, status, rows});
    ``dax`` is its source statement (may be '' for a record whose DAX was not
    retained - scope then degrades to unknown, never optimistic)."""
    rows = _coerce_sentinels(query.get("rows") or [])
    roles = _classify_columns(rows)
    if contract_hint:
        return _hint_contract(query, dax, contract_hint, rows, roles)
    grouping, metrics = _grouping_and_metrics(rows, roles)

    row_cap = max(2, int(state.get("max_rows_per_query", 15)))
    topn = _topn(dax)
    n = len(rows)
    # Truncated if the row count reached an explicit TOPN or the global row cap
    # (the same heuristic the stat detector uses for coverage decisions).
    truncated = bool(rows) and ((topn is not None and n >= topn) or n >= row_cap)

    comparable = {str(x) for x in state.get("insight_comparable_population", []) or []}
    excluded = {str(x) for x in state.get("insight_excluded_entities", []) or []}
    population = _detect_population(dax, rows, roles.get("labels", []),
                                   comparable, excluded, truncated)

    completeness, comp_reason = _completeness(rows, roles, topn, truncated)

    period_detected = bool(_PERIOD_HINT.search(dax or "")) or bool(roles.get("period") or roles.get("date"))
    order = _order_by(dax)

    # Parse confidence is low when we had no DAX to read - scope claims then
    # rest only on the returned values, so downstream must treat them as soft.
    parse_confidence = "high" if dax else "low"

    return {
        "query_name": query.get("query_name") or query.get("name") or "?",
        "purpose": query.get("purpose", ""),
        "metrics": metrics,
        "grouping_columns": grouping,
        "grouping_dimensions": [g.split("[")[-1].rstrip("]") if "[" in g else g
                                for g in grouping],
        "filters": {
            "store": {"detected": population["status"] not in ("unfiltered", "unknown"),
                      "codes": population["codes"],
                      "column": population["store_column"]},
            "period": {"detected": period_detected},
            "parse_confidence": parse_confidence,
        },
        "population_status": population["status"],
        "population": population,
        "time_window": ("windowed" if (roles.get("date") or roles.get("period"))
                        else ("windowed_filter" if period_detected else
                              ("point_in_time" if dax else "unknown"))),
        "sort": {"detected": order is not None, "raw": order},
        "topn": topn,
        "row_count": n,
        "truncated": truncated,
        "completeness": completeness,
        "completeness_reason": comp_reason,
        "dax_hash": dax_hash(dax),
        "coverage_kind": "parsed_unknown",
        "metric_roles": {},
        "grouping_references": [],
        "contract_source": "parsed_dax_and_rows",
    }


def build_contracts(state: dict) -> dict:
    """Contract every successful scan table. Joins normalized rows
    (insight_clean_data) with their source DAX (insight_validated_dax_queries)
    by name; a table whose DAX cannot be found is contracted at low confidence.

    Returns ``{query_name: contract}``.
    """
    metadata = state.get("model_metadata", {})
    clean = state.get("insight_clean_data", {"queries": []})
    source_by_name = {q.get("name"): q
                      for q in state.get("insight_validated_dax_queries", []) or []}

    contracts = {}
    for q in clean.get("queries", []):
        if q.get("status") != "success":
            continue
        name = q.get("query_name")
        source = source_by_name.get(name, {})
        dax = q.get("dax") or source.get("dax", "")
        hint = q.get("contract_hint") or source.get("contract_hint") or {}
        contracts[name] = extract_contract(q, dax, metadata, state, hint)
    return contracts


def run(state: dict) -> dict:
    """Graph node: contract scan evidence before statistical detection."""
    log = RunLogger(state)
    contracts = build_contracts(state)
    file_io.write_json(state, "insight_evidence_contracts.json", contracts)
    constructed = sum(1 for c in contracts.values() if c.get("contract_source") == "metadata_template")
    log.info(f"Evidence catalog: {len(contracts)} contracts ({constructed} construction-time).")
    return {"insight_evidence_contracts": contracts, **log.updates()}
