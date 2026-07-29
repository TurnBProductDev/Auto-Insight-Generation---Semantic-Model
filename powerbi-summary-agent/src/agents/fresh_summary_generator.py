"""Author one short, evidence-backed summary perspective.

This node consumes only summary candidates. It never reads insight candidates,
signals, investigations, reports, or memory.
"""

from __future__ import annotations

import math
import re
from typing import Any, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..tools import file_io
from ..tools.llm import get_llm
from ..tools.summary_validation import validate_draft
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


class FreshSummaryMetricSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fact_id: str = Field(description="Exact supported fact id supplying this tile's value")
    label: str = Field(description="Short presentation label; do not include the value")


class FreshSummarySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: Literal["What's working", "Risks", "Recommended actions"]
    points: List[str]


class FreshSummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    metrics: List[FreshSummaryMetricSelection]
    sections: List[FreshSummarySection] = Field(
        description=(
            "Only evidence-supported sections, in presentation order; use an empty list when "
            "no section has a useful supported point"
        )
    )
    covered_candidate_ids: List[str] = Field(
        description="Exact candidate ids actually represented in the summary"
    )


_SECTION_TONES = {
    "what's working": "positive",
    "risks": "warning",
    "recommended actions": "info",
}
_CHANGE_WORDS = {"change", "growth", "variance", "delta", "decline", "increase", "decrease"}
_RISK_WORDS = {
    "out of stock", "stockout", "unwanted", "expired", "shortage", "decline", "loss", "risk"
}


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _numeric_facts(selected: list[dict]) -> list[dict]:
    facts: list[dict] = []
    seen: set[str] = set()
    for candidate in selected:
        for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
            fact_id = str(fact.get("fact_id") or "").strip()
            display = str(fact.get("display_value") or "").strip()
            if fact_id and display and fact_id not in seen and _number(fact.get("raw_value")):
                seen.add(fact_id)
                facts.append(fact)
    return facts


def _metric_label(fact: dict) -> str:
    subject = str(fact.get("subject") or "Overall").strip()
    metric = str(fact.get("metric") or "Value").strip()
    if subject.casefold() == "overall":
        return metric[:64]
    return f"{subject} {metric}"[:64]


def _metric_tone(fact: dict) -> str:
    raw = float(fact.get("raw_value") or 0.0)
    text = " ".join(
        str(fact.get(key) or "") for key in ("metric", "statement")
    ).casefold()
    if any(token in text for token in _RISK_WORDS) and raw > 0:
        return "critical" if any(token in text for token in ("out of stock", "expired")) else "warning"
    tokens = set(re.findall(r"[a-z]+", text))
    if tokens & _CHANGE_WORDS:
        return "positive" if raw > 0 else "warning" if raw < 0 else "teal"
    return "teal"


def _fact_sentence(fact: dict) -> str:
    subject = str(fact.get("subject") or "Overall").strip()
    metric = str(fact.get("metric") or "performance").strip()
    value = str(fact.get("display_value") or "").strip()
    if subject.casefold() == "overall":
        return f"{metric} was {value}."
    return f"{subject} recorded {value} for {metric.lower()}."


def _headline_from_fact(candidate: dict, facts: list[dict]) -> str:
    if not facts:
        return str(candidate.get("title_hint") or "Latest performance summary").strip()
    fact = facts[0]
    subject = str(fact.get("subject") or "Overall").strip()
    metric = str(fact.get("metric") or "performance").strip()
    value = str(fact.get("display_value") or "").strip()
    raw = float(fact.get("raw_value") or 0.0)
    tokens = set(re.findall(r"[a-z]+", metric.casefold()))
    prefix = "" if subject.casefold() == "overall" else f"{subject} "
    if tokens & _CHANGE_WORDS:
        base = re.sub(
            r"\b(change|growth|variance|delta|increase|decrease|decline)\b",
            "",
            metric,
            flags=re.IGNORECASE,
        ).strip() or "performance"
        direction = "increased" if raw > 0 else "decreased" if raw < 0 else "was unchanged"
        text = f"{prefix}{base} {direction}, a change of {value}."
    else:
        text = f"{prefix}{metric} was {value}."
    return text[:1].upper() + text[1:]


def _fact_direction(fact: dict) -> str:
    raw = float(fact.get("raw_value") or 0.0)
    text = " ".join(str(fact.get(key) or "") for key in ("metric", "statement")).casefold()
    if any(token in text for token in _RISK_WORDS) and raw > 0:
        return "risk"
    tokens = set(re.findall(r"[a-z]+", text))
    if tokens & _CHANGE_WORDS:
        return "working" if raw > 0 else "risk" if raw < 0 else "neutral"
    return "neutral"


