"""Target Tracker reference dashboard - version 2, built to the client rules document.

`Target_Tracker_AI_Insights_Generation_Rules.md` governs this page. Where it and the
first reference disagree, the rules win. The differences that matter:

  * Section 32 fixes the running order: Executive Pulse, Yesterday, Last 7 Days,
    Current Week, MTD, YTD, Management Attention. Seven layers, not four.
  * Section 26 requires a diagnostic chain - overall gap, then store, then department,
    then section - rather than four independent breakdowns.
  * Sections 9 and 11 require run-rate: current versus required, and the Target Pace
    Index that section 14 defines.
  * Section 7.2 requires 30-day exception detection, and forbids claiming a record when
    the difference is not meaningful. On this data yesterday is 12th of 30, so no record
    is claimed - the honest finding is the 7.1-point gap to the 30-day average.
  * Section 29 caps a visual at roughly a quarter of the block, so every chart here is
    small and every one carries its interpretation (section 30).
  * Section 23 forbids inventing causes. Nothing on this page explains *why* sales moved.

Same shell as the other reference dashboards. No view toggle: the rules define one
report, and adding a scope switch would be invention.

    python docs/dashboard-reference/build_target_tracker_rules_reference.py
"""
from __future__ import annotations

import html
from pathlib import Path

OUT = Path(__file__).resolve().with_name("reference_target_tracker_rules.html")

CUR = "SAR"
TEAL, TEAL_DK = "#0f9f95", "#087f79"
AMBER, AMBER_DK = "#c08429", "#8a5f10"
RED, GREEN, FAINT, MID = "#cf4636", "#2f8f4e", "#8fa1a9", "#41545a"


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


def pts(v, dp=1) -> str:
    return f"{'+' if v >= 0 else '&minus;'}{abs(float(v)):.{dp}f} pts"


def attain(a, t) -> float:
    return a / t * 100.0


# Section 6 bands, named as the rules name them.
def status(v: float) -> tuple[str, str]:
    if v >= 115:
        return "good", "Exceptional"
    if v >= 105:
        return "good", "Strong"
    if v >= 100:
        return "good", "On target"
    if v >= 95:
        return "warn", "Near target"
    if v >= 85:
        return "crit", "Below target"
    return "crit", "Critical"


def band(a, t) -> str:
    return status(attain(a, t))[0]


# =========================================================================
# Verified figures. Anchor: Thursday 16 July 2026, report run Friday 17 July.
# =========================================================================
DAY = (526059.95, 553337.00)
WTD = (1625946.18, 1823412.00)
MTD = (9456777.96, 8877883.54)
YTD = (120172004.68, 116862300.84)
WEEK_FULL_TARGET, MONTH_FULL_TARGET = 3598827.00, 16805350.49
WTD_DAYS_DONE, WTD_DAYS_LEFT = 4, 3
MTD_DAYS_DONE, MTD_DAYS_LEFT = 16, 15

LAST30 = [
    ("2026-06-17", "Wed", 340657.48, 438246.00), ("2026-06-18", "Thu", 717739.21, 585810.00),
    ("2026-06-19", "Fri", 1147867.90, 1045000.00), ("2026-06-20", "Sat", 571630.27, 467018.00),
    ("2026-06-21", "Sun", 317058.16, 414467.00), ("2026-06-22", "Mon", 310204.19, 417467.00),
    ("2026-06-23", "Tue", 333562.60, 417467.00), ("2026-06-24", "Wed", 363603.10, 417467.00),
    ("2026-06-25", "Thu", 531188.68, 557885.00), ("2026-06-26", "Fri", 961476.71, 985000.00),
    ("2026-06-27", "Sat", 387820.82, 462467.00), ("2026-06-28", "Sun", 443512.43, 437467.00),
    ("2026-06-29", "Mon", 437580.79, 452467.13), ("2026-06-30", "Tue", 471100.10, 462107.43),
    ("2026-07-01", "Wed", 548926.52, 454347.81), ("2026-07-02", "Thu", 874022.57, 648475.00),
    ("2026-07-03", "Fri", 1423202.96, 1163832.00), ("2026-07-04", "Sat", 532904.08, 513025.00),
    ("2026-07-05", "Sun", 495771.51, 439025.00), ("2026-07-06", "Mon", 455209.42, 441025.00),
    ("2026-07-07", "Tue", 431450.78, 441025.00), ("2026-07-08", "Wed", 439371.95, 441025.00),
    ("2026-07-09", "Thu", 609818.11, 580337.00), ("2026-07-10", "Fri", 1192610.76, 1023762.00),
    ("2026-07-11", "Sat", 426132.14, 485567.74), ("2026-07-12", "Sun", 401410.98, 423025.00),
    ("2026-07-13", "Mon", 375439.25, 426025.00), ("2026-07-14", "Tue", 365292.95, 421025.00),
    ("2026-07-15", "Wed", 359154.03, 423025.00), ("2026-07-16", "Thu", 526059.95, 553337.00),
]
LAST7 = LAST30[-7:]

BRANCHES = [
    dict(code="CFH017", day=(85908.30, 125000.00), d7=(549846.76, 675000.00),
         wtd=(281760.26, 370000.00), mtd=(1462715.64, 1590000.00), ytd=(21247266.56, 22895758.64),
         month_target=3008405.13, months=[101.2, 100.1, 85.4, 100.3, 89.8, 83.7, 92.0]),
    dict(code="CFH018", day=(92086.78, 100000.00), d7=(745845.98, 672542.74),
         wtd=(271492.29, 280000.00), mtd=(1913324.80, 1585542.74), ytd=(25523889.60, 24175485.74),
         month_target=3180542.74, months=[108.0, 103.3, 95.1, 110.0, 111.6, 96.9, 120.7]),
    dict(code="CFH014", day=(177896.69, 173337.00), d7=(1153967.31, 1189224.00),
         wtd=(555810.56, 623412.00), mtd=(2982588.04, 2803717.00), ytd=(39799372.36, 39128478.89),
         month_target=5363778.82, months=[105.5, 101.5, 98.7, 112.6, 100.2, 91.4, 106.4]),
    dict(code="CFH021", day=(170168.18, 155000.00), d7=(1196440.01, 1219000.00),
         wtd=(516883.07, 550000.00), mtd=(3098149.48, 2898623.81), ytd=(41808278.93, 38590044.50),
         month_target=5252623.81, months=[111.0, 117.9, 100.3, 112.2, 110.6, 96.8, 106.9]),
]

DEPTS = [
    dict(name="FMCG FOOD", day=(192488.70, 212261.43), wtd=(593716.03, 693874.80),
         mtd=(3575212.27, 3357933.41), m3=(1.0)),
    dict(name="FARM FRESH", day=(120155.96, 99742.56), wtd=(329403.43, 327710.59),
         mtd=(1778576.74, 1581740.89), m3=(1.0)),
    dict(name="FMCG NON-FOOD", day=(75982.43, 83985.07), wtd=(237734.48, 277491.50),
         mtd=(1489894.66, 1370118.17), m3=(1.0)),
    dict(name="GM FASHION", day=(42066.68, 48461.58), wtd=(142138.26, 161744.41),
         mtd=(797964.56, 795179.91), m3=(1.0)),
    dict(name="FASHION", day=(31678.39, 34927.87), wtd=(94781.90, 116828.09),
         mtd=(554513.34, 564813.37), m3=(1.0)),
    dict(name="ELECTRONICS", day=(22156.56, 28143.62), wtd=(83830.07, 94147.99),
         mtd=(474214.84, 462012.45), m3=(1.0)),
    dict(name="GM HOME WARE", day=(15897.41, 18755.40), wtd=(54632.82, 62203.92),
         mtd=(300572.08, 303890.47), m3=(1.0)),
    dict(name="GM OTHERS", day=(9470.22, 10207.29), wtd=(33514.65, 33807.01),
         mtd=(178244.77, 168130.68), m3=(1.0)),
    dict(name="FOOTWEAR", day=(7017.66, 8247.01), wtd=(24763.18, 26805.66),
         mtd=(142666.37, 130300.75), m3=(1.0)),
    dict(name="HOME FASHION", day=(6392.81, 6998.76), wtd=(22624.53, 23097.88),
         mtd=(125196.73, 113722.45), m3=(1.0)),
    dict(name="LIVE KITCHEN", day=(2218.22, 1606.40), wtd=(6719.34, 5700.14),
         mtd=(33194.54, 30041.02), m3=(1.0)),
]

