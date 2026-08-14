"""WP2: the measurement spine, aggregation classes and ranking registry.

    python scripts/replay_kernel_spine.py

Offline - no auth, no LLM, no network.

The three things this must prove
-------------------------------
1. **Sales YoY is unchanged.** The period-over-period spine classifies and ranks
   the committed acceptance artifacts identically to the code path that produced
   them. (`golden_master.py` proves the same thing end to end; this proves it at
   the seam, so a failure says *which* part moved.)
2. **A semi-additive measure fails additive verification.** The brief calls this
   the entire point of the aggregation work, because the failure is invisible
   downstream: parts and whole are summed the same wrong way, so every existing
   reconciliation check passes on a number that is Nx too big.
3. **Unmeasurable is not a pass.** Both live inventory facts hold one snapshot,
   so semi-additivity cannot be tested there. That must come back UNVERIFIABLE,
   never "additive, confirmed".

The numbers in the semi-additive tests are the ones actually measured against
`SSR TREND` on 2026-08-13 (see docs/domain-verticals-findings.md §4), so this
test fails if the judgement drifts away from real observed data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.sales import spines as sales_spines  # noqa: E402
from src.kernel import aggregation, ranking  # noqa: E402
from src.kernel import spine as kernel_spine  # noqa: E402
from src.tools import summary_coverage as coverage  # noqa: E402
from src.tools import summary_materiality as materiality  # noqa: E402

FIXTURE_DIR = PROJECT_ROOT / "tests" / "fixtures" / "models"

# Measured live on 2026-08-13 from SSR TREND (findings §4a).
LIVE_SNAPSHOTS = [51677750.95553299, 52479645.71366396,
                  49775351.19328705, 50833557.23300002]
LIVE_SUM = 204766305.09548372
LIVE_LATEST = 50833557.23300002

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


# ------------------------------------------------------- 1. the spine protocol


def test_protocol() -> None:
    print("\n=== the spine protocol ===")

    spine = sales_spines.PeriodOverPeriodSpine()
    check("the sales spine satisfies the protocol",
          isinstance(spine, kernel_spine.MeasurementSpine))
    check("it names its baseline in English, because the label is printed",
          spine.baseline_label == "the same period last year",
          f"baseline_label={spine.baseline_label!r}")
    check("its delta is an absolute movement", spine.delta_kind() == kernel_spine.ABSOLUTE)
    check("delta and exposure share a unit for a value comparison",
          spine.delta_unit() == spine.exposure_unit() == "value")

    print("\n--- the vocabulary the live models forced in ---")
    check("'distance' is a delta kind (a policy band is days outside a limit)",
          kernel_spine.DISTANCE in kernel_spine.DELTA_KINDS)
    check("'none' is a delta kind (a snapshot with no baseline has no delta)",
          kernel_spine.NONE in kernel_spine.DELTA_KINDS)
    check("'baseline_missing' is a classification, distinct from current_only",
          kernel_spine.BASELINE_MISSING in kernel_spine.CLASSIFICATIONS
          and kernel_spine.BASELINE_MISSING != kernel_spine.CURRENT_ONLY)

    print("\n--- measures and the delta expression ---")
    bundled = sales_spines.PeriodOverPeriodSpine(
        {"measures": {"current": "Revenue Current", "prior": "Revenue Prior",
                      "change": "Revenue Growth"}})
    check("the prior slot is exposed as 'baseline', the spine's own word",
          bundled.measures() == {"current": "Revenue Current",
                                 "baseline": "Revenue Prior",
                                 "change": "Revenue Growth"},
          f"{bundled.measures()}")
    check("the delta expression prefers the model's own change measure",
          bundled.delta_expr() == "[Revenue Growth]", bundled.delta_expr())

    no_change = sales_spines.PeriodOverPeriodSpine(
        {"measures": {"current": "Net Bills Current", "prior": "Bills Prior"}})
    check("with no change measure it subtracts, rather than giving up",
          no_change.delta_expr() == "[Net Bills Current] - [Bills Prior]",
          no_change.delta_expr())
    check("with neither side it returns empty rather than invalid DAX",
          sales_spines.PeriodOverPeriodSpine().delta_expr() == "")

    print("\n--- registry ---")
    check("the sales spine is registered",
          "period_over_period" in kernel_spine.available())
    check("re-registering the same class is a no-op",
          kernel_spine.register("period_over_period",
                                sales_spines.PeriodOverPeriodSpine) is not None)
    try:
        kernel_spine.register("period_over_period", dict)
        check("rebinding a name to a DIFFERENT class is refused", False,
              "no error raised")
    except ValueError:
        check("rebinding a name to a DIFFERENT class is refused", True)
    try:
        kernel_spine.get("no_such_spine")
        check("an unknown spine name raises", False, "no error raised")
    except KeyError:
        check("an unknown spine name raises", True)


# ------------------------------------------- 2. Sales YoY behaviour unchanged


def test_sales_unchanged() -> None:
    print("\n=== the sales spine reproduces today's classification exactly ===")

    universe_path = PROJECT_ROOT / "outputs_scanb" / "summary_focus_universe.json"
    if not universe_path.exists():
        check("committed universe fixture is present", False, str(universe_path))
        return
    universe = json.loads(universe_path.read_text(encoding="utf-8"))

    spine = sales_spines.PeriodOverPeriodSpine()
    members = [m for role in (universe.get("roles") or {}).values()
               for m in (role.get("members") or [])]
    check(f"the fixture supplies members to test ({len(members)})", bool(members))

    mismatches = [
        m for m in members
        if coverage.is_comparable(m) != (spine.classify(m) == kernel_spine.COMPARABLE)
    ]
    check("spine.classify agrees with is_comparable on every real member",
          not mismatches,
          f"{len(mismatches)} disagreement(s), e.g. {mismatches[:2]}")

    check("routing is_comparable THROUGH the spine gives the same answer",
          all(coverage.is_comparable(m) == coverage.is_comparable(m, spine)
              for m in members))

    # The percentage must match the one the ranking already uses, or the spine
    # and the blend would disagree about the same member.
    pct_mismatch = []
    for member in members:
        if not coverage.is_comparable(member):
            continue
        change = materiality.area_change(member.get("current"), member.get("prior"))
        expected = materiality.area_change_pct(change, member.get("prior"))
        actual = spine.pct(member.get("current"), member.get("prior"))
        if expected != actual:
            pct_mismatch.append((member.get("member"), expected, actual))
    check("spine.pct matches the existing percentage on every member",
          not pct_mismatch, f"{pct_mismatch[:3]}")

    print("\n--- classification is exhaustive and distinguishes the states ---")
    check("a member with both sides is comparable",
          spine.classify({"current": 10.0, "prior": 8.0}) == kernel_spine.COMPARABLE)
    check("a member with no prior is current_only, NOT baseline_missing",
          spine.classify({"current": 10.0}) == kernel_spine.CURRENT_ONLY)
    check("a member with no current is baseline_missing",
          spine.classify({"prior": 8.0}) == kernel_spine.BASELINE_MISSING)
    check("a member with neither is inactive",
          spine.classify({}) == kernel_spine.INACTIVE)


def test_ranking_registry() -> None:
    print("\n=== the ranking registry ===")

    universe_path = PROJECT_ROOT / "outputs_scanb" / "summary_focus_universe.json"
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    role = next(iter((universe.get("roles") or {}).values()))
    members = list(role.get("members") or [])
    peer_median = coverage.peer_median_change_pct(members)

    direct = coverage.rank_scores(members, peer_median)
    through_registry = ranking.get("impact_magnitude_unexpectedness")(members, peer_median)
    check("the existing blend reached BY NAME is byte-identical to calling it",
          direct == through_registry,
          f"direct[:3]={direct[:3]} registry[:3]={through_registry[:3]}")

    via_param = coverage.rank_scores(members, peer_median,
                                     blend="impact_magnitude_unexpectedness")
    check("and identical again through the blend= parameter", direct == via_param)
    check("omitting blend= keeps the original path (this is what keeps YoY safe)",
          coverage.rank_scores(members, peer_median) == direct)

    try:
        ranking.get("no_such_blend")
        check("an unknown blend name raises", False, "no error raised")
    except KeyError:
        check("an unknown blend name raises", True)

    print("\n--- the change-free blend (no signed change exists) ---")
    # Modelled on the real ageing shape: a severe exception on a trivial value
    # must not outrank a moderate one on a large value.
    exceptions = [
        {"member": "tiny but extreme", "severity_score": 100.0,
         "exposure_value": 400.0, "persistence_days": 5},
        {"member": "large and moderate", "severity_score": 20.0,
         "exposure_value": 2_000_000.0, "persistence_days": 5},
    ]
    scores = ranking.severity_exposure_persistence(exceptions)
    check("exposure keeps a trivial-but-extreme item from leading",
          scores[1] > scores[0], f"tiny={scores[0]:.4f} large={scores[1]:.4f}")

    missing_duration = [
        {"severity_score": 50.0, "exposure_value": 1000.0},
        {"severity_score": 50.0, "exposure_value": 1000.0, "persistence_days": 40},
    ]
    dur = ranking.severity_exposure_persistence(missing_duration)
    check("a first-ever observation is not scored as long-standing",
          dur[1] > dur[0], f"{dur}")

    print("\n--- risk-tier ordering (Ageing BR-28) ---")
    tiers = [
        {"member": "huge but fresh", "tier": "0-03 MONTHS", "exposure_value": 30_000_000.0},
        {"member": "small but oldest", "tier": "24+ MONTHS", "exposure_value": 50_000.0},
        {"member": "mid, 12-24", "tier": "12-24 MONTHS", "exposure_value": 3_000_000.0},
    ]
    tier_scores = ranking.tier_then_value(tiers)
    ordered = [tiers[i]["member"] for i in
               sorted(range(len(tiers)), key=lambda i: tier_scores[i], reverse=True)]
    check("the oldest tier leads regardless of value - no amount of fresh stock "
          "can outrank it",
          ordered == ["small but oldest", "mid, 12-24", "huge but fresh"],
          f"order={ordered}")

    unknown = ranking.tier_then_value([
        {"tier": "24+ MONTHS", "exposure_value": 1.0},
        {"tier": "SOMETHING NEW", "exposure_value": 10_000_000.0}])
    check("an unrecognised tier sorts last, never silently safest",
          unknown[0] > unknown[1], f"{unknown}")


# --------------------------------------------------- 3. aggregation semantics


def test_aggregation() -> None:
    print("\n=== aggregation classes ===")

    check("all five classes exist",
          {c.value for c in aggregation.AggregationClass} == {
              "additive", "semi_additive_last", "additive_within_level",
              "non_additive_ratio", "duration"})
    check("only ADDITIVE claims to sum over time",
          [c for c in aggregation.AggregationClass if c.sums_over_time]
          == [aggregation.AggregationClass.ADDITIVE])
    check("a ratio does not sum over members either",
          not aggregation.AggregationClass.NON_ADDITIVE_RATIO.sums_over_members)

    print("\n--- THE CENTRAL TEST: a semi-additive measure must FAIL additive "
          "verification ---")
    refuted = aggregation.judge(aggregation.AggregationClass.ADDITIVE,
                                LIVE_SNAPSHOTS, latest_value=LIVE_LATEST)
    check("declaring the real stock series ADDITIVE is REFUTED",
          refuted.verdict is aggregation.Verdict.REFUTED, refuted.summary())
    check("the observed overstatement is the measured 4.03x",
          refuted.observed_ratio is not None
          and abs(refuted.observed_ratio - 4.03) < 0.01,
          f"ratio={refuted.observed_ratio}")
    check("it is not treated as safe to sum over time",
          not refuted.safe_to_sum_over_time)
    check("and it blocks the report rather than warning quietly",
          refuted.blocks_report)
    check("the reason states the factor, so the message is actionable",
          "4.03x" in refuted.reason, refuted.reason)
    check("the arithmetic matches the live figures exactly",
          abs(sum(LIVE_SNAPSHOTS) - LIVE_SUM) < 0.01,
          f"sum={sum(LIVE_SNAPSHOTS)} expected={LIVE_SUM}")

    print("\n--- the same series declared correctly ---")
    confirmed = aggregation.judge(aggregation.AggregationClass.SEMI_ADDITIVE_LAST,
                                  LIVE_SNAPSHOTS, latest_value=LIVE_LATEST)
    check("declaring it SEMI_ADDITIVE_LAST is CONFIRMED",
          confirmed.verdict is aggregation.Verdict.CONFIRMED, confirmed.summary())
    check("it still refuses to be summed over time",
          not confirmed.safe_to_sum_over_time)
    check("and it does not block the report", not confirmed.blocks_report)

    print("\n--- a genuinely additive series ---")
    additive = aggregation.judge(aggregation.AggregationClass.ADDITIVE,
                                 [10.0, 20.0, 30.0], latest_value=60.0)
    check("sum equals the axis total -> CONFIRMED",
          additive.verdict is aggregation.Verdict.CONFIRMED, additive.summary())
    check("it IS safe to sum over time", additive.safe_to_sum_over_time)

    mislabelled = aggregation.judge(aggregation.AggregationClass.SEMI_ADDITIVE_LAST,
                                    [10.0, 20.0, 30.0], latest_value=60.0)
    check("an additive series wrongly declared semi-additive is REFUTED too",
          mislabelled.verdict is aggregation.Verdict.REFUTED, mislabelled.summary())

    print("\n--- UNMEASURABLE IS NOT A PASS (both live inventory facts) ---")
    single = aggregation.judge(aggregation.AggregationClass.SEMI_ADDITIVE_LAST,
                               [50831646.81])
    check("one snapshot -> UNVERIFIABLE, not confirmed",
          single.verdict is aggregation.Verdict.UNVERIFIABLE, single.summary())
    check("it is not reported as safe to sum", not single.safe_to_sum_over_time)
    check("it does not block the report either - it is unknown, not wrong",
          not single.blocks_report)
    check("the reason explains why it could not be tested",
          "nothing to sum across" in single.reason, single.reason)

    empty = aggregation.judge(aggregation.AggregationClass.ADDITIVE, [])
    check("no observations -> UNVERIFIABLE",
          empty.verdict is aggregation.Verdict.UNVERIFIABLE, empty.summary())

    ambiguous = aggregation.judge(aggregation.AggregationClass.SEMI_ADDITIVE_LAST,
                                  [10.0, 20.0, 30.0, 100.0], latest_value=100.0)
    check("a series matching neither ~1x nor ~Nx is UNVERIFIABLE, not forced",
          ambiguous.verdict is aggregation.Verdict.UNVERIFIABLE, ambiguous.summary())

    print("\n--- classes that make no additivity claim ---")
    for cls in (aggregation.AggregationClass.NON_ADDITIVE_RATIO,
                aggregation.AggregationClass.DURATION):
        result = aggregation.judge(cls, LIVE_SNAPSHOTS)
        check(f"{cls.value} is CONFIRMED without an additivity test",
              result.verdict is aggregation.Verdict.CONFIRMED, result.summary())
        check(f"{cls.value} is never safe to sum over time",
              not result.safe_to_sum_over_time)


def test_verify_with_executor() -> None:
    print("\n=== verify() gathers observations through an injected executor ===")

    def fake_executor(dax: str):
        return [{"[v]": value} for value in LIVE_SNAPSHOTS]

    result = aggregation.verify(aggregation.AggregationClass.ADDITIVE,
                                "[Stock Value]", fake_executor,
                                time_axis="'SSR TREND'[dates]")
    check("an additive claim over the real series is REFUTED end to end",
          result.verdict is aggregation.Verdict.REFUTED, result.summary())
    check("the result carries the measure and axis it tested",
          result.detail.get("measure") == "[Stock Value]"
          and result.detail.get("time_axis") == "'SSR TREND'[dates]")

    no_axis = aggregation.verify(aggregation.AggregationClass.ADDITIVE,
                                 "[Stock Value]", fake_executor)
    check("with no time axis it says so rather than assuming safe",
          no_axis.verdict is aggregation.Verdict.UNVERIFIABLE, no_axis.summary())

    def exploding(dax: str):
        raise RuntimeError("dataset unavailable")

    failed = aggregation.verify(aggregation.AggregationClass.ADDITIVE,
                                "[Stock Value]", exploding,
                                time_axis="'SSR TREND'[dates]")
    check("a failed query is UNVERIFIABLE, and never takes the run down",
          failed.verdict is aggregation.Verdict.UNVERIFIABLE, failed.summary())


def test_metadata_classification() -> None:
    print("\n=== metadata gives a first guess, arithmetic gives the verdict ===")

    fixture = FIXTURE_DIR / "stock_snapshot.json"
    if not fixture.exists():
        check("stock fixture present", False, str(fixture))
        return
    measures = {m["name"]: m for m in
                json.loads(fixture.read_text(encoding="utf-8"))["measures"]}

    guess = aggregation.classify_from_metadata
    check("a LASTNONBLANK measure is guessed SEMI_ADDITIVE_LAST",
          guess(measures["Stock Units on Hand"])
          is aggregation.AggregationClass.SEMI_ADDITIVE_LAST)
    check("a plain SUM across snapshots is guessed ADDITIVE - which is exactly "
          "why the guess must be verified",
          guess(measures["Stock Units Naive Sum"])
          is aggregation.AggregationClass.ADDITIVE)
    check("the two are told apart here, where semantic_profiler could not",
          guess(measures["Stock Units on Hand"])
          is not guess(measures["Stock Units Naive Sum"]))
    check("a DIVIDE measure is NON_ADDITIVE_RATIO",
          guess(measures["Days Cover"])
          is aggregation.AggregationClass.NON_ADDITIVE_RATIO)
    check("an AVERAGEX measure is NON_ADDITIVE_RATIO",
          guess(measures["Average Daily Units Sold"])
          is aggregation.AggregationClass.NON_ADDITIVE_RATIO)

    # The live models' burn-out days: a span attached to a state, where the
    # BR-11 sentinel of 1000 makes averaging actively misleading.
    check("a days/cover measure is DURATION",
          guess({"name": "EXPECTED_BURNOUT_DAYS", "expression": "SUM(x[BD])"})
          is aggregation.AggregationClass.DURATION)


def main() -> int:
    print("=" * 72)
    print("WP2 kernel: spine, aggregation, ranking")
    print("=" * 72)

    test_protocol()
    test_sales_unchanged()
    test_ranking_registry()
    test_aggregation()
    test_verify_with_executor()
    test_metadata_classification()

    print("\n" + "=" * 72)
    if _failures:
        print(f"KERNEL SPINE FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
