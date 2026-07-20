"""Best-effort upload of the API payloads to Azure Blob Storage.

Runs after `write_api_payloads` so a single `python -m src.main` also refreshes the
JSON contract files in a blob container (default `insightgen`). Mirrors the
API-payload step's philosophy: **never fails the run** - any auth/network/SDK
problem is reported and swallowed. Disable with `"azure_blob_upload": false`.

Auth resolution order (first available wins):
  1. AZURE_STORAGE_CONNECTION_STRING   (env; the headless default - paste it in .env)
  2. AZURE_STORAGE_KEY                  (env; account key + configured account name)
  3. DefaultAzureCredential            (AAD - your `az login` or a managed identity;
                                        needs the 'Storage Blob Data Contributor' role)
"""

import os
from pathlib import Path

# .../powerbi-summary-agent/src/tools/azure_blob.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _service_client(account: str):
    """Build a BlobServiceClient from the first available credential."""
    from azure.storage.blob import BlobServiceClient

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn:
        return BlobServiceClient.from_connection_string(conn), "connection_string"
    url = f"https://{account}.blob.core.windows.net"
    key = os.environ.get("AZURE_STORAGE_KEY")
    if key:
        return BlobServiceClient(url, credential=key), "account_key"
    from azure.identity import DefaultAzureCredential
    return BlobServiceClient(url, credential=DefaultAzureCredential()), "aad"


def upload_api_payloads(final: dict) -> None:
    cfg = final.get("config", {})
    if not cfg.get("azure_blob_upload", False):
        return

    account = cfg.get("azure_blob_account")
    container = cfg.get("azure_blob_container", "insightgen")
    prefix = str(cfg.get("azure_blob_prefix", "") or "").strip("/")
    if not account:
        print("Azure upload skipped: 'azure_blob_account' not set in config.json.")
        return

    api_dir = PROJECT_ROOT / final.get("output_folder", "outputs") / "api"
    files = sorted(api_dir.glob("*.json"))
    if not files:
        print("Azure upload skipped: no outputs/api/*.json to push.")
        return

    try:
        from azure.storage.blob import ContentSettings

        svc, auth = _service_client(account)
        container_client = svc.get_container_client(container)
        try:
            container_client.create_container()  # no-op if it already exists
        except Exception:  # noqa: BLE001 - ResourceExistsError / no create perm; upload still tries
            pass

        pushed = []
        for f in files:
            blob_name = f"{prefix}/{f.name}" if prefix else f.name
            with open(f, "rb") as fh:
                container_client.upload_blob(
                    name=blob_name, data=fh, overwrite=True,
                    content_settings=ContentSettings(content_type="application/json"),
                )
            pushed.append(blob_name)
        loc = f"{account}/{container}" + (f"/{prefix}" if prefix else "")
        print(f"Azure upload: pushed {len(pushed)} file(s) to {loc} "
              f"[{', '.join(pushed)}] (auth={auth}).")
    except Exception as e:  # noqa: BLE001 - best-effort, must never fail the main run
        print(f"Azure upload skipped ({type(e).__name__}: {e}). "
              f"Set AZURE_STORAGE_CONNECTION_STRING in .env or grant the "
              f"'Storage Blob Data Contributor' role for AAD upload.")
