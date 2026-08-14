"""The code-owned page model for the interactive summary dashboard (R6).

Deterministic, pure functions - no state, no IO, no LLM. Summary-only; imports no
``insight_*`` module.

This module answers "what is on the page", and ``summary_dashboard_html`` answers
"what does it look like". Nothing here emits markup, and nothing in the renderer
computes a business figure.

**Why code owns the structure.** The R1-R5 summary lets the LLM choose the page
plan, which suits one deep story. This surface is a fixed four-layer briefing -
Overview, Entities, Areas, Detail - in two time views, where every layer must be
covered whether or not it has a headline. Leaving that to a prompt means a layer
silently disappears on a quiet day. So code lays out the page and guarantees
coverage; the LLM's only job is the prose *inside* slots that code has already
decided exist, and every slot has a grounded deterministic fallback so the page
ships even when authoring fails.

**Every figure is copied or derived arithmetically** from evidence the pipeline
already scanned: the Overall Performance families, the universe/coverage scans,
and the focus deep dives. This module never invents a number and never
zero-fills a missing one - an absent measure means an absent card, with the
reason recorded.
"""

from __future__ import annotations

import calendar
import math
from datetime import date
from typing import Any

from . import summary_calendar, summary_coverage, summary_levers, summary_rag

#: Layer keys in presentation order. Overview is always first and always present.
LAYERS = ("overview", "entities", "areas", "detail")

LAYER_TITLES = {
    "overview": "Overview",
    "entities": "Entities",
    "areas": "Areas",
    "detail": "Detail",
}

#: What to call a scanned member with no name. A model can carry rows whose
#: classification column is blank - on one live model 7.6% of revenue had no
#: department, section or category at all. Those rows are real trade and must stay in
#: the totals, but ``str(None)`` reaches the page as a row labelled "None", which
#: reads as a bug and tells the manager nothing. Naming it is the honest option:
#: the money is there, the classification is missing.
UNASSIGNED_LABEL = "Unassigned"

DEFAULT_TLDR_LIMIT = 5
DEFAULT_MOVERS_LIMIT = 5
DEFAULT_SPARKLINE_POINTS = 12


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def member_name(value: Any) -> str:
    """Display name for a scanned member, naming the unclassified bucket."""
    text = "" if value is None else str(value).strip()
    return text or UNASSIGNED_LABEL


def _compact(value: Any, decimals: int = 1) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    magnitude = abs(number)
    if magnitude >= 1_000_000_000:
        return f"{number / 1_000_000_000:.2f}B"
    if magnitude >= 1_000_000:
        return f"{number / 1_000_000:.{decimals}f}M"
    if magnitude >= 1_000:
        return f"{number / 1_000:.0f}K"
    return f"{number:.0f}"


def _signed_compact(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return ("+" if number >= 0 else "-") + _compact(abs(number))


def _pct(value: Any, decimals: int = 2) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:+.{decimals}f}%"


def _pts(value: Any, decimals: int = 2) -> str:
    number = _num(value)
    if number is None:
        return "n/a"
    return f"{number:+.{decimals}f} pts"


def _display(measure: dict) -> str:
    """Format a measure's level for a KPI card, by its declared unit."""
    value = _num(measure.get("current"))
    if value is None:
        return "n/a"
    unit = str(measure.get("unit") or "count")
    decimals = int(measure.get("decimals") or 0)
    if unit == "money" and decimals == 0:
        return _compact(value)
    if unit == "money":
        return f"{value:,.{decimals}f}"
    if unit == "items":
        return f"{value:.{decimals}f}"
    return _compact(value)


def period_label(value: Any, grain: Any = None) -> str:
    """Human month/period label. Month-of-year codes 1-12 become month names.

    A raw ``6`` in a manager-facing trend axis reads as a data artefact; the same
    conversion the R4 charts already apply is applied here so both surfaces agree.
    """
    number = _num(value)
    text = str(grain or "").casefold()
    if number is not None and float(number).is_integer() and "month" in text:
        index = int(number)
        if 1 <= index <= 12:
            return calendar.month_name[index]
    return str(value)


# ---------------------------------------------------------------------------
# Trend readers
# ---------------------------------------------------------------------------

def trend_series(trend: dict | None, points: int = DEFAULT_SPARKLINE_POINTS) -> list[float]:
    """The current-phase series from a summary-owned trend, oldest to newest."""
    if not trend:
        return []
    alias = (trend.get("value_aliases") or {}).get("current")
    if not alias:
        return []
    values = [
        _num(row.get(alias)) for row in trend.get("rows") or []
    ]
    return [value for value in values if value is not None][-max(1, int(points)):]


def dual_trend(trend: dict | None) -> dict | None:
    """Current vs prior series for the this-year-vs-last-year line chart.

    This is the visual that exposes a comparator effect - a dip against a spike
    in the same month last year - so it needs both phases, not just the level.
    """
    if not trend:
        return None
    aliases = trend.get("value_aliases") or {}
    current_alias, prior_alias = aliases.get("current"), aliases.get("prior")
    dimension = trend.get("dimension")
    if not (current_alias and prior_alias and dimension):
        return None
    labels: list[str] = []
    current: list[float] = []
    prior: list[float] = []
    for row in trend.get("rows") or []:
        current_value = _num(row.get(current_alias))
        prior_value = _num(row.get(prior_alias))
        if current_value is None or prior_value is None:
            continue
        labels.append(period_label(row.get(dimension), trend.get("grain")))
        current.append(current_value)
        prior.append(prior_value)
    if len(labels) < 2:
        return None
    return {
        "labels": labels,
        "series": [
            {"name": "Last year", "values": prior, "style": "reference"},
            {"name": "This year", "values": current, "style": "primary"},
        ],
        "grain": trend.get("grain"),
    }


def span_label(trend: dict | None, period: dict | None) -> str | None:
    """Name the span the scanned measures actually cover, e.g. "Jan-Jul 2026".

    The period context's ``grain`` is the *granularity of the time axis*, not the
    length of the reporting period - a month-grain scan over seven months is a
    year-to-date figure. Labelling that view "Month to date" (grain mistaken for
    span) tells the reader the headline covers one month when it covers seven.
    Returns ``None`` when the span cannot be established, so the caller falls back
    to a neutral label rather than asserting a wrong one.
    """
    if not trend:
        return None
    dimension = trend.get("dimension")
    if not dimension or "month" not in str(trend.get("grain") or "").casefold():
        return None
    months = sorted({
        int(value) for value in (
            _num(row.get(dimension)) for row in trend.get("rows") or []
        ) if value is not None and 1 <= int(value) <= 12
    })
    if not months:
        return None
    year = str((period or {}).get("data_as_of") or "")[:4]
    first, last = calendar.month_abbr[months[0]], calendar.month_abbr[months[-1]]
    span = first if first == last else f"{first}-{last}"
    return f"{span} {year}".strip()


