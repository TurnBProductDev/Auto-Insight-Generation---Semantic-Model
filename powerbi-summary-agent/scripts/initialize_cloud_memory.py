"""Provision a brand-new Azure Blob insight-memory store without overwriting.

Run from the powerbi-summary-agent directory:

    python scripts/initialize_cloud_memory.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main import build_initial_state, load_config  # noqa: E402
from src.tools.azure_blob import initialize_insight_memory  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create an empty cloud insight-memory blob exactly once"
    )
    parser.add_argument(
        "--config", default=str(PROJECT_ROOT / "config" / "config.json")
    )
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    cfg = load_config(config_path)
    state = build_initial_state(cfg, str(config_path))
    result = initialize_insight_memory(state)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("status") == "created":
        print("Cloud insight memory initialized empty. Local memory was not migrated.")
        return 0
    if result.get("status") == "exists" and result.get("empty"):
        print("Cloud insight memory already exists and is still empty; left unchanged.")
        return 0
    if result.get("status") == "exists":
        print("Cloud insight memory already contains state; refusing to reset or overwrite it.")
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
