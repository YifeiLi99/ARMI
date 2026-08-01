"""Production T-05 registration worker; deliberately contains no dispatcher."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    EffectId,
    EffectView,
    EffectViolation,
    LockPlan,
    LockTarget,
    RuntimeFence,
    WorkViolation,
)

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.effect_ledger import (
    PostgreSQLEffectLedgerRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

Diagnostic = Callable[[str], None]


def _ignore_diagnostic(event: str) -> None:
    del event


class EffectRegistrationPipeline:
    __slots__ = (
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_repository",
        "_stop",
        "_storage",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._repository = PostgreSQLEffectLedgerRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic: Diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        await self._factory.open()
        await self._storage.prepare()

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def register_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind="effect.register",
                lease_owner=self._lease_owner,
                lease_seconds=30,
                limit=1,
            )
        except WorkViolation:
            raise EffectViolation("EFFECT-DATABASE") from None
        if not records:
            return False
        lease = records[0].lease
        assert lease is not None
        try:
            async with self._factory.unit_of_work(LockPlan()) as uow:
                snapshot = await self._repository.snapshot(uow, lease)
            integrity_ok = await self._verify(
                snapshot.artifact_id,
                snapshot.payload_digest.value,
                snapshot.payload_bytes,
            )
            async with self._factory.unit_of_work(LockPlan()) as uow:
                await self._repository.settle(
                    uow, lease=lease, snapshot=snapshot, integrity_ok=integrity_ok
                )
            return True
        except EffectViolation as error:
            if error.code != "EFFECT-WORK-STALE":
                self._diagnostic("effect.registration.failed")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("effect.registration.transient_failure")
            return True

    async def get_effect(
        self, effect_id: EffectId, *, creator_party_id: UUID
    ) -> EffectView:
        async with self._factory.unit_of_work(LockPlan(), read_only=True) as uow:
            return await self._repository.get_effect(uow, effect_id, creator_party_id)

    async def _verify(self, artifact_id: UUID, digest: str, size: int) -> bool:
        try:
            from armi_kernel.application import (
                ArtifactId,
                ArtifactIntegrityStatus,
                ArtifactPrivacyScope,
                ArtifactRef,
            )
            from armi_kernel.contracts import Digest

            reference = ArtifactRef(
                ArtifactId(artifact_id),
                Digest(digest),
                size,
                "text/plain",
                "creator.reply.text",
                ArtifactPrivacyScope.CREATOR_VISIBLE,
                ArtifactIntegrityStatus.VERIFIED,
                1,
            )
            stream = await self._storage.open_verified(reference)
            try:
                value = await stream.read()
            finally:
                await stream.close()
            return len(value) == size and Digest.from_bytes(value).value == digest
        except Exception:
            return False

    async def run(self) -> None:
        while not self._stop.is_set():
            if await self.register_once():
                await asyncio.sleep(0)
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1)


def build_effect_registration_pipeline(
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
    diagnostic: Diagnostic | None,
) -> EffectRegistrationPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise EffectViolation("EFFECT-LOCK")

    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        lock_acquirer=reject_dynamic_lock,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return EffectRegistrationPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        diagnostic=diagnostic,
    )


__all__ = ("EffectRegistrationPipeline", "build_effect_registration_pipeline")
