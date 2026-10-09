"""Insight branch - Recipe Investigator (reasoned tier, tool-calling).

The investigated tier's investigator hands a model the whole model description
and lets it write DAX. On the measured 2026-09-08 run it then asked nothing:
its budget formula leaves zero probes once the gap scan has filled the gaps,
so what it bought was prose. This is the reasoned tier's investigator
(`docs/reasoned-tier-implementation-plan.md`, Phase 3). The model decides what
to ask; `insight_recipes` decides how, and checks it.

Per finding, mirroring `insight_investigator._investigate_signal`:

* **Fallback first.** `insight_deterministic.trail` - the gap-scan rows and a
  code-written explanation, exactly what the narrated tier publishes - is
  computed before any model call. A model failure, a crash, or a conclusion
  that fails the guard below leaves the finding on it.
* **Lean, fixed context.** The first message carries the finding's own facts,
  the brief, the recipe menu in business names, and only the rows returned for
  this finding - no model description. The system prompt is identical for
  every finding and later turns only append tool results, so the provider's
  prompt cache applies to everything already sent.
* **Budget.** ``min(insight_reasoned_probe_allowance, configured rounds -
  gap_probes_used, the day's escalated rounds)``: the allowance is room beyond
  the standard drill, the configured ceiling still bounds a finding's total,
  and escalation lowers it on an ordinary day - once. Custom DAX counts towards
  it and is capped again by ``insight_reasoned_custom_dax_per_finding``; zero
  removes that tool. Free recipes and cache hits cost nothing. The turn ceiling
  is ``budget * 2 + 6`` with a forced closure, as in the investigator.
* **Guarded conclusion.** No cause words, no figure that is not in a row this
  finding returned, within a length. One that fails keeps the code-written
  explanation and records why.

The output is the investigator's trail dict, with the gap-scan probes first
(so every reader that takes the first breakdown reads what the narrated tier
reads) and each recipe call after them, marked ``origin: recipe:<name>`` or
``custom_dax``. Token usage is labelled with this module's name, so its cost
shows separately and ``node_model_overrides`` can route it on its own.
"""

from __future__ import annotations

import re
from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from ..tools import file_io
from ..tools.llm import get_llm
from ..tools.summary_validation import _UNSUPPORTED_CAUSAL, parse_numbers
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger
from . import insight_deterministic
from . import insight_recipes as recipes
from .insight_investigator import _content_text
from .insight_synthesizer import _supported_numbers

#: Conclusion limits. The prompt asks for less, so a draft has room to pass.
MAX_CONCLUSION_WORDS = 120
MAX_CONCLUSION_SENTENCES = 6

#: The finding facts the model is shown - computed values, never story keys.
_FINDING_FACTS = ("id", "kind", "description", "affected_segment", "segment_members",
                  "metric", "metric_family", "current", "prior", "impact_value", "impact_share",
                  "decomposition", "question", "level", "period_label", "direction")

_ANSWERED = ("success", "cache_hit")


# ------------------------------------------------------------------- the tools


class breakdown(BaseModel):
    """Split a segment by another level: current, prior and change for each member.

    One query, or none if the same question was already asked.
    """

    segment: str = Field(description="The finding's own segment, or a member listed in members_seen.")
    by: str = Field(description="A level from the menu, by its business name.")


class compare_to_peers(BaseModel):
    """Every member of a level, with the finding's rank among them.

    Free when the scan already holds that level complete, otherwise one query.
    """

    level: str = Field(description="A level from the menu, by its business name.")


class trend(BaseModel):
    """A segment's current, prior and change over the validated time axis. One query."""

    segment: str = Field(description="The finding's own segment, or a member listed in members_seen.")


class split_units_vs_price(BaseModel):
    """Free. Split a segment's revenue change into units sold and revenue per unit.

    Works on a row you have already been shown for that segment.
    """

    segment: str = Field(description="The finding's own segment, or a member listed in members_seen.")


class measure_formula(BaseModel):
    """Free. The formula behind one or more measures."""

    names: List[str] = Field(description="Exact measure names.")


class custom_dax(BaseModel):
    """Last resort: one DAX query of your own, when no recipe can ask the question.

    Validated and held to the comparable stores like every recipe; counts
    against your budget and has its own cap. Call list_model_objects first.
    """

    dax: str = Field(description="One complete DAX query with exactly one EVALUATE.")


