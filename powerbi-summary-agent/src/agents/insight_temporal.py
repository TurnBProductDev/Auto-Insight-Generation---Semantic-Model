"""Insight branch - Temporal grain gate + series scan + drill (Phase 2, deterministic).

Runs after normalization and before the evidence catalog. It decides whether the
model exposes a **valid business time axis** and, if so:

  1. scans one comparable primary/volume series over it (a "period" cascade level),
  2. reconciles the series against the scanned grand total,
  3. drills the single worst-declining period by the metadata **primary dimension**
     so the story can say WHERE, not just WHEN ("October's decline was concentrated
     in Technology").

Why a gate: a date column can be a *load/posting* date, not business activity - on
the working model `UPDATED_DATE` concentrates ~all revenue on month-end, so mining
it invents anomalies. The gate judges each axis using the metadata-designated
**primary value metric** (not the largest numeric column), detects the grain
(month/week/quarter/period), excludes null members, and falls back to the finest
valid grain (here `DOC_MONTH`). Live probes are capped (`insight_temporal_max_probes`)
and a grain column can be forced (`insight_temporal_grain_column`).

Executes with the pre-fetched `state["pbi_token"]` (post-fork safe).
"""

from __future__ import annotations

import re

from ..tools import file_io
from ..tools import powerbi_executor as pbi
from ..utils.json_utils import clean_rows
from ..utils.logger import RunLogger
from .dax_validator import validate_one
from .insight_scan_templates import build_temporal_scan, build_gap_probe, shape_from_profile
from .scope_validator import validate_comparable_scope
from .semantic_profiler import bundle_phase

_PERIOD_TOKENS = {"month", "week", "period", "quarter", "wk", "mth", "mon", "qtr", "doc"}
_NUMERIC_HINTS = ("int", "number", "decimal", "double", "single", "currency")
_GRAIN_TOKENS = [("quarter", {"quarter", "qtr", "q"}), ("month", {"month", "mth", "mon", "doc"}),
                 ("week", {"week", "wk"}), ("day", {"day", "date"})]
_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def label_period(value, is_month: bool) -> str:
    """Human period label ('October') while callers keep the raw value for
    filtering and fingerprints. Month-name mapping assumes 1=January; disabled
    unless the axis looks like calendar months (ints 1..12)."""
    if is_month:
        try:
            n = int(float(value))
            if 1 <= n <= 12:
                return _MONTHS[n - 1]
        except (TypeError, ValueError):
            pass
    return str(value)


def looks_monthly(values) -> bool:
    ints = []
    for v in values:
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float)) and float(v).is_integer():
            ints.append(int(v))
        else:
            return False
    return bool(ints) and min(ints) >= 1 and max(ints) <= 12


def _is_date_dim(dim: dict) -> bool:
    return (dim.get("category") == "date"
            or "date" in str(dim.get("data_type", "")).lower())


def _is_period_numeric(dim: dict) -> bool:
    dt = str(dim.get("data_type", "")).lower()
    numeric = any(t in dt for t in _NUMERIC_HINTS)
    toks = set(re.findall(r"[a-z]+", str(dim.get("column", "")).lower()))
    return numeric and bool(toks & _PERIOD_TOKENS)


def _detect_grain(dim: dict) -> str:
    toks = set(re.findall(r"[a-z]+", str(dim.get("column", "")).lower()))
    for grain, keys in _GRAIN_TOKENS:
        if toks & keys:
            return grain
    return "period"


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _primary_aliases(profile: dict) -> tuple[str | None, str | None]:
    """The metadata-designated primary value metric's current and change aliases."""
    bundle = profile.get("primary_value_bundle") or {}
    cur = bundle_phase(bundle, "current") or {}
    chg = bundle_phase(bundle, "change") or {}
    return cur.get("alias"), chg.get("alias")


def _row_value(row: dict, alias: str | None):
    if not alias:
        return None
    if alias in row:
        return row.get(alias)
    for k, v in row.items():
        kk = k.split("[")[-1].rstrip("]") if "[" in k else k
        if kk == alias:
            return v
    return None


