"""Summary-only novelty gate. Insight memory is never read or written here."""

from __future__ import annotations

import math
from datetime import date

from ..tools import file_io, summary_memory
from ..utils.logger import RunLogger


def _as_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _materially_changed(candidate: dict, stored: dict, threshold_pct: float) -> bool:
    old_direction = str(stored.get("direction") or "")
    new_direction = str(candidate.get("direction") or "")
    if old_direction and new_direction and old_direction != new_direction:
        return True
    old = stored.get("observation_value")
    new = candidate.get("observation_value")
    if not all(
        isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
        for value in (old, new)
    ):
        return False
    old, new = float(old), float(new)
    if old == new:
        return False
    if old == 0:
        return new != 0
    return abs(new - old) / abs(old) * 100.0 >= max(0.0, float(threshold_pct))


def run(state: dict) -> dict:
    log = RunLogger(state)
    candidates = list(state.get("summary_candidates", []) or [])
    enabled = bool(state.get("summary_memory_enabled", True))
    hydration = state.get("summary_memory_hydration", {}) or {}

    if hydration.get("status") == "failed":
        novelty = {
            "status": "memory_unavailable",
            "memory_status": "failed",
            "detected": len(candidates),
            "suppressed": 0,
            "eligible": 0,
            "reason": hydration.get("reason") or hydration.get("error") or "summary memory hydration failed",
        }
        file_io.write_json(state, "summary_novelty.json", novelty)
        log.error("Summary memory is unavailable; refusing to guess which perspectives are new.")
        return {"summary_eligible_candidates": [], "summary_novelty": novelty, **log.updates()}

    if not enabled:
        limit = max(1, int(state.get("summary_candidates_max", 12)))
        eligible = candidates[:limit]
        novelty = {
            "status": "disabled",
            "memory_status": "disabled",
            "detected": len(candidates),
            "suppressed": 0,
            "eligible": len(eligible),
            "reason": "summary memory disabled",
            "summary_type": "new_data",
        }
        file_io.write_json(state, "summary_novelty.json", novelty)
        return {"summary_eligible_candidates": eligible, "summary_novelty": novelty, **log.updates()}

    store, status = summary_memory.load_store(state)
    if status == "corrupt":
        novelty = {
            "status": "memory_unavailable",
            "memory_status": "corrupt",
            "detected": len(candidates),
            "suppressed": 0,
            "eligible": 0,
            "reason": "summary memory is corrupt; refusing to overwrite it",
        }
        file_io.write_json(state, "summary_novelty.json", novelty)
        log.error("Summary memory is corrupt; novelty guarantee is unavailable and the store will not be overwritten.")
        return {"summary_eligible_candidates": [], "summary_novelty": novelty, **log.updates()}

    policy = str(state.get("summary_memory_policy", "never_repeat") or "never_repeat")
    cooldown = int(state.get("summary_memory_cooldown_days", 14))
    records = store.get("records", {})
    blocked = summary_memory.suppressed(records, policy, cooldown)
    unseen = [candidate for candidate in candidates if candidate.get("summary_key") not in blocked]
    period = state.get("summary_period_context") or {}
    current_watermark = _as_date(period.get("data_as_of"))
    prior_watermark = _as_date(store.get("watermark"))
    data_advanced = bool(current_watermark and (not prior_watermark or current_watermark > prior_watermark))
    change_pct = float(state.get("summary_resurface_change_pct", 20) or 20)
    resurfaced = [
        candidate
        for candidate in candidates
        if candidate.get("summary_key") in blocked
        and data_advanced
        and _materially_changed(candidate, records.get(candidate.get("summary_key"), {}), change_pct)
    ]
    # Rotate through unused perspectives before revisiting a changed one.
    pool = [*unseen, *resurfaced]
    limit = max(1, int(state.get("summary_candidates_max", 12)))
    eligible = pool[:limit]
    anchor = period.get("period_anchor")
    summary_type = (
        "new_data"
        if data_advanced or (anchor and anchor != store.get("period_anchor"))
        else "new_perspective"
    )
    if not eligible:
        summary_type = "no_new_perspective"
    novelty = {
        "status": "ok",
        "memory_status": status,
        "policy": policy,
        "detected": len(candidates),
        "suppressed": len(candidates) - len(pool),
        "unseen": len(unseen),
        "resurfaced": len(resurfaced),
        "eligible": len(eligible),
        "cap_dropped": max(0, len(pool) - len(eligible)),
        "summary_type": summary_type,
        "data_advanced": data_advanced,
        "resurface_change_pct": change_pct,
        "period_anchor": anchor,
        "previous_period_anchor": store.get("period_anchor"),
        "reason": "ok" if eligible else "all_material_perspectives_already_reported",
    }
    file_io.write_json(state, "summary_novelty.json", novelty)
    log.info(
        "Summary novelty: detected=%d suppressed=%d eligible=%d resurfaced=%d type=%s."
        % (len(candidates), novelty["suppressed"], len(eligible), len(resurfaced), summary_type)
    )
    return {"summary_eligible_candidates": eligible, "summary_novelty": novelty, **log.updates()}
