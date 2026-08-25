""""One product in full" - SKU Overview's per-SKU spotlight. Offline.

    python scripts/replay_sku_overview_product.py

No auth, no LLM, no network. Proves: the subject SKU is chosen in the
rulebook's own action-priority order (never arbitrary), every query stays
scoped to the five shops, a SKU/category value containing a double quote is
escaped rather than breaking the DAX string, a blank Opportunity Loss or
burnout reading stays None rather than being coerced to zero, and a
genuinely quiet day (no action rule fired) yields no fabricated subject.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import sku_overview_dashboard as dash  # noqa: E402
from src.domains.inventory import sku_overview_product as prod  # noqa: E402

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


def test_selection_priority() -> None:
    print("\n=== subject selection follows the rulebook's own action priority ===")

    stockout_row = {"sku_code": "S1", "description": "Stockout SKU", "category": "CAT A",
                    "location": "ST1"}
    verge_row = {"sku_code": "S2", "description": "Verge SKU", "category": "CAT B", "location": "ST2"}
    overstock_row = {"sku_code": "S3", "description": "Overstock SKU", "category": "CAT C",
                     "location": "ST3"}
    non_moving_row = {"sku_code": "S4", "description": "Non-moving SKU", "category": "CAT D",
                      "location": "ST4"}

    everything = {"rules": {
        "segment_a_stockouts": {"count": 1, "top": [stockout_row]},
        "verge_stockout_in_warehouse": [verge_row],
        "overstock_pending_order": [overstock_row],
        "non_moving_pending_order": [non_moving_row],
    }}
    check("stockouts win when present", prod.select_product(everything)["sku_code"] == "S1")

    no_stockout = {"rules": {
        "segment_a_stockouts": {"count": 0, "top": []},
        "verge_stockout_in_warehouse": [verge_row],
        "overstock_pending_order": [overstock_row],
        "non_moving_pending_order": [non_moving_row],
    }}
    check("verge is next", prod.select_product(no_stockout)["sku_code"] == "S2")

    only_overstock_and_non_moving = {"rules": {
        "segment_a_stockouts": {"count": 0, "top": []},
        "verge_stockout_in_warehouse": [],
        "overstock_pending_order": [overstock_row],
        "non_moving_pending_order": [non_moving_row],
    }}
    check("overstock is next", prod.select_product(only_overstock_and_non_moving)["sku_code"] == "S3")

    only_non_moving = {"rules": {
        "segment_a_stockouts": {"count": 0, "top": []},
        "verge_stockout_in_warehouse": [],
        "overstock_pending_order": [],
        "non_moving_pending_order": [non_moving_row],
    }}
    check("non-moving is last", prod.select_product(only_non_moving)["sku_code"] == "S4")

    quiet = {"rules": {
        "segment_a_stockouts": {"count": 0, "top": []},
        "verge_stockout_in_warehouse": [], "overstock_pending_order": [],
        "non_moving_pending_order": [],
    }}
    check("a genuinely quiet day yields no subject", prod.select_product(quiet) is None)
    check("a missing insights dict yields no subject", prod.select_product(None) is None)


def test_queries_scope_to_shops_only() -> None:
    print("\n=== every query scopes to the five shops, never the two warehouses ===")
    shops = '{"ST1", "ST2", "ST3", "ST4", "ST5"}'
    daxes = {
        "status": prod.status_dax("S1"),
        "weekly": prod.weekly_dax("S1"),
        "price": prod.price_dax("S1"),
        "price_range": prod.price_range_dax("S1"),
        "category": prod.category_dax("CAT A"),
    }
    for name, dax in daxes.items():
        check(f"{name} filters to the five shops", shops in dax, dax)
        check(f"{name} never mentions WH1/WH2", '"WH1"' not in dax and '"WH2"' not in dax, dax)


def test_sku_value_is_escaped() -> None:
    print("\n=== a SKU or category holding a double quote is escaped, not broken ===")
    dax = prod.status_dax('S"1')
    check("the embedded quote is doubled, not left to break the string literal",
          '"S""1"' in dax, dax)
    cat_dax = prod.category_dax('Cat "Special"')
    check("category values are escaped the same way",
          '"Cat ""Special"""' in cat_dax, cat_dax)


