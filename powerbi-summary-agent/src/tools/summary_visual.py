"""Render the fresh summary as a restrained white/black/teal report."""

from __future__ import annotations

import html
import math
from datetime import datetime, timezone


TEAL = "#0f9f95"
TEAL_DARK = "#087a73"
INK = "#111827"
MUTED = "#5f6b78"
GRID = "#dcebea"
TONE_COLORS = {
    "positive": "#0f9f95",
    "critical": "#dc5b5b",
    "warning": "#c98524",
    "info": "#3978b8",
    "teal": "#0f9f95",
}


def _safe(value) -> str:
    return html.escape(str(value or ""), quote=True)


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
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
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
        f'<line x1="{left}" y1="{zero_y:.1f}" x2="{width-right}" y2="{zero_y:.1f}" stroke="{GRID}" stroke-width="1.5"/>'
    ]
    for index, (label, value) in enumerate(pairs):
        x = left + gap * index + (gap - bar_w) / 2
        y = top + ((maximum - max(value, 0.0)) / span) * plot_h
        bar_h = abs(value) / span * plot_h
        if value < 0:
            y = zero_y
        fill = TEAL if value >= 0 else TEAL_DARK
        short = label if len(label) <= 14 else label[:13] + "…"
        value_y = max(16, y - 7) if value >= 0 else min(height - bottom + bar_h + 16, height - 50)
        elements.extend([
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(1.5, bar_h):.1f}" rx="4" fill="{fill}"/>',
            f'<text x="{x + bar_w/2:.1f}" y="{value_y:.1f}" text-anchor="middle" class="chart-value">{_safe(_compact(value))}</text>',
            f'<text x="{x + bar_w/2:.1f}" y="{height-34}" text-anchor="middle" class="chart-label">{_safe(short)}</text>',
        ])
    return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_safe(visual.get("title"))}">{"".join(elements)}</svg>'


