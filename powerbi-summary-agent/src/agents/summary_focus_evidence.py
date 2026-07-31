"""Focus deep-dive evidence builder (deterministic, no LLM).

Runs between ``summary_novelty_filter`` and ``fresh_summary_generator`` in the
summary branch. It takes the single focus the novelty filter selected and builds
a guaranteed, focused deep dive for *that focus only*: a scorecard, an internal
contributor breakdown by a metadata-discovered child dimension, a location
breakdown, an exact volume/rate driver bridge, and a validated period trend.

Concurrency contract (see CLAUDE.md):

* writes only summary-branch state keys;
* executes with the pre-fetched ``state["pbi_token"]`` and never calls
  ``get_powerbi_token()`` post-fork;
* is non-fatal - a failed drill degrades to remaining evidence plus a caveat and
  the branch still funnels through ``summary_branch_done``;
* imports the shared scope gate from the agent layer, never from a tool.

The LLM never generates or repairs any deep-dive DAX. Targeted DAX is validated
by ``dax_validator`` and the shared comparable-scope gate; one failed query is
non-fatal and no LLM repair is attempted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import deque
from datetime import date
from typing import Any

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..tools import summary_focus
from ..tools import summary_focus_queries as q
from ..tools import summary_roles
from ..utils.logger import RunLogger
from .dax_validator import validate_one
from .scope_validator import validate_comparable_scope


_TAIL_BRACKET = re.compile(r"\[([^\]]+)\]\s*$")
_FULL_REF = re.compile(r"^'((?:[^']|'')+)'\[([^\]]+)\]$")

# Generic reusable business-hierarchy roles.  These are semantic vocabulary,
# never model object names or members.  The closest valid child level wins.
_HIERARCHY_PATTERNS = (
    (10, "division", ("division", "div")),
    (20, "department", ("department", "dept", "dep")),
    (30, "category", ("item category", "category")),
    (35, "subcategory", ("sub category", "subcategory")),
    (40, "product_group", ("product group",)),
    (50, "special_product_group", ("special product group",)),
    (60, "brand", ("brand",)),
    (70, "item", ("sku", "item name", "item code", "product name")),
)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _clean_key(key: Any) -> str:
    match = _TAIL_BRACKET.search(str(key))
    return match.group(1) if match else str(key)


def _clean_row(row: dict) -> dict:
    return {_clean_key(key): value for key, value in (row or {}).items()}


def _fmt(value: float, signed: bool = False, pct: bool = False) -> str:
    if not _number(value):
        return str(value)
    sign = "+" if signed else ""
    if pct:
        return f"{value:{sign}.1f}%"
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:{sign}.2f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:{sign}.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:{sign}.1f}K"
    if absolute and absolute < 1:
        return f"{value:{sign}.2f}"
    return f"{value:{sign}.0f}"


# --- reference resolution ----------------------------------------------------
def _families(profile: dict) -> list[dict]:
    """Ordered value/volume families with their real current/prior/change measures."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(bundle: dict | None, label: str) -> None:
        if not isinstance(bundle, dict):
            return
        family = str(bundle.get("family") or label)
        if family in seen:
            return
        measures = bundle.get("measures") or {}
        phases = {phase: measures[phase] for phase in ("current", "prior", "change") if measures.get(phase)}
        if not phases.get("current"):
            return
        seen.add(family)
        out.append({
            "family": family,
            "label": label,
            "phases": phases,
            "source_table": bundle.get("source_table"),
        })

    add(profile.get("primary_value_bundle"), "revenue")
    for bundle in profile.get("volume_driver_bundles") or []:
        add(bundle, str(bundle.get("family") or "volume"))
    for bundle in profile.get("value_bundles") or []:
        add(bundle, str(bundle.get("family") or "value"))
    return out


def _alias(family: str, phase: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "_", str(family).lower()).strip("_") or "metric"
    return f"{safe}_{phase}"


def _ref_parts(reference: Any) -> tuple[str, str]:
    match = _FULL_REF.match(str(reference or "").strip())
    if not match:
        return "", ""
    return match.group(1).replace("''", "'"), match.group(2)


def _semantic_level(value: Any) -> tuple[int | None, str | None]:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    # Test the more specific names first ("special product group" also
    # contains "product group").
    for level, role, patterns in reversed(_HIERARCHY_PATTERNS):
        if any(re.search(rf"\b{re.escape(pattern)}\b", text) for pattern in patterns):
            return level, role
    return None, None


def _relationship_distance(metadata: dict, start: str, target: str, max_hops: int = 3) -> int | None:
    if not start or not target:
        return None
    if start == target:
        return 0
    graph: dict[str, set[str]] = {}
    for relationship in metadata.get("relationships", []) or []:
        if not relationship.get("is_active", True):
            continue
        left, right = relationship.get("from_table"), relationship.get("to_table")
        if left and right:
            graph.setdefault(str(left), set()).add(str(right))
            graph.setdefault(str(right), set()).add(str(left))
    queue = deque([(start, 0)])
    seen = {start}
    while queue:
        table, distance = queue.popleft()
        if distance >= max_hops:
            continue
        for neighbour in graph.get(table, set()):
            if neighbour == target:
                return distance + 1
            if neighbour not in seen:
                seen.add(neighbour)
                queue.append((neighbour, distance + 1))
    return None


def _override_values(state: dict, focus_ref: str | None, focus_role: str | None) -> list | None:
    overrides = state.get("summary_focus_hierarchy_overrides")
    if overrides is None:
        overrides = (state.get("config", {}) or {}).get("summary_focus_hierarchy_overrides")
    if overrides in (None, {}):
        return None
    if not isinstance(overrides, dict):
        raise ValueError("summary_focus_hierarchy_overrides must be an object keyed by focus role or column")
    focus_table, focus_column = _ref_parts(focus_ref)
    keys = {
        str(focus_role or "").casefold(),
        str(focus_ref or "").casefold(),
        str(focus_column or "").casefold(),
        f"{focus_table}[{focus_column}]".casefold() if focus_table and focus_column else "",
    }
    for key, values in overrides.items():
        if str(key).casefold() not in keys:
            continue
        if not isinstance(values, list) or not values:
            raise ValueError(f"hierarchy override {key!r} must contain at least one child column")
        return values
    return None


