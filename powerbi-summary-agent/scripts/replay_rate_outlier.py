"""Offline acceptance tests for Phase 2 of the rate-outlier lens: the
peer_growth_rate_outlier detector.

No authentication, LLM, or Power BI call. Drives the real ``_Detector`` over
synthetic full_dimension_breakdown tables (with real evidence contracts built by
``evidence_contract.extract_contract``) to exercise every gate.

Covers the Phase 2 fixtures:
  - true large-peer outlier detected
  - ordinary peer movement remains silent
  - zero-prior exclusion (member dropped, table not disabled)
  - lifecycle (discontinued) exclusion
  - negative/nonpositive transform guard disables the metric
  - minimum peer gate (< 8 valid peers -> nothing standalone)
  - prior-base (denominator-quality) rejection
  - business-exposure rejection
  - absolute-impact rejection
  - leave-one-out z (segment never inflates its own reference)
  - flat peers plus one material break -> flat_peer_break, robust_z null
  - completely flat peer set -> nothing
  - ineligible / non-reconciling table never dispatches
"""

import json
import math
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import evidence_contract, insight_rate_shadow  # noqa: E402
from src.agents import insight_signal_detector as sd  # noqa: E402
from src.agents.insight_stat_detector import _Detector, _point_robust_z  # noqa: E402
from src.tools import api_payloads as ap  # noqa: E402
from src.tools import insight_memory, insight_tiles as tiles  # noqa: E402
from src.utils.logger import RunLogger  # noqa: E402

CFG = json.loads((PROJECT_ROOT / "config" / "config.json").read_text(encoding="utf-8"))
# A high row cap so classify_metrics never treats a small fixture as truncated,
# and a low min-peer floor is NOT set - we test the real default of 8.
BASE = {**CFG, "max_rows_per_query": 100, "insight_stat_recon_tolerance_pct": 2.0,
        "insight_rate_outlier_mode": "report",
        "insight_rate_z_cutoff": 3.0, "insight_rate_min_peers": 8,
        "insight_rate_prior_share_floor_pct": 0.5, "insight_rate_exposure_floor_pct": 2.0,
        "insight_rate_min_abs_impact_pct": 1.0, "insight_rate_flat_min_pct": 10.0}

METRICS = [
    {"alias": "rev_cur", "phase": "current", "family": "revenue", "bundle_id": "B_REV",
     "semantic_role": "value", "additive_candidate": True},
    {"alias": "rev_prev", "phase": "prior", "family": "revenue", "bundle_id": "B_REV",
     "semantic_role": "value", "additive_candidate": True},
    {"alias": "rev_chg", "phase": "change", "family": "revenue", "bundle_id": "B_REV",
     "semantic_role": "value", "additive_candidate": True},
]


def rates(result):
    return [c for c in result["business_candidates"] if c["type"] == "peer_growth_rate_outlier"]


def bridge_for(result, seg):
    return next((c for c in result["business_candidates"]
                if c["type"] == "change_contribution" and c["segment"] == seg), None)


def reading(result, seg):
    """The rate reading for a segment, whether it stayed a standalone candidate or
    was merged into a bridge story (Phase 4 corroboration). Returns the rate-field
    dict, or None if the detector produced no reading for that segment."""
    for c in result["business_candidates"]:
        if c["type"] == "peer_growth_rate_outlier" and c["segment"] == seg:
            return c
        if (c["type"] == "change_contribution" and c["segment"] == seg
                and c.get("peer_rate_evidence")):
            return c["peer_rate_evidence"]
    return None


def any_reading(result):
    return any(c["type"] == "peer_growth_rate_outlier" or c.get("peer_rate_evidence")
               for c in result["business_candidates"])


