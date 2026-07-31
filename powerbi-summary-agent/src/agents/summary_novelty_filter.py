"""Summary-only novelty gate. Insight memory is never read or written here.

Two modes:

* ``summary_focus_enabled`` (default) - deterministic two-stage focus selection
  (``summary_focus.select_focus``). ``summary_key`` is used only to classify the
  run as new_data / new_perspective, never for suppression, so it can never evict
  the same-day pin.
* legacy - the original ``summary_key`` rotation, preserved unchanged and
  regression-tested, for a clean rollback of the focus feature.
"""

from __future__ import annotations

from ..tools import file_io, summary_focus, summary_memory, summary_portfolio
from ..utils.logger import RunLogger

# Relocated shared helpers now live in summary_focus; keep the legacy names
# available so the legacy path below reads identically to before.
_as_date = summary_focus._as_date
_materially_changed = summary_focus._materially_changed


def _memory_unavailable(state, log, candidates, memory_status, reason) -> dict:
    novelty = {
        "status": "memory_unavailable",
        "memory_status": memory_status,
        "detected": len(candidates),
        "suppressed": 0,
        "eligible": 0,
        "reason": reason,
    }
    file_io.write_json(state, "summary_novelty.json", novelty)
    log.error("Summary memory is unavailable; refusing to guess which perspectives are new.")
    return {
        "summary_eligible_candidates": [],
        "summary_novelty": novelty,
        "summary_selected_focus": {},
        **log.updates(),
    }


def _run_focus(state: dict, candidates: list[dict], log: RunLogger) -> dict:
    enabled = bool(state.get("summary_memory_enabled", True))
    hydration = state.get("summary_memory_hydration", {}) or {}
    if hydration.get("status") == "failed":
        return _memory_unavailable(
            state, log, candidates, "failed",
            hydration.get("reason") or hydration.get("error") or "summary memory hydration failed",
        )

    if enabled:
        store, status = summary_memory.load_store(state)
        if status == "corrupt":
            return _memory_unavailable(
                state, log, candidates, "corrupt",
                "summary memory is corrupt; refusing to overwrite it",
            )
    else:
        store, status = summary_memory._empty_store(), "disabled"

    try:
        result = summary_focus.select_focus(state, candidates, store, status)
    except ValueError as exc:  # unsupported timezone or other loud config error
        novelty = {
            "status": "config_error",
            "memory_status": status,
            "detected": len(candidates),
            "eligible": 0,
            "reason": str(exc),
        }
        file_io.write_json(state, "summary_novelty.json", novelty)
        log.error(f"Focus selection rejected the configuration loudly: {exc}")
        return {
            "summary_eligible_candidates": [],
            "summary_novelty": novelty,
            "summary_selected_focus": {},
            **log.updates(),
        }

    selected = result.get("selected")
    audit = result.get("audit", {})
    summary_type = result.get("summary_type", "no_new_perspective")
    eligible = [selected] if selected else []
    selected_focus = {}
    if selected:
        selected_focus = {
            "focus_key": selected.get("focus_key"),
            "candidate_id": selected.get("candidate_id"),
            "dimension_role": selected.get("dimension_role"),
            "segment": selected.get("segment"),
            "metric_family": selected.get("metric_family"),
            "lens": selected.get("lens"),
            "direction": selected.get("direction"),
            # Mutable tone (R2): reflects current direction, excluded from
            # focus_key, so a reversal resurfaces the same focus with a flipped
            # opportunity/risk framing.
            "sentiment": result.get("sentiment"),
            "observation_value": selected.get("observation_value"),
            "materiality": selected.get("materiality", selected.get("observation_value")),
            "fact_keys": [
                fact.get("fact_id")
                for fact in (selected.get("evidence") or {}).get("facts", []) or []
            ],
        }

    novelty = {
        "status": "ok",
        "mode": "focus",
        "memory_status": status,
        "detected": len(candidates),
        "eligible": len(eligible),
        "summary_type": summary_type,
        "selected_focus_key": selected_focus.get("focus_key"),
        "selected_segment": selected_focus.get("segment"),
        "selected_role": selected_focus.get("dimension_role"),
        "selected_sentiment": selected_focus.get("sentiment"),
        "reason": audit.get("reason"),
        "audit": audit,
    }
    file_io.write_json(state, "summary_novelty.json", novelty)
    log.info(
        "Summary focus: detected=%d role=%s segment=%s type=%s reason=%s."
        % (len(candidates), selected_focus.get("dimension_role"),
           selected_focus.get("segment"), summary_type, audit.get("reason"))
    )
    return {
        "summary_eligible_candidates": eligible,
        "summary_novelty": novelty,
        "summary_selected_focus": selected_focus,
        # R3: hand the recent-delivery signatures to the deep-dive node so it can
        # flag a signature that just repeats a recently delivered story.
        "summary_recent_focus": store.get("recent_focus", []) or [],
        **log.updates(),
    }


def _run_legacy(state: dict, candidates: list[dict], log: RunLogger) -> dict:
    enabled = bool(state.get("summary_memory_enabled", True))
    hydration = state.get("summary_memory_hydration", {}) or {}

    if hydration.get("status") == "failed":
        return _memory_unavailable(
            state, log, candidates, "failed",
            hydration.get("reason") or hydration.get("error") or "summary memory hydration failed",
        )

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
        return _memory_unavailable(
            state, log, candidates, "corrupt",
            "summary memory is corrupt; refusing to overwrite it",
        )

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


