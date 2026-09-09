"""Stable public contracts for artifact catalog ownership."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactPublication,
    ArtifactRef,
    ArtifactRegistration,
    StagedArtifact,
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


@dataclass(frozen=True, slots=True)
class ArtifactRetirement:
    artifact_id: UUID
    artifact_object_id: UUID
    object_generation: int
    deletion_id: UUID | None
    shared_local_reference: bool
    changed: bool


@dataclass(frozen=True, slots=True)
class ArtifactAdminRetirement:
    changed: bool
    deletion_id: UUID | None
    shared_local_reference: bool
    artifact_object_id: UUID | None = None
    content_digest: str | None = None
    trace_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ArtifactDeletionState:
    deletion_id: UUID
    status: str
    attempt_count: int
    last_error_code: str | None


@runtime_checkable
class ArtifactAdminPort(Protocol):
    def diagnostic_counts(
        self, transaction: PostgreSQLAdminTransaction
    ) -> tuple[tuple[str, int], ...]: ...
    def diagnostic_snapshots(
        self, transaction: PostgreSQLAdminTransaction, *, limit: int
    ) -> tuple[ArtifactAdminSnapshot, ...]: ...
    def snapshot(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> ArtifactAdminSnapshot | None: ...
    def read_verified_bytes(self, snapshot: ArtifactAdminSnapshot) -> bytes: ...
    def delete(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        artifact_id: UUID,
        deletion_id: UUID | None = None,
    ) -> ArtifactAdminRetirement: ...
    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class ArtifactCatalogPort(Protocol):
    async def observation(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[tuple[tuple[str, int], ...], int]: ...

    async def export_records(
        self, transaction: PostgreSQLTransaction
    ) -> tuple[tuple[str, tuple[bytes, ...]], ...]: ...

    async def reserve_publication(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        staged: StagedArtifact,
        *,
        orphan_grace_seconds: int,
    ) -> ArtifactPublication: ...

    async def mark_publication_published(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        publication: ArtifactPublication,
    ) -> None: ...

    async def abandon_publication(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        publication: ArtifactPublication,
    ) -> None: ...

    async def register(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        published: ArtifactPublication,
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

    async def retire_artifact(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
    ) -> ArtifactRetirement: ...

    async def mark_integrity(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: ArtifactId,
        status: ArtifactIntegrityStatus,
    ) -> bool: ...


@runtime_checkable
class ArtifactLifecyclePort(Protocol):
    async def recover(self) -> int: ...

    async def run(self) -> None: ...

    def stop(self) -> None: ...

    async def run_once(self) -> bool: ...

    async def deletion_states(
        self, transaction: PostgreSQLTransaction, deletion_ids: tuple[UUID, ...]
    ) -> tuple[ArtifactDeletionState, ...]: ...

    async def retry_blocked(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        deletion_ids: tuple[UUID, ...],
        retry_cycle: int,
    ) -> int: ...


__all__ = (
    "ArtifactAdminPort",
    "ArtifactAdminRetirement",
    "ArtifactAdminSnapshot",
    "ArtifactCatalogPort",
    "ArtifactDeletionState",
    "ArtifactLifecyclePort",
    "ArtifactRetirement",
)
