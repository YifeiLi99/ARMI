from __future__ import annotations

import asyncio
import unittest

from armi_kernel.application import RuntimeInstanceId
from armi_runtime.composition.authority import RuntimeAuthorityController
from armi_runtime.composition.supervisor import RuntimeSupervisor

from tests.runtime.test_runtime_authority import _AuthorityPort


class RuntimeSupervisorTests(unittest.TestCase):
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
