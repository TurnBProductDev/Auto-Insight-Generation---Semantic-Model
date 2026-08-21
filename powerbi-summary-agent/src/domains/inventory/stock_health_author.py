"""LLM-authored prose for the Inventory Management page, strictly validated.

Structure stays code-owned. The model fills four named prose slots and nothing
else: it cannot add or drop a tab, choose a chart, reorder the page, or change a
figure. Gated by `inventory_llm_authoring_enabled` (code default **false**);
off, or on any failure, the page is exactly the deterministic page.

Figure-grounding alone is not enough
------------------------------------
The Target Tracker rollout proved this the expensive way: a draft wrote *"No
branch missed today. CFH017 was the lowest at 91.3% of target."* Every number in
it was real, so a grounding check passed it - and 91.3% is below target, so the
claim was false. :func:`validate` therefore also holds a small set of assertions
derived from the model itself:

* it rejects "nothing needs action" when the queue says otherwise, and the
  reverse;
* it rejects a claim that a state has no lines when it has some, and the reverse
  - which matters here because `NON MOVING - ORDER PLACED` genuinely has none;
* it rejects any comparison against an earlier position unless the archive said
  the two are comparable. That is the fabricated-history rule, and prose is the
  easiest place for it to slip in.

The rest of the validator is the rulebook: BR-03's approved names, BR-33's plain
language, no asserted cause, no figure that is not in the model, at most one
decimal place, and none of the client-specific content the reference excludes.
"""

from __future__ import annotations

import re
from typing import Any

try:  # pydantic is present wherever the LLM path runs; the fallback path is pure
    from pydantic import BaseModel, Field
except ImportError:  # pragma: no cover - deterministic path needs no schema
    BaseModel = object  # type: ignore[assignment]

    def Field(**_kw):  # type: ignore[misc]
        return None

SLOTS = ("headline", "narrative", "queue_note", "excess_note")

#: BR-03: the approved name, and what is banned as a synonym for it. The message
#: names the approved word, so a rejection tells the model what to write instead.
BANNED: dict[str, str] = {
    "overstock value": "Excess Stock",
    "surplus": "Excess Stock",
    "excess inventory": "Excess Stock",
    "dead stock": "Non-Moving",
    "obsolete stock": "Non-Moving",
    "slow-moving": "Non-Moving",
    "write-off": "Damage",
    "written off": "Damage",
    "shrinkage": "Damage",
    "wastage": "Damage",
    "product": "SKU",
    "products": "SKUs",
    "item": "SKU",
    "items": "SKUs",
    "article": "SKU",
    "department": "Division",
    "departments": "Divisions",
    "shop": "Store",
    "shops": "Stores",
    "branch": "Store",
    "outlet": "Store",
    "warehouse stock transfer": "Transfer",
    "replenishment": "Transfer",
    "days of cover": "Burn-Out Days",
    "days cover": "Burn-Out Days",
    "lost sales": "Opportunity Loss",
    "missed sales": "Opportunity Loss",
    "open orders": "Pending Orders",
    "on order": "Pending Orders",
}

#: BR-33: jargon a free-form generator reaches for and a reader cannot act on.
JARGON = ("velocity", "carry cost", "carrying cost", "coverage ratio",
          "materiality", "breadth", "p90", "burnout rate", "eligible skus",
          "scoped", "sku-level", "granular", "leverage", "optimise inventory")

#: A cause may never be asserted: this report describes a position from a single
#: snapshot and cannot know why anything is the way it is.
CAUSE_WORDS = ("because", "due to", "driven by", "caused by", "as a result of",
               "thanks to", "owing to", "stems from", "reflects a", "explained by")

#: There is no prior period in a single stock position, and no forecast.
COMPARISON_WORDS = ("last year", "previous year", "year-on-year", "year on year",
                    "yoy", "last month", "previous month", "up from", "down from",
                    "compared with last", "versus last", "since yesterday")
FORECAST_WORDS = ("will be", "expect to", "forecast", "projected", "on track to",
                  "is likely to", "should reach", "by year end")

#: Carried over from the rules document: the vocabulary, never the client's data.
#: The currency code is deliberately NOT here. The rules document is written for
#: one client and names their country and currency in prose, which must not
#: travel; but the page prints whatever `inventory_currency` is configured to,
#: and banning that code outright would reject the report's own money figures.
#: :func:`_wrong_currency` handles the real risk instead - a currency that is
#: not the configured one.
CLIENT_SPECIFIC = ("saudi", "riyal", "ksa", "cityflower", "cfh0", "cdc010",
                   "cfw001", "buying team lead")

