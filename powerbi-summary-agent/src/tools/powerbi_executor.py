"""Power BI DAX execution tool.

Two execution modes (config.execution_mode):
  * "python"     -> headless MSAL auth + REST executeQueries (default, proven working)
  * "powershell" -> hand DAX to scripts/execute_dax.ps1 and read back its JSON

Auth reuses the MSAL refresh-token cache created by the parent project's
pbi_agent.py, so no extra browser login is needed on first run.
"""

import base64
import json
import os
import subprocess
import time
from pathlib import Path

import msal
import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# .../AI- 2.0/powerbi-summary-agent/src/tools/powerbi_executor.py
#            parents[2] = powerbi-summary-agent   parents[3] = AI- 2.0
PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[3]
PS_SCRIPT = PROJECT_ROOT / "scripts" / "execute_dax.ps1"

# Reuse the working token cache from the parent MVP so we don't re-login.
CACHE_FILE = REPO_ROOT / ".pbi_token_cache.json"

# ---------------------------------------------------------------------------
# Auth (headless MSAL — see parent project's get_pbi_token work)
# ---------------------------------------------------------------------------
CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"  # Azure PowerShell public client
SCOPES = ["https://analysis.windows.net/powerbi/api/.default"]
# The Fabric REST surface (getDefinition) needs its own audience. The same
# refresh token in the cache acquires it silently - no second browser login.
FABRIC_SCOPES = ["https://api.fabric.microsoft.com/.default"]
FABRIC_BASE = "https://api.fabric.microsoft.com/v1"


def _authority(tenant_id=None) -> str:
    """Build the MSAL authority from config or POWERBI_TENANT_ID.

    Tenant selection is deployment configuration, not a source-code constant.
    """
    resolved = str(tenant_id or os.environ.get("POWERBI_TENANT_ID") or "").strip()
    if not resolved or resolved.startswith("PASTE_"):
        raise RuntimeError(
            "Power BI tenant is not configured. Set tenant_id in config.json "
            "or POWERBI_TENANT_ID in the environment."
        )
    return f"https://login.microsoftonline.com/{resolved}"


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_FILE.write_text(cache.serialize())


def _resolve_auth_mode() -> str:
    """Pick the auth backend: "interactive" (local browser + refresh-token cache)
    vs a non-interactive mode ("managed_identity"/"service_principal") that mints
    tokens through DefaultAzureCredential.

    POWERBI_AUTH_MODE (env; main.py also surfaces config.json's powerbi_auth_mode
    into the env) wins; "auto" resolves to managed_identity inside Azure and
    interactive locally. The interactive branch below is the ONLY code path that
    reads or writes CACHE_FILE, so a non-interactive run never touches
    .pbi_token_cache.json - that is the "no token cache in Azure" guarantee.
    """
    from . import azure_identity

    return azure_identity.auth_mode(
        "POWERBI_AUTH_MODE", None, local_default="interactive"
    )


def get_powerbi_token(tenant_id=None) -> str:
    if _resolve_auth_mode() != "interactive":
        # Managed identity / service principal - no browser, no cache file.
        from . import azure_identity

        return azure_identity.access_token(SCOPES[0])

    cache = _load_cache()
    app = msal.PublicClientApplication(
        CLIENT_ID, authority=_authority(tenant_id), token_cache=cache)

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result:
        result = app.acquire_token_interactive(SCOPES)

    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(
            f"Auth failed: {result.get('error')} - {result.get('error_description')}"
        )
    return result["access_token"]


