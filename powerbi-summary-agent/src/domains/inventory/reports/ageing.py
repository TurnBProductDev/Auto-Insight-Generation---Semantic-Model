"""Stock Age Analysis - the report model.

Deterministic: it takes the scanned rows and produces the page. No LLM decides
the structure, because every layer must be *covered* whether or not it has a
headline - the same argument the R6 dashboard makes. Prose slots are filled with
grounded sentences built from the figures themselves.

The order is the rulebook's, not a scoring choice
-------------------------------------------------
BR-28 states it: lead with 24+ months, then 12-24, then aged-and-non-moving,
then non-moving in fresh bands, then the division and location profiles, then
the LOCAL/OVERSEAS split. Total stock value and fresh share are **context, not
findings**, so they sit in the header rather than leading. A weighted blend
could outvote that instruction, so it is expressed as an explicit sequence.

Every figure is copied or derived arithmetically from the scan. Nothing here can
introduce a number the model did not return.
"""

from __future__ import annotations

from typing import Any, Sequence

from ....kernel.report import ReportSpec
from .. import ageing_history, ageing_outlook, ageing_stats, buckets, families

#: BR-26: below this a finding is not worth a manager's time - except in the
#: oldest band, where the write-off implication makes even a small value worth
#: naming.
MATERIAL_SAR = 250_000.0


SPEC = ReportSpec(
    report_id="inventory_ageing",
    report_name="Stock Age Analysis",
    domain="inventory",
    chain_id="inventory",
    cadence="daily",
    spine="snapshot_vs_policy",
    kpis=("stock_value", "aged_value", "high_risk_value", "non_moving_value"),
    axes=("age_band", "division", "section", "location", "sku_type"),
    layout="age_distribution",
    rules=("ageing_prose",),
    thresholds={
        "high_risk_call_out_sar": buckets.HIGH_RISK_CALL_OUT_SAR,
        "material_sar": MATERIAL_SAR,
    },
)


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _cell(row: dict, *names: str) -> Any:
    """Read a column whatever the executor named it."""
    for name in names:
        for key, value in (row or {}).items():
            cleaned = str(key).strip("[]").split("[")[-1].strip("]").lower()
            if cleaned == name.lower():
                return value
    return None


def _sar(value: Any, currency: str = "SAR") -> str:
    """Currency value, rounded sensibly: millions in headlines, exact below."""
    number = _num(value)
    if number is None:
        return "not available"
    if abs(number) >= 1_000_000:
        return f"{currency} {number / 1_000_000:.2f}M".strip()
    if abs(number) >= 1_000:
        return f"{currency} {number / 1_000:.0f}K".strip()
    return f"{currency} {number:,.0f}".strip()


def _pct(value: Any) -> str:
    number = _num(value)
    return "not available" if number is None else f"{number:.1f}%"


def _rank(rows: Sequence[dict], key: str, label: str, top: int = 5) -> list[dict]:
    """Rank members by one column, carrying the others through.

    ``high_risk`` is carried deliberately: the dashboard's second view is scoped
    to stock over a year old, and dropping the column here left that view with
    no breakdown at all.
    """
    ranked = []
    for row in rows:
        value = _num(_cell(row, key)) or 0.0
        name = _cell(row, label)
        if name is None:
            continue
        ranked.append({
            "name": str(name),
            "value": value,
            "total": _num(_cell(row, "value")) or 0.0,
            "high_risk": _num(_cell(row, "high_risk")) or 0.0,
            # Carried for the same reason ``high_risk`` is: the comparison
            # against an earlier position is measured in units, and a member
            # with no quantity here simply drops out of it.
            "qty": _num(_cell(row, "qty")) or 0.0,
            "aged_qty": _num(_cell(row, "aged_qty")) or 0.0,
        })
    ranked.sort(key=lambda item: item["value"], reverse=True)
    return ranked[:top]


