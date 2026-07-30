from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid7

from armi_kernel.application import (
    WorkAttemptId,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkRecord,
    WorkResultRef,
    WorkStatus,
    WorkViolation,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, TraceId


def _instant(offset: int) -> Instant:
    return Instant(datetime(2026, 7, 30, tzinfo=UTC) + timedelta(seconds=offset))


def _draft(**changes: object) -> WorkDraft:
    values: dict[str, object] = {
        "work_id": WorkId(uuid7()),
        "work_kind": "work.conformance",
        "owner": WorkOwner("environment", uuid7()),
        "idempotency_key": IdempotencyKey("s014-conformance"),
        "payload": WorkPayloadRef("artifact", uuid7()),
        "payload_digest": Digest.from_bytes(b"work"),
        "priority": 10,
        "not_before": _instant(0),
        "deadline_at": _instant(60),
        "max_attempts": 3,
        "trace_id": TraceId("1" + ("0" * 31)),
    }
    values.update(changes)
    return WorkDraft(**values)  # type: ignore[arg-type]


class DurableWorkContractTests(unittest.TestCase):
    def test_ready_leased_and_completed_records_are_exact(self) -> None:
        draft = _draft()
        ready = WorkRecord(draft, WorkStatus.READY, 0)
        lease = WorkLease(
            draft.work_id,
            WorkAttemptId(uuid7()),
            uuid7(),
            _instant(20),
            1,
        )
        leased = WorkRecord(draft, WorkStatus.LEASED, 1, lease)
        result = WorkResultRef("artifact", uuid7())
        completed = WorkRecord(draft, WorkStatus.COMPLETED, 1, result=result)

        self.assertEqual(ready.status, WorkStatus.READY)
        self.assertEqual(leased.lease, lease)
        self.assertEqual(completed.result, result)

    def test_invalid_uuid_deadline_priority_and_attempts_are_rejected(self) -> None:
        cases = (
            lambda: WorkId(uuid4()),
            lambda: _draft(deadline_at=_instant(0)),
            lambda: _draft(deadline_at=_instant(3601)),
            lambda: _draft(priority=101),
            lambda: _draft(max_attempts=0),
        )
        for case in cases:
            with self.subTest(case=case), self.assertRaises(WorkViolation):
                case()

    def test_state_requires_matching_lease_and_result_shapes(self) -> None:
        draft = _draft()
        lease = WorkLease(
            draft.work_id,
            WorkAttemptId(uuid7()),
            uuid7(),
            _instant(20),
            1,
        )
        with self.assertRaises(WorkViolation) as missing_lease:
            WorkRecord(draft, WorkStatus.LEASED, 1)
        self.assertEqual(missing_lease.exception.code, "WORK-STATE")

        with self.assertRaises(WorkViolation) as leaked_lease:
            WorkRecord(draft, WorkStatus.READY, 1, lease)
        self.assertEqual(leaked_lease.exception.code, "WORK-STATE")

        with self.assertRaises(WorkViolation) as missing_result:
            WorkRecord(draft, WorkStatus.COMPLETED, 1)
        self.assertEqual(missing_result.exception.code, "WORK-STATE")

    def test_violation_is_redacted(self) -> None:
        error = WorkViolation("WORK-IDEMPOTENCY-CONFLICT")
        self.assertEqual(error.code, "WORK-IDEMPOTENCY-CONFLICT")
        self.assertNotIn("payload", repr(error))
        self.assertNotIn("database", str(error).lower())


if __name__ == "__main__":
    unittest.main()
