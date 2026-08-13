"""PostgreSQL reads and projections owned by the life-material module."""

from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_artifact_store.life_material_codec import parse_life_material_artifact
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
)
from armi_kernel.contracts import Digest, Instant
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
    MaterialCandidateSource,
    MaterialLifeRecordItem,
    MaterialOpportunitySource,
    MaterialProjectionSource,
    MaterialViolation,
    RecalledMaterials,
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


def _artifact(row: tuple[Any, ...], offset: int) -> ArtifactRef:
    return ArtifactRef(
        ArtifactId(row[offset]),
        Digest(str(row[offset + 1])),
        int(row[offset + 2]),
        str(row[offset + 3]),
        str(row[offset + 4]),
        ArtifactPrivacyScope(str(row[offset + 5])),
        ArtifactIntegrityStatus(str(row[offset + 6])),
    )


class PostgreSQLMaterialOwner:
    __slots__ = (
        "_creator_party_id",
        "_factory",
        "_storage",
    )

    def __init__(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        creator_party_id: UUID,
        data_root: Path,
        max_object_bytes: int,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._factory = factory
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
        generation_id: UUID,
        episode_id: UUID,
    ) -> tuple[MaterialCandidateSource, ...]:
        rows = await (
            await transaction.execute(
                """SELECT material.life_material_id,material.current_revision_id,
                          material.head_version,material.owner_party_id,material.material_kind,
                          revision.title,revision.metadata,revision.material_status,
                          revision.privacy_status,artifact.artifact_id,artifact.content_digest,
                          artifact.byte_size,artifact.media_type,artifact.logical_kind,
                          artifact.privacy_scope,artifact.integrity_status
                   FROM armi.cognitive_context_items AS item
                   JOIN armi.life_materials AS material
                     ON material.life_material_id=item.source_ref AND material.subject_id=%s
                    AND material.life_generation_id=%s AND material.head_version=item.source_version
                    AND material.deleted_at IS NULL
                   JOIN armi.life_material_revisions AS revision
                     ON revision.life_material_revision_id=material.current_revision_id
                   JOIN armi.artifacts AS artifact ON artifact.artifact_id=revision.artifact_id
                   WHERE item.cognitive_episode_id=%s AND item.disposition='included'
                     AND item.section='material' AND item.item_kind='current_material'
                     AND item.source_kind='life_material' ORDER BY item.ordinal""",
                (subject_id, generation_id, episode_id),
            )
        ).fetchall()
        return tuple(
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
                _artifact(row, 9),
            )
            for row in rows
        )

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
                """SELECT material.life_material_id,revision.title,revision.created_at
                   FROM armi.life_materials AS material
                   JOIN armi.life_material_revisions AS revision
                     ON revision.life_material_revision_id=material.current_revision_id
                   WHERE material.subject_id=%s AND material.deleted_at IS NULL
                     AND (%s::text IS NULL OR revision.title ILIKE '%%'||%s::text||'%%')
                     AND (%s::boolean IS FALSE OR revision.privacy_status='creator_visible')
                     AND (%s::timestamptz IS NULL OR
                          (revision.created_at,'material'::text,material.life_material_id)<(%s::timestamptz,%s::text,%s::uuid))
                   ORDER BY revision.created_at DESC,material.life_material_id DESC LIMIT %s""",
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
        generation_id: UUID,
    ) -> MaterialOpportunitySource | None:
        row = await (
            await transaction.execute(
                """SELECT material.life_material_id,revision.life_material_revision_id,material.head_version
                   FROM armi.life_materials AS material
                   JOIN armi.life_material_revisions AS revision
                     ON revision.life_material_revision_id=material.current_revision_id
                   WHERE material.subject_id=%s AND material.life_generation_id=%s
                     AND material.deleted_at IS NULL AND revision.material_status='active'
                     AND NOT EXISTS (SELECT 1 FROM armi.opportunities AS existing
                       WHERE existing.subject_id=material.subject_id
                         AND existing.source_kind='life_material_revision'
                         AND existing.source_ref=revision.life_material_revision_id
                         AND existing.source_version=material.head_version
                         AND existing.purpose='consider_autonomous_life'
                         AND existing.reconsideration_no=0)
                   ORDER BY material.updated_at,material.life_material_id LIMIT 1""",
                (subject_id, generation_id),
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
                creator = await (
                    await connection.execute(
                        """SELECT 1 FROM armi.parties WHERE party_id=%s AND party_kind='creator'
                           AND creator_role='unique_primary_creator' AND status='active'""",
                        (self._creator_party_id,),
                    )
                ).fetchone()
                subject = await (
                    await connection.execute(
                        "SELECT subject_id FROM armi.subjects WHERE singleton_key=1"
                    )
                ).fetchone()
                if creator is None or subject is None:
                    raise MaterialViolation("MATERIAL-QUERY-NOT-AUTHORIZED")
                row = await (
                    await connection.execute(
                        """SELECT material.life_material_id,material.current_revision_id,
                                  material.material_kind,material.head_version,material.created_at,
                                  material.updated_at,revision.revision_no,revision.title,
                                  revision.metadata,revision.material_status,revision.privacy_status,
                                  artifact.artifact_id,artifact.content_digest,artifact.byte_size,
                                  artifact.media_type,artifact.logical_kind,artifact.privacy_scope,
                                  artifact.integrity_status
                           FROM armi.life_materials AS material
                           JOIN armi.life_material_revisions AS revision
                             ON revision.life_material_revision_id=material.current_revision_id
                           JOIN armi.artifacts AS artifact ON artifact.artifact_id=revision.artifact_id
                           WHERE material.life_material_id=%s AND material.subject_id=%s
                             AND material.deleted_at IS NULL
                             AND revision.privacy_status = 'creator_visible'""",
                        (material_id, subject[0]),
                    )
                ).fetchone()
        except MaterialViolation:
            raise
        except RuntimeTransactionFailure:
            raise MaterialViolation("MATERIAL-QUERY-UNAVAILABLE") from None
        if row is None:
            return None
        body = ""
        try:
            ref = _artifact(row, 11)
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

    async def next_missing_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        model_binding: str,
        work_kind: str,
    ) -> MaterialProjectionSource | None:
        row = await (
            await transaction.execute(
                """SELECT material.life_material_id FROM armi.life_materials AS material
                   JOIN armi.life_material_revisions AS revision
                     ON revision.life_material_revision_id=material.current_revision_id
                   WHERE material.deleted_at IS NULL AND revision.revision_kind<>'deleted'
                     AND NOT EXISTS (SELECT 1 FROM armi.context_embedding_projections AS projection
                       WHERE projection.source_kind='life_material'
                         AND projection.source_ref=material.life_material_id
                         AND projection.source_version=material.head_version
                         AND projection.model_binding=%s)
                     AND NOT EXISTS (SELECT 1 FROM armi.durable_work AS work
                       WHERE work.owner_kind='life_material' AND work.owner_ref=material.life_material_id
                         AND work.work_kind=%s AND work.status IN ('ready','leased'))
                   ORDER BY material.life_material_id LIMIT 1""",
                (model_binding, work_kind),
            )
        ).fetchone()
        return None if row is None else await self.load_source(transaction, row[0])

    async def load_source(
        self, transaction: PostgreSQLTransaction, material_id: UUID
    ) -> MaterialProjectionSource | None:
        row = await (
            await transaction.execute(
                """SELECT material.subject_id,material.life_generation_id,material.life_material_id,
                          material.current_revision_id,material.head_version,material.owner_party_id,
                          material.material_kind,revision.title,revision.metadata,revision.material_status,
                          revision.privacy_status,artifact.artifact_id,artifact.content_digest,
                          artifact.byte_size,artifact.media_type,artifact.logical_kind,
                          artifact.privacy_scope,artifact.integrity_status
                   FROM armi.life_materials AS material
                   JOIN armi.life_material_revisions AS revision
                     ON revision.life_material_revision_id=material.current_revision_id
                   JOIN armi.artifacts AS artifact ON artifact.artifact_id=revision.artifact_id
                   WHERE material.life_material_id=%s AND material.deleted_at IS NULL
                     AND revision.revision_kind<>'deleted'""",
                (material_id,),
            )
        ).fetchone()
        return (
            None
            if row is None
            else MaterialProjectionSource(
                row[0],
                row[1],
                row[2],
                row[3],
                int(row[4]),
                row[5],
                LifeMaterialKind(str(row[6])),
                str(row[7]),
                _metadata(row[8]),
                LifeMaterialStatus(str(row[9])),
                LifeMaterialPrivacyStatus(str(row[10])),
                _artifact(row, 11),
            )
        )

    async def recall(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        generation_id: UUID,
        model_binding: str,
        query_vector: tuple[float, ...],
        minimum_similarity: float,
        limit: int,
    ) -> RecalledMaterials:
        vector = "[" + ",".join(format(item, ".17g") for item in query_vector) + "]"
        rows = await (
            await transaction.execute(
                """SELECT projection.source_ref,projection.source_version,
                          projection.chunk_ordinal,projection.chunk_text,
                          1-(projection.embedding OPERATOR(armi_extensions.<=>)
                             %s::armi_extensions.vector) AS similarity
                   FROM armi.context_embedding_projections AS projection
                   JOIN armi.life_materials AS material
                     ON projection.source_kind='life_material'
                    AND material.life_material_id=projection.source_ref
                    AND material.head_version=projection.source_version
                    AND material.deleted_at IS NULL
                   WHERE projection.subject_id=%s AND projection.life_generation_id=%s
                     AND projection.model_binding=%s
                     AND 1-(projection.embedding OPERATOR(armi_extensions.<=>)
                             %s::armi_extensions.vector)>=%s
                   ORDER BY similarity DESC,projection.source_ref,projection.chunk_ordinal LIMIT 32""",
                (
                    vector,
                    subject_id,
                    generation_id,
                    model_binding,
                    vector,
                    minimum_similarity,
                ),
            )
        ).fetchall()
        missing = await (
            await transaction.execute(
                """SELECT EXISTS (SELECT 1 FROM armi.life_materials AS material
                   WHERE material.subject_id=%s AND material.life_generation_id=%s
                     AND material.deleted_at IS NULL
                     AND NOT EXISTS (SELECT 1 FROM armi.context_embedding_projections AS projection
                       WHERE projection.source_kind='life_material'
                         AND projection.source_ref=material.life_material_id
                         AND projection.source_version=material.head_version
                         AND projection.model_binding=%s))""",
                (subject_id, generation_id, model_binding),
            )
        ).fetchone()
        groups: dict[UUID, list[tuple[int, str, float, int]]] = {}
        for source_ref, version, ordinal, text, similarity in rows:
            groups.setdefault(source_ref, []).append(
                (int(ordinal), str(text), float(similarity), int(version))
            )
        values: list[tuple[UUID, int, str, float]] = []
        ordered = sorted(
            groups.items(),
            key=lambda item: max(chunk[2] for chunk in item[1]),
            reverse=True,
        )
        for source_ref, chunks in ordered[:limit]:
            best = max(chunks, key=lambda item: item[2])
            adjacent = sorted(
                (item for item in chunks if abs(item[0] - best[0]) <= 1),
                key=lambda item: item[0],
            )
            merged = adjacent[0][1]
            for previous, current in pairwise(adjacent):
                merged += current[1][min(150, len(previous[1]), len(current[1])) :]
            values.append((source_ref, best[3], merged, best[2]))
        return RecalledMaterials(tuple(values), bool(missing and missing[0]))


__all__ = ("PostgreSQLMaterialOwner",)
