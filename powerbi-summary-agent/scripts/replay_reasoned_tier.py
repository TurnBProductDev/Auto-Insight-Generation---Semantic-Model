"""The reasoned tier: a model chooses the findings, code does everything else.

    python scripts/replay_reasoned_tier.py

Offline - no auth, no LLM, no network.

`reasoned` is the fourth value of `report_ai_tier` (`src/tools/ai_tier.py`,
`docs/reasoned-tier-implementation-plan.md`). It is narrated plus the decisions
in ``ai_tier.REASONING_STEPS``: the signal detector's model selection (Phase 1)
and the recipe investigation (Phase 3, `scripts/replay_recipe_investigator.py`
tests its loop). What this file has to prove, in order of how badly each would
hurt if it were wrong:

1. **Nothing else moved.** The three existing tiers ask the model at exactly
   the nodes they did before; the node-call matrix below pins all four.
2. **Reasoned decides only where it is allowed to.** Understanding and summary
   DAX planning and generation are run with a `get_llm` that raises, so a
   missed gate is a failure here; the investigation asks the model and falls
   back to the code-written trail when it cannot.
3. **Its selection is the investigated one.** The same model picks, bound,
   re-scored and capped exactly as on the investigated tier.
4. **A failed selection call costs nothing.** It falls back to the narrated
   tier's rule-based selection, never to zero findings, and the report says
   what actually happened.
5. **The Web App sees the same shapes.** `kpi_insights.json`,
   `report_summary.json` and both history entries carry exactly the keys and
   types of a narrated run (the S2 seam).
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.replay_ai_tier import (  # noqa: E402
    PROFILE, LLMCalled, _reply, _slot_state, _SlotModel, candidate, gap_evidence,
    torch_signal,
)
from src import config_schema  # noqa: E402
from src.agents import (  # noqa: E402
    dax_generator, dax_planner, dax_validator, fresh_summary_generator,
    insight_investigator, insight_recipe_investigator, insight_signal_detector,
    insight_synthesizer, report_understanding,
)
from src.agents.insight_signal_detector import Signal, SignalList  # noqa: E402
from src.tools import ai_tier, api_payloads, insight_history, summary_history  # noqa: E402
from src.tools import llm as llm_module  # noqa: E402

OUT = "outputs_replay/reasoned_tier"
WHEN = datetime(2026, 10, 7, 7, 0, tzinfo=timezone.utc)

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    _failures.append(label)


# Every module that holds its own reference to get_llm, plus src.tools.llm for
# the writers that import it inside a function (insight_deterministic).
_GATED = (report_understanding, dax_planner, dax_generator, insight_signal_detector,
          insight_investigator, insight_recipe_investigator, insight_synthesizer, api_payloads,
          fresh_summary_generator, llm_module)


@contextmanager
def model(factory):
    """Install ``factory`` as get_llm everywhere a node can reach it."""
    saved = [(module, module.get_llm) for module in _GATED]
    for module, _ in saved:
        module.get_llm = factory  # type: ignore[attr-defined]
    try:
        yield factory
    finally:
        for module, original in saved:
            module.get_llm = original  # type: ignore[attr-defined]


class Counter:
    """Counts model requests and refuses each one."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_a, **_k):
        self.calls += 1
        raise LLMCalled("a language model was requested")


class Selector:
    """A get_llm stand-in for the signal detector: answers with fixed picks."""

    def __init__(self, picks: list[dict] | None = None, fail: bool = False) -> None:
        self.picks = picks or []
        self.fail = fail
        self.schemas: list[str] = []
        self.messages: list = []

    def __call__(self, state=None, structured_schema=None, **_kwargs):
        self.schemas.append(getattr(structured_schema, "__name__", str(structured_schema)))
        selector = self

        class _Model:
            def invoke(self, messages):
                selector.messages.append(messages)
                if selector.fail:
                    raise TimeoutError("the selection call timed out")
                return SignalList(signals=[Signal(**pick) for pick in selector.picks])

        return _Model()


