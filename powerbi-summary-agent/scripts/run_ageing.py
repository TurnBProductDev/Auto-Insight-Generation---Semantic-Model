"""Run the complete Ageing flow: scan, stat check, investigate, summarize.

    python scripts/run_ageing.py --config config/sbmart-ageing/config.json
    python scripts/run_ageing.py --config ... --from-scan outputs_sbmart_ageing/ageing_scan.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domains.inventory import (ageing_flow, ageing_history, ageing_html,
                                   ageing_mapping, archive, dashboard,
                                   dashboard_html, snapshot_memory,
                                   snapshot_trend)  # noqa: E402


def _executor(workspace: str, dataset: str, token: str):
    from src.tools.powerbi_executor import extract_rows, run_dax

    def execute(dax: str) -> list[dict]:
        ok, body = run_dax(workspace, dataset, dax, token)
        if not ok:
            raise RuntimeError(f"Power BI rejected an Ageing query: {str(body)[:500]}")
        result = (body.get("results") or [{}])[0]
        if result.get("error"):
            raise RuntimeError(f"Ageing DAX failed: {json.dumps(result['error'])[:500]}")
        return extract_rows(body)

    return execute


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/sbmart-ageing/config.json")
    parser.add_argument("--from-scan")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--publish", action="store_true", help="upload to Azure Blob")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    out = ROOT / os.environ.get("AGENT_OUTPUT_FOLDER", cfg.get("output_folder", "outputs_ageing"))
    out.mkdir(parents=True, exist_ok=True)

    metadata = None
    token = None
    if args.from_scan:
        scan_result = json.loads(Path(args.from_scan).read_text(encoding="utf-8"))
    else:
        os.environ.setdefault("POWERBI_TENANT_ID", str(cfg.get("tenant_id") or ""))
        from src.agents import metadata_reader
        meta_state = {**cfg, "output_folder": str(out)}
        meta_result = metadata_reader.run(meta_state)
        if meta_result.get("fatal"):
            print("Ageing semantic metadata is empty; scan refused.")
            return 1
        metadata = meta_result.get("model_metadata") or {}
        token = meta_result.get("pbi_token")
        print("Scanning the Ageing semantic model...")
        scan_result = ageing_flow.scan(
            _executor(cfg["workspace_id"], cfg["dataset_id"], token), cfg, log=print)
        (out / "ageing_scan.json").write_text(ageing_flow.dump_json(scan_result), encoding="utf-8")
        # Keep a dated copy of the raw scan - the semantic model retains only
        # one snapshot, so this is the pipeline's own memory of every earlier
        # position. Keyed on the RUN date, never the model's as-at stamp (see
        # archive.py's own docstring for why that distinction is load-bearing).
        archive.write(scan_result, out, cfg, log=print)
        preview = ageing_flow.build(scan_result, cfg)
        mapping_cfg = cfg.get("ageing_mapping") or {}
        snapshot = (scan_result.get("snapshot") or [{}])[0]
        snapshot_cardinality = next(
            (value for key, value in snapshot.items()
             if str(key).strip("[]").split("[")[-1].strip("]").lower()
             == "snapshot_cardinality"), None)
        semantic = ageing_mapping.resolve(
            metadata,
            overrides={key: mapping_cfg.get(key)
                       for key in ("exposure", "bucket", "snapshot", "non_moving")
                       if mapping_cfg.get(key)} | {"dimensions": mapping_cfg.get("dimensions") or {}},
            observed={
                "snapshot_cardinality": snapshot_cardinality,
                "bucket_order": cfg.get("ageing_bucket_order") or [],
                "high_risk_bands": cfg.get("ageing_high_risk_bands") or [],
                "reconciled": all((preview.get("checks") or {}).values()),
                "aged_derived": True,
            },
        )
        (out / "semantic_mapping.json").write_text(
            ageing_flow.dump_json(semantic), encoding="utf-8")
        if semantic.get("status") != "ready":
            print("Ageing semantic mapping requires review: "
                  + "; ".join(semantic.get("issues") or []))
            return 1
    if args.scan_only:
        return 0

    model = ageing_flow.build(scan_result, cfg)

    # Day-over-day / robust-statistical detection, built on the archive just
    # written. Honest by construction: `compare_window` refuses a comparison
    # against a stale or unchanged position, and `snapshot_trend` refuses a
    # z-score below its configured history floor - both report why rather
    # than staying silent, and neither ever backdates a fabricated span.
    comparison = archive.compare_window(scan_result, out, cfg)

    # The second history lane. The model's own history table gives a reference
    # position whose window moves only when the source system re-freezes it;
    # this one is yesterday's kept scan. They are built by the SAME comparison
    # code and kept as separate lanes on the page, because merging them would
    # produce one comparison whose window silently changes length.
    if comparison.get("comparable") and comparison.get("prior"):
        model["day_movement"] = ageing_history.build(
            ageing_history.position_from_scan(scan_result),
            ageing_history.position_from_scan(comparison["prior"]),
            label="day_on_day")
    else:
        model["day_movement"] = {
            "available": False, "lane": "day_on_day",
            "as_at": model.get("as_at") or "",
            "reason": (comparison.get("reason_text")
                       or "No earlier reading of this report has been kept yet, "
                          "so there is nothing to compare today against."),
        }
    band_trend = snapshot_trend.detect(
        scan_result, out, cfg,
        report_id=str(cfg.get("report_id") or "inventory_ageing"),
        metric="ageing_band",
        extractor=snapshot_trend.series_extractor("bands", "NEW AGE", "aged"),
        comparison=comparison, currency=model.get("currency") or "",
        min_history_days=int(cfg.get("ageing_trend_min_history_days", 5) or 5),
        materiality_pct=float(cfg.get("ageing_trend_materiality_pct", 3.0) or 3.0),
        z_cutoff=float(cfg.get("ageing_trend_z_cutoff", 2.5) or 2.5),
    )
    model["trend_verdict"] = band_trend["verdict"]
    if band_trend["findings"]:
        model["stat_signals"] = sorted(
            model["stat_signals"] + band_trend["findings"],
            key=lambda s: (-float(s.get("score") or 0.0), str(s.get("candidate_id"))))
    print(f"Trend: {comparison['reason'] if not comparison.get('comparable') else 'comparable'}"
         f", {band_trend['verdict']['history_days']} archived day(s), "
         f"{len(band_trend['findings'])} movement finding(s)")

    # Cross-run novelty: which of today's findings are worth alerting on
    # (onset / escalated / duration milestone), plus any clearance for a
    # member that dropped out of today's scan while still flagged. The
    # deterministic report below is built from the FULL `stat_signals` list
    # regardless - only the KPI feed and the investigation budget are
    # memory-filtered, so the page never hides a still-true fact because it
    # was said yesterday.
    # A scheduled Container Apps Job gets a fresh, empty filesystem every
    # run - the local memory file snapshot_memory.py reads/writes has to be
    # synced with a blob before and after, or "already reported" never
    # actually persists (see src/tools/azure_blob.py's hydrate/publish
    # _snapshot_memory functions and their module-docstring reasoning).
    from src.tools import azure_blob

    report_id = str(cfg.get("report_id") or "inventory_ageing")
    dataset_id = str(cfg.get("dataset_id") or "")
    memory_hydration = azure_blob.hydrate_snapshot_memory(cfg, out, report_id, dataset_id)
    if azure_blob.cloud_snapshot_memory_enabled(cfg) and memory_hydration.get("status") == "failed":
        print("Stopped: cloud snapshot memory could not be hydrated safely.")
        return 1

    memory_result = snapshot_memory.filter_signals(
        model["stat_signals"], report_id=report_id,
        out_dir=out, dataset_id=dataset_id,
        observed_at=model.get("as_at") or "")
    reportable = memory_result["reportable"] + memory_result["cleared"]
    model["stat_signals_reportable"] = reportable
    print(f"Memory: {memory_result['stats']['detected']} finding(s), "
         f"{memory_result['stats']['reportable']} worth alerting, "
         f"{memory_result['stats']['suppressed']} unchanged, "
         f"{memory_result['stats']['cleared']} cleared")

    # Adaptive "where does this hotspot concentrate" investigation - only for
    # findings that survived memory filtering, so a live query is never spent
    # narrating the same unchanged finding two days running. Needs a live
    # token (never runs from a saved scan) and is off by default; a failure
    # anywhere inside costs only this section, never the report.
    if token and cfg.get("ageing_investigation_enabled", False):
        from src.domains.inventory import ageing_investigator
        from src.tools.file_io import read_summary_business_rules

        try:
            rules = read_summary_business_rules(str(config_path))
        except Exception:  # noqa: BLE001 - the rulebook is guidance, not a dependency
            rules = ""
        print("Investigating the top Ageing hotspots...")
        investigation_model = {**model, "stat_signals": reportable}
        result = ageing_investigator.investigate(
            _executor(cfg["workspace_id"], cfg["dataset_id"], token),
            investigation_model, cfg, rules=rules, log=print)
        model["investigation"] = result["entries"]
        model["investigation_budget"] = result["budget"]
        print(f"Investigation budget: {result['budget']['used']}/{result['budget']['total']} "
             f"quer{'y' if result['budget']['used'] == 1 else 'ies'} used")

    (out / "report_ageing.json").write_text(ageing_flow.dump_json(model), encoding="utf-8")
    (out / "stat_check.json").write_text(ageing_flow.dump_json(model.get("stat_check")), encoding="utf-8")
    (out / "findings.json").write_text(ageing_flow.dump_json(ageing_flow.findings_payload(model)), encoding="utf-8")
    (out / "report_summary.md").write_text(ageing_flow.summary_markdown(model), encoding="utf-8")
    (out / "insight_report.md").write_text(ageing_flow.insight_markdown(model), encoding="utf-8")
    (out / "report_ageing.html").write_text(ageing_html.render(model, eyebrow="Inventory · SB Mart"), encoding="utf-8")
    page = dashboard.build(model)
    (out / "report_dashboard_ageing.json").write_text(ageing_flow.dump_json(page), encoding="utf-8")
    (out / "report_dashboard_ageing.html").write_text(
        dashboard_html.render(page, eyebrow="Inventory · SB Mart"), encoding="utf-8")

    failures = [name for name, ok in (model.get("checks") or {}).items() if not ok]
    for name, ok in (model.get("checks") or {}).items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    signals = model.get("stat_signals") or []
    print(f"Findings: {len(signals)}")
    print(f"Outputs: {out}")
    if failures:
        print("Report reconciliation failed; outputs are diagnostic only: " + ", ".join(failures))
        return 1

    # The report exists now (every file above is written), which is the same
    # bar `insight_memory.commit_run` uses for "observed" - commit regardless
    # of --publish, a local run is still a real observation of this position.
    snapshot_memory.commit(memory_result)
    memory_publish = azure_blob.publish_snapshot_memory(cfg, out, report_id, dataset_id, memory_hydration)
    if memory_publish.get("status") not in ("ok", "skipped"):
        print(f"Cloud snapshot memory publish did not succeed: {memory_publish}")

    # Ranked findings for the shared KPI feed, memory-filtered so an unchanged
    # finding does not re-alert every day. Deterministic and non-fatal: the
    # report does not depend on them, so a detector problem must never cost
    # the report. Built only when the client has been migrated to the
    # multi-report contract - the cards carry `reportId`, which the app must
    # tolerate first.
    cards: list = []
    limited = reportable[: max(0, int(cfg.get("insight_max_new_per_run", 3) or 3))]
    if cfg.get("ai_content_multi_report_feed", False) and limited:
        from src.tools import api_payloads

        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens"),
                 "report_id": cfg.get("report_id", "inventory_ageing"),
                 "ai_content_multi_report_feed": True,
                 "output_folder": str(out)}
        try:
            cards = api_payloads.generate_kpi_insights_payload(limited, state)
            (out / "kpi_insights.json").write_text(
                json.dumps(cards, indent=2, default=str), encoding="utf-8")
            print(f"KPI cards: {len(cards)}")
        except Exception as exc:  # noqa: BLE001 - the feed must never cost the report
            print(f"KPI cards skipped: {type(exc).__name__}: {exc}")

    if args.publish:
        from src.domains.inventory import ageing_publish

        receipt = ageing_publish.publish(cfg, out, model, cards=cards)
        print(json.dumps(receipt, indent=2, default=str)[:2000])
        return 0 if receipt.get("status") == "ok" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
