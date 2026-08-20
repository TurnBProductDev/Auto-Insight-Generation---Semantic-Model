"""Publish completed pipeline outputs into a tenant's app-serving container.

The existing ``insightgen`` and ``insightstate`` stores remain authoritative for
pipeline artifacts and private novelty memory.  This module adds a separate,
customer-facing projection under ``{client}/ai-content/``.  It never publishes
memory files and never writes outside the single configured client container.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID
from zoneinfo import ZoneInfo

import requests

from . import api_payloads
from .azure_blob import PROJECT_ROOT, _service_client


SCHEMA_VERSION = 1
_CLIENT = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])?$")
_REPORTS_URL = "https://api.powerbi.com/v1.0/myorg/groups/{workspace_id}/reports"


def enabled(state: dict) -> bool:
    cfg = state.get("config") or {}
    return bool(cfg.get("ai_content_publish_enabled", False))


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _client(state: dict) -> str:
    cfg = state.get("config") or {}
    value = str(cfg.get("ai_content_client") or "").strip().lower()
    if not value:
        mapping = cfg.get("dataset_client_map") or {}
        value = str(mapping.get(str(state.get("dataset_id") or "")) or "").strip().lower()
    if not value:
        raise ValueError("ai-content client is not configured")
    if not _CLIENT.fullmatch(value):
        raise ValueError(f"invalid Azure client container name: {value!r}")
    return value


def _guid(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text.startswith("PASTE_"):
        return None
    try:
        return str(UUID(text))
    except (ValueError, TypeError, AttributeError):
        return None


def _configured_report_ids(state: dict) -> list[str]:
    cfg = state.get("config") or {}
    raw = cfg.get("ai_content_report_ids") or cfg.get("ai_content_report_id") or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.split(",")]
    if not isinstance(raw, (list, tuple)):
        raise ValueError("ai_content_report_ids must be an array or comma-separated string")
    resolved = []
    invalid = []
    for value in raw:
        parsed = _guid(value)
        if parsed:
            if parsed not in resolved:
                resolved.append(parsed)
        elif str(value or "").strip():
            invalid.append(str(value))
    if invalid:
        raise ValueError(f"invalid Power BI report GUID(s): {invalid}")
    return resolved


def discover_report_ids(
    state: dict,
    *,
    http_get: Callable[..., Any] = requests.get,
) -> list[str]:
    """Return every workspace report backed by this run's dataset."""
    workspace_id = str(state.get("workspace_id") or "").strip()
    dataset_id = str(state.get("dataset_id") or "").strip().casefold()
    token = str(state.get("pbi_token") or "").strip()
    if not workspace_id or not dataset_id or not token:
        raise RuntimeError("report discovery requires workspace_id, dataset_id and the shared Power BI token")

    url = _REPORTS_URL.format(workspace_id=workspace_id)
    headers = {"Authorization": f"Bearer {token}"}
    report_ids: list[str] = []
    for _ in range(10):
        response = http_get(url, headers=headers, timeout=60)
        if not response.ok:
            raise RuntimeError(f"Power BI report discovery failed with HTTP {response.status_code}: {response.text[:500]}")
        body = response.json()
        for report in body.get("value", []) or []:
            if str(report.get("datasetId") or "").casefold() != dataset_id:
                continue
            report_id = _guid(report.get("id"))
            if report_id and report_id not in report_ids:
                report_ids.append(report_id)
        url = str(body.get("@odata.nextLink") or body.get("nextLink") or "").strip()
        if not url:
            break
    if not report_ids:
        raise RuntimeError(f"no Power BI report in workspace {workspace_id} uses dataset {state.get('dataset_id')}")
    return report_ids


def resolve_report_ids(state: dict) -> tuple[list[str], str]:
    configured = _configured_report_ids(state)
    if configured:
        return configured, "configured"
    return discover_report_ids(state), "powerbi_discovery"


def build_envelope(
    *,
    client: str,
    dataset_id: str,
    payload: Any,
    generated_at: datetime,
    expires_at: datetime,
) -> dict:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "client": client,
        "generatedFor": "client",
        "generatedAt": _iso_utc(generated_at),
        "expiresAt": _iso_utc(expires_at),
        "sourceDatasets": [dataset_id],
        "payload": payload,
    }


def _card_date(card: dict) -> date | None:
    try:
        return date.fromisoformat(str(card.get("isoDate") or ""))
    except (TypeError, ValueError):
        return None


_FEED_ORDER_KEY = "__feed_order"


