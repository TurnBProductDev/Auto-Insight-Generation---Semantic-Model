"""Deterministic R4 multi-focus portfolio selection (summary-only).

Replaces the single-focus early-return design (§13) with three explicit stages:

* Stage A - filter to eligible Division/Department/Category candidates;
* Stage B - diversity-gated priority seeds (reversal / magnitude-on-advanced-data
  / most-overdue), which get priority but never immunity from portfolio diversity;
* Stage C - divide-by-max normalized greedy fill with same-area, parent-child and
  fact-overlap diversity, stopping at the target count or when nothing qualifies
  (a target, never a padded minimum).

Pure and offline-testable: no I/O, no LLM. It reads materiality via
``summary_materiality`` and role/hierarchy rules via ``summary_roles``; memory is
passed in as a plain ``coverage`` map so this module never touches the store.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import summary_materiality as materiality
from . import summary_focus
from . import summary_memory
from . import summary_roles

# Importance / priority weights (§12).
_IMPORTANCE_GLOBAL = 0.70
_IMPORTANCE_SHARE = 0.30
_PRIORITY_IMPORTANCE = 0.55
_PRIORITY_DEBT = 0.25
_PRIORITY_SIBLING = 0.10
_PRIORITY_COMPLETENESS = 0.10


def _norm(value: Any) -> str:
    return summary_memory._norm_text(value)


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _path(candidate: dict) -> list[str]:
    path = candidate.get("hierarchy_path")
    if isinstance(path, (list, tuple)) and path:
        return [_norm(part) for part in path if str(part or "").strip()]
    segment = candidate.get("segment")
    return [_norm(segment)] if str(segment or "").strip() else []


def _is_parent_child(a: dict, b: dict) -> bool:
    """True when one candidate's hierarchy path is a prefix of the other's."""
    pa, pb = _path(a), _path(b)
    if not pa or not pb:
        return False
    shorter, longer = (pa, pb) if len(pa) <= len(pb) else (pb, pa)
    return longer[: len(shorter)] == shorter


def _entities(candidate: dict) -> set[str]:
    """Featured business entities: the focus segment plus its peer contributors."""
    entities = {_norm(candidate.get("segment"))}
    for fact in (candidate.get("evidence") or {}).get("facts", []) or []:
        if str(fact.get("subject_role")) in {"focus", "peer"}:
            entities.add(_norm(fact.get("subject")))
    return {entity for entity in entities if entity}


def _fact_overlap(a: dict, b: dict) -> float:
    """Fraction of ``a``'s featured entities already featured by ``b``."""
    ea, eb = _entities(a), _entities(b)
    if not ea:
        return 0.0
    return len(ea & eb) / len(ea)


def _coverage_debt(area_key: str, coverage: dict, today: date, window_days: int) -> float:
    """1.0 for an unseen area; decays toward 0 as coverage becomes recent."""
    record = (coverage or {}).get(area_key)
    if not record:
        return 1.0
    last = _as_date(record.get("last_covered"))
    if last is None:
        return 1.0
    window = max(1, int(window_days))
    return min(1.0, max(0.0, (today - last).days) / window)


def _within_gap(area_key: str, coverage: dict, today: date, gap_days: int) -> bool:
    record = (coverage or {}).get(area_key)
    last = _as_date((record or {}).get("last_covered"))
    if last is None:
        return False
    return 0 <= (today - last).days < max(0, int(gap_days))


def _within_days(when: Any, today: date, window: int) -> bool:
    parsed = _as_date(when)
    return parsed is not None and 0 <= (today - parsed).days <= max(0, int(window))


def _direction(candidate: dict) -> str:
    return _norm(candidate.get("direction"))


def _is_reversal(candidate: dict, coverage: dict) -> bool:
    record = (coverage or {}).get(candidate.get("area_key"))
    old = _norm((record or {}).get("last_direction"))
    new = _direction(candidate)
    return bool(old and new and old != new)


