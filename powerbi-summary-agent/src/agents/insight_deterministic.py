"""Code-owned investigation trails and insight report, below the investigated tier.

The investigated tier spends most of a run's money in two places: a
tool-calling investigator that decides which follow-up queries to run, and a
free-form writer that turns the trails into the report. This module is what
both become when no model may make a decision - the ``narrated`` and
``deterministic`` tiers of `src/tools/ai_tier.py`. The ``reasoned`` tier uses
them too: a model chose the findings, and the caveat says so.

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
unchanged. Code owns the structure completely. The manager-facing Key Insights
paragraphs are the only prose slots:

* deterministic - each is `insight_synthesizer._deterministic_finding`, the
  writer that already replaces an LLM paragraph failing the clarity check;
* narrated - `narrate_key_insights` has a model rewrite those same paragraphs
  for a manager, and every rewritten paragraph is held, on its own, to the same
  `_clarity_issues` check against its own fact brief and the run's supported
  numbers. One that fails keeps the code-written paragraph. The model never
  sees a raw row, chooses a finding, adds a section or writes the four owner
  sections.

What is genuinely lost below the investigated tier, and the report says so: a
model could merge related findings into one story and ask a follow-up question
the standard breakdowns did not cover. Neither is attempted here.
"""

from __future__ import annotations

from typing import Any, Callable

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


def grounded_paragraph(signal: dict, brief: dict) -> str | None:
    """The code-written Key Insights paragraph for one finding."""
    return syn._deterministic_finding(signal, brief) or _minimal_finding(signal, brief)


def _segment(signal: dict) -> str:
    return str(signal.get("affected_segment") or signal.get("segment") or "This area")


def business_pairs(signals: list[dict], fact_briefs: list[dict]) -> list[tuple[dict, dict]]:
    return [(s, b) for s, b in zip(signals, fact_briefs) if s.get("kind") != "data_quality"]


def paragraph_issues(paragraph: str, brief: dict, supported_numbers: list[float]) -> list[str]:
    """The synthesizer's manager-facing check, applied to one paragraph alone."""
    return syn._clarity_issues(
        "# Key Insights\n" + paragraph.strip() + "\n\n# Data Quality Watch-outs\n",
        1, [brief], supported_numbers)


# ------------------------------------------------------------ narrated slots

_NARRATION_TASK = """\
You write the Key Insights paragraphs of a retail sales report for store and
area managers.

For each signal_id you receive a GROUNDED DRAFT that is already correct and
already passes every check. Rewrite it so a busy manager understands it at a
glance. You change wording only - never the facts.

A checker reads every paragraph you return. Any paragraph that breaks one rule
below is thrown away and the grounded draft is published instead:

- Start with one bold sentence (**...**) that says what changed and quotes its
  figure.
- Keep every figure exactly as it is written in the draft, including its sign,
  unit and rounding. Never calculate, re-round or add a figure.
- Keep every figure the draft gives for the change, the percentage, the
  starting and ending values and the share of the overall result, and for every
  reason it measures (units sold, purchases, revenue per item).
- Keep the comparison words, such as "from X to Y" and "compared with the same
  period last year".
- At most 105 words, at most 7 sentences, at most 28 words in any sentence.
- End with one sentence telling the reader what to check next.
- Never state a cause, never predict, never speculate. Purchases are
  purchases, not customers.
- Never use these words or phrases: {banned}.
- No emojis, no headings, no bullet points.

Return exactly one paragraph per signal_id you were given.
"""


def _banned_phrases() -> str:
    return ", ".join(f'"{phrase}"' for phrase in syn._TECHNICAL_MANAGER_PHRASES)


