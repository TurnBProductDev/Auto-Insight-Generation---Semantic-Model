"""Isolated LIVE probe: what does this semantic model actually expose?

A thin CLI over ``src.services.probe.run_probe`` - the same call the config UI
makes, so the two can never disagree about what a model supports. It runs only
the pre-fork metadata/profile/scope nodes plus ``summary_focus_universe``, into
a temporary output + memory location, with no LLM call and no production
memory/history/published-output write.

Requires live Power BI auth: the cached MSAL refresh token at repo-root
``.pbi_token_cache.json`` (or a one-time browser login on first ever run).

Usage:
    python scripts/probe_summary_universe.py [--config config/config.json] [--pool 30]
    python scripts/probe_summary_universe.py --config config/scanb/config.json --json probe.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.main import load_config  # noqa: E402
from src.services.probe import run_probe  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/config.json")
    parser.add_argument("--pool", type=int, default=None, help="override candidate_pool_per_role")
    parser.add_argument("--json", default=None, help="write the full ProbeResult here")
    parser.add_argument("--artifacts", default=None, help="keep the probe's JSON artifacts in this directory")
    parser.add_argument("--deep", action="store_true",
                        help="also run the shared diagnostic portfolio so freshness and the "
                             "per-axis verdicts are measured rather than unknown")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except Exception:  # noqa: BLE001 - .env is optional
        pass

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path

    result = run_probe(
        load_config(config_path),
        config_path=str(config_path),
        on_log=lambda line: print(f"  {line}"),
        candidate_pool=args.pool,
        keep_artifacts=args.artifacts,
        deep=args.deep,
    )

    print("\n" + "=" * 72)
    print(f"PROBE {result.status.upper()} in {result.duration_seconds}s")
    print("=" * 72)

    model = result.model
    print(f"\nfact table       : {model.get('factTable')}")
    print(f"primary metric   : {(model.get('primaryMetric') or {}).get('family')} "
          f"{(model.get('primaryMetric') or {}).get('measures')}")
    print(f"entity dimension : "
          f"{(model.get('entityDimension') or {}).get('reference') if model.get('entityResolved') else 'UNRESOLVED'}")
    families = model.get("measureFamilies") or []
    print(f"measure families : {len(families)}")
    for family in families[:8]:
        note = " (prior reconstructed from change)" if family.get("priorReconstructed") else ""
        print(f"   {family.get('family')}: {family.get('current')} / {family.get('prior')} / "
              f"{family.get('change')}{note}")

    print("\nresolved roles:")
    for role in result.roles.get("resolved", []):
        print(f"   {role['role']:<16} depth={role['depth']} column={role['column']} "
              f"members={role['memberCount']} reconciled={role['reconciled']} "
              f"pool_capped={role['poolCapped']}"
              + (" [coverage only]" if role["coverageOnly"] else ""))

    entities = result.entities
    print(f"\nentity scope     : source={entities.get('source')} "
          f"comparable={len(entities.get('comparable') or [])} "
          f"excluded={len(entities.get('excluded') or [])} "
          f"current_only={len(entities.get('currentOnly') or [])} "
          f"prior_only={len(entities.get('priorOnly') or [])}")

    freshness = result.freshness
    print(f"freshness        : data_as_of={freshness.get('data_as_of')} "
          f"status={freshness.get('freshness_status')} grain={freshness.get('grain')} "
          f"axis={freshness.get('axis')}")
    for axis in result.time_axes[:8]:
        label = f"{axis.get('table')}[{axis['column']}]"
        print(f"   {label:<44} type={axis['dataType']} "
              f"verdict={axis.get('verdict') or ('not evaluated' if result.deep else 'not probed (use --deep)')}")

    if result.recommendations:
        print("\nrecommended config:")
        for item in result.recommendations:
            print(f"   {item['key']} = {json.dumps(item['value'])}")
            print(f"      {item['reason']}")

    for warning in result.warnings:
        print(f"\nWARNING: {warning}")
    for blocker in result.blocking:
        print(f"\nBLOCKING: {blocker}")

    if args.json:
        destination = Path(args.json)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result.json(), indent=2, default=str), encoding="utf-8")
        print(f"\nfull result written to: {destination}")

    return 0 if result.status != "failed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
