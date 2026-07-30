from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import UUID, uuid4

from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditQuery,
    AuditQueryResult,
    AuditRecord,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId, TraceId

_FIRST = UUID("01980f7d-7b8f-7e2a-8a11-2ab8e1234567")
_SECOND = UUID("01980f7d-7b90-7e2a-8a11-2ab8e1234567")
_TRACE = TraceId("0123456789abcdef0123456789abcdef")
_DIGEST = Digest(f"sha256:{'a' * 64}")


def _draft(**changes: object) -> AuditDraft:
    values: dict[str, object] = {
        "audit_event_id": AuditEventId(_FIRST),
        "actor": AuditReference("runtime", _FIRST),
        "purpose": Purpose("artifact.catalog"),
        "operation": "artifact.catalog.registered",
        "target": AuditReference("artifact", _SECOND),
        "result_status": AuditResultStatus.APPLIED,
        "trace_id": _TRACE,
        "sensitivity": AuditSensitivity.PRIVATE,
        "artifact_digest": _DIGEST,
    }
    values.update(changes)
    return AuditDraft(**values)  # type: ignore[arg-type]


class AuditContractTests(unittest.TestCase):
    def test_safe_fixed_record_and_query_are_immutable(self) -> None:
        draft = _draft(
            subject_id=SubjectId(_SECOND),
            request=AuditReference("request", _FIRST),
            before_version=0,
            after_version=1,
        )
        record = AuditRecord(
            draft,
            Instant(datetime(2026, 7, 30, 1, 2, 3, 4, tzinfo=UTC)),
        )
        result = AuditQueryResult((record,), False)

        self.assertEqual(
            result.records[0].draft.operation, "artifact.catalog.registered"
        )
        self.assertEqual(AuditQuery(target=draft.target, limit=1).limit, 1)
        with self.assertRaises(AttributeError):
            draft.operation = "changed"  # type: ignore[misc]

    def test_uuid_tokens_versions_and_selector_are_strict(self) -> None:
        invalid = (
            lambda: AuditEventId(uuid4()),
            lambda: AuditReference("Bad Kind", _FIRST),
            lambda: _draft(before_version=0),
            lambda: _draft(before_version=1, after_version=1),
            lambda: _draft(schema_version=2),
            lambda: AuditQuery(),
            lambda: AuditQuery(event_id=AuditEventId(_FIRST), trace_id=_TRACE),
            lambda: AuditQuery(trace_id=_TRACE, limit=0),
            lambda: AuditQuery(trace_id=_TRACE, limit=101),
        )
        for candidate in invalid:
            with self.subTest(candidate=candidate), self.assertRaises(AuditViolation):
                candidate()

    def test_violation_does_not_echo_untrusted_content(self) -> None:
        secret = "Do Not Echo"
        with self.assertRaises(AuditViolation) as raised:
            AuditReference(secret, _FIRST)
        self.assertNotIn(secret, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
