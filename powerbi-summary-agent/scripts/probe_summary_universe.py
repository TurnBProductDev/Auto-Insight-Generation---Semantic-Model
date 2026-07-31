"""Isolated LIVE probe for the R4 focus universe scan.

Runs ONLY the pre-fork metadata/profile/scope nodes plus ``summary_focus_universe``
against the configured Power BI model, into a TEMPORARY output + memory location,
so the per-parent broadcast-diagnostic DAX can be validated on the real model
before Memory v3 is built. Nothing else in the pipeline runs and no production
memory/history is touched.

Requires live Power BI auth: the cached MSAL refresh token at repo-root
``.pbi_token_cache.json`` (or a one-time browser login on first ever run).

Usage:
    python scripts/probe_summary_universe.py [--config config/config.json] [--pool 30]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import baseline_scope, metadata_reader, semantic_profiler, summary_focus_universe  # noqa: E402
from src.main import build_initial_state, load_config  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.json")
    parser.add_argument("--pool", type=int, default=None, help="override candidate_pool_per_role")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:  # noqa: BLE001 - .env is optional
        pass

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    cfg = load_config(config_path)
    state = build_initial_state(cfg, str(config_path))

    probe_out = PROJECT_ROOT / "outputs_probe"
    probe_out.mkdir(parents=True, exist_ok=True)
    state["output_folder"] = str(probe_out)
    state["summary_memory_root"] = str(probe_out / "memory")
    state["summary_r4_enabled"] = True
    if args.pool:
        state["summary_focus_candidate_pool_per_role"] = args.pool
    state.setdefault("logs", [])
    state.setdefault("errors", [])

    print("== resolving metadata / profile / scope (pre-fork) ==")
    state.update(metadata_reader.run(state))
    if not state.get("pbi_token"):
        print("ERROR: no Power BI token acquired; check auth / .pbi_token_cache.json")
        return 2
    state.update(semantic_profiler.run(state))
    state.update(baseline_scope.run(state))

    roles = summary_focus_universe._resolve_role_columns(state.get("semantic_model_profile") or {}, state)
    print("resolved roles:")
    print(json.dumps({r: {"group": i["group_ref"], "parents": i["parent_refs"]} for r, i in roles.items()}, indent=2))

    print("\n== running summary_focus_universe (LIVE DAX) ==")
    state.update(summary_focus_universe.run(state))
    universe = state.get("summary_focus_universe", {})
    print("status:", universe.get("status"), universe.get("reason", ""))
    for role, info in (universe.get("roles") or {}).items():
        members = info.get("members") or []
        print(
            f"\n[{role}] status={info.get('status')} returned={info.get('returned_member_count')} "
            f"max_siblings={info.get('max_siblings_per_parent')} "
            f"reconciled={info.get('diagnostics_reconciled')} "
            f"pool_capped={info.get('pool_capped')}"
        )
        for member in members[:8]:
            print(
                f"   {member.get('hierarchy_path')}: chg={member.get('change')} "
                f"global%={member.get('global_impact_pct')} share%={member.get('business_share_pct')} "
                f"sibling%={member.get('sibling_movement_impact_pct')}"
            )

    dest = probe_out / "summary_focus_universe_probe.json"
    dest.write_text(json.dumps(universe, indent=2, default=str), encoding="utf-8")
    print(f"\nfull contract written to: {dest}")
    print("\nValidate: (1) reconciled=True where expected, (2) sibling%% is per-parent "
          "(siblings under the same department, not global), (3) global%% uses the overall "
          "denominator, (4) member counts look right, (5) DAX did not error.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
