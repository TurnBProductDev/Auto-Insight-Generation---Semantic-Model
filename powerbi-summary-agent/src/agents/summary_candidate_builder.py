"""Build descriptive summary perspectives from summary-owned evidence only."""

from __future__ import annotations

import calendar
import math
import re
from typing import Any

from ..domains.sales import families as sales_families
from ..tools import file_io, summary_memory, summary_roles
from ..utils.logger import RunLogger


_WORDS = re.compile(r"[a-z0-9]+")
_TIME = {"date", "day", "week", "month", "quarter", "year", "period"}
_ENTITY = {"store", "branch", "outlet", "location", "region", "entity"}


def _tokens(*values) -> set[str]:
    return set(_WORDS.findall(" ".join(str(value or "") for value in values).casefold()))


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _source_queries(state: dict) -> list[dict]:
    clean = state.get("clean_summary_data") or {}
    queries = [q for q in clean.get("queries", []) or [] if q.get("status") == "success" and q.get("rows")]
    baseline = state.get("baseline_scope_evidence") or {}
    if baseline.get("status") == "success" and baseline.get("rows"):
        queries.append(baseline)
    coverage = state.get("baseline_coverage_clean_data") or {}
    queries.extend(
        q for q in coverage.get("queries", []) or []
        if q.get("status") == "success" and q.get("rows")
    )
    return queries


def _columns(rows: list[dict]) -> tuple[list[str], list[str]]:
    keys = list(dict.fromkeys(key for row in rows for key in row))
    numeric_dimensions = {
        key for key in keys
        if _tokens(key) & _TIME and len({row.get(key) for row in rows if row.get(key) is not None}) >= 2
    }
    numeric = [
        key for key in keys
        if key not in numeric_dimensions and any(_number(row.get(key)) for row in rows)
    ]
    labels = [key for key in keys if any(isinstance(row.get(key), str) and row.get(key).strip() for row in rows)]
    labels.extend(key for key in numeric_dimensions if key not in labels)
    return labels, numeric


def _family(name: str) -> str:
    """Label a returned column for keying and presentation.

    The vocabulary now has one owner (WP3): src/domains/sales/families.py, where
    it sits beside the profiler's - which is a *different* classifier, not a
    copy (37 of 56 real measure names classify differently). Re-sourced, not
    merged: merging would change candidate and memory keys on the live model.
    """
    return sales_families.candidate_family(_tokens(name))


def _metric_priority(name: str) -> tuple[int, int]:
    text = name.casefold()
    change = any(token in text for token in ("growth", "change", "variance", "delta"))
    pct = "%" in text or "percent" in text or " pct" in text
    current = any(token in text for token in ("current", "actual", "this year"))
    family = _family(name)
    family_score = {"revenue": 6, "profit": 5, "quantity": 4, "transactions": 3, "rate": 2}.get(family, 1)
    return ((30 if change and not pct else 20 if current else 10) + family_score, -len(name))


def _primary_metric(numeric: list[str]) -> str | None:
    return max(numeric, key=_metric_priority) if numeric else None


def _dimension(labels: list[str], query: dict, state: dict) -> str:
    purpose_tokens = _tokens(query.get("query_name"), query.get("purpose"))
    if purpose_tokens & {"overall", "grand", "total", "totals"}:
        return "overall"
    entity = ((state.get("semantic_model_profile") or {}).get("entity_dimension") or {}).get("column")
    if entity:
        for label in labels:
            if label.casefold() == str(entity).casefold():
                return label
    non_meta = [label for label in labels if "label" not in label.casefold()]
    if non_meta:
        return non_meta[0]
    for token in ("store", "category", "product", "division", "department", "region", "month", "date"):
        if token in purpose_tokens:
            return token
    return "overall"


def _angle(query: dict, rows: list[dict], dimension: str, numeric: list[str], r4_enabled: bool = False) -> str:
    dimension_tokens = _tokens(dimension)
    purpose_tokens = _tokens(query.get("query_name"), query.get("purpose"))
    toks = purpose_tokens | dimension_tokens
    if len(rows) == 1 and (dimension == "overall" or purpose_tokens & {"overall", "grand", "total", "totals"}):
        # Only a comparison-capable grand total is the mandatory Overall
        # Performance view. A current-only total (e.g. a newly opened branch
        # reported separately) is a supporting contribution note, not Overall.
        return "overall_performance" if _has_comparison_family(rows, numeric) else "overall_contribution"
    # Classify from the actual grouping column before reading generic scope words
    # in the query purpose.  For example, "category within the comparable branch
    # population" is a category perspective, not a store perspective.
    if dimension_tokens & _TIME:
        return "period_movement"
    if dimension_tokens & _ENTITY:
        return "store_overview"
    if "department" in dimension_tokens:
        # R4 splits Department into its own focus level; with R4 off it collapses
        # into Division exactly as before so legacy candidates/keys are unchanged.
        return "department_overview" if r4_enabled else "division_overview"
    if "division" in dimension_tokens:
        return "division_overview"
    if "category" in dimension_tokens:
        return "category_overview"
    if dimension_tokens & {"product", "item"}:
        return "product_overview"
    if purpose_tokens & _TIME:
        return "period_movement"
    if purpose_tokens & _ENTITY:
        return "store_overview"
    if "department" in purpose_tokens:
        return "department_overview" if r4_enabled else "division_overview"
    if "division" in purpose_tokens:
        return "division_overview"
    if "category" in purpose_tokens:
        return "category_overview"
    if purpose_tokens & {"product", "item"}:
        return "product_overview"
    families = {_family(name) for name in numeric}
    if "quantity" in families and "transactions" in families:
        return "volume_and_transactions"
    if any(token in toks for token in ("bottom", "decline", "negative", "loss")):
        return "largest_declines"
    return "business_breakdown"