def pick(cid: str, segment: str, related: list[str] | None = None, kind: str = "business") -> dict:
    return {"candidate_id": cid, "related_candidate_ids": related, "id": f"{cid}_story",
            "kind": kind, "description": f"The model's own sentence about {segment}.",
            "affected_segment": segment, "impact_value": 1.0, "impact_share": 1.0,
            "question": f"What is driving {segment}?", "evidence_query": "meta_movers"}


def rich_candidate(cid: str, segment: str, score: float) -> dict:
    """A candidate carrying every fact the report and the cards read off a signal."""
    torch = torch_signal()
    return {
        "id": cid, "kind": "business", "type": "change_contribution",
        "analysis_type": "change_contribution", "metric": torch["metric"],
        "metric_family": "revenue", "bundle_id": "SALES::revenue", "segment": segment,
        "score": score, "detail": f"{segment} revenue increased by 226612.35.",
        "table": "meta_movers", "level": "high", "story_key": f"key-{cid}",
        "story_fields": {"segment": segment, "metric": torch["metric"],
                         "analysis_type": "change_contribution", "direction": "up"},
        "direction": "up", "current": torch["current"], "prior": torch["prior"],
        "impact_value": torch["impact_value"], "impact_share": torch["impact_share"],
        "rate_volume": torch["decomposition"],
    }


def selection_state(tier: str, eligible: dict, **extra) -> dict:
    state = {"output_folder": OUT, "insight_memory_enabled": True,
             "insight_max_new_per_run": 3, "insight_max_dq_signals": 1,
             "insight_clean_data": {"successful": 1, "queries": []},
             "insight_eligible_candidates": eligible, "insight_novelty": {"reason": "ok"},
             "report_understanding": {"domain": "Sales / Retail"}, **extra}
    if tier != "investigated":
        state["report_ai_tier"] = tier
    return state


def dq_candidate(cid: str, score: float, segment: str) -> dict:
    # The model path copies a candidate's own kind onto the signal, so a
    # data-quality candidate must say so itself, as the stat detector's do.
    return {**candidate(cid, score, segment), "kind": "data_quality"}


def mixed_eligible() -> dict:
    return {
        "business_candidates": [candidate("c1", 4.0, "ST1"), candidate("c2", 40.0, "ST2"),
                                candidate("c3", 12.0, "ST3"), candidate("c4", 1.0, "ST4")],
        "data_quality_candidates": [dq_candidate("d1", 90.0, "reconciliation"),
                                    dq_candidate("d2", 80.0, "totals")],
    }


# ------------------------------------------------------------------ 1. the dial