class list_model_objects(BaseModel):
    """Free. The exact tables, columns and measures custom_dax may use.

    Give a table name for its columns and measures; leave it empty for the table list.
    """

    table: Optional[str] = Field(default=None, description="A table name, or empty for the list of tables.")


class conclude(BaseModel):
    """Finish with what the evidence shows about this finding.

    Two to five sentences. Quote only figures from rows you were shown or
    returned; describe contribution, never cause; say what your questions added
    beyond the standard drill; end with the one check a person should run next.
    """

    likely_explanation: str = Field(description="Two to five sentences, at most 110 words.")


# ---------------------------------------------------------------- the budget


def budget_for(state: dict, gap_used: int) -> int:
    """Recipe queries one finding may spend beyond the standard drill."""
    allowance = max(0, int(state.get("insight_reasoned_probe_allowance", 2)))
    rounds = int(state.get("insight_max_investigation_rounds", 3))
    escalation = state.get("insight_escalation") or {}
    configured = int(escalation.get("configured_max_investigation_rounds", rounds))
    return max(0, min(allowance, configured - int(gap_used or 0), rounds))


# ------------------------------------------------------------------ the guard


def conclusion_issues(text: str, supported: list[float]) -> list[str]:
    """Why a model's conclusion may not replace the code-written explanation."""
    text = str(text or "").strip()
    if not text:
        return ["empty"]
    issues = []
    if _UNSUPPORTED_CAUSAL.search(text):
        issues.append("states a cause the data cannot show")
    words = len(re.findall(r"\b\w[\w'-]*\b", text))
    if words > MAX_CONCLUSION_WORDS:
        issues.append(f"{words} words; at most {MAX_CONCLUSION_WORDS}")
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sentences) > MAX_CONCLUSION_SENTENCES:
        issues.append(f"{len(sentences)} sentences; at most {MAX_CONCLUSION_SENTENCES}")
    for value, tolerance, token in parse_numbers(text):
        if not any(abs(value - known) <= max(tolerance, abs(known) * 0.0005) for known in supported):
            issues.append(f"figure {token!r} is not in any row returned for this finding")
    return issues


# ------------------------------------------------------------- the context


def _shown_evidence(state: dict, signal: dict) -> list[dict]:
    """This finding's rows only: its gap-scan breakdowns whole, and from the
    scan tables just the rows that name its segment."""
    own = recipes._own_names(signal)
    shown = []
    for table in recipes.finding_evidence(state, signal):
        rows = table["rows"]
        if table["within"] is None:
            rows = [r for r in rows if set(recipes._labels(r).values()) & own]
        if rows:
            shown.append({**table, "rows": rows})
    return shown


def _first_message(signal: dict, brief: dict, fallback: dict, menu: dict,
                   evidence: list[dict], budget: int, custom: int) -> str:
    facts = [{k: f.get(k) for k in ("fact", "metric", "impact_value", "impact_share") if f.get(k) is not None}
             for f in brief.get("known_facts") or []]
    payload = {
        "finding": {k: signal.get(k) for k in _FINDING_FACTS if signal.get(k) not in (None, [], "")},
        "standard_drill": fallback.get("explanation"),
        "brief": {"scope_type": brief.get("scope_type"), "known_facts": facts,
                  "open_questions": brief.get("unanswered_questions") or [],
                  "stop_condition": brief.get("stop_condition")},
        "menu": menu,
        "evidence": evidence,
        "budget": {"queries": budget, "custom_dax": custom},
    }
    return "INVESTIGATE THIS FINDING:\n" + dumps(payload)


def _model_objects(metadata: dict, table: Optional[str]) -> dict:
    tables = sorted({t.get("name") for t in metadata.get("tables", []) if t.get("name")})
    if not table or table not in tables:
        return {"tables": tables, **({"not_found": table} if table else {})}
    return {"table": table,
            "columns": [{"column": c.get("column"), "data_type": c.get("data_type")}
                        for c in metadata.get("columns", []) if c.get("table") == table],
            "measures": [m.get("name") for m in metadata.get("measures", []) if m.get("table") == table]}


def _tool_reply(entry: dict, budget: recipes.Budget) -> str:
    """What the model reads back: the answer, or why there is none, and what is left."""
    status = entry.get("status")
    if status == "rejected":
        text = "REFUSED: " + str(entry.get("reason"))
    elif status == "budget_refused":
        text = "REFUSED: " + str(entry.get("reason")) + ". Call conclude with what you have."
    elif status in ("failed", "cache_hit_failed"):
        text = "QUERY FAILED: " + str(entry.get("error"))
    else:
        text = dumps({k: entry[k] for k in ("rows", "row_count", "completeness", "position", "splits",
                                             "source", "within", "definitions", "definition_unavailable",
                                             "not_found") if k in entry})
    return text + f"\n(queries left: {budget.queries})"


