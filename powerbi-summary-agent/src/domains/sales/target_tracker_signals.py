"""Deterministic signals from the Target Tracker model (P5.2).

``target_tracker.build`` already computes every finding this report supports -
the run of days below target, the branch that missed in every period, the
catch-up requirement, the surplus burn rate, the department below target while
its parent is above. **This module turns those into ranked, scored signals; it
does not recompute any of them.** Recomputing would create the second copy that
is free to drift, which is the defect the repo's §1.3 note warns about.

Pure: no state, no I/O, no LLM. Every figure is copied or derived arithmetically
from the model.

Two rules this module exists to enforce:

* **No cause is ever stated.** The model holds sales and targets. It does not
  hold promotions, stock, staffing, weather or footfall, so a signal says
  *where* and *how large*, never *why* (Non-negotiable 1).
* **No prior-year comparison.** This dataset holds 2026 only. ``prior`` is never
  populated on a signal, and every signal carries an explicit
  ``comparison_label`` naming the target it was measured against, so nothing
  downstream can default to "vs the prior period" (Non-negotiable 2).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import spines

REPORT_ID = "target_tracker"
REPORT_NAME = "Target Tracker"

#: A finding must move at least this share of its scope's target to be worth a
#: card. Below it the gap is noise against the number it is measured against.
MIN_SCORE_PCT = 0.25

#: A run of days below target is only a story once it is a run, not a bad day.
MIN_RUN_DAYS = 2

_SEVERITY_CRITICAL_PCT = 5.0
_SEVERITY_WARNING_PCT = 1.0

_SCOPE_NAMES = {"day": "today", "wtd": "this week", "mtd": "this month", "ytd": "this year"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _pct(part: Any, whole: Any) -> float | None:
    part_val, whole_val = _num(part), _num(whole)
    if part_val is None or whole_val is None or whole_val == 0:
        return None
    return abs(part_val) / abs(whole_val) * 100.0


def _scope_name(scope: str) -> str:
    return _SCOPE_NAMES.get(scope, scope)


def story_key(finding: str, member: str, anchor: str) -> str:
    """Stable identity for suppression and for the published card id.

    Built from the spine's own ``novelty_key`` so the anchor rule lives in one
    place: keyed on the latest **targeted** day, not on the run date. Sales run
    ahead of targets on this model, so keying on the run date would mint a new
    story every morning for a position that has not moved.
    """
    components = spines.TargetVsActualSpine().novelty_key(
        {"member": member, "role": "branch" if member else "company", "finding": finding},
        {"anchor": anchor},
    )
    blob = json.dumps(components, sort_keys=True, separators=(",", ":"), default=str)
    return "tt:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _severity(impact_value: Any, score: float) -> str:
    value = _num(impact_value) or 0.0
    if value >= 0:
        return "positive"
    if score >= _SEVERITY_CRITICAL_PCT:
        return "critical"
    if score >= _SEVERITY_WARNING_PCT:
        return "warning"
    return "info"


def _signal(
    *,
    finding: str,
    member: str,
    segment: str,
    dimension: str,
    impact_value: float,
    base_target: Any,
    anchor: str,
    comparison_label: str,
    description: str,
    question: str,
    current: Any = None,
    target: Any = None,
    extra: dict | None = None,
) -> dict:
    score = _pct(impact_value, base_target) or 0.0
    return {
        "candidate_id": f"{finding}:{member or 'company'}",
        "story_key": story_key(finding, member, anchor),
        "kind": "business",
        "analysis_type": finding,
        "spine": spines.TargetVsActualSpine.kind,
        "report_id": REPORT_ID,
        "affected_segment": segment,
        "segment_members": [member] if member else [],
        "dimension": dimension,
        "metric": "Sales against target",
        "metric_family": "revenue",
        "direction": "increase" if impact_value >= 0 else "decrease",
        "impact_value": impact_value,
        "impact_share": _pct(impact_value, base_target),
        "score": score,
        "severity": _severity(impact_value, score),
        # `prior` is deliberately absent, not None-valued: there is no prior year
        # in this model, and the explicit label stops any consumer inferring one.
        "current": current,
        "target": target,
        "comparison_label": comparison_label,
        "description": description,
        "question": question,
        **(extra or {}),
    }


# --- detectors ----------------------------------------------------------------
def below_target_run(model: dict) -> list[dict]:
    """A run of consecutive days finishing below target."""
    run = model.get("run") or {}
    length = int(_num(run.get("length")) or 0)
    if length < MIN_RUN_DAYS:
        return []
    surplus = model.get("surplus") or {}
    given_back = abs(_num(surplus.get("given_back")) or 0.0)
    month_target = _num((model.get("periods") or {}).get("mtd", {}).get("target"))
    return [_signal(
        finding="target_below_run",
        member="",
        segment="Whole business",
        dimension="period",
        impact_value=-given_back,
        base_target=month_target,
        anchor=str(model.get("anchor") or ""),
        comparison_label="against the daily target",
        description=(
            f"Sales finished below target on {length} days in a row, from "
            f"{run.get('first')} to {run.get('last')}, giving back "
            f"{given_back:,.0f} in total."
        ),
        question=f"Which branches accounted for the shortfall over these {length} days?",
        extra={"run_length": length, "run_first": run.get("first"), "run_last": run.get("last")},
    )]


def branch_below_every_period(model: dict) -> list[dict]:
    """A branch below target in every period reported.

    This is the finding a live authored draft got wrong - it wrote "No branch
    missed today" while a branch sat at 91.3% of target. Detecting it in code,
    from the model, is what makes the claim checkable rather than trusted.
    """
    out: list[dict] = []
    for branch in model.get("branches") or []:
        measured = [
            (scope, _num((branch.get(scope) or {}).get("attainment")))
            for scope in ("day", "wtd", "mtd", "ytd")
            if isinstance(branch.get(scope), dict)
        ]
        measured = [(scope, value) for scope, value in measured if value is not None]
        if len(measured) < 2 or not all(value < 100 for _scope, value in measured):
            continue
        mtd = branch.get("mtd") or {}
        variance = _num(mtd.get("variance"))
        if variance is None:
            continue
        worst = min(measured, key=lambda pair: pair[1])
        detail = ", ".join(f"{_scope_name(s)} {v:.1f}%" for s, v in measured)
        out.append(_signal(
            finding="target_branch_below_every_period",
            member=str(branch.get("name") or ""),
            segment=str(branch.get("name") or ""),
            dimension="branch",
            impact_value=variance,
            base_target=_num(mtd.get("target")),
            anchor=str(model.get("anchor") or ""),
            comparison_label="against its target for this month so far",
            current=_num(mtd.get("actual")),
            target=_num(mtd.get("target")),
            description=(
                f"{branch.get('name')} is below target in every period reported - "
                f"{detail}. This month so far it is {abs(variance):,.0f} short."
            ),
            question=f"Which departments in {branch.get('name')} are furthest below target?",
            extra={
                "attainment_by_scope": {scope: value for scope, value in measured},
                "worst_scope": worst[0],
            },
        ))
    return out


def catch_up_out_of_reach(model: dict) -> list[dict]:
    """The sales still needed exceed the target set for the days remaining."""
    out: list[dict] = []
    for scope, key in (("month", "month_close"), ("week", "week_close")):
        close = model.get(key) or {}
        needed_vs_target = _num(close.get("needed_vs_target"))
        needed = _num(close.get("needed"))
        remaining = _num(close.get("remaining_target"))
        if needed_vs_target is None or needed is None or needed <= 0:
            continue
        if needed_vs_target <= 100:
            continue
        out.append(_signal(
            finding=f"target_catch_up_{scope}",
            member="",
            segment="Whole business",
            dimension="period",
            impact_value=-(needed - (remaining or 0.0)),
            base_target=remaining,
            anchor=str(model.get("anchor") or ""),
            comparison_label=f"against the remaining {scope} target",
            description=(
                f"To finish the {scope} on target, {needed:,.0f} is still needed against a "
                f"remaining target of {remaining:,.0f} - {needed_vs_target:.0f}% of what the "
                f"rest of the {scope} was set to deliver."
            ),
            question=f"Which branches carry the largest part of the remaining {scope} target?",
            extra={
                "needed": needed,
                "remaining_target": remaining,
                "needed_vs_target_pct": needed_vs_target,
            },
        ))
    return out


def surplus_exhausting(model: dict) -> list[dict]:
    """A month's surplus is being given back fast enough to run out before month end."""
    surplus = model.get("surplus") or {}
    exhausts_on = surplus.get("exhausts_on")
    days_until = _num(surplus.get("days_until_exhausted"))
    now = _num(surplus.get("now"))
    if not exhausts_on or days_until is None or now is None or now <= 0:
        return []
    run_days = max(1, int(_num(surplus.get("run_days")) or 1))
    per_day = abs(_num(surplus.get("given_back")) or 0.0) / run_days
    month_target = _num((model.get("periods") or {}).get("mtd", {}).get("target"))
    return [_signal(
        finding="target_surplus_exhausting",
        member="",
        segment="Whole business",
        dimension="period",
        impact_value=-abs(now),
        base_target=month_target,
        anchor=str(model.get("anchor") or ""),
        comparison_label="against the target for this month so far",
        description=(
            f"The month is {now:,.0f} ahead of target, but the last {run_days} days have been "
            f"giving back {per_day:,.0f} a day. At that rate the surplus is used up around "
            f"{exhausts_on}."
        ),
        question="Which branches are giving back the most against target?",
        extra={
            "exhausts_on": exhausts_on,
            "days_until_exhausted": days_until,
            "surplus_now": now,
            "given_back_per_day": per_day,
        },
    )]


