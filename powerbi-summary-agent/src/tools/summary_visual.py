"""Render the fresh summary as a polished white/black/teal report."""

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


def render(summary: dict, title: str = "AI Summary") -> str:
    visual = summary.get("visual") or {}
    svg = _line_chart(visual) if visual.get("type") == "line" else _bar_chart(visual)
    freshness = str(summary.get("freshness_status") or "unknown").replace("_", " ").title()
    grain = str(summary.get("grain") or "snapshot").replace("_", " ").title()
    data_as_of = summary.get("data_as_of") or "Unknown"
    generated = datetime.now(timezone.utc).date().isoformat()
    metrics = _metric_band(list(summary.get("metrics") or []))
    sections = _section_layout(list(summary.get("sections") or []))
    chart = ""
    if svg:
        chart = (
            '<section class="chart"><div class="chart-head">'
            f'<h2>{_safe(visual.get("title") or "Supporting view")}</h2>'
            f'<span>{_safe(visual.get("value_label") or "")}</span></div>{svg}</section>'
        )
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
.summary-footer{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-top:28px;padding-top:16px;border-top:1px solid __GRID__;color:#8498a8;font-size:12px}.summary-footer strong{color:__TEAL_DARK__;font-weight:650}
@media(max-width:800px){.page{padding:34px 22px 48px}.metrics-3,.metrics-4{grid-template-columns:repeat(2,minmax(0,1fr))}.metric{border-bottom:1px solid __GRID__}.metric:nth-child(2n){border-right:0}.metric:last-child{border-bottom:0}.metrics-2 .metric{border-bottom:0}.metrics-4 .metric:nth-child(3),.metrics-4 .metric:nth-child(4),.metrics-3 .metric:nth-child(3){border-bottom:0}.section-grid{grid-template-columns:1fr;gap:24px}.summary-section{padding-right:0}}
@media(max-width:500px){.topline{align-items:flex-start;flex-direction:column;gap:7px}.hero{padding-bottom:24px}.metrics-2,.metrics-3,.metrics-4{grid-template-columns:1fr}.metrics-2 .metric,.metrics-3 .metric,.metrics-4 .metric,.metric:nth-child(2n){border-right:0;border-bottom:1px solid __GRID__}.metric:last-child,.metrics-2 .metric:last-child,.metrics-3 .metric:last-child,.metrics-4 .metric:last-child{border-bottom:0}.actions{padding:22px 20px}.chart{padding:20px 12px 12px}.chart-head,.summary-footer{align-items:flex-start;flex-direction:column;gap:5px}}
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
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)}</title><style>{style}</style></head><body><main class="page">
<header class="hero"><div class="topline"><div class="eyebrow">{_safe(title)}</div><div class="generated">Generated {_safe(generated)}</div></div>
<h1>{_safe(summary.get("heading"))}</h1>
<div class="context" aria-label="Report context"><span>Data through {_safe(data_as_of)}</span><span>{_safe(grain)} view</span><span>{_safe(freshness)} data</span></div></header>
{metrics}{sections}{chart}
<footer class="summary-footer"><span>Structured summary — figures are shown exactly as published.</span><strong>AI-assisted analysis</strong></footer>
</main></body></html>"""
