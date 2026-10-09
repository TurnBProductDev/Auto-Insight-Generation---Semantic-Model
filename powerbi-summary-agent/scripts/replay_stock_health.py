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
        # The model's own kept Stock Value readings, by date AND location. The
        # live shape: four dates, and one location that has emptied out. CFH021
        # here plays the part ST5 plays on the live model - it holds nothing at
        # the latest reading, so the position queries return no row for it and
        # it appears in no other part of the page.
        "trend": [
            {"[dates]": "2026-06-01T00:00:00", "[loc_code]": "CDC",
             "[stock]": 24000000.0},
            {"[dates]": "2026-06-01T00:00:00", "[loc_code]": "CFW001",
             "[stock]": 5500000.0},
            {"[dates]": "2026-06-01T00:00:00", "[loc_code]": "CFH021",
             "[stock]": 6100000.0},
            {"[dates]": "2026-07-01T00:00:00", "[loc_code]": "CDC",
             "[stock]": 25000000.0},
            {"[dates]": "2026-07-01T00:00:00", "[loc_code]": "CFW001",
             "[stock]": 5800000.0},
            {"[dates]": "2026-07-01T00:00:00", "[loc_code]": "CFH021",
             "[stock]": 2000000.0},
            {"[dates]": "2026-08-01T00:00:00", "[loc_code]": "CDC",
             "[stock]": 25500000.0},
            {"[dates]": "2026-08-01T00:00:00", "[loc_code]": "CFW001",
             "[stock]": 5900000.0},
            {"[dates]": "2026-08-01T00:00:00", "[loc_code]": "CFH021",
             "[stock]": 400000.0},
            {"[dates]": "2026-08-12T00:00:00", "[loc_code]": "CDC",
             "[stock]": 25847125.07},
            {"[dates]": "2026-08-12T00:00:00", "[loc_code]": "CFW001",
             "[stock]": 5989762.22},
            {"[dates]": "2026-08-12T00:00:00", "[loc_code]": "CFH021",
             "[stock]": 120000.0},
            {"[dates]": "2026-06-01T00:00:00", "[loc_code]": "CFH005",
             "[stock]": 6000000.0},
            {"[dates]": "2026-07-01T00:00:00", "[loc_code]": "CFH005",
             "[stock]": 6150000.0},
            {"[dates]": "2026-08-01T00:00:00", "[loc_code]": "CFH005",
             "[stock]": 6200000.0},
            {"[dates]": "2026-08-12T00:00:00", "[loc_code]": "CFH005",
             "[stock]": 6258285.75},
        ],
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

    # A model with no Inventory Health Score drops the two score layers rather
    # than rendering them empty - the other environment's Inventory Management
    # model has no `_HEALTH SCORE MEASURES` table at all.
    check("a model with no health score keeps the original four layers",
          page["layers"] == ["overview", "entities", "areas", "detail"])
    check("the queue layer carries BR-31's own name",
          page["layer_titles"]["detail"] == "Recommended Actions")
    overview = page["views"][0]["layers"]["overview"]
    check("the summary shows the top of the queue, not all of it",
          len(overview["queue"]) == min(dashboard.SUMMARY_QUEUE_ROWS,
                                        overview["queue_total"])
          and len(overview["queue"]) < overview["queue_total"],
          f"{len(overview['queue'])} of {overview['queue_total']}")
    check("and the full queue is still reachable in its own layer",
          len(page["views"][0]["layers"]["detail"]["queue"]) == overview["queue_total"])
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
    # An unrecognised view or layer in the URL must leave the page alone, never
    # blank it. Validating after hiding every view is what produced a blank
    # page from a stale link (`#needs/entities` against views keyed `all` and
    # `exceptions`).
    # Scoped to the routing function itself - the shared script has its own
    # `.view` query, and comparing against that measures nothing.
    show_fn = html.split("function show(view,layer){", 1)[-1].split("}", 1)[0]         if "function show(view,layer){" in html else ""
    show_body = html.split("function show(view,layer){", 1)[-1][:900]
    del show_fn
    check("routing validates the target before hiding anything",
          "function show(view,layer){" in html
          and show_body.index("if(!scope) return;")
          < show_body.index("for(var i=0;i<views.length"),
          "an unknown view must not blank the page")
    check("the view keys the routing serves are the ones the page emits",
          all(f'data-view="{key}"' in html
              for key in (v["key"] for v in page["views"])),
          [v["key"] for v in page["views"]])

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

    # The defect this pins: both inventory reports render through one module,
    # and its section headings and column labels were written for Stock Age
    # Analysis only. This page therefore carried a column headed "Aged stock"
    # above values that are stock held ABOVE AGREED COVER - labelling FMCG
    # FOOD's SAR 5.74M of excess as aged stock when its true aged figure was
    # SAR 0.92M, a ~6x misstatement from a label alone. Inventory Management
    # has no concept of stock age at all, so ANY ageing vocabulary here is
    # wrong. Asserting the right words are present (which the checks above do)
    # cannot catch a right word attached to the wrong number.
    ageing_words = ("aged stock", "aged share", "age band", "months old",
                    "high-risk stock", "not aged")
    leaked = sorted(w for w in ageing_words if w in html.lower())
    check("no stock-ageing vocabulary reaches the Inventory Management page",
          not leaked, f"leaked: {leaked}")

    check("the division column is labelled by what it measures",
          "Above cover" in html and "Aged stock" not in html)

    # `_signal_cards` is imported from the sales renderer and reads
    # signal["value"]. These views built signal["value_display"], so every
    # signal card rendered with a label, a note, and an EMPTY number - the
    # double-warning card said "Stock Out - Place Order" with no 17,717 beside
    # it. The keys are a seam between two modules, so pin the seam.
    signals = [s for v in page["views"] for s in (v.get("signals") or [])]
    check("every signal carries the key the renderer reads",
          bool(signals) and all(s.get("value") for s in signals),
          f"missing 'value': {[s.get('label') for s in signals if not s.get('value')]}")
    check("a signal's number reaches the page", "17,717 lines" in html)

    print("\n--- the charts ---")
    import re
    import xml.etree.ElementTree as ET

    svgs = re.findall(r"<svg.*?</svg>", html, re.S)
    # Counted in the ALL-STOCK view, not across the page. The scoped view used
    # to carry the estate-wide section, segment, non-moving and damage blocks -
    # rows that do not add to its own totals - so a whole-page count rewarded
    # exactly the leak the pointer contract exists to stop.
    _all = html.split('<section class="view" data-view="exceptions"', 1)[0]
    all_svgs = re.findall(r"<svg.*?</svg>", _all, re.S)
    check("the all-stock view draws charts, not only tables",
          len(all_svgs) >= 3, f"{len(all_svgs)} svg in the all-stock view")
    parsed = True
    for svg in svgs:
        try:
            ET.fromstring(svg)
        except Exception as exc:            # noqa: BLE001 - report, do not raise
            parsed = False
            check("every chart is well-formed XML", False, str(exc))
            break
    if parsed:
        check("every chart is well-formed XML", True)

    check("the action queue is drawn, not just tabulated", "queue-ladder" in html)
    # The whole argument of this report: urgency beats size. OVERSTOCK holds the
    # most value and must NOT lead. Sorting by value is what every chart tool
    # would do by default, and it would destroy the judgement BR-31 asks for.
    # One ladder per view, so bound the slice to the first or the two views'
    # rows concatenate and every ordering assertion becomes meaningless.
    _start = html.find('<div class="queue-ladder">')
    _end = html.find("Ordered by how urgent", _start)
    ladder = html[_start:_end if _end > _start else len(html)]
    order = re.findall(r'<div class="ql-lab">([A-Z][^<]*)', ladder)
    widths = [float(w) for w in re.findall(r'class="ql-fill" style="width:([\d.]+)%', ladder)]
    # Assert the PROPERTY, not a particular state name. The fixture carries
    # NON MOVING - ORDER PLACED and the live model does not, so pinning the
    # literal first row would pass here and mean nothing about production.
    drawn = [state.strip() for state in order]
    expected = [state for state in stock_health.ACTION_PRIORITY if state in drawn]
    check("the ladder is drawn in urgency order, whichever states exist",
          drawn == expected, f"drawn={drawn[:3]} expected={expected[:3]}")
    doubles_present = [state for state in stock_health.DOUBLE_WARNING if state in drawn]
    check("a double-warning state leads the ladder when one is present",
          not doubles_present or drawn[0] in doubles_present,
          f"first={drawn[:1]} doubles={doubles_present}")
    check("the largest bar is deliberately not at the top",
          bool(widths) and widths[0] < max(widths) or len(set(widths)) == 1,
          f"first={widths[:1]} max={max(widths) if widths else '-'}")
    check("every queue bar carries its urgency in words, not colour alone",
          ladder.count("ql-flag") >= len(order), "a flag per row")

    check("the estate composition is drawn as a donut", "donut-wrap" in html)
    check("days-without-a-sale is drawn as columns", "dz-axis" in html)
    check("content is escaped",
          "&lt;img" in dashboard_html.render({**page, "title": "<img src=x>"}))


