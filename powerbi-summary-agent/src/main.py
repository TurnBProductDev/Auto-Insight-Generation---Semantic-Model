"""Entry point for the Power BI Report Summary Agent.

Run from the project root:

    python -m src.main
    python -m src.main --config config/config.json
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
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
    # Environment overrides let one container image target a model without
    # baking deployment-specific IDs into the image.
    overrides = {
        "tenant_id": "POWERBI_TENANT_ID",
        "workspace_id": "POWERBI_WORKSPACE_ID",
        "dataset_id": "POWERBI_DATASET_ID",
        "output_folder": "AGENT_OUTPUT_FOLDER",
    }
    for key, env_name in overrides.items():
        if os.environ.get(env_name):
            cfg[key] = os.environ[env_name]
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
        # Cross-run insight memory (Phase 1): remember reported findings and only
        # surface unseen ones on later runs.
        "insight_memory_enabled": cfg.get("insight_memory_enabled", True),
        "insight_memory_policy": cfg.get("insight_memory_policy", "never_repeat"),
        "insight_memory_cooldown_days": cfg.get("insight_memory_cooldown_days", 14),
        "insight_max_new_per_run": cfg.get("insight_max_new_per_run", 3),
        "insight_reporting_grain": cfg.get("insight_reporting_grain", "month"),
        "insight_candidates_high": cfg.get("insight_candidates_high", 20),
        "insight_candidates_weekly": cfg.get("insight_candidates_weekly", 10),
        "insight_candidates_daily": cfg.get("insight_candidates_daily", 10),
        # Phase 2: validated sub-annual temporal level (weekly if a clean business-day
        # column exists, else monthly). Grain gate rejects load/posting-date axes.
        "insight_temporal_enabled": cfg.get("insight_temporal_enabled", True),
        "insight_temporal_batch_share": cfg.get("insight_temporal_batch_share", 0.5),
        "insight_temporal_min_periods": cfg.get("insight_temporal_min_periods", 6),
        "insight_temporal_recon_tolerance_pct": cfg.get("insight_temporal_recon_tolerance_pct", 2.0),
        "insight_temporal_max_probes": cfg.get("insight_temporal_max_probes", 3),
        "insight_temporal_grain_column": cfg.get("insight_temporal_grain_column", ""),
        "insight_candidates_period": cfg.get("insight_candidates_period", 10),
        "insight_period_top_movers": cfg.get("insight_period_top_movers", 4),
        "insight_period_recent_window": cfg.get("insight_period_recent_window", 12),
        "insight_period_drill": cfg.get("insight_period_drill", True),
        "insight_period_drill_top": cfg.get("insight_period_drill_top", 3),
        # Phase 3: previous-complete-week monitoring. Capability + freshness gate
        # disables the level on a load/posting-date axis or stale data.
        "insight_recent_week_enabled": cfg.get("insight_recent_week_enabled", True),
        "insight_business_date_override": cfg.get("insight_business_date_override", None),
        "insight_week_max_date_probes": cfg.get("insight_week_max_date_probes", 3),
        "insight_week_start": cfg.get("insight_week_start", "monday"),
        "insight_business_timezone": cfg.get("insight_business_timezone", "naive"),
        "insight_week_max_data_lag_days": cfg.get("insight_week_max_data_lag_days", 7),
        "insight_week_history_weeks": cfg.get("insight_week_history_weeks", 13),
        "insight_week_materiality_pct": cfg.get("insight_week_materiality_pct", 3.0),
        "insight_week_z_cutoff": cfg.get("insight_week_z_cutoff", 2.5),
        "insight_week_driver_rows": cfg.get("insight_week_driver_rows", 30),
        "insight_week_mode": cfg.get("insight_week_mode", "calendar"),
        # Phase 3b: daily anomaly incidents. Independent of insight_recent_week_enabled -
        # both consume the same shared insight_business_day_source, so disabling one
        # never disables the other. Gated the same way (self-disables safely on any
        # model lacking a clean business-day axis).
        "insight_daily_enabled": cfg.get("insight_daily_enabled", True),
        "insight_daily_rolling_window": cfg.get("insight_daily_rolling_window", 28),
        "insight_daily_recent_days": cfg.get("insight_daily_recent_days", 3),
        "insight_daily_exclude_today": cfg.get("insight_daily_exclude_today", True),
        "insight_daily_z_cutoff": cfg.get("insight_daily_z_cutoff", 3.0),
        "insight_daily_materiality_pct": cfg.get("insight_daily_materiality_pct", 3.0),
        "insight_daily_min_weekday_occurrences": cfg.get("insight_daily_min_weekday_occurrences", 3),
        # Phase 3b: rolling-week's structural resurface logic (not a general
        # Phase-4 switch - that remains future work). growth_pct is named so a
        # future general re-alert change can reuse it unchanged.
        "insight_re_alert_growth_pct": cfg.get("insight_re_alert_growth_pct", 50),
        "insight_rolling_report_delta_pct": cfg.get("insight_rolling_report_delta_pct", 5.0),
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


def write_api_payloads(final: dict) -> dict:
    """Post-run: build the MVC/FastAPI content payloads (LLM-authored) from the
    finished run so a single `python -m src.main` produces everything.

    Reads the two outputs a completed run leaves on disk and writes
    outputs/api/{report_summary,kpi_insights}.json in the exact shapes the ASP.NET
    controllers deserialize. Numbers/enums are code-owned and the payloads are
    strictly validated inside the generators. Best-effort: any failure here (LLM
    error, missing outputs, validation) is reported but never fails the main run.
    Disable with `"api_payloads": false` in config.json.
    """
    cfg = final.get("config", {})
    if not cfg.get("api_payloads", True):
        return {"status": "skipped", "reason": "api_payloads_disabled"}
    out = PROJECT_ROOT / final.get("output_folder", "outputs")
    summary_md = out / "report_summary.md"
    signals_json = out / "insight_signals.json"
    if not summary_md.exists() or not signals_json.exists():
        print("API payloads skipped: report_summary.md / insight_signals.json not present.")
        return {"status": "failed", "reason": "source_artifacts_missing"}
    try:
        from .tools.api_payloads import (
            generate_kpi_insights_payload,
            generate_report_summary_payload,
        )

        title = cfg.get("api_summary_title", "AI Summary")
        report_payload, dropped = generate_report_summary_payload(
            summary_md.read_text(encoding="utf-8"), final, title=title
        )
        kpi_payload = generate_kpi_insights_payload(
            json.loads(signals_json.read_text(encoding="utf-8")), final
        )
        api_dir = out / "api"
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / "report_summary.json").write_text(
            json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (api_dir / "kpi_insights.json").write_text(
            json.dumps(kpi_payload, indent=2, ensure_ascii=False), encoding="utf-8")
        note = f", {dropped} bullet(s) dropped by fidelity guard" if dropped else ""
        print(f"API payloads: {api_dir} "
              f"({len(kpi_payload)} KPI cards, {len(report_payload['sections'])} summary sections{note})")
        return {
            "status": "ok",
            "kpiCards": len(kpi_payload),
            "summarySections": len(report_payload["sections"]),
            "droppedBullets": dropped,
        }
    except Exception as e:  # noqa: BLE001 - best-effort, must never fail the main run
        print(f"API payloads skipped ({type(e).__name__}: {e})")
        return {"status": "failed", "error": str(e)}


def _azure_job_strict(cfg: dict) -> bool:
    value = os.environ.get("AZURE_JOB_STRICT")
    if value is not None:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(os.environ.get("CONTAINER_APP_JOB_NAME")) or bool(
        cfg.get("azure_job_strict", False)
    )


def main(argv=None) -> int:
    started = datetime.now(timezone.utc)
    parser = argparse.ArgumentParser(description="Power BI Report Summary Agent")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.json"))
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    state = build_initial_state(cfg, str(Path(args.config)))

    from .tools.azure_blob import (
        hydrate_insight_memory,
        publish_insight_memory,
        upload_api_payloads,
        upload_insight_history,
    )

    memory_hydration = hydrate_insight_memory(state)
    if _azure_job_strict(cfg) and memory_hydration.get("status") == "failed":
        print("Azure job stopped: persistent insight memory could not be hydrated.")
        return 1

    app = build_graph()
    final = app.invoke(state)
    memory_publish = publish_insight_memory(final, memory_hydration)

    print("\n" + "=" * 70)
    print("PIPELINE COMPLETE")
    print("=" * 70)
    out = PROJECT_ROOT / state["output_folder"]
    print(f"Outputs: {out}")
    if final.get("errors"):
        print(f"Errors ({len(final['errors'])}): see run_log.txt")

    api_payloads = write_api_payloads(final)

    # Build one immutable, presentation-ready insight-history entry.  A stub
    # report is never present in final['insight_report'], so failed synthesis
    # cannot accidentally enter customer-facing history.
    from .tools.insight_history import build_and_write
    history_error = None
    try:
        history_artifact = build_and_write(final)
    except Exception as e:  # noqa: BLE001 - visible but does not discard reports
        history_artifact = None
        history_error = e
        print(f"Insight history preparation failed ({type(e).__name__}: {e}).")
    history_entry = history_artifact[0] if history_artifact else None
    if history_artifact:
        entry, local_path = history_artifact
        print(f"Insight history: prepared {local_path} "
              f"({entry['insightCount']} insight(s), date={entry['date']['iso']}).")
    elif history_error is None:
        print("Insight history skipped: no completed insight report or feature disabled.")

    # Local runs remain best-effort. Azure jobs inspect these structured results
    # below and exit non-zero when a required publication did not complete.
    api_upload = upload_api_payloads(final)
    history_upload = upload_insight_history(final, history_entry)

    summary_path = out / "report_summary.md"
    if summary_path.exists():
        print("\n----- report_summary.md -----\n")
        print(summary_path.read_text(encoding="utf-8"))

    insight_path = out / "insight_report.md"
    if insight_path.exists():
        print("\n----- insight_report.md -----\n")
        print(insight_path.read_text(encoding="utf-8"))

    strict = _azure_job_strict(cfg)
    failures = []
    if not final.get("report_summary"):
        failures.append("report_summary_missing")
    if not final.get("insight_report"):
        failures.append("insight_report_missing")
    if cfg.get("api_payloads", True) and api_payloads.get("status") != "ok":
        failures.append("api_payload_generation_failed")
    if cfg.get("azure_blob_upload", False) and api_upload.get("status") != "ok":
        failures.append("api_payload_upload_failed")
    if cfg.get("insight_history_enabled", True) and cfg.get("azure_blob_upload", False):
        if history_upload.get("status") not in {"created", "exists"}:
            failures.append("insight_history_archive_failed")
        if history_upload.get("feedStatus") not in {"updated", "unchanged"}:
            failures.append("insight_history_feed_failed")
    if str(cfg.get("insight_memory_storage", "local")).lower() == "azure_blob":
        if memory_publish.get("status") != "ok":
            failures.append("insight_memory_publish_failed")

    finished = datetime.now(timezone.utc)
    manifest = {
        "runId": os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME"),
        "startedAt": started.isoformat(timespec="seconds"),
        "finishedAt": finished.isoformat(timespec="seconds"),
        "durationSeconds": round((finished - started).total_seconds(), 3),
        "status": "failed" if failures else "completed",
        "strict": strict,
        "failures": failures,
        "reports": {
            "summary": bool(final.get("report_summary")),
            "insights": bool(final.get("insight_report")),
        },
        "apiPayloads": api_payloads,
        "apiUpload": api_upload,
        "historyUpload": history_upload,
        "memoryHydration": memory_hydration,
        "memoryPublish": memory_publish,
    }
    (out / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    print(f"Run manifest: {out / 'run_manifest.json'} status={manifest['status']}")
    if failures:
        print("Run failures: " + ", ".join(failures))
    return 1 if strict and failures else 0


if __name__ == "__main__":
    sys.exit(main())