def _clean_label(value: Any) -> str:
    text = " ".join(str(value or "").replace("_", " ").strip().split())
    replacements = {
        "store no": "Store",
        "qty": "Quantity",
        "bills": "Transactions",
        "growth": "change",
        "current year": "current",
        "past year": "prior",
        "net revenue": "Revenue",
        "net quantity": "Quantity",
    }
    lowered = text.casefold()
    for source, target in replacements.items():
        lowered = re.sub(rf"\b{re.escape(source)}\b", target, lowered, flags=re.IGNORECASE)
    return lowered[:1].upper() + lowered[1:]


def _subject_label(value: Any, label_col: str | None) -> str:
    """Humanize verified time members without model-specific field names."""
    text = str(value or "Overall").strip()
    if "month" in str(label_col or "").casefold():
        match = re.fullmatch(r"(?:[^=]*=\s*)?(\d{1,2})", text)
        if match and 1 <= int(match.group(1)) <= 12:
            return calendar.month_name[int(match.group(1))]
    return text


def _comparison_label(profile: dict | None, numeric: list[str]) -> str:
    """Resolve the baseline from metadata; never guess that prior means a year."""
    names = {str(name).casefold() for name in numeric}
    text_parts = list(names)
    bundles = []
    if isinstance(profile, dict):
        bundles.extend(profile.get("value_bundles") or [])
        bundles.extend(profile.get("volume_driver_bundles") or [])
        primary = profile.get("primary_value_bundle")
        if isinstance(primary, dict):
            bundles.append(primary)
    for bundle in bundles:
        measures = bundle.get("measures") or {}
        aliases = {
            str(measures.get(phase) or "").casefold()
            for phase in ("current", "prior", "change")
        }
        if not (aliases & names):
            continue
        text_parts.append(str(measures.get("prior") or ""))
        text_parts.append(str((bundle.get("derived") or {}).get("prior") or ""))
        for item in bundle.get("evidence") or []:
            if item.get("phase") != "prior":
                continue
            text_parts.extend(
                str(item.get(key) or "")
                for key in ("name", "description", "display_folder")
            )
            text_parts.extend(
                str(ref.get("column") or "") for ref in item.get("column_refs") or []
            )
    text = " ".join(text_parts).casefold()
    if re.search(
        r"\b(?:last|past|prior|previous)[ _-]?year\b|"
        r"(?:^|[^a-z0-9])(?:ly|py|yoy)(?:$|[^a-z0-9])",
        text,
    ):
        return "the same period last year"
    if re.search(r"\b(?:last|prior|previous)[ _-]?month\b", text):
        return "the previous month"
    if re.search(r"\b(?:last|prior|previous)[ _-]?week\b", text):
        return "the previous week"
    return "the stated comparison period"


def _is_comparison_metric(name: str) -> bool:
    return bool(_tokens(name) & {"growth", "change", "variance", "delta", "prior", "past", "previous"})


def _metric_phase(name: str) -> str | None:
    text = str(name or "").casefold()
    tokens = _tokens(name)
    is_pct = "%" in text or bool(tokens & {"percent", "percentage", "pct"})
    if is_pct and tokens & {"growth", "change", "variance", "delta"}:
        return "change_pct"
    if tokens & {"growth", "change", "variance", "delta"}:
        return "change"
    if tokens & {"current", "actual", "curr", "cy", "ty"} or "this year" in text:
        return "current"
    if tokens & {"prior", "past", "previous", "prev", "ly", "py"} or "last year" in text:
        return "prior"
    return None


def _has_comparison_family(rows: list[dict], numeric: list[str]) -> bool:
    """True when any metric family carries current plus prior/change.

    Overall Performance is a company-level *comparison* view. A single-row total
    that only exposes current-period measures (for example a newly opened branch
    shown separately from the like-for-like set) is a contribution note, not the
    mandatory comparison, and must never seize the Overall slot.
    """
    if not rows:
        return False
    families: dict[str, set[str]] = {}
    for name in numeric:
        phase = _metric_phase(name)
        family = _family(name)
        if phase and family != "performance":
            families.setdefault(family, set()).add(phase)
    return any(
        "current" in phases and ("prior" in phases or "change" in phases)
        for phases in families.values()
    )


