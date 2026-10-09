"""The brief's payload and its one blob, ``ai-content/kpi/client/brief.json``.

One job writes the brief for the whole client, so it is a plain overwrite in
the v1 envelope, unlike the merged feeds. The payload is validated against the
contract (Web App ``docs/home-v4/PLAN.md`` 5.1) before anything is written:
extra fields refused, absent ones left out rather than sent as null.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from .facts import ReportFacts

BRIEF_BLOB = "ai-content/kpi/client/brief.json"


class BriefLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    tone: Literal["critical", "warning", "positive", "info"]
    rank: int
    reportIds: list[str]
    reportSlug: str
    reportName: Optional[str] = None


class BriefQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    reportIds: list[str]


class Brief(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataAsOf: Optional[str] = None
    generatedAt: str
    lines: list[BriefLine]
    suggestedQuestions: list[BriefQuestion] = []


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def payload(selected: list[ReportFacts], authored: dict, *, generated_at: datetime) -> dict:
    """The published brief: one line per selected report, in rank order."""
    by_slug = {report.slug: report for report in selected}
    lines = []
    for rank, report in enumerate(selected, start=1):
        written = (authored.get("lines") or {}).get(report.slug) or {}
        lines.append(BriefLine(
            text=str(written.get("text") or report.headline), tone=report.tone(), rank=rank,
            reportIds=list(report.report_ids), reportSlug=report.slug, reportName=report.name))
    questions = [BriefQuestion(text=q["text"], reportIds=list(by_slug[q["report"]].report_ids))
                 for q in authored.get("questions") or [] if q.get("report") in by_slug]
    dates = [str(report.data_as_of)[:10] for report in selected if report.data_as_of]
    brief = Brief(dataAsOf=max(dates) if dates else None, generatedAt=_iso(generated_at),
                  lines=lines, suggestedQuestions=questions)
    return brief.model_dump(exclude_none=True)


def publish(container, *, client: str, dataset_id: str, brief: dict, now: datetime,
            expires: datetime, json_settings) -> dict:
    """Write the brief over the previous one. Raises on a storage failure."""
    from ..tools.ai_content_publisher import _json_bytes, build_envelope

    Brief(**brief)
    envelope = build_envelope(client=client, dataset_id=dataset_id, payload=brief,
                              generated_at=now, expires_at=expires)
    container.get_blob_client(BRIEF_BLOB).upload_blob(
        data=_json_bytes(envelope), overwrite=True, content_settings=json_settings)
    return {"status": "ok", "blob": BRIEF_BLOB, "lines": len(brief.get("lines") or []),
            "questions": len(brief.get("suggestedQuestions") or [])}
