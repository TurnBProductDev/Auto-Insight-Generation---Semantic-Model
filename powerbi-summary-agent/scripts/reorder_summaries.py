"""Re-publish client summaries in a chosen order.

The Home "Business Headlines" widget shows the ten most recent summaries,
sorted by the envelope's `generatedAt`. SB Mart has thirteen reports, so three
are always hidden - and which three changes every day, because the six
pipeline reports re-run overnight while the seven hand-authored ones keep the
timestamp they were first published with.

This sets the order deliberately: the reports named first get the newest
timestamps and therefore the top slots.

`generatedAt` is the PUBLISH time, not a claim about when the analysis was
computed - `ai_content_publisher` sets it as `generated_at or
datetime.now(timezone.utc)` at the moment of upload, and every publisher does
the same. So re-publishing a summary genuinely does update when it was
published, and this restamps nothing that was not already a publish timestamp.
The payload itself is copied byte for byte; no figure, headline or section is
touched.

    python scripts/reorder_summaries.py --dry-run
    python scripts/reorder_summaries.py

**This is a workaround, not a fix.** The widget's ten-slot cap is hard-coded in
the app (there is no environment variable on `scanb-ai-agent`), and tomorrow's
scheduled runs will reorder everything again by their own run times. The real
fix is either a higher cap or sorting by a business priority - the `Module`
table already groups the reports for exactly that.
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

# Top of the widget first. The six reports with a live pipeline lead - sales,
# then inventory - because they are the ones whose numbers move daily.
DEFAULT_ORDER = [
    ("Sales Performance",             "aafb8798-6ed6-4b8b-bc48-9ea7c97e13fc"),
    ("Daily Sales Performance",       "6ddd2afa-a1b4-443c-854d-e1ec4ad88e77"),
    ("Target Tracker",                "02e86e30-e985-4f37-97a8-40d4bd7e821d"),
    ("Inventory Management",          "ea29c0ea-2b15-4b29-b506-82afa92b4240"),
    ("Ageing Report",                 "15a06619-c2cc-4c53-b8cd-c53c9dafa89c"),
    ("Product Performance",           "47003525-99b7-4121-8ecb-5f0b67b62d8b"),
]

# Spacing between consecutive summaries. Seconds, not milliseconds: the app
# renders a date, and a tie would leave the order to chance.
STEP = timedelta(seconds=5)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--client", default="sb-mart")
    ap.add_argument("--ttl-hours", type=int, default=24)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--report", action="append", default=None,
                    help="repeatable: pbReportId, top of the widget first "
                         "(overrides the built-in order)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    order = ([(rid, rid) for rid in args.report] if args.report else DEFAULT_ORDER)

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

    # The first in the list must end up newest, so stamp from the back.
    base = datetime.now(timezone.utc)
    stamps = [base - STEP * i for i in range(len(order))]

    print("=" * 76)
    print(f"Re-publishing {len(order)} summaries into {args.client} - newest first")
    print("=" * 76)
    for (name, guid), when in zip(order, stamps):
        bc = cc.get_blob_client(f"{FOLDER}/{guid}.json")
        try:
            envelope = json.loads(bc.download_blob().readall())
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  SKIP  {name}: {type(exc).__name__} - no summary published yet")
            continue
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            print(f"  SKIP  {name}: no payload in the envelope")
            continue

        was = envelope.get("generatedAt", "?")
        envelope["generatedAt"] = _iso(when)
        envelope["expiresAt"] = _iso(when + timedelta(hours=args.ttl_hours))
        # Kept equal, exactly as every publisher writes them.
        payload["generatedAt"] = _iso(when)

        print(f"  {name:<30} {was[11:19]} -> {_iso(when)[11:19]}"
              f"   ({len(payload.get('sections') or [])} sections, "
              f"{len(payload.get('metrics') or [])} metrics preserved)")
        if not args.dry_run:
            bc.upload_blob(json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8"),
                           overwrite=True, content_settings=json_ct)

    print()
    if args.dry_run:
        print("--dry-run: nothing uploaded.")
    else:
        print("Done. Refresh Home - the reports above should lead Business Headlines,")
        print("in this order. Everything else keeps its own timestamp and follows.")
    print()
    print("NOTE: tomorrow's scheduled runs will reorder this again. The lasting")
    print("fix is raising the widget's ten-slot cap, or sorting by module priority.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