def _comparison_facts(
    rows: list[dict],
    label_col: str | None,
    numeric: list[str],
    comparison_label: str = "the stated comparison period",
) -> list[dict]:
    """Derive manager-ready before/after/change/% facts from authoritative rows."""
    facts = []
    for row in rows[:2]:
        subject = _subject_label(row.get(label_col), label_col) if label_col else "Overall"
        families: dict[str, dict[str, str]] = {}
        for name in numeric:
            phase = _metric_phase(name)
            family = _family(name)
            if phase and family != "performance" and _number(row.get(name)):
                families.setdefault(family, {}).setdefault(phase, name)
        for family in ("revenue", "profit", "quantity", "transactions", "rate"):
            phases = families.get(family, {})
            current_name, prior_name = phases.get("current"), phases.get("prior")
            if not current_name or not prior_name:
                continue
            current, prior = float(row[current_name]), float(row[prior_name])
            change_name = phases.get("change")
            change = (
                float(row[change_name])
                if change_name and _number(row.get(change_name))
                else current - prior
            )
            pct = None if abs(prior) <= 1e-9 else (current - prior) / abs(prior) * 100.0
            direction = "increased" if change > 0 else "decreased" if change < 0 else "was unchanged"
            current_display = _format_number(current, current_name)
            prior_display = _format_number(prior, prior_name)
            change_display = _format_number(change, change_name or f"{family} change")
            pct_display = f"{abs(pct):.1f}%" if pct is not None else None
            facts.append({
                "fact_kind": "comparison",
                "subject": subject,
                "metric": f"{family.title()} comparison",
                "display_value": change_display,
                "raw_value": change,
                "current_value": current,
                "current_display": current_display,
                "prior_value": prior,
                "prior_display": prior_display,
                "change_value": change,
                "change_display": change_display,
                "change_pct": pct,
                "change_pct_display": pct_display,
                "comparison": comparison_label,
                "statement": (
                    f"{subject} - {family.title()} {direction} by {change_display}"
                    + (f" ({pct_display})" if pct_display else "")
                    + f", from {prior_display} to {current_display} compared with {comparison_label}"
                ),
            })
            if len(facts) >= 6:
                return facts
    return facts


def _scope_rows(
    rows: list[dict],
    dimension: str,
    numeric: list[str],
    state: dict,
    query: dict,
) -> tuple[list[dict], dict]:
    """Apply the resolved comparable population to entity comparisons.

    Scope discovery intentionally returns current-only entities.  Those rows are
    useful for discovering the population but must not be described as YoY
    growth.  Other already-scoped summary queries pass through unchanged.
    """
    resolved = state.get("resolved_entity_scope") or {}
    entity = ((state.get("semantic_model_profile") or {}).get("entity_dimension") or {}).get("column")
    active = [str(item) for item in resolved.get("active_comparable_population", []) or []]
    excluded = [str(item) for item in resolved.get("excluded_from_comparison", []) or []]
    contract = query.get("contract_hint") or {}
    population_status = str(contract.get("population_status") or "").strip()
    scope = {
        "population_status": population_status or "returned_rows",
        "comparable_entities": active,
        "excluded_entities": excluded,
        "note": "",
    }
    if (
        entity
        and str(dimension).casefold() == str(entity).casefold()
        and active
        and any(_is_comparison_metric(name) for name in numeric)
    ):
        allowed = {item.casefold() for item in active}
        filtered = [row for row in rows if str(row.get(dimension) or "").casefold() in allowed]
        entity_label = _clean_label(dimension).lower()
        if entity_label == "store":
            entity_label = "stores"
        elif not entity_label.endswith("s"):
            entity_label += "s"
        scope.update({
            "population_status": "resolved_comparable_population",
            "note": (
                f"Comparison includes {len(active)} active {entity_label} with both current and prior activity; "
                "current-only and prior-only entities are excluded."
            ),
        })
        return filtered, scope
    if "comparable" in population_status.casefold() or "comparable" in str(query.get("purpose") or "").casefold():
        scope["note"] = "The evidence is already filtered to the entities included in this comparison."
    return rows, scope


