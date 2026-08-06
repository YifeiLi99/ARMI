"""Contracts for caller-declared local other-human input acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, IdempotencyKey, TraceId

from .creator_input import EvidenceId, OpportunityId
from .scenes import SceneKey, SceneStatus

_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", re.ASCII)
_MAX_MESSAGE_BYTES = 256 * 1024


class OtherHumanInputViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or re.fullmatch(
                r"(?:CON-OTHER-HUMAN|OTHER-HUMAN|IDEMPOTENCY|SCOPE|ART|DB)-[A-Z0-9-]+",
                code,
            )
            is None
        ):
            raise ValueError("other-human input violation code is invalid")
        self.code = code
        super().__init__("other-human input acceptance failed")

    def __str__(self) -> str:
        return f"{self.code}: other-human input acceptance failed"


def _uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise OtherHumanInputViolation(code)


@dataclass(frozen=True, slots=True)
class OtherHumanPartyKey:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _KEY.fullmatch(self.value) is None:
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-PARTY-KEY")


@dataclass(frozen=True, slots=True)
class OtherHumanPartyView:
    party_id: UUID
    party_key: OtherHumanPartyKey
    display_label: str
    identity_assurance: Literal["caller_declared"] = "caller_declared"

    def __post_init__(self) -> None:
        _uuid7(self.party_id, "CON-OTHER-HUMAN-PARTY-ID")
        if type(self.party_key) is not OtherHumanPartyKey:
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-PARTY")
        if (
            type(self.display_label) is not str
            or not self.display_label.strip()
            or len(self.display_label.encode("utf-8")) > 256
            or self.identity_assurance != "caller_declared"
        ):
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-PARTY")


@dataclass(frozen=True, slots=True)
class RegisterOtherHumanPartyCommand:
    party_key: OtherHumanPartyKey
    display_label: str
    declared_role: Literal["other_human"]
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.party_key) is not OtherHumanPartyKey
            or type(self.trace_id) is not TraceId
        ):
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-PARTY-COMMAND")
        if self.declared_role != "other_human":
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-ROLE")
        if (
            type(self.display_label) is not str
            or not self.display_label.strip()
            or len(self.display_label.encode("utf-8")) > 256
        ):
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-DISPLAY-LABEL")


@dataclass(frozen=True, slots=True)
class OtherHumanSceneView:
    scene_id: UUID
    party_id: UUID
    scene_key: SceneKey
    status: SceneStatus

    def __post_init__(self) -> None:
        _uuid7(self.scene_id, "CON-OTHER-HUMAN-SCENE-ID")
        _uuid7(self.party_id, "CON-OTHER-HUMAN-PARTY-ID")
        if type(self.scene_key) is not SceneKey or type(self.status) is not SceneStatus:
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-SCENE")


@dataclass(frozen=True, slots=True)
class OtherHumanSceneCommand:
    party_key: OtherHumanPartyKey
    scene_key: SceneKey
    target_status: SceneStatus
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.party_key) is not OtherHumanPartyKey
            or type(self.scene_key) is not SceneKey
            or type(self.target_status) is not SceneStatus
            or type(self.trace_id) is not TraceId
        ):
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-SCENE-COMMAND")


@dataclass(frozen=True, slots=True)
class OtherHumanInteractionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-OTHER-HUMAN-INTERACTION-ID")


@dataclass(frozen=True, slots=True)
class OtherHumanInputCommand:
    party_key: OtherHumanPartyKey
    scene_key: SceneKey
    message: str
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.party_key) is not OtherHumanPartyKey
            or type(self.scene_key) is not SceneKey
            or type(self.idempotency_key) is not IdempotencyKey
            or type(self.trace_id) is not TraceId
            or type(self.message) is not str
            or "\x00" in self.message
        ):
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-INPUT")
        try:
            encoded = self.message.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-UNICODE") from None
        if not encoded or len(encoded) > _MAX_MESSAGE_BYTES or not self.message.strip():
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-INPUT")

    @property
    def message_bytes(self) -> bytes:
        return self.message.encode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class OtherHumanInputAcceptance:
    party_id: UUID
    scene_id: UUID
    interaction_id: OtherHumanInteractionId
    evidence_id: EvidenceId
    opportunity_id: OpportunityId
    request_digest: Digest
    content_digest: Digest
    newly_accepted: bool

    def __post_init__(self) -> None:
        _uuid7(self.party_id, "CON-OTHER-HUMAN-PARTY-ID")
        _uuid7(self.scene_id, "CON-OTHER-HUMAN-SCENE-ID")
        if (
            type(self.interaction_id) is not OtherHumanInteractionId
            or type(self.evidence_id) is not EvidenceId
            or type(self.opportunity_id) is not OpportunityId
            or type(self.request_digest) is not Digest
            or type(self.content_digest) is not Digest
            or type(self.newly_accepted) is not bool
        ):
            raise OtherHumanInputViolation("CON-OTHER-HUMAN-ACCEPTANCE")


@runtime_checkable
class OtherHumanInputPort(Protocol):
    async def register_party(
        self, command: RegisterOtherHumanPartyCommand
    ) -> OtherHumanPartyView: ...
    async def set_scene(
        self, command: OtherHumanSceneCommand
    ) -> OtherHumanSceneView: ...
    async def accept(
        self, command: OtherHumanInputCommand
    ) -> OtherHumanInputAcceptance: ...


__all__ = (
    "OtherHumanInputAcceptance",
    "OtherHumanInputCommand",
    "OtherHumanInputPort",
    "OtherHumanInputViolation",
    "OtherHumanInteractionId",
    "OtherHumanPartyKey",
    "OtherHumanPartyView",
    "OtherHumanSceneCommand",
    "OtherHumanSceneView",
    "RegisterOtherHumanPartyCommand",
)
