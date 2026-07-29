"""Render the fresh summary as a ScanB-styled HTML report.

Design contract: this document has to sit next to the ScanB web application
without looking like a different product, so it consumes the SAME design tokens
as `wwwroot/css/theme.css` (--sb-*) and mirrors the card/pill/stat patterns from
`KpiInsights.css`. Keep the token block in sync if the app's theme moves.

Standalone-safe: no external CSS, fonts, or scripts (the file is uploaded to blob
storage and opened directly), so Inter is requested but degrades to the system
stack. Dark mode is driven BOTH by `prefers-color-scheme` (standalone viewing)
and by `:root[data-theme="dark"]` (the attribute the app sets), so the same file
is correct in either context.

Charts are inline SVG coloured through CSS custom properties rather than
hard-coded fills, which is what lets them re-theme in dark mode.
"""

from __future__ import annotations

import html
import math
import re
from datetime import datetime, timezone

# Severity vocabulary shared with the app. Anything unrecognised falls back to
# the brand accent rather than inventing a colour.
TONES = ("positive", "critical", "warning", "info")
_NEGATIVE_HINT = re.compile(r"^\s*[-−]")
_POSITIVE_HINT = re.compile(r"^\s*\+")


def _safe(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _tone(value, default: str = "info") -> str:
    tone = str(value or "").casefold().strip()
    return tone if tone in TONES else default


def _compact(value: float) -> str:
    value = float(value)
    absolute = abs(value)
    if absolute >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if absolute >= 1_000:
        return f"{value / 1_000:.1f}K"
    return f"{value:.1f}" if not float(value).is_integer() else f"{int(value):,}"


def _pairs(visual: dict, limit: int) -> list[tuple[str, float]]:
    return [
        (str(label), float(value))
        for label, value in zip(visual.get("labels") or [], visual.get("values") or [])
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    ][:limit]


def _arrow(direction: str) -> str:
    """Up/down caret used on stat tiles. Inherits colour via currentColor."""
    path = "M8 3.5 13 10H3z" if direction == "up" else "M8 12.5 3 6h10z"
    return (
        '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
        f'<path d="{path}" fill="currentColor"/></svg>'
    )


def _direction(text: str) -> str:
    """Read +/- off a pre-formatted display value; never re-computes anything."""
    if _NEGATIVE_HINT.search(str(text)):
        return "down"
    if _POSITIVE_HINT.search(str(text)):
        return "up"
    return ""


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

def _axis(width: int, left: int, right: int, top: int, plot_h: float,
          maximum: float, minimum: float, ticks: int = 4) -> list[str]:
    """Horizontal gridlines + value ticks, drawn behind the series."""
    out = []
    span = (maximum - minimum) or 1.0
    for index in range(ticks + 1):
        value = maximum - span * index / ticks
        y = top + (maximum - value) / span * plot_h
        out.append(
            f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width - right}" y2="{y:.1f}"/>'
        )
        out.append(
            f'<text class="tick" x="{left - 10}" y="{y + 4:.1f}" text-anchor="end">'
            f'{_safe(_compact(value))}</text>'
        )
    return out


def _bar_chart(visual: dict) -> str:
    pairs = _pairs(visual, 8)
    if len(pairs) < 2:
        return ""
    width, height = 780, 340
    left, right, top, bottom = 74, 24, 26, 64
    plot_w, plot_h = width - left - right, height - top - bottom
    minimum = min(0.0, min(v for _, v in pairs))
    maximum = max(0.0, max(v for _, v in pairs))
    span = (maximum - minimum) or 1.0
    zero_y = top + (maximum / span) * plot_h
    gap = plot_w / len(pairs)
    bar_w = max(20.0, min(76.0, gap * 0.52))

    elements = _axis(width, left, right, top, plot_h, maximum, minimum)
    elements.append(
        f'<line class="zero" x1="{left}" y1="{zero_y:.1f}" x2="{width - right}" y2="{zero_y:.1f}"/>'
    )
    for index, (label, value) in enumerate(pairs):
        x = left + gap * index + (gap - bar_w) / 2
        y = top + ((maximum - max(value, 0.0)) / span) * plot_h
        bar_h = abs(value) / span * plot_h
        if value < 0:
            y = zero_y
        cls = "bar bar--neg" if value < 0 else "bar"
        short = label if len(label) <= 16 else label[:15] + "…"
        value_y = (y - 9) if value >= 0 else (y + bar_h + 17)
        elements.extend([
            f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{max(2.0, bar_h):.1f}" rx="5"/>',
            f'<text class="val" x="{x + bar_w / 2:.1f}" y="{value_y:.1f}" '
            f'text-anchor="middle">{_safe(_compact(value))}</text>',
            f'<text class="lbl" x="{x + bar_w / 2:.1f}" y="{height - 26}" '
            f'text-anchor="middle">{_safe(short)}</text>',
        ])
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="{_safe(visual.get("title") or "Chart")}">{"".join(elements)}</svg>'
    )


