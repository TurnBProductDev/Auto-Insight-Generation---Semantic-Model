"""The live probe: what does this semantic model actually expose?

Several config keys cannot be chosen before the model has been inspected, and a
wrong value degrades output silently rather than failing loudly - which roles
exist, whether the entity dimension resolves, whether a genuine business date
axis exists, which entities form the comparable population. So onboarding is a
wizard, not a settings page, and this is the screen the wizard is built around.

It runs only the pre-fork nodes plus the focus-universe scan:

    read_metadata -> semantic_profile -> baseline_scope -> summary_focus_universe

into a temporary output and memory location, with no LLM call, no production
memory or history write and no published output, so it is safe to run
repeatedly from a UI. Cost is roughly 10-20 REST calls and 30-120 seconds.

The CLI (``scripts/probe_summary_universe.py``) and the API both call
:func:`run_probe`. Nothing shells out to the script - subprocess invocation
makes progress streaming and error handling markedly worse.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .. import config_schema

PROJECT_ROOT = Path(__file__).resolve().parents[2]

LogSink = Callable[[str], None]


@dataclass
class ProbeResult:
    """Everything the wizard needs to fill in the probe-driven keys."""

    status: str = "pending"  # ok | degraded | failed
    reason: str = ""
    #: True when the shared diagnostic portfolio ran, so the time-axis verdicts
    #: and data_as_of are measured rather than simply not evaluated.
    deep: bool = False
    started_at: str = ""
    finished_at: str = ""
    duration_seconds: float = 0.0
    model: dict = field(default_factory=dict)
    time_axes: list = field(default_factory=list)
    freshness: dict = field(default_factory=dict)
    entities: dict = field(default_factory=dict)
    roles: dict = field(default_factory=dict)
    universe: dict = field(default_factory=dict)
    coverage: dict = field(default_factory=dict)
    #: Config keys the probe can answer, each with the evidence behind it.
    recommendations: list = field(default_factory=list)
    #: Hard stops. A deployment must be refused while any of these stand.
    blocking: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    logs: list = field(default_factory=list)

    def json(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _Recorder:
    """Collects the run's log lines and forwards each one as it happens."""

    def __init__(self, sink: LogSink | None) -> None:
        self.lines: list[str] = []
        self._sink = sink

    def __call__(self, line: str) -> None:
        text = str(line).rstrip()
        self.lines.append(text)
        if self._sink is not None:
            try:
                self._sink(text)
            except Exception:  # noqa: BLE001 - a broken sink must not fail the probe
                pass

    def drain(self, state: dict) -> None:
        """Forward node log lines that landed in state but not through us."""
        for line in state.get("logs") or []:
            text = str(line).rstrip()
            if text and text not in self.lines:
                self(text)
        state["logs"] = []


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


def _recommend(out: ProbeResult, key: str, value: Any, reason: str, *, confidence: str = "high") -> None:
    entry = config_schema.get(key)
    out.recommendations.append(
        {
            "key": key,
            "value": value,
            "reason": reason,
            "confidence": confidence,
            "help": entry.help if entry else "",
        }
    )


def _model_findings(profile: dict) -> dict:
    """Confirm the model was understood: metric, fact table, entity, families."""
    primary = profile.get("primary_value_bundle") or {}
    families = []
    for bundle in profile.get("measure_bundles") or []:
        measures = bundle.get("measures") or {}
        families.append(
            {
                "family": bundle.get("family"),
                "sourceTable": bundle.get("source_table"),
                "current": measures.get("current"),
                "prior": measures.get("prior"),
                "change": measures.get("change"),
                # A family with no prior measure is not broken: the dashboard
                # reconstructs prior = current - change.
                "priorReconstructed": bool(not measures.get("prior") and measures.get("change")),
                "additive": bool(bundle.get("additive_candidate")),
                "isPrimary": bundle.get("id") == primary.get("id"),
            }
        )
    entity = profile.get("entity_dimension") or None
    return {
        "factTable": profile.get("fact_table"),
        "primaryMetric": {
            "family": primary.get("family"),
            "measures": primary.get("measures") or {},
            "sourceTable": primary.get("source_table"),
        },
        "entityDimension": entity,
        "entityResolved": bool(entity and entity.get("reference")),
        "measureFamilies": families,
        "dimensionCount": len(profile.get("dimensions") or []),
        "warnings": list(profile.get("warnings") or []),
    }


