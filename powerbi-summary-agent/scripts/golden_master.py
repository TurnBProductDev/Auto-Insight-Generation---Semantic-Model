"""Golden master: prove a refactor did not change the arithmetic.

    python scripts/golden_master.py              # verify (exit 1 on any difference)
    python scripts/golden_master.py --update     # re-record the snapshots
    python scripts/golden_master.py --source outputs_scanb

WP0 deliverable 1 of the domain-verticals programme. WP1, WP2, WP3, WP4 and WP6
all carry the same exit criterion - "byte-identical" - and this is the tool that
decides it. Offline: no auth, no LLM, no network.

Why it recomputes instead of comparing committed files
------------------------------------------------------
Byte-comparing a committed artifact against itself always passes and detects
nothing. So each case re-derives an artifact from committed *inputs* through the
*production* code path and byte-compares the result against a snapshot recorded
in ``tests/golden/``. When a refactor changes a formula, the recompute moves and
the comparison fails - which is the whole point.

Two tiers, because the first is not enough on its own
-----------------------------------------------------
* **Recomputed** - the net. Production functions over committed inputs.
* **Pinned inputs** - the anchor. Every input file is hashed too. Without this,
  the cheapest way to "fix" a failure is to edit the input until the output
  matches, which silently destroys the net. An input change is therefore
  reported as its own distinct failure, ahead of any recompute difference.

Normalisation is deliberately absent
------------------------------------
The brief allows normalising timestamps and absolute paths. Measured against
these artifacts, there are none: every time-ish key is business data (a model
column named ``UPDATED_DATE``, a trend's ``run_length``). So instead of
normalising - which can only ever blind the net - a tripwire *asserts* the
recomputed blob carries no run-varying data. If a run timestamp is ever
introduced into one of these artifacts, this fails and says so, rather than
quietly masking it.

Case parameters are pinned here, not read from config
----------------------------------------------------
``build_coverage`` takes materiality thresholds that a client config can set.
They are written out explicitly per case and recorded in the manifest, so
editing a config cannot move the goalposts. This net tests code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import semantic_profiler  # noqa: E402
from src.tools import summary_coverage, summary_dashboard, summary_dashboard_html  # noqa: E402

GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"
MANIFEST = GOLDEN_DIR / "manifest.json"
DEFAULT_ACTUAL_DIR = PROJECT_ROOT / "outputs_golden"
SCHEMA_VERSION = 1

# Committed acceptance runs the net is anchored to. Sources are independent
# pins: a real model each, so one going stale cannot hide behind another.
SOURCES = (
    "outputs_r4_acceptance",
    "outputs_r4_acceptance_20260730_fix",
    "outputs_scanb",
)

# Pinned case parameters. Explicit on purpose - see the module docstring.
COVERAGE_PARAMS = {"material_change_pct": 10.0, "material_share_pct": 5.0, "collapse_mirrors": True}
MOVERS_PARAMS = {"limit": 5}
DISPLAY_ROWS = 8
PAGE_TITLE = "Sales vs Previous Year"

# Run-varying data must not appear in a recomputed artifact. Absolute paths are
# unambiguous; a date carrying a *time* is nearly always a run stamp, whereas a
# bare date (data_as_of, window_start) is business data and stays.
_ABS_PATH = re.compile(r"[A-Za-z]:[\\/]{1,2}|/(?:home|Users)/|\\\\\\\\")
_RUN_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")

# The one bare date that IS run metadata: the rendered page stamps the day it
# was generated. This was missed when the net was first recorded, because the
# tripwire only looked for dates carrying a time - so the snapshot passed for a
# day and then failed the moment the date rolled over. A test that goes red on
# the calendar rather than on a code change is worse than no test, so this is
# normalised (which the brief explicitly permits for timestamps) rather than
# re-recorded daily.
#
# Deliberately narrow: it matches only the literal "Generated <date>" stamp.
# Business dates - data_as_of, window_start, an "as at" label - are the numbers
# under test and must never be normalised away.
_GENERATED = re.compile(r"Generated \d{4}-\d{2}-\d{2}")
_GENERATED_PLACEHOLDER = "Generated <run-date>"

MAX_DIFFS_SHOWN = 12


# ----------------------------------------------------------------- primitives


def _canonical(obj) -> str:
    """Stable text for byte-comparison: sorted keys, no incidental whitespace."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=repr)