def test_status_run_keeps_blank_distinct_from_zero() -> None:
    print("\n=== a blank Opportunity Loss / burnout stays None, never coerced to zero ===")

    def execute(dax: str) -> list[dict]:
        return [
            {"[LOC_CODE]": "ST1", "[RECOMMENDED_ACTION]": "STOCK AVAILABLE",
             "[current_stock]": 5, "[stock_value]": 10.0, "[sales_1m]": 1.0, "[sales_3m]": 3.0,
             "[opp_loss]": None, "[pending_qty]": 0, "[pending_value]": 0.0,
             "[excess_value]": 0.0, "[burnout]": None, "[days_no_sale]": 2},
            {"[LOC_CODE]": "ST2", "[RECOMMENDED_ACTION]": "STOCK OUT - PLACE ORDER",
             "[current_stock]": 0, "[stock_value]": 0.0, "[sales_1m]": 5.0, "[sales_3m]": 15.0,
             "[opp_loss]": 42.5, "[pending_qty]": 0, "[pending_value]": 0.0,
             "[excess_value]": 0.0, "[burnout]": 0.0, "[days_no_sale]": 7},
        ]

    rows = prod.status_run(execute, "S1")
    st1 = next(r for r in rows if r["location"] == "ST1")
    st2 = next(r for r in rows if r["location"] == "ST2")
    check("a blank opp_loss stays None", st1["opp_loss"] is None)
    check("a blank burnout stays None", st1["burnout"] is None)
    check("a real opp_loss is kept as a number", st2["opp_loss"] == 42.5)
    check("a genuine zero burnout is kept as 0.0, not confused with blank",
          st2["burnout"] == 0.0 and st2["burnout"] is not None)


def test_weekly_run_sorts_chronologically() -> None:
    print("\n=== weekly rows are returned oldest-first for a left-to-right trend chart ===")

    def execute(dax: str) -> list[dict]:
        # DAX asks for DESC (most recent first); the fake executor mirrors that,
        # proving weekly_run does the re-sort rather than relying on query order.
        return [
            {"[week_start_date]": "2026-08-10", "[week_end_date]": "2026-08-16", "[qty]": 50},
            {"[week_start_date]": "2026-08-03", "[week_end_date]": "2026-08-09", "[qty]": 80},
            {"[week_start_date]": "2026-07-27", "[week_end_date]": "2026-08-02", "[qty]": 40},
        ]

    rows = prod.weekly_run(execute, "S1", weeks=3)
    check("rows come back oldest week first",
          [r["week_start"] for r in rows] == ["2026-07-27", "2026-08-03", "2026-08-10"], rows)


def test_build_returns_none_on_a_quiet_day() -> None:
    print("\n=== build() never fabricates a subject on a quiet day ===")

    def execute(dax: str) -> list[dict]:
        raise AssertionError("no query should run when there is no subject to feature")

    result = prod.build(execute, {"rules": {}}, log=None)
    check("no subject means no page data at all", result is None)


