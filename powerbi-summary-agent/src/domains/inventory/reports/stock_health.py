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

import datetime as _dt
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


def absent_states(queue: Sequence[dict]) -> list[str]:
    """Documented states the data never returned.

    A state with no rows is indistinguishable from a state the source system
    never produces, and the difference matters. Measured live on 2026-08-13,
    `NON MOVING - ORDER PLACED` - which BR-31 names as one of the *two* most
    urgent situations in the whole report, and which this module sorts first
    regardless of value - had **zero** rows, while the other fourteen states all
    had data. So one half of the documented urgency pair can never fire, and
    nothing said so: the queue simply did not list it, which reads as "no
    problem here" rather than "never reported".

    Returning it makes the silence visible. It is not an error - a genuinely
    empty state is good news - but an empty *double-warning* state is a question
    for whoever owns the source system, not a clean bill of health.
    """
    present = {str(r.get("action") or "").strip().upper() for r in queue}
    return [state for state in ACTION_PRIORITY if state.upper() not in present]


def build(scan: dict, currency: str = "SAR") -> dict:
    """The whole report model, from one scan. Pure.

    ``currency`` defaults to the value this report shipped with so every
    committed artifact reproduces byte-for-byte; the runner passes
    ``inventory_currency`` from the active config. The semantic model declares
    no currency of its own, so it cannot be resolved from the data.
    """
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

    missing = absent_states(queue)
    missing_urgent = [s for s in missing
                      if s.upper() in {d.upper() for d in DOUBLE_WARNING}]

    # `checks` holds guarantees that MUST be true - a false one means the report
    # is wrong and must not ship. An absent state is not that: it is a fact
    # about today's data, and on a quiet day it is good news. Putting it here
    # would fail the audit every day the source system happens not to produce a
    # state, training the reader to ignore a red build. It goes in
    # `observations`, which is reported and never fails.
    checks = {
        "queue_covers_every_row": abs(total_rows - (_num(_cell(header, "loc_skus")) or 0)) < 1,
        "excess_within_stock": excess <= stock * 1.0001,
        "opportunity_loss_scoped": opp_scoped <= opp_all * 1.0001,
    }

    observations = {
        "documented_states_absent": missing,
        "urgent_states_absent": missing_urgent,
    }

    return {
        "report_id": SPEC.report_id,
        "report_name": SPEC.report_name,
        "period_label": f"as at {as_at}" if as_at else "as at the latest snapshot",
        "as_at": as_at,
        "currency": currency,
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
        "states_absent": missing,
        "states_absent_urgent": missing_urgent,
        "locations": _rank(scan.get("locations") or [], "LOC_CODE"),
        "divisions": _rank(scan.get("divisions") or [], "DEPARTMENT"),
        "sections": _rank(scan.get("sections") or [], "SECTION", top=15),
        "segments": _segments(scan.get("segments") or []),
        "non_moving_bands": _bands(scan.get("non_moving_bands") or []),
        "damage": _damage(scan.get("damage") or []),
        "checks": checks,
        "observations": observations,
        "caveats": _caveats(opp_scoped, opp_all, missing_urgent),
        "narrative": _narrative(queue, stock, excess, opp_scoped, unwanted, as_at,
                                currency=currency),
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


def _caveats(opp_scoped: float, opp_all: float,
             missing_urgent: Sequence[str] = ()) -> list[str]:
    notes = [
        "Stock figures are a position as at the snapshot date, not a total over "
        "a period.",
        "Excess is the value held above the agreed cover for that section and "
        "location - not the whole value of an overstocked product.",
    ]

    # Say it plainly rather than letting an empty row read as good news.
    for state in missing_urgent:
        notes.append(
            f"No product lines came back in the \"{state}\" situation. The rules "
            f"list this as one of the two most urgent situations in the report, "
            f"so either nothing is currently in it, or the source system is not "
            f"producing it. Worth confirming - this report can only flag what "
            f"the data reports.")
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


def _money(value: Any, currency: str = "SAR") -> str:
    number = _num(value)
    if number is None:
        return "not available"
    if abs(number) >= 1_000_000:
        return f"{currency} {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{currency} {number / 1_000:.0f}K"
    return f"{currency} {number:,.0f}"


#: Retained under its original name: the currency was hard-coded when this was
#: written and callers outside this module still reach for it.
def _sar(value: Any) -> str:
    return _money(value, "SAR")


def _narrative(queue, stock, excess, opp_scoped, unwanted, as_at,
               currency: str = "SAR") -> list[str]:
    """Grounded sentences, led by the two double-warning states (BR-31)."""
    lines: list[str] = []
    by_action = {r["action"].upper(): r for r in queue}

    def _sar(value: Any) -> str:  # noqa: A001 - shadows deliberately, see _money
        return _money(value, currency)

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


# ---------------------------------------------------------------------------
# The live scan
# ---------------------------------------------------------------------------
#
# `build()` above is pure and takes a scan dict. Until now that dict was
# produced by hand, which is why the committed scans carry no provenance. This
# is the missing half: one bounded read of the semantic model returning exactly
# the dict `build()` already consumes, so every existing replay and auditor
# keeps working against it unchanged.

#: The fact table. Everything rolls up from here, and deliberately so: the
#: health-score tables (`LOC_CATEGORY_HEALTH`, `P90 CATEGORY LOCATION`) carry no
#: relationships, so slicing them by Division returns the company total for
#: every Division rather than that Division's own figure.
FACT = "REP_SSR_STOCK_STATUS_REPORTV2"
DAMAGE_TABLE = "DAMAGE DATA"

#: BR-16's three hard limits on Opportunity Loss, held as data rather than prose
#: so the query and the caveat cannot drift apart.
CRITICAL_SEGMENTS: tuple[str, ...] = ("SEG_A", "SEG_B")
LOCAL_PROCUREMENT = "LOCAL"
STORE_LOC_TYPE = "SH"

#: Columns that must never be selected. `LOC_CODE` is a display alias (ST1-ST5,
#: WH1/WH2), but `locsku` is built on the REAL location code, so any query
#: returning it leaks the client's own branch codes into published output.
#: Nothing here needs it - the scan aggregates, and its aggregation keys are the
#: aliases.
FORBIDDEN_COLUMNS: frozenset = frozenset({"locsku"})


class ScanBudgetExceeded(RuntimeError):
    """The scan asked for more queries than the config allows."""


def reject_forbidden(label: str, dax: str) -> None:
    """Raise if a query names a column that must never leave the model.

    Module level rather than buried in `scan`'s closure so it can be driven
    directly by a test: a guard that can only be exercised through the queries
    that already satisfy it is a guard nobody has actually checked.
    """
    lowered = dax.lower()
    for banned in FORBIDDEN_COLUMNS:
        if "[" + banned + "]" in lowered:
            raise ValueError(
                label + ": query selects [" + banned + "], which embeds the "
                "real location code and must never reach published output.")


def _critical_store_scope() -> str:
    """BR-16's scope, as TREATAS filter arguments.

    TREATAS rather than a bare equality throughout: a bare
    `KEEPFILTERS('Table'[Col] = "value")` fails against these models with
    "single value for column cannot be determined", and a multi-value scope
    written as a comma-joined string is a fake member rather than a filter.
    """
    segments = ", ".join('"%s"' % seg for seg in CRITICAL_SEGMENTS)
    return (
        "TREATAS({%s}, '%s'[SKUSEGMENT]), " % (segments, FACT)
        + 'TREATAS({"%s"}, \'%s\'[SKU_TYPE]), ' % (LOCAL_PROCUREMENT, FACT)
        + 'TREATAS({"%s"}, \'%s\'[loc_type])' % (STORE_LOC_TYPE, FACT)
    )


def scan(execute, cfg: dict | None = None, *, log=None) -> dict:
    """Every row the report needs, in the shape :func:`build` consumes.

    Eleven queries, none unfiltered by construction: each is either a single
    ``ROW`` of aggregates or a ``SUMMARIZECOLUMNS`` over a bounded, low
    cardinality axis (15 Recommended Action states, 7 Locations, 10 Divisions,
    4 SKU segments, 7 non-moving bands). ``execute`` is the caller's bound
    executor, which already holds the pre-fetched token: this function never
    acquires one, because ``get_powerbi_token`` does an unlocked
    read-modify-write of the shared cache.

    The Opportunity Loss trap
    -------------------------
    Three figures are available and only one may be published. Measured live on
    2026-08-21:

    ==========================================  ========
    ``OPP_LOSS_DUE_TO_STOCKOUT``, unscoped       313,038
    the model's own ``OPPORTUNITY LOSS`` column    59,051
    BR-16's scope applied to the first             49,076
    ==========================================  ========

    BR-16 names ``OPP_LOSS_DUE_TO_STOCKOUT`` as the column and states three hard
    limits - critical segments, local procurement, stores only. Applying them
    gives the smallest figure, and that is the one published. The model's own
    pre-scoped column is 20% higher, so it does not apply all three; it is
    returned as a third diagnostic purely so a caveat can name the gap, rather
    than leaving a reader to discover two different numbers for one measure.
    """
    cfg = cfg or {}
    budget = int(cfg.get("inventory_max_queries", 25) or 25)
    used = 0

    def run(label: str, dax: str) -> list:
        nonlocal used
        reject_forbidden(label, dax)
        used += 1
        if used > budget:
            raise ScanBudgetExceeded(
                "the scan needs more than inventory_max_queries=%d queries" % budget)
        rows = execute(dax)
        if log:
            log("  %s: %d row(s)" % (label, len(rows)))
        return rows

    scoped = _critical_store_scope()
    out: dict = {}

    out["snapshot"] = run("snapshot", """EVALUATE ROW(
      "as_at", MAX('{F}'[UPDATED_ON]),
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]),
      "excess_value", SUM('{F}'[EXCESS_STOCK_VALUE]),
      "pending_value", SUM('{F}'[PENDING_ORDERS_VALUE]),
      "loc_skus", COUNTROWS('{F}'),
      "skus", DISTINCTCOUNT('{F}'[sku_code]),
      "locations", DISTINCTCOUNT('{F}'[LOC_CODE]))""".format(F=FACT))

    out["actions"] = run("recommended actions", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[RECOMMENDED_ACTION],
      "loc_skus", COUNTROWS('{F}'),
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]),
      "excess_value", SUM('{F}'[EXCESS_STOCK_VALUE]))""".format(F=FACT))

    out["status"] = run("stock status", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[SKU_STOCK_STATUS],
      "loc_skus", COUNTROWS('{F}'),
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]))""".format(F=FACT))

    out["locations"] = run("locations", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[LOC_CODE], '{F}'[loc_type],
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]),
      "excess_value", SUM('{F}'[EXCESS_STOCK_VALUE]),
      "loc_skus", COUNTROWS('{F}'))""".format(F=FACT))

    out["divisions"] = run("divisions", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[DEPARTMENT],
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]),
      "excess_value", SUM('{F}'[EXCESS_STOCK_VALUE]),
      "loc_skus", COUNTROWS('{F}'))""".format(F=FACT))

    out["sections"] = run("sections", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[DEPARTMENT], '{F}'[SECTION],
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]),
      "excess_value", SUM('{F}'[EXCESS_STOCK_VALUE]))""".format(F=FACT))

    out["segments"] = run("SKU segments", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[SKUSEGMENT],
      "loc_skus", COUNTROWS('{F}'),
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]),
      "excess_value", SUM('{F}'[EXCESS_STOCK_VALUE]))""".format(F=FACT))

    out["non_moving_bands"] = run("non-moving bands", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[NM DAYS TAG],
      "loc_skus", COUNTROWS('{F}'),
      "stock_value", SUM('{F}'[SKU_STOCK_VALUE]))""".format(F=FACT))

    # BR-29: Damage is a monthly flow, not part of the stock position, and it is
    # negative at source. `build` takes its absolute value; the scan reports it
    # exactly as the model holds it.
    out["damage"] = run("damage by month", """EVALUATE TOPN(12,
      SUMMARIZECOLUMNS('{D}'[month_date],
        "damage_value", SUM('{D}'[damage_value])),
      '{D}'[month_date], DESC)""".format(D=DAMAGE_TABLE))

    out["opportunity_loss"] = run("opportunity loss", """EVALUATE ROW(
      "opp_loss_all", SUM('{F}'[OPP_LOSS_DUE_TO_STOCKOUT]),
      "opp_loss_stores_critical", CALCULATE(
          SUM('{F}'[OPP_LOSS_DUE_TO_STOCKOUT]), {S}),
      "opp_loss_model_column", SUM('{F}'[OPPORTUNITY LOSS]),
      "critical_stockout_skus", CALCULATE(DISTINCTCOUNT('{F}'[sku_code]), {S},
          FILTER(ALL('{F}'[CURRENT_STOCK]), '{F}'[CURRENT_STOCK] <= 0)))
    """.format(F=FACT, S=scoped))

    # BR-28: an Unwanted SKU is in Pending Orders AND already carrying Excess
    # Stock. BR-26 requires unique SKUs where a classification spans Locations,
    # so these are DISTINCTCOUNT of sku_code, never a row count.
    out["unwanted"] = run("unwanted SKUs", """EVALUATE ROW(
      "unwanted_skus", CALCULATE(DISTINCTCOUNT('{F}'[sku_code]),
          FILTER(ALL('{F}'[PENDING_ORDERS], '{F}'[EXCESS_STOCK]),
                 '{F}'[PENDING_ORDERS] > 0 && '{F}'[EXCESS_STOCK] > 0)),
      "unwanted_pending_value", CALCULATE(SUM('{F}'[PENDING_ORDERS_VALUE]),
          FILTER(ALL('{F}'[PENDING_ORDERS], '{F}'[EXCESS_STOCK]),
                 '{F}'[PENDING_ORDERS] > 0 && '{F}'[EXCESS_STOCK] > 0)),
      "pending_skus", CALCULATE(DISTINCTCOUNT('{F}'[sku_code]),
          FILTER(ALL('{F}'[PENDING_ORDERS]), '{F}'[PENDING_ORDERS] > 0)))
    """.format(F=FACT))

    # --- The Inventory Health Score -------------------------------------
    #
    # `_HEALTH SCORE MEASURES` publishes the score the business already uses, so
    # the page reports the model's own number rather than inventing a composite.
    # `Total Points Lost` is defined in the model as the sum of the six
    # `Category X Risk` measures and the score as `100 - that sum`, so those six
    # ARE the authoritative points; the impact dimensions are read alongside so
    # the page can show how each was arrived at, and `health.py` asserts the
    # rebuild reconciles rather than trusting it.
    #
    # Every roll-up is keyed on the FACT table, never on `LOC_CATEGORY_HEALTH`
    # or `P90 CATEGORY LOCATION`: those carry no relationships, so slicing them
    # returns the company total for every member. `FCT SKU HEALTH` is
    # bidirectionally related to the fact table on `locsku`, so a Division or
    # Location key on the fact table propagates correctly.
    out["health_overall"] = run("health score", """EVALUATE ROW(
      "score", [Inventory Health Score],
      "lost", [Total Points Lost],
      "stock", [Total Stock Value],
      "scored_loc_skus", [Total SKU Count],
      "eligible_loc_skus", [Eligible SKU Count],
      "sales_base", [Total Sales Value Base],
      "avg_scored_line", [Avg SKU Health (Simple Avg)],
      "dead_points", [Category Dead Risk],
      "excess_points", [Category Excess Risk],
      "ageing_points", [Category Ageing Risk],
      "damage_points", [Category Damage Risk],
      "verge_points", [Category Verge Risk],
      "oos_points", [Category OOS Risk],
      "dead_value_impact", [Dead Value Impact],
      "dead_sku_impact", [Dead SKU Impact],
      "dead_duration_impact", [Dead Duration Impact],
      "excess_value_impact", [Excess Value Impact],
      "excess_sku_impact", [Excess SKU Impact],
      "excess_duration_impact", [Excess Duration Impact],
      "ageing_value_impact", [Ageing Value Impact],
      "ageing_sku_impact", [Ageing SKU Impact],
      "ageing_severity_impact", [Ageing Severity Impact],
      "damage_value_impact", [Damage Value Impact],
      "damage_sku_impact", [Damage SKU Impact],
      "verge_sales_impact", [Verge Sales Impact],
      "verge_sku_impact", [Verge SKU Impact],
      "verge_severity_impact", [Verge Weighted Segment Severity],
      "oos_sales_impact", [OOS Sales Impact],
      "oos_sku_impact", [OOS SKU Impact],
      "oos_severity_impact", [OOS Weighted Segment Severity],
      "dead_loc_skus", [Dead SKU Count], "dead_value", [Dead Stock Value (Sum)],
      "excess_loc_skus", [Excess SKU Count], "excess_value", [Excess Value (Sum)],
      "ageing_loc_skus", [Ageing SKU Count], "ageing_value", [Ageing Value (Sum)],
      "damage_loc_skus", [Damage SKU Count], "damage_value", [Damage Value (Sum)],
      "verge_loc_skus", [Verge SKU Count], "verge_value", [Verge Sales At Risk (Sum)],
      "oos_loc_skus", [OOS SKU Count], "oos_value", [OOS Sales At Risk (Sum)])""")

    out["health_by_location"] = run("health by location", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[LOC_CODE], '{F}'[loc_type],
      "score", [Inventory Health Score],
      "lost", [Total Points Lost],
      "scored_loc_skus", [Total SKU Count],
      "stock", [Total Stock Value])""".format(F=FACT))

    out["health_by_division"] = run("health by division", """EVALUATE SUMMARIZECOLUMNS(
      '{F}'[DEPARTMENT],
      "score", [Inventory Health Score],
      "lost", [Total Points Lost],
      "scored_loc_skus", [Total SKU Count],
      "stock", [Total Stock Value])""".format(F=FACT))

    out["health_status"] = run("health status bands", """EVALUATE SUMMARIZECOLUMNS(
      'FCT SKU HEALTH'[Health Status],
      "loc_skus", COUNTROWS('FCT SKU HEALTH'),
      "stock", [Total Stock Value],
      "avg_scored_line", [Avg SKU Health (Simple Avg)])""")

    # The one genuinely historical series in the model. Stock Value only - there
    # is no history of the score itself, which is why the score's own trend is
    # drawn shape-only and says so.
    out["trend"] = run("stock value trend", """EVALUATE SUMMARIZECOLUMNS(
      'SSR TREND'[dates],
      "stock", SUM('SSR TREND'[SKU_STOCK_VALUE]))
    ORDER BY 'SSR TREND'[dates]""")

    header = (out["snapshot"] or [{}])[0]
    out["provenance"] = {
        "report_id": SPEC.report_id,
        "workspace_id": cfg.get("workspace_id"),
        "dataset_id": cfg.get("dataset_id"),
        # The RUN date, not the model's as-at stamp. They are different things,
        # and the archive keys on this one - see `inventory/archive.py`.
        "scanned_on": _dt.date.today().isoformat(),
        "scanned_at": _dt.datetime.now(_dt.timezone.utc)
                         .replace(microsecond=0).isoformat(),
        "as_at": str(_cell(header, "as_at") or "").split("T")[0],
        "queries": used,
        "query_budget": budget,
    }
    if log:
        log("  scan complete: %d/%d queries, as at %s"
            % (used, budget, out["provenance"]["as_at"]))
    return out
