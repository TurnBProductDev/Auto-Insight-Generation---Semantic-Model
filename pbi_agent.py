import json
import os
from pathlib import Path

import msal
import requests


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Target workspace + dataset are resolved outside source code (env var, then
# the full agent's config.json) so no tenant-specific GUIDs live in the repo.
# See _workspace_id() / _dataset_id() below.

# Public client used to sign you in. This default is the well-known Azure
# PowerShell first-party client id, which needs NO app registration and works
# immediately for delegated Power BI access. For production, register your own
# Azure AD *public client* app and paste its Application (client) ID here.
CLIENT_ID = "1950a258-227b-4e31-a9cf-717495945fc2"

SCOPES = ["https://analysis.windows.net/powerbi/api/.default"]

# Refresh-token cache. First login writes it; later runs reuse it silently.
# NOTE: this file contains a refresh token -- keep it out of source control.
CACHE_FILE = Path(__file__).with_name(".pbi_token_cache.json")
AGENT_CONFIG_FILE = Path(__file__).with_name("powerbi-summary-agent") / "config" / "config.json"


def _tenant_id() -> str:
    """Resolve tenant selection outside source code.

    POWERBI_TENANT_ID takes precedence; the full agent's config.json is the
    fallback so the parent MVP and product use the same tenant setting.
    """
    tenant = os.environ.get("POWERBI_TENANT_ID")
    if not tenant and AGENT_CONFIG_FILE.exists():
        tenant = json.loads(AGENT_CONFIG_FILE.read_text(encoding="utf-8")).get("tenant_id")
    if not tenant or str(tenant).startswith("PASTE_"):
        raise RuntimeError(
            "Power BI tenant is not configured. Set POWERBI_TENANT_ID or "
            "tenant_id in powerbi-summary-agent/config/config.json."
        )
    return str(tenant)


def _agent_cfg_value(env_var: str, cfg_key: str) -> str:
    """Resolve a Power BI target id outside source code.

    The matching env var takes precedence; the full agent's config.json is the
    fallback so the parent MVP and product point at the same model.
    """
    val = os.environ.get(env_var)
    if not val and AGENT_CONFIG_FILE.exists():
        val = json.loads(AGENT_CONFIG_FILE.read_text(encoding="utf-8")).get(cfg_key)
    if not val or str(val).startswith("PASTE_"):
        raise RuntimeError(
            f"Power BI {cfg_key} is not configured. Set {env_var} or "
            f"{cfg_key} in powerbi-summary-agent/config/config.json."
        )
    return str(val)


def _workspace_id() -> str:
    return _agent_cfg_value("POWERBI_WORKSPACE_ID", "workspace_id")


def _dataset_id() -> str:
    return _agent_cfg_value("POWERBI_DATASET_ID", "dataset_id")


# ---------------------------------------------------------------------------
# Auth (no PowerShell, no popup after the first run)
# ---------------------------------------------------------------------------
def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        cache.deserialize(CACHE_FILE.read_text())
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        CACHE_FILE.write_text(cache.serialize())


def get_powerbi_token() -> str:
    cache = _load_cache()
    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{_tenant_id()}",
        token_cache=cache,
    )

    result = None
    accounts = app.get_accounts()
    if accounts:
        # Silent path: reuse the cached refresh token, no browser.
        result = app.acquire_token_silent(SCOPES, account=accounts[0])

    if not result:
        # First run (or cache expired): opens the browser once.
        result = app.acquire_token_interactive(SCOPES)

    _save_cache(cache)

    if "access_token" not in result:
        raise RuntimeError(
            f"Auth failed: {result.get('error')} - "
            f"{result.get('error_description')}"
        )

    return "Bearer " + result["access_token"]


# ---------------------------------------------------------------------------
# Power BI REST: Execute Queries
# ---------------------------------------------------------------------------
def execute_dax(dax_query: str) -> dict:
    token = get_powerbi_token()

    url = (
        f"https://api.powerbi.com/v1.0/myorg/groups/"
        f"{_workspace_id()}/datasets/{_dataset_id()}/executeQueries"
    )

    body = {
        "queries": [{"query": dax_query}],
        "serializerSettings": {"includeNulls": True},
    }

    headers = {
        "Authorization": token,
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=body)

    if not response.ok:
        raise RuntimeError(
            f"Power BI API failed.\n"
            f"Status: {response.status_code}\n"
            f"Response: {response.text}"
        )

    return response.json()


def extract_rows(powerbi_response: dict) -> list:
    try:
        return powerbi_response["results"][0]["tables"][0]["rows"]
    except (KeyError, IndexError):
        return []


def main():
    dax = 'EVALUATE ROW("Test", 1)'

    result = execute_dax(dax)
    rows = extract_rows(result)

    print("DAX result:")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
