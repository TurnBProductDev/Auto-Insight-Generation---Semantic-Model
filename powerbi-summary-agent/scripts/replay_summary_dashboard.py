"""Offline replay: the R6 interactive dashboard.

Covers the pieces R6 adds on top of R1-R5, all deterministic:

* the three-lever spine - exact decomposition, multiplicative reconciliation,
  lever-state naming, growth quality, and the honest ``None`` when the model
  cannot supply all three inputs;
* measure-aware RAG bands, including the tougher band on real-demand measures
  and the refusal to pass an unmeasurable movement as green;
* the calendar/comparator check - the estate-wide signature, the configured
  event that names it, the exceptions it does not excuse, and the cases that
  must NOT fire;
* contributions that sum to the group move;
* movers ranked by the blended coverage score rather than raw percentage;
* per-entity stories that differ by situation, and the validation that catches
  boilerplate, invented figures, causal claims and internal vocabulary while
  still letting the deterministic fallback through;
* two time views, with the narrower one derived from the already-scanned trend
  at zero query cost;
* R6-off isolation - with the switch off the builder writes nothing;
* the rendered HTML shell: well-formed, self-contained, escaped, no storage APIs.

Also replays the REAL committed fixtures when present, so the arithmetic is
exercised against actually-scanned rows.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import html as html_lib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import summary_dashboard_builder  # noqa: E402
from src.tools import (  # noqa: E402
    summary_calendar,
    summary_coverage,
    summary_dashboard,
    summary_dashboard_html,
    summary_levers,
    summary_rag,
)
from src.tools.summary_validation import dashboard_rules  # noqa: E402

FAILURES: list[str] = []
OUT = PROJECT_ROOT / "outputs_replay"


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def _families(revenue, units, bills):
    def bundle(current, prior):
        change = current - prior
        return {
            "current": current, "prior": prior, "change": change,
            "change_pct": change / abs(prior) * 100.0 if prior else None,
            "comparison": "the same period last year",
        }
    out = {"revenue": bundle(*revenue)}
    if units:
        out["quantity"] = bundle(*units)
    if bills:
        out["transactions"] = bundle(*bills)
    return out


def _member(name, current, prior, *, overall=1_000_000.0, share=None, path=None):
    change = None if prior is None else current - prior
    return {
        "member": name,
        "hierarchy_path": path or [name],
        "current": current,
        "prior": prior,
        "change": change,
        "change_pct": None if (change is None or not prior) else change / abs(prior) * 100.0,
        "overall_current": overall,
        "business_share_pct": share if share is not None else current / overall * 100.0,
        "global_impact_pct": abs(change or 0.0) / overall * 100.0,
        "sibling_movement_impact_pct": 50.0,
        "gross_sibling_change": 100.0,
        "signed_sibling_change": 100.0,
        "parent_change": 100.0,
        "full_member_count": 4.0,
        "reconciled": True,
    }


def _universe(members, role="store", level=None, aliases=None):
    return {
        "status": "ok",
        "metric_family": "revenue",
        "value_aliases": aliases or {"current": "cur", "prior": "pri", "change": "chg"},
        "roles": {
            role: {
                "role": role, "group_ref": f"'T'[{role}]", "parent_refs": [],
                "column": role, "level": level, "status": "ok",
                "metric_family": "revenue", "members": members,
                "coverage_only": role == "store",
                "returned_member_count": len(members),
            }
        },
    }


# ---------------------------------------------------------------------------
def test_three_levers() -> None:
    print("\n[1] three-lever spine")
    families = _families((125_844_619.77, 122_819_915.62),
                         (18_611_367.74, 18_922_062.13),
                         (8_338_519.0, 8_125_232.0))
    bridge = summary_levers.three_lever_bridge(families)
    check("bridge produced", bridge is not None)
    effects = bridge["effects"]
    total = sum(effects.values())
    check("three effects sum to the revenue change",
          abs(total - bridge["revenue_change"]) < 1.0,
          f"{total} vs {bridge['revenue_change']}")
    check("growth factors multiply back to the revenue percentage",
          abs(bridge["factor_product_pct"] - bridge["revenue_change_pct"]) < 1e-6)
    check("reconciles flag set", bridge["reconciles"] is True)
    check("lever state named from the sign pattern, using the rulebook's vocabulary",
          bridge["state"].startswith("Thinner baskets, higher prices"), bridge["state"])
    # A pattern whose levers pull against each other cannot assert an outcome: the
    # live scanb model labelled a department down -12.88% "Successful promotion".
    check("an ambiguous pattern carries the computed revenue direction",
          summary_levers.lever_state(0.8, 2.12, -6.99, revenue_pct=-12.88)
          == "Successful promotion - revenue down",
          summary_levers.lever_state(0.8, 2.12, -6.99, revenue_pct=-12.88))
    check("the same pattern with revenue up says so",
          summary_levers.lever_state(3.0, 2.0, -1.0, revenue_pct=4.0)
          == "Successful promotion - revenue up")
    check("an unambiguous pattern needs no qualifier",
          summary_levers.lever_state(3.0, 2.0, 1.0, revenue_pct=6.0) == "Absolute growth"
          and summary_levers.lever_state(-3.0, -2.0, -1.0, revenue_pct=-6.0) == "Severe decline")
    check("with no revenue supplied the bare pattern name is returned",
          summary_levers.lever_state(0.8, 2.12, -6.99) == "Successful promotion")

    measures = summary_levers.derived_measures(families)
    check("basket value = revenue / bills",
          abs(measures["basket_value"]["current"]
              - families["revenue"]["current"] / families["transactions"]["current"]) < 1e-9)
    check("basket size = units / bills",
          abs(measures["basket_size"]["current"]
              - families["quantity"]["current"] / families["transactions"]["current"]) < 1e-9)
    check("price = revenue / units",
          abs(measures["price"]["current"]
              - families["revenue"]["current"] / families["quantity"]["current"]) < 1e-9)

    # Missing transactions must yield no bridge rather than a fabricated lever.
    partial = summary_levers.three_lever_bridge(
        _families((100.0, 90.0), (50.0, 45.0), None))
    check("no bridge without all three inputs", partial is None)
    check("no measure is zero-filled when its input is absent",
          "basket_size" not in summary_levers.derived_measures(
              _families((100.0, 90.0), None, None)))

    # Every sign combination must resolve to a name, including held levers.
    names = {
        summary_levers.lever_state(t, s, p)
        for t in (-5.0, 0.0, 5.0) for s in (-5.0, 0.0, 5.0) for p in (-5.0, 0.0, 5.0)
    }
    check("all 27 sign combinations name a state", all(names) and len(names) >= 9,
          str(len(names)))
    check("flat band suppresses noise",
          summary_levers.lever_state(0.1, -0.2, 0.3) == "Broadly flat on every lever")

    quality = summary_levers.growth_quality(bridge)
    check("growth quality measured against gross lever movement",
          quality is not None and 0 < quality["share_pct"] <= 100)
    # Pure footfall growth: bills and units rise together (so basket size holds)
    # and revenue rises with units (so price holds). All of the movement is on one
    # lever, which is exactly the fragile case the signal exists to name.
    one_lever = summary_levers.three_lever_bridge(
        _families((110.0, 100.0), (110.0, 100.0), (110.0, 100.0)))
    quality_one = summary_levers.growth_quality(one_lever)
    check("a genuinely single-lever result is flagged fragile",
          quality_one["fragile"] is True and quality_one["lever"] == "transactions",
          f"{quality_one['lever']} at {quality_one['share_pct']:.0f}%")
    check("a result spread across three levers is not flagged fragile",
          summary_levers.growth_quality(summary_levers.three_lever_bridge(
              _families((110.0, 100.0), (100.0, 100.0), (110.0, 100.0))))["fragile"] is False)

    facts = summary_levers.lever_facts(bridge)
    check("all three lever effects become supported facts", len(facts) == 3)
    check("an offsetting lever is never dropped",
          any(fact["raw_value"] < 0 for fact in facts)
          and any(fact["raw_value"] > 0 for fact in facts))

    steps = summary_levers.waterfall_steps(bridge, 122_819_915.62, 125_844_619.77)
    check("waterfall runs prior -> three levers -> current", len(steps) == 5)
    running = steps[0]["value"] + sum(step["value"] for step in steps[1:-1])
    check("waterfall closes on the current total",
          abs(running - steps[-1]["value"]) < 1.0)
    check("no waterfall when the bridge does not reconcile",
          summary_levers.waterfall_steps({"reconciles": False}, 1.0, 2.0) is None)


def test_rag() -> None:
    print("\n[2] measure-aware RAG bands")
    check("revenue -0.1% is a watch", summary_rag.verdict("revenue", -0.1)["status"] == "watch")
    check("revenue -3.5% is off track",
          summary_rag.verdict("revenue", -3.5)["status"] == "off_track")
    check("units flat is only a watch on the tougher band",
          summary_rag.verdict("units", 0.0)["status"] == "watch")
    check("units -0.1% is off track on the tougher band",
          summary_rag.verdict("units", -0.1)["status"] == "off_track")
    check("basket size uses the tougher band",
          summary_rag.verdict("basket_size", 1.0)["band"] == "tough")
    check("an unmeasurable movement is not passed as green",
          summary_rag.verdict("revenue", None)["status"] is None)
    check("a declining measure carries a plain-language caution",
          summary_rag.verdict("units", -2.0)["caution"])
    check("price is marked to be read with basket size",
          summary_rag.verdict("price", 5.0)["read_with"] == "basket_size")
    check("higher-is-worse bands invert correctly",
          summary_rag.evaluate(57.0, summary_rag.band_sets()["exposure"]) == "off_track"
          and summary_rag.evaluate(30.0, summary_rag.band_sets()["exposure"]) == "on_track")
    partial = {"summary_rag_bands": {"standard": {"off_track": -10.0}}}
    check("a partial band override keeps the other band sets",
          summary_rag.band_sets(partial)["tough"]["off_track"] == 0.0
          and summary_rag.band_sets(partial)["standard"]["off_track"] == -10.0)
    check("configured measure mapping is honoured",
          summary_rag.verdict("revenue", -1.0,
                              {"summary_rag_measure_bands": {"revenue": "tough"}})["band"] == "tough")


def test_calendar() -> None:
    print("\n[3] calendar / comparator awareness")
    uniform = [
        _member("S1", 6.16e6, 6.29e6, share=31), _member("S2", 6.20e6, 6.47e6, share=33),
        _member("S3", 4.09e6, 4.26e6, share=22), _member("S4", 2.51e6, 2.69e6, share=14),
    ]
    wider = [
        {"member": "S1", "change_pct": 7.8}, {"member": "S2", "change_pct": 3.0},
        {"member": "S3", "change_pct": 3.6}, {"member": "S4", "change_pct": -9.0},
    ]
    config = {"summary_calendar_events": [
        {"name": "Eid al-Fitr", "current": "2026-03-20", "prior": "2025-06-07"}]}
    read = summary_calendar.build(uniform, {"period_anchor": "2026-06"}, config, wider)
    check("estate-wide same-direction move is detected", read["comparator_effect"] is True)
    check("the configured event names the cause", (read["event"] or {}).get("name") == "Eid al-Fitr")
    check("the caveat says to check the calendar", "calendar" in (read["headline"] or "").casefold())
    check("the area weak in the wider period is named as a genuine exception",
          any(item["member"] == "S4" and item["persistent"] for item in read["exceptions"]))
    check("areas the comparator explains are not named as exceptions",
          not any(item["member"] in {"S1", "S2"} for item in read["exceptions"]))

    mixed = [_member("A", 110.0, 100.0), _member("B", 90.0, 100.0),
             _member("C", 104.0, 100.0), _member("D", 103.0, 100.0)]
    check("mixed directions do not fire",
          summary_calendar.build(mixed, {"period_anchor": "2026-06"}, {})["comparator_effect"]
          is False)
    scattered = [_member("A", 99.0, 100.0), _member("B", 70.0, 100.0),
                 _member("C", 97.0, 100.0), _member("D", 60.0, 100.0)]
    check("a same-direction but scattered move does not fire (not one shared cause)",
          summary_calendar.build(scattered, {"period_anchor": "2026-06"}, {})["comparator_effect"]
          is False)
    check("two members are too few to call an estate pattern",
          summary_calendar.comparator_check(
              [_member("A", 95.0, 100.0), _member("B", 95.0, 100.0)])["uniform_move"] is False)
    unnamed = summary_calendar.build(uniform, {"period_anchor": "2026-06"}, {}, wider)
    check("with no calendar configured the signature still fires, unnamed",
          unnamed["comparator_effect"] is True and unnamed["event"] is None)
    check("an event in neither or both years is not a comparability break",
          summary_calendar.festival_shift("2026-06", {"summary_calendar_events": [
              {"name": "X", "current": "2026-06-10", "prior": "2025-06-10"}]}) is None)
    check("measured inputs are always reported for audit",
          "cluster_spread_pct" in summary_calendar.comparator_check(uniform)["checks"])


def test_view() -> None:
    print("\n[4] view model: contributions, movers, signals")
    families = _families((1_100_000.0, 1_000_000.0), (95_000.0, 100_000.0),
                         (50_000.0, 48_000.0))
    members = [
        _member("S1", 500_000.0, 430_000.0, overall=1_100_000.0),
        _member("S2", 300_000.0, 300_000.0, overall=1_100_000.0),
        _member("S3", 300_000.0, 270_000.0, overall=1_100_000.0),
    ]
    coverage = summary_coverage.build_coverage(_universe(members, "store"))
    package = {"status": "ok", "families": families, "primary_family": "revenue",
               "comparison": "the same period last year"}
    view = summary_dashboard.build_view(
        "primary", "Period to date", package, coverage,
        {"data_as_of": "2026-07-29", "grain": "month", "period_anchor": "2026-06"},
        {}, entity_role="store", exposure_role="store")

    contributions = (view["layers"]["entities"] or {})["contributions"]
    expected = (1_100_000.0 - 1_000_000.0) / 1_000_000.0 * 100.0
    check("contribution points sum to the group revenue percentage",
          abs(contributions["sums_to_pts"] - expected) < 1e-6,
          f"{contributions['sums_to_pts']} vs {expected}")
    check("the carrier is named", (contributions["carrier"] or {}).get("member") == "S1")
    check("six KPI cards are built from three scanned families",
          [card["key"] for card in view["kpis"]]
          == ["revenue", "transactions", "units", "basket_value", "basket_size", "price"])
    check("units off track drives a caution on its card",
          any(card["key"] == "units" and card["rag"]["caution"] for card in view["kpis"]))
    check("growth quality appears as a signal",
          any(signal["key"] == "growth_quality" for signal in view["signals"]))
    check("declining-area exposure is paired with the revenue behind it",
          {"declining_areas", "at_risk_revenue"} <= {s["key"] for s in view["signals"]})
    check("the tough-band tension leads the executive summary",
          "fewer" in (view["tldr"][0]["text"] or "").casefold(), view["tldr"][0]["text"])

    # Movers must rank on the blended score, not the raw percentage: a freak
    # percentage on a trivial base must not lead.
    detail_members = [
        _member("BIG", 900_000.0, 800_000.0, overall=1_000_000.0),
        _member("TINY", 300.0, 10.0, overall=1_000_000.0),
    ]
    detail_coverage = summary_coverage.build_coverage(
        _universe(detail_members, "category", level=30))
    movers = summary_dashboard.build_movers(detail_coverage, roles=["category"], limit=2)
    check("a freak percentage on a trivial base does not lead the movers",
          movers["growth"][0]["member"] == "BIG",
          str([row["member"] for row in movers["growth"]]))
    check("movers carry the share-of-level shift a percentage hides",
          movers["growth"][0]["share_shift_pts"] is not None)
    check("spotlight restriction matches by hierarchy ancestry",
          summary_dashboard.build_movers(
              detail_coverage, roles=["category"], limit=2,
              restrict_to_paths=[["BIG"]])["growth"][0]["member"] == "BIG")


def test_two_views() -> None:
    print("\n[5] two time views from one scan")
    trend = {
        "dimension": "month", "grain": "month",
        "value_aliases": {"current": "rev_cur", "prior": "rev_pri", "change": "rev_chg"},
        "rows": [
            {"month": index, "rev_cur": 100.0 + index, "rev_pri": 100.0, "rev_chg": index}
            for index in range(1, 8)
        ],
    }
    period = {"period_anchor": "2026-06", "grain": "month", "data_as_of": "2026-07-29"}
    row = summary_dashboard.latest_complete_period(trend, period)
    check("the anchored complete period is selected, not the last row",
          row is not None and row["month"] == 6, str(row))
    families = summary_dashboard.families_from_trend_row(row, trend)
    check("a period view is derived with no extra query", "revenue" in families)
    check("that view honestly carries revenue only", set(families) == {"revenue"})
    check("a non-month grain is refused",
          summary_dashboard.latest_complete_period({**trend, "grain": "week"}, period) is None)

    dual = summary_dashboard.dual_trend(trend)
    check("dual trend exposes both years", len(dual["series"]) == 2)
    check("month codes are humanised for the reader",
          dual["labels"][0] == "January", str(dual["labels"][:2]))

    coverage = summary_coverage.build_coverage(
        _universe([_member("S1", 600.0, 500.0), _member("S2", 500.0, 500.0),
                   _member("S3", 400.0, 380.0)], "store"))
    package = {"status": "ok",
               "families": _families((1500.0, 1380.0), (900.0, 950.0), (700.0, 690.0)),
               "primary_family": "revenue", "trend": trend}
    wide = summary_dashboard.build_view("primary", "Period to date", package, coverage,
                                        period, {}, entity_role="store")
    narrow = summary_dashboard.build_view(
        "latest_period", summary_dashboard.period_name(period) or "Latest period",
        package, coverage, period, {}, entity_role="store",
        families_override=families, trend_override=trend,
        scan_label_hint=summary_dashboard.span_label(trend, period))
    page = summary_dashboard.build([wide, narrow], "Sales vs Previous Year")
    check("both views reach the page", [v["key"] for v in page["views"]]
          == ["primary", "latest_period"])
    check("the wider view is the default", page["default_view"] == "primary")
    check("a view without the three levers states the limitation",
          any("three-lever" in caveat for caveat in page["caveats"]))
    check("a page with no usable view reports unavailable, not an empty page",
          summary_dashboard.build([])["status"] == "unavailable")

    # Regression: the per-area scan runs ONCE, across the wider span. The narrower
    # view therefore does not own a breakdown by area. Showing the wider period's
    # rows there - as this first did - both broke the arithmetic (+18.25 points
    # against a -6.17% move) and showed the reader the same 13 rows twice under a
    # note saying they did not describe the period named in the toggle.
    check("the narrower view does not claim to own a breakdown",
          narrow["owns_breakdowns"] is False
          and narrow["period_scope"] == "overview_only")
    check("the narrower view holds no entity, area or mover rows at all",
          not narrow["layers"]["entities"]["cards"]
          and narrow["layers"]["entities"]["contributions"] is None
          and not narrow["layers"]["areas"]["entries"]
          and not narrow["layers"]["detail"]["growth"]
          and not narrow["layers"]["detail"]["decline"])
    check("every breakdown layer points at the view that does own it",
          all(narrow["layers"][layer].get("pointer")
              for layer in ("entities", "areas", "detail")))
    check("the pointer names the span the scan actually covers",
          narrow["breakdown_owner"] == "Jan-Jul 2026",
          str(narrow["breakdown_owner"]))
    check("the wider view owns its breakdowns", wide["owns_breakdowns"] is True
          and wide.get("breakdown_owner") is None)
    check("the estate-wide comparator test is not run on unscanned movements",
          narrow["calendar"]["comparator_effect"] is False
          and "did not scan" in narrow["calendar"]["verdict"]["reason"])
    check("the narrower headline reports only what the view owns",
          all("of business" not in item["text"] for item in narrow["tldr"]),
          str([item["text"][:40] for item in narrow["tldr"]]))
    check("a view with no lever split does not claim a broad-based read",
          narrow["hero"]["verdict_tag"] == "Top line only for this period",
          narrow["hero"]["verdict_tag"])
    check("a revenue-only hero still places the period in its own series",
          "periods scanned" in narrow["hero"]["narrative"],
          narrow["hero"]["narrative"])

    # Span vs grain: the label must describe the period covered, not the axis.
    check("the scanned span is named from the trend, not the grain",
          summary_dashboard.span_label(trend, period) == "Jan-Jul 2026",
          str(summary_dashboard.span_label(trend, period)))
    check("a single-period span is not written as a range",
          summary_dashboard.span_label(
              {**trend, "rows": [trend["rows"][0]]}, period) == "Jan 2026")
    check("the latest complete period is named as a reader would say it",
          summary_dashboard.period_name(period) == "June 2026",
          str(summary_dashboard.period_name(period)))
    check("an unusable anchor yields no invented period name",
          summary_dashboard.period_name({"period_anchor": "nope"}) is None)
    check("a revenue-only view still leads with its own headline result",
          narrow["tldr"][0]["layer"] == "overview"
          and "Revenue is" in narrow["tldr"][0]["text"], narrow["tldr"][0]["text"])
    check("a view with the full measure set still leads with the demand tension",
          wide["tldr"][0]["layer"] == "overview" and "fewer" in wide["tldr"][0]["text"])


def _period_rows():
    """One simulated ``period_breakdown`` result: 2 months x 3 divisions.

    June has every division moving down together (the comparator signature) with
    one that is also weak in the wider period; May is mixed.
    """
    def row(month, div, rc, rp, qc, qp, tc, tchg, orc, orp, oqc, oqp, otc, otchg):
        return {
            "month": month, "division_name": div,
            "revenue_current": rc, "revenue_prior": rp, "revenue_change": rc - rp,
            "quantity_current": qc, "quantity_prior": qp, "quantity_change": qc - qp,
            "transactions_current": tc, "transactions_change": tchg,
            "__overall_revenue_current": orc, "__overall_revenue_prior": orp,
            "__overall_revenue_change": orc - orp,
            "__overall_quantity_current": oqc, "__overall_quantity_prior": oqp,
            "__overall_quantity_change": oqc - oqp,
            "__overall_transactions_current": otc,
            "__overall_transactions_change": otchg,
            "__member_count": 3.0,
        }
    june = [
        row(6, "A", 500., 540., 95., 100., 50., -2., 1000., 1080., 190., 200., 100., -4.),
        row(6, "B", 300., 322., 60., 63., 50., -2., 1000., 1080., 190., 200., 100., -4.),
        row(6, "C", 200., 218., 35., 37., 50., -2., 1000., 1080., 190., 200., 100., -4.),
    ]
    may = [
        row(5, "A", 600., 500., 110., 100., 55., 5., 1200., 1100., 210., 200., 110., 8.),
        row(5, "B", 350., 360., 60., 62., 55., 5., 1200., 1100., 210., 200., 110., 8.),
        row(5, "C", 250., 240., 40., 38., 55., 5., 1200., 1100., 210., 200., 110., 8.),
    ]
    aliases = {
        "revenue": {"current": "revenue_current", "prior": "revenue_prior",
                    "change": "revenue_change"},
        "quantity": {"current": "quantity_current", "prior": "quantity_prior",
                     "change": "quantity_change"},
        "transactions": {"current": "transactions_current",
                         "change": "transactions_change"},
    }
    return june + may, aliases


def test_period_scan() -> None:
    print("\n[6] period-scoped scan: a real single-period view")
    rows, aliases = _period_rows()
    scan = summary_dashboard.read_period_scan(rows, "month", "division_name", aliases)
    june = scan["periods"][6]
    check("each period gets its own measure families",
          set(june["families"]) == {"revenue", "quantity", "transactions"})
    check("period families come from the scan's own overall totals, not row sums",
          june["families"]["revenue"]["current"] == 1000.0
          and june["families"]["revenue"]["prior"] == 1080.0)
    check("a family with only current+change is reconstructed",
          june["families"]["transactions"]["prior"] == 104.0,
          str(june["families"]["transactions"]))
    check("member shares are measured against that PERIOD's total",
          abs(june["members"][0]["business_share_pct"] - 50.0) < 1e-9,
          str(june["members"][0]["business_share_pct"]))
    check("a period whose rows add up is marked reconciled", june["reconciled"] is True)
    check("month labels are humanised", june["label"] == "June")

    # A truncated member list must not be allowed to support contributions.
    partial = summary_dashboard.read_period_scan(
        [r for r in rows if not (r["month"] == 6 and r["division_name"] == "C")],
        "month", "division_name", aliases)
    check("a period whose rows do NOT add up is flagged unreconciled",
          partial["periods"][6]["reconciled"] is False)

    coverage = summary_dashboard.period_coverage(scan, 6, "division")
    level = coverage["levels"][0]
    check("period coverage is ranked by the standard blend",
          len(level["rows"]) == 3 and all("rank_score" in r for r in level["rows"]))
    check("period coverage counts its own directions",
          level["counts"]["down"] == 3 and level["counts"]["up"] == 0)

    package = {"status": "ok", "primary_family": "revenue",
               "families": _families((2200.0, 2180.0), None, None)}
    view = summary_dashboard.build_view(
        "latest_period", "June 2026", package, None,
        {"period_anchor": "2026-06", "grain": "month"}, {},
        entity_role="division", families_override=june["families"],
        coverage_override=coverage,
        reference_members=[{"member": "A", "change_pct": 20.0},
                           {"member": "B", "change_pct": -2.8},
                           {"member": "C", "change_pct": 4.2}])
    check("a view given its own period scan owns its breakdowns",
          view["owns_breakdowns"] is True and view["period_scope"] == "own")
    check("the single period gets all six KPI cards",
          [card["key"] for card in view["kpis"]]
          == ["revenue", "transactions", "units", "basket_value", "basket_size", "price"])
    bridge = view["bridge"]
    check("the single period gets its own reconciling three-lever split",
          bridge is not None and bridge["reconciles"] is True)
    check("that split sums to the period's own revenue change",
          abs(sum(bridge["effects"].values()) - bridge["revenue_change"]) < 1e-6)
    contributions = view["layers"]["entities"]["contributions"]
    check("contributions sum to the PERIOD's revenue percentage",
          abs(contributions["sums_to_pts"]
              - view["measures"]["revenue"]["change_pct"]) < 0.01,
          f"{contributions['sums_to_pts']} vs {view['measures']['revenue']['change_pct']}")
    check("the estate-wide comparator check now runs on the period's own movements",
          view["calendar"]["comparator_effect"] is True,
          view["calendar"]["verdict"]["reason"])
    check("the area weak in the wider period is named as the genuine exception",
          [i["member"] for i in view["calendar"]["exceptions"] if i["persistent"]] == ["B"],
          str(view["calendar"]["exceptions"]))
    check("a detected comparator effect still leads the headline",
          view["tldr"][0]["layer"] == "entities"
          and "comparator" in view["tldr"][0]["text"].casefold(),
          view["tldr"][0]["text"][:70])
    check("every entity gets a story in the period view",
          all(card["story"] for card in view["layers"]["entities"]["cards"]))
    # The period scan carries every family per member, so a period card must show
    # THAT period's levers. Reusing the span-wide scan put a department at -4.01%
    # beside a lever state reading "revenue up".
    check("the period scan computes per-member levers for that period",
          set((scan["periods"][6].get("lever_rows") or {})) == {"A", "B", "C"},
          str(list((scan["periods"][6].get("lever_rows") or {})))) 
    for card in view["layers"]["entities"]["cards"]:
        if not card.get("state"):
            continue
        moved_up = (card.get("change_pct") or 0.0) >= 0
        claimed_up = "revenue up" in str(card["state"])
        claimed_down = "revenue down" in str(card["state"])
        if claimed_up or claimed_down:
            check(f"card {card['member']!r} lever state agrees with its own revenue",
                  claimed_up == moved_up,
                  f"{card['change_display']} vs {card['state']!r}")
    draft = {
        "hero": {"headline": view["hero"]["headline"],
                 "narrative": view["hero"]["narrative"]},
        "entities": [{"member": card["member"], "story": card["story"]}
                     for card in view["layers"]["entities"]["cards"]],
        "areas": [],
    }
    errors = dashboard_rules(draft, view)
    check("the period view's deterministic prose validates", errors == [], str(errors[:2]))

    # The query itself: one call, bounded, with per-period overall diagnostics.
    from src.tools import summary_focus_queries as queries
    dax = queries.period_breakdown(
        "n", "p", "T[month]", "T[div]", [queries.treatas("T[store]", ["S1"])],
        [("revenue_current", "rev cur"), ("revenue_prior", "rev pri")], 400, {})["dax"]
    check("the period scan groups by period AND member in one query",
          "T[month], T[div]" in dax)
    check("per-period overall totals remove only the member filter",
          "REMOVEFILTERS(T[div])" in dax and "REMOVEFILTERS(T[month])" not in dax)
    check("the period scan is row-bounded", "TOPN(400" in dax)
    check("the period scan keeps the comparable-population filter", "TREATAS(" in dax)

    # --- regressions found only by the live run ------------------------------
    # 1. A partial month must never be reported as the latest complete one. On the
    #    live model data_as_of was 2026-08-02 with the resolver at DAY grain, so
    #    period_anchor was a date; reading its month component selected August and
    #    shipped two days of trade against a full prior August as a -51.98%
    #    headline.
    day_grain = {"data_as_of": "2026-08-02", "period_anchor": "2026-08-02",
                 "grain": "day"}
    monthly = {
        "dimension": "month", "grain": "month",
        "value_aliases": {"current": "rev_cur", "prior": "rev_pri", "change": "rev_chg"},
    }
    eight = {**monthly, "rows": [
        {"month": m, "rev_cur": 100.0 + m, "rev_pri": 100.0, "rev_chg": float(m)}
        for m in range(1, 9)
    ]}
    picked = summary_dashboard.latest_complete_period(eight, day_grain)
    check("a partial current month is never picked as the latest complete one",
          picked is not None and picked["month"] == 7, str(picked))
    check("the reported month is named from the month actually selected",
          summary_dashboard.period_name(day_grain, 7) == "July 2026",
          str(summary_dashboard.period_name(day_grain, 7)))
    check("completeness is judged against the calendar, exactly at month end",
          summary_dashboard.month_is_complete(7, "2026-07-31") is True
          and summary_dashboard.month_is_complete(7, "2026-07-30") is False)
    check("a month later than the watermark's month belongs to the prior year",
          summary_dashboard.month_is_complete(12, "2026-01-15") is True
          and summary_dashboard.month_is_complete(1, "2026-01-15") is False)
    # A resolved axis can be a padded calendar whose maximum runs to a month end:
    # the live run returned data_as_of 2026-08-31 while real trade stopped around
    # 2026-08-02, so the watermark alone said "August is finished".
    padded = {"data_as_of": "2026-08-31", "today": "2026-08-03",
              "period_anchor": "2026-07", "grain": "month"}
    check("the month we are living in is never complete, whatever the watermark says",
          summary_dashboard.month_is_complete(8, "2026-08-31", "2026-08-03") is False
          and summary_dashboard.month_is_complete(7, "2026-08-31", "2026-08-03") is True)
    check("a padded watermark still resolves to the genuinely finished month",
          summary_dashboard.latest_complete_period(eight, padded)["month"] == 7)
    check("both live period shapes agree with the resolver's own anchor",
          summary_dashboard.latest_complete_period(eight, padded)["month"]
          == int(padded["period_anchor"][5:7]))
    check("a finished month is still accepted once we have moved past it",
          summary_dashboard.month_is_complete(7, "2026-08-31", "2026-09-15") is True)

    # Spurious precision: the model holds raw floats, and a live draft quoted one
    # to 16 decimal places - supported, unreadable, and not the number on the card.
    precision_view = {"measures": {"revenue": {"change_pct": 2.7147647284841927}},
                      "layers": {"entities": {"cards": []}, "areas": {"entries": []}}}
    verbose = {"hero": {"headline": "Revenue rose +2.7147647284841927%",
                        "narrative": "It rose +2.7147647284841927%."},
               "entities": [], "areas": []}
    check("a figure quoted to excessive precision is rejected",
          any("decimal places" in error for error in dashboard_rules(verbose, precision_view)))
    check("the same figure rounded for a reader is accepted",
          dashboard_rules({"hero": {"headline": "Revenue rose +2.71%",
                                    "narrative": "It rose +2.71%."},
                           "entities": [], "areas": []}, precision_view) == [])
    check("with no finished month, no period view is offered at all",
          summary_dashboard.latest_complete_period(
              {**monthly, "rows": [{"month": 8, "rev_cur": 1.0, "rev_pri": 1.0}]},
              day_grain) is None)

    # 2. The per-period overall totals must keep the population filter. When the
    #    member level IS the entity level, a bare REMOVEFILTERS(member) strips the
    #    comparable-population filter too and the "overall" total quietly includes
    #    excluded entities.
    from src.tools import summary_focus_queries as queries
    population = queries.treatas("T[store]", ["S1", "S2"])
    scoped = queries.period_breakdown(
        "n", "p", "T[month]", "T[store]", [population],
        [("revenue_current", "rev cur")], 400, {})["dax"]
    check("per-period overall totals re-apply the population filter",
          scoped.count("TREATAS(") >= 2
          and "REMOVEFILTERS(T[store]), TREATAS(" in scoped,
          "population not restored inside the overall CALCULATE")
    unscoped = queries.period_breakdown(
        "n", "p", "T[month]", "T[div]", [], [("revenue_current", "rev cur")], 400, {})["dax"]
    check("with no population filter the overall total is a plain REMOVEFILTERS",
          "CALCULATE([rev cur], REMOVEFILTERS(T[div]))" in unscoped)

    # 3. Reconciliation must check BOTH sides. Checking current alone passed on
    #    the live model while prior was contaminated, and the contributions -
    #    which divide by prior - shipped wrong.
    one_sided = [
        {"month": 6, "division_name": "A", "revenue_current": 60.0,
         "revenue_prior": 50.0, "revenue_change": 10.0,
         "__overall_revenue_current": 100.0, "__overall_revenue_prior": 130.0,
         "__overall_revenue_change": -30.0, "__member_count": 2.0},
        {"month": 6, "division_name": "B", "revenue_current": 40.0,
         "revenue_prior": 45.0, "revenue_change": -5.0,
         "__overall_revenue_current": 100.0, "__overall_revenue_prior": 130.0,
         "__overall_revenue_change": -30.0, "__member_count": 2.0},
    ]
    lopsided = summary_dashboard.read_period_scan(
        one_sided, "month", "division_name",
        {"revenue": {"current": "revenue_current", "prior": "revenue_prior",
                     "change": "revenue_change"}})
    bucket = lopsided["periods"][6]
    check("a period whose CURRENT agrees but PRIOR does not is unreconciled",
          bucket["reconciled"] is False,
          str(bucket.get("reconciliation")))
    check("the reconciliation records both sides for audit",
          set(bucket["reconciliation"]) == {"rows_current", "overall_current",
                                            "rows_prior", "overall_prior"})

    # 4. An unnamed member must be KEPT and NAMED, not dropped. Dropping it made the
    #    rows fall short of the period total by the unclassified amount, so every
    #    period failed reconciliation and the breakdown was withheld entirely - and
    #    where it was kept, str(None) reached the page as a row labelled "None".
    blank = [
        {"month": 6, "division_name": "A", "revenue_current": 60.0,
         "revenue_prior": 50.0, "revenue_change": 10.0,
         "__overall_revenue_current": 100.0, "__overall_revenue_prior": 90.0,
         "__overall_revenue_change": 10.0, "__member_count": 2.0},
        {"month": 6, "division_name": None, "revenue_current": 40.0,
         "revenue_prior": 40.0, "revenue_change": 0.0,
         "__overall_revenue_current": 100.0, "__overall_revenue_prior": 90.0,
         "__overall_revenue_change": 10.0, "__member_count": 2.0},
    ]
    kept = summary_dashboard.read_period_scan(
        blank, "month", "division_name",
        {"revenue": {"current": "revenue_current", "prior": "revenue_prior",
                     "change": "revenue_change"}})["periods"][6]
    check("an unnamed member is kept, so the period still reconciles",
          kept["reconciled"] is True and len(kept["members"]) == 2,
          str(kept.get("reconciliation")))
    check("an unnamed member is named, never left as None",
          summary_dashboard.UNASSIGNED_LABEL in [m["member"] for m in kept["members"]]
          and "None" not in [str(m["member"]) for m in kept["members"]])
    check("member_name only renames blanks, never a real name",
          summary_dashboard.member_name("FRESH FOOD") == "FRESH FOOD"
          and summary_dashboard.member_name(None) == summary_dashboard.UNASSIGNED_LABEL
          and summary_dashboard.member_name("  ") == summary_dashboard.UNASSIGNED_LABEL)


def test_stories_and_validation() -> None:
    print("\n[7] entity stories and prose validation")
    members = [
        _member("S1", 500_000.0, 430_000.0, overall=1_100_000.0),
        _member("S2", 300_000.0, 300_500.0, overall=1_100_000.0),
        _member("S3", 300_000.0, 270_000.0, overall=1_100_000.0),
        _member("NEW", 90_000.0, None, overall=1_100_000.0),
    ]
    coverage = summary_coverage.build_coverage(_universe(members, "store"))
    package = {"status": "ok",
               "families": _families((1_100_000.0, 1_000_000.0), (95_000.0, 100_000.0),
                                     (50_000.0, 48_000.0)),
               "primary_family": "revenue"}
    view = summary_dashboard.build_view("primary", "Period to date", package, coverage,
                                        {"period_anchor": "2026-06"}, {},
                                        entity_role="store")
    cards = view["layers"]["entities"]["cards"]
    stories = [card["story"] for card in cards]
    check("every entity gets a story", all(stories))
    material = [card for card in cards if card["severity"] != "steady"]
    check("material entities do not share one sentence",
          len({story for story in (card["story"] for card in material)}) == len(material))
    check("a current-only entity is never presented as growth",
          any("never as growth" in card["story"] for card in cards if not card["comparable"]))

    draft = {
        "hero": {"headline": view["hero"]["headline"],
                 "narrative": view["hero"]["narrative"]},
        "entities": [{"member": card["member"], "story": card["story"]} for card in cards],
        "areas": [],
    }
    check("the deterministic fallback passes strict validation (no dead end)",
          dashboard_rules(draft, view) == [], str(dashboard_rules(draft, view)[:2]))

    def errors(mutation):
        return dashboard_rules({**draft, **mutation}, view)

    check("an invented figure is rejected",
          any("does not support" in error for error in errors(
              {"hero": {"headline": "Revenue is +42.42%", "narrative": "It rose +42.42%."}})))
    check("a stated cause is rejected",
          any("cause" in error for error in errors(
              {"hero": {"headline": f"Revenue is +10.00% because prices rose",
                        "narrative": view["hero"]["narrative"]}})))
    check("internal vocabulary is rejected",
          any("internal wording" in error for error in errors(
              {"hero": {"headline": view["hero"]["headline"],
                        "narrative": "The volume effect was +10.00%."}})))
    # BR-26: transactions are bills, not people. A live draft wrote "higher traffic".
    for word in ("traffic", "footfall", "visits", "shoppers"):
        check(f"calling transactions {word!r} is rejected",
              any("write 'transactions'" in error for error in errors(
                  {"hero": {"headline": view["hero"]["headline"],
                            "narrative": f"Revenue rose +10.00% on higher {word}."}})))
    check("the approved word passes",
          not any("write 'transactions'" in error for error in errors(
              {"hero": {"headline": view["hero"]["headline"],
                        "narrative": "Revenue rose +10.00% on higher transactions."}})))
    check("an emoji is rejected",
          any("emoji" in error for error in errors(
              {"hero": {"headline": view["hero"]["headline"] + " \U0001F680",
                        "narrative": view["hero"]["narrative"]}})))
    check("a headline with no figure is rejected",
          any("exact figure" in error for error in errors(
              {"hero": {"headline": "Revenue moved", "narrative": "It moved."}})))
    check("an entity outside the view is rejected",
          any("not in this view" in error for error in errors(
              {"entities": [{"member": "GHOST", "story": "Revenue is +10.00%."}]})))

    boilerplate = [
        {"member": card["member"],
         "story": f"Revenue moved against the prior year in this area, {card['change_display']}."}
        for card in cards
    ]
    check("one sentence reused for every entity is rejected",
          errors({"entities": boilerplate}) != [])
    top_two = [dict(item) for item in draft["entities"]]
    top_two[0]["story"] = "Revenue climbed against the prior year here, +16.28%."
    top_two[1]["story"] = "Revenue climbed against the prior year here, +11.11%."
    check("two top-ranked entities sharing wording is rejected",
          any("top-ranked" in error for error in errors({"entities": top_two})))
    steady = [item for item in draft["entities"]
              if any(card["member"] == item["member"] and card["severity"] == "steady"
                     for card in cards)]
    if steady:
        shared = [{**item, "story": summary_dashboard.NO_MATERIAL_CHANGE} for item in steady]
        check("steady areas may share the honest no-material-change line",
              dashboard_rules({**draft, "entities": shared}, view) == [])


def test_r6_isolation() -> None:
    print("\n[8] R6-off isolation")
    state = {"summary_r6_enabled": False, "summary_coverage": {"levels": [{"role": "store"}]},
             "logs": [], "errors": []}
    result = summary_dashboard_builder.run(state)
    check("with R6 off the builder writes no page model", "summary_dashboard" not in result)
    check("with R6 off the builder still returns only log channels",
          set(result) <= {"logs", "errors"}, str(sorted(result)))


class _Balance(HTMLParser):
    VOID = {"meta", "br", "hr", "img", "input", "link", "circle", "rect", "path",
            "polyline", "line", "text", "use", "source", "col", "area"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.bad: list[tuple] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            self.bad.append(("mismatch", tag))
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.bad.append(("stray", tag))


def test_render() -> None:
    print("\n[9] rendered dashboard shell")
    members = [
        _member("S1 & Co", 500_000.0, 430_000.0, overall=1_100_000.0),
        _member("<script>S2", 300_000.0, 300_500.0, overall=1_100_000.0),
        _member("S3", 300_000.0, 270_000.0, overall=1_100_000.0),
    ]
    coverage = summary_coverage.build_coverage(_universe(members, "store"))
    package = {"status": "ok",
               "families": _families((1_100_000.0, 1_000_000.0), (95_000.0, 100_000.0),
                                     (50_000.0, 48_000.0)),
               "primary_family": "revenue"}
    view = summary_dashboard.build_view("primary", "Period to date", package, coverage,
                                        {"data_as_of": "2026-07-29", "grain": "month",
                                         "period_anchor": "2026-06"}, {},
                                        entity_role="store")
    page = summary_dashboard.build([view], "Sales vs Previous Year")
    markup = summary_dashboard_html.render(page, coverage, 8)

    parser = _Balance()
    parser.feed(markup)
    check("markup is well formed", not parser.stack and not parser.bad,
          f"unclosed={parser.stack[:3]} bad={parser.bad[:3]}")
    check("one layer section per layer", markup.count('class="layer"') == 4)
    check("rail navigation is present", markup.count("rail-btn") >= 4)
    check("executive summary is present", "tldr-item" in markup)
    # The summary scrolls with the page. Pinned, it covered the hero heading and the
    # first chart the moment the reader scrolled - hiding the content it points at.
    tldr_rule = next(
        (line for line in markup.splitlines() if line.startswith(".tldr{")), "")
    check("the executive summary is not pinned over the content",
          bool(tldr_rule) and "position:sticky" not in tldr_rule, tldr_rule[:70])
    check("the left rail is still pinned", any(
        line.startswith(".rail{") and "position:sticky" in line
        for line in markup.splitlines()))
    check("charts are inline SVG", markup.count("<svg") >= 3)
    check("nothing is fetched from outside the file",
          "http://" not in markup and "https://" not in markup)
    check("no browser storage APIs",
          "localStorage" not in markup and "sessionStorage" not in markup)
    check("member names are HTML-escaped",
          "S1 &amp; Co" in markup and "<script>S2" not in markup)
    check("print rules force hidden views open",
          "@media print" in markup and "[hidden]" in markup)
    check("full coverage is rendered", "coverage-store" in markup)
    check("a single view renders no view toggle", 'class="seg"' not in markup)

    two = summary_dashboard.build(
        [view, {**view, "key": "latest_period", "label": "Latest complete month"}],
        "Sales vs Previous Year")
    markup_two = summary_dashboard_html.render(two, coverage, 8)
    check("two views render a toggle and two view sections",
          'class="seg"' in markup_two and markup_two.count('class="view"') == 2)
    check("an unavailable page still renders a readable explanation",
          "could not be produced" in summary_dashboard_html.render(
              {"status": "unavailable", "reason": "no scan", "views": []}))

    # Regressions found only by looking at the rendered page.
    check("the context line uses real separators, not raw HTML entities",
          "&amp;middot;" not in markup and "&middot" not in markup.replace("&middot;", ""))
    check("the waterfall declares its truncated axis",
          "not zero" in markup)
    check("a mirrored ancestor path is not printed twice",
          summary_dashboard_html._ancestor_path(["FARM FRESH", "FARM FRESH"]) == "FARM FRESH")
    check("a genuine two-level path is preserved",
          summary_dashboard_html._ancestor_path(["DIV", "DEPT"]) == "DIV / DEPT")

    # A deep-dive table must not leak query helper columns, must humanise month
    # codes, and must never use internal vocabulary in a manager-facing caption.
    areas_view = summary_dashboard.build_view(
        "primary", "Period to date", package, coverage,
        {"period_anchor": "2026-06", "grain": "month"}, {}, entity_role="store",
        focuses=[{"focus_key": "f1", "segment": "MEAT", "dimension_role": "category"}],
        evidence_by_key={"f1": {
            "facts": [{"display_value": "+10.00%", "statement": "MEAT revenue rose +10.00%."}],
            "sections": {
                "location": {"rows": [
                    {"store_no": "S1", "revenue_current": 10.0, "abs_sort": 999.0},
                    {"store_no": "S2", "revenue_current": 20.0, "abs_sort": 998.0},
                ]},
                "period_trend": {"grain": "month", "rows": [
                    {"month": 6, "revenue_current": 5.0}, {"month": 7, "revenue_current": 6.0},
                ]},
            },
        }})
    areas_markup = summary_dashboard_html.render(
        summary_dashboard.build([areas_view], "T"), coverage, 8)
    check("query helper columns never reach a manager-facing table",
          "Abs Sort" not in areas_markup and "abs_sort" not in areas_markup)
    check("month codes are humanised in deep-dive tables",
          ">June<" in areas_markup and ">6<" not in areas_markup)
    check("no manager-facing caption uses the internal word 'comparable'",
          "Comparable" not in areas_markup)
    check("the deep-dive heading is not the area name repeated",
          areas_markup.count(">MEAT<") == 1, f"{areas_markup.count('>MEAT<')} times")

    OUT.mkdir(exist_ok=True)
    (OUT / "report_dashboard_replay.html").write_text(markup_two, encoding="utf-8")
    print(f"       wrote {OUT / 'report_dashboard_replay.html'}")


def test_real_fixture() -> None:
    print("\n[10] real committed fixtures")
    universe_path = next(
        (path for path in (
            PROJECT_ROOT / "outputs_r4_acceptance" / "summary_focus_universe.json",
            PROJECT_ROOT / "outputs" / "summary_focus_universe.json",
        ) if path.exists()), None)
    package_path = next(
        (path for path in (
            PROJECT_ROOT / "outputs_r4_acceptance_20260730_fix" / "summary_overall_performance.json",
            PROJECT_ROOT / "outputs" / "summary_overall_performance.json",
        ) if path.exists()), None)
    if not universe_path or not package_path:
        print("       (skipped - no committed fixture found)")
        return
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package.get("status") != "ok":
        print("       (skipped - committed overall package is unavailable)")
        return
    coverage = summary_coverage.build_coverage(universe)
    period_path = package_path.parent / "summary_period_context.json"
    period = json.loads(period_path.read_text(encoding="utf-8")) if period_path.exists() else {}

    bridge = summary_levers.three_lever_bridge(package["families"])
    check("real families produce a reconciling three-lever bridge",
          bridge is not None and bridge["reconciles"])
    check("real growth factors multiply back to the revenue percentage",
          abs(bridge["factor_product_pct"] - bridge["revenue_change_pct"]) < 1e-6)
    check("the real price effect equals the existing two-way rate/mix effect",
          abs(bridge["effects"]["price"]
              - (package.get("bridge") or {}).get("rate_mix_effect", 0.0)) < 1.0)

    entity_role = min(
        coverage["levels"], key=lambda level: level.get("level") or 0)["role"]
    view = summary_dashboard.build_view(
        "primary", "Period to date", package, coverage, period, {},
        entity_role=entity_role,
        exposure_role=max(coverage["levels"],
                          key=lambda level: level.get("level") or 0)["role"])
    contributions = view["layers"]["entities"]["contributions"]
    revenue_pct = view["measures"]["revenue"]["change_pct"]
    check("real contributions sum to the real group percentage",
          abs(contributions["sums_to_pts"] - revenue_pct) < 0.01,
          f"{contributions['sums_to_pts']} vs {revenue_pct}")
    draft = {
        "hero": {"headline": view["hero"]["headline"],
                 "narrative": view["hero"]["narrative"]},
        "entities": [{"member": card["member"], "story": card["story"]}
                     for card in view["layers"]["entities"]["cards"]],
        "areas": [],
    }
    real_errors = dashboard_rules(draft, view)
    check("the deterministic draft validates against real evidence",
          real_errors == [], str(real_errors[:3]))
    page = summary_dashboard.build([view], "Sales vs Previous Year")
    markup = summary_dashboard_html.render(page, coverage, 8)
    parser = _Balance()
    parser.feed(markup)
    check("the real-evidence page renders well-formed markup",
          not parser.stack and not parser.bad)
    OUT.mkdir(exist_ok=True)
    (OUT / "report_dashboard_real.html").write_text(markup, encoding="utf-8")
    print(f"       wrote {OUT / 'report_dashboard_real.html'}")


def main() -> int:
    print("=" * 72)
    print("REPLAY: R6 interactive summary dashboard")
    print("=" * 72)
    test_three_levers()
    test_rag()
    test_calendar()
    test_view()
    test_two_views()
    test_period_scan()
    test_stories_and_validation()
    test_r6_isolation()
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