def get_fabric_token(allow_interactive: bool = False, tenant_id=None):
    """Acquire a token for the Fabric REST API from the SAME cache.

    Silent-only by default: metadata_reader calls get_powerbi_token() first, so
    an account already exists in the cache and the shared refresh token mints
    the Fabric audience silently. Returns None instead of launching a browser
    (Fabric enrichment is optional - the pipeline must never hang on it)."""
    if _resolve_auth_mode() != "interactive":
        # Same DefaultAzureCredential, second audience. Stay best-effort: return
        # None (never raise) so enrichment can't fail an automated run.
        try:
            from . import azure_identity

            return azure_identity.access_token(FABRIC_SCOPES[0])
        except Exception:  # noqa: BLE001 - optional enrichment, degrade silently
            return None

    cache = _load_cache()
    app = msal.PublicClientApplication(
        CLIENT_ID, authority=_authority(tenant_id), token_cache=cache)

    result = None
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(FABRIC_SCOPES, account=accounts[0])
    if not result and allow_interactive:
        result = app.acquire_token_interactive(FABRIC_SCOPES)
    _save_cache(cache)

    return result.get("access_token") if result else None


# ---------------------------------------------------------------------------
# Fabric getDefinition — measure formulas that executeQueries redacts
# ---------------------------------------------------------------------------
def _join_tmsl_text(value) -> str:
    """TMSL stores expression / description as a string OR a list of lines."""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value or "")


def _await_fabric_operation(op_id: str, headers: dict, deadline: float):
    """Poll the Fabric long-running-operation until it resolves, then fetch
    the result body. Returns the parsed result dict or None."""
    status_url = f"{FABRIC_BASE}/operations/{op_id}"
    result_url = f"{FABRIC_BASE}/operations/{op_id}/result"
    while time.time() < deadline:
        try:
            r = requests.get(status_url, headers=headers, timeout=30)
        except requests.RequestException:
            return None
        if not r.ok:
            return None
        body = r.json()
        status = (body.get("status") or "").lower()
        if status == "succeeded":
            try:
                rr = requests.get(result_url, headers=headers, timeout=60)
            except requests.RequestException:
                return None
            return rr.json() if rr.ok else None
        if status in ("failed", "undetermined", "cancelled"):
            return None
        time.sleep(min(float(r.headers.get("Retry-After", 2) or 2), 8))
    return None


def _measures_from_definition(definition: dict) -> dict:
    """Decode the base64 model.bim part and pull ONLY sanitized measure fields.

    The raw model.bim also carries connection strings, Power Query (M), and RLS
    roles - none of that is extracted or returned here."""
    parts = (definition or {}).get("parts", []) or []
    model_part = next(
        (p for p in parts if str(p.get("path", "")).lower().endswith("model.bim")),
        None,
    )
    if not model_part or not model_part.get("payload"):
        return {}
    try:
        model_bim = json.loads(base64.b64decode(model_part["payload"]).decode("utf-8"))
    except (ValueError, TypeError):
        return {}

    out = {}
    for table in model_bim.get("model", {}).get("tables", []):
        tname = table.get("name", "")
        for m in table.get("measures", []) or []:
            name = m.get("name")
            if not name:
                continue
            out[name] = {
                "table": tname,
                "expression": _join_tmsl_text(m.get("expression", "")),
                "format_string": m.get("formatString", ""),
                "description": _join_tmsl_text(m.get("description", "")),
                "display_folder": m.get("displayFolder", ""),
                "is_hidden": bool(m.get("isHidden", False)),
            }
    return out


