"""Immutable per-run history and newest-first feed for report summaries."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
DEFAULT_TIMEZONE = "Asia/Kolkata"
_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _when(state: dict, generated_at: datetime | None = None) -> datetime:
    cfg = state.get("config") or {}
    name = str(cfg.get("summary_history_timezone") or DEFAULT_TIMEZONE).strip()
    if not name or name.casefold() in {"auto", "naive"}:
        name = DEFAULT_TIMEZONE
    tz = ZoneInfo(name)
    if generated_at is None:
        return datetime.now(tz)
    if generated_at.tzinfo is None:
        return generated_at.replace(tzinfo=tz)
    return generated_at.astimezone(tz)


def _run_id(when: datetime, explicit: str | None = None) -> str:
    raw = (
        explicit
        or os.environ.get("SUMMARY_HISTORY_RUN_ID")
        or os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME")
    )
    if raw:
        safe = _SAFE.sub("-", str(raw)).strip("-._")
        if safe:
            return safe
    return when.strftime("%Y%m%dT%H%M%S%f%z")


def build_entry(
    state: dict,
    *,
    generated_at: datetime | None = None,
    run_id: str | None = None,
) -> dict[str, Any] | None:
    summary = state.get("fresh_summary")
    if not isinstance(summary, dict) or not summary.get("heading"):
        return None
    when = _when(state, generated_at)
    rid = _run_id(when, run_id)
    status = "completed"
    if summary.get("summary_type") == "no_new_perspective":
        status = "no_new_perspective"
    elif summary.get("summary_type") == "memory_unavailable":
        status = "failed"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "datasetId": str(state.get("dataset_id") or "unknown_dataset"),
        "runId": rid,
        "date": {
            "iso": when.date().isoformat(),
            "display": f"{when.day} {when.strftime('%B %Y')}",
            "timezone": str(when.tzinfo),
        },
        "runAt": when.isoformat(timespec="seconds"),
        "status": status,
        "summaryType": summary.get("summary_type"),
        "dataAsOf": summary.get("data_as_of"),
        "grain": summary.get("grain"),
        "freshnessStatus": summary.get("freshness_status"),
        "headline": summary.get("heading"),
        "paragraphs": list(summary.get("paragraphs") or []),
        "metrics": list(summary.get("metrics") or []),
        "sections": list(summary.get("sections") or []),
        "visual": summary.get("visual"),
    }


def blob_name(state: dict, entry: dict) -> str:
    cfg = state.get("config") or {}
    root = str(cfg.get("azure_blob_prefix") or "").strip("/")
    prefix = str(cfg.get("azure_blob_summary_history_prefix") or "summary-history").strip("/")
    dataset = _SAFE.sub("_", str(entry.get("datasetId") or "unknown_dataset"))
    year, month, day = str(entry["date"]["iso"]).split("-")
    return "/".join(part for part in (root, prefix, dataset, year, month, day, f"{entry['runId']}.json") if part)


def build_history_response(entries: list[dict]) -> dict:
    valid = [
        entry for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("date"), dict)
        and entry["date"].get("iso") and entry.get("runAt")
    ]
    valid.sort(key=lambda entry: str(entry.get("runAt")), reverse=True)
    groups = []
    by_date = {}
    for entry in valid:
        iso_day = str(entry["date"]["iso"])
        group = by_date.get(iso_day)
        if group is None:
            group = {"date": iso_day, "runs": []}
            by_date[iso_day] = group
            groups.append(group)
        try:
            time_value = datetime.fromisoformat(str(entry["runAt"])).strftime("%H:%M:%S")
        except ValueError:
            time_value = str(entry["runAt"]).split("T", 1)[-1][:8]
        group["runs"].append({
            "time": time_value,
            "status": entry.get("status"),
            "summaryType": entry.get("summaryType"),
            "dataAsOf": entry.get("dataAsOf"),
            "grain": entry.get("grain"),
            "freshnessStatus": entry.get("freshnessStatus"),
            "headline": entry.get("headline"),
            "paragraphs": entry.get("paragraphs") or [],
            "metrics": entry.get("metrics") or [],
            "sections": entry.get("sections") or [],
            "visual": entry.get("visual"),
        })
    timezone_name = (
        str(valid[0].get("date", {}).get("timezone") or DEFAULT_TIMEZONE)
        if valid else DEFAULT_TIMEZONE
    )
    return {"timezone": timezone_name, "history": groups}


def _entries_from_response(response: dict | None) -> list[dict]:
    if not isinstance(response, dict):
        return []
    timezone_name = str(response.get("timezone") or DEFAULT_TIMEZONE)
    entries = []
    for group in response.get("history") or []:
        if not isinstance(group, dict):
            continue
        iso_day = str(group.get("date") or "")
        for run in group.get("runs") or []:
            if not isinstance(run, dict):
                continue
            raw_time = str(run.get("time") or "00:00:00")
            entries.append({
                "date": {"iso": iso_day, "timezone": timezone_name},
                "runAt": f"{iso_day}T{raw_time}",
                **{key: run.get(key) for key in (
                    "status", "summaryType", "dataAsOf", "grain", "freshnessStatus",
                    "headline", "paragraphs", "metrics", "sections", "visual"
                )},
            })
    return entries


def merge_history_response(response: dict | None, entry: dict) -> tuple[dict, bool]:
    existing = _entries_from_response(response)
    candidate = build_history_response([entry])
    candidate_group = (candidate.get("history") or [None])[0]
    candidate_run = (candidate_group.get("runs") or [None])[0] if candidate_group else None
    duplicate = bool(candidate_group and candidate_run and any(
        group.get("date") == candidate_group.get("date")
        and candidate_run in (group.get("runs") or [])
        for group in build_history_response(existing).get("history", [])
    ))
    normalized = build_history_response(existing)
    if duplicate:
        return normalized, normalized != response
    return build_history_response([entry, *existing]), True


def write_local(state: dict, entry: dict) -> tuple[Path, Path]:
    out = PROJECT_ROOT / state.get("output_folder", "outputs")
    immutable = out / "summary-history"
    immutable.mkdir(parents=True, exist_ok=True)
    path = immutable / f"{entry['runId']}.json"
    if not path.exists():
        path.write_text(json.dumps(entry, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    entries = []
    for candidate in immutable.glob("*.json"):
        try:
            value = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            entries.append(value)
    feed = out / "summary_history.json"
    feed.write_text(json.dumps(build_history_response(entries), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path, feed


def build_and_write(
    state: dict,
    *,
    generated_at: datetime | None = None,
    run_id: str | None = None,
) -> tuple[dict, Path, Path] | None:
    cfg = state.get("config") or {}
    if not cfg.get("summary_history_enabled", True):
        return None
    entry = build_entry(state, generated_at=generated_at, run_id=run_id)
    if entry is None:
        return None
    immutable, feed = write_local(state, entry)
    return entry, immutable, feed
