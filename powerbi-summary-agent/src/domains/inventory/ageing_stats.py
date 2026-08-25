"""Report-specific statistical checks for Stock Age Analysis.

Ageing is a one-snapshot distribution, not a period comparison.  These checks
therefore never manufacture YoY deltas, trends, z-scores, or significance
claims.  They measure the risks the model actually supports:

* ordered tail exposure (12--24 and 24+ months);
* the aged x non-moving intersection without double-counting it;
* member aged rates against a leave-one-out estate baseline, tempered by SAR
  excess so a tiny member with an extreme percentage cannot lead;
* concentration of aged value; and
* reconciliation / classification quality.

Pure: no state, I/O, connection, or LLM.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

REPORT_ID = "inventory_ageing"
MIN_MEMBER_SHARE_PCT = 0.25
MIN_RATE_GAP_PCT = 3.0
MIN_RATE_RATIO = 1.20
MIN_EXCESS_SAR = 50_000.0
MIN_EXCESS_TOTAL_PCT = 0.10
CONCENTRATION_TOP1_PCT = 50.0


def _setting(values: dict, key: str, default):
    """Read a nested detector setting (not a top-level application config key)."""
    return values[key] if key in values else default


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
    return "age:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _concentration(rows: Iterable[dict], aged_total: float) -> dict:
    values = sorted((max(0.0, _num(r.get("value")) or 0.0) for r in rows), reverse=True)
    shares = [(v / aged_total * 100.0) for v in values] if aged_total else []
    return {
        "top1_share_pct": shares[0] if shares else None,
        "top3_share_pct": sum(shares[:3]) if shares else None,
        "hhi": sum((share / 100.0) ** 2 for share in shares) if shares else None,
        "members": len(values),
    }


def _hotspots(rows: Iterable[dict], total_value: float, aged_total: float,
              role: str, *, limit: int = 3, config: dict | None = None) -> list[dict]:
    """Exposure-adjusted aged-rate exceptions against the rest of the estate.

    The comparator excludes the member itself.  This matters for CDC, which is
    over half of stock value: comparing it with an overall rate containing CDC
    would pull the baseline towards the very member being tested.
    """
    out: list[dict] = []
    cfg = config or {}
    min_member_share = float(_setting(cfg, "min_member_share_pct", MIN_MEMBER_SHARE_PCT))
    min_rate_gap = float(_setting(cfg, "min_rate_gap_pct", MIN_RATE_GAP_PCT))
    min_rate_ratio = float(_setting(cfg, "min_rate_ratio", MIN_RATE_RATIO))
    min_excess = float(_setting(cfg, "min_excess_value", MIN_EXCESS_SAR))
    min_excess_total_pct = float(_setting(cfg, "min_excess_total_pct", MIN_EXCESS_TOTAL_PCT))
    excess_floor = max(min_excess, total_value * min_excess_total_pct / 100.0)
    for row in rows:
        value = max(0.0, _num(row.get("total")) or 0.0)
        aged = max(0.0, _num(row.get("value")) or 0.0)
        rest_value, rest_aged = total_value - value, aged_total - aged
        if not value or rest_value <= 0 or rest_aged < 0:
            continue
        rate = aged / value * 100.0
        baseline = rest_aged / rest_value * 100.0
        expected = value * baseline / 100.0
        excess = aged - expected
        ratio = rate / baseline if baseline > 0 else None
        member_share = value / total_value * 100.0 if total_value else 0.0
        if (member_share < min_member_share or excess < excess_floor
                or rate - baseline < min_rate_gap
                or ratio is None or ratio < min_rate_ratio):
            continue
        out.append({
            "role": role,
            "member": str(row.get("name") or ""),
            "stock_value": value,
            "aged_value": aged,
            "aged_rate_pct": rate,
            "rest_of_estate_rate_pct": baseline,
            "rate_gap_pct_points": rate - baseline,
            "rate_ratio": ratio,
            "expected_aged_at_baseline": expected,
            "excess_aged_value": excess,
            "excess_share_of_total_pct": excess / total_value * 100.0 if total_value else None,
            "member_stock_share_pct": member_share,
        })
    out.sort(key=lambda x: (-x["excess_aged_value"], -x["aged_rate_pct"], x["member"]))
    return out[: max(0, int(limit))]


def analyze(report: dict) -> dict:
    header = report.get("header") or {}
    split = report.get("risk_split") or {}
    total = max(0.0, _num(header.get("total_value")) or 0.0)
    aged = max(0.0, _num(header.get("aged_value")) or 0.0)
    non_moving = max(0.0, _num(split.get("non_moving_total")) or 0.0)
    overlap = max(0.0, _num(split.get("aged_non_moving")) or 0.0)
    aged_rate = _pct(aged, total)
    aged_given_non_moving = _pct(overlap, non_moving)
    non_moving_given_aged = _pct(overlap, aged)
    lift = (aged_given_non_moving / aged_rate
            if aged_given_non_moving is not None and aged_rate not in (None, 0) else None)

    config = report.get("stat_config") or {}
    supplied = report.get("ageing_dimensions")
    if isinstance(supplied, dict):
        dimension_rows = {str(role): rows or [] for role, rows in supplied.items()}
    else:
        # Compatibility adapter for the first model. New ageing adapters should
        # populate ``ageing_dimensions`` and may use any role names.
        dimension_rows = {
            role: report.get(key) or []
            for role, key in (("location", "locations"), ("division", "divisions"))
            if report.get(key)
        }
    dimensions = {}
    for role, rows in dimension_rows.items():
        dimensions[role] = {
            "hotspots": _hotspots(rows, total, aged, role,
                                   limit=int(_setting(config, "hotspot_limit_per_role", 3)),
                                   config=config),
            "concentration": _concentration(rows, aged),
        }

    quality = {
        "reconciled": bool(report.get("checks")) and all((report.get("checks") or {}).values()),
        "failed_checks": sorted(k for k, ok in (report.get("checks") or {}).items() if not ok),
        "undetermined_value": _num((report.get("distribution") or {}).get("undetermined_value")) or 0.0,
        "comparison_available": bool((report.get("migration") or {}).get("available")),
        "comparison_reason": (report.get("migration") or {}).get("reason"),
    }
    return {
        "method": "single_snapshot_ageing_v2",
        "report_id": str(report.get("report_id") or REPORT_ID),
        "anchor": str(report.get("as_at") or ""),
        "overall": {
            "total_value": total,
            "aged_value": aged,
            "aged_share_pct": aged_rate,
            "high_risk_value": _num(header.get("high_risk_value")) or 0.0,
            "high_risk_share_pct": _num(header.get("high_risk_share_pct")),
        },
        "aged_non_moving_association": {
            "aged_non_moving_value": overlap,
            "aged_share_within_non_moving_pct": aged_given_non_moving,
            "non_moving_share_within_aged_pct": non_moving_given_aged,
            "estate_aged_share_pct": aged_rate,
            "aged_rate_lift": lift,
            "note": "Monetary association, not a causal or significance test.",
        },
        "dimensions": dimensions,
        "quality": quality,
    }


def detect(report: dict, *, hotspot_limit_per_role: int = 3) -> list[dict]:
    """Return ranked report-specific findings with an explicit comparison.

    Score bands encode BR-28's business priority; SAR/share only order findings
    *within* a tier.  No safer but larger finding can overtake the 24+ tier.
    """
    stats = report.get("stat_check") or analyze(report)
    report_id = str(stats.get("report_id") or report.get("report_id") or REPORT_ID)
    currency = str(report.get("currency") or "")
    anchor = str(stats.get("anchor") or "")
    total = float((stats.get("overall") or {}).get("total_value") or 0.0) or 1.0
    bands = (report.get("distribution") or {}).get("bands") or []
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
            "metric": "Stock value at ageing risk",
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

    # The adapter owns band semantics. The detector only needs ordered rows and
    # a high-risk flag; labels may be days, weeks, months, or client vocabulary.
    high_risk_bands = [
        (index, band) for index, band in enumerate(bands)
        if bool(band.get("high_risk")) and (_num(band.get("value")) or 0) > 0
    ]
    high_risk_bands.sort(
        key=lambda pair: float(pair[1].get("ordinal", pair[1].get("index", pair[0]))),
        reverse=True)
    for position, (_index, band) in enumerate(high_risk_bands):
        value = float(band.get("value") or 0.0)
        label = str(band.get("name") or "Oldest age band")
        oldest = position == 0
        add("ageing_oldest_band" if oldest else "ageing_high_risk_band",
            "age_band", label, value, 6 if oldest else 5,
            (f"{_money(value, currency)} is in the oldest reported age band, {label} "
             if oldest else f"{_money(value, currency)} is in the high-risk age band {label} ")
            + f"({value / total * 100:.1f}% of stock value).",
            "share of the current stock position",
            {"band_ordinal": band.get("ordinal", band.get("index", _index)),
             "high_risk": True, "oldest_reported_band": oldest})

    assoc = stats.get("aged_non_moving_association") or {}
    overlap = float(assoc.get("aged_non_moving_value") or 0.0)
    if overlap:
        lift = assoc.get("aged_rate_lift")
        lift_text = f", {lift:.1f}x the estate aged rate" if isinstance(lift, (int, float)) else ""
        add("ageing_aged_non_moving", "risk_intersection", "Aged and non-moving", overlap, 4,
            f"{_money(overlap, currency)} is both aged and has not sold since arrival{lift_text}.",
            "aged rate within non-moving stock versus the whole stock position",
            {"aged_rate_lift": lift,
             "aged_share_within_non_moving_pct": assoc.get("aged_share_within_non_moving_pct")})

    fresh_nm = float((report.get("risk_split") or {}).get("fresh_non_moving") or 0.0)
    if fresh_nm:
        add("ageing_not_aged_non_moving", "risk_intersection", "Not aged and non-moving",
            fresh_nm, 3,
            f"{_money(fresh_nm, currency)} is not classified as aged and has not sold since arrival.",
            "share of the current stock position")

    for role, dimension in (stats.get("dimensions") or {}).items():
        hotspots = (dimension or {}).get("hotspots") or []
        for hot in hotspots[: max(0, int(hotspot_limit_per_role))]:
            value = float(hot.get("excess_aged_value") or 0.0)
            member = str(hot.get("member") or "")
            add("ageing_rate_hotspot", role, member, value, 2,
                f"{member} holds {_money(value, currency)} more aged stock than its stock value would imply at the rest-of-estate rate; its aged rate is {hot['aged_rate_pct']:.1f}% versus {hot['rest_of_estate_rate_pct']:.1f}% elsewhere.",
                "aged-stock rate versus the rest of the estate",
                dict(hot))

    supplied = report.get("ageing_dimensions")
    dimension_rows = supplied if isinstance(supplied, dict) else {
        "location": report.get("locations") or [], "division": report.get("divisions") or []}
    concentration_floor = float((report.get("stat_config") or {}).get(
        "concentration_top1_pct", CONCENTRATION_TOP1_PCT))
    for role, dimension in (stats.get("dimensions") or {}).items():
        concentration = (dimension or {}).get("concentration") or {}
        if (concentration.get("top1_share_pct") or 0.0) < concentration_floor:
            continue
        rows = dimension_rows.get(role) or []
        leader = max(rows, key=lambda r: float(r.get("value") or 0.0), default={})
        value = float(leader.get("value") or 0.0)
        add("ageing_concentration", role, str(leader.get("name") or ""), value, 1,
            f"{leader.get('name')} holds {concentration['top1_share_pct']:.1f}% of all aged stock value across {role} members.",
            f"share of aged stock across {role} members", dict(concentration))

    quality = stats.get("quality") or {}
    if not quality.get("reconciled") or (quality.get("undetermined_value") or 0) > 0:
        findings.append({
            "candidate_id": "ageing_data_quality:estate",
            "story_key": _story_key(report_id, "ageing_data_quality", "estate", "", anchor),
            "report_id": report_id,
            "analysis_type": "ageing_data_quality",
            "dimension": "estate",
            "affected_segment": "Whole stock position",
            "impact_value": quality.get("undetermined_value") or 0.0,
            "impact_share": _pct(quality.get("undetermined_value") or 0.0, total),
            "score": 700.0,
            "severity": "critical",
            "comparison_label": "reconciliation and age-classification checks",
            "description": "The ageing position did not pass every reconciliation or classification check.",
            "failed_checks": quality.get("failed_checks") or [],
        })

    findings.sort(key=lambda item: (-float(item.get("score") or 0.0), item["candidate_id"]))
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"A{index}"
    return findings
