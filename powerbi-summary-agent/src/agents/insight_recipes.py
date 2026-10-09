"""Insight branch - the recipe shelf: tested queries a model may ask for by name.

The reasoned tier (`src/tools/ai_tier.py`, `docs/reasoned-tier-implementation-plan.md`)
lets a model decide *what* to ask the data about a finding, never *how* to write
the query. It chooses a recipe and its arguments from `menu`; this module turns
that choice into DAX from the builders the scan and the gap scan already use,
validates it, scopes it, caches it by DAX hash and executes it. Nothing here
calls a model.

    recipe                         cost        built from
    breakdown(segment, by)         1 query     insight_scan_templates.build_gap_probe
    compare_to_peers(level)        0-1 query   a complete scan breakdown, else build_full_breakdown
    trend(segment)                 1 query     build_segment_trend_probe on the temporal gate's grain
    split_units_vs_price(segment)  free        insight_stat_detector._rate_volume_split on a returned row
    measure_formula(names)         free        the model metadata already in memory
    custom_dax(dax)                1 query     the model's own DAX; capped separately by the caller

**Arguments are business names, never model objects.** A level is named as the
trail names it ("store", "division"); a segment is a member value. Two rules
keep a model from fishing:

* ``by`` and ``level`` must be levels of the semantic profile (``levels``);
* ``segment`` must be the finding's own segment, or a member that appeared in a
  row already returned for this finding (``finding_evidence`` plus whatever the
  caller appends as recipes return rows).

The population filter is never an argument: every query takes it from
``insight_comparable_population``, through the same template helper the gap
scan uses. Scope is then proven from the DAX text itself -
`validate_comparable_scope` is called *without* the builder's contract hint,
which it would otherwise accept on the builder's word.

**One trail entry per call**, in the investigator's vocabulary (``success``,
``cache_hit``, ``cache_hit_failed``, ``rejected``, ``budget_refused``,
``failed``) and its ``run_dax`` shape, plus ``origin`` (``recipe:<name>`` or
``custom_dax``) so every existing reader of ``probes`` reads it unchanged. A
refusal, a validator rejection, a cache hit and a free recipe all cost nothing;
``cost`` says what each entry spent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from . import insight_scan_templates as tpl
from .dax_validator import validate_one
from .evidence_contract import dax_hash
from .insight_deterministic import _dimension_label
from .insight_gap_scan import _segment_dimension
from .insight_stat_detector import _rate_volume_split
from .scope_validator import validate_comparable_scope
from .semantic_profiler import bundle_phase

RECIPES = ("breakdown", "compare_to_peers", "trend", "split_units_vs_price",
           "measure_formula", "custom_dax")
#: Recipes answered from what is already in memory; they never reach Power BI.
FREE_RECIPES = ("split_units_vs_price", "measure_formula")
#: Members per level the menu lists as askable.
MAX_MEMBERS_SHOWN = 15
#: Scan coverage that is a whole population over one level, so peers can be read from it.
_PEER_COVERAGE = ("full_entity_breakdown", "full_dimension_breakdown")

_TOOL = {"measure_formula": "get_measure_definition",
         "split_units_vs_price": "split_units_vs_price"}


@dataclass
class Budget:
    """What one finding may still spend: queries, and custom DAX within them."""

    queries: int
    custom_dax: int = 0


# ------------------------------------------------------------------ vocabulary


def levels(state: dict) -> dict[str, dict]:
    """Business name -> dimension spec, for every level a recipe may group by.

    Bounded the way the evidence assembler bounds the gap scan's drill
    dimensions: the profile's dimensions in rank order, one per column, the
    first ``insight_metadata_max_dimensions + 1`` of them - plus the entity, always.
    Lower-ranked columns are mostly keys and copies on related tables. Time
    axes are not levels: the only one a recipe may use is the grain the
    temporal gate validated, and ``trend`` reads it from the gate.
    """
    profile = state.get("semantic_model_profile") or {}
    time_refs = {d.get("reference") for d in profile.get("time_dimensions") or []}
    first: list[dict] = []
    columns: set[str] = set()
    for dim in profile.get("dimensions") or []:
        column = str(dim.get("column") or "")
        if not dim.get("reference") or dim.get("reference") in time_refs or column in columns:
            continue
        columns.add(column)
        first.append(dim)
    cap = max(1, int(state.get("insight_metadata_max_dimensions", 5))) + 1
    entity = profile.get("entity_dimension")
    out: dict[str, dict] = {}
    columns = set()
    for dim in ([entity] if entity else []) + first[:cap]:
        column = str(dim.get("column") or "")
        if not dim.get("reference") or column in columns:
            continue
        columns.add(column)
        name = _dimension_label(column)
        if name in out:
            # "store_no" and "store_name" both read as "store"; keep them apart.
            name = re.sub(r"[_\s]+", " ", column).strip().lower()
        if name and name not in out:
            out[name] = dim
    return out


def _level(state: dict, name: Any) -> tuple[str, dict] | None:
    wanted = str(name or "").strip().casefold()
    for label, dim in levels(state).items():
        if wanted in (label.casefold(), str(dim.get("column") or "").casefold()):
            return label, dim
    return None


def _level_name(state: dict, dim: dict | None) -> str | None:
    ref = (dim or {}).get("reference")
    return next((label for label, d in levels(state).items() if d.get("reference") == ref), None)


def _row_levels(state: dict) -> dict[str, tuple[str, dict]]:
    """A result row's key -> (level name, dimension). Rows carry the bare column
    name unless two tables collide, then the qualified reference."""
    keys: dict[str, tuple[str, dict]] = {}
    for label, dim in levels(state).items():
        keys[str(dim.get("column"))] = (label, dim)
        keys[str(dim.get("reference"))] = (label, dim)
    return keys


def _labels(row: dict) -> dict[str, str]:
    return {key: value for key, value in row.items() if isinstance(value, str) and value.strip()}


# ------------------------------------------------------------------- evidence


def finding_evidence(state: dict, signal: dict) -> list[dict]:
    """The rows this finding has already returned: its scan tables and its
    gap-scan breakdowns. Each table is ``{source, within, rows}``, where
    ``within`` names the segment filter its rows sit inside (None for a scan
    table over the whole population). A caller adds each recipe's result here
    as it arrives, which is what lets a model drill into a member it was shown.
    """
    rows_by_name = {q.get("query_name"): q.get("rows") or []
                    for q in (state.get("insight_clean_data") or {}).get("queries", [])}
    brief = (state.get("insight_evidence_briefs") or {}).get(signal.get("id")) or {}
    names = [signal.get("evidence_query"), *(brief.get("supporting_queries") or [])]
    tables = [{"source": name, "within": None, "rows": rows_by_name[name]}
              for name in dict.fromkeys(n for n in names if n) if name in rows_by_name]
    gap = (state.get("insight_gap_evidence") or {}).get(signal.get("id")) or {}
    for drill, ev in (gap.get("evidence") or {}).items():
        tables.append({"source": f"gap_scan:{drill}", "within": gap.get("segment"),
                       "rows": (ev or {}).get("rows") or []})
    return tables


def _own_names(signal: dict) -> set[str]:
    names: list[Any] = [signal.get("affected_segment"), signal.get("evidence_segment")]
    names += list(signal.get("segment_members") or [])
    flat: list[Any] = []
    for name in names:
        flat.extend(name if isinstance(name, (list, tuple)) else [name])
    return {str(n) for n in flat if n not in (None, "")}


def _own_segment(state: dict, signal: dict) -> tuple[dict | None, Any]:
    """The finding's own segment exactly as the gap scan filters it, so a
    breakdown the gap scan already ran is the same DAX - and a cache hit."""
    gap = (state.get("insight_gap_evidence") or {}).get(signal.get("id")) or {}
    dim = gap.get("segment_dimension") or _segment_dimension(
        signal, state.get("insight_evidence_contracts") or {},
        state.get("semantic_model_profile") or {})
    return dim, signal.get("segment_members") or signal.get("affected_segment")


def _scope_type(state: dict, signal: dict) -> str:
    brief = (state.get("insight_evidence_briefs") or {}).get(signal.get("id")) or {}
    return str(brief.get("scope_type") or "comparable")


def _segment(state: dict, signal: dict, evidence: Iterable[dict],
             segment: Any) -> tuple[dict, Any, str] | str:
    """``(dimension, filter value, scope type)`` for a segment argument, or the
    reason it is refused."""
    text = str(segment or "").strip()
    if not text:
        return "a segment is required"
    if text in _own_names(signal):
        dim, value = _own_segment(state, signal)
        if not dim:
            return f"the level of this finding's segment {text!r} could not be resolved from its evidence"
        return dim, value, _scope_type(state, signal)
    keys = _row_levels(state)
    for table in evidence:
        for row in table.get("rows") or []:
            for key, value in _labels(row).items():
                if value == text and key in keys:
                    return keys[key][1], text, "comparable"
    return (f"{text!r} is neither this finding's segment nor a member of a row returned for it; "
            f"run a breakdown that returns it first")


def _members_seen(state: dict, evidence: Iterable[dict]) -> dict[str, list[str]]:
    keys = _row_levels(state)
    seen: dict[str, list[str]] = {}
    for table in evidence:
        for row in table.get("rows") or []:
            for key, value in _labels(row).items():
                if key in keys:
                    members = seen.setdefault(keys[key][0], [])
                    if value not in members and len(members) < MAX_MEMBERS_SHOWN:
                        members.append(value)
    return seen


# ------------------------------------------------------------------------ menu


def _temporal_grain(state: dict) -> tuple[dict | None, str]:
    """The grain the temporal gate validated, or why there is none."""
    verdict = state.get("insight_temporal_verdict") or {}
    column = verdict.get("column")
    if not verdict.get("enabled") or not column:
        reason = verdict.get("reason") or "the temporal gate accepted no time axis"
        return None, f"no validated time axis on this model ({reason})"
    profile = state.get("semantic_model_profile") or {}
    for dim in list(profile.get("time_dimensions") or []) + list(profile.get("dimensions") or []):
        if dim.get("reference") == column:
            return dim, ""
    match = re.match(r"^'?(.*?)'?\[(.+)\]$", str(column))
    if not match:
        return None, f"the validated time axis {column!r} is not a column reference"
    return {"table": match.group(1), "column": match.group(2), "reference": column}, ""


def menu(state: dict, signal: dict, evidence: list[dict] | None = None,
         allow_custom_dax: bool = True) -> dict:
    """What a model may ask about this finding, in business names.

    This is what the model sees in place of the full model description: the
    levels, the members it has been shown, and each recipe with its cost.
    """
    evidence = finding_evidence(state, signal) if evidence is None else evidence
    own_dim, _ = _own_segment(state, signal)
    names = list(levels(state))
    recipes = [
        {"name": "breakdown", "arguments": {"segment": "a segment", "by": "a level"},
         "cost": "1 query",
         "returns": "the segment's current, prior and change, split by the chosen level"},
        {"name": "compare_to_peers", "arguments": {"level": "a level"},
         "cost": "free when the scan already holds it, else 1 query",
         "returns": "every member of the level, so the finding's segment can be ranked among its peers"},
        {"name": "trend", "arguments": {"segment": "a segment"}, "cost": "1 query",
         "returns": "the segment's current, prior and change over the validated time axis"},
        {"name": "split_units_vs_price", "arguments": {"segment": "a segment"}, "cost": "free",
         "returns": "how much of the segment's revenue change came from units and how much from "
                    "revenue per unit, from a row already returned"},
        {"name": "measure_formula", "arguments": {"names": "measure names"}, "cost": "free",
         "returns": "the formula behind a measure"},
    ]
    if allow_custom_dax:
        recipes.append({"name": "custom_dax", "arguments": {"dax": "one DAX query"},
                        "cost": "1 query, and it is capped separately",
                        "returns": "rows of your own query; use only when no recipe can ask the question"})
    unavailable = {}
    _grain, reason = _temporal_grain(state)
    if reason:
        unavailable["trend"] = reason
        recipes = [r for r in recipes if r["name"] != "trend"]
    return {
        "finding_segment": signal.get("affected_segment"),
        "finding_level": _level_name(state, own_dim),
        "levels": names,
        "members_seen": _members_seen(state, evidence),
        "segment_rule": "a segment is the finding's own, or a member listed in members_seen",
        "already_asked": already_asked(state, signal),
        "recipes": recipes,
        "unavailable": unavailable,
    }


def already_asked(state: dict, signal: dict) -> list[dict]:
    """The breakdowns the standard drill already ran for this finding, as recipe
    calls. Asking one again is a free cache hit that adds nothing - on
    2026-10-08 a model spent three turns doing exactly that."""
    gap = (state.get("insight_gap_evidence") or {}).get(signal.get("id")) or {}
    by_column = {str(dim.get("column")): label for label, dim in levels(state).items()}
    return [{"recipe": "breakdown", "segment": signal.get("affected_segment"), "by": by_column[column]}
            for column in (gap.get("evidence") or {}) if column in by_column]


# ----------------------------------------------------------------------- build


def _peer_rows(state: dict, dim: dict) -> tuple[str, list[dict]] | None:
    """A complete, comparable scan breakdown over exactly this level, if the scan ran one."""
    rows_by_name = {q.get("query_name"): q.get("rows") or []
                    for q in (state.get("insight_clean_data") or {}).get("queries", [])}
    for name, contract in (state.get("insight_evidence_contracts") or {}).items():
        if (contract.get("coverage_kind") in _PEER_COVERAGE
                and contract.get("completeness") == "complete"
                and contract.get("population_status") == "comparable"
                and list(contract.get("grouping_references") or []) == [dim.get("reference")]
                and rows_by_name.get(name)):
            return name, rows_by_name[name]
    return None


def build(name: str, args: dict, state: dict, signal: dict,
          evidence: list[dict] | None = None) -> dict:
    """The query a recipe stands for.

    Returns ``{"dax", "contract_hint", "dimension"}``; or ``{"reuse", "rows",
    "dimension"}`` when ``compare_to_peers`` can read a scan table instead; or
    ``{"refused": reason}``. A refusal is decided here, before anything reaches
    a validator or Power BI.
    """
    args = dict(args or {})
    evidence = finding_evidence(state, signal) if evidence is None else evidence
    if name in FREE_RECIPES:
        return {"refused": f"{name} needs no query"}
    if name == "custom_dax":
        dax = str(args.get("dax") or "").strip()
        return {"dax": dax, "contract_hint": None, "dimension": None} if dax else \
            {"refused": "custom_dax needs a DAX query"}
    if name not in RECIPES:
        return {"refused": f"unknown recipe {name!r}; choose one of {', '.join(RECIPES)}"}

    shape = tpl.shape_from_profile(state.get("semantic_model_profile") or {}, state)
    if not shape:
        return {"refused": "the semantic profile has no primary value to query"}
    population = [str(v) for v in state.get("insight_comparable_population", []) or []]
    max_rows = max(1, int(state.get("insight_probe_max_rows", 20)))

    if name == "compare_to_peers":
        level = _level(state, args.get("level"))
        if level is None:
            return {"refused": f"unknown level {args.get('level')!r}; choose one of "
                               f"{', '.join(levels(state))}"}
        _label, dim = level
        reused = _peer_rows(state, dim)
        if reused:
            return {"reuse": reused[0], "rows": reused[1], "dimension": dim.get("column")}
        built = tpl.build_full_breakdown(shape, dim, population,
                                         max(20, int(state.get("insight_peer_max_rows", 200))))
        return {"dax": built["dax"], "contract_hint": built["contract_hint"],
                "dimension": dim.get("column")}

    segment = _segment(state, signal, evidence, args.get("segment"))
    if isinstance(segment, str):
        return {"refused": segment}
    seg_dim, seg_value, scope_type = segment

    if name == "breakdown":
        level = _level(state, args.get("by"))
        if level is None:
            return {"refused": f"unknown level {args.get('by')!r}; choose one of "
                               f"{', '.join(levels(state))}"}
        _label, drill = level
        if drill.get("reference") == seg_dim.get("reference"):
            return {"refused": f"{args.get('segment')!r} is already a member of {args.get('by')!r}; "
                               f"break it down by another level"}
        built = tpl.build_gap_probe(shape, seg_dim, seg_value, drill, population, max_rows,
                                    scope_type=scope_type)
        return {**built, "dimension": drill.get("column")}

    # trend
    grain, reason = _temporal_grain(state)
    if grain is None:
        return {"refused": reason}
    cap = max(500, 2 * int(state.get("insight_period_recent_window", 12)))
    built = tpl.build_segment_trend_probe(shape, grain, seg_dim, seg_value, population, cap,
                                          scope_type=scope_type)
    return {**built, "dimension": grain.get("column")}


# ------------------------------------------------------------------ free recipes


def _measure_formula(state: dict, args: dict) -> dict:
    """The investigator's get_measure_definition, in its trail shape."""
    raw = args.get("names") or args.get("measure_names") or []
    names = [raw] if isinstance(raw, str) else [str(n) for n in raw]
    if not names:
        return {"status": "rejected", "stage": "arguments", "reason": "measure_formula needs measure names"}
    index = {m.get("name"): m for m in (state.get("model_metadata") or {}).get("measures", [])}
    found, blank, missing = {}, [], []
    for name in names:
        measure = index.get(name)
        if measure is None:
            missing.append(name)
        elif measure.get("expression"):
            found[name] = {"table": measure.get("table", ""), "expression": measure["expression"]}
        else:
            # Definitions are blank at some permission levels; say so plainly.
            blank.append(name)
    return {"measures": names, "definitions": found, "definition_unavailable": blank,
            "not_found": missing,
            "status": "success" if found else ("unavailable" if blank else "not_found")}


