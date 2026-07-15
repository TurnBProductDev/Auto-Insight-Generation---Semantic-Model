"""Node 2 - Metadata Reader (deterministic).

Runs the DAX INFO.VIEW functions and assembles structured model metadata.
Always uses the Python/REST executor (auth is proven), regardless of
execution_mode, because downstream planning needs metadata before any main
query runs.
"""

from ..tools import powerbi_executor as pbi
from ..tools import file_io
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger

METADATA_QUERIES = {
    "tables": "EVALUATE INFO.VIEW.TABLES()",
    "columns": "EVALUATE INFO.VIEW.COLUMNS()",
    "measures": "EVALUATE INFO.VIEW.MEASURES()",
    "relationships": "EVALUATE INFO.VIEW.RELATIONSHIPS()",
}


def _get(row: dict, *names, default=""):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return default


def _classify(data_type: str) -> str:
    t = (data_type or "").lower()
    if "date" in t or "time" in t:
        return "date"
    if any(k in t for k in ("number", "int", "decimal", "double", "currency", "whole", "float")):
        return "numeric"
    return "categorical"


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 2: reading semantic model metadata via INFO.VIEW DAX...")

    tenant_id = state.get("tenant_id")
    token = pbi.get_powerbi_token(tenant_id=tenant_id)
    raw = {}
    for key, dax in METADATA_QUERIES.items():
        ok, payload = pbi.run_dax(state["workspace_id"], state["dataset_id"], dax, token=token)
        if ok:
            raw[key] = clean_rows(pbi.extract_rows(payload))
            log.info(f"  {key}: {len(raw[key])} rows")
        else:
            raw[key] = []
            log.error(f"  {key}: metadata query failed -> {payload}")

    # --- assemble ---
    tables = []
    for r in raw["tables"]:
        name = _get(r, "Name", "Table")
        if not name:
            continue
        tables.append({
            "name": name,
            "description": _get(r, "Description"),
            "is_hidden": str(_get(r, "IsHidden", "Hidden", default="")).lower() in ("true", "1"),
        })

    columns = []
    for r in raw["columns"]:
        tbl = _get(r, "Table")
        col = _get(r, "Name", "Column")
        if not tbl or not col:
            continue
        dtype = _get(r, "DataType", "Data Type", "Type")
        hidden = str(_get(r, "IsHidden", "Hidden", default="")).lower() in ("true", "1")
        columns.append({
            "table": tbl, "column": col, "data_type": dtype,
            "category": _classify(dtype), "is_hidden": hidden,
            "description": _get(r, "Description"),
            "data_category": _get(r, "DataCategory", "Data Category"),
            "source_column": _get(r, "SourceColumn", "Source Column"),
            "sort_by_column": _get(r, "SortByColumn", "Sort By Column"),
            "summarize_by": _get(r, "SummarizeBy", "Summarize By"),
            "is_key": str(_get(r, "IsKey", "Key", default="")).lower() in ("true", "1"),
        })

    measures = []
    for r in raw["measures"]:
        name = _get(r, "Name", "Measure")
        if not name:
            continue
        measures.append({
            "name": name,
            "table": _get(r, "Table"),
            "expression": _get(r, "Expression"),
            "format_string": _get(r, "FormatString", "Format String"),
            "description": _get(r, "Description"),
            "display_folder": _get(r, "DisplayFolder", "Display Folder"),
            "is_hidden": str(_get(r, "IsHidden", "Hidden", default="")).lower() in ("true", "1"),
        })

    # executeQueries redacts measure Expression at this permission level. When
    # any come back blank, enrich from the Fabric getDefinition (TMSL) endpoint,
    # which returns the full model.bim including every measure's DAX. INFO.VIEW
    # stays the fallback: if Fabric is disabled, unavailable, or fails, the
    # blank expressions are simply left as-is.
    need_expr = measures and not all(m["expression"] for m in measures)
    if need_expr and state.get("fabric_definitions", True):
        try:
            tmsl_defs, err = pbi.fetch_measure_definitions_tmsl(
                state["workspace_id"], state["dataset_id"], tenant_id=tenant_id)
        except Exception as exc:  # noqa: BLE001 - enrichment must never be fatal
            tmsl_defs, err = {}, str(exc)
        if tmsl_defs:
            enriched = 0
            for m in measures:
                d = tmsl_defs.get(m["name"])
                if d and d.get("expression") and not m["expression"]:
                    m["expression"] = d["expression"]
                    enriched += 1
                if d:
                    if d.get("format_string"):
                        m["format_string"] = d["format_string"]
                    if d.get("description"):
                        m["description"] = d["description"]
                    if d.get("display_folder"):
                        m["display_folder"] = d["display_folder"]
                    if "is_hidden" in d:
                        m["is_hidden"] = bool(d["is_hidden"])
            log.info(f"  Fabric TMSL getDefinition: enriched {enriched}/{len(measures)} "
                     f"measure expressions.")
        else:
            log.info(f"  Fabric TMSL getDefinition unavailable ({err}); "
                     f"measure expressions stay blank (INFO.VIEW fallback).")

    relationships = []
    for r in raw["relationships"]:
        relationships.append({
            "from_table": _get(r, "FromTable", "From Table"),
            "from_column": _get(r, "FromColumn", "From Column"),
            "to_table": _get(r, "ToTable", "To Table"),
            "to_column": _get(r, "ToColumn", "To Column"),
            "is_active": _get(r, "IsActive", "Active", default=True),
            "cross_filtering_behavior": _get(r, "CrossFilteringBehavior", "Cross Filtering Behavior"),
            "from_cardinality": _get(r, "FromCardinality", "From Cardinality"),
            "to_cardinality": _get(r, "ToCardinality", "To Cardinality"),
        })

    skip_hidden = True
    visible_cols = [c for c in columns if not (skip_hidden and c["is_hidden"])]

    def fields(category):
        return [
            f"{c['table']}[{c['column']}]"
            for c in visible_cols
            if c["category"] == category and not c["column"].lower().startswith("rownumber")
        ]

    metadata = {
        "tables": tables,
        "columns": columns,
        "measures": measures,
        "relationships": relationships,
        "date_fields": fields("date"),
        "numeric_fields": fields("numeric"),
        "categorical_fields": fields("categorical"),
        "counts": {
            "tables": len(tables),
            "columns": len(columns),
            "measures": len(measures),
            "relationships": len(relationships),
        },
    }

    file_io.write_json(state, "model_metadata.json", metadata)

    with_expr = sum(1 for m in measures if m["expression"])
    if measures and not with_expr:
        log.info(
            "Note: all measure expressions are blank - executeQueries redacts them "
            "and the Fabric getDefinition enrichment did not fill them either. "
            "get_measure_definition will use its raw-column probe fallback."
        )
    elif measures and with_expr < len(measures):
        log.info(f"Note: {with_expr}/{len(measures)} measures have definitions available.")

    fatal = not tables and not measures and not columns
    if fatal:
        log.error("Metadata is empty - cannot continue (check dataset access / tenant setting).")
    else:
        log.info(
            f"Metadata assembled: {len(tables)} tables, {len(measures)} measures, "
            f"{len(metadata['date_fields'])} date fields."
        )

    # Share the token with both post-fork branches so neither re-enters the
    # (unlocked) MSAL cache read-modify-write concurrently.
    return {"model_metadata": metadata, "pbi_token": token, "fatal": fatal, **log.updates()}
