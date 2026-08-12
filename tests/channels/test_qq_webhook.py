from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from uuid import uuid7

import httpx
from armi_adapter_qq import QQAdapterConfig, QQIngressAdapter, create_qq_event_app
from armi_channel_napcat import NapCatActionResponse, NapCatDownloadedFile
from armi_evidence.api import EvidenceId
from armi_interaction.api import (
    ExternalMessageInputAcceptance,
    ExternalMessageInteractionId,
    ObservedExternalMessage,
    OpportunityId,
)
from armi_kernel.contracts import Digest


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
    async def send_group_text(self, *, group_id: int, text: str, echo: str):
        return NapCatActionResponse("ok", 0, "1", echo)

    async def send_private_text(self, *, user_id: int, text: str, echo: str):
        return NapCatActionResponse("ok", 0, "1", echo)

    async def get_message_sender(self, *, message_id: str) -> int | None:
        return None

    async def fetch_media(self, *, locator: str, kind: str, max_bytes: int):
        return NapCatDownloadedFile(b"media", "sample.bin", "application/octet-stream")


class QQWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_friend_and_acknowledges_temporary_private(self) -> None:
        secret = b"local-test-secret"
        port = _InputPort()
        config = QQAdapterConfig(
            10001,
            90009,
            {20002: "朋友群"},
            True,
            True,
            frozenset(),
            frozenset(),
        )
        app = create_qq_event_app(
            config=config,
            ingress=QQIngressAdapter(
                config=config, input_port=port, gateway=_Gateway()
            ),
            signing_secret=secret,
            request_body_max_bytes=4096,
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:
            statuses = []
            for subtype in ("friend", "group"):
                body = json.dumps(
                    {
                        "time": 1_800_000_000,
                        "self_id": 10001,
                        "post_type": "message",
                        "message_type": "private",
                        "sub_type": subtype,
                        "message_id": 345,
                        "user_id": 30003,
                        "message": [{"type": "text", "data": {"text": "你好"}}],
                        "sender": {"nickname": "小明"},
                    },
                    separators=(",", ":"),
                ).encode()
                signature = "sha1=" + hmac.new(secret, body, hashlib.sha1).hexdigest()
                response = await client.post(
                    "/",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-signature": signature,
                    },
                )
                statuses.append(response.status_code)
        self.assertEqual(statuses, [204, 204])
        self.assertEqual(len(port.accepted), 1)
        self.assertEqual(port.accepted[0].conversation_kind.value, "direct")

    async def test_rejects_bad_signature_and_wrong_account_header(self) -> None:
        secret = b"local-test-secret"
        port = _InputPort()
        config = QQAdapterConfig(
            10001,
            90009,
            {20002: "朋友群"},
            True,
            True,
            frozenset(),
            frozenset(),
        )
        app = create_qq_event_app(
            config=config,
            ingress=QQIngressAdapter(
                config=config, input_port=port, gateway=_Gateway()
            ),
            signing_secret=secret,
            request_body_max_bytes=4096,
        )
        body = b"{}"
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:
            bad = await client.post(
                "/", content=body, headers={"content-type": "application/json"}
            )
            signature = "sha1=" + hmac.new(secret, body, hashlib.sha1).hexdigest()
            wrong = await client.post(
                "/",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-signature": signature,
                    "x-self-id": "2",
                },
            )
        self.assertEqual((bad.status_code, wrong.status_code), (401, 403))


if __name__ == "__main__":
    unittest.main()
