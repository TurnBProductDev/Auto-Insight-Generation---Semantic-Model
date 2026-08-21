"""Inventory chart primitives - inline SVG, no library, no external request.

Why this module exists
----------------------
The inventory pages shipped with KPI cards, tables and prose and **no charts at
all** (the sales dashboard renders 30 SVGs; these rendered zero). Numbers in a
table are read one at a time; a stock position is a *shape* - most of the money
fresh, a tail that is old, a queue where the biggest number is not the most
urgent - and a shape has to be drawn.

Conventions inherited from the sales renderer, deliberately
-----------------------------------------------------------
Every mark carries ``class="data-point" tabindex="0" data-label data-value`` and
sits inside a ``.chart-stage`` with a ``.chart-tooltip`` span, which is what the
shared ``_script()`` already binds hover and keyboard focus to. So these charts
are interactive for free and cannot drift from the sales page's behaviour.

Colour follows the job, not taste
---------------------------------
- **Two-series comparisons** use TEAL (still fine) against AMBER (aged / above
  cover). That exact pair was run through the palette validator and passes all
  six checks against this page's white surface - lightness band, chroma floor,
  CVD separation (worst adjacent dE 13.0 protan), normal-vision floor (19.8) and
  3:1 contrast. Both are already the design system's own colours, so nothing new
  was introduced to get there.
- **Status** (critical / watch / steady) is a reserved palette and is never used
  as "another series". It always ships beside a text label, never colour alone,
  because red-green is precisely the pair a deutan reader cannot separate.
- A single series gets one colour and no legend; the title names it.

Axes start at zero here. The sales waterfall floats its axis because lever
effects are a few percent of a total and would otherwise be invisible slivers;
these charts plot whole quantities where zero is the honest baseline.
"""

from __future__ import annotations

from typing import Any, Sequence

from . import money

from ...tools.summary_dashboard_html import (
    AMBER,
    FAINT,
    GRID,
    INK,
    MUTED,
    NEG,
    POS,
    TEAL,
    TEAL_DARK,
    _safe,
)

#: The validated two-series pair. See the module docstring.
SERIES_CALM = TEAL
SERIES_FLAG = AMBER

