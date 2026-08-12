"""PostgreSQL ownership for Context embedding projection and exact recall."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid7

from armi_kernel.application import (
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId
from armi_material.api import MaterialProjectionPort
from armi_memory.api import MemoryProjectionPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._postgresql import ContextMaterialSource
from .api import EmbeddingResponse, RecallStatus

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
        material = await self._materials.next_missing_source(
            unit_of_work.transaction,
            model_binding=_EMBEDDING_BINDING_ID,
            work_kind=_WORK_KIND,
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
        memory = await self._memories.next_missing_source(
            unit_of_work.transaction, model_binding=_EMBEDDING_BINDING_ID
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
    ) -> EmbeddingProjectionSource | None:
        connection = unit_of_work.transaction
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
            memory = await self._memories.load_source(unit_of_work.transaction, work[1])
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
        material = await self._materials.load_source(unit_of_work.transaction, work[1])
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
        text: str,
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
        query_vector: tuple[float, ...],
    ) -> RecalledContext:
        recalled_materials = await self._materials.recall(
            unit_of_work.transaction,
            subject_id=subject_id,
            generation_id=life_generation_id,
            model_binding=_EMBEDDING_BINDING_ID,
            query_vector=query_vector,
            minimum_similarity=_RECALL_MIN_SIMILARITY,
            limit=_RECALL_MATERIAL_LIMIT,
        )
        recalled_memories = await self._memories.recall(
            unit_of_work.transaction,
            subject_id=subject_id,
            generation_id=life_generation_id,
            model_binding=_EMBEDDING_BINDING_ID,
            query_vector=query_vector,
            minimum_similarity=_RECALL_MIN_SIMILARITY,
            limit=_RECALL_MEMORY_LIMIT,
        )
        memory_values = list(recalled_memories.items)
        memory_values = memory_values[:_RECALL_MEMORY_LIMIT]
        material_values = recalled_materials.items
        if not memory_values and not material_values:
            status = (
                RecallStatus.PARTIAL
                if recalled_materials.missing_projection
                or recalled_memories.missing_projection
                else RecallStatus.NO_RELEVANT_RESULT
            )
        else:
            status = (
                RecallStatus.PARTIAL
                if recalled_materials.missing_projection
                or recalled_memories.missing_projection
                else RecallStatus.COMPLETE
            )
        return RecalledContext(status, tuple(memory_values), tuple(material_values))


__all__ = (
    "EmbeddingProjectionSource",
    "PostgreSQLContextEmbeddingRepository",
    "RecalledContext",
)
