"""PostgreSQL reads and projections owned by the life-material module."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from uuid import UUID

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_artifact_store.life_material_codec import parse_life_material_artifact
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactViolation,
)
from armi_kernel.contracts import Instant
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
    RuntimeTransactionFailure,
)

from .api import (
    CreatorLifeMaterialItem,
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    MaterialArtifactCatalogPort,
    MaterialCandidateSource,
    MaterialCandidateSourceRef,
    MaterialLifeRecordItem,
    MaterialOpportunitySource,
    MaterialProjectionHead,
    MaterialProjectionSource,
    MaterialViolation,
)


def _metadata(value: object) -> tuple[tuple[str, str], ...]:
    if type(value) is not dict:
        raise ValueError
    return tuple(
        sorted(
            (str(key), str(item))
            for key, item in cast(dict[object, object], value).items()
        )
    )


class PostgreSQLMaterialOwner:
    __slots__ = (
        "_catalog",
        "_factory",
        "_storage",
        "_subject_id",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        catalog: MaterialArtifactCatalogPort,
        subject_id: UUID,
        data_root: Path,
        max_object_bytes: int,
    ) -> None:
        self._catalog = catalog
        self._factory = factory
        self._subject_id = subject_id
        self._storage = ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        )

    async def open(self) -> None:
        try:
            await self._storage.prepare()
        except ArtifactViolation:
            raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE") from None

    async def close(self) -> None:
        return None

    async def candidate_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        sources: tuple[MaterialCandidateSourceRef, ...],
    ) -> tuple[MaterialCandidateSource, ...]:
        result: list[MaterialCandidateSource] = []
        for source in sources:
            row = await (
                await transaction.execute(
                    """SELECT material.life_material_id,material.life_material_revision_id,
                          material.revision_no,material.owner_party_id,material.material_kind,
                          material.title,material.metadata,material.material_status,
                          material.privacy_status,material.artifact_id
                   FROM armi.life_material_revisions AS material
                   WHERE material.is_current AND material.life_material_id=%s AND material.subject_id=%s AND material.revision_no=%s
                     AND material.deleted_at IS NULL""",
                    (
                        source.material_id,
                        subject_id,
                        source.head_version,
                    ),
                )
            ).fetchone()
            if row is None:
                raise MaterialViolation("MATERIAL-SOURCE-STALE")
            artifact = await self._catalog.retained_ref_in(
                transaction, ArtifactId(row[9])
            )
            if artifact is None:
                raise MaterialViolation("MATERIAL-SOURCE-STALE")
            result.append(
                MaterialCandidateSource(
                    row[0],
                    row[1],
                    int(row[2]),
                    row[3],
                    LifeMaterialKind(str(row[4])),
                    str(row[5]),
                    _metadata(row[6]),
                    LifeMaterialStatus(str(row[7])),
                    LifeMaterialPrivacyStatus(str(row[8])),
                    artifact,
                )
            )
        return tuple(result)

    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        creator_visible_only: bool,
        query_text: str | None,
        before: tuple[Any, str, UUID] | None,
        limit: int,
    ) -> tuple[MaterialLifeRecordItem, ...]:
        rows = await (
            await transaction.execute(
                """SELECT material.life_material_id,material.title,material.created_at
                   FROM armi.life_material_revisions AS material
                   WHERE material.is_current AND material.subject_id=%s AND material.deleted_at IS NULL
                     AND (%s::text IS NULL OR material.title ILIKE '%%'||%s::text||'%%')
                     AND (%s::boolean IS FALSE OR material.privacy_status='creator_visible')
                     AND (%s::timestamptz IS NULL OR
                          (material.created_at,'material'::text,material.life_material_id)<(%s::timestamptz,%s::text,%s::uuid))
                   ORDER BY material.created_at DESC,material.life_material_id DESC LIMIT %s""",
                (
                    subject_id,
                    query_text,
                    query_text,
                    creator_visible_only,
                    None if before is None else before[0],
                    None if before is None else before[0],
                    None if before is None else before[1],
                    None if before is None else before[2],
                    limit,
                ),
            )
        ).fetchall()
        return tuple(
            MaterialLifeRecordItem(row[0], str(row[1]), row[2]) for row in rows
        )

    async def next_opportunity_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> MaterialOpportunitySource | None:
        row = await (
            await transaction.execute(
                """SELECT material.life_material_id,material.life_material_revision_id,material.revision_no
                   FROM armi.life_material_revisions AS material
                   WHERE material.is_current AND material.subject_id=%s
                     AND material.deleted_at IS NULL AND material.material_status='active'
                   ORDER BY material.updated_at,material.life_material_id LIMIT 1""",
                (subject_id,),
            )
        ).fetchone()
        return (
            None
            if row is None
            else MaterialOpportunitySource(row[0], row[1], int(row[2]))
        )

    async def get_creator_visible(
        self, material_id: UUID
    ) -> CreatorLifeMaterialItem | None:
        try:
            async with self._factory.unit_of_work(read_only=True) as unit_of_work:
                connection = unit_of_work.transaction
                row = await (
                    await connection.execute(
                        """SELECT material.life_material_id,material.life_material_revision_id,
                                  material.material_kind,material.revision_no,material.material_created_at,
                                  material.updated_at,material.revision_no,material.title,
                                  material.metadata,material.material_status,material.privacy_status,
                                  material.artifact_id
                           FROM armi.life_material_revisions AS material
                           WHERE material.is_current AND material.life_material_id=%s AND material.subject_id=%s
                             AND material.deleted_at IS NULL
                             AND material.privacy_status = 'creator_visible'""",
                        (material_id, self._subject_id),
                    )
                ).fetchone()
                ref = (
                    None
                    if row is None
                    else await self._catalog.retained_ref(
                        unit_of_work, ArtifactId(row[11])
                    )
                )
        except MaterialViolation:
            raise
        except RuntimeTransactionFailure:
            raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE") from None
        if row is None or ref is None:
            return None
        body = ""
        try:
            if (
                ref.media_type != "application/json"
                or ref.logical_kind != "life.material.content"
                or ref.privacy_scope is not ArtifactPrivacyScope.PRIVATE
                or ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            ):
                raise ValueError
            async with await self._storage.open_verified(ref) as stream:
                body = parse_life_material_artifact(await stream.read()).decode(
                    "utf-8", errors="strict"
                )
            return CreatorLifeMaterialItem(
                row[0],
                row[1],
                LifeMaterialKind(str(row[2])),
                int(row[6]),
                int(row[3]),
                str(row[7]),
                body,
                _metadata(row[8]),
                LifeMaterialStatus(str(row[9])),
                LifeMaterialPrivacyStatus(str(row[10])),
                Instant(row[4]),
                Instant(row[5]),
            )
        except ArtifactViolation, TypeError, ValueError, UnicodeError:
            raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE") from None

    async def projection_head_page(
        self,
        transaction: PostgreSQLTransaction,
        *,
        after_material_id: UUID | None,
        limit: int = 256,
    ) -> tuple[MaterialProjectionHead, ...]:
        rows = await (
            await transaction.execute(
                """SELECT material.subject_id,material.life_material_id,material.revision_no
                   FROM armi.life_material_revisions AS material
                   WHERE material.is_current AND material.deleted_at IS NULL
                     AND material.revision_kind<>'deleted'
                     AND (%s::uuid IS NULL OR material.life_material_id>%s)
                   ORDER BY material.life_material_id LIMIT %s""",
                (after_material_id, after_material_id, limit),
            )
        ).fetchall()
        return tuple(
            MaterialProjectionHead(row[0], row[1], int(row[2])) for row in rows
        )

    async def filter_current_projection_heads(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        sources: tuple[MaterialCandidateSourceRef, ...],
    ) -> tuple[MaterialCandidateSourceRef, ...]:
        if not sources:
            return ()
        rows = await (
            await transaction.execute(
                """WITH requested AS (
                     SELECT material_id,head_version,ordinal
                     FROM unnest(%s::uuid[],%s::bigint[]) WITH ORDINALITY
                       AS source(material_id,head_version,ordinal)
                   )
                   SELECT requested.material_id,requested.head_version
                   FROM requested
                   JOIN armi.life_material_revisions AS material
                     ON material.life_material_id=requested.material_id
                    AND material.revision_no=requested.head_version
                   WHERE material.is_current AND material.subject_id=%s
                     AND material.deleted_at IS NULL
                     AND material.revision_kind<>'deleted'
                   ORDER BY requested.ordinal""",
                (
                    [source.material_id for source in sources],
                    [source.head_version for source in sources],
                    subject_id,
                ),
            )
        ).fetchall()
        return tuple(MaterialCandidateSourceRef(row[0], int(row[1])) for row in rows)

    async def lock_current_projection_head(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        source: MaterialCandidateSourceRef,
    ) -> bool:
        await transaction.execute(
            """SELECT life_material_revision_id FROM armi.life_material_revisions
               WHERE life_material_id=%s AND revision_no=1 FOR SHARE""",
            (source.material_id,),
        )
        row = await (
            await transaction.execute(
                """SELECT material.life_material_id
                   FROM armi.life_material_revisions AS material
                   WHERE material.is_current AND material.life_material_id=%s AND material.revision_no=%s
                     AND material.subject_id=%s
                     AND material.deleted_at IS NULL
                     AND material.revision_kind<>'deleted'""",
                (
                    source.material_id,
                    source.head_version,
                    subject_id,
                ),
            )
        ).fetchone()
        return row is not None

    async def projection_sources(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID | None = None,
    ) -> tuple[MaterialProjectionSource, ...]:
        rows = await (
            await transaction.execute(
                """SELECT material.life_material_id FROM armi.life_material_revisions AS material
                   WHERE material.is_current AND material.deleted_at IS NULL AND material.revision_kind<>'deleted'
                     AND (%s::uuid IS NULL OR material.subject_id=%s)
                   ORDER BY material.life_material_id""",
                (subject_id, subject_id),
            )
        ).fetchall()
        sources: list[MaterialProjectionSource] = []
        for row in rows:
            source = await self.load_source(transaction, row[0])
            if source is not None:
                sources.append(source)
        return tuple(sources)

    async def load_source(
        self, transaction: PostgreSQLTransaction, material_id: UUID
    ) -> MaterialProjectionSource | None:
        row = await (
            await transaction.execute(
                """SELECT material.subject_id,material.life_material_id,
                          material.life_material_revision_id,material.revision_no,material.owner_party_id,
                          material.material_kind,material.title,material.metadata,material.material_status,
                          material.privacy_status,material.artifact_id
                   FROM armi.life_material_revisions AS material
                   WHERE material.is_current AND material.life_material_id=%s AND material.deleted_at IS NULL
                     AND material.revision_kind<>'deleted'""",
                (material_id,),
            )
        ).fetchone()
        if row is None:
            return None
        artifact = await self._catalog.retained_ref_in(transaction, ArtifactId(row[10]))
        if artifact is None:
            raise MaterialViolation("MATERIAL-SOURCE-STALE")
        return MaterialProjectionSource(
            row[0],
            row[1],
            row[2],
            int(row[3]),
            row[4],
            LifeMaterialKind(str(row[5])),
            str(row[6]),
            _metadata(row[7]),
            LifeMaterialStatus(str(row[8])),
            LifeMaterialPrivacyStatus(str(row[9])),
            artifact,
        )


__all__ = ("PostgreSQLMaterialOwner",)