def test_build_end_to_end_with_a_fake_executor() -> None:
    print("\n=== build() assembles status + weekly + price + category from one subject ===")
    insights = {"rules": {"segment_a_stockouts": {"count": 1, "top": [
        {"sku_code": "S1", "description": "Widget", "category": "WIDGETS", "location": "ST1"}]}}}

    def execute(dax: str) -> list[dict]:
        if "week_start_date" in dax and "week_end_date" in dax and "SUMMARIZECOLUMNS" in dax:
            return [{"[week_start_date]": "2026-08-10", "[week_end_date]": "2026-08-16", "[qty]": 12}]
        if "RECOMMENDED_ACTION" in dax and "LOC_CODE" in dax and "CALCULATETABLE" in dax:
            return [
                {"[LOC_CODE]": "ST1", "[RECOMMENDED_ACTION]": "STOCK AVAILABLE",
                 "[current_stock]": 4, "[stock_value]": 40.0, "[sales_1m]": 5.0, "[sales_3m]": 15.0,
                 "[opp_loss]": None, "[pending_qty]": 0, "[pending_value]": 0.0,
                 "[excess_value]": 0.0, "[burnout]": 6.0, "[days_no_sale]": 1},
                {"[LOC_CODE]": "ST2", "[RECOMMENDED_ACTION]": "STOCK OUT - PLACE ORDER",
                 "[current_stock]": 0, "[stock_value]": 0.0, "[sales_1m]": 2.0, "[sales_3m]": 6.0,
                 "[opp_loss]": 9.0, "[pending_qty]": 0, "[pending_value]": 0.0,
                 "[excess_value]": 0.0, "[burnout]": None, "[days_no_sale]": 3},
            ]
        if "min_rp" in dax and "max_rp" in dax and "ROW" in dax:
            return [{"[min_rp]": 8.0, "[max_rp]": 12.0}]
        if "RP" in dax and "CALCULATETABLE" in dax:
            return [{"[LOC_CODE]": "ST1", "[rp]": 9.5}]
        if "cat_skus" in dax:
            return [{"[cat_skus]": 10, "[cat_sales_3m]": 210.0, "[cat_stock_value]": 400.0,
                     "[cat_excess_value]": 20.0}]
        raise AssertionError(f"unexpected query: {dax[:120]}")

    result = prod.build(execute, insights, weeks=4, log=None)
    check("a subject was selected", result is not None and result["subject"]["sku_code"] == "S1")
    check("stock value totals across both shops", result["totals"]["stock_value"] == 40.0)
    check("sales_3m totals across both shops", result["totals"]["sales_3m"] == 21.0)
    check("opp_loss totals only the non-blank readings", result["totals"]["opp_loss"] == 9.0)
    check("shops_with_stock/out are counted correctly",
          result["totals"]["shops_with_stock"] == 1 and result["totals"]["shops_out"] == 1)

    page = dash._product_section(result)
    check("the dashboard section carries a share-of-category figure",
          page["share_of_category_pct"] is not None
          and abs(page["share_of_category_pct"] - (21.0 / 210.0 * 100.0)) < 1e-9)
    check("the dashboard section carries a vs-category-average figure",
          page["vs_category_avg_pct"] is not None)
    check("status rows carry a plain-language label", all("label" in s for s in page["status"]))


def test_dashboard_build_handles_a_missing_top_view() -> None:
    print("\n=== sku_overview_dashboard.build() tolerates no Segment-A rescan ===")
    model = {"report_name": "SKU Overview", "as_at": "2026-08-23", "period_label": "as at 2026-08-23",
             "currency": "USD", "header": {"total_opp_loss": 0.0, "skus": 1, "rows": 1, "locations": 1,
                                           "total_stock_value": 1.0, "total_excess_value": 0.0},
             "states": []}
    page = dash.build(model, None)
    check("no live insights means the layer says so, not silently empty",
          page["rules_available"] is False)
    check("no Segment-A rescan means no top view at all",
          page["views"]["top"] is None)
    check("the all view is still built",
          page["views"]["all"]["hero"]["headline"] != "")
    check("no product means the product section is absent",
          page["product"] is None)


def main() -> int:
    print("=" * 72)
    print("SKU Overview - one product in full")
    print("=" * 72)

    test_selection_priority()
    test_queries_scope_to_shops_only()
    test_sku_value_is_escaped()
    test_status_run_keeps_blank_distinct_from_zero()
    test_weekly_run_sorts_chronologically()
    test_build_returns_none_on_a_quiet_day()
    test_build_end_to_end_with_a_fake_executor()
    test_dashboard_build_handles_a_missing_top_view()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SKU OVERVIEW PRODUCT FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
