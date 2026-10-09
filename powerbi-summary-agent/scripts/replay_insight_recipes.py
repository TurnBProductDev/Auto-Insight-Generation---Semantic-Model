"""The recipe shelf: tested queries the reasoned tier's model asks for by name.

    python scripts/replay_insight_recipes.py

Offline - no auth, no LLM, no network. Power BI is a fake executor.

`src/agents/insight_recipes.py` turns a recipe name and its arguments into a
validated, scoped, cached query (`docs/reasoned-tier-implementation-plan.md`,
Phase 2). What this file has to prove, in order of how badly each would hurt if
it were wrong:

1. **A recipe can never leave the comparable population.** Every query that is
   not about a store itself carries the population filter, read from the DAX
   text - and a builder that drops it is caught, here and by the validator.
2. **Every recipe builds DAX the validators accept**, on two committed live
   models and every fixture model that has a value to query.
3. **A model cannot fish.** Unknown levels, members it was never shown, a trend
   on a model with no validated time axis: refused with a reason, before
   Power BI, at no cost.
4. **The same question is paid for once**, including one the gap scan already
   asked.
5. **The units-versus-price split adds up** exactly to the change it explains.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import insight_recipes as recipes  # noqa: E402
from src.agents import insight_scan_templates as tpl  # noqa: E402
from src.agents import semantic_profiler  # noqa: E402
from src.agents.dax_validator import validate_one  # noqa: E402
from src.agents.evidence_contract import dax_hash  # noqa: E402
from src.agents.scope_validator import validate_comparable_scope  # noqa: E402

LIVE_RUNS = ("outputs_r4_acceptance", "outputs_scanb")
FIXTURE_MODELS = PROJECT_ROOT / "tests" / "fixtures" / "models"
VOCABULARY = {"success", "cache_hit", "cache_hit_failed", "rejected", "budget_refused", "failed",
              "unavailable", "not_found"}

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines()[:12]:
            print(f"         {line}")
    _failures.append(label)


# ------------------------------------------------------------------- fixtures


def _load(folder: str, name: str):
    return json.loads((PROJECT_ROOT / folder / f"{name}.json").read_text(encoding="utf-8"))


def live_state(folder: str) -> dict:
    """The insight branch's state at the investigator, from a committed run."""
    scope = _load(folder, "resolved_entity_scope")
    return {
        "semantic_model_profile": _load(folder, "semantic_model_profile"),
        "model_metadata": _load(folder, "model_metadata"),
        "resolved_entity_scope": scope,
        "insight_comparable_population": scope.get("active_comparable_population") or [],
        "insight_excluded_entities": scope.get("excluded_from_comparison") or [],
        "insight_clean_data": _load(folder, "insight_clean_data"),
        "insight_evidence_contracts": _load(folder, "insight_evidence_contracts"),
        "insight_evidence_briefs": _load(folder, "insight_evidence_briefs"),
        "insight_gap_evidence": _load(folder, "insight_gap_evidence"),
        "insight_temporal_verdict": _load(folder, "insight_temporal_verdict"),
        "insight_signals": _load(folder, "insight_signals"),
        "workspace_id": "ws", "dataset_id": "ds", "pbi_token": "pre-fetched-token",
    }


def _aliases(profile: dict) -> list[str]:
    shape = tpl.shape_from_profile(profile, {})
    return [s["alias"] for s in tpl._metric_specs(shape)] if shape else []


