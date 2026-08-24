"""Generate the Daily Sales reference dashboard.

Same shell as reference_target_tracker.html and the two inventory references: rail +
main and nothing else inside .app, four layers, two views, `#<view>/<layer>` in the URL
so a tab is linkable and a screenshot tool can reach it without a click.

What differs is the drill axis. The Target Tracker page drills through *time*, because its
priority order is Daily -> WTD -> MTD -> YTD. This one drills through the *hierarchy* -
Store -> Department -> Section -> Category - because its rulebook (BR-07) defines four
levels each owning its own benchmark table, and (BR-15) says to investigate a measure that
lands outside its band in two directions: across the other measures at the same level, and
down to the level below.

Every figure comes from daily_sales_facts.build(), which refuses to produce facts at all
unless the model reconciles. This module adds its own asserts on top - the store split, the
Bills x Basket Value decomposition - so a wrong number fails the build rather than shipping.

    python docs/dashboard-reference/build_daily_sales_reference.py
"""
from __future__ import annotations

import html
from pathlib import Path

import daily_sales_facts as F
from daily_sales_facts import ABOVE, BELOW, IN

OUT = Path(__file__).resolve().with_name("reference_daily_sales.html")
CUR = "SAR"

TEAL, TEAL_DK, AMBER, AMBER_DK = "#0f9f95", "#087f79", "#c08429", "#8a5f10"
RED, GREEN, FAINT, INK = "#cf4636", "#2f8f4e", "#8fa1a9", "#12201e"

# BR-05 is the whole severity convention: only the exceptions get colour, and the
# colour is never alone - every one of these is printed with its word beside it.
VCLS = {BELOW: "crit", IN: "", ABOVE: "good"}
VPILL = {BELOW: ("crit", "Underperforming"), IN: ("neutral", "In band"),
         ABOVE: ("ok", "Outperforming")}
VCOL = {BELOW: RED, IN: INK, ABOVE: GREEN}

FACTS = F.build()


# ------------------------------------------------------------- formatting ---

def e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def money(v, dp=None) -> str:
    v = float(v)
    a = abs(v)
    if dp is not None:
        return f"{v:,.{dp}f}"
    if a >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if a >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.2f}"


def sar(v, dp=None) -> str:
    return f"{CUR}&nbsp;{money(v, dp)}"


def sar_plain(v, dp=None) -> str:
    """SVG text has no HTML entities - a non-breaking space would print as SAR&nbsp;."""
    return f"{CUR} {money(v, dp)}"


def signed_sar(v, dp=None) -> str:
    s = "+" if float(v) >= 0 else "&minus;"
    return f"{s}{CUR}&nbsp;{money(abs(float(v)), dp)}"


def signed_sar_plain(v, dp=None) -> str:
    s = "+" if float(v) >= 0 else "−"
    return f"{s}{CUR} {money(abs(float(v)), dp)}"


def num(v) -> str:
    return f"{int(round(float(v))):,}"


def signed_num(v) -> str:
    v = float(v)
    return ("+" if v >= 0 else "&minus;") + f"{abs(int(round(v))):,}"


def pc(v, dp=1) -> str:
    return f"{float(v):.{dp}f}%"


def signed_pc(v, dp=1) -> str:
    v = float(v)
    return ("+" if v >= 0 else "&minus;") + f"{abs(v):.{dp}f}%"


def pp(v, dp=2) -> str:
    """Percentage points - margin moves in points, never in percent."""
    v = float(v)
    return ("+" if v >= 0 else "&minus;") + f"{abs(v):.{dp}f} points"


def val(r: F.Reading, dp=None) -> str:
    """One reading's actual, in its own unit."""
    if r.actual is None:
        return "&mdash;"
    if r.unit == "money":
        return sar(r.actual, dp if dp is not None else (2 if r.key == "basket" else None))
    if r.unit == "count":
        return num(r.actual)
    return pc(r.actual, 2)


def band_text(r: F.Reading, dp=None) -> str:
    if r.p20 is None:
        return "no benchmark"
    if r.unit == "money":
        d = dp if dp is not None else (2 if r.key == "basket" else None)
        return f"{money(r.p20, d)} to {money(r.p80, d)}"
    if r.unit == "count":
        return f"{num(r.p20)} to {num(r.p80)}"
    return f"{pc(r.p20, 2)} to {pc(r.p80, 2)}"


def gap_text(r: F.Reading, dp=None) -> str:
    """BR-18: never 'well below' on its own - always the figure and the edge."""
    v = r.verdict
    if v == IN:
        edge = r.on_edge
        return f"level with its P20 floor" if edge == "floor" else (
            "level with its P80 ceiling" if edge == "ceiling" else "inside the normal band")
    edge = "P20 floor" if v == BELOW else "P80 ceiling"
    if r.unit == "money":
        d = dp if dp is not None else (2 if r.key == "basket" else None)
        return f"{signed_sar(r.gap, d)} against its {edge}"
    if r.unit == "count":
        return f"{signed_num(r.gap)} against its {edge}"
    return f"{pp(r.gap)} against its {edge}"


def vs_bench(r: F.Reading, dp=None) -> str:
    if r.vs_p50 is None:
        return ""
    if r.unit == "pct":
        return f"{pp(r.vs_p50)} against the benchmark {pc(r.p50, 2)}"
    if r.unit == "count":
        return f"{signed_num(r.vs_p50)} against the benchmark {num(r.p50)}"
    d = dp if dp is not None else (2 if r.key == "basket" else None)
    return f"{signed_sar(r.vs_p50, d)} against the benchmark {sar(r.p50, d)}"


# ------------------------------------------------------------- components ---

def pill(r: F.Reading) -> str:
    k, word = VPILL[r.verdict] if r.verdict else ("neutral", "Not comparable")
    return f'<span class="pill pill-{k}">{word}</span>'


def bullet(r: F.Reading, width=250, height=30) -> str:
    """The band bullet: the normal band as a track, the benchmark as a tick, the day
    as a marker. This is the report's own argument in one shape (BR-04, BR-05)."""
    if r.p20 is None or r.actual is None:
        return ""
    half = (r.p80 - r.p20) / 2 * 1.9 or 1.0
    lo = min(r.p50 - half, r.actual)
    hi = max(r.p50 + half, r.actual)
    span = (hi - lo) or 1.0
    x = lambda v: 6 + (v - lo) / span * (width - 12)
    cy, bh = height / 2, 11
    col = VCOL[r.verdict]
    return (
        f'<svg class="bul" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" role="img" aria-label="{e(r.label)} {e(val(r))}, {e(gap_text(r))}">'
        f'<rect x="6" y="{cy-3:.1f}" width="{width-12}" height="6" rx="3" fill="#eef2f6"/>'
        f'<rect x="{x(r.p20):.1f}" y="{cy-3:.1f}" width="{max(1.5, x(r.p80)-x(r.p20)):.1f}" '
        f'height="6" rx="3" fill="#d7ece9"/>'
        f'<rect x="{x(r.p50)-0.9:.1f}" y="{cy-bh/2:.1f}" width="1.8" height="{bh}" '
        f'rx="0.9" fill="{TEAL_DK}"/>'
        f'<rect x="{x(r.actual)-1.6:.1f}" y="{cy-bh/2-2:.1f}" width="3.2" '
        f'height="{bh+4}" rx="1.6" fill="{col}"/>'
        f'</svg>')


