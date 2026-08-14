"""Which findings matter most, when "most" means different things per report.

The existing blend answers "what moved, relative to last year". It needs three
inputs - impact, magnitude, unexpectedness - and two of those are percent
changes, so it cannot rank anything that has no before-and-after.

WP0 proved that is not a hypothetical. Both live inventory facts hold exactly
one snapshot, so the Stock Age Analysis report has **no signed change at all**.
Its rulebook does not ask for one either: BR-28 ranks by risk tier and then by
SAR value. That report needs a different blend, and this registry is where a
report says which.

Deliberately an indirection layer, not a reimplementation
--------------------------------------------------------
`impact_magnitude_unexpectedness` is registered as a *reference* to the existing
`summary_coverage.rank_scores`. The arithmetic does not move, so WP2 cannot
change a Sales YoY number - the golden master proves it, and a reimplementation
would put that guarantee at risk for no benefit.

The normalization primitives are shared on purpose: a new blend that invents its
own scaling would drift from the one the product already trusts (brief §1.3).
"""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence

from ..tools import summary_materiality as materiality

#: A blend takes the level's members and returns one score per member, in order.
Blend = Callable[..., list[float]]

BLEND_REGISTRY: dict[str, Blend] = {}

#: Ratio components are winsorized before normalizing. A member worth a rounding
#: error otherwise maxes magnitude AND unexpectedness at once - a freak
#: percentage is by construction also far from the median.
DEFAULT_CEILING_PCT = 100.0


def register(name: str, blend: Blend) -> Blend:
    existing = BLEND_REGISTRY.get(name)
    if existing is not None and existing is not blend:
        raise ValueError(
            f"blend {name!r} is already registered; refusing to rebind it - two "
            f"reports resolving one name to different arithmetic is the drift "
            f"this registry prevents")
    BLEND_REGISTRY[name] = blend
    return blend


def get(name: str) -> Blend:
    try:
        return BLEND_REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown ranking blend {name!r}; registered: "
            f"{', '.join(sorted(BLEND_REGISTRY)) or '(none)'}") from None


def available() -> tuple[str, ...]:
    return tuple(sorted(BLEND_REGISTRY))


# --- shared primitives --------------------------------------------------------

def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def winsorize(value: Any, ceiling: float = DEFAULT_CEILING_PCT) -> float | None:
    """Clamp a ratio-based component, preserving None."""
    number = _num(value)
    if number is None:
        return None
    return max(-ceiling, min(ceiling, number))


def divide_by_max(values: Sequence[Any]) -> list[float]:
    """Normalize against the level's own maximum. Re-exported from the existing
    implementation so a new blend cannot drift from the trusted one."""
    return materiality.divide_by_max(list(values))


# --- the year-on-year blend (Sales YoY) ---------------------------------------

def impact_magnitude_unexpectedness(members: list[dict],
                                    peer_median: float | None = None) -> list[float]:
    """The existing blend, reached through the registry.

    A *reference*, not a reimplementation: it calls the same
    ``summary_coverage.rank_scores`` code path the product already trusts, so
    registering it cannot change a Sales YoY number. The import is deferred
    because ``summary_coverage`` imports this module.
    """
    from ..tools import summary_coverage

    if peer_median is None:
        peer_median = summary_coverage.peer_median_change_pct(members)
    return summary_coverage.rank_scores(members, peer_median)


register("impact_magnitude_unexpectedness", impact_magnitude_unexpectedness)


# --- the change-free blend (Ageing, Inventory Management) ---------------------

#: How far outside the acceptable state the member sits - the severity of the
#: exception itself.
WEIGHT_SEVERITY = 0.40
#: How much value is exposed to it. A severe exception on SAR 400 is not a
#: finding; the rulebooks say so explicitly (Ageing BR-26, Inventory BR-34).
WEIGHT_EXPOSURE = 0.40
#: How long it has been in that state. Rewards a problem that is not resolving.
WEIGHT_PERSISTENCE = 0.20


def severity_exposure_persistence(members: list[dict],
                                  *,
                                  severity_key: str = "severity_score",
                                  exposure_key: str = "exposure_value",
                                  persistence_key: str = "persistence_days",
                                  ceiling_pct: float = DEFAULT_CEILING_PCT
                                  ) -> list[float]:
    """Rank an exception queue that has no before-and-after.

    Mirrors the shape of the year-on-year blend rather than inventing a new one:
    each component is divide-by-max normalized against the level's own maximum,
    and severity is weighted by exposure for exactly the reason the existing
    blend weights magnitude by business share - otherwise a trivial item with an
    extreme severity outranks a large one with a moderate problem, which is the
    `CF-FRESH BAKES +2166.79%` failure in a new costume.

    Persistence is optional: with no duration recorded it contributes zero
    rather than being imputed, so a first-ever observation is not scored as if
    it had been outstanding for a long time.
    """
    severity = divide_by_max([winsorize(m.get(severity_key), ceiling_pct)
                              for m in members])
    exposure = divide_by_max([m.get(exposure_key) for m in members])
    persistence = divide_by_max([m.get(persistence_key) for m in members])
    return [
        exposure[index] * (WEIGHT_SEVERITY * severity[index]
                           + WEIGHT_PERSISTENCE * persistence[index])
        + WEIGHT_EXPOSURE * exposure[index]
        for index in range(len(members))
    ]


register("severity_exposure_persistence", severity_exposure_persistence)


# --- risk-tier ordering (Ageing BR-28) ---------------------------------------

#: Ageing ranks by risk tier FIRST, then by value inside the tier. That is a
#: business instruction, not a scoring choice, so it is expressed as an explicit
#: order rather than folded into a weighted blend where it could be outvoted.
DEFAULT_TIER_ORDER: tuple[str, ...] = ("24+ MONTHS", "12-24 MONTHS", "09-12 MONTHS",
                                       "06-09 MONTHS", "03-06 MONTHS", "0-03 MONTHS")


def tier_then_value(members: list[dict],
                    *,
                    tier_key: str = "tier",
                    value_key: str = "exposure_value",
                    tier_order: Sequence[str] = DEFAULT_TIER_ORDER) -> list[float]:
    """Score so that a worse tier always outranks a better one, value breaking ties.

    Each tier occupies its own band of the score range, so no amount of value in
    a safer tier can overtake a riskier one. An unknown tier sorts last rather
    than being silently treated as safest.
    """
    order = {str(name).strip().upper(): index for index, name in enumerate(tier_order)}
    unknown_rank = len(order)
    band = 1.0 / (unknown_rank + 1)
    values = divide_by_max([m.get(value_key) for m in members])
    scores = []
    for index, member in enumerate(members):
        rank = order.get(str(member.get(tier_key) or "").strip().upper(), unknown_rank)
        # Highest band for rank 0, and value only moves within the band.
        scores.append((unknown_rank - rank) * band + values[index] * band)
    return scores


register("tier_then_value", tier_then_value)
