"""Node 3 - Report Understanding Agent (LLM, structured output)."""

from typing import List

from pydantic import BaseModel, Field

from ..tools import file_io
from ..tools.llm import get_llm
from ..tools import plan_cache
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger
from ..utils.model_context import llm_model_context


class ReportUnderstanding(BaseModel):
    domain: str = Field(description="Likely business domain, e.g. 'Sales / Retail'.")
    fact_tables: List[str] = Field(default_factory=list)
    dimension_tables: List[str] = Field(default_factory=list)
    important_measures: List[str] = Field(default_factory=list)
    important_dimensions: List[str] = Field(
        default_factory=list, description="Each as 'Table[Column]'."
    )
    date_fields: List[str] = Field(default_factory=list, description="Each as 'Table[Column]'.")
    time_summary_possible: bool = False
    notes: str = ""


def _deterministic_understanding(state: dict) -> dict:
    """The fields the LLM returns, read off the semantic profile instead.

    Outside `dax_planner` - which plans nothing in the deterministic tier - the
    only field any node reads is `domain`, for the insight report's title. So
    this names what the profiler actually resolved rather than inventing a
    fuller answer, and `notes` says plainly that no model was asked.
    """
    from ..tools import ai_tier

    profile = state.get("semantic_model_profile") or {}
    cfg = state.get("config") or {}

    def reference(item) -> str | None:
        if isinstance(item, dict):
            return item.get("reference") or item.get("name") or item.get("table")
        return str(item) if item else None

    measures: list[str] = []
    for bundle in [profile.get("primary_value_bundle") or {}] + list(
            profile.get("volume_driver_bundles") or []):
        for name in ((bundle or {}).get("measures") or {}).values():
            if name and name not in measures:
                measures.append(name)
    dimensions = [r for r in (reference(d) for d in profile.get("dimensions") or []) if r]
    dates = [r for r in (reference(d) for d in profile.get("time_dimensions") or []) if r]
    fact = reference(profile.get("fact_table"))
    domain = str(cfg.get("report_domain") or state.get("report_domain") or "sales").strip()
    return {
        # "Sales / Retail" is what the LLM has returned for this domain on every
        # recorded run, so the report title is unchanged between the tiers.
        "domain": "Sales / Retail" if domain.lower() == "sales" else domain.title(),
        "fact_tables": [fact] if fact else [],
        "dimension_tables": [],
        "important_measures": measures,
        "important_dimensions": dimensions,
        "date_fields": dates,
        "time_summary_possible": bool(dates),
        "notes": (f"Built from the semantic profile without a model call "
                  f"(report_ai_tier={ai_tier.tier(state)})."),
    }


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 3: understanding the report/model...")

    from ..tools import ai_tier
    if not ai_tier.investigates(state):
        understanding = _deterministic_understanding(state)
        file_io.write_json(state, "report_understanding.json", understanding)
        log.info(f"Node 3: understanding built from the semantic profile "
                 f"(report_ai_tier={ai_tier.tier(state)}) - no LLM call.")
        return {"report_understanding": understanding, **log.updates()}

    # The model's structure decides this, not today's rows, so a stored answer
    # for an unchanged schema is the same answer at zero cost.
    cached = plan_cache.load(state)
    if cached and cached.get("report_understanding"):
        understanding = cached["report_understanding"]
        file_io.write_json(state, "report_understanding.json", understanding)
        log.info(f"Node 3: reused cached understanding "
                 f"(plan cache {cached['key'][:8]}, {cached['age_days']}d old) - no LLM call.")
        return {"report_understanding": understanding,
                "plan_cache_hit": True, **log.updates()}

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("report_understanding_prompt.md")
    model_context = llm_model_context(state["model_metadata"])
    model_context["deterministic_semantic_profile"] = state.get("semantic_model_profile", {})
    model_context["resolved_entity_scope"] = state.get("resolved_entity_scope", {})

    llm = get_llm(state, structured_schema=ReportUnderstanding)
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state) + "\n\n" + task},
        {"role": "user", "content": "MODEL METADATA (complete structural view):\n"
         + dumps(model_context)},
    ]

    result: ReportUnderstanding = llm.invoke(messages)
    understanding = result.model_dump()

    # Guard: if metadata has no date fields, force time_summary_possible False.
    if not model_context["date_fields"]:
        understanding["time_summary_possible"] = False

    plan_cache.save(state, report_understanding=understanding)
    file_io.write_json(state, "report_understanding.json", understanding)
    log.info(
        f"Domain: {understanding.get('domain')!r}; "
        f"{len(understanding.get('important_measures', []))} key measures; "
        f"time summary possible: {understanding.get('time_summary_possible')}."
    )
    return {"report_understanding": understanding, **log.updates()}
