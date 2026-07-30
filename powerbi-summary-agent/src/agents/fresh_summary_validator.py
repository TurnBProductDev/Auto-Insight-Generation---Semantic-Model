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
    blocks = summary.get("content_blocks")
    if blocks is not None:
        for block in blocks or []:
            kind = str(block.get("kind") or "")
            heading = str(block.get("heading") or "").strip()
            if heading:
                lines.extend([f"## {heading}", ""])
            if kind == "paragraph" and block.get("text"):
                lines.extend([str(block["text"]).strip(), ""])
            elif kind == "bullets":
                lines.extend(f"- {str(point).strip()}" for point in block.get("points") or [])
                lines.append("")
            elif kind == "chart" and isinstance(block.get("chart"), dict):
                chart = block["chart"]
                value_label = str(chart.get("value_label") or "Value")
                labels = list(chart.get("labels") or [])
                if chart.get("x_values") and chart.get("y_values"):
                    for index, (label, x_value, y_value) in enumerate(zip(
                        labels, chart.get("x_values") or [], chart.get("y_values") or []
                    )):
                        detail = f"{chart.get('x_label')}: {x_value}; {chart.get('y_label')}: {y_value}"
                        sizes = chart.get("size_values") or []
                        if index < len(sizes):
                            detail += f"; {chart.get('size_label')}: {sizes[index]}"
                        lines.append(f"- {label}: {detail}")
                elif chart.get("series"):
                    for index, label in enumerate(labels):
                        details = [
                            f"{series.get('name')}: {(series.get('values') or [])[index]}"
                            for series in chart.get("series") or []
                            if index < len(series.get("values") or [])
                        ]
                        lines.append(f"- {label}: {'; '.join(details)}")
                else:
                    for label, value in zip(labels, chart.get("values") or []):
                        lines.append(f"- {label}: {value} {value_label}")
                lines.append("")
    else:
        # Backward-compatible rendering for deterministic empty/legacy records.
        for section in summary.get("sections") or []:
            lines.extend([f"## {section.get('heading')}", ""])
            for point in section.get("points") or []:
                lines.append(f"- {str(point).strip()}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run(state: dict) -> dict:
    log = RunLogger(state)
    summary = dict(state.get("fresh_summary") or {})
    by_id = {
        str(candidate.get("candidate_id")): candidate
        for candidate in (
            list(state.get("summary_candidates", []) or [])
            + list(state.get("summary_eligible_candidates", []) or [])
        )
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
    charts = [
        block.get("chart")
        for block in summary.get("content_blocks") or []
        if block.get("kind") == "chart" and isinstance(block.get("chart"), dict)
    ]
    if charts:
        file_io.write_json(state, "summary_visual.json", {"charts": charts})

    log.info(
        "Fresh flexible summary validated and rendered (%d narrative block(s), %d interactive chart(s))."
        % (
            sum(1 for block in summary.get("content_blocks") or [] if block.get("kind") != "chart"),
            len(charts),
        )
    )
    return {
        "report_summary": markdown,
        "fresh_summary": summary,
        "summary_pending_keys": list(summary.get("covered_summary_keys") or []),
        **log.updates(),
    }
