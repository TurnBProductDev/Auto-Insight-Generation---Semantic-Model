"""Daily Sales - the scan and the report model.

SB Mart's second sales report, over a THIRD semantic model
(`8d111712-9ea8-4a65-9bb9-58f00e49d379`) unrelated to Sales YoY or Target
Tracker. Unlike either of those, the model does not hand the report raw
transactions: it hands it a pre-joined, pre-benchmarked snapshot -
`storebenchmark` / `departmentbenchmark` / `sectionbenchmark` /
`categorybenchmark` each carry one row per (store x grain) for the CURRENT
day only, already paired with that day's own historical P20/P50/P80 band
for its weekday-and-week-of-month cohort (e.g. "past Wednesdays in week 2
of the month"). There is no raw fact table exposed and no per-day history
beyond the 14-row `_Sparkline14` table, so this report reads and reshapes
those pre-computed figures rather than computing percentiles itself.

**A verified, real defect in the source model limits what this report can
show.** Recovering the measure DAX via Fabric `getDefinition` and
cross-checking it against the raw table columns established that every
SUM-based Net Sales figure below the store level is inflated by a
consistent ~3.7x (verified: `departmentbenchmark`, `sectionbenchmark` and
`categorybenchmark` each independently summed to the SAME 115,999.35 for
ST4 on 2026-08-12, against a true store total of 31,319.82 confirmed by
`storebenchmark` and matching the reference design's own figure exactly).
`storebenchmark[sales_p20/p50/p80]` and `_Sparkline14`'s own sales/basket
percentile columns carry the identical inflation. Bills (count-distinct-like)
and Margin (a ratio) are unaffected everywhere checked - consistent with a
join fan-out somewhere upstream of Power BI, not a filter mistake here.
Confirmed with the report owner (2026-08-24): ship now with the reliable
subset, not wait for an upstream fix.

What this means concretely:
  * Net Sales ACTUAL is trustworthy only at the store grain
    (`storebenchmark`) and the whole-business grain (`_Sparkline14`) -
    never at department/section/category grain, where it is omitted rather
    than shown wrong.
  * Net Sales and Basket Value BANDS (P20/P50/P80, and anything derived -
    Tmin/Tmax/verdict) are not trustworthy at ANY grain and are never
    shown. Basket Value ACTUAL (= Sales / Bills) is shown only where Sales
    ACTUAL itself is trustworthy.
  * Bills and Margin - actual, P20, P50, P80, verdict - are trustworthy at
    every grain and carry this report's benchmark comparisons.
  * Per-store day-by-day history does not exist in this model
    (`storebenchmark` holds one row per store, not 14) - only the
    whole-business `_Sparkline14` trend is buildable.

`daily_sales_mapping` in config names every table/column so a future
client's differently-named model can be pointed at the same code, per this
repo's established convention (never hardcode a model-specific name).
"""

from __future__ import annotations

import datetime as _dt
from typing import Callable

Execute = Callable[[str], list[dict]]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _clean_key(key: object) -> str:
    return str(key).split("[")[-1].strip("]").lower()


def _read(row: dict, name: str):
    wanted = name.lower()
    for key, value in (row or {}).items():
        if _clean_key(key) == wanted:
            return value
    return None


def _num(row: dict, name: str) -> float | None:
    value = _read(row, name)
    return float(value) if isinstance(value, (int, float)) else None


def _text(row: dict, name: str) -> str:
    value = _read(row, name)
    return str(value) if value is not None else ""


def _date(row: dict, name: str) -> str:
    value = _read(row, name)
    return str(value or "").split("T")[0]


def _table(cfg: dict, key: str) -> str:
    name = str((cfg.get("daily_sales_mapping") or {}).get(key) or "")
    if not name:
        raise ValueError(f"daily_sales_mapping.{key} is required")
    return name


