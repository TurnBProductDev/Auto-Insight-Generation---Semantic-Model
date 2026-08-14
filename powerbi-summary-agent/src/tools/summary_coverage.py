"""Deterministic full-coverage ranked tables per business level (summary-only).

The spec this implements asks for two things that pull against each other: every
store / department / section / category should be accounted for, *and* the report
must stay short and ranked rather than becoming an exhaustive dump. This module
resolves that tension by separating the two surfaces:

* **Coverage** (here) - every member of a level, one compact ranked row, with a
  direction, a severity band and an explicit "no material change" bucket. Cheap,
  complete, scannable.
* **Focus** (``summary_portfolio``) - the handful of areas that earn written
  narrative and a deep dive.

Coverage is computed entirely from rows the universe scan already returned, so it
costs **zero additional queries**. It is pure: no state, no I/O, no LLM. Every
number is copied or derived arithmetically from the scanned members - nothing
here can introduce a figure the model did not return.

Ranking implements the spec's three-part blend explicitly:

* **impact** - how much the move matters to the whole business (share of the
  overall current total),
* **magnitude** - how big the move is in its own right (percent change),
* **unexpectedness** - how far the member moved *against the rest of its own
  level*, measured as deviation from the peer median percent change. A member
  falling 5% while every sibling falls 5% is expected; the same fall while
  siblings grow is not.

Imports no insight module and contains no model-specific table, column or member
names.
"""

from __future__ import annotations

import math
from typing import Any

from . import summary_materiality as materiality

# Ranking blend (§5.2). Impact leads: a small percentage move on a large area
# routinely matters more than a large percentage move on a rounding error.
WEIGHT_IMPACT = 0.40
WEIGHT_MAGNITUDE = 0.35
WEIGHT_UNEXPECTEDNESS = 0.25

# Severity vocabulary, ordered most to least severe. These are presentation
# bands over the deterministic score plus the configured thresholds - never an
# LLM judgement.
SEVERITY_ORDER: tuple[str, ...] = ("critical", "watch", "steady")

# Percent-change ceiling applied before the magnitude component is normalized.
# Past roughly a doubling, the exact multiple stops carrying business meaning: a
# +2,167% move on a category worth 0.05% of revenue is a rounding error with a
# spectacular ratio. Without this clamp, divide-by-max normalization lets that
# one ratio drive every other member's magnitude score to nearly zero.
MAGNITUDE_CEILING_PCT = 100.0

# A movement must reach this share of total business before it can headline.
# Ranking still surfaces it inside its own level; this only stops a trivial
# absolute move from leading the report on the strength of its percentage.
HEADLINE_MIN_IMPACT_PCT = 0.05


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _median(values: list[float]) -> float | None:
    ordered = sorted(values)
    count = len(ordered)
    if count == 0:
        return None
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def direction(change: Any) -> str:
    """Signed direction of a movement; ``flat`` when absent or exactly zero."""
    value = _num(change)
    if value is None or value == 0:
        return "flat"
    return "up" if value > 0 else "down"


def is_comparable(member: dict, spine: Any = None) -> bool:
    """True when the member can be measured against its baseline.

    A member with no prior value is current-only (a new store, a newly listed
    category). Its growth percentage is undefined, so it must never be ranked
    against members that do have a prior - it is reported in its own bucket.

    With no ``spine`` this is the year-on-year test, unchanged. A spine
    generalises it: an inventory member is comparable when it has a *policy*, and
    one with no policy is `baseline_missing` - excluded rather than judged, since
    an item nobody set a rule for is not an exception (WP2).
    """
    if spine is not None:
        from ..kernel import spine as kernel_spine

        return spine.classify(member) == kernel_spine.COMPARABLE
    return _num(member.get("current")) is not None and _num(member.get("prior")) is not None


def peer_median_change_pct(members: list[dict]) -> float | None:
    """Median percent change across the comparable members of one level."""
    values = [
        _num(member.get("change_pct"))
        for member in members
        if is_comparable(member)
    ]
    return _median([value for value in values if value is not None])


def unexpectedness_pts(member: dict, peer_median: float | None) -> float | None:
    """Percentage points by which a member diverges from its peer median.

    This is the spec's "moved against the rest of the estate" measure. It is
    undefined for a current-only member (no percent change to compare) and when
    a level has no comparable members at all.
    """
    if peer_median is None or not is_comparable(member):
        return None
    change_pct = _num(member.get("change_pct"))
    if change_pct is None:
        return None
    return abs(change_pct - peer_median)


def severity(
    member: dict,
    *,
    material_change_pct: float,
    material_share_pct: float,
) -> str:
    """Deterministic severity band for one member.

    ``critical`` requires the move to be both meaningful in its own right and
    to matter to the business: a big percentage swing on a trivial area is
    ``watch``, never ``critical``. A current-only member can never be
    ``critical`` because its movement is unmeasurable.
    """
    if not is_comparable(member):
        return "steady"
    change_pct = _num(member.get("change_pct"))
    share = _num(member.get("business_share_pct"))
    impact = _num(member.get("global_impact_pct"))
    big_move = change_pct is not None and abs(change_pct) >= float(material_change_pct)
    big_area = share is not None and share >= float(material_share_pct)
    # A move large enough to shift the whole business is critical on its own,
    # even when the area is small relative to total revenue.
    moves_the_business = impact is not None and impact >= float(material_share_pct)
    if (big_move and big_area) or moves_the_business:
        return "critical"
    if big_move or big_area:
        return "watch"
    return "steady"


