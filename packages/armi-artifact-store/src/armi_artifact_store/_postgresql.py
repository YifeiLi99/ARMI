"""PostgreSQL catalog owned by the artifact-store distribution."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactRegistration,
    ArtifactViolation,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork


class PostgreSQLArtifactCatalog:
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration:
        connection = unit_of_work.transaction
        digest_hex = published.content_digest.value.removeprefix("sha256:")
        locator = f"objects/sha256/{digest_hex[:2]}/{digest_hex[2:4]}/{digest_hex}"
        row = await (
            await connection.execute(
                """INSERT INTO armi.artifacts
                   (artifact_id,content_digest,media_type,byte_size,storage_locator,
                    logical_kind,producer_kind,producer_trace_id,privacy_scope)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (content_digest) DO NOTHING
                   RETURNING artifact_id,content_digest,byte_size,media_type,
                             logical_kind,privacy_scope,integrity_status""",
                (
                    artifact_id.value,
                    published.content_digest.value,
                    published.policy.media_type,
                    published.byte_size,
                    locator,
                    published.policy.logical_kind,
                    published.policy.producer_kind,
                    published.policy.producer_trace_id.value,
                    published.policy.privacy_scope.value,
                ),
            )
        ).fetchone()
        inserted = row is not None
        if row is None:
            row = await (
                await connection.execute(
                    """SELECT artifact_id,content_digest,byte_size,media_type,
                              logical_kind,privacy_scope,integrity_status
                       FROM armi.artifacts WHERE content_digest=%s""",
                    (published.content_digest.value,),
                )
            ).fetchone()
        if row is None:
            raise ArtifactViolation("ART-DATABASE")
        ref = _row_to_ref(row)
        if (
            ref.byte_size != published.byte_size
            or ref.media_type != published.policy.media_type
            or ref.logical_kind != published.policy.logical_kind
            or ref.privacy_scope is not published.policy.privacy_scope
        ):
            raise ArtifactViolation("ART-METADATA-CONFLICT")
        return ArtifactRegistration(ref, inserted)

    async def get(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef:
        row = await (
            await unit_of_work.transaction.execute(
                """SELECT artifact_id,content_digest,byte_size,media_type,
                          logical_kind,privacy_scope,integrity_status
                   FROM armi.artifacts WHERE artifact_id=%s""",
                (artifact_id.value,),
            )
        ).fetchone()
        if row is None:
            raise ArtifactViolation("ART-NOT-FOUND")
        return _row_to_ref(row)

    async def all_refs(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> tuple[ArtifactRef, ...]:
        rows = await (
            await unit_of_work.transaction.execute(
                """SELECT artifact_id,content_digest,byte_size,media_type,
                          logical_kind,privacy_scope,integrity_status
                   FROM armi.artifacts
                   WHERE retention_status = 'retained'
                   ORDER BY content_digest"""
            )
        ).fetchall()
        return tuple(_row_to_ref(row) for row in rows)

    async def retained_ref(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef | None:
        row = await (
            await unit_of_work.transaction.execute(
                """SELECT artifact_id,content_digest,byte_size,media_type,
                          logical_kind,privacy_scope,integrity_status
                   FROM armi.artifacts
                   WHERE artifact_id=%s AND retention_status='retained'""",
                (artifact_id.value,),
            )
        ).fetchone()
        return None if row is None else _row_to_ref(row)

    async def mark_deleted(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> bool:
        result = await unit_of_work.transaction.execute(
            """UPDATE armi.artifacts
               SET retention_status='deleted', deleted_at=statement_timestamp()
               WHERE artifact_id=%s AND retention_status='retained'""",
            (artifact_id.value,),
        )
        if result.rowcount not in (0, 1):
            raise ArtifactViolation("ART-DATABASE")
        return result.rowcount == 1

    async def mark_integrity(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        status: ArtifactIntegrityStatus,
    ) -> bool:
        if status not in {
            ArtifactIntegrityStatus.MISSING,
            ArtifactIntegrityStatus.CORRUPT,
        }:
            raise ArtifactViolation("ART-STATE")
        result = await unit_of_work.transaction.execute(
            """UPDATE armi.artifacts SET integrity_status=%s
               WHERE artifact_id=%s AND integrity_status='verified'""",
            (status.value, artifact_id.value),
        )
        if result.rowcount not in (0, 1):
            raise ArtifactViolation("ART-DATABASE")
        return result.rowcount == 1


def _row_to_ref(row: Sequence[Any]) -> ArtifactRef:
    try:
        return ArtifactRef(
            ArtifactId(row[0]),
            Digest(str(row[1])),
            int(row[2]),
            str(row[3]),
            str(row[4]),
            ArtifactPrivacyScope(str(row[5])),
            ArtifactIntegrityStatus(str(row[6])),
        )
    except ArtifactViolation, TypeError, ValueError:
        raise ArtifactViolation("ART-DATABASE") from None


__all__ = ("PostgreSQLArtifactCatalog",)
