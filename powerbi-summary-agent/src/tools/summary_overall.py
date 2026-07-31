"""Deterministic Overall Performance package (summary-only, R4).

Builds the mandatory company-level view from the already-computed
``overall_performance`` candidate: current/prior/change/% for the primary value
family plus available quantity and transactions, an exact volume/rate-mix bridge,
comparison wording and reconciliation status. No LLM and no new query - the
optional overall period trend is attached separately by the node. Imports no
insight module.
"""

from __future__ import annotations

import math
from typing import Any


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _families_from_candidate(candidate: dict) -> dict:
    """Read per-family current/prior/change/% from the overall comparison facts."""
    out: dict = {}
    for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
        if fact.get("fact_kind") != "comparison":
            continue
        metric = str(fact.get("metric") or "")
        family = metric.split()[0].casefold() if metric else ""
        if not family or family in out:
            continue
        out[family] = {
            "current": _num(fact.get("current_value")),
            "prior": _num(fact.get("prior_value")),
            "change": _num(fact.get("change_value")),
            "change_pct": _num(fact.get("change_pct")),
            "comparison": fact.get("comparison"),
        }
    return out


def _bridge(families: dict) -> dict | None:
    """Exact volume vs rate/mix decomposition of the revenue change.

    volume = (Q1 - Q0) * (R0)      with R0 = Rev0 / Q0
    rate   = Q1 * (R1 - R0)        with R1 = Rev1 / Q1
    Rate/mix legitimately blends price and mix and is never called pure price.
    """
    revenue = families.get("revenue")
    quantity = families.get("quantity")
    if not (revenue and quantity):
        return None
    rev_c, rev_p = revenue.get("current"), revenue.get("prior")
    qty_c, qty_p = quantity.get("current"), quantity.get("prior")
    if None in (rev_c, rev_p, qty_c, qty_p) or not qty_p or not qty_c:
        return None
    rate0 = rev_p / qty_p
    rate1 = rev_c / qty_c
    volume = (qty_c - qty_p) * rate0
    rate = qty_c * (rate1 - rate0)
    total = volume + rate
    change = rev_c - rev_p
    reconciles = abs(total - change) <= (abs(change) * 0.02 if change else 1.0)
    return {
        "volume_effect": volume,
        "rate_mix_effect": rate,
        "total": total,
        "revenue_change": change,
        "reconciles": reconciles,
        "note": "Rate/mix reflects price and mix together, not pure price.",
    }


def _fmt(value: Any, signed: bool = True) -> str:
    number = _num(value)
    if number is None:
        return str(value)
    sign = "+" if signed else ""
    magnitude = abs(number)
    if magnitude >= 1_000_000_000:
        return f"{number / 1_000_000_000:{sign}.2f}B"
    if magnitude >= 1_000_000:
        return f"{number / 1_000_000:{sign}.1f}M"
    if magnitude >= 1_000:
        return f"{number / 1_000:{sign}.1f}K"
    return f"{number:{sign}.0f}"


def bridge_facts(bridge: dict | None, comparison: str = "the comparison period") -> list[dict]:
    """Both sides of the revenue bridge as supported facts (volume AND rate/mix).

    Promoting both effects to first-class facts lets the summary state the full
    story ("quantity reduced revenue by -2.0M while rate/mix added +5.0M") with
    figures that number-validation accepts, instead of only naming the dominant
    side. Values are derived, never hardcoded.
    """
    if not bridge or not bridge.get("reconciles"):
        return []
    volume = _num(bridge.get("volume_effect"))
    rate = _num(bridge.get("rate_mix_effect"))
    if volume is None or rate is None:
        return []
    return [
        {
            "fact_id": "OVERALL_VOLUME", "fact_kind": "bridge", "subject": "Overall",
            "subject_role": "focus", "detail_role": "driver",
            "metric": "Volume effect on revenue", "display_value": _fmt(volume), "raw_value": volume,
            "statement": (
                f"Change in quantity {'added' if volume >= 0 else 'reduced'} revenue by "
                f"{_fmt(volume)} versus {comparison}."
            ),
        },
        {
            "fact_id": "OVERALL_RATE_MIX", "fact_kind": "bridge", "subject": "Overall",
            "subject_role": "focus", "detail_role": "driver",
            "metric": "Rate and mix effect on revenue", "display_value": _fmt(rate), "raw_value": rate,
            "statement": (
                f"Average revenue per item and mix {'added' if rate >= 0 else 'reduced'} revenue by "
                f"{_fmt(rate)} versus {comparison}."
            ),
        },
    ]


