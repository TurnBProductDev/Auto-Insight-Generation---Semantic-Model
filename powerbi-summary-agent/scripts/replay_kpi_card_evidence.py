"""Offline replay: the KPI card `evidence` block.

Publishes the workings behind a card - the measure, the window it covers, the
figures it was compared against, and the branches or products that account for
the movement. All of it is already computed to produce the card and was
discarded at publish time, which forced any consumer asked to EXPLAIN a card to
re-derive it from a different data source, with no way to reconcile the two.

Gated by ``ai_content_kpi_card_evidence`` (code default False), following the
same rollout discipline as ``ai_content_kpi_card_fields`` - see
replay_kpi_card_fields.py and docs/phase5-app-contract-change.md.

Three exit criteria:

1. **Flag off is byte-identical.** No `evidence` key, not even a null.
2. **Flag on publishes only what the signal actually carries.** A sub-field the
   signal cannot back is absent, never null and never guessed - a consumer must
   be able to tell "this signal has no baseline" from "the baseline was lost".
3. **It is workings, not conclusions.** No prose, no recommended action: those
   are on the card already, and an explanation grounded on someone else's
   conclusion is not an explanation.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import api_payloads  # noqa: E402

FAILURES: list[str] = []
WHEN = datetime(2026, 8, 25, 9, 15, tzinfo=timezone.utc)


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _text():
    return api_payloads._KpiCardText(
        signal_id="S1", category="Sales", description="Revenue fell in this area.",
        insight_title="Revenue fell", insight_summary="Revenue fell in this area.",
        insight_action="Review the area.",
    )


def _card(sig, *, evidence=False, extended=False, state=None, idx=1):
    return api_payloads._assemble_kpi_card(
        idx, sig, _text(), WHEN, report_id=None,
        extended_fields=extended, evidence_fields=evidence, state=state,
    )


# --- fixtures, shaped like the real domain signals -----------------------
def _wow_signal():
    """A week-over-week signal: the richest case, and the common one."""
    return {
        "id": "S3", "story_key": "wow:fashion", "affected_segment": "FASHION",
        "dimension": "category", "metric": "Net revenue",
        "impact_value": -45_900.0, "impact_share": 8.04, "kind": "business",
        "segment_members": ["ST2", "ST7", "ST1"],
        "decomposition": [{"driver": "qty", "volume_effect": -30_000.0,
                           "rate_effect": -15_900.0}],
        "description": "FASHION net revenue fell week over week.",
        "recent_week": {
            "window_mode": "calendar", "change_pct": -8.7,
            "week_start": "2026-08-11", "week_end": "2026-08-17",
            "previous": 525_900.0, "actual": 480_000.0,
        },
    }


def _bare_signal():
    """A signal carrying nothing but its headline: no window, no drivers."""
    return {
        "id": "S8", "story_key": "bare:x", "affected_segment": "",
        "impact_value": 1_000.0, "kind": "business",
        "description": "Something moved.",
    }


def _daily_incident_signal():
    """No recent_week; the window comes from the episode instead."""
    return {
        "id": "S4", "story_key": "daily:2026-08-20", "affected_segment": "ST9",
        "impact_value": -12_000.0, "kind": "business",
        "episode_start": "2026-08-20", "episode_end": "2026-08-20",
        "expected_total": 100_000.0, "actual_total": 88_000.0,
        "description": "ST9 revenue dipped on 2026-08-20.",
    }


# --- checks ---------------------------------------------------------------
def test_flag_off_is_byte_identical():
    off = _card(_wow_signal(), evidence=False)
    check("flag off: no evidence key at all", "evidence" not in off,
          f"keys={sorted(off)}")

    # And the rest of the card is untouched by the new code path.
    on = _card(_wow_signal(), evidence=True)
    check("flag on changes nothing else on the card",
          {k: v for k, v in on.items() if k != "evidence"} == off)


def test_evidence_carries_the_workings():
    ev = _card(_wow_signal(), evidence=True).get("evidence") or {}

    check("segment published", ev.get("segment") == "FASHION", str(ev))
    check("window mode published", (ev.get("window") or {}).get("mode") == "calendar", str(ev))
    check("window start published", (ev.get("window") or {}).get("start") == "2026-08-11", str(ev))
    check("window end published", (ev.get("window") or {}).get("end") == "2026-08-17", str(ev))
    check("actual published as a number", ev.get("actual") == 480_000.0, str(ev))
    check("previous published as a number", ev.get("previous") == 525_900.0, str(ev))
    check("share of change published", ev.get("shareOfChangePct") == 8.0, str(ev))
    decomp = ev.get("decomposition") or {}
    check("decomposition driver published", decomp.get("driver") == "qty", str(ev))
    check("volume effect published", decomp.get("volumeEffect") == -30_000.0, str(ev))
    check("rate effect published", decomp.get("rateEffect") == -15_900.0, str(ev))


def test_drivers_are_ranked_and_capped():
    sig = _wow_signal()
    ev = _card(sig, evidence=True).get("evidence") or {}
    drivers = ev.get("drivers") or []
    check("drivers published in signal order",
          [d["name"] for d in drivers] == ["ST2", "ST7", "ST1"], str(drivers))
    check("drivers ranked from 1", [d["rank"] for d in drivers] == [1, 2, 3], str(drivers))

    # This rides into an LLM prompt downstream; a tail of forty names is cost
    # without information.
    sig["segment_members"] = [f"ST{i}" for i in range(40)]
    capped = (_card(sig, evidence=True).get("evidence") or {}).get("drivers") or []
    check("drivers capped", len(capped) == api_payloads._MAX_EVIDENCE_DRIVERS,
          f"got {len(capped)}")


def test_episode_window_when_there_is_no_recent_week():
    ev = _card(_daily_incident_signal(), evidence=True).get("evidence") or {}
    window = ev.get("window") or {}
    check("episode start becomes the window start", window.get("start") == "2026-08-20", str(ev))
    check("episode end becomes the window end", window.get("end") == "2026-08-20", str(ev))
    check("expected_total published", ev.get("expected") == 100_000.0, str(ev))
    check("actual_total published", ev.get("actual") == 88_000.0, str(ev))


def test_absent_never_null():
    """A consumer must be able to tell 'no baseline' from 'baseline lost'."""
    ev = _card(_daily_incident_signal(), evidence=True).get("evidence") or {}
    check("no explicit nulls anywhere in evidence",
          all(v is not None for v in ev.values()), str(ev))
    check("a signal with no previous omits the key", "previous" not in ev, str(ev))
    check("a signal with no drivers omits the key", "drivers" not in ev, str(ev))

    # A signal with nothing to say at all publishes no block, rather than an
    # empty one - an empty object invites a consumer to conclude something.
    bare = _card(_bare_signal(), evidence=True)
    bare_ev = bare.get("evidence")
    check("a signal with nothing to say publishes no evidence block",
          bare_ev is None or set(bare_ev) <= {"measureFamily"}, str(bare_ev))


def test_workings_not_conclusions():
    ev = _card(_wow_signal(), evidence=True).get("evidence") or {}
    prose_keys = {"action", "summary", "description", "title", "recommendation"}
    check("no conclusion fields in evidence", not (set(ev) & prose_keys), str(sorted(ev)))


def test_schema_rejects_an_undeclared_field():
    """KpiCard is extra='forbid', so a typo must fail loudly at publish time
    rather than shipping a key no reader knows about."""
    try:
        api_payloads.KpiEvidence(**{"measureFamily": "revenue", "typo": 1})
    except Exception:
        check("evidence schema forbids unknown fields", True)
    else:
        check("evidence schema forbids unknown fields", False, "accepted a typo")


def test_flag_is_off_by_default():
    check("code default is off", api_payloads.kpi_card_evidence({}) is False)
    check("reads ai_content_kpi_card_evidence",
          api_payloads.kpi_card_evidence({"config": {"ai_content_kpi_card_evidence": True}}) is True)
    check("independent of the extended-tile flag",
          api_payloads.kpi_card_evidence({"config": {"ai_content_kpi_card_fields": True}}) is False)


def main() -> int:
    print("Replay: KPI card evidence block")
    print("=" * 72)
    test_flag_off_is_byte_identical()
    test_evidence_carries_the_workings()
    test_drivers_are_ranked_and_capped()
    test_episode_window_when_there_is_no_recent_week()
    test_absent_never_null()
    test_workings_not_conclusions()
    test_schema_rejects_an_undeclared_field()
    test_flag_is_off_by_default()
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
