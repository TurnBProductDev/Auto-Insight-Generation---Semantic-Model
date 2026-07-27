"""Evidence-grounding and shape checks for structured fresh summaries."""

from __future__ import annotations

import math
import re
from typing import Any


_NUMBER = re.compile(
    r"(?<![A-Za-z0-9])(-?\d[\d,]*(?:\.\d+)?)\s*([KMB%]?)(?![A-Za-z])",
    re.IGNORECASE,
)
_EMOJI = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002700-\U000027BF"
    "]+",
    flags=re.UNICODE,
)
_SECTION_TONES = {
    "what's working": {"positive"},
    "risks": {"warning", "critical"},
    "recommended actions": {"info"},
}
_ACTION_VERBS = {
    "assess",
    "compare",
    "confirm",
    "investigate",
    "monitor",
    "prioritise",
    "prioritize",
    "review",
    "segment",
    "validate",
}
_TECHNICAL_MANAGER_PHRASES = {
    "movement decomposition",
    "volume effect",
    "rate effect",
    "share of total change",
    "realized rate",
    "basket mix",
    "product mix",
    "sell-through",
    "materiality",
    "reconciliation",
    "z-score",
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _walk_numbers(value: Any, name: str = ""):
    if _finite(value):
        yield float(value), name
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_numbers(item, str(key))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_numbers(item, name)


def evidence_numbers(candidates: list[dict]) -> list[float]:
    allowed = []
    for candidate in candidates:
        rows = (candidate.get("evidence") or {}).get("rows", []) or []
        if rows:
            allowed.append(float(len(rows)))
        for value, name in _walk_numbers(candidate.get("evidence", {})):
            allowed.append(value)
            lowered = name.casefold()
            if "%" in name or "percent" in lowered or " pct" in lowered:
                if abs(value) <= 2:
                    allowed.append(value * 100.0)
        for value, name in _walk_numbers(candidate.get("visual", {})):
            allowed.append(value)
        visual_values = (candidate.get("visual") or {}).get("values", []) or []
        if visual_values:
            allowed.append(float(len(visual_values)))
        for metric in candidate.get("metrics", []) or []:
            # Display strings are parsed below, so include their numeric meaning.
            for parsed, _, _ in parse_numbers(str(metric.get("value") or "")):
                allowed.append(parsed)
    return allowed


def parse_numbers(text: str) -> list[tuple[float, float, str]]:
    """Return ``(normalized value, rounding tolerance, original token)``."""
    out = []
    cleaned = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "", text or "")
    for match in _NUMBER.finditer(cleaned):
        raw, suffix = match.group(1), match.group(2).upper()
        token = match.group(0).strip()
        digits = raw.replace(",", "")
        try:
            value = float(digits)
        except ValueError:
            continue
        # ISO dates were removed above; ignore standalone calendar years.
        if not suffix and "." not in digits and 1900 <= abs(value) <= 2200:
            continue
        scale = {"K": 1_000.0, "M": 1_000_000.0, "B": 1_000_000_000.0}.get(suffix, 1.0)
        normalized = value * scale
        decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
        if suffix == "%":
            tolerance = 0.5 * (10 ** -decimals)
        elif suffix in {"K", "M", "B"}:
            tolerance = scale * 0.5 * (10 ** -decimals)
        else:
            tolerance = max(0.005 * abs(normalized), 0.5 * (10 ** -decimals))
        out.append((normalized, tolerance, token))
    return out


def validate_text(text: str, candidates: list[dict]) -> list[str]:
    errors = []
    if _EMOJI.search(text or ""):
        errors.append("emoji characters are not permitted")
    allowed = evidence_numbers(candidates)
    for value, tolerance, token in parse_numbers(text):
        if not any(abs(value - known) <= max(tolerance, abs(known) * 0.0005) for known in allowed):
            errors.append(f"figure {token!r} is not supported by selected summary evidence")
    return errors


def _facts(selected: list[dict]) -> dict[str, dict]:
    facts: dict[str, dict] = {}
    for candidate in selected:
        for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
            fact_id = str(fact.get("fact_id") or "").strip()
            if fact_id and str(fact.get("display_value") or "").strip():
                facts[fact_id] = fact
    return facts


def _clean_sections(draft: dict) -> list[dict]:
    return [item for item in draft.get("sections", []) or [] if isinstance(item, dict)]


