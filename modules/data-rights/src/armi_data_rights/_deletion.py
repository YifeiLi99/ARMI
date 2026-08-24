"""S015 local related-data deletion executor."""

from __future__ import annotations

from uuid import UUID

from armi_kernel.application import TransactionIsolation
from armi_runtime_foundation import RuntimeTransactionFailure

from ._deletion_postgresql import LocalDataDeletionRepository
from .api import (
    DataRightsArtifactLifecyclePort,
    DataRightsUnitOfWorkFactory,
    DataRightsViolation,
)


class LocalDataDeletionExecutor:
    __slots__ = ("_lifecycle", "_repository", "_uow_factory")

    def __init__(
        self,
        *,
        repository: LocalDataDeletionRepository,
        lifecycle: DataRightsArtifactLifecyclePort,
        unit_of_work_factory: DataRightsUnitOfWorkFactory,
    ) -> None:
        self._repository = repository
        self._lifecycle = lifecycle
        self._uow_factory = unit_of_work_factory

    async def resume_pending(self) -> None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit_of_work:
                order_ids = await self._repository.pending_order_ids(unit_of_work)
            for order_id in order_ids:
                await self.execute(order_id)
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def execute(self, order_id: UUID) -> None:
        try:
            async with self._uow_factory.unit_of_work(
                isolation=TransactionIsolation.SERIALIZABLE
            ) as unit_of_work:
                artifacts = await self._repository.prepare(unit_of_work, order_id)
            for _item in artifacts:
                await self._lifecycle.run_once()
            async with self._uow_factory.unit_of_work(
                isolation=TransactionIsolation.SERIALIZABLE
            ) as unit_of_work:
                await self._repository.reconcile_artifacts(
                    unit_of_work, order_id=order_id
                )
                await self._repository.finalize(unit_of_work, order_id)
        except DataRightsViolation:
            raise
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None


__all__ = ("LocalDataDeletionExecutor",)
