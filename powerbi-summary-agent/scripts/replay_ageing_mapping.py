"""Offline replay for automatic, fail-closed ageing semantic mapping."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.domains.inventory import ageing_mapping  # noqa: E402

failures = []


def check(label, condition, detail=""):
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}")
    if not condition:
        failures.append(label)
        if detail:
            print("        ", detail)


def model(names: dict) -> dict:
    table = names.get("table", "Ledger")
    return {"columns": [
        {"table": table, "column": names["bucket"], "data_type": "String",
         "category": "categorical", "description": "Ordered age band"},
        {"table": table, "column": names["snapshot"], "data_type": "Date",
         "category": "date", "description": "Position as of date"},
        {"table": table, "column": names["exposure"], "data_type": "Decimal",
         "category": "numeric", "description": "Outstanding balance amount"},
        {"table": table, "column": names["dimension"], "data_type": "String",
         "category": "categorical", "description": names.get("dimension_description", "Customer account")},
    ], "measures": []}


def main() -> int:
    observed = {"snapshot_cardinality": 1, "bucket_order": ["0-30", "31-60", "61+"],
                "high_risk_bands": ["61+"], "reconciled": True}
    first = ageing_mapping.resolve(model({
        "table": "AR Ledger", "bucket": "Overdue Bucket", "snapshot": "As Of Date",
        "exposure": "Outstanding Balance", "dimension": "Customer Group"}), observed=observed)
    check("a receivables-ageing vocabulary resolves", first["status"] == "ready", first)
    check("same column names are not required",
          first["roles"]["bucket"]["reference"] == "'AR Ledger'[Overdue Bucket]")
    check("customer is discovered as a business dimension", "customer" in first["dimensions"])

    second = ageing_mapping.resolve(model({
        "table": "Inventory Position", "bucket": "Age Band", "snapshot": "Snapshot Date",
        "exposure": "Carrying Value", "dimension": "Warehouse",
        "dimension_description": "Stock location"}), observed=observed)
    check("a stock-ageing vocabulary also resolves", second["status"] == "ready", second)
    check("warehouse becomes a location dimension", "location" in second["dimensions"])

    ambiguous = model({"bucket": "Group", "snapshot": "Date", "exposure": "Metric",
                       "dimension": "Label"})
    refused = ageing_mapping.resolve(ambiguous, observed={})
    check("weak names are refused rather than guessed", refused["status"] == "review", refused)
    check("the refusal names every missing measured fact",
          any("cardinality" in x for x in refused["issues"])
          and any("bucket order" in x for x in refused["issues"])
          and any("high-risk" in x for x in refused["issues"]), refused["issues"])

    overridden = ageing_mapping.resolve(ambiguous, overrides={
        "exposure": "'Ledger'[Metric]", "bucket": "'Ledger'[Group]",
        "snapshot": "'Ledger'[Date]", "dimensions": {"portfolio": "'Ledger'[Label]"},
        "bucket_order": ["A", "B"], "high_risk_bands": ["B"]},
        observed={"snapshot_cardinality": 1, "reconciled": True})
    check("explicit mappings resolve an otherwise anonymous model",
          overridden["status"] == "ready", overridden)
    check("configured custom dimensions survive", "portfolio" in overridden["dimensions"])

    anonymous_measured = ageing_mapping.resolve(ambiguous, observed={
        "exposure_reference": "'Ledger'[Metric]", "bucket_reference": "'Ledger'[Group]",
        "snapshot_reference": "'Ledger'[Date]", "snapshot_cardinality": 1,
        "bucket_order": ["A", "B"], "high_risk_bands": ["B"], "reconciled": True})
    check("bounded observations can resolve anonymous field names",
          anonymous_measured["status"] == "ready", anonymous_measured)

    print("\nAGEING MAPPING " + ("FAILED" if failures else "CLEAN"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
