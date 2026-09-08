"""Adaptive investigation: buying explanation in proportion to the day's news.

    python scripts/replay_escalation.py

Offline - no auth, no LLM, no network.

Every run currently costs the same whether the business had a dramatic day or
an entirely ordinary one, because the signal cap and the probe budget are fixed
numbers in config. `src/tools/escalation.py` turns the count of *unreported
material findings* - which the pipeline has already computed, for free, by the
time the novelty filter finishes - into that budget.

The load-bearing guarantee is the one that is easiest to break by accident:

**Enabling this may only ever lower a budget.** Every tier is floored with
`min()` against the configured value. A tier that returned its own number
directly would silently *raise* spend on any client whose config is tighter
than the tier - a cost control that increases cost, discovered on the invoice.

Two further properties this pins:

* **A quiet day is not a silent one.** The summary branch is untouched; the
  descriptive report still publishes in full. What a quiet day skips is the
  investigative spend, which by definition has nothing new to investigate.
* **An unscored candidate is counted, not dropped.** Discarding unknowns would
  let the materiality floor silence a story the detector merely could not
  measure - the gate would then be quietest exactly when it understood least.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import insight_novelty_filter, insight_signal_detector  # noqa: E402
from src.tools import escalation  # noqa: E402

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    _failures.append(label)


def eligible(business: int = 0, data_quality: int = 0, score: float = 10.0) -> dict:
    """The novelty filter's shortlist shape, which is a dict, not a list."""
    return {
        "business_candidates": [
            {"candidate_id": f"b{i}", "score": score} for i in range(business)],
        "data_quality_candidates": [
            {"candidate_id": f"d{i}", "score": score} for i in range(data_quality)],
    }


def state(**over) -> dict:
    base = {
        "adaptive_investigation_enabled": True,
        "adaptive_investigation_min_score": 0.0,
        "insight_max_new_per_run": 3,
        "insight_max_investigation_rounds": 3,
    }
    base.update(over)
    return base


# ------------------------------------------------------------------ the tiers


def test_the_three_tiers() -> None:
    print("\n=== the day's news picks the tier ===")

    quiet = escalation.decide(state(), eligible(business=0))
    check("nothing unreported survived -> quiet", quiet["tier"] == "quiet", quiet)
    check("quiet buys no signals", quiet["insight_max_new_per_run"] == 0)
    check("quiet buys no probes", quiet["insight_max_investigation_rounds"] == 0)

    for count in (1, 3, 5):
        plan = escalation.decide(state(), eligible(business=count))
        check(f"{count} finding(s) -> ordinary", plan["tier"] == "ordinary", plan)
        check(f"{count} finding(s) buys a reduced budget",
              plan["insight_max_new_per_run"] == 2
              and plan["insight_max_investigation_rounds"] == 1, plan)

    for count in (6, 12, 40):
        plan = escalation.decide(state(), eligible(business=count))
        check(f"{count} findings -> eventful", plan["tier"] == "eventful", plan)
        check(f"{count} findings keeps the configured budget unchanged",
              plan["insight_max_new_per_run"] == 3
              and plan["insight_max_investigation_rounds"] == 3, plan)

    # The boundary between quiet and ordinary is the expensive one to get
    # wrong: one finding off and a real story goes unexplained.
    check("exactly 1 finding is ordinary, not quiet",
          escalation.decide(state(), eligible(business=1))["tier"] == "ordinary")
    check("exactly 6 findings is eventful, not ordinary",
          escalation.decide(state(), eligible(business=6))["tier"] == "eventful")

    # Data-quality findings are still findings; a day full of them is not quiet.
    mixed = escalation.decide(state(), eligible(business=2, data_quality=5))
    check("business and data-quality candidates are counted together",
          mixed["material_eligible"] == 7 and mixed["tier"] == "eventful", mixed)


