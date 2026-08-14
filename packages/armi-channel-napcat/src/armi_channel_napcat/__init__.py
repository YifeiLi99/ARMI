"""Public OneBot boundary for a locally running NapCat instance."""

from .client import (
    NapCatDownloadedFile,
    NapCatGateway,
    NapCatHealthSnapshot,
    NapCatHealthState,
    NapCatHttpClient,
)
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
    "NapCatHealthSnapshot",
    "NapCatHealthState",
    "NapCatHttpClient",
    "NapCatMessageSegment",
    "NapCatPrivateMessageEvent",
    "NapCatRejected",
    "NapCatViolation",
    "parse_onebot_message",
)
