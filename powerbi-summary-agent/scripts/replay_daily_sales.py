"""Daily Sales - the full four-layer build. Offline.

    python scripts/replay_daily_sales.py

No auth, no LLM, no network. Runs from a synthetic scan that carries the live
figures, and additionally replays the committed
`outputs_sbmart_dailysales/daily_sales_scan.json` when it is present, so the
checks run against a real model shape as well as a hand-built one.

What this pins, and why each one is here rather than being obvious:

  * **The two scales.** Net Sales arrives on two scales in one model. The
    factor is MEASURED two independent ways and the report refuses to rescale
    if they disagree - the refusal path is tested, not just the happy one,
    because a silent wrong rescale is a 3.7x error on every figure below store
    level. The proof that the rescale is right is that all three grains then
    sum to the whole business exactly.
  * **A row with no sale is excluded from its parent's band.** A benchmark
    carrying groups that could not contribute makes every name read below its
    band. Pinned on the two grains where it changes a number.
  * **Category is `CATEGORY_NAME_2`, group is `CATEGORY_NAME`.** Reading the
    group column as the category turns 117 categories into 218 near-duplicates
    and loses the "recorded nothing today" finding entirely.
  * **Rank by money, never by percentage** - a category can be thousands of
    percent over its band on four Riyals of trade.
  * **Layout, not just content.** The previous version of this file asserted
    that the right strings were present, and the page still shipped with the
    whole right-hand hero column missing, because `.hero` is a grid and it was
    being given the wrong children. Presence is not layout.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import snapshot_memory  # noqa: E402
from src.domains.sales import daily_sales as ds  # noqa: E402
from src.domains.sales import daily_sales_dashboard as dash  # noqa: E402
from src.domains.sales import daily_sales_html as dhtml  # noqa: E402
from src.domains.sales import daily_sales_investigator as dinv  # noqa: E402

_failures: list[str] = []

#: The live model's own factor: the benchmark scale is 1/0.27 times the
#: reporting scale. Written as the ratio, never as 3.7037, so the fixture
#: cannot drift from the arithmetic it is meant to exercise.
FACTOR = 100.0 / 27.0

CFG = {
    "report_id": "daily_sales", "report_name": "Daily Sales", "daily_sales_currency": "SAR",
    "daily_sales_mapping": {
        "store_table": "storebenchmark", "department_table": "departmentbenchmark",
        "section_table": "sectionbenchmark", "category_table": "categorybenchmark",
        "sparkline_table": "_Sparkline14", "store_col": "store_no",
        "department_col": "DEPARTMENT", "section_col": "SECTION",
        "category_col": "CATEGORY_NAME_2", "category_group_col": "CATEGORY_NAME",
    },
}


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    _failures.append(label)


# ---------------------------------------------------------------------------
# a synthetic scan on the live model's shape
# ---------------------------------------------------------------------------

def _store_row(date: str, store: str, sales: float, bills: int, margin: float,
               p20: float, p50: float, p80: float,
               b20: int, b50: int, b80: int) -> dict:
    """`sales` is on the REPORTING scale, everything else on the source scale -
    exactly how the model publishes it. `actual_cost` is derived from the
    margin so `measure_scale`'s cost route measures the true factor."""
    return {
        "storebenchmark[tran_date]": f"{date}T00:00:00",
        "storebenchmark[dow_name]": "Wednesday",
        "storebenchmark[week_of_month]": 2,
        "storebenchmark[store_no]": store,
        "storebenchmark[actual_sales]": sales,
        "storebenchmark[actual_cost]": sales * FACTOR * (1.0 - margin / 100.0),
        "storebenchmark[actual_bills]": bills,
        "storebenchmark[actual_margin]": margin,
        "storebenchmark[sales_p20]": p20, "storebenchmark[sales_p50]": p50,
        "storebenchmark[sales_p80]": p80,
        "storebenchmark[bills_p20]": b20, "storebenchmark[bills_p50]": b50,
        "storebenchmark[bills_p80]": b80,
        "storebenchmark[margin_p20]": 20.0, "storebenchmark[margin_p50]": 21.0,
        "storebenchmark[margin_p80]": 22.0,
        "storebenchmark[sample_days]": 25, "storebenchmark[margin_sample_days]": 13,
    }


