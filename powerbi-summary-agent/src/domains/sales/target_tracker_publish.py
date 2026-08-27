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


def summary_payload(
    model: dict,
    *,
    currency: str = "SAR",
    title: str = "Target Tracker",
    generated_at: datetime | None = None,
) -> dict:
    """Project Target Tracker into the app's strict report-summary contract.
    The standalone report model is intentionally richer and has its own shape.
    The app does not deserialize that model directly: it expects exactly
    ``title``, ``generatedAt``, ``headline``, ``metrics`` and ``sections``.
    Keep this boundary explicit so adding fields to the report cannot silently
    make the app summary disappear.
    """
    from .target_tracker_html import _R, headline, money, pc
    from ...tools.api_payloads import ReportSummaryPayload

    currency = str(currency or "SAR").strip().upper()
    r = _R(currency)
    p = model["periods"]

    def tone(reading: dict) -> str:
        return {
            "good": "positive",
            "warn": "warning",
            "crit": "critical",
            "none": "info",
        }.get(str(reading.get("band") or "none"), "info")

    metrics = []
    performance = []
    for key in ("day", "wtd", "mtd", "ytd"):
        q = p[key]
        metric = {
            "label": q["name"],
            "value": (f"{pc(q['attainment'])} of target"
                      if q.get("attainment") is not None else "No target set"),
            "tone": tone(q),
        }
        # What the attainment is actually made of, so a consumer can show the
        # figure against its target rather than only the percentage. Published
        # for the same reason Daily Sales publishes its band: a percentage with
        # nothing behind it cannot be checked, and "124% of target" reads very
        # differently once you can see it is 1.36M against 1.09M.
        if q.get("target") is not None and q.get("actual") is not None:
            metric["note"] = (
                f"{currency} {money(q['actual'])} against a target of "
                f"{currency} {money(q['target'])}")
            # KpiTarget needs both halves; a target with no attainment is not
            # a meter, so the note carries it and nothing is drawn.
            if q.get("attainment") is not None:
                metric["target"] = {"value": float(q["target"]),
                                    "attainmentPct": round(float(q["attainment"]), 1)}
        if q.get("status"):
            metric["verdict"] = q["status"]
        metrics.append(metric)
        performance.append(
            f"{q['name']} ({q['elapsed']}): {currency} {money(q['actual'])} against a "
            f"target of {currency} {money(q['target'])} — {pc(q['attainment'])} of target, "
            f"{currency} {money(abs(q['variance']))} "
            f"{'above' if q['variance'] >= 0 else 'below'} target."
        )

    behind = sorted(
        (b for b in model.get("branches") or [] if b.get("mtd", {}).get("variance", 0) < 0),
        key=lambda b: b["mtd"]["variance"],
    )
    if behind:
        branch_points = [
            f"{branch['name']}: {pc(branch['mtd']['attainment'])} of target this month, "
            f"{currency} {money(abs(branch['mtd']['variance']))} below target."
            for branch in behind
        ]
        branch_tone = (
            "critical" if any(branch["mtd"].get("band") == "crit" for branch in behind)
            else "warning"
        )
    else:
        branch_points = ["Every branch is at or above target for the month."]
        branch_tone = "positive"

    # Both directions. The else-branch used to claim the two feeds were "both
    # measured through <anchor>", which on a model whose targets are loaded to
    # month end was flatly untrue - the anchor was five days beyond the last
    # recorded sale, and the sentence hid exactly the gap it should have named.
    lag = int(model.get("target_lag_days") or 0)
    sales_lag = int(model.get("sales_lag_days") or 0)
    if lag:
        context = (
            f"Targets are available through {model['anchor']}; sales are available through "
            f"{model['sold_through']}. The further {lag} sales "
            f"{'day is' if lag == 1 else 'days are'} excluded because no target is set."
        )
    elif sales_lag:
        context = (
            f"Sales are recorded through {model['sold_through']}, and this report measures "
            f"to that date. Targets are set a further {sales_lag} "
            f"{'day' if sales_lag == 1 else 'days'} ahead, to "
            f"{model.get('targeted_through')}; those days have not traded yet and are "
            f"excluded, so every percentage is against the target for the days elapsed."
        )
    else:
        context = f"Actual sales and targets are both measured through {model['anchor']}."

    prose = model.get("prose") or {}
    when = generated_at or datetime.now(timezone.utc)
    generated_date = (
        when.astimezone(timezone.utc).date().isoformat()
        if when.tzinfo is not None else when.date().isoformat()
    )
    payload = {
        "title": title,
        "generatedAt": generated_date,
        "headline": str(prose.get("headline") or headline(r, model)).strip(),
        "metrics": metrics,
        "sections": [
            {
                "heading": "Performance against target",
                "tone": tone(p["mtd"]),
                "points": performance,
            },
            {
                "heading": "Branch performance",
                "tone": branch_tone,
                "points": branch_points,
            },
            {
                "heading": "Important context",
                "tone": "info",
                "points": [
                    context,
                    "This model has no prior-year comparison; every figure is actual sales "
                    "against target.",
                    (f"Covers {len(model['population'])} branches: "
                     f"{', '.join(model['population'])}."
                     if model.get("population") else "No branch population was supplied."),
                ],
            },
        ],
    }
    return ReportSummaryPayload(**payload).model_dump(exclude_none=True)


