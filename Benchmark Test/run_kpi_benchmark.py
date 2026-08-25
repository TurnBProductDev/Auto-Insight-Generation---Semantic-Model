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
# Appended (not prepended) so it can never shadow a repo-root module; only used
# to reach the summary agent's shared Azure-blob helper.
sys.path.append(str(REPO_ROOT / "powerbi-summary-agent"))
import pbi_agent  # noqa: E402  (repo-root module, path set above)
# Reuse the SAME evaluator the daily snapshot uses, so the benchmark scores
# identically to production and the two can never drift (they did once, when
# kpi_thresholds.json moved its bands into `labels` + numeric *_at cut points).
from fastapi_backend.app.kpi_snapshot import evaluate_status  # noqa: E402

SPEC_PATH = REPO_ROOT / "fastapi_backend" / "app" / "kpi_thresholds.json"
RESULTS_PATH = Path(__file__).resolve().parent / "benchmark_results.json"
# Blob settings + credentials come from the same files the summary agent uses.
AGENT_CONFIG_PATH = REPO_ROOT / "powerbi-summary-agent" / "config" / "config.json"
AGENT_ENV_PATH = REPO_ROOT / "powerbi-summary-agent" / ".env"
BLOB_FILENAME = "kpi_benchmark_results.json"


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


def run_benchmark() -> list[dict]:
    results = []
    for kpi in load_kpi_spec():
        name = kpi["name"]
        formula = kpi.get("formula")  # the plain-language equation from the spec
        try:
            value = run_dax_scalar(measure_body(kpi["dax"]))
            # direction (higher/lower_is_better) + green_at/amber_at/severe_at
            # cut points now live in kpi_thresholds.json; evaluate_status is the
            # single source of truth for mapping a value to a band.
            status = evaluate_status(value, kpi["direction"], kpi["thresholds"]).capitalize()
            results.append({"name": name, "formula": formula, "value": value, "status": status, "error": None})
        except Exception as exc:
            results.append({"name": name, "formula": formula, "value": None, "status": "Error", "error": str(exc)})
    return results


def upload_results(payload: dict) -> None:
    """Best-effort push of the benchmark results to Azure Blob.

    Reuses the summary agent's shared _service_client (connection string ->
    account key -> AAD) and the same azure_blob_* config it uses, so there is one
    auth path for the whole repo. Never raises: a blob problem must not fail the
    benchmark, mirroring azure_blob.upload_api_payloads.
    """
    try:
        cfg = json.loads(AGENT_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Azure upload skipped: could not read config.json ({exc}).")
        return

    if not cfg.get("azure_blob_upload", False):
        print("Azure upload skipped: azure_blob_upload is false in config.json.")
        return
    account = cfg.get("azure_blob_account")
    if not account:
        print("Azure upload skipped: 'azure_blob_account' not set in config.json.")
        return
    container = cfg.get("azure_blob_container", "insightgen")
    prefix = str(cfg.get("azure_blob_prefix", "") or "").strip("/")
    blob_name = f"{prefix}/{BLOB_FILENAME}" if prefix else BLOB_FILENAME

    # Load the agent's .env so _service_client sees AZURE_STORAGE_CONNECTION_STRING
    # (its first-priority auth); without this it falls back to AAD, which lacks the
    # data-plane 'Storage Blob Data Contributor' role and returns a 403.
    try:
        from dotenv import load_dotenv
        load_dotenv(AGENT_ENV_PATH)
    except Exception:  # noqa: BLE001 - if dotenv is missing, _service_client still tries AAD
        pass

    try:
        from src.tools.azure_blob import _service_client
        from azure.storage.blob import ContentSettings

        svc, auth = _service_client(account)
        container_client = svc.get_container_client(container)
        try:
            container_client.create_container()  # no-op if it already exists
        except Exception:  # noqa: BLE001 - exists / no create perm; upload still tries
            pass
        container_client.upload_blob(
            name=blob_name,
            data=json.dumps(payload, indent=2).encode("utf-8"),
            overwrite=True,
            content_settings=ContentSettings(content_type="application/json"),
        )
        print(f"Azure upload: pushed {account}/{container}/{blob_name} (auth={auth}).")
    except Exception as exc:  # noqa: BLE001 - best-effort, never fail the benchmark
        print(f"Azure upload skipped ({type(exc).__name__}: {exc}).")


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
    payload = {"run_at": datetime.now(timezone.utc).isoformat(), "results": results}
    RESULTS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWritten to {RESULTS_PATH}")
    upload_results(payload)
