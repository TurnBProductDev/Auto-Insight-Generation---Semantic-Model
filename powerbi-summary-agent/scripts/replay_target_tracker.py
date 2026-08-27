"""Offline replay for Target Tracker. Proves the code; no auth, no LLM, no live call.

    python scripts/replay_target_tracker.py

`scripts/audit_target_tracker.py` is the companion that proves a *produced artifact*.
This file builds from synthetic scans that carry the live figures, so it runs on a clean
checkout, and additionally replays the committed live scan when one is present.
"""

from __future__ import annotations

import re
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.sales import target_tracker as tt  # noqa: E402
from src.domains.sales import target_tracker_doc as doc  # noqa: E402
from src.domains.sales import target_tracker_html as html  # noqa: E402
from src.domains.sales import target_tracker_publish as pub  # noqa: E402

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' - ' + detail) if detail and not ok else ''}")


# ---------------------------------------------------------------------------
# synthetic scans carrying the real mid-July figures
# ---------------------------------------------------------------------------
JULY = [
    ("Wed", 1, 548927.32, 454347.81), ("Thu", 2, 874022.57, 648475.00),
    ("Fri", 3, 1423202.96, 1163832.00), ("Sat", 4, 532904.08, 513025.00),
    ("Sun", 5, 495771.51, 439025.00), ("Mon", 6, 455209.42, 441025.00),
    ("Tue", 7, 431450.78, 441025.00), ("Wed", 8, 439371.95, 441025.00),
    ("Thu", 9, 609818.11, 580337.00), ("Fri", 10, 1192610.76, 1023762.00),
    ("Sat", 11, 426132.14, 485567.74), ("Sun", 12, 401410.98, 423025.00),
    ("Mon", 13, 375439.25, 426025.00), ("Tue", 14, 365292.95, 421025.00),
    ("Wed", 15, 359154.03, 423025.00), ("Thu", 16, 526059.95, 553337.00),
]


