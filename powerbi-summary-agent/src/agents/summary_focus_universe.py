"""Deterministic per-role focus universe (summary-only, R4).

Guarantees the rotation candidate universe does not depend on whether the LLM
DAX planner happened to request a Division/Department/Category breakdown. For
each resolved allowed role it runs at most one bounded, scope-validated universe
scan (``summary_focus_queries.universe_scan``) carrying full-set broadcast
diagnostics, and parses the result into the ``summary_focus_universe`` contract
consumed by the candidate builder and portfolio selector.

Concurrency contract (see CLAUDE.md): writes only summary-branch state; executes
with the pre-fetched ``state["pbi_token"]`` and never calls ``get_powerbi_token``
post-fork; never touches Insight baseline templates; uses no LLM-generated or
-repaired DAX; and is non-fatal - a failed role scan degrades to whatever else
resolved, and an empty universe simply yields Overall Performance only.
"""

from __future__ import annotations

from ..tools import file_io
from ..tools import summary_coverage
from ..tools import summary_focus_queries as q
from ..tools import summary_materiality as materiality
from ..tools import summary_roles
from ..utils.logger import RunLogger
from .summary_focus_evidence import (
    _families,
    _ref_parts,
    _relationship_distance,
    _run_query,
    _semantic_level,
)


def _resolve_role_columns(profile: dict, state: dict, roles_filter: set[str] | None = None) -> dict:
    """Map each allowed canonical role to its group column + ancestry refs.

    ``roles_filter`` overrides which canonical roles are resolved; it defaults to
    the configured primary-focus roles so existing callers are unchanged. The
    coverage pass reuses this with a wider role set.

    Ordering and roles come from the shared semantic hierarchy vocabulary, never
    model object names. Parents are the strictly-broader hierarchy columns in the
    same source table or connected through an active relationship path. This
    matters when a model keeps Department on a related dimension table while
    Division/Category live on the main merchandise table: the emitted path must
    still be Division -> Department -> Category for identity and diversity.
    """
    dims = [dim for dim in (profile.get("dimensions") or []) if dim.get("reference")]
    leveled: list[tuple[int, str, dict]] = []
    for dim in dims:
        _, column = _ref_parts(dim.get("reference"))
        inferred_level, inferred_role = _semantic_level(column or dim.get("column"))
        # Aliases must be able to resolve a model-specific name even when the
        # generic semantic matcher cannot recognise it first.
        role = summary_roles.canonical_role(
            inferred_role or column or dim.get("column"), dim.get("column"), state,
        )
        level = summary_roles.hierarchy_level(role)
        if level is None:
            level = inferred_level
        if level is not None and role:
            leveled.append((level, role, dim))
    leveled.sort(key=lambda item: item[0])
    allowed = set(roles_filter) if roles_filter is not None else set(summary_roles.allowed_roles(state))
    metadata = state.get("model_metadata") or {}
    out: dict = {}
    for level, role, dim in leveled:
        canonical = summary_roles.canonical_role(role, dim.get("column"), state)
        if canonical not in allowed or canonical in out:
            continue
        table, _ = _ref_parts(dim.get("reference"))
        # Keep one best parent per broader semantic level. Same-table parents
        # win; otherwise the shortest active relationship path wins. Including
        # related-table parents preserves the full hierarchy path without any
        # model-specific table or column names.
        parent_by_role: dict[str, tuple[tuple, dict]] = {}
        for plevel, prole, parent in leveled:
            if plevel >= level or prole == canonical:
                continue
            parent_table, _ = _ref_parts(parent.get("reference"))
            distance = 0 if parent_table == table else _relationship_distance(
                metadata, table, parent_table,
            )
            if distance is None:
                continue
            rank = (
                0 if parent_table == table else 1,
                int(distance),
                -float(parent.get("score") or 0),
                str(parent.get("reference") or ""),
            )
            current = parent_by_role.get(prole)
            if current is None or rank < current[0]:
                parent_by_role[prole] = (rank, parent)
        parents = [
            parent.get("reference")
            for _prole, (_rank, parent) in sorted(
                parent_by_role.items(),
                key=lambda item: summary_roles.hierarchy_level(item[0]) or 999,
            )
        ]
        out[canonical] = {
            "role": canonical,
            "group_ref": dim.get("reference"),
            "parent_refs": parents,
            "column": dim.get("column"),
            "level": level,
        }
    return out


