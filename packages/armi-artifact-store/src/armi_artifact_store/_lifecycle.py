"""Physical artifact lifecycle owned by the artifact-store boundary."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    DurableWorkPort,
    WorkOwner,
    WorkRecord,
    WorkResultRef,
    WorkType,
    WorkViolation,
)
from armi_kernel.contracts import Digest, Instant
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    RuntimeTransactionFailure,
)

from .api import ArtifactDeletionState
from .content_store import ContentAddressedArtifactStore

_DELETE_RETRY_DELAYS = (5, 15, 30, 60, 120, 300, 600)
_DETERMINISTIC_DELETE_ERRORS = {
    "ART-CORRUPT",
    "ART-DIGEST-CONFLICT",
    "ART-GENERATION-CONFLICT",
    "ART-PATH-UNSAFE",
}


class ArtifactLifecycleCoordinator:
    """Own generation-fenced physical deletion and crash recovery."""

    __slots__ = ("_factory", "_stop", "_storage", "_work", "_worker_id")

    def __init__(
        self,
        storage: ContentAddressedArtifactStore,
        unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
        durable_work: DurableWorkPort,
    ) -> None:
        self._storage = storage
        self._factory = unit_of_work_factory
        self._work = durable_work
        self._worker_id = uuid7()
        self._stop = asyncio.Event()

    async def recover(self) -> int:
        """Drain all currently claimable lifecycle work before business recovery."""

        recovered = await self._recover_publications()
        completed = 0
        while await self.run_once():
            completed += 1
        return recovered + completed

    async def _recover_publications(self) -> int:
        async with self._factory.unit_of_work(read_only=True) as unit:
            rows = await (
                await unit.transaction.execute(
                    """SELECT p.publication_id,p.artifact_object_id,
                              p.object_generation,p.status,p.expires_at,
                              o.content_digest,o.byte_size
                       FROM armi.artifact_publications p
                       JOIN armi.artifact_objects o USING (artifact_object_id)
                       WHERE p.status IN ('reserved','published')
                       ORDER BY p.created_at,p.publication_id"""
                )
            ).fetchall()
        recovered = 0
        for row in rows:
            exists = await self._storage.publication_object_exists(
                Digest(str(row[5])), int(row[6])
            )
            expired = row[4] <= datetime.now(UTC)
            if not exists and not expired:
                continue
            async with self._factory.unit_of_work() as unit:
                if exists:
                    await unit.transaction.execute(
                        """UPDATE armi.artifact_publications
                           SET status='published',
                               published_at=COALESCE(published_at,clock_timestamp())
                           WHERE publication_id=%s AND status IN ('reserved','published')""",
                        (row[0],),
                    )
                    await unit.transaction.execute(
                        """UPDATE armi.artifact_objects
                           SET object_status='available',integrity_status='verified',
                               updated_at=clock_timestamp()
                           WHERE artifact_object_id=%s AND generation=%s""",
                        (row[1], row[2]),
                    )
                else:
                    await unit.transaction.execute(
                        """UPDATE armi.artifact_publications SET status='abandoned'
                           WHERE publication_id=%s AND status='reserved'""",
                        (row[0],),
                    )
                    await unit.transaction.execute(
                        """UPDATE armi.artifact_objects o
                           SET object_status='absent',integrity_status='missing',
                               updated_at=clock_timestamp()
                           WHERE artifact_object_id=%s AND generation=%s
                             AND object_status='publishing'
                             AND NOT EXISTS (
                               SELECT 1 FROM armi.artifact_publications p
                               WHERE p.artifact_object_id=o.artifact_object_id
                                 AND p.object_generation=o.generation
                                 AND p.status IN ('reserved','published','consumed'))""",
                        (row[1], row[2]),
                    )
            recovered += 1
        return recovered

    async def run(self) -> None:
        while not self._stop.is_set():
            if not await self.run_once():
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1)

    def stop(self) -> None:
        self._stop.set()

    async def run_once(self) -> bool:
        try:
            claimed = await self._work.claim(
                work_kind=WorkType.ARTIFACT_OBJECT_DELETE,
                lease_owner=self._worker_id,
                lease_seconds=120,
            )
        except WorkViolation as error:
            raise ArtifactViolation("ART-DATABASE") from error
        if not claimed:
            return False
        record = claimed[0]
        if record.lease is None:
            raise ArtifactViolation("ART-STATE")
        prepared = await self._prepare_deletion(record)
        if prepared is None:
            await self._work.complete(
                record.lease,
                WorkResultRef("artifact_object_deletion", record.draft.owner.reference),
            )
            return True
        ref, deletion_id = prepared
        try:
            await self._storage.retire_verified(ref, deletion_id)
            await self._storage.delete_retired(ref, deletion_id)
        except ArtifactViolation as error:
            await self._settle_failure(record, error.code)
            return True
        await self._settle_success(record)
        return True

    async def deletion_states(
        self, transaction: PostgreSQLTransaction, deletion_ids: tuple[UUID, ...]
    ) -> tuple[ArtifactDeletionState, ...]:
        if not deletion_ids:
            return ()
        rows = await (
            await transaction.execute(
                """SELECT artifact_object_deletion_id,status,attempt_count,last_error_code
                   FROM armi.artifact_object_deletions
                   WHERE artifact_object_deletion_id=ANY(%s::uuid[])""",
                (list(deletion_ids),),
            )
        ).fetchall()
        return tuple(
            ArtifactDeletionState(
                deletion_id=row[0],
                status=str(row[1]),
                attempt_count=int(row[2]),
                last_error_code=None if row[3] is None else str(row[3]),
            )
            for row in rows
        )

    async def retry_blocked(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        deletion_ids: tuple[UUID, ...],
        retry_cycle: int,
    ) -> int:
        if not deletion_ids or retry_cycle < 2:
            return 0
        rows = await (
            await unit_of_work.transaction.execute(
                """UPDATE armi.artifact_object_deletions
                   SET status='ready',retry_cycle=%s,attempt_count=0,
                       last_error_code=NULL,completed_at=NULL,
                       updated_at=clock_timestamp()
                   WHERE artifact_object_deletion_id=ANY(%s::uuid[])
                     AND status='blocked'
                   RETURNING artifact_object_deletion_id""",
                (retry_cycle, list(deletion_ids)),
            )
        ).fetchall()
        for row in rows:
            deletion_id = row[0]
            now = datetime.now(UTC)
            await unit_of_work.work.successor(
                owner=WorkOwner("artifact_object_deletion", deletion_id),
                work_kind=WorkType.ARTIFACT_OBJECT_DELETE,
                not_before=Instant(now),
                deadline_at=Instant(now + timedelta(minutes=59)),
                max_attempts=8,
            )
        return len(rows)

    async def _prepare_deletion(
        self, record: WorkRecord
    ) -> tuple[ArtifactRef, UUID] | None:
        deletion_id = record.draft.owner.reference
        try:
            async with self._factory.unit_of_work() as unit:
                row = await (
                    await unit.transaction.execute(
                        """SELECT d.artifact_object_id,d.object_generation,d.status,
                                  o.generation,o.object_status,o.content_digest,o.byte_size,
                                  a.artifact_id,a.media_type,a.logical_kind,a.privacy_scope,
                                  o.integrity_status,
                                  (SELECT count(*) FROM armi.artifacts live
                                   WHERE live.artifact_object_id=d.artifact_object_id
                                     AND live.object_generation=d.object_generation
                                     AND live.retention_status='retained'),
                                  d.retry_cycle
                           FROM armi.artifact_object_deletions d
                           JOIN armi.artifact_objects o USING (artifact_object_id)
                           JOIN LATERAL (
                               SELECT artifact_id,media_type,logical_kind,privacy_scope
                               FROM armi.artifacts
                               WHERE artifact_object_id=d.artifact_object_id
                                 AND object_generation=d.object_generation
                               ORDER BY artifact_id LIMIT 1
                           ) a ON true
                           WHERE d.artifact_object_deletion_id=%s
                           FOR UPDATE OF d,o""",
                        (deletion_id,),
                    )
                ).fetchone()
                if row is None:
                    raise ArtifactViolation("ART-DATABASE")
                terminal = str(row[2]) in {"completed", "cancelled"}
                stale = int(row[1]) != int(row[3]) or int(row[12]) != 0
                if terminal or stale:
                    if not terminal:
                        await unit.transaction.execute(
                            """UPDATE armi.artifact_object_deletions
                               SET status='cancelled',completed_at=clock_timestamp(),
                                   updated_at=clock_timestamp(),
                                   last_error_code='ART-GENERATION-ADVANCED'
                               WHERE artifact_object_deletion_id=%s""",
                            (deletion_id,),
                        )
                    return None
                attempt_no = record.attempt_count
                await unit.transaction.execute(
                    """UPDATE armi.artifact_object_deletions
                       SET status='retiring',attempt_count=%s,
                           updated_at=clock_timestamp(),last_error_code=NULL
                       WHERE artifact_object_deletion_id=%s""",
                    (attempt_no, deletion_id),
                )
                await unit.transaction.execute(
                    """UPDATE armi.artifact_objects
                       SET object_status='retiring',updated_at=clock_timestamp()
                       WHERE artifact_object_id=%s AND generation=%s""",
                    (row[0], row[1]),
                )
                return (
                    ArtifactRef(
                        ArtifactId(row[7]),
                        Digest(str(row[5])),
                        int(row[6]),
                        str(row[8]),
                        str(row[9]),
                        ArtifactPrivacyScope(str(row[10])),
                        ArtifactIntegrityStatus(str(row[11])),
                    ),
                    deletion_id,
                )
        except RuntimeTransactionFailure as error:
            raise ArtifactViolation("ART-DATABASE") from error

    async def _settle_success(self, record: WorkRecord) -> None:
        if record.lease is None:
            raise ArtifactViolation("ART-STATE")
        deletion_id = record.draft.owner.reference
        try:
            async with self._factory.unit_of_work() as unit:
                result = await unit.transaction.execute(
                    """UPDATE armi.artifact_object_deletions d
                       SET status='completed',completed_at=clock_timestamp(),
                           updated_at=clock_timestamp(),last_error_code=NULL
                       FROM armi.artifact_objects o
                       WHERE d.artifact_object_deletion_id=%s
                         AND o.artifact_object_id=d.artifact_object_id
                         AND o.generation=d.object_generation
                         AND NOT EXISTS (
                             SELECT 1 FROM armi.artifacts a
                             WHERE a.artifact_object_id=d.artifact_object_id
                               AND a.object_generation=d.object_generation
                               AND a.retention_status='retained')""",
                    (deletion_id,),
                )
                if result.rowcount != 1:
                    raise ArtifactViolation("ART-GENERATION-CONFLICT")
                await unit.transaction.execute(
                    """UPDATE armi.artifact_objects o
                       SET object_status='absent',integrity_status='missing',
                           updated_at=clock_timestamp()
                       FROM armi.artifact_object_deletions d
                       WHERE d.artifact_object_deletion_id=%s
                         AND o.artifact_object_id=d.artifact_object_id
                         AND o.generation=d.object_generation""",
                    (deletion_id,),
                )
                await unit.transaction.execute(
                    """INSERT INTO armi.artifact_object_deletion_attempts
                       (artifact_object_deletion_attempt_id,
                        artifact_object_deletion_id,retry_cycle,attempt_no,
                        result_status,settled_at)
                       SELECT %s,d.artifact_object_deletion_id,d.retry_cycle,%s,
                              'completed',clock_timestamp()
                       FROM armi.artifact_object_deletions d
                       WHERE d.artifact_object_deletion_id=%s
                       ON CONFLICT (artifact_object_deletion_id,retry_cycle,attempt_no)
                       DO NOTHING""",
                    (
                        record.lease.attempt_id.value,
                        record.attempt_count,
                        deletion_id,
                    ),
                )
            await self._work.complete(
                record.lease,
                WorkResultRef("artifact_object_deletion", deletion_id),
            )
        except RuntimeTransactionFailure as error:
            raise ArtifactViolation("ART-COMMIT-UNKNOWN") from error

    async def _settle_failure(self, record: WorkRecord, error_code: str) -> None:
        if record.lease is None:
            raise ArtifactViolation("ART-STATE")
        blocked = (
            error_code in _DETERMINISTIC_DELETE_ERRORS or record.attempt_count >= 8
        )
        status = "blocked" if blocked else "retry_wait"
        attempt_status = "blocked" if blocked else "retryable"
        deletion_id = record.draft.owner.reference
        try:
            async with self._factory.unit_of_work() as unit:
                await unit.transaction.execute(
                    """UPDATE armi.artifact_object_deletions
                       SET status=%s,last_error_code=%s,updated_at=clock_timestamp(),
                           completed_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END
                       WHERE artifact_object_deletion_id=%s""",
                    (status, error_code, blocked, deletion_id),
                )
                await unit.transaction.execute(
                    """INSERT INTO armi.artifact_object_deletion_attempts
                       (artifact_object_deletion_attempt_id,
                        artifact_object_deletion_id,retry_cycle,attempt_no,
                        result_status,error_code,settled_at)
                       SELECT %s,d.artifact_object_deletion_id,d.retry_cycle,%s,
                              %s,%s,clock_timestamp()
                       FROM armi.artifact_object_deletions d
                       WHERE d.artifact_object_deletion_id=%s
                       ON CONFLICT (artifact_object_deletion_id,retry_cycle,attempt_no)
                       DO NOTHING""",
                    (
                        record.lease.attempt_id.value,
                        record.attempt_count,
                        attempt_status,
                        error_code,
                        deletion_id,
                    ),
                )
            if blocked:
                await self._work.fail(record.lease, error_code=error_code)
            else:
                delay = _DELETE_RETRY_DELAYS[record.attempt_count - 1]
                await self._work.release(
                    record.lease,
                    not_before=Instant(datetime.now(UTC) + timedelta(seconds=delay)),
                    error_code=error_code,
                )
        except (RuntimeTransactionFailure, WorkViolation) as error:
            raise ArtifactViolation("ART-DATABASE") from error


__all__ = ("ArtifactLifecycleCoordinator",)
