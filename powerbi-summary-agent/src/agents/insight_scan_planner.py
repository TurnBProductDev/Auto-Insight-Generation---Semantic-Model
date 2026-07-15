"""Insight scan planner (deterministic, metadata-driven).

Unlike the summary planner, the diagnostic coverage floor must be stable and
auditable.  The semantic profile selects coherent measures and compatible
dimensions; deterministic templates then produce the bounded portfolio.  No
LLM decides which model objects the scanner uses.
"""

from ..tools import file_io
from ..utils.logger import RunLogger
from .insight_scan_templates import build_metadata_scans


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: planning diagnostic coverage from semantic metadata...")
    queries = build_metadata_scans(state.get("semantic_model_profile", {}), state)
    plan = {
        "source": "semantic_model_profile",
        "query_budget": int(state.get("insight_max_scan_queries", 10)),
        "queries": queries,
    }
    file_io.write_json(state, "insight_dax_plan.json", plan)
    if queries:
        log.info(f"Metadata scan planned {len(queries)} queries: "
                 + ", ".join(q["name"] for q in queries))
    else:
        log.error("Metadata scan planner could not identify a coherent value/current/prior model shape.")
    return {"insight_dax_plan": plan, **log.updates()}
