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


def _env_bool(name: str, value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(
        f"{name} must be true/false, yes/no, on/off, or 1/0; got {value!r}."
    )


def _apply_environment_overrides(cfg: dict) -> dict:
    """Apply deployment settings without baking the real config into an image.

    The real config file remains the most convenient local-development path.
    Container Apps Jobs can use the committed config template and provide the
    target identifiers/storage settings as environment variables instead.
    """
    raw_overrides = os.environ.get("AGENT_CONFIG_OVERRIDES_JSON")
    if raw_overrides:
        try:
            overrides = json.loads(raw_overrides)
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"AGENT_CONFIG_OVERRIDES_JSON is not valid JSON: {exc}"
            ) from exc
        if not isinstance(overrides, dict):
            raise SystemExit("AGENT_CONFIG_OVERRIDES_JSON must be a JSON object.")
        cfg.update(overrides)

    string_overrides = {
        "POWERBI_TENANT_ID": "tenant_id",
        "POWERBI_WORKSPACE_ID": "workspace_id",
        "POWERBI_DATASET_ID": "dataset_id",
        "POWERBI_QUERY_API": "powerbi_query_api",
        "POWERBI_EFFECTIVE_USERNAME": "powerbi_effective_username",
        "AGENT_OUTPUT_FOLDER": "output_folder",
        "INSIGHT_HISTORY_TIMEZONE": "insight_history_timezone",
        "INSIGHT_MEMORY_STORAGE": "insight_memory_storage",
        "INSIGHT_MEMORY_RUNTIME_FOLDER": "insight_memory_runtime_folder",
        "SUMMARY_HISTORY_TIMEZONE": "summary_history_timezone",
        "SUMMARY_MEMORY_STORAGE": "summary_memory_storage",
        "SUMMARY_MEMORY_RUNTIME_FOLDER": "summary_memory_runtime_folder",
        "AZURE_BLOB_ACCOUNT": "azure_blob_account",
        "AZURE_BLOB_CONTAINER": "azure_blob_container",
        "AZURE_BLOB_PREFIX": "azure_blob_prefix",
        "AZURE_BLOB_HISTORY_PREFIX": "azure_blob_history_prefix",
        "AZURE_BLOB_HISTORY_FEED": "azure_blob_history_feed",
        "AZURE_BLOB_MEMORY_CONTAINER": "azure_blob_memory_container",
        "AZURE_BLOB_MEMORY_PREFIX": "azure_blob_memory_prefix",
        "AZURE_BLOB_SUMMARY_HISTORY_PREFIX": "azure_blob_summary_history_prefix",
        "AZURE_BLOB_SUMMARY_HISTORY_FEED": "azure_blob_summary_history_feed",
        "AZURE_BLOB_SUMMARY_MEMORY_PREFIX": "azure_blob_summary_memory_prefix",
        "AI_CONTENT_CLIENT": "ai_content_client",
        "POWERBI_REPORT_ID": "ai_content_report_id",
        "AI_CONTENT_REPORT_IDS": "ai_content_report_ids",
    }
    for env_name, config_name in string_overrides.items():
        if env_name in os.environ:
            cfg[config_name] = os.environ[env_name]
    if "AI_CONTENT_CLIENT" not in os.environ and "CLIENT" in os.environ:
        cfg["ai_content_client"] = os.environ["CLIENT"]

    boolean_overrides = {
        "AZURE_BLOB_UPLOAD": "azure_blob_upload",
        "INSIGHT_HISTORY_ENABLED": "insight_history_enabled",
        "FRESH_SUMMARY_ENABLED": "fresh_summary_enabled",
        "SUMMARY_HISTORY_ENABLED": "summary_history_enabled",
        "SUMMARY_MEMORY_ENABLED": "summary_memory_enabled",
        "SUMMARY_VISUAL_ENABLED": "summary_visual_enabled",
        "AI_CONTENT_PUBLISH_ENABLED": "ai_content_publish_enabled",
    }
    for env_name, config_name in boolean_overrides.items():
        if env_name in os.environ:
            cfg[config_name] = _env_bool(env_name, os.environ[env_name])

    return cfg