def period_name(period: dict | None, month: int | None = None) -> str | None:
    """Name a reported month as a reader would, e.g. "July 2026".

    ``month`` is the month actually selected for the view. It is passed explicitly
    rather than read from ``period_anchor`` because the anchor is only a month at
    month grain - at day grain it is a date, and its month component is the
    in-progress one, not the month being reported.
    """
    data_as_of = str((period or {}).get("data_as_of") or "")
    anchor = str((period or {}).get("period_anchor") or "")
    stamp = data_as_of if len(data_as_of) >= 7 else anchor
    if month is None:
        if len(anchor) < 7:
            return None
        try:
            month = int(anchor[5:7])
        except ValueError:
            return None
    if not 1 <= int(month) <= 12:
        return None
    try:
        watermark = date.fromisoformat(stamp)
    except (TypeError, ValueError):
        try:
            return f"{calendar.month_name[int(month)]} {int(stamp[:4])}"
        except (TypeError, ValueError):
            return calendar.month_name[int(month)]
    year = watermark.year if int(month) <= watermark.month else watermark.year - 1
    return f"{calendar.month_name[int(month)]} {year}"


def month_is_complete(month: int, data_as_of: Any, today: Any = None) -> bool:
    """True when month ``month`` has finished **and** is safe to report as finished.

    Two independent tests, because either signal alone has been wrong on this
    model:

    * **elapsed vs the data watermark** - the month must have ended on or before
      ``data_as_of``. Needed because at day grain ``period_anchor`` is a date and
      its month component is the in-progress one.
    * **not the month we are living in** - a month containing ``today`` is never
      reportable as complete, whatever the watermark claims. Needed because a
      resolved axis can be a padded calendar or batch column whose maximum runs to
      a month end (``data_as_of`` came back as 2026-08-31 while real trade stopped
      around 2026-08-02), which makes the first test alone say "August is done".

    The year is inferred from the watermark: a month at or before its month belongs
    to that year, a later month to the year before, so a series that wraps a year
    boundary is judged correctly.
    """
    try:
        watermark = date.fromisoformat(str(data_as_of))
    except (TypeError, ValueError):
        return False
    if not 1 <= int(month) <= 12:
        return False
    month = int(month)
    year = watermark.year if month <= watermark.month else watermark.year - 1
    last_day = calendar.monthrange(year, month)[1]
    if date(year, month, last_day) > watermark:
        return False
    try:
        now = date.fromisoformat(str(today)) if today else None
    except (TypeError, ValueError):
        now = None
    if now is not None and (year, month) >= (now.year, now.month):
        return False
    return True


def latest_complete_period(trend: dict | None, period: dict | None) -> dict | None:
    """The trend row for the latest month that has genuinely **finished**.

    Completeness is computed from the calendar against ``data_as_of``, NOT taken
    from ``period_anchor``. The anchor is only a month when the resolver settled
    on month grain; at day grain it is a *date*, and reading its month component
    picked the in-progress month. On the live model that shipped "August 2026"
    holding two days of trade (1.12M) against a full prior August (2.33M) as a
    -51.98% headline - a partial-period artefact presented as a business result.

    Returns ``None`` when no month in the series has finished, so the caller
    reports nothing rather than a fraction of a period.
    """
    if not trend or not period:
        return None
    dimension = trend.get("dimension")
    if not dimension or "month" not in str(trend.get("grain") or "").casefold():
        return None
    data_as_of = period.get("data_as_of")
    complete: list[tuple[int, dict]] = []
    for row in trend.get("rows") or []:
        value = _num(row.get(dimension))
        if value is None or not 1 <= int(value) <= 12:
            continue
        if month_is_complete(int(value), data_as_of, (period or {}).get("today")):
            complete.append((int(value), dict(row)))
    if not complete:
        return None
    # Latest by position in the series, so a wrapped year still ends on the most
    # recent month rather than the highest month number.
    order = [
        int(_num(row.get(dimension)))
        for row in trend.get("rows") or []
        if _num(row.get(dimension)) is not None
    ]
    complete.sort(key=lambda item: order.index(item[0]) if item[0] in order else -1)
    return complete[-1][1]


def families_from_trend_row(row: dict | None, trend: dict | None) -> dict:
    """Single-period families from one trend row (revenue only, by construction).

    The overall trend carries the primary value family alone, so a view built
    from it can show revenue and its movement but *not* the three levers. The
    caller records that as a stated limitation rather than filling the gap.
    """
    if not row or not trend:
        return {}
    aliases = trend.get("value_aliases") or {}
    current = _num(row.get(aliases.get("current")))
    prior = _num(row.get(aliases.get("prior")))
    if current is None or prior is None:
        return {}
    change = current - prior
    return {
        "revenue": {
            "current": current,
            "prior": prior,
            "change": change,
            "change_pct": (change / abs(prior) * 100.0) if prior else None,
            "comparison": "the same period last year",
        }
    }


# ---------------------------------------------------------------------------
# Overview layer
# ---------------------------------------------------------------------------

def build_kpis(measures: dict, config: dict | None = None,
               series: dict | None = None) -> list[dict]:
    """One card per available core measure, in fixed reading order.

    Order is fixed so the same measure sits in the same place every day. A
    measure the model cannot supply is skipped entirely - never shown as zero.
    """
    order = ("revenue", "transactions", "units", "basket_value", "basket_size", "price")
    cards: list[dict] = []
    for key in order:
        measure = (measures or {}).get(key)
        if not measure:
            continue
        rag = summary_rag.verdict(key, measure.get("change_pct"), config)
        cards.append({
            "key": key,
            "label": measure.get("label") or key.replace("_", " ").title(),
            "value_display": _display(measure),
            "unit_suffix": "items" if key == "basket_size" else "",
            "current": measure.get("current"),
            "prior": measure.get("prior"),
            "change": measure.get("change"),
            "change_pct": measure.get("change_pct"),
            "change_display": _pct(measure.get("change_pct")),
            "direction": "up" if (_num(measure.get("change_pct")) or 0.0) >= 0 else "down",
            "rag": rag,
            "sparkline": list((series or {}).get(key) or []),
            "note": _kpi_note(key),
        })
    return cards


def _kpi_note(key: str) -> str:
    return {
        "revenue": "The headline result.",
        "transactions": "How many bills - the healthiest lever to grow.",
        "units": "Real demand, with price stripped out.",
        "basket_value": "Average spend per bill.",
        "basket_size": "Items per bill - the range at work.",
        "price": "Read with Basket Size; a rise is not automatically good.",
    }.get(key, "")


def declining_exposure(level: dict | None, config: dict | None = None) -> dict | None:
    """Share of areas in decline, paired with the revenue exposed to them.

    These two belong together: "half the categories are shrinking" is only
    alarming in proportion to how much business sits inside them.
    """
    if not level:
        return None
    rows = [row for row in level.get("rows") or [] if row.get("comparable")]
    if not rows:
        return None
    declining = [row for row in rows if str(row.get("direction")) == "down"]
    total_current = sum(abs(_num(row.get("current")) or 0.0) for row in rows)
    at_risk = sum(abs(_num(row.get("current")) or 0.0) for row in declining)
    count_share = len(declining) / len(rows) * 100.0
    revenue_share = (at_risk / total_current * 100.0) if total_current else None
    return {
        "role": level.get("role"),
        "declining_count": len(declining),
        "comparable_count": len(rows),
        "count_share_pct": count_share,
        "at_risk_revenue_share_pct": revenue_share,
        "count_rag": summary_rag.verdict(
            "declining_share", count_share, config, band_name="exposure"),
        "revenue_rag": summary_rag.verdict(
            "at_risk_share", revenue_share, config, band_name="exposure"),
    }