def _col(cfg: dict, key: str) -> str:
    return str((cfg.get("daily_sales_mapping") or {}).get(key) or "")


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def build_queries(cfg: dict) -> dict[str, str]:
    store_tbl = _table(cfg, "store_table")
    dept_tbl = _table(cfg, "department_table")
    section_tbl = _table(cfg, "section_table")
    category_tbl = _table(cfg, "category_table")
    spark_tbl = _table(cfg, "sparkline_table")

    return {
        "meta": """EVALUATE ROW(
  "store_latest", [Store Latest Date],
  "dept_latest", [Dept Latest Date],
  "section_latest", [Section Latest Date],
  "category_latest", [Category Latest Date],
  "last_updated", [Last Updated]
)""",
        "store": f"""EVALUATE
VAR LatestDate = [Store Latest Date]
RETURN CALCULATETABLE({store_tbl}, {store_tbl}[tran_date] = LatestDate)""",
        "department": f"""EVALUATE
VAR LatestDate = [Dept Latest Date]
RETURN CALCULATETABLE({dept_tbl}, {dept_tbl}[tran_date] = LatestDate)""",
        "section": f"""EVALUATE
VAR LatestDate = [Section Latest Date]
RETURN CALCULATETABLE({section_tbl}, {section_tbl}[tran_date] = LatestDate)""",
        "category": f"""EVALUATE
VAR LatestDate = [Category Latest Date]
RETURN CALCULATETABLE({category_tbl}, {category_tbl}[tran_date] = LatestDate)""",
        "sparkline": f"EVALUATE {spark_tbl} ORDER BY {spark_tbl}[tran_date]",
    }


def scan(execute: Execute, cfg: dict, *, log: Callable[[str], None] | None = None) -> dict:
    queries = build_queries(cfg)
    result: dict = {}
    for name, dax in queries.items():
        if log:
            log(f"  {name}")
        result[name] = execute(dax)
    return result


# ---------------------------------------------------------------------------
# verdict classification - Bills and Margin only (the reliable measures)
# ---------------------------------------------------------------------------

def verdict(actual: float | None, p20: float | None, p80: float | None) -> dict:
    """`{"key": "crit"|"neutral"|"good"|None, "word": ...}`. `key` is None
    when any input is missing - never guessed as "in band"."""
    if actual is None or p20 is None or p80 is None:
        return {"key": None, "word": "Not available"}
    if actual < p20:
        return {"key": "crit", "word": "Underperforming"}
    if actual > p80:
        return {"key": "good", "word": "Outperforming"}
    return {"key": "neutral", "word": "In band"}


def _band_pos_pct(actual: float, p20: float, p80: float) -> float:
    """Where `actual` sits across [p20, p80] mapped to display range - used
    only for the bullet-chart tick position, matches the reference's own
    visual (band spans the middle third of the bar)."""
    span = (p80 - p20) or 1.0
    return (actual - p20) / span


# ---------------------------------------------------------------------------
# per-row measure bundle (Bills + Margin banded; Sales/Basket actual-only)
# ---------------------------------------------------------------------------

def _measure_bundle(row: dict, *, sales_reliable: bool) -> dict:
    bills_actual = _num(row, "actual_bills")
    bills_p20, bills_p50, bills_p80 = _num(row, "bills_p20"), _num(row, "bills_p50"), _num(row, "bills_p80")
    margin_actual = _num(row, "actual_margin")
    margin_p20, margin_p50, margin_p80 = _num(row, "margin_p20"), _num(row, "margin_p50"), _num(row, "margin_p80")
    sales_actual = _num(row, "actual_sales") if sales_reliable else None
    basket_actual = (sales_actual / bills_actual) if (sales_reliable and sales_actual is not None
                                                       and bills_actual) else None

    return {
        "sample_days": int(_num(row, "sample_days") or 0),
        "margin_sample_days": int(_num(row, "margin_sample_days") or 0),
        "net_sales": {"actual": sales_actual, "available": sales_reliable},
        "basket_value": {"actual": basket_actual, "available": sales_reliable},
        "bills": {
            "actual": bills_actual, "p20": bills_p20, "p50": bills_p50, "p80": bills_p80,
            "verdict": verdict(bills_actual, bills_p20, bills_p80),
        },
        "margin": {
            "actual": margin_actual, "p20": margin_p20, "p50": margin_p50, "p80": margin_p80,
            "verdict": verdict(margin_actual, margin_p20, margin_p80),
        },
    }


def _row_outside_band(bundle: dict) -> bool:
    return bundle["bills"]["verdict"]["key"] in ("crit", "good") or \
        bundle["margin"]["verdict"]["key"] in ("crit", "good")


# ---------------------------------------------------------------------------
# build - the reconciled model
# ---------------------------------------------------------------------------

