"""Public OneBot boundary for a locally running NapCat instance."""

from .client import NapCatGateway, NapCatHttpClient
from .contracts import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatGroupMessageEvent,
    NapCatRejected,
    NapCatViolation,
    parse_onebot_message,
)

__all__ = (
    "NapCatActionResponse",
    "NapCatAmbiguousDelivery",
    "NapCatGateway",
    "NapCatGroupMessageEvent",
    "NapCatHttpClient",
    "NapCatRejected",
    "NapCatViolation",
    "parse_onebot_message",
)
