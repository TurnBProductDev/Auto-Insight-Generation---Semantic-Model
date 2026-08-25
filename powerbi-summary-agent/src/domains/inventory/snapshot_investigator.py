"""Shared adaptive investigation engine for single-snapshot inventory reports.

Built once, used by `ageing_investigator.py` and `sku_overview_investigator.py`
as thin adapters, so the two cannot drift on exactly the things that matter
most for a feature that runs live DAX against a client's dataset and writes
prose onto a published report: the validation rules, and the safety split
between what the LLM is allowed to decide and what it is allowed to write.

The split, and why it stays fixed
----------------------------------
The LLM never writes or sees DAX. Each report supplies a deterministic,
TREATAS-scoped, TOPN-bounded query BUILDER; the LLM's only DAX-adjacent power
is choosing a ROLE NAME from a list the report itself offers, validated
against real config before use. This is the same split the R1 focus deep dive
uses in the sales product, and it is what makes real multi-round adaptivity
safe here: more rounds means more LLM decisions, never more LLM-authored
query text.

What "adaptive" means here, concretely
----------------------------------------
Round by round, the LLM sees the drill-down evidence gathered so far and
decides: drill one more role, or conclude. It is a genuine choice, not a
fixed count - budget and round caps are the outer bound, not the plan. Once
it concludes (or the bounds are hit), a SEPARATE call writes the narrative,
never combined with the decision: a call whose only job is to decide is
easier to get right than one that decides AND writes, and a call whose only
job is to write is the one already proven safe by `author_narrative` here.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from . import investigation_budget

try:  # pydantic is present wherever the LLM path runs
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - the deterministic path needs no schema
    BaseModel = object  # type: ignore[assignment]

    def Field(**_kw):  # type: ignore[misc]
        return None

Execute = Callable[[str], list[dict]]
#: (cfg, own_role, own_member, drill_role) -> deterministic DAX text.
BuildDax = Callable[..., str]
#: (rows, drill_role) -> [{"name": str, "value": float}], report-specific
#: column-alias resolution stays with the report, never in this module.
Normalize = Callable[[list[dict], str], list[dict]]
#: (model, cfg, *, max_findings) -> candidate findings, each carrying
#: "_drill_role" and "_drill_others".
Candidates = Callable[..., list[dict]]

DEFAULT_MAX_ROUNDS = 3

CAUSE_WORDS = ("because", "due to", "driven by", "caused by", "as a result of",
              "thanks to", "owing to", "stems from", "reflects a", "explained by")
JARGON = ("velocity", "offtake", "capital lock-up", "carry cost", "materiality",
         "write-down provision", "dead stock", "days of cover", "stock worth",
         "significance", "statistically", "correlation coefficient", "p-value")
COMPARISON_WORDS = ("last year", "previous year", "year-on-year", "year on year",
                    "yoy", "last month", "previous month", "up from", "down from",
                    "since yesterday", "trend", "trending", "forecast",
                    "will be", "expected to", "projected")

MAX_DECIMALS = 1
MAX_DECIMALS_ABBREVIATED = 2
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
#: No space in the class: a currency code followed by a number ("USD 999K")
#: must not be swallowed as one token, or the figure check never sees the
#: number at all and an unfounded figure passes silently.
_ENTITY = re.compile(r"[A-Z][A-Z0-9-]{2,}")


class DrillDecision(BaseModel):  # type: ignore[misc]
    """Decide only - never asked to write prose in the same call."""

    action: str = Field(description="'drill' to run one more query, or "
                                    "'conclude' once enough evidence exists.")
    role: str | None = Field(
        default=None,
        description="Required when action='drill' - exactly one of the "
                    "offered roles, the dimension to check next.")
    reasoning: str = Field(description="One sentence: why this role, or why "
                                       "concluding now.")


class DrillNarrative(BaseModel):  # type: ignore[misc]
    """The only string the model may produce here. Nothing structural."""

    text: str = Field(description="Two to three sentences describing where "
                                  "this finding's exposure concentrates "
                                  "within the drill-down results. Never "
                                  "state a cause.")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def money(value: Any, currency: str) -> str:
    number = _num(value) or 0.0
    prefix = f"{currency} " if currency else ""
    if abs(number) >= 1_000_000:
        return f"{prefix}{number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{prefix}{number / 1_000:.0f}K"
    return f"{prefix}{number:,.0f}"


def _figures(entry: dict) -> set[str]:
    """Every figure the narrative may quote, in the forms the page prints them."""
    values: set[float] = set()
    finding = entry["finding"]
    for key in ("impact_value", "current"):
        v = _num(finding.get(key))
        if v is not None:
            values.add(v)
    for drill in entry["drills"]:
        for row in drill["rows"]:
            v = _num(row.get("value"))
            if v is not None:
                values.add(v)
    out: set[str] = set()
    for v in values:
        for x in (v, abs(v)):
            out.add(f"{x:,.0f}")
            out.add(f"{x:.0f}")
            out.add(f"{x:.1f}")
            if abs(x) >= 1_000_000:
                out.add(f"{x / 1_000_000:.2f}")
                out.add(f"{x / 1_000_000:.1f}")
            elif abs(x) >= 1_000:
                out.add(f"{x / 1_000:.0f}")
                out.add(f"{x / 1_000:.1f}")
    for small in range(0, 10):
        out.add(str(small))
    return out


def validate(text: str, entry: dict) -> list[str]:
    """Every reason this draft may not be published. Empty means it may."""
    errors: list[str] = []
    text = str(text or "").strip()
    if not text:
        return ["empty narrative"]
    low = text.lower()
    if not text.isascii():
        errors.append("no emojis or non-ASCII characters")
    for word in CAUSE_WORDS:
        if word in low:
            errors.append(f"states a cause (\"{word}\") - a single snapshot supports "
                          f"concentration, not causation")
    for word in JARGON:
        if word in low:
            errors.append(f"uses jargon (\"{word}\")")
    for word in COMPARISON_WORDS:
        if word in low:
            errors.append(f"implies a comparison over time (\"{word}\") that this "
                          f"single stock position does not support")

    allowed = _figures(entry)
    without_names = _ENTITY.sub(" ", text)
    for match in _NUMBER.finditer(without_names):
        raw = match.group(0)
        cleaned = raw.replace(",", "")
        abbreviated = without_names[match.end():match.end() + 1] in ("M", "K")
        limit = MAX_DECIMALS_ABBREVIATED if abbreviated else MAX_DECIMALS
        if "." in cleaned and len(cleaned.split(".")[1]) > limit:
            errors.append(f"\"{raw}\" carries more than {limit} decimal place"
                          + ("s" if limit != 1 else ""))
            continue
        if raw not in allowed and cleaned not in allowed:
            errors.append(f"the figure \"{raw}\" is not in the drill-down results")
    return sorted(dict.fromkeys(errors))


def deterministic_narrative(entry: dict, currency: str) -> str:
    """The grounded draft. Asserted to pass `validate`, so strict cannot dead-end."""
    finding = entry["finding"]
    parts = []
    for drill in entry["drills"]:
        top = drill["rows"][0] if drill["rows"] else None
        if not top:
            continue
        parts.append(f"by {drill['role']}, {top['name']} accounts for the largest "
                     f"share at {money(top['value'], currency)}")
    if not parts:
        return ""
    return (f"{finding.get('affected_segment')}'s exposure breaks down as "
           f"follows: " + "; and ".join(parts) + ".")


def author_narrative(entry: dict, currency: str, cfg: dict, *,
                     enabled_key: str, rules: str = "") -> tuple[str, str]:
    """Returns (text, mode). Falls back to the grounded draft on any failure."""
    fallback = deterministic_narrative(entry, currency)
    if not cfg.get(enabled_key, False):
        return fallback, "deterministic"
    try:
        from ...tools.file_io import read_prompt
        from ...tools.llm import get_llm

        finding = entry["finding"]
        lines = [
            f"Finding: {finding.get('description')}",
            f"Segment: {finding.get('affected_segment')} (dimension: {finding.get('dimension')})",
            "", "Drill-down results - the ONLY figures you may quote, exactly as written:",
        ]
        for drill in entry["drills"]:
            lines.append(f"  By {drill['role']}:")
            for row in drill["rows"]:
                lines.append(f"    - {row['name']}: {money(row['value'], currency)}")
        lines += [
            "", "Write two to three sentences describing where this finding's "
            "exposure concentrates within the drill-down results above. Never "
            "state a cause - this is a single stock position, not a comparison "
            "over time. No forecasting. No emojis. Quote figures only from the "
            "list above, at most one decimal place unless abbreviated (M/K).",
        ]
        if rules:
            lines += ["", rules[:4000]]
        try:
            system = read_prompt("_global_rules.md")
        except Exception:  # noqa: BLE001 - the shared prompt file is optional here
            system = ("You write short, grounded investigative notes for a "
                      "retail stock report. You never invent a figure and "
                      "never assert a cause.")
        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens", 2048)}
        llm = get_llm(state, structured_schema=DrillNarrative)
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": "\n".join(lines)}]
        for attempt in (1, 2):
            draft = llm.invoke(messages)
            text = getattr(draft, "text", None)
            if text is None and isinstance(draft, dict):
                text = draft.get("text", "")
            text = str(text or "")
            errors = validate(text, entry)
            if not errors:
                return text, "llm"
            if attempt == 1:
                messages.append({"role": "assistant", "content": text})
                messages.append({"role": "user", "content":
                                 "That draft was rejected for these reasons. Rewrite "
                                 "it, fixing every one:\n"
                                 + "\n".join(f"  - {e}" for e in errors)})
    except Exception:  # noqa: BLE001 - investigation prose must never cost the report
        pass
    return fallback, "deterministic"


def _decide(entry: dict, offered_roles: list[str], cfg: dict) -> "DrillDecision | None":
    """One adaptive round's choice: drill a specific role, or conclude. None
    on any failure - the caller falls back to exhausting the round budget in
    a fixed order rather than stalling on a broken LLM call."""
    try:
        from ...tools.file_io import read_prompt
        from ...tools.llm import get_llm

        finding = entry["finding"]
        lines = [
            f"You are investigating: {finding.get('description')}",
            f"Segment: {finding.get('affected_segment')} (dimension: {finding.get('dimension')})",
            "",
        ]
        if entry["drills"]:
            lines.append("Evidence gathered so far:")
            for drill in entry["drills"]:
                lines.append(f"  By {drill['role']}:")
                for row in drill["rows"][:5]:
                    lines.append(f"    - {row['name']}: {row['value']:,.0f}")
        else:
            lines.append("No evidence gathered yet.")
        lines += [
            "", f"Dimensions you may still check: {', '.join(offered_roles)}.",
            "Decide: drill one more of these dimensions if it would meaningfully "
            "sharpen where the exposure concentrates, or conclude if you already "
            "have a clear picture. Prefer concluding once two dimensions agree "
            "on where the concentration sits.",
        ]
        try:
            system = read_prompt("_global_rules.md")
        except Exception:  # noqa: BLE001 - optional
            system = "You investigate a retail stock report. Be decisive and economical with queries."
        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens", 1024)}
        llm = get_llm(state, structured_schema=DrillDecision)
        return llm.invoke([{"role": "system", "content": system},
                          {"role": "user", "content": "\n".join(lines)}])
    except Exception:  # noqa: BLE001 - a broken decision call must not stall investigation
        return None


def investigate(execute: Execute, model: dict, cfg: dict, *,
                report_id: str, candidates_fn: Candidates, build_dax_fn: BuildDax,
                normalize_fn: Normalize, enabled_key: str,
                max_findings_key: str, max_rounds_key: str,
                budget_total_key: str, budget_per_finding_key: str,
                default_max_findings: int = 3, default_max_rounds: int = DEFAULT_MAX_ROUNDS,
                default_budget_total: int = 9, default_budget_per_finding: int = 3,
                rules: str = "", log: Callable[[str], None] | None = None) -> dict:
    """Drill the top findings adaptively, narrate each. Never fatal.

    Off by default (``cfg[enabled_key]``); a failure anywhere in this step
    costs only the investigation section, never the report. Returns
    ``{"entries": [...], "budget": {...summary...}}`` so the budget ledger is
    always visible, whether or not anything was found worth investigating.
    """
    empty = {"entries": [], "budget": investigation_budget.Budget(
        total=0, per_finding=0).summary()}
    if not cfg.get(enabled_key, False):
        return empty
    try:
        max_findings = int(cfg.get(max_findings_key, default_max_findings) or default_max_findings)
        max_rounds = int(cfg.get(max_rounds_key, default_max_rounds) or default_max_rounds)
        budget = investigation_budget.Budget(
            total=int(cfg.get(budget_total_key, default_budget_total) or default_budget_total),
            per_finding=int(cfg.get(budget_per_finding_key, default_budget_per_finding)
                           or default_budget_per_finding))
        found = candidates_fn(model, cfg, max_findings=max_findings)
        if not found:
            return {"entries": [], "budget": budget.summary()}

        currency = str(model.get("currency") or "")
        entries: list[dict] = []
        for finding in found:
            finding_id = str(finding.get("candidate_id"))
            role = finding["_drill_role"]
            member = str(finding.get("affected_segment") or "")
            tried: list[str] = []
            drills: list[dict] = []
            entry = {"finding": finding, "drills": drills}
            concluded = False

            for round_no in range(1, max_rounds + 1):
                offered = [r for r in finding["_drill_others"] if r not in tried]
                if not offered or not budget.can_spend_on(finding_id, 1):
                    break
                decision = _decide(entry, offered, cfg) if drills or round_no > 1 else None
                # Round 1 with no evidence yet is always a drill - there is
                # nothing to decide about before the first query returns.
                chosen_role = offered[0]
                if decision is not None:
                    if decision.action == "conclude":
                        concluded = True
                        break
                    if decision.role in offered:
                        chosen_role = decision.role

                dax = build_dax_fn(cfg, own_role=role, own_member=member, drill_role=chosen_role)
                try:
                    rows = execute(dax)
                    outcome = "ok"
                except Exception as exc:  # noqa: BLE001 - one bad drill must not cost the rest
                    if log:
                        log(f"  drill skipped ({finding_id}/{chosen_role}): "
                            f"{type(exc).__name__}: {exc}")
                    rows = []
                    outcome = f"failed:{type(exc).__name__}"
                budget.spend(finding_id=finding_id, role=chosen_role, dax=dax,
                            rows_returned=len(rows), round_no=round_no, outcome=outcome)
                tried.append(chosen_role)
                normalized = normalize_fn(rows, chosen_role)
                if normalized:
                    drills.append({"role": chosen_role, "rows": normalized[:5]})

            if not drills:
                continue
            text, mode = author_narrative(entry, currency, cfg, enabled_key=enabled_key, rules=rules)
            if not text:
                continue
            entries.append({
                "candidate_id": finding_id, "segment": finding.get("affected_segment"),
                "dimension": finding.get("dimension"), "drills": drills,
                "narrative": text, "authoring_mode": mode,
                "rounds": len(tried), "concluded_by_choice": concluded,
            })
            if log:
                log(f"  investigated {finding_id} ({mode}, {len(tried)} round(s))")
        return {"entries": entries, "budget": budget.summary()}
    except Exception as exc:  # noqa: BLE001 - never cost the report
        if log:
            log(f"  investigation skipped: {type(exc).__name__}: {exc}")
        return empty