def _scan_with_score() -> dict:
    """The same scan, plus the `_HEALTH SCORE MEASURES` the SB Mart model has.

    The points are COMPUTED from the dimension values rather than typed, so the
    fixture reconciles by construction and a change to `DIMENSION_WEIGHTS` shows
    up here as a failure rather than as a silently re-typed constant.
    """
    from src.domains.inventory import health

    dims = {
        "excess": (0.42131549, 0.42636002, 1.0),
        "ageing": (0.35899612, 0.44942302, 0.52244342),
        "dead": (0.12384015, 0.25636283, 0.88006715),
        "oos": (0.56044459, 0.19975876, 0.60837437),
        "verge": (0.03538148, 0.02562020, 0.85164813),
        "damage": (0.02644063, 0.15839331),
    }
    counts = {"excess": 53020, "ageing": 55888, "dead": 31880,
              "oos": 24841, "verge": 3186, "damage": 19697}
    values = {"excess": 5814679.56, "ageing": 4954594.52, "dead": 1709148.55,
              "oos": 5909957.11, "verge": 373102.0, "damage": 517677.0}

    row: dict = {}
    lost = 0.0
    for key, weights in health.DIMENSION_WEIGHTS.items():
        points = min(health.RISK_CAP, health.RISK_CAP * sum(
            dims[key][i] * weight for i, (_f, _l, weight) in enumerate(weights)))
        lost += points
        row["[%s_points]" % key] = points
        row["[%s_loc_skus]" % key] = float(counts[key])
        row["[%s_value]" % key] = values[key]
        for index, (field, _label, _weight) in enumerate(weights):
            row["[%s]" % field] = dims[key][index]
    row["[lost]"] = lost
    row["[score]"] = 100.0 - lost
    row["[scored_loc_skus]"] = 139436.0
    row["[stock]"] = 13801247.91

    scan = _scan()
    # CFH021 has emptied out, so the position queries return no row for it -
    # which is exactly why the history is the only thing that can see it.
    scan["locations"] = [
        {"[LOC_CODE]": "CDC", "[loc_type]": "WH", "[stock_value]": 25847125.07,
         "[excess_value]": 10848590.47, "[loc_skus]": 20000},
        {"[LOC_CODE]": "CFW001", "[loc_type]": "WH", "[stock_value]": 5989762.22,
         "[excess_value]": 3168532.49, "[loc_skus]": 18000},
        {"[LOC_CODE]": "CFH005", "[loc_type]": "SH", "[stock_value]": 6258285.75,
         "[excess_value]": 2258049.66, "[loc_skus]": 21000},
    ]
    scan["health_overall"] = [row]
    scan["health_status"] = [
        {"[Health Status]": "Critical", "[loc_skus]": 42672.0,
         "[stock]": 5070000.0, "[avg_scored_line]": 52.2},
        {"[Health Status]": "Excellent", "[loc_skus]": 30268.0,
         "[stock]": 3880000.0, "[avg_scored_line]": 52.2},
    ]
    return scan


