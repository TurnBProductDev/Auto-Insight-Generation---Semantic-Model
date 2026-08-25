"""A shared query budget and evidence ledger for single-snapshot inventory
investigations (Ageing, SKU Overview).

Not YoY's full evidence-contract system - that catalogs grouping, metric
bundle/phase/population, completeness and a DAX hash across a much larger,
multi-node evidence-reuse pipeline. This is the right-sized equivalent for a
smaller domain: one report, one investigation pass, a handful of deterministic
drill queries. What both share is the guarantee that actually matters - a
query budget that cannot be silently exceeded, and a visible, auditable
record of what was spent and on what, rather than a paragraph the reader has
to trust.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field


@dataclass
class Budget:
    total: int
    per_finding: int
    used: int = 0
    ledger: list[dict] = field(default_factory=list)

    def remaining(self) -> int:
        return max(0, self.total - self.used)

    def spent_on(self, finding_id: str) -> int:
        return sum(1 for entry in self.ledger if entry["finding_id"] == finding_id)

    def can_spend_on(self, finding_id: str, n: int = 1) -> bool:
        return self.remaining() >= n and (self.spent_on(finding_id) + n) <= self.per_finding

    def spend(self, *, finding_id: str, role: str, dax: str, rows_returned: int,
             round_no: int, outcome: str = "ok") -> None:
        self.used += 1
        self.ledger.append({
            "finding_id": finding_id, "role": role, "round": round_no,
            "rows_returned": rows_returned, "outcome": outcome,
            "dax_hash": hashlib.sha256(dax.encode("utf-8")).hexdigest()[:16],
        })

    def summary(self) -> dict:
        return {"total": self.total, "used": self.used, "remaining": self.remaining(),
               "per_finding_cap": self.per_finding, "queries": len(self.ledger),
               "ledger": list(self.ledger)}