def _contribution_family(metric: str) -> str | None:
    text = str(metric or "").casefold()
    if "current" not in text:
        return None
    if "revenue" in text or "sales" in text or "turnover" in text:
        return "revenue"
    if any(token in text for token in ("quantity", "qty", "units", "volume")):
        return "quantity"
    if any(token in text for token in ("transaction", "bills", "orders", "visits")):
        return "transactions"
    return None


def contribution_note(candidate: dict | None, label: str = "") -> dict | None:
    """A current-only total shown separately from the like-for-like comparison.

    Turns the current-period figures of a ``overall_contribution`` candidate
    (for example a newly opened branch excluded from the year-on-year set) into
    a small supporting note plus supported facts the summary may cite once. The
    facts carry a copyable ``display_value`` and are tagged ``contribution`` so
    they are never mistaken for a comparison or a driver bridge side. Returns
    ``None`` when the candidate exposes no usable current figure.
    """
    if not candidate:
        return None
    subject = str(label).strip() or str(candidate.get("segment") or "").strip() or "New contribution"
    facts: list[dict] = []
    seen: set[str] = set()
    for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
        if fact.get("fact_kind") == "comparison":
            continue
        raw = _num(fact.get("raw_value"))
        if raw is None:
            continue
        family = _contribution_family(str(fact.get("metric") or ""))
        if family is None or family in seen:
            continue
        seen.add(family)
        facts.append({
            "fact_id": f"CONTRIB_{family.upper()}",
            "fact_kind": "contribution",
            "subject": subject,
            "subject_role": "context",
            "detail_role": "context",
            "metric": f"{family.title()} current (separate contribution)",
            "display_value": _fmt(raw, signed=False),
            "raw_value": raw,
            "statement": (
                f"{subject} contributed {_fmt(raw, signed=False)} in current {family}; "
                "this is a separate current-period total and is not part of the "
                "like-for-like comparison."
            ),
        })
    if not facts:
        return None
    return {
        "subject": subject,
        "facts": facts,
        "note": (
            f"{subject} is shown separately from the like-for-like comparison because it "
            "reflects current-period activity without a prior-year baseline."
        ),
    }


def build_overall(candidate: dict | None, period: dict | None = None) -> dict:
    """Return the deterministic Overall Performance package (or an unavailable stub)."""
    if not candidate:
        return {"status": "unavailable", "reason": "no overall_performance evidence"}
    families = _families_from_candidate(candidate)
    if not families:
        return {"status": "unavailable", "reason": "no overall comparison facts"}
    comparison = next(
        (fam.get("comparison") for fam in families.values() if fam.get("comparison")),
        "the stated comparison period",
    )
    period = period or {}
    return {
        "status": "ok",
        "families": families,
        "primary_family": "revenue" if "revenue" in families else next(iter(families)),
        "bridge": _bridge(families),
        "comparison": comparison,
        "data_as_of": period.get("data_as_of"),
        "grain": period.get("grain"),
        "freshness_status": period.get("freshness_status"),
        "reconciled": str(candidate.get("coverage")) == "complete",
        "coverage": candidate.get("coverage"),
        "visual": candidate.get("visual"),
        "metrics": candidate.get("metrics") or [],
        "trend": None,  # attached best-effort by the node
    }
