"""Metadata-driven deterministic DAX templates for the insight pipeline.

The semantic profiler decides *which* model objects are compatible.  This
module only turns that profile into bounded, auditable query shapes.  Every
query carries a ``contract_hint`` alongside its DAX so provenance is known by
construction rather than reverse-engineered from result labels.
"""

from __future__ import annotations

import re

from .semantic_profiler import build_profile, bundle_phase


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_") or "field"


def _lit(value) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _typed_lit(value, dimension: dict | None) -> str:
    """Render a DAX scalar using the metadata type of its target column."""
    data_type = str((dimension or {}).get("data_type", "")).lower()
    text = str(value).strip()
    if "date" in data_type:
        match = re.match(
            r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?",
            text,
        )
        if match:
            year, month, day = (int(match.group(i)) for i in range(1, 4))
            hour, minute, second = (int(match.group(i) or 0) for i in range(4, 7))
            date_expr = f"DATE({year}, {month}, {day})"
            return (f"{date_expr} + TIME({hour}, {minute}, {second})"
                    if hour or minute or second else date_expr)
    if any(token in data_type for token in
           ("int", "decimal", "double", "single", "currency", "number")):
        try:
            number = float(value)
            return str(int(number)) if number.is_integer() else format(number, ".15g")
        except (TypeError, ValueError):
            pass
    if "bool" in data_type:
        if text.lower() in ("true", "1"):
            return "TRUE()"
        if text.lower() in ("false", "0"):
            return "FALSE()"
    return _lit(value)


def _dedupe_dimensions(profile: dict, limit: int) -> list[dict]:
    entity_ref = (profile.get("entity_dimension") or {}).get("reference")
    time_refs = {d.get("reference") for d in profile.get("time_dimensions", [])}
    seen, out = set(), []
    for dim in profile.get("dimensions", []):
        if dim.get("reference") == entity_ref or dim.get("reference") in time_refs:
            continue
        semantic = _slug(dim.get("column"))
        if semantic in seen:
            continue
        seen.add(semantic)
        out.append(dim)
        if len(out) >= limit:
            break
    return out


def shape_from_profile(profile: dict, state: dict | None = None) -> dict:
    state = state or {}
    primary = profile.get("primary_value_bundle")
    if not primary:
        return {}
    max_dims = max(1, int(state.get("insight_metadata_max_dimensions", 5)))
    drivers = profile.get("volume_driver_bundles", [])[:2]
    return {
        "fact_table": profile.get("fact_table"),
        "entity": profile.get("entity_dimension"),
        "dimensions": _dedupe_dimensions(profile, max_dims),
        "time": (profile.get("time_dimensions") or [None])[0],
        "primary": primary,
        "drivers": drivers,
        "profile_source": profile.get("source"),
    }


def detect_shape(md: dict, understanding: dict | None = None, state: dict | None = None) -> dict:
    """Compatibility wrapper used by the gap scanner and offline replay."""
    profile = (state or {}).get("semantic_model_profile") or build_profile(md)
    return shape_from_profile(profile, state)


def _metric_specs(shape: dict) -> list[dict]:
    specs = []
    for bundle in [shape["primary"], *shape.get("drivers", [])]:
        for phase in ("current", "prior", "change"):
            spec = bundle_phase(bundle, phase)
            if not spec:
                continue
            specs.append({
                **spec,
                "family": bundle.get("family"),
                "bundle_id": bundle.get("id"),
                "semantic_role": ("value" if bundle is shape["primary"] else "volume"),
                "additive_candidate": bool(bundle.get("additive_candidate")),
            })
    return specs


def _selects(specs: list[dict], indent: str = "        ") -> str:
    return (",\n" + indent).join(f'"{s["alias"]}", {s["expression"]}' for s in specs)


def _population_filter(shape: dict, population: list[str]) -> str | None:
    entity = shape.get("entity") or {}
    if not population or not entity.get("reference"):
        return None
    values = ", ".join(_typed_lit(v, entity) for v in population)
    return f"TREATAS({{{values}}}, {entity['reference']})"


def _contract(shape: dict, grouping: list[dict], specs: list[dict], population: list[str],
              coverage_kind: str, topn: int | None, sort_alias: str | None,
              direction: str = "DESC", time_window: str = "all_available") -> dict:
    return {
        "source": "metadata_template",
        "coverage_kind": coverage_kind,
        "grouping": grouping,
        "metrics": specs,
        "population_status": "comparable" if population else "unfiltered",
        "population_codes": list(population),
        "entity_dimension": shape.get("entity"),
        "topn": topn,
        "sort": {"alias": sort_alias, "direction": direction} if sort_alias else None,
        "time_window": time_window,
    }


def _totals_query(shape: dict, population: list[str]) -> dict:
    specs = _metric_specs(shape)
    pop = _population_filter(shape, population)
    parts = []
    for spec in specs:
        expr = spec["expression"]
        if pop:
            expr = f"CALCULATE({expr}, {pop})"
        parts.append(f'"{spec["alias"]}", {expr}')
    dax = "EVALUATE\nROW(\n    " + ",\n    ".join(parts) + "\n)"
    return {
        "name": "meta_comparable_totals",
        "purpose": "Metadata-selected comparable totals for the primary value and compatible volume families.",
        "intent": "metadata_template:totals",
        "dax": dax,
        "contract_hint": _contract(shape, [], specs, population, "grand_total", None, None),
    }