def _clamp(value: Any, ceiling: float) -> float | None:
    """Winsorize a magnitude at ``ceiling``, preserving None."""
    number = _num(value)
    if number is None:
        return None
    return max(-ceiling, min(ceiling, number))


def rank_scores(members: list[dict], peer_median: float | None,
                blend: str | None = None) -> list[float]:
    """Blended rank score per member, each component divide-by-max normalized.

    Normalizing each component against the level's own maximum keeps the three
    parts commensurate without letting an outlier in one component dominate the
    other two, and matches the normalization the R4 portfolio already uses.

    Magnitude and unexpectedness are both winsorized first (see
    ``MAGNITUDE_CEILING_PCT``): they are ratio-based, so a single freak
    percentage on a negligible member would otherwise collapse the whole level's
    normalized range. Impact is not clamped - it is already expressed as a share
    of the total business, so it cannot run away.

    The two ratio components are then **weighted by the size of the entity**, as
    the spec's ranking rule requires. Clamping alone is not sufficient: a member
    worth a rounding error can max out *both* magnitude and unexpectedness at
    once (a huge percentage swing is, by construction, also far from the peer
    median), scoring 0.60 on relevance it has not earned. Scaling those two by
    normalized business share means a percentage only counts in proportion to
    how much of the business it actually touches, while impact - already an
    absolute measure - is left undamped so a large mover still ranks on its own
    merit.

    ``blend`` selects a different ranking entirely, for a report with no signed
    change to rank on - both live inventory models hold one snapshot, so
    magnitude and unexpectedness are undefined there (WP2). Omitting it keeps
    this exact blend, which is why Sales YoY output is unchanged.
    """
    if blend is not None:
        from ..kernel import ranking

        return ranking.get(blend)(members)

    impact = materiality.divide_by_max([member.get("global_impact_pct") for member in members])
    magnitude = materiality.divide_by_max(
        [_clamp(member.get("change_pct"), MAGNITUDE_CEILING_PCT) for member in members]
    )
    surprise = materiality.divide_by_max(
        [_clamp(unexpectedness_pts(member, peer_median), MAGNITUDE_CEILING_PCT)
         for member in members]
    )
    relevance = materiality.divide_by_max([member.get("business_share_pct") for member in members])
    return [
        WEIGHT_IMPACT * impact[index]
        + relevance[index] * (
            WEIGHT_MAGNITUDE * magnitude[index]
            + WEIGHT_UNEXPECTEDNESS * surprise[index]
        )
        for index in range(len(members))
    ]


def build_role_coverage(
    role: str,
    info: dict,
    *,
    material_change_pct: float,
    material_share_pct: float,
) -> dict:
    """Rank every member of one level and summarise the level as a whole.

    Returns the full member list - coverage is complete by definition. Callers
    decide how many rows to *display*; nothing is dropped here.
    """
    members = list(info.get("members") or [])
    peer_median = peer_median_change_pct(members)
    scores = rank_scores(members, peer_median)

    rows: list[dict] = []
    for index, member in enumerate(members):
        comparable = is_comparable(member)
        band = severity(
            member,
            material_change_pct=material_change_pct,
            material_share_pct=material_share_pct,
        )
        rows.append({
            "member": member.get("member"),
            "hierarchy_path": list(member.get("hierarchy_path") or []),
            "current": member.get("current"),
            "prior": member.get("prior"),
            "change": member.get("change"),
            "change_pct": member.get("change_pct"),
            "business_share_pct": member.get("business_share_pct"),
            "global_impact_pct": member.get("global_impact_pct"),
            "direction": direction(member.get("change")),
            "comparable": comparable,
            "severity": band,
            "vs_peer_median_pts": unexpectedness_pts(member, peer_median),
            "rank_score": scores[index] if index < len(scores) else 0.0,
        })

    # Rank comparable members by score; current-only members always sort last
    # because their movement is unmeasurable, not because it is small.
    rows.sort(key=lambda row: (not row["comparable"], -float(row["rank_score"] or 0.0)))
    for position, row in enumerate(rows, start=1):
        row["rank"] = position

    comparable_rows = [row for row in rows if row["comparable"]]
    counts = {
        "total": len(rows),
        "comparable": len(comparable_rows),
        "current_only": len(rows) - len(comparable_rows),
        "up": sum(1 for row in comparable_rows if row["direction"] == "up"),
        "down": sum(1 for row in comparable_rows if row["direction"] == "down"),
        "flat": sum(1 for row in comparable_rows if row["direction"] == "flat"),
    }
    for band in SEVERITY_ORDER:
        counts[band] = sum(1 for row in comparable_rows if row["severity"] == band)
    # The honest "nothing to report here" line the spec asks for, so a quiet
    # level says so in one sentence instead of being padded.
    counts["no_material_change"] = counts["steady"]

    return {
        "role": role,
        "group_ref": info.get("group_ref"),
        "column": info.get("column"),
        "level": info.get("level"),
        "coverage_only": bool(info.get("coverage_only")),
        "metric_family": info.get("metric_family"),
        "peer_median_change_pct": peer_median,
        "pool_capped": bool(info.get("pool_capped")),
        "diagnostics_reconciled": bool(info.get("diagnostics_reconciled")),
        "counts": counts,
        "rows": rows,
    }


