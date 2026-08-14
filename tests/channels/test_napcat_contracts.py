from __future__ import annotations

import asyncio
import base64
import json
import unittest

import httpx
from armi_channel_napcat import (
    NapCatActionResponse,
    NapCatAmbiguousDelivery,
    NapCatGroupMessageEvent,
    NapCatHttpClient,
    NapCatPrivateMessageEvent,
    NapCatViolation,
    parse_onebot_message,
)


class NapCatContractTests(unittest.TestCase):
    def _health(
        self,
        handler: httpx.MockTransport,
        *,
        expected_account_id: int = 10001,
    ):
        async def exercise():
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:3000",
                transport=handler,
            ) as client:
                gateway = NapCatHttpClient(
                    base_url="http://127.0.0.1:3000",
                    access_token="test-" + "token",
                    client=client,
                )
                return await gateway.inspect_health(
                    expected_account_id=expected_account_id
                )

        return asyncio.run(exercise())

    def test_health_requires_status_and_matching_login(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            data = (
                {"online": True, "good": True}
                if request.url.path == "/get_status"
                else {"user_id": 10001, "nickname": "private"}
            )
            return httpx.Response(
                200, json={"status": "ok", "retcode": 0, "data": data}
            )

        health = self._health(httpx.MockTransport(handler))
        self.assertEqual(health.state, "ready")
        self.assertTrue(health.api_reachable)
        self.assertTrue(health.account_online)
        self.assertTrue(health.account_matches)
        self.assertEqual(health.reason_codes, ())
        self.assertNotIn("nickname", repr(health))

    def test_health_distinguishes_login_required_unhealthy_and_wrong_account(
        self,
    ) -> None:
        cases = (
            (
                {"online": False, "good": True},
                10001,
                "login_required",
                "NAPCAT-LOGIN-REQUIRED",
            ),
            (
                {"online": True, "good": False},
                10001,
                "unavailable",
                "NAPCAT-STATUS-UNHEALTHY",
            ),
            (
                {"online": True, "good": True},
                99999,
                "misconfigured",
                "NAPCAT-ACCOUNT-MISMATCH",
            ),
        )
        for status_data, login_id, state, reason in cases:
            with self.subTest(state=state, reason=reason):

                def handler(
                    request: httpx.Request,
                    status_value: dict[str, bool] = status_data,
                    login_value: int = login_id,
                ) -> httpx.Response:
                    data = (
                        status_value
                        if request.url.path == "/get_status"
                        else {"user_id": login_value}
                    )
                    return httpx.Response(
                        200, json={"status": "ok", "retcode": 0, "data": data}
                    )

                health = self._health(httpx.MockTransport(handler))
                self.assertEqual(health.state, state)
                self.assertIn(reason, health.reason_codes)

    def test_health_maps_auth_timeout_and_malformed_response(self) -> None:
        def timeout(_request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout")

        cases = (
            (
                httpx.MockTransport(lambda _request: httpx.Response(401)),
                "misconfigured",
                "NAPCAT-HEALTH-AUTH-REJECTED",
            ),
            (httpx.MockTransport(timeout), "unavailable", "NAPCAT-HEALTH-UNAVAILABLE"),
            (
                httpx.MockTransport(
                    lambda _request: httpx.Response(200, text="broken")
                ),
                "misconfigured",
                "NAPCAT-HEALTH-RESPONSE-INVALID",
            ),
        )
        for transport, state, reason in cases:
            with self.subTest(state=state, reason=reason):
                health = self._health(transport)
                self.assertEqual(health.state, state)
                self.assertIn(reason, health.reason_codes)

    def test_parses_group_message_and_mentions(self) -> None:
        parsed = parse_onebot_message(
            json.dumps(
                {
                    "time": 1_800_000_000,
                    "self_id": 10001,
                    "post_type": "message",
                    "message_type": "group",
                    "message_id": 345,
                    "group_id": 20002,
                    "user_id": 30003,
                    "message": [
                        {"type": "at", "data": {"qq": "10001"}},
                        {"type": "text", "data": {"text": " 你好"}},
                    ],
                    "sender": {"nickname": "小明", "card": "群名片"},
                }
            )
        )
        self.assertIsInstance(parsed, NapCatGroupMessageEvent)
        assert isinstance(parsed, NapCatGroupMessageEvent)
        self.assertEqual(parsed.sender_label, "群名片")
        self.assertEqual(parsed.mentioned_ids, frozenset({10001}))
        self.assertEqual(parsed.render_text(), "@QQ(10001) 你好")

    def test_preserves_validated_visual_and_face_fields_only(self) -> None:
        parsed = parse_onebot_message(
            json.dumps(
                {
                    "time": 1_800_000_000,
                    "self_id": 10001,
                    "post_type": "message",
                    "message_type": "private",
                    "sub_type": "friend",
                    "message_id": 347,
                    "user_id": 30003,
                    "message": [
                        {
                            "type": "face",
                            "data": {
                                "id": "14",
                                "resultId": "2",
                                "chainCount": 3,
                                "raw": {"faceText": "/微笑", "secret": "drop"},
                            },
                        },
                        {
                            "type": "image",
                            "data": {
                                "file": "picture.jpg",
                                "summary": "开心企鹅",
                                "sub_type": 1,
                                "emoji_id": "emoji-1",
                                "emoji_package_id": 8,
                                "key": "must-not-cross-boundary",
                                "url": "https://signed.invalid/value",
                            },
                        },
                    ],
                    "sender": {"nickname": "小明"},
                }
            )
        )
        self.assertIsInstance(parsed, NapCatPrivateMessageEvent)
        assert isinstance(parsed, NapCatPrivateMessageEvent)
        self.assertEqual(parsed.segments[0].data["face_text"], "/微笑")
        self.assertEqual(parsed.segments[0].data["chainCount"], "3")
        self.assertNotIn("raw", parsed.segments[0].data)
        self.assertEqual(parsed.segments[1].data["sub_type"], "1")
        self.assertNotIn("key", parsed.segments[1].data)
        self.assertNotIn("url", parsed.segments[1].data)

    def test_parses_successful_action_response(self) -> None:
        parsed = parse_onebot_message(
            '{"status":"ok","retcode":0,"data":{"message_id":88},"echo":"e1"}'
        )
        self.assertEqual(parsed, NapCatActionResponse("ok", 0, "88", "e1"))
        assert isinstance(parsed, NapCatActionResponse)
        self.assertTrue(parsed.succeeded)

    def test_parses_friend_private_and_ignores_group_temporary_private(self) -> None:
        base = {
            "time": 1_800_000_000,
            "self_id": 10001,
            "post_type": "message",
            "message_type": "private",
            "message_id": 346,
            "user_id": 30003,
            "message": [{"type": "text", "data": {"text": "你好"}}],
            "sender": {"nickname": "小明"},
        }
        parsed = parse_onebot_message(json.dumps({**base, "sub_type": "friend"}))
        self.assertIsInstance(parsed, NapCatPrivateMessageEvent)
        self.assertIsNone(
            parse_onebot_message(json.dumps({**base, "sub_type": "group"}))
        )

    def test_accepts_current_napcat_decimal_string_ids(self) -> None:
        parsed = parse_onebot_message(
            json.dumps(
                {
                    "time": "1800000000",
                    "self_id": "10001",
                    "post_type": "message",
                    "message_type": "group",
                    "message_id": "345",
                    "group_id": "20002",
                    "user_id": "30003",
                    "message": [{"type": "text", "data": {"text": "你好"}}],
                    "sender": {"nickname": "小明"},
                }
            )
        )
        self.assertIsInstance(parsed, NapCatGroupMessageEvent)
        assert isinstance(parsed, NapCatGroupMessageEvent)
        self.assertEqual(
            (parsed.self_id, parsed.group_id, parsed.user_id), (10001, 20002, 30003)
        )

    def test_ignores_non_group_events(self) -> None:
        self.assertIsNone(
            parse_onebot_message(
                '{"post_type":"notice","notice_type":"group_increase"}'
            )
        )

    def test_rejects_malformed_group_event(self) -> None:
        with self.assertRaisesRegex(NapCatViolation, "NAPCAT-GROUP-EVENT-INVALID"):
            parse_onebot_message(
                '{"post_type":"message","message_type":"group","self_id":1}'
            )

    def test_http_action_correlates_its_synchronous_response(self) -> None:
        observed: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            document = json.loads(request.content)
            observed.append(document)
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "retcode": 0,
                    "data": {"message_id": "88"},
                },
            )

        async def exercise() -> NapCatActionResponse:
            credential = "test-" + "token"
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:3000",
                transport=httpx.MockTransport(handler),
            ) as client:
                gateway = NapCatHttpClient(
                    base_url="http://127.0.0.1:3000",
                    access_token=credential,
                    client=client,
                )
                return await gateway.send_group_text(
                    group_id=20002, text="你好", echo="effect:attempt"
                )

        response = asyncio.run(exercise())
        self.assertEqual(response.message_id, "88")
        self.assertEqual(
            observed,
            [
                {
                    "group_id": 20002,
                    "message": "你好",
                }
            ],
        )

    def test_http_server_failure_is_ambiguous_after_dispatch(self) -> None:
        async def exercise() -> None:
            credential = "test-" + "token"
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:3000",
                transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
            ) as client:
                gateway = NapCatHttpClient(
                    base_url="http://127.0.0.1:3000",
                    access_token=credential,
                    client=client,
                )
                with self.assertRaisesRegex(
                    NapCatAmbiguousDelivery, "NAPCAT-DELIVERY-AMBIGUOUS"
                ):
                    await gateway.send_group_text(
                        group_id=20002, text="你好", echo="effect:attempt"
                    )

        asyncio.run(exercise())

    def test_http_private_send_uses_onebot_private_payload(self) -> None:
        observed: list[tuple[str, dict[str, object]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            observed.append((request.url.path, json.loads(request.content)))
            return httpx.Response(
                200, json={"status": "ok", "retcode": 0, "data": {"message_id": 89}}
            )

        async def exercise() -> None:
            credential = "test-" + "token"
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:3000", transport=httpx.MockTransport(handler)
            ) as client:
                gateway = NapCatHttpClient(
                    base_url="http://127.0.0.1:3000",
                    access_token=credential,
                    client=client,
                )
                await gateway.send_private_text(
                    user_id=30003, text="你好", echo="effect:attempt"
                )

        asyncio.run(exercise())
        self.assertEqual(
            observed, [("/send_private_msg", {"user_id": 30003, "message": "你好"})]
        )

    def test_reads_image_record_video_and_file_actions(self) -> None:
        observed: list[tuple[str, dict[str, object]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            observed.append((request.url.path, json.loads(request.content)))
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "retcode": 0,
                    "data": {
                        "base64": base64.b64encode(b"media").decode(),
                        "file_name": "sample.bin",
                    },
                },
            )

        async def exercise() -> None:
            async with httpx.AsyncClient(
                base_url="http://127.0.0.1:3000",
                transport=httpx.MockTransport(handler),
            ) as client:
                gateway = NapCatHttpClient(
                    base_url="http://127.0.0.1:3000",
                    access_token="test-" + "token",
                    client=client,
                )
                for kind in ("image", "audio", "video", "file"):
                    downloaded = await gateway.fetch_media(
                        locator=f"{kind}-locator", kind=kind, max_bytes=1024
                    )
                    self.assertEqual(downloaded.content, b"media")

        asyncio.run(exercise())
        self.assertEqual(
            observed,
            [
                ("/get_image", {"file": "image-locator"}),
                (
                    "/get_record",
                    {"file": "audio-locator", "out_format": "mp3"},
                ),
                ("/get_file", {"file": "video-locator"}),
                ("/get_file", {"file": "file-locator"}),
            ],
        )


if __name__ == "__main__":
    unittest.main()
