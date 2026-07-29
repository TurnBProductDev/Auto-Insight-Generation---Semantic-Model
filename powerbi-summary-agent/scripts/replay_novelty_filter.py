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
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import insight_daily as di  # noqa: E402
from src.agents import insight_novelty_filter as nf  # noqa: E402
from src.agents import insight_signal_detector as sd  # noqa: E402
from src.agents import insight_stat_detector as stat  # noqa: E402
from src.tools import insight_memory as mem  # noqa: E402
from src.tools import insight_tiles  # noqa: E402
from src.utils.logger import RunLogger  # noqa: E402

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


def test_cap_after_memory() -> None:
    print("\n=== candidate cap happens after memory ===")
    candidates = [
        _candidate(id=f"cand_{i:02d}_change_contribution", segment=segment, score=score)
        for i, (segment, score) in enumerate(
            [("SEEN A", 100.0), ("SEEN B", 90.0), ("NEW C", 80.0)], start=1
        )
    ]

    # The deterministic detector must retain all deduplicated findings even when
    # the configured downstream shortlist is only two.  Otherwise NEW C would be
    # discarded before the novelty filter can discover that A and B are old.
    detector_state = {
        "insight_stat_max_candidates": 2,
        "insight_candidates_high": 2,
        "insight_evidence_contracts": CONTRACTS,
        "logs": [], "errors": [],
    }
    detector = stat._Detector(detector_state, RunLogger(detector_state))
    detector.business = {str(i): dict(c) for i, c in enumerate(candidates)}
    detected = detector.run({"queries": []})
    check(len(detected["business_candidates"]) == 3,
          "stat detector does not discard candidate 3 before memory suppression")

    scope_h = mem.scope_hash({"insight_comparable_population": [],
                              "insight_excluded_entities": []})
    records = {}
    for cand in candidates[:2]:
        key, _ = mem.story_components(cand, DS, scope_h,
                                      CONTRACTS["meta_movers_by_dept"], "2023-12")
        records[key] = {"level": "high", "last_reported": "2023-12-31"}

    state, _tmp = _state(records)
    state["insight_stat_max_candidates"] = 2
    state["insight_candidates_high"] = 2
    state["insight_stat_candidates"] = detected
    out = nf.run(state)
    nov = out["insight_novelty"]
    eligible = out["insight_eligible_candidates"]["business_candidates"]
    check(nov["detected"] == 3 and nov["suppressed"] == 2,
          "memory checks all three detector candidates before applying the cap")
    check(nov["unseen"] == 1 and nov["eligible"] == 1
          and eligible[0]["segment"] == "NEW C",
          "the lower-ranked unseen candidate survives after the two higher-ranked seen stories")

    # With no memory matches, the same limit still keeps only the strongest two
    # unseen candidates for the LLM context.
    fresh_state, _tmp2 = _state({})
    fresh_state["insight_stat_max_candidates"] = 2
    fresh_state["insight_candidates_high"] = 3
    fresh_state["insight_stat_candidates"] = detected
    fresh_out = nf.run(fresh_state)
    fresh_eligible = fresh_out["insight_eligible_candidates"]["business_candidates"]
    check([c["segment"] for c in fresh_eligible] == ["SEEN A", "SEEN B"]
          and fresh_out["insight_novelty"]["cap_dropped"] == 1,
          "overall cap keeps the top two only after memory suppression")


def test_scope_note_is_not_an_insight_tile() -> None:
    print("\n=== one-time scope note is not an insight tile ===")
    report = """# Key Insights

All findings below compare the same business population across both periods.

**Revenue increased in the leading segment.** The increase was concentrated in one area.

**Quantity declined in another segment.** The decline was spread across several areas.

# Data Quality Watch-outs

None observed in this run.
"""
    parsed = insight_tiles._insights_from_md(report)
    check(len(parsed) == 2,
          "the unbolded scope sentence is ignored while both bold insight paragraphs remain")
    check(parsed[0][0] == "Revenue increased in the leading segment."
          and parsed[1][0] == "Quantity declined in another segment.",
          "tile headings still come from each bold business takeaway")


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
    res = mem.commit_run(state, [signal])
    memory, status = mem.load_store(state)
    check(res["status"] == "ok" and res["committed"] == 1, "commit ok")
    check(pk in memory["records"] and rk in memory["records"],
          "both primary and merged (covered) story_keys are recorded")
    check(memory["records"][rk].get("merged_into") == pk, "merged key points at its primary")

    # second same-day commit of the SAME story -> one journal entry, not two
    mem.commit_run(state, [signal])
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


_WEEK_CONTRACT = {
    "coverage_kind": "recent_week_history",
    "metric_roles": {"net revenue CURRENT": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                                             "phase": "current", "family": "revenue"}},
}


