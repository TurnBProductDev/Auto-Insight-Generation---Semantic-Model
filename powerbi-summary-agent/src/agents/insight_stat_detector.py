"""Insight branch - Stat Detector (deterministic, no LLM).

Sits between insight_normalize and insight_signal_detector. For every
successful scan table it computes, in pure Python:

  * contribution-to-change per segment (the variance bridge),
  * share-of-total and top-N concentration,
  * robust outlier scores on category distributions,
  * trend slope + simple change-point detection on date/period series,
  * reconciliation checks (change = current - prior row-wise; breakdown
    sums vs grand totals; zero-prior bases; non-finite values;
    non-differentiating metrics) - failures pre-tagged data_quality.

Output is a ranked candidate list (impact x significance scored) the
signal detector selects from, so impact numbers are computed facts, not
LLM estimates. Column roles are inferred numerically (a change column is
one that reconciles row-wise against two others), never from hardcoded
names - the node is model-agnostic by construction.

Metrics are additionally classified additive vs ratio-like by checking
whether any full breakdown's sum reconciles to the metric's grand total
(additive) or the grand total instead sits inside the row-value range
like an average (ratio). Shares of the grand total are only computed for
additive metrics - dividing a segment's ratio value by a grand-total
ratio produces absurd percentages that would drown the real movers.

The node never raises: any unexpected error degrades to an empty
candidate list and the LLM detector falls back to reading raw scan rows.
"""

import math
from datetime import datetime, timedelta

from ..tools import file_io
from ..utils.logger import RunLogger

_EPS = 1e-9

_MONTHS = ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def _looks_monthly(values) -> bool:
    ints = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not float(v).is_integer():
            return False
        ints.append(int(v))
    return bool(ints) and min(ints) >= 1 and max(ints) <= 12


def _period_label(value, is_month: bool) -> str:
    """'October' for a calendar month; the raw value otherwise. The raw value is
    kept as the fingerprint anchor - only the display label is humanized."""
    if is_month:
        try:
            n = int(float(value))
            if 1 <= n <= 12:
                return _MONTHS[n - 1]
        except (TypeError, ValueError):
            pass
    return str(value)


# --- value / column helpers ----------------------------------------------------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _finite(v) -> bool:
    return _is_num(v) and math.isfinite(v)


def _safe(v, digits: int = 4):
    """A candidate-payload-safe number: finite floats only, else None."""
    return round(float(v), digits) if _finite(v) else None


def _fmt(v) -> str:
    """Compact human-readable number for detail strings."""
    if not _finite(v):
        return str(v)
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e3:
        return f"{v / 1e3:.1f}K"
    return f"{v:.2f}"


_NUM_SENTINELS = {"infinity": math.inf, "-infinity": -math.inf, "nan": math.nan}


def _coerce_sentinels(rows: list) -> list:
    """Power BI serializes non-finite numbers as the strings "Infinity" /
    "-Infinity" / "NaN". Left as strings they make a numeric column look
    categorical, so segment labels get polluted with raw numbers. Coerce them
    to real floats; the _finite guards then exclude them from math and the
    non_finite_values check flags them."""
    out = []
    for r in rows:
        clean = {}
        for k, v in r.items():
            if isinstance(v, str) and v.strip().lower() in _NUM_SENTINELS:
                clean[k] = _NUM_SENTINELS[v.strip().lower()]
            else:
                clean[k] = v
        out.append(clean)
    return out


def _parse_date(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "").strip())
        except ValueError:
            return None
    return None


def _classify_columns(rows: list) -> dict:
    """Split columns into label / numeric / date / period roles by inspecting
    values only (never names). A 'period' column is an all-unique run of
    consecutive small integers (month 1..7, week 1..52...) - an axis, not a
    measure."""
    cols = {}
    for row in rows:
        for k in row:
            cols.setdefault(k, []).append(row.get(k))

    label_cols, numeric_cols, date_col, period_col = [], [], None, None
    for k, vals in cols.items():
        present = [v for v in vals if v is not None]
        if not present:
            label_cols.append(k)
            continue
        if all(_is_num(v) for v in present):
            ints = [v for v in present if _finite(v)]
            is_period = (
                len(ints) == len(present) and len(ints) >= 2
                and all(float(v).is_integer() for v in ints)
                and len(set(ints)) == len(ints)
                and 0 <= min(ints) and max(ints) <= 3000
                and int(max(ints) - min(ints)) + 1 == len(ints)
            )
            if is_period and period_col is None:
                period_col = k
            else:
                numeric_cols.append(k)
        elif all(_parse_date(v) is not None for v in present) and date_col is None:
            date_col = k
        else:
            label_cols.append(k)
    return {"labels": label_cols, "numerics": numeric_cols,
            "date": date_col, "period": period_col}


def _segment_of(row: dict, label_cols: list) -> str:
    parts = [str(row.get(c)) for c in label_cols if row.get(c) is not None]
    return " | ".join(parts) if parts else "overall"


def _column(rows: list, col: str) -> list:
    return [r.get(col) for r in rows]


# --- role inference -------------------------------------------------------------

