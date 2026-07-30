"""Render the flexible fresh summary in the fixed white/black/teal theme."""

from __future__ import annotations

import html
import math
from datetime import datetime, timezone


TEAL = "#0f9f95"
TEAL_DARK = "#087f79"
INK = "#1c2a31"
MUTED = "#5b7182"
GRID = "#dfe7ec"
SOFT = "#f7fafb"
TONE_COLORS = {
    "positive": "#0f9f95",
    "critical": "#dc3b42",
    "warning": "#d47b08",
    "info": "#2f67d8",
    "teal": "#0f9f95",
}


def _safe(value) -> str:
    return html.escape(str("" if value is None else value), quote=True)


def _compact(value: float) -> str:
    value = float(value)
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.1f}" if not value.is_integer() else f"{int(value):,}"


def _bar_chart(visual: dict) -> str:
    pairs = [
        (str(label), float(value))
        for label, value in zip(visual.get("labels") or [], visual.get("values") or [])
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ][:8]
    if len(pairs) < 2:
        return ""
    width, height = 760, 330
    left, right, top, bottom = 66, 22, 28, 72
    plot_w, plot_h = width - left - right, height - top - bottom
    minimum, maximum = min(0.0, min(v for _, v in pairs)), max(0.0, max(v for _, v in pairs))
    span = maximum - minimum or 1.0
    zero_y = top + (maximum / span) * plot_h
    gap = plot_w / len(pairs)
    bar_w = max(18.0, gap * 0.58)
    elements = [
        f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" '
        f'stroke="{GRID}" stroke-width="1.5"/>'
    ]
    for index, (label, value) in enumerate(pairs):
        x = left + gap * index + (gap - bar_w) / 2
        y = top + ((maximum - max(value, 0.0)) / span) * plot_h
        bar_h = abs(value) / span * plot_h
        if value < 0:
            y = zero_y
        fill = TEAL if value >= 0 else TONE_COLORS["critical"]
        short = label if len(label) <= 14 else label[:13] + "…"
        value_y = max(16, y - 7) if value >= 0 else min(height - bottom + bar_h + 16, height - 50)
        elements.extend([
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{max(1.5, bar_h):.1f}" rx="4" fill="{fill}"/>',
            f'<text x="{x + bar_w/2:.1f}" y="{value_y:.1f}" text-anchor="middle" '
            f'class="chart-value">{_safe(_compact(value))}</text>',
            f'<text x="{x + bar_w/2:.1f}" y="{height-34}" text-anchor="middle" '
            f'class="chart-label">{_safe(short)}</text>',
        ])
    title = _safe(visual.get("title") or "Supporting chart")
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
        f'<title>{title}</title>{"".join(elements)}</svg>'
    )


def _line_chart(visual: dict) -> str:
    pairs = [
        (str(label), float(value))
        for label, value in zip(visual.get("labels") or [], visual.get("values") or [])
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ][:12]
    if len(pairs) < 2:
        return ""
    width, height = 760, 330
    left, right, top, bottom = 66, 22, 28, 72
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [value for _, value in pairs]
    minimum, maximum = min(values), max(values)
    padding = (maximum - minimum) * 0.08 or max(abs(maximum) * 0.08, 1.0)
    minimum, maximum = minimum - padding, maximum + padding
    span = maximum - minimum
    points = []
    elements = []
    for index, (label, value) in enumerate(pairs):
        x = left + plot_w * index / (len(pairs) - 1)
        y = top + (maximum - value) / span * plot_h
        points.append(f"{x:.1f},{y:.1f}")
        if index in {0, len(pairs) - 1} or len(pairs) <= 6:
            short = label if len(label) <= 14 else label[:13] + "…"
            elements.append(
                f'<text x="{x:.1f}" y="{height-34}" text-anchor="middle" '
                f'class="chart-label">{_safe(short)}</text>'
            )
        elements.extend([
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="white" '
            f'stroke="{TEAL}" stroke-width="3"/>',
            f'<text x="{x:.1f}" y="{max(16, y-11):.1f}" text-anchor="middle" '
            f'class="chart-value">{_safe(_compact(value))}</text>',
        ])
    elements.insert(
        0,
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{TEAL}" '
        'stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>',
    )
    title = _safe(visual.get("title") or "Supporting chart")
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{title}">'
        f'<title>{title}</title>{"".join(elements)}</svg>'
    )


def _metric_band(metrics: list[dict]) -> str:
    items = []
    for metric in metrics[:4]:
        tone = str(metric.get("tone") or "teal").casefold()
        color = TONE_COLORS.get(tone, TEAL)
        items.append(
            '<article class="metric">'
            f'<div class="metric-label"><i style="background:{color}"></i>'
            f'{_safe(metric.get("label"))}</div>'
            f'<div class="metric-value" style="color:{color}">{_safe(metric.get("value"))}</div>'
            '</article>'
        )
    if not items:
        return ""
    return (
        f'<section class="metrics metrics-{len(items)}" aria-label="Key figures">'
        f'{"".join(items)}</section>'
    )


