"""Offline replay for the deterministic stat detector (Wave 2).

Runs src/agents/insight_stat_detector.py against a saved
insight_clean_data.json - no auth, no LLM, no Power BI round-trip.
Also runs a synthetic edge-case suite (Infinity/NaN/null/text columns,
empty tables, zero spread) to prove the node degrades instead of raising.

Run from the project dir:

    python scripts/replay_stat_detector.py                 # uses outputs/insight_clean_data.json
    python scripts/replay_stat_detector.py path/to.json    # any saved scan
    python scripts/replay_stat_detector.py --synthetic     # edge cases only

Artifacts go to outputs_replay/ so real run outputs are never touched.
"""

import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import insight_business_day_source as bds  # noqa: E402
from src.agents import insight_daily as di  # noqa: E402
from src.agents import insight_recent_week as rw  # noqa: E402
from src.agents import insight_stat_detector  # noqa: E402


def _base_state() -> dict:
    cfg = json.loads((PROJECT_ROOT / "config" / "config.json").read_text(encoding="utf-8"))
    state = {k: v for k, v in cfg.items() if k.startswith("insight_stat_")}
    state["max_rows_per_query"] = cfg.get("max_rows_per_query", 15)
    state["output_folder"] = "outputs_replay"
    return state


def replay(clean_path: Path) -> dict:
    state = _base_state()
    state["insight_clean_data"] = json.loads(clean_path.read_text(encoding="utf-8"))
    updates = insight_stat_detector.run(state)
    return updates["insight_stat_candidates"]


def synthetic_suite() -> dict:
    """Nasty table shapes the detector must survive without raising."""
    inf, nan = float("inf"), float("nan")
    queries = [
        # empty rows
        {"query_name": "empty", "status": "success", "rows": []},
        # failed query (must be skipped)
        {"query_name": "failed", "status": "failed", "error": "boom"},
        # all-null column, text-only table
        {"query_name": "text_only", "status": "success",
         "rows": [{"a": "x", "b": None}, {"a": "y", "b": None}]},
        # Infinity / NaN mixed into an otherwise valid triple
        {"query_name": "nonfinite", "status": "success", "rows": [
            {"seg": "A", "cur": 100.0, "prev": 80.0, "chg": 20.0},
            {"seg": "B", "cur": inf, "prev": 50.0, "chg": nan},
            {"seg": "C", "cur": 60.0, "prev": 0.0, "chg": 60.0},
            {"seg": "D", "cur": 30.0, "prev": 40.0, "chg": -10.0},
        ]},
        # zero spread (non-differentiating) + mixed types in one column
        {"query_name": "flat", "status": "success", "rows": [
            {"seg": s, "metric": 5.0, "mixed": (1 if s == "A" else "oops")}
            for s in "ABCDE"
        ]},
        # single-row grand totals
        {"query_name": "totals", "status": "success",
         "rows": [{"cur": 190.0, "prev": 170.0, "chg": 20.0}]},
        # date series with one unparseable date and a level shift
        {"query_name": "series", "status": "success", "rows": [
            {"d": f"2026-01-{i:02d}T00:00:00", "v": (10.0 if i <= 6 else 50.0)}
            for i in range(1, 13)
        ]},
    ]
    state = _base_state()
    state["insight_clean_data"] = {
        "query_count": len(queries),
        "successful": sum(1 for q in queries if q["status"] == "success"),
        "queries": queries,
    }
    updates = insight_stat_detector.run(state)
    return updates["insight_stat_candidates"]


