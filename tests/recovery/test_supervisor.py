from __future__ import annotations

import asyncio
import unittest

from armi_kernel.application import RuntimeInstanceId
from armi_runtime.composition.authority import (
    LocalAuthorityState,
    RuntimeAuthorityController,
)
from armi_runtime.composition.supervisor import RuntimeSupervisor

from tests.runtime.test_runtime_authority import _AuthorityPort


class RuntimeSupervisorTests(unittest.TestCase):
    def test_unexpected_owned_task_failure_is_reported(self) -> None:
        failures: list[tuple[str, BaseException]] = []

        async def exercise() -> None:
            supervisor = RuntimeSupervisor(
                None,
                on_task_failure=lambda name, error: failures.append((name, error)),
            )

            async def fail() -> None:
                raise RuntimeError("worker failed")

            task = supervisor.start(fail(), name="failed-worker")
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                await task
            await asyncio.sleep(0)

        asyncio.run(exercise())
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0][0], "failed-worker")
        self.assertIsInstance(failures[0][1], RuntimeError)

    def test_drain_waits_owned_task_then_releases_and_stops_heartbeat(self) -> None:
        async def exercise() -> None:
            port = _AuthorityPort()
            authority = RuntimeAuthorityController(port, lease_seconds=30)
            await authority.acquire(
                RuntimeInstanceId(port.record.fence.runtime_instance_id.value)
            )
            supervisor = RuntimeSupervisor(authority)
            completed = asyncio.Event()

            async def short_transaction() -> None:
                await asyncio.sleep(0)
                self.assertIs(
                    authority.snapshot().state,
                    LocalAuthorityState.ACTIVE,
                )
                completed.set()

            async def heartbeat() -> None:
                while True:
                    await asyncio.sleep(60)

            supervisor.start(short_transaction(), name="short-transaction")
            heartbeat_task = supervisor.start(
                heartbeat(),
                name="heartbeat",
                heartbeat=True,
            )
            self.assertTrue(await supervisor.drain(deadline_seconds=1))
            self.assertTrue(completed.is_set())
            self.assertTrue(heartbeat_task.cancelled())

        asyncio.run(exercise())

    def test_deadline_cancels_owned_task_without_release(self) -> None:
        async def exercise() -> None:
            port = _AuthorityPort()
            authority = RuntimeAuthorityController(port, lease_seconds=30)
            await authority.acquire(
                RuntimeInstanceId(port.record.fence.runtime_instance_id.value)
            )
            supervisor = RuntimeSupervisor(authority)

            async def stuck() -> None:
                await asyncio.sleep(2)

            task = supervisor.start(stuck(), name="stuck")
            self.assertFalse(await supervisor.drain(deadline_seconds=1))
            self.assertTrue(task.cancelled())

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
