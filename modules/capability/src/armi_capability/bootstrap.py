"""Read-only capability catalog composition."""

from collections.abc import Callable, Mapping

from ._catalog import CapabilityCatalog
from .api import CapabilityAvailability, CapabilityReadPort


def bootstrap_capability(
    availability: Callable[[], Mapping[str, CapabilityAvailability]],
) -> CapabilityReadPort:
    return CapabilityCatalog(availability)


__all__ = ("bootstrap_capability",)
