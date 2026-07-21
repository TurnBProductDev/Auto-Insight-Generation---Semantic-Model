"""Insight branch - Novelty Filter (deterministic, no LLM).

Sits between the stat detector and the signal detector. It fingerprints every
deterministic candidate with a stable ``story_key``, drops the ones already
reported in previous runs (per the memory policy), tags each survivor with its
temporal ``level`` (Phase 1: everything is ``high``), and hands the signal detector
an OVERCOMPLETE eligible shortlist plus a novelty summary. Filtering BEFORE the LLM
is the point: if the LLM were shown known findings and returned them, a post-filter
could leave zero signals while unused eligible candidates remained.

When memory is disabled this is a transparent pass-through. When the store reads
corrupt it fails LOUD - it never silently suppresses everything - and downstream
commit is refused so the damaged store is preserved.
"""

from __future__ import annotations

from ..tools import file_io
from ..tools import insight_memory as mem
from ..utils.logger import RunLogger


def _level_for(candidate: dict, contract: dict | None) -> str:
    """Temporal level of a candidate, from its scan's coverage_kind. Phase 2 adds
    the ``period`` (validated sub-annual series) level; Phase 3 adds ``recent_week``
    (the most recently completed week); Phase 3b adds ``recent_week_rolling`` and
    ``daily``."""
    kind = str((contract or {}).get("coverage_kind", "")).lower()
    # More specific check first: "recent_week_rolling_history" also starts with
    # "recent_week", so it would otherwise collide into that level.
    if kind.startswith("recent_week_rolling"):
        return "recent_week_rolling"
    if kind.startswith("recent_week"):
        return "recent_week"
    if kind == "period_series" or kind.startswith("weekly") or kind.startswith("monthly"):
        return "period"
    if kind.startswith("daily"):
        return "daily"
    return "high"


def _cap_for(state: dict, level: str) -> int:
    return {
        "high": int(state.get("insight_candidates_high", 20)),
        "period": int(state.get("insight_candidates_period", 10)),
        "daily": int(state.get("insight_candidates_daily", 10)),
        "recent_week": int(state.get("insight_candidates_weekly", 10)),
        "recent_week_rolling": int(state.get("insight_candidates_weekly", 10)),
    }.get(level, 20)


def _rolling_key(observation: dict, contracts: dict, dataset_id: str, scope_h: str,
                 anchor: str) -> str:
    """The ONE place a recent_week_rolling story_key is computed for the
    observation-only case (no candidate this run - an inactive reading). Builds
    a candidate-shaped dict from the observation's raw fields and runs it
    through the exact same ``story_components`` call a real candidate gets, so
    the key can never drift from what a real candidate for the same
    axis/metric/segment would receive. ``meta_recent_week_history`` is the
    fixed query_name ``insight_recent_week.py`` always uses (calendar or
    rolling), so the contract lookup resolves to the same metric_roles either
    way."""
    synthetic = {
        "level": "recent_week_rolling", "type": "recent_week_movement",
        "table": "meta_recent_week_history",
        "axis": observation.get("axis"), "metric": observation.get("metric"),
        "segment": observation.get("segment"),
    }
    contract = contracts.get("meta_recent_week_history") or {}
    key, _ = mem.story_components(synthetic, dataset_id, scope_h, contract, anchor)
    return key


def _annotate(candidates: list, contracts: dict, dataset_id: str, scope_h: str,
              anchor: str) -> list:
    out = []
    for cand in candidates:
        c = dict(cand)
        contract = contracts.get(c.get("table")) or {}
        c["level"] = _level_for(c, contract)
        key, fields = mem.story_components(c, dataset_id, scope_h, contract, anchor)
        c["story_key"] = key
        c["story_fields"] = fields
        out.append(c)
    return out


def _partition(candidates: list, suppressed: set) -> tuple[list, list]:
    eligible, dropped = [], []
    for c in candidates:
        (dropped if c.get("story_key") in suppressed else eligible).append(c)
    return eligible, dropped


