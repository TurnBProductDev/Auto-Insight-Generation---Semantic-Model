"""Publish an already-written summary so the app displays it. No pipeline.

For the case where the analysis exists as a file and only needs to reach the
app. It validates against the shared contract, wraps the envelope, and uploads
to the one path the app reads.

**Validation is the point.** `ReportSummaryPayload` is `extra="forbid"` with
exactly five fields, and the app discards a wrong-shaped file **silently** - no
error, no log line, the report simply never appears. That has shipped twice
(Target Tracker, then Inventory Management). So this refuses to upload anything
the contract would reject, and prints what to fix.

    # look before you leap - validates, shows the paths, uploads nothing
    python scripts/publish_summary_file.py --report <pbReportId> \\
        --json my_summary.json --dry-run

    # ...then for real
    python scripts/publish_summary_file.py --report <pbReportId> \\
        --json my_summary.json --html my_summary.html --client sb-mart

The `--report` id is `Report.pbReportId` from the config DB, which is also the
Power BI report id. For SB Mart every report is already registered, so no
database change is needed to display a summary against one of them.

The input JSON may be either the bare payload (title/generatedAt/headline/
metrics/sections) or an already-wrapped envelope; the envelope is rebuilt
either way so `client`, `expiresAt` and `sourceDatasets` are right for the
container being written to.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FOLDER = "ai-content/report-summaries/client"
SCHEMA_VERSION = 1


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_payload(path: Path) -> dict:
    """Accept a bare payload or a full envelope, return the payload."""
    blob = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(blob, dict):
        raise SystemExit(f"{path}: expected a JSON object")
    if "payload" in blob and isinstance(blob["payload"], dict):
        return blob["payload"]
    return blob


def validate(payload: dict) -> list[str]:
    """Every reason the app would reject this, in the reader's words."""
    from src.tools.api_payloads import ReportSummaryPayload

    problems: list[str] = []
    try:
        ReportSummaryPayload(**payload)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        try:
            for err in exc.errors():                      # pydantic ValidationError
                where = ".".join(str(x) for x in err.get("loc", ())) or "(payload)"
                problems.append(f"{where}: {err.get('msg', '')}")
        except AttributeError:
            problems.append(str(exc))
    # The contract permits an empty list; the app renders a blank card from it,
    # which looks like a broken report rather than an empty one.
    if not payload.get("headline", "").strip():
        problems.append("headline is empty - the app keys on it and will show nothing")
    if not payload.get("sections"):
        problems.append("sections is empty - there is nothing for the app to render")
    for i, section in enumerate(payload.get("sections") or []):
        if not (section.get("points") or []):
            problems.append(f"sections[{i}] ({section.get('heading','?')}) has no points")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, help="pbReportId (the Power BI report GUID)")
    ap.add_argument("--json", required=True, type=Path, help="the summary payload or envelope")
    ap.add_argument("--html", type=Path, help="the rendered page (optional but recommended)")
    ap.add_argument("--client", default="sb-mart", help="blob container (default sb-mart)")
    ap.add_argument("--dataset", default="", help="source dataset id, for provenance")
    ap.add_argument("--as-at", default=None,
                    help="business date for the history copy, e.g. 2026-08-27")
    ap.add_argument("--ttl-hours", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true", help="validate and show paths only")
    args = ap.parse_args()

    payload = load_payload(args.json)
    # Stamped before validating, not after: this tool owns the field, so a file
    # without it is complete as far as its author is concerned.
    payload.setdefault("generatedAt", _iso(datetime.now(timezone.utc)))
    problems = validate(payload)

    print("=" * 78)
    print(f"Report   {args.report}")
    print(f"Client   {args.client}")
    print(f"Title    {payload.get('title', '(none)')}")
    print(f"Headline {str(payload.get('headline',''))[:70]}")
    print(f"Metrics  {len(payload.get('metrics') or [])}   "
          f"Sections {len(payload.get('sections') or [])}")
    print("=" * 78)
    if problems:
        print("REFUSED - the app would discard this file silently:")
        for p in problems:
            print(f"  - {p}")
        print()
        print("The contract is exactly five fields: title, generatedAt, headline,")
        print("metrics[{label,value,tone}], sections[{heading,tone,points[]}].")
        print("`tone` is one of: critical, warning, positive, info, teal.")
        return 1
    print("Contract OK.")

    now = datetime.now(timezone.utc)
    envelope = {
        "schemaVersion": SCHEMA_VERSION,
        "client": args.client,
        "generatedFor": "client",
        "generatedAt": _iso(now),
        "expiresAt": _iso(now + timedelta(hours=args.ttl_hours)),
        "sourceDatasets": [args.dataset] if args.dataset else [],
        "payload": payload,
    }

    targets = [f"{FOLDER}/{args.report}.json"]
    if args.html:
        targets.append(f"{FOLDER}/{args.report}.html")
    if args.as_at:
        targets.append(f"{FOLDER}/{args.report}/{args.as_at}.json")
        targets.append(f"{FOLDER}/{args.report}/index.json")
    print()
    print("Would write:" if args.dry_run else "Writing:")
    for t in targets:
        print(f"  {args.client}/{t}")
    if args.dry_run:
        print("\n--dry-run: nothing uploaded.")
        return 0

    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    import os
    from azure.storage.blob import BlobServiceClient, ContentSettings

    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if not conn:
        raise SystemExit("AZURE_STORAGE_CONNECTION_STRING is not set")
    cc = BlobServiceClient.from_connection_string(conn).get_container_client(args.client)
    json_ct = ContentSettings(content_type="application/json")
    html_ct = ContentSettings(content_type="text/html; charset=utf-8")
    meta = {"schemaversion": str(SCHEMA_VERSION), "client": args.client,
            "generatedfor": "client", "generatedat": _iso(now),
            "expiresat": _iso(now + timedelta(hours=args.ttl_hours)),
            "sourcedatasets": args.dataset, "reportid": args.report}

    body = json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8")
    cc.get_blob_client(f"{FOLDER}/{args.report}.json").upload_blob(
        body, overwrite=True, content_settings=json_ct)
    print(f"  ok  {args.report}.json  ({len(body):,} bytes)")

    if args.html:
        html = args.html.read_bytes()
        cc.get_blob_client(f"{FOLDER}/{args.report}.html").upload_blob(
            html, overwrite=True, content_settings=html_ct, metadata=meta)
        print(f"  ok  {args.report}.html  ({len(html):,} bytes)")

    if args.as_at:
        dated = {"schemaVersion": SCHEMA_VERSION, "client": args.client,
                 "generatedFor": "client", "generatedAt": _iso(now),
                 "sourceRunId": f"{args.report}-{args.as_at}", "payload": payload}
        cc.get_blob_client(f"{FOLDER}/{args.report}/{args.as_at}.json").upload_blob(
            json.dumps(dated, indent=2, ensure_ascii=False).encode("utf-8"),
            overwrite=True, content_settings=json_ct)
        entry = {"reportId": args.report, "asAt": args.as_at,
                 "dataAsOf": args.as_at, "grain": "day",
                 "generatedAt": _iso(now), "headline": payload.get("headline", "")}
        index_client = cc.get_blob_client(f"{FOLDER}/{args.report}/index.json")
        try:
            existing = json.loads(index_client.download_blob().readall())
            if not isinstance(existing, list):
                existing = []
        except Exception:  # noqa: BLE001 - a missing index is the first publish
            existing = []
        merged = [e for e in existing if e.get("asAt") != args.as_at] + [entry]
        merged.sort(key=lambda e: str(e.get("asAt")), reverse=True)
        index_client.upload_blob(
            json.dumps(merged[:30], indent=2, ensure_ascii=False).encode("utf-8"),
            overwrite=True, content_settings=json_ct)
        print(f"  ok  {args.report}/{args.as_at}.json and index.json "
              f"({len(merged)} entries)")

    print("\nDone. The app reads these blobs directly - no service restart needed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
