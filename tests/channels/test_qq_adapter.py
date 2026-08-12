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
    NapCatDownloadedFile,
    NapCatGroupMessageEvent,
    NapCatMessageSegment,
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

    async def get_message_sender(self, *, message_id: str) -> int | None:
        return 10001 if message_id == "armi-message" else 30003

    async def fetch_media(self, *, locator: str, kind: str, max_bytes: int):
        return NapCatDownloadedFile(
            b"media", f"sample.{kind}", "application/octet-stream"
        )

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


def _segments(
    *values: tuple[str, dict[str, str]],
) -> tuple[NapCatMessageSegment, ...]:
    return tuple(NapCatMessageSegment(kind, data) for kind, data in values)


class QQAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingress_classifies_qq_visual_sources_and_magic_faces(self) -> None:
        port = _InputPort()
        adapter = QQIngressAdapter(
            config=_config(), input_port=port, gateway=_Gateway()
        )
        event = NapCatPrivateMessageEvent(
            1_800_000_000,
            10001,
            "visual-routes",
            90009,
            "主人",
            _segments(
                ("face", {"id": "14", "face_text": "/微笑"}),
                ("dice", {"result": "6"}),
                ("rps", {"result": "2"}),
                (
                    "image",
                    {
                        "file": "market.gif",
                        "summary": "开心企鹅",
                        "emoji_id": "e1",
                    },
                ),
                ("image", {"file": "custom.gif", "sub_type": "1"}),
                ("image", {"file": "normal.jpg", "sub_type": "0"}),
                ("image", {"file": "hot.jpg", "sub_type": "2"}),
                ("image", {"file": "unknown.jpg", "sub_type": "99"}),
            ),
        )
        await adapter.accept_event(event)
        parts = port.accepted[0].parts
        self.assertEqual([part.kind.value for part in parts[:3]], ["face"] * 3)
        self.assertEqual(parts[0].text, "/微笑")
        self.assertEqual(parts[1].text, "骰子结果 6")
        self.assertEqual(parts[2].text, "猜拳结果 2")
        visual_roles = []
        for part in parts[3:]:
            assert part.visual_role is not None
            visual_roles.append(part.visual_role.value)
        self.assertEqual(
            visual_roles,
            ["sticker", "sticker_candidate", "ordinary", "platform_special", "unknown"],
        )
        self.assertEqual(
            [part.source_kind for part in parts[3:]],
            [
                "qq.market_face",
                "qq.image.custom",
                "qq.image.normal",
                "qq.image.hot",
                "qq.image.unknown",
            ],
        )
        self.assertEqual(parts[3].source_summary, "开心企鹅")

    async def test_ingress_maps_group_and_friend_private(self) -> None:
        port = _InputPort()
        adapter = QQIngressAdapter(
            config=_config(), input_port=port, gateway=_Gateway()
        )
        group = NapCatGroupMessageEvent(
            1_800_000_000,
            10001,
            "345",
            20002,
            30003,
            "小明",
            _segments(("at", {"qq": "10001"}), ("text", {"text": " 你好"})),
        )
        private = NapCatPrivateMessageEvent(
            1_800_000_001,
            10001,
            "346",
            90009,
            "主人",
            _segments(("text", {"text": "晚上好"})),
        )
        await adapter.accept_event(group)
        await adapter.accept_event(private)
        self.assertEqual(
            [item.conversation_kind.value for item in port.accepted],
            ["group", "direct"],
        )
        self.assertTrue(port.accepted[0].addressed_to_subject)
        self.assertEqual(port.accepted[1].conversation_key.value, "90009")
        self.assertEqual(
            [part.kind.value for part in port.accepted[0].parts],
            ["mention", "text"],
        )

    async def test_ingress_ignores_unlisted_wrong_account_and_self(self) -> None:
        port = _InputPort()
        adapter = QQIngressAdapter(
            config=_config(), input_port=port, gateway=_Gateway()
        )
        events = (
            NapCatGroupMessageEvent(
                1, 10001, "1", 99999, 3, "x", _segments(("text", {"text": "x"}))
            ),
            NapCatPrivateMessageEvent(
                1, 20000, "2", 3, "x", _segments(("text", {"text": "x"}))
            ),
            NapCatPrivateMessageEvent(
                1, 10001, "3", 10001, "ARMI", _segments(("text", {"text": "x"}))
            ),
        )
        for event in events:
            self.assertIsNone(await adapter.accept_event(event))
        self.assertEqual(port.accepted, [])

    async def test_ingress_preserves_multimodal_order_and_resolves_reply_target(
        self,
    ) -> None:
        port = _InputPort()
        adapter = QQIngressAdapter(
            config=_config(), input_port=port, gateway=_Gateway()
        )
        event = NapCatGroupMessageEvent(
            1_800_000_000,
            10001,
            "media-1",
            20002,
            30003,
            "小明",
            _segments(
                ("reply", {"id": "armi-message"}),
                ("text", {"text": "看看"}),
                ("image", {"file": "image-locator", "file_size": "12"}),
                ("record", {"file": "audio-locator"}),
                ("video", {"file": "video-locator"}),
                ("file", {"file_id": "file-locator", "name": "report.pdf"}),
                ("poke", {"type": "1"}),
            ),
        )
        await adapter.accept_event(event)
        self.assertEqual(len(port.accepted), 1)
        accepted = port.accepted[0]
        self.assertTrue(accepted.addressed_to_subject)
        self.assertEqual(
            [part.kind.value for part in accepted.parts],
            ["reply", "text", "image", "audio", "video", "file", "face"],
        )
        self.assertEqual(accepted.parts[2].byte_size, 12)
        self.assertEqual(accepted.parts[5].file_name, "report.pdf")

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
        adapter = QQIngressAdapter(config=config, input_port=port, gateway=_Gateway())
        events = (
            NapCatPrivateMessageEvent(
                1, 10001, "1", 40004, "路人", _segments(("text", {"text": "x"}))
            ),
            NapCatGroupMessageEvent(
                1,
                10001,
                "2",
                20003,
                30003,
                "白名单好友",
                _segments(("text", {"text": "x"})),
            ),
            NapCatGroupMessageEvent(
                1, 10001, "3", 20002, 40004, "路人", _segments(("text", {"text": "x"}))
            ),
            NapCatPrivateMessageEvent(
                1, 10001, "4", 90009, "主人", _segments(("text", {"text": "x"}))
            ),
            NapCatPrivateMessageEvent(
                1,
                10001,
                "5",
                30003,
                "白名单好友",
                _segments(("text", {"text": "x"})),
            ),
            NapCatGroupMessageEvent(
                1,
                10001,
                "6",
                20002,
                30003,
                "白名单好友",
                _segments(("text", {"text": "x"})),
            ),
        )
        for event in events:
            await adapter.accept_event(event)
        self.assertEqual(
            [item.message_key.value for item in port.accepted],
            ["3", "4", "5", "6"],
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
reply_to_other_private_users = false
reply_in_groups = false
reply_private_user_allowlist = [30003]
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
        self.assertFalse(binding.adapter.reply_to_other_private_users)
        self.assertEqual(
            binding.adapter.reply_private_user_allowlist, frozenset({30003})
        )


if __name__ == "__main__":
    unittest.main()
