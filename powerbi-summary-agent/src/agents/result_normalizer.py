"""Node 8 - Result Normalizer (deterministic).

Converts raw Power BI executeQueries JSON into clean, structured rows.
"""

from ..tools import file_io
from ..tools.powerbi_executor import extract_rows
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 8: normalizing raw Power BI results...")

    raw = state.get("raw_pbi_results", {})
    queries_out = []
    success = 0

    for name, item in raw.items():
        if item.get("status") == "success":
            rows = clean_rows(extract_rows(item.get("result", {})))
            queries_out.append({
                "query_name": name,
                "purpose": item.get("purpose", ""),
                "status": "success",
                "rows": rows,
            })
            success += 1
        else:
            queries_out.append({
                "query_name": name,
                "purpose": item.get("purpose", ""),
                "status": "failed",
                "error": item.get("error", "unknown error"),
            })

    clean = {
        "query_count": len(queries_out),
        "successful": success,
        "failed": len(queries_out) - success,
        "queries": queries_out,
    }
    file_io.write_json(state, "clean_summary_data.json", clean)
    log.info(f"Normalized {len(queries_out)} results ({success} successful).")
    return {"clean_summary_data": clean, **log.updates()}