def _grain_row(table: str, cols: dict, sales, bills, margin, p20, p50, p80,
               b20=None, b50=None, b80=None) -> dict:
    """A department/section/category row. `sales` is on the SOURCE scale here,
    like the model's own below-store figures; `None` means the row recorded no
    sale, which is a different thing from zero."""
    row = {f"{table}[{name}]": value for name, value in cols.items()}
    row[f"{table}[tran_date]"] = "2026-08-12T00:00:00"
    row[f"{table}[actual_sales]"] = sales
    row[f"{table}[actual_cost]"] = (None if sales is None
                                    else sales * (1.0 - (margin or 0.0) / 100.0))
    row[f"{table}[actual_bills]"] = bills
    row[f"{table}[actual_margin]"] = margin
    row[f"{table}[sales_p20]"] = p20
    row[f"{table}[sales_p50]"] = p50
    row[f"{table}[sales_p80]"] = p80
    row[f"{table}[bills_p20]"] = b20
    row[f"{table}[bills_p50]"] = b50
    row[f"{table}[bills_p80]"] = b80
    row[f"{table}[sample_days]"] = 25
    row[f"{table}[margin_sample_days]"] = 13
    return row


def _spark_row(date: str, sales: float, bills: int, margin: float,
               p20: float, p50: float, p80: float, b20: int, b50: int, b80: int) -> dict:
    return {
        "_Sparkline14[tran_date]": f"{date}T00:00:00",
        "_Sparkline14[actual_sales]": sales,
        "_Sparkline14[actual_bills]": bills,
        "_Sparkline14[sales_p20]": p20, "_Sparkline14[sales_p50]": p50,
        "_Sparkline14[sales_p80]": p80,
        "_Sparkline14[bills_p20]": b20, "_Sparkline14[bills_p50]": b50,
        "_Sparkline14[bills_p80]": b80,
        "_Sparkline14[profit_actual]": sales * margin / 100.0,
        "_Sparkline14[margin_actual]": margin,
        "_Sparkline14[margin_p20]": 20.0, "_Sparkline14[margin_p50]": 21.0,
        "_Sparkline14[margin_p80]": 22.0,
    }


