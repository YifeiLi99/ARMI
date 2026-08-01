"""Technology-neutral Creator response and formal no-action contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest

_CODE = re.compile(r"^(?:CON|RESPONSE|ACTION|POLICY|SCOPE)-[A-Z0-9-]+$", re.ASCII)
_PROPOSAL = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


class FormalNoActionKind(StrEnum):
    DECLINE = "decline"
    NO_ACTION = "no_action"


class FormalNoActionReason(StrEnum):
    SUBJECTIVE_REFUSAL = "subjective_refusal"
    SUBJECTIVE_SILENCE = "subjective_silence"


class ResponseAdmissionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    NO_ACTION = "no_action"
    UNAUTHORIZED = "unauthorized"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ResponseViolation(RuntimeError):
    """Expose a stable response failure without response content."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("response violation code is invalid")
        self.code = code
        super().__init__("Creator response admission failed")

    def __str__(self) -> str:
        return f"{self.code}: Creator response admission failed"


@dataclass(frozen=True, slots=True)
class ActionIntentId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-RESPONSE-ACTION-ID")


@dataclass(frozen=True, slots=True)
class FormalNoActionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-RESPONSE-NO-ACTION-ID")


@dataclass(frozen=True, slots=True)
class CreatorResponseOperationId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-RESPONSE-OPERATION-ID")


@dataclass(frozen=True, slots=True)
class CreatorReplyDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    content_bytes: bytes
    content_digest: Digest
    capability_kind: str = "creator.scene.reply"
    operation: str = "send"
    audience_scope: str = "creator"
    data_scope: str = "creator_visible_response"
    purpose: str = "respond_to_creator"
    media_type: str = "text/plain"

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        for value in (self.subject_id, self.scene_id, self.creator_party_id):
            _uuid7(value, "CON-RESPONSE-REPLY")
        if (
            type(self.content_bytes) is not bytes
            or not 1 <= len(self.content_bytes) <= 65536
            or b"\x00" in self.content_bytes
            or type(self.content_digest) is not Digest
            or Digest.from_bytes(self.content_bytes) != self.content_digest
            or self.capability_kind != "creator.scene.reply"
            or self.operation != "send"
            or self.audience_scope != "creator"
            or self.data_scope != "creator_visible_response"
            or self.purpose != "respond_to_creator"
            or self.media_type != "text/plain"
        ):
            raise ResponseViolation("CON-RESPONSE-REPLY")
        try:
            text = self.content_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ResponseViolation("CON-RESPONSE-REPLY") from None
        if not text.strip():
            raise ResponseViolation("CON-RESPONSE-REPLY")


@dataclass(frozen=True, slots=True)
class FormalNoActionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    kind: FormalNoActionKind
    reason: FormalNoActionReason

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        expected = {
            FormalNoActionKind.DECLINE: FormalNoActionReason.SUBJECTIVE_REFUSAL,
            FormalNoActionKind.NO_ACTION: FormalNoActionReason.SUBJECTIVE_SILENCE,
        }
        if (
            type(self.kind) is not FormalNoActionKind
            or self.reason is not expected[self.kind]
        ):
            raise ResponseViolation("CON-RESPONSE-NO-ACTION")


type ResponseChoiceDraft = CreatorReplyDraft | FormalNoActionDraft


@dataclass(frozen=True, slots=True)
class ResponseAdmissionResult:
    operation_id: CreatorResponseOperationId
    status: ResponseAdmissionStatus
    completion_digest: Digest
    action_intent_id: ActionIntentId | None = None
    no_action_id: FormalNoActionId | None = None
    grant_ref: UUID | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.operation_id) is not CreatorResponseOperationId
            or type(self.status) is not ResponseAdmissionStatus
            or type(self.completion_digest) is not Digest
            or (
                self.grant_ref is not None
                and (type(self.grant_ref) is not UUID or self.grant_ref.version != 7)
            )
            or (
                self.reason_code is not None
                and _CODE.fullmatch(self.reason_code) is None
            )
        ):
            raise ResponseViolation("CON-RESPONSE-RESULT")
        if (self.status is ResponseAdmissionStatus.NO_ACTION) != (
            self.no_action_id is not None
        ):
            raise ResponseViolation("CON-RESPONSE-RESULT")
        if (
            self.status is ResponseAdmissionStatus.ACCEPTED
            and self.action_intent_id is None
        ):
            raise ResponseViolation("CON-RESPONSE-RESULT")


@runtime_checkable
class ResponseAdmissionPort(Protocol):
    async def admit_once(self) -> bool:
        """Claim and settle at most one durable response admission."""
        ...


def _proposal(proposal_ref: str, group_ref: str, basis: tuple[int, ...]) -> None:
    if (
        type(proposal_ref) is not str
        or _PROPOSAL.fullmatch(proposal_ref) is None
        or type(group_ref) is not str
        or _GROUP.fullmatch(group_ref) is None
        or type(basis) is not tuple
        or not 1 <= len(basis) <= 8
        or len(set(basis)) != len(basis)
        or any(type(value) is not int or not 1 <= value <= 999 for value in basis)
    ):
        raise ResponseViolation("CON-RESPONSE-PROPOSAL")


def _uuid7(value: UUID, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise ResponseViolation(code)


__all__ = (
    "ActionIntentId",
    "CreatorReplyDraft",
    "CreatorResponseOperationId",
    "FormalNoActionDraft",
    "FormalNoActionId",
    "FormalNoActionKind",
    "FormalNoActionReason",
    "ResponseAdmissionPort",
    "ResponseAdmissionResult",
    "ResponseAdmissionStatus",
    "ResponseChoiceDraft",
    "ResponseViolation",
)
