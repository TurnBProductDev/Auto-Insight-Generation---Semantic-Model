"""Daily Sales page model - reduced-scope build.

Mirrors the client reference's structure (Day / Stores / Departments /
Detail layers, an "Outside the band only" view) using only what
`daily_sales.build()` marked reliable: Bills and Margin, everywhere: Net
Sales only at store/whole-business grain, never as a department/section/
category figure, and never as a band anywhere (see `daily_sales.py`'s
module docstring for the verified defect this works around).

Department/section/category names collide across distinct underlying
source groups (the reference's own documented "several groups share one
name" behaviour). Bills is safe to sum across a collision the same way the
reference sums Net Sales for named groups; Margin has no safe weight
without Net Sales, so a bills-weighted average is used and stated as such
rather than presented as an unweighted or a sales-weighted figure.
"""

from __future__ import annotations

from typing import Any

_PILL = {"crit": "pill-crit", "good": "pill-ok", "neutral": "pill-neutral", None: "pill-neutral"}


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _money(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    number = _num(value)
    prefix = f"{currency} " if currency else ""
    if abs(number) >= 1_000_000:
        return f"{prefix}{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{prefix}{number / 1_000:.1f}K"
    return f"{prefix}{number:,.2f}" if abs(number) < 100 else f"{prefix}{number:,.0f}"


def _band_gap(actual: float | None, p20: float | None, p80: float | None) -> float | None:
    """Signed distance outside the band, 0 inside it, None if unavailable."""
    if actual is None or p20 is None or p80 is None:
        return None
    if actual < p20:
        return actual - p20
    if actual > p80:
        return actual - p80
    return 0.0


def _bullet(actual: float | None, p20: float | None, p50: float | None, p80: float | None,
           *, width: float = 214.0) -> dict | None:
    """Geometry for the reference's bullet-chart SVG: a full-range track, the
    [p20,p80] band, a p50 tick and an actual-value tick. The visible range is
    padded so the actual value and the band both always fit."""
    if actual is None or p20 is None or p80 is None:
        return None
    lo = min(actual, p20, p50 if p50 is not None else p20)
    hi = max(actual, p80, p50 if p50 is not None else p80)
    pad = (hi - lo) * 0.15 or max(abs(hi), 1.0) * 0.1
    lo -= pad
    hi += pad
    span = (hi - lo) or 1.0
    track_x, track_w = 6.0, width - 20.0

    def to_x(v: float) -> float:
        return track_x + (v - lo) / span * track_w

    return {
        "track_x": track_x, "track_w": track_w,
        "band_x": to_x(p20), "band_w": to_x(p80) - to_x(p20),
        "p50_x": to_x(p50) if p50 is not None else to_x((p20 + p80) / 2),
        "actual_x": to_x(actual),
        "width": width,
    }


def _bundle_display(bundle: dict, *, currency: str, label: str) -> dict:
    bills, margin = bundle["bills"], bundle["margin"]
    ns, bv = bundle["net_sales"], bundle["basket_value"]
    return {
        "label": label,
        "net_sales": {"available": ns["available"], "value": _money(ns["actual"], currency)},
        "basket_value": {"available": bv["available"],
                         "value": (f"{currency} {bv['actual']:.2f}" if bv["available"] and bv["actual"] is not None
                                   else "—")},
        "bills": {
            "available": bills["p20"] is not None, "actual": bills["actual"],
            "value": f"{bills['actual']:,.0f}" if bills["actual"] is not None else "—",
            "band": (f"{bills['p20']:,.0f} to {bills['p80']:,.0f}"
                    if bills["p20"] is not None and bills["p80"] is not None else ""),
            "gap": _band_gap(bills["actual"], bills["p20"], bills["p80"]),
            "verdict": bills["verdict"], "pill": _PILL.get(bills["verdict"]["key"]),
            "bullet": _bullet(bills["actual"], bills["p20"], bills["p50"], bills["p80"]),
        },
        "margin": {
            "available": margin["p20"] is not None, "actual": margin["actual"],
            "value": f"{margin['actual']:.2f}%" if margin["actual"] is not None else "—",
            "band": (f"{margin['p20']:.2f}% to {margin['p80']:.2f}%"
                    if margin["p20"] is not None and margin["p80"] is not None else ""),
            "gap": _band_gap(margin["actual"], margin["p20"], margin["p80"]),
            "verdict": margin["verdict"], "pill": _PILL.get(margin["verdict"]["key"]),
            "bullet": _bullet(margin["actual"], margin["p20"], margin["p50"], margin["p80"]),
        },
    }


def _outside_band(display: dict) -> bool:
    return display["bills"]["verdict"]["key"] in ("crit", "good") or \
        display["margin"]["verdict"]["key"] in ("crit", "good")


# ---------------------------------------------------------------------------
# merging duplicate-named department/section/category groups
# ---------------------------------------------------------------------------

def merge_by_name(rows: list[Any], *, key_fields: tuple[str, ...]) -> list[dict]:
    """Sums Bills (safe, matching the reference's own treatment of Net
    Sales) and computes a bills-weighted average Margin across rows sharing
    the same display name (and parent, when grouping below department
    level). Bands are summed the same way Bills itself is - the reference's
    own documented approach ("close but not a true benchmark... treat as a
    guide") - never silently dropped to a single arbitrary row."""
    groups: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row.get(f) for f in key_fields)
        g = groups.setdefault(key, {
            **{f: row.get(f) for f in key_fields},
            "bills_actual": 0.0, "bills_p20": 0.0, "bills_p50": 0.0, "bills_p80": 0.0,
            "bills_known": False,
            "margin_w": 0.0, "margin_weight": 0.0,
            "margin_p20_w": 0.0, "margin_p20_weight": 0.0,
            "margin_p80_w": 0.0, "margin_p80_weight": 0.0,
            "sample_days": row.get("sample_days"), "stores": set(), "rows": 0,
        })
        g["rows"] += 1
        g["stores"].add(row.get("store"))
        bills = row.get("bills") or {}
        b_actual = bills.get("actual")
        if b_actual is not None:
            g["bills_actual"] += b_actual
            g["bills_known"] = True
        if bills.get("p20") is not None:
            g["bills_p20"] += bills["p20"]
        if bills.get("p50") is not None:
            g["bills_p50"] += bills["p50"]
        if bills.get("p80") is not None:
            g["bills_p80"] += bills["p80"]
        margin = row.get("margin") or {}
        weight = b_actual or 0.0
        if margin.get("actual") is not None and weight:
            g["margin_w"] += margin["actual"] * weight
            g["margin_weight"] += weight
        if margin.get("p20") is not None and weight:
            g["margin_p20_w"] += margin["p20"] * weight
            g["margin_p20_weight"] += weight
        if margin.get("p80") is not None and weight:
            g["margin_p80_w"] += margin["p80"] * weight
            g["margin_p80_weight"] += weight

    out = []
    for g in groups.values():
        bills_actual = g["bills_actual"] if g["bills_known"] else None
        margin_actual = (g["margin_w"] / g["margin_weight"]) if g["margin_weight"] else None
        margin_p20 = (g["margin_p20_w"] / g["margin_p20_weight"]) if g["margin_p20_weight"] else None
        margin_p80 = (g["margin_p80_w"] / g["margin_p80_weight"]) if g["margin_p80_weight"] else None
        from . import daily_sales as _ds
        entry = {k: g[k] for k in g if k not in (
            "bills_actual", "bills_p20", "bills_p50", "bills_p80", "bills_known",
            "margin_w", "margin_weight", "margin_p20_w", "margin_p20_weight",
            "margin_p80_w", "margin_p80_weight", "rows", "stores")}
        entry["group_count"] = g["rows"]
        entry["stores"] = sorted(s for s in g["stores"] if s)
        entry["bills"] = {"actual": bills_actual, "p20": g["bills_p20"] or None,
                          "p50": g["bills_p50"] or None, "p80": g["bills_p80"] or None,
                          "verdict": _ds.verdict(bills_actual, g["bills_p20"] or None, g["bills_p80"] or None)}
        entry["margin"] = {"actual": margin_actual, "p20": margin_p20, "p50": None, "p80": margin_p80,
                           "verdict": _ds.verdict(margin_actual, margin_p20, margin_p80)}
        entry["net_sales"] = {"actual": None, "available": False}
        entry["basket_value"] = {"actual": None, "available": False}
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build(model: dict) -> dict:
    currency = model["currency"]
    whole_display = _bundle_display(model["whole"], currency=currency, label="Both stores")
    store_displays = [_bundle_display(s, currency=currency, label=s["store"]) for s in model["stores"]]

    dept_merged = merge_by_name(model["departments"], key_fields=("name",))
    dept_merged.sort(key=lambda d: -(d["bills"]["actual"] or 0.0))
    dept_display = [
        {**_bundle_display(d, currency=currency, label=d["name"]), "name": d["name"],
         "group_count": d["group_count"], "stores": d["stores"]}
        for d in dept_merged
    ]

    section_merged = merge_by_name(model["sections"], key_fields=("name", "parent"))
    section_merged.sort(key=lambda d: -(d["bills"]["actual"] or 0.0))
    section_display = [
        {**_bundle_display(d, currency=currency, label=d["name"]), "name": d["name"],
         "parent": d["parent"], "group_count": d["group_count"], "stores": d["stores"]}
        for d in section_merged
    ]

    category_merged = merge_by_name(model["categories"], key_fields=("name", "parent"))
    category_merged.sort(key=lambda d: -(d["bills"]["actual"] or 0.0))
    category_display = [
        {**_bundle_display(d, currency=currency, label=d["name"]), "name": d["name"],
         "parent": d["parent"], "group_count": d["group_count"], "stores": d["stores"]}
        for d in category_merged
    ]

    def outside(rows: list[dict]) -> list[dict]:
        return [r for r in rows if _outside_band(r)]

    hero_bits = []
    if whole_display["bills"]["verdict"]["key"] == "crit":
        hero_bits.append(f"Bills landed {abs(whole_display['bills']['gap'] or 0):,.0f} below the floor of "
                         f"the normal band.")
    elif whole_display["bills"]["verdict"]["key"] == "good":
        hero_bits.append(f"Bills landed {whole_display['bills']['gap'] or 0:,.0f} above the ceiling of "
                         f"the normal band.")
    else:
        hero_bits.append("Bills finished inside the normal band.")
    if whole_display["margin"]["verdict"]["key"] == "crit":
        hero_bits.append(f"Margin sat {abs(whole_display['margin']['gap'] or 0):.2f} points below its floor.")
    elif whole_display["margin"]["verdict"]["key"] == "good":
        hero_bits.append(f"Margin sat {whole_display['margin']['gap'] or 0:.2f} points above its ceiling.")
    else:
        hero_bits.append("Margin finished inside the normal band.")

    worst_dept = next((d for d in dept_display if d["bills"]["verdict"]["key"] == "crit"), None)

    hero = {
        "tag": f"{model['dow_name']} · week {model['week_of_month']} of the month",
        "headline": " ".join(hero_bits),
        "sub": (f"Net Sales stood at {whole_display['net_sales']['value']} across "
               f"{', '.join(model['store_names'])}. " +
               (f"{worst_dept['name']} is the department furthest below its own Bills band."
                if worst_dept else "No department fell below its own Bills band.")),
    }

    sparkline_chart = _trend_chart(model["sparkline"])

    caveats = [
        "Net Sales and Basket Value bands are not shown at any level, and Net Sales itself is "
        "shown only for the whole business and for each store - never for a department, section "
        "or category. The source figures behind those narrower cuts do not currently total "
        "correctly (verified: summing every department, section and category for a store gives "
        "the same wrong total, about 3.7 times the store's real figure). Bills and Margin are "
        "unaffected and carry every comparison on this page.",
        f"The figures cover {' and '.join(model['store_names'])} only, and both stores are in "
        "every combined total on this page.",
        "Bands are built from a small number of matching days: 25 for Bills, 13 for Margin at "
        "most levels (shown per row where it differs). A band drawn from a short run of days is "
        "wider and moves more than one drawn from a long run.",
        "A band at one level does not add up to the band at the level above it - each level is "
        "worked out separately.",
        "Bills cannot be added up across departments, sections or categories: one basket "
        "touching several departments counts once in each. Shares and sums at these levels are "
        "a guide, not an exact total.",
        "Several department/section/category names cover more than one underlying group in the "
        "source (the source does not carry the code that separates them). Bills for those names "
        "is added, which is safe the same way Net Sales addition is safe; Margin is a "
        "Bills-weighted average across the merged groups, stated as such because no sales-weighted "
        "figure is available at this level.",
        "This report has no per-store day-by-day history - only the whole-business trend below "
        "is available; a per-store trend chart is not buildable from the source model as it "
        "stands today.",
        "This is a comparison with the normal band, never with last year.",
    ]

    return {
        "title": model["report_name"], "as_at": model["as_at"], "currency": currency,
        "dow_name": model["dow_name"], "week_of_month": model["week_of_month"],
        "store_names": model["store_names"],
        "hero": hero,
        "whole": whole_display, "stores": store_displays,
        "sparkline_chart": sparkline_chart,
        "departments": {"all": dept_display, "outside": outside(dept_display)},
        "sections": {"all": section_display, "outside": outside(section_display)},
        "categories": {"all": category_display, "outside": outside(category_display)},
        "caveats": caveats,
        "checks": model["checks"],
    }


