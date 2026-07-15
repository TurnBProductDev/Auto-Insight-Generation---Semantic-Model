"""Insight branch - Investigator (LLM tool-calling agent).

For each detected signal the LLM gets three real tools and drives the
drill-down itself, the way an analyst would:

  * run_dax(dax)               - validated first (dax_validator.validate_one),
                                 then executed against the live model; rows
                                 cleaned and capped at insight_probe_max_rows.
  * get_measure_definition(measure_names) - returns the DAX expression behind
                                 model measures straight from Node 2's
                                 metadata; free (no Power BI call, no budget).
  * conclude(likely_explanation) - ends the investigation with a hedged
                                 (contribution/correlation) explanation.

The hard safety cap is on actual run_dax EXECUTIONS per signal
(insight_max_investigation_rounds, default 3) - not LLM turns, since one turn
can batch several tool calls. Validator-rejected probes don't consume budget
(they never hit Power BI) but every attempt - accepted, rejected,
budget-refused, or errored - is logged in the trail. If the budget is
exhausted without conclude, one final plain-text turn forces closure.
"""

from typing import List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..tools.llm import get_llm
from ..utils.json_utils import clean_rows, dumps
from ..utils.logger import RunLogger
from ..utils.model_context import llm_model_context

from .dax_validator import validate_one
from .evidence_contract import dax_hash
from .scope_validator import validate_comparable_scope


class run_dax(BaseModel):
    """Execute one DAX query against the live Power BI model and get its rows back.

    The query must contain exactly one EVALUATE, reference only real
    tables/columns/measures from AVAILABLE MODEL OBJECTS, and include a TOPN
    row limit on any query that can return more than one row. Invalid queries
    are rejected before execution with the reason.
    """

    dax: str = Field(description="One complete executable DAX statement.")


class get_measure_definition(BaseModel):
    """Look up the DAX formula behind one or more model measures.

    Free: this reads the model metadata already in memory - no Power BI
    query, and it does NOT consume your run_dax budget. Use it whenever a
    measure returns blank, zero, Infinity, or otherwise suspicious values:
    read its formula first to see which tables/columns it actually depends
    on, then aim your next probe at those instead of slicing blind.
    """

    measure_names: List[str] = Field(
        description="Exact measure names (as listed in AVAILABLE MODEL OBJECTS) to look up."
    )


class conclude(BaseModel):
    """Finish the investigation with your likely explanation of the signal.

    Power BI aggregates can show contribution, concentration, segmentation,
    and correlation - they cannot prove root cause. Phrase the explanation in
    hedged terms ('likely contributor', 'associated with', 'concentrated in'),
    never as an asserted cause. Call this exactly once, when the evidence you
    have gathered is enough to answer the signal's question - or to say it
    can't be answered from this model.
    """

    likely_explanation: str = Field(
        description="2-6 sentences: what the probes showed and the hedged likely explanation."
    )


def _content_text(resp) -> str:
    content = getattr(resp, "content", resp)
    if isinstance(content, list):  # some providers return content blocks
        content = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content or "").strip()


def _execute_probe(state: dict, dax: str, probe_name: str) -> dict:
    res = pbi.execute_python(
        state["workspace_id"], state["dataset_id"],
        [{"name": probe_name, "dax": dax, "purpose": ""}],
        token=state.get("pbi_token"),
    )
    return res[probe_name]


def _adaptive_budget(state: dict, brief: dict, gap_used: int = 0) -> int:
    """Shared per-signal budget. Total = genuine gaps (+1 only for data-quality),
    capped by the configured ceiling. The deterministic gap scan already spent
    ``gap_used`` from that total, so a well-covered signal can correctly receive
    zero additional probes. No brief falls back to the configured ceiling minus
    any gap executions."""
    ceiling = state.get("insight_max_investigation_rounds", 3)
    if not brief:
        return max(0, ceiling - gap_used)
    gaps = len(brief.get("recommended_probes", []))
    safe_facts = any(f.get("safe_to_reuse") for f in brief.get("known_facts", []))
    if gaps == 0 and (brief.get("already_answered") or safe_facts):
        return 0
    extra = 1 if brief.get("scope_type") == "data_quality" else 0
    total = min(ceiling, gaps + extra)
    return max(0, total - gap_used)


