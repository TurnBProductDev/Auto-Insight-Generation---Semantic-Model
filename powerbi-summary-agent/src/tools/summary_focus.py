"""Deterministic two-stage daily-focus selection for the summary branch.

This module owns the editorial decision "which single business focus should
today's summary deep-dive explain?". It is deliberately summary-only: it imports
no insight module and reads no insight state. It also owns the shared date and
material-change helpers so ``summary_novelty_filter`` (legacy and focus modes)
can reuse them without importing ``summary_period_resolver``.

Selection is two-stage and bounded so no role can win merely by returning more
members:

* Stage 1 - pick a role (dimension_role) by ``role_staleness + role_materiality``
  where role_materiality is the *mean* of the top-3 normalized member movements.
* Stage 2 - pick the member within that role by a weighted blend of materiality,
  staleness, movement and evidence completeness.

Suppression (focus cooldown + same-dimension gap) is applied before the role is
chosen; same-day recovery of an already-delivered focus bypasses suppression but
never bypasses evidence/scope validity.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from . import summary_memory


DEFAULT_TIMEZONE = "Asia/Kolkata"
_LENS_COMPLETENESS = {"complete": 1.0, "partial": 0.5, "invalid": 0.0}
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


# --- shared helpers (relocated so both modes reuse one copy) -----------------
def _as_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _materially_changed(candidate: dict, stored: dict, threshold_pct: float) -> bool:
    old_direction = str(stored.get("direction") or stored.get("last_direction") or "")
    new_direction = str(candidate.get("direction") or "")
    if old_direction and new_direction and old_direction != new_direction:
        return True
    old = stored.get("observation_value")
    if old is None:
        old = stored.get("last_observation")
    new = candidate.get("observation_value")
    if not (_number(old) and _number(new)):
        return False
    old, new = float(old), float(new)
    if old == new:
        return False
    if old == 0:
        return new != 0
    return abs(new - old) / abs(old) * 100.0 >= max(0.0, float(threshold_pct))


def focus_today(state: dict) -> date:
    """Resolve 'today' for focus rotation at day granularity.

    ``summary_now_override`` wins for deterministic offline tests. Otherwise the
    configured ``summary_focus_timezone`` is used; an unsupported timezone is
    rejected loudly rather than silently falling back to a naive clock.
    """
    raw = state.get("summary_now_override") or (state.get("config", {}) or {}).get("summary_now_override")
    if raw:
        parsed = _as_date(str(raw))
        if parsed:
            return parsed
    configured = str(
        state.get("summary_focus_timezone")
        or (state.get("config", {}) or {}).get("summary_focus_timezone")
        or ""
    ).strip()
    if not configured or configured.casefold() in {"auto", "naive", "local", "default"}:
        name = DEFAULT_TIMEZONE
    else:
        name = configured
    try:
        tz = ZoneInfo(name)
    except Exception as exc:  # noqa: BLE001 - configuration error must be loud
        raise ValueError(
            f"summary_focus_timezone {configured!r} is not a supported IANA timezone name"
        ) from exc
    return datetime.now(tz).date()


# --- scoring internals -------------------------------------------------------
def _role_last_reported(focus_records: dict, role: str) -> date | None:
    latest = None
    for record in (focus_records or {}).values():
        if str(record.get("dimension_role") or "") != str(role):
            continue
        when = _as_date(record.get("last_reported"))
        if when and (latest is None or when > latest):
            latest = when
    return latest


def _staleness(last: date | None, today: date, cooldown_days: int) -> float:
    if last is None:
        return 1.0
    window = max(1, int(cooldown_days))
    return min(1.0, max(0.0, (today - last).days) / window)


def _total_change(candidates: list[dict]) -> dict[str, float]:
    """Reconciled per-family total change from the overall/grand-total candidate."""
    totals: dict[str, float] = {}
    for candidate in candidates:
        if (
            candidate.get("dimension_role") == "overall"
            and candidate.get("candidate_kind") == "broad"
            and candidate.get("coverage") == "complete"
        ):
            value = candidate.get("observation_value")
            family = str(candidate.get("metric_family") or "")
            if _number(value) and family and abs(float(value)) > abs(totals.get(family, 0.0)):
                totals[family] = abs(float(value))
    return totals


def _materiality(candidate: dict, movement_norm: float, totals: dict[str, float]) -> float:
    """Share of the reconciled total change when it is known, else a bounded proxy."""
    if str(candidate.get("coverage")) == "complete":
        total = totals.get(str(candidate.get("metric_family") or ""))
        value = candidate.get("observation_value")
        if total and _number(value):
            return min(1.0, abs(float(value)) / total)
    return movement_norm


def _impact_share_pct(candidate: dict, totals: dict[str, float]) -> float | None:
    """Percent of the reconciled family total change this candidate accounts for."""
    total = totals.get(str(candidate.get("metric_family") or ""))
    value = candidate.get("observation_value")
    if total and _number(value):
        # Contributions can legitimately exceed 100% when other members offset
        # them, so keep the real share instead of silently clipping the audit.
        return abs(float(value)) / total * 100.0
    return None


def _sentiment(candidate: dict | None) -> str | None:
    """Mutable opportunity/risk tone from current direction (never in focus_key)."""
    if not candidate:
        return None
    direction = str(candidate.get("direction") or "").strip().casefold()
    if direction in {"increase", "increasing", "growth", "up", "positive"}:
        return "opportunity"
    if direction in {"decrease", "decreasing", "decline", "down", "negative"}:
        return "risk"
    if direction in {"flat", "mixed", "stable", "unchanged"}:
        return "mixed"
    value = candidate.get("observation_value")
    if not _number(value) or float(value) == 0.0:
        return "mixed"
    return "opportunity" if float(value) > 0 else "risk"


def _scheduled_roles(state: dict, today: date) -> set[str]:
    """Roles softly preferred today by the optional weekday schedule.

    Accepts either ``{weekday: role | [roles]}`` or the inverse
    ``{role: [weekdays]}``. Empty/missing schedule means no preference.
    """
    schedule = (
        state.get("summary_focus_schedule")
        or (state.get("config", {}) or {}).get("summary_focus_schedule")
        or {}
    )
    if not isinstance(schedule, dict) or not schedule:
        return set()
    weekday = _WEEKDAYS[today.weekday()]
    normalized = {str(key).strip().casefold(): value for key, value in schedule.items()}

    def values(item) -> set[str]:
        raw = [item] if isinstance(item, str) else item if isinstance(item, (list, tuple, set)) else []
        return {str(value).strip().casefold() for value in raw if str(value).strip()}

    # Direct form: {weekday: role | [roles]}. Keys are case-insensitive.
    if weekday in normalized:
        return values(normalized[weekday])

    # Inverse form: {role: weekday | [weekdays]}. A single weekday string is
    # accepted as well as a list; both shapes are documented as equivalent.
    return {
        role
        for role, days in normalized.items()
        if role not in _WEEKDAYS and weekday in values(days)
    }


def _valid_pool(candidates: list[dict]) -> list[dict]:
    """Selectable focus candidates: valid, scoped, and not a redundant aggregate.

    A broad ``*_overview`` candidate for a member-bearing dimension is dropped
    when its members are present: its observation is the SUM of the members, so
    letting it compete would let the aggregate always beat any single member and
    the deep dive could not member-scope. Genuine standalone broad foci
    (overall/period/volume, and any dimension with no members) are kept.
    """
    valid = [
        candidate
        for candidate in candidates
        if candidate.get("focus_key") and str(candidate.get("coverage")) != "invalid"
    ]
    member_roles = {
        c.get("dimension_role")
        for c in valid
        if c.get("candidate_kind") == "member"
    }
    return [
        candidate
        for candidate in valid
        if not (
            candidate.get("candidate_kind") == "broad"
            and candidate.get("dimension_role") in member_roles
        )
    ]


def _norm(value) -> str:
    return summary_memory._norm_text(value)


def _candidate_entities(candidate: dict) -> set[str]:
    """The business entities a candidate would feature (segment + its peers)."""
    entities = {_norm(candidate.get("segment"))}
    for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
        if str(fact.get("subject_role")) in {"focus", "peer"}:
            entities.add(_norm(fact.get("subject")))
    return {entity for entity in entities if entity}


def _recent_entities(entry: dict) -> set[str]:
    """The entities a past delivery already featured prominently."""
    keys = ("segment", "top_pos_contributor", "top_neg_contributor", "leading_location")
    return {_norm(entry.get(key)) for key in keys} - {""}


def _overlap_score(candidate: dict, entry: dict) -> float:
    """Fraction of a candidate's featured entities already featured recently.

    An exact re-feature of the candidate's own segment scores 1.0 (making it a
    guaranteed suppression above any reasonable threshold), so "don't headline
    what we just explained as a driver" is captured even when the peer sets
    differ.
    """
    segment = _norm(candidate.get("segment"))
    recent = _recent_entities(entry)
    if segment and segment in recent:
        return 1.0
    entities = _candidate_entities(candidate)
    if not entities:
        return 0.0
    return len(entities & recent) / len(entities)


def _within_days(when: Any, today: date, window: int) -> bool:
    parsed = _as_date(when)
    return parsed is not None and 0 <= (today - parsed).days <= max(0, int(window))


def select_focus(
    state: dict,
    candidates: list[dict],
    store: dict,
    memory_status: str,
) -> dict:
    """Return the selected focus and a full, auditable selection trace."""
    today = focus_today(state)
    focus_records = store.get("focus_records", {}) or {}
    daily_plan = store.get("daily_plan", {}) or {}
    cooldown_days = int(state.get("summary_focus_cooldown_days", 14))
    gap_days = int(state.get("summary_focus_same_dimension_gap_days", 2))

    pool = _valid_pool(candidates)
    audit: dict = {
        "today": today.isoformat(),
        "valid_candidates": len(pool),
        "detected": len(candidates),
    }

    # --- period + summary-type classification (never used for suppression) ---
    period = state.get("summary_period_context") or {}
    current_watermark = _as_date(period.get("data_as_of"))
    prior_watermark = _as_date(store.get("watermark"))
    data_advanced = bool(current_watermark and (not prior_watermark or current_watermark > prior_watermark))
    anchor = period.get("period_anchor")
    anchor_changed = bool(anchor and anchor != store.get("period_anchor"))

    def _finish(selected: dict | None, reason: str, recovered: bool = False) -> dict:
        if selected is None:
            summary_type = "no_new_perspective"
        elif data_advanced or anchor_changed:
            summary_type = "new_data"
        else:
            summary_type = "new_perspective"
        sentiment = _sentiment(selected)
        audit.update({
            "reason": reason,
            "summary_type": summary_type,
            "recovered_same_day": recovered,
            "selected_focus_key": selected.get("focus_key") if selected else None,
            "selected_candidate_id": selected.get("candidate_id") if selected else None,
            "selected_role": selected.get("dimension_role") if selected else None,
            "selected_segment": selected.get("segment") if selected else None,
            "sentiment": sentiment,
            "data_advanced": data_advanced,
            "anchor_changed": anchor_changed,
        })
        return {
            "selected": selected,
            "summary_type": summary_type,
            "sentiment": sentiment,
            "audit": audit,
        }

    if not pool:
        return _finish(None, "no valid focus candidate")

    by_focus = {}
    for candidate in pool:
        by_focus.setdefault(candidate["focus_key"], candidate)

    # --- 2. same-day recovery (pin): re-deliver today's focus if still valid --
    plan = daily_plan.get(today.isoformat())
    if isinstance(plan, dict):
        pinned = by_focus.get(str(plan.get("focus_key") or ""))
        if pinned is not None:
            return _finish(pinned, "same_day_recovery", recovered=True)

    totals = _total_change(candidates)
    blocked_focus = summary_memory.focus_suppressed(
        focus_records, state.get("summary_focus_policy", "cooldown"), cooldown_days, today
    )
    recent_focus = store.get("recent_focus", []) or []
    overlap_threshold = float(state.get("summary_focus_fact_overlap_threshold", 0.6) or 0.0)
    overlap_window = int(state.get("summary_focus_overlap_window_days", 7))
    recent_window = [
        entry for entry in recent_focus
        if _within_days(entry.get("reported_at"), today, overlap_window)
    ] if overlap_threshold > 0 else []

    def _partition_overlap(stage_pool: list[dict]) -> tuple[list[dict], list[dict]]:
        """Split a pool into fresh and recently featured candidates."""
        if not recent_window:
            return list(stage_pool), []
        novel, repeated = [], []
        for candidate in stage_pool:
            overlap = max(
                (_overlap_score(candidate, entry) for entry in recent_window),
                default=0.0,
            )
            (repeated if overlap >= overlap_threshold else novel).append(candidate)
        return novel, repeated

    def _choose(
        stage_pool: list[dict],
        audit_prefix: str = "",
        apply_schedule: bool = True,
    ) -> dict:
        """Apply the bounded role/member scoring to an already-gated pool."""
        max_abs = max(
            (abs(float(c.get("observation_value") or 0.0)) for c in stage_pool),
            default=0.0,
        ) or 1.0

        def movement_norm(candidate: dict) -> float:
            return min(1.0, abs(float(candidate.get("observation_value") or 0.0)) / max_abs)

        roles: dict[str, list[dict]] = {}
        for candidate in stage_pool:
            roles.setdefault(str(candidate.get("dimension_role") or "overall"), []).append(candidate)

        # Weekday schedule is a SOFT prior (R2): it nudges role ranking but a
        # strongly material or stale role still wins.
        scheduled = _scheduled_roles(state, today) if apply_schedule else set()
        schedule_weight = max(0.0, float(state.get("summary_focus_schedule_weight", 0.5) or 0.0))
        audit[f"{audit_prefix}scheduled_roles"] = sorted(scheduled)
        audit[f"{audit_prefix}schedule_applied"] = bool(apply_schedule and scheduled and schedule_weight)

        role_scores: dict[str, dict] = {}
        for role, role_candidates in roles.items():
            members = [c for c in role_candidates if c.get("candidate_kind") == "member"] or role_candidates
            movements = sorted((movement_norm(member) for member in members), reverse=True)[:3]
            role_materiality = sum(movements) / len(movements) if movements else 0.0
            role_staleness = _staleness(_role_last_reported(focus_records, role), today, cooldown_days)
            schedule_affinity = schedule_weight if role.casefold() in scheduled else 0.0
            role_scores[role] = {
                "score": role_staleness + role_materiality + schedule_affinity,
                "role_staleness": role_staleness,
                "role_materiality": role_materiality,
                "schedule_affinity": schedule_affinity,
                "members": len(members),
            }
        audit[f"{audit_prefix}role_scores"] = role_scores
        chosen_role = max(role_scores, key=lambda role: (role_scores[role]["score"], role))

        member_pool = [
            candidate for candidate in roles[chosen_role]
            if candidate.get("candidate_kind") == "member"
        ] or roles[chosen_role]

        def member_score(candidate: dict) -> float:
            movement = movement_norm(candidate)
            materiality = _materiality(candidate, movement, totals)
            stored = focus_records.get(candidate["focus_key"], {})
            last = _as_date(stored.get("last_reported"))
            staleness = _staleness(last, today, cooldown_days)
            completeness = _LENS_COMPLETENESS.get(str(candidate.get("coverage")), 0.5)
            return 0.40 * materiality + 0.30 * staleness + 0.20 * movement + 0.10 * completeness

        ranked = sorted(
            member_pool,
            key=lambda candidate: (
                member_score(candidate),
                abs(float(candidate.get("observation_value") or 0.0)),
            ),
            reverse=True,
        )
        selected = ranked[0]
        audit[f"{audit_prefix}chosen_role"] = chosen_role
        audit[f"{audit_prefix}member_score"] = round(member_score(selected), 4)
        return selected

    # Override lane (step 3): a genuine new development jumps the rotation,
    # bypassing cooldown and the role gap but never evidence/scope validity.
    #
    # (a) A real direction reversal versus the stored focus (fires even while
    # the focus is cooling - a reversal of a resting story is exactly what
    # should resurface it).
    reversals = []
    for candidate in pool:
        stored = focus_records.get(candidate["focus_key"], {})
        old_direction = str(stored.get("last_direction") or stored.get("direction") or "")
        new_direction = str(candidate.get("direction") or "")
        if old_direction and new_direction and old_direction != new_direction:
            reversals.append(candidate)
    if reversals:
        selected = _choose(reversals, "override_", apply_schedule=False)
        audit["override_candidates"] = len(reversals)
        return _finish(selected, "material_reversal")

    # (b) R2 magnitude/share override: a big AND material move that is NOT
    # already cooling jumps the role gap/schedule. The dual threshold stops a
    # large percentage on a trivial base, or a large base moving trivially,
    # from firing; a cooling focus only returns via the reversal lane above, so
    # this never re-shows the same big story day after day.
    override_change_pct = max(0.0, float(state.get("summary_focus_override_change_pct", 20) or 0.0))
    override_min_share = max(
        0.0, float(state.get("summary_focus_override_min_impact_share_pct", 2) or 0.0)
    )
    magnitude = []
    magnitude_audit = []
    for candidate in pool:
        if candidate["focus_key"] in blocked_focus:
            continue
        pct = candidate.get("change_pct")
        share = _impact_share_pct(candidate, totals)
        if (
            _number(pct) and abs(float(pct)) >= override_change_pct
            and _number(share) and float(share) >= override_min_share
        ):
            magnitude.append(candidate)
            magnitude_audit.append({
                "candidate_id": candidate.get("candidate_id"),
                "focus_key": candidate.get("focus_key"),
                "change_pct": float(pct),
                "impact_share_pct": float(share),
            })
    if magnitude:
        audit["magnitude_override_candidates"] = len(magnitude)
        audit["magnitude_override_evidence"] = magnitude_audit
        # A magnitude reading is only a genuinely new development when the
        # dataset watermark advanced. On an unchanged snapshot it must still
        # respect R3 overlap; otherwise yesterday's highlighted driver/location
        # can become today's headline solely because it is large. If every
        # magnitude candidate overlaps, defer to the normal pool so a fresh,
        # non-magnitude perspective still has a chance to win.
        magnitude_pool = magnitude
        if not data_advanced:
            magnitude_pool, repeated_magnitude = _partition_overlap(magnitude)
            audit["magnitude_overlap_suppressed"] = len(repeated_magnitude)
            if repeated_magnitude and not magnitude_pool:
                audit["magnitude_overlap_deferred"] = True
        if magnitude_pool:
            # The override jumps the editorial schedule and uses deterministic
            # role/member scoring without schedule affinity.
            selected = _choose(magnitude_pool, "magnitude_override_", apply_schedule=False)
            return _finish(selected, "material_override")

    # Only a newly completed business period can reopen an overall/period
    # focus.  A changing raw day watermark deliberately cannot.
    grain = str(period.get("grain") or "").casefold()
    if store.get("period_anchor") and anchor_changed and grain in {"week", "month", "quarter", "year"}:
        period_pool = [
            candidate for candidate in pool
            if str(candidate.get("dimension_role") or "") in {"overall", "period"}
            or str(candidate.get("lens") or "") == "trend"
        ]
        if period_pool:
            selected = _choose(period_pool, "period_override_", apply_schedule=False)
            audit["period_override_candidates"] = len(period_pool)
            return _finish(selected, "new_completed_period")

    # --- 4. suppression: focus cooldown + same-dimension role gap ------------
    survivors = [c for c in pool if c["focus_key"] not in blocked_focus]
    audit["cooldown_suppressed"] = len(pool) - len(survivors)

    roles_present = {c["dimension_role"] for c in survivors}
    recent_roles = set()
    for role in list(roles_present):
        last = _role_last_reported(focus_records, role)
        if last is not None and (today - last).days < max(0, gap_days):
            recent_roles.add(role)
    # Only apply the role gap when at least one alternative role remains.
    if recent_roles and (roles_present - recent_roles):
        survivors = [c for c in survivors if c["dimension_role"] not in recent_roles]
        audit["role_gap_suppressed_roles"] = sorted(recent_roles)

    if not survivors:
        return _finish(None, "all_focus_perspectives_recently_reported")

    # --- 7. recent-fact overlap suppression (R3) -----------------------------
    # Prefer a focus that does not just re-tell a story a recent delivery
    # already featured (same segment, or the driver/location it highlighted).
    # Reversal/new-period overrides and magnitude moves on an advanced data
    # watermark are exempt: a genuine new development beats overlap. Static
    # magnitude readings were already screened above. If EVERY survivor
    # overlaps, we still deliver the best one rather than go silent (a mild
    # repeat beats no summary), flagged in the audit.
    if recent_window:
        novel, repeated = _partition_overlap(survivors)
        audit["overlap_suppressed"] = len(repeated)
        audit["overlap_threshold"] = overlap_threshold
        if novel:
            survivors = novel
        else:
            audit["overlap_forced"] = True

    selected = _choose(survivors)
    return _finish(selected, "two_stage_selection")
