"""Offline regression for the R4 universe DAX/parser + materiality + selector.

No Power BI, Azure, or LLM credentials are required. Covers the correctness
cases that must hold before the live universe probe: per-parent broadcast
diagnostics, the exact materiality formulas, global-impact cross-level ranking,
low-impact/large-% exclusion, divide-by-max normalization, and the
filter -> seed -> diverse greedy fill portfolio selector.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import summary_focus_queries as q  # noqa: E402
from src.tools import summary_materiality as m  # noqa: E402
from src.tools import summary_memory  # noqa: E402
from src.tools import summary_portfolio  # noqa: E402


def _cand(role, path, current, prior, *, overall=1000.0, gross=None,
          parent_change=None, full=5, peers=(), coverage="partial", direction=None):
    change = current - prior
    parent_change = change if parent_change is None else parent_change
    gross = abs(change) if gross is None else gross
    segment = path[-1]
    facts = [{"subject": segment, "subject_role": "focus"}]
    facts += [{"subject": peer, "subject_role": "peer"} for peer in peers]
    cand = {
        "candidate_kind": "member",
        "dimension_role": role,
        "dimension": role.title(),
        "segment": segment,
        "metric_family": "revenue",
        "hierarchy_path": list(path),
        "coverage": coverage,
        "direction": direction or ("increase" if change > 0 else "decrease" if change < 0 else "flat"),
        "current": float(current),
        "prior": float(prior),
        "change": float(change),
        "observation_value": float(change),
        "overall_current": float(overall),
        "gross_sibling_change": float(gross),
        "signed_sibling_change": float(parent_change),
        "parent_change": float(parent_change),
        "full_member_count": full,
        "evidence": {"facts": facts},
    }
    cand["area_key"], _ = summary_memory.area_components(cand, "pf")
    cand["focus_key"], _ = summary_memory.focus_components(cand, "pf")
    return cand


def test_dax_builder():
    scan = q.universe_scan(
        "summary_universe_category", "Category universe",
        group_col_ref="'Dim'[Category]",
        parent_col_refs=["'Dim'[Division]", "'Dim'[Department]"],
        filters=["TREATAS({\"North\",\"West\"}, 'Store'[Store])"],
        current_measure="Revenue Current", prior_measure="Revenue Prior",
        change_measure="Revenue Growth", pool_rows=30,
    )
    dax = scan["dax"]
    assert dax.startswith("EVALUATE\nTOPN(30,")
    assert "SUMMARIZECOLUMNS('Dim'[Division], 'Dim'[Department], 'Dim'[Category]" in dax
    assert "TREATAS(" in dax
    # per-parent: sibling gross removes ONLY the leaf, parents stay in context.
    assert "SUMX(VALUES('Dim'[Category]), ABS([Revenue Growth]))" in dax
    assert "REMOVEFILTERS('Dim'[Category])" in dax
    assert "__gross_sibling_change" in dax and "__overall_current" in dax
    # overall removes the whole path.
    assert "REMOVEFILTERS('Dim'[Division]), REMOVEFILTERS('Dim'[Department]), REMOVEFILTERS('Dim'[Category])" in dax
    # no change measure -> additive difference.
    scan2 = q.universe_scan(
        "u", "u", "'D'[Cat]", [], [], "Cur", "Pri", None, 10,
    )
    assert "([Cur] - [Pri])" in scan2["dax"]
    print("  dax builder: per-parent diagnostics, TOPN, additive fallback  OK")


def test_parser():
    rows = [
        {"Category": "Meat", "Department": "Fresh", "__cur": 300, "__pri": 100, "__chg": 200,
         "__gross_sibling_change": 260, "__signed_sibling_change": 220, "__parent_change": 220,
         "__overall_current": 1000, "__full_member_count": 4},
        {"Category": "Dairy", "Department": "Fresh", "__cur": 80, "__pri": 100, "__chg": -20,
         "__gross_sibling_change": 260, "__signed_sibling_change": 220, "__parent_change": 220,
         "__overall_current": 1000, "__full_member_count": 4},
    ]
    parsed = m.parse_universe_rows(rows, "Category", ["Department"], tolerance_pct=2.0, pool_rows=2)
    assert parsed["returned_member_count"] == 2
    # per-parent sibling count is surfaced honestly; pool_capped signals TOPN hit the cap.
    assert parsed["max_siblings_per_parent"] == 4 and parsed["pool_capped"] is True
    assert m.parse_universe_rows(rows, "Category", ["Department"], pool_rows=30)["pool_capped"] is False
    assert parsed["diagnostics_reconciled"] is True
    meat = parsed["members"][0]
    assert meat["hierarchy_path"] == ["Fresh", "Meat"]
    assert abs(meat["global_impact_pct"] - 20.0) < 1e-9      # 200/1000
    assert abs(meat["business_share_pct"] - 30.0) < 1e-9     # 300/1000
    assert abs(meat["sibling_movement_impact_pct"] - (200 / 260 * 100)) < 1e-9
    # table-qualified result keys are tolerated.
    q_rows = [{"Dim[Category]": "X", "Dim[Department]": "Y", "__cur": 10, "__pri": 5, "__chg": 5,
               "__gross_sibling_change": 5, "__signed_sibling_change": 5, "__parent_change": 5,
               "__overall_current": 100, "__full_member_count": 1}]
    assert m.parse_universe_rows(q_rows, "Category", ["Department"])["members"][0]["member"] == "X"
    # unreconciled breakdown -> sibling impact withheld (business-share route only).
    bad = [{"Category": "Z", "Department": "F", "__cur": 50, "__pri": 40, "__chg": 10,
            "__gross_sibling_change": 40, "__signed_sibling_change": 10, "__parent_change": 90,
            "__overall_current": 500, "__full_member_count": 3}]
    parsed_bad = m.parse_universe_rows(bad, "Category", ["Department"], tolerance_pct=2.0)
    assert parsed_bad["members"][0]["sibling_movement_impact_pct"] is None
    assert parsed_bad["diagnostics_reconciled"] is False
    print("  parser: per-parent facts, path, truncation, reconciliation gate  OK")


def test_role_alias_and_related_table_ancestry():
    from src.agents import summary_focus_universe

    profile = {"dimensions": [
        {"table": "Merch", "column": "Business Unit", "reference": "'Merch'[Business Unit]", "score": 90},
        {"table": "Dept", "column": "Department", "reference": "'Dept'[Department]", "score": 85},
        {"table": "Merch", "column": "Item Category", "reference": "'Merch'[Item Category]", "score": 80},
    ]}
    state = {
        "summary_focus_role_aliases": {"business unit": "division"},
        "model_metadata": {"relationships": [{
            "from_table": "Merch", "to_table": "Dept", "is_active": True,
        }]},
    }
    roles = summary_focus_universe._resolve_role_columns(profile, state)
    assert set(roles) == {"division", "department", "category"}, roles
    assert roles["department"]["parent_refs"] == ["'Merch'[Business Unit]"]
    assert roles["category"]["parent_refs"] == [
        "'Merch'[Business Unit]", "'Dept'[Department]",
    ]
    print("  roles: config alias + related-table full ancestry  OK")


def test_path_scoped_portfolio_identity():
    from src.agents import summary_candidate_builder

    def member(parent):
        return {
            "member": "Other", "hierarchy_path": [parent, "Other"],
            "current": 100.0, "prior": 80.0, "change": 20.0,
            "change_pct": 25.0, "overall_current": 1000.0,
            "gross_sibling_change": 40.0, "signed_sibling_change": 20.0,
            "parent_change": 20.0, "full_member_count": 2,
        }

    state = {
        "dataset_id": "dup-path", "summary_r4_enabled": True,
        "summary_focus_enabled": True,
        "summary_period_context": {"period_anchor": "2026-08", "checks": []},
        "summary_focus_universe": {"status": "ok", "metric_family": "revenue", "roles": {
            "category": {"status": "ok", "role": "category", "column": "Category",
                         "metric_family": "revenue", "members": [member("Food"), member("Nonfood")]},
        }},
        "clean_summary_data": {"queries": []}, "baseline_coverage_clean_data": {"queries": []},
        "semantic_model_profile": {}, "resolved_entity_scope": {},
    }
    candidates = [
        candidate for candidate in summary_candidate_builder.build_candidates(state)
        if candidate.get("candidate_source") == "universe"
    ]
    assert len(candidates) == 2, candidates
    assert len({candidate["area_key"] for candidate in candidates}) == 2
    assert len({candidate["focus_key"] for candidate in candidates}) == 2
    assert all(candidate["focus_key"].startswith("focus:v2:") for candidate in candidates)
    assert len({candidate["candidate_id"] for candidate in candidates}) == 2
    print("  identity: duplicate leaves under different parents survive distinctly  OK")


def test_materiality_formulas():
    # Category outranks an offsetting parent through global impact.
    facts_cat = m.compute_facts(
        {"current": 300, "prior": 100, "overall_current": 1000,
         "gross_sibling_change": 260, "signed_sibling_change": 220, "parent_change": 220, "full_member_count": 4})
    facts_div = m.compute_facts(
        {"current": 600, "prior": 550, "overall_current": 1000,
         "gross_sibling_change": 350, "signed_sibling_change": 50, "parent_change": 50, "full_member_count": 2})
    assert facts_cat["global_impact_pct"] > facts_div["global_impact_pct"]  # 20% vs 5%
    assert facts_div["business_share_pct"] > facts_cat["business_share_pct"]  # 60% vs 30%
    # Low-impact, large-% area is excluded (tiny base).
    tiny = m.compute_facts(
        {"current": 2, "prior": 1, "overall_current": 1000,
         "gross_sibling_change": 500, "signed_sibling_change": 500, "parent_change": 500, "full_member_count": 6})
    assert tiny["area_change_pct"] == 100.0 and tiny["business_share_pct"] == 0.2
    assert not m.is_eligible(tiny, min_movement_pct=5, min_business_share_pct=5, min_change_pct=3)
    assert m.is_eligible(facts_cat, min_movement_pct=5, min_business_share_pct=5, min_change_pct=3)
    # divide-by-max, including a zero maximum.
    assert m.divide_by_max([10, 5, None, 0]) == [1.0, 0.5, 0.0, 0.0]
    assert m.divide_by_max([0, 0]) == [0.0, 0.0]
    # meaningful movement undefined when prior is zero.
    assert m.area_change_pct(5, 0) is None
    print("  materiality: global-impact ranking, tiny-base exclusion, normalization  OK")


def test_selector_ranking_and_diversity():
    st = {}  # all thresholds default
    today = date(2026, 8, 1)
    # Non-parent-child: category (high global impact) must rank above a bigger,
    # flatter division.
    cat = _cand("category", ["food", "meat", "fresh meat"], 300, 100, gross=260, parent_change=200)
    div = _cand("division", ["nonfood"], 600, 550, gross=350, parent_change=50)
    out = summary_portfolio.select_portfolio(st, [div, cat], today=today)
    assert [s["segment"] for s in out["selected"]][0] == "fresh meat", out["audit"]

    # Parent-child suppression: a Division and its own Category cannot both be slots.
    food_div = _cand("division", ["food"], 500, 300, gross=400, parent_change=200)
    food_cat = _cand("category", ["food", "meat", "beef"], 260, 100, gross=260, parent_change=160)
    out2 = summary_portfolio.select_portfolio(st, [food_div, food_cat], today=today)
    picked = [s["area_key"] for s in out2["selected"]]
    assert len(picked) == 1, "parent and its descendant must not occupy two slots"
    assert food_cat["area_key"] in [r["area_key"] for r in out2["reserves"]] or \
        food_div["area_key"] in [r["area_key"] for r in out2["reserves"]]

    # Two-or-three without padding: only two eligible diverse areas -> two focuses.
    a = _cand("category", ["food", "meat", "beef"], 300, 100, gross=260)
    b = _cand("category", ["nonfood", "home", "kitchen"], 250, 120, gross=240)
    out3 = summary_portfolio.select_portfolio(st, [a, b], today=today)
    assert len(out3["selected"]) == 2, "must not pad to the target count"

    # Ineligible tiny area never selected.
    tiny = _cand("category", ["food", "snacks", "gum"], 2, 1, gross=500, full=8)
    out4 = summary_portfolio.select_portfolio(st, [a, b, tiny], today=today)
    assert tiny["area_key"] not in [s["area_key"] for s in out4["selected"]]

    # A helper level that is a one-for-one copy of its parent is not a fresh
    # business area and must not consume a rotation slot.
    collapsed = _cand(
        "department", ["food", "food"], 500, 300,
        gross=200, parent_change=200, full=1,
    )
    out5 = summary_portfolio.select_portfolio(st, [a, collapsed], today=today)
    assert collapsed["area_key"] not in [s["area_key"] for s in out5["selected"]]
    assert out5["audit"]["dropped"]["collapsed_hierarchy"] == 1
    print("  selector: global ranking, parent-child, no-pad, gate  OK")


def test_selector_rotation_and_override():
    st = {}
    today = date(2026, 8, 1)
    a = _cand("category", ["food", "meat", "beef"], 300, 100, gross=260)
    b = _cand("category", ["nonfood", "home", "kitchen"], 300, 100, gross=260)
    # Equal materiality; b covered yesterday (low debt), a never covered -> a first.
    coverage = {b["area_key"]: {"last_covered": "2026-07-31", "times": 3}}
    out = summary_portfolio.select_portfolio(st, [a, b], coverage=coverage, today=today)
    assert out["selected"][0]["area_key"] == a["area_key"], "max coverage debt ranks first"

    # Repeat gap blocks a just-covered area, UNLESS it reversed direction.
    recent = _cand("category", ["food", "meat", "beef"], 80, 200, gross=260, direction="decrease")
    cov = {recent["area_key"]: {"last_covered": "2026-07-31", "times": 2, "last_direction": "increase"}}
    blocked = summary_portfolio.select_portfolio(st, [recent], coverage=cov, today=today)
    # reversal override admits it despite the gap (stored increase -> now decrease).
    assert len(blocked["selected"]) == 1 and blocked["selected"][0]["selection"]["reversal"] is True
    # same area, same direction -> gap suppresses it.
    same_dir = _cand("category", ["food", "meat", "beef"], 320, 100, gross=260, direction="increase")
    cov2 = {same_dir["area_key"]: {"last_covered": "2026-07-31", "times": 2, "last_direction": "increase"}}
    out2 = summary_portfolio.select_portfolio(st, [same_dir], coverage=cov2, today=today)
    assert not out2["selected"], "recently covered same-direction area is gap-suppressed"

    # Preserve R2's magnitude override semantics: the second threshold is the
    # area's share of a reconciled overall change, not change/current-value.
    magnitude = _cand(
        "category", ["food", "grocery", "oil"], 1300, 1000,
        overall=100000, gross=500, parent_change=300,
    )
    overall = {
        "candidate_kind": "broad", "dimension_role": "overall",
        "coverage": "complete", "metric_family": "revenue",
        "observation_value": 1000.0,
    }
    mag_cov = {
        magnitude["area_key"]: {
            "last_covered": "2026-07-31", "last_direction": "increase",
        },
    }
    mag = summary_portfolio.select_portfolio(
        st, [overall, magnitude], coverage=mag_cov, today=today, data_advanced=True,
    )
    assert mag["selected"] and mag["selected"][0]["selection"]["magnitude"] is True
    assert abs(mag["selected"][0]["materiality_facts"]["impact_share_pct"] - 30.0) < 1e-9

    # Fact overlap expires at the configured recent-story window.  A delivery
    # from yesterday suppresses the identical story; an older one does not.
    overlap_state = {
        "summary_focus_min_repeat_gap_days": 0,
        "summary_focus_overlap_window_days": 1,
    }
    yesterday = [{"segment": same_dir["segment"], "reported_at": "2026-07-31"}]
    older = [{"segment": same_dir["segment"], "reported_at": "2026-07-30"}]
    suppressed = summary_portfolio.select_portfolio(
        overlap_state, [same_dir], recent_focus=yesterday, today=today,
    )
    expired = summary_portfolio.select_portfolio(
        overlap_state, [same_dir], recent_focus=older, today=today,
    )
    assert not suppressed["selected"], "in-window fact overlap must suppress the repeated story"
    assert expired["selected"], "expired fact overlap must not suppress a valid focus forever"
    print("  selector: coverage-debt rotation, repeat gap, reversal, overlap expiry  OK")


def _universe_fixture():
    return {"status": "ok", "metric_family": "revenue", "roles": {
        "category": {"status": "ok", "role": "category", "column": "item_category_name", "metric_family": "revenue", "members": [
            {"member": "CF-FROZEN FOOD", "hierarchy_path": ["FMCG FOOD", "CF-FROZEN FOOD"], "current": 500, "prior": 300,
             "change": 200, "change_pct": 66.7, "overall_current": 10000, "gross_sibling_change": 260,
             "signed_sibling_change": 200, "parent_change": 200, "full_member_count": 4},
            {"member": "CF-BAKERY", "hierarchy_path": ["FMCG FOOD", "CF-BAKERY"], "current": 100, "prior": 105,
             "change": -5, "change_pct": -4.8, "overall_current": 10000, "gross_sibling_change": 260,
             "signed_sibling_change": 200, "parent_change": 200, "full_member_count": 4},
        ]},
        "division": {"status": "ok", "role": "division", "column": "division_name", "metric_family": "revenue", "members": [
            {"member": "GM FASHION", "hierarchy_path": ["GM FASHION"], "current": 2000, "prior": 1500, "change": 500,
             "change_pct": 33.3, "overall_current": 10000, "gross_sibling_change": 800, "signed_sibling_change": 500,
             "parent_change": 500, "full_member_count": 3},
            {"member": "FASHION", "hierarchy_path": ["FASHION"], "current": 3000, "prior": 2900, "change": 100,
             "change_pct": 3.4, "overall_current": 10000, "gross_sibling_change": 800, "signed_sibling_change": 500,
             "parent_change": 500, "full_member_count": 3},
        ]},
    }}


def test_r4_end_to_end():
    import json as _json
    import tempfile

    from src.agents import (
        fresh_summary_generator,
        fresh_summary_validator,
        summary_candidate_builder,
        summary_novelty_filter,
        summary_overall_performance,
    )

    with tempfile.TemporaryDirectory(prefix="r4-e2e-") as tmp:
        root = Path(tmp)
        state = {
            "dataset_id": "r4e2e", "output_folder": str(root / "out"), "summary_memory_root": str(root / "mem"),
            "summary_memory_enabled": True, "summary_memory_hydration": {"status": "missing"},
            "summary_r4_enabled": True, "summary_llm_authoring_enabled": False,
            "summary_focus_enabled": True, "summary_now_override": "2026-08-01",
            "semantic_model_profile": {}, "resolved_entity_scope": {},
            "summary_period_context": {"period_anchor": "2026-08", "data_as_of": "2026-08-01", "grain": "month", "checks": []},
            "summary_focus_universe": _universe_fixture(), "config": {}, "logs": [], "errors": [],
            "summary_visual_enabled": True,
            "clean_summary_data": {"queries": [
                {"query_name": "grand_totals", "purpose": "Overall totals", "status": "success", "rows": [{
                    "Revenue Current": 12000.0, "Revenue Prior": 10000.0, "Revenue Growth": 2000.0,
                    "Revenue Growth %": 0.2, "Quantity Current": 1100.0, "Quantity Prior": 1000.0,
                    "Quantity Growth": 100.0,
                }]},
            ]},
            "baseline_coverage_clean_data": {"queries": []},
        }
        # universe -> candidates carrying validated diagnostics
        state.update(summary_candidate_builder.run(state))
        universe_members = [c for c in state["summary_candidates"] if c.get("candidate_source") == "universe"]
        assert len(universe_members) == 4, len(universe_members)
        assert all(c.get("current") is not None and c.get("overall_current") for c in universe_members)
        assert all(c.get("area_key", "").startswith("area:v1:") for c in universe_members)
        assert any(c.get("angle") == "overall_performance" for c in state["summary_candidates"]), "overall candidate must exist"

        # Overall Performance package (deterministic bridge)
        state.update(summary_overall_performance.run(state))
        assert state["summary_overall_performance"]["status"] == "ok"

        # portfolio-mode novelty selection
        state.update(summary_novelty_filter.run(state))
        novelty = state["summary_novelty"]
        assert novelty["mode"] == "portfolio", novelty
        selected = state["summary_selected_focuses"]
        assert 2 <= len(selected) <= 3, [s["segment"] for s in selected]
        assert "CF-BAKERY" not in {s["segment"] for s in selected}, "tiny area must be excluded"
        assert selected[0]["area_key"] and selected[0]["focus_key"]
        assert all(s.get("sentiment") in {"opportunity", "risk", "mixed"} for s in selected)

        # generator: Overall Performance first, then one block group per focus
        state["summary_focus_evidence_by_key"] = {}  # deep dives are live; grounded facts still author
        state.update(fresh_summary_generator.run(state))
        fresh = state["fresh_summary"]
        blocks = fresh["content_blocks"]
        assert any(block.get("kind") == "chart" for block in blocks), (
            "R4 must include a chart whenever its covered evidence is chart-ready"
        )
        headings = [b.get("heading") for b in blocks if b.get("kind") == "bullets"]
        assert headings and headings[0] == "Overall Performance", headings
        for focus in selected:
            assert focus["segment"] in headings, (focus["segment"], headings)
        # Overall block quantifies BOTH sides of the driver bridge (volume AND
        # rate/mix), and both effects are attached as supported facts.
        overall_cand = next(c for c in state["summary_candidates"] if c.get("angle") == "overall_performance")
        bridge_facts = [f for f in (overall_cand.get("evidence") or {}).get("facts", []) if f.get("fact_kind") == "bridge"]
        assert len(bridge_facts) == 2, bridge_facts
        overall_block = next(b for b in blocks if b.get("kind") == "bullets" and b.get("heading") == "Overall Performance")
        joined = " ".join(overall_block["points"]).lower()
        assert "quantity" in joined and ("rate" in joined or "mix" in joined), overall_block["points"]
        from src.tools.summary_validation import validate_draft
        overall_candidate = next(c for c in state["summary_candidates"] if c.get("angle") == "overall_performance")
        assert not validate_draft(
            fresh, [overall_candidate, *selected], mode="balanced_multi_focus",
        )
        one_sided_overall = {
            **fresh,
            "content_blocks": [
                {
                    **block,
                    "points": [
                        point for point in block.get("points", [])
                        if "average revenue per item" not in point.casefold()
                    ],
                }
                if block.get("heading") == "Overall Performance"
                else block
                for block in fresh["content_blocks"]
            ],
        }
        assert any("every available overall driver fact" in error for error in validate_draft(
            one_sided_overall, [overall_candidate, *selected], mode="balanced_multi_focus",
        )), "a one-sided Overall bridge must be rejected"

        # The focus fallback and portfolio validator must also retain both
        # sides, including an offsetting negative rate/mix contribution.
        focus = selected[0]
        focus_evidence = dict(focus.get("evidence") or {})
        focus_evidence["facts"] = list(focus_evidence.get("facts") or []) + [
            {
                "fact_id": "FOCUS_VOLUME", "fact_kind": "deep_dive",
                "subject": focus["segment"], "subject_role": "focus", "detail_role": "driver",
                "metric": "Volume effect on revenue", "raw_value": 111100.0,
                "display_value": "+111.1K",
                "statement": f"Within {focus['segment']}, change in units sold added revenue by +111.1K.",
            },
            {
                "fact_id": "FOCUS_RATE_MIX", "fact_kind": "deep_dive",
                "subject": focus["segment"], "subject_role": "focus", "detail_role": "driver",
                "metric": "Rate and mix effect on revenue", "raw_value": -22200.0,
                "display_value": "-22.2K",
                "statement": (
                    f"Within {focus['segment']}, average revenue per item and mix reduced "
                    "revenue by -22.2K."
                ),
            },
        ]
        focus_with_bridge = {**focus, "evidence": focus_evidence}
        focus_fallback = fresh_summary_generator._r4_fallback(
            state, overall_candidate, [focus_with_bridge],
        )
        focus_block = next(
            block for block in focus_fallback["blocks"] if block.get("heading") == focus["segment"]
        )
        focus_text = " ".join(focus_block["points"])
        assert "+111.1K" in focus_text and "-22.2K" in focus_text, focus_block["points"]
        focus_sources = fresh_summary_generator._chart_sources([overall_candidate, focus_with_bridge])
        focus_fallback_errors = validate_draft(
            focus_fallback, [overall_candidate, focus_with_bridge],
            chart_sources=focus_sources, mode="balanced_multi_focus",
        )
        assert not focus_fallback_errors, focus_fallback_errors
        one_sided_focus = {
            **focus_fallback,
            "blocks": [
                {
                    **block,
                    "points": [point for point in block.get("points", []) if "-22.2K" not in point],
                }
                if block.get("heading") == focus["segment"]
                else block
                for block in focus_fallback["blocks"]
            ],
        }
        assert any(f"every available driver fact for {focus['segment']!r}" in error for error in validate_draft(
            one_sided_focus, [overall_candidate, focus_with_bridge],
            chart_sources=focus_sources, mode="balanced_multi_focus",
        )), "a one-sided focus bridge must be rejected"

        bad_order = {**fresh, "content_blocks": list(fresh["content_blocks"])[1:] + [fresh["content_blocks"][0]]}
        assert any("first block" in error for error in validate_draft(
            bad_order, [overall_candidate, *selected], mode="balanced_multi_focus",
        ))

        # Missing company-level evidence degrades honestly but never breaks the
        # mandatory opening or prevents the selected areas from being delivered.
        no_overall_state = {
            **state,
            "summary_candidates": [
                candidate for candidate in state["summary_candidates"]
                if candidate.get("angle") != "overall_performance"
            ],
            "summary_overall_performance": {"status": "unavailable"},
            "summary_llm_authoring_enabled": False,
        }
        no_overall = fresh_summary_generator.run(no_overall_state)["fresh_summary"]
        assert no_overall["content_blocks"][0]["heading"] == "Overall Performance"
        assert "could not be confirmed" in no_overall["content_blocks"][0]["points"][0]
        assert not validate_draft(no_overall, selected, mode="balanced_multi_focus")
        # every rendered bullet is a grounded fact statement (no invented figures)
        grounded = {
            str(f.get("statement") or "").strip()
            for c in state["summary_candidates"] for f in (c.get("evidence") or {}).get("facts", []) or []
        }
        for block in blocks:
            if block.get("kind") == "bullets":
                for point in block["points"]:
                    assert point in grounded or "driven mainly by" in point or "performance for the period" in point, point

        # Production R4 authors through the LLM. Feed the known-valid fallback
        # through a fake structured model to prove that path is wired and the
        # balanced validator accepts it without making a network call.
        overall_merged = fresh_summary_generator._merge_overall_evidence(
            overall_candidate, state.get("summary_overall_performance") or {},
        )
        fake_authored = fresh_summary_generator._r4_fallback(state, overall_merged, selected)

        class _FakeLlm:
            def invoke(self, _messages):
                return fresh_summary_generator.FreshSummaryDraft(**{
                    "headline": fake_authored["headline"],
                    "blocks": fake_authored["blocks"],
                    "covered_candidate_ids": fake_authored["covered_candidate_ids"],
                })

        original_get_llm = fresh_summary_generator.get_llm
        fresh_summary_generator.get_llm = lambda *_args, **_kwargs: _FakeLlm()
        try:
            llm_state = {**state, "summary_llm_authoring_enabled": True}
            llm_result = fresh_summary_generator.run(llm_state)["fresh_summary"]
            assert llm_result["authoring_mode"] == "llm"
        finally:
            fresh_summary_generator.get_llm = original_get_llm
        # public focus metadata is opt-in
        assert "dailyFocuses" not in fresh
        state_pub = {**state, "summary_focus_public_metadata": True}
        state_pub.update(fresh_summary_generator.run(state_pub))
        assert "dailyFocuses" in state_pub["fresh_summary"]
        assert {d["segment"] for d in state_pub["fresh_summary"]["dailyFocuses"]} == {s["segment"] for s in selected}

        # Final validation must see the same separately stored deep-dive facts
        # that the R4 generator used.  A live run exposed that validating the
        # original pre-drill candidate list rejects valid authored figures.
        deep_focus = selected[0]
        deep_statement = f"{deep_focus['segment']} recorded +987.7M in the selected comparison."
        deep_facts = list((deep_focus.get("evidence") or {}).get("facts") or []) + [{
            "fact_id": "LIVE_REGRESSION",
            "subject": deep_focus["segment"],
            "subject_role": "focus",
            "detail_role": "focus_metric",
            "raw_value": 987_654_321.0,
            "display_value": "+987.7M",
            "statement": deep_statement,
            "coverage": "complete",
        }]
        deep_summary = {
            **fresh,
            "content_blocks": [
                {
                    **block,
                    "points": list(block.get("points") or []) + [deep_statement],
                }
                if block.get("kind") == "bullets"
                and block.get("heading") == deep_focus["segment"]
                else block
                for block in fresh["content_blocks"]
            ],
        }
        deep_summary["paragraphs"] = [
            text
            for block in deep_summary["content_blocks"]
            for text in (
                list(block.get("points") or [])
                if block.get("kind") == "bullets"
                else [block.get("text")]
                if block.get("kind") == "paragraph" and block.get("text")
                else []
            )
        ]
        deep_state = {
            **state,
            "output_folder": str(root / "out-final-validator"),
            "fresh_summary": deep_summary,
            "summary_focus_evidence_by_key": {
                deep_focus["focus_key"]: {"facts": deep_facts, "sections": {}}
            },
        }
        chartless_state = {
            **deep_state,
            "fresh_summary": {
                **deep_summary,
                "content_blocks": [
                    block for block in deep_summary["content_blocks"]
                    if block.get("kind") != "chart"
                ],
            },
        }
        try:
            fresh_summary_validator.run(chartless_state)
        except ValueError as exc:
            assert "evidence-backed chart is required" in str(exc)
        else:
            raise AssertionError("final R4 validation accepted a chartless chart-ready summary")
        validated = fresh_summary_validator.run(deep_state)
        assert deep_statement in validated["report_summary"]

        # commit -> Memory v3 (area_records / weekly_coverage / multi daily_plan)
        fresh = {"summary_type": novelty["summary_type"], "heading": "Portfolio",
                 "covered_summary_keys": [s["summary_key"] for s in selected]}
        commit = summary_memory.commit_summary_run(state, fresh["covered_summary_keys"], fresh)
        assert commit["status"] == "ok", commit
        store = _json.loads(summary_memory.store_path(state).read_text(encoding="utf-8"))
        assert store["schema_version"] == 5  # v5 (WP4): adds state_records
        assert len(store["area_records"]) == len(selected)
        assert all(s["area_key"] in store["weekly_coverage"] for s in selected)
        plan = store["daily_plan"]["2026-08-01"]
        assert set(plan["focus_keys"]) == {s["focus_key"] for s in selected}
        assert set(plan["area_keys"]) == {s["area_key"] for s in selected}
        # coverage map feeds the selector next run
        cov = summary_memory.coverage_map(store)
        assert all(s["area_key"] in cov for s in selected)

        # same-day rerun pins the identical portfolio (order preserved)
        state.update(summary_novelty_filter.run(state))
        assert state["summary_novelty"]["recovered_same_day"] is True
        assert [s["focus_key"] for s in state["summary_selected_focuses"]] == [s["focus_key"] for s in selected]
    print("  r4 end-to-end: universe->candidates->portfolio->commit(v3)->same-day pin  OK")


def test_overall_package():
    from src.tools import summary_overall
    candidate = {
        "angle": "overall_performance", "coverage": "complete", "visual": {"type": "bar"},
        "metrics": [{"label": "Revenue", "value": "+200"}],
        "evidence": {"facts": [
            {"fact_kind": "comparison", "metric": "Revenue comparison", "current_value": 1200.0,
             "prior_value": 1000.0, "change_value": 200.0, "change_pct": 20.0, "comparison": "the same period last year"},
            {"fact_kind": "comparison", "metric": "Quantity comparison", "current_value": 110.0,
             "prior_value": 100.0, "change_value": 10.0, "change_pct": 10.0, "comparison": "the same period last year"},
        ]},
    }
    pkg = summary_overall.build_overall(candidate, {"data_as_of": "2026-08-01", "grain": "month", "freshness_status": "current"})
    assert pkg["status"] == "ok" and pkg["primary_family"] == "revenue"
    assert {"revenue", "quantity"} <= set(pkg["families"])
    bridge = pkg["bridge"]
    # volume=(110-100)*(1000/100)=100 ; rate=110*(1200/110 - 1000/100)=100 ; total=200=change
    assert abs(bridge["volume_effect"] - 100.0) < 1e-6 and abs(bridge["rate_mix_effect"] - 100.0) < 1e-6
    assert abs(bridge["total"] - 200.0) < 1e-6 and bridge["reconciles"] is True
    assert "pure price" not in bridge["note"].lower() or "not pure price" in bridge["note"].lower()
    assert pkg["comparison"] == "the same period last year"
    rev_only = {"angle": "overall_performance", "coverage": "complete", "evidence": {"facts": [
        {"fact_kind": "comparison", "metric": "Revenue comparison", "current_value": 1200.0,
         "prior_value": 1000.0, "change_value": 200.0, "change_pct": 20.0, "comparison": "x"}]}}
    assert summary_overall.build_overall(rev_only, {})["bridge"] is None
    assert summary_overall.build_overall(None, {})["status"] == "unavailable"
    print("  overall package: families, exact bridge reconciliation, graceful degradation  OK")


def test_overall_selector_and_contribution():
    """A comparison-capable company total is Overall; a current-only total
    (e.g. a newly opened branch) is a separate contribution and must never seize
    the Overall slot even when its raw current value is larger."""
    import tempfile
    from src.agents import summary_candidate_builder, summary_overall_performance
    from src.agents.fresh_summary_validator import _fmt_chart_number
    from src.tools import summary_overall

    lfl = {
        "net revenue CURRENT": 126_960_704.8, "net revenue PAST": 123_265_708.37,
        "revenue Growth": 3_694_996.43, "net qty CURRENT": 18_773_558.27,
        "net qty PAST": 18_989_414.48, "QTY Growth": -215_856.21,
        "net bills CURRENT": 8_414_798, "net bills PAST": 8_156_383, "bills growth": 258_415,
    }
    # Current-only total with a LARGER revenue value than the like-for-like
    # change - this is exactly what used to win the Overall slot on raw score.
    new_branch = {
        "net revenue CURRENT": 11_906_055.96, "net qty CURRENT": 2_113_071.87,
        "net bills CURRENT": 794_252,
    }
    with tempfile.TemporaryDirectory(prefix="overall-sel-") as tmp:
        state = {
            "dataset_id": "sel", "output_folder": tmp, "summary_r4_enabled": True,
            "summary_focus_enabled": True, "summary_overall_trend_enabled": False,
            "semantic_model_profile": {"entity_dimension": {"column": "STORE_NO"}},
            "resolved_entity_scope": {
                "active_comparable_population": ["CFH014", "CFH017", "CFH018", "CFH021"],
                "excluded_from_comparison": ["CFH022"],
            },
            "summary_period_context": {"period_anchor": "2026-07", "data_as_of": "2026-07-30",
                                       "grain": "day", "freshness_status": "current", "checks": []},
            "config": {}, "logs": [], "errors": [],
            "clean_summary_data": {"queries": [
                {"query_name": "like_for_like_kpi_totals", "status": "success", "rows": [lfl],
                 "purpose": "Summarize the core like-for-like business position."},
                {"query_name": "new_branch_current_totals", "status": "success", "rows": [new_branch],
                 "purpose": "Show the current-period contribution of CFH022 separately from like-for-like."},
            ]},
            "baseline_coverage_clean_data": {"queries": []},
        }
        state.update(summary_candidate_builder.run(state))
        cands = state["summary_candidates"]
        op = [c for c in cands if c["angle"] == "overall_performance"]
        oc = [c for c in cands if c["angle"] == "overall_contribution"]
        assert len(op) == 1 and op[0]["query_name"] == "like_for_like_kpi_totals", op
        assert len(oc) == 1 and oc[0]["query_name"] == "new_branch_current_totals", oc
        # the current-only total must not out-score its way into the Overall slot
        assert not any(c["angle"] == "overall_performance" and "new_branch" in c["query_name"] for c in cands)

        state.update(summary_overall_performance.run(state))
        pkg = state["summary_overall_performance"]
        assert pkg["status"] == "ok", pkg
        assert abs(pkg["families"]["revenue"]["change"] - 3_694_996.43) < 1
        assert abs(pkg["families"]["quantity"]["change"] + 215_856.21) < 1
        assert abs(pkg["families"]["transactions"]["change"] - 258_415) < 1

        contrib = pkg.get("contribution")
        assert contrib and contrib["subject"] == "CFH022", contrib
        disp = {f["fact_id"]: f["display_value"] for f in contrib["facts"]}
        assert disp.get("CONTRIB_REVENUE") == "11.9M", disp
        # contribution facts are copyable/supported on the overall candidate
        overall_cand = next(c for c in state["summary_candidates"] if c["angle"] == "overall_performance")
        kinds = {f.get("fact_kind") for f in overall_cand["evidence"]["facts"]}
        assert {"bridge", "contribution"} <= kinds, kinds

    # contribution_note degrades gracefully
    assert summary_overall.contribution_note(None) is None
    assert summary_overall.contribution_note({"evidence": {"facts": []}}) is None

    # Markdown chart numbers are human-readable, not raw floats.
    assert _fmt_chart_number(669_793.8700000001, "Revenue change") == "+669.8K"
    assert _fmt_chart_number(-2691.129999999999, "Revenue change") == "-2.7K"
    assert _fmt_chart_number(126_960_704.8, "Revenue") == "127.0M"
    assert _fmt_chart_number(0.0299, "growth %") == "+3.0%"
    assert _fmt_chart_number("n/a", "Revenue") == "n/a"
    print("  overall selector: comparison total wins Overall, current-only becomes note; md formatting  OK")


def test_multi_focus_orchestration():
    import tempfile
    from src.agents import summary_multi_focus_evidence as mfe

    def focus(seg, role, path, sig):
        return {"focus_key": f"fk:{seg}", "candidate_id": f"c:{seg}", "segment": seg,
                "dimension_role": role, "hierarchy_path": path, "area_key": f"ak:{seg}",
                "evidence": {"facts": [{"subject": seg, "subject_role": "focus"}]}, "_sig": sig}

    def fake_dd(state, foc, cands, per_focus_max):
        return {"focus_key": foc["focus_key"], "queries_attempted": min(per_focus_max, 3),
                "budget_received": per_focus_max,
                "signature_fields": foc["_sig"], "facts": [], "sections": {}}

    original = mfe._deep_dive_one
    mfe._deep_dive_one = fake_dd
    try:
        with tempfile.TemporaryDirectory(prefix="mfe-") as tmp:
            base = {"summary_r4_enabled": True, "summary_focus_max_replacements_per_slot": 1,
                    "summary_focus_fact_overlap_threshold": 0.6, "output_folder": tmp, "logs": [], "errors": []}
            sel = [focus("A", "division", ["A"], {"leading_location": "L1", "driver_class": "D1"}),
                   focus("B", "division", ["B"], {"leading_location": "L2", "driver_class": "D2"}),
                   focus("C", "division", ["C"], {"leading_location": "L3", "driver_class": "D3"})]
            res = [focus("R", "category", ["X", "R"], {"leading_location": "L9", "driver_class": "D9"})]

            out = mfe.run({**base, "summary_selected_focuses": sel, "summary_portfolio_reserves": res})
            by_key = out["summary_focus_evidence_by_key"]
            assert len(by_key) == 3, list(by_key)
            assert sum(d["queries_attempted"] for d in by_key.values()) <= 15
            assert all(d["queries_attempted"] <= 5 for d in by_key.values())
            assert next(iter(by_key.values()))["budget_received"] == 5

            # Reusing an output directory with no selected focus must clear the
            # complete keyed audit instead of leaving the previous run's data.
            import json
            audit_path = Path(tmp) / "summary_focus_evidence_by_key.json"
            assert len(json.loads(audit_path.read_text(encoding="utf-8"))) == 3
            empty = mfe.run({**base, "summary_selected_focuses": [], "summary_portfolio_reserves": []})
            assert empty["summary_focus_evidence_by_key"] == {}
            assert json.loads(audit_path.read_text(encoding="utf-8")) == {}

            # Emergent duplicate: B shares A's drilled signature -> replaced by reserve R.
            sel_dup = [focus("A", "division", ["A"], {"leading_location": "L1", "driver_class": "D1"}),
                       focus("B", "division", ["B"], {"leading_location": "L1", "driver_class": "D1"}),
                       focus("C", "division", ["C"], {"leading_location": "L3", "driver_class": "D3"})]
            out2 = mfe.run({**base, "summary_selected_focuses": sel_dup, "summary_portfolio_reserves": res})
            segs = {f["segment"] for f in out2["summary_selected_focuses"]}
            assert "B" not in segs and "R" in segs, segs

            # With no viable reserve, the duplicate slot is omitted rather than
            # knowingly publishing the same drilled story twice.
            out_no_reserve = mfe.run({
                **base, "summary_selected_focuses": sel_dup,
                "summary_portfolio_reserves": [],
            })
            no_reserve_segs = {f["segment"] for f in out_no_reserve["summary_selected_focuses"]}
            assert "B" not in no_reserve_segs and len(no_reserve_segs) == 2, no_reserve_segs

            # Budget starvation: tiny total, no reserves -> fewer focuses, never overspent.
            out3 = mfe.run({**base, "summary_focus_total_deep_dive_queries": 2,
                            "summary_selected_focuses": sel, "summary_portfolio_reserves": []})
            assert len(out3["summary_focus_evidence_by_key"]) <= 2
            assert sum(d["queries_attempted"] for d in out3["summary_focus_evidence_by_key"].values()) <= 2
    finally:
        mfe._deep_dive_one = original
    print("  multi-focus: shared budget, per-focus cap, emergent replacement, starvation  OK")


def test_required_delivery_gate():
    from src.main import _summary_delivery_gate

    final = {"report_summary": "ok", "fresh_summary": {"summary_type": "new_perspective"}}
    optional_failures = _summary_delivery_gate(
        final,
        {"summary_required_delivery_channels": ["local_report", "history"]},
        api_payloads={"summaryStatus": {"status": "failed"}},
        api_upload={"status": "failed", "receipts": {}},
        history_artifact=({"runId": "x"}, "path", "feed"),
        history_upload={"status": "failed"},
        ai_content_upload={"summaryStatus": "failed"},
    )
    assert optional_failures["ok"] is True, optional_failures
    required_api = _summary_delivery_gate(
        final,
        {"summary_required_delivery_channels": ["local_report", "history", "api_payload"]},
        api_payloads={"summaryStatus": {"status": "failed"}},
        api_upload={},
        history_artifact=({"runId": "x"}, "path", "feed"),
        history_upload={},
        ai_content_upload={},
    )
    assert required_api["ok"] is False and required_api["failed"] == ["api_payload"]
    print("  delivery gate: optional publish failures do not freeze rotation  OK")


def main() -> int:
    test_dax_builder()
    test_parser()
    test_role_alias_and_related_table_ancestry()
    test_path_scoped_portfolio_identity()
    test_materiality_formulas()
    test_selector_ranking_and_diversity()
    test_selector_rotation_and_override()
    test_overall_package()
    test_overall_selector_and_contribution()
    test_r4_end_to_end()
    test_multi_focus_orchestration()
    test_required_delivery_gate()
    print("summary portfolio replay: all deterministic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
