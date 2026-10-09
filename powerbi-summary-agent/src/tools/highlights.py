"""Top Insights for the Web App's Home page: small facts that stood out.

The Web App's Home (Ver 4) shows four tiles under "What stood out this week":
a title, a figure, and one comparison each ("Chocolate sales, +34%, vs last
week"). Until this existed it filled them from the KPI feed's positive and
info findings. This module turns numbers each report flow has ALREADY
computed into those facts: no new query, no LLM call, nothing re-derived.

    Highlight          the published item (pydantic, extra fields forbidden,
                       absent fields left out rather than sent as null)
    highlight_id       stable across runs: the same fact keeps its id
    tone_for           the value's colour, from direction and goodDirection
    cap_per_report     a report's own best few, by rank
    from_daily_sales   the best store against its benchmark; a measure's
                       streak above its normal range
    from_target_tracker  what the month still needs; the best and the
                       lowest branch against their month-so-far target
    from_sales_yoy     the biggest riser and faller in the report's ranked
                       coverage, above the headline relevance floor

Published by ``ai_content_publisher.publish_run_highlights`` (each report's
publisher calls it after its own blobs, behind ``ai_content_highlights``) into
``ai-content/kpi/client/highlights.json``: a one-day window shared by every
report, merged on ``reportSlug``. The publisher stamps ``isoDate`` with the
day of the run, not the data's date, so reports whose data ends on different
days still share one day's list. The AI Bot serves it at GET /kpi/highlights;
the Web App keeps the items whose ``reportIds`` the user may open, best four
by rank. Contract: Web App ``docs/home-v4/PLAN.md`` section 5.2.

Not built yet: Stock Age and Inventory Management extractors (PLAN.md 7a.2).
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict

from .api_payloads import stable_card_id

Kind = Literal["riser", "faller", "leader", "laggard", "risk", "streak", "milestone"]
Tone = Literal["critical", "warning", "positive", "info"]
Direction = Literal["up", "down", "flat"]


class Highlight(BaseModel):
    """One Top Insights fact. Every field but the identity is optional, and
    an absent one is left out of the payload, never published as null."""

    model_config = ConfigDict(extra="forbid")

    id: int
    kind: Kind
    title: str
    value: str
    rawValue: Optional[float] = None
    valueType: Optional[str] = None
    detail: Optional[str] = None
    comparisonLabel: Optional[str] = None
    direction: Optional[Direction] = None
    goodDirection: Optional[Direction] = None
    tone: Tone = "info"
    rank: Optional[int] = None
    isoDate: Optional[str] = None
    reportIds: list[str]
    reportSlug: str
    reportName: Optional[str] = None


def highlight_id(report_slug: str, kind: str, subject: Any) -> int:
    """Stable id: the same kind of fact about the same subject, from the same
    report, keeps its id from run to run (so the app's render key holds).
    The one hashing implementation the KPI feed uses, under its own prefix."""
    return stable_card_id(f"highlight|{report_slug}", f"{kind}:{subject}", 0)


def tone_for(direction: Optional[str], good_direction: Optional[str]) -> Tone:
    """Positive when the movement is the good way for the measure, critical
    when it is the bad way; info when either side is unknown or flat."""
    if direction not in ("up", "down") or good_direction not in ("up", "down"):
        return "info"
    return "positive" if direction == good_direction else "critical"


def cap_per_report(items: Iterable[Highlight], limit: int) -> list[Highlight]:
    """A report's best ``limit`` facts by rank (missing rank last)."""
    ordered = sorted(items, key=lambda h: (h.rank if h.rank is not None else 10**6))
    return ordered[:max(0, int(limit))]


def dump(items: Iterable[Highlight]) -> list[dict]:
    """The payload shape: absent fields left out."""
    return [item.model_dump(exclude_none=True) for item in items]


# ---------------------------------------------------------------------------
# Daily Sales
# ---------------------------------------------------------------------------

def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _share(value: float) -> str:
    return f"{value:.1f}%"


def _num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _days(count: int) -> str:
    return "1 day" if count == 1 else f"{count} days"


def from_daily_sales(page: dict, report_ids: list[str], *, report_slug: Optional[str] = None,
                     report_name: Optional[str] = None) -> list[Highlight]:
    """Facts from the Daily Sales page the report was built from.

    Leader: the store furthest ABOVE its own Net Sales benchmark today, as a
    share of that benchmark (a big store's absolute lead must not outrank a
    small store's proportionally larger one). Only a store actually above its
    benchmark qualifies: "top store" on a day every store missed would be a
    least-bad, not a highlight.

    Streak: a measure above its normal range for RUN or more days running,
    read from the scorecard's own facts (``scorecard_lines.daily_sales_facts``)
    so the tile and the report page state the same run.

    ``report_slug`` must be the slug the caller publishes under (the config's
    ``report_id``): the shared list replaces a report's items by it.
    """
    from ..domains.sales.daily_sales_dashboard import money
    from ..domains.sales.scorecard_lines import MEASURES, daily_sales_facts

    slug = str(report_slug or page.get("report_id") or "daily_sales")
    name = str(report_name or page.get("report_name") or "Daily Sales")
    currency = str(page.get("currency") or "")
    common = {"reportIds": list(report_ids), "reportSlug": slug, "reportName": name}
    items: list[Highlight] = []

    # The raw figures per store are the page's ``store_bundles``; its
    # ``stores`` rows hold the same figures already formatted for display.
    best = None
    for store in page.get("store_bundles") or []:
        sales = store.get("net_sales") or {}
        actual, benchmark = _num(sales.get("actual")), _num(sales.get("p50"))
        if actual is None or not benchmark or benchmark <= 0:
            continue
        lead = (actual - benchmark) / benchmark * 100.0
        if lead > 0 and (best is None or lead > best[0]):
            best = (lead, str(store.get("name") or "").strip(), actual)
    if best and best[1]:
        lead, store_name, actual = best
        items.append(Highlight(
            id=highlight_id(slug, "leader", "net_sales"),
            kind="leader", title="Top store", value=store_name,
            detail=money(actual, currency), rawValue=round(lead, 2), valueType="percent",
            comparisonLabel=f"best against its benchmark, {_pct(lead)}",
            direction="up", goodDirection="up", tone="positive", rank=1, **common))

    labels = dict(MEASURES)
    for fact in daily_sales_facts(page):
        if fact.get("kind") != "run_above":
            continue
        run = int((fact.get("numbers") or ["0"])[0])
        measure = labels.get(fact.get("key"), str(fact.get("measure") or ""))
        items.append(Highlight(
            id=highlight_id(slug, "streak", fact.get("key")),
            kind="streak", title=f"{measure} streak", value=f"{run} days",
            rawValue=float(run), valueType="count",
            comparisonLabel="above its normal range",
            direction="up", goodDirection="up", tone="positive",
            rank=2, **common))
    return items


# ---------------------------------------------------------------------------
# Target Tracker
# ---------------------------------------------------------------------------

def from_target_tracker(model: dict, report_ids: list[str], *, report_slug: Optional[str] = None,
                        report_name: Optional[str] = None) -> list[Highlight]:
    """Facts from the Target Tracker model the report was built from.

    Month target (rank 1), read from the same ``month_close`` the report's
    "With N days left, reaching the month target needs ..." paragraph states:
    the full month's target already reached is a milestone; otherwise, with
    days left, the share of their own plan those days must sell. At or under
    100% the month lands on target even a little under plan (a milestone);
    over 100% they must beat their plan (a risk: critical when the month so far
    is in the report's Below-target band, warning in Watch). A finished month
    gives nothing: the report says so and there is nothing left to change.

    Top branch (rank 2): the best month-so-far share of target, only when it is
    on target (a "top branch" every branch is behind would be a least-bad).
    Lowest branch (rank 3): the worst, only in the Below-target band. Both need
    two branches or more; with one there is no comparison.
    """
    from ..domains.sales.target_tracker import BANDS

    on_target, watch = BANDS[0][0], BANDS[1][0]
    slug = str(report_slug or model.get("report_id") or "target_tracker")
    name = str(report_name or model.get("report_name") or "Target Tracker")
    common = {"reportIds": list(report_ids), "reportSlug": slug, "reportName": name}
    items: list[Highlight] = []

    mtd = (model.get("periods") or {}).get("mtd") or {}
    close = model.get("month_close") or {}
    full, actual = _num(model.get("month_full_target")), _num(mtd.get("actual"))
    needed, needed_pct = _num(close.get("needed")), _num(close.get("needed_vs_target"))
    remaining, attainment = _num(close.get("remaining_target")), _num(mtd.get("attainment"))
    days_left = int(model.get("days_in_month") or 0) - int(model.get("days_elapsed") or 0)
    if full and full > 0 and actual is not None and needed is not None and needed <= 0:
        share = actual / full * 100.0
        items.append(Highlight(
            id=highlight_id(slug, "milestone", "month_target"),
            kind="milestone", title="Month target reached", value=_share(share),
            rawValue=round(share, 2), valueType="percent",
            comparisonLabel=(f"of the full month, {_days(days_left)} left" if days_left > 0
                             else "of the full month"),
            tone="positive", rank=1, **common))
    elif days_left > 0 and remaining and remaining > 0 and needed_pct is not None:
        behind = needed_pct > on_target
        items.append(Highlight(
            id=highlight_id(slug, "risk" if behind else "milestone", "month_target"),
            kind="risk" if behind else "milestone", title="Month target",
            value=_share(needed_pct), rawValue=round(needed_pct, 2), valueType="percent",
            comparisonLabel=f"of plan needed on the {_days(days_left)} left",
            tone=("positive" if not behind
                  else "warning" if attainment is not None and attainment >= watch
                  else "critical"),
            rank=1, **common))

    measured = []
    for branch in model.get("branches") or []:
        branch_name = str(branch.get("name") or "").strip()
        share = _num((branch.get("mtd") or {}).get("attainment"))
        if branch_name and branch_name != "Unassigned" and share is not None:
            measured.append((share, branch_name))
    if len(measured) >= 2:
        best, worst = max(measured), min(measured)
        if best[0] >= on_target:
            items.append(Highlight(
                id=highlight_id(slug, "leader", "branch_month"),
                kind="leader", title="Top branch", value=best[1], detail=_share(best[0]),
                rawValue=round(best[0], 2), valueType="percent",
                comparisonLabel="of its month target so far",
                direction="up", goodDirection="up", tone="positive", rank=2, **common))
        if worst[0] < watch:
            items.append(Highlight(
                id=highlight_id(slug, "laggard", "branch_month"),
                kind="laggard", title="Lowest branch", value=worst[1], detail=_share(worst[0]),
                rawValue=round(worst[0], 2), valueType="percent",
                comparisonLabel="of its month target so far",
                direction="down", goodDirection="up", tone="critical", rank=3, **common))
    return items


# ---------------------------------------------------------------------------
# Sales vs Previous Year
# ---------------------------------------------------------------------------

#: The plain word for a coverage family's figure, after the role ("store sales").
_FAMILY_WORDS = {"revenue": "sales", "sales": "sales", "quantity": "units", "units": "units"}


def from_sales_yoy(coverage: dict, report_ids: list[str], *, report_slug: Optional[str] = None,
                   report_name: Optional[str] = None) -> list[Highlight]:
    """The biggest riser and faller in the report's own ranked coverage.

    Same ranking and same relevance floor as the report's headline
    (``summary_coverage.top_movers``): a move too small to register against
    the whole business cannot reach Home on the strength of its percentage.
    Unlike the headline there is no fallback when nothing clears the floor: a
    quiet period has no highlight. Steady and current-only members never
    qualify (``top_movers`` already leaves them out).
    """
    from . import summary_coverage

    cov = coverage or {}
    slug = str(report_slug or "sales_yoy")
    name = str(report_name or "Sales vs Previous Year")
    common = {"reportIds": list(report_ids), "reportSlug": slug, "reportName": name}
    floor = _num((cov.get("thresholds") or {}).get("headline_min_impact_pct"))
    floor = summary_coverage.HEADLINE_MIN_IMPACT_PCT if floor is None else floor
    ranked = [row for row in summary_coverage.top_movers(cov, limit=10**6, min_impact_pct=floor)
              if (_num(row.get("global_impact_pct")) or 0.0) >= floor
              and _num(row.get("change_pct")) is not None
              and str(row.get("member") or "").strip()]
    word = _FAMILY_WORDS.get(str(cov.get("metric_family") or "").strip().lower(), "")

    items: list[Highlight] = []
    for rank, (kind, direction) in enumerate((("riser", "up"), ("faller", "down")), start=1):
        row = next((r for r in ranked if r.get("direction") == direction), None)
        if row is None:
            continue
        member = str(row["member"]).strip()
        role = str(row.get("role") or "").replace("_", " ").strip()
        change = float(row["change_pct"])
        label = " ".join(part for part in (role, word) if part)
        items.append(Highlight(
            id=highlight_id(slug, kind, f"{role}:{member}"),
            kind=kind, title=member, value=_pct(change),
            rawValue=round(change, 2), valueType="percent",
            comparisonLabel=f"{label} vs last year" if label else "vs last year",
            direction=direction, goodDirection="up", tone=tone_for(direction, "up"),
            rank=rank, **common))
    return items
