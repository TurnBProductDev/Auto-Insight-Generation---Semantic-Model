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


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: detecting notable signals in scan results...")

    max_signals = state.get("insight_max_signals", 5)
    max_dq = state.get("insight_max_dq_signals", 2)
    materiality_pct = state.get("insight_materiality_pct", 1.0)
    clean = state.get("insight_clean_data", {"queries": []})
    understanding = state.get("report_understanding", {})

    if not clean.get("successful"):
        log.error("Insight scan returned no usable data - no signals to detect.")
        file_io.write_json(state, "insight_signals.json", [])
        return {"insight_signals": [], **log.updates()}

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("insight_signal_detector_prompt.md")

    context = {
        "report_understanding": understanding,
        "stat_candidates": state.get("insight_stat_candidates", {}),
        "scan_results": clean,
    }

    llm = get_llm(state, structured_schema=SignalList)
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task
         + f"\n\nFlag at most {max_signals} signals."
         + f"\nMateriality floor: ignore movements smaller than "
           f"{materiality_pct}% of the relevant grand total unless they "
           f"indicate a data-quality problem."},
        {"role": "user", "content": "REPORT UNDERSTANDING + STAT CANDIDATES + SCAN RESULTS:\n" + dumps(context)},
    ]

    result: SignalList = llm.invoke(messages)
    raw = _bind_candidates([s.model_dump() for s in result.signals],
                           state.get("insight_stat_candidates", {}))
    signals = _apply_caps(raw, max_signals, max_dq)
    dropped = len(raw) - len(signals)
    if dropped:
        log.info(f"Caps dropped {dropped} signal(s) "
                 f"(max {max_signals} total, max {max_dq} data-quality).")

    file_io.write_json(state, "insight_signals.json", signals)
    log.info(f"Detected {len(signals)} signals: " + ", ".join(
        f"{s['id']}[{s.get('kind', '?')}]" for s in signals))
    return {"insight_signals": signals, **log.updates()}