def synthetic(anchor="2026-07-16", days=JULY, forced=False, month_full_target=16805350.49,
              week_full_target=3598827.00) -> dict:
    """Totals are summed from `days` rather than written by hand: a fixture whose header
    disagrees with its own rows tests nothing."""
    import datetime as _d
    day = days[-1]
    wk = tt.week_start(_d.date.fromisoformat(anchor)).day
    wtd_days = [d for d in days if d[1] >= wk]
    if month_full_target is None:                       # a completed month
        month_full_target = sum(d[3] for d in days)
    if week_full_target is None:
        week_full_target = sum(d[3] for d in wtd_days)
    return {
        "anchor": anchor, "sold_through": "2026-08-17", "anchor_forced": forced,
        "week_start": "2026-07-13", "month_start": "2026-07-01", "month_end": "2026-07-31",
        "population": ["CFH014", "CFH017", "CFH018", "CFH021"],
        "totals": [{
            "[day_sales]": day[2], "[day_target]": day[3],
            "[wtd_sales]": sum(d[2] for d in wtd_days), "[wtd_target]": sum(d[3] for d in wtd_days),
            "[week_full_target]": week_full_target,
            "[mtd_sales]": sum(d[2] for d in days), "[mtd_target]": sum(d[3] for d in days),
            "[month_full_target]": month_full_target,
            "[ytd_sales]": 120172004.68, "[ytd_target]": 116862300.84,
            "[prev_week_sales]": 3956004.14, "[prev_week_target]": 3835766.74}],
        "days": [{"[TY_DATE]": f"2026-07-{d[1]:02d}T00:00:00", "[DAY_OF_WEEK]": d[0],
                  "[DOC_DAY]": d[1], "[sales]": d[2], "[target]": d[3]} for d in days],
        "remaining_week_days": [
            {"[TY_DATE]": "2026-07-17T00:00:00", "[DAY_OF_WEEK]": "Fri", "[target]": 959365.00},
            {"[TY_DATE]": "2026-07-18T00:00:00", "[DAY_OF_WEEK]": "Sat", "[target]": 443025.00},
            {"[TY_DATE]": "2026-07-19T00:00:00", "[DAY_OF_WEEK]": "Sun", "[target]": 373025.00}],
        "weeks": [{"[week number]": 28, "[sales]": 3956004.14, "[target]": 3835766.74,
                   "[first_day]": "2026-07-06T00:00:00", "[last_day]": "2026-07-12T00:00:00", "[days]": 7},
                  {"[week number]": 29, "[sales]": 1625946.18, "[target]": 1823412.00,
                   "[first_day]": "2026-07-13T00:00:00", "[last_day]": "2026-07-16T00:00:00", "[days]": 4}],
        "months": [{"[DOC_MONTH]": 6, "[MONTH_NAME]": "JUN", "[sales]": 15550398.15, "[target]": 16769910.24},
                   {"[DOC_MONTH]": 7, "[MONTH_NAME]": "JUL", "[sales]": 9456777.96, "[target]": 8877883.54}],
        "branches": [
            {"[LOC_CODE]": "CFH017", "[day_sales]": 85908.30, "[day_target]": 125000.00,
             "[wtd_sales]": 281760.26, "[wtd_target]": 370000.00, "[mtd_sales]": 1462715.64,
             "[mtd_target]": 1590000.00, "[ytd_sales]": 21247266.56, "[ytd_target]": 22895758.64,
             "[month_full_target]": 3008405.13},
            {"[LOC_CODE]": "CFH014", "[day_sales]": 177896.69, "[day_target]": 173337.00,
             "[wtd_sales]": 555810.56, "[wtd_target]": 623412.00, "[mtd_sales]": 2982588.04,
             "[mtd_target]": 2803717.00, "[ytd_sales]": 39799372.36, "[ytd_target]": 39128478.89,
             "[month_full_target]": 5363778.82},
            {"[LOC_CODE]": "CFH021", "[day_sales]": 170168.18, "[day_target]": 155000.00,
             "[wtd_sales]": 516883.07, "[wtd_target]": 550000.00, "[mtd_sales]": 3098149.48,
             "[mtd_target]": 2898623.81, "[ytd_sales]": 41808278.93, "[ytd_target]": 38590044.50,
             "[month_full_target]": 5252623.81},
            {"[LOC_CODE]": "CFH018", "[day_sales]": 92086.78, "[day_target]": 100000.00,
             "[wtd_sales]": 271492.29, "[wtd_target]": 280000.00, "[mtd_sales]": 1913324.80,
             "[mtd_target]": 1585542.74, "[ytd_sales]": 25523889.60, "[ytd_target]": 24175485.74,
             "[month_full_target]": 3180542.74}],
        "departments": [
            {"[DEPARTMENT]": "FMCG FOOD", "[day_sales]": 192488.70, "[day_target]": 212261.43,
             "[wtd_sales]": 593716.03, "[wtd_target]": 693874.80, "[mtd_sales]": 3575212.27,
             "[mtd_target]": 3357933.41},
            {"[DEPARTMENT]": "FARM FRESH", "[day_sales]": 120155.96, "[day_target]": 99742.56,
             "[wtd_sales]": 329403.43, "[wtd_target]": 327710.59, "[mtd_sales]": 1778576.74,
             "[mtd_target]": 1581740.89},
            {"[DEPARTMENT]": "FASHION", "[day_sales]": 31678.39, "[day_target]": 34927.87,
             "[wtd_sales]": 94781.90, "[wtd_target]": 116828.09, "[mtd_sales]": 554513.34,
             "[mtd_target]": 564813.37},
            {"[DEPARTMENT]": "OTHER NON TRADE", "[day_sales]": 534.91, "[day_target]": None,
             "[wtd_sales]": 2087.49, "[wtd_target]": None, "[mtd_sales]": 6527.06,
             "[mtd_target]": None}],
        "sections": [
            {"[SECTION]": "CF-CHILLED & DAIRY", "[DEPARTMENT]": "FMCG FOOD",
             "[mtd_sales]": 376365.50, "[mtd_target]": 400294.48},
            {"[SECTION]": "CF-STAPLES", "[DEPARTMENT]": "FMCG FOOD",
             "[mtd_sales]": 902183.81, "[mtd_target]": 729623.78},
            {"[SECTION]": "CF-NON TRADING MERCHENDISE", "[DEPARTMENT]": "OTHER NON TRADE",
             "[mtd_sales]": 6527.06, "[mtd_target]": None}],
    }