def synthetic_period_suite() -> dict:
    """A gate-validated monthly period_series exercising the enhanced period():
    reconciled % (via a grand-total table), month-name labels, the worst-period
    drill (via state), sustained-run / reversal / value-volume-divergence patterns,
    and null-member exclusion."""
    rev_chg = [1.2, -0.8, 0.3, -0.5, 0.4, -0.8, 0.2, -1.3, -0.5, -1.7, -0.7, -0.16]  # ends in a decline run
    rows = []
    for i in range(12):
        rows.append({
            "DOC_MONTH": float(i + 1),
            "rev_cur": (10.0 + rev_chg[i]) * 1e6, "rev_prev": 10.0 * 1e6,
            "rev_chg": rev_chg[i] * 1e6,
            # volume rises every month -> months with falling revenue diverge
            "qty_cur": 5.5e6, "qty_prev": 5.0e6, "qty_chg": 0.5e6,
        })
    rows.append({"DOC_MONTH": None, "rev_cur": 1e5, "rev_prev": 0.0, "rev_chg": 1e5,
                 "qty_cur": 1.0, "qty_prev": 0.0, "qty_chg": 1.0})  # null member -> excluded
    totals = {"rev_chg": sum(rev_chg) * 1e6, "qty_chg": 0.5e6 * 12}   # grand totals for reconciliation
    roles = {
        "rev_cur": {"bundle_id": "F::revenue", "phase": "current", "semantic_role": "value"},
        "rev_prev": {"bundle_id": "F::revenue", "phase": "prior", "semantic_role": "value"},
        "rev_chg": {"bundle_id": "F::revenue", "phase": "change", "semantic_role": "value"},
        "qty_cur": {"bundle_id": "F::quantity", "phase": "current", "semantic_role": "volume"},
        "qty_prev": {"bundle_id": "F::quantity", "phase": "prior", "semantic_role": "volume"},
        "qty_chg": {"bundle_id": "F::quantity", "phase": "change", "semantic_role": "volume"}}
    contract = {"coverage_kind": "period_series", "grouping_references": ["'F'[DOC_MONTH]"],
                "metric_roles": roles}
    totals_contract = {"coverage_kind": "grand_total", "grouping_references": [], "metric_roles": roles}
    state = _base_state()
    state.update({"insight_period_top_movers": 4, "insight_period_recent_window": 12,
                  "insight_candidates_high": 20, "insight_candidates_period": 20,
                  "insight_candidates_daily": 10,
                  "insight_evidence_contracts": {"meta_period": contract, "meta_totals": totals_contract},
                  "insight_temporal_drill": {"period_raw": "10.0", "period_label": "October",
                      "top_segments": [{"segment": "Technology", "change": -1.2e6},
                                       {"segment": "Consumer Goods", "change": -0.5e6}]}})
    state["insight_clean_data"] = {"queries": [
        {"query_name": "meta_totals", "status": "success", "rows": [totals]},
        {"query_name": "meta_period", "status": "success", "rows": rows}]}
    return insight_stat_detector.run(state)["insight_stat_candidates"]


_MONDAY = date(2026, 4, 6)   # a Monday, for deterministic week fixtures


def _recent_week_result(values, volumes=None, **overrides):
    """Run the stat detector over a synthetic recent_week_history table and return
    only the recent_week_movement candidates."""
    rows = []
    for i, v in enumerate(values):
        row = {"week_start": (_MONDAY + timedelta(days=7 * i)).isoformat(), "rev_cur": float(v)}
        if volumes is not None:
            row["qty_cur"] = float(volumes[i])
        rows.append(row)
    last_ws = _MONDAY + timedelta(days=7 * (len(values) - 1))
    roles = {"rev_cur": {"bundle_id": "F::revenue", "phase": "current",
                         "semantic_role": "value", "family": "revenue"}}
    if volumes is not None:
        roles["qty_cur"] = {"bundle_id": "F::quantity", "phase": "current",
                            "semantic_role": "volume", "family": "quantity"}
    contract = {"coverage_kind": "recent_week_history", "axis": "week_start",
                "date_axis": "'F'[POSTING_DATE]", "metric_roles": roles,
                "week_start": last_ws.isoformat(),
                "week_end": (last_ws + timedelta(days=6)).isoformat(),
                "window_end": rows[-1]["week_start"], "grouping_references": ["[week_start]"]}
    state = _base_state()
    state.update({"insight_week_materiality_pct": 3.0, "insight_week_z_cutoff": 2.5,
                  "insight_candidates_weekly": 10, "insight_candidates_high": 20,
                  "insight_evidence_contracts": {"meta_recent_week_history": contract}})
    state.update(overrides)
    state["insight_clean_data"] = {"queries": [
        {"query_name": "meta_recent_week_history", "status": "success", "rows": rows}]}
    res = insight_stat_detector.run(state)["insight_stat_candidates"]
    return [c for c in res["business_candidates"] if c["type"] == "recent_week_movement"]


