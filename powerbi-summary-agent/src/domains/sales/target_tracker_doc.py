"""Target Tracker - the business document.

The same story as the page, written as prose for someone reading without the dashboard in
front of them. Mirrors how the Sales YoY report produces `report_summary.md`: a headline as
`#`, a context line in italics, then `##` sections in the reading order the rulebook fixes.

Deterministic and grounded - every figure is copied from the model or derived from it here.
Rulebook section 5 governs the language and section 9 the omissions: no prior-year
comparison, no invented cause, no forecast.
"""

from __future__ import annotations

import datetime as _dt

from .target_tracker import fmt_date
from .target_tracker_html import _share_words, money, name_list, pc, plural, verb


def _m(cur: str, value) -> str:
    return f"{cur} {money(value)}"


def _direction(value: float) -> str:
    return "above" if value >= 0 else "below"


def _period_line(cur: str, p: dict) -> str:
    return (f"- **{p['name']}** ({p['elapsed']}): {_m(cur, p['actual'])} against a target of "
            f"{_m(cur, p['target'])} — **{pc(p['attainment'])}** of target, "
            f"{_m(cur, abs(p['variance']))} {_direction(p['variance'])} target.")


def render(model: dict, *, currency: str = "SAR") -> str:
    cur = currency
    anchor = _dt.date.fromisoformat(model["anchor"])
    day, wtd = model["periods"]["day"], model["periods"]["wtd"]
    mtd, ytd = model["periods"]["mtd"], model["periods"]["ytd"]
    run, surplus = model["run"], model["surplus"]
    month_done = model["days_elapsed"] >= model["days_in_month"]
    days_left = model["days_in_month"] - model["days_elapsed"]

    from .target_tracker_html import headline as _headline
    from .target_tracker_html import _R

    prose = model.get("prose") or {}
    lines: list[str] = []
    lines.append(f"# {prose.get('headline') or _headline(_R(cur), model)}")
    lines.append("")
    context = [f"Target Tracker · data to {fmt_date(anchor, 'medium')} {anchor.year}",
               mtd["elapsed"], f"{len(model['population'])} branches", f"all figures in {cur}"]
    lines.append(f"*{' · '.join(context)}*")
    lines.append("")

    if model["target_lag_days"]:
        sold = _dt.date.fromisoformat(model["sold_through"])
        lines.append(
            f"> **Why this date.** {fmt_date(anchor, 'medium')} "
            + ("is the date this run was asked to report on."
               if model.get("anchor_forced")
               else "is the most recent day that has a sales target.")
            + f" Sales have been recorded for a further {model['target_lag_days']} days, "
            f"up to {fmt_date(sold, 'medium')}, but no target has been set for them, so they cannot "
            f"be measured against one.")
        lines.append("")

    # --- where we stand ---------------------------------------------------
    if prose.get("narrative"):
        lines.append(prose["narrative"])
        lines.append("")
    lines.append("## Where we stand")
    lines.append("")
    lines.append("Each period is compared with the target for the days that have already passed, "
                 "not with the target for the whole period. That is what makes these four figures "
                 "comparable with each other.")
    lines.append("")
    for key in ("day", "wtd", "mtd", "ytd"):
        lines.append(_period_line(cur, model["periods"][key]))
    lines.append("")

    # --- today -------------------------------------------------------------
    lines.append(f"## Today — {fmt_date(anchor, 'long')}")
    lines.append("")
    day_branches = sorted(model["branches"], key=lambda b: b["day"]["variance"])
    missed = [b for b in day_branches if b["day"]["variance"] < 0]
    beat = [b for b in day_branches if b["day"]["variance"] >= 0]
    para = (f"The business reached {pc(day['attainment'])} of its target for the day, selling "
            f"{_m(cur, day['actual'])} against {_m(cur, day['target'])} — "
            f"{_m(cur, abs(day['variance']))} {_direction(day['variance'])} target.")
    if run["length"] >= 2:
        para += f" It is the {run['length']}th day below target in a row."
    lines.append(para)
    lines.append("")
    if missed:
        worst = missed[0]
        share = abs(worst["day"]["variance"]) / sum(abs(b["day"]["variance"]) for b in missed) * 100
        detail = (f"{len(missed)} of the {len(model['branches'])} branches missed "
                  f"{'its' if len(missed) == 1 else 'their'} target. "
                  f"{worst['name']} was furthest short at {_m(cur, abs(worst['day']['variance']))}, "
                  f"which is {share:.0f}% of the shortfall across the branches that missed.")
        if abs(worst["day"]["variance"]) > abs(day["variance"]) and day["variance"] < 0:
            detail += (f" That is more than the whole company's shortfall of "
                       f"{_m(cur, abs(day['variance']))} — without {worst['name']} the day would "
                       f"have finished above target.")
        if beat:
            detail += f" {name_list([b['name'] for b in beat])} beat target."
        lines.append(detail)
        lines.append("")
    else:
        lines.append("Every branch reached its target today.")
        lines.append("")

    # --- this week ----------------------------------------------------------
    lines.append("## This week")
    lines.append("")
    wtd_behind = [b for b in model["branches"] if b["wtd"]["variance"] < 0]
    lines.append(
        f"The week is at {pc(wtd['attainment'])} of target after {wtd['elapsed']}, "
        f"{_m(cur, abs(wtd['variance']))} {_direction(wtd['variance'])} the target for those days. "
        + (f"All {len(model['branches'])} branches are below target for the week, which makes this "
           f"a broad slowdown rather than one branch's problem."
           if len(wtd_behind) == len(model["branches"]) else
           f"{len(wtd_behind)} of the {len(model['branches'])} branches "
           f"{verb(len(wtd_behind))} below target for the week."
           if wtd_behind else "Every branch is at or above target for the week."))
    lines.append("")
    week_close = model["week_close"]
    if week_close["needed_vs_target"] is not None and week_close["remaining_target"] > 0:
        rate = week_close["needed_vs_target"]
        lines.append(
            f"To finish the week on target, the days that are left must sell "
            f"{_m(cur, week_close['needed'])} — {pc(rate)} of what they are already targeted to "
            f"sell ({_m(cur, week_close['remaining_target'])}). "
            + ("They therefore need to beat their own plan." if rate > 100 else
               f"They can sell {pc(100 - rate)} below their own plan and the week still lands on target."))
    else:
        parts = wtd["elapsed"].split(" days of ")
        truncated = len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()             and int(parts[0]) < int(parts[1])
        if truncated:
            lines.append(f"The remaining days of the week carry no target, so the week cannot be "
                         f"tracked any further. Measured over the {parts[0]} days that do carry one, "
                         f"it is {_m(cur, abs(wtd['variance']))} {_direction(wtd['variance'])} target.")
        else:
            lines.append(f"The week is complete. It finished at {pc(wtd['attainment'])} of target, "
                         f"{_m(cur, abs(wtd['variance']))} {_direction(wtd['variance'])} plan.")
    prev = model["prev_week"]
    if prev["attainment"]:
        lines.append("")
        lines.append(f"The previous complete week finished at {pc(prev['attainment'])} of target, "
                     f"{_m(cur, abs(prev['variance']))} {_direction(prev['variance'])} it.")
    lines.append("")

    # --- this month ---------------------------------------------------------
    lines.append("## This month")
    lines.append("")
    lines.append(f"{model['days_hit']} of the {model['days_elapsed']} days so far reached their own "
                 f"target. The month stands at {pc(mtd['attainment'])}, "
                 f"{_m(cur, abs(mtd['variance']))} {_direction(mtd['variance'])} the target for the "
                 f"days that have passed.")
    lines.append("")
    if run["length"] and surplus["built"] > 0:
        para = (f"The month splits in two. The first {surplus['earlier_days']} days built a surplus "
                f"of {_m(cur, surplus['built'])}. The last {run['length']} days have all been below "
                f"target and have used up {_m(cur, surplus['given_back'])} of it — "
                f"{_share_words(surplus['share_given_back'])} of everything the month had banked.")
        if surplus["exhausts_on"]:
            para += (f" At the recent average shortfall of {_m(cur, run['average_shortfall'])} a "
                     f"day, the remaining {_m(cur, surplus['now'])} would be used up around "
                     f"**{fmt_date(_dt.date.fromisoformat(surplus['exhausts_on']), 'medium')}**.")
        lines.append(para)
        lines.append("")
    month_close = model["month_close"]
    if month_close["needed_vs_target"] is not None and month_close["remaining_target"] > 0:
        rate = month_close["needed_vs_target"]
        proj = model["projections"]
        lines.append(
            f"With {days_left} days left, reaching the month target needs "
            f"{_m(cur, month_close['needed'])} — {pc(rate)} of what those days are already targeted "
            f"to sell. " + ("They must beat their own plan." if rate > 100 else
                            f"They can sell {pc(100 - rate)} below their own plan and the month "
                            f"still lands on target."))
        if proj["at_month_rate"] and proj["at_recent_rate"]:
            lines.append("")
            lines.append(
                f"Carrying the month's own rate forward would finish July at about "
                f"{_m(cur, proj['at_month_rate'])} ({pc(proj['at_month_rate_pct'])} of target). "
                f"Carrying the recent rate forward instead would finish at about "
                f"{_m(cur, proj['at_recent_rate'])} ({pc(proj['at_recent_rate_pct'])}). "
                f"Both are arithmetic that continues a stated rate, not forecasts.")
    else:
        lines.append(f"The month is complete. It finished at {pc(mtd['attainment'])} of target, "
                     f"{_m(cur, abs(mtd['variance']))} {_direction(mtd['variance'])} plan. "
                     f"Nothing here can still be changed.")
    lines.append("")

    # --- branches -----------------------------------------------------------
    lines.append("## Branch performance")
    lines.append("")
    lines.append("| Branch | Today | This week | This month | This year | Above/below target |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for b in model["branches"]:
        lines.append(
            f"| {b['name']} | {pc(b['day']['attainment'])} | {pc(b['wtd']['attainment'])} | "
            f"{pc(b['mtd']['attainment'])} | {pc(b['ytd']['attainment'])} | "
            f"{_m(cur, abs(b['mtd']['variance']))} {_direction(b['mtd']['variance'])} |")
    lines.append("")
    behind_month = [b for b in model["branches"] if b["mtd"]["band"] == "crit"]
    if behind_month:
        for b in behind_month:
            close = b["close"]
            extra = ""
            if close["needed_vs_target"] is not None and close["remaining_target"] > 0:
                extra = (f" It needs {_m(cur, close['needed'])} from the days that are left, which is "
                         f"{pc(close['needed_vs_target'])} of what those days are targeted to sell.")
            lines.append(f"**{b['name']}** is below target for the month at "
                         f"{pc(b['mtd']['attainment'])}, {_m(cur, abs(b['mtd']['variance']))} short."
                         f"{extra}")
        lines.append("")
    else:
        lines.append("Every branch is at or above target for the month.")
        lines.append("")

    # --- departments --------------------------------------------------------
    lines.append("## Departments and sections")
    lines.append("")
    depts = sorted(model["departments"], key=lambda d: d["mtd"]["variance"])
    below = [d for d in depts if d["mtd"]["variance"] < 0]
    above = [d for d in depts if d["mtd"]["variance"] >= 0]
    if below:
        worst = below[0]
        lines.append(
            f"{len(below)} of the {len(depts)} departments {verb(len(below))} below target "
            f"for the month. "
            f"The largest shortfall is {worst['name']} at {_m(cur, abs(worst['mtd']['variance']))} "
            f"({pc(worst['mtd']['attainment'])} of target).")
    else:
        lines.append(f"All {len(depts)} departments are at or above target for the month.")
    if above:
        best = above[-1]
        lines.append("")
        lines.append(f"The largest surplus is {best['name']} at "
                     f"{_m(cur, best['mtd']['variance'])} above target "
                     f"({pc(best['mtd']['attainment'])}).")
    sections = sorted(model["sections"], key=lambda s: s["mtd"]["variance"])
    if sections:
        lines.append("")
        lines.append("Sections furthest from their month target:")
        lines.append("")
        for s in sections[:4]:
            lines.append(f"- **{s['name']}** ({s.get('department')}): "
                         f"{pc(s['mtd']['attainment'])} of target, "
                         f"{_m(cur, abs(s['mtd']['variance']))} short.")
        for s in reversed(sections[-3:]):
            lines.append(f"- **{s['name']}** ({s.get('department')}): "
                         f"{pc(s['mtd']['attainment'])} of target, "
                         f"{_m(cur, s['mtd']['variance'])} above.")
    lines.append("")

    # --- the year -----------------------------------------------------------
    lines.append("## The year so far")
    lines.append("")
    hit_months = sum(1 for m in model["months"] if (m["attainment"] or 0) >= 100)
    lines.append(f"The year stands at {pc(ytd['attainment'])} of target, "
                 f"{_m(cur, abs(ytd['variance']))} {_direction(ytd['variance'])} plan. "
                 f"{hit_months} of the {len(model['months'])} months so far reached their target.")
    missed_months = [m for m in model["months"] if (m["attainment"] or 0) < 100]
    if missed_months:
        lines.append("")
        lines.append("Months below target: "
                     + ", ".join(f"{m['name']} ({pc(m['attainment'])})" for m in missed_months) + ".")
    lines.append("")

    # --- what this does not say ----------------------------------------------
    lines.append("## Important things to know about these numbers")
    lines.append("")
    notes = [
        "There is no comparison with last year. The report only holds 2026 data, so every figure "
        "here is compared with target.",
        "No causes are given, only amounts and places. The report holds sales and targets — not "
        "promotions, stock, staffing or footfall — so nothing here explains why sales moved.",
        "Each period is compared with the target for the days that have passed. Full-period targets "
        "are used only in the catch-up figures, which say so.",
        "Projections continue a stated rate. They are arithmetic, not forecasts.",
    ]
    if "CFH022" not in model["population"]:
        notes.append("Branch CFH022 is not included, matching how the Sales performance report "
                     "treats it.")
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)
