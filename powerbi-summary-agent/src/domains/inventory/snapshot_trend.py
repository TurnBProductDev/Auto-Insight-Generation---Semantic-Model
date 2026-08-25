"""Day-over-day and robust-statistical detection for single-snapshot inventory
reports, built on the pipeline's own archive (`archive.py`) since the semantic
model retains none.

Two honesty rules carried over from every other temporal feature in this
codebase (Phase 2/3/3b's own gates, applied here to a stock position instead
of a sales period):

1. A comparison against a stale or backwards-moving position is refused, not
   silently produced - `archive.compare_window` already decides this, and
   this module trusts its verdict rather than re-deciding.
2. A robust statistic needs a real distribution to be robust ABOUT. Below
   `min_history_days` of genuinely distinct archived positions, this module
   reports day-over-day movement only and says plainly that a statistical
   read needs more history - it never computes a z-score on two points and
   calls it robust.
"""

from __future__ import annotations

import hashlib
import json
import statistics as _stats
from pathlib import Path
from typing import Callable

from . import archive

Extractor = Callable[[dict], list[tuple[str, float]]]

#: Below this many distinct archived days (the current one plus history), a
#: z-score is not computed - it would be a statistic in name only.
DEFAULT_MIN_HISTORY_DAYS = 5

#: A move must clear a share-of-total floor OR (once enough history exists) a
#: z-cutoff - the same dual-gate Phase 3's recent-week detector uses, so a
#: huge z on a trivial move is not reported on its own, but a big move is
#: never held hostage to a still-accumulating history.
DEFAULT_MATERIALITY_PCT = 3.0
DEFAULT_Z_CUTOFF = 2.5


def _clean_key(key: object) -> str:
    return str(key).strip("[]").split("[")[-1].strip("]").lower()


def _read(row: dict, name: str):
    wanted = str(name or "").lower()
    for key, value in (row or {}).items():
        if _clean_key(key) == wanted:
            return value
    return None


def series_extractor(block: str, member_key: str, value_key: str) -> Extractor:
    """Build an extractor reading `scan[block]` as a list of (member, value)."""
    def extract(scan: dict) -> list[tuple[str, float]]:
        rows = scan.get(block) or []
        out = []
        for row in rows:
            member = _read(row, member_key)
            value = _read(row, value_key)
            if member is None or not isinstance(value, (int, float)):
                continue
            out.append((str(member), float(value)))
        return out
    return extract


def _history(output_dir, cfg, extractor: Extractor,
            *, run_date=None) -> list[tuple[str, dict[str, float]]]:
    """Every archived day's series, oldest first, as (iso_date, {member: value})."""
    out = []
    for day, path in archive.archived_runs(output_dir, cfg):
        if run_date is not None and day > run_date:
            continue
        try:
            scan = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        series = dict(extractor(scan))
        if series:
            out.append((day.isoformat(), series))
    return out


def _robust_z(values: list[float], point: float) -> float | None:
    """Median/MAD-based z. None when the reference is flat (MAD == 0) -
    undefined, not zero, the same distinction Phase 3's detector makes."""
    if len(values) < 2:
        return None
    median = _stats.median(values)
    mad = _stats.median([abs(v - median) for v in values])
    if mad == 0:
        return None
    # 0.6745 rescales MAD to be comparable to a standard deviation under
    # normality - the standard robust-z construction.
    return (point - median) * 0.6745 / mad


def _story_key(report_id: str, metric: str, member: str, as_at: str) -> str:
    blob = json.dumps([report_id, "trend", metric, member, as_at], separators=(",", ":"))
    return "trend:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _fmt(value: float, currency: str, money: bool) -> str:
    if not money:
        return f"{value:,.1f}"
    prefix = f"{currency} " if currency else ""
    if abs(value) >= 1_000_000:
        return f"{prefix}{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{prefix}{value / 1_000:.0f}K"
    return f"{prefix}{value:,.0f}"


def detect(current_scan: dict, output_dir: str | Path, cfg: dict, *,
          report_id: str, metric: str, extractor: Extractor,
          comparison: dict, currency: str = "", run_date=None,
          min_history_days: int = DEFAULT_MIN_HISTORY_DAYS,
          materiality_pct: float = DEFAULT_MATERIALITY_PCT,
          z_cutoff: float = DEFAULT_Z_CUTOFF,
          money: bool = True) -> dict:
    """Day-over-day and (once enough history exists) robust-z findings for one
    tracked metric.

    ``comparison`` is `archive.compare_window`'s own verdict, computed once by
    the caller and passed in - this module never re-decides whether today may
    be compared, it only reads the answer.

    Returns ``{"verdict": {...honest state...}, "findings": [...]}`` -
    ``findings`` is empty (never fabricated) whenever the verdict says the
    comparison, or the statistics, are not yet available.
    """
    verdict = {
        "metric": metric, "comparable": bool(comparison.get("comparable")),
        "reason_text": comparison.get("reason_text"), "history_days": 0,
        "statistical": False, "min_history_days": min_history_days,
    }
    if not comparison.get("comparable"):
        return {"verdict": verdict, "findings": []}

    history = _history(output_dir, cfg, extractor, run_date=run_date)
    verdict["history_days"] = len(history)
    if len(history) < 1:
        return {"verdict": verdict, "findings": []}

    current_series = dict(extractor(current_scan))
    as_at = comparison.get("as_at") or ""
    prior_as_at, prior_series = history[-1]
    total = sum(abs(v) for v in current_series.values()) or 1.0
    statistical = len(history) >= min_history_days
    verdict["statistical"] = statistical

    findings = []
    for member, value in current_series.items():
        before = prior_series.get(member)
        if before is None:
            continue
        change = value - before
        if not change:
            continue
        share = abs(change) / total * 100.0

        z = None
        if statistical:
            series_values = [s[member] for _, s in history if member in s]
            if len(series_values) >= min_history_days:
                z = _robust_z(series_values, value)

        materially_significant = share >= materiality_pct
        statistically_significant = z is not None and abs(z) >= z_cutoff
        if not (materially_significant or statistically_significant):
            continue

        if z is not None:
            basis = f", robust z={z:+.1f}"
        elif not statistical:
            basis = (f" (not enough history for a statistical read yet, "
                     f"{len(history)} of {min_history_days} day(s))")
        else:
            basis = ""

        findings.append({
            "candidate_id": f"trend:{metric}:{member}",
            "story_key": _story_key(report_id, metric, member, as_at),
            "report_id": report_id,
            "analysis_type": f"{metric}_trend_movement",
            "dimension": metric,
            "affected_segment": member,
            "segment_members": [member],
            "metric": metric,
            "current": value,
            "prior": before,
            "impact_value": change,
            "impact_share": share,
            "score": share + (abs(z) * 10 if z is not None else 0.0),
            "severity": "critical" if change < 0 and share >= materiality_pct * 2 else "warning",
            "comparison_label": f"since {prior_as_at}",
            "description": (f"{member} moved {_fmt(change, currency, money)} since "
                           f"{prior_as_at} ({'up' if change > 0 else 'down'} from "
                           f"{_fmt(before, currency, money)} to "
                           f"{_fmt(value, currency, money)}){basis}."),
        })

    findings.sort(key=lambda f: (-float(f.get("score") or 0.0), f["candidate_id"]))
    return {"verdict": verdict, "findings": findings}
