"""Inventory comparisons: current position against the agreed policy.

`SnapshotVsPolicySpine` is the **first** inventory spine, replacing the brief's
`SnapshotVsSnapshotSpine`. The reason is in `docs/domain-verticals-findings.md`
§8: both live models hold exactly one snapshot (`UPDATED_ON` has one distinct
value in each), so a snapshot-over-snapshot comparison has no baseline to
measure against. A policy band does - and it is real, verified and already
materialised on the fact row:

    EXCESS THRESHOLD    280 rows = 40 sections x 7 locations
    LEAD DAYS TABLE     LEAD_DAYS + SAFETY_DAYS per location per section
    RP TABLE            a genuine per-SKU reorder point (2..24, not a constant)
    EXCESS_THRESHOLD_DAYS / Reorder_Level   columns ON the fact row

Two units, kept apart
---------------------
The band is expressed in **days of cover**: a SKU is excess when Burn-Out Days
exceeds its section threshold, and on the verge of stockout when it falls below
lead + safety days. So the *distance* is in days while the *exposure* is in SAR.
Collapsing them prints "SAR 9". The spine declares both units and the deep dive
carries them separately.

What "no baseline" means here
-----------------------------
An item with no policy set is **not** an exception - nobody has said what its
level should be, so there is nothing to be outside of. It classifies as
`baseline_missing` and is excluded from the queue rather than being ranked as
compliant (Non-negotiable 13: unmeasurable is not green).
"""

from __future__ import annotations

from typing import Any

from ...kernel import spine as kernel_spine

#: The value the live model uses for "has stock but no sales", which must never
#: be read as a number of days (Inventory BR-11). 16.3% of live rows carry it,
#: and treating it as a number inflates mean Burn-Out Days from 187 to 326.
COVER_SENTINEL = 1000


