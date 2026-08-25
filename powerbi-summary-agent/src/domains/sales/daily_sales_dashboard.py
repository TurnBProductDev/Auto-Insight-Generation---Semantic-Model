"""Daily Sales page model - the four layers of the approved reference design.

Structure is code-owned and prose is deterministic, for the same reason the
inventory reports are: every figure on this page is a comparison against a
band, and the rulebook requires a number beside every comparison. There is
no LLM in this path.

Layers, matching `docs/dashboard-reference/reference_daily_sales.html`:

  The day     hero + four KPIs + the Net Sales trend + the Bills-vs-Basket
              bridge + all four measures side by side + the two stores +
              what the figures cover.
  Stores      each store against its own band, then each store's own last
              fourteen days.
  Departments every department on the day, how many baskets each reached
              against its usual share, the ones outside their band, and the
              same departments split store by store.
  Detail      what finished below its band and what finished above it, at
              section and category level; the groups that recorded nothing;
              then the full lists.

Two rules run through the whole file and are worth stating once:

  * **Rank by money, never by percentage.** A category can be 2,000% over
    its band on four Riyals of trade. Every ranked list here orders by the
    size of the gap in currency, which is what `_rank_bars` and the two
    outside-band lists do, and the page says so in its own words.
  * **A figure with no band is not a figure with a band of zero.** A
    measure whose band is unavailable renders as "no benchmark", never as a
    verdict. `daily_sales.verdict` already returns `key=None` for that case
    and every renderer here checks it.
"""

from __future__ import annotations

from typing import Any

from . import daily_sales as _ds

_PILL = {"crit": "pill-crit", "good": "pill-ok", "neutral": "pill-neutral", None: "pill-neutral"}

#: The reference's own minus sign and non-breaking space - a currency and its
#: amount must not break across a line.
MINUS = "−"
NBSP = " "

#: Two figures this close are the same figure. Shared with
#: `daily_sales.EDGE_TOLERANCE` so the wording ("level with its floor") and the
#: verdict ("In band") can never disagree about the same pair of numbers.
_LEVEL = _ds.EDGE_TOLERANCE


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------

