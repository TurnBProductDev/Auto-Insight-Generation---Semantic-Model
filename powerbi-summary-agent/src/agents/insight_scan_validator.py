"""Insight branch - Scan DAX Validator (deterministic).

Reuses dax_validator.validate_one against the same model metadata. Invalid
queries are kept as insight_skipped_dax_queries for the one-shot repair loop.
Sets insight_fatal (never the shared `fatal`) when nothing survives.
"""

from ..tools import file_io
from ..utils.logger import RunLogger

from .dax_validator import validate_one
from .scope_validator import validate_comparable_scope


def run(state: dict) -> dict:
    log = RunLogger(state)
    log.info("Insight branch: validating scan DAX against metadata...")

    md = state["model_metadata"]
    validated = []
    skipped = []
    audit = []

    for g in state.get("insight_generated_dax_queries", []):
        reasons = validate_one(g.get("dax"), md)
        reasons += validate_comparable_scope(g.get("dax", ""), state, g.get("contract_hint"))
        status = "valid" if not reasons else "skipped"
        record = {**g, "status": status}
        if reasons:
            record["reason"] = "; ".join(reasons)
            log.info(f"  insight scan held for repair {g['name']}: {record['reason']}")
            skipped.append({**g, "reason": record["reason"]})
        else:
            validated.append(dict(g))
        audit.append(record)

    file_io.write_json(state, "insight_validated_dax_queries.json", audit)

    fatal = not validated and not skipped
    if fatal:
        log.error("No insight scan queries were generated - insight branch stopping.")
    else:
        log.info(
            f"Insight scan: {len(validated)} of {len(audit)} queries passed validation "
            f"({len(skipped)} eligible for repair)."
        )

    return {
        "insight_validated_dax_queries": validated,
        "insight_skipped_dax_queries": skipped,
        "insight_fatal": fatal,
        **log.updates(),
    }