def _sha256(blob: str) -> str:
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _load(folder: Path, name: str) -> dict:
    path = folder / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _rel(path: Path) -> str:
    """Repo-relative, forward-slashed, so a manifest is portable across machines."""
    return path.relative_to(PROJECT_ROOT).as_posix()


# ---------------------------------------------------------------- diagnostics


def _walk_paths(obj, prefix: str = ""):
    """Every leaf as (json_path, value), for a diff a human can act on."""
    if isinstance(obj, dict):
        for key in obj:
            yield from _walk_paths(obj[key], f"{prefix}.{key}")
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            yield from _walk_paths(item, f"{prefix}[{index}]")
    else:
        yield prefix or ".", obj


def _json_diff(expected, actual) -> list[str]:
    """Leaf-level differences, so a failure names the field that moved."""
    left = dict(_walk_paths(expected))
    right = dict(_walk_paths(actual))
    lines: list[str] = []
    for path in sorted(set(left) | set(right)):
        if path not in right:
            lines.append(f"    {path}: REMOVED (was {left[path]!r})")
        elif path not in left:
            lines.append(f"    {path}: ADDED ({right[path]!r})")
        elif left[path] != right[path]:
            lines.append(f"    {path}: {left[path]!r} -> {right[path]!r}")
    return lines


def _text_diff(expected: str, actual: str) -> list[str]:
    """First divergence in a rendered document, with a little context."""
    limit = min(len(expected), len(actual))
    offset = next((i for i in range(limit) if expected[i] != actual[i]), limit)
    start = max(0, offset - 60)
    return [
        f"    first difference at byte {offset:,} "
        f"(expected {len(expected):,} bytes, got {len(actual):,})",
        f"    expected: ...{expected[start:offset + 60]!r}",
        f"    actual  : ...{actual[start:offset + 60]!r}",
    ]


def _normalise(blob: str) -> str:
    """Remove the one piece of run metadata these artifacts carry.

    Applied identically when recording and when verifying, so a snapshot and a
    recomputation are compared on the same basis.
    """
    return _GENERATED.sub(_GENERATED_PLACEHOLDER, blob)


def _run_varying(blob: str) -> list[str]:
    """The tripwire. Anything here means the artifact is no longer comparable.

    Runs AFTER normalisation, so it reports only what normalisation did not
    already handle - which is how a newly introduced run stamp gets caught
    instead of silently time-bombing the snapshot.
    """
    found = []
    if _ABS_PATH.search(blob):
        found.append(f"absolute path: {_ABS_PATH.search(blob).group(0)!r}")
    if _RUN_STAMP.search(blob):
        found.append(f"run timestamp: {_RUN_STAMP.search(blob).group(0)!r}")
    if _GENERATED.search(blob):
        found.append(f"un-normalised generation stamp: "
                     f"{_GENERATED.search(blob).group(0)!r}")
    return found


# ---------------------------------------------------------------------- cases


class Case:
    """One recomputed artifact: how to build it, and where its snapshot lives."""

    def __init__(self, source: str, name: str, suffix: str, inputs: list[str], params: dict):
        self.source = source
        self.name = name
        self.suffix = suffix
        self.inputs = inputs
        self.params = params

    @property
    def key(self) -> str:
        return f"{self.source}:{self.name}"

    @property
    def snapshot(self) -> Path:
        return GOLDEN_DIR / self.source / f"{self.name}{self.suffix}"


