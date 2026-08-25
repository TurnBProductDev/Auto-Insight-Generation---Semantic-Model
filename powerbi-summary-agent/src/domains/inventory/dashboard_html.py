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
from . import charts, money

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
    # Gap 2: the as-at date is stated ONCE, in the masthead. Non-negotiable 18
    # still applies to it there - a position is stated as at a date, never as a
    # span - but repeating it here put it twice in the first 120px.
    del period
    return (
        '<section class="hero">'
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
        '<div class="scroll"><table class="tbl"><thead><tr>'
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
        ('<tr class="urgent">' if r.get("double_warning") else '<tr>')
        + f'<td>{_safe(r.get("action"))}'
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
        '<div class="scroll"><table class="tbl queue"><thead><tr>'
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
        ('<th class="n">' if numeric else '<th>') + f'{_safe(label)}</th>'
        for label, _key, numeric, _fmt in columns)
    body = "".join(
        "<tr>" + "".join(
            ('<td class="n">' if numeric else '<td>')
            + f'{_safe(fmt(r.get(key)))}</td>'
            for _label, key, numeric, fmt in columns) + "</tr>"
        for r in rows)
    return (f'<h3 class="block-title">{_safe(title)}</h3>'
            f'<div class="scroll"><table class="tbl"><thead><tr>{head}</tr></thead>'
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
        bands_nm = detail.get("non_moving_bands") or []
        if bands_nm:
            parts.append('<h3 class="block-title">How long stock has not sold</h3>')
            parts.append(charts.duration_columns(bands_nm))
        parts.append(_simple_table(
            bands_nm, "The same bands as a table",
            [("Days without a sale", "name", False, _text),
             ("Product lines", "loc_skus", True, _count),
             ("Stock value", "stock_value", True, _money)]))
        damage = detail.get("damage") or []
        if damage:
            parts.append('<h3 class="block-title">Stock written off, by month</h3>')
            parts.append(charts.trend_area(
                damage, "month", "value",
                "Negative stock adjustments - damage, expiry and wastage. Four "
                "months is a shape, not a trend to project forward from."))
        parts.append(_simple_table(
            damage, "The same months as a table",
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
            '<h3 class="block-title">How much is older than this?</h3>'
            + charts.cumulative_curve(bands))
        parts.append(
            '<h3 class="block-title">Every age band</h3>'
            '<div class="scroll"><table class="tbl"><thead><tr><th>Age band</th>'
            '<th class="n">Stock value</th><th class="n">Share</th>'
            '<th class="n">Of which aged</th><th class="n">This band or older</th>'
            f'</tr></thead><tbody>{body}</tbody></table></div>')

    split = detail.get("risk_split") or {}
    if split:
        parts.append(
            '<h3 class="block-title">Aged and not selling are separate things</h3>'
            '<div class="scroll"><table class="tbl"><thead><tr><th></th>'
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
            '<div class="scroll"><table class="tbl"><thead><tr><th>Section</th>'
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
            # Imported stock is expected to age more - longer lead times force
            # bigger batches (BR-20). The question the chart answers is whether
            # the gap is bigger than that explains, which needs both rates side
            # by side rather than one share at a time.
            + charts.split_bars(sku_types, value_key="aged", total_key="value")
            + '<div class="scroll"><table class="tbl"><thead><tr><th>Type</th>'
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
        return f"{money.CURRENCY} {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{money.CURRENCY} {number / 1_000:.0f}K"
    return f"{money.CURRENCY} {number:,.0f}"


def _ratio(part: Any, whole: Any) -> float | None:
    try:
        part, whole = float(part), float(whole)
    except (TypeError, ValueError):
        return None
    return None if not whole else part / whole * 100.0


def _score_layer_html(score: dict) -> str:
    """The Inventory Health Score: the gauge, the composition, the six risks.

    The waterfall shows COMPOSITION, not movement - with one stock position
    there is nothing to decompose a change into - so it is labelled as such and
    runs 100 down to the score, biggest cause first.
    """
    if not score.get("available"):
        return ('<p class="note-band">This dashboard does not publish an '
                'Inventory Health Score.</p>')

    value = score.get("score")
    band = score.get("band") or ""
    lost = score.get("points_lost") or 0.0
    tone = {"Excellent": "positive", "Healthy": "positive", "Watch": "warn",
            "At Risk": "warn", "Critical": "critical"}.get(band, "neutral")

    bands = "".join(
        f'<li><b>{b["floor"]:.0f}+</b> {_safe(b["name"])}</li>'
        if b["floor"] else f'<li><b>below 60</b> {_safe(b["name"])}</li>'
        for b in score.get("bands") or [])

    head = (
        f'<div class="score-head">'
        f'<div class="score-dial tone-{tone}">'
        f'<span class="score-value">{value:.1f}</span>'
        f'<span class="score-band">{_safe(band)}</span></div>'
        f'<div class="score-copy">'
        f'<p>Every SKU starts at 100 and loses points to six risks, each capped '
        f'at {score.get("risk_cap", 25):.0f}. '
        f'{lost:.1f} points are lost, leaving {value:.1f}.</p>'
        f'<ul class="score-bands">{bands}</ul></div></div>')

    # Composition bars. Each risk's width is its share of the whole loss, so the
    # six add to the full bar and nothing is left unexplained.
    rows = []
    for item in score.get("waterfall") or []:
        share = item.get("share_pct") or 0.0
        alias = (f'<span class="d-model">model: {_safe(item["model_name"])}</span>'
                 if item.get("model_name") else "")
        rows.append(
            f'<tr><th>{_safe(item["name"])}{alias}</th>'
            f'<td class="num">{item["points"]:.1f}</td>'
            f'<td class="bar-cell"><span class="bar" style="width:{max(1.0, share):.1f}%"></span></td>'
            f'<td class="num">{share:.1f}%</td></tr>')
    table = (
        '<table class="tbl score-tbl"><caption>What the score is losing, '
        'biggest cause first. This is what the position is made of, not how it '
        'has moved - only one position is kept.</caption>'
        '<thead><tr><th>Risk</th><th class="num">Points</th>'
        '<th>Share of the loss</th><th class="num">%</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>')

    # How each risk is worked out. Dropped, with a reason, if the model's own
    # build-up stopped matching the weights this report was set up with.
    if score.get("method_available"):
        cards = []
        for risk in score.get("risks") or []:
            dims = "".join(
                f'<li>{_safe(d["name"])} <b>{d["weight_pct"]:.0f}%</b>'
                f'<span class="num">{(d["value"] or 0.0) * 100:.1f}%</span></li>'
                for d in risk.get("dimensions") or [])
            cap = ('<span class="pill pill-critical">AT CAP</span>'
                   if risk.get("at_cap") else "")
            alias = (f'<p class="d-model">Called '
                     f'&ldquo;{_safe(risk["model_name"])}&rdquo; in the model</p>'
                     if risk.get("model_name") else "")
            cards.append(
                f'<article class="card risk-card"><h4>{_safe(risk["name"])} {cap}</h4>'
                f'{alias}<p class="big">{risk["points"]:.1f} <small>points</small></p>'
                f'<ul class="dims">{dims}</ul></article>')
        method = (
            '<section class="method"><h3>How the score is worked out</h3>'
            '<p>Each risk is built from its own parts and multiplied by '
            f'{score.get("risk_cap", 25):.0f}, then capped there. The weights '
            'are read from the dashboard itself, and this report checks every '
            'run that they still add up to the published score.</p>'
            f'<div class="grid-3">{"".join(cards)}</div></section>')
    else:
        method = f'<p class="note-band">{_safe(score.get("method_note"))}</p>'

    # The scored population by band. Out of Stock is not a band - those lines
    # start from 0 rather than 100 - so it is listed apart, never sorted among
    # them as though it were one.
    band_rows = "".join(
        f'<tr><th>{_safe(b["name"])}'
        + ('' if b["is_band"] else '<span class="d-model">not a band</span>')
        + f'</th><td class="num">{b["loc_skus"]:,}</td>'
        f'<td class="num">{_money(b["stock_value"])}</td></tr>'
        for b in score.get("status_bands") or [])
    population = (
        '<table class="tbl"><caption>Where the scored Loc-SKUs sit. Out of Stock '
        'lines start from zero rather than 100, so they are listed separately '
        'rather than placed in a band.</caption>'
        '<thead><tr><th>Band</th><th class="num">Loc-SKUs</th>'
        '<th class="num">Stock Value</th></tr></thead>'
        f'<tbody>{band_rows}</tbody></table>')

    avg = score.get("avg_scored_line")
    gap = (f'<p class="note">The average scored line reads {avg:.1f} against a '
           f'company score of {value:.1f}. They differ because the company score '
           f'is rebuilt from where the value and the breadth actually sit, not '
           f'averaged across lines.</p>' if avg is not None else "")

    return (head + '<div class="two-up">' + table + population + '</div>'
            + gap + method)


def _focus_layer_html(focus: dict) -> str:
    """The few risks worth acting on, each answering four questions."""
    if not focus.get("available"):
        return ('<p class="note-band">This dashboard does not publish an '
                'Inventory Health Score, so there is nothing to rank by.</p>')

    stories = focus.get("stories") or []
    if not stories:
        return '<p class="note-band">No risk is currently costing the score.</p>'

    covered = focus.get("covered_points") or 0.0
    lost = focus.get("points_lost") or 0.0
    lead = (f'<p class="note">Ordered by what each is costing the score, not by '
            f'how much stock it holds. Together these {len(stories)} account for '
            f'{covered:.1f} of the {lost:.1f} points lost.</p>')

    cards = []
    for story in stories:
        alias = (f'<p class="d-model">Called '
                 f'&ldquo;{_safe(story["model_name"])}&rdquo; in the model</p>'
                 if story.get("model_name") else "")
        cards.append(
            f'<article class="card story"><h4>{_safe(story["name"])}</h4>{alias}'
            f'<dl>'
            f'<dt>What it is</dt><dd>{_safe(story["what_it_is"])}</dd>'
            f'<dt>What it does to the score</dt><dd>{_safe(story["effect"])}</dd>'
            f'<dt>Do this</dt><dd>{_safe(story["do_this"])}</dd>'
            f'</dl></article>')

    queue = focus.get("queue") or []
    total = focus.get("queue_total") or len(queue)
    queue_rows = "".join(
        f'<tr><th>{_safe(row.get("action"))}</th>'
        f'<td class="num">{int(row.get("loc_skus") or 0):,}</td>'
        f'<td>{_safe(row.get("guidance") or "")}</td></tr>'
        for row in queue)
    evidence = (
        '<h3>The evidence underneath</h3>'
        f'<table class="tbl"><caption>The most urgent Recommended Actions. '
        f'All {total} states are in the Recommended Actions tab.</caption>'
        '<thead><tr><th>Recommended Action</th><th class="num">Loc-SKUs</th>'
        '<th>What to do</th></tr></thead>'
        f'<tbody>{queue_rows}</tbody></table>')

    return lead + f'<div class="grid-2">{"".join(cards)}</div>' + evidence


def _change_layer_html(change: dict) -> str:
    """What changed, one block per comparison lane.

    Each lane states its own window in its own heading. That repetition is
    deliberate and is the one thing this layer cannot get wrong: two comparisons
    over two different windows sitting under one shared date would be read as
    one comparison, and the reader has no way to notice.
    """
    if change.get("pointer"):
        return f'<p class="note-band">{_safe(change["pointer"])}</p>'
    lanes = change.get("lanes") or []
    if not lanes:
        return (f'<p class="note-band">{_safe(change.get("reason") or "")}</p>'
                if change.get("reason") else "")

    parts: list[str] = []
    if change.get("caption"):
        parts.append(f'<p class="viz-note">{_safe(change["caption"])}</p>')

    for lane in lanes:
        parts.append(f'<h3 class="block-title">{_safe(lane.get("title"))}</h3>')
        if not lane.get("available"):
            parts.append(f'<p class="note-band">{_safe(lane.get("reason") or "")}</p>')
            continue
        parts.append(
            '<div class="lane-head">'
            f'<span class="lane-verdict lane-{_safe(lane.get("verdict_tone") or "neutral")}">'
            f'{_safe(lane.get("verdict"))}</span>'
            f'<span class="lane-window">{_safe(lane.get("window"))}</span>'
            f'<span class="lane-sub">{_safe(lane.get("sub"))}</span>'
            '</div>')
        then_label = _date_text(lane.get("window"), first=True)
        now_label = _date_text(lane.get("window"), first=False)
        parts.append(charts.shift_dumbbells(
            lane.get("headlines") or [], then_label, now_label))
        if lane.get("agreement"):
            parts.append(f'<p class="viz-note">{_safe(lane["agreement"])}</p>')
        if not lane.get("value_comparable") and lane.get("value_note"):
            parts.append(
                '<div class="basis-note"><strong>Why totals are not compared</strong>'
                f'<p>{_safe(lane["value_note"])}</p></div>')

        bands = lane.get("bands") or []
        if bands:
            parts.append('<h3 class="block-title">Where the stock sits on the '
                         'age scale, then and now</h3>')
            parts.append(charts.band_share_pairs(bands, then_label, now_label))

        members = lane.get("members") or []
        if members:
            body = "".join(
                '<tr>'
                f'<td>{_safe(m.get("name"))}</td>'
                f'<td class="n">{_safe(_pct_text(m.get("aged_share_then_pct")))}</td>'
                f'<td class="n">{_safe(_pct_text(m.get("aged_share_now_pct")))}</td>'
                f'<td class="n">{_safe(_points_text(m.get("points")))}</td>'
                f'<td>{_safe(_move_word(m.get("direction")))}</td>'
                '</tr>'
                for m in members)
            parts.append(
                '<h3 class="block-title">Which locations moved</h3>'
                '<div class="scroll"><table class="tbl"><thead><tr><th>Location</th>'
                f'<th class="n">Aged share, {_safe(then_label)}</th>'
                f'<th class="n">Aged share, {_safe(now_label)}</th>'
                '<th class="n">Change</th><th>Reading</th>'
                f'</tr></thead><tbody>{body}</tbody></table></div>'
                '<p class="viz-note">Each location measured against its own '
                'stock, so a small store and a large warehouse can be compared '
                'fairly.</p>')

        skus_now, skus_then = lane.get("skus_now"), lane.get("skus_then")
        if skus_now and skus_then:
            moved = int(skus_now) - int(skus_then)
            word = ("the same number of" if moved == 0
                    else f"{abs(moved):,} {'more' if moved > 0 else 'fewer'}")
            parts.append(
                f'<p class="viz-note">The business stocked {word} products on '
                f'{_safe(now_label)} than on {_safe(then_label)} '
                f'({int(skus_then):,} to {int(skus_now):,}). Counting products '
                f'is not affected by how stock is valued.</p>')
    return "".join(parts)


def _date_text(window: Any, *, first: bool) -> str:
    """Pull one end of a window label like `14 August to 23 August - 9 days`."""
    text = str(window or "")
    if " to " not in text:
        return "earlier" if first else "now"
    left, right = text.split(" to ", 1)
    return left.strip() if first else right.split(" - ")[0].strip()


def _points_text(value: Any) -> str:
    number = _ratio_num(value)
    if number is None:
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.1f} pts"


def _move_word(direction: Any) -> str:
    return {"worse": "Got worse", "better": "Improved"}.get(
        str(direction or ""), "About the same")


def _ratio_num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _outlook_layer_html(outlook: dict) -> str:
    """Clearance, the category review and the stuck product lines."""
    if outlook.get("pointer"):
        return f'<p class="note-band">{_safe(outlook["pointer"])}</p>'
    parts: list[str] = []

    clearance = outlook.get("clearance") or {}
    if clearance.get("available"):
        horizon = int(clearance.get("horizon_days") or 30)
        parts.append(
            f'<h3 class="block-title">How much of the old stock would sell in '
            f'the next {horizon} days</h3>')
        parts.append(charts.clearance_bars(clearance.get("rows") or [], horizon))
        parts.append(_simple_table(
            clearance.get("rows") or [], "The same divisions as a table",
            [("Division", "name", False, _text),
             ("Aged stock", "aged_value", True, _money),
             ("Aged share of its own stock", "aged_share_pct", True, _pct_text),
             ("Units sitting aged", "aged_qty", True, _count),
             ("Units sold a day", "daily_qty", True, _count),
             (f"Clears in {horizon} days", "cleared_pct", True, _pct_text),
             ("Time to clear it all", "days_display", False, _text)]))
        for caveat in clearance.get("caveats") or []:
            parts.append(f'<p class="viz-note">{_safe(caveat)}</p>')
    elif clearance.get("reason"):
        parts.append(f'<p class="note-band">{_safe(clearance["reason"])}</p>')

    categories = outlook.get("categories") or {}
    if categories.get("available"):
        parts.append(
            f'<h3 class="block-title">Categories with too much old stock of '
            f'their own</h3>')
        parts.append(
            '<div class="cat-headline">'
            f'<span class="cat-big">{int(categories.get("over") or 0):,}</span>'
            f'<span class="cat-of">of {int(categories.get("carried") or 0):,} '
            f'categories are above the '
            f'{float(categories.get("threshold_pct") or 30):.0f}% line</span>'
            '</div>')
        parts.append(charts.category_bars(
            categories.get("worst") or [],
            float(categories.get("threshold_pct") or 30)))
        highest = categories.get("highest_share") or {}
        if highest.get("name"):
            parts.append(
                f'<p class="viz-note">The highest percentage of all belongs to '
                f'{_safe(highest.get("name"))} at '
                f'{_safe(_pct_text(highest.get("aged_share_pct")))}, but only '
                f'{_safe(_money(highest.get("aged")))} sits behind it. That is '
                f'why the list above is ordered by money rather than by '
                f'percentage.</p>')
    elif categories.get("reason"):
        parts.append(f'<p class="note-band">{_safe(categories["reason"])}</p>')

    stuck = outlook.get("stuck") or {}
    if stuck.get("available"):
        parts.append('<h3 class="block-title">The product lines with the most '
                     'money stuck</h3>')
        parts.append(_simple_table(
            stuck.get("rows") or [], "",
            [("Product", "sku", False, _text),
             ("Category", "category", False, _text),
             ("Location", "location", False, _text),
             ("Units held", "qty", True, _count),
             ("Stock value", "value", True, _money),
             ("Units sold a day", "daily_qty", True, _count),
             ("Ageing risk", "risk_score", True, _score_text),
             ("Status in the source report", "status", False, _text)]))
        estate = stuck.get("estate_lines")
        if estate:
            parts.append(
                f'<p class="viz-note">These are the {len(stuck.get("rows") or []):,} '
                f'with the most money against them. Across the whole business '
                f'{int(estate):,} product-and-location lines sit at or below the '
                f'same risk score, so this table is the top of a much longer '
                f'list.</p>')
        if stuck.get("still_selling"):
            parts.append(
                f'<p class="viz-note">{int(stuck["still_selling"])} of the lines '
                f'above are still selling every day. A product can sell well and '
                f'still be at the worst risk score, when one old batch is stuck '
                f'behind newer stock of the same product.</p>')
        if stuck.get("note"):
            parts.append(f'<p class="viz-note">{_safe(stuck["note"])}</p>')
    elif stuck.get("reason"):
        parts.append(f'<p class="note-band">{_safe(stuck["reason"])}</p>')

    return "".join(p for p in parts if p)


def _score_text(value: Any) -> str:
    number = _ratio_num(value)
    return "-" if number is None else f"{number:.0f}"

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

    kind = str(view.get("kind") or "")
    detail = layers.get("detail") or {}
    total = view.get("total_value") or 0.0

    # --- the summary layer --------------------------------------------------
    # The page opens with what the whole position looks like, then narrows.
    # Each report leads with the chart that carries ITS argument: for stock age
    # that is the shape of the tail; for stock health it is the work queue, whose
    # whole point is that the biggest bar is not at the top.
    headline_block = ""
    shape_block = ""
    if kind == "ageing":
        bands = detail.get("bands") or []
        if bands:
            headline_block = (
                '<h3 class="block-title">Where the money is sitting</h3>'
                + charts.age_columns(bands))
        split = detail.get("risk_split") or {}
        if split:
            shape_block = (
                '<h3 class="block-title">Old, or not selling? Two questions, '
                'four answers</h3>' + charts.risk_matrix(split, total))
    elif kind == "stock_health":
        queue = detail.get("queue") or []
        summary = layers.get("overview") or {}
        # The ladder shows the top of the queue only; the donut below still
        # counts every row, because that split describes the whole estate.
        ladder = summary.get("queue") or queue
        total_states = summary.get("queue_total") or len(queue)
        if queue:
            more = (f'<p class="note">Showing the {len(ladder)} most urgent of '
                    f'{total_states} Recommended Action states. All of them are '
                    f'in the Recommended Actions tab.</p>'
                    if total_states > len(ladder) else "")
            headline_block = (
                '<h3 class="block-title">What needs doing, most urgent first</h3>'
                + charts.queue_ladder(ladder) + more)
            needs = sum(int(r.get("loc_skus") or 0) for r in queue
                        if r.get("is_exception"))
            rest = sum(int(r.get("loc_skus") or 0) for r in queue
                       if not r.get("is_exception"))
            shape_block = (
                '<h3 class="block-title">How much of the estate needs '
                'attention</h3>'
                + charts.composition_donut(
                    [{"label": "Needs action", "value": needs, "color": charts.AMBER},
                     {"label": "No action needed", "value": rest,
                      "color": charts.SERIES_CALM}],
                    f"{needs:,}", "product lines need action"))

    overview = (
        _hero(view.get("hero") or {}, period)
        + headline_block
        + '<h3 class="block-title">The position at a glance</h3>'
        + _kpi_cards(view.get("kpis") or [])
        + (('<h3 class="block-title">What the headline does not show</h3>'
            + _signal_cards(view.get("signals") or []))
           if view.get("signals") else "")
        + shape_block
    )

    entities_body = (
        charts.ranked_bars(
            entities.get("cards") or [], value_key="value", held_key="held",
            label_key="member", unit=str(entities.get("rate_unit") or ""),
            average=entities.get("average_rate"))
        + _contribution_rows(entities.get("cards") or [], entities.get("caption") or "")
        + _location_cards(entities.get("cards") or [])
    ) if entities.get("available") else (
        f'<p class="note-band">{_safe(entities.get("pointer"))}</p>'
        if entities.get("pointer") else
        '<p class="note-band">No location breakdown was returned for this view.</p>')

    limitations = "".join(
        f'<p class="note-band">{_safe(text)}</p>'
        for text in view.get("limitations") or []
    )
    # Gap 2: the as-at date is printed ONCE, in the masthead. It used to appear
    # three times inside the first 120px - page subtitle, view context and hero
    # eyebrow - which reads as a stutter rather than as emphasis.

    # The Stock Age page grew two tabs once the source model started keeping an
    # earlier position and exposing selling rates. They are emitted only when the
    # view actually carries them, so a client whose model has neither still
    # renders exactly the four-layer page.
    change_layer = layers.get("change")
    outlook_layer = layers.get("outlook")
    change_html = (
        _layer(key, "change", "What changed",
               "how this position compares with the one before it",
               _change_layer_html(change_layer), False)
        if change_layer else "")
    outlook_html = (
        _layer(key, "outlook", "Where to act",
               "how fast the old stock clears, and what is stuck",
               _outlook_layer_html(outlook_layer), False)
        if outlook_layer else "")

    score_layer = layers.get("score") or {}
    focus_layer = layers.get("focus") or {}
    extra = ""
    if score_layer.get("available"):
        extra = (
            _layer(key, "score", "Inventory Health Score",
                   "the dashboard's own score, and what it is losing",
                   _score_layer_html(score_layer), False)
            + _layer(key, "focus", "Where to focus",
                     "the few risks costing the score the most",
                     _focus_layer_html(focus_layer), False))

    return (
        f'<section class="view" data-view="{_safe(key)}"{"" if active else " hidden"}>'
        f'{limitations}'
        + _tldr(view.get("tldr") or [], key)
        + _layer(key, "overview", "Inventory summary",
                 "the whole position, before any breakdown", overview, True)
        + change_html
        + extra
        + _layer(key, "entities",
                 labels.get("entities_title", "Locations"),
                 labels.get("entities_sub", ""), entities_body, False)
        + _layer(key, "areas",
                 labels.get("areas_title", "Divisions"),
                 labels.get("areas_sub", ""),
                 charts.ranked_bars(
                     areas.get("rows") or [], value_key="value", held_key="held",
                     unit=str(areas.get("rate_unit") or ""),
                     average=areas.get("average_rate"))
                 + _area_table(areas, labels), False)
        + outlook_html
        + _layer(key, "detail",
                 labels.get("detail_title", "Full detail"),
                 labels.get("detail_sub", ""),
                 _detail_block(layers.get("detail") or {}), False)
        + '</section>'
    )


_EXTRA_CSS = """
/* Six tabs, one of them two long words. Widen the rail rather than let a
   name break mid-word: 'Recommend / ed Actions' reads as a rendering
   fault. Scoped to this page so the sales dashboard's rail is untouched. */
.rail{width:96px;min-width:96px}
.rail-btn{width:84px;font-size:10px;overflow-wrap:break-word}
/* --- Inventory Health Score ------------------------------------------- */
/* Fixed column counts that divide the card count exactly. auto-fit lays six
   risk cards out 5+1 at 1280px and four stories 3+1, orphaning the last one
   beside a gap two cards wide. */
.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:10px}
.grid-2{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin:10px 0 20px}
.two-up{display:grid;grid-template-columns:1.4fr 1fr;gap:18px;align-items:start;margin:14px 0}
@media(max-width:900px){.grid-3,.grid-2,.two-up{grid-template-columns:1fr}}
.score-head{display:grid;grid-template-columns:190px 1fr;gap:22px;align-items:center;
  background:#0f2233;color:#fff;border-radius:14px;padding:20px 24px;margin-bottom:6px}
.score-dial{display:flex;flex-direction:column;align-items:center;justify-content:center;
  width:150px;height:150px;border-radius:50%;border:9px solid #2f8f4e;background:#12293c}
.score-dial.tone-warn{border-color:#c08429}
.score-dial.tone-critical{border-color:#cf4636}
.score-dial.tone-neutral{border-color:#8fa1a9}
.score-value{font-size:44px;font-weight:700;line-height:1;font-variant-numeric:tabular-nums}
.score-band{font-size:12px;letter-spacing:.09em;text-transform:uppercase;margin-top:6px;opacity:.88}
.score-copy p{margin:0 0 10px;font-size:14px;line-height:1.55;color:#dbe6ee}
.score-bands{list-style:none;display:flex;flex-wrap:wrap;gap:6px 16px;margin:0;padding:0;
  font-size:12px;color:#b9c9d6}
.score-bands b{color:#fff;margin-right:4px;font-variant-numeric:tabular-nums}
.score-tbl .bar-cell{width:40%}
.score-tbl .bar{display:block;height:11px;border-radius:99px;background:#0f9f95}
.d-model{display:block;font-size:11px;color:#8fa1a9;font-weight:400;margin-top:2px}
.risk-card .big{font-size:26px;font-weight:700;margin:6px 0 8px;font-variant-numeric:tabular-nums}
.risk-card .big small{font-size:12px;font-weight:500;color:#5a6b7f}
.dims{list-style:none;margin:0;padding:0;font-size:12px;color:#41566b}
.dims li{display:flex;justify-content:space-between;gap:8px;padding:3px 0;border-top:1px solid #eef2f6}
.dims li b{font-weight:600;color:#0f2233;margin-left:auto;margin-right:10px}
.dims .num{font-variant-numeric:tabular-nums;color:#5a6b7f}
/* Colour never carries meaning on its own - always paired with a word. */
.pill{display:inline-block;font-size:10px;letter-spacing:.08em;padding:2px 7px;border-radius:99px;
  vertical-align:middle;margin-left:6px;font-weight:700}
.pill-critical{background:#fbe7e4;color:#a5301f}
.method{margin-top:22px}
.method h3{margin-bottom:4px}
.story dl{margin:6px 0 0}
.story dt{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:#5a6b7f;margin-top:9px}
.story dd{margin:2px 0 0;font-size:13.5px;line-height:1.5;color:#233a4d}
/* ONE caveats block, bulleted. Never one grey box per caution. */
.caveats{margin:26px 0 8px;padding:16px 20px;background:#f5f8fa;border-radius:12px;
  border:1px solid #e3ebf1}
.caveats h3{margin:0 0 8px;font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:#5a6b7f}
.caveats ul{margin:0;padding-left:18px}
.caveats li{font-size:13px;line-height:1.6;color:#41566b;margin-bottom:5px}
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

/* --- charts -------------------------------------------------------------- */
/* Text wears text tokens, never the series colour: a value label sits in ink
   and the coloured mark beside it carries the identity. */
.dz-val{fill:#12201e;font-size:10.5px;font-weight:700;font-family:inherit}
.dz-axis{fill:#5b7182;font-size:10px;font-weight:600;font-family:inherit}
.dz-flag{fill:#c0562e;font-size:8.5px;font-weight:700;letter-spacing:.05em;font-family:inherit}
.chart-legend{display:flex;flex-wrap:wrap;gap:16px;font-size:12px;color:#5b7182;margin:2px 0 10px}
.chart-legend .lg-key{display:inline-flex;align-items:center;gap:6px}
.chart-legend .lg-key i{display:inline-block;width:11px;height:11px;border-radius:3px}
.chart-note{font-size:11.5px;color:#5b7182;margin:6px 0 16px;max-width:70ch;line-height:1.5}

/* Risk matrix: the 2x2 that keeps aged and not-selling from being added up. */
.risk-matrix{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:8px 0 4px}
.rm-cell{background:#fff;border:1px solid #dfe7ec;border-top-width:3px;border-radius:11px;padding:13px 14px}
.rm-critical{border-top-color:#cf4636}
.rm-warn{border-top-color:#c08429}
.rm-positive{border-top-color:#2f8f4e}
.rm-tag{display:block;font-size:9.5px;font-weight:750;letter-spacing:.09em;text-transform:uppercase;color:#5b7182;margin-bottom:6px}
.rm-val{display:block;font-size:22px;font-weight:700;line-height:1.15}
.rm-critical .rm-val{color:#cf4636}
.rm-warn .rm-val{color:#c08429}
.rm-positive .rm-val{color:#2f8f4e}
.rm-share{display:block;font-size:11.5px;color:#5b7182;margin-top:2px}
.rm-note{font-size:11.5px;color:#5b7182;margin:7px 0 0;line-height:1.45}

/* Ranked bars: size on the bar, severity on the rate beside it. */
.ranked-bars{display:flex;flex-direction:column;gap:7px;margin:8px 0 4px}
.rb-row{display:grid;grid-template-columns:190px 1fr 150px;gap:12px;align-items:center;font-size:13px}
.rb-lab{font-weight:600;line-height:1.25}
/* `.sb-val small` was missing here, so the two-population chart rendered
   its value and its sub-label as one run-on string: 'USD 2.21MUSD 657K
   aged'. */
.rb-lab small,.rb-val small,.sb-lab small,.sb-val small,.ql-val small{display:block;font-weight:400;font-size:11px;color:#5b7182}
.rb-track{background:#eef2f6;border-radius:99px;height:11px;overflow:hidden}
.rb-fill{display:block;height:100%;border-radius:99px}
.rb-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:650}
.rb-worse{color:#cf4636;font-weight:650}
.rb-level{color:#5b7182}

/* The action queue, in urgency order. */
.queue-ladder{display:flex;flex-direction:column;gap:6px;margin:8px 0 4px}
.ql-row{display:grid;grid-template-columns:270px 1fr 120px;gap:12px;align-items:center;font-size:12.5px}
.ql-lab{line-height:1.3;font-weight:600}
.ql-track{background:#eef2f6;border-radius:99px;height:11px;overflow:hidden}
.ql-fill{display:block;height:100%;border-radius:99px}
.ql-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
.ql-flag{display:inline-block;margin-left:7px;font-size:9px;font-weight:750;letter-spacing:.06em;
         text-transform:uppercase;border-radius:99px;padding:1px 7px;vertical-align:middle}
.ql-critical{color:#cf4636;border:1px solid #cf4636}
.ql-warn{color:#8a5f10;border:1px solid #c08429}
.ql-quiet{color:#5b7182;border:1px solid #dfe7ec}

/* Two populations, both size and rate. */
.split-bars{display:flex;flex-direction:column;gap:9px;margin:8px 0 14px}
.sb-row{display:grid;grid-template-columns:180px 1fr 150px;gap:12px;align-items:center;font-size:13px}
.sb-lab{font-weight:600}
.sb-track{background:#eef2f6;border-radius:99px;height:13px;overflow:hidden}
.sb-held{display:block;height:100%;background:#0f9f95;border-radius:99px;position:relative}
.sb-aged{position:absolute;left:0;top:0;height:100%;background:#c08429;border-radius:99px}
.sb-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:650}
.donut-wrap{display:flex;align-items:center;gap:22px;flex-wrap:wrap;margin:8px 0 4px}
.donut-wrap .chart-legend{flex-direction:column;gap:8px;margin:0}

@media (max-width:720px){
  .rb-row,.ql-row,.sb-row{grid-template-columns:1fr 1fr;grid-template-areas:"lab val" "track track"}
  .rb-lab,.ql-lab,.sb-lab{grid-area:lab}
  .rb-val,.ql-val,.sb-val{grid-area:val}
  .rb-track,.ql-track,.sb-track{grid-area:track}
}
@media print{.chart-stage{overflow:visible}.rm-cell,.ql-row,.rb-row{break-inside:avoid}}

/* A KPI card with no comparison still emitted an empty coloured pill, which
   read as a rendering fault once some cards on the same row DID carry one.
   Hidden here rather than in the shared card renderer, because that renderer
   also draws the sales dashboard and its output is byte-compared. */
.badge:empty{display:none}

/* `.scroll` was used by every table on both inventory pages and defined
   nowhere, so a wide table pushed the page sideways instead of scrolling
   inside its own box - and, because the tables carried no class at all, none
   of them picked up the shared `.tbl` styling either. Both fixed together. */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll table{min-width:100%}

/* --- Comparing two positions ------------------------------------------ */
/* Each lane states its own window in its own head, because two comparisons
   over two different windows under one shared date read as one comparison. */
.lane-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin:2px 0 12px}
.lane-verdict{font-weight:700;font-size:13px;border-radius:99px;padding:2px 11px}
.lane-critical{color:#cf4636;background:#fdeeeb}
.lane-positive{color:#2f8f4e;background:#e9f6ee}
.lane-neutral{color:#5b7182;background:#eef2f6}
.lane-window{font-size:12.5px;font-weight:650;color:#233b4d;font-variant-numeric:tabular-nums}
.lane-sub{font-size:11.5px;color:#5b7182}
.basis-note{border-left:3px solid #c08429;background:#fdf7ec;border-radius:0 8px 8px 0;
            padding:10px 14px;margin:10px 0 4px}
.basis-note strong{display:block;font-size:12px;color:#8a5f10;margin-bottom:3px}
.basis-note p{margin:0;font-size:12.5px;color:#3d5567;line-height:1.5}

/* Where it was, where it is: the gap is the reading, so the gap is drawn. */
/* Capped: on a wide screen a full-width track spreads three readings that
   sit between 7% and 18% across 900px, and the gap the chart exists to show
   becomes a smudge. */
.dumbbells{display:flex;flex-direction:column;gap:13px;margin:8px 0 4px;max-width:880px}
.band-pairs,.clearance,.cat-bars{max-width:980px}
.db-row{display:grid;grid-template-columns:210px 1fr 160px;gap:14px;align-items:center;font-size:13px}
.db-lab{font-weight:600;line-height:1.25}
.db-lab small,.db-val small,.bp-val small,.cl-lab small,.cl-val small,.cat-val small{
  display:block;font-weight:400;font-size:11px;color:#5b7182;margin-top:2px}
.db-track{position:relative;height:14px;background:#eef2f6;border-radius:99px}
.db-bar{position:absolute;top:4px;height:6px;border-radius:99px;opacity:.6}
.db-dot{position:absolute;top:1px;width:12px;height:12px;margin-left:-6px;border-radius:50%;
        border:2px solid #fff;box-shadow:0 0 0 1px rgba(16,24,40,.12)}
.db-then{background:#98a9b8}
.db-now{background:#c08429}
.db-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
.db-critical{color:#cf4636;font-weight:650}
.db-positive{color:#2f8f4e;font-weight:650}
.db-neutral{color:#5b7182}

/* Band mix on both dates. Shares, not counts - the two totals differ in size. */
.band-pairs{display:flex;flex-direction:column;gap:11px;margin:8px 0 4px}
.bp-row{display:grid;grid-template-columns:190px 1fr 140px;gap:14px;align-items:center;font-size:13px}
.bp-lab{font-weight:600}
.bp-flag{display:inline-block;margin-left:7px;font-size:9px;font-weight:750;letter-spacing:.05em;
         text-transform:uppercase;color:#8a5f10;border:1px solid #c08429;border-radius:99px;padding:1px 6px}
.bp-bars{display:flex;flex-direction:column;gap:3px}
.bp-bar{display:block;height:9px;border-radius:99px;min-width:2px}
.bp-then{background:#98a9b8}
.bp-now{background:#c08429}
.bp-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:650}

/* Clearance outlook, slowest first. */
.clearance{display:flex;flex-direction:column;gap:9px;margin:8px 0 4px}
.cl-row{display:grid;grid-template-columns:200px 1fr 190px;gap:12px;align-items:center;font-size:13px}
.cl-lab{font-weight:600;line-height:1.25}
.cl-track{background:#eef2f6;border-radius:99px;height:13px;overflow:hidden}
.cl-fill{display:block;height:100%;border-radius:99px}
.cl-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}
.cl-cap{color:#8a5f10}

/* Categories over the review line, ordered by money stuck. */
.cat-headline{display:flex;align-items:baseline;gap:12px;margin:6px 0 12px}
.cat-big{font-size:34px;font-weight:750;color:#cf4636;font-variant-numeric:tabular-nums;line-height:1}
.cat-of{font-size:13px;color:#3d5567}
.cat-bars{display:flex;flex-direction:column;gap:7px;margin:8px 0 4px}
.cat-row{display:grid;grid-template-columns:230px 1fr 165px;gap:12px;align-items:center;font-size:13px}
.cat-lab{font-weight:600;line-height:1.25}
.cat-track{background:#eef2f6;border-radius:99px;height:11px;overflow:hidden}
.cat-fill{display:block;height:100%;border-radius:99px;background:#c08429}
.cat-val{text-align:right;font-variant-numeric:tabular-nums;font-weight:650}

@media (max-width:720px){
  .db-row,.bp-row,.cl-row,.cat-row{grid-template-columns:1fr 1fr;
    grid-template-areas:"lab val" "track track"}
  .db-lab,.bp-lab,.cl-lab,.cat-lab{grid-area:lab}
  .db-val,.bp-val,.cl-val,.cat-val{grid-area:val}
  .db-track,.bp-bars,.cl-track,.cat-track{grid-area:track}
}
@media print{.db-row,.bp-row,.cl-row,.cat-row,.basis-note{break-inside:avoid}}
"""


#: Gap 10. The URL carries the state as `#<view>/<layer>`, which makes a tab
#: linkable, survives a reload, and is what lets a screenshot tool reach every
#: tab without a click:
#:
#:     chrome --headless=new --screenshot=out.png --window-size=1500,2500 \
#:         "file:///.../report_dashboard_stock_health.html#all/score"
#:
#: Appended to the shared script rather than replacing it: `_script()` already
#: carries its own <script> tags, and wrapping it again nests them, at which
#: point no JavaScript runs at all and every nav button goes dead.
_ROUTING_BODY = """
(function(){
  var app=document.getElementById('report');
  if(!app) return;
  function show(view,layer){
    // Validate BEFORE touching anything. Hiding every view and then discovering
    // the requested one does not exist leaves a blank page - which is exactly
    // what a stale or hand-typed link produced: `#needs/entities` against views
    // keyed `all` and `exceptions` hid all of them and returned.
    var scope=app.querySelector('.view[data-view="'+view+'"]');
    if(!scope) return;
    var layers=scope.querySelectorAll('.layer');
    var found=false;
    for(var j=0;j<layers.length;j++){
      if(layers[j].getAttribute('data-layer')===layer){found=true;}
    }
    if(!found){return;}
    var views=app.querySelectorAll('.view');
    for(var i=0;i<views.length;i++){
      var on=views[i].getAttribute('data-view')===view;
      if(on){views[i].removeAttribute('hidden');}else{views[i].setAttribute('hidden','');}
    }
    for(var k=0;k<layers.length;k++){
      var vis=layers[k].getAttribute('data-layer')===layer;
      if(vis){layers[k].removeAttribute('hidden');}else{layers[k].setAttribute('hidden','');}
    }
    var btns=app.querySelectorAll('.rail-btn');
    for(var b=0;b<btns.length;b++){
      btns[b].setAttribute('aria-pressed',
        String(btns[b].getAttribute('data-layer')===layer));
    }
    var tog=app.querySelectorAll('.seg button');
    for(var t=0;t<tog.length;t++){
      tog[t].setAttribute('aria-pressed',
        String(tog[t].getAttribute('data-view')===view));
    }
  }
  function fromHash(){
    var raw=(location.hash||'').replace(/^#/,'');
    if(!raw) return;
    var bits=raw.split('/');
    if(bits.length!==2) return;
    show(bits[0],bits[1]);
  }
  window.addEventListener('hashchange',fromHash);
  app.addEventListener('click',function(e){
    var el=e.target.closest?e.target.closest('.rail-btn,.seg button'):null;
    if(!el) return;
    var scope=app.querySelector('.view:not([hidden])');
    var view=scope?scope.getAttribute('data-view'):'';
    var layerEl=app.querySelector('.rail-btn[aria-pressed="true"]');
    var layer=layerEl?layerEl.getAttribute('data-layer'):'overview';
    if(el.matches('.seg button')){view=el.getAttribute('data-view');}
    if(el.classList.contains('rail-btn')){layer=el.getAttribute('data-layer');}
    if(view){history.replaceState(null,'','#'+view+'/'+layer);}
  },true);
  fromHash();
})();
"""


def _script_with_routing() -> str:
    """The shared behaviour plus this page's URL routing, in ONE script tag.

    Spliced in rather than appended as a second `<script>`: the shared helper
    already carries its own tags, and the page is asserted to hold exactly one
    of them. That assertion exists because wrapping `_script()` a second time
    nested the tags, at which point no JavaScript ran at all and every nav
    button on the page went dead.
    """
    shared = _script()
    closing = "</script>"
    if shared.count(closing) != 1:  # pragma: no cover - shape guard
        raise AssertionError("the shared script is no longer one <script> block")
    return shared.replace(closing, _ROUTING_BODY + closing)


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
    notes = [c for c in (page or {}).get("caveats") or []
             if str(c).strip() and str(c).strip() not in shown]
    caveats = (
        '<section class="caveats"><h3>Worth knowing before reading this</h3><ul>'
        + "".join(f'<li>{_safe(note)}</li>' for note in notes)
        + '</ul></section>') if notes else ""
    subtitle = (f'<p class="sub">{_safe((page or {}).get("subtitle"))}</p>'
                if (page or {}).get("subtitle") else "")
    generated = datetime.now(timezone.utc).date().isoformat()

    # The costing sentence is a CLAIM about the source data, and it is only true
    # where a rulebook says so. Inventory Management's rulebook states it of
    # SKU_STOCK_VALUE, so that page keeps it. The Stock Age report reads a
    # different column whose basis was measured MOVING between two snapshots, so
    # asserting a costing convention there would state something this pipeline
    # cannot see. A page that knows its own basis supplies the sentence.
    basis_line = str((page or {}).get("value_basis_note") or "").strip() or (
        f"All values are {money.CURRENCY} at landing cost, excluding VAT.")

    # The skeleton must match what _style() expects, exactly. `.app` is a flex
    # ROW whose only children are the rail and <main>; everything else lives
    # inside `main > .page`. Getting this wrong renders the header, rail, views
    # and footer as four side-by-side columns, with the title wrapping one word
    # per line - which is precisely what happened the first time.
    html = f"""<!doctype html>
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
<footer><span>{_safe(basis_line)} Every figure is copied or derived arithmetically
from the scanned stock position; no number is estimated.</span><strong>AI-assisted analysis</strong></footer>
</div></main></div>{_script_with_routing()}</body></html>"""
    currency = str((page or {}).get("currency") or "SAR").strip() or "SAR"
    if currency != "SAR":
        html = html.replace("SAR ", f"{currency} ")
        html = html.replace("values are SAR ", f"values are {currency} ")
    return html
