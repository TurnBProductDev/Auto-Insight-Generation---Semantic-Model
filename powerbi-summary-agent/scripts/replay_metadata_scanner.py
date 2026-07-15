"""Offline verification for the metadata-driven scanner.

Uses a saved ``outputs/model_metadata.json`` plus config.  No authentication,
LLM, or Power BI call is made.  The script fails fast if generated templates
reference invalid objects, scope enforcement misses an excluded/unfiltered
comparison, provenance overstates partial coverage, or the exact price/volume
identity stops reconciling.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import evidence_contract, evidence_assembler, insight_scan_templates  # noqa: E402
from src.agents.dax_validator import validate_one  # noqa: E402
from src.agents.insight_investigator import _adaptive_budget  # noqa: E402
from src.agents.insight_stat_detector import (  # noqa: E402
    _append_entity_lifecycle_candidates,
    _rate_volume_split,
)
from src.agents.scope_validator import validate_comparable_scope  # noqa: E402
from src.agents.semantic_profiler import build_profile  # noqa: E402


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "outputs"
    metadata = json.loads((out / "model_metadata.json").read_text(encoding="utf-8"))
    cfg = json.loads((PROJECT_ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    profile = build_profile(metadata)
    assert profile.get("primary_value_bundle"), "no primary current/prior value bundle"
    assert profile.get("fact_table"), "no primary fact table"
    state = {
        **cfg,
        "model_metadata": metadata,
        "semantic_model_profile": profile,
        "resolved_entity_scope": {
            "entity_dimension": profile.get("entity_dimension"),
            "active_comparable_population": cfg.get("insight_comparable_population", []),
            "excluded_from_comparison": cfg.get("insight_excluded_entities", []),
        },
    }

    scans = insight_scan_templates.build_metadata_scans(profile, state)
    assert scans, "metadata scan portfolio is empty"
    for query in scans:
        reasons = validate_one(query["dax"], metadata)
        reasons += validate_comparable_scope(query["dax"], state, query.get("contract_hint"))
        assert not reasons, f"{query['name']}: {reasons}"

    # The exact failure mode from the saved run: comparative measure with no
    # entity scope must be rejected; an excluded entity must also be rejected.
    primary = profile["primary_value_bundle"]
    prior = primary["measures"].get("prior")
    if prior and profile.get("entity_dimension") and cfg.get("insight_comparable_population"):
        unscoped = f'EVALUATE ROW("Prior", [{prior}])'
        assert validate_comparable_scope(unscoped, state), "unscoped comparison was accepted"
        excluded = (cfg.get("insight_excluded_entities") or [None])[0]
        if excluded:
            ref = profile["entity_dimension"]["reference"]
            bad = f'EVALUATE ROW("Prior", CALCULATE([{prior}], TREATAS({{"{excluded}"}}, {ref})))'
            assert validate_comparable_scope(bad, state), "excluded entity comparison was accepted"
            current = primary["measures"].get("current")
            comparable = cfg["insight_comparable_population"][0]
            mixed_safe = (
                'EVALUATE ROW('
                f'"Comparable prior", CALCULATE([{prior}], TREATAS({{"{comparable}"}}, {ref})), '
                f'"New current", CALCULATE([{current}], TREATAS({{"{excluded}"}}, {ref})))'
            )
            assert not validate_comparable_scope(mixed_safe, state), (
                "isolated current-only actual was incorrectly rejected")

    # Period-like words in non-business measures (for example a "last refresh"
    # timestamp) must not accidentally trigger comparable-scope enforcement.
    unrelated_prior = next((name for name, role in profile.get("measure_roles", {}).items()
                            if role.get("phase") == "prior" and role.get("family") == "other"), None)
    if unrelated_prior:
        assert not validate_comparable_scope(
            f'EVALUATE ROW("Status", [{unrelated_prior}])', state), (
            f"non-bundled status measure was treated as comparison: {unrelated_prior}")

    # Construction-time partial coverage must never become an answered drill.
    sample = scans[1]
    n = int(sample["contract_hint"].get("topn") or 2)
    fake_rows = [{sample["contract_hint"]["grouping"][0]["column"]: f"S{i}"}
                 for i in range(n)]
    contract = evidence_contract.extract_contract(
        {"query_name": sample["name"], "rows": fake_rows}, sample["dax"], metadata,
        state, sample["contract_hint"],
    )
    assert contract["completeness"] == "partial", "ranked/truncated coverage was overstated"
    assert not evidence_assembler._safe_coverage_reuse(contract, "comparable", True)

    # Concentration candidates carry several exact member values.  They must
    # become a multi-value TREATAS filter, not one comma-joined fake member.
    shape = insight_scan_templates.shape_from_profile(profile, state)
    dims = shape.get("dimensions", [])
    if dims and profile.get("entity_dimension"):
        built = insight_scan_templates.build_gap_probe(
            shape, dims[0], ["Alpha", "Beta"], profile["entity_dimension"],
            cfg.get("insight_comparable_population", []), 20,
        )
        dax = built["dax"]
        assert 'TREATAS({"Alpha", "Beta"}' in dax
        assert built["contract_hint"]["segment_filter"]["values"] == ["Alpha", "Beta"]
        time_dims = profile.get("time_dimensions", [])
        if time_dims:
            dated = insight_scan_templates.build_gap_probe(
                shape, time_dims[0], "2026-06-30 00:00:00",
                profile["entity_dimension"], cfg.get("insight_comparable_population", []), 20,
            )
            assert "DATE(2026, 6, 30)" in dated["dax"]
            assert 'TREATAS({"2026-06-30' not in dated["dax"]

    # Exact price/volume identity and the normal 0-3 shared budget.
    split = _rate_volume_split(
        {"R1": 132.0, "R0": 100.0, "Q1": 12.0, "Q0": 10.0},
        {"current": "R1", "prior": "R0", "change": "dR"},
        {"current": "Q1", "prior": "Q0", "change": "dQ"},
    )
    assert split and split["reconciled"]
    assert abs(split["volume_effect"] + split["rate_effect"] - 32.0) < 1e-6
    brief = {"recommended_probes": [{}, {}, {}], "scope_type": "comparable"}
    assert _adaptive_budget(state, brief, 0) <= 3
    assert _adaptive_budget(state, brief, 3) == 0

    # Lifecycle scope candidates must survive even when the materiality list is
    # already at its cap, because downstream scope typing depends on them.
    scope_path = out / "resolved_entity_scope.json"
    baseline_path = out / "baseline_scope_evidence.json"
    if scope_path.exists() and baseline_path.exists():
        lifecycle_state = {
            **state,
            "resolved_entity_scope": json.loads(scope_path.read_text(encoding="utf-8")),
            "baseline_scope_evidence": json.loads(baseline_path.read_text(encoding="utf-8")),
            "insight_stat_max_candidates": 20,
        }
        saturated = {
            "business_candidates": [
                {"type": "change_contribution", "score": 100 - i, "segment": f"S{i}"}
                for i in range(20)
            ],
            "data_quality_candidates": [],
        }
        _append_entity_lifecycle_candidates(saturated, lifecycle_state)
        if lifecycle_state["resolved_entity_scope"].get("new_entities"):
            assert any(c.get("type") == "new_entity_current_only"
                       for c in saturated["business_candidates"]), (
                "current-only lifecycle candidate was displaced at the cap")

    print("metadata scanner replay: OK")
    print(f"  primary: {primary['id']} -> {primary['measures']}")
    print(f"  entity: {(profile.get('entity_dimension') or {}).get('reference')}")
    print(f"  scans: {len(scans)}; dimensions: {len(profile.get('dimensions', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