def fixture_state(path: Path) -> dict | None:
    """A synthetic investigator state over a fixture model, or None when the
    profiler finds no value to query (the snapshot fixture, by design)."""
    md = json.loads(path.read_text(encoding="utf-8"))
    profile = semantic_profiler.build_profile(md)
    if not profile.get("primary_value_bundle"):
        return {"semantic_model_profile": profile, "model_metadata": md, "_no_primary": True}
    entity = profile.get("entity_dimension")
    population = ["P1", "P2", "P3"] if entity else []
    state = {"semantic_model_profile": profile, "model_metadata": md,
             "insight_comparable_population": population,
             "resolved_entity_scope": {"entity_dimension": entity,
                                       "active_comparable_population": population,
                                       "excluded_from_comparison": ["X9"] if entity else []},
             "workspace_id": "ws", "dataset_id": "ds", "pbi_token": "pre-fetched-token"}
    times = profile.get("time_dimensions") or []
    month = next((d for d in times if "month" in str(d.get("column")).lower()), times[0] if times else None)
    state["insight_temporal_verdict"] = ({"enabled": True, "column": month["reference"]} if month
                                         else {"enabled": False, "reason": "no time axis"})
    names = recipes.levels(state)
    own = next((d for d in names.values() if d is not entity), None)
    if own is None:
        return None
    signal = {"id": "fixture_finding", "affected_segment": "SEG A", "evidence_query": "fixture_scan"}
    rows = []
    for label, dim in names.items():
        member = "P1" if dim is entity else f"{label.upper()} ONE"
        rows.append({dim["column"]: member, **{a: 100.0 + i for i, a in enumerate(_aliases(profile))}})
    state.update({
        "insight_signals": [signal],
        "insight_gap_evidence": {"fixture_finding": {"segment": "SEG A", "segment_dimension": own,
                                                     "evidence": {}}},
        "insight_clean_data": {"queries": [{"query_name": "fixture_scan", "rows": rows}]},
        "insight_evidence_contracts": {}, "insight_evidence_briefs": {},
    })
    return state


def all_states() -> list[tuple[str, dict]]:
    out = [(folder, live_state(folder)) for folder in LIVE_RUNS]
    for path in sorted(FIXTURE_MODELS.glob("*.json")):
        state = fixture_state(path)
        if state is not None:
            out.append((f"fixture:{path.stem}", state))
    return out


def calls(state: dict, signal: dict) -> list[tuple[str, dict, bool]]:
    """Every recipe call worth building on this model: (recipe, args, segment is a store)."""
    names = recipes.levels(state)
    entity_ref = ((state["semantic_model_profile"].get("entity_dimension")) or {}).get("reference")
    evidence = recipes.finding_evidence(state, signal)
    members: dict[str, str] = {}
    for label, seen in recipes._members_seen(state, evidence).items():
        members.setdefault(label, seen[0])
    own_dim, _ = recipes._own_segment(state, signal)
    own_name = recipes._level_name(state, own_dim)
    # A finding whose segment has no level (a run of periods) is refused for its
    # own segment - tested on its own - but its members can still be asked about.
    segments = ([(signal["affected_segment"], own_name, own_dim.get("reference") == entity_ref)]
                if own_dim else [])
    for label, member in members.items():
        if label != own_name:
            segments.append((member, label, names[label].get("reference") == entity_ref))
    out: list[tuple[str, dict, bool]] = []
    for segment, seg_level, is_store in segments:
        for by in names:
            if by != seg_level:
                out.append(("breakdown", {"segment": segment, "by": by}, is_store))
        out.append(("trend", {"segment": segment}, is_store))
    out += [("compare_to_peers", {"level": label}, False) for label in names]
    return out


#: Captured at import, so the mutation test below cannot blind the check it tests.
_POPULATION_FILTER = tpl._population_filter


def population_problem(dax: str, state: dict, is_store: bool, segment: str) -> str | None:
    """Why this DAX is not confined to the comparable population, read from the text."""
    profile = state["semantic_model_profile"]
    shape = tpl.shape_from_profile(profile, state)
    entity = shape.get("entity") or {}
    population = [str(v) for v in state.get("insight_comparable_population") or []]
    if is_store:
        wanted = f"TREATAS({{{tpl._typed_lit(segment, entity)}}}, {entity['reference']})"
        return None if wanted in dax else f"store segment filter {wanted} missing"
    wanted = _POPULATION_FILTER(shape, population)
    if wanted is None:
        return None  # no entity concept on this model: there is no population to filter to
    return None if wanted in dax else f"population filter {wanted} missing"


