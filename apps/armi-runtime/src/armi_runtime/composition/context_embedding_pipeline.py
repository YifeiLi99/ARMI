"""Durable asynchronous builder for Context embedding projections."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid7

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_artifact_store.life_material_codec import parse_life_material_artifact
from armi_kernel.application import (
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactViolation,
    CredentialLocator,
    CredentialPort,
    ModelViolation,
    RuntimeFence,
    WorkLease,
    WorkResultRef,
    WorkViolation,
)
from armi_kernel.contracts import Instant

from armi_runtime.adapters.model.volcengine_embedding import (
    VolcengineArkEmbeddingAdapter,
)
from armi_runtime.adapters.persistence.context_embedding import (
    EmbeddingProjectionSource,
    PostgreSQLContextEmbeddingRepository,
)
from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .context_embedding import chunk_life_material, load_embedding_binding

_WORK_KIND = "context.embedding.project"
Diagnostic = Callable[[str], None]


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
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        adapter: VolcengineArkEmbeddingAdapter,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._adapter = adapter
        self._repository = PostgreSQLContextEmbeddingRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()

    async def open(self) -> None:
        await self._factory.open()
        await self._storage.prepare()

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

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
            source = await self._repository.load_source(unit_of_work, lease)
        if source is None:
            async with self._factory.unit_of_work() as unit_of_work:
                await unit_of_work.work.complete(
                    lease,
                    WorkResultRef("context_embedding_source", records[0].draft.owner.reference),
                )
            return True
        chunks = await self._source_chunks(source)
        if not chunks:
            await self._fail_work(lease, "MODEL-EMBEDDING-INPUT")
            return True
        last_projection: UUID | None = None
        for ordinal, text in enumerate(chunks):
            lease = await self._work.renew(lease, lease_seconds=30)
            async with self._factory.unit_of_work() as unit_of_work:
                attempt_id = await self._repository.prepare_attempt(
                    unit_of_work, source, ordinal, text
                )
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.mark_dispatched(unit_of_work, attempt_id)
            try:
                response = await self._adapter.embed(text)
            except ModelViolation as error:
                async with self._factory.unit_of_work() as unit_of_work:
                    await self._repository.settle_failure(
                        unit_of_work, attempt_id, error.code
                    )
                await self._fail_work(
                    lease,
                    error.code,
                    retry=records[0].attempt_count < records[0].draft.max_attempts,
                )
                return True
            async with self._factory.unit_of_work() as unit_of_work:
                last_projection = await self._repository.settle_success(
                    unit_of_work,
                    attempt_id=attempt_id,
                    source=source,
                    chunk_ordinal=ordinal,
                    text=text,
                    response=response,
                )
        assert last_projection is not None
        async with self._factory.unit_of_work() as unit_of_work:
            await unit_of_work.work.complete(
                lease, WorkResultRef("context_embedding_projection", last_projection)
            )
        return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                repaired = await self.repair_once()
                projected = await self.project_once()
            except DatabaseTransactionError, WorkViolation, ArtifactViolation:
                repaired = projected = False
            if repaired or projected:
                await asyncio.sleep(0)
            else:
                with suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=1)

    async def _source_chunks(
        self, source: EmbeddingProjectionSource
    ) -> tuple[str, ...]:
        if source.memory_text is not None:
            return (source.memory_text,)
        material = source.material_source
        if (
            material is None
            or material.ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            or material.ref.privacy_scope is not ArtifactPrivacyScope.PRIVATE
            or material.ref.logical_kind != "life.material.content"
        ):
            raise ArtifactViolation("ART-STATE")
        stream = await self._storage.open_verified(material.ref)
        async with stream:
            artifact = await stream.read()
        try:
            body = parse_life_material_artifact(artifact).decode("utf-8", errors="strict")
        except ValueError, UnicodeError:
            raise ArtifactViolation("ART-INTEGRITY") from None
        return chunk_life_material(f"{material.title}\n{body}")

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


def build_context_embedding_pipeline(
    conninfo: str,
    *,
    environment_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    credential_port: CredentialPort,
    credential_locator: CredentialLocator,
) -> ContextEmbeddingPipeline:
    return ContextEmbeddingPipeline(
        factory=PostgreSQLUnitOfWorkFactory(
            conninfo,
            environment_id=environment_id,
            pool_min=pool_min,
            pool_max=pool_max,
            acquire_timeout_seconds=acquire_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            authority_admission=authority_admission,
        ),
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        adapter=VolcengineArkEmbeddingAdapter(
            binding=load_embedding_binding(),
            credential_port=credential_port,
            locator=credential_locator,
        ),
    )


__all__ = ("ContextEmbeddingPipeline", "build_context_embedding_pipeline")