def recent_week_checks() -> None:
    """Phase 3 recent-week detection + gate + fold, offline (no auth/LLM)."""
    print("\n=== recent-week detection (Phase 3) ===")
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")

    noise = [0.02e6 if i % 2 else -0.02e6 for i in range(12)]
    stable = [10.0e6 + n for n in noise]

    # (a) material latest-week decline -> ONE candidate, correct facts
    cands = _recent_week_result(stable + [8.5e6])
    c = cands[0] if cands else {}
    p = c.get("recent_week", {})
    chk(len(cands) == 1, "material decline -> exactly one recent_week_movement candidate")
    chk(p.get("week_start") == (_MONDAY + timedelta(days=7 * 12)).isoformat(),
        "candidate anchored to the last completed week")
    chk(c.get("impact_share") is None, "impact_share is None (WoW % is not a share of change)")
    chk(isinstance(p.get("change_pct"), (int, float)) and -18 <= p["change_pct"] <= -13,
        f"change_pct ~ -15% (got {p.get('change_pct')})")
    chk(p.get("robust_z") is not None and abs(p["robust_z"]) >= 2.5, "robust z clears the cutoff")

    # (b) normal weeks -> no finding
    chk(_recent_week_result(stable + [10.05e6]) == [], "normal weeks -> no candidate")

    # (c) big-z but immaterial (flat baseline, tiny move) -> silent
    chk(_recent_week_result([10.0e6] * 12 + [10.02e6]) == [],
        "flat baseline + immaterial move -> silent (materiality required)")

    # (d) flat baseline + material break -> detected via the z=None path
    flat = _recent_week_result([10.0e6] * 12 + [8.0e6])
    chk(len(flat) == 1 and flat[0]["recent_week"]["robust_z"] is None
        and flat[0]["recent_week"]["facets"]["abnormal_vs_baseline"],
        "flat baseline + material break -> detected on materiality (robust_z None)")

    # (e) zero previous week + abnormal actual -> denominator falls back to the
    # trailing median (never a divide-by-zero) and the week is still detected.
    base = [5.0e6 + (0.03e6 if i % 2 else -0.03e6) for i in range(11)]
    zero_prev = _recent_week_result(base + [0.0, 2.0e6])
    chk(len(zero_prev) == 1 and zero_prev[0]["recent_week"]["change_pct"] is not None,
        "zero previous week -> change_pct uses the trailing median (no divide-by-zero)")

    # (f) value/volume divergence facet: value falls, volume rises
    div = _recent_week_result(stable + [8.5e6], volumes=[5.0e6] * 12 + [5.6e6])
    chk(len(div) == 1 and div[0]["recent_week"]["facets"]["value_volume_divergence"],
        "value down while volume up -> divergence facet set")

    # value/volume divergence facet stays False when no volume driver is folded
    chk(cands and not cands[0]["recent_week"]["facets"]["value_volume_divergence"],
        "no volume driver -> divergence facet stays False")

    _recent_week_pure_checks(chk)
    print("recent-week checks:", "ALL PASS" if ok else "FAILURES ABOVE")
    assert ok, "recent-week checks failed"


def _daily(n, start, value, alias="rev_cur", axis="POSTING_DATE", time=""):
    return [{axis: (start + timedelta(days=i)).isoformat() + time, alias: value} for i in range(n)]