def test_budgets_are_never_raised() -> None:
    print("\n=== enabling this can never increase spend ===")

    # A config tighter than every tier's own number. If a tier returned its
    # number directly instead of min()-ing it, this is where cost silently
    # rises - and nothing else in the pipeline would notice.
    tight = state(insight_max_new_per_run=1, insight_max_investigation_rounds=0)

    for count, label in ((0, "quiet"), (3, "ordinary"), (30, "eventful")):
        plan = escalation.decide(tight, eligible(business=count))
        check(f"{label}: signals never exceed config",
              plan["insight_max_new_per_run"] <= 1, plan)
        check(f"{label}: probes never exceed config",
              plan["insight_max_investigation_rounds"] <= 0, plan)

    # Specifically the ordinary tier, whose own numbers (2 signals, 1 probe)
    # are both larger than this config allows.
    ordinary = escalation.decide(tight, eligible(business=3))
    check("the ordinary tier is floored to config, not to its own 2/1",
          ordinary["insight_max_new_per_run"] == 1
          and ordinary["insight_max_investigation_rounds"] == 0, ordinary)

    # And across a spread of configs, exhaustively.
    for cfg_signals in range(0, 6):
        for cfg_rounds in range(0, 6):
            cfg = state(insight_max_new_per_run=cfg_signals,
                        insight_max_investigation_rounds=cfg_rounds)
            for count in (0, 1, 5, 6, 20):
                plan = escalation.decide(cfg, eligible(business=count))
                if (plan["insight_max_new_per_run"] > cfg_signals
                        or plan["insight_max_investigation_rounds"] > cfg_rounds):
                    check("no tier raises a budget above config, for any config",
                          False, f"config={cfg_signals}/{cfg_rounds} "
                                 f"count={count} plan={plan}")
                    return
    check("no tier raises a budget above config, for any config", True)


def test_the_materiality_floor() -> None:
    print("\n=== the materiality floor, and what it must not discard ===")

    trivial = {"business_candidates": [{"score": 0.2} for _ in range(9)],
               "data_quality_candidates": []}
    check("a day of trivial movements is not eventful",
          escalation.decide(state(adaptive_investigation_min_score=1.0),
                            trivial)["tier"] == "quiet")
    check("with no floor the same day counts every finding",
          escalation.decide(state(), trivial)["tier"] == "eventful")

    # An unscored candidate is an unknown, not a zero. Dropping it would let
    # the gate go quietest precisely where the detector understood least.
    unscored = {"business_candidates": [{"candidate_id": "b0"},
                                        {"candidate_id": "b1", "score": None}],
                "data_quality_candidates": []}
    plan = escalation.decide(state(adaptive_investigation_min_score=5.0), unscored)
    check("a candidate carrying no score is counted, not dropped",
          plan["material_eligible"] == 2, plan)

    unreadable = {"business_candidates": [{"score": "not a number"}],
                  "data_quality_candidates": []}
    check("an unreadable score is counted rather than raising",
          escalation.decide(state(adaptive_investigation_min_score=5.0),
                            unreadable)["material_eligible"] == 1)

    # The floor compares magnitude: a large decline is as material as a rise.
    signed = {"business_candidates": [{"score": -9.0}], "data_quality_candidates": []}
    check("the floor reads magnitude, so a decline still counts",
          escalation.decide(state(adaptive_investigation_min_score=5.0),
                            signed)["material_eligible"] == 1)


def test_the_payload_shape() -> None:
    print("\n=== the shortlist is a dict, and reading it as a list is a bug ===")

    payload = eligible(business=4, data_quality=2)

    # Iterating the dict yields its two KEYS, which would make every single day
    # look equally eventful - a cost control that never varies with the news.
    check("the dict payload counts its candidates, not its keys",
          escalation.decide(state(), payload)["material_eligible"] == 6)
    check("reading it as a list would have given 2, and does not",
          escalation.decide(state(), payload)["material_eligible"] != len(payload))

    # A bare list is still accepted, so a caller with the older shape works.
    check("a bare list of candidates is accepted",
          escalation.decide(state(), [{"score": 1.0}] * 7)["material_eligible"] == 7)

    for junk in (None, "", 0, {"unexpected": [1, 2, 3]}):
        check(f"an unusable payload reads as quiet rather than raising ({junk!r})",
              escalation.decide(state(), junk)["tier"] == "quiet")


def test_disabled_is_inert() -> None:
    print("\n=== off reproduces fixed budgets exactly ===")

    off = state(adaptive_investigation_enabled=False)
    check("the gate reports itself off", not escalation.enabled(off))
    check("a config that predates this is off", not escalation.enabled({}))

    updates = insight_novelty_filter.run(_novelty_state(off, candidates=0))
    check("the novelty filter writes no escalation plan while off",
          "insight_escalation" not in updates, sorted(updates))
    check("and does not touch the configured budgets",
          "insight_max_new_per_run" not in updates
          and "insight_max_investigation_rounds" not in updates)


# ------------------------------------------- the seam into the two live nodes


