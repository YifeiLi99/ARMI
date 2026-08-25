"""Creator and built-in other-human local data-right command service."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
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
    DataRightsArtifactLifecyclePort,
    DataRightsExecutionStatus,
    DataRightsItemStatus,
    DataRightsOrderCommand,
    DataRightsOrderDetail,
    DataRightsOrderItemResult,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResult,
    DataRightsOwnerContract,
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
        "_data_root",
        "_deletion",
        "_identity_key",
        "_lifecycle",
        "_notifier",
        "_owner_contracts",
        "_participant_owners",
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
        owner_contracts: tuple[DataRightsOwnerContract, ...],
        identity_key: str,
        data_root: Path,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        if creator_party_id.version != 7:
            raise DataRightsViolation("DATA-RIGHTS-COMPOSITION")
        self._creator_party_id = creator_party_id
        self._custody = custody
        self._deletion = deletion
        self._identity_key = identity_key
        self._data_root = data_root
        self._lifecycle = lifecycle
        self._repository = repository
        self._uow_factory = unit_of_work_factory
        self._notifier = notifier
        self._parties = parties
        if not participants:
            raise DataRightsViolation("DATA-RIGHTS-COMPOSITION")
        self._owner_contracts = owner_contracts
        self._participant_owners = tuple(
            participant.owner_identity.value for participant in participants
        )
        self._stop = asyncio.Event()

    async def open(self) -> None:
        try:
            async with self._uow_factory.unit_of_work(
                isolation=TransactionIsolation.SERIALIZABLE
            ) as unit:
                await self._validate_owner_contracts(unit)
                await unit.transaction.execute(
                    """INSERT INTO armi.data_rights_identity_keys
                       (singleton_key,key_identity) VALUES (1,%s)
                       ON CONFLICT (singleton_key) DO NOTHING""",
                    (self._identity_key,),
                )
                row = await (
                    await unit.transaction.execute(
                        """SELECT key_identity FROM armi.data_rights_identity_keys
                           WHERE singleton_key=1"""
                    )
                ).fetchone()
                if row is None or str(row[0]) != self._identity_key:
                    raise DataRightsViolation("DATA-RIGHTS-IDENTITY-KEY-MISMATCH")
            await self._deletion.resume_pending()
        except RuntimeTransactionFailure:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _validate_owner_contracts(
        self, unit: PostgreSQLRuntimeUnitOfWork
    ) -> None:
        owners = [contract.owner_identity.value for contract in self._owner_contracts]
        if len(owners) != len(set(owners)):
            raise DataRightsViolation("DATA-RIGHTS-LINEAGE-DUPLICATE-OWNER")
        if set(owners) != set(self._participant_owners):
            raise DataRightsViolation("DATA-RIGHTS-LINEAGE-OWNER-COVERAGE")
        declared = [
            (field.table_name, field.column_name)
            for contract in self._owner_contracts
            for field in contract.artifact_fields
        ]
        if len(declared) != len(set(declared)):
            raise DataRightsViolation("DATA-RIGHTS-LINEAGE-DUPLICATE-ARTIFACT-FK")
        rows = await (
            await unit.transaction.execute(
                """SELECT source_table.relname,source_column.attname
                   FROM pg_catalog.pg_constraint AS fk
                   JOIN pg_catalog.pg_class AS source_table
                     ON source_table.oid=fk.conrelid
                   JOIN pg_catalog.pg_namespace AS source_namespace
                     ON source_namespace.oid=source_table.relnamespace
                   JOIN pg_catalog.pg_class AS target_table
                     ON target_table.oid=fk.confrelid
                   JOIN pg_catalog.pg_namespace AS target_namespace
                     ON target_namespace.oid=target_table.relnamespace
                   JOIN pg_catalog.pg_attribute AS source_column
                     ON source_column.attrelid=source_table.oid
                    AND source_column.attnum=fk.conkey[1]
                   JOIN pg_catalog.pg_attribute AS target_column
                     ON target_column.attrelid=target_table.oid
                    AND target_column.attnum=fk.confkey[1]
                   WHERE fk.contype='f'
                     AND pg_catalog.cardinality(fk.conkey)=1
                     AND pg_catalog.cardinality(fk.confkey)=1
                     AND source_namespace.nspname='armi'
                     AND target_namespace.nspname='armi'
                     AND target_table.relname='artifacts'
                     AND target_column.attname='artifact_id'
                   ORDER BY source_table.relname,source_column.attname"""
            )
        ).fetchall()
        installed = [(str(row[0]), str(row[1])) for row in rows]
        if sorted(declared) != installed:
            raise DataRightsViolation("DATA-RIGHTS-LINEAGE-ARTIFACT-FK-COVERAGE")

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
        items = await self._repository.data_rights_order_items(unit, snapshot.order_id)
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
        results: list[DataRightsOrderItemResult] = []
        for item in items:
            deletion_id = item.artifact_deletion_id
            state = None if deletion_id is None else states.get(deletion_id)
            results.append(
                DataRightsOrderItemResult(
                    item_id=item.item_id,
                    target_kind=item.target_kind,
                    required_action=item.required_action,
                    responsible_owner=item.responsible_owner,
                    result_status=DataRightsItemStatus(item.result_status),
                    retention_reason=item.retention_reason,
                    created_at=item.created_at,
                    completed_at=item.completed_at,
                    artifact_deletion_id=item.artifact_deletion_id,
                    retryable=(
                        item.operator_action_required
                        or (state is not None and state.status == "blocked")
                    ),
                    deletion_attempt_count=0 if state is None else state.attempt_count,
                    last_error_code=None if state is None else state.last_error_code,
                    operator_action_required=item.operator_action_required,
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
            operator_snapshots = await self._operator_snapshot_paths(
                requester_kind=requester_kind,
                party_key=party_key,
                order_id=order_id,
            )
            removable: list[UUID] = []
            for snapshot_id, raw_path in operator_snapshots:
                if await asyncio.to_thread(self._managed_snapshot_is_absent, raw_path):
                    removable.append(snapshot_id)
            removable_snapshot_ids = tuple(removable)
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
                        """SELECT retry_cycle FROM armi.data_rights_order_retry_attempts
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
                               FROM armi.data_rights_order_items
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
                    if not blocked_ids and not removable_snapshot_ids:
                        raise DataRightsViolation("DATA-RIGHTS-RETRY-NOT-AVAILABLE")
                    cycle_row = await (
                        await unit.transaction.execute(
                            """SELECT COALESCE(max(retry_cycle),1)+1
                               FROM armi.data_rights_order_retry_attempts
                               WHERE deletion_order_id=%s""",
                            (order_id,),
                        )
                    ).fetchone()
                    if cycle_row is None:
                        raise DataRightsViolation("DATA-RIGHTS-STATE")
                    cycle = int(cycle_row[0])
                    await unit.transaction.execute(
                        """INSERT INTO armi.data_rights_order_retry_attempts
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
                    if removable_snapshot_ids:
                        await unit.transaction.execute(
                            """UPDATE armi.managed_data_snapshots
                               SET status='removed',removed_at=statement_timestamp()
                               WHERE managed_snapshot_id=ANY(%s::uuid[])
                                 AND status='active'""",
                            (list(removable_snapshot_ids),),
                        )
                        await unit.transaction.execute(
                            """UPDATE armi.data_rights_order_items
                               SET result_status='completed',
                                   operator_action_required=false,
                                   completed_at=statement_timestamp()
                               WHERE deletion_order_id=%s
                                 AND target_kind='managed_snapshot'
                                 AND target_ref=ANY(%s::uuid[])
                                 AND result_status='partial'""",
                            (order_id, list(removable_snapshot_ids)),
                        )
                    await unit.transaction.execute(
                        """UPDATE armi.data_rights_order_items SET result_status='pending',
                                  retention_reason=NULL,completed_at=NULL
                           WHERE deletion_order_id=%s AND result_status='partial'
                             AND artifact_object_deletion_id IS NOT NULL""",
                        (order_id,),
                    )
                    await unit.transaction.execute(
                        """UPDATE armi.data_rights_orders SET execution_status='executing',
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

    async def _operator_snapshot_paths(
        self,
        *,
        requester_kind: DataRightsRequesterKind,
        party_key: DataRightsPartyKey | None,
        order_id: UUID,
    ) -> tuple[tuple[UUID, str], ...]:
        async with self._uow_factory.unit_of_work(read_only=True) as unit:
            party_id = await self._requester_party(unit, requester_kind, party_key)
            order = await self._repository.get(
                unit, requester_party_id=party_id, order_id=order_id
            )
            if order is None:
                raise DataRightsViolation("DATA-RIGHTS-ORDER-NOT-FOUND")
            rows = await (
                await unit.transaction.execute(
                    """SELECT snapshot.managed_snapshot_id,snapshot.managed_path
                       FROM armi.data_rights_order_items AS item
                       JOIN armi.managed_data_snapshots AS snapshot
                         ON snapshot.managed_snapshot_id=item.target_ref
                       WHERE item.deletion_order_id=%s
                         AND item.target_kind='managed_snapshot'
                         AND item.result_status='partial'
                         AND snapshot.status='active'
                       ORDER BY snapshot.managed_snapshot_id""",
                    (order_id,),
                )
            ).fetchall()
        return tuple((UUID(str(row[0])), str(row[1])) for row in rows)

    def _managed_snapshot_is_absent(self, raw_path: str) -> bool:
        path = Path(raw_path)
        if not path.is_absolute():
            raise DataRightsViolation("DATA-RIGHTS-MANAGED-SNAPSHOT-PATH")
        return not path.exists()

    async def _notify(self, order_id: UUID) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorResourceKind("data_rights"),
                    str(order_id),
                    Instant(datetime.now(UTC)),
                    "data-rights-order-collection.v3",
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
                execution_status = DataRightsExecutionStatus.PENDING
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
                await self._deletion.prepare_in(unit_of_work, snapshot.order_id)
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
                closed = await self._repository.get(
                    unit_of_work,
                    requester_party_id=requester_party_id,
                    order_id=snapshot.order_id,
                )
                if closed is None:
                    raise DataRightsViolation("DATA-RIGHTS-STATE")
                return self._result(closed, newly_created=True)
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
