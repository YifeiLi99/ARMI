"""Stable public contracts for local data rights and Creator exports."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import (
    ArtifactRef,
    TransactionIsolation,
    VerifiedByteStream,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from ._export_contract import (
    CreatorExportCommand,
    CreatorExportPort,
    CreatorExportResult,
    CreatorExportStatus,
    CreatorExportViolation,
)
from ._rights_contract import (
    DataRightsDeletionItemResult,
    DataRightsExecutionStatus,
    DataRightsItemStatus,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResult,
    DataRightsPartyKey,
    DataRightsRequesterKind,
    DataRightsScopeKind,
    DataRightsViolation,
)


@runtime_checkable
class DataRightsArtifactStorePort(Protocol):
    async def open_verified(self, ref: ArtifactRef) -> VerifiedByteStream: ...

    async def delete_verified(self, ref: ArtifactRef) -> bool: ...


@runtime_checkable
class DataRightsInteractionGate(Protocol):
    async def blocks_new_interaction(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        requester_party_id: UUID,
    ) -> bool: ...


@runtime_checkable
class DataRightsSubjectCommitGate(Protocol):
    async def blocks_subject_commit(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        requester_party_id: UUID,
        opportunity_purpose: str,
    ) -> bool: ...


@runtime_checkable
class DataRightsEffectGate(Protocol):
    async def blocks_effect(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        requester_party_id: UUID,
    ) -> bool: ...


@runtime_checkable
class DataRightsProjectionInvalidationPort(Protocol):
    async def invalidate(
        self,
        transaction: PostgreSQLTransaction,
        *,
        source_kind: str,
        source_refs: tuple[UUID, ...],
    ) -> None: ...


@runtime_checkable
class DataRightsPartyIdentityPort(Protocol):
    async def creator_party(
        self,
        transaction: PostgreSQLTransaction,
        *,
        creator_party_id: UUID,
    ) -> UUID | None: ...

    async def other_human_party(
        self,
        transaction: PostgreSQLTransaction,
        *,
        declared_identity_key: str,
    ) -> UUID | None: ...


@runtime_checkable
class DataRightsSubjectEpochPort(Protocol):
    async def advance(self, transaction: PostgreSQLTransaction) -> None: ...


@runtime_checkable
class DataRightsMemoryPort(Protocol):
    async def find_for_party(
        self,
        transaction: PostgreSQLTransaction,
        party_id: UUID,
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class DataRightsRelationshipPort(Protocol):
    async def find_for_party(
        self,
        transaction: PostgreSQLTransaction,
        party_id: UUID,
    ) -> tuple[UUID, ...]: ...

    async def tombstone(
        self,
        transaction: PostgreSQLTransaction,
        *,
        relationship_id: UUID,
        order_id: UUID,
        tombstoned_at: datetime,
    ) -> None: ...


@runtime_checkable
class DataRightsUnitOfWorkFactory(Protocol):
    @property
    def environment_id(self) -> UUID: ...

    async def open(self) -> None: ...
    async def close(self) -> None: ...

    def unit_of_work(
        self,
        *,
        isolation: TransactionIsolation = TransactionIsolation.READ_COMMITTED,
        read_only: bool = False,
    ) -> AbstractAsyncContextManager[PostgreSQLRuntimeUnitOfWork]: ...


__all__ = (
    "CreatorExportCommand",
    "CreatorExportPort",
    "CreatorExportResult",
    "CreatorExportStatus",
    "CreatorExportViolation",
    "DataRightsArtifactStorePort",
    "DataRightsDeletionItemResult",
    "DataRightsEffectGate",
    "DataRightsExecutionStatus",
    "DataRightsInteractionGate",
    "DataRightsItemStatus",
    "DataRightsMemoryPort",
    "DataRightsOrderCommand",
    "DataRightsOrderDetail",
    "DataRightsOrderKind",
    "DataRightsOrderPort",
    "DataRightsOrderResult",
    "DataRightsPartyIdentityPort",
    "DataRightsPartyKey",
    "DataRightsProjectionInvalidationPort",
    "DataRightsRelationshipPort",
    "DataRightsRequesterKind",
    "DataRightsScopeKind",
    "DataRightsSubjectCommitGate",
    "DataRightsSubjectEpochPort",
    "DataRightsUnitOfWorkFactory",
    "DataRightsViolation",
)