class FakePowerBI:
    """Returns two rows for any query and records every execution."""

    def __init__(self, fail: bool = False) -> None:
        self.executed: list[str] = []
        self.tokens: list = []
        self.fail = fail

    def __call__(self, workspace_id, dataset_id, queries, token=None):
        self.tokens.append(token)
        out = {}
        for q in queries:
            self.executed.append(q["dax"])
            out[q["name"]] = ({"status": "failed", "error": "the dataset timed out"} if self.fail else
                              {"status": "success", "result": {"results": [{"tables": [{"rows": [
                                  {"T[member]": "ROW ONE", "[value]": 2.0},
                                  {"T[member]": "ROW TWO", "[value]": 1.0}]}]}]}})
        return out


def with_executor(fake: FakePowerBI):
    original = recipes.pbi.execute_python
    recipes.pbi.execute_python = fake

    def restore():
        recipes.pbi.execute_python = original
    return restore


# ------------------------------------------------- 1 + 2. valid and population-scoped


def test_every_recipe_builds_valid_scoped_dax() -> None:
    print("\n=== every recipe builds DAX the validators accept, inside the population ===")
    for label, state in all_states():
        if state.get("_no_primary"):
            refused = recipes.build("breakdown", {"segment": "x", "by": "y"}, state, {"id": "s"}, [])
            check(f"{label}: a model with no value to query refuses every recipe",
                  "no primary value" in str(refused.get("refused")), refused)
            continue
        built, invalid, unscoped = 0, [], []
        for signal in state["insight_signals"]:
            for name, args, is_store in calls(state, signal):
                result = recipes.build(name, args, state, signal)
                if "reuse" in result:
                    continue
                if "dax" not in result:
                    invalid.append((signal["id"], name, args, result.get("refused")))
                    continue
                built += 1
                reasons = validate_one(result["dax"], state["model_metadata"])
                reasons += validate_comparable_scope(result["dax"], state)
                if reasons:
                    invalid.append((signal["id"], name, args, reasons))
                problem = population_problem(result["dax"], state, is_store, args.get("segment", ""))
                if problem:
                    unscoped.append((signal["id"], name, args, problem))
        check(f"{label}: {built} recipe queries pass validate_one and validate_comparable_scope",
              built > 0 and not invalid, invalid[:5])
        check(f"{label}: every one carries the population filter, a store segment its own",
              not unscoped, unscoped[:5])

    state = live_state("outputs_r4_acceptance")
    signal = state["insight_signals"][0]
    peers = recipes.build("compare_to_peers", {"level": "store"}, state, signal)
    check("compare_to_peers reads the baseline's complete store breakdown instead of querying",
          peers.get("reuse") == "baseline_comparable_entities" and len(peers.get("rows") or []) == 4, peers)
    custom = recipes.build("custom_dax", {"dax": "EVALUATE ROW(\"x\", [net revenue CURRENT])"}, state, signal)
    check("custom_dax passes the model's own DAX through to the same validators",
          custom.get("dax", "").startswith("EVALUATE ROW") and custom.get("contract_hint") is None, custom)


# ------------------------------------------------------------------ 3. refusals