def _section_icon(kind: str) -> str:
    """Return a small dependency-free outline icon for a report section."""
    paths = {
        "working": (
            '<circle cx="12" cy="12" r="9"></circle>'
            '<path d="m7.8 12.2 2.7 2.7 5.9-6.2"></path>'
        ),
        "risk": (
            '<path d="M10.3 4.1 3.2 17a2 2 0 0 0 1.8 2.9h14a2 2 0 0 0 1.8-2.9'
            'L13.7 4.1a2 2 0 0 0-3.4 0Z"></path>'
            '<path d="M12 9v4"></path><path d="M12 17h.01"></path>'
        ),
        "action": (
            '<path d="M9 18h6"></path><path d="M10 22h4"></path>'
            '<path d="M8.2 14.8A7 7 0 1 1 15.8 14.8C14.8 15.5 14.5 16.2 14.5 17h-5'
            'c0-.8-.3-1.5-1.3-2.2Z"></path>'
        ),
        "info": (
            '<circle cx="12" cy="12" r="9"></circle>'
            '<path d="M12 11v5"></path><path d="M12 8h.01"></path>'
        ),
    }
    return (
        f'<svg class="section-icon icon-{kind}" viewBox="0 0 24 24" '
        f'aria-hidden="true">{paths.get(kind, paths["info"])}</svg>'
    )


def _section_presentation(heading: str, tone: str) -> tuple[str, str]:
    lowered = heading.casefold()
    if "risk" in lowered:
        return "risk", TONE_COLORS["critical"]
    if "working" in lowered or tone == "positive":
        return "working", TONE_COLORS["positive"]
    return "info", TONE_COLORS.get(tone, TEAL)


def _section_layout(sections: list[dict]) -> str:
    regular = []
    actions = []
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        target = actions if any(token in heading.casefold() for token in ("action", "next step")) else regular
        target.append(section)

    regular_html = []
    for index, section in enumerate(regular, start=1):
        heading = str(section.get("heading") or "").strip()
        tone = str(section.get("tone") or "teal").casefold()
        icon, color = _section_presentation(heading, tone)
        points = "".join(f"<li>{_safe(point)}</li>" for point in section.get("points") or [])
        regular_html.append(
            f'<section class="summary-section tone-{_safe(tone)}" style="--accent:{color}" '
            f'aria-labelledby="summary-section-{index}">'
            '<div class="section-heading">'
            f'{_section_icon(icon)}<h2 id="summary-section-{index}">{_safe(heading)}</h2>'
            f'</div><ul>{points}</ul></section>'
        )

    actions_html = []
    for action_index, section in enumerate(actions, start=1):
        points = "".join(
            f'<li><span>{number}</span><p>{_safe(point)}</p></li>'
            for number, point in enumerate(section.get("points") or [], start=1)
        )
        actions_html.append(
            f'<section class="actions" aria-labelledby="actions-heading-{action_index}">'
            '<div class="section-heading">'
            f'{_section_icon("action")}<h2 id="actions-heading-{action_index}">'
            f'{_safe(section.get("heading"))}</h2></div><ol>{points}</ol></section>'
        )
    regular_block = f'<div class="section-grid">{"".join(regular_html)}</div>' if regular_html else ""
    return regular_block + "".join(actions_html)


def _pairs(visual: dict, limit: int = 15) -> list[tuple[str, float]]:
    return [
        (str(label), float(value))
        for label, value in zip(visual.get("labels") or [], visual.get("values") or [])
        if label not in (None, "")
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ][:limit]


