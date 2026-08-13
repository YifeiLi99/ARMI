"""PostgreSQL owner for requester-scoped local data-right orders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from armi_kernel.contracts import Digest, Instant
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import (
    DataRightsExecutionStatus,
    DataRightsOrderKind,
    DataRightsRequesterKind,
    DataRightsScopeKind,
    DataRightsViolation,
)


@dataclass(frozen=True, slots=True)
class DataRightsOrderSnapshot:
    order_id: UUID
    requester_party_id: UUID
    requester_kind: DataRightsRequesterKind
    order_kind: DataRightsOrderKind
    scope_kind: DataRightsScopeKind
    scope_party_id: UUID
    execution_status: DataRightsExecutionStatus
    idempotency_key: str
    request_digest: Digest
    effective_at: Instant
    completed_at: Instant | None


@dataclass(frozen=True, slots=True)
class DataRightsDeletionItemSnapshot:
    item_id: UUID
    target_kind: str
    required_action: str
    result_status: str
    remaining_location: str | None
    created_at: Instant
    completed_at: Instant | None


class DataRightsOrderRepository:
    __slots__ = ()

    async def find_existing(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        requester_party_id: UUID,
        order_kind: DataRightsOrderKind,
        idempotency_key: str,
        lock: bool,
    ) -> DataRightsOrderSnapshot | None:
        connection = unit_of_work.transaction
        locking = "FOR UPDATE" if lock else ""
        row = await (
            await connection.execute(
                f"""
                SELECT deletion_order_id, requester_party_id, requester_kind,
                       order_kind, scope_kind, scope_party_id, execution_status,
                       idempotency_key, request_digest, effective_at, completed_at
                FROM armi.deletion_orders
                WHERE requester_party_id = %s
                  AND (idempotency_key = %s OR order_kind = %s)
                {locking}
                """,
                (requester_party_id, idempotency_key, order_kind.value),
            )
        ).fetchone()
        return None if row is None else _snapshot(row)

    async def insert(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        order_id: UUID,
        requester_party_id: UUID,
        requester_kind: DataRightsRequesterKind,
        order_kind: DataRightsOrderKind,
        scope_kind: DataRightsScopeKind,
        execution_status: DataRightsExecutionStatus,
        idempotency_key: str,
        request_digest: Digest,
        trace_id: str,
    ) -> DataRightsOrderSnapshot:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                INSERT INTO armi.deletion_orders (
                    deletion_order_id, requester_party_id, requester_kind,
                    order_kind, scope_kind, scope_party_id, reason_code, status,
                    execution_status, idempotency_key, request_digest, trace_id
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    'requester_exercised_local_right', 'effective',
                    %s, %s, %s, %s
                )
                RETURNING deletion_order_id, requester_party_id, requester_kind,
                          order_kind, scope_kind, scope_party_id, execution_status,
                          idempotency_key, request_digest, effective_at, completed_at
                """,
                (
                    order_id,
                    requester_party_id,
                    requester_kind.value,
                    order_kind.value,
                    scope_kind.value,
                    requester_party_id,
                    execution_status.value,
                    idempotency_key,
                    request_digest.value,
                    trace_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise DataRightsViolation("DATA-RIGHTS-STATE")
        return _snapshot(row)

    async def get(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        requester_party_id: UUID,
        order_id: UUID,
    ) -> DataRightsOrderSnapshot | None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT deletion_order_id, requester_party_id, requester_kind,
                       order_kind, scope_kind, scope_party_id, execution_status,
                       idempotency_key, request_digest, effective_at, completed_at
                FROM armi.deletion_orders
                WHERE deletion_order_id = %s AND requester_party_id = %s
                """,
                (order_id, requester_party_id),
            )
        ).fetchone()
        return None if row is None else _snapshot(row)

    async def list_orders(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        requester_party_id: UUID | None,
    ) -> tuple[DataRightsOrderSnapshot, ...]:
        connection = unit_of_work.transaction
        scope = "" if requester_party_id is None else "WHERE requester_party_id = %s"
        parameters: tuple[object, ...] = (
            () if requester_party_id is None else (requester_party_id,)
        )
        rows = await (
            await connection.execute(
                f"""
                SELECT deletion_order_id, requester_party_id, requester_kind,
                       order_kind, scope_kind, scope_party_id, execution_status,
                       idempotency_key, request_digest, effective_at, completed_at
                FROM armi.deletion_orders
                {scope}
                ORDER BY effective_at DESC, deletion_order_id DESC
                """,
                parameters,
            )
        ).fetchall()
        return tuple(_snapshot(row) for row in rows)

    async def get_any(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, order_id: UUID
    ) -> DataRightsOrderSnapshot | None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT deletion_order_id, requester_party_id, requester_kind,
                       order_kind, scope_kind, scope_party_id, execution_status,
                       idempotency_key, request_digest, effective_at, completed_at
                FROM armi.deletion_orders WHERE deletion_order_id = %s
                """,
                (order_id,),
            )
        ).fetchone()
        return None if row is None else _snapshot(row)

    async def deletion_items(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, order_id: UUID
    ) -> tuple[DataRightsDeletionItemSnapshot, ...]:
        connection = unit_of_work.transaction
        rows = await (
            await connection.execute(
                """
                SELECT deletion_item_id, target_kind, required_action,
                       result_status, remaining_location, created_at, completed_at
                FROM armi.deletion_items
                WHERE deletion_order_id = %s
                ORDER BY created_at, deletion_item_id
                """,
                (order_id,),
            )
        ).fetchall()
        return tuple(
            DataRightsDeletionItemSnapshot(
                item_id=row[0],
                target_kind=str(row[1]),
                required_action=str(row[2]),
                result_status=str(row[3]),
                remaining_location=None if row[4] is None else str(row[4]),
                created_at=Instant(row[5]),
                completed_at=None if row[6] is None else Instant(row[6]),
            )
            for row in rows
        )

    async def blocks_new_interaction(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        requester_party_id: UUID,
    ) -> bool:
        connection = unit_of_work.transaction
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"data-rights:{requester_party_id}",),
        )
        row = await (
            await connection.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM armi.deletion_orders
                    WHERE requester_party_id = %s
                      AND status = 'effective'
                      AND order_kind IN (
                          'stop_contact', 'stop_use', 'delete_related'
                      )
                )
                """,
                (requester_party_id,),
            )
        ).fetchone()
        return row is not None and bool(row[0])


def _snapshot(row: tuple[Any, ...]) -> DataRightsOrderSnapshot:
    return DataRightsOrderSnapshot(
        order_id=row[0],
        requester_party_id=row[1],
        requester_kind=DataRightsRequesterKind(str(row[2])),
        order_kind=DataRightsOrderKind(str(row[3])),
        scope_kind=DataRightsScopeKind(str(row[4])),
        scope_party_id=row[5],
        execution_status=DataRightsExecutionStatus(str(row[6])),
        idempotency_key=str(row[7]),
        request_digest=Digest(str(row[8])),
        effective_at=Instant(row[9]),
        completed_at=None if row[10] is None else Instant(row[10]),
    )


__all__ = (
    "DataRightsDeletionItemSnapshot",
    "DataRightsOrderRepository",
    "DataRightsOrderSnapshot",
)
