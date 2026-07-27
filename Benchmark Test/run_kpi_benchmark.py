"""Executes the KPI Threshold System (fastapi_backend/app/kpi_thresholds.json)
against the semantic model over the Power BI REST executeQueries API and
reports status.

Auth reuses pbi_agent.py's headless MSAL flow against the same repo-root
.pbi_token_cache.json -- silent after the first login, no pbi-cli/Desktop
session required. Target dataset comes from powerbi-summary-agent's
config.json (tenant_id/workspace_id/dataset_id), same as pbi_agent.py.

Each KPI runs as its own isolated EVALUATE query -- a single ROW() packing
several measures fails as a whole if any one throws (documented gotcha in
this repo's CLAUDE.md), so isolating them means one broken measure never
blanks out the rest of the report.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
import pbi_agent  # noqa: E402  (repo-root module, path set above)

SPEC_PATH = REPO_ROOT / "fastapi_backend" / "app" / "kpi_thresholds.json"
RESULTS_PATH = Path(__file__).resolve().parent / "benchmark_results.json"


def load_kpi_spec() -> list[dict]:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))["kpis"]


def measure_body(dax: str) -> str:
    """Strip the "<name> =" header off a measure definition, leaving the expression."""
    return dax.split("=\n", 1)[1]


def run_dax_scalar(expression: str) -> float:
    query = f'EVALUATE\nROW(\n    "Result", {expression}\n)'
    response = pbi_agent.execute_dax(query)
    result = response["results"][0]
    if "error" in result:
        # executeQueries can return HTTP 200 with a per-query error embedded
        # in the body -- trusting response.ok alone would fabricate a
        # zero-row success here, so this is checked explicitly.
        raise RuntimeError(json.dumps(result["error"]))
    rows = result["tables"][0]["rows"]
    return float(rows[0]["[Result]"])


def parse_comparison(expr: str):
    expr = expr.strip()
    for op in (">=", "<=", ">", "<"):
        if expr.startswith(op):
            return op, float(expr[len(op):].strip())
    return None  # range strings like "a to b" are display-only; red/green alone decide status


def status_for(value: float, thresholds: dict) -> str:
    for band in ("red", "green"):
        parsed = parse_comparison(thresholds[band])
        if parsed is None:
            continue
        op, bound = parsed
        if (op == ">=" and value >= bound) or (op == "<=" and value <= bound) \
                or (op == ">" and value > bound) or (op == "<" and value < bound):
            return band.capitalize()
    return "Amber"


def run_benchmark() -> list[dict]:
    results = []
    for kpi in load_kpi_spec():
        name = kpi["name"]
        try:
            value = run_dax_scalar(measure_body(kpi["dax"]))
            status = status_for(value, kpi["thresholds"])
            results.append({"name": name, "value": value, "status": status, "error": None})
        except Exception as exc:
            results.append({"name": name, "value": None, "status": "Error", "error": str(exc)})
    return results


def print_report(results: list[dict]) -> None:
    width = max(len(r["name"]) for r in results)
    for r in results:
        if r["error"] is not None:
            print(f"{r['name']:<{width}}  ERROR: {r['error']}")
        else:
            print(f"{r['name']:<{width}}  {r['value']:+9.4f}  {r['status']}")


if __name__ == "__main__":
    results = run_benchmark()
    print_report(results)
    RESULTS_PATH.write_text(
        json.dumps({"run_at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2),
        encoding="utf-8",
    )
    print(f"\nWritten to {RESULTS_PATH}")
