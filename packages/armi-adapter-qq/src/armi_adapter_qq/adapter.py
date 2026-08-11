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
    ExternalMessageInputAcceptance,
    ExternalMessageInputPort,
    ExternalMessageKey,
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


class QQIngressAdapter:
    __slots__ = ("_config", "_input")

    def __init__(
        self, *, config: QQAdapterConfig, input_port: ExternalMessageInputPort
    ) -> None:
        self._config = config
        self._input = input_port

    async def accept_event(
        self, event: NapCatGroupMessageEvent | NapCatPrivateMessageEvent
    ) -> ExternalMessageInputAcceptance | None:
        if event.self_id != self._config.account_id or event.user_id == event.self_id:
            return None
        message = event.render_text()
        if message is None:
            return None
        try:
            observed_at = Instant(datetime.fromtimestamp(event.time, UTC))
        except OSError, OverflowError, ValueError:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-INPUT") from None
        if isinstance(event, NapCatGroupMessageEvent):
            group_label = self._config.allowed_groups.get(event.group_id)
            if group_label is None:
                return None
            kind = ExternalConversationKind.GROUP
            conversation_key = str(event.group_id)
            conversation_label = group_label
            addressed = event.self_id in event.mentioned_ids
        else:
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
                message,
                observed_at,
                TraceId(uuid7().hex),
                addressed,
            )
        )


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
            text = request.content.decode("utf-8", errors="strict")
            echo = f"{request.effect_id}:{request.attempt_id}"
            if request.conversation_kind is ExternalConversationKind.GROUP:
                response = await self._gateway.send_group_text(
                    group_id=receiver_id, text=text, echo=echo
                )
            else:
                response = await self._gateway.send_private_text(
                    user_id=receiver_id, text=text, echo=echo
                )
        except UnicodeDecodeError:
            raise ExternalMessageViolation("CON-EXTERNAL-MESSAGE-UNICODE") from None
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
        payload,
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


__all__ = (
    "QQAdapterConfig",
    "QQEffectAdapter",
    "QQEgressAdapter",
    "QQIngressAdapter",
)