def _investigate_signal(state: dict, log: RunLogger, signal: dict,
                        available: dict, brief: dict, bundle: dict, cache: dict,
                        gap_used: int = 0) -> dict:
    md = state["model_metadata"]
    max_probes = _adaptive_budget(state, brief, gap_used)
    max_rows = state.get("insight_probe_max_rows", 20)
    # LLM-turn ceiling is a backstop only; the real budget is run_dax executions.
    # The +6 leaves room for free get_measure_definition lookups between probes.
    max_turns = max_probes * 2 + 6

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("insight_investigator_prompt.md")

    measure_index = {m["name"]: m for m in md.get("measures", [])}
    llm = get_llm(state).bind_tools([run_dax, get_measure_definition, conclude])
    messages = [
        SystemMessage(content=rules + file_io.business_rules_block(state)
                      + "\n\n" + task
                      + f"\n\nYou have a budget of {max_probes} run_dax executions for this signal. "
                      "The INVESTIGATION BRIEF below is a deterministic reuse analysis: treat its "
                      "known_facts and already_answered dimensions as established (do NOT spend a "
                      "probe re-deriving them), aim any probes at recommended_probes, and honor the "
                      "stop_condition. Facts are only reusable when the brief marks them so - anything "
                      "flagged verification_required may inform you but must be re-checked before you "
                      "rely on it to conclude."),
        HumanMessage(content=(
            "AVAILABLE MODEL OBJECTS:\n" + dumps(available)
            + "\n\nSIGNAL TO INVESTIGATE:\n" + dumps(signal)
            + "\n\nINVESTIGATION BRIEF (deterministic reuse/gap plan):\n" + dumps(brief)
            + "\n\nBUNDLED SCAN EVIDENCE (rows already retrieved - reuse before querying):\n"
            + dumps(bundle)
        )),
    ]

    trail = []
    probe_count = 0
    explanation = None

    for _ in range(max_turns):
        resp = llm.invoke(messages)
        messages.append(resp)
        calls = getattr(resp, "tool_calls", None) or []

        if not calls:
            # Plain text without conclude: accept it as the closing statement.
            text = _content_text(resp)
            if text:
                explanation = text
            break

        for call in calls:
            if call["name"] == "conclude":
                explanation = str(call["args"].get("likely_explanation", "")).strip()
                trail.append({"tool": "conclude", "status": "accepted"})
                messages.append(ToolMessage(content="Conclusion recorded.", tool_call_id=call["id"]))
                continue

            if call["name"] == "get_measure_definition":
                names = list(call["args"].get("measure_names", []) or [])
                found, blank, missing = {}, [], []
                for n in names:
                    m = measure_index.get(n)
                    if m is None:
                        missing.append(n)
                    elif m.get("expression"):
                        found[n] = {"table": m.get("table", ""),
                                    "expression": m["expression"]}
                    else:
                        # The executeQueries REST endpoint returns blank
                        # Expression values unless the caller's dataset
                        # permissions expose definitions - be explicit so the
                        # model pivots to raw-column probes instead of
                        # puzzling over empty strings.
                        blank.append(n)
                result = {"definitions": found}
                if blank:
                    result["definition_unavailable"] = {
                        "measures": blank,
                        "note": (
                            "The connection returned a blank formula for these "
                            "measures (definitions are not exposed at this "
                            "permission level). Do not request them again - "
                            "infer the measure's behavior by probing the raw "
                            "columns of its home table instead."
                        ),
                    }
                if missing:
                    result["not_found"] = missing
                # Store the returned formulas in the trail, not just the names -
                # the synthesizer reads the trail and must be able to quote the
                # actual DAX when a finding hinges on a measure's definition.
                trail.append({"tool": "get_measure_definition", "measures": names,
                              "definitions": found, "definition_unavailable": blank,
                              "not_found": missing,
                              "status": "success" if found else
                                        ("unavailable" if blank else "not_found")})
                log.info(f"    definition lookup for signal '{signal['id']}': "
                         f"{len(found)} found, {len(blank)} unavailable, "
                         f"{len(missing)} missing.")
                messages.append(ToolMessage(content=dumps(result), tool_call_id=call["id"]))
                continue

            if call["name"] != "run_dax":
                messages.append(ToolMessage(
                    content=f"Unknown tool: {call['name']}", tool_call_id=call["id"]))
                continue

            dax = str(call["args"].get("dax", ""))
            key = dax_hash(dax)
            cached = cache.get(key)
            if probe_count >= max_probes and not cached:
                result_text = (
                    f"REFUSED: probe budget exhausted ({max_probes} run_dax executions). "
                    "Call conclude now with your likely explanation from the evidence so far."
                )
                trail.append({"tool": "run_dax", "dax": dax, "status": "budget_refused"})
                log.info(f"    probe refused (budget exhausted) for signal '{signal['id']}'.")
            else:
                reasons = validate_one(dax, md)
                reasons += validate_comparable_scope(dax, state)
                if reasons:
                    result_text = "REJECTED before execution: " + "; ".join(reasons)
                    trail.append({"tool": "run_dax", "dax": dax,
                                  "status": "rejected", "reason": "; ".join(reasons)})
                    log.info(f"    probe rejected by validator for signal '{signal['id']}'.")
                else:
                    if cached:
                        item = {"status": cached.get("status", "failed"),
                                "error": cached.get("error", "")}
                        rows = cached.get("rows", [])
                    else:
                        probe_count += 1
                        item = _execute_probe(state, dax, f"{signal['id']}_probe_{probe_count}")
                    if item.get("status") == "success":
                        if not cached:
                            rows = clean_rows(pbi.extract_rows(item.get("result", {})))
                        truncated = len(rows) > max_rows
                        rows = rows[:max_rows]
                        result_text = dumps(rows)
                        if truncated:
                            result_text += f"\n\n(truncated to first {max_rows} rows)"
                        trail.append({"tool": "run_dax", "dax": dax,
                                      "status": "cache_hit" if cached else "success", "rows": rows})
                        if not cached:
                            cache[key] = {"status": "success", "rows": rows, "error": "",
                                          "dax": dax, "source": "investigator"}
                        log.info(f"    {'cache hit' if cached else f'probe {probe_count}/{max_probes}'} for "
                                 f"'{signal['id']}': {len(rows)} rows.")
                    else:
                        result_text = "QUERY FAILED: " + str(item.get("error", "unknown error"))
                        trail.append({"tool": "run_dax", "dax": dax,
                                      "status": "cache_hit_failed" if cached else "failed",
                                      "error": str(item.get("error", ""))})
                        if not cached:
                            cache[key] = {"status": "failed", "rows": [],
                                          "error": str(item.get("error", "")),
                                          "dax": dax, "source": "investigator"}
                        log.info(f"    probe {probe_count}/{max_probes} for "
                                 f"'{signal['id']}': failed.")
            messages.append(ToolMessage(content=result_text, tool_call_id=call["id"]))

        if explanation is not None:
            break

    if explanation is None:
        # Budget/turns exhausted without conclude: force a plain-text closure.
        messages.append(HumanMessage(content=(
            "No more queries are available. State your likely explanation now as "
            "plain text (no tool calls), using hedged contribution/correlation language."
        )))
        resp = llm.invoke(messages)
        explanation = _content_text(resp) or "Investigation inconclusive within the probe budget."
        trail.append({"tool": "forced_closure", "status": "accepted"})

    return {
        "signal": signal,
        "probes": trail,
        "probe_executions": probe_count,
        "concluded": any(t.get("tool") == "conclude" for t in trail),
        "explanation": explanation,
    }


