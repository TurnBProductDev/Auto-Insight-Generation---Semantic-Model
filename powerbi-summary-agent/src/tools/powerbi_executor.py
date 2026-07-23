"""Power BI DAX execution tool.

Two execution modes (config.execution_mode):
  * "python"     -> MSAL/Azure Identity + Power BI REST (default)
  * "powershell" -> hand DAX to scripts/execute_dax.ps1 and read back its JSON

The Python path supports two Power BI query APIs (POWERBI_QUERY_API):
  * "json"  -> legacy executeQueries JSON endpoint
  * "arrow" -> executeDaxQueries endpoint, decoded back into the legacy payload
  * "auto"  -> JSON for local interactive auth; Arrow for headless Azure auth

The compatibility payload returned by both APIs is deliberate: every existing
metadata, summary, insight, history, and memory consumer can keep using
``extract_rows`` without knowing which wire format Power BI returned.

Auth reuses the MSAL refresh-token cache created by the parent project's
pbi_agent.py, so no extra browser login is needed on first run.
"""

import base64
import datetime as dt
import io
import json
import os
import subprocess
import time
from decimal import Decimal
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


def _resolve_query_api() -> str:
    """Resolve the DAX wire format without changing local default behaviour.

    ``auto`` keeps the proven JSON path for an interactive laptop run and uses
    Arrow for unattended managed-identity/service-principal runs. An explicit
    POWERBI_QUERY_API always wins and provides a quick rollback switch.
    """
    configured = str(os.environ.get("POWERBI_QUERY_API") or "auto").strip().lower()
    aliases = {
        "legacy": "json",
        "executequeries": "json",
        "executedaxqueries": "arrow",
    }
    configured = aliases.get(configured, configured)
    if configured == "auto":
        return "json" if _resolve_auth_mode() == "interactive" else "arrow"
    if configured not in {"json", "arrow"}:
        raise RuntimeError(
            "POWERBI_QUERY_API must be auto, json, or arrow; "
            f"got {configured!r}."
        )
    return configured


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
class ArrowQueryError(RuntimeError):
    """Power BI returned an Arrow error rowset inside an HTTP 200 response."""


def _parse_rls_roles(raw_value=None) -> list[str]:
    """Parse optional RLS roles from JSON-array or comma-delimited config.

    An empty value means RLS impersonation is OFF. This is the production
    default: the managed identity queries with its workspace Contributor access.
    """
    raw = os.environ.get("POWERBI_RLS_ROLES") if raw_value is None else raw_value
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        text = str(raw).strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                values = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"POWERBI_RLS_ROLES is not valid JSON: {exc}") from exc
            if not isinstance(values, list):
                raise RuntimeError("POWERBI_RLS_ROLES JSON must be an array of role names.")
        else:
            values = text.split(",")
    roles = []
    for value in values:
        role = str(value).strip()
        if role and role not in roles:
            roles.append(role)
    return roles


def _arrow_request_body(dax_query: str) -> dict:
    """Build an Arrow request, omitting RLS fields unless explicitly configured."""
    body = {
        "query": dax_query,
        "queryTimeout": 120,
        "resultSetRowCountLimit": 100_000,
        "schemaOnly": False,
    }
    effective_username = str(
        os.environ.get("POWERBI_EFFECTIVE_USERNAME") or ""
    ).strip()
    roles = _parse_rls_roles()
    if effective_username:
        body["effectiveUsername"] = effective_username
    if roles:
        body["roles"] = roles
    return body


