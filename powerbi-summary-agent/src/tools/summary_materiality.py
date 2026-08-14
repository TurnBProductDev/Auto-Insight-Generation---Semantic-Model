"""Deterministic R4 materiality math + universe-row parsing (summary-only).

Pure functions: no state, no I/O, no LLM. Owns the exact cross-level materiality
formulas (§10), their reconciliation preconditions (§11), divide-by-max
normalization (§12), and the parser that turns executed universe-scan rows (with
broadcast ``__`` diagnostic columns) into the ``summary_focus_universe``
contract. Imports no insight module.
"""

from __future__ import annotations

import math
import re
from typing import Any

_TAIL_BRACKET = re.compile(r"\[([^\]]+)\]\s*$")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


# --- exact formulas (§10) ----------------------------------------------------
def area_change(current: Any, prior: Any) -> float | None:
    current_val, prior_val = _num(current), _num(prior)
    if current_val is None or prior_val is None:
        return None
    return current_val - prior_val


def global_impact_pct(change: Any, overall_current: Any) -> float | None:
    change_val, overall = _num(change), _num(overall_current)
    if change_val is None or overall is None or overall == 0:
        return None
    return abs(change_val) / abs(overall) * 100.0


def business_share_pct(current: Any, overall_current: Any) -> float | None:
    current_val, overall = _num(current), _num(overall_current)
    if current_val is None or overall is None or overall == 0:
        return None
    return abs(current_val) / abs(overall) * 100.0


def sibling_movement_impact_pct(change: Any, gross_sibling_change: Any) -> float | None:
    change_val, gross = _num(change), _num(gross_sibling_change)
    if change_val is None or gross is None or gross == 0:
        return None
    return abs(change_val) / abs(gross) * 100.0


def area_change_pct(change: Any, prior: Any) -> float | None:
    """Meaningful-movement %. Undefined (None) when prior is zero or absent."""
    change_val, prior_val = _num(change), _num(prior)
    if change_val is None or prior_val is None or prior_val == 0:
        return None
    return change_val / abs(prior_val) * 100.0


def reconciled(signed_sibling_change: Any, parent_change: Any, tolerance_pct: float) -> bool:
    """True when the signed sibling movement reconciles to the parent change."""
    signed, parent = _num(signed_sibling_change), _num(parent_change)
    if signed is None or parent is None:
        return False
    tol = max(0.0, float(tolerance_pct))
    denom = abs(parent) if parent != 0 else max(abs(signed), 1.0)
    return abs(signed - parent) <= denom * tol / 100.0


def compute_facts(member: dict, tolerance_pct: float = 2.0, spine: Any = None) -> dict:
    """Compute the four materiality metrics + reconciliation for one member.

    ``member`` carries current/prior/change plus the broadcast diagnostics
    overall_current, gross_sibling_change, signed_sibling_change, parent_change,
    full_member_count. Sibling movement impact is produced ONLY when the sibling
    breakdown is complete and reconciles - otherwise it is None and the member
    can qualify only through the business-share route.

    ``spine`` generalises what "the baseline" means (WP2): with none, the
    baseline is the prior period, which is the existing behaviour exactly. A
    spine supplies its own baseline slot and its own percentage, so a policy
    band or a target can be measured against with the same arithmetic.
    """
    current = member.get("current")
    prior = member.get("prior")
    if spine is not None and prior is None:
        prior = member.get("baseline")
    change = member.get("change")
    if change is None:
        change = area_change(current, prior)
    overall = member.get("overall_current")
    gross = member.get("gross_sibling_change")
    signed = member.get("signed_sibling_change")
    parent = member.get("parent_change")
    full = _num(member.get("full_member_count"))
    recon = reconciled(signed, parent, tolerance_pct)
    sibling = (
        sibling_movement_impact_pct(change, gross)
        if (recon and full and full > 0)
        else None
    )
    return {
        "area_change": change,
        "global_impact_pct": global_impact_pct(change, overall),
        "business_share_pct": business_share_pct(current, overall),
        "sibling_movement_impact_pct": sibling,
        "area_change_pct": area_change_pct(change, prior),
        "reconciled": recon,
        "sibling_usable": sibling is not None,
    }


