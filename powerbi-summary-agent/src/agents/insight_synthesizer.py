"""Insight branch - Synthesizer (LLM, free-form markdown).

Mirrors summary_generator: turns the detected signals + investigation trails
into insight_report.md/.html.
"""

from ..tools import file_io
from ..tools import html_report
from ..tools import insight_tiles
from ..tools.llm import get_llm
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


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
        "note": note,
    }

    llm = get_llm(state)  # free-form text output
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task},
        {"role": "user", "content": "SIGNALS + INVESTIGATION TRAILS:\n" + dumps(context)},
    ]

    resp = llm.invoke(messages)
    report = resp.content if hasattr(resp, "content") else str(resp)
    if isinstance(report, list):  # some providers return content blocks
        report = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in report
        )

    file_io.write_text(state, "insight_report.md", report)

    domain = understanding.get("domain") if isinstance(understanding, dict) else None
    title = f"{domain} Insight Report" if domain else "Insight Report"
    file_io.write_text(state, "insight_report.html",
                       html_report.render(report, title=title, eyebrow="Power BI Insight Report"))

    # Insight board: one visual tile per signal (bold heading + data-driven chart
    # + See-more). Best-effort and never fatal -- a rendering slip must not sink
    # the run, mirroring the enrichment/HTML philosophy elsewhere.
    try:
        insight_tiles.write_from_state(state, report_md=report)
        log.info("Insight board written (insight_tiles.html).")
    except Exception as exc:  # noqa: BLE001 - defensive; supplementary artifact
        log.info(f"Insight board skipped ({type(exc).__name__}: {exc}).")

    log.info(f"Insight report written ({len(report.split())} words).")
    return {"insight_report": report, **log.updates()}
