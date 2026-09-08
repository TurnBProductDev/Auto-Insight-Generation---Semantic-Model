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
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import dax_generator, dax_planner, dax_validator  # noqa: E402
from src.agents import report_understanding  # noqa: E402
from src.tools import azure_blob, plan_cache  # noqa: E402

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
    # Empty the directory rather than remove it: on Windows a synced folder can
    # hold a handle on the directory itself, and rmtree then fails on a test
    # that has nothing to do with the code under test.
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for stale in CACHE_DIR.iterdir():
        if stale.is_file():
            stale.unlink()
        else:
            shutil.rmtree(stale, ignore_errors=True)


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


# ------------------------------------ 4. it has to survive a wiped machine


class _Downloader:
    def __init__(self, data: bytes):
        self._data = data
        self.properties = SimpleNamespace(etag='"etag"')

    def readall(self):
        return self._data


class _Blob:
    def __init__(self, service, container, name):
        self.service, self.container, self.name = service, container, name

    def download_blob(self):
        try:
            return _Downloader(self.service.data[self.container][self.name])
        except KeyError as exc:
            raise ResourceNotFoundError("missing") from exc

    def upload_blob(self, data, overwrite=False, **_kw):
        store = self.service.data.setdefault(self.container, {})
        if self.name in store and not overwrite:
            raise ResourceExistsError("exists")
        store[self.name] = bytes(data)


class _Container:
    def __init__(self, service, container):
        self.service, self.container = service, container

    def list_blobs(self, name_starts_with=""):
        for name in sorted(self.service.data.get(self.container, {})):
            if name.startswith(name_starts_with):
                yield SimpleNamespace(name=name)

    def get_blob_client(self, name):
        return _Blob(self.service, self.container, name)

    def delete_blob(self, name):
        self.service.data.get(self.container, {}).pop(name, None)


class _Service:
    def __init__(self):
        self.data: dict = {}

    def get_blob_client(self, container, blob):
        return _Blob(self, container, blob)

    def get_container_client(self, container):
        return _Container(self, container)


def cloud_state(machine: Path, **over) -> dict:
    """A run whose plan cache lives on an ephemeral machine, as in a job."""
    state = base_state(plan_cache_folder=str(machine / ".runtime" / "plan_cache"))
    state["config"] = {"azure_blob_account": "turnbtestblobstorage",
                       "azure_blob_upload": True}
    state.update(over)
    return state


def test_the_switch_is_off_until_the_cache_is_on() -> None:
    print("\n=== the cloud lane cannot change any existing config ===")

    with tempfile.TemporaryDirectory() as tmp:
        machine = Path(tmp)

        off = cloud_state(machine, plan_cache_enabled=False)
        check("the cache being off means the cloud lane is off too",
              not azure_blob.cloud_plan_cache_enabled(off))
        check("and hydration reports itself skipped rather than acting",
              azure_blob.hydrate_plan_cache(off)["status"] == "skipped")

        # No committed config sets plan_cache_enabled, so this is every config
        # that exists today.
        legacy = base_state(plan_cache_enabled=False)
        legacy["config"] = {"azure_blob_upload": True, "azure_blob_account": "acct"}
        check("a config that predates this work is untouched",
              not azure_blob.cloud_plan_cache_enabled(legacy))

        on = cloud_state(machine)
        check("with the cache on, 'auto' follows the report's own storage",
              azure_blob.cloud_plan_cache_enabled(on))

        local = cloud_state(machine)
        local["config"] = {**local["config"], "plan_cache_storage": "local"}
        check("'local' overrides auto in the off direction",
              not azure_blob.cloud_plan_cache_enabled(local))

        forced = cloud_state(machine)
        forced["config"] = {"azure_blob_account": "acct",
                            "plan_cache_storage": "azure_blob"}
        check("'azure_blob' overrides auto in the on direction, with no upload set",
              azure_blob.cloud_plan_cache_enabled(forced))

        no_account = cloud_state(machine)
        no_account["config"] = {"azure_blob_upload": True}
        check("a missing storage account is reported, not guessed",
              azure_blob.hydrate_plan_cache(no_account)["reason"]
              == "azure_blob_account_missing")


