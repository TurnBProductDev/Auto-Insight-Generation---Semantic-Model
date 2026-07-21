"""Insight branch - recent-week folding, calendar or rolling (Phase 3/3b, deterministic).

Runs after ``insight_business_day_source`` (which owns the one REST fetch and
all axis validation - see that module) and before ``insight_daily``. Answers
"what was unusual over the most recent complete window?" - a Mon-Sun calendar
week by default, or a trailing-7-day rolling window when ``insight_week_mode``
is ``"rolling"`` - by folding the already-validated daily series in Python
(never a locale-dependent DAX WEEKNUM), summing ONLY proven-additive metrics,
then attaching a bounded target-vs-previous-window driver breakdown by the
metadata primary dimension.

This node no longer validates the axis or fetches data itself - it purely
folds whatever ``insight_business_day_source`` already validated, so a
folding-specific failure here (e.g. "insufficient complete weeks") disables
only this node's own output, never the shared source or ``insight_daily``.

Calendar folding always uses the true ``data_as_of`` (not the "today"-trimmed
``effective_data_as_of``) - trimming would wrongly skip an already-complete
preceding week just because today's row is partial. Rolling folding uses
``effective_data_as_of``, since its target window's end IS "today" by
definition.

Everything here is best-effort: any failure disables the level; it never
raises into the run. Executes with the pre-fetched ``state["pbi_token"]``
(post-fork safe, only for the optional driver drill).
"""

from __future__ import annotations

from datetime import date, timedelta

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger
from .dax_validator import validate_one
from .insight_business_day_source import _as_date, _is_num, _monday, business_today
from .insight_scan_templates import (
    build_recent_week_driver_scan,
    current_additive_specs,
    shape_from_profile,
)
from .insight_temporal import _row_value
from .scope_validator import validate_comparable_scope


# --- pure, offline-testable logic ---------------------------------------------

def pick_target_week(as_of: date, data_as_of: date | None, week_start: str = "monday") -> dict:
    """The latest fully completed Mon-Sun week: its Sunday is strictly before the
    current (incomplete) week's Monday AND is covered by the data (<= data_as_of).
    Never the incomplete current week; steps back to the latest week the data
    actually covers."""
    week_end = _monday(as_of) - timedelta(days=1)   # last completed Sunday
    while data_as_of is not None and week_end > data_as_of:
        week_end = week_end - timedelta(days=7)
    week_start_d = week_end - timedelta(days=6)
    prev_end = week_start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return {"week_start": week_start_d, "week_end": week_end,
            "prev_start": prev_start, "prev_end": prev_end}


def pick_target_window_rolling(effective_data_as_of: date) -> dict:
    """Rolling analogue of ``pick_target_week``: the target window is always the
    trailing 7 days ending at ``effective_data_as_of``; previous is the 7 days
    immediately before that (non-overlapping with the target)."""
    week_end = effective_data_as_of
    week_start_d = week_end - timedelta(days=6)
    prev_end = week_start_d - timedelta(days=1)
    prev_start = prev_end - timedelta(days=6)
    return {"week_start": week_start_d, "week_end": week_end,
            "prev_start": prev_start, "prev_end": prev_end}


def fold_weeks(rows: list, axis: str, operating_days: set, additive_aliases: list,
               data_as_of: date | None, week_start: str = "monday") -> list:
    """Bucket daily rows into Mon-Sun weeks, summing ONLY additive_aliases. A week
    is complete iff its Sunday <= data_as_of AND it covers every operating day
    (missing weekends OK, a Monday-only week is NOT complete). Emits only complete
    weeks, ordered by week_start."""
    weeks: dict = {}
    for r in rows:
        d = _as_date(r.get(axis))
        if d is None:
            continue
        wk = _monday(d)
        w = weeks.setdefault(wk, {"days": set(), "sums": {a: 0.0 for a in additive_aliases}})
        w["days"].add(d.weekday())
        for a in additive_aliases:
            v = _row_value(r, a)
            if _is_num(v):
                w["sums"][a] += float(v)
    out = []
    for wk in sorted(weeks):
        week_end = wk + timedelta(days=6)
        covered = (data_as_of is None or week_end <= data_as_of)
        complete = covered and set(operating_days).issubset(weeks[wk]["days"])
        if not complete:
            continue
        row = {"week_start": wk.isoformat()}
        row.update({a: weeks[wk]["sums"][a] for a in additive_aliases})
        out.append(row)
    return out


