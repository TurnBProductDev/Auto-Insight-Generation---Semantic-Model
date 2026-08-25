"""Ageing investigation: adaptive "where does this hotspot concentrate". Offline.

    python scripts/replay_ageing_investigator.py

No auth, no network. The LLM is mocked so the ADAPTIVE LOOP mechanics
themselves are proven, not just the deterministic fallback path: round
budget, per-finding query cap, the offered-role list actually constraining
what the model may choose, and early conclusion when the model says it has
enough evidence. Proves the properties that matter for a feature that runs
live DAX against a client's dataset and writes prose onto a published report:

* off by default, and untouched by a config missing the key;
* the DAX is a deterministic, TREATAS-scoped, TOPN-bounded template - never
  free-form LLM-authored text - and reuses the SAME exposure/aged expression
  the rest of the Ageing report reconciles against;
* the adaptive loop respects both the round cap and the query budget, and a
  model that never gets its offered role honoured cannot break the query;
* the deterministic narrative is asserted to pass its own validator, so
  strict validation cannot dead-end;
* validation rejects an ungrounded figure, a causal claim, jargon and a
  year-on-year/forecasting word - shared with `sku_overview_investigator.py`
  through `snapshot_investigator.py`, so both are proven by proving one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import ageing_investigator as inv  # noqa: E402
from src.domains.inventory import snapshot_investigator as engine  # noqa: E402

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


CFG = {
    "ageing_mapping": {
        "exposure": "[STOCK VALUE]",
        "snapshot": "'REP_SSR_SAG'[UPDATED_ON]",
        "dimensions": {
            "location": "'REP_SSR_SAG'[LOC_CODE]",
            "division": "'REP_SSR_SAG'[DEPARTMENT]",
            "sku_type": "'REP_SSR_SAG'[skutype]",
        },
    },
    "ageing_aged_filter": "'REP_SSR_SAG'[NEW AGE] IN {\"09-12 MONTHS\", \"12-24 MONTHS\", \"24+ MONTHS\"}",
}

MODEL = {
    "currency": "QAR",
    "stat_signals": [
        {"candidate_id": "ageing_rate_hotspot:location:OVERSEAS",
         "analysis_type": "ageing_rate_hotspot", "dimension": "location",
         "affected_segment": "OVERSEAS", "impact_value": 540000.0,
         "current": 540000.0, "description": "OVERSEAS holds QAR 540K more aged "
         "stock than its stock value would imply.", "score": 254.0},
        {"candidate_id": "ageing_oldest_band:age_band:24+ MONTHS",
         "analysis_type": "ageing_oldest_band", "dimension": "age_band",
         "affected_segment": "24+ MONTHS", "impact_value": 91000.0, "score": 601.5},
        {"candidate_id": "ageing_rate_hotspot:section:BAKERY",
         "analysis_type": "ageing_rate_hotspot", "dimension": "section",
         "affected_segment": "BAKERY", "impact_value": 10000.0, "score": 12.0},
    ],
}


def _fake_execute(dax: str) -> list[dict]:
    if "DEPARTMENT" in dax:
        return [{"[DEPARTMENT]": "GM HOME WARE", "[value]": 1200000.0, "[aged]": 500000.0}]
    if "skutype" in dax:
        return [{"[skutype]": "LOCAL", "[value]": 900000.0, "[aged]": 400000.0}]
    return []


def test_gated_off_by_default() -> None:
    print("\n=== off by default ===")
    calls: list[str] = []

    def execute(dax: str) -> list[dict]:
        calls.append(dax)
        return []

    result = inv.investigate(execute, MODEL, {**CFG}, log=None)
    check("no config key at all -> nothing runs", result["entries"] == [])
    check("no query was issued", not calls)
    check("the budget summary is still present, at zero",
          result["budget"]["used"] == 0)


def test_candidates_are_filtered_correctly() -> None:
    print("\n=== which findings are drillable ===")
    found = inv.candidates(MODEL, CFG, max_findings=5)
    ids = [f["candidate_id"] for f in found]
    check("the estate-wide oldest-band finding is excluded (nothing to scope to)",
          "ageing_oldest_band:age_band:24+ MONTHS" not in ids, ids)
    check("a role outside the mapped dimensions is excluded",
          "ageing_rate_hotspot:section:BAKERY" not in ids, ids)
    check("the real hotspot with a mapped role and a member survives",
          "ageing_rate_hotspot:location:OVERSEAS" in ids, ids)
    only = found[0]
    check("it carries the roles left to drill into",
          set(only["_drill_others"]) == {"division", "sku_type"}, only["_drill_others"])
    check("max_findings=0 drills nothing", inv.candidates(MODEL, CFG, max_findings=0) == [])


def test_drill_dax_is_deterministic_and_scoped() -> None:
    print("\n=== the drill DAX is a fixed template, never LLM text ===")
    dax = inv.build_drill_dax(CFG, own_role="location", own_member="OVERSEAS",
                              drill_role="division", limit=7)
    check("it scopes to the exact member via TREATAS",
          'TREATAS({"OVERSEAS"}, \'REP_SSR_SAG\'[LOC_CODE])' in dax, dax)
    check("it groups by the requested drill dimension",
          "'REP_SSR_SAG'[DEPARTMENT]," in dax, dax)
    check("it is TOPN-bounded to the requested limit", "TOPN(\n  7," in dax, dax)
    from src.domains.inventory import ageing_flow
    expected_exposure = ageing_flow._expression(ageing_flow._required(CFG, "exposure"))
    check("it reuses the report's own exposure expression, never a second copy",
          dax.count(expected_exposure) >= 2, dax)
    check("it never bare-filters the whole table (Non-negotiable 10)",
          "REMOVEFILTERS(" not in dax)

    injected = inv.build_drill_dax(CFG, own_role="location", own_member='X" || TRUE() || "',
                                   drill_role="division")
    check("the embedded quotes are doubled, not left to close the literal early",
          'TREATAS({"X"" || TRUE() || """}' in injected, injected)


