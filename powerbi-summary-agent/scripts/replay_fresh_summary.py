"""Offline regression for the autonomous fresh-summary path.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import argparse
import json
import copy
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import (  # noqa: E402
    fresh_summary_generator,
    fresh_summary_validator,
    summary_candidate_builder,
    summary_focus_evidence,
    summary_novelty_filter,
    summary_period_resolver,
)
from src.agents.fresh_summary_generator import _fallback  # noqa: E402
from src.tools import summary_history, summary_memory, summary_visual  # noqa: E402
from src.tools.api_payloads import generate_fresh_report_summary_payload  # noqa: E402
from src.tools.summary_validation import validate_draft  # noqa: E402


def _base_state(root: Path) -> dict:
    return {
        "dataset_id": "fixture-dataset",
        "output_folder": str(root / "outputs"),
        "summary_memory_root": str(root / "memory"),
        "summary_memory_enabled": True,
        "summary_memory_policy": "never_repeat",
        "summary_memory_cooldown_days": 14,
        "summary_resurface_change_pct": 20,
        "summary_candidates_max": 12,
        "summary_temporal_batch_share": 0.5,
        "summary_delayed_after_periods": 1,
        "summary_stale_after_periods": 2,
        "summary_now_override": "2026-07-23",
        "summary_visual_enabled": True,
        # This block is the legacy/disabled-mode regression: with focus off the
        # candidate set and summary_key rotation must reproduce prior behavior.
        "summary_focus_enabled": False,
        "summary_memory_hydration": {"status": "missing"},
        "resolved_entity_scope": {
            "active_comparable_population": ["North", "Central", "West"],
            "excluded_from_comparison": ["New Store"],
        },
        "config": {
            "summary_history_enabled": True,
            "summary_history_timezone": "Asia/Kolkata",
            "api_summary_title": "AI Summary",
        },
        "logs": [],
        "errors": [],
        "clean_summary_data": {
            "successful": 3,
            "queries": [
                {
                    "query_name": "grand_totals_overall",
                    "purpose": "Overall current, prior and change totals",
                    "status": "success",
                    "rows": [{
                        "Revenue Current": 12_255_310.14,
                        "Revenue Prior": 11_910_793.97,
                        "Revenue Growth": 344_516.17,
                        "Revenue Growth %": 0.0289,
                        "Quantity Current": 1_812_019.0,
                        "Transactions Current": 810_369,
                    }],
                },
                {
                    "query_name": "store_rank",
                    "purpose": "Comparable performance by store",
                    "status": "success",
                    "rows": [
                        {"Store": "North", "Revenue Growth": 424_051.0, "Revenue Current": 3_988_860.0},
                        {"Store": "Central", "Revenue Growth": 44_604.0, "Revenue Current": 2_428_358.0},
                        {"Store": "West", "Revenue Growth": -118_302.0, "Revenue Current": 2_040_545.0},
                    ],
                },
                {
                    "query_name": "monthly_movement",
                    "purpose": "Revenue movement by month",
                    "status": "success",
                    "rows": [
                        {"Month Date": "2023-10-31", "Revenue Growth": -91_000.0, "Revenue Current": 3_900_000.0},
                        {"Month Date": "2023-11-30", "Revenue Growth": 102_000.0, "Revenue Current": 4_050_000.0},
                        {"Month Date": "2023-12-31", "Revenue Growth": 333_516.17, "Revenue Current": 4_305_310.14},
                    ],
                },
            ],
        },
        "baseline_coverage_clean_data": {"queries": []},
    }


def _fresh_from(candidate: dict, period: dict, summary_type: str) -> dict:
    draft = _fallback(candidate, period, summary_type)
    sources = fresh_summary_generator._chart_sources([candidate])
    assert not validate_draft(draft, [candidate], chart_sources=sources)
    blocks = fresh_summary_generator._resolve_blocks(draft, sources)
    sections = fresh_summary_generator._legacy_sections(blocks)
    return {
        "summary_type": summary_type,
        "heading": draft["headline"],
        "paragraphs": [
            text for block in blocks
            for text in (
                [block["text"]] if block.get("kind") == "paragraph"
                else block.get("points", []) if block.get("kind") == "bullets"
                else []
            )
        ],
        "content_blocks": blocks,
        "sections": sections,
        "covered_candidate_ids": draft["covered_candidate_ids"],
        "covered_summary_keys": [candidate["summary_key"]],
        "metrics": [],
        "visual": None,
        "data_as_of": period.get("data_as_of"),
        "grain": period.get("grain"),
        "freshness_status": period.get("freshness_status"),
        "period_anchor": period.get("period_anchor"),
        "validation_status": "deterministic_fallback",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live-llm",
        action="store_true",
        help="Also send the synthetic fixture to the configured LLM and validate its authored summary.",
    )
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="fresh-summary-replay-") as temp:
        state = _base_state(Path(temp))

        state.update(summary_period_resolver.run(state))
        period = state["summary_period_context"]
        assert period["grain"] == "month", period
        assert period["data_as_of"] == "2023-12-31", period
        assert period["freshness_status"] == "stale", period

        state.update(summary_candidate_builder.run(state))
        candidates = state["summary_candidates"]
        angles = {candidate["angle"] for candidate in candidates}
        assert "overall_performance" in angles, angles
        assert "store_overview" in angles, angles
        assert "period_movement" in angles, angles
        assert all(candidate["summary_key"].startswith("summary:v1:") for candidate in candidates)
        assert all(candidate.get("metadata_context") for candidate in candidates)
        assert all((candidate.get("evidence") or {}).get("facts") for candidate in candidates)
        assert summary_candidate_builder._angle(
            {"purpose": "Category performance within the comparable branch population"},
            [{"Item Category": "A", "Revenue Growth": 1.0}, {"Item Category": "B", "Revenue Growth": -1.0}],
            "Item Category",
            ["Revenue Growth"],
        ) == "category_overview"

        scoped_rows, scoped = summary_candidate_builder._scope_rows(
            [
                {"Store": "North", "Revenue Growth": 10.0},
                {"Store": "New Store", "Revenue Growth": 50.0},
            ],
            "Store",
            ["Revenue Growth"],
            {
                **state,
                "semantic_model_profile": {"entity_dimension": {"column": "Store"}},
            },
            {"query_name": "scope_discovery"},
        )
        assert scoped_rows == [{"Store": "North", "Revenue Growth": 10.0}]
        assert scoped["population_status"] == "resolved_comparable_population"

        # The repair loop must preserve signed figures, reject the retired fixed
        # template, and accept a flexible narrative/chart plan.
        store_candidate = next(candidate for candidate in candidates if candidate["angle"] == "store_overview")
        chart_sources = fresh_summary_generator._chart_sources([store_candidate])
        assert chart_sources
        flexible = {
            "headline": "North led store revenue growth with a +424.1K increase",
            "blocks": [
                {
                    "kind": "bullets",
                    "heading": "Store performance",
                    "text": "",
                    "points": ["North led revenue change at +424.1K."],
                    "chart_source_id": "",
                    "chart_type": "bar",
                },
                {
                    "kind": "chart",
                    "heading": "Revenue change by store",
                    "text": "",
                    "points": [],
                    "chart_source_id": chart_sources[0]["source_id"],
                    "chart_type": chart_sources[0]["default_chart_type"],
                },
            ],
            "covered_candidate_ids": [store_candidate["candidate_id"]],
        }
        assert not validate_draft(flexible, [store_candidate], chart_sources=chart_sources)
        jargon = copy.deepcopy(flexible)
        jargon["blocks"][0]["heading"] = "Where the change happened across comparable branches"
        assert any("analyst shorthand" in error and "comparable" in error for error in validate_draft(
            jargon, [store_candidate], chart_sources=chart_sources
        )), "internal population terminology must never reach the manager-facing summary"
        numbered_month = copy.deepcopy(flexible)
        numbered_month["blocks"][0]["points"].append(
            "Revenue remained positive from month 1 through month 7."
        )
        assert any("calendar month names" in error for error in validate_draft(
            numbered_month, [store_candidate], chart_sources=chart_sources
        )), "month-of-year codes must not reach the manager-facing summary"
        no_chart = copy.deepcopy(flexible)
        no_chart["blocks"] = no_chart["blocks"][:1]
        assert any(
            "evidence-backed chart is required" in error
            for error in validate_draft(no_chart, [store_candidate], chart_sources=chart_sources)
        ), "chart-ready evidence must produce at least one chart"
        assert not validate_draft(
            no_chart, [store_candidate], chart_sources=[]
        ), "zero charts remains valid when no chart-ready dataset exists"
        long_form = copy.deepcopy(flexible)
        long_form["blocks"][0]["points"].append(
            " ".join(["This additional business context remains grounded in the same reported result."] * 40)
        )
        assert not any("word" in error.casefold() for error in validate_draft(
            long_form, [store_candidate], chart_sources=chart_sources
        )), "the flexible summary must not enforce a word ceiling"
        retired = copy.deepcopy(flexible)
        retired["blocks"][0]["heading"] = "Risks"
        assert any("fixed template heading" in error for error in validate_draft(
            retired, [store_candidate], chart_sources=chart_sources
        ))
        kpis = {**flexible, "metrics": [{"label": "Revenue", "value": "+424.1K"}]}
        assert any("KPI metric cards" in error for error in validate_draft(
            kpis, [store_candidate], chart_sources=chart_sources
        ))
        invented_chart = copy.deepcopy(flexible)
        invented_chart["blocks"][1]["chart_source_id"] = "invented:source"
        assert any("unknown source id" in error for error in validate_draft(
            invented_chart, [store_candidate], chart_sources=chart_sources
        ))
        original_get_llm = fresh_summary_generator.get_llm
        calls = []

        class _FakeLLM:
            def invoke(self, messages):
                calls.append(messages)
                if len(calls) == 1:
                    return {
                        "headline": "Store performance was led by North",
                        "blocks": [
                            {
                                "kind": "bullets",
                                "heading": "Store performance",
                                "text": "",
                                "points": ["North led revenue change at +424.1K."],
                                "chart_source_id": "",
                                "chart_type": "bar",
                            }
                        ],
                        "covered_candidate_ids": [store_candidate["candidate_id"]],
                    }
                return {
                    "headline": "North led store revenue growth with a +424.1K increase",
                    "blocks": [
                        {
                            "kind": "paragraph",
                            "heading": "Store comparison",
                            "text": "North led revenue change at +424.1K, while Central remained positive at +44.6K and West declined by -118.3K.",
                            "points": [],
                            "chart_source_id": "",
                            "chart_type": "bar",
                        },
                        {
                            "kind": "chart",
                            "heading": "Revenue change by store",
                            "text": "",
                            "points": [],
                            "chart_source_id": chart_sources[0]["source_id"],
                            "chart_type": chart_sources[0]["default_chart_type"],
                        },
                        {
                            "kind": "bullets",
                            "heading": "Comparison details",
                            "text": "",
                            "points": [
                                "Central added +44.6K while West reduced revenue by -118.3K."
                            ],
                            "chart_source_id": "",
                            "chart_type": "bar",
                        },
                    ],
                    "covered_candidate_ids": [store_candidate["candidate_id"]],
                }

        try:
            fake = _FakeLLM()
            fresh_summary_generator.get_llm = lambda *_args, **_kwargs: fake
            authored = fresh_summary_generator._invoke(state, [store_candidate])
        finally:
            fresh_summary_generator.get_llm = original_get_llm
        assert len(calls) == 2
        assert authored["authoring_mode"] == "llm"
        assert authored["validation_status"] == "validated"
        assert "only supported fact statements" in calls[1][-1]["content"]
        assert "maximum_words" not in calls[0][-1]["content"]

        if args.live_llm:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")
            live = fresh_summary_generator._invoke(state, [candidates[0]])
            assert live["authoring_mode"] == "llm"
            assert live["validation_status"] == "validated"
            print("synthetic live LLM summary:")
            print(live["headline"])
            for block in live["blocks"]:
                print(block.get("heading") or block["kind"])
                print(block.get("text") or "\n".join(block.get("points") or []))

        state.update(summary_novelty_filter.run(state))
        assert state["summary_novelty"]["summary_type"] == "new_data"
        first = state["summary_eligible_candidates"][0]
        fresh = _fresh_from(first, period, "new_data")
        payload = generate_fresh_report_summary_payload({**state, "fresh_summary": fresh})
        assert set(payload) == {"title", "generatedAt", "headline", "metrics", "sections"}
        assert payload["metrics"] == []
        assert payload["sections"]
        assert not ({"What's working", "Risks", "Recommended actions"} & {
            section["heading"] for section in payload["sections"]
        })
        facts_only_payload = generate_fresh_report_summary_payload({
            **state,
            "fresh_summary": {**fresh, "sections": [], "paragraphs": []},
        })
        assert facts_only_payload["sections"] == []
        page = summary_visual.render(fresh)
        assert "#0f9f95" in page and "background:#fff" in page
        assert '<section class="metrics' not in page and "summary-footer" in page
        assert "interactive-chart" in page and "chart-tooltip" in page and "View chart data" in page
        assert "No material downside" not in page and "emoji" not in page
        rendered_state = {**state, "fresh_summary": fresh}
        rendered_state.update(fresh_summary_validator.run(rendered_state))
        out = Path(state["output_folder"])
        assert (out / "report_summary.md").exists()
        assert (out / "report_summary.html").exists()
        assert (out / "fresh_summary.json").exists()

        commit = summary_memory.commit_summary_run(state, [first["summary_key"]], fresh)
        assert commit["status"] == "ok" and commit["committed"] == 1, commit
        state.update(summary_novelty_filter.run(state))
        assert state["summary_novelty"]["summary_type"] == "new_perspective"
        assert first["summary_key"] not in {
            candidate["summary_key"] for candidate in state["summary_eligible_candidates"]
        }

        remaining = [candidate["summary_key"] for candidate in candidates if candidate["summary_key"] != first["summary_key"]]
        summary_memory.commit_summary_run(state, remaining, fresh)
        state.update(summary_novelty_filter.run(state))
        assert state["summary_novelty"]["summary_type"] == "no_new_perspective"
        assert not state["summary_eligible_candidates"]

        changed = copy.deepcopy(state)
        changed["summary_period_context"] = {
            **period,
            "data_as_of": "2024-01-01",
        }
        changed_candidate = changed["summary_candidates"][0]
        changed_candidate["observation_value"] *= 1.5
        changed.update(summary_novelty_filter.run(changed))
        assert changed["summary_novelty"]["summary_type"] == "new_data"
        assert changed["summary_novelty"]["resurfaced"] == 1
        assert changed["summary_eligible_candidates"][0]["summary_key"] == changed_candidate["summary_key"]

        advanced = copy.deepcopy(state)
        month_rows = advanced["clean_summary_data"]["queries"][2]["rows"]
        for row in month_rows:
            row["Month Date"] = row["Month Date"].replace("2023-", "2024-")
        advanced.update(summary_period_resolver.run(advanced))
        advanced.update(summary_candidate_builder.run(advanced))
        advanced.update(summary_novelty_filter.run(advanced))
        assert advanced["summary_novelty"]["summary_type"] == "new_data"
        assert advanced["summary_eligible_candidates"]

        one = summary_history.build_entry(
            {**state, "fresh_summary": fresh},
            generated_at=datetime(2026, 7, 22, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
            run_id="run-one",
        )
        two = summary_history.build_entry(
            {**state, "fresh_summary": {**fresh, "heading": "Second view", "summary_type": "new_perspective"}},
            generated_at=datetime(2026, 7, 23, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")),
            run_id="run-two",
        )
        three = summary_history.build_entry(
            {**state, "fresh_summary": {**fresh, "heading": "Later same-day view", "summary_type": "new_perspective"}},
            generated_at=datetime(2026, 7, 23, 14, 30, tzinfo=ZoneInfo("Asia/Kolkata")),
            run_id="run-three",
        )
        feed = summary_history.build_history_response([one, two, three])
        assert feed["history"][0]["date"] == "2026-07-23"
        assert [run["time"] for run in feed["history"][0]["runs"]] == ["14:30:00", "09:00:00"]
        assert feed["history"][0]["runs"][0]["sections"] == fresh["sections"]
        merged, changed = summary_history.merge_history_response(feed, three)
        assert not changed and merged == feed
        immutable, local_feed = summary_history.write_local(
            {**state, "fresh_summary": fresh}, three
        )
        assert immutable.exists() and local_feed.exists()

        memory = json.loads(summary_memory.store_path(state).read_text(encoding="utf-8"))
        assert set(memory["records"]) == {candidate["summary_key"] for candidate in candidates}
        older = {
            **state,
            "summary_period_context": {
                **period,
                "data_as_of": "2022-12-31",
                "period_anchor": "2022-12",
            },
        }
        summary_memory.commit_summary_run(older, [], fresh)
        memory = json.loads(summary_memory.store_path(state).read_text(encoding="utf-8"))
        assert memory["watermark"] == "2023-12-31"
        assert memory["period_anchor"] == "2023-12"

        _focus_mode_checks(Path(temp))

    print("fresh summary replay: all deterministic checks passed")
    return 0


def _focus_mode_checks(temp: Path) -> None:
    """End-to-end summary branch with the daily-focus feature enabled."""
    state = _base_state(temp)
    state["summary_focus_enabled"] = True
    state["summary_memory_root"] = str(temp / "focus_memory")
    state["summary_focus_cooldown_days"] = 14
    state["summary_focus_same_dimension_gap_days"] = 2
    state["summary_focus_deep_dive_enabled"] = True

    state.update(summary_period_resolver.run(state))
    period = state["summary_period_context"]
    state.update(summary_candidate_builder.run(state))
    candidates = state["summary_candidates"]

    members = [c for c in candidates if c.get("candidate_kind") == "member"]
    broad = [c for c in candidates if c.get("candidate_kind") == "broad"]
    assert members, "focus mode must emit member-level candidates"
    assert broad, "broad candidates must remain alongside member candidates"
    assert all(str(c.get("focus_key", "")).startswith("focus:v1:") for c in candidates)
    # broad and member candidates for the same breakdown are distinct foci.
    assert not (
        {c["focus_key"] for c in members}
        & {c["focus_key"] for c in broad if not c.get("segment")}
    )

    # A member fallback must satisfy deterministic focus rules without KPI cards
    # or a fixed section template, so strict validation can never dead-end.
    member = members[0]
    member_draft = _fallback(member, period, "new_data")
    member_sources = fresh_summary_generator._chart_sources([member])
    assert not validate_draft(
        member_draft, [member], chart_sources=member_sources
    ), validate_draft(member_draft, [member], chart_sources=member_sources)
    assert member["segment"].casefold() in member_draft["headline"].casefold()

    # Deep-dive guarantees are code-enforced, not prompt-only, and the fallback
    # remains satisfiable under the stricter contract.
    deep_member = copy.deepcopy(member)
    deep_member["evidence"]["facts"].extend([
        {
            "fact_id": "DD1", "fact_kind": "deep_dive", "subject": "Subarea A",
            "metric": "Revenue contribution", "display_value": "+120", "raw_value": 120.0,
            "statement": f"Within {member['segment']}, Subarea A added +120.",
            "subject_role": "peer", "detail_role": "contributor", "coverage": "partial",
        },
        {
            "fact_id": "DD2", "fact_kind": "deep_dive", "subject": member["segment"],
            "metric": "Main driver of the change", "display_value": "+100", "raw_value": 100.0,
            "statement": f"Most of {member['segment']}'s change came from units sold (+100).",
            "subject_role": "focus", "detail_role": "driver", "coverage": "complete",
        },
    ])
    strict_fallback = _fallback(deep_member, period, "new_data")
    deep_sources = fresh_summary_generator._chart_sources([deep_member])
    assert not validate_draft(
        strict_fallback, [deep_member], chart_sources=deep_sources
    ), validate_draft(strict_fallback, [deep_member], chart_sources=deep_sources)
    assert "comparable" not in json.dumps(strict_fallback).casefold(), (
        "the deterministic fallback must translate internal population terminology"
    )

    # Live regression: a peer can be a shorter name nested inside the selected
    # focus (FRESH CHICKEN within CF-FRESH CHICKEN & PARTS). The valid focus
    # headline must pass, while a second peer mention outside the focus must
    # still be rejected.
    nested_focus = copy.deepcopy(deep_member)
    old_segment = str(nested_focus.get("segment") or "")
    nested_segment = "CF-FRESH CHICKEN & PARTS"
    nested_focus["segment"] = nested_segment
    nested_focus["title_hint"] = f"How {nested_segment} performed"
    for fact in nested_focus["evidence"]["facts"]:
        if fact.get("subject_role") == "focus":
            fact["subject"] = nested_segment
            fact["statement"] = str(fact.get("statement") or "").replace(old_segment, nested_segment)
    nested_focus["evidence"]["facts"].append({
        "fact_id": "NESTED_PEER", "fact_kind": "deep_dive", "subject": "FRESH CHICKEN",
        "metric": "Revenue contribution", "display_value": "+10", "raw_value": 10.0,
        "statement": f"Within {nested_segment}, FRESH CHICKEN added +10.",
        "subject_role": "peer", "detail_role": "supporting", "coverage": "partial",
    })
    nested_draft = _fallback(nested_focus, period, "new_data")
    nested_sources = fresh_summary_generator._chart_sources([nested_focus])
    assert not validate_draft(
        nested_draft, [nested_focus], chart_sources=nested_sources
    ), validate_draft(nested_draft, [nested_focus], chart_sources=nested_sources)
    repeated_peer = copy.deepcopy(nested_draft)
    repeated_peer["headline"] += " FRESH CHICKEN also contributed."
    assert any("another member" in error for error in validate_draft(
        repeated_peer, [nested_focus], chart_sources=nested_sources
    ))

    missing_contributor = copy.deepcopy(strict_fallback)
    for block in missing_contributor["blocks"]:
        block["points"] = [point for point in block.get("points", []) if "Subarea A" not in point]
    assert any("contributor fact" in error for error in validate_draft(
        missing_contributor, [deep_member], chart_sources=deep_sources
    ))

    causal = copy.deepcopy(strict_fallback)
    causal["blocks"][0]["points"].append("Revenue changed because of an operational decision.")
    assert any("causal" in error for error in validate_draft(causal, [deep_member], chart_sources=deep_sources))

    partial_as_complete = copy.deepcopy(strict_fallback)
    partial_as_complete["blocks"][0]["points"].append("Subarea A provides the complete breakdown.")
    assert any("complete breakdown" in error for error in validate_draft(
        partial_as_complete, [deep_member], chart_sources=deep_sources
    ))

    excluded_comparable = copy.deepcopy(strict_fallback)
    excluded_comparable["blocks"][0]["points"].append("New Store was the comparable leader.")
    assert any("excluded" in error for error in validate_draft(
        excluded_comparable, [deep_member], chart_sources=deep_sources
    ))

    # The number of charts is selected from evidence, not a fixed layout. Add
    # multiple chartable deep-dive datasets and verify any useful subset/order.
    chart_member = copy.deepcopy(deep_member)
    chart_member["evidence"]["deep_dive"] = {
        "internal_contributors": [{
            "dimension": "Category",
            "rows": [
                {"Category": "A", "Revenue Change": 120.0, "Revenue Current": 520.0, "Quantity Current": 80.0},
                {"Category": "B", "Revenue Change": -40.0, "Revenue Current": 340.0, "Quantity Current": 55.0},
                {"Category": "C", "Revenue Change": 20.0, "Revenue Current": 210.0, "Quantity Current": 30.0},
            ],
        }],
        "location": {
            "dimension": "Store",
            "completeness": "complete",
            "rows": [
                {"Store": "North", "Revenue Current": 300.0, "Revenue Prior": 255.0, "Revenue Change": 45.0, "Quantity Current": 70.0},
                {"Store": "South", "Revenue Current": 220.0, "Revenue Prior": 195.0, "Revenue Change": 25.0, "Quantity Current": 48.0},
            ],
        },
        "period_trend": {
            "dimension": "Month",
            "grain": "month",
            "rows": [
                {"Month": 1, "Revenue Current": 140.0, "Quantity Current": 34.0},
                {"Month": 2, "Revenue Current": 155.0, "Quantity Current": 37.0},
                {"Month": 3, "Revenue Current": 175.0, "Quantity Current": 41.0},
            ],
        },
    }
    variable_sources = fresh_summary_generator._chart_sources([chart_member])
    assert len(variable_sources) >= 6
    variable_fallback = _fallback(chart_member, period, "new_data")
    fallback_source_ids = [
        block["chart_source_id"]
        for block in variable_fallback["blocks"]
        if block.get("kind") == "chart"
    ]
    assert fallback_source_ids, "fallback should retain useful evidence-backed charts"
    assert not any(source_id.endswith((":multi", ":grouped")) for source_id in fallback_source_ids)
    assert sum(":contributor:" in source_id for source_id in fallback_source_ids) <= 1
    location_source = next(source for source in variable_sources if source["source_id"].endswith(":location"))
    overview_source = next(source for source in variable_sources if source["source_id"].endswith(":overview"))
    contributor_multi = next(source for source in variable_sources if source["source_id"].endswith(":contributor:0:multi"))
    trend_source = next(source for source in variable_sources if source["source_id"].endswith(":trend"))
    trend_variants = [
        source for source in variable_sources
        if source["source_id"].endswith((":trend", ":trend:multi", ":trend:grouped"))
    ]
    assert trend_variants and all(
        source["labels"] == ["January", "February", "March"]
        for source in trend_variants
    ), "every trend chart encoding must display month names"
    assert "donut" in location_source["allowed_chart_types"]
    assert {"scatter", "bubble", "heatmap"} <= set(contributor_multi["allowed_chart_types"])
    assert {"line", "area"} <= set(trend_source["allowed_chart_types"])
    chosen_blocks = [{
        "kind": "bullets", "heading": "Performance detail", "text": "",
        "points": strict_fallback["blocks"][0]["points"],
        "chart_source_id": "", "chart_type": "bar",
    }]
    for source, chart_type in (
        (location_source, "donut"),
        (overview_source, overview_source["default_chart_type"]),
    ):
        chosen_blocks.append({
            "kind": "chart", "heading": source["title"], "text": "", "points": [],
            "chart_source_id": source["source_id"],
            "chart_type": chart_type,
        })
    variable_draft = {
        "headline": strict_fallback["headline"],
        "blocks": chosen_blocks,
        "covered_candidate_ids": [chart_member["candidate_id"]],
    }
    assert not validate_draft(variable_draft, [chart_member], chart_sources=variable_sources)
    resolved = fresh_summary_generator._resolve_blocks(variable_draft, variable_sources)
    assert sum(block["kind"] == "chart" for block in resolved) == 2
    variable_page = summary_visual.render({
        "heading": variable_draft["headline"], "content_blocks": resolved,
        "data_as_of": period["data_as_of"], "grain": period["grain"],
        "freshness_status": period["freshness_status"],
    })
    assert variable_page.count('class="chart interactive-chart"') == 2
    assert "donut-layout" in variable_page
    assert "chart-tooltip" in variable_page and "View chart data" in variable_page

    contributor_source = next(
        source for source in variable_sources if source["source_id"].endswith(":contributor:0")
    )
    location_grouped = next(
        source for source in variable_sources if source["source_id"].endswith(":location:grouped")
    )
    assert {"horizontal_bar", "lollipop", "waterfall"} <= set(contributor_source["allowed_chart_types"])
    assert location_grouped["allowed_chart_types"] == ["grouped_bar"]
    catalog = [
        (overview_source, "bar"),
        (contributor_source, "horizontal_bar"),
        (contributor_source, "lollipop"),
        (contributor_source, "waterfall"),
        (trend_source, "line"),
        (trend_source, "area"),
        (location_source, "donut"),
        (contributor_multi, "scatter"),
        (contributor_multi, "bubble"),
        (contributor_multi, "heatmap"),
        (location_grouped, "grouped_bar"),
    ]
    narrative_block = next(
        block for block in fresh_summary_generator._resolve_blocks(strict_fallback, variable_sources)
        if block.get("kind") != "chart"
    )
    for source, chart_type in catalog:
        assert chart_type in source["allowed_chart_types"]
        unresolved = {
            "blocks": [{
                "kind": "chart", "heading": source["title"], "text": "", "points": [],
                "chart_source_id": source["source_id"], "chart_type": chart_type,
            }]
        }
        block = fresh_summary_generator._resolve_blocks(unresolved, variable_sources)[0]
        # The final validator reads resolved series rather than source ids. In
        # particular grouped bars are series-backed and have no flat `values`.
        resolved_draft = {
            "heading": strict_fallback["headline"],
            "content_blocks": [narrative_block, block],
            "covered_candidate_ids": [chart_member["candidate_id"]],
        }
        assert not validate_draft(
            resolved_draft, [chart_member]
        ), (chart_type, validate_draft(resolved_draft, [chart_member]))
        page = summary_visual.render({
            "heading": "Chart catalogue", "content_blocks": [block],
            "data_as_of": period["data_as_of"], "grain": period["grain"],
            "freshness_status": period["freshness_status"],
        })
        assert f'data-chart-type="{chart_type}"' in page, chart_type
        assert "data-point" in page and "View chart data" in page, chart_type

    incompatible = copy.deepcopy(variable_draft)
    incompatible["blocks"][1]["chart_source_id"] = location_source["source_id"]
    incompatible["blocks"][1]["chart_type"] = "bubble"
    assert any("not allowed" in error for error in validate_draft(
        incompatible, [chart_member], chart_sources=variable_sources
    ))

    state.update(summary_novelty_filter.run(state))
    novelty = state["summary_novelty"]
    assert novelty["status"] == "ok" and novelty.get("mode") == "focus", novelty
    selected_focus = state["summary_selected_focus"]
    assert selected_focus.get("focus_key"), selected_focus

    # Deep-dive node is non-fatal even with no token / no profile in this fixture.
    state.update(summary_focus_evidence.run(state))

    selected = state["summary_eligible_candidates"][0]
    fresh = _fresh_from(selected, period, novelty["summary_type"])
    fresh["focus"] = {
        "focus_key": selected_focus["focus_key"],
        "segment": selected_focus.get("segment"),
        "dimension_role": selected_focus.get("dimension_role"),
        "lens": selected_focus.get("lens"),
    }
    history_entry = summary_history.build_entry({**state, "fresh_summary": fresh})
    assert history_entry and history_entry.get("focus") == fresh["focus"]
    commit = summary_memory.commit_summary_run(state, fresh["covered_summary_keys"], fresh)
    assert commit["status"] == "ok", commit
    assert commit.get("focus_committed") == selected_focus["focus_key"]

    store = json.loads(summary_memory.store_path(state).read_text(encoding="utf-8"))
    assert store["schema_version"] == 5  # v5 (WP4): adds state_records
    assert selected_focus["focus_key"] in store["focus_records"], "commit must persist focus_records"
    today = state["summary_now_override"]
    assert today in store["daily_plan"], "commit must record the same-day plan"

    # Same-day re-run pins the same focus (never evicted by summary_key).
    state.update(summary_novelty_filter.run(state))
    assert state["summary_novelty"]["audit"].get("recovered_same_day") is True
    assert state["summary_selected_focus"]["focus_key"] == selected_focus["focus_key"]

    # A later day rotates to a different focus (cooldown + role gap).
    next_day = {**state, "summary_now_override": "2026-07-24"}
    next_day.update(summary_novelty_filter.run(next_day))
    rotated = next_day["summary_selected_focus"]
    assert rotated.get("focus_key") and rotated["focus_key"] != selected_focus["focus_key"]
    print("focus mode: member candidates, selection, deep-dive, pin, rotation  OK")


if __name__ == "__main__":
    raise SystemExit(main())
