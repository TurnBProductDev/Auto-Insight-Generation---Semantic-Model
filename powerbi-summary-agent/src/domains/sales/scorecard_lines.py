"""The one-line reading under each figure on the Web App's Home scorecard.

Home shows five figures from two reports - Net Sales, Bills, Basket Value and
Margin from Daily Sales, and the day's result against target from Target
Tracker - and under each one a short sentence saying what the last few days
show. This module owns that sentence.

**Code decides, the model words it.** Which fact a line states is chosen here,
by fixed rules over the published history. When the report's AI tier lets a
model write, it rewrites that one fact in plain words for a store manager; it
cannot pick another fact, add a figure or change a direction. Every draft is
checked against its fact before it is used, a rejected line is sent back once
with the reasons, and a line that fails twice - or a failed call, or a tier
with no AI - keeps the code-written sentence. So a card always carries a true
line, and the replay (`scripts/replay_scorecard_lines.py`) proves the
code-written lines pass the same checks, so the checks cannot dead-end.

**Why every fact is about the normal range and never about the day before.**
The Daily Sales rulebook compares a day only with past days that match its
weekday and week of the month. "Up on Tuesday" would mostly report the weekly
rhythm, so each fact here says where days sat against their OWN band or
benchmark, and for how many days in a row. Inside the band is normal for that
weekday, so it is never worded as bad news.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

#: A line longer than this wraps to a third line on a 200px tile.
MAX_CHARS = 70

#: The days a count reads over ("on 5 of the last 7 days").
WINDOW = 7

#: A run shorter than this is not called a run.
RUN = 2

MEASURES = (("net_sales", "Net Sales"), ("bills", "Bills"),
            ("basket_value", "Basket Value"), ("margin", "Margin"))
TARGET_KEY = "target"

# --- the words a line must, or must not, use for each kind of fact ----------
_BELOW = ("below", "under", "short of", "lower than", "less than", "weaker than",
          "fewer", "missed", "fell short")
_ABOVE = ("above", "over", "beat", "ahead of", "exceeded", "higher than", "more than",
          "more", "better than", "topped", "stronger than")
_ABOVE_STRICT = tuple(w for w in _ABOVE if w != "over")   # "over the last 7 days" is fine
_BACK = ("back", "return", "recovered", "again")
_HIT = ("reached", "hit", "met", "made")
_NORMAL = ("normal", "usual", "typical", "in range", "within", "inside", "in line")

_TONE = {"good": "positive", "bad": "critical", "neutral": "info"}

# --- what no line may say ----------------------------------------------------
_JARGON = ("p20", "p50", "p80", "percentile", "cohort", "band", "attainment", "variance",
           "mtd", "wtd", "ytd", "run rate", "run-rate", "benchmark cohort")
_NOT_BILLS = ("traffic", "footfall", "shoppers", "customers", "visitors")
_TIME = ("yesterday", "today", "tomorrow", "this week", "last week", "next week",
         "this month", "last month", "next month", "day before", "previous day")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD_NUMBERS = {w: str(i) for i, w in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
     "eleven", "twelve", "thirteen", "fourteen"))}
_WORD_NUMBERS.update({w: str(i) for i, w in enumerate(
    ("", "", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
     "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth")) if w})


# ---------------------------------------------------------------------------
# the model's answer: one line per card, nothing else
# ---------------------------------------------------------------------------
class ScorecardLine(BaseModel):
    key: str = Field(description="copied exactly from the card's key")
    text: str = Field(description="one short plain sentence, under 70 characters")


class ScorecardLines(BaseModel):
    lines: list[ScorecardLine]


# ---------------------------------------------------------------------------
# facts
# ---------------------------------------------------------------------------
def _fact(key: str, measure: str, kind: str, polarity: str, statement: str,
          numbers: tuple = (), must_any: tuple = (), must_not: tuple = ()) -> dict:
    return {"key": key, "measure": measure, "kind": kind, "polarity": polarity,
            "tone": _TONE[polarity], "statement": statement,
            "numbers": [str(n) for n in numbers],
            "must_any": list(must_any), "must_not": list(must_not)}


def _run_from_end(flags: list[bool]) -> int:
    run = 0
    for flag in reversed(flags):
        if not flag:
            break
        run += 1
    return run


def _band_fact(key: str, measure: str, history: list[dict]) -> dict | None:
    """One Daily Sales measure's fact, from its days against their own band."""
    days = [d for d in history if d.get("actual") is not None]
    if not days:
        return None
    today = days[-1]
    side = today.get("side")

    if side in ("below", "above"):
        word = "Below" if side == "below" else "Above"
        polarity = "bad" if side == "below" else "good"
        must = (_BELOW, _ABOVE_STRICT + _BACK) if side == "below" else (_ABOVE, _BELOW + _BACK)
        run = _run_from_end([d.get("side") == side for d in days])
        if run >= RUN:
            return _fact(key, measure, f"run_{side}", polarity,
                         f"{word} its normal range for {run} days in a row", (run,), *must)
        if len(days) == 1:
            return _fact(key, measure, f"{side}_only", polarity,
                         f"{word} its normal range", (), *must)
        earlier = [i for i, d in enumerate(days[:-1]) if d.get("side") == side]
        gap = (len(days) - 1 - earlier[-1]) if earlier else len(days)
        # "For the first time in 2 days" is true and reads as nothing: a
        # first is news only across a week or more, or when the history holds
        # no earlier one. Closer than that, say how often it has happened lately.
        if gap >= WINDOW or not earlier:
            return _fact(key, measure, f"first_{side}", polarity,
                         f"{word} its normal range for the first time in {gap} days", (gap,),
                         *must)
        window = days[-WINDOW:]
        often = sum(1 for d in window if d.get("side") == side)
        return _fact(key, measure, f"often_{side}", polarity,
                     f"{word} its normal range on {often} of the last {len(window)} days",
                     (often, len(window)), *must)

    if side == "inside":
        before = days[:-1]
        below_run = _run_from_end([d.get("side") == "below" for d in before])
        above_run = _run_from_end([d.get("side") == "above" for d in before])
        if below_run >= RUN:
            return _fact(key, measure, "back_from_below", "good",
                         f"Back in its normal range after {below_run} days below it",
                         (below_run,), _BACK, ("still below", "remains below", "stayed below"))
        if above_run >= RUN:
            return _fact(key, measure, "back_from_above", "neutral",
                         f"Back in its normal range after {above_run} days above it",
                         (above_run,), _BACK, ("still above", "remains above", "stayed above"))

    # Inside the band, or no band at all: count the days against the benchmark.
    window = [d for d in days[-WINDOW:] if d.get("p50") is not None]
    if len(window) >= 2:
        above = sum(1 for d in window if d["actual"] > d["p50"])
        below = sum(1 for d in window if d["actual"] < d["p50"])
        if above >= below:
            return _fact(key, measure, "count_above", "neutral",
                         f"Above benchmark on {above} of the last {len(window)} days",
                         (above, len(window)), _ABOVE, _BELOW)
        return _fact(key, measure, "count_below", "neutral",
                     f"Below benchmark on {below} of the last {len(window)} days",
                     (below, len(window)), _BELOW, _ABOVE_STRICT)
    if side == "inside":
        return _fact(key, measure, "inside_only", "neutral", "Inside its normal range",
                     (), _NORMAL, _BELOW + _ABOVE_STRICT)
    return None


