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

import json
import os
import re
from pathlib import Path
from uuid import uuid4

# .../powerbi-summary-agent/src/tools/azure_blob.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]


#: A plan-cache file is named for its own cache key - 32 hex characters from
#: `plan_cache.cache_key`. Matching that shape on both legs of the sync keeps
#: anything else that lands in the folder or the prefix out of the cache, and
#: means a downloaded blob can only ever be reunited with the key the planning
#: nodes will compute.
_PLAN_CACHE_LEAF = re.compile(r"^[0-9a-f]{32}\.json$")


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
    from .azure_identity import default_credential
    return BlobServiceClient(url, credential=default_credential()), "aad"


def upload_api_payloads(final: dict, filenames: list[str] | None = None) -> dict:
    cfg = final.get("config", {})
    if not cfg.get("azure_blob_upload", False):
        return {"status": "skipped", "reason": "azure_blob_upload_disabled"}

    account = cfg.get("azure_blob_account")
    container = cfg.get("azure_blob_container", "insightgen")
    prefix = str(cfg.get("azure_blob_prefix", "") or "").strip("/")
    if not account:
        print("Azure upload skipped: 'azure_blob_account' not set in config.json.")
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    api_dir = PROJECT_ROOT / final.get("output_folder", "outputs") / "api"
    if filenames is None:
        files = sorted(api_dir.glob("*.json"))
    else:
        files = [api_dir / name for name in filenames if (api_dir / name).is_file()]
    if not files:
        print("Azure upload skipped: no outputs/api/*.json to push.")
        return {"status": "failed", "reason": "api_payloads_missing"}

    try:
        from azure.storage.blob import ContentSettings

        svc, auth = _service_client(account)
        container_client = svc.get_container_client(container)
        try:
            container_client.create_container()  # no-op if it already exists
        except Exception:  # noqa: BLE001 - ResourceExistsError / no create perm; upload still tries
            pass

        pushed = []
        receipts = {}
        for f in files:
            blob_name = f"{prefix}/{f.name}" if prefix else f.name
            try:
                with open(f, "rb") as fh:
                    container_client.upload_blob(
                        name=blob_name, data=fh, overwrite=True,
                        content_settings=ContentSettings(content_type="application/json"),
                    )
                pushed.append(blob_name)
                receipts[f.name] = {"status": "ok", "blob": blob_name}
            except Exception as exc:  # noqa: BLE001 - preserve per-file delivery evidence
                receipts[f.name] = {"status": "failed", "blob": blob_name, "error": str(exc)}
        loc = f"{account}/{container}" + (f"/{prefix}" if prefix else "")
        print(f"Azure upload: pushed {len(pushed)} file(s) to {loc} "
              f"[{', '.join(pushed)}] (auth={auth}).")
        status = "ok" if receipts and all(item["status"] == "ok" for item in receipts.values()) else "failed"
        return {"status": status, "files": pushed, "receipts": receipts, "auth": auth}
    except Exception as e:  # noqa: BLE001 - best-effort, must never fail the main run
        print(f"Azure upload skipped ({type(e).__name__}: {e}). "
              f"Set AZURE_STORAGE_CONNECTION_STRING in .env or grant the "
              f"'Storage Blob Data Contributor' role for AAD upload.")
        return {"status": "failed", "error": str(e)}


def cloud_memory_enabled(state: dict) -> bool:
    cfg = state.get("config", {}) or {}
    mode = str(cfg.get("insight_memory_storage", "local") or "local").lower()
    return bool(state.get("insight_memory_enabled", True)) and mode == "azure_blob"


def cloud_summary_memory_enabled(state: dict) -> bool:
    cfg = state.get("config", {}) or {}
    mode = str(
        cfg.get("summary_memory_storage")
        or cfg.get("insight_memory_storage")
        or "local"
    ).lower()
    return bool(state.get("summary_memory_enabled", True)) and mode == "azure_blob"


