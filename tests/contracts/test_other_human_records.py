from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid7

from armi_kernel.application import (
    OtherHumanPartyRecord,
    OtherHumanRecordDirection,
    OtherHumanRecordViolation,
    OtherHumanSceneRecord,
    OtherHumanTimelineRecord,
)


class OtherHumanRecordContractTests(unittest.TestCase):
    def test_party_scene_and_timeline_keep_exact_identity_and_direction(self) -> None:
        now = datetime.now(UTC)
        party = OtherHumanPartyRecord(uuid7(), "friend-1", "朋友", 2, 8, now)
        scene = OtherHumanSceneRecord(uuid7(), "tea", "open", 3, now)
        item = OtherHumanTimelineRecord(
            uuid7(),
            uuid7(),
            OtherHumanRecordDirection.RECEIVED,
            "accepted",
            "你好",
            now,
        )
        self.assertEqual(party.party_key, "friend-1")
        self.assertEqual(scene.record_count, 3)
        self.assertIs(item.direction, OtherHumanRecordDirection.RECEIVED)

    def test_timeline_rejects_empty_text_and_unknown_status(self) -> None:
        with self.assertRaises(OtherHumanRecordViolation):
            OtherHumanTimelineRecord(
                uuid7(),
                uuid7(),
                OtherHumanRecordDirection.SENT,
                "registered",
                "",
                datetime.now(UTC),
            )


if __name__ == "__main__":
    unittest.main()
