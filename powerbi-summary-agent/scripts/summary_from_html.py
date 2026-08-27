"""Extract the app's summary payload from a hand-authored insight page.

The app needs TWO blobs per report. The `.html` is the full page a user opens;
the `.json` is what the Home strip renders, and without it the report has no
summary card even though the page exists. These pages were written without one.

Everything here is COPIED, never composed. The page already states its own
verdict, its own KPIs and its own ranked findings, so the payload is an
extraction, not a summarisation - nothing is inferred, reworded or rounded, and
a page missing a part yields a payload missing that part rather than an invented
one.

The pages share one structure (verified across all seven):

    <h1>                    the report title
    <span class="verdict">  the TL;DR sentence      -> headline
    <li class="tldr-item">  ranked findings          -> "What matters most"
    <div class="card kpi">  label / value / note     -> metrics + "Headline figures"

Tone comes from the page's own CSS modifier, so the colour a reader sees on the
page is the colour the app shows: `flagged` is critical, `warn` is warning,
and an unmodified card is info.

    python scripts/summary_from_html.py page.html --out payload.json
    python scripts/summary_from_html.py page.html --title "Margin Analytics"
"""
from __future__ import annotations

import argparse
import html as htmllib
import json
import re
import sys
from pathlib import Path

MAX_METRICS = 6
TONE_BY_CLASS = {"flagged": "critical", "warn": "warning", "": "info"}


def text(fragment: str) -> str:
    """Visible text of a fragment, with entities resolved and spacing sane."""
    fragment = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    fragment = htmllib.unescape(fragment)
    # These pages use non-breaking hyphens and spaces for typography; a JSON
    # consumer wants the plain characters.
    fragment = (fragment.replace("‑", "-").replace(" ", " ")
                        .replace(" ", " ").replace(" ", " "))
    return re.sub(r"\s+", " ", fragment).strip()


def first(pattern: str, source: str) -> str:
    m = re.search(pattern, source, re.S | re.I)
    return text(m.group(1)) if m else ""


def extract(source: str) -> dict:
    body = re.sub(r"<script.*?</script>|<style.*?</style>", "", source, flags=re.S | re.I)

    title = first(r"<h1[^>]*>(.*?)</h1>", body)
    headline = first(r'<span class="verdict"[^>]*>(.*?)</span>', body)

    metrics, figures = [], []
    for m in re.finditer(
            r'<div class="card kpi([^"]*)"[^>]*>\s*'
            r'<span class="lab"[^>]*>(.*?)</span>\s*'
            r'<span class="val"[^>]*>(.*?)</span>'
            r'(?:\s*<span class="note[^"]*"[^>]*>(.*?)</span>)?', body, re.S | re.I):
        modifier = (m.group(1) or "").strip()
        label, value, note = text(m.group(2)), text(m.group(3)), text(m.group(4) or "")
        if not label or not value:
            continue
        if len(metrics) < MAX_METRICS:
            metrics.append({"label": label, "value": value,
                            "tone": TONE_BY_CLASS.get(modifier, "info")})
        figures.append(f"{label}: {value}" + (f" - {note}" if note else ""))

    findings = [text(m.group(1)) for m in
                re.finditer(r'<span class="tldr-txt"[^>]*>(.*?)</span>\s*</li>', body, re.S | re.I)]
    findings = [f for f in findings if f]

    sections = []
    if findings:
        sections.append({"heading": "What matters most", "tone": "critical",
                         "points": findings})
    if figures:
        sections.append({"heading": "Headline figures", "tone": "info",
                         "points": figures[:12]})
    return {"title": title, "headline": headline, "metrics": metrics, "sections": sections}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("page", type=Path)
    ap.add_argument("--out", type=Path, help="write the payload here")
    ap.add_argument("--title", help="override the title (use the report's name in the app)")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    payload = extract(args.page.read_text(encoding="utf-8", errors="replace"))
    if args.title:
        payload["title"] = args.title

    missing = [k for k in ("title", "headline") if not payload.get(k)]
    print(f"{args.page.name}")
    print(f"  title    {payload['title']!r}")
    print(f"  headline {payload['headline'][:96]!r}")
    print(f"  metrics  {len(payload['metrics'])}   sections {len(payload['sections'])}"
          f"   points {sum(len(s['points']) for s in payload['sections'])}")
    if missing:
        print(f"  MISSING: {', '.join(missing)} - the page has no such element")
    if args.out:
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                            encoding="utf-8")
        print(f"  written  {args.out}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