def run(state: dict) -> dict:
    log = RunLogger(state)
    signals = state.get("insight_signals", [])
    log.info(f"Insight branch: investigating {len(signals)} signals (tool-calling agent)...")

    md = state["model_metadata"]
    available = llm_model_context(md)
    scan = state.get("insight_clean_data", {"queries": []})
    briefs = state.get("insight_evidence_briefs", {})
    gap_ev = state.get("insight_gap_evidence", {})
    contracts = state.get("insight_evidence_contracts", {})
    cache = dict(state.get("insight_query_cache", {}) or {})
    rows_by_name = {q.get("query_name"): q.get("rows") for q in scan.get("queries", [])}

    investigations = []
    for signal in signals:
        log.info(f"  investigating signal '{signal['id']}': {signal.get('question', '')}")
        brief = briefs.get(signal.get("id")) or {}
        # Bundle every scan table the brief marks relevant (reuse-before-DAX),
        # falling back to the single evidence_query when there is no brief.
        names = brief.get("supporting_queries") or [signal.get("evidence_query")]
        bundle = {n: {"rows": rows_by_name[n], "provenance": contracts.get(n, {})}
                  for n in names if n in rows_by_name}
        if not bundle and signal.get("evidence_query") in rows_by_name:
            name = signal["evidence_query"]
            bundle = {name: {"rows": rows_by_name[name], "provenance": contracts.get(name, {})}}
        # Fold in whatever the deterministic gap scan already fetched, and note
        # the filled dimensions on the brief so the LLM won't re-probe them.
        gap = gap_ev.get(signal.get("id"), {})
        gap_used = gap.get("gap_probes_used", 0)
        for drill, ev in (gap.get("evidence") or {}).items():
            bundle[f"gapfill::{signal.get('affected_segment')}::{drill}"] = ev
        if gap.get("filled_dimensions"):
            brief = {**brief, "gap_filled_dimensions": gap["filled_dimensions"]}
        try:
            inv = _investigate_signal(state, log, signal, available, brief, bundle, cache, gap_used)
        except Exception as exc:  # noqa: BLE001 - one bad signal shouldn't kill the branch
            log.error(f"  investigation of '{signal['id']}' crashed: {exc}")
            inv = {
                "signal": signal,
                "probes": [],
                "probe_executions": 0,
                "concluded": False,
                "explanation": f"Investigation failed with an internal error: {exc}",
            }
        # Carry reuse + gap-scan accounting onto the trail.
        inv["reuse_summary"] = brief.get("reuse_summary")
        inv["gap_probes_used"] = gap_used
        inv["probe_budget"] = _adaptive_budget(state, brief, gap_used)
        investigations.append(inv)
        log.info(f"  '{signal['id']}': {inv['probe_executions']}/{inv['probe_budget']} investigator probes "
                 f"(+{gap_used} gap-scan), concluded={inv['concluded']}.")

    file_io.write_json(state, "insight_investigations.json", investigations)
    log.info(f"Investigations complete for {len(investigations)} signals.")
    return {"insight_investigations": investigations,
            "insight_query_cache": cache, **log.updates()}
