"""Sales comparisons: this period against the same period last year.

``PeriodOverPeriodSpine`` is the only spine in WP2, and its one requirement is
that it **reproduces today exactly**. Every method therefore delegates to the
helper that already computes that answer rather than restating the formula:
`summary_coverage.is_comparable` decides comparability, `summary_materiality`
computes the percentages. A second copy of either would be free to drift, which
is the defect brief §1.3 names - the codebase already carries two independent
copies of the retail family vocabulary.

The spine adds naming, not arithmetic.
"""

from __future__ import annotations

from typing import Any

from ...kernel import spine as kernel_spine
from ...tools import summary_coverage as coverage
from ...tools import summary_materiality as materiality


class PeriodOverPeriodSpine(kernel_spine.BaseSpine):
    """Current period vs the same period a year earlier."""

    kind = "period_over_period"
    baseline_label = "the same period last year"
    _delta_kind = kernel_spine.ABSOLUTE
    _delta_unit = "value"
    _exposure_unit = "value"

    def __init__(self, bundle: dict | None = None):
        #: The `(current, prior, change)` measure names, as resolved by
        #: ``semantic_profiler``. Optional so the spine can be used for pure
        #: classification and ranking without a model attached.
        self.bundle = dict(bundle or {})

    # --- measures -------------------------------------------------------------

    def measures(self) -> dict:
        """slot -> measure name. ``baseline`` is this spine's word for prior."""
        measures = dict((self.bundle.get("measures") or {}))
        resolved = {
            "current": measures.get("current"),
            "baseline": measures.get("prior"),
            "change": measures.get("change"),
        }
        return {slot: name for slot, name in resolved.items() if name}

    def delta_expr(self) -> str:
        resolved = self.measures()
        change = resolved.get("change")
        if change:
            return f"[{change}]"
        current, baseline = resolved.get("current"), resolved.get("baseline")
        if current and baseline:
            return f"[{current}] - [{baseline}]"
        return ""

    # --- classification and percentages ---------------------------------------

    def pct(self, current: Any, baseline: Any) -> float | None:
        """Percent change. Delegates, so it cannot diverge from the ranking."""
        change = materiality.area_change(current, baseline)
        return materiality.area_change_pct(change, baseline)

    def classify(self, row: dict) -> str:
        """comparable / current_only / baseline_missing / inactive.

        `is_comparable` is the existing gate and stays authoritative: a member
        with no prior is current-only (a new store, a newly listed category) and
        must never be ranked against members that do have one.
        """
        if coverage.is_comparable(row):
            return kernel_spine.COMPARABLE
        has_current = _num(row.get("current")) is not None
        has_prior = _num(row.get("prior", row.get("baseline"))) is not None
        if has_current and not has_prior:
            return kernel_spine.CURRENT_ONLY
        if has_prior and not has_current:
            return kernel_spine.BASELINE_MISSING
        return kernel_spine.INACTIVE

    # --- scope ----------------------------------------------------------------

    def population_filter(self, scope: dict) -> str | None:
        """The comparable-population filter, when one has been resolved.

        Year-on-year growth over a shop that did not trade last year is
        meaningless, which is why this population exists and why the scope
        validator enforces it.
        """
        members = list((scope or {}).get("comparable") or [])
        if not members:
            return None
        reference = (scope or {}).get("entity_reference")
        if not reference:
            return None
        values = ", ".join('"' + str(m).replace('"', '""') + '"' for m in members)
        return f"TREATAS({{{values}}}, {reference})"

    def denominator(self, rows: list[dict]) -> float | None:
        """Overall current total - the base every share is measured against."""
        return super().denominator(rows)

    # --- ranking and novelty ---------------------------------------------------

    def rank_components(self, member: dict, level: dict) -> dict:
        return {
            "global_impact_pct": member.get("global_impact_pct"),
            "business_share_pct": member.get("business_share_pct"),
            "change_pct": member.get("change_pct"),
            "blend": "impact_magnitude_unexpectedness",
        }

    def novelty_key(self, member: dict, context: dict) -> dict:
        """Period-anchored: a new period is a new story, a re-run is not."""
        return {
            "spine": self.kind,
            "member": member.get("member"),
            "role": member.get("role"),
            "period_anchor": (context or {}).get("period_anchor"),
        }

    def caveats(self) -> list[str]:
        return []


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


kernel_spine.register(PeriodOverPeriodSpine.kind, PeriodOverPeriodSpine)


