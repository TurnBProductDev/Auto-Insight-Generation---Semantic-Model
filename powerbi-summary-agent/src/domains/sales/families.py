"""The retail measure vocabulary - the single place it is defined.

Brief §1.3 names the defect this closes: the codebase carried **two independent
copies** of the retail family vocabulary, in `semantic_profiler._FAMILY_TOKENS`
and `summary_candidate_builder._family()`, free to disagree with nothing to
catch it.

They already disagree, and not slightly
---------------------------------------
Measured across the 56 measure names in the two committed acceptance models:
**37 of 56 classify differently.** They are not a copy and its drifted twin -
they are two different classifiers:

* different family *names* - `margin` vs `rate`, `other` vs `performance`
* different membership - `spend` is **cost** to the profiler and **rate** to the
  builder; the profiler has `cost` and `customers` families the builder lacks
* different method - the profiler *scores* name tokens 3x against lineage tokens
  1x and takes the best; the builder short-circuits on the first matching set
* different reach - the builder's revenue set has `revenue` but not `rev`, so
  **`REV_CURRENT` is revenue to the profiler and performance to the builder**

So they are **not** merged here. Merging them would change candidate keys,
memory keys and rotation on the live model, which is precisely the silent
arithmetic change the golden master exists to prevent. What is fixed is the
drift *risk*: both now live in this file, side by side, so a change to one is
made in sight of the other, and `replay_domain_assembly.py` pins the divergence
so it cannot widen unnoticed.

Unifying them is a deliberate future change with its own before/after evidence,
not a side effect of a refactor.
"""

from __future__ import annotations

# --- the profiler's vocabulary (scored) ---------------------------------------
# Used by `semantic_profiler` to build measure bundles. Scoring means a measure
# named for one family but built over another family's column still lands
# sensibly: the semantic name counts 3x, incidental lineage 1x.

PROFILER_FAMILY_TOKENS: dict[str, set[str]] = {
    "revenue": {"revenue", "rev", "sales", "sale", "turnover", "gmv", "value", "amount"},
    "profit": {"profit", "contribution", "earnings", "ebit", "ebitda"},
    "cost": {"cost", "expense", "spend"},
    "quantity": {"quantity", "qty", "units", "unit", "volume"},
    "transactions": {"transactions", "transaction", "bills", "bill", "orders", "order",
                     "visits", "visit"},
    "customers": {"customers", "customer", "clients", "client", "shoppers", "shopper"},
    "margin": {"margin", "rate", "ratio", "percent", "percentage", "price", "average", "avg"},
}

#: Families that can carry the primary value metric.
PROFILER_VALUE_FAMILIES = {"revenue", "profit", "cost"}

#: Families that count activity rather than value - the economic drivers.
PROFILER_VOLUME_FAMILIES = {"quantity", "transactions", "customers"}

#: Which family wins when two score equally. Revenue leads because it is the
#: metric the business is actually run on.
PROFILER_FAMILY_PRIORITY: dict[str, int] = {
    "revenue": 100,
    "profit": 90,
    "cost": 70,
    "quantity": 60,
    "transactions": 55,
    "customers": 50,
    "margin": 20,
    "other": 0,
}

PROFILER_DEFAULT_FAMILY = "other"


# --- the candidate builder's vocabulary (first match wins) ---------------------
# Used by `summary_candidate_builder` to label a returned column. Narrower and
# name-only, because by that point the column has already been selected and the
# label is for presentation and keying rather than for choosing a metric.
# Ordered: the first matching set wins, so the sequence is part of the meaning.

CANDIDATE_FAMILY_ORDER: tuple[tuple[str, set[str]], ...] = (
    ("revenue", {"revenue", "sales", "turnover", "amount", "value"}),
    ("quantity", {"qty", "quantity", "units", "volume"}),
    ("transactions", {"bills", "transactions", "orders", "visits"}),
    ("rate", {"margin", "price", "rate", "spend", "average", "avg"}),
    ("profit", {"profit", "earnings"}),
)

CANDIDATE_DEFAULT_FAMILY = "performance"


def candidate_family(tokens: set[str]) -> str:
    """Label a measure name for the candidate builder. First match wins."""
    for family, hints in CANDIDATE_FAMILY_ORDER:
        if tokens & hints:
            return family
    return CANDIDATE_DEFAULT_FAMILY


#: The two vocabularies' family names, for anything that needs to know the union
#: exists (and that it is not one set).
PROFILER_FAMILIES = frozenset(PROFILER_FAMILY_TOKENS) | {PROFILER_DEFAULT_FAMILY}
CANDIDATE_FAMILIES = frozenset(name for name, _ in CANDIDATE_FAMILY_ORDER) | {
    CANDIDATE_DEFAULT_FAMILY}