def test_the_dial() -> None:
    print("\n=== the dial: reasoned is a fourth tier, and nothing else changed ===")
    check("reasoned is accepted", ai_tier.tier({"report_ai_tier": "reasoned"}) == "reasoned")
    check("read through config too, as a standalone runner hands it",
          ai_tier.tier({"config": {"report_ai_tier": " Reasoned "}}) == "reasoned")
    check("an unknown value still resolves to investigated",
          ai_tier.tier({"report_ai_tier": "reasonned"}) == "investigated")
    check("no key at all is still investigated", ai_tier.tier({}) == "investigated")

    key = config_schema.get("report_ai_tier")
    check("the catalogue offers exactly ai_tier.TIERS, in the same order",
          key is not None and tuple(key.choices or ()) == ai_tier.TIERS, key and key.choices)
    check("its code default is still investigated", key is not None and key.default == "investigated")
    labels = dict((key.choice_labels or ()) if key else ())
    check("reasoned has its plain label",
          labels.get("reasoned") == "AI reasons, code queries and checks", labels)
    check("the help says the AI never writes numbers and writes DAX only when no recipe fits",
          key is not None and "never writes a number" in key.help
          and "only when none of the tested ones fits" in key.help, key and key.help)
    check("a config setting reasoned passes the catalogue's type check",
          config_schema.type_errors({"report_ai_tier": "reasoned"}) == [])
    check("a misspelt tier is still refused by it",
          bool(config_schema.type_errors({"report_ai_tier": "reasonned"})))
    # Until the Phase 8 rollout, reasoned runs only as a shadow: a config that
    # opts in must publish nothing and keep its memory off production's blobs.
    opted = [(path, json.loads(path.read_text(encoding="utf-8")))
             for path in (PROJECT_ROOT / "config").rglob("config.json")
             if '"reasoned"' in path.read_text(encoding="utf-8")]
    leaking = [str(path.relative_to(PROJECT_ROOT)) for path, cfg in opted
               if cfg.get("ai_content_publish_enabled") is not False
               or cfg.get("azure_blob_upload") is not False
               or str(cfg.get("insight_memory_storage", "local")).lower() != "local"
               or str(cfg.get("summary_memory_storage", "local")).lower() != "local"]
    check("every config that opts in is a shadow: no publishing, no upload, local memory",
          not leaking, leaking)

    reasoned = {"report_ai_tier": "reasoned"}
    check("reasoned reasons at the two named steps",
          ai_tier.reasons(reasoned, "select_findings") and ai_tier.reasons(reasoned, "investigate"))
    check("and nowhere else",
          not ai_tier.reasons(reasoned, "plan_queries") and not ai_tier.reasons(reasoned, ""))
    check("investigated reasons at every step",
          all(ai_tier.reasons({}, step) for step in ("select_findings", "investigate", "plan_queries")))
    check("narrated and deterministic reason nowhere",
          not any(ai_tier.reasons({"report_ai_tier": t}, step)
                  for t in ("narrated", "deterministic") for step in ai_tier.REASONING_STEPS))
    check("reasoned does not count as investigating, so every other node takes the narrated route",
          not ai_tier.investigates(reasoned))
    check("reasoned writes the narrated slots",
          ai_tier.narrated(reasoned) and ai_tier.prose_allowed(reasoned, False)
          and ai_tier.authoring_allowed({**reasoned, "summary_llm_authoring_enabled": False}))
    check("narrated_code_slots hands a reasoned writer back to code as it does a narrated one",
          ai_tier.code_slot({**reasoned, "narrated_code_slots": ["summary"]}, "summary")
          and not ai_tier.code_slot({**reasoned, "narrated_code_slots": ["summary"]}, "dashboard"))
    check("deterministic is never narrated, investigated never narrated",
          not ai_tier.narrated({"report_ai_tier": "deterministic"}) and not ai_tier.narrated({}))


# ------------------------------------------- 2. reasoned plans nothing


def test_reasoned_plans_nothing() -> None:
    print("\n=== reasoned: no model understands or plans; the investigation asks one ===")
    base = {"report_ai_tier": "reasoned", "output_folder": OUT, "semantic_model_profile": PROFILE,
            "config": {"report_domain": "sales"},
            "model_metadata": {"tables": [], "columns": [], "measures": []}}
    signal = torch_signal()
    outputs: dict = {}
    with model(Counter()) as counter:
        for label, call in (
            ("report_understanding", lambda: report_understanding.run(dict(base))),
            ("dax_planner", lambda: dax_planner.run(dict(base, report_understanding={"domain": "Sales / Retail"}))),
            ("dax_generator", lambda: dax_generator.run(dict(base, dax_plan={"queries": []}))),
        ):
            before = counter.calls
            try:
                outputs[label] = call()
                ok = counter.calls == before
            except LLMCalled:
                ok = False
            check(f"{label} makes no model call on the reasoned tier", ok)
        before = counter.calls
        outputs["insight_investigator"] = insight_investigator.run(dict(
            base, insight_signals=[signal], insight_clean_data={"queries": []},
            insight_evidence_briefs={}, insight_gap_evidence={signal["id"]: gap_evidence()},
            insight_evidence_contracts={}, insight_query_cache={}))
        check("the investigation asks the model (the recipe investigator)", counter.calls > before)

    understanding = (outputs.get("report_understanding") or {}).get("report_understanding") or {}
    check("the understanding is the profile's, as on narrated",
          "report_ai_tier=reasoned" in str(understanding.get("notes")), understanding.get("notes"))
    check("the summary plans no DAX", (outputs.get("dax_planner") or {}).get("dax_plan") == {"queries": []})
    validated = dax_validator.run(dict(base, generated_dax_queries=[]))
    check("validate_dax takes the narrated route to the baseline summary, logged as no error",
          validated.get("summary_fatal") is True
          and not any("ERROR" in line for line in validated.get("logs") or []), validated.get("logs"))
    inv = ((outputs.get("insight_investigator") or {}).get("insight_investigations") or [{}])[0]
    check("with the model refused, it keeps the gap scan's code-written trail and spends nothing",
          inv.get("explanation_source") == "code" and inv.get("probe_executions") == 0
          and inv.get("probes") and all(p.get("origin") == "gap_scan" for p in inv.get("probes") or [])
          and inv.get("explanation") == insight_deterministic_trail(signal)["explanation"], inv)


