"""Cross-run novelty for single-snapshot inventory reports (Ageing, SKU Overview).

Wraps `kernel.state_novelty` - a persisting-state novelty engine already built
for exactly this need (brief WP6) but never wired into production before this.
A single stock position has no period to anchor novelty on the way
`insight_memory.story_key` does; state_novelty instead tracks each finding's
STATE across runs and reports only an onset, a clearance, a material
escalation, or a duration milestone - never a flat repeat of yesterday's
wording.

What gets memory-filtered, and what does not
----------------------------------------------
The deterministic report (report_*.json, the dashboard, report_summary.md)
ALWAYS shows every current finding - a stock position page that hid a
still-true fact because "we said it yesterday" would be dishonest. Memory
filtering applies ONLY to the two places repetition is actually a cost: the
KPI alert feed, and the investigation budget (spending a live query narrating
an unchanged finding every day is waste, and it is the same budget a
genuinely new problem needs).

Clearances are not free-standing findings
------------------------------------------
A member can be flagged today, absent from tomorrow's `detect()` output (it
quietly dropped below threshold), and never appear in `filter_signals` again -
there is no live signal to attach a "cleared" verdict to. `sweep_cleared`
closes that gap: it walks every stored record that was NOT touched this run
and, only for one whose last known state was "flagged", synthesises a
clearance finding from the record itself. A record already at rest
("within_policy") is left alone rather than re-checked forever, or the store
would grow without bound.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ...kernel import scoping, state_novelty

FLAGGED = "flagged"
WITHIN_POLICY = "within_policy"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def store_path(out_dir: str | Path, report_id: str, dataset_id: str) -> Path:
    root = Path(out_dir) / ".runtime" / "snapshot_memory"
    dataset_segment = scoping.safe_segment(dataset_id, "unknown_dataset")
    path, _status = scoping.scoped_store(root, dataset_segment, report_id=report_id)
    return path


def load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path: Path, records: dict) -> None:
    """Atomic write - a truncated file from an interrupted run must never be
    read back as "no history", which would re-open every cleared finding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _finding_state(signal: dict) -> dict:
    """A finding's condition, in the shape `state_novelty.judge` expects.

    `state` is coarse on purpose ("flagged"/"within_policy"): state_novelty's
    own escalation test already reads the finer-grained distance/exposure
    numbers, so folding that detail into the state label too would just be
    two ways of saying the same thing.
    """
    severity = str(signal.get("severity") or "info")
    distance = signal.get("rate_gap_pct_points")
    if distance is None:
        distance = signal.get("impact_share")
    return {
        "state": FLAGGED if severity in ("critical", "warning") else WITHIN_POLICY,
        "distance": _num(distance),
        "exposure": _num(signal.get("impact_value")),
    }


def identity_key(report_id: str, kind: str, role: str, member: str) -> str:
    """Anchor-independent identity.

    Deliberately NOT `story_key`: that includes the as-at date so a re-run on
    the same day is not a new story, which means the same ongoing hotspot
    mints a fresh key every NEW day too - correct for KPI-card id stability,
    wrong for novelty, where it would mean nothing is ever recognised as "the
    same problem, still here".
    """
    return state_novelty.state_key({
        "report": report_id, "kind": kind, "role": role,
        "member": str(member or "").strip().casefold(),
    })


def _describe_clearance(record: dict) -> str:
    member = record.get("member") or "This finding"
    role = record.get("role") or ""
    days = int(_num(record.get("days_in_state")) or 0)
    where = f" ({role})" if role else ""
    return (f"{member}{where} is no longer flagged. It was reported for "
           f"{days} day(s) before clearing.")


def filter_signals(signals: list[dict], *, report_id: str, out_dir: str | Path,
                   dataset_id: str, observed_at: str,
                   milestones=None) -> dict:
    """Which findings are worth alerting/investigating today.

    Returns a dict with:
      * ``reportable`` - today's signals worth surfacing (onset/escalated/
        milestone), each carrying a ``novelty`` block explaining why;
      * ``cleared`` - synthetic good-news findings for members that dropped
        out of today's scan while still flagged in the store;
      * ``path`` / ``records`` - ready for :func:`commit`, which the caller
        invokes only once the run has actually produced a report (the same
        "observed vs reported" caution `insight_memory.commit_run` uses).
    """
    path = store_path(out_dir, report_id, dataset_id)
    stored = load(path)
    reportable: list[dict] = []
    cleared: list[dict] = []
    updated: dict[str, dict] = dict(stored)
    seen: set[str] = set()
    kwargs = {} if milestones is None else {"milestones": milestones}

    for signal in signals:
        kind = str(signal.get("analysis_type") or "")
        role = str(signal.get("dimension") or "")
        member = str(signal.get("affected_segment") or "")
        key = identity_key(report_id, kind, role, member)
        seen.add(key)
        current = _finding_state(signal)
        current["observed_at"] = observed_at
        prior_record = stored.get(key)
        verdict = state_novelty.judge(prior_record, current, observed_at=observed_at, **kwargs)
        record = state_novelty.advance(prior_record, current, verdict, observed_at=observed_at)
        record.update({"report_id": report_id, "kind": kind, "role": role, "member": member})
        updated[key] = record
        signal["novelty"] = {"report": verdict.report, "reason": verdict.reason,
                             "kind": verdict.kind, "days_in_state": verdict.days_in_state}
        if verdict.report:
            reportable.append(signal)

    for key, record in stored.items():
        if key in seen or record.get("state") != FLAGGED:
            continue
        current = {"state": WITHIN_POLICY, "distance": None, "exposure": None,
                  "observed_at": observed_at}
        verdict = state_novelty.judge(record, current, observed_at=observed_at, **kwargs)
        if not verdict.report:
            continue
        new_record = state_novelty.advance(record, current, verdict, observed_at=observed_at)
        new_record.update({"report_id": record.get("report_id", report_id),
                           "kind": record.get("kind"), "role": record.get("role"),
                           "member": record.get("member")})
        updated[key] = new_record
        cleared.append({
            "candidate_id": f"cleared:{record.get('kind')}:{record.get('role')}:{record.get('member')}",
            "report_id": report_id, "analysis_type": "snapshot_cleared",
            "dimension": record.get("role"), "affected_segment": record.get("member"),
            "severity": "positive",
            "comparison_label": "against the position last reported",
            "description": _describe_clearance(record),
            "impact_value": _num(record.get("exposure")) or 0.0,
            "impact_share": None,
            "score": 50.0,
            "novelty": {"report": True, "reason": verdict.reason, "kind": verdict.kind,
                       "days_in_state": verdict.days_in_state},
        })

    return {
        "path": path, "records": updated,
        "reportable": reportable, "cleared": cleared,
        "stats": {"detected": len(signals), "reportable": len(reportable),
                  "suppressed": len(signals) - len(reportable), "cleared": len(cleared),
                  "store_path": str(path)},
    }


def commit(memory_result: dict) -> None:
    save(memory_result["path"], memory_result["records"])
