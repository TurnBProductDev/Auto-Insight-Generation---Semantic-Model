"""The Inventory Health Score, as the semantic model publishes it.

The score is the model's own, not a composite invented here. `_HEALTH SCORE
MEASURES` defines:

    Total Points Lost      = the six `Category X Risk` measures, summed
    Inventory Health Score = MAX(0, 100 - that sum)

so those six measures *are* the authoritative points. Every SKU starts at 100
and loses points to six risks, each capped at 25.

Each risk is rebuilt from its own dimensions rather than averaged from the level
below, and this module recomputes that rebuild and **asserts it closes**. It is
checked rather than trusted for a specific reason: the weights changed under us.

The weights changed, and that is why they are not hard-coded silently
--------------------------------------------------------------------
`docs/dashboard-reference/README.md` documents the rebuild as *value impact
(50%), SKU breadth (30%), duration or severity (20%); 70/30 for damage*. Read
out of the live model on 2026-08-21, every one of the six is now **40/30/30**
(damage still 70/30). Rebuilding with the documented weights misses `Total
Points Lost` by 5.85 points and reconciles at no scope at all.

So :data:`DIMENSION_WEIGHTS` records what the model actually does, and
:func:`build` proves it every run. If the model is revised again the rebuild
stops closing, `dimensions_reconcile` goes false, and the page drops the "how it
is worked out" panel rather than printing weights that are no longer true. The
score, the bands and the waterfall are unaffected, because they read the
published points directly.

Two naming clashes the page states rather than hides
----------------------------------------------------
The model names one risk **Dead Stock**; BR-03 bans that phrase for the
classification the business calls **Non-Moving**, and they are the same thing.
The model says *Verge of Stockout*; BR-17 says *On the Verge of Stockout*. Both
carry the business term with the model's own measure name printed beside it, so
a user can still find it in the model and the page can never drift from it.
"""

from __future__ import annotations

from typing import Any, Sequence

#: How each risk is rebuilt, read out of the live model rather than from the
#: methodology document. `(scan field, weight)`, and the weights sum to 1.0.
DIMENSION_WEIGHTS: dict[str, tuple[tuple[str, str, float], ...]] = {
    "excess": (("excess_value_impact", "Value impact", 0.4),
               ("excess_sku_impact", "SKU breadth", 0.3),
               ("excess_duration_impact", "Duration", 0.3)),
    "ageing": (("ageing_value_impact", "Value impact", 0.4),
               ("ageing_sku_impact", "SKU breadth", 0.3),
               ("ageing_severity_impact", "Severity", 0.3)),
    "dead": (("dead_value_impact", "Value impact", 0.4),
             ("dead_sku_impact", "SKU breadth", 0.3),
             ("dead_duration_impact", "Duration", 0.3)),
    "oos": (("oos_sales_impact", "Sales impact", 0.4),
            ("oos_sku_impact", "SKU breadth", 0.3),
            ("oos_severity_impact", "Segment severity", 0.3)),
    "verge": (("verge_sales_impact", "Sales impact", 0.4),
              ("verge_sku_impact", "SKU breadth", 0.3),
              ("verge_severity_impact", "Segment severity", 0.3)),
    "damage": (("damage_value_impact", "Value impact", 0.7),
               ("damage_sku_impact", "SKU breadth", 0.3)),
}

#: The most a single risk may cost, and the multiplier the model applies.
RISK_CAP = 25.0

#: Business names, and the model's own measure name where the two differ. The
#: clash is printed, never resolved by deleting one side (BR-03 vs the model).
RISK_LABELS: dict[str, tuple[str, str]] = {
    "excess": ("Excess Stock", ""),
    "ageing": ("Ageing Stock", ""),
    "dead": ("Non-Moving", "Dead Stock"),
    "oos": ("Out of Stock", ""),
    "verge": ("On the Verge of Stockout", "Verge of Stockout"),
    "damage": ("Damage", ""),
}

#: The methodology's bands, not a design choice.
BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "Excellent"),
    (80.0, "Healthy"),
    (70.0, "Watch"),
    (60.0, "At Risk"),
    (0.0, "Critical"),
)

#: How close the rebuild must come to the published points to count as closing.
TOLERANCE = 1e-6


def band(score: Any) -> str | None:
    value = _num(score)
    if value is None:
        return None
    for floor, name in BANDS:
        if value >= floor:
            return name
    return BANDS[-1][1]


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _cell(row: dict, name: str) -> Any:
    for key, value in (row or {}).items():
        cleaned = str(key).strip("[]").split("[")[-1].strip("]").lower()
        if cleaned == name.lower():
            return value
    return None


def available(scan: dict) -> bool:
    """Whether this model publishes a health score at all.

    Not every Inventory Management model does - the other environment's has no
    `_HEALTH SCORE MEASURES` table, and a page that assumed one would fail on
    it. Callers use this to decide whether the score layers exist, rather than
    rendering an empty tab.
    """
    rows = scan.get("health_overall") or []
    return bool(rows) and _num(_cell(rows[0], "score")) is not None


