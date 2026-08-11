from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import uuid7

from armi_adapter_qq import (
    QQAdapterConfig,
    QQEffectAdapter,
    QQEgressAdapter,
    QQIngressAdapter,
    load_qq_napcat_config,
)
from armi_channel_napcat import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatGroupMessageEvent,
    NapCatPrivateMessageEvent,
    NapCatRejected,
)
from armi_kernel.application import (
    EffectAttemptId,
    EffectId,
    EffectViolation,
    EvidenceId,
    ExternalMessageInputAcceptance,
    ExternalMessageInteractionId,
    FrozenEffectRequest,
    ObservedExternalMessage,
    OpportunityId,
)
from armi_kernel.contracts import Digest, TraceId


class _InputPort:
    def __init__(self) -> None:
        self.accepted: list[ObservedExternalMessage] = []

    async def configure_creator(self, command):
        raise AssertionError(command)

    async def accept(self, command: ObservedExternalMessage):
        self.accepted.append(command)
        return ExternalMessageInputAcceptance(
            uuid7(),
            uuid7(),
            "other_human",
            uuid7(),
            ExternalMessageInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"request"),
            Digest.from_bytes(command.message_bytes),
            True,
        )


class _Gateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[str, int, str, str]] = []

    async def send_group_text(self, *, group_id: int, text: str, echo: str):
        return await self._send("group", group_id, text, echo)

    async def send_private_text(self, *, user_id: int, text: str, echo: str):
        return await self._send("private", user_id, text, echo)

    async def _send(self, kind: str, target: int, text: str, echo: str):
        if self.error is not None:
            raise self.error
        self.sent.append((kind, target, text, echo))
        return NapCatActionResponse("ok", 0, "991", echo)


def _config() -> QQAdapterConfig:
    return QQAdapterConfig(
        10001,
        90009,
        {20002: "朋友群"},
        True,
        True,
        frozenset(),
        frozenset(),
    )


class QQAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingress_maps_group_and_friend_private(self) -> None:
        port = _InputPort()
        adapter = QQIngressAdapter(config=_config(), input_port=port)
        group = NapCatGroupMessageEvent(
            1_800_000_000,
            10001,
            "345",
            20002,
            30003,
            "小明",
            (("at", {"qq": "10001"}), ("text", {"text": " 你好"})),
        )
        private = NapCatPrivateMessageEvent(
            1_800_000_001,
            10001,
            "346",
            90009,
            "主人",
            (("text", {"text": "晚上好"}),),
        )
        await adapter.accept_event(group)
        await adapter.accept_event(private)
        self.assertEqual(
            [item.conversation_kind.value for item in port.accepted],
            ["group", "direct"],
        )
        self.assertTrue(port.accepted[0].addressed_to_subject)
        self.assertEqual(port.accepted[1].conversation_key.value, "90009")

    async def test_ingress_ignores_unlisted_wrong_account_and_self(self) -> None:
        port = _InputPort()
        adapter = QQIngressAdapter(config=_config(), input_port=port)
        events = (
            NapCatGroupMessageEvent(
                1, 10001, "1", 99999, 3, "x", (("text", {"text": "x"}),)
            ),
            NapCatPrivateMessageEvent(
                1, 20000, "2", 3, "x", (("text", {"text": "x"}),)
            ),
            NapCatPrivateMessageEvent(
                1, 10001, "3", 10001, "ARMI", (("text", {"text": "x"}),)
            ),
        )
        for event in events:
            self.assertIsNone(await adapter.accept_event(event))
        self.assertEqual(port.accepted, [])

    async def test_reply_switches_require_allowlist_exceptions(self) -> None:
        port = _InputPort()
        config = QQAdapterConfig(
            10001,
            90009,
            {20002: "朋友群", 20003: "安静群"},
            False,
            False,
            frozenset({30003}),
            frozenset({20002}),
        )
        adapter = QQIngressAdapter(config=config, input_port=port)
        events = (
            NapCatPrivateMessageEvent(
                1, 10001, "1", 40004, "路人", (("text", {"text": "x"}),)
            ),
            NapCatGroupMessageEvent(
                1,
                10001,
                "2",
                20003,
                30003,
                "白名单好友",
                (("text", {"text": "x"}),),
            ),
            NapCatGroupMessageEvent(
                1, 10001, "3", 20002, 40004, "路人", (("text", {"text": "x"}),)
            ),
            NapCatPrivateMessageEvent(
                1, 10001, "4", 90009, "主人", (("text", {"text": "x"}),)
            ),
            NapCatPrivateMessageEvent(
                1,
                10001,
                "5",
                30003,
                "白名单好友",
                (("text", {"text": "x"}),),
            ),
            NapCatGroupMessageEvent(
                1,
                10001,
                "6",
                20002,
                30003,
                "白名单好友",
                (("text", {"text": "x"}),),
            ),
        )
        for event in events:
            await adapter.accept_event(event)
        self.assertEqual(
            [item.message_key.value for item in port.accepted],
            ["4", "5", "6"],
        )

    async def test_egress_routes_group_and_private(self) -> None:
        gateway = _Gateway()
        adapter = QQEffectAdapter(QQEgressAdapter(config=_config(), gateway=gateway))
        routes: tuple[
            tuple[Literal["external_group", "external_private"], str], ...
        ] = (
            ("external_group", "20002"),
            ("external_private", "30003"),
        )
        for destination, conversation in routes:
            content = destination.encode()
            request = FrozenEffectRequest(
                EffectId(uuid7()),
                EffectAttemptId(uuid7()),
                uuid7(),
                uuid7(),
                uuid7(),
                destination,
                "qq",
                "10001",
                conversation,
                Digest.from_bytes(content),
                len(content),
                TraceId(uuid7().hex),
            )
            receipt = await adapter.dispatch(request, content)
            self.assertEqual(receipt.external_receiver_ref, "991")
        self.assertEqual([item[0] for item in gateway.sent], ["group", "private"])

    async def test_send_failure_mapping_does_not_retry(self) -> None:
        content = b"hello"
        request = FrozenEffectRequest(
            EffectId(uuid7()),
            EffectAttemptId(uuid7()),
            uuid7(),
            uuid7(),
            uuid7(),
            "external_private",
            "qq",
            "10001",
            "30003",
            Digest.from_bytes(content),
            len(content),
            TraceId(uuid7().hex),
        )
        for error, code in (
            (
                NapCatAmbiguousDelivery("NAPCAT-DELIVERY-AMBIGUOUS"),
                "EFFECT-RESULT-UNKNOWN",
            ),
            (
                NapCatRejected("NAPCAT-DELIVERY-REJECTED"),
                "EFFECT-RECEIVER-NOT-DELIVERED",
            ),
        ):
            adapter = QQEffectAdapter(
                QQEgressAdapter(config=_config(), gateway=_Gateway(error))
            )
            with self.assertRaisesRegex(EffectViolation, code):
                await adapter.dispatch(request, content)


class QQConfigTests(unittest.TestCase):
    def test_absent_file_keeps_channel_disabled(self) -> None:
        with TemporaryDirectory() as root:
            self.assertIsNone(load_qq_napcat_config(Path(root) / "missing.toml"))

    def test_v3_loads_reply_policy(self) -> None:
        with TemporaryDirectory() as root:
            path = Path(root) / "qq-napcat.toml"
            path.write_text(
                """schema_version = "armi.qq-napcat-channel.v3"
enabled = true
account_id = 10001
creator_user_id = 90009
api_base_url = "http://127.0.0.1:3000"
event_port = 6199
request_body_max_bytes = 262144
reply_to_other_users = false
reply_in_groups = false
reply_user_allowlist = [30003]
reply_group_allowlist = [20002]

[allowed_groups]
"20002" = "朋友群"
""",
                encoding="utf-8",
                newline="\n",
            )
            binding = load_qq_napcat_config(path)
        assert binding is not None
        self.assertEqual(binding.adapter.creator_user_id, 90009)
        self.assertFalse(binding.adapter.reply_to_other_users)
        self.assertEqual(binding.adapter.reply_user_allowlist, frozenset({30003}))


if __name__ == "__main__":
    unittest.main()
