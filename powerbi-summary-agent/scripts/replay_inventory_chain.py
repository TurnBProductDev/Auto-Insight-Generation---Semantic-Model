"""WP8: the inventory chain. Offline - no auth, no LLM, no network.

    python scripts/replay_inventory_chain.py

One investigative pass over pooled evidence, separate summaries per report. The
four things that must hold (brief WP8 exit criteria):

* pooled evidence keeps ``report_id``, so a finding can name its dashboard
* **a loud report cannot starve a quiet one**
* a chain of one behaves exactly like a standalone run
* chain memory commits once, and is shared across datasets
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.kernel import chain, scoping  # noqa: E402
from src.tools import insight_memory  # noqa: E402

AGEING_DATASET = "84212fd9-6504-4b22-a46b-e64109a1ab89"
STOCK_DATASET = "64eefa4b-d82f-41bd-a841-fc1cfbd7a88a"

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


INVENTORY = chain.ChainSpec(
    chain_id="inventory",
    report_ids=("inventory_ageing", "inventory_stock_health"),
    title="Inventory: what changed and why",
)


def test_spec() -> None:
    print("\n=== the chain specification ===")

    check("a chain names its reports in order",
          INVENTORY.report_ids == ("inventory_ageing", "inventory_stock_health"))
    check("a chain of two is not a single-report chain", not INVENTORY.is_single_report)
    check("a chain of one is recognised as such",
          chain.ChainSpec("solo", ("sales_yoy",)).is_single_report)

    for bad, why in (({"chain_id": "", "report_ids": ("a",)}, "empty chain id"),
                     ({"chain_id": "c", "report_ids": ()}, "no reports"),
                     ({"chain_id": "c", "report_ids": ("a", "a")}, "duplicate report")):
        try:
            chain.ChainSpec(**bad)
            check(f"rejects {why}", False, "no error raised")
        except ValueError:
            check(f"rejects {why}", True)


def test_sequential_and_pooled() -> None:
    print("\n=== reports run sequentially, in one process, and pool evidence ===")

    order: list[str] = []

    def run_report(report_id: str) -> dict:
        order.append(report_id)
        if report_id == "inventory_ageing":
            return {"dataset_id": AGEING_DATASET, "evidence": [
                {"finding": "SAR 788K over two years old", "score": 61.0},
                {"finding": "SAR 2.76M aged and not selling", "score": 44.0}]}
        return {"dataset_id": STOCK_DATASET, "evidence": [
            {"finding": "17,717 lines out of stock with no order", "score": 78.0}]}

    result = chain.run(INVENTORY, run_report)

    check("reports ran in the declared order - Non-negotiable 2 forbids parallel",
          order == list(INVENTORY.report_ids), order)
    check("both reports produced a result", len(result.reports) == 2)
    check("their evidence is pooled into one list", len(result.evidence) == 3)
    check("every pooled item carries its report_id",
          all(item.get("report_id") for item in result.evidence))
    check("...and its dataset_id, because the two models are different",
          {item["dataset_id"] for item in result.evidence}
          == {AGEING_DATASET, STOCK_DATASET})
    check("both reports are recorded as contributing",
          set(result.contributing_reports) == set(INVENTORY.report_ids),
          result.contributing_reports)

    print("\n--- one report failing does not cost the others their output ---")
    def half_broken(report_id: str) -> dict:
        if report_id == "inventory_ageing":
            raise RuntimeError("scan timed out")
        return {"evidence": [{"finding": "still here", "score": 10.0}]}

    partial = chain.run(INVENTORY, half_broken)
    check("the failure is recorded with its reason",
          "scan timed out" in partial.failures.get("inventory_ageing", ""))
    check("the other report still ran and contributed",
          partial.contributing_reports == ("inventory_stock_health",),
          partial.contributing_reports)


def test_loud_report_cannot_starve_a_quiet_one() -> None:
    print("\n=== a loud report cannot starve a quiet one ===")

    # The stock-health report has many large movements; ageing has one modest
    # finding. With a cap of 3 and pure score ranking, ageing vanishes entirely.
    loud = [{"report_id": "inventory_stock_health", "finding": f"exception {i}",
             "score": 90.0 - i} for i in range(6)]
    quiet = [{"report_id": "inventory_ageing", "finding": "aged and not selling",
              "score": 44.0}]
    candidates = loud + quiet

    naive = sorted(candidates, key=lambda c: c["score"], reverse=True)[:3]
    check("WITHOUT the guarantee, the quiet report is crowded out entirely",
          not any(c["report_id"] == "inventory_ageing" for c in naive),
          [c["report_id"] for c in naive])

    fair = chain.fair_share(candidates, naive, limit=3)
    check("WITH it, the quiet report is represented",
          any(c["report_id"] == "inventory_ageing" for c in fair),
          [(c["report_id"], c["score"]) for c in fair])
    check("the loud report still holds the rest of the places",
          sum(1 for c in fair if c["report_id"] == "inventory_stock_health") == 2)
    check("the injected candidate is that report's BEST, not an arbitrary one",
          next(c for c in fair if c["report_id"] == "inventory_ageing")["score"] == 44.0)

    print("\n--- but it is representation, NOT priority ---")
    check("the list is still ordered purely by score",
          [c["score"] for c in fair] == sorted((c["score"] for c in fair), reverse=True),
          [c["score"] for c in fair])
    check("the injected candidate did NOT jump ahead of stronger ones",
          fair[0]["score"] > 44.0, fair[0])
    check("a report gets one place, never a quota",
          sum(1 for c in chain.fair_share(candidates, [], limit=6)
              if c["report_id"] == "inventory_ageing") == 1)

    print("\n--- when the limit cannot fit everyone, score decides ---")
    three_reports = candidates + [
        {"report_id": "inventory_returns", "finding": "tiny", "score": 1.0}]
    squeezed = chain.fair_share(three_reports, [], limit=2)
    check("the weakest claim is dropped, not whichever report was listed last",
          not any(c["report_id"] == "inventory_returns" for c in squeezed),
          [(c["report_id"], c["score"]) for c in squeezed])

    print("\n--- and it reports who was left out ---")
    check("uncovered_reports names the missing report",
          chain.uncovered_reports(candidates, naive) == ("inventory_ageing",),
          chain.uncovered_reports(candidates, naive))
    check("nothing is reported missing once everyone is represented",
          chain.uncovered_reports(candidates, fair) == ())


def test_chain_of_one() -> None:
    print("\n=== a chain of one equals a standalone run ===")

    solo = chain.ChainSpec("sales", ("sales_yoy",))
    payload = {"dataset_id": "b3458a38", "evidence": [
        {"finding": "revenue up", "score": 12.0}]}
    result = chain.run(solo, lambda _report_id: payload)

    check("exactly one report ran", list(result.reports) == ["sales_yoy"])
    check("the evidence is the report's own, with provenance added",
          len(result.evidence) == 1
          and result.evidence[0]["finding"] == "revenue up"
          and result.evidence[0]["report_id"] == "sales_yoy")
    check("the source payload is not mutated by tagging",
          "report_id" not in payload["evidence"][0])

    # With one report there is nobody to be crowded out, so fair_share must be
    # a no-op - otherwise a chain of one would not equal a standalone run.
    selected = [{"report_id": "sales_yoy", "score": 12.0}]
    check("fair_share changes nothing for a single-report chain",
          chain.fair_share(result.evidence, selected, limit=5) == selected)


def test_chain_memory(root: Path) -> None:
    print("\n=== chain memory: one store, shared across datasets ===")

    def state(dataset: str) -> dict:
        return {"dataset_id": dataset, "chain_id": "inventory",
                "insight_memory_root": str(root / "insight")}

    ageing_path = insight_memory.store_path(state(AGEING_DATASET))
    stock_path = insight_memory.store_path(state(STOCK_DATASET))

    check("both inventory reports resolve to ONE chain store",
          ageing_path == stock_path, f"{ageing_path}\n{stock_path}")
    check("the path is <root>/chains/inventory/memory.json",
          ageing_path.parent.name == "inventory"
          and ageing_path.parent.parent.name == "chains", str(ageing_path))
    check("a different chain gets a different store",
          insight_memory.store_path(
              {**state(AGEING_DATASET), "chain_id": "sales"}) != ageing_path)

    print("\n--- migrating from the WP1 dataset-nested location ---")
    fresh = root / "migrate"
    legacy = (fresh / scoping.safe_segment(AGEING_DATASET) / "chains"
              / "inventory" / "memory.json")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text('{"schema_version": 1, "records": {"story:old": {}}}',
                      encoding="utf-8")

    scoped, status = scoping.scoped_store(
        fresh, scoping.safe_segment(AGEING_DATASET), chain_id="inventory")
    check("the older dataset-nested store is migrated", status == "migrated", status)
    check("its records come across",
          "story:old" in scoped.read_text(encoding="utf-8"))
    check("the legacy file survives - a rollback must still find its memory",
          legacy.exists())
    _again, second = scoping.scoped_store(
        fresh, scoping.safe_segment(AGEING_DATASET), chain_id="inventory")
    check("a second call is a no-op", second == "already_scoped", second)


def test_attribution() -> None:
    print("\n=== a pooled finding names where it came from ===")

    names = {"inventory_ageing": "Stock Age Analysis",
             "inventory_stock_health": "Inventory Management"}
    check("it names the report in words a reader recognises",
          chain.attribution({"report_id": "inventory_ageing"}, names)
          == "From Stock Age Analysis.")
    check("an unknown id still produces something readable",
          chain.attribution({"report_id": "inventory_returns"})
          == "From Inventory Returns.")
    check("a finding with no provenance says nothing rather than guessing",
          chain.attribution({}) == "")


def main() -> int:
    print("=" * 72)
    print("WP8 inventory chain")
    print("=" * 72)

    root = Path(tempfile.mkdtemp(prefix="wp8_chain_"))
    try:
        test_spec()
        test_sequential_and_pooled()
        test_loud_report_cannot_starve_a_quiet_one()
        test_chain_of_one()
        test_chain_memory(root)
        test_attribution()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print("\n" + "=" * 72)
    if _failures:
        print(f"INVENTORY CHAIN FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
