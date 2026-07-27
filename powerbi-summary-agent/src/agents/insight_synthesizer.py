"""Insight branch - Synthesizer (LLM, free-form markdown).

Mirrors summary_generator: turns the detected signals + investigation trails
into insight_report.md/.html.
"""

import re

from ..tools import file_io
from ..tools import html_report
from ..tools import insight_tiles
from ..tools.llm import get_llm
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


_BUSINESS_FIGURE = re.compile(
    r"(?<![A-Za-z0-9])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB]\b)|"
    r"(?<![A-Za-z0-9])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?"
)
_TECHNICAL_MANAGER_PHRASES = (
    "movement decomposition",
    "volume effect",
    "rate effect",
    "share of total change",
    "realized revenue per unit",
    "basket mix",
    "product mix",
    "sell-through",
    "materiality",
    "reconciliation",
    "z-score",
    "probe",
    "signal",
    "trail",
)
_CHANGE_WORDS = re.compile(
    r"\b(increased?|decreased?|rose|fell|grew|declined?|added|reduced|"
    r"higher|lower|more|fewer|above|below)\b",
    re.IGNORECASE,
)
_DRIVER_WORDS = re.compile(
    r"\b(because|mainly|driven|came from|resulted from|due to|led by|explained by|"
    r"concentrated|while|although|associated|linked|checks showed|no clear driver)\b",
    re.IGNORECASE,
)
_NEXT_CHECK_WORDS = re.compile(
    r"\b(check|review|compare|confirm|investigate|examine|validate|monitor|verify)\b",
    re.IGNORECASE,
)


def _response_text(response) -> str:
    report = response.content if hasattr(response, "content") else str(response)
    if isinstance(report, list):
        report = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in report
        )
    return str(report).strip()


def _key_insight_paragraphs(report: str) -> list[str]:
    match = re.search(
        r"(?ms)^# Key Insights\s*(.*?)(?=^# Data Quality Watch-outs\s*$)",
        report or "",
    )
    if not match:
        return []
    return [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", match.group(1))
        if paragraph.strip().startswith("**")
    ]


