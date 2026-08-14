"""Audit a PRODUCED dashboard output - not the code that made it.

``replay_summary_dashboard.py`` proves the logic is correct. This proves *this
particular file* is correct: it re-derives every arithmetic guarantee from the
written ``summary_dashboard.json``, re-runs prose grounding against the same view
model that was used to author it, and inspects ``report_dashboard.html`` as a
document. Run it after any live run, and after any change to the renderer.

    python scripts/audit_summary_dashboard.py [output_dir]

Defaults to the newest ``outputs*`` directory containing ``summary_dashboard.json``.
Exit code 0 means the artifact is internally consistent; 1 means it is not.
No auth, no LLM, no Power BI call - everything is checked from the files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import summary_levers  # noqa: E402
from src.tools.summary_validation import dashboard_rules  # noqa: E402

MODEL = "summary_dashboard.json"
MARKUP = "report_dashboard.html"

FAILURES: list[str] = []
NOTES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail and not ok else ""))
    if not ok:
        FAILURES.append(label)
    return ok


def note(text: str) -> None:
    NOTES.append(text)
    print(f"  [note] {text}")


def _num(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _close(left, right, tolerance: float) -> bool:
    left, right = _num(left), _num(right)
    if left is None or right is None:
        return False
    return abs(left - right) <= tolerance


# ---------------------------------------------------------------------------
def audit_arithmetic(view: dict) -> None:
    """Every number on the page has to come from, or agree with, another number."""
    key = view.get("key")
    measures = view.get("measures") or {}
    bridge = view.get("bridge")
    revenue = measures.get("revenue") or {}

    if not bridge:
        note(f"view {key!r}: no three-lever bridge (the page must say why)")
        check(f"view {key!r} states why the levers are absent",
              bool(view.get("limitations")), "no limitation recorded")
    else:
        effects = bridge.get("effects") or {}
        total = sum(_num(value) or 0.0 for value in effects.values())
        change = _num(bridge.get("revenue_change"))
        check(f"view {key!r}: three lever effects sum to the revenue change",
              _close(total, change, max(abs(change or 0.0) * 1e-6, 1.0)),
              f"{total} vs {change}")
        check(f"view {key!r}: growth factors multiply back to the revenue percentage",
              _close(bridge.get("factor_product_pct"), bridge.get("revenue_change_pct"), 1e-6),
              f"{bridge.get('factor_product_pct')} vs {bridge.get('revenue_change_pct')}")
        check(f"view {key!r}: bridge is marked reconciling",
              bridge.get("reconciles") is True)
        # The state name must match the signs actually present, not a stale label.
        levers = bridge.get("levers") or {}
        expected = summary_levers.lever_state(
            levers.get("transactions"), levers.get("basket_size"), levers.get("price"),
            revenue_pct=bridge.get("revenue_change_pct"))
        check(f"view {key!r}: lever state matches the lever signs",
              bridge.get("state") == expected, f"{bridge.get('state')!r} vs {expected!r}")

        steps = (view.get("hero") or {}).get("waterfall") or []
        if steps:
            running = (_num(steps[0].get("value")) or 0.0) + sum(
                _num(step.get("value")) or 0.0 for step in steps[1:-1])
            check(f"view {key!r}: waterfall closes on the current total",
                  _close(running, steps[-1].get("value"),
                         max(abs(_num(steps[-1].get('value')) or 0.0) * 1e-9, 1.0)),
                  f"{running} vs {steps[-1].get('value')}")

    # Ratio measures must match their own definition, so one definition holds
    # everywhere in the document.
    def ratio_ok(name: str, numerator: str, denominator: str) -> None:
        target, top, bottom = measures.get(name), measures.get(numerator), measures.get(denominator)
        if not (target and top and bottom):
            return
        for phase in ("current", "prior"):
            expected = (_num(top.get(phase)) or 0.0) / (_num(bottom.get(phase)) or 1.0)
            check(f"view {key!r}: {name} {phase} = {numerator}/{denominator}",
                  _close(target.get(phase), expected, abs(expected) * 1e-9 + 1e-9))

    ratio_ok("basket_value", "revenue", "transactions")
    ratio_ok("basket_size", "units", "transactions")
    ratio_ok("price", "revenue", "units")

    # Each KPI's percentage must agree with its own current/prior pair.
    for card in view.get("kpis") or []:
        current, prior = _num(card.get("current")), _num(card.get("prior"))
        if current is None or prior is None or not prior:
            continue
        expected = (current - prior) / abs(prior) * 100.0
        check(f"view {key!r}: {card.get('key')} percentage matches its own values",
              _close(card.get("change_pct"), expected, abs(expected) * 1e-6 + 1e-9))

    # Contributions are the claim "these add up to the group move". Verify it
    # against the period the member rows actually cover: when the view reports a
    # narrower period than the per-area scan, that is the SCANNED period, and the
    # page has to say so.
    contributions = ((view.get("layers") or {}).get("entities") or {}).get("contributions")
    owns = bool(view.get("owns_breakdowns", True))
    if not owns:
        # A view that does not own a breakdown must hold no breakdown rows at all
        # and must point the reader at the view that does.
        layers = view.get("layers") or {}
        note(f"view {key!r}: overview only - breakdowns belong to "
             f"{view.get('breakdown_owner')!r}")
        check(f"view {key!r}: holds no borrowed breakdown rows",
              contributions is None
              and not (layers.get("entities") or {}).get("cards")
              and not (layers.get("areas") or {}).get("entries")
              and not (layers.get("detail") or {}).get("growth")
              and not (layers.get("detail") or {}).get("decline"))
        check(f"view {key!r}: every breakdown layer points at its owner",
              all((layers.get(name) or {}).get("pointer")
                  for name in ("entities", "areas", "detail")))
        check(f"view {key!r}: names the span the scan covers",
              bool(view.get("breakdown_owner")))
    elif contributions:
        check(f"view {key!r}: contribution points sum to the group revenue percentage",
              _close(contributions.get("sums_to_pts"), revenue.get("change_pct"), 0.01),
              f"{contributions.get('sums_to_pts')} vs {revenue.get('change_pct')}")
        base = _num(revenue.get("prior"))
        if base:
            bad = [
                item.get("member") for item in contributions.get("items") or []
                if not _close(item.get("contribution_pts"),
                              (_num(item.get("change")) or 0.0) / abs(base) * 100.0, 1e-6)
            ]
            check(f"view {key!r}: every contribution is its own change over group prior",
                  not bad, f"mismatched: {bad[:3]}")
    else:
        note(f"view {key!r}: no entity contributions (the page must say why)")


def audit_prose(view: dict) -> None:
    """Re-run grounding on the prose that actually reached the file."""
    key = view.get("key")
    hero = view.get("hero") or {}
    cards = ((view.get("layers") or {}).get("entities") or {}).get("cards") or []
    areas = ((view.get("layers") or {}).get("areas") or {}).get("entries") or []
    draft = {
        "hero": {"headline": hero.get("headline"), "narrative": hero.get("narrative")},
        "entities": [{"member": card.get("member"), "story": card.get("story")}
                     for card in cards],
        "areas": [{"focus_key": entry.get("focus_key"),
                   "headline": entry.get("headline"),
                   "connect": entry.get("connect")}
                  for entry in areas if entry.get("connect") or entry.get("headline")],
    }
    errors = dashboard_rules(draft, view)
    check(f"view {key!r}: delivered prose is grounded and specific",
          not errors, "; ".join(errors[:3]))
    authored = [card.get("member") for card in cards if card.get("authored")]
    note(f"view {key!r}: {len(authored)} of {len(cards)} entity stories were LLM-authored")


def audit_coverage(page: dict, folder: Path, markup: str) -> None:
    """Coverage claims completeness. Check every member really is in the document."""
    coverage_path = folder / "summary_coverage.json"
    if not coverage_path.exists():
        note("summary_coverage.json not present; skipping completeness check")
        return
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    levels = coverage.get("levels") or []
    if not markup:
        note("no HTML present; skipping member-presence check")
        return
    import html as html_lib

    missing: list[str] = []
    total = 0
    for level in levels:
        for row in level.get("rows") or []:
            member = str(row.get("member") or "")
            if not member:
                continue
            total += 1
            if html_lib.escape(member, quote=True) not in markup:
                missing.append(f"{level.get('role')}/{member}")
    check(f"every one of {total} covered members appears in the document",
          not missing, f"missing {len(missing)}: {missing[:3]}")
    mirrored = coverage.get("mirrored_roles") or {}
    if mirrored:
        note(f"levels collapsed as duplicates (must be visible as a caveat): {mirrored}")
        check("the mirror collapse is disclosed in the document",
              "Not shown separately" in markup)


class _Balance(HTMLParser):
    VOID = {"meta", "br", "hr", "img", "input", "link", "circle", "rect", "path",
            "polyline", "line", "text", "use", "source", "col", "area"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.bad: list[tuple] = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            self.bad.append(("mismatch", tag))
            while self.stack and self.stack.pop() != tag:
                pass
        else:
            self.bad.append(("stray", tag))


def audit_markup(page: dict, markup: str) -> None:
    """The document has to survive being emailed, printed and opened offline."""
    parser = _Balance()
    parser.feed(markup)
    check("HTML is well formed", not parser.stack and not parser.bad,
          f"unclosed={parser.stack[:3]} bad={parser.bad[:3]}")
    check("nothing is fetched from outside the file",
          not re.search(r'(?:src|href)\s*=\s*"https?://', markup))
    check("no browser storage APIs",
          "localStorage" not in markup and "sessionStorage" not in markup)
    views = len(page.get("views") or [])
    check(f"all {views} view(s) are in the document",
          markup.count('class="view"') == views,
          f"found {markup.count(chr(34) + 'view' + chr(34))}")
    check("every view renders all four layers",
          markup.count('class="layer"') == views * 4,
          f"found {markup.count('class=' + chr(34) + 'layer' + chr(34))}")
    if views > 1:
        check("a view toggle is present", 'class="seg"' in markup)
    check("layer navigation is present", markup.count("rail-btn") >= 4)
    check("the executive summary is present", "tldr-item" in markup)
    check("charts are inline SVG", markup.count("<svg") >= 3)
    check("print rules force hidden views open",
          "@media print" in markup and "[hidden]" in markup)
    # A raw "<" or unescaped "&" outside script/style means an unescaped value.
    body = re.sub(r"<script.*?</script>", "", markup, flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    # Named, decimal AND hexadecimal character references are all valid escapes;
    # html.escape emits &#x27; for an apostrophe.
    check("no unescaped ampersands in the markup",
          not re.search(r"&(?![a-zA-Z]+;|#\d+;|#x[0-9a-fA-F]+;)", body))
    check("the report title is set", "<title>" in markup)


def audit_honesty(page: dict) -> None:
    """Whatever the page could not do, it has to say."""
    for caveat in page.get("caveats") or []:
        note(f"page caveat: {caveat}")
    for view in page.get("views") or []:
        calendar = view.get("calendar") or {}
        if calendar.get("comparator_effect"):
            note(f"view {view.get('key')!r}: comparator effect flagged - "
                 f"{len(calendar.get('exceptions') or [])} exception(s) named")
            check(f"view {view.get('key')!r}: a comparator caveat names its exceptions "
                  "or says none stood out",
                  calendar.get("exceptions") is not None)
        for card in ((view.get("layers") or {}).get("entities") or {}).get("cards") or []:
            if not card.get("comparable"):
                check(f"current-only entity {card.get('member')!r} is not shown as growth",
                      "never as growth" in str(card.get("story") or "")
                      or card.get("change_pct") is None)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", nargs="?", default=None)
    args = parser.parse_args()

    if args.output_dir:
        folder = Path(args.output_dir)
        if not folder.is_absolute():
            folder = PROJECT_ROOT / folder
    else:
        folders = sorted(
            (path for path in PROJECT_ROOT.glob("outputs*")
             if path.is_dir() and (path / MODEL).exists()),
            key=lambda path: path.stat().st_mtime, reverse=True)
        if not folders:
            print(f"No outputs* directory contains {MODEL}.")
            print("Run the agent with summary_r6_enabled, or point this at a directory.")
            return 1
        folder = folders[0]

    model_path = folder / MODEL
    if not model_path.exists():
        print(f"{model_path} not found.")
        return 1
    page = json.loads(model_path.read_text(encoding="utf-8"))
    markup_path = folder / MARKUP
    markup = markup_path.read_text(encoding="utf-8") if markup_path.exists() else ""

    print("=" * 72)
    print(f"AUDIT: {folder.name}")
    print("=" * 72)
    print(f"  model : {model_path.name} ({model_path.stat().st_size:,} bytes)")
    print(f"  markup: {markup_path.name if markup else '(absent)'}"
          + (f" ({markup_path.stat().st_size:,} bytes)" if markup else ""))
    print(f"  status={page.get('status')}  authoring={page.get('authoring_mode')}  "
          f"entity_role={page.get('entity_role')}  views="
          f"{[view.get('key') for view in page.get('views') or []]}")

    if page.get("status") != "ok":
        print(f"\n  page is not ok: {page.get('reason')}")
        return 1

    print("\n[1] arithmetic: does every figure agree with the others")
    for view in page.get("views") or []:
        audit_arithmetic(view)

    print("\n[2] prose: is every delivered sentence grounded and specific")
    for view in page.get("views") or []:
        audit_prose(view)

    print("\n[3] honesty: is every gap and caveat stated")
    audit_honesty(page)

    if markup:
        print("\n[4] document: self-contained, escaped, complete")
        audit_markup(page, markup)
        print("\n[5] coverage: is every member really in the file")
        audit_coverage(page, folder, markup)
    else:
        print(f"\n  ({MARKUP} not present - run with summary_r6_enabled to produce it)")

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for name in FAILURES:
            print(f"  - {name}")
        return 1
    print(f"ARTIFACT IS INTERNALLY CONSISTENT ({len(NOTES)} note(s) to read above)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
