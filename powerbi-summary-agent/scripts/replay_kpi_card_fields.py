"""Offline replay: the extended KPI tile fields (kpi-tile-schema-proposal.md).

Adds label / rawValue / unit / valueType / goodDirection / comparison{} /
target{} / shareOfTotalPct / rank to a KpiCard, gated by
``ai_content_kpi_card_fields`` (code default False) exactly the way
``reportId`` was added under ``ai_content_multi_report_feed`` -
see docs/phase5-app-contract-change.md for that precedent.

Two exit criteria:

1. **Flag off is byte-identical.** No new key appears, not even as an
   explicit null - same discipline as the reportId rollout.
2. **Flag on emits only what the signal actually supports.** A field the
   underlying signal cannot back (an unclassified "Performance" family, a
   share-branch card with no target, ...) stays absent rather than guessed.

No Power BI, Azure, or LLM credentials are required.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import api_payloads  # noqa: E402

FAILURES: list[str] = []
WHEN = datetime(2026, 8, 25, 9, 15, tzinfo=timezone.utc)


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}" + (f" - {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


LEGACY_KEYS = {
    "id", "severity", "category", "metric", "value", "delta", "deltaDirection",
    "description", "displayTime", "isoDate", "comparisonLabel", "insight",
}


def _text():
    return api_payloads._KpiCardText(
        signal_id="S1", category="Sales", description="Revenue fell in this area.",
        insight_title="Revenue fell", insight_summary="Revenue fell in this area.",
        insight_action="Review the area.",
    )


def _card(sig, *, report_id=None, extended=False, state=None, idx=1):
    return api_payloads._assemble_kpi_card(
        idx, sig, _text(), WHEN, report_id=report_id,
        extended_fields=extended, state=state,
    )


# --- fixtures, shaped like the real domain signals -----------------------
def _target_signal(target=3_010_000.0, val=-334_800.0, current=None, story_key="tt:ST2"):
    return {
        "id": "S1", "story_key": story_key, "affected_segment": "ST2",
        "dimension": "branch", "metric": "Sales against target",
        "metric_family": "revenue", "kind": "business",
        "impact_value": val, "target": target, "current": current,
        "comparison_label": "against its target for this month so far",
        "description": "ST2 is at 88.9% of its target for this month so far.",
    }


def _stock_signal(comparison_label="since 2026-08-01", val=90_700.0, family_hint="stock_value"):
    return {
        "id": "S2", "story_key": "ageing:24m", "affected_segment": "24+ MONTHS",
        "dimension": "bucket", "metric": "Stock value at ageing risk",
        "metric_family": family_hint, "kind": "business",
        "impact_value": val, "comparison_label": comparison_label,
        "description": "24+ MONTHS aged stock rose.",
    }


def _wow_signal(rolling=False, val=-45_900.0, previous=525_900.0):
    return {
        "id": "S3", "story_key": "wow:fashion", "affected_segment": "FASHION",
        "dimension": "category", "metric": "Net revenue",
        "impact_value": val, "kind": "business",
        "description": "FASHION net revenue fell week over week.",
        "recent_week": {
            "window_mode": "rolling" if rolling else "calendar",
            "change_pct": -8.7, "week_start": "2026-08-11", "week_end": "2026-08-17",
            "previous": previous, "actual": previous + val,
        },
    }


def _daily_incident_signal(val=-12_000.0, expected=100_000.0):
    return {
        "id": "S4", "story_key": "daily:2026-08-20", "affected_segment": "ST9",
        "impact_value": val, "kind": "business",
        "episode_start": "2026-08-20", "episode_end": "2026-08-20",
        "expected_total": expected, "description": "ST9 revenue dipped on 2026-08-20.",
    }


def _rate_signal(growth=42.0, median=6.0):
    return {
        "id": "S5", "story_key": "rate:gadgets", "affected_segment": "GADGETS",
        "kind": "business", "stat_basis": "robust_z", "reported_growth_pct": growth,
        "peer_median_reported_pct": median, "peer_count": 9,
        "description": "GADGETS revenue grew unusually fast relative to peers.",
    }


def _yoy_signal(current=480_000.0, prior=525_900.0, val=-45_900.0):
    return {
        "id": "S6", "story_key": "yoy:fashion", "affected_segment": "FASHION",
        "impact_value": val, "impact_share": 0.08, "current": current, "prior": prior,
        "kind": "business", "description": "FASHION revenue decreased.",
    }


def _share_signal(share=72.8, val=2_650_000.0):
    return {
        "id": "S7", "story_key": "share:st5", "affected_segment": "ST5",
        "impact_value": val, "impact_share": share, "kind": "business",
        "description": "ST5 revenue increased, accounting for a large share of the total increase.",
    }


def _dq_signal():
    return {
        "id": "S8", "story_key": "dq:recon", "affected_segment": "Reconciliation",
        "impact_value": 1200.0, "kind": "data_quality",
        "description": "A reconciliation check found a gap.",
    }


def _quantity_signal(val=3200.0):
    return {
        "id": "S9", "story_key": "qty:widgets", "affected_segment": "WIDGETS",
        "impact_value": val, "impact_share": 4.0, "current": 90000.0, "prior": 86800.0,
        "kind": "business", "description": "WIDGETS quantity sold increased.",
    }


def _unclassified_signal(val=17800.0):
    """The docs' own STOCK OUT example: a count on the "Performance" bucket -
    no metric_family, description carries none of the family keywords."""
    return {
        "id": "S10", "story_key": "queue:stockout", "affected_segment": "STOCK OUT - PLACE ORDER",
        "impact_value": val, "impact_share": 12.7, "kind": "business",
        "description": "STOCK OUT - PLACE ORDER count rose.",
    }


# --- 1. flag off is byte-identical -----------------------------------------
def test_flag_off_unchanged() -> None:
    print("\n[1] Flag off: card is byte-identical to today's contract")
    for sig in (_target_signal(), _stock_signal(), _wow_signal(), _yoy_signal(), _share_signal()):
        card = _card(sig, extended=False)
        check(f"no extended keys leak through ({sig['id']})",
              set(card) - (LEGACY_KEYS | {"reportId"}) == set(),
              str(set(card) - (LEGACY_KEYS | {"reportId"})))
    card = _card(_target_signal(), report_id="target_tracker", extended=False)
    check("multi-report mode without the new flag adds only reportId",
          set(card) == LEGACY_KEYS | {"reportId"}, str(set(card) ^ (LEGACY_KEYS | {"reportId"})))
    check("flag off by default", api_payloads.kpi_extended_fields({}) is False)
    check("flag reads from state", api_payloads.kpi_extended_fields({"ai_content_kpi_card_fields": True}))
    check("flag reads from config",
          api_payloads.kpi_extended_fields({"config": {"ai_content_kpi_card_fields": True}}))


# --- 2. label ---------------------------------------------------------------
def test_label() -> None:
    print("\n[2] label: dimension + segment + metric, never a lookup")
    card = _card(_target_signal(), extended=True)
    check("branch dimension + segment + metric",
          card["label"] == "Branch ST2 — Sales against target", card["label"])
    company = dict(_target_signal())
    company["dimension"], company["affected_segment"] = "company", "Company"
    card = _card(company, extended=True)
    check("a whole-population dimension is not prefixed onto the segment",
          not card["label"].lower().startswith("company company"), card["label"])
    no_metric = dict(_target_signal())
    no_metric.pop("metric")
    no_metric.pop("metric_family")
    card = _card(no_metric, extended=True)
    check("no metric name and no metric_family -> just the dimension + segment",
          card["label"] == "Branch ST2", card["label"])
    family_fallback = dict(_target_signal())
    family_fallback.pop("metric")
    card = _card(family_fallback, extended=True)
    check("no metric name but a declared metric_family -> falls back to it",
          card["label"] == "Branch ST2 - Revenue".replace(" - ", " — "), card["label"])
    # A whole-business finding carries no segment by design. The measure name
    # still names the number, and the tile has nothing else to fall back on -
    # `metric` is empty on that same card - so the label is the measure alone.
    no_segment = dict(_target_signal())
    no_segment["affected_segment"] = ""
    card = _card(no_segment, extended=True)
    check("no segment -> the measure name stands alone as the label",
          card.get("label") == "Sales against target", str(card.get("label")))
    leaky = dict(_target_signal())
    leaky["affected_segment"] = ""
    leaky["metric"] = "mis_deep_dive2::quantity"
    leaky.pop("metric_family", None)
    card = _card(leaky, extended=True)
    check("no segment + an internal metric identifier -> no label, never a leak",
          card.get("label") is None, str(card.get("label")))
    # Both found on the live SB Mart tiles by publishing and then reading them.
    from src.tools.api_payloads import _kpi_label
    dated = _kpi_label({"affected_segment": "All Locations", "dimension": "month",
                        "metric": "Damage Value"})
    check("a period is never prefixed to a name as if it were an entity",
          dated is not None and not dated.lower().startswith("month "), str(dated))
    leaky_label = _kpi_label({"affected_segment": "STOCK OUT - PLACE ORDER",
                              "dimension": "recommended_action",
                              "metric": "Loc-SKUs in a double-warning state"})
    check("internal vocabulary never reaches the label either",
          leaky_label is not None and "loc-sku" not in leaky_label.lower(),
          str(leaky_label))

    no_either = dict(_target_signal())
    no_either["affected_segment"] = ""
    no_either.pop("metric")
    card = _card(no_either, extended=True)
    check("no segment and no measure -> no label field at all",
          "label" not in card, str(card.get("label")))

    # Real bug caught on a live SB Mart Sales YoY run: the legacy path copies
    # dimension/metric straight from a deterministic candidate, where they are
    # internal identifiers - a raw DAX column reference (a LIST, not even a
    # string) for dimension, and a bundle key ("mis_deep_dive2::quantity") for
    # metric. Neither may leak into a reader-facing label.
    internal = {
        "id": "S11", "story_key": "yoy:concentration", "affected_segment": "PROVISIONS, REFRIDGERATED GOODS",
        "dimension": ["'mis_deep_dive2'[item_category_name]"], "metric": "mis_deep_dive2::quantity",
        "metric_family": None, "impact_share": 53.8, "impact_value": 12_328_375.7, "kind": "business",
        "description": "PROVISIONS and REFRIDGERATED GOODS concentrate current quantity.",
    }
    card = _card(internal, extended=True)
    check("a raw DAX dimension list never reaches the label",
          "[" not in card["label"] and "'" not in card["label"], card["label"])
    check("an internal bundle-key metric never reaches the label",
          "::" not in card["label"], card["label"])
    check("falls back to the segment alone when nothing readable is available",
          card["label"] == "PROVISIONS, REFRIDGERATED GOODS", card["label"])


# --- 3. rawValue -------------------------------------------------------------
def test_raw_value() -> None:
    print("\n[3] rawValue: the exact float behind the formatted string")
    card = _card(_target_signal(val=-334_800.0), extended=True)
    check("rawValue is the exact float, not the compacted string",
          card["rawValue"] == -334800.0, str(card["rawValue"]))
    check("value stays the pre-formatted display string",
          card["value"] == "-334.8K", card["value"])


# --- 4. unit / valueType -----------------------------------------------------
def test_unit_and_value_type() -> None:
    print("\n[4] unit / valueType: only for a classifiable family, never guessed")
    card = _card(_target_signal(), extended=True,
                 state={"config": {"target_tracker_currency": "QAR"}}, report_id="target_tracker")
    check("target_tracker revenue signal -> currency", card["valueType"] == "currency", card.get("valueType"))
    check("currency resolves from the report's own config key", card["unit"] == "QAR", card.get("unit"))

    card = _card(_stock_signal(), extended=True,
                 state={"config": {"ageing_currency": "USD"}}, report_id="stock_age_analysis")
    check("stock_value family -> currency too", card["valueType"] == "currency", card.get("valueType"))
    check("ageing currency resolves via its own config key", card["unit"] == "USD", card.get("unit"))
    check("stock_value carries no assumed direction", "goodDirection" not in card, str(card.get("goodDirection")))

    # The rule that matters most on this field: a currency nobody configured is
    # not published. It used to default to SAR here, which put that currency on
    # every unmapped report - a live client saw it beside a configured USD on
    # one Home strip, in neither country.
    card = _card(_target_signal(), extended=True, state=None, report_id=None)
    check("no report-specific currency and no generic override -> no unit at all",
          "unit" not in card, str(card.get("unit")))
    check("...and valueType still says what kind of number it is",
          card.get("valueType") == "currency", card.get("valueType"))
    card = _card(_target_signal(), extended=True,
                 state={"config": {"ai_content_kpi_currency": "AED"}}, report_id=None)
    check("generic ai_content_kpi_currency is the fallback for an unmapped report",
          card["unit"] == "AED", card.get("unit"))

    card = _card(_quantity_signal(), extended=True)
    check("quantity family -> count, no unit", card["valueType"] == "count", card.get("valueType"))
    check("count carries no currency unit", "unit" not in card, str(card.get("unit")))

    card = _card(_unclassified_signal(), extended=True)
    check("an unclassified 'Performance' signal gets no valueType",
          "valueType" not in card, str(card.get("valueType")))
    check("...and no unit either", "unit" not in card, str(card.get("unit")))


# --- 5. goodDirection ---------------------------------------------------------
def test_good_direction() -> None:
    print("\n[5] goodDirection: declared wins, family default, else absent")
    check("revenue family -> up is good", _card(_target_signal(), extended=True)["goodDirection"] == "up")
    check("quantity family -> up is good", _card(_quantity_signal(), extended=True)["goodDirection"] == "up")
    check("data_quality kind -> neutral", _card(_dq_signal(), extended=True)["goodDirection"] == "neutral")
    check("a rate outlier vs peers -> up is good", _card(_rate_signal(), extended=True)["goodDirection"] == "up")
    check("unclassified family -> no goodDirection asserted",
          "goodDirection" not in _card(_unclassified_signal(), extended=True))
    declared = dict(_unclassified_signal())
    declared["good_direction"] = "down"
    check("an explicit good_direction on the signal always wins",
          _card(declared, extended=True)["goodDirection"] == "down")


# --- 6. comparison ------------------------------------------------------------
def test_comparison() -> None:
    print("\n[6] comparison: type/label/baselineValue per branch, never fabricated")
    c = _card(_target_signal(), extended=True)["comparison"]
    check("target branch -> type=target", c["type"] == "target", str(c))
    check("target branch -> short chip label", c["label"] == "vs target", str(c))
    check("target branch -> baseline is the target value", c["baselineValue"] == 3_010_000.0, str(c))

    c = _card(_stock_signal(), extended=True)["comparison"]
    check("a declared comparison with no numeric target -> type=other", c["type"] == "other", str(c))
    check("...and no baseline fabricated for it", c.get("baselineValue") is None, str(c))

    c = _card(_wow_signal(rolling=False), extended=True)["comparison"]
    check("calendar week-over-week -> prior_period", c["type"] == "prior_period", str(c))
    check("calendar WoW baseline is last week's actual", c["baselineValue"] == 525_900.0, str(c))
    c = _card(_wow_signal(rolling=True), extended=True)["comparison"]
    check("rolling window -> prior_period with its own chip",
          c["type"] == "prior_period" and c["label"] == "vs prior 7 days", str(c))

    c = _card(_daily_incident_signal(), extended=True)["comparison"]
    check("a daily incident -> threshold vs the expected total", c["type"] == "threshold", str(c))
    check("...baseline is the expected total", c["baselineValue"] == 100_000.0, str(c))

    c = _card(_rate_signal(), extended=True)["comparison"]
    check("a peer-growth outlier -> peer_comparison", c["type"] == "peer_comparison", str(c))
    check("...baseline is the peer median", c["baselineValue"] == 6.0, str(c))

    c = _card(_yoy_signal(), extended=True)["comparison"]
    check("plain current/prior with no declared spine -> same_period_last_year",
          c["type"] == "same_period_last_year", str(c))
    check("...baseline is last year's figure", c["baselineValue"] == 525_900.0, str(c))

    card = _card(_share_signal(), extended=True)
    c = card["comparison"]
    check("a share-of-total card -> share_of_total", c["type"] == "share_of_total", str(c))
    check("share_of_total carries no baseline (nothing was subtracted from)",
          c.get("baselineValue") is None, str(c))


# --- 7. shareOfTotalPct --------------------------------------------------------
def test_share_of_total() -> None:
    print("\n[7] shareOfTotalPct: only for a genuine share-of-total card")
    card = _card(_share_signal(share=72.8), extended=True)
    check("share branch publishes shareOfTotalPct", card["shareOfTotalPct"] == 72.8, str(card.get("shareOfTotalPct")))
    # A target-tracker signal can ALSO carry an impact_share (attainment gap %,
    # a different meaning entirely) - it must never leak into shareOfTotalPct,
    # since the declared_comparison branch runs first and owns the card.
    tt = dict(_target_signal())
    tt["impact_share"] = 11.1
    card = _card(tt, extended=True)
    check("a target-tracker attainment gap is never mislabelled as shareOfTotalPct",
          "shareOfTotalPct" not in card, str(card.get("shareOfTotalPct")))


# --- 8. target ------------------------------------------------------------------
def test_target() -> None:
    print("\n[8] target: value + attainmentPct, matching the worked example")
    card = _card(_target_signal(target=3_010_000.0, val=-334_800.0), extended=True)
    check("target.value is the target figure", card["target"]["value"] == 3_010_000.0, str(card["target"]))
    # From the proposal's own worked example: target 3.01M, shortfall 334.8K
    # -> current 2,675,200 -> attainment 88.9%.
    check("attainmentPct matches the worked example (88.9%)",
          card["target"]["attainmentPct"] == 88.9, str(card["target"]))

    declared = _target_signal(target=3_010_000.0, val=-334_800.0)
    declared["current"] = None
    declared["attainment_pct"] = 91.2  # the domain's own number should win outright
    card = _card(declared, extended=True)
    check("a declared attainment_pct on the signal is used verbatim",
          card["target"]["attainmentPct"] == 91.2, str(card["target"]))

    card = _card(_share_signal(), extended=True)
    check("no target on the signal -> no target object at all", "target" not in card, str(card.get("target")))


# --- 9. rank ----------------------------------------------------------------------
def test_rank() -> None:
    print("\n[9] rank: the existing materiality order, exposed")
    check("rank is the run position", _card(_target_signal(), extended=True, idx=1)["rank"] == 1)
    check("...and tracks idx for a later card", _card(_target_signal(), extended=True, idx=4)["rank"] == 4)
    check("rank is absent with the flag off", "rank" not in _card(_target_signal(), extended=False, idx=1))


# --- 10. config catalogue ----------------------------------------------------------
def test_schema() -> None:
    print("\n[10] Config catalogue")
    from src import config_schema

    catalogued = config_schema.BY_KEY
    check("ai_content_kpi_card_fields is catalogued", "ai_content_kpi_card_fields" in catalogued)
    check("ai_content_kpi_currency is catalogued", "ai_content_kpi_currency" in catalogued)
    check("the flag defaults to OFF", catalogued["ai_content_kpi_card_fields"].default is False)
    check("the currency default is empty, not a guess",
          catalogued["ai_content_kpi_currency"].default == "")
    defaults = config_schema.state_defaults({})
    check("the flag is threaded into state", "ai_content_kpi_card_fields" in defaults)
    check("a config that predates the flag resolves to OFF",
          defaults["ai_content_kpi_card_fields"] is False)
    check("the currency key is threaded into state too", "ai_content_kpi_currency" in defaults)
    check("...and threads through as empty rather than as a currency",
          defaults.get("ai_content_kpi_currency") == "")


# --------------------------------------------------------------------------
# Card PROSE and STATS: what a store manager actually reads.
#
# Every case below is a card that shipped live to SB Mart on 2026-08-27 and was
# either meaningless or false. The signals are reproduced exactly as
# stock_health_signals emits them.
# --------------------------------------------------------------------------
DAMAGE_SIG = {
    "affected_segment": "All Locations", "segment_members": ["2026-08-01"],
    "dimension": "month", "metric": "Damage Value", "metric_family": "stock_value",
    "impact_value": 209333.0, "impact_share": 317.0, "value_kind": "level",
    "value_label": "Damage above the usual level",
    "share_label": "Above the 3-month average",
    "comparison_label": "against the average of the previous 3 months",
    "description": ("Damage in August 2026 was 275,371, 317.0% above the 66,038 "
                    "average of the previous 3 months."),
}
STOCKOUT_SIG = {
    "affected_segment": "STOCK OUT - PLACE ORDER",
    "segment_members": ["STOCK OUT - PLACE ORDER"],
    "dimension": "recommended_action",
    "metric": "Loc-SKUs in a double-warning state", "metric_family": "stock_value",
    "impact_value": 18344.0, "impact_share": 13.2, "value_kind": "level",
    "value_label": "Products in stores affected",
    "share_label": "Share of all products in stores",
    "comparison_label": "13.2% of all Loc-SKUs in the stock position",
    "description": ("18,344 Loc-SKUs are in STOCK OUT - PLACE ORDER, 13.2% of "
                    "the 139,388 in the position."),
}


def test_card_stats() -> None:
    print('\n' + "[card stats]")
    stats = {s["label"]: s["value"]
             for s in api_payloads._insight_stats(DAMAGE_SIG, "Performance")}

    # Shipped as `Segments: 2026-08-01` - a raw ISO date under a label
    # promising a business area.
    check("a date is never published under 'Segments'", "Segments" not in stats)
    check("the month is named after its own dimension", "Month" in stats)
    check("...and rendered as a month a manager recognises",
          stats.get("Month") == "August 2026", str(stats))

    # Shipped as `Share of performance increase: 317.0%`. No share exceeds 100%.
    check("a non-share percentage is not called a share",
          not any("Share" in k for k in stats), str(stats))
    check("it is named for what it measures",
          "Above the 3-month average" in stats, str(stats))

    # Shipped as `Performance change +209.3K` for a level.
    check("a level is not labelled a change",
          not any("change" in k.lower() for k in stats), str(stats))
    check("a level is published unsigned",
          stats.get("Damage above the usual level") == "209.3K", str(stats))

    out = {s["label"]: s["value"]
           for s in api_payloads._insight_stats(STOCKOUT_SIG, "Performance")}
    # Shipped as `Segments: STOCK OUT - PLACE ORDER` - the card's own heading.
    check("a segment stat repeating the card heading is dropped",
          "Recommended Action" not in out and "Segments" not in out, str(out))
    check("a genuine share keeps share wording",
          out.get("Share of all products in stores") == "13.2%", str(out))
    check("a count of products is named as such",
          out.get("Products in stores affected") == "18.3K", str(out))


def test_summary_is_grounded() -> None:
    print('\n' + "[card summary]")
    allowed = api_payloads._quotable_figures(DAMAGE_SIG, "Performance")
    check("the model is offered the real figures to quote",
          {"275,371", "66,038", "317.0%"} <= set(allowed), str(allowed))
    check("...and they reach the LLM with the signal facts",
          "quote_these_display_values" in api_payloads._signal_facts(DAMAGE_SIG))

    # The exact summary that shipped: no figure, so it carries no finding.
    shipped = ("The movement relates to damage across all locations. A breakdown "
               "by section and location should show where it was concentrated.")
    out = api_payloads._grounded_summary(DAMAGE_SIG, "Performance", shipped)
    check("a summary carrying no figure is replaced by the grounded sentence",
          "275,371" in out, out)

    invented = "Damage reached 999,999 this month, the highest on record."
    out = api_payloads._grounded_summary(DAMAGE_SIG, "Performance", invented)
    check("a summary quoting an invented figure is rejected",
          "999,999" not in out, out)

    good = ("Damage written off in August 2026 reached 275,371, more than four "
            "times the 66,038 monthly average of the last three months.")
    check("a grounded summary is kept verbatim",
          api_payloads._grounded_summary(
              DAMAGE_SIG, "Performance", good).startswith("Damage written off"))


def test_no_raw_values() -> None:
    print(chr(10) + "[raw values never quoted]")
    from src.tools.api_payloads import _is_display_figure
    # Every one of these reached a live SB Mart tile on 2026-08-27.
    for raw in ("1705150.8499", "640871.0", "13103971.9744", "71.9266%"):
        check(f"{raw} is not offered as a quotable figure",
              not _is_display_figure(raw))
    for good in ("264.6K", "400.6%", "66,053", "5.81M", "42.1%", "1,234.56"):
        check(f"{good} still is", _is_display_figure(good))

    # ...and a signal whose description carries raw floats offers none of them.
    sig = dict(DAMAGE_SIG)
    sig["description"] = ("Revenue rose by 1705150.8499 units across 640871.0 "
                          "transactions, a 71.9266% share.")
    offered = api_payloads._quotable_figures(sig, "Revenue")
    check("a description full of raw floats offers no raw float",
          all(_is_display_figure(f) for f in offered), str(offered))

    # A stat label must not carry an internal identifier: on the legacy path
    # `dimension` is a LIST holding a DAX column reference.
    leaky = dict(DAMAGE_SIG)
    leaky["dimension"] = ["'Mis Deep Dive2'[Store No]"]
    leaky["affected_segment"] = "ST1, ST4"
    leaky["segment_members"] = ["ST1", "ST4"]
    labels = [x["label"] for x in api_payloads._insight_stats(leaky, "Revenue")]
    check("a raw DAX reference never becomes a stat label",
          not any("[" in l or "'" in l for l in labels), str(labels))


def test_retail_vocabulary() -> None:
    print('\n' + "[retail vocabulary]")
    out = api_payloads._plain_business_text(
        "18,344 Loc-SKUs are in STOCK OUT. The assortment may suggest a "
        "broad-based issue with days of cover and stock above agreed cover.")
    for banned in ("Loc-SKU", "assortment", "broad-based", "days of cover"):
        check(banned + " never reaches a card", banned.lower() not in out.lower(), out)
    check("no doubled article from a blunt substitution", " the the " not in out, out)
    # Removing a hedge asserts a cause, which this branch may not do.
    check("a careful hedge is preserved, not stripped",
          "may suggest" in api_payloads._plain_business_text(
              "Concentration by division may suggest constrained reordering."))


def main() -> int:
    print("=" * 72)
    print("REPLAY: extended KPI tile fields (kpi-tile-schema-proposal.md)")
    print("=" * 72)
    test_flag_off_unchanged()
    test_label()
    test_raw_value()
    test_unit_and_value_type()
    test_good_direction()
    test_comparison()
    test_share_of_total()
    test_target()
    test_rank()
    test_schema()
    test_card_stats()
    test_summary_is_grounded()
    test_retail_vocabulary()
    test_no_raw_values()
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
