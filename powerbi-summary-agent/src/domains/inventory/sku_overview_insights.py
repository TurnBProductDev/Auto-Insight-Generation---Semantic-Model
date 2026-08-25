"""The eight SKU Overview insight rules, per `sku-insights-rules.md`.

Every rule scopes to the five shops only (`ST1`..`ST5`); the two warehouses
(`WH1`, `WH2`) are storage, not selling locations, and appear only as a
*fix* for a shop-floor problem (Rule 5's "available in warehouse"), never as
the subject of a rule. This is a correction from the earlier generic
hotspot detector, which scored warehouses as ordinary locations - on live
data that put WH1/WH2 at the top of the "hotspot" list for a report whose
own spec excludes them from every finding.

Rule 2 (rank promotion/demotion) has no history to compare against yet -
`SKU_RANK_IN_CATEGORY_V2_FINAL` is a live measure with no snapshot table
behind it. Per the rulebook: state this plainly as pending, never infer
movement from a different field standing in as a proxy.

DAX stays close to the rulebook's own validated patterns, adjusted only for
the real column casing confirmed against the live model (`SKU`, not `sku`;
`LOC_CODE` exists directly on the side tables, so a rule scopes on that
column itself rather than relying on cross-table relationship propagation
through a synthetic key wherever a direct column is available).
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable

Execute = Callable[[str], list[dict]]

FACT = "REP_SSR_STOCK_STATUS_REPORTV3"
PRICE_TABLE = "CURR_RP_SALES_DAYS"
TOP_DATES_TABLE = "TOP SALES DATES IN LOC"

#: The five selling locations. Warehouses are excluded from every rule's
#: population - they hold stock, they do not sell it.
SHOPS = ("ST1", "ST2", "ST3", "ST4", "ST5")


def _shops_literal() -> str:
    return "{" + ", ".join(f'"{s}"' for s in SHOPS) + "}"


def _clean_key(key: object) -> str:
    return str(key).strip("[]").split("[")[-1].strip("]").lower()


def _read(row: dict, name: str):
    wanted = str(name or "").lower()
    for key, value in (row or {}).items():
        if _clean_key(key) == wanted:
            return value
    return None


def _num(row: dict, name: str) -> float:
    value = _read(row, name)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _text(row: dict, name: str) -> str:
    value = _read(row, name)
    return str(value) if value is not None else ""


# ---------------------------------------------------------------------------
# Rule 1 - top-performing SKUs per department (last month)
# ---------------------------------------------------------------------------

def rule1_dax(*, top_n: int = 3, seg_a_only: bool = False) -> str:
    seg = f',\n    {FACT}[SKUSEGMENT] = "SEG_A"' if seg_a_only else ""
    return f"""EVALUATE
VAR Base =
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      {FACT}[DEPARTMENT],
      {FACT}[SKU_CODE],
      {FACT}[PART_DESCRIPTION],
      {FACT}[CATEGORY_NAME],
      "sales_1m", SUM({FACT}[SALES_VALUE_LAST_1MONTH]),
      "qty_1m", SUM({FACT}[SALES_QTY_LAST_1MONTH])),
    {FACT}[LOC_CODE] IN {_shops_literal()}{seg})
VAR Ranked =
  ADDCOLUMNS(Base, "rnk",
    RANKX(FILTER(Base, [DEPARTMENT] = EARLIER([DEPARTMENT])), [sales_1m],, DESC))