def test_refusals_cost_nothing() -> None:
    print("\n=== refusals: a reason each, nothing executed, nothing spent ===")
    state = live_state("outputs_r4_acceptance")
    signal = state["insight_signals"][0]
    fake = FakePowerBI()
    restore = with_executor(fake)
    try:
        cases = [
            ("an unknown level", "breakdown", {"segment": "CF-CONFECTIONERY", "by": "planet"}, "unknown level"),
            ("a segment never shown", "breakdown", {"segment": "CF-BAKERY", "by": "store"}, "neither this finding"),
            ("breaking a segment down by its own level", "breakdown",
             {"segment": "CF-CONFECTIONERY", "by": "item category"}, "already a member"),
            ("an unknown recipe", "pivot_everything", {}, "unknown recipe"),
            ("a split with no row to split", "split_units_vs_price", {"segment": "CF-BAKERY"}, "no single-level row"),
            ("custom DAX naming no real objects", "custom_dax",
             {"dax": "EVALUATE ROW(\"x\", [Imaginary Measure])"}, "unknown measure"),
            ("custom DAX reading a change measure outside the population", "custom_dax",
             {"dax": "EVALUATE ROW(\"x\", [revenue Growth])"}, "not provably filtered"),
        ]
        off = dict(state, insight_temporal_verdict={"enabled": False, "reason": "batch_load_date"})
        for label, name, args, reason in cases:
            budget = recipes.Budget(queries=2, custom_dax=1)
            cache: dict = {}
            entry = recipes.run(name, args, state, signal, cache, budget=budget)
            check(f"{label} is refused with its reason, at no cost",
                  entry.get("status") == "rejected" and reason in str(entry.get("reason"))
                  and entry.get("cost") == 0 and budget.queries == 2 and budget.custom_dax == 1
                  and not cache, entry)
        budget = recipes.Budget(queries=2)
        entry = recipes.run("trend", {"segment": "CF-CONFECTIONERY"}, off, signal, {}, budget=budget)
        check("trend is refused when the temporal gate validated no time axis, and says why",
              entry.get("status") == "rejected" and "batch_load_date" in str(entry.get("reason"))
              and budget.queries == 2, entry)
        menu = recipes.menu(off, signal)
        check("and the menu leaves trend out, with the reason",
              "trend" not in [r["name"] for r in menu["recipes"]]
              and "batch_load_date" in menu["unavailable"].get("trend", ""), menu["unavailable"])

        excluded = [{"source": "fixture", "within": None,
                     "rows": [{"store_no": "CFH022", "revenue Growth": 1.0}]}]
        entry = recipes.run("breakdown", {"segment": "CFH022", "by": "division"}, state, signal, {},
                            evidence=excluded, budget=recipes.Budget(queries=2))
        check("a store excluded from comparison is rejected by the scope validator, never run",
              entry.get("status") == "rejected" and entry.get("stage") == "validator"
              and "excluded" in str(entry.get("reason")), entry)

        budget = recipes.Budget(queries=0)
        entry = recipes.run("breakdown", {"segment": "CF-CONFECTIONERY", "by": "division"},
                            state, signal, {}, budget=budget)
        check("with no queries left the call is budget_refused before Power BI",
              entry.get("status") == "budget_refused" and entry.get("cost") == 0, entry)
        budget = recipes.Budget(queries=3, custom_dax=0)
        entry = recipes.run("custom_dax", {"dax": "EVALUATE ROW(\"x\", [net revenue CURRENT])"},
                            state, signal, {}, budget=budget)
        check("custom DAX past its own cap is budget_refused even with queries left",
              entry.get("status") == "budget_refused" and budget.queries == 3, entry)
        scanb = live_state("outputs_scanb")
        period = next(s for s in scanb["insight_signals"] if s.get("level") == "period")
        entry = recipes.run("breakdown", {"segment": period["affected_segment"], "by": "category"},
                            scanb, period, {}, budget=recipes.Budget(queries=2))
        check("a finding over a run of periods has no level to filter by, and is refused for it",
              entry.get("status") == "rejected" and "could not be resolved" in str(entry.get("reason")),
              entry)
        check("no refusal reached Power BI", fake.executed == [], fake.executed)
    finally:
        restore()

    menu = recipes.menu(state, signal, allow_custom_dax=False)
    check("the menu names levels in business words, no table or column references",
          menu["levels"] and not any("[" in n or "'" in n for n in menu["levels"]), menu["levels"])
    check("custom_dax can be left off the menu", "custom_dax" not in [r["name"] for r in menu["recipes"]])
    asked = menu["already_asked"]
    gap_columns = list(state["insight_gap_evidence"][signal["id"]]["evidence"])
    check("the menu lists the standard drill's breakdowns as already asked, in business names",
          len(asked) == len(gap_columns) and all(a["segment"] == signal["affected_segment"]
                                                 and a["by"] in menu["levels"] for a in asked), asked)
    restore = with_executor(FakePowerBI())
    try:
        seeded = {dax_hash(ev["dax"]): {"status": "success", "rows": ev["rows"], "dax": ev["dax"]}
                  for ev in state["insight_gap_evidence"][signal["id"]]["evidence"].values()}
        again = [recipes.run("breakdown", {"segment": a["segment"], "by": a["by"]}, state, signal,
                             dict(seeded)) for a in asked]
    finally:
        restore()
    check("and each one is exactly a cached gap-scan query, so the list is accurate",
          again and all(e.get("status") == "cache_hit" for e in again), [e.get("status") for e in again])
    check("the menu is small next to a model description",
          len(json.dumps(menu)) < 4000, len(json.dumps(menu)))


