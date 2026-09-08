"""The plan cache: what it reuses, what invalidates it, and what it never skips.

    python scripts/replay_plan_cache.py

Offline - no auth, no LLM, no network.

Three of the pipeline's LLM nodes (`report_understanding`, `dax_planner`,
`dax_generator`) read the semantic model's *structure*, not its rows, so on an
unchanged schema they buy the same answer every morning at full price.
`src/tools/plan_cache.py` stores that work and reuses it.

The saving is the easy part. What this file exists to prove is the three ways
the idea can go silently wrong:

1. **Keying on the wrong thing, in either direction.** Put today's *values* in
   the key and the cache never hits, so it is dead code that still adds a
   failure mode. Leave the model's *shape* out of the key and a renamed column
   makes yesterday's DAX wrong while the cache happily serves it - a report
   that looks right and is wrong, which is the failure this repo cares about
   most.
2. **Skipping the safety net along with the LLM call.** The cache is allowed to
   short-circuit the three planning nodes. It is *not* allowed to short-circuit
   `dax_validator` or `scope_validator`. A stale cached plan must be rejected
   by exactly the machinery that would reject a freshly generated bad plan.
3. **Never letting go.** A plan that has quietly drifted out of step with the
   model must cost at most one degraded run, not every run thereafter.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import dax_generator, dax_planner, dax_validator  # noqa: E402
from src.agents import report_understanding  # noqa: E402
from src.tools import plan_cache  # noqa: E402

OUT_DIR = "outputs_replay/plan_cache"
CACHE_DIR = PROJECT_ROOT / OUT_DIR / "cache"
PROBE_PROMPT = PROJECT_ROOT / "prompts" / "_replay_plan_cache_probe.md"

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


# --------------------------------------------------------------- the fixture
#
# A minimal but real-shaped model: two tables, three columns, two measures.
# `rows` and `sample_rows` carry *values*, which is exactly what must not
# reach the key.

def metadata(revenue_column: str = "REV_CURRENT") -> dict:
    return {
        "tables": [{"name": "Sales"}, {"name": "Store"}],
        "columns": [
            {"table": "Sales", "column": "DOC_MONTH", "data_type": "Int64"},
            {"table": "Sales", "column": revenue_column, "data_type": "Double"},
            {"table": "Store", "column": "STORE_CODE", "data_type": "String"},
        ],
        "measures": [
            {"name": "Total Revenue", "table": "Sales"},
            {"name": "Total Revenue LY", "table": "Sales"},
        ],
        # Values. These change every single day and must never move the key.
        "rows": [{"DOC_MONTH": 1, "Total Revenue": 125800000.0}],
        "sample_rows": [{"STORE_CODE": "ST1"}],
    }


def base_state(**over) -> dict:
    state = {
        "plan_cache_enabled": True,
        "plan_cache_folder": str(CACHE_DIR),
        "plan_cache_max_age_days": 7,
        "output_folder": OUT_DIR,
        "dataset_id": "f34c5654-bf75-4fb3-b289-2676d8e38241",
        "report_id": "sales_yoy",
        "model_metadata": metadata(),
        "business_rules": "Comparable stores only.",
        # Read by the planning nodes before they reach the cache. Not part of
        # the key - the key covers the model's shape, which is what produced it.
        "report_understanding": {"domain": "retail"},
    }
    state.update(over)
    return state


def fresh_cache() -> None:
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _explode(*_a, **_k):
    raise AssertionError("an LLM was built on a cache hit")


# ------------------------------------------------------------ 1. hit and miss


def test_round_trip_without_an_llm() -> None:
    print("\n=== a stored plan comes back, and no LLM is called ===")
    fresh_cache()

    state = base_state()
    check("nothing stored yet reads as a miss", plan_cache.load(state) is None)

    plan = {"queries": [{"name": "totals", "intent": "grand totals"}]}
    plan_cache.save(state, report_understanding={"domain": "retail"}, dax_plan=plan)

    hit = plan_cache.load(state)
    check("a saved plan is returned", hit is not None and hit.get("dax_plan") == plan)
    check("the understanding slot round-trips",
          hit is not None and hit.get("report_understanding") == {"domain": "retail"})
    check("the entry carries its key and age for the log",
          hit is not None and "key" in hit and "age_days" in hit)

    # The nodes must take the cached path *without* building a model. get_llm
    # raises here if it is ever reached, so a call is a hard failure rather
    # than a slow test.
    report_understanding.get_llm = _explode  # type: ignore[attr-defined]
    dax_planner.get_llm = _explode  # type: ignore[attr-defined]
    dax_generator.get_llm = _explode  # type: ignore[attr-defined]

    out = report_understanding.run(dict(state))
    check("report_understanding served from cache, no LLM built",
          out.get("report_understanding") == {"domain": "retail"}
          and out.get("plan_cache_hit") is True)

    out = dax_planner.run(dict(state))
    check("dax_planner served from cache, no LLM built",
          out.get("dax_plan") == plan and out.get("plan_cache_hit") is True)


def test_a_renamed_column_misses() -> None:
    print("\n=== the model's SHAPE is in the key ===")
    fresh_cache()

    state = base_state()
    plan_cache.save(state, dax_plan={"queries": [{"name": "totals"}]})
    check("the plan is stored", plan_cache.load(state) is not None)

    # This is the invalidation that matters: yesterday's DAX names a column
    # that no longer exists, so reusing it would produce a query that fails -
    # or worse, one that silently reads something else.
    renamed = base_state(model_metadata=metadata(revenue_column="NET_REVENUE"))
    check("a renamed column MISSES", plan_cache.load(renamed) is None)

    dropped = base_state(model_metadata=dict(
        metadata(), measures=[{"name": "Total Revenue", "table": "Sales"}]))
    check("a removed measure MISSES", plan_cache.load(dropped) is None)

    extra = base_state(model_metadata=dict(
        metadata(),
        tables=[{"name": "Sales"}, {"name": "Store"}, {"name": "Calendar"}]))
    check("an added table MISSES", plan_cache.load(extra) is None)

    retyped = base_state(model_metadata=dict(metadata(), columns=[
        {"table": "Sales", "column": "DOC_MONTH", "data_type": "String"},
        {"table": "Sales", "column": "REV_CURRENT", "data_type": "Double"},
        {"table": "Store", "column": "STORE_CODE", "data_type": "String"},
    ]))
    check("a changed column TYPE misses", plan_cache.load(retyped) is None)


def test_changed_values_still_hit() -> None:
    print("\n=== today's VALUES are not in the key ===")
    fresh_cache()

    state = base_state()
    plan_cache.save(state, dax_plan={"queries": [{"name": "totals"}]})

    # Data changing daily is the entire point of the product. If it moved the
    # key, the cache would never hit once and this whole module would be a
    # pure liability.
    moved = base_state(model_metadata=dict(
        metadata(),
        rows=[{"DOC_MONTH": 8, "Total Revenue": 131400000.0}],
        sample_rows=[{"STORE_CODE": "ST9"}]))
    check("changed sample values still HIT", plan_cache.load(moved) is not None)

    # Scan results, novelty state and the day's candidates are not part of the
    # payload at all; assert that rather than assume it.
    noisy = base_state(insight_clean_data={"huge": list(range(500))},
                       raw_pbi_results={"totals": {"status": "success"}},
                       insight_stat_candidates=[{"score": 9.1}])
    check("unrelated run state does not move the key",
          plan_cache.cache_key(noisy) == plan_cache.cache_key(state))


def test_rules_prompts_and_version_miss() -> None:
    print("\n=== rulebook, prompts and the version constant all invalidate ===")
    fresh_cache()

    state = base_state()
    plan_cache.save(state, dax_plan={"queries": [{"name": "totals"}]})

    edited = base_state(business_rules="Comparable stores only. Exclude ST9.")
    check("an edited business rule MISSES", plan_cache.load(edited) is None)

    # Editing a prompt is *meant* to change the output, so it must invalidate.
    # Point the digest at a real probe file rather than stubbing the function,
    # so the file-reading path itself is under test.
    original_files = plan_cache._PROMPT_FILES
    try:
        PROBE_PROMPT.write_text("first version\n", encoding="utf-8")
        plan_cache._PROMPT_FILES = (PROBE_PROMPT.name,)
        fresh_cache()
        probe = base_state()
        plan_cache.save(probe, dax_plan={"queries": [{"name": "totals"}]})
        check("stored against the first prompt", plan_cache.load(probe) is not None)

        PROBE_PROMPT.write_text("second version\n", encoding="utf-8")
        check("an edited PROMPT FILE misses", plan_cache.load(probe) is None)
    finally:
        plan_cache._PROMPT_FILES = original_files
        PROBE_PROMPT.unlink(missing_ok=True)

    fresh_cache()
    state = base_state()
    plan_cache.save(state, dax_plan={"queries": [{"name": "totals"}]})
    original_version = plan_cache.PLAN_CACHE_VERSION
    try:
        plan_cache.PLAN_CACHE_VERSION = str(int(original_version) + 1)
        check("bumping PLAN_CACHE_VERSION misses everything",
              plan_cache.load(state) is None)
    finally:
        plan_cache.PLAN_CACHE_VERSION = original_version
    check("restoring the version hits again", plan_cache.load(state) is not None)


def test_two_reports_over_one_model_do_not_share() -> None:
    print("\n=== identity is per dataset AND per report ===")
    fresh_cache()

    yoy = base_state(report_id="sales_yoy")
    plan_cache.save(yoy, dax_plan={"queries": [{"name": "yoy"}]})

    other = base_state(report_id="target_tracker")
    check("a second report over the same model does not read the first's plan",
          plan_cache.load(other) is None)

    other_model = base_state(dataset_id="8d111712-9ea8-4a65-9bb9-58f00e49d379")
    check("a different dataset does not read it either",
          plan_cache.load(other_model) is None)


def test_disabled_is_inert() -> None:
    print("\n=== off reproduces the previous behaviour exactly ===")
    fresh_cache()

    state = base_state(plan_cache_enabled=False)
    plan_cache.save(state, dax_plan={"queries": [{"name": "totals"}]})
    check("save writes nothing while disabled",
          not any(CACHE_DIR.glob("*.json")))
    check("load returns None while disabled", plan_cache.load(state) is None)
    check("record_execution is inert while disabled",
          plan_cache.record_execution(state, 0, 10) is None)

    # An unreadable cache must degrade to "do the full work", never raise.
    fresh_cache()
    live = base_state()
    plan_cache.save(live, dax_plan={"queries": [{"name": "totals"}]})
    corrupt = CACHE_DIR / (plan_cache.cache_key(live) + ".json")
    corrupt.write_text("{ not json", encoding="utf-8")
    check("a corrupt entry reads as a miss rather than raising",
          plan_cache.load(live) is None)


# ------------------------------------------------- 2. the safety net is intact


def test_a_cached_plan_is_still_validated() -> None:
    print("\n=== a cached plan still goes through the validators ===")
    fresh_cache()

    # A plan that WAS valid when it was stored, against a model that has since
    # renamed the column it reads. This is precisely the stale-plan case.
    stale = [{"name": "totals",
              "dax": "EVALUATE ROW(\"Revenue\", SUM('Sales'[REV_CURRENT]))"}]

    # The key already misses on a renamed column, so force the dangerous case
    # directly: hand the node the stale DAX anyway and prove the validator
    # still rejects it. The cache may skip the LLM, never this.
    moved_on = base_state(model_metadata=metadata(revenue_column="NET_REVENUE"))
    moved_on["dax_plan"] = {"queries": [{"name": "totals"}]}
    moved_on["generated_dax_queries"] = stale
    out = dax_validator.run(moved_on)
    check("the stale cached query is held for repair, not executed",
          out["validated_dax_queries"] == [] and len(out["skipped_dax_queries"]) == 1)
    check("and the reason names the column that moved",
          out["skipped_dax_queries"]
          and "REV_CURRENT" in out["skipped_dax_queries"][0]["reason"],
          out["skipped_dax_queries"])

    # And the generator's cache-hit path emits into exactly the key the
    # validator reads, so there is no route around it.
    fresh_cache()
    good = base_state()
    good["dax_plan"] = {"queries": [{"name": "totals"}]}
    plan_cache.save(good, generated_dax=stale)

    dax_generator.get_llm = _explode  # type: ignore[attr-defined]
    served = dax_generator.run(dict(good))
    check("the generator's cache hit writes generated_dax_queries",
          served.get("generated_dax_queries") == stale
          and served.get("plan_cache_hit") is True)

    downstream = dict(good)
    downstream["generated_dax_queries"] = served["generated_dax_queries"]
    out = dax_validator.run(downstream)
    check("against the CURRENT model that same cached DAX passes validation",
          len(out["validated_dax_queries"]) == 1 and out["skipped_dax_queries"] == [])

    # A cached set that no longer covers today's plan is not served wholesale:
    # a plan of two queries must not be answered with one.
    mismatched = base_state()
    mismatched["dax_plan"] = {"queries": [
        {"name": "totals", "intent": "grand totals"},
        {"name": "by_store", "intent": "revenue by store"}]}
    calls: list[int] = []

    def counting(*_a, **_k):
        calls.append(1)
        raise RuntimeError("stop once the LLM path is proven taken")

    dax_generator.get_llm = counting  # type: ignore[attr-defined]
    try:
        dax_generator.run(dict(mismatched))
    except RuntimeError:
        pass
    finally:
        dax_generator.get_llm = _explode  # type: ignore[attr-defined]
    check("a cached set that does not cover today's plan is regenerated",
          bool(calls), "the generator served a partial plan instead of regenerating")


# ------------------------------------------------------ 3. it lets go in time


def test_a_broken_plan_is_dropped() -> None:
    print("\n=== a plan that stops working is dropped ===")
    fresh_cache()

    state = base_state()
    state["plan_cache_hit"] = True
    plan_cache.save(state, generated_dax=[{"name": "totals", "dax": "EVALUATE ROW(1,1)"}])
    path = CACHE_DIR / (plan_cache.cache_key(state) + ".json")

    check("a fully successful run keeps the plan",
          plan_cache.record_execution(state, 10, 10) is None and path.exists())
    check("a run above the floor keeps it",
          plan_cache.record_execution(state, 7, 10) is None and path.exists())

    reason = plan_cache.record_execution(state, 5, 10)
    check("below the success floor the plan is dropped", reason is not None)
    check("the file is actually gone", not path.exists())
    check("and the reason says the next run will re-plan",
          reason is not None and "re-plan" in reason, reason)

    # Nothing was reused this run, so nothing should be blamed on the cache.
    fresh_cache()
    no_hit = base_state()
    plan_cache.save(no_hit, generated_dax=[{"name": "totals"}])
    check("a failing run that did NOT use the cache drops nothing",
          plan_cache.record_execution(no_hit, 0, 10) is None
          and plan_cache.load(no_hit) is not None)

    check("zero attempted queries is not read as a failure",
          plan_cache.record_execution(dict(no_hit, plan_cache_hit=True), 0, 0) is None)


def test_the_age_limit_expires_it_regardless() -> None:
    print("\n=== the age limit is a backstop the hash cannot provide ===")
    fresh_cache()

    state = base_state()
    plan_cache.save(state, dax_plan={"queries": [{"name": "totals"}]})
    path = CACHE_DIR / (plan_cache.cache_key(state) + ".json")

    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["saved_at"] = time.time() - (8 * 86400)
    path.write_text(json.dumps(entry), encoding="utf-8")

    check("an 8-day-old plan is expired at a 7-day limit",
          plan_cache.load(state) is None)
    check("the same plan is served under a 30-day limit",
          plan_cache.load(base_state(plan_cache_max_age_days=30)) is not None)
    check("zero means never expire",
          plan_cache.load(base_state(plan_cache_max_age_days=0)) is not None)

    # An entry holding no slots is not a hit; otherwise a half-written file
    # would suppress the planning nodes and produce an empty report.
    fresh_cache()
    empty = base_state()
    (CACHE_DIR / (plan_cache.cache_key(empty) + ".json")).write_text(
        json.dumps({"saved_at": time.time()}), encoding="utf-8")
    check("an entry with no stored slots is a miss", plan_cache.load(empty) is None)


def main() -> int:
    print("=" * 72)
    print("Plan cache: reuse, invalidation, and the safety net it may not skip")
    print("=" * 72)

    test_round_trip_without_an_llm()
    test_a_renamed_column_misses()
    test_changed_values_still_hit()
    test_rules_prompts_and_version_miss()
    test_two_reports_over_one_model_do_not_share()
    test_disabled_is_inert()
    test_a_cached_plan_is_still_validated()
    test_a_broken_plan_is_dropped()
    test_the_age_limit_expires_it_regardless()

    print("\n" + "=" * 72)
    if _failures:
        print(f"PLAN CACHE FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
