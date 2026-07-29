"""Offline acceptance tests for Phase 1 of the rate-outlier lens: honest peer
evidence.

No authentication, LLM, or Power BI call. Builds the real profile/scan portfolio
from a saved ``outputs/model_metadata.json`` (mode gating + budget), then drives
``evidence_contract.assess_peer_eligibility`` with synthetic peer distributions to
exercise completeness, reconciliation, scope, and provenance ordering.

Covers the nine Phase 1 fixtures:
  1. mode off produces no peer queries
  2. peer queries never exceed the remaining scan budget
  3. below-cap result can become complete
  4. cap-hit result remains partial
  5. unfiltered / wrong-scope result is rejected
  6. current/prior/change reconciliation success
  7. each reconciliation failure independently disables the triple
  8. partial evidence remains available to existing detectors
  9. complete evidence is processed before partial evidence
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import evidence_contract, insight_scan_templates  # noqa: E402
from src.agents.insight_stat_detector import _Detector  # noqa: E402
from src.agents.semantic_profiler import build_profile  # noqa: E402
from src.utils.logger import RunLogger  # noqa: E402


# Two additive bundles mirroring the working model: a revenue value bundle
# (current/prior/change) and a transactions volume bundle (current/prior/change).
METRICS = [
    {"alias": "rev_cur", "phase": "current", "family": "revenue", "bundle_id": "B_REV", "semantic_role": "value", "additive_candidate": True},
    {"alias": "rev_prev", "phase": "prior", "family": "revenue", "bundle_id": "B_REV", "semantic_role": "value", "additive_candidate": True},
    {"alias": "rev_chg", "phase": "change", "family": "revenue", "bundle_id": "B_REV", "semantic_role": "value", "additive_candidate": True},
    {"alias": "bills_cur", "phase": "current", "family": "transactions", "bundle_id": "B_TX", "semantic_role": "volume", "additive_candidate": True},
    {"alias": "bills_prev", "phase": "prior", "family": "transactions", "bundle_id": "B_TX", "semantic_role": "volume", "additive_candidate": True},
    {"alias": "bills_chg", "phase": "change", "family": "transactions", "bundle_id": "B_TX", "semantic_role": "volume", "additive_candidate": True},
]

# Four peers whose column sums reconcile exactly to the totals below.
PEER_ROWS = [
    {"cat": "A", "rev_cur": 400.0, "rev_prev": 300.0, "rev_chg": 100.0, "bills_cur": 40, "bills_prev": 30, "bills_chg": 10},
    {"cat": "B", "rev_cur": 300.0, "rev_prev": 320.0, "rev_chg": -20.0, "bills_cur": 30, "bills_prev": 32, "bills_chg": -2},
    {"cat": "C", "rev_cur": 200.0, "rev_prev": 180.0, "rev_chg": 20.0, "bills_cur": 20, "bills_prev": 17, "bills_chg": 3},
    {"cat": "D", "rev_cur": 100.0, "rev_prev": 150.0, "rev_chg": -50.0, "bills_cur": 10, "bills_prev": 11, "bills_chg": -1},
]
TOTALS = {"rev_cur": 1000.0, "rev_prev": 950.0, "rev_chg": 50.0,
          "bills_cur": 100, "bills_prev": 90, "bills_chg": 10}


def _totals_query(totals=None):
    return {"query_name": "meta_comparable_totals", "status": "success",
            "rows": [dict(totals or TOTALS)],
            "contract_hint": {"coverage_kind": "grand_total", "grouping": [], "metrics": METRICS}}


def _peer_query(rows, cap=200, population_status="comparable", grouping=None):
    return {"query_name": "meta_peer_breakdown_by_x_cat", "status": "success", "rows": rows,
            "contract_hint": {
                "coverage_kind": "full_dimension_breakdown",
                "grouping": grouping if grouping is not None
                else [{"reference": "'X'[cat]", "column": "cat"}],
                "topn": cap, "population_status": population_status, "metrics": METRICS}}


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "outputs"
    metadata = json.loads((out / "model_metadata.json").read_text(encoding="utf-8"))
    cfg = json.loads((PROJECT_ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    profile = build_profile(metadata)
    base_state = {**cfg, "model_metadata": metadata, "semantic_model_profile": profile,
                  "insight_stat_recon_tolerance_pct": 2.0}

    def peer_kinds(scans):
        return [q for q in scans
                if (q.get("contract_hint") or {}).get("coverage_kind") == "full_dimension_breakdown"]

    # --- 1. mode off produces no peer queries ---
    off = insight_scan_templates.build_metadata_scans(
        profile, {**base_state, "insight_rate_outlier_mode": "off"})
    assert not peer_kinds(off), "mode 'off' still planned peer scans"
    core_names = [q["name"] for q in off]

    # --- 2. peer queries never exceed the remaining scan budget ---
    max_q = max(1, int(base_state.get("insight_max_scan_queries", 20)))
    max_dims = int(base_state.get("insight_peer_max_dimensions", 5))
    shadow = insight_scan_templates.build_metadata_scans(
        profile, {**base_state, "insight_rate_outlier_mode": "shadow"})
    peers = peer_kinds(shadow)
    assert peers, "mode 'shadow' planned no peer scans"
    assert len(shadow) <= max_q, "scan portfolio exceeded the query ceiling"
    assert len(peers) <= max_dims, "more peer scans than insight_peer_max_dimensions"
    assert [q["name"] for q in shadow][:len(core_names)] == core_names, \
        "core diagnostic portfolio was displaced by peer scans"
    # Under budget pressure (core + 2), exactly the two remaining slots are used.
    tight = insight_scan_templates.build_metadata_scans(
        profile, {**base_state, "insight_rate_outlier_mode": "shadow",
                  "insight_max_scan_queries": len(core_names) + 2})
    assert len(peer_kinds(tight)) == 2, "peer scans did not clamp to the remaining budget"

    # --- 3 & 6. below-cap reconciling breakdown becomes complete + eligible ---
    cov = evidence_contract.assess_peer_eligibility([_totals_query(), _peer_query(PEER_ROWS)], base_state)
    e = cov["'X'[cat]"]
    assert e["completeness"] == "complete", "untruncated breakdown was not complete"
    assert e["eligible"] is True, f"reconciled comparable breakdown rejected: {e['rejection_reason']}"
    assert e["peer_count"] == 4
    assert all(t["reconciled"] for t in e["triples"]), "clean triples failed to reconcile"

    # --- 4. cap-hit result remains partial (and therefore ineligible) ---
    cov = evidence_contract.assess_peer_eligibility(
        [_totals_query(), _peer_query(PEER_ROWS, cap=4)], base_state)
    e = cov["'X'[cat]"]
    assert e["completeness"] == "partial", "truncated breakdown was not marked partial"
    assert e["eligible"] is False and "truncated" in e["rejection_reason"]

    # --- 5. unfiltered / wrong-scope result is rejected ---
    for status in ("unfiltered", "includes_excluded", "scope_ambiguous"):
        cov = evidence_contract.assess_peer_eligibility(
            [_totals_query(), _peer_query(PEER_ROWS, population_status=status)], base_state)
        e = cov["'X'[cat]"]
        assert e["eligible"] is False and "not comparable" in e["rejection_reason"], \
            f"population '{status}' was not rejected"

    # --- 7. each reconciliation failure independently disables its own triple ---
    broken = [dict(r) for r in PEER_ROWS]
    broken[0]["rev_chg"] = 999.0            # revenue change no longer sums to the total
    cov = evidence_contract.assess_peer_eligibility(
        [_totals_query(), _peer_query(broken)], base_state)
    e = cov["'X'[cat]"]
    by_family = {t["family"]: t for t in e["triples"]}
    assert by_family["revenue"]["reconciled"] is False, "broken revenue triple stayed reconciled"
    assert by_family["transactions"]["reconciled"] is True, \
        "intact transactions triple was disabled by an unrelated failure"
    assert e["eligible"] is True and e["eligible_bundle_ids"] == ["B_TX"], \
        "one broken bundle disabled an independently valid metric bundle"
    assert "B_REV" in e["metric_rejections"], "broken bundle reason was not preserved"

    # The detector consumes the bundle-level certificate: the intact bills bundle
    # may run even though revenue failed on the same physical table.
    totals_q, peer_q = _totals_query(), _peer_query(broken)
    contracts = {q["query_name"]: evidence_contract.extract_contract(
        {"query_name": q["query_name"], "rows": q["rows"]}, "", {}, base_state,
        q["contract_hint"]) for q in (totals_q, peer_q)}
    detector_state = {**base_state, "insight_rate_outlier_mode": "report",
                      "insight_rate_min_peers": 4, "insight_rate_z_cutoff": 0.01,
                      "insight_rate_prior_share_floor_pct": 0.0,
                      "insight_rate_exposure_floor_pct": 0.0,
                      "insight_rate_min_abs_impact_pct": 0.0,
                      "max_rows_per_query": 100,
                      "insight_evidence_contracts": contracts,
                      "insight_peer_coverage": cov}
    detected = _Detector(detector_state, RunLogger(detector_state)).run(
        {"queries": [totals_q, peer_q]})["business_candidates"]
    rate_metrics = {c.get("metric") for c in detected
                    if c.get("type") == "peer_growth_rate_outlier"}
    rate_metrics |= {c["peer_rate_evidence"].get("metric") for c in detected
                     if c.get("peer_rate_evidence")}
    assert "bills_cur" in rate_metrics and "rev_cur" not in rate_metrics, \
        "detector ignored the per-bundle eligibility certificate"

    # A missing prior phase disables only that bundle. This is the no-prior-year
    # fallback: rate comparison is unavailable for it, while other valid bundles
    # and all non-rate detectors remain usable.
    missing_prior_metrics = [m for m in METRICS
                             if not (m["bundle_id"] == "B_REV" and m["phase"] == "prior")]
    missing_q = _peer_query(PEER_ROWS)
    missing_q["contract_hint"]["metrics"] = missing_prior_metrics
    cov = evidence_contract.assess_peer_eligibility([_totals_query(), missing_q], base_state)
    e = cov["'X'[cat]"]
    by_family = {t["family"]: t for t in e["triples"]}
    assert by_family["revenue"]["eligible"] is False \
        and by_family["revenue"]["missing_phases"] == ["prior"], \
        "missing prior-year phase did not disable the affected rate bundle"
    assert by_family["transactions"]["eligible"] is True and e["eligible"] is True, \
        "missing prior-year data in one metric disabled an unrelated valid bundle"

    # --- 8. partial evidence still yields a usable contract for existing detectors ---
    trunc_q = _peer_query(PEER_ROWS, cap=4)
    contract = evidence_contract.extract_contract(
        {"query_name": trunc_q["query_name"], "rows": trunc_q["rows"]},
        "EVALUATE TOPN(4, ...)", metadata, base_state, trunc_q["contract_hint"])
    assert contract["completeness"] == "partial", "truncated peer contract was not partial"
    assert contract["metrics"], "partial peer evidence lost its metrics (dropped from detectors)"
    assert contract["coverage_kind"] == "full_dimension_breakdown"
    # A complete breakdown reports complete through the same public contract path.
    complete_q = _peer_query(PEER_ROWS)
    complete_contract = evidence_contract.extract_contract(
        {"query_name": complete_q["query_name"], "rows": complete_q["rows"]},
        "EVALUATE TOPN(200, ...)", metadata, base_state, complete_q["contract_hint"])
    assert complete_contract["completeness"] == "complete"

    # --- 9. complete evidence is processed before partial evidence ---
    rank = evidence_contract.evidence_quality_rank
    assert rank("complete", "comparable") == 0
    assert rank("complete", "unfiltered") == 1
    assert rank("partial", "comparable") == 2
    tables = [("partial_cmp", "partial", "comparable"),
              ("complete_unf", "complete", "unfiltered"),
              ("complete_cmp", "complete", "comparable")]
    ordered = sorted(tables, key=lambda t: rank(t[1], t[2]))
    assert [t[0] for t in ordered] == ["complete_cmp", "complete_unf", "partial_cmp"], \
        "evidence-quality ordering did not put complete+comparable first"

    print("peer evidence replay: OK")
    print(f"  core scans: {len(core_names)}; peer scans (shadow): {len(peers)}; "
          f"budget ceiling: {max_q}")
    print("  9/9 Phase 1 fixtures passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