# ------------------------------------------------------------ one finding


def _investigate(state: dict, log: RunLogger, signal: dict, fallback: dict, cache: dict,
                 budget_n: int, custom_cap: int) -> dict:
    sid = signal.get("id")
    brief = (state.get("insight_evidence_briefs") or {}).get(sid) or {}
    custom = min(custom_cap, budget_n)
    budget = recipes.Budget(queries=budget_n, custom_dax=custom)
    evidence = _shown_evidence(state, signal)
    menu = recipes.menu(state, signal, evidence, allow_custom_dax=custom > 0)

    tools = [breakdown, compare_to_peers, trend, split_units_vs_price, measure_formula, conclude]
    if custom > 0:
        tools += [custom_dax, list_model_objects]
    offered = {tool.__name__ for tool in tools}
    llm = get_llm(state).bind_tools(tools)
    messages = [
        SystemMessage(content=file_io.read_prompt("_global_rules.md") + file_io.business_rules_block(state)
                      + "\n\n" + file_io.read_prompt("insight_recipe_investigator_prompt.md")),
        HumanMessage(content=_first_message(signal, brief, fallback, menu, evidence, budget_n, custom)),
    ]

    trail: list[dict] = []
    explanation, error = None, None
    for _ in range(budget_n * 2 + 6):
        try:
            resp = llm.invoke(messages)
        except Exception as exc:  # noqa: BLE001 - the code-written trail stands in
            error = f"{type(exc).__name__}: {exc}"
            break
        messages.append(resp)
        calls = getattr(resp, "tool_calls", None) or []
        if not calls:
            explanation = _content_text(resp) or None
            break
        for call in calls:
            name, args = call["name"], call.get("args") or {}
            if name == "conclude":
                explanation = str(args.get("likely_explanation") or "").strip()
                trail.append({"tool": "conclude", "status": "accepted"})
                reply = "Conclusion recorded."
            elif name == "list_model_objects" and name in offered:
                trail.append({"tool": "list_model_objects", "table": args.get("table"),
                              "status": "success", "cost": 0})
                reply = dumps(_model_objects(state.get("model_metadata") or {}, args.get("table")))
            elif name in recipes.RECIPES and name in offered:
                entry = recipes.run(name, args, state, signal, cache, evidence=evidence, budget=budget)
                trail.append(entry)
                if entry.get("status") in _ANSWERED and entry.get("rows"):
                    # Members it returns become askable: the no-fishing rule
                    # follows what the model has actually been shown.
                    evidence.append({"source": entry["origin"], "within": args.get("segment"),
                                     "rows": entry["rows"]})
                log.info(f"    '{sid}': {name}({', '.join(f'{k}={v}' for k, v in args.items() if k != 'dax')}) "
                         f"-> {entry.get('status')}")
                reply = _tool_reply(entry, budget)
            else:
                trail.append({"tool": name, "status": "rejected", "reason": "not offered", "cost": 0})
                reply = f"REFUSED: {name} is not offered here."
            messages.append(ToolMessage(content=reply, tool_call_id=call["id"]))
        if explanation is not None:
            break

    if explanation is None and error is None:
        messages.append(HumanMessage(content=(
            "No more questions are available. State your conclusion now as plain text, "
            "following the rules for conclude.")))
        try:
            explanation = _content_text(llm.invoke(messages)) or None
            trail.append({"tool": "forced_closure", "status": "accepted"})
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"

    answered = [e for e in trail if e.get("status") in _ANSWERED and e.get("origin")]
    data_answers = [e for e in answered if e.get("rows") or e.get("splits")]
    supported = _supported_numbers({
        "finding": {k: signal.get(k) for k in _FINDING_FACTS},
        "known_facts": brief.get("known_facts") or [],
        "evidence": [t["rows"] for t in evidence],
        "answers": answered,
    })
    issues = conclusion_issues(explanation, supported) if explanation is not None else []
    rejected: list[str] = []
    if issues and error is None:
        # One rewrite with the guard's own reasons, as every narrated writer
        # gets. The guard is unchanged: the rewrite passes it or is discarded.
        rejected.append(explanation)
        messages.append(HumanMessage(content=(
            "Your conclusion was not accepted: " + "; ".join(issues) + ". Rewrite it once, as plain "
            "text with no tool calls, following the rules for conclude. If it fails again, the "
            "code-written explanation is published instead.")))
        try:
            retry = _content_text(llm.invoke(messages)) or None
        except Exception:  # noqa: BLE001 - the code-written explanation stands in
            retry = None
        retry_issues = conclusion_issues(retry, supported) if retry else ["no rewrite returned"]
        trail.append({"tool": "conclusion_repair", "status": "rejected" if retry_issues else "accepted",
                      "issues": issues})
        if retry and not retry_issues:
            explanation, issues = retry, []
        else:
            if retry:
                rejected.append(retry)
            issues = retry_issues if retry else issues
    accepted = explanation is not None and not issues
    probes = list(fallback.get("probes") or []) + trail
    inv = {
        "signal": signal,
        "probes": probes,
        "probe_executions": sum(int(e.get("cost") or 0) for e in trail),
        # Whichever explanation is published decides: the model's conclude, or
        # the code-written trail's own measure of a complete breakdown.
        "concluded": (any(e.get("tool") == "conclude" for e in trail) if accepted
                      else bool(fallback.get("concluded"))),
        "explanation": explanation if accepted else fallback.get("explanation"),
        "explanation_source": "model" if accepted else "code",
        "complete_breakdowns": sum(1 for p in probes if p.get("tool") == "run_dax"
                                   and p.get("status") in _ANSWERED and "rows" in p
                                   and p.get("completeness") == "complete"),
        # Questions the data answered beyond the standard drill (rows or a split).
        "follow_ups_answered": len(data_answers),
    }
    if issues:
        inv["conclusion_issues"] = issues
    if rejected:
        # Kept for review: what the model wrote that the guard turned away.
        inv["rejected_conclusions"] = rejected
    if error:
        inv["error"] = error
    return inv