def publish_kpi_feed(
    container,
    *,
    client: str,
    dataset_id: str,
    cards: list[dict],
    report_id: str,
    cfg: dict,
    now,
    expires,
    json_settings,
    receipts: dict,
) -> None:
    """Write this run's cards into the shared client KPI feed.

    Extracted so the LangGraph publisher and the standalone report runners share
    ONE implementation of the merge. A second copy would be free to drift, and
    the thing it would drift on is precisely the report-awareness that stops one
    report erasing another's cards.

    ``insights.json`` holds today's feed (a one-day window); ``alerts.json``
    holds the rolling retention. Both are read-merge-write with etag optimistic
    concurrency and three retries.
    """
    insights_blob = "ai-content/kpi/client/insights.json"
    alerts_blob = "ai-content/kpi/client/alerts.json"
    run_date = _run_date(cards, now, {})
    alert_days = max(1, int(cfg.get("ai_content_alert_days", 7)))

    for blob_name, days in ((insights_blob, 1), (alerts_blob, alert_days)):
        blob_client = container.get_blob_client(blob_name)
        for attempt in range(3):
            try:
                previous, etag = _download_alerts(blob_client)
                merged = merge_alerts(previous, cards, run_date, days, report_id=report_id)
                merged = _cap_feed(merged, cfg)
                envelope = build_envelope(
                    client=client,
                    dataset_id=dataset_id,
                    payload=merged,
                    generated_at=now,
                    expires_at=expires,
                )
                _upload_alerts(blob_client, envelope, etag, json_settings)
                receipts[blob_name] = {"status": "ok", "cards": len(merged)}
                break
            except Exception as exc:  # noqa: BLE001 - retry only Azure write conflicts
                from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

                if isinstance(exc, (ResourceExistsError, ResourceModifiedError)) and attempt < 2:
                    continue
                raise


def _cap_feed(cards: list[dict], cfg: dict) -> list[dict]:
    """Trim a shared feed to its total budget, guaranteeing every report a slot.

    ``fair_share`` reserves one place per contributing report **before** the list
    is truncated. Appending a quiet report's card and then cutting by score
    discards it every time, because an injected candidate is by definition the
    weakest thing in the list (WP8).

    Cards carry no score of their own, so the caller's existing order - newest
    date first, as ``merge_alerts`` left it - is turned into a descending score.
    That keeps the published ordering identical to what it would have been, and
    only changes *which* cards survive the cut. The temporary key never reaches
    the payload: ``KpiCard`` forbids extra fields, so leaking it would break the
    contract this whole change exists to protect.
    """
    limit = max(1, int(cfg.get("ai_content_feed_max_cards", 10)))
    if len(cards) <= limit:
        return cards
    from ..kernel import chain

    total = len(cards)
    ranked = [{**card, _FEED_ORDER_KEY: float(total - index)} for index, card in enumerate(cards)]
    selected = ranked[:limit]
    chosen = chain.fair_share(
        ranked, selected, limit=limit,
        score_key=_FEED_ORDER_KEY, report_key="reportId",
    )
    return [{k: v for k, v in card.items() if k != _FEED_ORDER_KEY} for card in chosen]


def _card_report(card: dict) -> str:
    """The report a published card belongs to; '' for a pre-multi-report card."""
    return str(card.get("reportId") or "")


def merge_alerts(
    previous: list[dict],
    today: list[dict],
    run_date: date,
    days: int = 7,
    report_id: str = "",
) -> list[dict]:
    """Replace this report's same-day rerun, retain N calendar days, newest first.

    The merge is **report-aware**: a run clears only the cards it published
    itself for that date. Dropping every same-day card - the previous behaviour -
    silently deleted the other reports' findings the moment two reports shared a
    client feed, and the seven-day retention repeated the fault on every
    subsequent day.

    ``report_id`` defaults to ``""``, which is also what an untagged legacy card
    reports. So in single-report mode a run still replaces the untagged cards it
    wrote yesterday - today's behaviour exactly - while in multi-report mode a
    run matches only its own tagged cards and leaves untagged legacy cards to
    age out of the window naturally.
    """
    cutoff = run_date - timedelta(days=max(1, int(days)) - 1)
    own = str(report_id or "")
    merged = [
        card for card in previous
        if isinstance(card, dict)
        and _card_date(card) is not None
        and cutoff <= _card_date(card) <= run_date
        and not (_card_date(card) == run_date and _card_report(card) == own)
    ]
    merged.extend(card for card in today if isinstance(card, dict))
    indexed = list(enumerate(merged))
    indexed.sort(key=lambda pair: (_card_date(pair[1]) or date.min, -pair[0]), reverse=True)
    return [card for _, card in indexed]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str).encode("utf-8")