#: How many date columns to test. One query per table covers all of that
#: table's dates at once, so this is a cap on tables, not on columns.
_SNAPSHOT_MAX_TABLES = 3


def _snapshot_findings(state: dict, log) -> dict:
    """Measure each date column's cardinality and judge what it actually is.

    One `EVALUATE ROW(...)` per table covers every date column on it, so this
    costs at most three queries. Read-only, bounded, and non-fatal: a model the
    probe cannot measure reports "unknown" rather than failing the run.
    """
    from ..kernel import snapshot
    from ..tools import powerbi_executor

    metadata = state.get("model_metadata") or {}
    by_table: dict[str, list[str]] = {}
    for reference in metadata.get("date_fields") or []:
        text = str(reference)
        if "[" not in text or not text.endswith("]"):
            continue
        table, column = text.split("[", 1)
        column = column[:-1]
        # RLS plumbing carries created/updated stamps that describe the security
        # model, not the business - testing them wastes a query and can only
        # produce a misleading answer.
        if table.upper().startswith("RLS"):
            continue
        by_table.setdefault(table, []).append(column)

    verdicts: list = []
    for table, columns in list(by_table.items())[:_SNAPSHOT_MAX_TABLES]:
        parts = [f'"rows", COUNTROWS({_ref(table)})']
        for index, column in enumerate(columns):
            reference = f"{_ref(table)}[{column}]"
            parts.append(f'"d{index}", DISTINCTCOUNT({reference})')
            parts.append(f'"m{index}", MAX({reference})')
        dax = "EVALUATE ROW(" + ", ".join(parts) + ")"
        try:
            results = powerbi_executor.execute_python(
                state.get("workspace_id"), state.get("dataset_id"),
                [{"name": "snapshot_probe", "dax": dax}],
                token=state.get("pbi_token"))
            entry = results.get("snapshot_probe") or {}
            if entry.get("status") != "success":
                continue
            row = entry["result"]["results"][0]["tables"][0]["rows"][0]
        except (KeyError, IndexError, TypeError, OSError):
            continue

        row_count = _cell(row, "rows") or 0
        for index, column in enumerate(columns):
            verdicts.append(snapshot.judge_date_role(
                f"{table}[{column}]",
                distinct_count=int(_cell(row, f"d{index}") or 0),
                row_count=int(row_count),
                latest=_cell(row, f"m{index}")))

    picked = snapshot.pick_snapshot_column(verdicts)
    if picked:
        log(f"  {picked.column} looks like an as-at stamp "
            f"({picked.distinct_count} distinct value(s)).")
    return {
        "column": picked.column if picked else None,
        "latest": _date_text(picked.latest) if picked else None,
        "role": picked.role.value if picked else "unknown",
        "reason": picked.reason if picked else "no as-at stamp was identified",
        "filterStyle": picked.role.filter_style if picked else None,
        "candidates": [
            {"column": v.column, "role": v.role.value,
             "distinctValues": v.distinct_count, "reason": v.reason}
            for v in verdicts
        ],
    }


def _ref(table: str) -> str:
    return "'" + str(table).replace("'", "''") + "'"


def _cell(row: dict, name: str):
    for key, value in (row or {}).items():
        if str(key).strip("[]").lower() == name.lower():
            return value
    return None


def _date_text(value) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text.split("T", 1)[0] if "T" in text else text


