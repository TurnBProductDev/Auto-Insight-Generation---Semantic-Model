"""Offline proof of the Inventory Management prose validator.

No LLM is called. Drafts are constructed by hand, one per rejection reason, so
every rule the validator claims to enforce is a named test rather than a line of
code nobody has exercised.

The two things that must both hold:

* **a clean draft passes**, and
* **the deterministic draft passes**, so strict validation can never dead-end -
  if it could, a rejected LLM draft would leave the report with no prose at all.

    python scripts/replay_stock_health_author.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import health, money  # noqa: E402
from src.domains.inventory import stock_health_author as author  # noqa: E402
from src.domains.inventory.reports import stock_health  # noqa: E402

FAILURES: list[str] = []
COMMITTED_SCAN = PROJECT_ROOT / "outputs_stock_health" / "stock_health_scan.json"


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _fixture(comparable: bool = False):
    scan = json.loads(COMMITTED_SCAN.read_text(encoding="utf-8"))
    model = stock_health.build(scan)
    model["comparison"] = ({"comparable": True, "label": "since 2026-08-11"}
                           if comparable else
                           {"comparable": False, "reason": "no_prior"})
    return model, health.build(scan)


def _clean(model, score) -> dict:
    return author.deterministic(model, score)


def rejects(label: str, model, score, slot: str, text: str, expect: str) -> None:
    """A draft differing from the clean one in exactly one slot must be rejected."""
    draft = dict(_clean(model, score))
    draft[slot] = text
    errors = author.validate(draft, model, score)
    hit = [e for e in errors if expect.lower() in e.lower()]
    check(label, bool(hit), f"errors were: {errors[:3]}")


def test_clean_and_fallback_pass() -> None:
    print("\nA clean draft passes, and so does the deterministic one")
    model, score = _fixture()
    money.use("SAR")
    fallback = author.deterministic(model, score)
    errors = author.validate(fallback, model, score)
    check("the deterministic draft passes its own validator", not errors,
          f"{errors[:4]} - if it did not, a rejected LLM draft would leave the "
          f"report with no prose at all")
    check("it fills every slot", all(fallback.get(s) for s in author.SLOTS))
    check("and is labelled as deterministic",
          fallback["authoring_mode"] == "deterministic")

    live = next(r for r in model["queue"] if r["loc_skus"])
    hand = dict(fallback)
    hand["headline"] = (f"{int(live['loc_skus']):,} Loc-SKUs are in "
                        f"{live['action']}.")
    check("a hand-written clean draft passes",
          not author.validate(hand, model, score),
          str(author.validate(hand, model, score)[:3]))


def test_figure_grounding() -> None:
    print("\nEvery figure must exist in the report")
    model, score = _fixture()
    rejects("a figure not in the report is rejected", model, score,
            "headline", "99,999,123 Loc-SKUs need attention.", "not in the report")
    rejects("more than one decimal place is rejected", model, score,
            "headline", "Excess Stock is 42.24657284% of Stock Value.", "decimal")
    check("an abbreviated money figure keeps two places",
          not [e for e in author.validate(
              dict(_clean(model, score),
                   headline="SAR 5.90M is held above the agreed cover."),
              model, score) if "decimal" in e],
          "SAR 5.90M is the page's own form")
    rejects("a comparison with no figure is rejected", model, score,
            "excess_note", "Excess Stock is more than we would like.",
            "without quoting a figure")


def test_vocabulary() -> None:
    print("\nBR-03's approved names, in both directions")
    model, score = _fixture()
    live = next(r for r in model["queue"] if r["loc_skus"])
    for word, approved in (("surplus", "Excess Stock"), ("dead stock", "Non-Moving"),
                           ("products", "SKUs"), ("departments", "Divisions"),
                           ("shops", "Stores")):
        rejects(f"\"{word}\" is rejected in favour of {approved}", model, score,
                "excess_note", f"There is too much {word} in the estate today.",
                approved)
    rejects("BR-33 jargon is rejected", model, score,
            "narrative", "Stock velocity is low across the estate.", "velocity")
    check("a Recommended Action state name is never mistaken for a banned word",
          not author.validate(
              dict(_clean(model, score),
                   queue_note=f"{live['action']} covers "
                              f"{int(live['loc_skus']):,} Loc-SKUs."),
              model, score),
          "state names legitimately contain words banned as synonyms elsewhere")


def test_wrong_currency() -> None:
    print("\nA currency other than the configured one is rejected")
    model, score = _fixture()
    money.use("USD")
    rejects("a figure quoted in another currency is rejected", model, score,
            "excess_note", "SAR 5.9M is held above the agreed cover.",
            "published in USD")
    money.use("SAR")
    check("and the configured currency itself is fine",
          not [e for e in author.validate(
              dict(_clean(model, score),
                   excess_note="SAR 21.13M is held above the agreed cover."),
              model, score) if "currency" in e or "client-specific" in e])


def test_no_asserted_cause() -> None:
    print("\nA cause may never be asserted")
    model, score = _fixture()
    for word in ("because", "due to", "driven by"):
        rejects(f"\"{word}\" is rejected", model, score, "narrative",
                f"Excess Stock is high {word} slow demand.", "cause")


def test_no_fabricated_history() -> None:
    print("\nNo comparison without an archived position to compare against")
    model, score = _fixture(comparable=False)
    for word in ("up from", "since yesterday", "last month"):
        rejects(f"\"{word}\" is rejected when there is no prior", model, score,
                "narrative", f"Excess Stock is 42.2% of Stock Value, {word} before.",
                "earlier position")

    ok_model, ok_score = _fixture(comparable=True)
    draft = dict(_clean(ok_model, ok_score))
    draft["narrative"] = ("102,371 Loc-SKUs need action, up from 102,000 at the "
                          "last position.")
    errors = [e for e in author.validate(draft, ok_model, ok_score)
              if "earlier position" in e]
    check("but allowed once the archive says the two are comparable", not errors,
          str(errors))


def test_no_forecasting_or_emojis() -> None:
    print("\nNo forecasting, no emojis")
    model, score = _fixture()
    rejects("a forecast is rejected", model, score, "narrative",
            "Excess Stock will be 30% of Stock Value by year end.", "forecast")
    rejects("an emoji is rejected", model, score, "headline",
            "17,806 Loc-SKUs need attention ⚠", "non-ASCII")


def test_client_specific_content() -> None:
    print("\nThe client's own data never reaches published prose")
    model, score = _fixture()
    for word in ("Saudi", "riyal", "CFH017"):
        rejects(f"\"{word}\" is rejected", model, score, "narrative",
                f"Stock across {word} is above cover.", "client-specific")


def test_assertions_beyond_grounding() -> None:
    print("\nClaims the model can prove false, whatever figures were quoted")
    model, score = _fixture()
    needing = int(model["header"]["exception_rows"])
    check("the fixture genuinely has lines needing action", needing > 0)

    rejects("\"nothing needs action\" is rejected when lines do", model, score,
            "headline", "Nothing needs action in the estate today.",
            "claims nothing needs action")

    # The trap: a state that genuinely has no rows, reported as a live problem.
    absent = model["states_absent_urgent"]
    check("the fixture has an urgent state with no rows", bool(absent))
    rejects("a state with no rows cannot be reported as having some", model, score,
            "queue_note", f"{absent[0]} covers 4,200 Loc-SKUs today.",
            "returned none")

    live = next(r for r in model["queue"] if r["loc_skus"])
    rejects("a state with rows cannot be reported as empty", model, score,
            "queue_note", f"There are no Loc-SKUs in {live['action']} today.",
            "has no lines")


def test_empty_slots() -> None:
    print("\nThe two required slots may not be empty")
    model, score = _fixture()
    for slot in ("headline", "narrative"):
        draft = dict(_clean(model, score))
        draft[slot] = ""
        check(f"an empty {slot} is rejected",
              any("must not be empty" in e for e in author.validate(draft, model, score)))
    draft = dict(_clean(model, score))
    draft["queue_note"] = ""
    check("but an optional slot may be left empty",
          not author.validate(draft, model, score))


def test_authoring_off_returns_the_fallback() -> None:
    print("\nWith authoring off, or on failure, the deterministic draft is used")
    model, score = _fixture()
    out = author.author(model, {}, score, log=lambda *_: None)
    check("authoring off returns the deterministic draft",
          out["authoring_mode"] == "deterministic")
    check("and it passes validation", not author.validate(out, model, score))

    # An LLM that raises must not cost the report its prose.
    broken = {"inventory_llm_authoring_enabled": True, "ai_provider": "nope"}
    out = author.author(model, broken, score, log=lambda *_: None)
    check("a failed LLM call still returns usable prose",
          out["authoring_mode"] == "deterministic" and bool(out["headline"]))


def test_context_offers_rounded_figures() -> None:
    print("\nThe prompt offers ready-rounded figures, not raw floats")
    model, score = _fixture()
    text = author.context(model, score)
    check("it names the position date", str(model["as_at"]) in text)
    check("it forbids comparison when there is no prior",
          "No earlier position" in text or "NO earlier position" in text)
    quotes = author.quotable(model, score)
    check("every offered figure would itself pass the figure check",
          all(not [e for e in author.validate(
              dict(_clean(model, score), excess_note=q), model, score)
              if "not in the report" in e]
              for q in quotes),
          "offering a figure the validator then rejects is the trap this avoids")


def main() -> int:
    print("=" * 72)
    print("Inventory Management - prose validation")
    print("=" * 72)
    money.use("SAR")
    test_clean_and_fallback_pass()
    test_figure_grounding()
    test_vocabulary()
    test_wrong_currency()
    test_no_asserted_cause()
    test_no_fabricated_history()
    test_no_forecasting_or_emojis()
    test_client_specific_content()
    test_assertions_beyond_grounding()
    test_empty_slots()
    test_authoring_off_returns_the_fallback()
    test_context_offers_rounded_figures()
    money.reset()
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
