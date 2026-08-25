"""Comparing today's stock position against an earlier one - honestly.

Two different histories now exist, and they answer different questions. They are
kept apart deliberately, because collapsing them would produce a comparison
whose window silently changes length.

* **The model's own history table** (`REP_SSR_SAG_HIST`) is a *reference
  position* frozen by the source system. It moves only when the source system
  re-freezes it, so the window it defines is not a day and not a week - it is
  "since whenever that snapshot was taken". That is the `reference` lane.
* **The pipeline's own archive** (`archive.py`) is one kept scan per run date.
  That is the `day-on-day` lane, and it is what the trend chart is built from.

The value trap this module exists to refuse
-------------------------------------------
The first live pair (14 Aug against 23 Aug) showed total stock value falling
59% while quantity rose 55%. A report that printed "stock nearly halved" would
have been wrong, and confidently so.

The discriminator is not a judgement call, it is measurable. At one location the
quantity was **byte-identical** across the two dates (79,838.25944 both times)
while its value moved to 27% of what it had been. Stock that did not move cannot
lose 73% of its worth, so the change is in how VALUE is calculated, not in what
is on the shelf. `basis_check` looks for exactly that signature and, when it
finds it, withholds every absolute value comparison and says why.

What survives a basis change, and why
-------------------------------------
A **share** is a ratio of two figures taken from the same table on the same
date, so whatever rescaled them cancels. Aged share of value, aged share of
units, each band's share of the mix, and every distinct count are therefore
comparable whether or not the basis moved - and on the first live pair they all
agreed that ageing had worsened, which is the finding the page should carry.

Nothing here reads a semantic model. It takes scanned rows and returns a model.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from . import buckets

#: A location whose quantity is unchanged within this tolerance is treated as
#: "the same stock" for the purposes of the basis test below. Not zero, because
#: the source carries fractional quantities and a float round-trip is not exact.
UNCHANGED_QTY_TOLERANCE_PCT = 0.5

#: Beyond this, a location's value-per-unit has moved by more than trading
#: explains. Deliberately generous: real mix change inside a location moves this
#: figure a little, and the test is meant to catch a rebasing, not a busy week.
UNIT_VALUE_SHIFT_PCT = 15.0

#: How much of the estate must show that shift before the whole comparison is
#: called unsafe. One rescaled store is a store problem; a third of the money is
#: a basis change.
UNSAFE_VALUE_SHARE_PCT = 20.0

#: Below this a movement is noise, and calling it out wastes a reader's time.
MATERIAL_POINTS = 0.2


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _f(value: Any) -> float:
    return _num(value) or 0.0


def _share_pct(part: Any, whole: Any) -> float | None:
    part_val, whole_val = _num(part), _num(whole)
    if part_val is None or not whole_val:
        return None
    return part_val / whole_val * 100.0


def _ratio(now: Any, then: Any) -> float | None:
    now_val, then_val = _num(now), _num(then)
    if now_val is None or not then_val:
        return None
    return now_val / then_val


def basis_check(pairs: Sequence[dict]) -> dict:
    """Did the meaning of VALUE change between the two positions?

    ``pairs`` is one entry per location present on both dates, each carrying
    ``name``, ``value_now``/``value_then`` and ``qty_now``/``qty_then``.

    The strongest evidence is a location whose **quantity did not change** while
    its value did: nothing left the shelf, so nothing should have left the
    valuation. That is reported as `proof`. The weaker, estate-wide evidence is
    the share of today's value sitting where value-per-unit has moved beyond
    `UNIT_VALUE_SHIFT_PCT`.
    """
    usable = [p for p in pairs or []
              if _f(p.get("qty_now")) > 0 and _f(p.get("qty_then")) > 0
              and _f(p.get("value_now")) > 0 and _f(p.get("value_then")) > 0]
    if not usable:
        return {"value_comparable": True, "checked": False, "proof": None,
                "shifted_share_pct": None, "members": [],
                "reason": "No location could be matched on both dates, so no "
                          "check of the valuation basis was possible."}

    members: list[dict] = []
    proof: dict | None = None
    for pair in usable:
        qty_now, qty_then = _f(pair["qty_now"]), _f(pair["qty_then"])
        value_now, value_then = _f(pair["value_now"]), _f(pair["value_then"])
        unit_now, unit_then = value_now / qty_now, value_then / qty_then
        qty_move = abs(qty_now - qty_then) / qty_then * 100.0
        unit_move = (unit_now / unit_then - 1.0) * 100.0
        entry = {
            "name": str(pair.get("name") or "Unknown"),
            "value_now": value_now, "value_then": value_then,
            "qty_now": qty_now, "qty_then": qty_then,
            "unit_value_now": unit_now, "unit_value_then": unit_then,
            "qty_move_pct": qty_move, "unit_value_move_pct": unit_move,
            "shifted": abs(unit_move) > UNIT_VALUE_SHIFT_PCT,
        }
        members.append(entry)
        # The decisive case: same stock on the shelf, different money against it.
        if (qty_move <= UNCHANGED_QTY_TOLERANCE_PCT
                and abs(unit_move) > UNIT_VALUE_SHIFT_PCT
                and (proof is None
                     or abs(unit_move) > abs(proof["unit_value_move_pct"]))):
            proof = entry

    total_now = sum(m["value_now"] for m in members) or 1.0
    shifted_share = sum(m["value_now"] for m in members if m["shifted"]) / total_now * 100.0
    unsafe = bool(proof) or shifted_share >= UNSAFE_VALUE_SHARE_PCT

    if not unsafe:
        reason = ("Stock value per unit is broadly unchanged between the two "
                  "dates, so value can be compared directly.")
    elif proof:
        reason = (
            f"{proof['name']} holds the same quantity of stock on both dates "
            f"({proof['qty_now']:,.0f} units) but its value has moved from "
            f"{proof['unit_value_then']:.2f} to {proof['unit_value_now']:.2f} "
            f"per unit. Stock that did not move cannot change in worth, so the "
            f"way stock value is calculated has changed between the two dates. "
            f"Value figures are therefore not compared here.")
    else:
        reason = (
            f"{shifted_share:.0f}% of today's stock value sits in locations "
            f"where value per unit has moved by more than "
            f"{UNIT_VALUE_SHIFT_PCT:.0f}%. That is more than trading explains, "
            f"so the way stock value is calculated appears to have changed and "
            f"value figures are not compared here.")

    return {"value_comparable": not unsafe, "checked": True, "proof": proof,
            "shifted_share_pct": shifted_share, "members": members,
            "reason": reason}


def _band_mix(bands: Sequence[dict], value_key: str, qty_key: str) -> dict:
    """One date's band profile, keyed by band name, with mix shares."""
    rows: dict[str, dict] = {}
    total_value = sum(_f(b.get(value_key)) for b in bands or [])
    total_qty = sum(_f(b.get(qty_key)) for b in bands or [])
    for band in bands or []:
        name = str(band.get("name") or band.get("band") or "").strip()
        if not name:
            continue
        entry = rows.setdefault(name, {"value": 0.0, "qty": 0.0, "skus": 0.0})
        entry["value"] += _f(band.get(value_key))
        entry["qty"] += _f(band.get(qty_key))
        entry["skus"] += _f(band.get("skus"))
    for entry in rows.values():
        entry["value_share_pct"] = _share_pct(entry["value"], total_value)
        entry["qty_share_pct"] = _share_pct(entry["qty"], total_qty)
    return {"bands": rows, "total_value": total_value, "total_qty": total_qty}


