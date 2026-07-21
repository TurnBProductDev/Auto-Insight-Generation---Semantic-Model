"""Insight branch - daily anomaly incidents (Phase 3b, deterministic).

Runs after ``insight_recent_week`` and reuses the SAME validated daily source
``insight_business_day_source`` already fetched - no new REST calls, no new
gate logic. Answers "which exact days were abnormal?" by flagging individual
days against two independent references (a trailing rolling window and, when
enough history exists, the same weekday's own history), merging consecutive
same-direction abnormal days (bridging a closed weekend) into ONE incident,
and scoring each. A recency filter, applied once here, keeps the very first
run for an axis from dumping the whole fetched window as if it were all new.

Independent of ``insight_recent_week_enabled`` - if weekly monitoring is off,
or fails for a weekly-specific reason (e.g. "insufficient complete weeks"),
daily anomaly detection is unaffected; it only cares whether
``insight_business_day_source`` itself validated an axis.

Deterministic, no LLM. Best-effort: any failure disables the level; it never
raises into the run. No REST calls of its own.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..tools import file_io
from ..tools import insight_memory as mem
from ..utils.logger import RunLogger
from .insight_business_day_source import _as_date, _is_num
from .insight_stat_detector import _point_robust_z

_EPS = 1e-9


# --- pure, offline-testable logic ---------------------------------------------

def _test_reference(value, ref: list, z_cutoff: float, materiality_pct: float):
    """(passed, direction) for ONE reference, or None if the reference is too
    small to judge (fewer than 3 points). A *variable* reference (robust z
    defined) must clear BOTH the z-cutoff AND materiality vs its own median. A
    *flat* reference (z undefined - the MAD/std are both ~0) is judged on
    materiality alone, since a z-score there would be infinite/undefined; this
    is what lets a break from an otherwise-identical history register."""
    ref = [v for v in ref if _is_num(v)]
    if len(ref) < 3 or not _is_num(value):
        return None
    med = sorted(ref)[len(ref) // 2]
    z = _point_robust_z(value, ref)
    dev_pct = abs(value - med) / (abs(med) + _EPS) * 100.0
    passed = ((abs(z) >= z_cutoff and dev_pct >= materiality_pct) if z is not None
              else dev_pct >= materiality_pct)
    direction = 1 if value > med else (-1 if value < med else 0)
    return (bool(passed), direction)


def flag_abnormal_days(rows: list, axis: str, value_alias: str, rolling_window: int,
                       min_weekday_occ: int, z_cutoff: float, materiality_pct: float,
                       effective_data_as_of: date | None) -> list:
    """Flags abnormal days over the FULL fetched window (after a
    ``rolling_window``-day warm-up) - recency filtering happens later, in
    ``run()``, so an incident's identity never drifts as old days age out of a
    window. The same-weekday reference for day D is built ONLY from PRIOR
    same-weekday observations (never a look-ahead) - history is appended
    AFTER a day is evaluated, never before.

    Combining the two references is AND, not OR: if both are available, the
    day is abnormal only when BOTH clear their own test and agree in
    direction - this is what stops a systematic weekend low (the trailing
    reference fires against a weekday-heavy mix; the same-weekday reference
    correctly vetoes it) from being flagged. If same-weekday history is
    insufficient, the trailing test alone decides.
    """
    series = sorted(
        ((_as_date(r.get(axis)), r.get(value_alias)) for r in rows
         if _as_date(r.get(axis)) is not None and _is_num(r.get(value_alias))),
        key=lambda kv: kv[0])
    if effective_data_as_of is not None:
        series = [(d, v) for d, v in series if d <= effective_data_as_of]

    by_weekday: dict = {}  # weekday -> [(date, value), ...] seen so far (prior only)
    flagged: list = []
    for i, (d, v) in enumerate(series):
        wd = d.weekday()
        if i >= rolling_window:
            trailing_vals = [vv for _, vv in series[i - rolling_window:i]]
            same_wd_hist = by_weekday.get(wd, [])
            same_wd_vals = [vv for _, vv in same_wd_hist]

            trailing_result = _test_reference(v, trailing_vals, z_cutoff, materiality_pct)
            weekday_result = (_test_reference(v, same_wd_vals, z_cutoff, materiality_pct)
                              if len(same_wd_vals) >= min_weekday_occ else None)

            if trailing_result is not None:
                t_pass, t_dir = trailing_result
                if weekday_result is not None:
                    w_pass, w_dir = weekday_result
                    abnormal = t_pass and w_pass and t_dir == w_dir
                    direction = t_dir
                    expected = sorted(same_wd_vals)[len(same_wd_vals) // 2]
                else:
                    abnormal = t_pass
                    direction = t_dir
                    expected = sorted(trailing_vals)[len(trailing_vals) // 2]
                if abnormal and direction != 0:
                    flagged.append({
                        "date": d, "value": v, "direction": direction, "expected": expected,
                        "z": _point_robust_z(v, trailing_vals),
                    })
        by_weekday.setdefault(wd, []).append((d, v))
    return flagged


def merge_incidents(flagged: list, operating_days: set) -> list:
    """Collapse consecutive same-direction abnormal days into ONE incident.
    "Consecutive" is under the OPERATING-day definition: a gap consisting only
    of non-operating weekdays (e.g. a closed Sat/Sun) still merges, so a
    Friday+Monday dip bridging a closed weekend is one business incident, not
    two."""
    if not flagged:
        return []
    flagged = sorted(flagged, key=lambda f: f["date"])
    groups = [[flagged[0]]]
    for f in flagged[1:]:
        prev = groups[-1][-1]
        gap_days = (f["date"] - prev["date"]).days
        bridges_only_closed_days = all(
            (prev["date"] + timedelta(days=k)).weekday() not in operating_days
            for k in range(1, gap_days))
        if f["direction"] == prev["direction"] and bridges_only_closed_days:
            groups[-1].append(f)
        else:
            groups.append([f])

    out = []
    for days in groups:
        actual_total = sum(day["value"] for day in days)
        expected_total = sum(day["expected"] for day in days)
        zs = [abs(day["z"]) for day in days if day["z"] is not None]
        out.append({
            "episode_start": days[0]["date"].isoformat(),
            "episode_end": days[-1]["date"].isoformat(),
            "direction": days[0]["direction"],
            "peak_z": max(zs) if zs else 0.0,
            "day_count": len(days),
            "actual_total": actual_total,
            "expected_total": expected_total,
            "cumulative_impact": actual_total - expected_total,
            "per_day": [{"date": day["date"].isoformat(), "value": day["value"],
                        "expected": day["expected"], "z": day["z"]} for day in days[:14]],
        })
    return out


def score_incident(incident: dict) -> float:
    """Percent-deviation-from-expected, analogous to ``recent_week``'s
    ``score = abs(change_pct)`` (insight_stat_detector.py) - a normalized
    materiality measure comparable across metrics/magnitudes."""
    expected_total = incident.get("expected_total") or 0.0
    impact = incident.get("cumulative_impact") or 0.0
    return abs(impact) / (abs(expected_total) + _EPS) * 100.0


# --- graph node ---------------------------------------------------------------

def run(state: dict) -> dict:
    log = RunLogger(state)

    def _disable(reason: str, extra: dict | None = None) -> dict:
        verdict = {"enabled": False, "level": "daily", "reason": reason,
                  "analysis_complete": False}
        if extra:
            verdict.update(extra)
        file_io.write_json(state, "insight_daily_verdict.json", verdict)
        log.info(f"Daily anomaly gate: disabled - {reason}.")
        return {"insight_daily_verdict": verdict, **log.updates()}

    if not state.get("insight_daily_enabled", True):
        return _disable("daily anomaly monitoring disabled by config")

    source = state.get("insight_business_day_source")
    if not source:
        bd_verdict = state.get("insight_business_day_verdict", {}) or {}
        reason = bd_verdict.get("reason", "no valid business-date axis available")
        return _disable(f"disabled - same reason as business-day source: {reason}")

    axis_key = source["axis_key"]
    axis_reference = source["axis_reference"]
    value_alias = source["value_alias"]
    rows = source["rows"]
    operating = set(source["operating_days"])
    effective_data_as_of = _as_date(source["effective_data_as_of"])

    rolling_window = max(7, int(state.get("insight_daily_rolling_window", 28)))
    min_weekday_occ = max(1, int(state.get("insight_daily_min_weekday_occurrences", 3)))
    z_cutoff = float(state.get("insight_daily_z_cutoff", 3.0))
    materiality_pct = float(state.get("insight_daily_materiality_pct", 3.0))
    recent_days = max(0, int(state.get("insight_daily_recent_days", 3)))

    try:
        flagged = flag_abnormal_days(rows, axis_key, value_alias, rolling_window,
                                     min_weekday_occ, z_cutoff, materiality_pct,
                                     effective_data_as_of)
        incidents = merge_incidents(flagged, operating)
        for inc in incidents:
            inc["score"] = score_incident(inc)
            inc["metric"] = value_alias
            inc["axis"] = axis_reference
            inc["segment"] = f"{axis_reference}={inc['episode_start']}"
    except Exception as exc:  # noqa: BLE001 - detection must never kill the run
        log.error(f"Daily anomaly detection failed ({exc}).")
        return _disable(f"internal error during detection: {exc}")

    # Recency filter (applied once, here, before rows ever reach the stat
    # detector - no second pass anywhere downstream). A plain read of the
    # store - no lock needed - same pattern insight_novelty_filter.py uses.
    memory_store, mem_status = mem.load_store(state)
    previous_cursor = ((memory_store.get("daily_cursor", {}) or {}).get(axis_reference)
                       if mem_status != "corrupt" else None)
    floor = (effective_data_as_of - timedelta(days=recent_days)).isoformat()
    eligible = [
        inc for inc in incidents
        if (previous_cursor is not None and inc["episode_end"] > previous_cursor)
        or (inc["episode_end"] >= floor)
    ]

    dates_present = [_as_date(r.get(axis_key)) for r in rows if _as_date(r.get(axis_key))]
    win_lo = min(dates_present) if dates_present else None
    hint = {
        "source": "metadata_template",
        "coverage_kind": "daily_incidents",
        "grouping": [{"reference": f"[{axis_key}]", "column": axis_key, "table": ""}],
        "metrics": [],
        "population_status": "comparable",
        "population_codes": [],
        "entity_dimension": None,
        "topn": None,
        "sort": {"alias": "episode_start", "direction": "ASC"},
        "time_window": "daily_incidents",
        "date_axis": axis_reference,
        "axis": "episode_start",
        "window_start": win_lo.isoformat() if win_lo else None,
        "window_end": effective_data_as_of.isoformat(),
        "day_limit": len(rows),
        "missing_expected_dates": [],
    }
    table = {"query_name": "meta_daily_incidents", "status": "success",
             "purpose": f"Daily anomaly incidents mined from {axis_reference} "
                        f"({len(eligible)} of {len(incidents)} eligible this run).",
             "rows": eligible, "dax": "(detected in Python from the comparable daily series)",
             "contract_hint": hint}

    clean = state.get("insight_clean_data", {"queries": []})
    queries = list(clean.get("queries", []))
    queries.append(table)
    clean_out = {"query_count": len(queries),
                 "successful": int(clean.get("successful", 0)) + 1,
                 "failed": clean.get("failed", 0), "queries": queries}
    file_io.write_json(state, "insight_clean_data.json", clean_out)

    verdict = {
        "enabled": True, "level": "daily", "axis": axis_reference,
        "effective_data_as_of": effective_data_as_of.isoformat(),
        "incidents_found": len(incidents), "incidents_reported": len(eligible),
        "checks": {"rolling_window": rolling_window, "min_weekday_occurrences": min_weekday_occ,
                   "z_cutoff": z_cutoff, "materiality_pct": materiality_pct,
                   "recent_days": recent_days},
        "reason": (f"validated business-date axis {axis_reference}; {len(eligible)} eligible "
                   f"incident(s) of {len(incidents)} detected"),
        "analysis_complete": True,
    }
    file_io.write_json(state, "insight_daily_verdict.json", verdict)
    log.info(f"Daily anomaly gate: using {axis_reference} - {len(eligible)} eligible "
             f"incident(s) of {len(incidents)} detected.")

    return {"insight_clean_data": clean_out, "insight_daily_verdict": verdict, **log.updates()}