def _line_chart(visual: dict) -> str:
    pairs = _pairs(visual, 12)
    if len(pairs) < 2:
        return ""
    width, height = 780, 340
    left, right, top, bottom = 74, 24, 26, 64
    plot_w, plot_h = width - left - right, height - top - bottom
    values = [value for _, value in pairs]
    minimum, maximum = min(values), max(values)
    padding = (maximum - minimum) * 0.12 or max(abs(maximum) * 0.12, 1.0)
    minimum, maximum = minimum - padding, maximum + padding
    span = (maximum - minimum) or 1.0

    points, elements, area = [], _axis(width, left, right, top, plot_h, maximum, minimum), []
    for index, (label, value) in enumerate(pairs):
        x = left + plot_w * index / (len(pairs) - 1)
        y = top + (maximum - value) / span * plot_h
        points.append(f"{x:.1f},{y:.1f}")
        area.append(f"{x:.1f},{y:.1f}")
        if index in {0, len(pairs) - 1} or len(pairs) <= 7:
            short = label if len(label) <= 16 else label[:15] + "…"
            elements.append(
                f'<text class="lbl" x="{x:.1f}" y="{height - 26}" text-anchor="middle">'
                f'{_safe(short)}</text>'
            )
    baseline = top + plot_h
    elements.append(
        f'<polygon class="area" points="{left:.1f},{baseline:.1f} '
        f'{" ".join(area)} {left + plot_w:.1f},{baseline:.1f}"/>'
    )
    elements.append(f'<polyline class="line" points="{" ".join(points)}"/>')
    for index, (_, value) in enumerate(pairs):
        x = left + plot_w * index / (len(pairs) - 1)
        y = top + (maximum - value) / span * plot_h
        elements.extend([
            f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="4.5"/>',
            f'<text class="val" x="{x:.1f}" y="{y - 12:.1f}" text-anchor="middle">'
            f'{_safe(_compact(value))}</text>',
        ])
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="{_safe(visual.get("title") or "Chart")}">{"".join(elements)}</svg>'
    )


def _donut_chart(visual: dict) -> str:
    """Composition: share of a whole. Falls back when values can go negative."""
    pairs = [(l, v) for l, v in _pairs(visual, 6) if v > 0]
    total = sum(v for _, v in pairs)
    if len(pairs) < 2 or total <= 0:
        return ""
    size, radius, thickness = 340, 128, 34
    cx = cy = size / 2
    circumference = 2 * math.pi * radius
    offset, elements = 0.0, []
    for index, (label, value) in enumerate(pairs):
        fraction = value / total
        dash = fraction * circumference
        elements.append(
            f'<circle class="arc arc--{index % 6}" cx="{cx}" cy="{cy}" r="{radius}" '
            f'fill="none" stroke-width="{thickness}" '
            f'stroke-dasharray="{dash:.2f} {circumference - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 {cx} {cy})"/>'
        )
        offset += dash
    top_label, top_value = max(pairs, key=lambda p: p[1])
    elements.append(
        f'<text class="donut-val" x="{cx}" y="{cy - 4}" text-anchor="middle">'
        f'{_safe(_compact(total))}</text>'
        f'<text class="donut-cap" x="{cx}" y="{cy + 18}" text-anchor="middle">Total</text>'
    )
    legend = "".join(
        f'<li><i class="key key--{index % 6}"></i><span>{_safe(label)}</span>'
        f'<b>{_safe(_compact(value))}</b>'
        f'<em>{value / total * 100:.0f}%</em></li>'
        for index, (label, value) in enumerate(pairs)
    )
    return (
        '<div class="donut-wrap">'
        f'<svg viewBox="0 0 {size} {size}" role="img" preserveAspectRatio="xMidYMid meet" '
        f'aria-label="{_safe(visual.get("title") or "Composition")}: largest share '
        f'{_safe(top_label)} at {_safe(_compact(top_value))}">{"".join(elements)}</svg>'
        f'<ul class="legend">{legend}</ul></div>'
    )


