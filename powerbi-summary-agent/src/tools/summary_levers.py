"""The three-lever spine: Revenue = Transactions x Basket Size x Price.

Deterministic, pure functions - no state, no IO, no LLM. Summary-only; imports no
``insight_*`` module.

Why a third lever when ``summary_overall._bridge`` already splits volume from
rate/mix: the two-way bridge answers "did we sell more items, or earn more per
item". It cannot separate *more shopping trips* from *fuller baskets*, and those
two have opposite management responses - a footfall problem is a traffic problem,
a basket problem is a range/cross-sell problem. Splitting quantity into
transactions x items-per-transaction is what turns "revenue -8%" into "revenue
-8% because baskets thinned while footfall held".

The decomposition is sequential and therefore *exact* (the three effects sum to
the revenue change), using the same construction as the existing two-way bridge:

    Revenue = T * S * P        T = transactions, S = units/T, P = revenue/units
    effect_T = (T1 - T0) * S0 * P0
    effect_S = T1 * (S1 - S0) * P0
    effect_P = T1 * S1 * (P1 - P0)

Sequential attribution is order-dependent (the interaction terms have to be
charged to somebody). The order here - traffic, then basket, then price - is the
retail reading order, and ``note`` says so rather than implying the split is
unique. Growth *factors* multiply back exactly regardless of order, so
``reconciles`` is the honest check.
"""

from __future__ import annotations

import math
from typing import Any

# A lever inside this band is read as "held" rather than up or down. Naming a
# +0.1% move "higher prices" is noise dressed as a finding.
FLAT_PCT = 0.5

#: Sign triple (transactions, basket size, price) -> the rulebook-style state
#: name. Sign is -1/0/+1 after the flat band is applied. Every one of the 27
#: combinations resolves: the eight strict corners are named specifically, and
#: anything with a held lever falls through to a two-lever or single-lever name.
_STATES: dict[tuple[int, int, int], str] = {
    (1, 1, 1): "Absolute growth",
    (1, 1, -1): "Successful promotion",
    (1, -1, 1): "Thinner baskets, higher prices",
    (1, -1, -1): "More transactions, less value",
    (-1, 1, 1): "Fewer, richer customers",
    (-1, 1, -1): "Consolidation",
    (-1, -1, 1): "Price masking",
    (-1, -1, -1): "Severe decline",
}

#: States where the levers pull against each other, so the revenue direction is a
#: question of size and cannot be read off the pattern. The rulebook marks these
#: "Depends" and warns against calling them a success on revenue alone - so their
#: name must never stand alone as a verdict. On the live scanb model a department
#: down -12.88% was labelled "Successful promotion" with nothing to contradict it.
_DEPENDS: frozenset = frozenset({
    (1, 1, -1), (1, -1, 1), (1, -1, -1), (-1, 1, 1), (-1, 1, -1), (-1, -1, 1),
})

_LEVER_WORDS = {
    "transactions": ("more transactions", "fewer transactions"),
    "basket_size": ("fuller baskets", "thinner baskets"),
    "price": ("higher prices and mix", "lower prices and mix"),
}

LEVER_LABELS = {
    "transactions": "Transactions",
    "basket_size": "Basket Size",
    "price": "Price",
}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _fmt(value: Any, signed: bool = True) -> str:
    """Compact signed money/count display, identical in style to summary_overall."""
    number = _num(value)
    if number is None:
        return str(value)
    sign = "+" if signed else ""
    magnitude = abs(number)
    if magnitude >= 1_000_000_000:
        return f"{number / 1_000_000_000:{sign}.2f}B"
    if magnitude >= 1_000_000:
        return f"{number / 1_000_000:{sign}.1f}M"
    if magnitude >= 1_000:
        return f"{number / 1_000:{sign}.1f}K"
    return f"{number:{sign}.0f}"


def _pct(value: Any, decimals: int = 2) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:+.{decimals}f}%"


