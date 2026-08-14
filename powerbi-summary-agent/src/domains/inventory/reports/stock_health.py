"""Inventory Management - a prioritised work queue, not a verdict.

The brief calls for an `exception_list` layout, and the rulebook agrees: BR-31
makes `RECOMMENDED_ACTION` "the operational output of the model", with one of 15
states on every location-SKU row. So the report is ordered by *what the buying
team should do next*, not by what is largest.

Two states are named as the most urgent because they combine two problems at
once (BR-31): **NON MOVING - ORDER PLACED** (already stagnant, and more stock is
coming) and **STOCK OUT - PLACE ORDER** (zero stock, no recovery in flight).
They lead the queue regardless of value.

The scoping trap this report must not fall into
-----------------------------------------------
BR-16 restricts Opportunity Loss to **critical SKUs at stores** - SEG_A/B, LOCAL
procurement, `loc_type = SH`. Measured live on 2026-08-13, the unscoped figure is
**SAR 292,771** against **SAR 45,944** correctly scoped: reporting the wrong one
overstates it by **6.4x**. The scan computes only the scoped figure for
publication and keeps the unscoped one solely so the report can say why they
differ.
"""

from __future__ import annotations

from typing import Any, Sequence

from ....kernel.report import ReportSpec

SPEC = ReportSpec(
    report_id="inventory_stock_health",
    report_name="Inventory Management",
    domain="inventory",
    chain_id="inventory",
    cadence="daily",
    spine="snapshot_vs_policy",
    kpis=("stock_value", "excess", "non_moving", "stockout", "opportunity_loss",
          "pending_orders"),
    axes=("recommended_action", "location", "division", "section", "sku_segment"),
    layout="exception_list",
    rules=("stock_health_prose",),
)

#: BR-31's states, most urgent first. The two double-warning states lead.
#: Anything not listed sorts after these, before the healthy states.
ACTION_PRIORITY: tuple[str, ...] = (
    "NON MOVING - ORDER PLACED",
    "STOCK OUT - PLACE ORDER",
    "STOCK OUT - AVAILABLE IN WAREHOUSE",
    "STOCK OUT - ORDER PLACED",
    "ON THE VERGE OF STOCK OUT - PLACE ORDER",
    "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE",
    "ON THE VERGE OF STOCK OUT - ORDER PLACED",
    "OVERSTOCK",
    "NON MOVING",
    "IN STOCK BUT NO SALES",
    "IN STOCK BUT NO TRANSFERS",
    "STOCK AVAILABLE - REORDER LEVEL UNKNOW",
    "NEW LISTED SKU",
    "NOT ACTIVE",
    "STOCK AVAILABLE",
    "NA",
)

#: What the buying team should actually do, from BR-31. Printed beside each row,
#: because "out of stock" alone is not enough information to act on (BR-15).
ACTION_GUIDANCE: dict[str, str] = {
    "NON MOVING - ORDER PLACED": "Urgent: review and cancel or defer the open order.",
    "STOCK OUT - PLACE ORDER": "Place an emergency purchase order.",
    "STOCK OUT - AVAILABLE IN WAREHOUSE": "Transfer from the warehouse immediately.",
    "STOCK OUT - ORDER PLACED": "Check the order date; consider an emergency transfer.",
    "ON THE VERGE OF STOCK OUT - PLACE ORDER": "Place a purchase order without delay.",
    "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE": "Transfer from the warehouse now.",
    "ON THE VERGE OF STOCK OUT - ORDER PLACED": "Check the order will arrive in time.",
    "OVERSTOCK": "Review for markdown, promotion or transfer between locations.",
    "NON MOVING": "Investigate demand; consider promotion, transfer or clearance.",
    "IN STOCK BUT NO SALES": "Monitor; follow up if there are no sales in 30 days.",
    "IN STOCK BUT NO TRANSFERS": "Check store demand; consider a push transfer.",
    "STOCK AVAILABLE - REORDER LEVEL UNKNOW": "Set a reorder level so this can be assessed.",
    "NEW LISTED SKU": "Monitor; do not apply excess or non-moving rules yet.",
    "NOT ACTIVE": "No stock action; review range planning.",
    "STOCK AVAILABLE": "No action needed.",
    "NA": "Investigate the source record.",
}

#: The two states BR-31 says to report first.
DOUBLE_WARNING = ("NON MOVING - ORDER PLACED", "STOCK OUT - PLACE ORDER")

#: States that represent work. Everything else is healthy or informational.
EXCEPTION_STATES = frozenset(ACTION_PRIORITY[:11])

HEALTHY_STATES = frozenset({"STOCK AVAILABLE", "NOT ACTIVE", "NEW LISTED SKU", "NA"})


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _cell(row: dict, *names: str) -> Any:
    for name in names:
        for key, value in (row or {}).items():
            cleaned = str(key).strip("[]").split("[")[-1].strip("]").lower()
            if cleaned == name.lower():
                return value
    return None


