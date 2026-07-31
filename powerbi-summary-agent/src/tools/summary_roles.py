"""Summary-only canonical business-hierarchy roles, aliases, and depth.

R4 restricts an individual daily focus to Division, Department or Category.
This module owns the vocabulary that decides which dimension roles may become a
primary focus and how roles order within the business hierarchy, so the
portfolio selector, candidate builder and deep dive all share one definition
without any of them importing another agent. It imports no insight module and
contains no model-specific table, column, or member names - only generic
semantic role vocabulary.
"""

from __future__ import annotations

from typing import Any

from . import summary_memory


# Canonical hierarchy levels: a lower number is higher/broader in the business
# hierarchy. This mirrors the deep dive's ``_HIERARCHY_PATTERNS`` ordering but is
# owned here so focus-role logic never imports the deep-dive agent. The values
# are semantic vocabulary, never model object names or members.
HIERARCHY_LEVELS: dict[str, int] = {
    "division": 10,
    "department": 20,
    "category": 30,
    "subcategory": 35,
    "product_group": 40,
    "special_product_group": 50,
    "brand": 60,
    "product": 70,
    "item": 70,
    "sku": 70,
}

# Default roles that may consume an individual focus slot. Everything below
# Category (product group / product / sku) and orthogonal roles (store, region,
# period) are supporting evidence only, never a primary focus.
DEFAULT_ALLOWED_ROLES: tuple[str, ...] = ("division", "department", "category")


def _norm(value: Any) -> str:
    return summary_memory._norm_text(value)


def allowed_roles(state: dict) -> tuple[str, ...]:
    """Configured primary-focus roles, normalized; falls back to the default."""
    raw = (
        state.get("summary_focus_allowed_roles")
        or (state.get("config", {}) or {}).get("summary_focus_allowed_roles")
        or DEFAULT_ALLOWED_ROLES
    )
    if isinstance(raw, str):
        raw = [raw]
    roles = tuple(dict.fromkeys(_norm(role) for role in raw if _norm(role)))
    return roles or DEFAULT_ALLOWED_ROLES


def role_aliases(state: dict) -> dict[str, str]:
    """Config-driven map from a model's role/dimension name to a canonical role."""
    raw = (
        state.get("summary_focus_role_aliases")
        or (state.get("config", {}) or {}).get("summary_focus_role_aliases")
        or {}
    )
    if not isinstance(raw, dict):
        return {}
    return {_norm(key): _norm(value) for key, value in raw.items() if _norm(key) and _norm(value)}


def _contains_phrase(text: str, phrase: str) -> bool:
    """Whole-token containment: 'business unit' matches 'company business unit'."""
    if not text or not phrase:
        return False
    text_tokens = text.split()
    phrase_tokens = phrase.split()
    span = len(phrase_tokens)
    if span == 0 or span > len(text_tokens):
        return False
    return any(text_tokens[i:i + span] == phrase_tokens for i in range(len(text_tokens) - span + 1))


def canonical_role(role: Any, dimension: Any, state: dict) -> str:
    """Map a raw role/dimension onto a canonical role, honouring config aliases.

    Aliases let another model expose an equivalent hierarchy under different
    names (``business_unit -> division``). Matching is on the normalized role
    first, then the dimension name, by whole-token containment so a multi-word
    alias still resolves. With no aliases configured this is a no-op that simply
    normalizes the incoming role.
    """
    role_norm = _norm(role)
    aliases = role_aliases(state)
    if role_norm in aliases:
        return aliases[role_norm]
    dim_norm = _norm(dimension)
    if dim_norm in aliases:
        return aliases[dim_norm]
    for key, target in aliases.items():
        if _contains_phrase(dim_norm, key) or _contains_phrase(role_norm, key):
            return target
    return role_norm


def is_primary_focus_role(role: Any, dimension: Any, state: dict) -> bool:
    """True when the (alias-resolved) role may consume an individual focus slot."""
    return canonical_role(role, dimension, state) in set(allowed_roles(state))


def hierarchy_level(role: Any) -> int | None:
    """Business-hierarchy depth for a canonical role (lower = broader)."""
    return HIERARCHY_LEVELS.get(_norm(role))


def is_descendant(child_role: Any, parent_role: Any) -> bool:
    """True when ``child_role`` is strictly below ``parent_role`` in the hierarchy."""
    child = hierarchy_level(child_role)
    parent = hierarchy_level(parent_role)
    if child is None or parent is None:
        return False
    return child > parent
