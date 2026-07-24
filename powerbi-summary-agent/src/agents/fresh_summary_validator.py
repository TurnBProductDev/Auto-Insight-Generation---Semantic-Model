"""Final deterministic validation and rendering for the fresh summary."""

from __future__ import annotations

from ..tools import file_io, summary_visual
from ..tools.summary_validation import validate_draft
from ..utils.logger import RunLogger


def _markdown(summary: dict) -> str:
    lines = [f"# {summary.get('heading') or 'Latest performance summary'}", ""]
    data_as_of = summary.get("data_as_of") or "unknown"
    grain = str(summary.get("grain") or "snapshot").replace("_", " ")
    freshness = str(summary.get("freshness_status") or "unknown").replace("_", " ")
    lines.extend([f"*Data through {data_as_of} · {grain} grain · {freshness}*", ""])
    for paragraph in summary.get("paragraphs") or []:
        lines.extend([str(paragraph).strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def run(state: dict) -> dict:
    log = RunLogger(state)
    summary = dict(state.get("fresh_summary") or {})
    by_id = {
        str(candidate.get("candidate_id")): candidate
        for candidate in state.get("summary_candidates", []) or []
        if candidate.get("candidate_id")
    }
    selected = [
        by_id[candidate_id]
        for candidate_id in summary.get("covered_candidate_ids", []) or []
        if candidate_id in by_id
    ]
    if selected:
        errors = validate_draft(summary, selected)
        if errors:
            # The generator already has a grounded fallback, so reaching this
            # point is a programming/contract failure rather than a prompt issue.
            raise ValueError("fresh summary failed final validation: " + "; ".join(errors))

    markdown = _markdown(summary)
    title = (state.get("config") or {}).get("api_summary_title", "AI Summary")
    file_io.write_text(state, "report_summary.md", markdown)
    file_io.write_text(state, "report_summary.html", summary_visual.render(summary, title=title))
    file_io.write_json(state, "fresh_summary.json", summary)
    if summary.get("visual"):
        file_io.write_json(state, "summary_visual.json", summary["visual"])

    log.info(
        "Fresh summary validated and rendered%s."
        % (" with one supporting chart" if summary.get("visual") else " without a chart")
    )
    return {
        "report_summary": markdown,
        "fresh_summary": summary,
        "summary_pending_keys": list(summary.get("covered_summary_keys") or []),
        **log.updates(),
    }