def _line_chart(visual: dict) -> str:
    pairs = [
        (str(label), float(value))
        for label, value in zip(visual.get("labels") or [], visual.get("values") or [])
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
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
            elements.append(f'<text x="{x:.1f}" y="{height-34}" text-anchor="middle" class="chart-label">{_safe(short)}</text>')
        elements.extend([
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="white" stroke="{TEAL}" stroke-width="3"/>',
            f'<text x="{x:.1f}" y="{max(16, y-11):.1f}" text-anchor="middle" class="chart-value">{_safe(_compact(value))}</text>',
        ])
    elements.insert(0, f'<polyline points="{" ".join(points)}" fill="none" stroke="{TEAL}" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>')
    return f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{_safe(visual.get("title"))}">{"".join(elements)}</svg>'


def _metric_band(metrics: list[dict]) -> str:
    items = []
    for metric in metrics[:4]:
        tone = str(metric.get("tone") or "teal").casefold()
        color = TONE_COLORS.get(tone, TEAL)
        items.append(
            '<article class="metric">'
            f'<div class="metric-label"><i style="background:{color}"></i>{_safe(metric.get("label"))}</div>'
            f'<div class="metric-value" style="color:{color}">{_safe(metric.get("value"))}</div>'
            "</article>"
        )
    return f'<section class="metrics">{"".join(items)}</section>' if items else ""


def _section_layout(sections: list[dict]) -> str:
    regular = []
    actions = []
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        target = actions if any(token in heading.casefold() for token in ("action", "next step")) else regular
        target.append(section)

    regular_html = []
    for section in regular:
        tone = str(section.get("tone") or "teal").casefold()
        color = TONE_COLORS.get(tone, TEAL)
        points = "".join(f"<li>{_safe(point)}</li>" for point in section.get("points") or [])
        regular_html.append(
            f'<section class="summary-section tone-{_safe(tone)}" style="--accent:{color}">'
            f'<h2>{_safe(section.get("heading"))}</h2><ul>{points}</ul></section>'
        )

    actions_html = []
    for section in actions:
        points = "".join(
            f'<li><span>{index}</span><p>{_safe(point)}</p></li>'
            for index, point in enumerate(section.get("points") or [], start=1)
        )
        actions_html.append(
            '<section class="actions"><h2>'
            f'{_safe(section.get("heading"))}</h2><ol>{points}</ol></section>'
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
*{box-sizing:border-box} body{margin:0;background:#fff;color:__INK__;font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.58}
.page{max-width:1080px;margin:0 auto;padding:54px 38px 72px} .topline{display:flex;justify-content:space-between;gap:24px;align-items:center}
.eyebrow{color:__TEAL_DARK__;font-weight:750;font-size:12px;letter-spacing:.13em;text-transform:uppercase} .generated{color:__MUTED__;font-size:13px}
h1{font-size:clamp(30px,4.7vw,47px);line-height:1.15;letter-spacing:-.034em;margin:18px 0 20px;max-width:940px} .rule{width:72px;height:5px;border-radius:8px;background:__TEAL__;margin:0 0 20px}
.meta{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 32px} .meta span{font-size:13px;color:__MUTED__;border:1px solid __GRID__;border-radius:999px;padding:6px 11px;background:#f8fcfb}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid __GRID__;border-radius:16px;overflow:hidden;margin:0 0 38px;background:#fff}
.metric{padding:22px 20px;min-height:116px;border-right:1px solid __GRID__} .metric:last-child{border-right:0} .metric-label{display:flex;align-items:center;gap:8px;color:__MUTED__;font-size:12px;font-weight:750;letter-spacing:.055em;text-transform:uppercase}
.metric-label i{width:8px;height:8px;border-radius:99px;display:inline-block;flex:0 0 auto} .metric-value{font-size:clamp(25px,3vw,36px);font-weight:780;letter-spacing:-.035em;margin-top:10px}
.section-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px;margin-top:4px} .summary-section{border-top:3px solid var(--accent);padding:20px 18px 6px 0}
h2{font-size:15px;line-height:1.3;text-transform:uppercase;letter-spacing:.055em;margin:0 0 15px} ul{margin:0;padding:0;list-style:none} .summary-section li{position:relative;padding:0 0 15px 24px;color:#374151}
.summary-section li:before{content:"";position:absolute;left:3px;top:.7em;width:7px;height:7px;border-radius:99px;background:var(--accent)}
.actions{margin-top:32px;padding:24px 28px;border:1px solid __GRID__;border-radius:17px;background:#f8fcfb} .actions h2{color:__TEAL_DARK__} .actions ol{margin:0;padding:0;list-style:none}
.actions li{display:grid;grid-template-columns:30px 1fr;gap:12px;align-items:start;padding:9px 0} .actions li span{display:grid;place-items:center;width:28px;height:28px;border-radius:8px;background:#dff4f1;color:__TEAL_DARK__;font-weight:750} .actions p{margin:1px 0 0;color:#28323e}
.chart{margin-top:38px;padding:24px;border:1px solid __GRID__;border-radius:18px;background:#fff;box-shadow:0 15px 40px rgba(15,159,149,.08)}
.chart-head{display:flex;justify-content:space-between;gap:18px;align-items:baseline;margin-bottom:10px} .chart-head h2{text-transform:none;letter-spacing:0;font-size:18px} .chart-head span,.chart-label{fill:__MUTED__;color:__MUTED__;font-size:12px} .chart-value{fill:__INK__;font-size:11px;font-weight:650} svg{display:block;width:100%;height:auto;overflow:visible}
@media(max-width:760px){.page{padding:38px 20px 52px} .metrics{grid-template-columns:repeat(2,minmax(0,1fr))} .metric{border-bottom:1px solid __GRID__} .section-grid{grid-template-columns:1fr}}
@media(max-width:440px){.topline{align-items:flex-start;flex-direction:column;gap:8px} .metrics{grid-template-columns:1fr} .metric{border-right:0} .chart{padding:14px}}
"""
    for token, value in {
        "__INK__": INK,
        "__TEAL__": TEAL,
        "__TEAL_DARK__": TEAL_DARK,
        "__MUTED__": MUTED,
        "__GRID__": GRID,
    }.items():
        style = style.replace(token, value)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)}</title><style>{style}</style></head><body><main class="page">
<div class="topline"><div class="eyebrow">{_safe(title)}</div><div class="generated">Generated {_safe(generated)}</div></div>
<h1>{_safe(summary.get("heading"))}</h1><div class="rule"></div>
<div class="meta"><span>Data through {_safe(data_as_of)}</span><span>{_safe(grain)} grain</span><span>{_safe(freshness)}</span></div>
{metrics}{sections}{chart}</main></body></html>"""
