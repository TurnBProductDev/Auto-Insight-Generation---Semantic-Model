"""Offline contract checks for the generic Ageing end-to-end flow."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domains.inventory import ageing_flow  # noqa: E402

FAILURES = []


def check(label, condition):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        FAILURES.append(label)


CFG = {
    "report_name": "Example Ageing", "ageing_currency": "QAR",
    "ageing_mapping": {
        "exposure": "[Exposure]", "bucket": "'F'[Band]", "snapshot": "'F'[AsAt]",
        "non_moving": "'F'[Stalled]", "sku": "'F'[Item]", "location": "'F'[Site]",
        "dimensions": {"location": "'F'[Site]", "customer": "'D'[Customer]"},
    },
    "ageing_aged_filter": "'F'[Over9] = \"Y\"",
    "ageing_high_risk_filter": "'F'[Over12] = \"Y\"",
    "ageing_oldest_filter": "'F'[Over24] = \"Y\"",
    "ageing_validation_share_expression": "[Bad Share]",
    "ageing_validation_numerator_expression": "SUM('F'[Bad Numerator])",
}


def main() -> int:
    queries = ageing_flow.build_queries(CFG)
    check("queries use configured semantic names", "'F'[Band]" in queries["bands"])
    check("the exposure measure is reused inside every policy cut",
          "CALCULATE([Exposure]" in queries["snapshot"])
    check("arbitrary mapped dimensions receive scans", "dimension__customer" in queries)

    def execute(dax):
        if '"as_at"' in dax:
            return [{"[as_at]": "2026-08-19", "[total_value]": 1000,
                     "[aged_value]": 300, "[high_risk_value]": 150,
                     "[oldest_value]": 50, "[skus]": 10, "[locations]": 2,
                     "[source_aged_share]": 1.5, "[source_aged_numerator]": 1500}]
        if "'F'[Band]" in dax and "DISTINCTCOUNT" in dax:
            return [
                {"F[Band]": "0-03 MONTHS", "[value]": 700, "[aged]": 0, "[skus]": 7},
                {"F[Band]": "09-12 MONTHS", "[value]": 150, "[aged]": 150, "[skus]": 2},
                {"F[Band]": "12-24 MONTHS", "[value]": 100, "[aged]": 100, "[skus]": 1},
                {"F[Band]": "24+ MONTHS", "[value]": 50, "[aged]": 50, "[skus]": 1},
            ]
        if "'F'[Stalled]" in dax and "SUMMARIZECOLUMNS" in dax:
            return [{"F[Stalled]": "YES", "[value]": 200, "[aged]": 100},
                    {"F[Stalled]": "NO", "[value]": 800, "[aged]": 200}]
        if "'F'[Site]" in dax:
            return [{"F[Site]": "A", "[value]": 600, "[aged]": 250, "[high_risk]": 120},
                    {"F[Site]": "B", "[value]": 400, "[aged]": 50, "[high_risk]": 30}]
        if "'D'[Customer]" in dax:
            return [{"D[Customer]": "X", "[value]": 1000, "[aged]": 300, "[high_risk]": 150}]
        return [{"F[Item]": "SKU1", "[value]": 50}]

    scanned = ageing_flow.scan(execute, CFG)
    model = ageing_flow.build(scanned, CFG)
    check("all four reconciliations pass", all(model["checks"].values()))
    if not all(model["checks"].values()):
        print(f"         {model['checks']} bands={scanned['bands']}")
    check("currency is configuration, not hardcoded", model["currency"] == "QAR")
    check("generic customer dimension reaches the stat check",
          "customer" in model["stat_check"]["dimensions"])
    check("an impossible source share is explicitly excluded",
          model["semantic_validation"]["excluded"] is True)
    check("summary and insight artifacts are grounded",
          "QAR" in ageing_flow.summary_markdown(model)
          and "single stock position" in ageing_flow.insight_markdown(model))
    print("\nAGEING FLOW CLEAN" if not FAILURES else f"\n{len(FAILURES)} FAILURE(S)")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    raise SystemExit(main())