def build_signals(package: dict, bridge: dict | None, exposure: dict | None,
                  calendar_read: dict | None, config: dict | None = None) -> list[dict]:
    """The less-obvious readings a headline percentage hides.

    Only signals whose inputs exist are emitted; there is no padding to a fixed
    count, because a fabricated signal is worse than four real ones.
    """
    signals: list[dict] = []

    if calendar_read and calendar_read.get("comparator_effect"):
        event = calendar_read.get("event") or {}
        signals.append({
            "key": "calendar",
            "label": "Calendar effect",
            "value": str(event.get("name") or "Comparator shift"),
            "badge": "check first",
            "tone": "warning",
            "note": calendar_read.get("headline") or "",
        })

    contribution = package.get("contribution") or {}
    contribution_facts = contribution.get("facts") or []
    revenue_fact = next(
        (fact for fact in contribution_facts
         if "revenue" in str(fact.get("metric") or "").casefold()),
        None,
    )
    if revenue_fact:
        signals.append({
            "key": "new_entities",
            "label": f"{contribution.get('subject') or 'New entities'} revenue",
            "value": str(revenue_fact.get("display_value") or ""),
            "badge": "not growth",
            "tone": "warning",
            "note": (
                str(contribution.get("note") or "")
                + " It is shown for completeness and never counted as growth."
            ).strip(),
        })

    if exposure:
        share = exposure.get("count_share_pct")
        signals.append({
            "key": "declining_areas",
            "label": f"{str(exposure.get('role') or 'areas').title()} in decline",
            "value": f"{share:.1f}%" if _num(share) is not None else "n/a",
            "badge": f"{exposure.get('declining_count')} of {exposure.get('comparable_count')}",
            "tone": (exposure.get("count_rag") or {}).get("tone") or "neutral",
            "note": "Read alongside the revenue those areas carry, on the next card.",
        })
        revenue_share = exposure.get("at_risk_revenue_share_pct")
        if _num(revenue_share) is not None:
            signals.append({
                "key": "at_risk_revenue",
                "label": "Revenue in declining areas",
                "value": f"{revenue_share:.1f}%",
                "badge": "exposure",
                "tone": (exposure.get("revenue_rag") or {}).get("tone") or "neutral",
                "note": (
                    "The share of current business sitting inside areas that went "
                    "backwards - the size of the exposure, not a forecast."
                ),
            })

    quality = summary_levers.growth_quality(bridge)
    if quality:
        signals.append({
            "key": "growth_quality",
            "label": "Growth quality",
            "value": f"{quality['share_pct']:.0f}%",
            "badge": f"from {quality['lever_label']}",
            "tone": "warning" if quality["fragile"] else "positive",
            "note": quality["statement"],
        })
    return signals


# ---------------------------------------------------------------------------
# Entity layer (stores / branches)
# ---------------------------------------------------------------------------

def build_contributions(level: dict | None, overall_prior: float | None) -> dict | None:
    """Each member's contribution to the parent move, in points that sum to it.

    ``contribution_pts = member change / overall prior x 100``. Because every
    member of the level is present and the scan's sibling diagnostics reconcile,
    the points add up to the group percentage - which is the whole value of the
    view. ``sums_to`` records the arithmetic so a reader can check it.
    """
    if not level:
        return None
    rows = [row for row in level.get("rows") or [] if row.get("comparable")]
    base = _num(overall_prior)
    if not rows or not base:
        return None
    items = []
    for row in rows:
        change = _num(row.get("change"))
        if change is None:
            continue
        items.append({
            "member": member_name(row.get("member")),
            "contribution_pts": change / abs(base) * 100.0,
            "change": change,
            "change_pct": row.get("change_pct"),
            "current": row.get("current"),
            "severity": row.get("severity"),
            "direction": row.get("direction"),
            "business_share_pct": row.get("business_share_pct"),
        })
    if not items:
        return None
    items.sort(key=lambda item: -item["contribution_pts"])
    total = sum(item["contribution_pts"] for item in items)
    carrier = items[0] if items[0]["contribution_pts"] > 0 else None
    drag = items[-1] if items[-1]["contribution_pts"] < 0 else None
    note_parts = []
    if carrier:
        note_parts.append(
            f"{carrier['member']} carries the group ({_pts(carrier['contribution_pts'])})"
        )
    if drag:
        note_parts.append(f"{drag['member']} drags it ({_pts(drag['contribution_pts'])})")
    return {
        "role": level.get("role"),
        "items": items,
        "sums_to_pts": total,
        "sums_to": _pts(total),
        "carrier": carrier,
        "drag": drag,
        "note": " while ".join(note_parts) + "." if note_parts else None,
    }


#: A steady area is allowed to share the standard one-liner - the spec asks for
#: "its own specific story *or* a one-line no-material-change", not a manufactured
#: narrative for something that did not move. Validation exempts this sentence
#: from the duplicate-story check for exactly that reason.
NO_MATERIAL_CHANGE = "No material change this period; it tracked the rest of the level."

#: Rank spelled as a word. Digits are stripped before the story-distinctness check
#: (two stories differing only in their figures are still the same sentence), so a
#: numeric rank would be invisible to it while a spelled one is not.
_ORDINAL_WORDS = {
    2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth", 7: "seventh",
    8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth",
}


def _ordinal_word(rank: Any) -> str | None:
    number = _num(rank)
    return _ORDINAL_WORDS.get(int(number)) if number is not None else None


def _entity_story(row: dict, levers: dict | None, contribution_pts: float | None,
                  carrier: str | None = None, drag: str | None = None,
                  peer_median: float | None = None) -> str:
    """Grounded fallback story for one entity, led by what is distinctive about it.

    Not one template with the numbers swapped: the sentence is chosen by the
    entity's *situation* - carrying the level, dragging it, moving against its
    peers, mattering by weight rather than by rate, or a sharp percentage on a
    small base. Two entities share wording only when they genuinely share a
    situation, and a steady one gets the honest one-liner instead of invented
    narrative. This is the floor the LLM improves on, never a placeholder.
    """
    name = member_name(row.get("member"))
    move = _pct(row.get("change_pct"))
    absolute = _signed_compact(row.get("change"))
    share = _num(row.get("business_share_pct"))
    peer = _num(row.get("vs_peer_median_pts"))
    severity = str(row.get("severity") or "steady")

    if levers and levers.get("reconciles"):
        pieces = [
            f"{label} {_pct((levers.get('levers') or {}).get(key))}"
            for key, label in (("transactions", "transactions"),
                               ("basket_size", "basket size"),
                               ("price", "price and mix"))
            if _num((levers.get("levers") or {}).get(key)) is not None
        ]
        return (
            f"Revenue {move} ({absolute}): {', '.join(pieces)} - "
            f"{str(levers.get('state') or '').lower()}."
        )

    if not row.get("comparable"):
        return (
            f"{absolute.lstrip('+-')} of current trade with no prior period behind it, "
            "so it is reported for completeness and never as growth."
        )

    if carrier and name == carrier:
        return (
            f"The largest single lift in the level: {move} adds {absolute}, "
            f"{_pts(contribution_pts)} of the group's move."
        )
    if drag and name == drag:
        return (
            f"The heaviest drag in the level: {move} removes {absolute}, "
            f"{_pts(contribution_pts)} off the group's move."
        )
    if peer is not None and abs(peer) >= 3.0:
        # ``vs_peer_median_pts`` is an unsigned distance, so the direction has to
        # come from comparing the member's own move with the level median.
        own = _num(row.get("change_pct"))
        heading = "behind"
        if peer_median is not None and own is not None and own >= peer_median:
            heading = "ahead of"
        return (
            f"Moving against the level - {move} is {abs(peer):.1f} points {heading} "
            f"the rest of it, worth {absolute}."
        )
    if share is not None and share >= 15.0 and abs(_num(row.get("change_pct")) or 0.0) < 2.0:
        return (
            f"Weight rather than rate: {move} looks quiet, but on {share:.1f}% of the "
            f"business it still moves {absolute}."
        )
    if share is not None and share < 2.0 and abs(_num(row.get("change_pct")) or 0.0) >= 10.0:
        return (
            f"A sharp {move} on a small base - {share:.1f}% of the business, so the "
            f"money effect is {absolute}."
        )
    if severity == "steady":
        return NO_MATERIAL_CHANGE
    # Last resort: state where this movement sits in the level. On a small level
    # whose members genuinely moved alike, rank IS the distinguishing fact - and
    # spelling the ordinal as a word keeps neighbouring stories textually distinct
    # as well as informative, so the distinctness check has something real to see.
    ordinal = _ordinal_word(row.get("rank"))
    if ordinal:
        return (
            f"The {ordinal} largest movement in the level: {move} ({absolute})"
            + (f" on {share:.1f}% of the business." if share is not None else ".")
        )
    return (
        f"{move} ({absolute}) on {share:.1f}% of the business."
        if share is not None else f"{move} ({absolute})."
    )


