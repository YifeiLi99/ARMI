"""Package-private PostgreSQL artifact metadata write surface."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest

from .unit_of_work import PostgreSQLUnitOfWork

_SELECT_COLUMNS = """
    artifact_id,
    content_digest,
    byte_size,
    media_type,
    logical_kind,
    privacy_scope,
    integrity_status,
    schema_version
"""


@dataclass(frozen=True, slots=True)
class ArtifactRegistration:
    ref: ArtifactRef
    inserted: bool


class ArtifactCatalogRepository:
    """Register and read immutable metadata through an existing UoW."""

    __slots__ = ()

    async def register(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration:
        if (
            type(unit_of_work) is not PostgreSQLUnitOfWork
            or type(artifact_id) is not ArtifactId
            or type(published) is not PublishedArtifact
        ):
            raise ArtifactViolation("ART-DECLARATION")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        digest_hex = published.content_digest.value.removeprefix("sha256:")
        locator = f"objects/sha256/{digest_hex[:2]}/{digest_hex[2:4]}/{digest_hex}"
        cursor = await connection.execute(
            f"""
            INSERT INTO armi.artifacts (
                artifact_id,
                content_digest,
                media_type,
                byte_size,
                storage_locator,
                logical_kind,
                producer_kind,
                producer_trace_id,
                privacy_scope,
                schema_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_digest) DO NOTHING
            RETURNING {_SELECT_COLUMNS}
            """,
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
                published.policy.schema_version,
            ),
        )
        row = await cursor.fetchone()
        inserted = row is not None
        if row is None:
            cursor = await connection.execute(
                f"""
                SELECT {_SELECT_COLUMNS}
                FROM armi.artifacts
                WHERE content_digest = %s
                """,
                (published.content_digest.value,),
            )
            row = await cursor.fetchone()
        if row is None:
            raise ArtifactViolation("ART-DATABASE")
        ref = _row_to_ref(row)
        if (
            ref.byte_size != published.byte_size
            or ref.media_type != published.policy.media_type
            or ref.logical_kind != published.policy.logical_kind
            or ref.privacy_scope is not published.policy.privacy_scope
            or ref.schema_version != published.policy.schema_version
        ):
            raise ArtifactViolation("ART-METADATA-CONFLICT")
        return ArtifactRegistration(ref, inserted)

    async def get(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef:
        if (
            type(unit_of_work) is not PostgreSQLUnitOfWork
            or type(artifact_id) is not ArtifactId
        ):
            raise ArtifactViolation("ART-DECLARATION")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        cursor = await connection.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM armi.artifacts
            WHERE artifact_id = %s
            """,
            (artifact_id.value,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise ArtifactViolation("ART-NOT-FOUND")
        return _row_to_ref(row)

    async def all_refs(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
    ) -> tuple[ArtifactRef, ...]:
        if type(unit_of_work) is not PostgreSQLUnitOfWork:
            raise ArtifactViolation("ART-DECLARATION")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        cursor = await connection.execute(
            f"""
            SELECT {_SELECT_COLUMNS}
            FROM armi.artifacts
            ORDER BY content_digest
            """
        )
        return tuple(_row_to_ref(row) for row in await cursor.fetchall())

    async def mark_integrity(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        artifact_id: ArtifactId,
        status: ArtifactIntegrityStatus,
    ) -> bool:
        if (
            type(unit_of_work) is not PostgreSQLUnitOfWork
            or type(artifact_id) is not ArtifactId
            or status
            not in (
                ArtifactIntegrityStatus.MISSING,
                ArtifactIntegrityStatus.CORRUPT,
            )
        ):
            raise ArtifactViolation("ART-STATE")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        cursor = await connection.execute(
            """
            UPDATE armi.artifacts
            SET integrity_status = %s
            WHERE artifact_id = %s
              AND integrity_status = 'verified'
            """,
            (status.value, artifact_id.value),
        )
        if cursor.rowcount not in (0, 1):
            raise ArtifactViolation("ART-DATABASE")
        return cursor.rowcount == 1


def _row_to_ref(row: Sequence[Any]) -> ArtifactRef:
    try:
        return ArtifactRef(
            artifact_id=ArtifactId(row[0]),
            content_digest=Digest(str(row[1])),
            byte_size=int(row[2]),
            media_type=str(row[3]),
            logical_kind=str(row[4]),
            privacy_scope=ArtifactPrivacyScope(str(row[5])),
            integrity_status=ArtifactIntegrityStatus(str(row[6])),
            schema_version=int(row[7]),
        )
    except ArtifactViolation, TypeError, ValueError:
        raise ArtifactViolation("ART-DATABASE") from None


__all__ = (
    "ArtifactCatalogRepository",
    "ArtifactRegistration",
)
