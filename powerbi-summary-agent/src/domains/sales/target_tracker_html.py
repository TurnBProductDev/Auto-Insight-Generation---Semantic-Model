"""Target Tracker - the page.

Renders the model from `target_tracker.py` into the four-layer dashboard approved as
`docs/dashboard-reference/reference_target_tracker.html`. Same shell as the inventory
dashboards: rail plus main and nothing else inside `.app`, layers, two views,
`#<view>/<layer>` in the URL.

Structure is code-owned (rulebook section 4). Prose slots carry grounded deterministic
sentences; an LLM may replace those strings and nothing else.

Three period states are handled, because the live model produces all three:

* **mid-period** - the reference case. Catch-up arithmetic is shown.
* **period complete** - the anchor is the last day of the week or month. There is nothing
  to catch up, so the block reports the outcome instead of printing a negative "still
  needed" figure.
* **no run of misses** - the surplus is described as built over the month rather than
  invented into two halves. Rulebook section 7: do not manufacture problems.
"""

from __future__ import annotations

import datetime as _dt
import html as _html

from .target_tracker import fmt_date

TEAL, TEAL_DK = "#0f9f95", "#087f79"
AMBER, AMBER_DK = "#c08429", "#8a5f10"
RED, GREEN, FAINT, MID = "#cf4636", "#2f8f4e", "#8fa1a9", "#41545a"
BAND_COL = {"good": GREEN, "warn": AMBER, "crit": RED, "none": FAINT}
BAND_WORD = {"good": "On target", "warn": "Watch", "crit": "Below target", "none": "No target set"}


def e(value) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def money(value) -> str:
    value = float(value or 0.0)
    size = abs(value)
    if size >= 1_000_000:
        return f"{value/1_000_000:.2f}M"
    if size >= 1_000:
        return f"{value/1_000:.1f}K"
    return f"{value:,.0f}"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    """`1 branch is`, `3 branches are`. Written out because the report is read by people."""
    return singular if count == 1 else (plural_form or singular + "s")


def verb(count: int) -> str:
    return "is" if count == 1 else "are"


def name_list(names) -> str:
    """`A`, `A and B`, `A, B and C`."""
    names = list(names)
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + " and " + names[-1]


def pc(value, dp=1) -> str:
    return "not available" if value is None else f"{float(value):.{dp}f}%"


class _R:
    """Small render context so the currency is not threaded through forty calls."""

    def __init__(self, currency: str):
        self.cur = currency

    def m(self, value) -> str:
        return f"{self.cur}&nbsp;{money(value)}"

    def signed(self, value) -> str:
        return f"{self.cur}&nbsp;" + ("+" if float(value or 0) >= 0 else "&minus;") + money(abs(float(value or 0)))


# ---------------------------------------------------------------------------
# components
# ---------------------------------------------------------------------------
def sect(title, sub):
    return f'<div class="sect"><h2>{e(title)}</h2><span>{e(sub)}</span></div>'


def card(title, sub, body, note=""):
    tail = f'<p class="note">{note}</p>' if note else ""
    return f'<section class="card"><h3>{e(title)}</h3><p class="sub">{e(sub)}</p>{body}{tail}</section>'


def meter(attain, band):
    if attain is None:
        return '<div class="meter"><div class="meter-fill" style="width:0"></div></div>'
    top = max(125.0, attain * 1.05)
    return (f'<div class="meter" role="img" aria-label="{pc(attain)} of target">'
            f'<div class="meter-fill" style="width:{min(attain/top*100,100):.1f}%;'
            f'background:{BAND_COL[band]}"></div>'
            f'<div class="meter-tick" style="left:{100/top*100:.1f}%"><span>Target</span></div></div>')


def scorecard(r: _R, p: dict):
    gap = p["variance"]
    col = BAND_COL[p["band"]] if gap < 0 else GREEN
    return (f'<div class="scorecard">'
            f'<div class="sc-cell"><div class="sc-label">Sold</div>'
            f'<div class="sc-value">{r.m(p["actual"])}</div></div>'
            f'<div class="sc-cell"><div class="sc-label">Target</div>'
            f'<div class="sc-value sc-muted">{r.m(p["target"])}</div></div>'
            f'<div class="sc-cell"><div class="sc-label">Reached</div>'
            f'<div class="sc-value" style="color:{BAND_COL[p["band"]]}">{pc(p["attainment"])}</div></div>'
            f'<div class="sc-cell"><div class="sc-label">'
            f'{"Above target" if gap >= 0 else "Below target"}</div>'
            f'<div class="sc-value" style="color:{col}">{r.m(abs(gap))}</div></div></div>'
            + meter(p["attainment"], p["band"])
            + f'<div class="meter-note">{e(p["elapsed"])} &middot; {e(p["when"])}</div>')


def period_kpis(r: _R, model: dict, tags: dict):
    out = []
    for key in ("day", "wtd", "mtd", "ytd"):
        p = model["periods"][key]
        gap = p["variance"]
        out.append(
            f'<div class="kpi {p["band"]}">'
            f'<p class="lab">{e(p["name"])}<br><span class="lab-sub">{e(p["when"])}</span></p>'
            f'<p class="val">{pc(p["attainment"])}</p>'
            f'<p class="sub">{r.m(p["actual"])} sold against a target of {r.m(p["target"])}<br>'
            f'{r.m(abs(gap))} {"above" if gap >= 0 else "below"} target &middot; {tags.get(key, "")}</p>'
            f'<span class="pill pill-{"ok" if p["band"] == "good" else p["band"]}">'
            f'{BAND_WORD[p["band"]]}</span></div>')
    return f'<div class="kpis k4">{"".join(out)}</div>'


def attainment_bars(r: _R, rows, scope):
    out = []
    for row in rows:
        s = row[scope]
        if s["attainment"] is None:
            continue
        out.append(
            f'<div class="rb"><div class="rb-l">{e(row["name"])}'
            f'<small>{r.m(s["actual"])} of {r.m(s["target"])}</small></div>'
            f'<div class="rb-t tick100"><span class="rb-f" style="width:'
            f'{min(s["attainment"],125)/125*100:.1f}%;background:{BAND_COL[s["band"]]}"></span></div>'
            f'<div class="rb-v" style="color:{BAND_COL[s["band"]]}">{pc(s["attainment"])}'
            f'<small class="{"under" if s["variance"] >= 0 else "over"}">'
            f'{r.signed(s["variance"])}</small></div></div>')
    return f'<div class="rbars">{"".join(out)}</div>'


def callout(kind, title, body):
    mark = {"action": "&#9654;", "risk": "!", "context": "i"}[kind]
    return (f'<aside class="callout callout-{kind}"><div class="callout-mark">{mark}</div>'
            f'<div><h3>{e(title)}</h3><p>{body}</p></div></aside>')


