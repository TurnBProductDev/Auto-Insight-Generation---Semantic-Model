"""The eight SKU Overview insight rules (sku-insights-rules.md). Offline.

    python scripts/replay_sku_overview_insights.py

No auth, no LLM, no network. Proves the property that matters most for this
module: every rule scopes to the five shops only, never the two warehouses -
the earlier generic detector scored warehouses as ordinary locations, and on
live data that put them at the top of the "hotspot" list for a report whose
own spec excludes them entirely. Also proves Rule 2 states its own absence
rather than being silently missing, and that the four "action" rules convert
into the same signal shape the memory/KPI-feed machinery already expects.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import sku_overview_insights as ins  # noqa: E402

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


def test_every_rule_scopes_to_shops_only() -> None:
    print("\n=== every rule excludes the two warehouses ===")
    daxes = {
        "rule1": ins.rule1_dax(), "rule3": ins.rule3_dax(), "rule4": ins.rule4_dax(),
        "rule4_count": ins.rule4_count_dax(), "rule5": ins.rule5_dax(),
        "rule6": ins.rule6_dax(), "rule7": ins.rule7_dax(), "rule8": ins.rule8_dax(),
    }
    shops = '{"ST1", "ST2", "ST3", "ST4", "ST5"}'
    for name, dax in daxes.items():
        check(f"{name} filters to the five shops, not the two warehouses",
              shops in dax, dax)
        check(f"{name} never mentions WH1/WH2 as a population filter",
              '"WH1"' not in dax and '"WH2"' not in dax, dax)


def test_rule2_states_its_own_absence() -> None:
    print("\n=== Rule 2 (rank movers) states pending, never guesses ===")
    status = ins.rule2_status()
    check("it is explicitly unavailable", status["available"] is False)
    check("it names the real reason (no snapshot history)",
          "snapshot" in status["reason"].lower(), status["reason"])
    check("it names a concrete next step for the model owner",
          "weekly" in status["action"].lower() or "history" in status["action"].lower(),
          status["action"])


def test_rule3_yesterday_is_a_scalar() -> None:
    print("\n=== Rule 3's 'yesterday' is resolved once, as a scalar ===")
    dax = ins.rule3_dax()
    check("a VAR resolves yesterday from the model's own MAX date",
          "VAR Yesterday = MAX(" in dax, dax)
    check("the filter compares against the resolved scalar, not a raw "
         "cross-table column reference",
          "[doc_date] = Yesterday" in dax, dax)


def test_rule4_distinguishes_blank_from_zero() -> None:
    print("\n=== Rule 4 keeps a blank Opportunity Loss distinct from zero ===")

    def execute(dax: str) -> list[dict]:
        if "COUNTROWS" in dax:
            return [{"[count]": 3, "[opp_loss_total]": 500.0}]
        return [
            {"REP_SSR_STOCK_STATUS_REPORTV3[SKU_CODE]": "A", "REP_SSR_STOCK_STATUS_REPORTV3[PART_DESCRIPTION]": "Item A",
             "REP_SSR_STOCK_STATUS_REPORTV3[CATEGORY_NAME]": "Cat", "REP_SSR_STOCK_STATUS_REPORTV3[LOC_CODE]": "ST1",
             "[sales_3m]": 1000.0, "[opp_loss]": 500.0},
            {"REP_SSR_STOCK_STATUS_REPORTV3[SKU_CODE]": "B", "REP_SSR_STOCK_STATUS_REPORTV3[PART_DESCRIPTION]": "Item B",
             "REP_SSR_STOCK_STATUS_REPORTV3[CATEGORY_NAME]": "Cat", "REP_SSR_STOCK_STATUS_REPORTV3[LOC_CODE]": "ST2",
             "[sales_3m]": 900.0, "[opp_loss]": None},
        ]

    result = ins.rule4_run(execute, top_n=10)
    by_sku = {r["sku_code"]: r for r in result["top"]}
    check("a real opportunity-loss estimate is kept as a number",
          by_sku["A"]["opp_loss"] == 500.0)
    check("a blank estimate stays None, never coerced to 0.0 - the model did "
         "not estimate one, which is a different fact from 'zero loss'",
          by_sku["B"]["opp_loss"] is None, by_sku["B"]["opp_loss"])


def test_seg_a_only_scopes_the_best_sellers_view() -> None:
    print("\n=== seg_a_only adds the Segment A filter, for the 'Best sellers "
         "only' view - every figure recomputed, not sliced ===")
    seg_filter = 'SKUSEGMENT] = "SEG_A"'

    unscoped = {
        "rule1": ins.rule1_dax(), "rule3": ins.rule3_dax(), "rule5": ins.rule5_dax(),
        "rule6": ins.rule6_dax(), "rule7": ins.rule7_dax(), "rule8": ins.rule8_dax(),
    }
    for name, dax in unscoped.items():
        check(f"{name} carries no Segment A filter by default", seg_filter not in dax, dax)

    scoped = {
        "rule1": ins.rule1_dax(seg_a_only=True), "rule3": ins.rule3_dax(seg_a_only=True),
        "rule5": ins.rule5_dax(seg_a_only=True), "rule6": ins.rule6_dax(seg_a_only=True),
        "rule7": ins.rule7_dax(seg_a_only=True), "rule8": ins.rule8_dax(seg_a_only=True),
    }
    shops = '{"ST1", "ST2", "ST3", "ST4", "ST5"}'
    for name, dax in scoped.items():
        check(f"{name}(seg_a_only=True) carries the Segment A filter", seg_filter in dax, dax)
        check(f"{name}(seg_a_only=True) still scopes to the five shops", shops in dax, dax)
        check(f"{name}(seg_a_only=True) still excludes the warehouses",
              '"WH1"' not in dax and '"WH2"' not in dax, dax)

    # Rule 3 reads a side table with no SKUSEGMENT column of its own, so the
    # scope has to arrive via a TREATAS join back to the fact table rather
    # than a bare column filter - confirm the join is actually present.
    check("rule3's Segment A scope joins back to the fact table via TREATAS",
          "TREATAS" in scoped["rule3"], scoped["rule3"])

    # Rule 4 is already Segment-A scoped by definition (that is the rule
    # itself), so it must not gain a second, redundant filter, and it takes
    # no seg_a_only parameter at all.
    check("rule4 has no seg_a_only parameter - it is already Segment A by definition",
          "seg_a_only" not in ins.rule4_dax.__code__.co_varnames)

    def execute(dax: str) -> list[dict]:
        return []

    result = ins.run_all(execute, {}, seg_a_only=True, log=None)
    check("run_all(seg_a_only=True) records which scope it ran under",
          result.get("seg_a_only") is True)
    check("run_all(seg_a_only=True) still returns every rule's key",
          set(result["rules"]) == {"top_performers", "rank_movers", "best_day_yesterday",
                                   "segment_a_stockouts", "verge_stockout_in_warehouse",
                                   "non_moving_pending_order", "overstock_pending_order",
                                   "at_price_floor"},
          set(result["rules"]))


def test_department_shop_detail_scopes_with_seg_a_only() -> None:
    print("\n=== department_shop_detail(seg_a_only=True) recomputes, "
         "never slices ===")
    seg_filter = 'SKUSEGMENT] = "SEG_A"'
    check("department rollup carries the Segment A filter when asked",
          seg_filter in ins.department_rollup_dax(seg_a_only=True))
    check("department rollup carries no filter by default",
          seg_filter not in ins.department_rollup_dax())
    check("shop rollup carries the Segment A filter when asked",
          seg_filter in ins.shop_rollup_dax(seg_a_only=True))
    check("state table carries the Segment A filter when asked",
          seg_filter in ins.state_table_dax(seg_a_only=True))
    check("the warehouse reference query takes no scope - warehouses are a "
         "fixed reference regardless of view",
          "seg_a_only" not in ins.warehouse_reference_dax.__code__.co_varnames)

    calls: list[str] = []

    def execute(dax: str) -> list[dict]:
        calls.append(dax)
        if "DEPARTMENT" in dax and "products" in dax:
            return [{"[DEPARTMENT]": "D1", "[products]": 5, "[lines]": 10,
                     "[sales_1m]": 1.0, "[sales_3m]": 3.0, "[stock_value]": 4.0,
                     "[excess_value]": 0.5}]
        if "LOC_CODE" in dax and "products" in dax:
            return [{"[LOC_CODE]": "ST1", "[products]": 5, "[sales_1m]": 1.0,
                     "[sales_3m]": 3.0, "[stock_value]": 4.0, "[excess_value]": 0.5}]
        if "WH1" in dax:
            return [{"[LOC_CODE]": "WH1", "[lines]": 2, "[stock_value]": 9.0}]
        if "RECOMMENDED_ACTION" in dax:
            return [{"[RECOMMENDED_ACTION]": "STOCK AVAILABLE", "[rows]": 3,
                     "[sales_3m]": 3.0, "[stock_value]": 4.0}]
        raise AssertionError(f"unexpected query: {dax[:120]}")

    detail = ins.department_shop_detail(execute, seg_a_only=True)
    check("every one of the four scoped queries carried the Segment A filter",
          all(seg_filter in c for c in calls if "WH1" not in c), calls)
    check("the warehouse reference query is unscoped even inside a Segment A pass",
          any("WH1" in c and seg_filter not in c for c in calls), calls)
    check("the shaped result carries all four sections",
          {"departments", "shops", "warehouses", "states", "quiet_shop"} <= set(detail))


def test_to_signals_shape_matches_the_existing_contract() -> None:
    print("\n=== the four action rules produce signals the existing "
         "memory/KPI-feed machinery already understands ===")
    insights = {
        "rules": {
            "segment_a_stockouts": {"count": 2439, "opp_loss_total": 25872.17, "top": []},
            "verge_stockout_in_warehouse": [{"sales_3m": 100.0}, {"sales_3m": 200.0}],
            "non_moving_pending_order": [{"pending_value": 50.0}],
            "overstock_pending_order": [{"excess_value": 300.0}],
        },
        "errors": {},
    }
    model = {"as_at": "2026-08-23", "header": {"rows": 139200}}
    signals = ins.to_signals(insights, model)

    check("all four action rules produced a signal", len(signals) == 4, signals)
    required = {"candidate_id", "story_key", "report_id", "analysis_type", "dimension",
               "affected_segment", "impact_value", "score", "severity", "comparison_label",
               "description", "id"}
    check("every signal carries the full contract the KPI-card assembler reads",
          all(required <= set(s) for s in signals),
          [sorted(set(s) - required) for s in signals if not required <= set(s)])
    check("the urgent stockout finding leads (highest score)",
          signals[0]["analysis_type"] == "sku_overview_segment_a_stockout", signals[0])
    check("story_keys are stable across an identical re-run",
          [s["story_key"] for s in ins.to_signals(insights, model)]
          == [s["story_key"] for s in signals])

    empty_signals = ins.to_signals({"rules": {}, "errors": {}}, model)
    check("no findings when no rule fired - never padded to a non-empty list",
          empty_signals == [])


def test_one_broken_rule_does_not_cost_the_others() -> None:
    print("\n=== run_all: one bad rule is skipped, not fatal ===")
    calls = {"n": 0}

    def flaky_execute(dax: str) -> list[dict]:
        calls["n"] += 1
        if "OVERSTOCK" in dax:
            raise RuntimeError("simulated Power BI error")
        return []

    result = ins.run_all(flaky_execute, {}, log=None)
    check("the broken rule is recorded as an error, not raised",
          "overstock_pending_order" in result["errors"], result["errors"])
    check("every other rule still ran and returned a result",
          "top_performers" in result["rules"] and "segment_a_stockouts" in result["rules"])
    check("rule2 needs no query and is always present",
          result["rules"]["rank_movers"]["available"] is False)


def main() -> int:
    print("=" * 72)
    print("SKU Overview insight rules (sku-insights-rules.md)")
    print("=" * 72)

    test_every_rule_scopes_to_shops_only()
    test_rule2_states_its_own_absence()
    test_rule3_yesterday_is_a_scalar()
    test_rule4_distinguishes_blank_from_zero()
    test_seg_a_only_scopes_the_best_sellers_view()
    test_department_shop_detail_scopes_with_seg_a_only()
    test_to_signals_shape_matches_the_existing_contract()
    test_one_broken_rule_does_not_cost_the_others()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SKU OVERVIEW INSIGHTS FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