def kpi(r: F.Reading, label: str, sub: str, dp=None) -> str:
    return (f'<div class="kpi {VCLS[r.verdict] if r.verdict else ""}">'
            f'<p class="lab">{label}</p>'
            f'<p class="val">{val(r, dp)}</p>'
            f'{bullet(r, 214, 26)}'
            f'<p class="sub">{sub}</p>{pill(r)}</div>')


def card(title, sub, body, note="") -> str:
    n = f'<p class="note">{note}</p>' if note else ""
    return (f'<div class="card"><h3>{title}</h3><p class="sub">{sub}</p>{body}{n}</div>')


def sect(title, sub) -> str:
    return f'<div class="sect"><h2>{title}</h2><span>{sub}</span></div>'


def measure_rows(ent: F.Entity, dp=None) -> str:
    """All four measures for one thing, each on its own band. BR-15 'look across'."""
    out = []
    for key in ("sales", "bills", "basket", "margin"):
        r = ent.r(key)
        out.append(
            f'<div class="mr"><div class="mr-l">{r.label}'
            f'<small>benchmark {band_text(r).split(" to ")[0]} to '
            f'{band_text(r).split(" to ")[1]}</small></div>'
            f'<div class="mr-b">{bullet(r, 210, 26)}</div>'
            f'<div class="mr-v {VCLS[r.verdict]}">{val(r)}'
            f'<small>{gap_text(r)}</small>{pill(r)}</div></div>')
    return f'<div class="mrs">{"".join(out)}</div>'


# ----------------------------------------------------------------- charts ---