def history_entry(model: dict, payload: dict, report_id: str, generated_at: datetime) -> dict:
    """One row of the report's history index.

    The index is the app's *second* route to a summary: it reads the dated
    archive when the current file is unavailable. Target Tracker published no
    archive at all, so when its current file was rejected there was no fallback
    and the report vanished entirely.

    ``grain`` and ``dataAsOf`` live here rather than in the payload - the
    payload contract has no field for them, the index entry does.
    """
    return {
        "reportId": report_id,
        "date": model["anchor"],
        "label": "Latest",
        "generatedAt": _iso(generated_at),
        "headline": payload["headline"],
        "grain": "day",
        "dataAsOf": model["anchor"],
        "runsThatDay": 1,
    }


def merge_index(existing: list, entry: dict, *, keep: int = 30) -> list:
    """Newest first, one row per date, only the newest labelled 'Latest'.

    A re-run on the same date replaces that date's row and increments its run
    count rather than adding a duplicate.
    """
    rows = [dict(row) for row in (existing or []) if isinstance(row, dict)]
    same_day = next((row for row in rows if row.get("date") == entry["date"]), None)
    if same_day is not None:
        entry = {**entry, "runsThatDay": int(same_day.get("runsThatDay") or 0) + 1}
        rows = [row for row in rows if row.get("date") != entry["date"]]
    rows.append(entry)
    rows.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
    rows = rows[: max(1, int(keep))]
    for index, row in enumerate(rows):
        row["label"] = "Latest" if index == 0 else _day_label(row.get("date"))
    return rows


def _day_label(value) -> str:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return str(value or "")


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
    payload = summary_payload(model, currency=currency, title=title, generated_at=now)
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
            # The dated archive and its index - the app's fallback route.
            for report_id in report_ids:
                folder = f"ai-content/report-summaries/client/{report_id}"
                dated = {
                    "schemaVersion": SCHEMA_VERSION,
                    "client": client_container,
                    "generatedFor": "client",
                    "generatedAt": _iso(now),
                    "sourceRunId": f"{model['report_id']}-{model['anchor']}",
                    "payload": payload,
                }
                put(client_container, f"{folder}/{model['anchor']}.json",
                    json.dumps(dated, indent=2, ensure_ascii=False).encode("utf-8"), json_ct)

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
                    json.dumps(merged, indent=2, ensure_ascii=False).encode("utf-8"), json_ct)
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