# ------------------------------------------- 3. the selection is the investigated one


def test_reasoned_selection_matches_investigated() -> None:
    print("\n=== reasoned selection: the investigated tier's, bound, re-scored and capped ===")
    picks = [pick("c3", "ST3", related=["c4"]), pick("c1", "ST1"), pick("ghost", "ST9"),
             pick("d1", "reconciliation", kind="data_quality"),
             pick("d2", "totals", kind="data_quality")]

    def run(tier: str) -> tuple[dict, Selector]:
        selector = Selector(picks)
        with model(selector):
            out = insight_signal_detector.run(selection_state(tier, mixed_eligible()))
        return out, selector

    investigated, inv_model = run("investigated")
    reasoned, rsn_model = run("reasoned")
    check("reasoned asks the model for a SignalList, once", rsn_model.schemas == ["SignalList"],
          rsn_model.schemas)
    check("with exactly the messages the investigated tier sends",
          rsn_model.messages == inv_model.messages)
    check("its signals are exactly the investigated tier's",
          reasoned.get("insight_signals") == investigated.get("insight_signals"))

    signals = reasoned.get("insight_signals") or []
    ids = [s.get("candidate_id") for s in signals]
    check("a pick naming no eligible candidate is dropped (exact-id binding)", "ghost" not in ids, ids)
    check("picks are re-scored from their candidates and capped, DQ sub-cap held",
          ids == ["d1", "c3", "c1"], ids)
    merged = next((s for s in signals if s.get("candidate_id") == "c3"), {})
    check("a merge marks every covered story seen",
          merged.get("covered_story_keys") == ["key-c3", "key-c4"], merged.get("covered_story_keys"))
    check("the candidate's computed facts replace the model's figures",
          merged.get("impact_value") == 12_000.0 and merged.get("score") == 12.0, merged)
    novelty = reasoned.get("insight_novelty") or {}
    check("the run records that the model selected", novelty.get("selection") == "model", novelty)
    check("the investigated tier's run summary is unchanged (no selection key)",
          "selection" not in (investigated.get("insight_novelty") or {}))


def test_merged_finding_keeps_its_own_figures_name() -> None:
    print("\n=== reasoned: a merged finding is named after the candidate whose figures it carries ===")
    # The 2026-10-08 live shape: the model merged several candidates into one
    # story labelled "overall", listing all of them, bound to one candidate.
    merged = {**pick("c2", "overall", related=["c3", "c1"]),
              "segment_members": ["ST2", "ST3", "ST1"]}

    def run(tier: str) -> dict:
        with model(Selector([merged])):
            out = insight_signal_detector.run(selection_state(tier, mixed_eligible()))
        return out

    reasoned, investigated = run("reasoned"), run("investigated")
    r = next(s for s in reasoned["insight_signals"] if s.get("candidate_id") == "c2")
    i = next(s for s in investigated["insight_signals"] if s.get("candidate_id") == "c2")
    check("reasoned names it after its own candidate, so name and figures agree",
          r.get("affected_segment") == "ST2" and r.get("segment_members") is None
          and r.get("impact_value") == 40_000.0, {k: r.get(k) for k in ("affected_segment", "segment_members", "impact_value")})
    check("the merge still marks every related story as told",
          r.get("covered_story_keys") == ["key-c2", "key-c3", "key-c1"], r.get("covered_story_keys"))
    check("the run log says a signal was renamed",
          any("renamed to the candidate" in line for line in reasoned.get("logs") or []))
    check("investigated keeps the model's label and list (its behaviour is unchanged)",
          i.get("affected_segment") == "overall" and i.get("segment_members") == ["ST2", "ST3", "ST1"],
          {k: i.get(k) for k in ("affected_segment", "segment_members")})


