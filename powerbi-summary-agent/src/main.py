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

from . import config_schema
from .graph import build_graph
from .kernel import report as kernel_report

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
    """Seed the graph state from a loaded config.

    ``config_schema`` owns every default, so adding a key there is the only edit
    needed for it to reach the graph - there is no second copy of a default to
    drift. Only genuinely derived values are computed here: the two memory
    roots (which are not config keys) and the identifiers the CLI hard-requires.
    """
    state = config_schema.state_defaults(cfg)

    output_folder = state["output_folder"]
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

    state.update(
        {
            # Node 1 (load_config) reads business_rules.md from beside this path.
            "config_path": config_path,
            "tenant_id": cfg["tenant_id"],
            "workspace_id": cfg["workspace_id"],
            "dataset_id": cfg["dataset_id"],
            "insight_memory_root": memory_root,
            "summary_memory_root": summary_memory_root,
            "config": cfg,
            "logs": [],
            "errors": [],
        }
    )
    return state


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


def _summary_delivery_gate(
    final: dict,
    cfg: dict,
    *,
    api_payloads: dict,
    api_upload: dict,
    history_artifact,
    history_upload: dict,
    ai_content_upload: dict,
) -> dict:
    """Evaluate only explicitly required Summary delivery channels.

    Local report delivery is always load-bearing. History is required by the
    default R4 configuration. API/blob/app publishing stays visible in its own
    receipt but cannot freeze weekly rotation unless a deployment explicitly
    adds that channel to ``summary_required_delivery_channels``.
    """
    local_ok = bool(
        final.get("report_summary")
        and final.get("fresh_summary")
        and (final.get("fresh_summary") or {}).get("summary_type") != "memory_unavailable"
    )
    receipts = api_upload.get("receipts") or {}
    channels = {
        "local_report": local_ok,
        "history": history_artifact is not None,
        "api_payload": (api_payloads.get("summaryStatus") or {}).get("status") == "ok",
        "blob_report": (receipts.get("report_summary.json") or {}).get("status") == "ok",
        "blob_history": (
            history_upload.get("status") in {"created", "exists"}
            and history_upload.get("feedStatus") in {"updated", "unchanged"}
        ),
        "ai_content": ai_content_upload.get("summaryStatus") == "ok",
    }
    raw = cfg.get("summary_required_delivery_channels", ["local_report", "history"])
    if isinstance(raw, str):
        raw = [raw]
    required = list(dict.fromkeys(str(item).strip().casefold() for item in raw or [] if str(item).strip()))
    if "local_report" not in required:
        required.insert(0, "local_report")
    unknown = [channel for channel in required if channel not in channels]
    failed = [channel for channel in required if not channels.get(channel, False)]
    return {
        "ok": not failed and not unknown,
        "required": required,
        "channels": channels,
        "failed": failed,
        "unknown": unknown,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Power BI Report Summary Agent")
    parser.add_argument(
        "--config",
        default=os.environ.get("AGENT_CONFIG_PATH")
        or str(PROJECT_ROOT / "config" / "config.json"),
    )
    parser.add_argument(
        "--report",
        default=os.environ.get("AGENT_REPORT_ID") or None,
        help="which report this run produces. Omit to use the report named in "
             "the config, which is what every pre-WP1 invocation does.",
    )
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    if args.report:
        # The flag wins over the config, mirroring how POWERBI_TENANT_ID
        # overrides the configured tenant.
        cfg = {**cfg, "report_id": args.report}
    state = build_initial_state(cfg, str(Path(args.config)))
    print(f"Report: {kernel_report.from_state(state).summary()}")

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

    summary_delivery_gate = _summary_delivery_gate(
        final,
        cfg,
        api_payloads=api_payloads,
        api_upload=api_upload,
        history_artifact=summary_history_artifact,
        history_upload=summary_history_upload,
        ai_content_upload=ai_content_upload,
    )
    summary_delivery_ok = bool(summary_delivery_gate["ok"])
    final["summary_delivery_gate"] = summary_delivery_gate

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
            "failed_channels": summary_delivery_gate.get("failed") or summary_delivery_gate.get("unknown"),
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
