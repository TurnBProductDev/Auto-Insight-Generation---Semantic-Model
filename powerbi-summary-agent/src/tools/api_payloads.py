"""LLM-authored MVC/FastAPI content payloads, with strict schema + fixed numbers.

The ASP.NET MVC app proxies to a FastAPI service that must return AI content in
two exact shapes:

  * ``/report/summary?format=json`` -> a JSON object
        {title, generatedAt, headline, metrics[], sections[]}
  * ``/kpi/insights`` -> a JSON array of cards
        {id, severity, category, metric, value, delta, deltaDirection,
         description, displayTime, isoDate, comparisonLabel, insight{...}}
    Plus, only when ``ai_content_kpi_card_fields`` is on (see
    ``kpi-tile-schema-proposal.md`` and ``docs/phase5-app-contract-change.md``
    for the rollout precedent this follows): ``label``, ``rawValue``, ``unit``,
    ``valueType``, ``goodDirection``, ``comparison{type,label,baselineValue}``,
    ``target{value,attainmentPct}``, ``shareOfTotalPct``, ``rank`` - each
    present only when the signal actually supports it, never a guess.

Generation is LLM-driven: the model reads the run's results and *writes the words*
(card descriptions, insight titles/summaries/actions, the summary headline, section
prose, metric curation and tone). But every number and every enum is owned by code,
never typed by the model:

  * KPI figures (value / delta / stats) are injected from the computed signals.
  * fresh-summary metric values are injected from deterministic evidence facts;
    the legacy summary path injects them from parsed Key Metrics.
  * numeric-fidelity guards reject section prose whose figures are not present
    in the selected evidence or source markdown.

The final payload is validated against strict pydantic schemas (``extra='forbid'``
plus ``Literal`` enums): if it does not match the contract, this raises rather than
shipping a malformed file. Only the summary + insights outputs are produced here;
the ``/kpi/alerts`` feed is a separate stream the agent does not generate.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any, get_args, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from . import file_io
from .llm import get_llm
from ..utils.json_utils import dumps

Severity = Literal["critical", "warning", "positive", "info"]
Tone = Literal["positive", "critical", "warning", "info", "teal"]
Direction = Literal["up", "down"]
# Extended tile-schema fields (kpi-tile-schema-proposal.md), gated by
# ai_content_kpi_card_fields -- see the KpiCard fields below.
ValueType = Literal["currency", "count", "percent", "ratio", "days"]
GoodDirection = Literal["up", "down", "neutral"]
ComparisonType = Literal[
    "target", "prior_period", "same_period_last_year", "share_of_total",
    "threshold", "peer_comparison", "other",
]
# The same names as a runtime set, for validating what a signal declares. Read
# off the Literal rather than retyped, so a value added above cannot be
# silently rejected here.
COMPARISON_TYPES = frozenset(get_args(ComparisonType))


# --------------------------------------------------------------------------
# STRICT output schemas -- the contract the MVC controllers deserialize.
# extra='forbid' rejects stray keys; Literal enums reject bad values.
# --------------------------------------------------------------------------
class InsightStat(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: str


class InsightBack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    summary: str
    stats: List[InsightStat]
    action: str


class KpiComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: ComparisonType
    label: str
    baselineValue: Optional[float] = None


class KpiTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float
    attainmentPct: float


class KpiCard(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: int
    # Which report this finding came from. Absent (and dropped from the dumped
    # payload) unless ai_content_multi_report_feed is on, so the single-report
    # feed the app renders today is unchanged byte-for-byte.
    reportId: Optional[str] = None
    severity: Severity
    category: str
    metric: str
    value: str
    delta: str
    deltaDirection: Direction
    description: str
    displayTime: str
    isoDate: str
    comparisonLabel: str
    insight: InsightBack
    # Extended tile-schema fields (kpi-tile-schema-proposal.md). Every one is
    # absent (never an explicit null) unless ai_content_kpi_card_fields is on,
    # so the default payload stays byte-identical -- same guard as reportId.
    label: Optional[str] = None
    rawValue: Optional[float] = None
    unit: Optional[str] = None
    valueType: Optional[ValueType] = None
    goodDirection: Optional[GoodDirection] = None
    comparison: Optional[KpiComparison] = None
    target: Optional[KpiTarget] = None
    shareOfTotalPct: Optional[float] = None
    rank: Optional[int] = None


class MetricBand(BaseModel):
    """Where a measure landed relative to its own normal band.

    The numbers, not the drawing. The report page computes pixel geometry for
    its own 214px bullet chart (`daily_sales_dashboard.bullet`), which is no use
    to a consumer rendering at a different width - so the band travels as four
    figures and every surface draws its own.
    """
    model_config = ConfigDict(extra="forbid")
    actual: float
    floor: float
    benchmark: Optional[float] = None
    ceiling: float


class ReportMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: str
    tone: Tone
    # Everything below is optional and additive, for a consumer that draws a
    # measure against its band rather than as a bare figure. Publishing used to
    # flatten a Daily Sales KPI down to label/value/tone, which threw away the
    # note, the verdict word and the band - the three things that turn "USD
    # 55.3K" into "USD 55.3K, 17.7K under the benchmark, underperforming".
    note: Optional[str] = None
    verdict: Optional[str] = None
    # A measure is read against ONE of these. Daily Sales measures sit inside a
    # band; a Target Tracker period is measured against a single target, which
    # has no floor or ceiling to draw - so the consumer picks its meter from
    # whichever arrived rather than being handed a band that was invented to
    # fill the shape.
    band: Optional[MetricBand] = None
    target: Optional[KpiTarget] = None


class ReportSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str
    tone: Tone
    points: List[str]


class ReportSummaryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    generatedAt: str
    headline: str
    metrics: List[ReportMetric]
    sections: List[ReportSection]


# --------------------------------------------------------------------------
# LLM authoring schemas -- what the model returns (text only, no numbers/enums
# it could get wrong except the tone enum, which is Literal-constrained).
# --------------------------------------------------------------------------
class _KpiCardText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signal_id: str = Field(description="exact id copied from the input signal facts")
    category: str = Field(description="1-2 word front label, e.g. Revenue / Quantity")
    description: str = Field(description="one plain-English card-front sentence")
    insight_title: str
    insight_summary: str
    insight_action: str


class _KpiCardTextList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cards: List[_KpiCardText]


class _MetricSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(description="copied EXACTLY from the available Key Metric labels")
    tone: Tone


class _AuthoredSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    heading: str
    tone: Tone
    points: List[str]


class _AuthoredSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str
    metrics: List[_MetricSelection]
    sections: List[_AuthoredSection]


# --------------------------------------------------------------------------
# deterministic helpers -- numbers, families, severities (code owns these)
# --------------------------------------------------------------------------
def _compact_number(n: Any, *, signed: bool = False) -> str:
    if n is None:
        return ""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return str(n)
    a = abs(n)
    if a >= 1e9:
        s = f"{n / 1e9:.2f}B"
    elif a >= 1e6:
        s = f"{n / 1e6:.2f}M"
    elif a >= 1e3:
        s = f"{n / 1e3:.1f}K"
    else:
        s = f"{n:.0f}"
    if signed and n > 0:
        s = "+" + s
    return s


def _manager_number(n: Any, family: str) -> str:
    """Readable before/after value; keep sub-million counts exact."""
    if family in {"Quantity", "Transactions"} and isinstance(n, (int, float)):
        if abs(float(n)) < 1_000_000:
            return f"{float(n):,.0f}"
    return _compact_number(n)


def _period_change_pct(current: Any, prior: Any) -> Optional[float]:
    if not isinstance(current, (int, float)) or not isinstance(prior, (int, float)):
        return None
    if abs(float(prior)) <= 1e-9:
        return None
    return (float(current) - float(prior)) / abs(float(prior)) * 100.0


def _business_measure(family: str) -> str:
    return {
        "Revenue": "revenue",
        "Quantity": "unit sales",
        "Transactions": "transactions",
    }.get(family, "performance")


def _sentence(text: Any) -> str:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if value and value[-1] not in ".!?":
        value += "."
    return value


def _plain_business_text(text: Any) -> str:
    """Remove recurring analyst shorthand from manager-facing card prose."""
    value = str(text or "")
    replacements = (
        (r"\bmovement decomposition\b", "breakdown of the change"),
        (r"\bvolume effect\b", "change from units sold"),
        (r"\brate effect\b", "change from average revenue per item"),
        (r"\brealized revenue per unit\b", "average revenue per item"),
        (r"\brevenue per unit\b", "average revenue per item"),
        (r"\bshare of total change\b", "part of the overall change"),
        (r"\bbasket mix\b", "items purchased per transaction"),
        (r"\bproduct mix\b", "mix of products sold"),
        (r"\bsell-through\b", "sales"),
        (r"\bbills\b", "transactions"),
        (r"\bbill\b", "transaction"),
        # Retail plain English. The prompt bans these, but a prompt is
        # guidance and this is enforcement: a store manager reading on a
        # phone does not know what a Loc-SKU is, and "the position" is not
        # a thing anyone says about stock on a shop floor. The hedge pairs
        # Hedge-stripping is deliberately NOT done here: removing "may"
        # turns a careful sentence into an asserted cause, which this
        # branch is forbidden to make. That habit is the prompt's to fix.
        (r"\blocation[- ]SKUs\b", "products in stores"),
        (r"\blocation[- ]SKU\b", "product in a store"),
        (r"\bLoc-SKUs\b", "products in stores"),
        (r"\bLoc-SKU\b", "product in a store"),
        (r"\bSKUs\b", "products"),
        (r"\bSKU\b", "product"),
        (r"\bdays of cover\b", "days of stock"),
        (r"\bagreed cover\b", "planned stock level"),
        (r"\babove cover\b", "above the planned stock level"),
        (r"\breplenishment flow\b", "reordering"),
        (r"\bassortment\b", "product range"),
        (r"\bbroad-based\b", "widespread"),
    )
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _share_details(sig: Dict[str, Any], family: str) -> "tuple[str, str, str]":
    """Return delta, contextual UI label, and contextual stat label."""
    share = float(sig.get("impact_share") or 0.0)
    magnitude = f"{abs(share):.1f}%"
    measure = _business_measure(family)
    cid = str(sig.get("candidate_id") or "").casefold()
    analysis_type = str(sig.get("analysis_type") or "").casefold()
    if "concentration" in cid or "concentration" in analysis_type:
        return magnitude, f"of current {measure}", f"Share of current {measure}"

    value = float(sig.get("impact_value") or 0.0)
    total_direction = "increase" if ((value >= 0) == (share >= 0)) else "decline"
    if share >= 0:
        return (
            magnitude,
            f"of the total {total_direction} in {measure}",
            f"Share of {measure} {total_direction}",
        )
    return (
        magnitude,
        f"offsetting the total {total_direction} in {measure}",
        f"Offset to {measure} {total_direction}",
    )


def _is_rate_signal(sig: Dict[str, Any]) -> bool:
    """A standalone peer-growth rate outlier: `stat_basis` is set ONLY for that
    signal type (copied by insight_signal_detector), so it uniquely identifies it."""
    return bool(sig.get("stat_basis")) and isinstance(
        sig.get("reported_growth_pct"), (int, float))


def _rate_relative_phrase(sig: Dict[str, Any]) -> str:
    """The careful, NON-CAUSAL peer-relative clause (Phase 8 wording rule):

    * a small-peer ordinal note -> its pre-built
      "the fastest/slowest of N comparable members" phrase (an ordinal rank, not a
      statistical-outlier claim);
    * a standalone candidate whose ``stat_basis`` proves it passed the configured
      detector threshold -> "unusually fast relative to its N peers". Renderers do
      not hard-code the default peer threshold.

    Never asserts a cause - only that the segment's rate is unusual versus peers.
    """
    ctx = sig.get("peer_rate_context") or {}
    if ctx.get("basis") == "ordinal_only" and ctx.get("phrase"):
        return str(ctx["phrase"])
    n = sig.get("peer_count")
    if _is_rate_signal(sig) and isinstance(n, int) and n > 0:
        return f"unusually fast relative to its {n} peers"
    if isinstance(n, int) and n > 0:
        return f"among {n} comparable members"  # safety: no outlier claim on a small set
    return "unusually fast relative to peers"


def _rate_message(sig: Dict[str, Any], family: str) -> str:
    """Code-owned first sentence for a standalone rate outlier: the segment's own
    growth %, the peer median, and the careful relative clause - all from the
    deterministic facts on the signal, never an LLM estimate, and with no cause."""
    segment = str(sig.get("affected_segment") or "This segment").strip()
    measure = _business_measure(family)
    growth = sig.get("reported_growth_pct")
    median = sig.get("peer_median_reported_pct")
    phrase = _rate_relative_phrase(sig)
    if isinstance(growth, (int, float)):
        verb = "grew" if growth >= 0 else "declined"
        main = f"{segment} {measure} {verb} {abs(growth):.1f}%, {phrase}"
    else:
        main = f"{segment} {measure} moved {phrase}"
    if isinstance(median, (int, float)):
        main += f" (peer median {median:+.1f}%)"
    return main + "."


def _main_change_sentence(sig: Dict[str, Any], family: str) -> str:
    """Code-owned first sentence: movement, magnitude, and comparison context."""
    segment = str(sig.get("affected_segment") or "This segment").strip()
    value = sig.get("impact_value")
    measure = _business_measure(family)
    if not isinstance(value, (int, float)):
        return f"{segment} had a material change in {measure}."

    amount = _compact_number(abs(value))
    rw = sig.get("recent_week") or {}
    wow = rw.get("change_pct")
    if isinstance(wow, (int, float)):
        direction = "higher" if value >= 0 else "lower"
        window = "the previous 7 days" if rw.get("window_mode") == "rolling" else "the previous week"
        return (
            f"{segment} {measure} was {amount} {direction}, a {abs(wow):.1f}% "
            f"change from {window}."
        )

    if sig.get("episode_start") is not None:
        direction = "above" if value >= 0 else "below"
        return (
            f"{segment} {measure} was {amount} {direction} expected from "
            f"{sig.get('episode_start')} through {sig.get('episode_end')}."
        )

    if _is_rate_signal(sig):
        return _rate_message(sig, family)

    cid = str(sig.get("candidate_id") or "").casefold()
    analysis_type = str(sig.get("analysis_type") or "").casefold()
    share = sig.get("impact_share")
    if "current_only" in cid:
        return (
            f"{segment} recorded {amount} in current {measure} but is not part of "
            "the year-over-year comparison."
        )
    if share is not None and ("concentration" in cid or "concentration" in analysis_type):
        return (
            f"{segment} recorded {amount} in {measure}, representing about "
            f"{abs(float(share)):.1f}% of current {measure}."
        )

    current, prior = sig.get("current"), sig.get("prior")
    period_pct = _period_change_pct(current, prior)
    if isinstance(current, (int, float)) and isinstance(prior, (int, float)):
        if family == "Quantity":
            base = (
                f"{segment} sold {amount} {'more' if value >= 0 else 'fewer'} units"
            )
        elif family == "Transactions":
            base = (
                f"{segment} recorded {amount} {'more' if value >= 0 else 'fewer'} transactions"
            )
        else:
            base = (
                f"{segment} {measure} {'increased' if value >= 0 else 'decreased'} by {amount}"
            )
        pct_text = f" ({abs(period_pct):.1f}%)" if period_pct is not None else ""
        base += (
            f"{pct_text}, from {_manager_number(prior, family)} to "
            f"{_manager_number(current, family)} versus the prior period"
        )
        if share is None:
            return base + "."
        share_value = float(share)
        total_direction = "increase" if ((value >= 0) == (share_value >= 0)) else "decline"
        if share_value >= 0:
            context = (
                f"about {abs(share_value):.1f}% of the total {total_direction} in {measure}"
            )
        else:
            context = (
                f"an offset equal to about {abs(share_value):.1f}% of the total "
                f"{total_direction} in {measure}"
            )
        return f"{base}, representing {context}."

    if family == "Quantity":
        base = f"{segment} sold {amount} {'more' if value >= 0 else 'fewer'} units"
    elif family == "Transactions":
        base = f"{segment} recorded {amount} {'more' if value >= 0 else 'fewer'} transactions"
    else:
        base = f"{segment} {measure} {'increased' if value >= 0 else 'decreased'} by {amount}"

    if share is None:
        return base + "."
    share_value = float(share)
    total_direction = "increase" if ((value >= 0) == (share_value >= 0)) else "decline"
    if share_value >= 0:
        if abs(share_value) > 100:
            context = (
                f"equivalent to about {abs(share_value):.1f}% of the net {total_direction} "
                f"in {measure} because movements elsewhere offset part of it"
            )
        else:
            context = (
                f"accounting for about {abs(share_value):.1f}% of the total "
                f"{total_direction} in {measure}"
            )
    else:
        context = (
            f"offsetting about {abs(share_value):.1f}% of the total "
            f"{total_direction} in {measure}"
        )
    return f"{base}, {context}."


def _main_decomposition_stat(sig: Dict[str, Any]) -> Optional[Dict[str, str]]:
    decomp = sig.get("decomposition") or []
    if not decomp:
        return None
    item = decomp[0] or {}
    driver = str(item.get("driver") or "").casefold()
    if any(token in driver for token in ("qty", "quantity", "unit")):
        volume_label, rate_label = "Change from units sold", "Change from revenue per item"
    elif any(token in driver for token in ("bill", "transaction", "order")):
        volume_label, rate_label = "Change from transactions", "Change from revenue per transaction"
    elif "customer" in driver:
        volume_label, rate_label = "Change from customers", "Change from revenue per customer"
    else:
        volume_label, rate_label = "Change from volume", "Change from average value"
    volume = item.get("volume_effect")
    rate = item.get("rate_effect")
    if not isinstance(volume, (int, float)) and not isinstance(rate, (int, float)):
        return None
    if not isinstance(rate, (int, float)) or (
        isinstance(volume, (int, float)) and abs(volume) >= abs(rate)
    ):
        return {"label": volume_label, "value": _compact_number(volume, signed=True)}
    return {"label": rate_label, "value": _compact_number(rate, signed=True)}


def _now(generated_at: Optional[datetime]) -> datetime:
    return generated_at or datetime.now()


def _signal_family(sig: Dict[str, Any]) -> str:
    d = (sig.get("description") or "").lower()
    hits: Dict[str, int] = {}
    for key, label in (
        ("net revenue", "Revenue"),
        ("revenue", "Revenue"),
        ("quantity", "Quantity"),
        ("qty", "Quantity"),
        ("transactions", "Transactions"),
        ("transaction", "Transactions"),
        ("orders", "Transactions"),
        ("bills", "Transactions"),
    ):
        i = d.find(key)
        if i >= 0:
            hits.setdefault(label, i)
    return min(hits, key=hits.get) if hits else "Performance"


def _signal_severity(sig: Dict[str, Any]) -> Severity:
    # A detector that graded its own finding wins. The heuristics below all read
    # a year-on-year share, which a target-vs-actual or stock-vs-policy signal
    # does not have; guessing from an absent share would grade it "info".
    declared = str(sig.get("severity") or "").strip().lower()
    if declared in ("critical", "warning", "positive", "info"):
        return declared  # type: ignore[return-value]
    cid = sig.get("candidate_id") or ""
    share = sig.get("impact_share")
    val = sig.get("impact_value") or 0
    if sig.get("kind") == "data_quality":
        return "warning"
    # Recent-week/rolling signals have no annual share; grade by the WoW/rolling
    # move instead.
    wow = (sig.get("recent_week") or {}).get("change_pct")
    if isinstance(wow, (int, float)):
        if val < 0:
            return "critical" if abs(wow) >= 10 else "warning"
        return "positive"
    # Daily incidents have no annual share either; grade by deviation vs expected.
    if sig.get("episode_start") is not None:
        expected = sig.get("expected_total")
        dev_pct = (abs(val) / abs(expected) * 100.0
                   if isinstance(expected, (int, float)) and expected else 0.0)
        if val < 0:
            return "critical" if dev_pct >= 10 else "warning"
        return "positive"
    # Rate outliers carry no annual share; grade by the segment's own growth
    # direction (a fast decline reads as a concern, fast growth as positive).
    if _is_rate_signal(sig):
        return "positive" if (sig.get("reported_growth_pct") or 0) >= 0 else "warning"
    if "current_only" in cid or share is None or "concentration" in cid:
        return "info"
    if val < 0:
        return "critical" if abs(share) >= 150 else "warning"
    return "positive"


# --------------------------------------------------------------------------
# Extended tile-schema fields (kpi-tile-schema-proposal.md), gated by
# ai_content_kpi_card_fields in _assemble_kpi_card below.
# --------------------------------------------------------------------------
EXTENDED_CARD_KEYS = (
    "label", "rawValue", "unit", "valueType", "goodDirection",
    "comparison", "target", "shareOfTotalPct", "rank",
)

# Two classifiers, most-reliable first. `metric_family` is a machine field a
# domain declares itself (target_tracker/sales_yoy: "revenue"; stock_health/
# ageing/sku_overview: "stock_value") - trust it when present. `family` (see
# `_signal_family`) is a fallback keyword match over free-form prose and only
# reliably resolves Revenue/Quantity/Transactions; everything else falls
# through to "Performance", which covers real currency figures, plain SKU
# counts and health scores alike (the docs' own "STOCK OUT ... performance
# increased by 17.8K" is a count, not a value, on that exact bucket). Rather
# than guess a unit/direction for "Performance", both are left absent there -
# a missing field the app already treats as "draw nothing", never a wrong one.
# "stock_value" deliberately has no direction: whether more stock is good
# depends on which measure it is (excess stock up is bad; stock on hand up
# is not, on its own) and the signal doesn't say which - so it is guessed
# only via the explicit `good_direction` declaration hook below, never here.
_VALUE_TYPE_BY_METRIC_FAMILY = {"revenue": "currency", "stock_value": "currency",
                                 "quantity": "count", "transactions": "count"}
_GOOD_DIRECTION_BY_METRIC_FAMILY = {"revenue": "up", "quantity": "up", "transactions": "up"}
_VALUE_TYPE_BY_FAMILY = {"Revenue": "currency", "Quantity": "count", "Transactions": "count"}
_GOOD_DIRECTION_BY_FAMILY = {"Revenue": "up", "Quantity": "up", "Transactions": "up"}

# Reports that carry their own currency config key already (config_schema.py).
# A report with none of its own (the original Sales YoY report) falls back to
# the generic ai_content_kpi_currency key.
_CURRENCY_CONFIG_KEY_BY_REPORT = {
    "target_tracker": "target_tracker_currency",
    "inventory_ageing": "ageing_currency",
    "stock_age_analysis": "ageing_currency",
    "inventory_stock_health": "inventory_currency",
    "inventory_management": "inventory_currency",
    "daily_sales": "daily_sales_currency",
    "sku_overview": "sku_overview_currency",
}


def _cfg_value(state: Optional[dict], key: str) -> Any:
    state = state or {}
    value = state.get(key)
    if value is None:
        value = (state.get("config") or {}).get(key)
    return value


def kpi_extended_fields(state: Optional[dict]) -> bool:
    """Off by default: adding a card key is an app contract change (see
    docs/phase5-app-contract-change.md for the reportId precedent)."""
    return bool(_cfg_value(state, "ai_content_kpi_card_fields"))


def _kpi_currency(state: Optional[dict], report_id: Optional[str]) -> Optional[str]:
    """The report's configured currency, or None.

    None is a real answer here. This used to end `return str(value) if value
    else "SAR"`, so a report with no currency of its own was stamped with one
    anyway - and only seven reports have their own key, which does not include
    the original Sales YoY report. On a live client that put "SAR +406.3K" and
    "SAR +383.7K" beside "USD -334.8K" on one Home strip, for a client in
    neither country: two currencies in one glance, one of them invented.

    A wrong currency on a financial figure is not a display bug, it is a false
    statement about money, and it is worse than no currency at all - an
    unqualified "+406.3K" is merely incomplete. So the fallback chain still
    runs (a client CAN set ai_content_kpi_currency and mean it), but it ends in
    nothing rather than in a guess. `unit` is optional precisely so that absent
    can mean "draw nothing", which is the rule every other extended field on
    the card already follows.
    """
    key = _CURRENCY_CONFIG_KEY_BY_REPORT.get(report_id or "")
    value = _cfg_value(state, key) if key else None
    if not value:
        value = _cfg_value(state, "ai_content_kpi_currency")
    text = str(value).strip() if value else ""
    return text or None


def _kpi_value_type_and_unit(
    sig: Dict[str, Any], family: str, state: Optional[dict], report_id: Optional[str]
) -> "tuple[Optional[str], Optional[str]]":
    declared_type = sig.get("value_type")
    if declared_type in ("currency", "count", "percent", "ratio", "days"):
        return declared_type, sig.get("value_unit")
    metric_family = str(sig.get("metric_family") or "").strip().casefold()
    value_type = _VALUE_TYPE_BY_METRIC_FAMILY.get(metric_family) or _VALUE_TYPE_BY_FAMILY.get(family)
    if value_type is None:
        return None, None
    unit = _kpi_currency(state, report_id) if value_type == "currency" else None
    return value_type, unit


def _kpi_good_direction(sig: Dict[str, Any], family: str) -> Optional[str]:
    declared = sig.get("good_direction")
    if declared in ("up", "down", "neutral"):
        return declared
    if sig.get("kind") == "data_quality":
        return "neutral"
    if _is_rate_signal(sig):
        return "up"
    metric_family = str(sig.get("metric_family") or "").strip().casefold()
    return _GOOD_DIRECTION_BY_METRIC_FAMILY.get(metric_family) or _GOOD_DIRECTION_BY_FAMILY.get(family)


# Dimension values that name the whole population rather than one entity -
# labelling a card "Company REVENUE" reads as a typo, not a scope.
# Dimensions that are a CLASSIFICATION rather than a thing with a name. A
# branch is an entity and reads well as "Branch ST2"; a recommended action is a
# bucket, and "Recommended Action STOCK OUT - PLACE ORDER" is three words of
# scaffolding in front of a status that already says what it is.
_NON_ENTITY_DIMENSIONS = {"", "company", "estate", "overall", "business",
                          "recommended action", "recommended_action",
                          "status", "state", "bucket", "classification"}

# A tile name, not a sentence. The proposal asks for ~40 characters; past this
# the tile clamps and cuts the end, which is where the measure sits.
_LABEL_MAX = 48


def _kpi_label(sig: Dict[str, Any]) -> Optional[str]:
    segment = str(sig.get("affected_segment") or "").strip()
    if not segment:
        # No segment does not mean no name. A whole-business finding carries no
        # segment by design - it is about everything - and returning None here
        # left the tile with nothing but the card's `metric`, which for that
        # same card is also empty. The measure is a perfectly good name on its
        # own: "Net Sales vs its normal band" says what the number is.
        return str(sig.get("metric") or "").strip() or None
    dimension = str(sig.get("dimension") or "").strip()
    metric_name = str(sig.get("metric") or "").strip()
    # "recommended_action" -> "Recommended Action". .title() alone leaves the
    # underscore in place and prints "Recommended_Action" on the tile.
    dimension = dimension.replace("_", " ").strip()
    prefix = (f"{dimension.title()} {segment}"
              if dimension.casefold() not in _NON_ENTITY_DIMENSIONS else segment)
    if not metric_name:
        return prefix

    label = f"{prefix} — {metric_name}"
    if len(label) <= _LABEL_MAX:
        return label

    # Too long to be a name. The measure is the half a reader cannot get
    # anywhere else - the segment is on the card as `metric` and every surface
    # already shows it - so when only one half fits, keep that one rather than
    # publishing a composite the tile will truncate mid-measure.
    return metric_name if len(metric_name) <= _LABEL_MAX else prefix


def _kpi_target(target_value: Any, val: Any, sig: Dict[str, Any]) -> Optional[Dict[str, float]]:
    if not isinstance(target_value, (int, float)) or not target_value:
        return None
    current_value = sig.get("current")
    if not isinstance(current_value, (int, float)) and isinstance(val, (int, float)):
        current_value = float(target_value) + float(val)
    attainment = sig.get("attainment_pct")
    if not isinstance(attainment, (int, float)) and isinstance(current_value, (int, float)):
        attainment = float(current_value) / float(target_value) * 100.0
    if not isinstance(attainment, (int, float)):
        return None
    return {"value": float(target_value), "attainmentPct": round(float(attainment), 1)}


def _rate_stats(sig: Dict[str, Any], family: str) -> List[Dict[str, str]]:
    """Structured rate facts as card stats (code-owned, not LLM-estimated): the
    segment's growth, the peer median, and the statistical basis (robust z, or a
    flat-peer break where a z is undefined) plus the peer count."""
    growth = sig.get("reported_growth_pct")
    median = sig.get("peer_median_reported_pct")
    z = sig.get("robust_z")
    stats: List[Dict[str, str]] = []
    if isinstance(growth, (int, float)):
        stats.append({"label": f"{family} growth", "value": f"{growth:+.1f}%"})
    if isinstance(median, (int, float)):
        stats.append({"label": "Peer median", "value": f"{median:+.1f}%"})
    if isinstance(z, (int, float)):
        stats.append({"label": "Robust z", "value": f"{z:+.1f}"})
    elif sig.get("stat_basis") == "flat_peer_break":
        stats.append({"label": "Peer basis", "value": "flat peer set"})
    if sig.get("peer_count") is not None and len(stats) < 3:
        stats.append({"label": "Peers", "value": str(sig.get("peer_count"))})
    return stats[:3]


def _grounded_summary(sig: Dict[str, Any], family: str, authored: Any) -> str:
    """The back-of-card summary, held to the figures code actually measured.

    Two failure modes, one fallback. A summary quoting a figure that is not on
    the allowed list is not trustworthy, and a summary carrying no figure at all
    is the vague restatement this field shipped for months ("The movement
    relates to damage across all locations..."). Both are replaced by the
    code-owned sentence, which is grounded by construction and is the sentence
    the reader needed in the first place.
    """
    summary = _sentence(_plain_business_text(authored))
    allowed = {f.replace(",", "").replace(" ", "") for f in _quotable_figures(sig, family)}
    if not allowed:
        # Nothing measured to quote (a rate outlier carries its facts as stats),
        # so hold the model to its words alone rather than to an empty list.
        return summary
    written = _figures(summary)
    if written and written <= allowed:
        return summary
    grounded = _sentence(_lead_sentence(sig, family))
    return grounded or summary


_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


def _readable_member(value: str) -> str:
    """A month a manager recognises, not the ISO date the model stores it as."""
    m = _ISO_DATE_RE.match(value.strip())
    if not m:
        return value
    year, month, day = (int(g) for g in m.groups())
    if not 1 <= month <= 12:
        return value
    name = f"{_MONTHS[month - 1]} {year}"
    return name if day == 1 else f"{day} {_MONTHS[month - 1]} {year}"


def _insight_stats(sig: Dict[str, Any], family: str) -> List[Dict[str, str]]:
    if _is_rate_signal(sig):
        return _rate_stats(sig, family)
    val = sig.get("impact_value")
    share = sig.get("impact_share")
    # A LEVEL is not a change, and labelling it one states a movement that did
    # not happen: a count of 18,344 products sitting in a stock-out state
    # published as "Performance change  +18.3K". A signal that knows what its
    # figure is says so; everything else keeps the change wording.
    is_level = str(sig.get("value_kind") or "").strip().casefold() == "level"
    declared_value_label = str(sig.get("value_label") or "").strip()
    if declared_value_label:
        measure_label = declared_value_label
    elif is_level:
        measure_label = str(sig.get("metric") or "").strip() or family
    else:
        measure_label = {
            "Quantity": "Unit sales change",
            "Transactions": "Transaction change",
        }.get(family, f"{family} change")
    stats: List[Dict[str, str]] = [
        {"label": measure_label, "value": _compact_number(val, signed=not is_level)}
    ]
    if share is not None:
        # `impact_share` is not always a share. On a snapshot spine it carries
        # whatever that report measured its percentage against - for Damage it
        # is 317.0%, the amount ABOVE a three-month average, and calling that a
        # "Share of performance increase" published an impossible figure: no
        # share exceeds 100%. A signal that declares what its percentage means
        # is believed; only the year-on-year spine keeps the share wording.
        declared_share_label = str(sig.get("share_label") or "").strip()
        if declared_share_label:
            stat_label = declared_share_label
        else:
            _, _, stat_label = _share_details(sig, family)
        stats.append({"label": stat_label, "value": f"{abs(float(share)):.1f}%"})
    else:
        # Recent-week/rolling signals carry a WoW/rolling % (not a share of an
        # annual total); daily incidents carry a deviation vs expected instead.
        rw = sig.get("recent_week") or {}
        if isinstance(rw.get("change_pct"), (int, float)):
            label = "Vs prior 7 days" if rw.get("window_mode") == "rolling" else "Week over week"
            stats.append({"label": label, "value": f"{rw['change_pct']:+.1f}%"})
        elif sig.get("episode_start") is not None:
            expected = sig.get("expected_total")
            if isinstance(expected, (int, float)) and expected and isinstance(val, (int, float)):
                stats.append({"label": "Vs expected", "value": f"{val / abs(expected) * 100.0:+.1f}%"})
    decomp = sig.get("decomposition")
    members = sig.get("segment_members")
    if decomp:
        main_stat = _main_decomposition_stat(sig)
        if main_stat:
            stats.append(main_stat)
    elif members:
        # Two ways this shipped nonsense. The Damage signal's "member" is the
        # month it covers, so the card published `Segments: 2026-08-01` - a raw
        # ISO date under a label promising a business area. And a state signal's
        # member IS its segment, so the stat repeated the card's own heading
        # back at the reader. Publish it only when it adds something, name it
        # after the dimension it came from, and render a date as a date.
        shown = [str(m).strip() for m in members if str(m).strip()]
        segment = str(sig.get("affected_segment") or "").strip()
        if shown and shown != [segment]:
            dimension = str(sig.get("dimension") or "").replace("_", " ").strip()
            stats.append({
                "label": dimension.title() if dimension else "Segments",
                "value": ", ".join(_readable_member(m) for m in shown),
            })
    return stats[:3]


# figures that carry meaning (decimals, K/M/B/%, or comma-grouped) -- bare small
# ints and years are ignored so the fidelity guard doesn't false-drop "top 3".
_FIG_RE = re.compile(r"-?\d[\d,]*\.\d+\s*[KMB%]?|-?\d[\d,]*\s*[KMB%]|-?\d{1,3}(?:,\d{3})+")


def _figures(text: str) -> set:
    return {m.group(0).replace(",", "").replace(" ", "") for m in _FIG_RE.finditer(text or "")}


# --------------------------------------------------------------------------
# report_summary.md structural parsing (feeds the LLM + injects metric values)
# --------------------------------------------------------------------------
def _parse_sections(md: str) -> Dict[str, List[str]]:
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in md.splitlines():
        m = re.match(r"^#\s+(.*)$", line)
        if m:
            current = m.group(1).strip()
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)
    return sections


def _parse_key_metrics(lines: Sequence[str]) -> "list[tuple[str, str]]":
    out = []
    for raw in lines:
        m = re.match(r"^\s*-\s+(.*?):\s+(.*\S)\s*$", raw)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


# --------------------------------------------------------------------------
# LLM invocation with one retry
# --------------------------------------------------------------------------
def _invoke(state: dict, schema, system: str, user: str):
    last = None
    for attempt in range(2):
        try:
            llm = get_llm(state, structured_schema=schema)
            return llm.invoke(
                [{"role": "system", "content": system}, {"role": "user", "content": user}]
            )
        except Exception as e:  # noqa: BLE001 - retry once, then surface
            last = e
    raise RuntimeError(f"LLM structured call failed after retry: {last}")


# --------------------------------------------------------------------------
# /kpi/insights
# --------------------------------------------------------------------------
def _quotable_figures(sig: Dict[str, Any], family: str) -> List[str]:
    """The exact display strings the LLM may copy into its prose.

    The prompt used to forbid figures outright, which is why every
    `insight_summary` read like "The movement relates to damage across all
    locations" - a restatement of the title followed by a guess at what an
    analysis might show. A summary with no number cannot carry a finding, and
    the modal shows the summary rather than the code-owned `description`, so
    the one specific sentence on the card never reached the reader.

    Letting the model write numbers freely is the other failure, so this is the
    same contract `report_summary` already uses for its bullets: the model may
    quote, and only quote, figures that appear here, and `_figures` re-checks
    the returned text against this set. A figure that is not on the list means
    the sentence is dropped for a grounded one, never published.
    """
    out: List[str] = []

    def add(text: Any) -> None:
        for token in _FIG_RE.finditer(str(text or "")):
            value = token.group(0).strip()
            if value not in out:
                out.append(value)

    # Whatever the grounded sentences already state - these carry the real
    # before/after values (e.g. "275,371", "66,038", "317.0%").
    add(_lead_sentence(sig, family))
    add(sig.get("description"))
    # ...plus the compact forms code itself prints on the card face.
    val = sig.get("impact_value")
    if isinstance(val, (int, float)):
        add(_compact_number(val, signed=True))
        add(_compact_number(val, signed=False))
    share = sig.get("impact_share")
    if isinstance(share, (int, float)):
        add(f"{abs(float(share)):.1f}%")
    return out


def _signal_facts(sig: Dict[str, Any]) -> Dict[str, Any]:
    val = sig.get("impact_value")
    rw = sig.get("recent_week") or {}
    family = _signal_family(sig)
    return {
        "signal_id": sig.get("id"),
        "segment": sig.get("affected_segment"),
        "segment_members": sig.get("segment_members"),
        "measure_family": family,
        "direction": "increase" if (val or 0) >= 0 else "decrease",
        "impact_display": _compact_number(val, signed=True),
        "share_of_change_pct": sig.get("impact_share"),
        "code_owned_main_message": _main_change_sentence(sig, family),
        "week_over_week_pct": rw.get("change_pct"),
        "recent_week": {k: rw.get(k) for k in
                        ("window_mode", "week_start", "week_end", "actual", "previous",
                         "expected", "facets")} if rw else None,
        "daily_incident": {
            "episode_start": sig.get("episode_start"), "episode_end": sig.get("episode_end"),
            "actual_total": sig.get("actual_total"), "expected_total": sig.get("expected_total"),
            "peak_z": sig.get("peak_z"),
        } if sig.get("episode_start") is not None else None,
        # Rate outlier facts (Phase 8): the LLM writes prose around them; every
        # number and the careful non-causal relative phrase are owned by code.
        "rate_outlier": {
            "reported_growth_pct": sig.get("reported_growth_pct"),
            "peer_median_pct": sig.get("peer_median_reported_pct"),
            "robust_z": sig.get("robust_z"), "stat_basis": sig.get("stat_basis"),
            "peer_count": sig.get("peer_count"),
            "relative_phrase": _rate_relative_phrase(sig),
        } if _is_rate_signal(sig) else None,
        # Small-peer ordinal rank riding on a bridge story (never a standalone claim).
        "peer_rank": sig.get("peer_rate_context"),
        "kind": sig.get("kind"),
        "decomposition": sig.get("decomposition"),
        "analyst_question": sig.get("question"),
        "raw_finding": sig.get("description"),
        # The ONLY figures the model may write. See _quotable_figures.
        "quote_these_display_values": _quotable_figures(sig, family),
    }


def _author_kpi_texts(facts: List[Dict[str, Any]], state: dict) -> Dict[str, _KpiCardText]:
    system = (
        file_io.read_prompt("_global_rules.md")
        + file_io.business_rules_block(state)
        + "\n\n"
        + file_io.read_prompt("kpi_insights_generator_prompt.md")
    )
    out: Dict[str, _KpiCardText] = {}
    remaining = facts
    for _ in range(2):
        user = (
            "SIGNAL FACTS -- author one card per signal_id. Numbers are fixed and "
            "injected by code; do not restate raw values:\n" + dumps(remaining)
        )
        result: _KpiCardTextList = _invoke(state, _KpiCardTextList, system, user)
        for c in result.cards:
            out.setdefault(c.signal_id, c)
        remaining = [f for f in facts if f["signal_id"] not in out]
        if not remaining:
            break
    return out


def multi_report_feed(state: dict) -> bool:
    """True when several reports share one client feed (see docs/phase5-app-contract-change.md)."""
    cfg = (state or {}).get("config") or {}
    return bool(
        (state or {}).get("ai_content_multi_report_feed")
        or cfg.get("ai_content_multi_report_feed")
    )


def feed_report_id(state: dict) -> str:
    """The short report slug stamped on this run's cards (WP1 identity)."""
    cfg = (state or {}).get("config") or {}
    return str(
        (state or {}).get("report_id") or cfg.get("report_id") or "sales_yoy"
    ).strip()


def stable_card_id(report_id: str, story_key: Any, fallback: int) -> int:
    """A collision-free, run-stable integer id for a card in a shared feed.

    The per-run ``enumerate(..., start=1)`` sequence is safe for one report and
    unsafe the moment two share a feed: both emit ``id: 1, 2, 3`` and a consumer
    keying on id sees two different cards claiming to be card 1. Hashing the
    report id together with the finding's own stable ``story_key`` fixes both
    problems at once - unique across reports, and unchanged when the same
    finding is republished tomorrow.

    Bounded below 2^31 so the value still fits a signed 32-bit integer column.
    Falls back to the run sequence for a legacy signal carrying no story_key,
    which is still unique within its own report's cards.
    """
    key = str(story_key or "").strip()
    if not key:
        key = f"__seq__:{int(fallback)}"
    digest = hashlib.sha256(f"{report_id}|{key}".encode("utf-8")).hexdigest()
    return 1 + (int(digest[:12], 16) % 2_000_000_000)


def _lead_sentence(sig: Dict[str, Any], family: str) -> str:
    """The card's code-owned first sentence.

    `_main_change_sentence` is written for a change spine - it says "increased
    by X, accounting for Y% of the total increase". A report whose spine is not
    a period-over-period comparison has no such total, and forcing one produces
    a sentence that is confidently wrong: a stock position published as
    "STOCK OUT - PLACE ORDER performance increased by 17.8K, accounting for
    12.7% of the total increase in performance", when nothing increased and the
    figure is a count of Loc-SKUs rather than a value.

    Those reports already write their own lead sentence, grounded in their own
    model and checked by their own prose validator, so it is used verbatim. The
    test is `comparison_label`: a spine that declares its own baseline is by
    construction not year-on-year, which leaves every existing year-on-year
    signal on the original path untouched.
    """
    declared = str(sig.get("description") or "").strip()
    if declared and str(sig.get("comparison_label") or "").strip():
        return _sentence(declared)
    return _main_change_sentence(sig, family)


def _assemble_kpi_card(
    idx: int,
    sig: Dict[str, Any],
    text: _KpiCardText,
    when: datetime,
    report_id: Optional[str] = None,
    *,
    extended_fields: bool = False,
    state: Optional[dict] = None,
) -> Dict[str, Any]:
    family = _signal_family(sig)
    val = sig.get("impact_value")
    share = sig.get("impact_share")
    category = text.category.strip() or ("Data Quality" if sig.get("kind") == "data_quality" else family)
    rw = sig.get("recent_week") or {}
    wow = rw.get("change_pct")
    # Alongside the existing prose delta/comparison, each branch also names its
    # own machine-readable comparison type/chip/baseline for the extended
    # `comparison` field -- one branch per kind of baseline this pipeline
    # actually produces, never a guess at one it doesn't.
    comparison_type: Optional[str] = None
    comparison_chip = ""
    baseline_value: Optional[float] = None
    share_total_pct: Optional[float] = None
    target_value = sig.get("target")
    declared_comparison = str(sig.get("comparison_label") or "").strip()
    if declared_comparison:
        # A spine that is not year-on-year must name its own baseline. Without
        # this, a Target Tracker signal falls through to the share branch and is
        # published against "the prior period" - a comparison this dataset does
        # not contain at all (Non-negotiable 2).
        if isinstance(val, (int, float)) and isinstance(target_value, (int, float)) and target_value:
            delta = f"{abs(val / abs(target_value) * 100.0):.1f}%"
        elif isinstance(sig.get("delta_pct"), (int, float)):
            # A signal that has worked out its own percentage says so. Without
            # this, every declared-baseline card published an empty delta and
            # the tile showed a bare figure with nothing to size it against:
            # "-7.1K" is a different day at a business turning 55K than at one
            # turning 5M, and only the percentage says which.
            delta = f"{abs(float(sig['delta_pct'])):.1f}%"
        else:
            delta = ""
        comparison = declared_comparison

        # A signal that knows what KIND of baseline it declared says so too,
        # rather than being filed under "other" with everything else.
        declared_type = str(sig.get("comparison_type") or "").strip()
        declared_chip = str(sig.get("comparison_chip") or "").strip()
        if declared_type in COMPARISON_TYPES and declared_chip:
            comparison_type, comparison_chip = declared_type, declared_chip
        elif isinstance(target_value, (int, float)):
            comparison_type, comparison_chip = "target", "vs target"
            baseline_value = float(target_value)
        elif str(sig.get("value_kind") or "").strip().casefold() == "level":
            # A LEVEL has no baseline. It is a reading of one position - "17,215
            # Loc-SKUs are in this state" - and there is no prior, no target and
            # nothing it was measured against. Publishing "other"/"vs baseline"
            # put a chip reading "vs baseline" on a card that compares itself to
            # nothing, which is a claim, not a caption.
            #
            # What it does have is its share of the whole, and the declared
            # clause already states it ("12.4% of all Loc-SKUs in the stock
            # position"), so that is the comparison such a card actually makes.
            if isinstance(sig.get("impact_share"), (int, float)):
                comparison_type, comparison_chip = "share_of_total", "share of total"
                share_total_pct = abs(float(sig["impact_share"]))
            # else: no chip at all rather than an invented one.
        else:
            # A declared, non-target baseline (e.g. an inventory policy band or
            # a snapshot-vs-snapshot position) whose exact kind isn't encoded
            # anywhere on the signal - "other" rather than a specific guess.
            comparison_type, comparison_chip = "other", "vs baseline"
    elif isinstance(wow, (int, float)):
        if rw.get("window_mode") == "rolling":
            delta = f"{abs(wow):.1f}%"
            comparison = f"vs the prior 7 days (ending {rw.get('week_end')})"
            comparison_chip = "vs prior 7 days"
        else:
            delta, comparison = f"{abs(wow):.1f}%", f"week over week (from {rw.get('week_start')})"
            comparison_chip = "week over week"
        comparison_type = "prior_period"
        prev = rw.get("previous")
        baseline_value = float(prev) if isinstance(prev, (int, float)) else None
    elif sig.get("episode_start") is not None:
        expected = sig.get("expected_total")
        if isinstance(expected, (int, float)) and expected and isinstance(val, (int, float)):
            delta = f"{abs(val / abs(expected) * 100.0):.1f}%"
        else:
            delta = ""
        comparison = f"vs expected ({sig.get('episode_start')}..{sig.get('episode_end')})"
        comparison_type, comparison_chip = "threshold", "vs expected"
        baseline_value = float(expected) if isinstance(expected, (int, float)) else None
    elif _is_rate_signal(sig):
        growth = sig.get("reported_growth_pct")
        median = sig.get("peer_median_reported_pct")
        delta = f"{abs(growth):.1f}%" if isinstance(growth, (int, float)) else ""
        comparison = (f"vs peer median {median:+.1f}%"
                      if isinstance(median, (int, float)) else "relative to peers")
        comparison_type, comparison_chip = "peer_comparison", "vs peer median"
        baseline_value = float(median) if isinstance(median, (int, float)) else None
    elif isinstance(sig.get("current"), (int, float)) and isinstance(sig.get("prior"), (int, float)):
        period_pct = _period_change_pct(sig.get("current"), sig.get("prior"))
        delta = f"{abs(period_pct):.1f}%" if period_pct is not None else ""
        comparison = "vs the prior period"
        comparison_type, comparison_chip = "same_period_last_year", "vs last year"
        baseline_value = float(sig["prior"])
    elif share is not None:
        delta, comparison, _ = _share_details(sig, family)
        comparison_type, comparison_chip = "share_of_total", "share of total"
        share_total_pct = abs(float(share))
    else:
        delta, comparison = "", "current period"
    # A LEVEL is not a movement, and signing one says it is.
    #
    # A snapshot signal - "17,215 Loc-SKUs are in STOCK OUT - PLACE ORDER" -
    # carries a count of what is in that state right now. Published through
    # signed=True it became "+17.2K", which reads as a rise of 17.2K, and the
    # card had no delta to contradict it. Signals that know they are levels now
    # say so (see the inventory _signal helper); everything else keeps the sign,
    # because for a genuine change the direction is the point.
    is_level = str(sig.get("value_kind") or "").strip().casefold() == "level"

    card = {
        "id": stable_card_id(report_id, sig.get("story_key"), idx) if report_id else idx,
        "reportId": report_id or None,
        "severity": _signal_severity(sig),
        "category": category,
        # affected_segment, when there is one. The old fallback was the literal
        # string "Segment", which is not a name and reached a customer's home
        # page as the heading of a tile; an absent segment is better carried as
        # an empty string, which every consumer already treats as "no segment".
        "metric": sig.get("affected_segment") or "",
        "value": _compact_number(val, signed=not is_level),
        "delta": delta,
        "deltaDirection": "up" if (val or 0) >= 0 else "down",
        "description": " ".join(
            part for part in (
                _lead_sentence(sig, family),
                _sentence(_plain_business_text(text.description)),
            ) if part
        ),
        "displayTime": when.strftime("%I:%M %p").lstrip("0"),
        "isoDate": when.date().isoformat(),
        "comparisonLabel": comparison,
        "insight": {
            "title": _plain_business_text(text.insight_title),
            "summary": _grounded_summary(sig, family, text.insight_summary),
            "stats": _insight_stats(sig, family),
            "action": _sentence(_plain_business_text(text.insight_action)),
        },
    }
    if extended_fields:
        value_type, unit = _kpi_value_type_and_unit(sig, family, state, report_id)
        card["label"] = _kpi_label(sig)
        card["rawValue"] = float(val) if isinstance(val, (int, float)) else None
        card["unit"] = unit
        card["valueType"] = value_type
        card["goodDirection"] = _kpi_good_direction(sig, family)
        card["target"] = _kpi_target(target_value, val, sig)
        card["shareOfTotalPct"] = round(share_total_pct, 1) if share_total_pct is not None else None
        card["rank"] = idx
        card["comparison"] = (
            {"type": comparison_type, "label": comparison_chip, "baselineValue": baseline_value}
            if comparison_type else None
        )
    dumped = KpiCard(**card).model_dump()  # strict validation
    if dumped.get("reportId") is None:
        # Single-report mode must emit the exact key set the app renders today,
        # so the field is removed rather than published as an explicit null.
        dumped.pop("reportId", None)
    for key in EXTENDED_CARD_KEYS:
        # Off by default, and even when on, a field with nothing to say (no
        # target, an unclassified family, ...) is dropped rather than
        # published as an explicit null - the proposal's own compatibility
        # rule: absent means "draw nothing", never "draw a wrong thing".
        if not extended_fields or dumped.get(key) is None:
            dumped.pop(key, None)
    return dumped


def generate_kpi_insights_payload(
    signals: Sequence[Dict[str, Any]],
    state: dict,
    *,
    generated_at: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """insight_signals.json -> LLM-authored, strictly-validated /kpi/insights array."""
    signals = list(signals or [])
    if not signals:
        return []
    when = _now(generated_at)
    texts = _author_kpi_texts([_signal_facts(s) for s in signals], state)
    report_id = feed_report_id(state) if multi_report_feed(state) else None
    extended_fields = kpi_extended_fields(state)
    cards: List[Dict[str, Any]] = []
    for idx, sig in enumerate(signals, start=1):
        text = texts.get(sig.get("id"))
        if text is None:
            raise RuntimeError(f"LLM returned no card text for signal id {sig.get('id')!r}")
        cards.append(_assemble_kpi_card(
            idx, sig, text, when, report_id=report_id,
            extended_fields=extended_fields, state=state,
        ))
    return cards


# --------------------------------------------------------------------------
# /report/summary
# --------------------------------------------------------------------------
def generate_report_summary_payload(
    md_text: str,
    state: dict,
    *,
    title: str = "AI Summary",
    generated_at: Optional[datetime] = None,
    max_metrics: int = 8,
) -> Dict[str, Any]:
    """report_summary.md -> LLM-authored, strictly-validated /report/summary object.

    Returns ``(payload, dropped)`` where ``dropped`` counts section bullets rejected
    by the numeric-fidelity guard.
    """
    when = _now(generated_at)
    sections = _parse_sections(md_text)
    key_metrics = _parse_key_metrics(sections.get("Key Metrics", []))
    metric_values = {label: value for label, value in key_metrics}

    system = (
        file_io.read_prompt("_global_rules.md")
        + file_io.business_rules_block(state)
        + "\n\n"
        + file_io.read_prompt("report_summary_payload_prompt.md")
    )
    user = (
        "SOURCE REPORT (report_summary.md) -- copy every figure verbatim:\n"
        + md_text
        + "\n\nAVAILABLE KEY-METRIC LABELS (use exactly; code injects the value):\n"
        + dumps(list(metric_values.keys()))
    )
    authored: _AuthoredSummary = _invoke(state, _AuthoredSummary, system, user)

    # metrics: LLM curates label + tone; code injects the value and drops any
    # label that is not verbatim in the source Key Metrics.
    metrics: List[Dict[str, Any]] = []
    for sel in authored.metrics:
        label = sel.label.strip()
        if label in metric_values:
            metrics.append({"label": label, "value": metric_values[label], "tone": sel.tone})
        if len(metrics) >= max_metrics:
            break
    if not metrics:  # never ship an empty tile row if the source had metrics
        metrics = [
            {"label": lbl, "value": val, "tone": "teal"} for lbl, val in key_metrics[:max_metrics]
        ]

    # sections: numeric-fidelity guard -- a bullet may only ship if every figure
    # it cites appears verbatim in the source markdown.
    src_figs = _figures(md_text)
    headline = _plain_business_text(authored.headline)
    if src_figs and not _figures(headline):
        raise ValueError("summary headline must include the primary source figure")
    if not _figures(headline) <= src_figs:
        raise ValueError("summary headline contains a figure not present in the source")
    out_sections: List[Dict[str, Any]] = []
    dropped = 0
    for s in authored.sections:
        kept = []
        for p in s.points:
            p = _plain_business_text(p)
            if not p:
                continue
            if _figures(p) <= src_figs:
                kept.append(p)
            else:
                dropped += 1
        if kept:
            out_sections.append({"heading": s.heading.strip(), "tone": s.tone, "points": kept})

    payload = {
        "title": title,
        "generatedAt": when.date().isoformat(),
        "headline": headline,
        "metrics": metrics,
        "sections": out_sections,
    }
    ReportSummaryPayload(**payload)  # strict validation (raises on mismatch)
    return payload, dropped


def generate_fresh_report_summary_payload(
    state: dict,
    *,
    title: str = "AI Summary",
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the latest-summary API object from the already validated draft.

    Fresh-summary mode intentionally makes no second LLM call here. Markdown,
    HTML, history, and this payload therefore stay on one source of truth.
    """
    summary = state.get("fresh_summary") or {}
    if not summary.get("heading"):
        raise ValueError("fresh_summary is missing a heading")
    metrics = []
    for metric in summary.get("metrics") or []:
        value = {
            "label": str(metric.get("label") or "").strip(),
            "value": str(metric.get("value") or "").strip(),
            "tone": metric.get("tone") or "teal",
        }
        if value["label"] and value["value"]:
            metrics.append(ReportMetric(**value).model_dump())
    sections = []
    for section in summary.get("sections") or []:
        value = {
            "heading": str(section.get("heading") or "").strip(),
            "tone": section.get("tone") or "teal",
            "points": [
                str(item).strip()
                for item in section.get("points") or []
                if str(item).strip()
            ],
        }
        if value["heading"] and value["points"]:
            sections.append(ReportSection(**value).model_dump())
    payload = {
        "title": title,
        "generatedAt": _now(generated_at).date().isoformat(),
        "headline": str(summary.get("heading")).strip(),
        "metrics": metrics,
        "sections": sections,
    }
    result = ReportSummaryPayload(**payload).model_dump(exclude_none=True)
    # R3 (coordinated UI/API release): expose the selected daily focus as an
    # additive, code-owned field. Off by default so the shipped contract is
    # unchanged until the UI opts in with summary_focus_public_metadata.
    cfg = state.get("config") or {}
    if cfg.get("summary_focus_public_metadata") or state.get("summary_focus_public_metadata"):
        focus = state.get("summary_selected_focus") or {}
        if focus.get("focus_key"):
            result["dailyFocus"] = {
                "segment": focus.get("segment") or None,
                "role": focus.get("dimension_role"),
                "lens": focus.get("lens"),
                "sentiment": focus.get("sentiment"),
            }
        # R4 (additive): the ordered focus portfolio. The singular dailyFocus
        # above stays as the first entry for backward compatibility.
        focuses = summary.get("dailyFocuses")
        if focuses:
            result["dailyFocuses"] = list(focuses)
            result.setdefault("dailyFocus", focuses[0])
    return result
