"""Offline proof of the Inventory Management live scan and its snapshot archive.

No Power BI, no Azure, no LLM: the scan is driven by a fake executor that
records the DAX it is handed and replays canned rows, so every query can be
inspected as text without a connection.

Two things are under test and they fail differently:

* **The scan** must produce exactly the dict `stock_health.build` already
  consumes, or the existing replays and auditors silently stop describing the
  artifact they claim to.
* **The archive** must never manufacture a comparison. Every refusal path is a
  named test here, because the failure mode is not a crash - it is a page that
  confidently reports a movement that did not happen.

    python scripts/replay_inventory_scan.py
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import archive  # noqa: E402
from src.domains.inventory.reports import stock_health as sh  # noqa: E402

FAILURES: list[str] = []

#: The real committed scan. It came from a different client's model, which is
#: exactly why it is the right fixture for a *shape* test: if the scan only
#: reproduced the shape of the model it was written against, this would pass by
#: coincidence rather than by contract.
COMMITTED_SCAN = PROJECT_ROOT / "outputs_stock_health" / "stock_health_scan.json"
COMMITTED_MODEL = PROJECT_ROOT / "outputs_stock_health" / "report_stock_health.json"


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


class FakeExecutor:
    """Replays the committed scan block by block, recording every query."""

    def __init__(self, scan: dict, *, fail_on: str = "") -> None:
        self.queries: list[str] = []
        self._fail_on = fail_on
        # The scan calls its blocks in a fixed order; map each returned table to
        # the committed block whose shape it must match.
        self._by_marker = [
            ("[UPDATED_ON]", scan.get("snapshot")),
            ("[RECOMMENDED_ACTION]", scan.get("actions")),
            ("[SKU_STOCK_STATUS]", scan.get("status")),
            ("[LOC_CODE], ", scan.get("locations")),
            ("[SECTION]", scan.get("sections")),
            ("[DEPARTMENT]", scan.get("divisions")),
            ("[SKUSEGMENT],", scan.get("segments")),
            ("[NM DAYS TAG]", scan.get("non_moving_bands")),
            ("month_date", scan.get("damage")),
            ("opp_loss_all", scan.get("opportunity_loss")),
            ("unwanted_skus", scan.get("unwanted")),
        ]

    def __call__(self, dax: str) -> list[dict]:
        self.queries.append(dax)
        if self._fail_on and self._fail_on in dax:
            raise RuntimeError("executor refused")
        for marker, rows in self._by_marker:
            if marker in dax:
                return list(rows or [])
        return []


def test_scan_shape() -> None:
    print("\nThe scan returns exactly the blocks build() consumes")
    committed = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    execute = FakeExecutor(committed)
    produced = sh.scan(execute, {"workspace_id": "ws", "dataset_id": "ds"})

    check("every committed block is produced",
          set(committed) <= set(produced),
          f"missing: {sorted(set(committed) - set(produced))}")
    # The committed scan predates the health-score blocks, so the produced scan
    # carries those plus provenance. Named explicitly rather than allowed
    # loosely: a block appearing here that build() does not read is dead weight
    # that still costs a query against the model.
    expected_new = {"provenance", "health_overall", "health_by_location",
                    "health_by_division", "health_status", "trend"}
    check("nothing is produced that is not either committed or expected",
          set(produced) - set(committed) == expected_new,
          f"unexpected: {sorted(set(produced) - set(committed) - expected_new)}")

    # A scan that returns the right keys holding nothing is not a working scan.
    empty = [name for name in committed if not produced.get(name)]
    check("no produced block is empty", not empty, f"empty: {empty}")

    # This fixture comes from a model with no `_HEALTH SCORE MEASURES` table at
    # all, so its health blocks come back empty. That is the degrade path, and
    # it must end in the score layers being dropped rather than rendered as
    # zeros.
    from src.domains.inventory import health

    check("a model with no health score reports none",
          health.available(produced) is False)
    check("and builds no score model rather than an empty one",
          health.build(produced) is None)

    print("\nbuild() over the produced scan yields the committed model's shape")
    from_committed = sh.build(committed)
    from_produced = sh.build(produced)
    check("identical key set", set(from_produced) == set(from_committed))
    check("every reconciliation check present and passing",
          from_produced["checks"] == from_committed["checks"],
          f"{from_produced['checks']}")
    check("the queue carries every documented state the data returned",
          len(from_produced["queue"]) == len(from_committed["queue"]))
    committed_model = json.loads(COMMITTED_MODEL.read_text(encoding="utf-8"))
    check("rebuilding the committed scan is still byte-identical",
          json.dumps(from_committed, sort_keys=True, default=str)
          == json.dumps(committed_model, sort_keys=True, default=str))


def test_scan_is_bounded() -> None:
    print("\nThe scan is bounded and refuses to exceed its budget")
    committed = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    execute = FakeExecutor(committed)
    produced = sh.scan(execute, {})
    check("sixteen queries, no more", len(execute.queries) == 16,
          str(len(execute.queries)))
    check("provenance records the count", produced["provenance"]["queries"] == 16)

    raised = False
    try:
        sh.scan(FakeExecutor(committed), {"inventory_max_queries": 3})
    except sh.ScanBudgetExceeded:
        raised = True
    check("a budget below the query count raises", raised)

    # Every query must be filtered or aggregated by construction. An unadorned
    # `EVALUATE 'Table'` would return 139,732 rows over the wire.
    bare = [q for q in execute.queries
            if "SUMMARIZECOLUMNS" not in q and "ROW(" not in q]
    check("no query returns raw fact rows", not bare, f"{len(bare)} bare query(ies)")


def test_health_rollups_key_on_the_fact_table() -> None:
    print("\nHealth roll-ups key on the fact table, which propagates")
    committed = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    execute = FakeExecutor(committed)
    sh.scan(execute, {})
    rollups = [q for q in execute.queries
               if "Inventory Health Score" in q and "SUMMARIZECOLUMNS" in q]
    check("both roll-ups scan the fact table", len(rollups) == 2, str(len(rollups)))
    check("never LOC_CATEGORY_HEALTH or P90 - they carry no relationships, so "
          "slicing them returns the company total for every member",
          not any("LOC_CATEGORY_HEALTH" in q or "P90" in q for q in execute.queries))
    check("the score itself is read once, unsliced",
          sum(1 for q in execute.queries
              if "Total Points Lost" in q and "SUMMARIZECOLUMNS" not in q) == 1)


def test_no_real_location_codes_leak() -> None:
    print("\nThe real location codes can never reach published output")
    committed = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    execute = FakeExecutor(committed)
    sh.scan(execute, {})
    leaking = [q for q in execute.queries if "[locsku]" in q.lower()]
    check("no query selects locsku", not leaking,
          "locsku embeds the real location code behind the ST/WH display alias")

    # And the guard is live, not merely satisfied by today's queries. Driven
    # through the real function, so deleting it fails this test.
    raised = False
    try:
        sh.reject_forbidden("probe", f"EVALUATE SUMMARIZECOLUMNS('{sh.FACT}'[locsku])")
    except ValueError:
        raised = True
    check("the guard rejects a query that does select it", raised)
    check("and lets an ordinary aggregate through",
          sh.reject_forbidden("probe", "EVALUATE ROW(\"n\", 1)") is None)


def test_br16_scope() -> None:
    print("\nOpportunity Loss carries all three of BR-16's hard limits")
    scope = sh._critical_store_scope()
    check("critical segments only", '"SEG_A"' in scope and '"SEG_B"' in scope)
    check("local procurement only", '"LOCAL"' in scope)
    check("stores only, never a warehouse", '"SH"' in scope)
    check("scoped with TREATAS, not an equality", scope.count("TREATAS(") == 3)
    check("no KEEPFILTERS equality", "KEEPFILTERS" not in scope,
          "fails on this model with 'single value for column cannot be determined'")

    committed = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    execute = FakeExecutor(committed)
    sh.scan(execute, {})
    opp = next(q for q in execute.queries if "opp_loss_all" in q)
    check("the unscoped figure is kept, so a caveat can name the gap",
          "opp_loss_all" in opp and "opp_loss_model_column" in opp)
    check("the published figure is the scoped one", "opp_loss_stores_critical" in opp)

    # The trap this guards: publishing the unscoped figure overstates the
    # measure roughly six-fold. Proven against the model the report ships with.
    model = sh.build(committed)
    header = model["header"]
    check("the model publishes the scoped figure, not the raw one",
          header["opportunity_loss_day"] < header["opportunity_loss_unscoped"],
          f"{header['opportunity_loss_day']} vs {header['opportunity_loss_unscoped']}")
    check("and says so in a caveat",
          any("stores only" in c.lower() or "critical products at stores" in c.lower()
              for c in model["caveats"]))


def test_provenance() -> None:
    print("\nProvenance records the run date, which is not the as-at stamp")
    committed = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    produced = sh.scan(FakeExecutor(committed), {"workspace_id": "ws", "dataset_id": "ds"})
    prov = produced["provenance"]
    check("names the dataset it read", prov["dataset_id"] == "ds")
    check("names the workspace", prov["workspace_id"] == "ws")
    check("carries the run date", prov["scanned_on"] == _dt.date.today().isoformat())
    check("carries the model's own as-at separately", prov["as_at"] == "2026-08-12")
    check("the two are distinct fields", prov["scanned_on"] != prov["as_at"],
          "collapsing them is what makes a same-stamp reload look like a day's movement")


def _scan_with(as_at: str) -> dict:
    return {
        "snapshot": [{"[as_at]": f"{as_at}T00:00:00", "[stock_value]": 100.0}],
        "provenance": {"as_at": as_at},
    }


def test_archive_round_trip() -> None:
    print("\nThe archive keeps one dated position per run day")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {"inventory_archive_enabled": True}
        day = _dt.date(2026, 8, 21)
        path = archive.write(_scan_with("2026-08-19"), tmp, cfg, run_date=day)
        check("written under the run date", path.name == "scan_2026-08-21.json")
        check("found by the listing", len(archive.archived_runs(tmp, cfg)) == 1)

        # A second run the same day replaces that day's file rather than adding.
        archive.write(_scan_with("2026-08-20"), tmp, cfg, run_date=day)
        check("a second run the same day overwrites, never appends",
              len(archive.archived_runs(tmp, cfg)) == 1)

        check("today is excluded when looking for a prior",
              archive.latest_prior(tmp, cfg, run_date=day) is None,
              "otherwise every run compares against itself and reports no change")

        archive.write(_scan_with("2026-08-18"), tmp, cfg, run_date=_dt.date(2026, 8, 20))
        found = archive.latest_prior(tmp, cfg, run_date=day)
        check("the most recent earlier run is the prior",
              found is not None and found[0] == _dt.date(2026, 8, 20))

    with tempfile.TemporaryDirectory() as tmp:
        check("archiving off writes nothing",
              archive.write(_scan_with("2026-08-19"), tmp,
                            {"inventory_archive_enabled": False}) is None)


def test_archive_refuses_a_dishonest_comparison() -> None:
    print("\nEvery way a comparison could be dishonest is refused, and says why")
    cfg = {"inventory_archive_enabled": True, "inventory_archive_max_age_days": 14}
    today = _dt.date(2026, 8, 21)

    with tempfile.TemporaryDirectory() as tmp:
        verdict = archive.compare_window(_scan_with("2026-08-19"), tmp, cfg, run_date=today)
        check("first run: no prior", verdict["reason"] == archive.NO_PRIOR)
        check("and not comparable", verdict["comparable"] is False)
        check("with a sentence the page can print", bool(verdict["reason_text"]))
        check("that never reads as 'no change'",
              "no change" not in verdict["reason_text"].lower())

    with tempfile.TemporaryDirectory() as tmp:
        archive.write(_scan_with("2026-07-01"), tmp, cfg, run_date=_dt.date(2026, 7, 2))
        verdict = archive.compare_window(_scan_with("2026-08-19"), tmp, cfg, run_date=today)
        check("a prior outside the window is refused",
              verdict["reason"] == archive.PRIOR_TOO_OLD, verdict["reason"])
        check("and the age is reported", verdict["age_days"] == 50)

    with tempfile.TemporaryDirectory() as tmp:
        archive.write(_scan_with("2026-08-19"), tmp, cfg, run_date=_dt.date(2026, 8, 20))
        verdict = archive.compare_window(_scan_with("2026-08-19"), tmp, cfg, run_date=today)
        check("an unchanged as-at stamp is refused",
              verdict["reason"] == archive.AS_AT_UNCHANGED, verdict["reason"])
        check("this is the measured case, not a hypothetical",
              verdict["prior_as_at"] == "2026-08-19",
              "on 2026-08-21 the live model still stamped 2026-08-19 while holding "
              "139,732 scored lines against the reference's 120,897")

    with tempfile.TemporaryDirectory() as tmp:
        archive.write(_scan_with("2026-08-19"), tmp, cfg, run_date=_dt.date(2026, 8, 20))
        verdict = archive.compare_window(_scan_with("2026-08-15"), tmp, cfg, run_date=today)
        check("an as-at that went backwards is refused",
              verdict["reason"] == archive.AS_AT_WENT_BACKWARDS, verdict["reason"])

    with tempfile.TemporaryDirectory() as tmp:
        archive.write(_scan_with("2026-08-18"), tmp, cfg, run_date=_dt.date(2026, 8, 20))
        verdict = archive.compare_window(_scan_with("2026-08-19"), tmp, cfg, run_date=today)
        check("an advanced as-at inside the window IS comparable",
              verdict["comparable"] is True, verdict["reason"])
        check("labelled by the position it compares against",
              verdict["label"] == "since 2026-08-18")
        check("and carries no refusal sentence", verdict["reason_text"] == "")


def test_movement() -> None:
    print("\nA movement is None when it cannot be measured, never zero")
    now = _scan_with("2026-08-19")
    before = _scan_with("2026-08-18")
    moved = archive.movement(now, before, ("snapshot",), key="stock_value")
    check("an equal pair reads flat, not absent",
          moved is not None and moved["direction"] == "flat")

    before["snapshot"] = [{"[as_at]": "2026-08-18T00:00:00", "[stock_value]": 80.0}]
    moved = archive.movement(now, before, ("snapshot",), key="stock_value")
    check("a real move is measured", moved["change"] == 20.0)
    check("and expressed as a share of the prior", round(moved["change_pct"], 1) == 25.0)
    check("with a direction", moved["direction"] == "up")

    check("a missing measure yields None, not a fabricated zero",
          archive.movement(now, before, ("snapshot",), key="excess_value") is None)
    check("a missing block yields None",
          archive.movement(now, before, ("nope",), key="stock_value") is None)


def main() -> int:
    print("=" * 72)
    print("Inventory Management - live scan and snapshot archive")
    print("=" * 72)
    test_scan_shape()
    test_scan_is_bounded()
    test_health_rollups_key_on_the_fact_table()
    test_no_real_location_codes_leak()
    test_br16_scope()
    test_provenance()
    test_archive_round_trip()
    test_archive_refuses_a_dishonest_comparison()
    test_movement()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
