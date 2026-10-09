"""One KPI card per story: merge cards that sit inside each other in a hierarchy.

The insight branch scans every hierarchy column on its own, so a single fall in
units can surface three times over. On SB Mart on 2026-10-06 the feed carried
PROVISIONS (a category), CONFECTIONERY (a product group inside it) and COVRD
CHOCO BARS AND TAB (a sub-group inside that), each "132-151% of the total
decline" - one story told three times, reading as three problems.

Nothing the run already holds says which member sits inside which: every scan
groups by one column, and the summary universe stops at Category. So the
nesting is asked of the model itself, with one bounded query per table, and only
when two cards could be nested at all - same table, same measure, same
direction, both on a merchandise level (``summary_focus_evidence``'s vocabulary)
and on different ones. A store is never a parent: it is orthogonal to the
merchandise hierarchy, and every store sells confectionery.

Of two nested cards the higher-ranked one stays, because the feed is already in
rank order. Best-effort throughout: with no query runner (offline, a replay) or
a query that fails, every card is kept exactly as before.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

_REF_RE = re.compile(r"^'?(?P<table>[^'\[\]]+)'?\[(?P<column>[^\]]+)\]$")
_STORE_RE = re.compile(r"\b(?:store|branch|location|loc|outlet)\b")
_MAX_ROWS = 2000


def column_ref(sig: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """``('MIS_DEEP_DIVE2', 'product_group_name')`` from a one-column dimension."""
    dims = sig.get("dimension")
    if isinstance(dims, str):
        dims = [dims]
    if not isinstance(dims, list) or len(dims) != 1:
        return None
    match = _REF_RE.match(str(dims[0]).strip())
    if not match:
        return None
    return match.group("table").strip(), match.group("column").strip()


def dimension_role(sig: Dict[str, Any]) -> Optional[str]:
    """The canonical role of the column a signal was measured on, or None."""
    ref = column_ref(sig)
    name = ref[1] if ref else str(sig.get("dimension") or "")
    from ..agents.summary_focus_evidence import _semantic_level

    _, role = _semantic_level(name)
    if role:
        return role
    words = re.sub(r"[^a-z0-9]+", " ", name.casefold())
    return "store" if _STORE_RE.search(words) else None


def _level(sig: Dict[str, Any]) -> Optional[int]:
    ref = column_ref(sig)
    if not ref:
        return None
    from ..agents.summary_focus_evidence import _semantic_level

    level, _ = _semantic_level(ref[1])
    return level


def _member(sig: Dict[str, Any]) -> Optional[str]:
    members = sig.get("segment_members")
    if isinstance(members, list) and len(members) == 1 and str(members[0]).strip():
        return str(members[0]).strip()
    segment = str(sig.get("affected_segment") or "").strip()
    return segment if segment and "," not in segment else None


def _sign(value: Any) -> int:
    return 1 if isinstance(value, (int, float)) and value >= 0 else -1


def candidate_pairs(signals: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every pair of cards that COULD be nested; the query decides which are."""
    pairs = []
    for i, a in enumerate(signals):
        for j in range(i + 1, len(signals)):
            b = signals[j]
            if a.get("kind") == "data_quality" or b.get("kind") == "data_quality":
                continue
            ref_a, ref_b = column_ref(a), column_ref(b)
            level_a, level_b = _level(a), _level(b)
            member_a, member_b = _member(a), _member(b)
            if not (ref_a and ref_b and member_a and member_b):
                continue
            if level_a is None or level_b is None or level_a == level_b:
                continue
            if ref_a[0].casefold() != ref_b[0].casefold():
                continue
            if str(a.get("metric_family") or "").casefold() != str(b.get("metric_family") or "").casefold():
                continue
            if _sign(a.get("impact_value")) != _sign(b.get("impact_value")):
                continue
            shallow, deep = ((i, ref_a, member_a), (j, ref_b, member_b)) if level_a < level_b \
                else ((j, ref_b, member_b), (i, ref_a, member_a))
            pairs.append({
                "ranks": (i, j),
                "table": ref_a[0],
                "parent": {"index": shallow[0], "column": shallow[1][1], "member": shallow[2]},
                "child": {"index": deep[0], "column": deep[1][1], "member": deep[2]},
            })
    return pairs