def _recent_week_pure_checks(chk) -> None:
    st = {"insight_temporal_batch_share": 0.5, "insight_temporal_recon_tolerance_pct": 2.0}

    # pick_target_week: Monday 2026-07-20 -> last complete week Jul 13..19
    tw = rw.pick_target_week(date(2026, 7, 20), date(2026, 7, 19))
    chk(tw["week_start"] == date(2026, 7, 13) and tw["week_end"] == date(2026, 7, 19),
        "pick_target_week selects the last completed week, excludes the current one")
    # stale data -> steps back to the latest covered week (never the current one)
    tw2 = rw.pick_target_week(date(2026, 7, 20), date(2023, 12, 31))
    chk(tw2["week_end"] <= date(2023, 12, 31), "pick_target_week steps back for stale data")

    # judge_business_date: clean additive series -> ok (moved to
    # insight_business_day_source.py - the shared validation node)
    clean = _daily(40, date(2026, 6, 1), 1000.0)
    v = bds.judge_business_date(clean, "rev_cur", "POSTING_DATE", True, 40 * 1000.0, st)
    chk(v["verdict"] == "ok", "judge_business_date: clean additive series -> ok")
    # batch/load date: one day dominates
    batch = [{"POSTING_DATE": date(2026, 6, 30).isoformat(), "rev_cur": 1_000_000.0}]
    batch += _daily(30, date(2026, 6, 1), 10.0)
    vb = bds.judge_business_date(batch, "rev_cur", "POSTING_DATE", True, None, st)
    chk(vb["verdict"] == "batch_load_date", "judge_business_date: month-end batch -> rejected")
    # non-additive metric (metadata flag False)
    vn = bds.judge_business_date(clean, "rev_cur", "POSTING_DATE", False, 40 * 1000.0, st)
    chk(vn["verdict"] == "non_additive_metric", "judge_business_date: non-additive -> rejected")
    # reconciliation mismatch (flag True but sum != windowed total)
    vr = bds.judge_business_date(clean, "rev_cur", "POSTING_DATE", True, 999.0, st)
    chk(vr["verdict"] == "non_additive_metric", "judge_business_date: non-reconciling -> rejected")
    # timestamped axis -> rejected (calendar-day grain required)
    ts = _daily(40, date(2026, 6, 1), 1000.0, time="T12:30:00")
    vt = bds.judge_business_date(ts, "rev_cur", "POSTING_DATE", True, 40 * 1000.0, st)
    chk(vt["verdict"] == "timestamped_axis", "judge_business_date: timestamped axis -> rejected")

    # learn_operating_days ignores the partial boundary week
    rows = []
    # partial first week (Thu, Fri only), then 2 full Mon-Fri weeks, then a full week
    rows += [{"POSTING_DATE": (date(2026, 4, 2) + timedelta(days=i)).isoformat()} for i in (0, 1)]
    for wk in (date(2026, 4, 6), date(2026, 4, 13), date(2026, 4, 20)):
        rows += [{"POSTING_DATE": (wk + timedelta(days=i)).isoformat()} for i in range(5)]  # Mon-Fri
    op = bds.learn_operating_days(rows, "POSTING_DATE")
    chk(op == {0, 1, 2, 3, 4}, "learn_operating_days: Mon-Fri from interior weeks, weekends excluded")

    # effective_data_as_of: rolls back to the previous operating day only when
    # data_as_of IS "business today" and exclude_today is set; otherwise unchanged.
    eff1 = bds.effective_data_as_of(date(2026, 4, 10), date(2026, 4, 10), {0, 1, 2, 3, 4}, True)
    chk(eff1 == date(2026, 4, 9), "effective_data_as_of rolls back to the previous operating day")
    eff2 = bds.effective_data_as_of(date(2026, 4, 10), date(2026, 4, 11), {0, 1, 2, 3, 4}, True)
    chk(eff2 == date(2026, 4, 10), "effective_data_as_of is unchanged when data_as_of != today")
    eff3 = bds.effective_data_as_of(date(2026, 4, 10), date(2026, 4, 10), {0, 1, 2, 3, 4}, False)
    chk(eff3 == date(2026, 4, 10), "effective_data_as_of is unchanged when exclude_today is False")

    # fold_weeks: missing-weekend week complete, Monday-only week incomplete
    days = [{"POSTING_DATE": (date(2026, 4, 6) + timedelta(days=i)).isoformat(), "rev_cur": 2.0}
            for i in range(5)]                                   # full Mon-Fri week
    days += [{"POSTING_DATE": date(2026, 4, 13).isoformat(), "rev_cur": 9.0}]  # Monday only
    weeks = rw.fold_weeks(days, "POSTING_DATE", {0, 1, 2, 3, 4}, ["rev_cur"], date(2026, 4, 19))
    chk(len(weeks) == 1 and weeks[0]["week_start"] == "2026-04-06" and weeks[0]["rev_cur"] == 10.0,
        "fold_weeks: missing-weekend week complete, Monday-only week dropped, sums additive")

    # Regression (calendar must use TRUE data_as_of, never effective_data_as_of):
    # a still-loading partial Monday row (effective rolled back to the preceding
    # Friday) must not make calendar mode skip the already-complete preceding week.
    true_target = rw.pick_target_week(date(2026, 7, 20), date(2026, 7, 20))
    wrong_target = rw.pick_target_week(date(2026, 7, 20), date(2026, 7, 17))  # if effective were used
    chk(true_target["week_end"] == date(2026, 7, 19),
        "pick_target_week(true data_as_of) targets the already-complete week ending 2026-07-19")
    chk(wrong_target["week_end"] == date(2026, 7, 12),
        "pick_target_week(effective data_as_of) would WRONGLY skip to the week ending "
        "2026-07-12 - insight_recent_week.py's calendar branch must pass true data_as_of")

    # Rolling fold (round-1 fix): non-overlapping 7-day windows counting back
    # from effective_data_as_of, NOT a 1-day slide - and produces a different
    # row count/anchor than the calendar fold of the same rows.
    roll_rows = []
    d = date(2026, 5, 4)  # a Monday
    eff = date(2026, 7, 17)  # a Friday, 11 weeks later
    while d <= eff:
        if d.weekday() < 5:
            roll_rows.append({"POSTING_DATE": d.isoformat(), "rev_cur": 100.0})
        d += timedelta(days=1)
    operating58 = {0, 1, 2, 3, 4}
    weeks_cal = rw.fold_weeks(roll_rows, "POSTING_DATE", operating58, ["rev_cur"], eff)
    weeks_roll = rw.fold_rolling_windows(roll_rows, "POSTING_DATE", operating58, ["rev_cur"], eff)
    chk(bool(weeks_roll), "fold_rolling_windows produces at least one complete window")
    starts = sorted(date.fromisoformat(w["week_start"]) for w in weeks_roll)
    gaps = [(starts[i + 1] - starts[i]).days for i in range(len(starts) - 1)]
    chk(bool(gaps) and all(g == 7 for g in gaps),
        "rolling windows are non-overlapping (exactly 7 days apart), not a 1-day slide")
    chk(starts[-1] == eff - timedelta(days=6),
        "the target rolling window ends at effective_data_as_of")
    chk(weeks_cal and weeks_cal[-1]["week_start"] != weeks_roll[-1]["week_start"],
        "calendar and rolling folds of the same rows produce different anchors")


