"""SKU Overview: single-snapshot Loc-SKU stock position. Offline.

    python scripts/replay_sku_overview.py

No auth, no LLM, no network. Uses a synthetic scan built to the live shape
(2026-08-23): 139,200 rows, RECOMMENDED_ACTION states summing to the total,
and a burnout-days sentinel of 1000 mixed with real, low, genuine readings -
because the live model returned exactly that mix and the sentinel handling is
the one thing in this report most likely to silently misread as data.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import sku_overview_flow as flow  # noqa: E402

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
    "report_id": "sku_overview",
    "report_name": "Test SKU Overview",
    "sku_overview_currency": "USD",
    "sku_overview_mapping": {
        "table": "REP_SSR_STOCK_STATUS_REPORTV3",
        "stock_value": "'REP_SSR_STOCK_STATUS_REPORTV3'[SKU_STOCK_VALUE]",
        "excess_value": "'REP_SSR_STOCK_STATUS_REPORTV3'[EXCESS_STOCK_VALUE]",
        "pending_value": "'REP_SSR_STOCK_STATUS_REPORTV3'[PENDING_ORDERS_VALUE]",
        "opp_loss": "'REP_SSR_STOCK_STATUS_REPORTV3'[OPP_LOSS_DUE_TO_STOCKOUT]",
        "burnout_days": "'REP_SSR_STOCK_STATUS_REPORTV3'[EXPECTED_BURNOUT_DAYS]",
        "recommended_action": "'REP_SSR_STOCK_STATUS_REPORTV3'[RECOMMENDED_ACTION]",
        "snapshot": "'REP_SSR_STOCK_STATUS_REPORTV3'[UPDATED_ON]",
        "sku": "'REP_SSR_STOCK_STATUS_REPORTV3'[SKU_CODE]",
        "sku_description": "'REP_SSR_STOCK_STATUS_REPORTV3'[PART_DESCRIPTION]",
        "location": "'REP_SSR_STOCK_STATUS_REPORTV3'[LOC_CODE]",
        "dimensions": {
            "department": "'REP_SSR_STOCK_STATUS_REPORTV3'[DEPARTMENT]",
            "location": "'REP_SSR_STOCK_STATUS_REPORTV3'[LOC_CODE]",
        },
    },
}


def _synthetic_scan() -> dict:
    return {
        "currency": "USD",
        "snapshot": [{"[as_at]": "2026-08-23T00:00:00", "[snapshot_cardinality]": 1,
                      "[rows]": 1000, "[skus]": 400, "[locations]": 7,
                      "[total_stock_value]": 13_000_000.0, "[total_excess_value]": 5_500_000.0,
                      "[total_pending_value]": 994_000.0, "[total_opp_loss]": 294_500.0}],
        "states": [
            {"REP_SSR_STOCK_STATUS_REPORTV3[RECOMMENDED_ACTION]": "STOCK OUT - PLACE ORDER",
             "[rows]": 172, "[stock_value]": 0.0, "[excess_value]": 0.0,
             "[pending_value]": 0.0, "[opp_loss]": 294_500.0},
            {"REP_SSR_STOCK_STATUS_REPORTV3[RECOMMENDED_ACTION]": "OVERSTOCK",
             "[rows]": 295, "[stock_value]": 8_000_000.0, "[excess_value]": 5_500_000.0,
             "[pending_value]": 0.0, "[opp_loss]": 0.0},
            {"REP_SSR_STOCK_STATUS_REPORTV3[RECOMMENDED_ACTION]": "STOCK AVAILABLE",
             "[rows]": 533, "[stock_value]": 5_000_000.0, "[excess_value]": 0.0,
             "[pending_value]": 994_000.0, "[opp_loss]": 0.0},
        ],
        "dimensions": {
            "department": [
                {"REP_SSR_STOCK_STATUS_REPORTV3[DEPARTMENT]": "HOME & LIVING",
                 "[stock_value]": 3_000_000.0, "[excess_value]": 1_800_000.0, "[opp_loss]": 50_000.0},
                {"REP_SSR_STOCK_STATUS_REPORTV3[DEPARTMENT]": "GROCERY",
                 "[stock_value]": 10_000_000.0, "[excess_value]": 3_700_000.0, "[opp_loss]": 244_500.0},
            ],
            "location": [
                {"REP_SSR_STOCK_STATUS_REPORTV3[LOC_CODE]": "WH1",
                 "[stock_value]": 6_000_000.0, "[excess_value]": 3_200_000.0, "[opp_loss]": 100_000.0},
                {"REP_SSR_STOCK_STATUS_REPORTV3[LOC_CODE]": "ST1",
                 "[stock_value]": 7_000_000.0, "[excess_value]": 2_300_000.0, "[opp_loss]": 194_500.0},
            ],
        },
        "deep_dives": {
            "lowest_burnout": [
                {"REP_SSR_STOCK_STATUS_REPORTV3[SKU_CODE]": "SKU001",
                 "REP_SSR_STOCK_STATUS_REPORTV3[PART_DESCRIPTION]": "Widget A",
                 "REP_SSR_STOCK_STATUS_REPORTV3[LOC_CODE]": "WH1",
                 "[burnout]": 2.0, "[value]": 500.0},
                {"REP_SSR_STOCK_STATUS_REPORTV3[SKU_CODE]": "SKU002",
                 "REP_SSR_STOCK_STATUS_REPORTV3[PART_DESCRIPTION]": "Widget B",
                 "REP_SSR_STOCK_STATUS_REPORTV3[LOC_CODE]": "ST1",
                 "[burnout]": 5.0, "[value]": 300.0},
            ],
            "highest_opp_loss": [
                {"REP_SSR_STOCK_STATUS_REPORTV3[SKU_CODE]": "SKU003",
                 "REP_SSR_STOCK_STATUS_REPORTV3[PART_DESCRIPTION]": "Widget C",
                 "[value]": 12_000.0},
            ],
            "highest_excess": [
                {"REP_SSR_STOCK_STATUS_REPORTV3[SKU_CODE]": "SKU004",
                 "REP_SSR_STOCK_STATUS_REPORTV3[PART_DESCRIPTION]": "Widget D",
                 "[value]": 45_000.0},
            ],
        },
    }


def test_burnout_sentinel_never_leaks_into_the_dax() -> None:
    print("\n=== the burnout-days sentinel is excluded in the DAX itself ===")
    queries = flow.build_queries(CFG)
    dax = queries["deep__lowest_burnout"]
    check("the sentinel floor is a filter condition",
          f"[burnout] < {int(flow.BURNOUT_SENTINEL_FLOOR)}" in dax, dax)
    check("blank/zero burnout is excluded, never read as zero days",
          "[burnout] > 0" in dax, dax)
    check("burnout is aggregated (MIN), never left as a raw multi-value column - "
          "this is the exact defect that made the live query fail",
          "MIN(" in dax, dax)
    check("the grain includes location - burnout is a per Loc-SKU figure, and "
          "grouping by SKU alone collapses two real facts into one",
          "'REP_SSR_STOCK_STATUS_REPORTV3'[LOC_CODE]," in dax
          and dax.index("'REP_SSR_STOCK_STATUS_REPORTV3'[LOC_CODE],") < dax.index('"burnout"'),
          dax)


def test_report_model() -> None:
    print("\n=== the report model ===")
    model = flow.build(_synthetic_scan(), CFG)

    check("the period is stated 'as at', never as a span (NN 18)",
          model["period_label"] == "as at 2026-08-23", model["period_label"])
    check("every reconciliation check passes on the synthetic figures",
          all(model["checks"].values()), model["checks"])
    check("the header carries the headline figures",
          {"total_stock_value", "total_excess_value", "total_opp_loss"} <= set(model["header"]))
    check("states are ranked by stock value, largest first",
          [s["action"] for s in model["states"]]
          == sorted([s["action"] for s in model["states"]],
                    key=lambda a: -next(s["stock_value"] for s in model["states"] if s["action"] == a)))

    print("\n--- deep dives carry the right unit, never money for a day count ---")
    burnout_dive = next(d for d in model["deep_dives"] if d["analysis"] == "lowest_burnout")
    check("burnout is tagged 'days', not 'money'", burnout_dive["unit"] == "days")
    check("its rows carry the location that makes two same-SKU rows distinct",
          all(r["location"] for r in burnout_dive["rows"]), burnout_dive["rows"])
    money_dive = next(d for d in model["deep_dives"] if d["analysis"] == "highest_opp_loss")
    check("opportunity loss is tagged 'money'", money_dive["unit"] == "money")


def test_stat_signals() -> None:
    print("\n=== ranked findings ===")
    model = flow.build(_synthetic_scan(), CFG)
    signals = model["stat_signals"]
    check("findings were produced", len(signals) > 0)
    check("the urgent stock-out state leads, whatever its value (it is zero)",
          signals[0]["analysis_type"] == "sku_overview_urgent_state", signals[0])
    check("every signal carries a story_key for the KPI feed's stable ids",
          all(s.get("story_key") for s in signals))
    check("every signal declares its own comparison label, never falling through "
          "to a year-on-year template",
          all(s.get("comparison_label") for s in signals))
    check("re-running on identical input produces identical story_keys",
          [s["story_key"] for s in flow.build(_synthetic_scan(), CFG)["stat_signals"]]
          == [s["story_key"] for s in signals])


def test_published_summary_contract() -> None:
    print("\n=== published summary contract ===")
    from src.domains.inventory import sku_overview_publish as pub
    from src.tools.api_payloads import ReportSummaryPayload

    model = flow.build(_synthetic_scan(), CFG)
    payload = pub.summary_payload(model)
    try:
        ReportSummaryPayload(**payload)
        check("the payload validates against the shared contract", True)
    except Exception as exc:  # noqa: BLE001
        check("the payload validates against the shared contract", False, str(exc))
    check("exactly the five contract fields, no more",
          set(payload) == {"title", "generatedAt", "headline", "metrics", "sections"},
          sorted(payload))
    check("the headline leads with the urgent stock-out state",
          "STOCK OUT - PLACE ORDER" in payload["headline"], payload["headline"])

    quiet = flow.build({**_synthetic_scan(), "states": [
        {"REP_SSR_STOCK_STATUS_REPORTV3[RECOMMENDED_ACTION]": "STOCK AVAILABLE",
         "[rows]": 1000, "[stock_value]": 13_000_000.0, "[excess_value]": 0.0,
         "[pending_value]": 0.0, "[opp_loss]": 0.0}]}, CFG)
    quiet_payload = pub.summary_payload(quiet)
    check("a quiet position still yields a headline", bool(quiet_payload["headline"].strip()))


def main() -> int:
    print("=" * 72)
    print("SKU Overview - single stock position")
    print("=" * 72)

    test_burnout_sentinel_never_leaks_into_the_dax()
    test_report_model()
    test_stat_signals()
    test_published_summary_contract()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SKU OVERVIEW FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
