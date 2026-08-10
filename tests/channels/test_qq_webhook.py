from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from uuid import uuid7

import httpx
from armi_adapter_qq import (
    QQAdapterConfig,
    QQGroupIngressAdapter,
    QQNapCatBindingConfig,
    create_qq_event_app,
    create_qq_napcat_binding,
)
from armi_kernel.application import (
    EnsureExternalGroupCommand,
    EvidenceId,
    ExternalGroupInputAcceptance,
    ExternalGroupView,
    ObservedExternalGroupMessage,
    OpportunityId,
    OtherHumanInteractionId,
    SceneKey,
)
from armi_kernel.contracts import Digest


class _InputPort:
    def __init__(self) -> None:
        self.accepted: list[ObservedExternalGroupMessage] = []

    async def ensure_group(
        self, command: EnsureExternalGroupCommand
    ) -> ExternalGroupView:
        del command
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


class QQWebhookTests(unittest.IsolatedAsyncioTestCase):
    async def test_binding_keeps_api_token_and_event_secret_separate(self) -> None:
        api_token = b"api-token"
        event_secret = b"event-secret"
        port = _InputPort()
        adapter_config = QQAdapterConfig(10001, {20002: "朋友群"})
        binding = create_qq_napcat_binding(
            config=QQNapCatBindingConfig(
                adapter_config,
                "http://127.0.0.1:3000",
                6199,
                4096,
            ),
            input_port=port,
            access_token=api_token,
            event_signing_secret=event_secret,
        )
        body = json.dumps(
            {
                "time": 1_800_000_000,
                "self_id": 10001,
                "post_type": "message",
                "message_type": "group",
                "message_id": 345,
                "group_id": 20002,
                "user_id": 30003,
                "message": [{"type": "text", "data": {"text": "你好"}}],
                "sender": {"nickname": "小明"},
            },
            separators=(",", ":"),
        ).encode()
        transport = httpx.ASGITransport(app=binding.event_app)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://127.0.0.1"
            ) as client:
                wrong_signature = (
                    "sha1=" + hmac.new(api_token, body, hashlib.sha1).hexdigest()
                )
                rejected = await client.post(
                    "/",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-signature": wrong_signature,
                    },
                )
                signature = (
                    "sha1=" + hmac.new(event_secret, body, hashlib.sha1).hexdigest()
                )
                accepted = await client.post(
                    "/",
                    content=body,
                    headers={
                        "content-type": "application/json",
                        "x-signature": signature,
                    },
                )
        finally:
            await binding.close()
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 204)
        self.assertEqual(len(port.accepted), 1)

    async def test_requires_signature_and_accepts_onebot_group_event(self) -> None:
        secret = b"local-test-secret"
        port = _InputPort()
        config = QQAdapterConfig(10001, {20002: "朋友群"})
        app = create_qq_event_app(
            config=config,
            ingress=QQGroupIngressAdapter(config=config, input_port=port),
            signing_secret=secret,
            request_body_max_bytes=4096,
        )
        body = json.dumps(
            {
                "time": 1_800_000_000,
                "self_id": 10001,
                "post_type": "message",
                "message_type": "group",
                "message_id": 345,
                "group_id": 20002,
                "user_id": 30003,
                "message": [{"type": "text", "data": {"text": "你好"}}],
                "sender": {"nickname": "小明"},
            },
            separators=(",", ":"),
        ).encode()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1"
        ) as client:
            rejected = await client.post(
                "/", content=body, headers={"content-type": "application/json"}
            )
            signature = "sha1=" + hmac.new(secret, body, hashlib.sha1).hexdigest()
            accepted = await client.post(
                "/",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x-self-id": "10001",
                    "x-signature": signature,
                },
            )
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 204)
        self.assertEqual(len(port.accepted), 1)


if __name__ == "__main__":
    unittest.main()
