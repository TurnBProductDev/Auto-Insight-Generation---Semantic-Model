"""Offline test for the deterministic insight-memory novelty filter (Phase 1).

No auth, no LLM, no Power BI. Exercises the story_key contract and the novelty
filter node against a fixture store, proving:

  * story_key is stable across field/candidate ordering;
  * it EXCLUDES direction and impact (a reversal maps to the SAME key), so Phase 4
    can re-alert on the same story;
  * case / whitespace / Unicode-form / member-order variants of a segment collide
    to one key, while different dataset / dimension / level / period differ;
  * a fixture store suppresses exactly the matching candidates;
  * per-level caps and the memory-disabled and corrupt-store paths behave;
  * commit() records every covered story_key (merge) and merges same-day journal.

Run from the project dir:

    python scripts/replay_novelty_filter.py

Store I/O is redirected to a throwaway temp dir so real memory is never touched.
"""

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import insight_novelty_filter as nf  # noqa: E402
from src.tools import insight_memory as mem  # noqa: E402

_FAILURES = []


def check(cond: bool, msg: str) -> None:
    status = "PASS" if cond else "FAIL"
    if not cond:
        _FAILURES.append(msg)
    print(f"  [{status}] {msg}")


def _candidate(**over) -> dict:
    base = {
        "id": "cand_01_change_contribution",
        "type": "change_contribution",
        "table": "meta_movers_by_dept",
        "metric": "revenue Growth",
        "segment": "CONSUMER GOODS",
        "segment_members": None,
        "impact_value": -1_224_468.0,
        "impact_share": None,
        "score": 90.0,
        "kind": "business",
    }
    base.update(over)
    return base


CONTRACTS = {
    "meta_movers_by_dept": {
        "coverage_kind": "paired_change_tails",
        "grouping_references": ["'MIS_DEEP_DIVE2'[DEPARTMENT]"],
        "metric_roles": {
            "revenue Growth": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                               "phase": "change", "family": "revenue"},
            "net revenue CURRENT": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                                    "phase": "current", "family": "revenue"},
            "net revenue PAST": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                                 "phase": "prior", "family": "revenue"}},
    },
    "meta_movers_by_section": {
        "coverage_kind": "paired_change_tails",
        "grouping_references": ["'MIS_DEEP_DIVE2'[SECTION]"],
        "metric_roles": {
            "revenue Growth": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                               "phase": "change", "family": "revenue"},
            "net revenue CURRENT": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                                    "phase": "current", "family": "revenue"},
            "net revenue PAST": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                                 "phase": "prior", "family": "revenue"}},
    },
}

DS = "dataset-A"
SCOPE = "scopehash0001"


def _key(cand, dataset=DS, anchor="2023-12"):
    contract = CONTRACTS.get(cand.get("table"), {})
    k, _ = mem.story_components(cand, dataset, SCOPE, contract, anchor)
    return k


def test_story_key() -> None:
    print("\n=== story_key contract ===")

    # ordering independence: two dicts, same semantics, different insertion order
    a = _candidate()
    b = _candidate(kind="business", impact_value=-1_224_468.0, segment="CONSUMER GOODS",
                   metric="revenue Growth", table="meta_movers_by_dept",
                   type="change_contribution", id="cand_99_change_contribution")
    check(_key(a) == _key(b), "story_key is independent of field/candidate ordering")

    # direction/impact excluded: a reversal is the SAME story
    up = _candidate(impact_value=+2_000_000.0)
    check(_key(a) == _key(up), "story_key excludes direction/impact (reversal = same key)")

    # normalization: case / whitespace / Unicode form / member order collide
    v_case = _candidate(segment="consumer goods")
    v_ws = _candidate(segment="  CONSUMER   GOODS ")
    v_uni = _candidate(segment="CONSUMER GOODS")  # non-breaking space -> NFKC space
    check(_key(a) == _key(v_case) == _key(v_ws) == _key(v_uni),
          "case / whitespace / Unicode variants of a segment collide")

    multi1 = _candidate(segment="A, B", segment_members=["Alpha", "Beta"])
    multi2 = _candidate(segment="B, A", segment_members=["beta", "ALPHA"])
    check(_key(multi1) == _key(multi2), "multi-segment member order/case is canonical")

    # things that MUST differ
    check(_key(a) != _key(a, dataset="dataset-B"), "different dataset -> different key")
    check(_key(a) != _key(a, anchor="2024-01"), "different period anchor -> different key")
    check(_key(a) != _key(_candidate(table="meta_movers_by_section")),
          "different dimension -> different key")
    check(_key(a) != _key(_candidate(type="concentration")),
          "different analysis type -> different key")
    check(_key(a) != _key(_candidate(segment="TECHNOLOGY")),
          "different segment -> different key")

    # canonical metric collapses phases of one family (via contract bundle_id)
    cur = _candidate(metric="net revenue CURRENT")
    chg = _candidate(metric="revenue Growth")
    check(_key(cur) == _key(chg),
          "current/change of one family collapse to one metric (contract bundle_id)")