def load_config(config_path: Path) -> dict:
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    cfg = _apply_environment_overrides(cfg)
    # Surface the Power BI auth mode into the env so the REST executor (which has
    # no config handle) can resolve it. Env wins over config.json; "auto" ->
    # managed identity in Azure, interactive locally.
    auth_mode = os.environ.get("POWERBI_AUTH_MODE") or cfg.get("powerbi_auth_mode")
    if auth_mode:
        os.environ["POWERBI_AUTH_MODE"] = str(auth_mode)
        cfg["powerbi_auth_mode"] = str(auth_mode)

    # The executor intentionally has no state/config dependency. Surface its
    # wire-format and optional RLS impersonation settings once, before graph
    # construction. RLS stays disabled unless a username and/or roles are
    # explicitly configured.
    query_api = os.environ.get("POWERBI_QUERY_API") or cfg.get(
        "powerbi_query_api", "auto"
    )
    os.environ["POWERBI_QUERY_API"] = str(query_api)
    cfg["powerbi_query_api"] = str(query_api)

    effective_username = os.environ.get("POWERBI_EFFECTIVE_USERNAME") or cfg.get(
        "powerbi_effective_username"
    )
    if effective_username:
        os.environ["POWERBI_EFFECTIVE_USERNAME"] = str(effective_username)

    if "POWERBI_RLS_ROLES" not in os.environ:
        rls_roles = cfg.get("powerbi_rls_roles") or []
        if rls_roles:
            if not isinstance(rls_roles, list):
                raise SystemExit("powerbi_rls_roles in config.json must be a JSON array.")
            os.environ["POWERBI_RLS_ROLES"] = json.dumps(rls_roles)
    required = ["tenant_id", "workspace_id", "dataset_id"]
    missing = [k for k in required if not cfg.get(k) or str(cfg[k]).startswith("PASTE_")]
    if missing:
        raise SystemExit(f"config.json is missing required values: {missing}")
    return cfg


