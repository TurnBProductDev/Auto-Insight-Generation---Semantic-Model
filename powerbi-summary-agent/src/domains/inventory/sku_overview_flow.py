"""Generic, reconciled SKU Overview scan -> stats -> outputs flow.

SB Mart's "SKU Overview - Mobile View Included" report is a single-snapshot
Loc-SKU stock position - the same shape as Ageing, and sharing most of its
`RECOMMENDED_ACTION` vocabulary with the separate Inventory Management report
(a different Power BI dataset over what looks like the same underlying stock
data). Deliberately not the `stock_health.py` machinery: that module is built
against Inventory Management's own exact schema and its Inventory Health
Score, archive and Opportunity Loss scoping rules, none of which are verified
against THIS dataset. Follows Ageing's shape instead - config-driven semantic
references, one snapshot, no manufactured trend - because that is the pattern
already proven against a single-snapshot Loc-SKU stock table.

Field mapping lives in `sku_overview_mapping` (config), never guessed: the
exact business meaning of "burnout" or "excess" is policy, not something a
generic scan can infer.
"""

from __future__ import annotations

import json
import re
from typing import Callable

Execute = Callable[[str], list[dict]]

#: Observed live (2026-08-23): 21,609 of 139,200 rows carry EXPECTED_BURNOUT_DAYS
#: exactly 1000, plus 3,905 rows above it - the same "no reliable velocity
#: signal" sentinel convention Inventory Management's BR-11 documents for its
#: own Burn-Out Days measure. Treated as unmeasurable, never as the safest SKU
#: in the business.
BURNOUT_SENTINEL_FLOOR = 1000.0

#: Per the rulebook (sku-insights-rules.md): every figure on this report scopes
#: to the five shops. The two warehouses hold stock but do not sell it, so
#: they are never added into a stock, sales or shelf total - they appear only
#: where a warehouse is the fix for a shop problem (Rule 5). This is the
#: canonical list; `sku_overview_insights.py` mirrors it rather than importing
#: it, so the two-module dependency runs one way (insights depends on flow's
#: scan shape, not the reverse).
SHOPS = ("ST1", "ST2", "ST3", "ST4", "ST5")


def _shops_literal() -> str:
    return "{" + ", ".join(f'"{s}"' for s in SHOPS) + "}"


def _required(cfg: dict, name: str) -> str:
    value = str((cfg.get("sku_overview_mapping") or {}).get(name) or "").strip()
    if not value:
        raise ValueError(f"sku_overview_mapping.{name} is required")
    return value


def _expression(reference: str) -> str:
    return reference if reference.startswith("[") or "(" in reference else f"SUM({reference})"


def _alias(reference: str) -> str:
    match = re.search(r"\[([^\]]+)\]\s*$", reference)
    return match.group(1) if match else reference


