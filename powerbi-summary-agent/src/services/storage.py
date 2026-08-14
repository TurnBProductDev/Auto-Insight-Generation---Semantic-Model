"""Where a run's files actually land, worked out from the settings.

"Where the reports are saved" is the step people get wrong, and the reason is
structural: there is not one cloud destination, there are three, and they serve
different audiences.

    1. the agent's own store      every client shares one container, separated
                                  only by a folder name
    2. your app's storage         a separate container per client - this is the
                                  one the web app reads
    3. private memory             what has already been reported; never read by
                                  an app

A form that lists sixteen ``azure_blob_*`` and ``ai_content_*`` fields in one
column cannot convey that. Showing the resolved paths can, so :func:`plan`
renders exactly what the next run will write and where.

The path rules here mirror ``azure_blob.py``, ``insight_history.py`` and
``ai_content_publisher.py``. ``scripts/replay_config_ui.py`` asserts they agree
with the real layout of the live containers, so a change in either place shows
up as a failing test rather than a misleading preview.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _join(*parts: Any) -> str:
    return "/".join(str(p).strip("/") for p in parts if str(p or "").strip("/"))


@dataclass
class Destination:
    """One place files go, in the words of whoever has to understand it."""

    id: str
    title: str
    audience: str
    purpose: str
    container: str
    enabled: bool
    #: (what it is, the blob path) pairs.
    paths: list = field(default_factory=list)
    #: Which form settings decide this destination.
    settings: list = field(default_factory=list)
    note: str = ""
    warning: str = ""

    def json(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "audience": self.audience,
            "purpose": self.purpose,
            "container": self.container,
            "enabled": self.enabled,
            "paths": [{"what": what, "path": path} for what, path in self.paths],
            "settings": self.settings,
            "note": self.note,
            "warning": self.warning,
        }


def plan(cfg: dict, *, other_clients: list | None = None) -> dict:
    """The three destinations, with the paths the next run will write."""
    account = str(cfg.get("azure_blob_account") or "").strip()
    dataset = str(cfg.get("dataset_id") or "").strip() or "{dataset-id}"

    # ---------------------------------------------------------- 1. own store
    upload = bool(cfg.get("azure_blob_upload"))
    container = str(cfg.get("azure_blob_container") or "insightgen").strip()
    prefix = str(cfg.get("azure_blob_prefix") or "").strip("/")
    history_prefix = str(cfg.get("azure_blob_history_prefix") or "history").strip("/")
    summary_history_prefix = str(
        cfg.get("azure_blob_summary_history_prefix") or "summary-history").strip("/")
    history_feed = str(cfg.get("azure_blob_history_feed") or "insight_history.json").strip("/")
    summary_feed = str(
        cfg.get("azure_blob_summary_history_feed") or "summary_history.json").strip("/")

    own = Destination(
        id="agent_store",
        title="The agent's own store",
        audience="the agent, and anything reading the history feeds",
        purpose="Every run's data files, plus a dated record of every past run.",
        container=container,
        enabled=upload,
        settings=["azure_blob_upload", "azure_blob_account", "azure_blob_container",
                  "azure_blob_prefix", "azure_blob_history_prefix", "azure_blob_history_feed",
                  "azure_blob_summary_history_prefix", "azure_blob_summary_history_feed"],
        paths=[
            ("Today's summary data", _join(prefix, "report_summary.json")),
            ("Today's insight data", _join(prefix, "kpi_insights.json")),
            ("Newest-first summary feed", _join(prefix, summary_feed)),
            ("Newest-first insight feed", _join(prefix, history_feed)),
            ("Dated summary records",
             _join(prefix, summary_history_prefix, dataset, "{yyyy}/{mm}/{dd}/{run}.json")),
            ("Dated insight records",
             _join(prefix, history_prefix, dataset, "{yyyy}/{mm}/{dd}/{run}.json")),
        ],
        note="Every client shares this container. The folder name is the ONLY thing keeping "
             "them apart - the dated records are filed under the dataset ID and cannot clash, "
             "but the four files at the top are named the same for every client.",
    )
    if upload and not prefix:
        own.warning = ("This client writes to the top level of the container, with no folder of "
                       "its own. That is correct for exactly one client and wrong for every "
                       "other one.")
    for other in other_clients or []:
        other_cfg = other.get("config") or {}
        if str(other_cfg.get("dataset_id") or "") == str(cfg.get("dataset_id") or ""):
            continue
        if (str(other_cfg.get("azure_blob_container") or "insightgen") == container
                and str(other_cfg.get("azure_blob_prefix") or "").strip("/") == prefix):
            own.warning = (f"The client {other.get('name')!r} writes to this exact place. "
                           "Whichever runs second overwrites the other's files.")

    # ------------------------------------------------------- 2. your app's store
    ai_enabled = bool(cfg.get("ai_content_publish_enabled"))
    ai_client = str(cfg.get("ai_content_client") or "").strip()
    report_ids = [str(r).strip() for r in (cfg.get("ai_content_report_ids") or []) if str(r).strip()]
    shown = report_ids[:3] or ["{report-id}"]

    app = Destination(
        id="app_store",
        title="Your app's storage",
        audience="the web app your users open",
        purpose="The finished summary and KPI tiles, in the shape the app expects.",
        container=ai_client or "(not set)",
        enabled=ai_enabled,
        settings=["ai_content_publish_enabled", "ai_content_client", "ai_content_report_ids",
                  "ai_content_ttl_hours", "ai_content_alert_days"],
        paths=(
            [("KPI tiles", "ai-content/kpi/client/insights.json"),
             ("Alerts", "ai-content/kpi/client/alerts.json")]
            + [(f"Summary for report {rid[:8]}…" if rid != "{report-id}" else "Summary per report",
                f"ai-content/report-summaries/client/{rid}.json") for rid in shown]
            + [(f"Summary page for report {rid[:8]}…" if rid != "{report-id}" else "Summary page per report",
                f"ai-content/report-summaries/client/{rid}.html") for rid in shown]
        ),
        note="This container belongs to this client alone, so nothing here can collide with "
             "another client. The file name is the Power BI REPORT id, because that is what the "
             "app asks for - it is not the dataset id.",
    )
    if ai_enabled and not report_ids:
        app.note += (" No report IDs are listed, so the agent will look them up in Power BI and "
                     "publish under whatever it finds.")
    if len(report_ids) > 3:
        app.note += f" ({len(report_ids)} report IDs configured; the first three are shown.)"

    # --------------------------------------------------------- 3. private memory
    memory_container = str(cfg.get("azure_blob_memory_container") or "insightstate").strip()
    memory_prefix = str(cfg.get("azure_blob_memory_prefix") or "").strip("/")
    summary_memory_prefix = str(
        cfg.get("azure_blob_summary_memory_prefix") or "summary-memory").strip("/")
    memory_cloud = str(cfg.get("insight_memory_storage") or "local") == "azure_blob"
    summary_cloud = str(cfg.get("summary_memory_storage")
                        or cfg.get("insight_memory_storage") or "local") == "azure_blob"

    memory = Destination(
        id="memory",
        title="Private memory",
        audience="nobody - the agent only",
        purpose="What has already been reported, so tomorrow's report does not repeat today's.",
        container=memory_container,
        enabled=memory_cloud or summary_cloud,
        settings=["insight_memory_storage", "summary_memory_storage",
                  "azure_blob_memory_container", "azure_blob_memory_prefix",
                  "azure_blob_summary_memory_prefix"],
        paths=[
            ("What insights were reported", _join(memory_prefix, dataset, "memory.json")),
            ("Which topics were covered", _join(summary_memory_prefix, dataset, "memory.json")),
        ],
        note="Filed under the dataset ID, so two clients can never clash here even sharing a "
             "folder. Never expose this container to an app.",
    )
    if not (memory_cloud and summary_cloud):
        memory.warning = ("Memory is kept on the machine that runs the job. A scheduled cloud job "
                          "gets a new machine every time, so it would forget everything nightly "
                          "and repeat itself.")

    return {
        "account": account or "(not set)",
        "destinations": [own.json(), app.json(), memory.json()],
    }
