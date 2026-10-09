"""The recipe investigator: the reasoned tier's model asks, the recipe shelf answers.

    python scripts/replay_recipe_investigator.py

Offline - no auth, no LLM, no network. The model is a script of tool calls;
Power BI is a fake executor.

`src/agents/insight_recipe_investigator.py` is Phase 3 of
`docs/reasoned-tier-implementation-plan.md`. What this file has to prove, in
order of how badly each would hurt if it were wrong:

1. **What the model writes is held to the data.** A conclusion that states a
   cause or quotes a figure no returned row holds is replaced by the
   code-written explanation - which is also what a failed model call, a crash,
   or a run with no model at all publishes.
2. **It cannot overspend.** Queries past the allowance are refused, custom DAX
   has its own cap, and a model that never concludes is closed for it.
3. **Its trail reads like the investigator's.** Same keys, same statuses, the
   gap scan's breakdowns first - so the report, the tiles and the history read
   it unchanged - and the report built from it passes the clarity check.
4. **It is lean and cache-friendly.** No model description in the first
   message, a system prompt identical for every finding, and later turns that
   only append.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402

from scripts.replay_insight_recipes import live_state  # noqa: E402
from src.agents import insight_deterministic, insight_investigator  # noqa: E402
from src.agents import insight_recipe_investigator as rinv  # noqa: E402
from src.agents import insight_recipes as recipes  # noqa: E402
from src.agents import insight_synthesizer  # noqa: E402
from src.tools import llm as llm_module  # noqa: E402
from src.tools import token_usage  # noqa: E402
from src.utils.model_context import llm_model_context  # noqa: E402

OUT = "outputs_replay/recipe_investigator"
INVESTIGATOR_KEYS = {"signal", "probes", "probe_executions", "concluded", "explanation",
                     "reuse_summary", "gap_probes_used", "probe_budget"}
VOCABULARY = {"success", "cache_hit", "cache_hit_failed", "rejected", "budget_refused", "failed",
              "unavailable", "not_found", "accepted"}
#: The first message's ceiling, in characters. The investigated investigator's
#: first message on the same finding is measured alongside it.
FIRST_MESSAGE_CEILING = 30_000

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines()[:14]:
            print(f"         {line}")
    _failures.append(label)


# ------------------------------------------------------------------ the fakes


class ScriptedModel:
    """A get_llm stand-in that plays one script of turns per finding.

    A turn is a list of ``(tool, args)`` calls, a plain string (the model
    answers in text), or an exception to raise. A finding with no script left
    answers in plain text. Structured requests (the Key Insights narration) are
    refused, so those slots keep their grounded drafts.
    """

    def __init__(self, scripts: dict[str, list]) -> None:
        self.scripts = {sid: list(turns) for sid, turns in scripts.items()}
        self.labels: list[str] = []
        self.bound: list[list[str]] = []
        self.invocations: dict[str, list[list]] = {}

    def __call__(self, state=None, structured_schema=None, **_kwargs):
        if structured_schema is not None:
            raise RuntimeError("structured output is not scripted here")
        self.labels.append(token_usage.caller_label(skip=1))
        return self

    def bind_tools(self, tools):
        self.bound.append([tool.__name__ for tool in tools])
        return self

    def invoke(self, messages):
        sid = json.loads(messages[1].content.split("\n", 1)[1])["finding"]["id"]
        self.invocations.setdefault(sid, []).append(list(messages))
        turns = self.scripts.get(sid) or []
        step = turns.pop(0) if turns else "Nothing further to add from the rows returned."
        if isinstance(step, Exception):
            raise step
        if isinstance(step, str):
            return AIMessage(content=step)
        n = len(self.invocations[sid])
        return AIMessage(content="", tool_calls=[
            {"name": name, "args": args, "id": f"{sid}_{n}_{i}", "type": "tool_call"}
            for i, (name, args) in enumerate(step)])


class FakePowerBI:
    """Two store rows for any query; records what was executed."""

    ROWS = [{"MIS_DEEP_DIVE2[store_no]": "CFH018", "[net qty CURRENT]": 900_000.0,
             "[net qty PAST]": 1_110_000.0, "[QTY Growth]": -210_000.0},
            {"MIS_DEEP_DIVE2[store_no]": "CFH014", "[net qty CURRENT]": 700_000.0,
             "[net qty PAST]": 850_000.0, "[QTY Growth]": -150_000.0}]

    def __init__(self) -> None:
        self.executed: list[str] = []

    def __call__(self, workspace_id, dataset_id, queries, token=None):
        out = {}
        for q in queries:
            self.executed.append(q["dax"])
            out[q["name"]] = {"status": "success",
                              "result": {"results": [{"tables": [{"rows": self.ROWS}]}]}}
        return out


def install(model, fake: FakePowerBI | None = None):
    """Route get_llm (everywhere it is held) and Power BI to the fakes."""
    saved = [(rinv, rinv.get_llm), (llm_module, llm_module.get_llm),
             (insight_synthesizer, insight_synthesizer.get_llm),
             (recipes.pbi, recipes.pbi.execute_python)]
    rinv.get_llm = model  # type: ignore[assignment]
    llm_module.get_llm = model  # type: ignore[assignment]
    insight_synthesizer.get_llm = model  # type: ignore[assignment]
    recipes.pbi.execute_python = fake or FakePowerBI()  # type: ignore[assignment]

    def restore():
        for owner, original in saved:
            attr = "execute_python" if owner is recipes.pbi else "get_llm"
            setattr(owner, attr, original)
    return restore


def reasoned_state(**overrides) -> dict:
    state = live_state("outputs_r4_acceptance")
    state.update({"report_ai_tier": "reasoned", "output_folder": OUT,
                  "insight_max_investigation_rounds": 9, "insight_reasoned_probe_allowance": 2,
                  "insight_reasoned_custom_dax_per_finding": 1, "insight_query_cache": {},
                  "report_understanding": {"domain": "Sales / Retail"},
                  "insight_novelty": {"reason": "ok", "selection": "model"}})
    state.update(overrides)
    return state


def investigate(state: dict, model, fake: FakePowerBI | None = None) -> dict:
    restore = install(model, fake)
    try:
        return insight_investigator.run(state)
    finally:
        restore()


def by_id(out: dict) -> dict[str, dict]:
    return {inv["signal"]["id"]: inv for inv in out.get("insight_investigations") or []}


def code_explanation(state: dict, signal: dict) -> str:
    gap = state["insight_gap_evidence"].get(signal["id"], {})
    return insight_deterministic.trail(signal, gap, state["semantic_model_profile"])["explanation"]


FIRST = "confectionery_chocolate_unit_decline"
GOOD = ("The standard drill places the decline in CF-CHOCOLATE, at -548.1K units. Breaking "
        "CF-CHOCOLATE down by store adds that CFH018 holds -210.0K of it and CFH014 -150.0K. "
        "Check the chocolate range in CFH018 against last year.")


# ------------------------------------------------------------- 1. happy path


def test_happy_path() -> None:
    print("\n=== a breakdown, its rows, a conclusion: the investigator's trail ===")
    state = reasoned_state()
    model = ScriptedModel({FIRST: [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"})],
                                   [("conclude", {"likely_explanation": GOOD})]]})
    fake = FakePowerBI()
    out = investigate(state, model, fake)
    inv = by_id(out)[FIRST]
    check("the published explanation is the model's", inv.get("explanation") == GOOD
          and inv.get("explanation_source") == "model", inv.get("conclusion_issues") or inv.get("explanation"))
    check("the trail carries every key the investigator's does", INVESTIGATOR_KEYS <= set(inv), set(inv))
    statuses = {p.get("status") for p in inv["probes"]}
    check("every trail status is from the investigator's vocabulary", statuses <= VOCABULARY, statuses)
    probes = inv["probes"]
    gap_count = len(state["insight_gap_evidence"][FIRST]["evidence"])
    check("the gap scan's breakdowns come first, as the narrated tier publishes them",
          [p.get("origin") for p in probes[:gap_count]] == ["gap_scan"] * gap_count)
    recipe = probes[gap_count]
    check("then the recipe call, marked recipe:breakdown with its rows",
          recipe.get("origin") == "recipe:breakdown" and recipe.get("status") == "success"
          and [r.get("store_no") for r in recipe.get("rows") or []] == ["CFH018", "CFH014"], recipe)
    check("one query spent, inside the budget of 2",
          inv.get("probe_executions") == 1 and inv.get("probe_budget") == 2 and len(fake.executed) == 1,
          (inv.get("probe_executions"), inv.get("probe_budget")))
    check("it concluded, and counts one follow-up answered",
          inv.get("concluded") is True and inv.get("follow_ups_answered") == 1)
    check("the cost is labelled with the module's own name",
          set(model.labels) == {"insight_recipe_investigator"}, model.labels)
    check("the shared query cache carries the new query back to the graph",
          any(v.get("source") == "recipe:breakdown" for v in out["insight_query_cache"].values()))
    others = [inv for sid, inv in by_id(out).items() if sid != FIRST]
    check("a finding the script never covered still gets a trail (its model said nothing new)",
          others and all(o.get("explanation_source") == "model" and o.get("probe_executions") == 0
                         for o in others),
          [(o["signal"]["id"], o.get("explanation_source"), o.get("conclusion_issues")) for o in others])


# ------------------------------------------------------------------ 2. budget


def test_budget() -> None:
    print("\n=== the budget: allowance, custom cap, and closure for a model that never stops ===")
    check("eventful day: the allowance, inside the configured ceiling",
          rinv.budget_for({"insight_max_investigation_rounds": 9, "insight_reasoned_probe_allowance": 2}, 3) == 2)
    check("without escalation it is the plan's min(allowance, rounds - gap-scan probes)",
          rinv.budget_for({"insight_max_investigation_rounds": 4, "insight_reasoned_probe_allowance": 2}, 3) == 1)
    ordinary = {"insight_max_investigation_rounds": 1, "insight_reasoned_probe_allowance": 2,
                "insight_escalation": {"tier": "ordinary", "configured_max_investigation_rounds": 9}}
    check("ordinary adaptive day: lowered to the day's rounds once, not again for the gap scan",
          rinv.budget_for(ordinary, 1) == 1)
    check("the configured ceiling still bounds a finding's total",
          rinv.budget_for({**ordinary, "insight_escalation": {"configured_max_investigation_rounds": 3}}, 3) == 0)
    check("an allowance of zero leaves only the free questions",
          rinv.budget_for({"insight_max_investigation_rounds": 9, "insight_reasoned_probe_allowance": 0}, 0) == 0)

    custom = "EVALUATE ROW(\"x\", [net qty CURRENT])"
    model = ScriptedModel({FIRST: [
        [("custom_dax", {"dax": custom})],
        [("custom_dax", {"dax": "EVALUATE ROW(\"y\", [net revenue CURRENT])"})],
        [("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"})],
        [("breakdown", {"segment": "CF-CHOCOLATE", "by": "division"})],
        [("breakdown", {"segment": "CF-CHOCOLATE", "by": "special product group"})],
        [("conclude", {"likely_explanation": GOOD})]]})
    inv = by_id(investigate(reasoned_state(insight_reasoned_probe_allowance=3), model))[FIRST]
    trail = [p for p in inv["probes"] if p.get("origin") in ("custom_dax", "recipe:breakdown")]
    statuses = [(p.get("origin"), p.get("status")) for p in trail]
    check("custom DAX runs once; the second is refused by its own cap",
          [p.get("status") for p in trail[:2]] == ["success", "budget_refused"]
          and "custom" in str(trail[1].get("reason")), statuses)
    check("the query after the allowance is spent is refused",
          [p.get("status") for p in trail[2:]] == ["success", "success", "budget_refused"], statuses)
    check("exactly the allowance was executed", inv.get("probe_executions") == 3, inv.get("probe_executions"))

    # Allowance 1: one query, then refusals until the turn ceiling (1 * 2 + 6).
    endless = [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"})]] + \
              [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "division"})]] * 7 + \
              ["Forced: CF-CHOCOLATE holds -548.1K units of the decline. Check CFH018 first."]
    model = ScriptedModel({FIRST: endless})
    inv = by_id(investigate(reasoned_state(insight_reasoned_probe_allowance=1), model))[FIRST]
    turns = len(model.invocations[FIRST])
    check("a model that never concludes is stopped at budget * 2 + 6 turns and closed",
          turns == 1 * 2 + 6 + 1 and any(p.get("tool") == "forced_closure" for p in inv["probes"]), turns)
    check("and its forced closing statement is held to the same guard",
          inv.get("explanation_source") == "model" and inv["explanation"].startswith("Forced:"),
          inv.get("conclusion_issues"))

    no_custom = ScriptedModel({FIRST: [[("custom_dax", {"dax": custom})],
                                       [("conclude", {"likely_explanation": GOOD})]]})
    inv = by_id(investigate(reasoned_state(insight_reasoned_custom_dax_per_finding=0), no_custom))[FIRST]
    check("a custom cap of zero removes custom_dax and list_model_objects from the tools",
          all("custom_dax" not in b and "list_model_objects" not in b for b in no_custom.bound),
          no_custom.bound)
    called = next(p for p in inv["probes"] if p.get("tool") == "custom_dax")
    check("and a call to it anyway is refused as not offered, at no cost",
          called.get("status") == "rejected" and inv.get("probe_executions") == 0, called)


# ------------------------------------------------------------------- 3. guard


def test_guard() -> None:
    print("\n=== the guard: a cause or an invented figure keeps the code-written explanation ===")
    cases = {
        "a cause word": GOOD.replace("Breaking", "This happened because breaking"),
        "a figure no row holds": GOOD.replace("-150.0K", "-999.9K"),
        "too long": " ".join([GOOD] * 4),
    }
    for label, text in cases.items():
        state = reasoned_state()
        # The rewrite repeats the fault, so the guard rejects it a second time.
        model = ScriptedModel({FIRST: [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"})],
                                       [("conclude", {"likely_explanation": text})], text]})
        inv = by_id(investigate(state, model))[FIRST]
        check(f"{label}: after one failed rewrite the code-written explanation is published",
              inv.get("explanation") == code_explanation(state, inv["signal"])
              and inv.get("explanation_source") == "code" and inv.get("conclusion_issues"),
              inv.get("conclusion_issues"))
        check(f"{label}: both rejected drafts are kept for review",
              inv.get("rejected_conclusions") == [text, text], inv.get("rejected_conclusions"))
        check(f"{label}: the follow-up rows it fetched are still on the trail",
              any(p.get("origin") == "recipe:breakdown" and p.get("rows") for p in inv["probes"]))

    long = " ".join([GOOD] * 4)
    model = ScriptedModel({FIRST: [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"})],
                                   [("conclude", {"likely_explanation": long})], GOOD]})
    inv = by_id(investigate(reasoned_state(), model))[FIRST]
    repair = model.invocations[FIRST][-1][-1].content
    check("a rejected conclusion gets one rewrite, told the guard's own reason",
          len(model.invocations[FIRST]) == 3 and "words; at most 120" in repair, repair)
    check("a rewrite that passes is published, and the rejected draft is kept",
          inv.get("explanation") == GOOD and inv.get("explanation_source") == "model"
          and inv.get("rejected_conclusions") == [long] and not inv.get("conclusion_issues"),
          inv.get("conclusion_issues"))
    check("the rewrite is on the trail",
          any(p.get("tool") == "conclusion_repair" and p.get("status") == "accepted" for p in inv["probes"]))
    supported = [548_078.6, 210_000.0]
    check("the guard accepts display rounding of a returned figure",
          not rinv.conclusion_issues("It fell by 548.1K, with 210.0K in one store.", supported))
    check("and rejects a percentage nobody returned",
          rinv.conclusion_issues("It fell by 12.3%.", supported) != [])


# ------------------------------------------------- 4. failure and isolation


def test_failure_and_isolation() -> None:
    print("\n=== failures: the code-written trail stands in, one finding at a time ===")
    state = reasoned_state()

    def unavailable(*_a, **_k):
        raise RuntimeError("Azure OpenAI provider selected but these env vars are not set")

    out = investigate(state, unavailable)
    invs = by_id(out)
    check("with no model at all, every finding keeps the code-written explanation",
          invs and all(i.get("explanation_source") == "code"
                       and i.get("explanation") == code_explanation(state, i["signal"]) for i in invs.values()))
    check("and the failure is in the run's errors", any("crashed" in e or "unavailable" in e
                                                       for e in out.get("errors") or []), out.get("errors"))

    signals = state["insight_signals"]
    second = signals[1]["id"]
    model = ScriptedModel({FIRST: [TimeoutError("the model timed out")],
                           second: [[("conclude", {"likely_explanation":
                                                   "The standard drill already covers this; nothing further "
                                                   "was asked. Check the largest store first."})]]})
    invs = by_id(investigate(reasoned_state(), model))
    check("a model failure on one finding keeps that finding on the code-written trail",
          invs[FIRST].get("explanation_source") == "code" and "TimeoutError" in str(invs[FIRST].get("error")))
    check("and the next finding is still investigated by the model",
          invs[second].get("explanation_source") == "model", invs[second].get("conclusion_issues"))

    original = recipes.run

    def crash_first(name, args, state, signal, *a, **k):
        if signal.get("id") == FIRST:
            raise ValueError("a recipe bug")
        return original(name, args, state, signal, *a, **k)

    recipes.run = crash_first  # type: ignore[assignment]
    try:
        model = ScriptedModel({FIRST: [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"})]],
                               second: [[("conclude", {"likely_explanation":
                                                       "Nothing further was asked. Check the largest store first."})]]})
        out = investigate(reasoned_state(), model)
    finally:
        recipes.run = original  # type: ignore[assignment]
    invs = by_id(out)
    check("a crash inside one finding's investigation does not stop the others",
          len(invs) == len(signals) and invs[FIRST].get("explanation_source") == "code"
          and invs[second].get("explanation_source") == "model", list(invs))


# ------------------------------------------------------------ 5. lean context


def test_lean_context() -> None:
    print("\n=== the context: lean, and a prefix the provider can cache ===")
    state = reasoned_state()
    model = ScriptedModel({FIRST: [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"})],
                                   [("list_model_objects", {"table": "MIS_DEEP_DIVE2"})],
                                   [("conclude", {"likely_explanation": GOOD})]]})
    investigate(state, model)
    turns = model.invocations[FIRST]
    first = turns[0][1].content
    md = state["model_metadata"]
    others = [t["name"] for t in md["tables"] if t["name"] not in first][:3]
    check("the first message carries no model description",
          "AVAILABLE MODEL OBJECTS" not in first and len(others) == 3, others)
    investigated_size = len(json.dumps(llm_model_context(md), default=str))
    check(f"and stays under {FIRST_MESSAGE_CEILING:,} characters "
          f"({len(first):,}; the investigated investigator sends a {investigated_size:,}-character "
          f"model description before any evidence)",
          len(first) < FIRST_MESSAGE_CEILING and len(first) < investigated_size, len(first))
    payload = json.loads(first.split("\n", 1)[1])
    check("it holds the finding, the standard drill, the brief, the menu, the rows and the budget",
          set(payload) == {"finding", "standard_drill", "brief", "menu", "evidence", "budget"}, set(payload))
    check("the finding's facts, never its story keys",
          "story_key" not in payload["finding"] and "covered_story_keys" not in payload["finding"])
    scan_rows = [t for t in payload["evidence"] if not str(t["source"]).startswith("gap_scan:")]
    check("from the scan tables, only the rows that name this finding's segment",
          scan_rows and all(set(recipes._labels(r).values()) & {"CF-CONFECTIONERY"}
                            for t in scan_rows for r in t["rows"]), scan_rows)
    check("every later turn only appends to what was sent before",
          all(turns[i][:len(turns[i - 1])] == turns[i - 1] for i in range(1, len(turns))))
    listing = next((m for m in turns[2] if getattr(m, "tool_call_id", "").endswith("_2_0")), None)
    check("the model's objects reach it only when it asks, for one table",
          listing is not None and "MIS_DEEP_DIVE2" in listing.content and '"columns"' in listing.content)

    many = ScriptedModel({})
    investigate(reasoned_state(), many)
    systems = {inv[0][0].content for inv in many.invocations.values()}
    check(f"the system prompt is identical for all {len(many.invocations)} findings",
          len(many.invocations) > 1 and len(systems) == 1 and isinstance(
              next(iter(many.invocations.values()))[0][0], SystemMessage))
    check("and each finding's opening message is its own",
          len({inv[0][1].content for inv in many.invocations.values()}) == len(many.invocations)
          and all(isinstance(inv[0][1], HumanMessage) for inv in many.invocations.values()))


# ------------------------------------------------------------ 6. end to end


def test_report_end_to_end() -> None:
    print("\n=== end to end: the narrated report from these trails passes the clarity check ===")
    state = reasoned_state()
    model = ScriptedModel({FIRST: [[("breakdown", {"segment": "CF-CHOCOLATE", "by": "store"}),
                                    ("compare_to_peers", {"level": "store"}),
                                    ("trend", {"segment": "CF-BAKERY"})],
                                   [("conclude", {"likely_explanation": GOOD})]]})
    restore = install(model)
    try:
        state.update(insight_investigator.run(dict(state)))
        state.update(insight_synthesizer.run(dict(state)))
    finally:
        restore()
    report = str(state.get("insight_report") or "")
    check("the report is written and its clarity check is clean",
          any("clarity check clean" in line for line in state.get("logs") or []),
          [line for line in state.get("logs") or [] if "clarity" in line])
    check("the five sections, in order",
          re.findall(r"(?m)^# (.+)$", report) == ["Key Insights", "Data Quality Watch-outs",
                                                   "Evidence Trail", "Confidence & Caveats",
                                                   "Suggested Follow-ups"])
    check("the Evidence Trail names each follow-up for what it was",
          "Follow-up breakdown of CF-CHOCOLATE by store: 2 row(s), complete." in report
          and "Follow-up comparison with every store:" in report
          and "Follow-up trend of CF-BAKERY: not run (" in report, report)
    check("and carries the model's conclusion", GOOD in report)
    check("the caveat counts the follow-up questions the data answered",
          "An AI model asked 2 follow-up question(s) of the data beyond the standard breakdowns" in report,
          report[report.find("# Confidence"):report.find("# Suggested")])
    check("no recipe line is labelled a gap-scan breakdown",
          report.count("Gap-scan breakdown") == sum(
              len(state["insight_gap_evidence"].get(s["id"], {}).get("evidence") or {})
              for s in state["insight_signals"]))


def main() -> int:
    print("=" * 72)
    print("insight recipe investigator: the reasoned tier's investigation")
    print("=" * 72)
    (PROJECT_ROOT / OUT).mkdir(parents=True, exist_ok=True)
    test_happy_path()
    test_budget()
    test_guard()
    test_failure_and_isolation()
    test_lean_context()
    test_report_end_to_end()

    print("\n" + "=" * 72)
    if _failures:
        print(f"RECIPE INVESTIGATOR FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
