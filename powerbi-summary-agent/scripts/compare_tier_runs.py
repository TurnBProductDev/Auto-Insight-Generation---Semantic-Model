"""Compare one day's shadow runs of the same report on different AI tiers.

    python scripts/compare_tier_runs.py outputs/shadow_narrated \
        outputs/shadow_investigated outputs/shadow_reasoned
    python scripts/compare_tier_runs.py ... --archive outputs/shadow_days/2026-10-08

Offline: it only reads the run folders. Phase 5 of
`docs/reasoned-tier-implementation-plan.md`. For each folder it prints the
measures the plan's acceptance criteria are written in:

* cost (USD), model calls and run seconds - `token_usage.json`, `run_log.txt`;
* findings published and merges - `insight_signals.json`;
* per finding: recipe calls, custom DAX, refusals, cache hits, and whether the
  investigation concluded or was forced - `insight_investigations.json`;
* findings whose published explanation adds a fact beyond the standard drill:
  a member or a figure that only a follow-up query returned;
* code fallbacks: a rejected conclusion, a failed selection call, prose slots
  kept on code wording - the trails, `insight_novelty.json`,
  `summary_authoring_attempts.json`;
* errors in the run log, and `audit_summary_dashboard.py`'s verdict.

``--archive DIR`` copies each folder (and the comparison) under DIR, because
the next day's run overwrites the output folder.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.summary_validation import parse_numbers  # noqa: E402

ANSWERED = ("success", "cache_hit")


def _load(folder: Path, name: str, default=None):
    path = folder / name
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _seconds(folder: Path) -> int | None:
    stamps = re.findall(r"^\[(\d\d):(\d\d):(\d\d)\]", (folder / "run_log.txt").read_text(encoding="utf-8"),
                        re.MULTILINE) if (folder / "run_log.txt").is_file() else []
    if len(stamps) < 2:
        return None
    first, last = (int(h) * 3600 + int(m) * 60 + int(s) for h, m, s in (stamps[0], stamps[-1]))
    return (last - first) % 86400


def _labels(rows: list) -> set[str]:
    return {v for r in rows or [] if isinstance(r, dict) for v in r.values()
            if isinstance(v, str) and v.strip()}


def _numbers(rows: list) -> list[float]:
    return [float(v) for r in rows or [] if isinstance(r, dict) for v in r.values()
            if isinstance(v, (int, float)) and not isinstance(v, bool)]


def _follow_ups(inv: dict) -> list[dict]:
    """Queries beyond the standard drill: recipe or custom calls, or (investigated)
    the investigator's own run_dax probes."""
    return [p for p in inv.get("probes") or []
            if p.get("tool") == "run_dax" and p.get("origin") != "gap_scan"]


def _adds_fact(inv: dict) -> bool:
    """Does the published explanation name a member or quote a figure that only a
    follow-up query returned?"""
    if inv.get("explanation_source") == "code":
        return False
    text = str(inv.get("explanation") or "")
    drill = [p.get("rows") or [] for p in inv.get("probes") or [] if p.get("origin") == "gap_scan"]
    drill_labels = set().union(*(_labels(r) for r in drill)) if drill else set()
    drill_numbers = [n for r in drill for n in _numbers(r)]
    for probe in _follow_ups(inv):
        if probe.get("status") not in ANSWERED:
            continue
        rows = probe.get("rows") or []
        if any(label in text for label in _labels(rows) - drill_labels):
            return True
        new = [n for n in _numbers(rows)
               if not any(abs(n - d) <= abs(d) * 0.0005 for d in drill_numbers)]
        for value, tolerance, _token in parse_numbers(text):
            if any(abs(value - n) <= max(tolerance, abs(n) * 0.0005) or
                   abs(value - abs(n)) <= max(tolerance, abs(n) * 0.0005) for n in new):
                return True
    return False


def _prose_fallbacks(attempts: dict) -> dict[str, str]:
    out = {}
    for writer, records in (attempts.get("writers") or {}).items():
        for record in records or []:
            if writer == "insight_deterministic":
                out["key_insights"] = f"{record.get('authored')}/{record.get('slots')} by model"
            elif writer == "fresh_summary_generator":
                slots = record.get("slots") or {}
                out["summary"] = (f"{slots.get('model')}/{slots.get('total')} slots by model"
                                  if slots else str(record.get("outcome")))
            elif writer == "summary_dashboard_builder":
                out.setdefault("dashboard", [])
                out["dashboard"].append(str(record.get("outcome")))
            elif writer == "api_payloads":
                out["kpi_cards"] = str(record.get("outcome"))
    if isinstance(out.get("dashboard"), list):
        out["dashboard"] = ", ".join(out["dashboard"])
    return out