def select_portfolio(
    state: dict,
    candidates: list[dict],
    *,
    coverage: dict | None = None,
    recent_focus: list[dict] | None = None,
    today: date | None = None,
    data_advanced: bool = False,
) -> dict:
    """Return an ordered focus portfolio, ranked reserves, and a full audit."""
    coverage = coverage or {}
    today = today or date.today()
    target = max(1, int(state.get("summary_focus_target_count", 3)))
    tol = float(state.get("summary_focus_reconciliation_tolerance_pct", 2))
    min_movement = float(state.get("summary_focus_min_movement_impact_pct", 5))
    min_share = float(state.get("summary_focus_min_business_share_pct", 5))
    min_change = float(state.get("summary_focus_min_change_pct", 3))
    window_days = int(state.get("summary_focus_rotation_window_days", 7))
    gap_days = int(state.get("summary_focus_min_repeat_gap_days", 2))
    overlap_threshold = float(state.get("summary_focus_fact_overlap_threshold", 0.6) or 0.0)
    overlap_window_days = int(state.get("summary_focus_overlap_window_days", 7))
    override_change = float(state.get("summary_focus_override_change_pct", 20) or 0.0)
    override_share = float(state.get("summary_focus_override_min_impact_share_pct", 2) or 0.0)

    audit: dict = {"detected": len(candidates), "today": today.isoformat()}
    overall_change_totals = summary_focus._total_change(candidates)

    # --- Stage A: filter -----------------------------------------------------
    eligible: list[dict] = []
    dropped = {
        "role": 0, "invalid": 0, "evidence": 0, "collapsed_hierarchy": 0,
        "materiality": 0, "repeat_gap": 0,
    }
    for candidate in candidates:
        if candidate.get("candidate_kind") != "member" or not candidate.get("area_key"):
            continue
        role = candidate.get("dimension_role")
        if not summary_roles.is_primary_focus_role(role, candidate.get("dimension"), state):
            dropped["role"] += 1
            continue
        if str(candidate.get("coverage")) == "invalid":
            dropped["invalid"] += 1
            continue
        if materiality._num(candidate.get("current")) is None or materiality._num(candidate.get("prior")) is None:
            dropped["evidence"] += 1
            continue
        path = _path(candidate)
        sibling_count = materiality._num(candidate.get("full_member_count"))
        if (
            len(path) >= 2
            and path[-1] == path[-2]
            and sibling_count is not None
            and sibling_count <= 1
        ):
            # A one-child level named exactly like its parent adds no distinct
            # business area (common when a semantic model exposes a helper
            # Department column that mirrors Division). Do not rotate it as a
            # separate story; its descendants and parent remain eligible.
            dropped["collapsed_hierarchy"] += 1
            continue
        facts = materiality.compute_facts(candidate, tol)
        candidate = {**candidate, "_facts": facts}
        candidate["_impact_share_pct"] = summary_focus._impact_share_pct(
            candidate, overall_change_totals,
        )
        candidate["_reversal"] = _is_reversal(candidate, coverage)
        candidate["_magnitude"] = bool(
            data_advanced
            and facts.get("area_change_pct") is not None
            and abs(facts["area_change_pct"]) >= override_change
            and candidate.get("_impact_share_pct") is not None
            and candidate["_impact_share_pct"] >= override_share
        )
        if not materiality.is_eligible(
            facts,
            min_movement_pct=min_movement,
            min_business_share_pct=min_share,
            min_change_pct=min_change,
        ):
            dropped["materiality"] += 1
            continue
        override = candidate["_reversal"] or candidate["_magnitude"]
        if _within_gap(candidate.get("area_key"), coverage, today, gap_days) and not override:
            dropped["repeat_gap"] += 1
            continue
        eligible.append(candidate)

    # Dedup exact area, keeping the strongest by global impact.
    by_area: dict[str, dict] = {}
    for candidate in eligible:
        key = candidate["area_key"]
        current = by_area.get(key)
        if current is None or (candidate["_facts"].get("global_impact_pct") or 0) > (
            current["_facts"].get("global_impact_pct") or 0
        ):
            by_area[key] = candidate
    pool = list(by_area.values())
    audit["dropped"] = dropped
    audit["eligible"] = len(pool)

    if not pool:
        audit["reason"] = "no_qualifying_hierarchy" if not candidates else "no_eligible_area"
        return {"selected": [], "reserves": [], "audit": audit}

    # --- normalization (§12): once, after filtering, before selection --------
    gi_norm = materiality.divide_by_max([c["_facts"].get("global_impact_pct") for c in pool])
    bs_norm = materiality.divide_by_max([c["_facts"].get("business_share_pct") for c in pool])
    for candidate, gin, bsn in zip(pool, gi_norm, bs_norm):
        candidate["_gi_norm"] = gin
        candidate["_bs_norm"] = bsn
        candidate["_importance"] = _IMPORTANCE_GLOBAL * gin + _IMPORTANCE_SHARE * bsn
    # Sibling impact normalizes within role + parent group.
    groups: dict[tuple, list[dict]] = {}
    for candidate in pool:
        group_key = (_norm(candidate.get("dimension_role")), tuple(_path(candidate)[:-1]))
        groups.setdefault(group_key, []).append(candidate)
    for members in groups.values():
        sib_norm = materiality.divide_by_max([m["_facts"].get("sibling_movement_impact_pct") for m in members])
        for member, value in zip(members, sib_norm):
            member["_sibling_norm"] = value
    for candidate in pool:
        debt = _coverage_debt(candidate["area_key"], coverage, today, window_days)
        completeness = 1.0 if candidate["_facts"].get("reconciled") else 0.5
        candidate["_debt"] = debt
        candidate["_completeness"] = completeness
        candidate["_priority"] = (
            _PRIORITY_IMPORTANCE * candidate["_importance"]
            + _PRIORITY_DEBT * debt
            + _PRIORITY_SIBLING * candidate.get("_sibling_norm", 0.0)
            + _PRIORITY_COMPLETENESS * completeness
        )

    # R3/R4 fact overlap is a *recent-story* guard, not permanent suppression.
    # Keep its date semantics aligned with deep-dive signature comparison:
    # entries without a valid reported_at timestamp, future entries, and
    # deliveries older than the configured window cannot suppress a focus.
    recent_window = [
        entry for entry in (recent_focus or [])
        if _within_days(entry.get("reported_at"), today, overlap_window_days)
    ]

    def diversity_ok(candidate: dict, chosen: list[dict]) -> bool:
        for other in chosen:
            if candidate["area_key"] == other["area_key"]:
                return False
            if _is_parent_child(candidate, other):
                return False
            if overlap_threshold > 0 and _fact_overlap(candidate, other) >= overlap_threshold:
                return False
        if overlap_threshold > 0 and recent_window:
            if max((_fact_overlap(candidate, entry) for entry in recent_window), default=0.0) >= overlap_threshold:
                return False
        return True

    selected: list[dict] = []

    # --- Stage B: diversity-gated priority seeds -----------------------------
    def _seed_rank(candidate: dict) -> tuple:
        return (
            0 if candidate.get("_reversal") else 1,
            -(candidate["_facts"].get("global_impact_pct") or 0.0),
            -candidate["_debt"],
        )

    seeds = [c for c in pool if c.get("_reversal") or c.get("_magnitude")]
    overdue = sorted(pool, key=lambda c: (-c["_debt"], -c["_priority"]))
    if overdue and overdue[0]["_debt"] >= 1.0:
        seeds.append(overdue[0])
    seen_seed: set[str] = set()
    ordered_seeds = []
    for candidate in sorted(seeds, key=_seed_rank):
        if candidate["area_key"] in seen_seed:
            continue
        seen_seed.add(candidate["area_key"])
        ordered_seeds.append(candidate)
    seeded = 0
    for candidate in ordered_seeds:
        if len(selected) >= target:
            break
        if diversity_ok(candidate, selected):
            candidate["_selection_reason"] = "reversal" if candidate.get("_reversal") else (
                "magnitude" if candidate.get("_magnitude") else "overdue"
            )
            selected.append(candidate)
            seeded += 1
    audit["seeds"] = seeded

    # --- Stage C: diverse greedy fill ----------------------------------------
    chosen_areas = {c["area_key"] for c in selected}
    remaining = sorted(
        (c for c in pool if c["area_key"] not in chosen_areas),
        key=lambda c: (-c["_priority"], -(c["_facts"].get("global_impact_pct") or 0.0), c["area_key"]),
    )
    reserves: list[dict] = []
    for candidate in remaining:
        if len(selected) >= target:
            reserves.append(candidate)
            continue
        if diversity_ok(candidate, selected):
            candidate["_selection_reason"] = "greedy"
            selected.append(candidate)
        else:
            reserves.append(candidate)

    audit["selected"] = len(selected)
    audit["reserves"] = len(reserves)
    audit["reason"] = "portfolio" if selected else "no_diverse_area"
    return {
        "selected": [_public(candidate) for candidate in selected],
        "reserves": [_public(candidate) for candidate in reserves],
        "audit": audit,
    }