def _dax_string(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def probe_query(table: str, pairs: Sequence[Dict[str, Any]]) -> str:
    """Which combinations of the involved members exist, in one query.

    SUMMARIZE over the table returns only combinations that occur, filtered to
    rows touching any involved member - a few hundred at most, capped by TOPN.
    FILTER over the summarised table, never KEEPFILTERS (see Gotchas).
    """
    values: Dict[str, set] = {}
    for pair in pairs:
        for side in ("parent", "child"):
            values.setdefault(pair[side]["column"], set()).add(pair[side]["member"])
    quoted = "'" + table.replace("'", "''") + "'"
    columns = sorted(values)
    refs = [f"{quoted}[{column}]" for column in columns]
    tests = " || ".join(
        f"{quoted}[{column}] IN {{{', '.join(_dax_string(v) for v in sorted(values[column]))}}}"
        for column in columns
    )
    return (
        "EVALUATE\n"
        f"TOPN({_MAX_ROWS},\n"
        f"    FILTER(SUMMARIZE({quoted}, {', '.join(refs)}),\n"
        f"        {tests}\n"
        "    )\n"
        ")"
    )


def _rows(payload: Any) -> List[Dict[str, Any]]:
    try:
        return list(payload["results"][0]["tables"][0]["rows"])
    except (KeyError, IndexError, TypeError):
        return []


def _cell(row: Dict[str, Any], column: str) -> str:
    for key, value in row.items():
        if str(key).endswith(f"[{column}]") or str(key) == column:
            return str(value or "").strip().casefold()
    return ""


def nested_pairs(pairs: Sequence[Dict[str, Any]], payload: Any) -> List[Dict[str, Any]]:
    """The candidate pairs the model confirms: the child occurs inside the parent."""
    rows = _rows(payload)
    confirmed = []
    for pair in pairs:
        parent, child = pair["parent"], pair["child"]
        want = (parent["member"].casefold(), child["member"].casefold())
        if any((_cell(r, parent["column"]), _cell(r, child["column"])) == want for r in rows):
            confirmed.append(pair)
    return confirmed


def merge_nested(
    signals: Sequence[Dict[str, Any]],
    run_query: Optional[Callable[[str], Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Drop the lower-ranked card of every confirmed nested pair.

    ``run_query`` takes DAX and returns the executeQueries payload. None means
    there is no model to ask, and the feed is returned untouched.
    """
    signals = list(signals)
    pairs = candidate_pairs(signals)
    if not pairs:
        return signals, {"status": "no_candidates"}
    if run_query is None:
        return signals, {"status": "skipped", "reason": "no_query_runner", "pairs": len(pairs)}
    by_table: Dict[str, List[Dict[str, Any]]] = {}
    for pair in pairs:
        by_table.setdefault(pair["table"], []).append(pair)
    confirmed: List[Dict[str, Any]] = []
    try:
        for table, table_pairs in by_table.items():
            confirmed.extend(nested_pairs(table_pairs, run_query(probe_query(table, table_pairs))))
    except Exception as exc:  # noqa: BLE001 - a card left in beats a feed lost
        return signals, {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
    dropped = sorted({max(pair["ranks"]) for pair in confirmed})
    kept = [s for idx, s in enumerate(signals) if idx not in dropped]
    return kept, {
        "status": "ok",
        "pairs": len(pairs),
        "nested": [f"{p['child']['member']} inside {p['parent']['member']}" for p in confirmed],
        "dropped": [_member(signals[idx]) for idx in dropped],
    }
