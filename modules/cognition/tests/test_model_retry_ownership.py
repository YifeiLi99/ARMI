"""Model retry ownership stays at durable work before provider dispatch."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_cognition._model_postgresql import (
    PostgreSQLCognitiveModelRepository,
)
from armi_kernel.application import ModelAttemptId
from armi_kernel.contracts import TraceId


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


@pytest.mark.parametrize(
    ("dispatch_status", "creates_attempt"),
    (("prepared", True), ("dispatched", False)),
)
def test_model_attempt_recovery_only_replays_pre_dispatch(
    dispatch_status: str,
    creates_attempt: bool,
) -> None:
    episode_id = uuid7()
    previous_id = uuid7()
    lease = SimpleNamespace(
        work_id=SimpleNamespace(value=uuid7()),
        attempt_id=SimpleNamespace(value=uuid7()),
        owner=uuid7(),
        token=3,
    )

    async def execute(statement: str, _parameters: object = None) -> _Cursor:
        if "SELECT work_id" in statement:
            return _Cursor((lease.work_id.value,))
        if "SELECT model_attempt_id" in statement:
            return _Cursor((previous_id, dispatch_status))
        if "SELECT count(*)" in statement:
            return _Cursor((1,))
        if "UPDATE armi.cognitive_episodes" in statement and "RETURNING" in statement:
            return _Cursor((episode_id,))
        if "UPDATE armi.opportunities" in statement:
            return _Cursor((uuid7(),))
        return _Cursor()

    connection = SimpleNamespace(execute=AsyncMock(side_effect=execute))
    work = SimpleNamespace(fail=AsyncMock())
    unit_of_work = SimpleNamespace(
        transaction=connection,
        work=work,
        audit=SimpleNamespace(append=AsyncMock()),
        environment_id=uuid7(),
    )
    snapshot = SimpleNamespace(
        episode_id=episode_id,
        subject_id=uuid7(),
        trace_id=TraceId("a" * 32),
    )
    binding = SimpleNamespace(
        provider="provider",
        model_id="model",
        version_policy="pinned",
        profile="default",
        request_contract_version="request.v1",
        response_contract_version="response.v1",
        pricing_snapshot_id="pricing",
        credential_identity="credential",
    )
    request_artifact = SimpleNamespace(artifact_id=SimpleNamespace(value=uuid7()))

    result = asyncio.run(
        PostgreSQLCognitiveModelRepository().prepare_attempt(
            cast(Any, unit_of_work),
            lease=cast(Any, lease),
            snapshot=cast(Any, snapshot),
            binding=cast(Any, binding),
            request_artifact=cast(Any, request_artifact),
        )
    )

    statements = tuple(call.args[0] for call in connection.execute.await_args_list)
    assert any("result_status = 'cancelled'" in item for item in statements) is (
        dispatch_status == "prepared"
    )
    assert any(
        "INSERT INTO armi.cognitive_attempts" in item for item in statements
    ) is (creates_attempt)
    if creates_attempt:
        assert isinstance(result, ModelAttemptId)
        work.fail.assert_not_awaited()
    else:
        assert result is None
        work.fail.assert_awaited_once_with(
            lease,
            error_code="MODEL-OUTCOME-UNKNOWN",
        )
