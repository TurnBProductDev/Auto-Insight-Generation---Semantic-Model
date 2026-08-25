"""SKU Overview's adapter onto the shared `snapshot_investigator` engine.

The eight rulebook rules (`sku_overview_insights.py`) superseded the earlier
generic hotspot detector, and its `to_signals()` findings are ESTATE-WIDE
aggregates (`dimension: "estate"`, `affected_segment` a description phrase
like "Segment A stockouts", not a real filterable member) - structurally
different from Ageing's/the old detector's "a named department/location is
worse than its own average" findings, which is what the original version of
this adapter drilled. Pointed at signals shaped that way, it found zero
drillable candidates every run (0/9 budget spent, silently) - an accepted
gap for a while, fixed here.

The right question for an estate-wide finding is not "TREATAS-scope to this
member, then drill" (there is no member) - it is "break the SAME rule's own
population down by a dimension it isn't already grouped by, and see where
it concentrates". So each of the four drillable rules keeps its own exact
filter predicate (the same one `sku_overview_insights.py` uses to find the
population in the first place - copied here deliberately rather than
imported, so a change to one is visible as a diff against the other, not a
silent shared mutation of a report's own rule), and the drill groups that
same population by department, section, location or category, ranked by
how many Loc-SKUs land in each.
"""

from __future__ import annotations

from typing import Callable

from . import sku_overview_flow as flow
from . import snapshot_investigator

Execute = Callable[[str], list[dict]]

#: analysis_type -> the exact filter predicate `sku_overview_insights.py`
#: uses for that rule (shops-only scope is added separately, in
#: `build_drill_dax`, matching every rule's own convention). `{FACT}` is
#: filled in from `sku_overview_mapping.table`.
_RULE_FILTERS: dict[str, str] = {
    "sku_overview_segment_a_stockout":
        '{FACT}[SKUSEGMENT] = "SEG_A",\n    {FACT}[SKU_STOCK_STATUS] = "STOCK OUT"',
    "sku_overview_verge_stockout_fixable":
        '{FACT}[RECOMMENDED_ACTION] = "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE"',
    "sku_overview_non_moving_pending":
        '{FACT}[RECOMMENDED_ACTION] = "NON MOVING",\n    {FACT}[PENDING_ORDERS] > 0',
    "sku_overview_overstock_pending":
        '{FACT}[RECOMMENDED_ACTION] = "OVERSTOCK",\n    {FACT}[PENDING_ORDERS] > 0',
}


def candidates(model: dict, cfg: dict, *, max_findings: int) -> list[dict]:
    """The rule-derived findings, each offered every mapped dimension to
    drill into - there is no "own" role to exclude, since the finding is
    estate-wide rather than already scoped to one dimension's member."""
    limit = max(0, int(max_findings))
    if limit == 0:
        return []
    roles = list((cfg.get("sku_overview_mapping") or {}).get("dimensions") or {})
    if not roles:
        return []
    out: list[dict] = []
    for finding in model.get("stat_signals") or []:
        atype = str(finding.get("analysis_type") or "")
        if atype not in _RULE_FILTERS:
            continue
        out.append({**finding, "_drill_role": atype, "_drill_others": list(roles)})
        if len(out) >= limit:
            break
    return out


def build_drill_dax(cfg: dict, *, own_role: str, own_member: str, drill_role: str,
                    limit: int = 10) -> str:
    """Deterministic, shops-scoped, TOPN-bounded. Never LLM-authored.

    `own_role` here is the finding's `analysis_type` (which rule it came
    from), not a dimension - it selects the rule's own predicate from
    `_RULE_FILTERS`. `own_member` is unused: the population is the whole
    matching estate, not one already-identified member."""
    mapping = cfg.get("sku_overview_mapping") or {}
    dims = mapping.get("dimensions") or {}
    table = mapping.get("table", "")
    drill_column = str(dims.get(drill_role) or "")
    predicate_template = _RULE_FILTERS.get(own_role)
    if predicate_template is None or not drill_column:
        raise ValueError(f"unsupported drill: own_role={own_role!r} drill_role={drill_role!r}")
    predicate = predicate_template.format(FACT=table)
    shops = flow._shops_literal()
    return f"""EVALUATE
TOPN(
  {int(limit)},
  CALCULATETABLE(
    SUMMARIZECOLUMNS(
      {drill_column},
      "value", COUNTROWS({table})
    ),
    {table}[LOC_CODE] IN {shops},
    {predicate}
  ),
  [value], DESC, {drill_column}, ASC
)"""


def _normalize(cfg: dict, rows: list[dict], drill_role: str) -> list[dict]:
    column = (cfg.get("sku_overview_mapping") or {}).get("dimensions", {}).get(drill_role, "")
    alias = flow._alias(str(column))
    normalized = [
        {"name": str(flow._read(row, alias) or "Unknown"),
         "value": flow._number(row, "value")}
        for row in rows
    ]
    normalized.sort(key=lambda r: -r["value"])
    return normalized


def investigate(execute: Execute, model: dict, cfg: dict, *, rules: str = "",
                log: Callable[[str], None] | None = None) -> dict:
    # The shared engine formats every drilled value with `model["currency"]`
    # (money(), built for stock-value drills). This adapter's drill values
    # are Loc-SKU COUNTS, not money - currency is blanked here only, for
    # this call, rather than touching the shared formatter (see
    # daily_sales_investigator.py for the identical fix and reasoning).
    drill_model = {**model, "currency": ""}
    return snapshot_investigator.investigate(
        execute, drill_model, cfg,
        report_id="sku_overview",
        candidates_fn=candidates,
        build_dax_fn=build_drill_dax,
        normalize_fn=lambda rows, role: _normalize(cfg, rows, role),
        enabled_key="sku_overview_investigation_enabled",
        max_findings_key="sku_overview_investigation_max_findings",
        max_rounds_key="sku_overview_investigation_max_rounds",
        budget_total_key="sku_overview_investigation_max_queries",
        budget_per_finding_key="sku_overview_investigation_max_roles_per_finding",
        default_max_findings=3, default_max_rounds=3,
        default_budget_total=9, default_budget_per_finding=3,
        rules=rules, log=log,
    )