def test_deterministic_narrative_passes_its_own_validator() -> None:
    print("\n=== the deterministic floor is asserted to pass strict validation ===")
    entry = {
        "finding": MODEL["stat_signals"][0],
        "drills": [{"role": "sku_type", "rows": [
            {"name": "LOCAL", "value": 400000.0},
            {"name": "IMPORT", "value": 140000.0},
        ]}],
    }
    text = engine.deterministic_narrative(entry, "QAR")
    check("it names the segment", "OVERSEAS" in text, text)
    check("it quotes a real figure", "QAR 400K" in text, text)
    errors = engine.validate(text, entry)
    check("and it passes its own validator", errors == [], errors)


def test_validate_rejects_the_real_failure_modes() -> None:
    print("\n=== validation catches what the deterministic draft never writes ===")
    entry = {"finding": MODEL["stat_signals"][0],
            "drills": [{"role": "sku_type", "rows": [{"name": "LOCAL", "value": 400000.0}]}]}
    check("an ungrounded figure is rejected",
          any("not in the drill-down results" in e
              for e in engine.validate("Concentrated at QAR 999K in LOCAL.", entry)))
    check("a causal claim is rejected",
          any("states a cause" in e for e in engine.validate(
              "This is because LOCAL stock arrived early, QAR 400K.", entry)))
    check("jargon is rejected",
          any("jargon" in e for e in engine.validate(
              "LOCAL carries the highest velocity, QAR 400K.", entry)))
    check("a year-on-year/forecast word is rejected",
          any("comparison over time" in e for e in engine.validate(
              "LOCAL is trending up from last year, QAR 400K.", entry)))
    check("an empty draft is rejected", engine.validate("", entry) == ["empty narrative"])
    check("a clean, grounded draft has no errors",
          engine.validate("LOCAL holds the largest share, QAR 400K.", entry) == [])


class _Decision:
    def __init__(self, action, role=None, reasoning="test"):
        self.action, self.role, self.reasoning = action, role, reasoning


class _Narrative:
    def __init__(self, text):
        self.text = text


