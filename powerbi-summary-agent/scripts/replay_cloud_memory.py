"""Offline replay for Azure Blob-backed insight-memory lifecycle."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import azure_blob, insight_memory  # noqa: E402


class _Downloader:
    def __init__(self, data: bytes, etag: str):
        self._data = data
        self.properties = SimpleNamespace(etag=etag)

    def readall(self):
        return self._data


class _Blob:
    def __init__(self, service, container: str, name: str):
        self.service = service
        self.container = container
        self.name = name

    def download_blob(self):
        try:
            data, etag = self.service.data[self.container][self.name]
        except KeyError as exc:
            raise ResourceNotFoundError("missing") from exc
        return _Downloader(data, etag)

    def upload_blob(self, data, overwrite=False, etag=None, **_kwargs):
        if self.container not in self.service.data:
            raise ResourceNotFoundError("container missing")
        existing = self.service.data[self.container].get(self.name)
        if existing and not overwrite:
            raise ResourceExistsError("exists")
        if etag is not None and (not existing or existing[1] != etag):
            raise ResourceModifiedError("etag changed")
        if hasattr(data, "read"):
            data = data.read()
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        self.service.version += 1
        self.service.data[self.container][self.name] = (
            raw,
            f'"etag-{self.service.version}"',
        )


class _Container:
    def __init__(self, service, name: str):
        self.service = service
        self.name = name

    def create_container(self):
        if self.name in self.service.data:
            raise ResourceExistsError("exists")
        self.service.data[self.name] = {}

    def get_blob_client(self, name: str):
        return _Blob(self.service, self.name, name)

    def upload_blob(self, name: str, data, **kwargs):
        return self.get_blob_client(name).upload_blob(data, **kwargs)


class _Service:
    def __init__(self):
        self.data = {}
        self.version = 0

    def get_container_client(self, name: str):
        return _Container(self, name)

    def get_blob_client(self, container: str, blob: str):
        return _Blob(self, container, blob)


def _state(root: Path, dataset: str = "dataset-123") -> dict:
    return {
        "dataset_id": dataset,
        "insight_memory_enabled": True,
        "insight_memory_root": str(root),
        "config": {
            "insight_memory_storage": "azure_blob",
            "azure_blob_account": "account",
            "azure_blob_memory_container": "insightstate",
            "azure_blob_memory_prefix": "",
        },
    }


def main() -> int:
    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
        azure_blob, "_service_client", return_value=(service, "fake")
    ):
        state = _state(Path(tmp) / "runtime")
        initialized = azure_blob.initialize_insight_memory(state)
        assert initialized["status"] == "created" and initialized["empty"] is True

        hydrated = azure_blob.hydrate_insight_memory(state)
        assert hydrated["status"] == "ok" and hydrated["etag"]
        memory, status = insight_memory.load_store(state)
        assert status == "ok" and memory["records"] == {}

        memory["records"]["story-1"] = {"last_reported": "2026-07-22"}
        insight_memory._atomic_write(insight_memory.store_path(state), memory)
        published = azure_blob.publish_insight_memory(state, hydrated)
        assert published["status"] == "ok"

        second = azure_blob.hydrate_insight_memory(state)
        blob = service.get_blob_client("insightstate", "dataset-123/memory.json")
        current = blob.download_blob().readall()
        blob.upload_blob(current, overwrite=True)
        conflict = azure_blob.publish_insight_memory(state, second)
        assert conflict["status"] == "conflict"

        missing_state = _state(Path(tmp) / "runtime", dataset="new-dataset")
        stale = insight_memory.store_path(missing_state)
        stale.write_text(json.dumps({"records": {"old": {}}}), encoding="utf-8")
        missing = azure_blob.hydrate_insight_memory(missing_state)
        assert missing["status"] == "missing" and not stale.exists()

        existing = azure_blob.initialize_insight_memory(state)
        assert existing["status"] == "exists" and existing["empty"] is False

    print("Cloud insight memory replay: PASS")
    print("  empty first store: yes")
    print("  local staging isolation: yes")
    print("  ETag conflict protection: yes")
    print("  existing non-empty store: never overwritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