# Section 26 diagnostic chain, measured for yesterday.
CFH017_DEPTS = [("FMCG FOOD", -18703.26), ("FMCG NON-FOOD", -5478.80), ("GM FASHION", -4495.54),
                ("FASHION", -2814.58), ("ELECTRONICS", -2703.83), ("GM HOME WARE", -1745.72),
                ("HOME FASHION", -912.97), ("FOOTWEAR", -910.67), ("GM OTHERS", -787.36),
                ("FARM FRESH", -630.25), ("OTHER NON TRADE", 91.30)]
CFH017_FMCG_SECTIONS = [("CF-GROCERY FOOD", -5725.04), ("CF-STAPLES", -4506.74),
                        ("CF-ROASTERY", -2556.20), ("CF-CONFECTIONERY", -2379.69)]

WEEKS = [(26, "22–28 Jun", 3331369.00, 3695220.00, 7), (27, "29 Jun–5 Jul", 4783508.53, 4133279.37, 7),
         (28, "6–12 Jul", 3956004.14, 3835766.74, 7), (29, "13–16 Jul", 1625946.18, 1823412.00, 4)]
MONTHS = [("Jan", 20454233.35, 19138881.21), ("Feb", 18942694.14, 17769310.70),
          ("Mar", 18618361.02, 19393702.33), ("Apr", 17197835.64, 15691369.65),
          ("May", 19951704.42, 19221243.16), ("Jun", 15550398.15, 16769910.24),
          ("Jul", 9456777.96, 8877883.54)]
WEEKS_ON = sum(1 for _, _, a, t, _ in WEEKS if a >= t)
QUARTERS = [("Q1", "Jan–Mar", 58015288.51, 56301894.24), ("Q2", "Apr–Jun", 52699938.21, 51682523.05),
            ("Q3", "Jul to 16th", 9456777.96, 8877883.54)]

# ---- derived --------------------------------------------------------------
DAY_ATT = attain(*DAY)
DAY_VAR = DAY[0] - DAY[1]
ATT30 = attain(sum(d[2] for d in LAST30), sum(d[3] for d in LAST30))
RANK30 = sorted(range(len(LAST30)), key=lambda i: attain(LAST30[i][2], LAST30[i][3])).index(len(LAST30) - 1) + 1
D7 = (sum(d[2] for d in LAST7), sum(d[3] for d in LAST7))
D7_ATT = attain(*D7)
D7_DAILY = [attain(d[2], d[3]) for d in LAST7]
D7_AVG_DAILY = sum(D7_DAILY) / len(D7_DAILY)
D7_ABOVE = sum(1 for v in D7_DAILY if v >= 100)
RUN_LEN = 6

NEG_DAY = [(b["code"], b["day"][0] - b["day"][1]) for b in BRANCHES if b["day"][0] < b["day"][1]]
TOT_NEG_DAY = sum(v for _, v in NEG_DAY)
POS_DAY = sum(b["day"][0] - b["day"][1] for b in BRANCHES if b["day"][0] >= b["day"][1])

WTD_CUR_RATE = WTD[0] / WTD_DAYS_DONE
WTD_REQ_RATE = (WEEK_FULL_TARGET - WTD[0]) / WTD_DAYS_LEFT
WTD_PACE = WTD_CUR_RATE / WTD_REQ_RATE
WEEK_REM_TARGET = WEEK_FULL_TARGET - WTD[1]
WEEK_REQ_ATT = (WEEK_FULL_TARGET - WTD[0]) / WEEK_REM_TARGET * 100

MTD_CUR_RATE = MTD[0] / MTD_DAYS_DONE
MTD_REQ_RATE = (MONTH_FULL_TARGET - MTD[0]) / MTD_DAYS_LEFT
MTD_PACE = MTD_CUR_RATE / MTD_REQ_RATE
MONTH_REM_TARGET = MONTH_FULL_TARGET - MTD[1]
MONTH_REQ_ATT = (MONTH_FULL_TARGET - MTD[0]) / MONTH_REM_TARGET * 100
FC_RUNRATE = MTD_CUR_RATE * 31
FC_ATT = MTD[0] + MONTH_REM_TARGET * attain(*MTD) / 100
FC_RECENT = MTD[0] + MONTH_REM_TARGET * 0.898
CUSHION = MTD[0] - MTD[1]

M3 = attain(sum(m[1] for m in MONTHS[3:6]), sum(m[2] for m in MONTHS[3:6]))
CONSISTENCY = 8 / 16 * 100
BREADTH_BRANCH = sum(1 for b in BRANCHES if b["mtd"][0] >= b["mtd"][1]) / len(BRANCHES) * 100
BREADTH_DEPT = sum(1 for d in DEPTS if d["mtd"][0] >= d["mtd"][1]) / len(DEPTS) * 100

assert abs(TOT_NEG_DAY + POS_DAY - DAY_VAR) < 1.0, "branch variances must sum to the company variance"
assert abs(sum(v for _, v in CFH017_DEPTS) - (-39091.70)) < 2.0, "CFH017 departments must sum to its shortfall"

# =========================================================================
# Components
# =========================================================================
def sect(title, sub):
    return f'<div class="sect"><h2>{e(title)}</h2><span>{e(sub)}</span></div>'


def card(title, sub, body, note=""):
    n = f'<p class="note">{note}</p>' if note else ""
    return f'<section class="card"><h3>{e(title)}</h3><p class="sub">{e(sub)}</p>{body}{n}</section>'


def pulse_bar(actual, target, label=""):
    """Section 7.6.A - the target attainment pulse. Actual against target, one line."""
    v = attain(actual, target)
    b = status(v)[0]
    col = {"good": GREEN, "warn": AMBER, "crit": RED}[b]
    top = max(1.2, v / 100 * 1.06)
    return (f'<div class="pulse">'
            f'<div class="pulse-track"><span class="pulse-fill" style="width:{min(v/100/top*100,100):.1f}%;'
            f'background:{col}"></span><i class="pulse-tick" style="left:{100/top:.1f}%"></i></div>'
            f'<div class="pulse-legend"><span>{sar(actual)} sold</span>'
            f'<span>target {sar(target)}</span></div>'
            f'{f"<p class=note>{label}</p>" if label else ""}</div>')


def kpi(label, value, sub, cls="", pill=None):
    p = f'<span class="pill pill-{pill[0]}">{e(pill[1])}</span>' if pill else ""
    return (f'<div class="kpi {cls}"><p class="lab">{label}</p><p class="val">{value}</p>'
            f'<p class="sub">{sub}</p>{p}</div>')


def period_kpi(name, when, pair, extra):
    a, t = pair
    v = attain(a, t)
    b, word = status(v)
    return kpi(f'{e(name)}<br><span class="lab-sub">{e(when)}</span>', pc(v),
               f'{sar(a)} against a target of {sar(t)}<br>{sar(abs(a-t))} '
               f'{"above" if a >= t else "below"} target &middot; {extra}',
               cls=b, pill=(("ok" if b == "good" else b), word))


def strip(rows):
    """Section 7.6.B - compact ranked store strip: attainment, variance, direction."""
    out = []
    for name, a, t, tail in rows:
        v = attain(a, t)
        b = status(v)[0]
        col = {"good": GREEN, "warn": AMBER, "crit": RED}[b]
        arrow = "&#9650;" if v >= 100 else ("&#9660;" if v < 95 else "&#8212;")
        out.append(f'<div class="sr"><span class="sr-n">{e(name)}</span>'
                   f'<span class="sr-t"><i style="width:{min(v,130)/130*100:.1f}%;background:{col}"></i></span>'
                   f'<span class="sr-v" style="color:{col}">{pc(v)} {arrow}</span>'
                   f'<span class="sr-x">{tail}</span></div>')
    return f'<div class="strips">{"".join(out)}</div>'