def build_queries(cfg: dict, *, seg_a_only: bool = False) -> dict[str, str]:
    mapping = cfg.get("sku_overview_mapping") or {}
    stock_value = _expression(_required(cfg, "stock_value"))
    excess_value = _expression(_required(cfg, "excess_value"))
    pending_value = _expression(_required(cfg, "pending_value"))
    opp_loss = _expression(_required(cfg, "opp_loss"))
    burnout_days = _required(cfg, "burnout_days")
    recommended_action = _required(cfg, "recommended_action")
    snapshot = _required(cfg, "snapshot")
    sku = _required(cfg, "sku")
    sku_desc = _required(cfg, "sku_description")
    location = _required(cfg, "location")
    dimensions = mapping.get("dimensions") or {}

    table = mapping.get("table", "")
    shops = _shops_literal()
    # "Best sellers only" (the reference's second view) keeps only the
    # model's own top sales band, SEG_A - every figure worked out again over
    # just those products, never a subset carved out of the all-products totals.
    scope = f"{location} IN {shops}"
    if seg_a_only:
        scope += f' && \'{table}\'[SKUSEGMENT] = "SEG_A"'
    queries = {
        # As-at and cardinality are read from the WHOLE table, deliberately:
        # they describe when the snapshot was taken, not what it covers, and
        # a shop-only filter could not change either.
        "snapshot": f"""EVALUATE ROW(
  "as_at", MAX({snapshot}),
  "snapshot_cardinality", DISTINCTCOUNT({snapshot}),
  "rows", CALCULATE(COUNTROWS('{table}'), {scope}),
  "skus", CALCULATE(DISTINCTCOUNT({sku}), {scope}),
  "locations", CALCULATE(DISTINCTCOUNT({location}), {scope}),
  "total_stock_value", CALCULATE({stock_value}, {scope}),
  "total_excess_value", CALCULATE({excess_value}, {scope}),
  "total_pending_value", CALCULATE({pending_value}, {scope}),
  "total_opp_loss", CALCULATE({opp_loss}, {scope})
)""",
        "states": f"""EVALUATE
CALCULATETABLE(
  SUMMARIZECOLUMNS(
    {recommended_action},
    "rows", COUNTROWS('{table}'),
    "stock_value", {stock_value},
    "excess_value", {excess_value},
    "pending_value", {pending_value},
    "opp_loss", {opp_loss}
  ),
  {scope}
)""",
    }
    limit = int(cfg.get("sku_overview_top_members", 50) or 50)
    for role, reference in dimensions.items():
        queries[f"dimension__{role}"] = f"""EVALUATE
TOPN(
  {limit},
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      {reference},
      "stock_value", {stock_value},
      "excess_value", {excess_value},
      "opp_loss", {opp_loss}
    ),
    {scope}
  ),
  {excess_value}, DESC
)"""

    deep_limit = int(cfg.get("sku_overview_deep_dive_members", 8) or 8)
    # EXPECTED_BURNOUT_DAYS is a per Loc-SKU figure, not per SKU: the same SKU
    # can carry a different burnout reading at each location. Grouping by SKU
    # alone left the column ungrouped and unaggregated, which Power BI
    # rejected outright ("a single value ... cannot be determined"). Location
    # joins the group-by so every row already has exactly one value, and
    # MIN() is only there to satisfy DAX's aggregation requirement.
    queries["deep__lowest_burnout"] = f"""EVALUATE
TOPN({deep_limit},
  FILTER(
    CALCULATETABLE(
      SUMMARIZECOLUMNS(
        {sku}, {sku_desc}, {location},
        "burnout", MIN({burnout_days}),
        "value", {stock_value}
      ),
      {scope}
    ),
    [burnout] > 0 && [burnout] < {BURNOUT_SENTINEL_FLOOR:.0f} && [value] > 0
  ),
  [burnout], ASC, {sku}, ASC)"""
    queries["deep__highest_opp_loss"] = f"""EVALUATE
TOPN({deep_limit},
  FILTER(
    CALCULATETABLE(SUMMARIZECOLUMNS({sku}, {sku_desc}, "value", {opp_loss}), {scope}),
    [value] > 0),
  [value], DESC, {sku}, ASC)"""
    queries["deep__highest_excess"] = f"""EVALUATE
TOPN({deep_limit},
  FILTER(
    CALCULATETABLE(SUMMARIZECOLUMNS({sku}, {sku_desc}, "value", {excess_value}), {scope}),
    [value] > 0),
  [value], DESC, {sku}, ASC)"""
    return queries


def scan_overview(execute: Execute, cfg: dict, *, seg_a_only: bool = False,
                  log: Callable[[str], None] | None = None) -> dict:
    """Just the snapshot + state totals - the minimum needed to recompute the
    Overview layer for a second scope (the "Best sellers only" view), without
    paying for the full dimension/deep-dive scan a second time."""
    queries = build_queries(cfg, seg_a_only=seg_a_only)
    out: dict = {"snapshot": [], "states": []}
    for name in ("snapshot", "states"):
        if log:
            log(f"  {name} ({'SEG_A' if seg_a_only else 'all'})")
        out[name] = execute(queries[name])
    return out


def scan(execute: Execute, cfg: dict, *, log: Callable[[str], None] | None = None) -> dict:
    queries = build_queries(cfg)
    result: dict = {"queries": {}, "states": [], "dimensions": {}, "deep_dives": {},
                    "currency": cfg.get("sku_overview_currency", "")}
    for name, dax in queries.items():
        if log:
            log(f"  {name}")
        rows = execute(dax)
        result["queries"][name] = dax
        if name == "states":
            result["states"] = rows
        elif name.startswith("dimension__"):
            result["dimensions"][name.split("__", 1)[1]] = rows
        elif name.startswith("deep__"):
            result["deep_dives"][name.split("__", 1)[1]] = rows
        else:
            result[name] = rows
    return result


def _clean_key(key: object) -> str:
    return str(key).strip("[]").split("[")[-1].strip("]").lower()


def _read(row: dict, name: str):
    wanted = str(name or "").lower()
    for key, value in (row or {}).items():
        if _clean_key(key) == wanted:
            return value
    return None


def _number(row: dict, name: str) -> float:
    value = _read(row, name)
    return float(value or 0.0)


