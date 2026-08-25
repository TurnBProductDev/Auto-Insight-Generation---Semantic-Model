"""Daily Sales investigation: adaptive "where does this Net Sales gap
concentrate". Offline.

    python scripts/replay_daily_sales_investigator.py

The adaptive loop, budget, and validation mechanics are proven once, shared
with Ageing/SKU Overview, in `replay_ageing_investigator.py`. This file
proves what is genuinely Daily-Sales-specific: only NET SALES findings are
drillable - never Margin, which is a ratio, and never Bills, which does not
add up across grains (one basket touching three departments counts once in
each, so a section Bills gap can exceed its own department gap, which is
what shipped once); a department may drill into section OR category, a
section only into category; the drill DAX picks the right table and scope
column for each hop AND keeps its filters attached to the aggregation; and
the drilled gaps are put on the reporting scale before they are shown beside
figures that already are.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.sales import daily_sales_investigator as inv  # noqa: E402

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
    "daily_sales_mapping": {
        "store_table": "storebenchmark", "department_table": "departmentbenchmark",
        "section_table": "sectionbenchmark", "category_table": "categorybenchmark",
        "department_col": "DEPARTMENT", "section_col": "SECTION",
        "category_col": "CATEGORY_NAME_2", "category_group_col": "CATEGORY_NAME",
    },
}

MODEL = {
    "currency": "USD",
    "stat_signals": [
        {"candidate_id": "daily_sales_department_net_sales:CONSUMER GOODS:",
         "analysis_type": "daily_sales_department_net_sales_band", "dimension": "department",
         "affected_segment": "CONSUMER GOODS", "impact_value": -1437.1, "current": 32517.9,
         "description": "CONSUMER GOODS finished Net Sales underperforming.", "score": 1437.1},
        {"candidate_id": "daily_sales_section_net_sales:SPICE MARKET:",
         "analysis_type": "daily_sales_section_net_sales_band", "dimension": "section",
         "affected_segment": "SPICE MARKET", "impact_value": -265.61, "current": 2713.44,
         "description": "SPICE MARKET finished Net Sales underperforming.", "score": 265.61},
        # Margin: never drillable - it is a ratio, there is nowhere to "drill".
        {"candidate_id": "daily_sales_whole_margin::",
         "analysis_type": "daily_sales_whole_margin_band", "dimension": "whole",
         "affected_segment": "", "impact_value": 0.2, "score": 1.0},
        # Bills: available at every grain, and still never drilled, because it
        # does not add up across them (see this file's module docstring).
        {"candidate_id": "daily_sales_department_bills:CONSUMER GOODS:",
         "analysis_type": "daily_sales_department_bills_band", "dimension": "department",
         "affected_segment": "CONSUMER GOODS", "impact_value": -19.0, "score": 19.0},
        # Whole-business: no single member to scope a filter by, so it is
        # never offered either.
        {"candidate_id": "daily_sales_whole_net_sales::",
         "analysis_type": "daily_sales_whole_net_sales_band", "dimension": "whole",
         "affected_segment": "", "impact_value": -98.79, "score": 494.0},
    ],
}


def test_candidates_are_net_sales_only_and_hierarchy_aware() -> None:
    print("\n=== only Net Sales findings are drillable, and only department/section ===")
    found = inv.candidates(MODEL, CFG, max_findings=5)
    ids = [f["candidate_id"] for f in found]
    check("the Margin finding is excluded - a ratio has nowhere to drill",
          "daily_sales_whole_margin::" not in ids, ids)
    check("a Bills finding is excluded - Bills does not add up across grains",
          "daily_sales_department_bills:CONSUMER GOODS:" not in ids, ids)
    check("the whole-business finding is excluded - no single member to scope by",
          "daily_sales_whole_net_sales::" not in ids, ids)
    check("the department Net Sales finding survives",
          "daily_sales_department_net_sales:CONSUMER GOODS:" in ids, ids)
    check("the section Net Sales finding survives",
          "daily_sales_section_net_sales:SPICE MARKET:" in ids, ids)

    by_id = {f["candidate_id"]: f for f in found}
    dept = by_id["daily_sales_department_net_sales:CONSUMER GOODS:"]
    check("a department finding may drill into section or category",
          set(dept["_drill_others"]) == {"section", "category"}, dept["_drill_others"])
    section = by_id["daily_sales_section_net_sales:SPICE MARKET:"]
    check("a section finding may only drill into category",
          set(section["_drill_others"]) == {"category"}, section["_drill_others"])

    check("max_findings=0 returns nothing", inv.candidates(MODEL, CFG, max_findings=0) == [])


def test_drill_dax_picks_the_right_table_and_scope() -> None:
    print("\n=== the drill DAX is deterministic, and picks the right table/scope per hop ===")
    to_section = inv.build_drill_dax(CFG, own_role="department", own_member="CONSUMER GOODS",
                                     drill_role="section", limit=10)
    check("department->section reads the section table", "sectionbenchmark" in to_section, to_section)
    check("department->section scopes by DEPARTMENT", 'sectionbenchmark[DEPARTMENT] = "CONSUMER GOODS"'
          in to_section, to_section)
    check("it resolves the section table's own latest date, never a literal DATE(...)",
          "[Section Latest Date]" in to_section and "DATE(" not in to_section, to_section)
    check("the aggregation is summarised over the SCOPED table variable - wrapping "
          "SUMMARIZE in CALCULATETABLE and adding the aggregation outside it loses "
          "every filter and sums every day the table holds",
          "CALCULATETABLE(" not in to_section and "Scoped," in to_section, to_section)
    check("it drills Net Sales, not the non-additive Bills count",
          "actual_sales" in to_section and "actual_bills" not in to_section, to_section)
    check("rows that recorded no sale are dropped, matching the page rollup",
          "NOT ISBLANK(sectionbenchmark[actual_sales])" in to_section, to_section)

    to_category_from_dept = inv.build_drill_dax(CFG, own_role="department", own_member="CONSUMER GOODS",
                                                drill_role="category", limit=10)
    check("department->category reads the category table",
          "categorybenchmark" in to_category_from_dept, to_category_from_dept)
    check("department->category scopes by DEPARTMENT (not SECTION - there is none yet)",
          'categorybenchmark[DEPARTMENT] = "CONSUMER GOODS"' in to_category_from_dept,
          to_category_from_dept)

    to_category_from_section = inv.build_drill_dax(CFG, own_role="section", own_member="SPICE MARKET",
                                                    drill_role="category", limit=10)
    check("section->category scopes by SECTION, not DEPARTMENT",
          'categorybenchmark[SECTION] = "SPICE MARKET"' in to_category_from_section,
          to_category_from_section)

    check("an unsupported drill_role raises rather than silently building a wrong query",
          _raises(lambda: inv.build_drill_dax(CFG, own_role="department", own_member="X",
                                              drill_role="store")))

    injected = inv.build_drill_dax(CFG, own_role="department", own_member='X" || TRUE() || "',
                                   drill_role="section")
    check("a double-quote in the member name is doubled (escaped), not left to close "
         "the string literal early",
          'sectionbenchmark[DEPARTMENT] = "X"" || TRUE() || """' in injected, injected)


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def test_normalize_reads_the_right_group_column() -> None:
    print("\n=== _normalize reads the group column matching the drill role ===")
    section_rows = [{"[SECTION]": "SPICE MARKET", "[gap]": -33.0},
                    {"[SECTION]": "PROVISIONS", "[gap]": 6.0}]
    out = inv._normalize(CFG, section_rows, "section")
    check("section rows are named from the SECTION column, sorted by |gap| descending",
          [r["name"] for r in out] == ["SPICE MARKET", "PROVISIONS"], out)

    category_rows = [{"[CATEGORY_NAME_2]": "SNACKS", "[gap]": -746.0}]
    out2 = inv._normalize(CFG, category_rows, "category")
    check("category rows are named from the category column, not the group column",
          out2 == [{"name": "SNACKS", "value": -746.0}], out2)

    print("\n=== a drilled gap is put on the reporting scale before it is shown ===")
    scaled = inv._normalize(CFG, [{"[SECTION]": "PROVISIONS", "[gap]": -21008.9}],
                            "section", 0.27)
    check("a source-scale gap is multiplied by the measured scale",
          abs(scaled[0]["value"] + 5672.4) < 0.1, str(scaled))
    check("the default is 1.0, so a model on one scale is untouched",
          inv._normalize(CFG, [{"[SECTION]": "P", "[gap]": -100.0}], "section")[0]["value"]
          == -100.0)