def narrate_key_insights(state: dict, signals: list[dict], fact_briefs: list[dict],
                         supported_numbers: list[float],
                         llm_factory: Callable[..., Any] | None = None,
                         log: Callable[[str], None] | None = None) -> tuple[dict, dict]:
    """Model-written Key Insights paragraphs, each checked alone, per-slot fallback.

    Returns ``({signal_id: paragraph}, stats)``. Never raises: any failure - the
    call, the schema, the check - leaves that slot on its grounded draft, so a
    narrated run can publish a plainer paragraph but never a worse one.

    One call writes every slot, with one repair round for the slots the check
    rejected, sending back the check's own reasons.
    """
    from pydantic import BaseModel, Field

    pairs = business_pairs(signals, fact_briefs)
    drafts: dict[str, str] = {}
    briefs: dict[str, dict] = {}
    for signal, brief in pairs:
        paragraph = grounded_paragraph(signal, brief)
        if paragraph:
            drafts[str(signal.get("id"))] = paragraph
            briefs[str(signal.get("id"))] = brief
    stats = {"slots": len(drafts), "authored": 0, "fallback": len(drafts), "rejected": [],
             "attempts": []}
    if not drafts:
        return drafts, stats
    from ..tools import ai_tier, authoring_attempts

    if ai_tier.code_slot(state, "key_insights"):
        stats["code_slot"] = True
        if log:
            log("Key Insights kept on the grounded drafts (narrated_code_slots lists key_insights) "
                "- no LLM call.")
        return drafts, stats

    usage_label = __name__.rsplit(".", 1)[-1]

    class _Paragraph(BaseModel):
        signal_id: str = Field(description="exact signal_id copied from the input")
        paragraph: str = Field(description="the rewritten paragraph, starting with a bold sentence")

    class _Paragraphs(BaseModel):
        paragraphs: list[_Paragraph]

    accepted: dict[str, str] = {}
    try:
        from ..tools import file_io
        from ..utils.json_utils import dumps

        if llm_factory is None:
            from ..tools.llm import get_llm as llm_factory  # noqa: N813
        system = (file_io.read_prompt("_global_rules.md") + file_io.business_rules_block(state)
                  + "\n\n" + _NARRATION_TASK.format(banned=_banned_phrases()))
        payload = [{"signal_id": sid, "segment": _segment(next(
                        s for s, _b in pairs if str(s.get("id")) == sid)),
                    "grounded_draft": draft}
                   for sid, draft in drafts.items()]
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": "GROUNDED DRAFTS:\n" + dumps(payload)}]
        llm = llm_factory(state, structured_schema=_Paragraphs)
        for attempt in (1, 2):
            since = authoring_attempts.mark(usage_label)
            try:
                result = llm.invoke(messages)
            except Exception as exc:
                stats["attempts"].append({
                    "attempt": attempt, "outcome": "call_failed",
                    "errors": [f"{type(exc).__name__}: {exc}"],
                    "usage": authoring_attempts.usage_since(usage_label, since)})
                raise
            items = result.paragraphs if hasattr(result, "paragraphs") else \
                [_Paragraph(**p) for p in (result or {}).get("paragraphs", [])]
            reasons: dict[str, list[str]] = {}
            accepted_before = set(accepted)
            for item in items:
                sid = str(item.signal_id)
                if sid not in drafts or sid in accepted:
                    continue
                issues = paragraph_issues(item.paragraph, briefs[sid], supported_numbers)
                if issues:
                    reasons[sid] = issues
                else:
                    accepted[sid] = item.paragraph.strip()
            stats["attempts"].append({
                "attempt": attempt, "returned": len(items),
                "accepted": [sid for sid in accepted if sid not in accepted_before],
                "rejected": [{"signal_id": sid, "issues": issues} for sid, issues in reasons.items()],
                "usage": authoring_attempts.usage_since(usage_label, since)})
            if reasons and log:
                log(f"Key Insights narration attempt {attempt}: {len(reasons)} paragraph(s) rejected - "
                    + "; ".join(f"{sid}: {', '.join(issues)}" for sid, issues in reasons.items()))
            missing = [sid for sid in drafts if sid not in accepted]
            if not missing or attempt == 2:
                stats["rejected"] = [{"signal_id": sid, "issues": reasons.get(sid, ["not returned"])}
                                     for sid in missing]
                break
            messages.append({"role": "assistant", "content": dumps(
                [{"signal_id": i.signal_id, "paragraph": i.paragraph} for i in items])})
            messages.append({"role": "user", "content": (
                "These paragraphs were rejected. Rewrite only them, fixing every reason, "
                "and start again from each grounded draft if in doubt:\n" + dumps(
                    [{"signal_id": sid, "reasons": reasons.get(sid, ["not returned"]),
                      "grounded_draft": drafts[sid]} for sid in missing]))})
    except Exception as exc:  # noqa: BLE001 - narration must never cost the report
        stats["error"] = f"{type(exc).__name__}: {exc}"
        if log:
            log(f"Key Insights narration failed ({stats['error']}); grounded drafts kept.")

    stats["authored"] = len(accepted)
    stats["fallback"] = len(drafts) - len(accepted)
    from ..tools import ai_tier
    authoring_attempts.record(state, usage_label, {
        "slot": "key_insights", "tier": ai_tier.tier(state),
        **{key: stats.get(key) for key in ("slots", "authored", "fallback", "rejected", "error")},
        "attempts": stats["attempts"],
    })
    return {sid: accepted.get(sid, draft) for sid, draft in drafts.items()}, stats


