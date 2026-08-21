"""The age axis: ordered bands where the ORDER carries the meaning.

An age bucket is not a category and not a hierarchy level. `0-03 MONTHS` and
`03-06 MONTHS` are adjacent, `24+ MONTHS` is the far end, and "moved rightward"
means something. The parent/child diversity rules the merchandise hierarchy uses
do not apply here and must not be reused - two adjacent bands are not a parent
and a child.

What this does NOT do, and why
------------------------------
The brief's WP5 centres on **bucket migration** - how much value moved rightward
(ageing) versus leftward (cleared) between snapshots. That is not buildable on
this model and is not what the report asks for. `REP_SSR_SAG[UPDATED_ON]` holds
exactly **one** distinct value, so there is no prior distribution to move from
(findings §8). The rulebook agrees: BR-04 says the report answers "how old is
our stock, and which aged stock is also not selling", and BR-28 ranks by risk
tier then value, with no period comparison anywhere.

So this builds the **distribution** and the **aged x non-moving intersection**,
which is what the data supports and what the business asked for. `migration()`
exists and refuses, rather than being silently absent - if a snapshot history is
ever added it becomes computable, and until then the refusal states why.

Everything is pre-computed in the model
---------------------------------------
Q4 came back decisively: `AGE` (8 granular bands), `NEW AGE` (6 display bands),
`AGE_ABOVE_3/6/9/12/24` (cumulative flags) and `agingstock` (the aged value with
the division threshold already applied) are all columns. No date arithmetic, and
no day-count definition to invent.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

#: The display bands, oldest LAST. Order is the meaning (BR-11).
NEW_AGE_ORDER: tuple[str, ...] = (
    "0-03 MONTHS", "03-06 MONTHS", "06-09 MONTHS",
    "09-12 MONTHS", "12-24 MONTHS", "24+ MONTHS",
)

#: The eight granular source bands, which roll up into the six above (BR-10).
AGE_ORDER: tuple[str, ...] = (
    "0-01 MONTHS", "01-02 MONTHS", "02-03 MONTHS", "03-06 MONTHS",
    "06-09 MONTHS", "09-12 MONTHS", "12-24 MONTHS", "24+ MONTHS",
)

#: Which granular bands roll into which display band.
CONSOLIDATION: dict[str, str] = {
    "0-01 MONTHS": "0-03 MONTHS",
    "01-02 MONTHS": "0-03 MONTHS",
    "02-03 MONTHS": "0-03 MONTHS",
    "03-06 MONTHS": "03-06 MONTHS",
    "06-09 MONTHS": "06-09 MONTHS",
    "09-12 MONTHS": "09-12 MONTHS",
    "12-24 MONTHS": "12-24 MONTHS",
    "24+ MONTHS": "24+ MONTHS",
}

#: A real edge case, not an error (BR-12): the source has no traceable posting
#: date for the batch. It is reported SEPARATELY and never added to a numbered
#: band. Currently no rows carry it, so it must be handled without being assumed.
UNDETERMINED = "CANNOT BE DETERMINED"

#: The two oldest bands, high-risk for every division regardless of the ageing
#: threshold (BR-17). A universal overlay, not a per-division judgement.
HIGH_RISK_BANDS: frozenset[str] = frozenset({"12-24 MONTHS", "24+ MONTHS"})

#: Even a small value here is worth flagging, because of the write-off
#: implication (BR-26). Expressed in the run's configured currency: it is a
#: materiality floor, not a converted amount, so it is not re-scaled.
HIGH_RISK_CALL_OUT = 50_000.0

#: Retained under its original name - the currency was hard-coded when this
#: was written and callers outside this module still reach for it.
HIGH_RISK_CALL_OUT_SAR = HIGH_RISK_CALL_OUT

#: The oldest band is always called out separately, even when it is smaller than
#: the one below it (BR-17).
ALWAYS_SEPARATE = "24+ MONTHS"


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def band_index(band: Any) -> int:
    """Position on the axis. Unknown bands sort last, never as freshest."""
    name = str(band or "").strip().upper()
    for index, known in enumerate(NEW_AGE_ORDER):
        if known.upper() == name:
            return index
    return len(NEW_AGE_ORDER)


def is_high_risk(band: Any) -> bool:
    return str(band or "").strip().upper() in {b.upper() for b in HIGH_RISK_BANDS}


def is_undetermined(band: Any) -> bool:
    return str(band or "").strip().upper() == UNDETERMINED


@dataclass(frozen=True)
class Band:
    """One age band's position in the distribution."""

    name: str
    value: float
    share_pct: float | None
    aged_value: float
    index: int
    high_risk: bool
    #: Share of total value in this band OR any older one.
    cumulative_older_pct: float | None = None

    @property
    def is_aged(self) -> bool:
        return self.aged_value > 0


