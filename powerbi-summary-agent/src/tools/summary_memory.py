"""Independent cross-run memory for fresh report summaries.

This store intentionally shares no records or keys with ``insight_memory``.
It remembers which descriptive perspectives were successfully delivered for a
reporting period so an unchanged monthly model can rotate through useful views
without pretending that new data arrived.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1


def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split())


def _safe_dataset(value: Any) -> str:
    raw = str(value or "unknown_dataset")
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in raw)


def store_path(state: dict) -> Path:
    root = Path(
        state.get("summary_memory_root")
        or f"{state.get('output_folder', 'outputs')}/.runtime/summary_memory"
    )
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    path = root / _safe_dataset(state.get("dataset_id")) / "memory.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _empty_store() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "watermark": None,
        "period_anchor": None,
        "records": {},
        "journal": {},
    }


def load_store(state: dict) -> tuple[dict, str]:
    """Return ``(store, status)`` where status is ok, empty, or corrupt."""
    path = store_path(state)
    if not path.exists():
        return _empty_store(), "empty"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
            return _empty_store(), "corrupt"
        data.setdefault("schema_version", SCHEMA_VERSION)
        data.setdefault("watermark", None)
        data.setdefault("period_anchor", None)
        data.setdefault("journal", {})
        return data, "ok"
    except (OSError, ValueError, json.JSONDecodeError):
        return _empty_store(), "corrupt"


def story_components(candidate: dict, dataset_id: str, period_anchor: str) -> tuple[str, dict]:
    """Return a stable summary-only key and the fields persisted on commit.

    Mutable values, rank, prose, and impact are deliberately excluded. A new
    reporting-period anchor reopens the same useful perspective automatically.
    """
    canon = {
        "namespace": "summary",
        "version": 1,
        "dataset": _norm_text(dataset_id),
        "period_anchor": _norm_text(period_anchor),
        "angle": _norm_text(candidate.get("angle")),
        "metric": _norm_text(candidate.get("metric_family")),
        "dimension": _norm_text(candidate.get("dimension")),
        "segment": _norm_text(candidate.get("segment")),
    }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    fields = {
        "angle": candidate.get("angle"),
        "metric": candidate.get("metric_family"),
        "dimension": candidate.get("dimension"),
        "segment": candidate.get("segment"),
        "period_anchor": period_anchor,
        "direction": candidate.get("direction"),
        "score": candidate.get("score"),
    }
    return f"summary:v1:{digest}", fields


def suppressed(records: dict, policy: str = "never_repeat", cooldown_days: int = 14) -> set[str]:
    if str(policy or "never_repeat").lower() != "cooldown":
        return set(records)
    today = datetime.now().date()
    out = set()
    for key, record in (records or {}).items():
        try:
            last = date.fromisoformat(str(record.get("last_reported")))
        except (TypeError, ValueError):
            continue
        if (today - last).days < max(0, int(cooldown_days)):
            out.add(key)
    return out


def _acquire_lock(path: Path, timeout: float = 5.0):
    lock = path.with_suffix(".lock")
    deadline = time.time() + timeout
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
            return fd, lock
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


def _atomic_write(path: Path, payload: dict) -> None:
    tmp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def commit_summary_run(
    state: dict,
    covered_keys: Iterable[str],
    fresh_summary: dict,
) -> dict:
    """Commit only after the caller has delivered the summary and history."""
    keys = list(dict.fromkeys(str(key) for key in covered_keys if key))
    path = store_path(state)
    lock = _acquire_lock(path)
    if not lock:
        return {"status": "locked", "committed": 0}
    try:
        memory, status = load_store(state)
        if status == "corrupt":
            return {"status": "corrupt", "committed": 0}

        now = datetime.now().astimezone().isoformat(timespec="seconds")
        today = now[:10]
        records = memory.setdefault("records", {})
        candidates = {
            str(candidate.get("summary_key")): candidate
            for candidate in state.get("summary_candidates", []) or []
            if candidate.get("summary_key")
        }
        committed = 0
        for key in keys:
            candidate = candidates.get(key, {})
            record = records.get(key)
            if record is None:
                record = {
                    "first_reported": now,
                    "times_reported": 0,
                }
                records[key] = record
            record.update({
                "last_reported": now,
                "times_reported": int(record.get("times_reported", 0)) + 1,
                "angle": candidate.get("angle"),
                "metric": candidate.get("metric_family"),
                "dimension": candidate.get("dimension"),
                "segment": candidate.get("segment"),
                "period_anchor": candidate.get("period_anchor"),
                "direction": candidate.get("direction"),
                "score": candidate.get("score"),
                "heading": fresh_summary.get("heading"),
            })
            committed += 1

        period = state.get("summary_period_context", {}) or {}
        watermark = period.get("data_as_of")
        anchor = period.get("period_anchor")
        previous_watermark = memory.get("watermark")
        if watermark and (not previous_watermark or watermark > previous_watermark):
            memory["watermark"] = watermark
        if anchor and (not previous_watermark or not watermark or watermark >= previous_watermark):
            memory["period_anchor"] = anchor

        journal = memory.setdefault("journal", {})
        runs = journal.setdefault(today, [])
        run_id = fresh_summary.get("run_id") or now
        entry = {
            "run_id": run_id,
            "summary_type": fresh_summary.get("summary_type"),
            "heading": fresh_summary.get("heading"),
            "covered_summary_keys": keys,
            "period_anchor": anchor,
        }
        runs = [item for item in runs if item.get("run_id") != run_id]
        runs.append(entry)
        journal[today] = runs

        _atomic_write(path, memory)
        return {
            "status": "ok",
            "committed": committed,
            "watermark": memory.get("watermark"),
            "period_anchor": memory.get("period_anchor"),
        }
    finally:
        _release_lock(lock)


def quarantine_corrupt(state: dict) -> Path | None:
    path = store_path(state)
    if not path.exists():
        return None
    dest = path.with_name(f"memory.corrupt-{datetime.now():%Y%m%d-%H%M%S}.json")
    try:
        os.replace(path, dest)
        return dest
    except OSError:
        return None