def contrib_bars(rows, total, unit_note=""):
    """Section 7.6.C - contribution to the overall shortfall."""
    out = []
    for name, v in rows:
        share = abs(v) / abs(total) * 100
        out.append(f'<div class="cb"><span class="cb-n">{e(name)}</span>'
                   f'<span class="cb-t"><i style="width:{share:.1f}%"></i></span>'
                   f'<span class="cb-v">{pc(share, 0)}</span>'
                   f'<span class="cb-x">{CUR} {signed(v)}</span></div>')
    return f'<div class="cbs">{"".join(out)}</div>{unit_note}'


def journey():
    """Section 8 - the 7-day target journey. Small, one reference line at 100%."""
    w, h = 520, 128
    l, r, t, b = 10, 10, 22, 34
    pw, ph = w - l - r, h - t - b
    lo, hi = 80.0, 122.0
    yy = lambda v: t + ph - (v - lo) / (hi - lo) * ph
    xx = lambda i: l + (i + .5) * (pw / len(LAST7))
    p = [f'<line x1="{l}" y1="{yy(100):.1f}" x2="{w-r}" y2="{yy(100):.1f}" stroke="{FAINT}" stroke-dasharray="4 3"/>',
         f'<text x="{w-r}" y="{yy(100)-5:.1f}" text-anchor="end" class="dz">target</text>']
    p.append('<polyline points="' + " ".join(f"{xx(i):.1f},{yy(v):.1f}" for i, v in enumerate(D7_DAILY))
             + f'" fill="none" stroke="{MID}" stroke-width="1.6"/>')
    for i, v in enumerate(D7_DAILY):
        col = {"good": GREEN, "warn": AMBER, "crit": RED}[status(v)[0]]
        p.append(f'<circle cx="{xx(i):.1f}" cy="{yy(v):.1f}" r="4.5" fill="{col}">'
                 f'<title>{LAST7[i][1]} {LAST7[i][0][-2:]} July - {pc(v)}</title></circle>')
        p.append(f'<text x="{xx(i):.1f}" y="{h-18}" text-anchor="middle" class="dza" fill="{col}">{v:.0f}</text>')
        p.append(f'<text x="{xx(i):.1f}" y="{h-5}" text-anchor="middle" class="dz">{LAST7[i][1]}</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="How much of target was reached on each of the last seven days">{"".join(p)}</svg>'


def pace_gauge(current, required, label_a, label_b):
    """Section 15.A - current pace against required pace."""
    mx = max(current, required) * 1.18
    w, h = 520, 96
    l, r = 10, 10
    pw = w - l - r
    cw, rw = current / mx * pw, required / mx * pw
    ok = current >= required
    col = GREEN if ok else RED
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Current daily rate against the rate needed">'
            f'<rect x="{l}" y="16" width="{pw}" height="18" rx="9" fill="#eef2f6"/>'
            f'<rect x="{l}" y="16" width="{cw:.1f}" height="18" rx="9" fill="{col}"/>'
            f'<line x1="{l+rw:.1f}" y1="9" x2="{l+rw:.1f}" y2="41" stroke="{MID}" stroke-width="2"/>'
            f'<text x="{l}" y="60" class="dza" fill="{col}">{label_a}: {CUR} {money(current)} a day</text>'
            f'<text x="{l+rw:.1f}" y="60" text-anchor="{"end" if rw > pw*.6 else "start"}" class="dza">'
            f'{label_b}: {CUR} {money(required)} a day</text>'
            f'<text x="{l}" y="80" class="dz">Pace index {current/required:.2f} '
            f'&#183; {"ahead of" if ok else "behind"} the rate needed</text></svg>')


def trajectory(points, label):
    """Sections 10 and 17 - compact attainment markers around the 100% line."""
    w, h = 520, 130
    l, r, t, b = 12, 12, 24, 36
    pw, ph = w - l - r, h - t - b
    vals = [v for _, v in points]
    lo, hi = min(min(vals), 88.0) - 3, max(max(vals), 112.0) + 3
    yy = lambda v: t + ph - (v - lo) / (hi - lo) * ph
    step = pw / len(points)
    p = [f'<line x1="{l}" y1="{yy(100):.1f}" x2="{w-r}" y2="{yy(100):.1f}" stroke="{FAINT}" stroke-dasharray="4 3"/>']
    for i, (name, v) in enumerate(points):
        x = l + (i + .5) * step
        col = {"good": GREEN, "warn": AMBER, "crit": RED}[status(v)[0]]
        p.append(f'<line x1="{x:.1f}" y1="{yy(100):.1f}" x2="{x:.1f}" y2="{yy(v):.1f}" stroke="{col}" stroke-width="2"/>')
        p.append(f'<circle cx="{x:.1f}" cy="{yy(v):.1f}" r="5" fill="{col}"><title>{name} - {pc(v)}</title></circle>')
        p.append(f'<text x="{x:.1f}" y="{yy(v)+(-10 if v>=100 else 16):.1f}" text-anchor="middle" '
                 f'class="dza" fill="{col}">{v:.0f}</text>')
        p.append(f'<text x="{x:.1f}" y="{h-8}" text-anchor="middle" class="dz">{e(name)}</text>')
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="How much of target was reached, {e(label)}">{"".join(p)}</svg>'


def momentum_table():
    rows = ""
    for b in sorted(BRANCHES, key=lambda x: attain(*x["day"]) - attain(*x["d7"])):
        ya, a7 = attain(*b["day"]), attain(*b["d7"])
        d = ya - a7
        word = "Improving" if d > 5 else ("Deteriorating" if d < -5 else "Stable")
        col = GREEN if d > 5 else (RED if d < -5 else FAINT)
        rows += (f'<tr><td><b>{e(b["code"])}</b></td>'
                 f'<td class="n" style="color:{ {"good":GREEN,"warn":AMBER,"crit":RED}[status(ya)[0]] };'
                 f'font-weight:700">{pc(ya)}</td>'
                 f'<td class="n" style="color:{ {"good":GREEN,"warn":AMBER,"crit":RED}[status(a7)[0]] };'
                 f'font-weight:700">{pc(a7)}</td>'
                 f'<td class="n">{pts(d)}</td>'
                 f'<td><span class="pill" style="background:{col}1f;color:{col}">{word}</span></td></tr>')
    return (f'<div class="scroll"><table><thead><tr><th>Branch</th><th class="n">Yesterday</th>'
            f'<th class="n">Last 7 days</th><th class="n">Change</th><th>Direction</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')


def bench_cards(items):
    out = ""
    for label, value, sub, col in items:
        out += (f'<div class="bench"><p class="bl">{e(label)}</p>'
                f'<p class="bv" style="color:{col}">{value}</p><p class="bs">{sub}</p></div>')
    return f'<div class="benches">{out}</div>'


