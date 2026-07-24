"""Generate an isolated fresh-summary preview from an existing output bundle.

This makes one summary LLM call, but performs no Power BI query, Blob upload,
history write, or memory commit. It is useful for prompt/style acceptance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from src.agents import (  # noqa: E402
    fresh_summary_generator,
    fresh_summary_validator,
    summary_candidate_builder,
    summary_novelty_filter,
    summary_period_resolver,
)
from src.main import build_initial_state  # noqa: E402


def _read(path: Path, required: bool = True):
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="outputs")
    parser.add_argument("--output", default="outputs_replay/fresh_summary_preview")
    args = parser.parse_args(argv)

    cfg = _read(PROJECT_ROOT / "config" / "config.json")
    cfg.update({
        "output_folder": args.output,
        "summary_memory_enabled": False,
        "summary_memory_storage": "local",
        "azure_blob_upload": False,
    })
    state = build_initial_state(cfg, str(PROJECT_ROOT / "config" / "config.json"))
    state["summary_memory_enabled"] = False
    source = PROJECT_ROOT / args.source
    state.update({
        "clean_summary_data": _read(source / "clean_summary_data.json"),
        "baseline_coverage_clean_data": _read(source / "baseline_coverage_clean_data.json", required=False),
        "baseline_scope_evidence": _read(source / "baseline_scope_evidence.json", required=False),
        "resolved_entity_scope": _read(source / "resolved_entity_scope.json", required=False),
        "semantic_model_profile": _read(source / "semantic_model_profile.json"),
        "report_understanding": _read(source / "report_understanding.json", required=False),
        "business_rules": "",
        "summary_memory_hydration": {"status": "skipped"},
    })

    for node in (
        summary_period_resolver.run,
        summary_candidate_builder.run,
        summary_novelty_filter.run,
        fresh_summary_generator.run,
        fresh_summary_validator.run,
    ):
        state.update(node(state))

    out = PROJECT_ROOT / args.output
    print(f"Fresh summary preview: {out / 'report_summary.html'}")
    print((out / "report_summary.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
