"""Insight branch - Signal Detector (LLM, structured output).

Reads the normalized scan results and flags up to insight_max_signals
genuinely notable findings, ranked by materiality (size of the movement x
share of the total at stake) - not routine facts. Each signal is classified
as a business finding or a data-quality issue, carries a quantified impact,
and names the question the investigator should try to answer.

Data-quality signals are capped in code (insight_max_dq_signals) so
reconciliation noise can never crowd business findings out of the list.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from ..tools import file_io
from ..tools.llm import get_llm
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


class Signal(BaseModel):
    candidate_id: Optional[str] = Field(
        default=None,
        description="id of the deterministic stat candidate selected for this signal, when applicable.",
    )
    related_candidate_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "ids of OTHER eligible stat candidates this signal merges/covers (the "
            "same underlying story seen through another metric or analysis). Used so "
            "every covered finding is marked seen and none reappears next run."
        ),
    )
    decomposition: Optional[List[dict]] = Field(
        default=None,
        description="Exact price-volume decomposition carried by the deterministic candidate.",
    )
    id: str = Field(description="Short snake_case unique id.")
    kind: Literal["business", "data_quality"] = Field(
        description=(
            "'business' = a real movement, concentration, or outlier in the "
            "business numbers. 'data_quality' = the numbers themselves look "
            "wrong: non-reconciling totals, blank/zero where volume is "
            "expected, non-differentiating or miscalculated metrics."
        )
    )
    description: str = Field(
        description="One factual sentence stating the notable finding, citing the numbers."
    )
    affected_segment: str = Field(
        description=(
            "The specific segment/entity the signal concerns (the category, "
            "location, period, or metric name from the scan rows). Use "
            "'overall' if it concerns the whole model."
        )
    )
    segment_members: Optional[List[str]] = Field(
        default=None,
        description=(
            "Exact metadata member values represented by a multi-segment "
            "finding. Null for ordinary single-segment findings."
        ),
    )
    impact_value: Optional[float] = Field(
        default=None,
        description=(
            "Signed size of the movement or gap in the measure's own units, "
            "computed from scan rows (e.g. the change amount, or the segment "
            "total at stake). null only if the scan rows genuinely do not "
            "allow computing one."
        ),
    )
    impact_share: Optional[float] = Field(
        default=None,
        description=(
            "The impact as a percentage (0-100) of the relevant grand total, "
            "computed from scan rows. null only if no usable total exists in "
            "the scan results."
        ),
    )
    question: str = Field(
        description="The 'why' question an analyst would drill into next."
    )
    evidence_query: str = Field(
        description="query_name of the scan query whose rows evidence this signal."
    )


class SignalList(BaseModel):
    signals: List[Signal]


def _copy_candidate_facts(signal: dict, candidate: dict) -> None:
    """Copy a deterministic candidate's computed facts onto a signal - the
    auditable foreign key that prevents small LLM numerical rewrites from breaking
    evidence assembly. The Phase-3 recent-week structured payload (week bounds,
    actual/previous/expected, WoW %, robust z, drivers) is copied verbatim so the
    synthesizer/memory/API/tiles read structured values, never the LLM's prose -
    including for a rolling-window reading, which reuses the SAME `recent_week`
    payload with `window_mode: "rolling"` inside it rather than a second key.
    `score` is copied too so every level (high/period/recent_week/
    recent_week_rolling/daily) can be ranked on one shared materiality scale
    with no per-level priority."""
    signal["candidate_id"] = candidate.get("id")
    signal["impact_value"] = candidate.get("impact_value")
    signal["impact_share"] = candidate.get("impact_share")
    signal["evidence_query"] = candidate.get("table") or signal.get("evidence_query")
    signal["kind"] = candidate.get("kind", signal.get("kind"))
    signal["decomposition"] = candidate.get("rate_volume") or signal.get("decomposition")
    signal["segment_members"] = candidate.get("segment_members") or signal.get("segment_members")
    signal["score"] = candidate.get("score", signal.get("score", 0.0))
    if candidate.get("recent_week"):
        signal["recent_week"] = candidate.get("recent_week")
        # The memory whitelist (insight_memory.commit_run) reads a TOP-LEVEL
        # change_pct off the signal, not the nested payload - without this the
        # rolling-week delta-pct resurface trigger has nothing to compare.
        signal["change_pct"] = candidate["recent_week"].get("change_pct")
        for f in ("week_start", "week_end"):
            if candidate.get(f) is not None:
                signal[f] = candidate.get(f)
        if (candidate.get("recent_week") or {}).get("data_as_of") is not None:
            signal["data_as_of"] = candidate["recent_week"]["data_as_of"]
    if candidate.get("type") == "daily_incident":
        for f in ("episode_start", "episode_end", "peak_z", "day_count",
                  "actual_total", "expected_total"):
            if candidate.get(f) is not None:
                signal[f] = candidate.get(f)


def _bind_candidates(signals: List[dict], candidates: dict) -> List[dict]:
    """Attach the exact deterministic candidate and copy its computed facts.

    This turns the LLM's semantic selection into an auditable foreign key and
    prevents small numerical rewrites from breaking evidence assembly.
    """
    all_candidates = (candidates.get("business_candidates", [])
                      + candidates.get("data_quality_candidates", []))
    by_id = {c.get("id"): c for c in all_candidates if c.get("id")}
    for signal in signals:
        candidate = by_id.get(signal.get("candidate_id"))
        if candidate is None:
            seg = str(signal.get("affected_segment"))
            value = signal.get("impact_value")
            options = [c for c in all_candidates if str(c.get("segment")) == seg]
            if options:
                def gap(c):
                    cv = c.get("impact_value")
                    if isinstance(value, (int, float)) and isinstance(cv, (int, float)):
                        return abs(value - cv)
                    return 0.0
                candidate = min(options, key=gap)
        if candidate:
            _copy_candidate_facts(signal, candidate)
    return signals


def _bind_eligible(signals: List[dict], eligible: dict) -> tuple[List[dict], int]:
    """Memory-mode binding: bind ONLY by an exact candidate_id present in the
    eligible allowlist and drop anything else. No segment heuristic - in memory
    mode it could attach a suppressed story to an unrelated eligible candidate.
    Copies computed facts and the candidate's story identity onto the signal, and
    resolves related_candidate_ids into covered_story_keys."""
    all_c = (eligible.get("business_candidates", []) or []) + \
            (eligible.get("data_quality_candidates", []) or [])
    by_id = {c.get("id"): c for c in all_c if c.get("id")}
    bound, dropped = [], 0
    for sig in signals:
        cand = by_id.get(sig.get("candidate_id"))
        if cand is None:
            dropped += 1
            continue
        _copy_candidate_facts(sig, cand)
        # Story identity carried from the deterministic candidate (for commit).
        sig["level"] = cand.get("level", "high")
        sig["story_key"] = cand.get("story_key")
        fields = cand.get("story_fields", {}) or {}
        for f in ("segment", "metric", "dimension", "analysis_type",
                  "period_anchor", "direction", "axis", "anchor", "week_start", "week_end",
                  "change_pct", "episode_end", "peak_z"):
            if fields.get(f) is not None:
                sig[f] = fields.get(f)
        covered = [sig["story_key"]] if sig.get("story_key") else []
        for rid in (sig.get("related_candidate_ids") or []):
            rc = by_id.get(rid)
            if rc and rc.get("story_key"):
                covered.append(rc["story_key"])
        sig["covered_story_keys"] = list(dict.fromkeys(covered))
        bound.append(sig)
    return bound, dropped


def _signal_from_candidate(cand: dict) -> dict:
    """Build a signal deterministically from a candidate's structured facts
    (templated description) - used only as a backstop when the LLM's response
    dropped an eligible candidate the LLM itself should have covered, so nothing
    material silently disappears to an LLM omission. No second LLM call."""
    rw = cand.get("recent_week")
    if rw:
        cp = rw.get("change_pct")
        direction = "declined" if (rw.get("abs_impact") or 0) < 0 else "rose"
        pct = f"{abs(cp):.1f}% " if isinstance(cp, (int, float)) else ""
        if rw.get("window_mode") == "rolling":
            desc = (f"Over the trailing 7 days ending {rw.get('week_end')}, "
                    f"{cand.get('metric')} {direction} {pct}vs the prior 7 days "
                    f"to {rw.get('actual')} (previous {rw.get('previous')}, "
                    f"trailing-median {rw.get('expected')}).")
            sig_id = f"recent_week_rolling_{rw.get('week_end')}"
            question = "What drove the trailing 7 days' movement versus the prior 7 days?"
        else:
            desc = (f"In the week of {rw.get('week_start')}, {cand.get('metric')} {direction} "
                    f"{pct}week-over-week to {rw.get('actual')} (previous week "
                    f"{rw.get('previous')}, trailing-median {rw.get('expected')}).")
            sig_id = f"recent_week_{rw.get('week_start')}"
            question = "What drove the most recently completed week's movement versus its norm?"
    elif cand.get("type") == "daily_incident":
        direction = "declined" if (cand.get("impact_value") or 0) < 0 else "rose"
        desc = (f"Between {cand.get('episode_start')} and {cand.get('episode_end')}, "
                f"{cand.get('metric')} {direction} {cand.get('impact_value')} "
                f"vs expected {cand.get('expected_total')}.")
        sig_id = f"daily_incident_{cand.get('episode_start')}"
        question = "What drove this daily incident?"
    else:
        desc = cand.get("detail") or f"{cand.get('type')}: {cand.get('metric')} at {cand.get('segment')}."
        sig_id = cand.get("id") or "injected_signal"
        question = "What is driving this finding?"
    sig = {
        "id": sig_id, "kind": cand.get("kind", "business"), "description": desc,
        "affected_segment": cand.get("segment") or "overall", "question": question,
        "evidence_query": cand.get("table"), "level": cand.get("level", "high"),
        "story_key": cand.get("story_key"),
        "covered_story_keys": [cand["story_key"]] if cand.get("story_key") else [],
        "injected": True,
    }
    _copy_candidate_facts(sig, cand)
    fields = cand.get("story_fields", {}) or {}
    for f in ("segment", "metric", "axis", "anchor", "analysis_type", "direction",
              "week_start", "week_end", "change_pct", "episode_end", "peak_z"):
        if fields.get(f) is not None:
            sig[f] = fields.get(f)
    return sig


def _backfill_uncovered(bound: List[dict], eligible: dict) -> List[dict]:
    """No level gets priority ordering - but a level (high/period/recent_week/daily)
    should never go entirely INVISIBLE just because an LLM prompt is more familiar
    with older levels than a newer one. This only backstops whole levels the LLM's
    response touched not at all (not individual candidates: the LLM's job of
    deduplicating/merging near-duplicate candidates within a level is preserved -
    injecting every uncovered candidate would flood the list with mechanical
    near-duplicates instead of synthesized stories). For each level with eligible
    material candidates but zero covered signals, inject its single best (highest
    score) candidate; it then competes purely on materiality like everything else."""
    covered = {s.get("candidate_id") for s in bound}
    for s in bound:
        covered |= set(s.get("related_candidate_ids") or [])
    covered_levels = {s.get("level") for s in bound}
    business = eligible.get("business_candidates", []) or []
    by_level: dict = {}
    for c in business:
        if c.get("id") and c.get("story_key"):
            by_level.setdefault(c.get("level", "high"), []).append(c)
    injected = []
    for level, cands in by_level.items():
        if level in covered_levels:
            continue
        best = max(cands, key=lambda c: c.get("score", 0.0))
        injected.append(_signal_from_candidate(best))
    return bound + injected


def _rank_and_cap(signals: List[dict], cap: int, max_dq: int) -> List[dict]:
    """Take up to `cap` signals ranked purely by materiality score (highest first,
    ties broken by original order) - no level (high/period/recent_week/daily) gets
    special priority; whatever the model found competes on equal footing. The DQ
    sub-cap still holds so reconciliation noise can't crowd out business findings."""
    ranked = sorted(enumerate(signals), key=lambda p: (-(p[1].get("score") or 0.0), p[0]))
    kept, dq = [], 0
    for _, s in ranked:
        if len(kept) >= cap:
            break
        if s.get("kind") == "data_quality":
            if dq >= max_dq:
                continue
            dq += 1
        kept.append(s)
    return kept


