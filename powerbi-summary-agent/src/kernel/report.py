"""What report is this run producing?

Until WP1 the answer was "the only one", and it was never written down: memory,
history and outputs were all keyed on ``dataset_id`` alone, so two reports over
one semantic model would silently share - and corrupt - each other's rotation
state.

``ReportSpec`` is that missing identity. WP1 fills in the identity fields only;
``spine``, ``kpis``, ``axes``, ``thresholds``, ``layout``, ``rules`` and
``knowledge`` are declared here so later work packages have a home to fill in
(WP2 the spine, WP3 the node sequence and layout, WP5+ the rule packs), and are
empty for now.

**Frozen on purpose.** WP3 resolves the spec pre-fork and then hands the same
object to both concurrent branches. The concurrency contract allows exactly one
writer per state key per superstep, so a mutable spec shared across the fork is
a race waiting to be written. Making it immutable now means that mistake cannot
be made later.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Mapping, Sequence

#: Today's single report and the chain it belongs to. These are the values a
#: config that predates WP1 resolves to, so its memory keeps its meaning after
#: the migration in ``scoping.py``.
DEFAULT_REPORT_ID = "sales_yoy"
DEFAULT_REPORT_NAME = "Sales vs Previous Year"
DEFAULT_DOMAIN = "sales"
DEFAULT_CHAIN_ID = "sales"
DEFAULT_CADENCE = "daily"

CADENCES = ("daily", "weekly", "monthly")

_EMPTY: Mapping[str, Any] = MappingProxyType({})


def _empty_mapping() -> Mapping[str, Any]:
    """Default factory for the immutable-mapping fields.

    These cannot be plain `= _EMPTY` defaults. Python 3.11's dataclasses reject
    any default whose class has `__hash__ = None`, and `mappingproxy` is one -
    "mutable default <class 'mappingproxy'> ... use default_factory". Python
    3.12 gave mappingproxy a real `__hash__`, so the same code imports fine
    there and fails only at runtime in the container, which runs 3.11.

    Returning the shared `_EMPTY` rather than a fresh dict keeps the field
    immutable, which is the point of a frozen spec being handed to two
    concurrent branches.
    """
    return _EMPTY


@dataclass(frozen=True)
class ReportSpec:
    """The identity of one report, plus the sections later WPs will fill in."""

    report_id: str = DEFAULT_REPORT_ID
    report_name: str = DEFAULT_REPORT_NAME
    domain: str = DEFAULT_DOMAIN
    chain_id: str = DEFAULT_CHAIN_ID
    dataset_id: str = ""
    cadence: str = DEFAULT_CADENCE

    # --- filled in by later work packages; empty today -----------------------
    spine: str | None = None                      # WP2
    kpis: tuple[str, ...] = ()                    # WP3
    axes: tuple[str, ...] = ()                    # WP3
    thresholds: Mapping[str, Any] = field(default_factory=_empty_mapping)        # WP3
    layout: str | None = None                     # WP3
    rules: tuple[str, ...] = ()                   # WP5+
    knowledge: Mapping[str, Any] = field(default_factory=_empty_mapping)         # WP5+

    def __post_init__(self) -> None:
        if not str(self.report_id or "").strip():
            raise ValueError("report_id cannot be empty")
        if not str(self.chain_id or "").strip():
            raise ValueError("chain_id cannot be empty")
        if self.cadence not in CADENCES:
            raise ValueError(
                f"cadence {self.cadence!r} is not one of {', '.join(CADENCES)}")

    def evolve(self, **changes: Any) -> "ReportSpec":
        """A modified copy. The original stays immutable, so a post-fork reader
        can never observe a half-applied change."""
        return replace(self, **changes)

    def summary(self) -> str:
        return (f"report={self.report_id} chain={self.chain_id} "
                f"domain={self.domain} cadence={self.cadence}")


@dataclass(frozen=True)
class ResolvedReport:
    """A spec bound to one model, resolved **pre-fork** and read-only after.

    The concurrency contract allows one writer per state key per superstep, and
    both branches read this object concurrently. Frozen means the mistake of
    mutating it mid-run cannot be made - which matters more here than anywhere
    else in the kernel, because a torn read would be silent.
    """

    spec: ReportSpec
    #: The node names this run executes. Empty means "the full default graph",
    #: which is what every pre-WP3 config resolves to.
    nodes: tuple[str, ...] = ()
    #: The domain package supplying vocabulary and defaults.
    domain: Any = None
    #: The resolved measurement spine instance.
    spine: Any = None
    #: Facts carried over from the metadata scan, for nodes that need them.
    profile: Mapping[str, Any] = field(default_factory=_empty_mapping)

    @property
    def report_id(self) -> str:
        return self.spec.report_id

    @property
    def chain_id(self) -> str:
        return self.spec.chain_id

    def summary(self) -> str:
        nodes = f"{len(self.nodes)} node(s)" if self.nodes else "default graph"
        spine = getattr(self.spine, "kind", None) or "unresolved"
        return f"{self.spec.summary()} spine={spine} {nodes}"


def resolve(spec: ReportSpec,
            profile: Mapping[str, Any] | None = None,
            metadata: Mapping[str, Any] | None = None,
            *,
            nodes: Sequence[str] = ()) -> ResolvedReport:
    """Bind a spec to a model. Pre-fork only.

    Resolution is deliberately forgiving about the *domain* and *spine* being
    absent - a domain package that has not been written yet (inventory, until
    WP4) must not stop a report from resolving its identity. It is strict about
    nothing else: an unknown node name is caught by ``graph.resolve_node_names``
    at build time, where the error can name the alternatives.
    """
    from .. import domains

    domain = None
    try:
        domain = domains.get(spec.domain)
    except KeyError:
        domain = None

    spine_obj = None
    if spec.spine:
        try:
            spine_obj = spine_registry_get(spec.spine)()
        except (KeyError, TypeError):
            spine_obj = None

    return ResolvedReport(
        spec=spec,
        nodes=tuple(nodes),
        domain=domain,
        spine=spine_obj,
        profile=MappingProxyType(dict(profile or {})),
    )


def spine_registry_get(kind: str):
    """Indirection so ``report`` does not import ``spine`` at module load."""
    from . import spine as kernel_spine

    return kernel_spine.get(kind)


def from_state(state: Mapping[str, Any]) -> ReportSpec:
    """Build the spec from graph state or a loaded config.

    A config written before WP1 names no report, and resolves to today's single
    report - which is what keeps every existing invocation working unchanged.
    """
    return ReportSpec(
        report_id=str(state.get("report_id") or DEFAULT_REPORT_ID),
        report_name=str(state.get("report_name") or DEFAULT_REPORT_NAME),
        domain=str(state.get("report_domain") or DEFAULT_DOMAIN),
        chain_id=str(state.get("chain_id") or DEFAULT_CHAIN_ID),
        dataset_id=str(state.get("dataset_id") or ""),
        cadence=str(state.get("report_cadence") or DEFAULT_CADENCE),
    )