def _clarity_issues(report: str, expected_findings: int) -> list[str]:
    """Check only manager-facing Key Insights; technical appendices stay auditable."""
    if expected_findings <= 0:
        return []
    paragraphs = _key_insight_paragraphs(report)
    issues: list[str] = []
    if len(paragraphs) != expected_findings:
        issues.append(
            f"Key Insights has {len(paragraphs)} finding paragraph(s); expected {expected_findings}"
        )
    for index, paragraph in enumerate(paragraphs, start=1):
        plain = paragraph.casefold()
        words = re.findall(r"\b\w+[\w'-]*\b", paragraph)
        figures = _BUSINESS_FIGURE.findall(paragraph)
        takeaway_match = re.match(r"\*\*(.+?)\*\*", paragraph, flags=re.DOTALL)
        takeaway = takeaway_match.group(1) if takeaway_match else ""
        if len(words) > 90:
            issues.append(f"finding {index} is {len(words)} words; maximum is 90")
        if not figures:
            issues.append(f"finding {index} does not state the size of the change")
        elif len(figures) > 4:
            issues.append(f"finding {index} contains {len(figures)} figures; maximum is 4")
        if not _CHANGE_WORDS.search(paragraph):
            issues.append(f"finding {index} does not plainly say what changed")
        if not _BUSINESS_FIGURE.search(takeaway) or not _CHANGE_WORDS.search(takeaway):
            issues.append(
                f"finding {index} bold takeaway must state what changed and its figure"
            )
        if not _DRIVER_WORDS.search(paragraph):
            issues.append(f"finding {index} does not explain the main evidenced contributor")
        if not _NEXT_CHECK_WORDS.search(paragraph):
            issues.append(f"finding {index} does not end with a specific check")
        found = [phrase for phrase in _TECHNICAL_MANAGER_PHRASES if phrase in plain]
        if found:
            issues.append(
                f"finding {index} uses analyst shorthand: {', '.join(found)}"
            )
    return issues


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: synthesizing the insight report...")

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("insight_synthesizer_prompt.md")

    understanding = state.get("report_understanding", {})
    signals = state.get("insight_signals", [])
    investigations = state.get("insight_investigations", [])
    novelty = state.get("insight_novelty", {}) or {}

    # Reason-aware empty state: distinguish "no data" / "nothing notable" / "all
    # already reported before" / "memory unreadable" so the report is truthful
    # about WHY there is nothing new, rather than implying nothing exists.
    empty_notes = {
        "no_scan_data": ("The diagnostic scan returned no usable data. Write the "
                         "report explaining that nothing could be evaluated this run."),
        "no_notable_findings": ("Nothing crossed the materiality floor this run. "
                                "Write the report emphasizing what was scanned and "
                                "why nothing stood out."),
        "all_previously_reported": ("Findings were detected but ALL of them were "
                                    "already reported in previous runs. Say clearly "
                                    "that there are no NEW insights today and briefly "
                                    "note that prior findings still stand."),
        "no_new_selected": ("No new findings were selected this run. State that there "
                            "is nothing new to report today."),
        "memory_corrupt": ("The insight memory store was unreadable this run, so the "
                           "no-repeat guarantee is unavailable and findings below may "
                           "have been reported before. Flag this caveat prominently."),
    }
    reason = novelty.get("reason")
    note = ""
    if not signals:
        note = empty_notes.get(reason, empty_notes["no_notable_findings"])
    elif reason == "memory_corrupt":
        note = empty_notes["memory_corrupt"]

    context = {
        "report_understanding": understanding,
        "signals": signals,
        "investigations": investigations,
        "coverage_matrix": state.get("insight_coverage_matrix", {}),
        "resolved_entity_scope": state.get("resolved_entity_scope", {}),
        "metadata_profile_warnings": state.get("semantic_model_profile", {}).get("warnings", []),
        "novelty": {k: novelty.get(k) for k in
                    ("reason", "detected", "suppressed", "eligible", "selected",
                     "policy", "memory_status", "level_breakdown")},
        "temporal": {**{k: (state.get("insight_temporal_verdict", {}) or {}).get(k)
                        for k in ("enabled", "grain", "column", "reason")},
                     "worst_period_drill": state.get("insight_temporal_drill")},
        # Phase 3/3b: the recent-week verdict carries the honest caveat when
        # disabled (load/posting-date axis or stale data). When enabled, phrase
        # the movement from each signal's structured `recent_week` payload (the
        # delta % is `change_pct`, NOT impact_share), with hedged contribution
        # language - and phrase it as "trailing 7 days" rather than "week of"
        # when `window_mode` is "rolling".
        "recent_week": {k: (state.get("insight_recent_week_verdict", {}) or {}).get(k)
                        for k in ("enabled", "reason", "window_mode", "week_start", "week_end",
                                  "data_as_of", "effective_data_as_of", "drivers")},
        # Phase 3b: the daily verdict carries the same honest disabled-caveat
        # pattern - it disables independently of recent-week's own gate/mode,
        # based only on whether a validated business-day axis exists.
        "daily": {k: (state.get("insight_daily_verdict", {}) or {}).get(k)
                 for k in ("enabled", "reason", "incidents_found", "incidents_reported")},
        "note": note,
    }

    llm = get_llm(state)  # free-form text output
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task},
        {"role": "user", "content": "SIGNALS + INVESTIGATION TRAILS:\n" + dumps(context)},
    ]

    report = ""
    clarity_issues = []
    expected_business_findings = sum(
        1 for signal in signals if signal.get("kind") != "data_quality"
    )
    for attempt in range(3):
        report = _response_text(llm.invoke(messages))
        clarity_issues = _clarity_issues(report, expected_business_findings)
        if not clarity_issues:
            break
        if attempt < 2:
            log.info(
                "Insight report clarity check requested a rewrite (%d issue(s))."
                % len(clarity_issues)
            )
            messages.extend([
                {"role": "assistant", "content": report},
                {
                    "role": "user",
                    "content": (
                        "Rewrite the complete report. Preserve the supplied facts and required "
                        "section headings, but fix every manager-facing clarity issue below. "
                        "Keep technical calculation detail only in Evidence Trail.\n- "
                        + "\n- ".join(clarity_issues)
                    ),
                },
            ])
    if clarity_issues:
        log.error(
            "Insight report still has %d manager-facing clarity issue(s) after retries."
            % len(clarity_issues)
        )

    file_io.write_text(state, "insight_report.md", report)

    domain = understanding.get("domain") if isinstance(understanding, dict) else None
    title = f"{domain} Insight Report" if domain else "Insight Report"
    file_io.write_text(state, "insight_report.html",
                       html_report.render(report, title=title, eyebrow="Power BI Insight Report"))

    # Optional deterministic visual board. Insight history still reuses the
    # Markdown heading parser from insight_tiles.py even when this HTML artifact
    # is disabled, so do not remove the shared module.
    if state.get("insight_tiles_enabled", False):
        try:
            insight_tiles.write_from_state(state, report_md=report)
            log.info("Insight board written (insight_tiles.html).")
        except Exception as exc:  # noqa: BLE001 - defensive; supplementary artifact
            log.info(f"Insight board skipped ({type(exc).__name__}: {exc}).")
    else:
        log.info("Insight board disabled (insight_tiles_enabled=false).")

    log.info(f"Insight report written ({len(report.split())} words).")
    return {"insight_report": report, **log.updates()}
