"""Daily Sales - the scan and the report model.

SB Mart's second sales report, over a THIRD semantic model
(`8d111712-9ea8-4a65-9bb9-58f00e49d379`) unrelated to Sales YoY or Target
Tracker. Unlike either of those, the model does not hand the report raw
transactions: it hands it a pre-joined, pre-benchmarked snapshot -
`storebenchmark` / `departmentbenchmark` / `sectionbenchmark` /
`categorybenchmark` each carry one row per (store x grain) per day, already
paired with that day's own historical P20/P50/P80 band for its
weekday-and-week-of-month cohort (e.g. "past Wednesdays in week 2 of the
month"). There is no raw fact table exposed, so this report reads and
reshapes those pre-computed figures rather than computing percentiles
itself.

The two scales, and why the report rescales rather than withholds
-----------------------------------------------------------------
Net Sales arrives on TWO different scales inside one model, and nothing in
the column names says which is which:

  * `storebenchmark[actual_sales]` and `_Sparkline14[actual_sales]` /
    `[profit_actual]` are on the REPORTING scale.
  * every `sales_p20/p50/p80`, every `basket_p*` / `profit_p*`, every
    `actual_cost`, and every `actual_sales` BELOW store level are on a
    SOURCE scale exactly `1 / 0.27` = 3.7037037037... times larger.

Measured, not assumed. Two independent routes agree to twelve decimal
places on every one of the 28 store-days the live model holds:

  * `actual_cost / (actual_sales x (1 - actual_margin/100))` - the store's
    own Margin is computed on the source scale, so this recovers the ratio
    between the two scales from a single row.
  * `SUM(department actual_sales) / store actual_sales` - the same
    constant, from an entirely different table.

Rescaling the source-scale figures by the measured factor makes every
level reconcile exactly: department, section AND category Net Sales each
sum to 69,360.3054 against a whole-business 69,360.3054, and each returns
a Margin of 23.1816% against a whole-business 23.1816% (figures for
2026-08-12, the position the approved reference design was drawn from).
Store costs rescaled sum to the whole-business cost to the cent. Bills is
a count and Margin a ratio, so neither is affected on either scale.

An earlier reading of the same numbers called this a "~3.7x join fan-out"
and withheld every affected figure. It is not a fan-out: a fan-out cannot
be constant to twelve decimal places across two tables and 28 days, and it
would not leave Margin correct. The constant is exactly 1/0.27, which is
what a currency conversion applied to the actuals but not to the benchmarks
looks like. The report does not assert that cause on the page - it states
what it measured and what it did about it.

The factor is a property of the model, not of this code: `measure_scale`
re-derives it every run from that run's own rows, requires the two routes
to agree, and **refuses to rescale** if they do not - in which case the
report degrades to the figures that need no rescale (Bills, Margin, and Net
Sales at store and whole-business level) and says so. A model that is later
fixed upstream measures a factor of 1.0 and the rescale becomes a no-op,
with no code change.

Grain, and the two category columns
-----------------------------------
`categorybenchmark` carries BOTH `CATEGORY_NAME_2` (the category) and
`CATEGORY_NAME` (the buying group underneath it). The reportable grain is
`(SECTION, CATEGORY_NAME_2)` - 117 categories with a sale on 2026-08-12,
built from 1,596 group rows. Treating the group column as the category
inflates the list to 218 rows of near-duplicates and loses the "groups that
recorded nothing today" finding entirely.

A row that recorded no sale is EXCLUDED from its parent's rollup, band
included. This is not a tidying choice: a benchmark carrying groups which
could not contribute makes every name read below its band. Verified against
the reference on the two grains where it changes a number - DELI's section
band, and every category band.

`daily_sales_mapping` in config names every table/column so a future
client's differently-named model can be pointed at the same code, per this
repo's established convention (never hardcode a model-specific name).
"""

from __future__ import annotations

import datetime as _dt
from typing import Callable

Execute = Callable[[str], list[dict]]

#: The two scale measurements must agree within this fraction before the
#: report will rescale anything. They agree to ~1e-12 on the live model; a
#: real disagreement means the assumption behind the rescale has broken.
SCALE_AGREEMENT = 1e-6

#: A factor this close to 1.0 means the model publishes one scale - nothing
#: to rescale, and no caveat to print.
SCALE_NEUTRAL = 1e-9