def build_entity_cards(level: dict | None, contributions: dict | None,
                       lever_rows: dict | None = None,
                       narratives: dict | None = None,
                       limit: int | None = None) -> list[dict]:
    """One card per entity, ranked by the coverage score, each with its own story.

    Ranking is the existing blended coverage score (impact x magnitude x
    unexpectedness), so "how far it pulls from the rest of the estate" decides
    the order - not size alone.
    """
    if not level:
        return []
    by_member = {
        str(item.get("member")): item for item in (contributions or {}).get("items") or []
    }
    carrier = str(((contributions or {}).get("carrier") or {}).get("member") or "") or None
    drag = str(((contributions or {}).get("drag") or {}).get("member") or "") or None
    cards: list[dict] = []
    rows = list(level.get("rows") or [])
    if limit:
        rows = rows[: max(0, int(limit))]
    for row in rows:
        name = member_name(row.get("member"))
        levers = (lever_rows or {}).get(name)
        contribution = by_member.get(name) or {}
        authored = (narratives or {}).get(name) or {}
        cards.append({
            "member": name,
            "comparable": bool(row.get("comparable")),
            "current": row.get("current"),
            "current_display": _compact(row.get("current")),
            "change_pct": row.get("change_pct"),
            "change_display": _pct(row.get("change_pct")),
            "change": row.get("change"),
            "severity": row.get("severity"),
            "rank": row.get("rank"),
            "business_share_pct": row.get("business_share_pct"),
            "vs_peer_median_pts": row.get("vs_peer_median_pts"),
            "state": (levers or {}).get("state"),
            "levers": (levers or {}).get("levers"),
            "lever_effects": (levers or {}).get("effects"),
            "contribution_pts": contribution.get("contribution_pts"),
            "contribution_display": (
                _pts(contribution.get("contribution_pts"))
                if contribution.get("contribution_pts") is not None else None
            ),
            "story": str(authored.get("story") or "").strip()
                     or _entity_story(row, levers, contribution.get("contribution_pts"),
                                      carrier, drag,
                                      _num(level.get("peer_median_change_pct"))),
            "authored": bool(str(authored.get("story") or "").strip()),
            "rag": summary_rag.verdict("revenue", row.get("change_pct")),
        })
    return cards


# ---------------------------------------------------------------------------
# Area layer (the rotating spotlight) and Detail layer
# ---------------------------------------------------------------------------

def _deep_dive_rows(evidence: dict | None, section: str) -> list[dict]:
    sections = (evidence or {}).get("sections") or {}
    block = sections.get(section) or {}
    if isinstance(block, dict):
        return list(block.get("rows") or [])
    return []


def build_spotlight(focuses: list[dict], evidence_by_key: dict | None = None,
                    narratives: dict | None = None,
                    coverage: dict | None = None) -> dict:
    """The rotating deep-dive subset, reusing the R4 portfolio and its evidence.

    The spotlight is *already* chosen and already evidenced upstream; this only
    presents it. Saying so on the page matters - a reader who does not know the
    subset rotates will read an unmentioned department as unimportant.
    """
    entries: list[dict] = []
    evidence_by_key = evidence_by_key or {}
    for focus in focuses or []:
        key = str(focus.get("focus_key") or "")
        evidence = evidence_by_key.get(key) or {}
        authored = (narratives or {}).get(key) or {}
        facts = [
            fact for fact in (evidence.get("facts") or [])
            if fact.get("display_value")
        ]
        entries.append({
            "focus_key": key,
            "segment": focus.get("segment"),
            "role": focus.get("dimension_role"),
            "lens": focus.get("lens"),
            "sentiment": focus.get("sentiment") or (focus.get("selection") or {}).get("sentiment"),
            "headline": str(authored.get("headline") or "").strip()
                        or str(focus.get("title_hint") or focus.get("segment") or ""),
            "connect": str(authored.get("connect") or "").strip(),
            "facts": facts,
            "contributors": _deep_dive_rows(evidence, "internal_contributors"),
            "location": _deep_dive_rows(evidence, "location"),
            "trend": ((evidence.get("sections") or {}).get("period_trend")),
            "signature_duplicate": bool(evidence.get("signature_duplicate")),
        })
    total_areas = None
    for level in (coverage or {}).get("levels") or []:
        if entries and str(level.get("role")) == str(entries[0].get("role")):
            total_areas = (level.get("counts") or {}).get("total")
            break
    return {
        "entries": entries,
        "count": len(entries),
        "total_in_level": total_areas,
        "rotates_note": (
            f"{len(entries)} of {total_areas} areas are put under the lens today; the "
            "selection rotates, so an area missing here is not an area with nothing "
            "happening. Every area is still ranked in full coverage below."
            if total_areas else
            "The deep-dive selection rotates between runs; every area is still ranked "
            "in full coverage below."
        ),
    }