def _resolve_store_role(profile: dict, state: dict) -> dict | None:
    """Resolve the store/location level from the profile's entity dimension.

    Store is orthogonal to the merchandise hierarchy, so it is not carried in
    ``HIERARCHY_LEVELS`` and is never resolved by ``_resolve_role_columns``. It
    is coverage-only: every store gets a ranked line, but a store can never
    consume a focus slot. It carries no parents - grouping a store under a
    merchandise ancestor would be meaningless.
    """
    if "store" not in set(summary_roles.coverage_roles(state)):
        return None
    entity = profile.get("entity_dimension") or {}
    reference = entity.get("reference")
    if not reference:
        return None
    return {
        "role": "store",
        "group_ref": reference,
        "parent_refs": [],
        "column": entity.get("column"),
        "level": None,
        "coverage_only": True,
    }


def _coverage_only_roles(profile: dict, state: dict, focus_roles: dict) -> dict:
    """Roles covered but not eligible for a focus slot, keyed by canonical role.

    Anything in ``summary_coverage_roles`` that is not already a resolved focus
    role: merchandise levels resolved the normal way, plus store.
    """
    coverage = set(summary_roles.coverage_roles(state))
    extra = coverage - set(focus_roles)
    out: dict = {}
    merchandise = {role for role in extra if summary_roles.hierarchy_level(role) is not None}
    if merchandise:
        for role, info in _resolve_role_columns(profile, state, merchandise).items():
            out[role] = {**info, "coverage_only": True}
    store = _resolve_store_role(profile, state) if "store" in extra else None
    if store:
        out["store"] = store
    return out


def _primary_measures(families: list[dict]) -> tuple[str | None, str | None, str | None, str]:
    if not families:
        return None, None, None, "performance"
    family = families[0]
    phases = family.get("phases") or {}
    return phases.get("current"), phases.get("prior"), phases.get("change"), str(family.get("family") or "revenue")


def _resolve_spine(state: dict):
    """The comparison this report is built on (WP2).

    Defaults to period-over-period, which is what every pre-WP2 config means,
    so resolution cannot change behaviour for Sales YoY. An unknown spine name
    falls back rather than failing the run - the caller is already on an error
    path when it asks.
    """
    from ..domains.sales import spines as sales_spines
    from ..kernel import spine as kernel_spine

    kind = str(state.get("report_spine") or sales_spines.PeriodOverPeriodSpine.kind)
    try:
        return kernel_spine.get(kind)()
    except (KeyError, TypeError):
        return sales_spines.PeriodOverPeriodSpine()


