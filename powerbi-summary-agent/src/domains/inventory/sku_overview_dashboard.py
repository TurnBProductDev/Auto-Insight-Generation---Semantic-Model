"""The SKU Overview page model, matching the client-approved reference design
(`reference_sku_overview.html` / `sku-insights-rules.md`).

Structure is code-owned throughout - every number here is copied or derived
arithmetically from `model` (the reconciled, shop-scoped report), `insights`
(the eight rulebook rules) and `detail`/`product` (the two extra data
sources below). Nothing is invented: a layer or view with no data says so
plainly rather than being padded or hidden.

Five nav layers, mirroring the reference:

* **Overview** - the hero verdict, headline KPIs, the RECOMMENDED_ACTION
  rank bars and what each problem is worth.
* **What is selling** - rules 1/3/8 (top performers, best-day-yesterday,
  at the price floor) plus rule 2's honest "pending" state.
* **What needs action** - rules 4/5/6/7 (the four exception rules).
* **Departments and shops** - `sku_overview_insights.department_shop_detail`:
  every department and every shop in full (never top-N'd), the two
  warehouses as a reference only, and the complete RECOMMENDED_ACTION table.
* **One product in full** - `sku_overview_product.build`'s spotlight on one
  automatically-selected SKU (the #1 Rule 4 result, "the largest gap on the
  shelf"), covering its per-shop status, a 12-week sales trend, its price
  against the 90-day range, and how it compares to its own category.

Two views, mirroring the reference's `.scoped` toggle: **All products** and
**Best sellers only** (Segment A). The view recomputes Overview/What is
selling/What needs action/Departments and shops from a second, genuinely
separate scan filtered to `SKUSEGMENT = "SEG_A"` - every figure in that view
is worked out again over just those products, never a subset carved out of
the all-products totals. "One product in full" is not duplicated per view:
a SKU either is or is not the selected subject, regardless of which view is
open.
"""

from __future__ import annotations

from typing import Any

#: RECOMMENDED_ACTION -> (plain-language label, urgency word, colour token).
#: An unknown state (a value the source system starts producing that this
#: map has not seen) falls back to a title-cased version of its own name and
#: a neutral urgency word, rather than being dropped from the page.
_STATE_LABELS: dict[str, tuple[str, str, str]] = {
    "STOCK OUT - PLACE ORDER": ("Shelf empty, nothing on order", "Act now", "red"),
    "STOCK OUT - ORDER PLACED": ("Shelf empty, order already placed", "Watch", "amber"),
    "STOCK OUT - AVAILABLE IN WAREHOUSE": ("Shelf empty, stock is in a warehouse", "Free fix", "amber"),
    "ON THE VERGE OF STOCK OUT - PLACE ORDER": ("Almost gone, nothing on order", "Watch", "amber"),
    "ON THE VERGE OF STOCK OUT - ORDER PLACED": ("Almost gone, order already placed", "Watch", "amber"),
    "ON THE VERGE OF STOCK OUT - AVAILABLE IN WAREHOUSE": ("Almost gone, stock is in a warehouse", "Free fix", "amber"),
    "NON MOVING": ("Not selling at all", "Watch", "amber"),
    "OVERSTOCK": ("More on the shelf than needed", "Watch", "amber"),
    "STOCK AVAILABLE": ("On the shelf and selling", "Healthy", "teal"),
    "IN STOCK BUT NO SALES": ("On the shelf but not selling", "Watch", "amber"),
    "IN STOCK BUT NO TRANSFERS": ("On the shelf, never sent to this shop", "Watch", "amber"),
    "NOT ACTIVE": ("No longer traded", "No action", "faint"),
    "NEW LISTED SKU": ("Newly listed, no track record yet", "Watch", "amber"),
    "STOCK AVAILABLE - REORDER LEVEL UNKNOW": ("On the shelf, no reorder level set", "Watch", "amber"),
    "NA": ("Not classified", "No action", "faint"),
}


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _money(value: Any, currency: str) -> str:
    number = _num(value)
    prefix = f"{currency} " if currency else ""
    if abs(number) >= 1_000_000:
        return f"{prefix}{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{prefix}{number:,.0f}"
    return f"{prefix}{number:,.0f}"

def _state_label(action: str) -> tuple[str, str, str]:
    return _STATE_LABELS.get(action, (action.title(), "Watch", "amber"))


def _rank_bars(states: list[dict]) -> list[dict]:
    rows = [s for s in states if s.get("rows")]
    rows.sort(key=lambda s: -_num(s.get("rows")))
    peak = max((_num(s.get("rows")) for s in rows), default=0.0) or 1.0
    out = []
    for row in rows:
        label, urgency, color = _state_label(str(row.get("action") or ""))
        out.append({
            "label": label, "model_name": row.get("action"),
            "count": int(_num(row.get("rows"))),
            "width_pct": _num(row.get("rows")) / peak * 100.0,
            "urgency": urgency, "color": color,
        })
    return out


