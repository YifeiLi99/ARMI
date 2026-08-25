"""Composition entry points for the data-rights business module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from armi_artifact_store.api import ArtifactCatalogPort
from armi_kernel.application import CreatorProjectionNotifier, ExecutionCustodyPort
from armi_runtime_foundation import EmptyRecoveryParticipant, RecoveryParticipant

from ._application import DataRightsOrderService
from ._creator_export import CreatorExportService
from ._data_rights_participant import PostgreSQLDataRightsParticipant
from ._deletion import LocalDataDeletionExecutor
from ._deletion_postgresql import LocalDataDeletionRepository
from ._managed_snapshots import PostgreSQLManagedSnapshotAdmin
from ._postgresql import DataRightsOrderRepository
from .api import (
    CreatorExportPort,
    DataRightsArtifactLifecyclePort,
    DataRightsArtifactStorePort,
    DataRightsCognitionGate,
    DataRightsEffectGate,
    DataRightsFencePort,
    DataRightsInteractionGate,
    DataRightsOrderPort,
    DataRightsOwnerContract,
    DataRightsParticipant,
    DataRightsPartyIdentityPort,
    DataRightsPartyRosterPort,
    DataRightsSubjectCommitGate,
    DataRightsUnitOfWorkFactory,
    DataRightsVisibilityPort,
)


class DataRightsCore:
    __slots__ = ("_gate", "_participant", "_sealed")

    def __init__(self) -> None:
        self._gate = DataRightsOrderRepository()
        self._participant = PostgreSQLDataRightsParticipant()
        self._sealed = False

    @property
    def gate(self) -> DataRightsInteractionGate:
        return self._gate

    @property
    def effect_gate(self) -> DataRightsEffectGate:
        return self._gate

    @property
    def cognition_gate(self) -> DataRightsCognitionGate:
        return self._gate

    @property
    def fence(self) -> DataRightsFencePort:
        return self._gate

    @property
    def visibility(self) -> DataRightsVisibilityPort:
        return self._gate

    @property
    def participant(self) -> DataRightsParticipant:
        return self._participant

    def seal(self) -> DataRightsOrderRepository:
        if self._sealed:
            raise RuntimeError("data rights core is already sealed")
        self._sealed = True
        return self._gate


@dataclass(frozen=True, slots=True)
class DataRightsModule:
    orders: DataRightsOrderPort
    exports: CreatorExportPort
    gate: DataRightsInteractionGate
    subject_commit: DataRightsSubjectCommitGate
    effect_gate: DataRightsEffectGate
    cognition: DataRightsCognitionGate
    fence: DataRightsFencePort
    visibility: DataRightsVisibilityPort
    participant: DataRightsParticipant
    _orders: DataRightsOrderService
    _exports: CreatorExportService

    async def open(self) -> None:
        await self._orders.open()
        try:
            await self._exports.open()
        except Exception:
            await self._orders.close()
            raise

    async def close(self) -> None:
        await self._orders.close()
        await self._exports.close()

    async def run(self) -> None:
        await self._orders.run()

    def stop(self) -> None:
        self._orders.stop()


def bootstrap_data_rights_core() -> DataRightsCore:
    return DataRightsCore()


def bootstrap_data_rights(
    *,
    creator_party_id: UUID,
    custody: ExecutionCustodyPort,
    data_root: Path,
    unit_of_work_factory: DataRightsUnitOfWorkFactory,
    storage: DataRightsArtifactStorePort,
    lifecycle: DataRightsArtifactLifecyclePort,
    core: DataRightsCore,
    parties: DataRightsPartyIdentityPort,
    party_roster: DataRightsPartyRosterPort,
    catalog: ArtifactCatalogPort,
    participants: tuple[DataRightsParticipant, ...],
    owner_contracts: tuple[DataRightsOwnerContract, ...],
    identity_key: str,
    notifier: CreatorProjectionNotifier | None = None,
) -> DataRightsModule:
    gate = core.seal()
    deletion = LocalDataDeletionExecutor(
        repository=LocalDataDeletionRepository(
            catalog,
            lifecycle,
            participants,
        ),
        lifecycle=lifecycle,
        unit_of_work_factory=unit_of_work_factory,
    )
    orders = DataRightsOrderService(
        creator_party_id=creator_party_id,
        custody=custody,
        deletion=deletion,
        repository=gate,
        unit_of_work_factory=unit_of_work_factory,
        notifier=notifier,
        parties=parties,
        lifecycle=lifecycle,
        participants=participants,
        owner_contracts=owner_contracts,
        identity_key=identity_key,
        data_root=data_root,
    )
    exports = CreatorExportService(
        creator_party_id=creator_party_id,
        custody=custody,
        data_root=data_root,
        storage=storage,
        unit_of_work_factory=unit_of_work_factory,
        participants=participants,
        party_roster=party_roster,
    )
    return DataRightsModule(
        orders,
        exports,
        gate,
        gate,
        gate,
        gate,
        gate,
        gate,
        core.participant,
        orders,
        exports,
    )


def bootstrap_data_rights_recovery() -> RecoveryParticipant:
    return EmptyRecoveryParticipant("data-rights")


def bootstrap_managed_snapshot_admin() -> PostgreSQLManagedSnapshotAdmin:
    return PostgreSQLManagedSnapshotAdmin()


__all__ = (
    "DataRightsCore",
    "DataRightsModule",
    "bootstrap_data_rights",
    "bootstrap_data_rights_core",
    "bootstrap_data_rights_recovery",
    "bootstrap_managed_snapshot_admin",
)