def _split(state: dict, signal: dict, evidence: list[dict], args: dict) -> dict:
    """Units versus revenue per unit, from a single-level row already returned."""
    text = str(args.get("segment") or "").strip()
    if not text:
        return {"status": "rejected", "stage": "arguments", "reason": "a segment is required"}
    if text in _own_names(signal) and signal.get("decomposition"):
        return {"segment": text, "status": "success", "source": "finding",
                "within": None, "splits": list(signal["decomposition"])}
    shape = tpl.shape_from_profile(state.get("semantic_model_profile") or {}, state)
    primary = (shape or {}).get("primary") or {}

    def phases(bundle: dict) -> dict | None:
        found = {p: bundle_phase(bundle, p) for p in ("current", "prior", "change")}
        return {p: s["alias"] for p, s in found.items()} if all(found.values()) else None

    revenue = phases(primary) if primary else None
    drivers = [d for d in (phases(b) for b in (shape or {}).get("drivers", [])) if d]
    if revenue and drivers:
        for table in evidence:
            for row in table.get("rows") or []:
                labels = _labels(row)
                # One label only: a row of two levels measures their intersection,
                # not the segment.
                if list(labels.values()) != [text]:
                    continue
                splits = [s for s in (_rate_volume_split(row, revenue, d) for d in drivers) if s]
                if splits:
                    return {"segment": text, "status": "success", "source": table.get("source"),
                            "within": table.get("within"), "splits": splits}
    return {"segment": text, "status": "rejected", "stage": "arguments",
            "reason": (f"no single-level row returned for {text!r} carries revenue and a volume "
                       f"driver; run a breakdown that returns it first")}