def build(scan: dict, cfg: dict | None = None) -> dict:
    """The whole report model, from one scan. Pure.

    ``cfg`` supplies the thresholds the new sections are measured against
    (the clearance window, the category review line, the risk cut-off). It
    is optional so a caller with only a scan - the offline replays, the
    golden master - reproduces the previous model exactly.
    """
    cfg = cfg or {}
    header = (scan.get("snapshot") or [{}])[0]
    as_at = str(_cell(header, "as_at") or "").split("T")[0]
    total = _num(_cell(header, "total_value")) or 0.0
    aged = _num(_cell(header, "aged_value")) or 0.0
    currency = str(scan.get("currency") or "SAR")

    band_rows = [
        {"band": _cell(r, "NEW AGE", "new age"), "value": _num(_cell(r, "value")) or 0.0,
         "aged": _num(_cell(r, "aged")) or 0.0, "skus": _num(_cell(r, "skus")) or 0,
         "qty": _num(_cell(r, "qty")) or 0.0}
        for r in scan.get("bands") or []
    ]
    qty_by_band = {str(r["band"]): r["qty"] for r in band_rows if r.get("band")}
    distribution = buckets.build_distribution(band_rows)

    risk_rows = [
        {"non_moving": _cell(r, "non_moving_status"),
         "value": _num(_cell(r, "value")) or 0.0,
         "aged": _num(_cell(r, "aged")) or 0.0}
        for r in scan.get("risk_split") or []
    ]
    split = buckets.risk_split(risk_rows)

    # Reconciliation is the guarantee everything else rests on. Checked, and
    # reported honestly rather than assumed (Non-negotiable 12).
    checks = {
        "bands_sum_to_total": buckets.reconciles(
            [b.value for b in distribution.bands] + [distribution.undetermined_value],
            total),
        "aged_sums_to_total_aged": buckets.reconciles(
            [b.aged_value for b in distribution.bands], aged),
        "risk_split_sums_to_total": buckets.reconciles([split.total], total),
        "risk_split_aged_matches": buckets.reconciles([split.aged_total], aged),
    }

    report = {
        "report_id": SPEC.report_id,
        "report_name": SPEC.report_name,
        # Non-negotiable 18: a position, never a span.
        "period_label": f"as at {as_at}" if as_at else "as at the latest snapshot",
        "as_at": as_at,
        "currency": currency,
        "header": {
            "total_value": total,
            "aged_value": aged,
            "aged_share_pct": distribution.aged_share_pct,
            "high_risk_value": distribution.high_risk_value,
            "high_risk_share_pct": distribution.high_risk_share_pct,
            "aged_non_moving": split.aged_non_moving,
            "skus": _num(_cell(header, "skus")),
            "locations": _num(_cell(header, "locations")),
        },
        "distribution": {
            "bands": [
                {"name": b.name, "value": b.value, "share_pct": b.share_pct,
                 "aged_value": b.aged_value, "high_risk": b.high_risk,
                 "cumulative_older_pct": b.cumulative_older_pct}
                for b in distribution.bands
            ],
            "undetermined_value": distribution.undetermined_value,
        },
        "risk_split": {
            "aged_non_moving": split.aged_non_moving,
            "aged_moving": split.aged_moving,
            "fresh_non_moving": split.fresh_non_moving,
            "fresh_moving": split.fresh_moving,
            "non_moving_total": split.non_moving_total,
            "aged_total": split.aged_total,
        },
        "call_outs": buckets.call_outs(distribution),
        # Every division and every location, not a top-N: the dashboard's Detail
        # layer is meant to be complete, and 10 divisions is not a dump.
        "divisions": _rank(scan.get("divisions") or [], "aged", "DEPARTMENT", top=50),
        "locations": _rank(scan.get("locations") or [], "aged", "LOC_CODE", top=50),
        "sections": _rank(scan.get("sections_high_risk") or [], "aged", "SECTION", top=15),
        "sku_types": [
            {"name": str(_cell(r, "skutype")),
             "value": _num(_cell(r, "value")) or 0.0,
             "aged": _num(_cell(r, "aged")) or 0.0}
            for r in scan.get("skutype") or []
        ],
        "migration": buckets.migration(),
        "checks": checks,
        "caveats": list(distribution.caveats),
        "narrative": _narrative(distribution, split, total, aged, as_at, currency),
    }
    report["quantity"] = {
        "total_qty": _num(_cell(header, "total_qty")),
        "aged_qty": _num(_cell(header, "aged_qty")),
        "aged_skus": _num(_cell(header, "aged_skus")),
    }
    comparison = ageing_history.build(
        _current_position(report, qty_by_band), _history_position(scan))
    report["comparison"] = comparison
    report["migration"] = _band_movement(comparison)
    report["clearance"] = _clearance_section(scan, cfg)
    report["categories"] = _category_section(scan, cfg)
    report["stuck_lines"] = _stuck_section(scan, cfg)
    if comparison.get("available") and not comparison.get("value_comparable"):
        report["caveats"].append(
            "Stock value is calculated differently on the two dates being "
            "compared, so this report compares units and shares only. "
            + str((comparison.get("basis") or {}).get("reason") or ""))
    report["stat_check"] = ageing_stats.analyze(report)
    report["stat_signals"] = ageing_stats.detect(report)
    return report


