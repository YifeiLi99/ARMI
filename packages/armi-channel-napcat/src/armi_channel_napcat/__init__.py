"""Public OneBot boundary for a locally running NapCat instance."""

from .client import NapCatDownloadedFile, NapCatGateway, NapCatHttpClient
from .contracts import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatGroupMessageEvent,
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
    "NapCatPrivateMessageEvent",
    "NapCatRejected",
    "NapCatViolation",
    "parse_onebot_message",
)
