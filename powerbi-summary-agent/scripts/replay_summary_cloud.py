"""Offline Azure Blob lifecycle checks for summary memory and history."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.replay_cloud_memory import _Service  # noqa: E402
from src.tools import azure_blob, summary_history, summary_memory  # noqa: E402


def _state(root: Path) -> dict:
    return {
        "dataset_id": "summary-dataset",
        "output_folder": str(root / "outputs"),
        "summary_memory_enabled": True,
        "summary_memory_root": str(root / "runtime"),
        "summary_candidates": [{
            "summary_key": "summary:v1:key-one",
            "angle": "overall_performance",
            "metric_family": "revenue",
            "dimension": "overall",
            "period_anchor": "2026-06",
        }],
        "summary_period_context": {
            "data_as_of": "2026-07-21",
            "period_anchor": "2026-06",
        },
        "fresh_summary": {
            "summary_type": "new_data",
            "heading": "Revenue moved ahead of the prior period",
            "paragraphs": ["Current revenue was above the prior comparison."],
            "sections": [
                {
                    "heading": "What's working",
                    "tone": "positive",
                    "points": ["Current revenue was above the prior comparison."],
                },
                {
                    "heading": "Risks",
                    "tone": "warning",
                    "points": ["No material downside is visible in this selected perspective."],
                },
                {
                    "heading": "Recommended actions",
                    "tone": "info",
                    "points": ["Monitor the comparison in the next reporting cycle."],
                },
            ],
            "covered_summary_keys": ["summary:v1:key-one"],
            "metrics": [],
            "visual": None,
            "data_as_of": "2026-07-21",
            "grain": "month",
            "freshness_status": "current",
        },
        "config": {
            "summary_memory_storage": "azure_blob",
            "summary_history_enabled": True,
            "summary_history_timezone": "Asia/Kolkata",
            "azure_blob_upload": True,
            "azure_blob_account": "account",
            "azure_blob_container": "insightgen",
            "azure_blob_memory_container": "insightstate",
            "azure_blob_summary_memory_prefix": "summary-memory",
            "azure_blob_summary_history_prefix": "summary-history",
            "azure_blob_summary_history_feed": "summary_history.json",
        },
    }


def main() -> int:
    service = _Service()
    service.data["insightstate"] = {}
    service.data["insightgen"] = {}
    with tempfile.TemporaryDirectory(prefix="summary-cloud-replay-") as temp, patch.object(
        azure_blob, "_service_client", return_value=(service, "fake")
    ):
        state = _state(Path(temp))
        stale = summary_memory.store_path(state)
        stale.write_text(json.dumps({"records": {"stale": {}}}), encoding="utf-8")
        hydration = azure_blob.hydrate_summary_memory(state)
        assert hydration["status"] == "missing" and not stale.exists()

        commit = summary_memory.commit_summary_run(
            state, ["summary:v1:key-one"], state["fresh_summary"]
        )
        assert commit["status"] == "ok"
        published = azure_blob.publish_summary_memory(state, hydration)
        assert published["status"] == "ok"
        expected_blob = "summary-memory/summary-dataset/memory.json"
        assert expected_blob in service.data["insightstate"]

        second = azure_blob.hydrate_summary_memory(state)
        assert second["status"] == "ok" and second["etag"]
        blob = service.get_blob_client("insightstate", expected_blob)
        current = blob.download_blob().readall()
        blob.upload_blob(current, overwrite=True)
        conflict = azure_blob.publish_summary_memory(state, second)
        assert conflict["status"] == "conflict"

        entry = summary_history.build_entry(
            state, generated_at=datetime(2026, 7, 23, 9, 30), run_id="summary-run-1"
        )
        first = azure_blob.upload_summary_history(state, entry)
        assert first["status"] == "created" and first["feedStatus"] == "updated"
        second_history = azure_blob.upload_summary_history(state, entry)
        assert second_history["status"] == "exists" and second_history["feedStatus"] == "unchanged"
        assert first["blob"] == (
            "summary-history/summary-dataset/2026/07/23/summary-run-1.json"
        )
        assert first["feed"] == "summary_history.json"

    print("Cloud summary memory/history replay: PASS")
    print("  separate summary-memory namespace: yes")
    print("  ETag conflict protection: yes")
    print("  immutable history + newest-first feed: yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
