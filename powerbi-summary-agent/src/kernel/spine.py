"""What is this measurement compared against?

Until WP2 the answer was hard-coded: a `(current, prior, change)` triple, i.e.
this period against the same period last year. That triple *was* the type system
- `semantic_profiler` built it, `summary_coverage.is_comparable` required both
sides of it, `summary_materiality` divided by it, and a model without it produced
nothing at all. The WP0 probe showed exactly that: both live inventory models
returned `primary=unresolved, fact=unresolved, 0 drill dimensions`.

A **spine** names the comparison instead of assuming it. Sales YoY compares
against last year; Inventory Management compares against an agreed stock policy;
Target Tracker compares against a target. Same ranking, same reconciliation,
same rendering - different baseline.

Two things the live data forced into this design
------------------------------------------------
**A delta is not always a number of the same kind.** `delta_kind` distinguishes
an absolute movement from a share-point movement from a *distance outside a
band*. The inventory policy is expressed in **days of cover** - a SKU is excess
when Burn-Out Days exceeds its section threshold - so the movement is "9 days
past the limit", not a quantity of stock.

**The delta unit and the exposure unit differ.** That policy finding is *measured*
in days but *ranked* by the SAR value at risk. Collapsing them into one number is
how "SAR 9" or "733,478 days" gets printed. So a spine declares both, and they
are carried separately all the way to the page.

Nothing here computes anything for Sales YoY that was not already computed:
`PeriodOverPeriodSpine` delegates to the existing helpers so WP2 can be verified
byte-identical.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# --- classification vocabulary ------------------------------------------------
# The four states a member can be in relative to its baseline. Deliberately not
# a bool: "no baseline" is a distinct, reportable state, never a zero and never
# green (Non-negotiable 13).
COMPARABLE = "comparable"
BASELINE_MISSING = "baseline_missing"
CURRENT_ONLY = "current_only"
INACTIVE = "inactive"
CLASSIFICATIONS = (COMPARABLE, BASELINE_MISSING, CURRENT_ONLY, INACTIVE)

# --- delta kinds --------------------------------------------------------------
ABSOLUTE = "absolute"    # a signed movement in the measure's own unit
POINTS = "points"        # a movement in share points
DISTANCE = "distance"    # how far outside a policy band (may be one-sided)
NONE = "none"            # no baseline exists; there is no delta to state
DELTA_KINDS = (ABSOLUTE, POINTS, DISTANCE, NONE)


@runtime_checkable
class MeasurementSpine(Protocol):
    """The comparison a report is built on."""

    kind: str
    #: Manager-facing name for the baseline. Printed, so it must read as English:
    #: "the same period last year", "the agreed stock policy", "the target".
    baseline_label: str

    def measures(self) -> dict: ...
    def delta_expr(self) -> str: ...
    def delta_kind(self) -> str: ...
    def delta_unit(self) -> str: ...
    def exposure_unit(self) -> str: ...
    def pct(self, current: Any, baseline: Any) -> float | None: ...
    def classify(self, row: dict) -> str: ...
    def population_filter(self, scope: dict) -> str | None: ...
    def denominator(self, rows: list[dict]) -> float | None: ...
    def rank_components(self, member: dict, level: dict) -> dict: ...
    def novelty_key(self, member: dict, context: dict) -> dict: ...
    def caveats(self) -> list[str]: ...


class BaseSpine:
    """Shared defaults, so a spine declares only what makes it different.

    Every default is deliberately conservative: no population filter, no
    caveats, and a classification that reports a missing baseline rather than
    inventing one.
    """

    kind = "base"
    baseline_label = "the baseline"
    _delta_kind = ABSOLUTE
    _delta_unit = "value"
    _exposure_unit = "value"

    def measures(self) -> dict:
        return {}

    def delta_expr(self) -> str:
        return ""

    def delta_kind(self) -> str:
        return self._delta_kind

    def delta_unit(self) -> str:
        return self._delta_unit

    def exposure_unit(self) -> str:
        return self._exposure_unit

    def pct(self, current: Any, baseline: Any) -> float | None:
        current_val, baseline_val = _num(current), _num(baseline)
        if current_val is None or baseline_val is None or baseline_val == 0:
            return None
        return (current_val - baseline_val) / abs(baseline_val) * 100.0

    def classify(self, row: dict) -> str:
        current = _num(row.get("current"))
        baseline = _num(row.get("baseline", row.get("prior")))
        if current is None and baseline is None:
            return INACTIVE
        if baseline is None:
            return CURRENT_ONLY
        if current is None:
            return BASELINE_MISSING
        return COMPARABLE

    def population_filter(self, scope: dict) -> str | None:
        return None

    def denominator(self, rows: list[dict]) -> float | None:
        total = 0.0
        seen = False
        for row in rows:
            value = _num(row.get("current"))
            if value is not None:
                total += value
                seen = True
        return total if seen else None

    def rank_components(self, member: dict, level: dict) -> dict:
        """Named inputs the ranking blend consumes. A spine may add its own."""
        return {
            "global_impact_pct": member.get("global_impact_pct"),
            "business_share_pct": member.get("business_share_pct"),
            "change_pct": member.get("change_pct"),
        }

    def novelty_key(self, member: dict, context: dict) -> dict:
        return {
            "spine": self.kind,
            "member": member.get("member"),
            "role": member.get("role"),
        }

    def caveats(self) -> list[str]:
        return []

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} kind={self.kind!r}>"


def _num(value: Any) -> float | None:
    """Local copy of the numeric guard, so the kernel does not import a tool."""
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


# --- registry -----------------------------------------------------------------

SPINE_REGISTRY: dict[str, type] = {}


def register(kind: str, spine_class: type) -> type:
    """Register a spine class under its kind. Re-registering the same class is
    a no-op; a *different* class under a taken name is an error, because two
    reports resolving the same name to different arithmetic is the drift this
    registry exists to prevent."""
    existing = SPINE_REGISTRY.get(kind)
    if existing is not None and existing is not spine_class:
        raise ValueError(
            f"spine kind {kind!r} is already registered to {existing.__name__}; "
            f"refusing to rebind it to {spine_class.__name__}")
    SPINE_REGISTRY[kind] = spine_class
    return spine_class


def get(kind: str) -> type:
    try:
        return SPINE_REGISTRY[kind]
    except KeyError:
        raise KeyError(
            f"unknown spine kind {kind!r}; registered: "
            f"{', '.join(sorted(SPINE_REGISTRY)) or '(none)'}") from None


def available() -> tuple[str, ...]:
    return tuple(sorted(SPINE_REGISTRY))