def test_off_by_default_and_drill_values_are_money() -> None:
    print("\n=== off by default; drill values are money and are printed as money ===")

    def execute(dax: str) -> list[dict]:
        if "SECTION" in dax:
            return [{"[SECTION]": "SPICE MARKET", "[gap]": -746.0}]
        return []

    off = inv.investigate(execute, MODEL, {**CFG}, log=None)
    check("no config key at all -> nothing runs", off["entries"] == [])

    with patch("src.tools.llm.get_llm", side_effect=RuntimeError("no LLM in this offline test")):
        on = inv.investigate(
            execute, MODEL, {**CFG, "daily_sales_investigation_enabled": True,
                             "daily_sales_investigation_max_findings": 1,
                             "daily_sales_investigation_max_rounds": 1,
                             "daily_sales_investigation_max_queries": 20,
                             "daily_sales_investigation_max_roles_per_finding": 20},
            log=None)
    check("one finding investigated with a single forced round", len(on["entries"]) == 1, on)
    entry = on["entries"][0]
    check("the deterministic fallback fires (LLM unavailable in this offline test)",
          entry["authoring_mode"] == "deterministic")
    check("the narrative names the drilled member",
          "SPICE MARKET" in entry["narrative"], entry["narrative"])
    check("a Net Sales gap IS printed with the currency - it is money, unlike the "
         "Bills count this drill used to read",
          "USD" in entry["narrative"], entry["narrative"])


def main() -> int:
    print("=" * 72)
    print("Daily Sales investigation - adaptive drill-down (Net Sales only)")
    print("=" * 72)

    test_candidates_are_net_sales_only_and_hierarchy_aware()
    test_drill_dax_picks_the_right_table_and_scope()
    test_normalize_reads_the_right_group_column()
    test_off_by_default_and_drill_values_are_money()

    print("\n" + "=" * 72)
    if _failures:
        print(f"DAILY SALES INVESTIGATOR FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
