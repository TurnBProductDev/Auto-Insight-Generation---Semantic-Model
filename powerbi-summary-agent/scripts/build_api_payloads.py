"""Build the MVC/FastAPI content payloads from a completed agent run (LLM-authored).

Reads the two agent outputs and writes the exact JSON shapes the ASP.NET MVC
controllers expect from FastAPI:

    outputs/report_summary.md    -> outputs/api/report_summary.json  (/report/summary)
    outputs/insight_signals.json -> outputs/api/kpi_insights.json    (/kpi/insights)

The wording is LLM-authored (same provider/creds as the agent, from config.json +
.env); numbers and enums are injected/validated by code, and the result is checked
against strict schemas before writing. Any LLM or validation failure aborts WITHOUT
writing a partial file. Run from the project dir:

    python scripts/build_api_payloads.py
    python scripts/build_api_payloads.py --title "Retail Branch Performance - AI Summary"
    python scripts/build_api_payloads.py --config config/config.json --out-dir outputs/api
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from src.tools import file_io  # noqa: E402
from src.tools.api_payloads import (  # noqa: E402
    generate_kpi_insights_payload,
    generate_report_summary_payload,
)


def _build_state(config_path: Path) -> dict:
    """Minimal state for the LLM factory + business-rules injection (no PBI needed)."""
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    return {
        "ai_provider": os.environ.get("LLM_PROVIDER") or cfg.get("ai_provider", "azure_openai"),
        "model": cfg.get("model", "claude-sonnet-5"),
        "max_tokens": cfg.get("max_tokens", 4096),
        "config": cfg,
        "business_rules": file_io.read_business_rules(str(config_path)),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build LLM-authored FastAPI content payloads.")
    ap.add_argument("--config", default=str(PROJECT_ROOT / "config" / "config.json"))
    ap.add_argument("--outputs-dir", default="outputs", help="folder holding the agent run outputs")
    ap.add_argument("--out-dir", default=None, help="where to write payloads (default: <outputs-dir>/api)")
    ap.add_argument("--title", default="AI Summary", help="title for the report-summary payload")
    ap.add_argument("--max-metrics", type=int, default=8, help="max Key Metrics as stat tiles")
    args = ap.parse_args()

    outputs = PROJECT_ROOT / args.outputs_dir if not Path(args.outputs_dir).is_absolute() else Path(args.outputs_dir)
    out_dir = Path(args.out_dir) if args.out_dir else outputs / "api"

    summary_md = outputs / "report_summary.md"
    signals_json = outputs / "insight_signals.json"
    for p in (summary_md, signals_json):
        if not p.exists():
            print(f"! missing {p} -- run the agent first")
            return 1

    state = _build_state(Path(args.config))

    try:
        print(f"Generating (provider={state['ai_provider']}, model={state['model']})...")
        report_payload, dropped = generate_report_summary_payload(
            summary_md.read_text(encoding="utf-8"), state, title=args.title, max_metrics=args.max_metrics
        )
        kpi_payload = generate_kpi_insights_payload(
            json.loads(signals_json.read_text(encoding="utf-8")), state
        )
    except Exception as e:  # noqa: BLE001 - strict: never write a partial/invalid file
        print(f"! generation failed, nothing written: {e}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    report_out = out_dir / "report_summary.json"
    kpi_out = out_dir / "kpi_insights.json"
    report_out.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    kpi_out.write_text(json.dumps(kpi_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"report_summary -> {report_out}")
    print(f"    headline : {report_payload['headline'][:88]}")
    print(f"    metrics  : {len(report_payload['metrics'])}")
    print(f"    sections : {len(report_payload['sections'])} "
          f"({', '.join(s['heading'] for s in report_payload['sections'])})")
    if dropped:
        print(f"    guard    : dropped {dropped} bullet(s) with figures not verbatim in source")
    sev: dict = {}
    for c in kpi_payload:
        sev[c["severity"]] = sev.get(c["severity"], 0) + 1
    print(f"kpi_insights   -> {kpi_out}")
    print(f"    cards    : {len(kpi_payload)}  severities: {sev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