TONE_FILL = {
    "critical": NEG,
    "warn": AMBER,
    "positive": POS,
    "neutral": FAINT,
}


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _sar(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "-"
    if abs(number) >= 1_000_000:
        return f"{money.CURRENCY} {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{money.CURRENCY} {number / 1_000:.0f}K"
    return f"{money.CURRENCY} {number:,.0f}"


def _pct(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.1f}%"


def _count(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _stage(svg: str, note: str = "") -> str:
    """Wrap a chart so the shared tooltip script picks its marks up."""
    footer = f'<p class="chart-note">{_safe(note)}</p>' if note else ""
    return (f'<div class="chart-stage">{svg}'
            f'<span class="chart-tooltip" role="status"></span></div>{footer}')


def _legend(items: Sequence[tuple]) -> str:
    """Always present for two or more series - identity is never colour alone."""
    if len(items) < 2:
        return ""
    keys = "".join(
        f'<span class="lg-key"><i style="background:{color}"></i>{_safe(label)}</span>'
        for label, color in items
    )
    return f'<div class="chart-legend">{keys}</div>'


# --- Stock Age Analysis -------------------------------------------------------

def age_columns(bands: Sequence[dict]) -> str:
    """Where the money is sitting, by age, with the aged portion inside each bar.

    The single most useful chart on the ageing page, because it shows the thing a
    table cannot: the shape of the tail, and the fact that ``06-09 MONTHS`` is
    only *partly* aged. That partial band is not a rounding artefact - it is the
    division-sensitive threshold made visible (BR-16: food crosses at six months,
    everything else at nine), so the same band is aged for some divisions and not
    for others.

    Stacked rather than grouped: the two parts sum to the band, and the reader's
    question is "how much of this band is a problem", which is a part-of-whole.
    """
    usable = [b for b in bands or [] if (_num(b.get("value")) or 0.0) > 0]
    if len(usable) < 2:
        return ""

    width, height = 640, 250
    pad_l, pad_r, pad_t, pad_b = 10, 10, 30, 54
    plot_h = height - pad_t - pad_b
    gap = 16
    bar_w = (width - pad_l - pad_r - (len(usable) - 1) * gap) / len(usable)
    ceiling = max(_num(b.get("value")) or 0.0 for b in usable) * 1.16 or 1.0
    scale = plot_h / ceiling
    base_y = pad_t + plot_h

    parts: list[str] = []
    # Recessive gridlines, drawn first so marks sit above them.
    for step in range(1, 4):
        y = base_y - plot_h * step / 4
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')

    for index, band in enumerate(usable):
        total = _num(band.get("value")) or 0.0
        aged = min(_num(band.get("aged_value")) or 0.0, total)
        calm = max(total - aged, 0.0)
        name = str(band.get("name") or "")
        x = pad_l + index * (bar_w + gap)

        calm_h = calm * scale
        aged_h = aged * scale
        # A 2px surface gap between stacked segments, so the boundary is read as
        # a boundary rather than as a colour change inside one solid block.
        # A visibility floor, not a scale distortion: on the live shape the
        # oldest band is 1.5% of stock and computes to under 2px, so the one
        # band BR-28 says to lead with was the least visible mark on the chart.
        # Every bar carries its exact value as a direct label, so the floor
        # cannot mislead about magnitude - it only guarantees the mark is there.
        floor_h = 3.0
        cursor = base_y
        if calm_h > 0:
            y = cursor - max(calm_h, floor_h)
            parts.append(
                f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{max(calm_h, floor_h):.1f}" rx="3" '
                f'fill="{SERIES_CALM}" data-label="{_safe(name)} - not yet aged" '
                f'data-value="{_safe(_sar(calm))}">'
                f'<title>{_safe(name)} not yet aged: {_safe(_sar(calm))}</title></rect>')
            cursor = y - 2
        if aged_h > 0:
            y = cursor - max(aged_h, floor_h)
            parts.append(
                f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{y:.1f}" '
                f'width="{bar_w:.1f}" height="{max(aged_h, floor_h):.1f}" rx="3" '
                f'fill="{SERIES_FLAG}" data-label="{_safe(name)} - aged" '
                f'data-value="{_safe(_sar(aged))}">'
                f'<title>{_safe(name)} aged: {_safe(_sar(aged))}</title></rect>')
            cursor = y

        # Direct label on the total only - a number on every segment is noise.
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{cursor - 7:.1f}" text-anchor="middle" '
            f'class="dz-val">{_safe(_sar(total))}</text>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
            f'class="dz-axis">{_safe(name)}</text>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{base_y + 28:.1f}" text-anchor="middle" '
            f'class="dz">{_safe(_pct(band.get("share_pct")))} of stock</text>')
        # Status marker, with its word beside it. BR-17: over a year is high-risk
        # for every division, so it is flagged regardless of the aged threshold.
        if band.get("high_risk"):
            parts.append(
                f'<rect x="{x:.1f}" y="{base_y + 33:.1f}" width="{bar_w:.1f}" '
                f'height="2.5" rx="1.2" fill="{NEG}"/>')
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{base_y + 45:.1f}" '
                f'text-anchor="middle" class="dz-flag">high-risk</text>')

    parts.append(f'<line x1="{pad_l}" y1="{base_y:.1f}" x2="{width - pad_r}" '
                 f'y2="{base_y:.1f}" stroke="{MUTED}" stroke-width="1"/>')

    svg = (f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'preserveAspectRatio="xMidYMid meet" role="img" '
           f'aria-label="Stock value by age band, showing the aged portion of each band">'
           f'{"".join(parts)}</svg>')

    return (_legend([("Not yet aged", SERIES_CALM), ("Aged", SERIES_FLAG)])
            + _stage(svg,
                     "The 06-09 month band is only partly aged because food "
                     "crosses the aged threshold at six months and every other "
                     "division at nine."))