def _build_view(model: dict, insights: dict | None, detail: dict | None, *,
                 scope_label: str, scoped: bool) -> dict:
    """One view's worth of page data (Overview/What is selling/What needs
    action/Departments and shops), for either the all-products scan or the
    Segment-A-only rescan."""
    header = model.get("header") or {}
    currency = str(model.get("currency") or "")
    states = model.get("states") or []
    rules = (insights or {}).get("rules") or {}
    errors = (insights or {}).get("errors") or {}

    urgent = next((s for s in states if s.get("action") == "STOCK OUT - PLACE ORDER"), None)
    urgent_count = int(_num((urgent or {}).get("rows")))
    total_opp_loss = _num(header.get("total_opp_loss"))

    stockouts = rules.get("segment_a_stockouts") or {}
    verge = rules.get("verge_stockout_in_warehouse") or []
    verge_sales = sum(_num(r.get("sales_3m")) for r in verge)
    stockout_sales = sum(_num(r.get("sales_3m")) for r in (stockouts.get("top") or []))

    hero = {
        "tag": f"Stock position as at {model.get('as_at') or 'the latest load'}"
              + (f" · {scope_label}" if scoped else ""),
        "headline": (
            f"{stockouts.get('count', 0):,} of your best-selling product lines "
            f"have an empty shelf. That is about {_money(total_opp_loss, currency)} "
            f"of estimated sales a day you cannot make."
            if stockouts.get("count") else
            f"{urgent_count:,} Loc-SKUs have an empty shelf with nothing on order."
        ),
        "sub": (
            f"A further {len(verge)} lines are close to running out - and for "
            f"those the stock is already sitting in a warehouse, so they can "
            f"be put back on the shelf today without buying anything."
            if verge else ""
        ),
        "stats": [
            {"value": f"{stockouts.get('count', urgent_count):,}",
             "label": "best-seller lines with nothing on the shelf" if stockouts.get("count")
                      else "Loc-SKUs with nothing on the shelf"},
            {"value": _money(total_opp_loss, currency), "label": "estimated Opportunity Loss",
             "crit": True},
            {"value": f"{len(verge):,}", "label": "lines a warehouse could refill today"},
        ],
    }

    kpis = [
        {"label": "Products tracked", "value": f"{int(_num(header.get('skus'))):,}",
         "sub": f"across {int(_num(header.get('rows'))):,} product-shop lines in "
               f"{int(_num(header.get('locations'))):,} shops"},
        {"label": "Stock on the shelf", "value": _money(header.get("total_stock_value"), currency),
         "sub": "valued at what it cost"},
        {"label": "Excess Stock", "value": _money(header.get("total_excess_value"), currency),
         "sub": (f"{header['excess_share_pct']:.1f}% of stock value"
                if isinstance(header.get("excess_share_pct"), (int, float)) else "")},
        {"label": "Opportunity Loss", "value": _money(total_opp_loss, currency),
         "sub": "across every line the model could estimate", "crit": True, "pill": "Act now"},
    ]

    bars = _rank_bars(states)

    overstock_pending = rules.get("overstock_pending_order") or []
    non_moving_pending = rules.get("non_moving_pending_order") or []
    worth = {
        "sales_at_stake": [
            {"label": "Best sellers, empty shelf", "count": stockouts.get("count", 0),
             "value": _money(stockout_sales, currency), "raw": stockout_sales, "color": "red"},
            {"label": "Almost gone, stock in a warehouse", "count": len(verge),
             "value": _money(verge_sales, currency), "raw": verge_sales, "color": "amber"},
        ],
        "stock_to_arrive": [
            {"label": "More on order than needed", "count": len(overstock_pending),
             "value": _money(sum(_num(r.get("pending_value")) for r in overstock_pending), currency),
             "raw": sum(_num(r.get("pending_value")) for r in overstock_pending), "color": "amber"},
            {"label": "On order but not selling", "count": len(non_moving_pending),
             "value": _money(sum(_num(r.get("pending_value")) for r in non_moving_pending), currency),
             "raw": sum(_num(r.get("pending_value")) for r in non_moving_pending), "color": "amber"},
        ],
    }

    caveats = [
        "This is one day's position, not a trend. Every figure is the state "
        f"of the shelves {model.get('period_label') or 'at the latest load'}.",
        "The figures cover the five shops only (ST1-ST5). The two "
        "warehouses hold stock but do not sell, so they are never added "
        "into a sales or shelf total. They appear only where a warehouse is "
        "the fix for a shop problem.",
        "The missed-sales figure is a daily rate, not a running total, and "
        "is only worked out for the Loc-SKUs the model could estimate - a "
        "blank is not a zero, so the true figure is higher.",
        "Product positions within a category cannot be compared over time "
        "yet - the model keeps no record of past positions, so the "
        "rank-movers section is pending, not empty because nothing changed.",
        "A product's best-day list is not a sales league table. A product "
        "appears there only if yesterday beat all its own recent days, "
        "which favours smaller, less predictable lines over steady big sellers.",
        "Stock is valued at what it cost, sales at what they sold for. The "
        "two are not the same measure and this page never adds one to the other.",
    ]
    if scoped:
        caveats.insert(0,
            "This view recomputes every figure over Segment A products only "
            "(the model's own top sales band) - it is a fresh scan, not a "
            "subset carved out of the All products totals, so every number "
            "here stands on its own.")
    if errors:
        caveats.append("Some rules could not run this time: " + ", ".join(errors))

    return {
        "scope_label": scope_label, "scoped": scoped,
        "hero": hero, "kpis": kpis, "bars": bars, "worth": worth, "caveats": caveats,
        "rules": rules, "errors": errors,
        "detail": _detail_section(detail, currency),
        "rules_available": bool(insights),
    }


