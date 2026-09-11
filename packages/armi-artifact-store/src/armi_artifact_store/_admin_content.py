"""Admin adapts synchronous transactions to the existing artifact publication protocol."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactPublication,
    ArtifactRef,
)
from armi_kernel.contracts import TraceId
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLAdminUnitOfWorkFactory,
)

from ._postgresql import PostgreSQLArtifactCatalog
from .content_store import ContentAddressedArtifactStore


def _run[T](operation: Coroutine[Any, Any, T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(operation)
    with ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="armi-admin-artifact"
    ) as worker:
        return worker.submit(asyncio.run, operation).result()


class _Result:
    def __init__(self, value: Any) -> None:
        self.value = value

    @property
    def rowcount(self) -> int:
        return self.value.rowcount

    async def fetchone(self) -> Any:
        return self.value.fetchone()

    async def fetchall(self) -> Any:
        return self.value.fetchall()


class _Transaction:
    def __init__(self, transaction: PostgreSQLAdminTransaction) -> None:
        self.transaction = transaction

    async def execute(self, statement: str, parameters: Any = ()) -> Any:
        return _Result(self.transaction.execute(statement, parameters))


class _Unit:
    """Only the catalog's SQL surface is adapted; no Runtime identity is manufactured."""

    def __init__(self, transaction: PostgreSQLAdminTransaction) -> None:
        self.transaction: Any = _Transaction(transaction)


class PostgreSQLArtifactAdminContent:
    def __init__(self, root: Path, factory: PostgreSQLAdminUnitOfWorkFactory) -> None:
        self.factory = factory
        self.storage = ContentAddressedArtifactStore(root, max_object_bytes=1_048_576)
        self.catalog: Any = PostgreSQLArtifactCatalog()

    def prepare(
        self, content: bytes, *, logical_kind: str, media_type: str, change_id: UUID
    ) -> ArtifactPublication:
        async def publish() -> ArtifactPublication:
            async def chunks():
                yield content

            policy = ArtifactPolicy(
                media_type=media_type,
                logical_kind=logical_kind,
                producer_kind="administrator",
                producer_trace_id=TraceId(change_id.hex),
                privacy_scope=ArtifactPrivacyScope.PRIVATE,
            )
            staged = await self.storage.stage(chunks(), policy)
            try:
                with self.factory.serializable() as unit:
                    publication = await self.catalog.reserve_publication(
                        _Unit(unit.transaction), staged, orphan_grace_seconds=3600
                    )
                    unit.commit()
                await self.storage.publish_reserved(staged, publication)
                with self.factory.serializable() as unit:
                    await self.catalog.mark_publication_published(
                        _Unit(unit.transaction), publication
                    )
                    unit.commit()
                return publication
            finally:
                await self.storage.discard(staged)

        return _run(publish())

    def register(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        artifact_id: UUID,
        publication: ArtifactPublication,
    ) -> ArtifactRef:
        registration = _run(
            self.catalog.register(
                _Unit(transaction), ArtifactId(artifact_id), publication
            )
        )
        return registration.ref


__all__ = ("PostgreSQLArtifactAdminContent",)
