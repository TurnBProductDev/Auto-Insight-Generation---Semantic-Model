"""One package per business domain.

A domain supplies the vocabulary and the comparisons its reports need: measure
families, available spines, decompositions, default layouts and rule packs. The
kernel supplies everything that is the same regardless of domain.

The dependency runs one way - a domain may import from ``src.kernel``, never the
reverse. WP3 turns ``DOMAIN_REGISTRY`` into the lookup that ``build_graph``
assembles a report from; WP2 populates only what the spine work needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

def _empty_mapping() -> Mapping[str, Any]:
    """Return an immutable empty mapping suitable for dataclass defaults."""
    return MappingProxyType({})


@dataclass(frozen=True)
class Domain:
    """What a business domain supplies to the reports built on it.

    Frozen for the same reason ``ReportSpec`` is: WP3 resolves this pre-fork and
    both concurrent branches read it, so it must have no writer.
    """

    name: str
    #: Measure family vocabulary module (``families.py``).
    families: Any = None
    #: Spine kinds this domain's reports may declare.
    spines: tuple[str, ...] = ()
    #: Ranking blends its reports default to.
    blends: tuple[str, ...] = ()
    #: Decomposition helpers (three-lever, volume/rate) - WP4+.
    decompositions: Mapping[str, Any] = field(default_factory=_empty_mapping)
    #: Default layout name per report kind - WP5+.
    layouts: Mapping[str, str] = field(default_factory=_empty_mapping)
    #: Default rule packs - WP5+.
    rules: tuple[str, ...] = ()
    #: Default thresholds, overridable per report.
    thresholds: Mapping[str, Any] = field(default_factory=_empty_mapping)

    def supports_spine(self, kind: str) -> bool:
        return kind in self.spines


DOMAIN_REGISTRY: dict[str, object] = {}


def register(name: str, domain: object) -> object:
    existing = DOMAIN_REGISTRY.get(name)
    if existing is not None and existing is not domain:
        raise ValueError(f"domain {name!r} is already registered")
    DOMAIN_REGISTRY[name] = domain
    return domain


def get(name: str) -> object:
    try:
        return DOMAIN_REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown domain {name!r}; registered: "
            f"{', '.join(sorted(DOMAIN_REGISTRY)) or '(none)'}") from None


def available() -> tuple[str, ...]:
    return tuple(sorted(DOMAIN_REGISTRY))