def build(scan_result: dict, cfg: dict) -> dict:
    """The reconciled report model. Every figure derived once, here, so the
    stat detector, narrative and dashboard cannot disagree about a total."""
    mapping = cfg.get("sku_overview_mapping") or {}
    snap = (scan_result.get("snapshot") or [{}])[0]
    currency = str(cfg.get("sku_overview_currency") or scan_result.get("currency") or "")
    total_stock = _number(snap, "total_stock_value")
    total_excess = _number(snap, "total_excess_value")
    total_pending = _number(snap, "total_pending_value")
    total_opp_loss = _number(snap, "total_opp_loss")
    as_at = str(_read(snap, "as_at") or "").split("T")[0]

    action_alias = _alias(_required(cfg, "recommended_action"))
    states = []
    state_rows_sum = 0
    for row in scan_result.get("states") or []:
        rows = int(_number(row, "rows"))
        state_rows_sum += rows
        states.append({
            "action": str(_read(row, action_alias) or "NA"),
            "rows": rows,
            "stock_value": _number(row, "stock_value"),
            "excess_value": _number(row, "excess_value"),
            "pending_value": _number(row, "pending_value"),
            "opp_loss": _number(row, "opp_loss"),
        })
    states.sort(key=lambda s: -s["stock_value"])

    total_rows = int(_number(snap, "rows"))
    checks = {
        "states_cover_every_row": state_rows_sum == total_rows and total_rows > 0,
        "excess_within_stock_value": total_excess <= total_stock + 0.01,
    }

    dimensions = {}
    for role, rows in (scan_result.get("dimensions") or {}).items():
        reference = str((mapping.get("dimensions") or {}).get(role) or "")
        alias = _alias(reference)
        dimensions[role] = [
            {"name": str(_read(r, alias) or "Unknown"),
             "stock_value": _number(r, "stock_value"),
             "excess_value": _number(r, "excess_value"),
             "opp_loss": _number(r, "opp_loss")}
            for r in rows
        ]

    sku_alias = _alias(_required(cfg, "sku"))
    desc_alias = _alias(_required(cfg, "sku_description"))
    location_alias = _alias(_required(cfg, "location"))
    deep_dives = []
    # unit: "money" formats the value with the currency; "days" prints it as a
    # day count. Burnout days is a per Loc-SKU figure - two rows for the same
    # SKU at different locations are two real facts, not a duplicate, so the
    # location rides along to say which is which.
    labels = {
        "lowest_burnout": ("Fastest-emptying SKUs", "burnout", "days"),
        "highest_opp_loss": ("Largest Opportunity Loss SKUs", "value", "money"),
        "highest_excess": ("Largest Excess Stock SKUs", "value", "money"),
    }
    for key, rows in (scan_result.get("deep_dives") or {}).items():
        title, metric_key, unit = labels.get(key, (key.replace("_", " ").title(), "value", "money"))
        deep_dives.append({
            "analysis": key, "title": title, "unit": unit,
            "rows": [{"sku": str(_read(r, sku_alias) or ""),
                      "description": str(_read(r, desc_alias) or ""),
                      "location": str(_read(r, location_alias) or ""),
                      "value": _number(r, metric_key)} for r in rows],
        })

    header = {
        "total_stock_value": total_stock,
        "total_excess_value": total_excess,
        "excess_share_pct": (total_excess / total_stock * 100.0) if total_stock else None,
        "total_pending_value": total_pending,
        "total_opp_loss": total_opp_loss,
        "skus": _number(snap, "skus"),
        "locations": _number(snap, "locations"),
        "rows": total_rows,
    }

    model = {
        "report_id": str(cfg.get("report_id") or "sku_overview"),
        "report_name": str(cfg.get("report_name") or "SKU Overview"),
        "as_at": as_at,
        "period_label": f"as at {as_at}" if as_at else "",
        "currency": currency,
        "header": header,
        "states": states,
        "dimensions": dimensions,
        "deep_dives": deep_dives,
        "checks": checks,
        "caveats": [
            "This is a single stock position; it supports distribution and "
            "outlier findings, not YoY or trend claims.",
            f"{int(header['skus']):,} SKUs across {int(header['locations']):,} "
            f"locations, {total_rows:,} Loc-SKU rows.",
        ],
    }

    from . import sku_overview_stats
    model["stat_check"] = sku_overview_stats.analyze(model)
    model["stat_signals"] = sku_overview_stats.detect(model)
    return model


def _money(value, currency: str) -> str:
    number = float(value or 0.0)
    if abs(number) >= 1_000_000:
        return f"{currency} {number / 1_000_000:.2f}M".strip()
    if abs(number) >= 1_000:
        return f"{currency} {number / 1_000:.0f}K".strip()
    return f"{currency} {number:,.0f}".strip()


