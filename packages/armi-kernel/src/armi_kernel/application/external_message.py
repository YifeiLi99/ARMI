"""Technology-neutral contracts for observed external conversations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, Instant, TraceId

from .creator_input import EvidenceId, OpportunityId

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_EXTERNAL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", re.ASCII)
_MAX_MESSAGE_BYTES = 256 * 1024


class ExternalMessageViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or re.fullmatch(
                r"(?:CON-EXTERNAL-MESSAGE|EXTERNAL-MESSAGE|SCOPE|ART|DB)-[A-Z0-9-]+",
                code,
            )
            is None
        ):
            raise ValueError("external message violation code is invalid")
        self.code = code
        super().__init__("external message operation failed")

    def __str__(self) -> str:
        return f"{self.code}: external message operation failed"


class ExternalConversationKind(StrEnum):
    DIRECT = "direct"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class ExternalChannel:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _TOKEN.fullmatch(self.value) is None:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-CHANNEL")


@dataclass(frozen=True, slots=True)
class ExternalAccountKey:
    value: str

    def __post_init__(self) -> None:
        _external_key(self.value, "CON-EXTERNAL-MESSAGE-ACCOUNT")


@dataclass(frozen=True, slots=True)
class ExternalConversationKey:
    value: str

    def __post_init__(self) -> None:
        _external_key(self.value, "CON-EXTERNAL-MESSAGE-CONVERSATION")


@dataclass(frozen=True, slots=True)
class ExternalPartyKey:
    value: str

    def __post_init__(self) -> None:
        _external_key(self.value, "CON-EXTERNAL-MESSAGE-PARTY")


@dataclass(frozen=True, slots=True)
class ExternalMessageKey:
    value: str

    def __post_init__(self) -> None:
        _external_key(self.value, "CON-EXTERNAL-MESSAGE-KEY")


@dataclass(frozen=True, slots=True)
class ConfigureExternalCreatorCommand:
    channel: ExternalChannel
    account_key: ExternalAccountKey
    creator_key: ExternalPartyKey
    display_label: str
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.channel) is not ExternalChannel
            or type(self.account_key) is not ExternalAccountKey
            or type(self.creator_key) is not ExternalPartyKey
            or type(self.trace_id) is not TraceId
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-CREATOR")
        _display_label(self.display_label)


@dataclass(frozen=True, slots=True)
class ExternalCreatorBinding:
    binding_id: UUID
    creator_party_id: UUID
    scene_id: UUID

    def __post_init__(self) -> None:
        for value in (self.binding_id, self.creator_party_id, self.scene_id):
            _uuid7(value, "CON-EXTERNAL-MESSAGE-CREATOR")


@dataclass(frozen=True, slots=True)
class ObservedExternalMessage:
    channel: ExternalChannel
    account_key: ExternalAccountKey
    conversation_kind: ExternalConversationKind
    conversation_key: ExternalConversationKey
    conversation_display_label: str
    message_key: ExternalMessageKey
    sender_key: ExternalPartyKey
    sender_display_label: str
    message: str
    observed_at: Instant
    trace_id: TraceId
    addressed_to_subject: bool

    def __post_init__(self) -> None:
        if (
            type(self.channel) is not ExternalChannel
            or type(self.account_key) is not ExternalAccountKey
            or type(self.conversation_kind) is not ExternalConversationKind
            or type(self.conversation_key) is not ExternalConversationKey
            or type(self.message_key) is not ExternalMessageKey
            or type(self.sender_key) is not ExternalPartyKey
            or type(self.observed_at) is not Instant
            or type(self.trace_id) is not TraceId
            or type(self.addressed_to_subject) is not bool
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-INPUT")
        _display_label(self.conversation_display_label)
        _display_label(self.sender_display_label)
        if type(self.message) is not str or "\x00" in self.message:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-INPUT")
        try:
            encoded = self.message.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-UNICODE") from None
        if not encoded or len(encoded) > _MAX_MESSAGE_BYTES or not self.message.strip():
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-INPUT")
        if (
            self.conversation_kind is ExternalConversationKind.DIRECT
            and self.conversation_key.value != self.sender_key.value
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-DIRECT")

    @property
    def message_bytes(self) -> bytes:
        return self.message.encode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class ExternalMessageInteractionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-EXTERNAL-MESSAGE-INTERACTION")


@dataclass(frozen=True, slots=True)
class ExternalMessageInputAcceptance:
    conversation_binding_id: UUID
    sender_party_id: UUID
    sender_party_kind: Literal["creator", "other_human"]
    scene_id: UUID
    interaction_id: ExternalMessageInteractionId
    evidence_id: EvidenceId
    opportunity_id: OpportunityId
    request_digest: Digest
    content_digest: Digest
    newly_accepted: bool

    def __post_init__(self) -> None:
        for value in (
            self.conversation_binding_id,
            self.sender_party_id,
            self.scene_id,
        ):
            _uuid7(value, "CON-EXTERNAL-MESSAGE-ACCEPTANCE")
        if (
            self.sender_party_kind not in {"creator", "other_human"}
            or type(self.interaction_id) is not ExternalMessageInteractionId
            or type(self.evidence_id) is not EvidenceId
            or type(self.opportunity_id) is not OpportunityId
            or type(self.request_digest) is not Digest
            or type(self.content_digest) is not Digest
            or type(self.newly_accepted) is not bool
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-ACCEPTANCE")


@dataclass(frozen=True, slots=True)
class ExternalMessageSendRequest:
    effect_id: UUID
    attempt_id: UUID
    channel: ExternalChannel
    account_key: ExternalAccountKey
    conversation_kind: ExternalConversationKind
    conversation_key: ExternalConversationKey
    content: bytes
    trace_id: TraceId

    def __post_init__(self) -> None:
        _uuid7(self.effect_id, "CON-EXTERNAL-MESSAGE-SEND")
        _uuid7(self.attempt_id, "CON-EXTERNAL-MESSAGE-SEND")
        if (
            type(self.channel) is not ExternalChannel
            or type(self.account_key) is not ExternalAccountKey
            or type(self.conversation_kind) is not ExternalConversationKind
            or type(self.conversation_key) is not ExternalConversationKey
            or type(self.content) is not bytes
            or not 1 <= len(self.content) <= 65536
            or b"\x00" in self.content
            or type(self.trace_id) is not TraceId
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-SEND")
        try:
            text = self.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-UNICODE") from None
        if not text.strip():
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-SEND")


@dataclass(frozen=True, slots=True)
class ExternalMessageSendReceipt:
    platform_message_ref: str
    receipt_digest: Digest
    received_at: Instant

    def __post_init__(self) -> None:
        if (
            type(self.platform_message_ref) is not str
            or not self.platform_message_ref.strip()
            or "\x00" in self.platform_message_ref
            or type(self.receipt_digest) is not Digest
            or type(self.received_at) is not Instant
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECEIPT")


@runtime_checkable
class ExternalMessageInputPort(Protocol):
    async def configure_creator(
        self, command: ConfigureExternalCreatorCommand
    ) -> ExternalCreatorBinding: ...

    async def accept(
        self, command: ObservedExternalMessage
    ) -> ExternalMessageInputAcceptance: ...


@runtime_checkable
class ExternalMessageSendPort(Protocol):
    async def send(
        self, request: ExternalMessageSendRequest
    ) -> ExternalMessageSendReceipt: ...


def _external_key(value: object, code: str) -> None:
    if type(value) is not str or _EXTERNAL_KEY.fullmatch(value) is None:
        raise ExternalMessageViolation(code)


def _display_label(value: object) -> None:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-DISPLAY-LABEL")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-DISPLAY-LABEL") from None
    if len(encoded) > 256:
        raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-DISPLAY-LABEL")


def _uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise ExternalMessageViolation(code)


__all__ = (
    "ConfigureExternalCreatorCommand",
    "ExternalAccountKey",
    "ExternalChannel",
    "ExternalConversationKey",
    "ExternalConversationKind",
    "ExternalCreatorBinding",
    "ExternalMessageInputAcceptance",
    "ExternalMessageInputPort",
    "ExternalMessageInteractionId",
    "ExternalMessageKey",
    "ExternalMessageSendPort",
    "ExternalMessageSendReceipt",
    "ExternalMessageSendRequest",
    "ExternalMessageViolation",
    "ExternalPartyKey",
    "ObservedExternalMessage",
)
