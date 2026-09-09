"""Read-only capability catalog composition."""

from collections.abc import Callable

from ._postgresql import PostgreSQLCapabilityCatalog
from .api import CapabilityAvailability, CapabilityReadPort


def bootstrap_capability(
    availability: Callable[[], CapabilityAvailability],
) -> CapabilityReadPort:
    return PostgreSQLCapabilityCatalog(availability)


__all__ = ("bootstrap_capability",)
