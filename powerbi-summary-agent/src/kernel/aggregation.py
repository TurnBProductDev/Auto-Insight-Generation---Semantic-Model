"""Does this number add up, and along which axis?

The failure this module exists to prevent is invisible downstream. A stock figure
summed across 30 snapshots is 30x too big, and **every existing reconciliation
check would pass**, because the parts and the whole were both summed the same
wrong way. Nothing later in the pipeline can detect it.

Measured on the live model (WP0, 2026-08-13), `SSR TREND[sku_stock_value]` over
its four snapshot dates:

    sum across all four   SAR 204,766,305.10
    latest snapshot        SAR  50,833,557.23
    overstatement           4.03x  across 4 snapshots

That is the failure, reproduced. It is why `metadata` alone is not allowed to
decide: `semantic_profiler._additive()` returns `True` for both a
`CALCULATE(SUM(...), LASTNONBLANK(...))` measure and a plain `SUM(...)` across
snapshots, so the safe measure and the 4x-wrong one are indistinguishable by
name or expression. Only arithmetic can tell them apart.

Two layers, on purpose
----------------------
:func:`judge` is pure - it takes observations and returns a verdict, so every
branch is testable offline with no auth and no model. :func:`verify` is the thin
wrapper that gathers those observations through an executor. The logic that
matters is therefore under test, which a query-issuing function would not be.

"Unverifiable" is a first-class verdict
---------------------------------------
Both live inventory facts hold exactly **one** snapshot. With one observation
there is nothing to sum across, so semi-additivity can be neither confirmed nor
refuted. Returning "additive - passed" there would be a lie of exactly the kind
Non-negotiable 13 forbids. The verdict is ``UNVERIFIABLE`` with the reason
stated, and the caller decides whether that is good enough to publish.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Sequence

#: How far the observed ratio may sit from 1.0 before a measure is judged not to
#: add up along the tested axis. Generous: real data carries rounding, and the
#: failure this catches is a factor of N, not a fraction of a percent.
ADDITIVE_TOLERANCE_PCT = 1.0

#: How close `sum / latest` must be to the number of periods before we call it
#: positive evidence of semi-additivity. The live measurement was 4.03 against 4
#: periods, i.e. 0.75% off - so this is comfortably wide without admitting a
#: genuinely additive series.
SEMI_ADDITIVE_TOLERANCE_PCT = 15.0


class AggregationClass(Enum):
    """How a measure may legitimately be combined."""

    #: Sums correctly over every axis, including time. Sales revenue.
    ADDITIVE = "additive"
    #: Sums over every axis EXCEPT time; over time take the last non-blank.
    #: Stock on hand, and the class that causes the Nx failure when ignored.
    SEMI_ADDITIVE_LAST = "semi_additive_last"
    #: Sums within one level but not across levels, because levels overlap.
    #: A SKU non-moving at three stores counted once per store, then rolled up.
    ADDITIVE_WITHIN_LEVEL = "additive_within_level"
    #: Never sums. A ratio, an average, a distinct count. Must be recomputed
    #: from its own numerator and denominator at each grain.
    NON_ADDITIVE_RATIO = "non_additive_ratio"
    #: A span of time attached to a state. Ages and days-of-cover: averaging is
    #: usually wrong and summing is always wrong.
    DURATION = "duration"

    @property
    def sums_over_time(self) -> bool:
        return self is AggregationClass.ADDITIVE

    @property
    def sums_over_members(self) -> bool:
        return self in (AggregationClass.ADDITIVE,
                        AggregationClass.SEMI_ADDITIVE_LAST,
                        AggregationClass.ADDITIVE_WITHIN_LEVEL)


class Verdict(Enum):
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class VerificationResult:
    """What the arithmetic actually showed."""

    claim: AggregationClass
    verdict: Verdict
    reason: str
    #: sum across the tested axis / value at the latest point. ~1 means it adds
    #: up; ~N means it is being N-times over-counted.
    observed_ratio: float | None = None
    period_count: int = 0
    detail: dict = field(default_factory=dict)

    @property
    def safe_to_sum_over_time(self) -> bool:
        """Only an ADDITIVE claim that was actually CONFIRMED earns this."""
        return (self.claim is AggregationClass.ADDITIVE
                and self.verdict is Verdict.CONFIRMED)

    @property
    def blocks_report(self) -> bool:
        """A refuted claim is a hard stop (brief Part 6.7)."""
        return self.verdict is Verdict.REFUTED

    def summary(self) -> str:
        ratio = "n/a" if self.observed_ratio is None else f"{self.observed_ratio:.2f}x"
        return (f"{self.claim.value}: {self.verdict.value} "
                f"(ratio={ratio}, periods={self.period_count}) - {self.reason}")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def judge(claim: AggregationClass,
          period_values: Sequence[Any],
          *,
          latest_value: Any = None,
          additive_tolerance_pct: float = ADDITIVE_TOLERANCE_PCT,
          semi_additive_tolerance_pct: float = SEMI_ADDITIVE_TOLERANCE_PCT
          ) -> VerificationResult:
    """Judge a claim against observations. Pure - no IO, no model, no auth.

    ``period_values`` is the measure evaluated at each point on the time axis,
    in order. ``latest_value`` is the measure evaluated with the whole axis in
    filter context; when omitted the last period is used, which is the correct
    reading for a last-non-blank measure.
    """
    values = [v for v in (_num(x) for x in period_values) if v is not None]
    count = len(values)
    latest = _num(latest_value)
    if latest is None and values:
        latest = values[-1]

    # A ratio or a duration makes no additivity claim to test; saying
    # "unverifiable" would imply we tried and failed.
    if claim in (AggregationClass.NON_ADDITIVE_RATIO, AggregationClass.DURATION):
        return VerificationResult(
            claim, Verdict.CONFIRMED,
            f"a {claim.value} measure makes no additivity claim over time; it must "
            f"be recomputed at each grain rather than combined",
            period_count=count)

    if count == 0:
        return VerificationResult(
            claim, Verdict.UNVERIFIABLE,
            "no values were observed on the time axis", period_count=0)

    if count == 1:
        # The live case for both inventory facts. Not a pass.
        return VerificationResult(
            claim, Verdict.UNVERIFIABLE,
            "only one point exists on the time axis, so there is nothing to sum "
            "across - semi-additivity can be neither confirmed nor refuted here",
            observed_ratio=None, period_count=1,
            detail={"latest": latest})

    total = sum(values)
    if latest is None or latest == 0:
        return VerificationResult(
            claim, Verdict.UNVERIFIABLE,
            "the latest value is zero or absent, so the ratio is undefined",
            period_count=count, detail={"sum": total})

    ratio = total / latest
    detail = {"sum": total, "latest": latest, "values": values}

    if claim is AggregationClass.ADDITIVE:
        # Additive means the axis total IS the sum. Anything materially above 1
        # means the measure is being counted once per period.
        if abs(ratio - 1.0) * 100.0 <= additive_tolerance_pct:
            return VerificationResult(
                claim, Verdict.CONFIRMED,
                "the sum across the axis equals the axis total, so the measure "
                "adds up over time",
                observed_ratio=ratio, period_count=count, detail=detail)
        return VerificationResult(
            claim, Verdict.REFUTED,
            f"summing across {count} points overstates the latest position by "
            f"{ratio:.2f}x - this measure does NOT add up over time and must not "
            f"be summed across it",
            observed_ratio=ratio, period_count=count, detail=detail)

    if claim in (AggregationClass.SEMI_ADDITIVE_LAST,
                 AggregationClass.ADDITIVE_WITHIN_LEVEL):
        # Positive evidence: the naive sum should be ~N times the true position.
        expected = float(count)
        off_by_pct = abs(ratio - expected) / expected * 100.0
        if off_by_pct <= semi_additive_tolerance_pct:
            return VerificationResult(
                claim, Verdict.CONFIRMED,
                f"summing across {count} points returns {ratio:.2f}x the latest "
                f"position, which is the expected ~{count}x - confirmed as "
                f"{claim.value}; never sum it across time",
                observed_ratio=ratio, period_count=count, detail=detail)
        if abs(ratio - 1.0) * 100.0 <= additive_tolerance_pct:
            return VerificationResult(
                claim, Verdict.REFUTED,
                f"the measure was declared {claim.value} but the sum across "
                f"{count} points equals the axis total, so it is additive over "
                f"time - the declaration is wrong",
                observed_ratio=ratio, period_count=count, detail=detail)
        return VerificationResult(
            claim, Verdict.UNVERIFIABLE,
            f"the sum is {ratio:.2f}x the latest position, which matches neither "
            f"an additive measure (~1x) nor a per-period one (~{count}x); the "
            f"series may be changing in size between points",
            observed_ratio=ratio, period_count=count, detail=detail)

    return VerificationResult(  # pragma: no cover - enum is exhaustive above
        claim, Verdict.UNVERIFIABLE,
        f"no verification is defined for {claim.value}", period_count=count)


def verify(claim: AggregationClass,
           measure: str,
           executor: Callable[[str], Sequence[Any]],
           *,
           time_axis: str | None = None,
           **judge_kwargs) -> VerificationResult:
    """Gather observations through ``executor`` and judge the claim.

    ``executor`` takes DAX and returns the rows it produced; it is injected so
    the kernel neither builds a connection nor depends on an executor module.
    With no ``time_axis`` there is no axis to test, which is itself reported
    rather than assumed safe.
    """
    if not time_axis:
        return VerificationResult(
            claim, Verdict.UNVERIFIABLE,
            "no time axis was supplied, so additivity over time was not tested",
            detail={"measure": measure})

    dax = (f"EVALUATE SUMMARIZECOLUMNS({time_axis}, \"v\", {measure})\n"
           f"ORDER BY {time_axis}")
    try:
        rows = executor(dax) or []
    except Exception as exc:  # a probe must never take the run down
        return VerificationResult(
            claim, Verdict.UNVERIFIABLE,
            f"the verification query failed: {exc}",
            detail={"measure": measure, "dax": dax})

    values = [_pick_value(row) for row in rows]
    result = judge(claim, values, **judge_kwargs)
    return VerificationResult(
        result.claim, result.verdict, result.reason,
        observed_ratio=result.observed_ratio, period_count=result.period_count,
        detail={**result.detail, "measure": measure, "time_axis": time_axis})


def _pick_value(row: Any) -> Any:
    """The measure column out of one returned row, whatever it got named."""
    if not isinstance(row, dict):
        return row
    for key, value in row.items():
        cleaned = str(key).strip("[]").lower()
        if cleaned == "v":
            return value
    # Fall back to the only numeric column, if there is exactly one.
    numbers = [v for v in row.values() if _num(v) is not None]
    return numbers[0] if len(numbers) == 1 else None


def classify_from_metadata(measure: dict) -> AggregationClass:
    """A first guess from metadata, to be *verified*, never trusted.

    Deliberately separate from :func:`judge`. `semantic_profiler._additive()`
    cannot tell a last-non-blank stock measure from a plain sum across snapshots
    - both contain `SUM(` - so this looks for the pattern that distinguishes
    them and still hands the answer to arithmetic for confirmation.
    """
    expression = str(measure.get("expression") or "").upper()
    name = str(measure.get("name") or "").upper()
    fmt = str(measure.get("format_string") or "")

    if any(token in expression for token in ("DIVIDE(", "AVERAGE(", "AVERAGEX(",
                                             "DISTINCTCOUNT(")) or "%" in fmt:
        return AggregationClass.NON_ADDITIVE_RATIO
    if any(token in expression for token in ("LASTNONBLANK", "LASTDATE",
                                             "LASTNONBLANKVALUE")):
        return AggregationClass.SEMI_ADDITIVE_LAST
    if any(token in name for token in ("DAYS", "AGE", "COVER", "BURNOUT",
                                       "BURN_OUT")):
        return AggregationClass.DURATION
    if "SUM(" in expression or "SUMX(" in expression:
        return AggregationClass.ADDITIVE
    return AggregationClass.NON_ADDITIVE_RATIO
