"""Deterministic enforcement for metadata-resolved comparison scope.

``business_rules.md`` remains authoritative prose for every LLM.  This module
enforces the critical rule that can be represented mechanically: a query using
prior/change objects must be confined to the resolved comparable population and
must never include a current-only/excluded entity.
"""

import re

from .dax_validator import _extract_refs


_STRING = re.compile(r'"([^"]*)"')


def _function_spans(dax: str, function: str) -> list[tuple[int, int]]:
    """Return balanced spans for a DAX function, including nested calls."""
    spans = []
    opener = re.compile(rf"\b{re.escape(function)}\s*\(", re.IGNORECASE)
    for match in opener.finditer(dax or ""):
        depth, quoted, i = 0, False, match.end() - 1
        while i < len(dax):
            ch = dax[i]
            if ch == '"':
                # DAX escapes a quote inside a string by doubling it.
                if quoted and i + 1 < len(dax) and dax[i + 1] == '"':
                    i += 2
                    continue
                quoted = not quoted
            elif not quoted:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        spans.append((match.start(), i + 1))
                        break
            i += 1
    return spans


def _object_positions(dax: str, profile: dict) -> list[int]:
    measures, columns = _comparison_objects(profile)
    positions = []
    for name in measures:
        positions.extend(m.start() for m in re.finditer(
            rf"\[{re.escape(name)}\]", dax or "", re.IGNORECASE))
    for table, column in columns:
        if not table or not column:
            continue
        patterns = (
            rf"'{re.escape(table)}'\s*\[{re.escape(column)}\]",
            rf"\b{re.escape(table)}\s*\[{re.escape(column)}\]",
        )
        for pattern in patterns:
            positions.extend(m.start() for m in re.finditer(pattern, dax or "", re.IGNORECASE))
    return positions


def _isolated_mixed_scope(dax: str, profile: dict, entity: dict,
                          comparable: set[str], excluded: set[str]) -> bool:
    """Allow a mixed result only when comparison and current-only expressions
    are isolated in separate CALCULATE calls with their own entity filters.

    This supports a report row/UNION that shows comparable YoY and a new
    entity's current actual side by side without weakening the leak guard.
    """
    spans = _function_spans(dax, "CALCULATE")
    if not spans:
        return False
    normalized_entity = re.sub(r"\s+", "", entity.get("reference", "")).replace("'", "").lower()

    def containing(position: int):
        candidates = [(a, b) for a, b in spans if a <= position < b]
        return min(candidates, key=lambda pair: pair[1] - pair[0]) if candidates else None

    comparison_positions = _object_positions(dax, profile)
    if not comparison_positions:
        return False
    for position in comparison_positions:
        span = containing(position)
        if not span:
            return False
        body = dax[span[0]:span[1]]
        literals = set(_STRING.findall(body))
        body_norm = re.sub(r"\s+", "", body).replace("'", "").lower()
        if literals & excluded or not (literals & comparable) or normalized_entity not in body_norm:
            return False

    # Every exact excluded member literal must sit in a CALCULATE that contains
    # current-only expressions, never a prior/change object.
    for member in excluded:
        for match in re.finditer(rf'"{re.escape(member)}"', dax or ""):
            span = containing(match.start())
            if not span:
                return False
            body = dax[span[0]:span[1]]
            if _uses_comparison(body, profile, None):
                return False
            body_norm = re.sub(r"\s+", "", body).replace("'", "").lower()
            if normalized_entity not in body_norm:
                return False
    return True


def _comparison_objects(profile: dict) -> tuple[set[str], set[tuple[str, str]]]:
    measures, columns = set(), set()
    roles = profile.get("measure_roles") or {}
    # A word such as "last" can describe a refresh timestamp rather than a
    # prior business period. Only measures participating in a coherent
    # metadata-built current/prior/change bundle are comparison objects.
    bundles = profile.get("measure_bundles") or []
    for bundle in bundles:
        for phase in ("prior", "change"):
            name = (bundle.get("measures") or {}).get(phase)
            if not name:
                continue
            measures.add(name)
            for ref in (roles.get(name) or {}).get("column_refs", []):
                columns.add((ref.get("table"), ref.get("column")))
    # Compatibility for an old/replayed profile without bundle information.
    if not bundles:
        for name, role in roles.items():
            if role.get("phase") in ("prior", "change"):
                measures.add(name)
                for ref in role.get("column_refs", []):
                    columns.add((ref.get("table"), ref.get("column")))
    return measures, columns


def _uses_comparison(dax: str, profile: dict, contract_hint: dict | None) -> bool:
    for metric in (contract_hint or {}).get("metrics", []):
        if metric.get("phase") in ("prior", "change"):
            return True
    cols, measures = _extract_refs(dax or "")
    comparison_measures, comparison_cols = _comparison_objects(profile)
    return bool(set(measures) & comparison_measures or set(cols) & comparison_cols)


def validate_comparable_scope(dax: str, state: dict, contract_hint: dict | None = None) -> list[str]:
    profile = state.get("semantic_model_profile", {})
    scope = state.get("resolved_entity_scope", {})
    if not _uses_comparison(dax, profile, contract_hint):
        return []

    entity = scope.get("entity_dimension") or profile.get("entity_dimension") or {}
    comparable = {str(v) for v in scope.get("active_comparable_population", [])
                  or state.get("insight_comparable_population", []) or []}
    excluded = {str(v) for v in scope.get("excluded_from_comparison", [])
                or state.get("insight_excluded_entities", []) or []}
    if not entity.get("reference") or not comparable:
        # No entity rule can be enforced in a model without a resolved entity
        # scope.  The evidence contract will report it as unknown; do not invent
        # a population or block a model that genuinely has no entity concept.
        return []

    hint_status = (contract_hint or {}).get("population_status")
    hint_codes = {str(v) for v in (contract_hint or {}).get("population_codes", [])}
    if hint_codes & excluded:
        return [f"comparison contract includes excluded/current-only entities: {sorted(hint_codes & excluded)}"]
    if hint_status == "comparable" and hint_codes and hint_codes <= comparable:
        return []

    literals = set(_STRING.findall(dax or ""))
    mentioned = literals & (comparable | excluded)
    bad = mentioned & excluded
    if bad:
        if _isolated_mixed_scope(dax, profile, entity, comparable, excluded):
            return []
        return [f"comparison query includes excluded/current-only entities: {sorted(bad)}"]

    # A subset is valid for a focused comparable-entity investigation; the full
    # set is valid for model totals/breakdowns.  The entity reference must also
    # appear so unrelated string literals cannot accidentally satisfy the gate.
    normalized = re.sub(r"\s+", "", dax or "").replace("'", "").lower()
    entity_token = re.sub(r"\s+", "", entity.get("reference", "")).replace("'", "").lower()
    if mentioned and mentioned <= comparable and entity_token in normalized:
        return []
    return [
        "comparison query is not provably filtered to the resolved comparable population "
        f"on {entity.get('reference')}"
    ]
