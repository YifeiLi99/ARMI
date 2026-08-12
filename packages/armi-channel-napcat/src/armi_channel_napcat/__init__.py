"""Public OneBot boundary for a locally running NapCat instance."""

from .client import NapCatDownloadedFile, NapCatGateway, NapCatHttpClient
from .contracts import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatGroupMessageEvent,
    NapCatMessageSegment,
    NapCatPrivateMessageEvent,
    NapCatRejected,
    NapCatViolation,
    parse_onebot_message,
)

__all__ = (
    "NapCatActionResponse",
    "NapCatAmbiguousDelivery",
    "NapCatDownloadedFile",
    "NapCatGateway",
    "NapCatGroupMessageEvent",
    "NapCatHttpClient",
    "NapCatMessageSegment",
    "NapCatPrivateMessageEvent",
    "NapCatRejected",
    "NapCatViolation",
    "parse_onebot_message",
)
