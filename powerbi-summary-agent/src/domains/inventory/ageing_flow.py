"""Generic, reconciled Ageing scan -> stats -> investigation -> outputs flow.

The flow is deliberately report-specific but model-agnostic: semantic object
references live in configuration, while every calculation here uses the same
exposure expression.  That prevents a convenient but incompatible model
measure from contaminating the denominator.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from .reports import ageing

Execute = Callable[[str], list[dict]]


def _required(cfg: dict, name: str) -> str:
    value = str((cfg.get("ageing_mapping") or {}).get(name) or "").strip()
    if not value:
        raise ValueError(f"ageing_mapping.{name} is required")
    return value


def _expression(reference: str) -> str:
    return reference if reference.startswith("[") or "(" in reference else f"SUM({reference})"


def _alias(reference: str) -> str:
    match = re.search(r"\[([^\]]+)\]\s*$", reference)
    return match.group(1) if match else reference


def _calc(expression: str, filter_expression: str) -> str:
    # KEEPFILTERS is essential when the query is already grouped by the age
    # band: a plain CALCULATE filter on that same column would replace the row's
    # band and repeat the whole aged total on every row.
    return f"CALCULATE({expression}, KEEPFILTERS({filter_expression}))"


def _top_query(dimension: str, exposure: str, aged: str, high_risk: str,
               *, rows: int = 100, quantity: str = "", aged_qty: str = "") -> str:
    # Quantity rides along on the same scan rather than costing a second query.
    # It is what makes a member comparable against an earlier position when the
    # valuation basis has moved underneath the value column (see
    # `ageing_history.basis_check`), so leaving it out would cost the whole
    # comparison for no saving.
    extra = ""
    if quantity:
        extra += f',\n      "qty", {quantity}'
    if aged_qty:
        extra += f',\n      "aged_qty", {aged_qty}'
    return f"""EVALUATE
TOPN(
  {int(rows)},
  FILTER(
    SUMMARIZECOLUMNS(
      {dimension},
      "value", {exposure},
      "aged", {aged},
      "high_risk", {high_risk}{extra}
    ),
    [value] <> 0
  ),
  [aged], DESC,
  {dimension}, ASC
)"""


def build_queries(cfg: dict) -> dict[str, str]:
    mapping = cfg.get("ageing_mapping") or {}
    exposure = _expression(_required(cfg, "exposure"))
    bucket = _required(cfg, "bucket")
    snapshot = _required(cfg, "snapshot")
    non_moving = _required(cfg, "non_moving")
    sku = _required(cfg, "sku")
    location = _required(cfg, "location")
    aged_filter = str(cfg.get("ageing_aged_filter") or "").strip()
    high_filter = str(cfg.get("ageing_high_risk_filter") or "").strip()
    oldest_filter = str(cfg.get("ageing_oldest_filter") or high_filter).strip()
    if not aged_filter or not high_filter:
        raise ValueError("ageing_aged_filter and ageing_high_risk_filter are required")
    aged = _calc(exposure, aged_filter)
    high = _calc(exposure, high_filter)
    oldest = _calc(exposure, oldest_filter)
    dimensions = mapping.get("dimensions") or {}
    quantity = _expression(str(cfg.get("ageing_quantity") or "").strip()) \
        if cfg.get("ageing_quantity") else ""
    aged_qty = _calc(quantity, aged_filter) if quantity else ""

    validation_share = str(cfg.get("ageing_validation_share_expression") or "").strip()
    validation_numerator = str(cfg.get("ageing_validation_numerator_expression") or "").strip()
    validation_fields = ""
    if validation_share:
        validation_fields += f',\n  "source_aged_share", {validation_share}'
    if validation_numerator:
        validation_fields += f',\n  "source_aged_numerator", {validation_numerator}'
    queries = {
        "snapshot": f"""EVALUATE ROW(
  "as_at", MAX({snapshot}),
  "snapshot_cardinality", DISTINCTCOUNT({snapshot}),
  "total_value", {exposure},
  "aged_value", {aged},
  "high_risk_value", {high},
  "oldest_value", {oldest},
  "skus", DISTINCTCOUNT({sku}),
  "aged_skus", CALCULATE(DISTINCTCOUNT({sku}), KEEPFILTERS({aged_filter})),
  "locations", DISTINCTCOUNT({location}){f',{chr(10)}  "total_qty", {quantity},{chr(10)}  "aged_qty", {aged_qty}' if quantity else ""}{validation_fields}
)""",
        "bands": f"""EVALUATE