def test_reference_gaps() -> None:
    """The gaps against `reference_inventory_management_standardised.html`.

    Each check is a numbered gap from `docs/dashboard-reference/README.md`, or a
    defect the delivered page showed that no existing check could see.
    """
    print("\n=== against the standardised reference ===")
    import re as _re

    from src.domains.inventory import health

    scan = _scan_with_score()
    report = stock_health.build(scan)
    score = health.build(scan)
    page = dashboard.build_stock_health(report, score)
    html = dashboard_html.render(page)
    all_view, scoped = page["views"]

    print("\n--- the historical series the scan already pays for ---")
    # Fetched by the scan on every run and never carried into the model, so the
    # page's own trend slot rendered empty from the day it was written.
    check("the kept Stock Value readings reach the model",
          len(report["trend"]) == 4, "%d readings" % len(report["trend"]))
    check("the company series is the locations summed back up",
          abs(report["trend"][-1]["value"]
              - sum(loc["points"][-1]["value"]
                    for loc in report["location_trend"])) < 0.01)
    check("and it is drawn on the page",
          "Stock value at each kept reading" in html)
    check("a scan taken before the location column existed still rebuilds",
          stock_health.build(
              dict(scan, trend=[{"[dates]": "2026-06-01T00:00:00",
                                 "[stock]": 100.0},
                                {"[dates]": "2026-07-01T00:00:00",
                                 "[stock]": 120.0}]))["trend"]
          == [{"date": "2026-06-01", "value": 100.0},
              {"date": "2026-07-01", "value": 120.0}])

    print("\n--- the location that no breakdown can see ---")
    # A location holding nothing returns no row from the position queries, so it
    # is absent from every split. Without the history it is not reported as
    # wound down - it simply stops being mentioned, which reads as never there.
    wound = [w["name"] for w in report["wind_down"]]
    check("a wound-down location is detected", wound == ["CFH021"], wound)
    check("it is absent from the position breakdown that should hold it",
          "CFH021" not in set(r["name"] for r in report["locations"]))
    check("yet the page names it anyway",
          "winding down" in html and "CFH021" in html)
    check("a trivial location cannot manufacture a wind-down finding",
          all(w["first"] >= report["trend"][0]["value"]
              * stock_health.WIND_DOWN_MIN_SHARE_PCT / 100.0
              for w in report["wind_down"]))

    print("\n--- gap 12: four slots, not three ---")
    stories = all_view["layers"]["focus"]["stories"]
    check("every story carries all four slots",
          bool(stories) and all(
              st.get("what_it_is") and st.get("why") and st.get("effect")
              and st.get("do_this") for st in stories))
    check("the why slot names a mechanism, not the points again",
          all("points" not in st["why"].lower() for st in stories),
          [st["why"] for st in stories if "points" in st["why"].lower()])
    check("it names the score's own term and how high it reads",
          all(any(term in st["why"] for term in
                  ("Duration", "SKU breadth", "Value impact", "Sales impact",
                   "Segment severity", "Severity"))
              and "%" in st["why"] for st in stories),
          [st["why"] for st in stories])
    check("a term at its ceiling is reported as such, not as merely highest",
          any("at its maximum" in st["why"] for st in stories))
    check("all four slot headings reach the page",
          all(head in html for head in
              ("What it is", "<dt>Why</dt>", "What it does to the score",
               "Do this")))

    print("\n--- gap 7: severity is a word, never colour alone ---")
    pills = _re.findall(r'<span class="pill pill-([a-z]+)">([^<]+)</span>', html)
    check("the page carries severity pills at all", len(pills) >= 10,
          "%d pills" % len(pills))
    check("every pill carries a word",
          bool(pills) and all(text.strip() for _cls, text in pills))
    for marker in ("Big problem", "Critical", "At Risk"):
        check("the word '%s' reaches the page" % marker, marker in html)
    check("every KPI card states its severity in words",
          all(k["rag"].get("label") is not None for k in all_view["kpis"]))
    check("a neutral card is not given a meaningless word",
          any(k["rag"].get("label") == "" for k in all_view["kpis"]))

    print("\n--- gap 1: the hero owns its own layout ---")
    check("the hero no longer borrows the sales two-column grid",
          'class="hero-inv"' in html and 'class="hero-line"' not in html)
    check("and it carries its own figures",
          len(all_view["hero"]["stats"]) == 3
          and html.count('class="hs') >= 3)

    print("\n--- gap 9: the scoped view owns no breakdowns ---")
    check("the scoped view declares it", scoped["owns_breakdowns"] is False)
    scoped_html = html.split('<section class="view" data-view="exceptions"', 1)[-1]
    check("the scoped breakdown layers name the view that owns the splits",
          scoped_html.count("Switch to All stock") >= 3,
          "%d pointers" % scoped_html.count("Switch to All stock"))
    check("the scoped view prints no estate-wide split rows",
          not scoped["layers"]["detail"]["sections"]
          and not scoped["layers"]["detail"]["segments"]
          and not scoped["layers"]["detail"]["damage"])
    check("but it keeps its own filtered queue",
          bool(scoped["layers"]["detail"]["queue"]))

    print("\n--- a heading with nothing under it ---")
    # `composition_donut` returns "" when a view has no second population, which
    # the scoped view never has - and the heading was emitted regardless.
    check("no heading is printed above a chart that did not render",
          "How much of the estate needs attention" not in scoped_html)

    print("\n--- the two populations are ranked apart ---")
    check("warehouses and stores each get their own ranking",
          ">Warehouses</h3>" in html and ">Stores</h3>" in html)

    check("the whole page is still one script tag", html.count("<script") == 1)
    check("and still self-contained",
          "http://" not in html and "https://" not in html)


