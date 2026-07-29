"""Insight branch - Synthesizer (LLM, free-form markdown).

Mirrors summary_generator: turns the detected signals + investigation trails
into insight_report.md/.html.
"""

import calendar
import math
import re

from ..tools import file_io
from ..tools import html_report
from ..tools import insight_tiles
from ..tools.llm import get_llm
from ..tools.summary_validation import parse_numbers
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


_BUSINESS_FIGURE = re.compile(
    r"(?<![A-Za-z0-9])[-+]?\d[\d,]*(?:\.\d+)?\s*(?:%|[KMB]\b)|"
    r"(?<![A-Za-z0-9])[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|"
    r"(?<![A-Za-z0-9])[-+]?(?:\d+\.\d+|\d{1,3})(?![A-Za-z0-9])"
)
_TECHNICAL_MANAGER_PHRASES = (
    "accounted for",
    "associated with",
    "broader demand",
    "current period versus prior period",
    "directional",
    "drag",
    "growth engine",
    "heaviest",
    "linked to",
    "mathematically associated",
    "mathematical decomposition",
    "mix of products",
    "more than explained",
    "movement decomposition",
    "overall movement",
    "other areas",
    "product pockets",
    "prior period",
    "volume effect",
    "rate effect",
    "share of total change",
    "realized revenue per unit",
    "basket mix",
    "product mix",
    "sell-through",
    "materiality",
    "reconciliation",
    "z-score",
    "probe",
    "signal",
    "this cut",
    "total movement",
    "trail",
    "uplift",
    "weakness",
    "elsewhere",
)
_CHANGE_WORDS = re.compile(
    r"\b(increased?|decreased?|rose|fell|grew|declined?|added|reduced|"
    r"higher|lower|more|fewer|above|below)\b",
    re.IGNORECASE,
)
_DRIVER_WORDS = re.compile(
    r"\b(because|mainly|driven|came from|resulted from|due to|led by|explained by|"
    r"concentrated|while|although|associated|linked|checks showed|no clear driver)\b",
    re.IGNORECASE,
)
_NEXT_CHECK_WORDS = re.compile(
    r"\b(check|review|compare|confirm|investigate|examine|validate|monitor|verify)\b",
    re.IGNORECASE,
)
_UNQUANTIFIED_CLAIM_WORDS = re.compile(
    r"\b(increased?|decreased?|rose|fell|grew|declined?|more|fewer|largest|"
    r"smallest|strongest|weakest|main|leading|led by|spread across|"
    r"concentrated|visible gains?|positive|negative|higher|lower)\b",
    re.IGNORECASE,
)
_LIMITATION_WORDS = re.compile(
    r"\b(did not|does not|could not|cannot|not available|not enough|"
    r"incomplete|was not measured|were not measured|was not quantified|"
    r"were not quantified)\b",
    re.IGNORECASE,
)

_MAX_MANAGER_WORDS = 105
_MAX_MANAGER_SENTENCE_WORDS = 28
_MAX_MANAGER_SENTENCES = 7
_DATA_QUALITY_TECHNICAL = (
    "coverage",
    "cross-slice",
    "directional",
    "manager fact brief",
    "reconciliation",
    "truncated",
)

_PLAIN_METRIC_TERMS = {
    "revenue": ("revenue", False),
    "quantity": ("units sold", True),
    "transactions": ("transactions", True),
    "profit": ("profit", False),
    "rate": ("average value", False),
}