def _fact_sheet(
    rows: list[dict],
    labels: list[str],
    numeric: list[str],
    metric: str | None,
    scope: dict,
    comparison_label: str = "the stated comparison period",
) -> list[dict]:
    """Create compact, signed display facts for reliable LLM authoring."""
    if not rows:
        return []
    facts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    label_col = labels[0] if labels else None
    if metric:
        ranked = sorted(
            (row for row in rows if _number(row.get(metric))),
            key=lambda row: abs(float(row.get(metric))),
            reverse=True,
        )
    else:
        ranked = list(rows)

    # Cover the main movement/distribution and the two strongest supporting
    # metric families for the leading subjects.  Raw rows remain available to
    # deterministic validation, while the LLM is asked to copy display_value.
    selected_rows = ranked[:5] if label_col else ranked[:1]
    chosen_metrics = []
    if metric:
        chosen_metrics.append(metric)
    for name in sorted(numeric, key=_metric_priority, reverse=True):
        if name not in chosen_metrics:
            chosen_metrics.append(name)
        if len(chosen_metrics) >= 4:
            break
    for row_index, row in enumerate(selected_rows):
        subject = _subject_label(row.get(label_col), label_col) if label_col else "Overall"
        # The structured summary layout supports four evidence tiles. Keep four
        # distinct facts for the leading subject when the query exposes them;
        # later subjects stay bounded so the prompt remains compact.
        metric_limit = 4 if row_index == 0 else 3 if row_index == 1 else 1
        for name in chosen_metrics[:metric_limit]:
            value = row.get(name)
            marker = (subject.casefold(), name.casefold())
            if marker in seen or not _number(value):
                continue
            seen.add(marker)
            display = _format_number(float(value), name)
            facts.append({
                "fact_id": f"F{len(facts) + 1}",
                "subject": subject,
                "metric": _clean_label(name),
                "display_value": display,
                "raw_value": float(value),
                "statement": f"{subject} — {_clean_label(name)}: {display}",
            })
    for comparison in _comparison_facts(
        selected_rows, label_col, numeric, comparison_label
    ):
        comparison["fact_id"] = f"F{len(facts) + 1}"
        facts.append(comparison)
    if scope.get("note"):
        facts.append({
            "fact_id": f"F{len(facts) + 1}",
            "subject": "Scope",
            "metric": "Population",
            "display_value": "",
            "statement": scope["note"],
        })
    return facts


def _metadata_context(state: dict, dimension: str, metric: str | None, scope: dict) -> dict:
    profile = state.get("semantic_model_profile") or {}
    measure = (profile.get("measure_profiles") or {}).get(metric or "", {}) or {}
    return {
        "dimension": _clean_label(dimension),
        "metric": _clean_label(metric or "performance"),
        "metric_family": measure.get("family") or _family(metric or ""),
        "metric_phase": measure.get("phase"),
        "metric_description": measure.get("description") or "",
        "population_status": scope.get("population_status"),
        "scope_note": scope.get("note"),
    }


def _title(angle: str, dimension: str) -> str:
    labels = {
        "overall_performance": "Overall performance at a glance",
        "overall_contribution": "Current-period contribution shown separately",
        "period_movement": "How performance moved across the latest period",
        "store_overview": "How performance varied across stores",
        "division_overview": "How divisions shaped the latest result",
        "department_overview": "How departments shaped the latest result",
        "category_overview": "How categories shaped the latest result",
        "product_overview": "How products shaped the latest result",
        "volume_and_transactions": "How volume and transactions moved",
        "largest_declines": "Where the largest declines occurred",
        "business_breakdown": f"How performance varied by {_clean_label(dimension).lower()}",
    }
    return labels.get(angle, "Latest performance summary")


def _trim_rows(rows: list[dict], labels: list[str], numeric: list[str], metric: str | None) -> list[dict]:
    keep_numeric = []
    if metric:
        keep_numeric.append(metric)
    for key in sorted(numeric, key=_metric_priority, reverse=True):
        if key not in keep_numeric:
            keep_numeric.append(key)
        if len(keep_numeric) >= 6:
            break
    keep = labels[:2] + keep_numeric
    return [{key: row.get(key) for key in keep if key in row} for row in rows[:10]]


def _format_number(value: float, name: str = "") -> str:
    if not _number(value):
        return str(value)
    signed = bool(_tokens(name) & {"growth", "change", "variance", "delta"})
    sign = "+" if signed else ""
    if "%" in name or "percent" in name.casefold():
        pct = value * 100 if abs(value) <= 1.5 else value
        return f"{pct:{sign}.1f}%"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:{sign}.2f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:{sign}.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:{sign}.1f}K"
    if 0 < absolute < 0.01:
        return f"{value:{sign}.3f}"
    if absolute < 1:
        return f"{value:{sign}.2f}"
    return f"{value:{sign}.1f}" if value else "0"


def _metrics(rows: list[dict], numeric: list[str], angle: str) -> list[dict]:
    if angle != "overall_performance" or not rows:
        return []
    row = rows[0]
    chosen = sorted(numeric, key=_metric_priority, reverse=True)[:3]
    return [
        {"label": _clean_label(key), "value": _format_number(row.get(key), key), "tone": "teal"}
        for key in chosen if _number(row.get(key))
    ]


