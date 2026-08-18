"""PostgreSQL ownership for Context embedding projection and exact recall."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid7

import psycopg
from armi_kernel.application import (
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
    WorkStatus,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId
from armi_material.api import (
    MaterialCandidateSourceRef,
    MaterialProjectionHead,
    MaterialProjectionPort,
    MaterialViolation,
)
from armi_memory.api import (
    MemoryCandidateSourceRef,
    MemoryProjectionHead,
    MemoryProjectionPort,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    PostgreSQLTransaction,
)

from ._embedding import (
    EMBEDDING_BINDING_ID,
    EMBEDDING_MODEL_ID,
    LIFE_MATERIAL_CHUNK_OVERLAP,
    RECALL_CANDIDATE_LIMIT,
    RECALL_DENSE_ANN_LIMIT,
    RECALL_HNSW_EF_SEARCH,
    RECALL_LEXICAL_CANDIDATE_LIMIT,
    RECALL_MATERIAL_LIMIT,
    RECALL_MEMORY_LIMIT,
    RECALL_MIN_LEXICAL_SIMILARITY,
    RECALL_MIN_SIMILARITY,
    RECALL_RRF_K,
    SEMANTIC_RECALL_PROFILE_ID,
)
from ._postgresql import ContextMaterialSource
from .api import ContextProjectionSourceRef, EmbeddingResponse, RecallStatus

_WORK_KIND = "context.embedding.project"
_RECONCILIATION_PAGE_SIZE = 256


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
        transaction = unit_of_work.transaction
        row = await (
            await transaction.execute(
                """SELECT coverage_state,epoch,scanning_epoch,source_kind,
                          after_source_ref
                   FROM armi.context_embedding_coverage
                   WHERE model_binding=%s FOR UPDATE""",
                (EMBEDDING_BINDING_ID,),
            )
        ).fetchone()
        if row is None:
            return False
        state, epoch, scanning_epoch, source_kind, after_source_ref = row
        if str(state) == "complete":
            return False
        if str(state) == "dirty":
            scanning_epoch = int(epoch)
            source_kind = "life_material"
            after_source_ref = None
            await transaction.execute(
                """UPDATE armi.context_embedding_coverage
                   SET coverage_state='reconciling',scanning_epoch=epoch,
                       source_kind='life_material',after_source_ref=NULL,
                       scan_found_missing=false,pending_work_count=0,
                       updated_at=statement_timestamp()
                   WHERE model_binding=%s AND coverage_state='dirty'""",
                (EMBEDDING_BINDING_ID,),
            )
        if str(source_kind) == "life_material":
            heads = await self._materials.projection_head_page(
                transaction,
                after_material_id=cast(UUID | None, after_source_ref),
                limit=_RECONCILIATION_PAGE_SIZE,
            )
            if heads:
                found_missing, actionable_count = await self._enqueue_missing_heads(
                    unit_of_work, "life_material", heads
                )
                await transaction.execute(
                    """UPDATE armi.context_embedding_coverage
                       SET after_source_ref=%s,
                           scan_found_missing=scan_found_missing OR %s,
                           pending_work_count=pending_work_count+%s,
                           updated_at=statement_timestamp()
                       WHERE model_binding=%s AND coverage_state='reconciling'
                         AND scanning_epoch=%s""",
                    (
                        heads[-1].material_id,
                        found_missing,
                        actionable_count,
                        EMBEDDING_BINDING_ID,
                        scanning_epoch,
                    ),
                )
                return actionable_count > 0 or not found_missing
            await transaction.execute(
                """UPDATE armi.context_embedding_coverage
                   SET source_kind='subjective_memory',after_source_ref=NULL,
                       updated_at=statement_timestamp()
                   WHERE model_binding=%s AND coverage_state='reconciling'
                     AND scanning_epoch=%s""",
                (EMBEDDING_BINDING_ID, scanning_epoch),
            )
            return True
        heads = await self._memories.projection_head_page(
            transaction,
            after_memory_id=cast(UUID | None, after_source_ref),
            limit=_RECONCILIATION_PAGE_SIZE,
        )
        if heads:
            found_missing, actionable_count = await self._enqueue_missing_heads(
                unit_of_work, "subjective_memory", heads
            )
            await transaction.execute(
                """UPDATE armi.context_embedding_coverage
                   SET after_source_ref=%s,
                       scan_found_missing=scan_found_missing OR %s,
                       pending_work_count=pending_work_count+%s,
                       updated_at=statement_timestamp()
                   WHERE model_binding=%s AND coverage_state='reconciling'
                     AND scanning_epoch=%s""",
                (
                    heads[-1].memory_id,
                    found_missing,
                    actionable_count,
                    EMBEDDING_BINDING_ID,
                    scanning_epoch,
                ),
            )
            return actionable_count > 0 or not found_missing
        coverage = await (
            await transaction.execute(
                """SELECT scan_found_missing,pending_work_count
                   FROM armi.context_embedding_coverage
                   WHERE model_binding=%s AND coverage_state='reconciling'
                     AND epoch=%s AND scanning_epoch=%s""",
                (EMBEDDING_BINDING_ID, scanning_epoch, scanning_epoch),
            )
        ).fetchone()
        if coverage is None:
            return False
        if not bool(coverage[0]):
            await transaction.execute(
                """UPDATE armi.context_embedding_coverage
                   SET coverage_state='complete',scanning_epoch=NULL,
                       scan_found_missing=false,source_kind=NULL,
                       after_source_ref=NULL,updated_at=statement_timestamp()
                   WHERE model_binding=%s AND coverage_state='reconciling'
                     AND epoch=%s AND scanning_epoch=%s""",
                (EMBEDDING_BINDING_ID, scanning_epoch, scanning_epoch),
            )
            return True
        if int(coverage[1]) > 0:
            return False
        await transaction.execute(
            """UPDATE armi.context_embedding_coverage
                   SET coverage_state='dirty',scanning_epoch=NULL,
                   scan_found_missing=false,pending_work_count=0,source_kind=NULL,
                   after_source_ref=NULL,updated_at=statement_timestamp()
               WHERE model_binding=%s AND coverage_state='reconciling'
                 AND epoch=%s AND scanning_epoch=%s""",
            (EMBEDDING_BINDING_ID, scanning_epoch, scanning_epoch),
        )
        return False

    async def _enqueue_missing_heads(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        source_kind: str,
        heads: tuple[MaterialProjectionHead, ...] | tuple[MemoryProjectionHead, ...],
    ) -> tuple[bool, int]:
        transaction = unit_of_work.transaction
        rows = await (
            await transaction.execute(
                """WITH requested AS (
                     SELECT source_ref,source_version
                     FROM unnest(%s::uuid[],%s::bigint[])
                       AS source(source_ref,source_version)
                   )
                   SELECT requested.source_ref,requested.source_version
                   FROM requested
                   WHERE NOT EXISTS (
                     SELECT 1 FROM armi.context_embedding_projections AS projection
                     WHERE projection.source_kind=%s
                       AND projection.source_ref=requested.source_ref
                       AND projection.source_version=requested.source_version
                       AND projection.chunk_ordinal=0
                       AND projection.model_binding=%s
                   )""",
                (
                    [
                        head.material_id
                        if isinstance(head, MaterialProjectionHead)
                        else head.memory_id
                        for head in heads
                    ],
                    [head.head_version for head in heads],
                    source_kind,
                    EMBEDDING_BINDING_ID,
                ),
            )
        ).fetchall()
        missing = {(row[0], int(row[1])) for row in rows}
        timestamp = await (
            await transaction.execute("SELECT statement_timestamp()")
        ).fetchone()
        if timestamp is None:
            return bool(missing), 0
        created_at = cast(datetime, timestamp[0])
        now = Instant(created_at)
        actionable_count = 0
        for head in heads:
            source_ref = (
                head.material_id
                if isinstance(head, MaterialProjectionHead)
                else head.memory_id
            )
            if (source_ref, head.head_version) not in missing:
                continue
            digest = Digest.from_bytes(
                f"{source_kind}:{source_ref}:{head.head_version}:"
                f"{EMBEDDING_BINDING_ID}".encode()
            )
            record = await unit_of_work.work.enqueue(
                WorkDraft(
                    WorkId(uuid7()),
                    _WORK_KIND,
                    WorkOwner(source_kind, source_ref),
                    IdempotencyKey(
                        f"embedding:{head.head_version}:{EMBEDDING_BINDING_ID}"
                    ),
                    digest,
                    15,
                    now,
                    Instant(created_at + timedelta(seconds=3600)),
                    3,
                    TraceId(source_ref.hex),
                    SubjectId(head.subject_id),
                    WorkPayloadRef(source_kind, source_ref),
                )
            )
            if record.status in {WorkStatus.READY, WorkStatus.LEASED}:
                actionable_count += 1
        return bool(missing), actionable_count

    async def note_projection_work_settled(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> None:
        await unit_of_work.transaction.execute(
            """UPDATE armi.context_embedding_coverage
               SET pending_work_count=greatest(pending_work_count-1,0),
                   updated_at=statement_timestamp()
               WHERE model_binding=%s""",
            (EMBEDDING_BINDING_ID,),
        )

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
    ) -> UUID | None:
        connection = unit_of_work.transaction
        if source.source_kind == "subjective_memory":
            current = await self._memories.lock_current_projection_head(
                connection,
                subject_id=source.subject_id,
                generation_id=source.life_generation_id,
                source=MemoryCandidateSourceRef(
                    source.source_ref, source.source_version
                ),
            )
        else:
            current = await self._materials.lock_current_projection_head(
                connection,
                subject_id=source.subject_id,
                generation_id=source.life_generation_id,
                source=MaterialCandidateSourceRef(
                    source.source_ref, source.source_version
                ),
            )
        if not current:
            await self.settle_failure(
                unit_of_work, attempt_id, "MODEL-EMBEDDING-SOURCE-STALE"
            )
            return None
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

    async def recall_parallel(
        self,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        *,
        subject_id: UUID,
        life_generation_id: UUID,
        query_text: str,
        query_vector: tuple[float, ...] | None,
    ) -> RecalledContext:
        async def dense() -> list[tuple[object, ...]]:
            if query_vector is None:
                return []
            async with factory.unit_of_work(read_only=True) as unit_of_work:
                return await self._dense_candidate_rows(
                    unit_of_work.transaction,
                    subject_id=subject_id,
                    life_generation_id=life_generation_id,
                    query_vector=query_vector,
                )

        async def lexical() -> list[tuple[object, ...]]:
            async with factory.unit_of_work(read_only=True) as unit_of_work:
                return await self._lexical_candidate_rows(
                    unit_of_work.transaction,
                    subject_id=subject_id,
                    life_generation_id=life_generation_id,
                    query_text=query_text,
                )

        dense_rows, lexical_rows = await asyncio.gather(dense(), lexical())
        async with factory.unit_of_work(read_only=True) as unit_of_work:
            return await self.recall(
                unit_of_work,
                subject_id=subject_id,
                life_generation_id=life_generation_id,
                query_text=query_text,
                query_vector=query_vector,
                _candidate_rows=(dense_rows, lexical_rows),
            )

    async def _dense_candidate_rows(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        life_generation_id: UUID,
        query_vector: tuple[float, ...],
    ) -> list[tuple[object, ...]]:
        vector = "[" + ",".join(format(item, ".17g") for item in query_vector) + "]"
        await transaction.execute(
            "SELECT set_config('hnsw.ef_search',%s,true)",
            (str(RECALL_HNSW_EF_SEARCH),),
        )
        await transaction.execute(
            "SELECT set_config('hnsw.iterative_scan','relaxed_order',true)"
        )
        rows = list(
            await (
                await transaction.execute(
                    """WITH parameters AS (
                         SELECT %s::armi_extensions.vector(1024) AS query_vector
                       ), nearest AS MATERIALIZED (
                         SELECT projection.*
                         FROM armi.context_embedding_projections AS projection
                         CROSS JOIN parameters
                         WHERE projection.subject_id=%s
                           AND projection.life_generation_id=%s
                           AND projection.model_binding=%s
                         ORDER BY
                           projection.embedding::armi_extensions.halfvec(1024)
                             OPERATOR(armi_extensions.<=>)
                           parameters.query_vector::armi_extensions.halfvec(1024)
                         LIMIT %s
                       )
                       SELECT nearest.source_kind,nearest.source_ref,
                              nearest.source_version,
                              nearest.chunk_ordinal,nearest.chunk_text,
                              1-(nearest.embedding
                                 OPERATOR(armi_extensions.<=>)
                                 parameters.query_vector) AS score
                       FROM nearest
                       CROSS JOIN parameters
                       ORDER BY nearest.embedding
                                  OPERATOR(armi_extensions.<=>)
                                  parameters.query_vector,
                                nearest.source_kind,nearest.source_ref,
                                nearest.chunk_ordinal""",
                    (
                        vector,
                        subject_id,
                        life_generation_id,
                        EMBEDDING_BINDING_ID,
                        RECALL_DENSE_ANN_LIMIT,
                    ),
                )
            ).fetchall()
        )
        return [
            row
            for row in rows
            if float(cast(float, row[5])) >= RECALL_MIN_SIMILARITY
        ]

    async def _lexical_candidate_rows(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        life_generation_id: UUID,
        query_text: str,
    ) -> list[tuple[object, ...]]:
        rows = list(
            await (
                await transaction.execute(
                    """WITH nearest AS MATERIALIZED (
                         SELECT projection.*
                         FROM armi.context_embedding_projections AS projection
                         WHERE projection.subject_id=%s
                           AND projection.life_generation_id=%s
                           AND projection.model_binding=%s
                         ORDER BY %s
                           OPERATOR(armi_extensions.<<->)
                           projection.retrieval_text
                         LIMIT %s
                       )
                       SELECT nearest.source_kind,nearest.source_ref,
                              nearest.source_version,nearest.chunk_ordinal,
                              nearest.chunk_text,
                              armi_extensions.word_similarity(
                                %s,nearest.retrieval_text)
                                AS score,
                              position(lower(%s)
                                in lower(nearest.retrieval_text))>0 AS contains
                       FROM nearest
                       ORDER BY
                         (position(lower(%s)
                           in lower(nearest.retrieval_text))>0) DESC,
                         score DESC,nearest.source_kind,
                         nearest.source_ref,nearest.chunk_ordinal""",
                    (
                        subject_id,
                        life_generation_id,
                        EMBEDDING_BINDING_ID,
                        query_text,
                        RECALL_LEXICAL_CANDIDATE_LIMIT,
                        query_text,
                        query_text,
                        query_text,
                    ),
                )
            ).fetchall()
        )
        return [
            row
            for row in rows
            if float(cast(float, row[5])) >= RECALL_MIN_LEXICAL_SIMILARITY
            or bool(row[6])
        ]

    async def recall(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_id: UUID,
        life_generation_id: UUID,
        query_text: str,
        query_vector: tuple[float, ...] | None,
        _candidate_rows: tuple[
            list[tuple[object, ...]], list[tuple[object, ...]]
        ]
        | None = None,
    ) -> RecalledContext:
        transaction = unit_of_work.transaction
        if _candidate_rows is None:
            dense_rows = (
                []
                if query_vector is None
                else await self._dense_candidate_rows(
                    transaction,
                    subject_id=subject_id,
                    life_generation_id=life_generation_id,
                    query_vector=query_vector,
                )
            )
            lexical_rows = await self._lexical_candidate_rows(
                transaction,
                subject_id=subject_id,
                life_generation_id=life_generation_id,
                query_text=query_text,
            )
        else:
            dense_rows, lexical_rows = _candidate_rows
        memory_refs: list[MemoryCandidateSourceRef] = []
        material_refs: list[MaterialCandidateSourceRef] = []
        seen_sources: set[tuple[str, UUID, int]] = set()
        for row in (*dense_rows, *lexical_rows):
            source_key = (str(row[0]), cast(UUID, row[1]), cast(int, row[2]))
            if source_key in seen_sources:
                continue
            seen_sources.add(source_key)
            if source_key[0] == "subjective_memory":
                memory_refs.append(MemoryCandidateSourceRef(source_key[1], source_key[2]))
            elif source_key[0] == "life_material":
                material_refs.append(
                    MaterialCandidateSourceRef(source_key[1], source_key[2])
                )
        current_memory_refs = await self._memories.filter_current_projection_heads(
            transaction,
            subject_id=subject_id,
            generation_id=life_generation_id,
            sources=tuple(memory_refs),
        )
        current_material_refs = await self._materials.filter_current_projection_heads(
            transaction,
            subject_id=subject_id,
            generation_id=life_generation_id,
            sources=tuple(material_refs),
        )
        current_memories = {
            (source.memory_id, source.head_version) for source in current_memory_refs
        }
        current_materials = {
            (source.material_id, source.head_version) for source in current_material_refs
        }
        candidates: dict[_CandidateKey, _RecallCandidate] = {}
        for signal, rows in (("dense", dense_rows), ("lexical", lexical_rows)):
            valid_rows = [
                row
                for row in rows
                if (
                    (cast(UUID, row[1]), cast(int, row[2]))
                    in (
                        current_memories
                        if str(row[0]) == "subjective_memory"
                        else current_materials
                    )
                )
            ][:RECALL_CANDIDATE_LIMIT]
            for rank, row in enumerate(valid_rows, 1):
                kind, source_ref, version, ordinal, text, score, *_ = row
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
            if kind == "subjective_memory":
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
            elif kind == "life_material":
                material_best.setdefault(
                    source_ref,
                    ((kind, source_ref, version, ordinal), value, final_rank),
                )
        material_values: list[RecalledItem] = []
        material_validation_failed = False
        for source_ref, (best_key, value, final_rank) in material_best.items():
            if len(material_values) >= RECALL_MATERIAL_LIMIT:
                break
            _kind, _ref, version, ordinal = best_key
            try:
                material_source = await self._materials.load_source(
                    transaction, source_ref
                )
            except MaterialViolation:
                material_source = None
            if material_source is None or material_source.head_version != version:
                material_validation_failed = True
                continue
            adjacent_rows = await (
                await transaction.execute(
                    """SELECT chunk_ordinal,chunk_text
                       FROM armi.context_embedding_projections
                       WHERE source_kind='life_material' AND source_ref=%s
                         AND source_version=%s AND model_binding=%s
                         AND subject_id=%s AND life_generation_id=%s
                         AND chunk_ordinal BETWEEN %s AND %s
                       ORDER BY chunk_ordinal""",
                    (
                        source_ref,
                        version,
                        EMBEDDING_BINDING_ID,
                        subject_id,
                        life_generation_id,
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
        coverage = await (
            await transaction.execute(
                """SELECT coverage_state FROM armi.context_embedding_coverage
                   WHERE model_binding=%s""",
                (EMBEDDING_BINDING_ID,),
            )
        ).fetchone()
        missing_projection = (
            coverage is None
            or str(coverage[0]) != "complete"
            or material_validation_failed
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
        if sources:
            await transaction.execute(
                """UPDATE armi.context_embedding_coverage
                   SET coverage_state='dirty',epoch=epoch+1,
                       scanning_epoch=NULL,scan_found_missing=false,
                       pending_work_count=0,
                       source_kind=NULL,after_source_ref=NULL,
                       updated_at=statement_timestamp()
                   WHERE model_binding=%s""",
                (EMBEDDING_BINDING_ID,),
            )


def inspect_embedding_storage(conninfo: str) -> dict[str, object]:
    try:
        with psycopg.connect(conninfo) as connection:
            row = connection.execute(
                """SELECT
                     (SELECT count(*)
                      FROM armi.context_embedding_projections
                      WHERE model_binding=%s),
                     (SELECT coverage_state
                      FROM armi.context_embedding_coverage
                      WHERE model_binding=%s),
                     to_regclass(
                       'armi.context_embedding_projections_embedding_hnsw_idx'
                     ) IS NOT NULL,
                     to_regclass(
                       'armi.context_embedding_projections_retrieval_gist_idx'
                     ) IS NOT NULL""",
                (EMBEDDING_BINDING_ID, EMBEDDING_BINDING_ID),
            ).fetchone()
    except psycopg.Error:
        return {"database_status": "unavailable"}
    if row is None:
        return {"database_status": "unavailable"}
    count = int(row[0])
    capacity_status = (
        "expansion_observation"
        if count > 100_000
        else "benchmark_recommended"
        if count >= 80_000
        else "normal"
    )
    return {
        "database_status": "ready",
        "projection_count": count,
        "coverage_state": row[1],
        "retrieval_profile": SEMANTIC_RECALL_PROFILE_ID,
        "dense_index_ready": bool(row[2]),
        "lexical_index_ready": bool(row[3]),
        "capacity_status": capacity_status,
    }
__all__ = (
    "EmbeddingProjectionSource",
    "PostgreSQLContextEmbeddingRepository",
    "PostgreSQLContextProjectionInvalidation",
    "RecalledContext",
    "RecalledItem",
    "inspect_embedding_storage",
)
