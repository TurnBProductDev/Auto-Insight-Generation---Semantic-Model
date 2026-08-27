"""Publish the Inventory Management report to blob storage.

Three destinations, and they are genuinely different things - conflating them is
what made the storage settings confusing enough to need `services/storage.py`:

1. **The agent's own store** (`azure_blob_*`), where every client shares one
   container and is kept apart only by `azure_blob_prefix`. Inventory writes to
   `sb-mart/inventory-management/`; Sales YoY uses an empty prefix in the same
   container, so an inventory run without a prefix would overwrite its
   `api/*.json`.
2. **The app's store** (`ai_content_*`), a container per client holding
   `ai-content/report-summaries/client/{report-id}.*`. This is what the web app
   actually reads, and it is not what the `azure_blob_*` settings control.
3. **The shared KPI feed**, which is report-aware and must stay so: the merge
   replaces only this report's own cards, so publishing inventory cannot erase
   the Sales YoY or Target Tracker cards already in the feed.

`publish_kpi_feed` is imported, never reimplemented. A second copy would be free
to drift on exactly the report-awareness that stops one report erasing another.
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


#: The health-score bands, mapped onto the contract's tone vocabulary.
_SCORE_TONE = {"Excellent": "positive", "Healthy": "positive", "Watch": "warning",
               "At Risk": "critical", "Critical": "critical"}


def summary_payload(model: dict, score: dict | None = None, *,
                    title: str = "Inventory Management",
                    generated_at: datetime | None = None) -> dict:
    """The app-facing summary, in the shared report-summary contract.

    **This must be `api_payloads.ReportSummaryPayload` and nothing else.** That
    model is `extra="forbid"` with exactly five fields - `title`, `generatedAt`,
    `headline`, `metrics`, `sections` - and the app reads those names.

    An earlier version of this function invented its own shape while its
    docstring claimed to be "additive to the shared contract": it omitted
    `generatedAt` and `sections` entirely, filed the KPI tiles under
    `name`/`unit`/`band`/`sharePct` instead of `label`/`value`/`tone` with
    numeric rather than string values, and added twelve fields the contract
    forbids (`reportId`, `reportName`, `periodLabel`, `asAt`, `currency`,
    `narrative`, `notes`, `queue`, `statesNotReported`, `comparison`,
    `caveats`, `checks`). Validated against the contract it produced 52 errors.

    This is the *second* time this defect has shipped - Target Tracker carried
    the identical fault, and the app discarded that file **silently**, with no
    error and no log line, so the report simply never appeared and looked from
    the outside like a missing blob. Here it presented as a client whose
    insights rendered while the Home brief stayed empty.

    The figures the contract has no field for are not dropped; they become
    sentences in `sections`, and the position figures ride on the history index
    entry where the contract does carry them.

    Deliberately states the position as *at* a date rather than over a span
    (Non-negotiable 18): a stock position has no period, and a consumer that
    formats a span label as a range would misreport it.

    The result is validated before it is returned, so this can never drift
    again in silence.
    """
    from ...tools.api_payloads import ReportSummaryPayload
    from . import money

    header = model.get("header") or {}
    prose = model.get("prose") or {}
    queue = model.get("queue") or []
    currency = model.get("currency") or money.CURRENCY

    def _int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # KPI tiles. `value` is a string by contract, so every figure is formatted
    # here rather than handed over raw for the app to guess a unit for.
    metrics = []
    if score:
        band = score.get("band")
        metrics.append({
            "label": "Inventory Health Score",
            "value": f"{float(score['score']):.1f}" + (f" - {band}" if band else ""),
            "tone": _SCORE_TONE.get(band, "info"),
        })
    metrics.append({
        "label": "Stock Value",
        "value": money.fmt(header.get("stock_value"), currency),
        "tone": "info",
    })
    excess_share = header.get("excess_share_pct")
    metrics.append({
        "label": "Excess Stock",
        "value": (money.fmt(header.get("excess_value"), currency)
                  + (f" ({float(excess_share):.1f}% of stock)"
                     if isinstance(excess_share, (int, float)) else "")),
        "tone": "warning",
    })
    metrics.append({
        "label": "Opportunity Loss per day",
        "value": money.fmt(header.get("opportunity_loss_day"), currency),
        "tone": "critical",
    })
    rows, total_rows = _int(header.get("exception_rows")), _int(header.get("loc_skus"))
    metrics.append({
        "label": "Loc-SKUs needing action",
        "value": (f"{rows:,} of {total_rows:,}" if rows is not None and total_rows
                  else (f"{rows:,}" if rows is not None else "-")),
        "tone": "critical" if rows else "info",
    })

    # The action queue, most urgent first. BR-31 puts the two double-warning
    # states ahead of everything regardless of value, and the queue arrives in
    # that order already, so it is preserved rather than re-sorted here.
    queue_points = []
    for row in queue:
        if not row.get("is_exception"):
            continue
        loc_skus = _int(row.get("loc_skus"))
        bits = [f"{row.get('action')}:",
                f"{loc_skus:,} Loc-SKUs" if loc_skus is not None else "Loc-SKUs"]
        if row.get("stock_value"):
            bits.append(f"holding {money.fmt(row.get('stock_value'), currency)}")
        sentence = " ".join(bits) + "."
        if row.get("guidance"):
            sentence += f" {row['guidance']}"
        if row.get("double_warning"):
            sentence += " Listed as most urgent."
        queue_points.append(sentence)
        if len(queue_points) >= 6:
            break
    if not queue_points:
        queue_points = ["No Loc-SKU is in a state that needs action."]

    position_points = []
    if prose.get("narrative"):
        position_points.append(prose["narrative"])
    for note in (prose.get("queue_note"), prose.get("excess_note")):
        if note:
            position_points.append(note)
    if not position_points:
        position_points = [
            f"{money.fmt(header.get('stock_value'), currency)} of stock is held, of which "
            f"{money.fmt(header.get('excess_value'), currency)} is above the agreed cover."
        ]

    # Where the contract has no field, the fact becomes a sentence rather than
    # being lost: the as-at date, the comparison verdict, the states the source
    # returned nothing for, and the standing caveats.
    coverage_points = [
        f"Figures state the stock position "
        f"{model.get('period_label') or 'as at the latest load'}."
    ]
    comparison = model.get("comparison") or {}
    if comparison.get("comparable"):
        coverage_points.append(
            f"Compared with the position {comparison.get('prior_as_at')}"
            + (f" ({comparison['age_days']} days earlier)."
               if comparison.get("age_days") is not None else ".")
        )
    elif comparison.get("reason_text"):
        coverage_points.append(str(comparison["reason_text"]))
    for state in (model.get("states_absent_urgent") or []):
        coverage_points.append(
            f"{state} returned no Loc-SKUs, which the rules list as one to report first."
        )
    coverage_points.extend(str(c) for c in (model.get("caveats") or []))
    coverage_points.append(f"All figures are in {currency}.")

    # The comparison verdict is also carried as a standing caveat, so the same
    # sentence arrives twice. Deduplicate on the text while keeping the first
    # position: a caveat printed twice reads as a broken page (the same lesson
    # as the R6 "every caveat appears once" rule).
    coverage_points = list(dict.fromkeys(coverage_points))

    # An empty headline is the exact shape the app discards - it looks for
    # `headline`, does not find one, and drops the file without a word. The
    # prose block always carries one in production (the deterministic draft is
    # the floor), so this is the belt-and-braces case: state the position from
    # figures already in the model rather than publish a file that cannot be
    # rendered.
    headline = prose.get("headline") or ""
    if not headline.strip():
        lead = next((row for row in queue if row.get("is_exception")), None)
        lead_rows = _int((lead or {}).get("loc_skus"))
        if lead and lead_rows:
            headline = (f"{lead_rows:,} Loc-SKUs are in {lead['action']} "
                        f"and need attention first.")
        else:
            headline = (f"{money.fmt(header.get('stock_value'), currency)} of stock is held "
                        f"{model.get('period_label') or 'at the latest load'}.")

    payload = {
        "title": title,
        "generatedAt": _iso(generated_at or datetime.now(timezone.utc)),
        "headline": headline,
        "metrics": metrics,
        "sections": [
            {"heading": "What needs action first", "tone": "critical",
             "points": queue_points},
            {"heading": "The stock position", "tone": "info",
             "points": position_points},
            {"heading": "What these figures cover", "tone": "info",
             "points": coverage_points},
        ],
    }
    # Fail loudly here rather than have the app discard the file in silence.
    return ReportSummaryPayload(**payload).model_dump(exclude_none=True)


def history_entry(model: dict, payload: dict, report_id: str,
                  generated_at: datetime) -> dict:
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
        "stockValue": header.get("stock_value"),
        "excessValue": header.get("excess_value"),
        "locSkusNeedingAction": header.get("exception_rows"),
    }


def merge_index(existing: list, entry: dict, *, keep: int = 30) -> list:
    """Newest first, one entry per position date, bounded.

    Keyed on the as-at date rather than the run date: two runs against the same
    stock position are the same entry, and the later one wins.
    """
    rows = [row for row in (existing or [])
            if isinstance(row, dict) and row.get("asAt") != entry.get("asAt")]
    rows.append(entry)
    rows.sort(key=lambda row: str(row.get("asAt") or ""), reverse=True)
    return rows[:keep]


def publish(cfg: dict, out_dir: Path, model: dict, score: dict | None = None, *,
            cards: list | None = None, service_client=None,
            generated_at: datetime | None = None) -> dict:
    """Push the report to all three destinations. Returns a visible receipt."""
    account = str(cfg.get("azure_blob_account") or "").strip()
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}

    title = cfg.get("api_summary_title", "Inventory Management")
    html_path = out_dir / "report_dashboard_stock_health.html"
    if not html_path.is_file():
        return {"status": "failed", "reason": "artifacts_missing",
                "missing": [str(html_path)]}

    report_ids = [g for g in (_guid(v) for v in (cfg.get("ai_content_report_ids") or []))
                  if g]
    if not report_ids:
        return {"status": "failed", "reason": "ai_content_report_ids_missing"}

    now = generated_at or datetime.now(timezone.utc)
    expires = now + timedelta(hours=max(1.0, float(cfg.get("ai_content_ttl_hours", 24))))
    payload = summary_payload(model, score, title=title, generated_at=now)
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

    # 1. the agent's own store, under this report's own prefix
    store = str(cfg.get("azure_blob_container") or "insightgen")
    prefix = str(cfg.get("azure_blob_prefix") or "").strip("/")
    base = f"{prefix}/" if prefix else ""
    html_bytes = html_path.read_bytes()
    model_bytes = json.dumps(model, indent=2, default=str).encode("utf-8")
    payload_bytes = json.dumps(payload, indent=2, ensure_ascii=False,
                               default=str).encode("utf-8")
    as_at = str(model.get("as_at") or "unknown")
    try:
        put(store, f"{base}api/report_summary.json", payload_bytes, json_ct)
        put(store, f"{base}report_dashboard_stock_health.html", html_bytes, html_ct)
        put(store, f"{base}report_stock_health.json", model_bytes, json_ct)
        put(store, f"{base}history/{as_at}/report_stock_health.json", model_bytes, json_ct)
        if score:
            put(store, f"{base}report_inventory_health.json",
                json.dumps(score, indent=2, default=str).encode("utf-8"), json_ct)
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
                "generatedfor": "client", "generatedat": _iso(now),
                "expiresat": _iso(expires),
                "sourcedatasets": str(cfg.get("dataset_id") or "")}
        try:
            for report_id in report_ids:
                folder = f"ai-content/report-summaries/client/{report_id}"
                put(client_container, f"{folder}.json",
                    json.dumps(envelope, indent=2, ensure_ascii=False,
                               default=str).encode("utf-8"), json_ct)
                put(client_container, f"{folder}.html", html_bytes, html_ct,
                    {**meta, "reportid": report_id})

                dated = {"schemaVersion": SCHEMA_VERSION, "client": client_container,
                         "generatedFor": "client", "generatedAt": _iso(now),
                         "sourceRunId": f"{model.get('report_id')}-{as_at}",
                         "payload": payload}
                put(client_container, f"{folder}/{as_at}.json",
                    json.dumps(dated, indent=2, ensure_ascii=False,
                               default=str).encode("utf-8"), json_ct)

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
                    json.dumps(merged, indent=2, ensure_ascii=False,
                               default=str).encode("utf-8"), json_ct)
            app_status = "ok"
        except Exception as exc:  # noqa: BLE001
            return {"status": "failed", "reason": type(exc).__name__, "error": str(exc),
                    "appStatus": "failed", "receipts": receipts}

        # 3. the shared KPI feed. Report-aware by construction: the merge
        # replaces only this report's own cards, so publishing inventory cannot
        # erase the cards Sales YoY or Target Tracker already put there.
        if cfg.get("ai_content_multi_report_feed", False) and cards:
            from ...tools import ai_content_publisher as feed

            try:
                feed.publish_kpi_feed(
                    svc.get_container_client(client_container),
                    client=client_container,
                    dataset_id=str(cfg.get("dataset_id") or ""),
                    cards=cards,
                    report_id=str(cfg.get("report_id") or "inventory_stock_health"),
                    cfg=cfg,
                    now=now,
                    expires=expires,
                    json_settings=json_ct,
                    receipts=receipts,
                )
                feed_status = "ok"
            except Exception as exc:  # noqa: BLE001 - never cost the report
                feed_status = f"failed: {type(exc).__name__}: {exc}"

    return {
        "status": "ok",
        "auth": auth,
        "account": account,
        "store": f"{store}/{base}" if base else store,
        "appContainer": client_container,
        "appStatus": app_status,
        "feedStatus": feed_status,
        "reportIds": report_ids,
        "asAt": as_at,
        "receipts": receipts,
    }
