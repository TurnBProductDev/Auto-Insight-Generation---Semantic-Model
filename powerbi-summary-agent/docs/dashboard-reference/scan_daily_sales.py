"""Live read of the DAILY_SALES_DASHBOARD semantic model into daily_sales_scan.json.

One scan, no LLM, no writes outside this folder. Every figure the reference page
publishes is derived from this file by daily_sales_facts.py - nothing is typed by hand.

    python scan_daily_sales.py            # rewrites daily_sales_scan.json
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from src.tools.powerbi_executor import get_powerbi_token, run_dax  # noqa: E402

WORKSPACE = "2829a4af-2e07-4b43-b913-0a829a06bef4"
DATASET = "8d111712-9ea8-4a65-9bb9-58f00e49d379"
REPORT = "6ddd2afa-a1b4-443c-854d-e1ec4ad88e77"

# Money columns arrive raw; daily_sales_facts.py owns the presentation scale.
MEASURE_COLS = [
    "actual_sales", "actual_cost", "actual_bills", "actual_margin",
    "sales_p20", "sales_p50", "sales_p80",
    "bills_p20", "bills_p50", "bills_p80",
    "margin_p20", "margin_p50", "margin_p80",
    "sample_days", "margin_sample_days",
]

_token = None


def token():
    global _token
    if _token is None:
        _token = get_powerbi_token()
    return _token


def q(dax: str) -> list[dict]:
    ok, resp = run_dax(WORKSPACE, DATASET, dax, token())
    if not ok:
        raise RuntimeError(f"query failed: {str(resp)[:400]}\n{dax[:300]}")
    result = resp["results"][0]
    if "error" in result:
        raise RuntimeError(f"embedded error: {json.dumps(result['error'])[:400]}\n{dax[:300]}")
    rows = result["tables"][0]["rows"]
    return [{k.split("[")[-1].rstrip("]"): v for k, v in r.items()} for r in rows]


def sums(table: str) -> str:
    """Aggregate every measure the way BR-11, BR-13 and BR-14 require.

    The band is summed over the sub-group rows that ACTUALLY TRADED, so the
    comparison is like for like: summing a band over rows with no sale while the
    actual can only sum rows with one makes every merged name read below band.
    What went quiet is not hidden - it is returned separately as silent_rows and
    silent_p50, which is a finding in its own right.

    Money and bills add. Margin never does: an actual margin is recovered from
    cost and sales (which IS the revenue weighting, exactly) and a benchmark
    margin comes back as its own weighted numerator and denominator so the
    caller divides rather than sums.
    """
    live = f"FILTER({table}, NOT ISBLANK({table}[actual_sales]))"
    quiet = f"FILTER({table}, ISBLANK({table}[actual_sales]))"
    parts = [
        f'"row_count", COUNTROWS({table})',
        f'"rows_with_actual", COUNTROWS({live})',
        f'"actual_sales", SUM({table}[actual_sales])',
        f'"actual_cost", SUM({table}[actual_cost])',
        f'"actual_bills", SUM({table}[actual_bills])',
        f'"silent_p50", SUMX({quiet}, {table}[sales_p50])',
        f'"silent_bills_p50", SUMX({quiet}, {table}[bills_p50])',
    ]
    for p in ("p20", "p50", "p80"):
        parts.append(f'"sales_{p}", SUMX({live}, {table}[sales_{p}])')
        parts.append(f'"bills_{p}", SUMX({live}, {table}[bills_{p}])')
        parts.append(f'"sales_{p}_all", SUM({table}[sales_{p}])')
        band = f"FILTER({live}, NOT ISBLANK({table}[margin_{p}]))"
        parts.append(f'"margin_{p}_num", SUMX({band}, {table}[margin_{p}] * {table}[sales_{p}])')
        parts.append(f'"margin_{p}_den", SUMX({band}, {table}[sales_{p}])')
    parts.append(f'"sample_days_min", MINX({live}, {table}[sample_days])')
    parts.append(f'"sample_days_max", MAXX({live}, {table}[sample_days])')
    parts.append(f'"margin_sample_days_min", MINX({live}, {table}[margin_sample_days])')
    parts.append(f'"margin_sample_days_max", MAXX({live}, {table}[margin_sample_days])')
    return ", ".join(parts)


def level(table: str, keys: list[str], date_filter: str | None = None) -> list[dict]:
    key_expr = ", ".join(f"{table}[{k}]" for k in keys)
    filt = ""
    if date_filter:
        filt = f", FILTER(ALL({table}[tran_date]), {table}[tran_date] = {date_filter})"
    return q(f"EVALUATE SUMMARIZECOLUMNS({key_expr}{filt}, {sums(table)})")


def main() -> None:
    scan: dict = {
        "source": {
            "report_id": REPORT,
            "report_name": "DAILY_SALES_DASHBOARD",
            "workspace_id": WORKSPACE,
            "dataset_id": DATASET,
        }
    }

    anchor_rows = q('EVALUATE ROW("store", [Store Latest Date], "dept", [Dept Latest Date], '
                    '"section", [Section Latest Date], "category", [Category Latest Date])')
    scan["latest_dates"] = {k: (v or "")[:10] for k, v in anchor_rows[0].items()}
    anchor = scan["latest_dates"]["store"]
    scan["anchor"] = anchor
    y, m, d = anchor.split("-")
    ADATE = f"DATE({int(y)},{int(m)},{int(d)})"

    scan["span"] = q('EVALUATE ROW("min", MIN(storebenchmark[tran_date]), '
                     '"max", MAX(storebenchmark[tran_date]), '
                     '"days", DISTINCTCOUNT(storebenchmark[tran_date]))')[0]
    for k in ("min", "max"):
        scan["span"][k] = (scan["span"][k] or "")[:10]

    scan["stores"] = [r["store_no"] for r in q("EVALUATE Dim_Store")]

    # --- store level, every day in the window -------------------------------
    store_days = q("EVALUATE SELECTCOLUMNS(storebenchmark, "
                   '"tran_date", [tran_date], "dow_name", [dow_name], '
                   '"week_of_month", [week_of_month], "store_no", [store_no], '
                   + ", ".join(f'"{c}", [{c}]' for c in MEASURE_COLS)
                   + ") ORDER BY [tran_date], [store_no]")
    for r in store_days:
        r["tran_date"] = (r["tran_date"] or "")[:10]
    scan["store_days"] = store_days

    # --- the three levels below, on the anchor day --------------------------
    scan["departments"] = level("departmentbenchmark", ["store_no", "DEPARTMENT"], ADATE)
    scan["sections"] = level("sectionbenchmark", ["store_no", "DEPARTMENT", "SECTION"], ADATE)
    scan["categories"] = level(
        "categorybenchmark",
        ["store_no", "DEPARTMENT", "SECTION", "CATEGORY_NAME_2"], ADATE)

    # --- grain evidence: rows vs distinct names, per level -------------------
    grain = {}
    for table, keys in (("departmentbenchmark", ["store_no", "DEPARTMENT"]),
                        ("sectionbenchmark", ["store_no", "DEPARTMENT", "SECTION"]),
                        ("categorybenchmark",
                         ["store_no", "DEPARTMENT", "SECTION", "CATEGORY_NAME_2"])):
        key_expr = ", ".join(f"{table}[{k}]" for k in keys)
        row = q(f'EVALUATE ROW("rows", COUNTROWS(FILTER({table}, {table}[tran_date] = {ADATE})), '
                f'"distinct_names", COUNTROWS(SUMMARIZE(FILTER({table}, '
                f"{table}[tran_date] = {ADATE}), {key_expr})))")[0]
        grain[table] = row
    scan["grain"] = grain

    # --- department bill penetration needs each store's own total bills ------
    scan["store_bills_anchor"] = {
        r["store_no"]: r["actual_bills"]
        for r in q("EVALUATE SUMMARIZECOLUMNS(storebenchmark[store_no], "
                   f"FILTER(ALL(storebenchmark[tran_date]), storebenchmark[tran_date] = {ADATE}), "
                   '"actual_bills", SUM(storebenchmark[actual_bills]))')
    }

    out = HERE / "daily_sales_scan.json"
    out.write_text(json.dumps(scan, indent=1, sort_keys=False), encoding="utf-8")
    counts = {k: len(v) for k, v in scan.items() if isinstance(v, list)}
    print(f"wrote {out.name}: anchor={anchor} {counts}")


if __name__ == "__main__":
    main()