# ------------------------------------------------------------------ 4. the cache


def test_same_question_runs_once() -> None:
    print("\n=== the cache: one execution per question, gap-scan questions included ===")
    state = live_state("outputs_r4_acceptance")
    signal = state["insight_signals"][0]
    fake = FakePowerBI()
    restore = with_executor(fake)
    try:
        cache: dict = {}
        budget = recipes.Budget(queries=2)
        args = {"segment": "CF-CHOCOLATE", "by": "store"}
        first = recipes.run("breakdown", args, state, signal, cache, budget=budget)
        second = recipes.run("breakdown", args, state, signal, cache, budget=budget)
        check("the first call executes once and spends one query",
              first.get("status") == "success" and first.get("cost") == 1 and len(fake.executed) == 1, first)
        check("the same call again is a cache hit that spends nothing",
              second.get("status") == "cache_hit" and second.get("cost") == 0
              and budget.queries == 1 and len(fake.executed) == 1, second)
        check("and returns the same rows", second.get("rows") == first.get("rows"))
        check("execution uses the run's pre-fetched token", fake.tokens == ["pre-fetched-token"], fake.tokens)
        check("the cache entry is keyed by DAX hash and says where it came from",
              cache.get(dax_hash(first["dax"]), {}).get("source") == "recipe:breakdown")
        check("every trail entry is in the investigator's run_dax shape and vocabulary",
              all(e.get("tool") == "run_dax" and e.get("origin") == "recipe:breakdown"
                  and e.get("status") in VOCABULARY for e in (first, second)))

        # The gap scan already asked the finding's own segment by these levels.
        gap = state["insight_gap_evidence"][signal["id"]]
        seeded = {dax_hash(ev["dax"]): {"status": "success", "rows": ev["rows"], "dax": ev["dax"],
                                        "source": "gap_scan"}
                  for ev in gap["evidence"].values()}
        before = len(fake.executed)
        budget = recipes.Budget(queries=2)
        hits = [recipes.run("breakdown", {"segment": signal["affected_segment"],
                                          "by": recipes._level_name(state, {"reference": next(
                                              d["reference"] for d in recipes.levels(state).values()
                                              if d["column"] == column)})},
                            state, signal, dict(seeded), budget=budget)
                for column in gap["filled_dimensions"]]
        check(f"re-asking the {len(hits)} breakdowns the gap scan already ran costs nothing",
              hits and all(h.get("status") == "cache_hit" for h in hits)
              and len(fake.executed) == before and budget.queries == 2,
              [(h.get("args"), h.get("status")) for h in hits])
    finally:
        restore()

    broken = FakePowerBI(fail=True)
    restore = with_executor(broken)
    try:
        cache = {}
        args = {"segment": "CF-CHOCOLATE", "by": "division"}
        failed = recipes.run("breakdown", args, state, signal, cache, budget=recipes.Budget(queries=2))
        again = recipes.run("breakdown", args, state, signal, cache, budget=recipes.Budget(queries=2))
        check("a failed query is recorded as failed, with the error",
              failed.get("status") == "failed" and "timed out" in str(failed.get("error")), failed)
        check("and is not retried: the repeat is cache_hit_failed at no cost",
              again.get("status") == "cache_hit_failed" and again.get("cost") == 0
              and len(broken.executed) == 1, again)
    finally:
        restore()

    formula = recipes.run("measure_formula", {"names": ["revenue Growth", "Imaginary"]}, state, signal, {})
    check("measure_formula answers from metadata in the investigator's shape, for free",
          formula.get("tool") == "get_measure_definition" and formula.get("cost") == 0
          and formula.get("not_found") == ["Imaginary"]
          and formula.get("status") in ("success", "unavailable"), formula)


