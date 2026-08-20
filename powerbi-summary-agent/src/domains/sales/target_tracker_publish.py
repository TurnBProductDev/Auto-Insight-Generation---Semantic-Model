"""Publish the Target Tracker report to Azure Blob.

Two destinations, matching what the existing reports do:

* the agent's own store (`azure_blob_*`, container `insightgen`) for the artifacts, under
  `azure_blob_prefix`. **That prefix is load-bearing**: the Sales YoY config uses an empty
  prefix in the same container, so without a distinct one Target Tracker would overwrite
  its `api/*.json`.
* the app's store (`ai_content_*`, a container per client) at
  `ai-content/report-summaries/client/{report_id}.{json,html}` - the pair the web app
  actually reads. Keyed by report id, so sharing the `cityflower` container with the Sales
  YoY report is correct and cannot collide.

The JSON payload deliberately reuses the shape the app already deserialises for a report
summary, so no application change is needed to display this report.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

SCHEMA_VERSION = 1


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _guid(value) -> str | None:
    try:
        return str(UUID(str(value).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def summary_payload(model: dict, *, currency: str = "SAR", title: str = "Target Tracker") -> dict:
    """The app-facing summary object. Same field names the report-summary contract uses."""
    from .target_tracker_html import _R, headline, money, pc

    r = _R(currency)
    p = model["periods"]
    points = []
    for key in ("day", "wtd", "mtd", "ytd"):
        q = p[key]
        points.append({
            "label": q["name"],
            "text": (f"{q['name']} ({q['elapsed']}): {currency} {money(q['actual'])} against a "
                     f"target of {currency} {money(q['target'])} — {pc(q['attainment'])} of target, "
                     f"{currency} {money(abs(q['variance']))} "
                     f"{'above' if q['variance'] >= 0 else 'below'} target."),
            "value": round(q["actual"], 2),
            "target": round(q["target"], 2),
            "attainmentPct": round(q["attainment"], 2) if q["attainment"] is not None else None,
            "variance": round(q["variance"], 2),
            "status": q["status"],
        })
    behind = [b["name"] for b in model["branches"] if b["mtd"]["band"] == "crit"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "reportId": model["report_id"],
        "title": title,
        "heading": headline(r, model),
        "dataAsOf": model["anchor"],
        "soldThrough": model["sold_through"],
        "currency": currency,
        "grain": "day",
        "summaryType": "target_vs_actual",
        "points": points,
        "branchesBelowTarget": behind,
        "generatedAt": _iso(datetime.now(timezone.utc)),
    }


def publish(cfg: dict, out_dir: Path, model: dict, *, cards: list | None = None,
            service_client=None,
            generated_at: datetime | None = None) -> dict:
    account = str(cfg.get("azure_blob_account") or "").strip()
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    currency = cfg.get("target_tracker_currency", "SAR")
    title = cfg.get("api_summary_title", "Target Tracker")
    html_path = out_dir / "report_target_tracker.html"
    md_path = out_dir / "report_target_tracker.md"
    missing = [str(p) for p in (html_path, md_path) if not p.is_file()]
    if missing:
        return {"status": "failed", "reason": "artifacts_missing", "missing": missing}

    report_ids = [g for g in (_guid(v) for v in (cfg.get("ai_content_report_ids") or [])) if g]
    if not report_ids:
        return {"status": "failed", "reason": "ai_content_report_ids_missing"}

    now = generated_at or datetime.now(timezone.utc)
    expires = now + timedelta(hours=max(1.0, float(cfg.get("ai_content_ttl_hours", 24))))
    payload = summary_payload(model, currency=currency, title=title)
    receipts: dict[str, dict] = {}

    from ...tools.azure_blob import _service_client
    from azure.storage.blob import ContentSettings

    svc, auth = ((service_client, "provided") if service_client is not None
                 else _service_client(account))
    json_ct = ContentSettings(content_type="application/json")
    html_ct = ContentSettings(content_type="text/html; charset=utf-8")
    md_ct = ContentSettings(content_type="text/markdown; charset=utf-8")

    def put(container_name, blob_name, data, settings, metadata=None):
        client = svc.get_container_client(container_name)
        client.get_blob_client(blob_name).upload_blob(
            data=data, overwrite=True, content_settings=settings, metadata=metadata)
        receipts[f"{container_name}/{blob_name}"] = {"status": "ok", "bytes": len(data)}

    # 1. the agent's own store, under the per-report prefix
    store = str(cfg.get("azure_blob_container") or "insightgen")
    prefix = str(cfg.get("azure_blob_prefix") or "").strip("/")
    base = f"{prefix}/" if prefix else ""
    html_bytes = html_path.read_bytes()
    md_bytes = md_path.read_bytes()
    model_bytes = json.dumps(model, indent=2, default=str).encode("utf-8")
    payload_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
    try:
        put(store, f"{base}api/report_summary.json", payload_bytes, json_ct)
        put(store, f"{base}report_target_tracker.html", html_bytes, html_ct)
        put(store, f"{base}report_target_tracker.md", md_bytes, md_ct)
        put(store, f"{base}report_target_tracker.json", model_bytes, json_ct)
        put(store, f"{base}history/{model['anchor']}/report_target_tracker.json", model_bytes, json_ct)
    except Exception as exc:  # noqa: BLE001 - visible receipt, caller owns policy
        return {"status": "failed", "reason": type(exc).__name__, "error": str(exc),
                "receipts": receipts}

    # 2. the app's store - the pair the web app reads, keyed by report id
    client_container = str(cfg.get("ai_content_client") or "").strip().lower()
    app_status = "skipped"
    feed_status = "skipped"
    cards = list(cards or [])
    if cfg.get("ai_content_publish_enabled", False) and client_container:
        envelope = {
            "schemaVersion": SCHEMA_VERSION,
            "client": client_container,
            "generatedFor": "client",
            "generatedAt": _iso(now),
            "expiresAt": _iso(expires),
            "sourceDatasets": [str(cfg.get("dataset_id") or "")],
            "payload": payload,
        }
        meta = {"schemaversion": str(SCHEMA_VERSION), "client": client_container,
                "generatedfor": "client", "generatedat": _iso(now), "expiresat": _iso(expires),
                "sourcedatasets": str(cfg.get("dataset_id") or "")}
        try:
            for report_id in report_ids:
                put(client_container, f"ai-content/report-summaries/client/{report_id}.json",
                    json.dumps(envelope, indent=2, ensure_ascii=False).encode("utf-8"), json_ct)
                put(client_container, f"ai-content/report-summaries/client/{report_id}.html",
                    html_bytes, html_ct, {**meta, "reportid": report_id})
                put(client_container, f"ai-content/report-summaries/client/{report_id}.md",
                    md_bytes, md_ct, {**meta, "reportid": report_id})
            app_status = "ok"
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "reason": type(exc).__name__, "error": str(exc),
                    "appStatus": "failed", "receipts": receipts}

        # 3. the shared KPI feed. Only when the client has been migrated: the
        # cards carry `reportId`, which the app must tolerate first
        # (docs/phase5-app-contract-change.md). Off, this report contributes no
        # cards and the Sales YoY feed is untouched.
        if cfg.get("ai_content_multi_report_feed", False) and cards:
            from ...tools import ai_content_publisher as feed

            try:
                feed.publish_kpi_feed(
                    svc.get_container_client(client_container),
                    client=client_container,
                    dataset_id=str(cfg.get("dataset_id") or ""),
                    cards=cards,
                    report_id=str(cfg.get("report_id") or "target_tracker"),
                    cfg=cfg,
                    now=now,
                    expires=expires,
                    json_settings=json_ct,
                    receipts=receipts,
                )
                feed_status = "ok"
            except Exception as exc:  # noqa: BLE001 - the feed must never cost the report
                feed_status = f"failed: {type(exc).__name__}: {exc}"

    return {
        "status": "ok",
        "auth": auth,
        "account": account,
        "store": f"{store}/{base}" if base else store,
        "appContainer": client_container,
        "appStatus": app_status,
        "kpiFeedStatus": feed_status,
        "kpiCards": len(cards),
        "reportIds": report_ids,
        "generatedAt": _iso(now),
        "expiresAt": _iso(expires),
        "blobs": sorted(receipts),
        "receipts": receipts,
    }