def _bullet_chart(visual: dict) -> str:
    """Horizontal ranked bars - reads better than vertical bars for long labels."""
    pairs = _pairs(visual, 8)
    if len(pairs) < 2:
        return ""
    peak = max(abs(v) for _, v in pairs) or 1.0
    rows = []
    for label, value in pairs:
        width = abs(value) / peak * 100.0
        tone = "neg" if value < 0 else "pos"
        rows.append(
            '<li class="blt">'
            f'<span class="blt__lbl" title="{_safe(label)}">{_safe(label)}</span>'
            f'<span class="blt__track"><span class="blt__fill blt__fill--{tone}" '
            f'style="width:{width:.1f}%"></span></span>'
            f'<b class="blt__val">{_safe(_compact(value))}</b></li>'
        )
    return f'<ul class="bullets">{"".join(rows)}</ul>'


_CHART_RENDERERS = {
    "bar": _bar_chart,
    "line": _line_chart,
    "donut": _donut_chart,
    "bullet": _bullet_chart,
}


def _chart_body(visual: dict) -> str:
    """Dispatch on the requested type, degrading to a shape the data supports.

    The type is a *presentation* choice; the data is supplied upstream. An
    unsuitable request (a donut over values that can go negative, a line over
    two points) silently falls back rather than drawing something misleading.
    """
    requested = str(visual.get("type") or "bar").casefold().strip()
    order = [requested] + [k for k in ("bar", "bullet", "line", "donut") if k != requested]
    for kind in order:
        renderer = _CHART_RENDERERS.get(kind)
        if not renderer:
            continue
        svg = renderer(visual)
        if svg:
            return svg
    return ""


# --------------------------------------------------------------------------
# Blocks
# --------------------------------------------------------------------------

def _stat_tiles(metrics: list[dict]) -> str:
    """Metric tiles mirroring the app's kpi-card figure block.

    The value string is injected by code upstream; this only reads its sign to
    pick an arrow, and never re-formats or recomputes the number.
    """
    items = []
    for metric in metrics[:4]:
        tone = _tone(metric.get("tone"), "info")
        value = str(metric.get("value") or "")
        direction = _direction(value)
        arrow = f'<span class="stat__arrow">{_arrow(direction)}</span>' if direction else ""
        items.append(
            f'<article class="stat stat--{tone}">'
            f'<div class="stat__label"><i class="stat__dot"></i>'
            f'<span>{_safe(metric.get("label"))}</span></div>'
            f'<div class="stat__value">{arrow}<span>{_safe(value)}</span></div>'
            "</article>"
        )
    if not items:
        return ""
    return f'<section class="stats" aria-label="Key metrics">{"".join(items)}</section>'


def _pill(tone: str, text: str) -> str:
    return (
        f'<span class="pill pill--{tone}"><i class="pill__dot"></i>{_safe(text)}</span>'
    )


def _sections(sections: list[dict]) -> str:
    regular, actions = [], []
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        bucket = actions if any(t in heading.casefold() for t in ("action", "next step")) else regular
        bucket.append(section)

    panels = []
    for section in regular:
        tone = _tone(section.get("tone"), "info")
        points = "".join(
            f'<li><span class="pt__mark"></span><p>{_safe(point)}</p></li>'
            for point in section.get("points") or []
        )
        panels.append(
            f'<section class="panel panel--{tone}">'
            f'<header class="panel__head">{_pill(tone, section.get("heading"))}</header>'
            f'<ul class="pts">{points}</ul></section>'
        )

    action_html = []
    for section in actions:
        rows = "".join(
            f'<li><span class="step">{index}</span><p>{_safe(point)}</p></li>'
            for index, point in enumerate(section.get("points") or [], start=1)
        )
        action_html.append(
            '<section class="actions">'
            f'<header class="panel__head">{_pill("info", section.get("heading"))}</header>'
            f'<ol class="steps">{rows}</ol></section>'
        )

    grid = f'<div class="panels">{"".join(panels)}</div>' if panels else ""
    return grid + "".join(action_html)


