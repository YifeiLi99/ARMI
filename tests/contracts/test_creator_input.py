"""CON-INPUT checks for the technology-neutral Creator acceptance contract."""

from __future__ import annotations

import unittest
from uuid import uuid7

from armi_evidence.api import EvidenceId
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorInteractionId,
    CreatorOperation,
    CreatorOperationPhase,
    CreatorVoiceInputCommand,
    OpportunityId,
)
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId


class CreatorInputContractTests(unittest.TestCase):
    def test_live_voice_command_preserves_exact_final_transcript(self) -> None:
        command = CreatorVoiceInputCommand(
            "creator-voice-local",
            "你今天开心吗?",
            IdempotencyKey("voice-session-turn-1"),
            TraceId("1" * 32),
        )

        self.assertEqual(command.transcript, "你今天开心吗?")
        self.assertEqual(command.transcript_bytes, "你今天开心吗?".encode())

    def test_command_preserves_exact_utf8_and_acceptance_is_stable(self) -> None:
        command = CreatorInputCommand(
            scene_key="default",
            message="  第一行\r\n第二行  ",
            idempotency_key=IdempotencyKey("request-1"),
            trace_id=TraceId("1" * 32),
        )
        self.assertEqual(
            command.message_bytes,
            "  第一行\r\n第二行  ".encode(),
        )
        acceptance = CreatorInputAcceptance(
            CreatorInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"request"),
            Digest.from_bytes(command.message_bytes),
            True,
        )
        self.assertTrue(acceptance.newly_accepted)

    def test_message_boundaries_and_safe_error_are_strict(self) -> None:
        common = {
            "scene_key": "default",
            "idempotency_key": IdempotencyKey("request-1"),
            "trace_id": TraceId("1" * 32),
        }
        for message, code in (
            (" \r\n\t", "CON-INPUT-MESSAGE"),
            ("contains\x00nul", "CON-INPUT-MESSAGE"),
            ("\ud800", "CON-INPUT-UNICODE"),
            ("x" * (256 * 1024 + 1), "CON-INPUT-SIZE"),
        ):
            with (
                self.subTest(code=code),
                self.assertRaisesRegex(CreatorInputViolation, code),
            ):
                CreatorInputCommand(message=message, **common)
        error = CreatorInputViolation("INPUT-MESSAGE")
        self.assertNotIn("contains", str(error))
        self.assertNotIn("path", str(error))

    def test_rejected_codex_result_keeps_effect_custody_and_candidate_error(
        self,
    ) -> None:
        acceptance = CreatorInputAcceptance(
            CreatorInteractionId(uuid7()),
            EvidenceId(uuid7()),
            OpportunityId(uuid7()),
            Digest.from_bytes(b"request"),
            Digest.from_bytes(b"task"),
            False,
        )
        operation = CreatorOperation(
            acceptance,
            CreatorOperationPhase.CODEX_RESULT_REJECTED,
            failure_code="CANDIDATE-CONTRACT",
            effect_ref=uuid7(),
        )

        self.assertEqual(
            operation.phase,
            CreatorOperationPhase.CODEX_RESULT_REJECTED,
        )
        with self.assertRaisesRegex(CreatorInputViolation, "CON-INPUT-OPERATION"):
            CreatorOperation(
                acceptance,
                CreatorOperationPhase.CODEX_RESULT_REJECTED,
                failure_code="MODEL-RESPONSE-SCHEMA",
                effect_ref=uuid7(),
            )


if __name__ == "__main__":
    unittest.main()
