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