def _week_cand(week_start="2026-07-13", **over) -> dict:
    base = {
        "id": "cand_01_recent_week_movement",
        "type": "recent_week_movement",
        "level": "recent_week",   # the novelty filter tags this before story_components runs
        "table": "meta_recent_week_history",
        "metric": "net revenue CURRENT",
        "segment": "overall (comparable base)",
        "anchor": week_start,
        "axis": "'MIS_DEEP_DIVE2'[POSTING_DATE]",
        "week_start": week_start,
        "week_end": (date.fromisoformat(week_start) + timedelta(days=6)).isoformat(),
        "impact_value": -1_500_000.0,
        "impact_share": None,
        "score": 15.0,
        "kind": "business",
        "recent_week": {"week_start": week_start, "change_pct": -15.0, "actual": 8.5e6,
                        "previous": 10.0e6, "expected": 10.0e6, "abs_impact": -1.5e6,
                        "facets": {"week_over_week": True, "abnormal_vs_baseline": True}},
    }
    base.update(over)
    return base


def _wk_key(cand) -> str:
    return mem.story_components(cand, DS, SCOPE, _WEEK_CONTRACT, "2026-07")[0]


def test_recent_week_memory() -> None:
    print("\n=== recent_week story_key + suppression (Phase 3) ===")
    a = _week_cand("2026-07-13")
    reversal = _week_cand("2026-07-13", id="cand_09", impact_value=+2_000_000.0,
                          recent_week={**a["recent_week"], "change_pct": +20.0, "abs_impact": 2e6})
    nextw = _week_cand("2026-07-20")
    check(_wk_key(a) == _wk_key(reversal),
          "same week + reversal -> same recent_week story_key (excludes direction/impact)")
    check(_wk_key(a) != _wk_key(nextw), "the following completed week -> a new story_key")
    check(_wk_key(a) != _wk_key(_week_cand("2026-07-13", axis="'MIS_DEEP_DIVE2'[OTHER_DATE]")),
          "a different selected date axis -> a different key")

    # suppression through the node: eligible once, suppressed after commit, next week fresh
    state, _tmp = _state({})
    state["insight_evidence_contracts"] = {"meta_recent_week_history": _WEEK_CONTRACT}
    state["insight_stat_candidates"] = {"business_candidates": [a], "data_quality_candidates": []}
    out = nf.run(state)
    elig = out["insight_eligible_candidates"]["business_candidates"]
    check(len(elig) == 1 and elig[0].get("level") == "recent_week",
          "recent_week candidate is eligible and tagged the recent_week level")
    key = elig[0]["story_key"]
    mem.commit_run(state, [{"id": "wk", "kind": "business", "level": "recent_week",
                            "description": "the week fell", "impact_value": -1.5e6,
                            "story_key": key, "covered_story_keys": [key],
                            "week_start": "2026-07-13", "week_end": "2026-07-19"}])
    out2 = nf.run(state)
    check(out2["insight_novelty"]["suppressed"] == 1 and out2["insight_novelty"]["eligible"] == 0,
          "the same completed week is suppressed on a later run")
    state["insight_stat_candidates"] = {"business_candidates": [nextw], "data_quality_candidates": []}
    out3 = nf.run(state)
    check(out3["insight_novelty"]["eligible"] == 1,
          "the following completed week is eligible (a new story)")


def test_rank_and_backfill() -> None:
    print("\n=== materiality-only ranking + per-level backfill (no reserved slots) ===")

    # _rank_and_cap: pure score ranking, no level gets priority.
    week_sig = {"id": "wk", "level": "recent_week", "kind": "business", "score": 5.0}
    highs = [{"id": f"h{i}", "level": "high", "kind": "business", "score": 90.0 - i}
             for i in range(5)]
    kept = sd._rank_and_cap([*highs, week_sig], cap=3, max_dq=2)
    check(len(kept) == 3 and all(s["level"] == "high" for s in kept),
          "a low-score recent_week signal does NOT jump ahead of higher-score high signals")
    week_sig_hot = {"id": "wk2", "level": "recent_week", "kind": "business", "score": 999.0}
    kept2 = sd._rank_and_cap([*highs, week_sig_hot], cap=3, max_dq=2)
    check(kept2[0]["id"] == "wk2",
          "a genuinely material recent_week signal DOES rank first on its own score")

    # _backfill_uncovered: a whole level with eligible material candidates but zero
    # bound signals gets its single best candidate injected (not every candidate).
    cand = _week_cand("2026-07-13")
    cand.update({"level": "recent_week", "score": 40.0, "story_key": "recent_week:v1:abc",
                 "story_fields": {"metric": "MIS_DEEP_DIVE2::revenue", "segment": "overall",
                                  "axis": "'MIS_DEEP_DIVE2'[POSTING_DATE]", "anchor": "2026-07-13"}})
    cand2 = _week_cand("2026-07-13", id="cand_02")
    cand2.update({"level": "recent_week", "score": 10.0, "story_key": "recent_week:v1:def"})
    eligible = {"business_candidates": [cand, cand2], "data_quality_candidates": []}
    backfilled = sd._backfill_uncovered([], eligible)
    check(len(backfilled) == 1 and backfilled[0].get("candidate_id") == cand["id"],
          "an uncovered level backfills only its single BEST candidate, not every eligible one")
    check(backfilled[0].get("injected") and backfilled[0].get("recent_week"),
          "the backfilled signal carries structured facts and is marked injected")

    already_bound = [{"candidate_id": cand["id"], "level": "recent_week",
                      "related_candidate_ids": []}]
    check(sd._backfill_uncovered(already_bound, eligible) == already_bound,
          "a level the LLM already covered is never backfilled")

    high_cand = {"id": "h1", "level": "high", "score": 50.0, "story_key": "high:v1:x"}
    mixed_eligible = {"business_candidates": [cand, high_cand], "data_quality_candidates": []}
    only_high_bound = [{"candidate_id": "h1", "level": "high", "related_candidate_ids": []}]
    out = sd._backfill_uncovered(only_high_bound, mixed_eligible)
    check(len(out) == 2 and any(s.get("level") == "recent_week" for s in out),
          "high is covered (skipped) while the untouched recent_week level is backfilled")