def _find_triples(rows: list, numeric_cols: list, rel_tol: float) -> list:
    """(current, prior, change) triples found numerically: chg ~= cur - prev on
    at least 60% of finite rows (violating rows are reported separately as
    data-quality evidence, so the bar must tolerate some bad rows)."""
    triples = []
    if not rows:
        return triples
    for chg in numeric_cols:
        for cur in numeric_cols:
            if cur == chg:
                continue
            for prev in numeric_cols:
                if prev in (chg, cur):
                    continue
                ok = bad = 0
                for r in rows:
                    c, p, g = r.get(cur), r.get(prev), r.get(chg)
                    if not (_finite(c) and _finite(p) and _finite(g)):
                        continue
                    scale = max(abs(c), abs(p), abs(g), 1.0)
                    if abs((c - p) - g) <= rel_tol * scale:
                        ok += 1
                    else:
                        bad += 1
                total = ok + bad
                if total and ok / total >= 0.6 and ok >= 1:
                    triples.append({"current": cur, "prior": prev, "change": chg,
                                    "ok_rows": ok, "bad_rows": bad})
    # A change column can only belong to one triple; keep the best fit.
    best = {}
    for t in triples:
        cur_best = best.get(t["change"])
        if cur_best is None or t["ok_rows"] > cur_best["ok_rows"]:
            best[t["change"]] = t

    # cur - prev = chg implies cur - chg = prev, so every real triple also
    # validates with the prior column playing the change role. Among
    # permutations of the same three columns keep the one whose change
    # column has the smallest typical magnitude - the difference is almost
    # always smaller than the levels it is computed from.
    def _med_abs(col: str) -> float:
        vals = sorted(abs(r[col]) for r in rows if _finite(r.get(col)))
        return vals[len(vals) // 2] if vals else 0.0

    groups = {}
    for t in best.values():
        key = frozenset((t["current"], t["prior"], t["change"]))
        groups.setdefault(key, []).append(t)
    kept = []
    for grp in groups.values():
        grp.sort(key=lambda t: (_med_abs(t["change"]), -t["ok_rows"]))
        kept.append(grp[0])
    return kept


def _contract_triples(contract: dict, numeric_cols: list) -> list:
    """Use construction-time metadata roles when available.

    Numerical inference remains the fallback for legacy/free-form artifacts,
    but metadata-templated queries know their current/prior/change identities
    exactly and must not be reinterpreted by magnitude.
    """
    grouped = {}
    for alias, role in (contract.get("metric_roles") or {}).items():
        if alias not in numeric_cols or not role.get("bundle_id") or not role.get("phase"):
            continue
        grouped.setdefault(role["bundle_id"], {})[role["phase"]] = alias
    out = []
    for bundle_id, phases in grouped.items():
        if all(p in phases for p in ("current", "prior", "change")):
            out.append({
                "current": phases["current"], "prior": phases["prior"],
                "change": phases["change"], "ok_rows": 0, "bad_rows": 0,
                "bundle_id": bundle_id,
                "semantic_role": (contract.get("metric_roles", {})
                                  .get(phases["change"], {}).get("semantic_role")),
                "family": (contract.get("metric_roles", {})
                           .get(phases["change"], {}).get("family")),
            })
    return out


def _rate_volume_split(row: dict, rev_tr: dict, vol_tr: dict) -> dict:
    """Exact two-factor split of a revenue change into a volume effect and a
    rate effect, using the identity R = S x (R/S):

        volume effect = (S1 - S0) * (R0 / S0)      [rate held at prior]
        rate effect   = S1 * (R1/S1 - R0/S0)       [volume held at current]
        volume + rate = R1 - R0                     (exact, no residual)

    ``S`` is a same-table volume driver (quantity, transactions...) so R and S
    share one scope by construction. The implied rate R/S is used deliberately -
    the model's own price measure is a different construct and would leave a
    residual, breaking the exactness. There is NO mix term: at an aggregate
    grain the rate bucket already blends price and mix, and it is not
    separable without complete child-grain rows. This is a decomposition of
    HOW the movement split, not a causal attribution.
    """
    R1, R0 = row.get(rev_tr["current"]), row.get(rev_tr["prior"])
    S1, S0 = row.get(vol_tr["current"]), row.get(vol_tr["prior"])
    if not all(_finite(x) for x in (R1, R0, S1, S0)):
        return None
    if abs(S0) <= _EPS or abs(S1) <= _EPS:
        return None  # rate R/S undefined where the driver is zero
    p1, p0 = R1 / S1, R0 / S0
    volume_effect = (S1 - S0) * p0
    rate_effect = S1 * (p1 - p0)
    dR = R1 - R0
    reconciled = abs((volume_effect + rate_effect) - dR) <= 1e-6 * max(abs(dR), 1.0)
    return {
        "driver": vol_tr["change"],
        "rate_of": f"{rev_tr['current']} / {vol_tr['current']}",
        "revenue_change": _safe(dR),
        "volume_effect": _safe(volume_effect),
        "rate_effect": _safe(rate_effect),
        "rate_current": _safe(p1),
        "rate_prior": _safe(p0),
        "reconciled": bool(reconciled),
        "basis": "exact price/volume split; rate = revenue per unit of driver "
                 "(blends price and mix at this grain); decomposition, not cause",
    }


def _robust_z(values: list) -> list:
    """Robust z-scores (median/MAD, falling back to mean/std). Returns [] when
    the spread is zero."""
    med = sorted(values)[len(values) // 2]
    mad = sorted(abs(v - med) for v in values)[len(values) // 2]
    if mad > _EPS:
        return [(v - med) / (1.4826 * mad) for v in values]
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(var)
    if std > _EPS:
        return [(v - mean) / std for v in values]
    return []


def _point_robust_z(value, ref: list):
    """Robust z of ONE value against a reference list (median/MAD, mean/std
    fallback). Returns None on a too-small or perfectly FLAT reference so callers
    handle a constant baseline explicitly (a material break from a flat history is
    detected on materiality, not a z-score that would be infinite/undefined)."""
    ref = [v for v in ref if _finite(v)]
    if len(ref) < 3 or not _finite(value):
        return None
    med = sorted(ref)[len(ref) // 2]
    mad = sorted(abs(v - med) for v in ref)[len(ref) // 2]
    if mad > _EPS:
        return (value - med) / (1.4826 * mad)
    mean = sum(ref) / len(ref)
    std = math.sqrt(sum((v - mean) ** 2 for v in ref) / len(ref))
    if std > _EPS:
        return (value - mean) / std
    return None


# --- the detector ---------------------------------------------------------------

class _Detector:
    def __init__(self, state: dict, log: RunLogger):
        self.log = log
        self.z_cutoff = float(state.get("insight_stat_z_cutoff", 3.0))
        self.conc_pct = float(state.get("insight_stat_concentration_pct", 50.0))
        self.recon_tol_pct = float(state.get("insight_stat_recon_tolerance_pct", 2.0))
        self.trend_window = max(2, int(state.get("insight_stat_trend_window", 3)))
        self.row_cap = max(2, int(state.get("max_rows_per_query", 15)))
        self.business = {}       # key -> candidate (dedup keeps best score)
        self.data_quality = {}
        self.grand_totals = {}   # column name -> value, from 1-row label-less tables
        self.additive = set()    # metrics whose breakdowns sum to the grand total
        self.ratio = set()       # metrics whose grand total behaves like an average
        self.canon = {}          # synonym metric name -> canonical name
        self.contracts = state.get("insight_evidence_contracts", {})
        # Phase 2 temporal level
        self.period_top = max(1, int(state.get("insight_period_top_movers", 4)))
        self.period_recent = max(1, int(state.get("insight_period_recent_window", 12)))
        self.gated_tables = set(state.get("insight_temporal_gated_tables", []) or [])
        self.drill = state.get("insight_temporal_drill", {}) or {}
        # Phase 3 recent-week level
        self.week_materiality_pct = float(state.get("insight_week_materiality_pct", 3.0))
        self.week_z_cutoff = float(state.get("insight_week_z_cutoff", 2.5))
        self.recent_week_drivers = state.get("insight_recent_week_drivers", {}) or {}
        # Phase 3b rolling-week: always-emitted raw observation (decision #8),
        # regardless of whether this run's reading clears the significance gate.
        self.rolling_observation = None

    # -- candidate plumbing --

    def _add(self, kind: str, cand: dict):
        cand["kind"] = kind
        # No table in the key: scan plans often run near-identical queries
        # (gainers/losers over the same slice) and the same finding must not
        # appear once per table. Metric goes through the synonym map: models
        # frequently expose the same measure under two names, and both would
        # otherwise emit one candidate each for every finding.
        key = (cand["type"], self.canon.get(cand.get("metric"), cand.get("metric")),
               cand.get("segment"))
        pool = self.data_quality if kind == "data_quality" else self.business
        old = pool.get(key)
        if old is None or cand["score"] > old["score"]:
            pool[key] = cand

    def _share(self, value, metric: str, fallback_total=None):
        """Percent share for `metric`. Returns (share_pct, basis).

        Proven-additive metrics share against their grand total. If a grand
        total EXISTS but the metric never reconciled to it, no basis is
        trustworthy (it is a ratio, or every breakdown was truncated) - return
        no share rather than a misleading one. The table-sum fallback only
        applies when no grand total was scanned at all."""
        if metric in self.ratio or not _finite(value):
            return None, None
        total = self.grand_totals.get(metric)
        if metric in self.additive and _finite(total) and abs(total) > _EPS:
            return value / total * 100.0, f"grand_total:{metric}"
        if _finite(total):
            return None, None
        if _finite(fallback_total) and abs(fallback_total) > _EPS:
            return value / fallback_total * 100.0, "table_sum"
        return None, None

    # -- pass 1: collect grand totals --

    def collect_totals(self, tables: list):
        # A single row with no text labels is a totals row. An incidental
        # date column (e.g. a last-refresh timestamp packed into the KPI
        # query) does not disqualify it - only a real segment label does.
        for t in tables:
            rows = t["rows"]
            roles = t["roles"]
            if len(rows) == 1 and not roles["labels"]:
                for col in roles["numerics"]:
                    v = rows[0].get(col)
                    if _finite(v):
                        self.grand_totals[col] = v
        # Metrics with (near-)identical grand totals are the same measure
        # published under two names; collapse them onto one canonical name so
        # each finding is emitted once.
        by_value = {}
        for col in sorted(self.grand_totals):   # sorted: deterministic canon pick
            v = self.grand_totals[col]
            if abs(v) <= _EPS:
                continue                        # zeros collide by accident
            match = next((rep for rep, rv in by_value.items()
                          if abs(v - rv) <= 1e-9 * max(abs(v), abs(rv))), None)
            if match is None:
                by_value[col] = v
            else:
                self.canon[col] = match

    # -- pass 2: additive vs ratio metrics --

    def classify_metrics(self, tables: list):
        """Vote per metric across full (non-truncated, non-windowed) label
        breakdowns: sum reconciles to the grand total -> additive; grand
        total sits inside the row-value range while the sum overshoots ->
        ratio-like (an average). An additive vote anywhere wins."""
        tol = self.recon_tol_pct / 100.0
        for t in tables:
            rows, roles = t["rows"], t["roles"]
            contract = t.get("contract") or {}
            if contract.get("contract_source") != "parsed_dax_and_rows":
                if (contract.get("completeness") != "complete"
                        or contract.get("population_status") != "comparable"):
                    continue
            if not roles["labels"] or roles["date"] or roles["period"]:
                continue
            if len(rows) >= self.row_cap:   # likely truncated: sum unreliable
                continue
            for col in roles["numerics"]:
                g = self.grand_totals.get(col)
                if not _finite(g):
                    continue
                vals = [r.get(col) for r in rows if _finite(r.get(col))]
                if len(vals) < 2:
                    continue
                s = sum(vals)
                if abs(s - g) <= tol * max(abs(g), 1.0):
                    self.additive.add(col)
                elif (len(vals) >= 5
                      and min(vals) - _EPS <= g <= max(vals) + _EPS
                      and abs(s) > 1.5 * abs(g)):
                    # average-like: total inside the row range while the sum
                    # overshoots it. Needs a real sample - a handful of rows
                    # can land there by chance and wrongly mute a metric.
                    self.ratio.add(col)
        self.ratio -= self.additive

    # -- analyses --

    def bridge(self, t: dict):
        """Contribution-to-change per segment for every (cur, prev, chg) triple."""
        rows, roles = t["rows"], t["roles"]
        if not roles["labels"] or len(rows) < 2:
            return

        # The price/volume split is only meaningful decomposing the table's
        # primary VALUE metric (revenue) by a volume driver (quantity) - never
        # the reverse ("decompose quantity by revenue" is nonsense). The value
        # metric is the additive change column of largest magnitude; monetary
        # totals dominate unit counts, so this picks revenue without needing
        # column names. Only proven-additive changes qualify (see overall_split).
        add_changes = [tr2["change"] for tr2 in t["triples"] if tr2["change"] in self.additive]

        def _mag(col: str) -> float:
            g = self.grand_totals.get(col)
            if _finite(g):
                return abs(g)
            return sum(abs(r[col]) for r in rows if _finite(r.get(col)))

        semantic_values = [tr2["change"] for tr2 in t["triples"]
                           if tr2.get("semantic_role") == "value"]
        primary_value = semantic_values[0] if semantic_values else (
            max(add_changes, key=_mag) if add_changes else None)

        for tr in t["triples"]:
            chg = tr["change"]
            # Contribution-to-change only makes sense for additive change
            # columns; a ratio's movement doesn't decompose across segments.
            if chg in self.ratio:
                continue
            finite_rows = [r for r in rows if _finite(r.get(chg))]
            if len(finite_rows) < 2:
                continue
            table_sum = sum(r[chg] for r in finite_rows)
            abs_sum = sum(abs(r[chg]) for r in finite_rows)
            ranked = sorted(finite_rows, key=lambda r: abs(r[chg]), reverse=True)
            for r in ranked[:4]:
                seg = _segment_of(r, roles["labels"])
                share, basis = self._share(r[chg], chg, table_sum)
                if share is not None:
                    score = abs(share)
                elif abs_sum > _EPS:
                    # scale-free fallback: share of the table's absolute change
                    score = abs(r[chg]) / abs_sum * 100.0 * 0.8
                else:
                    score = 0.0
                cur_v, prev_v = r.get(tr["current"]), r.get(tr["prior"])
                cand = {
                    "type": "change_contribution",
                    "table": t["name"], "metric": chg, "segment": seg,
                    "impact_value": _safe(r[chg]),
                    "impact_share": _safe(share),
                    "share_basis": basis,
                    "significance": 1.0,
                    "score": score,
                    "detail": (f"{seg}: {chg} of {_fmt(r[chg])} "
                               f"(from {_fmt(prev_v)} to {_fmt(cur_v)})"
                               + (f", {share:.1f}% of the total change" if share is not None else "")),
                }
                # Attach an exact price/volume decomposition only to the primary
                # value metric, using same-table additive volume drivers
                # (quantity, transactions) with current+prior for this row.
                # Ratio drivers can't decompose a level change, so they're
                # excluded.
                splits = []
                if chg == primary_value:
                    for vol_tr in t["triples"]:
                        if vol_tr is tr or vol_tr["change"] not in self.additive:
                            continue
                        split = _rate_volume_split(r, tr, vol_tr)
                        if split and split["reconciled"]:
                            splits.append(split)
                if splits:
                    cand["rate_volume"] = splits
                    drv = splits[0]
                    if drv["volume_effect"] is not None and drv["rate_effect"] is not None:
                        cand["detail"] += (
                            f"; split: volume {_fmt(drv['volume_effect'])} / "
                            f"rate {_fmt(drv['rate_effect'])} (per {drv['driver']})")
                self._add("business", cand)

    def overall_split(self, tables: list) -> list:
        """Grand-total price/volume decomposition. Segment-grain tables rarely
        carry a revenue triple AND a quantity triple together, but a single-row
        comparable KPI table does. Splitting it gives the headline '+X revenue
        growth = +A volume + B rate' for the whole comparable base - exact, and
        safe because it comes from ONE scoped table (never the merged
        grand_totals_seen, whose columns can span different scopes)."""
        results = []
        for t in tables:
            rows, roles = t["rows"], t["roles"]
            if len(rows) != 1 or roles["labels"]:
                continue
            row = rows[0]
            # Drivers must be PROVEN additive (a breakdown elsewhere reconciled
            # to their total), not merely "not proven ratio". A grand-totals
            # table also carries price levels and growth-% columns that never
            # appear in a breakdown, so they are never classified - requiring
            # additive membership keeps those out of the volume role.
            add = [tr for tr in t["triples"] if tr["change"] in self.additive]
            if len(add) < 2:
                continue

            def _mag(tr: dict) -> float:
                g = self.grand_totals.get(tr["change"])
                return abs(g) if _finite(g) else abs(row.get(tr["change"]) or 0.0)

            values = [tr for tr in add if tr.get("semantic_role") == "value"]
            rev_tr = values[0] if values else max(add, key=_mag)
            for vol_tr in [tr for tr in add if tr is not rev_tr
                           and (tr.get("semantic_role") in (None, "volume"))]:
                split = _rate_volume_split(row, rev_tr, vol_tr)
                if split and split["reconciled"]:
                    results.append({"table": t["name"], "metric": rev_tr["change"],
                                    "segment": "overall (comparable base)", **split})
        return results

    def concentration(self, t: dict):
        """Top-N share of the table total per value column."""
        rows, roles = t["rows"], t["roles"]
        if not roles["labels"] or len(rows) < 3:
            return
        # Skip change columns (movement, covered by the bridge) and prior-level
        # columns (last period's concentration is the same story as the current
        # one, told twice).
        skip_cols = ({tr["change"] for tr in t["triples"]}
                     | {tr["prior"] for tr in t["triples"]})
        for col in roles["numerics"]:
            if col in skip_cols or col in self.ratio:
                continue
            finite_rows = [r for r in rows if _finite(r.get(col)) and r.get(col) >= 0]
            if len(finite_rows) < 3 or len(finite_rows) < len(rows) * 0.8:
                continue
            table_sum = sum(r[col] for r in finite_rows)
            if table_sum <= _EPS:
                continue
            ranked = sorted(finite_rows, key=lambda r: r[col], reverse=True)
            top2 = ranked[:2]
            top2_sum = sum(r[col] for r in top2)
            share, basis = self._share(top2_sum, col, table_sum)
            if share is None or share < self.conc_pct:
                continue
            # A top-N table shows only its head; a share of that head's own
            # sum overstates concentration unless measured vs the grand total.
            if len(rows) >= self.row_cap and basis != f"grand_total:{col}":
                continue
            segment_members = sorted(_segment_of(r, roles["labels"]) for r in top2)
            segs = ", ".join(segment_members)
            self._add("business", {
                "type": "concentration",
                "table": t["name"], "metric": col, "segment": segs,
                # Preserve filter members independently from their display
                # label so targeted scans can issue a multi-value TREATAS.
                "segment_members": segment_members,
                "impact_value": _safe(top2_sum),
                "impact_share": _safe(share),
                "share_basis": basis,
                "significance": 1.0,
                "score": share * 0.6,   # concentration is state, not movement
                "detail": (f"top 2 of {len(finite_rows)} segments ({segs}) hold "
                           f"{_fmt(top2_sum)} = {share:.1f}% of {col}"),
            })

    def outliers(self, t: dict):
        """Robust z-score outliers per numeric column across segments.

        Columns that belong to a (current, prior, change) triple are skipped:
        their movement story is the bridge's job and their level story is
        concentration's - an outlier candidate there is always a duplicate.
        Z-scores earn their keep on standalone metrics (rates, ratios,
        counts) where no triple arithmetic exists."""
        rows, roles = t["rows"], t["roles"]
        if not roles["labels"] or len(rows) < 5:
            return
        triple_cols = set()
        for tr in t["triples"]:
            triple_cols |= {tr["current"], tr["prior"], tr["change"]}
        for col in roles["numerics"]:
            if col in triple_cols:
                continue
            finite_rows = [r for r in rows if _finite(r.get(col))]
            if len(finite_rows) < 5:
                continue
            zs = _robust_z([r[col] for r in finite_rows])
            if not zs:
                continue
            for r, z in zip(finite_rows, zs):
                if abs(z) < self.z_cutoff:
                    continue
                seg = _segment_of(r, roles["labels"])
                share, basis = self._share(r[col], col)
                self._add("business", {
                    "type": "outlier",
                    "table": t["name"], "metric": col, "segment": seg,
                    "impact_value": _safe(r[col]),
                    "impact_share": _safe(share),
                    "share_basis": basis,
                    "significance": _safe(min(abs(z) / (2 * self.z_cutoff), 1.0)),
                    "score": (abs(share) if share is not None else min(abs(z), 10.0)),
                    "detail": (f"{seg}: {col} = {_fmt(r[col])} is an outlier "
                               f"(robust z = {z:.1f}) vs {len(finite_rows)} peers"),
                })

    def trend(self, t: dict):
        """Slope + single change-point per numeric column over a date/period axis."""
        rows, roles = t["rows"], t["roles"]
        # The grain gate rejects load/posting-date axes (e.g. a month-end batch
        # date); mining a slope/change-point on such a table invents movement.
        if t["name"] in self.gated_tables:
            return
        # The recent-week series has its own dedicated composite detector; a
        # whole-series trend on 13 weeks would double-report the same story.
        if str((t.get("contract") or {}).get("coverage_kind", "")).startswith("recent_week"):
            return
        axis = roles["date"] or roles["period"]
        if axis is None:
            return
        keyed = []
        for r in rows:
            k = _parse_date(r.get(axis)) if roles["date"] else r.get(axis)
            if k is not None:
                keyed.append((k, r))
        keyed.sort(key=lambda kv: kv[0])
        n_min = max(2 * self.trend_window, 6)
        for col in roles["numerics"]:
            series = [(k, r[col]) for k, r in keyed if _finite(r.get(col))]
            n = len(series)
            if n < n_min:
                continue
            vals = [v for _, v in series]
            # slope + correlation on the index
            mean_i, mean_v = (n - 1) / 2.0, sum(vals) / n
            cov = sum((i - mean_i) * (v - mean_v) for i, v in enumerate(vals))
            var_i = sum((i - mean_i) ** 2 for i in range(n))
            var_v = sum((v - mean_v) ** 2 for v in vals)
            if var_v > _EPS:
                slope = cov / var_i
                r_corr = cov / math.sqrt(var_i * var_v)
                drift = slope * (n - 1)
                std_all = math.sqrt(var_v / n)
                if abs(r_corr) >= 0.7 and abs(drift) > _EPS:
                    share, basis = self._share(drift, col)
                    self._add("business", {
                        "type": "trend_slope",
                        "table": t["name"], "metric": col,
                        "segment": f"{series[0][0]} .. {series[-1][0]}",
                        "impact_value": _safe(drift),
                        "impact_share": _safe(share),
                        "share_basis": basis,
                        "significance": _safe(abs(r_corr)),
                        "score": (abs(share) * abs(r_corr) if share is not None
                                  else min(abs(drift) / (std_all + _EPS), 10.0) * abs(r_corr)),
                        "detail": (f"{col} drifts {_fmt(drift)} across {n} periods "
                                   f"(correlation {r_corr:.2f})"),
                    })
                # change-point: strongest mean shift, standardized by the
                # POOLED within-half spread. The global std is inflated by
                # the shift itself and caps the z near 2 for a clean level
                # change, which would make this check unable to ever fire.
                best = None
                for i in range(self.trend_window, n - self.trend_window + 1):
                    a, b = vals[:i], vals[i:]
                    m_a = sum(a) / len(a)
                    m_b = sum(b) / len(b)
                    var_a = sum((v - m_a) ** 2 for v in a) / len(a)
                    var_b = sum((v - m_b) ** 2 for v in b) / len(b)
                    pooled = math.sqrt((var_a * len(a) + var_b * len(b)) / n)
                    shift_z = min(abs(m_b - m_a) / (pooled + _EPS), 99.0)
                    if best is None or shift_z > best[0]:
                        best = (shift_z, i, m_b - m_a)
                if best and best[0] >= self.z_cutoff:
                    shift_z, i, shift = best
                    at = series[i][0]
                    self._add("business", {
                        "type": "trend_break",
                        "table": t["name"], "metric": col, "segment": str(at),
                        "impact_value": _safe(shift),
                        "impact_share": None, "share_basis": None,
                        "significance": _safe(min(shift_z / (2 * self.z_cutoff), 1.0)),
                        "score": min(shift_z, 10.0),
                        "detail": (f"{col} level shifts by {_fmt(shift)} around {at} "
                                   f"(shift z = {shift_z:.1f})"),
                    })

    def period(self, t: dict):
        """Which periods drove the comparable movement (Phase 2 temporal level).

        Runs only on a gate-validated ``period_series`` table. Attributes the
        movement to specific periods (top movers with a reconciled % of the total
        change), humanizes month labels, attaches the metadata-primary-dimension
        drill to the worst-declining period ("October's decline concentrated in
        Technology"), and flags temporal patterns (sustained runs, reversals,
        value/volume divergence). Distinct from ``trend`` (whole-series slope /
        one change-point). Null period members are excluded. Each finding keeps the
        RAW period value as its fingerprint anchor; only the display is humanized.
        """
        if (t.get("contract") or {}).get("coverage_kind") != "period_series":
            return
        rows, roles = t["rows"], t["roles"]
        axis = roles["period"] or roles["date"]
        if axis is None or not t["triples"]:
            return
        values = [tr for tr in t["triples"] if tr.get("semantic_role") == "value"]
        tr = values[0] if values else max(
            t["triples"],
            key=lambda x: sum(abs(r.get(x["change"])) for r in rows if _finite(r.get(x["change"]))))
        chg, cur, prev = tr["change"], tr["current"], tr["prior"]
        if chg in self.ratio:
            return

        def _axis_key(k):
            return _parse_date(k) if roles["date"] else k

        series = [(r.get(axis), r) for r in rows
                  if r.get(axis) is not None and _finite(r.get(chg))]
        series.sort(key=lambda kv: (_axis_key(kv[0]) is not None, _axis_key(kv[0])))
        if len(series) < 2:
            return
        is_month = _looks_monthly([k for k, _ in series])

        # Denominator: the period series is a complete breakdown of the change over
        # time, so its own total reconciles to the grand total. Use the grand total
        # when it agrees (proves reconciliation), else the series total.
        total_chg = sum(r[chg] for _, r in series)
        grand = self.grand_totals.get(chg)
        tol = self.recon_tol_pct / 100.0
        reconciled = (not _finite(grand)
                      or abs(total_chg - grand) <= tol * max(abs(grand), 1.0))
        denom = grand if (_finite(grand) and reconciled) else total_chg
        basis = "grand_total:period_reconciled" if (_finite(grand) and reconciled) else "period_series_total"

        recent = series[-self.period_recent:] if self.period_recent > 0 else series
        for raw, r in sorted(recent, key=lambda kv: abs(kv[1][chg]), reverse=True)[: self.period_top]:
            raw_s = (raw.date().isoformat() if isinstance(raw, datetime) else str(raw))
            label = _period_label(raw, is_month)
            share = (r[chg] / denom * 100.0) if denom and abs(denom) > _EPS else None
            detail = (f"{label}: {chg} of {_fmt(r[chg])} "
                      f"(from {_fmt(r.get(prev))} to {_fmt(r.get(cur))})"
                      + (f", {share:.1f}% of the total change" if share is not None else ""))
            cand = {
                "type": "period_change_contribution",
                "table": t["name"], "metric": chg, "segment": f"{axis}={raw_s}",
                "anchor": raw_s, "period_label": label,
                "impact_value": _safe(r[chg]), "impact_share": _safe(share),
                "share_basis": basis if share is not None else None,
                "significance": 1.0,
                "score": (abs(share) if share is not None
                          else abs(r[chg]) / (abs(total_chg) + _EPS) * 100.0),
                "detail": detail,
            }
            # Attach the WHERE drill to the period it was computed for.
            if self.drill and str(self.drill.get("period_raw")) == raw_s:
                segs = self.drill.get("top_segments", [])[:2]
                if segs:
                    cand["drill"] = self.drill
                    cand["detail"] += ("; concentrated in "
                                       + ", ".join(f"{s['segment']} ({_fmt(s['change'])})" for s in segs))
            self._add("business", cand)

        self._period_patterns(t, axis, chg, cur, prev, tr, series, is_month, denom, basis)

    def _period_patterns(self, t, axis, chg, cur, prev, tr, series, is_month, denom, basis):
        """Sustained runs, reversals, and value/volume divergence over the series."""
        def _lab(raw):
            return _period_label(raw, is_month)

        def _sign(v):
            return (v > _EPS) - (v < -_EPS)

        signs = [_sign(r[chg]) for _, r in series]

        # 1) Sustained run at the recent end (>= 3 same-signed periods).
        run_sign = signs[-1]
        run = 0
        for s in reversed(signs):
            if s == run_sign and s != 0:
                run += 1
            else:
                break
        if run >= 3 and run_sign != 0:
            seg = series[-run:]
            start, end = _lab(seg[0][0]), _lab(seg[-1][0])
            amount = sum(r[chg] for _, r in seg)
            share = (amount / denom * 100.0) if denom and abs(denom) > _EPS else None
            kind = "decline" if run_sign < 0 else "growth"
            # Fold the steepest months (with %) and the worst-period drill INTO the
            # run story, so the "where/which months" survives even if the LLM picks
            # this candidate as the headline over the individual month movers.
            steep = sorted(seg, key=lambda kv: abs(kv[1][chg]), reverse=True)[:2]
            steep_parts = []
            for raw, r in steep:
                pct = (f", {r[chg] / denom * 100.0:.0f}%" if denom and abs(denom) > _EPS else "")
                steep_parts.append(f"{_lab(raw)} ({_fmt(r[chg])}{pct})")
            detail = (f"{chg} {kind}d for {run} consecutive periods "
                      f"({start} to {end}), totalling {_fmt(amount)}"
                      + (f" ({share:.1f}% of the total change)" if share is not None else "")
                      + ("; steepest: " + ", ".join(steep_parts) if steep_parts else ""))
            run_raws = {str(raw) for raw, _ in seg}
            cand = {
                "type": f"period_sustained_{kind}", "table": t["name"], "metric": chg,
                "segment": f"{axis}:{start}..{end}", "anchor": f"{start}..{end}",
                "period_label": f"{start}-{end}",
                "impact_value": _safe(amount), "impact_share": _safe(share),
                "share_basis": basis if share is not None else None,
                "significance": 1.0, "score": (abs(share) if share is not None else 8.0) + run,
                "detail": detail,
            }
            if self.drill and str(self.drill.get("period_raw")) in run_raws:
                segs = self.drill.get("top_segments", [])[:2]
                if segs:
                    cand["drill"] = self.drill
                    cand["detail"] += (f"; {self.drill.get('period_label')}'s fall concentrated in "
                                       + ", ".join(f"{s['segment']} ({_fmt(s['change'])})" for s in segs))
            self._add("business", cand)

        # 2) Most recent reversal (sign flip) in the recent window.
        flip = None
        for i in range(len(signs) - 1, 0, -1):
            if signs[i] != 0 and signs[i - 1] != 0 and signs[i] != signs[i - 1]:
                flip = i
                break
        if flip is not None and (len(series) - flip) <= max(3, self.period_recent):
            raw, r = series[flip]
            direction = "decline" if signs[flip] < 0 else "growth"
            self._add("business", {
                "type": "period_reversal", "table": t["name"], "metric": chg,
                "segment": f"{axis}=reversal@{_lab(raw)}", "anchor": str(raw),
                "period_label": _lab(raw),
                "impact_value": _safe(r[chg]), "impact_share": None, "share_basis": None,
                "significance": 0.9, "score": 7.0,
                "detail": (f"{chg} reversed to {direction} around {_lab(raw)} "
                           f"({_fmt(series[flip - 1][1][chg])} -> {_fmt(r[chg])})"),
            })

        # 3) Value/volume divergence: a period where value falls but a volume driver
        #    rises (or vice versa) - a mix/price story worth surfacing.
        vol = next((v for v in t["triples"]
                    if v is not tr and v.get("semantic_role") in (None, "volume")
                    and v["change"] not in self.ratio), None)
        if vol:
            vchg = vol["change"]
            worst = None
            for raw, r in series:
                a, b = r.get(chg), r.get(vchg)
                if _finite(a) and _finite(b) and _sign(a) != 0 and _sign(a) != _sign(b) != 0:
                    if worst is None or abs(a) > abs(worst[1][chg]):
                        worst = (raw, r)
            if worst:
                raw, r = worst
                self._add("business", {
                    "type": "period_value_volume_divergence", "table": t["name"], "metric": chg,
                    "segment": f"{axis}=divergence@{_lab(raw)}", "anchor": str(raw),
                    "period_label": _lab(raw),
                    "impact_value": _safe(r[chg]), "impact_share": None, "share_basis": None,
                    "significance": 0.9, "score": 6.5,
                    "detail": (f"in {_lab(raw)} {chg} moved {_fmt(r[chg])} while {vchg} "
                               f"moved {_fmt(r[vchg])} - value and volume diverged"),
                })

    def recent_week(self, t: dict):
        """The most recently completed window vs the previous window and a
        trailing norm (Phase 3 calendar / Phase 3b rolling). Emits ONE composite
        ``recent_week_movement`` candidate with boolean facets - never six
        per-week rows. Window-relative math only: the WoW/rolling-delta % lives
        in the structured ``recent_week`` payload, NOT ``impact_share`` (which
        means share of a grand total elsewhere and would be mislabelled here). A
        perfectly flat baseline (robust z undefined) is detected on materiality
        alone; a zero previous window uses the trailing median as the %
        denominator.

        Shared between calendar weeks (``recent_week_history``) and rolling
        7-day windows (``recent_week_rolling_history``) - both fold to the same
        non-overlapping row shape, so the same ``vals[-1]``/``vals[-2]``
        comparison is valid for either; only wording differs by ``window_mode``.
        For rolling mode a structured observation is ALWAYS recorded (even when
        the reading isn't significant), because memory can only learn that a
        rolling incident recovered if it has a prior "inactive" reading to
        compare against."""
        contract = t.get("contract") or {}
        coverage_kind = contract.get("coverage_kind")
        if coverage_kind not in ("recent_week_history", "recent_week_rolling_history"):
            return
        window_mode = "calendar" if coverage_kind == "recent_week_history" else "rolling"
        rows, roles = t["rows"], t["roles"]
        axis = contract.get("axis") or roles["date"]
        if not axis:
            return
        mroles = contract.get("metric_roles") or {}

        def _alias(role_name):
            for a, r in mroles.items():
                if r.get("semantic_role") == role_name and r.get("phase") == "current":
                    return a
            return None

        value_alias = _alias("value")
        if not value_alias or value_alias in self.ratio:
            return
        volume_alias = _alias("volume")

        series = [(_parse_date(r.get(axis)), r) for r in rows
                  if _parse_date(r.get(axis)) is not None and _finite(r.get(value_alias))]
        series.sort(key=lambda kv: kv[0])
        if len(series) < 4:
            return
        vals = [r.get(value_alias) for _, r in series]
        actual, previous = vals[-1], vals[-2]
        trailing = vals[:-1]
        expected = sorted(trailing)[len(trailing) // 2]
        robust_z = _point_robust_z(actual, trailing)
        denom = previous if abs(previous) > _EPS else expected
        change_pct = ((actual - previous) / denom * 100.0) if abs(denom) > _EPS else None
        abs_impact = actual - previous
        dev_from_median = actual - expected

        def _sign(x):
            return (x > _EPS) - (x < -_EPS)

        mat = change_pct is not None and abs(change_pct) >= self.week_materiality_pct
        # Flat baseline -> materiality alone; otherwise require BOTH materiality
        # and a robust-z break (a big z on a tiny move is not reported).
        active = bool(mat and (robust_z is None or abs(robust_z) >= self.week_z_cutoff))
        abnormal = ((robust_z is not None and abs(robust_z) >= self.week_z_cutoff)
                    or (robust_z is None and mat))

        if window_mode == "rolling":
            # Raw canonical fields only - no story_key. insight_novelty_filter is
            # the single place that computes it (for both this observation and
            # any real candidate below), so the two can never drift apart.
            self.rolling_observation = {
                "axis": contract.get("date_axis") or axis, "metric": value_alias,
                "segment": "overall (comparable base)", "active": active,
                "impact_value": _safe(abs_impact), "change_pct": _safe(change_pct),
                "direction": _sign(abs_impact), "data_as_of": contract.get("window_end"),
            }

        if not active:
            return

        deltas = [vals[i] - vals[i - 1] for i in range(1, len(vals))]
        last_d = deltas[-1]
        reversal = (len(deltas) >= 2 and _sign(last_d) != 0 and _sign(deltas[-2]) != 0
                    and _sign(last_d) != _sign(deltas[-2]))
        run = 0
        for d in reversed(deltas):
            if _sign(d) == _sign(last_d) and _sign(d) != 0:
                run += 1
            else:
                break
        sustained_run = run >= 2

        divergence = False
        if volume_alias:
            va, vp = series[-1][1].get(volume_alias), series[-2][1].get(volume_alias)
            if _finite(va) and _finite(vp):
                divergence = (_sign(va - vp) != 0 and _sign(last_d) != 0
                              and _sign(va - vp) != _sign(last_d))

        facets = {"week_over_week": bool(mat), "abnormal_vs_baseline": bool(abnormal),
                  "reversal": bool(reversal), "sustained_run": bool(sustained_run),
                  "value_volume_divergence": bool(divergence)}

        ws = series[-1][0]
        week_start_iso = ws.date().isoformat() if isinstance(ws, datetime) else str(ws)
        week_end_iso = contract.get("week_end")
        if not week_end_iso and isinstance(ws, datetime):
            week_end_iso = (ws.date() + timedelta(days=6)).isoformat()

        drivers = self.recent_week_drivers or {}
        driver_segments = (drivers.get("top_segments", [])
                           if drivers.get("week_start") == week_start_iso else [])
        drivers_truncated = bool(drivers.get("truncated")) if driver_segments else False

        payload = {
            "window_mode": window_mode,
            "week_start": week_start_iso, "week_end": week_end_iso,
            "actual": _safe(actual), "previous": _safe(previous), "expected": _safe(expected),
            "change_pct": _safe(change_pct), "dev_from_median": _safe(dev_from_median),
            "robust_z": _safe(robust_z), "abs_impact": _safe(abs_impact),
            "driver_segments": driver_segments, "drivers_truncated": drivers_truncated,
            "data_as_of": contract.get("window_end"), "facets": facets,
        }

        direction = "declined" if abs_impact < 0 else "rose"
        window_label = (f"week of {week_start_iso}" if window_mode == "calendar"
                        else f"the trailing 7 days ending {week_end_iso}")
        pct_label = "WoW" if window_mode == "calendar" else "vs the prior 7 days"
        detail = (f"{window_label}: {value_alias} {direction} {_fmt(abs_impact)} "
                  f"({change_pct:+.1f}% {pct_label}) to {_fmt(actual)} from {_fmt(previous)}; "
                  f"trailing-median {_fmt(expected)}"
                  + (f", robust z {robust_z:.1f}" if robust_z is not None else ", flat baseline"))
        extra_facets = [k for k, v in facets.items()
                        if v and k not in ("week_over_week", "abnormal_vs_baseline")]
        if extra_facets:
            detail += "; " + ", ".join(extra_facets)
        if driver_segments:
            lead = ", ".join(f"{s['segment']} ({_fmt(s['change'])})" for s in driver_segments[:2])
            detail += f"; {'largest returned drivers' if drivers_truncated else 'top drivers'}: {lead}"

        self._add("business", {
            "type": "recent_week_movement",
            "table": t["name"], "metric": value_alias,
            "segment": "overall (comparable base)", "anchor": week_start_iso,
            "axis": contract.get("date_axis") or axis,
            "week_start": week_start_iso, "week_end": week_end_iso,
            "impact_value": _safe(abs_impact), "impact_share": None, "share_basis": None,
            "significance": (_safe(min(abs(robust_z) / (2 * self.week_z_cutoff), 1.0))
                             if robust_z is not None else 1.0),
            "score": abs(change_pct) if change_pct is not None else 0.0,
            "recent_week": payload,
            "detail": detail,
        })

    def daily(self, t: dict):
        """One ``daily_incident`` candidate per already-flagged, already-merged,
        already-scored incident row from ``insight_daily.py`` - the statistical
        work (per-reference testing, merging, scoring) happened upstream; this
        just turns each incident into a ranked candidate. Called exclusively
        (never alongside concentration/outliers/etc - see ``run()``'s dispatch),
        since incident rows carry a segment label alongside several numeric
        fields that those generic methods could otherwise misread as a segment
        breakdown."""
        contract = t.get("contract") or {}
        if contract.get("coverage_kind") != "daily_incidents":
            return
        for row in t["rows"]:
            metric = row.get("metric")
            share, basis = (
                self._share(row.get("cumulative_impact"), metric)
                if metric in self.additive
                else (None, None)
            )
            impact = row.get("cumulative_impact")
            peak_z = row.get("peak_z")
            self._add("business", {
                "type": "daily_incident", "table": t["name"],
                "metric": metric, "axis": contract.get("date_axis") or row.get("axis"),
                "segment": row.get("segment"), "anchor": row.get("episode_start"),
                "episode_start": row.get("episode_start"), "episode_end": row.get("episode_end"),
                "day_count": row.get("day_count"),
                "actual_total": _safe(row.get("actual_total")),
                "expected_total": _safe(row.get("expected_total")),
                "score": row.get("score", 0.0),
                "impact_value": _safe(impact), "impact_share": _safe(share),
                "share_basis": basis, "peak_z": _safe(peak_z),
                "detail": (f"{row.get('episode_start')}..{row.get('episode_end')}: {metric} "
                           f"{'declined' if _finite(impact) and impact < 0 else 'rose'} "
                           f"{_fmt(impact)} vs expected {_fmt(row.get('expected_total'))}"
                           + (f" (peak z {peak_z:.1f})" if _finite(peak_z) else "")),
            })

    def reconciliation(self, t: dict):
        """Data-quality checks: triple violations, zero-prior bases, coverage
        gaps vs grand totals, non-finite values, non-differentiating metrics."""
        rows, roles = t["rows"], t["roles"]

        # change != current - prior on specific rows
        for tr in t["triples"]:
            if not tr["bad_rows"]:
                continue
            chg, cur, prev = tr["change"], tr["current"], tr["prior"]
            worst, worst_gap = None, 0.0
            for r in rows:
                c, p, g = r.get(cur), r.get(prev), r.get(chg)
                if not (_finite(c) and _finite(p) and _finite(g)):
                    continue
                gap = abs((c - p) - g)
                if gap > (self.recon_tol_pct / 100.0) * max(abs(c), abs(p), abs(g), 1.0) and gap > worst_gap:
                    worst, worst_gap = r, gap
            if worst is not None:
                seg = _segment_of(worst, roles["labels"])
                self._add("data_quality", {
                    "type": "reconciliation_gap",
                    "table": t["name"], "metric": chg, "segment": seg,
                    "impact_value": _safe(worst_gap),
                    "impact_share": None, "share_basis": None,
                    "significance": 1.0,
                    "score": min(worst_gap / 1e6 + 5.0, 100.0),
                    "detail": (f"{tr['bad_rows']} row(s) where {chg} != {cur} - {prev}; "
                               f"worst at {seg} (gap {_fmt(worst_gap)})"),
                })

        # zero prior base with real current value
        for tr in t["triples"]:
            cur, prev = tr["current"], tr["prior"]
            hits = [r for r in rows
                    if _finite(r.get(cur)) and r.get(cur) > _EPS
                    and _finite(r.get(prev)) and abs(r.get(prev)) <= _EPS]
            if not hits or not roles["labels"]:
                continue
            hits.sort(key=lambda r: r[cur], reverse=True)
            segs = ", ".join(_segment_of(r, roles["labels"]) for r in hits[:3])
            total_cur = sum(r[cur] for r in hits)
            share, basis = self._share(total_cur, cur)
            self._add("data_quality", {
                "type": "zero_prior_base",
                "table": t["name"], "metric": cur, "segment": segs,
                "impact_value": _safe(total_cur),
                "impact_share": _safe(share),
                "share_basis": basis,
                "significance": 1.0,
                "score": (abs(share) if share is not None else 10.0) + 10.0,
                "detail": (f"{len(hits)} segment(s) ({segs}) have {cur} of "
                           f"{_fmt(total_cur)} with zero {tr['prior']} - growth vs "
                           f"prior is undefined there"),
            })

        # breakdown sum vs grand total (coverage gap). Only for proven-additive
        # metrics on full label breakdowns: date/period-windowed tables cover a
        # different span than the grand total by design, top-N tables are
        # truncated by design, and ratio metrics never sum to their total.
        contract_complete = (not t.get("contract")
                             or t["contract"].get("completeness") == "complete")
        if (contract_complete and roles["labels"] and not roles["date"] and not roles["period"]
                and len(rows) < self.row_cap):
            worst = None
            for col in roles["numerics"]:
                if col not in self.additive:
                    continue
                total = self.grand_totals.get(col)
                if not _finite(total) or abs(total) <= _EPS:
                    continue
                vals = [r.get(col) for r in rows if _finite(r.get(col))]
                if len(vals) < 2:
                    continue
                gap = sum(vals) - total
                gap_pct = abs(gap) / abs(total) * 100.0
                if gap_pct > self.recon_tol_pct and (worst is None or gap_pct > worst[2]):
                    worst = (col, gap, gap_pct, sum(vals), total)
            if worst:
                col, gap, gap_pct, s, total = worst
                self._add("data_quality", {
                    "type": "coverage_gap",
                    "table": t["name"], "metric": col, "segment": "overall",
                    "impact_value": _safe(gap),
                    "impact_share": _safe(gap_pct),
                    "share_basis": f"grand_total:{col}",
                    "significance": 0.9,
                    "score": min(gap_pct, 100.0),
                    "detail": (f"rows sum to {_fmt(s)} but the grand total of {col} "
                               f"is {_fmt(total)} - gap {_fmt(gap)} ({gap_pct:.1f}%); "
                               f"truncated rows or a different filter window"),
                })

        # non-finite values (Infinity / NaN)
        bad_cols = {}
        for col in roles["numerics"]:
            n_bad = sum(1 for r in rows if _is_num(r.get(col)) and not math.isfinite(r.get(col)))
            if n_bad:
                bad_cols[col] = n_bad
        if bad_cols:
            desc = ", ".join(f"{c} ({n})" for c, n in sorted(bad_cols.items()))
            self._add("data_quality", {
                "type": "non_finite_values",
                "table": t["name"], "metric": ", ".join(sorted(bad_cols)), "segment": "overall",
                "impact_value": None, "impact_share": None, "share_basis": None,
                "significance": 1.0,
                "score": 5.0 + sum(bad_cols.values()),
                "detail": f"Infinity/NaN values in: {desc} - usually a division by a zero or missing prior",
            })

        # non-differentiating metric
        if roles["labels"] and len(rows) >= 5:
            for col in roles["numerics"]:
                vals = [r.get(col) for r in rows if _finite(r.get(col))]
                if len(vals) >= 5 and max(vals) - min(vals) <= _EPS * max(abs(vals[0]), 1.0):
                    self._add("data_quality", {
                        "type": "non_differentiating",
                        "table": t["name"], "metric": col, "segment": "overall",
                        "impact_value": _safe(vals[0]),
                        "impact_share": None, "share_basis": None,
                        "significance": 1.0,
                        "score": 5.0,
                        "detail": (f"{col} returns the identical value {_fmt(vals[0])} for "
                                   f"all {len(vals)} segments - likely not sliced by this dimension"),
                    })

    # -- driver --

    def run(self, clean: dict) -> dict:
        tables = []
        for q in clean.get("queries", []):
            rows = q.get("rows") or []
            if q.get("status") != "success" or not rows:
                continue
            rows = _coerce_sentinels(rows)
            roles = _classify_columns(rows)
            contract = self.contracts.get(q.get("query_name", "?"), {})
            if contract.get("coverage_kind") == "entity_scope_discovery":
                # The comparable in-memory derivative is analysed normally;
                # current-only/prior-only members are emitted explicitly below
                # instead of being mislabelled as zero-base data-quality errors.
                continue
            triples = _contract_triples(contract, roles["numerics"])
            if not triples:
                triples = _find_triples(rows, roles["numerics"],
                                        self.recon_tol_pct / 100.0)
            else:
                # Preserve the existing reconciliation diagnostics even though
                # role identity came from metadata.
                for tr in triples:
                    for row in rows:
                        c, p, g = row.get(tr["current"]), row.get(tr["prior"]), row.get(tr["change"])
                        if not (_finite(c) and _finite(p) and _finite(g)):
                            continue
                        scale = max(abs(c), abs(p), abs(g), 1.0)
                        if abs((c - p) - g) <= (self.recon_tol_pct / 100.0) * scale:
                            tr["ok_rows"] += 1
                        else:
                            tr["bad_rows"] += 1
            tables.append({
                "name": q.get("query_name", "?"),
                "rows": rows,
                "roles": roles,
                "triples": triples,
                "contract": contract,
            })

        self.collect_totals(tables)
        self.classify_metrics(tables)
        for t in tables:
            # Incident rows are an exclusive dispatch, not an added method: they
            # carry a segment label alongside several numeric fields (peak_z,
            # cumulative_impact, day_count, ...) that the generic segment-
            # breakdown methods below could otherwise misread and turn into
            # spurious concentration/outlier candidates on top of the real ones.
            if (t.get("contract") or {}).get("coverage_kind") == "daily_incidents":
                self.daily(t)
                continue
            self.bridge(t)
            self.concentration(t)
            self.outliers(t)
            self.trend(t)
            self.period(t)
            self.recent_week(t)
            self.reconciliation(t)
        overall_pv = self.overall_split(tables)

        business = sorted(self.business.values(), key=lambda c: c["score"], reverse=True)
        dq = sorted(self.data_quality.values(), key=lambda c: c["score"], reverse=True)
        # Deliberately do not cap here.  Memory suppression happens in the next
        # node, and capping before that can let already-reported stories occupy
        # every slot while a lower-ranked unseen story is discarded.  The
        # novelty filter applies the configured per-level and overall caps after
        # it removes previously reported story keys.
        for i, c in enumerate(business + dq):
            c["id"] = f"cand_{i + 1:02d}_{c['type']}"
        return {
            "note": ("Deterministic pre-pass over the scan tables. impact_value / "
                     "impact_share are computed facts; share_basis says what the "
                     "share is measured against. Shares are only computed for "
                     "metrics proven additive (breakdown sums reconcile to the "
                     "grand total); ratio-like metrics are ranked by statistical "
                     "significance instead."),
            "grand_totals_seen": {k: _safe(v) for k, v in self.grand_totals.items()},
            "additive_metrics": sorted(self.additive),
            "ratio_metrics": sorted(self.ratio),
            "overall_price_volume": overall_pv,
            "business_candidates": business,
            "data_quality_candidates": dq,
        }


def _append_entity_lifecycle_candidates(result: dict, state: dict) -> None:
    scope = state.get("resolved_entity_scope", {})
    evidence = state.get("baseline_scope_evidence", {})
    rows = evidence.get("rows", []) if evidence.get("status") == "success" else []
    hint = evidence.get("contract_hint", {})
    entity = scope.get("entity_dimension") or {}
    current = next((m for m in hint.get("metrics", []) if m.get("phase") == "current"), None)
    prior = next((m for m in hint.get("metrics", []) if m.get("phase") == "prior"), None)
    if not rows or not entity.get("column") or not current or not prior:
        return

    def value(row, key):
        if key in row:
            return row.get(key)
        return next((v for k, v in row.items()
                     if k.split(".")[-1].strip("[]") == key), None)

    by_entity = {str(value(r, entity["column"])): r for r in rows
                 if value(r, entity["column"]) is not None}
    additions = []
    for code in scope.get("new_entities", []):
        amount = value(by_entity.get(str(code), {}), current["alias"])
        if not _finite(amount):
            continue
        additions.append({
            "type": "new_entity_current_only", "table": evidence.get("query_name"),
            "metric": current["alias"], "segment": str(code),
            "impact_value": _safe(amount), "impact_share": None, "share_basis": None,
            "significance": 1.0, "score": 12.0,
            "detail": f"{code}: current-only {current['alias']} of {_fmt(amount)}; excluded from comparable change",
            "kind": "business",
        })
    for code in scope.get("prior_only_entities", []):
        amount = value(by_entity.get(str(code), {}), prior["alias"])
        if not _finite(amount):
            continue
        additions.append({
            "type": "prior_only_entity", "table": evidence.get("query_name"),
            "metric": prior["alias"], "segment": str(code),
            "impact_value": _safe(-amount), "impact_share": None, "share_basis": None,
            "significance": 1.0, "score": 12.0,
            "detail": f"{code}: prior-only {prior['alias']} of {_fmt(amount)}; excluded from comparable change",
            "kind": "business",
        })
    if additions:
        # Lifecycle findings carry scope semantics used by every downstream
        # validator. Keep them in the uncapped detector output; the novelty
        # filter removes seen stories first and applies the final shortlist cap.
        ordinary = [c for c in result.get("business_candidates", [])
                    if c.get("type") not in ("new_entity_current_only", "prior_only_entity")]
        result["business_candidates"] = sorted(
            ordinary + additions, key=lambda c: c.get("score", 0.0), reverse=True
        )
        for i, c in enumerate(result.get("business_candidates", []) + result.get("data_quality_candidates", [])):
            c["id"] = f"cand_{i + 1:02d}_{c['type']}"


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: computing deterministic stat candidates...")

    clean = state.get("insight_clean_data", {"queries": []})
    rolling_observation = None
    try:
        detector = _Detector(state, log)
        result = detector.run(clean)
        _append_entity_lifecycle_candidates(result, state)
        rolling_observation = detector.rolling_observation
    except Exception as exc:  # noqa: BLE001 - stats must never kill the branch
        log.error(f"Stat detector failed ({exc}); signal detector falls back to raw rows.")
        result = {"note": f"stat pre-pass failed: {exc}",
                  "business_candidates": [], "data_quality_candidates": []}

    file_io.write_json(state, "insight_stat_candidates.json", result)
    n_b, n_d = len(result["business_candidates"]), len(result["data_quality_candidates"])
    log.info(f"Stat candidates: {n_b} business, {n_d} data-quality.")
    for c in result["business_candidates"][:5]:
        log.info(f"  [{c['score']:.1f}] {c['type']}: {c['detail']}")
    updates = {"insight_stat_candidates": result, **log.updates()}
    if rolling_observation is not None:
        updates["insight_rolling_observation"] = rolling_observation
    return updates