def _business_days(start: date, n: int) -> list:
    """n consecutive BUSINESS days (Mon-Fri), starting from `start`."""
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def daily_checks() -> None:
    """Phase 3b daily anomaly incidents, offline (no auth/LLM)."""
    print("\n=== daily anomaly incidents (Phase 3b) ===")
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")

    days = _business_days(date(2026, 1, 5), 90)  # ~18 weeks of business days
    eff = days[-1]
    base_rows = [{"POSTING_DATE": d.isoformat(), "rev_cur": 1000.0} for d in days]

    # (a) one isolated abnormal day -> exactly one daily_incident
    rows_a = [dict(r) for r in base_rows]
    target_day = days[-5]
    for r in rows_a:
        if r["POSTING_DATE"] == target_day.isoformat():
            r["rev_cur"] = 5000.0
    flagged_a = di.flag_abnormal_days(rows_a, "POSTING_DATE", "rev_cur", 28, 3, 3.0, 3.0, eff)
    incidents_a = di.merge_incidents(flagged_a, {0, 1, 2, 3, 4})
    chk(len(incidents_a) == 1
        and incidents_a[0]["episode_start"] == incidents_a[0]["episode_end"] == target_day.isoformat(),
        "one isolated abnormal day -> exactly one daily_incident")

    # (b) a 3-day consecutive dip -> ONE incident, not three
    rows_b = [dict(r) for r in base_rows]
    dip_days = [days[-7].isoformat(), days[-6].isoformat(), days[-5].isoformat()]
    for r in rows_b:
        if r["POSTING_DATE"] in dip_days:
            r["rev_cur"] = 100.0
    flagged_b = di.flag_abnormal_days(rows_b, "POSTING_DATE", "rev_cur", 28, 3, 3.0, 3.0, eff)
    incidents_b = di.merge_incidents(flagged_b, {0, 1, 2, 3, 4})
    chk(len(incidents_b) == 1 and incidents_b[0]["day_count"] == 3,
        "a 3-day consecutive dip merges into ONE incident, not three")
    score_b = di.score_incident(incidents_b[0])
    chk(score_b > 0, "score_incident is positive for a real incident")

    # (c) systematic weekend low -> NOT flagged. First prove each reference's
    # OWN test in isolation (the trailing reference alone WOULD flag it; the
    # same-weekday reference correctly vetoes it), then prove the combined
    # AND-gate actually suppresses the day end-to-end.
    trailing_ref = ([1000.0 + (10 if i % 2 else -10) for i in range(10)]
                    + [700.0] * 8
                    + [1000.0 + (10 if i % 2 else -10) for i in range(10)])
    res_trailing = di._test_reference(700.0, trailing_ref, 3.0, 3.0)
    chk(res_trailing is not None and res_trailing[0],
        "isolated trailing reference DOES flag a weekend-level value (trailing_pass=True)")
    res_weekday = di._test_reference(700.0, [700.0] * 5, 3.0, 3.0)
    chk(res_weekday is not None and not res_weekday[0],
        "isolated same-weekday reference does NOT flag it (flat, matches every prior Saturday)")

    full_days = [date(2026, 1, 5) + timedelta(days=i) for i in range(98)]  # 14 full 7-day weeks
    rows_c = [{"POSTING_DATE": d.isoformat(),
              "rev_cur": (700.0 if d.weekday() >= 5 else
                          1000.0 + (10 if d.toordinal() % 2 else -10))} for d in full_days]
    flagged_c = di.flag_abnormal_days(rows_c, "POSTING_DATE", "rev_cur", 28, 3, 3.0, 3.0, full_days[-1])
    weekend_flags = [f for f in flagged_c if f["date"].weekday() >= 5]
    chk(weekend_flags == [],
        "end-to-end: a systematic weekend low is NOT flagged (same-weekday reference vetoes it)")

    # (d) sparse weekday history -> falls back to trailing-only z, not silent.
    # Only 2 prior Saturdays exist (< min_weekday_occurrences=3), so the
    # same-weekday reference must be skipped, not treated as unavailable-and-fail.
    sparse_days = _business_days(date(2026, 1, 5), 40) + [date(2026, 3, 7), date(2026, 3, 14)]
    sparse_days.sort()
    sparse_rows = [{"POSTING_DATE": d.isoformat(), "rev_cur": 1000.0} for d in sparse_days]
    target_sparse = date(2026, 3, 21)  # a 3rd Saturday - still below min_weekday_occ (2 prior)
    sparse_rows.append({"POSTING_DATE": target_sparse.isoformat(), "rev_cur": 3000.0})
    flagged_d = di.flag_abnormal_days(sparse_rows, "POSTING_DATE", "rev_cur", 28, 3, 3.0, 3.0,
                                      target_sparse)
    chk(any(f["date"] == target_sparse for f in flagged_d),
        "sparse same-weekday history (< min_weekday_occurrences) falls back to trailing-only z")

    # (e) a Friday+Monday incident spanning a closed weekend merges into ONE
    # via operating-day adjacency (Mon-Fri operating; Sat/Sun closed). Index 39
    # is a Friday (39 % 5 == 4) and index 40 is the immediately following
    # Monday - both well past the 28-day warm-up and clear of other fixtures.
    fri, mon = days[39], days[40]
    assert fri.weekday() == 4 and mon.weekday() == 0 and (mon - fri).days == 3
    rows_e = [dict(r) for r in base_rows]
    for r in rows_e:
        if r["POSTING_DATE"] in (fri.isoformat(), mon.isoformat()):
            r["rev_cur"] = 100.0
    flagged_e = di.flag_abnormal_days(rows_e, "POSTING_DATE", "rev_cur", 28, 3, 3.0, 3.0, eff)
    incidents_e = di.merge_incidents(flagged_e, {0, 1, 2, 3, 4})
    matching = [i for i in incidents_e if i["episode_start"] == fri.isoformat()]
    chk(bool(matching) and matching[0]["episode_end"] == mon.isoformat() and matching[0]["day_count"] == 2,
        "a Friday+Monday dip bridging a closed weekend merges into ONE incident")

    # (f) a perfectly flat trailing baseline with a material break is still
    # flagged via the materiality-only fallback (robust z undefined on flat data).
    rows_f = [{"POSTING_DATE": d.isoformat(), "rev_cur": 1000.0} for d in days]
    for r in rows_f:
        if r["POSTING_DATE"] == target_day.isoformat():
            r["rev_cur"] = 1200.0
    flagged_f = di.flag_abnormal_days(rows_f, "POSTING_DATE", "rev_cur", 28, 3, 3.0, 3.0, eff)
    chk(any(f["date"] == target_day and f["z"] is None for f in flagged_f),
        "a flat baseline with a material break is flagged via materiality alone (z is None)")

    # (g) exclusive dispatch: a daily_incidents table produces ONLY
    # daily_incident candidates - no generic concentration/outlier candidates
    # leak through from the incident rows' numeric fields (episode_start,
    # peak_z, cumulative_impact, day_count, ...).
    inc_rows = [{
        "episode_start": target_day.isoformat(), "episode_end": target_day.isoformat(),
        "direction": 1, "peak_z": 8.0, "day_count": 1, "actual_total": 5000.0,
        "expected_total": 1000.0, "cumulative_impact": 4000.0,
        "metric": "rev_cur", "axis": "'F'[POSTING_DATE]",
        "segment": f"'F'[POSTING_DATE]={target_day.isoformat()}",
        "score": di.score_incident({"cumulative_impact": 4000.0, "expected_total": 1000.0}),
    } for _ in range(1)]
    contract_g = {"coverage_kind": "daily_incidents", "date_axis": "'F'[POSTING_DATE]",
                 "grouping_references": []}
    state_g = _base_state()
    state_g["insight_evidence_contracts"] = {"meta_daily_incidents": contract_g}
    state_g["insight_clean_data"] = {"queries": [
        {"query_name": "meta_daily_incidents", "status": "success", "rows": inc_rows}]}
    res_g = insight_stat_detector.run(state_g)["insight_stat_candidates"]
    types_g = {c["type"] for c in res_g["business_candidates"]}
    chk(types_g == {"daily_incident"},
        f"a daily_incidents table produces ONLY daily_incident candidates, got {types_g}")

    print("daily anomaly checks:", "ALL PASS" if ok else "FAILURES ABOVE")
    assert ok, "daily anomaly checks failed"