#: Currency codes a draft might import from the rules document or its examples.
KNOWN_CURRENCIES = ("SAR", "QAR", "AED", "USD", "EUR", "GBP", "INR", "KES")

#: A figure quoted to more places than this is not one a reader can check. The
#: rule exists to stop a raw float ("42.24657284") reaching the page.
MAX_DECIMALS = 1

#: An abbreviated figure is the page's own form and keeps two places - "USD
#: 5.90M" is how every money figure here is printed. Allowing one place there
#: would reject the deterministic draft, which must always pass.
MAX_DECIMALS_ABBREVIATED = 2


class StockHealthProse(BaseModel):  # type: ignore[misc]
    """Every string the model is allowed to produce. Nothing structural."""

    headline: str = Field(description="One sentence: the single most important thing "
                                      "about this stock position. Plain language.")
    narrative: str = Field(description="Two to four sentences under the headline, "
                                       "reading the position from most urgent to least.")
    queue_note: str = Field(description="One or two sentences on what the Recommended "
                                        "Action queue says needs doing first.")
    excess_note: str = Field(description="One or two sentences on Excess Stock and "
                                         "Pending Orders.")


def _configured_currency() -> str:
    from . import money

    return money.CURRENCY


def _wrong_currency(text: str) -> list[str]:
    """Currency codes in the draft that are not the one this run publishes in.

    The rules document's worked examples use a different currency from the
    group, and a draft that copies one produces a page quoting two currencies
    for the same figures without saying so.
    """
    configured = _configured_currency().upper()
    # Tokenised rather than matched with a word-boundary escape.
    # Written through a shell heredoc, a `\b` has been observed
    # arriving as a literal backspace byte - at which point the
    # pattern matches nothing and the guard silently stops guarding.
    # That is the same defect the Target Tracker auditor hit, and a
    # boundary no quoting layer can mangle is the fix.
    tokens = {token.upper()
              for token in re.split(r"[^A-Za-z]+", text) if token}
    return [code for code in KNOWN_CURRENCIES
            if code != configured and code in tokens]


def _num(value: Any) -> float | None:
    import math

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _figures(model: dict, score: dict | None = None) -> set[str]:
    """Every figure the prose may quote, in the forms a page prints them."""
    raw: set[float] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        else:
            number = _num(value)
            if number is not None:
                raw.add(number)

    walk(model)
    walk(score or {})

    out: set[str] = set()
    for value in raw:
        for v in (value, abs(value)):
            out.add(f"{v:,.0f}")
            out.add(f"{v:.0f}")
            out.add(f"{v:.1f}")
            if abs(v) >= 1_000_000:
                out.add(f"{v / 1_000_000:.2f}")
                out.add(f"{v / 1_000_000:.1f}")
            elif abs(v) >= 1_000:
                out.add(f"{v / 1_000:.1f}")
                out.add(f"{v / 1_000:.0f}")
    # Small counts a sentence may legitimately use without them being a claim.
    for small in range(0, 32):
        out.add(str(small))
    return out


def quotable(model: dict, score: dict | None = None) -> list[str]:
    """Ready-rounded figures the prompt offers. Quoting one always passes.

    Supplied because the model holds raw floats: told only to "copy the figure
    exactly", a draft will quote something like 42.24657 and be rejected for
    decimal places it had no way to know were wrong.
    """
    from . import money

    header = model.get("header") or {}
    out = [
        f"Stock Value {money.fmt(header.get('stock_value'))} across "
        f"{_fmt(header.get('locations'))} Locations",
        f"Excess Stock {money.fmt(header.get('excess_value'))}, "
        f"{_pct_text(header.get('excess_share_pct'))} of Stock Value",
        f"Pending Orders {money.fmt(header.get('pending_value'))}",
        f"{_fmt(header.get('loc_skus'))} Loc-SKUs covering "
        f"{_fmt(header.get('skus'))} SKUs",
        f"{_fmt(header.get('exception_rows'))} Loc-SKUs need action",
        f"Opportunity Loss {money.fmt(header.get('opportunity_loss_day'))} a day, "
        f"critical SKUs at Stores only",
        f"{_fmt(header.get('unwanted_skus'))} Unwanted SKUs carrying "
        f"{money.fmt(header.get('unwanted_pending_value'))} of Pending Orders",
    ]
    for row in (model.get("queue") or [])[:6]:
        out.append(f"{row.get('action')}: {_fmt(row.get('loc_skus'))} Loc-SKUs, "
                   f"{money.fmt(row.get('stock_value'))}")
    for state in model.get("states_absent_urgent") or []:
        out.append(f"{state}: 0 Loc-SKUs - the data returned none")
    if score:
        out.append(f"Inventory Health Score {score['score']:.1f}, band "
                   f"{score.get('band')}, {score['points_lost']:.1f} points lost")
        for risk in (score.get("risks") or [])[:4]:
            out.append(f"{risk['name']} costs {risk['points']:.1f} points, "
                       f"{(risk.get('share_of_loss_pct') or 0.0):.1f}% of the loss")
    return out


def _fmt(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:,.0f}"


def _pct_text(value: Any) -> str:
    number = _num(value)
    return "-" if number is None else f"{number:.1f}%"


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_ENTITY = re.compile(r"[A-Z][A-Z0-9-]{2,}")


def validate(prose: dict, model: dict, score: dict | None = None) -> list[str]:
    """Every reason this draft may not be published. Empty means it may."""
    errors: list[str] = []
    allowed = _figures(model, score)
    known_states = {str(r.get("action") or "").upper()
                    for r in model.get("queue") or []}
    known_states |= {s.upper() for s in model.get("states_absent") or []}
    comparable = bool((model.get("comparison") or {}).get("comparable"))

    for slot in SLOTS:
        text = str(prose.get(slot) or "").strip()
        if slot in ("headline", "narrative") and not text:
            errors.append(f"{slot}: must not be empty")
            continue
        if not text:
            continue
        low = text.lower()

        if not text.isascii():
            errors.append(f"{slot}: no emojis or non-ASCII characters")

        # Strip the Recommended Action state names before the vocabulary check:
        # they legitimately contain words that are banned as synonyms elsewhere.
        stripped = low
        for state in sorted(known_states, key=len, reverse=True):
            stripped = stripped.replace(state.lower(), " ")

        for word, approved in BANNED.items():
            if re.search(rf"\b{re.escape(word)}\b", stripped):
                errors.append(f"{slot}: BR-03 bans \"{word}\" - use \"{approved}\"")
        for word in JARGON:
            if word in stripped:
                errors.append(f"{slot}: BR-33 bans the jargon \"{word}\"")
        for word in CAUSE_WORDS:
            if word in low:
                errors.append(f"{slot}: states a cause (\"{word}\"). This report "
                              f"describes the position; it cannot explain it.")
        for word in FORECAST_WORDS:
            if word in low:
                errors.append(f"{slot}: no forecasting (\"{word}\")")
        for word in CLIENT_SPECIFIC:
            if word in low:
                errors.append(f"{slot}: client-specific content (\"{word}\") must "
                              f"not appear in published output")
        for code in _wrong_currency(text):
            errors.append(f"{slot}: quotes {code}, but this report is published in "
                          f"{_configured_currency()}")

        # Never fabricate history. A comparison is allowed only when the archive
        # said today and the kept position are genuinely comparable.
        if not comparable:
            for word in COMPARISON_WORDS:
                if word in low:
                    errors.append(
                        f"{slot}: compares against an earlier position (\"{word}\") "
                        f"when there is none to compare against")

        # Figures. Entity names are removed first, or a code like ST1 leaks its
        # digit into the number check.
        without_names = _ENTITY.sub(" ", text)
        for match in _NUMBER.finditer(without_names):
            raw = match.group(0)
            cleaned = raw.replace(",", "")
            # "5.90M" is the page's own abbreviation, not an unrounded float.
            abbreviated = without_names[match.end():match.end() + 1] in ("M", "K")
            limit = MAX_DECIMALS_ABBREVIATED if abbreviated else MAX_DECIMALS
            if "." in cleaned and len(cleaned.split(".")[1]) > limit:
                errors.append(f"{slot}: \"{raw}\" carries more than "
                              f"{limit} decimal place"
                              + ("s" if limit != 1 else ""))
                continue
            if raw not in allowed and cleaned not in allowed:
                errors.append(f"{slot}: the figure \"{raw}\" is not in the report")

        # A comparison with no figure cannot be checked by a reader (BR-33).
        if any(w in low for w in ("more than", "less than", "higher than",
                                  "lower than", "most of", "majority")) \
                and not _NUMBER.search(without_names):
            errors.append(f"{slot}: makes a comparison without quoting a figure")

    errors.extend(_assertions(prose, model))
    # Order is stable so a repair prompt reads the same way twice.
    return sorted(dict.fromkeys(errors))


def _assertions(prose: dict, model: dict) -> list[str]:
    """Claims the model can prove false, whatever figures the draft quoted."""
    errors: list[str] = []
    blob = " ".join(str(prose.get(slot) or "") for slot in SLOTS).lower()
    header = model.get("header") or {}
    needing = int(_num(header.get("exception_rows")) or 0)

    if needing and re.search(r"\b(nothing|no lines?|no loc-skus?) (needs?|need|require)", blob):
        errors.append(f"claims nothing needs action, but {needing:,} Loc-SKUs do")
    if not needing and "need action" in blob:
        errors.append("claims lines need action, but none do")

    # The absent double-warning state is the trap here: it is genuinely empty,
    # and a draft that reports it as a live problem is confidently wrong.
    absent = {s.upper() for s in model.get("states_absent") or []}
    for state in absent:
        if state.lower() in blob:
            pattern = rf"{re.escape(state.lower())}[^.]{{0,60}}?\b(\d[\d,]*)\s*(?:loc-skus?|lines?)"
            for match in re.finditer(pattern, blob):
                if match.group(1).replace(",", "") != "0":
                    errors.append(
                        f"says {state} has {match.group(1)} Loc-SKUs, but the data "
                        f"returned none for it")

    present = {str(r.get("action") or "").upper(): int(_num(r.get("loc_skus")) or 0)
               for r in model.get("queue") or []}
    for state, lines in present.items():
        if lines and re.search(rf"no (?:loc-skus?|lines?)[^.]{{0,40}}{re.escape(state.lower())}",
                               blob):
            errors.append(f"says {state} has no lines, but it has {lines:,}")

    return errors


# ---------------------------------------------------------------------------
# authoring
# ---------------------------------------------------------------------------


def deterministic(model: dict, score: dict | None = None) -> dict:
    """The grounded draft. Asserted to pass `validate`, so strict cannot dead-end."""
    from . import money

    header = model.get("header") or {}
    queue = model.get("queue") or []
    doubles = [r for r in queue if r.get("double_warning") and r.get("loc_skus")]
    needing = int(_num(header.get("exception_rows")) or 0)
    total = int(_num(header.get("loc_skus")) or 0)

    if doubles:
        lead = doubles[0]
        headline = (f"{int(lead['loc_skus']):,} Loc-SKUs are in "
                    f"{lead['action']} and need attention first.")
    elif score:
        headline = (f"The Inventory Health Score is {score['score']:.1f}, "
                    f"in the {score.get('band')} band.")
    else:
        headline = (f"{money.fmt(header.get('excess_value'))} is held above the "
                    f"agreed cover.")

    parts = [f"{needing:,} of {total:,} Loc-SKUs are in a state that needs action."]
    if score and score.get("risks"):
        worst = score["risks"][0]
        parts.append(f"{worst['name']} costs the Inventory Health Score "
                     f"{worst['points']:.1f} points, "
                     f"{(worst.get('share_of_loss_pct') or 0.0):.1f}% of the "
                     f"{score['points_lost']:.1f} lost.")
    opp = _num(header.get("opportunity_loss_day"))
    if opp:
        parts.append(f"Opportunity Loss is estimated at {money.fmt(opp)} a day for "
                     f"critical SKUs at Stores.")

    queue_bits = []
    for row in queue[:3]:
        if row.get("loc_skus"):
            queue_bits.append(f"{row['action']} {int(row['loc_skus']):,} Loc-SKUs")
    queue_note = ("Most urgent first: " + "; ".join(queue_bits) + "."
                  if queue_bits else "")
    for state in model.get("states_absent_urgent") or []:
        queue_note += (f" {state} returned 0 Loc-SKUs, which the rules list as one "
                       f"of the two most urgent situations.")

    unwanted = int(_num(header.get("unwanted_skus")) or 0)
    excess_note = (f"{money.fmt(header.get('excess_value'))} is held above the agreed "
                   f"cover, {_pct_text(header.get('excess_share_pct'))} of Stock "
                   f"Value.")
    if unwanted:
        excess_note += (f" {unwanted:,} Unwanted SKUs already above cover carry "
                        f"{money.fmt(header.get('unwanted_pending_value'))} of "
                        f"Pending Orders.")

    return {"headline": headline, "narrative": " ".join(parts),
            "queue_note": queue_note.strip(), "excess_note": excess_note,
            "authoring_mode": "deterministic"}


def context(model: dict, score: dict | None = None, rules: str = "") -> str:
    """Everything the model may draw on, and nothing it may not."""
    lines = ["Write the prose for an Inventory Management report.",
             "",
             f"Stock position as at {model.get('as_at')}.",
             "",
             "Quote figures ONLY from this list, exactly as written:"]
    lines.extend(f"  - {item}" for item in quotable(model, score))
    comparison = model.get("comparison") or {}
    lines.append("")
    if comparison.get("comparable"):
        lines.append(f"You MAY compare against the position {comparison.get('label')}.")
    else:
        lines.append("There is NO earlier position to compare against. Do not write "
                     "'up from', 'since yesterday' or any other comparison.")
    lines += [
        "",
        "Rules you must follow:",
        "  - Use SKU (never product or item), Loc-SKU for one SKU at one Location,",
        "    Store, Location, Division (never Department), Section, Stock Value,",
        "    Excess Stock (never overstock or surplus), Non-Moving (never dead stock),",
        "    Burn-Out Days, Opportunity Loss, Pending Orders, Damage, Transfer,",
        "    Critical SKU.",
        "  - Recommended Action state names appear in full and are never abbreviated.",
        "  - Never state a cause. Describe the position; do not explain it.",
        "  - Never forecast.",
        "  - Every comparison carries a figure.",
        "  - At most one decimal place on any figure.",
        "  - No emojis.",
    ]
    if rules:
        lines += ["", "The full rulebook follows.", "", rules[:12000]]
    return "\n".join(lines)


def author(model: dict, cfg: dict, score: dict | None = None, *,
           rules: str = "", log=print) -> dict:
    """The prose slots. Falls back to the grounded draft on any failure."""
    fallback = deterministic(model, score)
    if not cfg.get("inventory_llm_authoring_enabled", False):
        return fallback

    try:
        from ...tools.file_io import read_prompt
        from ...tools.llm import get_llm

        state = {"config": cfg, "ai_provider": cfg.get("ai_provider"),
                 "model": cfg.get("model"), "max_tokens": cfg.get("max_tokens", 4096)}
        try:
            task = read_prompt("stock_health_prompt.md")
        except Exception:  # noqa: BLE001 - the prompt file is optional
            task = ("You are writing the prose for a retail Inventory Management "
                    "report. Follow the rulebook exactly. You may not add a "
                    "section, drop a tab, choose a chart or change a figure.")
        messages = [{"role": "system", "content": task},
                    {"role": "user", "content": context(model, score, rules)}]
        llm = get_llm(state, structured_schema=StockHealthProse)

        # One repair attempt, then the fallback. The rejection reasons are handed
        # back verbatim, because "it was rejected" is not actionable.
        for attempt in (1, 2):
            draft = llm.invoke(messages)
            prose = draft.model_dump() if hasattr(draft, "model_dump") else dict(draft)
            errors = validate(prose, model, score)
            if not errors:
                prose["authoring_mode"] = "llm"
                log(f"  prose authored by the model (attempt {attempt})")
                return prose
            log(f"  draft rejected on attempt {attempt}: {len(errors)} problem(s)")
            for err in errors[:6]:
                log(f"     - {err}")
            if attempt == 1:
                messages.append({"role": "assistant", "content": str(prose)})
                messages.append({"role": "user", "content":
                                 "That draft was rejected for these reasons. Rewrite "
                                 "it, fixing every one:\n"
                                 + "\n".join(f"  - {e}" for e in errors)})
    except Exception as exc:  # noqa: BLE001 - prose must never cost the report
        log(f"  prose authoring skipped: {type(exc).__name__}: {exc}")

    log("  using the deterministic wording")
    return fallback
