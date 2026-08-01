from __future__ import annotations

import unittest
from datetime import UTC, datetime
from uuid import uuid4, uuid7

from armi_kernel.application import (
    EffectId,
    EffectStatus,
    EffectVerificationStatus,
    EffectView,
    EffectViolation,
    PolicyDecisionId,
    PolicyDecisionOutcome,
)
from armi_kernel.contracts import Instant


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
            )
        self.assertEqual(state.exception.code, "CON-EFFECT-STATE")

    def test_error_is_redacted(self) -> None:
        error = EffectViolation("EFFECT-DATABASE")
        self.assertNotIn("postgres", str(error).lower())


if __name__ == "__main__":
    unittest.main()
