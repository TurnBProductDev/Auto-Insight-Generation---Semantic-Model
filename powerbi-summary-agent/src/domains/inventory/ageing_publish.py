"""Publish the Stock Age Analysis report to blob storage.

Same three destinations as `stock_health_publish.py`, because it is the same
client publishing pattern for a second inventory report:

1. **The agent's own store** (`azure_blob_*`), kept apart from the other
   reports sharing the container only by `azure_blob_prefix`.
2. **The app's store** (`ai_content_*`), a container per client holding
   `ai-content/report-summaries/client/{report-id}.*` - what the web app
   actually reads.
3. **The shared KPI feed**, report-aware so publishing Ageing cannot erase the
   cards Sales YoY, Target Tracker or Inventory Management already put there.

`publish_kpi_feed` is imported, never reimplemented, for the same reason
`stock_health_publish.py` gives: a second copy would be free to drift on
exactly the report-awareness that stops one report erasing another.

`summary_payload` must be `api_payloads.ReportSummaryPayload` and nothing
else - `extra="forbid"`, exactly `title`/`generatedAt`/`headline`/`metrics`/
`sections`. Two other reports already shipped a payload that merely
resembled the contract and had the app discard the file in silence; the
result here is validated before it is returned so this cannot drift the same
way a third time.

States the position as *at* a date, never as a span (Non-negotiable 18): a
stock position has no period.
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


def summary_payload(model: dict, *, title: str = "Stock Age Analysis",
                    generated_at: datetime | None = None) -> dict:
    """The app-facing summary, in the shared report-summary contract."""
    from ...tools.api_payloads import ReportSummaryPayload
    from . import money

    header = model.get("header") or {}
    currency = model.get("currency") or money.CURRENCY

    def fmt(value):
        return money.fmt(value, currency)

    metrics = [
        {"label": "Stock Value", "value": fmt(header.get("total_value")), "tone": "info"},
    ]
    aged_share = header.get("aged_share_pct")
    metrics.append({
        "label": "Aged Stock",
        "value": (fmt(header.get("aged_value"))
                  + (f" ({float(aged_share):.1f}% of stock)"
                     if isinstance(aged_share, (int, float)) else "")),
        "tone": "warning",
    })
    high_risk_share = header.get("high_risk_share_pct")
    metrics.append({
        "label": "High-Risk Stock",
        "value": (fmt(header.get("high_risk_value"))
                  + (f" ({float(high_risk_share):.1f}% of stock)"
                     if isinstance(high_risk_share, (int, float)) else "")),
        "tone": "critical",
    })
    metrics.append({
        "label": "Aged and Non-Moving",
        "value": fmt(header.get("aged_non_moving")),
        "tone": "critical",
    })

    # The movement, as its own metric. The headline stays on BR-28's order -
    # the oldest band leads the ranked findings, and that ordering is what the
    # rule governs - but a report that runs every day has to make the DIRECTION
    # visible somewhere on the card, or a reader has no way to tell a position
    # that is drifting from one that is holding.
    comparison = model.get("comparison") or {}
    move = next((h for h in comparison.get("headlines") or []
                 if h.get("key") == "aged_value_share"), None)
    if comparison.get("available") and isinstance(move.get("points") if move else None,
                                                  (int, float)):
        points = float(move["points"])
        metrics.append({
            "label": f"Change since {comparison.get('prior_as_at')}",
            "value": (f"{'+' if points >= 0 else '-'}{abs(points):.1f} points "
                      f"of aged share"),
            "tone": "critical" if points > 0.2 else
                    "success" if points < -0.2 else "info",
        })

    # What needs attention first - the ordered risk bands (BR-28: oldest
    # leads), then the aged/non-moving overlap. Never summed with the aged
    # total (BR-19); each call-out already carries its own share of stock
    # value, computed once by the report model.
    call_outs = model.get("call_outs") or []
    attention_points = []
    for row in call_outs:
        share = row.get("share_pct")
        bits = [f"{row.get('band')}: {fmt(row.get('value'))}"]
        if isinstance(share, (int, float)):
            bits.append(f"({share:.1f}% of stock value)")
        sentence = " ".join(bits) + "."
        if row.get("note"):
            sentence += f" {row['note']}"
        attention_points.append(sentence)
    overlap = header.get("aged_non_moving")
    if overlap:
        attention_points.append(
            f"{fmt(overlap)} is both aged and non-moving stock - old stock "
            f"with no recorded sales, the highest-risk combination. It is "
            f"not added to the aged total, because the two measures overlap.")
    if not attention_points:
        attention_points = ["No age band in this stock position is flagged as high-risk."]

    # The stock position - the report's own grounded, rule-checked narrative,
    # used verbatim rather than restated: it already carries a figure on
    # every line and bans the vocabulary a free-form summary would reach for.
    position_points = list(model.get("narrative") or [])
    if not position_points:
        position_points = [
            f"{fmt(header.get('total_value'))} of stock is held, of which "
            f"{fmt(header.get('aged_value'))} is aged."
        ]

    # What these figures cover - the as-at date, why a movement comparison is
    # or is not available, and the standing caveats. Never fabricated: a
    # single-snapshot model states plainly that it has no prior position.
    coverage_points = [
        f"Figures state the stock position "
        f"{model.get('period_label') or 'as at the latest load'}."
    ]
    migration = model.get("migration") or {}
    if migration.get("reason"):
        coverage_points.append(str(migration["reason"]))
    coverage_points.extend(str(c) for c in (model.get("caveats") or []))
    if currency:
        coverage_points.append(f"All figures are in {currency}.")
    coverage_points = list(dict.fromkeys(p for p in coverage_points if p))

    # What moved, and what may not be compared. Every sentence here is a share
    # or a count, because the two positions are not always valued the same way -
    # `ageing_history.basis_check` decides that from the data, and when it says
    # no, the reason is published rather than the comparison being dropped in
    # silence.
    change_section: list[dict] = []
    if comparison.get("available"):
        change_points = [
            f"Compared with the stock position of "
            f"{comparison.get('prior_as_at')} ({comparison.get('days')} days "
            f"earlier): {str(comparison.get('verdict') or '').lower()}."
        ]
        for reading in comparison.get("headlines") or []:
            if not isinstance(reading.get("points"), (int, float)):
                continue
            change_points.append(
                f"{reading.get('label')}: "
                f"{float(reading.get('then_pct') or 0):.1f}% to "
                f"{float(reading.get('now_pct') or 0):.1f}% "
                f"({'+' if float(reading['points']) >= 0 else '-'}"
                f"{abs(float(reading['points'])):.1f} points).")
        agreement = (comparison.get("agreement") or {}).get("text")
        if agreement:
            change_points.append(str(agreement))
        if not comparison.get("value_comparable"):
            reason = (comparison.get("basis") or {}).get("reason")
            if reason:
                change_points.append(str(reason))
        change_section = [{
            "heading": f"What changed since {comparison.get('prior_as_at')}",
            "tone": "critical" if "worse" in str(comparison.get("verdict") or "").lower()
                    else "info",
            "points": change_points,
        }]

    # An empty headline is the exact shape the app discards - it looks for
    # `headline`, does not find one, and drops the file without a word.
    headline = ""
    if call_outs:
        lead = call_outs[0]
        share = lead.get("share_pct")
        headline = f"{fmt(lead.get('value'))} of stock is in {lead.get('band')}"
        if isinstance(share, (int, float)):
            headline += f", {share:.1f}% of stock value"
        headline += "."
        if lead.get("note"):
            headline += f" {lead['note']}"
    if not headline.strip():
        headline = (f"{fmt(header.get('total_value'))} of stock is held "
                    f"{model.get('period_label') or 'at the latest load'}.")

    payload = {
        "title": title,
        "generatedAt": _iso(generated_at or datetime.now(timezone.utc)),
        "headline": headline,
        "metrics": metrics,
        "sections": ([
            {"heading": "What needs attention first", "tone": "critical",
             "points": attention_points},
        ] + change_section + [
            {"heading": "The stock position", "tone": "info",
             "points": position_points},
            {"heading": "What these figures cover", "tone": "info",
             "points": coverage_points},
        ]),
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
        "stockValue": header.get("total_value"),
        "agedValue": header.get("aged_value"),
        "highRiskValue": header.get("high_risk_value"),
    }


def merge_index(existing: list, entry: dict, *, keep: int = 30) -> list:
    """Newest first, one entry per position date, bounded.

    Keyed on the as-at date rather than the run date: two runs against the
    same stock position are the same entry, and the later one wins.
    """
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

    title = cfg.get("api_summary_title", "Stock Age Analysis")
    html_path = out_dir / "report_dashboard_ageing.html"
    if not html_path.is_file():
        return {"status": "failed", "reason": "artifacts_missing",
                "missing": [str(html_path)]}

    report_ids = [g for g in (_guid(v) for v in (cfg.get("ai_content_report_ids") or []))
                  if g]
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
        put(store, f"{base}report_dashboard_ageing.html", html_bytes, html_ct)
        put(store, f"{base}report_ageing.json", model_bytes, json_ct)
        put(store, f"{base}history/{as_at}/report_ageing.json", model_bytes, json_ct)
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
        # replaces only this report's own cards, so publishing Ageing cannot
        # erase cards the other reports already put there.
        if cfg.get("ai_content_multi_report_feed", False) and cards:
            from ...tools import ai_content_publisher as feed

            try:
                feed.publish_kpi_feed(
                    svc.get_container_client(client_container),
                    client=client_container,
                    dataset_id=str(cfg.get("dataset_id") or ""),
                    cards=cards,
                    report_id=str(cfg.get("report_id") or "inventory_ageing"),
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