def validate_draft(draft: dict, selected: list[dict]) -> list[str]:
    """Validate either an LLM draft or the materialized internal summary.

    LLM metric entries carry ``fact_id`` and no values/tones. The final internal
    summary carries code-injected ``value``/``tone`` fields. Both shapes are
    checked here so the final renderer cannot accidentally weaken the authoring
    contract.
    """
    errors = []
    headline = str(draft.get("headline") or draft.get("heading") or "").strip()
    if not headline:
        errors.append("headline is empty")
    elif selected and _facts(selected) and not parse_numbers(headline):
        errors.append(
            "headline must include the exact display value for its main result"
        )

    sections = _clean_sections(draft)
    headings: list[str] = []
    text_parts = [headline]
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        normalized = heading.casefold()
        headings.append(normalized)
        points = [
            str(item or "").strip()
            for item in section.get("points", []) or []
            if str(item or "").strip()
        ]
        if not heading:
            errors.append("a section heading is empty")
        if not points:
            errors.append(f"section {heading!r} has no points")
        if len(points) > 3:
            errors.append(f"section {heading!r} has more than 3 points")
        tone = str(section.get("tone") or "").strip().casefold()
        if tone and normalized in _SECTION_TONES and tone not in _SECTION_TONES[normalized]:
            errors.append(f"section {heading!r} has incompatible tone {tone!r}")
        if normalized == "recommended actions":
            for point in points:
                first = re.sub(r"[^A-Za-z].*$", "", point).casefold()
                if first not in _ACTION_VERBS:
                    errors.append(
                        "recommended actions must start with a safe follow-up verb "
                        f"({', '.join(sorted(_ACTION_VERBS))}); got {point!r}"
                    )
        text_parts.extend([heading, *points])

    if selected:
        expected = list(_SECTION_TONES)
        if headings != expected:
            errors.append(
                "sections must contain exactly What's working, Risks, and Recommended actions in that order"
            )
    elif not sections:
        errors.append("summary content is empty")

    metrics = [item for item in draft.get("metrics", []) or [] if isinstance(item, dict)]
    known_facts = _facts(selected)
    target_metrics = min(4, len(known_facts))
    if selected and len(metrics) != target_metrics:
        errors.append(
            f"metrics must contain exactly {target_metrics} supported tile(s) for this perspective"
        )
    seen_fact_ids: set[str] = set()
    seen_labels: set[str] = set()
    for metric in metrics:
        label = str(metric.get("label") or "").strip()
        fact_id = str(metric.get("fact_id") or "").strip()
        value = str(metric.get("value") or "").strip()
        if not label:
            errors.append("a metric label is empty")
        elif label.casefold() in seen_labels:
            errors.append(f"duplicate metric label: {label!r}")
        seen_labels.add(label.casefold())
        if fact_id:
            if fact_id not in known_facts:
                errors.append(f"unknown metric fact id: {fact_id!r}")
            if fact_id in seen_fact_ids:
                errors.append(f"duplicate metric fact id: {fact_id!r}")
            seen_fact_ids.add(fact_id)
        elif selected and not value:
            errors.append(f"metric {label!r} has neither a fact id nor a materialized value")
        text_parts.extend([label, value])

    formatted = [part for part in text_parts if part]
    if headline.startswith("#") or any(part.startswith(("#", "- ", "* ")) for part in formatted):
        errors.append("Markdown formatting is not permitted in the structured summary text")
    manager_text = "\n".join(formatted).casefold()
    found_technical = sorted(
        phrase for phrase in _TECHNICAL_MANAGER_PHRASES if phrase in manager_text
    )
    if found_technical:
        errors.append(
            "manager-facing summary uses analyst shorthand: "
            + ", ".join(found_technical)
        )
    bills_outside_intro = manager_text.replace("transactions (bills)", "transactions")
    if re.search(r"\bbills?\b", bills_outside_intro):
        errors.append(
            "use transactions consistently; bills may appear only once as transactions (bills)"
        )
    selected_ids = {str(candidate.get("candidate_id")) for candidate in selected}
    covered = [str(item) for item in draft.get("covered_candidate_ids", []) or []]
    unknown = [item for item in covered if item not in selected_ids]
    if unknown:
        errors.append(f"unknown covered candidate ids: {unknown}")
    if selected and str(selected[0].get("candidate_id")) not in covered:
        errors.append("the primary selected perspective was not marked covered")
    errors.extend(validate_text("\n".join(formatted), selected))
    return errors