def _download_alerts(blob) -> tuple[list[dict], str | None]:
    from azure.core.exceptions import ResourceNotFoundError

    try:
        download = blob.download_blob()
    except ResourceNotFoundError:
        return [], None
    raw = download.readall()
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("existing ai-content alerts.json is corrupt; refusing to overwrite it") from exc
    # Accept a legacy unwrapped seed once, then migrate it to the v1 envelope.
    payload = body.get("payload") if isinstance(body, dict) else body
    if not isinstance(payload, list):
        raise RuntimeError("existing ai-content alerts.json payload is not an array")
    properties = getattr(download, "properties", None)
    etag = getattr(properties, "etag", None)
    if etag is None and isinstance(properties, dict):
        etag = properties.get("etag")
    return payload, etag


def _upload_alerts(blob, envelope: dict, previous_etag: str | None, content_settings) -> None:
    from azure.core import MatchConditions

    kwargs = {
        "data": _json_bytes(envelope),
        "content_settings": content_settings,
    }
    if previous_etag:
        blob.upload_blob(
            overwrite=True,
            etag=previous_etag,
            match_condition=MatchConditions.IfNotModified,
            **kwargs,
        )
    else:
        blob.upload_blob(overwrite=False, **kwargs)


def _run_date(cards: list[dict], generated_at: datetime, state: dict) -> date:
    dated = [value for value in (_card_date(card) for card in cards) if value]
    if dated:
        return max(dated)
    cfg = state.get("config") or {}
    timezone_name = str(cfg.get("insight_history_timezone") or "Asia/Kolkata")
    return generated_at.astimezone(ZoneInfo(timezone_name)).date()


