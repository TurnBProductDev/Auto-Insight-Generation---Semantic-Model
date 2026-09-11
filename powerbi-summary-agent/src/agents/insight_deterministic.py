"""Code-owned investigation trails and insight report (report_ai_tier=deterministic).

The investigated tier spends most of a run's money in two places: a
tool-calling investigator that decides which follow-up queries to run, and a
free-form writer that turns the trails into the report. This module is what
both become when a run may not call a language model.

**Investigation.** `insight_gap_scan` has already drilled every selected finding
deterministically, scoped to exactly its members, before the investigator is
reached. On the measured 2026-09-08 run the LLM investigator then added no probe
of its own to three of four signals and one to the fourth; what it contributed
was prose. So a trail here is those gap-scan rows, recorded in the investigator's
own `run_dax` shape (so every consumer of `probes` reads them unchanged) and
marked `origin: gap_scan`, with a code-written explanation naming the largest
movements in each breakdown.

**Report.** The same five sections the synthesizer prompt requires, in the same
order, so the history parser, the API payloads and the clarity check read it
unchanged. The manager-facing Key Insights paragraphs are
`insight_synthesizer._deterministic_finding` - the writer that already replaces
an LLM paragraph that fails the clarity check - so the words the reader sees are
ones this repo has been publishing as a fallback, now used first. The other four
sections are for the report owner and are stated plainly, including the fact
that no model was asked.

What is genuinely lost, and the report says so: the LLM could merge related
findings into one story and ask a follow-up question the standard breakdowns did
not cover. Neither is attempted here.
"""

from __future__ import annotations

from typing import Any

from . import insight_synthesizer as syn

#: Largest movements named per breakdown in a trail's explanation.
TOP_MOVERS = 3

_REASON_SENTENCES = {
    "no_scan_data": "The diagnostic scan returned no usable data, so nothing could be evaluated in this run.",
    "no_notable_findings": "Nothing crossed the reporting threshold in this run.",
    "all_previously_reported": ("Every finding detected in this run was already reported in an earlier "
                                "run, so there are no new insights today. Earlier findings still stand."),
    "no_new_selected": "No new findings were selected in this run.",
    "memory_corrupt": ("The record of earlier findings could not be read in this run, so findings below "
                       "may have been reported before."),
}


# --------------------------------------------------------------- investigation


def change_measure(signal: dict, profile: dict) -> str | None:
    """The change measure of the family this signal is about.

    Read from the semantic profile rather than named, so the trail works on any
    model whose profile resolved its bundles - "revenue Growth" on SB Mart is
    only this model's spelling.
    """
    family = str(signal.get("metric_family") or "").strip().lower()
    if not family:
        family = str(signal.get("metric") or "").split("::")[-1].strip().lower()
    bundles = ([profile.get("primary_value_bundle") or {}]
               + list(profile.get("volume_driver_bundles") or [])
               + list(profile.get("value_bundles") or [])
               + list(profile.get("measure_bundles") or []))
    for bundle in bundles:
        if isinstance(bundle, dict) and str(bundle.get("family") or "").lower() == family:
            name = (bundle.get("measures") or {}).get("change")
            if name:
                return name
    primary = profile.get("primary_value_bundle") or {}
    return (primary.get("measures") or {}).get("change")