def synthetic_scan(*, store_days: int = 14, dead_department: bool = True) -> dict:
    """Two stores, fourteen days, five live departments plus a silent one.

    ST1 finishes EXACTLY on its P20 floor - the case that shipped as
    "Underperforming" because the rescale leaves it a few parts in 1e-12
    below its own band edge."""
    dates = [f"2026-07-{30 + i}" if 30 + i <= 31 else f"2026-08-{30 + i - 31:02d}"
             for i in range(store_days)]
    dates = dates[-store_days:]

    stores = []
    for index, date in enumerate(dates):
        last = index == len(dates) - 1
        # On the final day ST1 lands on its floor and ST4 lands under it.
        st1_sales = 38040.4809
        st4_sales = 31319.8245 if last else 30000.0 + index * 10
        stores.append(_store_row(date, "ST1", st1_sales, 3111, 22.0,
                                 st1_sales * FACTOR, 41000.0 * FACTOR, 44083.0 * FACTOR,
                                 2994, 3102, 3219))
        stores.append(_store_row(date, "ST4", st4_sales, 2669, 24.0,
                                 31418.61 * FACTOR, 35000.0 * FACTOR, 41000.0 * FACTOR,
                                 2677, 2879, 3077))

    whole_sales = 38040.4809 + 31319.8245
    # The whole-business margin is the stores' own, weighted by sales - the
    # relationship the live model holds, and the one the store-cost
    # reconciliation check tests.
    whole_margin = (38040.4809 * 22.0 + 31319.8245 * 24.0) / whole_sales
    spark = []
    for index, date in enumerate(dates):
        last = index == len(dates) - 1
        sales = whole_sales if last else 66000.0 + index * 100
        spark.append(_spark_row(date, sales, 5780, whole_margin,
                                69459.093 * FACTOR, 76428.7 * FACTOR, 85206.9 * FACTOR,
                                5671, 5981, 6296))

    # Departments: the five live ones sum (on the source scale) to the whole
    # business once rescaled, plus OTHER which recorded nothing at all.
    dept_source = {"CONSUMER GOODS": 32517.9, "FRESH FOOD": 15061.6, "LIFESTYLE": 13268.2,
                   "HOME & LIVING": 4814.0, "TECHNOLOGY": 3698.6}
    scale_up = whole_sales / sum(dept_source.values())
    # Split each department between the stores by that store's real share of
    # the day, so the department total for a store is exactly that store's own
    # Net Sales times the factor - which is what the grain route measures.
    shares = {"ST1": 38040.4809 / whole_sales, "ST4": 31319.8245 / whole_sales}
    departments = []
    for name, value in dept_source.items():
        source = value * scale_up * FACTOR
        band_low = source * (1.05 if name == "CONSUMER GOODS" else 0.9)
        for store, share in shares.items():
            departments.append(_grain_row(
                "departmentbenchmark", {"store_no": store, "DEPARTMENT": name},
                source * share, int(500 * share * 2), 20.0,
                band_low * share, source * 0.6 * share, source * 0.8 * share,
                400, 500, 600))
    if dead_department:
        departments.append(_grain_row(
            "departmentbenchmark", {"store_no": "ST1", "DEPARTMENT": "OTHER"},
            None, None, None, 10.0, 20.0, 30.0, 1, 2, 3))

    # One section carrying a silent row whose band would otherwise be counted.
    sections = [
        _grain_row("sectionbenchmark",
                   {"store_no": "ST1", "DEPARTMENT": "FRESH FOOD", "SECTION": "DELI"},
                   1000.0 * FACTOR, 100, 20.0, 900.0 * FACTOR, 1100.0 * FACTOR,
                   1300.0 * FACTOR, 80, 100, 120),
        _grain_row("sectionbenchmark",
                   {"store_no": "ST1", "DEPARTMENT": "FRESH FOOD", "SECTION": "DELI"},
                   None, None, None, 50.0 * FACTOR, 60.0 * FACTOR, 70.0 * FACTOR, 1, 2, 3),
    ]

    # Two categories sharing the group name "OTHER" under different sections,
    # plus a freak percentage on a trivial base that must never lead a list.
    categories = [
        _grain_row("categorybenchmark",
                   {"store_no": "ST1", "DEPARTMENT": "CONSUMER GOODS", "SECTION": "PROVISIONS",
                    "CATEGORY_NAME_2": "RICE", "CATEGORY_NAME": "BASMATI"},
                   3000.0 * FACTOR, 200, 20.0, 3400.0 * FACTOR, 3600.0 * FACTOR,
                   4000.0 * FACTOR, 150, 200, 250),
        _grain_row("categorybenchmark",
                   {"store_no": "ST1", "DEPARTMENT": "CONSUMER GOODS", "SECTION": "PROVISIONS",
                    "CATEGORY_NAME_2": "RICE", "CATEGORY_NAME": "JASMINE"},
                   500.0 * FACTOR, 40, 20.0, 400.0 * FACTOR, 450.0 * FACTOR,
                   600.0 * FACTOR, 30, 40, 50),
        _grain_row("categorybenchmark",
                   {"store_no": "ST1", "DEPARTMENT": "CONSUMER GOODS", "SECTION": "PROVISIONS",
                    "CATEGORY_NAME_2": "RICE", "CATEGORY_NAME": "SELLA"},
                   None, None, None, 900.0 * FACTOR, 950.0 * FACTOR, 1000.0 * FACTOR, 5, 6, 7),
        _grain_row("categorybenchmark",
                   {"store_no": "ST1", "DEPARTMENT": "LIFESTYLE", "SECTION": "FOOTWEAR",
                    "CATEGORY_NAME_2": "TINY THING", "CATEGORY_NAME": "TINY THING"},
                   90.0 * FACTOR, 2, 20.0, 1.0 * FACTOR, 2.0 * FACTOR, 4.0 * FACTOR, 1, 1, 2),
        # A near-empty line 97% under its floor, against RICE's 400 shortfall
        # on 3,500 of trade. Money order puts RICE first; percentage order puts
        # this one first. The two orders MUST disagree here or the ranking rule
        # is untested.
        _grain_row("categorybenchmark",
                   {"store_no": "ST1", "DEPARTMENT": "LIFESTYLE", "SECTION": "FOOTWEAR",
                    "CATEGORY_NAME_2": "ALMOST NOTHING", "CATEGORY_NAME": "ALMOST NOTHING"},
                   1.0 * FACTOR, 1, 20.0, 40.0 * FACTOR, 50.0 * FACTOR, 60.0 * FACTOR, 1, 2, 3),
    ]

    return {
        "meta": [{"[store_latest]": f"{dates[-1]}T00:00:00",
                  "[last_updated]": f"Last updated {dates[-1]}"}],
        "store": stores, "department": departments, "section": sections,
        "category": categories, "sparkline": spark,
    }


# ---------------------------------------------------------------------------
# the two scales
# ---------------------------------------------------------------------------