def _interactive_bar(visual: dict) -> str:
    pairs = _pairs(visual)
    if len(pairs) < 2:
        return ""
    width, height = 900, 390
    left, right, top, bottom = 72, 24, 34, 92
    plot_w, plot_h = width - left - right, height - top - bottom
    minimum = min(0.0, min(value for _, value in pairs))
    maximum = max(0.0, max(value for _, value in pairs))
    span = maximum - minimum or 1.0
    zero_y = top + maximum / span * plot_h
    gap = plot_w / len(pairs)
    bar_w = max(15.0, gap * 0.62)
    highlight = visual.get("highlight")
    elements = [
        f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" '
        f'stroke="{GRID}" stroke-width="1.5"/>'
    ]
    for index, (label, value) in enumerate(pairs):
        x = left + gap * index + (gap - bar_w) / 2
        y = top + (maximum - max(value, 0.0)) / span * plot_h
        bar_h = max(2.0, abs(value) / span * plot_h)
        if value < 0:
            y = zero_y
        fill = TEAL_DARK if index == highlight else TEAL if value >= 0 else TONE_COLORS["critical"]
        short = label if len(label) <= 16 else label[:15] + "…"
        display = _compact(value)
        elements.extend([
            f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{y:.1f}" '
            f'width="{bar_w:.1f}" height="{bar_h:.1f}" rx="5" fill="{fill}" '
            f'data-label="{_safe(label)}" data-value="{_safe(display)}">'
            f'<title>{_safe(label)}: {_safe(display)}</title></rect>',
            f'<text x="{x + bar_w/2:.1f}" y="{height-47}" text-anchor="middle" '
            f'class="chart-label">{_safe(short)}</text>',
        ])
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_horizontal_bar(visual: dict) -> str:
    pairs = _pairs(visual, 12)
    if len(pairs) < 2:
        return ""
    width = 900
    row_h = 42
    height = 54 + row_h * len(pairs)
    left, right, top = 190, 72, 24
    plot_w = width - left - right
    minimum = min(0.0, min(value for _, value in pairs))
    maximum = max(0.0, max(value for _, value in pairs))
    span = maximum - minimum or 1.0
    zero_x = left + (-minimum / span) * plot_w
    elements = [
        f'<line x1="{zero_x:.1f}" y1="{top-5}" x2="{zero_x:.1f}" y2="{height-24}" '
        f'stroke="{GRID}" stroke-width="1.5"/>'
    ]
    for index, (label, value) in enumerate(pairs):
        y = top + index * row_h
        end_x = left + (value - minimum) / span * plot_w
        x = min(zero_x, end_x)
        bar_w = max(2.0, abs(end_x - zero_x))
        color = TEAL if value >= 0 else TONE_COLORS["critical"]
        display = _compact(value)
        short = label if len(label) <= 24 else label[:23] + "…"
        elements.extend([
            f'<text x="{left-12}" y="{y+18}" text-anchor="end" class="chart-label">{_safe(short)}</text>',
            f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="24" rx="5" fill="{color}" data-label="{_safe(label)}" data-value="{_safe(display)}">'
            f'<title>{_safe(label)}: {_safe(display)}</title></rect>',
            f'<text x="{max(x + bar_w + 8, zero_x + 8):.1f}" y="{y+17}" class="chart-value">{_safe(display)}</text>',
        ])
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_lollipop(visual: dict) -> str:
    pairs = _pairs(visual)
    if len(pairs) < 2:
        return ""
    width, height = 900, 390
    left, right, top, bottom = 72, 24, 34, 92
    plot_w, plot_h = width - left - right, height - top - bottom
    minimum = min(0.0, min(value for _, value in pairs))
    maximum = max(0.0, max(value for _, value in pairs))
    span = maximum - minimum or 1.0
    zero_y = top + maximum / span * plot_h
    gap = plot_w / len(pairs)
    elements = [
        f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" stroke="{GRID}"/>'
    ]
    for index, (label, value) in enumerate(pairs):
        x = left + gap * (index + .5)
        y = top + (maximum - value) / span * plot_h
        color = TEAL if value >= 0 else TONE_COLORS["critical"]
        display = _compact(value)
        short = label if len(label) <= 16 else label[:15] + "…"
        elements.extend([
            f'<line x1="{x:.1f}" y1="{zero_y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{color}" stroke-width="4"/>',
            f'<circle class="data-point" tabindex="0" cx="{x:.1f}" cy="{y:.1f}" r="8" fill="white" '
            f'stroke="{color}" stroke-width="4" data-label="{_safe(label)}" data-value="{_safe(display)}">'
            f'<title>{_safe(label)}: {_safe(display)}</title></circle>',
            f'<text x="{x:.1f}" y="{height-47}" text-anchor="middle" class="chart-label">{_safe(short)}</text>',
        ])
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_waterfall(visual: dict) -> str:
    pairs = _pairs(visual, 12)
    if len(pairs) < 2:
        return ""
    cumulative = [0.0]
    for _label, value in pairs:
        cumulative.append(cumulative[-1] + value)
    minimum = min(cumulative)
    maximum = max(cumulative)
    padding = (maximum - minimum) * .08 or max(abs(maximum) * .08, 1.0)
    minimum, maximum = minimum - padding, maximum + padding
    span = maximum - minimum
    width, height = 900, 410
    left, right, top, bottom = 72, 24, 34, 100
    plot_w, plot_h = width - left - right, height - top - bottom
    gap = plot_w / len(pairs)
    bar_w = max(16.0, gap * .58)

    def y(value: float) -> float:
        return top + (maximum - value) / span * plot_h

    elements = []
    for index, (label, value) in enumerate(pairs):
        start, end = cumulative[index], cumulative[index + 1]
        x = left + gap * index + (gap - bar_w) / 2
        top_y, bottom_y = min(y(start), y(end)), max(y(start), y(end))
        color = TEAL if value >= 0 else TONE_COLORS["critical"]
        display = _compact(value)
        short = label if len(label) <= 16 else label[:15] + "…"
        if index:
            previous_x = left + gap * (index - 1) + (gap + bar_w) / 2
            elements.append(
                f'<line x1="{previous_x:.1f}" y1="{y(start):.1f}" x2="{x:.1f}" y2="{y(start):.1f}" '
                f'stroke="{GRID}" stroke-dasharray="4 4"/>'
            )
        elements.extend([
            f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{top_y:.1f}" width="{bar_w:.1f}" '
            f'height="{max(2.0, bottom_y-top_y):.1f}" rx="4" fill="{color}" '
            f'data-label="{_safe(label)}" data-value="{_safe(display)}">'
            f'<title>{_safe(label)}: {_safe(display)}</title></rect>',
            f'<text x="{x+bar_w/2:.1f}" y="{height-49}" text-anchor="middle" class="chart-label">{_safe(short)}</text>',
        ])
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_line(visual: dict) -> str:
    pairs = _pairs(visual, 24)
    if len(pairs) < 2:
        return ""
    width, height = 900, 390
    left, right, top, bottom = 72, 24, 34, 86
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [value for _, value in pairs]
    minimum, maximum = min(values), max(values)
    padding = (maximum - minimum) * 0.08 or max(abs(maximum) * 0.08, 1.0)
    minimum, maximum = minimum - padding, maximum + padding
    span = maximum - minimum
    coords: list[tuple[float, float]] = []
    for index, (_label, value) in enumerate(pairs):
        coords.append((left + plot_w * index / (len(pairs) - 1), top + (maximum - value) / span * plot_h))
    elements = [
        f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in coords)}" '
        f'fill="none" stroke="{TEAL}" stroke-width="4" stroke-linejoin="round" '
        'stroke-linecap="round"/>'
    ]
    label_step = max(1, math.ceil(len(pairs) / 6))
    for index, ((label, value), (x, y)) in enumerate(zip(pairs, coords)):
        display = _compact(value)
        elements.append(
            f'<circle class="data-point" tabindex="0" cx="{x:.1f}" cy="{y:.1f}" r="6" '
            f'fill="white" stroke="{TEAL_DARK}" stroke-width="3" '
            f'data-label="{_safe(label)}" data-value="{_safe(display)}">'
            f'<title>{_safe(label)}: {_safe(display)}</title></circle>'
        )
        if index % label_step == 0 or index == len(pairs) - 1:
            short = label if len(label) <= 16 else label[:15] + "…"
            elements.append(
                f'<text x="{x:.1f}" y="{height-42}" text-anchor="middle" '
                f'class="chart-label">{_safe(short)}</text>'
            )
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_area(visual: dict) -> str:
    pairs = _pairs(visual, 24)
    if len(pairs) < 2:
        return ""
    width, height = 900, 390
    left, right, top, bottom = 72, 24, 34, 86
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [value for _, value in pairs]
    minimum, maximum = min(values), max(values)
    padding = (maximum - minimum) * .08 or max(abs(maximum) * .08, 1.0)
    minimum, maximum = minimum - padding, maximum + padding
    span = maximum - minimum
    coords = [
        (left + plot_w * index / (len(pairs) - 1), top + (maximum - value) / span * plot_h)
        for index, (_label, value) in enumerate(pairs)
    ]
    baseline = top + plot_h
    polygon = f"{left:.1f},{baseline:.1f} " + " ".join(
        f"{x:.1f},{y:.1f}" for x, y in coords
    ) + f" {left+plot_w:.1f},{baseline:.1f}"
    elements = [
        f'<defs><linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{TEAL}" stop-opacity=".42"/>'
        f'<stop offset="1" stop-color="{TEAL}" stop-opacity=".05"/></linearGradient></defs>',
        f'<polygon points="{polygon}" fill="url(#area-fill)"/>',
        f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in coords)}" fill="none" '
        f'stroke="{TEAL_DARK}" stroke-width="4" stroke-linejoin="round"/>',
    ]
    label_step = max(1, math.ceil(len(pairs) / 6))
    for index, ((label, value), (x, y)) in enumerate(zip(pairs, coords)):
        display = _compact(value)
        elements.append(
            f'<circle class="data-point" tabindex="0" cx="{x:.1f}" cy="{y:.1f}" r="6" fill="white" '
            f'stroke="{TEAL_DARK}" stroke-width="3" data-label="{_safe(label)}" data-value="{_safe(display)}">'
            f'<title>{_safe(label)}: {_safe(display)}</title></circle>'
        )
        if index % label_step == 0 or index == len(pairs) - 1:
            short = label if len(label) <= 16 else label[:15] + "…"
            elements.append(
                f'<text x="{x:.1f}" y="{height-42}" text-anchor="middle" class="chart-label">{_safe(short)}</text>'
            )
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_donut(visual: dict) -> str:
    pairs = [(label, value) for label, value in _pairs(visual) if value >= 0]
    total = sum(value for _, value in pairs)
    if len(pairs) < 2 or total <= 0:
        return ""
    palette = [TEAL_DARK, TEAL, "#42b9b0", "#76cbc5", "#2f67d8", "#6f91dd", "#d47b08", "#dc3b42"]
    circles = []
    legend = []
    offset = 0.0
    for index, (label, value) in enumerate(pairs):
        pct = value / total * 100.0
        color = palette[index % len(palette)]
        display = _compact(value)
        circles.append(
            f'<circle class="data-point" tabindex="0" cx="170" cy="170" r="112" '
            f'pathLength="100" fill="none" stroke="{color}" stroke-width="54" '
            f'stroke-dasharray="{max(0.0, pct - .35):.3f} {100 - max(0.0, pct - .35):.3f}" '
            f'stroke-dashoffset="{-offset:.3f}" transform="rotate(-90 170 170)" '
            f'data-label="{_safe(label)}" data-value="{_safe(display)} ({pct:.1f}%)">'
            f'<title>{_safe(label)}: {_safe(display)} ({pct:.1f}%)</title></circle>'
        )
        legend.append(
            '<li>'
            f'<i style="background:{color}"></i><span>{_safe(label)}</span>'
            f'<strong>{_safe(display)}</strong></li>'
        )
        offset += pct
    return (
        '<div class="donut-layout"><svg viewBox="0 0 340 340" role="img">'
        + "".join(circles)
        + f'<text x="170" y="162" text-anchor="middle" class="donut-total">{_safe(_compact(total))}</text>'
        + '<text x="170" y="188" text-anchor="middle" class="chart-label">total shown</text></svg>'
        + f'<ul class="chart-legend">{"".join(legend)}</ul></div>'
    )