def rolling_observation_checks() -> None:
    """Phase 3b: the rolling detector must emit insight_rolling_observation
    every run, including when the reading is not significant (needed so
    memory can later learn that an incident recovered)."""
    print("\n=== rolling observation always-emitted (Phase 3b) ===")
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")

    def _rolling_result(values, **overrides):
        rows = [{"week_start": (_MONDAY + timedelta(days=7 * i)).isoformat(), "rev_cur": float(v)}
                for i, v in enumerate(values)]
        roles = {"rev_cur": {"bundle_id": "F::revenue", "phase": "current",
                             "semantic_role": "value", "family": "revenue"}}
        contract = {"coverage_kind": "recent_week_rolling_history", "axis": "week_start",
                   "date_axis": "'F'[POSTING_DATE]", "metric_roles": roles,
                   "week_start": rows[-1]["week_start"],
                   "week_end": (date.fromisoformat(rows[-1]["week_start"]) + timedelta(days=6)).isoformat(),
                   "window_end": rows[-1]["week_start"], "grouping_references": ["[week_start]"]}
        state = _base_state()
        state.update({"insight_week_materiality_pct": 3.0, "insight_week_z_cutoff": 2.5,
                      "insight_candidates_weekly": 10, "insight_candidates_high": 20,
                      "insight_evidence_contracts": {"meta_recent_week_history": contract}})
        state.update(overrides)
        state["insight_clean_data"] = {"queries": [
            {"query_name": "meta_recent_week_history", "status": "success", "rows": rows}]}
        return insight_stat_detector.run(state)

    noise = [0.02e6 if i % 2 else -0.02e6 for i in range(12)]
    stable = [10.0e6 + n for n in noise]

    # normal (insignificant) reading -> no candidate, but observation IS emitted
    out_normal = _rolling_result(stable + [10.05e6])
    cands_normal = [c for c in out_normal["insight_stat_candidates"]["business_candidates"]
                    if c["type"] == "recent_week_movement"]
    obs_normal = out_normal.get("insight_rolling_observation")
    chk(cands_normal == [], "an insignificant rolling reading produces no candidate")
    chk(obs_normal is not None and obs_normal.get("active") is False,
        "but insight_rolling_observation IS still emitted, marked inactive")
    chk("story_key" not in obs_normal,
        "the observation carries NO story_key - the novelty filter is the sole place that adds one")

    # significant reading -> candidate AND observation, both consistent
    out_sig = _rolling_result(stable + [8.5e6])
    cands_sig = [c for c in out_sig["insight_stat_candidates"]["business_candidates"]
                if c["type"] == "recent_week_movement"]
    obs_sig = out_sig.get("insight_rolling_observation")
    chk(len(cands_sig) == 1 and cands_sig[0]["recent_week"]["window_mode"] == "rolling",
        "a significant rolling reading produces one candidate with window_mode='rolling'")
    chk(obs_sig is not None and obs_sig.get("active") is True,
        "and the observation is marked active, consistent with the candidate")

    print("rolling observation checks:", "ALL PASS" if ok else "FAILURES ABOVE")
    assert ok, "rolling observation checks failed"