def _aged_totals(mix: dict) -> dict:
    """Aged and high-risk totals derived from a band profile.

    Derived from the bands rather than read from a flag, because the source
    model's own nine-month flag does not include the 24+ month band - it returns
    the 9-12 and 12-24 bands only, which understates the oldest and worst stock.
    Summing the bands is the definition this report uses throughout, and using
    it on both dates is what makes the two sides comparable.
    """
    aged_floor = buckets.band_index("09-12 MONTHS")
    aged_names = {n for n in mix["bands"]
                  if aged_floor <= buckets.band_index(n) < len(buckets.NEW_AGE_ORDER)}
    high_names = {n for n in mix["bands"] if buckets.is_high_risk(n)}
    aged_value = sum(mix["bands"][n]["value"] for n in aged_names)
    aged_qty = sum(mix["bands"][n]["qty"] for n in aged_names)
    high_value = sum(mix["bands"][n]["value"] for n in high_names)
    return {
        "aged_value": aged_value,
        "aged_qty": aged_qty,
        "high_risk_value": high_value,
        "aged_value_share_pct": _share_pct(aged_value, mix["total_value"]),
        "aged_qty_share_pct": _share_pct(aged_qty, mix["total_qty"]),
        "high_risk_share_pct": _share_pct(high_value, mix["total_value"]),
    }


