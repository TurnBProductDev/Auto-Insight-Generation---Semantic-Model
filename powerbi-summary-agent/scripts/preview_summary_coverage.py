"""Render the coverage report shell from a saved universe scan - no auth, no LLM.

Builds the full-coverage tables from an existing ``summary_focus_universe.json``
and writes a browsable ``report_summary_preview.html``. Useful for reviewing the
layout, badges and search behaviour without spending a live run.

    python scripts/preview_summary_coverage.py
    python scripts/preview_summary_coverage.py --universe outputs/summary_focus_universe.json
    python scripts/preview_summary_coverage.py --summary outputs/fresh_summary.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import summary_coverage, summary_visual  # noqa: E402

def _discover_universes() -> list[Path]:
    """Candidate universe files, most-preferred first.

    A live ``outputs/`` wins; otherwise prefer a directory that ALSO has a
    ``fresh_summary.json`` with authored narrative, so the preview shows the
    whole page (Overall Performance + focuses + coverage) rather than the
    coverage tables on their own.
    """
    live = PROJECT_ROOT / "outputs" / "summary_focus_universe.json"
    if live.exists():
        return [live]
    found = sorted(PROJECT_ROOT.glob("outputs*/summary_focus_universe.json"))

    def rank(path: Path) -> tuple:
        summary = path.parent / "fresh_summary.json"
        blocks = 0
        if summary.exists():
            try:
                blocks = len(json.loads(summary.read_text(encoding="utf-8")).get("content_blocks") or [])
            except (ValueError, OSError):
                blocks = 0
        # More narrative blocks first, then the most recently written file.
        return (-blocks, -path.stat().st_mtime)

    return sorted(found, key=rank)


def _resolve_universe(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists():
            raise SystemExit(f"universe file not found: {path}")
        return path
    candidates = _discover_universes()
    if candidates:
        return candidates[0]
    raise SystemExit(
        "no summary_focus_universe.json found. Run the pipeline once, or pass --universe."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe", help="path to a summary_focus_universe.json")
    parser.add_argument("--summary", help="optional fresh_summary.json for the narrative blocks")
    parser.add_argument("--out", default="outputs_preview/report_summary_preview.html")
    parser.add_argument("--rows", type=int, default=8, help="rows shown per level before 'show all'")
    parser.add_argument("--change-pct", type=float, default=10.0)
    parser.add_argument("--share-pct", type=float, default=5.0)
    args = parser.parse_args()

    universe_path = _resolve_universe(args.universe)
    universe = json.loads(universe_path.read_text(encoding="utf-8"))
    coverage = summary_coverage.build_coverage(
        universe,
        material_change_pct=args.change_pct,
        material_share_pct=args.share_pct,
    )

    # Default to the narrative that belongs to this universe, so Overall
    # Performance and the focus write-ups appear above the coverage tables
    # exactly as they do in a real run.
    summary_path = Path(args.summary) if args.summary else (universe_path.parent / "fresh_summary.json")
    if not summary_path.is_absolute():
        summary_path = PROJECT_ROOT / summary_path
    summary: dict = {"heading": "Coverage preview"}
    if summary_path.exists():
        loaded = json.loads(summary_path.read_text(encoding="utf-8"))
        if loaded.get("content_blocks"):
            summary = loaded
        else:
            print(f"note: {summary_path.name} has no authored blocks - coverage only")
    elif args.summary:
        raise SystemExit(f"summary file not found: {summary_path}")

    html = summary_visual.render(
        summary,
        title="AI Summary (coverage preview)",
        coverage=coverage,
        coverage_display_rows=args.rows,
    )
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = PROJECT_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")

    print(f"universe : {universe_path}")
    print(f"narrative: {summary_path.name if summary.get('content_blocks') else 'none (coverage only)'}"
          + (f" ({len(summary.get('content_blocks') or [])} blocks)" if summary.get("content_blocks") else ""))
    print(f"status   : {coverage.get('status')}")
    for level in coverage.get("levels") or []:
        counts = level["counts"]
        print(
            f"  {level['role']:<12} {counts['total']:>3} covered | "
            f"{counts['up']:>3} up | {counts['down']:>3} down | "
            f"{counts['critical']:>2} need attention | "
            f"{counts['current_only']:>2} not comparable"
        )
    if coverage.get("skipped_roles"):
        print(f"  skipped  : {coverage['skipped_roles']}")
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