def _finish(state: dict, log: RunLogger, signals: List[dict],
            novelty: dict, reason: str) -> dict:
    file_io.write_json(state, "insight_signals.json", signals)
    novelty = dict(novelty)
    novelty["selected"] = len(signals)
    novelty["reason"] = reason
    file_io.write_json(state, "insight_novelty.json", novelty)
    if signals:
        log.info(f"Detected {len(signals)} signals: " + ", ".join(
            f"{s.get('id')}[{s.get('kind', '?')}]" for s in signals))
    else:
        log.info(f"No signals reported ({reason}).")
    return {"insight_signals": signals, "insight_novelty": novelty, **log.updates()}


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: detecting notable signals in scan results...")

    memory_enabled = bool(state.get("insight_memory_enabled", True))
    max_dq = state.get("insight_max_dq_signals", 2)
    materiality_pct = state.get("insight_materiality_pct", 1.0)
    clean = state.get("insight_clean_data", {"queries": []})
    understanding = state.get("report_understanding", {})
    novelty = dict(state.get("insight_novelty", {}) or {})

    cap = int(state.get("insight_max_new_per_run", 3)) if memory_enabled \
        else int(state.get("insight_max_signals", 5))

    # In memory mode the novelty filter already suppressed seen findings; work from
    # its eligible (unseen) shortlist. Otherwise fall back to the full stat list.
    eligible = state.get("insight_eligible_candidates") if memory_enabled else None
    if not eligible:
        eligible = state.get("insight_stat_candidates",
                             {"business_candidates": [], "data_quality_candidates": []})
    has_candidates = bool(eligible.get("business_candidates") or
                          eligible.get("data_quality_candidates"))

    if not clean.get("successful"):
        log.error("Insight scan returned no usable data - no signals to detect.")
        return _finish(state, log, [], novelty, reason="no_scan_data")

    # Memory mode with nothing unseen: don't fabricate; report it clearly.
    if memory_enabled and not has_candidates:
        reason = novelty.get("reason") or "all_previously_reported"
        log.info(f"Insight branch: no eligible (unseen) candidates - {reason}.")
        return _finish(state, log, [], novelty, reason=reason)

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("insight_signal_detector_prompt.md")

    context = {
        "report_understanding": understanding,
        "stat_candidates": eligible,
        "scan_results": clean,
    }

    extra = (f"\n\nReturn at most {cap} signals."
             f"\nMateriality floor: ignore movements smaller than "
             f"{materiality_pct}% of the relevant grand total unless they "
             f"indicate a data-quality problem.")
    if memory_enabled:
        extra += ("\n\nThe STAT CANDIDATES above are the ELIGIBLE set: findings NOT "
                  "reported in previous runs. Select ONLY from them and return each "
                  "chosen signal's exact `candidate_id`. When you merge several "
                  "candidates into one story, list the others in "
                  "`related_candidate_ids`. Select whatever is genuinely material "
                  "across ALL levels (high, period/weekly, recent_week, daily) - "
                  "none is prioritized over another; rank purely by materiality.")

    llm = get_llm(state, structured_schema=SignalList)
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task + extra},
        {"role": "user", "content": "REPORT UNDERSTANDING + STAT CANDIDATES + SCAN RESULTS:\n" + dumps(context)},
    ]

    result: SignalList = llm.invoke(messages)
    raw = [s.model_dump() for s in result.signals]

    if memory_enabled:
        bound, dropped = _bind_eligible(raw, eligible)
        if dropped:
            log.info(f"Dropped {dropped} signal(s) not bound to an eligible candidate "
                     f"(exact-id-only in memory mode).")
        before = len(bound)
        bound = _backfill_uncovered(bound, eligible)
        if len(bound) > before:
            log.info(f"Backfilled {len(bound) - before} eligible candidate(s) the LLM "
                     f"omitted (added to the pool, ranked equally with everything else).")
    else:
        bound = _bind_candidates(raw, eligible)

    signals = _rank_and_cap(bound, cap, max_dq)
    dropped_caps = len(bound) - len(signals)
    if dropped_caps > 0:
        log.info(f"Cap dropped {dropped_caps} lower-materiality signal(s) "
                 f"(max {cap} total, max {max_dq} data-quality).")

    reason = "ok" if signals else (novelty.get("reason") or "no_new_selected")
    return _finish(state, log, signals, novelty, reason=reason)