def build_initial_state(cfg: dict, config_path: str = "") -> dict:
    output_folder = cfg.get("output_folder", "outputs")
    memory_storage = str(cfg.get("insight_memory_storage", "local") or "local").lower()
    memory_root = cfg.get("insight_memory_runtime_folder")
    if memory_storage == "azure_blob" and not memory_root:
        # Never seed cloud memory from the existing local memory directory.
        memory_root = f"{output_folder}/.runtime/insight_memory"
    summary_memory_storage = str(
        cfg.get("summary_memory_storage") or memory_storage
    ).lower()
    summary_memory_root = cfg.get("summary_memory_runtime_folder")
    if summary_memory_storage == "azure_blob" and not summary_memory_root:
        summary_memory_root = f"{output_folder}/.runtime/summary_memory"
    if not summary_memory_root:
        summary_memory_root = f"{output_folder}/.runtime/summary_memory"
    return {
        # Node 1 (load_config) reads business_rules.md from beside this path.
        "config_path": config_path,
        "tenant_id": cfg["tenant_id"],
        "workspace_id": cfg["workspace_id"],
        "dataset_id": cfg["dataset_id"],
        "output_folder": output_folder,
        "summary_word_limit": cfg.get("summary_word_limit", 300),
        "fresh_summary_enabled": cfg.get("fresh_summary_enabled", True),
        "summary_visual_enabled": cfg.get("summary_visual_enabled", True),
        "summary_candidates_max": cfg.get("summary_candidates_max", 12),
        "summary_temporal_batch_share": cfg.get("summary_temporal_batch_share", 0.5),
        "summary_delayed_after_periods": cfg.get("summary_delayed_after_periods", 1),
        "summary_stale_after_periods": cfg.get("summary_stale_after_periods", 2),
        "summary_memory_enabled": bool(
            cfg.get("fresh_summary_enabled", True)
            and cfg.get("summary_memory_enabled", True)
        ),
        "summary_memory_root": summary_memory_root,
        "summary_memory_policy": cfg.get("summary_memory_policy", "never_repeat"),
        "summary_memory_cooldown_days": cfg.get("summary_memory_cooldown_days", 14),
        "summary_resurface_change_pct": cfg.get("summary_resurface_change_pct", 20),
        "summary_now_override": cfg.get("summary_now_override", None),
        # Daily focus + deep dive (summary R1). Focus rotation and the focused
        # deep dive default on; disabling summary_focus_enabled reproduces the
        # previous summary_key rotation exactly.
        "summary_focus_enabled": cfg.get("summary_focus_enabled", True),
        "summary_focus_timezone": cfg.get("summary_focus_timezone", "Asia/Kolkata"),
        "summary_focus_policy": cfg.get("summary_focus_policy", "cooldown"),
        "summary_focus_cooldown_days": cfg.get("summary_focus_cooldown_days", 14),
        "summary_focus_same_dimension_gap_days": cfg.get("summary_focus_same_dimension_gap_days", 2),
        "summary_focus_members_per_dimension": cfg.get("summary_focus_members_per_dimension", 10),
        "summary_focus_material_change_pct": cfg.get("summary_focus_material_change_pct", 20),
        "summary_focus_deep_dive_enabled": cfg.get("summary_focus_deep_dive_enabled", True),
        "summary_focus_max_queries": cfg.get("summary_focus_max_queries", 4),
        "summary_focus_max_child_dimensions": cfg.get("summary_focus_max_child_dimensions", 2),
        "summary_focus_max_rows_per_breakdown": cfg.get("summary_focus_max_rows_per_breakdown", 12),
        "summary_focus_reconciliation_tolerance_pct": cfg.get("summary_focus_reconciliation_tolerance_pct", 2),
        "summary_focus_include_driver_bridge": cfg.get("summary_focus_include_driver_bridge", True),
        "summary_focus_include_trend": cfg.get("summary_focus_include_trend", True),
        "summary_focus_daily_trend_enabled": cfg.get("summary_focus_daily_trend_enabled", False),
        "summary_focus_daily_trend_min_days": cfg.get("summary_focus_daily_trend_min_days", 14),
        "summary_focus_hierarchy_overrides": cfg.get("summary_focus_hierarchy_overrides", {}),
        # R2 editorial rhythm: weekday schedule soft prior + override lane.
        "summary_focus_schedule": cfg.get("summary_focus_schedule", {}),
        "summary_focus_schedule_weight": cfg.get("summary_focus_schedule_weight", 0.5),
        "summary_focus_override_change_pct": cfg.get("summary_focus_override_change_pct", 20),
        "summary_focus_override_min_impact_share_pct": cfg.get("summary_focus_override_min_impact_share_pct", 2),
        # R3 advanced novelty: overlap suppression + optional public focus metadata.
        "summary_focus_fact_overlap_threshold": cfg.get("summary_focus_fact_overlap_threshold", 0.6),
        "summary_focus_overlap_window_days": cfg.get("summary_focus_overlap_window_days", 7),
        "summary_focus_public_metadata": cfg.get("summary_focus_public_metadata", False),
        "summary_history_enabled": bool(
            cfg.get("fresh_summary_enabled", True)
            and cfg.get("summary_history_enabled", True)
        ),
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
        "insight_memory_root": memory_root,
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
        # Rate-outlier lens (peer growth-rate detection). Phase 1: honest peer
        # evidence. off | shadow | report; off plans no peer scans at all.
        "insight_rate_outlier_mode": cfg.get("insight_rate_outlier_mode", "off"),
        "insight_peer_max_dimensions": cfg.get("insight_peer_max_dimensions", 5),
        "insight_peer_max_rows": cfg.get("insight_peer_max_rows", 200),
        # Phase 2 detector thresholds (shadow-calibration hypotheses, not final).
        "insight_rate_z_cutoff": cfg.get("insight_rate_z_cutoff", 3.0),
        "insight_rate_min_peers": cfg.get("insight_rate_min_peers", 8),
        "insight_rate_prior_share_floor_pct": cfg.get("insight_rate_prior_share_floor_pct", 0.5),
        "insight_rate_exposure_floor_pct": cfg.get("insight_rate_exposure_floor_pct", 2.0),
        "insight_rate_min_abs_impact_pct": cfg.get("insight_rate_min_abs_impact_pct", 1.0),
        "insight_rate_flat_min_pct": cfg.get("insight_rate_flat_min_pct", 10.0),
        "insight_rate_min_ordinal_peers": cfg.get("insight_rate_min_ordinal_peers", 3),
        # Phase 9: optional cross-signal joint-interaction verification. It remains
        # off by default until the rate shadow evaluation earns promotion.
        "insight_thesis_linking_enabled": cfg.get("insight_thesis_linking_enabled", False),
        "insight_thesis_max_links": cfg.get("insight_thesis_max_links", 2),
        "insight_thesis_min_shared": cfg.get("insight_thesis_min_shared", 2),
        "insight_thesis_interaction_tol": cfg.get("insight_thesis_interaction_tol", 0.15),
        "insight_thesis_min_impact": cfg.get("insight_thesis_min_impact", 0.0),
        "metadata_scope_max_entities": cfg.get("metadata_scope_max_entities", 500),
        "insight_metadata_max_dimensions": cfg.get("insight_metadata_max_dimensions", 5),
        "insight_cross_dimensions": cfg.get("insight_cross_dimensions", 1),
        "insight_total_gap_scan_budget": cfg.get("insight_total_gap_scan_budget", 20),
        "insight_max_gap_dimensions_per_signal": cfg.get("insight_max_gap_dimensions_per_signal", 3),
        "config": cfg,
        "logs": [],
        "errors": [],
    }


