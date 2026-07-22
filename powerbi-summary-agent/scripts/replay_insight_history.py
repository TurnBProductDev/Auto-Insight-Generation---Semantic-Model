"""Offline replay for immutable insight-history generation and upload semantics.

Run from the project directory:

    python scripts/replay_insight_history.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.azure_blob import (  # noqa: E402
    _download_immutable_history,
    _update_history_feed,
    _upload_immutable_history,
)
from src.tools.insight_history import (  # noqa: E402
    blob_name,
    build_entry,
    build_history_response,
    merge_history_response,
    write_local,
)


REPORT = """# Key Insights
This scope sentence is deliberately unbolded and must not become history.

**Revenue decline concentrated in LED TV.** Revenue was lower in the current period.

**Volume improved while revenue declined.** Mix and rate should be checked next.

# Confidence & Caveats
**Not an insight.** This belongs to another section.
"""


class _FakeContainer:
    def __init__(self):
        self.blobs = {}

    def upload_blob(self, *, name, data, overwrite, content_settings):
        from azure.core.exceptions import ResourceExistsError

        assert overwrite is False
        assert content_settings.content_type == "application/json"
        if name in self.blobs:
            raise ResourceExistsError("already exists")
        self.blobs[name] = {"data": bytes(data), "etag": "1"}

    def get_blob_client(self, name):
        return _FakeBlob(self, name)


class _FakeDownload:
    def __init__(self, data, etag):
        self._data = data
        self.properties = {"etag": etag}

    def readall(self):
        return self._data


class _FakeBlob:
    def __init__(self, container, name):
        self.container = container
        self.name = name

    def download_blob(self):
        from azure.core.exceptions import ResourceNotFoundError

        current = self.container.blobs.get(self.name)
        if current is None:
            raise ResourceNotFoundError("missing")
        return _FakeDownload(current["data"], current["etag"])

    def upload_blob(
        self,
        *,
        data,
        overwrite,
        content_settings,
        etag=None,
        match_condition=None,
    ):
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

        assert content_settings.content_type == "application/json"
        current = self.container.blobs.get(self.name)
        if not overwrite and current is not None:
            raise ResourceExistsError("already exists")
        if overwrite and (current is None or current["etag"] != etag):
            raise ResourceModifiedError("etag mismatch")
        version = int(current["etag"]) + 1 if current else 1
        self.container.blobs[self.name] = {"data": bytes(data), "etag": str(version)}


def _state(report=REPORT, output_folder="outputs_replay"):
    return {
        "dataset_id": "dataset-123",
        "output_folder": output_folder,
        "insight_report": report,
        "config": {
            "insight_history_enabled": True,
            "insight_history_timezone": "Asia/Kolkata",
            "azure_blob_prefix": "",
            "azure_blob_history_prefix": "history",
        },
    }


def main() -> int:
    when = datetime(2026, 7, 22, 7, 0, 0)
    state = _state()
    entry = build_entry(state, generated_at=when, run_id="scheduled/run 1")
    assert entry is not None
    assert entry["runId"] == "scheduled-run-1"
    assert entry["date"] == {
        "iso": "2026-07-22",
        "display": "22 July 2026",
        "timezone": "Asia/Kolkata",
    }
    assert entry["runAt"] == "2026-07-22T07:00:00+05:30"
    assert entry["status"] == "completed"
    assert entry["insightCount"] == 2
    assert entry["insights"][0] == {
        "heading": "Revenue decline concentrated in LED TV.",
        "content": "Revenue was lower in the current period.",
    }
    assert blob_name(state, entry) == (
        "history/dataset-123/2026/07/22/scheduled-run-1.json"
    )

    # Container Apps supplies one execution name to every replica retry.
    with patch.dict(
        os.environ,
        {
            "INSIGHT_HISTORY_RUN_ID": "",
            "CONTAINER_APP_JOB_EXECUTION_NAME": "daily-job-abc123",
        },
    ):
        azure_entry = build_entry(state, generated_at=when)
    assert azure_entry["runId"] == "daily-job-abc123"

    # No graph-owned report means a save_outputs stub must not enter history.
    assert build_entry(_state(report=""), generated_at=when) is None

    empty = build_entry(
        _state(report="# Key Insights\n\nNo unseen insights were found.\n"),
        generated_at=when,
        run_id="empty",
    )
    assert empty is not None
    assert empty["status"] == "no_new_insights"
    assert empty["insights"] == []

    # Local audit file is byte-for-byte the same JSON object.
    with tempfile.TemporaryDirectory() as tmp:
        local_state = _state(output_folder=tmp)
        path = write_local(local_state, entry)
        assert json.loads(path.read_text(encoding="utf-8")) == entry
        local_feed = json.loads(
            (path.parent / "insight_history.json").read_text(encoding="utf-8")
        )
        assert local_feed == {
            "timezone": "Asia/Kolkata",
            "history": [{
                "date": "2026-07-22",
                "runs": [{
                    "time": "07:00:00",
                    "status": "completed",
                    "insights": entry["insights"],
                }],
            }],
        }

    # The same run id is idempotent and can never replace its first payload.
    fake = _FakeContainer()
    name = blob_name(state, entry)
    assert _upload_immutable_history(fake, name, entry) == "created"
    original = fake.blobs[name]["data"]
    changed_entry = {
        **entry,
        "insights": [{"heading": "changed", "content": "changed"}],
    }
    assert _upload_immutable_history(fake, name, changed_entry) == "exists"
    assert fake.blobs[name]["data"] == original
    assert _download_immutable_history(fake, name) == entry

    # The read-side projection groups dates and runs newest-first without
    # changing any immutable entry.
    later_same_day = build_entry(
        state, generated_at=datetime(2026, 7, 22, 12, 0), run_id="later"
    )
    tomorrow = build_entry(
        state, generated_at=datetime(2026, 7, 23, 7, 0), run_id="tomorrow"
    )
    feed = build_history_response([entry, tomorrow, later_same_day])
    assert feed["timezone"] == "Asia/Kolkata"
    assert [d["date"] for d in feed["history"]] == ["2026-07-23", "2026-07-22"]
    assert [r["time"] for r in feed["history"][1]["runs"]] == ["12:00:00", "07:00:00"]
    assert set(feed["history"][1]["runs"][0]) == {"time", "status", "insights"}

    duplicate_feed, changed = merge_history_response(feed, entry)
    assert changed is False
    assert duplicate_feed == feed

    # The API-facing single blob is created, then conditionally updated by ETag.
    feed_container = _FakeContainer()
    feed_status, first_feed = _update_history_feed(
        feed_container, "insight_history.json", entry
    )
    assert feed_status == "updated"
    feed_status, same_feed = _update_history_feed(
        feed_container, "insight_history.json", entry
    )
    assert feed_status == "unchanged"
    assert same_feed == first_feed
    feed_status, final_feed = _update_history_feed(
        feed_container, "insight_history.json", tomorrow
    )
    assert feed_status == "updated"
    assert final_feed["history"][0]["date"] == "2026-07-23"

    print("Insight history replay: PASS")
    print(f"  blob: {name}")
    print(f"  insights: {entry['insightCount']}")
    print("  duplicate upload: preserved original")
    print("  insight_history.json: ETag-safe and newest date/run first")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
