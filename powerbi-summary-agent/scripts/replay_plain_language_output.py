"""Offline checks for the manager-facing plain-language output contract.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.insight_synthesizer import _clarity_issues
from src.tools.api_payloads import _KpiCardText, _assemble_kpi_card
from src.tools.summary_validation import validate_draft


def _text(description: str) -> _KpiCardText:
    return _KpiCardText(
        signal_id="fixture",
        category="Revenue",
        description=description,
        insight_title="Electronics revenue growth",
        insight_summary=(
            "The increase was concentrated in CFH021. This may reflect the mix "
            "of products sold rather than higher prices."
        ),
        insight_action="Check pricing, discounts, and product groups in CFH021.",
    )


def main() -> int:
    when = datetime(2026, 7, 27, 9, 2)
    electronics = {
        "id": "fixture",
        "candidate_id": "cand_change_contribution",
        "kind": "business",
        "description": "ELECTRONICS revenue growth was 551600 alongside quantity growth.",
        "affected_segment": "ELECTRONICS",
        "impact_value": 551_600.0,
        "impact_share": 15.7,
        "decomposition": [{
            "driver": "QTY Growth",
            "volume_effect": 899_000.0,
            "rate_effect": -347_400.0,
        }],
    }
    card = _assemble_kpi_card(
        1,
        electronics,
        _text(
            "The increase came mainly from more units being sold, although average "
            "revenue per item decreased."
        ),
        when,
    )
    assert card["description"].startswith(
        "ELECTRONICS revenue increased by 551.6K, accounting for about 15.7% "
        "of the total increase in revenue."
    ), card["description"]
    assert card["comparisonLabel"] == "of the total increase in revenue"
    assert [item["label"] for item in card["insight"]["stats"]] == [
        "Revenue change",
        "Share of revenue increase",
        "Change from units sold",
    ]
    assert all(
        phrase not in str(card).casefold()
        for phrase in ("share of total change", "volume / rate", "volume effect", "rate effect")
    )

    vegetables = {
        **electronics,
        "id": "vegetables",
        "affected_segment": "CF-VEGETABLES",
        "impact_value": -514_400.0,
        "impact_share": -14.7,
    }
    vegetable_card = _assemble_kpi_card(
        2,
        vegetables,
        _text("The decline came mainly from fewer units being sold."),
        when,
    )
    assert "offsetting about 14.7% of the total increase in revenue" in vegetable_card["description"]
    assert vegetable_card["comparisonLabel"] == "offsetting the total increase in revenue"
    assert vegetable_card["insight"]["stats"][1] == {
        "label": "Offset to revenue increase",
        "value": "14.7%",
    }

    transactions = {
        **electronics,
        "id": "transactions",
        "description": "CFH018 bills growth was 67000.",
        "affected_segment": "CFH018",
        "impact_value": 67_000.0,
        "impact_share": 26.9,
        "decomposition": None,
    }
    transaction_card = _assemble_kpi_card(
        3,
        transactions,
        _text("More bills were recorded even though fewer items were sold."),
        when,
    )
    assert "67.0K more transactions" in transaction_card["description"]
    assert "bills" not in transaction_card["description"].casefold()

    clear_report = """# Key Insights
The figures compare the same stores with last year.

**Electronics revenue increased by about 551.6K.** The increase came mainly from more units being sold, although average revenue per item decreased. The growth was concentrated in CFH021 and may reflect the mix of products sold. Check pricing and product groups in CFH021.

# Data Quality Watch-outs
None observed in this run.

# Evidence Trail
- Calculation detail.

# Confidence & Caveats
- Supported by the available checks.

# Suggested Follow-ups
- Review product-level performance.
"""
    assert not _clarity_issues(clear_report, 1)
    unclear_report = clear_report.replace(
        "The increase came mainly from more units being sold, although average revenue per item decreased.",
        "The movement decomposition shows a 899.0K volume effect offset by a -347.4K rate effect.",
    ).replace("Check pricing and product groups in CFH021.", "")
    issues = _clarity_issues(unclear_report, 1)
    assert any("analyst shorthand" in issue for issue in issues), issues
    assert any("specific check" in issue for issue in issues), issues

    candidate = {
        "candidate_id": "summary-fixture",
        "evidence": {
            "facts": [{
                "fact_id": "F1",
                "subject": "Overall",
                "metric": "Revenue change",
                "display_value": "+551.6K",
                "raw_value": 551_600.0,
            }],
        },
    }
    draft = {
        "headline": "Revenue increased, a change of +551.6K",
        "metrics": [{"fact_id": "F1", "label": "Revenue change"}],
        "sections": [
            {"heading": "What's working", "points": ["Revenue increased by +551.6K."]},
            {"heading": "Risks", "points": ["No material downside is visible."]},
            {"heading": "Recommended actions", "points": ["Review the revenue breakdown."]},
        ],
        "covered_candidate_ids": ["summary-fixture"],
    }
    assert not validate_draft(draft, [candidate])
    missing_figure = {**draft, "headline": "Revenue increased"}
    assert any(
        "headline must include" in error
        for error in validate_draft(missing_figure, [candidate])
    )

    print("plain-language output replay: all deterministic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
