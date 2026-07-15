"""Entry point for the Power BI Report Summary Agent.

Run from the project root:

    python -m src.main
    python -m src.main --config config/config.json
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .graph import build_graph

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Load environment variables from powerbi-summary-agent/.env (Azure OpenAI creds,
# LLM_PROVIDER override, etc.) before any node reads os.environ.
try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def load_config(config_path: Path) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    # Environment override supports deployments that keep tenant selection out
    # of the JSON file; normalize it into cfg for the rest of the pipeline.
    cfg["tenant_id"] = os.environ.get("POWERBI_TENANT_ID") or cfg.get("tenant_id")
    required = ["tenant_id", "workspace_id", "dataset_id"]
    missing = [k for k in required if not cfg.get(k) or str(cfg[k]).startswith("PASTE_")]
    if missing:
        raise SystemExit(f"config.json is missing required values: {missing}")
    return cfg


def build_initial_state(cfg: dict, config_path: str = "") -> dict:
    return {
        # Node 1 (load_config) reads business_rules.md from beside this path.
        "config_path": config_path,
        "tenant_id": cfg["tenant_id"],
        "workspace_id": cfg["workspace_id"],
        "dataset_id": cfg["dataset_id"],
        "output_folder": cfg.get("output_folder", "outputs"),
        "summary_word_limit": cfg.get("summary_word_limit", 300),
        "max_rows_per_query": cfg.get("max_rows_per_query", 15),
        "ai_provider": os.environ.get("LLM_PROVIDER") or cfg.get("ai_provider", "azure_openai"),
        "model": cfg.get("model", "claude-sonnet-5"),
        "max_tokens": cfg.get("max_tokens", 4096),
        "execution_mode": cfg.get("execution_mode", "python"),
        "fabric_definitions": cfg.get("fabric_definitions", True),
        "insight_max_signals": cfg.get("insight_max_signals", 5),
        "insight_max_investigation_rounds": cfg.get("insight_max_investigation_rounds", 3),
        "insight_max_scan_queries": cfg.get("insight_max_scan_queries", 10),
        "insight_probe_max_rows": cfg.get("insight_probe_max_rows", 20),
        "insight_materiality_pct": cfg.get("insight_materiality_pct", 1.0),
        "insight_max_dq_signals": cfg.get("insight_max_dq_signals", 2),
        # Business-rule scope (mirrors config/business_rules.md - keep in sync).
        # Drives evidence_contract population classification and the reuse gate.
        "insight_comparable_population": cfg.get("insight_comparable_population", []),
        "insight_excluded_entities": cfg.get("insight_excluded_entities", []),
        "insight_stat_z_cutoff": cfg.get("insight_stat_z_cutoff", 3.0),
        "insight_stat_concentration_pct": cfg.get("insight_stat_concentration_pct", 50.0),
        "insight_stat_recon_tolerance_pct": cfg.get("insight_stat_recon_tolerance_pct", 2.0),
        "insight_stat_trend_window": cfg.get("insight_stat_trend_window", 3),
        "insight_stat_max_candidates": cfg.get("insight_stat_max_candidates", 20),
        "metadata_scope_max_entities": cfg.get("metadata_scope_max_entities", 500),
        "insight_metadata_max_dimensions": cfg.get("insight_metadata_max_dimensions", 5),
        "insight_total_gap_scan_budget": cfg.get("insight_total_gap_scan_budget", 20),
        "insight_max_gap_dimensions_per_signal": cfg.get("insight_max_gap_dimensions_per_signal", 3),
        "config": cfg,
        "logs": [],
        "errors": [],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Power BI Report Summary Agent")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.json"))
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    state = build_initial_state(cfg, str(Path(args.config)))

    app = build_graph()
    final = app.invoke(state)

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    out = PROJECT_ROOT / state["output_folder"]
    print(f"Outputs: {out}")
    if final.get("errors"):
        print(f"Errors ({len(final['errors'])}): see run_log.txt")

    summary_path = out / "report_summary.md"
    if summary_path.exists():
        print("\n----- report_summary.md -----\n")
        print(summary_path.read_text(encoding="utf-8"))

    insight_path = out / "insight_report.md"
    if insight_path.exists():
        print("\n----- insight_report.md -----\n")
        print(insight_path.read_text(encoding="utf-8"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
