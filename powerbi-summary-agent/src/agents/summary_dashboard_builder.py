"""Build the interactive summary dashboard page model (R6).

Gated behind ``summary_r6_enabled`` (code default **false**), so a config without
the key reproduces the R1-R5 summary byte-for-byte. Summary-only: imports no
``insight_*`` module and never reads insight state.

What this node does, in order:

1. resolves which scanned level is the *entity* level (the estate) and which is
   the *exposure* level (the granular one used for the declining-areas signals);
2. optionally spends up to two bounded REST calls, both non-fatal and budgeted:
   a per-entity three-lever scan, so each entity card can show transactions /
   basket size / price rather than revenue alone; and one scan by period x entity,
   which is what makes the single-period view a real view rather than a top-line
   reading - its own six measures, its own three-lever split, its own
   contributions, and its own estate-wide comparator check;
3. assembles the primary view, plus a latest-complete-period view (from the
   period scan when it succeeded, else derived from the already-scanned overall
   trend at zero extra REST cost, holding no borrowed breakdown rows);
4. optionally asks the LLM for the prose inside code-owned slots, validates it
   deterministically, and falls back to the grounded deterministic draft;
5. writes ``summary_dashboard.json``.

The HTML itself is written by ``fresh_summary_validator`` so that both summary
artifacts are produced at the same, single point in the branch.
"""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..tools import file_io, summary_dashboard, summary_levers
from ..tools import summary_focus_queries as q
from ..tools.llm import get_llm
from ..tools.summary_validation import dashboard_rules
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger
from .summary_focus_evidence import (
    _alias,
    _families,
    _run_query,
    _select_trend_dimension,
)

# Families the three-lever split needs. Anything else the profile exposes is not
# scanned here - this call has to stay a single bounded query.
_LEVER_FAMILIES = ("revenue", "quantity", "transactions")


