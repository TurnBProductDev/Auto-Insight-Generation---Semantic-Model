"""The deterministic tier: a Sales YoY run that calls no language model at all.

    python scripts/replay_ai_tier.py

Offline - no auth, no LLM, no network.

`report_ai_tier` (`src/tools/ai_tier.py`) is the brief's "Dial B" for the
LangGraph report: how much thinking a run buys. `investigated` is the report as
it has always run; `deterministic` routes every stage that used a model onto a
code-owned path. What this file has to prove, in order of how badly each would
hurt if it were wrong:

1. **The default is untouched.** A config without the key still reaches the
   model at every stage. A cost switch that quietly stripped the AI out of a
   client's report would be discovered by the client, not by us.
2. **Deterministic means no call, not a cheaper call.** Every gated node is run
   with `get_llm` replaced by something that raises, so a single missed gate is
   a hard failure here rather than a line on next month's invoice.
3. **The code-written words meet the bar the LLM's words are held to.** The
   insight report passes the synthesizer's own manager-facing clarity check,
   parses with the history parser, and the KPI cards validate - because the
   deterministic tier is only honest if what it publishes is still correct.
4. **A trail quotes only what the gap scan returned.** No figure in an
   explanation that is not in a returned row.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import config_schema  # noqa: E402
from src.agents import (  # noqa: E402
    dax_generator, dax_planner, dax_validator, insight_deterministic,
    insight_investigator, insight_signal_detector, insight_synthesizer,
    report_understanding,
)
from src.agents.insight_stat_detector import _rate_volume_split  # noqa: E402
from src.state import SummaryAgentState  # noqa: E402
from src.tools import ai_tier, api_payloads  # noqa: E402
from src.tools.insight_tiles import insights_from_markdown  # noqa: E402

OUT = "outputs_replay/ai_tier"

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


class LLMCalled(RuntimeError):
    """Raised by the stand-in for get_llm, so reaching the model is visible."""


def _no_llm(*_a, **_k):
    raise LLMCalled("a language model was requested")


_GATED = (report_understanding, dax_planner, dax_generator, insight_signal_detector,
          insight_investigator, insight_synthesizer, api_payloads)


def forbid_llm() -> None:
    for module in _GATED:
        module.get_llm = _no_llm  # type: ignore[attr-defined]


# ------------------------------------------------------------------- fixtures


PROFILE = {
    "fact_table": {"name": "SALES"},
    "primary_value_bundle": {
        "id": "SALES::revenue", "family": "revenue",
        "measures": {"current": "net revenue CURRENT", "prior": "net revenue PAST",
                     "change": "revenue Growth"},
    },
    "volume_driver_bundles": [{
        "id": "SALES::quantity", "family": "quantity",
        "measures": {"current": "net qty CURRENT", "prior": "net qty PAST",
                     "change": "QTY Growth"},
        "evidence": [{"phase": "prior", "name": "net qty PAST",
                      "column_refs": [{"column": "units_ly"}]}],
    }],
    "value_bundles": [{
        "id": "SALES::revenue", "family": "revenue",
        "measures": {"prior": "net revenue PAST"},
        "evidence": [{"phase": "prior", "name": "net revenue PAST",
                      "column_refs": [{"column": "revenue_ly"}]}],
    }],
    "dimensions": [{"reference": "'SALES'[product_group_name]"}],
    "time_dimensions": [{"reference": "'SALES'[max_date]"}],
}


def torch_signal() -> dict:
    """The same arithmetic `replay_plain_language_output.py` pins, reused."""
    row = {"net revenue CURRENT": 775_727.74, "net revenue PAST": 549_115.39,
           "net qty CURRENT": 13_154.0, "net qty PAST": 9_727.0,
           "net bills CURRENT": 10_264.0, "net bills PAST": 7_581.0}
    revenue = {"current": "net revenue CURRENT", "prior": "net revenue PAST",
               "change": "revenue Growth"}
    quantity = _rate_volume_split(row, revenue, {
        "current": "net qty CURRENT", "prior": "net qty PAST", "change": "QTY Growth"})
    bills = _rate_volume_split(row, revenue, {
        "current": "net bills CURRENT", "prior": "net bills PAST", "change": "bills growth"})
    return {
        "id": "cfh021_hand_torch_revenue_growth", "candidate_id": "c1", "kind": "business",
        "description": "CFH021 HAND TORCH revenue increased by 226612.35.",
        "affected_segment": "CFH021 HAND TORCH", "metric_family": "revenue",
        "bundle_id": "SALES::revenue", "metric": "revenue Growth",
        "current": 775_727.74, "prior": 549_115.39,
        "impact_value": 226_612.35, "impact_share": 6.5317,
        "decomposition": [quantity, bills], "score": 6.5317,
    }


GAP_ROWS = [
    {"product_group_name": "HAND TORCH", "revenue Growth": 180_400.0, "QTY Growth": 2_900.0},
    {"product_group_name": "HEAD TORCH", "revenue Growth": -41_250.5, "QTY Growth": -310.0},
    {"product_group_name": "LANTERNS", "revenue Growth": 87_463.0, "QTY Growth": 837.0},
    {"product_group_name": "BATTERIES", "revenue Growth": 12.0, "QTY Growth": 1.0},
]


def gap_evidence() -> dict:
    return {
        "gap_probes_used": 2,
        "evidence": {
            "product_group_name": {"completeness": "complete", "row_count": 4,
                                   "rows": GAP_ROWS, "dax": "EVALUATE ROW(\"x\", 1)"},
            "store_no": {"completeness": "partial", "row_count": 1,
                         "rows": [{"store_no": "CFH021", "revenue Growth": 226_612.35}]},
        },
    }


def candidate(cid: str, score: float, segment: str) -> dict:
    return {"id": cid, "kind": "business", "type": "change_contribution",
            "analysis_type": "change_contribution", "metric": "revenue Growth",
            "segment": segment, "score": score, "detail": f"{segment} revenue moved.",
            "table": "meta_movers", "level": "high", "story_key": f"key-{cid}",
            "impact_value": score * 1000.0, "impact_share": score}


# ------------------------------------------------------------------ 1. the dial


def test_the_dial() -> None:
    print("\n=== the dial resolves to today's behaviour unless told otherwise ===")
    check("no key at all is investigated", ai_tier.tier({}) == "investigated")
    check("None state is investigated", ai_tier.tier(None) == "investigated")  # type: ignore[arg-type]
    check("an explicit state value is honoured",
          ai_tier.tier({"report_ai_tier": "deterministic"}) == "deterministic")
    check("case and whitespace do not matter",
          ai_tier.tier({"report_ai_tier": "  Deterministic "}) == "deterministic")
    check("an unknown value falls back to investigated, never to no AI",
          ai_tier.tier({"report_ai_tier": "determinstic"}) == "investigated")

    # The report_id lesson: a key LangGraph does not carry reads differently
    # after the graph. config survives, so the tier must read through it too.
    post_graph = {"config": {"report_ai_tier": "deterministic"}}
    check("the tier is read through config when state has lost it",
          ai_tier.deterministic(post_graph))

    check("authoring is allowed by default", ai_tier.authoring_allowed({}))
    check("the old authoring switch still turns authoring off on its own",
          not ai_tier.authoring_allowed({"summary_llm_authoring_enabled": False}))
    check("the deterministic tier forces authoring off even when the switch says on",
          not ai_tier.authoring_allowed({"summary_llm_authoring_enabled": True,
                                         "report_ai_tier": "deterministic"}))

    key = config_schema.get("report_ai_tier")
    check("report_ai_tier is catalogued", key is not None)
    if key is not None:
        check("its code default is today's behaviour", key.default == "investigated", key.default)
        check("it offers exactly the two tiers that exist",
              tuple(key.choices or ()) == ai_tier.TIERS, key.choices)
    # Declared, or LangGraph drops it before any node sees it.
    check("report_ai_tier is a declared state channel",
          "report_ai_tier" in SummaryAgentState.__annotations__)


# ----------------------------------------------- 2. the default still reaches it


def test_default_tier_still_reaches_the_model() -> None:
    print("\n=== the investigated tier still asks the model, unchanged ===")
    forbid_llm()

    reached = []
    for label, call in (
        ("dax_planner", lambda: dax_planner.run({
            "output_folder": OUT, "model_metadata": {"tables": [], "columns": [], "measures": []},
            "report_understanding": {"domain": "Sales / Retail"}})),
        ("insight_signal_detector", lambda: insight_signal_detector.run({
            "output_folder": OUT, "insight_memory_enabled": True,
            "insight_clean_data": {"successful": 1, "queries": []},
            "insight_eligible_candidates": {"business_candidates": [candidate("c1", 5, "ST1")],
                                            "data_quality_candidates": []},
            "insight_max_new_per_run": 2})),
    ):
        try:
            call()
            reached.append((label, False))
        except LLMCalled:
            reached.append((label, True))
    for label, hit in reached:
        check(f"{label} requests the model when no tier is set", hit)


# --------------------------------------------- 3. no model on the deterministic tier


def test_planning_calls_no_model() -> None:
    print("\n=== planning: no DAX, no model, and the summary route it relies on ===")
    forbid_llm()
    base = {"report_ai_tier": "deterministic", "output_folder": OUT,
            "semantic_model_profile": PROFILE, "config": {"report_domain": "sales"},
            "model_metadata": {"tables": [], "columns": [], "measures": []}}

    try:
        understood = report_understanding.run(dict(base))
        ok = True
    except LLMCalled:
        understood, ok = {}, False
    check("report_understanding builds its answer without a model", ok)
    u = understood.get("report_understanding") or {}
    check("the domain matches what the LLM has returned for sales",
          u.get("domain") == "Sales / Retail", u.get("domain"))
    check("the measures are the profile's own bundle measures",
          "revenue Growth" in (u.get("important_measures") or [])
          and "QTY Growth" in (u.get("important_measures") or []), u.get("important_measures"))
    check("a date axis in the profile makes a time summary possible",
          u.get("time_summary_possible") is True)
    check("the answer says no model was asked", "without a model call" in str(u.get("notes")))

    state = dict(base, report_understanding=u)
    try:
        plan = dax_planner.run(dict(state))
        planned = plan.get("dax_plan")
    except LLMCalled:
        planned = None
    check("dax_planner plans nothing and calls no model", planned == {"queries": []}, planned)

    try:
        generated = dax_generator.run(dict(state, dax_plan={"queries": []}))
        queries = generated.get("generated_dax_queries")
    except LLMCalled:
        queries = None
    check("dax_generator generates nothing and calls no model", queries == [], queries)

    validated = dax_validator.run(dict(state, generated_dax_queries=[]))
    check("validate_dax raises summary_fatal, which routes to the baseline summary",
          validated.get("summary_fatal") is True)
    check("and does not log it as an error, because nothing failed",
          not any("ERROR" in line for line in validated.get("logs") or []), validated.get("logs"))

    investigated = dax_validator.run({"output_folder": OUT, "generated_dax_queries": [],
                                      "model_metadata": {"tables": [], "columns": [], "measures": []}})
    check("on the investigated tier an empty plan is still reported as an error",
          any("ERROR" in line for line in investigated.get("logs") or []))


def test_signal_selection_calls_no_model() -> None:
    print("\n=== signal selection: ranked by score, capped, no model ===")
    forbid_llm()
    dq = candidate("d1", 90.0, "reconciliation")
    state = {
        "report_ai_tier": "deterministic", "output_folder": OUT,
        "insight_memory_enabled": True, "insight_max_new_per_run": 3, "insight_max_dq_signals": 1,
        "insight_clean_data": {"successful": 1, "queries": []},
        "insight_eligible_candidates": {
            "business_candidates": [candidate("c1", 4.0, "ST1"), candidate("c2", 40.0, "ST2"),
                                    candidate("c3", 12.0, "ST3"), candidate("c4", 1.0, "ST4")],
            "data_quality_candidates": [dq, candidate("d2", 80.0, "totals")],
        },
        "insight_novelty": {"reason": "ok"},
    }
    try:
        out = insight_signal_detector.run(state)
        ok = True
    except LLMCalled:
        out, ok = {}, False
    check("the signal detector selects without a model", ok)
    signals = out.get("insight_signals") or []
    ids = [s.get("candidate_id") for s in signals]
    check("the cap holds", len(signals) == 3, ids)
    check("data-quality findings keep their kind from the list they came from",
          sum(1 for s in signals if s.get("kind") == "data_quality") == 1, [s.get("kind") for s in signals])
    check("ranking is by materiality score, largest first, within the DQ sub-cap",
          ids == ["d1", "c2", "c3"], ids)
    check("every signal is bound to its candidate for memory",
          all(s.get("covered_story_keys") for s in signals))
    check("no signal is left marked as an LLM-omission backfill",
          not any("injected" in s for s in signals))


def test_investigation_calls_no_model() -> None:
    print("\n=== investigation: a trail from the gap scan, no tool loop ===")
    forbid_llm()
    signal = torch_signal()
    state = {
        "report_ai_tier": "deterministic", "output_folder": OUT,
        "insight_signals": [signal], "semantic_model_profile": PROFILE,
        "model_metadata": {"tables": [], "columns": [], "measures": []},
        "insight_clean_data": {"queries": []}, "insight_evidence_briefs": {},
        "insight_gap_evidence": {signal["id"]: gap_evidence()},
        "insight_evidence_contracts": {}, "insight_query_cache": {},
    }
    try:
        out = insight_investigator.run(state)
        ok = True
    except LLMCalled:
        out, ok = {}, False
    check("the investigator writes its trail without a model", ok)
    inv = (out.get("insight_investigations") or [{}])[0]
    probes = inv.get("probes") or []
    check("each gap-scan breakdown becomes a probe", len(probes) == 2, probes)
    check("in the investigator's own run_dax shape, so every reader still finds rows",
          all(p.get("tool") == "run_dax" and isinstance(p.get("rows"), list) for p in probes))
    check("and marked as coming from the gap scan, not an investigator probe",
          all(p.get("origin") == "gap_scan" for p in probes)
          and inv.get("probe_executions") == 0)
    check("a complete breakdown lets the trail conclude", inv.get("concluded") is True)

    explanation = str(inv.get("explanation") or "")
    check("the explanation names the largest movers in order",
          explanation.find("HAND TORCH") < explanation.find("LANTERNS") < explanation.find("HEAD TORCH")
          and "BATTERIES" not in explanation, explanation)
    check("it uses the change measure of the signal's own family",
          "revenue Growth" in explanation, explanation)
    check("an incomplete breakdown is labelled as such", "incomplete" in explanation, explanation)

    # Every figure must come from a returned row; the display rounds, so compare
    # each quoted figure against the rounded display of some real value.
    real = [abs(v) for r in GAP_ROWS + [{"x": 226_612.35}] for v in r.values()
            if isinstance(v, (int, float))]
    shown = {insight_synthesizer._display_value(v) for v in real}
    quoted = re.findall(r"[+-]([\d.,]+[KMB]?)\)", explanation)
    check("every figure quoted in the explanation is a returned row's value",
          quoted and all(q in shown for q in quoted), (quoted, sorted(s for s in shown if s)))

    family = insight_deterministic.change_measure({"metric_family": "quantity"}, PROFILE)
    check("a quantity finding reads the quantity change measure", family == "QTY Growth", family)
    legacy = insight_deterministic.change_measure({"metric": "sales::quantity"}, PROFILE)
    check("the family is recovered from the metric id when not declared",
          legacy == "QTY Growth", legacy)


def test_report_calls_no_model_and_passes_clarity() -> None:
    print("\n=== the insight report: fixed rules, same sections, same bar ===")
    forbid_llm()
    signal = torch_signal()
    trail = insight_deterministic.trail(signal, gap_evidence(), PROFILE)
    state = {
        "report_ai_tier": "deterministic", "output_folder": OUT,
        "insight_signals": [signal], "insight_investigations": [trail],
        "semantic_model_profile": PROFILE, "insight_clean_data": {},
        "insight_novelty": {"reason": "ok"},
        "report_understanding": {"domain": "Sales / Retail"},
        "insight_recent_week_verdict": {"enabled": False, "reason": "batch_load_date"},
    }
    try:
        out = insight_synthesizer.run(state)
        ok = True
    except LLMCalled:
        out, ok = {}, False
    check("the synthesizer writes the report without a model", ok)
    report = str(out.get("insight_report") or "")

    headings = re.findall(r"(?m)^# (.+)$", report)
    check("the five required sections, in the prompt's order",
          headings == ["Key Insights", "Data Quality Watch-outs", "Evidence Trail",
                       "Confidence & Caveats", "Suggested Follow-ups"], headings)

    brief = insight_synthesizer._manager_fact_brief(signal, PROFILE)
    numbers = insight_synthesizer._supported_numbers({
        "manager_fact_briefs": [brief], "signals": [signal], "investigations": [trail]})
    issues = insight_synthesizer._clarity_issues(report, 1, [brief], numbers)
    check("the manager-facing clarity check passes with no issues", not issues, issues)
    check("the run log says the clarity check was clean",
          any("clarity check clean" in line for line in out.get("logs") or []), out.get("logs"))

    parsed = insights_from_markdown(report)
    check("the history parser finds exactly one insight", len(parsed) == 1, parsed)
    check("the report says plainly that no AI model was used",
          "without an AI model" in report)
    check("a check that was not run is disclosed, with its reason",
          "Recent-week checks were not run: batch_load_date" in report, report)

    empty = insight_deterministic.write_report(
        {}, [], [], [], {"reason": "all_previously_reported"})
    check("a day with nothing new says so in plain words",
          "already reported in an earlier run" in empty, empty)
    check("and still carries every section",
          re.findall(r"(?m)^# (.+)$", empty)[0] == "Key Insights"
          and len(re.findall(r"(?m)^# ", empty)) == 5)


def test_kpi_cards_call_no_model() -> None:
    print("\n=== KPI cards: code-owned wording that still validates ===")
    forbid_llm()
    signal = {
        "id": "electronics", "candidate_id": "c9", "kind": "business",
        "description": "ELECTRONICS revenue growth was 551600 alongside quantity growth.",
        "affected_segment": "ELECTRONICS", "impact_value": 551_600.0, "impact_share": 15.7,
        "decomposition": [{"driver": "QTY Growth", "volume_effect": 899_000.0,
                           "rate_effect": -347_400.0}],
    }
    try:
        cards = api_payloads.generate_kpi_insights_payload(
            [signal], {"report_ai_tier": "deterministic"},
            generated_at=datetime(2026, 9, 11, 7, 0))
        ok = True
    except LLMCalled:
        cards, ok = [], False
    check("KPI cards are built without a model", ok)
    card = cards[0] if cards else {}
    insight = card.get("insight") or {}
    check("the card leads with the code-owned change sentence",
          str(card.get("description", "")).startswith("ELECTRONICS revenue increased by 551.6K"),
          card.get("description"))
    check("the back-of-card summary is the grounded sentence, not empty",
          bool(str(insight.get("summary") or "").strip()), insight)
    check("the title and action name the area",
          "ELECTRONICS" in str(insight.get("title")) and "ELECTRONICS" in str(insight.get("action")),
          insight)


# ------------------------------ 4. the defects the first live run caught (2026-09-11)
#
# The offline fixtures above were all small, well-behaved findings. The first
# deterministic run against the live model produced three things none of them
# exercised; each is pinned here so it cannot come back.


def test_a_share_above_the_whole_change() -> None:
    print("\n=== a finding bigger than the whole change still reads cleanly ===")
    # A category that lost more units than the business lost overall - 145% of
    # the net drop, because other areas gained. The fallback used to say "the
    # above-100% result", quoting a figure nothing measured, on every such finding.
    signal = dict(torch_signal(), id="confectionery", affected_segment="CONFECTIONERY",
                  impact_value=-636_899.0, impact_share=145.17, current=4_603_800.9,
                  prior=5_240_699.9, metric_family="quantity", metric="QTY Growth",
                  decomposition=None, score=145.17)
    brief = insight_synthesizer._manager_fact_brief(signal, PROFILE)
    finding = insight_synthesizer._deterministic_finding(signal, brief) or ""
    numbers = insight_synthesizer._supported_numbers({"manager_fact_briefs": [brief],
                                                      "signals": [signal]})
    check("the fallback paragraph is written", bool(finding))
    check("it never quotes the unmeasured figure 100%", "100%" not in finding, finding)
    issues = insight_synthesizer._clarity_issues("# Key Insights\n" + finding
                                                 + "\n\n# Data Quality Watch-outs\n", 1, [brief], numbers)
    check("and it passes the manager-facing clarity check", not issues, issues)

    # Two quantified levers plus the missing-areas note ran to eight sentences
    # against a limit of seven; the note is now the first thing trimmed.
    long_signal = torch_signal()
    long_brief = insight_synthesizer._manager_fact_brief(long_signal, PROFILE)
    long_brief["main"] = dict(long_brief.get("main") or {}, share_of_total_pct=124.4,
                              share_of_total_pct_display="124.4%",
                              other_change_display="-230.0K", total_change_display="+968.1K")
    long_finding = insight_synthesizer._deterministic_finding(long_signal, long_brief) or ""
    sentences = insight_synthesizer._manager_sentences(long_finding)
    check("a finding with levers and the missing-areas note stays within the sentence limit",
          len(sentences) <= insight_synthesizer._MAX_MANAGER_SENTENCES, sentences)


def _lever_row(member: str, rank: int, pct: float, change: float, share: float,
               peer: float, severity: str = "watch") -> dict:
    return {"member": member, "rank": rank, "change_pct": pct, "change": change,
            "business_share_pct": share, "vs_peer_median_pts": peer, "severity": severity,
            "comparable": True, "current": 1_000_000.0}


def _levers(transactions: float, basket: float, price: float) -> dict:
    return {"reconciles": True, "state": "Thinner baskets, higher prices",
            "levers": {"transactions": transactions, "basket_size": basket, "price": price}}


def test_stores_sharing_a_lever_pattern() -> None:
    print("\n=== stores in the same lever pattern each get their own story ===")
    from src.tools import summary_dashboard
    from src.tools.summary_validation import _duplicate_story_errors

    # The live 2026-09-11 shape: three of four stores "thinner baskets, higher
    # prices", so the levers template made their stories identical once the
    # figures are set aside, and the page failed its own prose audit.
    rows = [_lever_row("ST4", 1, 10.07, 1_204_029.0, 32.4, 7.6, "critical"),
            _lever_row("ST2", 2, -5.43, -387_893.7, 16.6, 7.9),
            _lever_row("ST3", 3, 2.44, 192_000.0, 19.6, 0.0),
            _lever_row("ST1", 4, -0.31, -40_000.0, 31.4, 2.8)]
    levers = {"ST4": _levers(5.83, -5.17, 9.68), "ST2": dict(_levers(-6.45, -0.58, 1.68), state="Price masking"),
              "ST3": _levers(4.37, -5.05, 3.36), "ST1": _levers(2.22, -4.43, 2.05)}
    contributions = {"items": [{"member": r["member"], "contribution_pts": r["change_pct"] / 2}
                               for r in rows],
                     "carrier": {"member": "ST4"}, "drag": {"member": "ST2"}}
    level = {"rows": rows, "peer_median_change_pct": 1.07}

    cards = summary_dashboard.build_entity_cards(level, contributions, levers)
    stories = [(c["member"], c["story"], c["rank"]) for c in cards if c.get("severity") != "steady"]
    check("the page no longer fails the duplicate-story rule",
          not _duplicate_story_errors(stories, 0.82), [c["story"] for c in cards])
    check("every story still carries its own levers",
          all("transactions" in c["story"] for c in cards), [c["story"] for c in cards])
    check("the leading store's story is untouched - it repeated nothing before it",
          cards[0]["story"].startswith("Revenue +10.07%"), cards[0]["story"])
    check("no sentence is printed twice inside one story",
          all(len(set(summary_dashboard_sentences(c["story"])))
              == len(summary_dashboard_sentences(c["story"])) for c in cards),
          [c["story"] for c in cards])

    # A page the check already accepts must render exactly as before: the golden
    # master pins that on real data, and this pins it on a small one.
    distinct = [_lever_row("A", 1, 12.0, 500_000.0, 40.0, 11.0, "critical"),
                _lever_row("B", 2, -3.0, -90_000.0, 30.0, 4.0),
                _lever_row("C", 3, 0.2, 1_000.0, 30.0, 0.5, "steady")]
    # The same peer median the level hands build_entity_cards: without it the
    # direction reads "behind" where the real card correctly reads "ahead of".
    before = [summary_dashboard._entity_story(r, None, None, None, None, 0.2) for r in distinct]
    after = [c["story"] for c in summary_dashboard.build_entity_cards(
        {"rows": distinct, "peer_median_change_pct": 0.2}, {"items": []})]
    check("an accepted page's stories are byte-for-byte unchanged", before == after, (before, after))


def summary_dashboard_sentences(story: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", story or "") if s.strip()]


def test_overall_headline() -> None:
    print("\n=== the summary headline says what happened, with its figures ===")
    from src.agents import fresh_summary_generator

    def candidate(change: float, change_display: str, pct_display: str) -> dict:
        return {"angle": "overall_performance", "evidence": {"facts": [{
            "fact_id": "F5", "fact_kind": "comparison", "subject": "Overall",
            "metric": "Revenue comparison", "display_value": change_display, "raw_value": change,
            "change_value": change, "change_display": change_display,
            "change_pct_display": pct_display, "current_display": "40.7M",
            "prior_display": "39.7M", "comparison": "the same period last year"}]}}

    up = fresh_summary_generator._overall_headline(candidate(968_091.98, "+968.1K", "2.4%"))
    check("it no longer reads 'Revenue comparison was ...'", "comparison was" not in up, up)
    check("it states the direction, change, percentage and level",
          up == "Revenue increased by +968.1K (2.4%) to 40.7M, compared with the same period last year.", up)
    down = fresh_summary_generator._overall_headline(candidate(-12_000.0, "-12.0K", "0.1%"))
    check("a decline reads as a decrease", down.startswith("Revenue decreased by -12.0K"), down)
    check("with no comparison fact it still falls back to the old writer",
          fresh_summary_generator._overall_headline({"evidence": {"facts": []}})
          == "Latest performance summary")


# ------------------------------------------------- 5. the five standalone reports
#
# The same dial, reaching every report. Those modules import get_llm inside the
# function, so the stand-in is installed on src.tools.llm itself.


class _CountingLLM:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *_a, **_k):
        self.calls += 1
        raise LLMCalled("a language model was requested")


def _install(counter: _CountingLLM):
    from src.tools import llm as llm_module
    original = llm_module.get_llm
    llm_module.get_llm = counter  # type: ignore[assignment]
    return llm_module, original


def test_snapshot_investigation_keeps_drills_without_a_model() -> None:
    print("\n=== Stock Age / SKU Overview / Daily Sales: drills stay, the model goes ===")
    from src.domains.inventory import snapshot_investigator

    def run(cfg: dict) -> tuple[dict, int]:
        counter = _CountingLLM()
        module, original = _install(counter)
        try:
            result = snapshot_investigator.investigate(
                lambda dax: [{"name": "LOC1", "value": 900.0}, {"name": "LOC2", "value": 100.0}],
                {"currency": "USD"}, cfg, report_id="replay",
                candidates_fn=lambda model, cfg, max_findings: [{
                    "candidate_id": "f1", "affected_segment": "FMCG FOOD",
                    "dimension": "division", "description": "FMCG FOOD holds aged stock.",
                    "_drill_role": "division", "_drill_others": ["location", "category"]}],
                build_dax_fn=lambda cfg, own_role, own_member, drill_role: f"EVALUATE /* {drill_role} */",
                normalize_fn=lambda rows, role: rows,
                enabled_key="replay_investigation_enabled",
                max_findings_key="replay_max_findings", max_rounds_key="replay_max_rounds",
                budget_total_key="replay_budget_total", budget_per_finding_key="replay_budget_each",
                default_max_rounds=2, default_budget_total=4, default_budget_per_finding=2)
        finally:
            module.get_llm = original  # type: ignore[assignment]
        return result, counter.calls

    deterministic, calls = run({"replay_investigation_enabled": True, "report_ai_tier": "deterministic"})
    entry = (deterministic.get("entries") or [{}])[0]
    check("no model is requested on the deterministic tier", calls == 0, calls)
    check("the drill-down queries still run - the evidence is kept",
          len(entry.get("drills") or []) == 2, entry.get("drills"))
    check("roles are drilled in the engine's fixed order",
          [d["role"] for d in entry.get("drills") or []] == ["location", "category"], entry.get("drills"))
    check("and the narrative is the grounded draft",
          entry.get("authoring_mode") == "deterministic" and "LOC1" in str(entry.get("narrative")),
          entry)

    _investigated, calls = run({"replay_investigation_enabled": True})
    check("with no tier set the investigator still asks the model", calls > 0, calls)


def test_standalone_prose_writers_return_their_draft() -> None:
    print("\n=== Target Tracker / Inventory Management: the draft, even with AI wording on ===")
    from src.domains.inventory import stock_health_author
    from src.domains.sales import target_tracker_author, target_tracker_html

    counter = _CountingLLM()
    module, original = _install(counter)
    saved = (target_tracker_html.headline, target_tracker_html.hero_narrative,
             stock_health_author.deterministic, target_tracker_author.context)
    try:
        # The investigated path builds its prompt from the model before asking for
        # one; a stub context lets the empty fixture model reach that request.
        target_tracker_author.context = lambda model, rules: "fixture context"  # type: ignore[assignment]
        target_tracker_html.headline = lambda r, model: "Month at 105.1% of target."  # type: ignore[assignment]
        target_tracker_html.hero_narrative = lambda r, model: "13 of 31 days hit target."  # type: ignore[assignment]
        stock_health_author.deterministic = lambda model, score=None: {  # type: ignore[assignment]
            "headline": "Stock Value USD 13,966,417.", "authoring_mode": "deterministic"}

        prose = target_tracker_author.author(
            {}, {"target_tracker_llm_authoring_enabled": True, "report_ai_tier": "deterministic"})
        check("Target Tracker returns its grounded draft with AI wording switched on",
              prose.get("authoring_mode") == "deterministic"
              and prose.get("headline") == "Month at 105.1% of target.", prose)

        stock = stock_health_author.author(
            {}, {"inventory_llm_authoring_enabled": True, "report_ai_tier": "deterministic"})
        check("Inventory Management returns its grounded draft with AI wording switched on",
              stock.get("authoring_mode") == "deterministic", stock)
        check("neither writer requested a model", counter.calls == 0, counter.calls)

        target_tracker_author.author({}, {"target_tracker_llm_authoring_enabled": True})
        check("with no tier set, Target Tracker still asks the model when its switch is on",
              counter.calls > 0, counter.calls)
    finally:
        (target_tracker_html.headline, target_tracker_html.hero_narrative,
         stock_health_author.deterministic, target_tracker_author.context) = saved
        module.get_llm = original  # type: ignore[assignment]


def test_standalone_kpi_cards_read_the_tier_from_config() -> None:
    print("\n=== KPI cards from a standalone runner's state shape ===")
    forbid_llm()
    signal = {"id": "s1", "kind": "business", "affected_segment": "CFH017",
              "description": "CFH017 was below target in all four periods.",
              "comparison_label": "of target", "impact_value": -11.13, "impact_share": None}
    # Exactly what run_ageing / run_inventory / run_target_tracker build: the tier
    # lives only inside "config", never as a top-level key.
    state = {"config": {"report_ai_tier": "deterministic"}, "report_id": "target_tracker"}
    try:
        cards = api_payloads.generate_kpi_insights_payload(
            [signal], state, generated_at=datetime(2026, 9, 11, 7, 15))
        ok = True
    except LLMCalled:
        cards, ok = [], False
    check("KPI cards are built without a model from the runner's state shape", ok)
    check("the card uses the report's own grounded sentence",
          bool(cards) and "CFH017 was below target" in str(cards[0].get("description")),
          cards[0].get("description") if cards else None)


# ------------------------------------------------------------------ 6. narrated
#
# The middle tier: code decides everything a model could get wrong in substance,
# and a model writes only the sentences, each one checked, each with a fallback.


class _SchemaRecorder:
    """A get_llm stand-in recording which structured schema each call asked for."""

    def __init__(self, reply=None, raise_on_invoke: bool = True) -> None:
        self.schemas: list[str] = []
        self.reply = reply
        self.raise_on_invoke = raise_on_invoke

    def __call__(self, state=None, structured_schema=None, **_kwargs):
        self.schemas.append(getattr(structured_schema, "__name__", str(structured_schema)))
        recorder = self

        class _Model:
            def invoke(self, messages):
                if recorder.raise_on_invoke:
                    raise LLMCalled("stub model")
                return recorder.reply(messages) if callable(recorder.reply) else recorder.reply

        return _Model()


def _reply(paragraphs: list[tuple[str, str]]):
    from types import SimpleNamespace
    return SimpleNamespace(paragraphs=[SimpleNamespace(signal_id=sid, paragraph=text)
                                       for sid, text in paragraphs])


def _narration_inputs():
    signal = torch_signal()
    brief = insight_synthesizer._manager_fact_brief(signal, PROFILE)
    numbers = insight_synthesizer._supported_numbers({"manager_fact_briefs": [brief],
                                                      "signals": [signal]})
    draft = insight_deterministic.grounded_paragraph(signal, brief) or ""
    head, tail = draft.rsplit("Check ", 1)
    # A genuine rewording that keeps every figure: a different closing verb.
    reworded = head + "Review " + tail
    return signal, brief, numbers, draft, reworded


def test_narrated_decides_nothing() -> None:
    print("\n=== narrated: no model plans, selects or investigates ===")
    forbid_llm()
    base = {"report_ai_tier": "narrated", "output_folder": OUT, "semantic_model_profile": PROFILE,
            "config": {"report_domain": "sales"},
            "model_metadata": {"tables": [], "columns": [], "measures": []}}
    signal = torch_signal()
    for label, call in (
        ("report_understanding", lambda: report_understanding.run(dict(base))),
        ("dax_planner", lambda: dax_planner.run(dict(base, report_understanding={"domain": "Sales / Retail"}))),
        ("dax_generator", lambda: dax_generator.run(dict(base, dax_plan={"queries": []}))),
        ("insight_signal_detector", lambda: insight_signal_detector.run(dict(
            base, insight_memory_enabled=True, insight_max_new_per_run=2,
            insight_clean_data={"successful": 1, "queries": []},
            insight_eligible_candidates={"business_candidates": [candidate("c1", 5, "ST1")],
                                         "data_quality_candidates": []}))),
        ("insight_investigator", lambda: insight_investigator.run(dict(
            base, insight_signals=[signal], insight_clean_data={"queries": []},
            insight_evidence_briefs={}, insight_gap_evidence={signal["id"]: gap_evidence()},
            insight_evidence_contracts={}, insight_query_cache={}))),
    ):
        try:
            call()
            ok = True
        except LLMCalled:
            ok = False
        check(f"{label} makes no model call on the narrated tier", ok)

    check("narrated writes but never decides",
          ai_tier.narrated(base) and not ai_tier.investigates(base)
          and not ai_tier.deterministic(base) and ai_tier.prose_allowed(base, False))
    check("narrated turns the summary wording on even with its old switch off",
          ai_tier.authoring_allowed({"report_ai_tier": "narrated",
                                     "summary_llm_authoring_enabled": False}))
    check("investigated still leaves each report's own switch in charge",
          not ai_tier.prose_allowed({}, False) and ai_tier.prose_allowed({}, True))
    check("deterministic still refuses wording whatever the switch says",
          not ai_tier.prose_allowed({"report_ai_tier": "deterministic"}, True))


def test_narrated_key_insights_are_checked_slot_by_slot() -> None:
    print("\n=== narrated Key Insights: model wording, checked alone, fallback per slot ===")
    signal, brief, numbers, draft, reworded = _narration_inputs()
    sid = signal["id"]
    state = {"report_ai_tier": "narrated"}
    check("the grounded draft passes the check on its own",
          not insight_deterministic.paragraph_issues(draft, brief, numbers))
    check("the fixture rewording is itself a valid paragraph",
          not insight_deterministic.paragraph_issues(reworded, brief, numbers),
          insight_deterministic.paragraph_issues(reworded, brief, numbers))

    good = _SchemaRecorder(reply=_reply([(sid, reworded)]), raise_on_invoke=False)
    out, stats = insight_deterministic.narrate_key_insights(
        state, [signal], [brief], numbers, llm_factory=good)
    check("a paragraph that passes the check is published", out.get(sid) == reworded
          and stats["authored"] == 1, stats)
    check("the model is asked for paragraphs and nothing else", good.schemas == ["_Paragraphs"],
          good.schemas)

    invented = draft.rstrip() + " It could reach 999.9K."
    bad = _SchemaRecorder(reply=_reply([(sid, invented)]), raise_on_invoke=False)
    out, stats = insight_deterministic.narrate_key_insights(
        state, [signal], [brief], numbers, llm_factory=bad)
    check("a paragraph quoting a figure the data does not hold is thrown away",
          out.get(sid) == draft and stats["authored"] == 0, stats)
    check("and the rejection records the checker's reason",
          "unsupported figure" in json.dumps(stats["rejected"]), stats["rejected"])

    seen: list[list[dict]] = []

    def two_rounds(messages):
        seen.append(list(messages))
        return _reply([(sid, invented)]) if len(seen) == 1 else _reply([(sid, reworded)])

    healed = _SchemaRecorder(reply=two_rounds, raise_on_invoke=False)
    out, stats = insight_deterministic.narrate_key_insights(
        state, [signal], [brief], numbers, llm_factory=healed)
    check("a rejected paragraph gets one repair round and can still be published",
          len(seen) == 2 and out.get(sid) == reworded, stats)
    check("the repair request hands back the checker's own reasons",
          len(seen) == 2 and "unsupported figure" in seen[1][-1]["content"])

    broken = _SchemaRecorder(raise_on_invoke=True)
    out, stats = insight_deterministic.narrate_key_insights(
        state, [signal], [brief], numbers, llm_factory=broken)
    check("a failed model call keeps every grounded draft and never raises",
          out.get(sid) == draft and "error" in stats, stats)

    silent = _SchemaRecorder(reply=_reply([]), raise_on_invoke=False)
    out, stats = insight_deterministic.narrate_key_insights(
        state, [signal], [brief], numbers, llm_factory=silent)
    check("a slot the model did not return keeps its draft",
          out.get(sid) == draft and stats["fallback"] == 1, stats)


def test_narrated_report_end_to_end() -> None:
    print("\n=== narrated insight report: the model's words inside code's structure ===")
    signal, _brief, _numbers, _draft, reworded = _narration_inputs()
    recorder = _SchemaRecorder(reply=_reply([(signal["id"], reworded)]), raise_on_invoke=False)
    module, original = _install(recorder)
    try:
        trail = insight_deterministic.trail(signal, gap_evidence(), PROFILE)
        out = insight_synthesizer.run({
            "report_ai_tier": "narrated", "output_folder": OUT,
            "insight_signals": [signal], "insight_investigations": [trail],
            "semantic_model_profile": PROFILE, "insight_clean_data": {},
            "insight_novelty": {"reason": "ok"},
            "report_understanding": {"domain": "Sales / Retail"},
        })
    finally:
        module.get_llm = original  # type: ignore[assignment]
    report = str(out.get("insight_report") or "")
    check("the published Key Insights paragraph is the model's wording",
          "Review CFH021 HAND TORCH" in report, report[:400])
    check("the structure is code's: the five sections in order",
          re.findall(r"(?m)^# (.+)$", report) == ["Key Insights", "Data Quality Watch-outs",
                                                   "Evidence Trail", "Confidence & Caveats",
                                                   "Suggested Follow-ups"])
    check("only the Key Insights slots were requested from the model",
          recorder.schemas == ["_Paragraphs"], recorder.schemas)
    check("the report says which wording the model wrote and that figures were checked",
          "An AI model wrote the wording of 1 of the 1 key insight(s)" in report)
    check("the run log reports a clean clarity check",
          any("clarity check clean" in line for line in out.get("logs") or []), out.get("logs"))


def test_narrated_standalone_reports() -> None:
    print("\n=== narrated standalone reports: wording by the model, choices by rules ===")
    from src.domains.inventory import snapshot_investigator, stock_health_author
    from src.domains.sales import target_tracker_author, target_tracker_html

    recorder = _SchemaRecorder(raise_on_invoke=True)
    module, original = _install(recorder)
    saved = (target_tracker_html.headline, target_tracker_html.hero_narrative,
             stock_health_author.deterministic, target_tracker_author.context,
             stock_health_author.context, api_payloads.get_llm)
    try:
        target_tracker_html.headline = lambda r, model: "Month at 105.1% of target."  # type: ignore[assignment]
        target_tracker_html.hero_narrative = lambda r, model: "13 of 31 days hit target."  # type: ignore[assignment]
        target_tracker_author.context = lambda model, rules: "fixture context"  # type: ignore[assignment]
        stock_health_author.deterministic = lambda model, score=None: {  # type: ignore[assignment]
            "headline": "Stock Value USD 13,966,417.", "authoring_mode": "deterministic"}
        stock_health_author.context = lambda model, score, rules: "fixture context"  # type: ignore[assignment]

        result = snapshot_investigator.investigate(
            lambda dax: [{"name": "LOC1", "value": 900.0}, {"name": "LOC2", "value": 100.0}],
            {"currency": "USD"}, {"replay_investigation_enabled": True, "report_ai_tier": "narrated"},
            report_id="replay",
            candidates_fn=lambda model, cfg, max_findings: [{
                "candidate_id": "f1", "affected_segment": "FMCG FOOD", "dimension": "division",
                "description": "FMCG FOOD holds aged stock.",
                "_drill_role": "division", "_drill_others": ["location", "category"]}],
            build_dax_fn=lambda cfg, own_role, own_member, drill_role: f"EVALUATE /* {drill_role} */",
            normalize_fn=lambda rows, role: rows,
            enabled_key="replay_investigation_enabled",
            max_findings_key="replay_max_findings", max_rounds_key="replay_max_rounds",
            budget_total_key="replay_budget_total", budget_per_finding_key="replay_budget_each",
            default_max_rounds=2, default_budget_total=4, default_budget_per_finding=2)
        entry = (result.get("entries") or [{}])[0]
        check("the breakdowns still run in the fixed order",
              [d["role"] for d in entry.get("drills") or []] == ["location", "category"], entry)
        check("no model is asked which breakdown to drill next",
              "DrillDecision" not in recorder.schemas, recorder.schemas)
        check("a model is asked to write the breakdown up",
              "DrillNarrative" in recorder.schemas, recorder.schemas)

        recorder.schemas.clear()
        target_tracker_author.author({}, {"target_tracker_llm_authoring_enabled": False,
                                          "report_ai_tier": "narrated"})
        stock_health_author.author({}, {"inventory_llm_authoring_enabled": False,
                                        "report_ai_tier": "narrated"})
        check("Target Tracker and Inventory Management ask for wording with their old switches off",
              {"TargetTrackerProse", "StockHealthProse"} <= set(recorder.schemas), recorder.schemas)

        recorder.schemas.clear()
        api_payloads.get_llm = recorder  # type: ignore[assignment]
        try:
            api_payloads.generate_kpi_insights_payload(
                [{"id": "s1", "kind": "business", "affected_segment": "CFH017",
                  "description": "CFH017 was below target in all four periods.",
                  "comparison_label": "of target", "impact_value": -11.13}],
                {"config": {"report_ai_tier": "narrated"}},
                generated_at=datetime(2026, 9, 11, 7, 15))
        except Exception:  # noqa: BLE001 - the stub model refuses, which is the point
            pass
        check("KPI card wording is requested from the model on the narrated tier",
              "_KpiCardTextList" in recorder.schemas, recorder.schemas)
    finally:
        (target_tracker_html.headline, target_tracker_html.hero_narrative,
         stock_health_author.deterministic, target_tracker_author.context,
         stock_health_author.context, api_payloads.get_llm) = saved
        module.get_llm = original  # type: ignore[assignment]


def _attempts_file() -> Path:
    from src.tools import authoring_attempts
    return PROJECT_ROOT / OUT / authoring_attempts.FILENAME


def _read_attempts() -> dict:
    try:
        return json.loads(_attempts_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an absent file reads as nothing recorded
        return {}


def _writer(name: str) -> list:
    return (_read_attempts().get("writers") or {}).get(name) or []


class _Lines:
    """A RunLogger stand-in keeping every line it is given."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def info(self, message: str) -> None:
        self.lines.append(str(message))

    error = info


