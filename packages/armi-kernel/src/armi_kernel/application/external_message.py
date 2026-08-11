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


class ExternalMessagePartKind(StrEnum):
    TEXT = "text"
    MENTION = "mention"
    REPLY = "reply"
    FACE = "face"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    UNKNOWN = "unknown"


class ExternalMessageOutputPartKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"


@dataclass(frozen=True, slots=True)
class ExternalMessagePart:
    kind: ExternalMessagePartKind
    text: str | None = None
    target_key: str | None = None
    locator: str | None = None
    file_name: str | None = None
    media_type: str | None = None
    byte_size: int | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not ExternalMessagePartKind:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        for value in (
            self.text,
            self.target_key,
            self.locator,
            self.file_name,
            self.media_type,
        ):
            if value is not None and (type(value) is not str or "\x00" in value):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        if self.byte_size is not None and (
            type(self.byte_size) is not int
            or self.byte_size < 0
            or self.byte_size > 9_223_372_036_854_775_807
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        if self.kind is ExternalMessagePartKind.TEXT:
            if not self.text or any(
                value is not None
                for value in (
                    self.target_key,
                    self.locator,
                    self.file_name,
                    self.media_type,
                    self.byte_size,
                )
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        elif self.kind in {
            ExternalMessagePartKind.MENTION,
            ExternalMessagePartKind.REPLY,
        }:
            if not self.target_key or any(
                value is not None
                for value in (
                    self.text,
                    self.locator,
                    self.file_name,
                    self.media_type,
                    self.byte_size,
                )
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        elif self.kind in {
            ExternalMessagePartKind.IMAGE,
            ExternalMessagePartKind.AUDIO,
            ExternalMessagePartKind.VIDEO,
            ExternalMessagePartKind.FILE,
        }:
            if not self.locator or self.target_key is not None or self.text is not None:
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        elif self.kind in {
            ExternalMessagePartKind.FACE,
            ExternalMessagePartKind.UNKNOWN,
        } and (
            not self.text
            or any(
                value is not None
                for value in (
                    self.target_key,
                    self.locator,
                    self.file_name,
                    self.media_type,
                    self.byte_size,
                )
            )
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        if (
            self.text is not None
            and len(self.text.encode("utf-8", errors="strict")) > _MAX_MESSAGE_BYTES
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        if self.locator is not None and len(self.locator.encode("utf-8")) > 2048:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")
        if self.file_name is not None and len(self.file_name.encode("utf-8")) > 512:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-PART")

    @property
    def requires_recognition(self) -> bool:
        return self.kind in {
            ExternalMessagePartKind.IMAGE,
            ExternalMessagePartKind.AUDIO,
            ExternalMessagePartKind.VIDEO,
            ExternalMessagePartKind.FILE,
        }

    def render_placeholder(self) -> str:
        if self.kind is ExternalMessagePartKind.TEXT:
            return self.text or ""
        if self.kind is ExternalMessagePartKind.MENTION:
            return (
                "@全体成员" if self.target_key == "all" else f"@QQ({self.target_key})"
            )
        if self.kind is ExternalMessagePartKind.REPLY:
            return f"[回复消息 {self.target_key}]"
        if self.kind is ExternalMessagePartKind.FACE:
            return f"[QQ表情 {self.text}]"
        if self.kind is ExternalMessagePartKind.IMAGE:
            return "[图片]"
        if self.kind is ExternalMessagePartKind.AUDIO:
            return "[语音]"
        if self.kind is ExternalMessagePartKind.VIDEO:
            return "[视频]"
        if self.kind is ExternalMessagePartKind.FILE:
            return f"[文件: {self.file_name or '未命名'}]"
        return f"[不支持的消息类型: {self.text}]"


@dataclass(frozen=True, slots=True)
class ExternalMessageOutputPart:
    kind: ExternalMessageOutputPartKind
    text: str | None = None
    artifact_id: UUID | None = None
    file_name: str | None = None
    media_type: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not ExternalMessageOutputPartKind:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-SEND")
        if self.kind is ExternalMessageOutputPartKind.TEXT:
            if (
                type(self.text) is not str
                or not self.text.strip()
                or "\x00" in self.text
                or len(self.text.encode("utf-8", errors="strict")) > 65536
                or any(
                    value is not None
                    for value in (self.artifact_id, self.file_name, self.media_type)
                )
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-SEND")
        elif (
            self.text is not None
            or type(self.artifact_id) is not UUID
            or self.artifact_id.version != 7
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-SEND")


@dataclass(frozen=True, slots=True)
class ExternalMediaContent:
    content: bytes
    file_name: str
    media_type: str

    def __post_init__(self) -> None:
        if (
            type(self.content) is not bytes
            or not self.content
            or type(self.file_name) is not str
            or not self.file_name
            or "\x00" in self.file_name
            or type(self.media_type) is not str
            or not self.media_type
            or "\x00" in self.media_type
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-MEDIA")


@runtime_checkable
class ExternalMediaFetchPort(Protocol):
    async def fetch(
        self,
        *,
        channel: ExternalChannel,
        account_key: ExternalAccountKey,
        kind: ExternalMessagePartKind,
        locator: str,
        max_bytes: int,
    ) -> ExternalMediaContent: ...


class ExternalContentRecognitionStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ExternalContentRecognitionRequest:
    kind: ExternalMessagePartKind
    content: bytes
    file_name: str
    media_type: str
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            self.kind
            not in {
                ExternalMessagePartKind.IMAGE,
                ExternalMessagePartKind.AUDIO,
                ExternalMessagePartKind.VIDEO,
                ExternalMessagePartKind.FILE,
            }
            or type(self.content) is not bytes
            or not self.content
            or type(self.file_name) is not str
            or not self.file_name
            or "\x00" in self.file_name
            or type(self.media_type) is not str
            or not self.media_type
            or type(self.trace_id) is not TraceId
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")


@dataclass(frozen=True, slots=True)
class ExternalContentRecognitionResult:
    status: ExternalContentRecognitionStatus
    text: str | None
    provider: str
    model_id: str
    response_model_id: str | None
    provider_request_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    raw_response: bytes | None
    error_code: str | None

    def __post_init__(self) -> None:
        if (
            type(self.status) is not ExternalContentRecognitionStatus
            or type(self.provider) is not str
            or not self.provider
            or type(self.model_id) is not str
            or not self.model_id
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        if self.status is ExternalContentRecognitionStatus.SUCCEEDED:
            if (
                type(self.text) is not str
                or not self.text.strip()
                or type(self.raw_response) is not bytes
                or not self.raw_response
                or self.error_code is not None
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        elif self.text is not None or not self.error_code:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        for value in (
            self.response_model_id,
            self.provider_request_id,
            self.error_code,
        ):
            if value is not None and (
                type(value) is not str or not value or "\x00" in value
            ):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        for value in (self.input_tokens, self.output_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")
        if self.raw_response is not None and type(self.raw_response) is not bytes:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-RECOGNITION")


@runtime_checkable
class ExternalContentRecognitionPort(Protocol):
    async def recognize(
        self, request: ExternalContentRecognitionRequest
    ) -> ExternalContentRecognitionResult: ...


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
    parts: tuple[ExternalMessagePart, ...]
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
        if (
            type(self.parts) is not tuple
            or not 1 <= len(self.parts) <= 64
            or any(type(part) is not ExternalMessagePart for part in self.parts)
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-INPUT")
        encoded = self.message_bytes
        if not encoded or len(encoded) > _MAX_MESSAGE_BYTES:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-INPUT")
        if (
            self.conversation_kind is ExternalConversationKind.DIRECT
            and self.conversation_key.value != self.sender_key.value
        ):
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-DIRECT")

    @property
    def message_bytes(self) -> bytes:
        return "".join(part.render_placeholder() for part in self.parts).encode(
            "utf-8", errors="strict"
        )

    @property
    def has_media(self) -> bool:
        return any(part.requires_recognition for part in self.parts)


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
    evidence_id: EvidenceId | None
    opportunity_id: OpportunityId | None
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
            or (
                self.evidence_id is not None
                and type(self.evidence_id) is not EvidenceId
            )
            or (
                self.opportunity_id is not None
                and type(self.opportunity_id) is not OpportunityId
            )
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
    parts: tuple[ExternalMessageOutputPart, ...]
    trace_id: TraceId

    def __post_init__(self) -> None:
        _uuid7(self.effect_id, "CON-EXTERNAL-MESSAGE-SEND")
        _uuid7(self.attempt_id, "CON-EXTERNAL-MESSAGE-SEND")
        if (
            type(self.channel) is not ExternalChannel
            or type(self.account_key) is not ExternalAccountKey
            or type(self.conversation_kind) is not ExternalConversationKind
            or type(self.conversation_key) is not ExternalConversationKey
            or type(self.parts) is not tuple
            or not 1 <= len(self.parts) <= 16
            or any(type(part) is not ExternalMessageOutputPart for part in self.parts)
            or type(self.trace_id) is not TraceId
        ):
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
    "ExternalContentRecognitionPort",
    "ExternalContentRecognitionRequest",
    "ExternalContentRecognitionResult",
    "ExternalContentRecognitionStatus",
    "ExternalConversationKey",
    "ExternalConversationKind",
    "ExternalCreatorBinding",
    "ExternalMediaContent",
    "ExternalMediaFetchPort",
    "ExternalMessageInputAcceptance",
    "ExternalMessageInputPort",
    "ExternalMessageInteractionId",
    "ExternalMessageKey",
    "ExternalMessageOutputPart",
    "ExternalMessageOutputPartKind",
    "ExternalMessagePart",
    "ExternalMessagePartKind",
    "ExternalMessageSendPort",
    "ExternalMessageSendReceipt",
    "ExternalMessageSendRequest",
    "ExternalMessageViolation",
    "ExternalPartyKey",
    "ObservedExternalMessage",
)