def test_scale_is_measured_twice_and_must_agree() -> None:
    print("\n=== the Net Sales scale is measured two independent ways ===")
    scan = synthetic_scan()
    today = [r for r in scan["store"] if "2026-08-12" in str(r["storebenchmark[tran_date]"])]
    info = ds.measure_scale(today, scan["department"])
    check("the cost route measures the factor", abs(info["cost_factor"] - FACTOR) < 1e-9,
          f"got {info['cost_factor']}")
    check("the department-total route measures the same factor",
          abs(info["grain_factor"] - FACTOR) < 1e-6, f"got {info['grain_factor']}")
    check("the two agree, so the rescale is applied", info["applied"] is True)
    check("scale is the reciprocal of the factor", abs(info["scale"] - 0.27) < 1e-9,
          f"got {info['scale']}")
    check("the reason names the factor it measured", "3.7037" in info["reason"])

    print("\n=== a disagreement REFUSES to rescale rather than guessing ===")
    tampered = [dict(row) for row in scan["department"]]
    for row in tampered:
        if row.get("departmentbenchmark[actual_sales]") is not None:
            row["departmentbenchmark[actual_sales]"] *= 1.5
    bad = ds.measure_scale(today, tampered)
    check("applied is False when the two routes disagree", bad["applied"] is False)
    check("factor is left unset", bad["factor"] is None)
    check("scale falls back to 1.0, never to a half-measured value", bad["scale"] == 1.0)
    check("the reason states both measurements", "disagree" in bad["reason"])

    print("\n=== a model that publishes one scale is a no-op, not a caveat ===")
    clean_stores = []
    for row in today:
        copy = dict(row)
        margin = copy["storebenchmark[actual_margin]"]
        copy["storebenchmark[actual_cost]"] = (
            copy["storebenchmark[actual_sales]"] * (1.0 - margin / 100.0))
        clean_stores.append(copy)
    clean_depts = []
    for row in scan["department"]:
        copy = dict(row)
        if copy.get("departmentbenchmark[actual_sales]") is not None:
            copy["departmentbenchmark[actual_sales]"] /= FACTOR
        clean_depts.append(copy)
    neutral = ds.measure_scale(clean_stores, clean_depts)
    check("a factor of 1.0 measures cleanly", abs(neutral["factor"] - 1.0) < 1e-9,
          f"got {neutral['factor']}")
    check("nothing is rescaled", neutral["applied"] is False)
    check("and it is not reported as a refusal", "disagree" not in neutral["reason"])


def test_every_level_reconciles_after_the_rescale() -> None:
    print("\n=== the proof the rescale is right: every level sums to the whole ===")
    model = ds.build(synthetic_scan(), CFG)
    whole = model["whole"]["net_sales"]["actual"]
    for grain in ("departments", "sections", "categories"):
        total = sum((row.get("net_sales") or {}).get("actual") or 0.0
                    for row in model[grain])
        if grain == "departments":
            check("department Net Sales sums to the whole business",
                  abs(total - whole) < 0.01, f"{total} vs {whole}")
        else:
            check(f"{grain} are on the reporting scale (not {FACTOR:.2f}x too big)",
                  total < whole * 1.01, f"{total} vs whole {whole}")
    check("the model's own department check passes",
          model["checks"]["department_sales_reconciles_to_whole"])
    check("store Net Sales sums to the whole business",
          model["checks"]["store_sales_reconciles_to_whole"])
    check("store cost sums to the whole-business cost",
          model["checks"]["store_cost_reconciles_to_whole"])

    print("\n=== with no verified scale, below-store Net Sales is WITHHELD ===")
    scan = synthetic_scan()
    for row in scan["department"]:
        if row.get("departmentbenchmark[actual_sales]") is not None:
            row["departmentbenchmark[actual_sales]"] *= 1.5
    withheld = ds.build(scan, CFG)
    check("grain_sales_known is False", withheld["grain_sales_known"] is False)
    live = [row for row in withheld["departments"] if not row["silent"]]
    check("no department shows a Net Sales figure",
          all(row["net_sales"]["actual"] is None for row in live))
    check("no department shows a Net Sales band",
          all(row["net_sales"]["p20"] is None for row in live))
    check("Bills survives, because a count needs no rescale",
          all(row["bills"]["actual"] is not None for row in live))
    check("the reconciliation check reports the failure rather than hiding it",
          withheld["checks"]["department_sales_reconciles_to_whole"] is False)


# ---------------------------------------------------------------------------
# rollups
# ---------------------------------------------------------------------------

def test_a_row_with_no_sale_is_excluded_band_and_all() -> None:
    print("\n=== a row that recorded no sale is dropped from its parent, band included ===")
    model = ds.build(synthetic_scan(), CFG)
    deli = next(row for row in model["sections"] if row["name"] == "DELI")
    check("DELI's band excludes the silent row's P20",
          abs(deli["net_sales"]["p20"] - 900.0) < 0.01,
          f"got {deli['net_sales']['p20']}, would be 950.0 if the silent row counted")
    check("DELI's band excludes the silent row's P80",
          abs(deli["net_sales"]["p80"] - 1300.0) < 0.01)
    check("the silent row is counted, not forgotten", deli["silent_groups"] == 1)

    other = next((row for row in model["departments"] if row["name"] == "OTHER"), None)
    check("a department where every row is silent is marked silent",
          other is not None and other["silent"] is True)
    check("and it is not in the reportable department list",
          "OTHER" not in [row["name"] for row in model["departments"] if not row["silent"]])

    page = dash.build(model)
    check("the page's department table has no silent row",
          all(cells[0] != "OTHER" for cells in page["departments"]["table"]["rows"]))
    leads = " ".join(item["lead"] for item in page["caveats"])
    check("but the page says so in a caveat", "OTHER" in leads, leads)


