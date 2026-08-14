"""Run the inventory chain over already-scanned reports and pool the findings.

    python scripts/run_inventory_chain.py

Reads the two reports' saved scans, runs them through the chain runner in one
process, and writes one combined investigative view plus the per-report
summaries. Offline once the scans exist - the live scanning is a separate step.

This is the deterministic half of the chain. The LLM synthesiser that turns the
pooled evidence into prose is the existing insight branch; what this proves is
the part WP8 is actually about: that both reports' findings reach one pool with
their provenance intact, and that neither can crowd the other out.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.kernel import chain  # noqa: E402
from src.domains.inventory.reports import ageing, stock_health  # noqa: E402

OUT = PROJECT_ROOT / "outputs_inventory_chain"

SOURCES = {
    "inventory_ageing": {
        "scan": PROJECT_ROOT / "outputs_ageing" / "ageing_scan.json",
        "dataset_id": "84212fd9-6504-4b22-a46b-e64109a1ab89",
        "name": "Stock Age Analysis",
        "dashboard": "outputs_ageing/report_dashboard_ageing.html",
        "build": ageing.build,
    },
    "inventory_stock_health": {
        "scan": PROJECT_ROOT / "outputs_stock_health" / "stock_health_scan.json",
        "dataset_id": "64eefa4b-d82f-41bd-a841-fc1cfbd7a88a",
        "name": "Inventory Management",
        "dashboard": "outputs_stock_health/report_dashboard_stock_health.html",
        "build": stock_health.build,
    },
}

SPEC = chain.ChainSpec(
    chain_id="inventory",
    report_ids=tuple(SOURCES),
    title="Inventory: what changed and why",
)

#: How many findings the combined report carries. Small on purpose - a pooled
#: report that lists everything is not a narrative.
MAX_FINDINGS = 6


def _evidence_from_ageing(report: dict) -> list[dict]:
    """Turn the ageing report into scored, comparable findings."""
    header = report.get("header") or {}
    total = float(header.get("total_value") or 0) or 1.0
    split = report.get("risk_split") or {}
    out = []

    oldest = next((b for b in (report.get("distribution") or {}).get("bands") or []
                   if str(b.get("name", "")).upper().startswith("24+")), None)
    if oldest:
        value = float(oldest.get("value") or 0)
        out.append({
            "finding": f"SAR {value / 1e6:.2f}M of stock is more than two years old",
            "value": value, "score": value / total * 100.0 * 6.0,
            "kind": "write_off_risk"})

    # "Not selling" means something DIFFERENT in each report, and pooling them
    # into one ranked list is exactly where that bites. Stock Age Analysis
    # (BR-18) flags a batch from day one if it has not sold since it arrived;
    # Inventory Management (BR-24) requires 30 consecutive days of no sales with
    # stock available throughout. Same phrase, two populations. So each finding
    # states its own definition inline rather than borrowing the shorter word,
    # and the caveats say so as well.
    aged_nm = float(split.get("aged_non_moving") or 0)
    if aged_nm:
        out.append({
            "finding": f"SAR {aged_nm / 1e6:.2f}M is aged and has not sold since "
                       f"it arrived",
            "value": aged_nm, "score": aged_nm / total * 100.0 * 3.0,
            "kind": "aged_and_stalled"})

    fresh_nm = float(split.get("fresh_non_moving") or 0)
    if fresh_nm:
        out.append({
            "finding": f"SAR {fresh_nm / 1e6:.2f}M of stock under nine months old "
                       f"has not sold since it arrived",
            "value": fresh_nm, "score": fresh_nm / total * 100.0 * 2.0,
            "kind": "no_demand"})
    return out


def _evidence_from_stock_health(report: dict) -> list[dict]:
    header = report.get("header") or {}
    total = float(header.get("stock_value") or 0) or 1.0
    out = []

    for row in report.get("queue") or []:
        if not row.get("double_warning") or not row.get("loc_skus"):
            continue
        out.append({
            "finding": f"{row['loc_skus']:,} product lines: "
                       f"{row['action'].lower()}",
            "value": float(row.get("stock_value") or 0),
            "score": 80.0, "kind": "urgent_action"})

    excess = float(header.get("excess_value") or 0)
    if excess:
        out.append({
            "finding": f"SAR {excess / 1e6:.2f}M is held above the agreed cover",
            "value": excess, "score": excess / total * 100.0,
            "kind": "over_cover"})

    unwanted = int(float(header.get("unwanted_skus") or 0))
    if unwanted:
        out.append({
            "finding": f"{unwanted:,} already-overstocked products have more "
                       f"stock on order",
            "value": float(header.get("unwanted_pending_value") or 0),
            "score": 55.0, "kind": "buying_conflict"})
    return out


EXTRACTORS = {
    "inventory_ageing": _evidence_from_ageing,
    "inventory_stock_health": _evidence_from_stock_health,
}


def _connect(findings: list[dict]) -> list[str]:
    """The point of pooling: sentences no single report could write.

    Only stated when BOTH reports actually contributed, and only from figures
    already present in the findings - the two models are different, so a
    connection must be a shared observation, never a shared arithmetic total.
    """
    kinds = {f["kind"]: f for f in findings}
    lines = []
    # Findings are quoted verbatim. Lower-casing them to fit a sentence turns
    # "SAR 2.76M" into "sar 2.76m", which reads as a typo and, worse, changes a
    # figure the auditor checks against the model.
    if "aged_and_stalled" in kinds and "over_cover" in kinds:
        lines.append(
            f"Stock Age Analysis shows that {kinds['aged_and_stalled']['finding']}, "
            f"while Inventory Management shows that {kinds['over_cover']['finding']}. "
            f"These describe the same money from two directions: stock bought "
            f"beyond what was needed, which then sits long enough to age.")
    if "buying_conflict" in kinds and "write_off_risk" in kinds:
        lines.append(
            f"{kinds['buying_conflict']['finding']}, at the same time as "
            f"{kinds['write_off_risk']['finding']}. Reviewing those open "
            f"orders is the cheapest way to stop the oldest bracket growing.")
    if "no_demand" in kinds and "urgent_action" in kinds:
        lines.append(
            "Stock that has not sold since it arrived sits alongside lines that "
            "are out of stock entirely, so the problem is not the total amount "
            "held but where it is held.")
    return lines


def main() -> int:
    missing = [rid for rid, cfg in SOURCES.items() if not cfg["scan"].exists()]
    if missing:
        print("No scan found for: " + ", ".join(missing))
        print("Run the report scans first; this step is offline.")
        return 1

    def run_report(report_id: str) -> dict:
        cfg = SOURCES[report_id]
        scan = json.loads(cfg["scan"].read_text(encoding="utf-8"))
        report = cfg["build"](scan)
        return {
            "dataset_id": cfg["dataset_id"],
            "report_name": cfg["name"],
            "report": report,
            "evidence": EXTRACTORS[report_id](report),
        }

    result = chain.run(SPEC, run_report, logger=print)

    names = {rid: cfg["name"] for rid, cfg in SOURCES.items()}
    dashboards = {rid: cfg["dashboard"] for rid, cfg in SOURCES.items()}

    # Rank first, exactly as the signal detector does, THEN guarantee
    # representation. fair_share tops up a selection; handed an empty one it can
    # only return the reserved slots, which is its contract and not a shortcut
    # worth taking here.
    preselected = sorted(result.evidence,
                         key=lambda item: float(item.get("score") or 0.0),
                         reverse=True)[:MAX_FINDINGS]
    ranked = chain.fair_share(result.evidence, preselected, limit=MAX_FINDINGS)
    findings = [
        {**item,
         "report_name": names.get(str(item.get("report_id")), ""),
         "dashboard": dashboards.get(str(item.get("report_id")), ""),
         "attribution": chain.attribution(item, names)}
        for item in ranked
    ]

    combined = {
        "chain_id": SPEC.chain_id,
        "title": SPEC.title,
        "reports": [
            {"report_id": rid, "report_name": names[rid],
             "dataset_id": SOURCES[rid]["dataset_id"],
             "period_label": (result.reports[rid]["report"] or {}).get("period_label"),
             "dashboard": dashboards[rid]}
            for rid in result.reports
        ],
        "findings": findings,
        "connections": _connect(findings),
        "contributing_reports": list(result.contributing_reports),
        "uncovered_reports": list(chain.uncovered_reports(result.evidence, ranked)),
        "failures": result.failures,
        "caveats": [
            "These two reports come from different data models. Figures from one "
            "are never added to figures from the other; where both are mentioned, "
            "they are described side by side.",
            "Stock figures are a position as at the snapshot date, not a total "
            "over a period.",
            "The two reports measure \"not selling\" differently, so their "
            "figures are not interchangeable. Stock Age Analysis counts stock "
            "that has not sold since it arrived, from day one. Inventory "
            "Management counts 30 days in a row without a sale while stock was "
            "available throughout.",
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "insight_inventory_chain.json").write_text(
        json.dumps(combined, indent=2, default=str), encoding="utf-8")

    lines = [f"# {SPEC.title}", ""]
    for report in combined["reports"]:
        lines.append(f"- **{report['report_name']}** - {report['period_label']} "
                     f"([open dashboard]({report['dashboard']}))")
    lines += ["", "## What matters most", ""]
    for index, finding in enumerate(findings, start=1):
        lines.append(f"{index}. {finding['finding']}. {finding['attribution']}")
    if combined["connections"]:
        lines += ["", "## Across both reports", ""]
        lines += [f"- {line}" for line in combined["connections"]]
    lines += ["", "## What this does not say", ""]
    lines += [f"- {c}" for c in combined["caveats"]]
    (OUT / "insight_inventory_chain.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")

    print()
    print(result.summary())
    print(f"contributing: {', '.join(result.contributing_reports)}")
    print(f"uncovered   : {combined['uncovered_reports'] or 'none'}")
    print(f"wrote {OUT / 'insight_inventory_chain.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