def _visual(
    rows: list[dict],
    labels: list[str],
    metric: str | None,
    angle: str,
    highlight_label: Any = None,
) -> dict | None:
    if angle == "overall_performance" and rows and metric:
        family = _family(metric)
        compatible = [key for key in rows[0] if _family(key) == family and _number(rows[0].get(key))]
        current = next(
            (key for key in compatible if any(token in key.casefold() for token in ("current", "actual", "this year"))),
            None,
        )
        prior = next(
            (key for key in compatible if any(token in key.casefold() for token in ("prior", "past", "previous", "last year"))),
            None,
        )
        if current and prior:
            return {
                "type": "bar",
                "title": f"{_clean_label(family).title()}: prior versus current",
                "labels": ["Prior", "Current"],
                "values": [float(rows[0][prior]), float(rows[0][current])],
                "value_label": _clean_label(family).title(),
            }
    if not labels or not metric or len(rows) < 2:
        return None
    label_col = labels[0]
    points = [
        (str(row.get(label_col)), float(row.get(metric)))
        for row in rows
        if row.get(label_col) not in (None, "") and _number(row.get(metric))
    ]
    if len(points) < 2:
        return None
    chart_type = "line" if angle == "period_movement" else "bar"
    if chart_type == "bar":
        points = sorted(points, key=lambda item: abs(item[1]), reverse=True)[:8]
    else:
        points = points[:12]
    visual = {
        "type": chart_type,
        "title": f"{_clean_label(metric)} by {_clean_label(label_col).lower()}",
        "labels": [label for label, _ in points],
        "values": [value for _, value in points],
        "value_label": _clean_label(metric),
    }
    if highlight_label is not None:
        target = str(highlight_label)
        for index, (label, _value) in enumerate(points):
            if label == target:
                visual["highlight"] = index
                break
    return visual


# Breakdown angles whose returned rows can be re-sliced into per-member focus
# candidates (a member-bearing dimension with a label column and >=2 rows).
_MEMBER_ANGLES = {
    "store_overview",
    "division_overview",
    "department_overview",
    "category_overview",
    "product_overview",
    "business_breakdown",
    "largest_declines",
}


def _finalize(candidate: dict, dataset: str, anchor: str) -> dict:
    """Stamp the two stable identities and a candidate id onto a candidate."""
    key, _ = summary_memory.story_components(candidate, dataset, anchor)
    focus_key, _ = summary_memory.focus_components(candidate, dataset)
    area_key, _ = summary_memory.area_components(candidate, dataset)
    candidate["summary_key"] = key
    candidate["focus_key"] = focus_key
    candidate["area_key"] = area_key
    candidate["candidate_id"] = f"summary_{key.rsplit(':', 1)[-1][:12]}"
    return candidate


def _member_materiality(row: dict, numeric: list[str], metric: str | None) -> float:
    """Signed change vs prior for the leading comparison family (never a sum)."""
    families: dict[str, dict[str, str]] = {}
    for name in numeric:
        phase = _metric_phase(name)
        family = _family(name)
        if phase and family != "performance" and _number(row.get(name)):
            families.setdefault(family, {}).setdefault(phase, name)
    for family in ("revenue", "profit", "quantity", "transactions", "rate"):
        phases = families.get(family, {})
        change_name = phases.get("change")
        if change_name and _number(row.get(change_name)):
            return float(row[change_name])
        current_name, prior_name = phases.get("current"), phases.get("prior")
        if current_name and prior_name and _number(row.get(current_name)) and _number(row.get(prior_name)):
            return float(row[current_name]) - float(row[prior_name])
    return float(row[metric]) if metric and _number(row.get(metric)) else 0.0


def _change_pct(rows: list[dict], numeric: list[str]) -> float | None:
    """Aggregate percent change vs prior for the leading comparison family.

    Summed over ``rows`` so it works for a single member row and for a
    multi-row grand total alike; ``None`` when no reconcilable prior exists.
    This is the magnitude signal the R2 override lane reads.
    """
    families: dict[str, dict[str, str]] = {}
    for name in numeric:
        phase = _metric_phase(name)
        family = _family(name)
        if phase and family != "performance":
            families.setdefault(family, {}).setdefault(phase, name)
    for family in ("revenue", "profit", "quantity", "transactions", "rate"):
        phases = families.get(family, {})
        current_name, prior_name, change_name = phases.get("current"), phases.get("prior"), phases.get("change")
        if not current_name:
            continue
        current = sum(float(row[current_name]) for row in rows if _number(row.get(current_name)))
        prior = None
        if prior_name:
            prior = sum(float(row[prior_name]) for row in rows if _number(row.get(prior_name)))
        elif change_name:
            change = sum(float(row[change_name]) for row in rows if _number(row.get(change_name)))
            prior = current - change
        if prior is not None and abs(prior) > 1e-9:
            return (current - prior) / abs(prior) * 100.0
    return None


def _dimension_role(angle: str, dimension: str, state: dict) -> str:
    role = summary_memory._role_from_angle(angle, dimension)
    entity = ((state.get("semantic_model_profile") or {}).get("entity_dimension") or {}).get("column")
    if entity and str(dimension).casefold() == str(entity).casefold():
        return "store"
    # Apply configured role aliases so another model's equivalent hierarchy
    # (e.g. business_unit -> division) resolves to a canonical focus role. With
    # no aliases configured this only normalizes the role, leaving it unchanged.
    return summary_roles.canonical_role(role, dimension, state)


