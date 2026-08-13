"""Stable public contracts for artifact catalog ownership."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactRef,
    ArtifactRegistration,
    PublishedArtifact,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork


@runtime_checkable
class ArtifactCatalogPort(Protocol):
    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: PublishedArtifact,
    ) -> ArtifactRegistration: ...

    async def get(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef: ...

    async def all_refs(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> tuple[ArtifactRef, ...]: ...

    async def retained_ref(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef | None: ...

    async def mark_deleted(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> bool: ...

    async def mark_integrity(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        status: ArtifactIntegrityStatus,
    ) -> bool: ...


__all__ = ("ArtifactCatalogPort",)
