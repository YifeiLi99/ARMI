"""Production S028 response admission worker with no external effect authority."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_kernel.application import (
    ResponseViolation,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)

from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.response_admission import (
    PostgreSQLResponseAdmissionRepository,
    ResponseAdmissionSnapshot,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import EFFECT_REGISTER, RESPONSE_ADMIT, WorkWakeupBus

_WORK_KIND = "cognition.response.admit"
_LEASE_SECONDS = 30
Diagnostic = Callable[[str], None]


def _ignore_diagnostic(event: str) -> None:
    del event


class ResponseAdmissionPipeline:
    __slots__ = (
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_repository",
        "_stop",
        "_storage",
        "_wakeups",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._repository = PostgreSQLResponseAdmissionRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
        self._diagnostic: Diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        await self._factory.open()
        await self._storage.prepare()

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def admit_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=_LEASE_SECONDS,
                limit=1,
            )
        except WorkViolation:
            raise ResponseViolation("RESPONSE-DATABASE") from None
        if not records:
            return False
        lease = cast(WorkLease, records[0].lease)
        snapshot: ResponseAdmissionSnapshot | None = None
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                snapshot = await self._repository.snapshot(unit_of_work, lease)
            integrity_ok = await self._verify(snapshot)
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.settle(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    integrity_ok=integrity_ok,
                )
            self._wakeups.notify(EFFECT_REGISTER)
            return True
        except ResponseViolation as error:
            if error.code == "RESPONSE-WORK-STALE":
                return True
            self._diagnostic("response.admission.failed")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("response.admission.transient_failure")
            return True

    async def _verify(self, snapshot: ResponseAdmissionSnapshot) -> bool:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.artifact)
            async with stream:
                value = await stream.read()
        except Exception as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            return False
        return len(value) == snapshot.content_bytes

    async def run_worker(self) -> None:
        observed = self._wakeups.version(RESPONSE_ADMIT)
        while not self._stop.is_set():
            try:
                worked = await self.admit_once()
            except ResponseViolation:
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            observed = await self._wakeups.wait(
                RESPONSE_ADMIT,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )


def build_response_admission_pipeline(
    conninfo: str,
    *,
    environment_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
) -> ResponseAdmissionPipeline:
    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return ResponseAdmissionPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


__all__ = ("ResponseAdmissionPipeline", "build_response_admission_pipeline")