def _fallback(candidate: dict, period: dict, summary_type: str) -> dict:
    """Return a complete, grounded structured draft when LLM authoring fails."""
    del period, summary_type  # freshness remains code-owned metadata, not invented prose
    facts = _numeric_facts([candidate])
    headline = _headline_from_fact(candidate, facts)
    metric_selections = [
        {"fact_id": fact["fact_id"], "label": _metric_label(fact)}
        for fact in facts[:4]
    ]
    working = [fact for fact in facts if _fact_direction(fact) == "working"]
    risks = [fact for fact in facts if _fact_direction(fact) == "risk"]
    working_points = [_fact_sentence(fact) for fact in working[:2]]
    risk_points = [_fact_sentence(fact) for fact in risks[:2]]

    dimension = str(candidate.get("dimension") or "").replace("_", " ").strip()
    action_points = []
    if risks:
        fact = risks[0]
        action_points.append(
            "Investigate the drivers behind "
            f"{str(fact.get('subject') or 'the reported segment')}'s "
            f"{str(fact.get('metric') or 'movement').lower()} of {fact.get('display_value')} "
            "and confirm whether it persists in the next reporting cycle."
        )
    elif dimension.casefold() not in {"", "business", "overall", "snapshot"}:
        action_points.append(
            f"Review the {dimension} breakdown to confirm which areas contributed most to the reported result."
        )

    sections = []
    if working_points:
        sections.append({"heading": "What's working", "points": working_points})
    if risk_points:
        sections.append({"heading": "Risks", "points": risk_points})
    if action_points:
        sections.append({"heading": "Recommended actions", "points": action_points[:3]})
    return {
        "headline": headline,
        "metrics": metric_selections,
        "sections": sections,
        "covered_candidate_ids": [candidate.get("candidate_id")],
        "validation_status": "deterministic_fallback",
        "authoring_mode": "deterministic_fallback",
    }


def _empty_summary(state: dict, kind: str) -> dict:
    period = state.get("summary_period_context") or {}
    data_as_of = period.get("data_as_of")
    if kind == "memory_unavailable":
        heading = "Summary temporarily unavailable"
        paragraphs = [
            "The previous-summary memory could not be read safely, so this run did not publish a perspective that might repeat an earlier summary."
        ]
    else:
        heading = "No materially new summary perspective"
        suffix = f" through {data_as_of}" if data_as_of else ""
        paragraphs = [
            f"The available reporting data{suffix} has not changed, and the useful descriptive perspectives for this period have already been covered."
        ]
    return {
        "summary_type": kind,
        "heading": heading,
        "paragraphs": paragraphs,
        "sections": [{"heading": "Summary", "tone": "teal", "points": paragraphs}],
        "covered_candidate_ids": [],
        "covered_summary_keys": [],
        "metrics": [],
        "visual": None,
        "data_as_of": data_as_of,
        "grain": period.get("grain") or "snapshot",
        "freshness_status": period.get("freshness_status") or "unknown",
        "period_anchor": period.get("period_anchor"),
        "validation_status": "deterministic",
        "authoring_mode": "deterministic",
    }


def _perspective_context(candidate: dict) -> dict:
    evidence = candidate.get("evidence") or {}
    return {
        "candidate_id": candidate.get("candidate_id"),
        "aspect": candidate.get("angle"),
        "title_hint": candidate.get("title_hint"),
        "business_purpose": candidate.get("purpose"),
        "metadata": candidate.get("metadata_context") or {},
        "scope": evidence.get("scope") or {},
        "supported_facts": evidence.get("facts") or [],
    }


def _supported_fact_lines(selected: list[dict]) -> str:
    lines = []
    for candidate in selected:
        for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
            statement = str(fact.get("statement") or "").strip()
            if statement:
                lines.append(f"- {fact.get('fact_id')}: {statement}")
    return "\n".join(lines) or "- No numeric display facts are available; write qualitatively."


def _resolve_metrics(authored: dict, selected: list[dict]) -> list[dict]:
    facts = {str(fact.get("fact_id")): fact for fact in _numeric_facts(selected)}
    metrics = []
    seen: set[str] = set()
    for selection in authored.get("metrics", []) or []:
        fact_id = str(selection.get("fact_id") or "").strip()
        fact = facts.get(fact_id)
        if not fact or fact_id in seen:
            continue
        seen.add(fact_id)
        metrics.append({
            "label": str(selection.get("label") or _metric_label(fact)).strip(),
            "value": str(fact.get("display_value") or "").strip(),
            "tone": _metric_tone(fact),
        })
        if len(metrics) >= 4:
            break
    return metrics


def _resolve_sections(authored: dict) -> list[dict]:
    sections = []
    for section in authored.get("sections", []) or []:
        heading = str(section.get("heading") or "").strip()
        points = [
            str(item).strip()
            for item in section.get("points", []) or []
            if str(item).strip()
        ]
        if heading and points:
            sections.append({
                "heading": heading,
                "tone": _SECTION_TONES.get(heading.casefold(), "teal"),
                "points": points[:3],
            })
    return sections


