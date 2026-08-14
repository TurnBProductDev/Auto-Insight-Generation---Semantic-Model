"""The inventory vocabulary: stock, cover, value, ageing.

Built from the live models and the two rulebooks (WP0), not guessed at. Every
name here was observed on `REP_SSR_STOCK_STATUS_REPORTV2` or `REP_SSR_SAG` on
2026-08-13, and the aggregation classes come from what the arithmetic showed.

Why this cannot reuse the sales vocabulary
------------------------------------------
`semantic_profiler._FAMILY_TOKENS` has no stock words at all, and `"value"` is a
**revenue** token there - so `Stock Value on Hand` classifies as revenue and
`Stock Units` as quantity. That is not merely untidy: the sales families carry
`ADDITIVE` semantics, and a stock measure summed over time is Nx wrong
(measured: 4.03x over four snapshots).

Directions matter here in a way they do not for sales
-----------------------------------------------------
For revenue, up is good. Half of these are the opposite: more excess stock, more
non-moving stock, more aged stock and a longer time in an exception are all
worse. `HIGHER_IS_WORSE` records that, so a RAG band or a headline cannot read a
rising number as good news.
"""

from __future__ import annotations

from ...kernel.aggregation import AggregationClass

#: family -> the words that identify it. Matched against measure and column
#: names the same way the sales vocabulary is.
FAMILY_TOKENS: dict[str, set[str]] = {
    # SAR value of stock held. The headline of both reports.
    "stock_value": {"stock", "stockvalue", "value", "inventory", "landing", "cost"},
    # Physical units held.
    "stock_units": {"units", "unit", "qty", "quantity", "closing", "onhand"},
    # Days of stock remaining at the current rate of sale or transfer.
    "cover": {"burnout", "burn", "cover", "bd", "days", "expected"},
    # Stock held beyond the agreed coverage threshold.
    "excess": {"excess", "surplus", "overstock"},
    # Stock with no sales while it was available.
    "non_moving": {"nonmoving", "nm", "stagnant", "nomovement"},
    # How long stock has been held, in bands.
    "ageing": {"age", "ageing", "aging", "aged", "purchase", "period", "bucket"},
    # The replenishment policy itself.
    "policy": {"reorder", "rp", "lead", "safety", "threshold", "min", "max"},
    # Stock at zero when it should not be.
    "stockout": {"stockout", "stock_out", "verge", "outofstock"},
    # Estimated revenue not earned because of a stockout.
    "opportunity_loss": {"opportunity", "opploss", "loss"},
    # Unreceived purchase orders.
    "pending_orders": {"pending", "order", "orders", "po"},
    # Negative inventory adjustments: damage, expiry, wastage.
    "damage": {"damage", "expiry", "wastage", "writeoff", "adjustment"},
}

#: The family that carries the headline number for both reports.
PRIMARY_FAMILY = "stock_value"

#: Families whose value is a SAR amount, so they can be summed across members
#: and used as the exposure a finding is ranked by.
VALUE_FAMILIES = {"stock_value", "excess", "opportunity_loss", "pending_orders", "damage"}

#: Families that count things rather than measuring value.
VOLUME_FAMILIES = {"stock_units"}

#: Families where a rising number is BAD. Without this a RAG band reads growing
#: excess stock as growth.
HIGHER_IS_WORSE = frozenset({
    "excess", "non_moving", "ageing", "stockout", "opportunity_loss", "damage",
})

#: How each family may legitimately be combined. `cover` is DURATION rather than
#: a ratio because it is a span attached to a state - and because the live data
#: carries a sentinel of 1000 meaning "no velocity" alongside a real maximum of
#: 63,044, so averaging it is actively misleading (findings §10.1).
AGGREGATION: dict[str, AggregationClass] = {
    "stock_value": AggregationClass.SEMI_ADDITIVE_LAST,
    "stock_units": AggregationClass.SEMI_ADDITIVE_LAST,
    "excess": AggregationClass.SEMI_ADDITIVE_LAST,
    "pending_orders": AggregationClass.SEMI_ADDITIVE_LAST,
    "damage": AggregationClass.ADDITIVE,          # a flow, not a position
    "opportunity_loss": AggregationClass.ADDITIVE,  # a per-day estimate
    "cover": AggregationClass.DURATION,
    "ageing": AggregationClass.DURATION,
    "non_moving": AggregationClass.ADDITIVE_WITHIN_LEVEL,  # a SKU at 3 stores
    "stockout": AggregationClass.ADDITIVE_WITHIN_LEVEL,
    "policy": AggregationClass.NON_ADDITIVE_RATIO,  # a threshold, never summed
}

DEFAULT_FAMILY = "other"

#: The product hierarchy both rulebooks specify (BR-02). Note the model column
#: is named DEPARTMENT but means **Division** - so a config alias is required,
#: because `summary_roles.HIERARCHY_LEVELS` puts division at depth 10 and
#: department at 20. Without the alias the top level lands at the wrong depth.
HIERARCHY = ("division", "section", "category", "brand", "sku")

#: The column that carries the top level, and what it must be called in output.
DIVISION_COLUMN = "DEPARTMENT"
DIVISION_LABEL = "Division"

#: A value in a cover measure that means "no velocity", NOT a number of days
#: (Inventory BR-11). 16.3% of live rows carry it.
COVER_SENTINEL = 1000

#: Manager-facing names. Both rulebooks ban the alternatives outright (BR-03),
#: including "days of cover" for Burn-Out Days and "footfall" for transactions.
APPROVED_NAMES: dict[str, str] = {
    "stock_value": "Stock Value",
    "cover": "Burn-Out Days",
    "excess": "Excess Stock",
    "non_moving": "Non-Moving",
    "opportunity_loss": "Opportunity Loss",
    "pending_orders": "Pending Orders",
    "damage": "Damage",
    "ageing": "Aged Stock",
}

#: Words that must never appear in output for these reports. Drawn from BR-03
#: and BR-33/BR-25 of the two rulebooks.
BANNED_WORDS = frozenset({
    "inventory value", "stock worth", "asset value",
    "days of cover", "doc", "burn rate", "stock days",
    "overstock", "surplus",
    "dead stock", "slow-moving", "stagnant",
    "velocity", "offtake", "capital lock-up", "carry cost", "coverage ratio",
    "materiality", "z-score", "write-down provision",
})


def family(tokens: set[str]) -> str:
    """Label a measure or column name. Most specific match wins.

    Ordered rather than scored, and `policy`/`cover` are tested before
    `stock_value`, because a threshold measure named `EXCESS_THRESHOLD_DAYS`
    contains both "excess" and "days" and must not be mistaken for the value it
    governs.
    """
    for name in ("policy", "cover", "excess", "non_moving", "stockout",
                 "opportunity_loss", "pending_orders", "damage", "ageing",
                 "stock_units", "stock_value"):
        if tokens & FAMILY_TOKENS[name]:
            return name
    return DEFAULT_FAMILY


def direction_is_good(family_name: str, change: float | None) -> bool | None:
    """Is a movement in this family good news? None when it cannot be judged."""
    if change is None or change == 0:
        return None
    rising = change > 0
    return not rising if family_name in HIGHER_IS_WORSE else rising