def cumulative_curve(bands: Sequence[dict]) -> str:
    """"How much of the stock is older than this?" - one reading per band.

    This is the AGE_ABOVE idea the rulebook already works in (BR-14, BR-24): the
    cumulative share of stock at or beyond each age. It answers the question the
    column chart cannot, because the columns are dominated by the fresh band -
    62% of the value sits in the first bar, which squeezes the tail that the
    report is actually about.

    Plotted as a share, not a value, so the two charts cannot be confused for
    each other or read off the same axis.
    """
    usable = [b for b in bands or []
              if _num(b.get("cumulative_older_pct")) is not None]
    if len(usable) < 3:
        return ""
    width, height = 640, 190
    pad_l, pad_r, pad_t, pad_b = 12, 12, 26, 44
    plot_h = height - pad_t - pad_b
    base_y = pad_t + plot_h
    step = (width - pad_l - pad_r) / max(len(usable) - 1, 1)
    values = [_num(b.get("cumulative_older_pct")) or 0.0 for b in usable]

    def y_of(pct: float) -> float:
        return base_y - (pct / 100.0) * plot_h

    coords = [(pad_l + i * step, y_of(v)) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (f"{coords[0][0]:.1f},{base_y:.1f} " + line +
            f" {coords[-1][0]:.1f},{base_y:.1f}")

    parts: list[str] = []
    for pct in (25, 50, 75):
        y = y_of(pct)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{width - pad_r}" y="{y - 3:.1f}" text-anchor="end" '
                     f'class="dz">{pct}%</text>')
    parts.append(f'<polygon points="{area}" fill="{TEAL}" opacity="0.13"/>')
    parts.append(f'<polyline points="{line}" fill="none" stroke="{TEAL_DARK}" '
                 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    for index, (x, y) in enumerate(coords):
        name = str(usable[index].get("name") or "")
        parts.append(
            f'<circle class="data-point" tabindex="0" cx="{x:.1f}" cy="{y:.1f}" '
            f'r="4.5" fill="{TEAL_DARK}" stroke="#fff" stroke-width="2" '
            f'data-label="{_safe(name)} or older" '
            f'data-value="{_safe(_pct(values[index]))} of all stock">'
            f'<title>{_safe(name)} or older: {_safe(_pct(values[index]))}</title>'
            '</circle>')
        parts.append(
            f'<text x="{x:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
            f'class="dz-axis">{_safe(name)}</text>')
    # Label the two ends only; the rest are on hover.
    for index in (0, len(coords) - 1):
        x, y = coords[index]
        anchor = "start" if index == 0 else "end"
        parts.append(
            f'<text x="{x:.1f}" y="{y - 10:.1f}" text-anchor="{anchor}" '
            f'class="dz-val">{_safe(_pct(values[index]))}</text>')
    parts.append(f'<line x1="{pad_l}" y1="{base_y:.1f}" x2="{width - pad_r}" '
                 f'y2="{base_y:.1f}" stroke="{MUTED}" stroke-width="1"/>')
    svg = (f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'preserveAspectRatio="xMidYMid meet" role="img" '
           f'aria-label="Share of stock value at or older than each age band">'
           f'{"".join(parts)}</svg>')
    return _stage(svg, "Read it as: this share of all stock value is in this "
                       "band or an older one.")


def risk_matrix(split: dict, total: float) -> str:
    """Aged and not-selling are two independent questions, so there are four answers.

    Drawn as a 2x2 rather than a chart because that *is* the shape of the idea,
    and because the report's most important single figure - old stock that is
    also not selling - is one cell of it. BR-19 forbids adding the aged total to
    the not-selling total; a matrix makes the overlap impossible to add by
    accident, which a pair of bars does not.

    HTML rather than SVG so it reflows on a phone and prints cleanly.
    """
    if not split:
        return ""
    cells = [
        ("Aged", "Not selling", split.get("aged_non_moving"), "critical",
         "Old stock with no sales. The write-off candidates."),
        ("Aged", "Still selling", split.get("aged_moving"), "warn",
         "Old, but moving. May clear on its own."),
        ("Not aged", "Not selling", split.get("fresh_non_moving"), "warn",
         "Fresh with no sales. A demand or placement problem, not an age one."),
        ("Not aged", "Still selling", split.get("fresh_moving"), "positive",
         "Healthy stock, turning normally."),
    ]
    body = ""
    for age, motion, value, tone, note in cells:
        number = _num(value) or 0.0
        share = (number / total * 100.0) if total else None
        body += (
            f'<div class="rm-cell rm-{tone}">'
            f'<span class="rm-tag">{_safe(age)} &middot; {_safe(motion)}</span>'
            f'<strong class="rm-val">{_safe(_sar(number))}</strong>'
            f'<span class="rm-share">{_safe(_pct(share))} of all stock</span>'
            f'<p class="rm-note">{_safe(note)}</p>'
            '</div>')
    return (f'<div class="risk-matrix">{body}</div>'
            '<p class="chart-note">These four add to the total. Aged and not '
            'selling overlap, so the aged figure and the not-selling figure are '
            'never added together.</p>')


def split_bars(rows: Sequence[dict], value_key: str, total_key: str,
               label_key: str = "name") -> str:
    """Two populations compared on both size and severity - LOCAL against OVERSEAS.

    Two bars per member on one shared scale: what it holds, and how much of that
    is aged. Not a donut: the question is "does imported stock age more?", which
    is a comparison of rates, and a donut can only show one share at a time.
    """
    usable = [r for r in rows or [] if (_num(r.get(total_key)) or 0.0) > 0]
    if len(usable) < 2:
        return ""
    peak = max(_num(r.get(total_key)) or 0.0 for r in usable) or 1.0
    body = ""
    for row in usable:
        held = _num(row.get(total_key)) or 0.0
        flagged = _num(row.get(value_key)) or 0.0
        rate = (flagged / held * 100.0) if held else 0.0
        body += (
            '<div class="sb-row">'
            f'<div class="sb-lab">{_safe(row.get(label_key))}'
            f'<small>{_safe(_pct(rate))} of it aged</small></div>'
            '<div class="sb-track">'
            f'<span class="sb-held" style="width:{held / peak * 100:.2f}%">'
            f'<span class="sb-aged" style="width:{(flagged / held * 100) if held else 0:.2f}%"></span>'
            '</span></div>'
            f'<div class="sb-val">{_safe(_sar(held))}<small>{_safe(_sar(flagged))} aged</small></div>'
            '</div>')
    return (_legend([("Stock held", SERIES_CALM), ("Of which aged", SERIES_FLAG)])
            + f'<div class="split-bars">{body}</div>')


# --- Inventory Management -----------------------------------------------------

def queue_ladder(queue: Sequence[dict]) -> str:
    """The action queue as a ladder, in urgency order rather than by size.

    This is the chart that carries the whole report, because it makes the
    report's central claim visible in one look: **the biggest bar is not at the
    top**. OVERSTOCK holds by far the most value and sits eighth; 17,717 lines
    with no stock, no warehouse cover and no order placed sit first. Sorting by
    value - the default any chart tool would give you - would destroy exactly the
    judgement BR-31 asks for.

    Bars are line counts, because the queue is work to be done and the unit of
    work is a product line, not a riyal. The value rides along in the label.
    """
    usable = [r for r in queue or [] if int(r.get("loc_skus") or 0) > 0]
    if not usable:
        return ""
    peak = max(int(r.get("loc_skus") or 0) for r in usable) or 1

    body = ""
    for row in usable:
        lines = int(row.get("loc_skus") or 0)
        action = str(row.get("action") or "")
        if row.get("double_warning"):
            tone, tone_word = "critical", "most urgent"
        elif row.get("is_exception"):
            tone, tone_word = "warn", "needs action"
        else:
            tone, tone_word = "neutral", "no action"
        flag = (f'<span class="ql-flag ql-{tone}">{_safe(tone_word)}</span>'
                if tone != "neutral" else
                f'<span class="ql-flag ql-quiet">{_safe(tone_word)}</span>')
        body += (
            f'<div class="ql-row">'
            f'<div class="ql-lab">{_safe(action)}{flag}</div>'
            '<div class="ql-track">'
            f'<span class="ql-fill" style="width:{lines / peak * 100:.2f}%;'
            f'background:{TONE_FILL[tone]}" title="{_safe(action)}: '
            f'{_safe(_count(lines))} lines"></span></div>'
            f'<div class="ql-val">{_safe(_count(lines))}'
            f'<small>{_safe(_sar(row.get("stock_value")))}</small></div>'
            '</div>')

    return (f'<div class="queue-ladder">{body}</div>'
            '<p class="chart-note">Ordered by how urgent the situation is, not '
            'by how much money it holds. The largest bar is deliberately not at '
            'the top.</p>')


def duration_columns(bands: Sequence[dict]) -> str:
    """How long stock has gone without a sale. One series, so no legend.

    The oldest band is marked as status - with its word, not just its colour -
    because a long tail here is the write-off warning, and on the live model
    ">180" is both the largest band and the worst.
    """
    usable = [b for b in bands or [] if int(b.get("loc_skus") or 0) > 0]
    if len(usable) < 2:
        return ""
    width, height = 640, 200
    pad_l, pad_r, pad_t, pad_b = 10, 10, 26, 46
    plot_h = height - pad_t - pad_b
    gap = 16
    bar_w = (width - pad_l - pad_r - (len(usable) - 1) * gap) / len(usable)
    ceiling = max(int(b.get("loc_skus") or 0) for b in usable) * 1.18 or 1
    scale = plot_h / ceiling
    base_y = pad_t + plot_h
    worst = usable[-1].get("name")

    parts: list[str] = []
    for step in range(1, 4):
        y = base_y - plot_h * step / 4
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" '
                     f'y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')

    for index, band in enumerate(usable):
        lines = int(band.get("loc_skus") or 0)
        name = str(band.get("name") or "")
        x = pad_l + index * (bar_w + gap)
        bar_h = max(lines * scale, 2.0)
        y = base_y - bar_h
        fill = NEG if name == worst else AMBER
        parts.append(
            f'<rect class="data-point" tabindex="0" x="{x:.1f}" y="{y:.1f}" '
            f'width="{bar_w:.1f}" height="{bar_h:.1f}" rx="3" fill="{fill}" '
            f'data-label="{_safe(name)} days without a sale" '
            f'data-value="{_safe(_count(lines))} lines, {_safe(_sar(band.get("stock_value")))}">'
            f'<title>{_safe(name)} days: {_safe(_count(lines))} lines</title></rect>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'class="dz-val">{_safe(_sar(band.get("stock_value")))}</text>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
            f'class="dz-axis">{_safe(name)}</text>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{base_y + 28:.1f}" text-anchor="middle" '
            f'class="dz">{_safe(_count(lines))} lines</text>')
        if name == worst:
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{base_y + 40:.1f}" '
                f'text-anchor="middle" class="dz-flag">longest stalled</text>')

    parts.append(f'<line x1="{pad_l}" y1="{base_y:.1f}" x2="{width - pad_r}" '
                 f'y2="{base_y:.1f}" stroke="{MUTED}" stroke-width="1"/>')
    svg = (f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'preserveAspectRatio="xMidYMid meet" role="img" '
           f'aria-label="Product lines by days without a sale">{"".join(parts)}</svg>')
    return _stage(svg, "Days without a sale, across every location and product.")