def _memory_location(state: dict) -> tuple[str, str, str]:
    cfg = state.get("config", {}) or {}
    account = str(cfg.get("azure_blob_account") or "").strip()
    container = str(
        cfg.get("azure_blob_memory_container") or "insightstate"
    ).strip()
    prefix = str(cfg.get("azure_blob_memory_prefix", "") or "").strip("/")
    dataset = str(state.get("dataset_id") or "unknown_dataset")
    safe_dataset = "".join(
        ch if ch.isalnum() or ch in "_.-" else "_" for ch in dataset
    )
    name = "/".join(part for part in (prefix, safe_dataset, "memory.json") if part)
    return account, container, name


def _summary_memory_location(state: dict) -> tuple[str, str, str]:
    cfg = state.get("config", {}) or {}
    account = str(cfg.get("azure_blob_account") or "").strip()
    container = str(cfg.get("azure_blob_memory_container") or "insightstate").strip()
    prefix = str(cfg.get("azure_blob_summary_memory_prefix") or "summary-memory").strip("/")
    dataset = str(state.get("dataset_id") or "unknown_dataset")
    safe_dataset = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in dataset)
    name = "/".join(part for part in (prefix, safe_dataset, "memory.json") if part)
    return account, container, name


def _atomic_bytes(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp.write_bytes(raw)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def hydrate_insight_memory(state: dict) -> dict:
    """Hydrate the isolated runtime memory before the novelty filter runs.

    A missing cloud blob is intentionally treated as a brand-new memory. Any
    stale staging files are removed, and the existing local ``insight_memory``
    directory is never read or migrated.
    """
    if not cloud_memory_enabled(state):
        return {"status": "skipped", "reason": "local_memory_storage"}

    account, container, name = _memory_location(state)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.core.exceptions import ResourceNotFoundError
    from .insight_memory import markdown_path, store_path

    path = store_path(state)
    try:
        svc, auth = _service_client(account)
        blob = svc.get_blob_client(container=container, blob=name)
        downloader = blob.download_blob()
        raw = downloader.readall()
        props = downloader.properties
        etag = getattr(props, "etag", None)
        if etag is None and isinstance(props, dict):
            etag = props.get("etag")
        if not etag:
            raise RuntimeError("cloud memory download did not expose an ETag")
        _atomic_bytes(path, raw)
        print(f"Cloud insight memory: hydrated {account}/{container}/{name} (auth={auth}).")
        return {"status": "ok", "blob": name, "etag": etag, "auth": auth}
    except ResourceNotFoundError:
        # This only touches the cloud staging directory selected in main.py.
        for stale in (path, markdown_path(state)):
            try:
                stale.unlink()
            except FileNotFoundError:
                pass
        print(
            f"Cloud insight memory: {account}/{container}/{name} does not exist; "
            "starting from an empty memory."
        )
        return {"status": "missing", "blob": name, "etag": None}
    except Exception as exc:  # noqa: BLE001 - main treats cloud-memory failure as fatal
        print(f"Cloud insight memory hydration failed ({type(exc).__name__}: {exc}).")
        return {"status": "failed", "blob": name, "error": str(exc)}


def hydrate_summary_memory(state: dict) -> dict:
    """Hydrate only the summary memory namespace into its isolated runtime path."""
    if not cloud_summary_memory_enabled(state):
        return {"status": "skipped", "reason": "local_memory_storage"}
    account, container, name = _summary_memory_location(state)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.core.exceptions import ResourceNotFoundError
    from .summary_memory import store_path

    path = store_path(state)
    try:
        svc, auth = _service_client(account)
        blob = svc.get_blob_client(container=container, blob=name)
        downloader = blob.download_blob()
        raw = downloader.readall()
        props = downloader.properties
        etag = getattr(props, "etag", None)
        if etag is None and isinstance(props, dict):
            etag = props.get("etag")
        if not etag:
            raise RuntimeError("cloud summary memory download did not expose an ETag")
        _atomic_bytes(path, raw)
        print(f"Cloud summary memory: hydrated {account}/{container}/{name} (auth={auth}).")
        return {"status": "ok", "blob": name, "etag": etag, "auth": auth}
    except ResourceNotFoundError:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        print(f"Cloud summary memory: {account}/{container}/{name} does not exist; starting empty.")
        return {"status": "missing", "blob": name, "etag": None}
    except Exception as exc:  # noqa: BLE001 - caller exposes the failure and refuses commit
        print(f"Cloud summary memory hydration failed ({type(exc).__name__}: {exc}).")
        return {"status": "failed", "blob": name, "error": str(exc)}


def publish_insight_memory(state: dict, hydration: dict | None = None) -> dict:
    """Publish the committed runtime memory with optimistic concurrency."""
    if not cloud_memory_enabled(state):
        return {"status": "skipped", "reason": "local_memory_storage"}
    if (state.get("insight_novelty", {}) or {}).get("memory_status") == "corrupt":
        return {"status": "failed", "reason": "memory_corrupt"}

    account, container, name = _memory_location(state)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceExistsError, ResourceModifiedError
    from azure.storage.blob import ContentSettings
    from .insight_memory import store_path

    path = store_path(state)
    if not path.exists():
        return {"status": "failed", "reason": "runtime_memory_missing"}

    etag = (hydration or {}).get("etag")
    try:
        svc, auth = _service_client(account)
        blob = svc.get_blob_client(container=container, blob=name)
        kwargs = {
            "data": path.read_bytes(),
            "content_settings": ContentSettings(content_type="application/json"),
        }
        if etag:
            blob.upload_blob(
                overwrite=True,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
                **kwargs,
            )
        else:
            blob.upload_blob(overwrite=False, **kwargs)
        print(f"Cloud insight memory: published {account}/{container}/{name} (auth={auth}).")
        return {"status": "ok", "blob": name, "auth": auth}
    except (ResourceExistsError, ResourceModifiedError) as exc:
        print("Cloud insight memory publish refused: another run changed the blob.")
        return {"status": "conflict", "blob": name, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - main treats cloud-memory failure as fatal
        print(f"Cloud insight memory publish failed ({type(exc).__name__}: {exc}).")
        return {"status": "failed", "blob": name, "error": str(exc)}


def publish_summary_memory(state: dict, hydration: dict | None = None) -> dict:
    """Publish committed summary memory with the same optimistic-concurrency rule."""
    if not cloud_summary_memory_enabled(state):
        return {"status": "skipped", "reason": "local_memory_storage"}
    if (state.get("summary_novelty") or {}).get("memory_status") == "corrupt":
        return {"status": "failed", "reason": "memory_corrupt"}
    account, container, name = _summary_memory_location(state)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceExistsError, ResourceModifiedError
    from azure.storage.blob import ContentSettings
    from .summary_memory import store_path

    path = store_path(state)
    if not path.exists():
        return {"status": "failed", "reason": "runtime_memory_missing"}
    etag = (hydration or {}).get("etag")
    try:
        svc, auth = _service_client(account)
        blob = svc.get_blob_client(container=container, blob=name)
        kwargs = {
            "data": path.read_bytes(),
            "content_settings": ContentSettings(content_type="application/json"),
        }
        if etag:
            blob.upload_blob(
                overwrite=True, etag=etag,
                match_condition=MatchConditions.IfNotModified, **kwargs,
            )
        else:
            blob.upload_blob(overwrite=False, **kwargs)
        print(f"Cloud summary memory: published {account}/{container}/{name} (auth={auth}).")
        return {"status": "ok", "blob": name, "auth": auth}
    except (ResourceExistsError, ResourceModifiedError) as exc:
        print("Cloud summary memory publish refused: another run changed the blob.")
        return {"status": "conflict", "blob": name, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - caller treats this as a failed summary delivery
        print(f"Cloud summary memory publish failed ({type(exc).__name__}: {exc}).")
        return {"status": "failed", "blob": name, "error": str(exc)}


def cloud_snapshot_memory_enabled(cfg: dict) -> bool:
    """Same switch as `insight_memory_storage`/`summary_memory_storage`, for
    the separate memory system single-snapshot reports use (Ageing, SKU
    Overview, Daily Sales) - see `snapshot_memory.py`'s module docstring.
    Takes a plain config dict, not a LangGraph `state`: these reports run
    outside the graph entirely."""
    mode = str(cfg.get("snapshot_memory_storage", "local") or "local").lower()
    return mode == "azure_blob"


def _snapshot_memory_location(cfg: dict, report_id: str, dataset_id: str) -> tuple[str, str, str]:
    from ..kernel import scoping

    account = str(cfg.get("azure_blob_account") or "").strip()
    container = str(cfg.get("azure_blob_memory_container") or "insightstate").strip()
    prefix = str(cfg.get("azure_blob_snapshot_memory_prefix") or "snapshot-memory").strip("/")
    dataset_segment = scoping.safe_segment(dataset_id, "unknown_dataset")
    report_segment = scoping.safe_segment(report_id, "unknown_report")
    name = "/".join(part for part in (prefix, dataset_segment, "reports", report_segment, "memory.json")
                    if part)
    return account, container, name


def hydrate_snapshot_memory(cfg: dict, out_dir, report_id: str, dataset_id: str) -> dict:
    """Download the cross-run memory blob into the local scratch path
    `snapshot_memory.store_path` resolves, before `filter_signals` reads it.
    A missing blob is a brand-new memory, not a failure."""
    if not cloud_snapshot_memory_enabled(cfg):
        return {"status": "skipped", "reason": "local_memory_storage"}
    account, container, name = _snapshot_memory_location(cfg, report_id, dataset_id)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.core.exceptions import ResourceNotFoundError

    from ..domains.inventory.snapshot_memory import store_path

    path = store_path(out_dir, report_id, dataset_id)
    try:
        svc, auth = _service_client(account)
        blob = svc.get_blob_client(container=container, blob=name)
        downloader = blob.download_blob()
        raw = downloader.readall()
        props = downloader.properties
        etag = getattr(props, "etag", None)
        if etag is None and isinstance(props, dict):
            etag = props.get("etag")
        if not etag:
            raise RuntimeError("cloud snapshot memory download did not expose an ETag")
        _atomic_bytes(path, raw)
        print(f"Cloud snapshot memory: hydrated {account}/{container}/{name} (auth={auth}).")
        return {"status": "ok", "blob": name, "etag": etag, "auth": auth}
    except ResourceNotFoundError:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        print(f"Cloud snapshot memory: {account}/{container}/{name} does not exist; "
             "starting from an empty memory.")
        return {"status": "missing", "blob": name, "etag": None}
    except Exception as exc:  # noqa: BLE001 - caller decides whether this is fatal
        print(f"Cloud snapshot memory hydration failed ({type(exc).__name__}: {exc}).")
        return {"status": "failed", "blob": name, "error": str(exc)}


def publish_snapshot_memory(cfg: dict, out_dir, report_id: str, dataset_id: str,
                            hydration: dict | None = None) -> dict:
    """Upload the committed local memory back to blob, with the same
    optimistic-concurrency rule as `publish_insight_memory` (refuse rather
    than clobber if the blob changed since hydration)."""
    if not cloud_snapshot_memory_enabled(cfg):
        return {"status": "skipped", "reason": "local_memory_storage"}
    account, container, name = _snapshot_memory_location(cfg, report_id, dataset_id)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceExistsError, ResourceModifiedError
    from azure.storage.blob import ContentSettings

    from ..domains.inventory.snapshot_memory import store_path

    path = store_path(out_dir, report_id, dataset_id)
    if not path.exists():
        return {"status": "failed", "reason": "runtime_memory_missing"}
    etag = (hydration or {}).get("etag")
    try:
        svc, auth = _service_client(account)
        blob = svc.get_blob_client(container=container, blob=name)
        kwargs = {"data": path.read_bytes(),
                 "content_settings": ContentSettings(content_type="application/json")}
        if etag:
            blob.upload_blob(overwrite=True, etag=etag,
                            match_condition=MatchConditions.IfNotModified, **kwargs)
        else:
            blob.upload_blob(overwrite=False, **kwargs)
        print(f"Cloud snapshot memory: published {account}/{container}/{name} (auth={auth}).")
        return {"status": "ok", "blob": name, "auth": auth}
    except (ResourceExistsError, ResourceModifiedError) as exc:
        print("Cloud snapshot memory publish refused: another run changed the blob.")
        return {"status": "conflict", "blob": name, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - best-effort, must never fail the report
        print(f"Cloud snapshot memory publish failed ({type(exc).__name__}: {exc}).")
        return {"status": "failed", "blob": name, "error": str(exc)}


def cloud_plan_cache_enabled(state: dict) -> bool:
    """Whether the reused query plan survives between container runs.

    Defaults to "auto" rather than to "local" like the memory switches, because
    a lane nobody remembers to switch on is inert on exactly the deployment
    that needs it - which is how the plan cache came to be write-only in
    production in the first place. The cache matters precisely where the run is
    a scheduled job whose filesystem is discarded, and `azure_blob_upload` is
    what marks a config as publishing from such a job.

    This cannot change any existing config's behaviour, because it is reached
    only when `plan_cache_enabled` is itself true, and that is false by default
    and set by no committed config. Turning the cache on is the deliberate act;
    once taken, keeping it is what the operator meant.
    """
    if not state.get("plan_cache_enabled"):
        return False
    cfg = state.get("config", {}) or {}
    mode = str(cfg.get("plan_cache_storage", "auto") or "auto").lower()
    if mode == "azure_blob":
        return True
    if mode == "local":
        return False
    return bool(cfg.get("azure_blob_upload") or cloud_memory_enabled(state))


def _plan_cache_location(state: dict) -> tuple[str, str, str]:
    from ..kernel import scoping

    cfg = state.get("config", {}) or {}
    account = str(cfg.get("azure_blob_account") or "").strip()
    container = str(cfg.get("azure_blob_memory_container") or "insightstate").strip()
    prefix = str(cfg.get("azure_blob_plan_cache_prefix") or "plan-cache").strip("/")
    dataset_segment = scoping.safe_segment(state.get("dataset_id"), "unknown_dataset")
    report_segment = scoping.safe_segment(state.get("report_id"), "unknown_report")
    folder = "/".join(part for part in
                      (prefix, dataset_segment, "reports", report_segment) if part)
    return account, container, folder


def hydrate_plan_cache(state: dict) -> dict:
    """Download the stored query plan before the planning nodes read it.

    Without this the plan cache is write-only in production and every scheduled
    run is a cold one: a Container Apps Job gets a fresh filesystem, so the
    three planning nodes re-derive the same plan from the same unchanged schema
    every morning at full price - which is the entire cost the cache exists to
    remove. Measured, that is the difference between a run costing USD 1.20 and
    one costing USD 0.68.

    Deliberately NOT fatal, which is where this departs from
    `hydrate_insight_memory`. Starting from an empty *memory* would re-announce
    every finding the reader has already seen, so main.py stops the pipeline
    there. Starting from an empty *cache* costs money and nothing else, so a
    failure here degrades to the cold run the pipeline does today.
    """
    if not cloud_plan_cache_enabled(state):
        return {"status": "skipped", "reason": "local_plan_cache_storage"}
    account, container, folder = _plan_cache_location(state)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from . import plan_cache

    directory = plan_cache._root(state)
    try:
        svc, auth = _service_client(account)
        client = svc.get_container_client(container)
        pulled = []
        for blob in client.list_blobs(name_starts_with=f"{folder}/"):
            leaf = str(blob.name).rsplit("/", 1)[-1]
            # The local file name IS the cache key, so only a well-formed one
            # can be reunited with the key `plan_cache.load` will compute.
            if not _PLAN_CACHE_LEAF.match(leaf):
                continue
            raw = client.get_blob_client(blob.name).download_blob().readall()
            _atomic_bytes(directory / leaf, raw)
            pulled.append(leaf)
        print(f"Cloud plan cache: hydrated {len(pulled)} plan(s) from "
              f"{account}/{container}/{folder} (auth={auth}).")
        return {"status": "ok", "folder": folder, "pulled": pulled, "auth": auth}
    except Exception as exc:  # noqa: BLE001 - a cold run is the correct fallback
        print(f"Cloud plan cache hydration failed ({type(exc).__name__}: {exc}); "
              f"this run will re-plan.")
        return {"status": "failed", "folder": folder, "error": str(exc)}


def publish_plan_cache(state: dict, hydration: dict | None = None) -> dict:
    """Upload the verified plan back, and evict what the run discarded.

    No ETag, unlike every memory lane here, and that is a judgement not an
    omission. Memory uses optimistic concurrency because a lost write silently
    re-announces findings the reader has already been shown. This is a derived
    cache: the loser of a race re-plans tomorrow, which costs money and cannot
    cost correctness. Adding a conflict path would make a cheap, harmless
    outcome look like a failure.

    Pruning is what carries the two local evictions - `record_execution`
    deleting a plan whose queries stopped working, and a schema change minting
    a new key - out to the blob, so the folder holds the live plan rather than
    every plan this model has ever had. It is skipped when hydration failed,
    because a network blip that emptied the local view must not be mistaken for
    a deliberate eviction and wipe the stored plan.
    """
    if not cloud_plan_cache_enabled(state):
        return {"status": "skipped", "reason": "local_plan_cache_storage"}
    account, container, folder = _plan_cache_location(state)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.storage.blob import ContentSettings

    from . import plan_cache

    directory = plan_cache._root(state)
    local = {p.name: p for p in directory.glob("*.json")
             if _PLAN_CACHE_LEAF.match(p.name)} if directory.exists() else {}
    hydrated_cleanly = (hydration or {}).get("status") in ("ok", None)
    try:
        svc, auth = _service_client(account)
        client = svc.get_container_client(container)
        pushed, pruned = [], []
        for leaf, path in sorted(local.items()):
            client.get_blob_client(f"{folder}/{leaf}").upload_blob(
                path.read_bytes(), overwrite=True,
                content_settings=ContentSettings(content_type="application/json"))
            pushed.append(leaf)
        if hydrated_cleanly:
            for blob in client.list_blobs(name_starts_with=f"{folder}/"):
                leaf = str(blob.name).rsplit("/", 1)[-1]
                # Only ever delete a file this cache could have written. A
                # prefix is a shared namespace, and a lane that deletes
                # whatever it does not recognise destroys someone else's data
                # the first time the two are pointed at one folder.
                if _PLAN_CACHE_LEAF.match(leaf) and leaf not in local:
                    client.delete_blob(blob.name)
                    pruned.append(leaf)
        print(f"Cloud plan cache: published {len(pushed)} plan(s), pruned "
              f"{len(pruned)} to {account}/{container}/{folder} (auth={auth}).")
        return {"status": "ok", "folder": folder, "pushed": pushed,
                "pruned": pruned, "auth": auth}
    except Exception as exc:  # noqa: BLE001 - best-effort, same as the archive
        print(f"Cloud plan cache publish failed ({type(exc).__name__}: {exc}).")
        return {"status": "failed", "folder": folder, "error": str(exc)}


def initialize_insight_memory(state: dict) -> dict:
    """Create the private container and one empty memory blob, never overwrite."""
    if not cloud_memory_enabled(state):
        return {"status": "skipped", "reason": "local_memory_storage"}

    account, container, name = _memory_location(state)
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import ContentSettings
    from .insight_memory import _empty_store

    try:
        svc, auth = _service_client(account)
        container_client = svc.get_container_client(container)
        try:
            container_client.create_container()
            container_status = "created"
        except ResourceExistsError:
            container_status = "exists"
        payload = json.dumps(
            _empty_store(), indent=2, ensure_ascii=False
        ).encode("utf-8")
        try:
            container_client.upload_blob(
                name=name,
                data=payload,
                overwrite=False,
                content_settings=ContentSettings(content_type="application/json"),
            )
            status = "created"
            empty = True
        except ResourceExistsError:
            status = "exists"
            existing = container_client.get_blob_client(name).download_blob().readall()
            try:
                empty = json.loads(existing.decode("utf-8")) == _empty_store()
            except (UnicodeDecodeError, json.JSONDecodeError):
                empty = False
        return {
            "status": status,
            "empty": empty,
            "containerStatus": container_status,
            "container": container,
            "blob": name,
            "auth": auth,
        }
    except Exception as exc:  # noqa: BLE001 - provisioning result is explicit
        return {"status": "failed", "container": container, "blob": name, "error": str(exc)}


def _upload_immutable_history(container_client, blob_name: str, entry: dict) -> str:
    """Create one history blob exactly once.

    ``overwrite=False`` is the load-bearing behavior.  A duplicate run id is an
    idempotent retry, not permission to replace the already-published record.
    """
    from azure.core.exceptions import ResourceExistsError
    from azure.storage.blob import ContentSettings

    payload = json.dumps(entry, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    try:
        container_client.upload_blob(
            name=blob_name,
            data=payload,
            overwrite=False,
            content_settings=ContentSettings(content_type="application/json"),
        )
        return "created"
    except ResourceExistsError:
        return "exists"


def _download_immutable_history(container_client, blob_name: str) -> dict:
    """Read the original run after an idempotent retry finds it already exists."""
    raw = container_client.get_blob_client(blob_name).download_blob().readall()
    entry = json.loads(raw.decode("utf-8"))
    if not isinstance(entry, dict):
        raise RuntimeError(f"immutable history blob {blob_name!r} is not a JSON object")
    return entry


def _history_feed_blob_name(final: dict) -> str:
    cfg = final.get("config", {}) or {}
    root_prefix = str(cfg.get("azure_blob_prefix", "") or "").strip("/")
    filename = str(
        cfg.get("azure_blob_history_feed", "insight_history.json")
        or "insight_history.json"
    ).strip("/")
    return "/".join(part for part in (root_prefix, filename) if part)


def _summary_history_feed_blob_name(final: dict) -> str:
    cfg = final.get("config", {}) or {}
    root_prefix = str(cfg.get("azure_blob_prefix", "") or "").strip("/")
    filename = str(
        cfg.get("azure_blob_summary_history_feed", "summary_history.json")
        or "summary_history.json"
    ).strip("/")
    return "/".join(part for part in (root_prefix, filename) if part)


def _update_history_feed(
    container_client,
    feed_name: str,
    entry: dict,
    *,
    max_attempts: int = 4,
    history_kind: str = "insight",
) -> tuple[str, dict]:
    """Atomically merge one run into the single API-facing history JSON.

    The immutable per-run blob is the recovery record. This projection uses the
    downloaded blob's ETag for an optimistic-concurrency update; if another run
    wins the race, we re-read, re-merge, and retry without losing either run.
    """
    from azure.core import MatchConditions
    from azure.core.exceptions import (
        HttpResponseError,
        ResourceExistsError,
        ResourceModifiedError,
        ResourceNotFoundError,
    )
    from azure.storage.blob import ContentSettings

    if history_kind == "summary":
        from .summary_history import merge_history_response
    else:
        from .insight_history import merge_history_response

    blob = container_client.get_blob_client(feed_name)
    for _ in range(max(1, int(max_attempts))):
        etag = None
        existing = None
        try:
            downloader = blob.download_blob()
            raw = downloader.readall()
            existing = json.loads(raw.decode("utf-8"))
            props = downloader.properties
            etag = getattr(props, "etag", None)
            if etag is None and isinstance(props, dict):
                etag = props.get("etag")
            if not etag:
                raise RuntimeError("history feed download did not expose an ETag")
        except ResourceNotFoundError:
            existing = None
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"existing history feed {feed_name!r} is corrupt; refusing to overwrite it"
            ) from exc

        merged, changed = merge_history_response(existing, entry)
        if not changed:
            return "unchanged", merged
        payload = json.dumps(
            merged, indent=2, ensure_ascii=False, default=str
        ).encode("utf-8")
        try:
            if etag:
                blob.upload_blob(
                    data=payload,
                    overwrite=True,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                    content_settings=ContentSettings(content_type="application/json"),
                )
            else:
                blob.upload_blob(
                    data=payload,
                    overwrite=False,
                    content_settings=ContentSettings(content_type="application/json"),
                )
            return "updated", merged
        except (ResourceExistsError, ResourceModifiedError):
            continue
        except HttpResponseError as exc:
            if getattr(exc, "status_code", None) in (409, 412):
                continue
            raise
    raise RuntimeError(
        f"history feed {feed_name!r} changed concurrently {max_attempts} times"
    )


def upload_insight_history(final: dict, entry: dict | None) -> dict:
    """Upload a permanent per-run insight-history JSON to the existing container.

    Returns a small status object so the caller/tests can distinguish disabled,
    created, idempotent-retry, and failed cases.  Like the existing latest-file
    publisher, failures are visible but do not make the analytical graph fatal.
    """
    cfg = final.get("config", {}) or {}
    if not entry or not cfg.get("insight_history_enabled", True):
        return {"status": "skipped", "reason": "no_history_entry"}
    if not cfg.get("azure_blob_upload", False):
        return {"status": "skipped", "reason": "azure_blob_upload_disabled"}

    account = cfg.get("azure_blob_account")
    container = cfg.get("azure_blob_container", "insightgen")
    if not account:
        print("Azure history upload skipped: 'azure_blob_account' not set in config.json.")
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from .insight_history import blob_name

    name = blob_name(final, entry)
    try:
        svc, auth = _service_client(account)
        container_client = svc.get_container_client(container)
        try:
            container_client.create_container()
        except Exception:  # noqa: BLE001 - existing container / no create permission
            pass
        status = _upload_immutable_history(container_client, name, entry)
        verb = "created" if status == "created" else "already exists; kept unchanged"
        print(f"Azure insight history: {verb} {account}/{container}/{name} (auth={auth}).")

        # On a replica retry, the newly generated report text/time might differ.
        # The already-created immutable blob is authoritative, so use its exact
        # original values when repairing/updating the public minimal feed.
        feed_entry = (
            entry if status == "created"
            else _download_immutable_history(container_client, name)
        )
        feed_name = _history_feed_blob_name(final)
        feed_status, _ = _update_history_feed(container_client, feed_name, feed_entry)
        print(
            f"Azure insight history feed: {feed_status} "
            f"{account}/{container}/{feed_name}."
        )
        return {
            "status": status,
            "blob": name,
            "feed": feed_name,
            "feedStatus": feed_status,
            "auth": auth,
        }
    except Exception as e:  # noqa: BLE001 - history is best-effort, but visible
        print(f"Azure insight history failed ({type(e).__name__}: {e}) for {name}.")
        return {"status": "failed", "blob": name, "error": str(e)}


def upload_summary_history(final: dict, entry: dict | None) -> dict:
    """Publish the independent summary run record and newest-first summary feed."""
    cfg = final.get("config", {}) or {}
    if not entry or not cfg.get("summary_history_enabled", True):
        return {"status": "skipped", "reason": "no_history_entry"}
    if not cfg.get("azure_blob_upload", False):
        return {"status": "skipped", "reason": "azure_blob_upload_disabled"}
    account = cfg.get("azure_blob_account")
    container = cfg.get("azure_blob_container", "insightgen")
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    from .summary_history import blob_name

    name = blob_name(final, entry)
    try:
        svc, auth = _service_client(account)
        container_client = svc.get_container_client(container)
        try:
            container_client.create_container()
        except Exception:  # noqa: BLE001 - existing container / no create permission
            pass
        status = _upload_immutable_history(container_client, name, entry)
        feed_entry = entry if status == "created" else _download_immutable_history(container_client, name)
        feed_name = _summary_history_feed_blob_name(final)
        feed_status, _ = _update_history_feed(
            container_client, feed_name, feed_entry, history_kind="summary"
        )
        verb = "created" if status == "created" else "already exists; kept unchanged"
        print(f"Azure summary history: {verb} {account}/{container}/{name} (auth={auth}).")
        print(f"Azure summary history feed: {feed_status} {account}/{container}/{feed_name}.")
        return {
            "status": status,
            "blob": name,
            "feed": feed_name,
            "feedStatus": feed_status,
            "auth": auth,
        }
    except Exception as exc:  # noqa: BLE001 - visible; caller prevents memory commit
        print(f"Azure summary history failed ({type(exc).__name__}: {exc}) for {name}.")
        return {"status": "failed", "blob": name, "error": str(exc)}