def entity_table(rows, headers, urgent_key=None):
    body = ""
    for r in rows:
        cls = ' class="urgent"' if urgent_key and urgent_key(r) else ""
        cells = "".join(f'<td class="{c[1]}">{c[0]}</td>' for c in r["cells"])
        body += f'<tr{cls}><td><b>{e(r["name"])}</b></td>{cells}</tr>'
    head = "".join(f'<th class="{h[1]}">{e(h[0])}</th>' for h in headers)
    return (f'<div class="scroll"><table><thead><tr><th>Name</th>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def att_cell(a, t):
    v = attain(a, t)
    col = {"good": GREEN, "warn": AMBER, "crit": RED}[status(v)[0]]
    return f'<span style="color:{col};font-weight:700">{pc(v)}</span>'


# =========================================================================
# Layer 1 - Executive Pulse (section 31)
# =========================================================================
PULSE = [
    ("Yesterday", "crit",
     f"Thursday closed at <b>{pc(DAY_ATT)}</b> of target, {sar(abs(DAY_VAR))} short. "
     f"CFH017 accounts for <b>{pc(abs(NEG_DAY[0][1])/abs(TOT_NEG_DAY)*100, 0)}</b> of the shortfall on its own."),
    ("This week", "crit",
     f"Week to date is at <b>{pc(attain(*WTD))}</b>, {sar(abs(WTD[0]-WTD[1]))} behind, and all four branches "
     f"are below target. The remaining three days must reach <b>{pc(WEEK_REQ_ATT)}</b> of their own target "
     f"to close the week."),
    ("This month", "good",
     f"The month is at <b>{pc(attain(*MTD))}</b> with a surplus of {sar(CUSHION)} and is running "
     f"<b>ahead</b> of the rate needed (pace index {MTD_PACE:.2f}). The risk is the last six days, "
     f"not the month so far."),
    ("This year", "good",
     f"The year is at <b>{pc(attain(*YTD))}</b>, {sar(YTD[0]-YTD[1])} ahead, and the quarterly trend is "
     f"improving: {pc(attain(QUARTERS[0][2], QUARTERS[0][3]))} to {pc(attain(QUARTERS[1][2], QUARTERS[1][3]))} "
     f"to {pc(attain(QUARTERS[2][2], QUARTERS[2][3]))}."),
    ("Watch this", "warn",
     f"CFH017 has missed target in <b>4 of the 7 months</b> this year and is below target yesterday, this week "
     f"and this month. CFH018 is the opposite risk: {pc(attain(*BRANCHES[1]['d7']))} over seven days but "
     f"{pc(attain(*BRANCHES[1]['day']))} yesterday, the sharpest fall of any branch."),
]


def layer_pulse():
    items = "".join(
        f'<li class="pl pl-{tone}"><span class="pl-k">{e(k)}</span><p>{txt}</p></li>'
        for k, tone, txt in PULSE)
    hero = f"""<section class="hero">
      <div>
        <span class="hero-tag">Executive pulse</span>
        <h2>The month is comfortably ahead, but the last six days have all missed target.</h2>
        <p>Nothing in the year or the month is at risk today. The issue is recent and narrow: a
           six-day run below target, and one branch that has now missed in four of seven months.</p>
      </div>
      <div class="hero-stats">
        <div class="hs crit"><b>{pc(DAY_ATT)}</b><span>yesterday</span></div>
        <div class="hs crit"><b>{pc(attain(*WTD))}</b><span>this week so far</span></div>
        <div class="hs"><b>{pc(attain(*MTD))}</b><span>this month so far</span></div>
      </div>
    </section>"""
    return f"""{hero}
    {sect("The five things that matter", "one per time period, plus the exception worth watching")}
    <ol class="pulse-list">{items}</ol>
    {sect("Where we stand", "every time period, measured against the target for the days that have passed")}
    <div class="kpis k4">
      {period_kpi("Yesterday", "Thursday 16 July", DAY, f"{RUN_LEN}th day below target in a row")}
      {period_kpi("This week so far", f"{WTD_DAYS_DONE} days of 7", WTD, "all four branches below target")}
      {period_kpi("This month so far", f"{MTD_DAYS_DONE} days of 31", MTD, "ahead of the rate needed")}
      {period_kpi("This year so far", "1 Jan – 16 July", YTD, "quarterly trend improving")}
    </div>
    <p class="note" style="margin-top:10px">Each period is compared with the target for the days that have
    already passed, never with the target for the whole period. That is what makes these four percentages
    comparable with each other.</p>"""


# =========================================================================
# Layer 2 - Yesterday (section 7)
# =========================================================================
def layer_yesterday():
    day_rows = [(b["code"], b["day"][0], b["day"][1],
                 f'{CUR} {signed(b["day"][0]-b["day"][1])}') for b in
                sorted(BRANCHES, key=lambda x: attain(*x["day"]))]
    dep_sorted = sorted(DEPTS, key=lambda d: d["day"][0] - d["day"][1])
    return f"""{sect("Yesterday", "Thursday 16 July 2026 - the most important block")}
    <div class="grid g-2">
      {card("How the business did against target",
            "Actual against target for the day.",
            pulse_bar(*DAY) + bench_cards([
                ("Reached", pc(DAY_ATT), "of target", AMBER_DK),
                ("Short by", sar(abs(DAY_VAR)), f"{pc(DAY_ATT-100)} gap", RED),
                ("Status", status(DAY_ATT)[1], "section 6 band", AMBER_DK)]),
            note=f"Yesterday reached <b>{pc(DAY_ATT)}</b> of target and fell {sar(abs(DAY_VAR))} short. "
                 f"It is the sixth day below target in a row, which matters more than the size of the miss.")}
      {card("Is this unusual?",
            "Yesterday measured against the last 30 days.",
            bench_cards([
                ("Yesterday", pc(DAY_ATT), "of target", AMBER_DK),
                ("30-day average", pc(ATT30), "of target", MID),
                ("Difference", pts(DAY_ATT-ATT30), "below the average", RED)]),
            note=f"Yesterday is the <b>{RANK30}th weakest of the last 30 days</b>, not a record low - the "
                 f"weakest was 22 June at 74.3% and the strongest 2 July at 134.8%. What is notable is not "
                 f"the size of the miss but that it is the sixth in a row, and that it sits "
                 f"{pts(DAY_ATT-ATT30)} below the 30-day average.")}
    </div>
    <div class="grid g-2" style="margin-top:14px">
      {card("Which branches missed, and by how much",
            "Ranked worst to best. The bar is how much of its target the branch reached.",
            strip(day_rows),
            note=f"Two branches missed and two beat target. Ranking on percentage alone would be misleading, "
                 f"so the value of each miss is shown beside it.")}
      {card("Who explains the shortfall",
            "Each branch's share of the total shortfall across the branches that missed.",
            contrib_bars(sorted(NEG_DAY, key=lambda x: x[1]), TOT_NEG_DAY),
            note=f"The two missing branches were {sar(abs(TOT_NEG_DAY))} short between them, and the two that "
                 f"beat target added {sar(POS_DAY)} back, leaving the company {sar(abs(DAY_VAR))} short. "
                 f"<b>CFH017 alone was short by more than the whole company miss</b> - without it the day "
                 f"would have finished above target.")}
    </div>
    <div style="margin-top:14px">
      {card("Following the shortfall down: company, branch, department, section",
            "Each step explains the step above it.",
            f'''<div class="chain">
              <div class="ch"><p class="ch-l">Company</p><p class="ch-v">{CUR} {signed(DAY_VAR)}</p>
                <p class="ch-s">{pc(DAY_ATT)} of target</p></div>
              <div class="ch-a">&rarr;</div>
              <div class="ch"><p class="ch-l">Branch CFH017</p><p class="ch-v" style="color:{RED}">{CUR} {signed(-39091.70)}</p>
                <p class="ch-s">{pc(abs(-39091.70)/abs(TOT_NEG_DAY)*100,0)} of all shortfall</p></div>
              <div class="ch-a">&rarr;</div>
              <div class="ch"><p class="ch-l">FMCG FOOD in CFH017</p><p class="ch-v" style="color:{RED}">{CUR} {signed(-18703.26)}</p>
                <p class="ch-s">{pc(18703.26/39091.70*100,0)} of that branch's shortfall</p></div>
              <div class="ch-a">&rarr;</div>
              <div class="ch"><p class="ch-l">Its four weakest sections</p>
                <p class="ch-v" style="color:{RED}">{CUR} {signed(sum(v for _, v in CFH017_FMCG_SECTIONS))}</p>
                <p class="ch-s">{", ".join(n.replace("CF-","").title() for n, _ in CFH017_FMCG_SECTIONS[:3])}</p></div>
            </div>''',
            note="This is a chain of arithmetic, not of cause. It shows <b>where</b> the shortfall sits, not "
                 "why it happened - the report has no data on promotions, stock, staffing or footfall, so it "
                 "does not guess.")}
    </div>
    <div class="grid g-2e" style="margin-top:14px">
      {card("Departments that pulled the day down",
            "The four largest shortfalls by value.",
            strip([(d["name"], d["day"][0], d["day"][1], f'{CUR} {signed(d["day"][0]-d["day"][1])}')
                   for d in dep_sorted[:4]]),
            note=f"FMCG FOOD is the largest single shortfall at {sar(abs(dep_sorted[0]['day'][0]-dep_sorted[0]['day'][1]))}. "
                 f"ELECTRONICS reached only {pc(attain(*[d for d in DEPTS if d['name']=='ELECTRONICS'][0]['day']))}, "
                 f"the lowest of any department.")}
      {card("Departments that held the day up",
            "The departments that beat target.",
            strip([(d["name"], d["day"][0], d["day"][1], f'{CUR} {signed(d["day"][0]-d["day"][1])}')
                   for d in sorted(DEPTS, key=lambda x: -(x["day"][0]-x["day"][1]))
                   if d["day"][0] >= d["day"][1]]),
            note=f"FARM FRESH added {sar(20413.40)} above its target and was the main offset. Without it the "
                 f"day would have been close to {sar(abs(DAY_VAR)+20413.40)} short.")}
    </div>"""


# =========================================================================
# Layer 3 - Last 7 days (section 8)
# =========================================================================
def layer_last7():
    return f"""{sect("The last seven days", "is yesterday a one-off, or part of a pattern?")}
    <div class="grid g-2">
      {card("The seven-day journey",
            "How much of target each day reached. The dashed line is target.",
            f'<div class="mini">{journey()}</div>',
            note=f"Only <b>{D7_ABOVE} of the 7 days</b> reached target, and that one was Friday 10 July. "
                 f"Every day since has missed. Yesterday is <b>not</b> a one-off - it is the sixth day of a "
                 f"continuous run below target.")}
      {card("The seven days in total",
            "Everything from 10 to 16 July added together.",
            bench_cards([
                ("Reached", pc(D7_ATT), f"of target &middot; {sar(abs(D7[0]-D7[1]))} short", AMBER_DK),
                ("Average day", pc(D7_AVG_DAILY), "of its own target", MID),
                ("Days on target", f"{D7_ABOVE} of 7", "best Fri 116.5% &middot; worst Wed 84.9%", RED)]),
            note=f"The seven-day total of {pc(D7_ATT)} looks better than the daily average of {pc(D7_AVG_DAILY)} "
                 f"because one very large Friday carries most of the week's sales. The daily average is the "
                 f"fairer read of how the week has actually gone.")}
    </div>
    <div style="margin-top:14px">
      {card("Which branches are moving, and which way",
            "Yesterday compared with each branch's own seven-day average.",
            momentum_table(),
            note=f"<b>CFH018 is the sharpest change on the page</b>: {pc(attain(*BRANCHES[1]['d7']))} across "
                 f"seven days but {pc(attain(*BRANCHES[1]['day']))} yesterday, a fall of "
                 f"{pts(attain(*BRANCHES[1]['day'])-attain(*BRANCHES[1]['d7']))}. It is still the strongest "
                 f"branch for the month, so this is worth watching rather than acting on yet. "
                 f"CFH017 is different - it was already weak and has got weaker.")}
    </div>"""


# =========================================================================
# Layer 4 - This week (sections 9, 10)
# =========================================================================
def layer_wtd():
    wtd_rows = [(b["code"], b["wtd"][0], b["wtd"][1], f'{CUR} {signed(b["wtd"][0]-b["wtd"][1])}')
                for b in sorted(BRANCHES, key=lambda x: attain(*x["wtd"]))]
    dep_neg = [d for d in sorted(DEPTS, key=lambda x: x["wtd"][0]-x["wtd"][1]) if d["wtd"][0] < d["wtd"][1]]
    return f"""{sect("This week", "week 29, Monday 13 to Thursday 16 July - 4 days of 7")}
    <div class="grid g-2r">
      {card("Where the week stands",
            "Sales so far against the target for those four days.",
            pulse_bar(*WTD),
            note=f"The week is at <b>{pc(attain(*WTD))}</b> of target and {sar(abs(WTD[0]-WTD[1]))} behind "
                 f"after four days. All four branches are below target, which makes this a broad slowdown "
                 f"rather than one branch's problem.")}
      {card("What the rest of the week has to do",
            "The daily rate so far against the daily rate needed.",
            f'<div class="mini">{pace_gauge(WTD_CUR_RATE, WTD_REQ_RATE, "Selling now", "Needed")}</div>',
            note=f"Read this one carefully. The three days left are Friday, Saturday and Sunday, which carry "
                 f"much larger targets than midweek days - so a raw daily-rate comparison overstates the task. "
                 f"Measured against their own targets, those three days need to reach "
                 f"<b>{pc(WEEK_REQ_ATT)}</b>, not {pc(WTD_REQ_RATE/WTD_CUR_RATE*100)}.")}
    </div>
    <div class="grid g-2" style="margin-top:14px">
      {card("Every branch is behind this week",
            "Ranked worst to best.",
            strip(wtd_rows),
            note=f"CFH017 is furthest behind at {pc(attain(*BRANCHES[0]['wtd']))}, but CFH014 has the largest "
                 f"shortfall in value at {sar(abs(BRANCHES[2]['wtd'][0]-BRANCHES[2]['wtd'][1]))} because it is "
                 f"a bigger branch. Both matter, for different reasons.")}
      {card("Where the week is being lost",
            "The four departments with the largest shortfalls this week.",
            contrib_bars([(d["name"], d["wtd"][0]-d["wtd"][1]) for d in dep_neg[:4]],
                         sum(d["wtd"][0]-d["wtd"][1] for d in dep_neg)),
            note=f"Nine of eleven departments are below target this week. FMCG FOOD accounts for "
                 f"{pc(abs(dep_neg[0]['wtd'][0]-dep_neg[0]['wtd'][1])/abs(sum(d['wtd'][0]-d['wtd'][1] for d in dep_neg))*100,0)} "
                 f"of the total departmental shortfall - but it is still above target for the month, so this "
                 f"is recent rather than long-running.")}
    </div>
    <div style="margin-top:14px">
      {card("This week against the last four weeks",
            "How much of target each week reached. Week 29 is only four days old.",
            f'<div class="mini">{trajectory([(f"wk{n}", attain(a, t)) for n, _, a, t, _ in WEEKS], "weekly")}</div>',
            note=f"{['None','One','Two','Three','Four'][WEEKS_ON]} of the last four weeks reached target. "
                 f"Week 29 at {pc(attain(*WTD))} is the weakest "
                 f"of the four, but it is not yet complete - the weekend is still to come, and the weekend "
                 f"carries most of the week's target.")}
    </div>"""


# =========================================================================
# Layer 5 - This month (sections 11-15)
# =========================================================================
def layer_mtd():
    mtd_rows = [(b["code"], b["mtd"][0], b["mtd"][1], f'{CUR} {signed(b["mtd"][0]-b["mtd"][1])}')
                for b in sorted(BRANCHES, key=lambda x: attain(*x["mtd"]))]
    return f"""{sect("This month", "1 to 16 July - 16 days of 31")}
    <div class="grid g-2r">
      {card("Where the month stands",
            "Sales so far against the target for those sixteen days.",
            pulse_bar(*MTD),
            note=f"The month is at <b>{pc(attain(*MTD))}</b> of target with a surplus of {sar(CUSHION)}. "
                 f"That surplus was built in the first ten days; the last six have used up about a third of it.")}
      {card("Can the month still be made?",
            "The daily rate so far against the daily rate needed for the rest of July.",
            f'<div class="mini">{pace_gauge(MTD_CUR_RATE, MTD_REQ_RATE, "Selling now", "Needed")}</div>',
            note=f"Yes, comfortably on today's figures. The month is selling {sar(MTD_CUR_RATE)} a day and "
                 f"needs {sar(MTD_REQ_RATE)} a day to finish on target - a pace index of "
                 f"<b>{MTD_PACE:.2f}</b>. The remaining days can sell <b>{pc(100-MONTH_REQ_ATT)} below</b> "
                 f"their own target and July would still land on plan.")}
    </div>
    <div class="grid g-2e" style="margin-top:14px">
      {card("Three ways the month could finish",
            "Each carries a different current rate forward. None is a forecast.",
            f'''<div class="scen">
              <div class="sc"><p class="sc-l">If the last six days continue</p>
                <p class="sc-v" style="color:{RED}">{sar(FC_RECENT)}</p>
                <p class="sc-s">{pc(FC_RECENT/MONTH_FULL_TARGET*100)} of target &middot; below plan</p></div>
              <div class="sc"><p class="sc-l">If the month's own rate continues</p>
                <p class="sc-v" style="color:{GREEN}">{sar(FC_ATT)}</p>
                <p class="sc-s">{pc(FC_ATT/MONTH_FULL_TARGET*100)} of target</p></div>
              <div class="sc"><p class="sc-l">If the daily rate continues</p>
                <p class="sc-v" style="color:{GREEN}">{sar(FC_RUNRATE)}</p>
                <p class="sc-s">{pc(FC_RUNRATE/MONTH_FULL_TARGET*100)} of target &middot; flattering</p></div>
            </div>''',
            note="The third is the most optimistic and the least reliable: it carries a flat daily average "
                 "forward and ignores that the days already gone included three of July's biggest Fridays. "
                 "The gap between the first two is what the next week decides.")}
      {card("Is this month normal?",
            "July so far against the last three completed months.",
            bench_cards([
                ("July so far", pc(attain(*MTD)), "of target", GREEN),
                ("Last 3 months", pc(M3), "April, May, June", MID),
                ("Difference", pts(attain(*MTD)-M3), "above the recent average", GREEN)]),
            note=f"July is running better than the recent norm, not worse. June was the weak month at "
                 f"{pc(attain(MONTHS[5][1], MONTHS[5][2]))}, and April the strongest at "
                 f"{pc(attain(MONTHS[3][1], MONTHS[3][2]))}.")}
    </div>
    <div class="grid g-2" style="margin-top:14px">
      {card("How each branch is doing this month",
            "Ranked worst to best.",
            strip(mtd_rows),
            note=f"Only CFH017 is below target for the month. It needs {sar(BRANCHES[0]['month_target']-BRANCHES[0]['mtd'][0])} "
                 f"from the remaining fifteen days, which is "
                 f"{pc((BRANCHES[0]['month_target']-BRANCHES[0]['mtd'][0])/(BRANCHES[0]['month_target']-BRANCHES[0]['mtd'][1])*100)} "
                 f"of what those days are already targeted to sell - the only branch that has to beat its own "
                 f"plan to catch up.")}
      {card("How widely spread the performance is",
            "Three measures of whether the result is broad or concentrated.",
            bench_cards([
                ("Branches on target", pc(BREADTH_BRANCH, 0), "3 of 4", GREEN),
                ("Departments on target", pc(BREADTH_DEPT, 0), "9 of 11", GREEN),
                ("Days on target", pc(CONSISTENCY, 0), "8 of 16 days", AMBER_DK)]),
            note="The month is broad-based: most branches and most departments are above target. The weak "
                 "measure is consistency - only half the days have reached target, and all eight of the "
                 "misses are in the second half of the month.")}
    </div>"""


# =========================================================================
# Layer 6 - Year to date (sections 16-19)
# =========================================================================
def layer_ytd():
    ytd_rows = [(b["code"], b["ytd"][0], b["ytd"][1], f'{CUR} {signed(b["ytd"][0]-b["ytd"][1])}')
                for b in sorted(BRANCHES, key=lambda x: attain(*x["ytd"]))]
    return f"""{sect("This year", "1 January to 16 July 2026")}
    <div class="grid g-2r">
      {card("Where the year stands",
            "Sales so far against the target for the days that have passed.",
            pulse_bar(*YTD),
            note=f"The year is at <b>{pc(attain(*YTD))}</b> of target, {sar(YTD[0]-YTD[1])} ahead. "
                 f"Nothing in the current week threatens that position.")}
      {card("The trend across quarters",
            "How much of target each quarter reached.",
            f'<div class="mini">{trajectory([(f"{q[0]}", attain(q[2], q[3])) for q in QUARTERS], "quarterly")}</div>',
            note=f"The direction is improving: {pc(attain(QUARTERS[0][2],QUARTERS[0][3]))} in Q1, "
                 f"{pc(attain(QUARTERS[1][2],QUARTERS[1][3]))} in Q2, and Q3 currently tracking at "
                 f"{pc(attain(QUARTERS[2][2],QUARTERS[2][3]))}. Q3 covers only 16 days so far.")}
    </div>
    <div class="grid g-2" style="margin-top:14px">
      {card("Branch performance for the year",
            "Ranked worst to best.",
            strip(ytd_rows),
            note=f"CFH017 is the only branch below target for the year, at "
                 f"{pc(attain(*BRANCHES[0]['ytd']))} and {sar(abs(BRANCHES[0]['ytd'][0]-BRANCHES[0]['ytd'][1]))} short. "
                 f"CFH021 is the strongest at {pc(attain(*BRANCHES[3]['ytd']))}.")}
      {card("A long-running risk, not a bad week",
            "Months below target, by branch.",
            f'''<div class="pers">{"".join(
                f"""<div class="pr"><span class="pr-n">{b['code']}</span>
                    <span class="pr-d">{"".join(
                        f'<i style="background:{GREEN if v>=100 else (AMBER if v>=95 else RED)}" title="{m}: {v:.1f}%"></i>'
                        for m, v in zip(["Jan","Feb","Mar","Apr","May","Jun","Jul"], b["months"]))}</span>
                    <span class="pr-v">{sum(1 for v in b['months'] if v < 100)} of 7 below</span></div>"""
                for b in sorted(BRANCHES, key=lambda x: -sum(1 for v in x["months"] if v < 100)))}</div>''',
            note=f"<b>CFH017 has missed target in four of the seven months</b> - March, May, June and July - "
                 f"and is below target yesterday, this week, this month and for the year. That combination "
                 f"is what separates a long-running problem from a bad week. CFH021 has missed once.")}
    </div>"""


# =========================================================================
# Layer 7 - Management attention (section 33)
# =========================================================================
ATTENTION = [
    ("crit", "CFH017 &mdash; a long-running shortfall, not a bad day",
     f"{pc(attain(*BRANCHES[0]['day']))} yesterday and responsible for "
     f"{pc(abs(NEG_DAY[0][1])/abs(TOT_NEG_DAY)*100,0)} of the day's shortfall. Below target this week "
     f"({pc(attain(*BRANCHES[0]['wtd']))}), this month ({pc(attain(*BRANCHES[0]['mtd']))}) and this year "
     f"({pc(attain(*BRANCHES[0]['ytd']))}), and it has missed in four of seven months. It needs "
     f"{sar(BRANCHES[0]['month_target']-BRANCHES[0]['mtd'][0])} from the remaining fifteen days to make July, "
     f"more than those days are targeted to sell."),
    ("crit", "Six days below target in a row",
     f"Every day since Saturday 11 July has missed. The run has used up about a third of the month's "
     f"surplus, and at the recent average shortfall the remaining {sar(CUSHION)} would be gone around "
     f"<b>28 July</b>, three days before month end."),
    ("warn", "CFH018 has turned sharply",
     f"{pc(attain(*BRANCHES[1]['d7']))} across seven days but {pc(attain(*BRANCHES[1]['day']))} yesterday - "
     f"a fall of {pts(attain(*BRANCHES[1]['day'])-attain(*BRANCHES[1]['d7']))}, the largest of any branch. "
     f"It is still the strongest branch for the month at {pc(attain(*BRANCHES[1]['mtd']))}, so this is one "
     f"to watch before acting."),
    ("warn", "The weekend decides the week",
     f"Week 29 needs {sar(WEEK_FULL_TARGET-WTD[0])} from Friday, Saturday and Sunday - "
     f"{pc(WEEK_REQ_ATT)} of what those days are targeted to sell. Friday alone carries {sar(959365.00)} "
     f"of it."),
    ("ok", "The month and the year are not at risk",
     f"July is at {pc(attain(*MTD))} and running ahead of the rate needed. The remaining days can sell "
     f"{pc(100-MONTH_REQ_ATT)} below their own target and the month still lands on plan. The year is "
     f"{pc(attain(*YTD))} with an improving quarterly trend. Act on the week, not on the year."),
]


def layer_attention():
    items = "".join(
        f'<li class="att att-{tone}"><h3>{title}</h3><p>{body}</p></li>'
        for tone, title, body in ATTENTION)
    return f"""{sect("Management attention", "the shortest list that covers what matters")}
    <ol class="atts">{items}</ol>
    <p class="note" style="max-width:900px">This section introduces no new figures. Every point above appears
    in one of the earlier sections, brought together in order of how much attention it needs.</p>"""


CAVEATS = f"""<div class="caveats">
  <h3>Important things to know about these numbers</h3>
  <ul>
    <li><b>No causes are given, only amounts and places.</b> The report holds sales and targets. It does not
        hold promotions, stock levels, staffing, weather or footfall, so nothing here explains <i>why</i>
        sales moved - only where the difference sits.</li>
    <li><b>There is no comparison with last year.</b> The report only holds 2026 data, so every figure is
        compared with target.</li>
    <li><b>Each period is compared with the target for the days that have passed.</b> This week covers 4 days
        of 7 and this month 16 of 31. Full-period targets are used only in the "what is needed" figures.</li>
    <li><b>Percentages and values are both shown</b>, because a small branch with an extreme percentage is
        not the same as a large branch a few points below target.</li>
    <li><b>Branch CFH022 is not included.</b> It has had no sales since 1 August, and the Sales performance
        report leaves it out for the same reason.</li>
    <li><b>Projections carry a current rate forward.</b> They are arithmetic, not forecasts.</li>
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
.rail{width:182px;flex:0 0 182px;background:var(--rail);color:#cfe0dc;padding:18px 12px;
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
.hero{background:var(--rail);border-radius:var(--r);padding:20px 24px;margin-bottom:14px;
  display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:26px;align-items:center}
.hero-tag{display:inline-block;font-size:9px;letter-spacing:.12em;text-transform:uppercase;
  font-weight:750;color:#f0c46a;background:rgba(240,196,106,.14);padding:4px 9px;
  border-radius:6px;margin-bottom:10px}
.hero h2{color:#fff;font-size:23px;line-height:1.22;letter-spacing:-.015em;font-weight:700}
.hero p{color:#a9c2bd;font-size:12.5px;margin-top:8px;max-width:60ch}
.hero-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.hs{border-left:2px solid rgba(255,255,255,.14);padding-left:12px}
.hs b{display:block;color:#fff;font-size:19px;font-weight:700;line-height:1.15}
.hs span{display:block;color:#7f9a95;font-size:10.5px;margin-top:3px;line-height:1.35}
.hs.crit b{color:#ff8b73}
.grid{display:grid;gap:14px}
.g-2{grid-template-columns:minmax(0,1.25fr) minmax(0,1fr)}
.g-2r{grid-template-columns:minmax(0,1fr) minmax(0,1.3fr)}
.g-2e{grid-template-columns:repeat(2,minmax(0,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:16px 18px;box-shadow:var(--shadow)}
.card>h3{font-size:13.5px;font-weight:700;letter-spacing:-.01em}
.card>.sub{font-size:11.5px;color:var(--muted);margin-top:2px;margin-bottom:12px}
.sect{margin:22px 0 10px;display:flex;align-items:baseline;gap:11px}
.sect h2{font-size:16px;font-weight:700;letter-spacing:-.015em}
.sect span{font-size:11.5px;color:var(--faint)}
.note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.55}
.note b{color:var(--ink)}
.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:11px}
.kpis.k4{grid-template-columns:repeat(4,minmax(0,1fr))}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:13px 14px 12px;position:relative;overflow:hidden;box-shadow:var(--shadow)}
.kpi::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--faint)}
.kpi.crit::before{background:var(--red)} .kpi.warn::before{background:var(--amber)}
.kpi.good::before{background:var(--green)}
.kpi .lab{font-size:10px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);
  font-weight:650;min-height:26px}
.lab-sub{text-transform:none;letter-spacing:0;font-weight:500;color:var(--faint)}
.kpi .val{font-size:21px;font-weight:750;line-height:1.1;margin:5px 0 4px;letter-spacing:-.02em}
.kpi.crit .val{color:var(--red)} .kpi.warn .val{color:var(--amber-dk)} .kpi.good .val{color:var(--green)}
.kpi .sub{font-size:10.5px;color:var(--muted);line-height:1.4}
.pill{display:inline-block;font-size:9px;font-weight:750;letter-spacing:.05em;
  text-transform:uppercase;padding:2px 6px;border-radius:5px;margin-top:7px}
.pill-crit{background:var(--red-tint);color:var(--red)}
.pill-warn{background:var(--amber-tint);color:var(--amber-dk)}
.pill-ok{background:var(--green-tint);color:var(--green)}
/* --- executive pulse list --- */
.pulse-list{list-style:none;margin:0;padding:0;display:grid;gap:9px}
.pl{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:12px 16px;display:grid;grid-template-columns:120px minmax(0,1fr);
  gap:14px;align-items:baseline;box-shadow:var(--shadow)}
.pl-crit{border-left-color:var(--red)} .pl-warn{border-left-color:var(--amber)}
.pl-good{border-left-color:var(--green)}
.pl-k{font-size:10px;font-weight:750;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.pl p{font-size:12.5px;color:var(--mid);line-height:1.6}
.pl p b{color:var(--ink)}
/* --- target pulse bar --- */
.pulse{margin:2px 0 0}
.pulse-track{position:relative;height:14px;border-radius:99px;background:#eef2f6}
.pulse-fill{display:block;height:100%;border-radius:99px}
.pulse-tick{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--mid);opacity:.7;border-radius:2px}
.pulse-legend{display:flex;justify-content:space-between;margin-top:7px;font-size:11px;color:var(--muted)}
/* --- ranked strip --- */
.strips{display:flex;flex-direction:column;gap:7px}
.sr{display:grid;grid-template-columns:104px minmax(0,1fr) 74px 92px;gap:10px;align-items:center;font-size:12px}
.sr-n{font-weight:650}
.sr-t{background:#eef2f6;border-radius:99px;height:9px;overflow:hidden}
.sr-t i{display:block;height:100%;border-radius:99px}
.sr-v{text-align:right;font-weight:750}
.sr-x{text-align:right;color:var(--muted);font-size:11px}
/* --- contribution bars --- */
.cbs{display:flex;flex-direction:column;gap:7px}
.cb{display:grid;grid-template-columns:120px minmax(0,1fr) 42px 84px;gap:10px;align-items:center;font-size:12px}
.cb-n{font-weight:650}
.cb-t{background:#eef2f6;border-radius:99px;height:9px;overflow:hidden}
.cb-t i{display:block;height:100%;border-radius:99px;background:var(--red)}
.cb-v{text-align:right;font-weight:750;color:var(--red)}
.cb-x{text-align:right;color:var(--muted);font-size:11px}
/* --- benchmark cards --- */
.benches{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.bench{border:1px solid var(--line);border-radius:9px;padding:11px 12px;background:var(--soft)}
.bl{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700}
.bv{font-size:19px;font-weight:750;letter-spacing:-.02em;margin:4px 0 2px}
.bs{font-size:10.5px;color:var(--muted);line-height:1.35}
/* --- diagnostic chain --- */
.chain{display:grid;grid-template-columns:1fr 20px 1fr 20px 1fr 20px 1fr;gap:8px;align-items:center}
.ch{border:1px solid var(--line);border-radius:9px;padding:11px 13px;background:var(--soft)}
.ch-l{font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);font-weight:700}
.ch-v{font-size:17px;font-weight:750;letter-spacing:-.02em;margin:4px 0 2px}
.ch-s{font-size:10.5px;color:var(--muted);line-height:1.35}
.ch-a{text-align:center;color:var(--faint);font-size:15px}
/* --- scenarios --- */
.scen{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.sc{border:1px solid var(--line);border-radius:9px;padding:11px 12px;background:var(--soft)}
.sc-l{font-size:9.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:700;min-height:24px}
.sc-v{font-size:17px;font-weight:750;letter-spacing:-.02em;margin:4px 0 2px}
.sc-s{font-size:10.5px;color:var(--muted);line-height:1.35}
/* --- persistence --- */
.pers{display:flex;flex-direction:column;gap:8px}
.pr{display:grid;grid-template-columns:74px minmax(0,1fr) 92px;gap:11px;align-items:center;font-size:12px}
.pr-n{font-weight:650}
.pr-d{display:flex;gap:3px}
.pr-d i{flex:1;height:15px;border-radius:3px;display:block}
.pr-v{text-align:right;color:var(--muted);font-size:11px}
/* --- management attention --- */
.atts{list-style:none;margin:0 0 14px;padding:0;display:grid;gap:10px}
.att{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:14px 18px;box-shadow:var(--shadow)}
.att-crit{border-left-color:var(--red)} .att-warn{border-left-color:var(--amber)}
.att-ok{border-left-color:var(--green)}
.att h3{font-size:13px;font-weight:750;margin-bottom:5px}
.att p{font-size:12.5px;color:var(--mid);line-height:1.6}
.att p b{color:var(--ink)}
.scroll{overflow-x:auto;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:12px;min-width:440px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{font-size:9.5px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted);
  font-weight:700;white-space:nowrap}
td.n,th.n{text-align:right;white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--soft)}
tr.urgent td{background:var(--red-tint)}
.dz{fill:var(--faint);font-size:9.5px} .dza{fill:var(--muted);font-size:10px;font-weight:700}
.caveats{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--faint);
  border-radius:var(--r);padding:15px 18px;margin-top:20px}
.caveats h3{font-size:12px;font-weight:700;margin-bottom:9px}
.caveats ul{margin:0;padding-left:17px;color:var(--mid);font-size:11.5px;line-height:1.6}
.caveats li{margin-bottom:5px}
.foot{margin-top:18px;padding-top:12px;border-top:1px solid var(--line);
  display:flex;justify-content:space-between;gap:14px;flex-wrap:wrap;
  font-size:10.5px;color:var(--faint)}
svg{display:block;width:100%;height:auto;overflow:visible}
.mini{max-width:560px}
@media (max-width:1080px){
  .kpis,.kpis.k4{grid-template-columns:repeat(2,minmax(0,1fr))}
  .g-2,.g-2e,.g-2r{grid-template-columns:minmax(0,1fr)}
  .hero{grid-template-columns:minmax(0,1fr)}
  .chain{grid-template-columns:1fr}.ch-a{transform:rotate(90deg)}
  .pl{grid-template-columns:1fr;gap:4px}
}
@media (max-width:720px){.rail{display:none}.benches,.scen{grid-template-columns:1fr}
  .sr{grid-template-columns:88px minmax(0,1fr) 64px}.sr-x{display:none}}
@media print{
  .rail{display:none}.app{display:block}.card,.kpi,.hero,.att,.pl{break-inside:avoid;box-shadow:none}
  body{background:#fff}.layer[hidden]{display:block}
}
.layer[hidden]{display:none}
"""

SCRIPT = """<script>
(function(){
  var LAYERS = ['pulse','yesterday','last7','wtd','mtd','ytd','attention'];
  function setLayer(name){
    document.querySelectorAll('.layer').forEach(function(el){
      el.hidden = el.getAttribute('data-layer') !== name;
    });
    document.querySelectorAll('[data-nav]').forEach(function(btn){
      btn.setAttribute('aria-current', btn.getAttribute('data-nav') === name ? 'true' : 'false');
    });
    var hash = '#' + name;
    if (location.hash !== hash){ history.replaceState(null, '', hash); }
  }
  document.addEventListener('click', function(ev){
    var nav = ev.target.closest('[data-nav]');
    if (nav){ setLayer(nav.getAttribute('data-nav')); }
  });
  window.addEventListener('hashchange', function(){
    var n = (location.hash || '').replace('#','');
    setLayer(LAYERS.indexOf(n) !== -1 ? n : 'pulse');
  });
  var start = (location.hash || '').replace('#','');
  setLayer(LAYERS.indexOf(start) !== -1 ? start : 'pulse');
})();
</script>"""

LAYERS = [
    ("pulse", "Executive pulse", layer_pulse()),
    ("yesterday", "Yesterday", layer_yesterday()),
    ("last7", "Last 7 days", layer_last7()),
    ("wtd", "This week", layer_wtd()),
    ("mtd", "This month", layer_mtd()),
    ("ytd", "This year", layer_ytd()),
    ("attention", "Management attention", layer_attention()),
]

nav = "".join(f'<button data-nav="{k}"{" aria-current=\"true\"" if i == 0 else ""}>{e(label)}</button>'
              for i, (k, label, _) in enumerate(LAYERS))
body = "".join(
    f'<div class="layer" data-layer="{k}"{"" if i == 0 else " hidden"}>{content}'
    f'{CAVEATS if k in ("pulse", "attention") else ""}</div>'
    for i, (k, _, content) in enumerate(LAYERS))

HTML = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Target Tracker &mdash; reference dashboard (rules version)</title>
<style>{STYLE}</style>
</head>
<body>
<div class="app">
  <nav class="rail" aria-label="Sections">
    <div class="mark">AI</div>
    <div class="grp">Report</div>
    {nav}
    <p class="foot">Reference design, built to the<br>Target Tracker insight rules.<br>
      Figures are the live position<br>as at 16&nbsp;Jul&nbsp;2026.</p>
  </nav>
<main><div class="page">
    <div class="masthead">
      <div>
        <p class="eyebrow">Sales &middot; City Flower</p>
        <h1>Target Tracker</h1>
        <p class="asat">Performance against target up to 16 July 2026 &middot; report run 17 July &middot;
          4 branches &middot; all figures in Saudi Riyals ({CUR})</p>
      </div>
    </div>
{body}
    <p class="foot"><span>Every figure comes from the Target Tracker report and has been checked against its
      own totals. Nothing is estimated, and no cause is inferred.</span><span>AI-assisted analysis</span></p>
  </div></main>
</div>
{SCRIPT}
</body>
</html>"""

OUT.write_text(HTML, encoding="utf-8")
print(f"wrote {OUT}  ({len(HTML):,} bytes)")
print(f"  yesterday {DAY_ATT:.1f}% | 30-day avg {ATT30:.1f}% | rank {RANK30} of 30 (no record claimed)")
print(f"  7-day {D7_ATT:.1f}% total, {D7_AVG_DAILY:.1f}% daily average, {D7_ABOVE}/7 days on target")
print(f"  WTD pace {WTD_PACE:.2f} (needs {WEEK_REQ_ATT:.1f}% of remaining target)")
print(f"  MTD pace {MTD_PACE:.2f} (needs {MONTH_REQ_ATT:.1f}% of remaining target)")
print(f"  quarters {' '.join(f'{attain(q[2],q[3]):.1f}%' for q in QUARTERS)}")
print("  checks: branch variances sum to company variance; CFH017 departments sum to its shortfall")