class DashboardHero(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(description="The period's result in one sentence, with its exact figure")
    narrative: str = Field(
        description=(
            "The result read two ways (how many x worth how much each) and explained by "
            "the three levers underneath, using only supplied figures"
        )
    )


class DashboardEntityStory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    member: str = Field(description="Exact entity name as supplied")
    story: str = Field(
        description=(
            "What is distinctive about THIS entity, with its figures. Never the same "
            "sentence as another entity with the name changed."
        )
    )


class DashboardAreaStory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    focus_key: str = Field(description="Exact focus_key as supplied")
    headline: str = Field(description="This area's result in one sentence, with its exact figure")
    connect: str = Field(
        description="How this area's measure changes built its overall result"
    )


class DashboardDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hero: DashboardHero
    entities: List[DashboardEntityStory] = Field(default_factory=list)
    areas: List[DashboardAreaStory] = Field(default_factory=list)


def _levels(coverage: dict) -> list[dict]:
    return list((coverage or {}).get("levels") or [])


def _resolve_entity_role(state: dict, coverage: dict) -> str | None:
    """The level that represents the estate (stores/branches), if one was scanned.

    Preference order: an explicit config choice, then a coverage-only role such
    as ``store`` (orthogonal to the merchandise hierarchy, which is exactly what
    the entity layer wants), then the broadest merchandise level as a fallback so
    the layer is never empty on a model without a store dimension.
    """
    levels = _levels(coverage)
    if not levels:
        return None
    available = {str(level.get("role")) for level in levels}
    configured = str(state.get("summary_dashboard_entity_role") or "").strip()
    if configured:
        return configured if configured in available else None
    for level in levels:
        if level.get("coverage_only"):
            return str(level.get("role"))
    broadest = min(levels, key=lambda level: (level.get("level") is None,
                                              level.get("level") or 0))
    return str(broadest.get("role"))


def _resolve_exposure_role(state: dict, coverage: dict, entity_role: str | None) -> str | None:
    """The granular level used for the declining-areas / at-risk-revenue signals."""
    levels = [
        level for level in _levels(coverage)
        if str(level.get("role")) != str(entity_role)
    ] or _levels(coverage)
    if not levels:
        return None
    configured = str(state.get("summary_dashboard_exposure_role") or "").strip()
    available = {str(level.get("role")) for level in levels}
    if configured:
        return configured if configured in available else None
    deepest = max(levels, key=lambda level: (level.get("level") is None,
                                             level.get("level") or 0))
    return str(deepest.get("role"))


def _lever_scan(state: dict, coverage: dict, entity_role: str | None,
                log: RunLogger) -> dict:
    """One bounded per-entity scan of revenue, units and bills together.

    Without this the entity cards can only report revenue; with it each card
    carries its own three-lever read. Deliberately a single query: the levers are
    a fixed set of measures over one grouping, so there is nothing to iterate.
    Every failure path returns ``{}`` and the cards degrade with a stated reason.
    """
    if not entity_role or not state.get("summary_dashboard_entity_levers", True):
        return {}
    role_info = ((state.get("summary_focus_universe") or {}).get("roles") or {}).get(entity_role)
    group_ref = (role_info or {}).get("group_ref")
    if not group_ref:
        return {}

    families = {
        family["family"]: family
        for family in _families(state.get("semantic_model_profile") or {})
        if family["family"] in _LEVER_FAMILIES
    }
    if len(families) < len(_LEVER_FAMILIES):
        log.info(
            "Dashboard entity levers skipped: the model exposes "
            f"{sorted(families)} of {sorted(_LEVER_FAMILIES)}."
        )
        return {}

    measures: list[tuple[str, str]] = []
    aliases: dict[str, dict[str, str]] = {}
    for family in _LEVER_FAMILIES:
        bundle = families[family]
        phase_map: dict[str, str] = {}
        # ``prior`` is preferred, but a model that publishes only current and
        # change is fine: ``entity_levers`` reconstructs prior arithmetically.
        # Requiring a named prior measure would disable the three-lever read on
        # models that simply do not have one (the working model's bills family).
        for phase in ("current", "prior", "change"):
            measure = (bundle.get("phases") or {}).get(phase)
            if not measure:
                continue
            alias = _alias(family, phase)
            measures.append((alias, measure))
            phase_map[phase] = alias
        if "current" not in phase_map or not ({"prior", "change"} & set(phase_map)):
            log.info(
                f"Dashboard entity levers skipped: {family} exposes neither a prior "
                "nor a change measure."
            )
            return {}
        aliases[family] = phase_map

    scope = (role_info or {}).get("scope") or {}
    filters = list((role_info or {}).get("filters") or [])
    if not filters:
        entity = (state.get("semantic_model_profile") or {}).get("entity_dimension") or {}
        population = [
            str(item) for item in
            (state.get("resolved_entity_scope") or {}).get("active_comparable_population") or []
        ]
        if entity.get("reference") and population:
            filters = [q.treatas(entity["reference"], population)]

    query = q.breakdown(
        "summary_dashboard_entity_levers",
        f"Three-lever read per {entity_role}",
        group_ref,
        filters,
        measures,
        measures[0][1],
        int(state.get("summary_dashboard_entity_rows", 40)),
        scope,
    )
    budget = {"used": 0, "max": max(0, int(state.get("summary_dashboard_max_queries", 2)))}
    result = _run_query(state, query, budget, {})
    if result.get("status") != "success" or not result.get("rows"):
        # Log why, not just that: a scope rejection and an exhausted budget need
        # different fixes, and this scan is silent by design otherwise.
        detail = "; ".join(str(reason) for reason in result.get("reasons") or [])[:200]
        log.info(
            f"Dashboard entity levers unavailable ({result.get('status')})"
            + (f": {detail}" if detail else "")
            + "."
        )
        return {}

    column = str((role_info or {}).get("column") or "")
    rows: dict[str, dict] = {}
    for row in result["rows"]:
        member = row.get(column)
        if member is None:
            # Fall back to the only non-alias key, so a differently-qualified
            # column name does not silently drop every row.
            spare = [
                key for key in row
                if key not in {alias for alias, _ in measures} and not str(key).startswith("__")
            ]
            member = row.get(spare[0]) if spare else None
        if member is None:
            continue
        levers = summary_levers.entity_levers(row, aliases)
        if levers:
            rows[str(member)] = levers
    log.info(f"Dashboard entity levers resolved for {len(rows)} {entity_role}(s).")
    return rows


def _period_scan(state: dict, entity_role: str | None, package: dict,
                 log: RunLogger) -> dict | None:
    """One bounded scan of every lever measure by period AND by entity.

    This is what turns the latest-complete-period view from a top-line reading
    into a full one: with it that view gets its own six measures, its own
    three-lever split, its own per-entity contributions, and - the reason it
    matters most - its own estate-wide comparator check, which needs *that
    period's* member movements and cannot be borrowed from the wider span.

    One query, because grouping by period and member together returns both, and
    the per-period overall totals ride along as diagnostics. Non-fatal: without it
    the narrower view degrades to the honest top-line-only form.
    """
    if not state.get("summary_dashboard_period_scan", True) or not entity_role:
        return None
    profile = state.get("semantic_model_profile") or {}
    role_info = ((state.get("summary_focus_universe") or {}).get("roles") or {}).get(entity_role)
    group_ref = (role_info or {}).get("group_ref")
    if not group_ref:
        return None

    # The time axis is the one the summary-owned overall trend already validated,
    # so this scan cannot introduce a batch/load date the trend gate rejected.
    trend = (package or {}).get("trend") or {}
    axis_column = trend.get("dimension")
    grain = str(trend.get("grain") or "period")
    trend_dim, _note = _select_trend_dimension(state, profile, (_families(profile) or [{}])[0])
    axis_ref = (trend_dim or {}).get("reference")
    if not (axis_column and axis_ref):
        log.info("Dashboard period scan skipped: no validated time axis.")
        return None

    families = {
        family["family"]: family
        for family in _families(profile) if family["family"] in _LEVER_FAMILIES
    }
    if "revenue" not in families:
        return None
    measures: list[tuple[str, str]] = []
    aliases: dict[str, dict[str, str]] = {}
    # Revenue first: it is the primary family, and the reader uses the first
    # family for member values and completeness.
    for family in ("revenue",) + tuple(f for f in _LEVER_FAMILIES if f != "revenue"):
        bundle = families.get(family)
        if not bundle:
            continue
        phase_map: dict[str, str] = {}
        for phase in ("current", "prior", "change"):
            measure = (bundle.get("phases") or {}).get(phase)
            if not measure:
                continue
            alias = _alias(family, phase)
            measures.append((alias, measure))
            phase_map[phase] = alias
        if "current" in phase_map and ({"prior", "change"} & set(phase_map)):
            aliases[family] = phase_map

    entity = profile.get("entity_dimension") or {}
    population = [
        str(item) for item in
        (state.get("resolved_entity_scope") or {}).get("active_comparable_population") or []
    ]
    filters = [q.treatas(entity["reference"], population)] if (
        entity.get("reference") and population) else []

    query = q.period_breakdown(
        "summary_dashboard_period_breakdown",
        f"Every lever measure by {grain} and {entity_role}",
        axis_ref,
        group_ref,
        filters,
        measures,
        int(state.get("summary_dashboard_period_scan_rows", 400)),
        (role_info or {}).get("scope") or {},
    )
    budget = {"used": 0, "max": max(0, int(state.get("summary_dashboard_max_queries", 2)))}
    result = _run_query(state, query, budget, {})
    if result.get("status") != "success" or not result.get("rows"):
        detail = "; ".join(str(reason) for reason in result.get("reasons") or [])[:200]
        log.info(
            f"Dashboard period scan unavailable ({result.get('status')})"
            + (f": {detail}" if detail else "") + "."
        )
        return None

    member_column = str((role_info or {}).get("column") or entity_role)
    scan = summary_dashboard.read_period_scan(
        result["rows"], axis_column, member_column, aliases, grain=grain,
        tolerance_pct=float(state.get("summary_focus_reconciliation_tolerance_pct", 2)),
    )
    periods = scan.get("periods") or {}
    log.info(
        "Dashboard period scan: %d %s(s), %d with a reconciled %s breakdown, "
        "%d measure family(ies)."
        % (len(periods), grain,
           sum(1 for bucket in periods.values() if bucket.get("reconciled")),
           entity_role, len(aliases))
    )
    return scan if periods else None


def _narratives(state: dict, page_views: list[dict], log: RunLogger) -> dict:
    """Ask the LLM for the prose inside the code-owned slots, per view.

    Validation is per view against that view's own model, so a figure from the
    period-to-date view cannot leak into the latest-period view.
    """
    if not state.get("summary_llm_authoring_enabled", True):
        return {}
    rules = (
        file_io.read_prompt("_global_rules.md")
        + file_io.business_rules_block(state)
        + file_io.summary_business_rules_block(state)
    )
    task = file_io.read_prompt("summary_dashboard_prompt.md")
    out: dict = {}
    for view in page_views:
        context = _authoring_context(view)
        messages = [
            {"role": "system", "content": rules + "\n\n" + task},
            {"role": "user", "content": "DASHBOARD VIEW MODEL:\n" + dumps(context)},
        ]
        authored = None
        for attempt in range(3):
            try:
                llm = get_llm(state, structured_schema=DashboardDraft)
                response = llm.invoke(messages)
                draft = response.model_dump() if hasattr(response, "model_dump") else dict(response)
            except Exception as exc:  # noqa: BLE001 - fall back to deterministic prose
                log.error(
                    f"Dashboard authoring call failed for view {view.get('key')} "
                    f"({type(exc).__name__}: {exc})."
                )
                break
            errors = dashboard_rules(draft, view)
            if not errors:
                authored = draft
                break
            messages.append({"role": "assistant", "content": dumps(draft)})
            messages.append({
                "role": "user",
                "content": (
                    "The draft failed validation. Rewrite it and return the schema again.\n"
                    "Issues:\n- " + "\n- ".join(errors[:12])
                    + "\n\nQuote only figures that appear in the view model above, and give "
                      "every entity that moved materially its own distinct story."
                ),
            })
            if attempt == 2:
                log.error(
                    f"Dashboard authoring for view {view.get('key')} did not validate; "
                    "using the deterministic draft."
                )
        if authored:
            out[str(view.get("key"))] = {
                "hero": authored.get("hero") or {},
                "entities": {
                    str(item.get("member")): item
                    for item in authored.get("entities") or []
                },
                "areas": {
                    str(item.get("focus_key")): item
                    for item in authored.get("areas") or []
                },
            }
    return out


def _authoring_context(view: dict) -> dict:
    """Only what the prose needs - the figures, states and slot names.

    Full coverage tables are excluded deliberately: they are code-owned, never
    narrated, and shipping thousands of rows into the prompt buys nothing.
    """
    layers = view.get("layers") or {}
    entities = layers.get("entities") or {}
    # Display strings for every headline figure, so the draft has a correctly
    # rounded token to copy rather than a raw float to transcribe.
    display = {
        key: {
            "value": card.get("value_display"),
            "change": card.get("change_display"),
            "verdict": (card.get("rag") or {}).get("label"),
        }
        for key, card in (
            (str(item.get("key")), item) for item in view.get("kpis") or []
        )
    }
    return {
        "view": view.get("key"),
        "label": view.get("label"),
        "period": view.get("period"),
        "quote_these_display_values": display,
        "measures": view.get("measures"),
        "three_lever_bridge": view.get("bridge"),
        "lever_state": (view.get("hero") or {}).get("state"),
        "calendar": {
            "comparator_effect": (view.get("calendar") or {}).get("comparator_effect"),
            "headline": (view.get("calendar") or {}).get("headline"),
            "exceptions": (view.get("calendar") or {}).get("exceptions"),
        },
        "signals": view.get("signals"),
        "entity_role": entities.get("role"),
        "entity_contributions": (entities.get("contributions") or {}).get("items"),
        "entities": [
            {
                "member": card.get("member"),
                "rank": card.get("rank"),
                "severity": card.get("severity"),
                "change_pct": card.get("change_pct"),
                "change": card.get("change"),
                "current": card.get("current"),
                "business_share_pct": card.get("business_share_pct"),
                "vs_peer_median_pts": card.get("vs_peer_median_pts"),
                "contribution_pts": card.get("contribution_pts"),
                "levers": card.get("levers"),
                "lever_state": card.get("state"),
                "deterministic_story": card.get("story"),
            }
            for card in entities.get("cards") or []
        ],
        "areas": [
            {
                "focus_key": entry.get("focus_key"),
                "segment": entry.get("segment"),
                "role": entry.get("role"),
                "sentiment": entry.get("sentiment"),
                "facts": entry.get("facts"),
            }
            for entry in (layers.get("areas") or {}).get("entries") or []
        ],
        "limitations": view.get("limitations"),
    }


def _view_inputs(state: dict) -> list[dict]:
    """The ordered time views this run can honestly produce.

    The primary view is whatever the resolver settled on. A second, narrower
    "latest complete period" view is added only when the already-scanned overall
    trend can supply it - it costs no extra query, and it is what makes the
    calendar/comparator read possible at all.
    """
    package = state.get("summary_overall_performance") or {}
    period = state.get("summary_period_context") or {}
    trend = package.get("trend")

    # Name the span the scanned measures actually cover. The period context's
    # ``grain`` is the granularity of the time axis, NOT the length of the
    # reporting period: a month-grain scan spanning seven months is a
    # year-to-date figure, and calling that view "Month to date" tells the reader
    # the headline covers one month when it covers seven.
    span = summary_dashboard.span_label(trend, period)
    views = [{
        "key": "primary",
        "label": span or "Full period",
        "families_override": None,
        "trend_override": None,
        "scan_label_hint": span or "the full period",
    }]
    if not state.get("summary_dashboard_period_view", True):
        return views
    # The month is chosen by calendar completeness against data_as_of, never taken
    # from period_anchor: at day grain the anchor is a date, and its month is the
    # in-progress one. Both the label and the period-scan scope key come from the
    # row actually selected, so they cannot disagree with each other.
    row = summary_dashboard.latest_complete_period(trend, period)
    families = summary_dashboard.families_from_trend_row(row, trend)
    if families and row:
        period_key = None
        axis = trend.get("dimension") if trend else None
        if axis is not None and row.get(axis) is not None:
            try:
                period_key = int(float(row[axis]))
            except (TypeError, ValueError):
                period_key = None
        views.append({
            "key": "latest_period",
            "label": summary_dashboard.period_name(period, period_key)
                     or "Latest complete period",
            "families_override": families,
            "trend_override": trend,
            "scan_label_hint": span or "the full period",
            "period_key": period_key,
        })
    return views


def run(state: dict) -> dict:
    log = RunLogger(state)
    if not state.get("summary_r6_enabled", False):
        return {**log.updates()}

    coverage = state.get("summary_coverage") or {}
    package = state.get("summary_overall_performance") or {}
    period = state.get("summary_period_context") or {}
    config = state.get("config") or {}
    if not _levels(coverage) and package.get("status") != "ok":
        log.error("Dashboard skipped: neither coverage levels nor overall performance were available.")
        return {**log.updates()}

    entity_role = _resolve_entity_role(state, coverage)
    exposure_role = _resolve_exposure_role(state, coverage, entity_role)
    lever_rows = {}
    try:
        lever_rows = _lever_scan(state, coverage, entity_role, log)
    except Exception as exc:  # noqa: BLE001 - levers are best-effort, never fatal
        log.error(f"Dashboard entity lever scan skipped ({type(exc).__name__}: {exc}).")
    period_scan = None
    try:
        period_scan = _period_scan(state, entity_role, package, log)
    except Exception as exc:  # noqa: BLE001 - best-effort, never fatal
        log.error(f"Dashboard period scan skipped ({type(exc).__name__}: {exc}).")

    # Merged settings: dashboard knobs live in state, thresholds in config.
    settings = {**config, **{
        key: value for key, value in state.items()
        if str(key).startswith(("summary_dashboard_", "summary_calendar_", "summary_rag_"))
    }}
    focuses = list(state.get("summary_selected_focuses") or [])
    evidence_by_key = state.get("summary_focus_evidence_by_key") or {}

    specs = _view_inputs(state)

    def make(spec: dict, narratives: dict | None = None,
             reference_members: list[dict] | None = None) -> dict:
        # A narrower view is given its OWN period-scoped coverage when the period
        # scan supplied one, and its own families from that period's totals - so
        # its contributions, cards and comparator check all describe that period.
        scoped_coverage = None
        scoped_levers = None
        families_override = spec["families_override"]
        period_key = spec.get("period_key")
        if period_scan is not None and period_key is not None:
            scoped_coverage = summary_dashboard.period_coverage(
                period_scan, period_key, str(entity_role or "area"),
                material_change_pct=float(
                    settings.get("summary_coverage_material_change_pct", 10)),
                material_share_pct=float(
                    settings.get("summary_coverage_material_share_pct", 5)),
            )
            bucket = (period_scan.get("periods") or {}).get(period_key) or {}
            # Only adopt the scan's own families when it carries a full set; a
            # partial set would silently drop a KPI the trend could still supply.
            if bucket.get("families"):
                families_override = bucket["families"]
            # And this period's own per-entity levers, never the whole span's.
            scoped_levers = bucket.get("lever_rows") or None
            if scoped_coverage and not scoped_coverage.get("reconciled"):
                # Rows that do not add up to the period's own total cannot support
                # contributions, so the view falls back to top-line only.
                scoped_coverage = None
        return summary_dashboard.build_view(
            spec["key"], spec["label"], package, coverage, period, settings,
            entity_role=entity_role, exposure_role=exposure_role,
            focuses=focuses, evidence_by_key=evidence_by_key,
            narratives=narratives,
            lever_rows=scoped_levers if scoped_coverage else lever_rows,
            reference_members=reference_members,
            families_override=families_override,
            trend_override=spec["trend_override"],
            scan_label_hint=spec.get("scan_label_hint"),
            coverage_override=scoped_coverage,
        )

    # Pass 1: deterministic views. These are complete and publishable on their own.
    # The wider view is built first because it is the reference for "did this
    # weakness predate the shift" - the test that separates a calendar artefact
    # from a real problem in the narrower view.
    views: list[dict] = [make(specs[0])]
    reference_members = [
        {"member": card.get("member"), "change_pct": card.get("change_pct")}
        for card in ((views[0].get("layers") or {}).get("entities") or {}).get("cards") or []
    ]
    for spec in specs[1:]:
        views.append(make(spec, reference_members=reference_members))

    narratives = {}
    try:
        narratives = _narratives(state, views, log)
    except Exception as exc:  # noqa: BLE001 - deterministic prose still delivers
        log.error(f"Dashboard authoring skipped ({type(exc).__name__}: {exc}).")

    # Pass 2: rebuild only the views the LLM actually authored, so authored prose
    # lands in the same slots the deterministic pass validated.
    if narratives:
        by_key = {spec["key"]: spec for spec in specs}
        rebuilt: list[dict] = []
        for index, view in enumerate(views):
            authored = narratives.get(str(view.get("key")))
            spec = by_key.get(str(view.get("key")))
            if not authored or not spec:
                rebuilt.append(view)
                continue
            rebuilt.append(make(
                spec, narratives=authored,
                reference_members=reference_members if index else None,
            ))
        views = rebuilt

    page = summary_dashboard.build(
        views,
        title=str(config.get("api_summary_title") or state.get("report_name") or "AI Insights Summary"),
        subtitle=str((state.get("report_understanding") or {}).get("business_context") or "") or None,
        config=settings,
    )
    page["authoring_mode"] = "llm" if narratives else "deterministic"
    page["period_scan"] = bool(period_scan)
    page["entity_role"] = entity_role
    page["exposure_role"] = exposure_role
    file_io.write_json(state, "summary_dashboard.json", page)
    log.info(
        "Dashboard page built: status=%s views=%s entity_role=%s levers=%s mode=%s."
        % (page.get("status"), [view.get("key") for view in page.get("views") or []],
           entity_role, "yes" if lever_rows else "no", page["authoring_mode"])
    )
    return {"summary_dashboard": page, **log.updates()}