RETURN FILTER(Ranked, [rnk] <= {int(top_n)})"""


def rule1_run(execute: Execute, *, top_n: int = 3, seg_a_only: bool = False) -> list[dict]:
    rows = execute(rule1_dax(top_n=top_n, seg_a_only=seg_a_only))
    out = []
    for row in rows:
        out.append({
            "department": _text(row, "DEPARTMENT"), "sku_code": _text(row, "SKU_CODE"),
            "description": _text(row, "PART_DESCRIPTION"), "category": _text(row, "CATEGORY_NAME"),
            "sales_1m": _num(row, "sales_1m"), "qty_1m": _num(row, "qty_1m"),
            "rank": int(_num(row, "rnk")),
        })
    out.sort(key=lambda r: (r["department"], r["rank"]))
    return out


# ---------------------------------------------------------------------------
# Rule 2 - rank promotion/demotion. Not computable: no snapshot history.
# ---------------------------------------------------------------------------

def rule2_status() -> dict:
    return {
        "available": False,
        "reason": (
            "The model computes each SKU's current category rank "
            "(SKU_RANK_IN_CATEGORY_V2_FINAL) but keeps no snapshot of what "
            "that rank was in a prior period. Comparing requires two points "
            "in time, and only one exists today."),
        "action": (
            "Set up a weekly (or daily) snapshot export of "
            "SKU_RANK_IN_CATEGORY_V2_FINAL per SKU-location-category, "
            "appended to a history table, before this insight can run."),
    }


# ---------------------------------------------------------------------------
# Rule 3 - SKUs whose single best sales day (in a ~90-day window) was
# yesterday.
# ---------------------------------------------------------------------------

def rule3_dax(*, top_n: int = 10, seg_a_only: bool = False) -> str:
    # "Yesterday" must be resolved to a scalar first - a raw column
    # reference from a different table cannot be used as a row filter value.
    seg = f",\n    {FACT}[SKUSEGMENT] = \"SEG_A\"" if seg_a_only else ""
    join = (
        f',\n    TREATAS(\n      CALCULATETABLE(\n        VALUES({FACT}[SKU_CODE]),\n'
        f'        {FACT}[LOC_CODE] IN {_shops_literal()}{seg}),\n'
        f"      '{TOP_DATES_TABLE}'[SKU])"
        if seg_a_only else ""
    )
    return f"""EVALUATE
VAR Yesterday = MAX({FACT}[UPDATED_ON]) - 1
RETURN
TOPN({int(top_n)},
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      '{TOP_DATES_TABLE}'[SKU], '{TOP_DATES_TABLE}'[LOC_CODE],
      "sales_value", SUM('{TOP_DATES_TABLE}'[sales_value]),
      "sales_qty", SUM('{TOP_DATES_TABLE}'[sales_quantity])),
    '{TOP_DATES_TABLE}'[LOC_CODE] IN {_shops_literal()},
    '{TOP_DATES_TABLE}'[RNK] = 1,
    '{TOP_DATES_TABLE}'[doc_date] = Yesterday{join}),
  [sales_value], DESC)"""


def rule3_run(execute: Execute, *, top_n: int = 10, seg_a_only: bool = False) -> list[dict]:
    rows = execute(rule3_dax(top_n=top_n, seg_a_only=seg_a_only))
    out = []
    for row in rows:
        out.append({
            "sku": _text(row, "SKU"), "location": _text(row, "LOC_CODE"),
            "sales_value": _num(row, "sales_value"), "sales_qty": _num(row, "sales_qty"),
        })
    out.sort(key=lambda r: -r["sales_value"])
    return out


# ---------------------------------------------------------------------------
# Rule 4 - Segment A SKUs currently out of stock.
# ---------------------------------------------------------------------------

def rule4_dax(*, top_n: int = 10) -> str:
    return f"""EVALUATE
