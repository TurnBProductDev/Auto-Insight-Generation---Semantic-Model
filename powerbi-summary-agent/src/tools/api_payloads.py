"""LLM-authored MVC/FastAPI content payloads, with strict schema + fixed numbers.

The ASP.NET MVC app proxies to a FastAPI service that must return AI content in
two exact shapes:

  * ``/report/summary?format=json`` -> a JSON object
        {title, generatedAt, headline, metrics[], sections[]}
  * ``/kpi/insights`` -> a JSON array of cards
        {id, severity, category, metric, value, delta, deltaDirection,
         description, displayTime, isoDate, comparisonLabel, insight{...}}

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
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from . import file_io
from .llm import get_llm
from ..utils.json_utils import dumps

Severity = Literal["critical", "warning", "positive", "info"]
Tone = Literal["positive", "critical", "warning", "info", "teal"]
Direction = Literal["up", "down"]


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


class ReportMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    value: str
    tone: Tone


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


def _insight_stats(sig: Dict[str, Any], family: str) -> List[Dict[str, str]]:
    if _is_rate_signal(sig):
        return _rate_stats(sig, family)
    val = sig.get("impact_value")
    share = sig.get("impact_share")
    measure_label = {
        "Quantity": "Unit sales change",
        "Transactions": "Transaction change",
    }.get(family, f"{family} change")
    stats: List[Dict[str, str]] = [
        {"label": measure_label, "value": _compact_number(val, signed=True)}
    ]
    if share is not None:
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
        stats.append({"label": "Segments", "value": ", ".join(str(m) for m in members)})
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


def _assemble_kpi_card(
    idx: int,
    sig: Dict[str, Any],
    text: _KpiCardText,
    when: datetime,
    report_id: Optional[str] = None,
) -> Dict[str, Any]:
    family = _signal_family(sig)
    val = sig.get("impact_value")
    share = sig.get("impact_share")
    category = text.category.strip() or ("Data Quality" if sig.get("kind") == "data_quality" else family)
    rw = sig.get("recent_week") or {}
    wow = rw.get("change_pct")
    declared_comparison = str(sig.get("comparison_label") or "").strip()
    if declared_comparison:
        # A spine that is not year-on-year must name its own baseline. Without
        # this, a Target Tracker signal falls through to the share branch and is
        # published against "the prior period" - a comparison this dataset does
        # not contain at all (Non-negotiable 2).
        target_value = sig.get("target")
        if isinstance(val, (int, float)) and isinstance(target_value, (int, float)) and target_value:
            delta = f"{abs(val / abs(target_value) * 100.0):.1f}%"
        else:
            delta = ""
        comparison = declared_comparison
    elif isinstance(wow, (int, float)):
        if rw.get("window_mode") == "rolling":
            delta = f"{abs(wow):.1f}%"
            comparison = f"vs the prior 7 days (ending {rw.get('week_end')})"
        else:
            delta, comparison = f"{abs(wow):.1f}%", f"week over week (from {rw.get('week_start')})"
    elif sig.get("episode_start") is not None:
        expected = sig.get("expected_total")
        if isinstance(expected, (int, float)) and expected and isinstance(val, (int, float)):
            delta = f"{abs(val / abs(expected) * 100.0):.1f}%"
        else:
            delta = ""
        comparison = f"vs expected ({sig.get('episode_start')}..{sig.get('episode_end')})"
    elif _is_rate_signal(sig):
        growth = sig.get("reported_growth_pct")
        median = sig.get("peer_median_reported_pct")
        delta = f"{abs(growth):.1f}%" if isinstance(growth, (int, float)) else ""
        comparison = (f"vs peer median {median:+.1f}%"
                      if isinstance(median, (int, float)) else "relative to peers")
    elif isinstance(sig.get("current"), (int, float)) and isinstance(sig.get("prior"), (int, float)):
        period_pct = _period_change_pct(sig.get("current"), sig.get("prior"))
        delta = f"{abs(period_pct):.1f}%" if period_pct is not None else ""
        comparison = "vs the prior period"
    elif share is not None:
        delta, comparison, _ = _share_details(sig, family)
    else:
        delta, comparison = "", "current period"
    card = {
        "id": stable_card_id(report_id, sig.get("story_key"), idx) if report_id else idx,
        "reportId": report_id or None,
        "severity": _signal_severity(sig),
        "category": category,
        "metric": sig.get("affected_segment") or "Segment",
        "value": _compact_number(val, signed=True),
        "delta": delta,
        "deltaDirection": "up" if (val or 0) >= 0 else "down",
        "description": " ".join(
            part for part in (
                _main_change_sentence(sig, family),
                _sentence(_plain_business_text(text.description)),
            ) if part
        ),
        "displayTime": when.strftime("%I:%M %p").lstrip("0"),
        "isoDate": when.date().isoformat(),
        "comparisonLabel": comparison,
        "insight": {
            "title": _plain_business_text(text.insight_title),
            "summary": _sentence(_plain_business_text(text.insight_summary)),
            "stats": _insight_stats(sig, family),
            "action": _sentence(_plain_business_text(text.insight_action)),
        },
    }
    dumped = KpiCard(**card).model_dump()  # strict validation
    if dumped.get("reportId") is None:
        # Single-report mode must emit the exact key set the app renders today,
        # so the field is removed rather than published as an explicit null.
        dumped.pop("reportId", None)
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
    cards: List[Dict[str, Any]] = []
    for idx, sig in enumerate(signals, start=1):
        text = texts.get(sig.get("id"))
        if text is None:
            raise RuntimeError(f"LLM returned no card text for signal id {sig.get('id')!r}")
        cards.append(_assemble_kpi_card(idx, sig, text, when, report_id=report_id))
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
    result = ReportSummaryPayload(**payload).model_dump()
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