# ------------------------------------------------------------------------- run


def _execute(state: dict, dax: str, name: str) -> dict:
    try:
        return pbi.execute_python(state["workspace_id"], state["dataset_id"],
                                  [{"name": name, "dax": dax, "purpose": "reasoned-tier recipe"}],
                                  token=state.get("pbi_token"))[name]
    except Exception as exc:  # noqa: BLE001 - a failed query is a trail entry, never a crash
        return {"status": "failed", "error": str(exc)}


def _shown(name: str, rows: list[dict], state: dict, signal: dict) -> tuple[list[dict], str, dict]:
    """The rows a recipe hands back, how complete they are, and anything derived."""
    cap = max(1, int(state.get("insight_probe_max_rows", 20)))
    extra: dict = {}
    if name == "trend":
        # The series is ascending; the most recent periods are the ones to keep.
        shown = rows[-cap:]
        return shown, "complete" if len(rows) <= cap else f"most recent {cap} of {len(rows)}", extra
    if name == "compare_to_peers":
        peer_cap = max(20, int(state.get("insight_peer_max_rows", 200)))
        own = _own_names(signal)
        position = next(((i, r) for i, r in enumerate(rows, start=1)
                         if set(_labels(r).values()) & own), None)
        shown = rows[:cap]
        if position:
            extra["position"] = {"segment": signal.get("affected_segment"),
                                 "rank": position[0], "of": len(rows)}
            if position[0] > cap:
                shown = shown + [position[1]]
        return shown, "partial" if len(rows) >= peer_cap else "complete", extra
    return rows[:cap], "partial" if len(rows) >= cap else "complete", extra