class TargetVsActualSpine(kernel_spine.BaseSpine):
    """Actual sales against the agreed target - the Target Tracker comparison.

    This model holds **2026 only**. `LY_SALES`, `LY_SAME_DAY_SALES` and
    `LYLY_SALES` do not exist as columns, and roughly thirty model measures that
    reference them fail at query time. So there is no prior-year baseline to
    difference against and `PeriodOverPeriodSpine` cannot be used: its whole
    contract is a `(current, prior, change)` triple this data cannot supply.

    The baseline here is the target, which changes three things:

    * **A missing target is `baseline_missing`, never a miss.** August 2026
      carries a NULL `ACTUAL_SALES_TARGET` on all 2,682 rows. A day nobody set a
      target for has not underperformed - it is unmeasurable, and reporting it
      as a 100% shortfall would be the exact failure Non-negotiable 13 forbids.
    * **Attainment is always measured against the ELAPSED target.** Comparing
      month-to-date sales with a whole-month target reads as "36% of target" on
      day 11. The scan sums the elapsed target explicitly; this spine only
      names the comparison.
    * **The delta is signed currency**, so `delta_unit` and `exposure_unit`
      agree - unlike the inventory policy spine, where the band is in days and
      the exposure is in SAR.
    """

    kind = "target_vs_actual"
    baseline_label = "the target"
    _delta_kind = kernel_spine.ABSOLUTE
    _delta_unit = "value"
    _exposure_unit = "value"

    #: Slot names as they appear on a scanned Target Tracker row.
    CURRENT_KEYS = ("actual", "current", "sales")
    BASELINE_KEYS = ("target", "baseline")

    def measures(self) -> dict:
        # Scope targets are summed from the ACTUAL_SALES_TARGET column over an
        # explicit date range rather than read from a model measure: MTD_TARGET
        # and WTD_TARGET are the same broken expression (both filter
        # MTD_CHECK = "Y", true on all 44,127 rows) and both return the full
        # year target. No model measure is used for a headline figure.
        return {"current": None, "baseline": None, "change": None}

    def delta_expr(self) -> str:
        return ""

    # --- classification and percentages ---------------------------------------

    def _read(self, row: dict, keys) -> float | None:
        for key in keys:
            value = _num((row or {}).get(key))
            if value is not None:
                return value
        return None

    def pct(self, current: Any, baseline: Any) -> float | None:
        """Percent above/below target. Delegates to the report's own attainment.

        Returns attainment minus 100, so the protocol's "delta relative to
        baseline" meaning holds: 0 is on target, -8.7 is 8.7% short. A zero or
        absent target yields None rather than infinity.
        """
        from . import target_tracker

        current_val, baseline_val = _num(current), _num(baseline)
        if current_val is None or baseline_val is None:
            return None
        hit = target_tracker.attainment(current_val, baseline_val)
        return None if hit is None else hit - 100.0

    def classify(self, row: dict) -> str:
        """comparable / baseline_missing / current_only / inactive.

        A zero target counts as no target: it is what an untargeted day looks
        like once the NULL has been summed.

        **This deliberately follows `SnapshotVsPolicySpine`, not `BaseSpine`.**
        The two disagree: the base maps "no baseline" to `current_only`, while
        the policy spine maps it to `baseline_missing`. The policy reading is the
        one that matches what these words have to mean here - nobody set a
        target, so the day is excluded from judgement rather than scored as a
        total miss. Choosing the base's mapping would have put every August day
        into the queue as a 100% shortfall.
        """
        current = self._read(row, self.CURRENT_KEYS)
        baseline = self._read(row, self.BASELINE_KEYS)
        has_target = baseline is not None and baseline != 0
        if current is None and not has_target:
            return kernel_spine.INACTIVE
        if not has_target:
            return kernel_spine.BASELINE_MISSING
        if current is None:
            return kernel_spine.CURRENT_ONLY
        return kernel_spine.COMPARABLE

    # --- scope ----------------------------------------------------------------

    def population_filter(self, scope: dict) -> str | None:
        """The configured branch population, as the report's own scan builds it."""
        members = list((scope or {}).get("comparable") or (scope or {}).get("population") or [])
        if not members:
            return None
        reference = (scope or {}).get("entity_reference")
        if not reference:
            return None
        values = ", ".join('"' + str(m).replace('"', '""') + '"' for m in members)
        return f"TREATAS({{{values}}}, {reference})"

    def denominator(self, rows: list[dict]) -> float | None:
        """Total TARGET across the rows - the base every shortfall share uses.

        Deliberately not the total actual: a shortfall is meaningful as a share
        of what was asked for, not of what happened to be achieved.
        """
        total = 0.0
        seen = False
        for row in rows or []:
            value = self._read(row, self.BASELINE_KEYS)
            if value is not None:
                total += value
                seen = True
        return total if seen else None

    # --- ranking and novelty ---------------------------------------------------

    def rank_components(self, member: dict, level: dict) -> dict:
        """Exposure-weighted, for the reason the year-on-year blend is.

        A tiny branch missing target by 90% must not outrank a large one missing
        by 5%; `share_of_target_pct` is what stops it.
        """
        return {
            "global_impact_pct": member.get("shortfall_share_pct"),
            "business_share_pct": member.get("share_of_target_pct"),
            "change_pct": member.get("attainment_gap_pct"),
            "blend": "impact_magnitude_unexpectedness",
        }

    def novelty_key(self, member: dict, context: dict) -> dict:
        """Anchored on the targeted day, not on the run date.

        Sales run ahead of targets on this model (to 2026-08-17 against a target
        that stops at 2026-07-31), so the anchor is the latest day that carries a
        target. Keying on the run date would mint a new story every morning for
        a position that has not moved.
        """
        return {
            "spine": self.kind,
            "member": member.get("member"),
            "role": member.get("role"),
            "finding": member.get("finding"),
            "anchor": (context or {}).get("anchor"),
        }

    def caveats(self) -> list[str]:
        return [
            "This report compares sales with target. It does not compare with last year - "
            "the data holds 2026 only.",
        ]


kernel_spine.register(TargetVsActualSpine.kind, TargetVsActualSpine)
