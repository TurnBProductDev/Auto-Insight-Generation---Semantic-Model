"""Complete structural semantic-model context for LLM agents.

Measure expressions stay out of the general prompt payload because the
investigator can retrieve them on demand. Everything needed to select and
write queries - full column references, data types, numeric/date/categorical
roles, and relationships - is included without model-specific assumptions.
"""


def llm_model_context(metadata: dict) -> dict:
    """Return the full structural metadata view used by LLM nodes.

    The legacy string lists remain for easy exact-name lookup, while detailed
    records provide data types and relationship information. Hidden columns
    remain visible in ``column_details`` for completeness but are excluded
    from the preferred ``columns`` list.
    """
    columns = []
    visible_refs = []
    for col in metadata.get("columns", []):
        ref = f"{col.get('table', '')}[{col.get('column', '')}]"
        detail = {
            "reference": ref,
            "table": col.get("table", ""),
            "column": col.get("column", ""),
            "data_type": col.get("data_type", ""),
            "category": col.get("category", ""),
            "is_hidden": bool(col.get("is_hidden", False)),
        }
        columns.append(detail)
        if not detail["is_hidden"]:
            visible_refs.append(ref)

    measures = []
    measure_details = []
    for measure in metadata.get("measures", []):
        name = measure.get("name", "")
        if not name:
            continue
        measures.append(name)
        measure_details.append({
            "name": name,
            "table": measure.get("table", ""),
            "format_string": measure.get("format_string", ""),
            "description": measure.get("description", ""),
            "definition_available": bool(measure.get("expression")),
        })

    return {
        "tables": [t.get("name", "") for t in metadata.get("tables", []) if t.get("name")],
        "measures": measures,
        "measure_details": measure_details,
        "columns": visible_refs,
        "column_details": columns,
        "numeric_fields": list(metadata.get("numeric_fields", [])),
        "date_fields": list(metadata.get("date_fields", [])),
        "categorical_fields": list(metadata.get("categorical_fields", [])),
        "relationships": list(metadata.get("relationships", [])),
        "counts": dict(metadata.get("counts", {})),
    }
