"""Audit a PRODUCED Inventory Management artifact. Run after every live run.

    python scripts/audit_stock_health.py [output_dir]

A replay proves the code is right; this proves a produced artifact is right.
Its most important job is the Opportunity Loss scope: the unscoped figure is
6.4x the correct one on live data, and both are in the model, so publishing the
wrong one is a single-character mistake away.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = PROJECT_ROOT / "outputs_stock_health"
MAX_QUOTED_DECIMALS = 2
TOLERANCE_PCT = 0.5

BANNED = ("velocity", "offtake", "capital lock-up", "carry cost", "coverage ratio",
          "materiality", "z-score", "dead stock", "slow-moving", "stagnant",
          "days of cover", "stock worth", "asset value", "inventory value")

_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  [PASS] {label}")
        return
    print(f"  [FAIL] {label}")
    if detail:
        for line in str(detail).splitlines():
            print(f"         {line}")
    _failures.append(label)


def close(a, b, tolerance_pct: float = TOLERANCE_PCT) -> bool:
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if b == 0:
        return abs(a) < 1e-6
    return abs(a - b) / abs(b) * 100.0 <= tolerance_pct


def audit(folder: Path) -> int:
    model_path = folder / "report_stock_health.json"
    html_path = folder / "report_dashboard_stock_health.html"
    if not model_path.exists():
        print(f"[FAIL] no report model at {model_path}")
        return 1
    report = json.loads(model_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""

    header = report.get("header") or {}
    queue = report.get("queue") or []

    print("=" * 72)
    print(f"Inventory Management artifact audit: {folder.name}")
    print(f"  {report.get('report_name')} - {report.get('period_label')}")
    print("=" * 72)

    print("\n=== the queue is complete and correctly ordered ===")
    total_rows = sum(int(r.get("loc_skus") or 0) for r in queue)
    check("every product-location line is accounted for",
          close(total_rows, header.get("loc_skus")),
          f"queue={total_rows:,} vs model={header.get('loc_skus')}")
    ranks = [int(r.get("rank") or 0) for r in queue]
    check("the queue is sorted by urgency", ranks == sorted(ranks), ranks)
    doubles = [r for r in queue if r.get("double_warning")]
    if doubles:
        first_double = min(queue.index(r) for r in doubles)
        check("a double-warning state leads the queue", first_double == 0,
              f"first double warning at position {first_double}")
    check("every exception row tells the buying team what to do",
          all(r.get("guidance") for r in queue if r.get("is_exception")))

    print("\n=== the Opportunity Loss scope (the 6.4x trap) ===")
    scoped = float(header.get("opportunity_loss_day") or 0)
    unscoped = float(header.get("opportunity_loss_unscoped") or 0)
    check("the scoped figure is the one published",
          scoped <= unscoped, f"scoped={scoped} unscoped={unscoped}")
    if unscoped:
        check("and it is materially smaller, so the scope really was applied",
              scoped < unscoped, f"ratio={unscoped / scoped:.2f}x" if scoped else "")
    check("a caveat states the scope",
          any("stores only" in str(c) for c in report.get("caveats") or []))
    check("the published figure never appears as the unscoped one in prose",
          not any(f"{unscoped:,.0f}" in line for line in report.get("narrative") or [])
          or any("includes warehouses" in str(c) for c in report.get("caveats") or []))

    print("\n=== excess means the surplus, not the whole overstocked value ===")
    excess = float(header.get("excess_value") or 0)
    stock = float(header.get("stock_value") or 0)
    check("excess does not exceed total stock", excess <= stock * 1.0001,
          f"{excess:,.2f} vs {stock:,.2f}")
    overstock = next((r for r in queue if str(r.get("action")).upper() == "OVERSTOCK"), None)
    if overstock:
        check("excess is smaller than the stock value of overstocked lines",
              excess <= float(overstock.get("stock_value") or 0) * 1.0001,
              f"excess={excess:,.0f} overstocked stock={overstock.get('stock_value'):,.0f}")
    if stock:
        check("the excess share matches excess / stock",
              close(header.get("excess_share_pct"), excess / stock * 100.0))

    print("\n=== the report's own checks ===")
    for name, ok in (report.get("checks") or {}).items():
        check(f"  {name}", bool(ok))

    print("\n=== prose ===")
    known = _known(report)
    for line in report.get("narrative") or []:
        for text, suffix in re.findall(r"SAR\s([\d,]+(?:\.\d+)?)([MK]?)", line):
            value = float(text.replace(",", "")) * {"M": 1e6, "K": 1e3, "": 1}[suffix]
            check(f"  quoted 'SAR {text}{suffix}' exists in the model",
                  any(close(value, k, 1.0) for k in known),
                  f"no model figure within 1% of {value:,.2f}")
        for count in re.findall(r"(\d[\d,]{2,})\s+(?:lines|products)", line):
            value = float(count.replace(",", ""))
            check(f"  quoted count {count} exists in the model",
                  any(close(value, k, 0.01) for k in known))
        for pct in re.findall(r"(\d+\.\d+)%", line):
            check(f"  quoted {pct}% is rounded",
                  len(pct.split(".")[1]) <= MAX_QUOTED_DECIMALS)

    text = " ".join(report.get("narrative") or []).lower()
    hits = sorted(w for w in BANNED if w in text)
    check("no banned vocabulary reaches the reader", not hits, f"{hits}")
    check("no emojis", all(ord(ch) < 0x2190
                           for line in report.get("narrative") or [] for ch in line))

    print("\n=== the rendered document ===")
    if not html:
        print("  [note] no dashboard HTML was written, so it was not inspected")
    else:
        body = html.split("</style>", 1)[-1]
        check("the skeleton matches the shared stylesheet",
              '<div class="app" id="report">\n<nav class="rail"' in html
              and '<main><div class="page">' in html)
        check("exactly one script tag - the nav and toggle will work",
              html.count("<script") == 1, f"{html.count('<script')}")
        check("self-contained", "http://" not in html and "https://" not in html)
        check("every queue state appears in the document",
              all(str(r.get("action")) in html for r in queue),
              [r.get("action") for r in queue if str(r.get("action")) not in html])
        check("the 'as at' label is on the page",
              str(report.get("period_label")) in html)
        lower = html.lower()
        html_hits = sorted(w for w in BANNED if w in lower)
        check("no banned vocabulary in the document", not html_hits, f"{html_hits}")
        check("data is escaped", "<img" not in lower and "onerror" not in lower)

    print("\n" + "=" * 72)
    if _failures:
        print(f"STOCK HEALTH AUDIT FAILED - {len(_failures)} finding(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("STOCK HEALTH AUDIT CLEAN")
    return 0


def _known(report: dict) -> list[float]:
    values: list[float] = []

    def walk(node):
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            values.append(float(node))

    walk(report)
    return values


def main() -> int:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    if not folder.is_absolute():
        folder = PROJECT_ROOT / folder
    if not folder.is_dir():
        print(f"[FAIL] not a directory: {folder}")
        return 1
    return audit(folder)


if __name__ == "__main__":
    raise SystemExit(main())
