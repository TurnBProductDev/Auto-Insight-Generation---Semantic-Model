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
SCHEMA_VERSION = 2
# Bounded retention for the rotation-tracking channels. Suppression identity
# lives in focus_records (kept indefinitely, like v1 records); these two are
# only editorial scaffolding for same-day recovery and R3 overlap checks.
RECENT_FOCUS_MAX = 400
DAILY_PLAN_MAX_DAYS = 60


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
        # --- schema v2: focus rotation ---
        "focus_records": {},   # focus_key -> focus identity + last delivery
        "daily_plan": {},      # iso day -> the focus delivered that day (same-day pin)
        "recent_focus": [],    # newest-first signatures for R3 overlap checks
    }


def _migrate(data: dict, dataset_id: str) -> dict:
    """Non-destructively bring a v1 store up to the v2 shape in memory.

    v1 records are preserved untouched. ``focus_records`` is best-effort
    backfilled so a store that only ever ran the legacy path still has a
    period-independent focus history to rotate against on the first focus run.
    """
    data.setdefault("watermark", None)
    data.setdefault("period_anchor", None)
    data.setdefault("records", {})
    data.setdefault("journal", {})
    data.setdefault("focus_records", {})
    data.setdefault("daily_plan", {})
    data.setdefault("recent_focus", [])
    if int(data.get("schema_version") or 1) < 2:
        _backfill_focus_records(data, dataset_id)
    data["schema_version"] = SCHEMA_VERSION
    return data


def load_store(state: dict) -> tuple[dict, str]:
    """Return ``(store, status)`` where status is ok, empty, or corrupt."""
    path = store_path(state)
    if not path.exists():
        return _empty_store(), "empty"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
            return _empty_store(), "corrupt"
        return _migrate(data, str(state.get("dataset_id") or "unknown_dataset")), "ok"
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
        "observation_value": candidate.get("observation_value"),
        "score": candidate.get("score"),
    }
    return f"summary:v1:{digest}", fields


# --- schema v2: period-independent focus identity ---------------------------
# focus_key answers "have we recently *shown this analytical focus*?" and is
# deliberately free of period_anchor, direction, sentiment and any number, so a
# changed daily watermark cannot reopen an old focus and a reversal resurfaces
# the same focus instead of minting a new key.
_LENSES = ("performance", "trend", "driver", "composition")


def _clean_role(value: Any) -> str:
    text = _norm_text(value)
    return text or "overall"


def focus_components(candidate: dict, dataset_id: str) -> tuple[str, dict]:
    """Return a stable period-independent focus key and its persisted fields."""
    dimension_role = _clean_role(candidate.get("dimension_role") or candidate.get("dimension"))
    lens = _norm_text(candidate.get("lens")) or "performance"
    if lens not in _LENSES:
        lens = "performance"
    canon = {
        "namespace": "focus",
        "version": 1,
        "dataset": _norm_text(dataset_id),
        "dimension_role": dimension_role,
        "segment": _norm_text(candidate.get("segment")),
        "metric": _norm_text(candidate.get("metric_family")),
        "lens": lens,
    }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    fields = {
        "dimension_role": dimension_role,
        "lens": lens,
        "segment": candidate.get("segment"),
        "metric_family": candidate.get("metric_family"),
    }
    return f"focus:v1:{digest}", fields


def _role_from_angle(angle: str, dimension: str) -> str:
    text = _norm_text(angle)
    mapping = {
        "overall_performance": "overall",
        "period_movement": "period",
        "store_overview": "store",
        "division_overview": "division",
        "category_overview": "category",
        "product_overview": "product",
        "volume_and_transactions": "overall",
        "largest_declines": _clean_role(dimension),
        "business_breakdown": _clean_role(dimension),
    }
    return mapping.get(text, _clean_role(dimension))


def _lens_from_angle(angle: str) -> str:
    text = _norm_text(angle)
    if text == "period_movement":
        return "trend"
    if text == "largest_declines":
        return "driver"
    if text in {"volume_and_transactions", "business_breakdown"}:
        return "composition"
    return "performance"


def _backfill_focus_records(data: dict, dataset_id: str) -> None:
    """Derive broad focus_records from v1 records without inventing detail.

    Only records with enough structure to reconstruct a focus identity are
    carried over; the rest are simply skipped (a later real focus run recreates
    them). Backfilled entries assume the ``performance`` lens. The store's own
    dataset id is hashed in so backfilled keys line up with live ones.
    """
    focus_records = data.setdefault("focus_records", {})
    for record in (data.get("records") or {}).values():
        angle = record.get("angle")
        dimension = record.get("dimension")
        metric_family = record.get("metric")
        if not (angle or dimension) or not metric_family:
            continue
        pseudo = {
            "dimension_role": _role_from_angle(angle or "", dimension or ""),
            "lens": _lens_from_angle(angle or ""),
            "segment": record.get("segment") or "",
            "metric_family": metric_family,
        }
        key, fields = focus_components(pseudo, dataset_id)
        if key in focus_records:
            continue
        focus_records[key] = {
            **fields,
            "first_reported": record.get("first_reported"),
            "last_reported": record.get("last_reported"),
            "times_reported": int(record.get("times_reported", 0) or 0),
            "last_direction": record.get("direction"),
            "last_observation": record.get("observation_value"),
            "last_materiality": None,
            "deep_dive_signature": None,
            "backfilled": True,
        }