TOPN({int(top_n)},
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      {FACT}[SKU_CODE], {FACT}[PART_DESCRIPTION],
      {FACT}[CATEGORY_NAME], {FACT}[LOC_CODE],
      "sales_3m", SUM({FACT}[SALES_VALUE_LAST_3MONTHS]),
      "opp_loss", SUM({FACT}[OPP_LOSS_DUE_TO_STOCKOUT])),
    {FACT}[LOC_CODE] IN {_shops_literal()},
    {FACT}[SKUSEGMENT] = "SEG_A",
    {FACT}[SKU_STOCK_STATUS] = "STOCK OUT"),
  [sales_3m], DESC)"""


def rule4_count_dax() -> str:
    return f"""EVALUATE ROW(
  "count", CALCULATE(
    COUNTROWS({FACT}),
    {FACT}[LOC_CODE] IN {_shops_literal()},
    {FACT}[SKUSEGMENT] = "SEG_A",
    {FACT}[SKU_STOCK_STATUS] = "STOCK OUT"),
  "opp_loss_total", CALCULATE(
    SUM({FACT}[OPP_LOSS_DUE_TO_STOCKOUT]),
    {FACT}[LOC_CODE] IN {_shops_literal()},
    {FACT}[SKUSEGMENT] = "SEG_A",
    {FACT}[SKU_STOCK_STATUS] = "STOCK OUT")
)"""


def rule4_run(execute: Execute, *, top_n: int = 10) -> dict:
    totals = execute(rule4_count_dax())
    row0 = totals[0] if totals else {}
    top_rows = execute(rule4_dax(top_n=top_n))
    top = []
    for row in top_rows:
        top.append({
            "sku_code": _text(row, "SKU_CODE"), "description": _text(row, "PART_DESCRIPTION"),
            "category": _text(row, "CATEGORY_NAME"), "location": _text(row, "LOC_CODE"),
            "sales_3m": _num(row, "sales_3m"),
            # Blank OPP_LOSS_DUE_TO_STOCKOUT means "not estimated", not zero -
            # kept as None here so the caller never mistakes one for the other.
            "opp_loss": (_num(row, "opp_loss") if _read(row, "opp_loss") is not None else None),
        })
    top.sort(key=lambda r: -r["sales_3m"])
    return {"count": int(_num(row0, "count")), "opp_loss_total": _num(row0, "opp_loss_total"), "top": top}


# ---------------------------------------------------------------------------
# Rule 5 - verge-of-stockout SKUs with stock already sitting in a warehouse.
# ---------------------------------------------------------------------------

def rule5_dax(*, top_n: int = 10, seg_a_only: bool = False) -> str:
    seg = f',\n    {FACT}[SKUSEGMENT] = "SEG_A"' if seg_a_only else ""
    return f"""EVALUATE
TOPN({int(top_n)},
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      {FACT}[SKU_CODE], {FACT}[PART_DESCRIPTION],
      {FACT}[CATEGORY_NAME], {FACT}[LOC_CODE],
      "sales_3m", SUM({FACT}[SALES_VALUE_LAST_3MONTHS]),
      "current_stock", SUM({FACT}[CURRENT_STOCK])),
    {FACT}[LOC_CODE] IN {_shops_literal()},
    {FACT}[RECOMMENDED_ACTION] = "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE"{seg}),
  [sales_3m], DESC)"""


def rule5_run(execute: Execute, *, top_n: int = 10, seg_a_only: bool = False) -> list[dict]:
    rows = execute(rule5_dax(top_n=top_n, seg_a_only=seg_a_only))
    out = []
    for row in rows:
        out.append({
            "sku_code": _text(row, "SKU_CODE"), "description": _text(row, "PART_DESCRIPTION"),
            "category": _text(row, "CATEGORY_NAME"), "location": _text(row, "LOC_CODE"),
            "sales_3m": _num(row, "sales_3m"), "current_stock": _num(row, "current_stock"),
        })
    out.sort(key=lambda r: -r["sales_3m"])
    return out


# ---------------------------------------------------------------------------
# Rule 6 - non-moving SKUs with a pending purchase order.
# ---------------------------------------------------------------------------

def rule6_dax(*, cap: int = 25, seg_a_only: bool = False) -> str:
    seg = f',\n    {FACT}[SKUSEGMENT] = "SEG_A"' if seg_a_only else ""
    return f"""EVALUATE
TOPN({int(cap)},
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      {FACT}[SKU_CODE], {FACT}[PART_DESCRIPTION],
      {FACT}[CATEGORY_NAME], {FACT}[LOC_CODE],
      "pending_qty", SUM({FACT}[PENDING_ORDERS]),
      "pending_value", SUM({FACT}[PENDING_ORDERS_VALUE]),
      "days_no_sale", MAX({FACT}[DAYS_FROM_LAST_SALES])),
    {FACT}[LOC_CODE] IN {_shops_literal()},
    {FACT}[RECOMMENDED_ACTION] = "NON MOVING",
    {FACT}[PENDING_ORDERS] > 0{seg}),
  [pending_value], DESC)"""


def rule6_run(execute: Execute, *, cap: int = 25, seg_a_only: bool = False) -> list[dict]:
    rows = execute(rule6_dax(cap=cap, seg_a_only=seg_a_only))
    out = []
    for row in rows:
        out.append({
            "sku_code": _text(row, "SKU_CODE"), "description": _text(row, "PART_DESCRIPTION"),
            "category": _text(row, "CATEGORY_NAME"), "location": _text(row, "LOC_CODE"),
            "pending_qty": _num(row, "pending_qty"), "pending_value": _num(row, "pending_value"),
            "days_no_sale": _num(row, "days_no_sale"),
        })
    out.sort(key=lambda r: -r["pending_value"])
    return out


# ---------------------------------------------------------------------------
# Rule 7 - overstocked SKUs with a pending purchase order.
# ---------------------------------------------------------------------------

def rule7_dax(*, top_n: int = 10, seg_a_only: bool = False) -> str:
    seg = f',\n    {FACT}[SKUSEGMENT] = "SEG_A"' if seg_a_only else ""
    return f"""EVALUATE
