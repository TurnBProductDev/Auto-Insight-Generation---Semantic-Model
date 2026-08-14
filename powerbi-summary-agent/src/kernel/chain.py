"""A chain: several reports, separate summaries, ONE investigative report.

Brief §1.8 weighs two readings of "clubbed insight extraction" and picks (b):
the insight branch runs **once per chain** over pooled evidence, producing one
"why" narrative plus a descriptive summary per report. That avoids cross-report
suppression entirely - there is only one memory consumer - and it produces the
better artifact, because a stock-cover problem in one report and an ageing
build-up in another can be connected in a single sentence.

Three requirements, and why each is not optional
------------------------------------------------
1. **The chain runs as ONE process, sequentially.** `get_powerbi_token()` does an
   unlocked read-modify-write of the token cache, and `insight_memory.commit_run`
   takes a best-effort lock. Separate container jobs writing one chain memory
   would race (Non-negotiable 2). The runner here is deliberately a plain loop.
2. **Every report must be represented.** Pooling multiplies the candidate list,
   and `insight_max_new_per_run` would let the loudest report crowd the others
   out. `fair_share` guarantees each contributing report can place its single
   best candidate - which then competes on the same materiality score, **never
   ahead of it**. There is deliberately no priority ordering between reports,
   exactly as there is none between cascade levels today.
3. **Provenance survives pooling.** Every pooled item carries `report_id`, so a
   finding can name the report and dashboard it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class ChainSpec:
    """Which reports run together, and whether they share an investigation."""

    chain_id: str
    report_ids: tuple[str, ...]
    shared_insight: bool = True
    #: Manager-facing name for the combined investigative report.
    title: str = ""

    def __post_init__(self) -> None:
        if not str(self.chain_id or "").strip():
            raise ValueError("chain_id cannot be empty")
        if not self.report_ids:
            raise ValueError("a chain must name at least one report")
        seen = [r for r in self.report_ids if list(self.report_ids).count(r) > 1]
        if seen:
            raise ValueError(f"duplicate report id(s) in chain: {sorted(set(seen))}")

    @property
    def is_single_report(self) -> bool:
        """A chain of one must behave exactly like a standalone run."""
        return len(self.report_ids) == 1


@dataclass
class ChainRun:
    """What a chain produced. Mutable while the runner fills it in."""

    spec: ChainSpec
    #: report_id -> whatever that report's run returned.
    reports: dict = field(default_factory=dict)
    #: Pooled, provenance-tagged evidence for the single insight pass.
    evidence: list = field(default_factory=list)
    #: report_id -> the reason it produced nothing, when it failed.
    failures: dict = field(default_factory=dict)
    logs: list = field(default_factory=list)

    @property
    def contributing_reports(self) -> tuple[str, ...]:
        """Reports that actually put evidence into the pool."""
        return tuple(dict.fromkeys(
            str(item.get("report_id")) for item in self.evidence
            if item.get("report_id")))

    def summary(self) -> str:
        return (f"chain={self.spec.chain_id} reports={len(self.reports)}/"
                f"{len(self.spec.report_ids)} evidence={len(self.evidence)} "
                f"failed={len(self.failures)}")


def tag_evidence(items: Iterable[Mapping[str, Any]], report_id: str,
                 dataset_id: str = "") -> list[dict]:
    """Stamp provenance onto one report's evidence before it joins the pool.

    Without this a pooled finding cannot say which report it came from, and the
    reader has no dashboard to open. `dataset_id` rides along because the two
    inventory reports are in different models, and a figure from one must never
    be compared against a figure from the other without that being visible.
    """
    tagged = []
    for item in items or []:
        record = dict(item)
        record["report_id"] = report_id
        if dataset_id:
            record.setdefault("dataset_id", dataset_id)
        tagged.append(record)
    return tagged


def run(spec: ChainSpec,
        run_report: Callable[[str], Mapping[str, Any]],
        *,
        logger: Callable[[str], None] | None = None) -> ChainRun:
    """Run a chain's reports sequentially, in this process.

    ``run_report`` takes a report_id and returns that report's result, which may
    carry an ``evidence`` list to contribute to the pool. A report that raises
    is recorded and the chain continues: one report failing must not cost the
    others their output, which is the same argument the graph's two-branch
    barrier makes.
    """
    log = logger or (lambda message: None)
    outcome = ChainRun(spec=spec)

    for report_id in spec.report_ids:
        log(f"chain {spec.chain_id}: running {report_id}")
        try:
            result = run_report(report_id) or {}
        except Exception as exc:  # a chain is not all-or-nothing
            outcome.failures[report_id] = str(exc)
            outcome.logs.append(f"{report_id} failed: {exc}")
            log(f"chain {spec.chain_id}: {report_id} FAILED - {exc}")
            continue
        outcome.reports[report_id] = result
        contributed = tag_evidence(
            result.get("evidence") or [], report_id,
            str(result.get("dataset_id") or ""))
        outcome.evidence.extend(contributed)
        outcome.logs.append(
            f"{report_id}: {len(contributed)} evidence item(s)")
        log(f"chain {spec.chain_id}: {report_id} contributed "
            f"{len(contributed)} evidence item(s)")

    return outcome


def fair_share(candidates: Sequence[Mapping[str, Any]],
               selected: Sequence[Mapping[str, Any]],
               *,
               limit: int,
               score_key: str = "score",
               report_key: str = "report_id") -> list[dict]:
    """Guarantee every contributing report a place, without giving it priority.

    The problem pooling creates: one report with many large movements can fill
    `insight_max_new_per_run` on its own, and the others vanish - not because
    they had nothing to say, but because they were quieter. This is the same
    failure `_backfill_uncovered` already prevents for a whole cascade *level*,
    applied per report.

    The fix is deliberately narrow. An uncovered report gets its **single best**
    candidate injected, and that candidate then sorts on the same score as
    everything else. It is not moved up the list, and a report is never given a
    quota beyond one. If the limit cannot fit every report, the highest-scoring
    injections win - so the guarantee degrades by score, not by report order.
    """
    chosen = list(selected)
    covered = {str(item.get(report_key)) for item in chosen if item.get(report_key)}
    by_report: dict[str, list[Mapping[str, Any]]] = {}
    for candidate in candidates:
        report = str(candidate.get(report_key) or "")
        if not report or report in covered:
            continue
        by_report.setdefault(report, []).append(candidate)

    injections = [
        dict(max(items, key=lambda item: _score(item, score_key)))
        for items in by_report.values()
    ]
    # Highest-scoring injections first, so a hard limit drops the weakest claim
    # rather than whichever report happened to be listed last.
    injections.sort(key=lambda item: _score(item, score_key), reverse=True)

    if limit and limit > 0:
        # The slot must be RESERVED before the list is filled. Appending the
        # injection and then truncating by score simply discards it again -
        # the quiet report's candidate is by definition the weakest thing in
        # the list, so it is always the first casualty. Reserving first is what
        # makes the guarantee survive the cap.
        reserved = injections[:limit]
        base = sorted(chosen, key=lambda item: _score(item, score_key),
                      reverse=True)[:max(0, limit - len(reserved))]
        chosen = base + reserved
    else:
        chosen = chosen + injections

    # Rank the whole set purely on score. An injected candidate competes here
    # for its POSITION; it is never placed ahead of a stronger one.
    chosen.sort(key=lambda item: _score(item, score_key), reverse=True)
    return chosen


def _score(item: Mapping[str, Any], key: str) -> float:
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)


def uncovered_reports(candidates: Sequence[Mapping[str, Any]],
                      selected: Sequence[Mapping[str, Any]],
                      *, report_key: str = "report_id") -> tuple[str, ...]:
    """Reports that had something to say and were not represented."""
    had = {str(c.get(report_key)) for c in candidates if c.get(report_key)}
    covered = {str(s.get(report_key)) for s in selected if s.get(report_key)}
    return tuple(sorted(had - covered))


def attribution(finding: Mapping[str, Any],
                report_names: Mapping[str, str] | None = None) -> str:
    """How a pooled finding names where it came from.

    Required by the brief: with several reports in one narrative, a reader who
    cannot tell which dashboard to open cannot act on the finding.
    """
    report_id = str(finding.get("report_id") or "")
    if not report_id:
        return ""
    name = (report_names or {}).get(report_id, report_id.replace("_", " ").title())
    return f"From {name}."