# ------------------------------------------- 4. a failed call falls back to the rules


def test_failed_selection_falls_back_to_rules() -> None:
    print("\n=== reasoned selection: a failed call selects as narrated, never nothing ===")
    with model(Counter()):
        narrated = insight_signal_detector.run(selection_state("narrated", mixed_eligible()))
    broken = Selector(fail=True)
    with model(broken):
        reasoned = insight_signal_detector.run(selection_state("reasoned", mixed_eligible()))
    check("the model was asked", broken.schemas == ["SignalList"], broken.schemas)
    check("the fallback selection is exactly the narrated tier's",
          reasoned.get("insight_signals") == narrated.get("insight_signals")
          and len(reasoned.get("insight_signals") or []) == 3, reasoned.get("insight_signals"))
    novelty = reasoned.get("insight_novelty") or {}
    check("the run records the rules selected, and why",
          novelty.get("selection") == "rules" and "TimeoutError" in str(novelty.get("selection_error")),
          novelty)
    check("the failure is logged as an error, so the run log shows it",
          any("rule-based selection used instead" in e for e in reasoned.get("errors") or []),
          reasoned.get("errors"))

    with model(Selector(fail=True)):
        try:
            insight_signal_detector.run(selection_state("investigated", mixed_eligible()))
            raised = False
        except TimeoutError:
            raised = True
    check("the investigated tier still raises on the same failure (behaviour unchanged)", raised)


def _insight_lane(tier: str, selector) -> dict:
    """Detector, investigator and synthesizer of one tier over the same candidates."""
    eligible = {"business_candidates": [rich_candidate("c1", "CFH021 HAND TORCH", 6.5),
                                        rich_candidate("c2", "CFH017 LANTERN", 3.0)],
                "data_quality_candidates": []}
    state = selection_state(tier, eligible, semantic_model_profile=PROFILE,
                            model_metadata={"tables": [], "columns": [], "measures": []},
                            dataset_id="replay-dataset", config={"report_domain": "sales"})
    state["insight_max_new_per_run"] = 2
    with model(selector):
        state.update(insight_signal_detector.run(dict(state)))
        signals = state["insight_signals"]
        state.update(insight_clean_data={"queries": []}, insight_evidence_briefs={},
                     insight_evidence_contracts={}, insight_query_cache={},
                     insight_gap_evidence={s["id"]: gap_evidence() for s in signals})
        state.update(insight_investigator.run(dict(state)))
        state.update(insight_synthesizer.run(dict(state)))
    return state


class LaneModel:
    """Selection picks for the detector, a refusal for every other writer."""

    def __init__(self, picks: list[dict], fail_selection: bool = False) -> None:
        self.selector = Selector(picks, fail=fail_selection)
        self.other_calls = 0

    def __call__(self, state=None, structured_schema=None, **kwargs):
        if getattr(structured_schema, "__name__", "") == "SignalList":
            return self.selector(state, structured_schema, **kwargs)
        self.other_calls += 1
        raise LLMCalled("only the selection is answered here")


def test_reasoned_report_says_what_happened() -> None:
    print("\n=== reasoned insight report: same checks, a caveat that says who chose ===")
    picks = [pick("c1", "CFH021 HAND TORCH"), pick("c2", "CFH017 LANTERN")]
    chosen = _insight_lane("reasoned", LaneModel(picks))
    report = str(chosen.get("insight_report") or "")
    check("the report is written and its clarity check is clean",
          any("clarity check clean" in line for line in chosen.get("logs") or []), chosen.get("logs"))
    check("the five sections, in order",
          re.findall(r"(?m)^# (.+)$", report) == ["Key Insights", "Data Quality Watch-outs",
                                                   "Evidence Trail", "Confidence & Caveats",
                                                   "Suggested Follow-ups"])
    check("the caveat says an AI model chose the findings",
          "An AI model chose these findings" in report, report)
    check("and does not claim fixed rules chose them",
          "chosen, ranked and checked by fixed rules" not in report
          and "without an AI model" not in report)
    check("with the Key Insights narration refused, it says the wording is code's",
          "The wording was written by fixed rules." in report)
    check("the run log names the reasoned tier",
          any("report_ai_tier=reasoned" in line for line in chosen.get("logs") or []))

    fallback = _insight_lane("reasoned", LaneModel(picks, fail_selection=True))
    report = str(fallback.get("insight_report") or "")
    check("after a failed selection the caveat describes a rules run",
          "An AI model chose these findings" not in report and "without an AI model" in report, report)