def _discover_child_dimensions(
    state: dict,
    profile: dict,
    focus_ref: str | None,
    max_children: int,
    focus_role: str | None = None,
) -> list[dict]:
    """Discover semantically compatible child dimensions before runtime tests.

    This enforces the first two hierarchy tests here (semantic ordering and an
    active relationship path/same source table).  The targeted breakdown adds
    parent-filter, nestedness and reconciliation diagnostics in the same REST
    call, so discovery does not consume a separate probe budget.
    """
    focus_norm = str(focus_ref or "").casefold()
    focus_table, focus_column = _ref_parts(focus_ref)
    inferred_level, inferred_role = _semantic_level(focus_column)
    focus_role = summary_roles.canonical_role(
        focus_role or inferred_role or focus_column, focus_column, state,
    )
    parent_level = summary_roles.hierarchy_level(focus_role)
    if parent_level is None:
        parent_level = inferred_level
    metadata = state.get("model_metadata", {}) or {}
    entity_ref = str((profile.get("entity_dimension") or {}).get("reference") or "").casefold()
    dimensions = [dim for dim in profile.get("dimensions") or [] if dim.get("reference")]

    def compatible(dim: dict) -> tuple[bool, dict]:
        reference = str(dim.get("reference") or "")
        table, column = _ref_parts(reference)
        inferred_child_level, inferred_child_role = _semantic_level(column)
        role = summary_roles.canonical_role(
            inferred_child_role or column, column, state,
        )
        level = summary_roles.hierarchy_level(role)
        if level is None:
            level = inferred_child_level
        same_table = bool(focus_table and table == focus_table)
        path = _relationship_distance(metadata, focus_table, table) if focus_table else int(
            dim.get("relationship_distance", 0) or 0
        )
        semantic_ok = level is not None and (
            parent_level is None or level > parent_level
        )
        # Merchandise foci use the separate location drill, not a store column
        # masquerading as an internal child.  Store foci intentionally start at
        # the top of the merchandise hierarchy.
        if focus_role != "store" and reference.casefold() == entity_ref:
            semantic_ok = False
        path_ok = same_table or path is not None
        return semantic_ok and path_ok, {
            **dim,
            "hierarchy_level": level,
            "hierarchy_role": role,
            "same_source_table": same_table,
            "relationship_path_length": path,
        }

    candidates: list[dict] = []
    for dim in dimensions:
        if str(dim.get("reference") or "").casefold() == focus_norm:
            continue
        ok, enriched = compatible(dim)
        if ok:
            candidates.append(enriched)

    requested = _override_values(state, focus_ref, focus_role)
    if requested is not None:
        resolved: list[dict] = []
        for raw in requested:
            target = str(raw or "").casefold()
            matches = [
                dim for dim in candidates
                if target in {
                    str(dim.get("reference") or "").casefold(),
                    str(dim.get("column") or "").casefold(),
                    f"{dim.get('table')}[{dim.get('column')}]".casefold(),
                }
            ]
            if len(matches) > 1 and focus_table:
                same_table_matches = [dim for dim in matches if dim.get("table") == focus_table]
                if len(same_table_matches) == 1:
                    matches = same_table_matches
            if len(matches) != 1:
                raise ValueError(
                    f"hierarchy override child {raw!r} is missing, ambiguous, or incompatible with {focus_ref}"
                )
            resolved.append({**matches[0], "discovery_source": "validated_override"})
        return resolved[:max(0, int(max_children))]

    def rank(dim: dict) -> tuple:
        level = int(dim.get("hierarchy_level") or 999)
        gap = level - parent_level if parent_level is not None else level
        return (
            0 if dim.get("same_source_table") else 1,
            gap,
            int(dim.get("relationship_path_length") or 0),
            -float(dim.get("score") or 0),
            str(dim.get("reference") or ""),
        )

    ordered = sorted(candidates, key=rank)
    deduped: list[dict] = []
    seen_roles: set[tuple[str, str]] = set()
    for dim in ordered:
        # Name/code variants of the same semantic level are alternative labels,
        # not two independent drills.  Keep the strongest metadata-ranked one.
        identity = (str(dim.get("table") or ""), str(dim.get("hierarchy_role") or ""))
        if identity in seen_roles:
            continue
        seen_roles.add(identity)
        deduped.append({**dim, "discovery_source": "metadata"})
    return deduped[:max(0, int(max_children))]


# --- execution ---------------------------------------------------------------
def _run_query(state: dict, query: dict, budget: dict, cache: dict) -> dict:
    dax = query.get("dax") or ""
    reasons = validate_one(dax, state.get("model_metadata", {}))
    reasons += validate_comparable_scope(dax, state, query.get("contract_hint"))
    if reasons:
        return {"status": "invalid", "reasons": reasons, "rows": []}
    if dax in cache:
        return {**cache[dax], "cached": True}
    if not state.get("pbi_token"):
        return {"status": "no_token", "rows": []}
    if budget["used"] >= budget["max"]:
        return {"status": "budget_exhausted", "rows": []}
    budget["used"] += 1
    result = pbi.execute_python(
        state["workspace_id"], state["dataset_id"],
        [{"name": query["name"], "dax": dax, "purpose": query.get("purpose", "")}],
        token=state.get("pbi_token"),
    )
    entry = result.get(query["name"], {}) or {}
    if entry.get("status") == "success":
        rows = [_clean_row(row) for row in pbi.extract_rows(entry.get("result") or {})]
        out = {"status": "success", "rows": rows}
    else:
        out = {"status": "failed", "rows": [], "error": str(entry.get("error"))[:300]}
    cache[dax] = out
    return out


