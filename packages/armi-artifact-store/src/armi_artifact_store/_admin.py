from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
)
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import ArtifactAdminRetirement, ArtifactAdminSnapshot
from .content_store import ContentAddressedArtifactStore


class PostgreSQLArtifactAdmin:
    __slots__ = ("_storage",)

    def __init__(self, *, artifact_root: Path, max_object_bytes: int) -> None:
        self._storage = ContentAddressedArtifactStore(
            artifact_root, max_object_bytes=max_object_bytes
        )

    def snapshot(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> ArtifactAdminSnapshot | None:
        row = transaction.execute(
            "SELECT a.artifact_id,o.content_digest,o.byte_size,a.media_type,a.logical_kind,"
            "a.privacy_scope,o.integrity_status FROM armi.artifacts a "
            "JOIN armi.artifact_objects o USING (artifact_object_id) WHERE a.artifact_id=%s",
            (artifact_id,),
        ).fetchone()
        return (
            None
            if row is None
            else ArtifactAdminSnapshot(
                artifact_id=cast(UUID, row[0]),
                content_digest=str(row[1]),
                byte_size=int(cast(int, row[2])),
                media_type=str(row[3]),
                logical_kind=str(row[4]),
                privacy_scope=ArtifactPrivacyScope(str(row[5])),
                integrity_status=ArtifactIntegrityStatus(str(row[6])),
            )
        )

    def read_verified_bytes(self, snapshot: ArtifactAdminSnapshot) -> bytes:
        return self._storage.read_verified_bytes(
            ArtifactRef(
                artifact_id=ArtifactId(snapshot.artifact_id),
                content_digest=Digest(snapshot.content_digest),
                byte_size=snapshot.byte_size,
                media_type=snapshot.media_type,
                logical_kind=snapshot.logical_kind,
                privacy_scope=snapshot.privacy_scope,
                integrity_status=snapshot.integrity_status,
            )
        )

    def delete(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        artifact_id: UUID,
        deletion_id: UUID | None = None,
    ) -> ArtifactAdminRetirement:
        row = transaction.execute(
            """UPDATE armi.artifacts SET retention_status='deleted',
                      deleted_at=clock_timestamp()
               WHERE artifact_id=%s AND retention_status='retained'
               RETURNING artifact_object_id,object_generation,producer_trace_id""",
            (artifact_id,),
        ).fetchone()
        if row is None:
            return ArtifactAdminRetirement(False, None, False)
        object_id = cast(UUID, row[0])
        generation = int(cast(int, row[1]))
        trace_id = cast(UUID, row[2])
        retained = transaction.execute(
            """SELECT count(*) FROM armi.artifacts
               WHERE artifact_object_id=%s AND object_generation=%s
                 AND retention_status='retained'""",
            (object_id, generation),
        ).fetchone()
        if retained is None:
            raise RuntimeError("artifact reference count query returned no row")
        if int(cast(int, retained[0])) != 0:
            return ArtifactAdminRetirement(True, None, True, object_id)
        cleanup_id = deletion_id or uuid7()
        inserted = transaction.execute(
            """INSERT INTO armi.artifact_object_deletions
                   (artifact_object_deletion_id,artifact_object_id,
                    object_generation,status)
                   VALUES (%s,%s,%s,'ready')
                   ON CONFLICT (artifact_object_id,object_generation) DO UPDATE
                   SET updated_at=armi.artifact_object_deletions.updated_at
                   RETURNING artifact_object_deletion_id""",
            (cleanup_id, object_id, generation),
        ).fetchone()
        if inserted is None:
            raise RuntimeError("artifact deletion responsibility was not returned")
        cleanup_id = cast(UUID, inserted[0])
        digest_row = transaction.execute(
            "SELECT content_digest FROM armi.artifact_objects WHERE artifact_object_id=%s",
            (object_id,),
        ).fetchone()
        if digest_row is None:
            raise RuntimeError("artifact object was not returned")
        return ArtifactAdminRetirement(
            True, cleanup_id, False, object_id, str(digest_row[0]), trace_id
        )

    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]:
        rows = transaction.execute(
            "SELECT artifact_id FROM armi.artifacts WHERE artifact_id=ANY(%s::uuid[]) ORDER BY artifact_id",
            (object_ids,),
        ).fetchall()
        return tuple(cast(UUID, row[0]) for row in rows)


__all__ = ("PostgreSQLArtifactAdmin",)