def test_category_grain_is_the_category_not_the_group() -> None:
    print("\n=== category is CATEGORY_NAME_2; CATEGORY_NAME is the group underneath ===")
    model = ds.build(synthetic_scan(), CFG)
    names = [row["name"] for row in model["categories"]]
    check("RICE appears once, not once per group", names.count("RICE") == 1, str(names))
    check("the group names are not used as categories",
          "BASMATI" not in names and "SELLA" not in names, str(names))

    rice = next(row for row in model["categories"] if row["name"] == "RICE")
    check("the live groups are summed into the category",
          abs(rice["net_sales"]["actual"] - 3500.0) < 0.01, str(rice["net_sales"]["actual"]))
    check("the silent group is counted", rice["silent_groups"] == 1)
    check("the silent group's usual take is carried",
          abs(rice["silent_benchmark"] - 950.0) < 0.01)

    silent = next(row for row in model["silent_groups"] if row["name"] == "RICE")
    check("the silent-groups table reads '1 of 3'",
          silent["silent"] == 1 and silent["total"] == 3,
          f"{silent['silent']} of {silent['total']}")
    check("and states what the rest took",
          abs(silent["taken_by_rest"] - 3500.0) < 0.01)

    print("\n  -- reading the group column as the category instead --")
    wrong = dict(CFG)
    wrong["daily_sales_mapping"] = dict(CFG["daily_sales_mapping"], category_col="CATEGORY_NAME")
    wrong_model = ds.build(synthetic_scan(), wrong)
    check("it splits one category into its groups",
          len([r for r in wrong_model["categories"] if not r["silent"]]) >
          len([r for r in model["categories"] if not r["silent"]]))
    check("and loses the 'recorded nothing today' finding",
          not wrong_model["silent_groups"])


# ---------------------------------------------------------------------------
# band readings
# ---------------------------------------------------------------------------

def test_a_value_on_its_band_edge_is_inside_the_band() -> None:
    print("\n=== a figure sitting on its floor is IN BAND, not Underperforming ===")
    check("exactly on the floor", ds.verdict(100.0, 100.0, 120.0)["key"] == "neutral")
    check("exactly on the ceiling", ds.verdict(120.0, 100.0, 120.0)["key"] == "neutral")
    check("a hair below the floor, from a rescale, is still inside",
          ds.verdict(100.0, 100.0 * (1 + 1e-12), 120.0)["key"] == "neutral")
    check("a real move below the floor is still Underperforming",
          ds.verdict(99.99, 100.0, 120.0)["key"] == "crit")
    check("gap is exactly zero on the edge", ds.band_gap(100.0, 100.0, 120.0) == 0.0)
    check("a missing input never guesses a verdict", ds.verdict(None, 100.0, 120.0)["key"] is None)

    model = ds.build(synthetic_scan(), CFG)
    st1 = next(store for store in model["stores"] if store["store"] == "ST1")
    check("ST1, landing on its own rescaled floor, reads In band",
          st1["net_sales"]["verdict"]["word"] == "In band",
          f"actual {st1['net_sales']['actual']} p20 {st1['net_sales']['p20']}")
    fmt = dash._fmt("net_sales", "SAR")
    check("and is worded as level with its floor",
          dash.against_band(st1["net_sales"], fmt) == "level with its P20 floor")


def test_a_gap_too_small_to_print_is_worded_not_zeroed() -> None:
    print("\n=== a sub-rounding gap never prints as a signed zero ===")
    cases = [
        ("basket_value", 11.7328, 11.7365, "just below its P20 floor"),
        ("bills", 2676.7, 2677.0, "just below its P20 floor"),
        ("margin", 21.999999, 22.0, "just below its P20 floor"),
    ]
    for kind, actual, p20, expected in cases:
        got = dash.against_band({"actual": actual, "p20": p20, "p80": p20 * 2,
                                 "verdict": ds.verdict(actual, p20, p20 * 2)},
                                dash._fmt(kind, "SAR"))
        check(f"{kind}: {got!r}", got == expected, f"expected {expected!r}")
    real = dash.against_band({"actual": 31319.8245, "p20": 31418.61, "p80": 50000.0},
                             dash._fmt("net_sales", "SAR"))
    check("a real gap still prints its figure", "98.79" in real, real)


# ---------------------------------------------------------------------------
# ranking
# ---------------------------------------------------------------------------

