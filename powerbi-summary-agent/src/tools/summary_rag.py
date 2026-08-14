"""Measure-aware RAG verdicts for the summary dashboard.

Deterministic, pure functions - no state, no IO, no LLM.

Why this is not ``summary_coverage.severity``: that function bands a *member's
movement* by materiality and business share, to decide which rows deserve
attention inside a level. This one bands a *named measure* against the standard
the business holds that measure to, and the two are deliberately different
standards. Units and Basket Size are held to a tougher band because standing
still on real demand while revenue rises on price is already a problem - flat is
amber-at-best on those, whereas flat revenue is merely watch.

Bands are config-owned (``summary_rag_bands`` / ``summary_rag_measure_bands``) so
the rulebook stays the authority on thresholds; the defaults below match the
committed rulebook reading. Every band set declares its direction, so a
"higher is worse" measure (share of revenue in declining areas) uses the same
machinery as a "higher is better" one instead of a second inverted code path.
"""

from __future__ import annotations

import math
from typing import Any

ON_TRACK = "on_track"
WATCH = "watch"
OFF_TRACK = "off_track"

STATUS_LABELS = {ON_TRACK: "On track", WATCH: "Watch", OFF_TRACK: "Off track"}
STATUS_TONES = {ON_TRACK: "positive", WATCH: "warning", OFF_TRACK: "critical"}

HIGHER_IS_BETTER = "higher_is_better"
HIGHER_IS_WORSE = "higher_is_worse"

#: Default band sets. ``off_track``/``watch`` are the two boundaries; the third
#: status is whatever is left.
DEFAULT_BANDS: dict[str, dict] = {
    # Ordinary growth measure: a small decline is a watch, a real decline is off track.
    "standard": {"direction": HIGHER_IS_BETTER, "off_track": -3.0, "watch": 0.0},
    # Real-demand measures: any decline is off track, and flat-to-small growth
    # is only a watch. This is the tougher band the rulebook calls for.
    "tough": {"direction": HIGHER_IS_BETTER, "off_track": 0.0, "watch": 2.0},
    # Exposure percentages (share of business in decline): more is worse.
    "exposure": {"direction": HIGHER_IS_WORSE, "off_track": 55.0, "watch": 40.0},
    # Point-change in an exposure measure: rising exposure is worse.
    "drift": {"direction": HIGHER_IS_WORSE, "off_track": 3.0, "watch": -3.0},
}

DEFAULT_MEASURE_BANDS: dict[str, str] = {
    "revenue": "standard",
    "transactions": "standard",
    "basket_value": "standard",
    "price": "standard",
    "units": "tough",
    "basket_size": "tough",
}

#: Plain-language caution shown when a tough-band measure goes backwards. These
#: state the fact only - never a cause - because the cause is not in the number.
DEFAULT_CAUTIONS: dict[str, str] = {
    "units": "We sold fewer items than last year.",
    "basket_size": "Each basket held fewer items than last year.",
}

#: Read-together pairs. The rulebook forbids showing Price without Basket Size:
#: a price rise with thinning baskets is trading down, not pricing power.
READ_WITH: dict[str, str] = {
    "price": "basket_size",
    "basket_size": "price",
}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def band_sets(config: dict | None = None) -> dict[str, dict]:
    """Configured band sets merged over the defaults (per-set, not wholesale).

    Merging per set means a config that overrides only ``standard`` keeps the
    tough/exposure/drift defaults instead of silently losing them.
    """
    merged = {name: dict(spec) for name, spec in DEFAULT_BANDS.items()}
    for name, spec in ((config or {}).get("summary_rag_bands") or {}).items():
        if not isinstance(spec, dict):
            continue
        merged.setdefault(str(name), {}).update(spec)
    return merged


def measure_band_map(config: dict | None = None) -> dict[str, str]:
    merged = dict(DEFAULT_MEASURE_BANDS)
    for measure, band in ((config or {}).get("summary_rag_measure_bands") or {}).items():
        merged[str(measure).strip().casefold()] = str(band)
    return merged


def evaluate(value: Any, band: dict | None) -> str | None:
    """Status for ``value`` under one band set, or ``None`` if unmeasurable."""
    number = _num(value)
    if number is None or not band:
        return None
    off = _num(band.get("off_track"))
    watch = _num(band.get("watch"))
    if off is None or watch is None:
        return None
    if str(band.get("direction") or HIGHER_IS_BETTER) == HIGHER_IS_WORSE:
        if number > off:
            return OFF_TRACK
        return WATCH if number >= watch else ON_TRACK
    if number < off:
        return OFF_TRACK
    return WATCH if number < watch else ON_TRACK


def verdict(measure_key: str, change_pct: Any, config: dict | None = None,
            band_name: str | None = None) -> dict:
    """The full RAG verdict for one measure movement.

    An unmeasurable movement (no prior, blank measure) returns
    ``status=None`` with an explicit label rather than defaulting to green - a
    missing comparison is not a pass.
    """
    bands = band_sets(config)
    name = band_name or measure_band_map(config).get(
        str(measure_key).strip().casefold(), "standard"
    )
    band = bands.get(name) or bands.get("standard")
    status = evaluate(change_pct, band)
    if status is None:
        return {
            "measure": measure_key,
            "band": name,
            "status": None,
            "label": "Not comparable",
            "tone": "neutral",
            "caution": None,
            "read_with": READ_WITH.get(str(measure_key).strip().casefold()),
        }
    number = _num(change_pct)
    caution = None
    if number is not None and number < 0:
        caution = ((config or {}).get("summary_rag_cautions") or DEFAULT_CAUTIONS).get(
            str(measure_key).strip().casefold()
        )
    return {
        "measure": measure_key,
        "band": name,
        "status": status,
        "label": STATUS_LABELS[status],
        "tone": STATUS_TONES[status],
        "caution": caution,
        "read_with": READ_WITH.get(str(measure_key).strip().casefold()),
    }


def worst(statuses: list[str | None]) -> str | None:
    """The most severe status present - used to headline a group of measures."""
    order = [OFF_TRACK, WATCH, ON_TRACK]
    for status in order:
        if status in statuses:
            return status
    return None