def trend_chart(series, title_id: str, width=1180, height=290) -> str:
    """Each day placed inside its own normal band.

    Plotted against the day's own benchmark rather than in SAR, because the days are
    not the same size: a Friday takes three times a Tuesday here, so an absolute line
    is dominated by the weekend and the one day that fell out of its band disappears.
    Read as a percentage of that day's own benchmark, every day is comparable and the
    exceptions are the only things that leave the shaded band. The SAR figure is
    printed on every day that finished outside it, so no money is lost from the page.
    """
    pad_l, pad_r, pad_t, pad_b = 54, 58, 22, 42
    xs = [s["e"].r("sales") for s in series]
    rel = lambda v, r: v / r.p50 * 100.0
    lows = [rel(r.p20, r) for r in xs]
    highs = [rel(r.p80, r) for r in xs]
    acts = [rel(r.actual, r) for r in xs]
    lo = min(min(lows), min(acts)) - 4
    hi = max(max(highs), max(acts)) + 6
    n = len(series)
    px = lambda i: pad_l + i * (width - pad_l - pad_r) / (n - 1)
    py = lambda v: pad_t + (hi - v) / (hi - lo) * (height - pad_t - pad_b)

    ribbon = ("M" + " L".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(highs))
              + " L" + " L".join(f"{px(i):.1f},{py(v):.1f}"
                                 for i, v in reversed(list(enumerate(lows)))) + " Z")
    line = "M" + " L".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(acts))

    grid = []
    for v in range(int(lo // 10 * 10) + 10, int(hi) + 1, 10):
        y = py(v)
        if y < pad_t or y > height - pad_b:
            continue
        grid.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" '
                    f'stroke="#e6edf1" stroke-width="1"/>')
        grid.append(f'<text class="dz" x="{pad_l-8}" y="{y+3:.1f}" text-anchor="end">'
                    f'{v}%</text>')
    ybench = py(100.0)
    grid.append(f'<line x1="{pad_l}" y1="{ybench:.1f}" x2="{width-pad_r}" y2="{ybench:.1f}" '
                f'stroke="{TEAL_DK}" stroke-width="1.4" stroke-dasharray="4 3" '
                f'stroke-opacity="0.8"/>')
    grid.append(f'<text class="dza" x="{width-pad_r+6}" y="{ybench+3:.1f}">benchmark</text>')

    dots, labels = [], []
    for i, s_ in enumerate(series):
        r = s_["e"].r("sales")
        v = r.verdict
        col = VCOL[v]
        dots.append(f'<circle cx="{px(i):.1f}" cy="{py(acts[i]):.1f}" '
                    f'r="{4.8 if v != IN else 2.8}" fill="{col}" stroke="#fff" '
                    f'stroke-width="1.4"/>')
        if width >= 700 or i % 2 == 0 or i == n - 1:
            labels.append(f'<text class="dzday" x="{px(i):.1f}" y="{height-16}" '
                          f'text-anchor="middle">{e(F.fmt_date(s_["date"], "short"))}</text>')
        if v != IN:
            up = acts[i] >= highs[i]
            dy = -13 if up else 20
            if i and series[i-1]["e"].r("sales").verdict != IN:
                dy += -14 if up else 14
            labels.append(
                f'<text class="dzann" x="{px(i):.1f}" y="{py(acts[i])+dy:.1f}" '
                f'text-anchor="middle" fill="{col}">{sar_plain(r.actual)}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
            f'role="img" aria-labelledby="{title_id}">'
            f'<title id="{title_id}">Each of the last {n} days as a percentage of its own '
            f'benchmark, with the normal band shaded. '
            f'{sum(1 for x in series if x["e"].r("sales").verdict == IN)} days landed inside '
            f'the band.</title>'
            + "".join(grid)
            + f'<path d="{ribbon}" fill="{TEAL}" fill-opacity="0.16"/>'
            + f'<path d="{line}" fill="none" stroke="{INK}" stroke-width="2"/>'
            + "".join(dots) + "".join(labels) + '</svg>')


def bridge_chart(width=560, height=280) -> str:
    """BR-16: Net Sales is Bills x Basket Value. This says which one carried the day.

    (Q1-Q0)*R0 + Q1*(R1-R0) = Q1R1 - Q0R0 exactly, so the two effects always add to
    the whole gap. The build asserts it rather than trusting it.
    """
    o = FACTS["overall"]
    s, b, k = o.r("sales"), o.r("bills"), o.r("basket")
    bills_eff = (b.actual - b.p50) * k.p50
    basket_eff = b.actual * (k.actual - k.p50)
    assert abs(bills_eff + basket_eff - (s.actual - s.p50)) < 0.01,         "the two effects must add to the gap"

    steps = [("Benchmark", "for this weekday", s.p50, None),
             ("Fewer Bills", f"{num(abs(b.vs_p50))} fewer", None, bills_eff),
             ("Smaller basket", f"{sar_plain(abs(k.vs_p50), 2)} less each", None, basket_eff),
             ("The day", "what was taken", s.actual, None)]

    pad_t, base_y = 34, height - 52
    top = max(s.p50, s.actual) * 1.10
    scale = (base_y - pad_t) / top
    bw, gap, x0 = 92, 42, 30
    out, run, prev_x2, prev_y = [], 0.0, None, None
    for i, (lab, sub, total, delta) in enumerate(steps):
        x = x0 + i * (bw + gap)
        if total is not None:
            h = total * scale
            y = base_y - h
            col = TEAL_DK if i == 0 else VCOL[s.verdict]
            out.append(f'<rect x="{x}" y="{y:.1f}" width="{bw}" height="{h:.1f}" rx="2" '
                       f'fill="{col}"/>')
            out.append(f'<text class="dzv" x="{x+bw/2}" y="{y-9:.1f}" text-anchor="middle">'
                       f'{sar_plain(total)}</text>')
            run = total
            ny = y
        else:
            h = abs(delta) * scale
            ytop = base_y - run * scale
            y2 = ytop if delta < 0 else ytop - h
            out.append(f'<rect x="{x}" y="{y2:.1f}" width="{bw}" height="{max(h,2):.1f}" '
                       f'rx="2" fill="{AMBER}"/>')
            out.append(f'<text class="dzv" x="{x+bw/2}" y="{y2-9:.1f}" text-anchor="middle" '
                       f'fill="{AMBER_DK}">{signed_sar_plain(delta)}</text>')
            run += delta
            ny = ytop
        if prev_x2 is not None:
            out.insert(0, f'<line x1="{prev_x2}" y1="{prev_y:.1f}" x2="{x}" y2="{prev_y:.1f}" '
                          f'stroke="{FAINT}" stroke-width="1" stroke-dasharray="3 3"/>')
        prev_x2, prev_y = x + bw, (base_y - run * scale)
        out.append(f'<text class="dzday" x="{x+bw/2}" y="{height-28}" text-anchor="middle">'
                   f'{e(lab)}</text>')
        out.append(f'<text class="dzsub" x="{x+bw/2}" y="{height-14}" text-anchor="middle">'
                   f'{e(sub)}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" role="img" '
            f'aria-label="Net Sales of {e(sar(s.p50))} at benchmark, less '
            f'{e(sar(abs(bills_eff)))} from fewer Bills and {e(sar(abs(basket_eff)))} from a '
            f'smaller Basket Value, giving {e(sar(s.actual))} on the day.">'
            f'<line x1="20" y1="{base_y}" x2="{width-14}" y2="{base_y}" stroke="#dfe7ec"/>'
            + "".join(out) + '</svg>')


# ------------------------------------------------------------------ tables ---

def level_table(entities, label, show_parent=False, show_share=False, limit=None) -> str:
    rows = sorted(entities, key=lambda x: x.r("sales").actual, reverse=True)
    shown = rows[:limit] if limit else rows
    head = (f'<tr><th>{label}</th>' + ('<th>Sits under</th>' if show_parent else "")
            + '<th class="n">Net Sales</th><th class="n">Normal band</th>'
            '<th class="n">Against the band</th><th class="n">Bills</th>'
            '<th class="n">Basket Value</th><th class="n">Margin</th>'
            + ('<th class="n">Share of baskets</th>' if show_share else "")
            + '<th>Verdict</th></tr>')
    body = []
    for x in shown:
        s, b, k, m = x.r("sales"), x.r("bills"), x.r("basket"), x.r("margin")
        cls = ' class="urgent"' if s.verdict == BELOW else ""
        share = ""
        if show_share and x.penetration is not None:
            share = (f'<td class="n">{pc(x.penetration.actual)}'
                     f'<small class="act"> vs {pc(x.penetration.p50)}</small></td>')
        elif show_share:
            share = '<td class="n">&mdash;</td>'
        body.append(
            f'<tr{cls}><td><b>{e(x.name)}</b></td>'
            + (f'<td class="act">{e(x.parent or "&mdash;")}</td>' if show_parent else "")
            + f'<td class="n">{val(s)}</td>'
            f'<td class="n act">{band_text(s)}</td>'
            f'<td class="n {VCLS[s.verdict]}">'
            f'{signed_sar(s.gap) if s.verdict != IN else "&mdash;"}</td>'
            f'<td class="n {VCLS[b.verdict]}">{val(b)}</td>'
            f'<td class="n {VCLS[k.verdict]}">{val(k)}</td>'
            f'<td class="n {VCLS[m.verdict]}">{val(m)}</td>'
            + share
            + f'<td>{pill(s)}</td></tr>')
    more = ""
    if limit and len(rows) > limit:
        more = (f'<p class="note">Showing the {limit} largest of {len(rows)}. '
                f'The full list is in the table below.</p>')
    return (f'<div class="scroll"><table><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>{more}')


def exception_list(entities, kind: str, limit=8) -> str:
    """Ranked by the size of the gap in SAR, never by the percentage (BR-17)."""
    if not entities:
        word = "below" if kind == BELOW else "above"
        return (f'<p class="note">Nothing finished {word} its normal band at this level '
                f'on this day.</p>')
    rows = []
    for x in entities[:limit]:
        s = x.r("sales")
        w = max(6.0, min(100.0, abs(s.gap) / abs(entities[0].r("sales").gap) * 100))
        col = VCOL[s.verdict]
        rows.append(
            f'<div class="rb"><div class="rb-l">{e(x.name)}'
            f'<small>{e(x.parent) if x.parent else "&nbsp;"}</small></div>'
            f'<div class="rb-t"><span class="rb-f" style="width:{w:.1f}%;background:{col}">'
            f'</span></div>'
            f'<div class="rb-v">{signed_sar(s.gap)}'
            f'<small class="act">{val(s)} vs {money(s.p20 if s.verdict == BELOW else s.p80)}'
            f'</small></div></div>')
    return f'<div class="rbars">{"".join(rows)}</div>'


# ------------------------------------------------------------ the numbers ---

O = FACTS["overall"]
S1, S4 = FACTS["per_store"][0], FACTS["per_store"][1]
OS, OB, OK, OM = O.r("sales"), O.r("bills"), O.r("basket"), O.r("margin")

# BR-08: the two stores' actuals add, and so does the band that was built the same way.
# The whole group gap is therefore the sum of the two store gaps - asserted, not assumed.
assert abs((S1.r("sales").actual + S4.r("sales").actual) - OS.actual) < 0.01
assert abs((S1.r("sales").gap + S4.r("sales").gap) - OS.gap) < 0.01

BILLS_EFF = (OB.actual - OB.p50) * OK.p50
BASKET_EFF = OB.actual * (OK.actual - OK.p50)
assert abs(BILLS_EFF + BASKET_EFF - OS.vs_p50) < 0.01

TREND = FACTS["trend"]
IN_BAND_DAYS = sum(1 for t in TREND if t["e"].r("sales").verdict == IN)
BELOW_DAYS = [t for t in TREND if t["e"].r("sales").verdict == BELOW]
ABOVE_DAYS = [t for t in TREND if t["e"].r("sales").verdict == ABOVE]
MARGIN_RANK = sorted(TREND, key=lambda t: t["e"].r("margin").actual, reverse=True)
MARGIN_BEST = MARGIN_RANK[0]["date"] == FACTS["anchor"]

WORST_STORE = min(FACTS["per_store"], key=lambda x: x.r("sales").gap)
BEST_STORE = max(FACTS["per_store"], key=lambda x: x.r("sales").gap)
DEPT_BELOW = FACTS["below"]["departments"]
LEAD_DEPT = DEPT_BELOW[0] if DEPT_BELOW else None

# BR-15 "look down": which department under the weakest store carries it.
STORE_DEPTS = FACTS["dept_by_store"][WORST_STORE.name]
STORE_DEPT_BELOW = sorted((d for d in STORE_DEPTS if d.r("sales").verdict == BELOW),
                          key=lambda d: d.r("sales").gap)

SILENT = FACTS["silent_categories"]
SILENT_VALUE = sum(x.silent_p50 for x in SILENT)
SILENT_ROWS = sum(x.silent_rows for x in SILENT)

DAY_LABEL = FACTS["anchor_label"]
WIN = FACTS["window"]
WINDOW_LABEL = (f'{F.fmt_date(WIN["min"], "med")} to {F.fmt_date(WIN["max"], "med")}')
SAMPLE_LO, SAMPLE_HI = O.sample_days
MARGIN_SAMPLE = O.margin_sample_days[0]


# ------------------------------------------------------------------ layers ---

def hero() -> str:
    lead = (f'Net Sales landed {sar(abs(OS.gap), 2)} under the floor of its normal band, '
            f'and {sar(abs(OS.vs_p50))} under the benchmark.')
    if OS.verdict == IN:
        lead = 'Net Sales stayed inside its normal band.'
    stats = [
        ("crit" if OS.verdict == BELOW else "", sar(OS.actual),
         f"Net Sales &middot; {gap_text(OS)}"),
        ("crit" if OK.verdict == BELOW else "", sar(OK.actual, 2),
         f"Basket Value &middot; {signed_pc(OK.vs_p50_pct)} against the benchmark"),
        ("", pc(OM.actual, 2),
         f"Margin &middot; {'above the band ceiling' if OM.verdict == ABOVE else gap_text(OM)}"),
    ]
    cells = "".join(f'<div class="hs {c}"><b>{v}</b><span>{s}</span></div>'
                    for c, v, s in stats)
    return (f'<div class="hero"><div>'
            f'<span class="hero-tag">{e(FACTS["anchor_dow"])} &middot; week '
            f'{FACTS["week_of_month"]} of the month</span>'
            f'<h2>{lead}</h2>'
            f'<p>Bills held up &mdash; {num(OB.actual)} against a benchmark of {num(OB.p50)}, '
            f'inside the band. What fell was the amount in each basket. '
            f'All of the shortfall against the floor sits in {e(WORST_STORE.name)}; '
            f'{e(BEST_STORE.name)} finished level with its own floor.</p>'
            f'</div><div class="hero-stats">{cells}</div></div>')


def layer_day(scoped=False) -> str:
    banner = ""
    if scoped:
        banner = ('<div class="scoped">This view keeps only the parts of the business that '
                  'finished outside their normal band. The figures in this first section still '
                  'describe the whole day across both stores.</div>')

    kpis = (f'<div class="kpis k4">'
            f'{kpi(OS, "Net Sales", vs_bench(OS))}'
            f'{kpi(OB, "Bills", vs_bench(OB))}'
            f'{kpi(OK, "Basket Value", vs_bench(OK), dp=2)}'
            f'{kpi(OM, "Margin", vs_bench(OM))}</div>')

    trend_note = (
        f'The shaded band is the normal band for that weekday, and the dashed line is the '
        f'benchmark. {IN_BAND_DAYS} of the {len(TREND)} days landed inside the band. '
        f'{DAY_LABEL.split(",")[0]} is the only day in the window that finished below it.'
        if len(BELOW_DAYS) == 1 else
        f'The shaded band is the normal band for that weekday, and the dashed line is the '
        f'benchmark. {IN_BAND_DAYS} of the {len(TREND)} days landed inside the band, '
        f'{len(BELOW_DAYS)} below it and {len(ABOVE_DAYS)} above it.')

    lead = card(
        "Net Sales against the normal band, day by day",
        f"Both stores together &middot; {WINDOW_LABEL} &middot; each day scored against its own "
        f"weekday",
        trend_chart(TREND, "trend-all"),
        trend_note)

    bridge = card(
        "What carried the day",
        "Net Sales is Bills multiplied by Basket Value, so the gap belongs to one of them "
        "or to both",
        bridge_chart(),
        f'Starting from the benchmark of {sar(OS.p50)}: '
        f'{num(abs(OB.vs_p50))} fewer Bills took off {sar(abs(BILLS_EFF))}, and each basket '
        f'holding {sar(abs(OK.vs_p50), 2)} less took off {sar(abs(BASKET_EFF))}. '
        f'The smaller basket is {pc(abs(BASKET_EFF) / abs(OS.vs_p50) * 100, 0)} of the gap. '
        f'The two add to {sar(abs(OS.vs_p50))} exactly.')

    across = card(
        "Look across &mdash; the four measures side by side",
        "Every measure on this day, each against its own normal band",
        measure_rows(O),
        "A measure inside the band is normal for this weekday and is not a move. Only the two "
        "marked here sit outside it.")

    dept_line = ""
    if STORE_DEPT_BELOW:
        d = STORE_DEPT_BELOW[0]
        dept_line = (f'Inside {e(WORST_STORE.name)}, the department below its own band is '
                     f'<b>{e(d.name)}</b>: {val(d.r("sales"))}, {gap_text(d.r("sales"))}.')
    elif LEAD_DEPT:
        dept_line = (f'Across both stores the department below its own band is '
                     f'<b>{e(LEAD_DEPT.name)}</b>: {val(LEAD_DEPT.r("sales"))}, '
                     f'{gap_text(LEAD_DEPT.r("sales"))}.')

    down_rows = "".join(
        f'<div class="mini"><b>{e(s.name)}</b>'
        f'<span>{val(s.r("sales"))} &middot; {gap_text(s.r("sales"))}</span>'
        f'<span class="act">Bills {val(s.r("bills"))} &middot; Basket Value '
        f'{val(s.r("basket"))} &middot; Margin {val(s.r("margin"))}</span>'
        f'{pill(s.r("sales"))}</div>'
        for s in FACTS["per_store"])

    down = card(
        "Look down &mdash; where the day sits",
        "The two stores, then the department underneath the weaker one",
        f'<div class="minis">{down_rows}</div>',
        f'{dept_line} Both stores are shown because a group figure hides a store: '
        f'{e(BEST_STORE.name)} sat level with its floor at {val(BEST_STORE.r("sales"))} while '
        f'{e(WORST_STORE.name)} finished {sar(abs(WORST_STORE.r("sales").gap), 2)} below its '
        f'own.')

    return (f'{banner}{hero()}'
            f'{sect("The day", DAY_LABEL)}'
            f'{kpis}'
            f'<div class="grid" style="margin-top:14px">{lead}</div>'
            f'<div class="grid g-2" style="margin-top:14px">{bridge}{across}</div>'
            f'<div class="grid" style="margin-top:14px">{down}</div>')


def layer_stores(scoped=False) -> str:
    stores = FACTS["per_store"]
    if scoped:
        stores = [s for s in stores if s.below]
    banner = ('<div class="scoped">Only stores with a measure outside their normal band are '
              'shown here.</div>') if scoped else ""
    if not stores:
        return banner + card("Stores", "", '<p class="note">Both stores kept every measure '
                                           'inside its normal band on this day.</p>')

    cards = "".join(
        card(f'{e(s.name)}',
             f'All four measures against this store&rsquo;s own benchmark for a '
             f'{e(FACTS["anchor_dow"])} in week {FACTS["week_of_month"]} of the month',
             measure_rows(s),
             f'Benchmark built from {s.sample_days[0]} matching past days for Net Sales, '
             f'Bills and Basket Value, and {s.margin_sample_days[0]} for Margin.')
        for s in stores)

    runs = "".join(
        card(f'{e(st)} &mdash; the last {len(FACTS["store_trend"][st])} days',
             "Net Sales against this store&rsquo;s own normal band",
             trend_chart(FACTS["store_trend"][st], f"trend-{st.lower()}", 560, 210),
             f'{FACTS["store_trend_counts"][st][IN]} days inside the band, '
             f'{FACTS["store_trend_counts"][st][BELOW]} below it and '
             f'{FACTS["store_trend_counts"][st][ABOVE]} above it.')
        for st in FACTS["stores"] if not scoped or any(s.name == st for s in stores))

    return (f'{banner}{sect("Stores", f"{DAY_LABEL} &middot; each store on its own band")}'
            f'<div class="grid g-2e">{cards}</div>'
            f'{sect("The last two weeks", "One store at a time")}'
            f'<div class="grid g-2e">{runs}</div>')


def penetration_bars(depts) -> str:
    """BR-12: what share of the day's baskets each department reached, against its own
    benchmark share. Shares do not add to 100% because one basket touches several."""
    rows = sorted((d for d in depts if d.penetration is not None),
                  key=lambda d: d.penetration.actual, reverse=True)
    top = max((d.penetration.actual for d in rows), default=1) or 1
    out = []
    for d in rows:
        pen = d.penetration
        w = pen.actual / top * 100
        bench = pen.p50 / top * 100 if pen.p50 else None
        short = pen.p50 is not None and pen.actual < pen.p50
        tick = (f'<span class="rb-tick" style="left:{bench:.1f}%"></span>'
                if bench is not None else "")
        out.append(
            f'<div class="rb"><div class="rb-l">{e(d.name)}'
            f'<small>{num(d.r("bills").actual)} Bills</small></div>'
            f'<div class="rb-t"><span class="rb-f" style="width:{w:.1f}%;'
            f'background:{AMBER if short else TEAL}"></span>{tick}</div>'
            f'<div class="rb-v">{pc(pen.actual)}'
            f'<small class="act">benchmark {pc(pen.p50)}</small></div></div>')
    return f'<div class="rbars">{"".join(out)}</div>'


def by_store_table() -> str:
    """The same department in each store, side by side. A department can sit inside its
    band across both stores while one of the two is outside its own (BR-08, BR-15)."""
    stores = FACTS["stores"]
    per = {st: {d.name: d for d in FACTS["dept_by_store"][st]} for st in stores}
    names = [d.name for d in sorted(FACTS["departments"],
                                    key=lambda x: x.r("sales").actual, reverse=True)]
    head = ('<tr><th>Department</th>'
            + "".join(f'<th class="n">{e(st)} Net Sales</th>'
                      f'<th class="n">{e(st)} against the band</th>' for st in stores)
            + '<th class="n">Stores outside their band</th></tr>')
    body = []
    for n_ in names:
        cells, out_count = [], 0
        for st in stores:
            d = per[st].get(n_)
            if d is None:
                cells.append('<td class="n act">no sale</td><td class="n act">&mdash;</td>')
                continue
            r = d.r("sales")
            if r.verdict != IN:
                out_count += 1
            cells.append(
                f'<td class="n">{val(r)}</td>'
                f'<td class="n {VCLS[r.verdict]}">'
                f'{signed_sar(r.gap) if r.verdict != IN else "&mdash;"}</td>')
        cls = ' class="urgent"' if out_count else ""
        body.append(f'<tr{cls}><td><b>{e(n_)}</b></td>{"".join(cells)}'
                    f'<td class="n">{out_count or "&mdash;"}</td></tr>')
    return (f'<div class="scroll"><table><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def layer_departments(scoped=False) -> str:
    depts = FACTS["departments"]
    if scoped:
        depts = [d for d in depts if d.r("sales").verdict != IN]
    banner = ('<div class="scoped">Only departments that finished outside their normal band '
              'are shown. The share of baskets is still measured against the whole day.</div>'
              ) if scoped else ""
    if not depts:
        return banner + card("Departments", "Nothing outside its band",
                             '<p class="note">Every department finished inside its normal band '
                             'on this day, so this view has nothing to show. The full list is '
                             'in the All areas view.</p>')

    table = card(
        "Every department on this day",
        "Both stores together &middot; each department against its own benchmark table",
        level_table(depts, "Department", show_share=True),
        f'Share of baskets is this department&rsquo;s Bills divided by the {num(OB.actual)} '
        f'Bills taken across both stores, with the benchmark share beside it. One basket can '
        f'touch several departments, so these shares do not add to 100%.')

    ranked = card(
        "Departments outside their band",
        f"Ranked by the size of the gap in {CUR}, not by the percentage",
        exception_list(FACTS["below"]["departments"], BELOW)
        + ('<h4 class="mini-h">Above the band</h4>'
           + exception_list(FACTS["above"]["departments"], ABOVE) if not scoped else ""),
        "A department can sit far from its band and still be small. Ranking by "
        f"{CUR} keeps the biggest gap at the top.")

    pen = card(
        "How many baskets each department reached",
        "Share of the day&rsquo;s Bills, with the benchmark share marked",
        penetration_bars(depts),
        "The mark on each bar is that department&rsquo;s usual share for this weekday. "
        "A bar short of its mark reached fewer baskets than normal. The shares do not add "
        "to 100% because one basket can touch several departments.")

    split = card(
        "Each department, store by store",
        "The same department in each store, against that store&rsquo;s own benchmark",
        by_store_table(),
        "A department can sit inside its band across both stores while one of the two is "
        "outside its own, so both are shown.")

    return (f'{banner}{sect("Departments", DAY_LABEL)}'
            f'<div class="grid">{table}</div>'
            f'<div class="grid g-2" style="margin-top:14px">{pen}{ranked}</div>'
            f'{sect("Store by store", "The same five departments, split between the two stores")}'
            f'<div class="grid">{split}</div>')


def layer_detail(scoped=False) -> str:
    secs = FACTS["sections"]
    cats = FACTS["categories"]
    if scoped:
        secs = [x for x in secs if x.r("sales").verdict != IN]
        cats = [x for x in cats if x.r("sales").verdict != IN]
    banner = ('<div class="scoped">Only sections and categories that finished outside their '
              'normal band are shown.</div>') if scoped else ""

    below_card = card(
        "What finished below its band",
        f"Sections and categories, ranked by the size of the gap in {CUR}",
        '<h4 class="mini-h">Sections</h4>'
        + exception_list(FACTS["below"]["sections"], BELOW, 6)
        + '<h4 class="mini-h">Categories</h4>'
        + exception_list(FACTS["below"]["categories"], BELOW, 8),
        "A small gap on a small part of the business is not a finding. These are ordered by "
        f"how many {CUR} the gap is worth.")

    above_card = card(
        "What finished above its band",
        "The same ranking, for the parts that beat their ceiling",
        '<h4 class="mini-h">Sections</h4>'
        + exception_list(FACTS["above"]["sections"], ABOVE, 6)
        + '<h4 class="mini-h">Categories</h4>'
        + exception_list(FACTS["above"]["categories"], ABOVE, 8),
        "A day below its band overall can still hold parts that beat their own.")

    silent = card(
        "Groups that recorded nothing today",
        "Counted separately, never folded into a band comparison",
        '<div class="scroll"><table><thead><tr><th>Category</th><th>Sits under</th>'
        '<th class="n">Groups with no sale</th><th class="n">What they usually take</th>'
        '<th class="n">Taken by the rest</th></tr></thead><tbody>'
        + "".join(
            f'<tr><td><b>{e(x.name)}</b></td><td class="act">{e(x.parent or "")}</td>'
            f'<td class="n">{x.silent_rows} of {x.band_rows}</td>'
            f'<td class="n">{sar(x.silent_p50)}</td>'
            f'<td class="n">{val(x.r("sales"))}</td></tr>'
            for x in SILENT[:8])
        + '</tbody></table></div>',
        f'{SILENT_ROWS:,} groups across the day recorded no sale at all. On a matching past day '
        f'they take {sar(SILENT_VALUE)} between them. They are kept out of the band comparisons '
        f'above, because a benchmark that includes groups which could not contribute would make '
        f'every name read below its band.')

    sec_table = card(
        "Every section", f"{len(FACTS['sections'])} sections with a sale on this day",
        level_table(secs, "Section", show_parent=True))
    cat_table = card(
        "Every category", f"{len(FACTS['categories'])} categories with a sale on this day",
        level_table(cats, "Category", show_parent=True))

    return (f'{banner}{sect("Detail", f"Sections and categories &middot; {DAY_LABEL}")}'
            f'<div class="grid g-2e">{below_card}{above_card}</div>'
            f'<div class="grid" style="margin-top:14px">{silent}</div>'
            f'{sect("The full lists", "Every row, both stores together")}'
            f'<div class="grid">{sec_table}</div>'
            f'<div class="grid" style="margin-top:14px">{cat_table}</div>')


SAMPLE_TXT = (str(SAMPLE_LO) if SAMPLE_LO == SAMPLE_HI else f"{SAMPLE_LO} to {SAMPLE_HI}")
STORES_TXT = " and ".join(FACTS["stores"])
NO_TRADE_TXT = ", ".join(FACTS["no_trade_departments"]) or "none"
LEAD_DEPT_NAME = LEAD_DEPT.name if LEAD_DEPT else "one department"
LEAD_DEPT_GAP_SAR = sar(abs(LEAD_DEPT.r("sales").gap)) if LEAD_DEPT else ""
LAST_DAY_TXT = F.fmt_date(WIN["max"], "med")

CAVEATS = f"""<div class="caveats">
  <h3>What these figures cover, and what they do not</h3>
  <ul>
    <li><b>This is a comparison with the normal band, never with last year.</b> Every figure is
        {e(DAY_LABEL)} placed against past days that match on the same weekday, so a
        {e(FACTS["anchor_dow"])} is only ever judged against other {e(FACTS["anchor_dow"])}s.
        The report holds no same-day-last-year figure and does not claim one.</li>
    <li><b>The figures cover {e(STORES_TXT)} only</b>, and both stores are in
        every total on this page.</li>
    <li><b>The bands are built from a small number of matching days.</b> Net Sales, Bills and
        Basket Value use {SAMPLE_TXT}
        matching past days; Margin uses {MARGIN_SAMPLE} same-weekday readings. A band drawn from
        a short run of days is wider and moves more than one drawn from a long run.</li>
    <li><b>A band at one level will not add up to the band at the level above it.</b> The whole
        day finished {sar(abs(OS.gap), 2)} below its floor while
        {e(LEAD_DEPT_NAME)} alone was
        {LEAD_DEPT_GAP_SAR} below its own. Each level is
        worked out separately, so the two do not match and neither is wrong.</li>
    <li><b>Bills cannot be added up.</b> One basket holding bread, shampoo and a shirt is one
        Bill for the store but appears under each department, section and category it touched.
        Each figure on this page is taken from its own level, and department shares of baskets
        do not add to 100%.</li>
    <li><b>Several groups share one name.</b> A name such as LIFESTYLE or LADIES APPAREL covers
        more than one group in the source, and the source does not carry the code that separates
        them. Net Sales for those names is added, which is safe. Their bands are added too, which
        is close but is not a true benchmark for the whole name, and their Bills count some
        baskets more than once. Treat a band at these levels as a guide.</li>
    <li><b>One department, {e(NO_TRADE_TXT)}, recorded no
        sale on this day</b> and has been left out of the tables rather than shown as a zero.</li>
    <li><b>The figures run to {e(LAST_DAY_TXT)}.</b> That is the most recent day
        the report holds.</li>
  </ul>
</div>"""

STYLE = """
:root{
  --ground:#eef1f0; --card:#fff; --rail:#0e1b19; --ink:#12201e; --mid:#41545a;
  --muted:#5b7182; --faint:#8fa1a9; --line:#dfe7ec; --soft:#f7fafb;
  --teal:#0f9f95; --teal-dk:#087f79; --teal-tint:#e2f2ef;
  --amber:#c08429; --amber-tint:#faf1e1; --amber-dk:#8a5f10;
  --red:#cf4636; --red-tint:#fbeae7; --green:#2f8f4e; --green-tint:#e8f4ec;
  --r:12px; --shadow:0 1px 2px rgba(16,24,40,.05),0 10px 28px -20px rgba(16,24,40,.35);
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:'Segoe UI',Inter,Roboto,Arial,sans-serif;font-size:13.5px;line-height:1.5;
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
h1,h2,h3,h4,p{margin:0}

.app{display:flex;min-height:100vh}
.rail{width:172px;flex:0 0 172px;background:var(--rail);color:#cfe0dc;padding:18px 12px;
  position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:5px}
.rail .mark{width:34px;height:34px;border-radius:9px;background:rgba(15,159,149,.16);
  border:1px solid rgba(15,159,149,.5);color:#4fd3c4;display:grid;place-items:center;
  font-weight:800;font-size:12px;letter-spacing:.04em;margin-bottom:14px}
.rail .grp{font-size:9px;letter-spacing:.13em;text-transform:uppercase;color:#5f7d78;
  margin:14px 0 5px;padding-left:9px}
.rail button{all:unset;cursor:pointer;display:block;padding:8px 11px;border-radius:8px;
  font-size:12.5px;font-weight:600;color:#a9c2bd}
.rail button:hover{background:rgba(255,255,255,.06);color:#fff}
.rail button[aria-current=true]{background:var(--teal);color:#fff}
.rail .foot{margin-top:auto;font-size:10px;color:#4d6b66;line-height:1.45;padding-left:9px}

main{flex:1;min-width:0}
.page{max-width:1280px;margin:0 auto;padding:22px 26px 60px}

.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
  flex-wrap:wrap;margin-bottom:16px}
.eyebrow{font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--teal-dk);
  font-weight:750;margin-bottom:5px}
h1{font-size:27px;line-height:1.12;letter-spacing:-.02em;font-weight:700}
.asat{font-size:12px;color:var(--muted);margin-top:5px}
.seg{display:inline-flex;background:var(--card);border:1px solid var(--line);
  border-radius:9px;padding:3px}
.seg button{all:unset;cursor:pointer;padding:6px 14px;border-radius:7px;font-size:12px;
  font-weight:650;color:var(--muted)}
.seg button[aria-pressed=true]{background:var(--teal-tint);color:var(--teal-dk)}

.hero{background:var(--rail);border-radius:var(--r);padding:20px 24px;margin-bottom:14px;
  display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:26px;align-items:center}
.hero-tag{display:inline-block;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  font-weight:750;color:#f0c46a;background:rgba(240,196,106,.14);padding:4px 9px;
  border-radius:6px;margin-bottom:10px}
.hero h2{color:#fff;font-size:23px;line-height:1.22;letter-spacing:-.015em;font-weight:700}
.hero p{color:#a9c2bd;font-size:12.5px;margin-top:8px;max-width:60ch}
.hero-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.hs{border-left:2px solid rgba(255,255,255,.14);padding-left:12px}
.hs b{display:block;color:#fff;font-size:18px;font-weight:700;line-height:1.15}
.hs span{display:block;color:#7f9a95;font-size:10.5px;margin-top:3px;line-height:1.35}
.hs.crit b{color:#ff8b73}

.grid{display:grid;gap:14px;align-items:start}
.g-2{grid-template-columns:minmax(0,1.35fr) minmax(0,1fr)}
.g-2e{grid-template-columns:repeat(2,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:16px 18px;box-shadow:var(--shadow)}
.card>h3{font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.card>.sub{font-size:11.5px;color:var(--muted);margin-top:2px;margin-bottom:12px}
.sect{margin:22px 0 10px;display:flex;align-items:baseline;gap:11px}
.sect h2{font-size:16px;font-weight:700;letter-spacing:-.015em}
.sect span{font-size:11.5px;color:var(--faint)}
.note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.5}
.mini-h{font-size:10px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;margin:14px 0 8px}
.mini-h:first-child{margin-top:0}

.kpis{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:13px 14px 12px;position:relative;overflow:hidden;box-shadow:var(--shadow)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--faint)}
.kpi.crit::before{background:var(--red)} .kpi.good::before{background:var(--green)}
.kpi .lab{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  font-weight:650}
.kpi .val{font-size:21px;font-weight:750;line-height:1.1;margin:5px 0 2px;letter-spacing:-.02em}
.kpi.crit .val{color:var(--red)} .kpi.good .val{color:var(--green)}
.kpi .sub{font-size:10.5px;color:var(--muted);line-height:1.4;margin-top:2px}
.kpi .pill{margin-top:7px}
.bul{display:block;margin:2px 0 4px}

.pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 6px;border-radius:5px}
.pill-crit{background:var(--red-tint);color:var(--red)}
.pill-ok{background:var(--green-tint);color:var(--green)}
.pill-neutral{background:#eef2f6;color:var(--muted)}

.mrs{display:flex;flex-direction:column;gap:10px}
.mr{display:grid;grid-template-columns:122px minmax(64px,1fr) 152px;gap:12px;
  align-items:center;font-size:12px;min-width:0}
.mr-b{min-width:0}
.mr-l{font-weight:650}
.mr-l small{display:block;font-weight:400;font-size:10px;color:var(--muted);line-height:1.35}
.mr-v{text-align:right;font-weight:750;font-size:13px;white-space:nowrap;min-width:0}
.mr-v small{display:block;font-weight:500;font-size:10px;color:var(--muted);line-height:1.35}
.mr-v.crit{color:var(--red)} .mr-v.good{color:var(--green)}
.mr-v small{white-space:normal;font-weight:500}
.mr-v .pill{margin-top:4px}

.minis{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.mini{border:1px solid var(--line);border-radius:10px;padding:12px 14px;background:var(--soft)}
.mini b{display:block;font-size:14px;font-weight:750}
.mini>span{display:block;font-size:11.5px;color:var(--mid);margin-top:3px}
.mini>span.pill{display:inline-block;font-size:9px;color:inherit}
.mini .act{color:var(--faint);font-size:11px}
.mini .pill{margin-top:8px}

.rbars{display:flex;flex-direction:column;gap:9px}
.rb{display:grid;grid-template-columns:160px minmax(0,1fr) 128px;gap:11px;align-items:center;
  font-size:12px}
.rb-l{font-weight:650;overflow:hidden;text-overflow:ellipsis}
.rb-l small{display:block;font-weight:400;font-size:10px;color:var(--muted)}
.rb-t{background:#eef2f6;border-radius:99px;height:10px;position:relative}
.rb-tick{position:absolute;top:-3px;bottom:-3px;width:1.6px;background:var(--mid);
  opacity:.6;border-radius:2px}
.rb-f{display:block;height:100%;border-radius:99px}
.rb-v{text-align:right;font-weight:700}
.rb-v small{display:block;font-weight:500;font-size:10px}

.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;min-width:640px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
td.crit{color:var(--red);font-weight:700} td.good{color:var(--green);font-weight:700}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--soft)}
tr.urgent td{background:var(--red-tint)}
.act{color:var(--faint);font-size:11px;font-weight:400}

.dz{fill:var(--faint);font-size:9px} .dzv{fill:var(--ink);font-size:10.5px;font-weight:700}
.dzday{fill:var(--mid);font-size:10.5px;font-weight:650}
.dzsub{fill:var(--faint);font-size:9.5px}
.dza{fill:var(--teal-dk);font-size:9.5px;font-weight:650}
.dzann{font-size:10.5px;font-weight:750}

.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
  font-size:10.5px;color:var(--faint)}

@media (max-width:1080px){
  .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}
  .g-2,.g-2e,.minis{grid-template-columns:minmax(0,1fr)}
  .hero{grid-template-columns:minmax(0,1fr)}
  .mr{grid-template-columns:110px minmax(0,1fr)}
  .mr-b{display:none}
}
@media (max-width:720px){.rail{display:none}}
@media print{
  .rail,.seg{display:none}.app{display:block}.card,.kpi,.hero{break-inside:avoid;box-shadow:none}
  body{background:#fff}
}

.layer[hidden],.view[hidden]{display:none}
.scoped{background:var(--amber-tint);border:1px solid #e8d3a8;border-radius:var(--r);
  padding:11px 15px;font-size:11.5px;color:var(--amber-dk);margin-bottom:14px}
@media print{.layer[hidden],.view[hidden]{display:block}}
"""

SCRIPT = """<script>
(function(){
  var LAYERS = ['day','stores','departments','detail'];

  function setLayer(name){
    document.querySelectorAll('.layer').forEach(function(el){
      el.hidden = el.getAttribute('data-layer') !== name;
    });
    document.querySelectorAll('[data-nav]').forEach(function(btn){
      btn.setAttribute('aria-current',
        btn.getAttribute('data-nav') === name ? 'true' : 'false');
    });
  }

  function setView(name){
    document.querySelectorAll('.view').forEach(function(el){
      el.hidden = el.getAttribute('data-view') !== name;
    });
    document.querySelectorAll('[data-viewbtn]').forEach(function(btn){
      var on = btn.getAttribute('data-viewbtn') === name;
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      if (btn.closest('.rail')) btn.setAttribute('aria-current', on ? 'true' : 'false');
    });
  }

  var current = {view: 'all', layer: 'day'};

  function apply(){
    setView(current.view);
    setLayer(current.layer);
    var hash = '#' + current.view + '/' + current.layer;
    if (location.hash !== hash){ history.replaceState(null, '', hash); }
  }

  function fromHash(){
    var parts = (location.hash || '').replace('#', '').split('/');
    if (parts[0] && document.querySelector('.view[data-view="' + parts[0] + '"]')){
      current.view = parts[0];
    }
    if (parts[1] && LAYERS.indexOf(parts[1]) !== -1){ current.layer = parts[1]; }
  }

  document.addEventListener('click', function(ev){
    var nav = ev.target.closest('[data-nav]');
    if (nav){ current.layer = nav.getAttribute('data-nav'); apply(); return; }
    var view = ev.target.closest('[data-viewbtn]');
    if (view){ current.view = view.getAttribute('data-viewbtn'); apply(); }
  });

  window.addEventListener('hashchange', function(){ fromHash(); apply(); });
  fromHash();
  apply();
})();
</script>"""


def build_view(name: str, scoped: bool) -> str:
    layers = [("day", layer_day(scoped)), ("stores", layer_stores(scoped)),
              ("departments", layer_departments(scoped)), ("detail", layer_detail(scoped))]
    inner = "".join(
        f'<div class="layer" data-layer="{k}"{"" if i == 0 else " hidden"}>{v}'
        f'{CAVEATS if k == "day" else ""}</div>'
        for i, (k, v) in enumerate(layers))
    return (f'<div class="view" data-view="{name}"{"" if name == "all" else " hidden"}>'
            f'{inner}</div>')


HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Sales &mdash; reference dashboard</title>
<style>{STYLE}</style>
</head>
<body>
<div class="app">
  <nav class="rail" aria-label="Sections">
    <div class="mark">AI</div>
    <div class="grp">Report</div>
    <button data-nav="day" aria-current="true">The day</button>
    <button data-nav="stores">Stores</button>
    <button data-nav="departments">Departments</button>
    <button data-nav="detail">Detail</button>
    <div class="grp">View</div>
    <button data-viewbtn="all" aria-current="true">All areas</button>
    <button data-viewbtn="out">Outside the band only</button>
    <p class="foot">Reference design.<br>Figures are the live position for
      {e(LAST_DAY_TXT)}.</p>
  </nav>
<main><div class="page">
    <div class="masthead">
      <div>
        <p class="eyebrow">Sales &middot; Daily benchmark</p>
        <h1>Daily Sales</h1>
        <p class="asat">{e(DAY_LABEL)} &middot; scored against past
          {e(FACTS["anchor_dow"])}s in week {FACTS["week_of_month"]} of the month &middot;
          {e(STORES_TXT)} &middot; all figures in Saudi Riyals ({CUR}),
          before VAT</p>
      </div>
      <div class="seg" role="group" aria-label="View">
        <button data-viewbtn="all" aria-pressed="true">All areas</button>
        <button data-viewbtn="out" aria-pressed="false">Outside the band only</button>
      </div>
    </div>
{build_view("all", False)}
{build_view("out", True)}
    <p class="foot"><span>Every figure comes from the Daily Sales Dashboard report and has been
      checked against its own totals across all four levels. Nothing here is estimated.</span>
      <span>AI-assisted analysis</span></p>
  </div></main>
</div>
{SCRIPT}
</body>
</html>"""

if __name__ == "__main__":
    OUT.write_text(HTML, encoding="utf-8")
    print(f"wrote {OUT.name}  ({len(HTML):,} bytes)")
    print(f"  anchor          {DAY_LABEL}")
    print(f"  Net Sales       {F.CURRENCY} {OS.actual:,.2f}   band {OS.p20:,.2f} .. "
          f"{OS.p80:,.2f}   {OS.word}")
    print(f"  the two effects {BILLS_EFF:,.2f} (Bills) + {BASKET_EFF:,.2f} (Basket) = "
          f"{OS.vs_p50:,.2f}  [reconciles]")
    print(f"  store split     {S1.name} {S1.r('sales').gap:+,.2f} / "
          f"{S4.name} {S4.r('sales').gap:+,.2f}  = {OS.gap:+,.2f}  [reconciles]")
    print(f"  levels          {len(FACTS['departments'])} departments, "
          f"{len(FACTS['sections'])} sections, {len(FACTS['categories'])} categories")
    print(f"  outside band    {len(FACTS['below']['categories'])} categories below, "
          f"{len(FACTS['above']['categories'])} above")