TOPN({int(top_n)},
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      {FACT}[SKU_CODE], {FACT}[PART_DESCRIPTION],
      {FACT}[CATEGORY_NAME], {FACT}[LOC_CODE],
      "excess_value", SUM({FACT}[EXCESS_STOCK_VALUE]),
      "pending_qty", SUM({FACT}[PENDING_ORDERS]),
      "pending_value", SUM({FACT}[PENDING_ORDERS_VALUE])),
    {FACT}[LOC_CODE] IN {_shops_literal()},
    {FACT}[RECOMMENDED_ACTION] = "OVERSTOCK",
    {FACT}[PENDING_ORDERS] > 0{seg}),
  [excess_value], DESC)"""


def rule7_run(execute: Execute, *, top_n: int = 10, seg_a_only: bool = False) -> list[dict]:
    rows = execute(rule7_dax(top_n=top_n, seg_a_only=seg_a_only))
    out = []
    for row in rows:
        out.append({
            "sku_code": _text(row, "SKU_CODE"), "description": _text(row, "PART_DESCRIPTION"),
            "category": _text(row, "CATEGORY_NAME"), "location": _text(row, "LOC_CODE"),
            "excess_value": _num(row, "excess_value"), "pending_qty": _num(row, "pending_qty"),
            "pending_value": _num(row, "pending_value"),
        })
    out.sort(key=lambda r: -r["excess_value"])
    return out


# ---------------------------------------------------------------------------
# Rule 8 - SKUs currently at their 90-day price floor.
# ---------------------------------------------------------------------------

def rule8_dax(*, top_n: int = 10, spread_pct: float = 0.03, floor_tolerance_pct: float = 0.001,
              seg_a_only: bool = False) -> str:
    seg = f',\n      {FACT}[SKUSEGMENT] = "SEG_A"' if seg_a_only else ""
    return f"""EVALUATE
VAR Base =
  ADDCOLUMNS(
    CALCULATETABLE(
      SUMMARIZE({FACT},
        {FACT}[SKU_CODE], {FACT}[LOC_CODE],
        {FACT}[PART_DESCRIPTION], {FACT}[CATEGORY_NAME]),
      {FACT}[LOC_CODE] IN {_shops_literal()}{seg}),
    "RP", CALCULATE(MAX({PRICE_TABLE}[RP])),
    "minRP", CALCULATE(MIN('{TOP_DATES_TABLE}'[min_rp])),
    "maxRP", CALCULATE(MAX('{TOP_DATES_TABLE}'[max_rp])),
    "val3m", CALCULATE(SUM({FACT}[SALES_VALUE_LAST_3MONTHS])))
VAR AtFloor =
  FILTER(Base,
    NOT ISBLANK([RP]) && NOT ISBLANK([maxRP]) && [maxRP] > 0
    && ([maxRP] - [minRP]) > [minRP] * {spread_pct}
    && [RP] <= [minRP] * (1 + {floor_tolerance_pct}))
RETURN TOPN({int(top_n)}, AtFloor, [val3m], DESC)"""


def rule8_run(execute: Execute, *, top_n: int = 10, seg_a_only: bool = False) -> list[dict]:
    rows = execute(rule8_dax(top_n=top_n, seg_a_only=seg_a_only))
    out = []
    for row in rows:
        out.append({
            "sku_code": _text(row, "SKU_CODE"), "description": _text(row, "PART_DESCRIPTION"),
            "category": _text(row, "CATEGORY_NAME"), "location": _text(row, "LOC_CODE"),
            "price": _num(row, "RP"), "min_price_90d": _num(row, "minRP"),
            "max_price_90d": _num(row, "maxRP"), "sales_3m": _num(row, "val3m"),
        })
    out.sort(key=lambda r: -r["sales_3m"])
    return out


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

RULE_NAMES = {
    1: "Top-performing SKUs per department",
    2: "Rank promotion / demotion",
    3: "Best sales day was yesterday",
    4: "Segment A stockouts",
    5: "Verge of stockout, stock in warehouse",
    6: "Non-moving with a pending order",
    7: "Overstocked with a pending order",
    8: "At the 90-day price floor",
}


def department_rollup_dax(*, seg_a_only: bool = False) -> str:
    seg = f'\n    {FACT}[SKUSEGMENT] = "SEG_A",' if seg_a_only else ""
    return f"""EVALUATE