def _multi_points(visual: dict, *, require_size: bool = False, limit: int = 20) -> list[tuple]:
    labels = list(visual.get("labels") or [])
    xs = list(visual.get("x_values") or [])
    ys = list(visual.get("y_values") or [])
    sizes = list(visual.get("size_values") or [])
    points = []
    for index, (label, x_value, y_value) in enumerate(zip(labels, xs, ys)):
        if label in (None, "") or not _finite_number(x_value) or not _finite_number(y_value):
            continue
        size = sizes[index] if index < len(sizes) else None
        if require_size and not _finite_number(size):
            continue
        points.append((str(label), float(x_value), float(y_value), float(size) if _finite_number(size) else None))
    return points[:limit]


def _finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _interactive_scatter(visual: dict, *, bubble: bool = False) -> str:
    points = _multi_points(visual, require_size=bubble)
    if len(points) < 2:
        return ""
    width, height = 900, 450
    left, right, top, bottom = 92, 34, 32, 82
    plot_w, plot_h = width - left - right, height - top - bottom
    x_values = [point[1] for point in points]
    y_values = [point[2] for point in points]

    def bounds(values: list[float]) -> tuple[float, float]:
        low, high = min(values), max(values)
        padding = (high - low) * .08 or max(abs(high) * .08, 1.0)
        return low - padding, high + padding

    x_min, x_max = bounds(x_values)
    y_min, y_max = bounds(y_values)
    size_abs = [abs(point[3] or 0.0) for point in points]
    size_min, size_max = min(size_abs), max(size_abs)
    elements = [
        f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="{GRID}"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="{GRID}"/>',
        f'<text x="{left+plot_w/2:.1f}" y="{height-25}" text-anchor="middle" class="axis-label">{_safe(visual.get("x_label"))}</text>',
        f'<text x="22" y="{top+plot_h/2:.1f}" text-anchor="middle" class="axis-label" transform="rotate(-90 22 {top+plot_h/2:.1f})">{_safe(visual.get("y_label"))}</text>',
    ]
    for label, x_value, y_value, size_value in points:
        x = left + (x_value - x_min) / (x_max - x_min) * plot_w
        y = top + (y_max - y_value) / (y_max - y_min) * plot_h
        radius = 8.0
        if bubble:
            ratio = 0.5 if size_max == size_min else (abs(size_value or 0.0) - size_min) / (size_max - size_min)
            radius = 8.0 + math.sqrt(max(0.0, ratio)) * 20.0
        detail = f"{visual.get('x_label')}: {_compact(x_value)}; {visual.get('y_label')}: {_compact(y_value)}"
        if bubble:
            detail += f"; {visual.get('size_label')}: {_compact(size_value or 0.0)}"
        elements.append(
            f'<circle class="data-point" tabindex="0" cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
            f'fill="{TEAL}" fill-opacity=".62" stroke="{TEAL_DARK}" stroke-width="2" '
            f'data-label="{_safe(label)}" data-value="{_safe(detail)}">'
            f'<title>{_safe(label)}: {_safe(detail)}</title></circle>'
        )
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_heatmap(visual: dict) -> str:
    labels = list(visual.get("labels") or [])[:12]
    series = [item for item in visual.get("series") or [] if isinstance(item, dict)][:6]
    if len(labels) < 2 or len(series) < 2:
        return ""
    matrix = []
    for row_index, label in enumerate(labels):
        values = []
        for item in series:
            raw = (item.get("values") or [])[row_index] if row_index < len(item.get("values") or []) else None
            values.append(float(raw) if _finite_number(raw) else None)
        matrix.append((str(label), values))
    finite = [abs(value) for _label, values in matrix for value in values if value is not None]
    if not finite:
        return ""
    # Normalize colour intensity within each measure so a revenue column cannot
    # visually erase a smaller-scale quantity or percentage column.
    column_max = [
        max((abs(values[col]) for _label, values in matrix if values[col] is not None), default=1.0) or 1.0
        for col in range(len(series))
    ]
    cell_w, cell_h = 118, 38
    left, top = 190, 72
    width = left + cell_w * len(series) + 28
    height = top + cell_h * len(matrix) + 38
    elements = []
    for col, item in enumerate(series):
        short = str(item.get("name") or "Measure")
        if len(short) > 16:
            short = short[:15] + "…"
        elements.append(
            f'<text x="{left+col*cell_w+cell_w/2:.1f}" y="42" text-anchor="middle" class="chart-label">{_safe(short)}</text>'
        )
    for row, (label, values) in enumerate(matrix):
        short = label if len(label) <= 24 else label[:23] + "…"
        elements.append(
            f'<text x="{left-12}" y="{top+row*cell_h+24}" text-anchor="end" class="chart-label">{_safe(short)}</text>'
        )
        for col, value in enumerate(values):
            if value is None:
                continue
            color = TEAL if value >= 0 else TONE_COLORS["critical"]
            opacity = .16 + .8 * abs(value) / column_max[col]
            display = _compact(value)
            measure = str(series[col].get("name") or "Measure")
            elements.extend([
                f'<rect class="data-point" tabindex="0" x="{left+col*cell_w:.1f}" y="{top+row*cell_h:.1f}" '
                f'width="{cell_w-3:.1f}" height="{cell_h-3:.1f}" rx="4" fill="{color}" fill-opacity="{opacity:.3f}" '
                f'data-label="{_safe(label)}" data-value="{_safe(measure)}: {_safe(display)}">'
                f'<title>{_safe(label)} — {_safe(measure)}: {_safe(display)}</title></rect>',
                f'<text x="{left+col*cell_w+cell_w/2:.1f}" y="{top+row*cell_h+24}" text-anchor="middle" '
                f'class="heat-value">{_safe(display)}</text>',
            ])
    return f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'