def findings_payload(model: dict) -> dict:
    return {
        "report_id": model.get("report_id"),
        "period_label": model.get("period_label"),
        "stat_check": model.get("stat_check"),
        "findings": model.get("stat_signals") or [],
        "investigations": model.get("investigation") or [],
        "checks": model.get("checks") or {},
    }


def summary_markdown(model: dict) -> str:
    currency = str(model.get("currency") or "")
    h = model.get("header") or {}
    lines = [f"# {model.get('report_name')}", "", str(model.get("period_label") or ""), "",
             "## Executive summary", ""]
    urgent = next((s for s in model.get("states") or []
                  if s.get("action") == "STOCK OUT - PLACE ORDER"), None)
    if urgent and urgent.get("rows"):
        lines.append(f"- {int(urgent['rows']):,} Loc-SKUs are in STOCK OUT - PLACE ORDER "
                     f"and need attention first.")
    lines += [f"- Total stock value: {_money(h.get('total_stock_value'), currency)}.",
              f"- Excess Stock: {_money(h.get('total_excess_value'), currency)} "
              + (f"({h['excess_share_pct']:.1f}% of stock value)."
                 if isinstance(h.get('excess_share_pct'), (int, float)) else "."),
              f"- Opportunity Loss: {_money(h.get('total_opp_loss'), currency)} (estimate)."]
    lines += ["", "## Stat check", ""]
    for signal in (model.get("stat_signals") or [])[:6]:
        lines.append(f"- **{signal.get('severity', 'info').title()}** — {signal.get('description')}")
    all_ok = bool(model.get("checks")) and all((model.get("checks") or {}).values())
    lines += ["", "## Control totals", "",
              f"- {int(h.get('rows') or 0):,} Loc-SKU rows across "
              f"{int(h.get('skus') or 0):,} SKUs and {int(h.get('locations') or 0):,} locations.",
              "", ("All published values passed the report reconciliation gate."
                    if all_ok else "The report failed its reconciliation gate; figures are diagnostic only.")]
    return "\n".join(lines) + "\n"


def _insights_markdown(model: dict) -> list[str]:
    """The eight rulebook insights (sku-insights-rules.md), scoped to the
    five shops. Absent entirely when the run had no live token to compute
    them (e.g. a --from-scan rebuild) - `model.get("insights")` is None, not
    an empty dict, and that distinction matters: an empty section would read
    as "nothing found" rather than "not computed this run"."""
    insights = model.get("insights")
    if not insights:
        return []
    currency = str(model.get("currency") or "")
    rules = insights.get("rules") or {}
    errors = insights.get("errors") or {}
    lines = ["## What is selling", ""]

    top = rules.get("top_performers") or []
    if top:
        lines.append("### Top-performing SKUs per department (last month)")
        lines.append("")
        by_dept: dict[str, list] = {}
        for row in top:
            by_dept.setdefault(row["department"], []).append(row)
        for dept, rows in by_dept.items():
            lines.append(f"**{dept}**")
            for row in sorted(rows, key=lambda r: r["rank"]):
                lines.append(f"  {row['rank']}. {row['description']} "
                            f"({row['category']}): {_money(row['sales_1m'], currency)}")
            lines.append("")

    best_day = rules.get("best_day_yesterday") or []
    if best_day:
        lines.append("### Best sales day was yesterday")
        lines.append("")
        lines.append("Products whose single strongest day in the tracked window was "
                     "yesterday - not the same as yesterday's biggest sellers; a "
                     "high-volume staple usually peaked on an earlier bulk-buy day, "
                     "so this list surfaces smaller, less consistent sellers instead.")
        lines.append("")
        for row in best_day[:10]:
            lines.append(f"- {row['sku']} at {row['location']}: "
                        f"{_money(row['sales_value'], currency)}")
        lines.append("")

    at_floor = rules.get("at_price_floor") or []
    if at_floor:
        lines.append("### Currently at the 90-day price floor")
        lines.append("")
        lines.append("Marked down to the cheapest point in 90 days. This states that a "
                     "markdown is active, not that it caused any change in sales.")
        lines.append("")
        for row in at_floor[:10]:
            lines.append(f"- {row['description']} at {row['location']}: priced "
                        f"{_money(row['price'], currency)}, range "
                        f"{_money(row['min_price_90d'], currency)}-"
                        f"{_money(row['max_price_90d'], currency)}, "
                        f"{_money(row['sales_3m'], currency)} sold in 3 months.")
        lines.append("")

    lines += ["## What needs action", ""]

    stockouts = rules.get("segment_a_stockouts") or {}
    if stockouts.get("count"):
        lines.append("### Segment A SKUs out of stock")
        lines.append("")
        lines.append(f"{stockouts['count']:,} Segment A Loc-SKUs are out of stock, an "
                     f"estimated {_money(stockouts.get('opp_loss_total'), currency)} of "
                     f"Opportunity Loss (rows the model could not estimate are excluded, "
                     f"not counted as zero).")
        for row in stockouts.get("top") or []:
            opp = (f", {_money(row['opp_loss'], currency)} loss estimated"
                  if row.get("opp_loss") is not None else "")
            lines.append(f"  - {row['description']} at {row['location']}: "
                        f"{_money(row['sales_3m'], currency)} sold in 3 months{opp}")
        lines.append("")

    verge = rules.get("verge_stockout_in_warehouse") or []
    if verge:
        lines.append("### On the verge of stockout, fixable from a warehouse today")
        lines.append("")
        for row in verge[:10]:
            lines.append(f"- {row['description']} at {row['location']}: "
                        f"{_money(row['sales_3m'], currency)} sold in 3 months, "
                        f"{row['current_stock']:,.0f} units on the shelf.")
        lines.append("")

    non_moving = rules.get("non_moving_pending_order") or []
    if non_moving:
        lines.append("### Non-moving, with stock already on order")
        lines.append("")
        for row in non_moving[:15]:
            lines.append(f"- {row['description']} at {row['location']}: "
                        f"{_money(row['pending_value'], currency)} on order, "
                        f"{row['days_no_sale']:.0f} days since the last sale.")
        lines.append("")

    overstock = rules.get("overstock_pending_order") or []
    if overstock:
        lines.append("### Overstocked, with more already on order")
        lines.append("")
        for row in overstock[:10]:
            lines.append(f"- {row['description']} at {row['location']}: "
                        f"{_money(row['excess_value'], currency)} Excess Stock already "
                        f"held, {_money(row['pending_value'], currency)} more on order.")
        lines.append("")

    rank_movers = rules.get("rank_movers") or {}
    if rank_movers and not rank_movers.get("available", True):
        lines += ["### Rank promotion / demotion", "", "**Pending.** " + rank_movers.get("reason", ""),
                 "", rank_movers.get("action", ""), ""]

    if errors:
        lines += ["### Rules that could not run this time", ""]
        for name, message in errors.items():
            lines.append(f"- {name}: {message}")
        lines.append("")

    return lines


