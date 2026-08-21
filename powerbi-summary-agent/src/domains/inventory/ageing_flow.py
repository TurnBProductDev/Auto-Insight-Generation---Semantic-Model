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
               *, rows: int = 100) -> str:
    return f"""EVALUATE
TOPN(
  {int(rows)},
  FILTER(
    SUMMARIZECOLUMNS(
      {dimension},
      "value", {exposure},
      "aged", {aged},
      "high_risk", {high_risk}
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
  "locations", DISTINCTCOUNT({location}){validation_fields}
)""",
        "bands": f"""EVALUATE
SUMMARIZECOLUMNS(
  {bucket},
  "value", {exposure},
  "aged", {aged},
  "skus", DISTINCTCOUNT({sku})
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
            str(reference), exposure, aged, high, rows=limit)

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


def scan(execute: Execute, cfg: dict, *, log: Callable[[str], None] | None = None) -> dict:
    queries = build_queries(cfg)
    mapping = cfg.get("ageing_mapping") or {}
    result: dict = {"queries": {}, "dimensions": {}, "deep_dives": {},
                    "currency": cfg.get("ageing_currency", "")}
    for name, dax in queries.items():
        if log:
            log(f"  {name}")
        rows = execute(dax)
        result["queries"][name] = dax
        if name.startswith("dimension__"):
            result["dimensions"][name.split("__", 1)[1]] = rows
        elif name.startswith("deep__"):
            result["deep_dives"][name.split("__", 1)[1]] = rows
        elif name == "bands":
            bucket_name = _alias(_required(cfg, "bucket"))
            result[name] = [{"[NEW AGE]": _read(row, bucket_name),
                             "[value]": _number(row, "value"),
                             "[aged]": _number(row, "aged"),
                             "[skus]": _number(row, "skus")} for row in rows]
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
                 "[high_risk]": _number(row, "high_risk")}
                for row in result["dimensions"].get(role, [])]

    result["divisions"] = compatibility("division", "DEPARTMENT")
    result["locations"] = compatibility("location", "LOC_CODE")
    result["sections_high_risk"] = compatibility("section", "SECTION")
    result["skutype"] = compatibility("sku_type", "skutype")
    return result


def build(scan_result: dict, cfg: dict) -> dict:
    model = ageing.build(scan_result)
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
    lines += ["", "## Stat check", ""]
    for signal in (model.get("stat_signals") or [])[:6]:
        lines.append(f"- **{signal.get('severity', 'info').title()}** — {signal.get('description')}")
    validation = model.get("semantic_validation") or {}
    if validation.get("excluded"):
        lines.append(f"- **Data quality** — {validation.get('message')}")
    all_ok = bool(model.get("checks")) and all((model.get("checks") or {}).values())
    lines += ["", "## Control totals", "",
              f"- Total stock: {_money(h.get('total_value'), currency)}",
              f"- Aged stock: {_money(h.get('aged_value'), currency)} ({_pct(h.get('aged_share_pct'))})",
              f"- High-risk stock: {_money(h.get('high_risk_value'), currency)} ({_pct(h.get('high_risk_share_pct'))})",
              "", ("All published values passed the report reconciliation gate."
                    if all_ok else "The report failed its reconciliation gate; figures are diagnostic only.")]
    return "\n".join(lines) + "\n"


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