def _breakdowns(inv: dict) -> list[dict]:
    """The probes that returned rows: the gap scan's and, on the reasoned tier, the recipes'."""
    return [p for p in inv.get("probes") or []
            if p.get("tool") == "run_dax" and p.get("status") in ("success", "cache_hit") and "rows" in p]


_RECIPE_LABELS = {
    "breakdown": lambda a: f"breakdown of {a.get('segment')} by {a.get('by')}",
    "compare_to_peers": lambda a: f"comparison with every {a.get('level')}",
    "trend": lambda a: f"trend of {a.get('segment')}",
    "split_units_vs_price": lambda a: f"units versus revenue per unit for {a.get('segment')}",
    "measure_formula": lambda a: "formula of " + ", ".join(str(n) for n in (a.get("names") or [])),
    "custom_dax": lambda a: "custom query",
}


def _probe_line(probe: dict) -> str | None:
    """One Evidence Trail line: a gap-scan breakdown, or a reasoned-tier recipe call."""
    origin = str(probe.get("origin") or "")
    if origin == "gap_scan":
        return (f"  - Gap-scan breakdown by `{probe.get('dimension')}`: "
                f"{probe.get('row_count', 0)} row(s), {probe.get('completeness') or 'completeness unknown'}.")
    recipe = probe.get("recipe")
    if recipe not in _RECIPE_LABELS:
        return None  # conclude, closures and object listings are not evidence
    label = _RECIPE_LABELS[recipe](probe.get("args") or {})
    status = probe.get("status")
    if status in ("success", "cache_hit") and "rows" in probe:
        line = (f"  - Follow-up {label}: {probe.get('row_count', 0)} row(s), "
                f"{probe.get('completeness') or 'completeness unknown'}.")
        position = probe.get("position") or {}
        if position.get("rank"):
            line += f" {position.get('segment')} ranks {position['rank']} of {position.get('of')}."
        return line
    if status == "success":
        return f"  - Follow-up {label}: answered from rows already returned."
    return f"  - Follow-up {label}: not run ({probe.get('reason') or probe.get('error') or status})."


