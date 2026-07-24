"""Summary-only reporting-period and freshness resolver.

The insight branch has its own temporal gates. This module deliberately does
not read or mutate them: it resolves the summary context from summary results,
shared baseline evidence, and semantic metadata.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta
from statistics import median

from ..tools import file_io
from ..utils.logger import RunLogger


_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ][^ ]+)?$")
_MONTH_NAMES = {
    name.casefold(): index
    for index, name in enumerate(
        ("january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december"),
        start=1,
    )
}


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
        return None
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _queries(state: dict) -> list[dict]:
    out = []
    clean = state.get("clean_summary_data") or {}
    out.extend(q for q in clean.get("queries", []) or [] if q.get("status") == "success")
    baseline = state.get("baseline_scope_evidence") or {}
    if baseline.get("status") == "success":
        out.append(baseline)
    coverage = state.get("baseline_coverage_clean_data") or {}
    out.extend(q for q in coverage.get("queries", []) or [] if q.get("status") == "success")
    return out


def _date_axes(state: dict) -> tuple[list[dict], list[date]]:
    checks = []
    all_dates: list[date] = []
    batch_share = float(state.get("summary_temporal_batch_share", 0.5))
    for query in _queries(state):
        rows = query.get("rows", []) or []
        if not rows:
            continue
        keys = list(dict.fromkeys(key for row in rows for key in row))
        for key in keys:
            parsed = [_parse_date(row.get(key)) for row in rows]
            dates = [item for item in parsed if item is not None]
            if not dates:
                continue
            all_dates.extend(dates)
            unique = sorted(set(dates))
            numeric_keys = [
                candidate for candidate in keys
                if candidate != key and any(_is_number(row.get(candidate)) for row in rows)
            ]
            metric = next(
                (candidate for candidate in numeric_keys
                 if any(token in candidate.casefold() for token in ("revenue", "sales", "value", "amount"))),
                numeric_keys[0] if numeric_keys else None,
            )
            bucket_share = None
            if metric and len(unique) >= 2:
                totals = {}
                for row, parsed_date in zip(rows, parsed):
                    value = row.get(metric)
                    if parsed_date is not None and _is_number(value):
                        totals[parsed_date] = totals.get(parsed_date, 0.0) + abs(float(value))
                total = sum(totals.values())
                if total:
                    bucket_share = max(totals.values()) / total

            grain = "date"
            if len(unique) >= 3:
                gaps = [(b - a).days for a, b in zip(unique, unique[1:]) if b > a]
                typical = median(gaps) if gaps else 0
                if typical <= 2:
                    grain = "day"
                elif typical <= 10:
                    grain = "week"
                elif typical <= 45:
                    grain = "month"
                elif typical <= 120:
                    grain = "quarter"
                else:
                    grain = "year"
            verdict = "ok"
            if len(unique) < 3:
                verdict = "insufficient_periods"
            elif bucket_share is not None and bucket_share > batch_share and grain == "day":
                verdict = "batch_date"
            checks.append({
                "query": query.get("query_name"),
                "column": key,
                "grain": grain,
                "periods": len(unique),
                "max_bucket_share": bucket_share,
                "verdict": verdict,
            })
    return checks, all_dates


def _metadata_fallback_grain(state: dict, rejected_axes: set[str] | None = None) -> tuple[str, str | None]:
    dims = (state.get("semantic_model_profile") or {}).get("time_dimensions", []) or []
    priorities = (("day", 5), ("week", 4), ("month", 3), ("quarter", 2), ("year", 1))
    rejected = {str(item).casefold() for item in (rejected_axes or set())}
    best = None
    for dim in dims:
        names = {
            str(dim.get("column") or "").casefold(),
            str(dim.get("reference") or "").casefold(),
        }
        if names & rejected:
            continue
        text = f"{dim.get('column', '')} {dim.get('reference', '')}".casefold()
        for grain, priority in priorities:
            if grain in text or (grain == "day" and "date" in text):
                candidate = (priority, grain, dim.get("reference"))
                if best is None or candidate > best:
                    best = candidate
                break
    return (best[1], best[2]) if best else ("snapshot", None)


def _fallback_watermark(state: dict) -> date | None:
    latest = None
    for query in _queries(state):
        for row in query.get("rows", []) or []:
            for value in row.values():
                parsed = _parse_date(value)
                if parsed is not None and (latest is None or parsed > latest):
                    latest = parsed
    return latest


def _today(state: dict) -> date:
    raw = state.get("summary_now_override") or (state.get("config", {}) or {}).get("summary_now_override")
    if raw:
        parsed = _parse_date(str(raw))
        if parsed:
            return parsed
    return date.today()


def _previous_month(value: date) -> tuple[int, int]:
    if value.month == 1:
        return value.year - 1, 12
    return value.year, value.month - 1


def _period_anchor(grain: str, data_as_of: date | None, today: date, signature: str) -> str:
    if data_as_of is None:
        return f"snapshot:{signature[:16]}"
    effective = data_as_of
    if grain == "day" and data_as_of >= today:
        effective = today - timedelta(days=1)
    if grain == "month" and (data_as_of.year, data_as_of.month) >= (today.year, today.month):
        year, month = _previous_month(today)
        return f"{year:04d}-{month:02d}"
    if grain == "year":
        year = data_as_of.year - (1 if data_as_of.year >= today.year else 0)
        return f"{year:04d}"
    if grain == "quarter":
        quarter = (data_as_of.month - 1) // 3 + 1
        current_quarter = (today.month - 1) // 3 + 1
        year = data_as_of.year
        if (year, quarter) >= (today.year, current_quarter):
            quarter -= 1
            if quarter == 0:
                year, quarter = year - 1, 4
        return f"{year:04d}-Q{quarter}"
    if grain == "week":
        iso = effective.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    if grain == "month":
        return effective.strftime("%Y-%m")
    return effective.isoformat()


def _freshness(grain: str, data_as_of: date | None, today: date, state: dict) -> tuple[str, int | None]:
    if data_as_of is None:
        return "unknown", None
    if grain == "day":
        age = max(0, (today - data_as_of).days)
    elif grain == "week":
        age = max(0, (today - data_as_of).days // 7)
    elif grain == "month":
        age = max(0, (today.year - data_as_of.year) * 12 + today.month - data_as_of.month)
    elif grain == "quarter":
        today_q = today.year * 4 + (today.month - 1) // 3
        data_q = data_as_of.year * 4 + (data_as_of.month - 1) // 3
        age = max(0, today_q - data_q)
    elif grain == "year":
        age = max(0, today.year - data_as_of.year)
    else:
        age = max(0, (today - data_as_of).days)
    delayed_after = int(state.get("summary_delayed_after_periods", 1))
    stale_after = int(state.get("summary_stale_after_periods", 2))
    if age > stale_after:
        return "stale", age
    if age > delayed_after:
        return "delayed", age
    return "current", age


def _data_signature(state: dict) -> str:
    compact = []
    for query in _queries(state):
        rows = query.get("rows", []) or []
        compact.append({
            "purpose": query.get("purpose"),
            "rows": rows[:3],
        })
    raw = json.dumps(compact, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resolve(state: dict) -> dict:
    checks, dates = _date_axes(state)
    valid = [check for check in checks if check.get("verdict") == "ok"]
    priority = {"day": 5, "week": 4, "month": 3, "quarter": 2, "year": 1, "date": 0}
    chosen = max(valid, key=lambda item: (priority.get(item.get("grain"), 0), item.get("periods", 0)), default=None)
    if chosen:
        grain = chosen.get("grain") or "snapshot"
        axis = chosen.get("column")
        reason = f"validated {grain} axis from summary evidence"
    else:
        rejected_axes = {
            str(value).casefold()
            for check in checks if check.get("verdict") == "batch_date"
            for value in (check.get("column"), check.get("axis_reference"))
            if value
        }
        grain, axis = _metadata_fallback_grain(state, rejected_axes)
        reason = (
            "metadata fallback after rejecting batch/load date evidence"
            if rejected_axes else
            "metadata fallback; no sufficiently distributed date series in summary evidence"
        )
    watermark = max(dates) if dates else _fallback_watermark(state)
    today = _today(state)
    signature = _data_signature(state)
    anchor = _period_anchor(grain, watermark, today, signature)
    freshness, age = _freshness(grain, watermark, today, state)
    return {
        "grain": grain,
        "axis": axis,
        "data_as_of": watermark.isoformat() if watermark else None,
        "period_anchor": anchor,
        "freshness_status": freshness,
        "age_in_grain_periods": age,
        "today": today.isoformat(),
        "reason": reason,
        "checks": checks,
        "data_signature": signature,
    }


def run(state: dict) -> dict:
    log = RunLogger(state)
    context = resolve(state)
    file_io.write_json(state, "summary_period_context.json", context)
    log.info(
        "Summary period: grain=%s data_as_of=%s anchor=%s freshness=%s."
        % (context["grain"], context.get("data_as_of") or "unknown",
           context["period_anchor"], context["freshness_status"])
    )
    return {"summary_period_context": context, **log.updates()}