def test_rejected_drafts_leave_their_reasons() -> None:
    print("\n=== every rejected draft leaves the checker's reasons behind ===")
    import threading

    from src.agents import fresh_summary_generator, summary_dashboard_builder
    from src.tools import authoring_attempts, token_usage

    state = {"report_ai_tier": "narrated", "output_folder": OUT}

    # The artifact itself: never written without a folder, never raises,
    # survives concurrent writers, and a new run replaces the last one's file.
    authoring_attempts.reset()
    if _attempts_file().is_dir():
        import shutil
        shutil.rmtree(_attempts_file())
    _attempts_file().unlink(missing_ok=True)
    authoring_attempts.record({"config": {"report_ai_tier": "narrated"}}, "api_payloads", {"n": 1})
    check("a caller naming no output folder writes nothing", not _attempts_file().exists())
    # A folder nested under a plain file cannot be created. (Nesting it under the
    # artifact's own name would create a directory of that name and break every
    # later write in this test - which is exactly what a first draft of it did.)
    blocker = PROJECT_ROOT / OUT / "not_a_folder.txt"
    blocker.write_text("a file, not a folder", encoding="utf-8")
    try:
        authoring_attempts.record({"output_folder": f"{OUT}/not_a_folder.txt/nested"}, "x", {"n": 1})
        raised = False
    except Exception:  # noqa: BLE001
        raised = True
    check("an unwritable folder is swallowed, never raised", not raised)

    authoring_attempts.reset()
    threads = [threading.Thread(target=authoring_attempts.record, args=(state, f"w{i % 4}", {"n": i}))
               for i in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    writers = _read_attempts().get("writers") or {}
    check("forty concurrent records from two branches all survive the merge",
          sum(len(entries) for entries in writers.values()) == 40, writers)
    authoring_attempts.reset()
    authoring_attempts.record(state, "w0", {"n": "new run"})
    check("the first record of a new run replaces the previous run's file",
          _read_attempts().get("writers") == {"w0": [{"n": "new run"}]}, _read_attempts())

    # Tokens are attributed by writer, so a concurrent branch's call is not counted.
    token_usage.reset()
    since = authoring_attempts.mark("fresh_summary_generator")
    token_usage.record("fresh_summary_generator", "gpt-5.4", {"prompt": 19859, "cached": 0, "completion": 721})
    token_usage.record("insight_deterministic", "gpt-5.4", {"prompt": 2033, "cached": 0, "completion": 501})
    usage = authoring_attempts.usage_since("fresh_summary_generator", since)
    token_usage.reset()
    check("a call's tokens are attributed to its own writer and no other",
          usage["calls"] == 1 and usage["prompt_tokens"] == 19859
          and usage["completion_tokens"] == 721, usage)

    # The summary writer: rejected attempts reach the log; the artifact is verbatim.
    authoring_attempts.reset()
    log = _Lines()
    attempts = [
        {"attempt": 1, "outcome": "rejected", "errors": ["headline must quote a supported figure"]},
        {"attempt": 2, "outcome": "validated", "errors": []},
    ]
    fresh_summary_generator._report_attempts(state, log, attempts, mode="balanced_multi_focus",
                                             outcome="validated")
    check("a rejected summary attempt's reasons reach the run log, a validated one's do not",
          any("attempt 1 rejected" in line and "must quote a supported figure" in line
              for line in log.lines)
          and not any("attempt 2" in line for line in log.lines), log.lines)
    written = _writer("fresh_summary_generator")
    check("and the attempts artifact, verbatim and labelled with the tier",
          bool(written) and written[0]["attempts"] == attempts and written[0]["tier"] == "narrated",
          written)

    # The dashboard: three rejections per view, each recorded and logged, then fallback.
    saved = (summary_dashboard_builder.get_llm, summary_dashboard_builder.dashboard_rules,
             summary_dashboard_builder._authoring_context)
    calls: list = []

    class _Draft:
        def invoke(self, messages):
            calls.append(messages)
            return {"hero": {"headline": "Revenue rose."}, "entities": [], "areas": []}

    log = _Lines()
    try:
        summary_dashboard_builder.get_llm = lambda *_a, **_k: _Draft()  # type: ignore[assignment]
        summary_dashboard_builder.dashboard_rules = (  # type: ignore[assignment]
            lambda draft, view: ["hero headline quotes no figure"])
        summary_dashboard_builder._authoring_context = (  # type: ignore[assignment]
            lambda view: {"view": view.get("key")})
        out = summary_dashboard_builder._narratives(dict(state), [{"key": "primary"}], log)
    finally:
        (summary_dashboard_builder.get_llm, summary_dashboard_builder.dashboard_rules,
         summary_dashboard_builder._authoring_context) = saved
    views = _writer("summary_dashboard_builder")
    check("the dashboard records every rejected attempt per view, then falls back unchanged",
          out == {} and len(calls) == 3 and bool(views) and views[0]["view"] == "primary"
          and views[0]["outcome"] == "fallback"
          and [item["outcome"] for item in views[0]["attempts"]] == ["rejected"] * 3
          and views[0]["attempts"][0]["errors"] == ["hero headline quotes no figure"], views)
    check("each rejected dashboard attempt is logged with its reasons",
          sum("rejected" in line and "quotes no figure" in line for line in log.lines) == 3, log.lines)
    check("the summary writer's entry survives the dashboard's merge",
          bool(_writer("fresh_summary_generator")))

    # Key Insights: the rejected paragraph and the repair that passed, per attempt.
    signal, brief, numbers, draft, reworded = _narration_inputs()
    sid = signal["id"]
    invented = draft.rstrip() + " It could reach 999.9K."
    seen: list = []

    def two_rounds(messages):
        seen.append(messages)
        return _reply([(sid, invented)]) if len(seen) == 1 else _reply([(sid, reworded)])

    lines: list[str] = []
    _out, stats = insight_deterministic.narrate_key_insights(
        dict(state), [signal], [brief], numbers,
        llm_factory=_SchemaRecorder(reply=two_rounds, raise_on_invoke=False), log=lines.append)
    first, second = ((stats.get("attempts") or []) + [{}, {}])[:2]
    check("Key Insights records the rejected paragraph and the repair that passed",
          "unsupported figure" in json.dumps(first.get("rejected"))
          and second.get("accepted") == [sid], stats.get("attempts"))
    check("and logs the rejection with the checker's reason",
          any("unsupported figure" in line for line in lines), lines)
    entry = (_writer("insight_deterministic") or [{}])[-1]
    check("the Key Insights entry lands in the same artifact",
          entry.get("authored") == 1 and len(entry.get("attempts") or []) == 2, entry)

    # KPI cards: a summary swapped for code's sentence is a recorded fallback, and
    # one that quotes only a measured figure is not. The description carries the
    # figures, because with nothing measured to quote the summary is kept as written.
    def card(sid: str, summary: str):
        return api_payloads._KpiCardText(
            signal_id=sid, category="", description="", insight_title=f"CFH01{sid[-1]} target",
            insight_summary=summary, insight_action="Check the branch by department.")

    class _Cards:
        def invoke(self, messages):
            return api_payloads._KpiCardTextList(cards=[
                card("s1", "CFH011 fell short by 999.9K."),
                card("s2", "CFH012 reached 88.9% of target, a gap of 406.3K."),
            ])

    signals = [{"id": sid, "kind": "business", "affected_segment": segment,
                "description": f"{segment} reached 88.9% of target, a gap of 406.3K.",
                "comparison_label": "of target", "impact_value": -406300.0}
               for sid, segment in (("s1", "CFH011"), ("s2", "CFH012"))]
    saved_llm = api_payloads.get_llm
    try:
        api_payloads.get_llm = lambda *_a, **_k: _Cards()  # type: ignore[assignment]
        try:
            api_payloads.generate_kpi_insights_payload(
                signals, dict(state), generated_at=datetime(2026, 9, 11, 7, 15))
        except Exception:  # noqa: BLE001 - only the record is under test here
            pass
    finally:
        api_payloads.get_llm = saved_llm  # type: ignore[assignment]
    kpi = (_writer("api_payloads") or [{}])[-1]
    check("a KPI summary quoting an unmeasured figure is recorded as a fallback, a grounded one is not",
          kpi.get("summary_fallback") == ["s1"] and bool(kpi.get("rounds"))
          and kpi["rounds"][0]["returned"] == ["s1", "s2"], kpi)
    authoring_attempts.reset()


def _quantity_decline_candidate() -> dict:
    """The overall quantity comparison of the narrated run of 2026-09-11, as the builder printed it.

    Its percentage is unsigned beside a signed amount, while the check holds the
    signed change - the fact that rejected two live drafts for copying it.
    """
    return {"candidate_id": "overall", "angle": "overall_performance", "evidence": {"facts": [{
        "fact_id": "F1", "fact_kind": "comparison", "subject": "Overall",
        "metric": "Quantity comparison", "display_value": "-407.4K", "raw_value": -407406.1,
        "current_value": 22300000.0, "current_display": "22.3M",
        "prior_value": 22707406.1, "prior_display": "22.7M",
        "change_value": -407406.1, "change_display": "-407.4K",
        "change_pct": -1.794, "change_pct_display": "1.8%",
        "comparison": "the same period last year",
        "statement": ("Overall - Quantity decreased by -407.4K (1.8%), from 22.7M to 22.3M "
                      "compared with the same period last year"),
        "subject_role": "focus", "coverage": "complete",
    }]}}


class _CopyingSummaryModel:
    """Writes the page from the first supported fact it is shown, word for word."""

    def __init__(self, extra: str = "") -> None:
        self.calls: list = []
        self.extra = extra

    def invoke(self, messages):
        self.calls.append(list(messages))
        context = json.loads(messages[1]["content"].split("\n", 1)[1])
        fact = context["selected_perspectives"][0]["supported_facts"][0]
        return {
            "headline": f"Quantity decreased by {fact['display_value']} compared with the same period last year.",
            "blocks": [{"kind": "paragraph", "heading": "Overall Performance",
                        "text": fact["statement"] + "." + self.extra, "points": [],
                        "chart_source_id": "", "chart_type": "bar"}],
            "covered_candidate_ids": ["overall"],
        }


def test_narrated_summary_passes_first_time() -> None:
    print("\n=== narrated summary: what the model is shown passes the check as written ===")
    from src.agents import fresh_summary_generator as generator
    from src.tools import file_io, summary_validation

    candidate = _quantity_decline_candidate()
    narrated = {"report_ai_tier": "narrated", "output_folder": OUT}
    investigated = {"output_folder": OUT}

    def author(state: dict, model: _CopyingSummaryModel) -> tuple[list, bool]:
        attempts: list = []
        original = generator.get_llm
        generator.get_llm = lambda *_a, **_k: model  # type: ignore[assignment]
        try:
            generator._invoke(state, [candidate], mode="balanced_multi_focus", attempts=attempts)
            raised = False
        except ValueError:
            raised = True
        finally:
            generator.get_llm = original  # type: ignore[assignment]
        return attempts, raised

    copier = _CopyingSummaryModel()
    attempts, raised = author(narrated, copier)
    shown = json.loads(copier.calls[0][1]["content"].split("\n", 1)[1])
    statement = shown["selected_perspectives"][0]["supported_facts"][0]["statement"]
    check("narrated: the percentage the model is shown carries the sign the check expects",
          "(-1.8%)" in statement, statement)
    check("narrated: a draft copying code's own statement word for word passes on attempt 1",
          not raised and [a["outcome"] for a in attempts] == ["validated"] and len(copier.calls) == 1,
          attempts)

    copier = _CopyingSummaryModel()
    attempts, raised = author(investigated, copier)
    check("investigated: the same copy is still rejected, so the defect this closes is real",
          raised and "'1.8%' is not supported" in json.dumps(attempts), attempts)
    check("investigated: still allows three attempts",
          len(copier.calls) == 3 and len(attempts) == 3, attempts)
    expected_system = (file_io.read_prompt("_global_rules.md") + file_io.business_rules_block(investigated)
                       + file_io.summary_business_rules_block(investigated) + "\n\n"
                       + file_io.read_prompt("fresh_summary_prompt.md"))
    check("investigated: the system prompt is exactly what it was",
          copier.calls[0][0]["content"] == expected_system)
    check("investigated: the evidence it is shown is unchanged, unsigned percentage included",
          "(1.8%)" in copier.calls[0][1]["content"] and "(-1.8%)" not in copier.calls[0][1]["content"])

    inventor = _CopyingSummaryModel(extra=" It could reach 999.9K.")
    attempts, raised = author(narrated, inventor)
    check("narrated: an unsupported figure gets one repair, then gives way to the fallback",
          raised and len(inventor.calls) == 2 and [a["outcome"] for a in attempts] == ["rejected"] * 2,
          attempts)
    repair = inventor.calls[1][-1]["content"]
    check("narrated: that one repair is the final correction, and re-lists the signed statement",
          "final correction" in repair and "(-1.8%)" in repair and "(1.8%)" not in repair, repair)

    system = copier.calls[0][0]["content"]  # investigated
    probe = _CopyingSummaryModel()
    author(narrated, probe)
    narrated_system = probe.calls[0][0]["content"].casefold()
    missing = sorted(p for p in summary_validation._TECHNICAL_MANAGER_PHRASES if p not in narrated_system)
    check("narrated: the prompt names every phrase the check rejects, uplift included",
          not missing and "uplift" in narrated_system, missing)
    check("investigated: gains no rejected-words block", "# WORDS THE CHECK REJECTS" not in system)

    allowed = [2.7, -1.794, 5.0]
    check("a figure the check already accepts is left exactly as written",
          generator._copyable_text("up 2.7% and down (-1.8%) and +5.0%", allowed)
          == "up 2.7% and down (-1.8%) and +5.0%")
    check("a figure neither sign supports is left for the check to reject",
          generator._copyable_text("a 9.9% move", allowed) == "a 9.9% move")

    run = fresh_summary_generator_run_with(generator, dict(
        narrated, summary_r4_enabled=True, summary_candidates=[candidate], summary_novelty={},
        summary_overall_performance={}, summary_selected_focuses=[], summary_focus_evidence_by_key={}),
        _CopyingSummaryModel(extra=" It could reach 999.9K."))
    summary = run.get("fresh_summary") or {}
    check("narrated: after the one repair fails, the page is the grounded fallback",
          summary.get("authoring_mode") == "deterministic_fallback", summary.get("authoring_mode"))
    check("and the published fallback keeps its own display, unsigned percentage and all",
          "(1.8%)" in json.dumps(summary.get("content_blocks")), summary.get("content_blocks"))


def fresh_summary_generator_run_with(generator, state: dict, model) -> dict:
    original = generator.get_llm
    generator.get_llm = lambda *_a, **_k: model  # type: ignore[assignment]
    try:
        return generator.run(state)
    finally:
        generator.get_llm = original  # type: ignore[assignment]


def main() -> int:
    print("=" * 72)
    print("report_ai_tier: investigated, narrated and deterministic")
    print("=" * 72)
    (PROJECT_ROOT / OUT).mkdir(parents=True, exist_ok=True)
    test_rejected_drafts_leave_their_reasons()
    test_narrated_summary_passes_first_time()
    test_snapshot_investigation_keeps_drills_without_a_model()
    test_standalone_prose_writers_return_their_draft()
    test_standalone_kpi_cards_read_the_tier_from_config()
    test_narrated_decides_nothing()
    test_narrated_key_insights_are_checked_slot_by_slot()
    test_narrated_report_end_to_end()
    test_narrated_standalone_reports()

    test_the_dial()
    test_default_tier_still_reaches_the_model()
    test_planning_calls_no_model()
    test_signal_selection_calls_no_model()
    test_investigation_calls_no_model()
    test_report_calls_no_model_and_passes_clarity()
    test_kpi_cards_call_no_model()
    test_a_share_above_the_whole_change()
    test_stores_sharing_a_lever_pattern()
    test_overall_headline()

    print("\n" + "=" * 72)
    if _failures:
        print(f"AI TIER FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
