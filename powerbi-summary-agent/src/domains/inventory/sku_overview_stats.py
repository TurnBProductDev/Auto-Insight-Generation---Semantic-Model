"""Report-specific statistical checks for SKU Overview.

Single-snapshot Loc-SKU stock position - same shape as Ageing, so the same
rule applies: never manufacture a YoY delta, a trend, or a significance
claim. The comparisons this data supports are: state-of-business exposure
(which `RECOMMENDED_ACTION` states carry the most value), exposure-adjusted
concentration (which Department/Location holds more Excess Stock or
Opportunity Loss than its own size would suggest), and ranked outliers
(fastest-emptying, highest-loss, highest-excess SKUs) - all things a single
snapshot can actually support.

Pure: no state, I/O, connection, or LLM.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

REPORT_ID = "sku_overview"

#: BR-31's double-warning idea, carried over: a Loc-SKU with zero stock and
#: nothing on order is urgent regardless of its value - value-weighted
#: ranking would put it last, since a stockout holds no stock value at all.
URGENT_STATE = "STOCK OUT - PLACE ORDER"

MIN_MEMBER_SHARE_PCT = 0.25
MIN_RATE_GAP_PCT = 3.0
MIN_RATE_RATIO = 1.20
MIN_EXCESS_FLOOR = 20_000.0
MIN_EXCESS_TOTAL_PCT = 0.10


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _pct(part: Any, whole: Any) -> float | None:
    p, w = _num(part), _num(whole)
    if p is None or w is None or w == 0:
        return None
    return p / w * 100.0


def _money(value: float, currency: str) -> str:
    prefix = (str(currency or "").strip() + " ") if currency else ""
    if abs(value) >= 1_000_000:
        return f"{prefix}{value / 1_000_000:.2f}M"
    if abs(value) >= 1_000:
        return f"{prefix}{value / 1_000:.0f}K"
    return f"{prefix}{value:,.0f}"


def _story_key(report_id: str, kind: str, role: str, member: str, anchor: str) -> str:
    blob = json.dumps([report_id, kind, role, member, anchor], separators=(",", ":"))
    return "sku:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _hotspots(rows: Iterable[dict], total_value: float, total_excess: float,
             role: str, *, limit: int = 3) -> list[dict]:
    """Exposure-adjusted Excess Stock exceptions vs. the rest of the estate.

    Same construction as Ageing's rate hotspots: the comparator excludes the
    member itself, so a large member cannot pull the baseline toward its own
    figure.
    """
    out: list[dict] = []
    for row in rows:
        value = max(0.0, _num(row.get("stock_value")) or 0.0)
        excess = max(0.0, _num(row.get("excess_value")) or 0.0)
        rest_value, rest_excess = total_value - value, total_excess - excess
        if not value or rest_value <= 0 or rest_excess < 0:
            continue
        rate = excess / value * 100.0
        baseline = rest_excess / rest_value * 100.0
        expected = value * baseline / 100.0
        surplus = excess - expected
        ratio = rate / baseline if baseline > 0 else None
        member_share = value / total_value * 100.0 if total_value else 0.0
        excess_floor = max(MIN_EXCESS_FLOOR, total_value * MIN_EXCESS_TOTAL_PCT / 100.0)
        if (member_share < MIN_MEMBER_SHARE_PCT or surplus < excess_floor
                or rate - baseline < MIN_RATE_GAP_PCT
                or ratio is None or ratio < MIN_RATE_RATIO):
            continue
        out.append({
            "role": role, "member": str(row.get("name") or ""),
            "stock_value": value, "excess_value": excess,
            "excess_rate_pct": rate, "rest_of_estate_rate_pct": baseline,
            "rate_gap_pct_points": rate - baseline, "rate_ratio": ratio,
            "expected_excess_at_baseline": expected, "surplus_excess_value": surplus,
            "member_stock_share_pct": member_share,
        })
    out.sort(key=lambda x: (-x["surplus_excess_value"], -x["excess_rate_pct"], x["member"]))
    return out[: max(0, int(limit))]


def analyze(report: dict) -> dict:
    header = report.get("header") or {}
    total = max(0.0, _num(header.get("total_stock_value")) or 0.0)
    total_excess = max(0.0, _num(header.get("total_excess_value")) or 0.0)
    total_opp_loss = max(0.0, _num(header.get("total_opp_loss")) or 0.0)

    dimensions = {}
    for role, rows in (report.get("dimensions") or {}).items():
        dimensions[role] = {
            "hotspots": _hotspots(rows, total, total_excess, role, limit=3),
        }

    quality = {
        "reconciled": bool(report.get("checks")) and all((report.get("checks") or {}).values()),
        "failed_checks": sorted(k for k, ok in (report.get("checks") or {}).items() if not ok),
    }
    return {
        "method": "single_snapshot_sku_overview_v1",
        "report_id": str(report.get("report_id") or REPORT_ID),
        "anchor": str(report.get("as_at") or ""),
        "overall": {
            "total_stock_value": total,
            "total_excess_value": total_excess,
            "excess_share_pct": header.get("excess_share_pct"),
            "total_opp_loss": total_opp_loss,
        },
        "dimensions": dimensions,
        "quality": quality,
    }


def detect(report: dict) -> list[dict]:
    """Ranked report-specific findings with an explicit comparison.

    Tier order: the urgent stock-out state leads regardless of value, then
    exposure-adjusted hotspots, then estate-wide opportunity-loss and excess
    totals. No safer-but-larger finding can overtake the urgent tier.
    """
    stats = report.get("stat_check") or analyze(report)
    report_id = str(stats.get("report_id") or report.get("report_id") or REPORT_ID)
    currency = str(report.get("currency") or "")
    anchor = str(stats.get("anchor") or "")
    total = float((stats.get("overall") or {}).get("total_stock_value") or 0.0) or 1.0
    findings: list[dict] = []

    def add(kind: str, role: str, member: str, value: float, tier: int,
            description: str, comparison: str, extra: dict | None = None) -> None:
        share = value / total * 100.0
        findings.append({
            "candidate_id": f"{kind}:{role}:{member or 'estate'}",
            "story_key": _story_key(report_id, kind, role, member, anchor),
            "report_id": report_id,
            "analysis_type": kind,
            "dimension": role,
            "affected_segment": member or "Whole stock position",
            "segment_members": [member] if member else [],
            "metric": "Stock value at risk",
            "metric_family": "stock_value",
            "current": value,
            "impact_value": value,
            "impact_share": share,
            "score": tier * 100.0 + share,
            "severity": "critical" if tier >= 4 else "warning" if tier >= 2 else "info",
            "comparison_label": comparison,
            "description": description,
            **(extra or {}),
        })

    urgent = next((s for s in report.get("states") or [] if s.get("action") == URGENT_STATE), None)
    if urgent and urgent.get("rows"):
        rows = int(urgent["rows"])
        total_rows = int((report.get("header") or {}).get("rows") or 0) or 1
        add("sku_overview_urgent_state", "recommended_action", URGENT_STATE,
            float(urgent.get("stock_value") or 0.0), 6,
            f"{rows:,} Loc-SKUs are in {URGENT_STATE} ({rows / total_rows * 100:.1f}% "
            f"of all Loc-SKUs) - zero stock with nothing on order.",
            "share of all Loc-SKU rows",
            {"loc_skus": rows, "opp_loss": _num(urgent.get("opp_loss")) or 0.0})

    for role, dimension in (stats.get("dimensions") or {}).items():
        for hot in (dimension or {}).get("hotspots") or []:
            value = float(hot.get("surplus_excess_value") or 0.0)
            member = str(hot.get("member") or "")
            add("sku_overview_excess_hotspot", role, member, value, 3,
                f"{member} holds {_money(value, currency)} more Excess Stock than "
                f"its stock value would imply at the rest-of-estate rate; its "
                f"excess rate is {hot['excess_rate_pct']:.1f}% versus "
                f"{hot['rest_of_estate_rate_pct']:.1f}% elsewhere.",
                "Excess Stock rate versus the rest of the estate",
                dict(hot))

    overall = stats.get("overall") or {}
    opp_loss = float(overall.get("total_opp_loss") or 0.0)
    if opp_loss:
        add("sku_overview_opportunity_loss", "estate", "", opp_loss, 2,
            f"{_money(opp_loss, currency)} of estimated Opportunity Loss is "
            f"attributed to stock-out Loc-SKUs across the estate.",
            "estimated daily-sales-derived loss, not confirmed lost revenue")

    excess = float(overall.get("total_excess_value") or 0.0)
    excess_share = overall.get("excess_share_pct")
    if excess and isinstance(excess_share, (int, float)):
        add("sku_overview_excess_total", "estate", "", excess, 1,
            f"{_money(excess, currency)} is held as Excess Stock, "
            f"{excess_share:.1f}% of total stock value.",
            "share of total stock value")

    quality = stats.get("quality") or {}
    if not quality.get("reconciled"):
        findings.append({
            "candidate_id": "sku_overview_data_quality:estate",
            "story_key": _story_key(report_id, "sku_overview_data_quality", "estate", "", anchor),
            "report_id": report_id,
            "analysis_type": "sku_overview_data_quality",
            "dimension": "estate",
            "affected_segment": "Whole stock position",
            "impact_value": 0.0,
            "impact_share": None,
            "score": 700.0,
            "severity": "critical",
            "comparison_label": "reconciliation checks",
            "description": "The SKU Overview position did not pass every reconciliation check.",
            "failed_checks": quality.get("failed_checks") or [],
        })

    findings.sort(key=lambda item: (-float(item.get("score") or 0.0), item["candidate_id"]))
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"S{index}"
    return findings
