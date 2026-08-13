"""Creator and built-in other-human local data-right command service."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
)
from armi_kernel.contracts import Digest, Instant, Purpose
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    RuntimeTransactionFailure,
)

from ._deletion import LocalDataDeletionExecutor
from ._postgresql import DataRightsOrderRepository, DataRightsOrderSnapshot
from .api import (
    DataRightsDeletionItemResult,
    DataRightsExecutionStatus,
    DataRightsItemStatus,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResult,
    DataRightsPartyIdentityPort,
    DataRightsPartyKey,
    DataRightsRequesterKind,
    DataRightsScopeKind,
    DataRightsUnitOfWorkFactory,
    DataRightsViolation,
)


class DataRightsOrderService(DataRightsOrderPort):
    __slots__ = (
        "_creator_party_id",
        "_deletion",
        "_notifier",
        "_parties",
        "_repository",
        "_uow_factory",
    )

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        deletion: LocalDataDeletionExecutor,
        repository: DataRightsOrderRepository,
        unit_of_work_factory: DataRightsUnitOfWorkFactory,
        parties: DataRightsPartyIdentityPort,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        if creator_party_id.version != 7:
            raise DataRightsViolation("DATA-RIGHTS-COMPOSITION")
        self._creator_party_id = creator_party_id
        self._deletion = deletion
        self._repository = repository
        self._uow_factory = unit_of_work_factory
        self._notifier = notifier
        self._parties = parties

    async def open(self) -> None:
        try:
            await self._deletion.resume_pending()
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def close(self) -> None:
        return None

    async def request_creator(
        self, command: DataRightsOrderCommand
    ) -> DataRightsOrderResult:
        return await self._request(
            requester_kind=DataRightsRequesterKind.CREATOR,
            party_key=None,
            command=command,
        )

    async def request_other_human(
        self,
        party_key: DataRightsPartyKey,
        command: DataRightsOrderCommand,
    ) -> DataRightsOrderResult:
        return await self._request(
            requester_kind=DataRightsRequesterKind.OTHER_HUMAN,
            party_key=party_key,
            command=command,
        )

    async def get_creator(self, order_id: UUID) -> DataRightsOrderResult | None:
        return await self._get(
            requester_kind=DataRightsRequesterKind.CREATOR,
            party_key=None,
            order_id=order_id,
        )

    async def get_other_human(
        self,
        party_key: DataRightsPartyKey,
        order_id: UUID,
    ) -> DataRightsOrderResult | None:
        return await self._get(
            requester_kind=DataRightsRequesterKind.OTHER_HUMAN,
            party_key=party_key,
            order_id=order_id,
        )

    async def _request(
        self,
        *,
        requester_kind: DataRightsRequesterKind,
        party_key: DataRightsPartyKey | None,
        command: DataRightsOrderCommand,
    ) -> DataRightsOrderResult:
        result = await self._record_request(
            requester_kind=requester_kind,
            party_key=party_key,
            command=command,
        )
        if (
            result.order_kind is DataRightsOrderKind.DELETE_RELATED
            and result.execution_status
            in {DataRightsExecutionStatus.PENDING, DataRightsExecutionStatus.EXECUTING}
        ):
            await self._deletion.execute(result.order_id)
            refreshed = await self._get(
                requester_kind=requester_kind,
                party_key=party_key,
                order_id=result.order_id,
            )
            if refreshed is None:
                raise DataRightsViolation("DATA-RIGHTS-STATE")
            final = DataRightsOrderResult(
                refreshed.order_id,
                refreshed.requester_party_id,
                refreshed.requester_kind,
                refreshed.order_kind,
                refreshed.scope_kind,
                refreshed.scope_party_id,
                refreshed.status,
                refreshed.execution_status,
                refreshed.request_digest,
                refreshed.effective_at,
                refreshed.completed_at,
                result.newly_created,
            )
            await self._notify(final.order_id)
            return final
        if result.newly_created:
            await self._notify(result.order_id)
        return result

    async def list_creator(self) -> tuple[DataRightsOrderDetail, ...]:
        return await self._list(requester_party_id=None)

    async def detail_creator(self, order_id: UUID) -> DataRightsOrderDetail | None:
        return await self._detail(order_id=order_id, requester_party_id=None)

    async def list_other_human(
        self, party_key: DataRightsPartyKey
    ) -> tuple[DataRightsOrderDetail, ...]:
        return await self._list_for_other(party_key)

    async def detail_other_human(
        self, party_key: DataRightsPartyKey, order_id: UUID
    ) -> DataRightsOrderDetail | None:
        return await self._detail_for_other(party_key, order_id)

    async def _list_for_other(
        self, party_key: DataRightsPartyKey
    ) -> tuple[DataRightsOrderDetail, ...]:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit:
                party_id = await self._requester_party(
                    unit, DataRightsRequesterKind.OTHER_HUMAN, party_key
                )
                return await self._details(unit, party_id)
        except DataRightsViolation:
            raise
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _detail_for_other(
        self, party_key: DataRightsPartyKey, order_id: UUID
    ) -> DataRightsOrderDetail | None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit:
                party_id = await self._requester_party(
                    unit, DataRightsRequesterKind.OTHER_HUMAN, party_key
                )
                return await self._detail_in_unit(unit, order_id, party_id)
        except DataRightsViolation:
            raise
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _list(
        self, requester_party_id: UUID | None
    ) -> tuple[DataRightsOrderDetail, ...]:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit:
                return await self._details(unit, requester_party_id)
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _detail(
        self, *, order_id: UUID, requester_party_id: UUID | None
    ) -> DataRightsOrderDetail | None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit:
                return await self._detail_in_unit(unit, order_id, requester_party_id)
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _details(
        self, unit: PostgreSQLRuntimeUnitOfWork, requester_party_id: UUID | None
    ) -> tuple[DataRightsOrderDetail, ...]:
        orders = await self._repository.list_orders(
            unit, requester_party_id=requester_party_id
        )
        return tuple(
            [await self._detail_from_snapshot(unit, order) for order in orders]
        )

    async def _detail_in_unit(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        order_id: UUID,
        requester_party_id: UUID | None,
    ) -> DataRightsOrderDetail | None:
        snapshot = (
            await self._repository.get_any(unit, order_id)
            if requester_party_id is None
            else await self._repository.get(
                unit, requester_party_id=requester_party_id, order_id=order_id
            )
        )
        return (
            None
            if snapshot is None
            else await self._detail_from_snapshot(unit, snapshot)
        )

    async def _detail_from_snapshot(
        self, unit: PostgreSQLRuntimeUnitOfWork, snapshot: DataRightsOrderSnapshot
    ) -> DataRightsOrderDetail:
        items = await self._repository.deletion_items(unit, snapshot.order_id)
        return DataRightsOrderDetail(
            order=self._result(snapshot, False),
            items=tuple(
                DataRightsDeletionItemResult(
                    item.item_id,
                    item.target_kind,
                    item.required_action,
                    DataRightsItemStatus(item.result_status),
                    item.remaining_location,
                    item.created_at,
                    item.completed_at,
                )
                for item in items
            ),
        )

    async def _notify(self, order_id: UUID) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorEventResourceKind.DATA_RIGHTS,
                    str(order_id),
                    Instant(datetime.now(UTC)),
                    "data-rights-order.v2",
                )
            )
        except Exception:
            return

    async def _record_request(
        self,
        *,
        requester_kind: DataRightsRequesterKind,
        party_key: DataRightsPartyKey | None,
        command: DataRightsOrderCommand,
    ) -> DataRightsOrderResult:
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                requester_party_id = await self._requester_party(
                    unit_of_work, requester_kind, party_key
                )
                await unit_of_work.transaction.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"data-rights:{requester_party_id}",),
                )
                existing = await self._repository.find_existing(
                    unit_of_work,
                    requester_party_id=requester_party_id,
                    order_kind=command.order_kind,
                    idempotency_key=command.idempotency_key.value,
                    lock=True,
                )
                request_digest = self._request_digest(
                    requester_party_id, requester_kind, command.order_kind
                )
                if existing is not None:
                    if (
                        existing.idempotency_key == command.idempotency_key.value
                        and existing.order_kind is not command.order_kind
                    ):
                        raise DataRightsViolation("DATA-RIGHTS-IDEMPOTENCY-CONFLICT")
                    if existing.order_kind is command.order_kind:
                        return self._result(existing, newly_created=False)
                    raise DataRightsViolation("DATA-RIGHTS-IDEMPOTENCY-CONFLICT")
                scope_kind = (
                    DataRightsScopeKind.PARTY_CONTACT
                    if command.order_kind is DataRightsOrderKind.STOP_CONTACT
                    else DataRightsScopeKind.PARTY_LOCAL_DATA
                )
                execution_status = (
                    DataRightsExecutionStatus.PENDING
                    if command.order_kind is DataRightsOrderKind.DELETE_RELATED
                    else DataRightsExecutionStatus.NOT_REQUIRED
                )
                snapshot = await self._repository.insert(
                    unit_of_work,
                    order_id=uuid7(),
                    requester_party_id=requester_party_id,
                    requester_kind=requester_kind,
                    order_kind=command.order_kind,
                    scope_kind=scope_kind,
                    execution_status=execution_status,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                    trace_id=command.trace_id.value,
                )
                await unit_of_work.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference(requester_kind.value, requester_party_id),
                        Purpose("data.rights.request"),
                        f"data.rights.{command.order_kind.value}",
                        AuditReference("deletion_order", snapshot.order_id),
                        AuditResultStatus.APPLIED,
                        command.trace_id,
                        AuditSensitivity.RESTRICTED,
                    )
                )
                return self._result(snapshot, newly_created=True)
        except DataRightsViolation:
            raise
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _get(
        self,
        *,
        requester_kind: DataRightsRequesterKind,
        party_key: DataRightsPartyKey | None,
        order_id: UUID,
    ) -> DataRightsOrderResult | None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit_of_work:
                requester_party_id = await self._requester_party(
                    unit_of_work, requester_kind, party_key
                )
                snapshot = await self._repository.get(
                    unit_of_work,
                    requester_party_id=requester_party_id,
                    order_id=order_id,
                )
                return None if snapshot is None else self._result(snapshot, False)
        except DataRightsViolation:
            raise
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _requester_party(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        requester_kind: DataRightsRequesterKind,
        party_key: DataRightsPartyKey | None,
    ) -> UUID:
        if requester_kind is DataRightsRequesterKind.CREATOR:
            party_id = await self._parties.creator_party(
                unit_of_work.transaction,
                creator_party_id=self._creator_party_id,
            )
        elif party_key is None:
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER")
        else:
            party_id = await self._parties.other_human_party(
                unit_of_work.transaction,
                declared_identity_key=party_key.value,
            )
        if party_id is None:
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER-NOT-FOUND")
        return party_id

    def _request_digest(
        self,
        requester_party_id: UUID,
        requester_kind: DataRightsRequesterKind,
        order_kind: DataRightsOrderKind,
    ) -> Digest:
        scope_kind = (
            DataRightsScopeKind.PARTY_CONTACT
            if order_kind is DataRightsOrderKind.STOP_CONTACT
            else DataRightsScopeKind.PARTY_LOCAL_DATA
        )
        return Digest.from_bytes(
            rfc8785.dumps(
                {
                    "environment_id": str(self._uow_factory.environment_id),
                    "requester_party_id": str(requester_party_id),
                    "requester_kind": requester_kind.value,
                    "order_kind": order_kind.value,
                    "scope_kind": scope_kind.value,
                    "scope_party_id": str(requester_party_id),
                }
            )
        )

    @staticmethod
    def _result(
        snapshot: DataRightsOrderSnapshot,
        newly_created: bool,
    ) -> DataRightsOrderResult:
        return DataRightsOrderResult(
            order_id=snapshot.order_id,
            requester_party_id=snapshot.requester_party_id,
            requester_kind=snapshot.requester_kind,
            order_kind=snapshot.order_kind,
            scope_kind=snapshot.scope_kind,
            scope_party_id=snapshot.scope_party_id,
            status="effective",
            execution_status=snapshot.execution_status,
            request_digest=snapshot.request_digest,
            effective_at=snapshot.effective_at,
            completed_at=snapshot.completed_at,
            newly_created=newly_created,
        )


__all__ = ("DataRightsOrderService",)
