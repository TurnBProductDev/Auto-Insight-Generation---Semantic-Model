"""Render the fresh summary as a restrained white/black/teal report."""

from __future__ import annotations

import html
import math


TEAL = "#0f9f95"
TEAL_DARK = "#087a73"
INK = "#111827"
MUTED = "#5f6b78"
GRID = "#dcebea"


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


def render(summary: dict, title: str = "AI Summary") -> str:
    visual = summary.get("visual") or {}
    svg = _line_chart(visual) if visual.get("type") == "line" else _bar_chart(visual)
    freshness = str(summary.get("freshness_status") or "unknown").replace("_", " ").title()
    grain = str(summary.get("grain") or "snapshot").replace("_", " ").title()
    data_as_of = summary.get("data_as_of") or "Unknown"
    paragraphs = "".join(f"<p>{_safe(item)}</p>" for item in summary.get("paragraphs") or [])
    chart = ""
    if svg:
        chart = (
            '<section class="chart"><div class="chart-head">'
            f'<h2>{_safe(visual.get("title") or "Supporting view")}</h2>'
            f'<span>{_safe(visual.get("value_label") or "")}</span></div>{svg}</section>'
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_safe(title)}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#fff;color:{INK};font-family:Inter,Segoe UI,Arial,sans-serif;line-height:1.62}}
.page{{max-width:940px;margin:0 auto;padding:60px 42px 72px}} .eyebrow{{color:{TEAL_DARK};font-weight:700;font-size:12px;letter-spacing:.14em;text-transform:uppercase}}
h1{{font-size:clamp(30px,5vw,48px);line-height:1.12;letter-spacing:-.035em;margin:14px 0 18px;max-width:820px}} .rule{{width:72px;height:5px;border-radius:8px;background:{TEAL};margin:0 0 22px}}
.meta{{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 30px}} .meta span{{font-size:13px;color:{MUTED};border:1px solid {GRID};border-radius:999px;padding:6px 11px;background:#f8fcfb}}
.copy{{max-width:790px;font-size:18px}} .copy p{{margin:0 0 17px}} .chart{{margin-top:40px;padding:24px;border:1px solid {GRID};border-radius:18px;background:#fff;box-shadow:0 15px 40px rgba(15,159,149,.08)}}
.chart-head{{display:flex;justify-content:space-between;gap:18px;align-items:baseline;margin-bottom:10px}} h2{{font-size:18px;margin:0}} .chart-head span,.chart-label{{fill:{MUTED};color:{MUTED};font-size:12px}} .chart-value{{fill:{INK};font-size:11px;font-weight:650}} svg{{display:block;width:100%;height:auto;overflow:visible}}
@media(max-width:640px){{.page{{padding:38px 20px 52px}} .copy{{font-size:16px}} .chart{{padding:14px}}}}
</style></head><body><main class="page"><div class="eyebrow">{_safe(title)}</div><h1>{_safe(summary.get("heading"))}</h1><div class="rule"></div>
<div class="meta"><span>Data through { _safe(data_as_of) }</span><span>{_safe(grain)} grain</span><span>{_safe(freshness)}</span></div>
<section class="copy">{paragraphs}</section>{chart}</main></body></html>"""