# --- The sections that compare, forecast and rank ------------------------------
# Added once the source model started retaining a previous stock position and
# exposing the stock-status table. Each one is built only if its inputs are
# present, and each returns an explicit `available: False` with a reason when
# they are not - a missing section must read as "not available and here is why",
# never as a silent gap.


def _history_position(scan: dict) -> dict:
    """The earlier stock position, in the shape `ageing_history.build` expects."""
    header = (scan.get("history_snapshot") or [{}])[0]
    dims = scan.get("history_dimensions") or {}
    return {
        "as_at": str(_cell(header, "as_at") or "").split("T")[0],
        "skus": _num(_cell(header, "skus")) or 0.0,
        "bands": [
            {"name": str(r.get("name") or ""), "value": _num(r.get("value")) or 0.0,
             "qty": _num(r.get("qty")) or 0.0, "skus": _num(r.get("skus")) or 0.0}
            for r in scan.get("history_bands") or []
        ],
        "locations": dims.get("location") or [],
        "divisions": dims.get("division") or [],
    }


def _current_position(report: dict, qty_by_band: dict) -> dict:
    """Today's position, in the same shape, so the two can be compared."""
    bands = (report.get("distribution") or {}).get("bands") or []
    return {
        "as_at": report.get("as_at") or "",
        "skus": (report.get("header") or {}).get("skus") or 0.0,
        "bands": [
            {"name": b.get("name"), "value": b.get("value"),
             "qty": qty_by_band.get(str(b.get("name")), 0.0)}
            for b in bands
        ],
        "locations": [
            {"name": r.get("name"), "value": r.get("total"), "qty": r.get("qty"),
             "aged": r.get("value"), "aged_qty": r.get("aged_qty")}
            for r in report.get("locations") or []
        ],
        "divisions": [
            {"name": r.get("name"), "value": r.get("total"), "qty": r.get("qty"),
             "aged": r.get("value"), "aged_qty": r.get("aged_qty")}
            for r in report.get("divisions") or []
        ],
    }


def _clearance_section(scan: dict, cfg: dict) -> dict:
    rows = scan.get("clearance") or []
    if not rows:
        return {"available": False,
                "reason": "No selling-rate figures were returned, so how fast "
                          "the aged stock is likely to clear cannot be estimated."}
    # A row with no division name is stock-status velocity that does not map to
    # any division. It is not a division, so it never becomes a row - but its
    # size is carried through so the page can say what it is not counting.
    named = [r for r in rows if str(r.get("name") or "").strip()]
    unmapped = sum(_num(r.get("daily_qty")) or 0.0
                   for r in rows if not str(r.get("name") or "").strip())
    return ageing_outlook.clearance(
        named,
        horizon_days=int(cfg.get("ageing_clearance_days",
                                 ageing_outlook.DEFAULT_HORIZON_DAYS)
                         or ageing_outlook.DEFAULT_HORIZON_DAYS),
        unmapped_velocity=unmapped)


def _category_section(scan: dict, cfg: dict) -> dict:
    rows = scan.get("categories") or []
    if not rows:
        return {"available": False,
                "reason": "No category breakdown was returned, so the category "
                          "review check could not be run."}
    return ageing_outlook.categories(
        rows,
        threshold_pct=float(cfg.get("ageing_category_threshold_pct",
                                    ageing_outlook.DEFAULT_CATEGORY_THRESHOLD_PCT)
                            or ageing_outlook.DEFAULT_CATEGORY_THRESHOLD_PCT))