def _resolve_ref(state: dict, column_name: Any) -> str | None:
    """Resolve a bare column name to a fully-qualified 'Table'[Column] reference."""
    if not column_name:
        return None
    target = str(column_name).casefold()
    profile = state.get("semantic_model_profile") or {}
    pools = [profile.get("dimensions") or [], profile.get("time_dimensions") or []]
    entity = profile.get("entity_dimension")
    if entity:
        pools.append([entity])
    for pool in pools:
        for dim in pool:
            if str(dim.get("column") or "").casefold() == target and dim.get("reference"):
                return dim["reference"]
    for col in (state.get("model_metadata") or {}).get("columns", []) or []:
        if str(col.get("column") or "").casefold() == target:
            table = str(col.get("table") or "")
            return "'" + table.replace("'", "''") + f"'[{col.get('column')}]"
    return None


def _member_coverage(segment: str, dimension: str, numeric: list[str], state: dict) -> str:
    """Member candidates reuse returned rows: partial, or invalid if excluded."""
    resolved = state.get("resolved_entity_scope") or {}
    entity = ((state.get("semantic_model_profile") or {}).get("entity_dimension") or {}).get("column")
    if entity and str(dimension).casefold() == str(entity).casefold():
        excluded = {str(item).casefold() for item in resolved.get("excluded_from_comparison", []) or []}
        active = {str(item).casefold() for item in resolved.get("active_comparable_population", []) or []}
        if any(_is_comparison_metric(name) for name in numeric):
            if str(segment).casefold() in excluded:
                return "invalid"
            if active and str(segment).casefold() not in active:
                return "invalid"
    return "partial"


def _tag_facts(facts: list[dict], focus_subject: str | None, coverage: str) -> list[dict]:
    """Tag facts with subject_role/coverage.

    ``focus_subject=None`` marks every non-scope fact as ``focus`` (used for
    broad candidates that describe a whole returned set rather than one member).
    """
    for fact in facts:
        subject = str(fact.get("subject") or "")
        if subject == "Scope":
            fact["subject_role"] = "scope"
            fact["coverage"] = None
        elif focus_subject is None or subject == focus_subject:
            fact["subject_role"] = "focus"
            fact["coverage"] = coverage
        else:
            fact["subject_role"] = "peer"
            fact["coverage"] = "partial"
    return facts


def _member_candidate(
    state: dict,
    query: dict,
    angle: str,
    dimension: str,
    dimension_role: str,
    all_rows: list[dict],
    labels: list[str],
    numeric: list[str],
    metric: str | None,
    metric_family: str,
    comparison: str,
    scope: dict,
    focus_row: dict,
    peer_rows: list[dict],
    label_col: str,
    anchor: str,
    dataset: str,
) -> dict:
    segment_raw = focus_row.get(label_col)
    segment = _subject_label(segment_raw, label_col)
    coverage = _member_coverage(str(segment_raw or ""), dimension, numeric, state)
    materiality = _member_materiality(focus_row, numeric, metric)
    ordered = [focus_row, *peer_rows[:2]]
    facts = _tag_facts(
        _fact_sheet(ordered, labels, numeric, metric, scope, comparison),
        segment,
        coverage,
    )
    role_label = _clean_label(dimension).lower() or dimension_role
    candidate = {
        "candidate_id": "",
        "summary_key": "",
        "focus_key": "",
        "angle": angle,
        "candidate_kind": "member",
        "dimension_role": dimension_role,
        "lens": summary_memory._lens_from_angle(angle),
        "coverage": coverage,
        "title_hint": f"How {segment} performed",
        "purpose": f"Focus on {segment} within the {role_label} breakdown",
        "query_name": query.get("query_name"),
        "dimension": dimension,
        "dimension_ref": _resolve_ref(state, label_col) or _resolve_ref(state, dimension),
        "member_value": segment_raw,
        "segment": segment,
        # Leaf-only path for the legacy re-slice; the universe node supplies the
        # full Division -> Department -> Category ancestry when it builds the
        # candidate so identically named members under different parents differ.
        "hierarchy_path": [segment],
        "metric": metric,
        "metric_family": metric_family,
        "direction": "increase" if materiality > 0 else "decrease" if materiality < 0 else "flat",
        "observation_value": materiality,
        "materiality": materiality,
        "change_pct": _change_pct([focus_row], numeric),
        "score": 40.0 + min(9.0, math.log10(abs(materiality) + 1.0)),
        "period_anchor": anchor,
        "evidence": {
            "rows": _trim_rows(ordered, labels, numeric, metric),
            "coverage": coverage,
            "scope": scope,
            "facts": facts,
        },
        "metadata_context": {
            **_metadata_context(state, dimension, metric, scope),
            "segment": segment,
        },
        "metrics": [],
        "visual": _visual(all_rows, labels, metric, angle, highlight_label=segment_raw),
    }
    return _finalize(candidate, dataset, anchor)


_UNIVERSE_ANGLE = {
    "division": "division_overview",
    "department": "department_overview",
    "category": "category_overview",
}