# ------------------------------------------------------------------ 5. the split


def test_split_reconciles() -> None:
    print("\n=== split_units_vs_price: the two effects add up to the change ===")
    state = live_state("outputs_r4_acceptance")
    signal = state["insight_signals"][0]
    evidence = recipes.finding_evidence(state, signal)
    primary = state["semantic_model_profile"]["primary_value_bundle"]["measures"]
    checked, bad = 0, []
    for table in evidence:
        for row in table["rows"]:
            labels = recipes._labels(row)
            if len(labels) != 1:
                continue
            member = next(iter(labels.values()))
            entry = recipes.run("split_units_vs_price", {"segment": member}, state,
                                {**signal, "decomposition": None}, {}, evidence=[table])
            if entry.get("status") != "success":
                continue
            change = row[primary["current"]] - row[primary["prior"]]
            for split in entry["splits"]:
                checked += 1
                total = split["volume_effect"] + split["rate_effect"]
                if not (split["reconciled"] and abs(total - change) <= 1e-6 * max(1.0, abs(change))
                        and abs(split["revenue_change"] - change) <= 1e-6 * max(1.0, abs(change))):
                    bad.append((member, split["driver"], total, change))
    check(f"units effect + revenue-per-unit effect = the revenue change, on {checked} split(s)",
          checked > 10 and not bad, bad[:5])
    entry = recipes.run("split_units_vs_price", {"segment": "CF-CHOCOLATE"}, state, signal, {})
    check("each split says which returned table it came from and what that table sits inside",
          entry.get("source", "").startswith("gap_scan:") and entry.get("within") == "CF-CONFECTIONERY"
          and entry.get("cost") == 0, entry)
    cross = [{"source": "cross", "within": None, "rows": [
        {"store_no": "CFH018", "division_name": "CF-FOOD",
         **{k: 10.0 for k in ("net revenue CURRENT", "net revenue PAST", "net qty CURRENT", "net qty PAST")}}]}]
    entry = recipes.run("split_units_vs_price", {"segment": "CFH018"}, state, signal, {}, evidence=cross)
    check("a row of two levels is not split as if it were one segment", entry.get("status") == "rejected", entry)


# ------------------------------------------------------------------ 6. mutation


def test_a_dropped_population_filter_is_caught() -> None:
    print("\n=== mutation: a builder that drops the population filter is caught ===")
    state = live_state("outputs_r4_acceptance")
    signal = state["insight_signals"][0]
    original = tpl._population_filter
    tpl._population_filter = lambda shape, population: None  # type: ignore[assignment]
    try:
        unscoped, trapped, rejected = 0, 0, 0
        for name, args, is_store in calls(state, signal):
            result = recipes.build(name, args, state, signal)
            if "dax" not in result or is_store:
                continue
            if population_problem(result["dax"], dict(state), False, "") is None:
                continue
            unscoped += 1
            # The builder still claims "comparable" in its hint; a validator
            # taking that word for it would let the query through.
            if not validate_comparable_scope(result["dax"], state, result["contract_hint"]):
                trapped += 1
            entry = recipes.run(name, args, state, signal, {}, budget=recipes.Budget(queries=5))
            rejected += entry.get("status") == "rejected" and entry.get("stage") == "validator"
    finally:
        tpl._population_filter = original  # type: ignore[assignment]
    check("the population check sees the missing filter", unscoped > 0, unscoped)
    check("a validator trusting the builder's hint would have passed them",
          trapped == unscoped, (trapped, unscoped))
    check("the recipe shelf rejects every one, because it validates the DAX without the hint",
          rejected == unscoped, (rejected, unscoped))


def main() -> int:
    print("=" * 72)
    print("insight recipes: the reasoned tier's query shelf")
    print("=" * 72)
    test_every_recipe_builds_valid_scoped_dax()
    test_refusals_cost_nothing()
    test_same_question_runs_once()
    test_split_reconciles()
    test_a_dropped_population_filter_is_caught()

    print("\n" + "=" * 72)
    if _failures:
        print(f"INSIGHT RECIPES FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
