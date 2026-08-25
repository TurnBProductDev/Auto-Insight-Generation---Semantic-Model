"""Offline replay for the report-specific ageing statistical checks."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domains.inventory import ageing_stats  # noqa: E402
from src.domains.inventory.reports import ageing  # noqa: E402
from scripts.replay_ageing import _synthetic_scan  # noqa: E402

failures: list[str] = []


def check(label: str, condition: bool, detail="") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)
        if detail:
            print(f"         {detail}")


def main() -> int:
    report = ageing.build(_synthetic_scan())
    stats = report["stat_check"]
    signals = report["stat_signals"]
    assoc = stats["aged_non_moving_association"]

    check("the method is explicitly single-snapshot",
          stats["method"] == "single_snapshot_ageing_v2")
    check("no comparison is invented",
          stats["quality"]["comparison_available"] is False
          and "one stock position" in stats["quality"]["comparison_reason"])
    check("the aged/non-moving overlap is conditional, not double-counted",
          assoc["aged_non_moving_value"] == 2_760_784.20
          and assoc["aged_rate_lift"] > 3.0, assoc)
    check("every comparison names its real baseline",
          all(s.get("comparison_label") for s in signals))
    check("BR-28 priority is fixed: 24+ then 12-24 then the overlap",
          [s["analysis_type"] for s in signals[:3]] == [
              "ageing_oldest_band", "ageing_high_risk_band", "ageing_aged_non_moving"],
          [s["analysis_type"] for s in signals])
    check("story identities anchor to the snapshot",
          len({s["story_key"] for s in signals}) == len(signals)
          and all(s["story_key"].startswith("age:v1:") for s in signals))

    # A tiny extreme-rate member must not outrank a material hotspot.  The
    # detector may retain it, but excess SAR (not raw percentage) orders peers.
    synthetic = {
        "header": {"total_value": 10_000_000.0, "aged_value": 1_000_000.0,
                   "high_risk_value": 0.0, "high_risk_share_pct": 0.0},
        "risk_split": {"aged_non_moving": 0.0, "aged_moving": 1_000_000.0,
                       "fresh_non_moving": 0.0, "fresh_moving": 9_000_000.0,
                       "non_moving_total": 0.0},
        "distribution": {"bands": [], "undetermined_value": 0.0},
        "locations": [
            {"name": "material", "total": 3_000_000.0, "value": 700_000.0},
            {"name": "tiny", "total": 30_000.0, "value": 30_000.0},
            {"name": "rest", "total": 6_970_000.0, "value": 270_000.0},
        ],
        "divisions": [], "checks": {"ok": True},
        "migration": {"available": False, "reason": "one stock position"},
        "as_at": "2026-08-20",
    }
    hot = ageing_stats.analyze(synthetic)["dimensions"]["location"]["hotspots"]
    check("material SAR impact outranks a freak tiny percentage",
          hot and hot[0]["member"] == "material", hot)
    check("leave-one-out baseline is used",
          hot and hot[0]["rest_of_estate_rate_pct"] < hot[0]["aged_rate_pct"], hot)

    print("\n--- adapter-independent vocabulary and roles ---")
    generic = {
        **synthetic,
        "report_id": "client_receivables_ageing",
        "distribution": {"bands": [
            {"name": "0-30 days", "value": 8_000_000.0, "high_risk": False,
             "ordinal": 1},
            {"name": "31-60 days", "value": 1_000_000.0, "high_risk": True,
             "ordinal": 2},
            {"name": "61+ days", "value": 1_000_000.0, "high_risk": True,
             "ordinal": 3}], "undetermined_value": 0.0},
        "ageing_dimensions": {"customer_group": synthetic["locations"]},
        "locations": [], "divisions": [],
    }
    generic_report = {**generic}
    generic_report["stat_check"] = ageing_stats.analyze(generic_report)
    generic_signals = ageing_stats.detect(generic_report)
    check("arbitrary day-band labels are ordered by metadata, not exact text",
          generic_signals[0]["affected_segment"] == "61+ days"
          and generic_signals[1]["affected_segment"] == "31-60 days",
          [s["affected_segment"] for s in generic_signals])
    check("arbitrary business dimensions are analysed",
          "customer_group" in generic_report["stat_check"]["dimensions"])
    check("the source report identity is preserved",
          all(s["report_id"] == "client_receivables_ageing" for s in generic_signals))

    # Broken arithmetic must lead the signal list, never be buried as a caveat.
    broken = {**synthetic, "checks": {"bands": False}}
    broken_signals = ageing_stats.detect(broken)
    check("failed reconciliation becomes the first critical signal",
          broken_signals[0]["analysis_type"] == "ageing_data_quality"
          and broken_signals[0]["severity"] == "critical")

    print("\nAGEING STATS " + ("FAILED" if failures else "CLEAN"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
