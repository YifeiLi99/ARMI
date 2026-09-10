"""One execution owns the model result, finalization and cancellation."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_cognition import _model_application as model
from armi_cognition._model_postgresql import ModelEpisodeSnapshot
from armi_kernel.application import (
    CandidateViolation,
    ModelInvocationResult,
    ModelResultStatus,
    ModelUsage,
)
from armi_kernel.contracts import Digest, TraceId


@asynccontextmanager
async def _unit():
    yield SimpleNamespace()


class _Execution(model.ModelPipeline):
    def __init__(self, finalization: AsyncMock) -> None:
        self._stop = asyncio.Event()
        self._diagnostic = lambda _event: None
        self._factory = cast(
            Any, SimpleNamespace(environment_id=uuid7(), unit_of_work=_unit)
        )
        self._custody = cast(Any, SimpleNamespace(hold=lambda *_a, **_k: _unit()))
        self._catalog = cast(
            Any,
            SimpleNamespace(
                register=AsyncMock(
                    return_value=SimpleNamespace(inserted=False, ref=object())
                )
            ),
        )
        self._repository = cast(
            Any,
            SimpleNamespace(
                prepare_attempt=AsyncMock(return_value=model.ModelAttemptId(uuid7())),
                mark_dispatched=AsyncMock(),
                settle_success=AsyncMock(),
                finalize_primary_success=AsyncMock(),
                settle_failure=AsyncMock(),
                fail_episode=AsyncMock(),
            ),
        )
        self._finalization = cast(Any, SimpleNamespace(finalize=finalization))
        self.result_bytes = (
            b'{"schema_version":"armi.model-response-artifact.v1","candidate":{}}'
        )
        self.adapter = SimpleNamespace(
            binding=object(),
            tokenize=AsyncMock(return_value=1),
            invoke=AsyncMock(
                return_value=ModelInvocationResult(
                    ModelResultStatus.SUCCEEDED,
                    "controlled-request",
                    "controlled-model",
                    self.result_bytes,
                    ModelUsage(1, 1, 0, 0),
                )
            ),
        )
        self.episode = ModelEpisodeSnapshot(
            uuid7(),
            uuid7(),
            None,
            None,
            "consider_autonomous_life",
            0,
            0,
            uuid7(),
            Digest.from_bytes(b"context"),
            cast(Any, object()),
            (),
            (),
            TraceId(uuid7().hex),
        )

    async def _snapshot(self, work):
        return self.episode

    def _adapter_for(self, purpose) -> Any:
        return self.adapter

    async def _read_context(self, snapshot):
        return b"{}"

    async def _publish(self, value, *, logical_kind, snapshot) -> Any:
        return object()


@pytest.mark.asyncio
@pytest.mark.parametrize("reject", [False, True])
async def test_model_success_survives_finalization_failure(monkeypatch, reject) -> None:
    finalization = AsyncMock(
        side_effect=CandidateViolation("CANDIDATE-CONTRACT") if reject else None
    )
    pipeline = _Execution(finalization)
    monkeypatch.setattr(model, "build_request_bytes", lambda **_kwargs: b"{}")
    monkeypatch.setattr(
        model,
        "checked_model_request",
        lambda **_kwargs: SimpleNamespace(canonical_bytes=b"{}"),
    )
    record = SimpleNamespace(
        attempt_count=1, lease=object(), draft=SimpleNamespace(deadline_at=None)
    )

    await pipeline._execute(cast(Any, record))

    pipeline.adapter.invoke.assert_awaited_once()
    pipeline._repository.settle_success.assert_awaited_once()
    pipeline._repository.finalize_primary_success.assert_awaited_once()
    finalization.assert_awaited_once()
    assert finalization.await_args is not None
    assert finalization.await_args.args[0] is record
    assert finalization.await_args.args[2] is pipeline.result_bytes
    pipeline._repository.settle_failure.assert_not_awaited()
    assert pipeline._repository.fail_episode.await_count == int(reject)


class _Renewal(model.ModelPipeline):
    def __init__(self):
        self._stop = asyncio.Event()
        self._diagnostic = lambda _event: None
        self._work = cast(Any, SimpleNamespace(renew=AsyncMock(return_value=object())))
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def _execute(self, record):
        self.entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


@pytest.mark.asyncio
async def test_finalization_remains_renewed_and_stop_cancels_it(monkeypatch) -> None:
    pipeline = _Renewal()
    monkeypatch.setattr(model, "_RENEW_SECONDS", 0.01)
    renewed = asyncio.Event()

    async def renew(lease, **_kwargs):
        renewed.set()
        return lease

    pipeline._work.renew.side_effect = renew
    record = SimpleNamespace(lease=SimpleNamespace(attempt_id=uuid7()))
    task = asyncio.create_task(pipeline._execute_with_renewal(cast(Any, record)))
    await asyncio.wait_for(pipeline.entered.wait(), 1)
    await asyncio.wait_for(renewed.wait(), 1)
    pipeline.stop()
    await asyncio.wait_for(task, 1)
    assert pipeline.cancelled.is_set()
    assert pipeline._work.renew.await_count >= 1
