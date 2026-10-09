"""Seed shadow runs with today's production memory, read-only.

    python scripts/seed_shadow_memory.py config/sbmart-yoy/config.json \
        config/sbmart-yoy-shadow-narrated/config.json \
        config/sbmart-yoy-shadow-investigated/config.json \
        config/sbmart-yoy-shadow-reasoned/config.json

    python scripts/seed_shadow_memory.py config/sbmart-yoy/config.json --check

Phase 5 of `docs/reasoned-tier-implementation-plan.md`. A shadow run keeps its
memory on this machine (`insight_memory_storage: local`), so it can never mark a
finding "already told" for the customer. Starting it from an empty memory would
make day 1 treat everything as new, which is not a fair comparison; this copies
production's insight and summary memory into each shadow's own runtime folder
first, so all three tiers start from the same "already told" set.

It only downloads, through the same ``hydrate_*`` functions the production job
uses. It also prints each production memory blob's ETag and last-modified time:
run it again with ``--check`` after the shadow runs and the two must match,
which is the proof that nothing wrote to production.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.main import build_initial_state, load_config  # noqa: E402 - also loads .env
from src.tools import azure_blob  # noqa: E402


def _blob_stamps(state: dict) -> dict[str, dict]:
    """ETag and last-modified of the production memory blobs (properties only)."""
    out = {}
    for label, locate in (("insight", azure_blob._memory_location),
                          ("summary", azure_blob._summary_memory_location)):
        account, container, name = locate(state)
        try:
            svc, _auth = azure_blob._service_client(account)
            props = svc.get_blob_client(container=container, blob=name).get_blob_properties()
            out[label] = {"blob": f"{container}/{name}", "etag": str(props.etag),
                          "last_modified": props.last_modified.isoformat()}
        except Exception as exc:  # noqa: BLE001 - reported, never raised
            out[label] = {"blob": f"{container}/{name}", "error": f"{type(exc).__name__}: {exc}"}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("production", help="the production config the memory belongs to")
    parser.add_argument("shadows", nargs="*", help="shadow configs to seed")
    parser.add_argument("--check", action="store_true",
                        help="only print the production memory blobs' ETags")
    args = parser.parse_args()

    prod_path = Path(args.production)
    prod_cfg = load_config(prod_path)
    if str(prod_cfg.get("insight_memory_storage")).lower() != "azure_blob":
        print("[FAIL] the production config does not keep its memory in Azure blob")
        return 1
    stamps = _blob_stamps(build_initial_state(dict(prod_cfg), str(prod_path)))
    print(json.dumps({"production_memory": stamps}, indent=2))
    if args.check:
        return 0

    failed = 0
    for shadow_path in map(Path, args.shadows):
        shadow = load_config(shadow_path)
        if str(shadow.get("insight_memory_storage")).lower() != "local":
            print(f"[FAIL] {shadow_path}: a shadow must keep its memory locally; not seeded")
            failed += 1
            continue
        # Production's storage settings, so hydration reads production's blobs;
        # the shadow's runtime folders, so the copy lands where the shadow reads.
        seeding = {**prod_cfg,
                   "insight_memory_runtime_folder": shadow["insight_memory_runtime_folder"],
                   "summary_memory_runtime_folder": shadow["summary_memory_runtime_folder"]}
        state = build_initial_state(seeding, str(prod_path))
        insight = azure_blob.hydrate_insight_memory(state)
        summary = azure_blob.hydrate_summary_memory(state)
        ok = insight.get("status") in ("ok", "missing") and summary.get("status") in ("ok", "missing")
        failed += 0 if ok else 1
        print(f"[{'OK' if ok else 'FAIL'}] {shadow_path}: insight={insight.get('status')}, "
              f"summary={summary.get('status')} -> {shadow['insight_memory_runtime_folder']}, "
              f"{shadow['summary_memory_runtime_folder']}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
