"""Build immutable, presentation-ready insight-history entries.

Each successful run gets one JSON document.  The document is deliberately
self-contained: consumers can list the per-run blobs, sort ``runAt`` descending,
and group on ``date.iso`` without mutating an ever-growing master file.

The heading/body parser is shared with ``insight_tiles`` so the history screen
shows exactly the same bold takeaway and supporting paragraph as the tile board.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .insight_tiles import insights_from_markdown

# .../powerbi-summary-agent/src/tools/insight_history.py -> parents[2] == project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
DEFAULT_TIMEZONE = "Asia/Kolkata"
_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9_.-]+")
_SAFE_DATASET = re.compile(r"[^A-Za-z0-9_.-]+")


def _timezone(state: dict) -> ZoneInfo:
    cfg = state.get("config", {}) or {}
    name = str(cfg.get("insight_history_timezone") or DEFAULT_TIMEZONE).strip()
    if not name or name.lower() in {"auto", "naive"}:
        name = DEFAULT_TIMEZONE
    return ZoneInfo(name)


def _run_at(state: dict, generated_at: datetime | None = None) -> datetime:
    tz = _timezone(state)
    if generated_at is None:
        return datetime.now(tz)
    if generated_at.tzinfo is None:
        return generated_at.replace(tzinfo=tz)
    return generated_at.astimezone(tz)


def _run_id(when: datetime, explicit: str | None = None) -> str:
    # Container Apps exposes one stable name per job execution, including its
    # replica retries. Other schedulers can supply the generic override. Local
    # runs use a microsecond timestamp, so two intentional runs never collide.
    raw = (
        explicit
        or os.environ.get("INSIGHT_HISTORY_RUN_ID")
        or os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME")
    )
    if raw:
        safe = _SAFE_RUN_ID.sub("-", str(raw)).strip("-._")
        if safe:
            return safe
    return when.strftime("%Y%m%dT%H%M%S%f%z")


def _dataset_id(state: dict) -> str:
    return str(state.get("dataset_id") or "unknown_dataset")


def build_entry(
    state: dict,
    *,
    report_md: str | None = None,
    generated_at: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    """Return one history entry, or ``None`` when no real report was produced.

    ``save_outputs`` writes a stub report to disk when synthesis failed, but does
    not put that stub in ``state['insight_report']``.  Requiring the state value
    therefore prevents a stale/stub file from entering customer-facing history.
    """
    source = report_md if report_md is not None else state.get("insight_report")
    if not isinstance(source, str) or not source.strip():
        return None

    when = _run_at(state, generated_at)
    parsed = insights_from_markdown(source)
    insights = [
        {"heading": heading, "content": content}
        for heading, content in parsed
        if heading
    ]
    iso_day = when.date().isoformat()
    display_day = f"{when.day} {when.strftime('%B %Y')}"
    rid = _run_id(when, run_id)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "datasetId": _dataset_id(state),
        "runId": rid,
        "date": {
            "iso": iso_day,
            "display": display_day,
            "timezone": str(when.tzinfo),
        },
        "runAt": when.isoformat(timespec="seconds"),
        "status": "completed" if insights else "no_new_insights",
        "insightCount": len(insights),
        "insights": insights,
    }


def blob_name(state: dict, entry: dict) -> str:
    """Return the immutable blob path for ``entry`` within its container."""
    cfg = state.get("config", {}) or {}
    root_prefix = str(cfg.get("azure_blob_prefix", "") or "").strip("/")
    history_prefix = str(
        cfg.get("azure_blob_history_prefix", "history") or "history"
    ).strip("/")
    dataset = _SAFE_DATASET.sub("_", str(entry.get("datasetId") or "unknown_dataset"))
    year, month, day = str(entry["date"]["iso"]).split("-")
    parts = [
        root_prefix,
        history_prefix,
        dataset,
        year,
        month,
        day,
        f"{entry['runId']}.json",
    ]
    return "/".join(part for part in parts if part)


def build_history_response(entries: list[dict[str, Any]], dataset_id: str = "") -> dict:
    """Build the minimal API response: date groups and same-day runs, newest first.

    This is a read-side projection only. It never changes the source entries;
    an API can rebuild it at any time by listing the dataset's history prefix.
    ``dataset_id`` remains accepted for compatibility but is intentionally not
    exposed in the app-facing JSON.
    """
    valid = [
        entry for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("date"), dict)
        and entry["date"].get("iso")
        and entry.get("runAt")
    ]
    valid.sort(key=lambda entry: str(entry["runAt"]), reverse=True)

    dates: list[dict[str, Any]] = []
    by_date: dict[str, dict[str, Any]] = {}
    for entry in valid:
        iso_day = str(entry["date"]["iso"])
        group = by_date.get(iso_day)
        if group is None:
            group = {
                "date": iso_day,
                "runs": [],
            }
            by_date[iso_day] = group
            dates.append(group)
        run_at = str(entry.get("runAt") or "")
        try:
            run_time = datetime.fromisoformat(run_at).strftime("%H:%M:%S")
        except ValueError:
            run_time = run_at.split("T", 1)[-1][:8] if "T" in run_at else run_at
        group["runs"].append({
            "time": run_time,
            "status": entry.get("status"),
            "insights": entry.get("insights") or [],
        })

    timezone_name = DEFAULT_TIMEZONE
    if valid:
        timezone_name = str(
            valid[0].get("date", {}).get("timezone") or DEFAULT_TIMEZONE
        )
    return {
        "timezone": timezone_name,
        "history": dates,
    }


def _entries_from_response(response: dict | None) -> list[dict[str, Any]]:
    """Expand a stored single-file response back into immutable run entries."""
    if not isinstance(response, dict):
        return []
    groups = response.get("history")
    if not isinstance(groups, list):
        # Accept the short-lived pre-feed prototype name for painless upgrades.
        groups = response.get("dates")
    dataset_id = str(response.get("datasetId") or "")
    timezone_name = str(response.get("timezone") or DEFAULT_TIMEZONE)
    try:
        response_tz = ZoneInfo(timezone_name)
    except Exception:  # noqa: BLE001 - legacy/corrupt timezone stays sortable
        response_tz = None
    entries: list[dict[str, Any]] = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        raw_date = group.get("date")
        if isinstance(raw_date, dict):
            # Migration path from the first, more verbose feed shape.
            iso_day = str(raw_date.get("iso") or "")
            date_meta = dict(raw_date)
        else:
            iso_day = str(raw_date or "")
            date_meta = {
                "iso": iso_day,
                "display": iso_day,
                "timezone": timezone_name,
            }
        if not iso_day:
            continue
        for run in group.get("runs") or []:
            if not isinstance(run, dict):
                continue
            run_at = run.get("runAt")
            if not run_at:
                raw_time = str(run.get("time") or "00:00:00")
                try:
                    local_dt = datetime.fromisoformat(f"{iso_day}T{raw_time}")
                    if response_tz is not None:
                        local_dt = local_dt.replace(tzinfo=response_tz)
                    run_at = local_dt.isoformat(timespec="seconds")
                except ValueError:
                    run_at = f"{iso_day}T{raw_time}"
            entries.append({
                "schemaVersion": SCHEMA_VERSION,
                "datasetId": dataset_id,
                "runId": run.get("runId"),
                "date": date_meta,
                "runAt": run_at,
                "status": run.get("status"),
                "insightCount": run.get(
                    "insightCount", len(run.get("insights") or [])
                ),
                "insights": run.get("insights") or [],
            })
    return entries


def merge_history_response(response: dict | None, entry: dict) -> tuple[dict, bool]:
    """Insert ``entry`` newest-first unless its public run is already present.

    The caller resolves duplicate execution IDs through the immutable run blob,
    then passes that original entry here. Matching date/time/status/content is
    therefore an idempotent retry even though technical IDs stay out of the
    public response.
    """
    existing = _entries_from_response(response)
    normalized = build_history_response(existing, str(entry.get("datasetId") or ""))
    candidate = build_history_response([entry]).get("history", [])
    candidate_run = candidate[0] if candidate else None
    duplicate = False
    if candidate_run:
        candidate_date = candidate_run["date"]
        candidate_value = candidate_run["runs"][0]
        duplicate = any(
            group.get("date") == candidate_date
            and candidate_value in (group.get("runs") or [])
            for group in normalized.get("history", [])
        )
    if duplicate:
        # Return changed=True when normalizing the old verbose schema so Azure
        # performs the one-time migration even though the run itself is known.
        return normalized, normalized != response
    merged = build_history_response(
        [entry, *existing], str(entry.get("datasetId") or "")
    )
    return merged, True


def write_local(state: dict, entry: dict) -> Path:
    """Persist the exact entry locally for audit/replay before Azure upload."""
    out = PROJECT_ROOT / state.get("output_folder", "outputs") / "history"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{entry['runId']}.json"
    path.write_text(
        json.dumps(entry, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    # Local runs get the same single-file API view as Azure. The immutable run
    # documents remain the source material if this projection is ever removed.
    entries = []
    for candidate in out.glob("*.json"):
        if candidate.name == "insight_history.json":
            continue
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            entries.append(value)
    response = build_history_response(entries, _dataset_id(state))
    (out / "insight_history.json").write_text(
        json.dumps(response, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return path


def build_and_write(
    state: dict,
    *,
    generated_at: datetime | None = None,
    run_id: str | None = None,
) -> tuple[dict[str, Any], Path] | None:
    """Build and locally persist a history entry for a completed report."""
    cfg = state.get("config", {}) or {}
    if not cfg.get("insight_history_enabled", True):
        return None
    entry = build_entry(state, generated_at=generated_at, run_id=run_id)
    if entry is None:
        return None
    return entry, write_local(state, entry)