# --- deep-dive assembly ------------------------------------------------------
def _scorecard_metrics(row: dict, families: list[dict]) -> dict:
    """Derive current/prior/change/% and simple rates from a scorecard row."""
    out: dict[str, dict] = {}
    for family in families:
        label = family["family"]
        current = row.get(_alias(label, "current"))
        prior = row.get(_alias(label, "prior"))
        change = row.get(_alias(label, "change"))
        if not _number(current):
            continue
        if not _number(prior) and _number(change):
            prior = float(current) - float(change)
        if not _number(change) and _number(prior):
            change = float(current) - float(prior)
        pct = None
        if _number(prior) and abs(float(prior)) > 1e-9:
            pct = (float(current) - float(prior)) / abs(float(prior)) * 100.0
        out[label] = {
            "current": float(current) if _number(current) else None,
            "prior": float(prior) if _number(prior) else None,
            "change": float(change) if _number(change) else None,
            "change_pct": pct,
        }
    return out


def _reuse_scorecard(candidate: dict, families: list[dict]) -> dict:
    """Recover a member-scoped scorecard from already-returned comparison facts."""
    facts = [
        fact for fact in (candidate.get("evidence") or {}).get("facts", []) or []
        if str(fact.get("subject_role") or "") == "focus"
    ]
    out: dict[str, dict] = {}
    for family in families:
        family_name = str(family.get("family") or "")
        matching = [
            fact for fact in facts
            if family_name.casefold() in str(fact.get("metric") or "").casefold()
        ]
        comparison = next(
            (fact for fact in matching if fact.get("fact_kind") == "comparison"),
            None,
        )
        if comparison and _number(comparison.get("current_value")):
            current = float(comparison["current_value"])
            prior = comparison.get("prior_value")
            change = comparison.get("change_value")
            if not _number(prior) and _number(change):
                prior = current - float(change)
            if not _number(change) and _number(prior):
                change = current - float(prior)
            pct = comparison.get("change_pct")
            if not _number(pct) and _number(prior) and abs(float(prior)) > 1e-9:
                pct = (current - float(prior)) / abs(float(prior)) * 100.0
            out[family_name] = {
                "current": current,
                "prior": float(prior) if _number(prior) else None,
                "change": float(change) if _number(change) else None,
                "change_pct": float(pct) if _number(pct) else None,
            }
            continue

        phases: dict[str, float] = {}
        for fact in matching:
            metric = str(fact.get("metric") or "").casefold()
            for phase in ("current", "prior", "change"):
                if phase in metric and _number(fact.get("raw_value")):
                    phases.setdefault(phase, float(fact["raw_value"]))
        if "current" in phases and ("prior" in phases or "change" in phases):
            prior = phases.get("prior")
            change = phases.get("change")
            if prior is None:
                prior = phases["current"] - float(change)
            if change is None:
                change = phases["current"] - float(prior)
            pct = (phases["current"] - prior) / abs(prior) * 100.0 if abs(prior) > 1e-9 else None
            out[family_name] = {
                "current": phases["current"], "prior": prior, "change": change, "change_pct": pct,
            }
    return out


def _time_grain(dim: dict) -> str | None:
    text = re.sub(
        r"[^a-z0-9]+", " ",
        f"{dim.get('column', '')} {dim.get('reference', '')}".casefold(),
    )
    for grain in ("month", "quarter", "week", "year", "day", "date"):
        if re.search(rf"\b{grain}\b", text):
            return "day" if grain == "date" else grain
    return None


def _axis_checks(period: dict, dim: dict) -> list[dict]:
    """Find period-resolver checks for one metadata axis.

    REST rows and semantic metadata do not always spell a column the same way
    (for example ``UPDATED_DATE`` versus ``'Sales'[UPDATED_DATE]``), so compare
    both the full normalized references and their trailing column names.
    """
    reference = str(dim.get("reference") or "").strip().casefold()
    column = str(dim.get("column") or "").strip().casefold()
    wanted = {reference, column, _clean_key(reference).casefold()} - {""}
    matches = []
    for check in period.get("checks", []) or []:
        names = set()
        for value in (check.get("column"), check.get("axis_reference")):
            text = str(value or "").strip().casefold()
            if text:
                names.update({text, _clean_key(text).casefold()})
        if wanted & names:
            matches.append(check)
    return matches


def _daily_gate(state: dict, period: dict, dim: dict) -> tuple[bool, str]:
    """Summary-owned future-date/freshness/history gate for a daily axis.

    Deliberately reuses only summary state (the period resolver's checks and
    freshness) - it never imports or reads Insight's business-day gate. Rejects
    a stale axis, a future-dated axis (the live daily table exposed one), and an
    axis with too little history.
    """
    checks = _axis_checks(period, dim)
    if not checks:
        return False, "no observed day-axis evidence to validate"
    if any(str(check.get("verdict") or "") == "batch_date" for check in checks):
        return False, "axis behaves like a batch/load date"

    usable = [
        check for check in checks
        if str(check.get("verdict") or "") == "ok" and str(check.get("grain") or "") == "day"
    ]
    if not usable:
        periods = max((int(check.get("periods") or 0) for check in checks), default=0)
        return False, f"axis did not validate as a distributed business-day series ({periods} day(s))"
    check = max(usable, key=lambda item: int(item.get("periods") or 0))

    # Prefer the candidate axis's own maximum. Older resolver artifacts do not
    # have it, so retain a conservative global-watermark fallback.
    data_as_of = summary_focus._as_date(check.get("data_as_of") or period.get("data_as_of"))
    if data_as_of is None:
        return False, "no day-axis watermark"
    try:
        today = summary_focus.focus_today(state)
    except Exception:  # noqa: BLE001 - a bad timezone must not crash the deep dive
        return False, "timezone unresolved"
    if data_as_of > today:
        return False, "axis exposes a future date"

    stale_after = max(0, int(state.get("summary_stale_after_periods", 2)))
    lag = (today - data_as_of).days
    if lag > stale_after:
        return False, f"day axis is stale by {lag} day(s) (maximum {stale_after})"

    # Preserve the resolver's global stale verdict as a second safety check for
    # legacy contexts that carried no per-axis bounds.
    freshness = str(period.get("freshness_status") or "")
    if freshness == "stale":
        return False, "data freshness is stale"

    min_days = max(3, int(state.get("summary_focus_daily_trend_min_days", 14)))
    periods = int(check.get("periods") or 0)
    if periods < min_days:
        return False, f"only {periods} day(s) of history (minimum {min_days})"
    return True, "ok"