def _base_table(shape: dict, dim: dict, population: list[str]) -> tuple[str, list[dict]]:
    specs = _metric_specs(shape)
    args = [dim["reference"]]
    pop = _population_filter(shape, population)
    if pop:
        args.append(pop)
    args.append(_selects(specs))
    return "SUMMARIZECOLUMNS(\n        " + ",\n        ".join(args) + "\n    )", specs


def _movers_query(shape: dict, dim: dict, population: list[str], max_rows: int) -> dict:
    base, specs = _base_table(shape, dim, population)
    change = next(s for s in specs if s["bundle_id"] == shape["primary"]["id"] and s["phase"] == "change")
    tail = max(3, max_rows // 2)
    dax = (
        "EVALUATE\n"
        f"VAR ScanBase =\n    {base}\n"
        "RETURN\nDISTINCT(\n    UNION(\n"
        f"        TOPN({tail}, ScanBase, [{change['alias']}], DESC),\n"
        f"        TOPN({tail}, ScanBase, [{change['alias']}], ASC)\n"
        "    )\n)\n"
        f"ORDER BY [{change['alias']}] DESC"
    )
    return {
        "name": f"meta_movers_by_{_slug(dim['table'])}_{_slug(dim['column'])}",
        "purpose": f"Largest positive and negative comparable movements by {dim['reference']}.",
        "intent": "metadata_template:paired_change_tails",
        "dax": dax,
        "contract_hint": _contract(shape, [dim], specs, population, "paired_change_tails",
                                     tail * 2, change["alias"]),
    }


def _concentration_query(shape: dict, dim: dict, population: list[str], max_rows: int) -> dict:
    base, specs = _base_table(shape, dim, population)
    current = next(s for s in specs if s["bundle_id"] == shape["primary"]["id"] and s["phase"] == "current")
    dax = (
        "EVALUATE\n"
        f"TOPN({max_rows},\n    {base},\n    [{current['alias']}], DESC)\n"
        f"ORDER BY [{current['alias']}] DESC"
    )
    return {
        "name": f"meta_concentration_by_{_slug(dim['table'])}_{_slug(dim['column'])}",
        "purpose": f"Top contributors to the primary current value by {dim['reference']}.",
        "intent": "metadata_template:concentration",
        "dax": dax,
        "contract_hint": _contract(shape, [dim], specs, population, "top_concentration",
                                     max_rows, current["alias"]),
    }


def _trend_query(shape: dict, dim: dict, population: list[str], max_rows: int) -> dict:
    base, specs = _base_table(shape, dim, population)
    current = next(s for s in specs if s["bundle_id"] == shape["primary"]["id"] and s["phase"] == "current")
    dax = (
        "EVALUATE\n"
        f"TOPN({max_rows},\n    {base},\n    {dim['reference']}, DESC)\n"
        f"ORDER BY {dim['reference']} DESC"
    )
    return {
        "name": f"meta_trend_by_{_slug(dim['table'])}_{_slug(dim['column'])}",
        "purpose": f"Recent primary value and volume movement over {dim['reference']}.",
        "intent": "metadata_template:trend",
        "dax": dax,
        "contract_hint": _contract(shape, [dim], specs, population, "recent_time_window",
                                     max_rows, dim["reference"], "DESC", "recent_window"),
    }


def _cross_query(shape: dict, left: dict, right: dict, population: list[str], max_rows: int) -> dict:
    specs = _metric_specs(shape)
    args = [left["reference"], right["reference"]]
    pop = _population_filter(shape, population)
    if pop:
        args.append(pop)
    args.append(_selects(specs))
    base = "SUMMARIZECOLUMNS(\n        " + ",\n        ".join(args) + "\n    )"
    change = next(s for s in specs if s["bundle_id"] == shape["primary"]["id"] and s["phase"] == "change")
    dax = (
        "EVALUATE\n"
        f"TOPN({max_rows},\n    {base},\n    ABS([{change['alias']}]), DESC)\n"
        f"ORDER BY [{change['alias']}] DESC"
    )
    return {
        "name": f"meta_cross_{_slug(left['column'])}_by_{_slug(right['column'])}",
        "purpose": f"Largest interactions between {left['reference']} and {right['reference']}.",
        "intent": "metadata_template:cross_dimension",
        "dax": dax,
        "contract_hint": _contract(shape, [left, right], specs, population,
                                     "top_cross_dimension", max_rows, change["alias"]),
    }


def build_metadata_scans(profile: dict, state: dict) -> list[dict]:
    shape = shape_from_profile(profile, state)
    if not shape:
        return []
    population = [str(v) for v in state.get("insight_comparable_population", []) or []]
    max_rows = max(5, int(state.get("max_rows_per_query", 15)))
    max_queries = max(1, int(state.get("insight_max_scan_queries", 10)))

    queries = [_totals_query(shape, population)]
    # The pre-fork baseline already covers the entity dimension completely.
    for dim in shape.get("dimensions", []):
        if len(queries) >= max_queries:
            break
        queries.append(_movers_query(shape, dim, population, max_rows))
    for dim in shape.get("dimensions", [])[:2]:
        if len(queries) >= max_queries:
            break
        queries.append(_concentration_query(shape, dim, population, max_rows))
    if shape.get("time") and len(queries) < max_queries:
        queries.append(_trend_query(shape, shape["time"], population, max(max_rows, 24)))
    if shape.get("entity") and shape.get("dimensions") and len(queries) < max_queries:
        queries.append(_cross_query(shape, shape["entity"], shape["dimensions"][0],
                                    population, max_rows))
    return queries[:max_queries]


def build_templated_scans(md: dict, understanding: dict, state: dict) -> list[dict]:
    """Backward-compatible name used by older replay callers."""
    profile = state.get("semantic_model_profile") or build_profile(md)
    return build_metadata_scans(profile, state)


def build_temporal_scan(profile: dict, state: dict, grain_dim: dict) -> dict | None:
    """One comparable primary+volume series grouped by a temporal grain column
    (Phase 2). The grain column is chosen by the grain gate (a validated business
    time axis, e.g. a month number) - never a load/posting-date axis. Carries the
    full current/prior/change metric bundle so the stat detector can rank which
    periods drove the comparable movement."""
    shape = shape_from_profile(profile, state)
    if not shape or not grain_dim or not grain_dim.get("reference"):
        return None
    population = [str(v) for v in state.get("insight_comparable_population", []) or []]
    specs = _metric_specs(shape)
    if not specs:
        return None
    args = [grain_dim["reference"]]
    pop = _population_filter(shape, population)
    if pop:
        args.append(pop)
    args.append(_selects(specs))
    base = "SUMMARIZECOLUMNS(\n        " + ",\n        ".join(args) + "\n    )"
    # TOPN wrap bounds the query (and satisfies the row-limit validator) while the
    # large cap keeps the whole ordered series - a temporal axis is naturally small.
    cap = max(500, 2 * int(state.get("insight_period_recent_window", 12)))
    dax = ("EVALUATE\n"
           f"TOPN({cap},\n    {base},\n    {grain_dim['reference']}, ASC)\n"
           f"ORDER BY {grain_dim['reference']} ASC")
    return {
        "name": f"meta_period_by_{_slug(grain_dim['table'])}_{_slug(grain_dim['column'])}",
        "purpose": f"Comparable primary/volume series by {grain_dim['reference']} (temporal level).",
        "intent": "metadata_template:period_series",
        "dax": dax,
        "contract_hint": _contract(shape, [grain_dim], specs, population, "period_series",
                                   None, None, "ASC", "period_series"),
    }


def build_gap_probe(shape: dict, seg_dim: dict, seg_value, drill_dim: dict,
                    population: list[str], max_rows: int,
                    scope_type: str = "comparable") -> dict:
    """Build one scoped segment × drill query and its provenance contract."""
    specs = _metric_specs(shape)
    sort_phase = "current"
    if scope_type == "prior_only":
        sort_phase = "prior"
    elif scope_type == "comparable":
        sort_phase = "change"
    if scope_type in ("current_only", "prior_only"):
        specs = [s for s in specs if s["phase"] == sort_phase]
    sort_metric = next(s for s in specs
                       if s["bundle_id"] == shape["primary"]["id"]
                       and s["phase"] == sort_phase)
    filters = []
    segment_values = ([str(v) for v in seg_value]
                      if isinstance(seg_value, (list, tuple, set))
                      else [str(seg_value)])
    segment_literals = ", ".join(_typed_lit(v, seg_dim) for v in segment_values)
    entity = shape.get("entity") or {}
    if seg_dim.get("reference") == entity.get("reference"):
        filters.append(f"TREATAS({{{segment_literals}}}, {entity['reference']})")
        scope_codes = segment_values
    else:
        pop = _population_filter(shape, population)
        if pop:
            filters.append(pop)
        filters.append(f"TREATAS({{{segment_literals}}}, {seg_dim['reference']})")
        scope_codes = list(population)
    args = [drill_dim["reference"], *filters, _selects(specs)]
    base = "SUMMARIZECOLUMNS(\n        " + ",\n        ".join(args) + "\n    )"
    dax = (
        "EVALUATE\n"
        f"TOPN({max_rows},\n    {base},\n    ABS([{sort_metric['alias']}]), DESC)\n"
        f"ORDER BY [{sort_metric['alias']}] DESC"
    )
    contract = _contract(shape, [drill_dim], specs, scope_codes,
                         "targeted_gap", max_rows, sort_metric["alias"])
    if scope_type in ("current_only", "prior_only"):
        contract["population_status"] = "entity_specific"
    contract["segment_filter"] = {
        "dimension": seg_dim,
        "value": str(seg_value),
        "values": segment_values,
    }
    return {"dax": dax, "contract_hint": contract}
