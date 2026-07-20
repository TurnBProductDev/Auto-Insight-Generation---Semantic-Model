"""Persistent, deterministic cross-run insight memory (Phase 1: high level).

The insight branch detects the same top findings on every run. This module gives
it a memory: a per-dataset store of the findings already REPORTED, so a novelty
filter can suppress them and each run surfaces only genuinely unseen findings.

Design contracts (see the plan / CLAUDE.md):

* One authoritative JSON file per dataset - ``insight_memory/<dataset_id>/memory.json``
  - written as a single atomic transaction (temp file + os.replace). ``daily_insights.md``
  is DERIVED from it and may safely lag.
* Identity is a **story_key**: a stable, level-prefixed SHA-256 of canonical JSON
  that EXCLUDES mutable properties (direction, impact, episode end). Mutable
  observations live as record fields so a later phase can re-alert on a reversal or
  a materially larger movement without the key changing. Never a candidate id
  (their ranking-based numbering drifts between runs).
* Fail loud: a corrupt store is reported as ``status="corrupt"`` and never treated
  as empty - callers must not silently overwrite it or repeat everything.

Phase 1 implements the ``high`` level only; weekly/daily story keys and recency
gating are added by later phases (the canon branches on ``level``).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

# .../powerbi-summary-agent/src/tools/insight_memory.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

SCHEMA_VERSION = 1
_WS = re.compile(r"\s+")
_PHASE_TOKENS = re.compile(
    r"(?:^|[_\s])(current|curr|cy|ty|prior|previous|prev|past|ly|py|change|chg|"
    r"growth|grwth|variance|var|delta|diff|difference|yoy|derived)(?=$|[_\s])",
    re.IGNORECASE,
)


# --- paths --------------------------------------------------------------------

def _dataset_dir(state: dict) -> Path:
    ds = str(state.get("dataset_id") or "unknown_dataset")
    # dataset ids are GUIDs, but sanitize defensively for a filesystem path.
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", ds)
    d = PROJECT_ROOT / "insight_memory" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_path(state: dict) -> Path:
    return _dataset_dir(state) / "memory.json"


def markdown_path(state: dict) -> Path:
    return _dataset_dir(state) / "daily_insights.md"


# --- normalization / hashing --------------------------------------------------

def _norm_text(value: Any) -> str:
    """Unicode-NFKC + casefold + whitespace-collapse + strip - so the same segment
    written with different case / spacing / unicode form maps to one story."""
    text = unicodedata.normalize("NFKC", str(value if value is not None else ""))
    return _WS.sub(" ", text).strip().casefold()


def _normalize_segment(candidate: dict) -> list[str]:
    """Authoritative member list of a finding, normalized and sorted. Uses the
    explicit ``segment_members`` when present (multi-segment findings carry it);
    otherwise the single ``segment`` label as one member."""
    members = candidate.get("segment_members")
    if not members:
        seg = candidate.get("segment")
        members = [seg] if seg is not None else []
    return sorted({_norm_text(m) for m in members})


def _strip_phase(alias: Any) -> str:
    """Reduce a measure alias to a phase-agnostic family token so current/prior/
    change members of one family share a canonical metric."""
    text = _norm_text(alias)
    prev = None
    while prev != text:
        prev = text
        text = _PHASE_TOKENS.sub(" ", text)
    return _WS.sub(" ", text).strip() or _norm_text(alias)


def canonical_metric(candidate: dict, contract: dict | None) -> str:
    """Canonical metric = bundle/family from the query's evidence contract when
    available (authoritative), else the phase-stripped alias. NEVER the drifting
    raw alias, so current/prior/change of one family collapse to one story."""
    metric = candidate.get("metric")
    roles = (contract or {}).get("metric_roles") or {}
    role = roles.get(metric) or {}
    canon = role.get("bundle_id") or role.get("family")
    if canon:
        return _norm_text(canon)
    return _strip_phase(metric)


def _dimension(candidate: dict, contract: dict | None) -> list[str]:
    refs = (contract or {}).get("grouping_references") or []
    if refs:
        return sorted(_norm_text(r) for r in refs)
    table = candidate.get("table")
    return [_norm_text(table)] if table else []


def _sign(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return (value > 0) - (value < 0)
    return 0


def scope_hash(state: dict) -> str:
    payload = {
        "comparable": sorted(str(v) for v in state.get("insight_comparable_population", []) or []),
        "excluded": sorted(str(v) for v in state.get("insight_excluded_entities", []) or []),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]


def _hash(canon: dict) -> str:
    blob = json.dumps(canon, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def story_components(candidate: dict, dataset_id: str, scope_h: str,
                     contract: dict | None, period_anchor: str) -> tuple[str, dict]:
    """Return ``(story_key, fields)`` for one candidate.

    ``story_key`` is the stable suppression identity (excludes direction/impact).
    ``fields`` carries both the canonical (stable) parts and the mutable
    ``direction`` so ``commit`` can persist a full record. Phase 1 handles the
    ``high`` level; later phases branch on ``level`` here.
    """
    level = candidate.get("level") or "high"
    metric = canonical_metric(candidate, contract)
    segment = _normalize_segment(candidate)
    analysis_type = _norm_text(candidate.get("type"))
    dimension = _dimension(candidate, contract)

    if level == "period":
        # A period finding is anchored to its period (the month/week itself), not a
        # business dimension. The anchor is IN the key so each period is a distinct
        # story; direction/impact stay mutable for later re-alerting.
        anchor = _norm_text(candidate.get("anchor") or candidate.get("segment"))
        canon = {
            "level": level,
            "dataset": str(dataset_id),
            "scope": scope_h,
            "period_anchor": period_anchor,
            "analysis_type": analysis_type,
            "metric": metric,
            "segment": segment,
            "anchor": anchor,
        }
    else:
        canon = {
            "level": level,
            "dataset": str(dataset_id),
            "scope": scope_h,
            "period_anchor": period_anchor,
            "analysis_type": analysis_type,
            "metric": metric,
            "dimension": dimension,
            "segment": segment,
        }
    key = f"{level}:v1:" + _hash(canon)
    fields = {
        **canon,
        "kind": candidate.get("kind", "business"),
        "direction": _sign(candidate.get("impact_value")),
        "impact_value": candidate.get("impact_value"),
        "segment_label": candidate.get("segment"),
    }
    return key, fields


# --- watermark / period anchor ------------------------------------------------

def _parse_date(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "").strip())
        except ValueError:
            return None
    return None


def derive_watermark(state: dict) -> str | None:
    """Max business date visible in the scanned data - the data's 'as-of' day.

    Used as the period-anchor source for high-level keys (so a new reporting
    period resurfaces its stories) and, in later phases, for recency gating.
    Best-effort: scans normalized scan rows for the latest parseable date.
    """
    latest = None
    sources = [state.get("insight_clean_data"), state.get("baseline_coverage_clean_data")]
    for clean in sources:
        for q in (clean or {}).get("queries", []) if isinstance(clean, dict) else []:
            for row in q.get("rows", []) or []:
                for v in row.values():
                    d = _parse_date(v)
                    if d is not None and (latest is None or d > latest):
                        latest = d
    return latest.date().isoformat() if latest else None


def period_anchor(state: dict, watermark: str | None) -> str:
    """Bucket the watermark to the reporting grain (default month). Stable within a
    period, changes across periods so high-level stories can legitimately resurface.
    Empty when no watermark is derivable (rollover-resurfacing then inactive)."""
    if not watermark:
        return ""
    grain = str(state.get("insight_reporting_grain", "month")).lower()
    if grain == "year":
        return watermark[:4]
    if grain == "day":
        return watermark[:10]
    return watermark[:7]  # month


# --- store I/O (atomic, fail-loud) --------------------------------------------

def _empty_store() -> dict:
    return {"schema_version": SCHEMA_VERSION, "watermark": None, "records": {}, "journal": {}}


def load_store(state: dict) -> tuple[dict, str]:
    """Return ``(memory, status)``. status is 'ok', 'empty' (no file yet), or
    'corrupt'. A corrupt store is NEVER silently treated as empty - the caller
    must refuse to overwrite it and flag the run."""
    path = store_path(state)
    if not path.exists():
        return _empty_store(), "empty"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "records" not in data:
            return _empty_store(), "corrupt"
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("watermark", None)
        data.setdefault("records", {})
        data.setdefault("journal", {})
        return data, "ok"
    except (json.JSONDecodeError, OSError, ValueError):
        return _empty_store(), "corrupt"


def suppressed(records: dict, policy: str, cooldown_days: int,
               today: str | None = None) -> set[str]:
    """Story keys to suppress under the active policy.

    * never_repeat: every reported story, forever.
    * cooldown: only stories reported within ``cooldown_days`` (older ones may
      resurface).
    """
    if policy == "cooldown":
        ref = datetime.fromisoformat(today) if today else datetime.now()
        keep = set()
        for key, rec in records.items():
            last = _parse_date(rec.get("last_reported"))
            if last is not None and (ref - last).days < max(0, int(cooldown_days)):
                keep.add(key)
        return keep
    return set(records.keys())  # never_repeat (default)


def _acquire_lock(path: Path, timeout: float = 5.0):
    """Best-effort exclusive lock file; returns a handle or None. Stale locks
    (older than 60s) are reclaimed. Never blocks the run indefinitely."""
    lock = path.with_suffix(".lock")
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            return (fd, lock)
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 60:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.time() >= deadline:
                return None
            time.sleep(0.1)


def _release_lock(handle) -> None:
    if not handle:
        return
    fd, lock = handle
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        lock.unlink(missing_ok=True)
    except OSError:
        pass


def _atomic_write(path: Path, memory: dict) -> None:
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(memory, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def render_markdown(memory: dict) -> str:
    """Regenerate the human daily feed from the journal (most recent day first)."""
    lines = ["# Daily new insights", ""]
    journal = memory.get("journal", {})
    if not journal:
        lines.append("_No insights reported yet._")
        return "\n".join(lines) + "\n"
    for day in sorted(journal.keys(), reverse=True):
        entries = journal[day] or []
        lines.append(f"## {day}")
        lines.append("")
        if not entries:
            lines.append("- (no new insights)")
        for e in entries:
            impact = e.get("impact_value")
            impact_s = f" (impact {impact:,.0f})" if isinstance(impact, (int, float)) else ""
            tag = f" [{e.get('kind')}]" if e.get("kind") and e.get("kind") != "business" else ""
            lines.append(f"- {e.get('description') or e.get('id')}{impact_s}{tag}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def commit(state: dict, reported_signals: Iterable[dict]) -> dict:
    """Record the findings actually reported this run and refresh the derived
    markdown. Merge-aware: every ``covered_story_keys`` entry of a reported signal
    is marked seen so a merged-away candidate does not reappear tomorrow.

    Caller guards this (memory enabled, report generated, signals exist, store not
    corrupt); we additionally reload fresh and refuse to write onto a store that
    reads corrupt right now.
    """
    reported = [s for s in reported_signals if s]
    path = store_path(state)
    lock = _acquire_lock(path)
    try:
        memory, status = load_store(state)
        if status == "corrupt":
            return {"status": "corrupt", "committed": 0}

        today = date.today().isoformat()
        records = memory["records"]
        journal = memory.setdefault("journal", {})
        day_entries = journal.setdefault(today, [])
        by_key = {e.get("story_key"): e for e in day_entries}

        committed = 0
        for sig in reported:
            primary = sig.get("story_key")
            if not primary:
                continue
            covered = sig.get("covered_story_keys") or [primary]
            for key in covered:
                rec = records.get(key)
                is_primary = key == primary
                if rec is None:
                    rec = {
                        "level": sig.get("level", "high"),
                        "first_reported": today,
                        "times_reported": 0,
                        "re_alert_count": 0,
                    }
                    records[key] = rec
                rec["last_reported"] = today
                rec["times_reported"] = int(rec.get("times_reported", 0)) + 1
                # Full detail on the primary; covered/merged keys keep a light record
                # (enough to suppress them) pointing at the story they were folded into.
                if is_primary:
                    for f in ("kind", "segment", "segment_label", "metric", "dimension",
                              "analysis_type", "period_anchor", "direction", "impact_value",
                              "description"):
                        if sig.get(f) is not None:
                            rec[f] = sig.get(f)
                    rec["covered_story_keys"] = covered
                else:
                    rec.setdefault("merged_into", primary)

            entry = {
                "story_key": primary,
                "level": sig.get("level", "high"),
                "id": sig.get("id"),
                "description": sig.get("description"),
                "impact_value": sig.get("impact_value"),
                "kind": sig.get("kind", "business"),
            }
            by_key[primary] = entry  # merge by story_key within the day, never duplicate
            committed += 1

        journal[today] = list(by_key.values())

        wm = derive_watermark(state)
        if wm and (not memory.get("watermark") or wm > memory["watermark"]):
            memory["watermark"] = wm

        _atomic_write(path, memory)
        try:
            markdown_path(state).write_text(render_markdown(memory), encoding="utf-8")
        except OSError:
            pass
        return {"status": "ok", "committed": committed, "watermark": memory.get("watermark")}
    finally:
        _release_lock(lock)


def quarantine_corrupt(state: dict) -> Path | None:
    """Rename a corrupt store aside so a fresh one can be built, without silently
    discarding the damaged data. Returns the new path or None."""
    path = store_path(state)
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"memory.corrupt-{ts}.json")
    try:
        os.replace(path, dest)
        return dest
    except OSError:
        return None
