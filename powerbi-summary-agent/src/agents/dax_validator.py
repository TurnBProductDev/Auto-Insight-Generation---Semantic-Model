"""Node 6 - DAX Validator (deterministic).

Node 5 now writes free-form DAX text (no fixed template shape to read
structured refs from), so this parses every 'Table'[Column]/Table[Column]
reference and bare [Measure] token directly out of the DAX string and checks
it against the model metadata. Bare [Name] tokens matching a query-local
column alias (the "Name" in ADDCOLUMNS/SELECTCOLUMNS/ROW/SUMMARIZECOLUMNS
argument slots) are recognized as aliases, not treated as unknown measures.
Invalid queries are marked 'skipped' with a reason but kept (as
`skipped_dax_queries`) for Node 7's one-shot repair loop; valid ones move on
to execution.
"""

import re

from ..tools import file_io
from ..utils.logger import RunLogger

_QUOTED_COL = re.compile(r"'([^']+)'\[([^\]]+)\]")
_BARE_TABLE_COL = re.compile(r"(?<![\]\w'])([A-Za-z_][A-Za-z0-9_]*)\[([^\]]+)\]")
_BRACKET = re.compile(r"\[([^\]]+)\]")
# Query-local column aliases: the "Name" in ADDCOLUMNS/SELECTCOLUMNS/
# SUMMARIZECOLUMNS/ROW(..., "Name", <expr>, ...) — a quoted string sitting in
# an argument slot (after `(` or `,`, followed by `,`). A later bare [Name]
# token then refers to that alias, not to a model measure.
_ALIAS_DEF = re.compile(r'[(,]\s*"([^"]+)"\s*(?=,)')


def _extract_refs(dax: str):
    """Pull every table[column] reference and bare [Measure] token out of raw DAX text."""
    column_refs = []
    spans = []

    for m in _QUOTED_COL.finditer(dax):
        column_refs.append((m.group(1), m.group(2)))
        spans.append(m.span())

    for m in _BARE_TABLE_COL.finditer(dax):
        if any(m.start() >= s and m.end() <= e for s, e in spans):
            continue
        column_refs.append((m.group(1), m.group(2)))
        spans.append(m.span())

    measures = []
    for m in _BRACKET.finditer(dax):
        if any(m.start() >= s and m.end() <= e for s, e in spans):
            continue
        measures.append(m.group(1))

    return column_refs, measures


def validate_one(dax: str, metadata: dict) -> list:
    """Return a list of validation-failure reasons; an empty list means the DAX is valid."""
    if not dax:
        return ["no DAX generated"]

    reasons = []
    if dax.count("EVALUATE") != 1:
        reasons.append("query must contain exactly one EVALUATE")

    table_names = {t["name"] for t in metadata.get("tables", [])}
    measure_names = {m["name"] for m in metadata.get("measures", [])}
    column_pairs = {(c["table"], c["column"]) for c in metadata.get("columns", [])}

    aliases = set(_ALIAS_DEF.findall(dax))

    column_refs, measures = _extract_refs(dax)
    for tbl, col in column_refs:
        if (tbl, col) in column_pairs:
            continue
        reasons.append(f"unknown table: {tbl}" if tbl not in table_names else f"unknown column: {tbl}[{col}]")
    for m in measures:
        if m not in measure_names and m not in aliases:
            reasons.append(f"unknown measure: {m}")

    if "SUMMARIZECOLUMNS(" in dax.upper() and "TOPN(" not in dax.upper():
        reasons.append("breakdown-style query missing a row limit (TOPN)")

    return reasons


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Node 6: validating generated DAX against metadata...")

    md = state["model_metadata"]
    validated = []
    skipped = []
    audit = []

    for g in state["generated_dax_queries"]:
        reasons = validate_one(g.get("dax"), md)
        # Import locally to avoid a module cycle: scope_validator reuses this
        # module's reference parser.
        from .scope_validator import validate_comparable_scope
        reasons += validate_comparable_scope(g.get("dax", ""), state, g.get("contract_hint"))
        status = "valid" if not reasons else "skipped"
        record = {**g, "status": status}
        if reasons:
            record["reason"] = "; ".join(reasons)
            # This is recoverable: Node 7 gets one repair attempt.  Only a
            # failed repair/execution belongs in the final run error list.
            log.info(f"  held for repair {g['name']}: {record['reason']}")
            skipped.append({**g, "reason": record["reason"]})
        else:
            validated.append(dict(g))
        audit.append(record)

    file_io.write_json(state, "validated_dax_queries.json", audit)

    fatal = not validated and not skipped
    if fatal:
        log.error("No DAX queries were generated - stopping.")
    else:
        log.info(
            f"{len(validated)} of {len(audit)} queries passed validation "
            f"({len(skipped)} eligible for repair)."
        )

    # Branch-scoped fatal: this node runs concurrently with the insight branch,
    # so it must never write the shared pre-fork `fatal` key.
    return {
        "validated_dax_queries": validated,
        "skipped_dax_queries": skipped,
        "summary_fatal": fatal,
        **log.updates(),
    }