def _business_days(start: date, n: int) -> list:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _daily_state(daily_cursor: dict | None = None) -> tuple[dict, Path]:
    state, tmp = _state({})
    store = tmp / "memory.json"
    data = json.loads(store.read_text(encoding="utf-8"))
    data["daily_cursor"] = daily_cursor or {}
    store.write_text(json.dumps(data, default=str), encoding="utf-8")
    state.update({"insight_daily_enabled": True, "insight_daily_recent_days": 3,
                 "insight_daily_rolling_window": 28, "insight_daily_min_weekday_occurrences": 3,
                 "insight_daily_z_cutoff": 3.0, "insight_daily_materiality_pct": 3.0})
    return state, tmp


def test_daily_recency() -> None:
    print("\n=== daily recency (Phase 3b) ===")
    days = _business_days(date(2026, 1, 5), 90)
    eff = days[-1]
    old_day, recent_day = days[35], days[-3]  # both past the 28-day warm-up
    rows = [{"POSTING_DATE": d.isoformat(), "rev_cur": 1000.0} for d in days]
    for r in rows:
        if r["POSTING_DATE"] in (old_day.isoformat(), recent_day.isoformat()):
            r["rev_cur"] = 5000.0
    source = {
        "axis_key": "POSTING_DATE", "axis_reference": "'F'[POSTING_DATE]",
        "value_alias": "rev_cur", "additive_aliases": ["rev_cur"],
        "rows": rows, "operating_days": [0, 1, 2, 3, 4],
        "data_as_of": eff.isoformat(), "effective_data_as_of": eff.isoformat(),
    }

    # First-ever run for this axis: no stored cursor -> only the recent-days
    # clause applies (no doubled window from a seeded cursor).
    state1, _t1 = _daily_state()
    state1["insight_business_day_source"] = source
    out1 = di.run(state1)
    starts1 = {r["episode_start"] for r in out1["insight_clean_data"]["queries"][-1]["rows"]}
    check(recent_day.isoformat() in starts1,
          "first run: the RECENT incident is eligible (within recent_days of effective_data_as_of)")
    check(old_day.isoformat() not in starts1,
          "first run: the OLD incident is excluded (no prior cursor, outside recent_days)")
    check(out1["insight_daily_verdict"]["analysis_complete"] is True,
          "a healthy run reports analysis_complete=True")

    # Cursor already advanced PAST the old incident: it's both too old AND
    # already-known -> stays excluded. The recent incident is unaffected.
    state2, _t2 = _daily_state(daily_cursor={"'F'[POSTING_DATE]": days[50].isoformat()})
    state2["insight_business_day_source"] = source
    out2 = di.run(state2)
    starts2 = {r["episode_start"] for r in out2["insight_clean_data"]["queries"][-1]["rows"]}
    check(old_day.isoformat() not in starts2,
          "cursor past the old incident, outside recent_days -> stays excluded")
    check(recent_day.isoformat() in starts2, "the recent incident remains eligible")

    # Cursor BEFORE the old incident: it now "extends known territory" and
    # becomes eligible even though it's outside the recent_days window.
    state3, _t3 = _daily_state(daily_cursor={"'F'[POSTING_DATE]": days[20].isoformat()})
    state3["insight_business_day_source"] = source
    out3 = di.run(state3)
    starts3 = {r["episode_start"] for r in out3["insight_clean_data"]["queries"][-1]["rows"]}
    check(old_day.isoformat() in starts3,
          "a cursor BEFORE the old incident makes it eligible (extends known territory)")