CALCULATETABLE(
  SUMMARIZECOLUMNS(
    {FACT}[DEPARTMENT],
    "products", DISTINCTCOUNT({FACT}[SKU_CODE]),
    "lines", COUNTROWS({FACT}),
    "sales_1m", SUM({FACT}[SALES_VALUE_LAST_1MONTH]),
    "sales_3m", SUM({FACT}[SALES_VALUE_LAST_3MONTHS]),
    "stock_value", SUM({FACT}[SKU_STOCK_VALUE]),
    "excess_value", SUM({FACT}[EXCESS_STOCK_VALUE])
  ),{seg}
  {FACT}[LOC_CODE] IN {_shops_literal()}
)
ORDER BY [sales_3m] DESC"""


def shop_rollup_dax(*, seg_a_only: bool = False) -> str:
    seg = f'\n    {FACT}[SKUSEGMENT] = "SEG_A",' if seg_a_only else ""
    return f"""EVALUATE
CALCULATETABLE(
  SUMMARIZECOLUMNS(
    {FACT}[LOC_CODE],
    "products", DISTINCTCOUNT({FACT}[SKU_CODE]),
    "sales_1m", SUM({FACT}[SALES_VALUE_LAST_1MONTH]),
    "sales_3m", SUM({FACT}[SALES_VALUE_LAST_3MONTHS]),
    "stock_value", SUM({FACT}[SKU_STOCK_VALUE]),
    "excess_value", SUM({FACT}[EXCESS_STOCK_VALUE])
  ),{seg}
  {FACT}[LOC_CODE] IN {_shops_literal()}
)
ORDER BY [sales_3m] DESC"""


def warehouse_reference_dax() -> str:
    """The two warehouses, for the one place the rulebook allows them: a
    reference note, never counted into a shop/sales total."""
    return f"""EVALUATE
CALCULATETABLE(
  SUMMARIZECOLUMNS(
    {FACT}[LOC_CODE],
    "lines", COUNTROWS({FACT}),
    "stock_value", SUM({FACT}[SKU_STOCK_VALUE])
  ),
  {FACT}[LOC_CODE] IN {{"WH1", "WH2"}}
)"""


def state_table_dax(*, seg_a_only: bool = False) -> str:
    """The full RECOMMENDED_ACTION breakdown with sales - the same rank-bar
    data the Overview shows, but as a complete table (never truncated to a
    top-N) with the sales figure the bars alone cannot carry."""
    seg = f'\n    {FACT}[SKUSEGMENT] = "SEG_A",' if seg_a_only else ""
    return f"""EVALUATE
