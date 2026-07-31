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
_REMOVED_TEMPLATE_HEADINGS = {"what's working", "risks", "recommended actions"}
_TECHNICAL_MANAGER_PHRASES = {
    "accounted for",
    "associated with",
    "broader demand",
    "comparable",
    "directional",
    "growth engine",
    "linked to",
    "mix of products",
    "movement decomposition",
    "overall movement",
    "product pockets",
    "volume effect",
    "rate effect",
    "share of total change",
    "realized rate",
    "basket mix",
    "product mix",
    "sell-through",
    "materiality",
    "reconciliation",
    "total movement",
    "uplift",
    "z-score",
}
_EMPTY_SECTION_PHRASES = {
    "no clear risk",
    "no material downside",
    "no positive movement",
    "no risk was found",
    "nothing to report",
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def chart_data_is_sufficient(chart: dict | None) -> bool:
    """Return whether a resolved/source chart can render at least two points.

    Single-series, point, and matrix charts store their values differently.
    Keeping this contract in one place prevents pre-resolution validation,
    fallback resolution, and final validation from disagreeing—as happened
    when valid grouped bars were mistaken for empty single-series charts.
    """
    if not isinstance(chart, dict):
        return False
    chart_type = str(chart.get("type") or chart.get("default_chart_type") or "").casefold()
    labels = list(chart.get("labels") or [])
    if len(labels) < 2:
        return False

    if chart_type in {"scatter", "bubble"}:
        x_values = list(chart.get("x_values") or [])
        y_values = list(chart.get("y_values") or [])
        points = sum(
            1 for x_value, y_value in zip(x_values, y_values)
            if _finite(x_value) and _finite(y_value)
        )
        if points < 2:
            return False
        if chart_type == "bubble":
            sizes = list(chart.get("size_values") or [])
            if sum(1 for value in sizes[:min(len(x_values), len(y_values))] if _finite(value)) < 2:
                return False
        return True

    if chart_type in {"heatmap", "grouped_bar"}:
        series = [item for item in chart.get("series") or [] if isinstance(item, dict)]
        if len(series) < 2:
            return False
        return all(
            sum(1 for value in (item.get("values") or [])[:len(labels)] if _finite(value)) >= 2
            for item in series
        )

    values = list(chart.get("values") or [])
    return sum(1 for value in values[:len(labels)] if _finite(value)) >= 2


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


def _clean_blocks(draft: dict) -> list[dict]:
    raw = draft.get("blocks")
    if raw is None:
        raw = draft.get("content_blocks")
    if raw is not None:
        return [item for item in raw or [] if isinstance(item, dict)]
    # Legacy deterministic empty summaries still expose sections. Treat them as
    # bullet blocks so the validator remains backward compatible.
    return [
        {
            "kind": "bullets",
            "heading": item.get("heading"),
            "points": item.get("points") or [],
            "text": "",
        }
        for item in draft.get("sections", []) or []
        if isinstance(item, dict)
    ]


def _block_text(block: dict) -> list[str]:
    if str(block.get("kind") or "").casefold() == "paragraph":
        return [str(block.get("text") or "").strip()]
    if str(block.get("kind") or "").casefold() == "bullets":
        return [str(point).strip() for point in block.get("points", []) or [] if str(point).strip()]
    return []


def _first_point(blocks: list[dict]) -> str:
    for block in blocks:
        for text in _block_text(block):
            if text:
                return text
    return ""


_UNSUPPORTED_CAUSAL = re.compile(
    r"\b(?:because(?: of)?|caused by|due to|resulted from|as a result of|responsible for)\b",
    re.IGNORECASE,
)
_PARTIAL_AS_COMPLETE = re.compile(
    r"\b(?:all contributors|entire breakdown|complete breakdown|full picture|fully explains?|"
    r"every contributor|the total contribution)\b",
    re.IGNORECASE,
)


def _fact_used(fact: dict, draft: dict, all_text: str) -> bool:
    subject = str(fact.get("subject") or "").strip().casefold()
    display = str(fact.get("display_value") or "").strip().casefold()
    return bool(subject and display and subject in all_text and display in all_text)


def _driver_fact_used(fact: dict, draft: dict, all_text: str) -> bool:
    """Require the driver's figure and its business meaning in the narrative.

    Two bridge sides can legitimately have the same display value.  Checking
    only subject + number would then let one sentence satisfy both facts, so
    the bridge metric also supplies a small, generic semantic check.
    """
    if not _fact_used(fact, draft, all_text):
        return False
    metric = str(fact.get("metric") or "").casefold()
    if "volume" in metric or "quantity" in metric:
        return bool(re.search(r"\b(?:quantity|units?|items?|volume)\b", all_text))
    if "rate" in metric or "mix" in metric:
        return bool(re.search(r"\b(?:rate|mix)\b|average revenue per item", all_text))
    return True


def focus_rules(draft: dict, selected: list[dict]) -> list[str]:
    """Deterministic guards for the member-focus deep dive.

    These are enforced in addition to the shared checks whenever the primary
    selected perspective is a member focus (non-empty ``segment``). They are
    written to be satisfiable by the inherently-focused deterministic fallback,
    so strict validation can never dead-end the run. Broad foci (overall/period)
    and the legacy path carry no ``segment`` and skip these entirely.
    """
    errors: list[str] = []
    primary = selected[0] if selected else {}
    segment = str(primary.get("segment") or "").strip()
    if not segment:
        return errors

    facts = _facts(selected)
    headline = str(draft.get("headline") or draft.get("heading") or "")
    blocks = _clean_blocks(draft)
    first_point = _first_point(blocks)
    text_pieces = [headline, first_point] + [text for block in blocks for text in _block_text(block)]
    all_text = " ".join(text_pieces).casefold()
    segment_cf = segment.casefold()

    if segment_cf not in headline.casefold() and segment_cf not in first_point.casefold():
        errors.append(f"focus segment {segment!r} must appear in the headline or first point")

    driver_facts = [fact for fact in facts.values() if fact.get("detail_role") == "driver"]
    contributor_facts = [fact for fact in facts.values() if fact.get("detail_role") == "contributor"]
    missing_driver_facts = [
        fact for fact in driver_facts if not _driver_fact_used(fact, draft, all_text)
    ]
    if missing_driver_facts:
        errors.append("every available driver fact must be represented in the summary narrative")
    if contributor_facts and not any(_fact_used(fact, draft, all_text) for fact in contributor_facts):
        errors.append("an available contributor fact must be represented in the summary")

    peer_subjects = {
        str(fact.get("subject") or "").strip()
        for fact in facts.values()
        if str(fact.get("subject_role")) == "peer"
    }
    headline_cf = headline.casefold()
    # Do not mistake a shorter peer name for a second subject when it appears
    # only inside the exact selected focus name. Example: the peer
    # "FRESH CHICKEN" is nested inside "CF-FRESH CHICKEN & PARTS". Remove
    # the valid focus mention(s), then look for genuine peer mentions in what
    # remains; a peer repeated elsewhere in the headline is still rejected.
    headline_without_focus = re.sub(
        rf"(?<!\w){re.escape(segment_cf)}(?!\w)",
        " ",
        headline_cf,
    )
    for subject in peer_subjects:
        subject_cf = subject.casefold()
        if len(subject) > 2 and subject_cf != segment_cf and re.search(
            rf"(?<!\w){re.escape(subject_cf)}(?!\w)", headline_without_focus
        ):
            errors.append(f"headline names another member {subject!r}; keep the headline on the focus")
            break

    coverage = str(primary.get("coverage") or "")
    partial_detail = any(
        str(fact.get("coverage") or "") not in {"", "complete"}
        for fact in contributor_facts
    )
    if (coverage and coverage != "complete") or partial_detail:
        if "%" in all_text and re.search(r"\bof (?:the )?total\b", all_text):
            errors.append("partial evidence must not be described as a share of the total")
        if _PARTIAL_AS_COMPLETE.search(all_text):
            errors.append("partial evidence must not be described as a complete breakdown")

    excluded = {
        str(item).casefold()
        for item in ((primary.get("evidence") or {}).get("scope") or {}).get("excluded_entities", []) or []
        if str(item).strip()
    }
    for piece in text_pieces:
        piece_cf = piece.casefold()
        if "comparable" in piece_cf and any(member in piece_cf for member in excluded):
            errors.append("an excluded/current-only entity must not be described as comparable")
            break

    if _UNSUPPORTED_CAUSAL.search(all_text):
        errors.append("unsupported causal language is not permitted; describe measured contribution only")

    if "pure price" in all_text:
        errors.append("rate or mix effects must never be described as pure price")

    return errors


def portfolio_rules(draft: dict, selected: list[dict]) -> list[str]:
    """R4 guards: Overall first, then every selected business area covered.

    The page remains flexible after the mandatory opening section. These checks
    replace the single-focus headline rule, which would incorrectly force the
    first area into a company-level R4 headline.
    """
    errors: list[str] = []
    blocks = _clean_blocks(draft)
    if not blocks:
        return ["balanced summary has no content blocks"]
    first = blocks[0]
    if (
        str(first.get("kind") or "").casefold() not in {"paragraph", "bullets"}
        or str(first.get("heading") or "").strip().casefold() != "overall performance"
    ):
        errors.append("the first block must be a narrative section headed 'Overall Performance'")

    first_text = " ".join(
        [str(first.get("heading") or "").strip(), *_block_text(first)]
    ).casefold()

    headline = str(draft.get("headline") or draft.get("heading") or "")
    text_pieces = [headline]
    for block in blocks:
        heading = str(block.get("heading") or "").strip()
        if heading:
            text_pieces.append(heading)
        text_pieces.extend(_block_text(block))
    all_text = " ".join(text_pieces).casefold()

    overall = next(
        (candidate for candidate in selected if candidate.get("angle") == "overall_performance"),
        None,
    )
    overall_driver_facts = [
        fact for fact in ((overall or {}).get("evidence") or {}).get("facts", []) or []
        if isinstance(fact, dict)
        and fact.get("fact_kind") == "bridge"
        and fact.get("detail_role") == "driver"
    ]
    missing_overall_drivers = [
        fact for fact in overall_driver_facts
        if not _driver_fact_used(fact, draft, first_text)
    ]
    if missing_overall_drivers:
        errors.append(
            "every available overall driver fact must appear in the Overall Performance block"
        )

    focuses = [candidate for candidate in selected if str(candidate.get("segment") or "").strip()]
    for focus in focuses:
        segment = str(focus.get("segment") or "").strip()
        if segment.casefold() not in all_text:
            errors.append(f"selected focus area {segment!r} is missing from the summary")

        facts = [
            fact for fact in (focus.get("evidence") or {}).get("facts", []) or []
            if isinstance(fact, dict)
        ]
        driver_facts = [fact for fact in facts if fact.get("detail_role") == "driver"]
        contributor_facts = [fact for fact in facts if fact.get("detail_role") == "contributor"]
        missing_driver_facts = [
            fact for fact in driver_facts if not _driver_fact_used(fact, draft, all_text)
        ]
        if missing_driver_facts:
            errors.append(f"every available driver fact for {segment!r} must be represented")
        if contributor_facts and not any(_fact_used(fact, draft, all_text) for fact in contributor_facts):
            errors.append(f"an available contributor fact for {segment!r} must be represented")

        partial = str(focus.get("coverage") or "") not in {"", "complete"} or any(
            str(fact.get("coverage") or "") not in {"", "complete"}
            for fact in contributor_facts
        )
        if partial:
            if "%" in all_text and re.search(r"\bof (?:the )?total\b", all_text):
                errors.append("partial evidence must not be described as a share of the total")
            if _PARTIAL_AS_COMPLETE.search(all_text):
                errors.append("partial evidence must not be described as a complete breakdown")

    if _UNSUPPORTED_CAUSAL.search(all_text):
        errors.append("unsupported causal language is not permitted; describe measured contribution only")
    if "pure price" in all_text:
        errors.append("rate or mix effects must never be described as pure price")
    return errors


def validate_draft(
    draft: dict,
    selected: list[dict],
    *,
    chart_sources: list[dict] | None = None,
    mode: str = "single_focus",
    require_chart: bool = False,
) -> list[str]:
    """Validate flexible narrative/chart blocks without imposing a page template."""
    errors: list[str] = []
    headline = str(draft.get("headline") or draft.get("heading") or "").strip()
    headline_evidence = (
        [candidate for candidate in selected if candidate.get("angle") == "overall_performance"]
        if mode == "balanced_multi_focus"
        else selected
    )
    if not headline:
        errors.append("headline is empty")
    elif headline_evidence and _facts(headline_evidence) and not parse_numbers(headline):
        errors.append("headline must include the exact display value for its main result")

    if draft.get("metrics"):
        errors.append("KPI metric cards are not part of the flexible summary layout")

    blocks = _clean_blocks(draft)
    text_parts = [headline]
    narrative_count = 0
    chart_count = 0
    used_sources: set[str] = set()
    source_map = {
        str(source.get("source_id")): source
        for source in chart_sources or []
        if source.get("source_id")
    }
    for index, block in enumerate(blocks, start=1):
        kind = str(block.get("kind") or "").strip().casefold()
        heading = str(block.get("heading") or "").strip()
        if heading.casefold() in _REMOVED_TEMPLATE_HEADINGS:
            errors.append(f"fixed template heading {heading!r} is not permitted")
        if heading:
            text_parts.append(heading)

        if kind == "paragraph":
            text = str(block.get("text") or "").strip()
            if not text:
                errors.append(f"paragraph block {index} is empty")
            else:
                narrative_count += 1
                text_parts.append(text)
        elif kind == "bullets":
            points = [str(item).strip() for item in block.get("points", []) or [] if str(item).strip()]
            if not points:
                errors.append(f"bullet block {index} has no points")
            else:
                narrative_count += 1
                for point in points:
                    if any(phrase in point.casefold() for phrase in _EMPTY_SECTION_PHRASES):
                        errors.append(
                            f"bullet block {index} uses an empty placeholder; omit unsupported content"
                        )
                    text_parts.append(point)
        elif kind == "chart":
            chart_count += 1
            source_id = str(block.get("chart_source_id") or "").strip()
            chart_type = str(block.get("chart_type") or "").strip().casefold()
            resolved = block.get("chart") if isinstance(block.get("chart"), dict) else None
            if chart_sources is not None:
                source = source_map.get(source_id)
                if not source:
                    errors.append(f"chart block {index} uses unknown source id {source_id!r}")
                elif chart_type not in source.get("allowed_chart_types", []):
                    errors.append(
                        f"chart type {chart_type!r} is not allowed for source {source_id!r}"
                    )
                elif not chart_data_is_sufficient({**source, "type": chart_type}):
                    errors.append(f"chart block {index} has insufficient source data")
                if source_id in used_sources:
                    errors.append(f"chart source {source_id!r} is repeated")
                used_sources.add(source_id)
            elif not resolved:
                errors.append(f"resolved chart block {index} has no chart data")
            elif not chart_data_is_sufficient(resolved):
                errors.append(f"resolved chart block {index} has insufficient chart data")
        else:
            errors.append(f"block {index} has unsupported kind {kind!r}")

    if selected and narrative_count == 0:
        errors.append("summary must contain at least one evidence-backed paragraph or bullet group")
    elif not selected and not blocks:
        errors.append("summary content is empty")

    chart_ready = bool(chart_sources) and any(
        chart_data_is_sufficient(source) for source in chart_sources or []
    )
    if (require_chart or chart_ready) and chart_count == 0:
        errors.append("at least one evidence-backed chart is required when chart-ready data is available")

    formatted = [part for part in text_parts if part]
    if headline.startswith("#") or any(part.startswith(("#", "- ", "* ")) for part in formatted):
        errors.append("Markdown formatting is not permitted in structured summary text")
    manager_text = "\n".join(formatted).casefold()
    found_technical = sorted(phrase for phrase in _TECHNICAL_MANAGER_PHRASES if phrase in manager_text)
    if found_technical:
        errors.append("manager-facing summary uses analyst shorthand: " + ", ".join(found_technical))
    if re.search(
        r"\bmonths?\s+(?:0?[1-9]|1[0-2])(?:\s*(?:-|–|—|to|through)\s*(?:0?[1-9]|1[0-2]))?\b",
        manager_text,
    ):
        errors.append("use calendar month names instead of month numbers")
    bills_outside_intro = manager_text.replace("transactions (bills)", "transactions")
    if re.search(r"\bbills?\b", bills_outside_intro):
        errors.append("use transactions consistently; bills may appear only once as transactions (bills)")

    selected_ids = {str(candidate.get("candidate_id")) for candidate in selected}
    covered = [str(item) for item in draft.get("covered_candidate_ids", []) or []]
    unknown = [item for item in covered if item not in selected_ids]
    if unknown:
        errors.append(f"unknown covered candidate ids: {unknown}")
    if mode == "balanced_multi_focus":
        missing = sorted(selected_ids - set(covered))
        if missing:
            errors.append(f"selected perspectives were not marked covered: {missing}")
    elif selected and str(selected[0].get("candidate_id")) not in covered:
        errors.append("the primary selected perspective was not marked covered")

    errors.extend(validate_text("\n".join(formatted), selected))
    if mode == "balanced_multi_focus":
        errors.extend(portfolio_rules(draft, selected))
    else:
        errors.extend(focus_rules(draft, selected))
    return errors
