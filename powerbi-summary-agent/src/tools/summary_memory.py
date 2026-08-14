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

from ..kernel import report, scoping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# v4 (WP1): the store is report-scoped. The shape is unchanged from v3 - what
# changed is which report it belongs to, recorded in the ``scope`` block so a
# store found on disk can say which report wrote it.
# v5 (WP4): adds ``state_records`` for reports whose findings are states that
# persist rather than periods that end - a stock exception has no period to
# anchor novelty to. Purely additive; no existing record is rewritten.
SCHEMA_VERSION = 5
# Bounded retention for the rotation-tracking channels. Suppression identity
# lives in focus_records (kept indefinitely, like v1 records); these two are
# only editorial scaffolding for same-day recovery and R3 overlap checks.
RECENT_FOCUS_MAX = 400
DAILY_PLAN_MAX_DAYS = 60
WEEKLY_COVERAGE_MAX_DATES = 30


def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split())


def _safe_dataset(value: Any) -> str:
    raw = str(value or "unknown_dataset")
    return "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in raw)


def store_path(state: dict) -> Path:
    """This report's store, per dataset AND per report (WP1).

    Summary rotation belongs to one report: two reports over the same semantic
    model must not share a daily plan or suppress each other's focus areas. A
    pre-WP1 store sitting at the dataset root is copied into place on first use
    - see ``kernel.scoping.migrate_store``.
    """
    root = Path(
        state.get("summary_memory_root")
        or f"{state.get('output_folder', 'outputs')}/.runtime/summary_memory"
    )
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    # The dataset segment keeps this module's historical sanitiser so an
    # existing directory is never relocated.
    path, _status = scoping.scoped_store(
        root, _safe_dataset(state.get("dataset_id")),
        report_id=state.get("report_id") or report.DEFAULT_REPORT_ID)
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
        "daily_plan": {},      # iso day -> the focus/portfolio delivered that day (same-day pin)
        "recent_focus": [],    # newest-first signatures for R3 overlap checks
        # --- schema v3: weekly multi-focus rotation ---
        "area_records": {},    # area_key -> business-area coverage + last direction/impact
        "weekly_coverage": {}, # area_key -> recent delivery dates (bounded to the window)
        # --- schema v4: which report owns this store ---
        "scope": {},           # {report_id, dataset_id} - stamped on first write
        # --- schema v5: states that persist rather than periods that end ---
        "state_records": {},   # state_key -> position, first_seen, duration
    }


def _migrate(data: dict, dataset_id: str, report_id: str = "") -> dict:
    """Non-destructively bring an older store up to the current shape in memory.

    v1 records are preserved untouched. ``focus_records`` is best-effort
    backfilled so a store that only ever ran the legacy path still has a
    period-independent focus history to rotate against on the first focus run.
    v4 adds only the ``scope`` stamp; no record is rewritten, because a store
    that changed location did not change meaning.
    """
    data.setdefault("watermark", None)
    data.setdefault("period_anchor", None)
    data.setdefault("records", {})
    data.setdefault("journal", {})
    data.setdefault("focus_records", {})
    data.setdefault("daily_plan", {})
    data.setdefault("recent_focus", [])
    data.setdefault("area_records", {})
    data.setdefault("weekly_coverage", {})
    data.setdefault("scope", {})
    data.setdefault("state_records", {})
    original = int(data.get("schema_version") or 1)
    if original < 2:
        _backfill_focus_records(data, dataset_id)
    if original < 3:
        _backfill_area_records(data, dataset_id)
        _migrate_daily_plan_v3(data)
    if original < 4 and report_id:
        # A pre-WP1 store was copied here from the dataset root, so it belongs
        # to whichever report claimed it first - recorded, not guessed at later.
        data["scope"] = {"report_id": report_id, "dataset_id": dataset_id,
                         "migrated_from": "dataset_root"}
    elif report_id and not data["scope"].get("report_id"):
        data["scope"] = {"report_id": report_id, "dataset_id": dataset_id}
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
        return _migrate(
            data, str(state.get("dataset_id") or "unknown_dataset"),
            str(state.get("report_id") or report.DEFAULT_REPORT_ID)), "ok"
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


# --- schema v3: business-area identity (weekly rotation) --------------------
# area_key answers "have we recently *covered this business area*?" It is the
# rotation identity and deliberately excludes metric, lens, direction and any
# number, so covering a Category through different analytical lenses never
# counts as covering multiple areas. The full hierarchy path (not just the leaf
# member) is canonicalized so an identically named Category under two different
# parents produces two distinct area identities.
def _canonical_path(candidate: dict) -> list[str]:
    path = candidate.get("hierarchy_path")
    if isinstance(path, (list, tuple)) and path:
        cleaned = [_norm_text(part) for part in path if str(part or "").strip()]
        if cleaned:
            return cleaned
    segment = candidate.get("segment")
    return [_norm_text(segment)] if str(segment or "").strip() else []