def _col_total(rows: list, alias: str) -> float | None:
    vals = [abs(_row_value(r, alias)) for r in rows if _is_num(_row_value(r, alias))]
    return sum(vals) if vals else None


def _max_bucket_share(rows: list, alias: str | None) -> float | None:
    vals = [abs(_row_value(r, alias)) for r in rows if _is_num(_row_value(r, alias))]
    s = sum(vals)
    return (max(vals) / s) if s > 0 and vals else None


def _largest_numeric_alias(rows: list) -> str | None:
    totals: dict = {}
    for r in rows:
        for k, v in r.items():
            if _is_num(v):
                totals[k] = totals.get(k, 0.0) + abs(v)
    return max(totals, key=totals.get) if totals else None


def _grand_total(clean: dict, alias: str | None) -> float | None:
    if not alias:
        return None
    for q in clean.get("queries", []):
        if q.get("status") != "success":
            continue
        if (q.get("contract_hint", {}) or {}).get("coverage_kind") == "grand_total":
            v = _row_value((q.get("rows") or [{}])[0], alias)
            if _is_num(v):
                return v
    return None


def _find_scanned_table(clean: dict, dim: dict) -> dict | None:
    ref = dim.get("reference")
    for q in clean.get("queries", []):
        if q.get("status") != "success":
            continue
        groupings = (q.get("contract_hint", {}) or {}).get("grouping", []) or []
        refs = [g.get("reference") for g in groupings if isinstance(g, dict)]
        if ref in refs:
            return q
    return None


def _drill_worst_period(state: dict, profile: dict, grain_dim: dict, rows: list,
                        cur_alias: str, chg_alias: str, is_month: bool,
                        log: RunLogger) -> dict | None:
    """Break the single worst-declining period down by the metadata primary
    dimension, so the story gains a WHERE. One bounded probe, best-effort."""
    shape = shape_from_profile(profile, state)
    dims = shape.get("dimensions") or []
    primary_dim = dims[0] if dims else None
    if not primary_dim or not chg_alias:
        return None
    axis_col = grain_dim.get("column")
    scored = [(r, _row_value(r, chg_alias), _row_value(r, axis_col)) for r in rows]
    scored = [(r, c, a) for r, c, a in scored if _is_num(c) and a is not None]
    if not scored:
        return None
    worst = min(scored, key=lambda t: t[1])   # most negative change
    if worst[1] >= 0:
        return None                            # no decline period to attribute
    month_raw = worst[2]
    population = [str(v) for v in state.get("insight_comparable_population", []) or []]
    max_rows = max(5, int(state.get("max_rows_per_query", 15)))
    probe = build_gap_probe(shape, grain_dim, month_raw, primary_dim,
                            population, max_rows, "comparable")
    reasons = validate_one(probe["dax"], state.get("model_metadata", {}))
    reasons += validate_comparable_scope(probe["dax"], state, probe.get("contract_hint"))
    if reasons:
        log.info(f"  period drill skipped (invalid): {'; '.join(reasons)[:120]}")
        return None
    try:
        res = pbi.execute_python(state["workspace_id"], state["dataset_id"],
                                 [{"name": "period_drill", **probe}], token=state.get("pbi_token"))
    except Exception as exc:  # noqa: BLE001
        log.info(f"  period drill exec error: {exc}")
        return None
    item = res.get("period_drill", {})
    if item.get("status") != "success":
        return None
    drill_rows = clean_rows(pbi.extract_rows(item.get("result", {})))
    seg_col = primary_dim.get("column")
    segs = [(str(_row_value(r, seg_col)), _row_value(r, chg_alias)) for r in drill_rows]
    segs = [(s, c) for s, c in segs if _is_num(c)]
    if not segs:
        return None
    total = sum(c for _, c in segs) or worst[1]
    top = sorted(segs, key=lambda sc: abs(sc[1]), reverse=True)[: int(state.get("insight_period_drill_top", 3))]
    top_segments = [{"segment": s, "change": round(float(c), 2),
                     "share_pct": (round(c / total * 100.0, 2) if total else None)}
                    for s, c in top]
    return {
        "grain_column": grain_dim.get("reference"),
        "dimension": primary_dim.get("reference"),
        "period_raw": str(month_raw),
        "period_label": label_period(month_raw, is_month),
        "period_change": round(float(worst[1]), 2),
        "top_segments": top_segments,
    }