def _time_axis_findings(profile: dict, period_context: dict) -> list[dict]:
    """Candidate time axes with the resolver's verdict where it has one.

    The verdict is what decides whether weekly and daily analysis can ever
    work: a load/posting date concentrates the metric in one bucket, and a
    stale axis disables the level with an honest caveat rather than reporting
    against data that stopped months ago.
    """
    verdicts = {
        str(check.get("column") or "").casefold(): check
        for check in (period_context.get("checks") or [])
        if isinstance(check, dict)
    }
    axes = []
    for dim in profile.get("time_dimensions") or []:
        column = str(dim.get("column") or "")
        check = verdicts.get(column.casefold()) or {}
        axes.append(
            {
                "reference": dim.get("reference"),
                "table": dim.get("table"),
                "column": column,
                "dataType": dim.get("data_type"),
                "category": dim.get("category"),
                "score": dim.get("score"),
                "verdict": check.get("verdict"),
                "grain": check.get("grain"),
                "periods": check.get("periods"),
                "dataAsOf": check.get("data_as_of"),
                "maxBucketShare": check.get("max_bucket_share"),
                "selected": dim.get("reference") == period_context.get("axis"),
            }
        )
    return axes


def _entity_findings(scope: dict) -> dict:
    """The classification that populates the comparable/excluded multi-selects."""
    return {
        "source": scope.get("source"),
        "resolved": scope.get("source") != "unresolved",
        "entityDimension": scope.get("entity_dimension"),
        "comparable": list(scope.get("active_comparable_population") or []),
        "excluded": list(scope.get("excluded_from_comparison") or []),
        "currentOnly": list(scope.get("new_entities") or []),
        "priorOnly": list(scope.get("prior_only_entities") or []),
        "truncated": bool(scope.get("truncated")),
        "warnings": list(scope.get("warnings") or []),
    }


def _role_findings(resolved: dict, coverage: dict, universe: dict) -> dict:
    """Resolved hierarchy levels, with the ones safe to use marked as such."""
    roles = []
    universe_roles = universe.get("roles") or {}
    coverage_levels = {level.get("role"): level for level in (coverage.get("levels") or [])}
    for role, info in resolved.items():
        scanned = universe_roles.get(role) or {}
        level = coverage_levels.get(role) or {}
        counts = level.get("counts") or {}
        roles.append(
            {
                "role": role,
                "column": info.get("column"),
                "reference": info.get("group_ref"),
                "parents": list(info.get("parent_refs") or []),
                "depth": info.get("level"),
                "coverageOnly": bool(info.get("coverage_only")),
                "focusEligible": not info.get("coverage_only") and info.get("level") is not None,
                "status": scanned.get("status") or level.get("status"),
                "memberCount": scanned.get("returned_member_count") or counts.get("total"),
                "reconciled": scanned.get("diagnostics_reconciled"),
                "poolCapped": bool(scanned.get("pool_capped")),
            }
        )
    roles.sort(key=lambda item: (item["depth"] is None, item["depth"] or 0, item["role"]))
    return {
        "resolved": roles,
        "focusCandidates": [r["role"] for r in roles if r["focusEligible"]],
        "coverageCandidates": [r["role"] for r in roles],
        "mirrored": coverage.get("mirrored_roles") or {},
        "skipped": coverage.get("skipped_roles") or {},
    }