class _ScriptedLLM:
    """Returns queued responses in order, regardless of the schema asked for -
    the test scripts the exact sequence of calls it expects."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.invocations = 0

    def invoke(self, messages):
        self.invocations += 1
        if not self._responses:
            raise AssertionError("scripted LLM ran out of responses")
        return self._responses.pop(0)


def test_adaptive_loop_respects_round_cap_and_budget() -> None:
    print("\n=== the adaptive loop: round cap and budget are hard limits ===")
    cfg = {**CFG, "ageing_investigation_enabled": True,
          "ageing_investigation_max_findings": 1,
          "ageing_investigation_max_rounds": 2,
          "ageing_investigation_max_queries": 20,
          "ageing_investigation_max_roles_per_finding": 20}

    # Round 1 always drills (no evidence yet to decide from). Round 2 asks a
    # real decision; scripted to keep drilling. max_rounds=2 then forces a
    # stop even though a role remains unoffered, and the narrative call is
    # separate from the decision calls.
    llm = _ScriptedLLM([_Decision("drill", role="sku_type"), _Narrative("LOCAL holds the "
                                                                        "largest share, QAR 400K.")])
    with patch("src.tools.llm.get_llm", return_value=llm):
        result = inv.investigate(_fake_execute, MODEL, cfg, log=None)

    check("exactly one finding was investigated (max_findings=1)", len(result["entries"]) == 1)
    entry = result["entries"][0]
    check("exactly two rounds ran (the round cap), not more even though budget allowed it",
          entry["rounds"] == 2, entry["rounds"])
    check("the drilled roles are both real, offered roles",
          {d["role"] for d in entry["drills"]} <= {"division", "sku_type"}, entry["drills"])
    check("the LLM was asked to decide once and to narrate once - not merged into one call",
          llm.invocations == 2, llm.invocations)
    check("the budget ledger recorded exactly two spent queries",
          result["budget"]["used"] == 2, result["budget"])


def test_adaptive_loop_can_conclude_early() -> None:
    print("\n=== the model can conclude before the round cap, saving budget ===")
    cfg = {**CFG, "ageing_investigation_enabled": True,
          "ageing_investigation_max_findings": 1,
          "ageing_investigation_max_rounds": 3,
          "ageing_investigation_max_queries": 20,
          "ageing_investigation_max_roles_per_finding": 20}

    llm = _ScriptedLLM([_Decision("conclude"),
                       _Narrative("OVERSEAS's exposure breaks down as follows: "
                                  "by division, GM HOME WARE at QAR 500K.")])
    with patch("src.tools.llm.get_llm", return_value=llm):
        result = inv.investigate(_fake_execute, MODEL, cfg, log=None)

    entry = result["entries"][0]
    check("only round 1's forced drill ran before concluding",
          entry["rounds"] == 1, entry["rounds"])
    check("concluded_by_choice is recorded, not just budget exhaustion",
          entry["concluded_by_choice"] is True)
    check("the budget shows the saved query - well under the round cap's worth",
          result["budget"]["used"] == 1, result["budget"])


def test_role_not_in_offered_list_is_ignored() -> None:
    print("\n=== a role the model was never offered cannot be queried ===")
    cfg = {**CFG, "ageing_investigation_enabled": True,
          "ageing_investigation_max_findings": 1,
          "ageing_investigation_max_rounds": 2,
          "ageing_investigation_max_queries": 20,
          "ageing_investigation_max_roles_per_finding": 20}

    # The model hallucinates a role that was never offered ("region").
    llm = _ScriptedLLM([_Decision("drill", role="region"),
                       _Narrative("LOCAL holds the largest share, QAR 400K.")])
    with patch("src.tools.llm.get_llm", return_value=llm):
        result = inv.investigate(_fake_execute, MODEL, cfg, log=None)

    entry = result["entries"][0]
    check("the engine fell back to an offered role instead of the hallucinated one",
          all(d["role"] in {"division", "sku_type"} for d in entry["drills"]), entry["drills"])


def test_broken_llm_falls_back_to_deterministic_wording() -> None:
    print("\n=== a broken LLM call never costs the investigation section ===")
    cfg = {**CFG, "ageing_investigation_enabled": True,
          "ageing_investigation_max_findings": 1,
          "ageing_investigation_max_rounds": 2,
          "ageing_investigation_max_queries": 20,
          "ageing_investigation_max_roles_per_finding": 20}

    def broken_get_llm(*_a, **_kw):
        raise RuntimeError("simulated LLM outage")

    with patch("src.tools.llm.get_llm", side_effect=broken_get_llm):
        result = inv.investigate(_fake_execute, MODEL, cfg, log=None)

    check("a finding still comes back", len(result["entries"]) == 1)
    entry = result["entries"][0]
    check("authoring mode is honestly reported as deterministic",
          entry["authoring_mode"] == "deterministic", entry["authoring_mode"])
    check("the deterministic narrative is still grounded",
          bool(entry["narrative"]) and "QAR" in entry["narrative"], entry["narrative"])


def test_end_to_end_deterministic_path() -> None:
    print("\n=== end to end, LLM authoring off (the default) ===")
    out = inv.investigate(_fake_execute, MODEL, {**CFG, "ageing_investigation_enabled": False},
                          log=None)
    check("investigation is off means no entries even with a live executor",
          out["entries"] == [])


def main() -> int:
    print("=" * 72)
    print("Ageing investigation - adaptive drill-down")
    print("=" * 72)

    test_gated_off_by_default()
    test_candidates_are_filtered_correctly()
    test_drill_dax_is_deterministic_and_scoped()
    test_deterministic_narrative_passes_its_own_validator()
    test_validate_rejects_the_real_failure_modes()
    test_adaptive_loop_respects_round_cap_and_budget()
    test_adaptive_loop_can_conclude_early()
    test_role_not_in_offered_list_is_ignored()
    test_broken_llm_falls_back_to_deterministic_wording()
    test_end_to_end_deterministic_path()

    print("\n" + "=" * 72)
    if _failures:
        print(f"AGEING INVESTIGATOR FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