SUMMARIZECOLUMNS(
  {bucket},
  "value", {exposure},
  "aged", {aged},
  "skus", DISTINCTCOUNT({sku}){f',{chr(10)}  "qty", {quantity}' if quantity else ""}
)""",
        "risk_split": f"""EVALUATE
SUMMARIZECOLUMNS(
  {non_moving},
  "value", {exposure},
  "aged", {aged}
)""",
    }
    limit = int(cfg.get("ageing_top_members", 50) or 50)
    for role, reference in dimensions.items():
        queries[f"dimension__{role}"] = _top_query(
            str(reference), exposure, aged, high, rows=limit,
            quantity=quantity, aged_qty=aged_qty)

    queries.update(_history_queries(cfg))
    queries.update(_outlook_queries(cfg, exposure, quantity, aged_filter))

    deep_limit = int(cfg.get("ageing_deep_dive_members", 5) or 5)
    queries["deep__oldest_items"] = f"""EVALUATE
TOPN({deep_limit},
  FILTER(SUMMARIZECOLUMNS({sku}, "value", {oldest}), [value] > 0),
  [value], DESC, {sku}, ASC)
ORDER BY [value] DESC"""
    queries["deep__aged_non_moving_items"] = f"""EVALUATE
TOPN({deep_limit},
  FILTER(SUMMARIZECOLUMNS(
    {sku},
    "value", CALCULATE({exposure}, {aged_filter}, {non_moving} = "YES")
  ), [value] > 0),
  [value], DESC, {sku}, ASC)
ORDER BY [value] DESC"""
    return queries


# --- The history lane ---------------------------------------------------------
# Every reference below is configuration, never a name in code, so a second
# client's history table can differ in every particular. The whole block is
# optional: a config with no ``ageing_history`` produces no queries and the
# report says plainly that no earlier position was available.


def _history_queries(cfg: dict) -> dict[str, str]:
    history = cfg.get("ageing_history") or {}
    bucket = str(history.get("bucket") or "").strip()
    exposure = str(history.get("exposure") or "").strip()
    if not bucket or not exposure:
        return {}
    exposure = _expression(exposure)
    quantity = _expression(str(history.get("quantity") or "").strip()) \
        if history.get("quantity") else ""
    snapshot = str(history.get("snapshot") or "").strip()
    sku = str(history.get("sku") or "").strip()
    aged_filter = str(history.get("aged_filter") or "").strip()
    aged = _calc(exposure, aged_filter) if aged_filter else ""
    aged_qty = _calc(quantity, aged_filter) if quantity and aged_filter else ""

    header_fields = [f'"total_value", {exposure}']
    if snapshot:
        header_fields.insert(0, f'"as_at", MAX({snapshot})')
        header_fields.append(f'"snapshot_cardinality", DISTINCTCOUNT({snapshot})')
    if quantity:
        header_fields.append(f'"total_qty", {quantity}')
    if aged:
        header_fields.append(f'"aged_value", {aged}')
    if aged_qty:
        header_fields.append(f'"aged_qty", {aged_qty}')
    if sku:
        header_fields.append(f'"skus", DISTINCTCOUNT({sku})')

    band_fields = [f'"value", {exposure}']
    if quantity:
        band_fields.append(f'"qty", {quantity}')
    if sku:
        band_fields.append(f'"skus", DISTINCTCOUNT({sku})')

    joined_header = ",\n  ".join(header_fields)
    joined_bands = ",\n  ".join(band_fields)
    queries = {
        "history_snapshot": f"EVALUATE ROW(\n  {joined_header}\n)",
        "history_bands": (f"EVALUATE\nSUMMARIZECOLUMNS(\n  {bucket},\n  "
                          f"{joined_bands}\n)"),
    }

    # Grouped on the history table's OWN member columns, not through the shared
    # lookup. On the live model 1.5% of history value does not match that lookup,
    # and losing it from one side of a comparison only is the failure mode that
    # still adds up to something and is therefore invisible.
    member_fields = [f'"value", {exposure}']
    if quantity:
        member_fields.append(f'"qty", {quantity}')
    if aged:
        member_fields.append(f'"aged", {aged}')
    if aged_qty:
        member_fields.append(f'"aged_qty", {aged_qty}')
    joined_members = ",\n  ".join(member_fields)
    for role, reference in (history.get("dimensions") or {}).items():
        reference = str(reference or "").strip()
        if not reference:
            continue
        queries[f"history_dimension__{role}"] = (
            f"EVALUATE\nSUMMARIZECOLUMNS(\n  {reference},\n  {joined_members}\n)")
    return queries


# --- Clearance, categories and the stuck lines --------------------------------
# Clearance and the risk table read a second table whose stock value is on a
# different basis from the ageing table's. They are grouped through the SHARED
# lookup on purpose, because that is the only column that filters both facts at
# once; the resulting unmapped row is captured rather than dropped, so the page
# can say how much selling velocity it does not account for.


def _outlook_queries(cfg: dict, exposure: str, quantity: str,
                     aged_filter: str) -> dict[str, str]:
    queries: dict[str, str] = {}
    status = cfg.get("ageing_status") or {}
    velocity = _expression(str(status.get("velocity") or "").strip()) \
        if status.get("velocity") else ""
    shared_division = str(cfg.get("ageing_shared_division") or "").strip()
    category = str(cfg.get("ageing_category") or "").strip()

    if shared_division and velocity and quantity and aged_filter:
        queries["clearance"] = f"""EVALUATE