def _stuck_section(scan: dict, cfg: dict) -> dict:
    rows = scan.get("risk_lines") or []
    if not rows:
        return {"available": False,
                "reason": "No product lines were returned at or below the "
                          "ageing risk cut-off with enough money against them."}
    section = ageing_outlook.stuck_lines(
        rows,
        risk_cutoff=float(cfg.get("ageing_risk_score_cutoff",
                                  ageing_outlook.DEFAULT_RISK_CUTOFF)
                          or ageing_outlook.DEFAULT_RISK_CUTOFF),
        value_floor=float(cfg.get("ageing_risk_value_floor",
                                  ageing_outlook.DEFAULT_RISK_VALUE_FLOOR)
                          or ageing_outlook.DEFAULT_RISK_VALUE_FLOOR),
        top=int(cfg.get("ageing_risk_rows", 10) or 10))
    total = (scan.get("risk_total") or [{}])[0]
    # The number of lines at the cut-off across the whole estate, which is much
    # larger than the handful shown. Naming it stops the table reading as the
    # complete list of stuck stock.
    section["estate_lines"] = _num(_cell(total, "risk_lines"))
    section["estate_all_lines"] = _num(_cell(total, "all_lines"))
    return section


def _band_movement(comparison: dict) -> dict:
    """Bucket migration - available at last, and counted in units.

    `buckets.migration()` has refused this since the report was written, because
    the model held one snapshot. It now holds a previous one, so the band-by-band
    movement is computable. It is expressed in **units** rather than value
    because the valuation basis moved between the two dates, and a rightward
    shift measured in rebased money would be an artefact rather than a finding.
    """
    if not comparison.get("available"):
        return buckets.migration()
    bands = comparison.get("bands") or []
    if not bands:
        return buckets.migration()
    aged_floor = buckets.band_index("09-12 MONTHS")
    older = sum((b.get("qty_share_points") or 0.0) for b in bands
                if buckets.band_index(str(b.get("name"))) >= aged_floor)
    return {
        "available": True,
        "counted_in": "units",
        "prior_as_at": comparison.get("prior_as_at"),
        "as_at": comparison.get("as_at"),
        "bands": bands,
        "aged_share_points": older,
        "reason": "",
        "note": ("Movement between the two stock positions is counted in units. "
                 "Stock value is calculated differently on the two dates, so "
                 "comparing money would show a change that is not real."),
    }

def _narrative(distribution: buckets.Distribution, split: buckets.RiskSplit,
               total: float, aged: float, as_at: str,
               currency: str = "SAR") -> list[str]:
    """Grounded sentences, in BR-28's order. Every figure comes from the scan.

    Deliberately deterministic: BR-25 requires a number on every comparison, and
    BR-33's banned-word list rules out the vocabulary a free-form generator
    reaches for. A fallback that can dead-end is worse than one that is plain.
    """
    lines: list[str] = []

    oldest = distribution.band("24+ MONTHS")
    if oldest and oldest.value > 0:
        lines.append(
            f"{_sar(oldest.value, currency)} of stock is more than two years old, "
            f"{_pct(oldest.share_pct)} of all stock value as at {as_at}. This is "
            f"the most likely write-off candidate and is reported separately "
            f"from the 12-24 month band.")

    twelve = distribution.band("12-24 MONTHS")
    if twelve and twelve.value > 0:
        lines.append(
            f"A further {_sar(twelve.value, currency)} is between one and two years old "
            f"({_pct(twelve.share_pct)} of stock value). Together with the "
            f"24+ month band, {_sar(distribution.high_risk_value, currency)} is classed as "
            f"high-risk, {_pct(distribution.high_risk_share_pct)} of all stock.")

    if split.aged_non_moving > 0:
        lines.append(
            f"{_sar(split.aged_non_moving, currency)} is both aged and non-moving - old "
            f"stock with no recorded sales. This is the highest-risk "
            f"combination. It is not added to the aged total, because the two "
            f"measures overlap.")

    if split.fresh_non_moving > 0:
        lines.append(
            f"{_sar(split.fresh_non_moving, currency)} of stock under nine months old has "
            f"recorded no sales since it arrived. That is a demand or placement "
            f"signal rather than an age problem.")

    if aged and total:
        lines.append(
            f"Aged stock totals {_sar(aged, currency)}, {_pct(aged / total * 100.0)} of the "
            f"{_sar(total, currency)} held across all locations. The configured "
            f"ageing policy defines the threshold used for this report.")

    return lines