def _state(records: dict, *, enabled=True, policy="never_repeat", corrupt=False) -> tuple[dict, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="novelty_replay_"))
    mem._dataset_dir = lambda state: tmp  # redirect store I/O
    store = tmp / "memory.json"
    if corrupt:
        store.write_text("{ this is not valid json", encoding="utf-8")
    else:
        store.write_text(json.dumps(
            {"schema_version": 1, "watermark": "2023-12-31",
             "records": records, "journal": {}}), encoding="utf-8")
    state = {
        "dataset_id": DS,
        "output_folder": "outputs_replay",
        "insight_memory_enabled": enabled,
        "insight_memory_policy": policy,
        "insight_memory_cooldown_days": 14,
        "insight_candidates_high": 20,
        "insight_candidates_weekly": 10,
        "insight_candidates_daily": 10,
        "insight_reporting_grain": "month",
        "insight_comparable_population": [],
        "insight_excluded_entities": [],
        "insight_evidence_contracts": CONTRACTS,
        "insight_clean_data": {"queries": [
            {"query_name": "x", "status": "success",
             "rows": [{"UPDATED_DATE": "2023-12-31T00:00:00", "v": 1}]}]},
        "logs": [], "errors": [],
    }
    return state, tmp


def test_novelty_filter() -> None:
    print("\n=== novelty filter node ===")
    seen = _candidate(segment="CONSUMER GOODS")
    fresh = _candidate(id="cand_02_change_contribution", segment="TECHNOLOGY",
                       impact_value=-1_991_123.0)
    # scope_hash/anchor the node will compute: [] scope, watermark 2023-12-31 -> 2023-12
    scope_h = mem.scope_hash({"insight_comparable_population": [],
                              "insight_excluded_entities": []})
    seen_key, _ = mem.story_components(seen, DS, scope_h,
                                       CONTRACTS["meta_movers_by_dept"], "2023-12")

    state, _tmp = _state({seen_key: {"level": "high", "last_reported": "2023-12-31",
                                     "times_reported": 1}})
    state["insight_stat_candidates"] = {"business_candidates": [seen, fresh],
                                        "data_quality_candidates": []}
    out = nf.run(state)
    nov = out["insight_novelty"]
    elig = out["insight_eligible_candidates"]["business_candidates"]
    check(nov["detected"] == 2, "detected counts all candidates")
    check(nov["suppressed"] == 1, "the already-reported candidate is suppressed")
    check(nov["eligible"] == 1 and elig[0]["segment"] == "TECHNOLOGY",
          "only the unseen (TECHNOLOGY) candidate is eligible")
    check(nov["reason"] == "ok" and nov["level_breakdown"].get("high") == 1,
          "reason=ok with a high-level breakdown")
    check(elig[0].get("story_key"), "eligible candidates carry a story_key for commit")

    # all suppressed -> reason all_previously_reported
    tech_key, _ = mem.story_components(fresh, DS, scope_h,
                                       CONTRACTS["meta_movers_by_dept"], "2023-12")
    state2, _t2 = _state({seen_key: {"level": "high", "last_reported": "2023-12-31"},
                          tech_key: {"level": "high", "last_reported": "2023-12-31"}})
    state2["insight_stat_candidates"] = {"business_candidates": [seen, fresh],
                                         "data_quality_candidates": []}
    nov2 = nf.run(state2)["insight_novelty"]
    check(nov2["eligible"] == 0 and nov2["reason"] == "all_previously_reported",
          "everything seen -> all_previously_reported")

    # disabled -> pass-through
    state3, _t3 = _state({seen_key: {"level": "high", "last_reported": "2023-12-31"}},
                         enabled=False)
    state3["insight_stat_candidates"] = {"business_candidates": [seen, fresh],
                                         "data_quality_candidates": []}
    nov3 = nf.run(state3)["insight_novelty"]
    check(nov3["reason"] == "memory_disabled" and nov3["eligible"] == 2,
          "memory disabled -> pass-through, nothing suppressed")

    # corrupt -> fail loud, all eligible
    state4, _t4 = _state({}, corrupt=True)
    state4["insight_stat_candidates"] = {"business_candidates": [seen, fresh],
                                         "data_quality_candidates": []}
    nov4 = nf.run(state4)["insight_novelty"]
    check(nov4["memory_status"] == "corrupt" and nov4["reason"] == "memory_corrupt"
          and nov4["eligible"] == 2,
          "corrupt store -> memory_corrupt, all candidates eligible (never silently drop)")


