"""Offline proof that the KPI feed tells a nested story once.

On SB Mart on 2026-10-06 the Sales YoY feed carried PROVISIONS (a category),
CONFECTIONERY (a product group inside it) and COVRD CHOCO BARS AND TAB (a
sub-group inside that), each "132-151% of the total decline" - one fall in units
told three times. ``card_lineage`` asks the model which members sit inside
which and keeps the highest-ranked card of each nested set.

No Power BI, Azure or LLM credentials are required: the query runner is a
recorder that answers from a fixture.

    python scripts/replay_card_lineage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import card_lineage as cl  # noqa: E402

FAILURES: list[str] = []
TABLE = "MIS_DEEP_DIVE2"


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}"
          + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _sig(segment: str, column: str, value: float, family: str = "quantity",
         kind: str = "business", sid: str = "") -> dict:
    return {
        "id": sid or segment.lower().replace(" ", "_"),
        "kind": kind,
        "affected_segment": segment,
        "dimension": [f"'{TABLE}'[{column}]"],
        "metric_family": family,
        "impact_value": value,
    }


def _feed() -> list[dict]:
    # Rank order, as the feed arrives: the product group first.
    return [
        _sig("CONFECTIONERY", "product_group_name", -637_600.0),
        _sig("PROVISIONS", "item_category_name", -577_000.0),
        _sig("COVRD CHOCO BARS AND TAB", "special_product_group_name", -556_700.0),
        _sig("ST4", "store_no", 1_240_000.0, family="revenue"),
    ]


def _payload(rows: list[dict]) -> dict:
    return {"results": [{"tables": [{"rows": rows}]}]}


def _row(category: str, group: str, sub: str) -> dict:
    return {f"{TABLE}[item_category_name]": category,
            f"{TABLE}[product_group_name]": group,
            f"{TABLE}[special_product_group_name]": sub}


NESTED_ROWS = [
    _row("PROVISIONS", "CONFECTIONERY", "COVRD CHOCO BARS AND TAB"),
    _row("PROVISIONS", "CONFECTIONERY", "BOXED CHOCOLATE"),
    _row("PROVISIONS", "SNACKS", "CRISPS"),
]


def test_levels() -> None:
    print("\nLevels come from the shared hierarchy vocabulary")
    feed = _feed()
    check("a category is a category", cl.dimension_role(feed[1]) == "category")
    check("a product group is a product group", cl.dimension_role(feed[0]) == "product_group")
    check("a sub-group is a special product group",
          cl.dimension_role(feed[2]) == "special_product_group")
    check("a store is recognised, but as a store", cl.dimension_role(feed[3]) == "store")


def test_candidates() -> None:
    print("\nOnly cards that could be nested are put to the model")
    pairs = cl.candidate_pairs(_feed())
    check("the three merchandise cards make three pairs", len(pairs) == 3, str(len(pairs)))
    members = {m for p in pairs for m in (p["parent"]["member"], p["child"]["member"])}
    check("a store is never a parent or a child", "ST4" not in members, str(members))
    parents = {(p["parent"]["member"], p["child"]["member"]) for p in pairs}
    check("the broader level is always the parent",
          ("PROVISIONS", "CONFECTIONERY") in parents
          and ("CONFECTIONERY", "COVRD CHOCO BARS AND TAB") in parents, str(parents))

    rising = _feed()[:2]
    rising[1] = dict(rising[1], impact_value=10.0)
    check("a rise and a fall are different stories", not cl.candidate_pairs(rising))
    mixed = [_feed()[0], _sig("PROVISIONS", "item_category_name", -1.0, family="revenue")]
    check("units and revenue are different stories", not cl.candidate_pairs(mixed))
    dq = [_feed()[0], _sig("PROVISIONS", "item_category_name", -1.0, kind="data_quality")]
    check("a data-quality card is never merged", not cl.candidate_pairs(dq))
    same = [_feed()[0], _sig("SNACKS", "product_group_name", -1.0)]
    check("two members of the same level are siblings, not nested", not cl.candidate_pairs(same))


def test_query() -> None:
    print("\nThe probe is one bounded, filter-safe query")
    pairs = cl.candidate_pairs(_feed())
    dax = cl.probe_query(TABLE, pairs)
    check("it summarises only combinations that occur", "SUMMARIZE(" in dax)
    check("it is bounded", "TOPN(" in dax)
    check("it never uses KEEPFILTERS (see Gotchas)", "KEEPFILTERS" not in dax.upper())
    check("it filters on every involved member",
          all(m in dax for m in ("PROVISIONS", "CONFECTIONERY", "COVRD CHOCO BARS AND TAB")))
    quoted = cl.probe_query(TABLE, cl.candidate_pairs([
        _sig('BRAND "X"', "product_group_name", -2.0),
        _sig("PROVISIONS", "item_category_name", -1.0)]))
    check("a quote in a member name is escaped", '"BRAND ""X"""' in quoted, quoted)


def test_merge() -> None:
    print("\nNested cards collapse to the highest-ranked one")
    asked: list[str] = []

    def runner(dax: str) -> dict:
        asked.append(dax)
        return _payload(NESTED_ROWS)

    kept, receipt = cl.merge_nested(_feed(), runner)
    names = [s["affected_segment"] for s in kept]
    check("one query for one table", len(asked) == 1, str(len(asked)))
    check("the top-ranked card of the chain stays", names[0] == "CONFECTIONERY", str(names))
    check("the parent and the child of it go",
          "PROVISIONS" not in names and "COVRD CHOCO BARS AND TAB" not in names, str(names))
    check("the unrelated store card stays", "ST4" in names, str(names))
    check("the receipt says what was merged",
          receipt.get("status") == "ok" and len(receipt.get("nested") or []) == 3, str(receipt))

    siblings = [_row("PROVISIONS", "SNACKS", "CRISPS"),
                _row("FRESH", "CONFECTIONERY", "BOXED CHOCOLATE"),
                _row("FRESH", "DAIRY", "COVRD CHOCO BARS AND TAB")]
    kept, _ = cl.merge_nested(_feed(), lambda dax: _payload(siblings))
    check("members that never occur together are all kept", len(kept) == 4,
          str([s["affected_segment"] for s in kept]))


def test_fails_safe() -> None:
    print("\nWith no model to ask, or a failed query, nothing is lost")
    feed = _feed()
    kept, receipt = cl.merge_nested(feed, None)
    check("offline: the feed is untouched", kept == feed)
    check("...and the receipt says why", receipt.get("status") == "skipped", str(receipt))

    def broken(dax: str) -> dict:
        raise RuntimeError("Power BI said no")

    kept, receipt = cl.merge_nested(feed, broken)
    check("a failed query keeps every card", kept == feed)
    check("...and is reported, not raised", receipt.get("status") == "failed", str(receipt))
    kept, receipt = cl.merge_nested([feed[3]], broken)
    check("a feed with nothing to compare never queries",
          receipt.get("status") == "no_candidates", str(receipt))


def main() -> int:
    print("=" * 72)
    print("REPLAY: one KPI card per nested story")
    print("=" * 72)
    test_levels()
    test_candidates()
    test_query()
    test_merge()
    test_fails_safe()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