def build_movers(coverage: dict | None, roles: list[str] | None = None,
                 limit: int = DEFAULT_MOVERS_LIMIT,
                 restrict_to_paths: list[list[str]] | None = None) -> dict:
    """Top growth and de-growth rows, with each row's share-of-business shift.

    ``restrict_to_paths`` keeps the Detail layer under the spotlight, as the spec
    requires, by matching hierarchy-path ancestry rather than name equality.
    """
    pool: list[dict] = []
    for level in (coverage or {}).get("levels") or []:
        if roles and str(level.get("role")) not in roles:
            continue
        comparable = [row for row in level.get("rows") or [] if row.get("comparable")]
        # Level totals from the level's own comparable members, so the share
        # denominators are like-for-like on both sides of the comparison.
        level_current = sum(_num(row.get("current")) or 0.0 for row in comparable) or None
        level_prior = sum(_num(row.get("prior")) or 0.0 for row in comparable) or None
        for row in comparable:
            if restrict_to_paths and not _under_any(row.get("hierarchy_path") or [],
                                                   restrict_to_paths):
                continue
            pool.append({
                **row,
                "role": level.get("role"),
                "__level_current": level_current,
                "__level_prior": level_prior,
            })
    # Ranked by the blended coverage score, NOT by raw percentage. Sorting movers
    # on percentage alone reproduces exactly the failure the coverage ranking
    # exists to prevent: a category worth a rounding error posts a four-figure
    # percentage on a near-zero base and leads the list ahead of a real movement.
    growth = sorted(
        (row for row in pool if (_num(row.get("change_pct")) or 0.0) > 0),
        key=lambda row: -float(row.get("rank_score") or 0.0),
    )[: max(0, int(limit))]
    decline = sorted(
        (row for row in pool if (_num(row.get("change_pct")) or 0.0) < 0),
        key=lambda row: -float(row.get("rank_score") or 0.0),
    )[: max(0, int(limit))]
    return {
        "growth": [_mover(row, row.get("__level_current"), row.get("__level_prior"))
                   for row in growth],
        "decline": [_mover(row, row.get("__level_current"), row.get("__level_prior"))
                    for row in decline],
        "restricted": bool(restrict_to_paths),
        "pool_size": len(pool),
    }


def _under_any(path: list, ancestors: list[list[str]]) -> bool:
    normalized = [str(part).strip().casefold() for part in path or []]
    for ancestor in ancestors or []:
        prefix = [str(part).strip().casefold() for part in ancestor or []]
        if not prefix:
            continue
        if normalized[: len(prefix)] == prefix:
            return True
        # A spotlight named by its leaf still matches its own descendants.
        if prefix[-1] in normalized:
            return True
    return False


def _mover(row: dict, level_current: float | None = None,
           level_prior: float | None = None) -> dict:
    """One mover row, including the share-of-level shift a growth percentage hides.

    Share shift is ``share now - share before`` in points, using the level's own
    comparable totals as the denominator on each side. A category can grow in
    money terms and still lose share of its parent, and only this column shows it.
    """
    current, prior = _num(row.get("current")), _num(row.get("prior"))
    share_now = _num(row.get("business_share_pct"))
    share_shift = None
    if None not in (current, prior, level_current, level_prior) and level_current and level_prior:
        share_shift = (current / level_current - prior / level_prior) * 100.0
    return {
        "member": member_name(row.get("member")),
        "role": row.get("role"),
        "path": list(row.get("hierarchy_path") or []),
        # Nearest DISTINCT ancestor: on a model with a mirrored level the raw
        # parent equals the grandparent, so the label would repeat the same name.
        "parent": next(
            (
                str(part) for part in reversed(list(row.get("hierarchy_path") or [])[:-1])
                if str(part).strip()
                and str(part).strip().casefold() != str(row.get("member") or "").strip().casefold()
            ),
            None,
        ),
        "change_pct": row.get("change_pct"),
        "change_display": _pct(row.get("change_pct")),
        "change": row.get("change"),
        "change_abs_display": _signed_compact(row.get("change")),
        "current": current,
        "business_share_pct": share_now,
        "severity": row.get("severity"),
        "rank_score": row.get("rank_score"),
        "share_shift_pts": share_shift,
        "share_shift_display": _pts(share_shift) if share_shift is not None else None,
    }


# ---------------------------------------------------------------------------
# TL;DR
# ---------------------------------------------------------------------------

def build_tldr(coverage: dict | None, bridge: dict | None, measures: dict | None,
               calendar_read: dict | None, contributions: dict | None,
               limit: int = DEFAULT_TLDR_LIMIT,
               entity_role: str | None = None) -> list[dict]:
    """The ranked cross-report headline, each item pointing at the layer that explains it.

    Ordering is deliberate rather than purely score-based at the top: when a
    comparator effect is detected it leads, because every other reading in the
    view has to be interpreted through it. Everything after that is the coverage
    ranking, which already blends impact, magnitude and unexpectedness.
    """
    items: list[dict] = []

    if calendar_read and calendar_read.get("comparator_effect"):
        items.append({
            "tone": "warning",
            "layer": "entities",
            "text": calendar_read.get("headline") or "",
            "to": "Entities",
        })

    # A tough-band measure going backwards while revenue rises is the single most
    # commonly missed reading, so it is stated before the level detail.
    revenue = (measures or {}).get("revenue") or {}
    units = (measures or {}).get("units") or {}
    revenue_pct, units_pct = _num(revenue.get("change_pct")), _num(units.get("change_pct"))
    if revenue_pct is not None and units_pct is not None and units_pct < 0 <= revenue_pct:
        items.append({
            "tone": "critical",
            "layer": "overview",
            "text": (
                f"Revenue rose {_pct(revenue_pct)} but we sold {_pct(units_pct)} fewer "
                "items, so the growth is price and footfall rather than real demand."
            ),
            "to": "Overview",
        })

    for exception in (calendar_read or {}).get("exceptions", [])[:2]:
        items.append({
            "tone": "critical",
            "layer": "entities",
            "text": (
                f"{exception['member']} is {_pct(exception['change_pct'])} and {exception['why']}."
            ),
            "to": "Entities",
        })

    for mover in summary_coverage.top_movers(coverage or {}, limit=limit):
        role = str(mover.get("role") or "area")
        # Route to the layer that actually explains this row: whichever role the
        # view chose as its entity level lives on the Entities page, everything
        # else on Areas. Hardcoding "store"/"branch" here would misroute every
        # model that calls its estate level something else.
        layer = "entities" if entity_role and role == str(entity_role) else "areas"
        items.append({
            "tone": "critical" if str(mover.get("direction")) == "down" else "positive",
            "layer": layer,
            "text": (
                f"{mover.get('member')} ({role}) is {_pct(mover.get('change_pct'))}, "
                f"{_signed_compact(mover.get('change'))} of business."
            ),
            "to": LAYER_TITLES[layer],
        })

    if contributions and contributions.get("note"):
        items.append({
            "tone": "positive" if (contributions.get("carrier") or {}) else "warning",
            "layer": "entities",
            "text": contributions["note"],
            "to": "Entities",
        })

    # A view's executive summary must state that view's own headline result. The
    # tough-band tension above only fires when units are available, so a view
    # reporting revenue alone would otherwise open with a member finding and never
    # name its own top-line movement.
    if revenue_pct is not None and not any(item["layer"] == "overview" for item in items):
        # After any comparator caveat, never before it: when the comparator moved,
        # every other reading in the view has to be interpreted through that fact,
        # so it keeps the lead.
        position = 1 if items and items[0].get("layer") == "entities" and (
            calendar_read or {}).get("comparator_effect") else 0
        items.insert(position, {
            "tone": "positive" if revenue_pct >= 0 else "critical",
            "layer": "overview",
            "text": (
                f"Revenue is {_pct(revenue_pct)} "
                f"({_signed_compact(revenue.get('change'))}) against the comparison period."
            ),
            "to": "Overview",
        })

    seen: set[str] = set()
    ranked: list[dict] = []
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        item["rank"] = len(ranked) + 1
        ranked.append(item)
        if len(ranked) >= max(1, int(limit)):
            break
    return ranked


# ---------------------------------------------------------------------------
# View and page assembly
# ---------------------------------------------------------------------------