def action_rank(action: Any) -> int:
    name = str(action or "").strip().upper()
    for index, known in enumerate(ACTION_PRIORITY):
        if known.upper() == name:
            return index
    return len(ACTION_PRIORITY)


def is_exception(action: Any) -> bool:
    return str(action or "").strip().upper() in {a.upper() for a in EXCEPTION_STATES}


def build(scan: dict) -> dict:
    """The whole report model, from one scan. Pure."""
    header = (scan.get("snapshot") or [{}])[0]
    as_at = str(_cell(header, "as_at") or "").split("T")[0]
    stock = _num(_cell(header, "stock_value")) or 0.0
    excess = _num(_cell(header, "excess_value")) or 0.0
    pending = _num(_cell(header, "pending_value")) or 0.0

    opp = (scan.get("opportunity_loss") or [{}])[0]
    opp_scoped = _num(_cell(opp, "opp_loss_stores_critical")) or 0.0
    opp_all = _num(_cell(opp, "opp_loss_all")) or 0.0

    unwanted = (scan.get("unwanted") or [{}])[0]

    queue = _queue(scan.get("actions") or [])
    exceptions = [row for row in queue if row["is_exception"]]
    exception_rows = sum(row["loc_skus"] for row in exceptions)
    exception_value = sum(row["stock_value"] for row in exceptions)
    total_rows = sum(row["loc_skus"] for row in queue)

    checks = {
        "queue_covers_every_row": abs(total_rows - (_num(_cell(header, "loc_skus")) or 0)) < 1,
        "excess_within_stock": excess <= stock * 1.0001,
        "opportunity_loss_scoped": opp_scoped <= opp_all * 1.0001,
    }

    return {
        "report_id": SPEC.report_id,
        "report_name": SPEC.report_name,
        "period_label": f"as at {as_at}" if as_at else "as at the latest snapshot",
        "as_at": as_at,
        "currency": "SAR",
        "header": {
            "stock_value": stock,
            "excess_value": excess,
            "excess_share_pct": (excess / stock * 100.0) if stock else None,
            "pending_value": pending,
            "opportunity_loss_day": opp_scoped,
            "opportunity_loss_unscoped": opp_all,
            "critical_stockout_skus": _num(_cell(opp, "critical_stockout_skus")),
            "unwanted_skus": _num(_cell(unwanted, "unwanted_skus")),
            "unwanted_pending_value": _num(_cell(unwanted, "unwanted_pending_value")),
            "pending_skus": _num(_cell(unwanted, "pending_skus")),
            "loc_skus": _num(_cell(header, "loc_skus")),
            "skus": _num(_cell(header, "skus")),
            "locations": _num(_cell(header, "locations")),
            "exception_rows": exception_rows,
            "exception_value": exception_value,
        },
        "queue": queue,
        "double_warnings": [r for r in queue
                            if r["action"].upper() in {d.upper() for d in DOUBLE_WARNING}],
        "locations": _rank(scan.get("locations") or [], "LOC_CODE"),
        "divisions": _rank(scan.get("divisions") or [], "DEPARTMENT"),
        "sections": _rank(scan.get("sections") or [], "SECTION", top=15),
        "segments": _segments(scan.get("segments") or []),
        "non_moving_bands": _bands(scan.get("non_moving_bands") or []),
        "damage": _damage(scan.get("damage") or []),
        "checks": checks,
        "caveats": _caveats(opp_scoped, opp_all),
        "narrative": _narrative(queue, stock, excess, opp_scoped, unwanted, as_at),
    }


def _queue(rows: Sequence[dict]) -> list[dict]:
    out = []
    for row in rows:
        action = str(_cell(row, "RECOMMENDED_ACTION") or "").strip()
        if not action:
            continue
        out.append({
            "action": action,
            "loc_skus": int(_num(_cell(row, "loc_skus")) or 0),
            "stock_value": _num(_cell(row, "stock_value")) or 0.0,
            "excess_value": _num(_cell(row, "excess_value")) or 0.0,
            "guidance": ACTION_GUIDANCE.get(action.upper(), ""),
            "is_exception": is_exception(action),
            "double_warning": action.upper() in {d.upper() for d in DOUBLE_WARNING},
            "rank": action_rank(action),
        })
    out.sort(key=lambda r: (r["rank"], -r["loc_skus"]))
    return out


def _rank(rows: Sequence[dict], label: str, top: int = 50) -> list[dict]:
    ranked = []
    for row in rows:
        name = _cell(row, label)
        if name is None:
            continue
        ranked.append({
            "name": str(name),
            "loc_type": _cell(row, "loc_type"),
            "stock_value": _num(_cell(row, "stock_value")) or 0.0,
            "excess_value": _num(_cell(row, "excess_value")) or 0.0,
            "loc_skus": int(_num(_cell(row, "loc_skus")) or 0),
        })
    ranked.sort(key=lambda item: item["excess_value"], reverse=True)
    return ranked[:top]