def test_anchor_both_directions() -> None:
    """The anchor is where BOTH feeds reach - in either direction.

    Live on 2026-08-27 SB Mart published "31 days of 31", "the month is complete",
    a run of 25 days below target and a today of USD 0 against a full target,
    because targets are loaded to month end while sales lagged to the 26th. The
    year read 99.4% and "below target" when the elapsed truth was 101.5% and above
    it - a direction, not just a magnitude.
    """
    import datetime as _d
    print('\n' + "[anchor: both feeds]")

    def fake(targeted: str, sold: str | None):
        def execute(_dax: str):
            return [{"[with_target]": targeted, "[with_sales]": sold}]
        return execute

    # SB Mart's shape: targets ahead of sales. The anchor must fall back to sales.
    a, sold, targeted, forced = tt.resolve_anchor(fake("2026-08-31", "2026-08-26"), ["ST1"])
    check("targets ahead of sales -> anchor is the last SOLD day",
          a == _d.date(2026, 8, 26), str(a))
    check("...and both watermarks are returned",
          sold == _d.date(2026, 8, 26) and targeted == _d.date(2026, 8, 31),
          f"{sold} / {targeted}")
    check("...and it is not marked forced", forced is False)

    # The original shape this rule was written for: sales ahead of targets.
    # Behaviour must be unchanged - the other live client is in this state.
    a2, sold2, targeted2, _ = tt.resolve_anchor(fake("2026-07-31", "2026-08-19"), ["CFH014"])
    check("sales ahead of targets -> anchor is the last TARGETED day (unchanged)",
          a2 == _d.date(2026, 7, 31), str(a2))

    # A model with targets and no sales at all still resolves.
    a3, sold3, _, _ = tt.resolve_anchor(fake("2026-08-31", None), ["ST1"])
    check("no sales anywhere -> the target date is all there is",
          a3 == _d.date(2026, 8, 31) and sold3 is None, str(a3))

    # An override still wins, and is reported as forced.
    a4, _, _, forced4 = tt.resolve_anchor(fake("2026-08-31", "2026-08-26"), ["ST1"],
                                          override="2026-08-20")
    check("an override still wins and says so",
          a4 == _d.date(2026, 8, 20) and forced4 is True, str(a4))
    # An override equal to what would have been resolved is not "forced".
    _, _, _, forced5 = tt.resolve_anchor(fake("2026-08-31", "2026-08-26"), ["ST1"],
                                         override="2026-08-26")
    check("an override matching the resolved date is not reported as forced",
          forced5 is False)


def test_lag_is_symmetric() -> None:
    print('\n' + "[lag: both directions]")
    scan_ahead = synthetic(anchor="2026-07-16")          # sold_through 2026-08-17
    m = tt.build(scan_ahead)
    check("sales ahead of targets -> target_lag_days is set",
          m["target_lag_days"] > 0 and m["sales_lag_days"] == 0,
          f"{m['target_lag_days']}/{m['sales_lag_days']}")

    scan_behind = {**synthetic(anchor="2026-07-16"),
                   "sold_through": "2026-07-16", "targeted_through": "2026-07-31"}
    m2 = tt.build(scan_behind)
    check("targets ahead of sales -> sales_lag_days is set",
          m2["sales_lag_days"] == 15 and m2["target_lag_days"] == 0,
          f"{m2['target_lag_days']}/{m2['sales_lag_days']}")

    # The context line must name the gap, not deny it. This is the sentence that
    # shipped: "Actual sales and targets are both measured through 2026-08-31."
    from src.domains.sales import target_tracker_publish as pub
    payload = pub.summary_payload(m2)
    ctx = " ".join(p for s in payload["sections"] for p in s["points"])
    check("the reverse gap is stated on the page",
          "2026-07-31" in ctx and "not traded" in ctx.lower(), ctx[-190:])
    check("...and it never claims both feeds reach the same date",
          "both measured through" not in ctx.lower(), ctx[-190:])


