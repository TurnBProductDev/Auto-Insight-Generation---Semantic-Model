"""Insight branch - shared business-day source (Phase 3/3b, deterministic).

The one REST fetch and all axis validation that both ``insight_recent_week``
(weekly/rolling folding) and ``insight_daily`` (daily anomaly incidents) need.
This used to live inside ``insight_recent_week.py``, but that made daily
monitoring collapse whenever weekly monitoring was disabled or failed for a
reason that had nothing to do with axis validity (e.g. "insufficient complete
weeks"). Extracting it here means each consumer can fail or disable
independently - both just read ``state["insight_business_day_source"]``.

Runs after the temporal grain gate and before both ``insight_recent_week`` and
``insight_daily``. Validates a business-date axis (batch/load reject, proven
additivity via a windowed reconciliation, adequate density, true Date grain -
no timestamps), trying up to ``insight_week_max_date_probes`` ranked date
dimensions, and refuses stale data (``insight_week_max_data_lag_days``) with a
clear reason.

Also resolves ``effective_data_as_of``: the true ``data_as_of`` rolled back to
the previous *operating* day when it equals "business today" and
``insight_daily_exclude_today`` is set - so a still-loading current day never
leaks into a rolling window's sum or a daily incident's last day. Consumers
that need this trimming (rolling folding, daily detection, daily cursor
advancement) use ``effective_data_as_of``; calendar-week folding keeps using
the true ``data_as_of`` (trimming would wrongly skip an already-complete
preceding week).

Runs if EITHER ``insight_recent_week_enabled`` or ``insight_daily_enabled`` is
true, so disabling one consumer never starves the other of the fetch it
needs. Everything here is best-effort: any failure disables the source; it
never raises into the run. Executes with the pre-fetched ``state["pbi_token"]``
(post-fork safe).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger
from .dax_validator import validate_one
from .insight_scan_templates import (
    build_daily_series_scan,
    build_windowed_total,
    current_additive_specs,
    shape_from_profile,
)
from .insight_temporal import _is_date_dim, _max_bucket_share, _row_value
from .scope_validator import validate_comparable_scope


# --- value / date helpers -----------------------------------------------------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _parse_dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day)
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "").strip())
        except ValueError:
            return None
    return None


def _as_date(v):
    dt = _parse_dt(v)
    return dt.date() if dt else None


def _has_time(v) -> bool:
    dt = _parse_dt(v)
    return bool(dt and (dt.hour or dt.minute or dt.second or dt.microsecond))


def _date_key(rows: list) -> str | None:
    """The first column whose non-null values all parse as dates."""
    if not rows:
        return None
    cols: dict = {}
    for r in rows:
        for k in r:
            cols.setdefault(k, []).append(r.get(k))
    for k, vals in cols.items():
        present = [v for v in vals if v is not None]
        if present and all(_parse_dt(v) is not None for v in present):
            return k
    return None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# --- pure, offline-testable logic ---------------------------------------------

def learn_operating_days(rows: list, axis: str, week_start: str = "monday") -> set:
    """Weekdays (Mon=0..Sun=6) present in >=50% of INTERIOR fully covered weeks.
    Excludes the partial oldest/newest boundary weeks of the TOPN window so a
    truncated edge week does not distort the operating pattern. Missing weekends
    stay non-operating; missing expected weekdays make a week incomplete."""
    by_week: dict = {}
    for r in rows:
        d = _as_date(r.get(axis))
        if d is None:
            continue
        by_week.setdefault(_monday(d), set()).add(d.weekday())
    if not by_week:
        return set(range(5))
    keys = sorted(by_week)
    interior = {k: by_week[k] for k in keys[1:-1]} if len(keys) > 2 else by_week
    counts = {wd: 0 for wd in range(7)}
    for wds in interior.values():
        for wd in wds:
            counts[wd] += 1
    n = len(interior) or 1
    operating = {wd for wd, c in counts.items() if c >= 0.5 * n}
    return operating or set(range(5))


def judge_business_date(rows: list, alias: str, axis: str, additive_candidate: bool,
                        window_total, state: dict) -> dict:
    """Deterministic verdict for a candidate business-date axis. Rejects:
    timestamped axes (calendar-day grain required for MVP), batch/load dates (one
    bucket over the batch share = a repeated month-end total), non-additive metrics
    (metadata flag must be True AND the daily sum must reconcile to the same
    windowed total), and sparse axes. Returns {verdict, checks}."""
    checks: dict = {}
    batch_share = float(state.get("insight_temporal_batch_share", 0.5))
    recon_tol = float(state.get("insight_temporal_recon_tolerance_pct", 2.0)) / 100.0

    checks["timestamped"] = any(_has_time(r.get(axis)) for r in rows)
    if checks["timestamped"]:
        return {"verdict": "timestamped_axis", "checks": checks}

    share = _max_bucket_share(rows, alias)
    checks["max_bucket_share"] = share
    if share is not None and share > batch_share:
        return {"verdict": "batch_load_date", "checks": checks}

    checks["additive_candidate"] = bool(additive_candidate)
    daily_vals = [_row_value(r, alias) for r in rows]
    daily_sum = sum(v for v in daily_vals if _is_num(v))
    checks["daily_sum"] = round(daily_sum, 4)
    checks["window_total"] = round(window_total, 4) if _is_num(window_total) else None
    reconciled = (not _is_num(window_total)
                  or abs(daily_sum - window_total) <= recon_tol * max(abs(window_total), 1.0))
    checks["reconciled"] = reconciled
    if not additive_candidate or not reconciled:
        return {"verdict": "non_additive_metric", "checks": checks}

    dates = sorted({d for d in (_as_date(r.get(axis)) for r in rows) if d is not None})
    checks["distinct_days"] = len(dates)
    if len(dates) < 14:
        return {"verdict": "insufficient_density", "checks": checks}
    return {"verdict": "ok", "checks": checks}


def business_today(state: dict) -> date:
    """"Business today" - the override date if given, else today's date resolved
    in ``insight_business_timezone`` (naive uses the local system date)."""
    override = _as_date(state.get("insight_now_override"))
    if override is not None:
        return override
    tz = str(state.get("insight_business_timezone", "naive") or "naive").strip()
    if tz.lower() == "naive":
        return date.today()
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(tz)).date()


def effective_data_as_of(data_as_of: date, today: date, operating_days: set,
                         exclude_today: bool) -> date:
    """``data_as_of`` rolled back to the previous operating day when it equals
    "business today" and exclusion is enabled - a still-loading current day
    should never anchor a rolling window or a daily incident's last day. Bounded
    to 14 days back so a degenerate ``operating_days`` can never loop forever."""
    if not exclude_today or data_as_of != today:
        return data_as_of
    d = data_as_of - timedelta(days=1)
    steps = 0
    while d.weekday() not in operating_days and steps < 13:
        d -= timedelta(days=1)
        steps += 1
    return d


# --- graph node ---------------------------------------------------------------

def run(state: dict) -> dict:
    log = RunLogger(state)

    def _disable(reason: str, extra: dict | None = None) -> dict:
        verdict = {"enabled": False, "reason": reason}
        if extra:
            verdict.update(extra)
        file_io.write_json(state, "insight_business_day_verdict.json", verdict)
        log.info(f"Business-day source: disabled - {reason}.")
        return {"insight_business_day_verdict": verdict, **log.updates()}

    if not (state.get("insight_recent_week_enabled", True)
            or state.get("insight_daily_enabled", True)):
        return _disable("both recent-week and daily monitoring disabled by config")

    # Timezone: MVP buckets at day granularity. Reject "auto"/unsupported LOUDLY
    # instead of silently treating it as naive.
    tz = str(state.get("insight_business_timezone", "naive") or "naive").strip()
    if tz.lower() == "auto":
        return _disable("timezone 'auto' is not supported; set a specific IANA zone or 'naive'")
    if tz.lower() != "naive":
        try:
            from zoneinfo import ZoneInfo  # noqa: F401
            ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            return _disable(f"unsupported timezone '{tz}'; use an IANA zone or 'naive'")

    profile = state.get("semantic_model_profile", {}) or {}
    shape = shape_from_profile(profile, state)
    specs = current_additive_specs(shape) if shape else []
    if not shape or not specs:
        return _disable("no additive primary value metric available")
    value_spec = specs[0]
    aliases = [s["alias"] for s in specs]
    primary_additive = bool(value_spec.get("additive_candidate"))

    week_start = str(state.get("insight_week_start", "monday")).lower()
    max_probes = max(1, int(state.get("insight_week_max_date_probes", 3)))
    history_weeks = max(4, int(state.get("insight_week_history_weeks", 13)))
    n_days = history_weeks * 7 + 14
    max_lag = int(state.get("insight_week_max_data_lag_days", 7))
    as_of = business_today(state)

    override = str(state.get("insight_business_date_override") or "").strip()
    time_dims = [d for d in (profile.get("time_dimensions") or []) if _is_date_dim(d)]
    if override:
        cands = [d for d in time_dims
                 if d.get("reference") == override or d.get("column") == override]
        if not cands:
            return _disable(f"business date override '{override}' not found among date dimensions")
    else:
        cands = sorted(time_dims,
                       key=lambda d: (d.get("score", 0), d.get("table") == profile.get("fact_table")),
                       reverse=True)[:max_probes]
    if not cands:
        return _disable("model exposes no date dimension for business-day monitoring")

    rest_calls = 0
    checks_by_dim: list = []
    chosen = None
    for dim in cands:
        scan = build_daily_series_scan(profile, state, dim, n_days)
        if not scan:
            checks_by_dim.append({"axis": dim.get("reference"), "verdict": "no_scan"})
            continue
        reasons = validate_one(scan["dax"], state.get("model_metadata", {}))
        reasons += validate_comparable_scope(scan["dax"], state, scan.get("contract_hint"))
        if reasons:
            checks_by_dim.append({"axis": dim.get("reference"), "verdict": "invalid_dax",
                                  "reason": "; ".join(reasons)[:160]})
            if override:
                return _disable(f"override axis '{override}' produced invalid DAX",
                                {"checks": checks_by_dim, "rest_calls": rest_calls})
            continue
        try:
            rest_calls += 1
            res = pbi.execute_python(state["workspace_id"], state["dataset_id"], [scan],
                                     token=state.get("pbi_token"))
        except Exception as exc:  # noqa: BLE001
            checks_by_dim.append({"axis": dim.get("reference"), "verdict": "exec_error",
                                  "reason": str(exc)[:160]})
            if override:
                return _disable(f"override axis '{override}' failed to execute",
                                {"checks": checks_by_dim, "rest_calls": rest_calls})
            continue
        item = res.get(scan["name"], {})
        if item.get("status") != "success":
            checks_by_dim.append({"axis": dim.get("reference"), "verdict": "exec_failed",
                                  "reason": str(item.get("error"))[:160]})
            if override:
                return _disable(f"override axis '{override}' query failed",
                                {"checks": checks_by_dim, "rest_calls": rest_calls})
            continue
        rows = clean_rows(pbi.extract_rows(item.get("result", {})))
        axis_key = _date_key(rows) or dim.get("column")
        rows = [r for r in rows if _as_date(r.get(axis_key)) is not None]
        dates = [d for d in (_as_date(r.get(axis_key)) for r in rows) if d is not None]
        if not dates:
            checks_by_dim.append({"axis": dim.get("reference"), "verdict": "no_dates"})
            if override:
                return _disable(f"override axis '{override}' returned no dates",
                                {"checks": checks_by_dim, "rest_calls": rest_calls})
            continue
        data_as_of = max(dates)
        lag = (as_of - data_as_of).days
        if lag > max_lag:
            checks_by_dim.append({"axis": dim.get("reference"), "verdict": "stale",
                                  "data_as_of": data_as_of.isoformat(), "lag_days": lag})
            if override:
                return _disable(
                    f"Business-day monitoring unavailable: data is only available "
                    f"through {data_as_of.isoformat()}.",
                    {"checks": checks_by_dim, "rest_calls": rest_calls})
            continue

        # Additivity reconciliation over the exact scanned window.
        window_total = None
        wt = build_windowed_total(profile, state, dim, min(dates), data_as_of)
        if wt and not validate_one(wt["dax"], state.get("model_metadata", {})):
            try:
                rest_calls += 1
                wres = pbi.execute_python(state["workspace_id"], state["dataset_id"], [wt],
                                          token=state.get("pbi_token"))
                wi = wres.get(wt["name"], {})
                if wi.get("status") == "success":
                    wrows = clean_rows(pbi.extract_rows(wi.get("result", {})))
                    if wrows:
                        window_total = _row_value(wrows[0], "window_total")
            except Exception as exc:  # noqa: BLE001
                log.info(f"  window-total probe error: {exc}")

        judged = judge_business_date(rows, value_spec["alias"], axis_key, primary_additive,
                                     window_total, state)
        checks_by_dim.append({"axis": dim.get("reference"), "data_as_of": data_as_of.isoformat(),
                              **judged["checks"], "verdict": judged["verdict"]})
        if judged["verdict"] != "ok":
            if override:
                return _disable(f"override axis '{override}' unsuitable: {judged['verdict']}",
                                {"checks": checks_by_dim, "rest_calls": rest_calls})
            continue
        chosen = {"dim": dim, "rows": rows, "axis_key": axis_key, "data_as_of": data_as_of}
        break

    if not chosen:
        return _disable("no valid business-date axis for monitoring (or data is stale)",
                        {"checks": checks_by_dim,
                         "tried_dims": [d.get("reference") for d in cands],
                         "rest_calls": rest_calls})

    dim, rows = chosen["dim"], chosen["rows"]
    axis_key, data_as_of = chosen["axis_key"], chosen["data_as_of"]
    operating = learn_operating_days(rows, axis_key, week_start)
    exclude_today = bool(state.get("insight_daily_exclude_today", True))
    eff = effective_data_as_of(data_as_of, as_of, operating, exclude_today)

    source = {
        "axis_key": axis_key, "axis_reference": dim.get("reference"),
        "value_alias": value_spec["alias"], "additive_aliases": aliases,
        "rows": rows, "operating_days": sorted(operating),
        "data_as_of": data_as_of.isoformat(),
        "effective_data_as_of": eff.isoformat(),
    }
    verdict = {
        "enabled": True, "axis": dim.get("reference"),
        "data_as_of": data_as_of.isoformat(), "effective_data_as_of": eff.isoformat(),
        "tried_dims": [d.get("reference") for d in cands], "rest_calls": rest_calls,
        "checks": checks_by_dim,
        "reason": f"validated business-date axis {dim.get('reference')}",
    }
    file_io.write_json(state, "insight_business_day_verdict.json", verdict)
    log.info(f"Business-day source: using {dim.get('reference')} - data_as_of="
             f"{data_as_of.isoformat()} effective={eff.isoformat()} ({rest_calls} REST call(s)).")
    return {"insight_business_day_source": source, "insight_business_day_verdict": verdict,
            **log.updates()}
