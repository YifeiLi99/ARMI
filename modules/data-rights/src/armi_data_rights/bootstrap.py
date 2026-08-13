"""Composition entry points for the data-rights business module."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from armi_kernel.application import CreatorProjectionNotifier
from armi_memory.api import MemoryDataRightsParticipant
from armi_relationship.api import RelationshipDataRightsParticipant

from ._application import DataRightsOrderService
from ._creator_export import CreatorExportService
from ._deletion import LocalDataDeletionExecutor
from ._deletion_postgresql import LocalDataDeletionRepository
from ._postgresql import DataRightsOrderRepository
from .api import (
    CreatorExportPort,
    DataRightsArtifactStorePort,
    DataRightsInteractionGate,
    DataRightsOrderPort,
    DataRightsPartyIdentityPort,
    DataRightsProjectionInvalidationPort,
    DataRightsSubjectEpochPort,
    DataRightsUnitOfWorkFactory,
)


class DataRightsCore:
    __slots__ = ("_gate", "_sealed")

    def __init__(self) -> None:
        self._gate = DataRightsOrderRepository()
        self._sealed = False

    @property
    def gate(self) -> DataRightsInteractionGate:
        return self._gate

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
    _orders: DataRightsOrderService
    _exports: CreatorExportService

    async def open(self) -> None:
        await self._exports.open()
        try:
            await self._orders.open()
        except Exception:
            await self._exports.close()
            raise

    async def close(self) -> None:
        await self._orders.close()
        await self._exports.close()


def bootstrap_data_rights_core() -> DataRightsCore:
    return DataRightsCore()


def bootstrap_data_rights(
    *,
    creator_party_id: UUID,
    data_root: Path,
    unit_of_work_factory: DataRightsUnitOfWorkFactory,
    storage: DataRightsArtifactStorePort,
    memory: MemoryDataRightsParticipant,
    relationship: RelationshipDataRightsParticipant,
    context_projections: DataRightsProjectionInvalidationPort,
    core: DataRightsCore,
    parties: DataRightsPartyIdentityPort,
    subject_epoch: DataRightsSubjectEpochPort,
    notifier: CreatorProjectionNotifier | None = None,
) -> DataRightsModule:
    gate = core.seal()
    deletion = LocalDataDeletionExecutor(
        repository=LocalDataDeletionRepository(
            memory, relationship, context_projections
        ),
        storage=storage,
        unit_of_work_factory=unit_of_work_factory,
    )
    orders = DataRightsOrderService(
        creator_party_id=creator_party_id,
        deletion=deletion,
        repository=gate,
        unit_of_work_factory=unit_of_work_factory,
        notifier=notifier,
        parties=parties,
        subject_epoch=subject_epoch,
    )
    exports = CreatorExportService(
        creator_party_id=creator_party_id,
        data_root=data_root,
        storage=storage,
        unit_of_work_factory=unit_of_work_factory,
    )
    return DataRightsModule(orders, exports, gate, orders, exports)


__all__ = (
    "DataRightsCore",
    "DataRightsModule",
    "bootstrap_data_rights",
    "bootstrap_data_rights_core",
)