def show(result: dict, label: str) -> None:
    print(f"\n=== {label} ===")
    print(f"grand totals seen: {list(result.get('grand_totals_seen', {}))}")
    print(f"additive metrics:  {result.get('additive_metrics')}")
    print(f"ratio metrics:     {result.get('ratio_metrics')}")
    for pool in ("business_candidates", "data_quality_candidates"):
        cands = result.get(pool, [])
        print(f"\n{pool} ({len(cands)}):")
        for c in cands:
            print(f"  [{c['score']:8.2f}] {c['id']}: {c['detail']}")
    # every candidate payload must be JSON-safe (no inf/nan survives json.dumps
    # with allow_nan=False)
    json.dumps(result, allow_nan=False, default=str)
    print("\nJSON-safety check passed (no Infinity/NaN in payload).")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--synthetic" in args:
        show(synthetic_suite(), "synthetic edge cases")
        recent_week_checks()
        daily_checks()
        rolling_observation_checks()
        return 0
    src = Path(args[0]) if args else PROJECT_ROOT / "outputs" / "insight_clean_data.json"
    show(replay(src), f"replay of {src}")
    show(synthetic_suite(), "synthetic edge cases")
    period = synthetic_period_suite()
    show(period, "synthetic period series (Phase 2)")
    cands = period["business_candidates"]
    by_type = {}
    for c in cands:
        by_type.setdefault(c["type"], []).append(c)
    movers = by_type.get("period_change_contribution", [])
    oct_c = next((c for c in movers if c.get("period_label") == "October"), None)
    assert movers, "expected period_change_contribution candidates"
    assert len(movers) <= 4 and all("None" not in c["segment"] for c in movers), \
        "null period member must be excluded and top-movers capped"
    assert oct_c is not None, "October (month 10) should be labelled and present"
    assert oct_c.get("impact_share") is not None and 35 <= abs(oct_c["impact_share"]) <= 45, \
        f"October should reconcile to ~39% of the change, got {oct_c.get('impact_share')}"
    assert "Technology" in oct_c["detail"], "worst-period drill should attach the primary segment"
    assert by_type.get("period_sustained_decline"), "expected a sustained-decline run"
    assert by_type.get("period_reversal"), "expected a reversal"
    assert by_type.get("period_value_volume_divergence"), "expected a value/volume divergence"
    print(f"\nPeriod check passed: {len(movers)} movers (Oct {oct_c['impact_share']:.1f}%, "
          f"drill attached), patterns: "
          f"{[t for t in by_type if t.startswith('period_') and t != 'period_change_contribution']}.")

    recent_week_checks()
    daily_checks()
    rolling_observation_checks()
    return 0


if __name__ == "__main__":
    sys.exit(main())
