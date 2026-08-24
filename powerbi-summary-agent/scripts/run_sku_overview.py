"""Run the complete SKU Overview flow: scan, stat check, summarize, publish.

    python scripts/run_sku_overview.py --config config/sbmart-skuoverview/config.json
    python scripts/run_sku_overview.py --config ... --from-scan outputs_sbmart_skuoverview/sku_overview_scan.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domains.inventory import (archive, snapshot_memory,  # noqa: E402
                                   snapshot_trend, sku_overview_flow)


def _executor(workspace: str, dataset: str, token: str):
    from src.tools.powerbi_executor import extract_rows, run_dax

    def execute(dax: str) -> list[dict]:
        ok, body = run_dax(workspace, dataset, dax, token)
        if not ok:
            raise RuntimeError(f"Power BI rejected a SKU Overview query: {str(body)[:500]}")
        result = (body.get("results") or [{}])[0]
        if result.get("error"):
            raise RuntimeError(f"SKU Overview DAX failed: {json.dumps(result['error'])[:500]}")
        return extract_rows(body)

    return execute


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/sbmart-skuoverview/config.json")
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
    out = ROOT / os.environ.get("AGENT_OUTPUT_FOLDER",
                                cfg.get("output_folder", "outputs_sbmart_skuoverview"))
    out.mkdir(parents=True, exist_ok=True)

    token = None
    if args.from_scan:
        scan_result = json.loads(Path(args.from_scan).read_text(encoding="utf-8"))
    else:
        os.environ.setdefault("POWERBI_TENANT_ID", str(cfg.get("tenant_id") or ""))
        from src.tools.powerbi_executor import get_powerbi_token

        token = get_powerbi_token(cfg.get("tenant_id"))
        print("Scanning the SKU Overview semantic model...")
        scan_result = sku_overview_flow.scan(
            _executor(cfg["workspace_id"], cfg["dataset_id"], token), cfg, log=print)
        (out / "sku_overview_scan.json").write_text(
            sku_overview_flow.dump_json(scan_result), encoding="utf-8")
        # Keep a dated copy - the semantic model retains only one snapshot.
        archive.write(scan_result, out, cfg, log=print)
    if args.scan_only:
        return 0

    model = sku_overview_flow.build(scan_result, cfg)

    # The eight rulebook insights (sku-insights-rules.md), scoped to the five
    # shops only - warehouses are storage, not selling locations, and the
    # earlier generic hotspot detector scored them anyway. Needs a live
    # token; from a saved scan the report falls back to the broader,
    # unscoped detector already computed inside `build()`.
    insights = None
    detail = None
    model_top = None
    insights_top = None
    detail_top = None
    product = None
    if token:
        from src.domains.inventory import sku_overview_insights, sku_overview_product

        execute = _executor(cfg["workspace_id"], cfg["dataset_id"], token)

        print("Running the eight SKU Overview insight rules...")
        insights = sku_overview_insights.run_all(execute, cfg, log=print)
        model["insights"] = insights
        rule_signals = sku_overview_insights.to_signals(insights, model)
        if rule_signals:
            model["stat_signals"] = rule_signals

        print("Departments and shops - full detail, all products...")
        detail = sku_overview_insights.department_shop_detail(execute)

        print("One product in full...")
        weeks = int(cfg.get("sku_overview_product_weeks", 12) or 12)
        product = sku_overview_product.build(execute, insights, weeks=weeks, log=print)

        if cfg.get("sku_overview_top_view_enabled", True):
            print("Best sellers only (Segment A) - a second, separate scan...")
            scan_top = sku_overview_flow.scan_overview(execute, cfg, seg_a_only=True, log=print)
            model_top = sku_overview_flow.build(scan_top, cfg)
            insights_top = sku_overview_insights.run_all(execute, cfg, seg_a_only=True, log=print)
            detail_top = sku_overview_insights.department_shop_detail(execute, seg_a_only=True)

    # Day-over-day / robust-statistical detection on the STOCK OUT - PLACE
    # ORDER state's stock value and each state's excess exposure, built on
    # the archive above. Honest by construction: see `run_ageing.py`'s
    # identical wiring for why a comparison is refused rather than guessed.
    action_column = str((cfg.get("sku_overview_mapping") or {}).get("recommended_action") or "")
    action_alias = sku_overview_flow._alias(action_column) if action_column else "RECOMMENDED_ACTION"
    comparison = archive.compare_window(scan_result, out, cfg)
    state_trend = snapshot_trend.detect(
        scan_result, out, cfg,
        report_id=str(cfg.get("report_id") or "sku_overview"),
        metric="recommended_action_state",
        extractor=snapshot_trend.series_extractor("states", action_alias, "stock_value"),
        comparison=comparison, currency=model.get("currency") or "",
        min_history_days=int(cfg.get("sku_overview_trend_min_history_days", 5) or 5),
        materiality_pct=float(cfg.get("sku_overview_trend_materiality_pct", 3.0) or 3.0),
        z_cutoff=float(cfg.get("sku_overview_trend_z_cutoff", 2.5) or 2.5),
    )
    model["trend_verdict"] = state_trend["verdict"]
    if state_trend["findings"]:
        model["stat_signals"] = sorted(
            model["stat_signals"] + state_trend["findings"],
            key=lambda s: (-float(s.get("score") or 0.0), str(s.get("candidate_id"))))
    print(f"Trend: {comparison['reason'] if not comparison.get('comparable') else 'comparable'}"
         f", {state_trend['verdict']['history_days']} archived day(s), "
         f"{len(state_trend['findings'])} movement finding(s)")

    # Cross-run novelty - see run_ageing.py's identical wiring for the full
    # reasoning. The deterministic report below always shows every current
    # finding; only the KPI feed and the investigation budget are filtered.
    from src.tools import azure_blob

    report_id = str(cfg.get("report_id") or "sku_overview")
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

    if token and cfg.get("sku_overview_investigation_enabled", False):
        from src.domains.inventory import sku_overview_investigator
        from src.tools.file_io import read_summary_business_rules

        try:
            rules = read_summary_business_rules(str(config_path))
        except Exception:  # noqa: BLE001 - the rulebook is guidance, not a dependency
            rules = ""
        print("Investigating the top SKU Overview hotspots...")
        investigation_model = {**model, "stat_signals": reportable}
        result = sku_overview_investigator.investigate(
            _executor(cfg["workspace_id"], cfg["dataset_id"], token),
            investigation_model, cfg, rules=rules, log=print)
        model["investigation"] = result["entries"]
        model["investigation_budget"] = result["budget"]
        print(f"Investigation budget: {result['budget']['used']}/{result['budget']['total']} "
             f"quer{'y' if result['budget']['used'] == 1 else 'ies'} used")

    (out / "report_sku_overview.json").write_text(sku_overview_flow.dump_json(model), encoding="utf-8")
    (out / "stat_check.json").write_text(sku_overview_flow.dump_json(model.get("stat_check")),
                                         encoding="utf-8")
    (out / "findings.json").write_text(
        sku_overview_flow.dump_json(sku_overview_flow.findings_payload(model)), encoding="utf-8")
    (out / "report_summary.md").write_text(sku_overview_flow.summary_markdown(model), encoding="utf-8")
    (out / "insight_report.md").write_text(sku_overview_flow.insight_markdown(model), encoding="utf-8")

    from src.domains.inventory import sku_overview_dashboard, sku_overview_dashboard_html

    dashboard_page = sku_overview_dashboard.build(
        model, insights, detail, model_top=model_top, insights_top=insights_top,
        detail_top=detail_top, product=product)
    (out / "report_sku_overview.html").write_text(
        sku_overview_dashboard_html.render(dashboard_page, eyebrow="Inventory · SB Mart"),
        encoding="utf-8")

    failures = [name for name, ok in (model.get("checks") or {}).items() if not ok]
    for name, ok in (model.get("checks") or {}).items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    signals = model.get("stat_signals") or []
    print(f"Findings: {len(signals)}")
    print(f"Outputs: {out}")
    if failures:
        print("Report reconciliation failed; outputs are diagnostic only: " + ", ".join(failures))
        return 1

    snapshot_memory.commit(memory_result)
    memory_publish = azure_blob.publish_snapshot_memory(cfg, out, report_id, dataset_id, memory_hydration)
    if memory_publish.get("status") not in ("ok", "skipped"):
        print(f"Cloud snapshot memory publish did not succeed: {memory_publish}")

    cards: list = []
    limited = reportable[: max(0, int(cfg.get("insight_max_new_per_run", 3) or 3))]
    if cfg.get("ai_content_multi_report_feed", False) and limited:
        from src.tools import api_payloads

        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens"),
                 "report_id": cfg.get("report_id", "sku_overview"),
                 "ai_content_multi_report_feed": True, "output_folder": str(out)}
        try:
            cards = api_payloads.generate_kpi_insights_payload(limited, state)
            (out / "kpi_insights.json").write_text(
                json.dumps(cards, indent=2, default=str), encoding="utf-8")
            print(f"KPI cards: {len(cards)}")
        except Exception as exc:  # noqa: BLE001 - the feed must never cost the report
            print(f"KPI cards skipped: {type(exc).__name__}: {exc}")

    if args.publish:
        from src.domains.inventory import sku_overview_publish

        receipt = sku_overview_publish.publish(cfg, out, model, cards=cards)
        print(json.dumps(receipt, indent=2, default=str)[:2000])
        return 0 if receipt.get("status") == "ok" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
