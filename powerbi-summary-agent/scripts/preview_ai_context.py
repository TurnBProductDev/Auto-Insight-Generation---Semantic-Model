"""Show exactly what the LLM sees when it looks at the semantic model.

Reconstructs the verbatim SYSTEM + USER messages sent to the two nodes that
read the semantic model directly - Node 3 (report_understanding) and Node 4
(dax_planner) - by calling the same functions the live pipeline calls
(``llm_model_context``, ``file_io.business_rules_block``, the real prompt
files) against a saved ``outputs/`` bundle from a prior run.

Offline: no auth, no Power BI call, no LLM call. Requires a prior run's
``model_metadata.json`` (and ideally ``semantic_model_profile.json``,
``resolved_entity_scope.json``, ``report_understanding.json``,
``baseline_scope_evidence.json``, ``baseline_coverage_clean_data.json``) to
already exist under ``--source`` (default ``outputs``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools import file_io  # noqa: E402
from src.utils.json_utils import dumps  # noqa: E402
from src.utils.model_context import llm_model_context  # noqa: E402


def _read(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    return json.loads(path.read_text(encoding="utf-8"))


def _fence(text: str, lang: str = "") -> str:
    return f"```{lang}\n{text}\n```\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="outputs", help="Folder with a prior run's output JSON files.")
    parser.add_argument("--output", default=None, help="Markdown file to write (default: <source>/ai_context_view.md).")
    args = parser.parse_args(argv)

    source = PROJECT_ROOT / args.source
    metadata = _read(source / "model_metadata.json")
    if not metadata:
        print(f"No model_metadata.json in {source} - run the pipeline at least once first.")
        return 1

    profile = _read(source / "semantic_model_profile.json")
    entity_scope = _read(source / "resolved_entity_scope.json")
    baseline_evidence = _read(source / "baseline_scope_evidence.json")
    baseline_coverage = _read(source / "baseline_coverage_clean_data.json")
    understanding = _read(source / "report_understanding.json")

    business_rules = file_io.read_business_rules()
    state = {"business_rules": business_rules}
    rules = file_io.read_prompt("_global_rules.md")

    cfg = _read(PROJECT_ROOT / "config" / "config.json")
    max_rows = cfg.get("max_rows_per_query", 15)

    # ---- Node 3: report_understanding (mirrors src/agents/report_understanding.py) ----
    task3 = file_io.read_prompt("report_understanding_prompt.md")
    ctx3 = llm_model_context(metadata)
    ctx3["deterministic_semantic_profile"] = profile
    ctx3["resolved_entity_scope"] = entity_scope
    node3_system = rules + file_io.business_rules_block(state) + "\n\n" + task3
    node3_user_prefix = "MODEL METADATA (complete structural view):"
    node3_user_json = dumps(ctx3)

    # ---- Node 4: dax_planner (mirrors src/agents/dax_planner.py) ----
    task4 = file_io.read_prompt("dax_planner_prompt.md")
    ctx4 = {
        **llm_model_context(metadata),
        "important_measures": understanding.get("important_measures", []),
        "important_dimensions": understanding.get("important_dimensions", []),
        "domain": understanding.get("domain"),
        "time_summary_possible": understanding.get("time_summary_possible"),
        "deterministic_semantic_profile": profile,
        "shared_baseline_evidence": baseline_evidence,
        "shared_metadata_coverage": baseline_coverage,
        "resolved_entity_scope": entity_scope,
    }
    node4_system = (
        rules + file_io.business_rules_block(state) + "\n\n" + task4
        + f"\n\nDefault row limit for breakdown/time queries: {max_rows}."
        + "\nThe shared baseline evidence has already been fetched pre-fork. Do not plan "
          "a duplicate entity current/prior query; plan only summary supplements not present there."
    )
    node4_user_prefix = "AVAILABLE MODEL OBJECTS:"
    node4_user_json = dumps(ctx4)

    # ---- assemble document ----
    doc = []
    doc.append("# What the AI Sees\n")
    doc.append(
        "Byte-for-byte reconstruction of the SYSTEM + USER messages the pipeline sends "
        "to the LLM, built by calling the same code the live run calls "
        "(`llm_model_context`, `file_io.business_rules_block`, the real `prompts/*.md` "
        f"files) against the metadata captured in `{args.source}/model_metadata.json` "
        "from the last real run against the semantic model.\n"
    )

    counts = metadata.get("counts", {})
    doc.append("## At a glance\n")
    doc.append(f"- Tables: {len(metadata.get('tables', []))}")
    doc.append(f"- Columns total: {len(metadata.get('columns', []))} (visible/non-hidden sent as bare refs: {len(ctx3['columns'])})")
    doc.append(f"- Measures: {len(ctx3['measures'])}")
    doc.append(f"- Relationships: {len(metadata.get('relationships', []))}")
    doc.append(f"- Date fields: {len(ctx3['date_fields'])}")
    doc.append(f"- Numeric fields: {len(ctx3['numeric_fields'])}")
    doc.append(f"- Categorical fields: {len(ctx3['categorical_fields'])}")
    if counts:
        doc.append(f"- Row counts reported by the model: `{json.dumps(counts, ensure_ascii=False)}`")
    doc.append(
        "\n**What is deliberately withheld from this payload:** measure DAX "
        "expressions/formulas are never included here - `measure_details` only carries "
        "`definition_available` (true/false). Formulas are fetched on demand later "
        "(by the DAX generator/repair loop and the investigator via "
        "`get_measure_definition`) so the up-front context stays small and cheap. Hidden "
        "columns stay out of the plain `columns` name list but remain visible with their "
        "type/category in `column_details`.\n"
    )

    doc.append("## Node 3 - Report Understanding\n")
    doc.append("*First LLM call that ever looks at the semantic model. Infers domain, fact/dimension tables, key measures/dimensions, date fields.*\n")
    doc.append("### SYSTEM message\n")
    doc.append(_fence(node3_system))
    doc.append("### USER message\n")
    doc.append(f"Text prefix: `{node3_user_prefix}`\n")
    doc.append(_fence(node3_user_json, "json"))
    if understanding:
        doc.append("### What it answered (`report_understanding.json`, from the saved run)\n")
        doc.append(_fence(dumps(understanding), "json"))

    doc.append("## Node 4 - DAX Planner\n")
    doc.append("*Second LLM call. Plans the free-text analytical questions to ask of the model - this is what turns into DAX in Node 5.*\n")
    doc.append("### SYSTEM message\n")
    doc.append(_fence(node4_system))
    doc.append("### USER message\n")
    doc.append(f"Text prefix: `{node4_user_prefix}`\n")
    doc.append(_fence(node4_user_json, "json"))

    text = "\n".join(doc)
    out_path = Path(args.output) if args.output else source / "ai_context_view.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"Wrote {out_path} ({len(text):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
