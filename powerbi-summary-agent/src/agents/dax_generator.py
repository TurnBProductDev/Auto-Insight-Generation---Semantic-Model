"""Node 5 - DAX Generator (LLM).

Turns each planned intent into one executable DAX statement directly - no
fixed shape templates. Also exposes `repair()`, used by Node 7's one-shot
self-repair loop to fix a query that failed validation or execution.
"""

from ..tools import file_io
from ..tools.llm import get_llm
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger
from ..utils.model_context import llm_model_context


def _available_objects(md: dict) -> dict:
    return llm_model_context(md)


def _strip_code_fence(text: str) -> str:
    """LLMs sometimes wrap DAX in a ```dax fence despite being told not to; strip it."""
    t = text.strip()
    if t.startswith("```"):
        lines = t.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines)
    return t.strip()


def _invoke(state: dict, user_content: str) -> str:
    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("dax_generator_prompt.md")
    llm = get_llm(state)
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task},
        {"role": "user", "content": user_content},
    ]
    resp = llm.invoke(messages)
    dax = resp.content if hasattr(resp, "content") else str(resp)
    if isinstance(dax, list):  # some providers return content blocks
        dax = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in dax)
    return _strip_code_fence(dax)


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 5: generating DAX for each planned query (LLM)...")

    md = state["model_metadata"]
    max_rows = state.get("max_rows_per_query", 15)
    available = _available_objects(md)

    generated = []
    for q in state["dax_plan"]["queries"]:
        content = (
            "AVAILABLE MODEL OBJECTS:\n" + dumps(available)
            + f"\n\nDefault row limit if the intent doesn't specify one: {max_rows}."
            + "\n\nQUERY TO WRITE:\nname: " + q["name"]
            + "\npurpose: " + q.get("purpose", "")
            + "\nintent: " + q["intent"]
        )
        dax = _invoke(state, content)
        generated.append({
            "name": q["name"],
            "purpose": q.get("purpose", ""),
            "intent": q.get("intent", ""),
            "dax": dax,
        })
        log.info(f"  {q['name']}: generated.")

    file_io.write_json(state, "generated_dax_queries.json", generated)
    log.info(f"Generated {len(generated)} DAX statements.")
    return {"generated_dax_queries": generated, **log.updates()}


def repair(state: dict, entry: dict, error: str) -> str:
    """Ask the LLM to fix a DAX statement that failed validation or execution."""
    md = state["model_metadata"]
    available = _available_objects(md)
    content = (
        "AVAILABLE MODEL OBJECTS:\n" + dumps(available)
        + "\n\nQUERY TO FIX:\nname: " + entry["name"]
        + "\npurpose: " + entry.get("purpose", "")
        + "\nintent: " + entry.get("intent", "")
        + "\n\nPREVIOUS DAX:\n" + (entry.get("dax") or "")
        + "\n\nIT FAILED WITH:\n" + error
        + "\n\nWrite ONE corrected DAX statement that fixes this, following the "
          "same rules. Reference only real objects from AVAILABLE MODEL OBJECTS."
    )
    return _invoke(state, content)