def _universe_member_candidates(state: dict, dataset: str, anchor: str) -> list[dict]:
    """Build rotation member candidates from the deterministic focus universe.

    Each universe member carries the validated per-parent materiality diagnostics
    (current/prior/change + overall_current/gross_sibling_change/... ) that the
    portfolio selector reads. These are the PRIMARY rotation candidates in R4;
    they dedup above any LLM-planned re-slice for the same member via a higher
    base score, so selection never depends on what the planner happened to ask.
    """
    universe = state.get("summary_focus_universe") or {}
    if str(universe.get("status")) != "ok":
        return []
    candidates: list[dict] = []
    for role, info in (universe.get("roles") or {}).items():
        if str(info.get("status")) != "ok":
            continue
        # Coverage-only levels (store, and any covered level that is not
        # focus-eligible) are reported as ranked coverage rows, never rotated as
        # a daily focus. Skipping them here keeps them out of the candidate pool
        # and out of focus memory entirely, rather than relying on the
        # portfolio's downstream role filter.
        if info.get("coverage_only"):
            continue
        group_col = info.get("column") or role
        metric_family = info.get("metric_family") or universe.get("metric_family") or "revenue"
        angle = _UNIVERSE_ANGLE.get(role, "business_breakdown")
        lens = summary_memory._lens_from_angle(angle)
        dimension_ref = _resolve_ref(state, group_col)
        for member in info.get("members") or []:
            raw = member.get("member")
            if not str(raw or "").strip():
                continue
            segment = _subject_label(raw, group_col)
            change = member.get("change")
            change_val = change if _number(change) else 0.0
            direction = "increase" if change_val > 0 else "decrease" if change_val < 0 else "flat"
            path = member.get("hierarchy_path") or [segment]
            current, prior = member.get("current"), member.get("prior")
            fact = {
                "fact_id": "F1",
                "fact_kind": "comparison",
                "subject": segment,
                "subject_role": "focus",
                "coverage": "partial",
                "metric": f"{metric_family.title()} comparison",
                "current_value": current,
                "prior_value": prior,
                "change_value": change,
                "change_pct": member.get("change_pct"),
                "raw_value": change,
                "statement": f"{segment} - {metric_family.title()} change of {_format_number(change_val, f'{metric_family} change')}",
            }
            candidate = {
                "candidate_id": "",
                "summary_key": "",
                "focus_key": "",
                "area_key": "",
                "angle": angle,
                "candidate_kind": "member",
                "candidate_source": "universe",
                "dimension_role": role,
                "lens": lens,
                "coverage": "partial",
                "title_hint": f"How {segment} performed",
                "purpose": f"Focus on {segment} within the {_clean_label(group_col).lower()} universe",
                "query_name": f"summary_universe_{role}",
                "dimension": group_col,
                "dimension_ref": dimension_ref,
                "member_value": raw,
                "segment": segment,
                "hierarchy_path": list(path),
                "metric": None,
                "metric_family": metric_family,
                "direction": direction,
                "observation_value": change_val,
                "materiality": change_val,
                "change_pct": member.get("change_pct"),
                # Validated per-parent materiality diagnostics for the selector.
                "current": current,
                "prior": prior,
                "change": change,
                "overall_current": member.get("overall_current"),
                "gross_sibling_change": member.get("gross_sibling_change"),
                "signed_sibling_change": member.get("signed_sibling_change"),
                "parent_change": member.get("parent_change"),
                "full_member_count": member.get("full_member_count"),
                # High base score so a universe member wins the stable-key dedup
                # over any lower-scored LLM re-slice of the same member.
                "score": 60.0 + min(9.0, math.log10(abs(change_val) + 1.0)),
                "period_anchor": anchor,
                "evidence": {"rows": [], "coverage": "partial", "facts": [fact]},
                "metadata_context": {
                    "dimension": _clean_label(group_col),
                    "metric_family": metric_family,
                    "segment": segment,
                },
                "metrics": [],
                "visual": None,
            }
            finalized = _finalize(candidate, dataset, anchor)
            # R4 focus identity includes the full hierarchy path, so two
            # identically named leaves under different parents remain distinct
            # through selection, same-day pinning, evidence and history.
            portfolio_focus_key, _ = summary_memory.portfolio_focus_components(
                finalized, dataset,
            )
            finalized["focus_key"] = portfolio_focus_key
            finalized["candidate_id"] = f"summary_{portfolio_focus_key.rsplit(':', 1)[-1][:12]}"
            candidates.append(finalized)
    return candidates