SUMMARIZECOLUMNS(
  {shared_division},
  "aged_qty", {_calc(quantity, aged_filter)},
  "aged_value", {_calc(exposure, aged_filter)},
  "total_value", {exposure},
  "daily_qty", {velocity}
)"""

    if category and aged_filter:
        # Every carried category, not a top-N: the count of categories over the
        # threshold is one of the report's headline figures, and a truncated
        # scan would understate it without saying so.
        queries["categories"] = f"""EVALUATE
FILTER(
  SUMMARIZECOLUMNS(
    {category},
    "total", {exposure},
    "aged", {_calc(exposure, aged_filter)}
  ),
  [total] > 0
)"""

    risk_score = str(status.get("risk_score") or "").strip()
    status_column = str(status.get("status") or "").strip()
    status_sku = str(status.get("sku") or "").strip()
    status_value = _expression(str(status.get("value") or "").strip()) \
        if status.get("value") else ""
    if risk_score and status_sku and status_value:
        cutoff = float(cfg.get("ageing_risk_score_cutoff", -70.0) or -70.0)
        floor = float(cfg.get("ageing_risk_value_floor", 500.0) or 500.0)
        rows = int(cfg.get("ageing_risk_rows", 10) or 10)
        status_qty = _expression(str(status.get("quantity") or "").strip()) \
            if status.get("quantity") else ""
        group = [status_sku]
        for key in ("location", "category"):
            reference = str(status.get(key) or "").strip()
            if reference:
                group.append(reference)
        if status_column:
            group.append(status_column)
        fields = [f'"risk_score", CALCULATE(MIN({risk_score}))',
                  f'"value", {status_value}']
        if status_qty:
            fields.append(f'"qty", {status_qty}')
        if velocity:
            fields.append(f'"daily_qty", {velocity}')

        wanted = [str(s).strip() for s in (cfg.get("ageing_risk_statuses") or [])
                  if str(s).strip()]
        status_clause = ""
        if wanted and status_column:
            members = ", ".join(f'"{s}"' for s in wanted)
            status_clause = f"\n    && {status_column} IN {{{members}}}"

        joined_group = ",\n      ".join(group)
        joined_fields = ",\n      ".join(fields)
        queries["risk_lines"] = f"""EVALUATE
