"""Map QQ events and sends without leaking OneBot into the ARMI Kernel."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast
from uuid import uuid7

from armi_channel_napcat import (
    NapCatAmbiguousDelivery,
    NapCatGateway,
    NapCatGroupMessageEvent,
    NapCatPrivateMessageEvent,
    NapCatRejected,
    NapCatViolation,
)
from armi_kernel.application import (
    ActionAdapterPort,
    EffectAdapterReceipt,
    EffectDeliveryId,
    EffectViolation,
    ExternalAccountKey,
    ExternalChannel,
    ExternalConversationKey,
    ExternalConversationKind,
    ExternalMediaContent,
    ExternalMediaFetchPort,
    ExternalMessageInputAcceptance,
    ExternalMessageInputPort,
    ExternalMessageKey,
    ExternalMessageOutputPart,
    ExternalMessageOutputPartKind,
    ExternalMessagePart,
    ExternalMessagePartKind,
    ExternalMessageSendReceipt,
    ExternalMessageSendRequest,
    ExternalMessageViolation,
    ExternalPartyKey,
    FrozenEffectRequest,
    ObservedExternalMessage,
)
from armi_kernel.contracts import Digest, Instant, TraceId


@dataclass(frozen=True, slots=True)
class QQAdapterConfig:
    account_id: int
    creator_user_id: int
    allowed_groups: Mapping[int, str]
    reply_to_other_private_users: bool
    reply_in_groups: bool
    reply_private_user_allowlist: frozenset[int]
    reply_group_allowlist: frozenset[int]

    def __post_init__(self) -> None:
        if (
            type(self.account_id) is not int
            or self.account_id <= 0
            or type(self.creator_user_id) is not int
            or self.creator_user_id <= 0
            or self.creator_user_id == self.account_id
        ):
            raise ValueError("QQ account identities are invalid")
        groups = dict(self.allowed_groups)
        if not groups:
            raise ValueError("at least one QQ group must be explicitly allowed")
        for group_id, label in groups.items():
            try:
                label_bytes = label.encode("utf-8") if type(label) is str else b""
            except UnicodeEncodeError:
                label_bytes = b""
            if (
                type(group_id) is not int
                or group_id <= 0
                or type(label) is not str
                or not label.strip()
                or "\x00" in label
                or not label_bytes
                or len(label_bytes) > 256
            ):
                raise ValueError("QQ allowed group is invalid")
        object.__setattr__(self, "allowed_groups", MappingProxyType(groups))
        if (
            type(self.reply_to_other_private_users) is not bool
            or type(self.reply_in_groups) is not bool
            or type(self.reply_private_user_allowlist) is not frozenset
            or type(self.reply_group_allowlist) is not frozenset
            or any(
                type(user_id) is not int or user_id <= 0
                for user_id in self.reply_private_user_allowlist
            )
            or any(
                type(group_id) is not int or group_id <= 0
                for group_id in self.reply_group_allowlist
            )
            or not self.reply_group_allowlist.issubset(groups)
        ):
            raise ValueError("QQ reply policy is invalid")


class QQIngressAdapter:
    __slots__ = ("_config", "_gateway", "_input")

    def __init__(
        self,
        *,
        config: QQAdapterConfig,
        input_port: ExternalMessageInputPort,
        gateway: NapCatGateway,
    ) -> None:
        self._config = config
        self._input = input_port
        self._gateway = gateway

    async def accept_event(
        self, event: NapCatGroupMessageEvent | NapCatPrivateMessageEvent
    ) -> ExternalMessageInputAcceptance | None:
        if event.self_id != self._config.account_id or event.user_id == event.self_id:
            return None
        parts = _message_parts(event.segments)
        if not parts:
            return None
        try:
            observed_at = Instant(datetime.fromtimestamp(event.time, UTC))
        except OSError, OverflowError, ValueError:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-INPUT") from None
        if isinstance(event, NapCatGroupMessageEvent):
            group_label = self._config.allowed_groups.get(event.group_id)
            if group_label is None:
                return None
            if (
                not self._config.reply_in_groups
                and event.group_id not in self._config.reply_group_allowlist
            ):
                return None
            kind = ExternalConversationKind.GROUP
            conversation_key = str(event.group_id)
            conversation_label = group_label
            addressed = (
                event.self_id in event.mentioned_ids
                or await self._replies_to_self(event)
            )
        else:
            if (
                event.user_id != self._config.creator_user_id
                and not self._config.reply_to_other_private_users
                and event.user_id not in self._config.reply_private_user_allowlist
            ):
                return None
            kind = ExternalConversationKind.DIRECT
            conversation_key = str(event.user_id)
            conversation_label = event.sender_label
            addressed = True
        return await self._input.accept(
            ObservedExternalMessage(
                ExternalChannel("qq"),
                ExternalAccountKey(str(event.self_id)),
                kind,
                ExternalConversationKey(conversation_key),
                conversation_label,
                ExternalMessageKey(event.message_id),
                ExternalPartyKey(str(event.user_id)),
                event.sender_label,
                parts,
                observed_at,
                TraceId(uuid7().hex),
                addressed,
            )
        )

    async def _replies_to_self(self, event: NapCatGroupMessageEvent) -> bool:
        for kind, data in event.segments:
            if kind != "reply":
                continue
            message_id = data.get("id")
            if not message_id:
                continue
            try:
                sender = await self._gateway.get_message_sender(message_id=message_id)
            except NapCatViolation:
                continue
            if sender == event.self_id:
                return True
        return False


class QQEgressAdapter:
    __slots__ = ("_config", "_gateway")

    def __init__(self, *, config: QQAdapterConfig, gateway: NapCatGateway) -> None:
        self._config = config
        self._gateway = gateway

    async def send(
        self, request: ExternalMessageSendRequest
    ) -> ExternalMessageSendReceipt:
        receiver_id = self.validate_route(request)
        try:
            if (
                len(request.parts) != 1
                or request.parts[0].kind is not ExternalMessageOutputPartKind.TEXT
                or request.parts[0].text is None
            ):
                raise ExternalMessageViolation(
                    "EXTERNAL-MESSAGE-CAPABILITY-UNAVAILABLE"
                )
            text = request.parts[0].text
            echo = f"{request.effect_id}:{request.attempt_id}"
            if request.conversation_kind is ExternalConversationKind.GROUP:
                response = await self._gateway.send_group_text(
                    group_id=receiver_id, text=text, echo=echo
                )
            else:
                response = await self._gateway.send_private_text(
                    user_id=receiver_id, text=text, echo=echo
                )
        except NapCatRejected:
            raise ExternalMessageViolation(
                "EXTERNAL-MESSAGE-DELIVERY-REJECTED"
            ) from None
        except NapCatAmbiguousDelivery, NapCatViolation:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-RESULT-UNKNOWN") from None
        receipt_bytes = json.dumps(
            {
                "schema_version": "armi.external-message-receipt.v1",
                "channel": "qq",
                "account_key": request.account_key.value,
                "conversation_kind": request.conversation_kind.value,
                "conversation_key": request.conversation_key.value,
                "effect_id": str(request.effect_id),
                "attempt_id": str(request.attempt_id),
                "platform_message_ref": response.message_id,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ExternalMessageSendReceipt(
            cast(str, response.message_id),
            Digest.from_bytes(receipt_bytes),
            Instant(datetime.now(UTC)),
        )

    def validate_route(self, request: ExternalMessageSendRequest) -> int:
        if request.channel.value != "qq" or request.account_key.value != str(
            self._config.account_id
        ):
            raise ExternalMessageViolation("SCOPE-EXTERNAL-MESSAGE-NOT-ALLOWED")
        try:
            receiver_id = int(request.conversation_key.value)
        except ValueError:
            raise ExternalMessageViolation(
                "CON-EXTERNAL-MESSAGE-CONVERSATION"
            ) from None
        if (
            request.conversation_kind is ExternalConversationKind.GROUP
            and receiver_id not in self._config.allowed_groups
        ):
            raise ExternalMessageViolation("SCOPE-EXTERNAL-MESSAGE-NOT-ALLOWED")
        return receiver_id


class QQMediaFetchAdapter(ExternalMediaFetchPort):
    __slots__ = ("_config", "_gateway")

    def __init__(self, *, config: QQAdapterConfig, gateway: NapCatGateway) -> None:
        self._config = config
        self._gateway = gateway

    async def fetch(
        self,
        *,
        channel: ExternalChannel,
        account_key: ExternalAccountKey,
        kind: ExternalMessagePartKind,
        locator: str,
        max_bytes: int,
    ) -> ExternalMediaContent:
        if (
            channel.value != "qq"
            or account_key.value != str(self._config.account_id)
            or kind
            not in {
                ExternalMessagePartKind.IMAGE,
                ExternalMessagePartKind.AUDIO,
                ExternalMessagePartKind.VIDEO,
                ExternalMessagePartKind.FILE,
            }
        ):
            raise ExternalMessageViolation("SCOPE-EXTERNAL-MESSAGE-NOT-ALLOWED")
        try:
            downloaded = await self._gateway.fetch_media(
                locator=locator,
                kind=kind.value,
                max_bytes=max_bytes,
            )
        except NapCatViolation as error:
            code = (
                "EXTERNAL-MESSAGE-MEDIA-TOO-LARGE"
                if error.code == "NAPCAT-MEDIA-TOO-LARGE"
                else "EXTERNAL-MESSAGE-MEDIA-UNAVAILABLE"
            )
            raise ExternalMessageViolation(code) from None
        return ExternalMediaContent(
            downloaded.content,
            downloaded.file_name,
            downloaded.media_type,
        )


class QQEffectAdapter(ActionAdapterPort):
    __slots__ = ("_egress",)

    def __init__(self, egress: QQEgressAdapter) -> None:
        self._egress = egress

    async def dispatch(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> EffectAdapterReceipt:
        send_request = _send_request(request, payload)
        try:
            receipt = await self._egress.send(send_request)
        except ExternalMessageViolation as error:
            raise _effect_violation(error) from None
        return EffectAdapterReceipt(
            EffectDeliveryId(uuid7()),
            receipt.receipt_digest,
            receipt.received_at,
            external_receiver_ref=receipt.platform_message_ref,
        )

    async def observe(
        self, request: FrozenEffectRequest
    ) -> EffectAdapterReceipt | None:
        send_request = _send_request(request, b"observation")
        try:
            self._egress.validate_route(send_request)
        except ExternalMessageViolation as error:
            raise _effect_violation(error) from None
        raise EffectViolation("EFFECT-RESULT-UNKNOWN")


def _send_request(
    request: FrozenEffectRequest, payload: bytes
) -> ExternalMessageSendRequest:
    if (
        request.destination_kind not in {"external_group", "external_private"}
        or request.external_channel is None
        or request.external_account_key is None
        or request.external_conversation_key is None
    ):
        raise EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")
    kind = (
        ExternalConversationKind.GROUP
        if request.destination_kind == "external_group"
        else ExternalConversationKind.DIRECT
    )
    return ExternalMessageSendRequest(
        request.effect_id.value,
        request.attempt_id.value,
        ExternalChannel(request.external_channel),
        ExternalAccountKey(request.external_account_key),
        kind,
        ExternalConversationKey(request.external_conversation_key),
        (
            ExternalMessageOutputPart(
                ExternalMessageOutputPartKind.TEXT,
                text=payload.decode("utf-8", errors="strict"),
            ),
        ),
        request.trace_id,
    )


def _effect_violation(error: ExternalMessageViolation) -> EffectViolation:
    if error.code in {
        "EXTERNAL-MESSAGE-DELIVERY-REJECTED",
        "SCOPE-EXTERNAL-MESSAGE-NOT-ALLOWED",
    }:
        return EffectViolation("EFFECT-RECEIVER-NOT-DELIVERED")
    if error.code == "EXTERNAL-MESSAGE-RESULT-UNKNOWN":
        return EffectViolation("EFFECT-RESULT-UNKNOWN")
    return EffectViolation("EFFECT-ADAPTER-UNAVAILABLE")


def _message_parts(
    segments: tuple[tuple[str, dict[str, str]], ...],
) -> tuple[ExternalMessagePart, ...]:
    parts: list[ExternalMessagePart] = []
    for kind, data in segments:
        if kind == "text":
            text = data.get("text", "")
            if text:
                parts.append(
                    ExternalMessagePart(ExternalMessagePartKind.TEXT, text=text)
                )
        elif kind == "at":
            target = data.get("qq")
            if target:
                parts.append(
                    ExternalMessagePart(
                        ExternalMessagePartKind.MENTION, target_key=target
                    )
                )
        elif kind == "reply":
            target = data.get("id")
            if target:
                parts.append(
                    ExternalMessagePart(
                        ExternalMessagePartKind.REPLY, target_key=target
                    )
                )
        elif kind == "face":
            label = data.get("raw") or data.get("id") or "未知"
            parts.append(ExternalMessagePart(ExternalMessagePartKind.FACE, text=label))
        elif kind in {"image", "mface", "record", "video", "file"}:
            locator = (
                data.get("file_id") or data.get("file") or data.get("url")
                if kind == "file"
                else data.get("file") or data.get("file_id") or data.get("url")
            )
            if not locator:
                parts.append(
                    ExternalMessagePart(
                        ExternalMessagePartKind.UNKNOWN,
                        text=_unknown_part_label(kind, data),
                    )
                )
                continue
            mapped_kind = {
                "image": ExternalMessagePartKind.IMAGE,
                "mface": ExternalMessagePartKind.IMAGE,
                "record": ExternalMessagePartKind.AUDIO,
                "video": ExternalMessagePartKind.VIDEO,
                "file": ExternalMessagePartKind.FILE,
            }[kind]
            raw_size = data.get("file_size")
            byte_size = int(raw_size) if raw_size and raw_size.isdecimal() else None
            parts.append(
                ExternalMessagePart(
                    mapped_kind,
                    locator=locator,
                    file_name=(
                        data.get("file_name")
                        or data.get("name")
                        or (data.get("file") if kind == "file" else None)
                    ),
                    media_type=data.get("mime_type"),
                    byte_size=byte_size,
                )
            )
        else:
            parts.append(
                ExternalMessagePart(
                    ExternalMessagePartKind.UNKNOWN,
                    text=_unknown_part_label(kind, data),
                )
            )
    return tuple(parts)


def _unknown_part_label(kind: str, data: dict[str, str]) -> str:
    details = [
        f"{key}={data[key]}"
        for key in ("summary", "name", "title", "label")
        if data.get(key)
    ]
    return kind if not details else f"{kind} ({', '.join(details)})"


__all__ = (
    "QQAdapterConfig",
    "QQEffectAdapter",
    "QQEgressAdapter",
    "QQIngressAdapter",
    "QQMediaFetchAdapter",
)
