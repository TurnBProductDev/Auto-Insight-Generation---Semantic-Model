"""Node 4 - Auto DAX Planner Agent (LLM, structured output).

Plans free-text analytical intents rather than picking from a fixed set of
query shapes - Node 5 (dax_generator) is what turns each intent into real DAX.
"""

from typing import List

from pydantic import BaseModel, Field

from ..tools import file_io
from ..tools.llm import get_llm
from ..tools import plan_cache
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger
from ..utils.model_context import llm_model_context


class PlanQuery(BaseModel):
    name: str = Field(description="Short snake_case unique id.")
    purpose: str = Field(description="One plain-language sentence.")
    intent: str = Field(
        description=(
            "Precise, self-contained plain-language description of exactly what "
            "to compute - specific enough to write the DAX from directly. Name "
            "the exact measures/tables/columns involved, the aggregation or "
            "grouping, any row limit, and sort order."
        )
    )


class DaxPlan(BaseModel):
    queries: List[PlanQuery]


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 4: planning DAX queries automatically...")

    md = state["model_metadata"]
    understanding = state["report_understanding"]
    available = {
        **llm_model_context(md),
        "important_measures": understanding.get("important_measures", []),
        "important_dimensions": understanding.get("important_dimensions", []),
        "domain": understanding.get("domain"),
        "time_summary_possible": understanding.get("time_summary_possible"),
        "deterministic_semantic_profile": state.get("semantic_model_profile", {}),
        "shared_baseline_evidence": state.get("baseline_scope_evidence", {}),
        "shared_metadata_coverage": state.get("baseline_coverage_clean_data", {}),
        "resolved_entity_scope": state.get("resolved_entity_scope", {}),
    }

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("dax_planner_prompt.md")
    max_rows = state.get("max_rows_per_query", 15)

    from ..tools import ai_tier
    if not ai_tier.investigates(state):
        # An empty plan, on purpose: planning is a decision, and below the
        # investigated tier no model makes decisions. validate_dax then takes
        # the summary branch's existing "no valid summary DAX" route, and the
        # fresh summary is built from the pre-fork baseline portfolio instead of
        # from queries an LLM would have written.
        plan_dict = {"queries": []}
        file_io.write_json(state, "generated_dax_plan.json", plan_dict)
        log.info(f"Node 4: no DAX planned (report_ai_tier={ai_tier.tier(state)}); the "
                 f"summary is built from the shared baseline evidence.")
        return {"dax_plan": plan_dict, **log.updates()}

    cached = plan_cache.load(state)
    if cached and cached.get("dax_plan"):
        plan_dict = cached["dax_plan"]
        file_io.write_json(state, "generated_dax_plan.json", plan_dict)
        log.info(f"Node 4: reused cached plan of {len(plan_dict['queries'])} "
                 f"quer(y/ies) - no LLM call.")
        return {"dax_plan": plan_dict, "plan_cache_hit": True, **log.updates()}

    llm = get_llm(state, structured_schema=DaxPlan)
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task
         + f"\n\nDefault row limit for breakdown/time queries: {max_rows}."
         + "\nThe shared baseline evidence has already been fetched pre-fork. Do not plan "
           "a duplicate entity current/prior query; plan only summary supplements not present there."},
        {"role": "user", "content": "AVAILABLE MODEL OBJECTS:\n" + dumps(available)},
    ]

    plan: DaxPlan = llm.invoke(messages)
    plan_dict = plan.model_dump()

    plan_cache.save(state, dax_plan=plan_dict)
    file_io.write_json(state, "generated_dax_plan.json", plan_dict)
    log.info(f"Planned {len(plan_dict['queries'])} queries: "
             + ", ".join(q["name"] for q in plan_dict["queries"]))
    return {"dax_plan": plan_dict, **log.updates()}
