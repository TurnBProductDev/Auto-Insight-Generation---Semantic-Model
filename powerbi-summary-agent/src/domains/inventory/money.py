"""One money formatter for every inventory surface.

Four modules had grown their own copy of the same nine lines - `dashboard.py`,
`dashboard_html.py`, `charts.py` and `ageing_html.py` - each hard-coding `SAR`,
and `buckets.py` carried a threshold constant named after it. That is exactly
the two-copies-of-the-same-vocabulary drift the repository guide warns about:
changing the currency meant finding all five, and missing one produced a page
that quoted two different currencies without saying so.

Why the currency is a module setting rather than a threaded argument
--------------------------------------------------------------------
It reaches roughly forty call sites across the page model and the renderers, and
threading it through every one of them buys nothing here: a run produces one
report, for one client, in one currency. Reports in a chain run **sequentially
in one process** (the token cache does an unlocked read-modify-write, so they
must), and both inventory reports belong to the same client, so there is never a
moment when two currencies are live at once.

:func:`use` is therefore called once, by the runner, from `inventory_currency`.
The default is the value these reports shipped with, so every committed
artifact, replay and golden snapshot reproduces byte-for-byte until a config
says otherwise.
"""

from __future__ import annotations

import math
from typing import Any

#: The default is deliberately the value the committed artifacts carry. Changing
#: this constant would silently rewrite every recorded snapshot; change the
#: config key instead.
DEFAULT_CURRENCY = "SAR"

CURRENCY = DEFAULT_CURRENCY


def use(currency: str | None) -> str:
    """Set the currency for this run. Returns what was actually applied."""
    global CURRENCY
    CURRENCY = str(currency).strip() if currency and str(currency).strip() else DEFAULT_CURRENCY
    return CURRENCY


def reset() -> str:
    """Back to the shipped default. For tests, so one cannot leak into another."""
    return use(DEFAULT_CURRENCY)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def fmt(value: Any, currency: str | None = None, *, dash: str = "-") -> str:
    """A money figure, abbreviated the way the pages already abbreviate it.

    Returns ``dash`` for anything unmeasurable rather than printing zero: a
    missing figure and a figure of nothing are different answers, and only one
    of them means there is nothing there.
    """
    number = _num(value)
    if number is None:
        return dash
    unit = currency or CURRENCY
    if abs(number) >= 1_000_000:
        return f"{unit} {number / 1_000_000:.2f}M"
    if abs(number) >= 1_000:
        return f"{unit} {number / 1_000:.0f}K"
    return f"{unit} {number:,.0f}"