def _audit(folder: Path) -> str:
    result = subprocess.run([sys.executable, "scripts/audit_summary_dashboard.py", str(folder)],
                            cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    return "clean" if result.returncode == 0 else f"FAILED (exit {result.returncode})"


def summarise(folder: Path) -> dict:
    usage = _load(folder, "token_usage.json", {}) or {}
    signals = _load(folder, "insight_signals.json", []) or []
    investigations = _load(folder, "insight_investigations.json", []) or []
    novelty = _load(folder, "insight_novelty.json", {}) or {}
    attempts = _load(folder, "summary_authoring_attempts.json", {}) or {}
    log = (folder / "run_log.txt").read_text(encoding="utf-8") if (folder / "run_log.txt").is_file() else ""
    total = usage.get("total") or {}
    findings = []
    for inv in investigations:
        follow = _follow_ups(inv)
        tools = [p.get("tool") for p in inv.get("probes") or []]
        findings.append({
            "id": (inv.get("signal") or {}).get("id"),
            "segment": (inv.get("signal") or {}).get("affected_segment"),
            "budget": inv.get("probe_budget"),
            "queries": inv.get("probe_executions"),
            "recipe_calls": sum(1 for p in inv.get("probes") or []
                                if str(p.get("origin") or "").startswith("recipe:")),
            "custom_dax": sum(1 for p in follow if p.get("origin") == "custom_dax"),
            "refused": sum(1 for p in inv.get("probes") or [] if p.get("status") in ("rejected", "budget_refused")),
            "cache_hits": sum(1 for p in follow if p.get("status") == "cache_hit"),
            "failed": sum(1 for p in follow if p.get("status") in ("failed", "cache_hit_failed")),
            "closed": ("concluded" if "conclude" in tools else "forced" if "forced_closure" in tools
                       else "no model"),
            "explanation_by": inv.get("explanation_source") or ("model" if any(
                t in ("conclude", "forced_closure") for t in tools) else "code"),
            "conclusion_issues": inv.get("conclusion_issues"),
            "adds_fact": _adds_fact(inv),
        })
    return {
        "folder": str(folder),
        "tier": next((line.split("report_ai_tier=")[1].split(")")[0].split(",")[0]
                      for line in log.splitlines() if "report_ai_tier=" in line), "investigated"),
        "usd": total.get("usd"), "model_calls": total.get("calls"),
        "usd_by_node": {node: v.get("usd") for node, v in (usage.get("by_node") or {}).items()},
        "seconds": _seconds(folder),
        "findings": len(signals),
        "merged_candidates": sum(len(s.get("related_candidate_ids") or []) for s in signals),
        "selection": novelty.get("selection") or ("model" if not any(
            "Rule-based selection" in line for line in log.splitlines()) else "rules"),
        "per_finding": findings,
        "prose": _prose_fallbacks(attempts),
        "errors": [line for line in log.splitlines() if "ERROR:" in line][:10],
        "audit": _audit(folder),
    }


def _row(label: str, values: list) -> str:
    return f"| {label} | " + " | ".join("" if v is None else str(v) for v in values) + " |"


def report(runs: list[dict]) -> str:
    lines = ["| measure | " + " | ".join(r["tier"] for r in runs) + " |",
             "|---|" + "---|" * len(runs)]
    lines.append(_row("cost (USD)", [f"{r['usd']:.4f}" if r["usd"] is not None else None for r in runs]))
    lines.append(_row("model calls", [r["model_calls"] for r in runs]))
    lines.append(_row("run seconds", [r["seconds"] for r in runs]))
    lines.append(_row("findings published", [r["findings"] for r in runs]))
    lines.append(_row("candidates merged in", [r["merged_candidates"] for r in runs]))
    lines.append(_row("findings chosen by", [r["selection"] for r in runs]))
    lines.append(_row("queries beyond the drill", [sum(f["queries"] or 0 for f in r["per_finding"]) for r in runs]))
    lines.append(_row("custom DAX", [sum(f["custom_dax"] for f in r["per_finding"]) for r in runs]))
    lines.append(_row("refused calls", [sum(f["refused"] for f in r["per_finding"]) for r in runs]))
    lines.append(_row("failed queries", [sum(f["failed"] for f in r["per_finding"]) for r in runs]))
    lines.append(_row("explanations by model / code",
                      [f"{sum(f['explanation_by'] == 'model' for f in r['per_finding'])} / "
                       f"{sum(f['explanation_by'] == 'code' for f in r['per_finding'])}" for r in runs]))
    lines.append(_row("findings adding a fact beyond the drill",
                      [f"{sum(f['adds_fact'] for f in r['per_finding'])} of {len(r['per_finding'])}" for r in runs]))
    lines.append(_row("errors in run log", [len(r["errors"]) for r in runs]))
    lines.append(_row("dashboard audit", [r["audit"] for r in runs]))
    out = ["\n".join(lines), ""]
    for r in runs:
        out.append(f"## {r['tier']}  ({r['folder']})")
        out.append("cost by node: " + ", ".join(f"{k} {v:.4f}" for k, v in sorted(
            r["usd_by_node"].items(), key=lambda kv: -(kv[1] or 0)) if v is not None))
        out.append("prose: " + ", ".join(f"{k} {v}" for k, v in r["prose"].items()))
        for f in r["per_finding"]:
            out.append(f"  - {f['segment']}: budget {f['budget']}, queries {f['queries']}, recipes "
                       f"{f['recipe_calls']}, custom {f['custom_dax']}, refused {f['refused']}, cache "
                       f"{f['cache_hits']}, failed {f['failed']}, {f['closed']}, explanation by "
                       f"{f['explanation_by']}{' (adds a fact)' if f['adds_fact'] else ''}"
                       + (f"; rejected: {f['conclusion_issues']}" if f["conclusion_issues"] else ""))
        for line in r["errors"]:
            out.append(f"  ERROR {line[:160]}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folders", nargs="+")
    parser.add_argument("--archive", default=None, help="copy the folders and the comparison here")
    args = parser.parse_args()
    runs = [summarise(PROJECT_ROOT / f) for f in args.folders]
    text = report(runs)
    print(text)
    if args.archive:
        target = PROJECT_ROOT / args.archive
        target.mkdir(parents=True, exist_ok=True)
        for folder, run in zip(args.folders, runs):
            shutil.copytree(PROJECT_ROOT / folder, target / run["tier"], dirs_exist_ok=True)
        (target / "comparison.md").write_text(text, encoding="utf-8")
        (target / "comparison.json").write_text(json.dumps(runs, indent=2, default=str), encoding="utf-8")
        print(f"archived to {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