def build_view(
    key: str,
    label: str,
    package: dict | None,
    coverage: dict | None,
    period: dict | None = None,
    config: dict | None = None,
    entity_role: str | None = None,
    exposure_role: str | None = None,
    focuses: list[dict] | None = None,
    evidence_by_key: dict | None = None,
    narratives: dict | None = None,
    lever_rows: dict | None = None,
    reference_members: list[dict] | None = None,
    families_override: dict | None = None,
    trend_override: dict | None = None,
    scan_label_hint: str | None = None,
    coverage_override: dict | None = None,
) -> dict:
    """Assemble one complete time view across all four layers.

    ``coverage_override`` gives a narrower view its **own** period-scoped member
    breakdown. With it, the view owns its layers like any other; without it, the
    view is honest that the breakdown belongs to the wider span.
    """
    config = config or {}
    package = package or {}
    families = families_override if families_override is not None else (
        package.get("families") or {})
    if coverage_override is not None:
        coverage = coverage_override
    trend = trend_override if trend_override is not None else package.get("trend")
    measures = summary_levers.derived_measures(families)
    bridge = summary_levers.three_lever_bridge(
        families, float(config.get("summary_focus_reconciliation_tolerance_pct", 2))
    )
    limitations: list[str] = []
    if measures and not bridge:
        limitations.append(
            "The three-lever split needs revenue, units and transactions together; "
            "this view reports the measures the model exposes for the period."
        )

    levels = {str(level.get("role")): level for level in (coverage or {}).get("levels") or []}
    entity_level = levels.get(str(entity_role)) if entity_role else None
    exposure_level = (
        levels.get(str(exposure_role)) if exposure_role
        else (list(levels.values())[-1] if levels else None)
    )
    if entity_role and not entity_level:
        limitations.append(
            f"No prior-year scan was available for the {entity_role} level, so the "
            "entity layer reports what was scanned rather than an estate breakdown."
        )

    # A view whose measures are overridden reports a NARROWER period than the one
    # the universe/coverage scans cover. The per-member scan runs once per run, at
    # the wider span, so this view simply **does not own** a breakdown by area.
    #
    # It used to show the wider period's breakdown under a caveat. That was worse
    # than showing nothing: the reader saw the same 13 rows twice in one document,
    # under a note explaining they did not describe the period named in the toggle.
    # Now the breakdown layers point at the view that does own them, once.
    # A view owns its breakdowns when it is the primary view, or when it was given
    # its own period-scoped scan. Only a narrower view *without* one has to defer.
    derived_period = families_override is not None and coverage_override is None
    scan_measures = summary_levers.derived_measures(package.get("families") or {})
    owner_label = str(scan_label_hint or "the wider period").strip()
    pointer = (
        f"The breakdown by area is scanned once per run, across {owner_label}. "
        f"Switch to the {owner_label} view to see it - repeating it here would show "
        "the same rows against a period they do not describe."
    ) if derived_period else None

    if derived_period:
        # The estate-wide comparator test needs THIS period's member movements.
        # They were never scanned, so the test is not run rather than run on the
        # wider period's rows and labelled as this one's.
        calendar_read = {
            "comparator_effect": False,
            "verdict": {
                "uniform_move": False,
                "reason": (
                    "the estate-wide check needs per-area movements for this period, "
                    "which this run did not scan"
                ),
                "checks": {},
            },
            "event": None,
            "exceptions": [],
            "headline": None,
            "exceptions_note": None,
        }
        contributions = None
    else:
        calendar_members = list((entity_level or exposure_level or {}).get("rows") or [])
        calendar_read = summary_calendar.build(
            calendar_members, period, config, reference_members)
        contributions = build_contributions(
            entity_level, (measures.get("revenue") or {}).get("prior"))

    if derived_period:
        spotlight = {"entries": [], "count": 0, "total_in_level": None,
                     "rotates_note": None}
        movers = {"growth": [], "decline": [], "restricted": False, "pool_size": 0}
        entity_cards = []
        exposure = None
    else:
        spotlight = build_spotlight(focuses or [], evidence_by_key,
                                    (narratives or {}).get("areas"), coverage)
        spotlight_paths = [
            list(entry.get("segment") and [entry["segment"]] or [])
            for entry in spotlight.get("entries") or []
        ]
        detail_roles = [
            role for role, level in levels.items()
            if entity_role != role and (level.get("level") or 0) >= 30
        ]
        movers = build_movers(
            coverage,
            roles=detail_roles or None,
            limit=int(config.get("summary_dashboard_movers", DEFAULT_MOVERS_LIMIT)),
            restrict_to_paths=[path for path in spotlight_paths if path] or None,
        )
        if movers.get("restricted") and not (movers["growth"] or movers["decline"]):
            # Never show an empty Detail layer when unrestricted rows exist - fall
            # back to the whole level and say the spotlight filter was dropped.
            movers = build_movers(
                coverage, roles=detail_roles or None,
                limit=int(config.get("summary_dashboard_movers", DEFAULT_MOVERS_LIMIT)),
            )
            movers["spotlight_filter_dropped"] = True
        exposure = declining_exposure(exposure_level, config)
        entity_cards = build_entity_cards(
            entity_level, contributions, lever_rows, (narratives or {}).get("entities"))

    # An unclassified bucket in the entity level means the breakdown does not add to
    # the company total on its own. Say so once, rather than letting the page imply
    # the areas account for everything.
    unassigned = next(
        (card for card in entity_cards
         if str(card.get("member")) == UNASSIGNED_LABEL), None)
    if unassigned:
        share = _num(unassigned.get("business_share_pct"))
        limitations.append(
            f"{_pct(share, 1).lstrip('+') if share is not None else 'Some'} of "
            f"{entity_role or 'area'} revenue carries no classification in the model and "
            f"is shown as \"{UNASSIGNED_LABEL}\". It is included in every total, so the "
            "company figures are complete; the named areas alone are not."
        )

    revenue = measures.get("revenue") or {}
    hero_authored = ((narratives or {}).get("hero") or {})
    return {
        "key": key,
        "label": label,
        "period": {
            "data_as_of": period.get("data_as_of") if period else None,
            "grain": (period or {}).get("grain"),
            "freshness_status": (period or {}).get("freshness_status"),
            "period_anchor": (period or {}).get("period_anchor"),
            "comparison": package.get("comparison") or "the same period last year",
        },
        "hero": {
            "state": (bridge or {}).get("state"),
            "verdict_tag": _verdict_tag(bridge, calendar_read, measures),
            "headline": str(hero_authored.get("headline") or "").strip()
                        or _hero_headline(measures, bridge, calendar_read),
            "narrative": str(hero_authored.get("narrative") or "").strip()
                         or _hero_narrative(measures, bridge, calendar_read,
                                            trend, period),
            "levers": [
                {
                    "key": lever,
                    "label": summary_levers.LEVER_LABELS[lever],
                    "change_pct": ((bridge or {}).get("levers") or {}).get(lever),
                    "display": _pct(((bridge or {}).get("levers") or {}).get(lever)),
                    "effect": ((bridge or {}).get("effects") or {}).get(lever),
                    "effect_display": _signed_compact(
                        ((bridge or {}).get("effects") or {}).get(lever)),
                }
                for lever in ("transactions", "basket_size", "price")
                if bridge
            ],
            "waterfall": summary_levers.waterfall_steps(
                bridge, revenue.get("prior"), revenue.get("current")),
            "dual_trend": dual_trend(trend),
            "reconciles": bool((bridge or {}).get("reconciles")),
            "reconciliation_note": (bridge or {}).get("note"),
        },
        "kpis": build_kpis(measures, config, {"revenue": trend_series(trend)}),
        "signals": build_signals(package, bridge, exposure, calendar_read, config),
        "calendar": calendar_read,
        "layers": {
            "overview": {"available": bool(measures)},
            "entities": {
                "role": entity_role,
                "available": bool(entity_cards),
                "contributions": contributions,
                "cards": entity_cards,
                "new_entities": package.get("contribution") if not derived_period else None,
                "pointer": pointer,
            },
            "areas": {"available": bool(spotlight.get("entries")),
                      "pointer": pointer, **spotlight},
            "detail": {"available": bool(movers["growth"] or movers["decline"]),
                       "pointer": pointer, "coverage_owned": not derived_period,
                       **movers},
        },
        # A derived view gets no coverage rows: its headline reports what it owns
        # (its own top line), not the wider period's members relabelled.
        "tldr": build_tldr(None if derived_period else coverage,
                           bridge, measures, calendar_read, contributions,
                           int(config.get("summary_dashboard_tldr", DEFAULT_TLDR_LIMIT)),
                           entity_role=entity_role),
        "bridge": bridge,
        "measures": measures,
        "exposure": exposure,
        # Counts derived from the scanned trend rows. Present in the model so any
        # sentence quoting them passes the grounding check.
        "period_context": period_context(trend, period),
        "limitations": limitations,
        # Which period the per-area breakdowns describe, and the scanned totals
        # they are measured against. Present so the written artifact can be
        # audited on its own, without re-deriving anything from the pipeline.
        "period_scope": "own" if not derived_period else "overview_only",
        "owns_breakdowns": not derived_period,
        "breakdown_owner": owner_label if derived_period else None,
        "scan_reference": {
            "span": owner_label,
            "revenue": scan_measures.get("revenue"),
        } if derived_period else None,
    }


