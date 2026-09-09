"""Explicit unavailable boundaries allow deterministic local file extraction."""

from collections.abc import Callable

from armi_interaction.api import (
    ExternalAccountKey,
    ExternalChannel,
    ExternalMessagePartKind,
    ExternalMessageViolation,
)
from armi_perception.api import (
    ExternalContentRecognitionRequest,
    ExternalContentRecognitionResult,
    ExternalContentRecognitionStatus,
    ExternalMediaContent,
)


class UnavailableMediaFetch:
    async def fetch(
        self,
        *,
        channel: ExternalChannel,
        account_key: ExternalAccountKey,
        kind: ExternalMessagePartKind,
        locator: str,
        max_bytes: int,
    ) -> ExternalMediaContent:
        raise ExternalMessageViolation("EXTERNAL-MESSAGE-CHANNEL-UNAVAILABLE")


class UnavailableMediaRecognizer:
    def __init__(
        self, target_for: Callable[[ExternalMessagePartKind], tuple[str, str]]
    ) -> None:
        self.target_for = target_for

    async def recognize(
        self, request: ExternalContentRecognitionRequest
    ) -> ExternalContentRecognitionResult:
        provider, model_id = self.target_for(request.kind)
        return ExternalContentRecognitionResult(
            ExternalContentRecognitionStatus.FAILED,
            None,
            provider,
            model_id,
            None,
            None,
            None,
            None,
            None,
            "EXTERNAL-MESSAGE-CREDENTIAL-UNAVAILABLE",
        )


__all__ = ("UnavailableMediaFetch", "UnavailableMediaRecognizer")