def _interactive_grouped_bar(visual: dict) -> str:
    labels = list(visual.get("labels") or [])[:8]
    series = [item for item in visual.get("series") or [] if isinstance(item, dict)][:4]
    if len(labels) < 2 or len(series) < 2:
        return ""
    values = [
        float(raw)
        for item in series
        for raw in (item.get("values") or [])[:len(labels)]
        if _finite_number(raw)
    ]
    if not values:
        return ""
    maximum = max(values) or 1.0
    width, height = 900, 430
    left, right, top, bottom = 72, 24, 42, 112
    plot_w, plot_h = width-left-right, height-top-bottom
    group_w = plot_w / len(labels)
    bar_w = max(8.0, group_w * .72 / len(series))
    palette = [TEAL_DARK, TEAL, "#2f67d8", "#d47b08"]
    elements = []
    legend = []
    for series_index, item in enumerate(series):
        color = palette[series_index % len(palette)]
        name = str(item.get("name") or f"Measure {series_index+1}")
        legend.append(
            f'<span><i style="background:{color}"></i>{_safe(name)}</span>'
        )
        for label_index, label in enumerate(labels):
            raw_values = item.get("values") or []
            if label_index >= len(raw_values) or not _finite_number(raw_values[label_index]):
                continue
            value = float(raw_values[label_index])
            x = left + label_index*group_w + group_w*.14 + series_index*bar_w
            bar_h = max(2.0, value / maximum * plot_h)
            y = top + plot_h - bar_h
            display = _compact(value)
            elements.append(
                f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{y:.1f}" width="{bar_w-2:.1f}" '
                f'height="{bar_h:.1f}" rx="3" fill="{color}" data-label="{_safe(label)}" '
                f'data-value="{_safe(name)}: {_safe(display)}"><title>{_safe(label)} — {_safe(name)}: {_safe(display)}</title></rect>'
            )
    for label_index, label in enumerate(labels):
        short = str(label) if len(str(label)) <= 16 else str(label)[:15] + "…"
        elements.append(
            f'<text x="{left+(label_index+.5)*group_w:.1f}" y="{height-64}" text-anchor="middle" class="chart-label">{_safe(short)}</text>'
        )
    return (
        f'<div class="series-legend">{"".join(legend)}</div>'
        f'<svg viewBox="0 0 {width} {height}" role="img">{"".join(elements)}</svg>'
    )


