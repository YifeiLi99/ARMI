from __future__ import annotations

import unittest
from uuid import uuid4, uuid7

from armi_kernel.application import (
    RecoveryDecision,
    RecoveryFinding,
    RecoveryMetric,
    RecoveryRunId,
    RecoveryStatus,
    RecoverySummary,
    RecoveryViolation,
)


class RecoveryContractTests(unittest.TestCase):
    def test_safe_summary_requires_no_blocker(self) -> None:
        finding = RecoveryFinding(
            "critical_artifact",
            RecoveryDecision.VERIFIED,
            "REC-ARTIFACT-VERIFIED",
            uuid7(),
        )
        summary = RecoverySummary(
            recovery_run_id=RecoveryRunId(uuid7()),
            status=RecoveryStatus.SAFE,
            metrics=(
                RecoveryMetric("critical_artifact_count", 2),
                RecoveryMetric("requeued_work_count", 1),
                RecoveryMetric("resumable_opportunity_count", 4),
                RecoveryMetric("resumable_work_count", 2),
            ),
            blocker_count=0,
            findings=(finding,),
        )
        self.assertEqual(summary.status, RecoveryStatus.SAFE)

    def test_invalid_identity_state_and_reason_are_rejected(self) -> None:
        with self.assertRaises(RecoveryViolation):
            RecoveryRunId(uuid4())
        with self.assertRaises(RecoveryViolation):
            RecoveryFinding(
                "critical_artifact",
                RecoveryDecision.BLOCKED,
                "NOT-RECOVERY",
            )
        with self.assertRaises(RecoveryViolation):
            RecoverySummary(
                recovery_run_id=RecoveryRunId(uuid7()),
                status=RecoveryStatus.SAFE,
                metrics=(RecoveryMetric("critical_artifact_count", 2),),
                blocker_count=1,
            )
        with self.assertRaises(RecoveryViolation):
            RecoverySummary(
                recovery_run_id=RecoveryRunId(uuid7()),
                status=RecoveryStatus.SAFE,
                metrics=(
                    RecoveryMetric("z_metric", 0),
                    RecoveryMetric("a_metric", 0),
                ),
                blocker_count=0,
            )

    def test_error_output_is_redacted(self) -> None:
        error = RecoveryViolation("REC-DATABASE")
        self.assertEqual(error.code, "REC-DATABASE")
        self.assertNotIn("postgres", str(error).lower())
        self.assertNotIn("path", str(error).lower())


if __name__ == "__main__":
    unittest.main()
