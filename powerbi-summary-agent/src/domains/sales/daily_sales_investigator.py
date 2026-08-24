"""Daily Sales' adapter onto the shared `snapshot_investigator` engine
(`src/domains/inventory/snapshot_investigator.py`). The engine is genuinely
domain-agnostic - report_id, candidate list, a DAX builder and a row
normalizer are all supplied by the caller - so this reuses it directly
rather than duplicating the validation/budget/adaptive-round machinery a
second time. (A future tidy-up could promote it out of `domains/inventory`
into `kernel`; not done here to avoid touching the already-proven Ageing/
SKU Overview call sites for an unrelated change.)

Only Bills is drilled - Margin has no meaningful "where does it
concentrate" breakdown (it is already a ratio), and Net Sales is never
scoped by this report at all (see `daily_sales.py`'s module docstring for
why). A department-level finding may drill into its sections or
categories; a section-level finding may drill into its categories; a
whole-business finding has no single member to scope a drill by and is
never offered here.
"""

from __future__ import annotations

from typing import Callable

from ..inventory import investigation_budget, snapshot_investigator  # noqa: F401 (budget re-export)

Execute = Callable[[str], list[dict]]

#: dimension -> the roles a finding at that dimension may drill into.
_DRILLABLE: dict[str, tuple[str, ...]] = {
    "whole": (), "department": ("section", "category"), "section": ("category",),
}


def _clean_key(key: object) -> str:
    return str(key).split("[")[-1].strip("]").lower()


def _read(row: dict, name: str):
    wanted = name.lower()
    for key, value in (row or {}).items():
        if _clean_key(key) == wanted:
            return value
    return None


def _num(row: dict, name: str) -> float:
    value = _read(row, name)
    return float(value) if isinstance(value, (int, float)) else 0.0


def candidates(model: dict, cfg: dict, *, max_findings: int) -> list[dict]:
    limit = max(0, int(max_findings))
    if limit == 0:
        return []
    out: list[dict] = []
    for finding in model.get("stat_signals") or []:
        if "bills" not in str(finding.get("analysis_type") or ""):
            continue  # Margin has no drill; Net Sales is never a signal here
        role = str(finding.get("dimension") or "")
        others = _DRILLABLE.get(role) or ()
        member = str(finding.get("affected_segment") or "").strip()
        if not others or not member:
            continue
        out.append({**finding, "_drill_role": role, "_drill_others": list(others)})
        if len(out) >= limit:
            break
    return out


def build_drill_dax(cfg: dict, *, own_role: str, own_member: str, drill_role: str,
                    limit: int = 10) -> str:
    """A bounded, TREATAS-free (name-filter is exact and unambiguous - see
    module docstring on why department/section names are matched by name
    alone) breakdown of `own_member` (a department or section) by
    `drill_role`, ranked by the size of the Bills gap against that row's own
    P50 - the same "where does the shortfall concentrate" question the
    inventory reports' drills answer, over the one measure this report
    trusts at every grain."""
    mapping = cfg.get("daily_sales_mapping") or {}
    dept_col = mapping.get("department_col") or "DEPARTMENT"
    section_col = mapping.get("section_col") or "SECTION"
    category_col = mapping.get("category_col") or "CATEGORY_NAME"
    esc = str(own_member).replace('"', '""')

    if drill_role == "section":
        table = mapping.get("section_table") or "sectionbenchmark"
        group_col, scope_col, latest = section_col, dept_col, "[Section Latest Date]"
    elif drill_role == "category":
        table = mapping.get("category_table") or "categorybenchmark"
        group_col = category_col
        scope_col = dept_col if own_role == "department" else section_col
        latest = "[Category Latest Date]"
    else:
        raise ValueError(f"unsupported drill_role: {drill_role!r}")

    return f"""EVALUATE
VAR LatestDate = {latest}
RETURN
TOPN({int(limit)},
  ADDCOLUMNS(
    CALCULATETABLE(
      SUMMARIZE({table}, {table}[{group_col}]),
      {table}[tran_date] = LatestDate,
      {table}[{scope_col}] = "{esc}"
    ),
    "bills_actual", CALCULATE(SUM({table}[actual_bills])),
    "gap", CALCULATE(SUM({table}[actual_bills])) - CALCULATE(SUM({table}[bills_p50]))
  ),
  ABS([gap]), DESC
)"""


def _normalize(cfg: dict, rows: list[dict], drill_role: str) -> list[dict]:
    mapping = cfg.get("daily_sales_mapping") or {}
    group_col = (mapping.get("section_col") or "SECTION") if drill_role == "section" \
        else (mapping.get("category_col") or "CATEGORY_NAME")
    out = []
    for row in rows:
        name = _read(row, group_col)
        if name is None:
            continue
        out.append({"name": str(name), "value": _num(row, "gap")})
    out.sort(key=lambda r: -abs(r["value"]))
    return out


def investigate(execute: Execute, model: dict, cfg: dict, *, rules: str = "", log=None) -> dict:
    # The shared engine formats every drilled value with `model["currency"]`
    # (money(), built for stock-value drills elsewhere). This report's drill
    # values are Bills GAPS - a count, not money - so currency is blanked
    # here only, for this call, rather than touching the shared formatter.
    drill_model = {**model, "currency": ""}
    return snapshot_investigator.investigate(
        execute, drill_model, cfg, report_id="daily_sales",
        candidates_fn=candidates, build_dax_fn=build_drill_dax,
        normalize_fn=lambda rows, role: _normalize(cfg, rows, role),
        enabled_key="daily_sales_investigation_enabled",
        max_findings_key="daily_sales_investigation_max_findings",
        max_rounds_key="daily_sales_investigation_max_rounds",
        budget_total_key="daily_sales_investigation_max_queries",
        budget_per_finding_key="daily_sales_investigation_max_roles_per_finding",
        default_max_findings=3, default_max_rounds=2,
        default_budget_total=9, default_budget_per_finding=2,
        rules=rules, log=log)
