"""Offline 7-date rotation simulation for the R4 balanced summary (Phase 6).

Runs the full summary chain (universe -> candidates -> overall -> portfolio
selection -> generator -> commit) across seven consecutive dates against one
persistent Summary Memory, and verifies:

* Overall Performance is always the first block;
* focuses rotate (the min-repeat gap prevents an area on two consecutive days);
* every significant area is covered within the window (broad weekly coverage);
* same-day reruns pin the identical portfolio.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import (  # noqa: E402
    fresh_summary_generator,
    summary_candidate_builder,
    summary_novelty_filter,
    summary_overall_performance,
)
from src.tools import summary_memory  # noqa: E402


def _members(specs, division):
    changes = [current - prior for _, current, prior in specs]
    gross = sum(abs(change) for change in changes)
    signed = sum(changes)
    out = []
    for (name, current, prior), change in zip(specs, changes):
        out.append({
            "member": name, "hierarchy_path": [division, name],
            "current": float(current), "prior": float(prior), "change": float(change),
            "change_pct": (change / abs(prior) * 100 if prior else None),
            "overall_current": 10000.0, "gross_sibling_change": float(gross),
            "signed_sibling_change": float(signed), "parent_change": float(signed),
            "full_member_count": len(specs),
        })
    return out


def _universe():
    return {"status": "ok", "metric_family": "revenue", "roles": {
        "category": {"status": "ok", "role": "category", "column": "item_category_name",
                     "metric_family": "revenue", "members":
                     _members([("A", 2000, 1800), ("B", 1500, 1350), ("C", 800, 900)], "FMCG FOOD")
                     + _members([("D", 1800, 1620), ("E", 1200, 1080), ("F", 700, 790)], "GM")},
    }}


def _state(memory_root, day):
    return {
        "dataset_id": "rotation", "output_folder": str(Path(memory_root) / "out"),
        "summary_memory_root": str(memory_root), "summary_memory_enabled": True,
        "summary_memory_hydration": {"status": "missing"}, "summary_r4_enabled": True,
        "summary_llm_authoring_enabled": False,
        "summary_focus_enabled": True, "summary_now_override": day, "summary_visual_enabled": True,
        # Isolate the rotation mechanism (repeat-gap + coverage-debt): a 1-day
        # fact-overlap window lets an area re-cover after the 2-day gap, rather
        # than the default 7-day window suppressing every recently told story
        # (which, with static data + few areas, correctly yields fewer focuses).
        "summary_focus_overlap_window_days": 1, "summary_focus_min_repeat_gap_days": 2,
        "semantic_model_profile": {}, "resolved_entity_scope": {},
        "summary_period_context": {"period_anchor": "2026-08", "data_as_of": "2026-08-01",
                                   "grain": "month", "checks": []},
        "summary_focus_universe": _universe(), "config": {}, "logs": [], "errors": [],
        "clean_summary_data": {"queries": [
            {"query_name": "grand_totals", "purpose": "Overall totals", "status": "success", "rows": [{
                "Revenue Current": 12000.0, "Revenue Prior": 10000.0, "Revenue Growth": 2000.0,
                "Quantity Current": 1100.0, "Quantity Prior": 1000.0, "Quantity Growth": 100.0}]},
        ]},
        "baseline_coverage_clean_data": {"queries": []},
    }


def _run_day(memory_root, day):
    state = _state(memory_root, day)
    state.update(summary_candidate_builder.run(state))
    state.update(summary_overall_performance.run(state))
    state.update(summary_novelty_filter.run(state))
    state["summary_focus_evidence_by_key"] = {}
    state.update(fresh_summary_generator.run(state))
    return state


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="r4-rotation-") as tmp:
        start = date(2026, 8, 1)
        days = [(start + timedelta(days=offset)).isoformat() for offset in range(7)]
        covered_by_day: dict[str, set] = {}
        all_areas: set = set()

        for day in days:
            state = _run_day(tmp, day)
            fresh = state["fresh_summary"]
            bullet_headings = [b.get("heading") for b in fresh["content_blocks"] if b.get("kind") == "bullets"]
            assert bullet_headings and bullet_headings[0] == "Overall Performance", (day, bullet_headings)

            selected = state["summary_selected_focuses"]
            assert len(selected) <= 3, (day, len(selected))
            areas = {focus["area_key"] for focus in selected}
            covered_by_day[day] = areas
            all_areas |= areas

            # commit writes the same-day plan + area coverage for the next day
            covered_keys = [focus["summary_key"] for focus in selected]
            fresh_stub = {"summary_type": fresh["summary_type"], "heading": fresh["heading"],
                          "covered_summary_keys": covered_keys}
            commit = summary_memory.commit_summary_run(state, covered_keys, fresh_stub)
            assert commit["status"] == "ok", (day, commit)

            # a same-day rerun now pins the identical committed portfolio
            rerun = summary_novelty_filter.run(state)
            assert rerun["summary_novelty"]["recovered_same_day"] is True, day
            assert {f["area_key"] for f in rerun["summary_selected_focuses"]} == areas, day

        # No area appears on two consecutive days (min-repeat gap of 2).
        for earlier, later in zip(days, days[1:]):
            overlap = covered_by_day[earlier] & covered_by_day[later]
            assert not overlap, f"area repeated on consecutive days {earlier}->{later}: {overlap}"

        # Every significant area was covered within the week (all 6 rotate in).
        with tempfile.TemporaryDirectory(prefix="r4-rot-probe-") as probe:
            eligible_areas = {
                candidate["area_key"] for candidate in _run_day(probe, days[0])["summary_candidates"]
                if candidate.get("candidate_source") == "universe"
            }
        assert eligible_areas <= all_areas, f"uncovered significant areas: {eligible_areas - all_areas}"
        assert len(all_areas) == 6, len(all_areas)

    print(f"rotation sim: 7 dates, Overall-first always, {len(all_areas)} areas rotated, no consecutive repeats  OK")
    print("summary rotation replay: all deterministic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