def _select_trend_dimension(state: dict, profile: dict, revenue_family: dict) -> tuple[dict | None, dict | None]:
    """Pick a summary-owned business-period axis; never read Insight state.

    Returns ``(dim, daily_note)``. ``daily_note`` records the optional daily-axis
    gate outcome (passed/gated) when ``summary_focus_daily_trend_enabled`` is set,
    so the caller can report an honest daily-trend status.
    """
    daily_note: dict | None = None
    if not state.get("summary_focus_include_trend", True):
        if state.get("summary_focus_daily_trend_enabled", False):
            daily_note = {"status": "disabled", "reason": "summary_focus_include_trend is false"}
        return None, daily_note
    period = state.get("summary_period_context") or {}
    rejected = {
        str(value).casefold()
        for check in period.get("checks", []) or []
        if check.get("verdict") == "batch_date"
        for value in (check.get("column"), check.get("axis_reference"))
        if value
    }
    allow_daily = bool(state.get("summary_focus_daily_trend_enabled", False))
    source_table = str(revenue_family.get("source_table") or "")
    candidates = []
    daily_notes = []
    # Preserve the R1 preference for a stable business-period view. Enabling
    # R2 makes a validated day axis available as a fallback; the audit says
    # ``available`` when a safer/coarser period axis wins.
    priority = {"month": 0, "quarter": 1, "week": 2, "year": 3, "day": 4}
    for dim in profile.get("time_dimensions") or []:
        reference = str(dim.get("reference") or "")
        column = str(dim.get("column") or "")
        if not reference:
            continue
        grain = _time_grain(dim)
        if grain is None:
            continue
        if grain == "day":
            if not allow_daily:
                continue
            ok, why = _daily_gate(state, period, dim)
            if not ok:
                daily_notes.append({"status": "gated", "reason": why, "axis": column})
                continue
            daily_notes.append({"status": "passed", "axis": column})
        elif {reference.casefold(), column.casefold()} & rejected:
            continue
        candidates.append((
            0 if str(dim.get("table") or "") == source_table else 1,
            priority.get(grain, 9),
            -float(dim.get("score") or 0),
            reference,
            {**dim, "grain": grain},
        ))
    chosen = min(candidates)[-1] if candidates else None
    if allow_daily:
        if chosen is not None and str(chosen.get("grain")) == "day":
            daily_note = next(
                (note for note in daily_notes if note.get("status") == "passed"
                 and note.get("axis") == chosen.get("column")),
                {"status": "passed", "axis": chosen.get("column")},
            )
        else:
            daily_note = next(
                (note for note in daily_notes if note.get("status") == "passed"),
                daily_notes[0] if daily_notes else {
                    "status": "gated", "reason": "no daily axis in metadata", "axis": None,
                },
            )
    return chosen, daily_note


def _diagnostic_value(rows: list[dict], name: str) -> float | None:
    for row in rows:
        if _number(row.get(name)):
            return float(row[name])
    return None


def _hierarchy_runtime_checks(
    rows: list[dict], child: dict, focus_total: float | None, tol_pct: float
) -> dict:
    focus_diag = _diagnostic_value(rows, "__focus_total")
    global_diag = _diagnostic_value(rows, "__global_total")
    parent_counts = [float(row["__parent_count"]) for row in rows if _number(row.get("__parent_count"))]
    tolerance = abs(float(focus_total or 0.0)) * max(0.0, tol_pct) / 100.0
    reconciles = bool(
        _number(focus_total)
        and _number(focus_diag)
        and abs(float(focus_diag) - float(focus_total)) <= max(1.0, tolerance)
    )
    return {
        "semantic_order": child.get("hierarchy_level") is not None,
        "relationship_path": bool(
            child.get("same_source_table") or child.get("relationship_path_length") is not None
        ),
        "parent_filters_child": bool(rows and reconciles),
        "filter_effect_observed": bool(
            _number(focus_diag) and _number(global_diag)
            and abs(float(focus_diag) - float(global_diag)) > max(1.0, tolerance)
        ),
        "nestedness": bool(parent_counts) and all(count <= 1.0 for count in parent_counts),
        "reconciles_to_parent": reconciles,
        "focus_total": focus_diag,
        "unfiltered_total": global_diag,
    }


def _strip_diagnostics(rows: list[dict]) -> list[dict]:
    return [
        {key: value for key, value in row.items() if not str(key).startswith("__") and key != "abs_sort"}
        for row in rows
    ]


def _driver_bridge(scorecard: dict) -> dict | None:
    """Exact revenue decomposition into volume and rate/mix (never pure price)."""
    revenue = scorecard.get("revenue") or {}
    quantity = scorecard.get("quantity") or {}
    r1, r0 = revenue.get("current"), revenue.get("prior")
    q1, q0 = quantity.get("current"), quantity.get("prior")
    if not all(_number(v) for v in (r1, r0, q1, q0)) or abs(q0) < 1e-9 or abs(q1) < 1e-9:
        return None
    volume = (q1 - q0) * (r0 / q0)
    rate = q1 * ((r1 / q1) - (r0 / q0))
    total = r1 - r0
    driver_class = "volume" if abs(volume) >= abs(rate) else "rate/mix"
    return {
        "volume_effect": volume,
        "rate_mix_effect": rate,
        "total_change": total,
        "reconciles": abs((volume + rate) - total) <= max(1.0, abs(total) * 0.01),
        "driver_class": driver_class,
    }


