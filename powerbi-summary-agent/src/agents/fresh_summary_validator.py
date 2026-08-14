"""Final deterministic validation and rendering for the fresh summary."""

from __future__ import annotations

import math
import re

from ..tools import file_io, summary_dashboard_html, summary_visual
from ..tools.summary_validation import validate_draft
from ..utils.logger import RunLogger


def _fmt_chart_number(value, label: str = "") -> str:
    """Human-readable chart value for Markdown (e.g. ``+669.8K``, not
    ``669793.8700000001``). Non-numeric values pass through unchanged. A sign is
    shown only for change/growth measures, matched from the value label."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return str(value)
    number = float(value)
    text = str(label or "").casefold()
    sign = "+" if re.search(r"change|growth|variance|delta", text) else ""
    if "%" in text or "percent" in text:
        pct = number * 100 if abs(number) <= 1.5 else number
        return f"{pct:{sign}.1f}%"
    magnitude = abs(number)
    if magnitude >= 1_000_000_000:
        return f"{number / 1_000_000_000:{sign}.2f}B"
    if magnitude >= 1_000_000:
        return f"{number / 1_000_000:{sign}.1f}M"
    if magnitude >= 1_000:
        return f"{number / 1_000:{sign}.1f}K"
    if 0 < magnitude < 1:
        return f"{number:{sign}.2f}"
    return f"{number:{sign}.0f}"


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
                x_label, y_label = chart.get("x_label"), chart.get("y_label")
                size_label = chart.get("size_label")
                if chart.get("x_values") and chart.get("y_values"):
                    for index, (label, x_value, y_value) in enumerate(zip(
                        labels, chart.get("x_values") or [], chart.get("y_values") or []
                    )):
                        detail = (
                            f"{x_label}: {_fmt_chart_number(x_value, x_label)}; "
                            f"{y_label}: {_fmt_chart_number(y_value, y_label)}"
                        )
                        sizes = chart.get("size_values") or []
                        if index < len(sizes):
                            detail += f"; {size_label}: {_fmt_chart_number(sizes[index], size_label)}"
                        lines.append(f"- {label}: {detail}")
                elif chart.get("series"):
                    for index, label in enumerate(labels):
                        details = [
                            f"{series.get('name')}: "
                            f"{_fmt_chart_number((series.get('values') or [])[index], value_label)}"
                            for series in chart.get("series") or []
                            if index < len(series.get("values") or [])
                        ]
                        lines.append(f"- {label}: {'; '.join(details)}")
                else:
                    for label, value in zip(labels, chart.get("values") or []):
                        lines.append(f"- {label}: {_fmt_chart_number(value, value_label)} {value_label}")
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
    file_io.write_text(
        state,
        "report_summary.html",
        summary_visual.render(
            summary,
            title=title,
            # Coverage is a deterministic, code-owned surface: it is rendered
            # straight from the scanned rows and never passes through the LLM
            # or the draft-validation contract.
            coverage=state.get("summary_coverage") or {},
            coverage_display_rows=int(state.get("summary_coverage_display_rows", 8)),
        ),
    )
    file_io.write_json(state, "fresh_summary.json", summary)

    # R6 dashboard, written from the code-owned page model. It never passes
    # through validate_draft: its figures are already reconciled and its prose was
    # validated per view by dashboard_rules inside the builder. Off by default, and
    # written to its own file so the existing report_summary.html contract is
    # untouched until a deployment explicitly opts in.
    dashboard = state.get("summary_dashboard") or {}
    if state.get("summary_r6_enabled") and dashboard.get("status") == "ok":
        dashboard_html = summary_dashboard_html.render(
            dashboard,
            coverage=state.get("summary_coverage") or {},
            display_rows=int(state.get("summary_coverage_display_rows", 8)),
            eyebrow=str(state.get("summary_dashboard_eyebrow") or "AI Insights"),
        )
        file_io.write_text(state, "report_dashboard.html", dashboard_html)
        if state.get("summary_dashboard_replaces_summary_html", False):
            file_io.write_text(state, "report_summary.html", dashboard_html)
        log.info(
            "Dashboard HTML written (%d view(s), mode=%s%s)."
            % (len(dashboard.get("views") or []), dashboard.get("authoring_mode"),
               ", also published as report_summary.html"
               if state.get("summary_dashboard_replaces_summary_html", False) else "")
        )

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