def insight_markdown(model: dict) -> str:
    currency = str(model.get("currency") or "")
    lines = [f"# {model.get('report_name')} — Investigative insights", "",
             str(model.get("period_label") or ""), "", "## Findings", ""]
    signals = model.get("stat_signals") or []
    if signals:
        for signal in signals[:8]:
            lines.append(f"- {signal.get('description')}")
    else:
        lines.append("- No material exception crossed the configured SKU Overview thresholds.")
    lines.append("")
    lines += _insights_markdown(model)
    lines += ["## Deeper investigation", ""]
    for dive in model.get("deep_dives") or []:
        lines.append(f"### {dive.get('title')}")
        lines.append("")
        rows = dive.get("rows") or []
        unit = dive.get("unit") or "money"
        if not rows:
            lines.append("No exposure was returned for this cut.")
        else:
            for row in rows:
                label = row.get("description") or row.get("sku") or ""
                where = f" at {row['location']}" if row.get("location") else ""
                value = (f"{row.get('value'):.0f} day"
                        + ("s" if row.get("value") != 1 else "")
                        if unit == "days" else _money(row.get("value"), currency))
                lines.append(f"- {row.get('sku')} - {label}{where}: {value}")
        lines.append("")

    investigation = model.get("investigation") or []
    if investigation:
        lines += ["## Why here", ""]
        for entry in investigation:
            lines.append(f"### {entry.get('segment')} ({entry.get('dimension')})")
            lines.append("")
            lines.append(str(entry.get("narrative") or ""))
            lines.append("")
            for drill in entry.get("drills") or []:
                lines.append(f"- By {drill.get('role')}:")
                for row in drill.get("rows") or []:
                    lines.append(f"  - {row.get('name')}: {_money(row.get('value'), currency)}")
            lines.append("")

    lines += ["## Interpretation limits", "",
              "- This is a single stock position, so it supports distribution and "
              "concentration findings, not YoY or trend claims.",
              "- Opportunity Loss is an estimate derived from average daily sales, "
              "not confirmed lost revenue."]
    return "\n".join(lines) + "\n"


def dump_json(value: object) -> str:
    return json.dumps(value, indent=2, default=str)
