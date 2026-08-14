"""The four-layer inventory dashboard: Overview -> Locations -> Divisions -> Detail.

Same shape as the R6 sales dashboard, and for the same reason: every layer must
be *covered* whether or not it has a headline, so the structure is code-owned
rather than chosen per run. What changes is what fills each layer - a stock
position has no period comparison, so "which areas moved the group" becomes
"where the stock sits".

The two views are not two time periods
--------------------------------------
The sales dashboard toggles between a wide span and one complete month. A single
snapshot has no such pair. The useful toggle here is **all stock** against
**high-risk stock only** - everything, or just the problem - which is the
question a buyer actually asks and which the scan already supports (every
breakdown carries its own high-risk column).

Nothing here computes a figure the scan did not return.
"""

from __future__ import annotations

from typing import Any, Sequence

from . import buckets

#: Bands that count as high-risk for the second view (BR-17).
HIGH_RISK_BANDS = buckets.HIGH_RISK_BANDS

LAYERS = ("overview", "entities", "areas", "detail")
LAYER_TITLES = {
    "overview": "Overview",
    "entities": "Locations",
    "areas": "Divisions",
    "detail": "Full detail",
}


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _sar(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "-"
    if abs(number) >= 1_000_000:
        return f"SAR {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"SAR {number / 1_000:.0f}K"
    return f"SAR {number:,.0f}"


def _pct(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.1f}%"


def _share(part: Any, whole: Any) -> float | None:
    part_val, whole_val = _num(part), _num(whole)
    if part_val is None or not whole_val:
        return None
    return part_val / whole_val * 100.0


def _tone_for_share(share: float | None, *, warn: float, critical: float) -> str:
    """Higher is worse for every measure on this page - the inverse of sales."""
    if share is None:
        return "neutral"
    if share >= critical:
        return "critical"
    if share >= warn:
        return "warn"
    return "positive"


def _kpi(label: str, value: Any, *, sub: str = "", tone: str = "neutral",
         caution: str = "", change_display: str = "") -> dict:
    return {
        "label": label,
        "value_display": _sar(value) if isinstance(value, (int, float)) else str(value),
        "change_display": change_display,
        "note": sub,
        "rag": {"tone": tone, "caution": caution},
    }


def _entity_cards(rows: Sequence[dict], total_aged: float) -> list[dict]:
    """One card per location, ranked by how much aged stock it holds."""
    cards = []
    for row in rows:
        aged = _num(row.get("value")) or 0.0          # aged stock at this location
        held = _num(row.get("total")) or 0.0          # all stock at this location
        own_share = _share(aged, held)                 # BR-23: severity vs ITS OWN stock
        cards.append({
            "member": row.get("name"),
            "value_display": _sar(aged),
            "change_display": _pct(own_share),
            "note": (f"{_sar(aged)} aged of {_sar(held)} held here - "
                     f"{_pct(own_share)} of this location's own stock."),
            "share_of_group_pct": _share(aged, total_aged),
            "own_share_pct": own_share,
            "tone": _tone_for_share(own_share, warn=12.0, critical=20.0),
        })
    return cards


def build(report: dict) -> dict:
    """The whole page model, from the ageing report model. Pure."""
    header = report.get("header") or {}
    bands = (report.get("distribution") or {}).get("bands") or []
    split = report.get("risk_split") or {}
    total = _num(header.get("total_value")) or 0.0
    aged = _num(header.get("aged_value")) or 0.0
    high_risk = _num(header.get("high_risk_value")) or 0.0
    aged_nm = _num(header.get("aged_non_moving")) or 0.0
    oldest = next((b for b in bands if str(b.get("name", "")).upper().startswith("24+")), None)

    views = [
        _all_stock_view(report, header, bands, split, total, aged, high_risk,
                        aged_nm, oldest),
        _high_risk_view(report, header, bands, total, high_risk, oldest),
    ]

    caveats = list(report.get("caveats") or [])
    migration = report.get("migration") or {}
    if not migration.get("available"):
        caveats.append(migration.get("reason", ""))
    caveats.append(
        "This report shows how old stock is and which aged stock is not "
        "selling. It does not say why stock is ageing, or what to do about it.")

    return {
        "status": "ok",
        "title": report.get("report_name") or "Stock Age Analysis",
        "subtitle": f"Stock position {report.get('period_label')}",
        "layers": list(LAYERS),
        "layer_titles": dict(LAYER_TITLES),
        "default_view": "all",
        "views": [v for v in views if v],
        "caveats": [c for c in caveats if c],
        "checks": report.get("checks") or {},
    }


def _all_stock_view(report, header, bands, split, total, aged, high_risk,
                    aged_nm, oldest) -> dict:
    aged_share = _share(aged, total)
    hr_share = _share(high_risk, total)
    not_selling = _num(split.get("non_moving_total")) or 0.0

    kpis = [
        _kpi("Stock value", total, sub="Held across all locations."),
        _kpi("Aged stock", aged,
             sub=f"{_pct(aged_share)} of stock value. Food ages at six months, "
                 f"everything else at nine.",
             tone=_tone_for_share(aged_share, warn=10.0, critical=15.0)),
        _kpi("High-risk, over a year", high_risk,
             sub=f"{_pct(hr_share)} of stock value.",
             tone=_tone_for_share(hr_share, warn=5.0, critical=8.0)),
        _kpi("Aged and not selling", aged_nm,
             sub="Old stock with no recorded sales. The highest-risk combination.",
             tone=_tone_for_share(_share(aged_nm, total), warn=3.0, critical=5.0),
             caution="Not added to the aged total - the two measures overlap."),
        _kpi("Over two years old", (oldest or {}).get("value"),
             sub="The most likely write-off candidate.",
             tone="critical" if (_num((oldest or {}).get("value")) or 0)
                  >= buckets.HIGH_RISK_CALL_OUT_SAR else "warn"),
        _kpi("Not selling, any age", not_selling,
             sub="Stock with no recorded sales since it arrived.",
             tone=_tone_for_share(_share(not_selling, total), warn=8.0, critical=12.0)),
    ]

    signals = []
    migration = report.get("migration") or {}
    if not migration.get("available"):
        signals.append({"label": "No movement over time",
                        "value_display": "Not available",
                        "note": migration.get("reason")})
    undetermined = _num((report.get("distribution") or {}).get("undetermined_value")) or 0.0
    if undetermined > 0:
        signals.append({"label": "Could not be age-classified",
                        "value_display": _sar(undetermined),
                        "note": "Reported separately; not in any age band."})
    fresh_nm = _num(split.get("fresh_non_moving")) or 0.0
    if fresh_nm > 0:
        signals.append({
            "label": "Fresh but not selling", "value_display": _sar(fresh_nm),
            "note": "Under nine months old with no sales - a demand or "
                    "placement signal, not an age problem."})

    locations = report.get("locations") or []
    divisions = report.get("divisions") or []

    return {
        "key": "all",
        "label": "All stock",
        "owns_breakdowns": True,
        "period": {"data_as_of": report.get("as_at"), "grain": "snapshot"},
        "hero": {
            "headline": _headline(oldest, high_risk, hr_share, aged_nm),
            "narrative": (report.get("narrative") or [""])[0],
        },
        "kpis": kpis,
        "signals": signals,
        "tldr": _tldr(report, oldest, aged_nm, locations, divisions),
        "layers": {
            "overview": True,
            "entities": {
                "available": bool(locations),
                "role": "location",
                "cards": _entity_cards(locations, aged or 1.0),
                "caption": "Each location's aged stock, and what share of its "
                           "own stock that is.",
            },
            "areas": {
                "available": bool(divisions),
                "role": "division",
                "rows": [_area_row(d, aged) for d in divisions],
                "caption": "Divisions ranked by the aged stock they hold.",
            },
            "detail": {
                "bands": bands,
                "sections": report.get("sections") or [],
                "sku_types": report.get("sku_types") or [],
                "risk_split": split,
            },
        },
        "limitations": [],
    }


def _high_risk_view(report, header, bands, total, high_risk, oldest) -> dict | None:
    """Everything, filtered to stock over a year old."""
    if not high_risk:
        return None
    twelve = next((b for b in bands
                   if str(b.get("name", "")).upper().startswith("12-24")), None)
    locations = [r for r in (report.get("locations") or []) if r.get("high_risk")]
    divisions = [r for r in (report.get("divisions") or []) if r.get("high_risk")]

    kpis = [
        _kpi("High-risk stock", high_risk,
             sub=f"{_pct(_share(high_risk, total))} of all stock value.",
             tone="critical"),
        _kpi("Over two years old", (oldest or {}).get("value"),
             sub=f"{_pct((oldest or {}).get('share_pct'))} of all stock value. "
                 f"Reported separately because it is the likeliest write-off.",
             tone="critical"),
        _kpi("One to two years old", (twelve or {}).get("value"),
             sub=f"{_pct((twelve or {}).get('share_pct'))} of all stock value.",
             tone="warn"),
    ]

    return {
        "key": "high_risk",
        "label": "High-risk only",
        "owns_breakdowns": True,
        "period": {"data_as_of": report.get("as_at"), "grain": "snapshot"},
        "hero": {
            "headline": f"{_sar(high_risk)} of stock is more than a year old",
            "narrative": "This view shows only stock in the 12-24 month and 24+ "
                         "month bands. Every figure below is scoped to it.",
        },
        "kpis": kpis,
        "signals": [],
        "tldr": [],
        "layers": {
            "overview": True,
            "entities": {
                "available": bool(locations),
                "role": "location",
                "cards": _high_risk_cards(locations),
                "caption": "High-risk stock by location.",
            },
            "areas": {
                "available": bool(divisions),
                "role": "division",
                "rows": [_high_risk_area(d) for d in sorted(
                    divisions, key=lambda r: _num(r.get("high_risk")) or 0.0,
                    reverse=True)],
                "caption": "Divisions ranked by high-risk stock held.",
            },
            "detail": {
                "bands": [b for b in bands if b.get("high_risk")],
                "sections": [s for s in (report.get("sections") or []) if s.get("value")],
                "sku_types": [],
                "risk_split": {},
            },
        },
        "limitations": [
            "This view counts only stock over a year old. Totals will not match "
            "the all-stock view."],
    }


def _high_risk_cards(rows: Sequence[dict]) -> list[dict]:
    total = sum(_num(r.get("high_risk")) or 0.0 for r in rows) or 1.0
    cards = []
    # Ranked by THIS view's measure. The incoming rows are ordered by aged
    # stock, which puts a location with more high-risk stock below one with
    # less - wrong on a page whose whole subject is high-risk stock.
    rows = sorted(rows, key=lambda r: _num(r.get("high_risk")) or 0.0, reverse=True)
    for row in rows:
        value = _num(row.get("high_risk")) or 0.0
        held = _num(row.get("total")) or 0.0
        own = _share(value, held)
        cards.append({
            "member": row.get("name"),
            "value_display": _sar(value),
            "change_display": _pct(own),
            "note": f"{_sar(value)} over a year old, {_pct(own)} of this "
                    f"location's own stock.",
            "share_of_group_pct": _share(value, total),
            "own_share_pct": own,
            "tone": _tone_for_share(own, warn=6.0, critical=10.0),
        })
    return cards


def _area_row(row: dict, total_aged: float) -> dict:
    aged = _num(row.get("value")) or 0.0
    held = _num(row.get("total")) or 0.0
    return {
        "name": row.get("name"),
        "value_display": _sar(aged),
        "held_display": _sar(held),
        "own_share": _share(aged, held),
        "group_share": _share(aged, total_aged),
        "tone": _tone_for_share(_share(aged, held), warn=15.0, critical=25.0),
    }


def _high_risk_area(row: dict) -> dict:
    value = _num(row.get("high_risk")) or 0.0
    held = _num(row.get("total")) or 0.0
    return {
        "name": row.get("name"),
        "value_display": _sar(value),
        "held_display": _sar(held),
        "own_share": _share(value, held),
        "group_share": None,
        "tone": _tone_for_share(_share(value, held), warn=6.0, critical=10.0),
    }


# --- Inventory Management -----------------------------------------------------
# Same four layers, same shell. What differs is that this report's Overview is a
# WORK QUEUE rather than a verdict: the brief calls for an `exception_list`
# layout, and BR-31 makes RECOMMENDED_ACTION the operational output. So the
# Detail layer leads with the queue, ordered by urgency rather than by value.

STOCK_HEALTH_LAYER_TITLES = {
    "overview": "Overview",
    "entities": "Locations",
    "areas": "Divisions",
    "detail": "Action queue",
}


def build_stock_health(report: dict) -> dict:
    """The Inventory Management page model. Pure."""
    header = report.get("header") or {}
    stock = _num(header.get("stock_value")) or 0.0
    excess = _num(header.get("excess_value")) or 0.0
    queue = report.get("queue") or []
    exceptions = [r for r in queue if r.get("is_exception")]

    views = [
        _stock_health_view(report, header, stock, excess, queue, "all"),
        _stock_health_view(report, header, stock, excess, exceptions, "exceptions"),
    ]

    return {
        "status": "ok",
        "title": report.get("report_name") or "Inventory Management",
        "subtitle": f"Stock position {report.get('period_label')}",
        "layers": list(LAYERS),
        "layer_titles": dict(STOCK_HEALTH_LAYER_TITLES),
        "default_view": "all",
        "views": [v for v in views if v],
        "caveats": list(report.get("caveats") or []),
        "checks": report.get("checks") or {},
    }


def _stock_health_view(report, header, stock, excess, queue, key) -> dict:
    scoped = key == "exceptions"
    rows = sum(r.get("loc_skus") or 0 for r in queue)
    value = sum(r.get("stock_value") or 0.0 for r in queue)
    excess_share = _share(excess, stock)
    opp = _num(header.get("opportunity_loss_day")) or 0.0
    unwanted = int(_num(header.get("unwanted_skus")) or 0)
    doubles = [r for r in queue if r.get("double_warning")]
    double_rows = sum(r.get("loc_skus") or 0 for r in doubles)

    if scoped:
        kpis = [
            _kpi("Lines needing action", f"{rows:,}",
                 sub="Product-location lines in an exception state.", tone="critical"),
            _kpi("Value on those lines", value,
                 sub=f"{_pct(_share(value, stock))} of stock value."),
            _kpi("Most urgent lines", f"{double_rows:,}",
                 sub="Not selling with stock on order, or out of stock with no "
                     "order placed.", tone="critical"),
        ]
    else:
        kpis = [
            _kpi("Stock value", stock, sub="Held across all locations."),
            _kpi("Held above agreed cover", excess,
                 sub=f"{_pct(excess_share)} of stock value. The surplus only, not "
                     f"the whole value of overstocked products.",
                 tone=_tone_for_share(excess_share, warn=25.0, critical=35.0)),
            _kpi("Lines needing action", f"{sum(r['loc_skus'] for r in queue if r.get('is_exception')):,}",
                 sub=f"of {int(_num(header.get('loc_skus')) or 0):,} product-location lines.",
                 tone="warn"),
            _kpi("Most urgent lines", f"{double_rows:,}",
                 sub="Not selling with stock on order, or out of stock with no "
                     "order placed.",
                 tone="critical" if double_rows else "positive"),
            _kpi("Sales missed each day", opp,
                 sub="Top-selling locally bought products, at stores only.",
                 caution="An estimate from the recent rate of sale, not confirmed "
                         "lost revenue."),
            _kpi("Overstocked with more coming", f"{unwanted:,}",
                 sub=f"products, with {_sar(header.get('unwanted_pending_value'))} "
                     f"of orders still open.",
                 tone="critical" if unwanted else "positive"),
        ]

    signals = []
    if not scoped:
        for row in doubles:
            signals.append({
                "label": row["action"].title(),
                "value_display": f"{row['loc_skus']:,} lines",
                "note": row.get("guidance"),
            })

    locations = report.get("locations") or []
    divisions = report.get("divisions") or []

    return {
        "key": key,
        "label": "All stock" if not scoped else "Needs action only",
        "owns_breakdowns": True,
        "period": {"data_as_of": report.get("as_at"), "grain": "snapshot"},
        "hero": {
            "headline": (f"{double_rows:,} product lines need attention today"
                         if double_rows else
                         f"{_sar(excess)} is held above the agreed cover"),
            "narrative": (report.get("narrative") or [""])[0],
        },
        "kpis": kpis,
        "signals": signals,
        "tldr": [] if scoped else _stock_health_tldr(report, doubles, excess, unwanted),
        "layers": {
            "overview": True,
            "entities": {
                "available": bool(locations),
                "role": "location",
                "cards": _stock_health_cards(locations),
                "caption": "Each location's stock held above the agreed cover.",
            },
            "areas": {
                "available": bool(divisions),
                "role": "division",
                "rows": [_stock_health_area(d) for d in divisions],
                "caption": "Divisions ranked by stock held above the agreed cover.",
            },
            "detail": {
                "queue": queue,
                "sections": report.get("sections") or [],
                "segments": report.get("segments") or [],
                "non_moving_bands": report.get("non_moving_bands") or [],
                "damage": report.get("damage") or [],
            },
        },
        "limitations": (
            ["This view counts only lines in an exception state. Totals will not "
             "match the all-stock view."] if scoped else []),
    }


def _stock_health_cards(rows: Sequence[dict]) -> list[dict]:
    total = sum(_num(r.get("excess_value")) or 0.0 for r in rows) or 1.0
    cards = []
    for row in rows:
        excess = _num(row.get("excess_value")) or 0.0
        held = _num(row.get("stock_value")) or 0.0
        own = _share(excess, held)
        kind = "warehouse" if str(row.get("loc_type") or "").upper() == "WH" else "store"
        cards.append({
            "member": row.get("name"),
            "value_display": _sar(excess),
            "change_display": _pct(own),
            "note": f"{_sar(excess)} above cover, {_pct(own)} of the "
                    f"{_sar(held)} this {kind} holds.",
            "share_of_group_pct": _share(excess, total),
            "own_share_pct": own,
            "tone": _tone_for_share(own, warn=35.0, critical=50.0),
        })
    return cards


def _stock_health_area(row: dict) -> dict:
    excess = _num(row.get("excess_value")) or 0.0
    held = _num(row.get("stock_value")) or 0.0
    return {
        "name": row.get("name"),
        "value_display": _sar(excess),
        "held_display": _sar(held),
        "own_share": _share(excess, held),
        "group_share": None,
        "tone": _tone_for_share(_share(excess, held), warn=35.0, critical=50.0),
    }


def _stock_health_tldr(report, doubles, excess, unwanted) -> list[dict]:
    items = []
    for row in doubles:
        items.append({
            "rank": len(items) + 1, "tone": "critical", "layer": "detail",
            "to": "Action queue",
            "text": f"{row['loc_skus']:,} lines: {row['action'].lower()}."})
    if unwanted:
        items.append({
            "rank": len(items) + 1, "tone": "critical", "layer": "overview",
            "to": "Overview",
            "text": f"{unwanted:,} overstocked products have more stock on order."})
    if excess:
        items.append({
            "rank": len(items) + 1, "tone": "warn", "layer": "areas",
            "to": "Divisions",
            "text": f"{_sar(excess)} is held above the agreed cover."})
    return items


def _headline(oldest, high_risk, hr_share, aged_nm) -> str:
    oldest_value = _num((oldest or {}).get("value")) or 0.0
    if oldest_value >= buckets.HIGH_RISK_CALL_OUT_SAR:
        return (f"{_sar(oldest_value)} of stock is more than two years old, "
                f"inside {_sar(high_risk)} held over a year")
    if high_risk:
        return f"{_sar(high_risk)} of stock is more than a year old ({_pct(hr_share)})"
    return f"{_sar(aged_nm)} is aged and not selling"


def _tldr(report, oldest, aged_nm, locations, divisions) -> list[dict]:
    """Ranked in the rulebook's order (BR-28), each linking into a layer."""
    items = []
    oldest_value = _num((oldest or {}).get("value")) or 0.0
    if oldest_value:
        items.append({
            "rank": 1, "tone": "critical", "layer": "overview", "to": "Overview",
            "text": f"{_sar(oldest_value)} is over two years old - the likeliest "
                    f"write-off."})
    if aged_nm:
        items.append({
            "rank": len(items) + 1, "tone": "critical", "layer": "detail",
            "to": "Full detail",
            "text": f"{_sar(aged_nm)} is both aged and not selling."})
    if locations:
        worst = locations[0]
        items.append({
            "rank": len(items) + 1, "tone": "warn", "layer": "entities",
            "to": "Locations",
            "text": f"{worst.get('name')} holds the most aged stock, "
                    f"{_sar(worst.get('value'))}."})
    if divisions:
        worst = divisions[0]
        items.append({
            "rank": len(items) + 1, "tone": "warn", "layer": "areas",
            "to": "Divisions",
            "text": f"{worst.get('name')} holds {_sar(worst.get('value'))} of "
                    f"aged stock."})
    return items
