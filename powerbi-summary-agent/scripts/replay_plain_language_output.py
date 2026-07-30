"""Offline checks for the manager-facing plain-language output contract.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents.insight_stat_detector import _rate_volume_split
from src.agents.insight_synthesizer import (
    _clarity_issues,
    _deterministic_finding,
    _manager_fact_brief,
    _supported_numbers,
)
from src.agents.summary_candidate_builder import _comparison_facts, _comparison_label
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

    row = {
        "net revenue CURRENT": 775_727.74,
        "net revenue PAST": 549_115.39,
        "net qty CURRENT": 13_154.0,
        "net qty PAST": 9_727.0,
        "net bills CURRENT": 10_264.0,
        "net bills PAST": 7_581.0,
    }
    revenue_triple = {
        "current": "net revenue CURRENT",
        "prior": "net revenue PAST",
        "change": "revenue Growth",
    }
    quantity_split = _rate_volume_split(row, revenue_triple, {
        "current": "net qty CURRENT", "prior": "net qty PAST", "change": "QTY Growth",
    })
    transaction_split = _rate_volume_split(row, revenue_triple, {
        "current": "net bills CURRENT", "prior": "net bills PAST", "change": "bills growth",
    })
    assert quantity_split["driver_change"] == 3_427.0
    assert quantity_split["driver_change_pct"] == 35.2318
    assert quantity_split["volume_effect_share_pct"] == 85.372
    assert transaction_split["driver_change"] == 2_683.0
    assert transaction_split["driver_change_pct"] == 35.3911

    profile = {
        "value_bundles": [{
            "id": "SALES::revenue",
            "measures": {"prior": "Revenue last year"},
            "evidence": [{
                "phase": "prior",
                "name": "Revenue last year",
                "column_refs": [{"column": "revenue_ly"}],
            }],
        }],
        "volume_driver_bundles": [{
            "id": "SALES::quantity",
            "measures": {"prior": "Units last year"},
            "evidence": [{
                "phase": "prior",
                "name": "Units last year",
                "column_refs": [{"column": "units_ly"}],
            }],
        }],
    }

    torch_signal = {
        "id": "cfh021_hand_torch_revenue_growth",
        "kind": "business",
        "description": "CFH021 HAND TORCH revenue increased by 226612.35.",
        "affected_segment": "CFH021 HAND TORCH",
        "metric_family": "revenue",
        "bundle_id": "SALES::revenue",
        "metric": "revenue Growth",
        "current": 775_727.74,
        "prior": 549_115.39,
        "impact_value": 226_612.35,
        "impact_share": 6.5317,
        "decomposition": [quantity_split, transaction_split],
    }
    torch_brief = _manager_fact_brief(torch_signal, profile)
    assert torch_brief["main"]["change_pct_display"] == "41.3%"
    assert torch_brief["main"]["prior_display"] == "549.1K"
    assert torch_brief["drivers"][0]["prior_display"] == "9,727"
    assert torch_brief["drivers"][1]["change_pct_display"] == "35.4%"
    assert torch_brief["main"]["comparison"] == "the same period last year"

    torch_card = _assemble_kpi_card(
        4,
        torch_signal,
        _text("Most of the increase was linked to more units being sold."),
        when,
    )
    assert (
        "revenue increased by 226.6K (41.3%), from 549.1K to 775.7K versus the prior period"
        in torch_card["description"]
    ), torch_card["description"]
    assert torch_card["delta"] == "41.3%"
    assert torch_card["comparisonLabel"] == "vs the prior period"

    summary_comparisons = _comparison_facts(
        [{
            "product": "HAND TORCH",
            "net revenue CURRENT": 775_727.74,
            "net revenue PAST": 549_115.39,
            "revenue Growth": 226_612.35,
        }],
        "product",
        ["net revenue CURRENT", "net revenue PAST", "revenue Growth"],
        "the same period last year",
    )
    assert len(summary_comparisons) == 1
    assert summary_comparisons[0]["change_pct_display"] == "41.3%"
    assert "from 549.1K to 775.7K" in summary_comparisons[0]["statement"]
    assert summary_comparisons[0]["comparison"] == "the same period last year"
    assert _comparison_label(
        profile,
        ["Revenue current", "Revenue last year", "Revenue change"],
    ) == "the same period last year"
    month_comparisons = _comparison_facts(
        [{
            "month": 3,
            "net revenue CURRENT": 120.0,
            "net revenue PAST": 100.0,
            "revenue Growth": 20.0,
        }],
        "month",
        ["net revenue CURRENT", "net revenue PAST", "revenue Growth"],
        "the same period last year",
    )
    assert month_comparisons[0]["subject"] == "March"

    torch_supported_numbers = _supported_numbers(torch_brief)
    fallback_finding = _deterministic_finding(torch_signal, torch_brief)
    assert fallback_finding is not None
    clear_report = f"""# Key Insights
The figures compare the same stores with the same period last year.

{fallback_finding}

# Data Quality Watch-outs
None observed in this run.

# Evidence Trail
- Calculation detail.

# Confidence & Caveats
- Supported by the available checks.