def publish(
    state: dict,
    *,
    generated_at: datetime | None = None,
    service_client=None,
    report_ids: list[str] | None = None,
) -> dict:
    """Publish insights, rolling alerts, and report summary JSON/HTML."""
    if not enabled(state):
        return {"status": "skipped", "reason": "ai_content_publish_disabled"}

    cfg = state.get("config") or {}
    account = str(cfg.get("azure_blob_account") or "").strip()
    if not account:
        return {"status": "failed", "reason": "azure_blob_account_missing"}
    try:
        client = _client(state)
        resolved_reports, report_source = (
            ([item for item in (_guid(value) for value in report_ids) if item], "provided")
            if report_ids is not None
            else resolve_report_ids(state)
        )
        if not resolved_reports:
            raise RuntimeError("no valid Power BI report GUIDs were resolved")

        output = PROJECT_ROOT / str(state.get("output_folder") or "outputs")
        insights_path = output / "api" / "kpi_insights.json"
        summary_json_path = output / "api" / "report_summary.json"
        summary_html_path = output / "report_summary.html"
        missing = [str(path) for path in (insights_path, summary_json_path, summary_html_path) if not path.is_file()]
        if missing:
            raise RuntimeError(f"required ai-content artifacts are missing: {missing}")
        insights = _read_json(insights_path)
        summary = _read_json(summary_json_path)
        if not isinstance(insights, list):
            raise RuntimeError("kpi_insights.json root must be an array")
        if not isinstance(summary, dict):
            raise RuntimeError("report_summary.json root must be an object")
        summary_html = summary_html_path.read_text(encoding="utf-8")

        now = generated_at or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        ttl_hours = max(1.0, float(cfg.get("ai_content_ttl_hours", 24)))
        expires = now + timedelta(hours=ttl_hours)
        dataset_id = str(state.get("dataset_id") or "")

        svc, auth = (service_client, "provided") if service_client is not None else _service_client(account)
        container = svc.get_container_client(client)
        from azure.storage.blob import ContentSettings

        json_settings = ContentSettings(content_type="application/json")
        html_settings = ContentSettings(content_type="text/html; charset=utf-8")
        receipts: dict[str, dict] = {}

        def upload_json(name: str, payload: Any) -> None:
            envelope = build_envelope(
                client=client,
                dataset_id=dataset_id,
                payload=payload,
                generated_at=now,
                expires_at=expires,
            )
            container.get_blob_client(name).upload_blob(
                data=_json_bytes(envelope),
                overwrite=True,
                content_settings=json_settings,
            )
            receipts[name] = {"status": "ok"}

        insights_blob = "ai-content/kpi/client/insights.json"
        alerts_blob = "ai-content/kpi/client/alerts.json"
        multi_report = api_payloads.multi_report_feed(state)
        feed_report = api_payloads.feed_report_id(state) if multi_report else ""
        run_date = _run_date(insights, now, state)

        if multi_report:
            # insights.json is a plain overwrite in single-report mode, which
            # would erase every other report's cards the moment a second report
            # publishes into the same client feed. In multi-report mode it gets
            # the same read-merge-write with etag concurrency that alerts use,
            # over a single day's window (insights is today's feed; alerts is
            # the rolling history).
            insights_client = container.get_blob_client(insights_blob)
            for attempt in range(3):
                try:
                    previous, etag = _download_alerts(insights_client)
                    merged_insights = merge_alerts(
                        previous, insights, run_date, 1, report_id=feed_report,
                    )
                    merged_insights = _cap_feed(merged_insights, cfg)
                    envelope = build_envelope(
                        client=client,
                        dataset_id=dataset_id,
                        payload=merged_insights,
                        generated_at=now,
                        expires_at=expires,
                    )
                    _upload_alerts(insights_client, envelope, etag, json_settings)
                    receipts[insights_blob] = {"status": "ok", "cards": len(merged_insights)}
                    break
                except Exception as exc:  # noqa: BLE001 - retry only Azure write conflicts
                    from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

                    if isinstance(exc, (ResourceExistsError, ResourceModifiedError)) and attempt < 2:
                        continue
                    raise
        else:
            upload_json(insights_blob, insights)

        alert_client = container.get_blob_client(alerts_blob)
        alert_days = max(1, int(cfg.get("ai_content_alert_days", 7)))
        for attempt in range(3):
            try:
                previous, etag = _download_alerts(alert_client)
                merged = merge_alerts(
                    previous, insights, run_date, alert_days, report_id=feed_report,
                )
                envelope = build_envelope(
                    client=client,
                    dataset_id=dataset_id,
                    payload=merged,
                    generated_at=now,
                    expires_at=expires,
                )
                _upload_alerts(alert_client, envelope, etag, json_settings)
                receipts[alerts_blob] = {"status": "ok", "cards": len(merged)}
                break
            except Exception as exc:  # noqa: BLE001 - retry only Azure write conflicts
                from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

                if isinstance(exc, (ResourceExistsError, ResourceModifiedError)) and attempt < 2:
                    continue
                raise

        html_metadata_base = {
            "schemaversion": str(SCHEMA_VERSION),
            "client": client,
            "generatedfor": "client",
            "generatedat": _iso_utc(now),
            "expiresat": _iso_utc(expires),
            "sourcedatasets": dataset_id,
        }
        for report_id in resolved_reports:
            json_blob = f"ai-content/report-summaries/client/{report_id}.json"
            html_blob = f"ai-content/report-summaries/client/{report_id}.html"
            upload_json(json_blob, summary)
            container.get_blob_client(html_blob).upload_blob(
                data=summary_html.encode("utf-8"),
                overwrite=True,
                content_settings=html_settings,
                metadata={**html_metadata_base, "reportid": report_id},
            )
            receipts[html_blob] = {"status": "ok"}

        insight_names = {insights_blob, alerts_blob}
        summary_names = set(receipts) - insight_names
        insight_ok = all((receipts.get(name) or {}).get("status") == "ok" for name in insight_names)
        summary_ok = bool(summary_names) and all(receipts[name]["status"] == "ok" for name in summary_names)
        print(
            f"AI content: published {len(receipts)} blob(s) to {account}/{client}/ai-content "
            f"for {len(resolved_reports)} report(s) (auth={auth}, report_ids={report_source})."
        )
        return {
            "status": "ok" if insight_ok and summary_ok else "failed",
            "client": client,
            "reportIds": resolved_reports,
            "reportIdSource": report_source,
            "insightStatus": "ok" if insight_ok else "failed",
            "summaryStatus": "ok" if summary_ok else "failed",
            "receipts": receipts,
            "generatedAt": _iso_utc(now),
            "expiresAt": _iso_utc(expires),
            "auth": auth,
        }
    except Exception as exc:  # noqa: BLE001 - visible receipt; caller owns failure policy
        print(f"AI content publish failed ({type(exc).__name__}: {exc}).")
        return {
            "status": "failed",
            "reason": type(exc).__name__,
            "error": str(exc),
            "insightStatus": "failed",
            "summaryStatus": "failed",
        }
