"""Creator and built-in other-human local data-right command service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid7

import psycopg
import rfc8785
from armi_kernel.application import (
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    DataRightsExecutionStatus,
    DataRightsOrderCommand,
    DataRightsOrderKind,
    DataRightsOrderPort,
    DataRightsOrderResult,
    DataRightsRequesterKind,
    DataRightsScopeKind,
    DataRightsViolation,
    LockPlan,
    LockTarget,
    OtherHumanPartyKey,
    RuntimeFence,
)
from armi_kernel.contracts import Digest, Purpose

from armi_runtime.adapters.persistence.data_rights import (
    DataRightsOrderRepository,
    DataRightsOrderSnapshot,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError


class DataRightsOrderService(DataRightsOrderPort):
    __slots__ = ("_creator_party_id", "_repository", "_uow_factory")

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        repository: DataRightsOrderRepository,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    ) -> None:
        if creator_party_id.version != 7:
            raise DataRightsViolation("DATA-RIGHTS-COMPOSITION")
        self._creator_party_id = creator_party_id
        self._repository = repository
        self._uow_factory = unit_of_work_factory

    async def open(self) -> None:
        try:
            await self._uow_factory.open()
        except DatabaseTransactionError:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._uow_factory.close()

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
        party_key: OtherHumanPartyKey,
        command: DataRightsOrderCommand,
    ) -> DataRightsOrderResult:
        if type(party_key) is not OtherHumanPartyKey:
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER")
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
        party_key: OtherHumanPartyKey,
        order_id: UUID,
    ) -> DataRightsOrderResult | None:
        if type(party_key) is not OtherHumanPartyKey:
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER")
        return await self._get(
            requester_kind=DataRightsRequesterKind.OTHER_HUMAN,
            party_key=party_key,
            order_id=order_id,
        )

    async def _request(
        self,
        *,
        requester_kind: DataRightsRequesterKind,
        party_key: OtherHumanPartyKey | None,
        command: DataRightsOrderCommand,
    ) -> DataRightsOrderResult:
        if type(command) is not DataRightsOrderCommand:
            raise DataRightsViolation("DATA-RIGHTS-COMMAND")
        try:
            async with self._uow_factory.unit_of_work(LockPlan()) as unit_of_work:
                requester_party_id = await self._requester_party(
                    unit_of_work, requester_kind, party_key
                )
                await unit_of_work._connection_for_repository().execute(  # pyright: ignore[reportPrivateUsage]
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
                        request_digest=request_digest,
                    )
                )
                return self._result(snapshot, newly_created=True)
        except DataRightsViolation:
            raise
        except DatabaseTransactionError:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _get(
        self,
        *,
        requester_kind: DataRightsRequesterKind,
        party_key: OtherHumanPartyKey | None,
        order_id: UUID,
    ) -> DataRightsOrderResult | None:
        if type(order_id) is not UUID or order_id.version != 7:
            raise DataRightsViolation("DATA-RIGHTS-ORDER-ID")
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(), read_only=True
            ) as unit_of_work:
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
        except DatabaseTransactionError:
            raise DataRightsViolation("DATA-RIGHTS-UNAVAILABLE") from None

    async def _requester_party(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        requester_kind: DataRightsRequesterKind,
        party_key: OtherHumanPartyKey | None,
    ) -> UUID:
        if requester_kind is DataRightsRequesterKind.CREATOR:
            return await self._repository.creator_party(
                unit_of_work, self._creator_party_id
            )
        if party_key is None:
            raise DataRightsViolation("DATA-RIGHTS-REQUESTER")
        return await self._repository.other_human_party(unit_of_work, party_key)

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


async def _unused_lock_acquirer(
    connection: psycopg.AsyncConnection[tuple[Any, ...]], target: LockTarget
) -> None:
    del connection, target
    raise DataRightsViolation("DATA-RIGHTS-LOCK")


def build_data_rights_order_service(
    conninfo: str,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
) -> DataRightsOrderService:
    return DataRightsOrderService(
        creator_party_id=creator_party_id,
        repository=DataRightsOrderRepository(),
        unit_of_work_factory=PostgreSQLUnitOfWorkFactory(
            conninfo,
            environment_id=environment_id,
            lock_acquirer=_unused_lock_acquirer,
            pool_min=pool_min,
            pool_max=pool_max,
            acquire_timeout_seconds=acquire_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            authority_admission=authority_admission,
        ),
    )


__all__ = ("DataRightsOrderService", "build_data_rights_order_service")