def _change_pct(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or not prior:
        return None
    return (current - prior) / abs(prior) * 100.0


def _sign(change_pct: float | None, flat_pct: float = FLAT_PCT) -> int:
    if change_pct is None:
        return 0
    if change_pct > flat_pct:
        return 1
    if change_pct < -flat_pct:
        return -1
    return 0


def derived_measures(families: dict) -> dict:
    """Six comparable retail measures from the scanned families.

    Revenue / Transactions / Units come straight from the model. Basket Value,
    Basket Size and Price are ratios of those, computed here so one definition
    holds everywhere in the document:

        Basket Value = revenue / transactions   (spend per bill)
        Basket Size  = units   / transactions   (items per bill)
        Price        = revenue / units          (average selling price)

    A measure whose inputs are missing is simply absent from the result - never
    zero-filled, so a card for it is omitted rather than shown as a false 0.
    """
    revenue = families.get("revenue") or {}
    units = families.get("quantity") or {}
    bills = families.get("transactions") or {}

    def phase(bundle: dict, key: str) -> float | None:
        return _num(bundle.get(key))

    out: dict = {}

    def add(key: str, label: str, current: float | None, prior: float | None,
            unit: str, decimals: int) -> None:
        if current is None or prior is None:
            return
        out[key] = {
            "key": key,
            "label": label,
            "current": current,
            "prior": prior,
            "change": current - prior,
            "change_pct": _change_pct(current, prior),
            "unit": unit,
            "decimals": decimals,
        }

    def ratio(numerator: dict, denominator: dict, key: str, label: str,
              unit: str, decimals: int) -> None:
        n_c, n_p = phase(numerator, "current"), phase(numerator, "prior")
        d_c, d_p = phase(denominator, "current"), phase(denominator, "prior")
        if None in (n_c, n_p, d_c, d_p) or not d_c or not d_p:
            return
        add(key, label, n_c / d_c, n_p / d_p, unit, decimals)

    add("revenue", "Revenue", phase(revenue, "current"), phase(revenue, "prior"), "money", 0)
    add("transactions", "Transactions", phase(bills, "current"), phase(bills, "prior"), "count", 0)
    add("units", "Units", phase(units, "current"), phase(units, "prior"), "count", 0)
    ratio(revenue, bills, "basket_value", "Basket Value", "money", 2)
    ratio(units, bills, "basket_size", "Basket Size", "items", 2)
    ratio(revenue, units, "price", "Price", "money", 2)
    return out


def three_lever_bridge(families: dict, tolerance_pct: float = 2.0) -> dict | None:
    """Exact Transactions / Basket Size / Price decomposition of the revenue move.

    Returns ``None`` when the model does not expose all three inputs (revenue,
    units and transactions) - the caller then keeps the two-way volume vs
    rate/mix bridge rather than inventing a lever.
    """
    measures = derived_measures(families)
    needed = ("revenue", "transactions", "basket_size", "price")
    if any(key not in measures for key in needed):
        return None

    bills, size, price = measures["transactions"], measures["basket_size"], measures["price"]
    t0, t1 = bills["prior"], bills["current"]
    s0, s1 = size["prior"], size["current"]
    p0, p1 = price["prior"], price["current"]

    effect_t = (t1 - t0) * s0 * p0
    effect_s = t1 * (s1 - s0) * p0
    effect_p = t1 * s1 * (p1 - p0)
    total = effect_t + effect_s + effect_p
    change = measures["revenue"]["change"]
    limit = abs(change) * (tolerance_pct / 100.0) if change else 1.0
    reconciles = abs(total - change) <= max(limit, abs(change) * 1e-9, 1.0)

    factors = {
        "transactions": (t1 / t0) if t0 else None,
        "basket_size": (s1 / s0) if s0 else None,
        "price": (p1 / p0) if p0 else None,
    }
    product = 1.0
    for value in factors.values():
        if value is None:
            product = None
            break
        product *= value

    return {
        "effects": {"transactions": effect_t, "basket_size": effect_s, "price": effect_p},
        "levers": {
            "transactions": bills["change_pct"],
            "basket_size": size["change_pct"],
            "price": price["change_pct"],
        },
        "growth_factors": factors,
        "factor_product_pct": (product - 1.0) * 100.0 if product is not None else None,
        "revenue_change": change,
        "revenue_change_pct": measures["revenue"]["change_pct"],
        "total": total,
        "reconciles": reconciles,
        "state": lever_state(
            bills["change_pct"], size["change_pct"], price["change_pct"],
            revenue_pct=measures["revenue"]["change_pct"],
        ),
        "dominant": dominant_lever(
            {"transactions": effect_t, "basket_size": effect_s, "price": effect_p}
        ),
        "note": (
            "Growth rates multiply rather than add. Effects are charged in reading "
            "order - transactions, then basket size, then price - so they sum "
            "exactly to the revenue change; a different order moves the shared "
            "interaction between levers."
        ),
    }


def lever_state(transactions_pct: float | None, basket_size_pct: float | None,
                price_pct: float | None, flat_pct: float = FLAT_PCT,
                revenue_pct: float | None = None) -> str:
    """Name the lever pattern in plain retail language, deterministically.

    Code owns this naming rather than the LLM so the same lever pattern always
    reads the same way across entities, periods and runs. Names follow the
    rulebook's state matrix so the report and the rulebook use one vocabulary.

    When the levers pull against each other the revenue direction does not follow
    from the pattern, so a name like "Successful promotion" cannot stand alone -
    it has been observed on a department whose revenue fell 12.88%. Pass
    ``revenue_pct`` and the computed direction is appended, which is exactly what
    the rulebook's "Depends" verdict requires.
    """
    signs = (
        _sign(transactions_pct, flat_pct),
        _sign(basket_size_pct, flat_pct),
        _sign(price_pct, flat_pct),
    )
    named = _STATES.get(signs)
    if named:
        direction = _num(revenue_pct)
        if signs in _DEPENDS and direction is not None:
            return f"{named} - revenue {'up' if direction >= 0 else 'down'}"
        return named
    moved = [
        (key, sign)
        for key, sign in zip(("transactions", "basket_size", "price"), signs)
        if sign
    ]
    if not moved:
        return "Broadly flat on every lever"
    parts = [_LEVER_WORDS[key][0 if sign > 0 else 1] for key, sign in moved]
    if len(parts) == 1:
        return parts[0].capitalize() + ", other levers held"
    return (", ".join(parts[:-1]) + " and " + parts[-1]).capitalize()


def dominant_lever(effects: dict) -> str | None:
    """The lever that moved revenue most in absolute money terms."""
    ranked = [
        (abs(value), key) for key, value in (effects or {}).items()
        if _num(value) is not None
    ]
    return max(ranked)[1] if ranked else None


def growth_quality(bridge: dict | None) -> dict | None:
    """How concentrated the revenue move is in a single lever.

    A move carried by one lever is more fragile than the same move spread over
    three, and the headline percentage cannot show that. ``share_pct`` is the
    dominant lever's share of the gross (absolute) lever movement, so offsetting
    levers do not cancel into a misleadingly tidy 100%.
    """
    if not bridge or not bridge.get("reconciles"):
        return None
    effects = {key: _num(value) for key, value in (bridge.get("effects") or {}).items()}
    effects = {key: value for key, value in effects.items() if value is not None}
    if not effects:
        return None
    gross = sum(abs(value) for value in effects.values())
    if not gross:
        return None
    lead = dominant_lever(effects)
    share = abs(effects[lead]) / gross * 100.0
    return {
        "lever": lead,
        "lever_label": LEVER_LABELS.get(lead, lead),
        "share_pct": share,
        "fragile": share >= 60.0,
        "statement": (
            f"{LEVER_LABELS.get(lead, lead)} accounts for {share:.0f}% of the total "
            "lever movement, so the result rests mainly on one lever."
            if share >= 60.0 else
            f"No single lever dominates - the largest, {LEVER_LABELS.get(lead, lead)}, "
            f"is {share:.0f}% of the total lever movement."
        ),
    }


def entity_levers(row: dict, aliases: dict, flat_pct: float = FLAT_PCT) -> dict | None:
    """Per-entity three levers from one multi-measure scan row.

    ``aliases`` maps ``{family: {phase: column}}`` as produced by the lever scan.
    A family that exposes no prior measure is reconstructed from its **change**
    measure (``prior = current - change``) - real models often publish "bills
    CURRENT" and "bills growth" without a named "bills PAST", and refusing that
    shape would disable the three-lever read on exactly those models. This is the
    same arithmetic the overall comparison facts already rely on.

    Returns ``None`` when the row still cannot support all three levers, so a
    card degrades to its revenue story instead of showing invented levers.
    """
    families: dict = {}
    for family, phases in (aliases or {}).items():
        current = _num(row.get(phases.get("current")))
        if current is None:
            continue
        prior = _num(row.get(phases.get("prior"))) if phases.get("prior") else None
        if prior is None and phases.get("change"):
            change = _num(row.get(phases["change"]))
            if change is not None:
                prior = current - change
        if prior is None:
            continue
        families[family] = {"current": current, "prior": prior}
    bridge = three_lever_bridge(families)
    if not bridge:
        return None
    bridge["measures"] = derived_measures(families)
    return bridge


def lever_facts(bridge: dict | None, subject: str = "Overall",
                comparison: str = "the comparison period",
                prefix: str = "OVERALL") -> list[dict]:
    """All three lever effects as supported facts, in the shape validation reads.

    Every side is promoted - not only the dominant one - so an offsetting lever
    can never be quietly dropped from the narrative ("footfall added +3.7M while
    thinner baskets removed -5.2M").
    """
    if not bridge or not bridge.get("reconciles"):
        return []
    effects = bridge.get("effects") or {}
    levers = bridge.get("levers") or {}
    facts: list[dict] = []
    for key in ("transactions", "basket_size", "price"):
        effect = _num(effects.get(key))
        if effect is None:
            continue
        label = LEVER_LABELS[key]
        moved = _LEVER_WORDS[key][0 if effect >= 0 else 1]
        pct_text = _pct(levers.get(key))
        facts.append({
            "fact_id": f"{prefix}_LEVER_{key.upper()}",
            "fact_kind": "lever",
            "subject": subject,
            "subject_role": "focus",
            "detail_role": "driver",
            "metric": f"{label} effect on revenue",
            "display_value": _fmt(effect),
            "raw_value": effect,
            "statement": (
                f"{label} moved {pct_text} versus {comparison}, so {moved} "
                f"{'added' if effect >= 0 else 'removed'} {_fmt(effect)} of revenue."
            ),
        })
    return facts


def waterfall_steps(bridge: dict | None, prior_revenue: float | None,
                    current_revenue: float | None) -> list[dict] | None:
    """Prior -> three lever effects -> current, ready for a waterfall chart.

    Returned in chart-agnostic form (label / kind / value); the renderer owns
    geometry. ``None`` when the bridge does not reconcile, because a waterfall
    whose bars do not close is worse than no waterfall.
    """
    if not bridge or not bridge.get("reconciles"):
        return None
    start, end = _num(prior_revenue), _num(current_revenue)
    if start is None or end is None:
        return None
    effects = bridge.get("effects") or {}
    steps: list[dict] = [{"label": "Prior", "kind": "total", "value": start}]
    for key in ("transactions", "basket_size", "price"):
        value = _num(effects.get(key))
        if value is None:
            return None
        steps.append({
            "label": LEVER_LABELS[key],
            "kind": "up" if value >= 0 else "down",
            "value": value,
        })
    steps.append({"label": "Current", "kind": "total", "value": end})
    return steps