# ---------------------------------------------------------------------------
# charts
# ---------------------------------------------------------------------------
def chart_days(r: _R, model: dict) -> str:
    days = model["days"]
    if not days:
        return ""
    w, h = 1240, 330
    l, rr, t, b = 60, 18, 34, 60
    pw, ph = w - l - rr, h - t - b
    step = pw / len(days)
    bw = step * 0.58
    mx = max(max(d["actual"], d["target"]) for d in days) or 1.0
    parts = []
    for g in range(1, 4):
        y = t + ph - ph * g / 3
        parts.append(f'<line x1="{l}" y1="{y:.1f}" x2="{w-rr}" y2="{y:.1f}" stroke="#eef2f6"/>')
        parts.append(f'<text x="{l-8}" y="{y+3.5:.1f}" text-anchor="end" class="dz">{money(mx*g/3)}</text>')
    parts.append(f'<line x1="{l}" y1="{t+ph}" x2="{w-rr}" y2="{t+ph}" stroke="#dfe7ec"/>')
    split_at = model["surplus"]["earlier_days"]
    for i, d in enumerate(days):
        x = l + i * step + (step - bw) / 2
        bh = d["actual"] / mx * ph
        col = BAND_COL[d["band"]]
        recent = i >= split_at
        parts.append(
            f'<rect x="{x:.1f}" y="{t+ph-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2.5" '
            f'fill="{col}" opacity="{1 if recent else 0.72}"><title>{e(d["dow"])} {d["day"]} - '
            f'sold {r.cur} {money(d["actual"])}, target {r.cur} {money(d["target"])}, '
            f'{pc(d["attainment"])}</title></rect>')
        ty = t + ph - d["target"] / mx * ph
        parts.append(f'<line x1="{x-2.5:.1f}" y1="{ty:.1f}" x2="{x+bw+2.5:.1f}" y2="{ty:.1f}" '
                     f'stroke="{MID}" stroke-width="1.8" stroke-linecap="round"/>')
        label = f'{d["dow"]} {d["day"]}' if len(days) <= 20 else str(d["day"])
        parts.append(f'<text x="{l+(i+.5)*step:.1f}" y="{h-34}" text-anchor="middle" '
                     f'class="dzday">{e(label)}</text>')
        if len(days) <= 20:
            parts.append(f'<text x="{l+(i+.5)*step:.1f}" y="{h-17}" text-anchor="middle" '
                         f'class="dzpc" fill="{col}">{d["attainment"]:.0f}%</text>')
    if 0 < split_at < len(days):
        sx = l + split_at * step
        parts.append(f'<line x1="{sx:.1f}" y1="{t-6}" x2="{sx:.1f}" y2="{t+ph}" stroke="{RED}" '
                     f'stroke-width="1.2" stroke-dasharray="3 3"/>')
        parts.append(f'<text x="{sx-8:.1f}" y="{t-14}" text-anchor="end" class="dzann" '
                     f'fill="{MID}">built up {r.cur} {money(model["surplus"]["built"])}</text>')
        parts.append(f'<text x="{sx+8:.1f}" y="{t-14}" class="dzann" fill="{RED}">'
                     f'{model["run"]["length"]} days below target in a row, '
                     f'{r.cur} {money(model["surplus"]["given_back"])} used up</text>')
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Sales each day against its own '
            f'target">{"".join(parts)}</svg>')


def best_worst_days(r: _R, model: dict) -> str:
    """Which days carried the month and which cost it. Used when there is no run of
    consecutive misses to describe, where the surplus waterfall would show nothing."""
    days = [d for d in model["days"] if d["attainment"] is not None]
    if not days:
        return ""
    best = sorted(days, key=lambda d: d["variance"], reverse=True)[:3]
    worst = sorted(days, key=lambda d: d["variance"])[:3]
    def rows(entries, positive):
        span = max(abs(d["variance"]) for d in days) or 1.0
        out = ""
        for d in entries:
            gap = d["variance"]
            col = GREEN if positive else RED
            out += (f'<div class="rb rb-short"><div class="rb-l">{e(d["dow"])} {d["day"]}</div>'
                    f'<div class="rb-t"><span class="rb-f" style="width:'
                    f'{abs(gap)/span*100:.1f}%;background:{col}"></span></div>'
                    f'<div class="rb-v" style="color:{col}">{r.signed(gap)}'
                    f'<small class="under">{pc(d["attainment"])}</small></div></div>')
        return out
    return (f'<p class="mini-head">Biggest days above target</p><div class="rbars">{rows(best, True)}</div>'
            f'<p class="mini-head" style="margin-top:14px">Biggest days below target</p>'
            f'<div class="rbars">{rows(worst, False)}</div>')


def chart_surplus(r: _R, model: dict) -> str:
    s = model["surplus"]
    steps = [("Built up", s["built"], TEAL), ("Used up", -s["given_back"], RED),
             ("Surplus now", s["now"], TEAL_DK)]
    w, h = 560, 250
    l, rr, t, b = 20, 20, 32, 52
    pw, ph = w - l - rr, h - t - b
    step = pw / 3
    bw = step * 0.5
    mx = max(abs(v) for _, v, _ in steps) * 1.15 or 1.0
    parts = [f'<line x1="{l}" y1="{t+ph}" x2="{w-rr}" y2="{t+ph}" stroke="#dfe7ec"/>']
    for i, (name, val, col) in enumerate(steps):
        x = l + i * step + (step - bw) / 2
        bh = abs(val) / mx * ph
        parts.append(f'<rect x="{x:.1f}" y="{t+ph-bh:.1f}" width="{bw:.1f}" height="{max(bh,3):.1f}" '
                     f'rx="2.5" fill="{col}"><title>{name}: {r.cur} {money(val)}</title></rect>')
        sign = "+" if val >= 0 else "−"
        parts.append(f'<text x="{x+bw/2:.1f}" y="{t+ph-bh-8:.1f}" text-anchor="middle" '
                     f'class="dzv" fill="{col}">{sign}{money(abs(val))}</text>')
        parts.append(f'<text x="{x+bw/2:.1f}" y="{h-30}" text-anchor="middle" class="dz">{e(name)}</text>')
    if s["share_given_back"]:
        parts.append(f'<text x="{w/2:.1f}" y="{h-10}" text-anchor="middle" class="dza">'
                     f'{s["share_given_back"]:.0f}% of the surplus has already gone</text>')
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="How the surplus this month has '
            f'moved">{"".join(parts)}</svg>')