def _finite(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _pct_change(current, prior):
    if not (_finite(current) and _finite(prior)) or abs(prior) <= 1e-9:
        return None
    return (current - prior) / abs(prior) * 100.0


def _display_value(value, *, count: bool = False) -> str | None:
    """One deterministic manager-facing display value.

    Counts below one million remain comma-grouped so a manager can see the
    actual before/after population.  Larger business amounts use compact units.
    The writer copies these strings; it does not choose its own precision.
    """
    if not _finite(value):
        return None
    value = float(value)
    absolute = abs(value)
    if count and absolute < 1_000_000:
        if abs(value - round(value)) < 1e-6:
            return f"{int(round(value)):,}"
        if absolute >= 10_000:
            return f"{value / 1_000:.1f}K"
        return f"{value:,.1f}"
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.1f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    if count:
        return f"{value:,.1f}"
    if absolute < 10:
        return f"{value:.2f}"
    return f"{value:.1f}"


def _display_pct(value) -> str | None:
    return f"{float(value):.1f}%" if _finite(value) else None


def _display_rate(value) -> str | None:
    return f"{float(value):.2f}" if _finite(value) else None


def _metric_term(signal: dict) -> tuple[str, bool]:
    # The structured family is authoritative.  Descriptions often mention a
    # second measure and previously caused a quantity finding to be labelled as
    # revenue merely because the supporting description also cited revenue.
    family = str(signal.get("metric_family") or "").casefold()
    structured_metric = str(signal.get("metric") or "").casefold()
    for candidate in (family, structured_metric.rsplit("::", 1)[-1]):
        if candidate in _PLAIN_METRIC_TERMS:
            return _PLAIN_METRIC_TERMS[candidate]
    text = " ".join(
        str(signal.get(key) or "")
        for key in ("metric_family", "metric", "description")
    ).casefold()
    for family, display in _PLAIN_METRIC_TERMS.items():
        if family in text or (family == "quantity" and "qty" in text) or (
            family == "transactions" and any(word in text for word in ("bill", "order"))
        ):
            return display
    return "performance", False


def _human_segment(signal: dict) -> str:
    """Return a verified business label instead of a technical member token."""
    period_label = str(signal.get("period_label") or "").strip()
    if period_label:
        return period_label
    members = [
        str(item).strip()
        for item in signal.get("segment_members") or []
        if str(item).strip()
    ]
    if len(members) == 2:
        return f"{members[0]} and {members[1]}"
    if len(members) > 2:
        return ", ".join(members[:-1]) + f", and {members[-1]}"
    raw = str(signal.get("affected_segment") or "").strip()
    dimension = str(signal.get("dimension") or "").casefold()
    match = re.fullmatch(r"\s*[^=]*month[^=]*=\s*(\d{1,2})\s*", raw, re.IGNORECASE)
    if match and "month" in dimension:
        month = int(match.group(1))
        if 1 <= month <= 12:
            return calendar.month_name[month]
    return raw or "This area"


def _bundle_for_signal(signal: dict, profile: dict | None) -> dict:
    bundle_id = str(signal.get("bundle_id") or "")
    bundles = []
    if isinstance(profile, dict):
        bundles.extend(profile.get("value_bundles") or [])
        bundles.extend(profile.get("volume_driver_bundles") or [])
        primary = profile.get("primary_value_bundle")
        if isinstance(primary, dict):
            bundles.append(primary)
    return next(
        (bundle for bundle in bundles if str(bundle.get("id") or "") == bundle_id),
        {},
    )


def _comparison_from_metadata(signal: dict, profile: dict | None = None) -> str:
    """Name the baseline only when metadata proves what the prior phase means."""
    recent_week = signal.get("recent_week") or {}
    if recent_week:
        return (
            "the previous 7 days"
            if recent_week.get("window_mode") == "rolling"
            else "the previous complete week"
        )
    if signal.get("episode_start") is not None:
        return "the expected value for those dates"

    bundle = _bundle_for_signal(signal, profile)
    prior_text: list[str] = []
    measures = bundle.get("measures") or {}
    derived = bundle.get("derived") or {}
    prior_text.extend((str(measures.get("prior") or ""), str(derived.get("prior") or "")))
    for item in bundle.get("evidence") or []:
        if item.get("phase") != "prior":
            continue
        prior_text.extend(
            str(item.get(key) or "")
            for key in ("name", "description", "display_folder")
        )
        for ref in item.get("column_refs") or []:
            prior_text.append(str(ref.get("column") or ""))
    text = " ".join(prior_text).casefold()
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


def _member_forms(value) -> set[str]:
    text = " ".join(str(value or "").strip().casefold().split())
    forms = {text} if text else set()
    if "=" in text:
        forms.add(text.rsplit("=", 1)[-1].strip())
    return forms


def _other_area_breakdown(
    signal: dict,
    clean_data: dict | None,
    change,
    total_change,
    *,
    count: bool,
) -> dict | None:
    """Resolve a contribution-over-100 remainder into named evidence rows.

    The list is used only when the source row matching the signal and the sum of
    every returned row both reconcile to the deterministic contribution math.
    Otherwise the manager report states that the names are unavailable.
    """
    if not (isinstance(clean_data, dict) and _finite(change) and _finite(total_change)):
        return None
    query_name = str(signal.get("evidence_query") or "")
    query = next(
        (
            item for item in clean_data.get("queries", []) or []
            if str(item.get("query_name") or "") == query_name
        ),
        None,
    )
    rows = (query or {}).get("rows") or []
    if len(rows) < 2:
        return None

    targets: set[str] = set()
    for value in (
        signal.get("affected_segment"),
        signal.get("evidence_segment"),
        signal.get("anchor"),
    ):
        targets.update(_member_forms(value))
    for value in signal.get("segment_members") or []:
        targets.update(_member_forms(value))

    label_key = None
    target_row = None
    for key in rows[0]:
        for row in rows:
            if _member_forms(row.get(key)) & targets:
                label_key, target_row = key, row
                break
        if target_row is not None:
            break
    if target_row is None or label_key is None:
        return None

    numeric_keys = [key for key, value in target_row.items() if _finite(value)]
    if not numeric_keys:
        return None
    change_key = min(
        numeric_keys,
        key=lambda key: abs(float(target_row[key]) - float(change)),
    )
    tolerance = max(1.0, abs(float(change)) * 0.001)
    if abs(float(target_row[change_key]) - float(change)) > tolerance:
        return None

    values = [
        float(row.get(change_key))
        for row in rows
        if _finite(row.get(change_key))
    ]
    if not values:
        return None
    row_total = sum(values)
    total_tolerance = max(1.0, abs(float(total_change)) * 0.005)
    if abs(row_total - float(total_change)) > total_tolerance:
        return None

    positive = []
    negative = []
    target_forms = _member_forms(target_row.get(label_key))
    for row in rows:
        value = row.get(change_key)
        if not _finite(value) or _member_forms(row.get(label_key)) & target_forms:
            continue
        value = float(value)
        if abs(value) <= 1e-9:
            continue
        item = {
            "name": str(row.get(label_key) or "Unnamed area").strip(),
            "change": value,
            "change_display": _display_value(abs(value), count=count),
        }
        (positive if value > 0 else negative).append(item)
    positive.sort(key=lambda item: abs(item["change"]), reverse=True)
    negative.sort(key=lambda item: abs(item["change"]), reverse=True)
    return {
        "positive": positive,
        "negative": negative,
        "net": row_total - float(change),
        "net_display": _display_value(abs(row_total - float(change)), count=count),
        "reconciled": True,
    }


def _driver_term(item: dict) -> tuple[str, bool, str]:
    driver = str(item.get("driver") or "").casefold()
    if any(word in driver for word in ("qty", "quantity", "unit")):
        return "units sold", True, "revenue per item"
    if any(word in driver for word in ("bill", "transaction", "order")):
        return "transactions", True, "revenue per purchase"
    if "customer" in driver:
        return "customers", True, "revenue per customer"
    return "sales activity", False, "average value"


def _manager_fact_brief(
    signal: dict,
    profile: dict | None = None,
    clean_data: dict | None = None,
) -> dict:
    """Build the only manager-facing arithmetic brief supplied to the writer.

    Raw signals remain available for the audit appendix.  This compact projection
    makes the simple-language contract explicit: change, before, after, percentage,
    total contribution, and quantified drivers all travel together.
    """
    metric, count = _metric_term(signal)
    finding_type = str(
        signal.get("candidate_type") or signal.get("analysis_type") or "comparison"
    ).casefold()
    is_concentration = "concentration" in finding_type
    current = signal.get("impact_value") if is_concentration else signal.get("current")
    prior = None if is_concentration else signal.get("prior")
    change = None if is_concentration else signal.get("impact_value")
    change_pct = None if is_concentration else _pct_change(current, prior)
    comparison = "the current total" if is_concentration else _comparison_from_metadata(
        signal, profile
    )

    recent_week = signal.get("recent_week") or {}
    if recent_week:
        current, prior = recent_week.get("actual"), recent_week.get("previous")
        change_pct = recent_week.get("change_pct")
        comparison = _comparison_from_metadata(signal, profile)
    elif signal.get("episode_start") is not None:
        current, prior = signal.get("actual_total"), signal.get("expected_total")
        change_pct = _pct_change(current, prior)
        comparison = _comparison_from_metadata(signal, profile)
    elif _finite(signal.get("reported_growth_pct")):
        change_pct = signal.get("reported_growth_pct")
        comparison = _comparison_from_metadata(signal, profile)

    share = signal.get("impact_share")
    total_change = None
    other_change = None
    if not is_concentration and _finite(change) and _finite(share) and abs(share) > 1e-9:
        total_change = float(change) / (float(share) / 100.0)
        other_change = total_change - float(change)
    other_area_breakdown = None
    if _finite(share) and float(share) > 100.0:
        other_area_breakdown = _other_area_breakdown(
            signal,
            clean_data,
            change,
            total_change,
            count=count,
        )

    main = {
        "metric": metric,
        "finding_type": "concentration" if is_concentration else "comparison",
        "direction": "increase" if not _finite(change) or change >= 0 else "decrease",
        "comparison": comparison,
        "current": current,
        "current_display": _display_value(current, count=count),
        "prior": prior,
        "prior_display": _display_value(prior, count=count),
        "change": change,
        "change_display": _display_value(abs(change), count=count) if _finite(change) else None,
        "change_pct": change_pct,
        "change_pct_display": _display_pct(abs(change_pct)) if _finite(change_pct) else None,
        "share_of_total_pct": share,
        "share_of_total_pct_display": (
            _display_pct(abs(share)) if _finite(share) else None
        ),
        "total_change": total_change,
        "total_change_display": (
            _display_value(abs(total_change), count=count) if _finite(total_change) else None
        ),
        "other_change": other_change,
        "other_change_display": (
            _display_value(abs(other_change), count=count) if _finite(other_change) else None
        ),
        "other_area_breakdown": other_area_breakdown,
        "percentage_available": change_pct is not None,
    }

    drivers = []
    for item in signal.get("decomposition") or []:
        driver, driver_count, rate = _driver_term(item)
        driver_change = item.get("driver_change")
        driver_change_pct = item.get("driver_change_pct")
        effect = item.get("volume_effect")
        effect_share = item.get("volume_effect_share_pct")
        rate_change_pct = item.get("rate_change_pct")
        drivers.append({
            "driver": driver,
            "current": item.get("driver_current"),
            "current_display": _display_value(item.get("driver_current"), count=driver_count),
            "prior": item.get("driver_prior"),
            "prior_display": _display_value(item.get("driver_prior"), count=driver_count),
            "change": driver_change,
            "change_display": (
                _display_value(abs(driver_change), count=driver_count)
                if _finite(driver_change) else None
            ),
            "change_pct": driver_change_pct,
            "change_pct_display": (
                _display_pct(abs(driver_change_pct)) if _finite(driver_change_pct) else None
            ),
            "revenue_change_associated": effect,
            "revenue_change_associated_display": (
                _display_value(abs(effect)) if _finite(effect) else None
            ),
            "revenue_change_share_pct": effect_share,
            "revenue_change_share_pct_display": (
                _display_pct(abs(effect_share)) if _finite(effect_share) else None
            ),
            "rate": rate,
            "rate_current": item.get("rate_current"),
            "rate_current_display": _display_rate(item.get("rate_current")),
            "rate_prior": item.get("rate_prior"),
            "rate_prior_display": _display_rate(item.get("rate_prior")),
            "rate_change_pct": rate_change_pct,
            "rate_change_pct_display": (
                _display_pct(abs(rate_change_pct)) if _finite(rate_change_pct) else None
            ),
            "rate_revenue_change_associated": item.get("rate_effect"),
            "rate_revenue_change_associated_display": (
                _display_value(abs(item.get("rate_effect")))
                if _finite(item.get("rate_effect")) else None
            ),
            "rate_revenue_change_share_pct": item.get("rate_effect_share_pct"),
            "rate_revenue_change_share_pct_display": (
                _display_pct(abs(item.get("rate_effect_share_pct")))
                if _finite(item.get("rate_effect_share_pct")) else None
            ),
            "reconciled": item.get("reconciled"),
        })
    return {
        "signal_id": signal.get("id"),
        "segment": _human_segment(signal),
        "finding_type": "concentration" if is_concentration else "comparison",
        "kind": signal.get("kind"),
        "main": main,
        "drivers": drivers,
        "wording_guard": (
            "Transactions mean purchases recorded, not unique customers."
            if any(driver.get("driver") == "transactions" for driver in drivers)
            else None
        ),
    }


def _manager_fact_briefs(
    signals: list[dict],
    profile: dict | None = None,
    clean_data: dict | None = None,
) -> list[dict]:
    return [_manager_fact_brief(signal, profile, clean_data) for signal in signals]


def _supported_numbers(value, name: str = "") -> list[float]:
    numbers: list[float] = []
    if _finite(value):
        number = float(value)
        numbers.append(number)
        # Manager prose states direction in words ("fell by 370K"), so the
        # displayed magnitude is positive even when the stored change is negative.
        if number < 0:
            numbers.append(abs(number))
        lowered = name.casefold()
        if abs(number) <= 2 and any(
            token in lowered for token in ("pct", "percent", "share", "ratio")
        ):
            numbers.append(number * 100.0)
    elif isinstance(value, dict):
        for key, item in value.items():
            numbers.extend(_supported_numbers(item, str(key)))
    elif isinstance(value, (list, tuple)):
        for item in value:
            numbers.extend(_supported_numbers(item, name))
    return numbers


def _comparison_words(comparison: str) -> str:
    comparison = str(comparison or "the stated comparison period").strip()
    return f"compared with {comparison}"


def _join_area_items(items: list[dict]) -> str:
    labels = [f"{item['name']} ({item['change_display']})" for item in items]
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} and {labels[1]}"
    return ", ".join(labels[:-1]) + f", and {labels[-1]}"


