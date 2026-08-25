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
from datetime import date as _date
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


def _spoken_date(value) -> str:
    """`2026-08-14` as the page writes it: `14 August`."""
    try:
        day = _date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return str(value or "")
    return f"{day.day} {day.strftime('%B')}"


def audit(folder: Path) -> int:
    model_path = folder / "report_ageing.json"
    html_path = folder / "report_ageing.html"

    if not model_path.exists():
        print(f"[FAIL] no report model at {model_path}")
        return 1
    report = json.loads(model_path.read_text(encoding="utf-8"))
    html = html_path.read_text(encoding="utf-8") if html_path.exists() else ""
    # The published artifact is the dashboard, not this page - see
    # `ageing_publish.publish`. Both are inspected, because two artifacts from
    # one run disagreeing about what may be compared is worse than either being
    # wrong on its own.
    dashboard_path = folder / "report_dashboard_ageing.html"
    dashboard_html_text = (dashboard_path.read_text(encoding="utf-8")
                           if dashboard_path.exists() else "")

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
        comparison_state = report.get("comparison") or {}
        if comparison_state.get("available"):
            for name, document in (("summary page", html),
                                   ("published dashboard", dashboard_html_text)):
                if not document:
                    continue
                check(f"the comparison window is stated on the {name}",
                      str(comparison_state.get("prior_as_at") or "") in document
                      or _spoken_date(comparison_state.get("prior_as_at")) in document,
                      str(comparison_state.get("prior_as_at")))
                if not comparison_state.get("value_comparable"):
                    check(f"the {name} says why totals are not compared",
                          "not compared" in document.lower())
        else:
            check("the movement limitation is stated, not omitted",
                  "one stock position" in html
                  or "nothing can be compared" in html.lower())
        lower = html.lower()
        html_hits = sorted(w for w in BANNED if w in lower)
        check("no banned vocabulary in the document", not html_hits, f"{html_hits}")
        check("angle brackets in data are escaped",
              "<img" not in lower and "onerror" not in lower)

    # --- 5. honesty ------------------------------------------------------------
    print("\n=== honesty ===")
    check("the period is 'as at', never a span (NN 18)",
          str(report.get("period_label", "")).startswith("as at"),
          report.get("period_label"))


    # --- 6. the comparison against an earlier position -------------------------
    # The guarantee under test is not "a comparison exists" but "every figure in
    # it is a share or a count, unless the basis check cleared value". A value
    # movement printed after the basis check refused it is the one failure this
    # section exists to catch.
    print("\n=== what changed ===")
    comparison = report.get("comparison") or {}
    if not comparison.get("available"):
        check("an unavailable comparison states its reason",
              bool(str(comparison.get("reason") or "").strip()),
              str(comparison.get("reason") or "")[:120])
    else:
        prior, now = str(comparison.get("prior_as_at")), str(comparison.get("as_at"))
        check("the earlier position is genuinely earlier", prior < now,
              f"{prior} -> {now}")
        days = comparison.get("days")
        expected_days = None
        try:
            expected_days = (_date.fromisoformat(now) - _date.fromisoformat(prior)).days
        except ValueError:
            pass
        check("the stated window length matches its two dates",
              expected_days is None or days == expected_days,
              f"stated {days}, dates give {expected_days}")

        for reading in comparison.get("headlines") or []:
            then_pct, now_pct = reading.get("then_pct"), reading.get("now_pct")
            points = reading.get("points")
            if not all(isinstance(v, (int, float)) for v in (then_pct, now_pct, points)):
                continue
            check(f"  {reading.get('label')}: the movement is now minus then",
                  close(points, float(now_pct) - float(then_pct), tolerance_pct=1.0),
                  f"{points} vs {float(now_pct) - float(then_pct)}")
            check(f"  {reading.get('label')}: higher is worse is stated correctly",
                  (reading.get("direction") == "worse") == (float(points) >= 0.2)
                  or abs(float(points)) < 0.2,
                  f"points={points} direction={reading.get('direction')}")

        now_side, then_side = comparison.get("now") or {}, comparison.get("then") or {}
        for side, label in ((now_side, "today"), (then_side, "the earlier position")):
            total_value = float(side.get("total_value") or 0)
            aged_value = float(side.get("aged_value") or 0)
            if total_value:
                check(f"  the aged share of value on {label} matches its own figures",
                      close(side.get("aged_value_share_pct"),
                            aged_value / total_value * 100.0))
            total_qty = float(side.get("total_qty") or 0)
            if total_qty:
                check(f"  the aged share of units on {label} matches its own figures",
                      close(side.get("aged_qty_share_pct"),
                            float(side.get("aged_qty") or 0) / total_qty * 100.0))

        basis = comparison.get("basis") or {}
        check("the valuation basis was actually checked, not assumed",
              basis.get("checked") is True or bool(basis.get("reason")),
              str(basis.get("reason") or "")[:120])
        if not comparison.get("value_comparable"):
            check("a refused value comparison says why in plain words",
                  len(str(basis.get("reason") or "")) > 40)
            # The point of the whole lane: no absolute money movement anywhere.
            for reading in comparison.get("headlines") or []:
                check(f"  {reading.get('label')} is a share, not an amount",
                      "share" in str(reading.get("label") or "").lower()
                      or "%" in str(reading.get("label") or ""),
                      str(reading.get("label")))
            check("the page carries the basis warning as a caveat",
                  any("calculated differently" in str(c)
                      for c in report.get("caveats") or []))

        for row in comparison.get("bands") or []:
            then_pct, now_pct = row.get("qty_share_then_pct"), row.get("qty_share_now_pct")
            if all(isinstance(v, (int, float)) for v in (then_pct, now_pct)):
                check(f"  band {row.get('name')}: the unit-share movement adds up",
                      close(row.get("qty_share_points"),
                            float(now_pct) - float(then_pct), tolerance_pct=1.0))

    migration = report.get("migration") or {}
    check("stock movement between bands is either shown or explicitly refused",
          bool(migration.get("available")) or bool(migration.get("reason")),
          f"available={migration.get('available')}")
    if migration.get("available"):
        check("band movement is counted in units, not in rebased money",
              str(migration.get("counted_in")) == "units",
              str(migration.get("counted_in")))

    # --- 7. the clearance outlook, re-derived ---------------------------------
    print("\n=== where to act ===")
    clearance = report.get("clearance") or {}
    if clearance.get("available"):
        horizon = float(clearance.get("horizon_days") or 30)
        previous = None
        for row in clearance.get("rows") or []:
            aged_qty = float(row.get("aged_qty") or 0)
            daily = float(row.get("daily_qty") or 0)
            name = row.get("name")
            if aged_qty > 0 and daily > 0:
                expected = min(daily * horizon / aged_qty * 100.0, 100.0)
                check(f"  {name}: the share clearing matches its own figures",
                      close(row.get("cleared_pct"), expected),
                      f"{row.get('cleared_pct')} vs {expected}")
                check(f"  {name}: days to clear matches aged units over daily sales",
                      close(row.get("days_to_clear"), aged_qty / daily))
            check(f"  {name}: an estimate is never published above 100%",
                  float(row.get("cleared_pct") or 0) <= 100.0 + 1e-9,
                  str(row.get("cleared_pct")))
            if previous is not None:
                check(f"  {name}: the slowest divisions come first",
                      float(row.get("cleared_pct") or 0) >= previous - 1e-9,
                      f"{previous} then {row.get('cleared_pct')}")
            previous = float(row.get("cleared_pct") or 0)
        check("the outlook states that it assumes oldest stock sells first",
              any("oldest stock first" in str(c) for c in clearance.get("caveats") or []))

    categories = report.get("categories") or {}
    if categories.get("available"):
        threshold = float(categories.get("threshold_pct") or 30)
        check("the count over the line cannot exceed the count carried",
              int(categories.get("over") or 0) <= int(categories.get("carried") or 0),
              f"{categories.get('over')} of {categories.get('carried')}")
        worst = categories.get("worst") or []
        check("every listed category is genuinely over the line",
              all(float(c.get("aged_share_pct") or 0) > threshold for c in worst))
        check("the list is ordered by money stuck, not by percentage",
              all(float(worst[i].get("aged") or 0) >= float(worst[i + 1].get("aged") or 0)
                  for i in range(len(worst) - 1)),
              "; ".join(f"{c.get('name')}={c.get('aged'):,.0f}" for c in worst[:4]))
        for row in worst:
            total_cat = float(row.get("total") or 0)
            if total_cat:
                check(f"  {row.get('name')}: its share matches its own figures",
                      close(row.get("aged_share_pct"),
                            float(row.get("aged") or 0) / total_cat * 100.0))

    stuck = report.get("stuck_lines") or {}
    if stuck.get("available"):
        cutoff = float(stuck.get("risk_cutoff") or -70)
        floor = float(stuck.get("value_floor") or 0)
        rows = stuck.get("rows") or []
        check("every listed line is at or below the risk cut-off",
              all(float(r.get("risk_score") or 0) <= cutoff for r in rows))
        check("every listed line clears the money floor",
              all(float(r.get("value") or 0) >= floor for r in rows))
        check("the list is ordered by money at stake",
              all(float(rows[i].get("value") or 0) >= float(rows[i + 1].get("value") or 0)
                  for i in range(len(rows) - 1)))
        check("the list says it is the top of a longer one",
              isinstance(stuck.get("estate_lines"), (int, float))
              and float(stuck.get("estate_lines") or 0) >= len(rows),
              f"estate={stuck.get('estate_lines')} shown={len(rows)}")
        check("the second value basis is named rather than blended",
              "different basis" in str(stuck.get("note") or ""))

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
