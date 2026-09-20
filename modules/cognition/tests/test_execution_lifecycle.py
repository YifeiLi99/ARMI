"""One execution owns the model result, finalization and cancellation."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_cognition import _model_application as model
from armi_cognition._candidate_application import model_response_candidate
from armi_cognition._model_postgresql import ModelEpisodeSnapshot
from armi_kernel.application import (
    CandidateViolation,
    ModelInvocationResult,
    ModelResultStatus,
    ModelUsage,
    ModelViolation,
    WorkViolation,
)
from armi_kernel.contracts import Digest, TraceId


@asynccontextmanager
async def _unit():
    yield SimpleNamespace()


def test_invalid_saved_response_cannot_reach_subject_commit():
    response = json.dumps(
        {
            "schema_version": "armi.model-response-artifact.v3",
            "output_text": "invalid output",
        }
    ).encode()
    with pytest.raises(CandidateViolation, match="CANDIDATE-CONTRACT"):
        model_response_candidate(response)


class _Execution(model.ModelPipeline):
    def __init__(self, finalization: AsyncMock) -> None:
        self._prices = model.PriceCatalog(())
        self.published: list[tuple[str, bytes]] = []
        self.input_evidence = b'{"schema_version":"armi.model-input-evidence.v1","provider_request":{"instructions":"saved"}}'
        self._failure_notification = AsyncMock()
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
                attach_request=AsyncMock(),
                settle_success=AsyncMock(),
                finalize_primary_success=AsyncMock(),
                settle_failure=AsyncMock(),
                fail_episode=AsyncMock(),
            ),
        )
        self._finalization = cast(Any, SimpleNamespace(finalize=finalization))
        self.result_bytes = json.dumps(
            {
                "schema_version": "armi.model-response-artifact.v3",
                "output_text": '{"candidate":{}}',
            }
        ).encode()
        self.adapter = SimpleNamespace(
            binding=object(),
            tokenize=AsyncMock(return_value=1),
            request_evidence=lambda request: self.input_evidence,
            invoke=AsyncMock(
                return_value=ModelInvocationResult(
                    ModelResultStatus.SUCCEEDED,
                    "controlled-request",
                    "controlled-model",
                    self.result_bytes,
                    ModelUsage(1, 1, 0),
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
            TraceId(uuid7().hex),
        )

    async def _snapshot(self, work):
        return self.episode

    def _adapter_for(self, purpose, context_bytes, refs) -> Any:
        return self.adapter

    async def _read_context(self, snapshot):
        return b"{}"

    async def _publish(self, value, *, logical_kind, snapshot) -> Any:
        self.published.append((logical_kind, value))
        return object()


@pytest.mark.asyncio
@pytest.mark.parametrize("reject", [False, True, "schema", "incomplete"])
async def test_model_success_survives_finalization_failure(monkeypatch, reject) -> None:
    finalization = AsyncMock(
        side_effect=(
            ModelViolation("MODEL-RESPONSE-SCHEMA")
            if reject == "schema"
            else CandidateViolation("CANDIDATE-CONTRACT")
            if reject is True
            else None
        )
    )
    pipeline = _Execution(finalization)
    if reject == "incomplete":
        from dataclasses import replace

        pipeline.adapter.invoke.return_value = replace(
            pipeline.adapter.invoke.return_value,
            response_error_code="MODEL-RESPONSE-INCOMPLETE",
        )
    monkeypatch.setattr(model, "build_request_bytes", lambda **_kwargs: b"{}")
    monkeypatch.setattr(
        model,
        "checked_model_request",
        lambda **_kwargs: SimpleNamespace(canonical_bytes=b"{}"),
    )
    record = SimpleNamespace(
        attempt_count=1,
        lease=object(),
        draft=SimpleNamespace(deadline_at=None, max_attempts=2),
    )

    await pipeline._execute(cast(Any, record))

    pipeline.adapter.invoke.assert_awaited_once()
    assert pipeline.published == [
        ("model.request", pipeline.input_evidence),
        ("model.response", pipeline.result_bytes),
    ]
    pipeline._repository.settle_success.assert_awaited_once()
    pipeline._repository.finalize_primary_success.assert_awaited_once()
    if reject == "incomplete":
        finalization.assert_not_awaited()
        assert (
            pipeline._repository.fail_episode.await_args.kwargs["code"]
            == "MODEL-RESPONSE-INCOMPLETE"
        )
    else:
        finalization.assert_awaited_once()
        assert finalization.await_args is not None
        assert finalization.await_args.args[0] is record
        assert finalization.await_args.args[2] is pipeline.result_bytes
    pipeline._repository.settle_failure.assert_not_awaited()
    assert pipeline._repository.fail_episode.await_count == int(bool(reject))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("errors", "attempt_count", "expected_calls", "succeeds"),
    [
        ([ModelViolation("MODEL-CONNECTION", retryable=True), 1], 1, 2, True),
        ([ModelViolation("MODEL-CONNECTION", retryable=True)] * 2, 1, 2, False),
        ([ModelViolation("MODEL-CONNECTION", retryable=True)], 2, 1, False),
        ([ModelViolation("MODEL-TOKENIZATION")], 1, 1, False),
    ],
)
async def test_tokenization_retry_before_single_model_dispatch(
    monkeypatch, errors, attempt_count, expected_calls, succeeds
) -> None:
    pipeline = _Execution(AsyncMock())
    pipeline.adapter.tokenize.side_effect = errors
    pipeline._repository.end_abandoned_finalization = AsyncMock(return_value=False)
    monkeypatch.setattr(model, "build_request_bytes", lambda **_kwargs: b"{}")
    monkeypatch.setattr(
        model, "checked_model_request", lambda **_kwargs: SimpleNamespace()
    )
    record = SimpleNamespace(
        attempt_count=attempt_count,
        lease=object(),
        draft=SimpleNamespace(deadline_at=None, max_attempts=2),
    )

    await pipeline._execute(cast(Any, record))

    assert pipeline.adapter.tokenize.await_count == expected_calls
    assert pipeline.adapter.invoke.await_count == int(succeeds)
    assert pipeline._repository.mark_dispatched.await_count == int(succeeds)
    assert pipeline._finalization.finalize.await_count == int(succeeds)
    assert pipeline._failure_notification.await_count == int(not succeeds)
    pipeline._repository.prepare_attempt.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_during_tokenization_retry_prevents_model_dispatch(monkeypatch):
    pipeline = _Execution(AsyncMock())
    pipeline.adapter.tokenize.side_effect = ModelViolation(
        "MODEL-CONNECTION", retryable=True
    )
    retrying = asyncio.Event()
    pipeline._diagnostic = lambda _event: retrying.set()
    monkeypatch.setattr(model, "build_request_bytes", lambda **_kwargs: b"{}")
    record = SimpleNamespace(
        attempt_count=1,
        lease=SimpleNamespace(attempt_id=uuid7()),
        draft=SimpleNamespace(deadline_at=None, max_attempts=2),
    )
    task = asyncio.create_task(pipeline._execute_with_renewal(cast(Any, record)))
    await asyncio.wait_for(retrying.wait(), 1)
    pipeline.stop()
    await asyncio.wait_for(task, 1)

    pipeline.adapter.tokenize.assert_awaited_once()
    pipeline.adapter.invoke.assert_not_awaited()
    pipeline._repository.mark_dispatched.assert_not_awaited()
    pipeline._finalization.finalize.assert_not_awaited()
    pipeline._failure_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_model_result_is_not_retried(monkeypatch):
    pipeline = _Execution(AsyncMock())
    pipeline.adapter.invoke.return_value = ModelInvocationResult(
        ModelResultStatus.OUTCOME_UNKNOWN,
        None,
        None,
        None,
        None,
        error_code="MODEL-OUTCOME-UNKNOWN",
    )
    monkeypatch.setattr(model, "build_request_bytes", lambda **_kwargs: b"{}")
    monkeypatch.setattr(
        model, "checked_model_request", lambda **_kwargs: SimpleNamespace()
    )
    record = SimpleNamespace(
        attempt_count=1,
        lease=object(),
        draft=SimpleNamespace(deadline_at=None, max_attempts=2),
    )
    await pipeline._execute(cast(Any, record))

    pipeline.adapter.invoke.assert_awaited_once()
    pipeline._finalization.finalize.assert_not_awaited()
    pipeline._repository.settle_failure.assert_awaited_once()


@pytest.mark.asyncio
async def test_lease_loss_during_tokenization_retry_prevents_dispatch(monkeypatch):
    pipeline = _Execution(AsyncMock())
    pipeline.adapter.tokenize.side_effect = ModelViolation(
        "MODEL-CONNECTION", retryable=True
    )
    pipeline._work = cast(
        Any,
        SimpleNamespace(renew=AsyncMock(side_effect=WorkViolation("WORK-LEASE-LOST"))),
    )
    monkeypatch.setattr(model, "_RENEW_SECONDS", 0.01)
    monkeypatch.setattr(model, "build_request_bytes", lambda **_kwargs: b"{}")
    record = SimpleNamespace(
        attempt_count=1,
        lease=SimpleNamespace(attempt_id=uuid7()),
        draft=SimpleNamespace(deadline_at=None, max_attempts=2),
    )
    await pipeline._execute_with_renewal(cast(Any, record))

    pipeline.adapter.tokenize.assert_awaited_once()
    pipeline.adapter.invoke.assert_not_awaited()
    pipeline._failure_notification.assert_not_awaited()


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
