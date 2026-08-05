from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid7

import pytest
from armi_kernel.application import AuditDraft
from armi_runtime.adapters.persistence.effect_grant_coordination import (
    coordinate_dispatch_boundary,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWork


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(self, *, revoked: bool) -> None:
        self.revoked = revoked
        self.ids = {name: uuid7() for name in ("grant", "policy", "revision", "operation")}
        self.statements: list[str] = []

    async def execute(
        self, query: str, params: tuple[object, ...] = ()
    ) -> _Cursor:
        statement = " ".join(query.split())
        self.statements.append(statement)
        if "SELECT policy.matched_grant_id" in statement:
            return _Cursor((self.ids["grant"],))
        if "FROM armi.permission_grants" in statement:
            return _Cursor(("revoked", False) if self.revoked else ("active", True))
        if "SELECT policy.is_current" in statement:
            return _Cursor(
                (
                    True,
                    True,
                    uuid7(),
                    "respond_to_creator",
                    "1" * 32,
                    self.ids["policy"],
                    self.ids["revision"],
                    self.ids["operation"],
                )
            )
        if "UPDATE armi.effect_attempts" in statement:
            return _Cursor((datetime.now(UTC),))
        if "UPDATE armi.effects" in statement:
            return _Cursor((params[1],))
        if "UPDATE armi.effect_outbox_items" in statement:
            return _Cursor((params[1],))
        if "UPDATE armi.policy_decisions SET is_current=false" in statement:
            return _Cursor((self.ids["policy"],))
        if "INSERT INTO armi.policy_decisions" in statement:
            return _Cursor()
        if "UPDATE armi.creator_response_operations" in statement:
            return _Cursor((self.ids["operation"],))
        raise AssertionError(f"unexpected statement: {statement}")


class _Audit:
    def __init__(self) -> None:
        self.events: list[AuditDraft] = []

    async def append(self, draft: AuditDraft) -> None:
        self.events.append(draft)


class _UnitOfWork:
    def __init__(self, connection: _Connection) -> None:
        self.environment_id = uuid7()
        self.audit = _Audit()
        self._connection = connection

    def _connection_for_repository(self) -> _Connection:
        return self._connection


@pytest.mark.asyncio
async def test_active_grant_crosses_dispatch_boundary_without_cancellation() -> None:
    connection = _Connection(revoked=False)
    uow = _UnitOfWork(connection)

    result = await _coordinate(uow)

    assert result is not None and result.allowed
    assert not uow.audit.events
    assert not any("UPDATE armi.effect_attempts" in item for item in connection.statements)


@pytest.mark.asyncio
async def test_revoked_grant_cancels_prepared_attempt_before_dispatch() -> None:
    connection = _Connection(revoked=True)
    uow = _UnitOfWork(connection)

    result = await _coordinate(uow)

    assert result is not None and not result.allowed
    assert result.reason_code == "POLICY-GRANT-REVOKED"
    assert any("result_status='cancelled'" in item for item in connection.statements)
    assert any("decision_outcome" in item for item in connection.statements)
    assert len(uow.audit.events) == 1
    assert uow.audit.events[0].operation == "effect.cancelled"


async def _coordinate(uow: _UnitOfWork):
    return await coordinate_dispatch_boundary(
        cast(PostgreSQLUnitOfWork, cast(Any, uow)),
        effect_id=uuid7(),
        attempt_id=uuid7(),
        outbox_id=uuid7(),
        claim_owner=uuid7(),
        claim_token=1,
        expected_operation_status="effect_dispatching",
        cancelled_operation_status="effect_cancelled",
    )
