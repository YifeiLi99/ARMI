"""S015 local related-data deletion executor."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import TransactionIsolation
from armi_kernel.contracts import Digest
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    RuntimeTransactionFailure,
)

from ._deletion_postgresql import LocalDataDeletionRepository
from .api import (
    DataRightsArtifactLifecyclePort,
    DataRightsDeletionPreview,
    DataRightsTargetRef,
    DataRightsUnitOfWorkFactory,
    DataRightsViolation,
)


class LocalDataDeletionExecutor:
    __slots__ = ("_execution_lock", "_lifecycle", "_repository", "_uow_factory")

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
        self._execution_lock = asyncio.Lock()

    async def resume_pending(self) -> None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit_of_work:
                order_ids = await self._repository.pending_order_ids(unit_of_work)
            for order_id in order_ids:
                await self.execute(order_id)
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def execute(self, order_id: UUID) -> None:
        # The request path and the reconciliation worker share this executor.
        # Serialize their physical processing while owner transactions remain short.
        async with self._execution_lock:
            await self._execute(order_id)

    async def _transaction[T](
        self, action: Callable[[PostgreSQLRuntimeUnitOfWork], Awaitable[T]]
    ) -> T:
        for attempt in range(3):
            try:
                async with self._uow_factory.unit_of_work(
                    isolation=TransactionIsolation.SERIALIZABLE
                ) as unit:
                    return await action(unit)
            except RuntimeTransactionFailure as error:
                if error.code not in {"DB-TX-SERIALIZATION", "DB-TX-DEADLOCK"}:
                    raise
                if attempt == 2:
                    raise DataRightsViolation(
                        "DATA-RIGHTS-TRANSACTION-CONFLICT"
                    ) from None
                await asyncio.sleep(0.01 * (attempt + 1))
        raise AssertionError("unreachable transaction attempt")

    async def _execute(self, order_id: UUID) -> None:
        try:
            artifacts = await self._transaction(
                lambda unit: self._repository.prepare(unit, order_id)
            )
            for _item in artifacts:
                await self._lifecycle.run_once()

            async def settle(unit_of_work: PostgreSQLRuntimeUnitOfWork) -> None:
                await self._repository.reconcile_artifacts(
                    unit_of_work, order_id=order_id
                )
                await self._repository.finalize(unit_of_work, order_id)

            await self._transaction(settle)
        except DataRightsViolation:
            raise
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def prepare_in(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        order_id: UUID,
    ) -> None:
        """Close owner-visible lineage inside the caller's rights transaction."""

        await self._repository.prepare(unit_of_work, order_id)

    async def preview_in(
        self, unit: PostgreSQLRuntimeUnitOfWork, party_id: UUID
    ) -> DataRightsDeletionPreview:
        related, targets, usages = await self._repository.discover_targets(
            unit.transaction,
            order_id=uuid7(),
            party_id=party_id,
            order_kind="delete_related",
        )
        for artifact_id, (total, target) in usages.items():
            exclusive = total > 0 and total == target
            targets[("artifact", artifact_id)] = DataRightsTargetRef(
                "artifact",
                artifact_id,
                "delete" if exclusive else "retain",
                "rights_enforcement" if exclusive else "shared_reference",
                "artifact-store",
            )
        ordered = tuple(
            sorted(targets.values(), key=lambda item: (item.kind, str(item.ref)))
        )
        fence = await (
            await unit.transaction.execute(
                "SELECT contact_generation,use_generation FROM armi.data_rights_party_fences WHERE party_id=%s",
                (party_id,),
            )
        ).fetchone()
        scope = {
            "party_id": str(party_id),
            "fence": None if fence is None else [int(fence[0]), int(fence[1])],
            "related": [[item.kind, str(item.ref)] for item in related],
            "targets": [
                [
                    item.kind,
                    str(item.ref),
                    item.required_action,
                    item.retention_reason,
                    item.responsible_owner,
                ]
                for item in ordered
            ],
            "usages": [
                [str(key), *value]
                for key, value in sorted(usages.items(), key=lambda item: str(item[0]))
            ],
        }
        return DataRightsDeletionPreview(
            party_id, Digest.from_bytes(rfc8785.dumps(scope)), ordered
        )


__all__ = ("LocalDataDeletionExecutor",)