def _dimension_label(column: str) -> str:
    text = str(column or "").lower()
    for suffix in ("_name", "_no", "_code", "_id"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    return text.replace("_", " ").strip() or "breakdown"


def _member(row: dict, column: str) -> str:
    value = row.get(column)
    if value in (None, ""):
        for key, candidate in row.items():
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return "Unassigned"
    return str(value)


def _signed(value: float) -> str:
    shown = syn._display_value(abs(value)) or f"{abs(value):,.0f}"
    return ("+" if value >= 0 else "-") + shown


def trail(signal: dict, gap: dict, profile: dict) -> dict:
    """One investigation trail built from the gap scan's rows, no model call."""
    measure = change_measure(signal, profile)
    evidence = (gap or {}).get("evidence") or {}
    probes: list[dict] = []
    sentences: list[str] = []
    complete = 0
    for drill, ev in evidence.items():
        ev = ev or {}
        rows = [r for r in (ev.get("rows") or []) if isinstance(r, dict)]
        is_complete = ev.get("completeness") == "complete"
        complete += 1 if is_complete else 0
        probes.append({
            "tool": "run_dax",
            "origin": "gap_scan",
            "dimension": drill,
            "dax": ev.get("dax"),
            "status": "cache_hit" if ev.get("cache_hit") else "success",
            "completeness": ev.get("completeness"),
            "row_count": ev.get("row_count", len(rows)),
            "rows": rows,
        })
        if not measure:
            continue
        movers = sorted((r for r in rows if isinstance(r.get(measure), (int, float))),
                        key=lambda r: -abs(r[measure]))[:TOP_MOVERS]
        if movers:
            named = ", ".join(f"{_member(r, drill)} ({_signed(float(r[measure]))})" for r in movers)
            sentences.append(
                f"By {_dimension_label(drill)}, the largest movements in {measure} were {named}"
                + ("." if is_complete else "; this breakdown was incomplete."))
    if not sentences:
        sentences.append("No breakdown of this finding was returned, so no explanation was measured.")
    return {
        "signal": signal,
        "probes": probes,
        "probe_executions": 0,
        "concluded": complete > 0,
        "complete_breakdowns": complete,
        "explanation": " ".join(sentences),
        "deterministic": True,
    }


# ---------------------------------------------------------------------- report


def _minimal_finding(signal: dict, brief: dict) -> str | None:
    """A shorter grounded paragraph when the full one would exceed the word limit.

    `_deterministic_finding` returns None rather than publish a paragraph over the
    manager word limit. Retrying with one measured driver and no area breakdown
    keeps the headline, the share and the main reason, which is what the clarity
    check requires, and drops only the detail the Evidence Trail still carries.
    """
    trimmed = dict(brief)
    trimmed["drivers"] = list(brief.get("drivers") or [])[:1]
    main = dict(brief.get("main") or {})
    main.pop("other_area_breakdown", None)
    trimmed["main"] = main
    return syn._deterministic_finding(signal, trimmed)


def _segment(signal: dict) -> str:
    return str(signal.get("affected_segment") or signal.get("segment") or "This area")


def write_report(state: dict, signals: list[dict], investigations: list[dict],
                 fact_briefs: list[dict], novelty: dict) -> str:
    """The insight report with the synthesizer's five sections, no model call."""
    by_signal = {((inv.get("signal") or {}).get("id")): inv for inv in investigations or []}
    pairs = list(zip(signals, fact_briefs))
    business = [(s, b) for s, b in pairs if s.get("kind") != "data_quality"]
    data_quality = [s for s in signals if s.get("kind") == "data_quality"]

    lines: list[str] = ["# Key Insights"]
    if not business:
        reason = (novelty or {}).get("reason") or "no_notable_findings"
        lines.append(_REASON_SENTENCES.get(reason, _REASON_SENTENCES["no_notable_findings"]))
    else:
        paragraphs = []
        for signal, brief in business:
            paragraph = syn._deterministic_finding(signal, brief) or _minimal_finding(signal, brief)
            if paragraph:
                paragraphs.append(paragraph)
        lines.append("\n\n".join(paragraphs))

    lines.append("")
    lines.append("# Data Quality Watch-outs")
    if data_quality:
        lines.extend("- " + syn._simple_data_quality_bullet(str(s.get("description") or ""))
                     for s in data_quality)
    else:
        lines.append("None observed in this run.")

    lines.append("")
    lines.append("# Evidence Trail")
    if not signals:
        lines.append("- No finding was selected, so no breakdown was run.")
    for signal in signals:
        inv = by_signal.get(signal.get("id")) or {}
        lines.append(f"- **{_segment(signal)}** (`{signal.get('id')}`): {signal.get('description') or ''}".rstrip())
        for probe in inv.get("probes") or []:
            lines.append(f"  - Gap-scan breakdown by `{probe.get('dimension')}`: "
                         f"{probe.get('row_count', 0)} row(s), {probe.get('completeness') or 'completeness unknown'}.")
        if inv.get("explanation"):
            lines.append(f"  - {inv['explanation']}")

    lines.append("")
    lines.append("# Confidence & Caveats")
    for signal, _brief in business:
        inv = by_signal.get(signal.get("id")) or {}
        checked = len(inv.get("probes") or [])
        complete = int(inv.get("complete_breakdowns") or 0)
        if complete:
            lines.append(f"- {_segment(signal)}: {complete} of {checked} breakdown(s) came back complete.")
        else:
            lines.append(f"- {_segment(signal)}: no complete breakdown came back, so the finding "
                         f"is stated without a measured explanation.")
    lines.append("- This report was written by fixed rules without an AI model. Findings are ranked by "
                 "size, related findings are not combined, and no follow-up question was asked beyond "
                 "the standard breakdowns.")
    for key, label in (("insight_temporal_verdict", "Month-by-month checks"),
                       ("insight_recent_week_verdict", "Recent-week checks"),
                       ("insight_daily_verdict", "Daily checks")):
        verdict = state.get(key) or {}
        if verdict and not verdict.get("enabled") and verdict.get("reason"):
            lines.append(f"- {label} were not run: {verdict['reason']}.")

    lines.append("")
    lines.append("# Suggested Follow-ups")
    if not business:
        lines.append("- None for this run.")
    for signal, _brief in business:
        inv = by_signal.get(signal.get("id")) or {}
        incomplete = [p.get("dimension") for p in inv.get("probes") or []
                      if p.get("completeness") != "complete"]
        if incomplete:
            lines.append(f"- Which parts of {_segment(signal)} explain the change once the full breakdown "
                         f"is available? (by `{'`, `'.join(str(d) for d in incomplete)}`)")
        else:
            lines.append(f"- Which products inside {_segment(signal)} account for most of the change?")
    return "\n".join(lines).rstrip() + "\n"


def summary_numbers(**payload: Any) -> list[float]:
    """The synthesizer's supported-number set, for the clarity check."""
    return syn._supported_numbers(payload)