def _area_breakdown_sentences(breakdown: dict, metric: str) -> list[str]:
    if metric == "units sold":
        subject = "Units"
    elif metric == "transactions":
        subject = "Purchases"
    else:
        subject = metric[:1].upper() + metric[1:]
    sentences = []
    for direction, verb in (("positive", "rose"), ("negative", "fell")):
        items = breakdown.get(direction) or []
        for start in range(0, len(items), 6):
            chunk = items[start:start + 6]
            sentences.append(f"{subject} {verb} in {_join_area_items(chunk)}.")
    return sentences


def _deterministic_finding(signal: dict, brief: dict) -> str | None:
    """Short, code-owned wording when an LLM paragraph remains too complex."""
    main = brief.get("main", {}) or {}
    segment = str(brief.get("segment") or signal.get("affected_segment") or "This area")
    metric = str(main.get("metric") or "performance")

    if main.get("finding_type") == "concentration":
        amount = main.get("current_display")
        share = main.get("share_of_total_pct_display")
        if not amount or not share:
            return None
        if metric == "units sold":
            headline = f"**{segment} sold {amount} units in total.**"
            total_name = "all units sold"
        elif metric == "transactions":
            headline = f"**{segment} recorded {amount} purchases in total.**"
            total_name = "all recorded purchases"
        else:
            headline = f"**{segment} generated {amount} in {metric}.**"
            total_name = f"all {metric}"
        sentences = [
            headline,
            f"That was {share} of {total_name}.",
            "Check the complete branch and product breakdown before ranking the areas inside this total.",
        ]
        return " ".join(sentences)

    required = (
        main.get("change_display"),
        main.get("current_display"),
        main.get("prior_display"),
    )
    if not all(required):
        return None
    increasing = main.get("direction") != "decrease"
    pct = f" ({main['change_pct_display']})" if main.get("change_pct_display") else ""
    if metric == "units sold":
        headline = (
            f"**{segment} sold {main['change_display']} {'more' if increasing else 'fewer'} "
            f"units{pct}, moving from {main['prior_display']} to {main['current_display']} "
            f"{_comparison_words(main.get('comparison'))}.**"
        )
    elif metric == "transactions":
        headline = (
            f"**{segment} recorded {main['change_display']} "
            f"{'more' if increasing else 'fewer'} purchases{pct}, moving from "
            f"{main['prior_display']} to {main['current_display']} "
            f"{_comparison_words(main.get('comparison'))}.**"
        )
    else:
        headline = (
            f"**{segment} {metric} {'rose' if increasing else 'fell'} by "
            f"{main['change_display']}{pct}, from {main['prior_display']} to "
            f"{main['current_display']} {_comparison_words(main.get('comparison'))}.**"
        )
    sentences = [headline]
    share = main.get("share_of_total_pct")
    share_display = main.get("share_of_total_pct_display")
    if share_display:
        total_change = main.get("total_change")
        total_direction = "increase" if not _finite(total_change) or total_change >= 0 else "decline"
        total_name = "increase" if total_direction == "increase" else "drop"
        if share >= 0 and abs(float(share)) > 100:
            sentences.append(f"This was {share_display} of the final overall {total_name}.")
            breakdown = main.get("other_area_breakdown") or {}
            if breakdown.get("reconciled"):
                sentences.extend(_area_breakdown_sentences(breakdown, metric))
                net = breakdown.get("net")
                net_display = breakdown.get("net_display")
                if _finite(net) and net_display:
                    unit = (
                        "units"
                        if metric == "units sold"
                        else "purchases"
                        if metric == "transactions"
                        else metric
                    )
                    sentences.append(
                        f"Together, the areas outside {segment} "
                        f"{'gained' if net >= 0 else 'lost'} {net_display} {unit}."
                    )
            elif main.get("other_change_display") and main.get("total_change_display"):
                sentences.append(
                    "The area-by-area names were not available, so this report "
                    "cannot explain the above-100% result safely."
                )
        elif share >= 0:
            sentences.append(f"It made up {share_display} of the overall {total_name}.")
        else:
            sentences.append(f"It reduced the overall {total_name} by {share_display}.")

    for driver_index, driver in enumerate((brief.get("drivers") or [])[:2]):
        if not all(driver.get(key) for key in (
            "change_display", "prior_display", "current_display"
        )):
            continue
        driver_up = not _finite(driver.get("change")) or driver.get("change") >= 0
        driver_name = str(driver.get("driver") or "Sales activity")
        driver_sentence = (
            f"{driver_name.capitalize()} {'rose' if driver_up else 'fell'} by "
            f"{driver['change_display']}"
            + (f" ({driver['change_pct_display']})" if driver.get("change_pct_display") else "")
            + f", from {driver['prior_display']} to {driver['current_display']}."
        )
        if driver.get("driver") == "transactions":
            driver_sentence = driver_sentence[:-1] + (
                "; this means more purchases, not necessarily more customers."
                if driver_up else
                "; this means fewer purchases, not necessarily fewer customers."
            )
        sentences.append(driver_sentence)
        if driver_index == 0:
            effect_display = driver.get("revenue_change_associated_display")
            effect = driver.get("revenue_change_associated")
            if effect_display and _finite(effect):
                if effect >= 0:
                    sentences.append(f"This added {effect_display} to {metric}.")
                else:
                    sentences.append(f"This reduced {metric} by {effect_display}.")
            if all(driver.get(key) for key in (
                "rate_prior_display", "rate_current_display", "rate_change_pct_display",
                "rate_revenue_change_associated_display",
            )):
                rate_up = not _finite(driver.get("rate_change_pct")) or driver.get("rate_change_pct") >= 0
                sentences.append(
                    f"{str(driver.get('rate') or 'Average value').capitalize()} "
                    f"{'rose' if rate_up else 'fell'} {driver['rate_change_pct_display']}, from "
                    f"{driver['rate_prior_display']} to {driver['rate_current_display']}."
                )
                rate_effect = driver.get("rate_revenue_change_associated")
                rate_effect_display = driver.get("rate_revenue_change_associated_display")
                if _finite(rate_effect) and rate_effect_display:
                    if rate_effect >= 0 and not increasing:
                        sentences.append(
                            f"This added back {rate_effect_display} and made the decline smaller."
                        )
                    elif rate_effect < 0 and increasing:
                        sentences.append(f"This reduced the gain by {rate_effect_display}.")
                    elif rate_effect >= 0:
                        sentences.append(f"This added {rate_effect_display} to the gain.")
                    else:
                        sentences.append(f"This increased the decline by {rate_effect_display}.")

    if not brief.get("drivers") and not main.get("other_area_breakdown"):
        sentences.append("This report does not have a complete product-and-branch ranking.")
    sentences.append(
        f"Check {segment} by product and branch to find where the change happened."
    )
    while (
        len(re.findall(r"\b\w+[\w'-]*\b", " ".join(sentences))) > _MAX_MANAGER_WORDS
        or len(_manager_sentences(" ".join(sentences))) > _MAX_MANAGER_SENTENCES
    ):
        # Transactions remain in Evidence Trail when the manager paragraph is
        # already full.  Never remove the headline, main contribution, first
        # quantified driver, or final check.
        transaction_index = next(
            (i for i, sentence in enumerate(sentences) if sentence.startswith("Transactions ")),
            None,
        )
        if transaction_index is None:
            break
        sentences.pop(transaction_index)
    paragraph = " ".join(sentences)
    return (
        paragraph
        if len(re.findall(r"\b\w+[\w'-]*\b", paragraph)) <= _MAX_MANAGER_WORDS
        else None
    )