def _dashboard_views(folder: Path, coverage: dict, package: dict, period: dict) -> list[dict]:
    """The R6 page as the pipeline builds it: the wide view, then the period view.

    Mirrors ``preview_summary_dashboard.py`` so the net covers the same code the
    preview exercises - including ``families_override``/``reference_members``,
    which is most of the period-view machinery WP2 will parameterise.
    """
    levels = coverage.get("levels") or []
    entity_role = min(levels, key=lambda level: level.get("level") or 0)["role"]
    exposure_role = max(levels, key=lambda level: level.get("level") or 0)["role"]
    evidence = _load(folder, "summary_focus_evidence_by_key.json")

    primary = summary_dashboard.build_view(
        "primary", f"{str(period.get('grain') or 'Period').title()} to date",
        package, coverage, period, {}, entity_role=entity_role,
        exposure_role=exposure_role, evidence_by_key=evidence)
    views = [primary]

    row = summary_dashboard.latest_complete_period(package.get("trend"), period)
    families = summary_dashboard.families_from_trend_row(row, package.get("trend"))
    if families:
        cards = ((primary.get("layers") or {}).get("entities") or {}).get("cards") or []
        views.append(summary_dashboard.build_view(
            "latest_period", f"Latest complete {period.get('grain') or 'period'}",
            package, coverage, period, {}, entity_role=entity_role,
            exposure_role=exposure_role, evidence_by_key=evidence,
            reference_members=[
                {"member": card.get("member"), "change_pct": card.get("change_pct")}
                for card in cards
            ],
            families_override=families, trend_override=package.get("trend")))
    return views


def discover_cases(sources=SOURCES) -> tuple[list[Case], list[str]]:
    """Which cases each committed run can support, and what it cannot.

    A source that lacks an input simply contributes fewer cases - the R5/R6
    artifacts postdate the r4 acceptance runs, and ``outputs_r4_acceptance``
    has an unavailable overall package, so it has no dashboard to rebuild.
    """
    cases: list[Case] = []
    notes: list[str] = []
    for source in sources:
        folder = PROJECT_ROOT / source
        if not folder.is_dir():
            notes.append(f"{source}: directory missing")
            continue

        if (folder / "model_metadata.json").exists():
            cases.append(Case(source, "semantic_profile", ".json", ["model_metadata.json"], {}))
        else:
            notes.append(f"{source}: no model_metadata.json - semantic profile not covered")

        if (folder / "summary_focus_universe.json").exists():
            cases.append(Case(source, "coverage", ".json",
                              ["summary_focus_universe.json"], dict(COVERAGE_PARAMS)))
            cases.append(Case(source, "top_movers", ".json",
                              ["summary_focus_universe.json"],
                              {**COVERAGE_PARAMS, **MOVERS_PARAMS}))
        else:
            notes.append(f"{source}: no summary_focus_universe.json - coverage not covered")

        package = _load(folder, "summary_overall_performance.json")
        if package.get("status") == "ok" and (folder / "summary_focus_universe.json").exists():
            inputs = ["summary_focus_universe.json", "summary_overall_performance.json"]
            for optional in ("summary_period_context.json", "summary_focus_evidence_by_key.json"):
                if (folder / optional).exists():
                    inputs.append(optional)
            cases.append(Case(source, "dashboard", ".json", list(inputs),
                              {**COVERAGE_PARAMS, "title": PAGE_TITLE}))
            cases.append(Case(source, "dashboard_html", ".html", list(inputs),
                              {**COVERAGE_PARAMS, "title": PAGE_TITLE,
                               "display_rows": DISPLAY_ROWS}))
        else:
            notes.append(
                f"{source}: overall package status="
                f"{package.get('status') or 'missing'!r} - dashboard not covered")
    return cases, notes


def compute(case: Case) -> str:
    """Recompute one artifact through the production code path."""
    folder = PROJECT_ROOT / case.source

    if case.name == "semantic_profile":
        return _canonical(semantic_profiler.build_profile(_load(folder, "model_metadata.json")))

    universe = _load(folder, "summary_focus_universe.json")
    coverage = summary_coverage.build_coverage(universe, **COVERAGE_PARAMS)

    if case.name == "coverage":
        return _canonical(coverage)
    if case.name == "top_movers":
        return _canonical(summary_coverage.top_movers(coverage, **MOVERS_PARAMS))

    package = _load(folder, "summary_overall_performance.json")
    period = _load(folder, "summary_period_context.json")
    page = summary_dashboard.build(
        _dashboard_views(folder, coverage, package, period), PAGE_TITLE)

    if case.name == "dashboard":
        return _canonical(page)
    if case.name == "dashboard_html":
        if page.get("status") != "ok":
            raise SystemExit(
                f"{case.key}: page status={page.get('status')!r} - cannot render "
                f"({page.get('reason')})")
        return _normalise(summary_dashboard_html.render(page, coverage, DISPLAY_ROWS))

    raise SystemExit(f"unknown case: {case.name}")


# ------------------------------------------------------------------ manifest