def daily_sales_facts(page: dict) -> list[dict]:
    """A fact for each Daily Sales measure that has history to read."""
    card = page.get("scorecard") or {}
    facts = []
    for key, measure in MEASURES:
        fact = _band_fact(key, measure, (card.get(key) or {}).get("history") or [])
        if fact:
            facts.append(fact)
    return facts


def target_tracker_facts(model: dict) -> list[dict]:
    """The target card's fact: whether the days reached their target."""
    anchor = str(model.get("anchor") or "")
    days = [d for d in (model.get("days") or [])
            if d.get("attainment") is not None and (not anchor or d["date"] <= anchor)]
    if not days:
        return []
    measure = "Target achievement"
    hit = [d["attainment"] >= 100 for d in days]
    must_miss = (_BELOW, _HIT + _ABOVE_STRICT + _BACK)

    if not hit[-1]:
        run = _run_from_end([not h for h in hit])
        if run >= RUN:
            return [_fact(TARGET_KEY, measure, "target_run_below", "bad",
                          f"Below target for {run} days in a row", (run,), *must_miss)]
        if len(days) == 1:
            return [_fact(TARGET_KEY, measure, "target_below_only", "bad",
                          "Below target", (), *must_miss)]
        earlier = [i for i, h in enumerate(hit[:-1]) if not h]
        gap = (len(days) - 1 - earlier[-1]) if earlier else len(days)
        if gap >= WINDOW or not earlier:
            return [_fact(TARGET_KEY, measure, "target_first_below", "bad",
                          f"Below target for the first time in {gap} days", (gap,), *must_miss)]
        window = hit[-WINDOW:]
        missed = sum(1 for h in window if not h)
        return [_fact(TARGET_KEY, measure, "target_often_below", "bad",
                      f"Below target on {missed} of the last {len(window)} days",
                      (missed, len(window)), *must_miss)]

    missed_before = _run_from_end([not h for h in hit[:-1]])
    if missed_before >= RUN:
        return [_fact(TARGET_KEY, measure, "target_back", "good",
                      f"Back on target after {missed_before} days below it", (missed_before,),
                      _BACK, ("still below", "remains below", "stayed below"))]
    window = hit[-WINDOW:]
    reached = sum(window)
    return [_fact(TARGET_KEY, measure, "target_count", "good" if reached * 2 >= len(window)
                  else "bad",
                  f"Reached target on {reached} of the last {len(window)} days",
                  (reached, len(window)), _HIT, ("missed", "below", "short of", "under"))]


