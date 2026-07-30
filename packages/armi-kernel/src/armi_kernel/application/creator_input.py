"""Technology-neutral contracts for durable Creator input acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, IdempotencyKey, TraceId

_CODE = re.compile(
    r"^(?:CON-INPUT|INPUT|IDEMPOTENCY|SCOPE|AUTHORITY|ART|DB)-[A-Z0-9-]+$",
    re.ASCII,
)
_MAX_MESSAGE_BYTES = 256 * 1024


class CreatorInputViolation(RuntimeError):
    """Expose a stable input-acceptance code without message or adapter detail."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("creator input violation code is invalid")
        self.code = code
        super().__init__("creator input acceptance failed")

    def __str__(self) -> str:
        return f"{self.code}: creator input acceptance failed"


def _require_uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise CreatorInputViolation(code)


@dataclass(frozen=True, slots=True)
class CreatorInteractionId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-INPUT-INTERACTION-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class EvidenceId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-INPUT-EVIDENCE-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class OpportunityId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-INPUT-OPPORTUNITY-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CreatorInputCommand:
    scene_key: str
    message: str
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.scene_key) is not str
            or re.fullmatch(
                r"[a-z0-9][a-z0-9._-]{0,63}",
                self.scene_key,
                re.ASCII,
            )
            is None
        ):
            raise CreatorInputViolation("CON-INPUT-SCENE")
        if type(self.message) is not str or "\x00" in self.message:
            raise CreatorInputViolation("CON-INPUT-MESSAGE")
        try:
            encoded = self.message.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise CreatorInputViolation("CON-INPUT-UNICODE") from None
        if not encoded or len(encoded) > _MAX_MESSAGE_BYTES:
            raise CreatorInputViolation("CON-INPUT-SIZE")
        if not any(not character.isspace() for character in self.message):
            raise CreatorInputViolation("CON-INPUT-MESSAGE")
        if type(self.idempotency_key) is not IdempotencyKey:
            raise CreatorInputViolation("CON-INPUT-IDEMPOTENCY")
        if type(self.trace_id) is not TraceId:
            raise CreatorInputViolation("CON-INPUT-TRACE")

    @property
    def message_bytes(self) -> bytes:
        return self.message.encode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class CreatorInputAcceptance:
    interaction_id: CreatorInteractionId
    evidence_id: EvidenceId
    opportunity_id: OpportunityId
    request_digest: Digest
    content_digest: Digest
    newly_accepted: bool

    def __post_init__(self) -> None:
        if (
            type(self.interaction_id) is not CreatorInteractionId
            or type(self.evidence_id) is not EvidenceId
            or type(self.opportunity_id) is not OpportunityId
            or type(self.request_digest) is not Digest
            or type(self.content_digest) is not Digest
            or type(self.newly_accepted) is not bool
        ):
            raise CreatorInputViolation("CON-INPUT-ACCEPTANCE")


@runtime_checkable
class CreatorInputAcceptancePort(Protocol):
    async def accept(self, command: CreatorInputCommand) -> CreatorInputAcceptance:
        """Durably accept one Creator input through the authoritative owner."""
        ...


@runtime_checkable
class CreatorOperationQueryPort(Protocol):
    async def get(self, opportunity_id: OpportunityId) -> CreatorInputAcceptance:
        """Return an authorized accepted responsibility or reject its visibility."""
        ...


__all__ = (
    "CreatorInputAcceptance",
    "CreatorInputAcceptancePort",
    "CreatorInputCommand",
    "CreatorInputViolation",
    "CreatorInteractionId",
    "CreatorOperationQueryPort",
    "EvidenceId",
    "OpportunityId",
)