def child_below_parent_above(model: dict) -> list[dict]:
    """A part missing target inside a whole that is hitting it.

    Two shapes, same idea: a department below while the business is above, and a
    section below while its own department is above. A headline attainment
    figure hides both completely.
    """
    out: list[dict] = []
    mtd = (model.get("periods") or {}).get("mtd", {})
    company = _num(mtd.get("attainment"))
    company_target = _num(mtd.get("target"))

    if company is not None and company >= 100:
        for dept in model.get("departments") or []:
            scope = dept.get("mtd") or {}
            attainment = _num(scope.get("attainment"))
            variance = _num(scope.get("variance"))
            if attainment is None or variance is None or attainment >= 100:
                continue
            out.append(_signal(
                finding="target_department_below_company_above",
                member=str(dept.get("name") or ""),
                segment=str(dept.get("name") or ""),
                dimension="department",
                impact_value=variance,
                base_target=company_target,
                anchor=str(model.get("anchor") or ""),
                comparison_label="against its target for this month so far",
                current=_num(scope.get("actual")),
                target=_num(scope.get("target")),
                description=(
                    f"{dept.get('name')} is at {attainment:.1f}% of its target for this month so far, "
                    f"{abs(variance):,.0f} short, while the business as a whole is at "
                    f"{company:.1f}%."
                ),
                question=f"Which sections inside {dept.get('name')} are furthest below target?",
                extra={
                    "attainment_pct": attainment,
                    "parent": "company",
                    "parent_attainment_pct": company,
                },
            ))

    by_department = {
        str(dept.get("name") or ""): _num((dept.get("mtd") or {}).get("attainment"))
        for dept in model.get("departments") or []
    }
    for section in model.get("sections") or []:
        parent = str(section.get("department") or "")
        parent_attainment = by_department.get(parent)
        scope = section.get("mtd") or {}
        attainment = _num(scope.get("attainment"))
        variance = _num(scope.get("variance"))
        if parent_attainment is None or parent_attainment < 100:
            continue
        if attainment is None or variance is None or attainment >= 100:
            continue
        out.append(_signal(
            finding="target_section_below_department_above",
            member=str(section.get("name") or ""),
            segment=str(section.get("name") or ""),
            dimension="section",
            impact_value=variance,
            base_target=company_target,
            anchor=str(model.get("anchor") or ""),
            comparison_label="against its target for this month so far",
            current=_num(scope.get("actual")),
            target=_num(scope.get("target")),
            description=(
                f"{section.get('name')} is at {attainment:.1f}% of its target for this month so far, "
                f"{abs(variance):,.0f} short, while {parent} overall is at "
                f"{parent_attainment:.1f}%."
            ),
            question=f"Which branches drive the shortfall in {section.get('name')}?",
            extra={
                "attainment_pct": attainment,
                "parent": parent,
                "parent_attainment_pct": parent_attainment,
            },
        ))
    return out


DETECTORS = (
    below_target_run,
    branch_below_every_period,
    catch_up_out_of_reach,
    surplus_exhausting,
    child_below_parent_above,
)


def detect(
    model: dict,
    *,
    limit: int | None = None,
    min_score_pct: float = MIN_SCORE_PCT,
) -> list[dict]:
    """Every supported finding, ranked by how much of its target it moves.

    Ranking is exposure-weighted by construction: the score is the gap as a share
    of the target it is measured against, so a small section missing badly cannot
    outrank a large one missing by a little. A completed month with a surplus and
    no run of misses legitimately produces very few signals - that is an honest
    result, not an empty one.
    """
    signals: list[dict] = []
    for detector in DETECTORS:
        signals.extend(detector(model) or [])
    signals = [s for s in signals if (s.get("score") or 0.0) >= float(min_score_pct)]
    signals.sort(key=lambda s: (-(s.get("score") or 0.0), str(s.get("candidate_id"))))
    if limit is not None:
        signals = signals[: max(0, int(limit))]
    for index, signal in enumerate(signals, start=1):
        signal["id"] = f"T{index}"
    return signals