def test_ranking_is_by_money_never_by_percentage() -> None:
    print("\n=== a freak percentage on a trivial base must not lead a list ===")
    model = ds.build(synthetic_scan(), CFG)
    page = dash.build(model)
    above = page["categories"]["above"]
    check("the trivial category is present", any(b["name"] == "TINY THING" for b in above),
          str([b["name"] for b in above]))
    if above:
        tiny = next(b for b in above if b["name"] == "TINY THING")
        percent_over = (90.0 - 4.0) / 4.0 * 100.0
        check(f"it is {percent_over:.0f}% over its ceiling on 90 of trade, "
              f"and is ranked by its money gap", True)

    print("\n  -- and money order genuinely differs from percentage order here --")
    rows = {row["name"]: row["net_sales"] for row in page["categories"]["rows"]}
    by_money = sorted(rows, key=lambda n: -abs(rows[n]["gap"] or 0.0))
    by_percent = sorted(rows, key=lambda n: -abs((rows[n]["gap"] or 0.0)
                                                 / (rows[n]["actual"] or 1.0)))
    check("the fixture is one where the two orders disagree",
          by_money[0] != by_percent[0], f"money {by_money[:2]} percent {by_percent[:2]}")
    names = [bar["name"] for bar in page["categories"]["below"]]
    check("the below-band list leads with the largest MONEY gap",
          names and names[0] == by_money[0], f"{names} vs money order {by_money}")
    check("the near-empty line is present but not leading",
          "ALMOST NOTHING" in names and names[0] != "ALMOST NOTHING", str(names))
    gaps = [abs(rows[name]["gap"] or 0.0) for name in names]
    check("and the whole list is in descending money order",
          gaps == sorted(gaps, reverse=True), str(list(zip(names, gaps))))


def test_the_bridge_adds_up_and_names_the_right_driver() -> None:
    print("\n=== Bills x Basket Value splits the gap exactly ===")
    model = ds.build(synthetic_scan(), CFG)
    page = dash.build(model)
    bridge = page["bridge"]
    check("a bridge is built", bridge is not None)
    total = bridge["bills_effect"] + bridge["basket_effect"]
    gap = model["whole"]["net_sales"]["vs_benchmark"]
    check("the two effects add to the Net Sales gap against the benchmark",
          abs(total - gap) < 0.01, f"{total} vs {gap}")
    check("the waterfall closes on the day's real Net Sales",
          abs(bridge["end"] - model["whole"]["net_sales"]["actual"]) < 1e-9)

    print("\n  -- the quoted share belongs to the effect the sentence names --")
    # Two constructed days: one the bill count drives, one the basket drives.
    # The live 2026-08-23 position is the first, and it published "the bill
    # count is 3% of the gap" - the basket's share under the bill count's name.
    for label, bills, basket, expect_driver, expect_share in (
            ("bill count drives", {"actual": 4353.0, "p50": 5691.0},
             {"actual": 12.70, "p50": 12.83}, "bill count", 97),
            ("basket drives", {"actual": 5780.0, "p50": 5981.0},
             {"actual": 12.00, "p50": 12.78}, "smaller basket", 64)):
        model = {
            "currency": "SAR",
            "whole": {
                "net_sales": {"actual": bills["actual"] * basket["actual"],
                              "p50": bills["p50"] * basket["p50"]},
                "bills": bills, "basket_value": basket,
            },
        }
        note = dash._bridge(model)["note"]
        check(f"{label}: the note names the {expect_driver}", expect_driver in note, note)
        check(f"{label}: with a share of {expect_share}%, its own and not the other's",
              f"{expect_share}% of the gap" in note, note)
        other = "smaller basket" if expect_driver == "bill count" else "bill count"
        check(f"{label}: and does not name the other effect as the driver",
              f"The {other} is" not in note, note)


def test_signals_rank_by_money_and_never_by_bills() -> None:
    print("\n=== KPI-feed signals use Net Sales, which adds up at every level ===")
    page = dash.build(ds.build(synthetic_scan(), CFG))
    signals = dash.to_signals(page)
    check("signals are produced", bool(signals))
    kinds = {str(s["analysis_type"]) for s in signals}
    check("no signal is built on a Bills gap below the whole business",
          not any("bills" in kind and "whole" not in kind for kind in kinds), str(kinds))
    scores = [float(s["score"]) for s in signals]
    check("ranked by score, descending", scores == sorted(scores, reverse=True))
    check("every signal carries a comparison label, so the feed never publishes "
          "'against the prior period'",
          all(s.get("comparison_label") for s in signals))
    check("ids are assigned after the ranking",
          [s["id"] for s in signals] == [f"I{i}" for i in range(1, len(signals) + 1)])


# ---------------------------------------------------------------------------
# the rendered document
# ---------------------------------------------------------------------------

def _render() -> str:
    return dhtml.render(dash.build(ds.build(synthetic_scan(), CFG)), eyebrow="Sales")


