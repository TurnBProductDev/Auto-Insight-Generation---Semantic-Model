"""Each report's facts, read from what the client's reports already published.

The brief job runs after the report jobs and reads only their published
output in the client's container, never Power BI:

    ai-content/report-summaries/client/{guid}.json   the report's summary
    ai-content/kpi/client/insights.json               today's KPI feed
    ai-content/kpi/client/highlights.json             today's Top Insights

``brief_reports`` names each report: its slug (the feed and Top Insights key
their items by it), its display name, and its Power BI report GUIDs (the
summaries are keyed by them, and the Web App drops lines about a report the
reader cannot open by them).

A report's fact sheet is the only thing the model sees about it, and the
validator checks every figure of the model's sentence against that same text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

SUMMARY_BLOB = "ai-content/report-summaries/client/{guid}.json"
FEED_BLOB = "ai-content/kpi/client/insights.json"
HIGHLIGHTS_BLOB = "ai-content/kpi/client/highlights.json"

#: Most severe first. A report's severity is the most severe of its KPI cards
#: and its own figures' tones.
SEVERITIES = ("critical", "warning", "positive", "info")

#: How many of a report's KPI cards its sheet carries, most severe first.
MAX_CARDS = 4

#: How many points of the summary's first section the sheet carries, and how
#: many sentences of each: enough for the report's own framing, not its essay.
CONTEXT_POINTS = 2
CONTEXT_SENTENCES = 2

_SPACES = re.compile(r"[   \s]+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def plain(text: Any) -> str:
    """One line of plain text: no-break spaces as spaces, the minus sign as a hyphen."""
    return _SPACES.sub(" ", str(text or "").replace("−", "-")).strip()


def _first_sentences(text: str, count: int) -> str:
    return " ".join(_SENTENCE_END.split(plain(text))[:count])


def _day(value: str | None) -> str:
    try:
        day = date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return ""
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')} ({day.isoformat()})"


@dataclass
class ReportFacts:
    """One report: who it is, and what it published today."""

    slug: str
    name: str
    report_ids: list[str]
    headline: str = ""
    data_as_of: str | None = None
    metrics: list[dict] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    highlights: list[dict] = field(default_factory=list)

    @property
    def has_summary(self) -> bool:
        return bool(self.headline)

    def _severities(self) -> list[int]:
        found = [str(card.get("severity") or "").lower() for card in self.cards]
        found += [str(metric.get("tone") or "").lower() for metric in self.metrics]
        return [SEVERITIES.index(word) for word in found if word in SEVERITIES]

    def severity_index(self) -> int:
        """0 for critical ... 3 for info; 4 when nothing carries a severity."""
        return min(self._severities(), default=len(SEVERITIES))

    def count_at(self, index: int) -> int:
        return sum(1 for value in self._severities() if value == index)

    def tone(self) -> str:
        index = self.severity_index()
        return SEVERITIES[index] if index < len(SEVERITIES) else "info"

    def sheet(self) -> str:
        """The fact sheet, as the model reads it and the validator checks it."""
        lines = [f"Report: {plain(self.name)}"]
        if self.data_as_of:
            lines.append(f"Data as of: {_day(self.data_as_of) or plain(self.data_as_of)}")
        lines.append(f"Headline: {plain(self.headline)}")
        if self.metrics:
            lines.append("Figures:")
            for metric in self.metrics:
                parts = [plain(metric.get(key)) for key in ("verdict", "note", "takeaway")]
                extra = "; ".join(part for part in parts if part)
                lines.append(f"- {plain(metric.get('label'))}: {plain(metric.get('value'))}"
                             + (f" ({extra})" if extra else ""))
        if self.context:
            lines.append("Context:")
            lines.extend(f"- {point}" for point in self.context)
        if self.cards:
            lines.append("Findings:")
            for card in self.cards:
                label = plain(card.get("label") or card.get("metric") or "")
                text = f"- [{plain(card.get('severity'))}] {label}: {plain(card.get('value'))}"
                if card.get("delta"):
                    text += f", change {plain(card.get('delta'))} {plain(card.get('deltaDirection'))}"
                # The card's own phrase ("against the remaining month target")
                # says more than the chip ("vs baseline"); the chip is the fallback.
                comparison = card.get("comparisonLabel") or (card.get("comparison") or {}).get("label")
                if comparison:
                    text += f" ({plain(comparison)})"
                title = (card.get("insight") or {}).get("title")
                if title:
                    text += f". {plain(title)}"
                lines.append(text)
        if self.highlights:
            lines.append("Stood out:")
            for item in self.highlights:
                value = " ".join(plain(item.get(key)) for key in ("value", "detail") if item.get(key))
                text = f"- {plain(item.get('title'))}: {value}"
                if item.get("comparisonLabel"):
                    text += f" ({plain(item.get('comparisonLabel'))})"
                lines.append(text)
        return "\n".join(lines)


def configured_reports(cfg: dict) -> list[ReportFacts]:
    """The reports ``brief_reports`` names, in its order. Refuses a malformed entry
    rather than skipping it: a report silently missing from the brief is a fault
    nobody would see."""
    from ..tools.ai_content_publisher import _guid

    out: list[ReportFacts] = []
    raw = cfg.get("brief_reports") or []
    if not isinstance(raw, list):
        raise ValueError("brief_reports must be a list of reports")
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError(f"brief_reports entry is not an object: {entry!r}")
        slug = str(entry.get("report_id") or "").strip()
        ids = entry.get("ai_content_report_ids") or []
        guids = [g for g in (_guid(v) for v in (ids if isinstance(ids, list) else [ids])) if g]
        if not slug or not guids:
            raise ValueError(f"brief_reports entry needs report_id and ai_content_report_ids: {entry!r}")
        if any(report.slug == slug for report in out):
            raise ValueError(f"brief_reports names {slug!r} twice")
        out.append(ReportFacts(slug=slug, name=str(entry.get("report_name") or slug).strip(),
                               report_ids=guids))
    return out


def _payload(container, name: str, log=print) -> Any:
    """A published blob's payload; None when it is absent or unreadable.

    A missing or corrupt blob costs only its own report's facts. Any other
    failure (no access, no network) is not a fact about one report, and raises.
    """
    from azure.core.exceptions import ResourceNotFoundError

    try:
        raw = container.get_blob_client(name).download_blob().readall()
    except ResourceNotFoundError:
        return None
    try:
        body = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        log(f"  {name}: unreadable ({type(exc).__name__}); left out")
        return None
    return body.get("payload") if isinstance(body, dict) and "payload" in body else body


def _summary(container, report: ReportFacts, log=print) -> dict | None:
    """The newest summary among the report's GUIDs (they are normally copies)."""
    best = None
    for guid in report.report_ids:
        payload = _payload(container, SUMMARY_BLOB.format(guid=guid), log)
        if isinstance(payload, dict) and payload.get("headline"):
            if best is None or str(payload.get("generatedAt") or "") > str(best.get("generatedAt") or ""):
                best = payload
    return best


