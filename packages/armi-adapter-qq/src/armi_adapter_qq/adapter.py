"""Map QQ group events and sends without leaking OneBot into the ARMI Kernel."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from types import MappingProxyType
from uuid import uuid7

from armi_channel_napcat import (
    NapCatAmbiguousDelivery,
    NapCatGateway,
    NapCatGroupMessageEvent,
    NapCatRejected,
    NapCatViolation,
)
from armi_kernel.application import (
    EnsureExternalGroupCommand,
    ExternalAccountKey,
    ExternalChannel,
    ExternalConversationKey,
    ExternalGroupInputAcceptance,
    ExternalGroupInputPort,
    ExternalGroupSendPort,
    ExternalGroupSendReceipt,
    ExternalGroupSendRequest,
    ExternalGroupViolation,
    ExternalMessageKey,
    ExternalPartyKey,
    ObservedExternalGroupMessage,
)
from armi_kernel.contracts import Digest, Instant, TraceId


@dataclass(frozen=True, slots=True)
class QQAdapterConfig:
    account_id: int
    allowed_groups: Mapping[int, str]

    def __post_init__(self) -> None:
        if type(self.account_id) is not int or self.account_id <= 0:
            raise ValueError("QQ account_id must be a positive integer")
        groups = dict(self.allowed_groups)
        if not groups:
            raise ValueError("at least one QQ group must be explicitly allowed")
        for group_id, label in groups.items():
            if (
                type(group_id) is not int
                or group_id <= 0
                or type(label) is not str
                or not label.strip()
                or "\x00" in label
                or len(label.encode("utf-8")) > 256
            ):
                raise ValueError("QQ allowed group is invalid")
        object.__setattr__(self, "allowed_groups", MappingProxyType(groups))


class QQGroupIngressAdapter:
    __slots__ = ("_config", "_input")

    def __init__(
        self, *, config: QQAdapterConfig, input_port: ExternalGroupInputPort
    ) -> None:
        self._config = config
        self._input = input_port

    async def accept_event(
        self, event: NapCatGroupMessageEvent
    ) -> ExternalGroupInputAcceptance | None:
        if type(event) is not NapCatGroupMessageEvent:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-INPUT")
        if event.self_id != self._config.account_id or event.user_id == event.self_id:
            return None
        group_label = self._config.allowed_groups.get(event.group_id)
        if group_label is None:
            return None
        message = event.render_text()
        if message is None:
            return None
        trace_id = TraceId(uuid7().hex)
        channel = ExternalChannel("qq")
        account_key = ExternalAccountKey(str(event.self_id))
        conversation_key = ExternalConversationKey(str(event.group_id))
        await self._input.ensure_group(
            EnsureExternalGroupCommand(
                channel,
                account_key,
                conversation_key,
                group_label,
                trace_id,
            )
        )
        return await self._input.accept(
            ObservedExternalGroupMessage(
                channel,
                account_key,
                conversation_key,
                ExternalMessageKey(event.message_id),
                ExternalPartyKey(str(event.user_id)),
                event.sender_label,
                message,
                Instant(datetime.fromtimestamp(event.time, UTC)),
                trace_id,
                addressed_to_subject=event.self_id in event.mentioned_ids,
            )
        )


class QQGroupEgressAdapter(ExternalGroupSendPort):
    __slots__ = ("_config", "_gateway")

    def __init__(self, *, config: QQAdapterConfig, gateway: NapCatGateway) -> None:
        self._config = config
        self._gateway = gateway

    async def send(self, request: ExternalGroupSendRequest) -> ExternalGroupSendReceipt:
        group_id = self._validate_request(request)
        try:
            text = request.content.decode("utf-8", errors="strict")
            response = await self._gateway.send_group_text(
                group_id=group_id,
                text=text,
                echo=f"{request.effect_id}:{request.attempt_id}",
            )
        except UnicodeDecodeError:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-UNICODE") from None
        except NapCatRejected:
            raise ExternalGroupViolation("EXTERNAL-GROUP-DELIVERY-REJECTED") from None
        except NapCatAmbiguousDelivery:
            raise ExternalGroupViolation("EXTERNAL-GROUP-RESULT-UNKNOWN") from None
        except NapCatViolation:
            raise ExternalGroupViolation("EXTERNAL-GROUP-UNAVAILABLE") from None
        assert response.message_id is not None
        receipt_bytes = json.dumps(
            {
                "schema_version": "armi.external-group-receipt.v1",
                "channel": "qq",
                "account_key": request.account_key.value,
                "conversation_key": request.conversation_key.value,
                "effect_id": str(request.effect_id),
                "attempt_id": str(request.attempt_id),
                "platform_message_ref": response.message_id,
                "content_digest": request.content_digest.value,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ExternalGroupSendReceipt(
            response.message_id,
            Digest.from_bytes(receipt_bytes),
            Instant(datetime.now(UTC)),
        )

    async def observe(
        self, request: ExternalGroupSendRequest
    ) -> ExternalGroupSendReceipt | None:
        self._validate_request(request)
        raise ExternalGroupViolation("EXTERNAL-GROUP-RESULT-UNKNOWN")

    def _validate_request(self, request: ExternalGroupSendRequest) -> int:
        if type(request) is not ExternalGroupSendRequest:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-SEND")
        if request.channel.value != "qq" or request.account_key.value != str(
            self._config.account_id
        ):
            raise ExternalGroupViolation("SCOPE-EXTERNAL-GROUP-NOT-ALLOWED")
        try:
            group_id = int(request.conversation_key.value)
        except ValueError:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-CONVERSATION") from None
        if group_id not in self._config.allowed_groups:
            raise ExternalGroupViolation("SCOPE-EXTERNAL-GROUP-NOT-ALLOWED")
        return group_id


__all__ = ("QQAdapterConfig", "QQGroupEgressAdapter", "QQGroupIngressAdapter")
