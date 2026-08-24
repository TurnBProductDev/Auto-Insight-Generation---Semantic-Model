"""Mutation-test audit_daily_sales_reference.py.

An auditor that passes proves nothing until it has been shown to fail. Each mutation
below breaks the page or its inputs in one specific way; every one must be caught, and
a mutation that does not change the file is reported as such rather than counted as a
pass - a no-op mutation silently "passing" is how a blind check survives.

    python docs/dashboard-reference/mutate_daily_sales_audit.py
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "reference_daily_sales.html"
SCAN = HERE / "daily_sales_scan.json"


def run() -> tuple[int, list[str]]:
    r = subprocess.run([sys.executable, str(HERE / "audit_daily_sales_reference.py")],
                       capture_output=True, text=True, cwd=HERE)
    return r.returncode, [l.strip() for l in r.stdout.splitlines()
                          if l.strip().startswith("FAIL")]


PAGE_MUTATIONS = [
    ("a banned synonym replaces an approved name",
     "Net Sales is Bills multiplied by Basket Value",
     "Revenue is footfall multiplied by average ticket"),
    ("a second script tag is added", "</body>", "<script>1</script></body>"),
    ("an external stylesheet is linked", "<style>",
     '<link rel="stylesheet" href="https://example.com/x.css"><style>'),
    ("a last-year comparison creeps in", "What carried the day", "Growth against last year"),
    ("a figure gains spurious precision", "SAR&nbsp;98.79", "SAR&nbsp;98.7912345"),
    ("the layout container gains a third child", '<div class="app">\n  <nav class="rail"',
     '<div class="app">\n  <header>x</header>\n  <nav class="rail"'),
    ("the trading day is printed a second time above the hero",
     '<h1>Daily Sales</h1>', '<h1>Daily Sales</h1><p>Wednesday 12 August 2026</p>'),
    ("a vague comparison loses its figure",
     "A small gap on a small part of the business is not a finding.",
     "Some categories were significantly weaker than usual."),
    ("browser storage is used", "var current = {view:", "localStorage.getItem('v'); var current = {view:"),
]

SCAN_MUTATIONS = [
    ("a store's Net Sales is bent by 5%", "store_sales"),
    ("a category's benchmark is inflated", "cat_band"),
]


def mutate_scan(kind: str, data: dict) -> dict:
    if kind == "store_sales":
        for r in data["store_days"]:
            if r["tran_date"] == data["anchor"] and r["store_no"] == "ST4":
                r["actual_sales"] *= 1.05
    elif kind == "cat_band":
        for r in data["categories"]:
            if r.get("actual_sales"):
                r["sales_p20"] = (r.get("sales_p20") or 0) * 3
                break
    return data


def main() -> int:
    page_src = PAGE.read_text(encoding="utf-8")
    scan_src = SCAN.read_text(encoding="utf-8")
    missed, noop = [], []

    for name, find, repl in PAGE_MUTATIONS:
        if find not in page_src:
            noop.append(name)
            print(f"  NO-OP   {name}   (target not on the page)")
            continue
        PAGE.write_text(page_src.replace(find, repl, 1), encoding="utf-8")
        code, fails = run()
        print(f"  {'CAUGHT ' if code else 'MISSED '} {name}"
              + (f"   -> {fails[0][6:84]}" if fails else ""))
        if not code:
            missed.append(name)
    PAGE.write_text(page_src, encoding="utf-8")

    for name, kind in SCAN_MUTATIONS:
        SCAN.write_text(json.dumps(mutate_scan(kind, json.loads(scan_src)), indent=1),
                        encoding="utf-8")
        code, fails = run()
        print(f"  {'CAUGHT ' if code else 'MISSED '} {name}"
              + (f"   -> {fails[0][6:84]}" if fails else ""))
        if not code:
            missed.append(name)
    SCAN.write_text(scan_src, encoding="utf-8")

    clean = run()[0] == 0
    print(f"\n  restored page and scan audit clean: {clean}")
    if missed or noop or not clean:
        print(f"\n  MISSED: {missed}\n  NO-OP:  {noop}")
        return 1
    print(f"\n  all {len(PAGE_MUTATIONS) + len(SCAN_MUTATIONS)} mutations caught")
    return 0


if __name__ == "__main__":
    sys.exit(main())
