"""Target Tracker - the scan and the report model.

Deterministic. The scan issues a bounded set of DAX queries; `build` turns the returned
rows into the page model with no LLM and no IO. Prose slots are filled with grounded
sentences built from the figures themselves, and an LLM may later replace those slots
only (rulebook section 4).

Governed by `config/targettracker/summary_business_rules.md`. Three of its rules are
load-bearing here and are enforced in code rather than left to a prompt:

* **The anchor is the latest date that carries a target**, not the latest date that
  carries sales (section 3). On the live model sales run to 17 August while targets stop
  at 31 July, so reading `MAX(TY_DATE)` would produce a page of blank comparisons.
* **Scope targets are summed from `ACTUAL_SALES_TARGET` over a date range** (section 9).
  The model's own `MTD_TARGET` and `WTD_TARGET` measures both filter `MTD_CHECK = "Y"`,
  which is true on all 44,127 rows, so both return the full year target.
* **Every percentage is measured against the target for the days that have elapsed**
  (section 3.1), never the whole period's target. Whole-period targets are used only in
  the catch-up arithmetic.

No prior-year figure is computed anywhere: the model holds 2026 only and its
`LY_SALES` / `LY_SAME_DAY_SALES` columns do not exist, so every prior-year measure in it
fails at query time.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Callable, Sequence

FACT = "REP_DEPT_WISE_PERF_EVAL_RPT"

#: Rulebook section 6.
BANDS = ((100.0, "good", "On target"), (95.0, "warn", "Watch"), (0.0, "crit", "Below target"))


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _cell(row: dict, *names: str) -> Any:
    """Read a column whatever the executor named it."""
    for name in names:
        for key, value in (row or {}).items():
            cleaned = str(key).strip("[]").split("[")[-1].strip("]").lower()
            if cleaned == name.lower():
                return value
    return None


def _f(row: dict, *names: str) -> float:
    return _num(_cell(row, *names)) or 0.0


def _date(value: Any) -> _dt.date | None:
    text = str(value or "").split("T")[0]
    try:
        return _dt.date.fromisoformat(text)
    except ValueError:
        return None


def attainment(actual: float, target: float) -> float | None:
    """Percent of target. `None` when there is no target to measure against -
    rulebook section 10 forbids showing a zero or a blank comparison instead."""
    return (actual / target * 100.0) if target else None


def band(actual: float, target: float) -> tuple[str, str]:
    value = attainment(actual, target)
    if value is None:
        return "none", "No target set"
    for floor, key, word in BANDS:
        if value >= floor:
            return key, word
    return "crit", "Below target"


def fmt_date(day: _dt.date, style: str = "long") -> str:
    """Portable date formatting. `strftime("%-d")` is glibc-only and `%#d` is Windows-only,
    so the day number is inserted rather than formatted."""
    if style == "long":                       # Thursday 16 July 2026
        return f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"
    if style == "medium":                     # 16 July
        return f"{day.day} {day.strftime('%B')}"
    if style == "short":                      # Thu 16 Jul
        return f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"
    if style == "daymon":                     # 16 Jul
        return f"{day.day} {day.strftime('%b')}"
    return day.isoformat()


def _pop_filter(population: Sequence[str]) -> str:
    members = ",".join(f'"{str(code).strip()}"' for code in population if str(code).strip())
    return f"TREATAS({{{members}}}, '{FACT}'[LOC_CODE])" if members else "TRUE()"


def _dax_date(value: _dt.date) -> str:
    return f"DATE({value.year},{value.month},{value.day})"


def week_start(day: _dt.date) -> _dt.date:
    """Monday of the week containing `day` (rulebook section 3)."""
    return day - _dt.timedelta(days=day.weekday())


def month_bounds(day: _dt.date) -> tuple[_dt.date, _dt.date]:
    first = day.replace(day=1)
    if day.month == 12:
        last = day.replace(day=31)
    else:
        last = day.replace(month=day.month + 1, day=1) - _dt.timedelta(days=1)
    return first, last


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------
def _run(execute: Callable[[str], list[dict]], label: str, dax: str, log) -> list[dict]:
    rows = execute(dax)
    if log:
        log(f"  {label}: {len(rows)} row(s)")
    return rows


def resolve_anchor(execute: Callable[[str], list[dict]], population: Sequence[str],
                   override: str = "") -> tuple[_dt.date, _dt.date | None, _dt.date, bool]:
    """The date to report on, the latest sales date, the latest target date, and whether forced.

    The anchor is the latest date where BOTH a target and sales exist - in practice
    `min(latest_target, latest_sales)`, because each feed is contiguous up to its own
    watermark.

    This used to be the latest date carrying a TARGET alone, written for a model whose
    sales ran ahead of its targets (sales to 17 August, targets stopping at 31 July);
    anchoring on sales there produced a page of blank comparisons. SB Mart is the exact
    reverse - targets are loaded to month end while sales lag a few days - and the same
    rule then counted five unsold future days as elapsed. The live page reported
    "31 days of 31", "the month is complete", a run of 25 days below target, and a
    today of USD 0 against a full target, on 27 August. The year read 99.4% and
    "below target" when the elapsed truth was 101.5% and above it: a direction, not
    just a magnitude.

    `min` is right rather than "the latest day carrying both" because this is about each
    feed's WATERMARK, not per-day presence. A genuinely closed day with no sales, sitting
    before the watermark, is still an elapsed day the business missed its target on, and
    must keep counting; testing per-day presence would silently skip past it.

    Both dates are returned because when they differ the page has to say so - in either
    direction - and a caller that only knew the anchor could not.
    """
    pop = _pop_filter(population)
    rows = execute(f"""EVALUATE CALCULATETABLE(ROW(
      "with_target", CALCULATE(MAX('{FACT}'[TY_DATE]), '{FACT}'[ACTUAL_SALES_TARGET] > 0),
      "with_sales",  CALCULATE(MAX('{FACT}'[TY_DATE]), '{FACT}'[TY_SALES] <> 0)
    ), {pop})""")
    row = rows[0] if rows else {}
    targeted = _date(_cell(row, "with_target"))
    sold = _date(_cell(row, "with_sales"))
    if targeted is None:
        raise RuntimeError("no date in the Target Tracker model carries a sales target")
    # The reportable date is where both feeds reach. `sold` may be absent on a model
    # that carries targets and no sales at all, and there the target date is all there is.
    resolved = min(targeted, sold) if sold else targeted
    forced = _date(override) if override else None
    anchor = forced or resolved
    return anchor, sold, targeted, (forced is not None and forced != resolved)


def scan(execute: Callable[[str], list[dict]], population: Sequence[str],
         *, anchor_override: str = "", log=None) -> dict:
    """Every row the report needs. Bounded: nine queries, none unfiltered."""
    pop = _pop_filter(population)
    anchor, sold_through, targeted_through, forced = resolve_anchor(
        execute, population, anchor_override)
    wk_start = week_start(anchor)
    mo_start, mo_end = month_bounds(anchor)
    yr_start = anchor.replace(month=1, day=1)
    A, W, M, Y = (_dax_date(anchor), _dax_date(wk_start), _dax_date(mo_start), _dax_date(yr_start))
    ME = _dax_date(mo_end)
    WE = _dax_date(wk_start + _dt.timedelta(days=6))
    if log:
        how = ("forced by configuration" if forced
               else "latest date carrying both a target and sales")
        log(f"Anchor {anchor} ({how}); targets run to {targeted_through}, "
            f"sales run to {sold_through}")

    def scoped(extra: str = "") -> str:
        return f"{pop}{(', ' + extra) if extra else ''}"

    out: dict[str, Any] = {
        "anchor": anchor.isoformat(),
        "targeted_through": targeted_through.isoformat(),
        "sold_through": sold_through.isoformat() if sold_through else None,
        "anchor_forced": forced,
        "week_start": wk_start.isoformat(),
        "month_start": mo_start.isoformat(),
        "month_end": mo_end.isoformat(),
        "population": list(population),
    }

    out["totals"] = _run(execute, "period totals", f"""EVALUATE CALCULATETABLE(ROW(
      "day_sales",    CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]={A}),
      "day_target",   CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]={A}),
      "wtd_sales",    CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={W}, '{FACT}'[TY_DATE]<={A}),
      "wtd_target",   CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={W}, '{FACT}'[TY_DATE]<={A}),
      "week_full_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={W}, '{FACT}'[TY_DATE]<={WE}),
      "mtd_sales",    CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A}),
      "mtd_target",   CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A}),
      "month_full_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={ME}),
      "ytd_sales",    CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={Y}, '{FACT}'[TY_DATE]<={A}),
      "ytd_target",   CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={Y}, '{FACT}'[TY_DATE]<={A}),
      "prev_week_sales",  CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={_dax_date(wk_start - _dt.timedelta(days=7))}, '{FACT}'[TY_DATE]<={_dax_date(wk_start - _dt.timedelta(days=1))}),
      "prev_week_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={_dax_date(wk_start - _dt.timedelta(days=7))}, '{FACT}'[TY_DATE]<={_dax_date(wk_start - _dt.timedelta(days=1))})
    ), {pop})""", log)

    out["days"] = _run(execute, "day series", f"""EVALUATE CALCULATETABLE(
      SUMMARIZECOLUMNS('{FACT}'[TY_DATE],'{FACT}'[DAY_OF_WEEK],'{FACT}'[DOC_DAY],
        "sales", SUM('{FACT}'[TY_SALES]), "target", SUM('{FACT}'[ACTUAL_SALES_TARGET])),
      {scoped(f"'{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A}")})
    ORDER BY '{FACT}'[TY_DATE]""", log)

    out["remaining_week_days"] = _run(execute, "days left this week", f"""EVALUATE CALCULATETABLE(
      SUMMARIZECOLUMNS('{FACT}'[TY_DATE],'{FACT}'[DAY_OF_WEEK],
        "target", SUM('{FACT}'[ACTUAL_SALES_TARGET])),
      {scoped(f"'{FACT}'[TY_DATE]>{A}, '{FACT}'[TY_DATE]<={WE}")})
    ORDER BY '{FACT}'[TY_DATE]""", log)

    out["weeks"] = _run(execute, "weeks", f"""EVALUATE CALCULATETABLE(
      SUMMARIZECOLUMNS('{FACT}'[week number],
        "sales", SUM('{FACT}'[TY_SALES]), "target", SUM('{FACT}'[ACTUAL_SALES_TARGET]),
        "first_day", MIN('{FACT}'[TY_DATE]), "last_day", MAX('{FACT}'[TY_DATE]),
        "days", DISTINCTCOUNT('{FACT}'[TY_DATE])),
      {scoped(f"'{FACT}'[TY_DATE]<={A}")})
    ORDER BY '{FACT}'[week number]""", log)

    out["months"] = _run(execute, "months", f"""EVALUATE CALCULATETABLE(
      SUMMARIZECOLUMNS('{FACT}'[DOC_MONTH],'{FACT}'[MONTH_NAME],
        "sales", SUM('{FACT}'[TY_SALES]), "target", SUM('{FACT}'[ACTUAL_SALES_TARGET])),
      {scoped(f"'{FACT}'[TY_DATE]<={A}")})
    ORDER BY '{FACT}'[DOC_MONTH]""", log)

    out["branches"] = _run(execute, "branches", f"""EVALUATE CALCULATETABLE(
      SUMMARIZECOLUMNS('{FACT}'[LOC_CODE],
        "day_sales",   CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]={A}),
        "day_target",  CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]={A}),
        "wtd_sales",   CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={W}, '{FACT}'[TY_DATE]<={A}),
        "wtd_target",  CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={W}, '{FACT}'[TY_DATE]<={A}),
        "mtd_sales",   CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A}),
        "mtd_target",  CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A}),
        "ytd_sales",   CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={Y}, '{FACT}'[TY_DATE]<={A}),
        "ytd_target",  CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={Y}, '{FACT}'[TY_DATE]<={A}),
        "month_full_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={ME})),
      {pop})""", log)

    out["departments"] = _run(execute, "departments", f"""EVALUATE CALCULATETABLE(
      SUMMARIZECOLUMNS('{FACT}'[DEPARTMENT],
        "day_sales",  CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]={A}),
        "day_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]={A}),
        "wtd_sales",  CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={W}, '{FACT}'[TY_DATE]<={A}),
        "wtd_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={W}, '{FACT}'[TY_DATE]<={A}),
        "mtd_sales",  CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A}),
        "mtd_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A})),
      {pop})""", log)

    out["sections"] = _run(execute, "sections", f"""EVALUATE CALCULATETABLE(
      SUMMARIZECOLUMNS('{FACT}'[SECTION],'{FACT}'[DEPARTMENT],
        "mtd_sales",  CALCULATE(SUM('{FACT}'[TY_SALES]),            '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A}),
        "mtd_target", CALCULATE(SUM('{FACT}'[ACTUAL_SALES_TARGET]), '{FACT}'[TY_DATE]>={M}, '{FACT}'[TY_DATE]<={A})),
      {pop})""", log)

    return out


# ---------------------------------------------------------------------------
# model
# ---------------------------------------------------------------------------
def _period(actual: float, target: float, name: str, when: str, elapsed: str) -> dict:
    key, word = band(actual, target)
    return {
        "name": name, "when": when, "elapsed": elapsed,
        "actual": actual, "target": target,
        "variance": actual - target,
        "attainment": attainment(actual, target),
        "band": key, "status": word,
    }


def _entity(row: dict, scopes: Sequence[str], name_field: str) -> dict:
    out = {"name": str(_cell(row, name_field) or "Unassigned")}
    for scope in scopes:
        a, t = _f(row, f"{scope}_sales"), _f(row, f"{scope}_target")
        out[scope] = {"actual": a, "target": t, "variance": a - t,
                      "attainment": attainment(a, t), "band": band(a, t)[0]}
    return out


def build(scanned: dict) -> dict:
    """The whole report model, from one scan. Pure."""
    totals = (scanned.get("totals") or [{}])[0]
    anchor = _date(scanned.get("anchor"))
    sold_through = _date(scanned.get("sold_through"))
    mo_start, mo_end = month_bounds(anchor)
    wk_start = _date(scanned.get("week_start"))

    days = []
    for row in scanned.get("days") or []:
        day = _date(_cell(row, "TY_DATE"))
        if not day:
            continue
        a, t = _f(row, "sales"), _f(row, "target")
        days.append({"date": day.isoformat(), "dow": str(_cell(row, "DAY_OF_WEEK") or ""),
                     "day": int(_f(row, "DOC_DAY")), "actual": a, "target": t,
                     "variance": a - t,
                     "attainment": attainment(a, t), "band": band(a, t)[0]})
    days.sort(key=lambda d: d["date"])

    day_p = _period(_f(totals, "day_sales"), _f(totals, "day_target"),
                    "Today", fmt_date(anchor, "long"), "Full day")
    elapsed_w = sum(1 for d in days if d["date"] >= wk_start.isoformat())
    elapsed_m = len(days)
    days_in_month = (mo_end - mo_start).days + 1
    wtd_p = _period(_f(totals, "wtd_sales"), _f(totals, "wtd_target"), "This week so far",
                    f"{fmt_date(wk_start, 'short')} – {fmt_date(anchor, 'short')}",
                    f"{elapsed_w} days of 7")
    mtd_p = _period(_f(totals, "mtd_sales"), _f(totals, "mtd_target"), "This month so far",
                    f"1 – {fmt_date(anchor, 'medium')}", f"{elapsed_m} days of {days_in_month}")
    ytd_p = _period(_f(totals, "ytd_sales"), _f(totals, "ytd_target"), "This year so far",
                    f"1 January – {fmt_date(anchor, 'medium')} {anchor.year}",
                    f"{(anchor - anchor.replace(month=1, day=1)).days + 1} days elapsed")

    # --- how the month split: what was built, what has been given back -------
    # The split point is the start of the current run of days below target; if there is
    # no run, the month is described whole rather than invented into two halves.
    run = []
    for entry in reversed(days):
        if entry["attainment"] is not None and entry["attainment"] < 100:
            run.append(entry)
        else:
            break
    run.reverse()
    earlier = days[: len(days) - len(run)] if run else days
    built = sum(d["actual"] - d["target"] for d in earlier)
    given_back = -sum(d["actual"] - d["target"] for d in run) if run else 0.0
    surplus = mtd_p["variance"]
    burn = (given_back / len(run)) if run else 0.0
    exhausts_in = (surplus / burn) if (burn > 0 and surplus > 0) else None
    exhaust_date = None
    if exhausts_in is not None and exhausts_in <= (mo_end - anchor).days:
        exhaust_date = (anchor + _dt.timedelta(days=round(exhausts_in))).isoformat()

    week_full_target = _f(totals, "week_full_target")
    month_full_target = _f(totals, "month_full_target")
    remaining_week = [{"dow": str(_cell(r, "DAY_OF_WEEK") or ""),
                       "date": (_date(_cell(r, "TY_DATE")) or anchor).isoformat(),
                       "target": _f(r, "target")}
                      for r in scanned.get("remaining_week_days") or []]
    week_rem_target = sum(r["target"] for r in remaining_week)
    month_rem_target = month_full_target - mtd_p["target"]

    def close(full_target, done_actual, remaining_target):
        needed = full_target - done_actual
        return {"needed": needed, "remaining_target": remaining_target,
                "needed_vs_target": (needed / remaining_target * 100.0) if remaining_target else None}

    branches = [_entity(r, ("day", "wtd", "mtd", "ytd"), "LOC_CODE")
                for r in scanned.get("branches") or []]
    for row, model in zip(scanned.get("branches") or [], branches):
        full = _f(row, "month_full_target")
        model["month_full_target"] = full
        model["close"] = close(full, model["mtd"]["actual"], full - model["mtd"]["target"])
    branches.sort(key=lambda b: (b["mtd"]["attainment"] is None, b["mtd"]["attainment"] or 0))

    departments = [_entity(r, ("day", "wtd", "mtd"), "DEPARTMENT")
                   for r in scanned.get("departments") or []
                   if _f(r, "mtd_target") > 0]
    sections = [_entity(r, ("mtd",), "SECTION") for r in scanned.get("sections") or []
                if _f(r, "mtd_target") > 0]
    for row, model in zip([r for r in scanned.get("sections") or [] if _f(r, "mtd_target") > 0], sections):
        model["department"] = str(_cell(row, "DEPARTMENT") or "")

    weeks = []
    for row in scanned.get("weeks") or []:
        a, t = _f(row, "sales"), _f(row, "target")
        if t <= 0:
            continue
        first, last = _date(_cell(row, "first_day")), _date(_cell(row, "last_day"))
        weeks.append({"number": int(_f(row, "week number")), "actual": a, "target": t,
                      "days": int(_f(row, "days")), "attainment": attainment(a, t),
                      "band": band(a, t)[0],
                      "label": f"{fmt_date(first, 'daymon')}–{fmt_date(last, 'daymon')}"
                      if first and last else ""})
    weeks.sort(key=lambda w: w["number"])

    months = []
    for row in scanned.get("months") or []:
        a, t = _f(row, "sales"), _f(row, "target")
        if t <= 0:
            continue
        months.append({"number": int(_f(row, "DOC_MONTH")),
                       "name": str(_cell(row, "MONTH_NAME") or "").title(),
                       "actual": a, "target": t, "attainment": attainment(a, t),
                       "band": band(a, t)[0],
                       "complete": int(_f(row, "DOC_MONTH")) != anchor.month})
    months.sort(key=lambda m: m["number"])

    prev_week = {"actual": _f(totals, "prev_week_sales"), "target": _f(totals, "prev_week_target")}
    prev_week["attainment"] = attainment(prev_week["actual"], prev_week["target"])
    prev_week["variance"] = prev_week["actual"] - prev_week["target"]

    model = {
        "report_id": "target_tracker",
        "report_name": "Target Tracker",
        "anchor": anchor.isoformat(),
        "sold_through": sold_through.isoformat() if sold_through else None,
        "targeted_through": scanned.get("targeted_through"),
        "anchor_forced": bool(scanned.get("anchor_forced")),
        # TWO gaps, not one signed number. `target_lag_days` keeps its meaning -
        # sales recorded beyond the last target - so every existing consumer is
        # untouched; `sales_lag_days` is the reverse, targets set beyond the last
        # sale, which had no field at all and so was reported as "both measured
        # through <target date>" while five unsold days were counted as elapsed.
        "target_lag_days": (sold_through - anchor).days if (sold_through and sold_through > anchor) else 0,
        "sales_lag_days": ((_dt.date.fromisoformat(scanned["targeted_through"]) - sold_through).days
                           if (sold_through and scanned.get("targeted_through")
                               and _dt.date.fromisoformat(scanned["targeted_through"]) > sold_through)
                           else 0),
        "population": scanned.get("population") or [],
        "periods": {"day": day_p, "wtd": wtd_p, "mtd": mtd_p, "ytd": ytd_p},
        "days": days,
        "run": {"length": len(run), "average_shortfall": burn,
                "first": run[0]["date"] if run else None, "last": run[-1]["date"] if run else None},
        "surplus": {"built": built, "given_back": given_back, "now": surplus,
                    "share_given_back": (given_back / built * 100.0) if built > 0 else None,
                    "days_until_exhausted": exhausts_in, "exhausts_on": exhaust_date,
                    "earlier_days": len(earlier), "run_days": len(run)},
        "week_close": close(week_full_target, wtd_p["actual"], week_rem_target),
        "month_close": close(month_full_target, mtd_p["actual"], month_rem_target),
        "week_full_target": week_full_target,
        "month_full_target": month_full_target,
        "remaining_week_days": remaining_week,
        "days_hit": sum(1 for d in days if d["attainment"] is not None and d["attainment"] >= 100),
        "days_elapsed": len(days),
        "days_in_month": days_in_month,
        "prev_week": prev_week,
        "branches": branches,
        "departments": departments,
        "sections": sections,
        "weeks": weeks,
        "months": months,
    }
    model["projections"] = _projections(model)
    model["checks"] = reconcile(model)
    return model


def _projections(model: dict) -> dict:
    """Arithmetic that carries a stated rate forward. Never called a forecast
    (rulebook section 9)."""
    mtd = model["periods"]["mtd"]
    remaining_target = model["month_close"]["remaining_target"]
    at_month_rate = mtd["actual"] + remaining_target * (mtd["attainment"] or 0) / 100.0
    run_days = model["surplus"]["run_days"]
    recent = [d for d in model["days"][-run_days:]] if run_days else []
    recent_rate = (sum(d["actual"] for d in recent) / sum(d["target"] for d in recent) * 100.0
                   if recent and sum(d["target"] for d in recent) else None)
    at_recent_rate = (mtd["actual"] + remaining_target * recent_rate / 100.0) if recent_rate else None
    full = model["month_full_target"]
    return {
        "at_month_rate": at_month_rate,
        "at_month_rate_pct": (at_month_rate / full * 100.0) if full else None,
        "recent_rate": recent_rate,
        "at_recent_rate": at_recent_rate,
        "at_recent_rate_pct": (at_recent_rate / full * 100.0) if (at_recent_rate and full) else None,
    }


def reconcile(model: dict) -> dict:
    """Rulebook section 13. Every check is a fact about the model, not a warning."""
    checks = {}
    s = model["surplus"]
    checks["surplus_splits_reconcile"] = abs((s["built"] - s["given_back"]) - s["now"]) < 1.0
    day = model["periods"]["day"]
    branch_day = sum(b["day"]["variance"] for b in model["branches"])
    checks["branch_day_sums_to_company"] = abs(branch_day - day["variance"]) < 1.0
    mtd = model["periods"]["mtd"]
    branch_mtd = sum(b["mtd"]["variance"] for b in model["branches"])
    checks["branch_month_sums_to_company"] = abs(branch_mtd - mtd["variance"]) < 1.0
    day_series = sum(d["actual"] for d in model["days"])
    checks["day_series_sums_to_month"] = abs(day_series - mtd["actual"]) < 1.0
    checks["every_period_has_a_target"] = all(
        p["target"] > 0 for p in model["periods"].values())
    return checks
