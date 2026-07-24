"""Evidence-grounding checks for fresh summary prose."""

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


def validate_draft(draft: dict, selected: list[dict]) -> list[str]:
    errors = []
    heading = str(draft.get("heading") or "").strip()
    paragraphs = [str(item or "").strip() for item in draft.get("paragraphs", []) or [] if str(item or "").strip()]
    if not heading:
        errors.append("heading is empty")
    if not paragraphs:
        errors.append("summary content is empty")
    if heading.startswith("#") or any(paragraph.startswith(("#", "- ", "* ")) for paragraph in paragraphs):
        errors.append("Markdown formatting is not permitted in the structured summary text")
    selected_ids = {str(candidate.get("candidate_id")) for candidate in selected}
    covered = [str(item) for item in draft.get("covered_candidate_ids", []) or []]
    unknown = [item for item in covered if item not in selected_ids]
    if unknown:
        errors.append(f"unknown covered candidate ids: {unknown}")
    if selected and str(selected[0].get("candidate_id")) not in covered:
        errors.append("the primary selected perspective was not marked covered")
    errors.extend(validate_text("\n".join([heading, *paragraphs]), selected))
    return errors
