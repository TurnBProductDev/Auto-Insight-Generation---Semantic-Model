"""Author one flexible, evidence-backed summary perspective.

This node consumes only summary candidates. It never reads insight candidates,
signals, investigations, reports, or memory.
"""

from __future__ import annotations

import calendar
import math
import re
from typing import Any, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..tools import file_io
from ..tools.llm import get_llm
from ..tools.summary_validation import chart_data_is_sufficient, validate_draft
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


class FreshSummaryBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["paragraph", "bullets", "chart"]
    heading: str = Field(
        default="",
        description="Optional professional heading chosen for this specific summary",
    )
    text: str = Field(default="", description="Body text when kind is paragraph")
    points: List[str] = Field(default_factory=list, description="Items when kind is bullets")
    chart_source_id: str = Field(
        default="",
        description="Exact available chart source id when kind is chart",
    )
    chart_type: Literal[
        "bar",
        "horizontal_bar",
        "lollipop",
        "waterfall",
        "line",
        "area",
        "donut",
        "scatter",
        "bubble",
        "heatmap",
        "grouped_bar",
    ] = Field(
        default="bar",
        description="Evidence-compatible chart type when kind is chart",
    )


class FreshSummaryDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str
    blocks: List[FreshSummaryBlock] = Field(
        description=(
            "The complete page plan in presentation order. Choose paragraphs, bullet groups, "
            "and charts freely from the evidence; there is no fixed template or chart count."
        )
    )
    covered_candidate_ids: List[str] = Field(
        description="Exact candidate ids actually represented in the summary"
    )


_CHANGE_WORDS = {"change", "growth", "variance", "delta", "decline", "increase", "decrease"}


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