# Suggested Follow-ups
- Review product-level performance.
"""
    assert not _clarity_issues(
        clear_report, 1, [torch_brief], torch_supported_numbers
    )
    clear_issues = _clarity_issues(
        clear_report, 1, [torch_brief], torch_supported_numbers
    )
    assert not clear_issues, clear_issues
    unclear_report = """# Key Insights
The figures compare the same stores with the same period last year.

**CFH021 HAND TORCH revenue increased by 226.6K.** Most of the gain came from more units sold. Transactions also rose, suggesting 99.9% broader customer purchase activity. Check SKU-level sales and promotions in CFH021.

# Data Quality Watch-outs
None observed in this run.

# Evidence Trail
- Calculation detail.

# Confidence & Caveats
- Supported by the available checks.

# Suggested Follow-ups
- Review product-level performance.
"""
    issues = _clarity_issues(
        unclear_report, 1, [torch_brief], torch_supported_numbers
    )
    assert any("omits the supported percentage change" in issue for issue in issues), issues
    assert any("mentions transactions but omits its change" in issue for issue in issues), issues
    assert any("unsupported customer claim" in issue for issue in issues), issues
    assert any("unsupported figure '99.9%'" in issue for issue in issues), issues
    technical_report = clear_report.replace(
        "This added 193.5K to revenue.",
        "The mathematical decomposition assigned 193.5K to revenue.",
    )
    technical_issues = _clarity_issues(
        technical_report, 1, [torch_brief], torch_supported_numbers
    )
    assert any("analyst shorthand" in issue for issue in technical_issues), technical_issues
    no_check_report = clear_report.replace(
        "Check CFH021 HAND TORCH by product and branch to find where the change happened.",
        "",
    )
    no_check_issues = _clarity_issues(
        no_check_report, 1, [torch_brief], torch_supported_numbers
    )
    assert any("specific check" in issue for issue in no_check_issues), no_check_issues

    complex_report = clear_report.replace(
        fallback_finding,
        "**CFH021 HAND TORCH revenue rose by 226.6K (41.3%), from 549.1K to "
        "775.7K compared with the same period last year.** It accounted for 6.5% "
        "of the total movement. The uplift was spread across several product "
        "pockets, with visible gains and broader demand. Transactions increased "
        "across the leading branches. Check the product and branch breakdown.",
    )
    complex_issues = _clarity_issues(
        complex_report, 1, [torch_brief], torch_supported_numbers
    )
    assert any("analyst shorthand" in issue for issue in complex_issues), complex_issues
    assert any("unquantified supporting claim" in issue for issue in complex_issues), complex_issues

    month_signal = {
        **torch_signal,
        "affected_segment": "month=3",
        "period_label": "March",
        "dimension": "'SALES'[month]",
    }
    assert _manager_fact_brief(month_signal, profile)["segment"] == "March"

    concentration_signal = {
        "id": "division_concentration",
        "kind": "business",
        "candidate_type": "concentration",
        "affected_segment": "FARM FRESH and FMCG FOOD",
        "metric_family": "quantity",
        "impact_value": 13_644_163.0,
        "impact_share": 73.3331,
    }
    concentration_brief = _manager_fact_brief(concentration_signal, profile)
    concentration_finding = _deterministic_finding(
        concentration_signal, concentration_brief
    )
    concentration_report = clear_report.replace(fallback_finding, concentration_finding)
    assert not _clarity_issues(
        concentration_report,
        1,
        [concentration_brief],
        _supported_numbers(concentration_brief),
    )

    oversized_signal = {
        "id": "division_decline",
        "kind": "business",
        "candidate_type": "change_contribution",
        "affected_segment": "FOOD",
        "metric_family": "quantity",
        "bundle_id": "SALES::quantity",
        "evidence_query": "division_change",
        "evidence_segment": "FOOD",
        "current": 10_028_734.1561,
        "prior": 10_398_854.8761,
        "impact_value": -370_120.72,
        "impact_share": 148.1271,
        "decomposition": None,
    }
    oversized_clean_data = {
        "queries": [{
            "query_name": "division_change",
            "rows": [
                {"division": "FOOD", "QTY Growth": -370_120.72},
                {"division": "FASHION", "QTY Growth": 196_772.05},
                {"division": "FARM FRESH", "QTY Growth": -76_518.28},
            ],
        }],
    }
    oversized_brief = _manager_fact_brief(
        oversized_signal, profile, oversized_clean_data
    )
    oversized_finding = _deterministic_finding(oversized_signal, oversized_brief)
    assert "Units rose in FASHION (196.8K)" in oversized_finding
    assert "Units fell in FARM FRESH (76.5K)" in oversized_finding
    assert "other areas" not in oversized_finding.casefold()
    oversized_report = clear_report.replace(fallback_finding, oversized_finding)
    assert not _clarity_issues(
        oversized_report,
        1,
        [oversized_brief],
        _supported_numbers(oversized_brief),
    )

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
        "blocks": [
            {
                "kind": "paragraph",
                "heading": "Revenue performance",
                "text": "Revenue increased by +551.6K.",
                "points": [],
                "chart_source_id": "",
                "chart_type": "bar",
            },
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
