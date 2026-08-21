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

from src.domains.inventory import (ageing_flow, ageing_html, ageing_mapping,
                                   dashboard, dashboard_html)  # noqa: E402


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
    args = parser.parse_args(argv)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    out = ROOT / os.environ.get("AGENT_OUTPUT_FOLDER", cfg.get("output_folder", "outputs_ageing"))
    out.mkdir(parents=True, exist_ok=True)

    metadata = None
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
    print(f"Findings: {len(model.get('stat_signals') or [])}")
    print(f"Outputs: {out}")
    if failures:
        print("Report reconciliation failed; outputs are diagnostic only: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