TOPN(
  {rows},
  FILTER(
    SUMMARIZECOLUMNS(
      {joined_group},
      {joined_fields}
    ),
    [risk_score] <= {cutoff}
    && [value] >= {floor}{status_clause}
  ),
  [value], DESC
)
ORDER BY [value] DESC"""

        table = str(status.get("table") or "").strip()
        if table:
            queries["risk_total"] = f"""EVALUATE ROW(
  "risk_lines", CALCULATE(COUNTROWS({table}), KEEPFILTERS({risk_score} <= {cutoff})),
  "all_lines", COUNTROWS({table})
)"""
    return queries

def scan(execute: Execute, cfg: dict, *, log: Callable[[str], None] | None = None) -> dict:
    queries = build_queries(cfg)
    mapping = cfg.get("ageing_mapping") or {}
    result: dict = {"queries": {}, "dimensions": {}, "deep_dives": {},
                    "history_dimensions": {},
                    "currency": cfg.get("ageing_currency", "")}
    for name, dax in queries.items():
        if log:
            log(f"  {name}")
        rows = execute(dax)
        result["queries"][name] = dax
        if name.startswith("dimension__"):
            result["dimensions"][name.split("__", 1)[1]] = rows
        elif name.startswith("history_dimension__"):
            role = name.split("__", 1)[1]
            reference = str(((cfg.get("ageing_history") or {})
                             .get("dimensions") or {}).get(role) or "")
            result["history_dimensions"][role] = [
                {"name": _read(row, _alias(reference)),
                 "value": _number(row, "value"),
                 "qty": _number(row, "qty"),
                 "aged": _number(row, "aged"),
                 "aged_qty": _number(row, "aged_qty")} for row in rows]
        elif name == "clearance":
            member = _alias(str(cfg.get("ageing_shared_division") or ""))
            result[name] = [{"name": _read(row, member),
                             "aged_qty": _number(row, "aged_qty"),
                             "aged_value": _number(row, "aged_value"),
                             "total_value": _number(row, "total_value"),
                             "daily_qty": _number(row, "daily_qty")}
                            for row in rows]
        elif name == "categories":
            member = _alias(str(cfg.get("ageing_category") or ""))
            result[name] = [{"name": _read(row, member),
                             "total": _number(row, "total"),
                             "aged": _number(row, "aged")} for row in rows]
        elif name == "risk_lines":
            status = cfg.get("ageing_status") or {}
            result[name] = [{
                "sku": _read(row, _alias(str(status.get("sku") or ""))),
                "location": _read(row, _alias(str(status.get("location") or ""))),
                "category": _read(row, _alias(str(status.get("category") or ""))),
                "status": _read(row, _alias(str(status.get("status") or ""))),
                "risk_score": _read(row, "risk_score"),
                "value": _number(row, "value"),
                "qty": _number(row, "qty"),
                "daily_qty": _number(row, "daily_qty")} for row in rows]
        elif name == "history_bands":
            bucket_name = _alias(str((cfg.get("ageing_history") or {})
                                     .get("bucket") or ""))
            result[name] = [{"name": _read(row, bucket_name),
                             "value": _number(row, "value"),
                             "qty": _number(row, "qty"),
                             "skus": _number(row, "skus")} for row in rows]
        elif name.startswith("deep__"):
            result["deep_dives"][name.split("__", 1)[1]] = rows
        elif name == "bands":
            bucket_name = _alias(_required(cfg, "bucket"))
            result[name] = [{"[NEW AGE]": _read(row, bucket_name),
                             "[value]": _number(row, "value"),
                             "[aged]": _number(row, "aged"),
                             "[skus]": _number(row, "skus"),
                             "[qty]": _number(row, "qty")} for row in rows]
        elif name == "risk_split":
            status_name = _alias(_required(cfg, "non_moving"))
            result[name] = [{"[non_moving_status]": _read(row, status_name),
                             "[value]": _number(row, "value"),
                             "[aged]": _number(row, "aged")} for row in rows]
        else:
            result[name] = rows

    # Compatibility with the established report model while retaining every
    # generic role under ``dimensions`` for the statistical detector.
    def compatibility(role: str, canonical: str) -> list[dict]:
        reference = str((mapping.get("dimensions") or {}).get(role) or "")
        return [{f"[{canonical}]": _read(row, _alias(reference)),
                 "[value]": _number(row, "value"),
                 "[aged]": _number(row, "aged"),
                 "[high_risk]": _number(row, "high_risk"),
                 # Without these two the member never reaches the comparison
                 # against the earlier position: `basis_check` needs a quantity
                 # on both dates, and a member with none is skipped silently.
                 "[qty]": _number(row, "qty"),
                 "[aged_qty]": _number(row, "aged_qty")}
                for row in result["dimensions"].get(role, [])]

    result["divisions"] = compatibility("division", "DEPARTMENT")
    result["locations"] = compatibility("location", "LOC_CODE")
    result["sections_high_risk"] = compatibility("section", "SECTION")
    result["skutype"] = compatibility("sku_type", "skutype")
    return result


def build(scan_result: dict, cfg: dict) -> dict:
    model = ageing.build(scan_result, cfg)
    model["report_name"] = str(cfg.get("report_name") or model["report_name"])
    model["currency"] = str(cfg.get("ageing_currency") or model.get("currency") or "")
    model["ageing_dimensions"] = {
        role: [
            {"name": _read(row, _alias(str((cfg.get("ageing_mapping") or {})
                                            .get("dimensions", {}).get(role, "")))),
             "total": _number(row, "value"),
             "value": _number(row, "aged"),
             "high_risk": _number(row, "high_risk")}
            for row in rows
        ]
        for role, rows in (scan_result.get("dimensions") or {}).items()
    }
    # Re-run after attaching all generic dimension roles and configured currency.
    from . import ageing_stats
    model["stat_check"] = ageing_stats.analyze(model)
    model["stat_signals"] = ageing_stats.detect(model)
    model["deep_dives"] = _deep_dives(scan_result, cfg)
    model["semantic_policy"] = {
        "exposure": (cfg.get("ageing_mapping") or {}).get("exposure"),
        "aged_filter": cfg.get("ageing_aged_filter"),
        "high_risk_filter": cfg.get("ageing_high_risk_filter"),
        "oldest_filter": cfg.get("ageing_oldest_filter"),
        "rejected_measure": "[aged stock share]" if cfg.get("ageing_reject_model_aged_share", True) else None,
    }
    model["location_bands"] = {
        "watch_pct": cfg.get("ageing_location_watch_pct"),
        "critical_pct": cfg.get("ageing_location_critical_pct"),
    }
    model["semantic_validation"] = _semantic_validation(scan_result, model, cfg)
    if model["semantic_validation"].get("excluded"):
        model["caveats"].append(model["semantic_validation"]["message"])
    return model


def _semantic_validation(scan_result: dict, model: dict, cfg: dict) -> dict:
    row = (scan_result.get("snapshot") or [{}])[0]
    share = _read(row, "source_aged_share")
    numerator = _read(row, "source_aged_numerator")
    total = float((model.get("header") or {}).get("total_value") or 0.0)
    share_number = float(share) if share is not None else None
    numerator_number = float(numerator) if numerator is not None else None
    excluded = bool(
        (share_number is not None and (share_number < 0 or share_number > 1))
        or (numerator_number is not None and total >= 0 and numerator_number > total + 0.01)
    )
    measure = str(cfg.get("ageing_validation_share_expression") or "source measure")
    message = (
        f"The semantic model's {measure} was excluded: its numerator does not "
        "reconcile to the Stock Value exposure used by this report."
        if excluded else "The configured source ageing measure passed its bounded validation."
    )
    return {"measure": measure, "reported_share": share_number,
            "reported_numerator": numerator_number, "stock_value": total,
            "excluded": excluded, "message": message}


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


def _deep_dives(scan_result: dict, cfg: dict) -> list[dict]:
    sku_name = _alias(str((cfg.get("ageing_mapping") or {}).get("sku") or "sku"))
    labels = {
        "oldest_items": "Largest product exposures over 24 months",
        "aged_non_moving_items": "Largest products both aged and non-moving",
    }
    out = []
    for key, rows in (scan_result.get("deep_dives") or {}).items():
        normalized = [{"member": str(_read(row, sku_name) or "Unknown"),
                       "value": _number(row, "value")} for row in rows]
        out.append({"analysis": key, "title": labels.get(key, key.replace("_", " ").title()),
                    "rows": normalized})
    return out


def findings_payload(model: dict) -> dict:
    return {
        "report_id": model.get("report_id"),
        "period_label": model.get("period_label"),
        "stat_check": model.get("stat_check"),
        "findings": model.get("stat_signals") or [],
        "investigations": model.get("deep_dives") or [],
        "checks": model.get("checks") or {},
    }


def summary_markdown(model: dict) -> str:
    currency = str(model.get("currency") or "")
    h = model.get("header") or {}
    lines = [f"# {model.get('report_name')}", "", str(model.get("period_label") or ""), "",
             "## Executive summary", ""]
    lines.extend(f"- {sentence}" for sentence in model.get("narrative") or [])
    lines += _change_markdown(model)
    lines += ["", "## Stat check", ""]
    for signal in (model.get("stat_signals") or [])[:6]:
        lines.append(f"- **{signal.get('severity', 'info').title()}** — {signal.get('description')}")
    validation = model.get("semantic_validation") or {}
    if validation.get("excluded"):
        lines.append(f"- **Data quality** — {validation.get('message')}")
    all_ok = bool(model.get("checks")) and all((model.get("checks") or {}).values())
    lines += _outlook_markdown(model, currency)
    lines += ["", "## Control totals", "",
              f"- Total stock: {_money(h.get('total_value'), currency)}",
              f"- Aged stock: {_money(h.get('aged_value'), currency)} ({_pct(h.get('aged_share_pct'))})",
              f"- High-risk stock: {_money(h.get('high_risk_value'), currency)} ({_pct(h.get('high_risk_share_pct'))})",
              "", ("All published values passed the report reconciliation gate."
                    if all_ok else "The report failed its reconciliation gate; figures are diagnostic only.")]
    return "\n".join(lines) + "\n"


def _change_markdown(model: dict) -> list[str]:
    """What moved, in both lanes. Shares and counts only - see `ageing_history`."""
    lines: list[str] = []
    for lane, heading in ((model.get("comparison") or {}),
                          "Since the last stock position"),                          ((model.get("day_movement") or {}),
                          "Since the last reading of this report"):
        if not lane:
            continue
        lines += ["", f"## {heading}", ""]
        if not lane.get("available"):
            lines.append(f"- {lane.get('reason') or 'No comparison was available.'}")
            continue
        lines.append(f"- Compared with {lane.get('prior_as_at')} "
                     f"({lane.get('days')} days earlier): "
                     f"**{lane.get('verdict')}**.")
        for reading in lane.get("headlines") or []:
            points = reading.get("points")
            if not isinstance(points, (int, float)):
                continue
            lines.append(
                f"- {reading.get('label')}: {float(reading.get('then_pct') or 0):.1f}% "
                f"to {float(reading.get('now_pct') or 0):.1f}% "
                f"({'+' if points >= 0 else '-'}{abs(float(points)):.1f} points).")
        if not lane.get("value_comparable"):
            reason = (lane.get("basis") or {}).get("reason")
            if reason:
                lines.append(f"- {reason}")
    return lines


def _outlook_markdown(model: dict, currency: str) -> list[str]:
    """Clearance, the category review and the stuck lines."""
    lines: list[str] = []
    clearance = model.get("clearance") or {}
    if clearance.get("available"):
        horizon = int(clearance.get("horizon_days") or 30)
        lines += ["", f"## How much clears in the next {horizon} days", ""]
        for row in clearance.get("rows") or []:
            lines.append(
                f"- {row.get('name')}: about "
                f"{float(row.get('cleared_pct') or 0):.0f}% of its aged stock "
                f"would sell, {row.get('days_display')} to clear it all.")
    categories = model.get("categories") or {}
    if categories.get("available") and categories.get("over"):
        lines += ["", "## Categories over the review line", "",
                  f"- {categories['over']} of {categories['carried']} categories "
                  f"hold more than {float(categories['threshold_pct']):.0f}% of "
                  f"their own stock as aged stock."]
        for row in categories.get("worst") or []:
            lines.append(
                f"- {row.get('name')}: {_money(row.get('aged'), currency)} aged, "
                f"{float(row.get('aged_share_pct') or 0):.1f}% of its own stock.")
    stuck = model.get("stuck_lines") or {}
    if stuck.get("available"):
        lines += ["", "## Product lines with the most money stuck", ""]
        for row in (stuck.get("rows") or [])[:5]:
            lines.append(
                f"- {row.get('sku')} ({row.get('category')}) at "
                f"{row.get('location')}: {_money(row.get('value'), currency)}, "
                f"risk score {float(row.get('risk_score') or 0):.0f}.")
        if stuck.get("note"):
            lines.append(f"- {stuck['note']}")
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
        lines.append("- No material exception crossed the configured Ageing thresholds.")
    lines += ["", "## Deeper investigation", ""]
    for dive in model.get("deep_dives") or []:
        lines.append(f"### {dive.get('title')}")
        lines.append("")
        rows = dive.get("rows") or []
        if not rows:
            lines.append("No exposure was returned for this cut.")
        else:
            for row in rows:
                lines.append(f"- {row.get('member')}: {_money(row.get('value'), currency)}")
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
              "- This is a single stock position, so it supports distribution and concentration findings, not YoY or trend claims.",
              "- Aged and non-moving overlap; they are never added together.",
              f"- {(model.get('semantic_validation') or {}).get('message', 'Source ageing measures are validated before use.')}"]
    return "\n".join(lines) + "\n"


def _money(value, currency: str) -> str:
    number = float(value or 0.0)
    if abs(number) >= 1_000_000:
        return f"{currency} {number / 1_000_000:.2f}M".strip()
    if abs(number) >= 1_000:
        return f"{currency} {number / 1_000:.0f}K".strip()
    return f"{currency} {number:,.0f}".strip()


def _pct(value) -> str:
    return f"{float(value or 0.0):.1f}%"


def dump_json(value: object) -> str:
    return json.dumps(value, indent=2, default=str)
