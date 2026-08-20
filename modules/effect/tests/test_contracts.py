from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4, uuid7

from armi_effect.api import (
    EffectAttemptId,
    EffectDispatchBoundaryResult,
    EffectId,
    EffectStatus,
    EffectVerificationStatus,
    EffectView,
    EffectViolation,
    FrozenEffectRequest,
    PolicyDecisionId,
)
from armi_kernel.contracts import Digest, Instant, TraceId


class EffectContractTests(unittest.TestCase):
    def test_frozen_effect_contract(self) -> None:
        effect_id = EffectId(uuid7())
        decision_id = PolicyDecisionId(uuid7())
        view = EffectView(
            effect_id=effect_id,
            action_intent_ref=uuid7(),
            action_intent_revision_ref=uuid7(),
            policy_decision_ref=uuid7(),
            effect_kind="creator_response",
            status=EffectStatus.REGISTERED,
            verification_status=EffectVerificationStatus.NOT_STARTED,
            registered_at=Instant(datetime.now(UTC)),
            capability_kind="creator.scene.reply",
        )
        self.assertEqual(view.effect_id, effect_id)
        self.assertEqual(decision_id.value.version, 7)

    def test_invalid_identity_and_state_are_rejected(self) -> None:
        with self.assertRaises(EffectViolation) as identity:
            EffectId(uuid4())
        self.assertEqual(identity.exception.code, "CON-EFFECT-ID")
        with self.assertRaises(EffectViolation) as state:
            EffectView(
                effect_id=EffectId(uuid7()),
                action_intent_ref=uuid7(),
                action_intent_revision_ref=uuid7(),
                policy_decision_ref=uuid7(),
                effect_kind="creator_response",
                status=EffectStatus.CANCELLED,
                verification_status=EffectVerificationStatus.NOT_STARTED,
                registered_at=Instant(datetime.now(UTC)),
                capability_kind="creator.scene.reply",
            )
        self.assertEqual(state.exception.code, "CON-EFFECT-STATE")

    def test_dispatch_boundary_result_requires_stable_grant_identity(self) -> None:
        result = EffectDispatchBoundaryResult(True, uuid7())
        self.assertTrue(result.allowed)
        with self.assertRaises(EffectViolation):
            EffectDispatchBoundaryResult(False, uuid4(), "POLICY-GRANT-NOT-CURRENT")

    def test_error_is_redacted(self) -> None:
        error = EffectViolation("EFFECT-DATABASE")
        self.assertNotIn("postgres", str(error).lower())

    def test_unknown_requires_explicit_verification_action(self) -> None:
        with self.assertRaises(EffectViolation) as invalid:
            EffectView(
                effect_id=EffectId(uuid7()),
                action_intent_ref=uuid7(),
                action_intent_revision_ref=uuid7(),
                policy_decision_ref=uuid7(),
                effect_kind="creator_response",
                status=EffectStatus.UNKNOWN,
                verification_status=EffectVerificationStatus.INCONCLUSIVE,
                registered_at=Instant(datetime.now(UTC)),
                capability_kind="creator.scene.reply",
                attempt_count=1,
            )
        self.assertEqual(invalid.exception.code, "CON-EFFECT-VERIFICATION")

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

    def test_codex_effect_view_contains_only_effect_ledger_facts(self) -> None:
        view = EffectView(
            effect_id=EffectId(uuid7()),
            action_intent_ref=uuid7(),
            action_intent_revision_ref=uuid7(),
            policy_decision_ref=uuid7(),
            effect_kind="codex_delegation",
            status=EffectStatus.COMPLETED,
            verification_status=EffectVerificationStatus.VERIFIED,
            registered_at=Instant(datetime.now(UTC)),
            capability_kind="codex.delegated-work",
            attempt_count=1,
        )

        self.assertEqual(view.effect_kind, "codex_delegation")


if __name__ == "__main__":
    unittest.main()
