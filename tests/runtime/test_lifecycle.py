from __future__ import annotations

import unittest
from datetime import UTC, datetime

from armi_runtime.composition.lifecycle import (
    RUNTIME_BLOCKING_REASONS,
    LifecycleController,
)
from armi_runtime.composition.runtime_errors import RuntimeViolation
from armi_runtime.interfaces.creator_contract import Readiness, RuntimeState

ENVIRONMENT_ID = "01980f7d-7b8f-7e2a-8a11-2ab8e1234567"
OBSERVED = datetime(2026, 7, 29, 1, 2, 3, 456789, tzinfo=UTC)


class LifecycleTests(unittest.TestCase):
    def test_explicit_blocker_still_prevents_readiness(self) -> None:
        lifecycle = LifecycleController(
            environment_id=ENVIRONMENT_ID,
            clock=lambda: OBSERVED,
        )

        starting = lifecycle.start()
        blocked = lifecycle.block(("TEST_BLOCKER",))
        draining = lifecycle.drain()
        stopped = lifecycle.stop()

        self.assertEqual(starting.runtime_state, RuntimeState.STARTING)
        self.assertEqual(blocked.runtime_state, RuntimeState.BLOCKED)
        self.assertEqual(blocked.readiness, Readiness.NOT_READY)
        self.assertEqual(blocked.reason_codes, ("TEST_BLOCKER",))
        self.assertEqual(draining.runtime_state, RuntimeState.DRAINING)
        self.assertEqual(stopped.runtime_state, RuntimeState.STOPPED)
        self.assertEqual(stopped.observed_at, "2026-07-29T01:02:03.456789Z")

    def test_illegal_transition_has_stable_code(self) -> None:
        lifecycle = LifecycleController(environment_id=ENVIRONMENT_ID)
        with self.assertRaises(RuntimeViolation) as raised:
            lifecycle.block()
        self.assertEqual(raised.exception.code, "LIFE-TRANSITION")

    def test_recovery_completes_ready_after_s018_capability_is_available(self) -> None:
        lifecycle = LifecycleController(environment_id=ENVIRONMENT_ID)
        lifecycle.start()
        recovering = lifecycle.begin_recovery()
        ready = lifecycle.complete_startup()

        self.assertEqual(recovering.runtime_state, RuntimeState.RECOVERING)
        self.assertEqual(recovering.readiness, Readiness.NOT_READY)
        self.assertEqual(RUNTIME_BLOCKING_REASONS, ())
        self.assertEqual(ready.runtime_state, RuntimeState.READY)
        self.assertEqual(ready.readiness, Readiness.READY)

    def test_unborn_is_explicitly_not_ready_and_can_stop(self) -> None:
        lifecycle = LifecycleController(environment_id=ENVIRONMENT_ID)
        lifecycle.start()
        unborn = lifecycle.mark_unborn()

        self.assertEqual(unborn.runtime_state, RuntimeState.UNBORN)
        self.assertEqual(unborn.readiness, Readiness.NOT_READY)
        self.assertEqual(unborn.reason_codes, ())
        self.assertEqual(
            lifecycle.drain().runtime_state,
            RuntimeState.DRAINING,
        )


if __name__ == "__main__":
    unittest.main()
