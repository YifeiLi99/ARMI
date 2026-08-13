from pathlib import Path
from typing import cast
from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
)
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLAdminTransaction

from .api import ArtifactAdminSnapshot, ArtifactBackupSnapshot
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
            "SELECT artifact_id,content_digest,byte_size,media_type,logical_kind,"
            "privacy_scope,integrity_status FROM armi.artifacts WHERE artifact_id=%s",
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

    def retained_verified(
        self, transaction: PostgreSQLAdminTransaction
    ) -> tuple[ArtifactBackupSnapshot, ...]:
        rows = transaction.execute(
            """SELECT artifact_id,content_digest,byte_size,storage_locator
               FROM armi.artifacts
               WHERE retention_status='retained' AND integrity_status='verified'
               ORDER BY content_digest,artifact_id"""
        ).fetchall()
        return tuple(
            ArtifactBackupSnapshot(
                artifact_id=cast(UUID, row[0]),
                content_digest=str(row[1]),
                byte_size=int(cast(int, row[2])),
                storage_locator=str(row[3]),
            )
            for row in rows
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
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> bool:
        return (
            transaction.execute(
                "DELETE FROM armi.artifacts WHERE artifact_id=%s", (artifact_id,)
            ).rowcount
            == 1
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