def _segments(rows: Sequence[dict]) -> list[dict]:
    out = [{
        "name": str(_cell(r, "SKUSEGMENT") or ""),
        "loc_skus": int(_num(_cell(r, "loc_skus")) or 0),
        "stock_value": _num(_cell(r, "stock_value")) or 0.0,
        "excess_value": _num(_cell(r, "excess_value")) or 0.0,
    } for r in rows]
    out.sort(key=lambda r: r["name"])
    return out


def _bands(rows: Sequence[dict]) -> list[dict]:
    out = [{
        "name": str(_cell(r, "NM DAYS TAG") or ""),
        "loc_skus": int(_num(_cell(r, "loc_skus")) or 0),
        "stock_value": _num(_cell(r, "stock_value")) or 0.0,
    } for r in rows if _cell(r, "NM DAYS TAG")]
    # Bands read "30-60", "61-90", ... ">180": order by their first number.
    def start(name: str) -> int:
        digits = "".join(ch if ch.isdigit() else " " for ch in name).split()
        return int(digits[0]) if digits else 9999
    out.sort(key=lambda r: start(r["name"]))
    return out


def _damage(rows: Sequence[dict]) -> list[dict]:
    out = [{
        "month": str(_cell(r, "month_date") or "").split("T")[0],
        # BR-29: negative in the source; reported as an absolute cost.
        "value": abs(_num(_cell(r, "damage_value")) or 0.0),
    } for r in rows]
    out.sort(key=lambda r: r["month"])
    return out


def _caveats(opp_scoped: float, opp_all: float) -> list[str]:
    notes = [
        "Stock figures are a position as at the snapshot date, not a total over "
        "a period.",
        "Excess is the value held above the agreed cover for that section and "
        "location - not the whole value of an overstocked product.",
    ]
    if opp_all > opp_scoped:
        notes.append(
            f"Opportunity Loss is shown for critical products at stores only "
            f"(top-selling, locally bought). Across every product and location "
            f"the raw figure is {opp_all:,.0f} a day, but that number includes "
            f"warehouses and imported products, where it is not meaningful.")
    notes.append(
        "Opportunity Loss is an estimate based on the recent rate of sale and "
        "retail price. It is not confirmed lost revenue.")
    return notes


def _sar(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "not available"
    if abs(number) >= 1_000_000:
        return f"SAR {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"SAR {number / 1_000:.0f}K"
    return f"SAR {number:,.0f}"


def _narrative(queue, stock, excess, opp_scoped, unwanted, as_at) -> list[str]:
    """Grounded sentences, led by the two double-warning states (BR-31)."""
    lines: list[str] = []
    by_action = {r["action"].upper(): r for r in queue}

    nm_order = by_action.get("NON MOVING - ORDER PLACED")
    if nm_order and nm_order["loc_skus"]:
        lines.append(
            f"{nm_order['loc_skus']:,} product-location lines are not selling and "
            f"have a purchase order still open, holding {_sar(nm_order['stock_value'])}. "
            f"More stock is arriving for products that are already not moving. "
            f"Review and cancel or defer those orders first.")

    so_place = by_action.get("STOCK OUT - PLACE ORDER")
    if so_place and so_place["loc_skus"]:
        lines.append(
            f"{so_place['loc_skus']:,} lines are out of stock with no order placed "
            f"and no warehouse stock to draw on. These need a purchase order "
            f"raised now.")

    so_wh = by_action.get("STOCK OUT - AVAILABLE IN WAREHOUSE")
    if so_wh and so_wh["loc_skus"]:
        lines.append(
            f"A further {so_wh['loc_skus']:,} lines are out of stock at a store "
            f"while the warehouse holds stock. These can be fixed by transfer "
            f"today, without buying anything.")

    if excess and stock:
        lines.append(
            f"{_sar(excess)} is held above the agreed cover, "
            f"{excess / stock * 100.0:.1f}% of the {_sar(stock)} held across all "
            f"locations. That is the value tied up beyond what the buying team "
            f"agreed to carry, not the full value of overstocked products.")

    unwanted_skus = _num(_cell(unwanted, "unwanted_skus")) or 0
    if unwanted_skus:
        lines.append(
            f"{int(unwanted_skus):,} products already flagged as overstocked have "
            f"more stock on order, worth "
            f"{_sar(_cell(unwanted, 'unwanted_pending_value'))} of open orders. "
            f"Each one is worth reviewing before the stock arrives.")

    if opp_scoped:
        lines.append(
            f"Stockouts on top-selling locally bought products at stores are "
            f"estimated to cost {_sar(opp_scoped)} a day in sales not made.")

    return lines