def test_the_plan_survives_a_wiped_machine() -> None:
    print("\n=== the whole point: a fresh machine still hits the cache ===")

    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
            azure_blob, "_service_client", return_value=(service, "fake")):

        # --- Day 1, on one machine ---
        day1 = Path(tmp) / "machine_1"
        state1 = cloud_state(day1)

        first = azure_blob.hydrate_plan_cache(state1)
        check("the first run finds nothing stored, and says so rather than failing",
              first["status"] == "ok" and first["pulled"] == [], first)
        check("so the first run genuinely re-plans", plan_cache.load(state1) is None)

        plan_cache.save(state1, dax_plan={"queries": [{"name": "totals"}]},
                        generated_dax=[{"name": "totals", "dax": "EVALUATE ROW(1,1)"}])
        published = azure_blob.publish_plan_cache(state1, first)
        check("day 1 publishes the verified plan",
              published["status"] == "ok" and len(published["pushed"]) == 1, published)

        # --- Day 2, on a BRAND NEW machine, exactly as a scheduled job gets ---
        day2 = Path(tmp) / "machine_2"
        state2 = cloud_state(day2)
        check("the new machine starts with nothing on disk",
              plan_cache.load(state2) is None)

        pulled = azure_blob.hydrate_plan_cache(state2)
        check("hydration pulls the stored plan down", pulled["status"] == "ok"
              and len(pulled["pulled"]) == 1, pulled)

        hit = plan_cache.load(state2)
        check("and the planning nodes now HIT on a machine that never planned",
              hit is not None and hit.get("dax_plan") == {"queries": [{"name": "totals"}]},
              hit)
        check("the executed DAX came back too, so Node 5 is skipped as well",
              hit is not None and hit.get("generated_dax"))

        # The key is content-derived, so the same model on any machine resolves
        # to the same file name - that is what makes the blob reunitable at all.
        check("both machines computed the same cache key",
              plan_cache.cache_key(state1) == plan_cache.cache_key(state2))


def test_eviction_reaches_the_cloud() -> None:
    print("\n=== a dropped plan is dropped everywhere, not just locally ===")

    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
            azure_blob, "_service_client", return_value=(service, "fake")):
        machine = Path(tmp) / "machine"
        state = cloud_state(machine)
        state["plan_cache_hit"] = True

        # Seed the store as an earlier run would have left it.
        seed = azure_blob.hydrate_plan_cache(state)
        plan_cache.save(state, generated_dax=[{"name": "totals", "dax": "EVALUATE ROW(1,1)"}])
        azure_blob.publish_plan_cache(state, seed)
        _account, container, _folder = azure_blob._plan_cache_location(state)
        check("the plan is in the blob store", len(service.data[container]) == 1)

        # Now one whole run, in main.py's order: hydrate once before the graph,
        # publish once after it. Ordering is the load-bearing part - a hydrate
        # placed after the eviction re-downloads the plan that was just dropped
        # and the eviction never leaves the machine.
        machine2 = Path(tmp) / "machine_2"
        run = cloud_state(machine2)
        run["plan_cache_hit"] = True
        hydration = azure_blob.hydrate_plan_cache(run)
        check("the run starts by pulling the stored plan",
              len(hydration["pulled"]) == 1, hydration)

        # Mid-run, the queries stop working and Node 7 drops the plan.
        dropped = plan_cache.record_execution(run, 1, 10)
        check("the failing plan is dropped locally", dropped is not None)

        result = azure_blob.publish_plan_cache(run, hydration)
        check("and the eviction is carried out to the blob",
              result["pruned"] and not service.data[container], result)

        # Otherwise a plan that stopped working would be pulled down every
        # morning and dropped again every morning, forever.
        check("so the next run cannot pull the broken plan back down",
              azure_blob.hydrate_plan_cache(cloud_state(Path(tmp) / "m3"))["pulled"] == [])


def test_a_network_blip_does_not_wipe_the_stored_plan() -> None:
    print("\n=== a failed download must not read as a deliberate eviction ===")

    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
            azure_blob, "_service_client", return_value=(service, "fake")):
        seeded = cloud_state(Path(tmp) / "machine_1")
        plan_cache.save(seeded, dax_plan={"queries": [{"name": "totals"}]})
        azure_blob.publish_plan_cache(seeded, azure_blob.hydrate_plan_cache(seeded))
        _account, container, _folder = azure_blob._plan_cache_location(seeded)
        check("a plan is stored", len(service.data[container]) == 1)

        # A fresh machine whose hydration failed: local is empty, but not
        # because anything was evicted. Pruning here would destroy the plan.
        blank = cloud_state(Path(tmp) / "machine_2")
        blip = {"status": "failed", "error": "connection reset"}
        result = azure_blob.publish_plan_cache(blank, blip)
        check("nothing is pruned after a failed hydration",
              result["pruned"] == [], result)
        check("the stored plan is still there", len(service.data[container]) == 1)

        # And the run that hit the blip simply re-plans, which is the pipeline's
        # behaviour today - never a stopped run.
        with patch.object(azure_blob, "_service_client",
                          side_effect=RuntimeError("connection reset")):
            failed = azure_blob.hydrate_plan_cache(blank)
        check("a hydration failure is reported, not raised",
              failed["status"] == "failed", failed)
        check("and it degrades to a cold run", plan_cache.load(blank) is None)