def test_published_summary_contract() -> None:
    """The app-facing payload must BE the shared contract, not resemble it.

    There was no coverage here at all, which is how the report shipped for a
    live client emitting `name`/`unit`/`band` metrics, no `sections` and no
    `generatedAt`. The app discards an unparseable summary in silence - no
    error, no log line - so nothing downstream said a word: the client's
    insights rendered normally while the Home brief stayed empty. Target
    Tracker had already shipped this identical defect once.
    """
    print("\n[published summary contract]")
    from src.domains.inventory import stock_health_publish as pub
    from src.tools.api_payloads import ReportSummaryPayload

    report = stock_health.build(_scan())
    payload = pub.summary_payload(report, {"score": 43.54, "band": "Critical"})

    try:
        ReportSummaryPayload(**payload)
        check("the payload validates against the shared contract", True)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        check("the payload validates against the shared contract", False, str(exc))

    check("exactly the five contract fields, no more",
          set(payload) == {"title", "generatedAt", "headline", "metrics", "sections"},
          f"got {sorted(payload)}")
    check("every metric is label/value/tone with a string value",
          all(set(m) == {"label", "value", "tone"} and isinstance(m["value"], str)
              for m in payload["metrics"]),
          str(payload["metrics"][:2]))
    check("sections are present and populated",
          bool(payload["sections"]) and all(s["points"] for s in payload["sections"]))

    # The headline is the field the app keys on; an empty one is discarded just
    # as surely as a wrong shape, so the deterministic floor must fill it.
    stripped = {**report, "prose": {}}
    check("a missing prose block still yields a headline",
          bool(pub.summary_payload(stripped).get("headline", "").strip()))

    # Nothing the contract has no room for may be silently dropped: the queue,
    # the caveats and the as-at date all have to survive as prose.
    text = " ".join(pt for s in payload["sections"] for pt in s["points"])
    check("the as-at date survives into the sections",
          str(report.get("as_at") or "") in text)
    check("the urgent state the source returned nothing for is still stated",
          all(state in text for state in (report.get("states_absent_urgent") or [])))
    check("every standing caveat survives into the sections",
          all(str(c) in text for c in (report.get("caveats") or [])))
    check("the double-warning state leads the action section",
          "most urgent" in payload["sections"][0]["points"][0].lower(),
          payload["sections"][0]["points"][0])

    # And the shape that shipped must be provably rejected, so this test cannot
    # pass against a regression.
    try:
        ReportSummaryPayload(**{"reportId": "inventory_stock_health", "title": "t",
                                "headline": "h", "metrics": [{"name": "Stock Value",
                                                              "value": 1.0}],
                                "queue": [], "checks": {}})
        check("the previously shipped shape is rejected", False, "it validated")
    except Exception:
        check("the previously shipped shape is rejected", True)


def main() -> int:
    print("=" * 72)
    print("WP7 Inventory Management")
    print("=" * 72)

    test_queue_order()
    test_scoping_trap()
    test_excess_meaning()
    test_completeness_and_prose()
    test_dashboard()
    test_reference_gaps()
    test_published_summary_contract()

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