def _card_order(card: dict) -> tuple:
    severity = str(card.get("severity") or "").lower()
    rank = card.get("rank")
    return (SEVERITIES.index(severity) if severity in SEVERITIES else len(SEVERITIES),
            rank if isinstance(rank, (int, float)) else 10**6)


def gather(container, reports: list[ReportFacts], log=print) -> list[ReportFacts]:
    """Fill each report's facts from the client's published content."""
    feed = _payload(container, FEED_BLOB, log)
    feed = feed if isinstance(feed, list) else []
    stood_out = _payload(container, HIGHLIGHTS_BLOB, log)
    stood_out = stood_out if isinstance(stood_out, list) else []
    for report in reports:
        summary = _summary(container, report, log) or {}
        report.headline = plain(summary.get("headline"))
        report.data_as_of = summary.get("dataAsOf") or None
        report.metrics = [m for m in (summary.get("metrics") or []) if isinstance(m, dict)]
        sections = [s for s in (summary.get("sections") or []) if isinstance(s, dict)]
        points = (sections[0].get("points") or []) if sections else []
        report.context = [_first_sentences(p, CONTEXT_SENTENCES) for p in points[:CONTEXT_POINTS] if plain(p)]
        own = [c for c in feed if isinstance(c, dict) and str(c.get("reportId") or "") == report.slug]
        report.cards = sorted(own, key=_card_order)[:MAX_CARDS]
        report.highlights = [h for h in stood_out
                             if isinstance(h, dict) and str(h.get("reportSlug") or "") == report.slug]
        log(f"  {report.slug}: {'summary' if report.headline else 'NO summary'}, "
            f"{len(report.cards)} card(s), {len(report.highlights)} highlight(s)")
    return reports