# ---------------------------------------------------------------------------
# KPI-feed signals - the outside-band findings, in the shape the existing
# memory/KPI-card machinery already understands (see sku_overview_insights.
# to_signals for the sibling pattern this mirrors).
# ---------------------------------------------------------------------------

_REPORT_ID = "daily_sales"


def _story_key(kind: str, anchor: str, name: str) -> str:
    import hashlib
    import json as _json
    blob = _json.dumps([_REPORT_ID, "insight", kind, anchor, name], separators=(",", ":"))
    return "dsins:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def to_signals(page: dict) -> list[dict]:
    """Whole-business and per-department/section findings outside their
    Bills or Margin band, ranked by the size of the gap. Net Sales never
    contributes a signal - it carries no trustworthy band (see
    `daily_sales.py`)."""
    anchor = str(page.get("as_at") or "")
    out: list[dict] = []

    def _emit(name: str, grain: str, parent: str, measure_key: str, measure: dict):
        gap = measure.get("gap")
        if gap is None or gap == 0:
            return
        verdict = measure["verdict"]
        score = abs(gap) * (5.0 if grain == "whole" else 1.0)
        label = "Bills" if measure_key == "bills" else "Margin"
        unit = "" if measure_key == "bills" else " points"
        out.append({
            "candidate_id": f"daily_sales_{grain}_{measure_key}:{name}:",
            "story_key": _story_key(f"{grain}_{measure_key}", anchor, name),
            "report_id": _REPORT_ID, "analysis_type": f"daily_sales_{grain}_{measure_key}_band",
            "dimension": grain, "affected_segment": name,
            "metric": f"{label} vs its normal band", "current": measure.get("actual"),
            "impact_value": gap, "impact_share": None, "score": score,
            "severity": "critical" if verdict["key"] == "crit" else "info",
            "comparison_label": f"the normal {label.lower()} band for {name or 'the business'} on this weekday",
            "description": (
                f"{name or 'The whole business'} finished {label} {verdict['word'].lower()} "
                f"({'+' if gap > 0 else ''}{gap:,.2f}{unit} against its band)"
                + (f", inside {parent}" if parent else "") + "."),
        })

    whole = page.get("whole") or {}
    _emit("", "whole", "", "bills", whole.get("bills") or {})
    _emit("", "whole", "", "margin", whole.get("margin") or {})

    for row in (page.get("departments") or {}).get("outside", []):
        _emit(row["name"], "department", "", "bills", row["bills"])
        _emit(row["name"], "department", "", "margin", row["margin"])
    for row in (page.get("sections") or {}).get("outside", []):
        _emit(row["name"], "section", row.get("parent") or "", "bills", row["bills"])
        _emit(row["name"], "section", row.get("parent") or "", "margin", row["margin"])

    out.sort(key=lambda s: (-float(s.get("score") or 0.0), str(s.get("candidate_id"))))
    for index, signal in enumerate(out, start=1):
        signal["id"] = f"I{index}"
    return out


def _trend_chart(sparkline: list[dict]) -> dict | None:
    """Bills-vs-band, day by day, over the trailing window the model holds
    (up to 14 days) - the one trend the source model actually supports
    reliably. Each day is expressed as a % of that day's own Bills
    benchmark (p50), matching the reference's normalisation approach."""
    rows = [r for r in sparkline if r["bills"]["p50"]]
    if not rows:
        return None
    points = []
    for row in rows:
        p50 = row["bills"]["p50"] or 1.0
        points.append({
            "date": row["date"],
            "actual_pct": (row["bills"]["actual"] or 0.0) / p50 * 100.0,
            "p20_pct": (row["bills"]["p20"] or 0.0) / p50 * 100.0,
            "p80_pct": (row["bills"]["p80"] or 0.0) / p50 * 100.0,
            "actual": row["bills"]["actual"],
            "inside": (row["bills"]["p20"] or 0) <= (row["bills"]["actual"] or 0) <= (row["bills"]["p80"] or 0),
        })
    inside_count = sum(1 for p in points if p["inside"])
    return {"points": points, "inside_count": inside_count, "total": len(points)}