def _top_movers(rows: list[dict], label_col: str, change_alias: str) -> tuple[dict | None, dict | None]:
    scored = [
        (row, float(row.get(change_alias)))
        for row in rows
        if _number(row.get(change_alias)) and row.get(label_col) not in (None, "")
    ]
    if not scored:
        return None, None
    top_pos = max(scored, key=lambda item: item[1])
    top_neg = min(scored, key=lambda item: item[1])
    pos = {"member": top_pos[0].get(label_col), "change": top_pos[1]} if top_pos[1] > 0 else None
    neg = {"member": top_neg[0].get(label_col), "change": top_neg[1]} if top_neg[1] < 0 else None
    return pos, neg


def _reconciled(rows: list[dict], current_alias: str, focus_total: float | None, tol_pct: float) -> str:
    if not rows or not _number(focus_total) or abs(float(focus_total)) < 1e-9:
        return "partial"
    returned = sum(float(row[current_alias]) for row in rows if _number(row.get(current_alias)))
    if abs(returned - float(focus_total)) <= abs(float(focus_total)) * (tol_pct / 100.0):
        return "complete"
    return "partial"


def _trend_reconciled(rows: list[dict], focus_total: float | None, tol_pct: float) -> str:
    """Validate the complete pre-TOPN series and its selected-focus total."""
    if not rows or not _number(focus_total):
        return "partial"
    series_total = _diagnostic_value(rows, "__series_total")
    query_focus_total = _diagnostic_value(rows, "__focus_total")
    if not (_number(series_total) and _number(query_focus_total)):
        return "partial"
    tolerance = max(1.0, abs(float(focus_total)) * max(0.0, tol_pct) / 100.0)
    if (
        abs(float(series_total) - float(query_focus_total)) <= tolerance
        and abs(float(query_focus_total) - float(focus_total)) <= tolerance
    ):
        return "complete"
    return "partial"


