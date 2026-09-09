"""Creator system and perception use cases, independent of HTTP and MCP."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from armi_live_vision.api import LiveVisionViolation

from .creator_contract import (
    LiveVisionObservationResponse,
    LiveVisionStatusResponse,
    LiveVoiceStatusResponse,
    QQChannelHealthResponse,
    Readiness,
    RuntimeStatusResponse,
)


class CreatorSystemViolation(ValueError):
    def __init__(self, code: str, status_code: int = 503) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(code)

    @classmethod
    def from_vision(cls, error: LiveVisionViolation) -> CreatorSystemViolation:
        if error.code == "VISION-SOURCE-KIND":
            return cls("INPUT_VISION_SOURCE_KIND", 400)
        if error.code == "VISION-IDEMPOTENCY-CONFLICT":
            return cls("IDEMPOTENCY_VISION_CONFLICT", 409)
        return cls("DEPENDENCY_" + error.code.replace("-", "_"), 503)


@dataclass(frozen=True, slots=True)
class CreatorSystem:
    readiness: Callable[[], Readiness]
    runtime_status: Callable[[], RuntimeStatusResponse]
    qq_health: Callable[[], Awaitable[QQChannelHealthResponse]]
    qq_control: Callable[[str], Awaitable[QQChannelHealthResponse]] | None
    voice_control: Callable[[str], Awaitable[LiveVoiceStatusResponse]] | None
    vision_control: (
        Callable[[str, str | None], Awaitable[LiveVisionStatusResponse]] | None
    )
    vision_observe: (
        Callable[[str, str], Awaitable[LiveVisionObservationResponse]] | None
    )
    vision_observation: (
        Callable[[UUID], Awaitable[LiveVisionObservationResponse | None]] | None
    )
    vision_preview: Callable[[str], bytes | None] | None

    async def channel(
        self, action: Literal["start", "stop", "status"]
    ) -> QQChannelHealthResponse:
        if action == "status":
            return await self.qq_health()
        if self.qq_control is None:
            raise CreatorSystemViolation("DEPENDENCY_QQ_CHANNEL_CONTROL_UNAVAILABLE")
        return await self.qq_control(action)

    async def voice(
        self, action: Literal["start", "stop", "status"]
    ) -> LiveVoiceStatusResponse:
        if self.voice_control is None:
            raise CreatorSystemViolation("DEPENDENCY_LIVE_VOICE_UNAVAILABLE")
        return await self.voice_control(action)

    async def vision(
        self, action: str, source_kind: str | None = None
    ) -> LiveVisionStatusResponse:
        if self.vision_control is None:
            raise CreatorSystemViolation("DEPENDENCY_LIVE_VISION_UNAVAILABLE")
        try:
            return await self.vision_control(action, source_kind)
        except LiveVisionViolation as error:
            raise CreatorSystemViolation.from_vision(error) from None

    async def observe(
        self, source_kind: str, idempotency_key: str
    ) -> LiveVisionObservationResponse:
        await self.vision("authorize_observe", source_kind)
        if self.vision_observe is None:
            raise CreatorSystemViolation("DEPENDENCY_LIVE_VISION_UNAVAILABLE")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", idempotency_key) is None:
            raise CreatorSystemViolation("INPUT_IDEMPOTENCY_KEY", 400)
        try:
            return await self.vision_observe(source_kind, idempotency_key)
        except LiveVisionViolation as error:
            raise CreatorSystemViolation.from_vision(error) from None
        except ValueError:
            raise CreatorSystemViolation("INPUT_VISION_REQUEST", 400) from None

    async def observation(self, observation_id: str) -> LiveVisionObservationResponse:
        await self.vision("authorize_observation")
        try:
            parsed = UUID(observation_id)
            if parsed.version != 7 or str(parsed) != observation_id:
                raise ValueError
        except ValueError:
            raise CreatorSystemViolation("INPUT_VISION_NOT_FOUND", 404) from None
        result = (
            None
            if self.vision_observation is None
            else await self.vision_observation(parsed)
        )
        if result is None:
            raise CreatorSystemViolation("INPUT_VISION_NOT_FOUND", 404)
        return result

    async def preview(self, source_kind: str) -> bytes:
        await self.vision("authorize_preview", source_kind)
        result = (
            None if self.vision_preview is None else self.vision_preview(source_kind)
        )
        if result is None:
            raise CreatorSystemViolation("INPUT_VISION_NOT_FOUND", 404)
        return result


__all__ = ("CreatorSystem", "CreatorSystemViolation")
