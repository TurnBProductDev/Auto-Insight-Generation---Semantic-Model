"""WP1: report identity and run scoping. Offline - no auth, no LLM, no network.

    python scripts/replay_report_scoping.py

The defect this closes: both memory stores were filed under
``<root>/<dataset_id>/memory.json``, so two reports over one semantic model
shared one rotation history and one reported-findings set. Each would suppress
the other's findings and overwrite the other's daily plan, and nothing would
detect it.

Checks, in the order they matter:

* two report ids on one dataset get genuinely separate summary stores
* insight memory is scoped to the **chain**, so reports that share a chain share
  one investigative memory - that is the WP8 design, not an oversight
* the legacy migration is non-destructive and idempotent
* a config naming no report behaves exactly as before, with its memory intact
* the dataset segment is never re-sanitised, so an existing store cannot be
  orphaned by a change of sanitiser
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import config_schema  # noqa: E402
from src.kernel import report as kernel_report  # noqa: E402
from src.kernel import scoping  # noqa: E402
from src.tools import insight_memory, summary_memory  # noqa: E402

DATASET = "11111111-2222-3333-4444-555555555555"

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


def state_for(root: Path, *, report_id: str | None = None,
              chain_id: str | None = None) -> dict:
    state = {
        "dataset_id": DATASET,
        "output_folder": "outputs",
        "summary_memory_root": str(root / "summary"),
        "insight_memory_root": str(root / "insight"),
    }
    if report_id is not None:
        state["report_id"] = report_id
    if chain_id is not None:
        state["chain_id"] = chain_id
    return state


def write_store(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def legacy_summary_store(marker: str) -> dict:
    return {
        "schema_version": 3, "watermark": "2026-07-31", "period_anchor": "2026-07",
        "records": {f"story:{marker}": {"first_seen": "2026-07-01"}},
        "journal": {}, "focus_records": {f"focus:{marker}": {"last_seen": "2026-07-30"}},
        "daily_plan": {}, "recent_focus": [], "area_records": {}, "weekly_coverage": {},
    }


# --------------------------------------------------------------- 1. separation


def test_reports_do_not_collide(root: Path) -> None:
    print("\n=== two reports on one dataset get separate stores ===")

    ageing = summary_memory.store_path(state_for(root, report_id="inventory_ageing"))
    yoy = summary_memory.store_path(state_for(root, report_id="sales_yoy"))

    check("the two paths differ", ageing != yoy, f"{ageing}\n{yoy}")
    check("each is filed under its own report id",
          ageing.parent.name == "inventory_ageing" and yoy.parent.name == "sales_yoy",
          f"{ageing.parent.name} / {yoy.parent.name}")
    check("both sit under the same dataset directory",
          ageing.parent.parent.parent == yoy.parent.parent.parent,
          f"{ageing.parent.parent.parent}\n{yoy.parent.parent.parent}")
    check("the layout is <dataset>/reports/<report_id>/memory.json",
          ageing.parent.parent.name == "reports" and ageing.name == "memory.json",
          str(ageing))

    # The point of the separation: writing one must not be visible in the other.
    write_store(ageing, legacy_summary_store("ageing"))
    write_store(yoy, legacy_summary_store("yoy"))
    ageing_records = json.loads(ageing.read_text(encoding="utf-8"))["records"]
    yoy_records = json.loads(yoy.read_text(encoding="utf-8"))["records"]
    check("a record written for one report is absent from the other",
          "story:ageing" in ageing_records and "story:ageing" not in yoy_records,
          f"ageing={list(ageing_records)} yoy={list(yoy_records)}")


def test_insight_is_chain_scoped(root: Path) -> None:
    print("\n=== insight memory is chain-scoped, deliberately ===")

    ageing = insight_memory.store_path(
        state_for(root, report_id="inventory_ageing", chain_id="inventory"))
    health = insight_memory.store_path(
        state_for(root, report_id="inventory_stock_health", chain_id="inventory"))
    sales = insight_memory.store_path(
        state_for(root, report_id="sales_yoy", chain_id="sales"))

    check("two reports in ONE chain share one insight store", ageing == health,
          f"{ageing}\n{health}")
    check("two different chains do not", ageing != sales, f"{ageing}\n{sales}")
    check("the layout is <root>/chains/<chain_id>/memory.json",
          ageing.parent.parent.name == "chains"
          and ageing.parent.name == "inventory",
          str(ageing))
    check("the derived markdown feed sits beside its store",
          insight_memory.markdown_path(
              state_for(root, chain_id="inventory")).parent == ageing.parent)

    # WP8: the dataset is a property of a REPORT, not of a chain. The two
    # inventory reports live in different semantic models, so nesting chain
    # memory under a dataset gave the one chain two stores - which is exactly
    # the sharing the chain exists to provide.
    other_model = state_for(root, report_id="inventory_stock_health",
                            chain_id="inventory")
    other_model["dataset_id"] = "64eefa4b-d82f-41bd-a841-fc1cfbd7a88a"
    across_models = insight_memory.store_path(other_model)
    check("two reports in one chain share a store even across DIFFERENT datasets",
          across_models == ageing, f"{across_models}\n{ageing}")
    check("the chain path contains no dataset segment at all",
          "11111111" not in str(ageing) and "64eefa4b" not in str(across_models),
          str(ageing))


# ---------------------------------------------------------------- 2. migration


def test_migration_non_destructive(root: Path) -> None:
    print("\n=== legacy migration: non-destructive and idempotent ===")

    summary_root = root / "summary"
    legacy = scoping.legacy_dir(summary_root, DATASET) / "memory.json"
    write_store(legacy, legacy_summary_store("legacy"))
    legacy_bytes = legacy.read_bytes()

    state = state_for(root)  # no report_id at all - a pre-WP1 config
    scoped = summary_memory.store_path(state)

    check("the scoped store was created", scoped.exists(), str(scoped))
    check("the legacy file still exists afterwards", legacy.exists(),
          "a rollback to pre-WP1 code must still find its memory")
    check("the legacy file is byte-identical - nothing was moved or rewritten",
          legacy.read_bytes() == legacy_bytes)
    check("the copy carries the real records across",
          json.loads(scoped.read_text(encoding="utf-8"))["records"]
          == legacy_summary_store("legacy")["records"])
    check("a config naming no report resolves to today's single report",
          scoped.parent.name == kernel_report.DEFAULT_REPORT_ID,
          f"resolved to {scoped.parent.name!r}")

    # Idempotence: the second call must not copy again, and must not clobber a
    # scoped store that has since moved on from the legacy one.
    store = json.loads(scoped.read_text(encoding="utf-8"))
    store["records"]["story:added_after_migration"] = {"first_seen": "2026-08-01"}
    scoped.write_text(json.dumps(store), encoding="utf-8")

    again = summary_memory.store_path(state)
    check("the path is stable across calls", again == scoped)
    check("a second call does NOT overwrite the scoped store from the legacy one",
          "story:added_after_migration"
          in json.loads(again.read_text(encoding="utf-8"))["records"],
          "migrate_store must return already_scoped once the scoped file exists")

    status = scoping.migrate_store(legacy, scoped)
    check("migrate_store reports already_scoped in the steady state",
          status == "already_scoped", f"status={status!r}")


def test_migration_statuses(root: Path) -> None:
    print("\n=== migrate_store reports what it actually did ===")

    legacy = root / "legacy" / "memory.json"
    scoped = root / "scoped" / "memory.json"

    check("no legacy and no scoped store -> no_legacy",
          scoping.migrate_store(legacy, scoped) == "no_legacy")
    check("and it does not create an empty file", not scoped.exists())

    write_store(legacy, {"schema_version": 3, "records": {}})
    check("a legacy store present -> migrated",
          scoping.migrate_store(legacy, scoped) == "migrated")
    check("the scoped file now exists", scoped.exists())
    check("running it again -> already_scoped",
          scoping.migrate_store(legacy, scoped) == "already_scoped")


def test_v4_migration_stamps_scope(root: Path) -> None:
    print("\n=== schema v4 records which report owns the store ===")

    summary_root = root / "summary"
    state = state_for(root, report_id="inventory_ageing")

    legacy = scoping.legacy_dir(summary_root, DATASET) / "memory.json"
    write_store(legacy, legacy_summary_store("v4"))

    store, status = summary_memory.load_store(state)
    check("the migrated store loads cleanly", status == "ok", f"status={status!r}")
    check("it is upgraded to the current schema", store["schema_version"] == 5,
          f"schema_version={store.get('schema_version')}")
    check("v1-v3 records are preserved untouched",
          store["records"] == legacy_summary_store("v4")["records"])
    check("the focus history is preserved too",
          store["focus_records"] == legacy_summary_store("v4")["focus_records"])
    check("the scope block names the report that claimed it",
          store["scope"].get("report_id") == "inventory_ageing",
          f"scope={store['scope']}")
    check("and records that it came from the dataset root",
          store["scope"].get("migrated_from") == "dataset_root",
          f"scope={store['scope']}")

    # A store that is already scoped keeps its stamp rather than being reclaimed.
    fresh_state = state_for(root, report_id="inventory_ageing")
    fresh_state["summary_memory_root"] = str(summary_root / "brand_new")
    new_store, new_status = summary_memory.load_store(fresh_state)
    check("a genuinely new store starts empty", new_status == "empty",
          f"status={new_status!r}")
    check("and carries an empty scope until something is written",
          new_store["scope"] == {}, f"scope={new_store['scope']}")


# ------------------------------------------------------------- 3. path safety


def test_dataset_segment_untouched(root: Path) -> None:
    print("\n=== the dataset segment is never re-sanitised ===")

    # The two memory modules sanitise the dataset id with different rules:
    # str.isalnum() admits non-ASCII letters, the regex does not. Re-sanitising
    # in kernel.scoping would relocate - and orphan - an existing store for any
    # id where they disagree. Each module keeps its own rule; scoping owns only
    # the segments it introduced.
    awkward = "dataseté-01"  # a non-ASCII letter: the two rules disagree here
    state = state_for(root, report_id="sales_yoy")
    state["dataset_id"] = awkward

    summary_path = summary_memory.store_path(state)
    summary_segment = summary_path.parent.parent.parent.name
    check("summary keeps its historical sanitiser (non-ASCII letter survives)",
          summary_segment == "dataseté-01", f"segment={summary_segment!r}")
    check("the two modules' sanitisers still genuinely differ, which is why "
          "kernel.scoping must not unify them",
          scoping.safe_segment(awkward) == "dataset_-01"
          and summary_segment != scoping.safe_segment(awkward),
          f"summary={summary_segment!r} scoping={scoping.safe_segment(awkward)!r}")
    # Insight memory no longer carries a dataset segment at all (WP8), so the
    # divergence cannot reach it.
    insight_path = insight_memory.store_path({**state, "chain_id": "sales"})
    check("the chain store is unaffected, having no dataset segment to sanitise",
          "dataset" not in str(insight_path).lower().replace("dataseté", ""),
          str(insight_path))


def test_safe_segment() -> None:
    print("\n=== report/chain ids are made path-safe ===")

    check("a path separator cannot escape the directory",
          scoping.safe_segment("../../etc/passwd") == ".._.._etc_passwd",
          scoping.safe_segment("../../etc/passwd"))
    check("a backslash is neutralised too",
          "\\" not in scoping.safe_segment("a\\b"))
    check("an empty id falls back rather than producing an empty segment",
          scoping.safe_segment("", "unknown_report") == "unknown_report")
    check("whitespace-only is treated as empty",
          scoping.safe_segment("   ", "unknown_report") == "unknown_report")
    check("an ordinary id passes through unchanged",
          scoping.safe_segment("inventory_ageing") == "inventory_ageing")

    print("\n=== a store is report-scoped or chain-scoped, never both ===")
    for kwargs in ({}, {"report_id": "a", "chain_id": "b"}):
        try:
            scoping.scoped_store(Path("x"), "ds", **kwargs)
            check(f"rejects {kwargs or 'neither id'}", False, "no error raised")
        except ValueError:
            check(f"rejects {kwargs or 'neither id'}", True)


# ------------------------------------------------------------- 4. ReportSpec


def test_report_spec() -> None:
    print("\n=== ReportSpec ===")

    spec = kernel_report.from_state({"dataset_id": DATASET})
    check("a state naming no report resolves to today's report",
          spec.report_id == "sales_yoy" and spec.chain_id == "sales",
          spec.summary())
    check("its later-WP sections are empty, not guessed at",
          spec.spine is None and spec.kpis == () and spec.layout is None
          and dict(spec.thresholds) == {})

    spec = kernel_report.from_state({
        "dataset_id": DATASET, "report_id": "inventory_ageing",
        "chain_id": "inventory", "report_domain": "inventory",
        "report_cadence": "weekly", "report_name": "Stock Ageing"})
    check("an explicit identity is carried through",
          (spec.report_id, spec.chain_id, spec.domain, spec.cadence)
          == ("inventory_ageing", "inventory", "inventory", "weekly"),
          spec.summary())

    # Frozen because WP3 shares one resolved spec across both concurrent
    # branches; a mutable one is a race waiting to be written.
    try:
        spec.report_id = "mutated"  # type: ignore[misc]
        check("the spec is immutable", False, "assignment succeeded")
    except Exception:
        check("the spec is immutable", True)

    check("evolve() returns a copy and leaves the original alone",
          spec.evolve(report_id="other").report_id == "other"
          and spec.report_id == "inventory_ageing")

    for bad in ({"report_id": ""}, {"chain_id": ""}, {"cadence": "hourly"}):
        try:
            kernel_report.ReportSpec(**bad)
            check(f"rejects {bad}", False, "no error raised")
        except ValueError:
            check(f"rejects {bad}", True)


def test_config_surface() -> None:
    print("\n=== config and CLI surface ===")

    keys = {entry.key: entry for entry in config_schema.KEYS}
    for key, default in (("report_id", "sales_yoy"), ("chain_id", "sales"),
                         ("report_domain", "sales"), ("report_cadence", "daily"),
                         ("report_name", "Sales vs Previous Year")):
        check(f"{key} is catalogued with default {default!r}",
              key in keys and keys[key].default == default,
              f"default={keys.get(key) and keys[key].default!r}")
        check(f"{key} reaches the graph state", key in keys and keys[key].in_state)

    # A config that predates WP1 must produce today's identity.
    defaults = config_schema.state_defaults({})
    spec = kernel_report.from_state({**defaults, "dataset_id": DATASET})
    check("an empty config resolves to today's report and chain",
          (spec.report_id, spec.chain_id) == ("sales_yoy", "sales"), spec.summary())

    # The flag wins over the config, mirroring POWERBI_TENANT_ID over tenant_id.
    overridden = config_schema.state_defaults({"report_id": "inventory_ageing"})
    check("a configured report id is honoured",
          kernel_report.from_state(overridden).report_id == "inventory_ageing")



def test_python311_dataclass_defaults() -> None:
    """Every dataclass default must be hashable, because 3.11 requires it.

    The container runs **python:3.11-slim**; development here is on 3.12. Those
    two disagree about exactly one thing that matters to this codebase:
    3.11's dataclasses reject any field default whose class has
    `__hash__ = None`, and on 3.11 `mappingproxy` is such a class. 3.12 gave it
    a real `__hash__`, so `thresholds: Mapping = MappingProxyType({})` imported
    cleanly here, passed every replay, and then crashed the container at import
    with "mutable default <class 'mappingproxy'> ... use default_factory".

    kernel/report.py landed on 2026-08-14 and the deployed image was built on
    2026-08-12, so the fault was invisible until the first rollout attempted it.

    This check reproduces 3.11's rule on any interpreter, so the next one is
    caught by the gate rather than by a failed deployment.
    """
    import dataclasses
    import importlib
    import pkgutil

    import src.kernel as kernel_pkg
    import src.domains as domains_pkg

    offenders = []
    for package in (kernel_pkg, domains_pkg):
        for module in pkgutil.walk_packages(package.__path__, package.__name__ + "."):
            try:
                loaded = importlib.import_module(module.name)
            except Exception:  # noqa: BLE001 - an optional dependency is not this test's job
                continue
            for attribute in vars(loaded).values():
                if not (isinstance(attribute, type) and dataclasses.is_dataclass(attribute)):
                    continue
                for f in dataclasses.fields(attribute):
                    default = f.default
                    if default is dataclasses.MISSING:
                        continue
                    if type(default).__hash__ is None:
                        offenders.append(f"{attribute.__qualname__}.{f.name} = {type(default).__name__}")
                        continue
                    try:
                        hash(default)
                    except TypeError:
                        offenders.append(
                            f"{attribute.__qualname__}.{f.name} "
                            f"({type(default).__name__} is unhashable at runtime)")
    check("no dataclass default would be rejected by Python 3.11",
          not offenders, "; ".join(offenders))


def main() -> int:
    print("=" * 72)
    print("WP1 report identity and run scoping")
    print("=" * 72)

    root = Path(tempfile.mkdtemp(prefix="wp1_scoping_"))
    try:
        # Each test gets its own root. Sharing one let an earlier test's
        # sales_yoy store make a later migration a no-op - correct behaviour
        # reported as a failure, which is a test bug, not a code bug.
        test_reports_do_not_collide(root / "separation")
        test_insight_is_chain_scoped(root / "chains")
        test_migration_non_destructive(root / "migration")
        test_migration_statuses(root / "statuses")
        test_v4_migration_stamps_scope(root / "v4")
        test_dataset_segment_untouched(root / "segments")
        test_safe_segment()
        test_report_spec()
        test_config_surface()
        test_python311_dataclass_defaults()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 72)
    if _failures:
        print(f"REPORT SCOPING FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