def test_month_done_needs_real_sales() -> None:
    from src.domains.sales import target_tracker_author as author
    print('\n' + "[month complete: counter AND data]")
    # A forced anchor on month end, with sales stopping earlier, must NOT be
    # called complete - the counter says 31 of 31 but five days never traded.
    m = tt.build({**synthetic(anchor="2026-07-16"), "sold_through": "2026-07-16"})
    m = {**m, "days_elapsed": m["days_in_month"]}        # what a forced anchor produces
    errs = author.validate({"headline": "The month is complete at 95.1% of target.",
                            "narrative": "Today reached 95.1% of target.",
                            "today_note": "One branch missed target today.",
                            "month_note": "The month is complete."}, m)
    check("a forced month-end anchor with earlier sales is not 'complete'",
          any("calls the month complete" in e for e in errs), str(errs[:2]))
    check("...and the reason names the sales watermark, not '0 days remain'",
          any("only recorded to" in e for e in errs), str(errs[:2]))


def main() -> int:
    print("Target Tracker replay\n")

    # ---- helpers ---------------------------------------------------------
    print("date and scope helpers")
    import datetime as dt
    check("week starts on Monday", tt.week_start(dt.date(2026, 7, 16)) == dt.date(2026, 7, 13))
    check("a Monday is its own week start", tt.week_start(dt.date(2026, 7, 13)) == dt.date(2026, 7, 13))
    check("month bounds", tt.month_bounds(dt.date(2026, 7, 16)) == (dt.date(2026, 7, 1), dt.date(2026, 7, 31)))
    check("December does not roll into next year",
          tt.month_bounds(dt.date(2026, 12, 5))[1] == dt.date(2026, 12, 31))
    check("date formatting is portable",
          tt.fmt_date(dt.date(2026, 7, 6), "short") == "Mon 6 Jul", tt.fmt_date(dt.date(2026, 7, 6), "short"))

    print("\nbands (rulebook section 6)")
    check("100% is on target", tt.band(100, 100)[1] == "On target")
    check("99.9% is watch", tt.band(99.9, 100)[1] == "Watch")
    check("94.9% is below target", tt.band(94.9, 100)[1] == "Below target")
    check("no target gives no band, not a zero",
          tt.attainment(5, 0) is None and tt.band(5, 0)[0] == "none")

    # ---- the mid-month case ---------------------------------------------
    print("\nmid-month model (the approved reference figures)")
    m = tt.build(synthetic())
    p = m["periods"]
    check("day 95.1% of target", abs(p["day"]["attainment"] - 95.07) < 0.02, str(p["day"]["attainment"]))
    check("week 89.2% of target", abs(p["wtd"]["attainment"] - 89.17) < 0.02, str(p["wtd"]["attainment"]))
    check("month 106.5% of target", abs(p["mtd"]["attainment"] - 106.52) < 0.02, str(p["mtd"]["attainment"]))
    check("run of 6 days below target", m["run"]["length"] == 6, str(m["run"]["length"]))
    check("surplus built 857.4K", abs(m["surplus"]["built"] - 857410) < 50, str(m["surplus"]["built"]))
    check("surplus given back 278.5K", abs(m["surplus"]["given_back"] - 278515) < 50,
          str(m["surplus"]["given_back"]))
    check("the two halves reconcile to the month gap", m["checks"]["surplus_splits_reconcile"])
    check("surplus runs out on 28 July", m["surplus"]["exhausts_on"] == "2026-07-28",
          str(m["surplus"]["exhausts_on"]))
    check("week needs 111.1% of the remaining target",
          abs(m["week_close"]["needed_vs_target"] - 111.12) < 0.05,
          str(m["week_close"]["needed_vs_target"]))
    check("month needs 92.7% of the remaining target",
          abs(m["month_close"]["needed_vs_target"] - 92.69) < 0.05,
          str(m["month_close"]["needed_vs_target"]))
    check("8 of 16 days hit target", m["days_hit"] == 8, str(m["days_hit"]))
    check("all reconciliation checks pass", all(m["checks"].values()), str(m["checks"]))

    print("\nrulebook section 10 - a department with no target is excluded, not zeroed")
    check("untargeted department dropped from the attainment tables",
          all(d["name"] != "OTHER NON TRADE" for d in m["departments"]))
    check("untargeted section dropped too",
          all(s["name"] != "CF-NON TRADING MERCHENDISE" for s in m["sections"]))

    print("\nrulebook section 3.1 - every period measured against the elapsed target")
    check("month target is the elapsed target, not the full month",
          abs(p["mtd"]["target"] - 8877883.54) < 1 and abs(m["month_full_target"] - 16805350.49) < 1)
    check("full-month target only used for catch-up",
          abs(m["month_close"]["needed"] - 7348572.53) < 1, str(m["month_close"]["needed"]))

    # ---- the completed-period case ---------------------------------------
    print("\ncompleted month (no run of misses)")
    full = JULY + [("Fri", d, 500000.0, 450000.0) for d in range(17, 32)]
    done = tt.build({**synthetic(anchor="2026-07-31", days=full,
                                 month_full_target=None, week_full_target=None),
                     "remaining_week_days": []})
    check("no run when the last day beat target", done["run"]["length"] == 0, str(done["run"]["length"]))
    check("no invented exhaustion date", done["surplus"]["exhausts_on"] is None)
    check("catch-up is not offered when nothing is left",
          done["month_close"]["needed_vs_target"] is None or done["month_close"]["remaining_target"] <= 0)
    page = html.render(done)
    check("page says the period cannot be tracked or is complete",
          "cannot be tracked further" in page or "is complete" in page)
    check("no negative 'still needed' figure printed", "still needed</th>" not in page.lower()
          or "&minus;" not in page.split("Still needed")[-1][:400])

    # ---- rendering -------------------------------------------------------
    print("\npage structure (the three faults that broke the first inventory dashboard)")
    page = html.render(m)
    import re
    check("exactly one script tag", page.count("<script") == 1, str(page.count("<script")))
    app_children = re.findall(r'<div class="app">\s*<(\w+)', page)
    check("nav is the first child of .app", app_children == ["nav"], str(app_children))
    check("content lives in main > .page", "<main><div class=\"page\">" in page)
    check("no external requests", not re.findall(r'(?:src|href)\s*=\s*["\'](?!#)', page))
    check("no browser storage", not any(w in page for w in ("localStorage", "sessionStorage", "fetch(")))
    check("four layers", sorted(set(re.findall(r'data-layer="(\w+)"', page)))
          == ["branches", "departments", "detail", "performance"])
    check("two views", sorted(set(re.findall(r'data-view="(\w+)"', page))) == ["all", "behind"])
    check("caveats appear once per view", page.count("Important things to know") == 2,
          str(page.count("Important things to know")))

    print("\nlanguage (rulebook section 5)")
    banned = ["attainment", "month-to-date", "week-to-date", "cushion", "the estate", "QAR"]
    found = {w: page.count(w) for w in banned if w in page}
    check("no banned vocabulary on the page", not found, str(found))
    check("currency is SAR", "SAR" in page and "QAR" not in page)
    check("escaped", "<img" not in html.render({**m, "report_name": "<img src=x onerror=1>"}))
    sb_page = html.render(m, currency="QAR", title="SB Mart Target Tracker",
                          eyebrow="Sales · SB Mart")
    check("client branding is configurable",
          "SB Mart Target Tracker" in sb_page and "City Flower" not in sb_page)
    check("QAR uses the correct currency name",
          "Qatari riyals (QAR)" in sb_page and "Saudi riyals" not in sb_page)

    print("\nbusiness document")
    document = doc.render(m)
    check("headline is an h1", document.startswith("# "))
    check("covers all four periods",
          all(s in document for s in ("Today", "This week", "This month", "The year so far")))
    check("states the no-prior-year limitation", "no comparison with last year" in document)
    check("states that no cause is given", "No causes are given" in document)
    check("no banned vocabulary in the document",
          not [w for w in banned if w in document], str([w for w in banned if w in document]))
    check("branch table present", "| Branch |" in document)

    print("\napp payload")
    from datetime import datetime, timezone
    from src.tools.api_payloads import ReportSummaryPayload

    generated = datetime(2026, 8, 21, 5, 30, tzinfo=timezone.utc)
    payload = pub.summary_payload(m, title="SB Mart Target Tracker", currency="QAR",
                                  generated_at=generated)
    check("payload uses the exact app summary contract",
          set(payload) == {"title", "generatedAt", "headline", "metrics", "sections"},
          str(sorted(payload)))
    check("payload passes the app's strict schema", bool(ReportSummaryPayload(**payload)))
    check("payload carries all four target periods", len(payload["metrics"]) == 4)
    check("payload uses the configured client title and currency",
          payload["title"] == "SB Mart Target Tracker"
          and all("QAR" in point for point in payload["sections"][0]["points"]))
    check("payload generation date follows the published run",
          payload["generatedAt"] == "2026-08-21")
    check("payload keeps Target Tracker context",
          payload["sections"][0]["heading"] == "Performance against target"
          and "no prior-year comparison" in payload["sections"][2]["points"][1])
    check("headline is under 'headline' (the name the app reads)",
          bool(str(payload["headline"]).strip()))
    check("the anchor is stated in the prose",
          m["anchor"] in " ".join(pt for section in payload["sections"]
                                   for pt in section["points"]))
    check("no payload figure is printed with more than two decimals",
          not re.search(r"\d+\.\d{3,}", " ".join(
              [metric["value"] for metric in payload["metrics"]]
              + [pt for section in payload["sections"] for pt in section["points"]])))

    one_warn = {**m, "branches": [dict(branch) for branch in m["branches"]]}
    one_warn["branches"][0] = {
        **one_warn["branches"][0],
        "mtd": {**one_warn["branches"][0]["mtd"], "variance": -1.0, "band": "warn"},
    }
    warn_payload = pub.summary_payload(one_warn, generated_at=generated)
    check("every below-target branch is surfaced, including watch-band branches",
          one_warn["branches"][0]["name"] in warn_payload["sections"][1]["points"][0])

    print("\nforced anchor is described honestly")
    forced_model = tt.build(synthetic(forced=True))
    check("forced anchor is not called the latest targeted day",
          "most recent day that has a sales target" not in doc.render(forced_model))
    check("resolved anchor is", "most recent day that has a sales target" in document)

    # ---- Phase 4: authored prose -----------------------------------------
    from src.domains.sales import target_tracker_author as author

    print("\nprose validation (rulebook enforced on the model's words)")
    good = {
        "headline": "6 days below target have used up about one-third of this month's surplus.",
        "narrative": ("Today reached 95.1% of target. That makes six days below target in a row, "
                      "and the week is now at 89.2%. The month is still ahead at 106.5%, but the "
                      "surplus is being spent. The year is not at risk."),
        "today_note": "CFH017 was 68.7% of target and furthest short.",
        "month_note": "The month has SAR 578.9K above target left.",
    }
    check("a clean draft passes", not author.validate(good, m), str(author.validate(good, m)[:3]))

    def rejects(name, prose, needle):
        errs = author.validate(prose, m)
        check(name, any(needle in e for e in errs), f"errors were {errs[:3]}")

    rejects("invented figure is rejected",
            {**good, "headline": "The month is 141.9% of target with SAR 999.9K spare."},
            "not a figure in the report")
    rejects("over-precise figure is rejected",
            {**good, "headline": "The month reached 106.5231% of target."},
            "more than one decimal")
    rejects("banned vocabulary is rejected",
            {**good, "narrative": "Today's attainment was 95.1% of target."}, "attainment")
    rejects("MTD jargon is rejected",
            {**good, "month_note": "MTD is 106.5% of target."}, "mtd")
    rejects("an invented cause is rejected",
            {**good, "today_note": "CFH017 was 68.7% because of a stockout."}, "cause")
    rejects("a promotion claim is rejected",
            {**good, "today_note": "CFH017 was 68.7% of target after a promotion ended."},
            "promotion")
    rejects("forecasting language is rejected",
            {**good, "month_note": "The month will finish at 106.5% of target."},
            "forecasting")
    rejects("a prior-year comparison is rejected",
            {**good, "narrative": "Today reached 95.1% of target, ahead of last year."},
            "prior year")
    rejects("an unknown branch is rejected",
            {**good, "today_note": "CFH099 was 68.7% of target."}, "not a branch")
    rejects("an emoji is rejected", {**good, "headline": "Sales are up 106.5% \U0001F680"}, "emoji")
    rejects("a headline with no figure is rejected",
            {**good, "headline": "Performance was somewhat below expectations."},
            "quotes no figure")
    rejects("leading on the year is rejected",
            {**good, "narrative": "The year is at 102.8% of target. Today reached 95.1%, and the "
                                  "week is at 89.2%. The month is at 106.5%."},
            "leads on the year")
    rejects("the week before today is rejected",
            {**good, "narrative": "The week is at 89.2% of target and today reached 95.1%. The "
                                  "month is at 106.5%."},
            "week before today")
    check("SAR is allowed as a word", not any("SAR" in e for e in author.validate(
        {**good, "month_note": "The surplus is SAR 578.9K."}, m)))
    check("a year is not treated as an invented figure",
          not any("2026" in e for e in author.validate(
              {**good, "month_note": "July 2026 is 106.5% of target."}, m)))

    full = JULY + [("Fri", d, 500000.0, 450000.0) for d in range(17, 32)]
    print("\nclaims the figures contradict (a real live draft failed this way)")
    # On 31 July CFH017 was at 91.3% of target while the model wrote "No branch
    # missed today". Every figure in that sentence was real; the claim was not.
    rejects("'no branch missed' is rejected when one did",
            {**good, "today_note": "No branch missed today. CFH017 was the lowest at 68.7%."},
            "claims no branch missed")
    rejects("'every branch reached target' is rejected when one did not",
            {**good, "today_note": "Every branch reached target today."},
            "claims no branch missed")
    rejects("a wrong run length is rejected",
            {**good, "narrative": "Today reached 95.1%. That is 4 days below target in a row, "
                                  "the week is 89.2% and the month 106.5%."},
            "the run is")
    check("the correct run length passes",
          not any("run is" in e for e in author.validate(
              {**good, "narrative": "Today reached 95.1% of target. That is 6 days below target "
                                    "in a row. The week is at 89.2% and the month at 106.5%."}, m)))

    done_model = tt.build(synthetic(anchor="2026-07-31", days=full,
                                    month_full_target=None, week_full_target=None))
    errs = author.validate({**good, "month_note": "There are days left to change the month."},
                           done_model)
    check("'days left' is rejected once the month is complete",
          any("month is complete" in e for e in errs), str(errs[:2]))
    errs = author.validate({**good, "month_note": "The month is complete."}, m)
    check("'the month is complete' is rejected mid-month",
          any("days remain" in e for e in errs), str(errs[:2]))

    check("only four slots are asked for", author.SLOTS ==
          ("headline", "narrative", "today_note", "month_note"), str(author.SLOTS))

    print("\nauthoring falls back safely")
    off = author.author(m, {"target_tracker_currency": "SAR"})
    check("authoring off returns the deterministic draft", off["authoring_mode"] == "deterministic")
    check("the deterministic draft passes its own validator",
          not author.validate(off, m), str(author.validate(off, m)[:3]))
    broken = author.author(m, {"target_tracker_llm_authoring_enabled": True,
                               "ai_provider": "azure_openai"}, log=lambda *_: None)
    check("a failed LLM call still returns usable prose",
          broken["authoring_mode"] == "deterministic" and broken["headline"])
    check("the quotable list is non-empty and grounded", len(author.quotable(m)) >= 8)

    # ---- the committed live scan, when present ----------------------------
    live = PROJECT_ROOT / "outputs_targettracker" / "scan_liveanchor.json"
    if live.is_file():
        print("\nlive scan replay")
        lm = tt.build(json.loads(live.read_text(encoding="utf-8")))
        check("live model reconciles", all(lm["checks"].values()), str(lm["checks"]))
        check("live page renders", len(html.render(lm)) > 20000)
        check("live document renders", len(doc.render(lm)) > 1500)
    else:
        print("\nlive scan replay: skipped (no committed scan)")

    test_anchor_both_directions()
    test_lag_is_symmetric()
    test_month_done_needs_real_sales()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