_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


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


def _col(cfg: dict, key: str, default: str = "") -> str:
    return str((cfg.get("daily_sales_mapping") or {}).get(key) or default)


def day_label(iso_date: str, dow_name: str = "") -> str:
    """`"Wednesday 12 August 2026"` - the reference's own date wording. Falls
    back to the raw value rather than guessing when the date will not parse."""
    try:
        parsed = _dt.date.fromisoformat(str(iso_date)[:10])
    except (TypeError, ValueError):
        return str(iso_date or "")
    weekday = dow_name or parsed.strftime("%A")
    return f"{weekday} {parsed.day} {_MONTHS[parsed.month - 1]} {parsed.year}"


def short_day(iso_date: str) -> str:
    """`"12 Aug"` - the trend axis and window wording."""
    try:
        parsed = _dt.date.fromisoformat(str(iso_date)[:10])
    except (TypeError, ValueError):
        return str(iso_date or "")
    return f"{parsed.day} {_MONTHS[parsed.month - 1][:3]}"


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
        "meta": 'EVALUATE ROW(\n'
                '  "store_latest", [Store Latest Date],\n'
                '  "dept_latest", [Dept Latest Date],\n'
                '  "section_latest", [Section Latest Date],\n'
                '  "category_latest", [Category Latest Date],\n'
                '  "last_updated", [Last Updated]\n'
                ')',
        # The whole store table, not just the latest day: it holds one row per
        # (store x day) over the same trailing window `_Sparkline14` covers,
        # which is what makes the per-store trend buildable. It is 28 rows on
        # the live model, so this costs nothing over fetching a single day.
        "store": f"EVALUATE {store_tbl} ORDER BY {store_tbl}[tran_date]",
        "department": (f"EVALUATE\nVAR LatestDate = [Dept Latest Date]\n"
                       f"RETURN CALCULATETABLE({dept_tbl}, {dept_tbl}[tran_date] = LatestDate)"),
        "section": (f"EVALUATE\nVAR LatestDate = [Section Latest Date]\n"
                    f"RETURN CALCULATETABLE({section_tbl}, {section_tbl}[tran_date] = LatestDate)"),
        "category": (f"EVALUATE\nVAR LatestDate = [Category Latest Date]\n"
                     f"RETURN CALCULATETABLE({category_tbl}, {category_tbl}[tran_date] = LatestDate)"),
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
# the two scales
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _cost_scale_factor(store_rows: list[dict]) -> tuple[float | None, int]:
    """The source-to-reporting ratio read from each store-day on its own:
    `actual_cost` is published on the source scale and `actual_margin` is
    computed there too, so `cost / (sales x (1 - margin))` is the ratio."""
    factors = []
    for row in store_rows:
        sales = _num(row, "actual_sales")
        cost = _num(row, "actual_cost")
        margin = _num(row, "actual_margin")
        if not sales or cost is None or margin is None:
            continue
        implied = sales * (1.0 - margin / 100.0)
        if abs(implied) < 1e-9:
            continue
        factors.append(cost / implied)
    return _median(factors), len(factors)


def _grain_scale_factor(store_rows: list[dict], grain_rows: list[dict],
                        store_col: str) -> tuple[float | None, int]:
    """The same ratio from an entirely different table: every department's Net
    Sales for a store, over that store's own Net Sales."""
    totals: dict[str, float] = {}
    for row in grain_rows:
        sales = _num(row, "actual_sales")
        if sales:
            key = _text(row, store_col)
            totals[key] = totals.get(key, 0.0) + sales
    factors = []
    for row in store_rows:
        sales = _num(row, "actual_sales")
        total = totals.get(_text(row, store_col))
        if sales and total:
            factors.append(total / sales)
    return _median(factors), len(factors)


