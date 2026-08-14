"""WP4: snapshot semantics, the policy spine, and state-based novelty.

    python scripts/replay_snapshot_foundations.py

Offline - no auth, no LLM, no network.

**The highest-risk work package in the programme.** A stock figure summed across
30 snapshots is 30x too big and *every existing reconciliation check passes*,
because the parts and the whole were summed the same wrong way. Treat every test
here as load-bearing.

The three the brief calls the point of the package
--------------------------------------------------
1. a semi-additive measure summed across snapshots is **detected and refused**
2. an as-of date is told apart from a transaction date
3. a snapshot is labelled "as at <date>", never a span

Plus the two capabilities pulled forward from WP6 (findings §8), because neither
live model has a prior snapshot and so Ageing cannot rank or rotate without them:
change-free ranking, and novelty for a state that persists.

Figures come from the live models where possible: the 4.03x overstatement, the
one-distinct-value stamps, and the 14-value age axis that a naive rule misread.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import spines as inventory_spines  # noqa: E402
from src.kernel import aggregation, ranking, snapshot, state_novelty  # noqa: E402
from src.kernel import spine as kernel_spine  # noqa: E402

# Measured live, 2026-08-13 (findings §4a).
LIVE_SNAPSHOTS = [51677750.95553299, 52479645.71366396,
                  49775351.19328705, 50833557.23300002]
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


# ------------------------------------- 1. THE POINT OF THE WORK PACKAGE


def test_semi_additive_refused() -> None:
    print("\n=== a semi-additive measure summed across snapshots is REFUSED ===")

    refuted = aggregation.judge(aggregation.AggregationClass.ADDITIVE,
                                LIVE_SNAPSHOTS, latest_value=LIVE_LATEST)
    check("the real stock series declared additive is REFUTED",
          refuted.verdict is aggregation.Verdict.REFUTED, refuted.summary())
    check("the refusal is a hard stop, not a warning", refuted.blocks_report)
    check("it is never marked safe to sum over time", not refuted.safe_to_sum_over_time)

    guard = snapshot.guard_semi_additive(refuted)
    check("the guard returns a reason, so a caller must refuse", bool(guard), str(guard))
    check("the reason names the overstatement factor", "4.03x" in (guard or ""), guard)

    confirmed = aggregation.judge(aggregation.AggregationClass.SEMI_ADDITIVE_LAST,
                                  LIVE_SNAPSHOTS, latest_value=LIVE_LATEST)
    check("declared correctly it is CONFIRMED",
          confirmed.verdict is aggregation.Verdict.CONFIRMED, confirmed.summary())
    check("but the guard STILL refuses to let it be summed over time",
          snapshot.guard_semi_additive(confirmed) is not None,
          "semi-additive confirmed is not permission to sum")

    additive = aggregation.judge(aggregation.AggregationClass.ADDITIVE,
                                 [10.0, 20.0, 30.0], latest_value=60.0)
    check("a genuinely additive measure passes the guard",
          snapshot.guard_semi_additive(additive) is None)

    single = aggregation.judge(aggregation.AggregationClass.SEMI_ADDITIVE_LAST,
                               [50831646.81])
    check("one snapshot is UNVERIFIABLE - the live case, and not a pass",
          single.verdict is aggregation.Verdict.UNVERIFIABLE, single.summary())
    check("and the guard still refuses, because nothing was proved",
          snapshot.guard_semi_additive(single) is not None)


def test_snapshot_vs_transaction_date() -> None:
    print("\n=== an as-of stamp is told apart from a transaction date ===")

    # The live shapes, verbatim.
    stamp = snapshot.judge_date_role("REP_SSR_SAG[UPDATED_ON]",
                                     distinct_count=1, row_count=158_446,
                                     latest="2026-08-12T00:00:00")
    check("one distinct value across 158,446 rows -> SNAPSHOT",
          stamp.role is snapshot.DateRole.SNAPSHOT, stamp.summary())
    check("and it is filtered to the latest value only",
          stamp.role.filter_style == "latest value only")

    for column, distinct in (("doc_date1purch", 180), ("DOC_DATE2", 165),
                             ("DOC_DATE3", 1443)):
        verdict = snapshot.judge_date_role(column, distinct_count=distinct,
                                           row_count=140_113)
        check(f"{column} ({distinct} distinct) -> EVENT, filtered as a range",
              verdict.role is snapshot.DateRole.EVENT, verdict.summary())
        check(f"...and {column} is usable as a time axis",
              verdict.usable_as_time_axis)

    print("\n--- the trap this got wrong once, against real data ---")
    # 14 purchase periods over 158,446 rows is a ratio of 0.00009. A
    # "few distinct values means snapshot" rule classified the ageing report's
    # own AGE AXIS as an as-of stamp, and would have filtered the report to its
    # newest batch.
    age_axis = snapshot.judge_date_role("REP_SSR_SAG[sortdate]",
                                        distinct_count=14, row_count=158_446)
    check("the 14-value age axis is NOT classified as a snapshot",
          age_axis.role is not snapshot.DateRole.SNAPSHOT, age_axis.summary())
    check("it is reported as ambiguous rather than guessed",
          age_axis.role is snapshot.DateRole.UNKNOWN)
    check("and it is not offered as a time axis either",
          not age_axis.usable_as_time_axis)
    check("the reason says what evidence would settle it",
          "repeats the same members" in age_axis.reason, age_axis.reason)

    print("\n--- a load/posting date is not business activity ---")
    batch = snapshot.judge_date_role("UPDATED_DATE", distinct_count=365,
                                     row_count=500_000, bucket_shares=[0.53, 0.01])
    check("one bucket holding 53% of the measure -> BATCH_LOAD",
          batch.role is snapshot.DateRole.BATCH_LOAD, batch.summary())
    check("and it is not usable as a time axis", not batch.usable_as_time_axis)

    print("\n--- picking, when several columns qualify ---")
    picked = snapshot.pick_snapshot_column([stamp, age_axis])
    check("the as-of stamp is picked over the ambiguous axis",
          picked is not None and picked.column == "REP_SSR_SAG[UPDATED_ON]")
    tie = snapshot.pick_snapshot_column([
        snapshot.judge_date_role("A", distinct_count=1, row_count=10),
        snapshot.judge_date_role("B", distinct_count=1, row_count=10)])
    check("a tie returns nothing rather than choosing arbitrarily", tie is None)
    check("no candidates returns nothing", snapshot.pick_snapshot_column([]) is None)


def test_as_at_labelling() -> None:
    print("\n=== a snapshot is labelled 'as at', never a span ===")

    label = snapshot.period_label(snapshot.DateRole.SNAPSHOT, "2026-08-12T00:00:00")
    check("a snapshot reads 'as at <date>'", label == "as at 2026-08-12", label)
    check("the time component is dropped - the data has no such precision",
          "T00:00:00" not in label)
    check("a span label is IGNORED for a snapshot, not appended",
          snapshot.period_label(snapshot.DateRole.SNAPSHOT, "2026-08-12",
                                "Jan-Aug 2026") == "as at 2026-08-12")
    check("an event period keeps its span label",
          snapshot.period_label(snapshot.DateRole.EVENT, None, "Jan-Aug 2026")
          == "Jan-Aug 2026")
    check("a snapshot with no date still says 'as at'",
          "as at" in snapshot.period_label(snapshot.DateRole.SNAPSHOT, None))


def test_latest_snapshot_dax() -> None:
    print("\n=== the DAX pins to one snapshot, safely ===")

    var = snapshot.latest_snapshot_var("'F'[UPDATED_ON]")
    filt = snapshot.latest_snapshot_filter("'F'[UPDATED_ON]")
    check("a VAR resolves the newest snapshot", "MAX('F'[UPDATED_ON])" in var, var)
    check("REMOVEFILTERS targets the DATE COLUMN, never the table - a bare "
          "table-wide REMOVEFILTERS strips the population too (NN 10)",
          "REMOVEFILTERS('F'[UPDATED_ON])" in var and "REMOVEFILTERS('F')" not in var,
          var)
    check("the filter uses TREATAS, not a bare equality (NN 6)",
          filt.startswith("TREATAS(") and "KEEPFILTERS" not in filt, filt)
    check("the filter references the VAR rather than re-deriving the max",
          "__latest_snapshot" in filt, filt)


# ---------------------------------------------- 2. the policy spine


def _row(cover=None, lower=None, upper=None, exposure=None, days=None):
    row = {}
    if cover is not None:
        row["cover"] = cover
    if lower is not None:
        row["baseline_lower"] = lower
    if upper is not None:
        row["baseline_upper"] = upper
    if exposure is not None:
        row["exposure"] = exposure
    if days is not None:
        row["days_in_state"] = days
    return row


def test_policy_spine() -> None:
    print("\n=== SnapshotVsPolicySpine ===")

    spine = inventory_spines.SnapshotVsPolicySpine(
        cover_measure="EXPECTED_BURNOUT_DAYS",
        lower_measure="Reorder Trigger Days",
        upper_measure="EXCESS_THRESHOLD_DAYS",
        exposure_measure="SKU_STOCK_VALUE",
        snapshot_column="'F'[UPDATED_ON]")

    check("it satisfies the spine protocol",
          isinstance(spine, kernel_spine.MeasurementSpine))
    check("the baseline is named in English, because it is printed",
          spine.baseline_label == "the agreed stock policy")
    check("its delta is a DISTANCE, not an absolute movement",
          spine.delta_kind() == kernel_spine.DISTANCE)
    check("measured in DAYS while exposure is in VALUE - collapsing them "
          "prints 'SAR 9'",
          (spine.delta_unit(), spine.exposure_unit()) == ("days", "value"))

    print("\n--- classification ---")
    check("inside the band is comparable",
          spine.classify(_row(cover=30, lower=9, upper=60)) == kernel_spine.COMPARABLE)
    check("NO POLICY is baseline_missing - an item nobody set a rule for is "
          "not an exception",
          spine.classify(_row(cover=30)) == kernel_spine.BASELINE_MISSING)
    check("and baseline_missing is NOT comparable, so it leaves the queue",
          spine.classify(_row(cover=30)) != kernel_spine.COMPARABLE)
    check("nothing at all is inactive", spine.classify({}) == kernel_spine.INACTIVE)

    print("\n--- the BR-11 sentinel (16.3% of live rows) ---")
    sentinel_row = _row(cover=1000, lower=9, upper=60)
    check("cover of 1000 is read as 'no velocity', not 1000 days",
          spine.cover_of(sentinel_row) is None)
    check("so it does not become the most over-stocked line in the business",
          spine.distance(sentinel_row) is None)
    check("it classifies as current_only - a policy exists but cover cannot be "
          "measured",
          spine.classify(sentinel_row) == kernel_spine.CURRENT_ONLY)
    check("and its state says so", spine.state(sentinel_row) == "no_velocity")
    check("a real 63,044-day cover is NOT swallowed by the sentinel rule",
          spine.cover_of(_row(cover=63044, upper=60)) == 63044)

    print("\n--- distance outside the band ---")
    check("above the upper limit is positive days",
          spine.distance(_row(cover=90, lower=9, upper=60)) == 30)
    check("below the lower limit is negative days",
          spine.distance(_row(cover=4, lower=9, upper=60)) == -5)
    check("inside the band is zero, not a signed distance from the middle",
          spine.distance(_row(cover=30, lower=9, upper=60)) == 0.0)
    check("with no band there is no distance to state",
          spine.distance(_row(cover=30)) is None)

    print("\n--- states ---")
    for row, expected in ((_row(cover=90, lower=9, upper=60), "excess"),
                          (_row(cover=4, lower=9, upper=60), "below_reorder"),
                          (_row(cover=30, lower=9, upper=60), "within_policy"),
                          (_row(cover=30), "no_policy")):
        check(f"{expected} is named", spine.state(row) == expected, spine.state(row))

    print("\n--- percentage is against the LIMIT, not last year ---")
    check("40% past the excess threshold", spine.pct(84, 60) == 40.0)
    check("undefined against a zero limit (the live 'no excess' sections)",
          spine.pct(84, 0) is None)

    print("\n--- the delta expression, and pinning to one snapshot ---")
    expr = spine.delta_expr()
    check("a two-sided band produces a two-sided expression",
          "IF(" in expr and "EXCESS_THRESHOLD_DAYS" in expr, expr)
    upper_only = inventory_spines.SnapshotVsPolicySpine(
        cover_measure="BD", upper_measure="LIMIT").delta_expr()
    check("an upper-only band is one-sided, not invented into two",
          upper_only.count("IF(") == 1, upper_only)
    check("no cover measure means no expression rather than broken DAX",
          inventory_spines.SnapshotVsPolicySpine().delta_expr() == "")

    population = spine.population_filter({})
    check("every query is pinned to the latest snapshot (NN 11)",
          population is not None and population.startswith("TREATAS("), population)

    print("\n--- ranking feeds the change-free blend ---")
    components = spine.rank_components(
        _row(cover=90, lower=9, upper=60, exposure=250_000.0, days=12), {})
    check("severity is the distance in days", components["severity_score"] == 30)
    check("exposure is the value at risk", components["exposure_value"] == 250_000.0)
    check("persistence is how long it has held", components["persistence_days"] == 12)
    check("and it names the change-free blend, not the year-on-year one",
          components["blend"] == "severity_exposure_persistence")

    print("\n--- caveats are stated, not assumed understood ---")
    caveats = spine.caveats()
    check("it says the figure is a position, not a period total",
          any("position as at" in c for c in caveats), caveats)
    check("it explains the sentinel in plain words",
          any("no rate of sale" in c for c in caveats), caveats)


def test_change_free_ranking() -> None:
    print("\n=== ranking with no before-and-after ===")

    spine = inventory_spines.SnapshotVsPolicySpine(
        cover_measure="BD", upper_measure="LIMIT", exposure_measure="VALUE")
    members = [
        {"member": "trivial but extreme",
         **spine.rank_components(_row(cover=5000, upper=60, exposure=400.0), {})},
        {"member": "large and moderate",
         **spine.rank_components(_row(cover=90, upper=60, exposure=3_000_000.0), {})},
    ]
    scores = ranking.get("severity_exposure_persistence")(members)
    # This is the CF-FRESH BAKES +2166.79% failure in a new costume: an extreme
    # ratio on a near-zero base leading the report.
    check("a huge overage on SAR 400 does not outrank a real one on SAR 3M",
          scores[1] > scores[0], f"trivial={scores[0]:.4f} large={scores[1]:.4f}")


# ------------------------------------------- 3. state-based novelty


def test_state_novelty() -> None:
    print("\n=== novelty for a state that persists ===")

    key_a = state_novelty.state_key(
        {"member": "SKU-1", "role": "sku", "state": "below_reorder"})
    key_same = state_novelty.state_key(
        {"member": "SKU-1", "role": "sku", "state": "below_reorder",
         "days_in_state": 9, "first_seen": "2026-08-01"})
    check("duration is NOT part of the key - if it were, every day would mint a "
          "new identity and nothing would ever be suppressed",
          key_a == key_same)
    key_b = state_novelty.state_key(
        {"member": "SKU-1", "role": "sku", "state": "excess"})
    check("but the STATE is, so a transition is a new story", key_a != key_b)

    print("\n--- the behaviour the brief names ---")
    first = state_novelty.judge(None, {"state": "below_reorder"},
                                observed_at="2026-08-01")
    check("a first sighting is reported", first.report and first.kind == "first_seen")
    record = state_novelty.advance(None, {"state": "below_reorder"}, first,
                                   observed_at="2026-08-01")

    # Day 2..6: unchanged. This is the "do not re-announce every morning" rule.
    quiet = state_novelty.judge(record, {"state": "below_reorder"},
                                observed_at="2026-08-04")
    check("'below reorder point, day 3' is NOT re-announced",
          not quiet.report and quiet.kind == "unchanged", quiet.summary())
    check("but the duration is still counted", quiet.days_in_state == 3)

    print("\n--- it speaks up when it worsens ---")
    worse = state_novelty.judge(
        {**record, "distance": -5.0},
        {"state": "below_reorder", "distance": -12.0}, observed_at="2026-08-04")
    check("materially deeper below the limit IS reported",
          worse.report and worse.kind == "escalated", worse.summary())
    drift = state_novelty.judge(
        {**record, "distance": -5.0},
        {"state": "below_reorder", "distance": -5.5}, observed_at="2026-08-04")
    check("ordinary drift is not - a threshold, or it reports daily again",
          not drift.report, drift.summary())

    exposure = state_novelty.judge(
        {**record, "exposure": 100_000.0},
        {"state": "below_reorder", "exposure": 400_000.0}, observed_at="2026-08-04")
    check("more value exposed also counts as worse",
          exposure.report and exposure.kind == "escalated", exposure.summary())

    print("\n--- and when it clears ---")
    cleared = state_novelty.judge(record, {"state": "within_policy"},
                                  observed_at="2026-08-05")
    check("a clearance IS reported - a report that only ever announces problems "
          "never tells you one is over",
          cleared.report and cleared.kind == "cleared", cleared.summary())
    onset = state_novelty.judge(
        {"state": "within_policy", "first_seen": "2026-08-01"},
        {"state": "excess"}, observed_at="2026-08-05")
    check("an onset is reported as an onset", onset.report and onset.kind == "onset")

    print("\n--- time itself becomes the finding ---")
    milestone = state_novelty.judge(record, {"state": "below_reorder"},
                                    observed_at="2026-08-08")
    check("day 7 crosses a milestone and is reported",
          milestone.report and milestone.kind == "milestone", milestone.summary())
    after = state_novelty.advance(record, {"state": "below_reorder"}, milestone,
                                  observed_at="2026-08-08")
    again = state_novelty.judge(after, {"state": "below_reorder"},
                                observed_at="2026-08-09")
    check("the same milestone does not fire twice",
          not again.report, again.summary())
    day14 = state_novelty.judge(after, {"state": "below_reorder"},
                                observed_at="2026-08-15")
    check("but the next milestone does", day14.report and day14.kind == "milestone")

    print("\n--- duration survives a gap in runs ---")
    gapped = state_novelty.judge(record, {"state": "below_reorder"},
                                 observed_at="2026-08-20")
    check("a weekend without a run does not reset the clock",
          gapped.days_in_state == 19, f"days={gapped.days_in_state}")
    check("counted from the observation dates, not the number of runs",
          state_novelty.days_between("2026-08-01", "2026-08-20") == 19)

    print("\n--- the record it persists ---")
    check("first_seen holds across an unchanged run",
          state_novelty.advance(record, {"state": "below_reorder"}, quiet,
                                observed_at="2026-08-04")["first_seen"]
          == "2026-08-01")
    reset = state_novelty.advance(record, {"state": "within_policy"}, cleared,
                                  observed_at="2026-08-05")
    check("but resets when the state genuinely changed",
          reset["first_seen"] == "2026-08-05")
    check("times_reported only advances when something was reported",
          state_novelty.advance(record, {"state": "below_reorder"}, quiet,
                                observed_at="2026-08-04")["times_reported"]
          == record["times_reported"])


def test_memory_schema_v5() -> None:
    print("\n=== summary memory schema v5 ===")

    from src.tools import summary_memory

    check("the schema is at v5", summary_memory.SCHEMA_VERSION == 5)
    empty = summary_memory._empty_store()
    check("a new store carries state_records", "state_records" in empty)
    check("...and it starts empty", empty["state_records"] == {})

    # Non-destructive: an older store gains the field without losing anything.
    old = {"schema_version": 3, "records": {"story:x": {"seen": 1}},
           "focus_records": {"focus:y": {"seen": 2}}, "journal": {}}
    migrated = summary_memory._migrate(dict(old), "ds", "rep")
    check("migrating an older store adds state_records",
          migrated["state_records"] == {})
    check("...without touching existing records",
          migrated["records"] == old["records"])
    check("...or the focus history", migrated["focus_records"] == old["focus_records"])
    check("...and stamps it to v5", migrated["schema_version"] == 5)


def main() -> int:
    print("=" * 72)
    print("WP4 snapshot foundations")
    print("=" * 72)

    test_semi_additive_refused()
    test_snapshot_vs_transaction_date()
    test_as_at_labelling()
    test_latest_snapshot_dax()
    test_policy_spine()
    test_change_free_ranking()
    test_state_novelty()
    test_memory_schema_v5()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SNAPSHOT FOUNDATIONS FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
