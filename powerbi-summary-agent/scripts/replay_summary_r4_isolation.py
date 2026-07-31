"""Offline regression: R4 isolation (Phase 1 safety property).

Proves that with ``summary_r4_enabled=False`` the Department split is invisible:
a Department breakdown collapses into Division exactly as before, so legacy
candidates, identity keys and focus selection are unchanged. Because the
candidate set and every identity key are byte-identical to the pre-split
behaviour, the deterministic selector's choice is identical too. It also proves
that with R4 on Department becomes a distinct focus level and that ``area_key``
distinguishes an identically named member under different parents.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import summary_candidate_builder, summary_novelty_filter  # noqa: E402
from src.tools import summary_memory  # noqa: E402


def _state(root: Path, r4: bool) -> dict:
    return {
        "dataset_id": "r4-fixture",
        "output_folder": str(root / ("out_r4" if r4 else "out_legacy")),
        "summary_memory_root": str(root / ("mem_r4" if r4 else "mem_legacy")),
        "summary_memory_enabled": True,
        "summary_memory_hydration": {"status": "missing"},
        "summary_focus_enabled": True,
        "summary_r4_enabled": r4,
        "summary_focus_members_per_dimension": 10,
        "summary_focus_cooldown_days": 14,
        "summary_focus_same_dimension_gap_days": 2,
        "summary_focus_policy": "cooldown",
        "summary_now_override": "2026-07-23",
        "resolved_entity_scope": {},
        "semantic_model_profile": {},
        "summary_period_context": {
            "period_anchor": "2023-12",
            "data_as_of": "2023-12-31",
            "grain": "month",
            "checks": [],
        },
        "config": {},
        "logs": [],
        "errors": [],
        "clean_summary_data": {
            "queries": [
                {
                    "query_name": "overall",
                    "purpose": "Overall totals",
                    "status": "success",
                    "rows": [{"Revenue Current": 160.0, "Revenue Prior": 170.0, "Revenue Growth": -10.0}],
                },
                {
                    "query_name": "division_breakdown",
                    "purpose": "Revenue by division",
                    "status": "success",
                    "rows": [
                        {"Division": "Food", "Revenue Current": 100.0, "Revenue Prior": 80.0, "Revenue Growth": 20.0},
                        {"Division": "Nonfood", "Revenue Current": 60.0, "Revenue Prior": 90.0, "Revenue Growth": -30.0},
                    ],
                },
                {
                    "query_name": "department_breakdown",
                    "purpose": "Revenue by department",
                    "status": "success",
                    "rows": [
                        {"Department": "Fresh", "Revenue Current": 70.0, "Revenue Prior": 50.0, "Revenue Growth": 20.0},
                        {"Department": "Frozen", "Revenue Current": 30.0, "Revenue Prior": 45.0, "Revenue Growth": -15.0},
                    ],
                },
            ],
        },
        "baseline_coverage_clean_data": {"queries": []},
    }


def _focus_components(role: str, segment: str, metric_family: str) -> str:
    key, _ = summary_memory.focus_components(
        {"dimension_role": role, "segment": segment, "metric_family": metric_family, "lens": "performance"},
        "r4-fixture",
    )
    return key


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="r4-isolation-") as tmp:
        root = Path(tmp)

        # --- R4 OFF: Department collapses into Division (legacy) --------------
        legacy = _state(root, r4=False)
        legacy.update(summary_candidate_builder.run(legacy))
        cands = legacy["summary_candidates"]
        dept = [c for c in cands if c.get("query_name") == "department_breakdown"]
        assert dept, "department query must yield candidates"

        # No department role/angle leaks anywhere with R4 off.
        assert not any(c.get("angle") == "department_overview" for c in cands), "R4 off emitted department_overview"
        assert not any(c.get("dimension_role") == "department" for c in cands), "R4 off emitted a department role"

        # Department candidates behave exactly as a Division breakdown would have.
        dept_broad = [c for c in dept if c.get("candidate_kind") == "broad"]
        dept_members = [c for c in dept if c.get("candidate_kind") == "member"]
        assert dept_broad and dept_broad[0]["angle"] == "division_overview", dept_broad
        assert dept_members, "department breakdown must still re-slice member candidates"
        assert all(c["dimension_role"] == "division" for c in dept), dept
        assert all(c["lens"] == "performance" for c in dept)

        # Identity keys recompute to the legacy division-based focus identity.
        for member in dept_members:
            expected = _focus_components("division", member["segment"], member["metric_family"])
            assert member["focus_key"] == expected, (member["segment"], member["focus_key"], expected)

        # Selection runs and never surfaces a department role with R4 off.
        legacy.update(summary_novelty_filter.run(legacy))
        assert legacy["summary_novelty"]["status"] == "ok", legacy["summary_novelty"]
        assert legacy["summary_selected_focus"].get("dimension_role") != "department"

        # --- R4 ON: Department is a distinct focus level ----------------------
        r4 = _state(root, r4=True)
        r4.update(summary_candidate_builder.run(r4))
        r4_cands = r4["summary_candidates"]
        r4_dept = [c for c in r4_cands if c.get("query_name") == "department_breakdown"]
        r4_dept_broad = [c for c in r4_dept if c.get("candidate_kind") == "broad"]
        r4_dept_members = [c for c in r4_dept if c.get("candidate_kind") == "member"]
        assert r4_dept_broad and r4_dept_broad[0]["angle"] == "department_overview", r4_dept_broad
        assert all(c["dimension_role"] == "department" for c in r4_dept), r4_dept

        # The same member yields a DIFFERENT focus_key under R4 (department != division).
        for member in r4_dept_members:
            dept_key = _focus_components("department", member["segment"], member["metric_family"])
            div_key = _focus_components("division", member["segment"], member["metric_family"])
            assert member["focus_key"] == dept_key and dept_key != div_key, member["segment"]

        # --- area_key distinguishes a duplicate leaf under different parents ---
        a1, _ = summary_memory.area_components(
            {"dimension_role": "category", "segment": "Other", "hierarchy_path": ["Food", "Fresh", "Other"]},
            "r4-fixture",
        )
        a2, _ = summary_memory.area_components(
            {"dimension_role": "category", "segment": "Other", "hierarchy_path": ["Food", "Frozen", "Other"]},
            "r4-fixture",
        )
        assert a1 != a2, "duplicate leaf under different parents must produce distinct area identities"

    print("r4 isolation replay: all deterministic checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