def run(state: dict) -> dict:
    log = RunLogger(state)
    # R4 gate: with R4 off this node is a transparent no-op so the single-focus
    # path is completely unchanged.
    if not state.get("summary_r4_enabled", False):
        return {**log.updates()}

    profile = state.get("semantic_model_profile") or {}
    families = _families(profile)
    current_m, prior_m, change_m, metric_family = _primary_measures(families)
    roles = _resolve_role_columns(profile, state)
    # Coverage-only levels (store, plus any covered merchandise level that is not
    # focus-eligible) are scanned under their own budget so full coverage can
    # never starve the focus rotation of a scan.
    coverage_extra = _coverage_only_roles(profile, state, roles)

    if not roles and not coverage_extra:
        universe = {
            "status": "no_qualifying_hierarchy",
            "roles": {},
            "reason": "no allowed Division/Department/Category dimension resolved from metadata",
        }
        file_io.write_json(state, "summary_focus_universe.json", universe)
        log.info("Focus universe: no qualifying hierarchy; Overall Performance only.")
        return {"summary_focus_universe": universe, **log.updates()}

    if not (current_m and prior_m):
        # WP2: this is a spine-resolution failure, not simply a missing measure.
        # The report asked to be measured against a baseline and the model does
        # not carry one - so the reason names the baseline that is missing,
        # which is what tells a reader whether it is a config or a model problem.
        # On both live inventory models this is the branch that fires, and
        # "no last-year measure" is the correct, actionable answer there.
        spine = _resolve_spine(state)
        universe = {
            "status": "no_metric",
            "roles": {},
            "reason": "no additive current/prior value family in metadata",
            "spine": getattr(spine, "kind", None),
            "baseline_expected": getattr(spine, "baseline_label", None),
            "spine_reason": (
                f"this report measures against {getattr(spine, 'baseline_label', 'a baseline')}, "
                f"and the model exposes no such measure"),
        }
        file_io.write_json(state, "summary_focus_universe.json", universe)
        log.error("Focus universe: no additive current/prior family; universe scan skipped.")
        return {"summary_focus_universe": universe, **log.updates()}

    entity = profile.get("entity_dimension") or {}
    entity_ref = entity.get("reference")
    comparable = [
        str(item) for item in
        (state.get("resolved_entity_scope") or {}).get("active_comparable_population") or []
    ]
    population_filter = q.treatas(entity_ref, comparable) if (entity_ref and comparable) else None
    filters = [population_filter] if population_filter else []
    codes = list(comparable)
    contract_hint = {"population_status": "comparable", "population_codes": codes} if codes else {}

    pool = max(1, int(state.get("summary_focus_candidate_pool_per_role", 30)))
    budget = {"used": 0, "max": max(0, int(state.get("summary_focus_universe_max_queries", 4)))}
    coverage_budget = {
        "used": 0,
        "max": max(0, int(state.get("summary_coverage_max_queries", 3))),
    }
    cache: dict = {}
    tol = float(state.get("summary_focus_reconciliation_tolerance_pct", 2))

    universe: dict = {
        "status": "ok",
        "metric_family": metric_family,
        "value_aliases": {"current": current_m, "prior": prior_m, "change": change_m},
        "roles": {},
    }
    for role, info in {**roles, **coverage_extra}.items():
        role_budget = coverage_budget if info.get("coverage_only") else budget
        if role_budget["used"] >= role_budget["max"]:
            universe["roles"][role] = {**info, "source": "skipped_budget", "status": "budget_exhausted", "members": []}
            continue
        scan = q.universe_scan(
            f"summary_universe_{role}",
            f"{role} coverage universe" if info.get("coverage_only") else f"{role} focus universe",
            group_col_ref=info["group_ref"],
            parent_col_refs=info["parent_refs"],
            filters=filters,
            current_measure=current_m,
            prior_measure=prior_m,
            change_measure=change_m,
            pool_rows=pool,
            contract_hint=contract_hint,
        )
        result = _run_query(state, scan, role_budget, cache)
        if result.get("status") != "success":
            universe["roles"][role] = {
                **info, "source": "universe_scan", "status": result.get("status"),
                "reasons": result.get("reasons"), "members": [],
            }
            log.error(f"Focus universe: {role} scan {result.get('status')}.")
            continue
        group_name = _ref_parts(info["group_ref"])[1]
        parent_names = [_ref_parts(ref)[1] for ref in info["parent_refs"]]
        parsed = materiality.parse_universe_rows(result["rows"], group_name, parent_names, tol, pool_rows=pool)
        universe["roles"][role] = {
            **info,
            "source": "universe_scan",
            "status": "ok",
            "metric_family": metric_family,
            "members": parsed["members"],
            "returned_member_count": parsed["returned_member_count"],
            "max_siblings_per_parent": parsed["max_siblings_per_parent"],
            "pool_capped": parsed["pool_capped"],
            "diagnostics_reconciled": parsed["diagnostics_reconciled"],
            "scope": {"population_status": "comparable" if codes else "returned_rows", "comparable_entities": codes},
        }
        log.info(
            f"Focus universe: {role} -> {parsed['returned_member_count']} member(s), "
            f"reconciled={parsed['diagnostics_reconciled']}, pool_capped={parsed['pool_capped']}."
        )

    file_io.write_json(state, "summary_focus_universe.json", universe)

    # Full ranked coverage over every scanned level. This reuses the rows the
    # scans above already returned, so it costs no additional query.
    coverage = summary_coverage.build_coverage(
        universe,
        material_change_pct=float(state.get("summary_coverage_material_change_pct", 10)),
        material_share_pct=float(state.get("summary_coverage_material_share_pct", 5)),
    )
    file_io.write_json(state, "summary_coverage.json", coverage)
    covered = ", ".join(
        f"{level['role']}={level['counts']['total']}" for level in coverage.get("levels") or []
    )
    log.info(f"Coverage: {covered or 'none'}.")
    return {
        "summary_focus_universe": universe,
        "summary_coverage": coverage,
        **log.updates(),
    }
