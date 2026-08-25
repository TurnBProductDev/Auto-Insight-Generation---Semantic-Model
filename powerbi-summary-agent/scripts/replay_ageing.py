"""WP5: the Stock Age Analysis report. Offline - no auth, no LLM, no network.

    python scripts/replay_ageing.py

Proves the code is right. `scripts/audit_ageing.py` proves a *produced artifact*
is right; both are needed, and the auditor is the one that catches a real bug.

The figures are the live ones (2026-08-13), so the arithmetic cannot drift away
from the model it was built against.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.domains.inventory import (ageing_history, ageing_html,  # noqa: E402
                                   ageing_outlook, buckets, dashboard,
                                   dashboard_html)
from src.domains.inventory.reports import ageing  # noqa: E402

# Live figures, Stock Age Analysis, as at 2026-08-12.
LIVE_BANDS = [
    {"band": "0-03 MONTHS", "value": 31578194.16, "aged": 0.0},
    {"band": "03-06 MONTHS", "value": 7954826.48, "aged": 0.0},
    {"band": "06-09 MONTHS", "value": 4720840.48, "aged": 547530.08},
    {"band": "09-12 MONTHS", "value": 2721538.94, "aged": 2721538.94},
    {"band": "12-24 MONTHS", "value": 3068609.18, "aged": 3068609.18},
    {"band": "24+ MONTHS", "value": 787637.57, "aged": 787637.57},
]
LIVE_TOTAL = 50831646.81
LIVE_AGED = 7125315.77

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


def test_ordinal_axis() -> None:
    print("\n=== the age axis is ordinal: order carries the meaning ===")

    check("bands are ordered oldest last",
          buckets.band_index("0-03 MONTHS") < buckets.band_index("24+ MONTHS"))
    check("every display band has a position",
          all(buckets.band_index(b) < len(buckets.NEW_AGE_ORDER)
              for b in buckets.NEW_AGE_ORDER))
    check("an unknown band sorts LAST, never as freshest",
          buckets.band_index("SOMETHING NEW") == len(buckets.NEW_AGE_ORDER))
    check("the three finest source bands roll into 0-03 MONTHS",
          {b for b, t in buckets.CONSOLIDATION.items() if t == "0-03 MONTHS"}
          == {"0-01 MONTHS", "01-02 MONTHS", "02-03 MONTHS"})
    check("high-risk is the two oldest bands, for every division (BR-17)",
          buckets.is_high_risk("12-24 MONTHS") and buckets.is_high_risk("24+ MONTHS")
          and not buckets.is_high_risk("09-12 MONTHS"))

    dist = buckets.build_distribution(LIVE_BANDS)
    check("oldest_first() leads with the worst band, per BR-28",
          dist.oldest_first()[0].name == "24+ MONTHS")


def test_distribution_reconciles() -> None:
    print("\n=== the distribution reconciles to the total ===")

    dist = buckets.build_distribution(LIVE_BANDS)
    check("the bands sum to the live total",
          buckets.reconciles([b.value for b in dist.bands], LIVE_TOTAL),
          f"sum={sum(b.value for b in dist.bands):.2f} expected={LIVE_TOTAL}")
    check("the aged values sum to the live aged total",
          buckets.reconciles([b.aged_value for b in dist.bands], LIVE_AGED),
          f"sum={sum(b.aged_value for b in dist.bands):.2f} expected={LIVE_AGED}")
    check("aged share is 14.0% of stock value",
          abs((dist.aged_share_pct or 0) - 14.02) < 0.02, f"{dist.aged_share_pct}")
    check("high-risk is the 12-24 and 24+ bands only",
          abs(dist.high_risk_value - (3068609.18 + 787637.57)) < 0.01,
          f"{dist.high_risk_value}")

    print("\n--- the division-sensitive threshold shows in the data (BR-16) ---")
    six_nine = dist.band("06-09 MONTHS")
    check("06-09 MONTHS is PARTIALLY aged - the food-at-six-months rule",
          six_nine is not None and 0 < six_nine.aged_value < six_nine.value,
          f"aged={six_nine.aged_value if six_nine else None} of {six_nine.value if six_nine else None}")
    check("0-03 and 03-06 MONTHS are never aged for any division",
          all((dist.band(n) or buckets.Band(n, 0, 0, 0, 0, False)).aged_value == 0
              for n in ("0-03 MONTHS", "03-06 MONTHS")))
    check("09-12 and older are fully aged",
          all(abs((dist.band(n).aged_value - dist.band(n).value)) < 0.01
              for n in ("09-12 MONTHS", "12-24 MONTHS", "24+ MONTHS")))

    print("\n--- cumulative 'this band or older' ---")
    oldest = dist.band("24+ MONTHS")
    check("the oldest band's cumulative equals its own share",
          oldest is not None
          and abs((oldest.cumulative_older_pct or 0) - (oldest.share_pct or 0)) < 1e-9)
    freshest = dist.band("0-03 MONTHS")
    check("the freshest band's cumulative is 100%",
          freshest is not None and abs((freshest.cumulative_older_pct or 0) - 100.0) < 1e-6,
          f"{freshest.cumulative_older_pct if freshest else None}")


def test_undetermined_band() -> None:
    print("\n=== CANNOT BE DETERMINED is separated, never added to a band ===")

    rows = LIVE_BANDS + [{"band": buckets.UNDETERMINED, "value": 120_000.0, "aged": 0.0}]
    dist = buckets.build_distribution(rows)
    check("it does not become an age band",
          all(not buckets.is_undetermined(b.name) for b in dist.bands))
    check("its value is held separately", dist.undetermined_value == 120_000.0)
    check("the total INCLUDES it, so the page still adds up",
          abs(dist.total_value - (LIVE_TOTAL + 120_000.0)) < 0.01,
          f"{dist.total_value}")
    check("and a caveat says so rather than leaving it unexplained",
          any("could not be age-classified" in c for c in dist.caveats), dist.caveats)

    clean = buckets.build_distribution(LIVE_BANDS)
    check("with no such rows - the live case - there is no caveat and no value",
          clean.undetermined_value == 0 and not clean.caveats)


def test_risk_split() -> None:
    print("\n=== aged and non-moving are independent (BR-19) ===")

    rows = [
        {"non_moving": "YES", "value": 5995662.52, "aged": 2760784.20},
        {"non_moving": "NO", "value": 44835984.29, "aged": 4364531.57},
    ]
    split = buckets.risk_split(rows)
    check("the four cells sum to the live total",
          abs(split.total - LIVE_TOTAL) < 0.01, f"{split.total}")
    check("aged across both cells matches the live aged total",
          abs(split.aged_total - LIVE_AGED) < 0.01, f"{split.aged_total}")
    check("aged AND non-moving is the live SAR 2.76M",
          abs(split.aged_non_moving - 2760784.20) < 0.01)
    check("it is exposed as the highest-risk cell",
          split.highest_risk == split.aged_non_moving)
    check("fresh non-moving is a separate, smaller number",
          abs(split.fresh_non_moving - (5995662.52 - 2760784.20)) < 0.01)
    # BR-19: adding the two totals double-counts, because stock that is both
    # aged AND non-moving sits in each. The true "either" figure is the union.
    union = split.aged_moving + split.aged_non_moving + split.fresh_non_moving
    naive = split.aged_total + split.non_moving_total
    check("adding aged and non-moving overstates the union by exactly the "
          "overlap - which is why they are never summed",
          abs(naive - union - split.aged_non_moving) < 0.01,
          f"naive={naive:.2f} union={union:.2f} overlap={split.aged_non_moving:.2f}")
    check("and the overlap is real on this data, so the trap is live",
          split.aged_non_moving > 0)


def test_migration_refuses() -> None:
    print("\n=== bucket migration refuses, rather than being silently absent ===")

    result = buckets.migration()
    check("it reports unavailable", result.get("available") is False)
    check("the reason names the single snapshot, so the reader knows it was "
          "checked rather than forgotten",
          "one stock position" in result.get("reason", ""), result.get("reason"))


def _synthetic_scan() -> dict:
    """The live shape, with the live figures, but committed - so the replay
    runs on a clean checkout with no live artifact present."""
    return {
        "snapshot": [{"[as_at]": "2026-08-12T00:00:00", "[total_value]": LIVE_TOTAL,
                      "[aged_value]": LIVE_AGED, "[skus]": 41916, "[locations]": 7}],
        "bands": [{"REP_SSR_SAG[NEW AGE]": b["band"], "[value]": b["value"],
                   "[aged]": b["aged"], "[skus]": 100} for b in LIVE_BANDS],
        "risk_split": [
            {"REP_SSR_SAG[non_moving_status]": "YES", "[value]": 5995662.52,
             "[aged]": 2760784.20},
            {"REP_SSR_SAG[non_moving_status]": "NO", "[value]": 44835984.29,
             "[aged]": 4364531.57}],
        "divisions": [{"LINK TABLE[DEPARTMENT]": "GM HOME WARE", "[value]": 4807952.22,
                       "[aged]": 1489127.65, "[high_risk]": 900000.0}],
        "locations": [{"REP_SSR_SAG[LOC_CODE]": "CDC", "[value]": 25847125.25,
                       "[aged]": 4503025.81, "[high_risk]": 2000000.0}],
        "skutype": [{"REP_SSR_SAG[skutype]": "LOCAL", "[value]": 40000000.0,
                     "[aged]": 5000000.0}],
        "sections_high_risk": [],
    }


def test_report_model() -> None:
    print("\n=== the report model ===")

    report = ageing.build(_synthetic_scan())

    check("the period is stated 'as at', never as a span (NN 18)",
          report["period_label"] == "as at 2026-08-12", report["period_label"])
    check("every reconciliation check passes on the live figures",
          all(report["checks"].values()), report["checks"])
    check("the header carries the four headline figures",
          {"total_value", "aged_value", "high_risk_value", "aged_non_moving"}
          <= set(report["header"]))
    check("call-outs lead with the oldest band (BR-28)",
          report["call_outs"] and report["call_outs"][0]["band"] == "24+ MONTHS",
          [c["band"] for c in report["call_outs"]])
    check("the oldest band is marked for separate mention (BR-17)",
          report["call_outs"][0]["always_separate"] is True)
    check("migration is present and refusing",
          report["migration"]["available"] is False)

    print("\n--- the narrative is grounded and follows the rulebook ---")
    narrative = report["narrative"]
    check("it leads with the oldest band, not with total stock value",
          "two years old" in narrative[0], narrative[0])
    check("every line carries a figure (BR-25)",
          all("SAR" in line or "%" in line for line in narrative))
    check("it states that aged and non-moving overlap",
          any("overlap" in line for line in narrative))

    banned = {"velocity", "offtake", "capital lock-up", "carry cost",
              "materiality", "write-down provision", "dead stock",
              "days of cover", "stock worth"}
    text = " ".join(narrative).lower()
    hits = sorted(w for w in banned if w in text)
    check("no banned vocabulary reaches the reader (BR-03/BR-25)", not hits, f"{hits}")
    check("no emojis", all(ord(ch) < 0x2190 for line in narrative for ch in line))

    print("\n--- a report with nothing alarming still renders honestly ---")
    quiet = ageing.build({
        "snapshot": [{"[as_at]": "2026-08-12", "[total_value]": 1000.0,
                      "[aged_value]": 0.0, "[skus]": 5, "[locations]": 1}],
        "bands": [{"REP_SSR_SAG[NEW AGE]": "0-03 MONTHS", "[value]": 1000.0,
                   "[aged]": 0.0}],
        "risk_split": [{"REP_SSR_SAG[non_moving_status]": "NO", "[value]": 1000.0,
                        "[aged]": 0.0}],
    })
    check("no high-risk stock produces no high-risk call-outs, not a blank page",
          quiet["call_outs"] == [] and quiet["checks"]["bands_sum_to_total"])
    check("and it still reconciles", all(quiet["checks"].values()), quiet["checks"])


def test_rendering() -> None:
    print("\n=== the rendered page ===")

    # Built from the synthetic scan, never the live one: a replay must run on a
    # clean checkout, and the live scan carries real stock values so it is
    # gitignored. If it happens to be present it is rendered as well, but its
    # absence is not a failure.
    report = ageing.build(_synthetic_scan())
    html = ageing_html.render(report)

    live = PROJECT_ROOT / "outputs_ageing" / "ageing_scan.json"
    if live.exists():
        live_report = ageing.build(json.loads(live.read_text(encoding="utf-8")))
        check("the live scan also renders and reconciles",
              all(live_report["checks"].values())
              and len(ageing_html.render(live_report)) > 2000,
              live_report["checks"])
    else:
        print("  [note] no live scan present; synthetic fixture only")

    check("it renders", len(html) > 2000, f"{len(html)} bytes")
    check("it is self-contained - no external request",
          "http://" not in html and "https://" not in html and "<script" not in html)
    check("every age band appears",
          all(band["name"] in html
              for band in report["distribution"]["bands"]))
    check("the 'as at' label is on the page", report["period_label"] in html)
    check("the limitation about movement between dates is stated",
          "only one stock position" in html)
    check("and what the report does not answer is stated",
          "does not say why stock is" in html)

    escaped = ageing_html.render({**report, "report_name": '<img src=x onerror=1>'})
    check("content is HTML-escaped", "<img src=x" not in escaped
          and "&lt;img" in escaped)


def test_dashboard() -> None:
    print("\n=== the four-layer dashboard ===")

    from src.domains.inventory import dashboard, dashboard_html

    report = ageing.build(_synthetic_scan())
    page = dashboard.build(report)

    check("it has the same four layers as the sales dashboard",
          page["layers"] == ["overview", "entities", "areas", "detail"],
          page["layers"])
    check("two views, defaulting to all stock",
          [v["key"] for v in page["views"]] == ["all", "high_risk"]
          and page["default_view"] == "all",
          [v["key"] for v in page["views"]])
    check("the subtitle states the position 'as at' a date (NN 18)",
          str(page["subtitle"]).startswith("Stock position as at"), page["subtitle"])

    all_view = page["views"][0]
    check("the overview carries a hero and KPI cards",
          all_view["hero"]["headline"] and len(all_view["kpis"]) >= 4)
    check("the executive summary is ranked and links into layers",
          all_view["tldr"] and all(item.get("layer") in page["layers"]
                                   for item in all_view["tldr"]),
          all_view["tldr"])
    check("the locations layer owns cards", (all_view["layers"]["entities"] or {}).get("cards"))
    check("the divisions layer owns rows", (all_view["layers"]["areas"] or {}).get("rows"))

    print("\n--- the high-risk view is scoped, and says so ---")
    hr = page["views"][1]
    check("it has its own limitation stating totals will not match",
          any("will not match" in text for text in hr["limitations"]),
          hr["limitations"])
    check("it carries its own breakdowns rather than deferring",
          (hr["layers"]["entities"] or {}).get("cards")
          and (hr["layers"]["areas"] or {}).get("rows"))
    check("its detail layer holds only high-risk bands",
          all(b.get("high_risk") for b in (hr["layers"]["detail"] or {}).get("bands") or []))

    print("\n--- each view ranks by ITS OWN measure ---")
    hr_cards = (hr["layers"]["entities"] or {}).get("cards") or []
    values = [float(str(c["value_display"]).replace("SAR ", "").replace("M", "e6")
                    .replace("K", "e3").replace(",", "")) for c in hr_cards]
    check("high-risk locations are ordered by high-risk stock, not by aged stock",
          values == sorted(values, reverse=True), values)

    print("\n--- the document skeleton the shared CSS requires ---")
    html = dashboard_html.render(page)
    body = html.split("</style>", 1)[-1]

    # `.app` is a flex ROW whose only children are the rail and <main>. Giving
    # it four children rendered the header, rail, views and footer as four
    # side-by-side columns, with the title wrapping one word per line. The
    # shared stylesheet is not ours to change, so the skeleton must match it.
    check("the rail is the first child of .app",
          '<div class="app" id="report">\n<nav class="rail"' in html,
          body[:200])
    check("the page content is inside main > .page",
          '<main><div class="page">' in html)
    check("the header is inside the page, not a sibling of the rail",
          '<header class="hero-head">' in html
          and html.index('<main><div class="page">') < html.index('<header class="hero-head">'))
    check("the rail buttons are wrapped in .rail-nav, as the CSS expects",
          '<div class="rail-nav">' in html)
    check("no invented layout classes remain",
          'class="top"' not in body and 'class="views"' not in body)

    # _script() already carries its own <script> tags; wrapping it again nests
    # them, which silently kills the nav and the view toggle.
    check("exactly one script tag - _script() is not double-wrapped",
          html.count("<script") == 1, f"{html.count('<script')} script tags")

    print("\n--- the rendered document ---")
    check("it renders", len(html) > 8000, f"{len(html)} bytes")
    check("it is self-contained - no external request",
          "http://" not in html and "https://" not in html)
    check("it reuses the sales dashboard's stylesheet, so the two cannot drift",
          ".rail-btn" in html or "rail" in html)
    check("both view toggles are present",
          'data-view="all"' in html and 'data-view="high_risk"' in html)
    check("all four layer buttons are present",
          all(f'data-layer="{layer}"' in html for layer in page["layers"]))
    check("no year-on-year language leaked onto a stock page",
          "same period last year" not in html.lower()
          and "versus the comparison period" not in html.lower())
    check("the movement limitation is still stated",
          "one stock position" in html)

    # Same seam as replay_stock_health pins: `_signal_cards` reads
    # signal["value"], and these views were building "value_display", so the
    # cards rendered with no number - "Fresh but not selling" lost its SAR 3.23M.
    signals = [s for v in page["views"] for s in (v.get("signals") or [])]
    check("every signal carries the key the renderer reads",
          bool(signals) and all(s.get("value") for s in signals),
          f"missing 'value': {[s.get('label') for s in signals if not s.get('value')]}")

    # The high-risk view ranks by high-risk stock, so it must not be headed
    # "aged stock" - a different measure with a different total.
    check("the high-risk view is labelled by the measure it ranks on",
          "Which divisions hold the high-risk stock" in html)

    print("\n--- the charts ---")
    import re
    import xml.etree.ElementTree as ET

    svgs = re.findall(r"<svg.*?</svg>", html, re.S)
    check("the page draws charts, not only tables", len(svgs) >= 2, f"{len(svgs)} svg")
    well_formed = True
    for svg in svgs:
        try:
            ET.fromstring(svg)
        except Exception as exc:            # noqa: BLE001 - report, do not raise
            well_formed = False
            check("every chart is well-formed XML", False, str(exc))
            break
    if well_formed:
        check("every chart is well-formed XML", True)

    check("two series means a legend - identity is never colour alone",
          "chart-legend" in html and "Not yet aged" in html and "Aged" in html)

    # The oldest band is 1.5% of stock and computes to under 2px. It is the one
    # band BR-28 says to LEAD with, so a chart that renders it as nothing is
    # worse than no chart. Every drawn bar must be visible.
    heights = [float(h) for h in
               re.findall(r'<rect class="data-point"[^>]*height="([\d.]+)"', html)]
    check("every drawn band is visible, including the oldest",
          bool(heights) and min(heights) >= 3.0, f"min height {min(heights) if heights else '-'}")

    check("the aged/not-aged split is drawn inside each band",
          "not yet aged" in html.lower() and "- aged" in html.lower())
    check("the cumulative 'older than this' reading is drawn",
          "How much is older than this?" in html)
    check("the four-way risk split is drawn as a matrix, not a sum",
          "risk-matrix" in html and html.count("rm-cell") >= 4)
    check("the matrix says the two measures are never added",
          "never added together" in html)

    escaped = dashboard_html.render(
        {**page, "title": '<img src=x onerror=alert(1)>'})
    check("content is escaped", "<img src=x" not in escaped and "&lt;img" in escaped)


def test_published_summary_contract() -> None:
    """The app-facing payload must BE the shared contract, not resemble it.

    Two other reports already shipped a payload that merely resembled the
    contract - the app discards an unparseable summary in silence, no error
    and no log line, so the client's insights rendered normally while the
    Home brief stayed empty. Same coverage as `replay_stock_health.py`'s
    `test_published_summary_contract`, for the same reason.
    """
    print("\n[published summary contract]")
    from src.domains.inventory import ageing_publish as pub
    from src.tools.api_payloads import ReportSummaryPayload

    report = ageing.build(_synthetic_scan())
    payload = pub.summary_payload(report)

    try:
        ReportSummaryPayload(**payload)
        check("the payload validates against the shared contract", True)
    except Exception as exc:  # noqa: BLE001 - the message is the whole point
        check("the payload validates against the shared contract", False, str(exc))

    check("exactly the five contract fields, no more",
          set(payload) == {"title", "generatedAt", "headline", "metrics", "sections"},
          f"got {sorted(payload)}")
    check("every metric is label/value/tone with a string value",
          all(set(m) == {"label", "value", "tone"} and isinstance(m["value"], str)
              for m in payload["metrics"]),
          str(payload["metrics"][:2]))
    check("sections are present and populated",
          bool(payload["sections"]) and all(s["points"] for s in payload["sections"]))
    check("the headline leads with the oldest band (BR-28)",
          "24+ MONTHS" in payload["headline"], payload["headline"])

    # A quiet position - no high-risk band - must still yield a real headline
    # and a non-empty "what needs attention" section, never a blank one.
    quiet = ageing.build({
        "snapshot": [{"[as_at]": "2026-08-12", "[total_value]": 1000.0,
                      "[aged_value]": 0.0, "[skus]": 5, "[locations]": 1}],
        "bands": [{"REP_SSR_SAG[NEW AGE]": "0-03 MONTHS", "[value]": 1000.0,
                   "[aged]": 0.0}],
        "risk_split": [{"REP_SSR_SAG[non_moving_status]": "NO", "[value]": 1000.0,
                        "[aged]": 0.0}],
    })
    quiet_payload = pub.summary_payload(quiet)
    check("a quiet position still yields a headline",
          bool(quiet_payload.get("headline", "").strip()))
    check("and a stated, non-empty attention section rather than a blank one",
          quiet_payload["sections"][0]["points"]
          and "no age band" in quiet_payload["sections"][0]["points"][0].lower())

    # Nothing the contract has no room for may be silently dropped: the as-at
    # date and the single-snapshot limitation both have to survive as prose.
    text = " ".join(pt for s in payload["sections"] for pt in s["points"])
    check("the as-at date survives into the sections",
          str(report.get("as_at") or "") in text)
    check("the single-snapshot limitation survives into the sections",
          "one stock position" in text)



# --- Comparing against an earlier position ------------------------------------
# The live SB Mart pair (14 August against 23 August 2026), which is the pair
# that exposed the valuation-basis break. Committed here so the arithmetic under
# test cannot drift away from the data it was built against.

COMPARE_NOW = {
    "as_at": "2026-08-23", "skus": 41674,
    "bands": [
        {"name": "0-03 MONTHS", "value": 3415190.2756, "qty": 9040561.86011},
        {"name": "03-06 MONTHS", "value": 898651.9649, "qty": 2457723.57349},
        {"name": "06-09 MONTHS", "value": 576336.5578, "qty": 1707645.92904},
        {"name": "09-12 MONTHS", "value": 388542.9403, "qty": 1063064.34298},
        {"name": "12-24 MONTHS", "value": 363063.8403, "qty": 1570626.26857},
        {"name": "24+ MONTHS", "value": 90713.9685, "qty": 276657.70879},
    ],
    "locations": [
        {"name": "WH1", "value": 3570579.272, "qty": 10280860.00004, "aged": 689062.6078},
        {"name": "ST5", "value": 16867.6363, "qty": 79838.25944, "aged": 4183.4488},
    ],
    "divisions": [],
}
COMPARE_THEN = {
    "as_at": "2026-08-14", "skus": 41939,
    "bands": [
        {"name": "0-03 MONTHS", "value": 8768413.8171, "qty": 6333425.25964},
        {"name": "03-06 MONTHS", "value": 2148614.586, "qty": 1593180.55952},
        {"name": "06-09 MONTHS", "value": 1278865.1061, "qty": 926118.16004},
        {"name": "09-12 MONTHS", "value": 758314.0755, "qty": 505554.61648},
        {"name": "12-24 MONTHS", "value": 828696.1149, "qty": 891046.26907},
        {"name": "24+ MONTHS", "value": 213084.9153, "qty": 154005.41577},
    ],
    "locations": [
        {"name": "WH1", "value": 7198620.2631, "qty": 5431855.00002, "aged": 1226564.127},
        {"name": "ST5", "value": 62472.6945, "qty": 79838.25944, "aged": 14643.7092},
    ],
    "divisions": [],
}


def test_valuation_basis() -> None:
    print("\n=== the valuation basis is measured, not assumed ===")

    # THE test for this module. ST5 carries a byte-identical quantity on both
    # dates while its value moves to 27% of what it was. Stock that did not move
    # cannot lose 73% of its worth, so the change is in how VALUE is worked out.
    basis = ageing_history.basis_check([
        {"name": "ST5", "value_now": 16867.6363, "value_then": 62472.6945,
         "qty_now": 79838.25944, "qty_then": 79838.25944},
        {"name": "WH1", "value_now": 3570579.272, "value_then": 7198620.2631,
         "qty_now": 10280860.00004, "qty_then": 5431855.00002},
    ])
    check("a rebased valuation is detected", basis["value_comparable"] is False)
    check("the proof is the location whose quantity did not move",
          (basis.get("proof") or {}).get("name") == "ST5")
    check("the refusal is written in plain words a manager can check",
          "did not move cannot change in worth" in basis["reason"],
          basis["reason"])
    check("the refusal quotes both value-per-unit readings",
          "0.78" in basis["reason"] and "0.21" in basis["reason"], basis["reason"])

    # And the opposite: a stable basis must NOT be refused, or the comparison
    # would be permanently disabled on a healthy model.
    steady = ageing_history.basis_check([
        {"name": "A", "value_now": 1000.0, "value_then": 1100.0,
         "qty_now": 100.0, "qty_then": 110.0},
        {"name": "B", "value_now": 2000.0, "value_then": 1900.0,
         "qty_now": 200.0, "qty_then": 190.0},
    ])
    check("a stable basis is left alone", steady["value_comparable"] is True)
    check("and says so rather than staying silent",
          "can be compared" in steady["reason"], steady["reason"])

    # A location that traded normally is not proof of anything: the decisive
    # signal is the UNCHANGED quantity, not a large value move on its own.
    traded = ageing_history.basis_check([
        {"name": "A", "value_now": 500.0, "value_then": 1000.0,
         "qty_now": 50.0, "qty_then": 100.0},
    ])
    check("a location that simply sold half its stock is not called a rebasing",
          traded["value_comparable"] is True, traded["reason"])
    check("no pairs at all is reported as unchecked rather than as a pass",
          ageing_history.basis_check([])["checked"] is False)


def test_comparison() -> None:
    print("\n=== what changed, on the live pair ===")

    result = ageing_history.build(COMPARE_NOW, COMPARE_THEN)
    check("the comparison is available", result["available"] is True)
    check("the window is the nine days between the two positions",
          result["days"] == 9, result["days"])
    check("value totals are withheld once the basis check refuses them",
          result["value_comparable"] is False)

    readings = {r["key"]: r for r in result["headlines"]}
    check("aged share of value: 12.9% to 14.7%",
          round(readings["aged_value_share"]["then_pct"], 1) == 12.9
          and round(readings["aged_value_share"]["now_pct"], 1) == 14.7,
          f"{readings['aged_value_share']['then_pct']} -> "
          f"{readings['aged_value_share']['now_pct']}")
    check("aged share of units: 14.9% to 18.1%",
          round(readings["aged_qty_share"]["then_pct"], 1) == 14.9
          and round(readings["aged_qty_share"]["now_pct"], 1) == 18.1,
          f"{readings['aged_qty_share']['then_pct']} -> "
          f"{readings['aged_qty_share']['now_pct']}")
    for key, reading in readings.items():
        check(f"  {key}: the movement is now minus then",
              abs(reading["points"] - (reading["now_pct"] - reading["then_pct"])) < 1e-9)

    # The aged total is derived from the BANDS on both sides. The source model's
    # own nine-month flag omits the 24+ band, so reading it would understate the
    # oldest stock - and would do so on both dates, hiding the movement too.
    aged_now = sum(b["value"] for b in COMPARE_NOW["bands"]
                   if b["name"] in ("09-12 MONTHS", "12-24 MONTHS", "24+ MONTHS"))
    check("aged is summed from the bands, so the oldest band is included",
          abs(result["now"]["aged_value"] - aged_now) < 0.01,
          f"{result['now']['aged_value']} vs {aged_now}")

    check("both readings agree, and the page is told so",
          (result["agreement"] or {}).get("agree") is True
          and "same way" in result["agreement"]["text"])
    check("the verdict is stated in words, not left to the reader",
          result["verdict"] == "Ageing has got worse", result["verdict"])

    bands = {b["name"]: b for b in result["bands"]}
    check("the fresh band lost unit share", bands["0-03 MONTHS"]["qty_share_points"] < 0)
    check("every band above six months gained unit share",
          all(bands[n]["qty_share_points"] > 0
              for n in ("06-09 MONTHS", "09-12 MONTHS", "12-24 MONTHS", "24+ MONTHS")))
    check("the two oldest bands are marked high-risk",
          bands["12-24 MONTHS"]["high_risk"] and bands["24+ MONTHS"]["high_risk"])

    locations = {r["name"]: r for r in result["locations"]}
    check("a location's own aged share is compared, not its size",
          round(locations["WH1"]["aged_share_then_pct"], 1) == 17.0
          and round(locations["WH1"]["aged_share_now_pct"], 1) == 19.3,
          f"{locations['WH1']}")
    check("product counts are compared, since counting is basis-free",
          result["sku_change"] == -265, result["sku_change"])


def test_comparison_refuses() -> None:
    print("\n=== a comparison that cannot be made says why ===")

    for label, history, expected in (
        ("no earlier position at all", {"as_at": "", "bands": []}, "nothing to compare"),
        ("an earlier position with no date",
         {"as_at": "", "bands": COMPARE_THEN["bands"]}, "no date"),
        ("an earlier position that is not earlier",
         {"as_at": "2026-08-25", "bands": COMPARE_THEN["bands"]}, "not before"),
    ):
        result = ageing_history.build(COMPARE_NOW, history)
        check(f"{label}: refused", result["available"] is False)
        check(f"{label}: the reason is stated",
              expected in str(result.get("reason") or ""), result.get("reason"))


def test_position_from_scan() -> None:
    print("\n=== both history lanes share one comparison engine ===")

    scan = _synthetic_scan()
    scan["bands"] = [{**b, "[qty]": 1000.0} for b in scan["bands"]]
    position = ageing_history.position_from_scan(scan)
    check("a kept scan becomes a position the same builder can read",
          position["as_at"] == "2026-08-12" and len(position["bands"]) == 6)
    check("its members carry quantity, or the basis check has nothing to work with",
          all("qty" in row for row in position["locations"]))
    check("a scan compared with itself reports no movement",
          ageing_history.build(position, position)["available"] is False)


def test_clearance() -> None:
    print("\n=== the clearance outlook ===")

    result = ageing_outlook.clearance([
        {"name": "HOME & LIVING", "aged_qty": 1548073.05004, "aged_value": 365334.4867,
         "total_value": 1164133.729, "daily_qty": 23936.97},
        {"name": "CONSUMER GOODS", "aged_qty": 183603.2703, "aged_value": 61337.2256,
         "total_value": 2312537.35, "daily_qty": 155800.41},
        {"name": "NOTHING SELLS", "aged_qty": 5000.0, "aged_value": 900.0,
         "total_value": 9000.0, "daily_qty": 0.0},
    ], horizon_days=30, unmapped_velocity=72380.56)

    rows = {r["name"]: r for r in result["rows"]}
    check("the estimate is units sold over the window against units sitting aged",
          abs(rows["HOME & LIVING"]["cleared_pct"] - 46.4) < 0.1,
          rows["HOME & LIVING"]["cleared_pct"])
    check("days to clear is aged units over daily sales",
          abs(rows["HOME & LIVING"]["days_to_clear"] - 1548073.05004 / 23936.97) < 1e-6)
    check("an estimate over 100% is capped, because nothing clears more than it holds",
          rows["CONSUMER GOODS"]["cleared_pct"] == 100.0
          and rows["CONSUMER GOODS"]["capped"] is True)
    check("a division with no sales is reported as never clearing, not as zero days",
          rows["NOTHING SELLS"]["days_to_clear"] is None
          and rows["NOTHING SELLS"]["days_display"] == ageing_outlook.NEVER_CLEARS)
    check("the slowest come first, because the slow ones are the work",
          [r["name"] for r in result["rows"]][0] == "NOTHING SELLS")
    check("a day is written as a day, not as '1 days'",
          "1 days" not in rows["CONSUMER GOODS"]["days_display"],
          rows["CONSUMER GOODS"]["days_display"])
    check("the oldest-stock-first assumption is stated, never assumed silently",
          any("oldest stock first" in c for c in result["caveats"]))
    check("selling velocity that maps to no division is declared, not dropped",
          any("not mapped to a division" in c for c in result["caveats"]),
          result["caveats"])


def test_categories_rank_by_money() -> None:
    print("\n=== the category check counts fairly and ranks usefully ===")

    rows = [
        {"name": "KHALBATTA", "total": 4.0, "aged": 4.0},
        {"name": "KITCHEN KNIFE", "total": 118084.0, "aged": 38909.0},
        {"name": "OTHER", "total": 240923.0, "aged": 74111.0},
        {"name": "HEALTHY", "total": 100000.0, "aged": 1000.0},
        {"name": "EMPTY", "total": 0.0, "aged": 0.0},
    ]
    result = ageing_outlook.categories(rows, threshold_pct=30.0, top=8)

    check("a category holding nothing cannot fail a threshold",
          result["carried"] == 4, result["carried"])
    check("the count treats every category over the line equally",
          result["over"] == 3, result["over"])
    # The failure this ordering exists to prevent: a category holding four
    # dollars of entirely-old stock scores a perfect 100% and would lead a list
    # sorted on share, which is a true number and a useless instruction.
    check("the list leads with money stuck, not with the biggest percentage",
          [c["name"] for c in result["worst"]][0] == "OTHER",
          [c["name"] for c in result["worst"]])
    check("the freak percentage is still recorded, so the ordering can be explained",
          (result["highest_share"] or {})["name"] == "KHALBATTA")
    check("every listed category really is over the line",
          all(c["aged_share_pct"] > 30.0 for c in result["worst"]))
    check("the note says the list is ordered by money",
          "ordered by how much money is stuck" in result["note"], result["note"])


def test_stuck_lines() -> None:
    print("\n=== the stuck product lines ===")

    rows = [
        {"sku": "A", "risk_score": -100.0, "value": 26548.81, "qty": 14047.0,
         "daily_qty": 56.67, "status": "EXCESS STOCK", "location": "WH1",
         "category": "SMART WATCHES"},
        {"sku": "B", "risk_score": -100.0, "value": 400.0, "qty": 10.0,
         "daily_qty": 0.0, "status": "EXCESS STOCK", "location": "WH1",
         "category": "SMALL"},
        {"sku": "C", "risk_score": -20.0, "value": 90000.0, "qty": 10.0,
         "daily_qty": 1.0, "status": "EXCESS STOCK", "location": "WH1",
         "category": "HEALTHY"},
        {"sku": "D", "risk_score": -80.0, "value": 5000.0, "qty": 40.0,
         "daily_qty": 0.0, "status": "STOCK AVAILABLE BUT NO SALES",
         "location": "ST1", "category": "DEAD"},
    ]
    result = ageing_outlook.stuck_lines(rows, risk_cutoff=-70.0, value_floor=500.0)

    names = [r["sku"] for r in result["rows"]]
    check("a healthy score is not listed however much money it holds", "C" not in names)
    check("a line under the money floor is not listed", "B" not in names)
    check("the rest are ordered by money at stake", names == ["A", "D"], names)
    check("a line that still sells daily is flagged as such",
          result["rows"][0]["still_selling"] is True)
    check("a line with no sales is not", result["rows"][1]["still_selling"] is False)
    check("the source's own status wording is kept, only tidied",
          result["rows"][1]["status"] == "Stock Available but No Sales",
          result["rows"][1]["status"])
    check("the second value basis is named so the two are never added",
          "different basis" in result["note"], result["note"])


def test_optional_everywhere() -> None:
    print("\n=== every new section is optional ===")

    # A client whose model has no history table and no stock-status table must
    # still get exactly the page it got before any of this existed.
    scan = _synthetic_scan()
    model = ageing.build(scan)
    check("no history table means the comparison refuses, with a reason",
          (model["comparison"] or {}).get("available") is False
          and bool(model["comparison"].get("reason")))
    check("and band movement falls back to the standing refusal",
          model["migration"]["available"] is False
          and "one stock position" in model["migration"]["reason"])
    for section in ("clearance", "categories", "stuck_lines"):
        check(f"{section}: absent inputs are reported, not silently skipped",
              model[section]["available"] is False and bool(model[section].get("reason")),
              model[section])

    page = dashboard.build(model)
    check("the page falls back to exactly the four original tabs",
          page["layers"] == ["overview", "entities", "areas", "detail"],
          page["layers"])
    check("and renders without either new tab",
          "What changed" not in dashboard_html.render(page)
          and "Where to act" not in dashboard_html.render(page))


def test_new_layers_render() -> None:
    print("\n=== the two new tabs render as a document ===")

    scan = _synthetic_scan()
    scan["bands"] = [{**b, "[qty]": 1000.0} for b in scan["bands"]]
    model = ageing.build(scan)
    model["comparison"] = ageing_history.build(COMPARE_NOW, COMPARE_THEN)
    model["migration"] = {"available": True, "counted_in": "units",
                          "bands": model["comparison"]["bands"], "reason": ""}
    model["clearance"] = ageing_outlook.clearance([
        {"name": "HOME & LIVING", "aged_qty": 1548073.05, "aged_value": 365334.49,
         "total_value": 1164133.73, "daily_qty": 23936.97}], horizon_days=30)
    model["categories"] = ageing_outlook.categories(
        [{"name": "KITCHEN KNIFE", "total": 118084.0, "aged": 38909.0}],
        threshold_pct=30.0)
    model["stuck_lines"] = ageing_outlook.stuck_lines(
        [{"sku": "A", "risk_score": -100.0, "value": 26548.81, "qty": 14047.0,
          "daily_qty": 56.67, "status": "EXCESS STOCK", "location": "WH1",
          "category": "SMART WATCHES"}])
    model["stuck_lines"]["estate_lines"] = 40769

    page = dashboard.build(model)
    check("both tabs are offered",
          page["layers"] == ["overview", "change", "entities", "areas",
                             "outlook", "detail"], page["layers"])
    check("the scoped view defers rather than repeating unscoped rows",
          (page["views"][1]["layers"]["change"] or {}).get("pointer"))

    html = dashboard_html.render(page, eyebrow="Inventory")
    check("exactly one script tag - nesting them kills every one of them",
          html.count("<script") == 1, html.count("<script"))
    check("the rail lists both new tabs",
          'data-layer="change"' in html and 'data-layer="outlook"' in html)
    check("the refusal to compare totals is on the page, not only in the model",
          "not compared" in html.lower())
    check("the comparison window is named",
          "14 August" in html and "23 August" in html)
    check("the page stays self-contained", "http://" not in html
          and "https://" not in html and "<img" not in html)
    check("tables carry the shared styling rather than rendering bare",
          "<table>" not in html, "an unstyled <table> reached the document")
    check("content is escaped",
          "<script>alert" not in dashboard_html.render(
              dashboard.build({**model, "report_name": "<script>alert(1)</script>"})))

def main() -> int:
    print("=" * 72)
    print("WP5 Stock Age Analysis")
    print("=" * 72)

    test_ordinal_axis()
    test_distribution_reconciles()
    test_undetermined_band()
    test_risk_split()
    test_migration_refuses()
    test_report_model()
    test_rendering()
    test_dashboard()
    test_published_summary_contract()
    test_valuation_basis()
    test_comparison()
    test_comparison_refuses()
    test_position_from_scan()
    test_clearance()
    test_categories_rank_by_money()
    test_stuck_lines()
    test_optional_everywhere()
    test_new_layers_render()

    print("\n" + "=" * 72)
    if _failures:
        print(f"AGEING FAILED - {len(_failures)} check(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
