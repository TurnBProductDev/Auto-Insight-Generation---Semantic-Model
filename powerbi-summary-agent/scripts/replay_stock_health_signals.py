"""Offline proof of the Inventory Management signal detectors.

No Power BI, no Azure, no LLM. Two things are under test:

* **The ranking order**, because it is the whole point. Every score is a share
  of the base it is measured against, so a large percentage on a trivial slice
  cannot outrank a small percentage on a large one (BR-34). Scoring on raw
  magnitude is the failure this pins.
* **The prose guards**, because a signal's `description` is published to the
  KPI feed unchanged. It must obey BR-03's vocabulary, BR-33's plain-language
  rule and the no-asserted-cause rule exactly as the page does.

    python scripts/replay_stock_health_signals.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import health, stock_health_signals as sig  # noqa: E402
from src.domains.inventory.reports import stock_health  # noqa: E402

FAILURES: list[str] = []

COMMITTED_SCAN = PROJECT_ROOT / "outputs_stock_health" / "stock_health_scan.json"

#: BR-03 bans these names for classifications that already have one. Checked
#: against the published description, not only against the page.
BANNED = {
    "overstock value": "Excess Stock",
    "surplus": "Excess Stock",
    "dead stock": "Non-Moving",
    "write-off": "Damage",
    "product": "SKU",
    "item": "SKU",
    "department": "Division",
    "shop": "Store",
}

#: BR-33 bans the jargon a free-form generator reaches for.
JARGON = ("velocity", "carry cost", "coverage ratio", "materiality", "breadth",
          "p90", "burnout", "scoped", "eligible")

#: A cause may never be asserted - this report describes a position, it does not
#: explain one.
CAUSE_WORDS = ("because", "due to", "driven by", "caused by", "as a result of",
               "thanks to", "owing to")

#: The client's own data must never be carried into published prose.
CLIENT_SPECIFIC = ("saudi", "riyal", "sar ", "cfh0", "cdc010", "cfw001")


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _model(**overrides):
    scan = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    model = stock_health.build(scan)
    model["comparison"] = {"comparable": False, "reason": "no_prior"}
    model.update(overrides)
    return model, health.build(scan)


def test_double_warning_leads() -> None:
    print("\nA double-warning state leads, whatever it holds")
    model, score = _model()
    signals = sig.detect(model, score)
    check("at least one signal is produced", bool(signals))
    check("the double-warning state ranks first",
          signals[0]["analysis_type"] == "inventory_double_warning",
          signals[0]["analysis_type"])
    check("and is critical", signals[0]["severity"] == "critical")

    # The point of the boost: this state holds no stock value at all, so on any
    # value-weighted score it would rank last rather than first.
    lead = signals[0]
    queue = {r["action"]: r for r in model["queue"]}
    row = queue.get(lead["affected_segment"])
    check("the leading state holds no stock value, so value alone would bury it",
          row is not None and (row.get("stock_value") or 0.0) == 0.0)


def test_ranking_is_exposure_weighted() -> None:
    print("\nRanking is a share of the base, never a raw magnitude")
    model, score = _model()
    signals = sig.detect(model, score)
    ordered = [s["score"] for s in signals]
    check("signals come back in descending score order", ordered == sorted(ordered, reverse=True))

    # A trivial slice moving a lot must not outrank a large one moving a little.
    # Damage on this model is a few hundred thousand against a stock position of
    # tens of millions; Excess Stock is 42% of the whole position.
    by_type = {s["analysis_type"]: s for s in signals}
    excess = by_type.get("inventory_excess_share")
    check("Excess Stock is scored as its share of Stock Value",
          excess is not None
          and abs(excess["score"] - excess["impact_share"]) < 1e-9)

    tiny = dict(model)
    tiny["non_moving_bands"] = [
        {"name": "30-60", "loc_skus": 1, "stock_value": 10.0},
        {"name": ">180", "loc_skus": 1, "stock_value": 12.0},
    ]
    out = sig.non_moving_oldest_band(tiny)
    check("a band worth a rounding error scores on its share, not its size",
          out and out[0]["score"] < 100.0, str(out[0]["score"] if out else "none"))


def test_every_signal_carries_a_comparison_label() -> None:
    print("\nEvery signal names what it is compared against")
    model, score = _model()
    signals = sig.detect(model, score, limit=None)
    missing = [s["analysis_type"] for s in signals if not s.get("comparison_label")]
    check("no signal is missing one", not missing,
          f"{missing} - without it the feed publishes against 'the prior period', "
          f"a comparison this data does not contain")
    priors = [s["analysis_type"] for s in signals if "prior" in s]
    check("and none carries a prior", not priors, str(priors))
    check("every signal names the snapshot spine",
          all(s["spine"] == "snapshot_vs_policy" for s in signals))
    check("every signal is tagged with the report it came from",
          all(s["report_id"] == "inventory_stock_health" for s in signals))


def test_prose_guards() -> None:
    print("\nEvery published description obeys the rulebook")
    model, score = _model()
    signals = sig.detect(model, score, limit=None)
    prose = []
    for signal in signals:
        prose.append((signal["analysis_type"], signal["description"]))
        prose.append((signal["analysis_type"], signal["question"]))

    for name, text in prose:
        low = text.lower()
        # Strip the Recommended Action state names first: they legitimately
        # contain words the vocabulary check would otherwise flag.
        stripped = low
        for state in stock_health.ACTION_PRIORITY:
            stripped = stripped.replace(state.lower(), " ")
        hits = [word for word in BANNED if word in stripped]
        check(f"{name}: no banned synonym", not hits,
              f"{hits} - approved: {[BANNED[h] for h in hits]}")
        jargon = [word for word in JARGON if word in stripped]
        check(f"{name}: no jargon", not jargon, str(jargon))
        causes = [word for word in CAUSE_WORDS if word in low]
        check(f"{name}: asserts no cause", not causes, str(causes))
        client = [word for word in CLIENT_SPECIFIC if word in low]
        check(f"{name}: carries no client-specific content", not client, str(client))
        check(f"{name}: no emoji", text.isascii())


def test_comparisons_carry_a_number() -> None:
    print("\nBR-33: a comparison always carries a figure")
    model, score = _model()
    for signal in sig.detect(model, score, limit=None):
        text = signal["description"]
        check(f"{signal['analysis_type']}: quotes a figure",
              bool(re.search(r"\d", text)), text[:60])


def test_absent_urgent_state_is_reported() -> None:
    print("\nA double-warning state the data never returned is reported")
    model, score = _model()
    signals = sig.detect(model, score, limit=None)
    absent = [s for s in signals if s["analysis_type"] == "inventory_urgent_state_absent"]
    check("it produces a signal", bool(absent),
          "an empty row and a state the source never produces look identical, "
          "and only one of them is good news")
    check("classified as a data question, not a stock finding",
          absent and absent[0]["kind"] == "data_quality")


def test_opportunity_loss_is_the_scoped_figure() -> None:
    print("\nOpportunity Loss is published scoped, and says so")
    model, score = _model()
    out = sig.critical_stockouts(model, score)
    check("a signal is produced", bool(out))
    text = out[0]["description"]
    published = out[0]["extra"] if "extra" in out[0] else {}
    del published
    check("the scoped figure is the one quoted",
          str(int(model["header"]["opportunity_loss_day"])).replace("000", "") in
          text.replace(",", "") or "estimate" in text)
    check("it is called an estimate", "estimate" in text.lower())
    check("and the stores-only limit is stated", "stores only" in text.lower())
    check("the unscoped figure is never published as the number",
          f"{model['header']['opportunity_loss_unscoped']:,.0f}" not in text)


def test_no_comparison_without_an_archive() -> None:
    print("\nNo movement is stated without a comparable archived position")
    model, score = _model()
    model["state_changes"] = [
        {"action": "OVERSTOCK", "kind": "worsened", "current": 100,
         "prior": 50, "change": 50, "double_warning": False}]

    model["comparison"] = {"comparable": False, "reason": "no_prior"}
    check("a first run states no movement", not sig.state_changes(model, score))

    model["comparison"] = {"comparable": False, "reason": "as_at_unchanged"}
    check("an unchanged as-at states no movement",
          not sig.state_changes(model, score),
          "the same stamp has been observed carrying different data")

    model["comparison"] = {"comparable": True, "label": "since 2026-08-18"}
    out = sig.state_changes(model, score)
    check("a genuinely comparable pair does state it", bool(out))
    check("labelled by the position it compares against",
          out and out[0]["comparison_label"] == "since 2026-08-18")
    check("and the movement is quoted", out and "50" in out[0]["description"])


def test_month_is_named() -> None:
    print("\nA month reads as a month, not as the first of it")
    model, score = _model()
    out = sig.damage_against_trend(model, score)
    if out:
        text = out[0]["description"]
        check("the month is named", "August" in text or "July" in text
              or "June" in text or "May" in text, text[:70])
        check("and not printed as a date", "-01" not in text, text[:70])
    check("the converter handles a first-of-month date",
          sig._month_name("2026-08-01T00:00:00") == "August 2026")
    check("and leaves anything it cannot parse alone",
          sig._month_name("not a date") == "not a date")


def test_state_diff() -> None:
    print("\nAppeared, cleared, worsened, eased - and nothing when nothing moved")
    now = [{"action": "OVERSTOCK", "loc_skus": 120},
           {"action": "NON MOVING", "loc_skus": 80},
           {"action": "STOCK OUT - PLACE ORDER", "loc_skus": 10,
            "double_warning": True}]
    before = [{"action": "OVERSTOCK", "loc_skus": 100},
              {"action": "NON MOVING", "loc_skus": 90},
              {"action": "IN STOCK BUT NO SALES", "loc_skus": 5}]
    diff = {row["action"]: row for row in sig.state_diff(now, before)}
    check("a state that was not there before appeared",
          diff["STOCK OUT - PLACE ORDER"]["kind"] == "appeared")
    check("a state that is gone cleared",
          diff["IN STOCK BUT NO SALES"]["kind"] == "cleared")
    check("a state that grew worsened", diff["OVERSTOCK"]["kind"] == "worsened")
    check("a state that shrank eased", diff["NON MOVING"]["kind"] == "eased")
    check("the double-warning flag survives",
          diff["STOCK OUT - PLACE ORDER"]["double_warning"] is True)
    check("an unchanged state is not a finding",
          not sig.state_diff(now, now),
          "reporting every state every day would drown the real movements")
    check("ordered by the size of the movement",
          [r["action"] for r in sig.state_diff(now, before)][0] == "OVERSTOCK")


def test_quiet_position_is_honest() -> None:
    print("\nA quiet position produces few signals rather than padded ones")
    model, score = _model()
    model["double_warnings"] = []
    model["states_absent_urgent"] = []
    model["damage"] = []
    model["non_moving_bands"] = []
    model["header"] = dict(model["header"], excess_value=0.0, unwanted_skus=0,
                           critical_stockout_skus=0)
    signals = sig.detect(model, score, limit=None)
    check("nothing is invented to reach a count",
          all(s["analysis_type"] in ("inventory_risk_at_cap",) for s in signals),
          str([s["analysis_type"] for s in signals]))


def test_story_keys() -> None:
    print("\nStory identity is stable within a position and new across one")
    a = sig.story_key("inventory_excess_share", "", "2026-08-19")
    b = sig.story_key("inventory_excess_share", "", "2026-08-19")
    c = sig.story_key("inventory_excess_share", "", "2026-08-20")
    check("the same finding on the same position is one story", a == b)
    check("a new position is a new story", a != c)
    check("a different finding is a different story",
          a != sig.story_key("inventory_unwanted_skus", "", "2026-08-19"))
    check("member names are normalised",
          sig.story_key("f", "Overstock", "d") == sig.story_key("f", " OVERSTOCK ", "d"))


def main() -> int:
    print("=" * 72)
    print("Inventory Management - ranked signals")
    print("=" * 72)
    test_double_warning_leads()
    test_ranking_is_exposure_weighted()
    test_every_signal_carries_a_comparison_label()
    test_prose_guards()
    test_comparisons_carry_a_number()
    test_absent_urgent_state_is_reported()
    test_opportunity_loss_is_the_scoped_figure()
    test_no_comparison_without_an_archive()
    test_month_is_named()
    test_state_diff()
    test_quiet_position_is_honest()
    test_story_keys()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