def measure_scale(store_rows: list[dict], grain_rows: list[dict], *,
                  store_col: str = "store_no") -> dict:
    """`{"scale": float, "applied": bool, ...}` - what a source-scale figure
    must be multiplied by to sit on the same scale as the reporting figures.

    Two independent measurements must agree, or nothing is rescaled and the
    report degrades honestly. See this module's docstring for why."""
    cost_factor, cost_n = _cost_scale_factor(store_rows)
    grain_factor, grain_n = _grain_scale_factor(store_rows, grain_rows, store_col)
    result = {
        "cost_factor": cost_factor, "cost_observations": cost_n,
        "grain_factor": grain_factor, "grain_observations": grain_n,
        "factor": None, "scale": 1.0, "applied": False, "agreement": None,
        "reason": "",
    }
    if cost_factor is None or grain_factor is None:
        result["reason"] = (
            "The report could not measure the two Net Sales scales this run - it "
            "needs a store cost, a store margin and a department total - so no "
            "figure has been rescaled and Net Sales is shown only where it needs "
            "no rescale.")
        return result
    agreement = abs(cost_factor - grain_factor) / abs(cost_factor or 1.0)
    result["agreement"] = agreement
    if agreement > SCALE_AGREEMENT:
        result["reason"] = (
            "The two independent measurements of the Net Sales scale disagree "
            f"({cost_factor:,.6f} against {grain_factor:,.6f}), so no figure has "
            "been rescaled and Net Sales is shown only where it needs no rescale.")
        return result
    factor = (cost_factor + grain_factor) / 2.0
    result["factor"] = factor
    result["scale"] = 1.0 / factor
    result["applied"] = abs(factor - 1.0) > SCALE_NEUTRAL
    if not result["applied"]:
        result["scale"] = 1.0
        result["reason"] = ("The model publishes Net Sales on one scale, so nothing "
                            "needed rescaling.")
    else:
        result["reason"] = (
            "Net Sales for each store and for the whole business is published on one "
            "scale in the source, while every benchmark band, every cost and every Net "
            f"Sales figure below store level is published on another exactly {factor:,.4f} "
            "times larger. Two independent measurements taken from this run's own rows "
            "agree on that figure, so the second set has been brought onto the first. "
            "Every level then adds up to the whole business.")
    return result


# ---------------------------------------------------------------------------
# verdict classification
# ---------------------------------------------------------------------------

#: A value this close to a band edge IS the band edge. The bands are rescaled
#: by a measured factor, so a figure that sits exactly on its floor in the
#: source arrives a few parts in 1e-12 either side of it. Without this a store
#: that finished level with its floor is published as "Underperforming" - which
#: is what happened, and is the reason the tolerance exists. At 1e-9 relative
#: this is a fraction of a cent on any figure this report shows.
EDGE_TOLERANCE = 1e-9


def _at_edge(value: float, edge: float) -> bool:
    return abs(value - edge) <= max(abs(edge), 1.0) * EDGE_TOLERANCE


def verdict(actual: float | None, p20: float | None, p80: float | None) -> dict:
    """`{"key": "crit"|"neutral"|"good"|None, "word": ...}`. `key` is None when
    any input is missing - never guessed as "in band". A value sitting on an
    edge is inside the band: equal is not below."""
    if actual is None or p20 is None or p80 is None:
        return {"key": None, "word": "Not available"}
    if actual < p20 and not _at_edge(actual, p20):
        return {"key": "crit", "word": "Underperforming"}
    if actual > p80 and not _at_edge(actual, p80):
        return {"key": "good", "word": "Outperforming"}
    return {"key": "neutral", "word": "In band"}


def band_gap(actual: float | None, p20: float | None, p80: float | None) -> float | None:
    """Signed distance outside the band, 0.0 inside it, None if unavailable."""
    if actual is None or p20 is None or p80 is None:
        return None
    if actual < p20 and not _at_edge(actual, p20):
        return actual - p20
    if actual > p80 and not _at_edge(actual, p80):
        return actual - p80
    return 0.0


def _measure(actual: float | None, p20: float | None, p50: float | None,
             p80: float | None) -> dict:
    return {
        "actual": actual, "p20": p20, "p50": p50, "p80": p80,
        "verdict": verdict(actual, p20, p80),
        "gap": band_gap(actual, p20, p80),
        "vs_benchmark": (actual - p50) if (actual is not None and p50 is not None) else None,
    }


def _ratio(top: float | None, bottom: float | None) -> float | None:
    if top is None or not bottom:
        return None
    return top / bottom


def _bundle(sales: dict, bills: dict, margin: dict) -> dict:
    """The four measures for one row. Basket Value is derived - actual from the
    two actuals, and each band edge from the matching Net Sales and Bills edge,
    which is the only construction that keeps the band on the same scale as the
    value it brackets."""
    basket = _measure(
        _ratio(sales["actual"], bills["actual"]),
        _ratio(sales["p20"], bills["p20"]),
        _ratio(sales["p50"], bills["p50"]),
        _ratio(sales["p80"], bills["p80"]),
    )
    return {"net_sales": sales, "bills": bills, "basket_value": basket, "margin": margin}