def run(name: str, args: dict, state: dict, signal: dict, cache: dict,
        evidence: list[dict] | None = None, budget: Budget | None = None) -> dict:
    """Answer one recipe call with one trail entry.

    Order: arguments, then validators, then the shared DAX-hash cache, then the
    budget, then Power BI with the run's pre-fetched token. Only an execution
    spends budget (``cost: 1``) - a refusal, a rejection or a cache hit never
    does. ``cache`` is the shared ``insight_query_cache`` and gains an entry for
    every execution, so the same recipe and arguments run once per run.
    """
    args = dict(args or {})
    evidence = finding_evidence(state, signal) if evidence is None else evidence
    entry: dict = {"tool": _TOOL.get(name, "run_dax"),
                   "origin": "custom_dax" if name == "custom_dax" else f"recipe:{name}",
                   "recipe": name, "args": args, "cost": 0}

    if name == "measure_formula":
        return {**entry, **_measure_formula(state, args)}
    if name == "split_units_vs_price":
        return {**entry, **_split(state, signal, evidence, args)}

    built = build(name, args, state, signal, evidence)
    if "refused" in built:
        return {**entry, "status": "rejected", "stage": "arguments", "reason": built["refused"]}
    entry["dimension"] = built.get("dimension")
    if "reuse" in built:
        rows, completeness, extra = _shown(name, list(built["rows"]), state, signal)
        return {**entry, "status": "cache_hit", "source": built["reuse"], "rows": rows,
                "row_count": len(built["rows"]), "completeness": completeness, **extra}

    dax = built["dax"]
    entry["dax"] = dax
    # Without the contract hint: the scope must be provable from the DAX.
    reasons = validate_one(dax, state.get("model_metadata") or {})
    reasons += validate_comparable_scope(dax, state)
    if reasons:
        return {**entry, "status": "rejected", "stage": "validator", "reason": "; ".join(reasons)}

    key = dax_hash(dax)
    cached = cache.get(key)
    if cached:
        status = "cache_hit" if cached.get("status") == "success" else "cache_hit_failed"
        rows, error = list(cached.get("rows") or []), str(cached.get("error") or "")
    else:
        if budget is not None:
            if budget.queries <= 0:
                return {**entry, "status": "budget_refused",
                        "reason": "no queries left for this finding"}
            if name == "custom_dax" and budget.custom_dax <= 0:
                return {**entry, "status": "budget_refused",
                        "reason": "no custom queries left for this finding"}
            budget.queries -= 1
            if name == "custom_dax":
                budget.custom_dax -= 1
        entry["cost"] = 1
        item = _execute(state, dax, f"{signal.get('id')}_recipe_{name}_{key[:8]}")
        ok = item.get("status") == "success"
        status = "success" if ok else "failed"
        rows = clean_rows(pbi.extract_rows(item.get("result", {}))) if ok else []
        error = "" if ok else str(item.get("error") or "unknown error")
        cache[key] = {"status": status, "rows": rows, "error": error, "dax": dax,
                      "contract_hint": built.get("contract_hint"), "source": entry["origin"]}
    if status in ("failed", "cache_hit_failed"):
        return {**entry, "status": status, "error": error}
    shown, completeness, extra = _shown(name, rows, state, signal)
    return {**entry, "status": status, "rows": shown, "row_count": len(rows),
            "completeness": completeness, **extra}
