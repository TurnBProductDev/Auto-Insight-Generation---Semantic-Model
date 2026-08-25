"""Produce the Daily Sales report: scan, model, page, publish.

    python scripts/run_daily_sales.py --config config/sbmart-dailysales/config.json
    python scripts/run_daily_sales.py --from-scan outputs_sbmart_dailysales/daily_sales_scan.json
    python scripts/run_daily_sales.py --publish                # push to Azure Blob

Deliberately not part of the LangGraph pipeline - same reasoning as Target
Tracker and the inventory reports: the source model hands this report a
pre-benchmarked snapshot, not raw transactions, so there is no year-on-year
spine or focus rotation for it to plug into. See `src/domains/sales/
daily_sales.py`'s module docstring for the verified model defect that
bounds what this report can show today.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domains.inventory import snapshot_memory  # noqa: E402
from src.domains.sales import daily_sales, daily_sales_dashboard, daily_sales_html  # noqa: E402


def _executor(workspace_id: str, dataset_id: str, token: str):
    from src.tools.powerbi_executor import extract_rows, run_dax

    def execute(dax: str) -> list[dict]:
        ok, body = run_dax(workspace_id, dataset_id, dax, token)
        if not ok:
            raise RuntimeError(f"Power BI rejected a Daily Sales query: {json.dumps(body)[:400]}")
        result = (body.get("results") or [{}])[0]
        if result.get("error"):
            raise RuntimeError(f"Daily Sales query failed: {json.dumps(result['error'])[:400]}")
        return extract_rows(body)

    return execute


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/sbmart-dailysales/config.json")
    parser.add_argument("--from-scan", default=None, help="rebuild from a saved scan, no live call")
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
                                cfg.get("output_folder", "outputs_sbmart_dailysales"))
    out.mkdir(parents=True, exist_ok=True)

    token = None
    if args.from_scan:
        scan_result = json.loads(Path(args.from_scan).read_text(encoding="utf-8"))
    else:
        os.environ.setdefault("POWERBI_TENANT_ID", str(cfg.get("tenant_id") or ""))
        from src.tools.powerbi_executor import get_powerbi_token

        token = get_powerbi_token(cfg.get("tenant_id"))
        print("Scanning the Daily Sales semantic model...")
        scan_result = daily_sales.scan(
            _executor(cfg["workspace_id"], cfg["dataset_id"], token), cfg, log=print)
        (out / "daily_sales_scan.json").write_text(daily_sales.dump_json(scan_result), encoding="utf-8")
    if args.scan_only:
        return 0

    model = daily_sales.build(scan_result, cfg)
    page = daily_sales_dashboard.build(model)
    page["report_id"] = model["report_id"]
    signals = daily_sales_dashboard.to_signals(page)

    # Cross-run novelty (see run_ageing.py's identical wiring for the full
    # reasoning): the deterministic report below always shows every current
    # finding; only the KPI feed and the investigation budget are filtered.
    #
    # A scheduled Container Apps Job gets a fresh, empty filesystem every
    # run, so the local memory file snapshot_memory.py reads/writes has to
    # be synced with a blob before and after - otherwise "already reported"
    # would never actually persist and every run would look like day one.
    from src.tools import azure_blob

    dataset_id = str(cfg.get("dataset_id") or "")
    memory_hydration = azure_blob.hydrate_snapshot_memory(cfg, out, model["report_id"], dataset_id)
    if azure_blob.cloud_snapshot_memory_enabled(cfg) and memory_hydration.get("status") == "failed":
        print("Stopped: cloud snapshot memory could not be hydrated safely.")
        return 1

    memory_result = snapshot_memory.filter_signals(
        signals, report_id=model["report_id"], out_dir=out,
        dataset_id=dataset_id, observed_at=model["as_at"])
    reportable = memory_result["reportable"] + memory_result["cleared"]
    print(f"Memory: {memory_result['stats']['detected']} finding(s), "
         f"{memory_result['stats']['reportable']} worth alerting, "
         f"{memory_result['stats']['suppressed']} unchanged, "
         f"{memory_result['stats']['cleared']} cleared")

    if token and cfg.get("daily_sales_investigation_enabled", False):
        from src.domains.sales import daily_sales_investigator
        from src.tools.file_io import read_summary_business_rules

        try:
            rules = read_summary_business_rules(str(config_path))
        except Exception:  # noqa: BLE001 - the rulebook is guidance, not a dependency
            rules = ""
        print("Investigating the top Daily Sales hotspots...")
        investigation_model = {"currency": page["currency"], "stat_signals": reportable}
        result = daily_sales_investigator.investigate(
            _executor(cfg["workspace_id"], cfg["dataset_id"], token),
            investigation_model, cfg, rules=rules, log=print,
            scale=float((model.get("scale") or {}).get("scale") or 1.0))
        page["investigation"] = result["entries"]
        page["investigation_budget"] = result["budget"]
        print(f"Investigation budget: {result['budget']['used']}/{result['budget']['total']} "
             f"quer{'y' if result['budget']['used'] == 1 else 'ies'} used")

    (out / "report_daily_sales.json").write_text(daily_sales.dump_json(page), encoding="utf-8")
    (out / "findings.json").write_text(daily_sales.dump_json({
        "report_id": model["report_id"], "as_at": model["as_at"], "findings": signals,
        "reportable": reportable, "checks": model["checks"],
    }), encoding="utf-8")

    html = daily_sales_html.render(page, eyebrow="Sales · SB Mart")
    (out / "report_daily_sales.html").write_text(html, encoding="utf-8")

    failures = [name for name, ok in model["checks"].items() if not ok]
    for name, ok in model["checks"].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"Findings: {len(signals)}")
    print(f"Outputs: {out}")
    if failures:
        print("Report reconciliation failed; outputs are diagnostic only: " + ", ".join(failures))
        return 1

    snapshot_memory.commit(memory_result)
    memory_publish = azure_blob.publish_snapshot_memory(
        cfg, out, model["report_id"], dataset_id, memory_hydration)
    if memory_publish.get("status") not in ("ok", "skipped"):
        print(f"Cloud snapshot memory publish did not succeed: {memory_publish}")

    cards: list = []
    limited = reportable[: max(0, int(cfg.get("insight_max_new_per_run", 3) or 3))]
    if cfg.get("ai_content_multi_report_feed", False) and limited:
        from src.tools import api_payloads

        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens"),
                 "report_id": cfg.get("report_id", "daily_sales"),
                 "ai_content_multi_report_feed": True, "output_folder": str(out)}
        try:
            cards = api_payloads.generate_kpi_insights_payload(limited, state)
            (out / "kpi_insights.json").write_text(
                json.dumps(cards, indent=2, default=str), encoding="utf-8")
            print(f"KPI cards: {len(cards)}")
        except Exception as exc:  # noqa: BLE001 - the feed must never cost the report
            print(f"KPI cards skipped: {type(exc).__name__}: {exc}")

    if args.publish:
        from src.domains.sales import daily_sales_publish

        receipt = daily_sales_publish.publish(cfg, out, page, cards=cards)
        print(json.dumps(receipt, indent=2, default=str)[:2000])
        return 0 if receipt.get("status") == "ok" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