# Theme bridge. The app loads this document into an IFRAME via
# URL.createObjectURL(blob) (see wwwroot/js/AIAssistant/AIAssistant.js), and an
# iframe is a separate document: it does NOT inherit the parent's
# data-theme attribute, so CSS alone can never follow the app's toggle.
#
# Resolution order, highest wins:
#   1. ?theme= / #theme= on the iframe src        (explicit host instruction)
#   2. localStorage['sb-theme']                   (the SAME key _Layout.cshtml
#                                                  writes; readable because a
#                                                  blob: URL inherits the
#                                                  creating page's origin)
#   3. postMessage {type:'sb-theme', theme:'...'} (live toggle, no reload)
#   4. prefers-color-scheme                       (standalone file, CSS-only)
#
# Inline and dependency-free, so the document stays self-contained. Runs in
# <head> before paint to avoid a flash of the wrong theme.
_THEME_SCRIPT = """
(function(){
  var root=document.documentElement;
  function apply(t){ if(t==='dark'||t==='light'){ root.setAttribute('data-theme',t); } }
  try{
    var hash=(location.hash.match(/theme=(dark|light)/)||[])[1];
    var query=new URLSearchParams(location.search).get('theme');
    apply(hash||query||localStorage.getItem('sb-theme'));
  }catch(e){/* opaque origin or storage blocked: fall back to CSS */}
  window.addEventListener('message',function(e){
    var d=e&&e.data; if(d&&d.type==='sb-theme'){ apply(d.theme); }
  });
})();
"""