def test_commit_merge() -> None:
    print("\n=== commit (merge + same-day journal) ===")
    state, tmp = _state({})
    scope_h = mem.scope_hash(state)
    primary = _candidate(segment="CONSUMER GOODS")
    related = _candidate(id="cand_07_concentration", type="concentration",
                         table="meta_movers_by_section", segment="CONSUMER GOODS")
    pk, _ = mem.story_components(primary, DS, scope_h, CONTRACTS["meta_movers_by_dept"], "2023-12")
    rk, _ = mem.story_components(related, DS, scope_h, CONTRACTS["meta_movers_by_section"], "2023-12")

    signal = {"id": "consumer_goods_story", "kind": "business", "level": "high",
              "description": "CONSUMER GOODS revenue fell", "impact_value": -1_224_468.0,
              "story_key": pk, "covered_story_keys": [pk, rk]}
    res = mem.commit(state, [signal])
    memory, status = mem.load_store(state)
    check(res["status"] == "ok" and res["committed"] == 1, "commit ok")
    check(pk in memory["records"] and rk in memory["records"],
          "both primary and merged (covered) story_keys are recorded")
    check(memory["records"][rk].get("merged_into") == pk, "merged key points at its primary")

    # second same-day commit of the SAME story -> one journal entry, not two
    mem.commit(state, [signal])
    memory2, _ = mem.load_store(state)
    day = next(iter(memory2["journal"]))
    check(len(memory2["journal"][day]) == 1, "same-day re-commit merges the journal entry")
    check(memory2["records"][pk]["times_reported"] == 2, "times_reported increments")

    # markdown regenerated and JSON safe
    md = (tmp / "daily_insights.md").read_text(encoding="utf-8")
    check("CONSUMER GOODS revenue fell" in md, "daily_insights.md rendered from journal")
    json.dumps(memory2, allow_nan=False, default=str)


def test_policy() -> None:
    print("\n=== suppression policy ===")
    recs = {"high:v1:abc": {"last_reported": "2023-12-01"},
            "high:v1:def": {"last_reported": "2023-12-30"}}
    never = mem.suppressed(recs, "never_repeat", 14)
    check(never == set(recs), "never_repeat suppresses all reported stories")
    cool = mem.suppressed(recs, "cooldown", 14, today="2023-12-31")
    check(cool == {"high:v1:def"},
          "cooldown suppresses only recently-reported stories (older resurfaces)")


def main() -> int:
    test_story_key()
    test_novelty_filter()
    test_commit_merge()
    test_policy()
    print("\n" + "=" * 50)
    if _FAILURES:
        print(f"{len(_FAILURES)} CHECK(S) FAILED:")
        for f in _FAILURES:
            print(f"  - {f}")
        return 1
    print("All novelty-filter replay checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
