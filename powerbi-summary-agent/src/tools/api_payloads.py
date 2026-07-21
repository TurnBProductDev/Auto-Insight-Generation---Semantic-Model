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
  * summary metric values are injected from the parsed Key Metrics.
  * a numeric-fidelity guard drops any section bullet whose figures are not present
    verbatim in the source markdown.

The final payload is validated against strict pydantic schemas (``extra='forbid'``
plus ``Literal`` enums): if it does not match the contract, this raises rather than
shipping a malformed file. Only the summary + insights outputs are produced here;
the ``/kpi/alerts`` feed is a separate stream the agent does not generate.
"""

from __future__ import annotations

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
        ("bills", "Transactions"),
    ):
        i = d.find(key)
        if i >= 0:
            hits.setdefault(label, i)
    return min(hits, key=hits.get) if hits else "Performance"


def _signal_severity(sig: Dict[str, Any]) -> Severity:
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
    if "current_only" in cid or share is None or "concentration" in cid:
        return "info"
    if val < 0:
        return "critical" if abs(share) >= 150 else "warning"
    return "positive"


def _insight_stats(sig: Dict[str, Any], family: str) -> List[Dict[str, str]]:
    val = sig.get("impact_value")
    share = sig.get("impact_share")
    stats: List[Dict[str, str]] = [
        {"label": f"{family} impact", "value": _compact_number(val, signed=True)}
    ]
    if share is not None:
        stats.append({"label": "Share of change", "value": f"{share:+.1f}%"})
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
        d0 = decomp[0]
        stats.append({
            "label": "Volume / rate",
            "value": f"{_compact_number(d0.get('volume_effect'))} / {_compact_number(d0.get('rate_effect'))}",
        })
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
    return {
        "signal_id": sig.get("id"),
        "segment": sig.get("affected_segment"),
        "segment_members": sig.get("segment_members"),
        "measure_family": _signal_family(sig),
        "direction": "increase" if (val or 0) >= 0 else "decrease",
        "impact_display": _compact_number(val, signed=True),
        "share_of_change_pct": sig.get("impact_share"),
        "week_over_week_pct": rw.get("change_pct"),
        "recent_week": {k: rw.get(k) for k in
                        ("window_mode", "week_start", "week_end", "actual", "previous",
                         "expected", "facets")} if rw else None,
        "daily_incident": {
            "episode_start": sig.get("episode_start"), "episode_end": sig.get("episode_end"),
            "actual_total": sig.get("actual_total"), "expected_total": sig.get("expected_total"),
            "peak_z": sig.get("peak_z"),
        } if sig.get("episode_start") is not None else None,
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


def _assemble_kpi_card(idx: int, sig: Dict[str, Any], text: _KpiCardText, when: datetime) -> Dict[str, Any]:
    family = _signal_family(sig)
    val = sig.get("impact_value")
    share = sig.get("impact_share")
    category = text.category.strip() or ("Data Quality" if sig.get("kind") == "data_quality" else family)
    rw = sig.get("recent_week") or {}
    wow = rw.get("change_pct")
    if share is not None:
        delta, comparison = f"{abs(share):.1f}%", "share of total change"
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
    else:
        delta, comparison = "", "current period"
    card = {
        "id": idx,
        "severity": _signal_severity(sig),
        "category": category,
        "metric": sig.get("affected_segment") or "Segment",
        "value": _compact_number(val, signed=True),
        "delta": delta,
        "deltaDirection": "up" if (val or 0) >= 0 else "down",
        "description": text.description.strip(),
        "displayTime": when.strftime("%I:%M %p").lstrip("0"),
        "isoDate": when.date().isoformat(),
        "comparisonLabel": comparison,
        "insight": {
            "title": text.insight_title.strip(),
            "summary": text.insight_summary.strip(),
            "stats": _insight_stats(sig, family),
            "action": text.insight_action.strip(),
        },
    }
    return KpiCard(**card).model_dump()  # strict validation


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
    cards: List[Dict[str, Any]] = []
    for idx, sig in enumerate(signals, start=1):
        text = texts.get(sig.get("id"))
        if text is None:
            raise RuntimeError(f"LLM returned no card text for signal id {sig.get('id')!r}")
        cards.append(_assemble_kpi_card(idx, sig, text, when))
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
    out_sections: List[Dict[str, Any]] = []
    dropped = 0
    for s in authored.sections:
        kept = []
        for p in s.points:
            p = p.strip()
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
        "headline": authored.headline.strip(),
        "metrics": metrics,
        "sections": out_sections,
    }
    ReportSummaryPayload(**payload)  # strict validation (raises on mismatch)
    return payload, dropped