def _points(now: Any, then: Any) -> float | None:
    now_val, then_val = _num(now), _num(then)
    if now_val is None or then_val is None:
        return None
    return now_val - then_val


def _direction(points: float | None) -> str:
    """Higher is worse for every share on this page."""
    if points is None or abs(points) < MATERIAL_POINTS:
        return "flat"
    return "worse" if points > 0 else "better"


def build(current: dict, history: dict, *, label: str = "reference") -> dict:
    """Compare two stock positions.

    ``current`` and ``history`` each carry ``as_at``, ``bands`` (name/value/qty/
    skus), ``locations`` and ``divisions`` (name/value/qty/aged), and ``skus``.

    Returns a model in which every figure is either a share, a count or a
    quantity - and in which absolute value movement is present only when
    `basis_check` has cleared it.
    """
    as_at = str(current.get("as_at") or "")
    prior_as_at = str(history.get("as_at") or "")
    if not history.get("bands"):
        return _unavailable(label, as_at, prior_as_at,
                            "No earlier stock position was returned, so there "
                            "is nothing to compare today against.")
    if not prior_as_at or not as_at:
        return _unavailable(label, as_at, prior_as_at,
                            "One of the two positions carries no date, so the "
                            "comparison window cannot be stated honestly.")
    if prior_as_at[:10] >= as_at[:10]:
        return _unavailable(
            label, as_at, prior_as_at,
            f"The earlier position is dated {prior_as_at[:10]}, which is not "
            f"before today's {as_at[:10]}, so no movement can be measured.")

    now_mix = _band_mix(current.get("bands") or [], "value", "qty")
    then_mix = _band_mix(history.get("bands") or [], "value", "qty")
    now_aged = _aged_totals(now_mix)
    then_aged = _aged_totals(then_mix)

    location_pairs = _pair_members(current.get("locations") or [],
                                   history.get("locations") or [])
    basis = basis_check(location_pairs)

    band_rows = []
    for name in sorted(set(now_mix["bands"]) | set(then_mix["bands"]),
                       key=buckets.band_index):
        now_band = now_mix["bands"].get(name) or {}
        then_band = then_mix["bands"].get(name) or {}
        share_points = _points(now_band.get("value_share_pct"),
                               then_band.get("value_share_pct"))
        band_rows.append({
            "name": name,
            "high_risk": buckets.is_high_risk(name),
            "qty_now": _f(now_band.get("qty")),
            "qty_then": _f(then_band.get("qty")),
            "qty_change": _f(now_band.get("qty")) - _f(then_band.get("qty")),
            "value_share_now_pct": now_band.get("value_share_pct"),
            "value_share_then_pct": then_band.get("value_share_pct"),
            "value_share_points": share_points,
            "qty_share_now_pct": now_band.get("qty_share_pct"),
            "qty_share_then_pct": then_band.get("qty_share_pct"),
            "qty_share_points": _points(now_band.get("qty_share_pct"),
                                        then_band.get("qty_share_pct")),
            "direction": _direction(share_points),
        })

    aged_value_points = _points(now_aged["aged_value_share_pct"],
                                then_aged["aged_value_share_pct"])
    aged_qty_points = _points(now_aged["aged_qty_share_pct"],
                              then_aged["aged_qty_share_pct"])
    high_points = _points(now_aged["high_risk_share_pct"],
                          then_aged["high_risk_share_pct"])

    headlines = [
        {"key": "aged_value_share", "label": "Aged share of stock value",
         "now_pct": now_aged["aged_value_share_pct"],
         "then_pct": then_aged["aged_value_share_pct"],
         "points": aged_value_points, "direction": _direction(aged_value_points),
         "note": "How much of the money on the shelf is nine months old or more."},
        {"key": "aged_qty_share", "label": "Aged share of units",
         "now_pct": now_aged["aged_qty_share_pct"],
         "then_pct": then_aged["aged_qty_share_pct"],
         "points": aged_qty_points, "direction": _direction(aged_qty_points),
         "note": "The same question counted in units instead of money."},
        {"key": "high_risk_share", "label": "Over a year old, share of value",
         "now_pct": now_aged["high_risk_share_pct"],
         "then_pct": then_aged["high_risk_share_pct"],
         "points": high_points, "direction": _direction(high_points),
         "note": "The part of the aged stock that is hardest to sell."},
    ]

    skus_now = _f(current.get("skus"))
    skus_then = _f(history.get("skus"))

    return {
        "available": True,
        "lane": label,
        "as_at": as_at[:10],
        "prior_as_at": prior_as_at[:10],
        "days": _days_between(prior_as_at, as_at),
        "window_label": f"since {prior_as_at[:10]}",
        "value_comparable": basis["value_comparable"],
        "basis": basis,
        "now": {**now_aged, "total_value": now_mix["total_value"],
                "total_qty": now_mix["total_qty"], "skus": skus_now},
        "then": {**then_aged, "total_value": then_mix["total_value"],
                 "total_qty": then_mix["total_qty"], "skus": skus_then},
        "sku_change": skus_now - skus_then,
        "headlines": headlines,
        "bands": band_rows,
        "locations": _member_rows(location_pairs),
        "divisions": _member_rows(_pair_members(current.get("divisions") or [],
                                                history.get("divisions") or [])),
        "agreement": _agreement(aged_value_points, aged_qty_points),
        "verdict": _verdict(aged_value_points, aged_qty_points),
    }