def is_eligible(
    facts: dict,
    *,
    min_movement_pct: float,
    min_business_share_pct: float,
    min_change_pct: float,
) -> bool:
    """§11 gate: sibling movement impact, OR business share + meaningful movement.

    When the sibling breakdown does not reconcile, ``sibling_movement_impact_pct``
    is None, so only the business-share route can qualify the area.
    """
    sibling = facts.get("sibling_movement_impact_pct")
    if sibling is not None and sibling >= float(min_movement_pct):
        return True
    share = facts.get("business_share_pct")
    change_pct = facts.get("area_change_pct")
    return (
        share is not None
        and share >= float(min_business_share_pct)
        and change_pct is not None
        and abs(change_pct) >= float(min_change_pct)
    )


# --- divide-by-max normalization (§12) ---------------------------------------
def divide_by_max(values: list[Any]) -> list[float]:
    """Normalize |value| by the maximum |value|; a zero maximum yields all zeros."""
    magnitudes = [abs(v) for v in (_num(x) for x in values) if v is not None]
    peak = max(magnitudes) if magnitudes else 0.0
    if peak == 0:
        return [0.0 for _ in values]
    out: list[float] = []
    for raw in values:
        val = _num(raw)
        out.append(abs(val) / peak if val is not None else 0.0)
    return out


# --- universe-row parsing ----------------------------------------------------
def _clean_key(key: Any) -> str:
    match = _TAIL_BRACKET.search(str(key))
    return match.group(1) if match else str(key)


def _pick(row: dict, name: str) -> Any:
    """Read a value by bare column name, tolerating 'Table'[Col] result keys."""
    if name in row:
        return row[name]
    target = str(name).casefold()
    for key, value in row.items():
        if _clean_key(key).casefold() == target:
            return value
    return None


def parse_universe_rows(
    rows: list[dict],
    group_name: str,
    parent_names: list[str],
    tolerance_pct: float = 2.0,
    pool_rows: int | None = None,
) -> dict:
    """Turn executed universe-scan rows into members + role-level diagnostics.

    Diagnostic columns are per-parent broadcast scalars: each member's
    ``full_member_count`` is the count of siblings under *its own parent*, and
    ``gross_sibling_change`` is the full sibling set under that parent (never the
    returned TOPN). Role level therefore reports only what is meaningful across
    parents: whether the TOPN pool was capped (``pool_capped`` = returned hit the
    pool size, so more members exist than the rotation pool holds) and the
    largest per-parent sibling count seen (``max_siblings_per_parent``).
    """
    members: list[dict] = []
    reconciled_all = True
    full_counts: list[float] = []
    for row in rows or []:
        member_value = _pick(row, group_name)
        parents = [_pick(row, parent) for parent in parent_names]
        path = [str(part) for part in parents if str(part or "").strip()]
        if str(member_value or "").strip():
            path = path + [str(member_value)]
        current = _num(_pick(row, "__cur"))
        prior = _num(_pick(row, "__pri"))
        change = _num(_pick(row, "__chg"))
        if change is None:
            change = area_change(current, prior)
        raw = {
            "member": member_value,
            "hierarchy_path": path,
            "current": current,
            "prior": prior,
            "change": change,
            "change_pct": area_change_pct(change, prior),
            "overall_current": _num(_pick(row, "__overall_current")),
            "gross_sibling_change": _num(_pick(row, "__gross_sibling_change")),
            "signed_sibling_change": _num(_pick(row, "__signed_sibling_change")),
            "parent_change": _num(_pick(row, "__parent_change")),
            "full_member_count": _num(_pick(row, "__full_member_count")),
        }
        facts = compute_facts(raw, tolerance_pct)
        raw.update({
            "global_impact_pct": facts["global_impact_pct"],
            "business_share_pct": facts["business_share_pct"],
            "sibling_movement_impact_pct": facts["sibling_movement_impact_pct"],
            "reconciled": facts["reconciled"],
        })
        reconciled_all = reconciled_all and facts["reconciled"]
        if raw["full_member_count"]:
            full_counts.append(raw["full_member_count"])
        members.append(raw)

    returned = len(members)
    max_siblings = int(max(full_counts)) if full_counts else returned
    pool_capped = bool(pool_rows) and returned >= int(pool_rows)
    return {
        "members": members,
        "returned_member_count": returned,
        "max_siblings_per_parent": max_siblings,
        "pool_capped": pool_capped,
        "diagnostics_reconciled": reconciled_all and returned > 0,
    }
