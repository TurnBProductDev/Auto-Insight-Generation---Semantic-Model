"""Daily Sales' adapter onto the shared `snapshot_investigator` engine
(`src/domains/inventory/snapshot_investigator.py`). The engine is genuinely
domain-agnostic - report_id, candidate list, a DAX builder and a row
normalizer are all supplied by the caller - so this reuses it directly
rather than duplicating the validation/budget/adaptive-round machinery a
second time. (A future tidy-up could promote it out of `domains/inventory`
into `kernel`; not done here to avoid touching the already-proven Ageing/
SKU Overview call sites for an unrelated change.)

Only Net Sales is drilled. Margin has no meaningful "where does it
concentrate" breakdown - it is already a ratio - and **Bills is the wrong
key even though it is available**: one basket touching three departments
counts once in each, so a section's Bills gap can exceed its own
department's. Ranked side by side that reads as nonsense, and it shipped
that way once (a section at -4,797 under a department at -620). Net Sales
adds up exactly at every level once the two scales are reconciled (see
`daily_sales.measure_scale`), so it is the only additive key here.

The drilled figures are on the SOURCE scale, like everything else below
store level, so `investigate` is handed the run's measured scale and
multiplies each gap by it before the value is shown. A drill that printed
raw source-scale numbers beside a rescaled page would disagree with the
page by 3.7x.

A department-level finding may drill into its sections or categories; a
section-level finding may drill into its categories; a whole-business
finding has no single member to scope a drill by and is never offered here.
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
        if "net_sales" not in str(finding.get("analysis_type") or ""):
            continue  # Margin is a ratio; Bills does not add up across grains
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
    `drill_role`, ranked by the size of the Net Sales gap against that row's
    own P50 - the same "where does the shortfall concentrate" question the
    inventory reports' drills answer, over the one measure that adds up at
    every grain in this model.

    Rows that recorded no sale are excluded, matching `daily_sales._rollup`:
    a benchmark carrying groups which could not contribute drags every name
    below its own band."""
    mapping = cfg.get("daily_sales_mapping") or {}
    dept_col = mapping.get("department_col") or "DEPARTMENT"
    section_col = mapping.get("section_col") or "SECTION"
    category_col = mapping.get("category_col") or "CATEGORY_NAME_2"
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

    # The scope is a table VARIABLE that the aggregation is summarised over,
    # not a CALCULATETABLE wrapped around SUMMARIZE with the aggregation added
    # outside it. The second shape looks equivalent and is not: the ADDCOLUMNS
    # expressions evaluate in the OUTER filter context, so the tran_date and
    # member filters never reach them and each row is summed across every day
    # the table holds. Measured live on 2026-08-23: PROVISIONS came back at
    # -28,293.58 against its true -5,672.40, a five-fold overstatement on a
    # query that returned the right member names and no error.
    return f"""EVALUATE
VAR LatestDate = {latest}
VAR Scoped =
  FILTER(
    ALL({table}),
    {table}[tran_date] = LatestDate
      && {table}[{scope_col}] = "{esc}"
      && NOT ISBLANK({table}[actual_sales])
  )
RETURN
TOPN({int(limit)},
  SUMMARIZE(
    Scoped,
    {table}[{group_col}],
    "sales_actual", SUM({table}[actual_sales]),
    "gap", SUM({table}[actual_sales]) - SUM({table}[sales_p50])
  ),
  ABS([gap]), DESC
)"""


def _normalize(cfg: dict, rows: list[dict], drill_role: str, scale: float = 1.0) -> list[dict]:
    """`scale` puts the drilled gaps on the same scale as the page. They come
    off the source-scale columns, so without it a drill disagrees with the
    figure it is explaining by the whole factor."""
    mapping = cfg.get("daily_sales_mapping") or {}
    group_col = (mapping.get("section_col") or "SECTION") if drill_role == "section" \
        else (mapping.get("category_col") or "CATEGORY_NAME_2")
    out = []
    for row in rows:
        name = _read(row, group_col)
        if name is None:
            continue
        out.append({"name": str(name), "value": _num(row, "gap") * scale})
    out.sort(key=lambda r: -abs(r["value"]))
    return out


def investigate(execute: Execute, model: dict, cfg: dict, *, rules: str = "", log=None,
                scale: float = 1.0) -> dict:
    """`scale` is the run's measured source-to-reporting factor (see
    `daily_sales.measure_scale`); the drilled gaps are read straight off the
    source-scale columns, so they are multiplied by it here."""
    return snapshot_investigator.investigate(
        execute, model, cfg, report_id="daily_sales",
        candidates_fn=candidates, build_dax_fn=build_drill_dax,
        normalize_fn=lambda rows, role: _normalize(cfg, rows, role, scale),
        enabled_key="daily_sales_investigation_enabled",
        max_findings_key="daily_sales_investigation_max_findings",
        max_rounds_key="daily_sales_investigation_max_rounds",
        budget_total_key="daily_sales_investigation_max_queries",
        budget_per_finding_key="daily_sales_investigation_max_roles_per_finding",
        default_max_findings=3, default_max_rounds=2,
        default_budget_total=9, default_budget_per_finding=2,
        rules=rules, log=log)
