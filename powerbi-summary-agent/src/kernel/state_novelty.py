"""Novelty for a state that persists, rather than a period that ends.

Every existing novelty rule anchors on a period: a new month is a new story, a
re-run of the same month is suppressed. A stock exception has no period. "Below
reorder point" is simply *true today*, and it was true yesterday, and it may be
true tomorrow.

The behaviour to get right (brief WP6): **"below reorder point, day 9" must not
be re-announced as brand new every morning, but must speak up when it worsens or
clears.** A report that repeats yesterday's warning verbatim trains its reader to
stop opening it, which costs more than the finding was worth.

Three things make a persisting state worth saying again
-------------------------------------------------------
1. **It changed** - within policy to below reorder, or excess to within policy.
   A clearance is news as much as an onset is; a report that only ever announces
   problems never tells you one is over.
2. **It got materially worse** - deeper outside the band, or more value exposed.
   A threshold, not any movement, or drift re-announces it daily.
3. **It crossed a duration milestone** - day 7, day 14, day 30. Time itself is
   the finding when nothing else moves: an exception outstanding for a month is
   a different conversation from the same one on day two.

Duration is deliberately NOT part of the key
--------------------------------------------
If it were, every day would mint a new identity and nothing would ever be
suppressed - which is the exact failure this module exists to prevent. The key
is the state; the duration is a mutable property of the record.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Mapping, Sequence

#: Days at which a still-outstanding exception is worth repeating.
DEFAULT_MILESTONES: tuple[int, ...] = (7, 14, 30, 60, 90)

#: How much deeper outside the band counts as "materially worse", in percent of
#: the previous distance. Below this it is drift, not news.
DEFAULT_ESCALATION_PCT = 25.0

#: How much more value exposed counts as materially worse.
DEFAULT_EXPOSURE_ESCALATION_PCT = 25.0


@dataclass(frozen=True)
class StateVerdict:
    """Whether a state is worth reporting, and why."""

    report: bool
    reason: str
    #: onset | cleared | changed | escalated | milestone | unchanged | first_seen
    kind: str
    days_in_state: int = 0
    detail: dict = field(default_factory=dict)

    def summary(self) -> str:
        return (f"{self.kind}: {'report' if self.report else 'suppress'} "
                f"(day {self.days_in_state}) - {self.reason}")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    text = text.split("T", 1)[0]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def days_between(earlier: Any, later: Any) -> int:
    """Whole days between two dates, floored at zero.

    Counted from the observation dates themselves, not from run count, so a
    weekend without a run does not reset a duration - the state persisted
    whether or not anyone looked.
    """
    start, end = _as_date(earlier), _as_date(later)
    if start is None or end is None:
        return 0
    return max(0, (end - start).days)


def state_key(components: Mapping[str, Any]) -> str:
    """A stable identity for a state. Duration is excluded on purpose."""
    import hashlib
    import json

    canon = {k: v for k, v in sorted(components.items())
             if k not in ("days_in_state", "first_seen", "observed_at")}
    blob = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
    return "state:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def judge(stored: Mapping[str, Any] | None,
          current: Mapping[str, Any],
          *,
          observed_at: Any = None,
          milestones: Sequence[int] = DEFAULT_MILESTONES,
          escalation_pct: float = DEFAULT_ESCALATION_PCT,
          exposure_escalation_pct: float = DEFAULT_EXPOSURE_ESCALATION_PCT
          ) -> StateVerdict:
    """Should this state be reported today?

    ``stored`` is the record from the last run (None on the first ever sighting).
    ``current`` carries at least ``state``, and optionally ``distance`` (how far
    outside the band) and ``exposure`` (value at risk).
    """
    now = observed_at or current.get("observed_at")
    state = str(current.get("state") or "unknown")

    if stored is None:
        return StateVerdict(
            True, "this exception has not been reported before", "first_seen",
            days_in_state=0,
            detail={"state": state})

    previous_state = str(stored.get("state") or "unknown")
    first_seen = stored.get("first_seen") or stored.get("last_seen")
    days = days_between(first_seen, now)

    # 1. The state changed. Both directions are news - a clearance especially,
    # because a report that only announces problems never closes one.
    if state != previous_state:
        healthy = {"within_policy", "no_policy", "inactive"}
        kind = "cleared" if state in healthy and previous_state not in healthy else (
            "onset" if previous_state in healthy and state not in healthy else "changed")
        return StateVerdict(
            True,
            f"the position moved from {previous_state.replace('_', ' ')} to "
            f"{state.replace('_', ' ')}",
            kind, days_in_state=0,
            detail={"from": previous_state, "to": state})

    # 2. It got materially worse. A threshold, so ordinary drift stays quiet.
    worse, note = _escalated(stored, current, escalation_pct, exposure_escalation_pct)
    if worse:
        return StateVerdict(True, note, "escalated", days_in_state=days,
                            detail={"state": state})

    # 3. A duration milestone. Time is the finding when nothing else moved.
    reported_days = int(_num(stored.get("reported_at_days")) or -1)
    crossed = [m for m in sorted(milestones) if reported_days < m <= days]
    if crossed:
        milestone = crossed[-1]
        return StateVerdict(
            True,
            f"still {state.replace('_', ' ')} after {milestone} days",
            "milestone", days_in_state=days,
            detail={"milestone": milestone, "state": state})

    return StateVerdict(
        False,
        f"unchanged since it was last reported {days} day(s) ago",
        "unchanged", days_in_state=days, detail={"state": state})


def _escalated(stored: Mapping[str, Any], current: Mapping[str, Any],
               distance_pct: float, exposure_pct: float) -> tuple[bool, str]:
    """Materially worse on distance outside the band, or on value exposed."""
    was, now = _num(stored.get("distance")), _num(current.get("distance"))
    if was is not None and now is not None and was != 0:
        # Deeper outside the band, in the direction it was already outside.
        if abs(now) > abs(was) * (1.0 + distance_pct / 100.0) and _same_side(was, now):
            return True, (f"it moved further outside the policy - from "
                          f"{abs(was):.0f} to {abs(now):.0f} days past the limit")

    was_value, now_value = _num(stored.get("exposure")), _num(current.get("exposure"))
    if was_value is not None and now_value is not None and was_value != 0:
        if abs(now_value) > abs(was_value) * (1.0 + exposure_pct / 100.0):
            return True, (f"the value exposed to it grew from {abs(was_value):,.0f} "
                          f"to {abs(now_value):,.0f}")
    return False, ""


def _same_side(was: float, now: float) -> bool:
    return (was >= 0) == (now >= 0)


def advance(stored: Mapping[str, Any] | None,
            current: Mapping[str, Any],
            verdict: StateVerdict,
            *,
            observed_at: Any = None) -> dict:
    """The record to persist after a run.

    ``first_seen`` resets only when the state genuinely changed, so a duration
    measures how long *this* position has held. ``reported_at_days`` advances
    only when something was actually reported, which is what stops a milestone
    firing twice.
    """
    now = observed_at or current.get("observed_at")
    state = str(current.get("state") or "unknown")
    changed = verdict.kind in ("first_seen", "onset", "cleared", "changed")
    first_seen = now if changed else (
        (stored or {}).get("first_seen") or (stored or {}).get("last_seen") or now)

    record = {
        "state": state,
        "first_seen": _text(first_seen),
        "last_seen": _text(now),
        "days_in_state": days_between(first_seen, now),
        "distance": _num(current.get("distance")),
        "exposure": _num(current.get("exposure")),
        "reported_at_days": (
            days_between(first_seen, now) if verdict.report
            else int(_num((stored or {}).get("reported_at_days")) or -1)),
        "times_reported": int(_num((stored or {}).get("times_reported")) or 0)
        + (1 if verdict.report else 0),
    }
    return record


def _text(value: Any) -> str | None:
    resolved = _as_date(value)
    return resolved.isoformat() if resolved else (str(value) if value else None)