def test_commit_run_observations() -> None:
    print("\n=== commit_run: observed vs. reported (Phase 3b) ===")
    state, tmp = _state({})
    state["insight_daily_verdict"] = {"analysis_complete": True}
    state["insight_business_day_source"] = {
        "axis_key": "POSTING_DATE", "axis_reference": "'F'[POSTING_DATE]",
        "effective_data_as_of": "2026-07-20",
    }
    state["insight_rolling_observation"] = {
        "story_key": "recent_week_rolling:v1:xyz", "active": True,
        "impact_value": -1.5e6, "change_pct": -15.0, "direction": -1,
        "data_as_of": "2026-07-20",
    }
    # Simulate a synthesizer/report failure: commit_run is called with an EMPTY
    # reported list (the caller in graph.py computes this whenever
    # insight_report is missing), even though observations exist.
    res = mem.commit_run(state, [])
    memory, _ = mem.load_store(state)
    check(res["status"] == "ok" and res["committed"] == 0,
          "commit_run with an empty reported list still succeeds, commits zero signals")
    check(memory["daily_cursor"].get("'F'[POSTING_DATE]") == "2026-07-20",
          "the daily cursor still advances even when nothing was reported")
    check(memory["rolling_state"].get("recent_week_rolling:v1:xyz", {}).get("active") is True,
          "the rolling observation still updates even when nothing was reported")
    check(memory["records"] == {},
          "no story keys are marked 'seen' - a synthesizer failure must never "
          "suppress a finding the user never actually received")

    # Monotonic guard: an older effective_data_as_of must never overwrite a
    # newer stored cursor (protects against a replay/out-of-order run).
    state["insight_business_day_source"]["effective_data_as_of"] = "2026-07-01"
    mem.commit_run(state, [])
    memory2, _ = mem.load_store(state)
    check(memory2["daily_cursor"].get("'F'[POSTING_DATE]") == "2026-07-20",
          "an older effective_data_as_of never overwrites a newer stored cursor")


_ROLLING_CONTRACT = {
    "coverage_kind": "recent_week_rolling_history",
    "metric_roles": {"net revenue CURRENT": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                                             "phase": "current", "family": "revenue"}},
}


def _rolling_cand(**over) -> dict:
    base = {
        "id": "cand_01_recent_week_movement", "type": "recent_week_movement",
        "level": "recent_week_rolling", "table": "meta_recent_week_history",
        "metric": "net revenue CURRENT", "segment": "overall (comparable base)",
        "axis": "'MIS_DEEP_DIVE2'[POSTING_DATE]",
        "impact_value": -1_500_000.0, "impact_share": None, "score": 15.0, "kind": "business",
        "recent_week": {"window_mode": "rolling", "week_start": "2026-07-14",
                        "week_end": "2026-07-20", "change_pct": -15.0, "actual": 8.5e6,
                        "previous": 10.0e6, "expected": 10.0e6, "abs_impact": -1.5e6,
                        "facets": {}},
    }
    base.update(over)
    return base


def _rolling_obs(**over) -> dict:
    base = {"axis": "'MIS_DEEP_DIVE2'[POSTING_DATE]", "metric": "net revenue CURRENT",
            "segment": "overall (comparable base)", "active": True,
            "impact_value": -1_500_000.0, "change_pct": -15.0, "direction": -1,
            "data_as_of": "2026-07-20"}
    base.update(over)
    return base


def _rolling_key() -> str:
    scope_h = mem.scope_hash({"insight_comparable_population": [], "insight_excluded_entities": []})
    return mem.story_components(_rolling_cand(), DS, scope_h, _ROLLING_CONTRACT, "")[0]


def _rolling_run(cand: dict, obs: dict, *, records=None, rolling_state=None,
                 enabled=True, corrupt=False, policy="never_repeat", cooldown_days=14) -> dict:
    state, tmp = _state(records or {}, enabled=enabled, policy=policy, corrupt=corrupt)
    state["insight_memory_cooldown_days"] = cooldown_days
    if rolling_state is not None and not corrupt:
        store = tmp / "memory.json"
        data = json.loads(store.read_text(encoding="utf-8"))
        data["rolling_state"] = rolling_state
        store.write_text(json.dumps(data, default=str), encoding="utf-8")
    state["insight_evidence_contracts"] = {"meta_recent_week_history": _ROLLING_CONTRACT}
    state["insight_stat_candidates"] = {"business_candidates": [cand], "data_quality_candidates": []}
    state["insight_rolling_observation"] = obs
    return nf.run(state)


def _rolling_elig(out: dict) -> list:
    return [c for c in out["insight_eligible_candidates"]["business_candidates"]
            if c.get("level") == "recent_week_rolling"]


