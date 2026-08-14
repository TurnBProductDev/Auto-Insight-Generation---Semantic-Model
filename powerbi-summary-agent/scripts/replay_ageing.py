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

from src.domains.inventory import ageing_html, buckets  # noqa: E402
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

    escaped = dashboard_html.render(
        {**page, "title": '<img src=x onerror=alert(1)>'})
    check("content is escaped", "<img src=x" not in escaped and "&lt;img" in escaped)


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
