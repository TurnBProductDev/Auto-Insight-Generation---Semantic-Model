"""Offline replay: P5.2 - TargetVsActualSpine and the target-vs-actual detectors.

Exit criterion: Target Tracker emits ranked signals offline from a committed
scan. That scan is a **completed** month with a surplus, so it exercises only the
detectors that state can produce; the mid-period detectors (a run of misses, a
catch-up requirement out of reach, a surplus burning out) are exercised from
synthetic models built on the same shape.

The guards matter as much as the detections:

* no signal states a cause - this model holds no promotions, stock, staffing,
  weather or footfall;
* no signal carries a prior-year comparison, because the data is 2026 only;
* no signal uses the rulebook's banned vocabulary, and the ban list is imported
  from the author rather than copied;
* a day with no target is `baseline_missing`, never a 100% miss.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.sales import spines, target_tracker as tt  # noqa: E402
from src.domains.sales import target_tracker_author as author  # noqa: E402
from src.domains.sales import target_tracker_signals as ts  # noqa: E402
from src.kernel import spine as kernel_spine  # noqa: E402

FAILURES: list[str] = []
LIVE_SCAN = PROJECT_ROOT / "outputs_targettracker" / "target_tracker_scan.json"


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _live_model() -> dict | None:
    if not LIVE_SCAN.exists():
        return None
    return tt.build(json.loads(LIVE_SCAN.read_text(encoding="utf-8")))


# --- 1. the spine -------------------------------------------------------------
def test_spine() -> None:
    print("\n[1] TargetVsActualSpine")
    spine = spines.TargetVsActualSpine()
    check("registered in the kernel registry", "target_vs_actual" in kernel_spine.available())
    check("registry returns the class", kernel_spine.get("target_vs_actual") is spines.TargetVsActualSpine)
    check("baseline is named in English", spine.baseline_label == "the target")
    check("delta is an absolute movement", spine.delta_kind() == kernel_spine.ABSOLUTE)
    check("delta and exposure share a unit (unlike the policy spine)",
          spine.delta_unit() == spine.exposure_unit() == "value")

    # pct is attainment relative to 100, delegated to the report's own helper.
    check("91.3% of target reads as -8.7", abs((spine.pct(91.3, 100.0) or 0) + 8.7) < 1e-9,
          str(spine.pct(91.3, 100.0)))
    check("on target reads as 0", spine.pct(100.0, 100.0) == 0.0)
    check("a zero target yields no percentage", spine.pct(50.0, 0) is None)
    check("a missing actual yields no percentage", spine.pct(None, 100.0) is None)

    # The August case: 2,682 rows with a NULL target.
    check("no target is baseline_missing, NOT a 100% miss",
          spine.classify({"actual": 5.0, "target": None}) == kernel_spine.BASELINE_MISSING)
    check("a zero target is also baseline_missing",
          spine.classify({"actual": 5.0, "target": 0}) == kernel_spine.BASELINE_MISSING)
    check("target but no actual is current_only",
          spine.classify({"actual": None, "target": 5.0}) == kernel_spine.CURRENT_ONLY)
    check("neither is inactive",
          spine.classify({"actual": None, "target": None}) == kernel_spine.INACTIVE)
    check("both present is comparable",
          spine.classify({"actual": 5.0, "target": 6.0}) == kernel_spine.COMPARABLE)

    # A shortfall is a share of what was ASKED FOR, not of what was achieved.
    check("denominator totals the target, not the actual",
          spine.denominator([{"actual": 100, "target": 10}, {"actual": 1, "target": 30}]) == 40.0)
    check("no targets yields no denominator", spine.denominator([{"actual": 5}]) is None)

    check("population filter uses TREATAS, never KEEPFILTERS",
          "TREATAS" in (spine.population_filter(
              {"population": ["CFH017"], "entity_reference": "'t'[LOC_CODE]"}) or ""))
    check("no population yields no filter", spine.population_filter({}) is None)
    check("the caveat states there is no prior year",
          any("last year" in c.lower() for c in spine.caveats()), str(spine.caveats()))

    # The anchor rule: keyed on the targeted day, not the run date.
    key_a = ts.story_key("target_below_run", "", "2026-07-31")
    key_b = ts.story_key("target_below_run", "", "2026-07-31")
    key_c = ts.story_key("target_below_run", "", "2026-06-30")
    check("story key is stable for the same anchor", key_a == key_b)
    check("a new targeted day is a new story", key_a != key_c)
    check("a different finding is a different story",
          ts.story_key("target_catch_up_month", "", "2026-07-31") != key_a)
    check("a different branch is a different story",
          ts.story_key("target_branch_below_every_period", "CFH017", "2026-07-31")
          != ts.story_key("target_branch_below_every_period", "CFH014", "2026-07-31"))


# --- 2. the committed live scan -----------------------------------------------
def test_live_scan() -> None:
    print("\n[2] Ranked signals from the committed live scan")
    model = _live_model()
    if model is None:
        print("  [SKIP] no committed target_tracker_scan.json")
        return
    signals = ts.detect(model)
    check("signals are produced", len(signals) > 0, str(len(signals)))
    check("ids are assigned in rank order",
          [s["id"] for s in signals] == [f"T{i}" for i in range(1, len(signals) + 1)])
    scores = [s["score"] for s in signals]
    check("ranked by score, descending", scores == sorted(scores, reverse=True), str(scores))

    # The branch that fooled a live authored draft ("No branch missed today"
    # while it sat at 91.3% of target) must be detected, and must lead.
    top = signals[0]
    check("CFH017 is detected as below target in every period",
          any(s["affected_segment"] == "CFH017"
              and s["analysis_type"] == "target_branch_below_every_period" for s in signals))
    check("it ranks first - it is the largest gap against its target",
          top["affected_segment"] == "CFH017", top["affected_segment"])
    check("it is graded critical", top["severity"] == "critical", top["severity"])
    check("its four period readings are all recorded",
          set(top["attainment_by_scope"]) == {"day", "wtd", "mtd", "ytd"})
    check("every recorded reading is below target",
          all(v < 100 for v in top["attainment_by_scope"].values()))

    # A completed month with a surplus must NOT invent mid-period findings.
    kinds = {s["analysis_type"] for s in signals}
    check("no run-of-misses signal on a month with no run",
          "target_below_run" not in kinds, str(kinds))
    check("no catch-up signal once the month is complete",
          not any(k.startswith("target_catch_up") for k in kinds), str(kinds))
    check("no surplus-exhausting signal when nothing is being given back",
          "target_surplus_exhausting" not in kinds, str(kinds))
    check("a part below target inside a whole above it IS detected",
          any(k in kinds for k in ("target_department_below_company_above",
                                   "target_section_below_department_above")), str(kinds))


# --- 3. the guards ------------------------------------------------------------
def test_guards() -> None:
    print("\n[3] Guards: no cause, no prior year, plain language")
    model = _live_model()
    if model is None:
        print("  [SKIP] no committed scan")
        return
    signals = ts.detect(model)

    def prose(signal: dict) -> str:
        return " ".join(
            str(signal.get(key) or "")
            for key in ("description", "question", "comparison_label", "metric")
        ).lower()

    banned = [(s["id"], w) for s in signals for w in author.BANNED if w in prose(s)]
    check("no banned vocabulary in any signal", not banned, str(banned))
    causes = [(s["id"], w) for s in signals for w in author.CAUSE_WORDS if w in prose(s)]
    check("no signal states a cause", not causes, str(causes))
    priors = [(s["id"], w) for s in signals for w in author.PRIOR_YEAR_WORDS if w in prose(s)]
    check("no signal implies a prior-year comparison", not priors, str(priors))

    check("no signal carries a populated prior",
          all(s.get("prior") is None for s in signals))
    check("every signal names what it was compared against",
          all(str(s.get("comparison_label") or "").strip() for s in signals))
    check("every signal is stamped with its report",
          all(s.get("report_id") == "target_tracker" for s in signals))
    check("every signal carries its spine",
          all(s.get("spine") == "target_vs_actual" for s in signals))
    check("every signal has a stable story key",
          all(str(s.get("story_key") or "").startswith("tt:v1:") for s in signals))
    check("story keys are unique within a run",
          len({s["story_key"] for s in signals}) == len(signals))


# --- 4. mid-period states the live scan cannot reach --------------------------
def _mid_month_model(**over) -> dict:
    """A mid-month model in the shape `build` produces, for the states a
    completed month cannot exercise."""
    model = {
        "anchor": "2026-07-18",
        "periods": {
            "day": {"actual": 900.0, "target": 1000.0, "attainment": 90.0, "variance": -100.0},
            "wtd": {"actual": 4000.0, "target": 4200.0, "attainment": 95.2, "variance": -200.0},
            "mtd": {"actual": 9000.0, "target": 10000.0, "attainment": 90.0, "variance": -1000.0},
            "ytd": {"actual": 50000.0, "target": 52000.0, "attainment": 96.2, "variance": -2000.0},
        },
        "run": {"length": 0, "average_shortfall": 0.0, "first": None, "last": None},
        "surplus": {"built": 0.0, "given_back": 0.0, "now": 0.0, "run_days": 0,
                    "days_until_exhausted": None, "exhausts_on": None},
        "month_close": {"needed": 0.0, "remaining_target": 5000.0, "needed_vs_target": 0.0},
        "week_close": {"needed": 0.0, "remaining_target": 1000.0, "needed_vs_target": 0.0},
        "branches": [], "departments": [], "sections": [],
    }
    model.update(over)
    return model


def test_mid_period() -> None:
    print("\n[4] Mid-period detectors (synthetic, same model shape)")

    # (a) a run of days below target
    run_model = _mid_month_model(
        run={"length": 4, "average_shortfall": 250.0, "first": "2026-07-15", "last": "2026-07-18"},
        surplus={"built": 3000.0, "given_back": 1000.0, "now": 2000.0, "run_days": 4,
                 "days_until_exhausted": None, "exhausts_on": None},
    )
    run_signals = [s for s in ts.detect(run_model) if s["analysis_type"] == "target_below_run"]
    check("a run of 4 days below target is detected", len(run_signals) == 1)
    if run_signals:
        check("the run signal names both ends of the run",
              "2026-07-15" in run_signals[0]["description"]
              and "2026-07-18" in run_signals[0]["description"])
        check("the run length is carried structurally", run_signals[0]["run_length"] == 4)
    check("a single bad day is NOT a run",
          not [s for s in ts.detect(_mid_month_model(
              run={"length": 1, "average_shortfall": 100.0,
                   "first": "2026-07-18", "last": "2026-07-18"}))
              if s["analysis_type"] == "target_below_run"])

    # (b) catch-up beyond what the remaining days were set to deliver
    catch = _mid_month_model(
        month_close={"needed": 7000.0, "remaining_target": 5000.0, "needed_vs_target": 140.0})
    catch_signals = [s for s in ts.detect(catch) if s["analysis_type"] == "target_catch_up_month"]
    check("a catch-up requirement above 100% is detected", len(catch_signals) == 1)
    if catch_signals:
        check("the catch-up signal quotes the requirement",
              "140%" in catch_signals[0]["description"], catch_signals[0]["description"])
    check("a reachable catch-up is not a signal",
          not [s for s in ts.detect(_mid_month_model(
              month_close={"needed": 4000.0, "remaining_target": 5000.0, "needed_vs_target": 80.0}))
              if s["analysis_type"] == "target_catch_up_month"])

    # (c) a surplus burning out before month end
    burn = _mid_month_model(
        surplus={"built": 5000.0, "given_back": 1200.0, "now": 1800.0, "run_days": 3,
                 "days_until_exhausted": 4.5, "exhausts_on": "2026-07-23"})
    burn_signals = [s for s in ts.detect(burn) if s["analysis_type"] == "target_surplus_exhausting"]
    check("a surplus running out before month end is detected", len(burn_signals) == 1)
    if burn_signals:
        check("it states the date the surplus runs out",
              "2026-07-23" in burn_signals[0]["description"])
    check("a surplus that is not being given back is not a signal",
          not [s for s in ts.detect(_mid_month_model()) if s["analysis_type"] == "target_surplus_exhausting"])

    # Guards apply to the synthetic prose too.
    for model in (run_model, catch, burn):
        for signal in ts.detect(model):
            text = f"{signal['description']} {signal['question']}".lower()
            check(f"{signal['analysis_type']}: no cause stated",
                  not any(w in text for w in author.CAUSE_WORDS))
            check(f"{signal['analysis_type']}: plain language",
                  not any(w in text for w in author.BANNED))


# --- 5. ranking is exposure-weighted ------------------------------------------
def test_ranking() -> None:
    print("\n[5] A small area missing badly cannot outrank a large one")
    model = _mid_month_model(
        periods={
            "day": {"actual": 900.0, "target": 1000.0, "attainment": 90.0, "variance": -100.0},
            "wtd": {"actual": 4000.0, "target": 4200.0, "attainment": 95.2, "variance": -200.0},
            "mtd": {"actual": 10500.0, "target": 10000.0, "attainment": 105.0, "variance": 500.0},
            "ytd": {"actual": 50000.0, "target": 52000.0, "attainment": 96.2, "variance": -2000.0},
        },
        departments=[
            {"name": "TINY", "mtd": {"actual": 10.0, "target": 100.0,
                                     "attainment": 10.0, "variance": -90.0}},
            {"name": "LARGE", "mtd": {"actual": 4600.0, "target": 5000.0,
                                      "attainment": 92.0, "variance": -400.0}},
        ],
    )
    signals = [s for s in ts.detect(model)
               if s["analysis_type"] == "target_department_below_company_above"]
    order = [s["affected_segment"] for s in signals]
    check("both departments are detected", set(order) == {"TINY", "LARGE"}, str(order))
    check("the LARGE department outranks the TINY one at 10% of target",
          order.index("LARGE") < order.index("TINY"), str(order))
    check("a gap below the relevance floor is dropped",
          not [s for s in ts.detect(_mid_month_model(
              periods=model["periods"],
              departments=[{"name": "SPECK", "mtd": {"actual": 9.0, "target": 10.0,
                                                     "attainment": 90.0, "variance": -1.0}}]))
              if s["analysis_type"] == "target_department_below_company_above"])
    check("an empty model produces no signals", ts.detect({}) == [])
    check("limit is honoured", len(ts.detect(_live_model() or {}, limit=1)) <= 1)



# --- 6. the published summary must match the shared app contract --------------
def test_summary_contract() -> None:
    """The app reads five field names. Anything else is discarded in silence.

    An earlier version of `summary_payload` filed the headline under `heading`
    and the detail under `points`, and added ten fields the contract forbids.
    The app found no `headline`, dropped the whole file without logging
    anything, and the report was invisible for eight days while looking like a
    missing blob.
    """
    print("\n[6] Published summary conforms to the report-summary contract")
    from src.domains.sales import target_tracker_publish as tp
    from src.tools.api_payloads import ReportSummaryPayload

    model = _live_model()
    if model is None:
        print("  [SKIP] no committed scan")
        return
    payload = tp.summary_payload(model)
    contract = {"title", "generatedAt", "headline", "metrics", "sections"}

    check("key set is exactly the contract", set(payload) == contract,
          str(set(payload) ^ contract))
    check("the headline is under 'headline', not 'heading'",
          bool(str(payload.get("headline") or "").strip()) and "heading" not in payload)
    check("the detail is under 'sections', not 'points'",
          isinstance(payload.get("sections"), list) and "points" not in payload)
    check("metrics are present", isinstance(payload.get("metrics"), list) and payload["metrics"])
    check("it validates against the shared model",
          ReportSummaryPayload(**payload) is not None)

    tones = {"positive", "critical", "warning", "info", "teal"}
    check("every metric tone is a contract tone",
          all(m["tone"] in tones for m in payload["metrics"]))
    check("every section tone is a contract tone",
          all(s["tone"] in tones for s in payload["sections"]))
    check("every section has points",
          all(s["points"] for s in payload["sections"]))

    # The facts the contract has no field for must survive as prose, not vanish.
    prose = " ".join(pt for s in payload["sections"] for pt in s["points"])
    check("the as-at date survives in the prose", model["anchor"] in prose)
    if model.get("target_lag_days"):
        check("the gap to the latest sales is stated",
              str(model["target_lag_days"]) in prose and str(model["sold_through"]) in prose)
    check("the branch population is stated",
          all(b in prose for b in (model.get("population") or [])))
    check("a branch below target is named",
          all(b["name"] in prose for b in model["branches"] if b["mtd"]["band"] == "crit"))

    # History index: the app's fallback route, which did not exist at all.
    entry = tp.history_entry(model, payload, "guid-1", __import__("datetime").datetime.now())
    check("history entry carries the headline", entry["headline"] == payload["headline"])
    check("history entry carries grain and dataAsOf",
          entry["grain"] == "day" and entry["dataAsOf"] == model["anchor"])
    rows = tp.merge_index([], entry)
    check("a fresh index has one row labelled Latest",
          len(rows) == 1 and rows[0]["label"] == "Latest")
    rows = tp.merge_index(rows, entry)
    check("a same-day re-run does not duplicate the date", len(rows) == 1)
    check("a same-day re-run increments the run count", rows[0]["runsThatDay"] == 2)
    older = {**entry, "date": "2026-06-30", "dataAsOf": "2026-06-30"}
    rows = tp.merge_index(rows, older)
    check("older dates sort after the newest",
          [r["date"] for r in rows] == sorted([r["date"] for r in rows], reverse=True))
    check("only the newest row is labelled Latest",
          [r["label"] for r in rows].count("Latest") == 1)


def main() -> int:
    print("=" * 72)
    print("REPLAY: Target Tracker signals (P5.2 - target vs actual)")
    print("=" * 72)
    test_spine()
    test_live_scan()
    test_guards()
    test_mid_period()
    test_ranking()
    test_summary_contract()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