def _blank_bundle() -> dict:
    empty = _measure(None, None, None, None)
    return {"net_sales": dict(empty), "bills": dict(empty),
            "basket_value": dict(empty), "margin": dict(empty)}


# ---------------------------------------------------------------------------
# rollups
# ---------------------------------------------------------------------------

_SUM_COLUMNS = ("actual_sales", "actual_cost", "sales_p20", "sales_p50", "sales_p80",
                "actual_bills", "bills_p20", "bills_p50", "bills_p80")


def _rollup(rows: list[dict]) -> dict:
    """Sums the addable columns over the rows that recorded a sale.

    A row with no sale is dropped, band included - a benchmark carrying groups
    which could not contribute makes every name read below its band."""
    totals: dict = {name: 0.0 for name in _SUM_COLUMNS}
    live = silent = 0
    silent_p50 = 0.0
    sample_days: list[int] = []
    margin_sample_days: list[int] = []
    for row in rows:
        if not _num(row, "actual_sales"):
            silent += 1
            silent_p50 += _num(row, "sales_p50") or 0.0
            continue
        live += 1
        for name in _SUM_COLUMNS:
            totals[name] += _num(row, name) or 0.0
        days = _num(row, "sample_days")
        if days:
            sample_days.append(int(days))
        margin_days = _num(row, "margin_sample_days")
        if margin_days:
            margin_sample_days.append(int(margin_days))
    totals["live_rows"] = live
    totals["silent_rows"] = silent
    totals["silent_benchmark"] = silent_p50
    totals["sample_days"] = max(sample_days) if sample_days else 0
    totals["margin_sample_days"] = max(margin_sample_days) if margin_sample_days else 0
    return totals


def _from_rollup(totals: dict, scale: float) -> dict:
    """The four-measure bundle for a rolled-up group. Margin is recomputed from
    the summed sales and cost rather than averaged across rows - the scale
    cancels out of a ratio, so this is exact whether or not anything was
    rescaled, and it needs no weighting rule."""
    sales_actual = totals["actual_sales"] * scale
    cost_actual = totals["actual_cost"] * scale
    sales = _measure(sales_actual, totals["sales_p20"] * scale,
                     totals["sales_p50"] * scale, totals["sales_p80"] * scale)
    bills = _measure(totals["actual_bills"] or None, totals["bills_p20"] or None,
                     totals["bills_p50"] or None, totals["bills_p80"] or None)
    margin_actual = ((sales_actual - cost_actual) / sales_actual * 100.0) if sales_actual else None
    bundle = _bundle(sales, bills, _measure(margin_actual, None, None, None))
    bundle["cost"] = cost_actual
    bundle["sample_days"] = totals["sample_days"]
    bundle["margin_sample_days"] = totals["margin_sample_days"]
    bundle["group_count"] = totals["live_rows"]
    bundle["silent_groups"] = totals["silent_rows"]
    bundle["silent_benchmark"] = totals["silent_benchmark"] * scale
    return bundle


def _mul(value: float | None, scale: float) -> float | None:
    return None if value is None else value * scale


def _store_bundle(row: dict, scale: float) -> dict:
    """One `storebenchmark` row. Net Sales actual is already on the reporting
    scale; its band, and the cost behind Margin, are not."""
    sales = _measure(_num(row, "actual_sales"),
                     _mul(_num(row, "sales_p20"), scale),
                     _mul(_num(row, "sales_p50"), scale),
                     _mul(_num(row, "sales_p80"), scale))
    bills = _measure(_num(row, "actual_bills"), _num(row, "bills_p20"),
                     _num(row, "bills_p50"), _num(row, "bills_p80"))
    margin = _measure(_num(row, "actual_margin"), _num(row, "margin_p20"),
                      _num(row, "margin_p50"), _num(row, "margin_p80"))
    bundle = _bundle(sales, bills, margin)
    bundle["sample_days"] = int(_num(row, "sample_days") or 0)
    bundle["margin_sample_days"] = int(_num(row, "margin_sample_days") or 0)
    bundle["cost"] = _mul(_num(row, "actual_cost"), scale)
    return bundle