def _f(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def amount(value: float | None) -> str:
    """`"69.4K"`, `"965.87"`, `"1.42M"` - the reference's own rounding, with
    no currency word. Band edges and axis labels use this."""
    number = _f(value)
    if number is None:
        return "—"
    size = abs(number)
    if size >= 1_000_000:
        return f"{number / 1_000_000:,.2f}M"
    if size >= 1_000:
        return f"{number / 1_000:,.1f}K"
    return f"{number:,.2f}"


def money(value: float | None, currency: str) -> str:
    """`"SAR 69.4K"` - the amount with its currency, joined by a
    non-breaking space so the two never split across a line."""
    if _f(value) is None:
        return "—"
    return f"{currency}{NBSP}{amount(value)}" if currency else amount(value)


def signed_money(value: float | None, currency: str) -> str:
    number = _f(value)
    if number is None:
        return "—"
    sign = MINUS if number < 0 else "+"
    return f"{sign}{money(abs(number), currency)}"


def count(value: float | None) -> str:
    number = _f(value)
    return "—" if number is None else f"{number:,.0f}"


def signed_count(value: float | None) -> str:
    number = _f(value)
    if number is None:
        return "—"
    return f"{MINUS if number < 0 else '+'}{abs(number):,.0f}"


def percent(value: float | None, places: int = 2) -> str:
    number = _f(value)
    return "—" if number is None else f"{number:.{places}f}%"


def signed_points(value: float | None) -> str:
    number = _f(value)
    if number is None:
        return "—"
    return f"{MINUS if number < 0 else '+'}{abs(number):.2f} points"


class _Fmt:
    """How one measure prints. Keeping the four styles in one place is what
    stops a Bills count rendering with a currency word or a Margin gap
    rendering as money - both of which say something untrue."""

    def __init__(self, kind: str, currency: str):
        self.kind = kind
        self.currency = currency

    def value(self, v: float | None) -> str:
        if self.kind == "money":
            return money(v, self.currency)
        if self.kind == "count":
            return count(v)
        if self.kind == "rate":
            return money(v, self.currency)
        return percent(v)

    def bare(self, v: float | None) -> str:
        if self.kind == "count":
            return count(v)
        if self.kind == "percent":
            return percent(v)
        return amount(v)

    def signed(self, v: float | None) -> str:
        if self.kind == "count":
            return signed_count(v)
        if self.kind == "percent":
            return signed_points(v)
        return signed_money(v, self.currency)


_KINDS = {"net_sales": "money", "bills": "count", "basket_value": "rate", "margin": "percent"}
_LABELS = {"net_sales": "Net Sales", "bills": "Bills",
           "basket_value": "Basket Value", "margin": "Margin"}


def _fmt(key: str, currency: str) -> _Fmt:
    return _Fmt(_KINDS[key], currency)


# ---------------------------------------------------------------------------
# how a measure sits against its band, in words
# ---------------------------------------------------------------------------

def band_label(measure: dict, fmt: _Fmt) -> str:
    p20, p80 = measure.get("p20"), measure.get("p80")
    if p20 is None or p80 is None:
        return "no benchmark for this day"
    return f"benchmark {fmt.bare(p20)} to {fmt.bare(p80)}"


def against_band(measure: dict, fmt: _Fmt) -> str:
    """`"-SAR 98.79 against its P20 floor"` / `"level with its P20 floor"` /
    `"inside the normal band"`. "Level with" is deliberately its own reading:
    a figure sitting exactly on its floor is not comfortably inside a band,
    and the reference calls it out."""
    actual, p20, p80 = measure.get("actual"), measure.get("p20"), measure.get("p80")
    if actual is None or p20 is None or p80 is None:
        return "no benchmark for this day"
    if abs(actual - p20) <= max(abs(p20), 1.0) * _LEVEL:
        return "level with its P20 floor"
    if abs(actual - p80) <= max(abs(p80), 1.0) * _LEVEL:
        return "level with its P80 ceiling"
    if actual < p20:
        return _edge_phrase(fmt, actual - p20, "below its P20 floor", "against its P20 floor")
    if actual > p80:
        return _edge_phrase(fmt, actual - p80, "above its P80 ceiling", "against its P80 ceiling")
    return "inside the normal band"


def _edge_phrase(fmt: _Fmt, gap: float, near: str, far: str) -> str:
    """A gap too small to survive rounding prints as words, not as a signed
    zero. ST4's Basket Value finished 0.4 of a cent under its floor, which
    rendered as "-SAR 0.00 against its P20 floor" - a figure that reads as an
    error. It is genuinely below, so the verdict is unchanged; only the
    wording is."""
    printed = fmt.signed(gap)
    digits = "".join(ch for ch in printed if ch.isdigit() or ch == ".")
    try:
        rounds_to_nothing = float(digits or "0") == 0.0
    except ValueError:                      # a currency word carrying a digit
        rounds_to_nothing = False
    return f"just {near}" if rounds_to_nothing else f"{printed} {far}"


def against_benchmark(measure: dict, fmt: _Fmt) -> str:
    """`"-SAR 7.1K against the benchmark SAR 76.4K"`."""
    delta, p50 = measure.get("vs_benchmark"), measure.get("p50")
    if delta is None or p50 is None:
        return "no benchmark for this day"
    return f"{fmt.signed(delta)} against the benchmark {fmt.value(p50)}"


def finished_phrase(measure: dict, fmt: _Fmt) -> str:
    """The same reading as `against_band`, worded to sit inside a sentence:
    `"finished SAR 98.79 below its own floor"`."""
    actual, p20, p80 = measure.get("actual"), measure.get("p20"), measure.get("p80")
    if actual is None or p20 is None or p80 is None:
        return "has no benchmark for this day"
    if abs(actual - p20) <= max(abs(p20), 1.0) * _LEVEL:
        return "finished level with its own floor"
    if abs(actual - p80) <= max(abs(p80), 1.0) * _LEVEL:
        return "finished level with its own ceiling"
    if actual < p20:
        return f"finished {fmt.value(abs(actual - p20))} below its own floor"
    if actual > p80:
        return f"finished {fmt.value(abs(actual - p80))} above its own ceiling"
    return "finished inside its own band"


def band_words(measure: dict) -> str:
    key = (measure.get("verdict") or {}).get("key")
    if key == "crit":
        return "below the band floor"
    if key == "good":
        return "above the band ceiling"
    if key is None:
        return "no benchmark for this day"
    return "inside the normal band"


# ---------------------------------------------------------------------------
# bullet chart geometry
# ---------------------------------------------------------------------------

#: The band occupies this share of the track, so every bullet on the page has
#: the same visual weight and two bands can be compared by eye.
_BAND_SHARE = 0.5262


def bullet(measure: dict, *, width: float = 214.0) -> dict | None:
    """Geometry for the reference's bullet chart: a full-width track, a
    fixed-width [p20,p80] band centred on P50, a P50 tick and an actual-value
    tick. If the actual value would fall off the track the mapping is widened
    until it fits - a tick drawn outside its own chart is worse than a
    narrower band."""
    actual, p20, p50, p80 = (measure.get("actual"), measure.get("p20"),
                             measure.get("p50"), measure.get("p80"))
    if actual is None or p20 is None or p80 is None:
        return None
    if p50 is None:
        p50 = (p20 + p80) / 2.0
    span = (p80 - p20) or max(abs(p80), 1.0) * 1e-6
    track_x, track_w = 6.0, width - 12.0
    centre = track_x + track_w / 2.0

    share = _BAND_SHARE
    for _ in range(24):
        scale = (track_w * share) / span
        actual_x = centre + (actual - p50) * scale
        if track_x + 2.0 <= actual_x <= track_x + track_w - 2.0:
            break
        share *= 0.8
    scale = (track_w * share) / span

    def to_x(value: float) -> float:
        return centre + (value - p50) * scale

    band_x, band_end = to_x(p20), to_x(p80)
    actual_x = min(max(to_x(actual), track_x + 1.6), track_x + track_w - 1.6)
    return {
        "width": width, "track_x": track_x, "track_w": track_w,
        "band_x": band_x, "band_w": band_end - band_x,
        "p50_x": centre, "actual_x": actual_x,
        "tone": (measure.get("verdict") or {}).get("key"),
    }


# ---------------------------------------------------------------------------
# one measure, rendered three ways
# ---------------------------------------------------------------------------

def kpi(key: str, measure: dict, currency: str) -> dict:
    fmt = _fmt(key, currency)
    verdict = measure.get("verdict") or {}
    return {
        "key": key, "label": _LABELS[key], "value": fmt.value(measure.get("actual")),
        "note": against_benchmark(measure, fmt),
        "tone": verdict.get("key"), "pill": _PILL.get(verdict.get("key")),
        "word": verdict.get("word") or "Not available",
        "bullet": bullet(measure),
        "has_band": measure.get("p20") is not None and measure.get("p80") is not None,
    }


def measure_row(key: str, measure: dict, currency: str) -> dict:
    fmt = _fmt(key, currency)
    verdict = measure.get("verdict") or {}
    return {
        "key": key, "label": _LABELS[key], "band": band_label(measure, fmt),
        "value": fmt.value(measure.get("actual")),
        "note": against_band(measure, fmt),
        "tone": verdict.get("key"), "pill": _PILL.get(verdict.get("key")),
        "word": verdict.get("word") or "Not available",
        "bullet": bullet(measure, width=210.0),
        "has_band": measure.get("p20") is not None and measure.get("p80") is not None,
    }


def _measure_rows(bundle: dict, currency: str) -> list[dict]:
    return [measure_row(key, bundle[key], currency)
            for key in ("net_sales", "bills", "basket_value", "margin")]


# ---------------------------------------------------------------------------
# the day
# ---------------------------------------------------------------------------

def _hero(model: dict) -> dict:
    currency = model["currency"]
    whole = model["whole"]
    sales, bills, basket = whole["net_sales"], whole["bills"], whole["basket_value"]
    money_fmt = _fmt("net_sales", currency)

    gap, delta = sales.get("gap"), sales.get("vs_benchmark")
    if sales["verdict"]["key"] == "crit" and gap is not None and delta is not None:
        headline = (f"Net Sales landed {money(abs(gap), currency)} under the floor of its "
                    f"normal band, and {money(abs(delta), currency)} under the benchmark.")
    elif sales["verdict"]["key"] == "good" and gap is not None and delta is not None:
        headline = (f"Net Sales finished {money(abs(gap), currency)} above the ceiling of its "
                    f"normal band, and {money(abs(delta), currency)} above the benchmark.")
    elif delta is not None:
        side = "under" if delta < 0 else "over"
        headline = (f"Net Sales finished inside its normal band, "
                    f"{money(abs(delta), currency)} {side} the benchmark.")
    else:
        headline = f"Net Sales came to {money(sales.get('actual'), currency)} on the day."

    parts = []
    bills_delta = bills.get("vs_benchmark")
    if bills.get("p50") is not None and bills_delta is not None:
        verb = {"crit": "fell short", "good": "ran ahead", "neutral": "held up"}.get(
            bills["verdict"]["key"], "came in")
        parts.append(f"Bills {verb} — {count(bills.get('actual'))} against a benchmark of "
                     f"{count(bills['p50'])}, {band_words(bills)}.")
    _, bills_effect, basket_effect = _bridge_effects(whole)
    if bills_effect is not None and basket_effect is not None:
        if abs(basket_effect) > abs(bills_effect):
            parts.append("What fell was the amount in each basket." if basket_effect < 0
                         else "What carried the day was the amount in each basket.")
        else:
            parts.append("What fell was the number of baskets." if bills_effect < 0
                         else "What carried the day was the number of baskets.")
    parts.append(_store_attribution(model))

    stats = [
        {"value": money(sales.get("actual"), currency),
         "label": f"Net Sales · {against_band(sales, money_fmt)}",
         "tone": sales["verdict"]["key"]},
        {"value": money(basket.get("actual"), currency),
         "label": f"Basket Value · {_pct_vs_benchmark(basket)} against the benchmark",
         "tone": basket["verdict"]["key"]},
        {"value": percent(whole["margin"].get("actual")),
         "label": f"Margin · {band_words(whole['margin'])}",
         "tone": whole["margin"]["verdict"]["key"]},
    ]
    return {
        "tag": f"{model['dow_name']} · week {model['week_of_month']} of the month",
        "headline": headline,
        "narrative": " ".join(p for p in parts if p),
        "stats": stats,
    }


def _pct_vs_benchmark(measure: dict) -> str:
    actual, p50 = measure.get("actual"), measure.get("p50")
    if actual is None or not p50:
        return "no benchmark"
    change = (actual / p50 - 1.0) * 100.0
    return f"{MINUS if change < 0 else '+'}{abs(change):.1f}%"


def _store_attribution(model: dict) -> str:
    """Which store the day's shortfall (or surplus) sits in. A group figure
    hides a store, so both are always named."""
    currency = model["currency"]
    stores = [s for s in model["stores"] if s["net_sales"].get("gap") is not None]
    if len(stores) < 2:
        return ""
    outside = [s for s in stores if s["net_sales"]["verdict"]["key"] in ("crit", "good")]
    if not outside:
        return ("Every store finished inside its own normal band: "
                + "; ".join(f"{s['store']} at {money(s['net_sales']['actual'], currency)}"
                            for s in stores) + ".")
    worst = min(stores, key=lambda s: s["net_sales"]["gap"] or 0.0)
    others = [s for s in stores if s is not worst]
    if (worst["net_sales"]["gap"] or 0.0) < 0:
        lead = f"All of the shortfall against the floor sits in {worst['store']}"
    else:
        best = max(stores, key=lambda s: s["net_sales"]["gap"] or 0.0)
        worst, others = best, [s for s in stores if s is not best]
        lead = f"The whole of the surplus above the ceiling sits in {worst['store']}"
    rest = "; ".join(
        f"{s['store']} {finished_phrase(s['net_sales'], _fmt('net_sales', currency))}"
        for s in others)
    return f"{lead}; {rest}."


def _bridge_effects(whole: dict) -> tuple[float | None, float | None, float | None]:
    """Net Sales is Bills x Basket Value, so the gap against the benchmark
    splits exactly into the two. The split is sequential and therefore exact:
    the two effects add to the Net Sales gap to the cent."""
    bills, basket = whole.get("bills") or {}, whole.get("basket_value") or {}
    bills_actual, bills_p50 = bills.get("actual"), bills.get("p50")
    basket_actual, basket_p50 = basket.get("actual"), basket.get("p50")
    if None in (bills_actual, bills_p50, basket_actual, basket_p50):
        return None, None, None
    bills_effect = (bills_actual - bills_p50) * basket_p50
    basket_effect = bills_actual * (basket_actual - basket_p50)
    return basket_actual - basket_p50, bills_effect, basket_effect


def _bridge(model: dict) -> dict | None:
    currency = model["currency"]
    whole = model["whole"]
    if not whole:
        return None
    basket_delta, bills_effect, basket_effect = _bridge_effects(whole)
    if bills_effect is None:
        return None
    sales, bills = whole["net_sales"], whole["bills"]
    start, end = sales.get("p50"), sales.get("actual")
    if start is None or end is None:
        return None
    total = bills_effect + basket_effect
    bills_delta = (bills["actual"] or 0) - (bills["p50"] or 0)
    biggest = max(abs(bills_effect), abs(basket_effect)) or 1.0
    # The share must belong to the effect actually named. Quoting the basket's
    # share beside the words "the bill count" published "the bill count is 3%
    # of the gap" on a day when the bill count WAS the gap.
    if abs(basket_effect) >= abs(bills_effect):
        driver = "smaller basket" if basket_effect < 0 else "fuller basket"
        driver_effect = basket_effect
    else:
        driver = "bill count"
        driver_effect = bills_effect
    share = abs(driver_effect) / (abs(total) or 1.0) * 100.0
    return {
        "start": start, "end": end,
        "bills_effect": bills_effect, "basket_effect": basket_effect,
        "steps": [
            {"label": "Benchmark", "sub": "for this weekday", "value": start, "kind": "total"},
            {"label": "Fewer Bills" if bills_delta < 0 else "More Bills",
             "sub": f"{abs(bills_delta):,.0f} {'fewer' if bills_delta < 0 else 'more'}",
             "value": bills_effect, "kind": "delta"},
            {"label": "Smaller basket" if (basket_delta or 0) < 0 else "Fuller basket",
             "sub": f"{money(abs(basket_delta or 0), currency)} "
                    f"{'less' if (basket_delta or 0) < 0 else 'more'} each",
             "value": basket_effect, "kind": "delta"},
            {"label": "The day", "sub": "what was taken", "value": end, "kind": "total"},
        ],
        "note": (
            f"Starting from the benchmark of {money(start, currency)}: "
            f"{abs(bills_delta):,.0f} {'fewer' if bills_delta < 0 else 'more'} Bills "
            f"{'took off' if bills_effect < 0 else 'added'} {money(abs(bills_effect), currency)}, "
            f"and each basket holding {money(abs(basket_delta or 0), currency)} "
            f"{'less' if (basket_delta or 0) < 0 else 'more'} "
            f"{'took off' if basket_effect < 0 else 'added'} "
            f"{money(abs(basket_effect), currency)}. The {driver} is {share:.0f}% of the gap. "
            f"The two add to {money(abs(total), currency)} exactly."),
        "_peak": biggest,
    }


def _trend(rows: list[dict], key: str = "net_sales") -> dict | None:
    """Each day as a percentage of that day's own benchmark, so fourteen days
    with fourteen different benchmarks can share one axis."""
    points = []
    for row in rows:
        measure = row.get(key) or {}
        p50 = measure.get("p50")
        actual = measure.get("actual")
        if not p50 or actual is None:
            continue
        p20, p80 = measure.get("p20"), measure.get("p80")
        inside = p20 is not None and p80 is not None and p20 <= actual <= p80
        below = p20 is not None and actual < p20
        points.append({
            "date": row["date"], "label": _ds.short_day(row["date"]),
            "actual_pct": actual / p50 * 100.0,
            "p20_pct": (p20 / p50 * 100.0) if p20 is not None else None,
            "p80_pct": (p80 / p50 * 100.0) if p80 is not None else None,
            "actual": actual, "inside": inside, "below": below,
            "above": (not inside) and (not below),
        })
    if len(points) < 2:
        return None
    inside_count = sum(1 for p in points if p["inside"])
    below_count = sum(1 for p in points if p["below"])
    return {
        "points": points, "total": len(points),
        "inside": inside_count, "below": below_count,
        "above": len(points) - inside_count - below_count,
        "window": f"{_ds.short_day(points[0]['date'])} to {_ds.short_day(points[-1]['date'])}",
    }


def _look_down(model: dict) -> dict:
    currency = model["currency"]
    fmt = _fmt("net_sales", currency)
    cards = []
    for store in model["stores"]:
        sales = store["net_sales"]
        cards.append({
            "name": store["store"],
            "headline": f"{money(sales.get('actual'), currency)} · {against_band(sales, fmt)}",
            "detail": (f"Bills {count(store['bills'].get('actual'))} · "
                       f"Basket Value {money(store['basket_value'].get('actual'), currency)} · "
                       f"Margin {percent(store['margin'].get('actual'))}"),
            "tone": sales["verdict"]["key"], "pill": _PILL.get(sales["verdict"]["key"]),
            "word": sales["verdict"]["word"],
        })

    sentence = ""
    outside = [s for s in model["stores"] if s["net_sales"]["verdict"]["key"] == "crit"]
    if outside:
        weakest = min(outside, key=lambda s: s["net_sales"]["gap"] or 0.0)
        inside_store = weakest["store"]
        below = [d for d in model["departments"]
                 if not d["silent"]
                 and (d["by_store"].get(inside_store) or {}).get("net_sales", {}).get(
                     "verdict", {}).get("key") == "crit"]
        below.sort(key=lambda d: d["by_store"][inside_store]["net_sales"]["gap"] or 0.0)
        if below:
            worst = below[0]
            bundle = worst["by_store"][inside_store]["net_sales"]
            figures = (f"{money(bundle.get('actual'), currency)}, "
                       f"{against_band(bundle, fmt)}")
            if len(below) == 1:
                sentence = (f"Inside {inside_store}, the department below its own band is "
                            f"{worst['name']}: {figures}.")
            else:
                # Name them all, then attribute the figures to the one they
                # belong to. A list of names followed by a single department's
                # numbers reads as though the numbers describe the list.
                shown = 3 if len(below) > 4 else len(below)
                names = [d["name"] for d in below[:shown]]
                if shown < len(below):
                    listed = ", ".join(names) + f" and {len(below) - shown} more"
                else:
                    listed = ", ".join(names[:-1]) + f" and {names[-1]}"
                sentence = (f"Inside {inside_store}, {len(below)} departments finished below "
                            f"their own band — {listed}. The largest gap is "
                            f"{worst['name']}: {figures}.")
        else:
            sentence = (f"Inside {inside_store}, no single department finished below its own "
                        f"band - the shortfall is spread across the estate rather than "
                        f"concentrated in one area.")
    if len(model["stores"]) > 1:
        pieces = [f"{s['store']} {finished_phrase(s['net_sales'], fmt)} at "
                  f"{money(s['net_sales'].get('actual'), currency)}" for s in model["stores"]]
        sentence = (sentence + " Both stores are shown because a group figure hides a store: "
                    + "; ".join(pieces) + ".").strip()
    return {"stores": cards, "sentence": sentence}


# ---------------------------------------------------------------------------
# caveats
# ---------------------------------------------------------------------------

def _caveats(model: dict) -> list[dict]:
    currency = model["currency"]
    whole = model["whole"]
    stores = " and ".join(model["store_names"])
    out: list[dict] = [{
        "lead": "This is a comparison with the normal band, never with last year.",
        "body": (f"Every figure is {model['as_at_label']} placed against past days that match "
                 f"on the same weekday, so a {model['dow_name']} is only ever judged against "
                 f"other {model['dow_name']}s. The report holds no same-day-last-year figure "
                 f"and does not claim one."),
    }, {
        "lead": f"The figures cover {stores} only",
        "body": ", and both stores are in every total on this page."
                if len(model["store_names"]) == 2
                else ", and every store is in every total on this page.",
    }]

    sample = whole.get("sample_days") or 0
    margin_sample = whole.get("margin_sample_days") or 0
    if sample or margin_sample:
        out.append({
            "lead": "The bands are built from a small number of matching days.",
            "body": (f"Net Sales, Bills and Basket Value use {sample} matching past days; "
                     f"Margin uses {margin_sample} same-weekday readings. A band drawn from a "
                     f"short run of days is wider and moves more than one drawn from a long run."),
        })

    scale = model.get("scale") or {}
    if scale.get("reason") and (scale.get("applied") or not scale.get("factor")):
        out.append({
            "lead": "Net Sales arrives on two scales in the source, and has been put on one.",
            "body": " " + scale["reason"] + (
                " Department, section and category Net Sales each add up to the whole-business "
                "figure exactly, which is the check that this was done right."
                if scale.get("applied") else ""),
        })

    worst = next((d for d in model["departments"]
                  if not d["silent"] and d["net_sales"]["verdict"]["key"] == "crit"), None)
    whole_gap = (whole.get("net_sales") or {}).get("gap")
    if worst is not None and whole_gap:
        out.append({
            "lead": "A band at one level will not add up to the band at the level above it.",
            "body": (f" The whole day finished {money(abs(whole_gap), currency)} "
                     f"{'below' if whole_gap < 0 else 'above'} its floor while "
                     f"{worst['name']} alone was "
                     f"{money(abs(worst['net_sales']['gap'] or 0), currency)} "
                     f"{'below' if (worst['net_sales']['gap'] or 0) < 0 else 'above'} its own. "
                     f"Each level is worked out separately, so the two do not match and neither "
                     f"is wrong."),
        })

    out.append({
        "lead": "Bills cannot be added up.",
        "body": (" One basket holding bread, shampoo and a shirt is one Bill for the store but "
                 "appears under each department, section and category it touched. Each figure "
                 "on this page is taken from its own level, and department shares of baskets do "
                 "not add to 100%."),
    })

    merged = [d for d in model["departments"] if (d.get("group_count") or 0) > 1]
    if merged:
        out.append({
            "lead": "Several groups share one name.",
            "body": (" A name at department, section or category level can cover more than one "
                     "group in the source, and the source does not carry the code that "
                     "separates them. Net Sales for those names is added, which is safe. Their "
                     "bands are added too, which is close but is not a true benchmark for the "
                     "whole name, and their Bills count some baskets more than once. Treat a "
                     "band at these levels as a guide."),
        })

    silent_departments = [d["name"] for d in model["departments"] if d["silent"]]
    if silent_departments:
        names = ", ".join(silent_departments)
        plural = "departments" if len(silent_departments) > 1 else "department"
        verb = "recorded no sale" if len(silent_departments) == 1 else "recorded no sales"
        out.append({
            "lead": f"{'One' if len(silent_departments) == 1 else str(len(silent_departments))} "
                    f"{plural}, {names}, {verb} on this day",
            "body": " and has been left out of the tables rather than shown as a zero."
                    if len(silent_departments) == 1
                    else " and have been left out of the tables rather than shown as zeros.",
        })

    out.append({
        "lead": f"The figures run to {_ds.short_day(model['as_at'])}.",
        "body": "That is the most recent day the report holds."
                + (f" {model['last_updated']}." if model.get("last_updated") else ""),
    })
    return [_joined(item) for item in out]


def _joined(item: dict) -> dict:
    """A caveat renders as `<b>lead</b>body`, so the body carries its own
    leading space unless it opens with punctuation that must sit tight against
    the bold run ("The figures cover ST1 and ST4 only, and ...")."""
    body = str(item["body"]).lstrip()
    if body and body[0] not in ",.;:":
        body = " " + body
    return {"lead": item["lead"], "body": body}


# ---------------------------------------------------------------------------
# grains
# ---------------------------------------------------------------------------

def _live(rows: list[dict]) -> list[dict]:
    return [row for row in rows if not row.get("silent")]


def _grain_table(rows: list[dict], currency: str, *, with_parent: bool,
                 whole_bills: float | None, whole_bills_p50: float | None,
                 with_share: bool = False) -> dict:
    headers = ["Department" if not with_parent else "Name"]
    if with_parent:
        headers.append("Sits under")
    headers += ["Net Sales", "Normal band", "Against the band", "Bills", "Basket Value", "Margin"]
    if with_share:
        headers.append("Share of baskets")
    headers.append("Verdict")

    body, urgent = [], set()
    for index, row in enumerate(rows):
        sales = row["net_sales"]
        if sales["verdict"]["key"] == "crit":
            urgent.add(index)
        cells = [row["name"]]
        if with_parent:
            cells.append(row.get("parent") or "")
        gap = sales.get("gap")
        cells += [
            money(sales.get("actual"), currency),
            (f"{amount(sales.get('p20'))} to {amount(sales.get('p80'))}"
             if sales.get("p20") is not None else "—"),
            (signed_money(gap, currency) if gap else "—"),
            count(row["bills"].get("actual")),
            money(row["basket_value"].get("actual"), currency),
            percent(row["margin"].get("actual")),
        ]
        if with_share:
            cells.append(_share_text(row, whole_bills, whole_bills_p50))
        cells.append(sales["verdict"]["word"])
        body.append(cells)
    return {"headers": headers, "rows": body, "urgent": sorted(urgent),
            "numeric": _numeric_columns(headers)}


def _numeric_columns(headers: list[str]) -> list[int]:
    numeric = {"Net Sales", "Normal band", "Against the band", "Bills", "Basket Value",
               "Margin", "Share of baskets", "ST1 Net Sales", "Stores outside their band"}
    return [i for i, head in enumerate(headers)
            if head in numeric or head.endswith("Net Sales") or head.endswith("against the band")]


def _share(row: dict, whole_bills: float | None) -> float | None:
    bills = row["bills"].get("actual")
    if bills is None or not whole_bills:
        return None
    return bills / whole_bills * 100.0


def _bench_share(row: dict, whole_bills_p50: float | None) -> float | None:
    bills = row["bills"].get("p50")
    if bills is None or not whole_bills_p50:
        return None
    return bills / whole_bills_p50 * 100.0


def _share_text(row: dict, whole_bills: float | None, whole_bills_p50: float | None) -> str:
    share = _share(row, whole_bills)
    bench = _bench_share(row, whole_bills_p50)
    if share is None:
        return "—"
    if bench is None:
        return f"{share:.1f}%"
    return f"{share:.1f}% vs {bench:.1f}%"


def _share_bars(rows: list[dict], whole_bills: float | None,
                whole_bills_p50: float | None) -> list[dict]:
    bars = []
    peak = max((_share(row, whole_bills) or 0.0) for row in rows) if rows else 0.0
    peak = peak or 1.0
    for row in rows:
        share = _share(row, whole_bills)
        if share is None:
            continue
        bench = _bench_share(row, whole_bills_p50)
        bars.append({
            "name": row["name"],
            "sub": f"{count(row['bills'].get('actual'))} Bills",
            "width": share / peak * 100.0,
            "tick": (bench / peak * 100.0) if bench is not None else None,
            "value": f"{share:.1f}%",
            "note": f"benchmark {bench:.1f}%" if bench is not None else "no benchmark",
            "short": bench is not None and share < bench,
        })
    return bars


def _outside(rows: list[dict], currency: str, *, want: str) -> list[dict]:
    """The rows outside their band, ranked by the size of the gap in money.

    Ranking by percentage is exactly the failure this ordering exists to
    prevent: a category can be 2,000% over its band on four Riyals."""
    picked = []
    for row in rows:
        gap = row["net_sales"].get("gap")
        if not gap:
            continue
        if (want == "below") != (gap < 0):
            continue
        picked.append(row)
    picked.sort(key=lambda r: -abs(r["net_sales"]["gap"] or 0.0))
    peak = max((abs(r["net_sales"]["gap"] or 0.0) for r in picked), default=0.0) or 1.0
    out = []
    for row in picked:
        sales = row["net_sales"]
        gap = sales["gap"] or 0.0
        edge = sales["p20"] if gap < 0 else sales["p80"]
        out.append({
            "name": row["name"], "parent": row.get("parent") or "",
            "width": abs(gap) / peak * 100.0,
            "tone": "crit" if gap < 0 else "good",
            "value": signed_money(gap, currency),
            "note": f"{money(sales.get('actual'), currency)} vs {amount(edge)}",
        })
    return out


def _by_store_table(rows: list[dict], store_names: list[str], currency: str) -> dict:
    headers = ["Department"]
    for name in store_names:
        headers += [f"{name} Net Sales", f"{name} against the band"]
    headers.append("Stores outside their band")
    body, urgent = [], set()
    for index, row in enumerate(rows):
        cells = [row["name"]]
        outside = 0
        for name in store_names:
            bundle = row["by_store"].get(name)
            if not bundle:
                cells += ["—", "—"]
                continue
            sales = bundle["net_sales"]
            gap = sales.get("gap")
            if gap:
                outside += 1
            cells += [money(sales.get("actual"), currency),
                      signed_money(gap, currency) if gap else "—"]
        if outside:
            urgent.add(index)
        cells.append(str(outside) if outside else "—")
        body.append(cells)
    return {"headers": headers, "rows": body, "urgent": sorted(urgent),
            "numeric": [i for i in range(1, len(headers))]}


def _silent_table(model: dict, limit: int = 10) -> dict:
    currency = model["currency"]
    rows = []
    for entry in model["silent_groups"][:limit]:
        rows.append([
            entry["name"], entry["parent"],
            f"{entry['silent']} of {entry['total']}",
            money(entry["usually_take"], currency),
            money(entry["taken_by_rest"], currency),
        ])
    return {
        "headers": ["Category", "Sits under", "Groups with no sale",
                    "What they usually take", "Taken by the rest"],
        "rows": rows, "urgent": [], "numeric": [2, 3, 4],
    }


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------

def build(model: dict) -> dict:
    currency = model["currency"]
    whole = model.get("whole") or {}
    whole_bills = (whole.get("bills") or {}).get("actual")
    whole_bills_p50 = (whole.get("bills") or {}).get("p50")

    departments = _live(model["departments"])
    sections = _live(model["sections"])
    categories = _live(model["categories"])

    store_trends = []
    for name in model["store_names"]:
        chart = _trend(model["store_trend"].get(name) or [])
        if not chart:
            continue
        store_trends.append({
            "name": name, "chart": chart,
            "note": (f"{chart['inside']} days inside the band, {chart['below']} below it and "
                     f"{chart['above']} above it."),
        })

    trend = _trend(model["trend"])
    page = {
        "report_id": model["report_id"],
        "title": model["report_name"],
        "as_at": model["as_at"],
        "as_at_label": model["as_at_label"],
        "currency": currency,
        "dow_name": model["dow_name"],
        "week_of_month": model["week_of_month"],
        "store_names": model["store_names"],
        "last_updated": model.get("last_updated") or "",
        "masthead_sub": (
            f"{model['as_at_label']} · scored against past {model['dow_name']}s in week "
            f"{model['week_of_month']} of the month · "
            f"{' and '.join(model['store_names'])} · all figures in {currency}"),
        "hero": _hero(model) if whole else {"tag": "", "headline": "", "narrative": "", "stats": []},
        "kpis": [kpi(key, whole[key], currency)
                 for key in ("net_sales", "bills", "basket_value", "margin")] if whole else [],
        "trend": trend,
        "bridge": _bridge(model),
        "look_across": _measure_rows(whole, currency) if whole else [],
        "look_down": _look_down(model) if whole else {"stores": [], "sentence": ""},
        "caveats": _caveats(model) if whole else [],
        "stores": [{
            "name": store["store"],
            "measures": _measure_rows(store, currency),
            "note": (f"Benchmark built from {store['sample_days']} matching past days for Net "
                     f"Sales, Bills and Basket Value, and {store['margin_sample_days']} for "
                     f"Margin."),
        } for store in model["stores"]],
        "store_trends": store_trends,
        "departments": {
            "rows": departments,
            "table": _grain_table(departments, currency, with_parent=False,
                                  whole_bills=whole_bills, whole_bills_p50=whole_bills_p50,
                                  with_share=True),
            "share_bars": _share_bars(departments, whole_bills, whole_bills_p50),
            "below": _outside(departments, currency, want="below"),
            "above": _outside(departments, currency, want="above"),
            "by_store": _by_store_table(departments, model["store_names"], currency),
        },
        "sections": {
            "rows": sections,
            "table": _grain_table(sections, currency, with_parent=True,
                                  whole_bills=whole_bills, whole_bills_p50=whole_bills_p50),
            "below": _outside(sections, currency, want="below"),
            "above": _outside(sections, currency, want="above"),
        },
        "categories": {
            "rows": categories,
            "table": _grain_table(categories, currency, with_parent=True,
                                  whole_bills=whole_bills, whole_bills_p50=whole_bills_p50),
            "below": _outside(categories, currency, want="below"),
            "above": _outside(categories, currency, want="above"),
        },
        "silent": {
            "table": _silent_table(model),
            "total": model["silent_group_total"],
            "benchmark": money(model["silent_group_benchmark"], currency),
            "shown": min(len(model["silent_groups"]), 10),
            "of": len(model["silent_groups"]),
        },
        "counts": {"sections": len(sections), "categories": len(categories),
                   "departments": len(departments)},
        # Raw measure bundles, carried so `to_signals` reads the same numbers
        # the page shows rather than re-deriving them from formatted strings.
        "whole": whole,
        "store_bundles": [{"name": s["store"], "net_sales": s["net_sales"],
                           "bills": s["bills"], "margin": s["margin"]}
                          for s in model["stores"]],
        "scale": model.get("scale") or {},
        "checks": model["checks"],
        "grain_sales_known": model.get("grain_sales_known", False),
    }
    return page


# ---------------------------------------------------------------------------
# KPI-feed signals
# ---------------------------------------------------------------------------

_REPORT_ID = "daily_sales"


def _story_key(kind: str, anchor: str, name: str) -> str:
    import hashlib
    import json as _json
    blob = _json.dumps([_REPORT_ID, "insight", kind, anchor, name], separators=(",", ":"))
    return "dsins:v1:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def to_signals(page: dict) -> list[dict]:
    """Whole-business, store, department and section findings outside their
    band, ranked by the size of the gap in money.

    Money, not Bills, is what ranks these. A Bills gap is not additive - one
    basket touching three departments is one Bill in each - so a section's
    Bills gap can exceed its own department's, which reads as nonsense on a
    ranked list. Net Sales adds up exactly at every level here (see
    `daily_sales.measure_scale`), so it is the honest ranking key."""
    anchor = str(page.get("as_at") or "")
    currency = page.get("currency") or ""
    out: list[dict] = []

    def _emit(name: str, grain: str, parent: str, measure_key: str, measure: dict,
              weight: float) -> None:
        gap = measure.get("gap")
        if gap is None or gap == 0:
            return
        verdict = measure.get("verdict") or {}
        label = _LABELS.get(measure_key, measure_key)
        fmt = _fmt(measure_key, currency)
        who = name or "The whole business"
        out.append({
            "candidate_id": f"daily_sales_{grain}_{measure_key}:{name}:",
            "story_key": _story_key(f"{grain}_{measure_key}", anchor, name),
            "report_id": _REPORT_ID,
            "analysis_type": f"daily_sales_{grain}_{measure_key}_band",
            "dimension": grain, "affected_segment": name,
            "metric": f"{label} vs its normal band",
            "current": measure.get("actual"),
            "impact_value": gap, "impact_share": None,
            "score": abs(gap) * weight if measure_key != "margin" else abs(gap) * weight * 1000.0,
            "severity": "critical" if verdict.get("key") == "crit" else "info",
            "comparison_label": (f"the normal {label.lower()} band for "
                                 f"{name or 'the business'} on this weekday"),
            "description": (
                f"{who} finished {label} {(verdict.get('word') or '').lower()} "
                f"({fmt.signed(gap)} against its band, {fmt.value(measure.get('actual'))} "
                f"on the day)" + (f", inside {parent}" if parent else "") + "."),
        })

    # The whole business first, weighted so it leads the feed; then each store,
    # then the two grains a buyer can act on. Category level is deliberately
    # absent - 117 rows of small gaps would crowd out everything above them.
    whole = page.get("whole") or {}
    for measure_key in ("net_sales", "bills", "margin"):
        if whole.get(measure_key):
            _emit("", "whole", "", measure_key, whole[measure_key], 5.0)
    for store in page.get("store_bundles") or []:
        _emit(store["name"], "store", "", "net_sales", store["net_sales"], 2.0)
    for row in (page.get("departments") or {}).get("rows", []):
        _emit(row["name"], "department", "", "net_sales", row["net_sales"], 1.0)
    for row in (page.get("sections") or {}).get("rows", []):
        _emit(row["name"], "section", row.get("parent") or "", "net_sales", row["net_sales"], 0.7)

    out.sort(key=lambda s: (-float(s.get("score") or 0.0), str(s.get("candidate_id"))))
    for index, signal in enumerate(out, start=1):
        signal["id"] = f"I{index}"
    return out