# ------------------------------------------------------- 5. the node-call matrix


#: Which nodes ask a model, per tier. The first three columns are what the
#: tiers did before the reasoned tier existed; changing one is a regression.
EXPECTED_CALLS = {
    "report_understanding":    {"investigated": True, "reasoned": False, "narrated": False, "deterministic": False},
    "dax_planner":             {"investigated": True, "reasoned": False, "narrated": False, "deterministic": False},
    "dax_generator":           {"investigated": True, "reasoned": False, "narrated": False, "deterministic": False},
    "insight_signal_detector": {"investigated": True, "reasoned": True, "narrated": False, "deterministic": False},
    "insight_investigator":    {"investigated": True, "reasoned": True, "narrated": False, "deterministic": False},
    "insight_synthesizer":     {"investigated": True, "reasoned": True, "narrated": True, "deterministic": False},
    "kpi_cards":               {"investigated": True, "reasoned": True, "narrated": True, "deterministic": False},
}


def _node_calls(tier: str) -> dict[str, bool]:
    base = {"output_folder": OUT, "semantic_model_profile": PROFILE,
            "config": {"report_domain": "sales"},
            "model_metadata": {"tables": [], "columns": [], "measures": []}}
    if tier != "investigated":
        base["report_ai_tier"] = tier
    signal = torch_signal()
    trail = insight_deterministic_trail(signal)
    calls = {
        "report_understanding": lambda: report_understanding.run(dict(base)),
        "dax_planner": lambda: dax_planner.run(dict(base, report_understanding={"domain": "Sales / Retail"})),
        "dax_generator": lambda: dax_generator.run(dict(base, dax_plan={"queries": [
            {"name": "q1", "purpose": "revenue by store", "intent": "revenue by store"}]})),
        "insight_signal_detector": lambda: insight_signal_detector.run(selection_state(
            tier, {"business_candidates": [candidate("c1", 5, "ST1")], "data_quality_candidates": []})),
        "insight_investigator": lambda: insight_investigator.run(dict(
            base, insight_signals=[signal], insight_clean_data={"queries": []},
            insight_evidence_briefs={}, insight_gap_evidence={signal["id"]: gap_evidence()},
            insight_evidence_contracts={}, insight_query_cache={})),
        "insight_synthesizer": lambda: insight_synthesizer.run(dict(
            base, insight_signals=[signal], insight_investigations=[trail],
            insight_clean_data={}, insight_novelty={"reason": "ok"},
            report_understanding={"domain": "Sales / Retail"})),
        "kpi_cards": lambda: api_payloads.generate_kpi_insights_payload(
            [signal], dict(base), generated_at=WHEN),
    }
    seen: dict[str, bool] = {}
    for node, call in calls.items():
        counter = Counter()
        with model(counter):
            try:
                call()
            except Exception:  # noqa: BLE001 - some writers wrap the refusal; the count decides
                pass
        seen[node] = counter.calls > 0
    return seen


def insight_deterministic_trail(signal: dict) -> dict:
    from src.agents import insight_deterministic
    return insight_deterministic.trail(signal, gap_evidence(), PROFILE)


def test_node_call_matrix() -> None:
    print("\n=== which nodes ask a model, per tier (existing tiers pinned) ===")
    for tier in ai_tier.TIERS:
        seen = _node_calls(tier)
        expected = {node: row[tier] for node, row in EXPECTED_CALLS.items()}
        wrong = {node: seen[node] for node in expected if seen.get(node) != expected[node]}
        check(f"{tier}: model calls at exactly {sorted(n for n, v in expected.items() if v) or 'no node'}",
              not wrong, f"differs at {wrong}")


