"""How much AI one run of the LangGraph report is allowed to buy.

`docs/cost-and-tiering-implementation-brief.md` separates two questions the
pipeline had welded together: *what does this report compare against* (a fact
about the data, already named by `kernel/spine.py`) and *how much thinking does
this run buy* (a business decision). This module is the second dial.

Two tiers:

* ``investigated`` - the pipeline as it has always run: the LLM plans the DAX,
  selects the findings, runs a tool-calling investigation and writes the prose.
  It is the code default, so a config that predates this key is unchanged.
* ``deterministic`` - no LLM call anywhere in the run. Every stage that used a
  model already had a code-owned path beside it, and this tier selects it:

  - planning: no summary DAX is planned, so `validate_dax` takes the summary
    branch's existing "no valid summary DAX" route and the fresh summary is
    built from the pre-fork baseline portfolio;
  - signal selection: every eligible candidate is ranked by its computed
    materiality score through the same `_rank_and_cap` the LLM's picks go
    through - the LLM's only extra power was merging related candidates;
  - investigation: the deterministic gap scan has already drilled each finding
    (on the measured 2026-09-08 run the LLM investigator added no probe at all
    to three of four signals), so the trail is written from those rows;
  - prose: the grounded writers that already existed as fallbacks -
    `_deterministic_finding`, the R4/R6 summary drafts and the KPI lead sentence.

The brief's ``narrated`` tier (code-owned structure, LLM-filled prose slots) is
not offered yet. An unrecognised value resolves to ``investigated`` because that
is today's behaviour; the config catalogue's enum rejects it before a run anyway.

The value is read from state first and from ``config`` second. `report_id` taught
that lesson: a key LangGraph does not carry as a declared channel reads one way
before the graph and another way inside it, silently.
"""

from __future__ import annotations

INVESTIGATED = "investigated"
DETERMINISTIC = "deterministic"
TIERS = (INVESTIGATED, DETERMINISTIC)
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


def authoring_allowed(state: dict) -> bool:
    """Whether the summary writers may use the LLM for their wording.

    The long-standing `summary_llm_authoring_enabled` switch still works on its
    own; the deterministic tier simply forces it off.
    """
    enabled = bool((state or {}).get("summary_llm_authoring_enabled", True))
    return enabled and not deterministic(state)