def trend_area(points: Sequence[dict], label_key: str, value_key: str,
               caption: str = "") -> str:
    """A short monthly series - stock written off. One series, area under the line.

    Kept small and honest: with four points this is a shape, not a trend line to
    extrapolate from, so there is no fitted slope and no forecast.
    """
    usable = [p for p in points or [] if _num(p.get(value_key)) is not None]
    if len(usable) < 3:
        return ""
    width, height = 640, 170
    pad_l, pad_r, pad_t, pad_b = 12, 12, 24, 38
    plot_h = height - pad_t - pad_b
    values = [_num(p.get(value_key)) or 0.0 for p in usable]
    ceiling = max(values) * 1.2 or 1.0
    step = (width - pad_l - pad_r) / max(len(usable) - 1, 1)
    base_y = pad_t + plot_h

    def y_of(value: float) -> float:
        return base_y - (value / ceiling) * plot_h

    coords = [(pad_l + i * step, y_of(v)) for i, v in enumerate(values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (f"{coords[0][0]:.1f},{base_y:.1f} " + line +
            f" {coords[-1][0]:.1f},{base_y:.1f}")

    parts = [f'<polygon points="{area}" fill="{AMBER}" opacity="0.14"/>',
             f'<polyline points="{line}" fill="none" stroke="{AMBER}" '
             'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>']
    for index, (x, y) in enumerate(coords):
        label = str(usable[index].get(label_key) or "")
        parts.append(
            f'<circle class="data-point" tabindex="0" cx="{x:.1f}" cy="{y:.1f}" '
            f'r="4.5" fill="{AMBER}" stroke="#fff" stroke-width="2" '
            f'data-label="{_safe(label)}" data-value="{_safe(_sar(values[index]))}">'
            f'<title>{_safe(label)}: {_safe(_sar(values[index]))}</title></circle>')
        parts.append(
            f'<text x="{x:.1f}" y="{base_y + 16:.1f}" text-anchor="middle" '
            f'class="dz-axis">{_safe(label)}</text>')
    # Label the peak only - a number on every point is noise.
    peak_index = values.index(max(values))
    parts.append(
        f'<text x="{coords[peak_index][0]:.1f}" y="{coords[peak_index][1] - 10:.1f}" '
        f'text-anchor="middle" class="dz-val">{_safe(_sar(max(values)))}</text>')
    parts.append(f'<line x1="{pad_l}" y1="{base_y:.1f}" x2="{width - pad_r}" '
                 f'y2="{base_y:.1f}" stroke="{MUTED}" stroke-width="1"/>')
    svg = (f'<svg viewBox="0 0 {width} {height}" width="100%" '
           f'preserveAspectRatio="xMidYMid meet" role="img" '
           f'aria-label="{_safe(caption or "Monthly series")}">{"".join(parts)}</svg>')
    return _stage(svg, caption)


# --- shared ------------------------------------------------------------------

def ranked_bars(rows: Sequence[dict], *, value_key: str, held_key: str,
                label_key: str = "name", unit: str = "aged",
                average: float | None = None,
                average_label: str = "") -> str:
    """Members ranked by one measure, each with its own severity beside it.

    Two things at once, because either alone misleads: the **bar** is how much a
    member holds (so a warehouse dominates), and the **percentage** is how much
    of that member's own stock it is (so a small store with a bad ratio is still
    visible). BR-23 makes the second the one to judge severity on.

    The reference line is the company-wide rate, so "worse than the estate" is a
    position on the page rather than a calculation the reader has to do.
    """
    usable = [r for r in rows or [] if (_num(r.get(value_key)) or 0.0) > 0]
    if not usable:
        return ""
    usable = sorted(usable, key=lambda r: _num(r.get(value_key)) or 0.0, reverse=True)
    peak = max(_num(r.get(value_key)) or 0.0 for r in usable) or 1.0

    ref = ""
    if average is not None:
        ref = (f'<p class="chart-note">The company-wide {_safe(unit)} rate is '
               f'{_safe(_pct(average))}'
               f'{(" - " + _safe(average_label)) if average_label else ""}. '
               f'A rate marked in red is worse than that.</p>')

    body = ""
    for row in usable:
        value = _num(row.get(value_key)) or 0.0
        held = _num(row.get(held_key)) or 0.0
        own = (value / held * 100.0) if held else None
        # The bar length encodes the absolute value, so the comparison against
        # the estate rate cannot live on the bar - it is a different measure.
        # It is carried on the rate text instead, where the number it judges is,
        # and the word "worse" is written out in the note so the meaning is never
        # colour alone.
        worse = own is not None and average is not None and own > average
        tone = "worse" if worse else "level"
        body += (
            '<div class="rb-row">'
            f'<div class="rb-lab">{_safe(row.get(label_key))}'
            f'<small>{_safe(_sar(held))} held here</small></div>'
            '<div class="rb-track">'
            f'<span class="rb-fill" style="width:{value / peak * 100:.2f}%;'
            f'background:{SERIES_FLAG}" title="{_safe(row.get(label_key))}: '
            f'{_safe(_sar(value))}"></span></div>'
            f'<div class="rb-val">{_safe(_sar(value))}'
            f'<small class="rb-{tone}">{_safe(_pct(own))} of its own stock</small>'
            '</div></div>')
    return f'<div class="ranked-bars">{body}</div>{ref}'


def composition_donut(parts: Sequence[dict], center_top: str,
                      center_bottom: str) -> str:
    """A complete, non-negative composition - lines needing action against the rest."""
    usable = [p for p in parts or [] if (_num(p.get("value")) or 0.0) > 0]
    if len(usable) < 2:
        return ""
    import math

    total = sum(_num(p["value"]) or 0.0 for p in usable)
    size, radius, stroke = 168, 66, 20
    center = size / 2
    circumference = 2 * math.pi * radius
    offset = 0.0
    arcs: list[str] = []
    for part in usable:
        value = _num(part["value"]) or 0.0
        # A 2px surface gap between segments so adjacent fills read as separate.
        length = max(value / total * circumference - 2.0, 0.5)
        arcs.append(
            f'<circle class="data-point" tabindex="0" cx="{center}" cy="{center}" '
            f'r="{radius}" fill="none" stroke="{part.get("color") or TEAL}" '
            f'stroke-width="{stroke}" '
            f'stroke-dasharray="{length:.2f} {circumference - length:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {center} {center})" '
            f'data-label="{_safe(part.get("label"))}" '
            f'data-value="{_safe(_count(value))} lines">'
            f'<title>{_safe(part.get("label"))}: {_safe(_count(value))}</title></circle>')
        offset += length + 2.0
    middle = (
        f'<text x="{center}" y="{center - 2}" text-anchor="middle" '
        f'class="donut-total">{_safe(center_top)}</text>'
        f'<text x="{center}" y="{center + 15}" text-anchor="middle" '
        f'class="dz">{_safe(center_bottom)}</text>')
    svg = (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
           f'role="img" aria-label="{_safe(center_bottom)}">'
           f'{"".join(arcs)}{middle}</svg>')
    legend = _legend([(str(p.get("label")), str(p.get("color") or TEAL))
                      for p in usable])
    return f'<div class="donut-wrap">{svg}{legend}</div>'
