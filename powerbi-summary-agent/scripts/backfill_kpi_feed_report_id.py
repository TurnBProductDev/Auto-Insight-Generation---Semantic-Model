"""Stamp reportId onto KPI cards published before the multi-report contract.

Cards written before ``ai_content_multi_report_feed`` was enabled carry no
``reportId``, so the app files them as **Unassigned**. They also carry the old
per-run ``id`` sequence, which repeats across days: a seven-day feed routinely
holds three different cards all called ``1``.

This backfills both, in place, on the published blobs:

* ``reportId`` <- the report that wrote them. Only one report has ever
  published KPI cards into a given client container, so this is a lookup, not a
  guess - but pass ``--report-id`` explicitly and it is checked against what is
  already in the feed.
* ``id`` <- the same stable hash new cards get, so an untagged card stops
  colliding with the one published the day before.

Nothing else on the card is touched, and a card that already carries a
``reportId`` is left exactly as it is.

    python scripts/backfill_kpi_feed_report_id.py --client cityflower --report-id sales_yoy
    python scripts/backfill_kpi_feed_report_id.py --client cityflower --report-id sales_yoy --apply

Dry run by default. Always writes a timestamped backup before applying.
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

FEED_BLOBS = ("ai-content/kpi/client/insights.json", "ai-content/kpi/client/alerts.json")


def _card_key(card: dict) -> str:
    """A stable identity for a card that predates story_key.

    Built from the fields that identify the finding rather than its position in
    a run, so re-running the backfill produces the same id.
    """
    return "|".join(str(card.get(field) or "") for field in
                    ("isoDate", "category", "metric", "comparisonLabel", "value"))


def backfill(cards: list, report_id: str) -> tuple[list, int]:
    from src.tools.api_payloads import stable_card_id

    out, changed = [], 0
    for index, card in enumerate(cards, start=1):
        if not isinstance(card, dict):
            out.append(card)
            continue
        if card.get("reportId"):
            out.append(card)
            continue
        patched = dict(card)
        patched["reportId"] = report_id
        patched["id"] = stable_card_id(report_id, _card_key(card), index)
        out.append(patched)
        changed += 1
    return out, changed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, help="blob container, e.g. cityflower")
    parser.add_argument("--report-id", required=True, help="slug to stamp, e.g. sales_yoy")
    parser.add_argument("--account", default="turnbtestblobstorage")
    parser.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    parser.add_argument("--confirm", action="store_true",
                        help="acknowledge that untagged cards belong to --report-id "
                             "when another report has also published to this feed")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    from src.tools.api_payloads import KpiCard
    from src.tools.azure_blob import _service_client

    svc, auth = _service_client(args.account)
    container = svc.get_container_client(args.client)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = PROJECT_ROOT / "outputs_feed_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    print(f"account={args.account} auth={auth} client={args.client} "
          f"report_id={args.report_id} mode={'APPLY' if args.apply else 'dry run'}\n")

    total_changed = 0
    for blob_name in FEED_BLOBS:
        blob = container.get_blob_client(blob_name)
        try:
            raw = blob.download_blob().readall()
        except Exception as exc:  # noqa: BLE001
            print(f"{blob_name}: cannot read ({type(exc).__name__}) - skipped")
            continue
        envelope = json.loads(raw)
        cards = envelope.get("payload") or []
        short = blob_name.rsplit("/", 1)[-1]

        # Guard: another report has published here, so attribution is a
        # judgement rather than a lookup. It is often still knowable - a report
        # whose cards are all already tagged cannot be the source of an
        # untagged one - but the operator has to say so, because getting it
        # wrong files one report's findings under another's name.
        others = {c.get("reportId") for c in cards
                  if isinstance(c, dict) and c.get("reportId")} - {args.report_id}
        untagged = [c for c in cards if isinstance(c, dict) and not c.get("reportId")]
        if others and untagged and not args.confirm:
            print(f"{short}: {len(untagged)} untagged card(s), and the feed already contains "
                  f"{sorted(others)}.")
            print(f"   Those reports' cards are already tagged, so an untagged card is most "
                  f"likely {args.report_id} - but confirm it rather than assume.")
            print("   Re-run with --confirm once you are sure.")
            return 2

        patched, changed = backfill(cards, args.report_id)
        total_changed += changed
        ids = [c.get("id") for c in patched if isinstance(c, dict)]
        dupes = {i for i in ids if ids.count(i) > 1}
        print(f"{short}: {len(cards)} card(s), {changed} to stamp, "
              f"duplicate ids after: {dupes or 'none'}")
        for card in patched:
            if isinstance(card, dict):
                KpiCard(**card)  # strict: refuse to write anything off-contract

        if not changed:
            continue
        if not args.apply:
            continue

        (backup_dir / f"{short.replace('.json','')}.{stamp}.pre-backfill.json").write_bytes(raw)
        envelope["payload"] = patched
        blob.upload_blob(
            data=json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8"),
            overwrite=True,
        )
        print(f"   written; backup saved as {short.replace('.json','')}.{stamp}.pre-backfill.json")

    print(f"\n{total_changed} card(s) {'stamped' if args.apply else 'would be stamped'}.")
    if not args.apply and total_changed:
        print("Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
