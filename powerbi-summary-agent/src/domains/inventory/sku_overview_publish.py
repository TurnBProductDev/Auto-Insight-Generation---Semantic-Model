"""Publish the SKU Overview report to blob storage.

Same three-destination shape as `ageing_publish.py` and `stock_health_publish.py`
- the agent's own store, the app's store, and the shared KPI feed. See those
modules for why the three are kept separate; this is a near-identical copy
adapted to the SKU Overview model's own fields, following this repo's
established convention of one small publish module per report rather than a
shared base class.
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


def summary_payload(model: dict, *, title: str = "SKU Overview",
                    generated_at: datetime | None = None) -> dict:
    """The app-facing summary, in the shared report-summary contract."""
    from ...tools.api_payloads import ReportSummaryPayload

    header = model.get("header") or {}
    currency = str(model.get("currency") or "")

    def fmt(value):
        number = float(value or 0.0)
        prefix = f"{currency} " if currency else ""
        if abs(number) >= 1_000_000:
            return f"{prefix}{number / 1_000_000:.2f}M"
        if abs(number) >= 1_000:
            return f"{prefix}{number / 1_000:.0f}K"
        return f"{prefix}{number:,.0f}"

    metrics = [{"label": "Stock Value", "value": fmt(header.get("total_stock_value")), "tone": "info"}]
    share = header.get("excess_share_pct")
    metrics.append({
        "label": "Excess Stock",
        "value": fmt(header.get("total_excess_value"))
                + (f" ({float(share):.1f}% of stock)" if isinstance(share, (int, float)) else ""),
        "tone": "warning",
    })
    metrics.append({"label": "Opportunity Loss", "value": fmt(header.get("total_opp_loss")),
                    "tone": "critical"})
    metrics.append({"label": "Loc-SKU rows", "value": f"{int(header.get('rows') or 0):,}",
                    "tone": "info"})

    urgent = next((s for s in model.get("states") or []
                  if s.get("action") == "STOCK OUT - PLACE ORDER"), None)
    attention_points = []
    if urgent and urgent.get("rows"):
        attention_points.append(
            f"{int(urgent['rows']):,} Loc-SKUs are in STOCK OUT - PLACE ORDER: "
            f"{fmt(urgent.get('stock_value'))} of stock value, zero units with "
            f"nothing on order.")
    for signal in (model.get("stat_signals") or [])[:5]:
        if signal.get("analysis_type") == "sku_overview_urgent_state":
            continue
        attention_points.append(str(signal.get("description") or ""))
    if not attention_points:
        attention_points = ["No SKU Overview finding is flagged as high-priority."]

    coverage_points = [
        f"Figures state the stock position {model.get('period_label') or 'as at the latest load'}."
    ]
    coverage_points.extend(str(c) for c in (model.get("caveats") or []))
    if currency:
        coverage_points.append(f"All figures are in {currency}.")
    coverage_points = list(dict.fromkeys(p for p in coverage_points if p))

    headline = attention_points[0] if attention_points else (
        f"{fmt(header.get('total_stock_value'))} of stock is held "
        f"{model.get('period_label') or 'at the latest load'}.")

    payload = {
        "title": title,
        "generatedAt": _iso(generated_at or datetime.now(timezone.utc)),
        "headline": headline,
        "metrics": metrics,
        "sections": [
            {"heading": "What needs attention first", "tone": "critical",
             "points": attention_points},
            {"heading": "What these figures cover", "tone": "info",
             "points": coverage_points},
        ],
    }
    return ReportSummaryPayload(**payload).model_dump(exclude_none=True)


def history_entry(model: dict, payload: dict, report_id: str, generated_at: datetime) -> dict:
    header = model.get("header") or {}
    return {
        "reportId": report_id,
        "asAt": model.get("as_at"),
        # The app reads `dataAsOf` off the index row to say how current a
        # summary is; `asAt` is this report's own key for the same date and
        # nothing downstream reads it. Publishing only asAt meant Home had no
        # data date for this report at all - and with Target Tracker the only
        # publisher emitting dataAsOf, its anchor ended up labelling the whole
        # page ("data to 31 Jul" beside content a month newer).
        "dataAsOf": model.get("as_at"),
        "grain": "day",
        "generatedAt": _iso(generated_at),
        "headline": payload.get("headline") or "",
        "stockValue": header.get("total_stock_value"),
        "excessValue": header.get("total_excess_value"),
        "opportunityLoss": header.get("total_opp_loss"),
    }


def merge_index(existing: list, entry: dict, *, keep: int = 30) -> list:
    rows = [row for row in (existing or [])
            if isinstance(row, dict) and row.get("asAt") != entry.get("asAt")]
    rows.append(entry)
    rows.sort(key=lambda row: str(row.get("asAt") or ""), reverse=True)
    return rows[:keep]


def publish(cfg: dict, out_dir: Path, model: dict, *,
            cards: list | None = None, service_client=None,
            generated_at: datetime | None = None) -> dict:
    """Push the report to all three destinations. Returns a visible receipt."""
    account = str(cfg.get("azure_blob_account") or "").strip()
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    title = cfg.get("api_summary_title", "SKU Overview")
    html_path = out_dir / "report_sku_overview.html"
    if not html_path.is_file():
        return {"status": "failed", "reason": "artifacts_missing", "missing": [str(html_path)]}

    report_ids = [g for g in (_guid(v) for v in (cfg.get("ai_content_report_ids") or [])) if g]
    if not report_ids:
        return {"status": "failed", "reason": "ai_content_report_ids_missing"}

    now = generated_at or datetime.now(timezone.utc)
    expires = now + timedelta(hours=max(1.0, float(cfg.get("ai_content_ttl_hours", 24))))
    payload = summary_payload(model, title=title, generated_at=now)
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
    model_bytes = json.dumps(model, indent=2, default=str).encode("utf-8")
    payload_bytes = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
    as_at = str(model.get("as_at") or "unknown")
    try:
        put(store, f"{base}api/report_summary.json", payload_bytes, json_ct)
        put(store, f"{base}report_sku_overview.html", html_bytes, html_ct)
        put(store, f"{base}report_sku_overview.json", model_bytes, json_ct)
        put(store, f"{base}history/{as_at}/report_sku_overview.json", model_bytes, json_ct)
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
                         "sourceRunId": f"{model.get('report_id')}-{as_at}", "payload": payload}
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
                merged = merge_index(existing, history_entry(model, payload, report_id, now))
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
                    cards=cards, report_id=str(cfg.get("report_id") or "sku_overview"),
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