def _input_pins(cases: list[Case]) -> dict[str, str]:
    """sha256 of every input any case consumes."""
    pins: dict[str, str] = {}
    for case in cases:
        for name in case.inputs:
            path = PROJECT_ROOT / case.source / name
            key = _rel(path)
            if key not in pins:
                pins[key] = _sha256(path.read_text(encoding="utf-8"))
    return pins


def _read_manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise SystemExit(f"{_rel(MANIFEST)} is unreadable: {exc}")


# -------------------------------------------------------------------- update


def update(cases: list[Case], notes: list[str]) -> int:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    changed, created = [], []

    for case in cases:
        blob = compute(case)
        varying = _run_varying(blob)
        if varying:
            print(f"[FAIL] {case.key}: run-varying data present - "
                  f"{'; '.join(varying)}")
            print("       Recording this would make the net compare a moving target.")
            return 1
        case.snapshot.parent.mkdir(parents=True, exist_ok=True)
        previous = case.snapshot.read_text(encoding="utf-8") if case.snapshot.exists() else None
        if previous is None:
            created.append(case.key)
        elif previous != blob:
            changed.append(case.key)
        case.snapshot.write_text(blob, encoding="utf-8", newline="\n")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "python scripts/golden_master.py --update",
        "note": (
            "Recomputed snapshots plus pinned input hashes. Do not hand-edit: a "
            "difference in verify means the code changed, and the fix is to "
            "diagnose the code, not to re-record. See scripts/golden_master.py."
        ),
        "cases": {
            case.key: {
                "snapshot": _rel(case.snapshot),
                "inputs": [_rel(PROJECT_ROOT / case.source / name) for name in case.inputs],
                "params": case.params,
                "sha256": _sha256(case.snapshot.read_text(encoding="utf-8")),
            }
            for case in cases
        },
        "inputs": _input_pins(cases),
        "not_covered": notes,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n")

    print(f"recorded {len(cases)} case(s) into {_rel(GOLDEN_DIR)}")
    for key in created:
        print(f"  [NEW]     {key}")
    for key in changed:
        print(f"  [CHANGED] {key}")
    if not created and not changed:
        print("  (no snapshot content changed)")
    for note in notes:
        print(f"  [note] {note}")
    return 0


# -------------------------------------------------------------------- verify


