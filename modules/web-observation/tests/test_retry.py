"""Web retry ownership only recreates attempts not sent to the provider."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_kernel.contracts import Digest
from armi_web_observation._observation_postgresql import (
    PostgreSQLWebObservationRepository,
)
from armi_web_observation.api import WebObservationAttemptId


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


@pytest.mark.parametrize(
    ("dispatch_state", "creates_attempt"),
    (("prepared", True), ("dispatched", False)),
)
def test_web_attempt_recovery_only_replays_pre_dispatch(
    dispatch_state: str,
    creates_attempt: bool,
) -> None:
    request_id = uuid7()
    previous_id = uuid7()
    lease = SimpleNamespace(
        work_id=SimpleNamespace(value=uuid7()),
        attempt_id=SimpleNamespace(value=uuid7()),
        owner=uuid7(),
        token=5,
    )

    async def execute(statement: str, _parameters: object = None) -> _Cursor:
        if "SELECT work.work_id" in statement:
            return _Cursor((lease.work_id.value,))
        if "SELECT observation_attempt_id" in statement:
            return _Cursor((previous_id, dispatch_state))
        return _Cursor()

    connection = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    work = SimpleNamespace(fail=AsyncMock())
    unit_of_work = SimpleNamespace(
        transaction=connection,
        work=work,
    )
    snapshot = SimpleNamespace(
        request_id=SimpleNamespace(value=request_id),
        attempt_count=1,
    )

    result = asyncio.run(
        PostgreSQLWebObservationRepository(cast(Any, object())).prepare_attempt(
            cast(Any, unit_of_work),
            lease=cast(Any, lease),
            snapshot=cast(Any, snapshot),
            credential_identity=Digest("sha256:" + "a" * 64),
        )
    )

    statements = tuple(call.args[0] for call in connection.execute.await_args_list)
    assert any("result_status = 'cancelled'" in item for item in statements) is (
        dispatch_state == "prepared"
    )
    assert any(
        "INSERT INTO armi.observation_attempts" in item for item in statements
    ) is (creates_attempt)
    if creates_attempt:
        assert isinstance(result, WebObservationAttemptId)
        work.fail.assert_not_awaited()
    else:
        assert result is None
        work.fail.assert_awaited_once_with(
            lease,
            error_code="WEB-RECOVERY-OUTCOME-UNKNOWN",
        )
