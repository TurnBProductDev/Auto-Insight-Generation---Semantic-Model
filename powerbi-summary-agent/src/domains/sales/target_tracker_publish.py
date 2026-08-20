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


#: Band -> the contract's Tone literal. `Tone` allows only these five values.
_TONE = {"good": "positive", "warn": "warning", "crit": "critical", "none": "info"}


def summary_payload(model: dict, *, currency: str = "SAR", title: str = "Target Tracker") -> dict:
    """The app-facing summary object, in the shared report-summary contract.

    **This must be `api_payloads.ReportSummaryPayload` and nothing else.** That
    model is `extra="forbid"` with exactly five fields - `title`, `generatedAt`,
    `headline`, `metrics`, `sections` - and the app reads those names.

    An earlier version of this function invented its own shape: the headline
    sentence was filed under `heading`, the detail under `points`, `metrics` was
    absent, and ten fields the contract does not allow were added
    (`reportId`, `dataAsOf`, `soldThrough`, `currency`, `grain`, `summaryType`,
    `branchesBelowTarget`, `schemaVersion`). The app looked for `headline`, did
    not find it, and discarded the whole file **silently** - no error, no log
    line - so the report simply never appeared for eight days and looked from
    the outside like a missing blob.

    The figures that the contract has no field for are not dropped; they are
    stated in the prose, and `grain`/`dataAsOf` ride on the history index entry
    where the contract does carry them.

    The result is validated before it is returned, so this can never drift
    again in silence.
    """
    from ...tools.api_payloads import ReportSummaryPayload
    from .target_tracker_html import _R, headline, money, pc

    r = _R(currency)
    periods = model["periods"]

    # KPI tiles: one per period, worst-performing tone carried from its band.
    metrics = [
        {
            "label": periods[key]["name"],
            "value": f"{pc(periods[key]['attainment'])} of target",
            "tone": _TONE.get(periods[key]["band"], "info"),
        }
        for key in ("day", "wtd", "mtd", "ytd")
    ]

    performance_points = [
        (f"{periods[key]['name']} ({periods[key]['elapsed']}): {currency} "
         f"{money(periods[key]['actual'])} against a target of {currency} "
         f"{money(periods[key]['target'])} - {pc(periods[key]['attainment'])} of target, "
         f"{currency} {money(abs(periods[key]['variance']))} "
         f"{'above' if periods[key]['variance'] >= 0 else 'below'} target.")
        for key in ("day", "wtd", "mtd", "ytd")
    ]

    behind = [b["name"] for b in model["branches"] if b["mtd"]["band"] == "crit"]
    if behind:
        branch_points = [
            (f"{b['name']} is at {pc(b['mtd']['attainment'])} of target for this month so far, "
             f"{currency} {money(abs(b['mtd']['variance']))} below target.")
            for b in model["branches"] if b["mtd"]["band"] == "crit"
        ]
        branch_tone = "critical"
    else:
        branch_points = ["Every branch reached its target for this month so far."]
        branch_tone = "positive"

    # Where the contract has no field, the fact becomes a sentence rather than
    # being lost: the as-at date, the gap to the latest sales, and the branches
    # the comparison covers.
    coverage_points = [
        f"Figures are measured to {model['anchor']}, the most recent day that carries a target."
    ]
    if model.get("target_lag_days"):
        coverage_points.append(
            f"Sales have been recorded for a further {model['target_lag_days']} days, to "
            f"{model['sold_through']}, but no target has been set for them, so they are not "
            f"included in any comparison above."
        )
    if model.get("population"):
        coverage_points.append(
            f"Covers {len(model['population'])} branches: {', '.join(model['population'])}."
        )
    coverage_points.append(f"All figures are in {currency}.")

    payload = {
        "title": title,
        "generatedAt": _iso(datetime.now(timezone.utc)),
        "headline": headline(r, model),
        "metrics": metrics,
        "sections": [
            {"heading": "Performance against target",
             "tone": _TONE.get(periods["mtd"]["band"], "info"),
             "points": performance_points},
            {"heading": "Branches", "tone": branch_tone, "points": branch_points},
            {"heading": "What these figures cover", "tone": "info", "points": coverage_points},
        ],
    }
    # Fail loudly here rather than have the app discard the file in silence.
    return ReportSummaryPayload(**payload).model_dump()


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
