"""Produce the Inventory Management report: scan, archive, model, page, publish.

    python scripts/run_inventory.py --config config/inventory/config.json
    python scripts/run_inventory.py --scan-only          # no render, no publish
    python scripts/run_inventory.py --from-scan path.json  # rebuild, no live call
    python scripts/run_inventory.py --publish            # push to Azure Blob

Deliberately not part of the LangGraph pipeline, for the same reason Target
Tracker is not: the summary branch there is built around a year-on-year spine
with focus rotation and coverage, and a stock position has no prior period to
rotate over. This follows the Target Tracker runner's shape - deterministic
scan, model, render - and publishes through the same `ai_content_publisher` so
the app sees it exactly like any other report.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import archive  # noqa: E402
from src.domains.inventory.reports import stock_health as sh  # noqa: E402


def _executor(workspace_id: str, dataset_id: str, token: str):
    from src.tools.powerbi_executor import extract_rows, run_dax

    def execute(dax: str) -> list[dict]:
        ok, body = run_dax(workspace_id, dataset_id, dax, token)
        if not ok:
            raise RuntimeError(
                f"Power BI rejected an Inventory Management query: {json.dumps(body)[:400]}")
        result = (body.get("results") or [{}])[0]
        if result.get("error"):
            # A 200 carrying an embedded error is a real DAX failure, not an
            # empty result. Trusting resp.ok alone turns it into a fabricated
            # zero-row success.
            raise RuntimeError(
                f"Inventory Management query failed: {json.dumps(result['error'])[:400]}")
        return extract_rows(body)

    return execute


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/inventory/config.json")
    parser.add_argument("--scan-only", action="store_true")
    parser.add_argument("--from-scan", default=None,
                        help="rebuild from a saved scan, no live call")
    parser.add_argument("--publish", action="store_true", help="upload to Azure Blob")
    parser.add_argument("--run-date", default=None,
                        help="force the archive's run date (YYYY-MM-DD); testing only")
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
    out_dir = PROJECT_ROOT / cfg.get("output_folder", "outputs_inventory")
    out_dir.mkdir(parents=True, exist_ok=True)
    run_date = _dt.date.fromisoformat(args.run_date) if args.run_date else _dt.date.today()

    if args.from_scan:
        scanned = json.loads(Path(args.from_scan).read_text(encoding="utf-8"))
        print(f"Rebuilt from {args.from_scan}")
    else:
        import os

        os.environ.setdefault("POWERBI_TENANT_ID", str(cfg.get("tenant_id") or ""))
        from src.tools.powerbi_executor import get_powerbi_token

        # One token, fetched here and passed down. Never inside `scan`: the
        # acquisition does an unlocked read-modify-write of the shared cache.
        token = get_powerbi_token(cfg.get("tenant_id"))
        execute = _executor(cfg["workspace_id"], cfg["dataset_id"], token)
        print("Scanning the Inventory Management model...")
        scanned = sh.scan(execute, cfg, log=print)
        (out_dir / "stock_health_scan.json").write_text(
            json.dumps(scanned, indent=2, default=str), encoding="utf-8")
        print(f"Scan written to {out_dir / 'stock_health_scan.json'}")
        archive.write(scanned, out_dir, cfg, run_date=run_date, log=print)

    if args.scan_only:
        return 0

    # Whether today may be compared against a kept position, and if not, why -
    # in words the page can print. Never fabricated: no archive means no
    # comparison, stated plainly.
    window = archive.compare_window(scanned, out_dir, cfg, run_date=run_date)
    print(f"Comparison: {window['reason']}"
          + (f" (prior as at {window['prior_as_at']})" if window.get("prior_as_at") else ""))

    model = sh.build(scanned, currency=cfg.get("inventory_currency", "SAR"))
    model["comparison"] = {k: v for k, v in window.items() if k != "prior"}
    if window["reason_text"]:
        model["caveats"] = list(model["caveats"]) + [window["reason_text"]]

    # What appeared, cleared or moved since the last kept position - computed
    # only once the archive has confirmed the two are genuinely comparable, so
    # there is no path by which a movement can be stated without one.
    if window.get("comparable") and window.get("prior"):
        from src.domains.inventory import stock_health_signals as signals_mod

        prior_model = sh.build(window["prior"], currency=model["currency"])
        model["state_changes"] = signals_mod.state_diff(
            model["queue"], prior_model["queue"])
        print(f"State changes {window['label']}: {len(model['state_changes'])}")

    (out_dir / "report_stock_health.json").write_text(
        json.dumps(model, indent=2, default=str), encoding="utf-8")

    failed = [name for name, ok in model["checks"].items() if not ok]
    for name, ok in model["checks"].items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if failed:
        print(f"Reconciliation failed: {failed}. Report not written.")
        return 1

    from src.domains.inventory import dashboard, dashboard_html, health, money

    # One currency for the whole run, set before anything formats a figure.
    money.use(cfg.get("inventory_currency"))
    score = health.build(scanned)
    if score:
        failed_score = [n for n, ok in score["checks"].items() if not ok]
        for name, ok in score["checks"].items():
            print(f"  {'PASS' if ok else 'FAIL'}  score: {name}")
        if failed_score:
            print(f"The health score does not reconcile: {failed_score}. Not written.")
            return 1
        (out_dir / "report_inventory_health.json").write_text(
            json.dumps(score, indent=2, default=str), encoding="utf-8")
    else:
        print("  This model publishes no Inventory Health Score; those tabs are omitted.")

    # The four prose slots. Structure stays code-owned; the model fills these
    # and nothing else, and every draft is validated before it is used.
    from src.domains.inventory import stock_health_author as author
    from src.tools.file_io import read_summary_business_rules

    try:
        rules = read_summary_business_rules(str(config_path))
    except Exception:  # noqa: BLE001 - the rulebook is guidance, not a dependency
        rules = ""
    model["prose"] = author.author(model, cfg, score, rules=rules, log=print)
    print(f"Prose: {model['prose']['authoring_mode']}")
    (out_dir / "report_stock_health.json").write_text(
        json.dumps(model, indent=2, default=str), encoding="utf-8")

    page = dashboard.build_stock_health(model, score)
    (out_dir / "dashboard_stock_health.json").write_text(
        json.dumps(page, indent=2, default=str), encoding="utf-8")
    (out_dir / "report_dashboard_stock_health.html").write_text(
        dashboard_html.render(page), encoding="utf-8")
    print(f"Page written: {out_dir / 'report_dashboard_stock_health.html'}")

    # Ranked findings for the shared KPI feed. Deterministic and non-fatal: the
    # report does not depend on them, so a detector problem must never cost the
    # page.
    from src.domains.inventory import stock_health_signals as signals_mod

    signals = signals_mod.detect(
        model, score, limit=int(cfg.get("insight_max_new_per_run", 3) or 3))
    (out_dir / "insight_signals.json").write_text(
        json.dumps(signals, indent=2, default=str), encoding="utf-8")
    print()
    print(f"Signals: {len(signals)}")
    for signal in signals:
        print(f"  {signal['id']:3} {signal['severity']:8} {signal['analysis_type']:34}"
              f" {signal['affected_segment']}")

    header = model["header"]
    currency = model["currency"]
    print()
    print(f"As at {model['as_at']}  ({currency})")
    print(f"  Stock Value        {header['stock_value']:16,.0f}")
    print(f"  Excess Stock       {header['excess_value']:16,.0f}"
          f"   ({header['excess_share_pct']:.1f}% of Stock Value)")
    print(f"  Pending Orders     {header['pending_value']:16,.0f}")
    print(f"  Opportunity Loss   {header['opportunity_loss_day']:16,.0f}   per day, scoped")
    print(f"  Loc-SKUs {header['loc_skus']:,.0f} covering {header['skus']:,.0f} SKUs "
          f"at {header['locations']:.0f} Locations")
    if model["states_absent_urgent"]:
        print(f"  Urgent states with no rows: {model['states_absent_urgent']}")
    print(f"Outputs: {out_dir}")

    # KPI cards for the shared client feed. Built only when the client has been
    # migrated to the multi-report contract - the cards carry `reportId`, which
    # the app must tolerate first.
    cards: list = []
    if cfg.get("ai_content_multi_report_feed", False) and signals:
        from src.tools import api_payloads

        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens"),
                 "report_id": cfg.get("report_id", "inventory_stock_health"),
                 "ai_content_multi_report_feed": True,
                 "output_folder": str(out_dir)}
        try:
            cards = api_payloads.generate_kpi_insights_payload(signals, state)
            (out_dir / "kpi_insights.json").write_text(
                json.dumps(cards, indent=2, default=str), encoding="utf-8")
            print(f"KPI cards: {len(cards)}")
        except Exception as exc:  # noqa: BLE001 - the feed must never cost the report
            print(f"KPI cards skipped: {type(exc).__name__}: {exc}")

    if args.publish:
        from src.domains.inventory import stock_health_publish as publish

        receipt = publish.publish(cfg, out_dir, model, score, cards=cards)
        print(json.dumps(receipt, indent=2, default=str)[:2000])
        return 0 if receipt.get("status") == "ok" else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