def build(scan: dict) -> dict | None:
    """The score, its six risks and their arithmetic guarantees. Pure.

    Returns None when the model publishes no score, so the caller can drop the
    score layers rather than print zeros.
    """
    if not available(scan):
        return None

    row = (scan.get("health_overall") or [{}])[0]
    score = _num(_cell(row, "score")) or 0.0
    lost = _num(_cell(row, "lost")) or 0.0

    risks = []
    for key, dims in DIMENSION_WEIGHTS.items():
        points = _num(_cell(row, f"{key}_points")) or 0.0
        breakdown = [{
            "name": label,
            "value": _num(_cell(row, field)),
            "weight_pct": weight * 100.0,
        } for field, label, weight in dims]
        rebuilt = min(RISK_CAP, RISK_CAP * sum(
            (_num(_cell(row, field)) or 0.0) * weight for field, _, weight in dims))
        business_name, model_name = RISK_LABELS[key]
        risks.append({
            "key": key,
            "name": business_name,
            # Printed in small type beside the business name where the two
            # differ, so the model's vocabulary is never deleted (BR-03).
            "model_name": model_name,
            "points": points,
            "share_of_loss_pct": (points / lost * 100.0) if lost else None,
            "loc_skus": _num(_cell(row, f"{key}_loc_skus")),
            "value": _num(_cell(row, f"{key}_value")),
            "dimensions": breakdown,
            "rebuilt_points": rebuilt,
            "reconciles": abs(rebuilt - points) < TOLERANCE,
            "at_cap": abs(points - RISK_CAP) < TOLERANCE,
        })
    risks.sort(key=lambda r: r["points"], reverse=True)

    dimensions_reconcile = all(r["reconciles"] for r in risks)

    return {
        "score": score,
        "band": band(score),
        "points_lost": lost,
        "risks": risks,
        "risk_cap": RISK_CAP,
        "bands": [{"floor": floor, "name": name} for floor, name in BANDS],
        "scored_loc_skus": _num(_cell(row, "scored_loc_skus")),
        "eligible_loc_skus": _num(_cell(row, "eligible_loc_skus")),
        "stock_value": _num(_cell(row, "stock")),
        "avg_scored_line": _num(_cell(row, "avg_scored_line")),
        "by_location": _ranked(scan.get("health_by_location") or [], "LOC_CODE"),
        "by_division": _ranked(scan.get("health_by_division") or [], "DEPARTMENT"),
        "status_bands": _status(scan.get("health_status") or []),
        "checks": {
            # The three guarantees. Each is re-derived, never assumed.
            "risks_sum_to_points_lost":
                abs(sum(r["points"] for r in risks) - lost) < 1e-6,
            "score_is_hundred_less_points_lost":
                abs((100.0 - lost) - score) < 1e-6,
            "no_risk_exceeds_its_cap":
                all(r["points"] <= RISK_CAP + TOLERANCE for r in risks),
        },
        # Not a `check`: a revised model is a fact to report, not a broken
        # report. The page drops the method panel and says why.
        "dimensions_reconcile": dimensions_reconcile,
        "dimension_note": (
            "" if dimensions_reconcile else
            "The score below is the model's own published figure. How each risk "
            "is built up from its parts is not shown, because the model's own "
            "build-up no longer matches the weights this report was set up with "
            "- the weights have been changed at source and need confirming."),
        "caveats": _caveats(risks, scan),
    }


def _ranked(rows: Sequence[dict], label: str) -> list[dict]:
    """Every member, worst score first - the order a reader acts in."""
    out = []
    for row in rows:
        name = _cell(row, label)
        if name is None:
            continue
        out.append({
            "name": str(name),
            "loc_type": _cell(row, "loc_type"),
            "score": _num(_cell(row, "score")),
            "band": band(_cell(row, "score")),
            "points_lost": _num(_cell(row, "lost")),
            "scored_loc_skus": _num(_cell(row, "scored_loc_skus")),
            "stock_value": _num(_cell(row, "stock")),
        })
    # A member with no score sorts last rather than as the worst: unscored and
    # scored-zero are different answers.
    out.sort(key=lambda item: (item["score"] is None,
                               item["score"] if item["score"] is not None else 0.0))
    return out


def _status(rows: Sequence[dict]) -> list[dict]:
    """The scored population by health band, worst first.

    `Out of Stock` is not a band: those lines start from 0 rather than 100 and
    are not floored, so the model reports a negative average for them. It is
    kept and labelled, never sorted among the bands as though it were one.
    """
    order = {name: index for index, (_, name) in enumerate(BANDS)}
    out = []
    for row in rows:
        name = str(_cell(row, "Health Status") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "loc_skus": int(_num(_cell(row, "loc_skus")) or 0),
            "stock_value": _num(_cell(row, "stock")),
            "avg_scored_line": _num(_cell(row, "avg_scored_line")),
            "is_band": name in order,
        })
    out.sort(key=lambda r: (not r["is_band"], -order.get(r["name"], 0)))
    return out


def _caveats(risks: Sequence[dict], scan: dict) -> list[str]:
    notes: list[str] = []

    clashing = [r for r in risks if r["model_name"]]
    for risk in clashing:
        notes.append(
            f"The model calls this risk \"{risk['model_name']}\"; the business "
            f"term is \"{risk['name']}\". They are the same thing - both are "
            f"shown so the figure can still be found in the model.")

    capped = [r["name"] for r in risks if r["at_cap"]]
    if capped:
        notes.append(
            f"{', '.join(capped)} has reached the most a single risk can cost "
            f"({RISK_CAP:.0f} points), so the score cannot show it getting any "
            f"worse. Read the underlying figure, not the points.")

    scored = _num(_cell((scan.get("health_overall") or [{}])[0], "scored_loc_skus"))
    locations = scan.get("health_by_location") or []
    unscored = [str(_cell(r, "LOC_CODE")) for r in locations
                if _num(_cell(r, "score")) is None]
    if unscored:
        notes.append(
            f"No score is published for {', '.join(sorted(unscored))}. Those "
            f"Locations are shown as stock evidence with no score attached, and "
            f"are never added into the scored total.")
    elif scored:
        notes.append(
            f"The score covers {scored:,.0f} Loc-SKUs across every Location, "
            f"warehouses included.")

    notes.append(
        "There is no history of the score itself - the dashboard keeps one "
        "position at a time - so no past values are implied.")
    return notes
