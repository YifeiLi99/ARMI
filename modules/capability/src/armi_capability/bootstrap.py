"""Read-only capability catalog composition."""

from collections.abc import Callable, Mapping

from ._postgresql import PostgreSQLCapabilityCatalog
from .api import CapabilityAvailability, CapabilityReadPort


def bootstrap_capability(
    availability: Callable[[], Mapping[str, CapabilityAvailability]],
) -> CapabilityReadPort:
    return PostgreSQLCapabilityCatalog(availability)


__all__ = ("bootstrap_capability",)
