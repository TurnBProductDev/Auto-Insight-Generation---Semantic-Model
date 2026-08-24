"""Ageing's adapter onto the shared `snapshot_investigator` engine.

Ageing has no period to compare against (`ageing_stats.py` is explicit: never
manufacture a YoY delta, a trend, or a significance claim), so the question
worth investigating is not "why did this change" but "where inside this
hotspot does the exposure sit". This module owns only what is genuinely
Ageing-specific - which findings are worth investigating, and the
deterministic, TREATAS-scoped DAX that drills one of them by another
dimension. Everything about HOW the investigation runs (the adaptive
round-by-round loop, the budget, the validation, the narrative authoring) is
shared with `sku_overview_investigator.py` through `snapshot_investigator.py`,
so the two cannot drift on the things that matter most for a feature running
live DAX against a published report.
"""

from __future__ import annotations

from typing import Callable

from . import ageing_flow, snapshot_investigator

Execute = Callable[[str], list[dict]]

#: Only these finding types name a real member with a concrete dimension role -
#: an estate-wide finding ("Whole stock position") has nothing to scope a
#: TREATAS filter to.
_DRILLABLE_TYPES = {"ageing_rate_hotspot", "ageing_concentration"}


def candidates(model: dict, cfg: dict, *, max_findings: int) -> list[dict]:
    """Top findings worth drilling, ranked by the report's own score.

    A candidate needs a real member AND a dimension role that is itself one
    of the mapped roles (so a TREATAS filter has a real column to scope to),
    AND at least one other mapped role to drill into.
    """
    limit = max(0, int(max_findings))
    if limit == 0:
        return []
    roles = list((cfg.get("ageing_mapping") or {}).get("dimensions") or {})
    out: list[dict] = []
    for finding in model.get("stat_signals") or []:
        if finding.get("analysis_type") not in _DRILLABLE_TYPES:
            continue
        role = str(finding.get("dimension") or "")
        member = str(finding.get("affected_segment") or "").strip()
        if role not in roles or not member or member == "Whole stock position":
            continue
        others = [r for r in roles if r != role]
        if not others:
            continue
        out.append({**finding, "_drill_role": role, "_drill_others": others})
        if len(out) >= limit:
            break
    return out


def build_drill_dax(cfg: dict, *, own_role: str, own_member: str, drill_role: str,
                    limit: int = 10) -> str:
    """Deterministic, TREATAS-scoped, TOPN-bounded. Never LLM-authored.

    Reuses `ageing_flow`'s own exposure/aged expressions - the same ones the
    rest of the report reconciles against - so a drill-down can never
    disagree with the finding it explains.
    """
    mapping = cfg.get("ageing_mapping") or {}
    dims = mapping.get("dimensions") or {}
    exposure = ageing_flow._expression(ageing_flow._required(cfg, "exposure"))
    aged_filter = str(cfg.get("ageing_aged_filter") or "")
    own_column = str(dims.get(own_role) or "")
    drill_column = str(dims.get(drill_role) or "")
    aged = ageing_flow._calc(exposure, aged_filter)
    escaped_member = str(own_member).replace('"', '""')
    return f"""EVALUATE
TOPN(
  {int(limit)},
  FILTER(
    CALCULATETABLE(
      SUMMARIZECOLUMNS(
        {drill_column},
        "value", {exposure},
        "aged", {aged}
      ),
      TREATAS({{"{escaped_member}"}}, {own_column})
    ),
    [aged] <> 0
  ),
  [aged], DESC, {drill_column}, ASC
)"""


def _normalize(cfg: dict, rows: list[dict], drill_role: str) -> list[dict]:
    column = (cfg.get("ageing_mapping") or {}).get("dimensions", {}).get(drill_role, "")
    alias = ageing_flow._alias(str(column))
    normalized = [
        {"name": str(ageing_flow._read(row, alias) or "Unknown"),
         "value": ageing_flow._number(row, "aged")}
        for row in rows
    ]
    normalized.sort(key=lambda r: -r["value"])
    return normalized


def investigate(execute: Execute, model: dict, cfg: dict, *, rules: str = "",
                log: Callable[[str], None] | None = None) -> dict:
    return snapshot_investigator.investigate(
        execute, model, cfg,
        report_id="inventory_ageing",
        candidates_fn=candidates,
        build_dax_fn=build_drill_dax,
        normalize_fn=lambda rows, role: _normalize(cfg, rows, role),
        enabled_key="ageing_investigation_enabled",
        max_findings_key="ageing_investigation_max_findings",
        max_rounds_key="ageing_investigation_max_rounds",
        budget_total_key="ageing_investigation_max_queries",
        budget_per_finding_key="ageing_investigation_max_roles_per_finding",
        default_max_findings=3, default_max_rounds=3,
        default_budget_total=9, default_budget_per_finding=3,
        rules=rules, log=log,
    )