def _verdict_tag(bridge: dict | None, calendar_read: dict | None,
                 measures: dict | None) -> str:
    if calendar_read and calendar_read.get("comparator_effect"):
        return "Calendar effect - check the comparator"
    units = _num(((measures or {}).get("units") or {}).get("change_pct"))
    revenue = _num(((measures or {}).get("revenue") or {}).get("change_pct"))
    if units is not None and revenue is not None and units < 0 <= revenue:
        return "Price masking - watch real demand"
    quality = summary_levers.growth_quality(bridge)
    if quality and quality.get("fragile"):
        return f"One lever carrying the result - {quality['lever_label']}"
    if not bridge:
        # "Broad-based read" would claim the levers were checked and agreed. With
        # no lever split available, nothing has been read broadly.
        return "Top line only for this period"
    return "Broad-based read"


def _hero_headline(measures: dict, bridge: dict | None,
                   calendar_read: dict | None) -> str:
    revenue = (measures or {}).get("revenue") or {}
    move = _pct(revenue.get("change_pct"))
    if calendar_read and calendar_read.get("comparator_effect"):
        return f"Revenue is {move}, but the comparator moved - read the calendar first"
    units = _num(((measures or {}).get("units") or {}).get("change_pct"))
    if units is not None and units < 0 <= (_num(revenue.get("change_pct")) or 0.0):
        return f"Revenue is {move}, but we sold fewer items than last year"
    if bridge and bridge.get("state"):
        return f"Revenue is {move} - {str(bridge['state']).lower()}"
    return f"Revenue is {move} versus the comparison period"


def period_context(trend: dict | None, period: dict | None) -> dict | None:
    """Place the reported period inside the scanned series, from the rows themselves.

    Counts how many of the scanned periods came in behind their prior year and how
    long the run of same-direction periods is at the reported period. Counted from
    the trend rows - no inference.

    Returned as data, not only prose, so the counts land in the view model. Any
    figure a sentence quotes has to be *in* the model, or the grounding check
    rejects it - which is exactly what happened when this first shipped as a
    string alone.
    """
    if not trend:
        return None
    aliases = trend.get("value_aliases") or {}
    dimension = trend.get("dimension")
    current_alias, prior_alias = aliases.get("current"), aliases.get("prior")
    if not (dimension and current_alias and prior_alias):
        return None
    series: list[tuple[int, float]] = []
    for row in trend.get("rows") or []:
        index = _num(row.get(dimension))
        current, prior = _num(row.get(current_alias)), _num(row.get(prior_alias))
        if None in (index, current, prior) or not prior:
            continue
        series.append((int(index), (current - prior) / abs(prior) * 100.0))
    if len(series) < 3:
        return None
    series.sort()
    behind = sum(1 for _index, move in series if move < 0)
    parts = [
        f"Across the {len(series)} periods scanned, {behind} came in below last year."
    ]
    anchor = str((period or {}).get("period_anchor") or "")
    try:
        anchor_month = int(anchor[5:7]) if len(anchor) >= 7 else None
    except ValueError:
        anchor_month = None
    run = None
    direction = None
    if anchor_month is not None:
        position = next(
            (offset for offset, (index, _move) in enumerate(series) if index == anchor_month),
            None,
        )
        if position is not None:
            direction = "below" if series[position][1] < 0 else "above"
            run = 0
            for index in range(position, -1, -1):
                if (series[index][1] < 0) != (direction == "below"):
                    break
                run += 1
            if run >= 2:
                parts.append(
                    f"This is the {run}th consecutive period {direction} last year."
                )
    return {
        "periods_scanned": len(series),
        "periods_below_prior": behind,
        "run_length": run,
        "run_direction": direction,
        "statement": " ".join(parts),
    }


def _hero_narrative(measures: dict, bridge: dict | None,
                    calendar_read: dict | None,
                    trend: dict | None = None,
                    period: dict | None = None) -> str:
    """Grounded fallback hero prose: the result read two ways, explained three ways.

    On a view that can only report revenue, the two-way read and the lever
    explanation are both unavailable, which would leave a single bare sentence.
    The trend is used instead to place the period in its own run of periods -
    honest context derived from rows already scanned, not a substitute claim.
    """
    revenue = (measures or {}).get("revenue") or {}
    parts = [f"Revenue is {_pct(revenue.get('change_pct'))} "
             f"({_signed_compact(revenue.get('change'))})."]
    if not bridge:
        context = period_context(trend, period)
        if context:
            parts.append(str(context.get("statement") or ""))
    bills = (measures or {}).get("transactions") or {}
    basket_value = (measures or {}).get("basket_value") or {}
    if bills and basket_value:
        parts.append(
            f"Read two ways, that is {_pct(bills.get('change_pct'))} on how many bills "
            f"and {_pct(basket_value.get('change_pct'))} on what each was worth."
        )
    if bridge and bridge.get("reconciles"):
        effects = bridge.get("effects") or {}
        parts.append(
            "Underneath, transactions "
            f"{_signed_compact(effects.get('transactions'))}, basket size "
            f"{_signed_compact(effects.get('basket_size'))} and price and mix "
            f"{_signed_compact(effects.get('price'))} - these sum to the revenue move."
        )
    units = (measures or {}).get("units") or {}
    if _num(units.get("change_pct")) is not None:
        parts.append(f"Units, which strip price out, are {_pct(units.get('change_pct'))}.")
    if calendar_read and calendar_read.get("comparator_effect"):
        parts.append(str(calendar_read.get("headline") or ""))
    return " ".join(part for part in parts if part)