def _invoke(state: dict, selected: list[dict]) -> dict:
    period = state.get("summary_period_context") or {}
    rules = file_io.read_prompt("_global_rules.md") + file_io.business_rules_block(state)
    task = file_io.read_prompt("fresh_summary_prompt.md")
    context = {
        "report_context": state.get("report_understanding") or {},
        "reporting_period": period,
        "selected_perspectives": [_perspective_context(candidate) for candidate in selected],
        "metric_tile_count": min(4, len(_numeric_facts(selected))),
        "maximum_words": int(state.get("fresh_summary_max_words", 220)),
    }
    messages = [
        {"role": "system", "content": rules + "\n\n" + task},
        {"role": "user", "content": "SELECTED SUMMARY EVIDENCE:\n" + dumps(context)},
    ]
    last_errors = []
    for attempt in range(3):
        llm = get_llm(state, structured_schema=FreshSummaryDraft)
        response = llm.invoke(messages)
        draft = response.model_dump() if hasattr(response, "model_dump") else dict(response)
        errors = validate_draft(draft, selected)
        prose = [str(draft.get("headline") or "")]
        prose.extend(str(metric.get("label") or "") for metric in draft.get("metrics", []) or [])
        for section in draft.get("sections", []) or []:
            prose.append(str(section.get("heading") or ""))
            prose.extend(str(point or "") for point in section.get("points", []) or [])
        word_count = len(" ".join(prose).split())
        if word_count > int(state.get("fresh_summary_max_words", 220)):
            errors.append(
                f"draft is {word_count} words; maximum is {int(state.get('fresh_summary_max_words', 220))}"
            )
        if not errors:
            draft["validation_status"] = "validated"
            draft["authoring_mode"] = "llm"
            return draft
        last_errors = errors
        messages.append({"role": "assistant", "content": dumps(draft)})
        final_instruction = ""
        if attempt >= 1:
            final_instruction = (
                "\nThis is the final correction: if you cannot copy a supported display value exactly, "
                "omit that figure and describe the direction qualitatively. Do not approximate it yourself."
            )
        messages.append({
            "role": "user",
            "content": (
                "The draft above failed validation. Rewrite it as a polished business summary and return the schema again.\n"
                "Validation issues:\n- "
                + "\n- ".join(errors)
                + "\n\nThese are the only supported fact statements and signed display values:\n"
                + _supported_fact_lines(selected)
                + final_instruction
            ),
        })
    raise ValueError("; ".join(last_errors) or "fresh summary validation failed")


def run(state: dict) -> dict:
    log = RunLogger(state)
    novelty = state.get("summary_novelty") or {}
    eligible = list(state.get("summary_eligible_candidates") or [])

    if novelty.get("status") == "memory_unavailable":
        summary = _empty_summary(state, "memory_unavailable")
        log.error("Fresh summary generation skipped because summary memory is unavailable.")
        return {"fresh_summary": summary, **log.updates()}
    if not eligible:
        summary = _empty_summary(state, "no_new_perspective")
        log.info("Fresh summary: no unused material perspective; no summary LLM call made.")
        return {"fresh_summary": summary, **log.updates()}

    # One perspective per run gives the memory rotation a clear, stable unit.
    selected = eligible[:1]
    summary_type = str(novelty.get("summary_type") or "new_perspective")
    try:
        authored = _invoke(state, selected)
    except Exception as exc:  # noqa: BLE001 - a deterministic grounded fallback still delivers
        authored = _fallback(selected[0], state.get("summary_period_context") or {}, summary_type)
        log.error(f"Fresh summary LLM draft failed validation; used deterministic fallback ({type(exc).__name__}: {exc}).")

    by_id = {str(item.get("candidate_id")): item for item in selected}
    covered = [by_id[item] for item in authored.get("covered_candidate_ids", []) if item in by_id]
    if not covered:
        covered = selected
        authored["covered_candidate_ids"] = [selected[0].get("candidate_id")]
    period = state.get("summary_period_context") or {}
    primary = covered[0]
    metrics = _resolve_metrics(authored, covered)
    sections = _resolve_sections(authored)
    paragraphs = [
        point
        for section in sections
        for point in section.get("points", []) or []
    ]
    summary = {
        "summary_type": summary_type,
        "heading": str(authored.get("headline") or primary.get("title_hint") or "Latest performance summary").strip(),
        # Kept privately for backward-compatible history readers; the public
        # app contract receives structured sections only.
        "paragraphs": paragraphs,
        "sections": sections,
        "covered_candidate_ids": authored.get("covered_candidate_ids") or [],
        "covered_summary_keys": [item.get("summary_key") for item in covered if item.get("summary_key")],
        "metrics": metrics,
        "visual": primary.get("visual") if state.get("summary_visual_enabled", True) else None,
        "data_as_of": period.get("data_as_of"),
        "grain": period.get("grain") or "snapshot",
        "freshness_status": period.get("freshness_status") or "unknown",
        "period_anchor": period.get("period_anchor"),
        "validation_status": authored.get("validation_status") or "validated",
        "authoring_mode": authored.get("authoring_mode") or "llm",
    }
    log.info(
        "Fresh summary: authored %s perspective %s (mode=%s)."
        % (summary_type, primary.get("candidate_id"), summary.get("authoring_mode"))
    )
    return {"fresh_summary": summary, **log.updates()}
