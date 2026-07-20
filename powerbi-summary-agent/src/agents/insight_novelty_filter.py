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
    the ``period`` level (validated sub-annual series); daily is a later phase."""
    kind = str((contract or {}).get("coverage_kind", "")).lower()
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
    }.get(level, 20)


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


def run(state: dict) -> dict:
    log = RunLogger(state)
    stats = state.get("insight_stat_candidates", {}) or {}
    business = list(stats.get("business_candidates", []) or [])
    dq = list(stats.get("data_quality_candidates", []) or [])
    detected = len(business) + len(dq)

    passthrough = dict(stats)  # preserve grand_totals_seen / additive / overall_pv / note

    if not state.get("insight_memory_enabled", True):
        log.info("Novelty filter: memory disabled - passing all candidates through.")
        novelty = {"detected": detected, "suppressed": 0, "eligible": detected,
                   "selected": None, "policy": "disabled", "reason": "memory_disabled",
                   "memory_status": "disabled", "level_breakdown": {"high": detected},
                   "watermark": None, "period_anchor": ""}
        file_io.write_json(state, "insight_novelty.json", novelty)
        return {"insight_eligible_candidates": passthrough, "insight_novelty": novelty,
                **log.updates()}

    dataset_id = str(state.get("dataset_id") or "")
    scope_h = mem.scope_hash(state)
    watermark = mem.derive_watermark(state)
    anchor = mem.period_anchor(state, watermark)
    contracts = state.get("insight_evidence_contracts", {}) or {}

    business = _annotate(business, contracts, dataset_id, scope_h, anchor)
    dq = _annotate(dq, contracts, dataset_id, scope_h, anchor)

    memory, status = mem.load_store(state)
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

    eligible_b = _cap_per_level(state, eligible_b)
    eligible_d = _cap_per_level(state, eligible_d)
    eligible_total = len(eligible_b) + len(eligible_d)
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
    }
    file_io.write_json(state, "insight_novelty.json", novelty)
    log.info(
        f"Novelty filter: detected={detected} suppressed={suppressed_n} "
        f"eligible={eligible_total} (status={status}, policy={novelty['policy']}, "
        f"levels={level_breakdown or '{}'})."
    )
    return {"insight_eligible_candidates": eligible_payload, "insight_novelty": novelty,
            **log.updates()}
