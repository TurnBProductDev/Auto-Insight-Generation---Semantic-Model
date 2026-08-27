"""Ranked Inventory Management findings for the shared KPI feed.

Recomputes nothing. `stock_health.build` and `health.build` have already derived
the queue, the classifications, the Opportunity Loss scope and the six risks, so
these detectors read them. A second arithmetic path would be a second thing to
keep reconciled, and the first divergence would be invisible - both would look
plausible.

Ranking is exposure-weighted by construction
--------------------------------------------
Every score is a gap expressed as a **share of the base it is measured
against**, never a raw magnitude. BR-34 is explicit that a large percentage on a
trivial slice is not a finding: on this data, one Section can hold a handful of
Loc-SKUs and swing wildly while Excess Stock quietly holds 42% of the whole
position. Scoring on magnitude would rank the first above the second. That is
the same failure the year-on-year coverage ranking exists to prevent, arriving
in a different costume.

Every signal carries an explicit `comparison_label`
---------------------------------------------------
Without one, `api_payloads._assemble_kpi_card` falls through to its share branch
and publishes the finding against *"the prior period"* - a comparison this data
does not contain. A stock position is measured against a policy, a scope or the
whole position, and the label says which. The same reason `prior` is absent
rather than None: an explicit absence cannot be misread as a zero.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Sequence

from . import spines

REPORT_ID = "inventory_stock_health"

#: Below this, a finding is not worth a manager's time (BR-34). Expressed in the
#: same units as every score: percentage points of the base it is measured
#: against.
MIN_SCORE_PCT = 0.5

#: BR-31's two double-warning states. They combine two problems at once and are
#: reported first regardless of value - which is why they are boosted rather
#: than left to compete on share alone. A stockout with no recovery in flight
#: holds no stock value at all, so on value it would rank last.
DOUBLE_WARNING_BOOST = 100.0

#: What counts as critical rather than a watch item, in score points.
CRITICAL_SCORE = 15.0


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _pct(part: Any, whole: Any) -> float | None:
    part_n, whole_n = _num(part), _num(whole)
    if part_n is None or not whole_n:
        return None
    return abs(part_n) / abs(whole_n) * 100.0


def story_key(finding: str, member: str, as_at: str) -> str:
    """A stable identity for one finding about one thing.

    Anchored on the as-at date so the same exception on a new stock position is
    a new story, and a re-run of the same position is not. Deliberately excludes
    the size of the exception: a queue that grows by four lines overnight is the
    same story, not a fresh one.
    """
    canon = json.dumps({"report": REPORT_ID, "finding": finding,
                        "member": (member or "").strip().casefold(),
                        "as_at": as_at}, sort_keys=True)
    return "inv:v1:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:32]


def _severity(score: float, *, double_warning: bool = False) -> str:
    if double_warning or score >= CRITICAL_SCORE:
        return "critical"
    return "warn"


def _signal(*, finding: str, member: str, segment: str, dimension: str,
            metric: str, impact_value: Any, base: Any, as_at: str,
            comparison_label: str, description: str, question: str,
            current: Any = None, score_override: float | None = None,
            double_warning: bool = False, value_label: str = "",
            share_label: str = "", extra: dict | None = None) -> dict:
    share = _pct(impact_value, base)
    score = float(score_override) if score_override is not None else (share or 0.0)
    signal = {
        "candidate_id": f"{finding}:{member or 'company'}",
        "story_key": story_key(finding, member, as_at),
        "kind": "business",
        "analysis_type": finding,
        "spine": spines.SnapshotVsPolicySpine.kind,
        "report_id": REPORT_ID,
        "affected_segment": segment,
        "segment_members": [member] if member else [],
        "dimension": dimension,
        "metric": metric,
        "metric_family": "stock_value",
        "direction": "increase" if (_num(impact_value) or 0.0) >= 0 else "decrease",
        "impact_value": _num(impact_value),
        "impact_share": share,
        "score": score,
        "severity": _severity(score, double_warning=double_warning),
        # `prior` is absent, not None-valued: this model holds one stock
        # position and no prior, and an explicit absence cannot be misread.
        "current": current,
        # ...and because there is no prior, impact_value is a LEVEL - how much
        # is in this state right now - not a movement. Downstream had no way to
        # tell, so it signed the figure and published "+17.2K" for a count of
        # 17,215 Loc-SKUs that had not gone up by anything. Stated explicitly
        # here rather than inferred from the absence of `prior`, because a
        # reader of the card should not have to reconstruct that.
        "value_kind": "level",
        "comparison_label": comparison_label,
        # What the card's two figures actually MEAN, named by the report that
        # computed them. Without these the shared assembler falls back to its
        # year-on-year wording and published "Performance change +18.3K" for a
        # count of products, and "Share of performance increase 317.0%" for a
        # percentage above a three-month average - a share over 100%.
        "value_label": value_label,
        "share_label": share_label,
        "description": description,
        "question": question,
        "as_at": as_at,
    }
    if extra:
        signal.update(extra)
    return signal


def _month_name(value: Any) -> str:
    """"2026-08-01" -> "August 2026".

    A month printed as a first-of-month date reads as a day, and a reader then
    looks for what happened on the 1st. The same reason the sales dashboard
    converts month-of-year codes before they reach a chart encoding.
    """
    text = str(value or "").split("T")[0]
    parts = text.split("-")
    if len(parts) < 2:
        return text
    names = ("January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December")
    try:
        return f"{names[int(parts[1]) - 1]} {parts[0]}"
    except (ValueError, IndexError):
        return text


def _fmt(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:,.0f}"


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def double_warning_states(model: dict, score: dict | None = None) -> list[dict]:
    """BR-31's two double-warning states. Reported first, whatever they hold.

    Scored above every share-based detector rather than competing with them: a
    stockout with no order placed carries no stock value at all, so on any
    value-weighted measure it ranks last. What makes it urgent is that two
    problems coincide, and that is not a quantity.
    """
    as_at = str(model.get("as_at") or "")
    total_rows = _num((model.get("header") or {}).get("loc_skus")) or 0.0
    out = []
    for row in model.get("double_warnings") or []:
        lines = int(_num(row.get("loc_skus")) or 0)
        if not lines:
            continue
        action = str(row.get("action") or "")
        share = _pct(lines, total_rows) or 0.0
        out.append(_signal(
            finding="inventory_double_warning",
            member=action, segment=action, dimension="recommended_action",
            metric="Loc-SKUs in a double-warning state",
            value_label="Products in stores affected",
            share_label="Share of all products in stores",
            impact_value=lines, base=total_rows, as_at=as_at,
            current=lines,
            score_override=DOUBLE_WARNING_BOOST + share,
            double_warning=True,
            # The share belongs IN the clause. Published without it, the card
            # showed "of all Loc-SKUs in the stock position" directly beneath
            # the count, so the tile asserted that 17.2K was the share - a
            # false sentence assembled from two true halves.
            comparison_label=f"{share:.1f}% of all Loc-SKUs in the stock position",
            description=(
                f"{_fmt(lines)} Loc-SKUs are in {action}, "
                f"{share:.1f}% of the {_fmt(total_rows)} in the position. "
                f"{row.get('guidance') or ''}".strip()),
            question=(f"Which Divisions and Locations hold the {action} "
                      f"Loc-SKUs, and how long have they been there?"),
            extra={"loc_skus": lines, "recommended_action": action},
        ))
    return out


def urgent_state_never_reported(model: dict, score: dict | None = None) -> list[dict]:
    """A double-warning state the data never returned.

    An empty state and a state the source system does not produce look
    identical on a page - the row simply is not there - and only one of them is
    good news. `NON MOVING - ORDER PLACED` has zero rows on every model measured
    so far, and it is one of the two BR-31 names as most urgent.
    """
    as_at = str(model.get("as_at") or "")
    out = []
    for state in model.get("states_absent_urgent") or []:
        out.append(_signal(
            finding="inventory_urgent_state_absent",
            member=state, segment=state, dimension="recommended_action",
            metric="Loc-SKUs in a double-warning state",
            value_label="Products in stores affected",
            share_label="Share of all products in stores",
            impact_value=0.0, base=None, as_at=as_at, current=0,
            score_override=CRITICAL_SCORE,
            comparison_label="against the states the rules say to expect",
            description=(
                f"0 Loc-SKUs came back in {state}. The rules list this as one "
                f"of the two most urgent situations in the report, so either "
                f"nothing is currently in it or the source system is not "
                f"producing it."),
            question=(f"Does the source system produce the {state} state at "
                      f"all, and if so when was it last populated?"),
            extra={"data_quality": True},
        ))
    # This is a question about the data, not about the stock.
    for signal in out:
        signal["kind"] = "data_quality"
    return out


def excess_stock_share(model: dict, score: dict | None = None) -> list[dict]:
    """Excess Stock as a share of Stock Value (BR-20, BR-34).

    Excess is the portion held above the agreed cover, never the whole value
    of an overstocked line, and the description says so - the two differ by
    millions and only one of them is the number to act on. BR-03 bans
    "surplus" as a name for it, so the wording is BR-20's own.
    """
    header = model.get("header") or {}
    excess = _num(header.get("excess_value"))
    stock = _num(header.get("stock_value"))
    share = _pct(excess, stock)
    if not excess or not stock or share is None:
        return []
    return [_signal(
        finding="inventory_excess_share",
        member="", segment="All Locations", dimension="company",
        metric="Excess Stock",
        value_label="Stock above the planned level",
        share_label="Share of total stock value",
        impact_value=excess, base=stock, as_at=str(model.get("as_at") or ""),
        current=excess,
        comparison_label=f"{share:.1f}% of total Stock Value",
        description=(
            f"{_fmt(excess)} is held above the agreed cover, {share:.1f}% of "
            f"the {_fmt(stock)} Stock Value. That is the portion held above "
            f"cover only, not the whole value of the overstocked Loc-SKUs."),
        question=("Which Divisions and Sections hold the most above their "
                  "agreed cover, and are their thresholds still right?"),
    )]


def unwanted_skus(model: dict, score: dict | None = None) -> list[dict]:
    """BR-28: in Pending Orders and already carrying Excess Stock.

    Counted in unique SKUs rather than Loc-SKUs, because the classification is
    reported across Locations (BR-26). Scored against Pending Orders Value: the
    question is how much of what is on its way is unwanted.
    """
    header = model.get("header") or {}
    skus = _num(header.get("unwanted_skus"))
    value = _num(header.get("unwanted_pending_value"))
    pending = _num(header.get("pending_value"))
    if not skus:
        return []
    share = _pct(value, pending)
    return [_signal(
        finding="inventory_unwanted_skus",
        member="", segment="All Locations", dimension="company",
        metric="Unwanted SKUs in Pending Orders",
        impact_value=value if value is not None else skus,
        base=pending, as_at=str(model.get("as_at") or ""),
        current=int(skus),
        score_override=share if share is not None else MIN_SCORE_PCT,
        comparison_label="of Pending Orders Value",
        description=(
            f"{_fmt(skus)} SKUs already carrying Excess Stock have more stock "
            f"on order, worth {_fmt(value)}"
            + (f", {share:.1f}% of the {_fmt(pending)} Pending Orders Value."
               if share is not None else ".")
            + " The rules call this one of the most actionable signals in the "
              "report."),
        question=("Can the open orders on these SKUs be cancelled or deferred, "
                  "and why were they raised against lines already above cover?"),
        extra={"unwanted_skus": int(skus)},
    )]


def critical_stockouts(model: dict, score: dict | None = None) -> list[dict]:
    """Out of Stock among Critical SKUs, with its Opportunity Loss (BR-07, BR-16).

    The Opportunity Loss quoted is the scoped figure - critical segments, local
    procurement, stores only. The unscoped column is roughly six times larger
    and is not comparable, so it is named as a contrast and never published as
    the figure.
    """
    header = model.get("header") or {}
    skus = _num(header.get("critical_stockout_skus"))
    opp = _num(header.get("opportunity_loss_day"))
    all_skus = _num(header.get("skus"))
    if not skus:
        return []
    share = _pct(skus, all_skus)
    return [_signal(
        finding="inventory_critical_stockout",
        member="", segment="Stores", dimension="company",
        metric="Critical SKUs out of stock",
        impact_value=skus, base=all_skus,
        as_at=str(model.get("as_at") or ""), current=int(skus),
        comparison_label="of all SKUs in the stock position",
        description=(
            f"{_fmt(skus)} Critical SKUs are out of stock at stores"
            + (f", {share:.1f}% of the {_fmt(all_skus)} SKUs held" if share is not None else "")
            + (f", with an estimated {_fmt(opp)} a day of Opportunity Loss."
               if opp else ".")
            + " Opportunity Loss is an estimate from average daily sales and "
              "retail price, for critical SKUs at stores only. It is not "
              "confirmed lost revenue."),
        question=("Which Critical SKUs are out of stock at more than one Store, "
                  "and is warehouse stock available to transfer?"),
        extra={"opportunity_loss_day": opp},
    )]


def non_moving_oldest_band(model: dict, score: dict | None = None) -> list[dict]:
    """Non-Moving stock in the oldest band (BR-25).

    The band furthest from a sale is where obsolescence risk sits, so it is
    scored against the whole Non-Moving population rather than against total
    stock - the question is how much of what is not selling has stopped
    entirely.
    """
    bands = model.get("non_moving_bands") or []
    if not bands:
        return []
    oldest = bands[-1]
    name = str(oldest.get("name") or "")
    value = _num(oldest.get("stock_value"))
    lines = int(_num(oldest.get("loc_skus")) or 0)
    total = sum(_num(b.get("stock_value")) or 0.0 for b in bands)
    share = _pct(value, total)
    if not value or share is None:
        return []
    return [_signal(
        finding="inventory_non_moving_oldest",
        member=name, segment=f"Non-Moving {name} days", dimension="non_moving_band",
        metric="Non-Moving Stock Value in the oldest band",
        impact_value=value, base=total,
        as_at=str(model.get("as_at") or ""), current=value,
        comparison_label="of all Non-Moving Stock Value",
        description=(
            f"{_fmt(value)} sits in the {name} day Non-Moving band across "
            f"{_fmt(lines)} Loc-SKUs, {share:.1f}% of the {_fmt(total)} that is "
            f"not moving. Obsolescence risk rises with every band."),
        question=("Which Divisions hold the oldest Non-Moving stock, and has "
                  "any of it been through a clearance already?"),
        extra={"band": name, "loc_skus": lines},
    )]


def damage_against_trend(model: dict, score: dict | None = None) -> list[dict]:
    """The latest month's Damage against the months before it (BR-29).

    Scored against the mean of the earlier months, so a spike is measured
    against what is normal for this business rather than against zero. Reported
    only when it is above that mean: Damage falling is not a finding here.
    """
    months = [m for m in (model.get("damage") or []) if _num(m.get("value"))]
    if len(months) < 3:
        return []
    latest = months[-1]
    earlier = months[:-1]
    baseline = sum(_num(m.get("value")) or 0.0 for m in earlier) / len(earlier)
    value = _num(latest.get("value")) or 0.0
    if not baseline or value <= baseline:
        return []
    excess = value - baseline
    share = _pct(excess, baseline) or 0.0
    return [_signal(
        finding="inventory_damage_spike",
        member=str(latest.get("month") or ""), segment="All Locations",
        dimension="month", metric="Damage Value",
        impact_value=excess, base=baseline,
        as_at=str(model.get("as_at") or ""), current=value,
        comparison_label=f"against the average of the previous {len(earlier)} months",
        value_label="Damage above the usual level",
        share_label=f"Above the {len(earlier)}-month average",
        description=(
            f"Damage in {_month_name(latest.get('month'))} was {_fmt(value)}, "
            f"{share:.1f}% "
            f"above the {_fmt(baseline)} average of the previous "
            f"{len(earlier)} months."),
        question=("Which Sections and Locations drove the Damage in that month, "
                  "and is it concentrated in one supplier or SKU type?"),
        extra={"month": str(latest.get("month") or "")},
    )]


def risk_at_cap(model: dict, score: dict | None = None) -> list[dict]:
    """A health-score risk that has hit its cap.

    Worth reporting on its own: once a risk is capped the score stops moving
    when the underlying position gets worse, so the score alone will understate
    it from here. Scored by its share of the whole points loss.
    """
    if not score:
        return []
    as_at = str(model.get("as_at") or "")
    out = []
    for risk in score.get("risks") or []:
        if not risk.get("at_cap"):
            continue
        share = risk.get("share_of_loss_pct") or 0.0
        out.append(_signal(
            finding="inventory_risk_at_cap",
            member=risk["name"], segment=risk["name"], dimension="health_risk",
            metric=f"{risk['name']} risk points",
            impact_value=risk["points"], base=score.get("points_lost"),
            as_at=as_at, current=risk["points"],
            score_override=share,
            comparison_label="of the Inventory Health Score points lost",
            description=(
                f"{risk['name']} has reached the most a single risk can cost "
                f"the Inventory Health Score ({risk['points']:.1f} points, "
                f"{share:.1f}% of the loss). The score cannot show this getting "
                f"any worse, so read the underlying figure rather than the "
                f"points."),
            question=(f"How far past the cap is {risk['name']}, and which "
                      f"Divisions account for most of it?"),
            extra={"risk": risk["key"], "points": risk["points"]},
        ))
    return out


def state_changes(model: dict, score: dict | None = None) -> list[dict]:
    """Appeared, persisted or cleared, against the archived stock position.

    Only produced when `archive.compare_window` said the two positions are
    genuinely comparable. When it did not - first run, an archive outside the
    window, or an as-at stamp that did not advance - there is nothing to compare
    and this returns nothing rather than a movement of zero.
    """
    window = model.get("comparison") or {}
    if not window.get("comparable"):
        return []
    changes = model.get("state_changes") or []
    as_at = str(model.get("as_at") or "")
    label = window.get("label") or "since the last stock position"
    total_rows = _num((model.get("header") or {}).get("loc_skus")) or 0.0
    out = []
    for change in changes:
        action = str(change.get("action") or "")
        kind = str(change.get("kind") or "")
        delta = _num(change.get("change")) or 0.0
        if not action or not kind:
            continue
        share = _pct(delta, total_rows) or 0.0
        verb = {"appeared": "now has", "cleared": "no longer has",
                "worsened": "has grown to", "eased": "has fallen to"}.get(kind, "has")
        out.append(_signal(
            finding=f"inventory_state_{kind}",
            member=action, segment=action, dimension="recommended_action",
            metric="Loc-SKUs in a Recommended Action state",
            value_label="Products in stores affected",
            share_label="Share of all products in stores",
            impact_value=delta, base=total_rows, as_at=as_at,
            current=_num(change.get("current")),
            double_warning=bool(change.get("double_warning")),
            comparison_label=label,
            description=(
                f"{action} {verb} {_fmt(change.get('current'))} Loc-SKUs, "
                f"{'up' if delta > 0 else 'down'} {_fmt(abs(delta))} {label}."),
            question=(f"What moved into or out of {action} {label}?"),
            extra={"change_kind": kind, "recommended_action": action},
        ))
    return out


#: Order is documentation only - `detect` ranks by score. The double-warning
#: detectors lead through their boost, not through their position here.
DETECTORS: tuple[Callable[..., list], ...] = (
    double_warning_states,
    urgent_state_never_reported,
    state_changes,
    unwanted_skus,
    excess_stock_share,
    critical_stockouts,
    non_moving_oldest_band,
    damage_against_trend,
    risk_at_cap,
)


def detect(model: dict, score: dict | None = None, *, limit: int | None = None,
           min_score_pct: float = MIN_SCORE_PCT) -> list[dict]:
    """Every supported finding, ranked by the share of its own base it moves.

    A quiet position legitimately produces few signals. That is an honest
    result, not an empty one, and nothing here pads the list to reach a count.
    """
    signals: list[dict] = []
    for detector in DETECTORS:
        signals.extend(detector(model, score) or [])
    signals = [s for s in signals if (s.get("score") or 0.0) >= float(min_score_pct)]
    signals.sort(key=lambda s: (-(s.get("score") or 0.0), str(s.get("candidate_id"))))
    if limit is not None:
        signals = signals[: max(0, int(limit))]
    for index, signal in enumerate(signals, start=1):
        signal["id"] = f"I{index}"
    return signals


def state_diff(current_queue: Sequence[dict], prior_queue: Sequence[dict]) -> list[dict]:
    """Which Recommended Action states appeared, cleared or moved materially.

    Pure, and separate from the detectors so it can be computed by the runner
    once the archive has said the two positions are comparable. A state present
    in one position and absent from the other is an appearance or a clearance;
    a state in both is reported only when it moved by more than a rounding.
    """
    def by_action(rows: Sequence[dict]) -> dict:
        return {str(r.get("action") or "").upper(): r for r in rows or []}

    now, before = by_action(current_queue), by_action(prior_queue)
    out = []
    for action in sorted(set(now) | set(before)):
        current = int(_num((now.get(action) or {}).get("loc_skus")) or 0)
        prior = int(_num((before.get(action) or {}).get("loc_skus")) or 0)
        if current == prior:
            continue
        row = now.get(action) or before.get(action) or {}
        if prior == 0:
            kind = "appeared"
        elif current == 0:
            kind = "cleared"
        else:
            kind = "worsened" if current > prior else "eased"
        out.append({
            "action": row.get("action") or action,
            "kind": kind,
            "current": current,
            "prior": prior,
            "change": current - prior,
            "double_warning": bool(row.get("double_warning")),
        })
    out.sort(key=lambda r: -abs(r["change"]))
    return out