# ------------------------------------------------------- 6. the payload shapes


def shape(value):
    """Keys and types, recursively; a list is the set of its items' shapes."""
    if isinstance(value, dict):
        return {key: shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return sorted({json.dumps(shape(item), sort_keys=True) for item in value})
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def _differences(a, b, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out = [f"{path}.{k}: only in narrated" for k in a.keys() - b.keys()]
        out += [f"{path}.{k}: only in reasoned" for k in b.keys() - a.keys()]
        for key in a.keys() & b.keys():
            out += _differences(a[key], b[key], f"{path}.{key}")
        return out
    return [] if a == b else [f"{path or '<root>'}: {a} vs {b}"]


def test_payload_shapes_match_narrated() -> None:
    print("\n=== S2 seam guard: the published payloads have the narrated shapes ===")
    # The model picks what the rules would have picked, so the only difference
    # between the two runs is the tier's own path.
    picks = [pick("c1", "CFH021 HAND TORCH"), pick("c2", "CFH017 LANTERN")]
    lanes = {"narrated": _insight_lane("narrated", LaneModel([])),
             "reasoned": _insight_lane("reasoned", LaneModel(picks))}
    check("both runs published the same number of findings",
          len(lanes["narrated"]["insight_signals"]) == len(lanes["reasoned"]["insight_signals"]) == 2)

    cards, insights = {}, {}
    for tier, state in lanes.items():
        # Card wording from code on both tiers, so neither needs a model; the
        # card assembly that follows has no tier branch.
        card_state = {**state, "narrated_code_slots": ["kpi_cards"]}
        cards[tier] = api_payloads.generate_kpi_insights_payload(
            state["insight_signals"], card_state, generated_at=WHEN)
        insights[tier] = insight_history.build_entry(
            state, report_md=state["insight_report"], generated_at=WHEN, run_id="replay")
    diff = _differences(shape(cards["narrated"]), shape(cards["reasoned"]))
    check("kpi_insights.json: same keys and types", bool(cards["reasoned"]) and not diff, diff)
    diff = _differences(shape(insights["narrated"]), shape(insights["reasoned"]))
    check("insight history entry: same keys and types",
          insights["reasoned"] is not None and insights["reasoned"]["insightCount"] == 2 and not diff,
          diff or insights["reasoned"])

    summaries, entries = {}, {}
    for tier in ("narrated", "reasoned"):
        state = {**_slot_state(tier), "output_folder": OUT}
        with model(_SlotModel()):
            state.update(fresh_summary_generator.run(dict(state)))
        summaries[tier] = api_payloads.generate_fresh_report_summary_payload(state, generated_at=WHEN)
        entries[tier] = summary_history.build_entry(state, generated_at=WHEN, run_id="replay")
    check("the reasoned summary is model-worded through the narrated slots",
          summaries["reasoned"] == summaries["narrated"], _differences(summaries["narrated"], summaries["reasoned"]))
    diff = _differences(shape(summaries["narrated"]), shape(summaries["reasoned"]))
    check("report_summary.json: same keys and types", not diff, diff)
    diff = _differences(shape(entries["narrated"]), shape(entries["reasoned"]))
    check("summary history entry: same keys and types", entries["reasoned"] is not None and not diff, diff)


def main() -> int:
    print("=" * 72)
    print("report_ai_tier: reasoned")
    print("=" * 72)
    (PROJECT_ROOT / OUT).mkdir(parents=True, exist_ok=True)
    test_the_dial()
    test_reasoned_plans_nothing()
    test_reasoned_selection_matches_investigated()
    test_merged_finding_keeps_its_own_figures_name()
    test_failed_selection_falls_back_to_rules()
    test_reasoned_report_says_what_happened()
    test_node_call_matrix()
    test_payload_shapes_match_narrated()

    print("\n" + "=" * 72)
    if _failures:
        print(f"REASONED TIER FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
