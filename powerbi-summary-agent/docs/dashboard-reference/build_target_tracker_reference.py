"""Generate the Target Tracker reference dashboard.

Same shell as `reference_inventory_management.html` and `reference_stock_age_analysis.html`:
rail + main, four layers, two views, `#<view>/<layer>` in the URL. What differs is that the
drill axis here is **time**, because the report's priority order is Daily -> WTD -> MTD -> YTD.

Hand-authoring SVG geometry is where reference pages go wrong, so the page is emitted from
the figures the live probe returned on 2026-08-18. The cushion reconciliation is asserted, so
a wrong number fails the build rather than shipping.

    python docs/dashboard-reference/build_target_tracker_reference.py
"""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().with_name("reference_target_tracker.html")

CUR = "SAR"          # Saudi Riyals. The model's own "Metrics description"
                     # table says QAR on four rows; it is stale. The group is
                     # Saudi-based and every other City Flower dashboard uses SAR.
TEAL, TEAL_DK = "#0f9f95", "#087f79"
AMBER, AMBER_DK = "#c08429", "#8a5f10"
RED, GREEN, FAINT = "#cf4636", "#2f8f4e", "#8fa1a9"


def e(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def money(v) -> str:
    v = float(v)
    a = abs(v)
    if a >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if a >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def sar(v) -> str:
    return f"{CUR}&nbsp;{money(v)}"


def signed(v) -> str:
    return ("+" if float(v) >= 0 else "&minus;") + money(abs(float(v)))


def pc(v, dp=1) -> str:
    return f"{float(v):.{dp}f}%"


def attain(a, t) -> float:
    return a / t * 100.0


def at(p) -> float:
    """Attainment of a period dict."""
    return attain(p["actual"], p["target"])


def band(a, t) -> str:
    r = attain(a, t)
    return "good" if r >= 100 else ("warn" if r >= 95 else "crit")


BAND_WORD = {"good": "On target", "warn": "Watch", "crit": "Below target"}
BAND_COL = {"good": GREEN, "warn": AMBER, "crit": RED}

# =========================================================================
# Verified figures. Anchor: Thursday 16 July 2026. Four trading branches.
# =========================================================================
DAY = dict(actual=526059.95, target=553337.00)
WTD = dict(actual=1625946.18, target=1823412.00)
MTD = dict(actual=9456777.96, target=8877883.54)
YTD = dict(actual=120172004.68, target=116862300.84)
PREV_WEEK = dict(actual=3956004.14, target=3835766.74)
WEEK_FULL_TARGET = 3598827.00
MONTH_FULL_TARGET = 16805350.49
DAY_BILLS, MTD_BILLS = 26978, 449933

JULY = [
    ("Wed", 1, 548927.32, 454348.00), ("Thu", 2, 874022.60, 648475.00),
    ("Fri", 3, 1423202.85, 1163832.00), ("Sat", 4, 532904.31, 513025.00),
    ("Sun", 5, 495771.75, 439025.00), ("Mon", 6, 455209.42, 441025.00),
    ("Tue", 7, 431450.78, 441025.00), ("Wed", 8, 439371.95, 441025.00),
    ("Thu", 9, 609818.11, 580337.00), ("Fri", 10, 1192610.76, 1023762.00),
    ("Sat", 11, 426132.14, 485567.74), ("Sun", 12, 401410.98, 423025.00),
    ("Mon", 13, 375439.25, 426025.00), ("Tue", 14, 365292.95, 421025.00),
    ("Wed", 15, 359154.03, 423025.00), ("Thu", 16, 526059.95, 553337.00),
]
REMAINING_WEEK = [("Fri 17", 959365.00), ("Sat 18", 443025.00), ("Sun 19", 373025.00)]

WEEKS = [(22, "25–31 May", 4867610.90, 4079751.90, 7), (23, "1–7 Jun", 3905807.28, 4303855.68, 7),
         (24, "8–14 Jun", 3597990.00, 4033227.00, 7), (25, "15–21 Jun", 3806551.00, 3823033.00, 7),
         (26, "22–28 Jun", 3331369.00, 3695220.00, 7), (27, "29 Jun–5 Jul", 4783508.53, 4133279.37, 7),
         (28, "6–12 Jul", 3956004.14, 3835766.74, 7), (29, "13–16 Jul", 1625946.18, 1823412.00, 4)]

MONTHS = [("Jan", 20454233.35, 19138881.21, True), ("Feb", 18942694.14, 17769310.70, True),
          ("Mar", 18618361.02, 19393702.33, True), ("Apr", 17197835.64, 15691369.65, True),
          ("May", 19951704.42, 19221243.16, True), ("Jun", 15550398.15, 16769910.24, True),
          ("Jul", 9456777.96, 8877883.54, False)]

BRANCHES = [
    dict(code="CFH017", day=(85908.30, 125000.00), wtd=(281760.26, 370000.00),
         mtd=(1462715.64, 1590000.00), ytd=(21247266.56, 22895758.64), month_target=3008405.13),
    dict(code="CFH014", day=(177896.69, 173337.00), wtd=(555810.56, 623412.00),
         mtd=(2982588.04, 2803717.00), ytd=(39799372.36, 39128478.89), month_target=5363778.82),
    dict(code="CFH021", day=(170168.18, 155000.00), wtd=(516883.07, 550000.00),
         mtd=(3098149.48, 2898623.81), ytd=(41808278.93, 38590044.50), month_target=5252623.81),
    dict(code="CFH018", day=(92086.78, 100000.00), wtd=(271492.29, 280000.00),
         mtd=(1913324.80, 1585542.74), ytd=(25523889.60, 24175485.74), month_target=3180542.74),
]

DEPTS = [
    dict(name="FMCG FOOD", day=(192488.70, 212261.43), wtd=(593716.03, 693874.80), mtd=(3575212.27, 3357933.41)),
    dict(name="FARM FRESH", day=(120155.96, 99742.56), wtd=(329403.43, 327710.59), mtd=(1778576.74, 1581740.89)),
    dict(name="FMCG NON-FOOD", day=(75982.43, 83985.07), wtd=(237734.48, 277491.50), mtd=(1489894.66, 1370118.17)),
    dict(name="GM FASHION", day=(42066.68, 48461.58), wtd=(142138.26, 161744.41), mtd=(797964.56, 795179.91)),
    dict(name="FASHION", day=(31678.39, 34927.87), wtd=(94781.90, 116828.09), mtd=(554513.34, 564813.37)),
    dict(name="ELECTRONICS", day=(22156.56, 28143.62), wtd=(83830.07, 94147.99), mtd=(474214.84, 462012.45)),
    dict(name="GM HOME WARE", day=(15897.41, 18755.40), wtd=(54632.82, 62203.92), mtd=(300572.08, 303890.47)),
    dict(name="GM OTHERS", day=(9470.22, 10207.29), wtd=(33514.65, 33807.01), mtd=(178244.77, 168130.68)),
    dict(name="FOOTWEAR", day=(7017.66, 8247.01), wtd=(24763.18, 26805.66), mtd=(142666.37, 130300.75)),
    dict(name="HOME FASHION", day=(6392.81, 6998.76), wtd=(22624.53, 23097.88), mtd=(125196.73, 113722.45)),
    dict(name="LIVE KITCHEN", day=(2218.22, 1606.40), wtd=(6719.34, 5700.14), mtd=(33194.54, 30041.02)),
]

SECTIONS = [
    ("CF-CHILLED & DAIRY", "FMCG FOOD", 376365.50, 400294.48),
    ("CF-CONFECTIONERY", "FMCG FOOD", 297478.64, 313074.21),
    ("CF-MENS FASHION", "FASHION", 430832.45, 442936.57),
    ("CF-PLASTICS", "GM HOME WARE", 108787.51, 120495.49),
    ("CF-SMART WATCHES", "GM FASHION", 62764.54, 73434.47),
    ("CF-LUGGAGE", "GM FASHION", 150903.68, 155268.56),
    ("CF-STAPLES", "FMCG FOOD", 902183.81, 729623.78),
    ("CF-FRUIT & VEGETABLES", "FARM FRESH", 992317.81, 882974.56),
    ("CF-PERSONAL CARE", "FMCG NON-FOOD", 1161690.42, 1080601.55),
    ("CF-MEAT", "FARM FRESH", 634908.53, 571857.03),
]

# ---- derived -------------------------------------------------------------
FIRST10 = [d for d in JULY if d[1] <= 10]
LAST6 = [d for d in JULY if d[1] >= 11]
BUILT = sum(d[2] for d in FIRST10) - sum(d[3] for d in FIRST10)
GAVE_BACK = sum(d[3] for d in LAST6) - sum(d[2] for d in LAST6)
CUSHION = MTD["actual"] - MTD["target"]
assert abs((BUILT - GAVE_BACK) - CUSHION) < 1.0, "the two halves of July must reconcile to the MTD gap"
BURN = GAVE_BACK / len(LAST6)
CUSHION_DAYS = CUSHION / BURN
WEEK_NEEDED = WEEK_FULL_TARGET - WTD["actual"]
WEEK_REM_TARGET = sum(t for _, t in REMAINING_WEEK)
MONTH_NEEDED = MONTH_FULL_TARGET - MTD["actual"]
MONTH_REM_TARGET = MONTH_FULL_TARGET - MTD["target"]
PROJ_AT_MTD = MTD["actual"] + MONTH_REM_TARGET * at(MTD) / 100.0
PROJ_AT_RUN = MTD["actual"] + MONTH_REM_TARGET * (sum(d[2] for d in LAST6) / sum(d[3] for d in LAST6))
HIT_DAYS = sum(1 for d in JULY if d[2] >= d[3])
RUN_LEN = 0
for d in reversed(JULY):
    if d[2] < d[3]:
        RUN_LEN += 1
    else:
        break

PERIODS = [
    ("Today", "Thursday 16 July", DAY, "6th day below target in a row"),
    ("This week so far", "Mon 13 – Thu 16 · 4 days of 7", WTD, "all four branches below target"),
    ("This month so far", "1 – 16 July · 16 days of 31", MTD, "the surplus that is left"),
    ("This year so far", "1 January – 16 July", YTD, "no risk to the year"),
]

# =========================================================================
# Components
# =========================================================================
def kpi(label, value, sub, cls="", pill=None):
    p = f'<span class="pill pill-{pill[0]}">{e(pill[1])}</span>' if pill else ""
    return (f'<div class="kpi {cls}"><p class="lab">{label}</p><p class="val">{value}</p>'
            f'<p class="sub">{sub}</p>{p}</div>')


def period_kpis(items):
    out = []
    for title, when, p, tag in items:
        b = band(p["actual"], p["target"])
        gap = p["actual"] - p["target"]
        out.append(kpi(
            f'{e(title)}<br><span style="text-transform:none;letter-spacing:0;font-weight:500;color:#8fa1a9">{e(when)}</span>',
            pc(attain(p["actual"], p["target"])),
            f'{sar(p["actual"])} sold against a target of {sar(p["target"])}<br>{sar(abs(gap))} '
            f'{"above" if gap >= 0 else "below"} target &middot; {e(tag)}',
            cls=b, pill=(("ok" if b == "good" else b), BAND_WORD[b])))
    return f'<div class="kpis k4">{"".join(out)}</div>'


def rbar(label, small, fill_pct, value, rate, rate_cls, color):
    return (f'<div class="rb"><div class="rb-l">{e(label)}<small>{small}</small></div>'
            f'<div class="rb-t"><span class="rb-f" style="width:{fill_pct:.1f}%;background:{color}"></span></div>'
            f'<div class="rb-v">{value}<small class="{rate_cls}">{rate}</small></div></div>')


def attainment_bars(rows, scope, sub_fmt):
    """One bar per member, length = attainment capped at 125%, tick at 100%."""
    out = []
    for r in rows:
        a, t = r[scope]
        ratio = attain(a, t)
        b = band(a, t)
        out.append(
            f'<div class="rb"><div class="rb-l">{e(r["code"] if "code" in r else r["name"])}'
            f'<small>{sub_fmt(r, scope)}</small></div>'
            f'<div class="rb-t tick100"><span class="rb-f" style="width:{min(ratio,125)/125*100:.1f}%;'
            f'background:{BAND_COL[b]}"></span></div>'
            f'<div class="rb-v" style="color:{BAND_COL[b]}">{pc(ratio)}'
            f'<small class="{"under" if a>=t else "over"}">{CUR} {signed(a-t)}</small></div></div>')
    return f'<div class="rbars">{"".join(out)}</div>'


# ---- charts --------------------------------------------------------------
def chart_days():
    """Sixteen days, actual column against its own daily target. The pattern is the point."""
    w, h = 1240, 330
    l, r, t, b = 60, 18, 34, 60
    pw, ph = w - l - r, h - t - b
    step = pw / len(JULY)
    bw = step * 0.58
    mx = max(max(d[2], d[3]) for d in JULY)
    p = []
    for g in range(1, 4):
        y = t + ph - ph * g / 3
        p.append(f'<line x1="{l}" y1="{y:.1f}" x2="{w-r}" y2="{y:.1f}" stroke="#eef2f6"/>')
        p.append(f'<text x="{l-8}" y="{y+3.5:.1f}" text-anchor="end" class="dz">{money(mx*g/3)}</text>')
    p.append(f'<line x1="{l}" y1="{t+ph}" x2="{w-r}" y2="{t+ph}" stroke="#dfe7ec"/>')
    for i, (dow, dn, act, tgt) in enumerate(JULY):
        x = l + i * step + (step - bw) / 2
        bh = act / mx * ph
        col = BAND_COL[band(act, tgt)]
        p.append(f'<rect x="{x:.1f}" y="{t+ph-bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2.5" '
                 f'fill="{col}" opacity="{1 if dn >= 11 else 0.72}"><title>{dow} {dn} July — actual '
                 f'{CUR} {money(act)}, target {CUR} {money(tgt)}, {pc(attain(act,tgt))}</title></rect>')
        ty = t + ph - tgt / mx * ph
        p.append(f'<line x1="{x-2.5:.1f}" y1="{ty:.1f}" x2="{x+bw+2.5:.1f}" y2="{ty:.1f}" '
                 f'stroke="#41545a" stroke-width="1.8" stroke-linecap="round"/>')
        p.append(f'<text x="{l+(i+.5)*step:.1f}" y="{h-34}" text-anchor="middle" class="dzday">{dow} {dn}</text>')
        p.append(f'<text x="{l+(i+.5)*step:.1f}" y="{h-17}" text-anchor="middle" class="dzpc" '
                 f'fill="{col}">{attain(act,tgt):.0f}%</text>')
    split = l + 10 * step
    p.append(f'<line x1="{split:.1f}" y1="{t-6}" x2="{split:.1f}" y2="{t+ph}" stroke="#cf4636" '
             f'stroke-width="1.2" stroke-dasharray="3 3"/>')
    p.append(f'<text x="{split-8:.1f}" y="{t-14}" text-anchor="end" class="dzann" fill="#5b7182">'
             f'1–10 July · built up {CUR} {money(BUILT)}</text>')
    p.append(f'<text x="{split+8:.1f}" y="{t-14}" class="dzann" fill="#cf4636">'
             f'11–16 July · {len(LAST6)} days below target in a row, {CUR} {money(GAVE_BACK)} used up</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Sales each day against its own target, 1 to 16 July">{"".join(p)}</svg>'


def chart_cushion():
    """Waterfall: what the month banked, what it has handed back, what is left."""
    steps = [("Built up 1–10 Jul", BUILT, TEAL), ("Used up 11–16 Jul", -GAVE_BACK, RED),
             ("Surplus left now", CUSHION, TEAL_DK)]
    w, h = 560, 250
    l, r, t, b = 20, 20, 32, 52
    pw, ph = w - l - r, h - t - b
    step = pw / 3
    bw = step * 0.5
    mx = BUILT * 1.12
    p = [f'<line x1="{l}" y1="{t+ph}" x2="{w-r}" y2="{t+ph}" stroke="#dfe7ec"/>']
    running = 0.0
    for i, (name, val, col) in enumerate(steps):
        x = l + i * step + (step - bw) / 2
        if i == 2:
            y0, y1 = 0.0, CUSHION
        else:
            y0, y1 = running, running + val
            running = y1
        top = max(y0, y1) / mx * ph
        bot = min(y0, y1) / mx * ph
        p.append(f'<rect x="{x:.1f}" y="{t+ph-top:.1f}" width="{bw:.1f}" height="{max(top-bot,3):.1f}" '
                 f'rx="2.5" fill="{col}"><title>{name}: {CUR} {money(val)}</title></rect>')
        p.append(f'<text x="{x+bw/2:.1f}" y="{t+ph-top-8:.1f}" text-anchor="middle" class="dzv" '
                 f'fill="{col}">{signed(val) if i < 2 else money(val)}</text>')
        p.append(f'<text x="{x+bw/2:.1f}" y="{h-30}" text-anchor="middle" class="dz">{e(name)}</text>')
    p.append(f'<text x="{w/2:.1f}" y="{h-10}" text-anchor="middle" class="dza">'
             f'about one-third ({GAVE_BACK/BUILT*100:.0f}%) of the surplus has already gone</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="How the surplus this month has moved">{"".join(p)}</svg>'


def chart_weeks():
    w, h = 500, 230
    l, r, t, b = 40, 14, 20, 46
    pw, ph = w - l - r, h - t - b
    vals = [attain(a, tg) for _, _, a, tg, _ in WEEKS]
    lo, hi = 84.0, 122.0
    yy = lambda v: t + ph - (v - lo) / (hi - lo) * ph
    xx = lambda i: l + (i + .5) * (pw / len(WEEKS))
    p = []
    for g in (90, 100, 110, 120):
        y = yy(g)
        solid = g == 100
        p.append(f'<line x1="{l}" y1="{y:.1f}" x2="{w-r}" y2="{y:.1f}" stroke="{"#8fa1a9" if solid else "#eef2f6"}"'
                 f'{" stroke-dasharray=\'4 3\'" if solid else ""}/>')
        p.append(f'<text x="{l-7}" y="{y+3.5:.1f}" text-anchor="end" class="dz">{g}</text>')
    p.append(f'<polyline points="{" ".join(f"{xx(i):.1f},{yy(v):.1f}" for i, v in enumerate(vals))}" '
             f'fill="none" stroke="{TEAL_DK}" stroke-width="2.2" stroke-linejoin="round"/>')
    for i, (num, lab, a, tg, dc) in enumerate(WEEKS):
        col = BAND_COL[band(a, tg)]
        part = dc < 7
        p.append(f'<circle cx="{xx(i):.1f}" cy="{yy(vals[i]):.1f}" r="{5.5 if part else 4.5}" '
                 f'fill="{"#fff" if part else col}" stroke="{col}" stroke-width="2.4">'
                 f'<title>Week {num} ({lab}) — {pc(vals[i])}{" · 4 of 7 days" if part else ""}</title></circle>')
        p.append(f'<text x="{xx(i):.1f}" y="{h-28}" text-anchor="middle" class="dz">wk{num}</text>')
    p.append(f'<text x="{xx(len(WEEKS)-1):.1f}" y="{h-12}" text-anchor="end" class="dza" fill="{RED}">'
             f'this week, only 4 days in</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="How much of target was reached each week, over the last eight weeks">{"".join(p)}</svg>'


def chart_months():
    w, h = 500, 230
    l, r, t, b = 40, 14, 20, 46
    pw, ph = w - l - r, h - t - b
    vals = [attain(a, tg) for _, a, tg, _ in MONTHS]
    lo, hi = 88.0, 114.0
    yy = lambda v: t + ph - (v - lo) / (hi - lo) * ph
    step = pw / len(MONTHS)
    bw = step * 0.5
    p = [f'<line x1="{l}" y1="{yy(100):.1f}" x2="{w-r}" y2="{yy(100):.1f}" stroke="#8fa1a9" stroke-dasharray="4 3"/>']
    for g in (90, 110):
        p.append(f'<text x="{l-7}" y="{yy(g)+3.5:.1f}" text-anchor="end" class="dz">{g}</text>')
    p.append(f'<text x="{l-7}" y="{yy(100)+3.5:.1f}" text-anchor="end" class="dz">100</text>')
    for i, (name, a, tg, complete) in enumerate(MONTHS):
        v = vals[i]
        col = BAND_COL[band(a, tg)]
        x = l + i * step + (step - bw) / 2
        y0, y1 = yy(100), yy(v)
        p.append(f'<rect x="{x:.1f}" y="{min(y0,y1):.1f}" width="{bw:.1f}" height="{max(abs(y1-y0),2):.1f}" '
                 f'rx="2" fill="{col}" opacity="{0.55 if complete else 1}">'
                 f'<title>{name} — {pc(v)}{"" if complete else " (to the 16th)"}</title></rect>')
        p.append(f'<text x="{x+bw/2:.1f}" y="{(y1-6) if v>=100 else (y1+13):.1f}" text-anchor="middle" '
                 f'class="dza" fill="{col}">{v:.0f}</text>')
        p.append(f'<text x="{l+(i+.5)*step:.1f}" y="{h-28}" text-anchor="middle" class="dz">{name}</text>')
    p.append(f'<text x="{w-r}" y="{h-12}" text-anchor="end" class="dza">'
             f'July is shown up to the 16th &middot; how far above or below target</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="How much of target was reached each month in 2026">{"".join(p)}</svg>'


# ---- tables --------------------------------------------------------------
def branch_table(rows):
    body = ""
    for br in rows:
        need = br["month_target"] - br["mtd"][0]
        rem = br["month_target"] - br["mtd"][1]
        req = need / rem * 100
        cells = ""
        for scope in ("day", "wtd", "mtd", "ytd"):
            a, t = br[scope]
            cells += f'<td class="n" style="color:{BAND_COL[band(a,t)]};font-weight:700">{pc(attain(a,t))}</td>'
        body += (f'<tr{" class=\"urgent\"" if band(*br["mtd"]) == "crit" else ""}>'
                 f'<td><b>{e(br["code"])}</b></td>{cells}'
                 f'<td class="n">{CUR} {signed(br["mtd"][0]-br["mtd"][1])}</td>'
                 f'<td class="n">{sar(need)}</td>'
                 f'<td class="n" style="font-weight:700;color:{RED if req>100 else "#41545a"}">{pc(req)}</td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Branch</th><th class="n">Today</th>'
            f'<th class="n">This week</th><th class="n">This month</th><th class="n">This year</th>'
            f'<th class="n">Above/below target</th><th class="n">Still needed</th>'
            f'<th class="n">Needed vs target</th></tr></thead><tbody>{body}</tbody></table></div>')


def dept_table(rows):
    body = ""
    for d in rows:
        wa, wt = d["wtd"]
        ma, mt = d["mtd"]
        da, dt = d["day"]
        body += (f'<tr{" class=\"urgent\"" if band(ma, mt) == "crit" else ""}><td><b>{e(d["name"])}</b></td>'
                 f'<td class="n" style="color:{BAND_COL[band(da,dt)]};font-weight:700">{pc(attain(da,dt))}</td>'
                 f'<td class="n" style="color:{BAND_COL[band(wa,wt)]};font-weight:700">{pc(attain(wa,wt))}</td>'
                 f'<td class="n">{CUR} {signed(wa-wt)}</td>'
                 f'<td class="n" style="color:{BAND_COL[band(ma,mt)]};font-weight:700">{pc(attain(ma,mt))}</td>'
                 f'<td class="n">{CUR} {signed(ma-mt)}</td>'
                 f'<td class="n act">{sar(ma)}</td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Department</th><th class="n">Today</th>'
            f'<th class="n">This week</th><th class="n">Above/below</th><th class="n">This month</th>'
            f'<th class="n">Above/below</th><th class="n">Sold this month</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def section_table(rows):
    body = ""
    for name, dep, a, t in rows:
        b = band(a, t)
        body += (f'<tr{" class=\"urgent\"" if b == "crit" else ""}><td><b>{e(name)}</b>'
                 f'<br><span class="act">{e(dep)}</span></td>'
                 f'<td class="n">{sar(a)}</td><td class="n">{sar(t)}</td>'
                 f'<td class="n" style="color:{BAND_COL[b]};font-weight:700">{pc(attain(a,t))}</td>'
                 f'<td class="n">{CUR} {signed(a-t)}</td>'
                 f'<td><span class="pill pill-{"ok" if b=="good" else b}">{BAND_WORD[b]}</span></td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Section</th><th class="n">Sold this month</th>'
            f'<th class="n">Target</th><th class="n">% of target</th><th class="n">Above/below</th>'
            f'<th>Status</th></tr></thead><tbody>{body}</tbody></table></div>')


def sect(title, sub):
    return f'<div class="sect"><h2>{e(title)}</h2><span>{e(sub)}</span></div>'


def card(title, sub, body, note=""):
    n = f'<p class="note">{note}</p>' if note else ""
    return (f'<section class="card"><h3>{e(title)}</h3><p class="sub">{e(sub)}</p>{body}{n}</section>')


# =========================================================================
# Layers
# =========================================================================
BEHIND_BRANCHES_MTD = [b for b in BRANCHES if b["mtd"][0] < b["mtd"][1]]
BEHIND_DEPTS_WTD = [d for d in DEPTS if d["wtd"][0] < d["wtd"][1]]
BEHIND_DEPTS_MTD = [d for d in DEPTS if d["mtd"][0] < d["mtd"][1]]
BEHIND_SECTIONS = [s for s in SECTIONS if s[2] < s[3]]

BRANCH_SUB = lambda r, s: f'{sar(r[s][0])} of {sar(r[s][1])}'
DEPT_SUB = lambda r, s: f'{sar(r[s][0])} of {sar(r[s][1])}'


def layer_performance(behind=False):
    hero = f"""<section class="hero">
      <div>
        <span class="hero-tag">Sales are slipping against target</span>
        <h2>{"Every branch is below target this week, and one is below target for the month."
             if behind else
             "Six days below target have used up one-third of July&rsquo;s surplus."}</h2>
        <p>{"CFH017 is the only branch below target for the month, and the only one that needs to sell more "
            "than planned to catch up. The other three are behind for this week, but each built up enough of "
            "a surplus earlier in the month to cover it."
            if behind else
            f"July is still performing above target at {pc(at(MTD))}, with a surplus of {sar(CUSHION)}. "
            f"However, most of that surplus was built during the first 10 days of the month, and the last "
            f"six days of below-target sales have used up about one-third of it. If sales continue at the "
            f"current rate, the remaining surplus could be fully used up by around 28 July &mdash; just "
            f"three days before the month ends."}</p>
      </div>
      <div class="hero-stats">
        <div class="hs crit"><b>{pc(at(DAY))}</b><span>of target today &middot; {RUN_LEN}th day below target in a row</span></div>
        <div class="hs crit"><b>{pc(at(WTD))}</b><span>of target this week &middot; {sar(abs(WTD['actual']-WTD['target']))} below target</span></div>
        <div class="hs"><b>{pc(at(MTD))}</b><span>of target this month &middot; {sar(CUSHION)} surplus</span></div>
      </div>
    </section>"""

    scoped = ('<div class="scoped">Showing only the branches, departments and sections that are '
              '<b>below target</b>. The totals still cover the whole business.</div>'
              if behind else "")

    story = f"""{sect("What has happened", "how today affected the week, and the week affected the month")}
    <div style="margin-bottom:14px">
      {card("Sales each day this month, against that day's target",
            "Each column is one day's sales. The dark line across it is the target for that day. The percentage below shows how much of that target was reached.",
            chart_days(),
            note=f"The first 10 days of July sold {pc(attain(sum(d[2] for d in FIRST10), sum(d[3] for d in FIRST10)))} "
                 f"of their target and built up a surplus of {sar(BUILT)}. The last six days have sold only "
                 f"{pc(attain(sum(d[2] for d in LAST6), sum(d[3] for d in LAST6)))} of their target and used up {sar(GAVE_BACK)} of it. "
                 f"<b>{HIT_DAYS} of the 16 days so far met their target, and all eight days that missed are in the second half of the month.</b>")}
    </div>
    <div class="grid g-2e">
      {card("How much of the surplus is left",
            "The surplus so far this month, split into what was built up and what has been used.",
            chart_cushion(),
            note=f"Over the last six days, sales fell short of target by an average of {sar(BURN)} a day. At that rate the {sar(CUSHION)} still left "
                 f"would run out in about <b>{CUSHION_DAYS:.1f} days</b> &mdash; around <b>28 July</b>.")}
      {card("Which branches missed target today",
            ("Branches that did not reach their target on Thursday 16 July."
             if behind else
             "How much of its target each branch reached on Thursday 16 July. The bar shows the percentage reached; the line marks 100%."),
            attainment_bars(sorted([b for b in BRANCHES if not behind or band(*b["day"]) != "good"],
                                   key=lambda b: attain(*b["day"])), "day", BRANCH_SUB),
            note=f"CFH017 alone fell {sar(39091.70)} short. That is more than the whole company's shortfall of "
                 f"{sar(abs(DAY['actual']-DAY['target']))} &mdash; so if CFH017 had reached its target, the business as a whole would have finished the day above target. "
                 f"CFH021 and CFH014 both beat theirs.")}
    </div>"""

    ladder = f"""{sect("How we are doing right now", "all four time periods, most important first")}
    {period_kpis(PERIODS)}
    <p class="note" style="margin-top:10px">Each period is compared with the target for the days that
    have already passed, not with the target for the whole period. That is what makes the four
    percentages comparable with each other.
    This week covers 4 days out of 7, and this month covers 16 days out of 31.</p>"""

    close = f"""{sect("What is needed to catch up", "the maths, for this week and this month")}
    <div class="grid g-2e">
      {card("This week (week 29)",
            f"Three days are left. Together they are targeted to sell {CUR} {money(WEEK_REM_TARGET)}.",
            f'<div class="closeout">'
            f'<div><b>{sar(WEEK_NEEDED)}</b><span>must be sold on Friday, Saturday and Sunday to reach the week&rsquo;s target</span></div>'
            f'<div><b style="color:{RED}">{pc(WEEK_NEEDED/WEEK_REM_TARGET*100)}</b>'
            f'<span>of what those three days are targeted to sell, so they must beat target</span></div></div>'
            + ''.join(f'<div class="rb rb-short"><div class="rb-l">{lab}</div>'
                      f'<div class="rb-t"><span class="rb-f" style="width:{t/WEEK_REM_TARGET*100:.1f}%;'
                      f'background:{FAINT}"></span></div><div class="rb-v">{sar(t)}</div></div>'
                      for lab, t in REMAINING_WEEK),
            note=f"Friday alone is targeted at {sar(959365.00)}, more than half of what is left. The last two Fridays reached 116.5% and "
                 f"99.0% of their targets, so the week can still be saved &mdash; but only with a strong weekend.")}
      {card("This month (July)",
            f"Fifteen days are left. Together they are targeted to sell {CUR} {money(MONTH_REM_TARGET)}.",
            f'<div class="closeout">'
            f'<div><b>{sar(MONTH_NEEDED)}</b><span>must be sold between 17 and 31 July to reach the monthly target</span></div>'
            f'<div><b style="color:{GREEN}">{pc(MONTH_NEEDED/MONTH_REM_TARGET*100)}</b>'
            f'<span>of what those days are targeted to sell, so they can sell slightly under target and still get there</span></div></div>'
            f'<p class="note" style="margin-top:12px">If the rest of the month sells at the same rate as the month so far ({pc(at(MTD))} of target), '
            f'July would finish at about <b>{sar(PROJ_AT_MTD)}</b> &mdash; {pc(PROJ_AT_MTD/MONTH_FULL_TARGET*100)} of the monthly target. '
            f'If it sells at the rate of the <em>last six days</em> rate instead, July would finish at about <b>{sar(PROJ_AT_RUN)}</b>, '
            f'which is below target.</p>',
            note="The difference between those two outcomes is what the next week decides. The month can still "
                 "afford to sell slightly below target and still reach its goal &mdash; that is what the "
                 "surplus buys. It is also why this is worth acting on now, rather than at the end of the month.")}
    </div>"""

    return hero + scoped + ladder + story + close


def layer_branches(behind=False):
    rows = BEHIND_BRANCHES_MTD if behind else BRANCHES
    rows = sorted(rows, key=lambda b: attain(*b["mtd"]))
    return f"""{sect("Branch performance", "branches below target for the month" if behind else "how each of the four branches is doing")}
    <div class="grid g-2">
      {card("How each branch is doing this month",
            "The bar shows how much of its target each branch has reached so far. The line marks 100%.",
            attainment_bars(rows, "mtd", BRANCH_SUB),
            note="CFH017 is the only branch below target for July, and it is below target over every time period &mdash; "
                 "68.7% today, 76.2% this week and 92.0% this month. It is the one thing on this page that "
                 "needs a decision.")}
      {card("How each branch is doing this week",
            "All four branches are below target this week.",
            attainment_bars(sorted(BRANCHES, key=lambda b: attain(*b["wtd"])), "wtd", BRANCH_SUB),
            note="All four branches are below target this week. That is what makes this different from one bad "
                 "day at a single branch.")}
    </div>
    <div style="margin-top:14px">
      {card("Full branch figures",
            "How each branch is performing over each time period, and what it still needs to sell to reach its July target.",
            branch_table(rows),
            note=f"&ldquo;Still needed&rdquo; is the full July target minus what the branch has sold so far. "
                 f"&ldquo;Needed vs target&rdquo; shows that as a percentage of what the remaining "
                 f"15 days are already targeted to sell. Above 100% means the branch has to sell more than its plan "
                 f"to recover.")}
    </div>"""


def layer_departments(behind=False):
    wtd_rows = BEHIND_DEPTS_WTD if behind else DEPTS
    mtd_rows = BEHIND_DEPTS_MTD if behind else DEPTS
    return f"""{sect("Department performance", "departments below target" if behind else "where the week is being lost")}
    <div class="grid g-2">
      {card("This week so far",
            "Ranked from worst to best. Nine of the eleven departments are below target this week.",
            attainment_bars(sorted(wtd_rows, key=lambda d: attain(*d["wtd"])), "wtd", DEPT_SUB),
            note=f"FMCG FOOD has the biggest shortfall this week at {sar(100158.77)} below target. But it is "
                 f"still {pc(attain(*[d for d in DEPTS if d['name']=='FMCG FOOD'][0]['mtd']))} for the month as a whole, "
                 f"so this is a recent slowdown in the largest department rather than a long-running problem.")}
      {card("This month so far",
            "The same departments measured over the whole month.",
            attainment_bars(sorted(mtd_rows, key=lambda d: attain(*d["mtd"])), "mtd", DEPT_SUB),
            note="Only two departments are below target for the month, and both only slightly. The contrast "
                 "with the weekly picture is the real story: almost every department has slowed at the same time.")}
    </div>
    <div style="margin-top:14px">
      {card("Full department figures", "Every trading department, across each time period.",
            dept_table(sorted(mtd_rows, key=lambda d: attain(*d["mtd"]))))}
    </div>"""


def layer_detail(behind=False):
    rows = BEHIND_SECTIONS if behind else SECTIONS
    rows = sorted(rows, key=lambda s: attain(s[2], s[3]))
    return f"""{sect("More detail", "sections, weeks and months")}
    <div style="margin-bottom:14px">
      {card("Sections that stand out",
            "The sections furthest below their target this month, and the furthest above." if not behind else
            "Sections below their target for the month so far.",
            section_table(rows),
            note="Section targets are set for each branch and added together here. A section can be below target while its "
                 "department is above, which is why both are shown.")}
    </div>
    <div class="grid g-2e">
      {card("Week-by-week performance", "The last eight weeks. This week is only four days old.",
            chart_weeks(),
            note=f"Last week (6&ndash;12 July) finished at {pc(attain(PREV_WEEK['actual'], PREV_WEEK['target']))} of target, "
                 f"{sar(PREV_WEEK['actual']-PREV_WEEK['target'])} above it. The change happened recently "
                 f"and started on Saturday 11 July.")}
      {card("Month-by-month performance", "How far above or below target each month finished.",
            chart_months(),
            note="Four of the six completed months beat their target. The two that did not &mdash; March at 96.0% "
                 "and June at 92.7% &mdash; both followed the same pattern as the last six days: a strong "
                 "start to the month, then a run of below-target days that was not stopped. "
                 f"June finished {sar(1219512.09)} below target.")}
    </div>"""


CAVEATS = f"""<div class="caveats">
  <h3>Important things to know about these numbers</h3>
  <ul>
    <li><b>There is no comparison with last year.</b> The report only holds 2026 data, so every figure
        here is compared with target, never with last year.</li>
    <li><b>Each period is compared with the target for the days that have passed.</b> This week covers
        4 days of 7, and this month 16 days of 31. Targets for the full week and full month are used
        only in the &ldquo;what is needed to catch up&rdquo; figures, which say so.</li>
    <li><b>Branch CFH022 is not included.</b> It has had no sales since 1 August, and the Sales
        performance report leaves it out for the same reason.</li>
    <li><b>One non-trading department has sold {sar(6527.06)} this month but has no target</b>,
        so it is left out of the percentage tables. It is too small to change any figure here.</li>
    <li><b>The projections simply continue the current rate.</b> They are arithmetic, not forecasts, and
        they assume the remaining days keep the targets they already have.</li>
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
.hero p{color:#a9c2bd;font-size:12.5px;margin-top:8px;max-width:56ch}
.hero-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.hs{border-left:2px solid rgba(255,255,255,.14);padding-left:12px}
.hs b{display:block;color:#fff;font-size:19px;font-weight:700;line-height:1.15}
.hs span{display:block;color:#7f9a95;font-size:10.5px;margin-top:3px;line-height:1.35}
.hs.crit b{color:#ff8b73}

.grid{display:grid;gap:14px}
.g-2{grid-template-columns:minmax(0,1.55fr) minmax(0,1fr)}
.g-2e{grid-template-columns:repeat(2,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:16px 18px;box-shadow:var(--shadow)}
.card>h3{font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.card>.sub{font-size:11.5px;color:var(--muted);margin-top:2px;margin-bottom:12px}
.sect{margin:22px 0 10px;display:flex;align-items:baseline;gap:11px}
.sect h2{font-size:16px;font-weight:700;letter-spacing:-.015em}
.sect span{font-size:11.5px;color:var(--faint)}
.note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.5}

.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:11px}
.kpis.k4{grid-template-columns:repeat(4,minmax(0,1fr))}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:13px 14px 12px;position:relative;overflow:hidden;box-shadow:var(--shadow)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--faint)}
.kpi.crit::before{background:var(--red)} .kpi.warn::before{background:var(--amber)}
.kpi.good::before{background:var(--green)}
.kpi .lab{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  font-weight:650;min-height:24px}
.kpi .val{font-size:21px;font-weight:750;line-height:1.1;margin:5px 0 4px;letter-spacing:-.02em}
.kpi.crit .val{color:var(--red)} .kpi.warn .val{color:var(--amber-dk)}
.kpi.good .val{color:var(--green)}
.kpi .sub{font-size:10.5px;color:var(--muted);line-height:1.4}
.kpi .pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 6px;border-radius:5px;margin-top:7px}
.pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 6px;border-radius:5px}
.pill-crit{background:var(--red-tint);color:var(--red)}
.pill-warn{background:var(--amber-tint);color:var(--amber-dk)}
.pill-ok{background:var(--green-tint);color:var(--green)}

.rbars{display:flex;flex-direction:column;gap:9px}
.rb{display:grid;grid-template-columns:132px minmax(0,1fr) 104px;gap:11px;align-items:center;font-size:12px}
.rb-l{font-weight:650}
.rb-l small{display:block;font-weight:400;font-size:10px;color:var(--muted)}
.rb-t{background:#eef2f6;border-radius:99px;height:10px;overflow:hidden;position:relative}
.rb-f{display:block;height:100%;border-radius:99px;background:var(--amber)}
.rb-t.tick100:after{content:"";position:absolute;left:80%;top:-3px;bottom:-3px;width:1.5px;
  background:var(--mid);opacity:.55;border-radius:2px}
.rb-v{text-align:right;font-weight:700}
.rb-v small{display:block;font-weight:600;font-size:10px}
.rb.rb-short{grid-template-columns:64px minmax(0,1fr) 96px}
.over{color:var(--red)} .under{color:var(--muted)}

.closeout{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:12px}
.closeout b{display:block;font-size:19px;font-weight:750;line-height:1.15;letter-spacing:-.02em}
.closeout span{display:block;font-size:10.5px;color:var(--muted);margin-top:3px;line-height:1.35}

.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;min-width:440px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--soft)}
tr.urgent td{background:var(--red-tint)}
.act{color:var(--muted);font-size:11px}

.dz{fill:var(--faint);font-size:9px} .dzv{fill:var(--ink);font-size:10px;font-weight:700}
.dza{fill:var(--muted);font-size:9.5px;font-weight:650}
.dzday{fill:var(--faint);font-size:10.5px}
.dzpc{font-size:11px;font-weight:750}
.dzann{font-size:11px;font-weight:700}

.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
  font-size:10.5px;color:var(--faint)}

@media (max-width:1080px){
  .kpis,.kpis.k4{grid-template-columns:repeat(2,minmax(0,1fr))}
  .g-2,.g-2e{grid-template-columns:minmax(0,1fr)}
  .hero{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:720px){.rail{display:none}.rb{grid-template-columns:104px minmax(0,1fr) 88px}}
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
  var LAYERS = ['performance','branches','departments','detail'];

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

  var current = {view: 'all', layer: 'performance'};

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


def build_view(name, behind):
    layers = [("performance", layer_performance(behind)), ("branches", layer_branches(behind)),
              ("departments", layer_departments(behind)), ("detail", layer_detail(behind))]
    inner = "".join(
        f'<div class="layer" data-layer="{k}"{"" if i == 0 else " hidden"}>{v}{CAVEATS if k == "performance" else ""}</div>'
        for i, (k, v) in enumerate(layers))
    return f'<div class="view" data-view="{name}"{"" if name == "all" else " hidden"}>{inner}</div>'


HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Target Tracker &mdash; reference dashboard</title>
<style>{STYLE}</style>
</head>
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
    <button data-viewbtn="behind">Behind target only</button>
    <p class="foot">Reference design.<br>Figures are the live position as at 16&nbsp;Jul&nbsp;2026.</p>
  </nav>
<main><div class="page">
    <div class="masthead">
      <div>
        <p class="eyebrow">Sales &middot; City Flower</p>
        <h1>Target Tracker</h1>
        <p class="asat">Performance against target up to 16 July 2026 &middot; day 16 of 31 &middot;
          week 29, day 4 of 7 &middot; 4 branches &middot; all figures in Saudi Riyals ({CUR})</p>
      </div>
      <div class="seg" role="group" aria-label="View">
        <button data-viewbtn="all" aria-pressed="true">All areas</button>
        <button data-viewbtn="behind" aria-pressed="false">Behind target only</button>
      </div>
    </div>
{build_view("all", False)}
{build_view("behind", True)}
    <p class="foot"><span>Every figure comes from the Target Tracker report and has been checked against
      its own totals. Nothing here is estimated.</span><span>AI-assisted analysis</span></p>
  </div></main>
</div>
{SCRIPT}
</body>
</html>"""

OUT.write_text(HTML, encoding="utf-8")
print(f"wrote {OUT}  ({len(HTML):,} bytes)")
print(f"  cushion: built {BUILT:,.0f} - gave back {GAVE_BACK:,.0f} = {CUSHION:,.0f}  [reconciles]")
print(f"  run of misses: {RUN_LEN} days, burn {BURN:,.0f}/day, cushion lasts {CUSHION_DAYS:.1f} days")
print(f"  week needs {WEEK_NEEDED:,.0f} = {WEEK_NEEDED/WEEK_REM_TARGET*100:.1f}% of remaining target")
print(f"  month needs {MONTH_NEEDED:,.0f} = {MONTH_NEEDED/MONTH_REM_TARGET*100:.1f}% of remaining target")
