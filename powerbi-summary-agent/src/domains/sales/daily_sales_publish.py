"""Publish the Daily Sales report to blob storage.

Same three-destination shape as `sku_overview_publish.py` / `ageing_publish.py`
- the agent's own store, the app's store, and the shared KPI feed.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = 1

_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                   r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _guid(value) -> str | None:
    text = str(value or "").strip()
    return text if _GUID.match(text) else None


def summary_payload(page: dict, *, title: str = "Daily Sales",
                    generated_at: datetime | None = None) -> dict:
    """The app-facing summary, in the shared report-summary contract."""
    from ...tools.api_payloads import ReportSummaryPayload

    currency = str(page.get("currency") or "")

    # The KPI row the page already built: same four measures, same wording, so
    # the app card and the page can never quote different figures for the same
    # day. Reading the raw bundles here would mean a second formatter.
    metrics = [_metric(entry, page) for entry in (page.get("kpis") or [])]
    if not metrics:
        metrics = [{"label": "Net Sales", "value": "—", "tone": "info"}]

    attention_points = []
    for grain_key, label in (("departments", "department"), ("sections", "section")):
        grain = page.get(grain_key) or {}
        for side, word in (("below", "below its normal band"), ("above", "above its normal band")):
            for row in (grain.get(side) or [])[:3]:
                attention_points.append(
                    f"{row['name']} ({label}): {row['note']} - {row['value']} {word}.")
    if not attention_points:
        attention_points = ["No department or section finished outside its Net Sales band today."]

    coverage_points = [f"{item['lead']}{item['body']}".strip()
                       for item in (page.get("caveats") or [])
                       if isinstance(item, dict)]
    if currency:
        coverage_points.append(f"All figures are in {currency}.")

    headline = (page.get("hero") or {}).get("headline") or "Daily Sales figures are available."

    payload = {
        "title": title,
        "generatedAt": _iso(generated_at or datetime.now(timezone.utc)),
        "headline": headline,
        "metrics": metrics,
        "sections": [
            {"heading": "What needs attention first", "tone": "critical",
             "points": attention_points[:5]},
            {"heading": "What these figures cover", "tone": "info",
             "points": coverage_points},
        ],
    }
    return ReportSummaryPayload(**payload).model_dump(exclude_none=True)


def _metric(entry: dict, page: dict) -> dict:
    """One published KPI: the figure, and what it should be read against.

    This used to keep only label/value/tone, which is enough to print "USD
    55.3K" and nothing else. The page had already worked out that the figure
    was 17.7K under its benchmark, that the verdict was Underperforming, and
    where it sat inside its band - and all three were dropped at the door, so
    every consumer downstream showed a number with no way to judge it.

    The band travels as four numbers rather than as this page's own bullet
    geometry: that geometry is computed for a 214px chart in this report's HTML
    and means nothing to a consumer rendering at another width.
    """
    metric = {
        "label": entry["label"],
        "value": entry["value"],
        "tone": {"crit": "critical", "good": "positive"}.get(entry.get("tone"), "info"),
    }
    if entry.get("note"):
        metric["note"] = entry["note"]
    if entry.get("word"):
        metric["verdict"] = entry["word"]

    # Only where the day actually has a band. A measure with no comparable past
    # days has no floor to be under, and an invented one would be a judgement
    # the data does not support.
    measure = (page.get("whole") or {}).get(entry.get("key") or "") or {}
    actual, p20, p80 = measure.get("actual"), measure.get("p20"), measure.get("p80")
    if entry.get("has_band") and None not in (actual, p20, p80):
        band = {"actual": float(actual), "floor": float(p20), "ceiling": float(p80)}
        if measure.get("p50") is not None:
            band["benchmark"] = float(measure["p50"])
        metric["band"] = band
    return metric


def history_entry(page: dict, payload: dict, report_id: str, generated_at: datetime) -> dict:
    whole = page.get("whole") or {}

    def _word(key: str) -> str | None:
        return ((whole.get(key) or {}).get("verdict") or {}).get("word")

    return {
        "reportId": report_id,
        "asAt": page.get("as_at"),
        # The app reads `dataAsOf` off the index row to say how current a
        # summary is; `asAt` is this report's own key for the same date and
        # nothing downstream reads it. Publishing only asAt meant Home had no
        # data date for this report at all - and with Target Tracker the only
        # publisher emitting dataAsOf, its anchor ended up labelling the whole
        # page ("data to 31 Jul" beside content a month newer).
        "dataAsOf": page.get("as_at"),
        "grain": "day",
        "generatedAt": _iso(generated_at),
        "headline": payload.get("headline") or "",
        "netSalesVerdict": _word("net_sales"),
        "billsVerdict": _word("bills"),
        "marginVerdict": _word("margin"),
    }


def merge_index(existing: list, entry: dict, *, keep: int = 30) -> list:
    rows = [row for row in (existing or [])
            if isinstance(row, dict) and row.get("asAt") != entry.get("asAt")]
    rows.append(entry)
    rows.sort(key=lambda row: str(row.get("asAt") or ""), reverse=True)
    return rows[:keep]


def publish(cfg: dict, out_dir: Path, page: dict, *,
            cards: list | None = None, service_client=None,
            generated_at: datetime | None = None) -> dict:
    """Push the report to all three destinations. Returns a visible receipt."""
    account = str(cfg.get("azure_blob_account") or "").strip()
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    title = cfg.get("api_summary_title", "Daily Sales")
    html_path = out_dir / "report_daily_sales.html"
    if not html_path.is_file():
        return {"status": "failed", "reason": "artifacts_missing", "missing": [str(html_path)]}

    report_ids = [g for g in (_guid(v) for v in (cfg.get("ai_content_report_ids") or [])) if g]
    if not report_ids:
        return {"status": "failed", "reason": "ai_content_report_ids_missing"}

    now = generated_at or datetime.now(timezone.utc)
    expires = now + timedelta(hours=max(1.0, float(cfg.get("ai_content_ttl_hours", 24))))
    payload = summary_payload(page, title=title, generated_at=now)
    receipts: dict[str, dict] = {}

    from azure.storage.blob import ContentSettings

    from ...tools.azure_blob import _service_client

    svc, auth = ((service_client, "provided") if service_client is not None
                 else _service_client(account))
    json_ct = ContentSettings(content_type="application/json")
    html_ct = ContentSettings(content_type="text/html; charset=utf-8")

    def put(container_name, blob_name, data, settings, metadata=None):
        client = svc.get_container_client(container_name)
        client.get_blob_client(blob_name).upload_blob(
            data=data, overwrite=True, content_settings=settings, metadata=metadata)
        receipts[f"{container_name}/{blob_name}"] = {"status": "ok", "bytes": len(data)}

    store = str(cfg.get("azure_blob_container") or "insightgen")
    prefix = str(cfg.get("azure_blob_prefix") or "").strip("/")
    base = f"{prefix}/" if prefix else ""
    html_bytes = html_path.read_bytes()
    page_bytes = json.dumps(page, indent=2, default=str).encode("utf-8")
    payload_bytes = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    as_at = str(page.get("as_at") or "unknown")
    try:
        put(store, f"{base}api/report_summary.json", payload_bytes, json_ct)
        put(store, f"{base}report_daily_sales.html", html_bytes, html_ct)
        put(store, f"{base}report_daily_sales.json", page_bytes, json_ct)
        put(store, f"{base}history/{as_at}/report_daily_sales.json", page_bytes, json_ct)
    except Exception as exc:  # noqa: BLE001 - visible receipt, caller owns policy
        return {"status": "failed", "reason": type(exc).__name__, "error": str(exc),
                "receipts": receipts}

    client_container = str(cfg.get("ai_content_client") or "").strip().lower()
    app_status = "skipped"
    feed_status = "skipped"
    cards = list(cards or [])
    if cfg.get("ai_content_publish_enabled", False) and client_container:
        envelope = {
            "schemaVersion": SCHEMA_VERSION, "client": client_container,
            "generatedFor": "client", "generatedAt": _iso(now), "expiresAt": _iso(expires),
            "sourceDatasets": [str(cfg.get("dataset_id") or "")], "payload": payload,
        }
        meta = {"schemaversion": str(SCHEMA_VERSION), "client": client_container,
                "generatedfor": "client", "generatedat": _iso(now),
                "expiresat": _iso(expires), "sourcedatasets": str(cfg.get("dataset_id") or "")}
        try:
            for report_id in report_ids:
                folder = f"ai-content/report-summaries/client/{report_id}"
                put(client_container, f"{folder}.json",
                    json.dumps(envelope, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
                    json_ct)
                put(client_container, f"{folder}.html", html_bytes, html_ct,
                    {**meta, "reportid": report_id})

                dated = {"schemaVersion": SCHEMA_VERSION, "client": client_container,
                         "generatedFor": "client", "generatedAt": _iso(now),
                         "sourceRunId": f"{page.get('report_id') or 'daily_sales'}-{as_at}",
                         "payload": payload}
                put(client_container, f"{folder}/{as_at}.json",
                    json.dumps(dated, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
                    json_ct)

                index_blob = svc.get_container_client(client_container).get_blob_client(
                    f"{folder}/index.json")
                try:
                    existing = json.loads(index_blob.download_blob().readall())
                    if not isinstance(existing, list):
                        existing = []
                except Exception:  # noqa: BLE001 - a missing index is the first run
                    existing = []
                merged = merge_index(existing, history_entry(page, payload, report_id, now))
                put(client_container, f"{folder}/index.json",
                    json.dumps(merged, indent=2, ensure_ascii=False, default=str).encode("utf-8"),
                    json_ct)
            app_status = "ok"
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "reason": type(exc).__name__, "error": str(exc),
                    "appStatus": "failed", "receipts": receipts}

        if cfg.get("ai_content_multi_report_feed", False) and cards:
            from ...tools import ai_content_publisher as feed

            try:
                feed.publish_kpi_feed(
                    svc.get_container_client(client_container),
                    client=client_container, dataset_id=str(cfg.get("dataset_id") or ""),
                    cards=cards, report_id=str(cfg.get("report_id") or "daily_sales"),
                    cfg=cfg, now=now, expires=expires, json_settings=json_ct, receipts=receipts,
                )
                feed_status = "ok"
            except Exception as exc:  # noqa: BLE001 - never cost the report
                feed_status = f"failed: {type(exc).__name__}: {exc}"

    return {
        "status": "ok", "auth": auth, "account": account,
        "store": f"{store}/{base}" if base else store,
        "appContainer": client_container, "appStatus": app_status, "feedStatus": feed_status,
        "reportIds": report_ids, "asAt": as_at, "receipts": receipts,
    }
