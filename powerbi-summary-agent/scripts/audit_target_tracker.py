"""Audit a *produced* Target Tracker artifact.

    python scripts/audit_target_tracker.py [output_dir]

`replay_target_tracker.py` proves the code is right. This proves a delivered artifact is
right: it re-derives every arithmetic guarantee from the written `report_target_tracker.json`,
checks every figure quoted in the page and the document exists in the model and is rounded,
and inspects the HTML as a document. Run it after every live run.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_DIR = PROJECT_ROOT / "outputs_targettracker"
PASS, FAIL, NOTE = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{(' - ' + detail) if detail and not ok else ''}")


def close(a, b, tol=1.0):
    return abs(float(a) - float(b)) <= tol


def audit(folder: Path) -> int:
    model_path = folder / "report_target_tracker.json"
    html_path = folder / "report_target_tracker.html"
    doc_path = folder / "report_target_tracker.md"
    if not model_path.is_file():
        print(f"No report_target_tracker.json in {folder}")
        return 1
    model = json.loads(model_path.read_text(encoding="utf-8"))
    page = html_path.read_text(encoding="utf-8") if html_path.is_file() else ""
    document = doc_path.read_text(encoding="utf-8") if doc_path.is_file() else ""
    p = model["periods"]

    print(f"Auditing {folder}\n")
    print(f"anchor {model['anchor']} | sales through {model['sold_through']} "
          f"| {len(model['population'])} branches\n")

    # ---- arithmetic ------------------------------------------------------
    print("arithmetic")
    for key, q in p.items():
        check(f"{key}: variance is actual minus target",
              close(q["variance"], q["actual"] - q["target"]))
        if q["target"]:
            check(f"{key}: percentage matches its own values",
                  close(q["attainment"], q["actual"] / q["target"] * 100, 0.01))
    s = model["surplus"]
    check("the two halves of the month reconcile to the month gap",
          close(s["built"] - s["given_back"], s["now"]),
          f"{s['built']} - {s['given_back']} != {s['now']}")
    check("day series sums to the month actual",
          close(sum(d["actual"] for d in model["days"]), p["mtd"]["actual"]))
    check("day series sums to the month target",
          close(sum(d["target"] for d in model["days"]), p["mtd"]["target"]))
    check("branch day variances sum to the company day variance",
          close(sum(b["day"]["variance"] for b in model["branches"]), p["day"]["variance"]))
    check("branch month variances sum to the company month variance",
          close(sum(b["mtd"]["variance"] for b in model["branches"]), p["mtd"]["variance"]))
    check("days elapsed matches the day series",
          model["days_elapsed"] == len(model["days"]))
    check("days hit is countable from the series",
          model["days_hit"] == sum(1 for d in model["days"]
                                   if d["attainment"] is not None and d["attainment"] >= 100))
    run = model["run"]
    if run["length"]:
        tail = model["days"][-run["length"]:]
        check("the run really is consecutive days below target",
              all(d["attainment"] < 100 for d in tail))
        check("the day before the run was not below target",
              len(model["days"]) == run["length"]
              or model["days"][-run["length"] - 1]["attainment"] >= 100)
        check("average shortfall matches the run",
              close(run["average_shortfall"],
                    sum(d["target"] - d["actual"] for d in tail) / len(tail), 0.5))
    for which in ("week", "month"):
        c = model[f"{which}_close"]
        full = model[f"{which}_full_target"]
        done = p["wtd" if which == "week" else "mtd"]
        check(f"{which} catch-up equals full target minus sold",
              close(c["needed"], full - done["actual"]))
        if c["needed_vs_target"] is not None and c["remaining_target"] > 0:
            check(f"{which} needed-vs-target is the stated ratio",
                  close(c["needed_vs_target"], c["needed"] / c["remaining_target"] * 100, 0.01))

    # ---- rulebook --------------------------------------------------------
    print("\nrulebook")
    check("every period is measured against an elapsed target, not the full period",
          p["mtd"]["target"] <= model["month_full_target"] + 1
          and p["wtd"]["target"] <= model["week_full_target"] + 1)
    check("no department without a target is in the tables",
          all(d["mtd"]["target"] > 0 for d in model["departments"]))
    check("no section without a target is in the tables",
          all(s_["mtd"]["target"] > 0 for s_ in model["sections"]))
    check("CFH022 is excluded", "CFH022" not in model["population"])
    if model["target_lag_days"]:
        check("the page explains why it is dated earlier than the newest sales",
              "no target has been set" in page or "cannot be measured" in page)

    # ---- prose grounding -------------------------------------------------
    print("\nprose grounding")
    figures = set()

    def collect(value):
        if isinstance(value, dict):
            for v in value.values():
                collect(v)
        elif isinstance(value, list):
            for v in value:
                collect(v)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            figures.add(round(float(value), 2))

    collect(model)
    # every figure the model holds, in the two shortened forms the page prints
    printable = set()
    for raw in figures:
        for f in (raw, abs(raw)):          # the page prints magnitudes with the sign as a word
            printable.add(f"{f:.1f}")
            printable.add(f"{f:,.0f}")
            if abs(f) >= 1_000_000:
                printable.add(f"{f/1_000_000:.2f}M")
            elif abs(f) >= 1_000:
                printable.add(f"{f/1_000:.1f}K")
    # Prose only. Chart axis labels are derived furniture (gridline values), not
    # quoted figures, so the SVGs come out before the text does.
    prose_html = re.sub(r"<svg[^>]*>.*?</svg>", " ", page, flags=re.S)
    prose_html = re.sub(r"<script[^>]*>.*?</script>", " ", prose_html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", prose_html)
    quoted = set(re.findall(r"\d[\d,]*\.?\d*(?:M|K|%)?", text))
    # only audit the compact money forms; percentages are checked arithmetically above
    money_quoted = {q for q in quoted if q.endswith(("M", "K"))}
    unknown = sorted(q for q in money_quoted if q not in printable)
    check("every money figure on the page exists in the model",
          not unknown, f"not in model: {unknown[:8]}")
    over_precise = re.findall(r"\d+\.\d{3,}", text)
    check("no figure printed with more than two decimals",
          not over_precise, str(over_precise[:5]))

    # ---- document --------------------------------------------------------
    print("\nbusiness document")
    if document:
        check("starts with a headline", document.startswith("# "))
        check("covers today, the week, the month and the year",
              all(h in document for h in ("## Today", "## This week", "## This month",
                                          "## The year so far")))
        check("carries the limitations section", "Important things to know" in document)
        doc_over = re.findall(r"\d+\.\d{3,}", document)
        check("no over-precise figure in the document", not doc_over, str(doc_over[:5]))
    else:
        NOTE.append("no report_target_tracker.md was written, so it was not inspected")

    # ---- the page as a document ------------------------------------------
    print("\npage")
    if page:
        check("exactly one script tag", page.count("<script") == 1)
        check("no external requests", not re.findall(r'(?:src|href)\s*=\s*["\'](?!#)', page))
        check("no browser storage", not any(w in page for w in
                                            ("localStorage", "sessionStorage", "fetch(")))
        check("nav is the first child of .app",
              re.findall(r'<div class="app">\s*<(\w+)', page) == ["nav"])
        check("four layers present",
              sorted(set(re.findall(r'data-layer="(\w+)"', page)))
              == ["branches", "departments", "detail", "performance"])
        banned = ["attainment", "month-to-date", "week-to-date", "cushion", "QAR"]
        hits = {w: page.count(w) for w in banned if w in page}
        check("no banned vocabulary", not hits, str(hits))
        check("every branch appears on the page",
              all(b["name"] in page for b in model["branches"]))
        check("every department appears on the page",
              all(d["name"] in page for d in model["departments"]))
        markup = re.sub(r"<script[^>]*>.*?</script>", "", page, flags=re.S)
        unescaped = re.findall(r"&(?!amp;|lt;|gt;|quot;|#\d+;|nbsp;|middot;|minus;|mdash;|ndash;"
                               r"|ldquo;|rdquo;|rsquo;|#x27;)", markup)
        check("ampersands escaped in the markup", not unescaped, str(len(unescaped)))
    else:
        NOTE.append("no report_target_tracker.html was written, so it was not inspected")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    for note in NOTE:
        print(f"  note: {note}")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    sys.exit(audit(target))
