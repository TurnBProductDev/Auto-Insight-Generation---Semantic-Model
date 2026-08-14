"""The inventory domain: Stock Age Analysis and Inventory Management.

WP3 supplied the vocabulary and aggregation classes; WP4 adds
`SnapshotVsPolicySpine`. Per the revision in `docs/domain-verticals-findings.md`
§8, **snapshot-vs-policy is first** - neither live model holds a prior snapshot,
so a snapshot-vs-snapshot comparison has no baseline to work from.
"""

from __future__ import annotations

from .. import Domain, register
from . import families
from . import spines as _spines  # noqa: F401  (registers SnapshotVsPolicySpine)

DOMAIN = Domain(
    name="inventory",
    families=families,
    # WP4: snapshot-vs-policy only. Snapshot-vs-snapshot is deliberately absent
    # - neither live model holds a prior snapshot, so it would have no baseline.
    spines=("snapshot_vs_policy",),
    # Both reports rank without a signed change - see findings §8.
    blends=("severity_exposure_persistence", "tier_then_value"),
    thresholds={
        # Ageing BR-26: even small values in the oldest band are worth flagging,
        # because of the write-off implication.
        "high_risk_call_out_sar": 50_000,
        # Inventory BR-14/BR-20: too little trading history to judge excess.
        "excess_min_active_days": 30,
        # Inventory BR-19: uniform, never location-specific.
        "safety_days": 2,
    },
)

register("inventory", DOMAIN)
