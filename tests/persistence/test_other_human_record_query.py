from __future__ import annotations

import unittest
from uuid import uuid7

from armi_kernel.application import OtherHumanRecordViolation
from armi_kernel.contracts import OpaqueCursor
from armi_runtime.adapters.persistence.other_human_records import (
    OtherHumanRecordCursorCodec,
)


class OtherHumanRecordCursorTests(unittest.TestCase):
    def test_cursor_survives_reconnect_and_remains_bound_to_scope(self) -> None:
        environment_id = uuid7()
        key = b"r" * 32
        first = OtherHumanRecordCursorCodec(key=key, environment_id=environment_id)
        cursor = first.encode("scenes", "party-a", {"before_id": str(uuid7())})
        restarted = OtherHumanRecordCursorCodec(key=key, environment_id=environment_id)
        decoded = restarted.decode(cursor, "scenes", "party-a", {"before_id"})
        self.assertIn("before_id", decoded)
        with self.assertRaises(OtherHumanRecordViolation):
            restarted.decode(cursor, "scenes", "party-b", {"before_id"})

    def test_cursor_rejects_tampering(self) -> None:
        codec = OtherHumanRecordCursorCodec(key=b"r" * 32, environment_id=uuid7())
        cursor = codec.encode("parties", "all", {"before_id": str(uuid7())})
        tampered = OpaqueCursor(
            cursor.value[:-1] + ("A" if cursor.value[-1] != "A" else "B")
        )
        with self.assertRaises(OtherHumanRecordViolation):
            codec.decode(tampered, "parties", "all", {"before_id"})


if __name__ == "__main__":
    unittest.main()
