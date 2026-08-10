"""S015 local related-data deletion executor."""

from __future__ import annotations

from uuid import UUID

from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_kernel.application import ArtifactViolation, DataRightsViolation, LockPlan

from armi_runtime.adapters.persistence.data_deletion import LocalDataDeletionRepository
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError


class LocalDataDeletionExecutor:
    __slots__ = ("_repository", "_storage", "_uow_factory")

    def __init__(
        self,
        *,
        repository: LocalDataDeletionRepository,
        storage: ContentAddressedArtifactStore,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._uow_factory = unit_of_work_factory

    async def resume_pending(self) -> None:
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(), read_only=True
            ) as unit_of_work:
                order_ids = await self._repository.pending_order_ids(unit_of_work)
            for order_id in order_ids:
                await self.execute(order_id)
        except DatabaseTransactionError:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def execute(self, order_id: UUID) -> None:
        try:
            async with self._uow_factory.unit_of_work(LockPlan()) as unit_of_work:
                artifacts = await self._repository.prepare(unit_of_work, order_id)
            for item in artifacts:
                completed = False
                try:
                    await self._storage.delete_verified(item.ref)
                    completed = True
                except ArtifactViolation:
                    completed = False
                async with self._uow_factory.unit_of_work(LockPlan()) as unit_of_work:
                    await self._repository.settle_artifact(
                        unit_of_work,
                        order_id=order_id,
                        item_id=item.item_id,
                        artifact_id=item.ref.artifact_id.value,
                        completed=completed,
                    )
            async with self._uow_factory.unit_of_work(LockPlan()) as unit_of_work:
                await self._repository.finalize(unit_of_work, order_id)
        except DataRightsViolation:
            raise
        except DatabaseTransactionError:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None


__all__ = ("LocalDataDeletionExecutor",)
