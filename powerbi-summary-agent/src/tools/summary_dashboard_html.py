"""Renderer for the interactive summary dashboard (R6).

One self-contained HTML file: all CSS and the small amount of JS travel inside it,
every chart is inline SVG, and nothing is fetched at open time - so the file still
works emailed, archived or opened offline. No browser storage APIs.

This module renders the page model from ``summary_dashboard`` and computes no
business figures of its own: it formats, positions and colours values that were
already derived and reconciled upstream. Every string that reaches the document
goes through ``_safe``.

**Both time views are rendered into the page** and the toggle switches which one
is visible, rather than the page holding a data model and re-deriving figures in
JavaScript. That keeps one source of truth (Python), keeps every number inside
reach of the deterministic validators, and still gives the reader an instant
whole-document switch.

Charts stay deliberately small - each is a compact support for the written
insight, never a full-frame centrepiece - and each cut gets the chart that fits
it rather than the same bar chart repeated down the page.
"""

from __future__ import annotations

import calendar
import html
import math
from datetime import datetime, timezone
from typing import Any

from . import summary_dashboard

TEAL = "#0f9f95"
TEAL_DARK = "#087f79"
INK = "#12201e"
MUTED = "#5b7182"
FAINT = "#8fa1a9"
GRID = "#dfe7ec"
SOFT = "#f7fafb"
RAIL = "#0e1b19"
POS = "#2f8f4e"
NEG = "#cf4636"
AMBER = "#c08429"

TONE_COLORS = {
    "positive": POS,
    "warning": AMBER,
    "critical": NEG,
    "neutral": FAINT,
}

SEVERITY_LABELS = {"critical": "Critical", "watch": "Watch", "steady": "Steady"}
SEVERITY_TONES = {"critical": "critical", "watch": "warning", "steady": "neutral"}

_ARROW_UP = '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 1l4 6H1z"/></svg>'
_ARROW_DOWN = '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M5 9L1 3h8z"/></svg>'


