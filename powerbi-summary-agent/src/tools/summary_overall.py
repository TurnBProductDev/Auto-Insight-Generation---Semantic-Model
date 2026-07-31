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
