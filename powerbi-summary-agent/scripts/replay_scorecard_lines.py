"""The Home scorecard lines - facts, checks and authoring. Offline.

    python scripts/replay_scorecard_lines.py

No auth, no network, no real model: the model is a stand-in that returns fixed
drafts, installed where `get_llm` is looked up, so every path the authoring
step can take is exercised - accepted, repaired, kept as code wrote it, and
never called at all.

What this pins, and why each one is here:

  * **Every fact is about the normal range, never the day before.** The Daily
    Sales rulebook compares a day only with past days like it. A fact kind for
    each situation is built from a hand-made history and named here.
  * **The code-written line passes the same checks as a model's.** Otherwise a
    strict check could reject the fallback and leave a card with nothing true
    to say.
  * **The checks catch a fluent wrong sentence.** A line can read well and
    still change the count of days, flip the direction, name a cause or quote
    money - each is a named rejection.
  * **A rejected line costs only itself.** One bad line is sent back once; a
    line that fails twice keeps its code-written sentence while the others keep
    the model's wording.
  * **The AI tier decides above the report's switch**, and `scorecard` in
    `narrated_code_slots` hands these lines back to code without a model call.
  * **A ratio's week is the ratio of the week's totals.** Averaging seven
    daily baskets gives a different number from the report's own arithmetic.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.sales import daily_sales_dashboard as dash  # noqa: E402
from src.domains.sales import scorecard_lines as sl  # noqa: E402

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    _failures.append(label)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _day(i: int, side: str | None, actual: float = 100.0, p50: float | None = 100.0) -> dict:
    return {"date": f"2026-08-{i + 1:02d}", "actual": actual, "p20": 90.0, "p50": p50,
            "p80": 110.0, "side": side, "sales": actual, "bills": 10.0}


def _history(sides: list, actuals: list | None = None) -> list[dict]:
    actuals = actuals or [100.0] * len(sides)
    return [_day(i, side, actual) for i, (side, actual) in enumerate(zip(sides, actuals))]


def _fact_for(sides: list, actuals: list | None = None) -> dict | None:
    return sl._band_fact("net_sales", "Net Sales", _history(sides, actuals))


def _target_model(attainments: list, anchor: str | None = None) -> dict:
    days = [{"date": f"2026-08-{i + 1:02d}", "actual": a * 10.0, "target": 1000.0,
             "attainment": a} for i, a in enumerate(attainments)]
    return {"anchor": anchor or days[-1]["date"], "days": days}


# ---------------------------------------------------------------------------
# facts
# ---------------------------------------------------------------------------
def test_daily_sales_facts() -> None:
    print("\n=== each Daily Sales situation reads as its own fact ===")
    below = "below"
    inside = "inside"
    above = "above"

    f = _fact_for([inside, inside, below, below, below])
    check("three days below the band is a run of 3",
          f["kind"] == "run_below" and f["numbers"] == ["3"] and f["tone"] == "critical",
          str(f))
    f = _fact_for([below, above, above])
    check("two days above the band is a good run of 2",
          f["kind"] == "run_above" and f["numbers"] == ["2"] and f["tone"] == "positive", str(f))
    f = _fact_for([below] + [inside] * 7 + [below])
    check("a day below after a week and more inside is a first in 8 days",
          f["kind"] == "first_below" and f["numbers"] == ["8"], str(f))
    f = _fact_for([below, inside, inside, inside, below])
    check("a day below with another close behind it is counted, not called a first",
          f["kind"] == "often_below" and f["numbers"] == ["2", "5"]
          and f["statement"] == "Below its normal range on 2 of the last 5 days", str(f))
    f = _fact_for([inside, inside, inside, above])
    check("a first day above with none before counts the whole window",
          f["kind"] == "first_above" and f["numbers"] == ["4"] and f["tone"] == "positive",
          str(f))
    f = _fact_for([below])
    check("a single day below is stated with no count",
          f["kind"] == "below_only" and f["numbers"] == [], str(f))
    f = _fact_for([below, below, below, inside])
    check("back inside after three days below is a good turn",
          f["kind"] == "back_from_below" and f["numbers"] == ["3"] and f["tone"] == "positive",
          str(f))
    f = _fact_for([above, above, inside])
    check("back inside after two days above is neutral, not bad news",
          f["kind"] == "back_from_above" and f["tone"] == "info", str(f))
    f = _fact_for([inside] * 9, [101, 102, 99, 104, 105, 98, 103, 97, 106])
    check("inside the band reads as days against the benchmark, over the last 7",
          f["kind"] == "count_above" and f["numbers"] == ["4", "7"] and f["tone"] == "info",
          str(f))
    f = _fact_for([inside] * 7, [99, 98, 101, 97, 96, 95, 102])
    check("more days under the benchmark reads as a count below",
          f["kind"] == "count_below" and f["numbers"] == ["5", "7"], str(f))
    f = _fact_for([inside])
    check("one day inside, with no history, is stated plainly",
          f["kind"] == "inside_only" and f["numbers"] == [], str(f))
    check("no history, no fact", sl._band_fact("bills", "Bills", []) is None)

    no_bench = [dict(d, p50=None, side=None) for d in _history([None, None, None])]
    check("no band and no benchmark, no fact",
          sl._band_fact("margin", "Margin", no_bench) is None)

    page = {"scorecard": {"net_sales": {"history": _history([below, below])},
                          "margin": {"history": _history([inside])}}}
    facts = sl.daily_sales_facts(page)
    check("one fact per measure with history, in scorecard order",
          [f["key"] for f in facts] == ["net_sales", "margin"], str([f["key"] for f in facts]))


def test_target_facts() -> None:
    print("\n=== the target card's fact ===")
    f = sl.target_tracker_facts(_target_model([101, 99, 95, 90]))[0]
    check("three days short of target is a run of 3",
          f["kind"] == "target_run_below" and f["numbers"] == ["3"] and f["tone"] == "critical",
          str(f))
    f = sl.target_tracker_facts(_target_model([101, 102, 103, 95]))[0]
    check("a first miss with none before counts the whole month so far",
          f["kind"] == "target_first_below" and f["numbers"] == ["4"], str(f))
    f = sl.target_tracker_facts(_target_model([95, 101, 102, 94]))[0]
    check("a miss with another close behind it is counted, not called a first",
          f["kind"] == "target_often_below" and f["numbers"] == ["2", "4"], str(f))
    f = sl.target_tracker_facts(_target_model([95, 90, 88, 101]))[0]
    check("a hit after three misses is back on target",
          f["kind"] == "target_back" and f["numbers"] == ["3"] and f["tone"] == "positive",
          str(f))
    f = sl.target_tracker_facts(_target_model([101, 95, 102, 103]))[0]
    check("otherwise it counts the days that reached target",
          f["kind"] == "target_count" and f["numbers"] == ["3", "4"] and f["tone"] == "positive",
          str(f))
    f = sl.target_tracker_facts(_target_model([90, 101, 92, 94, 91, 95, 105, 93, 102]))[0]
    check("a count over the last 7 with most days short reads as bad",
          f["kind"] == "target_count" and f["numbers"] == ["2", "7"] and f["tone"] == "critical",
          str(f))
    beyond = _target_model([101, 102, 90, 80], anchor="2026-08-02")
    f = sl.target_tracker_facts(beyond)[0]
    check("days past the anchor are not read", f["kind"] == "target_count"
          and f["numbers"] == ["2", "2"], str(f))
    unset = _target_model([101, 95])
    unset["days"].append({"date": "2026-08-03", "actual": 5.0, "target": 0.0, "attainment": None})
    unset["anchor"] = "2026-08-03"
    f = sl.target_tracker_facts(unset)[0]
    check("a day with no target is left out rather than read as a miss",
          f["kind"] == "target_first_below", str(f))
    check("no days, no fact", sl.target_tracker_facts({"anchor": "2026-08-01", "days": []}) == [])


# ---------------------------------------------------------------------------
# the code-written line must pass its own checks
# ---------------------------------------------------------------------------
def test_code_lines_pass_their_own_checks() -> None:
    print("\n=== every code-written line passes the checks a model's line must pass ===")
    b, i, a = "below", "inside", "above"
    facts = [f for f in (
        _fact_for([i, b, b, b]), _fact_for([b, a, a]), _fact_for([b, i, i, b]),
        _fact_for([i, i, a]), _fact_for([b]), _fact_for([a]), _fact_for([b, b, i]),
        _fact_for([a, a, i]), _fact_for([i] * 7, [101, 99, 102, 98, 103, 97, 104]),
        _fact_for([i] * 7, [99, 98, 97, 101, 96, 95, 102]), _fact_for([i]),
        _fact_for([b] * 14),
    ) if f]
    for attainments in ([101, 99, 95, 90], [101, 102, 103, 95], [95, 90, 88, 101],
                        [101, 95, 102, 103], [95], [90, 101, 92, 94, 105, 91, 93, 102],
                        [95, 101, 102, 94]):
        facts += sl.target_tracker_facts(_target_model(attainments))
    failing = {f["statement"]: sl.validate_line(f["statement"], f) for f in facts}
    failing = {k: v for k, v in failing.items() if v}
    check(f"all {len(facts)} code-written lines pass", not failing, str(failing))
    check("every code-written line fits the tile",
          all(len(f["statement"]) <= sl.MAX_CHARS for f in facts))
    check("no code-written line compares with the day before",
          not [f for f in facts if any(w in f["statement"].lower()
                                       for w in ("yesterday", "previous day", "day before"))])


# ---------------------------------------------------------------------------
# the checks
# ---------------------------------------------------------------------------
def test_checks_catch_a_fluent_wrong_line() -> None:
    print("\n=== the checks catch a line that reads well and says the wrong thing ===")
    run = _fact_for(["inside", "below", "below", "below"])      # below, 3 days
    count = _fact_for(["inside"] * 7, [101, 99, 102, 98, 103, 97, 104])   # above, 4 of 7
    back = sl.target_tracker_facts(_target_model([95, 90, 88, 101]))[0]

    def rejects(label: str, text: str, fact: dict, needle: str) -> None:
        errors = sl.validate_line(text, fact)
        check(label, any(needle in e for e in errors), f"{text!r} -> {errors}")

    check("a plain rewrite passes",
          sl.validate_line("Below the normal range for 3 days running", run) == [],
          str(sl.validate_line("Below the normal range for 3 days running", run)))
    check("'Fewer bills than usual' is a below direction",
          sl.validate_line("Fewer bills than usual for 3 days running", run) == [],
          str(sl.validate_line("Fewer bills than usual for 3 days running", run)))
    check("a count rewritten plainly passes",
          sl.validate_line("Above the usual level on 4 of the last 7 days", count) == [])
    check("back on target, reworded, passes",
          sl.validate_line("Back on target after 3 days short of it", back) == [],
          str(sl.validate_line("Back on target after 3 days short of it", back)))

    rejects("a different count of days", "Below the normal range for 4 days running", run,
            "'4' is not a figure")
    rejects("a count written as a word", "Below the normal range for four days running", run,
            "'four' is not a figure")
    rejects("an ordinal that is not the fact", "Below the normal range for the second day", run,
            "'second' is not a figure")
    rejects("the opposite direction", "Above the normal range for 3 days running", run,
            "says the opposite")
    rejects("no direction at all", "Sales held steady for 3 days", run,
            "does not say the fact's direction")
    rejects("a cause", "Below the normal range for 3 days because of the weather", run,
            "claims a cause")
    rejects("a forecast", "Sales will stay below the normal range for 3 days", run,
            "is a forecast")
    rejects("last year", "Below last year for 3 days", run, "no prior-year figure")
    rejects("jargon", "Below the P20 floor for 3 days", run, "jargon")
    rejects("the band by name", "Below its band for 3 days", run, "jargon")
    rejects("people for Bills", "Fewer customers than usual for 3 days", run,
            "Bills counts completed sales")
    rejects("the day before", "Below the normal range for 3 days, lower than yesterday", run,
            "say what the days show")
    rejects("a percentage", "Below the normal range for 3 days, 9% under", run,
            "quotes a percentage")
    rejects("money", "Below the normal range for 3 days at 69.4K", run,
            "'69.4' is not a figure")
    rejects("two sentences", "Below the normal range. That makes 3 days", run,
            "more than one sentence")
    rejects("too long", "Below the normal range for 3 days in a row, which is a longer run "
            "than usual", run, "characters")
    rejects("an emoji", "Below the normal range for 3 days \U0001F4C9", run, "emoji")
    rejects("an empty line", "", run, "empty")
    rejects("a count that is not the fact", "Above the usual level on 5 of the last 7 days",
            count, "'5' is not a figure")
    rejects("still below is not back", "Still below target after 3 days", back,
            "does not say the fact's direction")


# ---------------------------------------------------------------------------
# authoring, with a stand-in model
# ---------------------------------------------------------------------------
class _StandIn:
    """Returns fixed drafts in order; a draft that is an exception is raised."""

    def __init__(self, drafts: list):
        self.drafts = list(drafts)
        self.calls = 0
        self.messages: list = []

    def invoke(self, messages):
        self.calls += 1
        self.messages.append(list(messages))
        draft = self.drafts.pop(0)
        if isinstance(draft, Exception):
            raise draft
        return sl.ScorecardLines(lines=[sl.ScorecardLine(key=k, text=t)
                                        for k, t in draft.items()])


def _with_model(stand_in: _StandIn, run):
    from src.tools import llm as llm_module

    asked: dict = {}
    original = llm_module.get_llm

    def factory(state, structured_schema=None):
        asked["schema"] = structured_schema
        asked["state"] = state
        return stand_in

    llm_module.get_llm = factory
    try:
        return run(), asked
    finally:
        llm_module.get_llm = original


def test_authoring() -> None:
    print("\n=== authoring: accepted, repaired, kept, or never asked ===")
    facts = [_fact_for(["inside", "below", "below", "below"]),
             sl._band_fact("margin", "Margin", _history(["below", "above", "above"]))]
    good = {"net_sales": "Below the normal range for 3 days running",
            "margin": "Above the normal range for 2 days running."}
    narrated = {"report_ai_tier": "narrated"}

    stand_in = _StandIn([good])
    lines, asked = _with_model(stand_in, lambda: sl.author(facts, narrated, log=lambda *_: None))
    check("the narrated tier asks the model once and keeps a clean draft",
          stand_in.calls == 1 and all(v["mode"] == "llm" for v in lines.values()), str(lines))
    check("the trailing full stop is dropped, like the code-written lines",
          lines["margin"]["text"] == "Above the normal range for 2 days running")
    check("the tone comes from the fact, not from the model",
          lines["net_sales"]["tone"] == "critical" and lines["margin"]["tone"] == "positive")
    check("the model is asked for the lines schema, with a small output budget",
          asked.get("schema") is sl.ScorecardLines
          and int(asked["state"]["max_tokens"]) <= 800, str(asked))
    prompt = stand_in.messages[0][1]["content"]
    check("the model is told each card's fact and the numbers it may use",
          "net_sales" in prompt and "numbers you may use: 3" in prompt, prompt)

    stand_in = _StandIn([{**good, "net_sales": "Below the normal range for 4 days running"}, good])
    lines, _ = _with_model(stand_in, lambda: sl.author(facts, narrated, log=lambda *_: None))
    repair = stand_in.messages[1][-1]["content"] if stand_in.calls == 2 else ""
    check("a rejected line is sent back once, with its reason",
          stand_in.calls == 2 and "net_sales" in repair and "'4'" in repair, repair)
    check("...and the repaired line is used",
          lines["net_sales"]["mode"] == "llm"
          and lines["net_sales"]["text"] == good["net_sales"])

    bad = {**good, "net_sales": "Sales fell because of the weather"}
    stand_in = _StandIn([bad, bad])
    lines, _ = _with_model(stand_in, lambda: sl.author(facts, narrated, log=lambda *_: None))
    check("a line that fails twice keeps its code-written sentence",
          lines["net_sales"] == {"text": facts[0]["statement"], "tone": "critical",
                                 "mode": "deterministic"}, str(lines))
    check("...while the other card keeps the model's wording",
          lines["margin"]["mode"] == "llm")

    stand_in = _StandIn([{"margin": good["margin"]}, {"margin": good["margin"]}])
    lines, _ = _with_model(stand_in, lambda: sl.author(facts, narrated, log=lambda *_: None))
    check("a card the model left out keeps its code-written line",
          lines["net_sales"]["mode"] == "deterministic" and lines["margin"]["mode"] == "llm")

    stand_in = _StandIn([RuntimeError("the endpoint is down")])
    lines, _ = _with_model(stand_in, lambda: sl.author(facts, narrated, log=lambda *_: None))
    check("a failed call keeps every code-written line",
          lines == sl.deterministic(facts), str(lines))

    for label, cfg, flag in (
        ("the deterministic tier never asks the model", {"report_ai_tier": "deterministic"},
         True),
        ("the investigated tier asks only when the report's switch is on", {}, False),
        ("'scorecard' in narrated_code_slots keeps code wording without a call",
         {"report_ai_tier": "narrated", "narrated_code_slots": ["scorecard"]}, True),
    ):
        stand_in = _StandIn([good])
        lines, _ = _with_model(stand_in, lambda: sl.author(facts, cfg, flag=flag,
                                                           log=lambda *_: None))
        check(label, stand_in.calls == 0 and lines == sl.deterministic(facts), str(lines))

    stand_in = _StandIn([good])
    lines, _ = _with_model(stand_in, lambda: sl.author(facts, {}, flag=True,
                                                       log=lambda *_: None))
    check("...and does ask when it is on", stand_in.calls == 1 and lines["net_sales"]["mode"] == "llm")

    check("no facts, no call and no lines", sl.author([], narrated) == {})


# ---------------------------------------------------------------------------
# the figures behind the tile
# ---------------------------------------------------------------------------
def test_window_figures_and_change() -> None:
    print("\n=== a ratio's week is the ratio of the week's totals ===")
    history = [
        {"date": "2026-08-01", "actual": 10.0, "sales": 100.0, "bills": 10.0},
        {"date": "2026-08-02", "actual": 6.0, "sales": 300.0, "bills": 50.0},
    ]
    basket = dash._window_figure("basket_value", history)
    check("Basket Value over the days is total sales over total bills (6.67, not 8.00)",
          abs(basket - 400.0 / 60.0) < 1e-9, str(basket))
    margins = [dict(history[0], actual=10.0), dict(history[1], actual=30.0)]
    margin = dash._window_figure("margin", margins)
    check("Margin over the days is weighted by sales (25.0, not 20.0)",
          abs(margin - 25.0) < 1e-9, str(margin))
    check("Net Sales over the days is the plain average",
          dash._window_figure("net_sales", [dict(d, actual=d["sales"]) for d in history]) == 200.0)
    check("one day is not a window", dash._window_figure("bills", history[:1]) is None)

    # A strong weekly shape, as the live model has: a Friday sells about
    # three times a Sunday. The week has to be read against the week's own
    # benchmarks, or it reads as far up when it ran slightly up.
    week = [{"date": f"2026-09-{7 + i:02d}", "actual": a, "p50": b, "sales": a, "bills": 10.0,
             "sales_p50": b, "bills_p50": 10.0}
            for i, (a, b) in enumerate(zip([120, 114, 113, 189, 338, 127, 111],
                                           [146, 114, 120, 174, 310, 130, 113]))]
    figure = dash._window_figure("net_sales", week)
    bench = dash._window_benchmark("net_sales", week)
    check("the week's benchmark is the average of the same days' own benchmarks",
          abs(bench - sum(d["p50"] for d in week) / 7) < 1e-9, str(bench))
    check("...so the week reads level with it, where the day's benchmark said 40% up",
          abs(figure / bench - 1) < 0.02 and figure / week[-1]["p50"] - 1 > 0.35,
          f"{figure / bench - 1:.3f} vs {figure / week[-1]['p50'] - 1:.3f}")
    ratio_week = [{"p50": 10.0, "sales_p50": 100.0, "bills_p50": 10.0},
                  {"p50": 6.0, "sales_p50": 300.0, "bills_p50": 50.0}]
    check("Basket Value's week benchmark is benchmark sales over benchmark bills",
          abs(dash._window_benchmark("basket_value", ratio_week) - 400.0 / 60.0) < 1e-9)
    check("Margin's week benchmark is weighted by benchmark sales",
          abs(dash._window_benchmark("margin", [dict(ratio_week[0], p50=10.0),
                                                 dict(ratio_week[1], p50=30.0)]) - 25.0) < 1e-9)
    check("a day with no benchmark leaves the week without one",
          dash._window_benchmark("bills", [dict(week[0], p50=None)] + week[1:]) is None)

    delta = dash._scorecard_delta("net_sales", {"actual": 98.1, "p50": 100.0})
    check("Net Sales moves in percent, unsigned, with its direction",
          delta == {"delta": "1.9%", "goodDirection": "up", "deltaDirection": "down"}, str(delta))
    delta = dash._scorecard_delta("margin", {"actual": 22.0, "p50": 21.21})
    check("Margin moves in points",
          delta == {"delta": "0.79 pts", "goodDirection": "up", "deltaDirection": "up"},
          str(delta))
    delta = dash._scorecard_delta("bills", {"actual": 100.0, "p50": 100.02})
    check("a change that rounds to nothing has no arrow",
          delta.get("delta") == "0.0%" and "deltaDirection" not in delta, str(delta))
    check("no benchmark, no change", dash._scorecard_delta("bills", {"actual": 5.0}) == {})


def main() -> int:
    test_daily_sales_facts()
    test_target_facts()
    test_code_lines_pass_their_own_checks()
    test_checks_catch_a_fluent_wrong_line()
    test_authoring()
    test_window_figures_and_change()

    print()
    if _failures:
        print(f"FAILED ({len(_failures)}):")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("All scorecard line replay checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