def test_rolling_eligibility() -> None:
    print("\n=== rolling-week eligibility (Phase 3b) ===")
    key = _rolling_key()

    # unknown key -> eligible; the observation is stamped with the SAME key.
    out1 = _rolling_run(_rolling_cand(), _rolling_obs())
    check(len(_rolling_elig(out1)) == 1, "an unknown rolling story_key is eligible")
    check(out1["insight_rolling_observation"].get("story_key") == key,
          "the observation is stamped with the SAME story_key as the candidate")

    stored_record = {"level": "recent_week_rolling", "last_reported": "2026-07-13",
                     "impact_value": -1_500_000.0, "direction": -1, "change_pct": -15.0}

    # known + inactive -> active transition -> eligible (resurfaced), even
    # though the reading exactly matches the stored magnitude.
    out2 = _rolling_run(_rolling_cand(), _rolling_obs(),
                        records={key: stored_record},
                        rolling_state={key: {"active": False, "impact_value": 0.0,
                                             "change_pct": 0.0, "direction": 0,
                                             "observed_through": "2026-07-13"}})
    check(len(_rolling_elig(out2)) == 1 and out2["insight_novelty"]["resurfaced"] == 1,
          "known key, inactive -> active transition, is eligible (resurfaced)")

    # known + still active + unchanged -> suppressed.
    out3 = _rolling_run(_rolling_cand(), _rolling_obs(),
                        records={key: stored_record},
                        rolling_state={key: {"active": True, "impact_value": -1_500_000.0,
                                             "change_pct": -15.0, "direction": -1,
                                             "observed_through": "2026-07-13"}})
    check(_rolling_elig(out3) == [], "known key, active, unchanged -> suppressed")

    # material growth -> resurfaces via resurface_check even with no transition.
    grown_cand = _rolling_cand(impact_value=-3_000_000.0,
                               recent_week={**_rolling_cand()["recent_week"],
                                           "change_pct": -30.0, "abs_impact": -3e6})
    grown_obs = _rolling_obs(impact_value=-3_000_000.0, change_pct=-30.0)
    out4 = _rolling_run(grown_cand, grown_obs,
                        records={key: stored_record},
                        rolling_state={key: {"active": True, "impact_value": -1_500_000.0,
                                             "change_pct": -15.0, "direction": -1,
                                             "observed_through": "2026-07-13"}})
    check(len(_rolling_elig(out4)) == 1 and out4["insight_novelty"]["resurfaced"] == 1,
          "material growth (>= growth_pct) resurfaces despite no active-state transition")

    # memory disabled -> dropped outright, rolling_unavailable flagged.
    out5 = _rolling_run(_rolling_cand(), _rolling_obs(), enabled=False)
    check(_rolling_elig(out5) == [] and out5["insight_novelty"]["rolling_unavailable"] is True,
          "memory disabled -> rolling candidate dropped, rolling_unavailable flagged")

    # corrupt store -> dropped outright, never emitted raw.
    out6 = _rolling_run(_rolling_cand(), _rolling_obs(), corrupt=True)
    check(_rolling_elig(out6) == [] and out6["insight_novelty"]["rolling_unavailable"] is True,
          "corrupt memory -> rolling candidate dropped, rolling_unavailable flagged")

    # never_repeat/cooldown must NEVER be consulted for this level: even a
    # cooldown policy short enough that the record would normally have expired
    # (making it "eligible" via the generic path) must NOT resurface an
    # unchanged reading - decision #9's bespoke path is the only thing that
    # can make a rolling candidate eligible.
    out7 = _rolling_run(_rolling_cand(), _rolling_obs(),
                        records={key: {**stored_record, "last_reported": "2000-01-01"}},
                        rolling_state={key: {"active": True, "impact_value": -1_500_000.0,
                                             "change_pct": -15.0, "direction": -1,
                                             "observed_through": "2000-01-01"}},
                        policy="cooldown", cooldown_days=1)
    check(_rolling_elig(out7) == [],
          "an ancient last_reported date under a short cooldown does NOT resurface an "
          "unchanged rolling reading (never_repeat/cooldown is never consulted for this level)")


def test_single_story_key_authority() -> None:
    print("\n=== single rolling story-key authority (Phase 3b) ===")
    scope_h = mem.scope_hash({"insight_comparable_population": [], "insight_excluded_entities": []})
    real_key, _ = mem.story_components(_rolling_cand(), DS, scope_h, _ROLLING_CONTRACT, "")
    synthetic_key = nf._rolling_key(_rolling_obs(), {"meta_recent_week_history": _ROLLING_CONTRACT},
                                    DS, scope_h, "")
    check(real_key == synthetic_key,
          "a real candidate's story_key matches the key computed from an equivalent "
          "observation-only dict (single authority - the two can never drift apart)")


_RATE_CONTRACT = {
    "coverage_kind": "full_dimension_breakdown",
    "grouping_references": ["'MIS_DEEP_DIVE2'[DEPARTMENT]"],
    "metric_roles": {
        "net revenue CURRENT": {"bundle_id": "MIS_DEEP_DIVE2::revenue",
                                "phase": "current", "family": "revenue"}},
}


