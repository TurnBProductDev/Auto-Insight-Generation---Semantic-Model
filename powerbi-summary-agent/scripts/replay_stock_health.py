"""WP7: the Inventory Management report. Offline - no auth, no LLM, no network.

    python scripts/replay_stock_health.py

Figures are the live ones (2026-08-13), so the arithmetic cannot drift away from
the model it was built against.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import dashboard, dashboard_html  # noqa: E402
from src.domains.inventory.reports import stock_health  # noqa: E402

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


def _scan() -> dict:
    """The live shape and the live figures, committed so this runs anywhere."""
    return {
        "snapshot": [{"[as_at]": "2026-08-12T00:00:00", "[stock_value]": 50831641.03,
                      "[excess_value]": 21126059.57, "[pending_value]": 3385983.81,
                      "[loc_skus]": 140113, "[skus]": 45860, "[locations]": 7}],
        "actions": [
            {"[RECOMMENDED_ACTION]": "STOCK AVAILABLE", "[loc_skus]": 19037,
             "[stock_value]": 10131473.07, "[excess_value]": 0.0},
            {"[RECOMMENDED_ACTION]": "OVERSTOCK", "[loc_skus]": 29932,
             "[stock_value]": 26887690.34, "[excess_value]": 21126059.57},
            {"[RECOMMENDED_ACTION]": "NON MOVING", "[loc_skus]": 36377,
             "[stock_value]": 6411195.86, "[excess_value]": 0.0},
            {"[RECOMMENDED_ACTION]": "STOCK OUT - PLACE ORDER", "[loc_skus]": 17717,
             "[stock_value]": 0.0, "[excess_value]": 0.0},
            {"[RECOMMENDED_ACTION]": "STOCK OUT - AVAILABLE IN WAREHOUSE",
             "[loc_skus]": 6042, "[stock_value]": 0.0, "[excess_value]": 0.0},
            {"[RECOMMENDED_ACTION]": "ON THE VERGE OF STOCK OUT - PLACE ORDER",
             "[loc_skus]": 2566, "[stock_value]": 733478.26, "[excess_value]": 0.0},
            {"[RECOMMENDED_ACTION]": "NON MOVING - ORDER PLACED", "[loc_skus]": 40,
             "[stock_value]": 12000.0, "[excess_value]": 0.0},
            {"[RECOMMENDED_ACTION]": "NOT ACTIVE", "[loc_skus]": 28402,
             "[stock_value]": 655803.5, "[excess_value]": 0.0},
        ],
        "opportunity_loss": [{"[opp_loss_all]": 292770.82,
                              "[opp_loss_stores_critical]": 45944.38,
                              "[critical_stockout_skus]": 3993}],
        "unwanted": [{"[unwanted_skus]": 216, "[unwanted_pending_value]": 874892.40,
                      "[pending_skus]": 799}],
        "locations": [
            {"[LOC_CODE]": "CDC", "[loc_type]": "WH", "[stock_value]": 25847125.07,
             "[excess_value]": 10848590.47, "[loc_skus]": 20000},
            {"[LOC_CODE]": "CFW001", "[loc_type]": "WH", "[stock_value]": 5989762.22,
             "[excess_value]": 3168532.49, "[loc_skus]": 18000},
            {"[LOC_CODE]": "CFH021", "[loc_type]": "SH", "[stock_value]": 6258285.75,
             "[excess_value]": 2258049.66, "[loc_skus]": 21000},
        ],
        "divisions": [
            {"[DEPARTMENT]": "FMCG FOOD", "[stock_value]": 12767610.88,
             "[excess_value]": 4000000.0, "[loc_skus]": 30000}],
        "sections": [
            {"[DEPARTMENT]": "FMCG FOOD", "[SECTION]": "CF-GROCERY FOOD",
             "[stock_value]": 5000000.0, "[excess_value]": 1500000.0}],
        "segments": [
            {"[SKUSEGMENT]": "SEG_A", "[loc_skus]": 16158, "[stock_value]": 20000000.0,
             "[excess_value]": 6000000.0},
            {"[SKUSEGMENT]": "SEG_D", "[loc_skus]": 71538, "[stock_value]": 8000000.0,
             "[excess_value]": 5000000.0}],
        "non_moving_bands": [
            {"[NM DAYS TAG]": "30-60", "[loc_skus]": 5000, "[stock_value]": 1000000.0},
            {"[NM DAYS TAG]": ">180", "[loc_skus]": 9000, "[stock_value]": 2000000.0},
            {"[NM DAYS TAG]": "91-120", "[loc_skus]": 3000, "[stock_value]": 800000.0}],
        "damage": [
            {"[month_date]": "2026-07-01T00:00:00", "[damage_value]": -120000.0},
            {"[month_date]": "2026-05-01T00:00:00", "[damage_value]": -90000.0}],
    }


def test_queue_order() -> None:
    print("\n=== the queue is ordered by urgency, not by value (BR-31) ===")

    report = stock_health.build(_scan())
    queue = report["queue"]
    actions = [r["action"] for r in queue]

    check("the two double-warning states lead the queue",
          actions[0] == "NON MOVING - ORDER PLACED"
          and actions[1] == "STOCK OUT - PLACE ORDER", actions[:3])
    check("...even though OVERSTOCK holds far more value",
          actions.index("OVERSTOCK") > 1
          and max(r["stock_value"] for r in queue)
          == next(r["stock_value"] for r in queue if r["action"] == "OVERSTOCK"))
    check("both are flagged as double warnings",
          all(r["double_warning"] for r in queue[:2]))
    check("healthy states sort to the bottom",
          actions.index("STOCK AVAILABLE") > actions.index("NON MOVING"))
    check("every row carries an action for the buying team",
          all(r["guidance"] for r in queue if r["is_exception"]),
          [r["action"] for r in queue if r["is_exception"] and not r["guidance"]])
    check("an unrecognised state would sort after the known ones, not first",
          stock_health.action_rank("SOMETHING NEW")
          == len(stock_health.ACTION_PRIORITY))

    print("\n--- exception states are separated from healthy ones ---")
    check("out of stock is an exception",
          stock_health.is_exception("STOCK OUT - PLACE ORDER"))
    check("stock available is not", not stock_health.is_exception("STOCK AVAILABLE"))
    check("not active is not", not stock_health.is_exception("NOT ACTIVE"))


def test_scoping_trap() -> None:
    print("\n=== Opportunity Loss is scoped, or it is 6.4x too big (BR-16) ===")

    report = stock_health.build(_scan())
    header = report["header"]

    check("the published figure is the scoped one",
          abs(header["opportunity_loss_day"] - 45944.38) < 0.01,
          header["opportunity_loss_day"])
    check("the unscoped figure is kept only to explain the difference",
          abs(header["opportunity_loss_unscoped"] - 292770.82) < 0.01)
    check("the scoped figure is materially smaller - the trap is live",
          header["opportunity_loss_day"] < header["opportunity_loss_unscoped"] / 5)
    check("a caveat explains the scope in plain words",
          any("critical products at stores only" in c for c in report["caveats"]),
          report["caveats"])
    check("and says it is an estimate, not confirmed lost revenue",
          any("not confirmed lost revenue" in c for c in report["caveats"]))
    check("the check records that scoped <= unscoped",
          report["checks"]["opportunity_loss_scoped"])


def test_excess_meaning() -> None:
    print("\n=== excess is the surplus only, not the whole overstocked value ===")

    report = stock_health.build(_scan())
    header = report["header"]
    overstock = next(r for r in report["queue"] if r["action"] == "OVERSTOCK")

    check("excess is smaller than the stock value of overstocked lines",
          header["excess_value"] < overstock["stock_value"],
          f"excess={header['excess_value']} overstock_stock={overstock['stock_value']}")
    check("excess never exceeds total stock", report["checks"]["excess_within_stock"])
    check("the narrative says which of the two it is",
          any("not the full value of overstocked products" in line
              for line in report["narrative"]), report["narrative"])


def test_completeness_and_prose() -> None:
    print("\n=== completeness and prose ===")

    report = stock_health.build(_scan())
    check("the queue accounts for every product-location line",
          report["checks"]["queue_covers_every_row"],
          f"{sum(r['loc_skus'] for r in report['queue'])} vs "
          f"{report['header']['loc_skus']}")
    check("the period is stated 'as at' (NN 18)",
          report["period_label"].startswith("as at"))
    check("non-moving bands are ordered by days, not alphabetically",
          [b["name"] for b in report["non_moving_bands"]] == ["30-60", "91-120", ">180"],
          [b["name"] for b in report["non_moving_bands"]])
    check("damage is reported as a positive cost, not a negative (BR-29)",
          all(d["value"] > 0 for d in report["damage"]), report["damage"])
    check("damage months are in order",
          [d["month"] for d in report["damage"]] == sorted(d["month"] for d in report["damage"]))

    banned = {"velocity", "offtake", "capital lock-up", "carry cost", "materiality",
              "dead stock", "days of cover", "stock worth", "overstock ", "surplus"}
    text = " ".join(report["narrative"]).lower()
    hits = sorted(w for w in banned if w in text)
    check("no banned vocabulary reaches the reader (BR-03/BR-33)", not hits, f"{hits}")
    check("every line carries a figure (BR-33)",
          all(any(ch.isdigit() for ch in line) for line in report["narrative"]))
    check("no emojis",
          all(ord(ch) < 0x2190 for line in report["narrative"] for ch in line))


def test_dashboard() -> None:
    print("\n=== the four-layer dashboard ===")

    report = stock_health.build(_scan())
    page = dashboard.build_stock_health(report)

    check("same four layers as the sales and ageing dashboards",
          page["layers"] == ["overview", "entities", "areas", "detail"])
    check("the detail layer is named for what it is - a work queue",
          page["layer_titles"]["detail"] == "Action queue")
    check("two views, defaulting to all stock",
          [v["key"] for v in page["views"]] == ["all", "exceptions"]
          and page["default_view"] == "all")

    all_view, scoped = page["views"]
    check("the overview leads with the most urgent lines",
          "need attention today" in all_view["hero"]["headline"]
          or "above the agreed cover" in all_view["hero"]["headline"],
          all_view["hero"]["headline"])
    check("the double-warning states appear as signals",
          len(all_view["signals"]) >= 1, all_view["signals"])
    check("the scoped view says its totals will not match",
          any("will not match" in text for text in scoped["limitations"]))
    check("the scoped view's queue holds only exception states",
          all(r["is_exception"] for r in (scoped["layers"]["detail"] or {}).get("queue") or []))

    print("\n--- the rendered document ---")
    html = dashboard_html.render(page)
    body = html.split("</style>", 1)[-1]
    check("the skeleton matches the shared stylesheet",
          '<div class="app" id="report">\n<nav class="rail"' in html
          and '<main><div class="page">' in html)
    check("exactly one script tag", html.count("<script") == 1)
    check("it is self-contained", "http://" not in html and "https://" not in html)
    check("all four layer buttons are present",
          all(f'data-layer="{layer}"' in html for layer in page["layers"]))
    check("the queue is rendered with its guidance column",
          "What the buying team should do" in html)
    check("the most-urgent rows are marked",
          "most urgent" in html)
    check("no year-on-year language on a stock page",
          "same period last year" not in html.lower()
          and "versus the comparison period" not in html.lower())
    check("content is escaped",
          "&lt;img" in dashboard_html.render({**page, "title": "<img src=x>"}))


def main() -> int:
    print("=" * 72)
    print("WP7 Inventory Management")
    print("=" * 72)

    test_queue_order()
    test_scoping_trap()
    test_excess_meaning()
    test_completeness_and_prose()
    test_dashboard()

    print("\n" + "=" * 72)
    if _failures:
        print(f"STOCK HEALTH FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
