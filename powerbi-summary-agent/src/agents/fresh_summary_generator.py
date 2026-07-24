"""Author one short, evidence-backed summary perspective.

This node consumes only summary candidates. It never reads insight candidates,
signals, investigations, reports, or memory.
"""

from __future__ import annotations

import math
from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field

from ..tools import file_io
from ..tools.llm import get_llm
from ..tools.summary_validation import validate_draft
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


class FreshSummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str
    paragraphs: List[str]
    covered_candidate_ids: List[str] = Field(
        description="Exact candidate ids actually represented in the summary"
    )


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _fmt(value: Any, name: str = "") -> str:
    if not _number(value):
        return str(value)
    value = float(value)
    lowered = name.casefold()
    if "%" in name or "percent" in lowered or " pct" in lowered:
        value = value * 100 if abs(value) <= 1.5 else value
        return f"{value:+.1f}%"
    signed = any(token in lowered for token in ("growth", "change", "variance", "delta"))
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:{'+' if signed else ''}.2f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:{'+' if signed else ''}.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:{'+' if signed else ''}.1f}K"
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:{'+' if signed else ''},.1f}"


def _freshness_sentence(period: dict, summary_type: str) -> str:
    data_as_of = period.get("data_as_of")
    grain = str(period.get("grain") or "snapshot").replace("_", " ")
    freshness = period.get("freshness_status")
    if not data_as_of:
        return "The source does not expose a reliable business-data watermark."
    if summary_type == "new_perspective":
        return (
            f"The underlying {grain}-level data is unchanged and available through "
            f"{data_as_of}; this is a different view of that reporting period."
        )
    if freshness == "stale":
        return f"The underlying {grain}-level model is available through {data_as_of} and is currently stale."
    if freshness == "delayed":
        return f"The underlying {grain}-level model is available through {data_as_of} and is delayed."
    return ""


def _fallback(candidate: dict, period: dict, summary_type: str) -> dict:
    heading = str(candidate.get("title_hint") or "Latest performance summary")
    rows = (candidate.get("evidence") or {}).get("rows", []) or []
    dimension = str(candidate.get("dimension") or "segment").replace("_", " ")
    metric = str(candidate.get("metric") or "performance").replace("_", " ")
    paragraphs: list[str] = []

    visual = candidate.get("visual") or {}
    labels = visual.get("labels") or []
    values = visual.get("values") or []
    pairs = [(str(label), value) for label, value in zip(labels, values) if _number(value)]
    if pairs:
        display_metric = str(visual.get("value_label") or metric).replace("_", " ")
        by_label = {label.casefold(): (label, value) for label, value in pairs}
        if "current" in by_label and "prior" in by_label:
            current = by_label["current"]
            prior = by_label["prior"]
            movement = current[1] - prior[1]
            relation = "above" if movement > 0 else "below" if movement < 0 else "in line with"
            sentence = (
                f"Current {display_metric.lower()} was {_fmt(current[1], display_metric)}, "
                f"{relation} the prior value of {_fmt(prior[1], display_metric)}."
            )
            paragraphs.append(sentence)
            pairs = []
    if pairs:
        high = max(pairs, key=lambda item: item[1])
        low = min(pairs, key=lambda item: item[1])
        if high[0] == low[0]:
            sentence = f"{high[0]} recorded {_fmt(high[1], display_metric)} for {display_metric}."
        else:
            sentence = (
                f"Across the returned {dimension} values, {high[0]} recorded the highest "
                f"{display_metric} at {_fmt(high[1], display_metric)}, while {low[0]} recorded "
                f"{_fmt(low[1], display_metric)}."
            )
        paragraphs.append(sentence)
    elif rows:
        facts = []
        for key, value in rows[0].items():
            if _number(value):
                label = str(key).replace("_", " ").strip()
                if label.casefold().startswith("comparable "):
                    label = label[len("comparable "):]
                label = label.replace("QTY", "quantity").replace("Qty", "quantity")
                if label.casefold() == "bills growth":
                    label = "transaction growth"
                label = label.casefold()
                facts.append(f"{label} was {_fmt(value, str(key))}")
        if facts:
            chosen = facts[:3]
            if len(chosen) == 1:
                sentence = chosen[0]
            elif len(chosen) == 2:
                sentence = f"{chosen[0]} and {chosen[1]}"
            else:
                sentence = f"{chosen[0]}, {chosen[1]}, and {chosen[2]}"
            paragraphs.append(sentence[0].upper() + sentence[1:] + ".")
        else:
            paragraphs.append(str(candidate.get("purpose") or heading).rstrip(".") + ".")
    else:
        paragraphs.append(str(candidate.get("purpose") or heading).rstrip(".") + ".")

    freshness = _freshness_sentence(period, summary_type)
    if freshness:
        paragraphs.append(freshness)
    return {
        "heading": heading,
        "paragraphs": paragraphs,
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


def _invoke(state: dict, selected: list[dict]) -> dict:
    period = state.get("summary_period_context") or {}
    rules = file_io.read_prompt("_global_rules.md") + file_io.business_rules_block(state)
    task = file_io.read_prompt("fresh_summary_prompt.md")
    context = {
        "report_context": state.get("report_understanding") or {},
        "reporting_period": period,
        "selected_perspectives": [_perspective_context(candidate) for candidate in selected],
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
        word_count = len(
            " ".join([str(draft.get("heading") or ""), *(draft.get("paragraphs") or [])]).split()
        )
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
    summary = {
        "summary_type": summary_type,
        "heading": str(authored.get("heading") or primary.get("title_hint") or "Latest performance summary").strip(),
        "paragraphs": [str(item).strip() for item in authored.get("paragraphs", []) if str(item).strip()],
        "covered_candidate_ids": authored.get("covered_candidate_ids") or [],
        "covered_summary_keys": [item.get("summary_key") for item in covered if item.get("summary_key")],
        "metrics": primary.get("metrics") or [],
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