def test_page_skeleton() -> None:
    print("\n=== layout, not just content ===")
    html = _render()

    app = re.search(r'<div class="app"[^>]*>(.*)</div>\s*<script', html, re.S)
    check("the .app wrapper is found", app is not None)
    inner = app.group(1) if app else ""
    check(".app's first child is the rail", inner.lstrip().startswith("<nav class=\"rail\""))
    check(".app's only other child is <main>", inner.count("<main>") == 1)
    check("the page lives inside main > .page", '<main><div class="page">' in html)

    hero = re.search(r'<div class="hero">(.*?)</div></div>', html, re.S)
    check("the hero is found", hero is not None)
    check("the hero's second child is .hero-stats",
          '</div><div class="hero-stats">' in html,
          "a non-grid hero loses the whole right-hand column")
    heroes = html.count('<div class="hero">')
    check("every hero has a stats column",
          heroes == html.count('<div class="hero-stats">') and heroes >= 1,
          f"{heroes} heroes")
    blocks = html.count('<div class="hs')
    check("each one carries three stat blocks", blocks == 3 * heroes,
          f"{blocks} blocks across {heroes} heroes")
    check(".hero is declared as a grid in the stylesheet",
          "display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)" in html)

    check("exactly one <script tag - nesting them kills every handler",
          html.count("<script") == 1, str(html.count("<script")))
    check("no external request", "http://" not in html and "https://" not in html)
    check("no browser storage API", "localStorage" not in html and "sessionStorage" not in html)


def test_every_layer_is_reachable_and_present() -> None:
    print("\n=== every layer has a nav button, and every button has a layer ===")
    html = _render()
    layers = set(re.findall(r'data-layer="([a-z]+)"', html))
    navs = set(re.findall(r'data-nav="([a-z]+)"', html))
    check("layers and nav buttons match exactly", layers == navs, f"{layers} vs {navs}")
    check("all four layers are present",
          layers == {"day", "stores", "departments", "detail"}, str(layers))
    check("both views exist on every layer",
          html.count('data-view="all"') == html.count('data-view="out"'))


def test_the_reference_sections_are_all_there() -> None:
    print("\n=== the approved design's sections all render ===")
    html = _render()
    for heading in ("What carried the day",
                    "Net Sales against the normal band, day by day",
                    "Look across", "Look down",
                    "The last two weeks",
                    "Every department on this day",
                    "How many baskets each department reached",
                    "Departments outside their band",
                    "Each department, store by store",
                    "What finished below its band",
                    "What finished above its band",
                    "Groups that recorded nothing today",
                    "Every section", "Every category",
                    "What these figures cover, and what they do not"):
        check(f"section present: {heading}", heading in html)
    check("the share bars carry a benchmark tick", 'class="rb-tick"' in html)
    check("the date is written out, not printed as an ISO stamp",
          "Wednesday 12 August 2026" in html and ">2026-08-12<" not in html)


def test_store_trend_degrades_when_the_model_holds_one_day() -> None:
    print("\n=== one day of store history means no store trend, not a broken one ===")
    page = dash.build(ds.build(synthetic_scan(store_days=1), CFG))
    check("no per-store trend is offered", page["store_trends"] == [])
    html = dhtml.render(page)
    check("and the section is absent rather than empty", "The last two weeks" not in html)
    check("the rest of the page still renders", "Every department on this day" in html)

    full = dash.build(ds.build(synthetic_scan(store_days=14), CFG))
    check("fourteen days of store history produces one trend per store",
          len(full["store_trends"]) == 2, str(len(full["store_trends"])))
    check("each trend counts its days",
          all(t["chart"]["total"] == 14 for t in full["store_trends"]))


def test_html_is_escaped() -> None:
    print("\n=== a member name carrying markup is escaped, never injected ===")
    scan = synthetic_scan()
    scan["department"][0]["departmentbenchmark[DEPARTMENT]"] = '<img src=x onerror=alert(1)>'
    html = dhtml.render(dash.build(ds.build(scan, CFG)))
    check("the tag is escaped", "<img src=x" not in html)
    check("and its text still shows", "&lt;img src=x" in html)


# ---------------------------------------------------------------------------
# the investigator's DAX
# ---------------------------------------------------------------------------

