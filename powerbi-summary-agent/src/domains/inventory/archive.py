"""The pipeline's own snapshot history, because the semantic model has none.

Why this exists
---------------
`docs/phase5-inventory-deferred.md` blocks day-over-day inventory alerting on
two preconditions. Re-checked live on 2026-08-21, one still fails and one
passes:

* **more than one retained snapshot: FAILING.** `UPDATED_ON` holds exactly one
  distinct value. The semantic model *replaces* yesterday's stock position with
  today's rather than retaining both.
* **durable item identity: PASSING.** `locsku` is `LOC_CODE + sku_code`, a
  business key rather than a regenerated surrogate.

Waiting for Power BI to retain history would block the feature indefinitely, and
it does not have to: the pipeline can keep its own. Each run writes a dated copy
of its scan, and the next run compares against the most recent one.

The key is the RUN date, never the model's as-at stamp
------------------------------------------------------
This is the load-bearing decision, and it was made against measured evidence
rather than taste. On 2026-08-21 the model still stamped `UPDATED_ON` as
2026-08-19 - exactly the stamp the approved reference design carries - while
reading materially different data:

===============================  ==========  ==========
                                 reference       live
===============================  ==========  ==========
scored Loc-SKUs                     120,897     139,732
Inventory Health Score                 58.5        43.5
===============================  ==========  ==========

Two things had happened under one unchanged stamp. Warehouse scoring landed, so
the scored population grew from stores-only to every Location; and the
stores-only position itself fell from 58.5 to 48.8. The dataset had refreshed
six times in between.

So the as-at stamp does not identify a business position. Keying the archive on
it would have silently overwritten one position with a different one under the
same filename, and a later comparison would have reported the difference between
two loads of "the same day" as a day's trading movement. Keying on the run date
keeps every position, and :func:`compare_window` then refuses to state a
movement unless the as-at stamp actually advanced between the two files.

Nothing here fabricates. When there is no usable prior - first run, an archive
older than the configured window, or an unchanged as-at - the caller is told
which, in words the page can print, and the comparison is omitted.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any, Iterable

#: `scan_YYYY-MM-DD.json`. Anchored at both ends so a partial or renamed file
#: cannot be mistaken for an archived position.
FILENAME = re.compile(r"^scan_(\d{4}-\d{2}-\d{2})\.json$")

#: Why a comparison could not be made. These are states, not errors: a first run
#: has no prior and that is normal. Each maps to a sentence the page prints.
NO_PRIOR = "no_prior"
PRIOR_TOO_OLD = "prior_too_old"
AS_AT_UNCHANGED = "as_at_unchanged"
AS_AT_WENT_BACKWARDS = "as_at_went_backwards"
COMPARABLE = "comparable"

#: What the page is allowed to say for each state. Written out rather than
#: assembled, because the honest phrasing is the point: an absent comparison
#: must read as "not known", never as "no change".
REASON_TEXT: dict[str, str] = {
    NO_PRIOR: (
        "This is the first stock position kept for this report, so nothing is "
        "compared against an earlier day. Figures describe today only."),
    PRIOR_TOO_OLD: (
        "The most recent stock position kept is older than the comparison "
        "window, so figures describe today only rather than being compared "
        "against a stale position."),
    AS_AT_UNCHANGED: (
        "The dashboard still reports the same position date as the last copy "
        "kept, so there is no movement to report. Figures describe that "
        "position only."),
    AS_AT_WENT_BACKWARDS: (
        "The dashboard reports an earlier position date than the last copy "
        "kept, so the two are not compared. Figures describe today only."),
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_at(scan: dict) -> str:
    """The model's own as-at stamp, as recorded by the scan's provenance.

    Falls back to reading the snapshot row so an archive written before
    provenance existed is still usable rather than silently unreadable.
    """
    provenance = scan.get("provenance") or {}
    stamp = str(provenance.get("as_at") or "").strip()
    if stamp:
        return stamp.split("T")[0]
    header = (scan.get("snapshot") or [{}])[0] or {}
    for key, value in header.items():
        if str(key).strip("[]").split("[")[-1].strip("]").lower() == "as_at":
            return str(value or "").split("T")[0]
    return ""


def archive_dir(output_dir: str | Path, cfg: dict | None = None) -> Path:
    cfg = cfg or {}
    name = str(cfg.get("inventory_archive_dir", "archive") or "archive")
    return Path(output_dir) / name


def write(scan: dict, output_dir: str | Path, cfg: dict | None = None,
          *, run_date: _dt.date | None = None, log=None) -> Path | None:
    """Keep a dated copy of this run's scan. Returns the path, or None if off.

    The filename carries the run date. A second run on the same day overwrites
    that day's file, which is correct: the archive holds one position per day,
    the latest one seen.
    """
    cfg = cfg or {}
    if not cfg.get("inventory_archive_enabled", True):
        if log:
            log("  archive: disabled by config")
        return None
    day = (run_date or _dt.date.today()).isoformat()
    directory = archive_dir(output_dir, cfg)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"scan_{day}.json"
    path.write_text(json.dumps(scan, indent=2, default=str), encoding="utf-8")
    if log:
        log(f"  archive: kept {path.name} (as at {_as_at(scan) or 'unknown'})")
    return path


def archived_runs(output_dir: str | Path, cfg: dict | None = None) -> list[tuple[_dt.date, Path]]:
    """Every kept position, oldest first. Anything unparseable is ignored."""
    directory = archive_dir(output_dir, cfg)
    if not directory.is_dir():
        return []
    found: list[tuple[_dt.date, Path]] = []
    for path in directory.iterdir():
        match = FILENAME.match(path.name)
        if not match:
            continue
        try:
            found.append((_dt.date.fromisoformat(match.group(1)), path))
        except ValueError:
            continue
    found.sort(key=lambda item: item[0])
    return found


def latest_prior(output_dir: str | Path, cfg: dict | None = None,
                 *, run_date: _dt.date | None = None) -> tuple[_dt.date, dict] | None:
    """The most recent kept position from *before* today. None if there is none.

    Excluding today matters: :func:`write` is called before the comparison, so
    without this the run would compare today against itself and report no change
    every single day.
    """
    today = run_date or _dt.date.today()
    for day, path in reversed(archived_runs(output_dir, cfg)):
        if day >= today:
            continue
        try:
            return day, _read(path)
        except (OSError, json.JSONDecodeError):
            continue  # a truncated file is skipped, not fatal
    return None


def compare_window(current: dict, output_dir: str | Path, cfg: dict | None = None,
                   *, run_date: _dt.date | None = None) -> dict:
    """Decide whether today may be compared against a kept position, and say why.

    Returns a verdict the page and the detectors both read. ``comparable`` is
    True only when a prior exists, is inside the configured window, and the
    model's as-at stamp genuinely advanced - the three ways a comparison can be
    dishonest, each refused separately so the reason can be printed.
    """
    cfg = cfg or {}
    today = run_date or _dt.date.today()
    max_age = int(cfg.get("inventory_archive_max_age_days", 14) or 14)
    current_as_at = _as_at(current)

    found = latest_prior(output_dir, cfg, run_date=today)
    if not found:
        return _verdict(NO_PRIOR, current_as_at)

    prior_day, prior_scan = found
    age = (today - prior_day).days
    prior_as_at = _as_at(prior_scan)

    if age > max_age:
        return _verdict(PRIOR_TOO_OLD, current_as_at, prior_as_at=prior_as_at,
                        prior_run_date=prior_day.isoformat(), age_days=age)
    if not current_as_at or not prior_as_at or current_as_at == prior_as_at:
        return _verdict(AS_AT_UNCHANGED, current_as_at, prior_as_at=prior_as_at,
                        prior_run_date=prior_day.isoformat(), age_days=age)
    if current_as_at < prior_as_at:
        return _verdict(AS_AT_WENT_BACKWARDS, current_as_at, prior_as_at=prior_as_at,
                        prior_run_date=prior_day.isoformat(), age_days=age)

    verdict = _verdict(COMPARABLE, current_as_at, prior_as_at=prior_as_at,
                       prior_run_date=prior_day.isoformat(), age_days=age)
    verdict["comparable"] = True
    verdict["prior"] = prior_scan
    verdict["label"] = f"since {prior_as_at}"
    verdict["reason_text"] = ""
    return verdict


def _verdict(reason: str, as_at: str, **extra: Any) -> dict:
    out = {
        "comparable": False,
        "reason": reason,
        "reason_text": REASON_TEXT.get(reason, ""),
        "as_at": as_at,
        "prior_as_at": None,
        "prior_run_date": None,
        "age_days": None,
        "prior": None,
        "label": None,
    }
    out.update(extra)
    return out


def movement(current: dict, prior: dict, path: Iterable[str],
             *, key: str) -> dict | None:
    """One measure's movement between two kept positions, or None.

    ``path`` names the scan block and ``key`` the field inside its first row -
    the shape every single-row block in the scan uses. Returns None rather than
    zero when either side is missing, because "not measurable" and "did not
    move" are different answers and only one of them is a finding.
    """
    def _pick(scan: dict) -> float | None:
        rows = scan
        for step in path:
            rows = (rows or {}).get(step) if isinstance(rows, dict) else None
        row = (rows or [{}])[0] if isinstance(rows, list) and rows else {}
        for name, value in (row or {}).items():
            cleaned = str(name).strip("[]").split("[")[-1].strip("]").lower()
            if cleaned == key.lower():
                return float(value) if isinstance(value, (int, float)) else None
        return None

    now, before = _pick(current), _pick(prior)
    if now is None or before is None:
        return None
    change = now - before
    return {
        "current": now,
        "prior": before,
        "change": change,
        "change_pct": (change / abs(before) * 100.0) if before else None,
        "direction": "up" if change > 0 else ("down" if change < 0 else "flat"),
    }