def _setup(peers, eligible=True, cap=200, state_over=None, kind="full_dimension_breakdown"):
    """Build (clean, state): a reconciling grand-total row + a peer breakdown table,
    real evidence contracts, and a peer coverage entry."""
    rows, tc, tp, tg = [], 0.0, 0.0, 0.0
    for cat, cur, prev in peers:
        rows.append({"cat": cat, "rev_cur": cur, "rev_prev": prev, "rev_chg": cur - prev})
        tc += cur; tp += prev; tg += (cur - prev)
    totals_q = {"query_name": "meta_comparable_totals", "status": "success",
                "rows": [{"rev_cur": tc, "rev_prev": tp, "rev_chg": tg}],
                "contract_hint": {"coverage_kind": "grand_total", "grouping": [], "metrics": METRICS}}
    topn = None if kind == "full_entity_breakdown" else cap
    peer_q = {"query_name": "meta_peer_breakdown_by_x_cat", "status": "success", "rows": rows,
              "dax": "EVALUATE TOPN(200, ...)",
              "contract_hint": {"coverage_kind": kind,
                                "grouping": [{"reference": "'X'[cat]", "column": "cat"}],
                                "topn": topn, "population_status": "comparable", "metrics": METRICS}}
    state = {**BASE, **(state_over or {})}
    contracts = {q["query_name"]: evidence_contract.extract_contract(
        {"query_name": q["query_name"], "rows": q["rows"]}, q.get("dax", ""), {}, state,
        q["contract_hint"]) for q in (totals_q, peer_q)}
    state["insight_evidence_contracts"] = contracts
    state["insight_peer_coverage"] = {"'X'[cat]": {
        "query": "meta_peer_breakdown_by_x_cat", "eligible": eligible,
        "eligible_bundle_ids": (["B_REV"] if eligible else []),
        "completeness": "complete", "population_status": "comparable"}}
    return {"queries": [totals_q, peer_q], "successful": 2, "failed": 0}, state


def run_detector(peers, **kw):
    """peers: list of (cat, current, prior). Runs the detector, returns its full
    result dict (rate mode defaults to report; the shadow divert is not applied)."""
    clean, state = _setup(peers, **kw)
    return _Detector(state, RunLogger(state)).run(clean)


def run_shadow(peers, mode, tmp_dir=None, **kw):
    """Run the detector AND insight_rate_shadow.apply(mode) against isolated temp
    output/memory dirs. Returns (result, updates, state, tmp_dir)."""
    tmp = Path(tmp_dir) if tmp_dir is not None else Path(tempfile.mkdtemp(prefix="rateshadow_"))
    over = dict(kw.pop("state_over", None) or {})
    over.update({"insight_rate_outlier_mode": mode, "dataset_id": "TESTDS",
                 "output_folder": str(tmp / "out"), "insight_memory_root": str(tmp / "mem")})
    clean, state = _setup(peers, state_over=over, **kw)
    # Real portfolios already contain the ordinary partial mover tail in off,
    # shadow, and report modes. Add that base evidence here so shadow can prove
    # corroboration while the extra full distribution remains observational.
    peer_rows = clean["queries"][1]["rows"]
    tail_rows = sorted(peer_rows, key=lambda r: abs(r["rev_chg"]), reverse=True)[:8]
    tail_q = {"query_name": "meta_movers_by_x_cat", "status": "success",
              "rows": tail_rows, "dax": "EVALUATE TOPN(8, ...)",
              "contract_hint": {"coverage_kind": "paired_change_tails",
                                "grouping": [{"reference": "'X'[cat]", "column": "cat"}],
                                "topn": 8, "population_status": "comparable",
                                "metrics": METRICS}}
    clean["queries"].append(tail_q)
    state["insight_evidence_contracts"][tail_q["query_name"]] = evidence_contract.extract_contract(
        {"query_name": tail_q["query_name"], "rows": tail_q["rows"]}, tail_q["dax"],
        {}, state, tail_q["contract_hint"])
    result = _Detector(state, RunLogger(state)).run(clean)
    updates = insight_rate_shadow.apply(state, result)
    return result, updates, state, tmp


def _varied_peers(n=9, base_prev=1000.0):
    # n ordinary peers with small, DISTINCT growth (so the reference has spread and
    # the leave-one-out z is a real robust z, not a flat-peer break).
    deltas = [20, 30, 40, 25, 35, 45, 28, 33, 48, 22, 38][:n]
    return [(f"P{i}", base_prev + d, base_prev) for i, d in enumerate(deltas)]


