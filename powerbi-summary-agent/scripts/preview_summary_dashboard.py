"""Render a browsable R6 dashboard from saved run artifacts - no live run needed.

Reads a directory of already-written outputs (``summary_focus_universe.json``,
``summary_overall_performance.json``, ``summary_period_context.json``, and
optionally ``semantic_model_profile.json`` / ``summary_focus_evidence_by_key.json``)
and writes ``outputs_preview/report_dashboard_preview.html``.

    python scripts/preview_summary_dashboard.py [artifact_dir] [--out FILE]

Defaults to the most recent ``outputs*`` directory that has a usable overall
package. Deterministic prose only - no auth, no LLM, no Power BI call.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import summary_coverage, summary_dashboard, summary_dashboard_html  # noqa: E402

REQUIRED = "summary_focus_universe.json"
PACKAGE = "summary_overall_performance.json"


def _load(folder: Path, name: str) -> dict:
    path = folder / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _candidates() -> list[Path]:
    return sorted(
        (path for path in PROJECT_ROOT.glob("outputs*") if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _pick() -> tuple[Path, Path] | None:
    """A universe scan and an overall package, taken from the same run if possible."""
    folders = _candidates()
    for folder in folders:
        if (folder / REQUIRED).exists() and _load(folder, PACKAGE).get("status") == "ok":
            return folder, folder
    universe = next((f for f in folders if (f / REQUIRED).exists()), None)
    package = next((f for f in folders if _load(f, PACKAGE).get("status") == "ok"), None)
    if universe and package:
        return universe, package
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact_dir", nargs="?", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if args.artifact_dir:
        folder = Path(args.artifact_dir)
        if not folder.is_absolute():
            folder = PROJECT_ROOT / folder
        universe_dir = package_dir = folder
    else:
        picked = _pick()
        if not picked:
            print("No artifact directory with a usable universe scan and overall package.")
            print("Looked in: " + ", ".join(path.name for path in _candidates()) or "(none)")
            return 1
        universe_dir, package_dir = picked

    universe = _load(universe_dir, REQUIRED)
    package = _load(package_dir, PACKAGE)
    if not universe:
        print(f"{universe_dir / REQUIRED} not found or unreadable.")
        return 1
    period = _load(package_dir, "summary_period_context.json")
    evidence = _load(package_dir, "summary_focus_evidence_by_key.json")
    print(f"universe: {universe_dir.name}/{REQUIRED}")
    print(f"overall : {package_dir.name}/{PACKAGE} (status={package.get('status')})")

    coverage = summary_coverage.build_coverage(universe)
    levels = coverage.get("levels") or []
    if not levels:
        print("The universe scan produced no usable levels.")
        return 1
    entity_role = min(levels, key=lambda level: level.get("level") or 0)["role"]
    exposure_role = max(levels, key=lambda level: level.get("level") or 0)["role"]

    views = [summary_dashboard.build_view(
        "primary", f"{str(period.get('grain') or 'Period').title()} to date",
        package, coverage, period, {}, entity_role=entity_role,
        exposure_role=exposure_role, evidence_by_key=evidence)]
    row = summary_dashboard.latest_complete_period(package.get("trend"), period)
    families = summary_dashboard.families_from_trend_row(row, package.get("trend"))
    if families:
        views.append(summary_dashboard.build_view(
            "latest_period",
            f"Latest complete {period.get('grain') or 'period'}",
            package, coverage, period, {}, entity_role=entity_role,
            exposure_role=exposure_role, evidence_by_key=evidence,
            reference_members=[
                {"member": card.get("member"), "change_pct": card.get("change_pct")}
                for card in ((views[0].get("layers") or {}).get("entities") or {}).get("cards") or []
            ],
            families_override=families, trend_override=package.get("trend")))

    page = summary_dashboard.build(views, "Sales vs Previous Year")
    if page.get("status") != "ok":
        print(f"Page unavailable: {page.get('reason')}")
        return 1
    markup = summary_dashboard_html.render(page, coverage, 8)
    out = Path(args.out) if args.out else PROJECT_ROOT / "outputs_preview" / "report_dashboard_preview.html"
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markup, encoding="utf-8")
    print(f"entity level: {entity_role}   exposure level: {exposure_role}")
    print(f"views: {', '.join(str(view.get('key')) for view in page['views'])}")
    print(f"wrote {out}  ({len(markup):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