def _chart_block(block: dict, index: int) -> str:
    visual = block.get("chart") or {}
    chart_type = str(visual.get("type") or "bar")
    renderers = {
        "bar": _interactive_bar,
        "horizontal_bar": _interactive_horizontal_bar,
        "lollipop": _interactive_lollipop,
        "waterfall": _interactive_waterfall,
        "line": _interactive_line,
        "area": _interactive_area,
        "donut": _interactive_donut,
        "scatter": lambda value: _interactive_scatter(value, bubble=False),
        "bubble": lambda value: _interactive_scatter(value, bubble=True),
        "heatmap": _interactive_heatmap,
        "grouped_bar": _interactive_grouped_bar,
    }
    graphic = renderers.get(chart_type, _interactive_bar)(visual)
    if not graphic:
        return ""
    if visual.get("x_values") and visual.get("y_values"):
        rows = []
        for point in _multi_points(visual, limit=24):
            label, x_value, y_value, size_value = point
            detail = f"{visual.get('x_label')}: {_compact(x_value)}; {visual.get('y_label')}: {_compact(y_value)}"
            if size_value is not None:
                detail += f"; {visual.get('size_label')}: {_compact(size_value)}"
            rows.append(f'<tr><th scope="row">{_safe(label)}</th><td>{_safe(detail)}</td></tr>')
        rows = "".join(rows)
    elif visual.get("series"):
        rows = []
        labels = list(visual.get("labels") or [])[:24]
        for row_index, label in enumerate(labels):
            details = []
            for series in visual.get("series") or []:
                values = series.get("values") or []
                if row_index < len(values) and _finite_number(values[row_index]):
                    details.append(f"{series.get('name')}: {_compact(float(values[row_index]))}")
            rows.append(f'<tr><th scope="row">{_safe(label)}</th><td>{_safe("; ".join(details))}</td></tr>')
        rows = "".join(rows)
    else:
        rows = "".join(
            f'<tr><th scope="row">{_safe(label)}</th><td>{_safe(_compact(value))}</td></tr>'
            for label, value in _pairs(visual, 24)
        )
    return (
        f'<section class="chart interactive-chart" data-chart-type="{_safe(chart_type)}" '
        f'aria-labelledby="chart-{index}">'
        '<div class="chart-head">'
        f'<h2 id="chart-{index}">{_safe(visual.get("title") or block.get("heading") or "Supporting view")}</h2>'
        f'<span>{_safe(visual.get("value_label") or "")}</span></div>'
        f'<div class="chart-stage">{graphic}<div class="chart-tooltip" role="status"></div></div>'
        '<details class="chart-data"><summary>View chart data</summary>'
        f'<table><tbody>{rows}</tbody></table></details></section>'
    )


def _content_layout(blocks: list[dict]) -> str:
    rendered: list[str] = []
    for index, block in enumerate(blocks, start=1):
        kind = str(block.get("kind") or "")
        heading = str(block.get("heading") or "").strip()
        heading_html = f'<h2>{_safe(heading)}</h2>' if heading else ""
        if kind == "paragraph" and block.get("text"):
            rendered.append(
                f'<section class="content-block prose-block">{heading_html}'
                f'<p>{_safe(block.get("text"))}</p></section>'
            )
        elif kind == "bullets" and block.get("points"):
            points = "".join(f'<li>{_safe(point)}</li>' for point in block.get("points") or [])
            rendered.append(
                f'<section class="content-block bullet-block">{heading_html}<ul>{points}</ul></section>'
            )
        elif kind == "chart":
            chart = _chart_block(block, index)
            if chart:
                rendered.append(chart)
    return "".join(rendered)


def _interaction_script() -> str:
    return """<script>
document.querySelectorAll('.interactive-chart .data-point').forEach(function(point){
  const chart = point.closest('.interactive-chart');
  const tip = chart.querySelector('.chart-tooltip');
  function show(event){
    tip.textContent = point.dataset.label + ': ' + point.dataset.value;
    tip.classList.add('visible');
    const box = chart.querySelector('.chart-stage').getBoundingClientRect();
    const target = point.getBoundingClientRect();
    tip.style.left = Math.max(8, Math.min(box.width - tip.offsetWidth - 8, target.left - box.left + target.width / 2 - tip.offsetWidth / 2)) + 'px';
    tip.style.top = Math.max(8, target.top - box.top - tip.offsetHeight - 8) + 'px';
  }
  function hide(){ tip.classList.remove('visible'); }
  point.addEventListener('mouseenter', show);
  point.addEventListener('mousemove', show);
  point.addEventListener('mouseleave', hide);
  point.addEventListener('focus', show);
  point.addEventListener('blur', hide);
});
</script>"""