def deterministic(facts: list[dict]) -> dict:
    """The code-written line for every fact."""
    return {f["key"]: {"text": f["statement"], "tone": f["tone"], "mode": "deterministic"}
            for f in facts}


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def _has(low: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", low) is not None


def validate_line(text: Any, fact: dict) -> list[str]:
    """Every reason a line may not stand for its fact."""
    errors: list[str] = []
    line = str(text or "").strip()
    if not line:
        return ["the line is empty"]
    low = line.lower()
    if len(line) > MAX_CHARS:
        errors.append(f"{len(line)} characters - keep it under {MAX_CHARS}")
    if "\n" in line or re.search(r"[.!?;:]\s+\S", line):
        errors.append("more than one sentence - write one")
    if _EMOJI.search(line):
        errors.append("contains an emoji")
    if "%" in line:
        errors.append("quotes a percentage - the card already shows it")

    from .target_tracker_author import CAUSE_WORDS, FORECAST_WORDS, PRIOR_YEAR_WORDS
    for word in CAUSE_WORDS:
        if _has(low, word):
            errors.append(f"'{word}' claims a cause the figures cannot support")
    for word in FORECAST_WORDS + ("will",):
        if _has(low, word):
            errors.append(f"'{word}' is a forecast")
    for word in PRIOR_YEAR_WORDS:
        if _has(low, word):
            errors.append(f"'{word}' - there is no prior-year figure")
    for word in _JARGON:
        if _has(low, word):
            errors.append(f"'{word}' is jargon - use plain words")
    for word in _NOT_BILLS:
        if _has(low, word):
            errors.append(f"'{word}' - Bills counts completed sales, not people")
    for word in _TIME:
        if _has(low, word):
            errors.append(f"'{word}' - say what the days show, not when they were")

    allowed = set(fact["numbers"])
    for found in _NUMBER.findall(line):
        if found.replace(",", "") not in allowed:
            errors.append(f"'{found}' is not a figure in the fact")
    for word, digit in _WORD_NUMBERS.items():
        if _has(low, word) and digit not in allowed:
            errors.append(f"'{word}' is not a figure in the fact")

    if fact["must_any"] and not any(_has(low, w) for w in fact["must_any"]):
        errors.append(f"does not say the fact's direction - use one of: "
                      f"{', '.join(fact['must_any'][:5])}")
    for word in fact["must_not"]:
        if _has(low, word):
            errors.append(f"'{word}' says the opposite of the fact")
    return errors


# ---------------------------------------------------------------------------
# authoring
# ---------------------------------------------------------------------------
def context(facts: list[dict]) -> str:
    """What the model is told: each card's fact, and nothing it may invent from."""
    lines = ["## The cards", "Write one line for each card. Keep its fact exactly.", ""]
    for f in facts:
        numbers = ", ".join(f["numbers"]) or "none"
        lines.append(f"- key: {f['key']} | measure: {f['measure']} | fact: {f['statement']} "
                     f"| numbers you may use: {numbers}")
    return "\n".join(lines)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().rstrip(".").strip()


def author(facts: list[dict], cfg: dict, *, flag: bool = False,
           out_dir: str | None = None, log=print) -> dict:
    """One line per fact, keyed by the card's key.

    ``flag`` is the report's own "let the AI write" switch, read by the caller
    with its catalogued default; the AI tier decides above it (`ai_tier`). On
    any failure every line keeps its code-written sentence."""
    lines = deterministic(facts)
    if not facts:
        return lines

    from ...tools import ai_tier
    if not ai_tier.prose_allowed(cfg, flag) or ai_tier.code_slot(cfg, "scorecard"):
        return lines

    try:
        from ...tools.file_io import read_prompt
        from ...tools.llm import get_llm

        try:
            task = read_prompt("scorecard_lines_prompt.md")
        except Exception:  # noqa: BLE001 - the prompt file is guidance, not a dependency
            task = ("Rewrite each card's fact as one short, plain sentence for a store manager. "
                    "Keep its meaning and its numbers exactly.")
        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"), "model": cfg.get("model"),
                 "max_tokens": min(int(cfg.get("max_tokens") or 800), 800)}
        if out_dir:
            state["output_folder"] = str(out_dir)
        messages = [{"role": "system", "content": task},
                    {"role": "user", "content": context(facts)}]
        llm = get_llm(state, structured_schema=ScorecardLines)
        pending = {f["key"]: f for f in facts}
        for attempt in (1, 2):
            draft = llm.invoke(messages)
            raw = draft.model_dump() if hasattr(draft, "model_dump") else dict(draft)
            written = {str(item.get("key")): _clean(item.get("text"))
                       for item in (raw.get("lines") or []) if isinstance(item, dict)}
            problems = []
            for key, fact in list(pending.items()):
                errors = validate_line(written.get(key), fact)
                if errors:
                    problems += [f"{key}: {e}" for e in errors]
                    continue
                lines[key] = {"text": written[key], "tone": fact["tone"], "mode": "llm"}
                del pending[key]
            if not pending:
                log(f"  scorecard lines written by the model (attempt {attempt})")
                return lines
            log(f"  {len(pending)} scorecard line(s) rejected on attempt {attempt}")
            for problem in problems[:6]:
                log(f"     - {problem}")
            if attempt == 1:
                messages.append({"role": "user", "content":
                                 "These lines were rejected. Fix every point and return all the "
                                 "lines again:\n" + "\n".join(f"- {p}" for p in problems)})
        log(f"  keeping the code-written line for: {', '.join(pending)}")
    except Exception as exc:  # noqa: BLE001 - a line must never cost the report
        log(f"  scorecard lines kept as written by code ({type(exc).__name__}: {exc})")
        return deterministic(facts)
    return lines
