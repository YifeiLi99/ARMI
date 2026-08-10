from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4, uuid7

from armi_kernel.application import (
    EffectAdapterReceipt,
    EffectAttemptId,
    EffectDeliveryId,
    EffectId,
    EffectObservation,
    EffectObservationId,
    EffectObservationKind,
    EffectObservationReliability,
    EffectSettlement,
    EffectStatus,
    EffectVerificationStatus,
    EffectView,
    EffectViolation,
    FrozenEffectRequest,
    PolicyDecisionId,
    PolicyDecisionOutcome,
)
from armi_kernel.contracts import Digest, Instant, TraceId


class EffectContractTests(unittest.TestCase):
    def test_frozen_effect_contract(self) -> None:
        effect_id = EffectId(uuid7())
        decision_id = PolicyDecisionId(uuid7())
        view = EffectView(
            effect_id,
            uuid7(),
            "creator_response",
            EffectStatus.REGISTERED,
            EffectVerificationStatus.NOT_STARTED,
            Instant(datetime.now(UTC)),
            uuid7(),
            uuid7(),
            "creator.scene.reply",
        )
        self.assertEqual(view.effect_id, effect_id)
        self.assertEqual(decision_id.value.version, 7)
        self.assertEqual(
            {item.value for item in PolicyDecisionOutcome},
            {"allowed", "denied", "confirmation_required", "unavailable"},
        )

    def test_invalid_identity_and_state_are_rejected(self) -> None:
        with self.assertRaises(EffectViolation) as identity:
            EffectId(uuid4())
        self.assertEqual(identity.exception.code, "CON-EFFECT-ID")
        with self.assertRaises(EffectViolation) as state:
            EffectView(
                EffectId(uuid7()),
                uuid7(),
                "creator_response",
                EffectStatus.CANCELLED,
                EffectVerificationStatus.NOT_STARTED,
                Instant(datetime.now(UTC)),
                uuid7(),
                uuid7(),
                "creator.scene.reply",
            )
        self.assertEqual(state.exception.code, "CON-EFFECT-STATE")

    def test_error_is_redacted(self) -> None:
        error = EffectViolation("EFFECT-DATABASE")
        self.assertNotIn("postgres", str(error).lower())

    def test_receipt_observation_and_terminal_settlement_are_strict(self) -> None:
        now = Instant(datetime.now(UTC))
        effect_id = EffectId(uuid7())
        attempt_id = EffectAttemptId(uuid7())
        delivery_id = EffectDeliveryId(uuid7())
        receipt = EffectAdapterReceipt(
            delivery_id,
            Digest.from_bytes(b"receipt"),
            now,
        )
        observation = EffectObservation(
            EffectObservationId(uuid7()),
            attempt_id,
            EffectObservationKind.RECEIPT,
            EffectObservationReliability.RELIABLE,
            receipt.receipt_digest,
            now,
            delivery_id.value,
        )
        settlement = EffectSettlement(
            effect_id,
            EffectStatus.COMPLETED,
            EffectVerificationStatus.VERIFIED,
            1,
            observation,
            now,
        )
        self.assertEqual(settlement.attempt_count, 1)

    def test_unknown_requires_explicit_verification_action(self) -> None:
        with self.assertRaises(EffectViolation) as invalid:
            EffectView(
                EffectId(uuid7()),
                uuid7(),
                "creator_response",
                EffectStatus.UNKNOWN,
                EffectVerificationStatus.INCONCLUSIVE,
                Instant(datetime.now(UTC)),
                uuid7(),
                uuid7(),
                "creator.scene.reply",
                attempt_count=1,
            )
        self.assertEqual(invalid.exception.code, "CON-EFFECT-VERIFICATION")

    def test_verified_cancellation_after_attempt_keeps_settlement(self) -> None:
        now = Instant(datetime.now(UTC))
        observation = EffectObservation(
            EffectObservationId(uuid7()),
            EffectAttemptId(uuid7()),
            EffectObservationKind.QUERY,
            EffectObservationReliability.RELIABLE,
            Digest.from_bytes(b"confirmed absent"),
            now,
        )
        settlement = EffectSettlement(
            EffectId(uuid7()),
            EffectStatus.CANCELLED,
            EffectVerificationStatus.VERIFIED,
            1,
            observation,
            now,
        )

        self.assertIs(settlement.status, EffectStatus.CANCELLED)

    def test_external_group_effect_requires_complete_frozen_route(self) -> None:
        content = b"hello"
        request = FrozenEffectRequest(
            EffectId(uuid7()),
            EffectAttemptId(uuid7()),
            uuid7(),
            uuid7(),
            uuid7(),
            "external_group",
            "qq",
            "10001",
            "20002",
            Digest.from_bytes(content),
            len(content),
            TraceId(uuid7().hex),
        )
        self.assertEqual(request.external_conversation_key, "20002")

        with self.assertRaises(EffectViolation) as invalid:
            FrozenEffectRequest(
                EffectId(uuid7()),
                EffectAttemptId(uuid7()),
                uuid7(),
                uuid7(),
                uuid7(),
                "external_group",
                "qq",
                "10001",
                None,
                Digest.from_bytes(content),
                len(content),
                TraceId(uuid7().hex),
            )
        self.assertEqual(invalid.exception.code, "CON-EFFECT-DESTINATION")

    def test_codex_effect_allows_model_identity_enrichment_from_manifest(self) -> None:
        view = EffectView(
            EffectId(uuid7()),
            uuid7(),
            "codex_delegation",
            EffectStatus.COMPLETED,
            EffectVerificationStatus.VERIFIED,
            Instant(datetime.now(UTC)),
            uuid7(),
            uuid7(),
            "codex.delegated-work",
            attempt_count=1,
            sdk_identity="openai-codex==0.144.4",
            source_tree_digest=Digest.from_bytes(b"source"),
            validation_status="passed",
            cleanup_status="succeeded",
            result_acceptance_status="accepted",
        )

        self.assertIsNone(view.model_id)


if __name__ == "__main__":
    unittest.main()
