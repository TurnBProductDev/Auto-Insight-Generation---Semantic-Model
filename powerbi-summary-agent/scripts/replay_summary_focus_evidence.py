"""Offline regression for the summary focus deep-dive node and selection.

No Power BI, Azure, or LLM credentials are required. Targeted DAX execution is
replayed through a fake executor so the deterministic reuse-first / targeted-DAX
assembly, reconciliation, budget, and non-fatal failure handling can all be
verified without a live model.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import summary_focus_evidence
from src.tools import summary_focus, summary_focus_queries, summary_memory


# --- fixtures ----------------------------------------------------------------
COMPARABLE = ["CFH014", "CFH017", "CFH018", "CFH021"]


def _profile() -> dict:
    revenue = {
        "id": "Sales::revenue", "family": "revenue", "source_table": "Sales",
        "measures": {"current": "Revenue Current", "prior": "Revenue Prior", "change": "Revenue Change"},
        "derived": {}, "additive_candidate": True,
    }
    quantity = {
        "id": "Sales::quantity", "family": "quantity", "source_table": "Sales",
        "measures": {"current": "Qty Current", "prior": "Qty Prior", "change": "Qty Change"},
        "derived": {}, "additive_candidate": True,
    }
    transactions = {
        "id": "Sales::transactions", "family": "transactions", "source_table": "Sales",
        "measures": {"current": "Txn Current", "prior": "Txn Prior", "change": "Txn Change"},
        "derived": {}, "additive_candidate": True,
    }
    return {
        "primary_value_bundle": revenue,
        "value_bundles": [revenue],
        "volume_driver_bundles": [quantity, transactions],
        "measure_bundles": [revenue, quantity, transactions],
        "measure_roles": {
            "Revenue Prior": {"phase": "prior", "column_refs": [{"table": "Sales", "column": "Amount"}]},
            "Revenue Change": {"phase": "change", "column_refs": [{"table": "Sales", "column": "Amount"}]},
        },
        "fact_table": "Sales",
        "entity_dimension": {"table": "Store", "column": "Store No", "reference": "'Store'[Store No]"},
        "dimensions": [
            {"table": "Item", "column": "Item Category", "reference": "'Item'[Item Category]"},
            {"table": "Item", "column": "Product Group", "reference": "'Item'[Product Group]"},
        ],
        "time_dimensions": [
            {"table": "Calendar", "column": "Doc Month", "reference": "'Calendar'[Doc Month]"},
        ],
    }


def _metadata() -> dict:
    measures = [
        "Revenue Current", "Revenue Prior", "Revenue Change",
        "Qty Current", "Qty Prior", "Qty Change",
        "Txn Current", "Txn Prior", "Txn Change",
    ]
    return {
        "tables": [{"name": t} for t in ("Sales", "Store", "Item", "Calendar")],
        "measures": [{"name": m} for m in measures],
        "columns": [
            {"table": "Store", "column": "Store No"},
            {"table": "Item", "column": "Item Category"},
            {"table": "Item", "column": "Product Group"},
            {"table": "Calendar", "column": "Doc Month"},
        ],
    }


def _selected_candidate() -> dict:
    return {
        "candidate_id": "summary_focus_fmcg",
        "candidate_kind": "member",
        "angle": "category_overview",
        "dimension_role": "category",
        "lens": "performance",
        "coverage": "partial",
        "segment": "FMCG FOOD",
        "dimension": "Item Category",
        "dimension_ref": "'Item'[Item Category]",
        "member_value": "FMCG FOOD",
        "metric": "Revenue Change",
        "metric_family": "revenue",
        "focus_key": "focus:v1:testfmcg",
        "summary_key": "summary:v1:testfmcg",
        "evidence": {
            "facts": [
                {
                    "fact_id": "F1", "fact_kind": "comparison", "subject": "FMCG FOOD",
                    "metric": "Revenue comparison", "display_value": "+40.0K", "raw_value": 40000.0,
                    "current_value": 500000.0, "prior_value": 460000.0,
                    "change_value": 40000.0, "change_pct": 8.6957,
                    "statement": "FMCG FOOD revenue changed by +40.0K.",
                    "subject_role": "focus", "coverage": "partial",
                },
                {
                    "fact_id": "F2", "fact_kind": "comparison", "subject": "FMCG FOOD",
                    "metric": "Quantity comparison", "display_value": "+1.0K", "raw_value": 1000.0,
                    "current_value": 20000.0, "prior_value": 19000.0,
                    "change_value": 1000.0, "change_pct": 5.2632,
                    "statement": "FMCG FOOD quantity changed by +1.0K.",
                    "subject_role": "focus", "coverage": "partial",
                },
                {
                    "fact_id": "F3", "fact_kind": "comparison", "subject": "FMCG FOOD",
                    "metric": "Transactions comparison", "display_value": "+200", "raw_value": 200.0,
                    "current_value": 8000.0, "prior_value": 7800.0,
                    "change_value": 200.0, "change_pct": 2.5641,
                    "statement": "FMCG FOOD transactions changed by +200.",
                    "subject_role": "focus", "coverage": "partial",
                },
            ],
            "rows": [], "scope": {},
        },
    }


def _base_state(root: Path, **overrides) -> dict:
    state = {
        "dataset_id": "fixture-dataset",
        "workspace_id": "ws", "output_folder": str(root / "outputs"),
        "pbi_token": "fake-token",
        "summary_focus_enabled": True,
        "summary_focus_deep_dive_enabled": True,
        "summary_focus_include_driver_bridge": True,
        "summary_focus_include_trend": True,
        "summary_focus_daily_trend_enabled": False,
        "summary_focus_max_queries": 4,
        "summary_focus_max_child_dimensions": 2,
        "summary_focus_max_rows_per_breakdown": 12,
        "summary_focus_reconciliation_tolerance_pct": 2,
        "semantic_model_profile": _profile(),
        "model_metadata": _metadata(),
        "resolved_entity_scope": {
            "active_comparable_population": COMPARABLE,
            "excluded_from_comparison": ["CFH022"],
            "entity_dimension": {"reference": "'Store'[Store No]"},
        },
        "insight_comparable_population": COMPARABLE,
        "insight_excluded_entities": ["CFH022"],
        "summary_period_context": {
            "grain": "month",
            "checks": [{"column": "Doc Month", "verdict": "ok", "grain": "month"}],
        },
        "insight_temporal_gated_tables": [],
        "config": {},
        "summary_selected_focus": {
            "focus_key": "focus:v1:testfmcg",
            "candidate_id": "summary_focus_fmcg",
            "dimension_role": "category",
            "segment": "FMCG FOOD",
            "metric_family": "revenue",
        },
        "summary_eligible_candidates": [_selected_candidate()],
        "summary_candidates": [_selected_candidate()],
        "logs": [], "errors": [],
    }
    state.update(overrides)
    return state


# --- fake executor -----------------------------------------------------------
def _payload(rows):
    return {"results": [{"tables": [{"rows": rows}]}]}


def _make_executor(calls, fail=(), child_rows=None, trend_rows=None):
    scorecard_row = {
        "[revenue_current]": 500000.0, "[revenue_prior]": 460000.0, "[revenue_change]": 40000.0,
        "[quantity_current]": 20000.0, "[quantity_prior]": 19000.0, "[quantity_change]": 1000.0,
        "[transactions_current]": 8000.0, "[transactions_prior]": 7800.0, "[transactions_change]": 200.0,
    }
    diagnostics = {"[__focus_total]": 500000.0, "[__global_total]": 900000.0, "[__parent_count]": 1}
    default_children = [
        {"'Item'[Product Group]": "Rice", "[revenue_current]": 300000.0, "[revenue_prior]": 250000.0, "[revenue_change]": 50000.0, **diagnostics},
        {"'Item'[Product Group]": "Oil", "[revenue_current]": 150000.0, "[revenue_prior]": 170000.0, "[revenue_change]": -20000.0, **diagnostics},
        {"'Item'[Product Group]": "Snacks", "[revenue_current]": 50000.0, "[revenue_prior]": 40000.0, "[revenue_change]": 10000.0, **diagnostics},
    ]
    stores = [
        {"'Store'[Store No]": "CFH014", "[revenue_current]": 260000.0, "[revenue_prior]": 230000.0, "[revenue_change]": 30000.0},
        {"'Store'[Store No]": "CFH017", "[revenue_current]": 240000.0, "[revenue_prior]": 230000.0, "[revenue_change]": 10000.0},
    ]
    trend_diagnostics = {"[__series_total]": 500000.0, "[__focus_total]": 500000.0}
    months = [
        {"'Calendar'[Doc Month]": 10, "[revenue_current]": 150000.0, "[revenue_prior]": 160000.0, "[revenue_change]": -10000.0, **trend_diagnostics},
        {"'Calendar'[Doc Month]": 11, "[revenue_current]": 170000.0, "[revenue_prior]": 150000.0, "[revenue_change]": 20000.0, **trend_diagnostics},
        {"'Calendar'[Doc Month]": 12, "[revenue_current]": 180000.0, "[revenue_prior]": 150000.0, "[revenue_change]": 30000.0, **trend_diagnostics},
    ]

    def fake(workspace_id, dataset_id, queries, token=None):
        out = {}
        for q in queries:
            name = q["name"]
            calls.append(name)
            if any(tag in name for tag in fail):
                out[name] = {"status": "failed", "query": q["dax"], "error": "boom"}
                continue
            if "scorecard" in name:
                rows = [scorecard_row]
            elif "child" in name:
                rows = child_rows if child_rows is not None else default_children
            elif "location" in name:
                rows = stores
            elif "trend" in name:
                rows = trend_rows if trend_rows is not None else months
            else:
                rows = []
            out[name] = {"status": "success", "query": q["dax"], "result": _payload(rows)}
        return out

    return fake


def _run_node(state, calls, **kw):
    original = summary_focus_evidence.pbi.execute_python
    summary_focus_evidence.pbi.execute_python = _make_executor(calls, **kw)
    try:
        return summary_focus_evidence.run(state)
    finally:
        summary_focus_evidence.pbi.execute_python = original


# --- deep-dive tests ---------------------------------------------------------
def _test_happy_path(root: Path) -> None:
    state = _base_state(root)
    calls: list[str] = []
    result = _run_node(state, calls)
    doc = result["summary_focus_evidence"]

    sc = doc["sections"]["scorecard"]["metrics"]["revenue"]
    assert sc["current"] == 500000.0 and sc["prior"] == 460000.0 and sc["change"] == 40000.0, sc

    contributors = doc["sections"]["internal_contributors"]
    assert contributors and contributors[0]["dimension"] == "Product Group", contributors
    # 300000 + 150000 + 50000 == 500000 -> reconciles to the focus total.
    assert contributors[0]["completeness"] == "complete", contributors[0]
    assert contributors[0]["top_positive"]["member"] == "Rice"
    assert contributors[0]["top_negative"]["member"] == "Oil"

    assert doc["sections"]["location"] is not None
    assert doc["sections"]["location"]["top_positive"]["member"] == "CFH014"

    bridge = doc["sections"]["driver_bridge"]
    assert bridge and bridge["reconciles"] and bridge["driver_class"] in {"volume", "rate/mix"}
    assert abs((bridge["volume_effect"] + bridge["rate_mix_effect"]) - bridge["total_change"]) < 1.0

    assert doc["sections"]["period_trend"] is not None
    assert doc["sections"]["daily_trend"]["status"] == "disabled"

    metrics = {f["metric"] for f in doc["facts"]}
    assert "Revenue change" in metrics
    assert any(f["subject_role"] == "peer" for f in doc["facts"]), "expected a contributor/location peer fact"
    assert any("driver" in f["metric"].lower() for f in doc["facts"]), "expected a driver fact"
    assert doc["deep_dive_signature"] and doc["signature_fields"]["top_pos_contributor"] == "Rice"

    enriched = result["summary_eligible_candidates"][0]
    assert enriched.get("has_deep_dive") is True
    assert len(enriched["evidence"]["facts"]) > 1
    # Scorecard is reused; child + location + trend fit under the default cap.
    assert doc["sections"]["scorecard"]["source"] == "reused_candidate"
    assert doc["queries_attempted"] == 3, doc["queries_attempted"]
    assert not any("scorecard" in call for call in calls), calls
    assert calls == [c for c in calls if any(t in c for t in ("scorecard", "child", "location", "trend"))]
    print("  happy path: scorecard + reconciled child + location + bridge + trend  OK")


def _test_partial_reconciliation(root: Path) -> None:
    # Child rows that do NOT sum to the focus total must stay 'partial'.
    partial_children = [
        {"'Item'[Product Group]": "Rice", "[revenue_current]": 120000.0, "[revenue_prior]": 100000.0, "[revenue_change]": 20000.0, "[__focus_total]": 500000.0, "[__global_total]": 900000.0, "[__parent_count]": 1},
        {"'Item'[Product Group]": "Oil", "[revenue_current]": 80000.0, "[revenue_prior]": 90000.0, "[revenue_change]": -10000.0, "[__focus_total]": 500000.0, "[__global_total]": 900000.0, "[__parent_count]": 1},
    ]
    state = _base_state(root)
    calls: list[str] = []
    result = _run_node(state, calls, child_rows=partial_children)
    contributors = result["summary_focus_evidence"]["sections"]["internal_contributors"]
    assert contributors[0]["completeness"] == "partial", contributors[0]
    # A partial contributor must not be quoted as complete on the attached fact.
    peer_facts = [f for f in result["summary_focus_evidence"]["facts"] if f["subject_role"] == "peer"]
    assert peer_facts and all(f["coverage"] != "complete" for f in peer_facts if "Product Group" in f["metric"])
    print("  partial reconciliation: contributors stay partial, facts not called complete  OK")


def _test_hierarchy_runtime_rejection(root: Path) -> None:
    overlapping = [
        {"'Item'[Product Group]": "Shared Group", "[revenue_current]": 500000.0,
         "[revenue_prior]": 460000.0, "[revenue_change]": 40000.0,
         "[__focus_total]": 500000.0, "[__global_total]": 900000.0,
         "[__parent_count]": 2},
    ]
    result = _run_node(_base_state(root), [], child_rows=overlapping)
    doc = result["summary_focus_evidence"]
    assert not doc["sections"]["internal_contributors"]
    assert any("failed hierarchy validation" in caveat for caveat in doc["caveats"])
    print("  hierarchy runtime: a child shared across unrelated parents is rejected  OK")


def _test_budget(root: Path) -> None:
    state = _base_state(root, summary_focus_max_queries=2)
    calls: list[str] = []
    result = _run_node(state, calls)
    doc = result["summary_focus_evidence"]
    assert doc["queries_attempted"] == 2, doc["queries_attempted"]
    # The node reserves the two available calls deterministically and never
    # exceeds the cap or invokes an LLM repair.
    assert len(calls) == 2, calls
    print("  budget: fresh REST attempts capped at 2, remaining drills skipped  OK")


def _test_failed_drill_non_fatal(root: Path) -> None:
    state = _base_state(root)
    calls: list[str] = []
    result = _run_node(state, calls, fail=("location",))
    doc = result["summary_focus_evidence"]
    # A failed drill counts against the budget but is non-fatal: scorecard,
    # child, and trend still land, with an honest caveat.
    assert "location breakdown failed" in doc["caveats"], doc["caveats"]
    assert doc["sections"]["scorecard"]["metrics"], "scorecard should still be present"
    assert doc["sections"]["internal_contributors"], "child breakdown should still be present"
    assert doc["queries_attempted"] == 3, doc["queries_attempted"]
    print("  failed drill: non-fatal, remaining evidence + caveat retained  OK")


def _test_no_token_reuse_only(root: Path) -> None:
    state = _base_state(root)
    state.pop("pbi_token", None)
    calls: list[str] = []
    result = _run_node(state, calls)
    assert not calls, "no fresh DAX may be issued without a token"
    doc = result["summary_focus_evidence"]
    assert doc["queries_attempted"] == 0
    print("  no token: zero fresh queries, node still non-fatal  OK")


def _test_child_discovery_override(root: Path) -> None:
    profile = _profile()
    # Override validated against live metadata: only 'Product Group' is a real dim.
    overrides = {"category": ["Product Group"]}
    children = summary_focus_evidence._discover_child_dimensions(
        {"summary_focus_hierarchy_overrides": overrides, "model_metadata": _metadata()},
        profile, "'Item'[Item Category]", 2, "category",
    )
    assert [c["column"] for c in children] == ["Product Group"], children
    try:
        summary_focus_evidence._discover_child_dimensions(
            {"summary_focus_hierarchy_overrides": {"category": ["Ghost"]}, "model_metadata": _metadata()},
            profile, "'Item'[Item Category]", 2, "category",
        )
    except ValueError:
        pass
    else:
        raise AssertionError("invalid hierarchy override must fail loudly")
    print("  child discovery: role-matched override honored; invalid override fails loudly  OK")


def _test_driver_bridge_math() -> None:
    scorecard = {
        "revenue": {"current": 500000.0, "prior": 460000.0},
        "quantity": {"current": 20000.0, "prior": 19000.0},
    }
    bridge = summary_focus_evidence._driver_bridge(scorecard)
    assert bridge and bridge["reconciles"]
    assert abs((bridge["volume_effect"] + bridge["rate_mix_effect"]) - 40000.0) < 1e-6
    assert bridge["driver_class"] in {"volume", "rate/mix"}
    print("  driver bridge: (Q1-Q0)*R0/Q0 + Q1*(R1/Q1 - R0/Q0) reconciles  OK")


def _test_query_contracts() -> None:
    filters = [summary_focus_queries.member_filter("'Item'[Item Category]", "FMCG FOOD")]
    child = summary_focus_queries.breakdown(
        "child", "child", "'Item'[Product Group]", filters,
        [("revenue_current", "Revenue Current"), ("revenue_change", "Revenue Change")],
        "Revenue Change", 12, parent_col_ref="'Item'[Item Category]",
    )["dax"]
    assert "TREATAS" in child and "DISTINCTCOUNT" in child and "REMOVEFILTERS" in child
    assert "KEEPFILTERS" not in child and "TOPN(12" in child
    trend = summary_focus_queries.period_trend(
        "trend", "trend", "'Calendar'[Doc Month]", filters,
        [("revenue_current", "Revenue Current")], 24,
    )["dax"]
    assert "TOPN(24" in trend and "DESC" in trend and "ORDER BY 'Calendar'[Doc Month] ASC" in trend
    assert "SUMX(__series" in trend and '"__series_total"' in trend and '"__focus_total"' in trend
    print("  query contracts: TREATAS + hierarchy diagnostics + reconciled latest-N trend  OK")


# --- selection tests ---------------------------------------------------------
def _member(role, segment, obs, coverage="partial") -> dict:
    cand = {
        "candidate_id": f"c_{role}_{segment}".lower(),
        "candidate_kind": "member",
        "dimension_role": role,
        "segment": segment,
        "metric_family": "revenue",
        "lens": "performance",
        "coverage": coverage,
        "direction": "increase" if obs > 0 else "decrease",
        "observation_value": obs,
    }
    key, _ = summary_memory.focus_components(cand, "ds")
    cand["focus_key"] = key
    return cand


def _test_selection_and_rotation() -> None:
    store = summary_memory._empty_store()
    # A broad store aggregate whose movement is the SUM of the members must NOT
    # beat its own members (it would leave the deep dive unable to member-scope).
    broad_store = {**_member("store", "", 620000), "candidate_kind": "broad", "coverage": "partial"}
    candidates = [
        _member("store", "CFH014", 500000),
        _member("store", "CFH017", 120000),
        _member("category", "FMCG FOOD", 90000),
        broad_store,
        {**_member("overall", "", 350000), "candidate_kind": "broad", "coverage": "complete"},
    ]
    state = {"summary_now_override": "2026-07-01", "summary_focus_cooldown_days": 14,
             "summary_focus_same_dimension_gap_days": 2, "dataset_id": "ds"}
    result = summary_focus.select_focus(state, candidates, store, "empty")
    selected = result["selected"]
    assert selected is not None and result["summary_type"] in {"new_data", "new_perspective"}
    # role_materiality is a bounded top-3 mean, never a sum that rewards member count.
    scores = result["audit"]["role_scores"]
    assert all(v["role_materiality"] <= 1.0 for v in scores.values()), scores
    # The redundant broad store aggregate is never the selected focus.
    assert selected["focus_key"] != broad_store["focus_key"], "aggregate must not beat its members"
    if selected["dimension_role"] == "store":
        assert selected.get("segment"), "a member-bearing role must resolve to a specific member"

    # Simulate delivery of the selected focus, then a same-day re-run pins it.
    today = "2026-07-01"
    store["focus_records"][selected["focus_key"]] = {
        "dimension_role": selected["dimension_role"], "last_reported": f"{today}T09:00:00",
        "times_reported": 1,
    }
    store["daily_plan"][today] = {"focus_key": selected["focus_key"]}
    pinned = summary_focus.select_focus(state, candidates, store, "ok")
    assert pinned["audit"]["recovered_same_day"] is True
    assert pinned["selected"]["focus_key"] == selected["focus_key"], "same-day pin must re-deliver"

    # A different day: the just-delivered focus is inside cooldown and its role
    # is inside the same-dimension gap, so a different focus/role is chosen.
    state2 = {**state, "summary_now_override": "2026-07-02"}
    rotated = summary_focus.select_focus(state2, candidates, store, "ok")
    assert rotated["selected"] is not None
    assert rotated["selected"]["focus_key"] != selected["focus_key"], "cooldown must rotate the focus"
    print("  selection: bounded role score, same-day pin, cooldown rotation  OK")


def _test_r1_resurface_overrides() -> None:
    reversed_focus = _member("category", "FMCG FOOD", -250000)
    alternative = _member("store", "CFH014", 900000)
    state = {
        "summary_now_override": "2026-07-10", "summary_focus_cooldown_days": 14,
        "summary_focus_same_dimension_gap_days": 2, "dataset_id": "ds",
        "summary_period_context": {"grain": "day", "period_anchor": "2026-07-09"},
    }
    store = summary_memory._empty_store()
    store["period_anchor"] = "2026-07-08"
    store["focus_records"][reversed_focus["focus_key"]] = {
        "dimension_role": "category", "last_reported": "2026-07-09T09:00:00",
        "last_direction": "increase",
    }
    result = summary_focus.select_focus(state, [reversed_focus, alternative], store, "ok")
    assert result["audit"]["reason"] == "material_reversal", result["audit"]
    assert result["selected"]["focus_key"] == reversed_focus["focus_key"]

    period_focus = {**_member("period", "", 100000), "candidate_kind": "broad", "lens": "trend"}
    period_key, _ = summary_memory.focus_components(period_focus, "ds")
    period_focus["focus_key"] = period_key
    store = summary_memory._empty_store()
    store["period_anchor"] = "2026-06"
    store["focus_records"][period_key] = {
        "dimension_role": "period", "last_reported": "2026-07-09T09:00:00",
        "last_direction": "increase",
    }
    daily = {
        **state,
        "summary_period_context": {"grain": "day", "period_anchor": "2026-07-10"},
    }
    daily_result = summary_focus.select_focus(daily, [period_focus, alternative], store, "ok")
    assert daily_result["selected"]["focus_key"] != period_key
    monthly = {
        **state,
        "summary_period_context": {"grain": "month", "period_anchor": "2026-07"},
    }
    result = summary_focus.select_focus(monthly, [period_focus, alternative], store, "ok")
    assert result["audit"]["reason"] == "new_completed_period", result["audit"]
    assert result["selected"]["focus_key"] == period_key
    print("  resurfacing: reversal and newly completed period bypass cooldown; raw day does not  OK")


def _test_timezone_loud() -> None:
    try:
        summary_focus.focus_today({"summary_focus_timezone": "Mars/Phobos"})
    except ValueError:
        print("  timezone: unsupported IANA name rejected loudly  OK")
        return
    raise AssertionError("unsupported timezone should raise loudly")


def _test_memory_migration_backfill(root: Path) -> None:
    import json
    state = {"dataset_id": "ds", "output_folder": str(root / "mig"),
             "summary_memory_root": str(root / "mig_mem")}
    path = summary_memory.store_path(state)
    v1 = {
        "schema_version": 1, "watermark": "2023-12-31", "period_anchor": "2023-12",
        "records": {
            "summary:v1:abc": {
                "angle": "store_overview", "dimension": "Store No", "metric": "revenue",
                "segment": "CFH014", "direction": "increase", "observation_value": 1000.0,
                "first_reported": "2023-12-31T09:00:00", "last_reported": "2023-12-31T09:00:00",
                "times_reported": 1,
            }
        },
        "journal": {},
    }
    path.write_text(json.dumps(v1), encoding="utf-8")
    store, status = summary_memory.load_store(state)
    assert status == "ok"
    assert store["schema_version"] == 3
    assert store["records"], "v1 records must be preserved"
    assert store["focus_records"], "focus_records must be backfilled from v1 records"
    assert "area_records" in store and "weekly_coverage" in store, "v3 channels must be present"
    backfilled = next(iter(store["focus_records"].values()))
    assert backfilled.get("backfilled") is True and backfilled["dimension_role"] == "store"
    print("  memory: v1 store migrates to v2, focus_records backfilled non-destructively  OK")


# --- R2 editorial rhythm tests -----------------------------------------------
def _test_schedule_soft_prior() -> None:
    """A weekday schedule is a soft prior: it flips a tie but not a big gap."""
    category = {**_member("category", "A", 100000), "change_pct": 5.0}
    division = {**_member("division", "B", 100000), "change_pct": 5.0}
    candidates = [category, division]  # equal materiality + staleness
    base = {
        "summary_now_override": "2026-07-01",  # Wednesday
        "summary_focus_cooldown_days": 14, "summary_focus_same_dimension_gap_days": 2,
        "dataset_id": "ds",
    }
    store = summary_memory._empty_store()
    # No schedule: the tie breaks alphabetically on the role -> division.
    plain = summary_focus.select_focus(base, candidates, store, "empty")
    assert plain["selected"]["dimension_role"] == "division", plain["audit"]["role_scores"]
    # Schedule Wednesday -> category flips the tie without any data change.
    scheduled = summary_focus.select_focus(
        {**base, "summary_focus_schedule": {"wednesday": "category"}, "summary_focus_schedule_weight": 0.5},
        candidates, store, "empty",
    )
    assert scheduled["selected"]["dimension_role"] == "category", scheduled["audit"]["role_scores"]
    assert scheduled["audit"]["role_scores"]["category"]["schedule_affinity"] == 0.5
    # The documented inverse shape is case-insensitive and accepts one weekday
    # as a string, not just an array.
    inverse = summary_focus.select_focus(
        {**base, "summary_focus_schedule": {"Category": "Wednesday"},
         "summary_focus_schedule_weight": 0.5},
        candidates, store, "empty",
    )
    assert inverse["selected"]["dimension_role"] == "category", inverse["audit"]
    print("  schedule: both shapes softly flip a tie and record affinity  OK")


def _test_magnitude_override() -> None:
    """A big + material move jumps the role gap; a cooling one does not re-fire."""
    overall = {**_member("overall", "", 1000000), "candidate_kind": "broad", "coverage": "complete"}
    big = {**_member("store", "CFH021", 900000), "change_pct": 35.0}  # 90% share, 35% change
    small = {**_member("category", "SNACKS", 20000), "change_pct": 3.0}
    state = {
        "summary_now_override": "2026-07-11", "summary_focus_cooldown_days": 14,
        "summary_focus_same_dimension_gap_days": 2, "dataset_id": "ds",
        "summary_focus_override_change_pct": 20, "summary_focus_override_min_impact_share_pct": 2,
    }
    # The store role was delivered yesterday (inside the gap) but the big member
    # itself is unseen -> the override lane still lets it jump the gap.
    store = summary_memory._empty_store()
    store["focus_records"]["some_prior_store"] = {
        "dimension_role": "store", "last_reported": "2026-07-10T09:00:00", "times_reported": 1,
    }
    result = summary_focus.select_focus(state, [overall, big, small], store, "ok")
    assert result["audit"]["reason"] == "material_override", result["audit"]
    assert result["selected"]["focus_key"] == big["focus_key"]

    # The dual threshold blocks a large percentage on a trivial share.
    trivial = {**_member("category", "GUM", 500), "change_pct": 80.0}
    result_trivial = summary_focus.select_focus(
        state, [overall, trivial], summary_memory._empty_store(), "empty"
    )
    assert result_trivial["audit"]["reason"] != "material_override", result_trivial["audit"]

    # A partial aggregate is not a reconciled denominator and therefore cannot
    # authorize the share threshold.
    partial_total = {**overall, "coverage": "partial"}
    no_denominator = summary_focus.select_focus(
        state, [partial_total, big], summary_memory._empty_store(), "empty"
    )
    assert no_denominator["audit"]["reason"] != "material_override", no_denominator["audit"]

    # A big move that is itself cooling and unchanged in direction must not
    # re-fire the override day after day (only a reversal would).
    cooling = summary_memory._empty_store()
    cooling["focus_records"][big["focus_key"]] = {
        "dimension_role": "store", "last_reported": "2026-07-10T09:00:00",
        "times_reported": 1, "last_direction": "increase",
    }
    result_cool = summary_focus.select_focus(state, [overall, big, small], cooling, "ok")
    assert result_cool["audit"]["reason"] != "material_override", result_cool["audit"]
    assert result_cool["selected"]["focus_key"] != big["focus_key"], "a cooling big move must not re-fire"

    # A large schedule weight must not steer the override lane. Both members
    # qualify, but the materially larger unscheduled focus still wins.
    scheduled_small = {**_member("division", "B", 100000), "change_pct": 40.0}
    bypass = summary_focus.select_focus(
        {**state, "summary_focus_schedule": {"friday": "division"},
         "summary_focus_schedule_weight": 10.0},
        [overall, big, scheduled_small], summary_memory._empty_store(), "empty",
    )
    assert bypass["audit"]["reason"] == "material_override", bypass["audit"]
    assert bypass["selected"]["focus_key"] == big["focus_key"], bypass["audit"]
    assert bypass["audit"]["magnitude_override_schedule_applied"] is False
    print("  override: jumps schedule/gap; trivial and cooling moves do not re-fire  OK")


def _test_sentiment() -> None:
    assert summary_focus._sentiment(_member("category", "A", 100000)) == "opportunity"
    assert summary_focus._sentiment(_member("category", "B", -100000)) == "risk"
    assert summary_focus._sentiment({"observation_value": 0}) == "mixed"
    assert summary_focus._sentiment({"direction": "decrease", "observation_value": 10}) == "risk"
    result = summary_focus.select_focus(
        {"summary_now_override": "2026-07-01", "dataset_id": "ds"},
        [_member("category", "A", 100000)], summary_memory._empty_store(), "empty",
    )
    assert result["sentiment"] == "opportunity" and result["audit"]["sentiment"] == "opportunity"
    print("  sentiment: opportunity/risk/mixed derived from direction  OK")


def _test_daily_trend_gate() -> None:
    profile = {
        "time_dimensions": [{"table": "Sales", "column": "Doc Date", "reference": "'Calendar'[Doc Date]"}],
    }
    revenue_family = {"source_table": "Sales"}
    base = {"summary_focus_include_trend": True, "summary_focus_daily_trend_enabled": True,
            "summary_now_override": "2026-07-15", "summary_focus_daily_trend_min_days": 14}

    def context(**over):
        return {**base, "summary_period_context": {
            "freshness_status": over.get("freshness", "current"),
            "data_as_of": over.get("data_as_of", "2026-07-14"),
            "checks": [{
                "column": "Doc Date", "verdict": over.get("verdict", "ok"), "grain": "day",
                "periods": over.get("periods", 60),
                "data_as_of": over.get("axis_data_as_of", over.get("data_as_of", "2026-07-14")),
            }],
        }}

    # The candidate axis's own bound is authoritative even when a different
    # global watermark looks safe.
    dim, note = summary_focus_evidence._select_trend_dimension(
        context(data_as_of="2026-07-14", axis_data_as_of="2026-07-20"), profile, revenue_family
    )
    assert dim is None and note["status"] == "gated" and "future" in note["reason"], note
    # Stale data is rejected.
    _, stale = summary_focus_evidence._select_trend_dimension(context(freshness="stale"), profile, revenue_family)
    assert stale["status"] == "gated" and "freshness" in stale["reason"], stale
    # Too little history is rejected.
    _, short = summary_focus_evidence._select_trend_dimension(context(periods=5), profile, revenue_family)
    assert short["status"] == "gated" and "history" in short["reason"], short
    # Batch/load behavior and missing observed evidence cannot silently pass.
    _, batch = summary_focus_evidence._select_trend_dimension(context(verdict="batch_date"), profile, revenue_family)
    assert batch["status"] == "gated" and "batch/load" in batch["reason"], batch
    missing_state = {**base, "summary_period_context": {
        "freshness_status": "current", "data_as_of": "2026-07-14", "checks": [],
    }}
    _, missing = summary_focus_evidence._select_trend_dimension(missing_state, profile, revenue_family)
    assert missing["status"] == "gated" and "observed" in missing["reason"], missing
    # A clean, current, well-populated day axis passes and is selected.
    passed_dim, passed = summary_focus_evidence._select_trend_dimension(context(), profile, revenue_family)
    assert passed["status"] == "passed" and passed_dim is not None and passed_dim.get("grain") == "day", passed
    # With the feature disabled the day axis is never even considered.
    disabled_dim, disabled_note = summary_focus_evidence._select_trend_dimension(
        {**context(), "summary_focus_daily_trend_enabled": False}, profile, revenue_family
    )
    assert disabled_dim is None and disabled_note is None

    # A validated day axis is recorded as available when the existing R1
    # preference chooses a coarser, same-fact-table business period.
    mixed_profile = {**profile, "time_dimensions": [
        {"table": "Sales", "column": "Doc Month", "reference": "'Sales'[Doc Month]"},
        *profile["time_dimensions"],
    ]}
    picked, picked_note = summary_focus_evidence._select_trend_dimension(context(), mixed_profile, revenue_family)
    assert picked and picked["grain"] == "month" and picked_note["status"] == "passed"
    print("  daily trend gate: unsafe axes rejected; validated day is active or honestly available  OK")


def _test_daily_trend_runtime(root: Path) -> None:
    """The status is active only after the targeted day query reconciles."""
    profile = _profile()
    profile["time_dimensions"] = [
        {"table": "Calendar", "column": "Doc Date", "reference": "'Calendar'[Doc Date]"},
    ]
    metadata = _metadata()
    metadata["columns"].append({"table": "Calendar", "column": "Doc Date"})
    state = _base_state(
        root,
        semantic_model_profile=profile,
        model_metadata=metadata,
        summary_focus_daily_trend_enabled=True,
        summary_focus_daily_trend_min_days=14,
        summary_stale_after_periods=2,
        summary_now_override="2026-07-15",
        summary_period_context={
            "grain": "day", "freshness_status": "current", "data_as_of": "2026-07-14",
            "checks": [{"column": "Doc Date", "verdict": "ok", "grain": "day",
                        "periods": 30, "data_as_of": "2026-07-14"}],
        },
    )
    diagnostics = {"[__series_total]": 500000.0, "[__focus_total]": 500000.0}
    days = [
        {"'Calendar'[Doc Date]": "2026-07-12", "[revenue_current]": 10000.0,
         "[revenue_prior]": 12000.0, "[revenue_change]": -2000.0, **diagnostics},
        {"'Calendar'[Doc Date]": "2026-07-13", "[revenue_current]": 20000.0,
         "[revenue_prior]": 18000.0, "[revenue_change]": 2000.0, **diagnostics},
        {"'Calendar'[Doc Date]": "2026-07-14", "[revenue_current]": 30000.0,
         "[revenue_prior]": 25000.0, "[revenue_change]": 5000.0, **diagnostics},
    ]
    active = _run_node(state, [], trend_rows=days)["summary_focus_evidence"]["sections"]
    assert active["daily_trend"]["status"] == "active", active["daily_trend"]
    assert active["period_trend"]["grain"] == "day"
    assert all(not any(str(key).startswith("__") for key in row) for row in active["period_trend"]["rows"])

    unreconciled = [{key: value for key, value in row.items() if "__" not in key} for row in days]
    gated = _run_node(state, [], trend_rows=unreconciled)["summary_focus_evidence"]["sections"]
    assert gated["daily_trend"]["status"] == "gated", gated["daily_trend"]
    assert gated["period_trend"] is None
    print("  daily trend runtime: active only after full-series reconciliation  OK")


# --- R3 advanced novelty tests -----------------------------------------------
def _test_overlap_suppression() -> None:
    """A focus that just re-tells a recent story is suppressed for a fresh one."""
    store = summary_memory._empty_store()
    store["recent_focus"] = [{
        "focus_key": "recent_fmcg", "reported_at": "2026-07-14",
        "dimension_role": "category", "segment": "FMCG FOOD",
        "top_pos_contributor": "VEGETABLE OIL", "top_neg_contributor": "SUN FLOWER OIL",
        "leading_location": "CFH021", "driver_class": "rate/mix",
    }]
    state = {
        "summary_now_override": "2026-07-15", "summary_focus_cooldown_days": 14,
        "summary_focus_same_dimension_gap_days": 2, "dataset_id": "ds",
        "summary_focus_fact_overlap_threshold": 0.6, "summary_focus_overlap_window_days": 7,
    }
    # Featuring VEGETABLE OIL today just repeats yesterday's driver; SNACKS is fresh.
    veg = _member("product", "VEGETABLE OIL", 300000)
    snacks = _member("product", "SNACKS", 250000)
    result = summary_focus.select_focus(state, [veg, snacks], store, "ok")
    assert result["selected"]["segment"] == "SNACKS", result["audit"]
    assert result["audit"].get("overlap_suppressed", 0) >= 1

    # If everything overlaps, a mild repeat still ships (never silent), flagged.
    store["recent_focus"][0]["top_neg_contributor"] = "SNACKS"
    forced = summary_focus.select_focus(state, [veg, snacks], store, "ok")
    assert forced["selected"] is not None and forced["audit"].get("overlap_forced") is True

    # A static magnitude candidate must not bypass overlap just because it is
    # large. This is the exact "yesterday's driver becomes today's headline"
    # failure: CFH021 was yesterday's leading location and data did not advance.
    static_store = summary_memory._empty_store()
    static_store["watermark"] = "2026-07-14"
    static_store["recent_focus"] = list(store["recent_focus"])
    overall = {**_member("overall", "", 1000000), "candidate_kind": "broad", "coverage": "complete"}
    cfh021 = {**_member("store", "CFH021", 400000), "change_pct": 35.0}
    fresh = {**_member("category", "FRESH STORY", 250000), "change_pct": 5.0}
    static_state = {
        **state,
        "summary_period_context": {"data_as_of": "2026-07-14"},
        "summary_focus_override_change_pct": 20,
        "summary_focus_override_min_impact_share_pct": 2,
    }
    static = summary_focus.select_focus(static_state, [overall, cfh021, fresh], static_store, "ok")
    assert static["selected"]["focus_key"] != cfh021["focus_key"], static["audit"]
    assert static["audit"].get("magnitude_overlap_suppressed") == 1, static["audit"]

    # Once the data watermark genuinely advances, the same magnitude override
    # is allowed to beat overlap as intended by the resurfacing lane.
    advanced = summary_focus.select_focus(
        {**static_state, "summary_period_context": {"data_as_of": "2026-07-15"}},
        [overall, cfh021, fresh], static_store, "ok",
    )
    assert advanced["audit"]["reason"] == "material_override", advanced["audit"]
    assert advanced["selected"]["focus_key"] == cfh021["focus_key"], advanced["audit"]
    print("  overlap: repeats suppressed; static magnitude gated; new-data override allowed  OK")


def _test_signature_duplicate(root: Path) -> None:
    recent = [{"focus_key": "r1", "reported_at": "2026-07-29",
               "top_pos_contributor": "VEG OIL", "top_neg_contributor": "SUN OIL",
               "leading_location": "CFH021", "driver_class": "rate/mix"}]
    same = {"top_pos_contributor": "veg oil", "top_neg_contributor": "SUN OIL",
            "leading_location": "CFH021", "driver_class": "rate/mix"}
    key, overlap = summary_focus_evidence._signature_duplicate(
        same, recent, 0.6, today=date(2026, 7, 30), window_days=7
    )
    assert key == "r1" and overlap == 1.0, (key, overlap)
    diff = {"top_pos_contributor": "NEW A", "driver_class": "volume"}
    assert summary_focus_evidence._signature_duplicate(diff, recent, 0.6)[0] is None

    # A generic shared driver alone is insufficient evidence of a duplicate.
    sparse = [{"focus_key": "sparse", "reported_at": "2026-07-29", "driver_class": "rate/mix"}]
    assert summary_focus_evidence._signature_duplicate(
        same, sparse, 0.6, today=date(2026, 7, 30), window_days=7
    )[0] is None

    # Even a full signature is irrelevant after the configured recent window.
    old = [{**recent[0], "focus_key": "old", "reported_at": "2026-06-01"}]
    assert summary_focus_evidence._signature_duplicate(
        same, old, 0.6, today=date(2026, 7, 30), window_days=7
    )[0] is None

    # End-to-end: replay the node once, then feed its own signature back as a
    # recent delivery and confirm it is flagged as a duplicate with a caveat.
    calls: list[str] = []
    first = _run_node(_base_state(root), calls)
    signature = first["summary_focus_evidence"]["signature_fields"]
    assert first["summary_focus_evidence"]["signature_duplicate"] is False
    second = _run_node(_base_state(
        root,
        summary_now_override="2026-07-30",
        summary_focus_overlap_window_days=7,
        summary_recent_focus=[{"focus_key": "prev", "reported_at": "2026-07-29", **signature}],
    ), [])
    doc = second["summary_focus_evidence"]
    assert doc["signature_duplicate"] is True and doc["signature_duplicate_of"] == "prev"
    assert any("repeats a recently delivered story" in c for c in doc["caveats"])
    print("  signature: evidence minimum + recency window + duplicate caveat  OK")


def _test_daily_focus_metadata() -> None:
    from src.tools.api_payloads import generate_fresh_report_summary_payload

    fresh = {
        "heading": "FMCG FOOD revenue rose +1.0M", "summary_type": "new_perspective",
        "metrics": [{"label": "Revenue change", "value": "+1.0M", "tone": "teal"}],
        "sections": [{"heading": "What's working", "tone": "positive", "points": ["Revenue rose."]}],
        "data_as_of": "2026-07-14", "grain": "month", "freshness_status": "current",
    }
    focus = {"focus_key": "f", "segment": "FMCG FOOD", "dimension_role": "category",
             "lens": "performance", "sentiment": "opportunity"}
    base = {"fresh_summary": fresh, "summary_selected_focus": focus, "config": {}}
    off = generate_fresh_report_summary_payload(base)
    assert "dailyFocus" not in off, "public metadata must be off by default"
    on = generate_fresh_report_summary_payload({**base, "summary_focus_public_metadata": True})
    assert on["dailyFocus"] == {
        "segment": "FMCG FOOD", "role": "category", "lens": "performance", "sentiment": "opportunity",
    }, on.get("dailyFocus")
    # The core contract is unchanged either way.
    assert set(off) == {"title", "generatedAt", "headline", "metrics", "sections"}
    print("  dailyFocus: additive, code-owned, off by default  OK")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="focus-evidence-replay-") as temp:
        root = Path(temp)
        _test_happy_path(root)
        _test_partial_reconciliation(root)
        _test_hierarchy_runtime_rejection(root)
        _test_budget(root)
        _test_failed_drill_non_fatal(root)
        _test_no_token_reuse_only(root)
        _test_child_discovery_override(root)
        _test_driver_bridge_math()
        _test_query_contracts()
        _test_selection_and_rotation()
        _test_r1_resurface_overrides()
        _test_schedule_soft_prior()
        _test_magnitude_override()
        _test_sentiment()
        _test_daily_trend_gate()
        _test_daily_trend_runtime(root)
        _test_overlap_suppression()
        _test_signature_duplicate(root)
        _test_daily_focus_metadata()
        _test_timezone_loud()
        _test_memory_migration_backfill(root)
    print("summary focus evidence replay: all deterministic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
