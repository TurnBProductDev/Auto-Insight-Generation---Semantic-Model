"""How fast aged stock is likely to clear, and which lines are stuck.

Three questions that all point at the same decision - what do we do about the
old stock - and that all come from outside the ageing table itself:

* **Clearance outlook.** At the pace a division currently sells, how much of its
  aged stock moves in the next 30 days, and how long would all of it take?
* **The category check.** How many categories have let aged stock grow past a
  configured share of their own stock?
* **The stuck lines.** Which individual products, in which location, are sitting
  at the worst ageing risk with real money against them?

The two value bases, and why they are labelled rather than blended
------------------------------------------------------------------
Clearance and the risk table read the stock-status table, whose stock value is
on a **different basis** from the ageing table - USD 13.03M against USD 5.73M on
the first live pair, close to a 2.3x gap. Neither is wrong; they are different
measures of the same shelves. So nothing here ever adds one to the other, the
clearance outlook is expressed in **units and days** (which the gap does not
touch), and every money column sourced from the stock-status table carries its
own label so a reader is never invited to compare it with the headline.

The clearance estimate is directional and says so
-------------------------------------------------
It assumes each sale takes the oldest stock first. The source does not guarantee
that, so this answers "is this division slow to turn over?" and not "this will
be gone on the 30th". An estimate over 100% is capped for display, because a
division cannot clear more than it holds.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

#: The outlook window the report is built around. Configurable, because 30 days
#: is a review cycle rather than a property of the data.
DEFAULT_HORIZON_DAYS = 30

#: A category above this share of its own stock being aged is called out.
#: A requested check, not a rule in the source model - it can be moved.
DEFAULT_CATEGORY_THRESHOLD_PCT = 30.0

#: At or below this score a line is at or near the worst ageing risk the source
#: model records. The scale runs 0 (healthy) to -100 (worst), so lower is worse.
DEFAULT_RISK_CUTOFF = -70.0

#: Below this there is not enough money on the line to be worth a buyer's time.
DEFAULT_RISK_VALUE_FLOOR = 500.0

#: A division selling nothing at all cannot be given a days-to-clear figure. It
#: is reported as never clearing at the current pace, which is the honest read.
NEVER_CLEARS = "No sales recorded"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _f(value: Any) -> float:
    return _num(value) or 0.0


def _days_text(days: float | None) -> str:
    """Days to clear, written the way a person would say it."""
    if days is None:
        return NEVER_CLEARS
    if days < 1:
        return "under a day"
    if days < 1.5:
        return "about a day"
    if days >= 365:
        return "more than a year"
    return f"about {days:,.0f} days"


def clearance(rows: Sequence[dict], *, horizon_days: int = DEFAULT_HORIZON_DAYS,
              unmapped_velocity: float = 0.0) -> dict:
    """Per-division clearance outlook, ranked slowest first.

    ``rows`` carry ``name``, ``aged_qty``, ``aged_value``, ``total_value`` and
    ``daily_qty`` (units sold per day, summed from the stock-status table).

    Ranked slowest first because the slow ones are the problem; a division that
    turns its aged stock over in a week does not need a manager's attention.
    """
    horizon = max(int(horizon_days or DEFAULT_HORIZON_DAYS), 1)
    out: list[dict] = []
    for row in rows or []:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        aged_qty = _f(row.get("aged_qty"))
        daily = _f(row.get("daily_qty"))
        aged_value = _f(row.get("aged_value"))
        total_value = _f(row.get("total_value"))
        aged_share = (aged_value / total_value * 100.0) if total_value else None
        if aged_qty <= 0:
            cleared_pct, days, tone = 100.0, 0.0, "positive"
        elif daily <= 0:
            cleared_pct, days, tone = 0.0, None, "critical"
        else:
            raw = daily * horizon / aged_qty * 100.0
            cleared_pct = min(raw, 100.0)
            days = aged_qty / daily
            tone = ("positive" if cleared_pct >= 90.0
                    else "warn" if cleared_pct >= 50.0 else "critical")
        out.append({
            "name": name,
            "aged_qty": aged_qty,
            "aged_value": aged_value,
            "total_value": total_value,
            "aged_share_pct": aged_share,
            "daily_qty": daily,
            "cleared_pct": cleared_pct,
            "capped": bool(daily > 0 and aged_qty > 0
                           and daily * horizon / aged_qty * 100.0 > 100.0),
            "days_to_clear": days,
            "days_display": _days_text(days),
            "tone": tone,
        })
    # Slowest first: a low clearance percentage is the thing to act on. Ties
    # broken by how much aged stock is behind the number, so the bigger problem
    # leads when two divisions are equally slow.
    out.sort(key=lambda r: (r["cleared_pct"], -r["aged_value"]))

    total_daily = sum(r["daily_qty"] for r in out) + max(unmapped_velocity, 0.0)
    unmapped_share = ((unmapped_velocity / total_daily * 100.0)
                      if total_daily and unmapped_velocity > 0 else 0.0)
    caveats = [
        f"This assumes each sale takes the oldest stock first, which the source "
        f"data does not guarantee. Read it as 'this division is slow to turn "
        f"over', not as a promise about the next {horizon} days.",
    ]
    if unmapped_share >= 1.0:
        caveats.append(
            f"{unmapped_share:.0f}% of recorded daily sales belong to products "
            f"that are not mapped to a division, so they are not counted in any "
            f"row below. The divisions shown may clear slightly faster than "
            f"these figures suggest.")
    return {"available": bool(out), "horizon_days": horizon, "rows": out,
            "caveats": caveats,
            "slowest": out[0] if out else None,
            "fastest": out[-1] if out else None}


def categories(rows: Sequence[dict], *,
               threshold_pct: float = DEFAULT_CATEGORY_THRESHOLD_PCT,
               top: int = 8) -> dict:
    """How many categories have let aged stock past the threshold, and which.

    Counted over every category that holds any stock at all, so the denominator
    is the number of categories actually carried rather than the number that
    exist in the lookup - an empty category cannot fail a threshold.
    """
    threshold = float(threshold_pct or DEFAULT_CATEGORY_THRESHOLD_PCT)
    carried: list[dict] = []
    for row in rows or []:
        name = str(row.get("name") or "").strip()
        total = _f(row.get("total"))
        if not name or total <= 0:
            continue
        aged = _f(row.get("aged"))
        carried.append({"name": name, "total": total, "aged": aged,
                        "aged_share_pct": aged / total * 100.0})
    over = [c for c in carried if c["aged_share_pct"] > threshold]
    # The COUNT is the check, and it treats every category equally - a category
    # is over the line or it is not. The LIST is a work list, and it is ranked by
    # money stuck rather than by share, because sorting on share alone puts a
    # category holding fifty dollars of entirely-old stock at the top on a
    # perfect 100%. That is a true number and a useless instruction; the
    # categories worth a buyer's morning are the ones with real money behind the
    # percentage.
    worst = sorted(over, key=lambda c: c["aged"], reverse=True)[:max(int(top), 0)]
    return {
        "available": bool(carried),
        "threshold_pct": threshold,
        "carried": len(carried),
        "over": len(over),
        "over_share_pct": (len(over) / len(carried) * 100.0) if carried else None,
        "aged_value_in_over": sum(c["aged"] for c in over),
        "worst": worst,
        "highest_share": max(over, key=lambda c: c["aged_share_pct"]) if over else None,
        "note": (f"Each category is measured against its own stock, so a small "
                 f"category with a bad ratio still counts. The list below is "
                 f"ordered by how much money is stuck, not by the percentage, so "
                 f"the biggest problems come first. {threshold:.0f}% is a review "
                 f"line that can be moved."),
    }


def stuck_lines(rows: Sequence[dict], *,
                risk_cutoff: float = DEFAULT_RISK_CUTOFF,
                value_floor: float = DEFAULT_RISK_VALUE_FLOOR,
                top: int = 10) -> dict:
    """Individual product lines at or near the worst ageing risk.

    Ranked by money at stake rather than by score, because every line here is
    already at the worst end of the scale - the score selects, the value orders.
    """
    kept: list[dict] = []
    for row in rows or []:
        score = _num(row.get("risk_score"))
        value = _f(row.get("value"))
        if score is None or score > risk_cutoff or value < value_floor:
            continue
        daily = _f(row.get("daily_qty"))
        qty = _f(row.get("qty"))
        kept.append({
            "sku": str(row.get("sku") or "Unknown"),
            "category": str(row.get("category") or "Not categorised"),
            "location": str(row.get("location") or "Unknown"),
            "status": _plain_status(row.get("status")),
            "risk_score": score,
            "value": value,
            "qty": qty,
            "daily_qty": daily,
            # A line that sells briskly and is still at worst risk is the most
            # informative row on the table: it means one old batch is stuck
            # behind newer stock, rather than the product being dead.
            "still_selling": daily > 0,
        })
    kept.sort(key=lambda r: r["value"], reverse=True)
    shown = kept[:max(int(top), 0)]
    movers = [r for r in shown if r["still_selling"]]
    return {
        "available": bool(shown),
        "risk_cutoff": risk_cutoff,
        "value_floor": value_floor,
        "matched": len(kept),
        "rows": shown,
        "value_shown": sum(r["value"] for r in shown),
        "still_selling": len(movers),
        "note": ("The ageing risk score runs from 0 (healthy) to -100 (worst) "
                 "and is calculated inside the source report. Stock value in "
                 "this table comes from the stock-status table, which is on a "
                 "different basis from the headline stock value above, so the "
                 "two are not added together."),
    }


def _plain_status(value: Any) -> str:
    """The source's own status wording, tidied for reading but never renamed.

    BR-03 allows one approved name per concept, so a status is title-cased and
    nothing more - inventing a friendlier synonym would put a second name on the
    same thing and break the link back to the source report.
    """
    text = str(value or "").strip()
    if not text:
        return "Not stated"
    return text.title().replace(" And ", " and ").replace(" But ", " but ")
