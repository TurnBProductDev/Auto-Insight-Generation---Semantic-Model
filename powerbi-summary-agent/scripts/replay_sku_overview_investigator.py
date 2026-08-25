"""SKU Overview investigation: adaptive "where does this rule-wide finding
concentrate". Offline.

    python scripts/replay_sku_overview_investigator.py

The adaptive loop, budget, and validation mechanics are proven once, shared
with Ageing/Daily Sales, in `replay_ageing_investigator.py`. This file
proves what changed: the eight-rule engine's findings are ESTATE-WIDE
(no single member to TREATAS-scope by), so the drill is "break this rule's
own population down by department/section/location/category", not
"zoom into an already-identified member" - the shape the original version
of this adapter assumed and which left it finding zero candidates against
live data (fixed 2026-08-24).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import sku_overview_investigator as inv  # noqa: E402

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


CFG = {
    "sku_overview_mapping": {
        "table": "REP_SSR_STOCK_STATUS_REPORTV3",
        "dimensions": {
            "department": "'REP_SSR_STOCK_STATUS_REPORTV3'[DEPARTMENT]",
            "section": "'REP_SSR_STOCK_STATUS_REPORTV3'[SECTION]",
            "location": "'REP_SSR_STOCK_STATUS_REPORTV3'[LOC_CODE]",
            "category": "'REP_SSR_STOCK_STATUS_REPORTV3'[CATEGORY_NAME]",
        },
    },
}

MODEL = {
    "currency": "USD",
    "stat_signals": [
        {"candidate_id": "sku_overview_segment_a_stockout:estate:",
         "analysis_type": "sku_overview_segment_a_stockout", "dimension": "estate",
         "affected_segment": "Segment A stockouts", "impact_value": 25872.17,
         "current": 2439, "description": "2,439 Segment A Loc-SKUs are out of stock.",
         "score": 500.0},
        {"candidate_id": "sku_overview_verge_stockout_fixable:estate:",
         "analysis_type": "sku_overview_verge_stockout_fixable", "dimension": "estate",
         "affected_segment": "Verge of stockout, fixable today", "impact_value": 100.0,
         "current": 10, "score": 400.0},
        # Not one of the four rule-derived types - never drillable.
        {"candidate_id": "sku_overview_urgent_state:recommended_action:STOCK OUT - PLACE ORDER",
         "analysis_type": "sku_overview_urgent_state", "dimension": "recommended_action",
         "affected_segment": "STOCK OUT - PLACE ORDER", "impact_value": 0.0, "score": 600.0},
    ],
}


def test_candidates_are_the_four_rule_types_only() -> None:
    print("\n=== which findings are drillable ===")
    found = inv.candidates(MODEL, CFG, max_findings=5)
    ids = [f["candidate_id"] for f in found]
    check("the legacy urgent-state finding is excluded (not a rule-derived type)",
          "sku_overview_urgent_state:recommended_action:STOCK OUT - PLACE ORDER" not in ids, ids)
    check("the segment A stockout finding survives",
          "sku_overview_segment_a_stockout:estate:" in ids, ids)
    check("the verge-stockout finding survives",
          "sku_overview_verge_stockout_fixable:estate:" in ids, ids)

    only = found[0]
    check("every mapped dimension is offered to drill into - there is no "
         "'own' role to exclude for an estate-wide finding",
          set(only["_drill_others"]) == {"department", "section", "location", "category"},
          only["_drill_others"])
    check("max_findings=0 returns nothing", inv.candidates(MODEL, CFG, max_findings=0) == [])
    check("no mapped dimensions at all -> nothing is offered",
          inv.candidates(MODEL, {"sku_overview_mapping": {}}, max_findings=5) == [])


def test_drill_dax_reuses_the_rule_own_predicate_and_scopes_to_shops() -> None:
    print("\n=== the drill DAX reuses each rule's own predicate, scoped to the five shops ===")
    dax = inv.build_drill_dax(CFG, own_role="sku_overview_segment_a_stockout",
                              own_member="Segment A stockouts", drill_role="department", limit=10)
    check("it scopes to the five shops, never the two warehouses",
          '{"ST1", "ST2", "ST3", "ST4", "ST5"}' in dax and '"WH1"' not in dax and '"WH2"' not in dax,
          dax)
    check("it reuses the exact Segment A stockout predicate",
          'SKUSEGMENT] = "SEG_A"' in dax and 'SKU_STOCK_STATUS] = "STOCK OUT"' in dax, dax)
    check("it groups by the requested drill dimension",
          "'REP_SSR_STOCK_STATUS_REPORTV3'[DEPARTMENT]," in dax, dax)
    check("it is TOPN-bounded to the requested limit", "TOPN(\n  10," in dax, dax)
    check("it counts Loc-SKUs, never re-derives a money figure of its own",
          "COUNTROWS(REP_SSR_STOCK_STATUS_REPORTV3)" in dax, dax)

    verge = inv.build_drill_dax(CFG, own_role="sku_overview_verge_stockout_fixable",
                                own_member="anything", drill_role="location", limit=5)
    check("a different rule uses its own predicate, not segment A's",
          'RECOMMENDED_ACTION] = "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE"' in verge
          and "SEG_A" not in verge, verge)

    check("an unknown rule type raises rather than silently building an empty predicate",
          _raises(lambda: inv.build_drill_dax(CFG, own_role="not_a_real_rule",
                                              own_member="x", drill_role="department")))
    check("an unmapped drill dimension raises rather than grouping by nothing",
          _raises(lambda: inv.build_drill_dax(CFG, own_role="sku_overview_segment_a_stockout",
                                              own_member="x", drill_role="brand")))


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def test_off_by_default_and_deterministic_smoke() -> None:
    print("\n=== off by default; a live run produces a grounded deterministic entry ===")

    def execute(dax: str) -> list[dict]:
        if "DEPARTMENT" in dax:
            return [{"'REP_SSR_STOCK_STATUS_REPORTV3'[DEPARTMENT]": "CONSUMER GOODS", "[value]": 1084}]
        return []

    off = inv.investigate(execute, MODEL, {**CFG}, log=None)
    check("no config key at all -> nothing runs", off["entries"] == [])

    with patch("src.tools.llm.get_llm", side_effect=RuntimeError("no LLM in this offline test")):
        on = inv.investigate(
            execute, MODEL, {**CFG, "sku_overview_investigation_enabled": True,
                             "sku_overview_investigation_max_findings": 1,
                             "sku_overview_investigation_max_rounds": 1,
                             "sku_overview_investigation_max_queries": 20,
                             "sku_overview_investigation_max_roles_per_finding": 20},
            log=None)
    check("one finding investigated with a single forced round", len(on["entries"]) == 1, on)
    entry = on["entries"][0]
    check("the narrative is grounded and passes validation (LLM unavailable in this "
         "offline test, so it falls back to the deterministic floor)",
          entry["authoring_mode"] == "deterministic" and "CONSUMER GOODS" in entry["narrative"],
          entry["narrative"])
    check("a Loc-SKU count is never printed with a currency code, even though "
         "MODEL declares currency=USD",
          "USD" not in entry["narrative"], entry["narrative"])


def main() -> int:
    print("=" * 72)
    print("SKU Overview investigation - adaptive drill-down (rule-population breakdown)")
    print("=" * 72)

    test_candidates_are_the_four_rule_types_only()
    test_drill_dax_reuses_the_rule_own_predicate_and_scopes_to_shops()
    test_off_by_default_and_deterministic_smoke()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SKU OVERVIEW INVESTIGATOR FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
