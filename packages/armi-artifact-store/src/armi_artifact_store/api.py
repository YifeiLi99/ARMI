"""Stable public contracts for artifact catalog ownership."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactRegistration,
    PublishedArtifact,
)
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)


@dataclass(frozen=True, slots=True)
class ArtifactAdminSnapshot:
    artifact_id: UUID
    content_digest: str
    byte_size: int
    media_type: str
    logical_kind: str
    privacy_scope: ArtifactPrivacyScope
    integrity_status: ArtifactIntegrityStatus


@runtime_checkable
class ArtifactAdminPort(Protocol):
    def snapshot(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> ArtifactAdminSnapshot | None: ...
    def read_verified_bytes(self, snapshot: ArtifactAdminSnapshot) -> bytes: ...
    def delete(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> bool: ...
    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]: ...


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

    async def all_refs_in(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[ArtifactRef, ...]: ...

    async def retained_ref(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRef | None: ...

    async def retained_ref_in(
        self,
        transaction: PostgreSQLTransaction,
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


__all__ = ("ArtifactAdminPort", "ArtifactAdminSnapshot", "ArtifactCatalogPort")