def write_api_payloads(final: dict) -> dict:
    """Post-run: build the MVC/FastAPI content payloads from the finished run.

    Fresh summary JSON is projected deterministically from the already-validated
    draft; insight card wording keeps its existing LLM authoring path. Writes
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
    api_dir = out / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    from .tools.api_payloads import (
        generate_fresh_report_summary_payload,
        generate_kpi_insights_payload,
        generate_report_summary_payload,
    )

    summary_status = {"status": "failed", "reason": "real_summary_missing"}
    report_payload = None
    dropped = 0
    generated_files = []
    try:
        if final.get("fresh_summary_enabled", True) and final.get("fresh_summary"):
            report_payload = generate_fresh_report_summary_payload(
                final, title=cfg.get("api_summary_title", "AI Summary")
            )
        elif final.get("report_summary") and summary_md.exists():
            report_payload, dropped = generate_report_summary_payload(
                summary_md.read_text(encoding="utf-8"), final,
                title=cfg.get("api_summary_title", "AI Summary"),
            )
        if report_payload is not None:
            (api_dir / "report_summary.json").write_text(
                json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            summary_status = {"status": "ok", "dropped": dropped}
            generated_files.append("report_summary.json")
    except Exception as e:  # noqa: BLE001 - the insight payload remains independent
        summary_status = {"status": "failed", "error": str(e)}
        print(f"Summary API payload failed ({type(e).__name__}: {e}).")

    insight_status = {"status": "failed", "reason": "real_insight_missing"}
    kpi_payload = None
    try:
        if final.get("insight_report") and signals_json.exists():
            kpi_payload = generate_kpi_insights_payload(
                json.loads(signals_json.read_text(encoding="utf-8")), final
            )
        if kpi_payload is not None:
            (api_dir / "kpi_insights.json").write_text(
                json.dumps(kpi_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            insight_status = {"status": "ok", "cards": len(kpi_payload)}
            generated_files.append("kpi_insights.json")
    except Exception as e:  # noqa: BLE001 - the summary payload remains independent
        insight_status = {"status": "failed", "error": str(e)}
        print(f"Insight API payload failed ({type(e).__name__}: {e}).")

    overall = "ok" if summary_status.get("status") == "ok" and insight_status.get("status") == "ok" else "failed"
    note = f", {dropped} summary point(s) dropped by fidelity guard" if dropped else ""
    print(
        f"API payloads: {api_dir} (summary={summary_status.get('status')}, "
        f"insights={insight_status.get('status')}{note})"
    )
    return {
        "status": overall,
        "summaryStatus": summary_status,
        "insightStatus": insight_status,
        "files": generated_files,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Power BI Report Summary Agent")
    parser.add_argument(
        "--config",
        default=os.environ.get("AGENT_CONFIG_PATH")
        or str(PROJECT_ROOT / "config" / "config.json"),
    )
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    state = build_initial_state(cfg, str(Path(args.config)))

    from .tools.azure_blob import (
        cloud_memory_enabled,
        cloud_summary_memory_enabled,
        hydrate_insight_memory,
        hydrate_summary_memory,
        publish_insight_memory,
        publish_summary_memory,
        upload_api_payloads,
        upload_insight_history,
        upload_summary_history,
    )

    memory_hydration = hydrate_insight_memory(state)
    if cloud_memory_enabled(state) and memory_hydration.get("status") == "failed":
        print("Pipeline stopped: cloud insight memory could not be hydrated safely.")
        return 1

    summary_memory_hydration = hydrate_summary_memory(state)
    state["summary_memory_hydration"] = summary_memory_hydration

    app = build_graph()
    final = app.invoke(state)

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

    from .tools.summary_history import build_and_write as build_summary_history
    summary_history_error = None
    try:
        summary_history_artifact = build_summary_history(final)
    except Exception as e:  # noqa: BLE001 - visible; summary memory will not advance
        summary_history_artifact = None
        summary_history_error = e
        print(f"Summary history preparation failed ({type(e).__name__}: {e}).")
    summary_history_entry = summary_history_artifact[0] if summary_history_artifact else None
    if summary_history_artifact:
        entry, local_path, feed_path = summary_history_artifact
        final["fresh_summary"]["run_id"] = entry["runId"]
        print(
            f"Summary history: prepared {local_path} and {feed_path} "
            f"(type={entry['summaryType']}, dataAsOf={entry.get('dataAsOf')})."
        )
    elif summary_history_error is None:
        print("Summary history skipped: no completed fresh summary or feature disabled.")

    # Publish app-facing outputs first. Cloud memory advances only after these
    # deliveries succeed, so a retry cannot suppress an insight the app missed.
    api_upload = (
        upload_api_payloads(final, api_payloads.get("files"))
        if api_payloads.get("files")
        else {"status": "skipped", "reason": "api_payload_generation_failed"}
    )
    history_upload = upload_insight_history(final, history_entry)
    summary_history_upload = upload_summary_history(final, summary_history_entry)

    # Project the same validated payloads into the tenant-specific serving
    # container before memory advances. If app delivery fails, the unseen
    # summary/insight keys remain eligible for a safe retry.
    from .tools.ai_content_publisher import enabled as ai_content_enabled, publish as publish_ai_content

    if ai_content_enabled(final) and api_payloads.get("status") == "ok":
        ai_content_upload = publish_ai_content(final)
    elif ai_content_enabled(final):
        ai_content_upload = {
            "status": "failed",
            "reason": "current_api_payload_generation_failed",
            "insightStatus": "failed",
            "summaryStatus": "failed",
        }
    else:
        ai_content_upload = {"status": "skipped", "reason": "ai_content_publish_disabled"}
    final["ai_content_upload"] = ai_content_upload

    delivery_ok = bool(final.get("report_summary") and final.get("insight_report"))
    if cfg.get("api_payloads", True):
        delivery_ok = delivery_ok and api_payloads.get("status") == "ok"
    if cfg.get("azure_blob_upload", False) and cfg.get("api_payloads", True):
        delivery_ok = delivery_ok and api_upload.get("status") == "ok"
    if cfg.get("azure_blob_upload", False) and cfg.get("insight_history_enabled", True):
        delivery_ok = (
            delivery_ok
            and history_upload.get("status") in {"created", "exists"}
            and history_upload.get("feedStatus") in {"updated", "unchanged"}
        )
    if ai_content_enabled(final):
        delivery_ok = delivery_ok and ai_content_upload.get("insightStatus") == "ok"

    summary_delivery_ok = bool(
        final.get("report_summary")
        and final.get("fresh_summary")
        and (final.get("fresh_summary") or {}).get("summary_type") != "memory_unavailable"
    )
    if cfg.get("api_payloads", True):
        summary_delivery_ok = (
            summary_delivery_ok
            and (api_payloads.get("summaryStatus") or {}).get("status") == "ok"
        )
    if cfg.get("summary_history_enabled", True):
        summary_delivery_ok = summary_delivery_ok and summary_history_artifact is not None
    if cfg.get("azure_blob_upload", False) and cfg.get("api_payloads", True):
        summary_delivery_ok = (
            summary_delivery_ok
            and ((api_upload.get("receipts") or {}).get("report_summary.json") or {}).get("status") == "ok"
        )
    if cfg.get("azure_blob_upload", False) and cfg.get("summary_history_enabled", True):
        summary_delivery_ok = (
            summary_delivery_ok
            and summary_history_upload.get("status") in {"created", "exists"}
            and summary_history_upload.get("feedStatus") in {"updated", "unchanged"}
        )
    if ai_content_enabled(final):
        summary_delivery_ok = (
            summary_delivery_ok and ai_content_upload.get("summaryStatus") == "ok"
        )

    from .tools.summary_memory import commit_summary_run

    if final.get("summary_memory_enabled", True) and summary_delivery_ok:
        summary_commit = commit_summary_run(
            final,
            final.get("summary_pending_keys") or [],
            final.get("fresh_summary") or {},
        )
    else:
        summary_commit = {
            "status": "skipped",
            "reason": "delivery_failed" if not summary_delivery_ok else "memory_disabled",
        }
    final["summary_memory_commit"] = summary_commit

    summary_cloud_memory = cloud_summary_memory_enabled(final)
    if summary_cloud_memory and summary_commit.get("status") == "ok":
        summary_memory_publish = publish_summary_memory(final, summary_memory_hydration)
    elif summary_cloud_memory:
        summary_memory_publish = {
            "status": "skipped",
            "reason": "summary_memory_commit_failed",
        }
    else:
        summary_memory_publish = {"status": "skipped", "reason": "local_memory_storage"}

    cloud_memory = cloud_memory_enabled(final)
    memory_commit = final.get("insight_memory_commit", {}) or {}
    if cloud_memory and delivery_ok and memory_commit.get("status") == "ok":
        memory_publish = publish_insight_memory(final, memory_hydration)
    elif cloud_memory:
        memory_publish = {
            "status": "skipped",
            "reason": (
                "delivery_failed" if not delivery_ok else "memory_commit_failed"
            ),
        }
    else:
        memory_publish = {"status": "skipped", "reason": "local_memory_storage"}

    summary_path = out / "report_summary.md"
    if summary_path.exists():
        print("\n----- report_summary.md -----\n")
        print(summary_path.read_text(encoding="utf-8"))

    insight_path = out / "insight_report.md"
    if insight_path.exists():
        print("\n----- insight_report.md -----\n")
        print(insight_path.read_text(encoding="utf-8"))

    if cloud_memory and memory_publish.get("status") != "ok":
        print(
            "Pipeline failed: cloud insight memory was not advanced "
            f"({memory_publish.get('reason') or memory_publish.get('status')})."
        )
        return 1
    if summary_memory_hydration.get("status") == "failed":
        print("Pipeline failed: cloud summary memory could not be hydrated safely; insight outputs were left intact.")
        return 1
    if (final.get("summary_novelty") or {}).get("status") == "memory_unavailable":
        print("Pipeline failed: summary novelty memory is unavailable; it was preserved without overwrite.")
        return 1
    if summary_cloud_memory and summary_memory_publish.get("status") != "ok":
        print(
            "Pipeline failed: cloud summary memory was not advanced "
            f"({summary_memory_publish.get('reason') or summary_memory_publish.get('status')})."
        )
        return 1
    if ai_content_enabled(final) and ai_content_upload.get("status") != "ok":
        print(
            "Pipeline failed: client ai-content was not fully refreshed "
            f"({ai_content_upload.get('reason') or ai_content_upload.get('status')})."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