def run(state: dict) -> dict:
    log = RunLogger(state)

    if not state.get("summary_focus_enabled", True) or not state.get("summary_focus_deep_dive_enabled", True):
        return {**log.updates()}

    focus = state.get("summary_selected_focus") or {}
    candidate_id = str(focus.get("candidate_id") or "")
    if not candidate_id:
        log.info("Focus deep dive: no focus was selected this run; nothing to enrich.")
        return {**log.updates()}

    eligible = list(state.get("summary_eligible_candidates") or [])
    selected = next((c for c in eligible if str(c.get("candidate_id")) == candidate_id), None)
    if selected is None:
        log.error("Focus deep dive: selected focus candidate not found among eligible; skipped.")
        return {**log.updates()}

    profile = state.get("semantic_model_profile") or {}
    entity = profile.get("entity_dimension") or {}
    entity_ref = entity.get("reference")
    families = _families(profile)
    if not families:
        log.error("Focus deep dive: no additive value family in metadata; deep dive skipped.")
        return {**log.updates()}

    resolved = state.get("resolved_entity_scope") or {}
    comparable = [
        str(item) for item in
        (resolved.get("active_comparable_population") or [])
    ]

    focus_ref = selected.get("dimension_ref")
    member_value = selected.get("member_value")
    is_broad = selected.get("candidate_kind") != "member" or not focus_ref or member_value is None
    is_entity_focus = bool(entity_ref and focus_ref and str(focus_ref) == str(entity_ref))

    focus_filters: list[str] = []
    if not is_broad:
        focus_filters.append(q.member_filter(focus_ref, member_value))
    population_filter = None
    if entity_ref and comparable and not is_entity_focus:
        population_filter = q.treatas(entity_ref, comparable)

    def _drill_filters() -> list[str]:
        out = list(focus_filters)
        if population_filter is not None:
            out.append(population_filter)
        return out

    if is_entity_focus and member_value is not None:
        codes = [str(member_value)]
    else:
        codes = list(comparable)
    contract_hint = {"population_status": "comparable", "population_codes": codes} if codes else {}

    budget = {"used": 0, "max": max(0, int(state.get("summary_focus_max_queries", 4)))}
    cache: dict = {}
    tol_pct = float(state.get("summary_focus_reconciliation_tolerance_pct", 2))
    caveats: list[str] = []
    sections: dict = {}

    # --- 1. Scorecard --------------------------------------------------------
    # Member candidates already contain exact current/prior/change comparison
    # facts for the selected row.  Reusing them is what lets the default budget
    # cover children + location + trend in four fresh calls.
    scorecard_metrics = _reuse_scorecard(selected, families)
    required_families = {family["family"] for family in families}
    if required_families and required_families <= set(scorecard_metrics):
        sections["scorecard"] = {"source": "reused_candidate", "metrics": scorecard_metrics}
    else:
        score_measures = []
        for family in families:
            for phase, measure in family["phases"].items():
                score_measures.append((_alias(family["family"], phase), measure))
        query = q.scorecard(
            f"focus_scorecard_{candidate_id}",
            f"Focus scorecard for {selected.get('segment')}",
            _drill_filters(),
            score_measures,
            contract_hint,
        )
        result = _run_query(state, query, budget, cache)
        if result.get("status") == "success" and result.get("rows"):
            scorecard_metrics = _scorecard_metrics(result["rows"][0], families)
            sections["scorecard"] = {"source": "targeted_dax", "metrics": scorecard_metrics}
        else:
            caveats.append("scorecard unavailable")
            sections["scorecard"] = {"source": "unavailable", "status": result.get("status")}

    # --- 2. Internal contributor breakdown ----------------------------------
    revenue_family = families[0]
    rev_cur = _alias(revenue_family["family"], "current")
    rev_chg = _alias(revenue_family["family"], "change")
    breakdown_measures = [
        (_alias(revenue_family["family"], phase), measure)
        for phase, measure in revenue_family["phases"].items()
    ]
    has_change = "change" in revenue_family["phases"]
    sort_measure = revenue_family["phases"].get("change") or revenue_family["phases"]["current"]
    rows_cap = int(state.get("summary_focus_max_rows_per_breakdown", 12))
    focus_current_total = (scorecard_metrics.get(revenue_family["family"]) or {}).get("current")
    trend_dim, daily_note = _select_trend_dimension(state, profile, revenue_family)
    location_needed = bool(entity_ref and str(focus_ref or "") != str(entity_ref))
    reserved_queries = int(location_needed) + int(trend_dim is not None)
    child_budget = max(0, budget["max"] - budget["used"] - reserved_queries)
    max_children = min(
        max(0, int(state.get("summary_focus_max_child_dimensions", 2))),
        child_budget,
    )

    try:
        children = _discover_child_dimensions(
            state, profile, focus_ref, max_children, selected.get("dimension_role")
        )
    except ValueError as exc:
        children = []
        caveats.append(str(exc))
        log.error(f"Focus deep dive hierarchy override rejected: {exc}")
    contributor_sections = []
    for child in children:
        child_ref = child.get("reference")
        child_col = child.get("column")
        query = q.breakdown(
            f"focus_child_{candidate_id}_{len(contributor_sections)}",
            f"{selected.get('segment')} by {child_col}",
            child_ref,
            _drill_filters(),
            breakdown_measures,
            sort_measure,
            rows_cap,
            contract_hint,
            parent_col_ref=focus_ref if not is_broad else None,
        )
        result = _run_query(state, query, budget, cache)
        if result.get("status") != "success":
            if result.get("status") not in {"budget_exhausted", "invalid", "no_token"}:
                caveats.append(f"contributor breakdown by {child_col} failed")
            continue
        raw_rows = result["rows"]
        if is_broad:
            hierarchy_checks = {
                "semantic_order": True,
                "relationship_path": bool(
                    child.get("same_source_table") or child.get("relationship_path_length") is not None
                ),
                "parent_filters_child": True,
                "filter_effect_observed": None,
                "nestedness": True,
                "reconciles_to_parent": _reconciled(
                    _strip_diagnostics(raw_rows), rev_cur, focus_current_total, tol_pct
                ) == "complete",
                "not_applicable": "broad focus has no parent member",
            }
        else:
            hierarchy_checks = _hierarchy_runtime_checks(raw_rows, child, focus_current_total, tol_pct)
            if is_entity_focus:
                # Store -> merchandise is an intentional cross-cut, not a
                # strict taxonomy: the same category naturally appears in many
                # stores. Parent filtering and reconciliation remain required,
                # while child-to-parent nestedness is not applicable.
                hierarchy_checks["nestedness"] = True
                hierarchy_checks["nestedness_not_applicable"] = "entity-to-merchandise cross-cut"
        if not all(
            hierarchy_checks.get(name)
            for name in (
                "semantic_order", "relationship_path", "parent_filters_child",
                "nestedness", "reconciles_to_parent",
            )
        ):
            caveats.append(f"child dimension {child_col} failed hierarchy validation")
            continue
        rows = _strip_diagnostics(raw_rows)
        completeness = _reconciled(rows, rev_cur, focus_current_total, tol_pct)
        pos, neg = _top_movers(rows, child_col, rev_chg if has_change else rev_cur)
        contributor_sections.append({
            "dimension": child_col,
            "reference": child_ref,
            "hierarchy_role": child.get("hierarchy_role"),
            "discovery_source": child.get("discovery_source"),
            "hierarchy_checks": hierarchy_checks,
            "rows": rows[:rows_cap],
            "completeness": completeness,
            "top_positive": pos,
            "top_negative": neg,
        })
    sections["internal_contributors"] = contributor_sections

    # --- 3. Location breakdown ----------------------------------------------
    location_section = None
    if location_needed:
        # Merchandise focus split across the calculation's eligible stores.
        query = q.breakdown(
            f"focus_location_{candidate_id}",
            f"{selected.get('segment')} across the stores included in the comparison",
            entity_ref,
            _drill_filters(),
            breakdown_measures,
            sort_measure,
            rows_cap,
            contract_hint,
        )
        result = _run_query(state, query, budget, cache)
        if result.get("status") == "success":
            rows = result["rows"]
            pos, neg = _top_movers(rows, _clean_key(entity.get("column")), rev_chg if has_change else rev_cur)
            location_section = {
                "dimension": entity.get("column"),
                "rows": rows[:rows_cap],
                "completeness": _reconciled(rows, rev_cur, focus_current_total, tol_pct),
                "top_positive": pos,
                "top_negative": neg,
            }
        elif result.get("status") not in {"budget_exhausted", "invalid", "no_token"}:
            caveats.append("location breakdown failed")
    sections["location"] = location_section

    # --- 4. Driver bridge ----------------------------------------------------
    bridge = _driver_bridge(scorecard_metrics) if state.get("summary_focus_include_driver_bridge", True) else None
    sections["driver_bridge"] = bridge

    # --- 5. Period trend -----------------------------------------------------
    trend_section = None
    trend_outcome = None
    if state.get("summary_focus_include_trend", True):
        if trend_dim is not None:
            query = q.period_trend(
                f"focus_trend_{candidate_id}",
                f"{selected.get('segment')} over time",
                trend_dim.get("reference"),
                _drill_filters(),
                breakdown_measures,
                int(state.get("summary_focus_max_rows_per_breakdown", 12)) * 2,
                contract_hint,
            )
            result = _run_query(state, query, budget, cache)
            if result.get("status") == "success" and result.get("rows"):
                raw_rows = result["rows"]
                completeness = _trend_reconciled(raw_rows, focus_current_total, tol_pct)
                rows = _strip_diagnostics(raw_rows)
                if completeness == "complete" and len(rows) >= 3:
                    trend_section = {
                        "dimension": trend_dim.get("column"),
                        "reference": trend_dim.get("reference"),
                        "grain": trend_dim.get("grain"),
                        "rows": rows,
                        "completeness": completeness,
                        "direction": _trend_direction(rows, rev_chg if has_change else rev_cur),
                    }
                    trend_outcome = "active"
                else:
                    trend_outcome = "trend query did not reconcile to the selected focus"
                    caveats.append("period trend did not reconcile to the selected focus")
            elif result.get("status") not in {"budget_exhausted", "invalid", "no_token"}:
                trend_outcome = "trend query failed"
                caveats.append("period trend failed")
            else:
                trend_outcome = f"trend query was {result.get('status')}"
        else:
            trend_outcome = "no validated business time axis"
            caveats.append("no validated business time axis for the focus trend")
    sections["period_trend"] = trend_section

    # Optional daily trend (R2): only after the summary-owned future-date /
    # freshness / history gate passes. When it passes it is delivered as the
    # period trend above (day grain), so this records the gate outcome.
    if not state.get("summary_focus_daily_trend_enabled", False):
        sections["daily_trend"] = {"status": "disabled", "reason": "summary_focus_daily_trend_enabled is false"}
    elif daily_note and daily_note.get("status") == "disabled":
        sections["daily_trend"] = dict(daily_note)
    elif (
        daily_note and daily_note.get("status") == "passed"
        and trend_dim is not None and str(trend_dim.get("grain")) == "day"
        and trend_section is not None
    ):
        sections["daily_trend"] = {
            "status": "active", "axis": trend_dim.get("column"),
            "note": "delivered as the focus period trend",
        }
    elif (
        daily_note and daily_note.get("status") == "passed"
        and trend_dim is not None and str(trend_dim.get("grain")) == "day"
    ):
        sections["daily_trend"] = {
            "status": "gated", "axis": daily_note.get("axis"),
            "reason": trend_outcome or "the day trend could not be validated",
        }
    elif daily_note and daily_note.get("status") == "passed":
        sections["daily_trend"] = {
            "status": "available", "axis": daily_note.get("axis"),
            "reason": "a coarser business period axis was preferred",
        }
    else:
        sections["daily_trend"] = {
            "status": "gated",
            "axis": (daily_note or {}).get("axis"),
            "reason": (daily_note or {}).get("reason") or "no daily axis in metadata",
        }

    # --- assemble enriched facts + signature --------------------------------
    sections["caveats"] = list(caveats)
    facts, signature_fields = _build_facts(selected, scorecard_metrics, contributor_sections,
                                           location_section, bridge, trend_section, revenue_family)

    # R3: compare this deep dive's signature against recently delivered ones. A
    # near-duplicate means we resolved essentially the same story (same top
    # contributors / driver / location) as a recent focus - flagged so it is
    # visible and can inform the next run's overlap suppression.
    duplicate_of, overlap = _signature_duplicate(
        signature_fields,
        state.get("summary_recent_focus") or [],
        float(state.get("summary_focus_fact_overlap_threshold", 0.6) or 0.0),
        today=summary_focus.focus_today(state),
        window_days=int(state.get("summary_focus_overlap_window_days", 7)),
    )
    if duplicate_of:
        caveats.append("this deep dive repeats a recently delivered story (same contributors or driver)")
    sections["caveats"] = list(caveats)

    enriched = _attach(selected, facts, sections)

    evidence_doc = {
        "focus_key": focus.get("focus_key"),
        "candidate_id": candidate_id,
        "segment": selected.get("segment"),
        "dimension_role": selected.get("dimension_role"),
        "sections": sections,
        "caveats": caveats,
        "queries_attempted": budget["used"],
        "query_budget": budget["max"],
        "signature_fields": signature_fields,
        "deep_dive_signature": _signature(signature_fields),
        "signature_duplicate": bool(duplicate_of),
        "signature_duplicate_of": duplicate_of,
        "signature_overlap": round(overlap, 3),
        "facts": facts,
    }
    file_io.write_json(state, "summary_focus_evidence.json", evidence_doc)

    new_candidates = [
        enriched if str(c.get("candidate_id")) == candidate_id else c
        for c in state.get("summary_candidates", []) or []
    ]
    new_eligible = [
        enriched if str(c.get("candidate_id")) == candidate_id else c
        for c in eligible
    ]
    updated_focus = {
        **focus,
        "fact_keys": [
            fact.get("fact_id")
            for fact in (enriched.get("evidence") or {}).get("facts", []) or []
            if fact.get("fact_id")
        ],
        "deep_dive_signature": evidence_doc["deep_dive_signature"],
    }
    log.info(
        "Focus deep dive: %s enriched with %d fact(s) over %d fresh quer(y/ies)%s."
        % (selected.get("segment"), len(facts), budget["used"],
           f"; caveats: {'; '.join(caveats)}" if caveats else "")
    )
    return {
        "summary_focus_evidence": evidence_doc,
        "summary_selected_focus": updated_focus,
        "summary_eligible_candidates": new_eligible,
        "summary_candidates": new_candidates,
        **log.updates(),
    }