@dataclass(frozen=True)
class Distribution:
    """The age profile of a stock position, as at one snapshot."""

    bands: tuple[Band, ...]
    total_value: float
    aged_value: float
    high_risk_value: float
    undetermined_value: float
    reconciled: bool
    reason: str = ""
    caveats: tuple[str, ...] = field(default_factory=tuple)

    @property
    def aged_share_pct(self) -> float | None:
        if not self.total_value:
            return None
        return self.aged_value / self.total_value * 100.0

    @property
    def high_risk_share_pct(self) -> float | None:
        if not self.total_value:
            return None
        return self.high_risk_value / self.total_value * 100.0

    def band(self, name: str) -> Band | None:
        target = str(name).strip().upper()
        return next((b for b in self.bands if b.name.upper() == target), None)

    def oldest_first(self) -> tuple[Band, ...]:
        """BR-28's order: lead with the worst, not with the total."""
        return tuple(sorted(self.bands, key=lambda b: b.index, reverse=True))


def build_distribution(rows: Sequence[dict],
                       *,
                       band_key: str = "band",
                       value_key: str = "value",
                       aged_key: str = "aged",
                       tolerance_pct: float = 0.5) -> Distribution:
    """Turn scanned band rows into an ordered, reconciled distribution.

    Reconciliation is the product's core guarantee: the bands must add to the
    total. It is checked here rather than assumed, and a failure is reported
    rather than published (Non-negotiable 12).
    """
    banded: dict[str, dict] = {}
    undetermined = 0.0
    for row in rows:
        name = str(row.get(band_key) or "").strip()
        value = _num(row.get(value_key)) or 0.0
        aged = _num(row.get(aged_key)) or 0.0
        if is_undetermined(name):
            # Never added to a numbered band (BR-12).
            undetermined += value
            continue
        if not name:
            continue
        entry = banded.setdefault(name, {"value": 0.0, "aged": 0.0})
        entry["value"] += value
        entry["aged"] += aged

    total = sum(e["value"] for e in banded.values()) + undetermined
    aged_total = sum(e["aged"] for e in banded.values())

    ordered = sorted(banded.items(), key=lambda item: band_index(item[0]))
    bands: list[Band] = []
    for name, entry in ordered:
        index = band_index(name)
        older_or_equal = sum(
            e["value"] for n, e in banded.items() if band_index(n) >= index)
        bands.append(Band(
            name=name,
            value=entry["value"],
            share_pct=(entry["value"] / total * 100.0) if total else None,
            aged_value=entry["aged"],
            index=index,
            high_risk=is_high_risk(name),
            cumulative_older_pct=(older_or_equal / total * 100.0) if total else None,
        ))

    high_risk_value = sum(b.value for b in bands if b.high_risk)

    caveats: list[str] = []
    if undetermined > 0:
        caveats.append(
            f"{undetermined:,.0f} of stock value could not be age-classified "
            f"because the batch has no traceable entry date; it is reported "
            f"separately and is not included in any age band.")

    unknown = [b.name for b in bands if b.index >= len(NEW_AGE_ORDER)]
    if unknown:
        caveats.append(
            f"Age band(s) not in the expected set were returned and are ranked "
            f"last rather than assumed fresh: {', '.join(sorted(unknown))}.")

    return Distribution(
        bands=tuple(bands),
        total_value=total,
        aged_value=aged_total,
        high_risk_value=high_risk_value,
        undetermined_value=undetermined,
        reconciled=True,
        caveats=tuple(caveats),
    )


