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
from ._participant_contract import (
    DataRightsApplyContribution,
    DataRightsApplyRequest,
    DataRightsArtifactUsage,
    DataRightsCanonicalRecord,
    DataRightsContributionVersion,
    DataRightsDiscoveryContribution,
    DataRightsDiscoveryRequest,
    DataRightsExportScope,
    DataRightsExportSegment,
    DataRightsOwnerIdentity,
    DataRightsParticipant,
    DataRightsParticipantViolation,
    DataRightsRecordBatchStream,
    DataRightsRelatedRef,
    DataRightsTargetRef,
    DataRightsTupleRecordStream,
    DataRightsVisibilityPort,
    EmptyDataRightsParticipant,
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
class DataRightsCognitionGate(Protocol):
    async def blocks_cognition(
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
    "DataRightsApplyContribution",
    "DataRightsApplyRequest",
    "DataRightsArtifactStorePort",
    "DataRightsArtifactUsage",
    "DataRightsCanonicalRecord",
    "DataRightsCognitionGate",
    "DataRightsContributionVersion",
    "DataRightsDeletionItemResult",
    "DataRightsDiscoveryContribution",
    "DataRightsDiscoveryRequest",
    "DataRightsEffectGate",
    "DataRightsExecutionStatus",
    "DataRightsExportScope",
    "DataRightsExportSegment",
    "DataRightsInteractionGate",
    "DataRightsItemStatus",
    "DataRightsOrderCommand",
    "DataRightsOrderDetail",
    "DataRightsOrderKind",
    "DataRightsOrderPort",
    "DataRightsOrderResult",
    "DataRightsOwnerIdentity",
    "DataRightsParticipant",
    "DataRightsParticipantViolation",
    "DataRightsPartyIdentityPort",
    "DataRightsPartyKey",
    "DataRightsRecordBatchStream",
    "DataRightsRelatedRef",
    "DataRightsRequesterKind",
    "DataRightsScopeKind",
    "DataRightsSubjectCommitGate",
    "DataRightsTargetRef",
    "DataRightsTupleRecordStream",
    "DataRightsUnitOfWorkFactory",
    "DataRightsViolation",
    "DataRightsVisibilityPort",
    "EmptyDataRightsParticipant",
)
