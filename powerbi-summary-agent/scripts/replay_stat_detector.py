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
    return 0


if __name__ == "__main__":
    sys.exit(main())
