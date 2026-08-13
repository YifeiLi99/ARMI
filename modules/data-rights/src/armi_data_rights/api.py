"""Stable public contracts for local data rights and Creator exports."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
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
class DataRightsProjectionInvalidationPort(Protocol):
    async def invalidate(
        self,
        transaction: PostgreSQLTransaction,
        *,
        source_kind: str,
        source_refs: tuple[UUID, ...],
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
    "DataRightsExecutionStatus",
    "DataRightsInteractionGate",
    "DataRightsItemStatus",
    "DataRightsOrderCommand",
    "DataRightsOrderDetail",
    "DataRightsOrderKind",
    "DataRightsOrderPort",
    "DataRightsOrderResult",
    "DataRightsPartyKey",
    "DataRightsProjectionInvalidationPort",
    "DataRightsRequesterKind",
    "DataRightsScopeKind",
    "DataRightsUnitOfWorkFactory",
    "DataRightsViolation",
)