def _detail_section(detail: dict | None, currency: str) -> dict | None:
    """Shapes `sku_overview_insights.department_shop_detail`'s output for
    rendering. Returns None when the detail scan was not run this pass
    (e.g. a --from-scan rebuild with no live token)."""
    if not detail:
        return None
    departments = sorted(detail.get("departments") or [], key=lambda d: -_num(d.get("sales_3m")))
    shops = sorted(detail.get("shops") or [], key=lambda s: -_num(s.get("sales_3m")))
    warehouses = detail.get("warehouses") or []
    states = []
    for row in detail.get("states") or []:
        label, urgency, color = _state_label(str(row.get("action") or ""))
        states.append({**row, "label": label, "urgency": urgency, "color": color})
    return {
        "departments": departments, "shops": shops, "warehouses": warehouses,
        "states": states, "quiet_shop": detail.get("quiet_shop"),
    }


def _product_section(product: dict | None) -> dict | None:
    """Shapes `sku_overview_product.build`'s output for rendering. Returns
    None when no action rule had a candidate to feature - a genuinely quiet
    day, stated plainly rather than showing a fabricated subject."""
    if not product:
        return None
    subject = product["subject"]
    totals = product["totals"]
    status = []
    for row in product.get("status") or []:
        label, urgency, color = _state_label(str(row.get("action") or ""))
        status.append({**row, "label": label, "urgency": urgency, "color": color})
    weekly = product.get("weekly") or []
    peak_qty = max((_num(w.get("qty")) for w in weekly), default=0.0) or 1.0
    weekly_chart = [{"label": w["week_start"], "qty": _num(w.get("qty")),
                     "height_pct": _num(w.get("qty")) / peak_qty * 100.0} for w in weekly]

    category = product.get("category")
    share_of_category_pct = None
    vs_category_avg_pct = None
    if category and _num(category.get("cat_sales_3m")):
        share_of_category_pct = totals["sales_3m"] / _num(category["cat_sales_3m"]) * 100.0
    if category and _num(category.get("avg_sales_3m_per_sku")):
        avg = _num(category["avg_sales_3m_per_sku"])
        vs_category_avg_pct = (totals["sales_3m"] - avg) / avg * 100.0

    return {
        "subject": subject, "totals": totals, "status": status,
        "weekly_chart": weekly_chart, "price": product.get("price") or {},
        "category": category,
        "share_of_category_pct": share_of_category_pct,
        "vs_category_avg_pct": vs_category_avg_pct,
    }


def build(model: dict, insights: dict | None, detail: dict | None = None, *,
          model_top: dict | None = None, insights_top: dict | None = None,
          detail_top: dict | None = None, product: dict | None = None) -> dict:
    """The full page model. `insights`/`detail`/`product`/the `_top` scan may
    all be None (e.g. a --from-scan rebuild with no live token) - the page
    still renders, with each data-dependent layer or view stating plainly
    that it was not computed this run."""
    all_view = _build_view(model, insights, detail, scope_label="All products", scoped=False)
    top_view = None
    if model_top is not None:
        top_view = _build_view(model_top, insights_top, detail_top,
                                scope_label="Best sellers only (Segment A)", scoped=True)

    return {
        "title": model.get("report_name") or "SKU Overview",
        "as_at": model.get("as_at"), "period_label": model.get("period_label"),
        "currency": str(model.get("currency") or ""),
        "views": {"all": all_view, "top": top_view},
        "product": _product_section(product),
        "rules_available": bool(insights),
    }
