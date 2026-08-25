""""One product in full" - the reference's per-SKU spotlight.

Not a lookup tool: this pipeline produces one automated daily report, so
there is no user picking a SKU. The product featured is chosen
deterministically - the #1 result of Rule 4 (Segment A stockouts, already
ranked by 3-month sales value descending), i.e. "the largest gap on the
shelf". If Rule 4 has no stockouts today, the next rule in the rulebook's
own action-priority order supplies the subject instead, so the layer is
absent only when every action rule is genuinely empty.

Every number here is a fresh, real query against the SKU actually selected -
never a subset carved out of another rule's already-fetched rows - because
the reference's per-product page is a different grain (one SKU across all
five shops, a 12-week trend, a 90-day price band) than any existing scan.
Table/column names are confirmed live against the model (`WEEK SALES`,
`CURR_RP_SALES_DAYS`, `TOP SALES DATES IN LOC`; see sku_overview_insights.py
for the same tables' use in rules 3 and 8).
"""

from __future__ import annotations

from typing import Callable

Execute = Callable[[str], list[dict]]

FACT = "REP_SSR_STOCK_STATUS_REPORTV3"
WEEK_SALES_TABLE = "WEEK SALES"
PRICE_TABLE = "CURR_RP_SALES_DAYS"
TOP_DATES_TABLE = "TOP SALES DATES IN LOC"
SHOPS = ("ST1", "ST2", "ST3", "ST4", "ST5")


def _shops_literal() -> str:
    return "{" + ", ".join(f'"{s}"' for s in SHOPS) + "}"


def _esc(value: str) -> str:
    return str(value).replace('"', '""')


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
# selection - reuses whichever action rule actually found something, in the
# rulebook's own priority order (BR-31-style: emptiest shelf first).
# ---------------------------------------------------------------------------

def select_product(insights: dict | None) -> dict | None:
    """Picks the subject SKU from the already-computed rule results. Returns
    `{"sku_code", "description", "category", "location", "reason"}` or None
    when every action rule came back empty (a genuinely quiet day)."""
    rules = (insights or {}).get("rules") or {}

    stockouts = (rules.get("segment_a_stockouts") or {}).get("top") or []
    if stockouts:
        row = stockouts[0]
        return {"sku_code": row["sku_code"], "description": row["description"],
                "category": row["category"], "location": row["location"],
                "reason": "the largest gap on the shelf - your best-selling "
                          "Segment A line that is currently out of stock"}

    verge = rules.get("verge_stockout_in_warehouse") or []
    if verge:
        row = verge[0]
        return {"sku_code": row["sku_code"], "description": row["description"],
                "category": row["category"], "location": row["location"],
                "reason": "closest to running out, with stock already sitting "
                          "in a warehouse"}

    overstock = rules.get("overstock_pending_order") or []
    if overstock:
        row = overstock[0]
        return {"sku_code": row["sku_code"], "description": row["description"],
                "category": row["category"], "location": row["location"],
                "reason": "the largest overstock still carrying more stock on order"}

    non_moving = rules.get("non_moving_pending_order") or []
    if non_moving:
        row = non_moving[0]
        return {"sku_code": row["sku_code"], "description": row["description"],
                "category": row["category"], "location": row["location"],
                "reason": "not moving at all, with stock still on order"}

    return None


# ---------------------------------------------------------------------------
# per-shop status
# ---------------------------------------------------------------------------

