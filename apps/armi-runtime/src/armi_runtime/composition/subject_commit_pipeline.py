"""Production M0-S026 T-03 subject commit pipeline."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    CreatorEventResourceKind,
    CreatorEventViolation,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    LockPlan,
    LockTarget,
    RuntimeFence,
    SceneKey,
    SubjectCommitResult,
    SubjectCommitViolation,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Instant

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
from armi_runtime.adapters.persistence.durable_work import PostgreSQLDurableWorkGateway
from armi_runtime.adapters.persistence.subject_commit import (
    PostgreSQLSubjectCommitRepository,
    SubjectCommitSnapshot,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .subject_commit_contract import parse_subject_change_set

_WORK_KIND = "cognition.subject.commit"
_LEASE_SECONDS = 30
Diagnostic = Callable[[str], None]


def _ignore_diagnostic(_event: str) -> None:
    return None


class SubjectCommitPipeline:
    """Apply validated ChangeSets through the sole T-03 coordinator."""

    __slots__ = (
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_notifier",
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
        notifier: CreatorProjectionNotifier | None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._notifier = notifier
        self._repository = PostgreSQLSubjectCommitRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except DatabaseTransactionError:
            raise SubjectCommitViolation("SUBJECT-DATABASE") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def commit_once(self) -> bool:
        snapshot: SubjectCommitSnapshot | None = None
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=_LEASE_SECONDS,
                limit=1,
            )
        except WorkViolation:
            raise SubjectCommitViolation("SUBJECT-DATABASE") from None
        if not records:
            return False
        lease = records[0].lease
        assert lease is not None
        try:
            snapshot = await self._snapshot(lease)
            change_set = parse_subject_change_set(await self._read(snapshot))
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                result = await self._repository.settle(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    change_set=change_set,
                )
            if result.subject_commit_id is not None:
                await self._notify(snapshot.scene_key)
            return True
        except SubjectCommitViolation as error:
            if error.code in {
                "SUBJECT-WORK-STALE",
                "SUBJECT-HEAD-STALE",
                "SUBJECT-CAS-STALE",
            }:
                self._diagnostic("subject_commit.work.stale")
                return True
            await self._release(lease, error.code)
            return True
        except DatabaseTransactionError as error:
            if error.code == "DB-TX-COMMIT-UNKNOWN" and snapshot is not None:
                recovered = await self._recover_committed(snapshot)
                if recovered is not None:
                    if recovered.subject_commit_id is not None:
                        await self._notify(snapshot.scene_key)
                    return True
                self._diagnostic("subject_commit.commit.outcome_unknown")
                return True
            self._diagnostic("subject_commit.worker.transient_failure")
            return True
        except WorkViolation:
            self._diagnostic("subject_commit.worker.transient_failure")
            return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                worked = await self.commit_once()
            except SubjectCommitViolation:
                self._diagnostic("subject_commit.worker.failed")
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1)

    async def _snapshot(self, lease: WorkLease) -> SubjectCommitSnapshot:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._repository.snapshot(unit_of_work, lease)
        except DatabaseTransactionError:
            raise SubjectCommitViolation("SUBJECT-DATABASE") from None

    async def _read(self, snapshot: SubjectCommitSnapshot) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.change_set_artifact)
            async with stream:
                value = await stream.read()
        except Exception as error:
            if isinstance(error, asyncio.CancelledError):
                raise
            raise SubjectCommitViolation("SUBJECT-CHANGE-SET-ARTIFACT") from None
        if (
            not value
            or snapshot.change_set_digest != snapshot.change_set_artifact.content_digest
        ):
            raise SubjectCommitViolation("SUBJECT-CHANGE-SET-ARTIFACT")
        return value

    async def _release(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                row = await (
                    await unit_of_work._connection_for_repository().execute(  # pyright: ignore[reportPrivateUsage]
                        "SELECT statement_timestamp()"
                    )
                ).fetchone()
                if row is None:
                    return
                await unit_of_work.work.release(
                    lease,
                    not_before=Instant(row[0]),
                    error_code=code,
                )
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("subject_commit.settlement.deferred")

    async def _recover_committed(
        self, snapshot: SubjectCommitSnapshot
    ) -> SubjectCommitResult | None:
        try:
            async with self._factory.unit_of_work(
                LockPlan(), read_only=True
            ) as unit_of_work:
                return await self._repository.existing_result(
                    unit_of_work, snapshot.validation_id
                )
        except DatabaseTransactionError:
            return None

    async def _notify(self, scene_key: str) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorEventResourceKind.SCENE_TIMELINE,
                    SceneKey(scene_key),
                    Instant(datetime.now(UTC)),
                )
            )
        except CreatorEventViolation:
            self._diagnostic("subject_commit.notification.failed")


def build_subject_commit_pipeline(
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
    notifier: CreatorProjectionNotifier | None,
    diagnostic: Diagnostic | None,
) -> SubjectCommitPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise SubjectCommitViolation("SUBJECT-LOCK")

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
    return SubjectCommitPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        notifier=notifier,
        diagnostic=diagnostic,
    )


__all__ = ("SubjectCommitPipeline", "build_subject_commit_pipeline")