def build(views: list[dict], title: str = "AI Insights Summary",
          subtitle: str | None = None, config: dict | None = None) -> dict:
    """The complete page model: ordered views plus page-level context."""
    usable = [view for view in views or [] if view and view.get("measures")]
    if not usable:
        return {
            "status": "unavailable",
            "reason": "no view had measures with a prior period to compare",
            "title": title,
            "views": [],
        }
    return {
        "status": "ok",
        "title": title,
        "subtitle": subtitle,
        "views": usable,
        "default_view": usable[0]["key"],
        "layers": list(LAYERS),
        "layer_titles": dict(LAYER_TITLES),
        "caveats": sorted({
            limitation
            for view in usable
            for limitation in view.get("limitations") or []
        }),
    }


# ---------------------------------------------------------------------------
# Period-scoped scan reader (turns one period_breakdown scan into a real view)
# ---------------------------------------------------------------------------

def _phase_value(row: dict, phases: dict, prefix: str = "") -> tuple[float | None, float | None]:
    """Current and prior for one family, reconstructing prior from change if needed."""
    current = _num(row.get(f"{prefix}{phases.get('current')}")) if phases.get("current") else None
    prior = _num(row.get(f"{prefix}{phases.get('prior')}")) if phases.get("prior") else None
    if prior is None and phases.get("change") and current is not None:
        change = _num(row.get(f"{prefix}{phases['change']}"))
        if change is not None:
            prior = current - change
    return current, prior


def read_period_scan(
    rows: list[dict],
    axis_column: str,
    member_column: str,
    aliases: dict,
    *,
    grain: str = "month",
    tolerance_pct: float = 2.0,
) -> dict:
    """Group one ``period_breakdown`` result into per-period families and members.

    Per-period **families** come from the scan's ``__overall_*`` diagnostics, which
    are that period's totals across every member - not the sum of the returned
    rows, so a truncated member list cannot silently shrink the period's headline.
    The returned rows are then compared against those totals to decide whether the
    member breakdown for that period is ``complete``; an incomplete one is still
    reported, flagged, so the caller can withhold contributions rather than publish
    points that do not add up.
    """
    periods: dict = {}
    for row in rows or []:
        index = _num(row.get(axis_column))
        if index is None:
            continue
        # An unnamed member is kept, not dropped. Dropping it made the returned rows
        # fall short of the period's own total by exactly the unclassified amount, so
        # every period failed reconciliation and the whole breakdown was withheld.
        member = member_name(row.get(member_column))
        key = int(index)
        bucket = periods.setdefault(key, {
            "period": key,
            "label": period_label(key, grain),
            "families": {},
            "members": [],
            "member_count": _num(row.get("__member_count")),
        })
        if not bucket["families"]:
            for family, phases in (aliases or {}).items():
                current, prior = _phase_value(row, phases, prefix="__overall_")
                if current is None or prior is None:
                    continue
                change = current - prior
                bucket["families"][family] = {
                    "current": current, "prior": prior, "change": change,
                    "change_pct": (change / abs(prior) * 100.0) if prior else None,
                    "comparison": "the same period last year",
                }
        primary = next(iter(aliases or {}), None)
        current, prior = _phase_value(row, (aliases or {}).get(primary) or {})
        if current is None:
            continue
        # Per-member levers for THIS period. The row already carries every family, so
        # this costs nothing. Without it a period card showed the whole span's lever
        # pattern beside that period's revenue - which produced a department at -4.01%
        # labelled "revenue up".
        member_levers = summary_levers.entity_levers(row, aliases or {})
        if member_levers:
            bucket.setdefault("lever_rows", {})[member] = member_levers
        bucket["members"].append({
            "member": member,
            "hierarchy_path": [str(member)],
            "current": current,
            "prior": prior,
            "change": None if prior is None else current - prior,
            "change_pct": None if not prior else (current - prior) / abs(prior) * 100.0,
        })

    # Denominators come from the period's own overall totals, so a member's share
    # and impact are measured against that period - never against the run's span.
    for bucket in periods.values():
        primary = next(iter(aliases or {}), None)
        overall = (bucket["families"].get(primary) or {})
        overall_current = _num(overall.get("current"))
        overall_prior = _num(overall.get("prior"))
        returned = sum(_num(item.get("current")) or 0.0 for item in bucket["members"])
        returned_prior = sum(_num(item.get("prior")) or 0.0 for item in bucket["members"])
        # BOTH sides, deliberately. Checking current alone passed on the live model
        # while prior was contaminated by an excluded entity, and the contributions
        # - which divide by prior - shipped wrong. A one-sided reconciliation is
        # not a reconciliation.
        def agrees(rows_total: float, overall_total: float | None) -> bool:
            if overall_total is None:
                return False
            limit = abs(overall_total) * (tolerance_pct / 100.0)
            return abs(rows_total - overall_total) <= max(limit, 1.0)

        bucket["reconciled"] = (
            agrees(returned, overall_current) and agrees(returned_prior, overall_prior)
        )
        bucket["reconciliation"] = {
            "rows_current": returned, "overall_current": overall_current,
            "rows_prior": returned_prior, "overall_prior": overall_prior,
        }
        bucket["returned_member_count"] = len(bucket["members"])
        for item in bucket["members"]:
            current = _num(item.get("current")) or 0.0
            change = _num(item.get("change"))
            item["overall_current"] = overall_current
            item["business_share_pct"] = (
                abs(current) / abs(overall_current) * 100.0 if overall_current else None
            )
            item["global_impact_pct"] = (
                abs(change) / abs(overall_current) * 100.0
                if change is not None and overall_current else None
            )
    return {"grain": grain, "axis": axis_column, "periods": periods}


def period_coverage(
    scan: dict | None,
    period_key: Any,
    role: str,
    *,
    material_change_pct: float = 10.0,
    material_share_pct: float = 5.0,
) -> dict | None:
    """A coverage document for ONE period, ranked by the standard blend.

    Deliberately built through ``summary_coverage.build_role_coverage`` rather
    than with bespoke ranking: severity bands, the impact/magnitude/unexpectedness
    blend, peer-median unexpectedness and current-only handling then behave
    identically whether a level is scanned across the whole span or for a single
    period. One ranking, one set of bands, two scopes.
    """
    bucket = ((scan or {}).get("periods") or {}).get(period_key)
    if not bucket or not bucket.get("members"):
        return None
    level = summary_coverage.build_role_coverage(
        role,
        {
            "role": role,
            "column": role,
            "level": None,
            "members": bucket["members"],
            "metric_family": "revenue",
            "diagnostics_reconciled": bool(bucket.get("reconciled")),
        },
        material_change_pct=material_change_pct,
        material_share_pct=material_share_pct,
    )
    return {
        "status": "ok",
        "levels": [level],
        "skipped_roles": {},
        "mirrored_roles": {},
        "period": bucket.get("period"),
        "period_label": bucket.get("label"),
        "reconciled": bool(bucket.get("reconciled")),
    }