def _replace_invalid_key_insights(
    report: str,
    signals: list[dict],
    fact_briefs: list[dict],
) -> str:
    match = re.search(
        r"(?ms)^# Key Insights\s*(.*?)(?=^# Data Quality Watch-outs\s*$)",
        report or "",
    )
    if not match:
        return report
    blocks = [
        block.strip() for block in re.split(r"\n\s*\n", match.group(1)) if block.strip()
    ]
    scope = next((block for block in blocks if not block.startswith("**")), "")
    if scope:
        comparison = str(
            ((fact_briefs[0].get("main") or {}).get("comparison") if fact_briefs else "")
            or ""
        ).casefold()
        baseline = (
            "current and last-year data"
            if "last year" in comparison
            else "current and comparison data"
        )
        scope = re.sub(
            r"\b(\w+)\s+like-for-like\s+(branches|stores|locations|areas)\s+only\b",
            lambda match: f"only {match.group(1)} {match.group(2)} with {baseline}",
            scope,
            flags=re.IGNORECASE,
        )
        scope = re.sub(
            r"\blike-for-like\s+(branches|stores|locations|areas)\b",
            lambda match: f"{match.group(1)} with {baseline}",
            scope,
            flags=re.IGNORECASE,
        )
    old_findings = [block for block in blocks if block.startswith("**")]
    replacements = []
    for index, (signal, brief) in enumerate(zip(signals, fact_briefs)):
        replacements.append(
            _deterministic_finding(signal, brief)
            or (old_findings[index] if index < len(old_findings) else "")
        )
    body = "\n\n".join(part for part in ([scope] if scope else []) + replacements if part)
    return report[:match.start()] + "# Key Insights\n" + body + "\n\n" + report[match.end():]


