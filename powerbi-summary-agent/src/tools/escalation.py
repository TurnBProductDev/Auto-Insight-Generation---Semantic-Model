"""Let the day's news decide how much investigation to buy.

Every run currently costs the same whether the business had a dramatic day or
an entirely ordinary one: the signal cap and the investigator's probe budget
are fixed numbers in config, read identically on a morning with six new
findings and on a morning with none.

That is the wrong shape. The pipeline already *knows* how eventful the day
was before it spends anything on explaining it - `insight_stat_detector`
computes every candidate deterministically, and `insight_novelty_filter` has
already removed the ones that were reported on an earlier run. What survives
both is, precisely, "material things we have not said yet". This turns that
count into the budget.

The tiers are deliberately coarse, because the input is a count of findings
and a finer gradation would imply a precision it does not have:

* **quiet** - nothing unreported survived. Publish the deterministic page and
  buy no investigation at all. This is the case the fixed budget wastes most.
* **ordinary** - a few findings. Explain the best of them.
* **eventful** - a lot changed. Spend the full budget, exactly as today.

Two guarantees the caller depends on:

1. **It only ever lowers a budget.** `min()` against the configured value, so
   turning this on can never make a run more expensive or more talkative than
   its config already permits.
2. **Quiet is not silent.** The summary branch is untouched - the descriptive
   report still publishes in full. What a quiet day skips is the *investigative*
   spend, which by definition has nothing new to investigate.

Off by default (``adaptive_investigation_enabled``), so a config that predates
this behaves exactly as before.
"""

from __future__ import annotations

from typing import Any, Dict, List

#: (name, minimum eligible findings, signal cap, probe rounds per signal)
TIERS = (
    ("eventful", 6, None, None),   # None = keep whatever config allows
    ("ordinary", 1, 2, 1),
    ("quiet",    0, 0, 0),
)


def enabled(state: dict) -> bool:
    return bool(state.get("adaptive_investigation_enabled"))


def _candidates(payload: Any) -> List[Dict[str, Any]]:
    """Flatten the novelty filter's eligible payload into a list of findings.

    The payload is the shortlist dict the signal detector consumes
    (``business_candidates`` / ``data_quality_candidates``), not a bare list -
    reading it as a list yields its *keys* and would make every day look
    equally eventful. A list is still accepted so the function can be called
    with either shape.
    """
    if isinstance(payload, dict):
        out: List[Dict[str, Any]] = []
        for key in ("business_candidates", "data_quality_candidates"):
            value = payload.get(key)
            if isinstance(value, list):
                out.extend(c for c in value if isinstance(c, dict))
        return out
    if isinstance(payload, list):
        return [c for c in payload if isinstance(c, dict)]
    return []


def _material(candidates: List[Dict[str, Any]], floor: float) -> int:
    """How many eligible findings clear the materiality floor.

    A candidate with no score is counted rather than dropped: an unscored
    finding is an unknown, and quietly discarding unknowns would let the gate
    silence a real story it simply could not measure.
    """
    if floor <= 0:
        return len(candidates)
    count = 0
    for c in candidates:
        try:
            score = c.get("score")
            if score is None or abs(float(score)) >= floor:
                count += 1
        except Exception:
            count += 1
    return count


def decide(state: dict, eligible: Any) -> Dict[str, Any]:
    """Return the tier and the budgets it implies, plus why.

    The returned budgets are already floored against config, so the caller can
    apply them directly.
    """
    configured_signals = int(state.get("insight_max_new_per_run", 3) or 0)
    configured_rounds = int(state.get("insight_max_investigation_rounds", 3) or 0)
    floor = float(state.get("adaptive_investigation_min_score", 0) or 0)

    count = _material(_candidates(eligible), floor)
    for name, threshold, signals, rounds in TIERS:
        if count >= threshold:
            tier = name
            max_signals = configured_signals if signals is None \
                else min(signals, configured_signals)
            max_rounds = configured_rounds if rounds is None \
                else min(rounds, configured_rounds)
            break
    else:  # pragma: no cover - TIERS ends at 0, so this cannot be reached
        tier, max_signals, max_rounds = "eventful", configured_signals, configured_rounds

    return {
        "tier": tier,
        "material_eligible": count,
        "insight_max_new_per_run": max_signals,
        "insight_max_investigation_rounds": max_rounds,
        "configured_max_new_per_run": configured_signals,
        "configured_max_investigation_rounds": configured_rounds,
        "reason": (f"{count} material unreported finding(s) -> {tier}: "
                   f"up to {max_signals} signal(s), {max_rounds} probe(s) each"),
    }
