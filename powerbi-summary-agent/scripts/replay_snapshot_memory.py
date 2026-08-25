"""Cross-run novelty for single-snapshot inventory reports. Offline.

    python scripts/replay_snapshot_memory.py

No auth, no LLM, no network - a temp directory stands in for the store.
Proves the properties that matter for a feature deciding what a live client
sees repeated or not: a genuinely new finding is always reported; an
unchanged one is suppressed; a member that quietly clears is still announced
as good news; and the persisted store survives a save/reload round trip.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import snapshot_memory as mem  # noqa: E402

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


def _signal(kind: str, role: str, member: str, *, severity="critical",
           impact_value=100_000.0, rate_gap=10.0) -> dict:
    return {
        "candidate_id": f"{kind}:{role}:{member}", "analysis_type": kind,
        "dimension": role, "affected_segment": member, "severity": severity,
        "impact_value": impact_value, "rate_gap_pct_points": rate_gap,
        "description": f"{member} is flagged", "comparison_label": "test",
    }


def test_first_sighting_always_reports() -> None:
    print("\n=== a finding never seen before is always reported ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        result = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS")],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-24")
        check("one signal in, one reportable out", len(result["reportable"]) == 1)
        check("it carries a novelty verdict",
              result["reportable"][0]["novelty"]["kind"] == "first_seen")
        check("no clearances on a first run", result["cleared"] == [])
    finally:
        shutil.rmtree(tmp)


def test_unchanged_is_suppressed_then_escalation_reopens_it() -> None:
    print("\n=== unchanged is suppressed; a material worsening reopens it ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        day1 = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS", impact_value=100_000.0)],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-20")
        mem.commit(day1)

        day2 = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS", impact_value=101_000.0)],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-21")
        check("a ~1% drift the next day is suppressed", day2["reportable"] == [],
              day2["reportable"])
        mem.commit(day2)

        day3 = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS", impact_value=200_000.0)],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-22")
        check("a doubling of exposure is reported as an escalation",
              len(day3["reportable"]) == 1
              and day3["reportable"][0]["novelty"]["kind"] == "escalated",
              day3["reportable"])
    finally:
        shutil.rmtree(tmp)


def test_clearance_is_announced_as_good_news() -> None:
    print("\n=== a member that drops out of the scan while flagged clears ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        day1 = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS")],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-20")
        mem.commit(day1)

        # OVERSEAS no longer appears at all - it fell below the hotspot threshold.
        day2 = mem.filter_signals(
            [], report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-21")
        check("no live signal, but one synthetic clearance", len(day2["cleared"]) == 1,
              day2["cleared"])
        cleared = day2["cleared"][0]
        check("it names the member", "OVERSEAS" in cleared["description"], cleared["description"])
        check("it is graded positive, not a problem", cleared["severity"] == "positive")

        mem.commit(day2)
        day3 = mem.filter_signals(
            [], report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-22")
        check("an already-cleared member is not re-announced every day",
              day3["cleared"] == [], day3["cleared"])
    finally:
        shutil.rmtree(tmp)


def test_two_different_members_do_not_collide() -> None:
    print("\n=== distinct members get distinct identities ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        result = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS"),
             _signal("ageing_rate_hotspot", "location", "WH1")],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-20")
        check("both are reported on first sighting", len(result["reportable"]) == 2)
        keys = {mem.identity_key("inventory_ageing", "ageing_rate_hotspot", "location", m)
               for m in ("OVERSEAS", "WH1")}
        check("their identity keys differ", len(keys) == 2)
    finally:
        shutil.rmtree(tmp)


def test_anchor_independence() -> None:
    print("\n=== identity excludes the observation date, unlike story_key ===")
    key_a = mem.identity_key("inventory_ageing", "ageing_rate_hotspot", "location", "OVERSEAS")
    key_b = mem.identity_key("inventory_ageing", "ageing_rate_hotspot", "location", "OVERSEAS")
    check("the same (report, kind, role, member) is the same key regardless of "
         "when it is computed - state_novelty.judge could never recognise "
         "'still the same problem' otherwise", key_a == key_b)
    check("case/whitespace on the member do not mint a new identity",
          mem.identity_key("inventory_ageing", "ageing_rate_hotspot", "location", " overseas ")
          == key_a)


def test_persistence_round_trips() -> None:
    print("\n=== the store survives a save/reload cycle ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        path = mem.store_path(tmp, "inventory_ageing", "ds1")
        check("no store yet -> load() is empty, not an error", mem.load(path) == {})
        result = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS")],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-20")
        mem.commit(result)
        reloaded = mem.load(path)
        check("the record persisted", len(reloaded) == 1, reloaded)
        check("re-filtering against the reloaded store suppresses the unchanged finding",
              mem.filter_signals(
                  [_signal("ageing_rate_hotspot", "location", "OVERSEAS")],
                  report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
                  observed_at="2026-08-21")["reportable"] == [])
    finally:
        shutil.rmtree(tmp)


def test_corrupt_store_is_treated_as_empty_not_fatal() -> None:
    print("\n=== a corrupt store degrades to empty rather than crashing the run ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        path = mem.store_path(tmp, "inventory_ageing", "ds1")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        result = mem.filter_signals(
            [_signal("ageing_rate_hotspot", "location", "OVERSEAS")],
            report_id="inventory_ageing", out_dir=tmp, dataset_id="ds1",
            observed_at="2026-08-20")
        check("it falls back to first_seen behaviour", len(result["reportable"]) == 1)
    finally:
        shutil.rmtree(tmp)


def main() -> int:
    print("=" * 72)
    print("Cross-run novelty for single-snapshot reports")
    print("=" * 72)

    test_first_sighting_always_reports()
    test_unchanged_is_suppressed_then_escalation_reopens_it()
    test_clearance_is_announced_as_good_news()
    test_two_different_members_do_not_collide()
    test_anchor_independence()
    test_persistence_round_trips()
    test_corrupt_store_is_treated_as_empty_not_fatal()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SNAPSHOT MEMORY FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