def _cap_per_level(state: dict, candidates: list) -> list:
    """Keep the top-N (by score) eligible candidates within each level."""
    buckets: dict[str, list] = {}
    for c in candidates:
        buckets.setdefault(c.get("level", "high"), []).append(c)
    kept = []
    for level, items in buckets.items():
        items.sort(key=lambda c: c.get("score", 0.0), reverse=True)
        kept.extend(items[: _cap_for(state, level)])
    return kept


def _cap_overall(state: dict, business: list, dq: list) -> tuple[list, list]:
    """Apply the overall shortlist cap after memory suppression.

    The stat detector deliberately returns its full deduplicated candidate set.
    Applying this limit here prevents already-reported high scorers from hiding a
    lower-ranked unseen candidate before its story key is checked against memory.
    """
    cap = max(0, int(state.get("insight_stat_max_candidates", 20)))
    ranked = sorted(
        [("business", i, c) for i, c in enumerate(business)]
        + [("dq", i, c) for i, c in enumerate(dq)],
        key=lambda item: (-(item[2].get("score") or 0.0), item[1]),
    )[:cap]
    return (
        [c for kind, _i, c in ranked if kind == "business"],
        [c for kind, _i, c in ranked if kind == "dq"],
    )


def run(state: dict) -> dict:
    log = RunLogger(state)
    stats = state.get("insight_stat_candidates", {}) or {}
    business = list(stats.get("business_candidates", []) or [])
    dq = list(stats.get("data_quality_candidates", []) or [])
    detected = len(business) + len(dq)

    passthrough = dict(stats)  # preserve grand_totals_seen / additive / overall_pv / note

    if not state.get("insight_memory_enabled", True):
        log.info("Novelty filter: memory disabled - passing all candidates through.")
        contracts = state.get("insight_evidence_contracts", {}) or {}
        # Rolling-week is dropped even in the pass-through path (decision #9):
        # without persisted state it cannot know "since last reported," so
        # emitting it raw would just report the same reading every run.
        business_out = [c for c in business
                        if _level_for(c, contracts.get(c.get("table")) or {}) != "recent_week_rolling"]
        unseen_total = len(business_out) + len(dq)
        business_out, dq_out = _cap_overall(state, business_out, dq)
        eligible_out = len(business_out) + len(dq_out)
        novelty = {"detected": detected, "suppressed": 0, "eligible": eligible_out,
                   "selected": None, "policy": "disabled", "reason": "memory_disabled",
                   "memory_status": "disabled", "level_breakdown": {"high": eligible_out},
                   "watermark": None, "period_anchor": "", "resurfaced": 0,
                   "rolling_unavailable": bool(state.get("insight_rolling_observation")),
                   "unseen": unseen_total, "cap_dropped": unseen_total - eligible_out}
        file_io.write_json(state, "insight_novelty.json", novelty)
        eligible_payload = {**passthrough, "business_candidates": business_out,
                            "data_quality_candidates": dq_out}
        return {"insight_eligible_candidates": eligible_payload, "insight_novelty": novelty,
                **log.updates()}

    dataset_id = str(state.get("dataset_id") or "")
    scope_h = mem.scope_hash(state)
    watermark = mem.derive_watermark(state)
    anchor = mem.period_anchor(state, watermark)
    contracts = state.get("insight_evidence_contracts", {}) or {}

    business = _annotate(business, contracts, dataset_id, scope_h, anchor)
    dq = _annotate(dq, contracts, dataset_id, scope_h, anchor)

    memory, status = mem.load_store(state)

    # --- rolling-week: its own eligibility path, NEVER never_repeat/cooldown ---
    # (decision #9). Pulled out of `business` before the normal suppression
    # logic below runs, so it can never be affected by that policy.
    rolling_candidates = [c for c in business if c.get("level") == "recent_week_rolling"]
    business = [c for c in business if c.get("level") != "recent_week_rolling"]
    rolling_candidate = rolling_candidates[0] if rolling_candidates else None
    observation = state.get("insight_rolling_observation")
    rolling_out: list = []
    rolling_observation_update = None
    resurfaced_n = 0
    rolling_unavailable = False
    if observation:
        # Decision #16: exactly one place computes this key - reuse the real
        # candidate's key when one exists this run, else build it fresh from
        # the observation's raw fields via the same story_components() call.
        key = (rolling_candidate.get("story_key") if rolling_candidate
              else _rolling_key(observation, contracts, dataset_id, scope_h, anchor))
        rolling_observation_update = {**observation, "story_key": key}
        if status == "corrupt":
            rolling_unavailable = True
        elif rolling_candidate is not None:
            records = memory.get("records", {})
            if key not in records:
                rolling_out.append(rolling_candidate)  # unknown -> eligible
            else:
                rolling_state = (memory.get("rolling_state", {}) or {}).get(key)
                transitioned = ((not rolling_state or not rolling_state.get("active"))
                               and observation.get("active"))
                if transitioned:
                    rolling_out.append(rolling_candidate)  # inactive -> active
                    resurfaced_n += 1
                else:
                    growth_pct = float(state.get("insight_re_alert_growth_pct", 50))
                    delta_pct = float(state.get("insight_rolling_report_delta_pct", 5.0))
                    if mem.resurface_check(records[key], rolling_candidate, growth_pct, delta_pct):
                        rolling_out.append(rolling_candidate)  # material change
                        resurfaced_n += 1
                # otherwise: suppressed - no policy/cooldown consulted at all

    if status == "corrupt":
        log.error("Novelty filter: memory store is CORRUPT - novelty guarantee "
                  "UNAVAILABLE this run; emitting all candidates and refusing to "
                  "overwrite the damaged store.")
        eligible_b, eligible_d = business, dq
        suppressed_keys: set = set()
        reason = "memory_corrupt"
    else:
        policy = str(state.get("insight_memory_policy", "never_repeat"))
        cooldown = int(state.get("insight_memory_cooldown_days", 14))
        suppressed_keys = mem.suppressed(memory.get("records", {}), policy, cooldown)
        eligible_b, dropped_b = _partition(business, suppressed_keys)
        eligible_d, dropped_d = _partition(dq, suppressed_keys)
        reason = None

    unseen_total = len(eligible_b) + len(eligible_d) + len(rolling_out)
    eligible_b = _cap_per_level(state, eligible_b) + rolling_out
    eligible_d = _cap_per_level(state, eligible_d)
    eligible_b, eligible_d = _cap_overall(state, eligible_b, eligible_d)
    eligible_total = len(eligible_b) + len(eligible_d)
    cap_dropped = max(0, unseen_total - eligible_total)
    suppressed_n = sum(1 for c in business + dq if c.get("story_key") in suppressed_keys)

    level_breakdown: dict[str, int] = {}
    for c in eligible_b + eligible_d:
        level_breakdown[c.get("level", "high")] = level_breakdown.get(c.get("level", "high"), 0) + 1

    if reason is None:
        if detected == 0:
            reason = "no_notable_findings"
        elif eligible_total == 0:
            reason = "all_previously_reported"
        else:
            reason = "ok"

    eligible_payload = {
        **passthrough,
        "business_candidates": eligible_b,
        "data_quality_candidates": eligible_d,
    }
    novelty = {
        "detected": detected,
        "suppressed": suppressed_n,
        "eligible": eligible_total,
        "selected": None,
        "policy": str(state.get("insight_memory_policy", "never_repeat")),
        "reason": reason,
        "memory_status": status,
        "level_breakdown": level_breakdown,
        "watermark": watermark,
        "period_anchor": anchor,
        "resurfaced": resurfaced_n,
        "rolling_unavailable": rolling_unavailable,
        "unseen": unseen_total,
        "cap_dropped": cap_dropped,
    }
    file_io.write_json(state, "insight_novelty.json", novelty)
    log.info(
        f"Novelty filter: detected={detected} suppressed={suppressed_n} "
        f"unseen={unseen_total} eligible={eligible_total} cap_dropped={cap_dropped} "
        f"(status={status}, policy={novelty['policy']}, "
        f"levels={level_breakdown or '{}'})."
    )
    updates = {"insight_eligible_candidates": eligible_payload, "insight_novelty": novelty,
              **log.updates()}
    if rolling_observation_update is not None:
        updates["insight_rolling_observation"] = rolling_observation_update
    return updates
