"""Summary-only novelty gate. Insight memory is never read or written here."""

from __future__ import annotations

from ..tools import file_io, summary_memory
from ..utils.logger import RunLogger


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
    blocked = summary_memory.suppressed(store.get("records", {}), policy, cooldown)
    unseen = [candidate for candidate in candidates if candidate.get("summary_key") not in blocked]
    limit = max(1, int(state.get("summary_candidates_max", 12)))
    eligible = unseen[:limit]
    anchor = (state.get("summary_period_context") or {}).get("period_anchor")
    summary_type = "new_data" if anchor and anchor != store.get("period_anchor") else "new_perspective"
    if not eligible:
        summary_type = "no_new_perspective"
    novelty = {
        "status": "ok",
        "memory_status": status,
        "policy": policy,
        "detected": len(candidates),
        "suppressed": len(candidates) - len(unseen),
        "unseen": len(unseen),
        "eligible": len(eligible),
        "cap_dropped": max(0, len(unseen) - len(eligible)),
        "summary_type": summary_type,
        "period_anchor": anchor,
        "previous_period_anchor": store.get("period_anchor"),
        "reason": "ok" if eligible else "all_material_perspectives_already_reported",
    }
    file_io.write_json(state, "summary_novelty.json", novelty)
    log.info(
        "Summary novelty: detected=%d suppressed=%d eligible=%d type=%s."
        % (len(candidates), novelty["suppressed"], len(eligible), summary_type)
    )
    return {"summary_eligible_candidates": eligible, "summary_novelty": novelty, **log.updates()}