def render(summary: dict, title: str = "AI Summary") -> str:
    freshness = str(summary.get("freshness_status") or "unknown").replace("_", " ").title()
    grain = str(summary.get("grain") or "snapshot").replace("_", " ").title()
    data_as_of = summary.get("data_as_of") or "Unknown"
    generated = datetime.now(timezone.utc).date().isoformat()
    dynamic = summary.get("content_blocks") is not None
    if dynamic:
        content = _content_layout(list(summary.get("content_blocks") or []))
    else:
        visual = summary.get("visual") or {}
        svg = _line_chart(visual) if visual.get("type") == "line" else _bar_chart(visual)
        metrics = _metric_band(list(summary.get("metrics") or []))
        sections = _section_layout(list(summary.get("sections") or []))
        chart = ""
        if svg:
            chart = (
                '<section class="chart"><div class="chart-head">'
                f'<h2>{_safe(visual.get("title") or "Supporting view")}</h2>'
                f'<span>{_safe(visual.get("value_label") or "")}</span></div>{svg}</section>'
            )
        content = metrics + sections + chart
    style = """
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#fff;color:__INK__;font-family:"Segoe UI",Inter,Arial,sans-serif;line-height:1.58;border-top:1px solid __GRID__}
.page{max-width:1280px;margin:0 auto;padding:40px 30px 58px}.hero{padding:0 0 30px}.topline{display:flex;justify-content:space-between;gap:24px;align-items:center}
.eyebrow{color:__TEAL_DARK__;font-weight:750;font-size:13px;letter-spacing:.12em;text-transform:uppercase}.generated{color:#8496a5;font-size:14px;white-space:nowrap}
h1{font-size:clamp(30px,3.45vw,44px);line-height:1.28;letter-spacing:-.025em;margin:21px 0 18px;max-width:980px;font-weight:720}.context{display:flex;align-items:center;flex-wrap:wrap;gap:0;color:__MUTED__;font-size:13px}
.context span{display:inline-flex;align-items:center}.context span+span:before{content:"";width:4px;height:4px;margin:0 11px;border-radius:50%;background:__TEAL__;opacity:.8}
.metrics{display:grid;border:1px solid __GRID__;border-radius:2px;overflow:hidden;margin:0 0 38px;background:#fff}.metrics-1{grid-template-columns:1fr}.metrics-2{grid-template-columns:repeat(2,minmax(0,1fr))}.metrics-3{grid-template-columns:repeat(3,minmax(0,1fr))}.metrics-4{grid-template-columns:repeat(4,minmax(0,1fr))}
.metric{padding:24px 26px 22px;min-height:118px;border-right:1px solid __GRID__}.metric:last-child{border-right:0}.metric-label{display:flex;align-items:center;gap:9px;color:#8093a2;font-size:12px;font-weight:750;letter-spacing:.07em;text-transform:uppercase}
.metric-label i{width:8px;height:8px;border-radius:99px;display:inline-block;flex:0 0 auto}.metric-value{font-size:clamp(27px,2.8vw,39px);line-height:1.15;font-weight:760;letter-spacing:-.035em;margin-top:12px}
.section-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:62px;row-gap:30px;margin-top:2px}.summary-section{padding:0 6px 4px 0}.summary-section:only-child{grid-column:1/-1}.section-heading{display:flex;align-items:center;gap:11px;margin-bottom:16px;color:var(--accent,__TEAL__)}
.section-icon{width:21px;height:21px;display:block;flex:0 0 auto;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.section-heading h2{color:#526a7b;font-size:15px;line-height:1.3;text-transform:uppercase;letter-spacing:.055em;margin:0;font-weight:750}
ul{margin:0;padding:0;list-style:none}.summary-section li{position:relative;padding:0 0 16px 24px;color:__MUTED__;font-size:17px;line-height:1.6}.summary-section li:before{content:"";position:absolute;left:1px;top:.72em;width:7px;height:7px;border-radius:99px;background:var(--accent)}
.actions{--accent:__TEAL__;margin-top:32px;padding:25px 30px 23px;border:1px solid __GRID__;border-radius:18px;background:__SOFT__}.actions .section-heading{margin-bottom:10px}.actions ol{margin:0;padding:0;list-style:none}
.actions li{display:grid;grid-template-columns:31px 1fr;gap:13px;align-items:start;padding:8px 0}.actions li span{display:grid;place-items:center;width:29px;height:29px;border-radius:8px;background:#e9f8f6;color:__TEAL_DARK__;font-weight:750;font-size:14px}.actions p{margin:0;color:__INK__;font-size:17px;line-height:1.55}
.chart{margin-top:34px;padding:25px 28px 18px;border:1px solid __GRID__;border-radius:15px;background:#fff}.chart-head{display:flex;justify-content:space-between;gap:18px;align-items:baseline;margin-bottom:9px}.chart-head h2{text-transform:none;letter-spacing:-.01em;font-size:19px;margin:0;color:__INK__}.chart-head span,.chart-label{fill:__MUTED__;color:__MUTED__;font-size:12px}.chart-value{fill:__INK__;font-size:11px;font-weight:650}svg{display:block;width:100%;height:auto;overflow:visible}
.content-block{margin:0 0 30px;max-width:1050px}.content-block h2{margin:0 0 13px;color:__INK__;font-size:21px;line-height:1.35;letter-spacing:-.012em}.prose-block p{margin:0;color:__MUTED__;font-size:17px;line-height:1.72}.bullet-block ul{display:grid;gap:11px;margin:0;padding:0;list-style:none}.bullet-block li{position:relative;padding-left:22px;color:__MUTED__;font-size:17px;line-height:1.65}.bullet-block li:before{content:"";position:absolute;left:2px;top:.72em;width:7px;height:7px;border-radius:50%;background:__TEAL__}
.interactive-chart{margin:32px 0}.chart-stage{position:relative;overflow-x:auto}.interactive-chart svg{min-width:620px}.data-point{cursor:pointer;transition:opacity .16s ease,filter .16s ease,stroke-width .16s ease;outline:none}.data-point:hover,.data-point:focus{opacity:.78;filter:brightness(.96)}.data-point:focus{stroke-width:5px}.chart-tooltip{position:absolute;z-index:3;pointer-events:none;opacity:0;transform:translateY(4px);transition:opacity .12s ease,transform .12s ease;background:__INK__;color:white;padding:7px 10px;border-radius:7px;font-size:12px;font-weight:650;white-space:nowrap;box-shadow:0 7px 20px rgba(28,42,49,.18)}.chart-tooltip.visible{opacity:1;transform:translateY(0)}
.axis-label{fill:__MUTED__;font-size:13px;font-weight:700}.heat-value{fill:__INK__;font-size:10.5px;font-weight:720;pointer-events:none}.series-legend{display:flex;justify-content:flex-end;flex-wrap:wrap;gap:14px;margin:2px 8px -18px;color:__MUTED__;font-size:12px}.series-legend span{display:inline-flex;align-items:center;gap:6px}.series-legend i{width:9px;height:9px;border-radius:2px;display:inline-block}
.donut-layout{display:grid;grid-template-columns:minmax(260px,420px) minmax(260px,1fr);align-items:center;gap:24px}.donut-layout svg{min-width:260px;max-width:400px;margin:auto}.donut-total{fill:__INK__;font-size:27px;font-weight:760}.chart-legend{display:grid;gap:9px;margin:0;padding:0;list-style:none}.chart-legend li{display:grid;grid-template-columns:10px minmax(0,1fr) auto;gap:10px;align-items:center;color:__MUTED__;font-size:13px}.chart-legend i{width:9px;height:9px;border-radius:50%}.chart-legend strong{color:__INK__;font-weight:700}.chart-data{margin:2px 0 7px;border-top:1px solid __GRID__;padding-top:12px}.chart-data summary{cursor:pointer;color:__TEAL_DARK__;font-size:13px;font-weight:700;list-style-position:inside}.chart-data table{width:100%;margin-top:10px;border-collapse:collapse;font-size:13px}.chart-data th,.chart-data td{padding:7px 8px;border-bottom:1px solid __GRID__;text-align:left}.chart-data th{color:__MUTED__;font-weight:550}.chart-data td{color:__INK__;font-weight:700;text-align:right}
.summary-footer{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-top:28px;padding-top:16px;border-top:1px solid __GRID__;color:#8498a8;font-size:12px}.summary-footer strong{color:__TEAL_DARK__;font-weight:650}
@media(max-width:800px){.page{padding:34px 22px 48px}.metrics-3,.metrics-4{grid-template-columns:repeat(2,minmax(0,1fr))}.metric{border-bottom:1px solid __GRID__}.metric:nth-child(2n){border-right:0}.metric:last-child{border-bottom:0}.metrics-2 .metric{border-bottom:0}.metrics-4 .metric:nth-child(3),.metrics-4 .metric:nth-child(4),.metrics-3 .metric:nth-child(3){border-bottom:0}.section-grid{grid-template-columns:1fr;gap:24px}.summary-section{padding-right:0}}
@media(max-width:700px){.donut-layout{grid-template-columns:1fr}.interactive-chart svg{min-width:560px}.donut-layout svg{min-width:260px}}
@media(max-width:500px){.topline{align-items:flex-start;flex-direction:column;gap:7px}.hero{padding-bottom:24px}.metrics-2,.metrics-3,.metrics-4{grid-template-columns:1fr}.metrics-2 .metric,.metrics-3 .metric,.metrics-4 .metric,.metric:nth-child(2n){border-right:0;border-bottom:1px solid __GRID__}.metric:last-child,.metrics-2 .metric:last-child,.metrics-3 .metric:last-child,.metrics-4 .metric:last-child{border-bottom:0}.actions{padding:22px 20px}.chart{padding:20px 12px 12px}.chart-head,.summary-footer{align-items:flex-start;flex-direction:column;gap:5px}.content-block h2{font-size:19px}.prose-block p,.bullet-block li{font-size:16px}}
@media print{body{border-top:0}.page{max-width:none;padding:24px}.actions,.chart,.metrics,.summary-section{break-inside:avoid}}
"""
    for token, value in {
        "__INK__": INK,
        "__TEAL__": TEAL,
        "__TEAL_DARK__": TEAL_DARK,
        "__MUTED__": MUTED,
        "__GRID__": GRID,
        "__SOFT__": SOFT,
    }.items():
        style = style.replace(token, value)
    script = _interaction_script() if dynamic else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)}</title><style>{style}</style></head><body><main class="page">
<header class="hero"><div class="topline"><div class="eyebrow">{_safe(title)}</div><div class="generated">Generated {_safe(generated)}</div></div>
<h1>{_safe(summary.get("heading"))}</h1>
<div class="context" aria-label="Report context"><span>Data through {_safe(data_as_of)}</span><span>{_safe(grain)} view</span><span>{_safe(freshness)} data</span></div></header>
{content}
<footer class="summary-footer"><span>Figures are shown from the validated report evidence.</span><strong>AI-assisted analysis</strong></footer>
</main>{script}</body></html>"""