# ---------------------------------------------------------------------------
# build - the reconciled model
# ---------------------------------------------------------------------------

def build(scan_result: dict, cfg: dict) -> dict:
    currency = str(cfg.get("daily_sales_currency") or "")
    store_col = _col(cfg, "store_col", "store_no")
    dept_col = _col(cfg, "department_col", "DEPARTMENT")
    section_col = _col(cfg, "section_col", "SECTION")
    category_col = _col(cfg, "category_col", "CATEGORY_NAME_2")
    group_col = _col(cfg, "category_group_col", "CATEGORY_NAME")

    meta_row = (scan_result.get("meta") or [{}])[0]
    as_at = _date(meta_row, "store_latest")
    last_updated = _text(meta_row, "last_updated")

    all_store_rows = scan_result.get("store") or []
    if not as_at and all_store_rows:
        as_at = max(_date(row, "tran_date") for row in all_store_rows)
    today_store_rows = [row for row in all_store_rows if _date(row, "tran_date") == as_at]

    dow_name = _text(today_store_rows[0], "dow_name") if today_store_rows else ""
    week_of_month = int(_num(today_store_rows[0], "week_of_month") or 0) if today_store_rows else 0

    scale_info = measure_scale(today_store_rows, scan_result.get("department") or [],
                               store_col=store_col)
    scale = float(scale_info["scale"])
    # Without a verified scale the below-store figures cannot be placed on the
    # reporting scale at all, so they are withheld rather than shown wrong.
    grain_sales_known = scale_info["factor"] is not None

    stores = []
    for row in sorted(today_store_rows, key=lambda r: _text(r, store_col)):
        stores.append({"store": _text(row, store_col), **_store_bundle(row, scale)})
    store_names = [store["store"] for store in stores]

    # ---- whole business, and its trend ------------------------------------
    trend = []
    for row in sorted(scan_result.get("sparkline") or [], key=lambda r: _date(r, "tran_date")):
        sales = _measure(_num(row, "actual_sales"), _mul(_num(row, "sales_p20"), scale),
                         _mul(_num(row, "sales_p50"), scale), _mul(_num(row, "sales_p80"), scale))
        bills = _measure(_num(row, "actual_bills"), _num(row, "bills_p20"),
                         _num(row, "bills_p50"), _num(row, "bills_p80"))
        margin = _measure(_num(row, "margin_actual"), _num(row, "margin_p20"),
                          _num(row, "margin_p50"), _num(row, "margin_p80"))
        entry = {"date": _date(row, "tran_date"), **_bundle(sales, bills, margin)}
        entry["profit"] = _num(row, "profit_actual")
        trend.append(entry)

    today = trend[-1] if trend else {}
    whole: dict = {}
    if today:
        whole = {key: today[key] for key in ("net_sales", "bills", "basket_value", "margin")}
        whole["sample_days"] = max((s["sample_days"] for s in stores), default=0)
        whole["margin_sample_days"] = max((s["margin_sample_days"] for s in stores), default=0)
        sales_actual = whole["net_sales"]["actual"]
        profit = today.get("profit")
        whole["cost"] = ((sales_actual - profit)
                         if (sales_actual is not None and profit is not None) else None)

    # ---- per-store trend --------------------------------------------------
    store_trend: dict[str, list[dict]] = {name: [] for name in store_names}
    for row in sorted(all_store_rows, key=lambda r: (_date(r, "tran_date"), _text(r, store_col))):
        name = _text(row, store_col)
        if name not in store_trend:
            continue
        store_trend[name].append({"date": _date(row, "tran_date"), **_store_bundle(row, scale)})

    # ---- the three grains -------------------------------------------------
    def _grain(key: str, name_col: str, parent_col: str | None) -> list[dict]:
        buckets: dict[tuple, list[dict]] = {}
        for row in scan_result.get(key) or []:
            name = _text(row, name_col)
            parent = _text(row, parent_col) if parent_col else ""
            buckets.setdefault((name, parent), []).append(row)
        out = []
        for (name, parent), rows in buckets.items():
            totals = _rollup(rows)
            if not totals["live_rows"]:
                out.append({"name": name, "parent": parent, "silent": True,
                            "silent_groups": totals["silent_rows"],
                            "silent_benchmark": totals["silent_benchmark"] * scale,
                            "by_store": {}, **_blank_bundle()})
                continue
            entry = {"name": name, "parent": parent, "silent": False,
                     **_from_rollup(totals, scale)}
            by_store = {}
            for store in store_names:
                store_totals = _rollup([r for r in rows if _text(r, store_col) == store])
                if store_totals["live_rows"]:
                    by_store[store] = _from_rollup(store_totals, scale)
            entry["by_store"] = by_store
            if not grain_sales_known:
                # No verified scale: Net Sales, its band, Basket Value and the
                # Margin derived from cost are all unplaceable at this grain.
                for measure in ("net_sales", "basket_value", "margin"):
                    entry[measure] = _measure(None, None, None, None)
                for bundle in by_store.values():
                    for measure in ("net_sales", "basket_value", "margin"):
                        bundle[measure] = _measure(None, None, None, None)
            out.append(entry)
        out.sort(key=lambda e: -((e.get("net_sales") or {}).get("actual") or 0.0))
        return out

    departments = _grain("department", dept_col, None)
    sections = _grain("section", section_col, dept_col)
    categories = _grain("category", category_col, section_col)

    # ---- the groups that recorded nothing ---------------------------------
    silent_groups = []
    silent_total = 0
    silent_benchmark = 0.0
    for entry in categories:
        if entry.get("silent") or not entry.get("silent_groups"):
            continue
        silent_total += entry["silent_groups"]
        silent_benchmark += entry["silent_benchmark"]
        silent_groups.append({
            "name": entry["name"], "parent": entry["parent"],
            "silent": entry["silent_groups"],
            "total": entry["silent_groups"] + entry["group_count"],
            "usually_take": entry["silent_benchmark"],
            "taken_by_rest": entry["net_sales"]["actual"],
        })
    silent_groups.sort(key=lambda g: -(g["usually_take"] or 0.0))

    # ---- reconciliation ---------------------------------------------------
    whole_sales = (whole.get("net_sales") or {}).get("actual") if whole else None
    whole_bills = (whole.get("bills") or {}).get("actual") if whole else None
    store_sales = sum(s["net_sales"]["actual"] or 0.0 for s in stores)
    store_bills = sum(s["bills"]["actual"] or 0.0 for s in stores)
    store_cost = sum(s.get("cost") or 0.0 for s in stores)

    def _sums_to_whole(rows: list[dict]) -> bool:
        if whole_sales is None or not grain_sales_known:
            return False
        total = sum((entry.get("net_sales") or {}).get("actual") or 0.0 for entry in rows)
        return abs(total - whole_sales) < max(1.0, abs(whole_sales) * 1e-6)

    checks = {
        "scale_verified": grain_sales_known,
        "store_sales_reconciles_to_whole": (
            whole_sales is not None and abs(store_sales - whole_sales) < 1.0),
        "store_bills_reconciles_to_whole": store_bills == (whole_bills or 0),
        "store_cost_reconciles_to_whole": bool(
            whole.get("cost") is not None and abs(store_cost - whole["cost"]) < 1.0),
        "department_sales_reconciles_to_whole": _sums_to_whole(departments),
        "section_sales_reconciles_to_whole": _sums_to_whole(sections),
        "category_sales_reconciles_to_whole": _sums_to_whole(categories),
        "trend_has_today": bool(trend) and trend[-1]["date"] == as_at,
    }

    return {
        "report_id": str(cfg.get("report_id") or "daily_sales"),
        "report_name": str(cfg.get("report_name") or "Daily Sales"),
        "currency": currency,
        "as_at": as_at,
        "as_at_label": day_label(as_at, dow_name),
        "last_updated": last_updated,
        "dow_name": dow_name,
        "week_of_month": week_of_month,
        "scale": scale_info,
        "stores": stores,
        "store_names": store_names,
        "whole": whole,
        "trend": trend,
        "store_trend": store_trend,
        "departments": departments,
        "sections": sections,
        "categories": categories,
        "silent_groups": silent_groups,
        "silent_group_total": silent_total,
        "silent_group_benchmark": silent_benchmark,
        "grain_sales_known": grain_sales_known,
        "checks": checks,
        "column_labels": {"category": category_col, "group": group_col},
    }


def dump_json(value: object) -> str:
    import json
    return json.dumps(value, indent=2, default=str)
