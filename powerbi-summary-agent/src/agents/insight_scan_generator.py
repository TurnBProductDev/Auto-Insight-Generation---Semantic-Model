"""Materialize metadata-planned insight DAX (deterministic, no LLM)."""

from ..tools import file_io
from ..utils.logger import RunLogger


def run(state: dict) -> dict:
    log = RunLogger(state)
    planned = list((state.get("insight_dax_plan") or {}).get("queries", []))
    generated = []
    for query in planned:
        generated.append({
            "name": query["name"],
            "purpose": query.get("purpose", ""),
            "intent": query.get("intent", "metadata_template"),
            "dax": query.get("dax", ""),
            "contract_hint": query.get("contract_hint", {}),
            "generation": "metadata_template",
        })
    file_io.write_json(state, "insight_generated_dax_queries.json", generated)
    log.info(f"Insight scan materialized {len(generated)} metadata-templated DAX statements.")
    return {"insight_generated_dax_queries": generated, **log.updates()}