def area_components(candidate: dict, dataset_id: str) -> tuple[str, dict]:
    """Return a stable weekly-rotation area key and its persisted fields."""
    role = _clean_role(candidate.get("dimension_role") or candidate.get("dimension"))
    path = _canonical_path(candidate)
    canon = {
        "namespace": "area",
        "version": 1,
        "dataset": _norm_text(dataset_id),
        "role": role,
        "path": path,
    }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    raw_path = candidate.get("hierarchy_path")
    if not (isinstance(raw_path, (list, tuple)) and raw_path):
        raw_path = [candidate.get("segment")] if str(candidate.get("segment") or "").strip() else []
    fields = {
        "role": role,
        "hierarchy_path": list(raw_path),
        "segment": candidate.get("segment"),
    }
    return f"area:v1:{digest}", fields


def portfolio_focus_components(candidate: dict, dataset_id: str) -> tuple[str, dict]:
    """R4 focus identity with the full hierarchy path.

    The R1-R3 ``focus:v1`` key intentionally predates hierarchy paths. R4 can
    contain identically named leaves under different parents, so its analytical
    focus key must include that path while still excluding mutable period,
    direction, sentiment and numbers.
    """
    role = _clean_role(candidate.get("dimension_role") or candidate.get("dimension"))
    lens = _norm_text(candidate.get("lens")) or "performance"
    metric = _norm_text(candidate.get("metric_family"))
    path = _canonical_path(candidate)
    canon = {
        "namespace": "focus",
        "version": 2,
        "dataset": _norm_text(dataset_id),
        "role": role,
        "path": path,
        "metric": metric,
        "lens": lens,
    }
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return f"focus:v2:{digest}", {
        "dimension_role": role,
        "hierarchy_path": list(candidate.get("hierarchy_path") or []),
        "segment": candidate.get("segment"),
        "metric_family": candidate.get("metric_family"),
        "lens": lens,
    }


