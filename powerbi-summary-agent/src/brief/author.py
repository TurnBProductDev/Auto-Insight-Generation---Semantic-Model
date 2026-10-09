"""The brief's sentences and suggested questions, written by the model.

**Code decides, the model words it.** Which reports speak, in what order and
in what tone is decided in ``select``; the model writes one sentence for each
from that report's fact sheet and nothing else. Every draft is checked
(``validate``), a rejected draft is sent back once with the reasons, and a line
that fails twice - or a failed call, or a tier with no AI - keeps the report's
own headline. A question that fails is simply not offered; with none, the Web
App keeps its own default questions.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .facts import ReportFacts, plain
from .validate import validate_line, validate_question

_TASK = ("Write one plain sentence of at most 35 words for each report, from that report's "
         "facts only, quoting figures exactly as written. Then write short questions a "
         "manager might ask next, each about one report. Never give causes or forecasts.")


class BriefLineDraft(BaseModel):
    report: str = Field(description="the report's key, copied exactly")
    text: str = Field(description="one plain sentence, at most 35 words")


class BriefQuestionDraft(BaseModel):
    report: str = Field(description="the key of the report the question is about")
    text: str = Field(description="one short question, ending with '?'")


class BriefDraft(BaseModel):
    lines: list[BriefLineDraft]
    questions: list[BriefQuestionDraft]


def context(selected: list[ReportFacts], questions: int) -> str:
    """What the model is told: each report's key and its facts, nothing else."""
    parts = [f"Write a line for each of these {len(selected)} reports, and {questions} "
             f"suggested questions.", ""]
    for report in selected:
        parts += [f"## Report key: {report.slug}", report.sheet(), ""]
    return "\n".join(parts)


def _clean(text) -> str:
    return re.sub(r"\s+", " ", plain(text)).strip()


def headlines(selected: list[ReportFacts]) -> dict:
    """The code path: each report's own headline, and no questions."""
    return {"lines": {r.slug: {"text": r.headline, "mode": "headline"} for r in selected},
            "questions": []}


def author(selected: list[ReportFacts], cfg: dict, *, out_dir: str | None = None,
           llm=None, log=print) -> dict:
    """``{"lines": {slug: {"text", "mode"}}, "questions": [{"report", "text"}]}``.

    ``llm`` replaces the configured model (the replay passes a stub). The AI
    tier decides first: the deterministic tier never calls a model.
    """
    out = headlines(selected)
    if not selected:
        return out
    from ..tools import ai_tier

    if not ai_tier.prose_allowed(cfg, True):
        log("  brief: deterministic tier - each report's own headline")
        return out

    wanted = max(0, int(cfg.get("brief_suggested_questions", 4)))
    by_slug = {r.slug: r for r in selected}
    pending = dict(by_slug)
    kept_questions: list[dict] = []
    try:
        if llm is None:
            from ..tools.file_io import read_prompt
            from ..tools.llm import get_llm

            try:
                task = read_prompt("executive_brief_prompt.md")
            except Exception:  # noqa: BLE001 - the prompt file is guidance, not a dependency
                task = _TASK
            state = {"config": cfg, "ai_provider": cfg.get("ai_provider"), "model": cfg.get("model"),
                     "max_tokens": min(int(cfg.get("max_tokens") or 1500), 1500)}
            if out_dir:
                state["output_folder"] = str(out_dir)
            llm = get_llm(state, structured_schema=BriefDraft)
        else:
            task = _TASK
        messages = [{"role": "system", "content": task},
                    {"role": "user", "content": context(selected, wanted)}]
        for attempt in (1, 2):
            draft = llm.invoke(messages)
            raw = draft.model_dump() if hasattr(draft, "model_dump") else dict(draft)
            written = {}
            for item in raw.get("lines") or []:
                if isinstance(item, dict) and str(item.get("report")) not in written:
                    written[str(item.get("report"))] = _clean(item.get("text"))
            problems = []
            for slug, report in list(pending.items()):
                errors = validate_line(written.get(slug), report.sheet())
                if errors:
                    problems += [f"line {slug}: {e}" for e in errors]
                    continue
                out["lines"][slug] = {"text": written[slug], "mode": "llm"}
                del pending[slug]

            seen = {q["text"].lower() for q in kept_questions}
            for item in raw.get("questions") or []:
                if len(kept_questions) >= wanted or not isinstance(item, dict):
                    break
                slug, text = str(item.get("report")), _clean(item.get("text"))
                if slug not in by_slug:
                    problems.append(f"question '{text}': '{slug}' is not one of the report keys")
                    continue
                errors = validate_question(text, by_slug[slug].sheet())
                if errors:
                    problems += [f"question '{text}': {e}" for e in errors]
                    continue
                if text.lower() not in seen:
                    seen.add(text.lower())
                    kept_questions.append({"report": slug, "text": text})

            if not pending and len(kept_questions) >= wanted:
                log(f"  brief written by the model (attempt {attempt})")
                break
            log(f"  brief: {len(pending)} line(s) and {wanted - len(kept_questions)} question(s) "
                f"short on attempt {attempt}")
            for problem in problems[:8]:
                log(f"     - {problem}")
            if attempt == 1:
                messages.append({"role": "user", "content":
                                 "These were rejected. Fix every point and return all the lines "
                                 "and questions again:\n" + "\n".join(f"- {p}" for p in problems)})
        if pending:
            log(f"  brief: keeping the report's own headline for: {', '.join(pending)}")
    except Exception as exc:  # noqa: BLE001 - the brief must never fail for want of prose
        log(f"  brief: model unavailable ({type(exc).__name__}: {exc}); "
            f"headlines kept for: {', '.join(pending) or 'none'}")
    out["questions"] = kept_questions[:wanted]
    return out
