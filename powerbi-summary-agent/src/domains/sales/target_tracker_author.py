"""Target Tracker - LLM-authored prose, deterministically validated.

Structure stays code-owned (rulebook section 4). The model fills a fixed set of prose
slots and nothing else: it cannot add a section, drop a period, choose a chart or reorder
the page. Every slot already has a grounded deterministic sentence, so authoring is an
improvement pass rather than a dependency - if the call fails, the draft fails validation,
or authoring is switched off, the page is exactly the Phase 3 page.

What the validator enforces, from the rulebook:

* **section 4** - the priority order. The narrative must mention today before the week and
  the week before the month, and it must not lead on the year.
* **section 5** - plain language: no banned vocabulary, no bare number, no emoji.
* **section 9** - no invented cause, no prior-year comparison, no forecasting language.
* **section 13** - every figure quoted must exist in the page model, rounded to at most one
  decimal place. This is the check that stops a fluent hallucination.

The grounded fallback is verified against the same rules by
`scripts/replay_target_tracker.py`, so strict validation cannot dead-end.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# the slots the model may fill
# ---------------------------------------------------------------------------
class TargetTrackerProse(BaseModel):
    """Every string the LLM is allowed to produce. Nothing structural."""

    headline: str = Field(description="One sentence, the single most important thing. "
                                      "Plain language, no jargon.")
    narrative: str = Field(description="Two to four sentences under the headline. Read today "
                                       "through the week, the week through the month.")
    today_note: str = Field(description="One or two sentences on which branches missed today "
                                        "and by how much.")
    month_note: str = Field(description="One or two sentences on the month's surplus or "
                                        "deficit and what it means.")


SLOTS = ("headline", "narrative", "today_note", "month_note")

# --- rulebook section 5 ------------------------------------------------------
BANNED = {
    "attainment": "% of target",
    "month-to-date": "this month so far",
    "mtd": "this month so far",
    "week-to-date": "this week so far",
    "wtd": "this week so far",
    "ytd": "this year so far",
    "cushion": "surplus",
    "the estate": "all branches",
    "horizon": "time period",
    "run-rate": "daily rate",
    "run rate": "daily rate",
    "materiality": "how much it matters",
    "variance": "difference from target",
    "qar": "SAR",
    "footfall": "bills",
    "traffic": "bills",
}
# --- rulebook section 9 ------------------------------------------------------
CAUSE_WORDS = ("because", "due to", "driven by", "caused by", "thanks to", "as a result of",
               "owing to", "promotion", "promotional", "stockout", "stock-out", "out of stock",
               "weather", "staffing", "footfall", "competitor", "seasonal", "holiday")
FORECAST_WORDS = ("forecast", "we expect", "will finish", "will end", "is expected to",
                  "predict", "projected to reach", "should reach")
PRIOR_YEAR_WORDS = ("last year", "previous year", "year-on-year", "year on year", "yoy",
                    "same period last")
ALLOWED_CAPS = {"SAR", "AI", "OK"}
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _figures(model: dict) -> set[str]:
    """Every figure the page may quote, in the forms it prints them."""
    raw: set[float] = set()

    def walk(value: Any):
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            raw.add(float(value))

    walk(model)
    out: set[str] = set()
    for value in raw:
        for v in (value, abs(value)):
            out.add(f"{v:,.0f}")
            out.add(f"{v:.0f}")
            out.add(f"{v:.1f}")
            if abs(v) >= 1_000_000:
                out.add(f"{v/1_000_000:.2f}")
                out.add(f"{v/1_000_000:.1f}")
            elif abs(v) >= 1_000:
                out.add(f"{v/1_000:.1f}")
                out.add(f"{v/1_000:.0f}")
    # counts a sentence may legitimately use
    for small in range(0, 32):
        out.add(str(small))
    return out


def quotable(model: dict) -> list[str]:
    """The ready-rounded figures the prompt offers. Quoting one of these always passes."""
    from .target_tracker_html import money, pc

    p = model["periods"]
    out = []
    for key in ("day", "wtd", "mtd", "ytd"):
        q = p[key]
        out.append(f"{q['name']}: {pc(q['attainment'])} of target, "
                   f"{money(q['actual'])} sold against {money(q['target'])}, "
                   f"{money(abs(q['variance']))} {'above' if q['variance'] >= 0 else 'below'} target")
    s, run = model["surplus"], model["run"]
    if run["length"]:
        out.append(f"{run['length']} days below target in a row, average shortfall "
                   f"{money(run['average_shortfall'])} a day")
        out.append(f"surplus built {money(s['built'])}, used {money(s['given_back'])}, "
                   f"{money(s['now'])} left")
        if s["exhausts_on"]:
            out.append(f"the surplus runs out on {s['exhausts_on']}")
    for which in ("week", "month"):
        c = model[f"{which}_close"]
        if c["needed_vs_target"] is not None and c["remaining_target"] > 0:
            out.append(f"the rest of the {which} needs {money(c['needed'])}, "
                       f"{pc(c['needed_vs_target'])} of what those days are targeted to sell")
    out.append(f"{model['days_hit']} of {model['days_elapsed']} days reached their target")
    for b in model["branches"]:
        out.append(f"{b['name']}: today {pc(b['day']['attainment'])}, week "
                   f"{pc(b['wtd']['attainment'])}, month {pc(b['mtd']['attainment'])}, "
                   f"{money(abs(b['mtd']['variance']))} "
                   f"{'above' if b['mtd']['variance'] >= 0 else 'below'} target for the month")
    return out


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def validate(prose: dict, model: dict) -> list[str]:
    """Every rule that must hold. Returns the reasons it does not."""
    errors: list[str] = []
    allowed = _figures(model)
    names = {b["name"] for b in model["branches"]}
    names |= {d["name"] for d in model["departments"]}
    names |= {s["name"] for s in model["sections"]}

    for slot in SLOTS:
        text = str(prose.get(slot) or "").strip()
        if not text:
            continue
        low = text.lower()

        for word, better in BANNED.items():
            if re.search(rf"\b{re.escape(word)}\b", low):
                errors.append(f"{slot}: says '{word}' - write '{better}' (rulebook 5)")
        if EMOJI.search(text):
            errors.append(f"{slot}: contains an emoji (rulebook 5)")
        for word in CAUSE_WORDS:
            if word in low:
                errors.append(f"{slot}: '{word}' asserts or implies a cause the report cannot "
                              f"support (rulebook 9)")
        for word in FORECAST_WORDS:
            if word in low:
                errors.append(f"{slot}: '{word}' is forecasting language (rulebook 9)")
        for word in PRIOR_YEAR_WORDS:
            if word in low:
                errors.append(f"{slot}: '{word}' - the model holds no prior year (rulebook 9)")

        # Entity names are removed before either check runs. A branch code like
        # CFH017 otherwise leaks "017" into the figure check, and an all-caps
        # department name is not an invented word.
        stripped = text
        for name in sorted(names, key=len, reverse=True):
            stripped = stripped.replace(name, " ")

        for found in NUMBER.findall(stripped.replace("&nbsp;", " ")):
            cleaned = found.rstrip(".")
            if cleaned in allowed:
                continue
            if re.fullmatch(r"20\d\d", cleaned):        # a year
                continue
            if "." in cleaned and len(cleaned.split(".")[1]) > 1:
                errors.append(f"{slot}: '{found}' is quoted to more than one decimal place "
                              f"(rulebook 13)")
            else:
                errors.append(f"{slot}: '{found}' is not a figure in the report (rulebook 13)")

        # What is left that still looks like a name the report does not contain.
        # Digits and spaces are deliberately excluded from the token: including them
        # made "SAR 578894" read as a single unknown entity.
        for token in re.findall(r"\b[A-Z][A-Z0-9-]{2,}\b", stripped):
            if token not in ALLOWED_CAPS:
                errors.append(f"{slot}: names '{token}', which is not a branch, department or "
                              f"section in the report (rulebook 13)")

    # --- claims the figures contradict -------------------------------------
    # Figure-grounding is not enough on its own: a sentence can quote only real
    # numbers and still say the opposite of what they mean. A live draft wrote
    # "No branch missed today" while one branch sat at 91.3% of target.
    joined = " ".join(str(prose.get(slot) or "") for slot in SLOTS).lower()
    missed_today = [b for b in model["branches"] if (b["day"]["attainment"] or 0) < 100]
    all_clear = ("no branch missed", "every branch reached", "all branches reached",
                 "every branch met", "all branches met", "no branch was below",
                 "every branch beat", "all four branches reached")
    if missed_today and any(phrase in joined for phrase in all_clear):
        errors.append(
            f"prose: claims no branch missed today, but "
            f"{', '.join(b['name'] for b in missed_today)} "
            f"{'was' if len(missed_today) == 1 else 'were'} below target (rulebook 13)")
    if not missed_today and re.search(r"\bmissed (its|their) target\b", joined):
        errors.append("prose: says a branch missed today, but every branch reached its target "
                      "(rulebook 13)")

    # BOTH conditions, and each is load-bearing.
    #
    # The window must cover the month - that alone is the original test, and it is
    # right: a report anchored mid-month because targets stop there has not seen the
    # month out, even if sales were later recorded into the next one.
    #
    # And the sales must actually REACH month end. Without that, an anchor sitting on
    # month end while trade stopped days earlier made the counter read 31 of 31, so
    # the guardrail ENFORCED the false claim - it permitted "the month is complete"
    # and would have rejected correct prose naming the days still to trade. Fixing
    # the anchor cures the normal path; this keeps it true when an anchor is forced.
    month_done = model["days_elapsed"] >= model["days_in_month"]
    sold_through = model.get("sold_through")
    if month_done and sold_through:
        month_end = _dt.date.fromisoformat(model["anchor"]).replace(
            day=model["days_in_month"])
        month_done = _dt.date.fromisoformat(sold_through) >= month_end
    if month_done and re.search(r"\b(days? (are |is )?left|remaining days|rest of the month)\b",
                                joined):
        errors.append("prose: talks about days left, but the month is complete (rulebook 13)")
    if not month_done and re.search(r"\bthe month (is|has) (complete|finished|closed|over)\b",
                                    joined):
        # Say WHICH of the two conditions failed. Reporting "0 days remain" when
        # the counter is full but trade stopped early is a confusing non-reason,
        # and the author cannot act on it.
        left = model["days_in_month"] - model["days_elapsed"]
        reason = (f"{left} days remain" if left > 0
                  else f"sales are only recorded to {model.get('sold_through')}")
        errors.append(f"prose: calls the month complete, but {reason} (rulebook 13)")

    run = model["run"]["length"]
    # every mention, not just the first - a correct headline followed by a wrong
    # sentence would otherwise pass
    for claimed in re.finditer(r"(\d+)\s+(?:consecutive\s+)?days? below target", joined):
        if int(claimed.group(1)) != run:
            errors.append(f"prose: says {claimed.group(1)} days below target in a row; the run is "
                          f"{run} (rulebook 13)")

    # rulebook section 2 - the priority order
    narrative = str(prose.get("narrative") or "").lower()
    if narrative:
        pos = {w: narrative.find(w) for w in ("today", "week", "month", "year")}
        if pos["year"] >= 0 and pos["year"] < max(p for w, p in pos.items() if w != "year"):
            errors.append("narrative: leads on the year - the order is today, week, month, "
                          "then the year as context (rulebook 2)")
        if pos["today"] >= 0 and pos["week"] >= 0 and pos["today"] > pos["week"]:
            errors.append("narrative: mentions the week before today (rulebook 2)")

    headline = str(prose.get("headline") or "")
    if headline and not NUMBER.search(headline):
        errors.append("headline: quotes no figure (rulebook 5 - never a bare claim)")
    if len(headline) > 160:
        errors.append(f"headline: {len(headline)} characters, over the 160 limit")
    return errors


# ---------------------------------------------------------------------------
# authoring
# ---------------------------------------------------------------------------
def context(model: dict, rules: str = "") -> str:
    """What the model is told. Figures only - no instruction to invent."""
    import json

    from .target_tracker_html import _R, headline, hero_narrative

    r = _R("SAR")
    p = model["periods"]
    lines = [
        "## The report",
        f"Target Tracker, data to {model['anchor']}. All figures in SAR.",
        f"Population: {', '.join(model['population'])}.",
        "",
        "## Figures you may quote (copy them exactly as written)",
    ]
    lines += [f"- {line}" for line in quotable(model)]
    lines += [
        "",
        "## The deterministic draft you are improving",
        "Keep every fact. Improve only the reading.",
        f"- headline: {headline(r, model)}",
        f"- narrative: {hero_narrative(r, model)}",
        "",
        "## Period states",
        json.dumps({k: {"reached": round(v["attainment"], 2) if v["attainment"] else None,
                        "elapsed": v["elapsed"], "status": v["status"]}
                    for k, v in p.items()}, indent=2),
    ]
    if rules:
        lines += ["", "## The rulebook you must follow", rules]
    return "\n".join(lines)


def author(model: dict, cfg: dict, *, rules: str = "", log=print) -> dict:
    """Return the prose slots. Falls back to the grounded draft on any failure."""
    from .target_tracker_html import _R, headline, hero_narrative

    r = _R(cfg.get("target_tracker_currency", "SAR"))
    fallback = {"headline": headline(r, model), "narrative": hero_narrative(r, model),
                "today_note": "", "month_note": "", "authoring_mode": "deterministic"}

    if not cfg.get("target_tracker_llm_authoring_enabled", False):
        return fallback

    try:
        from pathlib import Path

        from ...tools.file_io import read_prompt
        from ...tools.llm import get_llm

        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens", 4096)}
        try:
            task = read_prompt("target_tracker_prompt.md")
        except Exception:  # noqa: BLE001 - the prompt file is optional
            task = ("You are writing the prose for a retail Target Tracker report. "
                    "Follow the rulebook exactly.")
        rules_text = rules
        messages = [
            {"role": "system", "content": task},
            {"role": "user", "content": context(model, rules_text)},
        ]
        llm = get_llm(state, structured_schema=TargetTrackerProse)
        for attempt in (1, 2):
            draft = llm.invoke(messages)
            prose = draft.model_dump() if hasattr(draft, "model_dump") else dict(draft)
            errors = validate(prose, model)
            if not errors:
                prose["authoring_mode"] = "llm"
                log(f"  prose authored by the model (attempt {attempt})")
                return prose
            log(f"  draft rejected on attempt {attempt}: {len(errors)} problem(s)")
            for err in errors[:6]:
                log(f"     - {err}")
            if attempt == 1:
                messages.append({"role": "user", "content":
                                 "That draft was rejected. Fix every point and return the whole "
                                 "object again:\n" + "\n".join(f"- {e}" for e in errors)})
        log("  keeping the deterministic draft - the model's prose did not pass")
    except Exception as exc:  # noqa: BLE001 - authoring must never fail the report
        log(f"  authoring skipped ({type(exc).__name__}: {exc})")
    return fallback