def test_reports_do_not_read_each_others_plans() -> None:
    print("\n=== one folder per dataset and report ===")

    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
            azure_blob, "_service_client", return_value=(service, "fake")):
        yoy = cloud_state(Path(tmp) / "m1", report_id="sales_yoy")
        plan_cache.save(yoy, dax_plan={"queries": [{"name": "yoy"}]})
        azure_blob.publish_plan_cache(yoy, azure_blob.hydrate_plan_cache(yoy))

        other = cloud_state(Path(tmp) / "m2", report_id="target_tracker")
        pulled = azure_blob.hydrate_plan_cache(other)
        check("a second report over the same model pulls nothing",
              pulled["pulled"] == [], pulled)

        _a, _c, yoy_folder = azure_blob._plan_cache_location(yoy)
        _a, _c, other_folder = azure_blob._plan_cache_location(other)
        check("their folders are different", yoy_folder != other_folder)
        check("and both name the dataset and the report",
              "sales_yoy" in yoy_folder and "target_tracker" in other_folder
              and yoy["dataset_id"] in yoy_folder, (yoy_folder, other_folder))

        # Publishing from the second report must not prune the first's plan,
        # which a shared folder would have made happen silently.
        azure_blob.publish_plan_cache(other, pulled)
        _account, container, _f = azure_blob._plan_cache_location(yoy)
        check("publishing one report never prunes another's plan",
              any(name.startswith(yoy_folder) for name in service.data[container]),
              sorted(service.data[container]))


def test_hydrate_and_publish_agree_after_the_graph() -> None:
    print("\n=== the folder must not move between hydrate and publish ===")

    # `report_id` is not a declared channel on SummaryAgentState, so LangGraph
    # drops it: main.py hydrates from the state it built (report_id present)
    # and publishes from the state `invoke` returned (report_id gone). Reading
    # it bare put those in `reports/sales_yoy/` and `reports/unknown_report/`,
    # so the plan was filed where the next run would never look and the cache
    # could never hit - caught by a live run, not by a test, which is why this
    # one exists. `config` survives the graph, and carries the identity.
    before = cloud_state(Path("/nonexistent"), report_id="sales_yoy")
    before["config"] = {**before["config"], "report_id": "sales_yoy"}
    after = {k: v for k, v in before.items() if k != "report_id"}

    check("the graph does drop report_id from the returned state",
          "report_id" in before and "report_id" not in after)
    check("hydrate and publish still resolve the SAME folder",
          azure_blob._plan_cache_location(before)
          == azure_blob._plan_cache_location(after),
          (azure_blob._plan_cache_location(before)[2],
           azure_blob._plan_cache_location(after)[2]))
    check("and that folder names the report rather than 'unknown_report'",
          "sales_yoy" in azure_blob._plan_cache_location(after)[2]
          and "unknown_report" not in azure_blob._plan_cache_location(after)[2],
          azure_blob._plan_cache_location(after)[2])

    # The same read is what keeps the cache KEY per-report. Inside the graph
    # every node sees report_id as absent, so without this two reports over one
    # model would compute one key and silently share a plan.
    other = dict(after, config={**after["config"], "report_id": "target_tracker"})
    check("the cache key is still per report inside the graph",
          plan_cache.cache_key(after) != plan_cache.cache_key(other))
    check("a --report override reaches both, because main.py folds it into config",
          "target_tracker" in azure_blob._plan_cache_location(other)[2])


def test_only_real_cache_files_move() -> None:
    print("\n=== anything else in the folder or the prefix is ignored ===")

    service = _Service()
    with tempfile.TemporaryDirectory() as tmp, patch.object(
            azure_blob, "_service_client", return_value=(service, "fake")):
        machine = Path(tmp) / "machine"
        state = cloud_state(machine)
        _account, container, folder = azure_blob._plan_cache_location(state)

        service.data.setdefault(container, {})[f"{folder}/notes.txt"] = b"hello"
        service.data[container][f"{folder}/README.json"] = b"{}"
        pulled = azure_blob.hydrate_plan_cache(state)
        check("a blob that is not a cache key is not pulled",
              pulled["pulled"] == [], pulled)

        directory = plan_cache._root(state)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "scratch.json").write_text("{}", encoding="utf-8")
        plan_cache.save(state, dax_plan={"queries": [{"name": "totals"}]})
        result = azure_blob.publish_plan_cache(state, pulled)
        check("only the real cache file is published",
              result["pushed"] == [plan_cache.cache_key(state) + ".json"], result)
        check("and the foreign blobs are left alone, not pruned",
              f"{folder}/notes.txt" in service.data[container],
              sorted(service.data[container]))


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
    test_the_switch_is_off_until_the_cache_is_on()
    test_the_plan_survives_a_wiped_machine()
    test_eviction_reaches_the_cloud()
    test_a_network_blip_does_not_wipe_the_stored_plan()
    test_reports_do_not_read_each_others_plans()
    test_hydrate_and_publish_agree_after_the_graph()
    test_only_real_cache_files_move()

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