def _trend_direction(rows: list[dict], change_alias: str) -> str:
    values = [float(row[change_alias]) for row in rows if _number(row.get(change_alias))]
    if len(values) < 2:
        return "insufficient"
    recent = values[-1]
    if recent > 0 and values[-2] <= 0:
        return "reversal_up"
    if recent < 0 and values[-2] >= 0:
        return "reversal_down"
    if recent > values[-2]:
        return "accelerating" if recent > 0 else "weakening_decline"
    return "decelerating" if recent > 0 else "deepening_decline"


def _build_facts(selected, scorecard, contributors, location, bridge, trend, revenue_family):
    facts: list[dict] = []
    segment = str(selected.get("segment") or "the focus")
    coverage_scorecard = "complete" if scorecard else str(selected.get("coverage") or "partial")

    def add(
        subject, metric, raw, statement, role="focus", coverage="partial",
        signed=False, pct=False, detail_role="focus_metric",
    ):
        facts.append({
            "fact_id": f"D{len(facts) + 1}",
            "fact_kind": "deep_dive",
            "subject": subject,
            "metric": metric,
            "display_value": _fmt(raw, signed=signed, pct=pct),
            "raw_value": float(raw),
            "statement": statement,
            "subject_role": role,
            "detail_role": detail_role,
            "coverage": coverage,
        })

    rev = scorecard.get(revenue_family["family"]) or {}
    if _number(rev.get("change")):
        change = rev["change"]
        pct = rev.get("change_pct")
        detail = f" ({_fmt(pct, signed=True, pct=True)})" if _number(pct) else ""
        add(segment, "Revenue change", change,
            f"{segment} revenue changed by {_fmt(change, signed=True)}{detail}.",
            coverage=coverage_scorecard, signed=True)
    for family in ("quantity", "transactions"):
        info = scorecard.get(family) or {}
        if _number(info.get("change")):
            add(segment, f"{family.title()} change", info["change"],
                f"{segment} {family} changed by {_fmt(info['change'], signed=True)}.",
                coverage=coverage_scorecard, signed=True)

    signature_fields = {
        "top_pos_contributor": None,
        "top_neg_contributor": None,
        "leading_location": None,
        "driver_class": bridge.get("driver_class") if bridge else None,
    }
    if contributors:
        section = contributors[0]
        coverage = section.get("completeness", "partial")
        pos, neg = section.get("top_positive"), section.get("top_negative")
        if pos and _number(pos.get("change")):
            signature_fields["top_pos_contributor"] = pos.get("member")
            add(str(pos.get("member")), f"Revenue change in {section['dimension']}", pos["change"],
                f"Within {segment}, {pos.get('member')} added {_fmt(pos['change'], signed=True)}.",
                role="peer", coverage=coverage, signed=True, detail_role="contributor")
        if neg and _number(neg.get("change")):
            signature_fields["top_neg_contributor"] = neg.get("member")
            add(str(neg.get("member")), f"Revenue change in {section['dimension']}", neg["change"],
                f"Within {segment}, {neg.get('member')} reduced revenue by {_fmt(neg['change'], signed=True)}.",
                role="peer", coverage=coverage, signed=True, detail_role="contributor")
    if location and location.get("top_positive") and _number((location["top_positive"] or {}).get("change")):
        pos = location["top_positive"]
        signature_fields["leading_location"] = pos.get("member")
        add(str(pos.get("member")), "Store contribution", pos["change"],
            f"{pos.get('member')} led {segment} across the stores included in the comparison at {_fmt(pos['change'], signed=True)}.",
            role="peer", coverage=location.get("completeness", "partial"), signed=True,
            detail_role="location")
    if bridge and bridge.get("reconciles"):
        primary = bridge["volume_effect"] if bridge["driver_class"] == "volume" else bridge["rate_mix_effect"]
        label = "units sold" if bridge["driver_class"] == "volume" else "average revenue per item"
        add(segment, "Main driver of the change", primary,
            f"Most of {segment}'s revenue change came from {label} ({_fmt(primary, signed=True)}).",
            coverage="complete", signed=True, detail_role="driver")
    return facts, signature_fields