def _simple_data_quality_bullet(text: str) -> str:
    plain = text.casefold()
    if any(word in plain for word in ("label", "metric name", "metric name", "matches the evidence")):
        return (
            "One finding may use the wrong metric label. "
            "Check that every label matches the data before publishing."
        )
    if "branch" in plain and any(word in plain for word in ("rank", "partial", "incomplete")):
        return (
            "The branch information was incomplete, so the branch ranking may be wrong. "
            "Check the full branch breakdown."
        )
    if any(word in plain for word in ("product", "category")):
        return (
            "Some product information was incomplete, so smaller rankings may change. "
            "Check the full product breakdown."
        )
    return (
        "One supporting data check was incomplete. "
        "Review the Evidence Trail before using the detailed ranking."
    )


def _replace_complex_data_quality(report: str) -> str:
    match = re.search(
        r"(?ms)^# Data Quality Watch-outs\s*(.*?)(?=^# Evidence Trail\s*$)",
        report or "",
    )
    if not match:
        return report
    lines = []
    for line in match.group(1).strip().splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            lines.append(line)
            continue
        bullet = stripped[2:].strip()
        words = re.findall(r"\b\w+[\w'-]*\b", bullet)
        too_technical = any(
            phrase in bullet.casefold() for phrase in _DATA_QUALITY_TECHNICAL
        )
        if len(words) > 40 or len(_manager_sentences(bullet)) > 2 or too_technical:
            lines.append("- " + _simple_data_quality_bullet(bullet))
        else:
            lines.append(line)
    body = "\n".join(lines).strip()
    return (
        report[:match.start()]
        + "# Data Quality Watch-outs\n"
        + body
        + "\n\n"
        + report[match.end():]
    )