def level_signature(level: dict) -> tuple:
    """Identity of what a level actually reports: its members and their values.

    Two levels sharing a signature are the same breakdown under two names. On a
    model where a helper column duplicates its parent (a Department column whose
    members are exactly the Divisions), reporting both would state every finding
    twice and inflate the apparent breadth of the analysis.
    """
    return tuple(sorted(
        (
            str(row.get("member") or ""),
            round(float(row["current"]), 2) if _num(row.get("current")) is not None else None,
            round(float(row["prior"]), 2) if _num(row.get("prior")) is not None else None,
        )
        for row in level.get("rows") or []
    ))


def build_coverage(
    universe: dict,
    *,
    material_change_pct: float = 10.0,
    material_share_pct: float = 5.0,
    collapse_mirrors: bool = True,
) -> dict:
    """Full ranked coverage for every successfully scanned role in the universe.

    A role that failed its scan is recorded with its status rather than silently
    omitted, so the report can say which level it could not cover. A level that
    merely mirrors a broader one is likewise recorded, not silently dropped.
    """
    roles_in = (universe or {}).get("roles") or {}
    levels: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for role, info in roles_in.items():
        if str(info.get("status")) != "ok" or not info.get("members"):
            skipped[role] = str(info.get("status") or "no_members")
            continue
        levels[role] = build_role_coverage(
            role,
            info,
            material_change_pct=material_change_pct,
            material_share_pct=material_share_pct,
        )
    ordered = sorted(
        levels.values(),
        key=lambda level: (level.get("level") is None, level.get("level") or 0, level["role"]),
    )

    # Broad -> narrow, so the level that survives a duplicate pair is always the
    # broader, more meaningful one.
    kept: list[dict] = []
    mirrored: dict[str, str] = {}
    if collapse_mirrors:
        seen: dict[tuple, str] = {}
        for level in ordered:
            signature = level_signature(level)
            if signature and signature in seen:
                mirrored[level["role"]] = seen[signature]
                continue
            seen[signature] = level["role"]
            kept.append(level)
    else:
        kept = list(ordered)

    return {
        "status": "ok" if kept else "no_coverage",
        "metric_family": (universe or {}).get("metric_family"),
        "value_aliases": (universe or {}).get("value_aliases") or {},
        "thresholds": {
            "material_change_pct": float(material_change_pct),
            "material_share_pct": float(material_share_pct),
            "headline_min_impact_pct": HEADLINE_MIN_IMPACT_PCT,
            "magnitude_ceiling_pct": MAGNITUDE_CEILING_PCT,
        },
        "weights": {
            "impact": WEIGHT_IMPACT,
            "magnitude": WEIGHT_MAGNITUDE,
            "unexpectedness": WEIGHT_UNEXPECTEDNESS,
        },
        "levels": [dict(level) for level in kept],
        "skipped_roles": skipped,
        # role -> the broader role it duplicates, so the collapse is auditable.
        "mirrored_roles": mirrored,
    }


def top_movers(
    coverage: dict,
    limit: int = 5,
    min_impact_pct: float | None = None,
) -> list[dict]:
    """The highest-ranked comparable movements across every covered level.

    Feeds the report's headline summary. Ranking is the same blended score used
    within a level; the level name travels with each row so the reader knows
    whether they are looking at a store, a department or a category.

    A relevance floor applies here and nowhere else: a movement too small to
    register against the whole business must not lead the report on the strength
    of its percentage, even though it is still ranked and shown inside its own
    level. If the floor would empty the headline entirely it is dropped, so a
    genuinely quiet period still gets a "biggest movements" list rather than a
    blank block.
    """
    floor = HEADLINE_MIN_IMPACT_PCT if min_impact_pct is None else float(min_impact_pct)
    pool: list[dict] = []
    for level in (coverage or {}).get("levels") or []:
        for row in level.get("rows") or []:
            if not row.get("comparable") or row.get("severity") == "steady":
                continue
            pool.append({**row, "role": level.get("role")})
    material = [
        row for row in pool
        if (_num(row.get("global_impact_pct")) or 0.0) >= floor
    ]
    ranked = material or pool
    ranked.sort(key=lambda row: -float(row.get("rank_score") or 0.0))
    return ranked[: max(0, int(limit))]
