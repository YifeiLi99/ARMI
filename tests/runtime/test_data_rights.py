from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import uuid7

import pytest
from armi_kernel.application import (
    DataRightsExecutionStatus,
    DataRightsOrderCommand,
    DataRightsOrderKind,
    DataRightsOrderResult,
    DataRightsRequesterKind,
    DataRightsScopeKind,
    DataRightsViolation,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, TraceId
from armi_runtime.adapters.persistence.data_rights import DataRightsOrderRepository
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWork


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, blocked: bool) -> None:
        self.blocked = blocked
        self.statements: list[str] = []

    async def execute(
        self, statement: str, parameters: tuple[object, ...] = ()
    ) -> _Cursor:
        del parameters
        self.statements.append(statement)
        return _Cursor((self.blocked,))


class _UnitOfWork:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection

    def _connection_for_repository(self) -> _Connection:
        return self.connection


def test_three_order_kinds_are_explicit_and_bounded() -> None:
    for kind in DataRightsOrderKind:
        command = DataRightsOrderCommand(
            kind,
            IdempotencyKey(f"data-right-{kind.value}"),
            TraceId("1" * 32),
        )
        assert command.order_kind is kind
    with pytest.raises(ValueError):
        DataRightsOrderKind("delete_all_life")


def test_delete_related_tracks_pending_and_terminal_s015_execution() -> None:
    party_id = uuid7()
    now = Instant(datetime.now(UTC))
    result = DataRightsOrderResult(
        uuid7(),
        party_id,
        DataRightsRequesterKind.OTHER_HUMAN,
        DataRightsOrderKind.DELETE_RELATED,
        DataRightsScopeKind.PARTY_LOCAL_DATA,
        party_id,
        "effective",
        DataRightsExecutionStatus.PENDING,
        Digest.from_bytes(b"request"),
        now,
        None,
        True,
    )
    assert result.execution_status is DataRightsExecutionStatus.PENDING
    for status in (
        DataRightsExecutionStatus.COMPLETED,
        DataRightsExecutionStatus.PARTIAL,
    ):
        settled = DataRightsOrderResult(
            uuid7(),
            party_id,
            DataRightsRequesterKind.OTHER_HUMAN,
            DataRightsOrderKind.DELETE_RELATED,
            DataRightsScopeKind.PARTY_LOCAL_DATA,
            party_id,
            "effective",
            status,
            Digest.from_bytes(b"request"),
            now,
            now,
            False,
        )
        assert settled.completed_at == now
    with pytest.raises(DataRightsViolation):
        DataRightsOrderResult(
            uuid7(),
            party_id,
            DataRightsRequesterKind.OTHER_HUMAN,
            DataRightsOrderKind.DELETE_RELATED,
            DataRightsScopeKind.PARTY_LOCAL_DATA,
            party_id,
            "effective",
            DataRightsExecutionStatus.NOT_REQUIRED,
            Digest.from_bytes(b"request"),
            now,
            None,
            True,
        )


@pytest.mark.parametrize("blocked", [False, True])
def test_effective_order_guard_controls_new_interactions(blocked: bool) -> None:
    connection = _Connection(blocked)
    repository = DataRightsOrderRepository()
    observed = asyncio.run(
        repository.blocks_new_interaction(
            cast(PostgreSQLUnitOfWork, _UnitOfWork(connection)),
            uuid7(),
        )
    )
    assert observed is blocked
    assert "pg_advisory_xact_lock" in connection.statements[0]
    statement = connection.statements[1]
    assert "status = 'effective'" in statement
    assert "'stop_contact', 'stop_use', 'delete_related'" in statement