def _rate_candidate(**over) -> dict:
    base = {
        "id": "cand_50_peer_growth_rate_outlier",
        "type": "peer_growth_rate_outlier",
        "table": "meta_peer_breakdown_by_dept",
        "metric": "net revenue CURRENT",
        "segment": "ELECTRONICS",
        "bundle_id": "MIS_DEEP_DIVE2::revenue",
        "dimension": "'MIS_DEEP_DIVE2'[DEPARTMENT]",
        "direction": 1,
        "impact_value": 50_000.0,
        "reported_growth_pct": 40.0,
        "robust_z": 3.5,
        "score": 25.0,        # tiny relative-priority, off the bridge scale
        "kind": "business",
    }
    base.update(over)
    return base


def test_rate_reservation() -> None:
    print("\n=== rate-mover reservation + one-slot selection (Phase 6) ===")
    contracts = {**CONTRACTS, "meta_peer_breakdown_by_dept": _RATE_CONTRACT}

    # --- novelty filter: the reserved rate mover survives the caps despite a tiny
    #     score, while lower-scored HIGH candidates are dropped by the caps ---
    highs = [_candidate(id=f"cand_{i:02d}_change_contribution", segment=f"SEG{i}",
                        impact_value=-(100 - i) * 1000.0, score=100 - i) for i in range(5)]
    rate = _rate_candidate()
    state, tmp = _state({})                          # empty store -> all unseen
    state["insight_evidence_contracts"] = contracts
    state["insight_candidates_high"] = 3
    state["insight_stat_max_candidates"] = 3         # force the caps to bite
    state["insight_stat_candidates"] = {"business_candidates": highs + [rate],
                                        "data_quality_candidates": []}
    out = nf.run(state)
    nov = out["insight_novelty"]
    elig = out["insight_eligible_candidates"]["business_candidates"]
    reserved = [c for c in elig if c.get("reserved_relative")]
    check(nov["rate_detected"] == 1 and nov["rate_reserved"] is True,
          "novelty filter reserves the standalone rate mover")
    check(len(reserved) == 1 and reserved[0]["segment"] == "ELECTRONICS",
          "the reserved rate mover is in the eligible set, tagged reserved_relative")
    check(reserved[0].get("level") == "rate", "the rate mover carries its own 'rate' level")
    # 3 high (cap) + 1 reserved rate = 4; the two lowest HIGH candidates were dropped
    check(len([c for c in elig if c.get("type") == "change_contribution"]) == 3,
          "the high-level cap still bit (3 of 5 high candidates kept)")
    check(any(c["segment"] == "ELECTRONICS" for c in elig),
          "the reserved rate mover survived caps that dropped higher-scored high candidates")

    # --- seen rate story is NOT reserved ---
    # (the filter tags level "rate" before hashing, so the key must too)
    scope_h = mem.scope_hash({"insight_comparable_population": [], "insight_excluded_entities": []})
    rate_key, _ = mem.story_components({**_rate_candidate(), "level": "rate"},
                                       DS, scope_h, _RATE_CONTRACT, "2023-12")
    state2, _t2 = _state({rate_key: {"level": "rate", "last_reported": "2023-12-31"}})
    state2["insight_evidence_contracts"] = contracts
    state2["insight_stat_candidates"] = {"business_candidates": [_rate_candidate()],
                                         "data_quality_candidates": []}
    nov2 = nf.run(state2)["insight_novelty"]
    check(nov2["rate_detected"] == 1 and nov2["rate_reserved"] is False,
          "an already-reported rate story is not reserved (reserve nothing)")

    # --- only the BEST unseen rate mover is reserved when several qualify ---
    state3, _t3 = _state({})
    state3["insight_evidence_contracts"] = contracts
    state3["insight_stat_candidates"] = {"business_candidates": [
        _rate_candidate(id="cand_50_peer_growth_rate_outlier", segment="ELECTRONICS", score=25.0),
        _rate_candidate(id="cand_51_peer_growth_rate_outlier", segment="APPAREL", score=60.0),
    ], "data_quality_candidates": []}
    out3 = nf.run(state3)
    res3 = [c for c in out3["insight_eligible_candidates"]["business_candidates"]
            if c.get("reserved_relative")]
    check(out3["insight_novelty"]["rate_detected"] == 2 and len(res3) == 1
          and res3[0]["segment"] == "APPAREL",
          "with several rate movers, exactly one (the highest-priority) is reserved")

    # --- no rate candidates -> reserve nothing, normal selection ---
    state4, _t4 = _state({})
    state4["insight_evidence_contracts"] = contracts
    state4["insight_stat_candidates"] = {"business_candidates": [_candidate()],
                                         "data_quality_candidates": []}
    nov4 = nf.run(state4)["insight_novelty"]
    check(nov4["rate_detected"] == 0 and nov4["rate_reserved"] is False,
          "no rate candidate -> nothing reserved")

    # --- signal detector _rank_and_cap: the reserved mover takes ONE slot by policy,
    #     displacing the lowest-ranked BUSINESS signal, never a data-quality one ---
    biz = [{"id": f"b{i}", "kind": "business", "score": s}
           for i, s in enumerate([100, 90, 80, 70])]
    reserved_sig = {"id": "r", "kind": "business", "score": 25, "reserved_relative": True}
    out5 = sd._rank_and_cap(biz + [reserved_sig], cap=4, max_dq=2)
    ids5 = {s["id"] for s in out5}
    check(len(out5) == 4, "final count never exceeds the cap")
    check("r" in ids5 and "b3" not in ids5,
          "the reserved mover displaces the lowest-ranked business signal (b3)")
    check(sum(1 for s in out5 if s.get("reserved_relative")) == 1,
          "at most one standalone rate signal survives")

    dq_sig = {"id": "dq1", "kind": "data_quality", "score": 85}
    out6 = sd._rank_and_cap([biz[0], biz[1], dq_sig, biz[2], reserved_sig], cap=4, max_dq=2)
    ids6 = {s["id"] for s in out6}
    check("dq1" in ids6 and "r" in ids6 and "b2" not in ids6,
          "the reserved mover never evicts a data-quality signal (a business one goes)")

    all_dq = [{"id": "dq1", "kind": "data_quality", "score": 100},
              {"id": "dq2", "kind": "data_quality", "score": 90}]
    out_dq = sd._rank_and_cap(all_dq + [reserved_sig], cap=2, max_dq=2)
    check({s["id"] for s in out_dq} == {"dq1", "dq2"},
          "when every occupied slot is data-quality, the relative slot reverts instead of evicting DQ")

    out7 = sd._rank_and_cap(biz, cap=4, max_dq=2)
    check({s["id"] for s in out7} == {"b0", "b1", "b2", "b3"},
          "no reserved mover -> all slots revert to normal score-ranked selection")

    # --- signal detector backfill: an omitted reserved mover is injected as a signal ---
    eligible = {"business_candidates": [_rate_candidate(story_key="rate:v1:abc",
                                                        reserved_relative=True)],
                "data_quality_candidates": []}
    out8 = sd._ensure_reserved_relative([], eligible)
    check(len(out8) == 1 and out8[0].get("reserved_relative")
          and out8[0].get("candidate_id") == "cand_50_peer_growth_rate_outlier",
          "the LLM omitting the reserved mover triggers a deterministic backfill")
    already = [{"id": "s1", "candidate_id": "cand_50_peer_growth_rate_outlier"}]
    out9 = sd._ensure_reserved_relative(already, eligible)
    check(len(out9) == 1 and out9[0].get("reserved_relative"),
          "when the LLM already selected the reserved mover it is tagged, not duplicated")