def run(state: dict) -> dict:
    log = RunLogger(state)
    signals = state.get("insight_signals", [])
    log.info(f"Insight branch: investigating {len(signals)} signals with the recipe shelf "
             f"(report_ai_tier=reasoned)...")
    profile = state.get("semantic_model_profile") or {}
    gap_ev = state.get("insight_gap_evidence", {}) or {}
    briefs = state.get("insight_evidence_briefs", {}) or {}
    cache = dict(state.get("insight_query_cache", {}) or {})
    custom_cap = max(0, int(state.get("insight_reasoned_custom_dax_per_finding", 1)))

    investigations = []
    for signal in signals:
        sid = signal.get("id")
        gap = gap_ev.get(sid, {}) or {}
        gap_used = int(gap.get("gap_probes_used", 0) or 0)
        budget_n = budget_for(state, gap_used)
        fallback = insight_deterministic.trail(signal, gap, profile)
        fallback.pop("deterministic", None)
        try:
            inv = _investigate(state, log, signal, fallback, cache, budget_n, custom_cap)
        except Exception as exc:  # noqa: BLE001 - one bad finding must not cost the others
            log.error(f"  recipe investigation of '{sid}' crashed ({type(exc).__name__}: {exc}); "
                      f"code-written trail kept.")
            inv = {**fallback, "explanation_source": "code", "follow_ups_answered": 0,
                   "error": f"{type(exc).__name__}: {exc}"}
        else:
            if inv.get("error"):
                log.error(f"  '{sid}': model unavailable ({inv['error']}); code-written explanation kept.")
            elif inv.get("conclusion_issues"):
                log.info(f"  '{sid}': conclusion failed the guard ({'; '.join(inv['conclusion_issues'])}); "
                         f"code-written explanation kept.")
        inv["reuse_summary"] = (briefs.get(sid) or {}).get("reuse_summary")
        inv["gap_probes_used"] = gap_used
        inv["probe_budget"] = budget_n
        investigations.append(inv)
        log.info(f"  '{sid}': {inv['probe_executions']}/{budget_n} recipe queries "
                 f"(+{gap_used} gap-scan), {inv.get('follow_ups_answered', 0)} follow-up(s) answered, "
                 f"explanation by {inv['explanation_source']}.")

    file_io.write_json(state, "insight_investigations.json", investigations)
    return {"insight_investigations": investigations, "insight_query_cache": cache, **log.updates()}
