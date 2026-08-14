"""The sales domain: today's Sales YoY report, plus the additions in WP9-WP11."""

from __future__ import annotations

from .. import Domain, register
from . import families
from . import spines as _spines  # noqa: F401  (registers PeriodOverPeriodSpine)

DOMAIN = Domain(
    name="sales",
    families=families,
    spines=("period_over_period",),
    blends=("impact_magnitude_unexpectedness",),
)

register("sales", DOMAIN)