def _response_text(response) -> str:
    report = response.content if hasattr(response, "content") else str(response)
    if isinstance(report, list):
        report = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in report
        )
    return str(report).strip()


def _key_insight_paragraphs(report: str) -> list[str]:
    match = re.search(
        r"(?ms)^# Key Insights\s*(.*?)(?=^# Data Quality Watch-outs\s*$)",
        report or "",
    )
    if not match:
        return []
    return [
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", match.group(1))
        if paragraph.strip().startswith("**")
    ]


def _data_quality_bullets(report: str) -> list[str]:
    match = re.search(
        r"(?ms)^# Data Quality Watch-outs\s*(.*?)(?=^# Evidence Trail\s*$)",
        report or "",
    )
    if not match:
        return []
    return [
        item.strip()[2:].strip()
        for item in match.group(1).splitlines()
        if item.strip().startswith("- ")
    ]


def _display_present(paragraph: str, display: str | None) -> bool:
    if not display:
        return True
    normalized_paragraph = re.sub(r"[\s,+]", "", paragraph).casefold()
    normalized_display = re.sub(r"[\s,+]", "", display).casefold()
    return normalized_display in normalized_paragraph


def _term_is_quantified(paragraph: str, terms: tuple[str, ...]) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        plain = sentence.casefold()
        if any(term in plain for term in terms) and _BUSINESS_FIGURE.search(sentence):
            return True
    return False


def _unsupported_customer_claim(paragraph: str, brief: dict) -> bool:
    has_transaction_driver = any(
        driver.get("driver") == "transactions" for driver in brief.get("drivers", [])
    )
    if not has_transaction_driver:
        return False
    for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
        plain = sentence.casefold()
        if "customer" not in plain:
            continue
        if any(guard in plain for guard in ("does not", "do not", "cannot", "not necessarily")):
            continue
        if re.search(r"\b(more|fewer|broader|higher|lower|additional|unique)\b", plain):
            return True
    return False


def _manager_sentences(paragraph: str) -> list[str]:
    plain_markdown = paragraph.replace("**", " ")
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", plain_markdown)
        if sentence.strip()
    ]


def _action_sentence(sentence: str) -> bool:
    return bool(re.match(
        r"^(check|review|compare|confirm|investigate|examine|validate|monitor|verify)\b",
        sentence.strip(),
        re.IGNORECASE,
    ))