class SnapshotVsPolicySpine(kernel_spine.BaseSpine):
    """Stock position now, against the band the buying team agreed."""

    kind = "snapshot_vs_policy"
    baseline_label = "the agreed stock policy"
    _delta_kind = kernel_spine.DISTANCE
    _delta_unit = "days"
    _exposure_unit = "value"

    def __init__(self,
                 *,
                 cover_measure: str | None = None,
                 lower_measure: str | None = None,
                 upper_measure: str | None = None,
                 exposure_measure: str | None = None,
                 snapshot_column: str | None = None,
                 sentinel: int = COVER_SENTINEL):
        #: Burn-Out Days, or whatever the model calls days of cover.
        self.cover_measure = cover_measure
        #: Lower bound: lead days + safety days. Below it is a stockout risk.
        self.lower_measure = lower_measure
        #: Upper bound: the section's excess threshold. Above it is excess.
        self.upper_measure = upper_measure
        #: What is at risk, in money. This is what findings are ranked by.
        self.exposure_measure = exposure_measure
        #: The as-of stamp, so every query pins to one snapshot.
        self.snapshot_column = snapshot_column
        self.sentinel = sentinel

    # --- measures -------------------------------------------------------------

    def measures(self) -> dict:
        resolved = {
            "current": self.cover_measure,
            "baseline_lower": self.lower_measure,
            "baseline_upper": self.upper_measure,
            "exposure": self.exposure_measure,
        }
        return {slot: name for slot, name in resolved.items() if name}

    def delta_expr(self) -> str:
        """How far outside the band, in days. Zero inside it.

        One-sided on purpose: a position inside the band has no distance to
        report, and inventing a signed "distance from the middle" would rank
        healthy stock alongside exceptions.
        """
        if not self.cover_measure:
            return ""
        cover = f"[{self.cover_measure}]"
        lower = f"[{self.lower_measure}]" if self.lower_measure else None
        upper = f"[{self.upper_measure}]" if self.upper_measure else None
        if lower and upper:
            return (f"IF({cover} > {upper}, {cover} - {upper}, "
                    f"IF({cover} < {lower}, {cover} - {lower}, 0))")
        if upper:
            return f"IF({cover} > {upper}, {cover} - {upper}, 0)"
        if lower:
            return f"IF({cover} < {lower}, {cover} - {lower}, 0)"
        return ""

    # --- classification and percentages ---------------------------------------

    def cover_of(self, row: dict) -> float | None:
        """Days of cover, with the sentinel removed.

        The sentinel means "no velocity", not a very long cover. Left in, it
        makes an item with no sales look like the best-stocked line in the
        business.
        """
        value = _num(row.get("cover", row.get("current")))
        if value is None:
            return None
        return None if value == self.sentinel else value

    def band_of(self, row: dict) -> tuple[float | None, float | None]:
        return (_num(row.get("baseline_lower", row.get("lower"))),
                _num(row.get("baseline_upper", row.get("upper"))))

    def classify(self, row: dict) -> str:
        """comparable / baseline_missing / current_only / inactive.

        ``baseline_missing`` is the important one: an item nobody set a policy
        for is excluded from the exception queue, not reported as compliant.
        """
        cover = self.cover_of(row)
        lower, upper = self.band_of(row)
        has_band = lower is not None or upper is not None
        if cover is None and not has_band:
            return kernel_spine.INACTIVE
        if not has_band:
            return kernel_spine.BASELINE_MISSING
        if cover is None:
            # A policy exists but cover is unmeasurable - typically the
            # sentinel, i.e. stock with no sales at all.
            return kernel_spine.CURRENT_ONLY
        return kernel_spine.COMPARABLE

    def distance(self, row: dict) -> float | None:
        """Days outside the band. Negative below, positive above, 0 inside."""
        cover = self.cover_of(row)
        lower, upper = self.band_of(row)
        if cover is None:
            return None
        if upper is not None and cover > upper:
            return cover - upper
        if lower is not None and cover < lower:
            return cover - lower
        if lower is None and upper is None:
            return None
        return 0.0

    def state(self, row: dict) -> str:
        """A name for the position, used for state-based novelty (WP4/WP6)."""
        classification = self.classify(row)
        if classification == kernel_spine.BASELINE_MISSING:
            return "no_policy"
        if classification == kernel_spine.INACTIVE:
            return "inactive"
        if classification == kernel_spine.CURRENT_ONLY:
            return "no_velocity"
        gap = self.distance(row)
        if gap is None:
            return "unknown"
        if gap > 0:
            return "excess"
        if gap < 0:
            return "below_reorder"
        return "within_policy"

    def pct(self, current: Any, baseline: Any) -> float | None:
        """How far past the limit, as a share of the limit itself.

        Against the *band edge*, not against last year - "40% past the excess
        threshold" is the sentence a buyer can act on.
        """
        cover, limit = _num(current), _num(baseline)
        if cover is None or limit is None or limit == 0:
            return None
        return (cover - limit) / abs(limit) * 100.0

    # --- scope ----------------------------------------------------------------

    def population_filter(self, scope: dict) -> str | None:
        """Pin every query to the latest snapshot.

        This is the spine's single most important job. Non-negotiable 11: a
        semi-additive measure is never aggregated across snapshot dates.
        """
        column = (scope or {}).get("snapshot_column") or self.snapshot_column
        if not column:
            return None
        from ...kernel import snapshot

        return snapshot.latest_snapshot_filter(column)

    def denominator(self, rows: list[dict]) -> float | None:
        """Total value at risk - what every share is measured against."""
        total = 0.0
        seen = False
        for row in rows:
            value = _num(row.get("exposure", row.get("current")))
            if value is not None:
                total += value
                seen = True
        return total if seen else None

    # --- ranking and novelty ---------------------------------------------------

    def rank_components(self, member: dict, level: dict) -> dict:
        """Severity in days, exposure in money, persistence in days.

        There is no signed change to rank on, so this feeds the change-free
        blend registered in WP2 rather than the year-on-year one.
        """
        gap = self.distance(member)
        return {
            "severity_score": abs(gap) if gap is not None else None,
            "exposure_value": _num(member.get("exposure", member.get("current"))),
            "persistence_days": _num(member.get("days_in_state")),
            "blend": "severity_exposure_persistence",
        }

    def novelty_key(self, member: dict, context: dict) -> dict:
        """Keyed on the STATE, not a period.

        A snapshot report has no period to anchor to, and "below reorder point,
        day 9" must not be re-announced as brand new every morning - but must
        speak up when it worsens or clears. The state is part of the key so a
        transition is a new story; the duration deliberately is not, or every
        day would be.
        """
        return {
            "spine": self.kind,
            "member": member.get("member"),
            "role": member.get("role"),
            "state": self.state(member),
        }

    def caveats(self) -> list[str]:
        notes = [
            "Stock figures are a position as at the snapshot date, not a total "
            "over a period.",
        ]
        if self.cover_measure:
            notes.append(
                f"Items with stock but no sales carry a cover value of "
                f"{self.sentinel}, which means no rate of sale rather than "
                f"{self.sentinel} days of stock; they are excluded from cover "
                f"averages.")
        return notes


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


kernel_spine.register(SnapshotVsPolicySpine.kind, SnapshotVsPolicySpine)
