"""Authenticated Creator calls and projection notifications without a transport."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from armi_kernel.application import CreatorProjectionInvalidation

from .interaction import InteractionResult


@dataclass(frozen=True, slots=True)
class CreatorActor:
    creator_party_id: UUID
    default_scene_key: str
    delegate_id: UUID | None


@dataclass(frozen=True, slots=True)
class CreatorCall:
    actor: CreatorActor
    input: Mapping[str, Any]
    parameters: tuple[tuple[str, str], ...] = ()
    idempotency_key: str | None = None


class CreatorEventSink(Protocol):
    async def notify(self, invalidation: CreatorProjectionInvalidation) -> None: ...


type CreatorUseCase = Callable[..., Awaitable[InteractionResult]]


def creator_result(
    *, content: Mapping[str, object] | None = None, status_code: int = 200
) -> InteractionResult:
    return InteractionResult(
        "unavailable"
        if status_code >= 500
        else "rejected"
        if status_code >= 400
        else "returned",
        {} if content is None else content,
        status_code,
    )


__all__ = (
    "CreatorActor",
    "CreatorCall",
    "CreatorEventSink",
    "CreatorUseCase",
    "creator_result",
)
