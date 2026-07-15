"""Offline replay for the evidence layer (contracts + assembler + price/volume).

Runs, with no auth / no LLM / no Power BI round-trip, against a completed run's
saved artifacts in outputs/:

  * re-computes stat candidates with the new price/volume split and prints the
    exact volume/rate decomposition per material mover;
  * contracts every scan table and prints its population_status + completeness
    (proving the business-rule scope classifier works on the real DAX);
  * assembles a per-signal brief and prints the reuse vs gap summary;
  * cross-checks the brief against the run's ACTUAL investigation probes
    (insight_investigations.json) to quantify how many executed probes the
    reuse path would have avoided.

Run from the project dir:

    python scripts/replay_evidence_assembler.py                 # uses outputs/
    python scripts/replay_evidence_assembler.py path/to/outputs # any saved run

Artifacts go to outputs_replay/ so real run outputs are never touched.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import (insight_stat_detector, evidence_assembler, evidence_contract,
                        semantic_profiler)  # noqa: E402


def _load(out: Path, name: str, default):
    p = out / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _state(out: Path) -> dict:
    cfg = json.loads((PROJECT_ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    state = {k: v for k, v in cfg.items()
             if k.startswith("insight_") or k == "max_rows_per_query"}
    state["output_folder"] = "outputs_replay"
    state["model_metadata"] = _load(out, "model_metadata.json", {})
    state["semantic_model_profile"] = semantic_profiler.build_profile(state["model_metadata"])
    state["resolved_entity_scope"] = _load(out, "resolved_entity_scope.json", {
        "entity_dimension": state["semantic_model_profile"].get("entity_dimension"),
        "active_comparable_population": state.get("insight_comparable_population", []),
        "excluded_from_comparison": state.get("insight_excluded_entities", []),
        "source": "replay_config",
    })
    state["baseline_scope_evidence"] = _load(out, "baseline_scope_evidence.json", {})
    state["insight_comparable_population"] = state["resolved_entity_scope"].get(
        "active_comparable_population", state.get("insight_comparable_population", []))
    state["insight_excluded_entities"] = state["resolved_entity_scope"].get(
        "excluded_from_comparison", state.get("insight_excluded_entities", []))
    state["insight_clean_data"] = _load(out, "insight_clean_data.json", {"queries": []})
    state["insight_validated_dax_queries"] = _load(out, "insight_validated_dax_queries.json", [])
    state["insight_signals"] = _load(out, "insight_signals.json", [])
    return state


def _pv_row(label: str, rv: dict) -> None:
    dR, vol, rate = rv["revenue_change"], rv["volume_effect"], rv["rate_effect"]
    check = "OK" if rv["reconciled"] else "MISMATCH"
    vshare = f"{100*vol/dR:5.0f}%" if dR else "   -"
    rshare = f"{100*rate/dR:5.0f}%" if dR else "   -"
    print(f"  {label:<30} dR={dR:>13,.0f}  volume={vol:>13,.0f} ({vshare})  "
          f"rate={rate:>13,.0f} ({rshare})  [{check}] driver={rv['driver']}")


def show_price_volume(candidates: dict) -> None:
    print("\n=== price/volume decomposition (recomputed with new detector) ===")
    for rv in candidates.get("overall_price_volume", []):
        _pv_row(rv["segment"], rv)
    n = 0
    for c in candidates.get("business_candidates", []):
        for rv in c.get("rate_volume", []):
            n += 1
            _pv_row(c["segment"], rv)
    if not candidates.get("overall_price_volume") and not n:
        print("  (no table carried a revenue triple + volume triple together)")


def show_contracts(state: dict) -> dict:
    contracts = evidence_contract.build_contracts(state)
    print("\n=== evidence contracts (scope classification on real DAX) ===")
    print(f"  {'query':<42} {'population':<20} {'complete':<9} topn rows")
    for name, c in contracts.items():
        print(f"  {name[:41]:<42} {c['population_status']:<20} "
              f"{c['completeness']:<9} {str(c['topn'] or '-'):>4} {c['row_count']:>4}")
    # highlight anything a reuse path must never trust silently
    risky = [n for n, c in contracts.items()
             if c["population_status"] in ("unfiltered", "includes_excluded", "scope_ambiguous", "unknown")
             or c["completeness"] != "complete"]
    print(f"\n  verification-required tables ({len(risky)}): {risky}")
    return contracts


def show_briefs_and_reuse(state: dict) -> None:
    updates = evidence_assembler.run(state)
    briefs = updates["insight_evidence_briefs"]
    investigations = _load(Path(state["_outdir"]), "insight_investigations.json", [])
    inv_by_id = {i.get("signal", {}).get("id"): i for i in investigations}

    print("\n=== per-signal reuse vs actual probes ===")
    print(f"  {'signal':<44} dims reuse gaps | actual_probes")
    tot_reuse = tot_gap = tot_actual = 0
    for sid, b in briefs.items():
        rs = b.get("reuse_summary", {})
        actual = inv_by_id.get(sid, {}).get("probe_executions", "-")
        if isinstance(actual, int):
            tot_actual += actual
        tot_reuse += rs.get("answered_by_reuse", 0)
        tot_gap += rs.get("gaps_needing_probe", 0)
        print(f"  {sid[:43]:<44} {rs.get('drill_dimensions','-'):>4} "
              f"{rs.get('answered_by_reuse','-'):>5} {rs.get('gaps_needing_probe','-'):>4} | {actual}")
    print(f"\n  TOTALS: drill-dims answered by reuse={tot_reuse}, "
          f"gaps needing a probe={tot_gap}, actual probes executed in the run={tot_actual}")
    print(f"  -> the reuse path targets {tot_gap} probes vs {tot_actual} the free-form "
          f"investigator actually ran.")


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT_ROOT / "outputs"
    if not (out / "insight_clean_data.json").exists():
        print(f"No insight_clean_data.json in {out} - run the pipeline first.")
        return 1
    state = _state(out)
    state["_outdir"] = str(out)

    state["insight_evidence_contracts"] = evidence_contract.build_contracts(state)
    candidates = insight_stat_detector.run(state)["insight_stat_candidates"]
    state["insight_stat_candidates"] = candidates
    show_price_volume(candidates)
    show_contracts(state)
    show_briefs_and_reuse(state)
    print("\nreplay complete (artifacts in outputs_replay/).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