def _novelty_state(base: dict, candidates: int, memory: bool = True) -> dict:
    """Enough state for insight_novelty_filter.run to reach the escalation call."""
    stats = [{"candidate_id": f"c{i}",
              "analysis_type": "contribution",
              "kind": "business",
              "metric": "Total Revenue",
              "dimension": "division_name",
              "segment": f"SEG{i}",
              "score": 10.0,
              "impact_value": 1000.0 * (i + 1)}
             for i in range(candidates)]
    return dict(base,
                insight_memory_enabled=memory,
                # An empty store, so every candidate reads as unreported and
                # the count under test is the one the tiers actually see.
                insight_memory_root="outputs_replay/escalation/memory",
                insight_candidates_high=50,
                insight_stat_max_candidates=50,
                dataset_id="replay-escalation",
                output_folder="outputs_replay/escalation",
                insight_stat_candidates={"business_candidates": stats,
                                         "data_quality_candidates": []})


def test_the_novelty_filter_sizes_the_budget() -> None:
    print("\n=== the novelty filter is where the budget is decided ===")

    quiet = insight_novelty_filter.run(_novelty_state(state(), candidates=0))
    check("a quiet day writes the plan into state",
          quiet.get("insight_escalation", {}).get("tier") == "quiet",
          quiet.get("insight_escalation"))
    check("and lowers both budgets to zero",
          quiet.get("insight_max_new_per_run") == 0
          and quiet.get("insight_max_investigation_rounds") == 0)
    check("the reason is written in plain words for the run log",
          "material unreported finding" in quiet["insight_escalation"]["reason"],
          quiet["insight_escalation"]["reason"])

    busy = insight_novelty_filter.run(_novelty_state(state(), candidates=8))
    check("an eventful day keeps the configured budget",
          busy.get("insight_max_new_per_run") == 3
          and busy.get("insight_max_investigation_rounds") == 3,
          busy.get("insight_escalation"))

    # The plan records what config allowed as well as what was bought, so the
    # log can show the saving rather than just the number spent.
    plan = quiet["insight_escalation"]
    check("the plan records the configured budget it lowered from",
          plan["configured_max_new_per_run"] == 3
          and plan["configured_max_investigation_rounds"] == 3, plan)

    # The gate sits inside the memory-enabled path on purpose: "unreported"
    # is a statement about memory, and without a store every candidate looks
    # new every morning, so the count would say "eventful" every single day.
    # Sizing a budget from that number would be worse than not sizing it, so
    # the feature is deliberately inert here rather than confidently wrong.
    no_memory = insight_novelty_filter.run(
        _novelty_state(state(), candidates=0, memory=False))
    check("without cross-run memory the gate is inert, not confidently wrong",
          "insight_escalation" not in no_memory, sorted(no_memory))
    check("and it leaves the configured budgets alone",
          "insight_max_new_per_run" not in no_memory
          and "insight_max_investigation_rounds" not in no_memory)


def test_a_quiet_day_returns_before_the_llm() -> None:
    print("\n=== a quiet day skips the LLM, not the report ===")

    def explode(*_a, **_k):
        raise AssertionError("the signal detector built an LLM on a quiet day")

    original = insight_signal_detector.get_llm
    insight_signal_detector.get_llm = explode  # type: ignore[attr-defined]
    try:
        out = insight_signal_detector.run({
            "insight_memory_enabled": True,
            "insight_max_new_per_run": 0,
            "output_folder": "outputs_replay/escalation",
            "insight_escalation": {"tier": "quiet"},
            "insight_eligible_candidates": {"business_candidates": [],
                                            "data_quality_candidates": []},
            "insight_stat_candidates": [],
        })
    finally:
        insight_signal_detector.get_llm = original  # type: ignore[attr-defined]

    check("a zero cap returns no signals without calling the model",
          out.get("insight_signals") == [], out.get("insight_signals"))
    check("and the run log says why, naming the tier",
          any("escalation tier=quiet" in line for line in out.get("logs", [])),
          out.get("logs"))

    # The summary branch shares no key with any of this. A quiet day must not
    # reach into the descriptive report at all.
    summary_keys = [k for k in out if k.startswith("summary_")
                    or k.startswith("fresh_summary")]
    check("the summary branch is untouched on a quiet day",
          not summary_keys, summary_keys)


def main() -> int:
    print("=" * 72)
    print("Adaptive investigation: tiers, floors, and the budget it may not raise")
    print("=" * 72)

    test_the_three_tiers()
    test_budgets_are_never_raised()
    test_the_materiality_floor()
    test_the_payload_shape()
    test_disabled_is_inert()
    test_the_novelty_filter_sizes_the_budget()
    test_a_quiet_day_returns_before_the_llm()

    print("\n" + "=" * 72)
    if _failures:
        print(f"ESCALATION FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
