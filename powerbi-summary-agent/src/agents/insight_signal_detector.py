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


def _apply_caps(signals: List[dict], max_signals: int, max_dq: int) -> List[dict]:
    """Enforce the overall cap and the data-quality sub-cap in the LLM's
    ranking order, so DQ findings can never crowd out business findings."""
    kept, dq_count = [], 0
    for s in signals:
        if len(kept) >= max_signals:
            break
        if s.get("kind") == "data_quality":
            if dq_count >= max_dq:
                continue
            dq_count += 1
        kept.append(s)
    return kept


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
            signal["candidate_id"] = candidate.get("id")
            signal["impact_value"] = candidate.get("impact_value")
            signal["impact_share"] = candidate.get("impact_share")
            signal["evidence_query"] = candidate.get("table") or signal.get("evidence_query")
            signal["kind"] = candidate.get("kind", signal.get("kind"))
            signal["decomposition"] = candidate.get("rate_volume") or signal.get("decomposition")
            signal["segment_members"] = candidate.get("segment_members") or signal.get("segment_members")
    return signals


_LEVEL_RANK = {"high": 0, "period": 1, "weekly": 1, "daily": 2}


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
        sig["candidate_id"] = cand.get("id")
        sig["impact_value"] = cand.get("impact_value")
        sig["impact_share"] = cand.get("impact_share")
        sig["evidence_query"] = cand.get("table") or sig.get("evidence_query")
        sig["kind"] = cand.get("kind", sig.get("kind"))
        sig["decomposition"] = cand.get("rate_volume") or sig.get("decomposition")
        sig["segment_members"] = cand.get("segment_members") or sig.get("segment_members")
        # Story identity carried from the deterministic candidate (for commit).
        sig["level"] = cand.get("level", "high")
        sig["story_key"] = cand.get("story_key")
        fields = cand.get("story_fields", {}) or {}
        for f in ("segment", "metric", "dimension", "analysis_type",
                  "period_anchor", "direction"):
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


def _slot_fill(signals: List[dict], cap: int, max_dq: int) -> List[dict]:
    """Cascade slot-filling: order by (level priority high->weekly->daily, then the
    LLM's materiality rank), take up to `cap`, enforce the data-quality sub-cap.
    Applied AFTER the LLM so a merge that collapses several high candidates frees
    the slots for weekly/daily the LLM already saw."""
    indexed = sorted(enumerate(signals),
                     key=lambda p: (_LEVEL_RANK.get(p[1].get("level", "high"), 0), p[0]))
    kept, dq = [], 0
    for _, s in indexed:
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
                  "`related_candidate_ids`. Candidates are level-tagged; prefer "
                  "higher-priority levels (high, then weekly, then daily) first.")

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
        signals = _slot_fill(bound, cap, max_dq)
    else:
        bound = _bind_candidates(raw, eligible)
        signals = _apply_caps(bound, cap, max_dq)

    dropped_caps = len(bound) - len(signals)
    if dropped_caps > 0:
        log.info(f"Caps/slot-fill dropped {dropped_caps} signal(s) "
                 f"(max {cap} total, max {max_dq} data-quality).")

    reason = "ok" if signals else (novelty.get("reason") or "no_new_selected")
    return _finish(state, log, signals, novelty, reason=reason)
