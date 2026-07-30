from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4, uuid7

from armi_kernel.application import (
    RuntimeAuthorityRecord,
    RuntimeAuthorityStatus,
    RuntimeAuthorityViolation,
    RuntimeFence,
    RuntimeInstanceId,
)
from armi_runtime.composition.authority import (
    LocalAuthorityState,
    RuntimeAuthorityController,
)


def _record(
    *,
    status: RuntimeAuthorityStatus = RuntimeAuthorityStatus.ACTIVE,
) -> RuntimeAuthorityRecord:
    now = datetime.now(UTC)
    stopped_at = None if status is RuntimeAuthorityStatus.ACTIVE else now
    return RuntimeAuthorityRecord(
        fence=RuntimeFence(
            RuntimeInstanceId(uuid7()),
            uuid7(),
            uuid7(),
            uuid7(),
            1,
        ),
        status=status,
        started_at=now,
        last_heartbeat_at=now,
        lease_expires_at=now + timedelta(seconds=30),
        stopped_at=stopped_at,
    )


class _AuthorityPort:
    def __init__(self) -> None:
        self.record = _record()
        self.heartbeat_results: list[
            RuntimeAuthorityRecord | RuntimeAuthorityViolation
        ] = []

    async def acquire(
        self,
        *,
        runtime_instance_id: RuntimeInstanceId,
        lease_seconds: int,
    ) -> RuntimeAuthorityRecord:
        del lease_seconds
        self.record = RuntimeAuthorityRecord(
            fence=RuntimeFence(
                runtime_instance_id,
                self.record.fence.subject_id,
                self.record.fence.life_generation_id,
                self.record.fence.bundle_activation_id,
                self.record.fence.fence_token,
            ),
            status=self.record.status,
            started_at=self.record.started_at,
            last_heartbeat_at=self.record.last_heartbeat_at,
            lease_expires_at=self.record.lease_expires_at,
        )
        return self.record

    async def heartbeat(
        self,
        fence: RuntimeFence,
        *,
        lease_seconds: int,
    ) -> RuntimeAuthorityRecord:
        del fence, lease_seconds
        if self.heartbeat_results:
            result = self.heartbeat_results.pop(0)
            if isinstance(result, RuntimeAuthorityViolation):
                raise result
            self.record = result
        return self.record

    async def release(self, fence: RuntimeFence) -> RuntimeAuthorityRecord:
        del fence
        self.record = _record(status=RuntimeAuthorityStatus.STOPPED)
        return self.record


class RuntimeAuthorityContractTests(unittest.TestCase):
    def test_contract_requires_uuid7_positive_fence_and_consistent_state(self) -> None:
        with self.assertRaises(RuntimeAuthorityViolation):
            RuntimeInstanceId(uuid4())
        with self.assertRaises(RuntimeAuthorityViolation):
            RuntimeFence(RuntimeInstanceId(uuid7()), uuid7(), uuid7(), uuid7(), 0)
        with self.assertRaises(RuntimeAuthorityViolation):
            RuntimeAuthorityRecord(
                fence=_record().fence,
                status=RuntimeAuthorityStatus.ACTIVE,
                started_at=datetime.now(UTC),
                last_heartbeat_at=datetime.now(UTC),
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=1),
                stopped_at=datetime.now(UTC),
            )

    def test_violation_is_redacted(self) -> None:
        error = RuntimeAuthorityViolation("AUTH-DATABASE")
        self.assertEqual(error.code, "AUTH-DATABASE")
        self.assertNotIn("postgres", str(error).lower())
        self.assertNotIn("connection", str(error).lower())

    def test_first_connection_error_suspends_recovery_resumes(self) -> None:
        async def exercise() -> None:
            port = _AuthorityPort()
            controller = RuntimeAuthorityController(port, lease_seconds=30)
            await controller.acquire(RuntimeInstanceId(uuid7()))
            port.heartbeat_results = [
                RuntimeAuthorityViolation("AUTH-DATABASE"),
                port.record,
            ]
            first = await controller.heartbeat_once()
            self.assertEqual(first.state, LocalAuthorityState.SUSPENDED)
            self.assertFalse(first.writable)
            with self.assertRaises(RuntimeAuthorityViolation) as suspended:
                controller.require_writable()
            self.assertEqual(suspended.exception.code, "AUTH-LOCAL-SUSPENDED")
            recovered = await controller.heartbeat_once()
            self.assertEqual(recovered.state, LocalAuthorityState.ACTIVE)
            self.assertTrue(recovered.writable)

        asyncio.run(exercise())

    def test_second_connection_error_or_explicit_stale_loses_authority(self) -> None:
        async def connection_failures() -> None:
            port = _AuthorityPort()
            controller = RuntimeAuthorityController(port, lease_seconds=30)
            await controller.acquire(RuntimeInstanceId(uuid7()))
            port.heartbeat_results = [
                RuntimeAuthorityViolation("AUTH-DATABASE"),
                RuntimeAuthorityViolation("AUTH-DATABASE"),
            ]
            await controller.heartbeat_once()
            with self.assertRaises(RuntimeAuthorityViolation) as lost:
                await controller.heartbeat_once()
            self.assertEqual(lost.exception.code, "AUTH-HEARTBEAT-LOST")
            self.assertEqual(
                controller.snapshot().state,
                LocalAuthorityState.LOST,
            )

        async def stale() -> None:
            port = _AuthorityPort()
            controller = RuntimeAuthorityController(port, lease_seconds=30)
            await controller.acquire(RuntimeInstanceId(uuid7()))
            port.heartbeat_results = [RuntimeAuthorityViolation("AUTH-FENCE-STALE")]
            with self.assertRaises(RuntimeAuthorityViolation) as lost:
                await controller.heartbeat_once()
            self.assertEqual(lost.exception.code, "AUTH-FENCE-STALE")
            self.assertEqual(controller.snapshot().state, LocalAuthorityState.LOST)

        asyncio.run(connection_failures())
        asyncio.run(stale())


if __name__ == "__main__":
    unittest.main()
