"""Creator and built-in other-human local data-right command service."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    CreatorResourceKind,
    ExecutionCustodyMode,
    ExecutionCustodyPort,
    ExecutionCustodyRequest,
    ExecutionCustodyScope,
    ExecutionCustodyScopeKind,
    TransactionIsolation,
    ordered_custody_requests,
)
from armi_kernel.contracts import Digest, Instant, Purpose
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    RuntimeTransactionFailure,
)

from ._deletion import LocalDataDeletionExecutor
from ._postgresql import DataRightsOrderRepository, DataRightsOrderSnapshot
from .api import (
    DataRightsApplyRequest,
    DataRightsArtifactLifecyclePort,
    DataRightsDeletionItemResult,
    DataRightsExecutionStatus,
    DataRightsItemStatus,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResult,
    DataRightsParticipant,
    DataRightsPartyIdentityPort,
    DataRightsPartyKey,
    DataRightsRequesterKind,
    DataRightsRetryCommand,
    DataRightsScopeKind,
    DataRightsUnitOfWorkFactory,
    DataRightsViolation,
)


class DataRightsOrderService(DataRightsOrderPort):
    __slots__ = (
        "_creator_party_id",
        "_custody",
        "_deletion",
        "_lifecycle",
        "_notifier",
        "_order_participant",
        "_parties",
        "_repository",
        "_stop",
        "_uow_factory",
    )

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        custody: ExecutionCustodyPort,
        deletion: LocalDataDeletionExecutor,
        repository: DataRightsOrderRepository,
        unit_of_work_factory: DataRightsUnitOfWorkFactory,
        parties: DataRightsPartyIdentityPort,
        lifecycle: DataRightsArtifactLifecyclePort,
        participants: tuple[DataRightsParticipant, ...],
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        if creator_party_id.version != 7:
            raise DataRightsViolation("DATA-RIGHTS-COMPOSITION")
        self._creator_party_id = creator_party_id
        self._custody = custody
        self._deletion = deletion
        self._lifecycle = lifecycle
        self._repository = repository
        self._uow_factory = unit_of_work_factory
        self._notifier = notifier
        self._parties = parties
        order_participants = tuple(
            participant
            for participant in participants
            if participant.owner_identity.value == "opportunity"
        )
        if len(order_participants) != 1:
            raise DataRightsViolation("DATA-RIGHTS-COMPOSITION")
        self._order_participant = order_participants[0]
        self._stop = asyncio.Event()

    async def open(self) -> None:
        try:
            await self._deletion.resume_pending()
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def close(self) -> None:
        return None

    async def run(self) -> None:
        """Continuously reconcile orders whose physical deletion finishes later."""

        while not self._stop.is_set():
            await self._deletion.resume_pending()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1)

    def stop(self) -> None:
        self._stop.set()

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
        requester_party_id = await self._resolve_requester_party(
            requester_kind, party_key
        )
        request = ExecutionCustodyRequest(
            ExecutionCustodyScope(
                ExecutionCustodyScopeKind.DATA_RIGHTS_PARTY, requester_party_id
            ),
            ExecutionCustodyMode.EXCLUSIVE,
        )
        async with self._custody.hold(
            ordered_custody_requests(request), deadline_at=None
        ):
            result = await self._record_request(
                requester_kind=requester_kind,
                party_key=party_key,
                command=command,
                requester_party_id=requester_party_id,
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
        deletion_ids = tuple(
            item.artifact_deletion_id
            for item in items
            if item.artifact_deletion_id is not None
        )
        states = {
            state.deletion_id: state
            for state in await self._lifecycle.deletion_states(
                unit.transaction, deletion_ids
            )
        }
        results: list[DataRightsDeletionItemResult] = []
        for item in items:
            deletion_id = item.artifact_deletion_id
            state = None if deletion_id is None else states.get(deletion_id)
            results.append(
                DataRightsDeletionItemResult(
                    item.item_id,
                    item.target_kind,
                    item.required_action,
                    DataRightsItemStatus(item.result_status),
                    item.remaining_location,
                    item.created_at,
                    item.completed_at,
                    item.artifact_deletion_id,
                    state is not None and state.status == "blocked",
                    0 if state is None else state.attempt_count,
                    None if state is None else state.last_error_code,
                )
            )
        return DataRightsOrderDetail(
            order=self._result(snapshot, False),
            items=tuple(results),
        )

    async def retry_creator(
        self, order_id: UUID, command: DataRightsRetryCommand
    ) -> DataRightsOrderResult:
        return await self._retry(
            requester_kind=DataRightsRequesterKind.CREATOR,
            party_key=None,
            order_id=order_id,
            command=command,
        )

    async def retry_other_human(
        self,
        party_key: DataRightsPartyKey,
        order_id: UUID,
        command: DataRightsRetryCommand,
    ) -> DataRightsOrderResult:
        return await self._retry(
            requester_kind=DataRightsRequesterKind.OTHER_HUMAN,
            party_key=party_key,
            order_id=order_id,
            command=command,
        )

    async def _retry(
        self,
        *,
        requester_kind: DataRightsRequesterKind,
        party_key: DataRightsPartyKey | None,
        order_id: UUID,
        command: DataRightsRetryCommand,
    ) -> DataRightsOrderResult:
        try:
            created = False
            async with self._uow_factory.unit_of_work() as unit:
                party_id = await self._requester_party(unit, requester_kind, party_key)
                await unit.transaction.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                    (f"data-rights:{party_id}",),
                )
                order = await self._repository.get(
                    unit, requester_party_id=party_id, order_id=order_id
                )
                if (
                    order is None
                    or order.order_kind is not DataRightsOrderKind.DELETE_RELATED
                ):
                    raise DataRightsViolation("DATA-RIGHTS-ORDER-NOT-FOUND")
                existing = await (
                    await unit.transaction.execute(
                        """SELECT retry_cycle FROM armi.deletion_order_retry_attempts
                           WHERE deletion_order_id=%s AND idempotency_key=%s""",
                        (order_id, command.idempotency_key.value),
                    )
                ).fetchone()
                if existing is None:
                    if order.execution_status is not DataRightsExecutionStatus.PARTIAL:
                        raise DataRightsViolation("DATA-RIGHTS-RETRY-NOT-AVAILABLE")
                    deletion_rows = await (
                        await unit.transaction.execute(
                            """SELECT artifact_object_deletion_id
                               FROM armi.deletion_items
                               WHERE deletion_order_id=%s AND result_status='partial'
                                 AND artifact_object_deletion_id IS NOT NULL""",
                            (order_id,),
                        )
                    ).fetchall()
                    deletion_ids = tuple(row[0] for row in deletion_rows)
                    states = await self._lifecycle.deletion_states(
                        unit.transaction, deletion_ids
                    )
                    blocked_ids = tuple(
                        state.deletion_id
                        for state in states
                        if state.status == "blocked"
                    )
                    if not blocked_ids:
                        raise DataRightsViolation("DATA-RIGHTS-RETRY-NOT-AVAILABLE")
                    cycle_row = await (
                        await unit.transaction.execute(
                            """SELECT COALESCE(max(retry_cycle),1)+1
                               FROM armi.deletion_order_retry_attempts
                               WHERE deletion_order_id=%s""",
                            (order_id,),
                        )
                    ).fetchone()
                    if cycle_row is None:
                        raise DataRightsViolation("DATA-RIGHTS-STATE")
                    cycle = int(cycle_row[0])
                    await unit.transaction.execute(
                        """INSERT INTO armi.deletion_order_retry_attempts
                           (deletion_order_retry_attempt_id,deletion_order_id,
                            retry_cycle,idempotency_key,trace_id)
                           VALUES (%s,%s,%s,%s,%s)""",
                        (
                            uuid7(),
                            order_id,
                            cycle,
                            command.idempotency_key.value,
                            command.trace_id.value,
                        ),
                    )
                    reset = await self._lifecycle.retry_blocked(
                        unit, blocked_ids, cycle
                    )
                    if reset != len(blocked_ids):
                        raise DataRightsViolation("DATA-RIGHTS-RETRY-STATE")
                    await unit.transaction.execute(
                        """UPDATE armi.deletion_items SET result_status='pending',
                                  remaining_location=NULL,completed_at=NULL
                           WHERE deletion_order_id=%s AND result_status='partial'
                             AND artifact_object_deletion_id IS NOT NULL""",
                        (order_id,),
                    )
                    await unit.transaction.execute(
                        """UPDATE armi.deletion_orders SET execution_status='executing',
                                  completed_at=NULL
                           WHERE deletion_order_id=%s AND execution_status='partial'""",
                        (order_id,),
                    )
                    created = True
            await self._deletion.execute(order_id)
            refreshed = await self._get(
                requester_kind=requester_kind,
                party_key=party_key,
                order_id=order_id,
            )
            if refreshed is None:
                raise DataRightsViolation("DATA-RIGHTS-STATE")
            await self._notify(order_id)
            return DataRightsOrderResult(
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
                created,
            )
        except DataRightsViolation:
            raise
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _notify(self, order_id: UUID) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("data_rights"),
                    str(order_id),
                    Instant(datetime.now(UTC)),
                    "data-rights-order-collection.v2",
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
        requester_party_id: UUID,
        _transaction_retry: int = 0,
    ) -> DataRightsOrderResult:
        try:
            async with self._uow_factory.unit_of_work(
                isolation=TransactionIsolation.SERIALIZABLE
            ) as unit_of_work:
                confirmed_party_id = await self._requester_party(
                    unit_of_work, requester_kind, party_key
                )
                if confirmed_party_id != requester_party_id:
                    raise DataRightsViolation("DATA-RIGHTS-REQUESTER")
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
                await self._repository.advance_fence(
                    unit_of_work.transaction,
                    party_id=requester_party_id,
                    order_kind=command.order_kind,
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
                apply_request = DataRightsApplyRequest(
                    snapshot.order_id,
                    requester_party_id,
                    command.order_kind.value,
                    (),
                    (),
                    (),
                )
                contribution = await self._order_participant.apply(
                    unit_of_work.transaction, apply_request
                )
                if (
                    contribution.owner_identity
                    != self._order_participant.owner_identity
                ):
                    raise DataRightsViolation("DATA-RIGHTS-PARTICIPANT-OWNER-MISMATCH")
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
        except RuntimeTransactionFailure as error:
            if (
                error.code in {"DB-TX-SERIALIZATION", "DB-TX-DEADLOCK"}
                and _transaction_retry < 2
            ):
                await asyncio.sleep(0)
                return await self._record_request(
                    requester_kind=requester_kind,
                    party_key=party_key,
                    command=command,
                    requester_party_id=requester_party_id,
                    _transaction_retry=_transaction_retry + 1,
                )
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _resolve_requester_party(
        self,
        requester_kind: DataRightsRequesterKind,
        party_key: DataRightsPartyKey | None,
    ) -> UUID:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit:
                return await self._requester_party(unit, requester_kind, party_key)
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