CALCULATETABLE(
  SUMMARIZECOLUMNS(
    {FACT}[RECOMMENDED_ACTION],
    "rows", COUNTROWS({FACT}),
    "sales_3m", SUM({FACT}[SALES_VALUE_LAST_3MONTHS]),
    "stock_value", SUM({FACT}[SKU_STOCK_VALUE])
  ),{seg}
  {FACT}[LOC_CODE] IN {_shops_literal()}
)
ORDER BY [rows] DESC"""


def department_shop_detail(execute: Execute, *, seg_a_only: bool = False) -> dict:
    """Departments and shops layer data: full rollups, never top-N'd, plus
    the warehouse reference and the complete instruction-state table."""
    dept_rows = execute(department_rollup_dax(seg_a_only=seg_a_only))
    shop_rows = execute(shop_rollup_dax(seg_a_only=seg_a_only))
    wh_rows = execute(warehouse_reference_dax())
    state_rows = execute(state_table_dax(seg_a_only=seg_a_only))

    def rollup(rows, key_col, extra=()):
        out = []
        for row in rows:
            entry = {"key": _text(row, key_col), "products": int(_num(row, "products")),
                    "sales_1m": _num(row, "sales_1m"), "sales_3m": _num(row, "sales_3m"),
                    "stock_value": _num(row, "stock_value"),
                    "excess_value": _num(row, "excess_value")}
            for e in extra:
                entry[e] = int(_num(row, e))
            out.append(entry)
        return out

    departments = rollup(dept_rows, "DEPARTMENT", extra=("lines",))
    shops = rollup(shop_rows, "LOC_CODE")
    warehouses = [{"location": _text(r, "LOC_CODE"), "lines": int(_num(r, "lines")),
                  "stock_value": _num(r, "stock_value")} for r in wh_rows]
    states = [{"action": _text(r, "RECOMMENDED_ACTION"), "rows": int(_num(r, "rows")),
              "sales_3m": _num(r, "sales_3m"), "stock_value": _num(r, "stock_value")}
             for r in state_rows]
    states.sort(key=lambda s: -s["rows"])

    quiet_shop = min(shops, key=lambda s: s["sales_1m"], default=None)
    quiet_note = None
    if quiet_shop and quiet_shop["sales_1m"] == 0 and quiet_shop["sales_3m"] > 0:
        quiet_note = quiet_shop

    return {"departments": departments, "shops": shops, "warehouses": warehouses,
           "states": states, "quiet_shop": quiet_note}


def run_all(execute: Execute, cfg: dict, *, seg_a_only: bool = False, log=None) -> dict:
    """Every rule that can run today. Non-fatal per rule: one broken query
    must not cost the other seven.

    `seg_a_only` recomputes every figure - including rule 4, which is
    already Segment-A scoped by definition - over Segment A products only,
    for the "Best sellers only" view. It is a genuinely separate scan, not a
    filter on the all-products result: every total in this view is worked
    out again from just those products, matching the reference's own
    "over just those products" framing."""
    top_n = int(cfg.get("sku_overview_insight_top_n", 10) or 10)
    dept_top_n = int(cfg.get("sku_overview_insight_dept_top_n", 3) or 3)
    cap6 = int(cfg.get("sku_overview_insight_rule6_cap", 25) or 25)
    out: dict = {"rules": {}, "errors": {}, "seg_a_only": seg_a_only}

    def run(name: str, fn) -> None:
        if log:
            log(f"  rule: {name}")
        try:
            out["rules"][name] = fn()
        except Exception as exc:  # noqa: BLE001 - one bad rule must not cost the rest
            out["errors"][name] = f"{type(exc).__name__}: {exc}"
            if log:
                log(f"    skipped: {out['errors'][name]}")

    run("top_performers", lambda: rule1_run(execute, top_n=dept_top_n, seg_a_only=seg_a_only))
    out["rules"]["rank_movers"] = rule2_status()
    run("best_day_yesterday", lambda: rule3_run(execute, top_n=top_n, seg_a_only=seg_a_only))
    run("segment_a_stockouts", lambda: rule4_run(execute, top_n=top_n))
    run("verge_stockout_in_warehouse", lambda: rule5_run(execute, top_n=top_n, seg_a_only=seg_a_only))
    run("non_moving_pending_order", lambda: rule6_run(execute, cap=cap6, seg_a_only=seg_a_only))
    run("overstock_pending_order", lambda: rule7_run(execute, top_n=top_n, seg_a_only=seg_a_only))
    run("at_price_floor", lambda: rule8_run(execute, top_n=top_n, seg_a_only=seg_a_only))
    return out


# ---------------------------------------------------------------------------
# turning the four "action" rules into stat_signals-shaped findings, so the
# existing memory / trend / KPI-feed machinery (built for the earlier generic
# detector) keeps working unchanged, fed by the report's own precise rules
# instead. Rules 1/3/8 are "what is selling" content, not alerts, and stay
# out of this feed - a top seller is not an exception to act on.
# ---------------------------------------------------------------------------

_REPORT_ID = "sku_overview"


def _story_key(kind: str, anchor: str) -> str:
    blob = json.dumps([_REPORT_ID, "insight", kind, anchor], separators=(",", ":"))
    return "skuins:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def to_signals(insights: dict, model: dict) -> list[dict]:
    rules = insights.get("rules") or {}
    anchor = str(model.get("as_at") or "")
    total_rows = float((model.get("header") or {}).get("rows") or 0.0) or 1.0
    out: list[dict] = []

    stockouts = rules.get("segment_a_stockouts") or {}
    count = int(stockouts.get("count") or 0)
    if count:
        share = count / total_rows * 100.0
        out.append({
            "candidate_id": "sku_overview_segment_a_stockout:estate:",
            "story_key": _story_key("segment_a_stockout", anchor),
            "report_id": _REPORT_ID, "analysis_type": "sku_overview_segment_a_stockout",
            "dimension": "estate", "affected_segment": "Segment A stockouts",
            "metric": "Segment A Loc-SKUs out of stock", "current": count,
            "impact_value": float(stockouts.get("opp_loss_total") or 0.0),
            "impact_share": share, "score": 500.0 + share,
            "severity": "critical",
            "comparison_label": "share of all Loc-SKU rows in the five shops",
            "description": (
                f"{count:,} Segment A Loc-SKUs are out of stock in the shops, "
                f"an estimated {stockouts.get('opp_loss_total', 0.0):,.0f} of "
                f"Opportunity Loss (from rows where the model estimates one)."),
        })

    verge = rules.get("verge_stockout_in_warehouse") or []
    if verge:
        total_sales = sum(r["sales_3m"] for r in verge)
        out.append({
            "candidate_id": "sku_overview_verge_stockout_fixable:estate:",
            "story_key": _story_key("verge_stockout_fixable", anchor),
            "report_id": _REPORT_ID, "analysis_type": "sku_overview_verge_stockout_fixable",
            "dimension": "estate", "affected_segment": "Verge of stockout, fixable today",
            "metric": "Loc-SKUs on the verge of stockout with warehouse stock available",
            "current": len(verge), "impact_value": total_sales,
            "impact_share": None, "score": 400.0,
            "severity": "warning",
            "comparison_label": "3-month sales value of the affected Loc-SKUs",
            "description": (
                f"{len(verge)} Loc-SKUs are on the verge of stockout with stock "
                f"already sitting in a warehouse - a same-day transfer, not a "
                f"purchase order, would fix them."),
        })

    non_moving = rules.get("non_moving_pending_order") or []
    if non_moving:
        total_pending = sum(r["pending_value"] for r in non_moving)
        out.append({
            "candidate_id": "sku_overview_non_moving_pending:estate:",
            "story_key": _story_key("non_moving_pending", anchor),
            "report_id": _REPORT_ID, "analysis_type": "sku_overview_non_moving_pending",
            "dimension": "estate", "affected_segment": "Non-moving with stock on order",
            "metric": "Pending Orders Value on non-moving Loc-SKUs",
            "current": len(non_moving), "impact_value": total_pending,
            "impact_share": None, "score": 300.0,
            "severity": "warning",
            "comparison_label": "total Pending Orders Value on these Loc-SKUs",
            "description": (
                f"{len(non_moving)} Loc-SKUs are not moving and still have "
                f"{total_pending:,.0f} of stock on order - worth cancelling or "
                f"deferring."),
        })

    overstock = rules.get("overstock_pending_order") or []
    if overstock:
        total_excess = sum(r["excess_value"] for r in overstock)
        out.append({
            "candidate_id": "sku_overview_overstock_pending:estate:",
            "story_key": _story_key("overstock_pending", anchor),
            "report_id": _REPORT_ID, "analysis_type": "sku_overview_overstock_pending",
            "dimension": "estate", "affected_segment": "Overstocked with more on order",
            "metric": "Excess Stock Value already held on overstocked Loc-SKUs",
            "current": len(overstock), "impact_value": total_excess,
            "impact_share": None, "score": 250.0,
            "severity": "warning",
            "comparison_label": "Excess Stock Value already held",
            "description": (
                f"{len(overstock)} Loc-SKUs are already overstocked and have "
                f"more stock on order, {total_excess:,.0f} of Excess Stock "
                f"Value already sitting there."),
        })

    out.sort(key=lambda s: (-float(s.get("score") or 0.0), str(s.get("candidate_id"))))
    for index, signal in enumerate(out, start=1):
        signal["id"] = f"I{index}"
    return out