def _safe(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _arrow(value: Any) -> str:
    number = _num(value)
    return _ARROW_UP if number is None or number >= 0 else _ARROW_DOWN


def _compact(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    magnitude = abs(number)
    if magnitude >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if magnitude >= 1_000:
        return f"{number / 1_000:.0f}K"
    return f"{number:.0f}"


def _tone_of_change(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "neutral"
    return "positive" if number >= 0 else "critical"


# ---------------------------------------------------------------------------
# Compact inline-SVG charts
# ---------------------------------------------------------------------------

def _sparkline(values: list, tone: str = "positive") -> str:
    """A 6-12 point trend inside a KPI card. Empty string when there is no series -
    an absent sparkline is honest; a flat line drawn from one point is not."""
    points = [_num(value) for value in values or []]
    points = [value for value in points if value is not None]
    if len(points) < 3:
        return ""
    width, height, pad = 118, 26, 3
    low, high = min(points), max(points)
    span = (high - low) or 1.0
    step = (width - 2 * pad) / (len(points) - 1)
    coords = [
        (pad + index * step, height - pad - (value - low) / span * (height - 2 * pad))
        for index, value in enumerate(points)
    ]
    path = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    color = TONE_COLORS.get(tone, TEAL)
    last_x, last_y = coords[-1]
    return (
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" '
        f'height="{height}" aria-hidden="true">'
        f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.7" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.1" fill="{color}"/></svg>'
    )


def _waterfall(steps: list[dict], value_label: str = "") -> str:
    """Prior -> lever effects -> current. Bars are drawn from the running total so
    the visual closes on the current bar exactly as the arithmetic does."""
    usable = [step for step in steps or [] if _num(step.get("value")) is not None]
    if len(usable) < 3:
        return ""
    width, height = 420, 200
    pad_l, pad_r, pad_t, pad_b = 8, 8, 20, 48
    count = len(usable)
    gap = 13
    bar_w = (width - pad_l - pad_r - (count - 1) * gap) / count
    running = 0.0
    bars: list[dict] = []
    for step in usable:
        value = _num(step["value"]) or 0.0
        kind = str(step.get("kind") or "")
        if kind == "total":
            bars.append({"base": value, "top": value, "value": value,
                         "kind": kind, "label": step.get("label")})
            running = value
        else:
            start, end = running, running + value
            bars.append({"base": min(start, end), "top": max(start, end), "value": value,
                         "kind": kind, "label": step.get("label")})
            running = end

    # The axis floats just below the lowest running value, and says so on the
    # chart. Lever effects are a few percent of the total, so an axis anchored at
    # zero spends ~95% of its height on the unchanging base and renders the
    # movement as invisible slivers between two near-identical full-height blocks -
    # a chart that encodes the data and communicates nothing. Each bar still starts
    # where its predecessor finished, so the waterfall reading survives; a
    # truncated axis that did not admit it would be the dishonest version.
    lows = [bar["base"] for bar in bars]
    highs = [bar["top"] for bar in bars]
    spread = (max(highs) - min(lows)) or abs(max(highs)) * 0.02 or 1.0
    floor = min(lows) - spread * 0.4
    if min(lows) >= 0 and floor < 0:
        floor = 0.0
    ceiling = max(highs) + spread * 0.22
    plot_h = height - pad_t - pad_b
    scale = plot_h / ((ceiling - floor) or 1.0)

    def y_of(value: float) -> float:
        return pad_t + plot_h - (value - floor) * scale

    parts: list[str] = []
    for index, bar in enumerate(bars):
        x = pad_l + index * (bar_w + gap)
        y = y_of(bar["top"])
        bar_h = max(2.5, (y_of(floor) if bar["kind"] == "total" else y_of(bar["base"])) - y)
        fill = TEAL_DARK if bar["kind"] == "total" else (POS if bar["value"] >= 0 else NEG)
        display = (
            _compact(bar["value"]) if bar["kind"] == "total"
            else ("+" if bar["value"] >= 0 else "-") + _compact(abs(bar["value"]))
        )
        parts.append(
            f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{y:.1f}" '
            f'width="{bar_w:.1f}" height="{bar_h:.1f}" rx="2" fill="{fill}" '
            f'data-label="{_safe(bar["label"])}" data-value="{_safe(display)}">'
            f'<title>{_safe(bar["label"])}: {_safe(display)}</title></rect>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'class="dz" style="fill:{fill};font-weight:700">{_safe(display)}</text>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{height - pad_b + 15:.1f}" '
            f'text-anchor="middle" class="dz">{_safe(bar["label"])}</text>'
        )
        if index < len(bars) - 1:
            # Connector sits at the running value the next bar starts from.
            link = y_of(bars[index + 1]["base"] if bars[index + 1]["value"] >= 0
                        else bars[index + 1]["top"])
            parts.append(
                f'<line x1="{x + bar_w:.1f}" y1="{link:.1f}" x2="{x + bar_w + gap:.1f}" '
                f'y2="{link:.1f}" stroke="{GRID}" stroke-width="1" stroke-dasharray="2 2"/>'
            )
    parts.append(
        f'<line x1="{pad_l}" y1="{y_of(floor):.1f}" x2="{width - pad_r}" '
        f'y2="{y_of(floor):.1f}" stroke="{GRID}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{width - pad_r}" y="{height - 7}" text-anchor="end" class="dz">'
        f'axis starts at {_safe(_compact(floor))}, not zero</text>'
    )
    label = (
        f'<text x="{pad_l}" y="12" class="dz">{_safe(value_label)}</text>'
        if value_label else ""
    )
    return (
        f'<div class="chart-stage"><svg viewBox="0 0 {width} {height}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img">{label}{"".join(parts)}</svg>'
        '<span class="chart-tooltip" role="status"></span></div>'
    )


def _dual_line(spec: dict | None) -> str:
    """This year against last year. The one chart that makes a comparator effect
    visible: a dip this year sitting under a spike in the same period last year."""
    if not spec:
        return ""
    labels = list(spec.get("labels") or [])
    series = list(spec.get("series") or [])
    if len(labels) < 2 or len(series) < 2:
        return ""
    values = [
        _num(value)
        for entry in series for value in entry.get("values") or []
    ]
    values = [value for value in values if value is not None]
    if not values:
        return ""
    width, height = 420, 175
    pad_l, pad_r, pad_t, pad_b = 10, 12, 22, 30
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    plot_w, plot_h = width - pad_l - pad_r, height - pad_t - pad_b

    def px(index: int) -> float:
        return pad_l + index * plot_w / max(1, len(labels) - 1)

    def py(value: float) -> float:
        return pad_t + plot_h - (value - low) / span * plot_h

    parts: list[str] = []
    legend: list[str] = []
    for entry in series:
        points = [_num(value) for value in entry.get("values") or []]
        if any(value is None for value in points) or len(points) != len(labels):
            continue
        reference = str(entry.get("style")) == "reference"
        color = GRID if reference else TEAL
        stroke = "1.8" if reference else "2.2"
        dash = ' stroke-dasharray="3 2"' if reference else ""
        path = " ".join(
            ("M" if index == 0 else "L") + f"{px(index):.1f} {py(value):.1f}"
            for index, value in enumerate(points)
        )
        parts.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="{stroke}"'
            f'{dash} stroke-linejoin="round"/>'
        )
        if not reference:
            for index, value in enumerate(points):
                parts.append(
                    f'<circle class="data-point" tabindex="0" cx="{px(index):.1f}" '
                    f'cy="{py(value):.1f}" r="3" fill="{color}" '
                    f'data-label="{_safe(labels[index])}" '
                    f'data-value="{_safe(_compact(value))}">'
                    f'<title>{_safe(labels[index])}: {_safe(_compact(value))}</title>'
                    '</circle>'
                )
        legend.append(
            f'<span><i style="background:{color}"></i>{_safe(entry.get("name"))}</span>'
        )
    if not parts:
        return ""
    every = max(1, math.ceil(len(labels) / 7))
    for index, label in enumerate(labels):
        if index % every and index != len(labels) - 1:
            continue
        short = str(label)[:3]
        parts.append(
            f'<text x="{px(index):.1f}" y="{height - 9:.1f}" text-anchor="middle" '
            f'class="dz">{_safe(short)}</text>'
        )
    return (
        f'<div class="series-legend">{"".join(legend)}</div>'
        f'<div class="chart-stage"><svg viewBox="0 0 {width} {height}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet" role="img">{"".join(parts)}</svg>'
        '<span class="chart-tooltip" role="status"></span></div>'
    )


def _donut(segments: list[dict], center_top: str = "", center_bottom: str = "") -> str:
    """Mix / share of a whole. Only for a complete, non-negative composition."""
    usable = [
        segment for segment in segments or []
        if (_num(segment.get("value")) or 0.0) > 0
    ]
    if len(usable) < 2:
        return ""
    total = sum(_num(segment["value"]) or 0.0 for segment in usable)
    if not total:
        return ""
    size, radius, stroke = 132, 52, 15
    center = size / 2
    circumference = 2 * math.pi * radius
    offset = 0.0
    arcs: list[str] = []
    for segment in usable:
        length = (_num(segment["value"]) or 0.0) / total * circumference
        arcs.append(
            f'<circle cx="{center}" cy="{center}" r="{radius}" fill="none" '
            f'stroke="{segment.get("color") or TEAL}" stroke-width="{stroke}" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {center} {center})"><title>'
            f'{_safe(segment.get("label"))}</title></circle>'
        )
        offset += length
    middle = (
        f'<text x="{center}" y="{center - 1}" text-anchor="middle" class="donut-total">'
        f'{_safe(center_top)}</text>'
        f'<text x="{center}" y="{center + 13}" text-anchor="middle" class="dz">'
        f'{_safe(center_bottom)}</text>'
    )
    return (
        f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" role="img">'
        f'{"".join(arcs)}{middle}</svg>'
    )


def _diverging_row(label: str, sub: str, value: Any, display: str,
                   max_abs: float, tone: str) -> str:
    """One diverging bar around a shared zero line - the contribution primitive.

    CSS rather than SVG so the rows reflow on a phone and stay crisp when printed.
    """
    number = _num(value) or 0.0
    width = min(48.0, abs(number) / max_abs * 48.0) if max_abs else 0.0
    side = f"left:50%;width:{width:.2f}%" if number >= 0 else f"right:50%;width:{width:.2f}%"
    color = TONE_COLORS.get(tone, FAINT)
    sub_html = f"<small>{_safe(sub)}</small>" if sub else ""
    return (
        '<div class="bar-row">'
        f'<div class="bl">{_safe(label)}{sub_html}</div>'
        '<div class="btrack"><span class="zc"></span>'
        f'<span class="bfill" style="{side};background:{color}"></span></div>'
        f'<div class="bv" style="color:{color}">{_safe(display)}</div>'
        '</div>'
    )


def _lever_mini(levers: dict | None) -> str:
    """A single entity's three levers at a glance, on a shared scale."""
    if not levers:
        return ""
    rows = [
        ("Transactions", levers.get("transactions")),
        ("Basket Size", levers.get("basket_size")),
        ("Price", levers.get("price")),
    ]
    values = [abs(_num(value) or 0.0) for _label, value in rows]
    max_abs = max(values + [3.0])
    parts = []
    for label, value in rows:
        number = _num(value)
        if number is None:
            continue
        parts.append(_diverging_row(
            label, "", number, f"{number:+.2f}%", max_abs, _tone_of_change(number)))
    return f'<div class="lmini">{"".join(parts)}</div>' if parts else ""


# ---------------------------------------------------------------------------
# Page blocks
# ---------------------------------------------------------------------------

def _badge(display: str, tone: str, change: Any = None) -> str:
    color = TONE_COLORS.get(tone, FAINT)
    arrow = _arrow(change) if change is not None else ""
    return (
        f'<span class="badge" style="color:{color};background:{color}14">'
        f'{arrow}{_safe(display)}</span>'
    )


def _rag_strip(rag: dict | None) -> str:
    if not rag or not rag.get("label"):
        return ""
    color = TONE_COLORS.get(str(rag.get("tone")), FAINT)
    return (
        f'<span class="rag"><i style="background:{color}"></i>'
        f'<span style="color:{color}">{_safe(rag.get("label"))}</span></span>'
    )


def _kpi_cards(cards: list[dict]) -> str:
    if not cards:
        return ""
    items = []
    for card in cards:
        rag = card.get("rag") or {}
        caution = rag.get("caution")
        flagged = " flagged" if str(rag.get("tone")) == "critical" else ""
        suffix = (
            f'<span class="valx">{_safe(card.get("unit_suffix"))}</span>'
            if card.get("unit_suffix") else ""
        )
        spark = _sparkline(card.get("sparkline") or [], str(rag.get("tone") or "positive"))
        read_with = rag.get("read_with")
        note = str(card.get("note") or "")
        if read_with:
            note = note or f"Read together with {read_with.replace('_', ' ')}."
        items.append(
            f'<article class="card kpi{flagged}">'
            f'<div class="lab">{_safe(card.get("label"))}</div>'
            f'<div class="val">{_safe(card.get("value_display"))}{suffix}</div>'
            '<div class="foot">'
            f'{_badge(str(card.get("change_display")), str(rag.get("tone") or "neutral"), card.get("change_pct"))}'
            f'{_rag_strip(rag)}</div>'
            + (f'<div class="spark-wrap">{spark}</div>' if spark else "")
            + f'<p class="note">{_safe(note)}</p>'
            + (f'<p class="note caution">{_safe(caution)}</p>' if caution else "")
            + '</article>'
        )
    return f'<div class="grid kpis">{"".join(items)}</div>'


def _signal_cards(signals: list[dict]) -> str:
    if not signals:
        return ""
    items = []
    for signal in signals:
        tone = str(signal.get("tone") or "neutral")
        items.append(
            '<article class="card kpi">'
            f'<div class="lab">{_safe(signal.get("label"))}</div>'
            f'<div class="val small">{_safe(signal.get("value"))}</div>'
            f'<div class="foot">{_badge(str(signal.get("badge") or ""), tone)}</div>'
            f'<p class="note">{_safe(signal.get("note"))}</p>'
            '</article>'
        )
    return f'<div class="grid signals">{"".join(items)}</div>'


def _hero(hero: dict, period: dict) -> str:
    levers = "".join(
        '<div class="lever-chip">'
        f'<span class="ln">{_safe(lever.get("label"))}</span>'
        f'<span class="lv" style="color:{TONE_COLORS.get(_tone_of_change(lever.get("change_pct")), FAINT)}">'
        f'{_arrow(lever.get("change_pct"))}{_safe(lever.get("display"))}</span>'
        f'<span class="le">{_safe(lever.get("effect_display"))}</span>'
        '</div>'
        for lever in hero.get("levers") or []
    )
    chart = _waterfall(hero.get("waterfall") or [], "Revenue effect by lever")
    caption = (
        "The levers pull against each other; the three effects sum exactly to the "
        "revenue move."
    )
    if not chart:
        chart = _dual_line(hero.get("dual_trend"))
        caption = "This year against the same periods last year."
    visual = (
        '<div class="hero-viz">'
        f'<div class="viz-cap">{"How revenue moved" if hero.get("waterfall") else "This year vs last year"}'
        f'<span class="tag">{_safe(period.get("comparison") or "")}</span></div>'
        f'{chart}<p class="viz-note">{_safe(caption)}</p></div>'
    ) if chart else ""
    tag = (
        f'<span class="verdict-tag">{_safe(hero.get("verdict_tag"))}</span>'
        if hero.get("verdict_tag") else ""
    )
    state = (
        f'<p class="hero-state">Lever state: <b>{_safe(hero.get("state"))}</b></p>'
        if hero.get("state") else ""
    )
    return (
        '<div class="hero"><div class="hero-read">'
        f'{tag}<h3>{_safe(hero.get("headline"))}</h3>'
        f'<p>{_safe(hero.get("narrative"))}</p>'
        f'<div class="levers">{levers}</div>{state}'
        f'</div>{visual}</div>'
    )


def _contribution_block(contributions: dict | None, entity_role: str | None) -> str:
    if not contributions or not contributions.get("items"):
        return ""
    items = contributions["items"]
    max_abs = max(
        [abs(_num(item.get("contribution_pts")) or 0.0) for item in items] + [0.01]
    )
    rows = "".join(
        _diverging_row(
            str(item.get("member")),
            f"{_num(item.get('change_pct')):+.2f}% own revenue"
            if _num(item.get("change_pct")) is not None else "",
            item.get("contribution_pts"),
            f"{_num(item.get('contribution_pts')):+.2f}"
            if _num(item.get("contribution_pts")) is not None else "n/a",
            max_abs,
            _tone_of_change(item.get("contribution_pts")),
        )
        for item in items
    )
    ranked = sorted(items, key=lambda row: -(_num(row.get("current")) or 0.0))
    palette = [TEAL, "#5b7b78", AMBER, NEG, TEAL_DARK, MUTED]
    shown, rest = ranked[:6], ranked[6:]
    segments = [
        {"label": item.get("member"), "value": item.get("current"),
         "color": palette[index % len(palette)]}
        for index, item in enumerate(shown)
    ]
    # The remainder is a real segment, not a rounding gap. Without it the ring
    # shows the proportions of six areas while the centre states the total of all
    # of them - two different denominators in one chart.
    remainder = sum(_num(item.get("current")) or 0.0 for item in rest)
    if remainder > 0:
        segments.append({
            "label": f"Other ({len(rest)} more)", "value": remainder, "color": GRID,
        })
    total_current = sum(_num(item.get("current")) or 0.0 for item in items)
    donut = _donut(segments, _compact(total_current), "current revenue")
    legend = "".join(
        f'<li><i style="background:{segment["color"]}"></i>'
        f'<span>{_safe(segment["label"])}</span>'
        f'<strong>{_safe(_compact(segment["value"]))}</strong></li>'
        for segment in segments
    )
    share_card = (
        '<div class="card pad-lg">'
        f'<div class="viz-cap">Share of revenue by {_safe(entity_role or "area")}</div>'
        f'<div class="donut-layout">{donut}<ul class="chart-legend">{legend}</ul></div>'
        '</div>'
    ) if donut else ""
    note = (
        f'<p class="viz-note">{_safe(contributions.get("note"))}</p>'
        if contributions.get("note") else ""
    )
    return (
        '<div class="grid g2">'
        '<div class="card pad-lg">'
        '<div class="viz-cap">Contribution to the group revenue move'
        f'<span class="tag">points &middot; sums to {_safe(contributions.get("sums_to"))}</span></div>'
        f'<div class="bar-list">{rows}</div>{note}'
        '<p class="viz-note">Each area\'s own change measured against the group\'s prior '
        'revenue, so the points add up to the group percentage.</p>'
        '</div>'
        f'{share_card}</div>'
    )


def _entity_cards(cards: list[dict]) -> str:
    if not cards:
        return ""
    blocks = []
    for card in cards:
        severity = str(card.get("severity") or "steady")
        tone = SEVERITY_TONES.get(severity, "neutral")
        color = TONE_COLORS.get(tone, FAINT)
        state = (
            f'<span class="state-pill" style="color:{color};background:{color}14">'
            f'{_safe(card.get("state") or SEVERITY_LABELS.get(severity, "Steady"))}</span>'
        )
        contribution = (
            f'<p class="contrib-line">Contributed '
            f'<b>{_safe(card.get("contribution_display"))}</b> to the group move.</p>'
            if card.get("contribution_display") else ""
        )
        not_comparable = (
            '<p class="note caution">No prior-period trade, so this area is shown for '
            'completeness and never counted as growth.</p>'
            if not card.get("comparable") else ""
        )
        blocks.append(
            '<article class="card pad-lg entity">'
            '<div class="etop"><div>'
            f'<div class="ename">{_safe(card.get("member"))}</div>{state}</div>'
            '<div class="eright">'
            f'<div class="erev">{_safe(card.get("current_display"))}</div>'
            f'{_badge(str(card.get("change_display")), _tone_of_change(card.get("change_pct")), card.get("change_pct"))}'
            '</div></div>'
            f'<p class="body">{_safe(card.get("story"))}</p>'
            f'{_lever_mini(card.get("levers"))}{contribution}{not_comparable}'
            '</article>'
        )
    return f'<div class="grid g2">{"".join(blocks)}</div>'


def _fact_list(facts: list[dict], limit: int = 6) -> str:
    items = [
        f'<li>{_safe(fact.get("statement") or fact.get("metric"))}</li>'
        for fact in (facts or [])[:limit]
        if fact.get("statement") or fact.get("metric")
    ]
    return f'<ul class="facts">{"".join(items)}</ul>' if items else ""


#: Query-construction helper columns. They do not start with "__" the way the
#: deep-dive diagnostics do, so they need naming explicitly - otherwise an
#: internal sort key reaches a manager-facing table as a duplicate value column.
_HELPER_COLUMNS = {"abs_sort", "abs", "sort", "rank_helper"}


def _rows_table(rows: list[dict], caption: str, limit: int = 8,
                grain: Any = None) -> str:
    """Compact numeric detail where a chart would add nothing.

    Month-of-year codes are converted to month names, matching every other
    manager-facing surface: a column of bare 1..12 reads as a data artefact.
    """
    if not rows:
        return ""
    keys: list[str] = []
    for row in rows[:limit]:
        for key in row:
            name = str(key)
            if name.startswith("__") or name.casefold() in _HELPER_COLUMNS or key in keys:
                continue
            keys.append(key)
    keys = keys[:5]
    if not keys:
        return ""
    head = "".join(f"<th>{_safe(str(key).replace('_', ' ').title())}</th>" for key in keys)
    body = []
    for row in rows[:limit]:
        cells = []
        for key in keys:
            value = row.get(key)
            number = _num(value)
            is_period = "month" in str(key).casefold() or "month" in str(grain or "").casefold()
            if number is not None and is_period and float(number).is_integer() \
                    and 1 <= int(number) <= 12:
                cells.append(f"<td>{_safe(calendar.month_name[int(number)])}</td>")
            elif number is not None:
                cells.append(f'<td class="n">{_safe(_compact(number))}</td>')
            else:
                cells.append(f"<td>{_safe(value)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return (
        f'<div class="viz-cap">{_safe(caption)}</div>'
        f'<div class="table-wrap"><table class="tbl"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def _areas_block(areas: dict) -> str:
    entries = areas.get("entries") or []
    if not entries:
        return (
            '<p class="note-band">No area was selected for a deep dive in this run. '
            'Every area is still ranked in full coverage below.</p>'
        )
    blocks = []
    for index, entry in enumerate(entries):
        duplicate = (
            '<p class="note caution">This deep dive repeats a recently delivered '
            'story for the same area.</p>'
            if entry.get("signature_duplicate") else ""
        )
        connect = (
            f'<p class="body">{_safe(entry.get("connect"))}</p>'
            if entry.get("connect") else ""
        )
        trend = entry.get("trend") or {}
        detail = _rows_table(
            entry.get("contributors") or [], "Contributors inside this area")
        # "Comparable" is internal vocabulary and is banned from every
        # manager-facing string; the population is described in plain words.
        location = _rows_table(
            entry.get("location") or [], "Stores included in the comparison")
        trend_table = _rows_table(list(trend.get("rows") or []), "Period trend", 12,
                                  grain=trend.get("grain"))
        # The collapsed summary already names the area, so an identical <h4> is
        # noise. It only appears when authoring gave it a real headline.
        headline = str(entry.get("headline") or "").strip()
        heading = (
            f'<h4>{_safe(headline)}</h4>'
            if headline and headline.casefold() != str(entry.get("segment") or "").strip().casefold()
            else ""
        )
        blocks.append(
            f'<details class="collapsible"{" open" if index == 0 else ""}>'
            '<summary><span class="chev" aria-hidden="true"></span>'
            f'<span class="ct">{_safe(entry.get("segment"))}</span>'
            f'<span class="cmeta">{_safe(str(entry.get("role") or "").title())}'
            f'{" &middot; " + _safe(str(entry.get("lens"))) if entry.get("lens") else ""}'
            '</span></summary>'
            '<div class="coll-body">'
            f'{heading}{connect}{duplicate}'
            f'{_fact_list(entry.get("facts") or [])}'
            f'{detail}{location}{trend_table}</div></details>'
        )
    return (
        f'<p class="note-band">{_safe(areas.get("rotates_note"))}</p>'
        + "".join(blocks)
    )


def _movers_block(detail: dict) -> str:
    def side(rows: list[dict], title: str, tone: str) -> str:
        if not rows:
            return (
                f'<div class="card pad-lg"><div class="viz-cap">{_safe(title)}</div>'
                '<p class="viz-note">Nothing material to report on this side.</p></div>'
            )
        max_abs = max(
            [abs(_num(row.get("change_pct")) or 0.0) for row in rows] + [0.01]
        )
        bars = "".join(
            _diverging_row(
                str(row.get("member")),
                " / ".join(part for part in [str(row.get("parent") or ""),
                                             f"share {row.get('share_shift_display')}"
                                             if row.get("share_shift_display") else ""]
                           if part),
                row.get("change_pct"),
                f"{_num(row.get('change_pct')):+.2f}%"
                if _num(row.get("change_pct")) is not None else "n/a",
                max_abs,
                tone,
            )
            for row in rows
        )
        return (
            '<div class="card pad-lg">'
            f'<div class="viz-cap">{_safe(title)}'
            '<span class="tag">share shift in points</span></div>'
            f'<div class="bar-list">{bars}</div></div>'
        )

    dropped = (
        '<p class="note-band">No detail rows sat under the areas in today\'s spotlight, '
        'so the whole level is shown instead.</p>'
        if detail.get("spotlight_filter_dropped") else ""
    )
    return (
        dropped
        + '<div class="grid g2">'
        + side(detail.get("growth") or [], "Top growth", "positive")
        + side(detail.get("decline") or [], "Top de-growth", "critical")
        + '</div>'
    )


def _coverage_block(coverage: dict | None, display_rows: int) -> str:
    """Full ranked coverage of every level - complete by definition, compact by display."""
    levels = (coverage or {}).get("levels") or []
    if not levels:
        return ""
    blocks = []
    for level in levels:
        role = str(level.get("role") or "level")
        rows = list(level.get("rows") or [])
        counts = level.get("counts") or {}
        visible, hidden = rows[:display_rows], rows[display_rows:]

        def row_html(row: dict) -> str:
            severity = str(row.get("severity") or "steady")
            tone = SEVERITY_TONES.get(severity, "neutral")
            color = TONE_COLORS.get(tone, FAINT)
            change = _num(row.get("change_pct"))
            path = _ancestor_path((row.get("hierarchy_path") or [])[:-1])
            comparable = bool(row.get("comparable"))
            change_cell = (
                f'<td class="n" style="color:{TONE_COLORS.get(_tone_of_change(change), FAINT)}">'
                f'{change:+.2f}%</td>' if change is not None
                else '<td class="n muted">no prior year</td>'
            )
            return (
                f'<tr data-search="{_safe(summary_dashboard.member_name(row.get("member")) + " " + role)}">'
                f'<td class="rank-cell">{_safe(row.get("rank"))}</td>'
                f'<th scope="row">{_safe(summary_dashboard.member_name(row.get("member")))}'
                + (f'<span class="row-path">{_safe(path)}</span>' if path else "")
                + '</th>'
                f'<td class="n">{_safe(_compact(row.get("current")))}</td>'
                f'{change_cell}'
                f'<td class="n">{_safe(_compact(row.get("change")))}</td>'
                f'<td><span class="badge" style="color:{color};background:{color}14">'
                f'{_safe(SEVERITY_LABELS.get(severity, "Steady") if comparable else "No prior year")}'
                '</span></td></tr>'
            )

        more = (
            f'<details class="coverage-more"><summary>Show the remaining '
            f'{len(hidden)}</summary><div class="table-wrap"><table class="tbl">'
            f'<tbody>{"".join(row_html(row) for row in hidden)}</tbody></table></div>'
            '</details>'
            if hidden else ""
        )
        blocks.append(
            f'<details class="collapsible coverage-level" id="coverage-{_safe(role)}">'
            '<summary><span class="chev" aria-hidden="true"></span>'
            f'<span class="ct">{_safe(role.title())}</span>'
            f'<span class="cmeta">{_safe(counts.get("total"))} members &middot; '
            f'{_safe(counts.get("up"))} up &middot; {_safe(counts.get("down"))} down'
            f'{" &middot; " + _safe(counts.get("current_only")) + " no prior year" if counts.get("current_only") else ""}'
            '</span></summary>'
            '<div class="coll-body"><div class="table-wrap"><table class="tbl">'
            '<thead><tr><th>#</th><th>Member</th><th class="n">Current</th>'
            '<th class="n">Change</th><th class="n">Impact</th><th>Band</th></tr></thead>'
            f'<tbody>{"".join(row_html(row) for row in visible)}</tbody></table></div>'
            f'{more}</div></details>'
        )
    mirrored = (coverage or {}).get("mirrored_roles") or {}
    mirror_note = (
        '<p class="note-band">Not shown separately: '
        + _safe(", ".join(f"{role} (identical to {parent})"
                          for role, parent in mirrored.items()))
        + ' - the same members with the same values, so each is reported once.</p>'
        if mirrored else ""
    )
    return (
        '<h3 class="block-title">Full coverage by level</h3>'
        '<p class="viz-note">Every member of every scanned level, ranked by how much '
        'its movement matters to the business.</p>'
        f'{mirror_note}{"".join(blocks)}'
    )


def _tldr(items: list[dict], view_key: str) -> str:
    if not items:
        return ""
    entries = "".join(
        '<li><button class="tldr-item" type="button" '
        f'data-goto="{_safe(item.get("layer"))}" data-view="{_safe(view_key)}">'
        f'<span class="tldr-rank" style="background:{TONE_COLORS.get(str(item.get("tone")), FAINT)}">'
        f'{_safe(item.get("rank"))}</span>'
        f'<span class="tldr-txt">{_safe(item.get("text"))}'
        f'<span class="to">To {_safe(item.get("to"))}</span></span></button></li>'
        for item in items
    )
    return (
        '<section class="tldr" aria-label="Executive summary">'
        '<div class="tldr-h"><span class="k">Executive summary</span>'
        '<span class="verdict">The most important readings this period, ranked by '
        'business impact.</span></div>'
        f'<ol class="tldr-list">{entries}</ol></section>'
    )


def _layer(view_key: str, layer: str, title: str, hint: str, body: str,
           active: bool) -> str:
    if not body:
        return ""
    return (
        f'<section class="layer" data-layer="{_safe(layer)}" id="{_safe(view_key)}-{_safe(layer)}"'
        f'{"" if active else " hidden"}>'
        '<div class="section-label"><h2>' + _safe(title) + '</h2>'
        + (f'<span class="hint">{_safe(hint)}</span>' if hint else "")
        + f'</div>{body}</section>'
    )


def _ancestor_path(path: list) -> str:
    """Ancestor trail for a member, with consecutive repeats collapsed.

    A mirrored level (a Department column whose members are exactly the Divisions)
    puts the same name in two consecutive positions, and rendering it verbatim
    gives "FARM FRESH / FARM FRESH" - which reads as a bug rather than as the
    duplicate hierarchy it actually is. The mirror itself is already disclosed
    once, as a caveat.
    """
    trail: list[str] = []
    for part in path or []:
        text = str(part).strip()
        if text and (not trail or trail[-1].casefold() != text.casefold()):
            trail.append(text)
    return " / ".join(trail)


def _view_html(view: dict, coverage: dict | None, display_rows: int,
               active: bool) -> str:
    key = str(view.get("key") or "view")
    period = view.get("period") or {}
    layers = view.get("layers") or {}
    entities = layers.get("entities") or {}
    owns = bool(view.get("owns_breakdowns", True))
    # One pointer sentence, used in place of a breakdown this view does not own.
    # It replaces the layer's content rather than prefacing a duplicate of the
    # other view's rows.
    pointer = (
        f'<p class="note-band">{_safe(entities.get("pointer"))}</p>'
        if entities.get("pointer") else ""
    )
    cards = view.get("kpis") or []
    # Only explain the tougher band when a measure on it is actually shown.
    tough_note = (
        '<p class="viz-note">Units and Basket Size are held to the tougher band, so '
        'standing still on real demand is already a warning.</p>'
        if any(str((card.get("rag") or {}).get("band")) == "tough" for card in cards)
        else ""
    )
    overview_body = (
        _hero(view.get("hero") or {}, period)
        + '<h3 class="block-title">Core measures versus the comparison period</h3>'
        + tough_note
        + _kpi_cards(cards)
        + (
            '<h3 class="block-title">Signals a headline hides</h3>'
            + _signal_cards(view.get("signals") or [])
            if view.get("signals") else ""
        )
    )
    if not owns:
        entities_body = pointer
    elif entities.get("available"):
        entities_body = (
            _contribution_block(entities.get("contributions"), entities.get("role"))
            + _entity_cards(entities.get("cards") or [])
        )
    else:
        entities_body = (
            '<p class="note-band">No breakdown with a prior period to compare was '
            'available for the entity level in this run.</p>'
        )
    areas_body = pointer if not owns else _areas_block(layers.get("areas") or {})
    detail_body = pointer if not owns else (
        _movers_block(layers.get("detail") or {})
        + _coverage_block(coverage, display_rows)
    )
    # Limitations are stated once, here, at the top of the view they belong to.
    # The page-level footer lists only caveats that are NOT already shown by a
    # view, so the same sentence never appears twice in one document.
    limitations = "".join(
        f'<p class="note-band">{_safe(limitation)}</p>'
        for limitation in view.get("limitations") or []
    )
    # A real middle dot, not "&middot;": this string is escaped by _safe below, so
    # an HTML entity here would reach the reader as literal "&middot;" text.
    context = " · ".join(
        part for part in [
            f'Data through {period.get("data_as_of")}' if period.get("data_as_of") else "",
            f'{str(period.get("grain") or "").title()} grain' if period.get("grain") else "",
            str(period.get("freshness_status") or "").replace("_", " ").title()
            if period.get("freshness_status") else "",
        ] if part
    )
    return (
        f'<section class="view" data-view="{_safe(key)}"{"" if active else " hidden"}>'
        f'<p class="view-context">{_safe(context)}</p>{limitations}'
        + _tldr(view.get("tldr") or [], key)
        + _layer(key, "overview", "The headline read",
                 "a result read two ways, explained three ways", overview_body, True)
        + _layer(key, "entities", f'Which {str(entities.get("role") or "area")}s moved the group',
                 "contributions sum to the group move" if owns else
                 f'scanned across {view.get("breakdown_owner") or "the full period"}',
                 entities_body, False)
        + _layer(key, "areas", "Areas under the lens today",
                 "a rotating deep-dive subset" if owns else
                 f'scanned across {view.get("breakdown_owner") or "the full period"}',
                 areas_body, False)
        + _layer(key, "detail", "Movers and full coverage",
                 "ranked, with share shift" if owns else
                 f'scanned across {view.get("breakdown_owner") or "the full period"}',
                 detail_body, False)
        + '</section>'
    )


def _style() -> str:
    return f"""
:root{{color-scheme:light}}*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#eef1f0;color:{INK};font-family:'Segoe UI',Inter,Roboto,Arial,sans-serif;font-size:13.5px;line-height:1.55;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}}
.app{{display:flex;min-height:100vh}}
.rail{{width:74px;flex:0 0 auto;background:{RAIL};display:flex;flex-direction:column;align-items:center;padding:18px 0;position:sticky;top:0;height:100vh}}
.rail-mark{{width:40px;height:40px;border-radius:11px;border:1.5px solid {TEAL};color:{TEAL};display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;margin-bottom:22px}}
.rail-nav{{display:flex;flex-direction:column;gap:7px;width:100%;align-items:center}}
.rail-btn{{width:58px;padding:9px 2px;border:0;border-radius:11px;background:transparent;color:#8fa3a0;font:inherit;font-size:9.5px;font-weight:650;cursor:pointer;text-align:center;line-height:1.2}}
.rail-btn:hover{{background:rgba(255,255,255,.07);color:#c6d3d0}}
.rail-btn[aria-pressed=true]{{background:{TEAL_DARK};color:#fff}}
main{{flex:1;min-width:0}}
.page{{max-width:1420px;margin:0 auto;padding:22px 28px 56px}}
.hero-head{{display:flex;justify-content:space-between;align-items:flex-end;gap:20px;flex-wrap:wrap;margin-bottom:14px}}
.eyebrow{{color:{TEAL_DARK};font-size:10px;font-weight:750;letter-spacing:.13em;text-transform:uppercase}}
h1{{font-size:clamp(20px,2.2vw,27px);font-weight:780;letter-spacing:-.3px;margin:5px 0 3px}}
.sub{{color:{FAINT};font-size:11.5px}}
.seg{{display:inline-flex;background:#fff;border:1px solid {GRID};border-radius:9px;padding:3px}}
.seg button{{border:0;background:transparent;font:inherit;font-size:12px;font-weight:650;color:{MUTED};padding:6px 13px;border-radius:7px;cursor:pointer}}
.seg button[aria-pressed=true]{{background:#def4f0;color:{TEAL_DARK}}}
.view-context{{color:{FAINT};font-size:11.5px;margin-bottom:12px}}
.tldr{{background:linear-gradient(180deg,#12201e,#0e1b19);color:#eaf1ef;border-radius:13px;padding:15px 17px;margin-bottom:20px;box-shadow:0 8px 26px rgba(16,24,40,.09)}}
.tldr-h{{display:flex;gap:9px;align-items:baseline;flex-wrap:wrap;margin-bottom:10px}}
.tldr-h .k{{color:{TEAL};font-size:9.5px;font-weight:750;letter-spacing:.14em;text-transform:uppercase}}
.tldr-h .verdict{{color:#c7d3d0;font-size:12px}}
.tldr-list{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:8px;list-style:none}}
.tldr-item{{display:flex;gap:10px;align-items:flex-start;width:100%;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:9px 11px;cursor:pointer;text-align:left;font:inherit;color:inherit}}
.tldr-item:hover,.tldr-item:focus{{background:rgba(255,255,255,.1);outline:none}}
.tldr-rank{{width:19px;height:19px;border-radius:5px;flex:0 0 auto;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:700;color:#fff}}
.tldr-txt{{font-size:11.5px;line-height:1.42;color:#d4dedb}}
.tldr-txt .to{{display:block;color:{TEAL};font-size:9.5px;font-weight:700;margin-top:3px}}
.section-label{{display:flex;align-items:baseline;gap:11px;margin:22px 0 11px}}
.section-label h2{{font-size:15px;font-weight:750}}
.section-label .hint{{color:{FAINT};font-size:11px;margin-left:auto}}
.block-title{{font-size:13px;font-weight:750;letter-spacing:.02em;margin:22px 0 4px}}
.grid{{display:grid;gap:12px}}
.g2{{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}}
.kpis{{grid-template-columns:repeat(auto-fit,minmax(178px,1fr));margin-top:9px}}
.signals{{grid-template-columns:repeat(auto-fit,minmax(215px,1fr));margin-top:9px}}
.card{{background:#fff;border:1px solid {GRID};border-radius:13px;padding:14px 15px;box-shadow:0 1px 2px rgba(16,24,40,.05)}}
.card.pad-lg{{padding:16px 18px}}
.kpi{{position:relative;display:flex;flex-direction:column}}
.kpi .lab{{color:{MUTED};font-size:11px;font-weight:650}}
.kpi .val{{font-size:21px;font-weight:800;letter-spacing:-.4px;margin-top:3px}}
.kpi .val.small{{font-size:17px}}
.kpi .valx{{font-size:11px;font-weight:500;color:{FAINT};margin-left:4px}}
.kpi .foot{{display:flex;align-items:center;justify-content:space-between;gap:7px;margin-top:8px;flex-wrap:wrap}}
.kpi .note{{color:{FAINT};font-size:10px;line-height:1.4;margin-top:7px}}
.kpi .note.caution{{color:{NEG};font-weight:650}}
.kpi.flagged{{border-color:#eac3bc}}
.kpi.flagged:before{{content:"";position:absolute;left:0;top:12px;bottom:12px;width:3px;border-radius:3px;background:{NEG}}}
.spark-wrap{{margin-top:9px}}.spark{{display:block;width:100%;height:auto;max-width:118px}}
.badge{{display:inline-flex;align-items:center;gap:3px;font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px}}
.badge svg{{width:9px;height:9px;fill:currentColor}}
.rag{{display:inline-flex;align-items:center;gap:5px;font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}}
.rag i{{width:8px;height:8px;border-radius:50%;flex:0 0 auto}}
.hero{{background:#fff;border:1px solid {GRID};border-radius:13px;padding:17px 19px;display:grid;grid-template-columns:1.1fr 1fr;gap:22px;box-shadow:0 8px 26px rgba(16,24,40,.06)}}
.verdict-tag{{display:inline-block;color:{AMBER};background:#faf1e1;font-size:9.5px;font-weight:750;letter-spacing:.1em;text-transform:uppercase;padding:4px 9px;border-radius:6px;margin-bottom:10px}}
.hero h3{{font-size:18px;font-weight:800;line-height:1.28;letter-spacing:-.3px;margin-bottom:8px}}
.hero p{{color:{MUTED};font-size:12.5px;line-height:1.55}}
.hero-state{{margin-top:9px;font-size:11.5px;color:{FAINT}}}.hero-state b{{color:{INK}}}
.levers{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}
.lever-chip{{display:flex;flex-direction:column;gap:1px;border:1px solid {GRID};border-radius:9px;padding:7px 11px;min-width:96px}}
.lever-chip .ln{{color:{FAINT};font-size:9.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase}}
.lever-chip .lv{{display:flex;align-items:center;gap:3px;font-size:14px;font-weight:750}}
.lever-chip .lv svg{{width:10px;height:10px;fill:currentColor}}
.lever-chip .le{{color:{FAINT};font-size:10px;font-weight:600}}
.hero-viz{{display:flex;flex-direction:column;justify-content:center;min-width:0}}
.viz-cap{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;color:{MUTED};font-size:10.5px;font-weight:700;margin-bottom:8px}}
.viz-cap .tag{{color:{FAINT};background:{SOFT};font-size:8.5px;font-weight:700;padding:2px 6px;border-radius:5px;letter-spacing:.04em}}
.viz-note{{color:{FAINT};font-size:10.5px;line-height:1.45;margin-top:7px}}
.dz{{fill:{FAINT};font-size:8.5px;font-family:inherit}}
svg{{display:block;max-width:100%;height:auto}}
.chart-stage{{position:relative;overflow-x:auto}}
.data-point{{cursor:pointer;outline:none;transition:opacity .15s}}
.data-point:hover,.data-point:focus{{opacity:.75}}
.chart-tooltip{{position:absolute;z-index:3;pointer-events:none;opacity:0;background:{INK};color:#fff;padding:6px 9px;border-radius:6px;font-size:11px;font-weight:650;white-space:nowrap;transition:opacity .12s}}
.chart-tooltip.visible{{opacity:1}}
.series-legend{{display:flex;justify-content:flex-end;gap:13px;color:{MUTED};font-size:11px;margin-bottom:2px}}
.series-legend span{{display:inline-flex;align-items:center;gap:5px}}
.series-legend i{{width:9px;height:9px;border-radius:2px}}
.donut-layout{{display:grid;grid-template-columns:auto minmax(0,1fr);gap:18px;align-items:center}}
.donut-total{{fill:{INK};font-size:16px;font-weight:780}}
.chart-legend{{display:grid;gap:7px;list-style:none}}
.chart-legend li{{display:grid;grid-template-columns:10px minmax(0,1fr) auto;gap:9px;align-items:center;color:{MUTED};font-size:12px}}
.chart-legend i{{width:9px;height:9px;border-radius:50%}}
.chart-legend strong{{color:{INK}}}
.bar-list{{display:flex;flex-direction:column;gap:8px}}
.bar-row{{display:grid;grid-template-columns:minmax(96px,150px) 1fr 62px;align-items:center;gap:10px}}
.bar-row .bl{{font-size:11.5px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar-row .bl small{{display:block;color:{FAINT};font-size:9.5px;font-weight:500}}
.bar-row .bv{{font-size:11.5px;font-weight:750;text-align:right}}
.btrack{{position:relative;height:9px;background:{SOFT};border-radius:5px}}
.btrack .zc{{position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:{GRID}}}
.bfill{{position:absolute;top:0;bottom:0;border-radius:5px}}
.lmini{{display:flex;flex-direction:column;gap:6px;margin-top:10px}}
.lmini .bar-row{{grid-template-columns:78px 1fr 56px}}
.entity .etop{{display:flex;justify-content:space-between;align-items:flex-start;gap:11px;margin-bottom:8px}}
.entity .ename{{font-size:14px;font-weight:750}}
.entity .eright{{text-align:right}}
.entity .erev{{font-size:16px;font-weight:800}}
.state-pill{{display:inline-block;font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px;margin-top:4px}}
.entity .body{{color:{MUTED};font-size:12px;line-height:1.5}}
.contrib-line{{color:{MUTED};font-size:11px;margin-top:9px}}.contrib-line b{{color:{INK}}}
.collapsible{{background:#fff;border:1px solid {GRID};border-radius:13px;margin-bottom:11px;overflow:hidden;scroll-margin-top:70px}}
.collapsible>summary{{display:flex;align-items:baseline;gap:11px;padding:13px 16px;cursor:pointer;list-style:none}}
.collapsible>summary::-webkit-details-marker{{display:none}}
.collapsible>summary:hover{{background:{SOFT}}}
.chev{{width:0;height:0;border-left:5px solid {FAINT};border-top:4px solid transparent;border-bottom:4px solid transparent;flex:0 0 auto;transition:transform .18s}}
.collapsible[open]>summary .chev{{transform:rotate(90deg)}}
.collapsible .ct{{font-size:13.5px;font-weight:750;flex:1}}
.collapsible .cmeta{{color:{MUTED};font-size:11.5px}}
.coll-body{{padding:0 16px 15px}}
.coll-body h4{{font-size:13px;font-weight:750;margin-bottom:5px}}
.facts{{list-style:none;display:grid;gap:6px;margin:9px 0}}
.facts li{{position:relative;padding-left:16px;color:{MUTED};font-size:11.5px;line-height:1.45}}
.facts li:before{{content:"";position:absolute;left:2px;top:.55em;width:6px;height:6px;border-radius:50%;background:{TEAL}}}
.table-wrap{{overflow-x:auto}}
.tbl{{width:100%;border-collapse:collapse;font-size:11.5px}}
.tbl th{{text-align:left;color:{FAINT};font-size:9.5px;font-weight:750;letter-spacing:.05em;text-transform:uppercase;padding:7px 8px;border-bottom:1px solid {GRID}}}
.tbl td,.tbl tbody th{{padding:7px 8px;border-bottom:1px solid {SOFT};text-align:left;font-weight:400}}
.tbl tbody th{{font-weight:700}}
.tbl .n{{text-align:right;font-weight:650}}
.tbl .muted{{color:{FAINT};font-weight:400}}
.tbl .rank-cell{{color:#a4b4c0;width:32px}}
.row-path{{display:block;color:{FAINT};font-size:10px;font-weight:400;margin-top:1px}}
.coverage-more>summary{{cursor:pointer;padding:10px 0 4px;color:{TEAL_DARK};font-size:12px;font-weight:700}}
.note-band{{background:{SOFT};border:1px solid {GRID};border-radius:10px;padding:10px 13px;color:{MUTED};font-size:11.5px;line-height:1.5;margin:11px 0}}
.search-wrap{{margin:14px 0 0}}
.search{{width:100%;max-width:320px;padding:8px 13px;border:1px solid {GRID};border-radius:99px;font:inherit;font-size:12.5px;background:#fff;color:{INK}}}
.search:focus{{outline:none;border-color:{TEAL};box-shadow:0 0 0 3px rgba(15,159,149,.14)}}
footer{{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;margin-top:26px;padding-top:14px;border-top:1px solid {GRID};color:{FAINT};font-size:11px}}
footer strong{{color:{TEAL_DARK}}}
@media(max-width:1000px){{.hero{{grid-template-columns:1fr}}}}
@media(max-width:820px){{
.app{{flex-direction:column}}
.rail{{flex-direction:row;width:100%;height:auto;position:static;padding:9px 12px;gap:8px;justify-content:flex-start;overflow-x:auto}}
.rail-mark{{margin:0 6px 0 0}}.rail-nav{{flex-direction:row;width:auto}}
.page{{padding:16px 15px 44px}}
.bar-row{{grid-template-columns:minmax(84px,1fr) 1fr 56px}}
}}
@media print{{
.rail,.seg,.search-wrap{{display:none}}
.app{{display:block}}.page{{max-width:none;padding:14px}}
.card,.collapsible,.hero,.tldr{{break-inside:avoid;box-shadow:none}}
.tldr{{background:#fff;color:{INK};border:1px solid {GRID}}}
.tldr-txt,.tldr-h .verdict{{color:{MUTED}}}
.layer[hidden],.view[hidden]{{display:block !important}}
.collapsible>.coll-body{{display:block !important}}
}}
"""


def _script() -> str:
    return """<script>
(function(){
  var root=document.getElementById('report');
  if(!root) return;
  function setLayer(layer){
    root.querySelectorAll('.rail-btn').forEach(function(b){
      b.setAttribute('aria-pressed', String(b.dataset.layer===layer));
    });
    root.querySelectorAll('.layer').forEach(function(s){
      s.hidden = s.dataset.layer !== layer;
    });
  }
  function setView(view){
    root.querySelectorAll('.seg button').forEach(function(b){
      b.setAttribute('aria-pressed', String(b.dataset.view===view));
    });
    root.querySelectorAll('.view').forEach(function(s){
      s.hidden = s.dataset.view !== view;
    });
  }
  root.querySelectorAll('.rail-btn').forEach(function(b){
    b.addEventListener('click', function(){ setLayer(b.dataset.layer); });
  });
  root.querySelectorAll('.seg button').forEach(function(b){
    b.addEventListener('click', function(){ setView(b.dataset.view); });
  });
  root.querySelectorAll('.tldr-item').forEach(function(b){
    b.addEventListener('click', function(){
      if(b.dataset.view) setView(b.dataset.view);
      setLayer(b.dataset.goto);
      var target=document.getElementById(b.dataset.view+'-'+b.dataset.goto);
      if(target) target.scrollIntoView({behavior:'smooth', block:'start'});
    });
  });
  root.querySelectorAll('.data-point').forEach(function(point){
    var stage=point.closest('.chart-stage');
    if(!stage) return;
    var tip=stage.querySelector('.chart-tooltip');
    if(!tip) return;
    function show(){
      tip.textContent=point.dataset.label+': '+point.dataset.value;
      tip.classList.add('visible');
      var box=stage.getBoundingClientRect(), spot=point.getBoundingClientRect();
      var left=spot.left-box.left+spot.width/2-tip.offsetWidth/2;
      tip.style.left=Math.max(4, Math.min(box.width-tip.offsetWidth-4, left))+'px';
      tip.style.top=Math.max(2, spot.top-box.top-tip.offsetHeight-6)+'px';
    }
    function hide(){ tip.classList.remove('visible'); }
    point.addEventListener('mouseenter',show);
    point.addEventListener('mouseleave',hide);
    point.addEventListener('focus',show);
    point.addEventListener('blur',hide);
  });
  var search=root.querySelector('.search');
  if(search){
    var rows=Array.prototype.slice.call(root.querySelectorAll('[data-search]'));
    search.addEventListener('input', function(){
      var term=search.value.trim().toLowerCase();
      rows.forEach(function(row){
        row.hidden = term!=='' && row.dataset.search.toLowerCase().indexOf(term)===-1;
      });
      root.querySelectorAll('.coverage-level').forEach(function(level){
        var visible=level.querySelectorAll('tbody [data-search]:not([hidden])').length;
        level.hidden = term!=='' && visible===0;
        if(term!=='' && visible>0) level.open=true;
      });
    });
  }
})();
</script>"""


def render(page: dict, coverage: dict | None = None, display_rows: int = 8,
           eyebrow: str = "AI Insights") -> str:
    """Render the whole dashboard - all views, all layers - as one HTML document."""
    views = list((page or {}).get("views") or [])
    title = str((page or {}).get("title") or "AI Insights Summary")
    if not views:
        reason = str((page or {}).get("reason") or "no evidence with a prior period to compare")
        return (
            f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{_safe(title)}</title><style>{_style()}</style></head><body>'
            f'<main class="page"><h1>{_safe(title)}</h1>'
            f'<p class="note-band">This report could not be produced: {_safe(reason)}.</p>'
            '</main></body></html>'
        )

    default_view = str((page or {}).get("default_view") or views[0].get("key"))
    layer_titles = (page or {}).get("layer_titles") or {}
    layers_present: list[str] = []
    for layer in (page or {}).get("layers") or []:
        if any((view.get("layers") or {}).get(layer) for view in views):
            layers_present.append(str(layer))
    rail = "".join(
        f'<button class="rail-btn" type="button" data-layer="{_safe(layer)}" '
        f'aria-pressed="{"true" if index == 0 else "false"}">'
        f'{_safe(layer_titles.get(layer, layer.title()))}</button>'
        for index, layer in enumerate(layers_present)
    )
    toggle = (
        '<div class="seg" role="group" aria-label="Time view">'
        + "".join(
            f'<button type="button" data-view="{_safe(view.get("key"))}" '
            f'aria-pressed="{"true" if str(view.get("key")) == default_view else "false"}">'
            f'{_safe(view.get("label"))}</button>'
            for view in views
        )
        + '</div>'
    ) if len(views) > 1 else ""
    body = "".join(
        _view_html(view, coverage, display_rows, str(view.get("key")) == default_view)
        for view in views
    )
    # A caveat already printed at the top of the view it belongs to must not be
    # repeated in the page footer. Without this filter the reader saw the same
    # sentence three times - once per view limitation, once per breakdown layer,
    # and once here - which read as a broken page rather than as one caution.
    shown = {
        str(limitation).strip()
        for view in views for limitation in view.get("limitations") or []
    }
    caveats = "".join(
        f'<p class="note-band">{_safe(caveat)}</p>'
        for caveat in (page or {}).get("caveats") or []
        if str(caveat).strip() not in shown
    )
    subtitle = (
        f'<p class="sub">{_safe((page or {}).get("subtitle"))}</p>'
        if (page or {}).get("subtitle") else ""
    )
    generated = datetime.now(timezone.utc).date().isoformat()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)}</title><style>{_style()}</style></head>
<body><div class="app" id="report">
<nav class="rail" aria-label="Report layers"><div class="rail-mark" aria-hidden="true">AI</div>
<div class="rail-nav">{rail}</div></nav>
<main><div class="page">
<header class="hero-head"><div>
<p class="eyebrow">{_safe(eyebrow)}</p><h1>{_safe(title)}</h1>{subtitle}
<p class="sub">Generated {_safe(generated)}</p></div>{toggle}</header>
<div class="search-wrap"><input class="search" type="search" placeholder="Search any member across every level"
aria-label="Search members"></div>
{body}{caveats}
<footer><span>Every figure is copied or derived arithmetically from the validated
report evidence; no number is estimated.</span><strong>AI-assisted analysis</strong></footer>
</div></main></div>{_script()}</body></html>"""