def status_dax(sku_code: str) -> str:
    sku = _esc(sku_code)
    return f"""EVALUATE
CALCULATETABLE(
  SUMMARIZECOLUMNS(
    {FACT}[LOC_CODE],
    {FACT}[RECOMMENDED_ACTION],
    "current_stock", SUM({FACT}[CURRENT_STOCK]),
    "stock_value", SUM({FACT}[SKU_STOCK_VALUE]),
    "sales_1m", SUM({FACT}[SALES_VALUE_LAST_1MONTH]),
    "sales_3m", SUM({FACT}[SALES_VALUE_LAST_3MONTHS]),
    "opp_loss", SUM({FACT}[OPP_LOSS_DUE_TO_STOCKOUT]),
    "pending_qty", SUM({FACT}[PENDING_ORDERS]),
    "pending_value", SUM({FACT}[PENDING_ORDERS_VALUE]),
    "excess_value", SUM({FACT}[EXCESS_STOCK_VALUE]),
    "burnout", MIN({FACT}[EXPECTED_BURNOUT_DAYS]),
    "days_no_sale", MAX({FACT}[DAYS_FROM_LAST_SALES])
  ),
  {FACT}[SKU_CODE] = "{sku}",
  {FACT}[LOC_CODE] IN {_shops_literal()}
)
ORDER BY {FACT}[LOC_CODE]"""


def status_run(execute: Execute, sku_code: str) -> list[dict]:
    rows = execute(status_dax(sku_code))
    out = []
    for row in rows:
        out.append({
            "location": _text(row, "LOC_CODE"), "action": _text(row, "RECOMMENDED_ACTION"),
            "current_stock": _num(row, "current_stock"), "stock_value": _num(row, "stock_value"),
            "sales_1m": _num(row, "sales_1m"), "sales_3m": _num(row, "sales_3m"),
            "opp_loss": (_num(row, "opp_loss") if _read(row, "opp_loss") is not None else None),
            "pending_qty": _num(row, "pending_qty"), "pending_value": _num(row, "pending_value"),
            "excess_value": _num(row, "excess_value"),
            "burnout": (_num(row, "burnout") if _read(row, "burnout") is not None else None),
            "days_no_sale": _num(row, "days_no_sale"),
        })
    out.sort(key=lambda r: r["location"])
    return out


# ---------------------------------------------------------------------------
# weekly sales trend (last N weeks, all five shops combined)
# ---------------------------------------------------------------------------

def weekly_dax(sku_code: str, *, weeks: int = 12) -> str:
    sku = _esc(sku_code)
    return f"""EVALUATE
VAR Weekly =
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      '{WEEK_SALES_TABLE}'[week_start_date],
      '{WEEK_SALES_TABLE}'[week_end_date],
      "qty", SUM('{WEEK_SALES_TABLE}'[sales_qty])
    ),
    '{WEEK_SALES_TABLE}'[SKU] = "{sku}",
    '{WEEK_SALES_TABLE}'[LOC_CODE] IN {_shops_literal()}
  )
RETURN TOPN({int(weeks)}, Weekly, [week_start_date], DESC)"""


def weekly_run(execute: Execute, sku_code: str, *, weeks: int = 12) -> list[dict]:
    rows = execute(weekly_dax(sku_code, weeks=weeks))
    out = [{"week_start": str(_read(r, "week_start_date") or "").split("T")[0],
           "week_end": str(_read(r, "week_end_date") or "").split("T")[0],
           "qty": _num(r, "qty")} for r in rows]
    out.sort(key=lambda r: r["week_start"])
    return out


# ---------------------------------------------------------------------------
# price - current price per shop, and the 90-day range already computed on
# the side tables Rule 8 uses.
# ---------------------------------------------------------------------------

def price_dax(sku_code: str) -> str:
    sku = _esc(sku_code)
    return f"""EVALUATE
CALCULATETABLE(
  SUMMARIZECOLUMNS(
    {PRICE_TABLE}[LOC_CODE],
    "rp", MAX({PRICE_TABLE}[RP])
  ),
  {PRICE_TABLE}[SKU] = "{sku}",
  {PRICE_TABLE}[LOC_CODE] IN {_shops_literal()}
)
ORDER BY {PRICE_TABLE}[LOC_CODE]"""


def price_range_dax(sku_code: str) -> str:
    sku = _esc(sku_code)
    return f"""EVALUATE ROW(
  "min_rp", CALCULATE(
    MIN('{TOP_DATES_TABLE}'[min_rp]),
    '{TOP_DATES_TABLE}'[SKU] = "{sku}",
    '{TOP_DATES_TABLE}'[LOC_CODE] IN {_shops_literal()}),
  "max_rp", CALCULATE(
    MAX('{TOP_DATES_TABLE}'[max_rp]),
    '{TOP_DATES_TABLE}'[SKU] = "{sku}",
    '{TOP_DATES_TABLE}'[LOC_CODE] IN {_shops_literal()})
)"""