def fold_rolling_windows(rows: list, axis: str, operating_days: set, additive_aliases: list,
                         effective_data_as_of: date | None) -> list:
    """Bucket daily rows into non-overlapping 7-day windows counting BACK from
    ``effective_data_as_of`` (bucket 0 = the trailing 7 days ending there, bucket 1
    = the 7 days immediately before that, ...) - structurally identical to
    ``fold_weeks``, just anchored to "today" instead of the calendar Monday
    boundary. A daily 1-day slide would overlap 6/7 with its neighbor and break
    the stat detector's non-overlapping week-over-week comparison; this doesn't.
    A window is complete iff it covers every operating day. Emits only complete
    windows, ordered by week_start - same row shape as ``fold_weeks``."""
    if effective_data_as_of is None:
        return []
    buckets: dict = {}
    for r in rows:
        d = _as_date(r.get(axis))
        if d is None or d > effective_data_as_of:
            continue
        offset = (effective_data_as_of - d).days // 7
        b = buckets.setdefault(offset, {"days": set(), "sums": {a: 0.0 for a in additive_aliases}})
        b["days"].add(d.weekday())
        for a in additive_aliases:
            v = _row_value(r, a)
            if _is_num(v):
                b["sums"][a] += float(v)
    out = []
    for offset in sorted(buckets):
        window_start = effective_data_as_of - timedelta(days=7 * offset + 6)
        complete = set(operating_days).issubset(buckets[offset]["days"])
        if not complete:
            continue
        row = {"week_start": window_start.isoformat()}
        row.update({a: buckets[offset]["sums"][a] for a in additive_aliases})
        out.append(row)
    out.sort(key=lambda r: r["week_start"])
    return out


def _missing_expected(rows: list, axis: str, weeks: list, operating: set) -> list:
    """Operating-day calendar dates inside the kept complete weeks/windows that
    have no data row - surfaced honestly in the evidence contract. Bounded."""
    present = {d for d in (_as_date(r.get(axis)) for r in rows) if d is not None}
    missing: list = []
    for w in weeks:
        wk = date.fromisoformat(w["week_start"])
        for off in range(7):
            d = wk + timedelta(days=off)
            if d.weekday() in operating and d not in present:
                missing.append(d.isoformat())
                if len(missing) >= 20:
                    return missing
    return missing


# --- graph node ---------------------------------------------------------------

def run(state: dict) -> dict:
    log = RunLogger(state)

    def _disable(reason: str, extra: dict | None = None) -> dict:
        verdict = {"enabled": False, "level": "recent_week", "reason": reason}
        if extra:
            verdict.update(extra)
        file_io.write_json(state, "insight_recent_week_verdict.json", verdict)
        log.info(f"Recent-week gate: disabled - {reason}.")
        return {"insight_recent_week_verdict": verdict, **log.updates()}

    if not state.get("insight_recent_week_enabled", True):
        return _disable("recent-week monitoring disabled by config")

    source = state.get("insight_business_day_source")
    if not source:
        bd_verdict = state.get("insight_business_day_verdict", {}) or {}
        reason = bd_verdict.get("reason", "no valid business-date axis available")
        return _disable(f"disabled - same reason as business-day source: {reason}")

    window_mode = str(state.get("insight_week_mode", "calendar")).lower()
    if window_mode not in ("calendar", "rolling"):
        window_mode = "calendar"

    profile = state.get("semantic_model_profile", {}) or {}
    shape = shape_from_profile(profile, state)
    specs = current_additive_specs(shape) if shape else []
    if not shape or not specs:
        return _disable("no additive primary value metric available")

    week_start = str(state.get("insight_week_start", "monday")).lower()
    history_weeks = max(4, int(state.get("insight_week_history_weeks", 13)))

    axis_key = source["axis_key"]
    axis_reference = source["axis_reference"]
    rows = source["rows"]
    aliases = source["additive_aliases"]
    data_as_of = _as_date(source["data_as_of"])
    effective_data_as_of = _as_date(source["effective_data_as_of"])
    operating = set(source["operating_days"])

    if window_mode == "calendar":
        as_of = business_today(state)
        target = pick_target_week(as_of, data_as_of, week_start)
        weeks = fold_weeks(rows, axis_key, operating, aliases, data_as_of, week_start)
        boundary = data_as_of
    else:
        target = pick_target_window_rolling(effective_data_as_of)
        weeks = fold_rolling_windows(rows, axis_key, operating, aliases, effective_data_as_of)
        boundary = effective_data_as_of

    weeks = [w for w in weeks if w["week_start"] <= target["week_start"].isoformat()]
    weeks = weeks[-history_weeks:]
    if len(weeks) < 4 or not weeks or weeks[-1]["week_start"] != target["week_start"].isoformat():
        return _disable(
            f"insufficient complete {window_mode} windows up to the target window",
            {"complete_windows": len(weeks), "target_week": target["week_start"].isoformat(),
             "operating_days": sorted(operating), "window_mode": window_mode})

    win_lo = min(_as_date(r.get(axis_key)) for r in rows if _as_date(r.get(axis_key)))
    missing = _missing_expected(rows, axis_key, weeks, operating)
    population = [str(v) for v in state.get("insight_comparable_population", []) or []]
    coverage_kind = "recent_week_history" if window_mode == "calendar" else "recent_week_rolling_history"
    hint = {
        "source": "metadata_template",
        "coverage_kind": coverage_kind,
        "grouping": [{"reference": "[week_start]", "column": "week_start", "table": ""}],
        "metrics": specs,
        "population_status": "comparable" if population else "unfiltered",
        "population_codes": list(population),
        "entity_dimension": shape.get("entity"),
        "topn": None,
        "sort": {"alias": "week_start", "direction": "ASC"},
        "time_window": coverage_kind,
        "date_axis": axis_reference,
        "axis": "week_start",
        "window_start": win_lo.isoformat(),
        "window_end": boundary.isoformat(),
        "day_limit": len(rows),
        "missing_expected_dates": missing,
        "week_start": target["week_start"].isoformat(),
        "week_end": target["week_end"].isoformat(),
    }
    table = {"query_name": "meta_recent_week_history", "status": "success",
             "purpose": f"Comparable {window_mode} series folded from {axis_reference} "
                        f"(recent-week level, {len(weeks)} complete windows).",
             "rows": weeks, "dax": "(folded in Python from the comparable daily series)",
             "contract_hint": hint}

    clean = state.get("insight_clean_data", {"queries": []})
    queries = list(clean.get("queries", []))
    queries.append(table)
    clean_out = {"query_count": len(queries),
                 "successful": int(clean.get("successful", 0)) + 1,
                 "failed": clean.get("failed", 0), "queries": queries}
    file_io.write_json(state, "insight_clean_data.json", clean_out)

    dim = next((d for d in (profile.get("time_dimensions") or [])
               if d.get("reference") == axis_reference), {"reference": axis_reference})
    drivers = _run_driver_drill(state, profile, shape, dim, target, log)
    rest_calls = 1 if drivers else 0

    verdict = {
        "enabled": True, "level": "recent_week", "axis": axis_reference,
        "window_mode": window_mode,
        "week_start": target["week_start"].isoformat(), "week_end": target["week_end"].isoformat(),
        "prev_start": target["prev_start"].isoformat(), "data_as_of": data_as_of.isoformat(),
        "effective_data_as_of": effective_data_as_of.isoformat(),
        "operating_days": sorted(operating), "history_weeks_used": len(weeks),
        "missing_expected_dates": missing, "drivers": drivers,
        "rest_calls": rest_calls,
        "reason": (f"validated business-date axis {axis_reference}; "
                   f"target window {target['week_start'].isoformat()}..{target['week_end'].isoformat()}"),
    }
    file_io.write_json(state, "insight_recent_week_verdict.json", verdict)
    log.info(f"Recent-week gate ({window_mode}): using {axis_reference} - target window "
             f"{target['week_start'].isoformat()}..{target['week_end'].isoformat()} "
             f"({len(weeks)} complete windows, {rest_calls} REST call(s)).")

    updates = {"insight_clean_data": clean_out, "insight_recent_week_verdict": verdict}
    if drivers:
        updates["insight_recent_week_drivers"] = drivers
    return {**updates, **log.updates()}


