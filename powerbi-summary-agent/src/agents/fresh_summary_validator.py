"""Final deterministic validation and rendering for the fresh summary."""

from __future__ import annotations

from ..tools import file_io, summary_visual
from ..tools.summary_validation import validate_draft
from ..utils.logger import RunLogger


def _merge_focus_evidence(candidate: dict, evidence_doc: dict) -> dict:
    """Rebuild the grounded R4 candidate used by the authoring validator.

    The multi-focus node stores deep-dive evidence separately so it does not
    mutate the shared candidate list.  The generator merges that evidence
    before authoring; final validation must validate against the same merged
    view rather than the pre-drill candidate snapshot.
    """
    base = candidate.get("evidence") or {}
    if not evidence_doc:
        return candidate
    return {
        **candidate,
        "evidence": {
            **base,
            "deep_dive": evidence_doc.get("sections") or base.get("deep_dive") or {},
            "facts": evidence_doc.get("facts") or base.get("facts") or [],
        },
    }


def _merge_overall_evidence(candidate: dict, package: dict) -> dict:
    """Attach the summary-owned Overall trend exactly as the generator does."""
    base = candidate.get("evidence") or {}
    deep_dive = dict(base.get("deep_dive") or {})
    trend = (package or {}).get("trend")
    if trend:
        deep_dive["period_trend"] = trend
    return {**candidate, "evidence": {**base, "deep_dive": deep_dive}}


def _validation_candidates(state: dict, summary: dict) -> list[dict]:
    """Resolve covered candidates with the same R4 evidence used to author."""
    candidates = (
        list(state.get("summary_candidates", []) or [])
        + list(state.get("summary_eligible_candidates", []) or [])
    )
    by_id = {
        str(candidate.get("candidate_id")): candidate
        for candidate in candidates
        if candidate.get("candidate_id")
    }
    if state.get("summary_r4_enabled"):
        package = state.get("summary_overall_performance") or {}
        for candidate_id, candidate in list(by_id.items()):
            if candidate.get("angle") == "overall_performance":
                by_id[candidate_id] = _merge_overall_evidence(candidate, package)

        evidence_by_key = state.get("summary_focus_evidence_by_key") or {}
        for focus in state.get("summary_selected_focuses", []) or []:
            candidate_id = str(focus.get("candidate_id") or "")
            if not candidate_id:
                continue
            base = by_id.get(candidate_id) or focus
            evidence_doc = evidence_by_key.get(str(focus.get("focus_key") or "")) or {}
            by_id[candidate_id] = _merge_focus_evidence(base, evidence_doc)

    return [
        by_id[candidate_id]
        for candidate_id in (
            str(item) for item in summary.get("covered_candidate_ids", []) or []
        )
        if candidate_id in by_id
    ]


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
    selected = _validation_candidates(state, summary)
    if selected:
        # Authoring validates against the chart-source catalogue before
        # resolution. Recompute only its availability here so a chart that was
        # accidentally lost during resolution cannot silently reach the HTML.
        from .fresh_summary_generator import _chart_sources

        chart_required = bool(
            state.get("summary_visual_enabled", True)
            and _chart_sources(selected)
        )
        errors = validate_draft(
            summary,
            selected,
            mode="balanced_multi_focus" if state.get("summary_r4_enabled") else "single_focus",
            require_chart=chart_required,
        )
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