def build(scan_result: dict, cfg: dict) -> dict:
    currency = str(cfg.get("daily_sales_currency") or "")
    store_col = _col(cfg, "store_col") or "store_no"
    dept_col = _col(cfg, "department_col") or "DEPARTMENT"
    section_col = _col(cfg, "section_col") or "SECTION"
    category_col = _col(cfg, "category_col") or "CATEGORY_NAME"

    meta_row = (scan_result.get("meta") or [{}])[0]
    as_at = _date(meta_row, "store_latest")
    last_updated = _text(meta_row, "last_updated")

    store_rows = scan_result.get("store") or []
    dow_name = _text(store_rows[0], "dow_name") if store_rows else ""
    week_of_month = int(_num(store_rows[0], "week_of_month") or 0) if store_rows else 0

    stores = []
    for row in store_rows:
        bundle = _measure_bundle(row, sales_reliable=True)
        stores.append({"store": _text(row, store_col), **bundle})
    stores.sort(key=lambda s: s["store"])

    total_sales = sum(s["net_sales"]["actual"] or 0.0 for s in stores)
    total_bills = sum(s["bills"]["actual"] or 0.0 for s in stores)

    spark_rows = scan_result.get("sparkline") or []
    sparkline = []
    for row in spark_rows:
        sparkline.append({
            "date": _date(row, "tran_date"),
            "net_sales_actual": _num(row, "actual_sales"),
            "bills": {"actual": _num(row, "actual_bills"), "p20": _num(row, "bills_p20"),
                     "p50": _num(row, "bills_p50"), "p80": _num(row, "bills_p80")},
            "margin": {"actual": _num(row, "margin_actual"), "p20": _num(row, "margin_p20"),
                      "p50": _num(row, "margin_p50"), "p80": _num(row, "margin_p80")},
        })
    sparkline.sort(key=lambda d: d["date"])
    today_spark = sparkline[-1] if sparkline else {}
    whole = {
        "net_sales": {"actual": _num(today_spark, "net_sales_actual") if today_spark else None,
                      "available": True},
        "bills": {**(today_spark.get("bills") or {}),
                 "verdict": verdict((today_spark.get("bills") or {}).get("actual"),
                                    (today_spark.get("bills") or {}).get("p20"),
                                    (today_spark.get("bills") or {}).get("p80"))},
        "margin": {**(today_spark.get("margin") or {}),
                  "verdict": verdict((today_spark.get("margin") or {}).get("actual"),
                                     (today_spark.get("margin") or {}).get("p20"),
                                     (today_spark.get("margin") or {}).get("p80"))},
    }
    if whole["bills"].get("actual") is not None and whole["bills"]["actual"]:
        whole["basket_value"] = {"actual": whole["net_sales"]["actual"] / whole["bills"]["actual"],
                                 "available": True}
    else:
        whole["basket_value"] = {"actual": None, "available": False}

    checks = {
        "store_sales_reconciles_to_whole": (
            abs(total_sales - (whole["net_sales"]["actual"] or 0.0)) < 1.0
            if whole["net_sales"]["actual"] is not None else False),
        "store_bills_reconciles_to_whole": total_bills == (whole["bills"].get("actual") or 0),
        "sparkline_has_today": bool(today_spark) and today_spark.get("date") == as_at,
    }

    def _grain_rows(key: str, name_col: str, parent_col: str | None) -> list[dict]:
        out = []
        for row in scan_result.get(key) or []:
            bundle = _measure_bundle(row, sales_reliable=False)
            entry = {"name": _text(row, name_col), "store": _text(row, store_col), **bundle}
            if parent_col:
                entry["parent"] = _text(row, parent_col)
            out.append(entry)
        return out

    departments = _grain_rows("department", dept_col, None)
    sections = _grain_rows("section", section_col, dept_col)
    categories = _grain_rows("category", category_col, section_col)

    model = {
        "report_id": str(cfg.get("report_id") or "daily_sales"),
        "report_name": str(cfg.get("report_name") or "Daily Sales"),
        "currency": currency,
        "as_at": as_at,
        "last_updated": last_updated,
        "dow_name": dow_name,
        "week_of_month": week_of_month,
        "stores": stores,
        "store_names": [s["store"] for s in stores],
        "whole": whole,
        "sparkline": sparkline,
        "departments": departments,
        "sections": sections,
        "categories": categories,
        "checks": checks,
        "sales_reliability": {
            "store_and_whole": True,
            "department_section_category": False,
            "reason": (
                "Net Sales and Basket Value figures below the store level, and every level's "
                "P20/P50/P80 bands for Net Sales and Basket Value, are inflated by a verified "
                "~3.7x join fan-out in the source model and are not shown. Bills and Margin are "
                "unaffected at every level and carry this report's comparisons."),
        },
    }
    return model


def dump_json(value: object) -> str:
    import json
    return json.dumps(value, indent=2, default=str)