def build_candidates(state: dict) -> list[dict]:
    period = state.get("summary_period_context") or {}
    anchor = str(period.get("period_anchor") or "snapshot")
    dataset = str(state.get("dataset_id") or "unknown_dataset")
    focus_enabled = bool(state.get("summary_focus_enabled", True))
    r4_enabled = bool(state.get("summary_r4_enabled", False))
    members_cap = max(0, int(state.get("summary_focus_members_per_dimension", 10)))
    candidates = []
    gated_queries = {
        check.get("query")
        for check in period.get("checks", []) or []
        if check.get("verdict") == "batch_date" and check.get("query")
    }
    for query in _source_queries(state):
        if query.get("query_name") in gated_queries:
            continue
        rows = query.get("rows", []) or []
        labels, numeric = _columns(rows)
        if not numeric:
            continue
        dimension = _dimension(labels, query, state)
        rows, scope = _scope_rows(rows, dimension, numeric, state, query)
        if not rows:
            continue
        labels, numeric = _columns(rows)
        angle = _angle(query, rows, dimension, numeric, r4_enabled=r4_enabled)
        metric = _primary_metric(numeric)
        metric_family = _family(metric or "")
        dimension_role = _dimension_role(angle, dimension, state)
        comparison = _comparison_label(
            state.get("semantic_model_profile") or {}, numeric
        )
        evidence_rows = _trim_rows(rows, labels, numeric, metric)
        values = [float(row.get(metric)) for row in rows if metric and _number(row.get(metric))]
        movement = sum(values) if values else 0.0
        base_score = {
            "overall_performance": 100,
            "overall_contribution": 60,
            "period_movement": 95,
            "store_overview": 90,
            "division_overview": 82,
            "department_overview": 80,
            "category_overview": 78,
            "product_overview": 74,
            "volume_and_transactions": 72,
            "largest_declines": 70,
            "business_breakdown": 65,
        }.get(angle, 50)
        candidate = {
            "candidate_id": "",
            "summary_key": "",
            "focus_key": "",
            "angle": angle,
            "candidate_kind": "broad",
            "dimension_role": dimension_role,
            "lens": summary_memory._lens_from_angle(angle),
            "coverage": "complete" if angle == "overall_performance" else "partial",
            "title_hint": _title(angle, dimension),
            "purpose": query.get("purpose") or _title(angle, dimension),
            "query_name": query.get("query_name"),
            "dimension": dimension,
            "dimension_ref": _resolve_ref(state, labels[0] if labels else dimension),
            "segment": "",
            "metric": metric,
            "metric_family": metric_family,
            "direction": "increase" if movement > 0 else "decrease" if movement < 0 else "flat",
            # Mutable observation for summary-only resurface checks. It is not
            # part of the stable summary_key canon.
            "observation_value": movement,
            "change_pct": _change_pct(rows, numeric),
            "score": base_score + min(9.0, math.log10(abs(movement) + 1.0)),
            "period_anchor": anchor,
            "evidence": {
                "rows": evidence_rows,
                "coverage": "returned_rows",
                "scope": scope,
                "facts": _tag_facts(
                    _fact_sheet(rows, labels, numeric, metric, scope, comparison),
                    focus_subject=None,  # broad candidates describe the whole set
                    coverage="complete" if angle == "overall_performance" else "partial",
                ),
            },
            "metadata_context": _metadata_context(state, dimension, metric, scope),
            "metrics": _metrics(rows, numeric, angle),
            "visual": _visual(rows, labels, metric, angle),
        }
        candidates.append(_finalize(candidate, dataset, anchor))

        # Member-level focus candidates: re-slice the already-returned rows into
        # one focus candidate per leading member. No new DAX is issued here; the
        # deep-dive node builds reconciled evidence only for the selected focus.
        label_col = labels[0] if labels else None
        if (
            focus_enabled
            and members_cap
            and angle in _MEMBER_ANGLES
            and label_col
            and len(rows) >= 2
        ):
            ranked = sorted(
                (row for row in rows if row.get(label_col) not in (None, "")),
                key=lambda row: abs(_member_materiality(row, numeric, metric)),
                reverse=True,
            )
            for index, focus_row in enumerate(ranked[:members_cap]):
                peers = [row for j, row in enumerate(ranked) if j != index][:2]
                candidates.append(
                    _member_candidate(
                        state, query, angle, dimension, dimension_role, rows, labels,
                        numeric, metric, metric_family, comparison, scope, focus_row,
                        peers, label_col, anchor, dataset,
                    )
                )

    # R4: the deterministic focus universe is the primary source of rotating
    # Division/Department/Category member candidates (with validated per-parent
    # materiality diagnostics). Appended after the LLM-derived candidates so the
    # stable-key dedup below keeps the higher-scored universe member.
    if r4_enabled:
        candidates.extend(_universe_member_candidates(state, dataset, anchor))

    # One perspective per stable key. Keep the strongest evidence if the LLM
    # planner happened to produce two semantically equivalent queries.
    by_key = {}
    for candidate in candidates:
        identity = (
            ("area", candidate.get("area_key"))
            if r4_enabled and candidate.get("candidate_source") == "universe"
            else ("summary", candidate.get("summary_key"))
        )
        existing = by_key.get(identity)
        if existing is None or candidate["score"] > existing["score"]:
            by_key[identity] = candidate
    return sorted(by_key.values(), key=lambda item: item["score"], reverse=True)


def run(state: dict) -> dict:
    log = RunLogger(state)
    candidates = build_candidates(state)
    file_io.write_json(state, "summary_candidates.json", candidates)
    log.info(
        "Summary candidates: %d perspective(s) from summary-owned evidence%s."
        % (len(candidates), "" if candidates else " (none usable)")
    )
    return {"summary_candidates": candidates, **log.updates()}