def test_rate_memory() -> None:
    print("\n=== rate story_key + cross-run memory (Phase 7) ===")
    contracts = {**CONTRACTS, "meta_peer_breakdown_by_dept": _RATE_CONTRACT}
    scope_h = mem.scope_hash({"insight_comparable_population": [],
                              "insight_excluded_entities": []})

    def rkey(anchor="2023-12", **over) -> str:
        cand = {**_rate_candidate(**over), "level": "rate"}  # the filter tags 'rate' first
        return mem.story_components(cand, DS, scope_h, _RATE_CONTRACT, anchor)[0]

    # --- the story-key contract for the dedicated 'rate' level ---
    base = rkey()
    check(base.startswith("rate:v1:"),
          "a standalone rate mover gets a dedicated 'rate'-prefixed story key "
          "(not the high-level fallback)")
    # every MUTABLE reading is excluded from the key (Phase 7: direction, growth %,
    # z-score, deviation, impact, peer count) -> a reversal / larger move is ONE story
    check(base == rkey(direction=-1, impact_value=-50_000.0)
          == rkey(impact_value=250_000.0, reported_growth_pct=180.0, robust_z=9.9, peer_count=25),
          "the rate key excludes direction, growth %, z-score, impact and peer count")
    check(base == rkey(segment="  electronics ") == rkey(segment="ELECTRONICS"),
          "case / whitespace variants of the rate segment collide to one key")
    # things that MUST differ
    check(base != rkey(anchor="2024-01"),
          "a new reporting period -> a new rate story (so it resurfaces next period)")
    check(base != rkey(segment="APPAREL"), "a different segment -> a different rate key")

    # --- suppression: a seen rate story with an UNCHANGED reading stays suppressed ---
    stored = {"level": "rate", "last_reported": "2023-12-31",
              "direction": 1, "impact_value": 50_000.0}
    st, _t = _state({base: stored})
    st["insight_evidence_contracts"] = contracts
    st["insight_stat_candidates"] = {"business_candidates": [_rate_candidate()],
                                     "data_quality_candidates": []}
    nov = nf.run(st)["insight_novelty"]
    check(nov["rate_detected"] == 1 and nov["rate_reserved"] is False
          and nov["rate_resurfaced"] == 0,
          "a previously reported rate story with an unchanged reading is suppressed")

    # --- resurface on a direction reversal (same story key, opposite direction) ---
    st2, _t2 = _state({base: stored})
    st2["insight_evidence_contracts"] = contracts
    st2["insight_stat_candidates"] = {
        "business_candidates": [_rate_candidate(direction=-1, impact_value=-50_000.0)],
        "data_quality_candidates": []}
    out2 = nf.run(st2)
    nov2 = out2["insight_novelty"]
    res2 = [c for c in out2["insight_eligible_candidates"]["business_candidates"]
            if c.get("reserved_relative")]
    check(nov2["rate_reserved"] is True and nov2["rate_resurfaced"] == 1
          and nov2["resurfaced"] == 1,
          "a direction reversal resurfaces a suppressed rate story")
    check(len(res2) == 1 and res2[0].get("resurfaced") is True,
          "the resurfaced mover is reserved and tagged 'resurfaced'")

    # --- resurface on a materially larger movement (>= insight_re_alert_growth_pct) ---
    st3, _t3 = _state({base: stored})
    st3["insight_evidence_contracts"] = contracts
    st3["insight_stat_candidates"] = {
        "business_candidates": [_rate_candidate(impact_value=100_000.0)],  # +100% >= 50% floor
        "data_quality_candidates": []}
    nov3 = nf.run(st3)["insight_novelty"]
    check(nov3["rate_reserved"] is True and nov3["rate_resurfaced"] == 1,
          "a materially larger movement (>= growth_pct) resurfaces a suppressed rate story")

    # --- a sub-threshold change does NOT resurface (still suppressed) ---
    st4, _t4 = _state({base: stored})
    st4["insight_evidence_contracts"] = contracts
    st4["insight_stat_candidates"] = {
        "business_candidates": [_rate_candidate(impact_value=60_000.0)],  # +20% < 50%, same dir
        "data_quality_candidates": []}
    nov4 = nf.run(st4)["insight_novelty"]
    check(nov4["rate_reserved"] is False and nov4["rate_resurfaced"] == 0,
          "a sub-threshold change to a seen rate story stays suppressed (no resurface)")

    # --- reported rate finding round-trips through commit and is suppressed next run ---
    st5, tmp5 = _state({})
    st5["insight_evidence_contracts"] = contracts
    key = rkey()
    signal = {"id": "electronics_rate", "kind": "business", "level": "rate",
              "description": "ELECTRONICS grew unusually fast vs peers",
              "impact_value": 50_000.0, "direction": 1,
              "story_key": key, "covered_story_keys": [key]}
    res = mem.commit_run(st5, [signal])
    memory, _ = mem.load_store(st5)
    check(res["status"] == "ok" and key in memory["records"]
          and memory["records"][key].get("direction") == 1
          and memory["records"][key].get("impact_value") == 50_000.0,
          "a reported rate story commits its key WITH direction/impact (so it can resurface)")
    st5["insight_stat_candidates"] = {"business_candidates": [_rate_candidate()],
                                      "data_quality_candidates": []}
    nov5 = nf.run(st5)["insight_novelty"]
    check(nov5["rate_reserved"] is False,
          "after commit, the same unchanged rate story is suppressed on the next run")


