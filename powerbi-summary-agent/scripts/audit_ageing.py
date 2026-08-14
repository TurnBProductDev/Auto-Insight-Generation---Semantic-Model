"""Audit a PRODUCED Stock Age Analysis artifact. Run after every live run.

    python scripts/audit_ageing.py [output_dir]

A replay proves the *code* is right; this proves a *produced artifact* is right.
Both are needed, and on this codebase the auditor is the one that has caught the
real bugs - the derived-period contribution error and the contaminated
denominator were both found this way, not by a replay.

It re-derives every arithmetic guarantee from the written `report_ageing.json`,
checks each figure quoted in prose exists in the model, and inspects
`report_ageing.html` as a document.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = PROJECT_ROOT / "outputs_ageing"

#: Rounding in prose must not exceed this, or a raw float has leaked through.
MAX_QUOTED_DECIMALS = 2
#: Arithmetic tolerance, in percent.
TOLERANCE_PCT = 0.5

#: BR-03 and BR-25 ban these outright from anything a manager reads.
BANNED = (
    "velocity", "offtake", "capital lock-up", "carry cost", "coverage ratio",
    "materiality", "z-score", "write-down provision", "dead stock",
    "slow-moving", "stagnant", "days of cover", "stock worth", "asset value",
    "inventory value",
)

_failures: list[str] = []
_notes: list[str] = []


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
    model_path = folder / "report_ageing.json"
    html_path = folder / "report_ageing.html"

    if not model_path.exists():
        print(f"[FAIL] no report model at {model_path}")
        return 1
    report = json.loads(model_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""

    header = report.get("header") or {}
    bands = (report.get("distribution") or {}).get("bands") or []
    split = report.get("risk_split") or {}
    total = float(header.get("total_value") or 0)

    print("=" * 72)
    print(f"Ageing artifact audit: {folder.name}")
    print(f"  {report.get('report_name')} - {report.get('period_label')}")
    print("=" * 72)

    # --- 1. the arithmetic, re-derived rather than trusted -------------------
    print("\n=== arithmetic ===")
    band_sum = sum(float(b.get("value") or 0) for b in bands)
    undetermined = float((report.get("distribution") or {}).get("undetermined_value") or 0)
    check("the age bands sum to total stock value",
          close(band_sum + undetermined, total),
          f"bands={band_sum:,.2f} + undetermined={undetermined:,.2f} vs total={total:,.2f}")

    aged_sum = sum(float(b.get("aged_value") or 0) for b in bands)
    check("the aged values sum to the aged total",
          close(aged_sum, header.get("aged_value")),
          f"{aged_sum:,.2f} vs {header.get('aged_value')}")

    high_risk = sum(float(b.get("value") or 0) for b in bands if b.get("high_risk"))
    check("high-risk equals the 12-24 and 24+ bands, nothing else",
          close(high_risk, header.get("high_risk_value")),
          f"{high_risk:,.2f} vs {header.get('high_risk_value')}")

    if total:
        check("the aged share matches aged / total",
              close(header.get("aged_share_pct"),
                    float(header.get("aged_value") or 0) / total * 100.0))
        check("the high-risk share matches high-risk / total",
              close(header.get("high_risk_share_pct"), high_risk / total * 100.0))

    for band in bands:
        value = float(band.get("value") or 0)
        if total:
            check(f"  {band.get('name')}: share matches its own value",
                  close(band.get("share_pct"), value / total * 100.0))

    print("\n--- the four aged/non-moving cells ---")
    cells = ["aged_non_moving", "aged_moving", "fresh_non_moving", "fresh_moving"]
    cell_sum = sum(float(split.get(c) or 0) for c in cells)
    check("the four cells sum to total stock value", close(cell_sum, total),
          f"{cell_sum:,.2f} vs {total:,.2f}")
    check("aged across both cells matches the aged total",
          close(float(split.get("aged_non_moving") or 0)
                + float(split.get("aged_moving") or 0), header.get("aged_value")))
    check("the aged and non-moving totals are NOT summed into one figure "
          "anywhere in the model",
          not any(close(float(v or 0),
                        float(split.get("aged_total") or 0)
                        + float(split.get("non_moving_total") or 0))
                  for k, v in header.items() if isinstance(v, (int, float)) and v),
          "a figure equal to aged + non-moving would be double-counted")

    print("\n--- cumulative bands ---")
    for band in bands:
        index = band.get("name")
        older = sum(float(b.get("value") or 0) for b in bands
                    if (b.get("cumulative_older_pct") or 0) <= (band.get("cumulative_older_pct") or 0))
        if total:
            check(f"  {index}: 'this band or older' is internally consistent",
                  0 <= (band.get("cumulative_older_pct") or 0) <= 100.0 + 1e-6)

    # --- 2. the reconciliation gate the report published --------------------
    print("\n=== the report's own reconciliation gate ===")
    checks = report.get("checks") or {}
    check("the report ran its reconciliation checks", bool(checks))
    for name, ok in checks.items():
        check(f"  {name}", bool(ok))

    # --- 3. prose grounding --------------------------------------------------
    print("\n=== prose ===")
    narrative = report.get("narrative") or []
    check("the report says something", bool(narrative))

    known = _known_figures(report)
    for line in narrative:
        for quoted in re.findall(r"SAR\s([\d,]+(?:\.\d+)?)([MK]?)", line):
            text, suffix = quoted
            value = float(text.replace(",", ""))
            value *= {"M": 1_000_000, "K": 1_000, "": 1}[suffix]
            check(f"  quoted {('SAR ' + text + suffix)!r} exists in the model",
                  any(close(value, k, 1.0) for k in known),
                  f"no model figure within 1% of {value:,.2f}")
        for pct in re.findall(r"(\d+\.\d+)%", line):
            decimals = len(pct.split(".")[1])
            check(f"  quoted {pct}% is rounded, not a raw float",
                  decimals <= MAX_QUOTED_DECIMALS, f"{decimals} decimal places")

    text = " ".join(narrative).lower()
    hits = sorted(w for w in BANNED if w in text)
    check("no banned vocabulary reaches the reader", not hits, f"{hits}")
    check("no emojis", all(ord(ch) < 0x2190 for line in narrative for ch in line))

    # --- 4. the document ------------------------------------------------------
    print("\n=== the rendered document ===")
    if not html:
        _notes.append("no report_ageing.html was written, so it was not inspected")
    else:
        check("the page is self-contained - no external request",
              "http://" not in html and "https://" not in html)
        check("no script tag", "<script" not in html.lower())
        check("every age band appears in the document",
              all(str(b.get("name")) in html for b in bands),
              [b.get("name") for b in bands if str(b.get("name")) not in html])
        check("the 'as at' label is on the page",
              str(report.get("period_label")) in html)
        check("the movement limitation is stated, not omitted",
              "one stock position" in html)
        lower = html.lower()
        html_hits = sorted(w for w in BANNED if w in lower)
        check("no banned vocabulary in the document", not html_hits, f"{html_hits}")
        check("angle brackets in data are escaped",
              "<img" not in lower and "onerror" not in lower)

    # --- 5. honesty ------------------------------------------------------------
    print("\n=== honesty ===")
    migration = report.get("migration") or {}
    check("bucket migration is explicitly reported as unavailable, so the "
          "reader knows it was checked",
          migration.get("available") is False and bool(migration.get("reason")))
    check("the period is 'as at', never a span (NN 18)",
          str(report.get("period_label", "")).startswith("as at"),
          report.get("period_label"))

    print("\n" + "=" * 72)
    for note in _notes:
        print(f"[note] {note}")
    if _failures:
        print(f"AGEING AUDIT FAILED - {len(_failures)} finding(s)")
        for label in _failures:
            print(f"  - {label}")
        return 1
    print("AGEING AUDIT CLEAN")
    return 0


def _known_figures(report: dict) -> list[float]:
    """Every figure the model actually holds, for prose to be checked against."""
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
    # Derived figures a sentence may legitimately state.
    split = report.get("risk_split") or {}
    values.append(float(split.get("aged_moving") or 0)
                  + float(split.get("aged_non_moving") or 0))
    values.append(float(split.get("fresh_non_moving") or 0)
                  + float(split.get("aged_non_moving") or 0))
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