def write_report(state: dict, signals: list[dict], investigations: list[dict],
                 fact_briefs: list[dict], novelty: dict,
                 paragraphs: dict | None = None, authored: int = 0) -> str:
    """The insight report with the synthesizer's five sections.

    ``paragraphs`` carries narrated Key Insights by signal id; any slot without
    one uses its grounded draft. ``authored`` is how many a model wrote, so the
    caveat states what actually happened.
    """
    by_signal = {((inv.get("signal") or {}).get("id")): inv for inv in investigations or []}
    business = business_pairs(signals, fact_briefs)
    data_quality = [s for s in signals if s.get("kind") == "data_quality"]

    lines: list[str] = ["# Key Insights"]
    if not business:
        reason = (novelty or {}).get("reason") or "no_notable_findings"
        lines.append(_REASON_SENTENCES.get(reason, _REASON_SENTENCES["no_notable_findings"]))
    else:
        written = []
        for signal, brief in business:
            paragraph = (paragraphs or {}).get(str(signal.get("id"))) or grounded_paragraph(signal, brief)
            if paragraph:
                written.append(paragraph)
        lines.append("\n\n".join(written))

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
            line = _probe_line(probe)
            if line:
                lines.append(line)
        if inv.get("explanation"):
            lines.append(f"  - {inv['explanation']}")

    lines.append("")
    lines.append("# Confidence & Caveats")
    for signal, _brief in business:
        inv = by_signal.get(signal.get("id")) or {}
        checked = len(_breakdowns(inv))
        complete = int(inv.get("complete_breakdowns") or 0)
        if complete:
            lines.append(f"- {_segment(signal)}: {complete} of {checked} breakdown(s) came back complete.")
        else:
            lines.append(f"- {_segment(signal)}: no complete breakdown came back, so the finding "
                         f"is stated without a measured explanation.")
        # Reasoned tier only: why the published explanation is code's, not the model's.
        if inv.get("conclusion_issues"):
            lines.append(f"- {_segment(signal)}: the AI's written explanation did not pass the checks "
                         f"({inv['conclusion_issues'][0]}), so the code-written explanation is shown.")
        elif inv.get("error"):
            lines.append(f"- {_segment(signal)}: the AI investigation could not run, so the "
                         f"code-written explanation is shown.")
    asked = sum(int((by_signal.get(s.get("id")) or {}).get("follow_ups_answered") or 0)
                for s, _b in business)
    selected_by_model = (novelty or {}).get("selection") == "model"
    if business and (selected_by_model or asked):
        # The reasoned tier. Each part is said only when it happened: the signal
        # detector records whether a model selected, and the investigation
        # counts the follow-up questions the data answered.
        chooser = ("An AI model chose these findings from those that fixed rules detected and "
                   "ranked, and may have combined related findings into one"
                   if selected_by_model else
                   "Findings were chosen and ranked by fixed rules, and related findings are not combined")
        wording = (f"An AI model wrote the wording of {authored} of the {len(business)} key "
                   f"insight(s), and every figure in that wording was checked against the data."
                   if authored else "The wording was written by fixed rules.")
        follow = (f"An AI model asked {asked} follow-up question(s) of the data beyond the standard "
                  f"breakdowns, each through a checked query."
                  if asked else "No follow-up question was asked beyond the standard breakdowns.")
        lines.append(f"- {chooser}; every figure comes from the data and was checked by fixed rules. "
                     f"{wording} {follow}")
    elif authored:
        lines.append(f"- Findings were chosen, ranked and checked by fixed rules. An AI model wrote "
                     f"the wording of {authored} of the {len(business)} key insight(s), and every "
                     f"figure in that wording was checked against the data. Related findings are not "
                     f"combined, and no follow-up question was asked beyond the standard breakdowns.")
    else:
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
        incomplete = [p.get("dimension") for p in _breakdowns(inv)
                      if p.get("origin") in ("gap_scan", "recipe:breakdown")
                      and p.get("completeness") != "complete"]
        if incomplete:
            lines.append(f"- Which parts of {_segment(signal)} explain the change once the full breakdown "
                         f"is available? (by `{'`, `'.join(str(d) for d in incomplete)}`)")
        else:
            lines.append(f"- Which products inside {_segment(signal)} account for most of the change?")
    return "\n".join(lines).rstrip() + "\n"


def summary_numbers(**payload: Any) -> list[float]:
    """The synthesizer's supported-number set, for the clarity check."""
    return syn._supported_numbers(payload)
