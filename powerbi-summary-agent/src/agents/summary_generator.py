"""Node 9 - Summary Generator Agent (LLM, free-form markdown)."""

from ..tools import file_io
from ..tools import html_report
from ..tools.llm import get_llm
from ..utils.json_utils import dumps
from ..utils.logger import RunLogger


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 9: generating the business summary...")

    rules = file_io.read_prompt("_global_rules.md")
    task = file_io.read_prompt("summary_generator_prompt.md")
    word_limit = state.get("summary_word_limit", 300)

    understanding = state.get("report_understanding", {})
    clean = state.get("clean_summary_data", {"queries": []})
    successful = clean.get("successful", 0)

    context = {
        "report_understanding": understanding,
        "results": clean,
        "shared_baseline_evidence": state.get("baseline_scope_evidence", {}),
        "shared_metadata_coverage": state.get("baseline_coverage_clean_data", {}),
        "resolved_entity_scope": state.get("resolved_entity_scope", {}),
        "word_limit": word_limit,
        "note": (
            "No queries returned usable data. Write the summary emphasizing data "
            "limitations." if successful == 0 else ""
        ),
    }

    llm = get_llm(state)  # free-form text output
    messages = [
        {"role": "system", "content": rules + file_io.business_rules_block(state)
         + "\n\n" + task
         + f"\n\nTarget length: about {word_limit} words."},
        {"role": "user", "content": "REPORT UNDERSTANDING + CLEAN RESULTS:\n" + dumps(context)},
    ]

    resp = llm.invoke(messages)
    summary = resp.content if hasattr(resp, "content") else str(resp)
    if isinstance(summary, list):  # some providers return content blocks
        summary = "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in summary
        )

    file_io.write_text(state, "report_summary.md", summary)

    domain = understanding.get("domain") if isinstance(understanding, dict) else None
    title = f"{domain} Report Summary" if domain else "Report Summary"
    file_io.write_text(state, "report_summary.html",
                       html_report.render(summary, title=title, eyebrow="Power BI Report Summary"))

    log.info(f"Summary written ({len(summary.split())} words).")
    return {"report_summary": summary, **log.updates()}
