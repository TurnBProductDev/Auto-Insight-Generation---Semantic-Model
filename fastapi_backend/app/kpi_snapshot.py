"""Daily KPI threshold snapshot.

Runs after the Power BI refresh, reads the model over the REST executeQueries
API (headless -- reuses the repo-root MSAL refresh-token cache via pbi_agent),
computes all eight KPIs year-to-date vs the same elapsed window last year,
applies the benchmark thresholds in kpi_thresholds.json, and emits one snapshot
object per KPI:

    {"data_as_of": "2026-07-27", "window": "ytd", "kpi": "Revenue Growth %",
     "value": 0.126, "status": "green", "absolute_change": 15375467.6,
     "unit": "currency"}

Design notes live in kpi_thresholds.json -> "reporting". The short version:
  * The model pairs current/last-year values at the row level and the refresh
    trims last year to the same elapsed day, so YTD-vs-last-year is like-for-like
    with no partial-vs-full-month distortion. This job asserts that alignment
    each run and marks the snapshot degraded if it ever breaks.
  * The whole snapshot is ONE query; it only references MIS_DEEP_DIVE2[max_date]
    plus measures-by-name, so it is robust to the local/published schema drift
    the KPI notes warn about.

Run standalone (from repo root, after a refresh):
    python -m fastapi_backend.app.kpi_snapshot
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# --- locate repo root so we can reuse the proven headless auth ---------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

THRESHOLDS_FILE = Path(__file__).with_name("kpi_thresholds.json")
OUTPUT_DIR = _REPO_ROOT / "fastapi_backend" / "outputs"

# --- the single snapshot query ----------------------------------------------
# YTD = everything loaded this year (Jan 1 -> latest business date) vs the same
# elapsed window last year. Measures are referenced by name (stable surface);
# the only column touched is MIS_DEEP_DIVE2[max_date]. ly_as_of drives the
# alignment guard: its (month, day) must equal data_as_of's.
SNAPSHOT_DAX = r"""
EVALUATE
VAR DataAsOf = CALCULATE ( MAX ( MIS_DEEP_DIVE2[max_date] ), ALL ( MIS_DEEP_DIVE2 ) )
VAR CurYr = YEAR ( DataAsOf )
VAR LyAsOf = CALCULATE ( MAX ( MIS_DEEP_DIVE2[max_date] ), ALL ( MIS_DEEP_DIVE2 ), YEAR ( MIS_DEEP_DIVE2[max_date] ) = CurYr - 1 )
RETURN
ROW (
    "data_as_of", DataAsOf,
    "ly_as_of", LyAsOf,
    "rev_growth_pct", [revenue growth %],
    "rev_growth_abs", [revenue Growth],
    "vol_growth_pct", [QTY GROWTH %],
    "vol_growth_abs", [QTY Growth],
    "footfall_growth_pct", [bills growth %],
    "footfall_growth_abs", [bills growth],
    "asp_cur", [retail price current year],
    "asp_past", [retail price past year],
    "atv_cur", [SPEND PER TRANSACTION CURRENT YEAR],
    "atv_past", [SPEND PER TRANSACTION PAST YEAR],
    "upt_cur", [QUANTITY PER TRANSACTION CURRENT YEAR],
    "upt_past", [QUANTITY PER TRANSACTION PAST YEAR],
    "cat_breadth_pct", [COUNT %],
    "cat_declining", [COUNT],
    "cat_total", [COUNT_TOTAL],
    "atrisk_share_cur", DIVIDE ( [sum deg cur rev], [sum total cur rev] ),
    "atrisk_share_past", DIVIDE ( [sum deg past rev], [sum total past rev] )
)
"""


# --- status evaluation -------------------------------------------------------
def evaluate_status(value: Optional[float], direction: str, thresholds: dict) -> str:
    """Map a KPI value to red / amber / green (or 'severe') per its band.

    higher_is_better: green if value >= green_at, else amber if value >= amber_at,
                      else red (severe if severe_at set and value < severe_at).
    lower_is_better:  green if value <= green_at, else amber if value <= amber_at,
                      else red.
    """
    if value is None:
        return "unknown"
    green_at = thresholds["green_at"]
    amber_at = thresholds["amber_at"]
    severe_at = thresholds.get("severe_at")
    if direction == "higher_is_better":
        if severe_at is not None and value < severe_at:
            return "severe"
        if value >= green_at:
            return "green"
        if value >= amber_at:
            return "amber"
        return "red"
    # lower_is_better
    if value <= green_at:
        return "green"
    if value <= amber_at:
        return "amber"
    return "red"


# --- raw row -> per-KPI (value, absolute_change, unit) -----------------------
def _num(row: dict, key: str) -> Optional[float]:
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_ratio(cur: Optional[float], past: Optional[float]) -> Optional[float]:
    if cur is None or past is None or past == 0:
        return None
    return (cur - past) / past


def kpi_facts(row: dict) -> dict:
    """Compute each KPI's headline value + absolute change from the raw row.

    Ratio KPIs (ASP/ATV/UPT) and the at-risk delta are derived here from their
    cur/past pieces -- exactly the DAX in kpi_thresholds.json, kept in Python so
    the snapshot query stays a flat, drift-resistant measure pull.
    """
    asp_cur, asp_past = _num(row, "asp_cur"), _num(row, "asp_past")
    atv_cur, atv_past = _num(row, "atv_cur"), _num(row, "atv_past")
    upt_cur, upt_past = _num(row, "upt_cur"), _num(row, "upt_past")
    share_cur, share_past = _num(row, "atrisk_share_cur"), _num(row, "atrisk_share_past")

    def delta(a, b):
        return None if a is None or b is None else a - b

    return {
        "revenue_growth_pct":        {"value": _num(row, "rev_growth_pct"),      "absolute_change": _num(row, "rev_growth_abs"),      "unit": "currency"},
        "volume_growth_pct":         {"value": _num(row, "vol_growth_pct"),      "absolute_change": _num(row, "vol_growth_abs"),      "unit": "units"},
        "footfall_growth_pct":       {"value": _num(row, "footfall_growth_pct"), "absolute_change": _num(row, "footfall_growth_abs"), "unit": "transactions"},
        "asp_growth_pct":            {"value": _safe_ratio(asp_cur, asp_past),   "absolute_change": delta(asp_cur, asp_past),         "unit": "currency_per_unit"},
        "atv_growth_pct":            {"value": _safe_ratio(atv_cur, atv_past),   "absolute_change": delta(atv_cur, atv_past),         "unit": "currency_per_txn"},
        "upt_growth_pct":            {"value": _safe_ratio(upt_cur, upt_past),   "absolute_change": delta(upt_cur, upt_past),         "unit": "units_per_txn"},
        "category_decline_breadth":  {"value": _num(row, "cat_breadth_pct"),     "absolute_change": _num(row, "cat_declining"),       "unit": "categories_declining"},
        "atrisk_concentration_delta":{"value": delta(share_cur, share_past),     "absolute_change": delta(share_cur, share_past),     "unit": "share_pp"},
    }


# --- alignment guard ---------------------------------------------------------
def _parse_dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw).replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt)
        except ValueError:
            continue
    return None


def alignment_status(row: dict) -> dict:
    """The comparison is only valid if last year is trimmed to the same elapsed
    day. Confirm data_as_of and ly_as_of land on the same (month, day)."""
    cur = _parse_dt(row.get("data_as_of"))
    ly = _parse_dt(row.get("ly_as_of"))
    if cur is None or ly is None:
        return {"aligned": None, "reason": "could not parse data_as_of / ly_as_of"}
    aligned = (cur.month, cur.day) == (ly.month, ly.day)
    return {
        "aligned": aligned,
        "data_as_of": cur.date().isoformat(),
        "ly_as_of": ly.date().isoformat(),
        "reason": None if aligned else (
            f"elapsed windows differ: current reaches {cur:%m-%d}, last year reaches {ly:%m-%d}. "
            "YoY comparison may be current-partial vs last-year-full -- treat KPIs as degraded."
        ),
    }


# --- build the snapshot ------------------------------------------------------
def build_snapshot(row: dict, config: dict) -> dict:
    facts = kpi_facts(row)
    align = alignment_status(row)
    data_as_of = align.get("data_as_of") or (str(row.get("data_as_of", ""))[:10])
    window = config.get("reporting", {}).get("window", "ytd")

    items = []
    for kpi in config["kpis"]:
        f = facts[kpi["key"]]
        status = evaluate_status(f["value"], kpi["direction"], kpi["thresholds"])
        if align.get("aligned") is False:
            status = "degraded"
        items.append({
            "data_as_of": data_as_of,
            "window": window,
            "kpi": kpi["name"],
            "key": kpi["key"],
            "value": f["value"],
            "status": status,
            "absolute_change": f["absolute_change"],
            "unit": f["unit"],
            "direction": kpi["direction"],
            "bands": kpi["thresholds"].get("labels"),
        })
    return {"data_as_of": data_as_of, "window": window, "alignment": align, "kpis": items}


# --- execution ---------------------------------------------------------------
def run(execute_fn: Optional[Callable[[str], dict]] = None) -> dict:
    """Execute the snapshot query and build the result.

    execute_fn(dax) -> executeQueries JSON. Defaults to pbi_agent.execute_dax
    (headless REST against the published dataset). Inject a fake for testing.
    """
    if execute_fn is None:
        import pbi_agent  # repo-root; reuses the shared MSAL token cache
        execute_fn = pbi_agent.execute_dax

    resp = execute_fn(SNAPSHOT_DAX)
    try:
        rows = resp["results"][0]["tables"][0]["rows"]
    except (KeyError, IndexError):
        rows = []
    if not rows:
        raise RuntimeError("Snapshot query returned no rows.")
    # executeQueries names ROW columns "[name]"; normalize to bare keys.
    raw = {k.strip("[]"): v for k, v in rows[0].items()}

    config = json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    return build_snapshot(raw, config)


def main() -> None:
    snapshot = run()
    print(json.dumps(snapshot, indent=2, default=str))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = snapshot["data_as_of"] or datetime.now().strftime("%Y-%m-%d")
    (OUTPUT_DIR / f"kpi_snapshot_{stamp}.json").write_text(
        json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
    )
    (OUTPUT_DIR / "kpi_snapshot_latest.json").write_text(
        json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
    )

    align = snapshot["alignment"]
    if align.get("aligned") is False:
        print(f"\n[WARN] elapsed-window misalignment: {align['reason']}", file=sys.stderr)


if __name__ == "__main__":
    main()