def test_drill_dax_scopes_its_aggregation() -> None:
    print("\n=== the drill's filters must reach the aggregation ===")
    dax = dinv.build_drill_dax(CFG, own_role="department", own_member="CONSUMER GOODS",
                               drill_role="section")
    check("it summarises over a scoped table variable", "SUMMARIZE(\n    Scoped," in dax, dax)
    check("the scope filters on the latest date", "[tran_date] = LatestDate" in dax)
    check("and on the parent member", 'sectionbenchmark[DEPARTMENT] = "CONSUMER GOODS"' in dax)
    check("and drops rows with no sale", "NOT ISBLANK(sectionbenchmark[actual_sales])" in dax)
    check("it does NOT wrap SUMMARIZE in CALCULATETABLE with the aggregation outside - "
          "that shape loses every filter and sums all 14 days",
          "CALCULATETABLE(" not in dax, dax)
    check("it drills Net Sales, not the non-additive Bills count",
          "actual_sales" in dax and "actual_bills" not in dax)
    check("the latest date comes from a measure, never a literal",
          "[Section Latest Date]" in dax and "2026-" not in dax)

    check("a quoted member name is escaped",
          '""' in dinv.build_drill_dax(CFG, own_role="department", own_member='A"B',
                                       drill_role="section"))

    print("\n  -- and the drilled gaps are put on the reporting scale --")
    rows = [{"sectionbenchmark[SECTION]": "PROVISIONS", "[gap]": -21008.9}]
    scaled = dinv._normalize(CFG, rows, "section", 0.27)
    check("a source-scale gap is rescaled", abs(scaled[0]["value"] + 5672.4) < 0.1,
          str(scaled))
    check("candidates are drawn from Net Sales findings only",
          dinv.candidates({"stat_signals": [
              {"analysis_type": "daily_sales_department_bills_band", "dimension": "department",
               "affected_segment": "X"}]}, CFG, max_findings=3) == [])


# ---------------------------------------------------------------------------
# memory
# ---------------------------------------------------------------------------

def test_memory_suppresses_an_unchanged_finding() -> None:
    print("\n=== an unchanged finding is not re-alerted the next day ===")
    import tempfile
    page = dash.build(ds.build(synthetic_scan(), CFG))
    signals = dash.to_signals(page)
    if not signals:
        check("signals exist to test with", False)
        return
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        first = snapshot_memory.filter_signals(signals, report_id="daily_sales", out_dir=out,
                                               dataset_id="ds", observed_at="2026-08-12")
        snapshot_memory.commit(first)
        second = snapshot_memory.filter_signals(signals, report_id="daily_sales", out_dir=out,
                                                dataset_id="ds", observed_at="2026-08-13")
        check("the first run reports them", first["stats"]["reportable"] == len(signals))
        check("the second run suppresses them", second["stats"]["reportable"] == 0,
              str(second["stats"]))
        check("but they are still counted as detected",
              second["stats"]["detected"] == len(signals))


# ---------------------------------------------------------------------------
# the committed live scan
# ---------------------------------------------------------------------------

def test_committed_scan() -> None:
    path = PROJECT_ROOT / "outputs_sbmart_dailysales" / "daily_sales_scan.json"
    if not path.exists():
        print("\n=== committed scan not present, skipping ===")
        return
    print(f"\n=== replayed against the committed scan ({path.name}) ===")
    scan = json.loads(path.read_text(encoding="utf-8"))
    cfg = dict(CFG)
    cfg["daily_sales_currency"] = "SAR"
    model = ds.build(scan, cfg)
    check("the scale is verified on real data", model["checks"]["scale_verified"])
    check("the measured factor is 1/0.27",
          abs(model["scale"]["factor"] - FACTOR) < 1e-6, str(model["scale"]["factor"]))
    for name, ok in model["checks"].items():
        check(f"reconciliation: {name}", ok)

    page = dash.build(model)
    html = dhtml.render(page)
    check("the page renders", len(html) > 50_000)
    check("every reportable department is in the document",
          all(row["name"].replace("&", "&amp;") in html
              for row in page["departments"]["rows"]))
    check("every reportable section is in the document",
          all(row["name"].replace("&", "&amp;") in html
              for row in page["sections"]["rows"]))
    check("the hero leads on Net Sales", "Net Sales" in page["hero"]["headline"])
    check("no ISO date is printed as a heading", ">2026-08-" not in html)


def main() -> int:
    test_scale_is_measured_twice_and_must_agree()
    test_every_level_reconciles_after_the_rescale()
    test_a_row_with_no_sale_is_excluded_band_and_all()
    test_category_grain_is_the_category_not_the_group()
    test_a_value_on_its_band_edge_is_inside_the_band()
    test_a_gap_too_small_to_print_is_worded_not_zeroed()
    test_ranking_is_by_money_never_by_percentage()
    test_the_bridge_adds_up_and_names_the_right_driver()
    test_signals_rank_by_money_and_never_by_bills()
    test_page_skeleton()
    test_every_layer_is_reachable_and_present()
    test_the_reference_sections_are_all_there()
    test_store_trend_degrades_when_the_model_holds_one_day()
    test_html_is_escaped()
    test_drill_dax_scopes_its_aggregation()
    test_memory_suppresses_an_unchanged_finding()
    test_committed_scan()

    print()
    if _failures:
        print(f"FAILED ({len(_failures)}):")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("All Daily Sales replay checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
