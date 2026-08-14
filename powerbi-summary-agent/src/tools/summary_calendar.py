"""Calendar / comparator awareness for the summary dashboard.

Deterministic, pure functions - no state, no IO, no LLM.

The rule this implements: **if every area moves the same way at once, suspect the
comparator before calling the period good or bad.** A festival that fell inside
the comparison period last year but outside it this year makes the whole estate
look weak simultaneously - which is a calendar artefact, not a trading change.
Reporting that as a business decline is one of the easiest ways for an automated
summary to be confidently wrong.

Two things are deliberately kept apart:

* **The signature** (``uniform_move``) is inferred from the data we already
  scanned - a broad, clustered, same-direction move across the estate. This is
  always computable.
* **The cause** (a named festival shift) is *not* inferable from POS totals. It
  comes from a configured calendar. With no calendar configured the signature
  still fires and says "check the calendar", it just cannot name the festival -
  which is honest, where guessing would not be.

And crucially, a comparator caveat must never become a blanket excuse: whenever
the signature fires, ``exceptions`` names the areas whose movement the comparator
does *not* explain, so real problems still get called out.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

DEFAULT_MIN_MEMBERS = 3
DEFAULT_UNIFORM_COUNT_SHARE_PCT = 80.0
DEFAULT_UNIFORM_BUSINESS_SHARE_PCT = 80.0
DEFAULT_CLUSTER_SPREAD_PCT = 8.0
DEFAULT_EXCEPTION_DEVIATION_PCT = 3.0


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _comparable(members: list[dict]) -> list[dict]:
    """Members with a measurable movement. A current-only area has no comparison
    and therefore cannot be evidence either for or against a comparator effect."""
    out = []
    for member in members or []:
        if _num(member.get("change_pct")) is None:
            continue
        if _num(member.get("prior")) in (None, 0.0):
            continue
        out.append(member)
    return out


def _weight(member: dict) -> float:
    """Business weight for share-weighting. Falls back to prior magnitude when the
    scan did not carry a share, so weighting never silently degrades to counting."""
    share = _num(member.get("business_share_pct"))
    if share is not None:
        return abs(share)
    return abs(_num(member.get("prior")) or 0.0)


def comparator_check(members: list[dict], config: dict | None = None) -> dict:
    """Test one level's members for the broad, clustered, same-direction signature.

    Returns the verdict *and* every measured input, so the caveat can be stated
    honestly whether or not it fires, and a reader can audit why.
    """
    config = config or {}
    min_members = int(config.get("summary_calendar_min_members", DEFAULT_MIN_MEMBERS))
    need_count = float(config.get(
        "summary_calendar_uniform_count_share_pct", DEFAULT_UNIFORM_COUNT_SHARE_PCT))
    need_business = float(config.get(
        "summary_calendar_uniform_business_share_pct", DEFAULT_UNIFORM_BUSINESS_SHARE_PCT))
    max_spread = float(config.get(
        "summary_calendar_cluster_spread_pct", DEFAULT_CLUSTER_SPREAD_PCT))

    comparable = _comparable(members)
    checks = {
        "comparable_members": len(comparable),
        "min_members": min_members,
        "required_count_share_pct": need_count,
        "required_business_share_pct": need_business,
        "max_cluster_spread_pct": max_spread,
    }
    if len(comparable) < min_members:
        return {
            "uniform_move": False,
            "reason": "too few areas with a prior year to read an estate-wide pattern",
            "checks": checks,
        }

    downs = [m for m in comparable if (_num(m.get("change_pct")) or 0.0) < 0]
    ups = [m for m in comparable if (_num(m.get("change_pct")) or 0.0) > 0]
    cohort, direction = (downs, "down") if len(downs) >= len(ups) else (ups, "up")

    count_share = len(cohort) / len(comparable) * 100.0
    total_weight = sum(_weight(m) for m in comparable)
    business_share = (
        sum(_weight(m) for m in cohort) / total_weight * 100.0 if total_weight else 0.0
    )
    moves = [_num(m.get("change_pct")) or 0.0 for m in cohort]
    median = _median(moves)
    low, high = _percentile(moves, 0.1), _percentile(moves, 0.9)
    spread = abs((high or 0.0) - (low or 0.0))

    checks.update({
        "direction": direction,
        "count_share_pct": count_share,
        "business_share_pct": business_share,
        "median_change_pct": median,
        "cluster_spread_pct": spread,
    })
    uniform = (
        count_share >= need_count
        and business_share >= need_business
        and spread <= max_spread
    )
    return {
        "uniform_move": uniform,
        "direction": direction,
        "median_change_pct": median,
        "cluster_spread_pct": spread,
        "count_share_pct": count_share,
        "business_share_pct": business_share,
        "member_count": len(comparable),
        "reason": (
            f"{len(cohort)} of {len(comparable)} areas with a prior year moved {direction} "
            f"together within a {spread:.1f} point spread"
            if uniform else
            "movements are not uniform enough across the estate to point at the comparator"
        ),
        "checks": checks,
    }


def festival_shift(period_anchor: str | None, config: dict | None = None) -> dict | None:
    """Name a configured moveable event that changes the period's comparability.

    ``summary_calendar_events`` is a list of
    ``{"name": str, "current": "YYYY-MM-DD", "prior": "YYYY-MM-DD"}``. An event
    qualifies when it lands inside the anchor month in exactly one of the two
    years - that is precisely when the two periods are not like-for-like.
    Returns ``None`` when nothing is configured; the caller then keeps the
    unnamed signature rather than inventing a cause.
    """
    events = ((config or {}).get("summary_calendar_events") or [])
    anchor = str(period_anchor or "").strip()
    if not events or len(anchor) < 7:
        return None
    try:
        year, month = int(anchor[:4]), int(anchor[5:7])
    except ValueError:
        return None

    def in_anchor_month(value: Any, year_offset: int) -> bool:
        try:
            parsed = date.fromisoformat(str(value))
        except (TypeError, ValueError):
            return False
        return parsed.year == year - year_offset and parsed.month == month

    for event in events:
        if not isinstance(event, dict):
            continue
        current_in = in_anchor_month(event.get("current"), 0)
        prior_in = in_anchor_month(event.get("prior"), 1)
        if current_in == prior_in:
            continue
        name = str(event.get("name") or "A moveable event").strip()
        return {
            "name": name,
            "in_current_period": current_in,
            "in_prior_period": prior_in,
            "current_date": event.get("current"),
            "prior_date": event.get("prior"),
            "statement": (
                f"{name} falls inside this period this year but not last year, so the "
                "comparison is against a weaker base."
                if current_in else
                f"{name} fell inside this period last year but not this year, so the "
                "comparison is against a stronger base."
            ),
        }
    return None


def exceptions(members: list[dict], verdict: dict | None,
               config: dict | None = None,
               reference_members: list[dict] | None = None) -> list[dict]:
    """Areas the comparator does not explain - the ones still worth acting on.

    Two independent qualifying routes, because they catch different things:

    * **deviation** - the area moved materially worse than the estate median, so
      whatever hit everybody hit this one harder.
    * **persistent** - the area is also negative in the reference view (the
      longer YTD read), so its weakness predates the calendar shift. This is the
      stronger signal and is marked as such.

    Ranked worst-first. With no comparator effect detected the caller does not
    need this at all, so an empty verdict yields an empty list.
    """
    config = config or {}
    if not verdict or not verdict.get("uniform_move"):
        return []
    threshold = float(config.get(
        "summary_calendar_exception_deviation_pct", DEFAULT_EXCEPTION_DEVIATION_PCT))
    median = _num(verdict.get("median_change_pct"))
    direction = str(verdict.get("direction") or "down")
    reference = {
        str(member.get("member")): _num(member.get("change_pct"))
        for member in (reference_members or [])
    }

    found: list[dict] = []
    for member in _comparable(members):
        move = _num(member.get("change_pct"))
        if move is None:
            continue
        name = str(member.get("member") or "")
        deviates = (
            median is not None
            and (move < median - threshold if direction == "down" else move > median + threshold)
        )
        reference_move = reference.get(name)
        persistent = (
            reference_move is not None
            and ((reference_move < 0) if direction == "down" else (reference_move > 0))
            and move is not None
            and ((move < 0) if direction == "down" else (move > 0))
        )
        if not (deviates or persistent):
            continue
        if persistent:
            why = (
                "moved the same way in the wider period too, so the weakness predates "
                "the comparator shift"
            )
        else:
            why = (
                f"moved {abs(move - (median or 0.0)):.1f} points further than the estate "
                "median, so the comparator does not account for it"
            )
        found.append({
            "member": name,
            "change_pct": move,
            "reference_change_pct": reference_move,
            "persistent": persistent,
            "deviates": deviates,
            "why": why,
        })
    found.sort(key=lambda item: (not item["persistent"], item["change_pct"]
                                 if direction == "down" else -item["change_pct"]))
    return found


def build(members: list[dict], period: dict | None = None, config: dict | None = None,
          reference_members: list[dict] | None = None) -> dict:
    """The complete calendar read for one view: signature, cause, exceptions."""
    verdict = comparator_check(members, config)
    event = festival_shift((period or {}).get("period_anchor"), config) if verdict.get(
        "uniform_move") else None
    named = exceptions(members, verdict, config, reference_members)
    if not verdict.get("uniform_move"):
        headline = None
    elif event:
        headline = (
            f"{verdict['reason'].capitalize()}. {event['statement']} Check the calendar "
            "before reading this period as a trading change."
        )
    else:
        headline = (
            f"{verdict['reason'].capitalize()} - the signature of a comparator effect "
            "rather than a trading change. Confirm the period is like-for-like "
            "(a moved festival or trading-day shift) before acting on it."
        )
    return {
        "comparator_effect": bool(verdict.get("uniform_move")),
        "verdict": verdict,
        "event": event,
        "exceptions": named,
        "headline": headline,
        "exceptions_note": (
            "These areas are not explained by the comparator and still need attention."
            if named else None
        ),
    }