def _attach(selected: dict, facts: list[dict], sections: dict) -> dict:
    enriched = {**selected}
    evidence = dict(selected.get("evidence") or {})
    existing_facts = list(evidence.get("facts") or [])
    existing_rows = list(evidence.get("rows") or [])
    extra_rows: list[dict] = []
    for section in sections.get("internal_contributors") or []:
        extra_rows.extend(section.get("rows") or [])
    if sections.get("location"):
        extra_rows.extend((sections["location"] or {}).get("rows") or [])
    evidence["facts"] = existing_facts + facts
    evidence["rows"] = existing_rows + extra_rows[:24]
    evidence["deep_dive"] = sections
    enriched["evidence"] = evidence
    enriched["has_deep_dive"] = True
    return enriched


def _signature(fields: dict) -> str:
    blob = json.dumps(fields, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


_SIGNATURE_FIELDS = ("top_pos_contributor", "top_neg_contributor", "leading_location", "driver_class")


def _signature_overlap(fields: dict, entry: dict) -> float:
    """Return a conservative overlap score for two deep-dive signatures.

    At least two independently populated fields must be comparable. The score's
    denominator is the union of populated fields, so a generic driver class by
    itself can never turn a sparse signature into a 100% duplicate.
    """
    left = {name: summary_focus._norm(fields.get(name)) for name in _SIGNATURE_FIELDS if fields.get(name)}
    right = {name: summary_focus._norm(entry.get(name)) for name in _SIGNATURE_FIELDS if entry.get(name)}
    common = [name for name in _SIGNATURE_FIELDS if name in left and name in right]
    if len(common) < 2:
        return 0.0
    matches = sum(1 for name in common if left[name] == right[name])
    return matches / len(set(left) | set(right))


def _signature_duplicate(
    fields: dict,
    recent: list[dict],
    threshold: float,
    *,
    today: date | None = None,
    window_days: int | None = None,
) -> tuple[str | None, float]:
    """Return the focus_key of the most-overlapping recent delivery, if >= threshold."""
    best_key, best_overlap = None, 0.0
    for entry in recent or []:
        if today is not None and window_days is not None and not summary_focus._within_days(
            entry.get("reported_at"), today, window_days
        ):
            continue
        overlap = _signature_overlap(fields, entry)
        if overlap > best_overlap:
            best_key, best_overlap = str(entry.get("focus_key") or ""), overlap
    if threshold > 0 and best_overlap >= threshold and best_key:
        return best_key, best_overlap
    return None, best_overlap