def fetch_measure_definitions_tmsl(workspace_id, dataset_id, token=None,
                                   timeout=120, tenant_id=None):
    """Return {measure_name: {expression, format_string, ...}} via the Fabric
    getDefinition (TMSL) endpoint, or ({}, reason) on any failure.

    executeQueries redacts measure Expression at this permission level; this
    reads the full model.bim (measures only, sanitized) instead. Never raises -
    the caller falls back to blank INFO.VIEW expressions on ({}, reason)."""
    if token is None:
        token = get_fabric_token(tenant_id=tenant_id)
    if not token:
        return {}, "no Fabric token (silent acquisition failed)"

    url = (f"{FABRIC_BASE}/workspaces/{workspace_id}"
           f"/semanticModels/{dataset_id}/getDefinition?format=TMSL")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return {}, f"request failed: {exc}"

    deadline = time.time() + timeout
    if resp.status_code == 202:  # long-running operation
        op_id = resp.headers.get("x-ms-operation-id")
        if not op_id:
            loc = resp.headers.get("Location", "")
            op_id = loc.rstrip("/").split("/")[-1] if loc else None
        if not op_id:
            return {}, "202 without an operation id"
        body = _await_fabric_operation(op_id, headers, deadline)
        if body is None:
            return {}, "operation did not succeed in time"
        definition = body.get("definition") or body
    elif resp.ok:
        definition = resp.json().get("definition")
    else:
        return {}, f"status {resp.status_code}: {resp.text[:300]}"

    measures = _measures_from_definition(definition)
    if not measures:
        return {}, "no measures decoded from model.bim"
    return measures, None


# ---------------------------------------------------------------------------
# Single-query REST call
# ---------------------------------------------------------------------------
def run_dax(workspace_id: str, dataset_id: str, dax_query: str, token: str = None):
    """Execute one DAX query. Returns (ok: bool, payload).

    ok=True  -> payload is the raw Power BI executeQueries JSON
    ok=False -> payload is an error string
    """
    if token is None:
        token = get_powerbi_token()

    url = (
        f"https://api.powerbi.com/v1.0/myorg/groups/"
        f"{workspace_id}/datasets/{dataset_id}/executeQueries"
    )
    body = {
        "queries": [{"query": dax_query}],
        "serializerSettings": {"includeNulls": True},
    }
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=120)
    except requests.RequestException as exc:
        return False, f"HTTP request failed: {exc}"

    if resp.ok:
        return True, resp.json()
    return False, f"Status {resp.status_code}: {resp.text}"


def extract_rows(pbi_response: dict) -> list:
    try:
        return pbi_response["results"][0]["tables"][0]["rows"]
    except (KeyError, IndexError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Batch execution used by Node 7
# ---------------------------------------------------------------------------
def execute_python(workspace_id, dataset_id, validated_queries, token=None):
    """Run every validated query one-by-one via the REST API.

    Pass `token` when calling from concurrent graph branches: get_powerbi_token()
    does an unlocked read-modify-write of the cache file, which is only safe
    serially. Node 2 fetches one token into state["pbi_token"] for both branches.
    """
    if token is None:
        token = get_powerbi_token()
    results = {}
    for q in validated_queries:
        name = q["name"]
        ok, payload = run_dax(workspace_id, dataset_id, q["dax"], token=token)
        query_error = None
        if ok:
            try:
                query_error = payload["results"][0].get("error")
            except (KeyError, IndexError, TypeError):
                query_error = None
        if ok and not query_error:
            results[name] = {
                "status": "success",
                "purpose": q.get("purpose", ""),
                "query": q["dax"],
                "result": payload,
            }
        elif ok:
            results[name] = {
                "status": "failed",
                "purpose": q.get("purpose", ""),
                "query": q["dax"],
                "error": query_error.get("message", str(query_error)),
            }
        else:
            results[name] = {
                "status": "failed",
                "purpose": q.get("purpose", ""),
                "query": q["dax"],
                "error": payload,
            }
    return results


def execute_powershell(state, validated_queries, write_json, output_path):
    """Delegate to execute_dax.ps1. Expects it to write raw_pbi_results.json."""
    # queries + config are already on disk (validated_dax_queries.json / config.json);
    # ensure config values the script needs are available in outputs too.
    write_json(state, "_ps_exec_config.json", {
        "workspace_id": state["workspace_id"],
        "dataset_id": state["dataset_id"],
    })
    cmd = [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", str(PS_SCRIPT),
        "-OutputFolder", str(output_path(state, ".").parent),
    ]
    subprocess.run(cmd, check=True)
    from .file_io import read_json
    return read_json(output_path(state, "raw_pbi_results.json"))