def _unavailable(label: str, as_at: str, prior_as_at: str, reason: str) -> dict:
    return {"available": False, "lane": label, "as_at": as_at[:10],
            "prior_as_at": prior_as_at[:10] if prior_as_at else "",
            "value_comparable": False, "reason": reason}


def _days_between(then: str, now: str) -> int | None:
    import datetime as _dt

    try:
        start = _dt.date.fromisoformat(str(then)[:10])
        end = _dt.date.fromisoformat(str(now)[:10])
    except (TypeError, ValueError):
        return None
    return (end - start).days


def _pair_members(now_rows: Sequence[dict], then_rows: Sequence[dict]) -> list[dict]:
    """Match members by name across the two dates.

    Matched on each table's OWN member column rather than through the shared
    lookup: on the live model 1.5% of the history table's value does not match
    that lookup at all, so joining through it would quietly drop value from one
    side of the comparison only - the worst kind of error, because both sides
    still add up to something.
    """
    then_by_name = {str(r.get("name") or "").strip().upper(): r
                    for r in then_rows or []}
    out: list[dict] = []
    seen: set[str] = set()
    for row in now_rows or []:
        name = str(row.get("name") or "").strip()
        key = name.upper()
        seen.add(key)
        prior = then_by_name.get(key) or {}
        out.append({
            "name": name or "Unassigned",
            "value_now": _f(row.get("value")), "value_then": _f(prior.get("value")),
            "qty_now": _f(row.get("qty")), "qty_then": _f(prior.get("qty")),
            "aged_now": _f(row.get("aged")), "aged_then": _f(prior.get("aged")),
            "present_then": key in then_by_name,
            "gone": False,
        })
    for key, row in then_by_name.items():
        if key in seen:
            continue
        out.append({
            "name": str(row.get("name") or "Unassigned"),
            "value_now": 0.0, "value_then": _f(row.get("value")),
            "qty_now": 0.0, "qty_then": _f(row.get("qty")),
            "aged_now": 0.0, "aged_then": _f(row.get("aged")),
            "present_then": True, "gone": True,
        })
    return out


