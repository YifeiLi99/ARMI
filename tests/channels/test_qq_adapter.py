from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid7

from armi_adapter_qq import (
    QQAdapterConfig,
    QQGroupEffectAdapter,
    QQGroupEgressAdapter,
    QQGroupIngressAdapter,
    load_qq_napcat_config,
)
from armi_channel_napcat import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatGroupMessageEvent,
    NapCatRejected,
)
from armi_kernel.application import (
    EffectAttemptId,
    EffectId,
    EffectViolation,
    EnsureExternalGroupCommand,
    EvidenceId,
    ExternalAccountKey,
    ExternalChannel,
    ExternalConversationKey,
    ExternalGroupInputAcceptance,
    ExternalGroupSendRequest,
    ExternalGroupView,
    ExternalMessageKey,
    ExternalPartyKey,
    FrozenEffectRequest,
    ObservedExternalGroupMessage,
    OpportunityId,
    OtherHumanInteractionId,
    SceneKey,
)
from armi_kernel.contracts import Digest, TraceId


class _InputPort:
    def __init__(self) -> None:
        self.ensured: list[EnsureExternalGroupCommand] = []
        self.accepted: list[ObservedExternalGroupMessage] = []

    async def ensure_group(
        self, command: EnsureExternalGroupCommand
    ) -> ExternalGroupView:
        self.ensured.append(command)
        return ExternalGroupView(uuid7(), uuid7(), uuid7(), SceneKey("qq-group"))

    async def accept(
        self, command: ObservedExternalGroupMessage
    ) -> ExternalGroupInputAcceptance:
        self.accepted.append(command)
        return ExternalGroupInputAcceptance(
            uuid7(),
            uuid7(),
            uuid7(),
            OtherHumanInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"request"),
            Digest.from_bytes(command.message_bytes),
            True,
        )


class _Gateway:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, str]] = []

    async def send_group_text(
        self, *, group_id: int, text: str, echo: str
    ) -> NapCatActionResponse:
        self.sent.append((group_id, text, echo))
        return NapCatActionResponse("ok", 0, "991", echo)


class _FailingGateway:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def send_group_text(
        self, *, group_id: int, text: str, echo: str
    ) -> NapCatActionResponse:
        del group_id, text, echo
        raise self.error


class QQAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingress_maps_only_allowlisted_group(self) -> None:
        port = _InputPort()
        adapter = QQGroupIngressAdapter(
            config=QQAdapterConfig(10001, {20002: "朋友群"}), input_port=port
        )
        event = NapCatGroupMessageEvent(
            1_800_000_000,
            10001,
            "345",
            20002,
            30003,
            "小明",
            (("at", {"qq": "10001"}), ("text", {"text": " 你好"})),
        )
        accepted = await adapter.accept_event(event)
        self.assertIsNotNone(accepted)
        self.assertEqual(len(port.ensured), 1)
        self.assertEqual(len(port.accepted), 1)
        command = port.accepted[0]
        self.assertEqual(command.channel, ExternalChannel("qq"))
        self.assertEqual(command.account_key, ExternalAccountKey("10001"))
        self.assertEqual(command.conversation_key, ExternalConversationKey("20002"))
        self.assertEqual(command.sender_key, ExternalPartyKey("30003"))
        self.assertEqual(command.message_key, ExternalMessageKey("345"))
        self.assertTrue(command.addressed_to_subject)

    async def test_ingress_ignores_unlisted_and_self_messages(self) -> None:
        port = _InputPort()
        adapter = QQGroupIngressAdapter(
            config=QQAdapterConfig(10001, {20002: "朋友群"}), input_port=port
        )
        unlisted = NapCatGroupMessageEvent(
            1_800_000_000, 10001, "1", 99999, 30003, "小明", (("text", {"text": "x"}),)
        )
        own = NapCatGroupMessageEvent(
            1_800_000_000, 10001, "2", 20002, 10001, "ARMI", (("text", {"text": "x"}),)
        )
        self.assertIsNone(await adapter.accept_event(unlisted))
        self.assertIsNone(await adapter.accept_event(own))
        self.assertEqual(port.accepted, [])

    async def test_egress_sends_text_with_stable_echo(self) -> None:
        gateway = _Gateway()
        adapter = QQGroupEgressAdapter(
            config=QQAdapterConfig(10001, {20002: "朋友群"}), gateway=gateway
        )
        content = "晚上好".encode()
        request = ExternalGroupSendRequest(
            uuid7(),
            uuid7(),
            ExternalChannel("qq"),
            ExternalAccountKey("10001"),
            ExternalConversationKey("20002"),
            content,
            Digest.from_bytes(content),
            TraceId(uuid7().hex),
        )
        receipt = await adapter.send(request)
        self.assertEqual(receipt.platform_message_ref, "991")
        self.assertEqual(gateway.sent[0][0:2], (20002, "晚上好"))
        self.assertEqual(
            gateway.sent[0][2], f"{request.effect_id}:{request.attempt_id}"
        )

    async def test_effect_adapter_preserves_platform_message_reference(self) -> None:
        gateway = _Gateway()
        egress = QQGroupEgressAdapter(
            config=QQAdapterConfig(10001, {20002: "朋友群"}), gateway=gateway
        )
        adapter = QQGroupEffectAdapter(egress)
        content = "晚上好".encode()
        request = FrozenEffectRequest(
            EffectId(uuid7()),
            EffectAttemptId(uuid7()),
            uuid7(),
            uuid7(),
            uuid7(),
            "external_group",
            "qq",
            "10001",
            "20002",
            Digest.from_bytes(content),
            len(content),
            Digest.from_bytes(b"request"),
            TraceId(uuid7().hex),
        )
        receipt = await adapter.dispatch(request, content)
        self.assertEqual(receipt.external_receiver_ref, "991")

    async def test_effect_adapter_keeps_ambiguous_send_unknown(self) -> None:
        content = "晚上好".encode()
        request = FrozenEffectRequest(
            EffectId(uuid7()),
            EffectAttemptId(uuid7()),
            uuid7(),
            uuid7(),
            uuid7(),
            "external_group",
            "qq",
            "10001",
            "20002",
            Digest.from_bytes(content),
            len(content),
            Digest.from_bytes(b"request"),
            TraceId(uuid7().hex),
        )
        ambiguous = QQGroupEffectAdapter(
            QQGroupEgressAdapter(
                config=QQAdapterConfig(10001, {20002: "朋友群"}),
                gateway=_FailingGateway(
                    NapCatAmbiguousDelivery("NAPCAT-DELIVERY-AMBIGUOUS")
                ),
            )
        )
        with self.assertRaisesRegex(EffectViolation, "EFFECT-RESULT-UNKNOWN"):
            await ambiguous.dispatch(request, content)

        rejected = QQGroupEffectAdapter(
            QQGroupEgressAdapter(
                config=QQAdapterConfig(10001, {20002: "朋友群"}),
                gateway=_FailingGateway(NapCatRejected("NAPCAT-DELIVERY-REJECTED")),
            )
        )
        with self.assertRaisesRegex(EffectViolation, "EFFECT-RECEIVER-NOT-DELIVERED"):
            await rejected.dispatch(request, content)


class QQConfigTests(unittest.TestCase):
    def test_absent_file_keeps_channel_disabled(self) -> None:
        with TemporaryDirectory() as root:
            self.assertIsNone(load_qq_napcat_config(Path(root) / "missing.toml"))

    def test_enabled_file_owns_napcat_and_allowlist_settings(self) -> None:
        with TemporaryDirectory() as root:
            path = Path(root) / "qq-napcat.toml"
            path.write_text(
                """schema_version = "armi.qq-napcat-channel.v1"
enabled = true
account_id = 10001
api_base_url = "http://127.0.0.1:3000"
event_port = 6199
request_body_max_bytes = 262144

[allowed_groups]
"20002" = "朋友群"
""",
                encoding="utf-8",
                newline="\n",
            )
            binding = load_qq_napcat_config(path)
        self.assertIsNotNone(binding)
        assert binding is not None
        self.assertEqual(binding.adapter.account_id, 10001)
        self.assertEqual(binding.adapter.allowed_groups[20002], "朋友群")


if __name__ == "__main__":
    unittest.main()
