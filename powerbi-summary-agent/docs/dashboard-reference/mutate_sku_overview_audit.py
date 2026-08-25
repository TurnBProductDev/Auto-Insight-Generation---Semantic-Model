"""Break the SKU Overview page ten ways and assert the auditor objects to each.

    python mutate_sku_overview_audit.py

An auditor that passes proves nothing until it has been shown to fail. Each
mutation below is a defect that has either happened on a page in this repo or
is one line away from happening. The page and scan are restored afterwards.

A mutation whose target is not present is reported as NO-OP, never as a pass -
a mutation that changed nothing looks exactly like a success.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "reference_sku_overview.html"
SCAN = HERE / "sku_overview_scan.json"
AUDIT = HERE / "audit_sku_overview_reference.py"


def page_sub(old, new):
    def apply():
        t = PAGE.read_text(encoding="utf-8")
        if old not in t:
            return False
        PAGE.write_text(t.replace(old, new, 1), encoding="utf-8")
        return True
    return apply


def page_append(fragment):
    def apply():
        t = PAGE.read_text(encoding="utf-8")
        PAGE.write_text(t.replace("</body>", fragment + "</body>", 1),
                        encoding="utf-8")
        return True
    return apply


def scan_edit(fn):
    def apply():
        d = json.loads(SCAN.read_text(encoding="utf-8"))
        if not fn(d):
            return False
        SCAN.write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
        return True
    return apply


def _break_department_sum(d):
    d["all"]["by_department"][0]["stock_value_usd"] = 1.0
    return True


def _swap_featured(d):
    rows = sorted(d["all"]["rule4_rows"],
                  key=lambda r: -(r.get("sales_3m_local") or 0))
    if len(rows) < 2:
        return False
    d["featured"]["sku"] = rows[1]["SKU_CODE"]
    d["featured"]["home_loc"] = rows[1]["LOC_CODE"]
    return True


def _break_opp_basis(d):
    d["currency_evidence"]["opp_loss_over_avg_daily_value"]["max"] = 9.9
    return True


def _stock_on_a_stockout(d):
    d["all"]["rule4_totals"]["stock_value_usd"] = 500.0
    return True


def _surplus_exceeds_holding(d):
    d["all"]["rule7_totals"]["excess_value_usd"] = (
        float(d["all"]["rule7_totals"]["stock_value_usd"]) + 1000.0)
    return True


MUTATIONS = [
    ("a second script tag is added",
     page_append("<script>var x=1;</script>")),
    ("an external stylesheet is linked",
     page_sub("<style>", '<link rel="stylesheet" href="https://cdn.example/x.css"><style>')),
    ("a local-currency label reaches the page",
     page_sub("all money in US dollars", "all money in SAR")),
    ("a raw float escapes into the prose",
     page_sub("</h1>", "</h1><p>USD 2.7147647284841927</p>")),
    ("the daily-rate caveat is deleted",
     page_sub("daily rate, not a running total", "total lost so far")),
    ("the unavailable insight is quietly dropped",
     page_sub("Not available yet", "Coming soon")),
    ("banned jargon creeps back in",
     page_sub("</h1>", "</h1><p>ranked by velocity</p>")),
    ("a department no longer adds to the total", scan_edit(_break_department_sum)),
    ("the featured product is not the largest stockout", scan_edit(_swap_featured)),
    ("opportunity loss stops being one day's sales", scan_edit(_break_opp_basis)),
    ("an out-of-stock line is given stock value", scan_edit(_stock_on_a_stockout)),
    ("surplus is reported larger than the stock holding it",
     scan_edit(_surplus_exceeds_holding)),
]


def run_audit():
    r = subprocess.run([sys.executable, str(AUDIT)], capture_output=True, text=True)
    return r.returncode, r.stdout


def main():
    if not PAGE.exists():
        print("no page - run the builder first")
        return 1
    tmp = pathlib.Path(tempfile.mkdtemp())
    shutil.copy2(PAGE, tmp / PAGE.name)
    shutil.copy2(SCAN, tmp / SCAN.name)

    code, out = run_audit()
    if code != 0:
        print("the page does not pass its own audit before mutation:\n" + out)
        return 1
    print("clean page passes.\n")

    caught, missed, noop = 0, [], []
    try:
        for name, apply in MUTATIONS:
            shutil.copy2(tmp / PAGE.name, PAGE)
            shutil.copy2(tmp / SCAN.name, SCAN)
            if not apply():
                noop.append(name)
                print("  NO-OP   %s  (target not present - mutation proves nothing)"
                      % name)
                continue
            code, out = run_audit()
            if code != 0:
                caught += 1
                first = next((l.strip() for l in out.splitlines()
                              if l.strip().startswith("x ")), "")
                print("  caught  %-52s %s" % (name, first[:60]))
            else:
                missed.append(name)
                print("  MISSED  %s" % name)
    finally:
        shutil.copy2(tmp / PAGE.name, PAGE)
        shutil.copy2(tmp / SCAN.name, SCAN)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d of %d mutations caught" % (caught, len(MUTATIONS)))
    if noop:
        print("NO-OP (prove nothing): %s" % "; ".join(noop))
    if missed:
        print("MISSED: %s" % "; ".join(missed))
    return 1 if (missed or noop) else 0


if __name__ == "__main__":
    sys.exit(main())