def _clarity_issues(
    report: str,
    expected_findings: int,
    fact_briefs: list[dict] | None = None,
    supported_numbers: list[float] | None = None,
) -> list[str]:
    """Check only manager-facing Key Insights; technical appendices stay auditable."""
    if expected_findings <= 0:
        return []
    paragraphs = _key_insight_paragraphs(report)
    issues: list[str] = []
    key_match = re.search(
        r"(?ms)^# Key Insights\s*(.*?)(?=^# Data Quality Watch-outs\s*$)",
        report or "",
    )
    if key_match:
        scope_blocks = [
            block.strip()
            for block in re.split(r"\n\s*\n", key_match.group(1))
            if block.strip() and not block.strip().startswith("**")
        ]
        if any(
            phrase in " ".join(scope_blocks).casefold()
            for phrase in ("like-for-like", "comparable population", "comparable basis")
        ):
            issues.append(
                "Key Insights scope uses comparison jargon instead of saying which data is included"
            )
    if len(paragraphs) != expected_findings:
        issues.append(
            f"Key Insights has {len(paragraphs)} finding paragraph(s); expected {expected_findings}"
        )
    for index, paragraph in enumerate(paragraphs, start=1):
        plain = paragraph.casefold()
        words = re.findall(r"\b\w+[\w'-]*\b", paragraph)
        sentences = _manager_sentences(paragraph)
        figures = _BUSINESS_FIGURE.findall(paragraph)
        takeaway_match = re.match(r"\*\*(.+?)\*\*", paragraph, flags=re.DOTALL)
        takeaway = takeaway_match.group(1) if takeaway_match else ""
        if len(words) > _MAX_MANAGER_WORDS:
            issues.append(
                f"finding {index} is {len(words)} words; maximum is {_MAX_MANAGER_WORDS}"
            )
        if len(sentences) > _MAX_MANAGER_SENTENCES:
            issues.append(
                f"finding {index} has {len(sentences)} sentences; maximum is "
                f"{_MAX_MANAGER_SENTENCES}"
            )
        for sentence_index, sentence in enumerate(sentences, start=1):
            sentence_words = re.findall(r"\b\w+[\w'-]*\b", sentence)
            if len(sentence_words) > _MAX_MANAGER_SENTENCE_WORDS:
                issues.append(
                    f"finding {index} sentence {sentence_index} is "
                    f"{len(sentence_words)} words; maximum is "
                    f"{_MAX_MANAGER_SENTENCE_WORDS}"
                )
            if (
                _UNQUANTIFIED_CLAIM_WORDS.search(sentence)
                and not _BUSINESS_FIGURE.search(sentence)
                and not _action_sentence(sentence)
                and not _LIMITATION_WORDS.search(sentence)
            ):
                issues.append(
                    f"finding {index} sentence {sentence_index} makes an "
                    "unquantified supporting claim"
                )
        if not figures:
            issues.append(f"finding {index} does not state the size of the change")
        if not _NEXT_CHECK_WORDS.search(paragraph):
            issues.append(f"finding {index} does not end with a specific check")
        found = [phrase for phrase in _TECHNICAL_MANAGER_PHRASES if phrase in plain]
        if found:
            issues.append(
                f"finding {index} uses analyst shorthand: {', '.join(found)}"
            )
        if supported_numbers is not None:
            for value, tolerance, token in parse_numbers(paragraph):
                if not any(
                    abs(value - known) <= max(tolerance, abs(known) * 0.0005)
                    for known in supported_numbers
                ):
                    issues.append(
                        f"finding {index} contains unsupported figure {token!r}"
                    )
        if fact_briefs and index <= len(fact_briefs):
            brief = fact_briefs[index - 1]
            main = brief.get("main", {}) or {}
            concentration = main.get("finding_type") == "concentration"
            if not concentration and not _CHANGE_WORDS.search(paragraph):
                issues.append(f"finding {index} does not plainly say what changed")
            if (
                not _BUSINESS_FIGURE.search(takeaway)
                or (not concentration and not _CHANGE_WORDS.search(takeaway))
            ):
                issues.append(
                    f"finding {index} bold takeaway must state "
                    + ("the current result and its figure" if concentration else "what changed and its figure")
                )
            main_displays = [
                ("change", main.get("change_display")),
                ("percentage change", main.get("change_pct_display")),
                ("prior value", main.get("prior_display")),
                ("current value", main.get("current_display")),
                ("part of the overall result", main.get("share_of_total_pct_display")),
            ]
            for label, display in main_displays:
                if display and not _display_present(paragraph, display):
                    issues.append(
                        f"finding {index} omits the supported {label} ({display})"
                    )
            if main.get("prior_display") and main.get("current_display") and not re.search(
                r"\b(from|to|versus|vs\.?|compared|prior|previous|last year|expected)\b",
                paragraph,
                re.IGNORECASE,
            ):
                issues.append(f"finding {index} does not name the comparison baseline")

            drivers = brief.get("drivers", []) or []
            explained_driver = False
            for driver_index, driver in enumerate(drivers):
                driver_name = str(driver.get("driver") or "")
                if driver_name == "units sold":
                    terms = ("unit", "quantity", "items sold")
                elif driver_name == "transactions":
                    terms = ("transaction", "bill", "purchase")
                else:
                    terms = (driver_name.casefold(),)
                mentioned = any(term and term in plain for term in terms)
                if not mentioned:
                    continue
                explained_driver = True
                if not _term_is_quantified(paragraph, terms):
                    issues.append(
                        f"finding {index} mentions {driver_name} without a quantified value"
                    )
                for label, display in (
                    ("prior", driver.get("prior_display")),
                    ("current", driver.get("current_display")),
                    ("change", driver.get("change_display")),
                    ("percentage change", driver.get("change_pct_display")),
                ):
                    if display and not _display_present(paragraph, display):
                        issues.append(
                            f"finding {index} mentions {driver_name} but omits its {label} ({display})"
                        )
                # One effect amount is enough in the manager paragraph.  The
                # effect percentage stays in Evidence Trail when it would make
                # a simple explanation harder to follow (especially above 100%).
                if driver_index == 0:
                    display = driver.get("revenue_change_associated_display")
                    if display and not _display_present(paragraph, display):
                        issues.append(
                            f"finding {index} describes the main contributor but "
                            f"omits its amount ({display})"
                        )
                rate_name = str(driver.get("rate") or "").casefold()
                if rate_name and rate_name in plain:
                    for label, display in (
                        ("prior", driver.get("rate_prior_display")),
                        ("current", driver.get("rate_current_display")),
                        ("percentage change", driver.get("rate_change_pct_display")),
                        ("effect amount", driver.get("rate_revenue_change_associated_display")),
                    ):
                        if display and not _display_present(paragraph, display):
                            issues.append(
                                f"finding {index} mentions {rate_name} but omits its {label} ({display})"
                            )
            if not concentration:
                if drivers and not explained_driver:
                    issues.append(
                        f"finding {index} does not explain the main measured reason"
                    )
                if (
                    not drivers
                    and not main.get("other_area_breakdown")
                    and not _LIMITATION_WORDS.search(paragraph)
                ):
                    issues.append(
                        f"finding {index} must plainly say that no reason was measured"
                    )
            if _unsupported_customer_claim(paragraph, brief):
                issues.append(
                    f"finding {index} turns transaction activity into an unsupported customer claim"
                )
    for index, bullet in enumerate(_data_quality_bullets(report), start=1):
        words = re.findall(r"\b\w+[\w'-]*\b", bullet)
        sentences = _manager_sentences(bullet)
        if len(words) > 40:
            issues.append(
                f"data-quality bullet {index} is {len(words)} words; maximum is 40"
            )
        if len(sentences) > 2:
            issues.append(
                f"data-quality bullet {index} has {len(sentences)} sentences; maximum is 2"
            )
        found = [phrase for phrase in _DATA_QUALITY_TECHNICAL if phrase in bullet.casefold()]
        if found:
            issues.append(
                f"data-quality bullet {index} uses technical wording: {', '.join(found)}"
            )
    return issues


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: synthesizing the insight report...")

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("insight_synthesizer_prompt.md")

    understanding = state.get("report_understanding", {})
    signals = state.get("insight_signals", [])
    investigations = state.get("insight_investigations", [])
    theses = state.get("insight_theses", []) or []
    novelty = state.get("insight_novelty", {}) or {}
    fact_briefs = _manager_fact_briefs(
        signals,
        state.get("semantic_model_profile") or {},
        state.get("insight_clean_data") or {},
    )
    manager_supported_numbers = _supported_numbers({
        "manager_fact_briefs": fact_briefs,
        "signals": signals,
        "investigations": investigations,
        "theses": theses,
    })

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
        # Deterministic manager-ready arithmetic.  Key Insights copies these
        # display values and explains them in ordinary language; it never has to
        # derive a percentage or hunt through a raw probe result.
        "manager_fact_briefs": fact_briefs,
        # Phase 9: deterministic cross-signal links. A "same_movement" verdict means
        # two findings moved together at the same rate (consistent with one event);
        # anything else is only "related". Never a proven cause - phrase as such.
        "theses": theses,
        "coverage_matrix": state.get("insight_coverage_matrix", {}),
        "resolved_entity_scope": state.get("resolved_entity_scope", {}),
        "metadata_profile_warnings": state.get("semantic_model_profile", {}).get("warnings", []),
        "novelty": {k: novelty.get(k) for k in
                    ("reason", "detected", "suppressed", "eligible", "selected",
                     "policy", "memory_status", "level_breakdown")},
        "temporal": {**{k: (state.get("insight_temporal_verdict", {}) or {}).get(k)
                        for k in ("enabled", "grain", "column", "reason")},
                     "worst_period_drill": state.get("insight_temporal_drill")},
        # Phase 3/3b: the recent-week verdict carries the honest caveat when
        # disabled (load/posting-date axis or stale data). When enabled, phrase
        # the movement from each signal's structured `recent_week` payload (the
        # delta % is `change_pct`, NOT impact_share), with hedged contribution
        # language - and phrase it as "trailing 7 days" rather than "week of"
        # when `window_mode` is "rolling".
        "recent_week": {k: (state.get("insight_recent_week_verdict", {}) or {}).get(k)
                        for k in ("enabled", "reason", "window_mode", "week_start", "week_end",
                                  "data_as_of", "effective_data_as_of", "drivers")},
        # Phase 3b: the daily verdict carries the same honest disabled-caveat
        # pattern - it disables independently of recent-week's own gate/mode,
        # based only on whether a validated business-day axis exists.
        "daily": {k: (state.get("insight_daily_verdict", {}) or {}).get(k)
                 for k in ("enabled", "reason", "incidents_found", "incidents_reported")},
        "note": note,
    }

    llm = get_llm(state)  # free-form text output
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task},
        {"role": "user", "content": "SIGNALS + INVESTIGATION TRAILS:\n" + dumps(context)},
    ]

    report = ""
    clarity_issues = []
    expected_business_findings = sum(
        1 for signal in signals if signal.get("kind") != "data_quality"
    )
    business_fact_briefs = [
        brief for brief in fact_briefs if brief.get("kind") != "data_quality"
    ]
    business_signals = [
        signal for signal in signals if signal.get("kind") != "data_quality"
    ]
    for attempt in range(3):
        report = _response_text(llm.invoke(messages))
        clarity_issues = _clarity_issues(
            report,
            expected_business_findings,
            business_fact_briefs,
            manager_supported_numbers,
        )
        if not clarity_issues:
            break
        if attempt < 2:
            log.info(
                "Insight report clarity check requested a rewrite (%d issue(s))."
                % len(clarity_issues)
            )
            messages.extend([
                {"role": "assistant", "content": report},
                {
                    "role": "user",
                    "content": (
                        "Rewrite the complete report. Preserve the supplied facts and required "
                        "section headings, but fix every manager-facing clarity issue below. "
                        "Keep technical calculation detail only in Evidence Trail.\n- "
                        + "\n- ".join(clarity_issues)
                    ),
                },
            ])
    if clarity_issues:
        fallback_report = _replace_invalid_key_insights(
            report,
            business_signals,
            business_fact_briefs,
        )
        fallback_report = _replace_complex_data_quality(fallback_report)
        fallback_issues = _clarity_issues(
            fallback_report,
            expected_business_findings,
            business_fact_briefs,
            manager_supported_numbers,
        )
        if len(fallback_issues) < len(clarity_issues):
            report = fallback_report
            clarity_issues = fallback_issues
            log.info(
                "Insight report used deterministic quantified wording for "
                "manager-facing finding(s) that still failed the LLM clarity check."
            )
    if clarity_issues:
        log.error(
            "Insight report still has %d manager-facing clarity issue(s) after retries."
            % len(clarity_issues)
        )

    file_io.write_text(state, "insight_report.md", report)

    domain = understanding.get("domain") if isinstance(understanding, dict) else None
    title = f"{domain} Insight Report" if domain else "Insight Report"
    file_io.write_text(state, "insight_report.html",
                       html_report.render(report, title=title, eyebrow="Power BI Insight Report"))

    # Optional deterministic visual board. Insight history still reuses the
    # Markdown heading parser from insight_tiles.py even when this HTML artifact
    # is disabled, so do not remove the shared module.
    if state.get("insight_tiles_enabled", False):
        try:
            insight_tiles.write_from_state(state, report_md=report)
            log.info("Insight board written (insight_tiles.html).")
        except Exception as exc:  # noqa: BLE001 - defensive; supplementary artifact
            log.info(f"Insight board skipped ({type(exc).__name__}: {exc}).")
    else:
        log.info("Insight board disabled (insight_tiles_enabled=false).")

    log.info(f"Insight report written ({len(report.split())} words).")
    return {"insight_report": report, **log.updates()}