def _run_driver_drill(state: dict, profile: dict, shape: dict, dim: dict, target: dict,
                      log: RunLogger) -> dict:
    """Bounded target-vs-previous-window breakdown by the metadata primary
    dimension. Best-effort; returns {} on any problem. Honestly flags truncation."""
    dims = shape.get("dimensions") or []
    primary_dim = dims[0] if dims else None
    if not primary_dim:
        return {}
    max_rows = int(state.get("insight_week_driver_rows", 30))
    scan = build_recent_week_driver_scan(
        profile, state, dim, primary_dim,
        (target["week_start"], target["week_end"]),
        (target["prev_start"], target["prev_end"]), max_rows)
    if not scan:
        return {}
    reasons = validate_one(scan["dax"], state.get("model_metadata", {}))
    reasons += validate_comparable_scope(scan["dax"], state, scan.get("contract_hint"))
    if reasons:
        log.info(f"  recent-week driver scan skipped (invalid): {'; '.join(reasons)[:120]}")
        return {}
    try:
        res = pbi.execute_python(state["workspace_id"], state["dataset_id"], [scan],
                                 token=state.get("pbi_token"))
    except Exception as exc:  # noqa: BLE001
        log.info(f"  recent-week driver scan error: {exc}")
        return {}
    item = res.get(scan["name"], {})
    if item.get("status") != "success":
        return {}
    drows = clean_rows(pbi.extract_rows(item.get("result", {})))
    seg_col = primary_dim.get("column")
    segs = [(str(_row_value(r, seg_col)), _row_value(r, "week_change")) for r in drows]
    segs = [(s, c) for s, c in segs if _is_num(c)]
    if not segs:
        return {}
    total = sum(c for _, c in segs) or 0.0
    top = sorted(segs, key=lambda sc: abs(sc[1]), reverse=True)[
        : int(state.get("insight_period_drill_top", 3))]
    top_segments = [{"segment": s, "change": round(float(c), 2),
                     "share_pct": (round(c / total * 100.0, 2) if total else None)}
                    for s, c in top]
    return {
        "dimension": primary_dim.get("reference"),
        "week_start": target["week_start"].isoformat(),
        "week_end": target["week_end"].isoformat(),
        "top_segments": top_segments,
        "truncated": len(drows) >= max_rows,
    }