def price_run(execute: Execute, sku_code: str) -> dict:
    per_shop = execute(price_dax(sku_code))
    range_rows = execute(price_range_dax(sku_code))
    range_row = range_rows[0] if range_rows else {}
    return {
        "per_shop": [{"location": _text(r, "LOC_CODE"), "price": _num(r, "rp")} for r in per_shop],
        "min_90d": (_num(range_row, "min_rp") if _read(range_row, "min_rp") is not None else None),
        "max_90d": (_num(range_row, "max_rp") if _read(range_row, "max_rp") is not None else None),
    }


# ---------------------------------------------------------------------------
# category comparison
# ---------------------------------------------------------------------------

def category_dax(category: str) -> str:
    cat = _esc(category)
    return f"""EVALUATE ROW(
  "cat_skus", CALCULATE(
    DISTINCTCOUNT({FACT}[SKU_CODE]),
    {FACT}[CATEGORY_NAME] = "{cat}", {FACT}[LOC_CODE] IN {_shops_literal()}),
  "cat_sales_3m", CALCULATE(
    SUM({FACT}[SALES_VALUE_LAST_3MONTHS]),
    {FACT}[CATEGORY_NAME] = "{cat}", {FACT}[LOC_CODE] IN {_shops_literal()}),
  "cat_stock_value", CALCULATE(
    SUM({FACT}[SKU_STOCK_VALUE]),
    {FACT}[CATEGORY_NAME] = "{cat}", {FACT}[LOC_CODE] IN {_shops_literal()}),
  "cat_excess_value", CALCULATE(
    SUM({FACT}[EXCESS_STOCK_VALUE]),
    {FACT}[CATEGORY_NAME] = "{cat}", {FACT}[LOC_CODE] IN {_shops_literal()})
)"""


def category_run(execute: Execute, category: str) -> dict:
    rows = execute(category_dax(category))
    row = rows[0] if rows else {}
    cat_skus = int(_num(row, "cat_skus"))
    return {
        "category": category, "cat_skus": cat_skus,
        "cat_sales_3m": _num(row, "cat_sales_3m"), "cat_stock_value": _num(row, "cat_stock_value"),
        "cat_excess_value": _num(row, "cat_excess_value"),
        "avg_sales_3m_per_sku": (_num(row, "cat_sales_3m") / cat_skus) if cat_skus else 0.0,
    }


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def build(execute: Execute, insights: dict | None, *, weeks: int = 12, log=None) -> dict | None:
    """Runs every product-page query for the selected subject SKU. Returns
    None when no action rule had a candidate to feature (quiet day) - the
    page must say so plainly, not fabricate a subject."""
    subject = select_product(insights)
    if not subject:
        return None
    sku_code = subject["sku_code"]
    if log:
        log(f"  one product in full: {sku_code}")

    status = status_run(execute, sku_code)
    weekly = weekly_run(execute, sku_code, weeks=weeks)
    price = price_run(execute, sku_code)
    category = category_run(execute, subject["category"]) if subject.get("category") else None

    total_stock_value = sum(r["stock_value"] for r in status)
    total_sales_3m = sum(r["sales_3m"] for r in status)
    total_sales_1m = sum(r["sales_1m"] for r in status)
    total_opp_loss = sum(r["opp_loss"] for r in status if r["opp_loss"] is not None)

    return {
        "subject": subject, "status": status, "weekly": weekly, "price": price,
        "category": category,
        "totals": {
            "stock_value": total_stock_value, "sales_3m": total_sales_3m,
            "sales_1m": total_sales_1m, "opp_loss": total_opp_loss,
            "shops_with_stock": sum(1 for r in status if r["current_stock"] > 0),
            "shops_out": sum(1 for r in status if r["current_stock"] <= 0),
        },
    }