def focus_suppressed(
    focus_records: dict,
    policy: str = "never_repeat",
    cooldown_days: int = 14,
    today: date | None = None,
) -> set[str]:
    """Return focus keys blocked by the configured focus-memory policy."""
    normalized_policy = str(policy or "cooldown").casefold()
    if normalized_policy in {"off", "disabled", "none"}:
        return set()
    if normalized_policy == "never_repeat":
        return set((focus_records or {}).keys())
    today = today or datetime.now().date()
    out: set[str] = set()
    window = max(0, int(cooldown_days))
    for key, record in (focus_records or {}).items():
        try:
            last = date.fromisoformat(str(record.get("last_reported"))[:10])
        except (TypeError, ValueError):
            continue
        if (today - last).days < window:
            out.add(key)
    return out


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
                "observation_value": candidate.get("observation_value"),
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

        focus_committed = _commit_focus(memory, state, fresh_summary, now, today)

        _atomic_write(path, memory)
        return {
            "status": "ok",
            "committed": committed,
            "focus_committed": focus_committed,
            "watermark": memory.get("watermark"),
            "period_anchor": memory.get("period_anchor"),
        }
    finally:
        _release_lock(lock)


def _commit_focus(memory: dict, state: dict, fresh_summary: dict, now: str, today: str) -> str | None:
    """Persist the delivered focus identity, same-day pin, and R3 signature.

    Returns the committed focus_key, or ``None`` when this run delivered no
    focus (legacy mode, or a focus run that produced no perspective). Only ever
    called from inside ``commit_summary_run`` after delivery has succeeded.
    """
    focus = state.get("summary_selected_focus") or {}
    focus_key = str(focus.get("focus_key") or "")
    if not focus_key:
        return None

    # The daily_plan key must match the day the selector pins on, which is
    # summary_focus.focus_today (override/timezone aware), not the wall clock -
    # otherwise the same-day pin never fires under a summary_now_override.
    plan_day = today
    try:
        from . import summary_focus  # lazy import avoids a module cycle
        plan_day = summary_focus.focus_today(state).isoformat()
    except Exception:  # noqa: BLE001 - fall back to the wall-clock day
        plan_day = today

    evidence = state.get("summary_focus_evidence") or {}
    signature = evidence.get("deep_dive_signature")

    focus_records = memory.setdefault("focus_records", {})
    record = focus_records.get(focus_key)
    if record is None:
        record = {"first_reported": now, "times_reported": 0}
        focus_records[focus_key] = record
    # Cooldown dates and the same-day pin must use the same timezone/override
    # day as selection.  Keep the time/offset for auditability, but replace the
    # wall-clock date when summary_now_override or a non-local focus timezone is
    # in force.
    focus_stamp = f"{plan_day}{now[10:]}" if len(now) >= 10 else now
    record.update({
        "dimension_role": focus.get("dimension_role"),
        "lens": focus.get("lens"),
        "segment": focus.get("segment"),
        "metric_family": focus.get("metric_family"),
        "last_reported": focus_stamp,
        "times_reported": int(record.get("times_reported", 0)) + 1,
        "last_direction": focus.get("direction"),
        "last_observation": focus.get("observation_value"),
        "last_materiality": focus.get("materiality"),
        "deep_dive_signature": signature,
        "heading": fresh_summary.get("heading"),
    })
    record.pop("backfilled", None)

    daily_plan = memory.setdefault("daily_plan", {})
    daily_plan[plan_day] = {
        "focus_key": focus_key,
        "candidate_id": focus.get("candidate_id"),
        "dimension_role": focus.get("dimension_role"),
        "segment": focus.get("segment"),
        "metric_family": focus.get("metric_family"),
        "lens": focus.get("lens"),
        "reported_at": focus_stamp,
    }
    # Bound daily_plan to the retention window.
    _prune_daily_plan(daily_plan, plan_day)

    recent = memory.setdefault("recent_focus", [])
    recent.insert(0, {
        "focus_key": focus_key,
        "reported_at": focus_stamp,
        "dimension_role": focus.get("dimension_role"),
        "segment": focus.get("segment"),
        "fact_keys": list(focus.get("fact_keys") or []),
        "top_pos_contributor": (evidence.get("signature_fields") or {}).get("top_pos_contributor"),
        "top_neg_contributor": (evidence.get("signature_fields") or {}).get("top_neg_contributor"),
        "leading_location": (evidence.get("signature_fields") or {}).get("leading_location"),
        "driver_class": (evidence.get("signature_fields") or {}).get("driver_class"),
    })
    del recent[RECENT_FOCUS_MAX:]
    return focus_key


def _prune_daily_plan(daily_plan: dict, today: str) -> None:
    try:
        cutoff = date.fromisoformat(str(today)[:10])
    except (TypeError, ValueError):
        return
    for day in list(daily_plan):
        try:
            when = date.fromisoformat(str(day)[:10])
        except (TypeError, ValueError):
            daily_plan.pop(day, None)
            continue
        if (cutoff - when).days > DAILY_PLAN_MAX_DAYS:
            daily_plan.pop(day, None)


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
