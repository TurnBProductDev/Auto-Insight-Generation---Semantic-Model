"""Show the raw semantic-model metadata exactly as the code reads it.

This is Node 2 (metadata_reader) output only - the literal result of
INFO.VIEW.TABLES() / INFO.VIEW.COLUMNS() / INFO.VIEW.MEASURES() /
INFO.VIEW.RELATIONSHIPS() (plus Fabric getDefinition expression enrichment).
No LLM, no agent planning, no business rules, no prompts - just what the
code pulled from the model.

Offline: reads a saved outputs/model_metadata.json from a prior run. No
auth, no Power BI call, no LLM call.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _bool(v) -> str:
    return "yes" if v else "no"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="outputs", help="Folder with a prior run's model_metadata.json.")
    parser.add_argument("--output", default=None, help="Markdown file to write (default: <source>/raw_metadata_view.md).")
    args = parser.parse_args(argv)

    source = PROJECT_ROOT / args.source
    meta_path = source / "model_metadata.json"
    if not meta_path.exists():
        print(f"No model_metadata.json in {source} - run the pipeline at least once first.")
        return 1
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    tables = metadata.get("tables", [])
    columns = metadata.get("columns", [])
    measures = metadata.get("measures", [])
    relationships = metadata.get("relationships", [])
    counts = metadata.get("counts", {})

    cols_by_table = defaultdict(list)
    for c in columns:
        cols_by_table[c.get("table", "")].append(c)

    measures_by_table = defaultdict(list)
    for m in measures:
        measures_by_table[m.get("table", "")].append(m)

    doc = []
    doc.append("# Raw Semantic Model Metadata\n")
    doc.append(
        "Exactly what Node 2 (`metadata_reader`) reads from the model via "
        "`INFO.VIEW.TABLES()`, `INFO.VIEW.COLUMNS()`, `INFO.VIEW.MEASURES()`, "
        "`INFO.VIEW.RELATIONSHIPS()` (measure expressions enriched from the Fabric "
        "`getDefinition` TMSL where the executeQueries endpoint redacts them). "
        "This is the ground-truth scan - no LLM, no agent, no prompts, no business "
        "rules have touched it yet.\n"
    )

    doc.append("## Summary\n")
    doc.append(f"- Tables: {counts.get('tables', len(tables))}")
    doc.append(f"- Columns: {counts.get('columns', len(columns))}")
    doc.append(f"- Measures: {counts.get('measures', len(measures))}")
    doc.append(f"- Relationships: {counts.get('relationships', len(relationships))}")
    hidden_tables = sum(1 for t in tables if t.get("is_hidden"))
    hidden_cols = sum(1 for c in columns if c.get("is_hidden"))
    hidden_measures = sum(1 for m in measures if m.get("is_hidden"))
    doc.append(f"- Hidden: {hidden_tables} tables, {hidden_cols} columns, {hidden_measures} measures\n")

    doc.append("## Tables & Columns\n")
    for t in tables:
        name = t.get("name", "")
        doc.append(f"### {name}")
        meta_bits = []
        if t.get("is_hidden"):
            meta_bits.append("hidden")
        if t.get("description"):
            meta_bits.append(t["description"])
        if meta_bits:
            doc.append(f"*{' - '.join(meta_bits)}*")
        cols = cols_by_table.get(name, [])
        if cols:
            doc.append("")
            doc.append("| Column | Data Type | Category | Hidden | Key | Summarize By | Description |")
            doc.append("|---|---|---|---|---|---|---|")
            for c in cols:
                doc.append(
                    f"| {c.get('column','')} | {c.get('data_type','')} | {c.get('category','')} "
                    f"| {_bool(c.get('is_hidden'))} | {_bool(c.get('is_key'))} "
                    f"| {c.get('summarize_by','')} | {c.get('description','')} |"
                )
        else:
            doc.append("*(no columns read for this table)*")
        doc.append("")

    doc.append("## Measures\n")
    for name in sorted(measures_by_table):
        table_measures = measures_by_table[name]
        doc.append(f"### {name or '(no table)'}\n")
        for m in table_measures:
            hidden = " *(hidden)*" if m.get("is_hidden") else ""
            doc.append(f"#### {m.get('name','')}{hidden}")
            expr = m.get("expression") or ""
            if expr:
                doc.append("```dax\n" + expr + "\n```")
            else:
                doc.append("*(expression not available - redacted by executeQueries and not recovered via Fabric)*")
            details = []
            if m.get("format_string"):
                details.append(f"Format: `{m['format_string']}`")
            if m.get("display_folder"):
                details.append(f"Display folder: {m['display_folder']}")
            if m.get("description"):
                details.append(f"Description: {m['description']}")
            if details:
                doc.append(" | ".join(details))
            doc.append("")

    doc.append("## Relationships\n")
    if relationships:
        doc.append("| From | Cardinality | To | Active | Cross-filter |")
        doc.append("|---|---|---|---|---|")
        for r in relationships:
            card = f"{r.get('from_cardinality','')}→{r.get('to_cardinality','')}"
            doc.append(
                f"| {r.get('from_table','')}[{r.get('from_column','')}] | {card} "
                f"| {r.get('to_table','')}[{r.get('to_column','')}] | {_bool(r.get('is_active'))} "
                f"| {r.get('cross_filtering_behavior','')} |"
            )
    else:
        doc.append("*(none read)*")
    doc.append("")

    def _field_line(label: str, key: str) -> str:
        vals = metadata.get(key, [])
        rendered = ", ".join(f"`{f}`" for f in vals) if vals else "*(none)*"
        return f"**{label} ({len(vals)}):** {rendered}"

    doc.append("## Classified fields (as the code categorizes them)\n")
    doc.append(_field_line("Date fields", "date_fields"))
    doc.append("")
    doc.append(_field_line("Numeric fields", "numeric_fields"))
    doc.append("")
    doc.append(_field_line("Categorical fields", "categorical_fields"))
    doc.append("")

    text = "\n".join(doc)
    out_path = Path(args.output) if args.output else source / "raw_metadata_view.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"Wrote {out_path} ({len(text):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
