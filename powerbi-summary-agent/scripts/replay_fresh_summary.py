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

from src.agents import fresh_summary_generator, fresh_summary_validator, summary_candidate_builder, summary_novelty_filter, summary_period_resolver
from src.agents.fresh_summary_generator import _fallback
from src.tools import summary_history, summary_memory, summary_visual
from src.tools.api_payloads import generate_fresh_report_summary_payload
from src.tools.summary_validation import validate_draft


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
    assert not validate_draft(draft, [candidate])
    metrics = fresh_summary_generator._resolve_metrics(draft, [candidate])
    sections = fresh_summary_generator._resolve_sections(draft)
    return {
        "summary_type": summary_type,
        "heading": draft["headline"],
        "paragraphs": [point for section in sections for point in section["points"]],
        "sections": sections,
        "covered_candidate_ids": draft["covered_candidate_ids"],
        "covered_summary_keys": [candidate["summary_key"]],
        "metrics": metrics,
        "visual": candidate.get("visual"),
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

        # The repair loop must preserve signed figures and still return an
        # LLM-authored draft rather than dropping to a deterministic summary.
        store_candidate = next(candidate for candidate in candidates if candidate["angle"] == "store_overview")
        metric_selections = [
            {"fact_id": fact["fact_id"], "label": f"{fact['subject']} {fact['metric']}"}
            for fact in (store_candidate.get("evidence") or {}).get("facts", [])
            if fact.get("display_value")
        ][:4]
        assert len(metric_selections) == 4
        optional_sections = {
            "headline": "North led comparable store revenue growth with a +424.1K increase",
            "metrics": metric_selections,
            "sections": [
                {
                    "heading": "What's working",
                    "points": ["North led comparable revenue change at +424.1K."],
                }
            ],
            "covered_candidate_ids": [store_candidate["candidate_id"]],
        }
        assert not validate_draft(optional_sections, [store_candidate])
        assert not validate_draft({**optional_sections, "sections": []}, [store_candidate])
        placeholder = copy.deepcopy(optional_sections)
        placeholder["sections"] = [
            {"heading": "Risks", "points": ["No material downside is visible."]}
        ]
        assert any(
            "omit the unsupported section" in error
            for error in validate_draft(placeholder, [store_candidate])
        )
        original_get_llm = fresh_summary_generator.get_llm
        calls = []

        class _FakeLLM:
            def invoke(self, messages):
                calls.append(messages)
                if len(calls) == 1:
                    return {
                        "headline": "Comparable store performance was led by North",
                        "metrics": metric_selections,
                        "sections": [
                            {
                                "heading": "What's working",
                                "points": ["North led comparable revenue change at +424.1K."],
                            },
                            {
                                "heading": "Risks",
                                "points": ["West recorded +118.3K for revenue change."],
                            },
                            {
                                "heading": "Recommended actions",
                                "points": ["Review West's performance against North and Central."],
                            },
                        ],
                        "covered_candidate_ids": [store_candidate["candidate_id"]],
                    }
                return {
                    "headline": "North led comparable store revenue growth with a +424.1K increase",
                    "metrics": metric_selections,
                    "sections": [
                        {
                            "heading": "What's working",
                            "points": [
                                "North led comparable revenue change at +424.1K, while Central remained positive at +44.6K."
                            ],
                        },
                        {
                            "heading": "Risks",
                            "points": ["West declined by -118.3K for revenue change."],
                        },
                        {
                            "heading": "Recommended actions",
                            "points": [
                                "Review West's performance against North and Central to confirm where the gap is concentrated."
                            ],
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

        if args.live_llm:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")
            live = fresh_summary_generator._invoke(state, [candidates[0]])
            assert live["authoring_mode"] == "llm"
            assert live["validation_status"] == "validated"
            print("synthetic live LLM summary:")
            print(live["headline"])
            for section in live["sections"]:
                print(section["heading"])
                print("\n".join(section["points"]))

        state.update(summary_novelty_filter.run(state))
        assert state["summary_novelty"]["summary_type"] == "new_data"
        first = state["summary_eligible_candidates"][0]
        fresh = _fresh_from(first, period, "new_data")
        payload = generate_fresh_report_summary_payload({**state, "fresh_summary": fresh})
        assert set(payload) == {"title", "generatedAt", "headline", "metrics", "sections"}
        assert len(payload["metrics"]) == 4
        payload_headings = [section["heading"] for section in payload["sections"]]
        expected_order = ["What's working", "Risks", "Recommended actions"]
        assert payload_headings == [heading for heading in expected_order if heading in payload_headings]
        facts_only_payload = generate_fresh_report_summary_payload({
            **state,
            "fresh_summary": {**fresh, "sections": [], "paragraphs": []},
        })
        assert facts_only_payload["sections"] == []
        assert all(isinstance(metric["value"], str) for metric in payload["metrics"])
        page = summary_visual.render(fresh)
        assert "#0f9f95" in page and "background:#fff" in page and "metric-value" in page
        assert "section-icon" in page and "summary-footer" in page
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

    print("fresh summary replay: all deterministic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