def _run_portfolio(state: dict, candidates: list[dict], log: RunLogger) -> dict:
    """R4 multi-focus portfolio mode.

    Keeps ownership of memory load/corruption handling, summary-type
    classification, same-day plan recovery and the novelty artifact, but
    delegates the actual multi-focus scoring to
    ``summary_portfolio.select_portfolio`` (reading v3 coverage). Emits the
    ordered ``summary_selected_focuses`` plus a first-focus alias for backward
    compatibility.
    """
    enabled = bool(state.get("summary_memory_enabled", True))
    hydration = state.get("summary_memory_hydration", {}) or {}
    if hydration.get("status") == "failed":
        return _memory_unavailable(
            state, log, candidates, "failed",
            hydration.get("reason") or hydration.get("error") or "summary memory hydration failed",
        )
    if enabled:
        store, status = summary_memory.load_store(state)
        if status == "corrupt":
            return _memory_unavailable(
                state, log, candidates, "corrupt",
                "summary memory is corrupt; refusing to overwrite it",
            )
    else:
        store, status = summary_memory._empty_store(), "disabled"

    try:
        today = summary_focus.focus_today(state)
    except ValueError as exc:  # unsupported timezone or other loud config error
        novelty = {
            "status": "config_error", "memory_status": status,
            "detected": len(candidates), "eligible": 0, "reason": str(exc),
        }
        file_io.write_json(state, "summary_novelty.json", novelty)
        log.error(f"Portfolio selection rejected the configuration loudly: {exc}")
        return {
            "summary_eligible_candidates": [], "summary_selected_focuses": [],
            "summary_novelty": novelty, "summary_selected_focus": {}, **log.updates(),
        }

    period = state.get("summary_period_context") or {}
    current_watermark = summary_focus._as_date(period.get("data_as_of"))
    prior_watermark = summary_focus._as_date(store.get("watermark"))
    data_advanced = bool(current_watermark and (not prior_watermark or current_watermark > prior_watermark))
    anchor = period.get("period_anchor")
    anchor_changed = bool(anchor and anchor != store.get("period_anchor"))

    by_focus: dict = {}
    by_area: dict = {}
    for candidate in candidates:
        by_focus.setdefault(candidate.get("focus_key"), candidate)
        by_area.setdefault(candidate.get("area_key"), candidate)

    # Same-day recovery: pin the previously delivered portfolio in order, keeping
    # only focuses whose candidate is still valid this run.
    recovered = False
    pinned = summary_memory.pinned_portfolio(store, today.isoformat())
    if pinned and pinned.get("focus_keys"):
        if pinned.get("area_keys"):
            selected = [by_area[key] for key in pinned["area_keys"] if key in by_area]
        else:
            # Migrated v2 plans have no area list; keep the legacy fallback.
            selected = [by_focus[key] for key in pinned["focus_keys"] if key in by_focus]
        reserves: list = []
        audit = {"reason": "same_day_recovery", "recovered": True, "pinned": len(pinned["focus_keys"])}
        recovered = bool(selected)
    if not recovered:
        coverage = summary_memory.coverage_map(store)
        recent = store.get("recent_focus", []) or []
        result = summary_portfolio.select_portfolio(
            state, candidates, coverage=coverage, recent_focus=recent,
            today=today, data_advanced=data_advanced,
        )
        selected = result["selected"]
        reserves = result["reserves"]
        audit = result["audit"]

    if selected:
        if data_advanced or anchor_changed:
            summary_type = "new_data"
        elif recovered:
            summary_type = pinned.get("summary_type") or "new_perspective"
        else:
            summary_type = "new_perspective"
    else:
        summary_type = "no_new_perspective"

    selected_alias = selected[0] if selected else {}
    novelty = {
        "status": "ok",
        "mode": "portfolio",
        "memory_status": status,
        "detected": len(candidates),
        "eligible": len(selected),
        "summary_type": summary_type,
        "recovered_same_day": recovered,
        "selected_areas": [focus.get("area_key") for focus in selected],
        "selected_segments": [focus.get("segment") for focus in selected],
        "selected_roles": [focus.get("dimension_role") for focus in selected],
        "reason": audit.get("reason"),
        "audit": audit,
    }
    file_io.write_json(state, "summary_novelty.json", novelty)
    log.info(
        "Summary portfolio: detected=%d selected=%d type=%s reason=%s."
        % (len(candidates), len(selected), summary_type, audit.get("reason"))
    )
    return {
        "summary_eligible_candidates": selected,
        "summary_selected_focuses": selected,
        "summary_portfolio_reserves": reserves,
        "summary_novelty": novelty,
        # Backward-compat alias: existing single-focus consumers read the first.
        "summary_selected_focus": selected_alias,
        "summary_recent_focus": store.get("recent_focus", []) or [],
        **log.updates(),
    }


def run(state: dict) -> dict:
    log = RunLogger(state)
    candidates = list(state.get("summary_candidates", []) or [])
    if state.get("summary_r4_enabled", False):
        return _run_portfolio(state, candidates, log)
    if state.get("summary_focus_enabled", True):
        return _run_focus(state, candidates, log)
    return _run_legacy(state, candidates, log)
