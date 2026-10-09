"""Whether a sentence the model wrote may stand for its report.

The same idea as Target Tracker's prose validation: a figure is grounded only
if it appears in that report's own facts, and words that claim more than the
figures show are refused. Nothing here judges style; a rejected sentence is
sent back once with the reasons, and a line that fails twice is replaced by
the report's own headline (``author``).
"""

from __future__ import annotations

import re

from ..domains.sales.target_tracker_author import (
    CAUSE_WORDS,
    EMOJI,
    FORECAST_WORDS,
    PRIOR_YEAR_WORDS,
)
from .facts import plain

#: A brief line is read in a banner, beside four others.
MAX_WORDS = 35
#: A suggested question fills a small card in the Ask ScanB panel.
MAX_QUESTION_WORDS = 14

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
#: A name with digits in it (ST1, CFH017): a name, not a figure.
CODE = re.compile(r"\b[A-Za-z]+\d[A-Za-z0-9]*\b")

_JARGON = ("p20", "p50", "p80", "percentile", "cohort", "mtd", "wtd", "ytd",
           "run rate", "run-rate", "story key", "kpi feed")
#: Comparisons with a prior year, allowed only when the report's facts make one.
_PRIOR_YEAR = PRIOR_YEAR_WORDS + ("same period last year",)
_WORD_NUMBERS = {word: str(value) for value, word in enumerate(
    ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
     "eleven", "twelve")) if value >= 2}


def _has(low: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", low) is not None


def _forms(number: str) -> set[str]:
    """The spellings of one figure a sentence may use: as written, without
    thousands separators, and without a zero fraction (92.0 may read 92)."""
    bare = number.replace(",", "").rstrip(".")
    forms = {number, bare}
    if "." in bare:
        whole, fraction = bare.split(".", 1)
        if not fraction.strip("0"):
            forms.add(whole)
    elif bare.isdigit():
        forms.add(str(int(bare)))
    return forms


def figures(sheet: str) -> set[str]:
    """Every figure a sentence about this report may quote."""
    text = CODE.sub(" ", plain(sheet))
    allowed: set[str] = set()
    for found in NUMBER.findall(text):
        allowed |= _forms(found)
    return allowed


def _common(text: str, sheet: str, max_words: int) -> list[str]:
    errors: list[str] = []
    line = plain(text)
    low = line.lower()
    sheet_low = plain(sheet).lower()
    words = len(line.split())
    if words > max_words:
        errors.append(f"{words} words - keep it to {max_words}")
    if EMOJI.search(line):
        errors.append("contains an emoji")
    for word in CAUSE_WORDS:
        if _has(low, word):
            errors.append(f"'{word}' claims a cause the figures cannot show")
    for word in FORECAST_WORDS + ("will",):
        if _has(low, word):
            errors.append(f"'{word}' is a forecast - say what the figures show")
    for word in _JARGON:
        if _has(low, word):
            errors.append(f"'{word}' is jargon - use plain words")
    if not any(_has(sheet_low, word) for word in _PRIOR_YEAR):
        for word in _PRIOR_YEAR:
            if _has(low, word):
                errors.append(f"'{word}' - this report's facts make no prior-year comparison")

    names = {token for token in CODE.findall(plain(sheet))}
    for token in CODE.findall(line):
        if token not in names:
            errors.append(f"names '{token}', which is not in this report's facts")
    allowed = figures(sheet)
    for found in NUMBER.findall(CODE.sub(" ", line)):
        if not (_forms(found) & allowed):
            errors.append(f"'{found}' is not a figure in this report's facts - quote the facts exactly")
    for word, digit in _WORD_NUMBERS.items():
        if _has(low, word) and digit not in allowed:
            errors.append(f"'{word}' is not a figure in this report's facts")
    return errors


def validate_line(text, sheet: str) -> list[str]:
    """Every reason a brief line may not stand for its report."""
    line = plain(text)
    if not line:
        return ["the line is empty"]
    errors = _common(line, sheet, MAX_WORDS)
    if "?" in line:
        errors.append("a brief line states; it does not ask")
    if re.search(r"[.!;:]\s+\S", line.rstrip(".")):
        errors.append("more than one sentence - write one")
    return errors


def validate_question(text, sheet: str) -> list[str]:
    """Every reason a suggested question may not be offered about its report."""
    question = plain(text)
    if not question:
        return ["the question is empty"]
    errors = _common(question, sheet, MAX_QUESTION_WORDS)
    if not question.endswith("?") or question.count("?") != 1:
        errors.append("one question, ending with a single '?'")
    if re.search(r"[.!;:]\s+\S", question):
        errors.append("more than one sentence - ask one thing")
    return errors