def _public(candidate: dict) -> dict:
    """Attach the computed selection facts as stable public fields."""
    facts = candidate.get("_facts", {})
    result = {
        key: value for key, value in candidate.items()
        if not key.startswith("_")
    }
    result["materiality_facts"] = {
        "global_impact_pct": facts.get("global_impact_pct"),
        "business_share_pct": facts.get("business_share_pct"),
        "sibling_movement_impact_pct": facts.get("sibling_movement_impact_pct"),
        "area_change_pct": facts.get("area_change_pct"),
        "reconciled": facts.get("reconciled"),
        "impact_share_pct": candidate.get("_impact_share_pct"),
    }
    direction = _direction(candidate)
    sentiment = (
        "opportunity" if direction in {"increase", "increasing", "growth", "up", "positive"}
        else "risk" if direction in {"decrease", "decreasing", "decline", "down", "negative"}
        else "mixed"
    )
    result["sentiment"] = sentiment
    result["selection"] = {
        "reason": candidate.get("_selection_reason"),
        "priority": round(candidate.get("_priority", 0.0), 4),
        "importance": round(candidate.get("_importance", 0.0), 4),
        "coverage_debt": round(candidate.get("_debt", 0.0), 4),
        "reversal": bool(candidate.get("_reversal")),
        "magnitude": bool(candidate.get("_magnitude")),
        "sentiment": sentiment,
    }
    return result