_STYLE = """
/* ScanB design tokens - mirrors wwwroot/css/theme.css. Keep in sync. */
:root{
  --sb-teal:#2dbdad; --sb-teal-strong:#148D8B; --sb-teal-soft:#f0fdfa;
  --sb-page-bg:#f0f2f4; --sb-surface:#ffffff; --sb-surface-alt:#f8fafc;
  --sb-text:#1a2a2e; --sb-text-muted:#506675; --sb-text-faint:#8a9ba8;
  --sb-critical:#dc2626; --sb-critical-bg:#fef2f2;
  --sb-warning:#d97706;  --sb-warning-bg:#fffbeb;
  --sb-positive:#0f8a7e; --sb-positive-bg:#f0fdfa;
  --sb-info:#2563eb;     --sb-info-bg:#eff6ff;
  --sb-border:#e8edf0; --sb-border-strong:#d7e0e5;
  --sb-radius-sm:6px; --sb-radius:10px; --sb-radius-lg:14px;
  --sb-shadow-sm:0 3px 10px rgba(26,42,46,.08);
  --sb-shadow-md:0 10px 24px rgba(26,42,46,.14);
  --sb-font-sans:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
}
/* Dark: honour the app's attribute AND the OS preference when standalone. */
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --sb-teal:#3ccbb9; --sb-teal-strong:#2dbdad; --sb-teal-soft:rgba(45,189,173,.10);
  --sb-page-bg:#0b1415; --sb-surface:#121d1f; --sb-surface-alt:#182527;
  --sb-text:#edf5f3; --sb-text-muted:#b4c6c2; --sb-text-faint:#7f948f;
  --sb-critical:#f97066; --sb-critical-bg:rgba(249,112,102,.10);
  --sb-warning:#e39a3b;  --sb-warning-bg:rgba(227,154,59,.10);
  --sb-positive:#3ccbb9; --sb-positive-bg:rgba(60,203,185,.10);
  --sb-info:#7cabf8;     --sb-info-bg:rgba(124,171,248,.10);
  --sb-border:#233335; --sb-border-strong:#2e4144;
  --sb-shadow-sm:0 3px 10px rgba(0,0,0,.40); --sb-shadow-md:0 10px 24px rgba(0,0,0,.50);
  color-scheme:dark;
}}
:root[data-theme="dark"]{
  --sb-teal:#3ccbb9; --sb-teal-strong:#2dbdad; --sb-teal-soft:rgba(45,189,173,.10);
  --sb-page-bg:#0b1415; --sb-surface:#121d1f; --sb-surface-alt:#182527;
  --sb-text:#edf5f3; --sb-text-muted:#b4c6c2; --sb-text-faint:#7f948f;
  --sb-critical:#f97066; --sb-critical-bg:rgba(249,112,102,.10);
  --sb-warning:#e39a3b;  --sb-warning-bg:rgba(227,154,59,.10);
  --sb-positive:#3ccbb9; --sb-positive-bg:rgba(60,203,185,.10);
  --sb-info:#7cabf8;     --sb-info-bg:rgba(124,171,248,.10);
  --sb-border:#233335; --sb-border-strong:#2e4144;
  --sb-shadow-sm:0 3px 10px rgba(0,0,0,.40); --sb-shadow-md:0 10px 24px rgba(0,0,0,.50);
  color-scheme:dark;
}

*{box-sizing:border-box}
body{margin:0;background:var(--sb-page-bg);color:var(--sb-text);
  font-family:var(--sb-font-sans);font-size:14px;line-height:1.6;
  -webkit-font-smoothing:antialiased}
.page{max-width:1120px;margin:0 auto;padding:36px 28px 64px}

/* ---------- Header ---------- */
.head{background:var(--sb-surface);border:1px solid var(--sb-border);
  border-radius:16px;padding:26px 28px;box-shadow:var(--sb-shadow-sm);margin-bottom:16px}
.eyebrow{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.eyebrow b{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:var(--sb-teal-strong)}
h1{font-size:clamp(21px,2.6vw,29px);line-height:1.28;letter-spacing:-.022em;
  font-weight:700;margin:0 0 16px;max-width:64ch;color:var(--sb-text)}
.meta{display:flex;gap:8px;flex-wrap:wrap;padding-top:14px;
  border-top:1px solid var(--sb-border)}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;font-weight:550;
  color:var(--sb-text-muted);background:var(--sb-surface-alt);
  border:1px solid var(--sb-border);border-radius:999px;padding:5px 11px}
.chip b{color:var(--sb-text);font-weight:650}

/* ---------- Stat tiles ---------- */
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}
.stat{background:var(--sb-surface);border:1px solid var(--sb-border);
  border-radius:12px;padding:16px 18px;box-shadow:var(--sb-shadow-sm);
  display:flex;flex-direction:column;gap:10px;min-height:104px;
  border-top:3px solid var(--tone,var(--sb-teal))}
.stat--positive{--tone:var(--sb-positive)} .stat--critical{--tone:var(--sb-critical)}
.stat--warning{--tone:var(--sb-warning)}   .stat--info{--tone:var(--sb-info)}
.stat__label{display:flex;align-items:center;gap:7px;font-size:10.5px;font-weight:700;
  letter-spacing:.07em;text-transform:uppercase;color:var(--sb-text-muted);line-height:1.35}
.stat__dot{width:7px;height:7px;border-radius:50%;background:var(--tone);flex:0 0 auto}
.stat__value{display:flex;align-items:center;gap:6px;margin-top:auto;
  font-size:clamp(22px,2.4vw,29px);font-weight:700;letter-spacing:-.03em;
  line-height:1;color:var(--tone);font-variant-numeric:tabular-nums}
.stat__arrow{display:inline-flex}.stat__arrow svg{width:15px;height:15px}

/* ---------- Panels ---------- */
.panels{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:16px}
.panel,.actions{background:var(--sb-surface);border:1px solid var(--sb-border);
  border-radius:14px;padding:18px 20px 8px;box-shadow:var(--sb-shadow-sm)}
.actions{padding-bottom:16px}
.panel__head{margin-bottom:14px}
.pill{display:inline-flex;align-items:center;gap:6px;padding:4px 11px 4px 9px;
  border-radius:999px;font-size:10.5px;font-weight:700;text-transform:uppercase;
  letter-spacing:.07em}
.pill__dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.pill--positive{background:var(--sb-positive-bg);color:var(--sb-positive)}
.pill--critical{background:var(--sb-critical-bg);color:var(--sb-critical)}
.pill--warning{background:var(--sb-warning-bg);color:var(--sb-warning)}
.pill--info{background:var(--sb-info-bg);color:var(--sb-info)}
.pts{margin:0;padding:0;list-style:none}
.pts li{display:grid;grid-template-columns:14px 1fr;gap:10px;align-items:start;
  padding:0 0 14px}
.pt__mark{width:6px;height:6px;border-radius:50%;margin-top:.55em;
  background:var(--sb-border-strong)}
.panel--positive .pt__mark{background:var(--sb-positive)}
.panel--critical .pt__mark{background:var(--sb-critical)}
.panel--warning .pt__mark{background:var(--sb-warning)}
.panel--info .pt__mark{background:var(--sb-info)}
.pts p,.steps p{margin:0;color:var(--sb-text-muted);font-size:13px;line-height:1.6}

/* ---------- Actions ---------- */
.steps{margin:0;padding:0;list-style:none;counter-reset:step}
.steps li{display:grid;grid-template-columns:26px 1fr;gap:12px;align-items:start;
  padding:7px 0;border-bottom:1px solid var(--sb-border)}
.steps li:last-child{border-bottom:0}
.step{display:grid;place-items:center;width:24px;height:24px;border-radius:7px;
  background:var(--sb-teal-soft);color:var(--sb-teal-strong);
  font-size:11.5px;font-weight:700;font-variant-numeric:tabular-nums}

/* ---------- Chart ---------- */
.chart{background:var(--sb-surface);border:1px solid var(--sb-border);
  border-radius:14px;padding:20px 22px 12px;box-shadow:var(--sb-shadow-sm);margin-bottom:16px}
.chart__head{display:flex;justify-content:space-between;align-items:baseline;
  gap:16px;flex-wrap:wrap;margin-bottom:6px}
.chart__head h2{margin:0;font-size:15px;font-weight:700;letter-spacing:-.012em;
  color:var(--sb-text)}
.chart__head span{font-size:11px;font-weight:700;letter-spacing:.07em;
  text-transform:uppercase;color:var(--sb-text-faint)}
svg{display:block;width:100%;height:auto;overflow:visible}
.grid{stroke:var(--sb-border);stroke-width:1}
.zero{stroke:var(--sb-border-strong);stroke-width:1.5}
.bar{fill:var(--sb-teal)} .bar--neg{fill:var(--sb-critical)}
.line{fill:none;stroke:var(--sb-teal);stroke-width:3;
  stroke-linejoin:round;stroke-linecap:round}
.area{fill:var(--sb-teal);opacity:.10}
.dot{fill:var(--sb-surface);stroke:var(--sb-teal);stroke-width:3}
.val{fill:var(--sb-text);font-size:11px;font-weight:650;
  font-variant-numeric:tabular-nums}
.tick{fill:var(--sb-text-faint);font-size:10.5px;font-variant-numeric:tabular-nums}
.lbl{fill:var(--sb-text-muted);font-size:11px}

/* Donut + categorical key. Ordered so adjacent slices stay distinguishable. */
.donut-wrap{display:grid;grid-template-columns:minmax(0,260px) 1fr;gap:24px;
  align-items:center}
.donut-wrap svg{max-width:260px;margin:0 auto}
.arc--0{stroke:var(--sb-teal-strong)} .arc--1{stroke:var(--sb-info)}
.arc--2{stroke:var(--sb-warning)}     .arc--3{stroke:var(--sb-teal)}
.arc--4{stroke:var(--sb-critical)}    .arc--5{stroke:var(--sb-text-faint)}
.donut-val{fill:var(--sb-text);font-size:26px;font-weight:700;
  letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.donut-cap{fill:var(--sb-text-faint);font-size:10.5px;font-weight:700;
  letter-spacing:.1em;text-transform:uppercase}
.legend{margin:0;padding:0;list-style:none}
.legend li{display:grid;grid-template-columns:12px 1fr auto auto;gap:10px;
  align-items:center;padding:7px 0;border-bottom:1px solid var(--sb-border);
  font-size:12.5px}
.legend li:last-child{border-bottom:0}
.legend span{color:var(--sb-text-muted);overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap}
.legend b{color:var(--sb-text);font-weight:650;font-variant-numeric:tabular-nums}
.legend em{color:var(--sb-text-faint);font-style:normal;font-size:11.5px;
  min-width:34px;text-align:right;font-variant-numeric:tabular-nums}
.key{width:10px;height:10px;border-radius:3px}
.key--0{background:var(--sb-teal-strong)} .key--1{background:var(--sb-info)}
.key--2{background:var(--sb-warning)}     .key--3{background:var(--sb-teal)}
.key--4{background:var(--sb-critical)}    .key--5{background:var(--sb-text-faint)}

/* Horizontal ranked bars */
.bullets{margin:6px 0 4px;padding:0;list-style:none}
.blt{display:grid;grid-template-columns:minmax(90px,26%) 1fr auto;gap:14px;
  align-items:center;padding:7px 0}
.blt__lbl{font-size:12.5px;color:var(--sb-text-muted);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.blt__track{height:10px;border-radius:999px;background:var(--sb-surface-alt);
  border:1px solid var(--sb-border);overflow:hidden}
.blt__fill{display:block;height:100%;border-radius:999px}
.blt__fill--pos{background:var(--sb-teal)}
.blt__fill--neg{background:var(--sb-critical)}
.blt__val{font-size:12.5px;font-weight:650;color:var(--sb-text);
  font-variant-numeric:tabular-nums;min-width:56px;text-align:right}
@media (max-width:620px){
  .donut-wrap{grid-template-columns:1fr}
  .blt{grid-template-columns:1fr auto;gap:6px}
  .blt__track{grid-column:1/-1}
}

/* ---------- Narrative + footer ---------- */
.notes{background:var(--sb-surface);border:1px solid var(--sb-border);
  border-radius:14px;padding:18px 20px;box-shadow:var(--sb-shadow-sm);margin-bottom:16px}
.notes h2{margin:0 0 10px;font-size:11px;font-weight:700;letter-spacing:.1em;
  text-transform:uppercase;color:var(--sb-text-faint)}
.notes p{margin:0 0 10px;color:var(--sb-text-muted);font-size:13px;max-width:78ch}
.notes p:last-child{margin-bottom:0}
footer{color:var(--sb-text-faint);font-size:11.5px;line-height:1.6;
  padding:6px 4px 0;max-width:88ch}

@media (max-width:900px){
  .stats{grid-template-columns:repeat(2,minmax(0,1fr))}
  .panels{grid-template-columns:1fr}
}
@media (max-width:560px){
  .page{padding:20px 14px 44px}
  .stats{grid-template-columns:1fr}
  .head,.panel,.actions,.chart,.notes{padding-left:16px;padding-right:16px}
}
@media print{
  body{background:#fff}
  .page{max-width:none;padding:0}
  .head,.stat,.panel,.actions,.chart,.notes{box-shadow:none;break-inside:avoid}
  .stats,.panels{break-inside:avoid}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


def render(summary: dict, title: str = "AI Summary") -> str:
    """Convert the validated fresh-summary payload into a standalone HTML page."""
    visual = summary.get("visual") or {}
    svg = _chart_body(visual) if visual else ""

    freshness = str(summary.get("freshness_status") or "unknown").replace("_", " ").title()
    grain = str(summary.get("grain") or "snapshot").replace("_", " ").title()
    data_as_of = summary.get("data_as_of") or "Unknown"
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    validation = str(summary.get("validation_status") or "").replace("_", " ").strip()

    status_tone = {"current": "positive", "delayed": "warning", "stale": "critical"}.get(
        str(summary.get("freshness_status") or "").casefold(), "info"
    )

    stats = _stat_tiles(list(summary.get("metrics") or []))
    body = _sections(list(summary.get("sections") or []))

    chart = ""
    if svg:
        chart = (
            '<section class="chart"><div class="chart__head">'
            f'<h2>{_safe(visual.get("title") or "Supporting view")}</h2>'
            f'<span>{_safe(visual.get("value_label") or "")}</span></div>{svg}</section>'
        )

    notes = ""
    paragraphs = [p for p in (summary.get("paragraphs") or []) if str(p).strip()]
    if paragraphs:
        rendered = "".join(f"<p>{_safe(p)}</p>" for p in paragraphs)
        notes = f'<section class="notes"><h2>Detail</h2>{rendered}</section>'

    badge = _pill(status_tone, freshness)
    validated = (
        f'<span class="chip"><b>{_safe(validation.title())}</b></span>' if validation else ""
    )

    return (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_safe(title)}</title>"
        f"<script>{_THEME_SCRIPT}</script>"
        f"<style>{_STYLE}</style></head><body>"
        '<main class="page">'
        '<header class="head">'
        f'<div class="eyebrow"><b>{_safe(title)}</b>{badge}</div>'
        f'<h1>{_safe(summary.get("heading"))}</h1>'
        '<div class="meta">'
        f'<span class="chip">Data through&nbsp;<b>{_safe(data_as_of)}</b></span>'
        f'<span class="chip">Grain&nbsp;<b>{_safe(grain)}</b></span>'
        f'<span class="chip">Generated&nbsp;<b>{_safe(generated)}</b></span>'
        f"{validated}"
        "</div></header>"
        f"{stats}{chart}{body}{notes}"
        "<footer>Generated automatically from the connected Power BI semantic model. "
        "Figures reflect only the queries executed in this run and the business rules "
        "in force at the time; see the accompanying insight report for coverage gaps."
        "</footer>"
        "</main></body></html>"
    )
