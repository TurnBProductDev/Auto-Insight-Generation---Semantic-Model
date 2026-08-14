"""WP3: domain packages and the assembled graph. Offline - no auth, no LLM.

    python scripts/replay_domain_assembly.py

What must hold
--------------
1. **The assembled Sales-YoY graph is the fixed graph.** Same nodes, same edges,
   same conditional routing. If assembly drifts by one edge the pipeline changes
   shape without any output changing until it matters.
2. **The fork/join topology survives every variation.** A report that omits an
   optional node must still fan out to two branches and fan in through ONE
   joined edge - an ad-hoc edge into `save_outputs` can fire it twice
   (Non-negotiable 5).
3. **Two specs in one process do not share mutable state.**
4. **The two family vocabularies stay distinct.** They are not duplicates: 37 of
   56 real measure names classify differently. This pins the divergence so
   nobody "tidies" it into a behaviour change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src import domains  # noqa: E402
from src import graph as graph_module  # noqa: E402
from src.agents import semantic_profiler  # noqa: E402
from src.agents import summary_candidate_builder as candidate_builder  # noqa: E402
from src.domains.inventory import families as inventory_families  # noqa: E402
from src.domains.sales import families as sales_families  # noqa: E402
from src.domains.sales.reports import yoy_performance  # noqa: E402
from src.kernel import report as kernel_report  # noqa: E402
from src.kernel.aggregation import AggregationClass  # noqa: E402

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


def shape(app) -> tuple[set[str], set[tuple[str, str, bool]]]:
    """The graph as comparable data: node names and typed edges."""
    drawn = app.get_graph()
    nodes = {n for n in drawn.nodes if n not in ("__start__", "__end__")}
    edges = {(e.source, e.target, bool(e.conditional)) for e in drawn.edges}
    return nodes, edges


# --------------------------------------------------- 1. assembly == fixed graph


def test_assembled_matches_fixed() -> None:
    print("\n=== the assembled graph IS the fixed graph ===")

    fixed_nodes, fixed_edges = shape(graph_module.build_graph())
    check(f"the fixed graph has nodes and edges ({len(fixed_nodes)}/{len(fixed_edges)})",
          bool(fixed_nodes) and bool(fixed_edges))

    resolved = kernel_report.resolve(yoy_performance.SPEC, nodes=yoy_performance.NODES)
    built_nodes, built_edges = shape(graph_module.build_graph(resolved))

    check("assembling from the Sales-YoY spec gives the same NODES",
          built_nodes == fixed_nodes,
          f"only in spec: {sorted(built_nodes - fixed_nodes)}\n"
          f"only in fixed: {sorted(fixed_nodes - built_nodes)}")
    check("...and the same EDGES, including conditional routing",
          built_edges == fixed_edges,
          f"only in spec: {sorted(built_edges - fixed_edges)}\n"
          f"only in fixed: {sorted(fixed_edges - built_edges)}")

    check("the spec's node list matches the graph's registry exactly - so the "
          "two cannot drift",
          set(yoy_performance.NODES) == set(graph_module.NODE_FACTORIES),
          f"spec-only: {sorted(set(yoy_performance.NODES) - set(graph_module.NODE_FACTORIES))}\n"
          f"registry-only: {sorted(set(graph_module.NODE_FACTORIES) - set(yoy_performance.NODES))}")
    check("no report argument still yields the full default graph",
          graph_module.resolve_node_names(None) == tuple(graph_module.NODE_FACTORIES))


def test_topology_is_preserved() -> None:
    print("\n=== the fork/join topology (Non-negotiables 4 and 5) ===")

    _nodes, edges = shape(graph_module.build_graph())

    fan_out = {t for s, t, _ in edges if s == "understand_report"}
    check("understand_report fans out to BOTH branch heads",
          fan_out == {"plan_dax", "insight_normalize"}, f"{sorted(fan_out)}")

    into_save = {(s, c) for s, t, c in edges if t == "save_outputs"}
    barriers = {s for s, c in into_save if not c}
    conditional_in = {s for s, c in into_save if c}
    check("save_outputs is reached from exactly the two branch barriers",
          barriers == {"summary_branch_done", "insight_branch_done"},
          f"{sorted(barriers)}")
    check("...plus exactly one pre-fork fatal edge, and nothing else",
          conditional_in == {"read_metadata"}, f"{sorted(conditional_in)}")

    routers = {s for s, _t, c in edges if c}
    check("every conditional router is present",
          routers == {"read_metadata", "validate_dax", "normalize_results",
                      "summary_novelty_filter"},
          f"{sorted(routers)}")


def test_omitting_a_node() -> None:
    print("\n=== a report may omit an optional node ===")

    # R6's dashboard build is optional: a report that does not publish a
    # dashboard should not run it.
    without = tuple(n for n in yoy_performance.NODES if n != "summary_dashboard_build")
    resolved = kernel_report.resolve(
        yoy_performance.SPEC.evolve(report_id="sales_yoy_no_dashboard"), nodes=without)
    nodes, edges = shape(graph_module.build_graph(resolved))

    check("the omitted node is absent", "summary_dashboard_build" not in nodes)
    check("the chain re-links across the gap rather than dangling",
          ("fresh_summary_generator", "fresh_summary_validator", False) in edges,
          "expected fresh_summary_generator -> fresh_summary_validator")
    check("the branch still reaches its barrier",
          ("fresh_summary_validator", "summary_branch_done", False) in edges)

    into_save = {s for s, t, c in edges if t == "save_outputs" and not c}
    check("and the join still waits for BOTH branches",
          into_save == {"summary_branch_done", "insight_branch_done"},
          f"{sorted(into_save)}")

    # Several insight levels are independently disable-able.
    trimmed = tuple(n for n in yoy_performance.NODES
                    if n not in ("insight_recent_week", "insight_daily"))
    nodes2, edges2 = shape(graph_module.build_graph(
        kernel_report.resolve(yoy_performance.SPEC, nodes=trimmed)))
    check("omitting two consecutive insight nodes re-links across both",
          ("insight_business_day_source", "insight_evidence_catalog", False) in edges2)
    check("the insight branch still reaches its barrier",
          ("insight_synthesizer", "insight_branch_done", False) in edges2)


def test_omission_is_bounded() -> None:
    print("\n=== the topology itself cannot be omitted ===")

    for required in ("save_outputs", "summary_branch_done", "insight_normalize"):
        nodes = tuple(n for n in yoy_performance.NODES if n != required)
        try:
            graph_module.resolve_node_names(
                kernel_report.resolve(yoy_performance.SPEC, nodes=nodes))
            check(f"omitting {required} is refused", False, "no error raised")
        except ValueError as exc:
            check(f"omitting {required} is refused", "topology" in str(exc), str(exc))

    try:
        graph_module.resolve_node_names(
            kernel_report.resolve(yoy_performance.SPEC,
                                  nodes=yoy_performance.NODES + ("invented_node",)))
        check("an unknown node name is refused", False, "no error raised")
    except ValueError as exc:
        check("an unknown node name is refused", "no factory" in str(exc), str(exc))


def test_no_shared_state() -> None:
    print("\n=== two specs in one process do not share mutable state ===")

    a = kernel_report.resolve(
        yoy_performance.SPEC.evolve(report_id="report_a"), {"fact_table": "A"},
        nodes=yoy_performance.NODES)
    b = kernel_report.resolve(
        yoy_performance.SPEC.evolve(report_id="report_b"), {"fact_table": "B"},
        nodes=tuple(n for n in yoy_performance.NODES if n != "summary_dashboard_build"))

    check("each keeps its own identity",
          (a.report_id, b.report_id) == ("report_a", "report_b"))
    check("each keeps its own node set", len(a.nodes) != len(b.nodes))
    check("each keeps its own profile",
          a.profile["fact_table"] == "A" and b.profile["fact_table"] == "B")
    check("the shared source spec is unchanged by either",
          yoy_performance.SPEC.report_id == "sales_yoy")

    try:
        a.nodes = ()  # type: ignore[misc]
        check("a resolved report is frozen (both branches read it)", False,
              "assignment succeeded")
    except Exception:
        check("a resolved report is frozen (both branches read it)", True)

    try:
        a.profile["fact_table"] = "mutated"  # type: ignore[index]
        check("its profile is read-only too", False, "mutation succeeded")
    except TypeError:
        check("its profile is read-only too", True)

    # Building one graph must not disturb another already built.
    graph_a = shape(graph_module.build_graph(a))
    graph_b = shape(graph_module.build_graph(b))
    graph_a_again = shape(graph_module.build_graph(a))
    check("building b does not disturb a", graph_a == graph_a_again)
    check("a and b genuinely differ", graph_a != graph_b)


# ---------------------------------------------------------- 2. domain packages


def test_domains() -> None:
    print("\n=== domain registry ===")

    import src.domains.inventory  # noqa: F401  (registers)

    check("both domains are registered",
          set(domains.available()) >= {"sales", "inventory"},
          f"{domains.available()}")

    sales = domains.get("sales")
    check("sales declares the period-over-period spine",
          sales.supports_spine("period_over_period"))
    check("sales owns the retail vocabulary", sales.families is sales_families)

    inventory = domains.get("inventory")
    check("inventory declares the snapshot-vs-policy spine (WP4)",
          inventory.spines == ("snapshot_vs_policy",), f"{inventory.spines}")
    check("and NOT snapshot-vs-snapshot - neither live model has a prior "
          "snapshot for it to compare against",
          "snapshot_vs_snapshot" not in inventory.spines)
    check("inventory defaults to the change-free blends",
          set(inventory.blends) == {"severity_exposure_persistence", "tier_then_value"})
    check("a domain is frozen", _is_frozen(sales))

    try:
        domains.get("no_such_domain")
        check("an unknown domain raises", False, "no error raised")
    except KeyError:
        check("an unknown domain raises", True)


def _is_frozen(obj) -> bool:
    try:
        obj.name = "mutated"
        return False
    except Exception:
        return True


def test_family_vocabularies() -> None:
    print("\n=== the two sales vocabularies have ONE owner but stay distinct ===")

    check("the profiler re-sources its tokens from the domain",
          semantic_profiler._FAMILY_TOKENS is sales_families.PROFILER_FAMILY_TOKENS)
    check("...and its value families",
          semantic_profiler._VALUE_FAMILIES is sales_families.PROFILER_VALUE_FAMILIES)
    check("...and its priorities",
          semantic_profiler._FAMILY_PRIORITY is sales_families.PROFILER_FAMILY_PRIORITY)

    # The divergence is real and must not be "tidied" into a behaviour change.
    names = set()
    for name in ("outputs_scanb", "outputs_r4_acceptance"):
        path = PROJECT_ROOT / name / "model_metadata.json"
        if path.exists():
            names |= {m["name"] for m in
                      json.loads(path.read_text(encoding="utf-8"))["measures"]}
    disagreements = [
        n for n in names
        if semantic_profiler._family({"name": n})[0] != candidate_builder._family(n)
    ]
    check(f"the two classifiers still disagree on real names "
          f"({len(disagreements)} of {len(names)}) - they are NOT duplicates",
          len(disagreements) > 0)
    check("REV_CURRENT is the clearest case: revenue to one, performance to the "
          "other (the builder's set has 'revenue' but not 'rev')",
          semantic_profiler._family({"name": "REV_CURRENT"})[0] == "revenue"
          and candidate_builder._family("REV_CURRENT") == "performance")
    check("the family NAMES differ too, so they are not interchangeable",
          "margin" in sales_families.PROFILER_FAMILIES
          and "rate" in sales_families.CANDIDATE_FAMILIES
          and "margin" not in sales_families.CANDIDATE_FAMILIES)


def test_inventory_vocabulary() -> None:
    print("\n=== the inventory vocabulary (WP3 skeleton) ===")

    fam = inventory_families
    check("stock value is its own family, not 'revenue'",
          fam.family({"stock", "value"}) == "stock_value")
    check("a policy threshold is NOT mistaken for the value it governs",
          fam.family({"excess", "threshold", "days"}) == "policy",
          "EXCESS_THRESHOLD_DAYS contains both 'excess' and 'days'")
    check("burn-out days is cover, not a value",
          fam.family({"expected", "burnout", "days"}) == "cover")
    check("an unknown name falls back rather than guessing",
          fam.family({"zzz"}) == fam.DEFAULT_FAMILY)

    print("\n--- aggregation classes come from what the arithmetic showed ---")
    check("stock value is SEMI_ADDITIVE_LAST - the 4.03x measurement",
          fam.AGGREGATION["stock_value"] is AggregationClass.SEMI_ADDITIVE_LAST)
    check("damage is ADDITIVE - it is a flow, not a position",
          fam.AGGREGATION["damage"] is AggregationClass.ADDITIVE)
    check("cover is DURATION, so it is never summed or naively averaged",
          fam.AGGREGATION["cover"] is AggregationClass.DURATION)
    check("non-moving is ADDITIVE_WITHIN_LEVEL - one SKU at three stores",
          fam.AGGREGATION["non_moving"] is AggregationClass.ADDITIVE_WITHIN_LEVEL)
    check("a policy threshold is never summed",
          fam.AGGREGATION["policy"] is AggregationClass.NON_ADDITIVE_RATIO)

    print("\n--- direction: half these families are 'higher is worse' ---")
    check("more excess stock is bad news",
          fam.direction_is_good("excess", 100.0) is False)
    check("more stock value is good news", fam.direction_is_good("stock_value", 100.0) is True)
    check("less non-moving stock is good news",
          fam.direction_is_good("non_moving", -50.0) is True)
    check("no movement cannot be judged good or bad",
          fam.direction_is_good("excess", 0) is None)

    print("\n--- naming rules from the rulebooks ---")
    check("Burn-Out Days is the approved name", fam.APPROVED_NAMES["cover"] == "Burn-Out Days")
    check("'days of cover' is banned (BR-03)", "days of cover" in fam.BANNED_WORDS)
    check("'velocity' is banned in findings (BR-33/BR-25)",
          "velocity" in fam.BANNED_WORDS)
    check("the cover sentinel is recorded as a sentinel, not a number of days",
          fam.COVER_SENTINEL == 1000)
    check("the hierarchy runs Division > Section > Category > Brand > SKU",
          fam.HIERARCHY == ("division", "section", "category", "brand", "sku"))
    check("and records that the DEPARTMENT column actually means Division",
          fam.DIVISION_COLUMN == "DEPARTMENT" and fam.DIVISION_LABEL == "Division")


def test_resolve() -> None:
    print("\n=== resolve() binds a spec to a model ===")

    resolved = kernel_report.resolve(yoy_performance.SPEC, {"fact_table": "F"})
    check("the domain resolves", getattr(resolved.domain, "name", None) == "sales")
    check("the spine resolves to an instance",
          getattr(resolved.spine, "kind", None) == "period_over_period")
    check("identity is carried through", resolved.report_id == "sales_yoy")
    check("summary() is readable", "sales_yoy" in resolved.summary(), resolved.summary())

    # An inventory report must still resolve its identity before WP4 supplies a
    # spine - otherwise the domain could not be developed at all.
    spec = kernel_report.ReportSpec(
        report_id="inventory_ageing", report_name="Stock Age Analysis",
        domain="inventory", chain_id="inventory", spine="snapshot_vs_policy")
    partial = kernel_report.resolve(spec)
    check("an inventory report resolves its domain",
          getattr(partial.domain, "name", None) == "inventory")
    check("...and its spine, now that WP4 has written it",
          getattr(partial.spine, "kind", None) == "snapshot_vs_policy")
    check("...without losing its identity", partial.report_id == "inventory_ageing")

    # A spine a later WP has not written yet must still leave the report
    # resolvable, or the domain could not be developed incrementally.
    future = kernel_report.resolve(spec.evolve(spine="snapshot_vs_snapshot"))
    check("an unwritten spine leaves the report resolvable rather than failing",
          future.spine is None and future.report_id == "inventory_ageing")


def main() -> int:
    print("=" * 72)
    print("WP3 domain packages and assembled graph")
    print("=" * 72)

    test_assembled_matches_fixed()
    test_topology_is_preserved()
    test_omitting_a_node()
    test_omission_is_bounded()
    test_no_shared_state()
    test_domains()
    test_family_vocabularies()
    test_inventory_vocabulary()
    test_resolve()

    print("\n" + "=" * 72)
    if _failures:
        print(f"DOMAIN ASSEMBLY FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
