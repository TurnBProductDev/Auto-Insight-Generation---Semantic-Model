"""Offline replay for the Phase-9 joint-interaction thesis linker.

No auth or LLM. Power BI execution is replaced with a deterministic one-row
fixture while the real query builder, candidate routing, cache, and interaction
math are exercised.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import insight_thesis_linker as tl  # noqa: E402
from src.agents import insight_scan_templates as tpl  # noqa: E402
from src.main import build_initial_state  # noqa: E402


_FAILURES = []


def check(cond: bool, msg: str) -> None:
    print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    if not cond:
        _FAILURES.append(msg)


STORE = {"table": "F", "column": "STORE", "reference": "'F'[STORE]", "data_type": "string"}
CATEGORY = {"table": "F", "column": "CATEGORY", "reference": "'F'[CATEGORY]", "data_type": "string"}
MONTH = {"table": "F", "column": "MONTH", "reference": "'F'[MONTH]", "data_type": "int64"}
BUNDLE = {"id": "B_REV", "family": "revenue", "measures": {
    "current": "REV_CURRENT", "prior": "REV_PRIOR", "change": "REV_CHANGE"},
    "derived": {}, "additive_candidate": True}
PROFILE = {"primary_value_bundle": BUNDLE, "measure_bundles": [BUNDLE],
           "entity_dimension": STORE, "dimensions": [CATEGORY], "time_dimensions": [MONTH]}
CONTRACTS = {
    "store_table": {"grouping_references": [STORE["reference"]], "metric_roles": {
        "REV_CHANGE": {"phase": "change", "bundle_id": "B_REV", "family": "revenue"}}},
    "month_table": {"grouping_references": [MONTH["reference"]], "metric_roles": {
        "REV_CHANGE": {"phase": "change", "bundle_id": "B_REV", "family": "revenue"}}},
    "category_table": {"grouping_references": [CATEGORY["reference"]], "metric_roles": {
        "REV_CHANGE": {"phase": "change", "bundle_id": "B_REV", "family": "revenue"}}},
}


def _sig(sid: str, segment, dimension: dict, table: str, impact=-100.0, **over) -> dict:
    base = {"id": sid, "kind": "business", "affected_segment": str(segment),
            "evidence_segment": segment, "dimension": dimension["reference"],
            "bundle_id": "B_REV", "metric": "REV_CHANGE", "evidence_query": table,
            "impact_value": impact, "period_anchor": "2026-03",
            "candidate_type": "change_contribution"}
    base.update(over)
    return base


def _state(signals, enabled=True, **over) -> dict:
    state = {"output_folder": "outputs_replay", "workspace_id": "W", "dataset_id": "D",
             "insight_thesis_linking_enabled": enabled, "insight_thesis_max_links": 2,
             "insight_thesis_min_shared": 2, "insight_thesis_interaction_tol": 0.15,
             "insight_thesis_min_impact": 0.0, "semantic_model_profile": PROFILE,
             "insight_evidence_contracts": CONTRACTS,
             "resolved_entity_scope": {"entity_dimension": STORE,
                                       "active_comparable_population": ["S1", "S2"]},
             "insight_comparable_population": ["S1", "S2"],
             "insight_signals": signals, "insight_query_cache": {},
             "model_metadata": {}, "logs": [], "errors": []}
    state.update(over)
    return state


def _row(cell_cur, cell_prior, a_cur, a_prior, b_cur, b_prior,
         overall_cur=1000.0, overall_prior=1000.0):
    return {"cell_current": cell_cur, "cell_prior": cell_prior,
            "facet_a_current": a_cur, "facet_a_prior": a_prior,
            "facet_b_current": b_cur, "facet_b_prior": b_prior,
            "overall_current": overall_cur, "overall_prior": overall_prior}


class _MockExecution:
    def __init__(self, row):
        self.row = row
        self.calls = 0

    def __call__(self, _workspace, _dataset, queries, token=None):
        self.calls += 1
        name = queries[0]["name"]
        return {name: {"status": "success", "result": {"fixture_rows": [self.row]}}}


def _run_with_row(state: dict, row: dict):
    mock = _MockExecution(row)
    old_execute, old_extract = tl.pbi.execute_python, tl.pbi.extract_rows
    old_validate, old_scope = tl.validate_one, tl.validate_comparable_scope
    try:
        tl.pbi.execute_python = mock
        tl.pbi.extract_rows = lambda result: result["fixture_rows"]
        tl.validate_one = lambda _dax, _metadata: []
        tl.validate_comparable_scope = lambda _dax, _state, _hint: []
        return tl.run(state), mock.calls
    finally:
        tl.pbi.execute_python, tl.pbi.extract_rows = old_execute, old_extract
        tl.validate_one, tl.validate_comparable_scope = old_validate, old_scope


def test_builder_and_gate() -> None:
    print("\n=== builder and gate ===")
    built = tpl.build_thesis_interaction_scan(
        tpl.shape_from_profile(PROFILE), BUNDLE,
        {"dimension": STORE, "values": ["S1"]},
        {"dimension": MONTH, "values": [3]}, ["S1", "S2"])
    check(built is not None and all(alias in built["dax"] for alias in
          ("cell_current", "facet_a_current", "facet_b_current", "overall_current")),
          "joint query contains the intersection, both marginals, and overall cells")
    a = _sig("a", "S1", STORE, "store_table")
    b = _sig("b", 3, MONTH, "month_table", candidate_type="period_change_contribution", anchor=3)
    check(tl.run(_state([a, b], enabled=False))["insight_theses"] == [],
          "disabled gate produces no thesis and no query")
    wired = build_initial_state({"tenant_id": "T", "workspace_id": "W", "dataset_id": "D",
                                 "insight_thesis_linking_enabled": True,
                                 "insight_thesis_max_links": 7,
                                 "insight_thesis_interaction_tol": 0.25})
    check(wired["insight_thesis_linking_enabled"] is True
          and wired["insight_thesis_max_links"] == 7
          and wired["insight_thesis_interaction_tol"] == 0.25,
          "thesis config values are copied into runtime state")


def test_interaction_semantics() -> None:
    print("\n=== joint interaction semantics ===")
    a = _sig("a", "S1", STORE, "store_table")
    b = _sig("b", 3, MONTH, "month_table", candidate_type="period_change_contribution", anchor=3)

    # Store ratio .8 and month ratio .9 predict an independent intersection ratio
    # of .72 when overall is flat. An actual .50 is an extra decline: one event is
    # supported by the joint cell.
    out, calls = _run_with_row(_state([a, b]), _row(500, 1000, 800, 1000, 900, 1000))
    thesis = out["insight_theses"][0]
    check(calls == 1, "exactly one bounded joint query is issued for one candidate pair")
    check(thesis["verdict"] == "same_movement"
          and thesis["basis"] == "interaction_exceeds_independence"
          and thesis["interaction"] < -0.15,
          "an extra intersection decline supports a hedged same-movement thesis")

    out, _ = _run_with_row(_state([a, b]), _row(720, 1000, 800, 1000, 900, 1000))
    thesis = out["insight_theses"][0]
    check(thesis["verdict"] == "related" and thesis["basis"] == "independence_consistent",
          "an intersection equal to independent main effects is not called one event")

    sparse = {"intersection": (0.0, 1000.0), "facet_a": (800.0, 1000.0),
              "facet_b": (900.0, 1000.0), "overall": (1000.0, 1000.0)}
    check(tl.interaction_verdict(sparse, -1, 0.15)["basis"] == "sparse_evidence",
          "a non-positive intersection falls back to related/sparse evidence")


def test_no_false_same_dimension_link() -> None:
    print("\n=== unrelated peers do not link ===")
    a = _sig("a", "TVS", CATEGORY, "category_table")
    b = _sig("b", "PHONES", CATEGORY, "category_table")
    out, calls = _run_with_row(_state([a, b]), _row(500, 1000, 800, 1000, 900, 1000))
    check(out["insight_theses"] == [] and calls == 0,
          "same-rate members of one dimension are not mistaken for a joint thesis")


def test_cache_and_cap() -> None:
    print("\n=== cache and bounded cap ===")
    store = _sig("store", "S1", STORE, "store_table", impact=-300)
    month = _sig("month", 3, MONTH, "month_table", impact=-200,
                 candidate_type="period_change_contribution", anchor=3)
    category = _sig("category", "TVS", CATEGORY, "category_table", impact=-100)
    state = _state([store, month, category], insight_thesis_max_links=1)
    out, calls = _run_with_row(state, _row(500, 1000, 800, 1000, 900, 1000))
    check(len(out["insight_theses"]) == 1 and calls == 1,
          "max_links bounds both selected links and REST calls")
    replay_state = {**state, "insight_query_cache": out["insight_query_cache"]}
    out2, calls2 = _run_with_row(replay_state, _row(1, 1, 1, 1, 1, 1))
    check(calls2 == 0 and out2["insight_theses"][0]["cache_hit"] is True,
          "the shared DAX-hash cache makes a repeated joint query free")


def main() -> int:
    test_builder_and_gate()
    test_interaction_semantics()
    test_no_false_same_dimension_link()
    test_cache_and_cap()
    print("\n" + "=" * 50)
    if _FAILURES:
        print(f"{len(_FAILURES)} CHECK(S) FAILED:")
        for failure in _FAILURES:
            print(f"  - {failure}")
        return 1
    print("All thesis-linker replay checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