def verify(cases: list[Case], notes: list[str], actual_dir: Path, sources: tuple[str, ...]) -> int:
    manifest = _read_manifest()
    if not manifest:
        print(f"[FAIL] no golden master recorded yet at {_rel(MANIFEST)}")
        print("       Run: python scripts/golden_master.py --update")
        return 1

    failures: list[str] = []
    # Scope the recorded set to the sources under test, so `--source X` reports
    # on X only. Without this, deliberately narrowing a run reads as eight
    # cases having vanished.
    recorded = {
        key: entry for key, entry in (manifest.get("cases") or {}).items()
        if key.split(":", 1)[0] in sources
    }

    # --- Tier B first. An edited input explains everything downstream of it,
    # --- and re-recording over it is how a net gets quietly disabled.
    print("Pinned inputs")
    pinned = {
        key: value for key, value in (manifest.get("inputs") or {}).items()
        if key.split("/", 1)[0] in sources
    }
    input_drift = []
    for key in sorted(pinned):
        path = PROJECT_ROOT / key
        if not path.exists():
            input_drift.append(f"{key}: MISSING")
            continue
        actual = _sha256(path.read_text(encoding="utf-8"))
        if actual != pinned[key]:
            input_drift.append(f"{key}: content changed")
    if input_drift:
        for line in input_drift:
            print(f"  [FAIL] {line}")
        print("  A committed acceptance artifact is an INPUT to this net. If you")
        print("  changed one deliberately, re-record; if you did not, restore it.")
        failures.extend(input_drift)
    else:
        print(f"  [PASS] {len(pinned)} input file(s) unchanged")

    # --- Case coverage. A case that silently disappears shrinks the net.
    print("\nCase coverage")
    discovered = {case.key for case in cases}
    missing = sorted(set(recorded) - discovered)
    added = sorted(discovered - set(recorded))
    if missing:
        for key in missing:
            print(f"  [FAIL] {key}: recorded but no longer discoverable "
                  f"(inputs removed?)")
        failures.extend(missing)
    if added:
        for key in added:
            print(f"  [FAIL] {key}: discoverable but not recorded")
        print("  Run --update to record new cases.")
        failures.extend(added)
    if not missing and not added:
        print(f"  [PASS] {len(discovered)} case(s), matching the manifest")

    # --- Tier A. The net itself.
    print("\nRecomputed artifacts")
    for case in sorted(cases, key=lambda c: c.key):
        entry = recorded.get(case.key)
        if not entry:
            continue
        if not case.snapshot.exists():
            print(f"  [FAIL] {case.key}: snapshot missing at {_rel(case.snapshot)}")
            failures.append(case.key)
            continue

        expected = case.snapshot.read_text(encoding="utf-8")
        if _sha256(expected) != entry.get("sha256"):
            print(f"  [FAIL] {case.key}: snapshot file does not match its manifest hash")
            print("         The snapshot was edited by hand. Restore it or re-record.")
            failures.append(case.key)
            continue

        if entry.get("params") != case.params:
            print(f"  [FAIL] {case.key}: case parameters changed")
            print(f"         recorded {entry.get('params')!r}")
            print(f"         current  {case.params!r}")
            failures.append(case.key)
            continue

        actual = compute(case)

        varying = _run_varying(actual)
        if varying:
            print(f"  [FAIL] {case.key}: run-varying data appeared - {'; '.join(varying)}")
            print("         This artifact is no longer stable enough to compare.")
            failures.append(case.key)
            continue

        if actual == expected:
            print(f"  [PASS] {case.key} ({len(actual):,} bytes)")
            continue

        print(f"  [FAIL] {case.key}: recomputed output differs from the golden master")
        if case.suffix == ".json":
            lines = _json_diff(json.loads(expected), json.loads(actual))
            for line in lines[:MAX_DIFFS_SHOWN]:
                print(line)
            if len(lines) > MAX_DIFFS_SHOWN:
                print(f"    ... and {len(lines) - MAX_DIFFS_SHOWN} more difference(s)")
        else:
            for line in _text_diff(expected, actual):
                print(line)
        written = actual_dir / case.source / case.snapshot.name
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(actual, encoding="utf-8", newline="\n")
        print(f"    actual written to {_rel(written)}")
        failures.append(case.key)

    for note in notes:
        print(f"\n[note] {note}")

    print("\n" + "=" * 72)
    if failures:
        print(f"GOLDEN MASTER FAILED - {len(failures)} difference(s)")
        print("The programme's exit criterion for WP1-WP4 and WP6 is byte-identical.")
        print("A difference means the refactor changed arithmetic: revert and")
        print("diagnose. Do NOT adjust the expected values (brief, Part 6.3).")
        return 1
    print("GOLDEN MASTER CLEAN - every recomputed artifact is byte-identical")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--update", action="store_true",
                        help="re-record the snapshots and manifest")
    parser.add_argument("--source", action="append", default=None,
                        help="limit to one committed run (repeatable)")
    parser.add_argument("--out", default=None,
                        help=f"where to write actuals on failure (default {_rel(DEFAULT_ACTUAL_DIR)})")
    args = parser.parse_args()

    sources = tuple(args.source) if args.source else SOURCES
    unknown = [source for source in sources if source not in SOURCES]
    if unknown:
        raise SystemExit(f"unknown source(s): {', '.join(unknown)}\nknown: {', '.join(SOURCES)}")

    if args.update and set(sources) != set(SOURCES):
        # Recording a narrowed set would drop every other source's case from the
        # manifest, shrinking the net without saying so.
        raise SystemExit(
            "--update rewrites the whole manifest and cannot be combined with "
            "--source.\nUse --source to verify a subset; re-record with plain "
            "--update.")

    cases, notes = discover_cases(sources)
    if not cases:
        print("No committed acceptance artifacts found - nothing to compare.")
        print(f"Expected at least one of: {', '.join(SOURCES)}")
        return 1

    if args.update:
        return update(cases, notes)

    actual_dir = Path(args.out) if args.out else DEFAULT_ACTUAL_DIR
    if not actual_dir.is_absolute():
        actual_dir = PROJECT_ROOT / actual_dir
    return verify(cases, notes, actual_dir, sources)


if __name__ == "__main__":
    raise SystemExit(main())
