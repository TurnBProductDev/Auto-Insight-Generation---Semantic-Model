"""Render the inventory dashboard, reusing the sales dashboard's visual system.

The look, the navigation rail, the view toggle, the KPI cards, the executive
summary and every stylesheet rule come from `summary_dashboard_html` - imported,
not copied, so the two pages cannot drift apart visually and a fix to one is a
fix to both.

What is NOT reused is `_view_html`. It hard-codes year-on-year language into the
layer titles ("Which areas moved the group", "contributions sum to the group
move", "Core measures versus the comparison period"), which would be wrong on a
stock position that has no comparison period at all. So the layers are composed
here instead, from the same primitives.

Importing the underscore-prefixed helpers is deliberate. They are genuinely
shared presentation primitives that happen to live in the module that needed
them first; duplicating them to respect a naming convention would recreate
exactly the drift risk brief §1.3 warns about. Promoting them to public names in
a shared page module is a tidy-up for a later work package, not a reason to copy
them now.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...tools.summary_dashboard_html import (  # noqa: F401  (shared primitives)
    _badge,
    _donut,
    _kpi_cards,
    _layer,
    _rag_strip,
    _safe,
    _script,
    _signal_cards,
    _sparkline,
    _style,
    _tldr,
)

TONE_BAR = {
    "critical": "#c0562e",
    "warn": "#c9a227",
    "positive": "#2e9e6b",
    "neutral": "#8a97a6",
}


def _pct_text(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _hero(hero: dict, period: dict) -> str:
    if not hero:
        return ""
    as_at = period.get("data_as_of")
    # Non-negotiable 18: a position is stated as at a date, never as a span.
    context = f"Stock position as at {as_at}" if as_at else "Latest stock position"
    return (
        '<section class="hero">'
        f'<p class="hero-eyebrow">{_safe(context)}</p>'
        f'<h2 class="hero-line">{_safe(hero.get("headline"))}</h2>'
        f'<p class="hero-note">{_safe(hero.get("narrative"))}</p>'
        '</section>'
    )


def _age_bar(bands: list[dict]) -> str:
    """The age profile as one ordered bar - the ORDER is the finding."""
    total = sum(float(b.get("value") or 0) for b in bands) or 1.0
    colours = ["#2e9e6b", "#6bbf8a", "#c9a227", "#d98324", "#c0562e", "#9b2c2c"]
    segments = "".join(
        f'<span style="width:{max(0.0, float(b.get("value") or 0)) / total * 100:.4f}%;'
        f'background:{colours[min(index, len(colours) - 1)]}" '
        f'title="{_safe(b.get("name"))}: {_safe(b.get("share_pct") and _pct_text(b.get("share_pct")))}">'
        '</span>'
        for index, b in enumerate(bands)
    )
    legend = "".join(
        f'<span class="lg"><i style="background:{colours[min(index, len(colours) - 1)]}"></i>'
        f'{_safe(b.get("name"))} {_safe(_pct_text(b.get("share_pct")))}</span>'
        for index, b in enumerate(bands)
    )
    return (f'<div class="agebar">{segments}</div>'
            f'<div class="agelegend">{legend}</div>')


def _contribution_rows(cards: list[dict], caption: str) -> str:
    """Each location's share of the group total, as ranked bars.

    What the total *is* differs per report - aged stock, or value above agreed
    cover - so the caption is supplied by the view rather than written here.
    """
    if not cards:
        return ""
    peak = max((abs(float(c.get("share_of_group_pct") or 0)) for c in cards),
               default=0.0) or 1.0
    rows = "".join(
        '<div class="crow">'
        f'<span class="clab">{_safe(c.get("member"))}</span>'
        '<span class="ctrack">'
        f'<span class="cfill" style="width:{abs(float(c.get("share_of_group_pct") or 0)) / peak * 100:.2f}%;'
        f'background:{TONE_BAR.get(str(c.get("tone")), TONE_BAR["neutral"])}"></span>'
        '</span>'
        f'<span class="cval">{_safe(c.get("value_display"))}</span>'
        f'<span class="cpct">{_safe(_pct_text(c.get("share_of_group_pct")))}</span>'
        '</div>'
        for c in cards
    )
    return (f'<h3 class="block-title">{_safe(caption)}</h3>'
            f'<div class="contrib">{rows}</div>')


def _location_cards(cards: list[dict]) -> str:
    if not cards:
        return ""
    items = "".join(
        '<article class="card ent">'
        f'<div class="ent-h"><span class="ent-n">{_safe(c.get("member"))}</span>'
        f'{_badge(str(c.get("change_display")), str(c.get("tone")))}</div>'
        f'<div class="val">{_safe(c.get("value_display"))}</div>'
        f'<p class="note">{_safe(c.get("note"))}</p>'
        '</article>'
        for c in cards
    )
    return f'<div class="grid ents">{items}</div>'


def _area_table(areas: dict, labels: dict) -> str:
    """The division table.

    Column headings come from the view, never from this module: both inventory
    reports render through here and they measure different things (aged stock
    against value held above agreed cover). See `dashboard.AGEING_LABELS`.
    """
    rows = areas.get("rows") or []
    if not rows:
        return '<p class="note-band">No division breakdown was returned.</p>'
    body = "".join(
        '<tr>'
        f'<td>{_safe(r.get("name"))}</td>'
        f'<td class="n">{_safe(r.get("value_display"))}</td>'
        f'<td class="n">{_safe(r.get("held_display"))}</td>'
        f'<td class="n">{_safe(_pct_text(r.get("own_share")))}</td>'
        f'<td><span class="dot" style="background:{TONE_BAR.get(str(r.get("tone")), TONE_BAR["neutral"])}"></span></td>'
        '</tr>'
        for r in rows
    )
    return (
        f'<h3 class="block-title">{_safe(areas.get("caption"))}</h3>'
        '<div class="scroll"><table><thead><tr>'
        f'<th>{_safe(labels.get("area_member", "Division"))}</th>'
        f'<th class="n">{_safe(labels.get("area_value", "Value"))}</th>'
        f'<th class="n">{_safe(labels.get("area_held", "Stock held"))}</th>'
        f'<th class="n">{_safe(labels.get("area_share", "Share of its own stock"))}</th>'
        '<th></th></tr></thead>'
        f'<tbody>{body}</tbody></table></div>'
    )


def _queue_block(queue: list[dict]) -> str:
    """The work queue, ordered by urgency rather than by value (BR-31).

    The two double-warning states are marked, because they combine two problems
    at once and the rulebook says to report them first.
    """
    if not queue:
        return ""
    body = "".join(
        f'<tr{" class=\"urgent\"" if r.get("double_warning") else ""}>'
        f'<td>{_safe(r.get("action"))}'
        + ('<span class="flag">most urgent</span>' if r.get("double_warning") else "")
        + f'</td>'
        f'<td class="n">{int(r.get("loc_skus") or 0):,}</td>'
        f'<td class="n">{_safe(_money(r.get("stock_value")))}</td>'
        f'<td class="act">{_safe(r.get("guidance"))}</td>'
        '</tr>'
        for r in queue
    )
    return (
        '<h3 class="block-title">What to do next, most urgent first</h3>'
        '<div class="scroll"><table class="queue"><thead><tr>'
        '<th>Situation</th><th class="n">Product lines</th>'
        '<th class="n">Stock value</th><th>What the buying team should do</th>'
        f'</tr></thead><tbody>{body}</tbody></table></div>'
        '<p class="viz-note">Every product-location line in the dashboard carries '
        'one of these situations, so the list is complete.</p>'
    )


def _simple_table(rows: list[dict], title: str, columns: list[tuple]) -> str:
    if not rows:
        return ""
    head = "".join(
        f'<th{" class=\"n\"" if numeric else ""}>{_safe(label)}</th>'
        for label, _key, numeric, _fmt in columns)
    body = "".join(
        "<tr>" + "".join(
            f'<td{" class=\"n\"" if numeric else ""}>{_safe(fmt(r.get(key)))}</td>'
            for _label, key, numeric, fmt in columns) + "</tr>"
        for r in rows)
    return (f'<h3 class="block-title">{_safe(title)}</h3>'
            f'<div class="scroll"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def _count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _text(value: Any) -> str:
    return str(value if value is not None else "-")


def _detail_block(detail: dict) -> str:
    parts: list[str] = []

    # Inventory Management: the queue leads the layer.
    queue = detail.get("queue") or []
    if queue:
        parts.append(_queue_block(queue))
        parts.append(_simple_table(
            detail.get("sections") or [], "Sections holding the most above cover",
            [("Section", "name", False, _text),
             ("Above cover", "excess_value", True, _money),
             ("Stock held", "stock_value", True, _money)]))
        parts.append(_simple_table(
            detail.get("segments") or [],
            "By how much each product sells (A sells most, D least)",
            [("Segment", "name", False, _text),
             ("Product lines", "loc_skus", True, _count),
             ("Stock value", "stock_value", True, _money),
             ("Above cover", "excess_value", True, _money)]))
        parts.append(_simple_table(
            detail.get("non_moving_bands") or [], "How long stock has not sold",
            [("Days without a sale", "name", False, _text),
             ("Product lines", "loc_skus", True, _count),
             ("Stock value", "stock_value", True, _money)]))
        parts.append(_simple_table(
            detail.get("damage") or [], "Stock written off, by month",
            [("Month", "month", False, _text),
             ("Written off", "value", True, _money)]))
        return "".join(p for p in parts if p)

    bands = detail.get("bands") or []
    if bands:
        body = "".join(
            '<tr>'
            f'<td>{_safe(b.get("name"))}</td>'
            f'<td class="n">{_safe(_money(b.get("value")))}</td>'
            f'<td class="n">{_safe(_pct_text(b.get("share_pct")))}</td>'
            f'<td class="n">{_safe(_money(b.get("aged_value")))}</td>'
            f'<td class="n">{_safe(_pct_text(b.get("cumulative_older_pct")))}</td>'
            '</tr>'
            for b in bands
        )
        parts.append(
            '<h3 class="block-title">Every age band</h3>'
            '<div class="scroll"><table><thead><tr><th>Age band</th>'
            '<th class="n">Stock value</th><th class="n">Share</th>'
            '<th class="n">Of which aged</th><th class="n">This band or older</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>')

    split = detail.get("risk_split") or {}
    if split:
        parts.append(
            '<h3 class="block-title">Aged and not selling are separate things</h3>'
            '<div class="scroll"><table><thead><tr><th></th>'
            '<th class="n">Not selling</th><th class="n">Still selling</th>'
            '</tr></thead><tbody>'
            f'<tr><td>Aged</td><td class="n">{_safe(_money(split.get("aged_non_moving")))}</td>'
            f'<td class="n">{_safe(_money(split.get("aged_moving")))}</td></tr>'
            f'<tr><td>Not aged</td><td class="n">{_safe(_money(split.get("fresh_non_moving")))}</td>'
            f'<td class="n">{_safe(_money(split.get("fresh_moving")))}</td></tr>'
            '</tbody></table></div>'
            '<p class="viz-note">These overlap, so they are never added together '
            'into a single at-risk figure.</p>')

    sections = detail.get("sections") or []
    if sections:
        body = "".join(
            f'<tr><td>{_safe(s.get("name"))}</td>'
            f'<td class="n">{_safe(_money(s.get("value")))}</td>'
            f'<td class="n">{_safe(_money(s.get("total")))}</td></tr>'
            for s in sections
        )
        parts.append(
            '<h3 class="block-title">Sections holding the most aged stock</h3>'
            '<div class="scroll"><table><thead><tr><th>Section</th>'
            '<th class="n">Aged stock</th><th class="n">Stock held</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>')

    sku_types = detail.get("sku_types") or []
    if sku_types:
        body = "".join(
            f'<tr><td>{_safe(t.get("name"))}</td>'
            f'<td class="n">{_safe(_money(t.get("value")))}</td>'
            f'<td class="n">{_safe(_money(t.get("aged")))}</td>'
            f'<td class="n">{_safe(_pct_text(_ratio(t.get("aged"), t.get("value"))))}</td></tr>'
            for t in sku_types
        )
        parts.append(
            '<h3 class="block-title">Locally bought against imported</h3>'
            '<div class="scroll"><table><thead><tr><th>Type</th>'
            '<th class="n">Stock value</th><th class="n">Aged stock</th>'
            '<th class="n">Aged share</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>')

    return "".join(parts)


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if abs(number) >= 1_000_000:
        return f"SAR {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"SAR {number / 1_000:.0f}K"
    return f"SAR {number:,.0f}"


def _ratio(part: Any, whole: Any) -> float | None:
    try:
        part, whole = float(part), float(whole)
    except (TypeError, ValueError):
        return None
    return None if not whole else part / whole * 100.0


def _view_html(view: dict, active: bool) -> str:
    key = str(view.get("key") or "view")
    period = view.get("period") or {}
    layers = view.get("layers") or {}
    entities = layers.get("entities") or {}
    areas = layers.get("areas") or {}
    # Owned by the view, because the two reports measure different things and
    # this renderer serves both. A missing set would silently reintroduce one
    # report's vocabulary on the other's page, so there is no default here.
    labels = view.get("labels") or {}

    overview = (
        _hero(view.get("hero") or {}, period)
        + '<h3 class="block-title">The position at a glance</h3>'
        + _kpi_cards(view.get("kpis") or [])
        + (('<h3 class="block-title">What the headline does not show</h3>'
            + _signal_cards(view.get("signals") or []))
           if view.get("signals") else "")
        + (('<h3 class="block-title">Where the stock sits by age</h3>'
            + _age_bar((layers.get("detail") or {}).get("bands") or []))
           if (layers.get("detail") or {}).get("bands") else "")
    )

    entities_body = (
        _contribution_rows(entities.get("cards") or [], entities.get("caption") or "")
        + _location_cards(entities.get("cards") or [])
    ) if entities.get("available") else (
        '<p class="note-band">No location breakdown was returned for this view.</p>')

    limitations = "".join(
        f'<p class="note-band">{_safe(text)}</p>'
        for text in view.get("limitations") or []
    )
    context = f'Stock position as at {period.get("data_as_of")}' if period.get("data_as_of") else ""

    return (
        f'<section class="view" data-view="{_safe(key)}"{"" if active else " hidden"}>'
        f'<p class="view-context">{_safe(context)}</p>{limitations}'
        + _tldr(view.get("tldr") or [], key)
        + _layer(key, "overview", "The position at a glance",
                 "a stock position, read four ways", overview, True)
        + _layer(key, "entities",
                 labels.get("entities_title", "Locations"),
                 labels.get("entities_sub", ""), entities_body, False)
        + _layer(key, "areas",
                 labels.get("areas_title", "Divisions"),
                 labels.get("areas_sub", ""), _area_table(areas, labels), False)
        + _layer(key, "detail",
                 labels.get("detail_title", "Full detail"),
                 labels.get("detail_sub", ""),
                 _detail_block(layers.get("detail") or {}), False)
        + '</section>'
    )


_EXTRA_CSS = """
.agebar{display:flex;height:30px;border-radius:8px;overflow:hidden;margin:10px 0 8px}
.agebar span{display:block}
.agelegend{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:#5a6b7f;margin-bottom:8px}
.agelegend .lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}
.contrib{display:flex;flex-direction:column;gap:6px;margin:8px 0 18px}
.crow{display:grid;grid-template-columns:150px 1fr 110px 70px;gap:10px;align-items:center;font-size:13px}
.ctrack{background:#eef2f6;border-radius:99px;height:10px;overflow:hidden}
.cfill{display:block;height:100%;border-radius:99px}
.cval,.cpct{text-align:right;font-variant-numeric:tabular-nums}
.grid.ents{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card.ent .ent-h{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px}
.card.ent .ent-n{font-weight:600}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%}
table.queue td.act{color:#5a6b7f;font-size:12.5px}
table.queue tr.urgent td{background:#fdf1ec}
.flag{display:inline-block;margin-left:8px;font-size:9.5px;font-weight:700;letter-spacing:.06em;
      text-transform:uppercase;color:#c0562e;border:1px solid #c0562e;border-radius:99px;padding:1px 7px}
@media (max-width:640px){.crow{grid-template-columns:110px 1fr 90px}.cpct{display:none}}
"""


def render(page: dict, eyebrow: str = "Inventory") -> str:
    """The whole dashboard as one self-contained HTML document."""
    views = list((page or {}).get("views") or [])
    title = str((page or {}).get("title") or "Inventory")
    if not views:
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_safe(title)}</title><style>{_style()}</style></head><body>'
            f'<main class="page"><h1>{_safe(title)}</h1>'
            '<p class="note-band">This report could not be produced.</p>'
            '</main></body></html>'
        )

    default_view = str((page or {}).get("default_view") or views[0].get("key"))
    layer_titles = (page or {}).get("layer_titles") or {}
    layers_present = [
        str(layer) for layer in (page or {}).get("layers") or []
        if any((view.get("layers") or {}).get(layer) for view in views)
    ]
    rail = "".join(
        f'<button class="rail-btn" type="button" data-layer="{_safe(layer)}" '
        f'aria-pressed="{"true" if index == 0 else "false"}">'
        f'{_safe(layer_titles.get(layer, layer.title()))}</button>'
        for index, layer in enumerate(layers_present)
    )
    toggle = (
        '<div class="seg" role="group" aria-label="Stock view">'
        + "".join(
            f'<button type="button" data-view="{_safe(v.get("key"))}" '
            f'aria-pressed="{"true" if str(v.get("key")) == default_view else "false"}">'
            f'{_safe(v.get("label"))}</button>'
            for v in views)
        + '</div>'
    ) if len(views) > 1 else ""

    body = "".join(
        _view_html(view, str(view.get("key")) == default_view) for view in views)

    shown = {str(text).strip()
             for view in views for text in view.get("limitations") or []}
    caveats = "".join(
        f'<p class="note-band">{_safe(caveat)}</p>'
        for caveat in (page or {}).get("caveats") or []
        if str(caveat).strip() not in shown)
    subtitle = (f'<p class="sub">{_safe((page or {}).get("subtitle"))}</p>'
                if (page or {}).get("subtitle") else "")
    generated = datetime.now(timezone.utc).date().isoformat()

    # The skeleton must match what _style() expects, exactly. `.app` is a flex
    # ROW whose only children are the rail and <main>; everything else lives
    # inside `main > .page`. Getting this wrong renders the header, rail, views
    # and footer as four side-by-side columns, with the title wrapping one word
    # per line - which is precisely what happened the first time.
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)}</title><style>{_style()}{_EXTRA_CSS}</style></head>
<body><div class="app" id="report">
<nav class="rail" aria-label="Report layers"><div class="rail-mark" aria-hidden="true">AI</div>
<div class="rail-nav">{rail}</div></nav>
<main><div class="page">
<header class="hero-head"><div>
<p class="eyebrow">{_safe(eyebrow)}</p><h1>{_safe(title)}</h1>{subtitle}
<p class="sub">Generated {_safe(generated)}</p></div>{toggle}</header>
{body}{caveats}
<footer><span>All values are SAR at landing cost, excluding VAT. Every figure is
copied or derived arithmetically from the scanned stock position; no number is
estimated.</span><strong>AI-assisted analysis</strong></footer>
</div></main></div>{_script()}</body></html>"""
