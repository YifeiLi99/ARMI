"""PostgreSQL ownership for Context embedding projection and exact recall."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid7

from armi_kernel.application import (
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId
from armi_material.api import MaterialProjectionPort
from armi_memory.api import MemoryProjectionPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from ._embedding import (
    EMBEDDING_BINDING_ID,
    EMBEDDING_MODEL_ID,
    LIFE_MATERIAL_CHUNK_OVERLAP,
    RECALL_CANDIDATE_LIMIT,
    RECALL_MATERIAL_LIMIT,
    RECALL_MEMORY_LIMIT,
    RECALL_MIN_LEXICAL_SIMILARITY,
    RECALL_MIN_SIMILARITY,
    RECALL_RRF_K,
)
from ._postgresql import ContextMaterialSource
from .api import ContextProjectionSourceRef, EmbeddingResponse, RecallStatus

_WORK_KIND = "context.embedding.project"


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
    memories: tuple[RecalledItem, ...]
    materials: tuple[RecalledItem, ...]
    dense_available: bool = True


@dataclass(frozen=True, slots=True)
class RecalledItem:
    source_ref: UUID
    source_version: int
    text: str
    rank: int
    dense_similarity: float | None
    lexical_similarity: float | None


type _CandidateKey = tuple[str, UUID, int, int]


@dataclass(slots=True)
class _RecallCandidate:
    text: str
    rrf: float = 0.0
    dense: float | None = None
    lexical: float | None = None


class PostgreSQLContextEmbeddingRepository:
    def __init__(
        self, memories: MemoryProjectionPort, materials: MaterialProjectionPort
    ) -> None:
        self._memories = memories
        self._materials = materials

    async def enqueue_one_missing(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
    ) -> bool:
        connection = unit_of_work.transaction
        projected = await self._projected_source_versions(connection)
        materials = await self._materials.projection_sources(unit_of_work.transaction)
        material = next(
            (
                source
                for source in materials
                if ("life_material", source.material_id, source.head_version)
                not in projected
            ),
            None,
        )
        row: tuple[UUID, UUID, str, UUID, int, datetime] | None = None
        if material is not None:
            timestamp = await (
                await connection.execute("SELECT statement_timestamp()")
            ).fetchone()
            if timestamp is not None:
                row = (
                    material.subject_id,
                    material.generation_id,
                    "life_material",
                    material.material_id,
                    material.head_version,
                    cast(datetime, timestamp[0]),
                )
        memories = await self._memories.projection_sources(unit_of_work.transaction)
        memory = next(
            (
                source
                for source in memories
                if ("subjective_memory", source.memory_id, source.head_version)
                not in projected
            ),
            None,
        )
        if memory is not None:
            timestamp = await (
                await connection.execute("SELECT statement_timestamp()")
            ).fetchone()
            if timestamp is None:
                return False
            row = (
                memory.subject_id,
                memory.generation_id,
                "subjective_memory",
                memory.memory_id,
                memory.head_version,
                cast(datetime, timestamp[0]),
            )
        if row is None:
            return False
        digest = Digest.from_bytes(
            f"{row[2]}:{row[3]}:{row[4]}:{EMBEDDING_BINDING_ID}".encode()
        )
        now = Instant(row[5])
        await unit_of_work.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                _WORK_KIND,
                WorkOwner(str(row[2]), row[3]),
                IdempotencyKey(f"embedding:{row[4]}:{EMBEDDING_BINDING_ID}"),
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

    async def _projected_source_versions(
        self, transaction: PostgreSQLTransaction
    ) -> set[tuple[str, UUID, int]]:
        rows = await (
            await transaction.execute(
                """SELECT DISTINCT source_kind,source_ref,source_version
                   FROM armi.context_embedding_projections
                   WHERE model_binding=%s""",
                (EMBEDDING_BINDING_ID,),
            )
        ).fetchall()
        return {(str(row[0]), row[1], int(row[2])) for row in rows}

    async def _projected_requested_versions(
        self,
        transaction: PostgreSQLTransaction,
        *,
        memory_keys: tuple[tuple[UUID, int], ...],
        material_keys: tuple[tuple[UUID, int], ...],
    ) -> set[tuple[str, UUID, int]]:
        rows = await (
            await transaction.execute(
                """WITH requested AS (
                     SELECT 'subjective_memory'::text AS source_kind,
                            source_ref,source_version
                     FROM unnest(%s::uuid[],%s::bigint[])
                       AS source(source_ref,source_version)
                     UNION ALL
                     SELECT 'life_material'::text AS source_kind,
                            source_ref,source_version
                     FROM unnest(%s::uuid[],%s::bigint[])
                       AS source(source_ref,source_version)
                   )
                   SELECT DISTINCT projection.source_kind,
                                   projection.source_ref,
                                   projection.source_version
                   FROM armi.context_embedding_projections AS projection
                   JOIN requested USING (source_kind,source_ref,source_version)
                   WHERE projection.model_binding=%s""",
                (
                    [item[0] for item in memory_keys],
                    [item[1] for item in memory_keys],
                    [item[0] for item in material_keys],
                    [item[1] for item in material_keys],
                    EMBEDDING_BINDING_ID,
                ),
            )
        ).fetchall()
        return {(str(row[0]), row[1], int(row[2])) for row in rows}

    async def load_source(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        owner_kind: str,
        owner_ref: UUID,
    ) -> EmbeddingProjectionSource | None:
        if owner_kind == "subjective_memory":
            memory = await self._memories.load_source(
                unit_of_work.transaction, owner_ref
            )
            if memory is None:
                return None
            return EmbeddingProjectionSource(
                memory.subject_id,
                memory.generation_id,
                "subjective_memory",
                memory.memory_id,
                memory.head_version,
                memory.text,
            )
        if owner_kind != "life_material":
            return None
        material = await self._materials.load_source(
            unit_of_work.transaction, owner_ref
        )
        if material is None:
            return None
        source = ContextMaterialSource(
            material.artifact,
            material.material_id,
            material.current_revision_id,
            material.head_version,
            material.owner_party_id,
            material.material_kind.value,
            material.title,
            material.metadata,
            material.material_status.value,
            material.privacy_status.value,
        )
        return EmbeddingProjectionSource(
            material.subject_id,
            material.generation_id,
            "life_material",
            material.material_id,
            material.head_version,
            material_source=source,
        )

    async def prepare_attempt(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        source: EmbeddingProjectionSource,
        chunk_ordinal: int,
        text: str,
    ) -> UUID:
        attempt_id = uuid7()
        connection = unit_of_work.transaction
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
                EMBEDDING_BINDING_ID,
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
                EMBEDDING_BINDING_ID,
                EMBEDDING_MODEL_ID,
                Digest.from_bytes(text.encode()).value,
            ),
        )
        return attempt_id

    async def mark_dispatched(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, attempt_id: UUID
    ) -> None:
        connection = unit_of_work.transaction
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        attempt_id: UUID,
        source: EmbeddingProjectionSource,
        chunk_ordinal: int,
        display_text: str,
        retrieval_text: str,
        response: EmbeddingResponse,
    ) -> UUID:
        connection = unit_of_work.transaction
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
              source_version, chunk_ordinal, chunk_text, retrieval_text,
              model_binding, embedding)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
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
                display_text,
                retrieval_text,
                EMBEDDING_BINDING_ID,
                vector,
            ),
        )
        return projection_id

    async def settle_failure(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        attempt_id: UUID,
        error_code: str,
    ) -> None:
        connection = unit_of_work.transaction
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_id: UUID,
        life_generation_id: UUID,
        query_text: str,
        query_vector: tuple[float, ...] | None,
    ) -> RecalledContext:
        transaction = unit_of_work.transaction
        memories = await self._memories.projection_sources(
            transaction,
            subject_id=subject_id,
            generation_id=life_generation_id,
        )
        materials = await self._materials.projection_sources(
            transaction,
            subject_id=subject_id,
            generation_id=life_generation_id,
        )
        current_memories = {
            (source.memory_id, source.head_version): source for source in memories
        }
        current_materials = {
            (source.material_id, source.head_version): source for source in materials
        }
        memory_keys = tuple(current_memories)
        material_keys = tuple(current_materials)
        allowed_parameters = (
            [item[0] for item in memory_keys],
            [item[1] for item in memory_keys],
            [item[0] for item in material_keys],
            [item[1] for item in material_keys],
        )
        dense_rows: list[tuple[object, ...]] = []
        if query_vector is not None:
            vector = "[" + ",".join(format(item, ".17g") for item in query_vector) + "]"
            dense_rows = list(
                await (
                    await transaction.execute(
                        """WITH allowed AS (
                             SELECT 'subjective_memory'::text AS source_kind,
                                    source_ref,source_version
                             FROM unnest(%s::uuid[],%s::bigint[])
                               AS source(source_ref,source_version)
                             UNION ALL
                             SELECT 'life_material'::text AS source_kind,
                                    source_ref,source_version
                             FROM unnest(%s::uuid[],%s::bigint[])
                               AS source(source_ref,source_version)
                           ), parameters AS (
                             SELECT %s::armi_extensions.vector AS query_vector
                           )
                           SELECT projection.source_kind,projection.source_ref,
                                  projection.source_version,
                                  projection.chunk_ordinal,projection.chunk_text,
                                  1-(projection.embedding
                                     OPERATOR(armi_extensions.<=>)
                                     parameters.query_vector) AS score
                           FROM armi.context_embedding_projections AS projection
                           JOIN allowed USING (source_kind,source_ref,source_version)
                           CROSS JOIN parameters
                           WHERE projection.subject_id=%s
                             AND projection.life_generation_id=%s
                             AND projection.model_binding=%s
                           ORDER BY projection.embedding
                                      OPERATOR(armi_extensions.<=>)
                                      parameters.query_vector,
                                    projection.source_kind,
                                    projection.source_ref,
                                    projection.chunk_ordinal
                           LIMIT %s""",
                        (
                            *allowed_parameters,
                            vector,
                            subject_id,
                            life_generation_id,
                            EMBEDDING_BINDING_ID,
                            RECALL_CANDIDATE_LIMIT,
                        ),
                    )
                ).fetchall()
            )
            dense_rows = [
                row
                for row in dense_rows
                if float(cast(float, row[5])) >= RECALL_MIN_SIMILARITY
            ]
        await transaction.execute(
            "SELECT set_config('pg_trgm.word_similarity_threshold',%s,true)",
            (str(RECALL_MIN_LEXICAL_SIMILARITY),),
        )
        lexical_rows = list(
            await (
                await transaction.execute(
                    """WITH allowed AS (
                         SELECT 'subjective_memory'::text AS source_kind,
                                source_ref,source_version
                         FROM unnest(%s::uuid[],%s::bigint[])
                           AS source(source_ref,source_version)
                         UNION ALL
                         SELECT 'life_material'::text AS source_kind,
                                source_ref,source_version
                         FROM unnest(%s::uuid[],%s::bigint[])
                           AS source(source_ref,source_version)
                       )
                       SELECT projection.source_kind,projection.source_ref,
                              projection.source_version,projection.chunk_ordinal,
                              projection.chunk_text,
                              armi_extensions.word_similarity(
                                %s,projection.retrieval_text)
                                AS score
                       FROM armi.context_embedding_projections AS projection
                       JOIN allowed USING (source_kind,source_ref,source_version)
                       WHERE projection.subject_id=%s
                         AND projection.life_generation_id=%s
                         AND projection.model_binding=%s
                         AND (
                           projection.retrieval_text
                             OPERATOR(armi_extensions.%%>) %s
                           OR position(lower(%s)
                              in lower(projection.retrieval_text))>0
                         )
                         AND (
                           armi_extensions.word_similarity(
                             %s,projection.retrieval_text)>=%s
                           OR position(lower(%s)
                              in lower(projection.retrieval_text))>0
                         )
                       ORDER BY
                         (position(lower(%s)
                           in lower(projection.retrieval_text))>0) DESC,
                         score DESC,projection.source_kind,
                         projection.source_ref,projection.chunk_ordinal
                       LIMIT %s""",
                    (
                        *allowed_parameters,
                        query_text,
                        subject_id,
                        life_generation_id,
                        EMBEDDING_BINDING_ID,
                        query_text,
                        query_text,
                        query_text,
                        RECALL_MIN_LEXICAL_SIMILARITY,
                        query_text,
                        query_text,
                        RECALL_CANDIDATE_LIMIT,
                    ),
                )
            ).fetchall()
        )
        projected = await self._projected_requested_versions(
            transaction,
            memory_keys=memory_keys,
            material_keys=material_keys,
        )
        candidates: dict[_CandidateKey, _RecallCandidate] = {}
        for signal, rows in (("dense", dense_rows), ("lexical", lexical_rows)):
            for rank, row in enumerate(rows, 1):
                kind, source_ref, version, ordinal, text, score = row
                key: _CandidateKey = (
                    str(kind),
                    cast(UUID, source_ref),
                    cast(int, version),
                    cast(int, ordinal),
                )
                value = candidates.setdefault(key, _RecallCandidate(str(text)))
                if signal == "dense":
                    value.dense = float(cast(float, score))
                else:
                    value.lexical = float(cast(float, score))
                value.rrf += 1.0 / (RECALL_RRF_K + rank)
        ordered = sorted(
            candidates.items(),
            key=lambda item: (
                -item[1].rrf,
                item[0][0],
                item[0][1].hex,
                item[0][3],
            ),
        )
        memory_values: list[RecalledItem] = []
        material_best: dict[UUID, tuple[_CandidateKey, _RecallCandidate, int]] = {}
        for final_rank, (candidate_key, value) in enumerate(ordered, 1):
            kind, source_ref, version, ordinal = candidate_key
            source_key = (source_ref, version)
            if kind == "subjective_memory" and source_key in current_memories:
                if len(memory_values) < RECALL_MEMORY_LIMIT:
                    memory_values.append(
                        RecalledItem(
                            source_ref,
                            version,
                            value.text,
                            final_rank,
                            value.dense,
                            value.lexical,
                        )
                    )
            elif kind == "life_material" and source_key in current_materials:
                material_best.setdefault(
                    source_ref,
                    ((kind, source_ref, version, ordinal), value, final_rank),
                )
        material_values: list[RecalledItem] = []
        for source_ref, (best_key, value, final_rank) in list(material_best.items())[
            :RECALL_MATERIAL_LIMIT
        ]:
            _kind, _ref, version, ordinal = best_key
            adjacent_rows = await (
                await transaction.execute(
                    """SELECT chunk_ordinal,chunk_text
                       FROM armi.context_embedding_projections
                       WHERE source_kind='life_material' AND source_ref=%s
                         AND source_version=%s AND model_binding=%s
                         AND chunk_ordinal BETWEEN %s AND %s
                       ORDER BY chunk_ordinal""",
                    (
                        source_ref,
                        version,
                        EMBEDDING_BINDING_ID,
                        max(0, ordinal - 1),
                        ordinal + 1,
                    ),
                )
            ).fetchall()
            merged = ""
            previous = ""
            for _adjacent_ordinal, adjacent_text in adjacent_rows:
                current = str(adjacent_text)
                if not merged:
                    merged = current
                elif (
                    previous[-LIFE_MATERIAL_CHUNK_OVERLAP:]
                    == current[:LIFE_MATERIAL_CHUNK_OVERLAP]
                ):
                    merged += current[LIFE_MATERIAL_CHUNK_OVERLAP:]
                else:
                    merged += f"\n\n{current}"
                previous = current
            material_values.append(
                RecalledItem(
                    source_ref,
                    version,
                    merged,
                    final_rank,
                    value.dense,
                    value.lexical,
                )
            )
        missing_projection = any(
            ("subjective_memory", source.memory_id, source.head_version)
            not in projected
            for source in memories
        ) or any(
            ("life_material", source.material_id, source.head_version) not in projected
            for source in materials
        )
        dense_available = query_vector is not None
        if not memory_values and not material_values:
            status = (
                RecallStatus.PARTIAL
                if missing_projection or not dense_available
                else RecallStatus.NO_RELEVANT_RESULT
            )
        else:
            status = (
                RecallStatus.PARTIAL
                if missing_projection or not dense_available
                else RecallStatus.COMPLETE
            )
        return RecalledContext(
            status, tuple(memory_values), tuple(material_values), dense_available
        )


class PostgreSQLContextProjectionInvalidation:
    async def invalidate(
        self,
        transaction: PostgreSQLTransaction,
        sources: tuple[ContextProjectionSourceRef, ...],
    ) -> None:
        for source in sources:
            await transaction.execute(
                """DELETE FROM armi.context_embedding_projections
                   WHERE source_kind=%s AND source_ref=%s""",
                (source.source_kind, source.source_ref),
            )


__all__ = (
    "EmbeddingProjectionSource",
    "PostgreSQLContextEmbeddingRepository",
    "PostgreSQLContextProjectionInvalidation",
    "RecalledContext",
    "RecalledItem",
)