def test_ordinal_uses_contribution_key() -> None:
    print("\n=== ordinal enrichment uses the existing contribution key (Phase 7) ===")
    # A small-peer ordinal note attaches to an EXISTING bridge (change_contribution)
    # candidate; it creates no new candidate and no new story key, so it can never
    # consume a report slot or a memory record of its own.
    scope_h = mem.scope_hash({"insight_comparable_population": [],
                              "insight_excluded_entities": []})
    bridge = _candidate(segment="CFH021")
    plain_key, _ = mem.story_components(bridge, DS, scope_h,
                                        CONTRACTS["meta_movers_by_dept"], "2023-12")
    enriched = _candidate(segment="CFH021", peer_rate_context={
        "rank_by_rate": 1, "peer_count": 4, "rank_desc": "fastest-growing",
        "basis": "ordinal_only", "phrase": "the fastest-growing of 4 comparable peers"})
    enriched_key, _ = mem.story_components(enriched, DS, scope_h,
                                           CONTRACTS["meta_movers_by_dept"], "2023-12")
    check(plain_key == enriched_key,
          "the ordinal note does not change the bridge candidate's contribution story key")
    check(enriched.get("type") == "change_contribution",
          "the enriched candidate remains a contribution finding (no rate type/key)")


def main() -> int:
    test_story_key()
    test_novelty_filter()
    test_cap_after_memory()
    test_scope_note_is_not_an_insight_tile()
    test_commit_merge()
    test_policy()
    test_recent_week_memory()
    test_rank_and_backfill()
    test_daily_recency()
    test_commit_run_observations()
    test_rolling_eligibility()
    test_single_story_key_authority()
    test_rate_reservation()
    test_rate_memory()
    test_ordinal_uses_contribution_key()
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
