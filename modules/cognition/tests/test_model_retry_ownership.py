"""Model retry ownership stays at durable work before provider dispatch."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
import rfc8785
from armi_cognition._model_application import (
    ModelPipeline,
    _DeterministicMoodReflectionAdapter,
)
from armi_cognition._model_postgresql import (
    ModelBranchSnapshot,
    ModelEpisodeSnapshot,
    PostgreSQLCognitiveModelRepository,
)
from armi_cognition._recovery import CognitionRecoveryParticipant
from armi_kernel.application import ModelAttemptId, ModelViolation
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import RecoveryWorkSnapshot


def test_mood_reflection_adapter_uses_no_provider_and_authors_no_vad() -> None:
    adapter = _DeterministicMoodReflectionAdapter(
        cast(Any, SimpleNamespace(model_id="configured-model"))
    )
    request = SimpleNamespace(
        canonical_bytes=rfc8785.dumps(
            {
                "compiled_context": {
                    "layers": [
                        {
                            "items": [
                                {
                                    "item_kind": "mood",
                                    "source": {"version": 7},
                                }
                            ]
                        }
                    ]
                },
                "included_context_refs": [
                    {"ref": "ctx:3", "item_kind": "current_maintenance_phase"},
                    {"ref": "ctx:5", "item_kind": "mood"},
                ],
            }
        )
    )
    result = asyncio.run(adapter.invoke(cast(Any, request)))
    assert result.response_bytes is not None
    response = json.loads(result.response_bytes)
    assert response["expected_version"] == 7
    assert response["next_state"] == {}
    assert "valence" not in result.response_bytes.decode("utf-8")


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    async def fetchall(self) -> list[tuple[object, ...]]:
        return []


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
        if "UPDATE armi.cognitive_branches" in statement and "RETURNING" in statement:
            return _Cursor((branch.branch_id,))
        if "UPDATE armi.cognitive_episodes" in statement and "RETURNING" in statement:
            return _Cursor((episode_id,))
        if "SELECT opportunity_id FROM armi.cognitive_episodes" in statement:
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
    branch = SimpleNamespace(branch_id=uuid7())
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

    opportunities = SimpleNamespace(
        resolve_cognition_failure=AsyncMock(return_value=True)
    )
    result = asyncio.run(
        PostgreSQLCognitiveModelRepository(
            cast(Any, SimpleNamespace()),
            cast(Any, SimpleNamespace()),
            cast(Any, opportunities),
        ).prepare_attempt(
            cast(Any, unit_of_work),
            lease=cast(Any, lease),
            snapshot=cast(Any, snapshot),
            branch=cast(Any, branch),
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
        work.fail.assert_not_awaited()


def test_retryable_preparation_failure_settles_on_final_work_attempt() -> None:
    episode_id = uuid7()
    lease = cast(Any, SimpleNamespace())
    work = SimpleNamespace(release=AsyncMock())
    unit_of_work = SimpleNamespace(work=work)

    @asynccontextmanager
    async def unit_of_work_context():
        yield unit_of_work

    repository = SimpleNamespace(fail_before_attempt=AsyncMock())
    repository.fail_episode = AsyncMock()
    pipeline = object.__new__(ModelPipeline)
    pipeline._factory = cast(Any, SimpleNamespace(unit_of_work=unit_of_work_context))
    pipeline._repository = cast(Any, repository)
    pipeline._diagnostic = cast(Any, lambda _event: None)
    snapshot = ModelEpisodeSnapshot(
        episode_id,
        uuid7(),
        "consider_creator_input",
        1,
        0,
        uuid7(),
        Digest.from_bytes(b"context"),
        cast(Any, SimpleNamespace()),
        (),
        (),
        TraceId("a" * 32),
        (ModelBranchSnapshot(uuid7(), "primary", "prepared", None, None, None, 0),),
    )
    record = cast(
        Any,
        SimpleNamespace(attempt_count=2, draft=SimpleNamespace(max_attempts=2)),
    )

    asyncio.run(
        pipeline._settle_before_attempt(
            record,
            lease,
            snapshot,
            ModelViolation("MODEL-CONNECTION"),
        )
    )

    work.release.assert_not_awaited()
    repository.fail_before_attempt.assert_awaited_once_with(
        unit_of_work,
        lease=lease,
        snapshot=snapshot,
        branch=snapshot.branches[0],
        code="MODEL-CONNECTION",
    )
    repository.fail_episode.assert_awaited_once()


def test_recovery_fails_episode_when_model_work_exhausted() -> None:
    episode_id = uuid7()
    opportunity_id = uuid7()
    statements: list[str] = []

    async def execute(statement: str, _parameters: object = None) -> _Cursor:
        statements.append(statement)
        if "dispatch_status='dispatched'" in statement:
            return _Cursor()
        if "SELECT opportunity_id, status" in statement:
            return cast(Any, _RowsCursor([(opportunity_id, "failed")]))
        if "SELECT cognitive_episode_id, status" in statement:
            return cast(Any, _RowsCursor([]))
        return _Cursor()

    contribution = asyncio.run(
        CognitionRecoveryParticipant().recover(
            cast(Any, SimpleNamespace(execute=execute)),
            cast(Any, None),
            (
                RecoveryWorkSnapshot(
                    uuid7(),
                    "cognition.model.invoke",
                    "cognitive_episode",
                    episode_id,
                    "failed",
                    2,
                    2,
                ),
            ),
        )
    )

    assert any("MODEL-WORK-ATTEMPTS-EXHAUSTED" in item for item in statements)
    assert contribution.findings[0].reference == opportunity_id


class _RowsCursor(_Cursor):
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        super().__init__()
        self._rows = rows

    async def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows
