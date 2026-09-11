"""How much AI one report run is allowed to buy.

`docs/cost-and-tiering-implementation-brief.md` separates two questions the
pipeline had welded together: *what does this report compare against* (a fact
about the data, already named by `kernel/spine.py`) and *how much thinking does
this run buy* (a business decision). This module is the second dial, and every
report reads it.

Three tiers, matching the brief's:

* ``investigated`` - each report as it has always run. In Sales YoY the model
  plans the DAX, selects the findings, runs a tool-calling investigation and
  writes the prose; in the standalone reports it chooses which breakdown to
  drill next. Every older per-report "let the AI write" switch keeps its own
  meaning here. It is the code default, so a config without this key is
  unchanged.
* ``narrated`` - code owns everything a model could get wrong in substance:
  which findings, which breakdowns, which numbers, what the page holds. A model
  writes the sentences, and only the sentences, and every sentence goes through
  the same deterministic check an LLM draft already had to pass, with the
  grounded code-written draft as the fallback. Prose is on in every report here,
  whatever the older per-report switches say - that is what choosing this tier
  means.
* ``deterministic`` - no model call anywhere. Every prose slot uses its grounded
  code-written draft.

What each tier permits, as the two questions the code asks:

    ==============  ===================  ===============
    tier            model decides        model writes
    ==============  ===================  ===============
    investigated    yes                  per-report flag
    narrated        no                   yes
    deterministic   no                   no
    ==============  ===================  ===============

An unrecognised value resolves to ``investigated`` because that is today's
behaviour; the config catalogue's enum rejects it before a run anyway.

The value is read from state first and from ``config`` second. `report_id` taught
that lesson: a key LangGraph does not carry as a declared channel reads one way
before the graph and another way inside it, silently. The standalone runners
hand the config itself, which this reads the same way.
"""

from __future__ import annotations

INVESTIGATED = "investigated"
NARRATED = "narrated"
DETERMINISTIC = "deterministic"
TIERS = (INVESTIGATED, NARRATED, DETERMINISTIC)
DEFAULT = INVESTIGATED


def tier(state: dict) -> str:
    """The resolved tier for this run, never an unknown value."""
    cfg = (state or {}).get("config") or {}
    raw = (state or {}).get("report_ai_tier") or cfg.get("report_ai_tier") or DEFAULT
    value = str(raw).strip().lower()
    return value if value in TIERS else DEFAULT


def deterministic(state: dict) -> bool:
    """True when this run may not call a language model at all."""
    return tier(state) == DETERMINISTIC


def narrated(state: dict) -> bool:
    """True when a model writes the wording but decides nothing."""
    return tier(state) == NARRATED


def investigates(state: dict) -> bool:
    """Whether a model may make a substantive decision: plan queries, choose
    findings, run an investigation, pick the next breakdown."""
    return tier(state) == INVESTIGATED


def prose_allowed(state: dict, flag: bool = True) -> bool:
    """Whether a model may write the wording of one prose slot.

    ``flag`` is that slot's older per-report switch, already read by the caller
    with its catalogued default. It decides only on the investigated tier; the
    other two tiers answer the question themselves.
    """
    current = tier(state)
    if current == DETERMINISTIC:
        return False
    if current == NARRATED:
        return True
    return bool(flag)


def authoring_allowed(state: dict) -> bool:
    """Whether the Sales YoY summary writers may use the model for their wording."""
    return prose_allowed(state, bool((state or {}).get("summary_llm_authoring_enabled", True)))


#: The narrated writers ``narrated_code_slots`` can switch back to code wording.
CODE_SLOTS = ("summary", "dashboard", "key_insights", "kpi_cards")


def code_slots(state: dict) -> tuple[str, ...]:
    """The narrated writers this run hands back to code wording, known names only.

    Read from state first and ``config`` second, like the tier. An unknown name
    is refused by the config catalogue before a run; here it is simply not a
    slot, so a typo can never switch off a writer nobody meant to switch off.
    """
    cfg = (state or {}).get("config") or {}
    raw = (state or {}).get("narrated_code_slots")
    if raw is None:
        raw = cfg.get("narrated_code_slots")
    if isinstance(raw, str):
        raw = [raw]
    wanted = {str(item).strip().casefold() for item in raw or [] if str(item).strip()}
    return tuple(slot for slot in CODE_SLOTS if slot in wanted)


def code_slot(state: dict, slot: str) -> bool:
    """True when the narrated tier writes this slot with code's wording and no model call.

    A per-writer way back to the grounded draft without dropping the whole report
    to the deterministic tier: the summary, the dashboard stories, the Key
    Insights paragraphs or the KPI card text. It has no effect on the other two
    tiers - investigated keeps each report's own switches, deterministic already
    uses code wording everywhere.
    """
    return narrated(state) and slot in code_slots(state)
