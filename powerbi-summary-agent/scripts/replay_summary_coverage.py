"""Offline replay: full-coverage ranked tables + the report navigation shell.

Covers the "every store / department / section / category gets a line" surface:
the deterministic severity bands, the three-part rank blend, current-only
handling, the honest "no material change" count, coverage-only role isolation
(a store must never become a focus), and the rendered HTML shell (sticky TL;DR,
jump nav, collapsible levels, search box, print rules).

Also replays the REAL committed universe fixture when one is present, so the
math is exercised against actual scanned rows rather than only synthetic ones.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import summary_focus_universe  # noqa: E402
from src.tools import summary_coverage, summary_roles, summary_visual  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _member(name, current, prior, *, overall=1000.0, gross=None, signed=None, parent=None, full=4.0):
    change = None if (current is None or prior is None) else current - prior
    return {
        "member": name,
        "hierarchy_path": [name],
        "current": current,
        "prior": prior,
        "change": change,
        "change_pct": None if (change is None or not prior) else change / abs(prior) * 100.0,
        "business_share_pct": None if current is None else abs(current) / overall * 100.0,
        "global_impact_pct": None if change is None else abs(change) / overall * 100.0,
        "overall_current": overall,
        "gross_sibling_change": gross,
        "signed_sibling_change": signed,
        "parent_change": parent,
        "full_member_count": full,
    }


def _role(role, members, level=20):
    return {
        "role": role,
        "group_ref": f"'T'[{role}]",
        "column": role,
        "level": level,
        "status": "ok",
        "members": members,
        "metric_family": "revenue",
    }


# --- 1. severity, direction, comparability ------------------------------------
def test_bands() -> None:
    print("\n[1] Severity bands, direction and comparability")
    big_and_broad = _member("A", 300.0, 200.0)          # +50%, 30% share
    big_but_tiny = _member("B", 3.0, 2.0)               # +50%, 0.3% share, 0.1% impact
    broad_but_flat = _member("C", 400.0, 398.0)         # +0.5%, 40% share
    quiet = _member("D", 20.0, 20.2)                    # -1%, 2% share
    new_store = _member("E", 50.0, None)

    kw = {"material_change_pct": 10.0, "material_share_pct": 5.0}
    check("large move on a large area is critical",
          summary_coverage.severity(big_and_broad, **kw) == "critical")
    check("large move on a trivial area is only watch",
          summary_coverage.severity(big_but_tiny, **kw) == "watch",
          summary_coverage.severity(big_but_tiny, **kw))
    check("large area barely moving is only watch",
          summary_coverage.severity(broad_but_flat, **kw) == "watch")
    check("small move on a small area is steady",
          summary_coverage.severity(quiet, **kw) == "steady")
    check("current-only member is never critical",
          summary_coverage.severity(new_store, **kw) == "steady")

    check("direction up", summary_coverage.direction(5) == "up")
    check("direction down", summary_coverage.direction(-5) == "down")
    check("direction flat on zero", summary_coverage.direction(0) == "flat")
    check("direction flat on None", summary_coverage.direction(None) == "flat")
    check("comparable requires both sides", summary_coverage.is_comparable(big_and_broad))
    check("current-only is not comparable", not summary_coverage.is_comparable(new_store))


# --- 2. unexpectedness --------------------------------------------------------
def test_unexpectedness() -> None:
    print("\n[2] Unexpectedness = divergence from the peer median")
    # Three members fall ~10%; one grows. The grower is the unexpected one even
    # though its absolute percentage move is the same size as its peers'.
    members = [
        _member("A", 90.0, 100.0),
        _member("B", 90.0, 100.0),
        _member("C", 89.0, 100.0),
        _member("D", 110.0, 100.0),
    ]
    median = summary_coverage.peer_median_change_pct(members)
    check("peer median is the declining consensus", median is not None and -11.0 < median < -9.0,
          str(median))
    surprise = [summary_coverage.unexpectedness_pts(m, median) for m in members]
    check("the grower diverges most", surprise[3] == max(x for x in surprise if x is not None))
    check("an in-line member diverges least", surprise[0] < surprise[3])
    check("current-only has no divergence",
          summary_coverage.unexpectedness_pts(_member("E", 5.0, None), median) is None)
    check("no comparable members yields no median",
          summary_coverage.peer_median_change_pct([_member("E", 5.0, None)]) is None)


# --- 3. ranking and counts ----------------------------------------------------
def test_role_coverage() -> None:
    print("\n[3] Per-level ranking, counts and complete coverage")
    members = [
        _member("Big mover", 700.0, 500.0),
        _member("Trivial swing", 2.0, 1.0),
        _member("Quiet giant", 900.0, 898.0),
        _member("New line", 40.0, None),
        _member("Steady", 30.0, 30.1),
    ]
    level = summary_coverage.build_role_coverage(
        "department", _role("department", members),
        material_change_pct=10.0, material_share_pct=5.0,
    )
    rows = level["rows"]
    check("every member is present - coverage is complete", len(rows) == len(members))
    check("ranks are 1..n contiguous", [r["rank"] for r in rows] == list(range(1, len(rows) + 1)))
    check("current-only sorts last", rows[-1]["member"] == "New line")
    check("the big mover outranks the trivial swing",
          [r["member"] for r in rows].index("Big mover")
          < [r["member"] for r in rows].index("Trivial swing"))

    counts = level["counts"]
    check("total counts every member", counts["total"] == 5)
    check("current_only counted separately", counts["current_only"] == 1)
    check("comparable excludes current-only", counts["comparable"] == 4)
    check("up + down + flat equals comparable",
          counts["up"] + counts["down"] + counts["flat"] == counts["comparable"])
    check("no_material_change mirrors steady",
          counts["no_material_change"] == counts["steady"])
    check("peer median recorded", level["peer_median_change_pct"] is not None)


# --- 4. universe -> coverage --------------------------------------------------
def test_build_coverage() -> None:
    print("\n[4] Building coverage from a universe, incl. failed roles")
    universe = {
        "status": "ok",
        "metric_family": "revenue",
        "value_aliases": {"current": "cur", "prior": "pri"},
        "roles": {
            "category": _role("category", [_member("Cat A", 300.0, 200.0)], level=30),
            "division": _role("division", [_member("Div A", 500.0, 400.0)], level=10),
            "store": {**_role("store", [_member("S1", 250.0, 240.0)], level=None),
                      "coverage_only": True},
            "department": {**_role("department", [], level=20), "status": "budget_exhausted"},
        },
    }
    coverage = summary_coverage.build_coverage(universe)
    roles = [level["role"] for level in coverage["levels"]]
    check("failed role is not silently dropped", coverage["skipped_roles"].get("department") == "budget_exhausted")
    check("failed role produces no level", "department" not in roles)
    check("levels sort broad -> narrow, unlevelled last",
          roles == ["division", "category", "store"], str(roles))
    check("coverage_only flag survives",
          next(l for l in coverage["levels"] if l["role"] == "store")["coverage_only"] is True)
    check("thresholds are recorded", coverage["thresholds"]["material_change_pct"] == 10.0)
    check("weights sum to 1",
          abs(sum(coverage["weights"].values()) - 1.0) < 1e-9)
    check("empty universe reports no_coverage",
          summary_coverage.build_coverage({"roles": {}})["status"] == "no_coverage")

    movers = summary_coverage.top_movers(coverage, limit=5)
    check("top movers carry their level", all(m.get("role") for m in movers))
    check("top movers exclude steady rows",
          all(m["severity"] != "steady" for m in movers))
    check("top movers respect the limit",
          len(summary_coverage.top_movers(coverage, limit=1)) <= 1)


# --- 4b. anti-noise guards ----------------------------------------------------
def test_noise_guards() -> None:
    print("\n[4b] Mirror collapse, magnitude ceiling, headline floor")

    # (a) A level that duplicates a broader one is collapsed, not reported twice.
    same = [_member("FASHION", 500.0, 400.0), _member("FMCG", 900.0, 880.0)]
    universe = {
        "status": "ok",
        "roles": {
            "division": _role("division", [dict(m) for m in same], level=10),
            "department": _role("department", [dict(m) for m in same], level=20),
            "category": _role("category", [_member("Shirts", 200.0, 150.0)], level=30),
        },
    }
    coverage = summary_coverage.build_coverage(universe)
    roles = [level["role"] for level in coverage["levels"]]
    check("a mirrored level is not reported twice", roles == ["division", "category"], str(roles))
    check("the BROADER level survives the collapse", "division" in roles)
    check("the collapse is auditable",
          coverage["mirrored_roles"].get("department") == "division")
    check("collapse can be turned off",
          len(summary_coverage.build_coverage(universe, collapse_mirrors=False)["levels"]) == 3)
    check("a genuinely different level is kept", "category" in roles)
    # Same member names but different values is NOT a mirror.
    differing = {
        "status": "ok",
        "roles": {
            "division": _role("division", [dict(m) for m in same], level=10),
            "department": _role("department", [_member("FASHION", 250.0, 200.0),
                                               _member("FMCG", 450.0, 440.0)], level=20),
        },
    }
    check("different values are not treated as a mirror",
          len(summary_coverage.build_coverage(differing)["levels"]) == 2)

    # (b) One freak percentage must not flatten every other member's magnitude.
    members = [
        _member("Freak", 22.0, 1.0),        # +2100%, trivial in absolute terms
        _member("Real mover", 700.0, 500.0),  # +40% on a big base
        _member("Mid", 300.0, 250.0),
    ]
    level = summary_coverage.build_role_coverage(
        "category", _role("category", members),
        material_change_pct=10.0, material_share_pct=5.0,
    )
    order = [row["member"] for row in level["rows"]]
    check("the real mover outranks the freak percentage",
          order.index("Real mover") < order.index("Freak"), str(order))

    # (c) A trivial absolute move cannot headline, but is still covered.
    tiny_universe = {
        "status": "ok",
        "roles": {
            "division": _role("division", [
                _member("Trivial", 0.6, 4.0, overall=100000.0),   # -85%, ~0 impact
                _member("Solid", 30000.0, 26000.0, overall=100000.0),
            ], level=10),
        },
    }
    tiny_cov = summary_coverage.build_coverage(tiny_universe)
    movers = summary_coverage.top_movers(tiny_cov, limit=5)
    check("the trivial mover is excluded from the headline",
          all(m["member"] != "Trivial" for m in movers), str([m["member"] for m in movers]))
    check("the solid mover headlines", any(m["member"] == "Solid" for m in movers))
    check("the trivial mover is STILL covered in its level",
          any(row["member"] == "Trivial" for row in tiny_cov["levels"][0]["rows"]))
    # If the floor would empty the headline, fall back rather than go blank.
    only_trivial = summary_coverage.build_coverage({
        "status": "ok",
        "roles": {"division": _role("division", [
            _member("Trivial", 0.6, 4.0, overall=100000.0)], level=10)},
    })
    check("headline falls back rather than rendering empty",
          len(summary_coverage.top_movers(only_trivial, limit=5)) == 1)


# --- 5. role vocabulary + coverage-only isolation ------------------------------
def test_roles() -> None:
    print("\n[5] Role vocabulary: Section added, Store coverage-only")
    check("section sits between department and category",
          summary_roles.hierarchy_level("department")
          < summary_roles.hierarchy_level("section")
          < summary_roles.hierarchy_level("category"))
    check("section is a default focus role",
          "section" in summary_roles.DEFAULT_ALLOWED_ROLES)
    check("store has NO hierarchy depth (orthogonal to merchandise)",
          summary_roles.hierarchy_level("store") is None)
    check("store is a default coverage role",
          "store" in summary_roles.DEFAULT_COVERAGE_ROLES)
    check("store can never be a primary focus",
          not summary_roles.is_primary_focus_role("store", "store_no", {}))
    check("section can be a primary focus",
          summary_roles.is_primary_focus_role("section", "sec", {}))
    check("coverage roles default to a superset of focus roles",
          set(summary_roles.DEFAULT_ALLOWED_ROLES) <= set(summary_roles.DEFAULT_COVERAGE_ROLES))
    check("config can override coverage roles",
          summary_roles.coverage_roles({"summary_coverage_roles": ["store"]}) == ("store",))

    from src.agents.summary_focus_evidence import _semantic_level

    check("a 'sec' column resolves to section", _semantic_level("sec")[1] == "section")
    check("a 'SECTION' column resolves to section", _semantic_level("SECTION")[1] == "section")
    check("'sector' does not false-match section", _semantic_level("sector")[1] != "section")
    check("department still resolves", _semantic_level("dep")[1] == "department")
    check("special product group still wins over product group",
          _semantic_level("special_product_group_name")[1] == "special_product_group")


def test_candidate_isolation() -> None:
    print("\n[6] Coverage-only roles never enter the focus rotation")
    from src.agents import summary_candidate_builder

    state = {
        "summary_r4_enabled": True,
        "summary_focus_universe": {
            "status": "ok",
            "metric_family": "revenue",
            "roles": {
                "division": _role("division", [_member("Div A", 500.0, 400.0)], level=10),
                "store": {**_role("store", [_member("S1", 250.0, 240.0)]), "coverage_only": True},
            },
        },
        "semantic_model_profile": {},
        "config": {},
    }
    built = summary_candidate_builder._universe_member_candidates(state, "ds-fixture", "2026-06")
    roles_seen = {str(c.get("dimension_role") or c.get("role") or "") for c in built}
    check("a focus-eligible role produces candidates", len(built) > 0)
    check("no store candidate is produced", "store" not in roles_seen, str(roles_seen))
    check("no candidate mentions the store member",
          all("S1" not in json.dumps(c) for c in built))


# --- 7. rendering -------------------------------------------------------------
def test_render() -> None:
    print("\n[7] Rendered HTML shell")
    universe = {
        "status": "ok",
        "roles": {
            "store": {**_role("store", [
                _member("CFH014", 300.0, 200.0),
                _member("CFH017", 250.0, 249.0),
                _member("CFH022", 40.0, None),
            ]), "coverage_only": True},
            "department": _role("department", [
                _member(f"Dept {i}", 100.0 + i * 40, 100.0) for i in range(12)
            ], level=20),
        },
    }
    coverage = summary_coverage.build_coverage(universe)
    html = summary_visual.render(
        {"heading": "Test", "content_blocks": [
            {"kind": "paragraph", "heading": "Overall Performance", "text": "Revenue grew."},
        ]},
        title="Coverage test", coverage=coverage, coverage_display_rows=5,
    )
    check("jump nav is rendered", 'class="jump"' in html)
    check("nav links to each level", 'href="#cov-store"' in html and 'href="#cov-department"' in html)
    check("sticky TL;DR block present", 'class="tldr"' in html)
    check("search input present", 'class="report-search"' in html)
    check("levels are collapsible <details>", '<details class="coverage-level"' in html)
    check("severity badge rendered", "badge-critical" in html or "badge-watch" in html)
    check("overflow rows hidden behind Show the remaining",
          "Show the remaining" in html)
    check("all 12 departments still present in the document",
          all(f"Dept {i}" in html for i in range(12)))
    check("current-only member labelled honestly",
          "not comparable" in html and "no prior year" in html)
    check("search script emitted", "report-search" in html and "addEventListener('input'" in html)
    check("print hides the nav", "@media print" in html and ".jump,.report-search{display:none}" in html)
    check("narrative wrapper present", 'id="narrative"' in html)
    check("no coverage renders no coverage markup",
          'class="coverage"' not in summary_visual.render({"heading": "x"}, coverage={}))
    check("member names are HTML-escaped",
          "&lt;b&gt;" in summary_visual.render(
              {"heading": "x"},
              coverage=summary_coverage.build_coverage({
                  "status": "ok",
                  "roles": {"store": {**_role("store", [_member("<b>x</b>", 5.0, 4.0)]),
                                      "coverage_only": True}},
              }),
          ))


# --- 8. real fixture ----------------------------------------------------------
def test_real_fixture() -> None:
    print("\n[8] Real committed universe fixture")
    fixture = PROJECT_ROOT / "outputs_r4_acceptance" / "summary_focus_universe.json"
    if not fixture.exists():
        print("  [SKIP] no committed universe fixture found")
        return
    universe = json.loads(fixture.read_text(encoding="utf-8"))
    coverage = summary_coverage.build_coverage(universe)
    check("fixture produces coverage", coverage["status"] == "ok")
    for level in coverage["levels"]:
        counts = level["counts"]
        check(
            f"{level['role']}: counts reconcile to the member list",
            counts["comparable"] + counts["current_only"] == counts["total"] == len(level["rows"]),
            f"{counts}",
        )
        check(
            f"{level['role']}: every row has a severity band",
            all(row["severity"] in summary_coverage.SEVERITY_ORDER for row in level["rows"]),
        )
        check(
            f"{level['role']}: comparable rows are ranked above current-only",
            [row["comparable"] for row in level["rows"]]
            == sorted([row["comparable"] for row in level["rows"]], reverse=True),
        )
    html = summary_visual.render({"heading": "Fixture"}, coverage=coverage)
    check("fixture renders without error", len(html) > 2000)
    print(f"  ... levels: {[ (l['role'], l['counts']['total']) for l in coverage['levels'] ]}")


def main() -> int:
    print("=" * 72)
    print("REPLAY: summary full-coverage tables + report shell")
    print("=" * 72)
    test_bands()
    test_unexpectedness()
    test_role_coverage()
    test_build_coverage()
    test_noise_guards()
    test_roles()
    test_candidate_isolation()
    test_render()
    test_real_fixture()
    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