def _member_rows(pairs: Sequence[dict]) -> list[dict]:
    """Per-member movement, ranked by how much the aged share moved."""
    rows = []
    for pair in pairs or []:
        now_share = _share_pct(pair.get("aged_now"), pair.get("value_now"))
        then_share = _share_pct(pair.get("aged_then"), pair.get("value_then"))
        points = _points(now_share, then_share)
        rows.append({
            "name": pair.get("name"),
            "aged_share_now_pct": now_share,
            "aged_share_then_pct": then_share,
            "points": points,
            "direction": _direction(points),
            "qty_now": pair.get("qty_now"),
            "qty_then": pair.get("qty_then"),
            "qty_change": _f(pair.get("qty_now")) - _f(pair.get("qty_then")),
            "new": not pair.get("present_then"),
            "gone": bool(pair.get("gone")),
            "comparable": bool(pair.get("present_then")) and not pair.get("gone"),
        })
    rows.sort(key=lambda r: (r["points"] is None, -(r["points"] or 0.0)))
    return rows


def _agreement(value_points: float | None, qty_points: float | None) -> dict:
    """Do the money reading and the unit reading tell the same story?

    They are independent of one another - a share of value and a share of units
    can move in opposite directions - so when they agree the finding is much
    harder to argue with, and saying so is worth a line on the page.
    """
    if value_points is None or qty_points is None:
        return {"agree": None, "text": ""}
    same = _direction(value_points) == _direction(qty_points)
    if same and _direction(value_points) != "flat":
        word = "worse" if value_points > 0 else "better"
        return {"agree": True,
                "text": f"Counted in money and counted in units, the picture "
                        f"moved the same way - {word}. Two separate readings "
                        f"agreeing makes this a solid finding."}
    if same:
        return {"agree": True,
                "text": "Counted in money and counted in units, the picture is "
                        "broadly unchanged."}
    return {"agree": False,
            "text": "The money reading and the unit reading disagree, which "
                    "usually means the mix of what is ageing has changed rather "
                    "than the amount. Read both before acting."}


def _verdict(value_points: float | None, qty_points: float | None) -> str:
    moves = [p for p in (value_points, qty_points) if p is not None]
    if not moves:
        return "No comparable reading"
    if all(p > MATERIAL_POINTS for p in moves):
        return "Ageing has got worse"
    if all(p < -MATERIAL_POINTS for p in moves):
        return "Ageing has improved"
    return "Broadly unchanged"


def position_from_scan(scan: dict) -> dict:
    """Turn a raw Ageing scan into the position shape `build` compares.

    This is what lets the pipeline's own kept scans go through exactly the same
    comparison as the model's history table. One engine, two lanes: a bug in the
    band arithmetic cannot be fixed in one comparison and left in the other.
    """
    header = (scan.get("snapshot") or [{}])[0]

    def cell(row: dict, name: str) -> Any:
        wanted = str(name).lower()
        for key, value in (row or {}).items():
            if str(key).strip("[]").split("[")[-1].strip("]").lower() == wanted:
                return value
        return None

    def members(rows: Sequence[dict], label: str) -> list[dict]:
        return [{"name": cell(r, label), "value": _f(cell(r, "value")),
                 "qty": _f(cell(r, "qty")), "aged": _f(cell(r, "aged")),
                 "aged_qty": _f(cell(r, "aged_qty"))} for r in rows or []]

    return {
        "as_at": str(cell(header, "as_at") or "").split("T")[0],
        "skus": _f(cell(header, "skus")),
        "bands": [{"name": cell(r, "NEW AGE"), "value": _f(cell(r, "value")),
                   "qty": _f(cell(r, "qty")), "skus": _f(cell(r, "skus"))}
                  for r in scan.get("bands") or []],
        "locations": members(scan.get("locations") or [], "LOC_CODE"),
        "divisions": members(scan.get("divisions") or [], "DEPARTMENT"),
    }
