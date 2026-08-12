"""Select the configured external-content recognizer by trusted part kind."""

from __future__ import annotations

from armi_interaction.api import ExternalMessagePartKind

from .api import (
    ExternalContentRecognitionPort,
    ExternalContentRecognitionRequest,
    ExternalContentRecognitionResult,
)


class ExternalContentRecognizer:
    __slots__ = ("_ark", "_speech")

    def __init__(
        self,
        *,
        ark: ExternalContentRecognitionPort,
        speech: ExternalContentRecognitionPort,
    ) -> None:
        self._ark = ark
        self._speech = speech

    async def recognize(
        self, request: ExternalContentRecognitionRequest
    ) -> ExternalContentRecognitionResult:
        adapter = (
            self._speech if request.kind is ExternalMessagePartKind.AUDIO else self._ark
        )
        return await adapter.recognize(request)


__all__ = ("ExternalContentRecognizer",)
