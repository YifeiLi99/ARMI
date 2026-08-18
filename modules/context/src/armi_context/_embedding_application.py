"""Durable asynchronous builder for Context embedding projections."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid7

from armi_artifact_store import (
    ContentAddressedArtifactStore,
    parse_life_material_artifact,
)
from armi_kernel.application import (
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactViolation,
    DurableWorkPort,
    ModelViolation,
    WorkLease,
    WorkResultRef,
    WorkViolation,
)
from armi_kernel.contracts import Instant
from armi_material.api import MaterialProjectionPort
from armi_memory.api import MemoryProjectionPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._embedding import (
    DOCUMENT_BATCH_SIZE,
    chunk_life_material,
    material_retrieval_text,
)
from ._embedding_postgresql import (
    EmbeddingProjectionSource,
    PostgreSQLContextEmbeddingRepository,
)
from .api import EmbeddingPort

_WORK_KIND = "context.embedding.project"


class ContextEmbeddingPipeline:
    __slots__ = (
        "_adapter",
        "_factory",
        "_lease_owner",
        "_repository",
        "_stop",
        "_storage",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        adapter: EmbeddingPort,
        work: DurableWorkPort,
        memories: MemoryProjectionPort,
        materials: MaterialProjectionPort,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._adapter = adapter
        self._repository = PostgreSQLContextEmbeddingRepository(memories, materials)
        self._work = work
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()

    async def open(self) -> None:
        await self._storage.prepare()

    async def close(self) -> None:
        self._stop.set()
        await self._adapter.close()

    def stop(self) -> None:
        self._stop.set()

    async def repair_once(self) -> bool:
        async with self._factory.unit_of_work() as unit_of_work:
            return await self._repository.enqueue_one_missing(unit_of_work)

    async def project_once(self) -> bool:
        records = await self._work.claim(
            work_kind=_WORK_KIND,
            lease_owner=self._lease_owner,
            lease_seconds=30,
            limit=1,
        )
        if not records:
            return False
        lease = cast(WorkLease, records[0].lease)
        async with self._factory.unit_of_work(read_only=True) as unit_of_work:
            source = await self._repository.load_source(
                unit_of_work,
                owner_kind=records[0].draft.owner.kind,
                owner_ref=records[0].draft.owner.reference,
            )
        if source is None:
            async with self._factory.unit_of_work() as unit_of_work:
                await unit_of_work.work.complete(
                    lease,
                    WorkResultRef(
                        "context_embedding_source", records[0].draft.owner.reference
                    ),
                )
                await self._repository.note_projection_work_settled(unit_of_work)
            return True
        chunks = await self._source_chunks(source)
        if not chunks:
            await self._fail_work(lease, "MODEL-EMBEDDING-INPUT")
            return True
        last_projection: UUID | None = None
        for batch_start in range(0, len(chunks), DOCUMENT_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + DOCUMENT_BATCH_SIZE]
            attempts: list[UUID] = []
            for offset, (_display_text, retrieval_text) in enumerate(batch):
                lease = await self._work.renew(lease, lease_seconds=30)
                ordinal = batch_start + offset
                async with self._factory.unit_of_work() as unit_of_work:
                    attempt_id = await self._repository.prepare_attempt(
                        unit_of_work, source, ordinal, retrieval_text
                    )
                    await self._repository.mark_dispatched(unit_of_work, attempt_id)
                attempts.append(attempt_id)
            try:
                responses = await self._adapter.embed_documents(
                    tuple(item[1] for item in batch)
                )
            except ModelViolation as error:
                async with self._factory.unit_of_work() as unit_of_work:
                    for attempt_id in attempts:
                        await self._repository.settle_failure(
                            unit_of_work, attempt_id, error.code
                        )
                await self._fail_work(
                    lease,
                    error.code,
                    retry=records[0].attempt_count < records[0].draft.max_attempts,
                )
                return True
            for offset, (attempt_id, response) in enumerate(
                zip(attempts, responses, strict=True)
            ):
                display_text, retrieval_text = batch[offset]
                async with self._factory.unit_of_work() as unit_of_work:
                    projection = await self._repository.settle_success(
                        unit_of_work,
                        attempt_id=attempt_id,
                        source=source,
                        chunk_ordinal=batch_start + offset,
                        display_text=display_text,
                        retrieval_text=retrieval_text,
                        response=response,
                    )
                    if projection is None:
                        for pending_attempt in attempts[offset + 1 :]:
                            await self._repository.settle_failure(
                                unit_of_work,
                                pending_attempt,
                                "MODEL-EMBEDDING-SOURCE-STALE",
                            )
                        await unit_of_work.work.complete(
                            lease,
                            WorkResultRef(
                                "context_embedding_source", source.source_ref
                            ),
                        )
                        await self._repository.note_projection_work_settled(
                            unit_of_work
                        )
                        return True
                    last_projection = projection
        assert last_projection is not None
        async with self._factory.unit_of_work() as unit_of_work:
            await unit_of_work.work.complete(
                lease, WorkResultRef("context_embedding_projection", last_projection)
            )
            await self._repository.note_projection_work_settled(unit_of_work)
        return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                repaired = await self.repair_once()
                projected = await self.project_once()
            except RuntimeTransactionFailure, WorkViolation, ArtifactViolation:
                repaired = projected = False
            if repaired or projected:
                await asyncio.sleep(0)
            else:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1)

    async def _source_chunks(
        self, source: EmbeddingProjectionSource
    ) -> tuple[tuple[str, str], ...]:
        if source.memory_text is not None:
            return ((source.memory_text, f"Memory: {source.memory_text}"),)
        material = source.material_source
        if (
            material is None
            or material.ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            or material.ref.privacy_scope is not ArtifactPrivacyScope.PRIVATE
            or material.ref.logical_kind != "life.material.content"
        ):
            raise ArtifactViolation("ART-STATE")
        stream = await self._storage.open_verified(material.ref)
        artifact = b""
        async with stream:
            artifact = await stream.read()
        try:
            body = parse_life_material_artifact(artifact).decode(
                "utf-8", errors="strict"
            )
        except ValueError, UnicodeError:
            raise ArtifactViolation("ART-INTEGRITY") from None
        return tuple(
            (
                chunk,
                material_retrieval_text(material.title, material.material_kind, chunk),
            )
            for chunk in chunk_life_material(body)
        )

    async def _fail_work(
        self,
        lease: WorkLease,
        code: str,
        *,
        retry: bool = False,
    ) -> None:
        if retry:
            await self._work.release(
                lease,
                not_before=Instant(datetime.now(UTC) + timedelta(seconds=5)),
                error_code=code,
            )
            return
        async with self._factory.unit_of_work() as unit_of_work:
            await unit_of_work.work.fail(lease, error_code=code)
            await self._repository.note_projection_work_settled(unit_of_work)


__all__ = ("ContextEmbeddingPipeline",)