def _json_safe_arrow_value(value):
    """Keep Arrow's useful numeric types while making rows JSON serializable."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, dict):
        return {str(k): _json_safe_arrow_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_arrow_value(v) for v in value]
    return value


def _decode_arrow_metadata(metadata) -> dict[str, str]:
    out = {}
    for key, value in (metadata or {}).items():
        k = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
        v = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        out[k] = v
    return out


def _arrow_error(metadata: dict, rows: list[dict]) -> ArrowQueryError:
    message = (
        metadata.get("FaultString")
        or metadata.get("ErrorMessage")
        or metadata.get("ErrorDescription")
    )
    if not message and rows:
        first = rows[0]
        message = (
            first.get("ErrorMessage")
            or first.get("ErrorDescription")
            or first.get("Message")
        )
    message = str(message or "Power BI returned an unspecified Arrow query error.")
    code = metadata.get("FaultCode")
    if not code and rows:
        code = rows[0].get("ErrorCode")
    return ArrowQueryError(f"{code}: {message}" if code else message)


def _decode_arrow_payload(content: bytes) -> dict:
    """Decode concatenated Arrow IPC streams into the legacy JSON row shape."""
    try:
        import pyarrow as pa
    except ImportError as exc:
        raise RuntimeError(
            "POWERBI_QUERY_API=arrow requires pyarrow; install requirements.txt."
        ) from exc

    if not content:
        raise RuntimeError("Power BI returned an empty Arrow response.")

    source = io.BytesIO(content)
    tables = []
    while source.tell() < len(content):
        start = source.tell()
        try:
            reader = pa.ipc.open_stream(source)
            table = reader.read_all()
        except Exception as exc:  # pyarrow raises several format/compression subclasses
            snippet = content[start:start + 300].decode("utf-8", errors="replace")
            raise RuntimeError(
                f"Power BI returned an invalid Arrow stream: {exc}; body={snippet!r}"
            ) from exc

        metadata = _decode_arrow_metadata(reader.schema.metadata)
        rows = [
            {str(key): _json_safe_arrow_value(value) for key, value in row.items()}
            for row in table.to_pylist()
        ]
        if str(metadata.get("IsError", "")).strip().lower() == "true":
            raise _arrow_error(metadata, rows)
        tables.append({"rows": rows})

        # Defensive progress guard for malformed streams.
        if source.tell() <= start:
            raise RuntimeError("Arrow decoder made no progress through the response.")

    if not tables:
        raise RuntimeError("Power BI returned no Arrow result sets.")
    return {"results": [{"tables": tables}]}


def _run_dax_json(workspace_id: str, dataset_id: str, dax_query: str, token: str):
    url = (
        "https://api.powerbi.com/v1.0/myorg/groups/"
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
        try:
            return True, resp.json()
        except ValueError as exc:
            return False, f"Power BI returned invalid JSON: {exc}"
    return False, f"Status {resp.status_code}: {resp.text}"


def _run_dax_arrow(workspace_id: str, dataset_id: str, dax_query: str, token: str):
    url = (
        "https://api.powerbi.com/v1.0/myorg/groups/"
        f"{workspace_id}/datasets/{dataset_id}/executeDaxQueries"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/vnd.apache.arrow.stream",
    }
    try:
        resp = requests.post(
            url,
            headers=headers,
            json=_arrow_request_body(dax_query),
            timeout=150,
        )
    except requests.RequestException as exc:
        return False, f"HTTP request failed: {exc}"
    if not resp.ok:
        return False, f"Status {resp.status_code}: {resp.text}"
    try:
        return True, _decode_arrow_payload(resp.content)
    except (ArrowQueryError, RuntimeError) as exc:
        return False, str(exc)


def run_dax(workspace_id: str, dataset_id: str, dax_query: str, token: str = None):
    """Execute one DAX query and return the stable legacy-compatible payload.

    ok=True  -> payload always has results[0].tables[*].rows, whether the wire
               response was legacy JSON or Apache Arrow.
    ok=False -> payload is a bounded error string.
    """
    if token is None:
        token = get_powerbi_token()
    if _resolve_query_api() == "arrow":
        return _run_dax_arrow(workspace_id, dataset_id, dax_query, token)
    return _run_dax_json(workspace_id, dataset_id, dax_query, token)


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
