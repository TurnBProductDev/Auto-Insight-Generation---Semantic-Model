"""The executive brief job: read what the reports published, write the brief.

    python -m src.brief.run --config config/sbmart-brief/config.json            # local, no upload
    python -m src.brief.run --config config/sbmart-brief/config.json --publish  # upload

In a container: ``AGENT_RUNNER=executive_brief`` (``container_entrypoint``),
which adds ``--publish``. Schedule it after the client's last report job: it
reads their published output and nothing else, so it has no Power BI query.

Off (``ai_content_executive_brief`` false, the default) it reads and writes
nothing. Uploading also needs ``ai_content_publish_enabled``, like every other
app-facing write.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(cfg: dict, *, publish: bool = False, service_client=None, now: datetime | None = None,
        out_dir: Path | None = None, llm=None, log=print) -> dict:
    """One brief, start to finish. Returns a visible receipt; never half-writes."""
    from . import author, facts, select
    from . import publish as brief_publish

    if not cfg.get("ai_content_executive_brief", False):
        return {"status": "skipped", "reason": "ai_content_executive_brief_disabled"}
    try:
        account = str(cfg.get("azure_blob_account") or "").strip()
        client = str(cfg.get("ai_content_client") or "").strip().lower()
        if not account or not client:
            return {"status": "failed", "reason": "azure_blob_account_or_ai_content_client_missing"}
        reports = facts.configured_reports(cfg)
        if not reports:
            return {"status": "failed", "reason": "brief_reports_missing"}

        now = now or datetime.now(timezone.utc)
        from ..tools.azure_blob import _service_client

        svc, auth = ((service_client, "provided") if service_client is not None
                     else _service_client(account))
        container = svc.get_container_client(client)
        log(f"Executive brief for {client}: reading {len(reports)} report(s)")
        facts.gather(container, reports, log=log)
        selected = select.rank_reports(reports, int(cfg.get("brief_max_lines", 5)))
        if not selected:
            return {"status": "skipped", "reason": "no_report_summaries", "auth": auth}

        authored = author.author(selected, cfg, out_dir=str(out_dir) if out_dir else None,
                                 llm=llm, log=log)
        brief = brief_publish.payload(selected, authored, generated_at=now)
        if out_dir is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "brief.json").write_text(
                json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")

        receipt = {
            "status": "ok", "auth": auth, "client": client,
            "lines": [{"report": r.slug, "mode": authored["lines"][r.slug]["mode"]} for r in selected],
            "questions": len(brief.get("suggestedQuestions") or []),
            "dataAsOf": brief.get("dataAsOf"), "published": False,
        }
        if publish and cfg.get("ai_content_publish_enabled", False):
            from azure.storage.blob import ContentSettings

            expires = now + timedelta(hours=max(1.0, float(cfg.get("ai_content_ttl_hours", 24))))
            receipt["publish"] = brief_publish.publish(
                container, client=client, dataset_id=str(cfg.get("dataset_id") or ""), brief=brief,
                now=now, expires=expires, json_settings=ContentSettings(content_type="application/json"))
            receipt["published"] = True
        elif publish:
            receipt["publish"] = {"status": "skipped", "reason": "ai_content_publish_disabled"}
        return receipt
    except Exception as exc:  # noqa: BLE001 - visible receipt; the exit code carries the failure
        return {"status": "failed", "reason": type(exc).__name__, "error": str(exc)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default="config/sbmart-brief/config.json")
    parser.add_argument("--publish", action="store_true", help="upload to the client's container")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    out = ROOT / os.environ.get("AGENT_OUTPUT_FOLDER", cfg.get("output_folder", "outputs_brief"))

    receipt = run(cfg, publish=args.publish, out_dir=out)
    print(json.dumps(receipt, indent=2, default=str)[:2000])
    return 0 if receipt.get("status") in ("ok", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