def _plain_label(value: Any) -> str:
    text = str(value or "")
    if "[" in text and text.rstrip().endswith("]"):
        text = text.rsplit("[", 1)[-1].rstrip()[:-1]
    text = re.sub(r"[_\[\]]+", " ", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text[:1].upper() + text[1:] if text else "Value"


def _time_axis_label(value: Any, grain: Any) -> str:
    """Turn month-of-year codes into manager-facing month names.

    This is presentation-only: the evidence rows and DAX keep their original
    values. Other grains and non-month labels pass through unchanged.
    """
    text = str(value or "").strip()
    if str(grain or "").casefold() != "month":
        return text
    match = re.fullmatch(r"(?:month\s*)?0?([1-9]|1[0-2])(?:\.0+)?", text, re.IGNORECASE)
    return calendar.month_name[int(match.group(1))] if match else text


def _numeric_column(rows: list[dict], *, trend: bool = False) -> str | None:
    counts: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            if _number(value):
                counts[str(key)] = counts.get(str(key), 0) + 1
    eligible = [key for key, count in counts.items() if count >= 2]
    if not eligible:
        return None

    def score(key: str) -> tuple[int, str]:
        lowered = key.casefold()
        if trend:
            priorities = (
                ("revenue", "current"),
                ("sales", "current"),
                ("revenue",),
                ("sales",),
                ("current",),
                ("change",),
                ("growth",),
            )
        else:
            priorities = (
                ("revenue", "change"),
                ("sales", "change"),
                ("growth",),
                ("change",),
                ("revenue", "current"),
                ("sales", "current"),
                ("current",),
            )
        for index, tokens in enumerate(priorities):
            if all(token in lowered for token in tokens):
                return len(priorities) - index, key
        return 0, key

    return max(eligible, key=score)


def _numeric_columns(rows: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for row in rows:
        for key, value in row.items():
            if _number(value):
                counts[str(key)] = counts.get(str(key), 0) + 1
    eligible = [key for key, count in counts.items() if count >= 2]

    def priority(key: str) -> tuple[int, int, str]:
        lowered = key.casefold()
        semantic = 0
        for score, tokens in (
            (9, ("revenue", "current")),
            (9, ("sales", "current")),
            (8, ("revenue", "change")),
            (8, ("sales", "change")),
            (7, ("quantity", "current")),
            (7, ("unit", "current")),
            (6, ("transaction", "current")),
            (5, ("prior",)),
            (4, ("growth",)),
            (3, ("change",)),
        ):
            if all(token in lowered for token in tokens):
                semantic = score
                break
        # Percent columns remain available for heatmaps but rank after amounts.
        is_amount = 0 if "%" in key or "percent" in lowered or " pct" in lowered else 1
        return semantic, is_amount, key

    return sorted(eligible, key=priority, reverse=True)


def _row_key(rows: list[dict], requested: Any) -> str | None:
    if not rows:
        return None
    def normalized(value: Any) -> str:
        text = str(value or "").casefold().strip()
        if "[" in text and text.endswith("]"):
            text = text.rsplit("[", 1)[-1][:-1]
        return re.sub(r"[^a-z0-9]+", "", text)

    target = normalized(requested)
    keys = [str(key) for key in rows[0]]
    return next((key for key in keys if normalized(key) == target), None)


def _chart_source(
    source_id: str,
    title: str,
    value_label: str,
    labels: list[Any],
    values: list[Any],
    *,
    default_type: str,
    highlight: int | None = None,
    allow_donut: bool = False,
) -> dict | None:
    pairs = [
        (str(label), float(value))
        for label, value in zip(labels, values)
        if label not in (None, "") and _number(value)
    ]
    if len(pairs) < 2:
        return None
    if default_type == "line":
        allowed = ["line", "area", "bar"]
    else:
        allowed = ["bar", "horizontal_bar", "lollipop"]
        metric_text = f"{title} {value_label}".casefold()
        if any(token in metric_text for token in ("change", "growth", "variance", "delta")):
            allowed.append("waterfall")
    if allow_donut and default_type != "line" and all(value >= 0 for _, value in pairs):
        allowed.append("donut")
    return {
        "source_id": source_id,
        "title": title,
        "value_label": value_label,
        "labels": [label for label, _ in pairs],
        "values": [value for _, value in pairs],
        "allowed_chart_types": allowed,
        "default_chart_type": default_type if default_type in allowed else allowed[0],
        "highlight": highlight,
    }


def _multi_chart_source(
    source_id: str,
    title: str,
    labels: list[Any],
    rows: list[dict],
    numeric_columns: list[str],
) -> dict | None:
    columns = [column for column in numeric_columns if column][:4]
    points = []
    for label, row in zip(labels, rows):
        values = [row.get(column) for column in columns]
        if label in (None, "") or not all(_number(value) for value in values):
            continue
        points.append((str(label), [float(value) for value in values]))
    if len(points) < 2 or len(columns) < 2:
        return None

    allowed = ["scatter", "heatmap"]
    if len(columns) >= 3:
        allowed.append("bubble")
    series = [
        {
            "name": _plain_label(column),
            "values": [values[index] for _label, values in points],
        }
        for index, column in enumerate(columns)
    ]
    return {
        "source_id": source_id,
        "title": title,
        "value_label": "Multiple measures",
        "labels": [label for label, _values in points],
        "values": [],
        "x_label": _plain_label(columns[0]),
        "y_label": _plain_label(columns[1]),
        "size_label": _plain_label(columns[2]) if len(columns) >= 3 else "",
        "x_values": [values[0] for _label, values in points],
        "y_values": [values[1] for _label, values in points],
        "size_values": [values[2] for _label, values in points] if len(columns) >= 3 else [],
        "series": series,
        "allowed_chart_types": allowed,
        "default_chart_type": "bubble" if "bubble" in allowed else "scatter",
        "highlight": None,
    }


def _metric_family(column: str) -> str:
    lowered = str(column).casefold()
    for family, tokens in (
        ("revenue", ("revenue", "sales", "value", "amount")),
        ("quantity", ("quantity", "qty", "unit", "volume")),
        ("transactions", ("transaction", "bill")),
        ("rate", ("rate", "average", "avg")),
        ("percentage", ("percent", " pct", "%")),
    ):
        if any(token in lowered for token in tokens):
            return family
    return ""


def _grouped_chart_source(
    source_id: str,
    labels: list[Any],
    rows: list[dict],
    numeric_columns: list[str],
) -> dict | None:
    by_family: dict[str, list[str]] = {}
    for column in numeric_columns:
        family = _metric_family(column)
        if family:
            by_family.setdefault(family, []).append(column)
    families = [
        (family, columns[:4])
        for family, columns in by_family.items()
        if len(columns) >= 2
    ]
    if not families:
        return None
    family, columns = max(families, key=lambda item: (len(item[1]), item[0] == "revenue"))
    points = []
    for label, row in zip(labels, rows):
        values = [row.get(column) for column in columns]
        if label in (None, "") or not all(_number(value) and float(value) >= 0 for value in values):
            continue
        points.append((str(label), [float(value) for value in values]))
    if len(points) < 2:
        return None
    return {
        "source_id": source_id,
        "title": f"{family.title()} measures by business area",
        "value_label": family.title(),
        "labels": [label for label, _values in points],
        "values": [],
        "x_label": "",
        "y_label": "",
        "size_label": "",
        "x_values": [],
        "y_values": [],
        "size_values": [],
        "series": [
            {
                "name": _plain_label(column),
                "values": [values[index] for _label, values in points],
            }
            for index, column in enumerate(columns)
        ],
        "allowed_chart_types": ["grouped_bar"],
        "default_chart_type": "grouped_bar",
        "highlight": None,
    }


def _chart_sources(selected: list[dict]) -> list[dict]:
    """Build every chartable dataset from summary-owned evidence.

    The LLM chooses which of these datasets to show, how many to show, their
    order, and an allowed chart type. It never supplies chart values itself.
    """
    sources: list[dict] = []
    seen: set[str] = set()

    def add(source: dict | None) -> None:
        if source and source["source_id"] not in seen:
            seen.add(source["source_id"])
            sources.append(source)

    for candidate in selected:
        candidate_id = str(candidate.get("candidate_id") or "focus")
        visual = candidate.get("visual") or {}
        add(_chart_source(
            f"{candidate_id}:overview",
            str(visual.get("title") or candidate.get("title_hint") or "Supporting comparison"),
            str(visual.get("value_label") or "Value"),
            list(visual.get("labels") or []),
            list(visual.get("values") or []),
            default_type="line" if visual.get("type") == "line" else "bar",
            highlight=visual.get("highlight") if isinstance(visual.get("highlight"), int) else None,
        ))

        deep_dive = (candidate.get("evidence") or {}).get("deep_dive") or {}
        for index, section in enumerate(deep_dive.get("internal_contributors") or []):
            rows = list(section.get("rows") or [])
            label_key = _row_key(rows, section.get("dimension"))
            value_key = _numeric_column(rows)
            if label_key and value_key:
                add(_chart_source(
                    f"{candidate_id}:contributor:{index}",
                    f"{_plain_label(value_key)} by {_plain_label(label_key).lower()}",
                    _plain_label(value_key),
                    [row.get(label_key) for row in rows],
                    [row.get(value_key) for row in rows],
                    default_type="bar",
                    allow_donut=section.get("completeness") == "complete",
                ))
                add(_multi_chart_source(
                    f"{candidate_id}:contributor:{index}:multi",
                    f"Measure relationships by {_plain_label(label_key).lower()}",
                    [row.get(label_key) for row in rows],
                    rows,
                    _numeric_columns(rows),
                ))
                add(_grouped_chart_source(
                    f"{candidate_id}:contributor:{index}:grouped",
                    [row.get(label_key) for row in rows],
                    rows,
                    _numeric_columns(rows),
                ))

        location = deep_dive.get("location") or {}
        location_rows = list(location.get("rows") or [])
        location_key = _row_key(location_rows, location.get("dimension"))
        location_value = _numeric_column(location_rows)
        if location_key and location_value:
            add(_chart_source(
                f"{candidate_id}:location",
                f"{_plain_label(location_value)} by {_plain_label(location_key).lower()}",
                _plain_label(location_value),
                [row.get(location_key) for row in location_rows],
                [row.get(location_value) for row in location_rows],
                default_type="bar",
                allow_donut=location.get("completeness") == "complete",
            ))
            add(_multi_chart_source(
                f"{candidate_id}:location:multi",
                f"Measure relationships by {_plain_label(location_key).lower()}",
                [row.get(location_key) for row in location_rows],
                location_rows,
                _numeric_columns(location_rows),
            ))
            add(_grouped_chart_source(
                f"{candidate_id}:location:grouped",
                [row.get(location_key) for row in location_rows],
                location_rows,
                _numeric_columns(location_rows),
            ))

        trend = deep_dive.get("period_trend") or {}
        trend_rows = list(trend.get("rows") or [])
        trend_key = _row_key(trend_rows, trend.get("dimension"))
        trend_value = _numeric_column(trend_rows, trend=True)
        if trend_key and trend_value:
            trend_labels = [
                _time_axis_label(row.get(trend_key), trend.get("grain"))
                for row in trend_rows
            ]
            add(_chart_source(
                f"{candidate_id}:trend",
                f"{_plain_label(trend_value)} over time",
                _plain_label(trend_value),
                trend_labels,
                [row.get(trend_value) for row in trend_rows],
                default_type="line",
            ))
            add(_multi_chart_source(
                f"{candidate_id}:trend:multi",
                "Measure relationships over time",
                trend_labels,
                trend_rows,
                _numeric_columns(trend_rows),
            ))
            add(_grouped_chart_source(
                f"{candidate_id}:trend:grouped",
                trend_labels,
                trend_rows,
                _numeric_columns(trend_rows),
            ))
    return sources


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


def _fallback_chart_sources(sources: list[dict]) -> list[dict]:
    """Choose one useful default view per evidence purpose for the fallback.

    The source catalog contains alternative encodings (single, multi-measure,
    grouped) of the same dataset so the LLM can choose freely. A deterministic
    fallback must not render every alternative at once. Its chart count remains
    evidence-driven: overview, first chartable contributor, location and trend
    are included only when those datasets exist.
    """
    chosen: list[dict] = []

    def take(predicate) -> None:
        source = next((item for item in sources if predicate(str(item.get("source_id") or ""))), None)
        if source is not None and source not in chosen:
            chosen.append(source)

    take(lambda source_id: source_id.endswith(":overview"))
    take(lambda source_id: ":contributor:" in source_id and not source_id.endswith((":multi", ":grouped")))
    take(lambda source_id: source_id.endswith(":location"))
    take(lambda source_id: source_id.endswith(":trend"))
    return chosen


def _fallback(candidate: dict, period: dict, summary_type: str) -> dict:
    """Return a grounded flexible draft when LLM authoring fails."""
    del period, summary_type  # freshness remains code-owned metadata, not invented prose
    facts = _numeric_facts([candidate])
    focus_facts = [fact for fact in facts if str(fact.get("subject_role") or "") == "focus"] or facts

    def preferred(token: str) -> dict | None:
        matches = [fact for fact in focus_facts if token in str(fact.get("metric") or "").casefold()]
        return next((fact for fact in matches if fact.get("fact_kind") == "comparison"), None) or (
            matches[0] if matches else None
        )

    headline_fact = preferred("revenue") or (focus_facts[0] if focus_facts else None)
    headline = _headline_from_fact(candidate, [headline_fact] if headline_fact else [])

    driver_facts = [fact for fact in facts if fact.get("detail_role") == "driver"]
    contributor_facts = [fact for fact in facts if fact.get("detail_role") == "contributor"]
    # Required deep-dive facts lead the fallback narrative so strict validation
    # can never dead-end the branch. No generic risks/actions are manufactured.
    narrative_facts: list[dict] = []
    if contributor_facts:
        narrative_facts.append(contributor_facts[0])
    if driver_facts:
        narrative_facts.append(driver_facts[0])
    for fact in focus_facts:
        if fact not in narrative_facts:
            narrative_facts.append(fact)
    points: list[str] = []
    for fact in narrative_facts:
        point = str(fact.get("statement") or "").strip() or _fact_sentence(fact)
        if point and point not in points:
            points.append(point)

    blocks: list[dict] = []
    if points:
        blocks.append({
            "kind": "bullets",
            "heading": "Performance details",
            "text": "",
            "points": points,
            "chart_source_id": "",
            "chart_type": "bar",
        })
    for source in _fallback_chart_sources(_chart_sources([candidate])):
        blocks.append({
            "kind": "chart",
            "heading": source["title"],
            "text": "",
            "points": [],
            "chart_source_id": source["source_id"],
            "chart_type": source["default_chart_type"],
        })
    return {
        "headline": headline,
        "blocks": blocks,
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
        "content_blocks": [{
            "kind": "paragraph",
            "heading": "",
            "text": paragraphs[0],
            "points": [],
        }],
        # The public JSON payload remains backward compatible while the HTML
        # consumes content_blocks directly.
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


def _deep_dive_brief(deep_dive: dict | None) -> dict | None:
    """Compact, number-free navigation hints from the focus deep dive.

    Every figure still comes from ``supported_facts``; this only tells the model
    which child area, location and driver the deep dive actually resolved so it
    can build a focused, layered narrative instead of a flat one-liner.
    """
    if not isinstance(deep_dive, dict):
        return None
    contributors = deep_dive.get("internal_contributors") or []
    first = contributors[0] if contributors else {}
    location = deep_dive.get("location") or {}
    bridge = deep_dive.get("driver_bridge") or {}
    trend = deep_dive.get("period_trend") or {}
    brief = {
        "contributor_dimension": first.get("dimension"),
        "contributor_completeness": first.get("completeness"),
        "top_positive_contributor": (first.get("top_positive") or {}).get("member") if first else None,
        "top_negative_contributor": (first.get("top_negative") or {}).get("member") if first else None,
        "leading_store": (location.get("top_positive") or {}).get("member") if location else None,
        "main_driver": bridge.get("driver_class") if bridge else None,
        "trend_direction": trend.get("direction") if trend else None,
        "caveats": deep_dive.get("caveats") or [],
    }
    return {key: value for key, value in brief.items() if value not in (None, [], "")}


def _perspective_context(candidate: dict) -> dict:
    evidence = candidate.get("evidence") or {}
    return {
        "candidate_id": candidate.get("candidate_id"),
        "aspect": candidate.get("angle"),
        "focus_segment": candidate.get("segment") or None,
        "dimension_role": candidate.get("dimension_role"),
        "sentiment": candidate.get("sentiment") or (candidate.get("selection") or {}).get("sentiment"),
        "coverage": candidate.get("coverage"),
        "title_hint": candidate.get("title_hint"),
        "business_purpose": candidate.get("purpose"),
        "metadata": candidate.get("metadata_context") or {},
        "scope": evidence.get("scope") or {},
        "supported_facts": evidence.get("facts") or [],
        "deep_dive": _deep_dive_brief(evidence.get("deep_dive")),
    }


def _supported_fact_lines(selected: list[dict]) -> str:
    lines = []
    for candidate in selected:
        for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
            statement = str(fact.get("statement") or "").strip()
            if statement:
                lines.append(f"- {fact.get('fact_id')}: {statement}")
    return "\n".join(lines) or "- No numeric display facts are available; write qualitatively."


def _resolve_blocks(authored: dict, sources: list[dict]) -> list[dict]:
    by_id = {source["source_id"]: source for source in sources}
    blocks: list[dict] = []
    for raw in authored.get("blocks", []) or []:
        kind = str(raw.get("kind") or "").strip().casefold()
        heading = str(raw.get("heading") or "").strip()
        if kind == "paragraph":
            text = str(raw.get("text") or "").strip()
            if text:
                blocks.append({"kind": "paragraph", "heading": heading, "text": text, "points": []})
        elif kind == "bullets":
            points = [str(item).strip() for item in raw.get("points", []) or [] if str(item).strip()]
            if points:
                blocks.append({"kind": "bullets", "heading": heading, "text": "", "points": points})
        elif kind == "chart":
            source = by_id.get(str(raw.get("chart_source_id") or "").strip())
            chart_type = str(raw.get("chart_type") or "").strip().casefold()
            if source and chart_type in source["allowed_chart_types"]:
                chart = {
                    "source_id": source["source_id"],
                    "type": chart_type,
                    "title": heading or source["title"],
                    "value_label": source["value_label"],
                    "labels": list(source["labels"]),
                    "values": list(source["values"]),
                    "x_label": source.get("x_label") or "",
                    "y_label": source.get("y_label") or "",
                    "size_label": source.get("size_label") or "",
                    "x_values": list(source.get("x_values") or []),
                    "y_values": list(source.get("y_values") or []),
                    "size_values": list(source.get("size_values") or []),
                    "series": [dict(series) for series in source.get("series") or []],
                    "highlight": source.get("highlight"),
                }
                # Defense in depth: only resolved datasets that the final
                # validator/renderer can use are allowed into the page.
                if chart_data_is_sufficient(chart):
                    blocks.append({"kind": "chart", "heading": chart["title"], "text": "", "points": [], "chart": chart})
    return blocks


def _legacy_sections(blocks: list[dict]) -> list[dict]:
    """Project flexible narrative into the unchanged public summary API shape."""
    sections: list[dict] = []
    for block in blocks:
        if block.get("kind") == "paragraph" and block.get("text"):
            sections.append({
                "heading": str(block.get("heading") or "Summary"),
                "tone": "teal",
                "points": [str(block["text"])],
            })
        elif block.get("kind") == "bullets" and block.get("points"):
            sections.append({
                "heading": str(block.get("heading") or "Details"),
                "tone": "teal",
                "points": list(block["points"]),
            })
    return sections


def _overall_headline(overall_candidate: dict | None) -> str:
    """Business-level headline from the overall revenue comparison fact."""
    if not overall_candidate:
        return "Overall business performance"
    facts = _numeric_facts([overall_candidate])
    revenue = next(
        (fact for fact in facts
         if fact.get("fact_kind") == "comparison" and "revenue" in str(fact.get("metric") or "").casefold()),
        None,
    )
    return _headline_from_fact(overall_candidate, [revenue] if revenue else facts[:1])


def _grounded_points(candidate: dict, *, focus_only: bool = False, limit: int = 4) -> list[str]:
    """Verbatim supported-fact statements (never invented numbers)."""
    facts = _numeric_facts([candidate])
    if focus_only:
        facts = [fact for fact in facts if str(fact.get("subject_role") or "") == "focus"] or facts
    points: list[str] = []
    for fact in facts:
        statement = str(fact.get("statement") or "").strip() or _fact_sentence(fact)
        if statement and statement not in points:
            points.append(statement)
        if len(points) >= limit:
            break
    return points


def _chart_blocks(candidate: dict) -> list[dict]:
    blocks: list[dict] = []
    for source in _fallback_chart_sources(_chart_sources([candidate])):
        blocks.append({
            "kind": "chart", "heading": source["title"], "text": "", "points": [],
            "chart_source_id": source["source_id"], "chart_type": source["default_chart_type"],
        })
    return blocks


def _overall_group(overall_candidate: dict | None, overall_pkg: dict) -> list[dict]:
    """Overall Performance block (mandatory, first): grounded families + a
    qualitative volume/rate-mix driver line (no invented figures)."""
    if not overall_candidate:
        return [{
            "kind": "bullets", "heading": "Overall Performance", "text": "",
            "points": [
                "Overall business performance could not be confirmed from the available company-level evidence."
            ],
            "chart_source_id": "", "chart_type": "bar",
        }]
    points = _grounded_points(overall_candidate, limit=4)
    bridge = (overall_pkg or {}).get("bridge") or {}
    if bridge.get("reconciles"):
        volume = float(bridge.get("volume_effect") or 0.0)
        rate = float(bridge.get("rate_mix_effect") or 0.0)
        driver = "higher volume" if abs(volume) >= abs(rate) else "rate and mix"
        points.append(f"The revenue movement was driven mainly by {driver}.")
    block = {"kind": "bullets", "heading": "Overall Performance", "text": "",
             "points": points or ["Overall business performance for the period."],
             "chart_source_id": "", "chart_type": "bar"}
    return [block] + _chart_blocks(overall_candidate)


def _focus_group(merged_focus: dict) -> list[dict]:
    segment = str(merged_focus.get("segment") or "Focus area")
    facts = _numeric_facts([merged_focus])
    focus_facts = [fact for fact in facts if str(fact.get("subject_role") or "") == "focus"] or facts
    contributors = [fact for fact in facts if fact.get("detail_role") == "contributor"]
    drivers = [fact for fact in facts if fact.get("detail_role") == "driver"]
    ordered = [*(contributors[:1]), *(drivers[:1]), *focus_facts]
    points: list[str] = []
    for fact in ordered:
        statement = str(fact.get("statement") or "").strip() or _fact_sentence(fact)
        if statement and statement not in points:
            points.append(statement)
        if len(points) >= 4:
            break
    block = {"kind": "bullets", "heading": segment, "text": "",
             "points": points or [f"{segment} performance for the period."],
             "chart_source_id": "", "chart_type": "bar"}
    return [block] + _chart_blocks(merged_focus)


def _r4_fallback(state: dict, overall_candidate: dict | None, merged_focuses: list[dict]) -> dict:
    """Deterministic Overall-first multi-focus draft, grounded in supported facts."""
    overall_pkg = state.get("summary_overall_performance") or {}
    blocks: list[dict] = []
    covered: list[str] = []
    blocks += _overall_group(overall_candidate, overall_pkg)
    if overall_candidate:
        covered.append(overall_candidate.get("candidate_id"))
    for focus in merged_focuses:
        blocks += _focus_group(focus)
        covered.append(focus.get("candidate_id"))
    return {
        "headline": _overall_headline(overall_candidate),
        "blocks": blocks,
        "covered_candidate_ids": [cid for cid in covered if cid],
        "validation_status": "deterministic_fallback",
        "authoring_mode": "deterministic_fallback",
    }


def _merge_focus_evidence(focus: dict, evidence: dict) -> dict:
    """Attach the multi-focus deep-dive sections + facts onto a focus candidate."""
    base = focus.get("evidence") or {}
    return {**focus, "evidence": {
        **base,
        "deep_dive": (evidence or {}).get("sections") or base.get("deep_dive") or {},
        "facts": (evidence or {}).get("facts") or base.get("facts") or [],
    }}


def _merge_overall_evidence(overall: dict | None, package: dict) -> dict | None:
    """Expose the reconciled Overall trend through the existing chart catalog."""
    if not overall:
        return None
    base = overall.get("evidence") or {}
    deep_dive = dict(base.get("deep_dive") or {})
    trend = (package or {}).get("trend")
    if trend:
        deep_dive["period_trend"] = trend
    return {**overall, "evidence": {**base, "deep_dive": deep_dive}}


def _run_r4(state: dict, log: RunLogger, novelty: dict) -> dict:
    period = state.get("summary_period_context") or {}
    summary_type = str(novelty.get("summary_type") or "new_perspective")
    candidates = state.get("summary_candidates") or []
    overall_candidate = next((c for c in candidates if c.get("angle") == "overall_performance"), None)
    overall_candidate = _merge_overall_evidence(
        overall_candidate, state.get("summary_overall_performance") or {},
    )
    focuses = list(state.get("summary_selected_focuses") or [])
    evidence_by_key = state.get("summary_focus_evidence_by_key") or {}
    merged_focuses = [
        _merge_focus_evidence(focus, evidence_by_key.get(str(focus.get("focus_key"))) or {})
        for focus in focuses
    ]
    covered_set = ([overall_candidate] if overall_candidate else []) + merged_focuses
    if not covered_set:
        summary = _empty_summary(state, "no_new_perspective")
        log.info("Fresh summary (R4): no overall evidence or focus; empty summary.")
        return {"fresh_summary": summary, **log.updates()}

    if not state.get("summary_llm_authoring_enabled", True):
        authored = _r4_fallback(state, overall_candidate, merged_focuses)
        log.info("Balanced summary LLM authoring disabled; used deterministic fallback.")
    else:
        try:
            authored = _invoke(state, covered_set, mode="balanced_multi_focus")
        except Exception as exc:  # noqa: BLE001 - grounded fallback still delivers
            authored = _r4_fallback(state, overall_candidate, merged_focuses)
            log.error(
                "Balanced summary LLM draft failed validation; used deterministic fallback "
                f"({type(exc).__name__}: {exc})."
            )
    chart_sources = _chart_sources(covered_set) if state.get("summary_visual_enabled", True) else []
    blocks = _resolve_blocks(authored, chart_sources)
    sections = _legacy_sections(blocks)
    paragraphs = [
        text
        for block in blocks
        for text in (
            [str(block.get("text"))] if block.get("kind") == "paragraph" and block.get("text")
            else [str(point) for point in block.get("points", []) or []]
            if block.get("kind") == "bullets"
            else []
        )
    ]
    summary = {
        "summary_type": summary_type,
        "heading": str(authored.get("headline") or "Overall business performance").strip(),
        "paragraphs": paragraphs,
        "content_blocks": blocks,
        "sections": sections,
        "covered_candidate_ids": authored.get("covered_candidate_ids") or [],
        "covered_summary_keys": [c.get("summary_key") for c in covered_set if c.get("summary_key")],
        "metrics": [],
        "visual": None,
        "data_as_of": period.get("data_as_of"),
        "grain": period.get("grain") or "snapshot",
        "freshness_status": period.get("freshness_status") or "unknown",
        "period_anchor": period.get("period_anchor"),
        "validation_status": authored.get("validation_status") or "deterministic_fallback",
        "authoring_mode": authored.get("authoring_mode") or "deterministic_fallback",
        "overall_performance": state.get("summary_overall_performance") or {},
        "focuses": [
            {"focus_key": f.get("focus_key"), "segment": f.get("segment"),
             "dimension_role": f.get("dimension_role"), "lens": f.get("lens")}
            for f in focuses
        ],
    }
    # R3 additive public metadata, off by default (coordinated UI/API opt-in).
    if state.get("summary_focus_public_metadata"):
        summary["dailyFocuses"] = [
            {"segment": f.get("segment"), "role": f.get("dimension_role"),
             "lens": f.get("lens"), "sentiment": f.get("sentiment") or (f.get("selection") or {}).get("sentiment")}
            for f in focuses
        ]
    log.info(
        "Fresh summary (R4): Overall Performance + %d focus block-group(s) (mode=%s)."
        % (len(focuses), summary["authoring_mode"])
    )
    return {"fresh_summary": summary, **log.updates()}


def _invoke(state: dict, selected: list[dict], *, mode: str = "single_focus") -> dict:
    period = state.get("summary_period_context") or {}
    chart_sources = _chart_sources(selected) if state.get("summary_visual_enabled", True) else []
    rules = (
        file_io.read_prompt("_global_rules.md")
        + file_io.business_rules_block(state)
        + file_io.summary_business_rules_block(state)
    )
    task = file_io.read_prompt("fresh_summary_prompt.md")
    focus = state.get("summary_selected_focus") or {}
    context = {
        "summary_mode": mode,
        "report_context": state.get("report_understanding") or {},
        "reporting_period": period,
        # Mutable tone (R2): opportunity when the focus grew, risk when it fell.
        # It only guides framing; every figure still comes from supported_facts.
        "focus_sentiment": focus.get("sentiment"),
        "selected_perspectives": [_perspective_context(candidate) for candidate in selected],
        "available_chart_sources": chart_sources,
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
        errors = validate_draft(
            draft,
            selected,
            chart_sources=chart_sources,
            mode=mode,
            require_chart=bool(chart_sources),
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
                + "\n\nUse only these chart source ids and their allowed chart types:\n"
                + dumps([
                    {
                        "source_id": source["source_id"],
                        "allowed_chart_types": source["allowed_chart_types"],
                    }
                    for source in chart_sources
                ])
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
    # R4: Overall Performance first, then the selected focus portfolio. Runs even
    # with no focus (Overall Performance only).
    if state.get("summary_r4_enabled"):
        return _run_r4(state, log, novelty)
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
    chart_sources = _chart_sources(covered) if state.get("summary_visual_enabled", True) else []
    blocks = _resolve_blocks(authored, chart_sources)
    sections = _legacy_sections(blocks)
    paragraphs = [
        text
        for block in blocks
        for text in (
            [str(block.get("text"))] if block.get("kind") == "paragraph" and block.get("text")
            else [str(point) for point in block.get("points", []) or []]
            if block.get("kind") == "bullets"
            else []
        )
    ]
    summary = {
        "summary_type": summary_type,
        "heading": str(authored.get("headline") or primary.get("title_hint") or "Latest performance summary").strip(),
        # Kept privately for backward-compatible history readers; the public
        # app contract receives structured sections only.
        "paragraphs": paragraphs,
        "content_blocks": blocks,
        "sections": sections,
        "covered_candidate_ids": authored.get("covered_candidate_ids") or [],
        "covered_summary_keys": [item.get("summary_key") for item in covered if item.get("summary_key")],
        # KPI cards and the old single-chart field are intentionally empty. The
        # flexible HTML consumes evidence-resolved chart blocks instead.
        "metrics": [],
        "visual": None,
        "data_as_of": period.get("data_as_of"),
        "grain": period.get("grain") or "snapshot",
        "freshness_status": period.get("freshness_status") or "unknown",
        "period_anchor": period.get("period_anchor"),
        "validation_status": authored.get("validation_status") or "validated",
        "authoring_mode": authored.get("authoring_mode") or "llm",
    }
    focus = state.get("summary_selected_focus") or {}
    if focus.get("focus_key"):
        summary["focus"] = {
            "focus_key": focus.get("focus_key"),
            "segment": focus.get("segment"),
            "dimension_role": focus.get("dimension_role"),
            "lens": focus.get("lens"),
        }
    log.info(
        "Fresh summary: authored %s perspective %s (mode=%s%s)."
        % (summary_type, primary.get("candidate_id"), summary.get("authoring_mode"),
           f", focus={focus.get('segment')}" if focus.get("segment") else "")
    )
    return {"fresh_summary": summary, **log.updates()}
