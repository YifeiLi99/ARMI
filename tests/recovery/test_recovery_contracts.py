from __future__ import annotations

import unittest
from uuid import uuid4, uuid7

from armi_kernel.application import (
    RecoveryDecision,
    RecoveryFinding,
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
            requeued_work_count=1,
            terminal_work_count=0,
            requeued_outbox_count=1,
            dead_outbox_count=0,
            resumable_work_count=2,
            resumable_outbox_count=3,
            resumable_opportunity_count=4,
            resumable_cognitive_episode_count=1,
            resumable_model_attempt_count=0,
            resumable_candidate_validation_count=0,
            resumable_subject_commit_count=0,
            resumable_capability_request_count=0,
            resumable_response_operation_count=0,
            resumable_effect_count=0,
            resumable_effect_outbox_count=0,
            resumable_effect_attempt_count=0,
            reliable_effect_observation_count=0,
            creator_response_delivery_count=0,
            resumable_web_observation_count=0,
            unknown_web_observation_attempt_count=0,
            critical_artifact_count=2,
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
                requeued_work_count=0,
                terminal_work_count=0,
                requeued_outbox_count=0,
                dead_outbox_count=0,
                resumable_work_count=0,
                resumable_outbox_count=0,
                resumable_opportunity_count=0,
                resumable_cognitive_episode_count=0,
                resumable_model_attempt_count=0,
                resumable_candidate_validation_count=0,
                resumable_subject_commit_count=0,
                resumable_capability_request_count=0,
                resumable_response_operation_count=0,
                resumable_effect_count=0,
                resumable_effect_outbox_count=0,
                resumable_effect_attempt_count=0,
                reliable_effect_observation_count=0,
                creator_response_delivery_count=0,
                resumable_web_observation_count=0,
                unknown_web_observation_attempt_count=0,
                critical_artifact_count=2,
                blocker_count=1,
            )

    def test_error_output_is_redacted(self) -> None:
        error = RecoveryViolation("REC-DATABASE")
        self.assertEqual(error.code, "REC-DATABASE")
        self.assertNotIn("postgres", str(error).lower())
        self.assertNotIn("path", str(error).lower())


if __name__ == "__main__":
    unittest.main()
