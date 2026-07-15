"""Node 3 - Report Understanding Agent (LLM, structured output)."""

from typing import List

from pydantic import BaseModel, Field

from ..tools import file_io
from ..tools.llm import get_llm
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


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 3: understanding the report/model...")

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

    file_io.write_json(state, "report_understanding.json", understanding)
    log.info(
        f"Domain: {understanding.get('domain')!r}; "
        f"{len(understanding.get('important_measures', []))} key measures; "
        f"time summary possible: {understanding.get('time_summary_possible')}."
    )
    return {"report_understanding": understanding, **log.updates()}