def main() -> int:
    # Detection tests read the rate reading via reading(), which finds it whether
    # it stayed standalone or was folded into a bridge story (Phase 4) - the
    # detector's correctness is independent of that downstream routing.

    # --- true large-peer outlier detected; ordinary peers silent; leave-one-out ---
    res = run_detector(_varied_peers(9) + [("OUT", 1800.0, 1000.0)])
    out = reading(res, "OUT")
    assert out is not None, "the outlier reading was not produced"
    assert out["direction"] == 1 and out["stat_basis"] == "peer_robust_z"
    assert out["reported_growth_pct"] == 80.0 and out["peer_count"] == 10
    assert all(reading(res, f"P{i}") is None for i in range(9)), "an ordinary peer was flagged"
    # leave-one-out: reported z equals z of OUT vs the OTHERS only
    others = [math.log((1000 + d) / 1000) for d in [20, 30, 40, 25, 35, 45, 28, 33, 48]]
    expected_z = _point_robust_z(math.log(1.8), others)
    assert abs(out["robust_z"] - round(expected_z, 4)) < 1e-6, "robust z is not leave-one-out"
    expected_median_pct = sorted([2.0, 3.0, 4.0, 2.5, 3.5, 4.5, 2.8, 3.3, 4.8])[4]
    assert out["peer_median_reported_pct"] == expected_median_pct, \
        "reported peer median included the candidate instead of using its leave-one-out reference"

    # --- zero-prior exclusion: member dropped, table still works, OUT still found ---
    res = run_detector(_varied_peers(9) + [("OUT", 1800.0, 1000.0), ("NEW", 500.0, 0.0)])
    assert reading(res, "OUT") is not None
    assert reading(res, "NEW") is None, "zero-prior member was scored"
    assert reading(res, "OUT")["peer_count"] == 10, "zero-prior member was counted as a peer"

    # --- lifecycle (discontinued: zero current) exclusion ---
    res = run_detector(_varied_peers(9) + [("OUT", 1800.0, 1000.0), ("GONE", 0.0, 900.0)])
    assert reading(res, "GONE") is None
    assert reading(res, "OUT")["peer_count"] == 10

    # --- negative level disables the whole metric (no reading anywhere) ---
    res = run_detector(_varied_peers(9) + [("OUT", 1800.0, 1000.0), ("BAD", -50.0, 100.0)])
    assert not any_reading(res), "a negative level did not disable the metric"

    # --- minimum peer gate: only 6 valid peers -> nothing standalone ---
    peers = [(f"P{i}", 1000 + d, 1000) for i, d in enumerate([20, 30, 40, 25, 35])] + \
            [("OUT", 1800.0, 1000.0)]  # 6 valid peers, still < 8
    assert rates(run_detector(peers)) == [], "standalone candidate emitted below the minimum peer count"

    # --- prior-base (denominator-quality) rejection: huge % on a tiny prior base ---
    big = [(f"P{i}", 10000 + d * 100, 10000) for i, d in enumerate([20, 30, 40, 25, 35, 45, 28, 33, 48])]
    res = run_detector(big + [("TINYBASE", 900.0, 5.0)])     # prior 5 -> ~0.006% share
    assert reading(res, "TINYBASE") is None, "tiny prior base was not rejected"

    # --- business-exposure rejection: real fast move but segment too small overall ---
    big = [(f"P{i}", 10000 + d, 10000) for i, d in enumerate([20, 30, 40, 25, 35, 45, 28, 33, 48])]
    res = run_detector(big + [("SMALL", 200.0, 120.0)])      # +67%, shares < 2%
    assert reading(res, "SMALL") is None, "sub-exposure segment was not rejected"

    # --- absolute-impact rejection: high exposure, unusual rate, but tiny abs move ---
    big = [(f"P{i}", 100000 + d, 100000) for i, d in enumerate([200, 300, 400, 250, 350, 450, 280, 330, 480])]
    res = run_detector(big + [("STEADY", 3400.0, 3000.0)])   # abs 400 of ~903k -> 0.04%
    assert reading(res, "STEADY") is None, "sub-impact move was not rejected"

    # --- flat peers plus one material break -> flat_peer_break, robust_z null ---
    flat = [(f"F{i}", 1050.0, 1000.0) for i in range(9)]     # all exactly +5%
    res = run_detector(flat + [("BREAK", 1300.0, 1000.0)])   # +30%, 25 pts over the flat norm
    brk = reading(res, "BREAK")
    assert brk is not None and brk["stat_basis"] == "flat_peer_break" and brk["robust_z"] is None
    assert all(reading(res, f"F{i}") is None for i in range(9)), "a flat peer produced a reading"

    # --- completely flat peer set -> nothing ---
    assert not any_reading(run_detector([(f"F{i}", 1050.0, 1000.0) for i in range(10)])), \
        "a uniformly flat peer set produced a reading"

    # --- ineligible table never dispatches (even with an obvious outlier) ---
    assert not any_reading(run_detector(_varied_peers(9) + [("OUT", 1800.0, 1000.0)], eligible=False)), \
        "an ineligible table dispatched the detector"

    print("rate-outlier detector replay: OK")
    print("  13/13 Phase 2 fixtures passed")

    # ================= Phase 3: small-peer ordinal enrichment =================
    # --- 4-peer set (the store case): ordinal context attached, NO standalone ---
    four = [("S_UP", 1300.0, 1000.0),     # +30%  fastest growing
            ("S_MID1", 1080.0, 1000.0),   # +8%
            ("S_MID2", 1030.0, 1000.0),   # +3%
            ("S_DOWN", 850.0, 1000.0)]    # -15%  fastest declining
    res = run_detector(four, kind="full_entity_breakdown")
    assert rates(res) == [], "a 4-peer set produced a standalone statistical candidate"
    up = bridge_for(res, "S_UP")
    down = bridge_for(res, "S_DOWN")
    assert up and up.get("peer_rate_context"), "no ordinal context attached to the top grower"
    assert up["peer_rate_context"]["rank_desc"] == "fastest-growing"
    assert up["peer_rate_context"]["basis"] == "ordinal_only"
    assert up["peer_rate_context"]["peer_count"] == 4
    assert down and down["peer_rate_context"]["rank_desc"] == "fastest-declining"
    assert "of 4 comparable peers" in down["peer_rate_context"]["phrase"]
    assert res["peer_ordinal_orphans"] == [], "unexpected orphan when every peer has a bridge"

    # --- a ranked segment with no bridge candidate becomes an orphan ---
    # 5 members: four with large |change| take the bridge's top-4 slots; the tiny
    # mover gets ranked but has no bridge candidate to enrich -> orphan (not reported).
    five = [("A", 1300.0, 1000.0), ("B", 1250.0, 1000.0), ("C", 700.0, 1000.0),
            ("D", 1280.0, 1000.0), ("TINY", 1001.0, 1000.0)]
    res = run_detector(five, kind="full_entity_breakdown")
    assert rates(res) == [], "5-peer set produced a standalone candidate"
    assert bridge_for(res, "TINY") is None, "tiny mover unexpectedly got a bridge candidate"
    orphans = {o["segment"] for o in res["peer_ordinal_orphans"]}
    assert "TINY" in orphans, "orphan ordinal (no bridge candidate) was not recorded"
    # the orphan is diagnostic only - it must never appear as a reported candidate
    assert not any(c["segment"] == "TINY" for c in res["business_candidates"]
                   if c["type"] == "peer_growth_rate_outlier")

    # --- below the ordinal floor (2 peers) -> no ordinal, no orphan ---
    res = run_detector([("A", 1300.0, 1000.0), ("B", 800.0, 1000.0)],
                       kind="full_entity_breakdown")
    assert res["peer_ordinal_orphans"] == []
    assert all("peer_rate_context" not in c for c in res["business_candidates"]), \
        "ordinal context attached below the minimum ordinal peer count"

    # --- an ineligible dimension breakdown gets no ordinal enrichment either ---
    res = run_detector(four, eligible=False, kind="full_dimension_breakdown")
    assert all("peer_rate_context" not in c for c in res["business_candidates"]), \
        "ordinal enrichment ran on an ineligible dimension breakdown"

    print("small-peer ordinal enrichment: OK")
    print("  4/4 Phase 3 fixtures passed")

    # ================= Phase 4: overlap handling =================
    # --- corroborating: a top-absolute mover that is ALSO a rate outlier merges ---
    # into its bridge story (no standalone rate candidate; evidence attached).
    peers = [(f"P{i}", 10000 + d, 10000) for i, d in enumerate([200, 300, 400, 250, 350, 450, 280, 330, 480])] + \
            [("TOP", 60000.0, 40000.0)]        # +50%, +20000 -> biggest abs AND fastest
    res = run_detector(peers)
    assert not any(c["segment"] == "TOP" for c in rates(res)), \
        "an overlapping rate outlier was left as a standalone candidate"
    top = bridge_for(res, "TOP")
    assert top and top.get("has_rate_corroboration"), "rate evidence was not merged into the bridge story"
    assert top["peer_rate_evidence"]["reported_growth_pct"] == 50.0
    assert top["peer_rate_evidence"]["stat_basis"] in ("peer_robust_z", "flat_peer_break")

    # --- genuinely-new: a rate outlier that is NOT a top-absolute mover stays ---
    # standalone (nothing to merge into). Materiality floors relaxed so the routing,
    # not the calibration, is what is under test.
    anchors = [("A1", 102000.0, 100000.0), ("A2", 102100.0, 100000.0),
               ("A3", 101900.0, 100000.0), ("A4", 102200.0, 100000.0)]   # big abs, ~2%
    smalls = [(f"S{i}", 2000 + c, 2000) for i, c in enumerate([50, 40, 60, 45, 55])]  # tiny
    fast = [("FAST", 4500.0, 3000.0)]          # +50%, +1500 -> rate outlier, small abs
    res = run_detector(anchors + smalls + fast,
                       state_over={"insight_rate_exposure_floor_pct": 0.0,
                                   "insight_rate_min_abs_impact_pct": 0.0,
                                   "insight_rate_prior_share_floor_pct": 0.0})
    fast_rates = [c for c in rates(res) if c["segment"] == "FAST"]
    assert len(fast_rates) == 1, "a genuinely-new relative mover was dropped"
    assert bridge_for(res, "FAST") is None, "FAST unexpectedly had a bridge candidate"
    assert not any(c.get("has_rate_corroboration") for c in res["business_candidates"]), \
        "nothing should have merged when the rate outlier has no bridge story"

    dedup_state = {**BASE, "insight_evidence_contracts": {}, "insight_peer_coverage": {}}
    dedup = _Detector(dedup_state, RunLogger(dedup_state))
    for dimension in ("'F'[CATEGORY]", "'F'[PRODUCT_GROUP]"):
        dedup._add("business", {"type": "change_contribution", "metric": "rev_chg",
                                "dimension": dimension, "segment": "OTHER",
                                "score": 10.0})
    assert len(dedup.business) == 2, \
        "same-named members at different hierarchy levels collided during dedup"

    print("overlap handling: OK")
    print("  3/3 Phase 4 fixtures passed")

    # ================= Phase 5: memory-safe shadow mode =================
    tmp_dirs = []

    def art(state):
        return json.loads((Path(state["output_folder"]) / "insight_rate_shadow.json").read_text(encoding="utf-8"))

    # --- shadow mode diverts every rate trace out of the reported set ---
    result, updates, state, tmp = run_shadow(_varied_peers(9) + [("OUT", 1800.0, 1000.0)], "shadow")
    tmp_dirs.append(tmp)
    biz = result["business_candidates"]
    assert not any(c["type"] == "peer_growth_rate_outlier" for c in biz), "standalone rate leaked into report"
    assert not any(c.get("peer_rate_evidence") or c.get("has_rate_corroboration") for c in biz), \
        "merged rate evidence leaked into report"
    assert not any(c.get("peer_rate_context") for c in biz), "ordinal context leaked into report"
    # ids are re-numbered contiguously after the divert
    nums = [int(c["id"].split("_")[1]) for c in biz]
    assert nums == list(range(1, len(nums) + 1)), "candidate ids not contiguous after divert"
    # the diverted findings live only in the shadow channel + artifact
    sc = updates.get("insight_rate_shadow_candidates")
    assert sc and any(i["segment"] == "OUT" for i in sc), "diverted finding missing from shadow channel"
    report = art(state)
    assert report["mode"] == "shadow"
    assert report["projected_effect_on_report"]["corroborating_count"] >= 1  # OUT merged -> corroborating
    assert report["memory"]["status"] == "empty"
    assert all("bridge_reported_before" in i and "threshold_margins" in i
                for i in report["corroborating"]), "memory/sensitivity classification missing"

    # The ordinary report candidate set must be byte-for-byte identical between
    # off and shadow even though shadow also evaluated the full peer distribution.
    off_result, _, off_state, off_tmp = run_shadow(
        _varied_peers(9) + [("OUT", 1800.0, 1000.0)], "off")
    tmp_dirs.append(off_tmp)
    assert result["business_candidates"] == off_result["business_candidates"] \
        and result["data_quality_candidates"] == off_result["data_quality_candidates"], \
        "shadow mode changed the ordinary candidate set versus off mode"

    # --- read-only: shadow mode writes NOTHING to the memory store ---
    assert not insight_memory.store_path(state).exists(), "shadow mode wrote to the memory store"

    # --- report mode keeps the rate findings in the pipeline (Phase 6 selects) ---
    result, updates, state, tmp = run_shadow(_varied_peers(9) + [("OUT", 1800.0, 1000.0)], "report")
    tmp_dirs.append(tmp)
    assert updates == {}, "report mode set a shadow channel"
    assert any(c.get("peer_rate_evidence") for c in result["business_candidates"]), \
        "report mode stripped the merged rate evidence"
    assert (Path(state["output_folder"]) / "insight_rate_shadow.json").exists(), \
        "report mode did not write the audit artifact"

    # --- off mode is a no-op (no channel, no artifact) ---
    result, updates, state, tmp = run_shadow(_varied_peers(9) + [("OUT", 1800.0, 1000.0)], "off")
    tmp_dirs.append(tmp)
    assert updates == {}
    assert not (Path(state["output_folder"]) / "insight_rate_shadow.json").exists(), \
        "off mode wrote a shadow artifact"

    # --- a materiality-gate rejection is recorded for shadow calibration ---
    # SMALL is a large-z rate outlier whose prior share clears the denominator floor
    # (0.77%) but whose business exposure (1.28%) is below the 2% floor -> rejected
    # at the exposure gate, and recorded (proves significance-first ordering).
    big = [(f"P{i}", 10000 + d, 10000) for i, d in enumerate([20, 30, 40, 25, 35, 45, 28, 33, 48])]
    _, _, state, tmp = run_shadow(big + [("SMALL", 1169.0, 700.0)], "shadow")
    tmp_dirs.append(tmp)
    report = art(state)
    assert any(r.get("segment") == "SMALL" and r.get("failed_gate") == "exposure_below_floor"
                for r in report["rejected"]), "a significant-but-immaterial outlier was not recorded as rejected"

    # Diagnostics are genuinely best-effort: even a writer that fails twice cannot
    # escape after the safety-first divert and wipe out the ordinary stat result.
    broken = {"business_candidates": [], "data_quality_candidates": [],
              "rate_rejections": []}
    original_write = insight_rate_shadow.file_io.write_json
    try:
        insight_rate_shadow.file_io.write_json = lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk"))
        insight_rate_shadow.apply({**state, "insight_rate_outlier_mode": "shadow"}, broken)
        writer_safe = True
    except Exception:
        writer_safe = False
    finally:
        insight_rate_shadow.file_io.write_json = original_write
    assert writer_safe, "a shadow diagnostics write failure escaped the best-effort boundary"

    _, _, flat_state, flat_tmp = run_shadow(
        [(f"P{i}", 1050.0, 1000.0) for i in range(9)]
        + [("BREAK", 1300.0, 1000.0)], "shadow")
    tmp_dirs.append(flat_tmp)
    flat_report = art(flat_state)
    flat_items = flat_report["genuinely_new"] + flat_report["corroborating"]
    flat_item = next(i for i in flat_items if i.get("segment") == "BREAK")
    assert flat_item["threshold_margins"].get("flat_break_margin") is not None, \
        "flat-peer candidates omitted their margin to insight_rate_flat_min_pct"

    # Shadow's promotion yield is memory-aware: a previously committed rate story
    # is counted as seen, not mislabeled as genuinely new, and the read itself does
    # not advance or rewrite memory.
    shadow_peers = [
        ("A1", 102000.0, 100000.0), ("A2", 102100.0, 100000.0),
        ("A3", 101900.0, 100000.0), ("A4", 102200.0, 100000.0),
        *[(f"S{i}", 2000 + c, 2000) for i, c in enumerate([50, 40, 60, 45, 55])],
        ("FAST", 4500.0, 3000.0),
    ]
    shadow_over = {"insight_rate_exposure_floor_pct": 0.0,
                   "insight_rate_min_abs_impact_pct": 0.0,
                   "insight_rate_prior_share_floor_pct": 0.0}
    _, _, seen_state, seen_tmp = run_shadow(
        shadow_peers, "shadow", state_over=shadow_over)
    tmp_dirs.append(seen_tmp)
    first_art = art(seen_state)
    first_item = next(i for i in first_art["genuinely_new"] if i.get("segment") == "FAST")
    commit = insight_memory.commit_run(seen_state, [{
        "story_key": first_item["rate_story_key"], "covered_story_keys": [first_item["rate_story_key"]],
        "level": "rate", "kind": "business", "direction": first_item.get("direction"),
        "impact_value": first_item.get("impact_value"), "description": "FAST rate",
    }])
    assert commit["committed"] == 1, "shadow memory-classification fixture could not seed a seen story"
    _, _, seen_state2, _ = run_shadow(
        shadow_peers, "shadow", tmp_dir=seen_tmp, state_over=shadow_over)
    second_art = art(seen_state2)
    assert second_art["projected_effect_on_report"]["genuinely_new_count"] == 0 \
        and second_art["projected_effect_on_report"]["already_seen_count"] == 1, \
        "shadow promotion metrics counted an already-seen standalone rate as genuinely new"

    for d in tmp_dirs:
        shutil.rmtree(d, ignore_errors=True)

    print("memory-safe shadow mode: OK")
    print("  8/8 Phase 5 fixtures passed")

    # ================= Phase 8: surface structured facts + careful wording =====
    # Produce a REAL standalone rate outlier (>= 8 peers, and NOT the top absolute
    # mover so it stays standalone rather than merging into a bridge), copy its
    # facts onto a signal exactly as insight_signal_detector does, then verify every
    # surface reads the deterministic facts (never an LLM estimate) with non-causal
    # wording. FAST is +50% on a small base, so it is a rate outlier but not a top
    # contributor.
    anchors = [("A1", 102000.0, 100000.0), ("A2", 102100.0, 100000.0),
               ("A3", 101900.0, 100000.0), ("A4", 102200.0, 100000.0)]
    smalls = [(f"S{i}", 2000 + c, 2000) for i, c in enumerate([50, 40, 60, 45, 55])]
    res = run_detector(anchors + smalls + [("FAST", 4500.0, 3000.0)],
                       state_over={"insight_rate_exposure_floor_pct": 0.0,
                                   "insight_rate_min_abs_impact_pct": 0.0,
                                   "insight_rate_prior_share_floor_pct": 0.0})
    cand = next(c for c in rates(res) if c["segment"] == "FAST")
    sig = {"id": "s_fast", "kind": "business", "affected_segment": "FAST",
           "description": cand["detail"], "evidence_query": cand["evidence_query"]}
    sd._copy_candidate_facts(sig, cand)
    assert sig["reported_growth_pct"] == 50.0 and sig["peer_count"] == 10, \
        "growth %/peer count not copied onto the signal"
    assert sig["stat_basis"] == "peer_robust_z" and sig.get("robust_z") is not None, \
        "statistical basis not copied onto the signal"
    assert sig.get("current") is not None and sig.get("prior") is not None, \
        "current/prior values not copied onto the signal"
    assert sig["evidence_query"], "evidence provenance missing from the signal"
    assert ap._is_rate_signal(sig), "a standalone rate signal is not recognized"

    family = ap._signal_family(sig)
    msg = ap._main_change_sentence(sig, family)
    assert "50.0%" in msg, "reported growth % missing from the rate sentence"
    assert "relative to its 10 peers" in msg, "peer-relative clause / count missing"
    assert "peer median" in msg.lower(), "peer median missing from the rate sentence"
    assert not any(w in msg.lower() for w in ("because", "due to", "driven", "caused", "led by")), \
        "the rate sentence must make no causal claim"

    stats = {s["label"]: s["value"] for s in ap._insight_stats(sig, family)}
    assert any("growth" in k.lower() for k in stats), "growth stat missing"
    assert "Peer median" in stats and "Robust z" in stats, "peer median / robust z stat missing"

    assert ap._signal_severity(sig) == "positive", "a fast grower should grade positive"
    assert ap._signal_severity({**sig, "reported_growth_pct": -50.0}) == "warning", \
        "a fast decliner should grade as a concern"

    # the >= / < eight-peers wording rule, in one place
    assert ap._rate_relative_phrase({"peer_count": 12, "stat_basis": "peer_robust_z",
                                     "reported_growth_pct": 20.0}) \
        == "unusually fast relative to its 12 peers"
    assert ap._rate_relative_phrase({"peer_count": 5}) == "among 5 comparable members", \
        "a small peer set must not make a statistical-outlier claim"
    assert ap._rate_relative_phrase({"peer_count": 4, "peer_rate_context": {
        "basis": "ordinal_only", "phrase": "the fastest-growing of 4 comparable peers"}}) \
        == "the fastest-growing of 4 comparable peers"

    facts = ap._signal_facts(sig)
    assert facts["rate_outlier"] and facts["rate_outlier"]["peer_count"] == 10, \
        "rate facts not exposed to the LLM authoring context"

    card_text = ap._KpiCardText(
        signal_id="s_fast", category="Revenue", description="Peer-relative movement.",
        insight_title="Fast growth", insight_summary="Growth exceeded the peer norm.",
        insight_action="Review the segment mix.")
    card = ap._assemble_kpi_card(1, sig, card_text, datetime(2026, 3, 31, 9, 0))
    assert card["delta"] == "50.0%" and "peer median" in card["comparisonLabel"], \
        "rate card displayed impact share instead of growth versus the peer median"

    spec = tiles._resolve_chart(sig, None, {"business_candidates": [cand]}, {})
    assert spec["type"] == "rate_kpi" and spec["growth_pct"] == 50.0 and spec["peer_count"] == 10, \
        "the rate signal did not resolve to a rate_kpi tile"
    tile_html = tiles._rate_kpi_html(spec)
    assert "+50.0%" in tile_html and "10 peers" in tile_html and "peer median" in tile_html, \
        "the rate tile did not render the deterministic facts"

    # A small-peer ordinal note rides onto the bridge signal (no rate type/key of
    # its own) and surfaces the "of N members" ordinal wording, not an outlier claim.
    res_o = run_detector([("S_UP", 1300.0, 1000.0), ("S_MID1", 1080.0, 1000.0),
                          ("S_MID2", 1030.0, 1000.0), ("S_DOWN", 850.0, 1000.0)],
                         kind="full_entity_breakdown")
    bridge = bridge_for(res_o, "S_UP")
    bsig = {"id": "b_up", "kind": "business", "affected_segment": "S_UP",
            "description": "S_UP revenue rose"}
    sd._copy_candidate_facts(bsig, bridge)
    assert bsig.get("peer_rate_context", {}).get("basis") == "ordinal_only", \
        "ordinal context did not flow onto the bridge signal"
    assert not ap._is_rate_signal(bsig), "a bridge+ordinal signal must not read as a rate signal"
    assert "of 4 comparable peers" in ap._rate_relative_phrase(bsig), \
        "the ordinal (of-N-members) wording is not surfaced"

    # Bridge corroboration (a top mover that is ALSO a rate outlier) rides along too.
    peers = [(f"P{i}", 10000 + d, 10000) for i, d in enumerate([200, 300, 400, 250, 350, 450, 280, 330, 480])] + \
            [("TOP", 60000.0, 40000.0)]
    csig = {"id": "c_top", "kind": "business", "affected_segment": "TOP",
            "description": "TOP revenue rose"}
    sd._copy_candidate_facts(csig, bridge_for(run_detector(peers), "TOP"))
    assert csig.get("peer_rate_evidence"), "bridge corroboration did not flow onto the signal"

    print("surface structured facts + careful wording: OK")
    print("  6/6 Phase 8 fixtures passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