def chart_series(points, label, partial_last=False) -> str:
    """A compact attainment line - weeks or months."""
    if len(points) < 2:
        return ""
    w, h = 900, 360
    l, rr, t, b = 66, 24, 30, 78
    pw, ph = w - l - rr, h - t - b
    vals = [v for _, v, _ in points]
    lo, hi = min(min(vals), 88.0) - 4, max(max(vals), 112.0) + 4
    yy = lambda v: t + ph - (v - lo) / (hi - lo) * ph
    xx = lambda i: l + (i + .5) * (pw / len(points))
    parts = []
    for g in (90, 100, 110, 120):
        if lo <= g <= hi:
            y = yy(g)
            solid = g == 100
            dash = "" if solid else ' stroke-dasharray="3 4"'
            parts.append(f'<line x1="{l}" y1="{y:.1f}" x2="{w-rr}" y2="{y:.1f}" '
                         f'stroke="{TEAL if solid else "#dfe7ec"}" '
                         f'stroke-width="{2 if solid else 1}"{dash}/>')
            parts.append(f'<text x="{l-10}" y="{y+4:.1f}" text-anchor="end" class="dz">{g}%</text>')
    parts.append('<polyline points="' + " ".join(f"{xx(i):.1f},{yy(v):.1f}" for i, v in enumerate(vals))
                 + f'" fill="none" stroke="{TEAL_DK}" stroke-width="2.6" stroke-linejoin="round"/>')
    for i, (name, v, band) in enumerate(points):
        col = BAND_COL[band]
        last = partial_last and i == len(points) - 1
        parts.append(f'<circle cx="{xx(i):.1f}" cy="{yy(v):.1f}" r="{7 if last else 6}" '
                     f'fill="{"#fff" if last else col}" stroke="{col}" stroke-width="3">'
                     f'<title>{e(name)} - {pc(v)}</title></circle>')
        parts.append(f'<text x="{xx(i):.1f}" y="{h-46}" text-anchor="middle" class="dz">{e(name)}</text>')
        parts.append(f'<text x="{xx(i):.1f}" y="{h-26}" text-anchor="middle" class="dzpc" '
                     f'fill="{col}">{v:.0f}%</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{e(label)}">{"".join(parts)}</svg>'


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
def branch_table(r: _R, rows) -> str:
    body = ""
    for b in rows:
        cells = ""
        for scope in ("day", "wtd", "mtd", "ytd"):
            s = b[scope]
            cells += (f'<td class="n" style="color:{BAND_COL[s["band"]]};font-weight:700">'
                      f'{pc(s["attainment"])}</td>')
        close = b["close"]
        needed = close["needed"]
        rate = close["needed_vs_target"]
        rate_cell = (f'<td class="n" style="font-weight:700;color:'
                     f'{RED if (rate or 0) > 100 else MID}">{pc(rate)}</td>'
                     if rate is not None else '<td class="n muted">period complete</td>')
        needed_cell = (f'<td class="n">{r.m(needed)}</td>' if needed > 0
                       else '<td class="n muted">met</td>')
        urgent = ' class="urgent"' if b["mtd"]["band"] == "crit" else ""
        body += (f'<tr{urgent}><td><b>{e(b["name"])}</b></td>{cells}'
                 f'<td class="n">{r.signed(b["mtd"]["variance"])}</td>{needed_cell}{rate_cell}</tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Branch</th><th class="n">Today</th>'
            f'<th class="n">This week</th><th class="n">This month</th><th class="n">This year</th>'
            f'<th class="n">Above/below target</th><th class="n">Still needed</th>'
            f'<th class="n">Needed vs target</th></tr></thead><tbody>{body}</tbody></table></div>')


def dept_table(r: _R, rows) -> str:
    body = ""
    for d in rows:
        urgent = ' class="urgent"' if d["mtd"]["band"] == "crit" else ""
        body += (f'<tr{urgent}><td><b>{e(d["name"])}</b></td>'
                 f'<td class="n" style="color:{BAND_COL[d["day"]["band"]]};font-weight:700">'
                 f'{pc(d["day"]["attainment"])}</td>'
                 f'<td class="n" style="color:{BAND_COL[d["wtd"]["band"]]};font-weight:700">'
                 f'{pc(d["wtd"]["attainment"])}</td>'
                 f'<td class="n">{r.signed(d["wtd"]["variance"])}</td>'
                 f'<td class="n" style="color:{BAND_COL[d["mtd"]["band"]]};font-weight:700">'
                 f'{pc(d["mtd"]["attainment"])}</td>'
                 f'<td class="n">{r.signed(d["mtd"]["variance"])}</td>'
                 f'<td class="n muted">{r.m(d["mtd"]["actual"])}</td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Department</th><th class="n">Today</th>'
            f'<th class="n">This week</th><th class="n">Above/below</th><th class="n">This month</th>'
            f'<th class="n">Above/below</th><th class="n">Sold this month</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def section_table(r: _R, rows) -> str:
    body = ""
    for s in rows:
        m = s["mtd"]
        urgent = ' class="urgent"' if m["band"] == "crit" else ""
        body += (f'<tr{urgent}><td><b>{e(s["name"])}</b><br>'
                 f'<span class="act">{e(s.get("department"))}</span></td>'
                 f'<td class="n">{r.m(m["actual"])}</td><td class="n">{r.m(m["target"])}</td>'
                 f'<td class="n" style="color:{BAND_COL[m["band"]]};font-weight:700">'
                 f'{pc(m["attainment"])}</td><td class="n">{r.signed(m["variance"])}</td>'
                 f'<td><span class="pill pill-{"ok" if m["band"] == "good" else m["band"]}">'
                 f'{BAND_WORD[m["band"]]}</span></td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Section</th>'
            f'<th class="n">Sold this month</th><th class="n">Target</th><th class="n">% of target</th>'
            f'<th class="n">Above/below</th><th>Status</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


# ---------------------------------------------------------------------------
# prose - deterministic, grounded. An LLM may replace these strings only.
# ---------------------------------------------------------------------------
def _share_words(share: float) -> str:
    """A fraction a general reader can picture, falling back to the percentage."""
    for low, high, words in ((22, 28, "about a quarter"), (28, 39, "about one-third"),
                             (44, 56, "about half"), (60, 72, "about two-thirds"),
                             (72, 80, "about three-quarters")):
        if low <= share < high:
            return words
    return f"{share:.0f}%"


def headline(r: _R, model: dict) -> str:
    run = model["run"]
    s = model["surplus"]
    mtd = model["periods"]["mtd"]
    month_done = model["days_elapsed"] >= model["days_in_month"]
    if run["length"] >= 3 and s["share_given_back"]:
        return (f"{run['length']} days below target have used up "
                f"{_share_words(s['share_given_back'])} of this month's surplus.")
    if month_done:
        month = _dt.date.fromisoformat(model["anchor"]).strftime("%B")
        direction = "above" if mtd["variance"] >= 0 else "below"
        return (f"{month} finished {direction} target at {pc(mtd['attainment'])}, "
                f"{money(abs(mtd['variance']))} {'ahead of' if mtd['variance'] >= 0 else 'short of'} plan.")
    left = model["days_in_month"] - model["days_elapsed"]
    if mtd["variance"] >= 0:
        return (f"The month is {pc(mtd['attainment'])} of target with a surplus of "
                f"{money(mtd['variance'])} and {left} days left.")
    return (f"The month is {pc(mtd['attainment'])} of target and "
            f"{money(abs(mtd['variance']))} behind with {left} days left.")


def hero_narrative(r: _R, model: dict) -> str:
    run, s, mtd = model["run"], model["surplus"], model["periods"]["mtd"]
    month_done = model["days_elapsed"] >= model["days_in_month"]
    if run["length"] >= 3 and s["exhausts_on"]:
        return (f"The month is still performing above target at {pc(mtd['attainment'])}, with a surplus "
                f"of {r.m(mtd['variance'])}. However, most of that surplus was built earlier in the "
                f"month, and the last {run['length']} days of below-target sales have used up about "
                f"{s['share_given_back']:.0f}% of it. If sales continue at the current rate, the "
                f"remaining surplus could be fully used up by around "
                f"{fmt_date(_dt.date.fromisoformat(s['exhausts_on']), 'medium')}.")
    if month_done:
        hit = model["days_hit"]
        return (f"The month is complete. {hit} of its {model['days_elapsed']} days reached their own "
                f"target, and the month as a whole finished {r.m(abs(mtd['variance']))} "
                f"{'above' if mtd['variance'] >= 0 else 'below'} plan at {pc(mtd['attainment'])}. "
                f"This is a review rather than a decision aid - there are no days left to change it.")
    left = model["days_in_month"] - model["days_elapsed"]
    rate = model["month_close"]["needed_vs_target"]
    return (f"{model['days_hit']} of the {model['days_elapsed']} days so far reached their target. "
            f"With {left} days left, the rest of the month needs to sell "
            f"{pc(rate)} of what those days are already targeted to sell.")


def _close_block(r: _R, model: dict, which: str) -> str:
    """The catch-up arithmetic, or an honest statement that the period is over."""
    close = model[f"{which}_close"]
    period = "week" if which == "week" else "month"
    label = "This week" if which == "week" else "This month"
    if close["needed_vs_target"] is None or close["remaining_target"] <= 0:
        p = model["periods"]["wtd" if which == "week" else "mtd"]
        elapsed, total = (p["elapsed"].split(" days of ") + ["", ""])[:2]
        truncated = which == "week" and elapsed.strip().isdigit() and total.strip().isdigit()             and int(elapsed) < int(total)
        heading = (f"{label} cannot be tracked further" if truncated else f"{label} is complete")
        sub = (f"The {period} still has days to run, but none of them carries a target."
               if truncated else f"No days are left in the {period} that carry a target.")
        return card(
            heading, sub,
            f'<div class="closeout"><div><b>{r.m(p["actual"])}</b>'
            f'<span>sold across the {period} '
            f'{"so far" if truncated else "in total"}</span></div>'
            f'<div><b style="color:{BAND_COL[p["band"]]}">{pc(p["attainment"])}</b>'
            f'<span>of the {period} target of {r.m(p["target"])}</span></div></div>',
            note=(f"Measured over the days that do carry a target, the {period} is "
                  f"{r.m(abs(p['variance']))} "
                  f"{'above' if p['variance'] >= 0 else 'below'} target."
                  if truncated else
                  f"The {period} finished {r.m(abs(p['variance']))} "
                  f"{'above' if p['variance'] >= 0 else 'below'} target. Nothing here can still be "
                  f"changed, so this section is a record rather than an instruction."))
    rate = close["needed_vs_target"]
    days_left = (len(model["remaining_week_days"]) if which == "week"
                 else model["days_in_month"] - model["days_elapsed"])
    rows = ""
    if which == "week":
        for d in model["remaining_week_days"]:
            share = (d["target"] / close["remaining_target"] * 100.0) if close["remaining_target"] else 0
            rows += (f'<div class="rb rb-short"><div class="rb-l">{e(d["dow"])} '
                     f'{e(_dt.date.fromisoformat(d["date"]).day)}</div>'
                     f'<div class="rb-t"><span class="rb-f" style="width:{share:.1f}%;'
                     f'background:{FAINT}"></span></div><div class="rb-v">{r.m(d["target"])}</div></div>')
    over = rate > 100
    return card(
        f"{label}", f"{days_left} days are left. Together they are targeted to sell "
                    f"{r.cur} {money(close['remaining_target'])}.",
        f'<div class="closeout"><div><b>{r.m(close["needed"])}</b>'
        f'<span>must be sold in the days that are left to reach the {period} target</span></div>'
        f'<div><b style="color:{RED if over else GREEN}">{pc(rate)}</b>'
        f'<span>of what those days are targeted to sell, so they '
        f'{"need to beat target" if over else "can sell a little under target and still get there"}'
        f'</span></div></div>{rows}',
        note=(f"Reaching the {period} target now needs more than the remaining days were planned to "
              f"deliver." if over else
              f"There is headroom: the remaining days can sell {pc(100 - rate)} below their own "
              f"target and the {period} would still land on plan."))


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------
def _tags(model: dict) -> dict:
    run = model["run"]
    behind_wtd = sum(1 for b in model["branches"] if b["wtd"]["band"] == "crit")
    return {
        "day": (f"{run['length']}th day below target in a row" if run["length"] >= 2
                else ("below target" if model["periods"]["day"]["variance"] < 0 else "above target")),
        "wtd": (f"{behind_wtd} of {len(model['branches'])} branches below target"
                if behind_wtd else "all branches at or above target"),
        "mtd": ("the surplus that is left" if model["periods"]["mtd"]["variance"] >= 0
                else "behind for the month"),
        "ytd": ("no risk to the year" if model["periods"]["ytd"]["variance"] >= 0
                else "the year is behind"),
    }


def layer_performance(r: _R, model: dict, behind: bool) -> str:
    day = model["periods"]["day"]
    run, s = model["run"], model["surplus"]
    day_sorted = sorted(model["branches"], key=lambda b: b["day"]["attainment"] or 0)
    if behind:
        day_sorted = [b for b in day_sorted if b["day"]["band"] != "good"]
    worst = day_sorted[0] if day_sorted else None
    prose = model.get("prose") or {}
    hero_h = ("Every branch is below target this week." if behind
              else (prose.get("headline") or headline(r, model)))
    hero_p = (("The totals below still cover the whole business; only the breakdowns are filtered.")
              if behind else (prose.get("narrative") or hero_narrative(r, model)))
    hero = f"""<section class="hero">
      <div>
        <span class="hero-tag">Sales against target</span>
        <h2>{e(hero_h)}</h2>
        <p>{hero_p}</p>
      </div>
      <div class="hero-stats">
        <div class="hs {'crit' if day['band'] != 'good' else ''}"><b>{pc(day['attainment'])}</b>
          <span>of target today</span></div>
        <div class="hs {'crit' if model['periods']['wtd']['band'] != 'good' else ''}">
          <b>{pc(model['periods']['wtd']['attainment'])}</b><span>of target this week</span></div>
        <div class="hs"><b>{pc(model['periods']['mtd']['attainment'])}</b>
          <span>of target this month</span></div>
      </div>
    </section>"""
    scoped = ('<div class="scoped">Showing only the branches, departments and sections that are '
              '<b>below target</b>. The totals still cover the whole business.</div>' if behind else "")

    surplus_card = ""
    if run["length"] and s["built"] > 0:
        note = (f"Over the last {run['length']} days, sales fell short of target by an average of "
                f"{r.m(run['average_shortfall'])} a day. At that rate the {r.m(s['now'])} still left "
                + (f"would run out in about <b>{s['days_until_exhausted']:.1f} days</b> &mdash; around "
                   f"<b>{fmt_date(_dt.date.fromisoformat(s['exhausts_on']), 'medium')}</b>."
                   if s["exhausts_on"] else "would last beyond the end of the month."))
        surplus_card = card("How much of the surplus is left",
                            "The surplus so far this month, split into what was built up and what has been used.",
                            chart_surplus(r, model),
                            note=(prose.get("month_note") or note) if not behind else note)
    else:
        mtd_var = model["periods"]["mtd"]["variance"]
        surplus_card = card(
            "Which days carried the month",
            "The three days furthest above their target, and the three furthest below.",
            best_worst_days(r, model),
            note=(prose.get("month_note") if not behind else "") or
                 (f"{model['days_hit']} of the {model['days_elapsed']} days reached their own target, "
                  f"yet the month finished {r.m(abs(mtd_var))} "
                  f"{'above' if mtd_var >= 0 else 'below'} plan &mdash; so a small number of large "
                  f"days did the work. There is no run of consecutive misses to report."))

    if worst and worst["day"]["variance"] < 0:
        total_short = sum(abs(b["day"]["variance"]) for b in model["branches"]
                          if b["day"]["variance"] < 0)
        company = abs(day["variance"]) or 1.0
        note = (f"{e(worst['name'])} alone fell {r.m(abs(worst['day']['variance']))} short"
                + (f", which is more than the whole company's shortfall of {r.m(company)} &mdash; "
                   f"so if it had reached its target the business as a whole would have finished the "
                   f"day above target."
                   if abs(worst["day"]["variance"]) > company and day["variance"] < 0
                   else f", {abs(worst['day']['variance'])/total_short*100:.0f}% of the shortfall "
                        f"across the branches that missed."))
    else:
        note = "Every branch reached its target today."
    today_card = card(
        "Which branches missed target today" if behind else "How each branch did today",
        "The bar shows how much of its target each branch reached; the line marks 100%.",
        attainment_bars(r, day_sorted, "day"),
        note=(prose.get("today_note") or note) if not behind else note)

    return f"""{hero}{scoped}
    {sect("How we are doing right now", "all four time periods, most important first")}
    {period_kpis(r, model, _tags(model))}
    <p class="note" style="margin-top:10px">Each period is compared with the target for the days that
    have already passed, not with the target for the whole period. That is what makes the four
    percentages comparable with each other.</p>
    {sect("What has happened", "how today affected the week, and the week affected the month")}
    <div style="margin-bottom:14px">
      {card("Sales each day this month, against that day's target",
            "Each column is one day's sales. The dark line across it is the target for that day."
            + (" The percentage below shows how much of that target was reached." if len(model['days']) <= 20 else ""),
            chart_days(r, model),
            note=f"{model['days_hit']} of the {model['days_elapsed']} days so far met their target.")}
    </div>
    <div class="grid g-2e">{surplus_card}{today_card}</div>
    {sect("What is needed to catch up", "the maths, for this week and this month")}
    <div class="grid g-2e">{_close_block(r, model, "week")}{_close_block(r, model, "month")}</div>"""


def layer_branches(r: _R, model: dict, behind: bool) -> str:
    rows = model["branches"]
    if behind:
        rows = [b for b in rows if b["mtd"]["band"] != "good"] or rows
    wtd_sorted = sorted(model["branches"], key=lambda b: b["wtd"]["attainment"] or 0)
    if behind:
        wtd_sorted = [b for b in wtd_sorted if b["wtd"]["band"] != "good"] or wtd_sorted
    behind_month = [b for b in model["branches"] if b["mtd"]["band"] == "crit"]
    note = (f"{', '.join(b['name'] for b in behind_month)} "
            f"{'is' if len(behind_month) == 1 else 'are'} below target for the month."
            if behind_month else "Every branch is at or above target for the month.")
    return f"""{sect("Branch performance", "how each branch is doing")}
    <div class="grid g-2">
      {card("How each branch is doing this month",
            "The bar shows how much of its target each branch has reached so far. The line marks 100%.",
            attainment_bars(r, rows, "mtd"), note=note)}
      {card("How each branch is doing this week",
            "The same branches over the current week.",
            attainment_bars(r, wtd_sorted, "wtd"),
            note=f"{sum(1 for b in model['branches'] if b['wtd']['band'] == 'crit')} of "
                 f"{len(model['branches'])} branches are below target this week.")}
    </div>
    <div style="margin-top:14px">
      {card("Full branch figures",
            "How each branch is performing over each time period, and what it still needs to sell.",
            branch_table(r, rows),
            note="&ldquo;Still needed&rdquo; is the full month target minus what the branch has sold "
                 "so far. &ldquo;Needed vs target&rdquo; shows that as a percentage of what the "
                 "remaining days are already targeted to sell. Above 100% means the branch has to "
                 "sell more than its plan to catch up.")}
    </div>"""


def layer_departments(r: _R, model: dict, behind: bool) -> str:
    wtd = sorted(model["departments"], key=lambda d: d["wtd"]["attainment"] or 0)
    mtd = sorted(model["departments"], key=lambda d: d["mtd"]["attainment"] or 0)
    if behind:
        wtd = [d for d in wtd if d["wtd"]["band"] != "good"] or wtd
        mtd = [d for d in mtd if d["mtd"]["band"] != "good"] or mtd
    below_w = sum(1 for d in model["departments"] if (d["wtd"]["attainment"] or 0) < 100)
    below_m = sum(1 for d in model["departments"] if (d["mtd"]["attainment"] or 0) < 100)
    return f"""{sect("Department performance", "where the month is being won and lost")}
    <div class="grid g-2">
      {card("This week so far", "Ranked from worst to best.", attainment_bars(r, wtd, "wtd"),
            note=f"{below_w} of the {len(model['departments'])} departments are below target this week.")}
      {card("This month so far", "The same departments measured over the whole month.",
            attainment_bars(r, mtd, "mtd"),
            note=f"{below_m} of the {len(model['departments'])} departments are below target for the month.")}
    </div>
    <div style="margin-top:14px">
      {card("Full department figures", "Every trading department, across each time period.",
            dept_table(r, mtd))}
    </div>"""


def layer_detail(r: _R, model: dict, behind: bool) -> str:
    sections = sorted(model["sections"], key=lambda s: s["mtd"]["attainment"] or 0)
    if behind:
        sections = [s for s in sections if s["mtd"]["band"] != "good"] or sections
    else:
        sections = sections[:6] + sections[-4:] if len(sections) > 12 else sections
        sections = sorted(sections, key=lambda s: s["mtd"]["attainment"] or 0)
    weeks = model["weeks"][-8:]
    week_points = [(f"wk{w['number']}", w["attainment"], w["band"]) for w in weeks]
    month_points = [(m["name"][:3], m["attainment"], m["band"]) for m in model["months"]]
    prev = model["prev_week"]
    return f"""{sect("More detail", "sections, weeks and months")}
    <div style="margin-bottom:14px">
      {card("Sections that stand out",
            "Sections below their target this month." if behind else
            "The sections furthest below their target this month, and the furthest above.",
            section_table(r, sections),
            note="Section targets are set for each branch and added together here. A section can be "
                 "below target while its department is above, which is why both are shown.")}
    </div>
    <div class="grid g-2e">
      {card("Week-by-week performance", f"The last {len(weeks)} weeks.",
            chart_series(week_points, "How much of target was reached each week",
                         partial_last=weeks[-1]["days"] < 7 if weeks else False),
            note=f"The previous complete week finished at {pc(prev['attainment'])} of target, "
                 f"{r.m(abs(prev['variance']))} "
                 f"{'above' if prev['variance'] >= 0 else 'below'} it.")}
      {card("Month-by-month performance", "How much of target each month reached.",
            chart_series(month_points, "How much of target was reached each month",
                         partial_last=model["days_elapsed"] < model["days_in_month"]),
            note=f"{sum(1 for m in model['months'] if (m['attainment'] or 0) >= 100)} of the "
                 f"{len(model['months'])} months so far reached target.")}
    </div>"""


def caveats(r: _R, model: dict) -> str:
    items = [
        "<b>There is no comparison with last year.</b> The report only holds 2026 data, so every "
        "figure here is compared with target, never with last year.",
        "<b>No causes are given, only amounts and places.</b> The report holds sales and targets. "
        "It does not hold promotions, stock levels, staffing or footfall, so nothing here explains "
        "<i>why</i> sales moved &mdash; only where the difference sits.",
        "<b>Each period is compared with the target for the days that have passed</b>, not with the "
        "target for the whole period. Full-period targets are used only in the "
        "&ldquo;what is needed to catch up&rdquo; figures, which say so.",
    ]
    if model.get("sales_lag_days"):
        # The reverse gap, which had no caveat at all: targets loaded ahead of
        # trade. Stated first because it changes what every percentage on the
        # page means.
        n = int(model["sales_lag_days"])
        items.insert(0, (
            f"<b>This report is dated "
            f"{fmt_date(_dt.date.fromisoformat(model['anchor']), 'medium')} "
            f"{_dt.date.fromisoformat(model['anchor']).year}"
            + ("</b>, the date this run was asked to report on. " if model.get("anchor_forced")
               else ", the most recent day that has both a target and recorded sales.</b> ")
            + f"Targets are set a further {n} {'day' if n == 1 else 'days'} ahead, to "
            f"{fmt_date(_dt.date.fromisoformat(model['targeted_through']), 'medium')}. "
            f"Those days have not traded yet, so they are excluded rather than counted "
            f"as elapsed with no sales against them."))
    if model["target_lag_days"]:
        items.insert(0, (
            f"<b>This report is dated {fmt_date(_dt.date.fromisoformat(model['anchor']), 'medium')} "
            f"{_dt.date.fromisoformat(model['anchor']).year}"
            + ("</b>, the date this run was asked to report on. " if model.get("anchor_forced")
               else ", the most recent day that has both a target and recorded sales.</b> ")
            + f"Sales have been recorded for a further "
            f"{model['target_lag_days']} days, up to "
            f"{fmt_date(_dt.date.fromisoformat(model['sold_through']), 'medium')}, but no target has "
            f"been set for them yet, so they cannot be measured against one."))
    excluded = [c for c in ("CFH022",) if c not in model["population"]]
    if excluded:
        items.append(f"<b>Branch {', '.join(excluded)} is not included</b>, matching how the Sales "
                     f"performance report treats it.")
    items.append("<b>Projections carry a current rate forward.</b> They are arithmetic, not "
                 "forecasts, and they assume the remaining days keep the targets they already have.")
    return ('<div class="caveats"><h3>Important things to know about these numbers</h3><ul>'
            + "".join(f"<li>{i}</li>" for i in items) + "</ul></div>")


STYLE = """
:root{--ground:#eef1f0;--card:#fff;--rail:#0e1b19;--ink:#12201e;--mid:#41545a;
 --muted:#5b7182;--faint:#8fa1a9;--line:#dfe7ec;--soft:#f7fafb;--teal:#0f9f95;--teal-dk:#087f79;
 --teal-tint:#e2f2ef;--amber:#c08429;--amber-tint:#faf1e1;--amber-dk:#8a5f10;--red:#cf4636;
 --red-tint:#fbeae7;--green:#2f8f4e;--green-tint:#e8f4ec;--r:12px;
 --shadow:0 1px 2px rgba(16,24,40,.05),0 10px 28px -20px rgba(16,24,40,.35)}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);font-family:'Segoe UI',Inter,Roboto,Arial,sans-serif;
 font-size:13.5px;line-height:1.5;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
h1,h2,h3,h4,p{margin:0}
.app{display:flex;min-height:100vh}
.rail{width:172px;flex:0 0 172px;background:var(--rail);color:#cfe0dc;padding:18px 12px;
 position:sticky;top:0;height:100vh;display:flex;flex-direction:column;gap:5px}
.rail .mark{width:34px;height:34px;border-radius:9px;background:rgba(15,159,149,.16);
 border:1px solid rgba(15,159,149,.5);color:#4fd3c4;display:grid;place-items:center;
 font-weight:800;font-size:12px;letter-spacing:.04em;margin-bottom:14px}
.rail .grp{font-size:9px;letter-spacing:.13em;text-transform:uppercase;color:#5f7d78;margin:14px 0 5px;padding-left:9px}
.rail button{all:unset;cursor:pointer;display:block;padding:8px 11px;border-radius:8px;font-size:12.5px;font-weight:600;color:#a9c2bd}
.rail button:hover{background:rgba(255,255,255,.06);color:#fff}
.rail button[aria-current=true]{background:var(--teal);color:#fff}
.rail .foot{margin-top:auto;font-size:10px;color:#4d6b66;line-height:1.45;padding-left:9px}
main{flex:1;min-width:0}
.page{max-width:1280px;margin:0 auto;padding:22px 26px 60px}
.masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap;margin-bottom:16px}
.eyebrow{font-size:9.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--teal-dk);font-weight:750;margin-bottom:5px}
h1{font-size:27px;line-height:1.12;letter-spacing:-.02em;font-weight:700}
.asat{font-size:12px;color:var(--muted);margin-top:5px}
.seg{display:inline-flex;background:var(--card);border:1px solid var(--line);border-radius:9px;padding:3px}
.seg button{all:unset;cursor:pointer;padding:6px 14px;border-radius:7px;font-size:12px;font-weight:650;color:var(--muted)}
.seg button[aria-pressed=true]{background:var(--teal-tint);color:var(--teal-dk)}
.hero{background:var(--rail);border-radius:var(--r);padding:20px 24px;margin-bottom:14px;
 display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:26px;align-items:center}
.hero-tag{display:inline-block;font-size:9px;letter-spacing:.12em;text-transform:uppercase;font-weight:750;
 color:#f0c46a;background:rgba(240,196,106,.14);padding:4px 9px;border-radius:6px;margin-bottom:10px}
.hero h2{color:#fff;font-size:23px;line-height:1.22;letter-spacing:-.015em;font-weight:700}
.hero p{color:#a9c2bd;font-size:12.5px;margin-top:8px;max-width:60ch}
.hero-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.hs{border-left:2px solid rgba(255,255,255,.14);padding-left:12px}
.hs b{display:block;color:#fff;font-size:19px;font-weight:700;line-height:1.15}
.hs span{display:block;color:#7f9a95;font-size:10.5px;margin-top:3px;line-height:1.35}
.hs.crit b{color:#ff8b73}
.grid{display:grid;gap:14px}
.g-2{grid-template-columns:minmax(0,1.55fr) minmax(0,1fr)}
.g-2e{grid-template-columns:repeat(2,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:16px 18px;box-shadow:var(--shadow)}
.card>h3{font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.card>.sub{font-size:11.5px;color:var(--muted);margin-top:2px;margin-bottom:12px}
.sect{margin:22px 0 10px;display:flex;align-items:baseline;gap:11px}
.sect h2{font-size:16px;font-weight:700;letter-spacing:-.015em}
.sect span{font-size:11.5px;color:var(--faint)}
.note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.55}
.note b{color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:11px}
.kpis.k4{grid-template-columns:repeat(4,minmax(0,1fr))}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:13px 14px 12px;
 position:relative;overflow:hidden;box-shadow:var(--shadow)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--faint)}
.kpi.crit::before{background:var(--red)}.kpi.warn::before{background:var(--amber)}.kpi.good::before{background:var(--green)}
.kpi .lab{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:650;min-height:26px}
.lab-sub{text-transform:none;letter-spacing:0;font-weight:500;color:var(--faint)}
.kpi .val{font-size:21px;font-weight:750;line-height:1.1;margin:5px 0 4px;letter-spacing:-.02em}
.kpi.crit .val{color:var(--red)}.kpi.warn .val{color:var(--amber-dk)}.kpi.good .val{color:var(--green)}
.kpi .sub{font-size:10.5px;color:var(--muted);line-height:1.4}
.pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;text-transform:uppercase;
 padding:2px 6px;border-radius:5px;margin-top:7px}
.pill-crit{background:var(--red-tint);color:var(--red)}
.pill-warn{background:var(--amber-tint);color:var(--amber-dk)}
.pill-ok{background:var(--green-tint);color:var(--green)}
.pill-none{background:#eef2f6;color:var(--muted)}
.scorecard{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border:1px solid var(--line);
 border-radius:2px;overflow:hidden;margin:18px 0 0;background:#fff}
.sc-cell{padding:18px 22px 16px;border-right:1px solid var(--line)}.sc-cell:last-child{border-right:0}
.sc-label{color:#8093a2;font-size:11.5px;font-weight:750;letter-spacing:.07em;text-transform:uppercase}
.sc-value{font-size:clamp(21px,2.1vw,28px);line-height:1.15;font-weight:760;letter-spacing:-.03em;margin-top:8px}
.sc-muted{color:var(--muted);font-weight:700}
.meter{position:relative;height:12px;margin:16px 0 0;border-radius:99px;background:#eef3f6}
.meter-fill{position:absolute;left:0;top:0;height:100%;border-radius:99px}
.meter-tick{position:absolute;top:-6px;height:24px;width:2px;background:var(--ink);opacity:.65}
.meter-tick span{position:absolute;top:26px;left:50%;transform:translateX(-50%);font-size:11px;
 font-weight:700;color:var(--muted);white-space:nowrap;letter-spacing:.04em;text-transform:uppercase}
.meter-note{margin:26px 0 0;color:#8496a5;font-size:12.5px}
.callout{display:grid;grid-template-columns:30px 1fr;gap:14px;margin:16px 0 0;padding:16px 20px 14px;
 border:1px solid var(--line);border-radius:var(--r);background:var(--soft)}
.callout-mark{display:grid;place-items:center;width:28px;height:28px;border-radius:8px;font-weight:750;font-size:14px}
.callout-action{border-left:3px solid var(--teal)}.callout-action .callout-mark{background:var(--teal-tint);color:var(--teal-dk)}
.callout-risk{border-left:3px solid var(--red)}.callout-risk .callout-mark{background:var(--red-tint);color:#b5262d}
.callout-context{border-left:3px solid var(--faint)}.callout-context .callout-mark{background:#eef3f6;color:#6b8394}
.callout h3{margin:2px 0 5px;font-size:13px}.callout p{margin:0;font-size:12.5px;line-height:1.6;color:var(--mid)}
.closeout{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:12px}
.closeout b{display:block;font-size:19px;font-weight:750;line-height:1.15;letter-spacing:-.02em}
.closeout span{display:block;font-size:10.5px;color:var(--muted);margin-top:3px;line-height:1.35}
.rbars{display:flex;flex-direction:column;gap:9px}
.rb{display:grid;grid-template-columns:132px minmax(0,1fr) 104px;gap:11px;align-items:center;font-size:12px}
.rb.rb-short{grid-template-columns:64px minmax(0,1fr) 96px}
.rb-l{font-weight:650}.rb-l small{display:block;font-weight:400;font-size:10px;color:var(--muted)}
.rb-t{background:#eef2f6;border-radius:99px;height:10px;overflow:hidden;position:relative}
.rb-f{display:block;height:100%;border-radius:99px;background:var(--amber)}
.rb-t.tick100:after{content:"";position:absolute;left:80%;top:-3px;bottom:-3px;width:1.5px;background:var(--mid);opacity:.55;border-radius:2px}
.rb-v{text-align:right;font-weight:700}.rb-v small{display:block;font-weight:600;font-size:10px}
.over{color:var(--red)}.under{color:var(--muted)}
.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;min-width:440px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
td.muted{color:var(--faint)}
tbody tr:last-child td{border-bottom:none}tbody tr:hover{background:var(--soft)}
tr.urgent td{background:var(--red-tint)}
.act{color:var(--muted);font-size:11px}
svg{display:block;width:100%;height:auto;overflow:visible}
.dz{fill:var(--faint);font-size:9px}.dzv{fill:var(--ink);font-size:10px;font-weight:700}
.dza{fill:var(--muted);font-size:9.5px;font-weight:650}
.dzday{fill:var(--faint);font-size:10.5px}.dzpc{font-size:11px;font-weight:750}
.dzann{font-size:11px;font-weight:700}
.mini-head{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:750;margin-bottom:8px}
.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
 border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);display:flex;
 justify-content:space-between;gap:14px;flex-wrap:wrap;font-size:10.5px;color:var(--faint)}
.scoped{background:var(--amber-tint);border:1px solid #e8d3a8;border-radius:var(--r);
 padding:11px 15px;font-size:11.5px;color:var(--amber-dk);margin-bottom:14px}
.layer[hidden],.view[hidden]{display:none}
@media (max-width:1080px){.kpis,.kpis.k4{grid-template-columns:repeat(2,minmax(0,1fr))}
 .g-2,.g-2e{grid-template-columns:minmax(0,1fr)}.hero{grid-template-columns:minmax(0,1fr)}
 .scorecard{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:720px){.rail{display:none}.rb{grid-template-columns:104px minmax(0,1fr) 88px}
 .scorecard{grid-template-columns:1fr}}
@media print{.rail,.seg{display:none}.app{display:block}
 .card,.kpi,.hero,.callout{break-inside:avoid;box-shadow:none}body{background:#fff}
 .layer[hidden],.view[hidden]{display:block}}
"""

SCRIPT = """<script>
(function(){
  var LAYERS = ['performance','branches','departments','detail'];
  function setLayer(name){
    document.querySelectorAll('.layer').forEach(function(el){
      el.hidden = el.getAttribute('data-layer') !== name;
    });
    document.querySelectorAll('[data-nav]').forEach(function(btn){
      btn.setAttribute('aria-current', btn.getAttribute('data-nav') === name ? 'true' : 'false');
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
  var current = {view:'all', layer:'performance'};
  function apply(){
    setView(current.view); setLayer(current.layer);
    var hash = '#' + current.view + '/' + current.layer;
    if (location.hash !== hash){ history.replaceState(null, '', hash); }
  }
  function fromHash(){
    var parts = (location.hash || '').replace('#','').split('/');
    if (parts[0] && document.querySelector('.view[data-view="' + parts[0] + '"]')){ current.view = parts[0]; }
    if (parts[1] && LAYERS.indexOf(parts[1]) !== -1){ current.layer = parts[1]; }
  }
  document.addEventListener('click', function(ev){
    var nav = ev.target.closest('[data-nav]');
    if (nav){ current.layer = nav.getAttribute('data-nav'); apply(); return; }
    var view = ev.target.closest('[data-viewbtn]');
    if (view){ current.view = view.getAttribute('data-viewbtn'); apply(); }
  });
  window.addEventListener('hashchange', function(){ fromHash(); apply(); });
  fromHash(); apply();
})();
</script>"""


def _currency_label(currency: str) -> str:
    code = str(currency or "").strip().upper()
    names = {
        "SAR": "Saudi riyals",
        "QAR": "Qatari riyals",
        "INR": "Indian rupees",
        "AED": "UAE dirhams",
        "USD": "US dollars",
    }
    return f"{names.get(code, 'currency')} ({code})" if code else "the configured currency"


def render(model: dict, *, currency: str = "SAR", title: str = "Target Tracker",
           eyebrow: str = "Sales · City Flower") -> str:
    r = _R(currency)
    anchor = _dt.date.fromisoformat(model["anchor"])
    wtd, mtd = model["periods"]["wtd"], model["periods"]["mtd"]

    def build_view(name, behind):
        layers = [("performance", layer_performance(r, model, behind)),
                  ("branches", layer_branches(r, model, behind)),
                  ("departments", layer_departments(r, model, behind)),
                  ("detail", layer_detail(r, model, behind))]
        inner = "".join(
            f'<div class="layer" data-layer="{key}"{"" if i == 0 else " hidden"}>{content}'
            f'{caveats(r, model) if key == "performance" else ""}</div>'
            for i, (key, content) in enumerate(layers))
        return f'<div class="view" data-view="{name}"{"" if name == "all" else " hidden"}>{inner}</div>'

    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{STYLE}</style></head>
<body>
<div class="app">
  <nav class="rail" aria-label="Sections">
    <div class="mark">AI</div>
    <div class="grp">Report</div>
    <button data-nav="performance" aria-current="true">Performance</button>
    <button data-nav="branches">Branches</button>
    <button data-nav="departments">Departments</button>
    <button data-nav="detail">Detail</button>
    <div class="grp">View</div>
    <button data-viewbtn="all" aria-current="true">All areas</button>
    <button data-viewbtn="behind">Below target only</button>
    <p class="foot">Figures as at<br>{e(fmt_date(anchor, 'daymon'))}&nbsp;{anchor.year}.</p>
  </nav>
<main><div class="page">
    <div class="masthead">
      <div>
        <p class="eyebrow">{e(eyebrow)}</p>
        <h1>{e(title)}</h1>
        <p class="asat">Performance against target up to {e(fmt_date(anchor, 'medium'))} {anchor.year}
          &middot; {e(mtd['elapsed'])} &middot; {e(wtd['elapsed'])} of the week
          &middot; {len(model['population'])} branches
          &middot; all figures in {e(_currency_label(currency))}</p>
      </div>
      <div class="seg" role="group" aria-label="View">
        <button data-viewbtn="all" aria-pressed="true">All areas</button>
        <button data-viewbtn="behind" aria-pressed="false">Below target only</button>
      </div>
    </div>
{build_view("all", False)}
{build_view("behind", True)}
    <p class="foot"><span>Every figure comes from the Target Tracker report and has been checked
      against its own totals. Nothing is estimated, and no cause is inferred.</span>
      <span>AI-assisted analysis</span></p>
  </div></main>
</div>
{SCRIPT}
</body></html>"""