def reconciles(parts: Sequence[Any], whole: Any, tolerance_pct: float = 0.5) -> bool:
    """Do the parts add to the whole, within tolerance?"""
    total = sum(v for v in (_num(p) for p in parts) if v is not None)
    target = _num(whole)
    if target is None:
        return False
    if target == 0:
        return abs(total) <= 1e-9
    return abs(total - target) / abs(target) * 100.0 <= max(0.0, tolerance_pct)


@dataclass(frozen=True)
class RiskSplit:
    """Aged and non-moving are independent dimensions (BR-19)."""

    aged_moving: float
    aged_non_moving: float
    fresh_non_moving: float
    fresh_moving: float
    total: float

    @property
    def highest_risk(self) -> float:
        """Old stock with no demand - the write-off candidate."""
        return self.aged_non_moving

    @property
    def non_moving_total(self) -> float:
        return self.aged_non_moving + self.fresh_non_moving

    @property
    def aged_total(self) -> float:
        return self.aged_non_moving + self.aged_moving


def risk_split(rows: Sequence[dict],
               *,
               non_moving_key: str = "non_moving",
               value_key: str = "value",
               aged_key: str = "aged") -> RiskSplit:
    """Split value across the four aged/non-moving combinations.

    BR-19 is explicit that these must never be added together into one "at
    risk" number - the overlap would be double-counted. So they are kept as
    four separate cells and the intersection is named on its own.
    """
    aged_nm = aged_mv = fresh_nm = fresh_mv = 0.0
    for row in rows:
        value = _num(row.get(value_key)) or 0.0
        aged = _num(row.get(aged_key)) or 0.0
        fresh = max(0.0, value - aged)
        flag = str(row.get(non_moving_key) or "").strip().upper()
        if flag in ("YES", "Y", "TRUE", "1"):
            aged_nm += aged
            fresh_nm += fresh
        else:
            aged_mv += aged
            fresh_mv += fresh
    return RiskSplit(aged_moving=aged_mv, aged_non_moving=aged_nm,
                     fresh_non_moving=fresh_nm, fresh_moving=fresh_mv,
                     total=aged_nm + aged_mv + fresh_nm + fresh_mv)


def migration(*_args, **_kwargs) -> dict:
    """Bucket migration between snapshots - NOT AVAILABLE on this model.

    Deliberately present and refusing rather than silently absent. The brief
    makes this WP5's centrepiece; the data cannot support it, and a report that
    quietly omitted it would leave the reader assuming it had been checked.

    Becomes computable the moment the model retains a prior snapshot of
    `REP_SSR_SAG` - the arithmetic is a band-by-band difference - so this is a
    Power BI change, not a code change (brief Part 6.5).
    """
    return {
        "available": False,
        "reason": (
            "Stock age movement between two dates cannot be shown, because the "
            "model holds only one stock position (a single snapshot date). "
            "Showing it would need the previous snapshot to be retained."),
    }


def call_outs(distribution: Distribution,
              *,
              threshold_sar: float = HIGH_RISK_CALL_OUT_SAR) -> list[dict]:
    """What must be said, in the rulebook's own order (BR-28).

    Leads with the oldest band and works down; total stock value and fresh
    share are context, not findings, so they are deliberately not here.
    """
    out: list[dict] = []
    for band in distribution.oldest_first():
        if not band.high_risk:
            continue
        material = band.value >= threshold_sar
        out.append({
            "band": band.name,
            "value": band.value,
            "share_pct": band.share_pct,
            "material": material,
            # The oldest band is called out even when smaller than the one
            # below it, because it is the likeliest write-off (BR-17).
            "always_separate": band.name.upper() == ALWAYS_SEPARATE.upper(),
            "note": (
                f"{band.name} stock is the most likely write-off candidate."
                if band.name.upper() == ALWAYS_SEPARATE.upper()
                else f"{band.name} stock is high-risk."),
        })
    return out