def run(state: dict) -> dict:
    log = RunLogger(state)
    if not state.get("insight_temporal_enabled", True):
        verdict = {"enabled": False, "grain": "disabled",
                   "reason": "temporal level disabled by config", "checks": []}
        file_io.write_json(state, "insight_temporal_verdict.json", verdict)
        return {"insight_temporal_verdict": verdict, "insight_temporal_gated_tables": [],
                **log.updates()}

    profile = state.get("semantic_model_profile", {}) or {}
    clean = state.get("insight_clean_data", {"queries": []})
    time_dims = profile.get("time_dimensions", []) or []
    batch_share = float(state.get("insight_temporal_batch_share", 0.5))
    min_periods = int(state.get("insight_temporal_min_periods", 6))
    max_probes = max(1, int(state.get("insight_temporal_max_probes", 3)))
    recon_tol = float(state.get("insight_temporal_recon_tolerance_pct", 2.0)) / 100.0
    override = str(state.get("insight_temporal_grain_column", "") or "").strip()
    cur_alias, chg_alias = _primary_aliases(profile)

    checks, gated = [], []

    # 1) Judge each scanned DATE axis using the PRIMARY value metric (fall back to
    #    the largest column only if the primary alias isn't present). A single
    #    bucket over `batch_share` of that metric is a load/posting-date fingerprint.
    for dim in time_dims:
        if not _is_date_dim(dim):
            continue
        tbl = _find_scanned_table(clean, dim)
        if not tbl:
            continue
        alias = cur_alias if any(_is_num(_row_value(r, cur_alias)) for r in tbl["rows"]) \
            else _largest_numeric_alias(tbl["rows"])
        share = _max_bucket_share(tbl["rows"], alias)
        invalid = share is not None and share > batch_share
        checks.append({"column": dim.get("reference"), "grain": "date",
                       "metric": alias, "max_bucket_share": share,
                       "verdict": "batch_load_date" if invalid else "ok"})
        if invalid:
            gated.append(tbl.get("query_name"))

    # 2) Candidate business axes: an override wins; else numeric month/week/period
    #    columns ranked by score. Live probes are capped.
    candidates = [d for d in time_dims if _is_period_numeric(d)]
    if override:
        candidates = [d for d in time_dims if d.get("reference") == override
                      or d.get("column") == override] or candidates
    candidates = sorted(candidates,
                        key=lambda d: (d.get("score", 0), d.get("table") == profile.get("fact_table")),
                        reverse=True)

    chosen, period_table, drill, probes = None, None, None, 0
    for dim in candidates:
        if probes >= max_probes:
            checks.append({"column": dim.get("reference"), "verdict": "probe_budget_exhausted"})
            break
        query = build_temporal_scan(profile, state, dim)
        if not query:
            continue
        reasons = validate_one(query["dax"], state.get("model_metadata", {}))
        reasons += validate_comparable_scope(query["dax"], state, query.get("contract_hint"))
        if reasons:
            checks.append({"column": dim.get("reference"), "verdict": "invalid_dax",
                           "reason": "; ".join(reasons)})
            continue
        probes += 1
        try:
            res = pbi.execute_python(state["workspace_id"], state["dataset_id"], [query],
                                     token=state.get("pbi_token"))
        except Exception as exc:  # noqa: BLE001
            checks.append({"column": dim.get("reference"), "verdict": "exec_error",
                           "reason": str(exc)[:200]})
            continue
        item = res.get(query["name"], {})
        if item.get("status") != "success":
            checks.append({"column": dim.get("reference"), "verdict": "exec_failed",
                           "reason": str(item.get("error"))[:200]})
            continue
        rows_all = clean_rows(pbi.extract_rows(item.get("result", {})))
        axis_col = dim.get("column")
        rows = [r for r in rows_all if _row_value(r, axis_col) is not None]  # drop null members
        nulls = len(rows_all) - len(rows)
        alias = cur_alias if any(_is_num(_row_value(r, cur_alias)) for r in rows) \
            else _largest_numeric_alias(rows)
        share = _max_bucket_share(rows, alias)
        grand = _grand_total(clean, cur_alias)
        series_sum = _col_total_signed(rows, cur_alias)
        reconciled = (grand is None or series_sum is None
                      or abs(series_sum - grand) <= recon_tol * max(abs(grand), 1.0))
        grain = _detect_grain(dim)
        if len(rows) < min_periods:
            verdict_v = f"too_few_periods({len(rows)}<{min_periods})"
        elif alias is None:
            verdict_v = "no_values"
        elif share is not None and share > batch_share:
            verdict_v = "batch_concentration"
        elif not reconciled:
            verdict_v = "series_does_not_reconcile"
        else:
            verdict_v = "ok"
        checks.append({"column": dim.get("reference"), "grain": grain, "metric": alias,
                       "rows": len(rows), "null_members": nulls,
                       "max_bucket_share": share, "reconciled": reconciled,
                       "verdict": verdict_v})
        if verdict_v == "ok":
            chosen = dim
            hint = dict(query["contract_hint"])
            hint["grain"] = grain
            period_table = {"query_name": query["name"], "purpose": query["purpose"],
                            "status": "success", "rows": rows, "dax": query["dax"],
                            "contract_hint": hint}
            if state.get("insight_period_drill", True):
                drill = _drill_worst_period(state, profile, dim, rows, cur_alias, chg_alias,
                                            looks_monthly([_row_value(r, axis_col) for r in rows]), log)
            break

    updates: dict = {"insight_temporal_gated_tables": gated}
    if chosen and period_table:
        queries = list(clean.get("queries", []))
        queries.append(period_table)
        clean_out = {"query_count": len(queries),
                     "successful": int(clean.get("successful", 0)) + 1,
                     "failed": clean.get("failed", 0), "queries": queries}
        file_io.write_json(state, "insight_clean_data.json", clean_out)
        updates["insight_clean_data"] = clean_out
        grain = _detect_grain(chosen)
        verdict = {"enabled": True, "grain": grain, "level": "period",
                   "column": chosen.get("reference"), "table": period_table["query_name"],
                   "primary_metric": cur_alias, "gated_date_tables": gated,
                   "drill": drill, "checks": checks, "probes_used": probes,
                   "reason": f"validated business {grain} grain {chosen.get('reference')}"}
        if drill:
            updates["insight_temporal_drill"] = drill
        seg_note = (f"; worst period {drill['period_label']} concentrated in "
                    f"{drill['top_segments'][0]['segment']}" if drill and drill.get("top_segments") else "")
        log.info(f"Temporal gate: using {chosen.get('reference')} ({grain}, "
                 f"{len(period_table['rows'])} periods, reconciled); gated {len(gated)} "
                 f"load-date table(s){seg_note}.")
    else:
        verdict = {"enabled": True, "grain": "disabled", "level": "period", "column": None,
                   "gated_date_tables": gated, "checks": checks, "probes_used": probes,
                   "reason": ("no valid business time axis found - sub-annual "
                              "monitoring disabled (only a load/posting-date column exists)")}
        log.info("Temporal gate: no valid business time grain; period level disabled "
                 f"(gated {len(gated)} load-date table(s)). Report will carry the caveat.")

    updates["insight_temporal_verdict"] = verdict
    file_io.write_json(state, "insight_temporal_verdict.json", verdict)
    return {**updates, **log.updates()}


def _col_total_signed(rows: list, alias: str | None) -> float | None:
    vals = [_row_value(r, alias) for r in rows]
    vals = [v for v in vals if _is_num(v)]
    return sum(vals) if vals else None
