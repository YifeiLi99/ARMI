"""Technology-neutral contracts for observed external group conversations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, Instant, TraceId

from .creator_input import EvidenceId, OpportunityId
from .other_human_input import OtherHumanInteractionId
from .scenes import SceneKey

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)
_EXTERNAL_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", re.ASCII)
_MESSAGE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,191}$", re.ASCII)
_MAX_MESSAGE_BYTES = 256 * 1024


class ExternalGroupViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or re.fullmatch(
                r"(?:CON-EXTERNAL-GROUP|EXTERNAL-GROUP|SCOPE|ART|DB)-[A-Z0-9-]+",
                code,
            )
            is None
        ):
            raise ValueError("external group violation code is invalid")
        self.code = code
        super().__init__("external group operation failed")

    def __str__(self) -> str:
        return f"{self.code}: external group operation failed"


@dataclass(frozen=True, slots=True)
class ExternalChannel:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _TOKEN.fullmatch(self.value) is None:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-CHANNEL")


@dataclass(frozen=True, slots=True)
class ExternalAccountKey:
    value: str

    def __post_init__(self) -> None:
        _external_key(self.value, "CON-EXTERNAL-GROUP-ACCOUNT")


@dataclass(frozen=True, slots=True)
class ExternalConversationKey:
    value: str

    def __post_init__(self) -> None:
        _external_key(self.value, "CON-EXTERNAL-GROUP-CONVERSATION")


@dataclass(frozen=True, slots=True)
class ExternalPartyKey:
    value: str

    def __post_init__(self) -> None:
        _external_key(self.value, "CON-EXTERNAL-GROUP-PARTY")


@dataclass(frozen=True, slots=True)
class ExternalMessageKey:
    value: str

    def __post_init__(self) -> None:
        if type(self.value) is not str or _MESSAGE_KEY.fullmatch(self.value) is None:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-MESSAGE-KEY")


@dataclass(frozen=True, slots=True)
class EnsureExternalGroupCommand:
    channel: ExternalChannel
    account_key: ExternalAccountKey
    conversation_key: ExternalConversationKey
    display_label: str
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.channel) is not ExternalChannel
            or type(self.account_key) is not ExternalAccountKey
            or type(self.conversation_key) is not ExternalConversationKey
            or type(self.trace_id) is not TraceId
        ):
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-ENSURE")
        _display_label(self.display_label, "CON-EXTERNAL-GROUP-DISPLAY-LABEL")


@dataclass(frozen=True, slots=True)
class ExternalGroupView:
    binding_id: UUID
    group_party_id: UUID
    scene_id: UUID
    scene_key: SceneKey

    def __post_init__(self) -> None:
        for value in (self.binding_id, self.group_party_id, self.scene_id):
            _uuid7(value, "CON-EXTERNAL-GROUP-VIEW")
        if type(self.scene_key) is not SceneKey:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-VIEW")


@dataclass(frozen=True, slots=True)
class ObservedExternalGroupMessage:
    channel: ExternalChannel
    account_key: ExternalAccountKey
    conversation_key: ExternalConversationKey
    message_key: ExternalMessageKey
    sender_key: ExternalPartyKey
    sender_display_label: str
    message: str
    observed_at: Instant
    trace_id: TraceId
    addressed_to_subject: bool = False

    def __post_init__(self) -> None:
        if (
            type(self.channel) is not ExternalChannel
            or type(self.account_key) is not ExternalAccountKey
            or type(self.conversation_key) is not ExternalConversationKey
            or type(self.message_key) is not ExternalMessageKey
            or type(self.sender_key) is not ExternalPartyKey
            or type(self.observed_at) is not Instant
            or type(self.trace_id) is not TraceId
            or type(self.addressed_to_subject) is not bool
        ):
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-INPUT")
        _display_label(
            self.sender_display_label,
            "CON-EXTERNAL-GROUP-SENDER-DISPLAY-LABEL",
        )
        if type(self.message) is not str or "\x00" in self.message:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-INPUT")
        try:
            encoded = self.message.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-UNICODE") from None
        if not encoded or len(encoded) > _MAX_MESSAGE_BYTES or not self.message.strip():
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-INPUT")

    @property
    def message_bytes(self) -> bytes:
        return self.message.encode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class ExternalGroupInputAcceptance:
    binding_id: UUID
    sender_party_id: UUID
    scene_id: UUID
    interaction_id: OtherHumanInteractionId
    evidence_id: EvidenceId
    opportunity_id: OpportunityId
    request_digest: Digest
    content_digest: Digest
    newly_accepted: bool

    def __post_init__(self) -> None:
        for value in (self.binding_id, self.sender_party_id, self.scene_id):
            _uuid7(value, "CON-EXTERNAL-GROUP-ACCEPTANCE")
        if (
            type(self.interaction_id) is not OtherHumanInteractionId
            or type(self.evidence_id) is not EvidenceId
            or type(self.opportunity_id) is not OpportunityId
            or type(self.request_digest) is not Digest
            or type(self.content_digest) is not Digest
            or type(self.newly_accepted) is not bool
        ):
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-ACCEPTANCE")


@dataclass(frozen=True, slots=True)
class ExternalGroupSendRequest:
    effect_id: UUID
    attempt_id: UUID
    channel: ExternalChannel
    account_key: ExternalAccountKey
    conversation_key: ExternalConversationKey
    content: bytes
    content_digest: Digest
    trace_id: TraceId

    def __post_init__(self) -> None:
        _uuid7(self.effect_id, "CON-EXTERNAL-GROUP-SEND")
        _uuid7(self.attempt_id, "CON-EXTERNAL-GROUP-SEND")
        if (
            type(self.channel) is not ExternalChannel
            or type(self.account_key) is not ExternalAccountKey
            or type(self.conversation_key) is not ExternalConversationKey
            or type(self.content) is not bytes
            or not 1 <= len(self.content) <= 65536
            or b"\x00" in self.content
            or type(self.content_digest) is not Digest
            or Digest.from_bytes(self.content) != self.content_digest
            or type(self.trace_id) is not TraceId
        ):
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-SEND")
        try:
            text = self.content.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-UNICODE") from None
        if not text.strip():
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-SEND")


@dataclass(frozen=True, slots=True)
class ExternalGroupSendReceipt:
    platform_message_ref: str
    receipt_digest: Digest
    received_at: Instant

    def __post_init__(self) -> None:
        if (
            type(self.platform_message_ref) is not str
            or _EXTERNAL_KEY.fullmatch(self.platform_message_ref) is None
            or type(self.receipt_digest) is not Digest
            or type(self.received_at) is not Instant
        ):
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-RECEIPT")


@runtime_checkable
class ExternalGroupInputPort(Protocol):
    async def ensure_group(
        self, command: EnsureExternalGroupCommand
    ) -> ExternalGroupView: ...

    async def accept(
        self, command: ObservedExternalGroupMessage
    ) -> ExternalGroupInputAcceptance: ...


@runtime_checkable
class ExternalGroupSendPort(Protocol):
    async def send(
        self, request: ExternalGroupSendRequest
    ) -> ExternalGroupSendReceipt: ...

    async def observe(
        self, request: ExternalGroupSendRequest
    ) -> ExternalGroupSendReceipt | None: ...


def _external_key(value: object, code: str) -> None:
    if type(value) is not str or _EXTERNAL_KEY.fullmatch(value) is None:
        raise ExternalGroupViolation(code)


def _display_label(value: object, code: str) -> None:
    if (
        type(value) is not str
        or not value.strip()
        or "\x00" in value
        or len(value.encode("utf-8", errors="strict")) > 256
    ):
        raise ExternalGroupViolation(code)


def _uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise ExternalGroupViolation(code)


__all__ = (
    "EnsureExternalGroupCommand",
    "ExternalAccountKey",
    "ExternalChannel",
    "ExternalConversationKey",
    "ExternalGroupInputAcceptance",
    "ExternalGroupInputPort",
    "ExternalGroupSendPort",
    "ExternalGroupSendReceipt",
    "ExternalGroupSendRequest",
    "ExternalGroupView",
    "ExternalGroupViolation",
    "ExternalMessageKey",
    "ExternalPartyKey",
    "ObservedExternalGroupMessage",
)
