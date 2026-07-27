"""Offline regression for the per-client ``ai-content/`` publisher."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import ai_content_publisher as publisher  # noqa: E402


DATASET = "b3458a38-ad83-4e9a-b2f2-39d15c6aa22c"
REPORT = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


class _Download:
    def __init__(self, item):
        self.item = item
        self.properties = SimpleNamespace(etag=item["etag"])

    def readall(self):
        return self.item["data"]


class _Blob:
    def __init__(self, service, container, name):
        self.service = service
        self.container = container
        self.name = name

    def download_blob(self):
        try:
            return _Download(self.service.data[self.container][self.name])
        except KeyError as exc:
            raise ResourceNotFoundError("missing") from exc

    def upload_blob(
        self,
        data,
        overwrite=False,
        content_settings=None,
        metadata=None,
        etag=None,
        match_condition=None,
    ):
        if self.container not in self.service.data:
            raise ResourceNotFoundError("container missing")
        current = self.service.data[self.container].get(self.name)
        if current and not overwrite:
            raise ResourceExistsError("exists")
        if overwrite and etag is not None and (not current or current["etag"] != etag):
            raise ResourceModifiedError("etag mismatch")
        raw = data.read() if hasattr(data, "read") else data
        raw = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
        self.service.version += 1
        self.service.data[self.container][self.name] = {
            "data": raw,
            "etag": f'"etag-{self.service.version}"',
            "content_type": getattr(content_settings, "content_type", None),
            "metadata": dict(metadata or {}),
            "conditional": bool(etag and match_condition),
        }


class _Container:
    def __init__(self, service, name):
        self.service = service
        self.name = name

    def get_blob_client(self, name):
        return _Blob(self.service, self.name, name)


class _Service:
    def __init__(self):
        self.data = {"cityflower": {}, "scanb": {"keep.txt": {"data": b"unchanged"}}}
        self.version = 0

    def get_container_client(self, name):
        return _Container(self, name)


class _Response:
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {
            "value": [
                {"id": REPORT, "datasetId": DATASET},
                {"id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "datasetId": "other"},
            ]
        }


def _write_outputs(root: Path, cards: list[dict]) -> None:
    api = root / "api"
    api.mkdir(parents=True, exist_ok=True)
    (api / "kpi_insights.json").write_text(json.dumps(cards), encoding="utf-8")
    (api / "report_summary.json").write_text(
        json.dumps({
            "title": "AI Summary",
            "generatedAt": "2026-07-23",
            "headline": "Fresh view",
            "metrics": [
                {"label": "Revenue change", "value": "+3.5M", "tone": "positive"},
            ],
            "sections": [
                {"heading": "What's working", "tone": "positive", "points": ["Revenue improved."]},
                {"heading": "Risks", "tone": "warning", "points": ["No material downside is visible."]},
                {"heading": "Recommended actions", "tone": "info", "points": ["Monitor the next run."]},
            ],
        }),
        encoding="utf-8",
    )
    (root / "report_summary.html").write_text(
        "<!doctype html><html><body><h1>Fresh view</h1></body></html>",
        encoding="utf-8",
    )


def _state(output: Path) -> dict:
    return {
        "workspace_id": "workspace-1",
        "dataset_id": DATASET,
        "pbi_token": "token",
        "output_folder": str(output),
        "config": {
            "ai_content_publish_enabled": True,
            "ai_content_client": "cityflower",
            "ai_content_report_ids": [],
            "ai_content_ttl_hours": 24,
            "ai_content_alert_days": 7,
            "insight_history_timezone": "Asia/Kolkata",
            "azure_blob_account": "account",
        },
    }


def _body(service: _Service, name: str):
    return json.loads(service.data["cityflower"][name]["data"].decode("utf-8"))


def main() -> int:
    service = _Service()
    now = datetime(2026, 7, 23, 5, 5, tzinfo=timezone.utc)
    initial_alerts = [
        {"id": 90, "isoDate": "2026-07-17", "metric": "within-window"},
        {"id": 91, "isoDate": "2026-07-16", "metric": "expired"},
    ]
    legacy = service.get_container_client("cityflower").get_blob_client(
        "ai-content/kpi/client/alerts.json"
    )
    legacy.upload_blob(json.dumps(initial_alerts), overwrite=False)

    with tempfile.TemporaryDirectory(prefix="ai-content-replay-") as temp:
        output = Path(temp) / "outputs"
        cards_one = [{"id": 1, "isoDate": "2026-07-23", "metric": "Revenue", "value": "+3.5M"}]
        _write_outputs(output, cards_one)
        state = _state(output)

        discovered = publisher.discover_report_ids(state, http_get=lambda *_a, **_k: _Response())
        assert discovered == [REPORT]

        first = publisher.publish(state, generated_at=now, service_client=service, report_ids=discovered)
        assert first["status"] == "ok" and first["client"] == "cityflower", first
        assert first["reportIds"] == [REPORT]
        expected = {
            "ai-content/kpi/client/insights.json",
            "ai-content/kpi/client/alerts.json",
            f"ai-content/report-summaries/client/{REPORT}.json",
            f"ai-content/report-summaries/client/{REPORT}.html",
        }
        assert expected <= set(service.data["cityflower"])

        insights = _body(service, "ai-content/kpi/client/insights.json")
        assert insights["schemaVersion"] == 1
        assert insights["client"] == "cityflower"
        assert insights["generatedFor"] == "client"
        assert insights["generatedAt"] == "2026-07-23T05:05:00Z"
        assert insights["expiresAt"] == "2026-07-24T05:05:00Z"
        assert insights["sourceDatasets"] == [DATASET]
        assert insights["payload"] == cards_one

        summary_name = f"ai-content/report-summaries/client/{REPORT}.json"
        summary = _body(service, summary_name)
        assert set(summary["payload"]) == {"title", "generatedAt", "headline", "metrics", "sections"}
        assert [section["heading"] for section in summary["payload"]["sections"]] == [
            "What's working", "Risks", "Recommended actions"
        ]

        alerts = _body(service, "ai-content/kpi/client/alerts.json")["payload"]
        assert [item["isoDate"] for item in alerts] == ["2026-07-23", "2026-07-17"]
        assert service.data["cityflower"]["ai-content/kpi/client/alerts.json"]["conditional"] is True

        html_name = f"ai-content/report-summaries/client/{REPORT}.html"
        html_item = service.data["cityflower"][html_name]
        assert html_item["data"].startswith(b"<!doctype html>")
        assert html_item["content_type"] == "text/html; charset=utf-8"
        assert html_item["metadata"]["client"] == "cityflower"
        assert html_item["metadata"]["reportid"] == REPORT

        # A second same-day run replaces that day's cards instead of duplicating
        # them, while retaining the in-window back-day.
        cards_two = [{"id": 1, "isoDate": "2026-07-23", "metric": "Quantity", "value": "-216.2K"}]
        _write_outputs(output, cards_two)
        second = publisher.publish(state, generated_at=now, service_client=service, report_ids=[REPORT])
        assert second["status"] == "ok"
        alerts = _body(service, "ai-content/kpi/client/alerts.json")["payload"]
        assert alerts == [cards_two[0], initial_alerts[0]]

        # Tenant isolation and the private-memory boundary are structural.
        assert service.data["scanb"] == {"keep.txt": {"data": b"unchanged"}}
        assert not any("memory" in name.casefold() for name in service.data["cityflower"])

        bad = _state(output)
        bad["config"]["ai_content_client"] = "../scanb"
        rejected = publisher.publish(bad, generated_at=now, service_client=service, report_ids=[REPORT])
        assert rejected["status"] == "failed"

    print("AI content publisher replay: PASS")
    print("  cityflower-only tenant boundary: yes")
    print("  JSON envelopes + raw HTML metadata: yes")
    print("  seven-day alerts + same-day replacement + ETag write: yes")
    print("  report-id discovery: yes")
    print("  memory never published: yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