def _derive_findings(out: ProbeResult, state: dict) -> None:
    """Turn the raw node output into blocking errors, warnings and key advice."""
    universe = out.universe
    roles = out.roles

    # The root cause first. Everything this agent does is "this period versus
    # the same period last year", so a model with no current+prior measure pair
    # cannot be reported on at all - and saying "rename your levels" to someone
    # in that position sends them to fix the wrong thing.
    has_measures = bool(out.model.get("measureFamilies"))
    has_dimensions = bool(out.model.get("dimensionCount"))
    if not has_measures:
        # WP4: a snapshot model is no longer refused outright. It cannot support
        # a *year-on-year sales* report - that part was always true - but it can
        # support a stock report measured against a policy, which is what the
        # inventory reports actually need. So the refusal now depends on what
        # kind of report is being set up.
        snapshot = out.model.get("snapshotDate") or {}
        if snapshot.get("column"):
            out.warnings.append(
                f"This dashboard is a stock position taken at a single moment "
                f"({snapshot.get('column')}, as at {snapshot.get('latest') or 'the latest load'}), "
                "not a record of trade over time. It has no 'same period last year' to compare "
                "against, so a sales-style growth report cannot be built from it. A stock report "
                "- comparing what you hold against your agreed stock policy - can be, and that is "
                "what the inventory reports do. Choose a stock report on the next step."
            )
        else:
            out.blocking.append(
                "This dashboard has no measures that compare one period with the same period a year "
                "earlier, and that comparison is the whole basis of a sales growth report. It "
                "needs a matching set - this year, last year, and the change between them - such as "
                "'net revenue CURRENT', 'net revenue PAST' and 'revenue Growth'. Nothing here can be "
                "made to work by changing settings on this page: the measures have to exist in the "
                "Power BI model first."
            )

    if universe.get("status") not in {"ok", "partial"} and has_measures:
        # Without measures the scan was never going to run, and reporting it as
        # a second failure just triples one problem.
        reason = str(universe.get("reason") or "").strip()
        out.blocking.append(
            "The agent could not read your product levels from this dashboard"
            + (f" ({reason})" if reason else "")
            + ". Nothing else on this page can be trusted until that works, so do not set this "
            "client live yet."
        )

    # Reconciliation is a hard stop, not a warning: a level whose scanned members
    # do not add up to the overall total will publish ranked percentages that are
    # wrong, and it will do it quietly.
    unreconciled = [
        role["role"] for role in roles.get("resolved", [])
        if role.get("status") == "ok" and role.get("reconciled") is False
    ]
    if unreconciled:
        out.blocking.append(
            "The parts do not add up to the whole for: " + ", ".join(unreconciled) + ". "
            "Adding up every member of these levels gives a different total from the dashboard's "
            "own figure, so any percentage the report calculated for them would be wrong. "
            "This usually means a filter or a relationship in the dashboard needs looking at. "
            "Remove these levels, or fix the dashboard, before going live."
        )

    focus_roles = [r["role"] for r in roles.get("resolved", [])
                   if r.get("focusEligible") and r.get("status") == "ok" and r.get("reconciled") is not False]
    if focus_roles:
        _recommend(out, "summary_focus_allowed_roles", focus_roles,
                   f"Found {len(focus_roles)} product level(s) whose figures add up correctly: "
                   + ", ".join(focus_roles) + ".")
    elif has_measures and has_dimensions:
        # Measures exist and the model has columns to group by - so this really
        # is a naming difference, and renaming is the right fix.
        out.blocking.append(
            "None of this dashboard's columns look like a product hierarchy the agent "
            "recognises, so it has nothing to write about. This is usually a naming difference "
            "rather than a real problem: on the 'Product levels' step, use 'Rename your levels to "
            "standard ones' to say which of your columns is the division, the department and so "
            "on, then run this check again."
        )
    elif has_measures:
        # Measures but no groupable columns at all. Renaming cannot conjure a
        # column that is not there, so do not send anyone to that box.
        out.blocking.append(
            "The agent found figures it could report, but no columns to break them down by - no "
            "product, department or category columns at all. Renaming levels cannot help here, "
            "because there is nothing to rename. The Power BI model needs the descriptive "
            "columns added alongside its measures."
        )

    coverage_roles = [
        r["role"] for r in roles.get("resolved", [])
        if r.get("status") in {"ok", None} and r["role"] not in (roles.get("mirrored") or {})
    ]
    if coverage_roles:
        _recommend(out, "summary_coverage_roles", coverage_roles,
                   "Every member of these levels can get its own ranked row. Levels that turned "
                   "out to be duplicates of another are left out.")

    for role, mirrors in (roles.get("mirrored") or {}).items():
        # summary_coverage.mirrored_roles maps role -> the single role it copies,
        # as a plain string. Joining a string yields "d, i, v, i, s, i, o, n".
        names = ", ".join(mirrors) if isinstance(mirrors, (list, tuple, set)) else str(mirrors)
        out.warnings.append(
            f"Your '{role}' level holds exactly the same members and the same figures as "
            f"'{names}', so it is a second copy of that level rather than a level of its own. "
            "It has been left out so the report does not say the same thing twice - nothing is "
            f"lost, because '{names}' already covers it."
        )

    capped = [r["role"] for r in roles.get("resolved", []) if r.get("poolCapped")]
    if capped:
        out.warnings.append(
            "These levels have more members than the agent looked at: " + ", ".join(capped) + ". "
            "It examined the largest ones, so a small member could be missed. If that matters, "
            "raise 'Members looked at per level' on the summary settings step and check again."
        )

    # Entity dimension: the R6 dashboard needs a level whose bills filter
    # correctly and add to the company total. When the profile cannot find one,
    # pinning it is configuration, not code.
    if not out.model.get("entityResolved"):
        fallback = next(
            (r["role"] for r in roles.get("resolved", []) if r.get("focusEligible")), ""
        )
        out.warnings.append(
            "The agent could not tell which column identifies your stores or branches - the "
            "names in this dashboard do not match anything it recognises. Without that, the "
            "dashboard's per-location cards have nothing to be built from, so you need to choose "
            "a level for them by hand on the 'Product levels' step."
        )
        if fallback:
            _recommend(out, "summary_dashboard_entity_role", fallback,
                       f"Stores could not be identified, so the cards need a level chosen by "
                       f"hand. '{fallback}' is a reasonable choice - check that its figures add "
                       "up to your company total before relying on it.",
                       confidence="medium")
    else:
        _recommend(out, "summary_dashboard_entity_role", "",
                   "Your stores were identified automatically, so this can be left empty and the "
                   "agent will use them.")

    entities = out.entities
    if entities.get("resolved"):
        if entities.get("comparable"):
            _recommend(out, "insight_comparable_population", entities["comparable"],
                       f"{len(entities['comparable'])} shop(s) were trading in both this year and "
                       "last year, so comparing them is fair.")
        if entities.get("currentOnly") or entities.get("priorOnly"):
            excluded = sorted({*entities.get("currentOnly", []), *entities.get("priorOnly", [])})
            _recommend(out, "insight_excluded_entities", excluded,
                       f"{len(excluded)} shop(s) appear in only one of the two years - newly "
                       "opened, or closed. Comparing them against a year they were not trading "
                       "in would make growth look wrong.")
        if entities.get("truncated"):
            out.warnings.append(
                "There are more shops than the agent listed, so the lists above are incomplete. "
                "Raise 'Maximum shops to list' on the deep-dive settings step if you need all of "
                "them."
            )
    else:
        out.warnings.append(
            "The agent could not identify individual shops in this dashboard, so it will work "
            "out which ones are comparable each time it runs rather than using a fixed list. "
            "That is usually fine. "
            + "; ".join(entities.get("warnings") or [])
        )

    # Time axes decide whether the weekly and daily levels can ever produce
    # anything. Saying so here is cheaper than a run that quietly disables them.
    freshness = out.freshness
    selected_verdict = next(
        (axis for axis in out.time_axes if axis.get("selected")), {}
    )
    batch_axes = [axis["column"] for axis in out.time_axes if axis.get("verdict") == "batch_date"]
    if batch_axes:
        out.warnings.append(
            "These date columns record when data was loaded into the dashboard, not when trading "
            "happened: " + ", ".join(batch_axes) + ". A whole month of sales lands on one date, "
            "so day-by-day and week-by-week analysis on them would be meaningless. The agent has "
            "correctly refused to use them."
        )
    if freshness.get("freshness_status") in {None, "", "unknown"}:
        # Saying "not probed" is the honest answer. Guessing a verdict from
        # metadata alone is how a load/posting date gets treated as business
        # activity, which is the exact mistake the temporal gate exists to stop.
        out.warnings.append(
            "How up to date this dashboard is has not been measured, because that needs the "
            "thorough check. Tick 'thorough check' and run it again to find out whether "
            "day-by-day and week-by-week reporting can work here. Until then, treat those as "
            "unknown rather than working."
        )
    elif freshness.get("freshness_status") == "stale":
        out.warnings.append(
            f"This dashboard's data stops at {freshness.get('data_as_of')}, but today is "
            f"{freshness.get('today')}. Reporting on 'last week' or 'yesterday' would be "
            "meaningless, so those sections will switch themselves off and say why. Everything "
            "comparing this year to last year still works normally."
        )
        _recommend(out, "insight_recent_week_enabled", False,
                   "There is no up-to-date daily date to report a week against, so this section "
                   "would switch itself off anyway.",
                   confidence="medium")
        _recommend(out, "insight_daily_enabled", False,
                   "Same reason as the weekly setting: no up-to-date daily date.",
                   confidence="medium")
    elif selected_verdict.get("grain"):
        _recommend(out, "insight_reporting_grain",
                   "month" if selected_verdict["grain"] not in {"day", "week", "month"} else selected_verdict["grain"],
                   f"This dashboard records time by {selected_verdict['grain']}, so that is the "
                   "natural reporting period.",
                   confidence="medium")

    if out.blocking:
        out.status = "failed"
        out.reason = out.blocking[0]
    elif out.warnings:
        out.status = "degraded"
        out.reason = out.warnings[0]
    else:
        out.status = "ok"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_probe(
    config: dict,
    *,
    config_path: str = "",
    on_log: LogSink | None = None,
    candidate_pool: int | None = None,
    keep_artifacts: Path | str | None = None,
    deep: bool = False,
) -> ProbeResult:
    """Inspect a live semantic model and report what it exposes.

    ``config`` is a plain config dict (already env-overridden by
    ``main.load_config`` when it came from a file). ``on_log`` receives each
    log line as it is produced, so a UI can stream progress.

    ``deep`` additionally runs the shared pre-fork diagnostic portfolio
    (``baseline_coverage``). That is what gives the period resolver real trend
    evidence, so the time-axis verdicts and ``data_as_of`` become measured
    rather than "not probed" - at the cost of up to ``insight_max_scan_queries``
    further REST calls. The default stays cheap because the roles, entities and
    reconciliation answers arrive without it.

    Writes go to a temporary directory that is deleted afterwards unless
    ``keep_artifacts`` names somewhere to copy them, so a probe can never touch
    production memory, history or published output.
    """
    from ..agents import baseline_scope, metadata_reader, semantic_profiler, summary_focus_universe
    from ..agents import summary_period_resolver
    from ..main import build_initial_state

    log = _Recorder(on_log)
    out = ProbeResult(started_at=_now(), deep=bool(deep))
    started = time.monotonic()
    workdir = Path(tempfile.mkdtemp(prefix="insightgen-probe-"))

    try:
        state = build_initial_state(config, config_path)
        # Isolate every write. The probe is safe to run repeatedly precisely
        # because nothing it does is visible outside this directory.
        state["output_folder"] = str(workdir)
        state["summary_memory_root"] = str(workdir / "memory")
        state["insight_memory_root"] = str(workdir / "insight-memory")
        # The universe scan is R4's; the probe must exercise it whatever the
        # config says, because that is the thing being validated.
        state["summary_r4_enabled"] = True
        if candidate_pool:
            state["summary_focus_candidate_pool_per_role"] = int(candidate_pool)
        state.setdefault("logs", [])
        state.setdefault("errors", [])

        log("Reading the dashboard's structure...")
        state.update(metadata_reader.run(state))
        log.drain(state)
        if state.get("fatal"):
            out.blocking.append(
                "The agent could not read this dashboard's structure. Check that the workspace "
                f"and dataset IDs are right and that you have access to them. ({state.get('fatal')})"
            )
            out.status = "failed"
            out.reason = out.blocking[0]
            return out
        if not state.get("pbi_token"):
            out.blocking.append(
                "Could not sign in to Power BI. Two things usually cause this, and both need "
                "your Power BI administrator: the 'Execute queries' setting must be switched on "
                "for your organisation, and you need read and build permission on this dataset."
            )
            out.status = "failed"
            out.reason = out.blocking[0]
            return out

        log("Working out which measures are sales, quantities and comparisons...")
        state.update(semantic_profiler.run(state))
        log.drain(state)
        profile = state.get("semantic_model_profile") or {}
        out.model = _model_findings(profile)

        # WP4: is this a stock position or a record of trade? Filtering a
        # snapshot with a date RANGE produces a confidently wrong number, so the
        # answer has to be measured rather than inferred from a column name.
        log("Checking whether the dates record events or stamp a stock position...")
        out.model["snapshotDate"] = _snapshot_findings(state, log)

        log("Sorting shops into those trading in both years and those in only one...")
        state.update(baseline_scope.run(state))
        log.drain(state)
        out.entities = _entity_findings(state.get("resolved_entity_scope") or {})

        if deep:
            from ..agents import baseline_coverage

            log("Running the thorough check, to measure how up to date the data is...")
            state.update(baseline_coverage.run(state))
            log.drain(state)

        log("Reading your product levels and checking their figures add up...")
        state.update(summary_focus_universe.run(state))
        log.drain(state)
        out.universe = state.get("summary_focus_universe") or {}
        out.coverage = state.get("summary_coverage") or {}

        resolved_roles = summary_focus_universe._resolve_role_columns(profile, state)
        store = summary_focus_universe._resolve_store_role(profile, state)
        if store:
            resolved_roles = {**resolved_roles, "store": store}
        resolved_roles.update(
            summary_focus_universe._coverage_only_roles(profile, state, resolved_roles)
        )
        out.roles = _role_findings(resolved_roles, out.coverage, out.universe)

        # Freshness is metadata-derived here: the probe deliberately does not
        # run the broad diagnostic portfolio, so the resolver falls back to the
        # evidence it does have and says which axis it chose and why.
        try:
            state.update(summary_period_resolver.run(state))
            log.drain(state)
        except Exception as exc:  # noqa: BLE001 - freshness is additive to the probe
            out.warnings.append(f"Period/freshness resolution was unavailable ({type(exc).__name__}: {exc}).")
        context = state.get("summary_period_context") or {}
        out.freshness = {
            "grain": context.get("grain"),
            "axis": context.get("axis"),
            "data_as_of": context.get("data_as_of"),
            "period_anchor": context.get("period_anchor"),
            "freshness_status": context.get("freshness_status"),
            "today": context.get("today"),
            "reason": context.get("reason"),
            "checks": context.get("checks") or [],
        }
        out.time_axes = _time_axis_findings(profile, context)

        for error in state.get("errors") or []:
            out.warnings.append(str(error))

        _derive_findings(out, state)
        log(f"Probe finished: {out.status}"
            f" ({len(out.blocking)} blocking, {len(out.warnings)} warning(s))")

    except Exception as exc:  # noqa: BLE001 - a probe failure is a reported result
        out.status = "failed"
        out.reason = f"{type(exc).__name__}: {exc}"
        out.blocking.append(out.reason)
        log(f"Probe failed: {out.reason}")
    finally:
        if keep_artifacts:
            destination = Path(keep_artifacts)
            destination.mkdir(parents=True, exist_ok=True)
            for item in workdir.glob("*.json"):
                shutil.copy2(item, destination / item.name)
        shutil.rmtree(workdir, ignore_errors=True)
        out.logs = log.lines
        out.finished_at = _now()
        out.duration_seconds = round(time.monotonic() - started, 2)

    return out
