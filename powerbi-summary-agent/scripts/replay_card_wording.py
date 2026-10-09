"""Offline proof of the KPI card wording a demo audience reads.

Each check pins a sentence SB Mart's feed published on 2026-10-06 and a reader
stumbled on:

* "...versus the prior period, representing about 151.3% of the total decline
  in unit sales" - an unnamed baseline, and a share no reader believes.
* "14,499 Loc-SKUs are in STOCK OUT - PLACE ORDER, 11.6% of the 124,535 in the
  position. Place an emergency purchase order." - code-owned, so it skipped the
  plain-language pass the model's words go through.
* "That matters because..." opening every summary's second sentence, and
  "Most of this is likely to be in..." closing the inventory cards.
* "-39.8K" on a card saying the month was 39,824 ahead of target.
* A count of products tagged as USD.

No Power BI, Azure or LLM credentials are required.

    python scripts/replay_card_wording.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import stock_health_signals  # noqa: E402,F401
from src.domains.sales import target_tracker_signals as ts  # noqa: E402
from src.tools import api_payloads as ap  # noqa: E402

FAILURES: list[str] = []
WHEN = datetime(2026, 10, 6, 7, 0)


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _text(summary: str = "", description: str = "") -> ap._KpiCardText:
    return ap._KpiCardText(
        signal_id="fixture", category="Units", description=description,
        insight_title="Confectionery drove the drop", insight_summary=summary,
        insight_action="Review the confectionery range for the period.",
    )


def _yoy(share: float = 151.3) -> dict:
    return {
        "id": "confectionery", "kind": "business", "candidate_id": "cand_01_change_contribution",
        "affected_segment": "CONFECTIONERY",
        "dimension": ["'MIS_DEEP_DIVE2'[product_group_name]"],
        "metric_family": "quantity", "bundle_id": "MIS::qty",
        "impact_value": -637_600.0, "impact_share": share,
        "current": 4_710_000.0, "prior": 5_350_000.0,
        "description": "CONFECTIONERY changed by -637600 of QTY Growth.",
    }


PROFILE = {"value_bundles": [{"id": "MIS::qty", "measures": {
    "current": "net qty CY", "prior": "net qty LY", "change": "QTY Growth"}}]}


def test_year_on_year_lead() -> None:
    print("\nA year-on-year card names its baseline and never quotes a share over 100%")
    sig = ap._with_baseline_labels([_yoy()], {"semantic_model_profile": PROFILE})[0]
    check("metadata that proves last year labels the card", sig.get("baseline_label")
          == "the same period last year", str(sig.get("baseline_label")))
    lead = ap._main_change_sentence(sig, ap._signal_family(sig))
    check("the lead says which period", "versus the same period last year" in lead, lead)
    check("the impossible-looking share is said in words, not figures",
          "151.3%" not in lead and "more than the whole business's net decline" in lead, lead)
    card = ap._assemble_kpi_card(1, sig, _text(), WHEN)
    check("the caption names the period too",
          card["comparisonLabel"] == "vs the same period last year", card["comparisonLabel"])
    check("the model may not put the share back",
          "151.3%" not in ap._quotable_figures(sig, ap._signal_family(sig)))

    unproven = ap._with_baseline_labels([_yoy()], {"semantic_model_profile": {}})[0]
    check("unproven metadata keeps the neutral wording",
          "versus the prior period" in ap._main_change_sentence(unproven, "Quantity"))
    ordinary = ap._with_baseline_labels([_yoy(share=42.0)], {"semantic_model_profile": PROFILE})[0]
    check("an ordinary share is still quoted",
          "about 42.0% of the total decline" in ap._main_change_sentence(ordinary, "Quantity"))
    damage = dict(_yoy(share=317.0), share_label="Above the 3-month average",
                  comparison_label="against the average of the previous 3 months",
                  description="Damage in August 2026 was 275,371, 317.0% above the average.")
    check("a declared non-share percentage stays quotable",
          "317.0%" in ap._quotable_figures(damage, "Performance"))
    check("the model is told the segment's real level",
          ap._signal_facts(sig)["segment_level"] == "product group",
          str(ap._signal_facts(sig)["segment_level"]))


def test_stock_words() -> None:
    print("\nThe inventory report's codes become words on a card")
    plain = ap._plain_business_text(
        "14,499 Loc-SKUs are in STOCK OUT - PLACE ORDER, 11.6% of the 124,535 in the position.")
    check("the state becomes a clause", "are out of stock, with no order placed" in plain, plain)
    check("no status code, no 'position'",
          "STOCK OUT" not in plain and "position" not in plain, plain)
    nearly = ap._plain_business_text("2,592 Loc-SKUs are in ON THE VERGE OF STOCK OUT - PLACE ORDER.")
    check("the longer state is read whole, not as its shorter tail",
          "about to run out, with no order placed" in nearly, nearly)
    label = ap._plain_business_text("Check the oldest STOCK OUT - PLACE ORDER lines.")
    check("anywhere else it is a short label", '"out of stock, not yet ordered"' in label, label)
    check("a caption loses 'in the stock position'",
          ap._plain_business_text("11.6% of all Loc-SKUs in the stock position")
          == "11.6% of all products in stores")
    check("measure names lose their capitals",
          ap._plain_business_text("6,469,902 is 43.5% of the 14,868,950 Stock Value.")
          .endswith("stock value."))
    check("'Critical SKUs' are top sellers, not 'Critical products'",
          "top-selling products" in ap._plain_business_text("1,042 Critical SKUs are out"))
    check("the rulebook stops describing itself",
          ap._plain_business_text("The rules list this as one of the two most urgent "
                                  "situations.").startswith("This is one of"))


def test_summary_habits() -> None:
    print("\nThe two narration habits are removed from what the model wrote")
    cleaned = ap._without_formula(
        "CONFECTIONERY lost 637.6K units. That matters because this one product group "
        "carries the fall. Most of this is likely to be in the stores with the oldest stock.")
    check("'That matters because' is cut, the point kept",
          "That matters" not in cleaned and "This one product group carries the fall." in cleaned,
          cleaned)
    check("a guess at where it sits is dropped", "likely to be" not in cleaned, cleaned)
    hedge = ap._without_formula("Units fell. This may reflect a smaller range on shelf.")
    check("a careful hedge on a cause is kept", "may reflect" in hedge, hedge)

    sig = ap._with_baseline_labels([_yoy()], {"semantic_model_profile": PROFILE})[0]
    card = ap._assemble_kpi_card(1, sig, _text(
        summary="CONFECTIONERY lost 637.6K units. That matters because the drop sits "
                "in one area. This is likely to sit in the largest stores.",
        description="That matters because it is the largest fall."), WHEN)
    shown = card["description"] + " " + card["insight"]["summary"]
    check("neither habit reaches the published card",
          "That matters" not in shown and "likely to sit" not in shown, shown)


def test_counts_and_leads() -> None:
    print("\nA count is a count, and a lead is a positive number")
    model = {"as_at": "2026-09-15", "header": {"loc_skus": 124_535},
             "double_warnings": [{"action": "STOCK OUT - PLACE ORDER", "loc_skus": 14_499,
                                  "guidance": "Place an emergency purchase order."}]}
    signal = stock_health_signals.double_warning_states(model)[0]
    check("the rulebook's order stays on the page, off the card",
          "emergency" not in signal["description"], signal["description"])
    card = ap._assemble_kpi_card(1, signal, _text(), WHEN, extended_fields=True,
                                 state={"config": {}})
    check("a count of products is not tagged as money",
          card.get("valueType") == "count" and not card.get("unit"),
          f"{card.get('valueType')} {card.get('unit')}")

    lead = ts.surplus_exhausting({
        "anchor": "2026-09-15",
        "surplus": {"now": 39_824.0, "given_back": 32_580.0, "run_days": 4,
                    "days_until_exhausted": 4.9, "exhausts_on": "2026-09-20"},
        "periods": {"mtd": {"target": 2_450_000.0}},
    })[0]
    card = ap._assemble_kpi_card(1, lead, _text(), WHEN)
    check("a month 39,824 ahead shows +39.8K", card["value"] == "+39.8K", card["value"])
    check("...still as something to act on", card["severity"] != "positive", card["severity"])
    check("...with its date written for a reader",
          "20 September" in card["description"] and "2026-09-20" not in card["description"],
          card["description"])


def main() -> int:
    print("=" * 72)
    print("REPLAY: KPI card wording")
    print("=" * 72)
    test_year_on_year_lead()
    test_stock_words()
    test_summary_habits()
    test_counts_and_leads()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