def _role_from_angle(angle: str, dimension: str) -> str:
    text = _norm_text(angle)
    mapping = {
        "overall_performance": "overall",
        "period_movement": "period",
        "store_overview": "store",
        "division_overview": "division",
        "department_overview": "department",
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


def _backfill_area_records(data: dict, dataset_id: str) -> None:
    """Best-effort v2->v3 area history from focus_records (leaf-only path).

    v2 focus_records carry a role + segment but no hierarchy path, so the derived
    area_key is leaf-only and is marked ``backfilled``; a real R4 delivery with
    the full Division->...->member path supersedes it on the next commit.
    """
    area_records = data.setdefault("area_records", {})
    for record in (data.get("focus_records") or {}).values():
        role = record.get("dimension_role")
        segment = record.get("segment")
        if not role or not str(segment or "").strip():
            continue
        area_key, fields = area_components({"dimension_role": role, "segment": segment}, dataset_id)
        if area_key in area_records:
            continue
        area_records[area_key] = {
            **fields,
            "first_covered": record.get("first_reported"),
            "last_covered": record.get("last_reported"),
            "times_covered": int(record.get("times_reported", 0) or 0),
            "last_direction": record.get("last_direction"),
            "last_global_impact": None,
            "backfilled": True,
        }


def _migrate_daily_plan_v3(data: dict) -> None:
    """Convert singular v2 daily_plan entries to the v3 multi-focus shape.

    Non-destructive: the singular focus_key/candidate_id are preserved so the
    legacy single-focus path still reads them.
    """
    for entry in (data.get("daily_plan") or {}).values():
        if not isinstance(entry, dict) or "focus_keys" in entry:
            continue
        focus_key = entry.get("focus_key")
        entry["focus_keys"] = [focus_key] if focus_key else []
        candidate_id = entry.get("candidate_id")
        entry["candidate_ids"] = [candidate_id] if candidate_id else []
        entry.setdefault("area_keys", [])


def coverage_map(store: dict) -> dict:
    """Selector-facing view of area coverage keyed by area_key (§14)."""
    out: dict = {}
    for area_key, record in (store.get("area_records") or {}).items():
        out[area_key] = {
            "last_covered": record.get("last_covered"),
            "times": int(record.get("times_covered", 0) or 0),
            "last_direction": record.get("last_direction"),
            "last_global_impact": record.get("last_global_impact"),
        }
    return out


def pinned_portfolio(store: dict, day: str) -> dict | None:
    """Return the ordered focus set delivered on ``day`` for same-day recovery."""
    entry = (store.get("daily_plan") or {}).get(day)
    if not isinstance(entry, dict):
        return None
    focus_keys = entry.get("focus_keys")
    if focus_keys is None and entry.get("focus_key"):
        focus_keys = [entry.get("focus_key")]
    if not focus_keys:
        return None
    candidate_ids = entry.get("candidate_ids")
    if candidate_ids is None:
        candidate_ids = [entry["candidate_id"]] if entry.get("candidate_id") else []
    return {
        "focus_keys": list(focus_keys),
        "area_keys": list(entry.get("area_keys") or []),
        "candidate_ids": list(candidate_ids),
        "summary_type": entry.get("summary_type"),
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

        if state.get("summary_r4_enabled"):
            focus_committed = _commit_portfolio(memory, state, fresh_summary, now, today)
        else:
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


def _commit_portfolio(memory: dict, state: dict, fresh_summary: dict, now: str, today: str) -> str | None:
    """Persist the delivered R4 portfolio: area_records, weekly_coverage, the
    multi-focus same-day plan, focus_records and R3 signatures.

    Reads the ordered ``state["summary_selected_focuses"]`` (the public portfolio
    from the selector) and optional per-focus deep-dive signatures from
    ``summary_focus_evidence_by_key``. Returns the lead focus_key, or None when no
    focus was delivered. Only ever called from inside ``commit_summary_run`` after
    the required delivery channels have succeeded.
    """
    focuses = state.get("summary_selected_focuses") or []
    if not focuses:
        return None

    plan_day = today
    try:
        from . import summary_focus  # lazy import avoids a module cycle
        plan_day = summary_focus.focus_today(state).isoformat()
    except Exception:  # noqa: BLE001 - fall back to the wall-clock day
        plan_day = today
    focus_stamp = f"{plan_day}{now[10:]}" if len(now) >= 10 else now
    day_only = focus_stamp[:10]

    evidence_by_key = state.get("summary_focus_evidence_by_key") or {}
    focus_records = memory.setdefault("focus_records", {})
    area_records = memory.setdefault("area_records", {})
    weekly = memory.setdefault("weekly_coverage", {})
    recent = memory.setdefault("recent_focus", [])

    area_keys: list[str] = []
    focus_keys: list[str] = []
    candidate_ids: list = []
    for focus in focuses:
        focus_key = str(focus.get("focus_key") or "")
        if not focus_key:
            continue
        area_key = str(focus.get("area_key") or "")
        focus_keys.append(focus_key)
        candidate_ids.append(focus.get("candidate_id"))
        mfacts = focus.get("materiality_facts") or {}
        evidence = evidence_by_key.get(focus_key) or {}
        signature = evidence.get("signature_fields") or {}

        record = focus_records.get(focus_key) or {"first_reported": now, "times_reported": 0}
        record.update({
            "dimension_role": focus.get("dimension_role"),
            "lens": focus.get("lens"),
            "segment": focus.get("segment"),
            "metric_family": focus.get("metric_family"),
            "hierarchy_path": focus.get("hierarchy_path"),
            "last_reported": focus_stamp,
            "times_reported": int(record.get("times_reported", 0)) + 1,
            "last_direction": focus.get("direction"),
            "last_global_impact": mfacts.get("global_impact_pct"),
            "deep_dive_signature": evidence.get("deep_dive_signature"),
            "heading": fresh_summary.get("heading"),
        })
        record.pop("backfilled", None)
        focus_records[focus_key] = record

        if area_key:
            area_keys.append(area_key)
            arec = area_records.get(area_key) or {"first_covered": now, "times_covered": 0}
            arec.update({
                "role": focus.get("dimension_role"),
                "hierarchy_path": focus.get("hierarchy_path"),
                "segment": focus.get("segment"),
                "last_covered": focus_stamp,
                "times_covered": int(arec.get("times_covered", 0)) + 1,
                "last_direction": focus.get("direction"),
                "last_global_impact": mfacts.get("global_impact_pct"),
            })
            arec.pop("backfilled", None)
            area_records[area_key] = arec
            dates = [day_only] + [d for d in (weekly.get(area_key) or []) if d != day_only]
            weekly[area_key] = dates[:WEEKLY_COVERAGE_MAX_DATES]

        recent.insert(0, {
            "focus_key": focus_key,
            "area_key": area_key,
            "reported_at": focus_stamp,
            "dimension_role": focus.get("dimension_role"),
            "segment": focus.get("segment"),
            "top_pos_contributor": signature.get("top_pos_contributor"),
            "top_neg_contributor": signature.get("top_neg_contributor"),
            "leading_location": signature.get("leading_location"),
            "driver_class": signature.get("driver_class"),
        })
    del recent[RECENT_FOCUS_MAX:]

    daily_plan = memory.setdefault("daily_plan", {})
    daily_plan[plan_day] = {
        "summary_type": fresh_summary.get("summary_type"),
        "area_keys": area_keys,
        "focus_keys": focus_keys,
        "candidate_ids": candidate_ids,
        "reported_at": focus_stamp,
    }
    _prune_daily_plan(daily_plan, plan_day)
    return focus_keys[0] if focus_keys else None


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
