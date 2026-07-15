"""Execute only the metadata baseline/coverage DAX against the live model."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.baseline_scope import build_query  # noqa: E402
from src.agents.insight_scan_templates import build_metadata_scans  # noqa: E402
from src.agents.semantic_profiler import build_profile  # noqa: E402
from src.tools import powerbi_executor as pbi  # noqa: E402


def main() -> int:
    cfg = json.loads((ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    metadata = json.loads((ROOT / "outputs" / "model_metadata.json").read_text(encoding="utf-8"))
    profile = build_profile(metadata)
    state = {**cfg, "semantic_model_profile": profile}
    queries = [build_query(profile, cfg.get("metadata_scope_max_entities", 500))]
    queries += build_metadata_scans(profile, state)
    queries = [q for q in queries if q]
    token = pbi.get_powerbi_token(tenant_id=cfg["tenant_id"])
    results = pbi.execute_python(cfg["workspace_id"], cfg["dataset_id"], queries, token=token)
    failures = 0
    for name, item in results.items():
        status = item.get("status")
        print(f"{name}: {status}")
        if status != "success":
            failures += 1
            print("  " + str(item.get("error", "unknown error"))[:500])
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
