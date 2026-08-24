"""Daily Sales - reduced-scope build. Offline.

    python scripts/replay_daily_sales.py

No auth, no LLM, no network. The central thing this pins is the defect
boundary itself: a verified ~3.7x join-fan-out in the source model inflates
every SUM-based Net Sales figure below the store level, and every level's
Net Sales/Basket Value P20/P50/P80 band (see `daily_sales.py`'s module
docstring for how this was established against the live model). Bills and
Margin are unaffected everywhere. These checks assert the code never shows
a Net Sales figure or band outside the one place it is trustworthy
(store/whole-business actual only), so a future edit cannot quietly
reintroduce the exact number this was built to avoid showing.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import snapshot_memory  # noqa: E402
from src.domains.sales import daily_sales as ds  # noqa: E402
from src.domains.sales import daily_sales_dashboard as dash  # noqa: E402

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


def test_verdict_classification() -> None:
    print("\n=== verdict() classifies against the band, never guesses when data is missing ===")
    check("below the floor is Underperforming", ds.verdict(90, 100, 120)["key"] == "crit")
    check("above the ceiling is Outperforming", ds.verdict(130, 100, 120)["key"] == "good")
    check("inside the band is neutral", ds.verdict(110, 100, 120)["key"] == "neutral")
    check("exactly on the floor counts as inside (not below)", ds.verdict(100, 100, 120)["key"] == "neutral")
    check("exactly on the ceiling counts as inside (not above)", ds.verdict(120, 100, 120)["key"] == "neutral")
    check("a missing actual returns key=None, never a guessed verdict", ds.verdict(None, 100, 120)["key"] is None)
    check("a missing p20 returns key=None", ds.verdict(110, None, 120)["key"] is None)
    check("a missing p80 returns key=None", ds.verdict(110, 100, None)["key"] is None)


def _bundle(bills_actual, bills_p20, bills_p80, margin_actual, margin_p20, margin_p80,
           *, sales_reliable=False, sales_actual=None):
    row = {
        "[actual_bills]": bills_actual, "[bills_p20]": bills_p20, "[bills_p50]": None,
        "[bills_p80]": bills_p80, "[actual_margin]": margin_actual, "[margin_p20]": margin_p20,
        "[margin_p50]": None, "[margin_p80]": margin_p80, "[sample_days]": 25,
        "[margin_sample_days]": 13, "[actual_sales]": sales_actual,
    }
    return ds._measure_bundle(row, sales_reliable=sales_reliable)


def test_measure_bundle_never_exposes_unreliable_sales() -> None:
    print("\n=== _measure_bundle never marks Net Sales/Basket Value reliable "
         "when sales_reliable=False ===")
    b = _bundle(100, 90, 110, 20.0, 18.0, 22.0, sales_reliable=False, sales_actual=99999.0)
    check("net_sales.available is False regardless of a present actual_sales column",
          b["net_sales"]["available"] is False)
    check("net_sales.actual is None, not the (unreliable) raw column value",
          b["net_sales"]["actual"] is None)
    check("basket_value.available is False too - it derives from Net Sales",
          b["basket_value"]["available"] is False)
    check("bills is still classified", b["bills"]["verdict"]["key"] == "neutral")
    check("margin is still classified", b["margin"]["verdict"]["key"] == "neutral")

    reliable = _bundle(100, 90, 110, 20.0, 18.0, 22.0, sales_reliable=True, sales_actual=1200.0)
    check("net_sales.available is True only when sales_reliable=True was passed explicitly",
          reliable["net_sales"]["available"] is True)
    check("basket_value is then Sales/Bills", reliable["basket_value"]["actual"] == 12.0)


def test_grain_rows_are_always_sales_unreliable() -> None:
    print("\n=== department/section/category rows never carry a Net Sales figure ===")
    scan_result = {
        "meta": [{"[store_latest]": "2026-08-12T00:00:00", "[dept_latest]": "2026-08-12T00:00:00",
                 "[section_latest]": "2026-08-12T00:00:00", "[category_latest]": "2026-08-12T00:00:00",
                 "[last_updated]": "Last updated 12 Aug 2026"}],
        "store": [{"[store_no]": "ST1", "[dow_name]": "Wednesday", "[week_of_month]": 2,
                  "[actual_sales]": 38040.48, "[actual_bills]": 3111, "[bills_p20]": 2994,
                  "[bills_p50]": 3102, "[bills_p80]": 3219, "[actual_margin]": 22.56,
                  "[margin_p20]": 20.87, "[margin_p50]": 21.28, "[margin_p80]": 22.19,
                  "[sample_days]": 25, "[margin_sample_days]": 13}],
        "department": [{"[store_no]": "ST1", "[DEPARTMENT]": "CONSUMER GOODS",
                        "[actual_sales]": 999999.0, "[actual_bills]": 1430, "[bills_p20]": 1400,
                        "[bills_p50]": 1420, "[bills_p80]": 1500, "[actual_margin]": 18.0,
                        "[margin_p20]": 17.0, "[margin_p50]": 17.5, "[margin_p80]": 19.0,
                        "[sample_days]": 25, "[margin_sample_days]": 13}],
        "section": [], "category": [],
        "sparkline": [{"[tran_date]": "2026-08-12T00:00:00", "[actual_sales]": 38040.48,
                      "[actual_bills]": 3111, "[bills_p20]": 2994, "[bills_p50]": 3102,
                      "[bills_p80]": 3219, "[margin_actual]": 22.56, "[margin_p20]": 20.87,
                      "[margin_p50]": 21.28, "[margin_p80]": 22.19}],
    }
    cfg = {"daily_sales_currency": "SAR",
          "daily_sales_mapping": {"store_col": "store_no", "department_col": "DEPARTMENT",
                                  "section_col": "SECTION", "category_col": "CATEGORY_NAME"}}
    model = ds.build(scan_result, cfg)
    dept = model["departments"][0]
    check("a department row's actual_sales column (999999.0, deliberately absurd) is never surfaced",
          dept["net_sales"]["available"] is False and dept["net_sales"]["actual"] is None, dept)
    check("store rows DO carry a reliable Net Sales actual",
          model["stores"][0]["net_sales"]["available"] is True
          and model["stores"][0]["net_sales"]["actual"] == 38040.48)
    check("the whole-business figure comes from the sparkline row, matching the store total",
          model["whole"]["net_sales"]["actual"] == 38040.48)
    check("reconciliation passes when store and whole agree",
          model["checks"]["store_sales_reconciles_to_whole"] is True)


def test_merge_by_name_sums_bills_and_weights_margin_by_bills() -> None:
    print("\n=== merge_by_name: Bills summed (safe), Margin bills-weighted, never sales-weighted ===")
    rows = [
        {"name": "CONSUMER GOODS", "store": "ST1", "sample_days": 25,
         "bills": {"actual": 100.0, "p20": 90.0, "p50": 95.0, "p80": 110.0},
         "margin": {"actual": 10.0, "p20": 8.0, "p50": 9.0, "p80": 12.0}},
        {"name": "CONSUMER GOODS", "store": "ST1", "sample_days": 25,
         "bills": {"actual": 300.0, "p20": 280.0, "p50": 290.0, "p80": 320.0},
         "margin": {"actual": 30.0, "p20": 28.0, "p50": 29.0, "p80": 32.0}},
    ]
    merged = dash.merge_by_name(rows, key_fields=("name",))
    check("exactly one merged group for the shared name", len(merged) == 1, merged)
    g = merged[0]
    check("Bills actual is the sum (100+300=400)", g["bills"]["actual"] == 400.0)
    check("Bills p20/p80 are summed too, matching the reference's own treatment of Net Sales bands",
          g["bills"]["p20"] == 370.0 and g["bills"]["p80"] == 430.0)
    expected_margin = (10.0 * 100.0 + 30.0 * 300.0) / (100.0 + 300.0)
    check("Margin is bills-weighted, not a plain average (would give 20.0, not 25.0)",
          abs(g["margin"]["actual"] - expected_margin) < 1e-9, g["margin"])
    check("net_sales is never populated on a merged row",
          g["net_sales"]["available"] is False and g["net_sales"]["actual"] is None)
    check("group_count records how many underlying rows were merged", g["group_count"] == 2)
    check("stores lists every contributing store", g["stores"] == ["ST1"])


def test_merge_by_name_keeps_blank_bills_distinct_from_zero() -> None:
    print("\n=== a group with no Bills reading at all stays None, not 0 ===")
    rows = [{"name": "OTHER", "store": "ST1", "sample_days": 11,
            "bills": {"actual": None, "p20": 1.0, "p50": 3.0, "p80": 8.0},
            "margin": {"actual": None, "p20": 10.34, "p50": 10.4, "p80": 12.5}}]
    merged = dash.merge_by_name(rows, key_fields=("name",))
    check("bills actual stays None (a group that recorded nothing, not zero bills)",
          merged[0]["bills"]["actual"] is None)
    check("its verdict is 'not available', never a guessed classification",
          merged[0]["bills"]["verdict"]["key"] is None)


def test_outside_band_filter() -> None:
    print("\n=== _outside_band keeps a row if EITHER Bills or Margin is outside its band ===")
    inside = dash._bundle_display(_bundle(100, 90, 110, 20.0, 18.0, 22.0, sales_reliable=False),
                                  currency="SAR", label="X")
    check("both measures inside the band is not outside", dash._outside_band(inside) is False)
    bills_out = dash._bundle_display(_bundle(80, 90, 110, 20.0, 18.0, 22.0, sales_reliable=False),
                                     currency="SAR", label="X")
    check("Bills alone outside the band counts", dash._outside_band(bills_out) is True)
    margin_out = dash._bundle_display(_bundle(100, 90, 110, 25.0, 18.0, 22.0, sales_reliable=False),
                                      currency="SAR", label="X")
    check("Margin alone outside the band counts", dash._outside_band(margin_out) is True)


def test_to_signals_never_emits_a_net_sales_signal() -> None:
    print("\n=== to_signals() only ever scores Bills/Margin gaps, never Net Sales ===")
    page = {
        "as_at": "2026-08-12",
        "whole": {
            "bills": {"actual": 5780, "p20": 5671, "p50": 5981, "p80": 6296, "gap": 0.0,
                     "verdict": {"key": "neutral", "word": "In band"}},
            "margin": {"actual": 23.18, "p20": 21.80, "p50": 22.39, "p80": 22.98, "gap": 0.20,
                      "verdict": {"key": "good", "word": "Outperforming"}},
        },
        "departments": {"outside": [
            {"name": "CONSUMER GOODS",
             "bills": {"actual": 4082, "p20": 4101, "p80": 4759, "gap": -19.0,
                      "verdict": {"key": "crit", "word": "Underperforming"}},
             "margin": {"actual": 17.99, "p20": 16.67, "p80": 17.92, "gap": 0.0,
                       "verdict": {"key": "neutral", "word": "In band"}}},
        ]},
        "sections": {"outside": []},
    }
    signals = dash.to_signals(page)
    check("at least one signal was produced", len(signals) >= 1, signals)
    for s in signals:
        # "daily_sales" is the report-id prefix on every analysis_type by design;
        # what must never appear is the *measure* net_sales/basket_value.
        measure_part = s["analysis_type"].removeprefix("daily_sales_")
        check(f"{s['candidate_id']} scores Bills or Margin only, never Net Sales/Basket Value",
              "net_sales" not in measure_part and "basket" not in measure_part, s)
        check(f"{s['candidate_id']} carries the full contract the KPI-card assembler reads",
              {"candidate_id", "story_key", "report_id", "impact_value", "score", "severity",
               "comparison_label", "description", "id"} <= set(s), s)
    check("story_keys are stable across an identical re-run",
          [s["story_key"] for s in signals] == [s["story_key"] for s in dash.to_signals(page)])


def test_memory_suppresses_an_unchanged_finding_and_reports_a_clearance() -> None:
    print("\n=== to_signals() output feeds cleanly into the shared cross-run "
         "memory engine (snapshot_memory) ===")
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="daily_sales_memory_replay_"))
    try:
        signal = {
            "candidate_id": "daily_sales_department_bills:CONSUMER GOODS:",
            "story_key": "irrelevant-for-memory", "report_id": "daily_sales",
            "analysis_type": "daily_sales_department_bills_band", "dimension": "department",
            "affected_segment": "CONSUMER GOODS", "impact_value": -19.0, "score": 19.0,
            "severity": "critical", "description": "CONSUMER GOODS finished Bills underperforming.",
        }
        r1 = snapshot_memory.filter_signals(
            [signal], report_id="daily_sales", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-12")
        check("day 1: a brand-new finding is reportable", len(r1["reportable"]) == 1, r1)
        snapshot_memory.commit(r1)

        r2 = snapshot_memory.filter_signals(
            [signal], report_id="daily_sales", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-13")
        check("day 2: the identical finding is suppressed, not re-reported",
              len(r2["reportable"]) == 0, r2)
        snapshot_memory.commit(r2)

        r3 = snapshot_memory.filter_signals(
            [], report_id="daily_sales", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-14")
        check("day 3: the finding vanishing from the scan surfaces a clearance",
              len(r3["cleared"]) == 1 and "CONSUMER GOODS" in r3["cleared"][0]["description"],
              r3["cleared"])
        check("a clearance is positive severity, never critical",
              r3["cleared"][0]["severity"] == "positive", r3["cleared"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_queries_use_dynamic_latest_date_not_a_hardcoded_one() -> None:
    print("\n=== build_queries never hardcodes a date - always the model's own latest ===")
    cfg = {"daily_sales_mapping": {
        "store_table": "storebenchmark", "department_table": "departmentbenchmark",
        "section_table": "sectionbenchmark", "category_table": "categorybenchmark",
        "sparkline_table": "_Sparkline14"}}
    queries = ds.build_queries(cfg)
    for name in ("store", "department", "section", "category"):
        check(f"{name} query resolves the latest date via a measure, not a literal DATE(...)",
              "DATE(" not in queries[name] and "Latest Date" in queries[name], queries[name])


def main() -> int:
    print("=" * 72)
    print("Daily Sales - reduced-scope build (verified model defect boundary)")
    print("=" * 72)

    test_verdict_classification()
    test_measure_bundle_never_exposes_unreliable_sales()
    test_grain_rows_are_always_sales_unreliable()
    test_merge_by_name_sums_bills_and_weights_margin_by_bills()
    test_merge_by_name_keeps_blank_bills_distinct_from_zero()
    test_outside_band_filter()
    test_to_signals_never_emits_a_net_sales_signal()
    test_memory_suppresses_an_unchanged_finding_and_reports_a_clearance()
    test_build_queries_use_dynamic_latest_date_not_a_hardcoded_one()

    print("\n" + "=" * 72)
    if _failures:
        print(f"DAILY SALES FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
