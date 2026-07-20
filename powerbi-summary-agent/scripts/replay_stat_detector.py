"""Offline replay for the deterministic stat detector (Wave 2).

Runs src/agents/insight_stat_detector.py against a saved
insight_clean_data.json - no auth, no LLM, no Power BI round-trip.
Also runs a synthetic edge-case suite (Infinity/NaN/null/text columns,
empty tables, zero spread) to prove the node degrades instead of raising.

Run from the project dir:

    python scripts/replay_stat_detector.py                 # uses outputs/insight_clean_data.json
    python scripts/replay_stat_detector.py path/to.json    # any saved scan
    python scripts/replay_stat_detector.py --synthetic     # edge cases only

Artifacts go to outputs_replay/ so real run outputs are never touched.
"""

import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import insight_stat_detector  # noqa: E402


def _base_state() -> dict:
    cfg = json.loads((PROJECT_ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    state = {k: v for k, v in cfg.items() if k.startswith("insight_stat_")}
    state["max_rows_per_query"] = cfg.get("max_rows_per_query", 15)
    state["output_folder"] = "outputs_replay"
    return state


def replay(clean_path: Path) -> dict:
    state = _base_state()
    state["insight_clean_data"] = json.loads(clean_path.read_text(encoding="utf-8"))
    updates = insight_stat_detector.run(state)
    return updates["insight_stat_candidates"]


def synthetic_suite() -> dict:
    """Nasty table shapes the detector must survive without raising."""
    inf, nan = float("inf"), float("nan")
    queries = [
        # empty rows
        {"query_name": "empty", "status": "success", "rows": []},
        # failed query (must be skipped)
        {"query_name": "failed", "status": "failed", "error": "boom"},
        # all-null column, text-only table
        {"query_name": "text_only", "status": "success",
         "rows": [{"a": "x", "b": None}, {"a": "y", "b": None}]},
        # Infinity / NaN mixed into an otherwise valid triple
        {"query_name": "nonfinite", "status": "success", "rows": [
            {"seg": "A", "cur": 100.0, "prev": 80.0, "chg": 20.0},
            {"seg": "B", "cur": inf, "prev": 50.0, "chg": nan},
            {"seg": "C", "cur": 60.0, "prev": 0.0, "chg": 60.0},
            {"seg": "D", "cur": 30.0, "prev": 40.0, "chg": -10.0},
        ]},
        # zero spread (non-differentiating) + mixed types in one column
        {"query_name": "flat", "status": "success", "rows": [
            {"seg": s, "metric": 5.0, "mixed": (1 if s == "A" else "oops")}
            for s in "ABCDE"
        ]},
        # single-row grand totals
        {"query_name": "totals", "status": "success",
         "rows": [{"cur": 190.0, "prev": 170.0, "chg": 20.0}]},
        # date series with one unparseable date and a level shift
        {"query_name": "series", "status": "success", "rows": [
            {"d": f"2026-01-{i:02d}T00:00:00", "v": (10.0 if i <= 6 else 50.0)}
            for i in range(1, 13)
        ]},
    ]
    state = _base_state()
    state["insight_clean_data"] = {
        "query_count": len(queries),
        "successful": sum(1 for q in queries if q["status"] == "success"),
        "queries": queries,
    }
    updates = insight_stat_detector.run(state)
    return updates["insight_stat_candidates"]


def synthetic_period_suite() -> dict:
    """A gate-validated monthly period_series exercising the enhanced period():
    reconciled % (via a grand-total table), month-name labels, the worst-period
    drill (via state), sustained-run / reversal / value-volume-divergence patterns,
    and null-member exclusion."""
    rev_chg = [1.2, -0.8, 0.3, -0.5, 0.4, -0.8, 0.2, -1.3, -0.5, -1.7, -0.7, -0.16]  # ends in a decline run
    rows = []
    for i in range(12):
        rows.append({
            "DOC_MONTH": float(i + 1),
            "rev_cur": (10.0 + rev_chg[i]) * 1e6, "rev_prev": 10.0 * 1e6,
            "rev_chg": rev_chg[i] * 1e6,
            # volume rises every month -> months with falling revenue diverge
            "qty_cur": 5.5e6, "qty_prev": 5.0e6, "qty_chg": 0.5e6,
        })
    rows.append({"DOC_MONTH": None, "rev_cur": 1e5, "rev_prev": 0.0, "rev_chg": 1e5,
                 "qty_cur": 1.0, "qty_prev": 0.0, "qty_chg": 1.0})  # null member -> excluded
    totals = {"rev_chg": sum(rev_chg) * 1e6, "qty_chg": 0.5e6 * 12}   # grand totals for reconciliation
    roles = {
        "rev_cur": {"bundle_id": "F::revenue", "phase": "current", "semantic_role": "value"},
        "rev_prev": {"bundle_id": "F::revenue", "phase": "prior", "semantic_role": "value"},
        "rev_chg": {"bundle_id": "F::revenue", "phase": "change", "semantic_role": "value"},
        "qty_cur": {"bundle_id": "F::quantity", "phase": "current", "semantic_role": "volume"},
        "qty_prev": {"bundle_id": "F::quantity", "phase": "prior", "semantic_role": "volume"},
        "qty_chg": {"bundle_id": "F::quantity", "phase": "change", "semantic_role": "volume"}}
    contract = {"coverage_kind": "period_series", "grouping_references": ["'F'[DOC_MONTH]"],
                "metric_roles": roles}
    totals_contract = {"coverage_kind": "grand_total", "grouping_references": [], "metric_roles": roles}
    state = _base_state()
    state.update({"insight_period_top_movers": 4, "insight_period_recent_window": 12,
                  "insight_candidates_high": 20, "insight_candidates_period": 20,
                  "insight_candidates_daily": 10,
                  "insight_evidence_contracts": {"meta_period": contract, "meta_totals": totals_contract},
                  "insight_temporal_drill": {"period_raw": "10.0", "period_label": "October",
                      "top_segments": [{"segment": "Technology", "change": -1.2e6},
                                       {"segment": "Consumer Goods", "change": -0.5e6}]}})
    state["insight_clean_data"] = {"queries": [
        {"query_name": "meta_totals", "status": "success", "rows": [totals]},
        {"query_name": "meta_period", "status": "success", "rows": rows}]}
    return insight_stat_detector.run(state)["insight_stat_candidates"]


def show(result: dict, label: str) -> None:
    print(f"\n=== {label} ===")
    print(f"grand totals seen: {list(result.get('grand_totals_seen', {}))}")
    print(f"additive metrics:  {result.get('additive_metrics')}")
    print(f"ratio metrics:     {result.get('ratio_metrics')}")
    for pool in ("business_candidates", "data_quality_candidates"):
        cands = result.get(pool, [])
        print(f"\n{pool} ({len(cands)}):")
        for c in cands:
            print(f"  [{c['score']:8.2f}] {c['id']}: {c['detail']}")
    # every candidate payload must be JSON-safe (no inf/nan survives json.dumps
    # with allow_nan=False)
    json.dumps(result, allow_nan=False, default=str)
    print("\nJSON-safety check passed (no Infinity/NaN in payload).")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--synthetic" in args:
        show(synthetic_suite(), "synthetic edge cases")
        return 0
    src = Path(args[0]) if args else PROJECT_ROOT / "outputs" / "insight_clean_data.json"
    show(replay(src), f"replay of {src}")
    show(synthetic_suite(), "synthetic edge cases")
    period = synthetic_period_suite()
    show(period, "synthetic period series (Phase 2)")
    cands = period["business_candidates"]
    by_type = {}
    for c in cands:
        by_type.setdefault(c["type"], []).append(c)
    movers = by_type.get("period_change_contribution", [])
    oct_c = next((c for c in movers if c.get("period_label") == "October"), None)
    assert movers, "expected period_change_contribution candidates"
    assert len(movers) <= 4 and all("None" not in c["segment"] for c in movers), \
        "null period member must be excluded and top-movers capped"
    assert oct_c is not None, "October (month 10) should be labelled and present"
    assert oct_c.get("impact_share") is not None and 35 <= abs(oct_c["impact_share"]) <= 45, \
        f"October should reconcile to ~39% of the change, got {oct_c.get('impact_share')}"
    assert "Technology" in oct_c["detail"], "worst-period drill should attach the primary segment"
    assert by_type.get("period_sustained_decline"), "expected a sustained-decline run"
    assert by_type.get("period_reversal"), "expected a reversal"
    assert by_type.get("period_value_volume_divergence"), "expected a value/volume divergence"
    print(f"\nPeriod check passed: {len(movers)} movers (Oct {oct_c['impact_share']:.1f}%, "
          f"drill attached), patterns: "
          f"{[t for t in by_type if t.startswith('period_') and t != 'period_change_contribution']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
