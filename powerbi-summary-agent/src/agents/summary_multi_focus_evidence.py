"""Multi-focus deep-dive evidence (summary-only, R4).

Runs a bounded deep dive for EACH selected focus in priority order, reusing the
verified single-focus builder (``summary_focus_evidence.run``) under one SHARED
query budget, and replaces an emergent-duplicate focus (two focuses that only
turn out to share a leading driver/location once drilled) with the next diverse
reserve. Gated behind ``summary_r4_enabled``; on the single-focus path the old
``summary_focus_evidence`` node still runs unchanged.

Concurrency contract: writes only summary-branch keys, executes with the
pre-fetched token (inherited by the reused builder), never LLM-repairs DAX, and
is non-fatal - a failed focus degrades to fewer focuses.
"""

from __future__ import annotations

from ..tools import file_io, summary_memory, summary_portfolio
from ..utils.logger import RunLogger
from . import summary_focus_evidence

_SIG_FIELDS = ("top_pos_contributor", "top_neg_contributor", "leading_location", "driver_class")


def _norm(value) -> str:
    return summary_memory._norm_text(value)


def _deep_dive_one(state: dict, focus: dict, candidates: list[dict], per_focus_max: int) -> dict:
    """Deep-dive one focus under a per-focus budget; returns its evidence doc.

    Reuses the single-focus node by pointing it at ``focus`` with the shared
    candidate pool and a capped budget. Isolated here so the orchestration can be
    offline-tested without live DAX.
    """
    sub = dict(state)
    sub["summary_selected_focus"] = focus
    sub["summary_eligible_candidates"] = candidates
    sub["summary_focus_enabled"] = True
    sub["summary_focus_deep_dive_enabled"] = True
    sub["summary_focus_max_queries"] = max(0, int(per_focus_max))
    result = summary_focus_evidence.run(sub)
    return result.get("summary_focus_evidence") or {}


def _emergent_duplicate(signature: dict, accepted: list[dict], threshold: float) -> bool:
    """True when a drilled signature repeats an already-accepted focus this run.

    Only catches collisions that were NOT visible at selection (a shared leading
    driver/location discovered during the drill); at least two signature fields
    must be comparable so a single generic driver alone cannot force a duplicate.
    """
    if not signature or threshold <= 0:
        return False
    for other in accepted:
        comparable = [field for field in _SIG_FIELDS if signature.get(field) and other.get(field)]
        if len(comparable) < 2:
            continue
        matches = sum(1 for field in comparable if _norm(signature.get(field)) == _norm(other.get(field)))
        if matches / len(comparable) >= threshold:
            return True
    return False


def _reserve_ok(reserve: dict, accepted_focuses: list[dict], threshold: float) -> bool:
    """A reserve may replace a slot only if it stays diverse from accepted focuses."""
    for focus in accepted_focuses:
        if reserve.get("area_key") and reserve.get("area_key") == focus.get("area_key"):
            return False
        if summary_portfolio._is_parent_child(reserve, focus):
            return False
        if threshold > 0 and summary_portfolio._fact_overlap(reserve, focus) >= threshold:
            return False
    return True


