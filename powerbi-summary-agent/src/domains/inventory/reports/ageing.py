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
from .. import buckets, families

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


def _sar(value: Any) -> str:
    """SAR, rounded sensibly (BR-25): millions in headlines, exact below."""
    number = _num(value)
    if number is None:
        return "not available"
    if abs(number) >= 1_000_000:
        return f"SAR {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"SAR {number / 1_000:.0f}K"
    return f"SAR {number:,.0f}"


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
        })
    ranked.sort(key=lambda item: item["value"], reverse=True)
    return ranked[:top]


def build(scan: dict) -> dict:
    """The whole report model, from one scan. Pure."""
    header = (scan.get("snapshot") or [{}])[0]
    as_at = str(_cell(header, "as_at") or "").split("T")[0]
    total = _num(_cell(header, "total_value")) or 0.0
    aged = _num(_cell(header, "aged_value")) or 0.0

    band_rows = [
        {"band": _cell(r, "NEW AGE", "new age"), "value": _num(_cell(r, "value")) or 0.0,
         "aged": _num(_cell(r, "aged")) or 0.0, "skus": _num(_cell(r, "skus")) or 0}
        for r in scan.get("bands") or []
    ]
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

    return {
        "report_id": SPEC.report_id,
        "report_name": SPEC.report_name,
        # Non-negotiable 18: a position, never a span.
        "period_label": f"as at {as_at}" if as_at else "as at the latest snapshot",
        "as_at": as_at,
        "currency": "SAR",
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
        "narrative": _narrative(distribution, split, total, aged, as_at),
    }


def _narrative(distribution: buckets.Distribution, split: buckets.RiskSplit,
               total: float, aged: float, as_at: str) -> list[str]:
    """Grounded sentences, in BR-28's order. Every figure comes from the scan.

    Deliberately deterministic: BR-25 requires a number on every comparison, and
    BR-33's banned-word list rules out the vocabulary a free-form generator
    reaches for. A fallback that can dead-end is worse than one that is plain.
    """
    lines: list[str] = []

    oldest = distribution.band("24+ MONTHS")
    if oldest and oldest.value > 0:
        lines.append(
            f"{_sar(oldest.value)} of stock is more than two years old, "
            f"{_pct(oldest.share_pct)} of all stock value as at {as_at}. This is "
            f"the most likely write-off candidate and is reported separately "
            f"from the 12-24 month band.")

    twelve = distribution.band("12-24 MONTHS")
    if twelve and twelve.value > 0:
        lines.append(
            f"A further {_sar(twelve.value)} is between one and two years old "
            f"({_pct(twelve.share_pct)} of stock value). Together with the "
            f"24+ month band, {_sar(distribution.high_risk_value)} is classed as "
            f"high-risk, {_pct(distribution.high_risk_share_pct)} of all stock.")

    if split.aged_non_moving > 0:
        lines.append(
            f"{_sar(split.aged_non_moving)} is both aged and non-moving - old "
            f"stock with no recorded sales. This is the highest-risk "
            f"combination. It is not added to the aged total, because the two "
            f"measures overlap.")

    if split.fresh_non_moving > 0:
        lines.append(
            f"{_sar(split.fresh_non_moving)} of stock under nine months old has "
            f"recorded no sales since it arrived. That is a demand or placement "
            f"signal rather than an age problem.")

    if aged and total:
        lines.append(
            f"Aged stock totals {_sar(aged)}, {_pct(aged / total * 100.0)} of the "
            f"{_sar(total)} held across all locations. Food divisions cross the "
            f"aged threshold at six months and all others at nine.")

    return lines
