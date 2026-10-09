"""Which reports speak in the brief, and in what order.

Only a report that published a summary qualifies: its headline is the line's
fallback, so a report without one has nothing true to fall back to (and Home
already says "No summary yet" for it). The rest are ordered by their most
severe card or figure (critical, warning, positive, info), then by how many of
their findings share that severity, then by their place in ``brief_reports``.
"""

from __future__ import annotations

from .facts import ReportFacts


def rank_reports(reports: list[ReportFacts], limit: int) -> list[ReportFacts]:
    """The reports the brief covers, most pressing first, at most ``limit``."""
    candidates = [(position, report) for position, report in enumerate(reports) if report.has_summary]

    def order(pair: tuple[int, ReportFacts]) -> tuple[int, int, int]:
        position, report = pair
        severity = report.severity_index()
        return severity, -report.count_at(severity), position

    return [report for _, report in sorted(candidates, key=order)][:max(0, int(limit))]
