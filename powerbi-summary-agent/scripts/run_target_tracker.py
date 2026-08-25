"""Produce the Target Tracker report: scan, model, page, business document, publish.

    python scripts/run_target_tracker.py --config config/targettracker/config.json
    python scripts/run_target_tracker.py --anchor 2026-07-16      # a specific day
    python scripts/run_target_tracker.py --scan-only              # no render, no publish
    python scripts/run_target_tracker.py --publish                # push to Azure Blob

Deliberately not part of the LangGraph pipeline. The summary branch there is built around
a year-on-year spine with focus rotation and coverage; Target Tracker has no prior year and
its structure is fixed by its rulebook, so it follows the inventory reports' pattern -
deterministic scan, model, render - and publishes through the same `ai_content_publisher`
so the app sees it exactly like any other report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.sales import target_tracker as tt  # noqa: E402


def _executor(workspace_id: str, dataset_id: str, token: str):
    from src.tools.powerbi_executor import extract_rows, run_dax

    def execute(dax: str) -> list[dict]:
        ok, body = run_dax(workspace_id, dataset_id, dax, token)
        if not ok:
            raise RuntimeError(f"Power BI rejected a Target Tracker query: {json.dumps(body)[:400]}")
        result = (body.get("results") or [{}])[0]
        if result.get("error"):
            # A 200 with an embedded error is a real DAX failure, not an empty result.
            raise RuntimeError(f"Target Tracker query failed: {json.dumps(result['error'])[:400]}")
        return extract_rows(body)

    return execute


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/targettracker/config.json")
    parser.add_argument("--anchor", default=None, help="force the anchor date (YYYY-MM-DD)")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--publish", action="store_true", help="upload to Azure Blob")
    parser.add_argument("--from-scan", default=None, help="rebuild from a saved scan, no live call")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(PROJECT_ROOT / ".env")
    except ImportError:
        pass

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    out_dir = PROJECT_ROOT / os.environ.get(
        "AGENT_OUTPUT_FOLDER", cfg.get("output_folder", "outputs_targettracker")
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    population = cfg.get("target_tracker_population") or []

    if args.from_scan:
        scanned = json.loads(Path(args.from_scan).read_text(encoding="utf-8"))
        print(f"Rebuilt from {args.from_scan}")
    else:
        os.environ.setdefault("POWERBI_TENANT_ID", str(cfg.get("tenant_id") or ""))
        from src.tools.powerbi_executor import get_powerbi_token

        token = get_powerbi_token(cfg.get("tenant_id"))
        execute = _executor(cfg["workspace_id"], cfg["dataset_id"], token)
        print("Scanning the Target Tracker model...")
        scanned = tt.scan(execute, population,
                          anchor_override=args.anchor or cfg.get("target_tracker_anchor_override") or "",
                          log=print)
        (out_dir / "target_tracker_scan.json").write_text(
            json.dumps(scanned, indent=2, default=str), encoding="utf-8")
        print(f"Scan written to {out_dir / 'target_tracker_scan.json'}")

    if args.scan_only:
        return 0

    model = tt.build(scanned)
    (out_dir / "report_target_tracker.json").write_text(
        json.dumps(model, indent=2, default=str), encoding="utf-8")

    failed = [name for name, ok in model["checks"].items() if not ok]
    for name, ok in model["checks"].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(f"Reconciliation failed: {failed}. Report not written.")
        return 1

    from src.domains.sales import target_tracker_author as author
    from src.domains.sales import target_tracker_doc as doc
    from src.domains.sales import target_tracker_html as html
    from src.tools.file_io import read_summary_business_rules

    rules = ""
    try:
        rules = read_summary_business_rules(str(config_path))
    except Exception:  # noqa: BLE001 - the rulebook is guidance, not a dependency
        rules = ""
    model["prose"] = author.author(model, cfg, rules=rules, log=print)
    (out_dir / "report_target_tracker.json").write_text(
        json.dumps(model, indent=2, default=str), encoding="utf-8")

    report_title = str(
        cfg.get("api_summary_title") or cfg.get("report_name") or "Target Tracker"
    ).strip()
    brand = (
        report_title[:-len("Target Tracker")].strip()
        if report_title.lower().endswith("target tracker")
        else ""
    )
    (out_dir / "report_target_tracker.html").write_text(
        html.render(
            model,
            currency=cfg.get("target_tracker_currency", "SAR"),
            title=report_title,
            eyebrow=f"Sales · {brand}" if brand else "Sales",
        ),
        encoding="utf-8",
    )
    (out_dir / "report_target_tracker.md").write_text(
        doc.render(model, currency=cfg.get("target_tracker_currency", "SAR")), encoding="utf-8")

    # P5.2: ranked target-vs-actual signals for the shared KPI feed. Deterministic
    # and non-fatal - the report itself does not depend on them, so a detector
    # problem must never cost the page.
    from src.domains.sales import target_tracker_signals as signals_mod

    signals = signals_mod.detect(model, limit=int(cfg.get("insight_max_new_per_run", 3) or 3))
    (out_dir / "insight_signals.json").write_text(
        json.dumps(signals, indent=2, default=str), encoding="utf-8")
    print()
    print(f"Signals: {len(signals)}")
    for signal in signals:
        print(f"  {signal['id']:3} {signal['severity']:8} {signal['analysis_type']}"
              f"  {signal['affected_segment']}")

    periods = model["periods"]
    print()
    print(f"Anchor {model['anchor']}"
          + (f" (sales run {model['target_lag_days']} days later, to {model['sold_through']})"
             if model["target_lag_days"] else ""))
    for key in ("day", "wtd", "mtd", "ytd"):
        p = periods[key]
        print(f"  {p['name']:20} {p['attainment']:6.1f}% of target   "
              f"{p['actual']:14,.0f} vs {p['target']:14,.0f}   {p['status']}")
    print(f"Outputs: {out_dir}")

    # KPI cards for the shared client feed. Only built when the client has been
    # migrated to the multi-report contract - the cards carry `reportId`, which
    # the app must tolerate first (docs/phase5-app-contract-change.md).
    cards: list = []
    if cfg.get("ai_content_multi_report_feed", False) and signals:
        from src.tools import api_payloads

        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens"),
                 "report_id": cfg.get("report_id", "target_tracker"),
                 "ai_content_multi_report_feed": True,
                 "ai_content_kpi_card_fields": cfg.get("ai_content_kpi_card_fields", False),
                 "output_folder": str(out_dir)}
        try:
            cards = api_payloads.generate_kpi_insights_payload(signals, state)
            (out_dir / "kpi_insights.json").write_text(
                json.dumps(cards, indent=2, default=str), encoding="utf-8")
            print(f"KPI cards: {len(cards)}")
        except Exception as exc:  # noqa: BLE001 - the feed must never cost the report
            print(f"KPI cards skipped: {type(exc).__name__}: {exc}")

    if args.publish:
        from src.domains.sales import target_tracker_publish as publish

        receipt = publish.publish(cfg, out_dir, model, cards=cards)
        print(json.dumps(receipt, indent=2)[:2000])
        return 0 if receipt.get("status") == "ok" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
