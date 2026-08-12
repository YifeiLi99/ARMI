"""PostgreSQL ownership for Context embedding projection and exact recall."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from itertools import pairwise
from uuid import UUID, uuid7

from armi_kernel.application import (
    EmbeddingResponse,
    RecallStatus,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId

from .context import ContextMaterialSource
from .unit_of_work import PostgreSQLUnitOfWork

_WORK_KIND = "context.embedding.project"
_EMBEDDING_BINDING_ID = "armi.embedding.volcengine-ark-doubao-vision-250615-v1"
_RECALL_MIN_SIMILARITY = 0.60
_RECALL_MEMORY_LIMIT = 4
_RECALL_MATERIAL_LIMIT = 2


@dataclass(frozen=True, slots=True)
class EmbeddingProjectionSource:
    subject_id: UUID
    life_generation_id: UUID
    source_kind: str
    source_ref: UUID
    source_version: int
    memory_text: str | None = None
    material_source: ContextMaterialSource | None = None


@dataclass(frozen=True, slots=True)
class RecalledContext:
    status: RecallStatus
    memories: tuple[tuple[UUID, int, str, float], ...]
    materials: tuple[tuple[UUID, int, str, float], ...]


class PostgreSQLContextEmbeddingRepository:
    async def enqueue_one_missing(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
    ) -> bool:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                WITH candidates AS (
                  SELECT memory.subject_id, memory.life_generation_id,
                         'subjective_memory'::text AS source_kind,
                         memory.memory_id AS source_ref,
                         memory.head_version AS source_version
                  FROM armi.subjective_memories AS memory
                  JOIN armi.subjective_memory_revisions AS revision
                    ON revision.memory_revision_id = memory.current_revision_id
                  WHERE revision.accessibility IN ('available','faded')
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.deletion_items AS deletion_item
                      WHERE deletion_item.target_kind='memory'
                        AND deletion_item.target_ref=memory.memory_id
                        AND deletion_item.result_status IN ('completed','partial')
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.context_embedding_projections AS projection
                      WHERE projection.source_kind = 'subjective_memory'
                        AND projection.source_ref = memory.memory_id
                        AND projection.source_version = memory.head_version
                        AND projection.model_binding = %s
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.durable_work AS work
                      WHERE work.owner_kind = 'subjective_memory'
                        AND work.owner_ref = memory.memory_id
                        AND work.work_kind = %s
                        AND work.status IN ('ready','leased')
                    )
                  UNION ALL
                  SELECT material.subject_id, material.life_generation_id,
                         'life_material'::text, material.life_material_id,
                         material.head_version
                  FROM armi.life_materials AS material
                  JOIN armi.life_material_revisions AS revision
                    ON revision.life_material_revision_id = material.current_revision_id
                  WHERE material.deleted_at IS NULL
                    AND revision.revision_kind <> 'deleted'
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.context_embedding_projections AS projection
                      WHERE projection.source_kind = 'life_material'
                        AND projection.source_ref = material.life_material_id
                        AND projection.source_version = material.head_version
                        AND projection.model_binding = %s
                    )
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.durable_work AS work
                      WHERE work.owner_kind = 'life_material'
                        AND work.owner_ref = material.life_material_id
                        AND work.work_kind = %s
                        AND work.status IN ('ready','leased')
                    )
                )
                SELECT subject_id, life_generation_id, source_kind,
                       source_ref, source_version, statement_timestamp()
                FROM candidates
                ORDER BY source_kind DESC, source_ref
                LIMIT 1
                """,
                (
                    _EMBEDDING_BINDING_ID,
                    _WORK_KIND,
                    _EMBEDDING_BINDING_ID,
                    _WORK_KIND,
                ),
            )
        ).fetchone()
        if row is None:
            return False
        digest = Digest.from_bytes(
            f"{row[2]}:{row[3]}:{row[4]}:{_EMBEDDING_BINDING_ID}".encode()
        )
        now = Instant(row[5])
        await unit_of_work.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                _WORK_KIND,
                WorkOwner(str(row[2]), row[3]),
                IdempotencyKey(f"embedding:{row[4]}:{_EMBEDDING_BINDING_ID}"),
                digest,
                15,
                now,
                Instant(row[5] + timedelta(seconds=3600)),
                3,
                TraceId(row[3].hex),
                SubjectId(row[0]),
                WorkPayloadRef(str(row[2]), row[3]),
            )
        )
        return True

    async def load_source(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
    ) -> EmbeddingProjectionSource | None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        work = await (
            await connection.execute(
                """
                SELECT owner_kind, owner_ref
                FROM armi.durable_work
                WHERE work_id = %s AND status = 'leased'
                  AND current_attempt_id = %s AND lease_owner = %s
                  AND lease_token = %s
                  AND lease_expires_at >= statement_timestamp()
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
            )
        ).fetchone()
        if work is None:
            return None
        if work[0] == "subjective_memory":
            row = await (
                await connection.execute(
                    """
                    SELECT memory.subject_id, memory.life_generation_id,
                           memory.memory_id, memory.head_version, revision.summary
                    FROM armi.subjective_memories AS memory
                    JOIN armi.subjective_memory_revisions AS revision
                      ON revision.memory_revision_id = memory.current_revision_id
                    WHERE memory.memory_id = %s
                      AND revision.accessibility IN ('available','faded')
                    """,
                    (work[1],),
                )
            ).fetchone()
            if row is None:
                return None
            return EmbeddingProjectionSource(
                row[0], row[1], "subjective_memory", row[2], int(row[3]), str(row[4])
            )
        row = await (
            await connection.execute(
                """
                SELECT material.subject_id, material.life_generation_id,
                       material.life_material_id, material.current_revision_id,
                       material.head_version, material.owner_party_id,
                       material.material_kind, revision.title, revision.metadata,
                       revision.material_status, revision.privacy_status,
                       artifact.artifact_id, artifact.content_digest,
                       artifact.media_type, artifact.byte_size,
                       artifact.storage_locator, artifact.logical_kind,
                       artifact.producer, artifact.created_at,
                       artifact.integrity_status, artifact.privacy_scope
                FROM armi.life_materials AS material
                JOIN armi.life_material_revisions AS revision
                  ON revision.life_material_revision_id = material.current_revision_id
                JOIN armi.artifacts AS artifact ON artifact.artifact_id = revision.artifact_id
                WHERE material.life_material_id = %s AND material.deleted_at IS NULL
                  AND revision.revision_kind <> 'deleted'
                """,
                (work[1],),
            )
        ).fetchone()
        if row is None:
            return None
        from armi_kernel.application import (  # local to keep projection SQL focused
            ArtifactId,
            ArtifactIntegrityStatus,
            ArtifactPrivacyScope,
            ArtifactRef,
        )

        ref = ArtifactRef(
            artifact_id=ArtifactId(row[11]),
            content_digest=Digest(str(row[12])),
            byte_size=int(row[14]),
            media_type=str(row[13]),
            logical_kind=str(row[16]),
            privacy_scope=ArtifactPrivacyScope(str(row[20])),
            integrity_status=ArtifactIntegrityStatus(str(row[19])),
        )
        source = ContextMaterialSource(
            ref,
            row[2],
            row[3],
            int(row[4]),
            row[5],
            str(row[6]),
            str(row[7]),
            tuple(sorted((str(k), str(v)) for k, v in row[8].items())),
            str(row[9]),
            str(row[10]),
        )
        return EmbeddingProjectionSource(
            row[0], row[1], "life_material", row[2], int(row[4]), material_source=source
        )

    async def prepare_attempt(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        source: EmbeddingProjectionSource,
        chunk_ordinal: int,
        text: str,
    ) -> UUID:
        attempt_id = uuid7()
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await connection.execute(
            """
            UPDATE armi.context_embedding_attempts
            SET status='failed', error_code='MODEL-EMBEDDING-OUTCOME-UNKNOWN',
                settled_at=statement_timestamp()
            WHERE source_kind=%s AND source_ref=%s AND source_version=%s
              AND chunk_ordinal=%s AND model_binding=%s
              AND status='dispatched'
            """,
            (
                source.source_kind,
                source.source_ref,
                source.source_version,
                chunk_ordinal,
                _EMBEDDING_BINDING_ID,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.context_embedding_attempts (
              context_embedding_attempt_id, subject_id, life_generation_id,
              source_kind, source_ref, source_version, chunk_ordinal,
              model_binding, provider_model, input_digest, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'prepared')
            """,
            (
                attempt_id,
                source.subject_id,
                source.life_generation_id,
                source.source_kind,
                source.source_ref,
                source.source_version,
                chunk_ordinal,
                _EMBEDDING_BINDING_ID,
                "doubao-embedding-vision-250615",
                Digest.from_bytes(text.encode()).value,
            ),
        )
        return attempt_id

    async def mark_dispatched(
        self, unit_of_work: PostgreSQLUnitOfWork, attempt_id: UUID
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await connection.execute(
            """
            UPDATE armi.context_embedding_attempts
            SET status='dispatched', dispatched_at=statement_timestamp()
            WHERE context_embedding_attempt_id=%s AND status='prepared'
            """,
            (attempt_id,),
        )

    async def settle_success(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        attempt_id: UUID,
        source: EmbeddingProjectionSource,
        chunk_ordinal: int,
        text: str,
        response: EmbeddingResponse,
    ) -> UUID:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        projection_id = uuid7()
        vector = "[" + ",".join(format(item, ".17g") for item in response.vector) + "]"
        await connection.execute(
            """
            UPDATE armi.context_embedding_attempts
            SET status='succeeded', provider_request_id=%s, input_tokens=%s,
                settled_at=statement_timestamp()
            WHERE context_embedding_attempt_id=%s AND status='dispatched'
            """,
            (response.provider_request_id, response.input_tokens, attempt_id),
        )
        await connection.execute(
            """
            INSERT INTO armi.context_embedding_projections (
              context_embedding_projection_id, context_embedding_attempt_id,
              subject_id, life_generation_id, source_kind, source_ref,
              source_version, chunk_ordinal, chunk_text, model_binding, embedding)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s::armi_extensions.vector)
            ON CONFLICT (source_kind, source_ref, source_version,
                         chunk_ordinal, model_binding) DO NOTHING
            """,
            (
                projection_id,
                attempt_id,
                source.subject_id,
                source.life_generation_id,
                source.source_kind,
                source.source_ref,
                source.source_version,
                chunk_ordinal,
                text,
                _EMBEDDING_BINDING_ID,
                vector,
            ),
        )
        return projection_id

    async def settle_failure(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        attempt_id: UUID,
        error_code: str,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await connection.execute(
            """
            UPDATE armi.context_embedding_attempts
            SET status='failed', error_code=%s, settled_at=statement_timestamp()
            WHERE context_embedding_attempt_id=%s AND status IN ('prepared','dispatched')
            """,
            (error_code, attempt_id),
        )

    async def recall(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        subject_id: UUID,
        life_generation_id: UUID,
        query_vector: tuple[float, ...],
    ) -> RecalledContext:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        vector = "[" + ",".join(format(item, ".17g") for item in query_vector) + "]"
        rows = await (
            await connection.execute(
                """
                SELECT projection.source_kind, projection.source_ref,
                       projection.source_version, projection.chunk_ordinal,
                       projection.chunk_text,
                       1 - (projection.embedding OPERATOR(armi_extensions.<=>)
                            %s::armi_extensions.vector) AS similarity
                FROM armi.context_embedding_projections AS projection
                LEFT JOIN armi.subjective_memories AS memory
                  ON projection.source_kind='subjective_memory'
                 AND memory.memory_id=projection.source_ref
                 AND memory.head_version=projection.source_version
                LEFT JOIN armi.subjective_memory_revisions AS memory_revision
                  ON memory_revision.memory_revision_id=memory.current_revision_id
                LEFT JOIN armi.life_materials AS material
                  ON projection.source_kind='life_material'
                 AND material.life_material_id=projection.source_ref
                 AND material.head_version=projection.source_version
                 AND material.deleted_at IS NULL
                WHERE projection.subject_id=%s
                  AND projection.life_generation_id=%s
                  AND projection.model_binding=%s
                  AND (
                    (projection.source_kind='subjective_memory'
                     AND memory_revision.accessibility IN ('available','faded')
                     AND NOT EXISTS (
                       SELECT 1 FROM armi.deletion_items AS deletion_item
                       WHERE deletion_item.target_kind='memory'
                         AND deletion_item.target_ref=memory.memory_id
                         AND deletion_item.result_status IN ('completed','partial')))
                    OR (projection.source_kind='life_material'
                        AND material.life_material_id IS NOT NULL)
                  )
                  AND 1 - (projection.embedding OPERATOR(armi_extensions.<=>)
                           %s::armi_extensions.vector) >= %s
                ORDER BY similarity DESC, projection.source_ref,
                         projection.chunk_ordinal
                LIMIT 32
                """,
                (
                    vector,
                    subject_id,
                    life_generation_id,
                    _EMBEDDING_BINDING_ID,
                    vector,
                    _RECALL_MIN_SIMILARITY,
                ),
            )
        ).fetchall()
        missing = await (
            await connection.execute(
                """
                SELECT EXISTS (
                  SELECT 1 FROM armi.subjective_memories AS memory
                  JOIN armi.subjective_memory_revisions AS revision
                    ON revision.memory_revision_id=memory.current_revision_id
                  WHERE memory.subject_id=%s AND memory.life_generation_id=%s
                    AND revision.accessibility IN ('available','faded')
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.deletion_items AS deletion_item
                      WHERE deletion_item.target_kind='memory'
                        AND deletion_item.target_ref=memory.memory_id
                        AND deletion_item.result_status IN ('completed','partial'))
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.context_embedding_projections AS projection
                      WHERE projection.source_kind='subjective_memory'
                        AND projection.source_ref=memory.memory_id
                        AND projection.source_version=memory.head_version
                        AND projection.model_binding=%s))
                OR EXISTS (
                  SELECT 1 FROM armi.life_materials AS material
                  WHERE material.subject_id=%s AND material.life_generation_id=%s
                    AND material.deleted_at IS NULL
                    AND NOT EXISTS (
                      SELECT 1 FROM armi.context_embedding_projections AS projection
                      WHERE projection.source_kind='life_material'
                        AND projection.source_ref=material.life_material_id
                        AND projection.source_version=material.head_version
                        AND projection.model_binding=%s))
                """,
                (
                    subject_id,
                    life_generation_id,
                    _EMBEDDING_BINDING_ID,
                    subject_id,
                    life_generation_id,
                    _EMBEDDING_BINDING_ID,
                ),
            )
        ).fetchone()
        memory_values: list[tuple[UUID, int, str, float]] = []
        material_groups: dict[UUID, list[tuple[int, str, float, int]]] = {}
        for source_kind, source_ref, version, ordinal, text, similarity in rows:
            score = float(similarity)
            if source_kind == "subjective_memory":
                if all(item[0] != source_ref for item in memory_values):
                    memory_values.append((source_ref, int(version), str(text), score))
            else:
                material_groups.setdefault(source_ref, []).append(
                    (int(ordinal), str(text), score, int(version))
                )
        memory_values = memory_values[:_RECALL_MEMORY_LIMIT]
        material_values: list[tuple[UUID, int, str, float]] = []
        ordered_groups = sorted(
            material_groups.items(),
            key=lambda item: max(chunk[2] for chunk in item[1]),
            reverse=True,
        )
        for source_ref, chunks in ordered_groups[:_RECALL_MATERIAL_LIMIT]:
            best = max(chunks, key=lambda item: item[2])
            adjacent = sorted(
                (item for item in chunks if abs(item[0] - best[0]) <= 1),
                key=lambda item: item[0],
            )
            merged = adjacent[0][1]
            for previous, current in pairwise(adjacent):
                overlap = min(150, len(previous[1]), len(current[1]))
                merged += current[1][overlap:]
            material_values.append((source_ref, best[3], merged, best[2]))
        if not memory_values and not material_values:
            status = (
                RecallStatus.PARTIAL
                if bool(missing and missing[0])
                else RecallStatus.NO_RELEVANT_RESULT
            )
        else:
            status = (
                RecallStatus.PARTIAL
                if bool(missing and missing[0])
                else RecallStatus.COMPLETE
            )
        return RecalledContext(status, tuple(memory_values), tuple(material_values))


__all__ = (
    "EmbeddingProjectionSource",
    "PostgreSQLContextEmbeddingRepository",
    "RecalledContext",
)
