from __future__ import annotations

import json
import unittest

from armi_channel_napcat import (
    NapCatActionResponse,
    NapCatGroupMessageEvent,
    NapCatViolation,
    parse_onebot_message,
)


class NapCatContractTests(unittest.TestCase):
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

    def test_parses_successful_action_response(self) -> None:
        parsed = parse_onebot_message(
            '{"status":"ok","retcode":0,"data":{"message_id":88},"echo":"e1"}'
        )
        self.assertEqual(parsed, NapCatActionResponse("ok", 0, "88", "e1"))
        assert isinstance(parsed, NapCatActionResponse)
        self.assertTrue(parsed.succeeded)

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


if __name__ == "__main__":
    unittest.main()