def run(state: dict) -> dict:
    log = RunLogger(state)
    if not state.get("summary_r4_enabled", False):
        return {**log.updates()}

    selected = list(state.get("summary_selected_focuses") or [])
    reserves = list(state.get("summary_portfolio_reserves") or [])
    if not selected:
        file_io.write_json(state, "summary_multi_focus_evidence.json", {"focuses": []})
        # Output folders can be reused across runs.  Replace the keyed audit as
        # well so yesterday's focus evidence can never masquerade as today's.
        file_io.write_json(state, "summary_focus_evidence_by_key.json", {})
        log.info("Multi-focus evidence: no focus selected; Overall Performance only.")
        return {"summary_focus_evidence_by_key": {}, **log.updates()}

    total = max(1, int(state.get("summary_focus_total_deep_dive_queries", 15)))
    per_focus_cap = max(1, int(state.get("summary_focus_max_queries_per_focus", 5)))
    max_repl = max(0, int(state.get("summary_focus_max_replacements_per_slot", 1)))
    threshold = float(state.get("summary_focus_fact_overlap_threshold", 0.6) or 0.0)
    target = len(selected)

    # All candidate ids the reused builder may need to resolve.
    candidate_pool = selected + reserves

    evidence_by_key: dict = {}
    accepted: list[dict] = []
    accepted_signatures: list[dict] = []
    used = 0
    replacements = 0
    reserve_queue = list(reserves)
    queue = list(selected)

    while queue and len(accepted) < target:
        focus = queue.pop(0)
        remaining = total - used
        if remaining <= 0:
            break
        later_slots = target - len(accepted) - 1
        # Reserve at least one call per still-unfilled slot so the first focus
        # cannot starve the others, while still guaranteeing this focus >= 1 call
        # when any budget remains; the per-focus cap bounds the top.
        this_max = min(per_focus_cap, max(1, remaining - later_slots))
        doc = _deep_dive_one(state, focus, candidate_pool, this_max)
        used += int(doc.get("queries_attempted", 0) or 0)
        signature = doc.get("signature_fields") or {}

        duplicate = _emergent_duplicate(signature, accepted_signatures, threshold)
        if duplicate:
            # Pull the next diverse reserve to replace this emergent duplicate;
            # the spent queries still count. If none fits (or no replacement
            # budget remains), publish fewer instead of knowingly repeating the
            # same drilled story in two focus slots.
            replacement = None
            if replacements < max_repl and (total - used) >= 1:
                while reserve_queue:
                    candidate = reserve_queue.pop(0)
                    if _reserve_ok(candidate, accepted, threshold):
                        replacement = candidate
                        break
            if replacement is not None:
                replacements += 1
                queue.insert(0, replacement)
                log.info(f"Multi-focus evidence: {focus.get('segment')} was an emergent duplicate; trying a reserve.")
            else:
                log.info(f"Multi-focus evidence: {focus.get('segment')} was an emergent duplicate; publishing fewer focuses.")
            continue

        focus_key = str(focus.get("focus_key") or focus.get("candidate_id") or len(accepted))
        doc["selection"] = focus.get("selection")
        doc["materiality_facts"] = focus.get("materiality_facts")
        evidence_by_key[focus_key] = doc
        accepted.append(focus)
        accepted_signatures.append(signature)

    # Re-order the delivered portfolio to the accepted set (may be fewer).
    delivered = accepted
    alias_evidence = evidence_by_key.get(str(delivered[0].get("focus_key"))) if delivered else {}
    file_io.write_json(state, "summary_multi_focus_evidence.json", {
        "focuses": [
            {"focus_key": f.get("focus_key"), "segment": f.get("segment"),
             "role": f.get("dimension_role"),
             "queries_attempted": (evidence_by_key.get(str(f.get("focus_key"))) or {}).get("queries_attempted")}
            for f in delivered
        ],
        "total_queries_used": used,
        "total_budget": total,
        "replacements": replacements,
    })
    # Persist the COMPLETE per-focus evidence. The reused single-focus node
    # overwrites summary_focus_evidence.json on every call (last focus wins), so
    # this keyed file is the full audit trail for all delivered focuses.
    file_io.write_json(state, "summary_focus_evidence_by_key.json", evidence_by_key)
    log.info(
        "Multi-focus evidence: %d focus(es) deep-dived over %d/%d shared quer(y/ies), %d replacement(s)."
        % (len(delivered), used, total, replacements)
    )
    return {
        "summary_selected_focuses": delivered,
        "summary_focus_evidence_by_key": evidence_by_key,
        # Backward-compat aliases for existing single-focus consumers.
        "summary_selected_focus": delivered[0] if delivered else {},
        "summary_focus_evidence": alias_evidence or {},
        **log.updates(),
    }
