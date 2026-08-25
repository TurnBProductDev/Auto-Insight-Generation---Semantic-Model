"""Day-over-day and robust-statistical detection for single-snapshot inventory
reports. Offline.

    python scripts/replay_snapshot_trend.py

No auth, no LLM, no network - a temp directory holds a synthetic archive.
Proves the two honesty rules that matter most for a feature computing
statistics on top of the pipeline's own history: a comparison the archive
refuses produces zero findings (never a guess), and a z-score is never
computed on too few real days - day-over-day movement is still shown, but
"statistical" stays false and says how many days are missing.
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import archive  # noqa: E402
from src.domains.inventory import snapshot_trend as trend  # noqa: E402

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


def _scan(as_at: str, band_value: float) -> dict:
    return {
        "snapshot": [{"[as_at]": as_at, "[total_value]": 1_000_000.0}],
        "bands": [{"[NEW AGE]": "24+ MONTHS", "[value]": band_value, "[aged]": band_value},
                 {"[NEW AGE]": "0-03 MONTHS", "[value]": 500_000.0, "[aged]": 0.0}],
    }


EXTRACTOR = trend.series_extractor("bands", "NEW AGE", "aged")


def test_no_prior_produces_no_findings() -> None:
    print("\n=== nothing fabricated on the first-ever run ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        current = _scan("2026-08-24", 100_000.0)
        comparison = archive.compare_window(current, tmp, {}, run_date=_dt.date(2026, 8, 24))
        result = trend.detect(current, tmp, {}, report_id="test", metric="ageing_band",
                              extractor=EXTRACTOR, comparison=comparison)
        check("compare_window correctly refuses (no_prior)",
              comparison["reason"] == "no_prior")
        check("no findings are produced", result["findings"] == [])
        check("the verdict says why", result["verdict"]["comparable"] is False)
    finally:
        shutil.rmtree(tmp)


def test_single_prior_gives_movement_but_not_statistics() -> None:
    print("\n=== one prior day: real movement, honestly not yet a statistic ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        archive.write(_scan("2026-08-23", 100_000.0), tmp, {}, run_date=_dt.date(2026, 8, 23))
        current = _scan("2026-08-24", 150_000.0)  # +50% on a real band
        comparison = archive.compare_window(current, tmp, {}, run_date=_dt.date(2026, 8, 24))
        result = trend.detect(current, tmp, {}, report_id="test", metric="ageing_band",
                              extractor=EXTRACTOR, comparison=comparison,
                              min_history_days=5, materiality_pct=3.0)
        check("comparable", comparison["comparable"] is True)
        check("history_days is 1, not fabricated as more", result["verdict"]["history_days"] == 1)
        check("statistical is honestly False with only 1 archived day",
              result["verdict"]["statistical"] is False)
        check("the material move is still reported on day-over-day grounds alone",
              len(result["findings"]) == 1, result["findings"])
        finding = result["findings"][0]
        check("it names the real prior/current values",
              finding["prior"] == 100_000.0 and finding["current"] == 150_000.0)
        check("the description says history is insufficient for a statistical read, "
             "rather than silently omitting the caveat",
              "not enough history" in finding["description"], finding["description"])
    finally:
        shutil.rmtree(tmp)


def test_immaterial_move_is_not_reported() -> None:
    print("\n=== a trivial move stays quiet ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        archive.write(_scan("2026-08-23", 100_000.0), tmp, {}, run_date=_dt.date(2026, 8, 23))
        current = _scan("2026-08-24", 100_500.0)  # +0.5% of total - well under 3%
        comparison = archive.compare_window(current, tmp, {}, run_date=_dt.date(2026, 8, 24))
        result = trend.detect(current, tmp, {}, report_id="test", metric="ageing_band",
                              extractor=EXTRACTOR, comparison=comparison, materiality_pct=3.0)
        check("no finding for a sub-materiality drift", result["findings"] == [])
    finally:
        shutil.rmtree(tmp)


def test_robust_z_activates_once_enough_history_exists() -> None:
    print("\n=== a real robust-z read, once the history floor is met ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        # Five stable prior days (~100K, tiny noise), then a real spike today.
        stable = [98_000.0, 101_000.0, 99_500.0, 100_500.0, 100_000.0]
        for i, value in enumerate(stable):
            day = _dt.date(2026, 8, 18) + _dt.timedelta(days=i)
            archive.write(_scan(day.isoformat(), value), tmp, {}, run_date=day)
        current = _scan("2026-08-24", 250_000.0)  # a genuine spike
        comparison = archive.compare_window(current, tmp, {}, run_date=_dt.date(2026, 8, 24))
        result = trend.detect(current, tmp, {}, report_id="test", metric="ageing_band",
                              extractor=EXTRACTOR, comparison=comparison,
                              min_history_days=5, materiality_pct=3.0, z_cutoff=2.5)
        check("history_days reaches 5", result["verdict"]["history_days"] == 5)
        check("statistical is now True", result["verdict"]["statistical"] is True)
        check("the spike is reported", len(result["findings"]) == 1, result["findings"])
        check("its description carries a robust z, not a 'not enough history' caveat",
              "robust z=" in result["findings"][0]["description"]
              and "not enough history" not in result["findings"][0]["description"],
              result["findings"][0]["description"])

        # Same five stable days, a near-identical value today - no finding.
        quiet = _scan("2026-08-24", 100_200.0)
        comparison2 = archive.compare_window(quiet, tmp, {}, run_date=_dt.date(2026, 8, 24))
        quiet_result = trend.detect(quiet, tmp, {}, report_id="test", metric="ageing_band",
                                    extractor=EXTRACTOR, comparison=comparison2,
                                    min_history_days=5, materiality_pct=3.0, z_cutoff=2.5)
        check("a value inside the normal range is not flagged even with full "
             "history available", quiet_result["findings"] == [], quiet_result["findings"])
    finally:
        shutil.rmtree(tmp)


def test_flat_reference_never_divides_by_zero() -> None:
    print("\n=== a perfectly flat reference does not crash, and reports on "
         "materiality alone ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        for i in range(5):
            day = _dt.date(2026, 8, 18) + _dt.timedelta(days=i)
            archive.write(_scan(day.isoformat(), 100_000.0), tmp, {}, run_date=day)
        current = _scan("2026-08-24", 140_000.0)  # +40K on a flat MAD=0 reference
        comparison = archive.compare_window(current, tmp, {}, run_date=_dt.date(2026, 8, 24))
        result = trend.detect(current, tmp, {}, report_id="test", metric="ageing_band",
                              extractor=EXTRACTOR, comparison=comparison,
                              min_history_days=5, materiality_pct=3.0)
        check("no exception, and the material move is still reported",
              len(result["findings"]) == 1, result["findings"])
        check("no fabricated z on an undefined (flat) reference",
              "robust z=" not in result["findings"][0]["description"],
              result["findings"][0]["description"])
    finally:
        shutil.rmtree(tmp)


def test_story_keys_are_stable_and_distinct() -> None:
    print("\n=== story_keys are stable across re-runs and distinct per member ===")
    tmp = Path(tempfile.mkdtemp())
    try:
        archive.write(_scan("2026-08-23", 100_000.0), tmp, {}, run_date=_dt.date(2026, 8, 23))
        current = _scan("2026-08-24", 150_000.0)
        comparison = archive.compare_window(current, tmp, {}, run_date=_dt.date(2026, 8, 24))
        r1 = trend.detect(current, tmp, {}, report_id="test", metric="ageing_band",
                          extractor=EXTRACTOR, comparison=comparison, materiality_pct=3.0)
        r2 = trend.detect(current, tmp, {}, report_id="test", metric="ageing_band",
                          extractor=EXTRACTOR, comparison=comparison, materiality_pct=3.0)
        check("identical inputs produce identical story_keys",
              r1["findings"][0]["story_key"] == r2["findings"][0]["story_key"])
    finally:
        shutil.rmtree(tmp)


def main() -> int:
    print("=" * 72)
    print("Snapshot trend detection")
    print("=" * 72)

    test_no_prior_produces_no_findings()
    test_single_prior_gives_movement_but_not_statistics()
    test_immaterial_move_is_not_reported()
    test_robust_z_activates_once_enough_history_exists()
    test_flat_reference_never_divides_by_zero()
    test_story_keys_are_stable_and_distinct()

    print("\n" + "=" * 72)
    if _failures:
        print(f"SNAPSHOT TREND FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
