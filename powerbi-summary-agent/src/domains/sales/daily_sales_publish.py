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

    whole = page.get("whole") or {}
    currency = str(page.get("currency") or "")

    metrics = [
        {"label": "Net Sales", "value": whole.get("net_sales", {}).get("value", "—"), "tone": "info"},
        {"label": "Bills", "value": whole.get("bills", {}).get("value", "—"),
         "tone": {"crit": "critical", "good": "positive"}.get(
             whole.get("bills", {}).get("verdict", {}).get("key"), "info")},
        {"label": "Basket Value", "value": whole.get("basket_value", {}).get("value", "—"), "tone": "info"},
        {"label": "Margin", "value": whole.get("margin", {}).get("value", "—"),
         "tone": {"crit": "critical", "good": "positive"}.get(
             whole.get("margin", {}).get("key"), "info")},
    ]

    attention_points = []
    for grain_key, label in (("departments", "department"), ("sections", "section")):
        for row in (page.get(grain_key) or {}).get("outside", [])[:3]:
            word = row["bills"]["verdict"]["word"] if row["bills"]["verdict"]["key"] == "crit" else \
                row["margin"]["verdict"]["word"]
            attention_points.append(
                f"{row['name']} ({label}): Bills {row['bills']['value']} against "
                f"{row['bills']['band'] or 'its band'} - {row['bills']['verdict']['word']}.")
    if not attention_points:
        attention_points = ["No department or section fell outside its Bills or Margin band today."]

    coverage_points = [str(c) for c in (page.get("caveats") or [])]
    if currency:
        coverage_points.append(f"All figures are in {currency}.")

    headline = page.get("hero", {}).get("headline") or "Daily Sales figures are available."

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
    return ReportSummaryPayload(**payload).model_dump()


def history_entry(page: dict, payload: dict, report_id: str, generated_at: datetime) -> dict:
    whole = page.get("whole") or {}
    return {
        "reportId": report_id,
        "asAt": page.get("as_at"),
        "generatedAt": _iso(generated_at),
        "headline": payload.get("headline") or "",
        "billsVerdict": whole.get("bills", {}).get("verdict", {}).get("word"),
        "marginVerdict": whole.get("margin", {}).get("verdict", {}).get("word"),
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
