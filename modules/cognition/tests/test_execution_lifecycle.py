"""One execution owns the model result, finalization and cancellation."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import ANY, AsyncMock
from uuid import uuid7

import pytest
from armi_cognition import _model_application as model
from armi_cognition._candidate_application import model_response_candidate
from armi_cognition._model_postgresql import ModelEpisodeSnapshot
from armi_kernel.application import (
    AutonomyCategory,
    CandidateViolation,
    ModelInvocationResult,
    ModelResultStatus,
    ModelUsage,
    ModelViolation,
    WorkViolation,
    provider_call,
)
from armi_kernel.contracts import Digest, TraceId


@asynccontextmanager
async def _unit():
    yield SimpleNamespace()


def test_invalid_saved_response_cannot_reach_subject_commit():
    response = json.dumps(
        {
            "schema_kind": "armi.model-response-artifact",
            "output_text": "invalid output",
        }
    ).encode()
    with pytest.raises(CandidateViolation, match="CANDIDATE-CONTRACT"):
        model_response_candidate(response)


class _Execution(model.ModelPipeline):
    def __init__(self, finalization: AsyncMock) -> None:
        self._prices = model.PriceCatalog(())
        self.published: list[tuple[str, bytes]] = []
        self.input_evidence = b'{"schema_kind":"armi.model-input-evidence","provider_request":{"instructions":"saved"}}'
        self._failure_notification = AsyncMock()
        self._stop = asyncio.Event()
        self._wakeups = model._LocalWakeups()
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
                "schema_kind": "armi.model-response-artifact",
                "output_text": '{"candidate":{}}',
            }
        ).encode()
        self.adapter = SimpleNamespace(
            binding=SimpleNamespace(provider="volcengine_ark"),
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


def _format_retry_execution(monkeypatch, *, provider="deepseek", other=False):
    from dataclasses import replace

    pipeline = _Execution(AsyncMock())
    pipeline.adapter.binding = SimpleNamespace(
        provider=provider,
        response_contract_kind=(
            "armi.other-human-dialogue-candidate"
            if other
            else "armi.creator-cognitive-act-candidate"
        ),
    )
    pipeline.episode = replace(
        pipeline.episode,
        purpose="consider_other_human_input" if other else "consider_creator_input",
    )
    pipeline._repository.prepare_attempt.side_effect = lambda *_a, **_k: (
        model.ModelAttemptId(uuid7())
    )
    frozen_request = SimpleNamespace(canonical_bytes=b"frozen")
    monkeypatch.setattr(model, "build_request_bytes", lambda **_kwargs: b"frozen")
    monkeypatch.setattr(
        model, "checked_model_request", lambda **_kwargs: frozen_request
    )
    record = SimpleNamespace(
        attempt_count=1,
        lease=object(),
        draft=SimpleNamespace(deadline_at=None, max_attempts=2),
    )

    def response(text):
        return replace(
            pipeline.adapter.invoke.return_value,
            response_bytes=json.dumps(
                {
                    "schema_kind": "armi.model-response-artifact",
                    "output_text": text,
                }
            ).encode(),
        )

    return pipeline, record, frozen_request, response


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", [*AutonomyCategory, "unknown", "invalid"])
async def test_jev_check_resolves_attention_without_main_model_or_format_retry(
    monkeypatch, choice
):
    from dataclasses import replace

    engage = choice not in {"wait", "unknown", "invalid"}
    pipeline, record, _frozen, _response = _format_retry_execution(monkeypatch)
    pipeline.episode = replace(pipeline.episode, purpose="consider_autonomy_check")
    pipeline._read_context = AsyncMock(
        return_value=json.dumps(
            {
                "layers": [
                    {
                        "items": [
                            {
                                "item_kind": "current_motivation",
                                "content": json.dumps(
                                    {"consideration": {"eligible": engage}}
                                ),
                            }
                        ]
                    }
                ]
            }
        ).encode()
    )
    pipeline._repository.finalize_autonomy_check = AsyncMock()
    raw = json.dumps(
        {
            "answers": {
                "category": {
                    "type": "choice",
                    "choice": choice,
                    "confidence": 1,
                    "probabilities": {
                        "continue_activity": 0,
                        "explore": 0,
                        "communicate": 0,
                        "reflect": 0,
                        "wait": 1,
                        "unknown": 0,
                    },
                }
            }
        }
    ).encode()
    check = SimpleNamespace(
        binding=SimpleNamespace(provider="typesafe"),
        request_evidence=lambda context: context,
        invoke=AsyncMock(
            return_value=replace(
                pipeline.adapter.invoke.return_value, response_bytes=raw
            )
        ),
    )
    pipeline._autonomy_check = cast(Any, check)
    await pipeline._execute(cast(Any, record))
    pipeline.adapter.invoke.assert_not_awaited()
    pipeline.adapter.tokenize.assert_not_awaited()
    check.invoke.assert_awaited_once()
    pipeline._repository.settle_success.assert_awaited_once()
    assert ("model.response", raw) in pipeline.published
    pipeline._finalization.finalize.assert_not_awaited()
    if choice in {"unknown", "invalid"}:
        pipeline._repository.finalize_autonomy_check.assert_not_awaited()
        pipeline._repository.fail_episode.assert_awaited_once()
        assert pipeline._repository.fail_episode.call_args.kwargs["code"] == (
            "MODEL-JEV-CHECK-UNDETERMINED"
            if choice == "unknown"
            else "MODEL-JEV-CHECK-CONTRACT"
        )
        return
    pipeline._repository.finalize_autonomy_check.assert_awaited_once_with(
        ANY,
        lease=record.lease,
        snapshot=pipeline.episode,
        category=AutonomyCategory(choice),
    )
    pipeline._failure_notification.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", "qwen"])
@pytest.mark.parametrize("other", [False, True])
@pytest.mark.parametrize("failures", [0, 1, 4, 5])
async def test_format_retry_preserves_request_and_finalizes_once(
    monkeypatch, provider, other, failures
):
    pipeline, record, request, response = _format_retry_execution(
        monkeypatch, provider=provider, other=other
    )
    invalid = response('{"action":"reply","content":["bad"],"event_null":false}')
    valid = response('{"action":"reply","content":["hello"]}')
    events: list[str] = []
    pipeline._diagnostic = lambda _event: events.append(_event)
    pipeline.adapter.invoke.side_effect = [invalid] * failures + [valid]
    if failures == 5:
        pipeline._finalization.finalize.side_effect = CandidateViolation(
            "CANDIDATE-CONTRACT"
        )
    await pipeline._execute(cast(Any, record))
    calls = min(failures + 1, 5)
    assert events.count("cognition.model.response.format_rejected") == min(failures, 5)
    assert pipeline.adapter.invoke.await_count == calls
    assert all(
        item.args[0] is request for item in pipeline.adapter.invoke.await_args_list
    )
    assert pipeline._repository.prepare_attempt.await_count == calls
    settlements = pipeline._repository.settle_success.await_args_list
    assert len({item.kwargs["attempt_id"] for item in settlements}) == calls
    assert [item.kwargs["result"].response_error_code for item in settlements] == (
        ["MODEL-RESPONSE-SCHEMA"] * min(failures, 5) + ([None] if failures < 5 else [])
    )
    assert [kind for kind, _ in pipeline.published] == ["model.request"] + [
        "model.response"
    ] * calls
    pipeline._repository.finalize_primary_success.assert_awaited_once()
    pipeline._finalization.finalize.assert_awaited_once()
    assert pipeline._finalization.finalize.await_args.args[2] == (
        invalid.response_bytes if failures == 5 else valid.response_bytes
    )
    pipeline._repository.settle_failure.assert_not_awaited()
    assert pipeline._failure_notification.await_count == int(failures == 5)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ['{"action":', '{"action":"reply"}'])
async def test_format_retry_covers_invalid_json_and_missing_required(monkeypatch, bad):
    pipeline, record, _, response = _format_retry_execution(monkeypatch)
    pipeline.adapter.invoke.side_effect = [
        response(bad),
        response('{"action":"no_action"}'),
    ]
    await pipeline._execute(cast(Any, record))
    assert pipeline.adapter.invoke.await_count == 2
    pipeline._finalization.finalize.assert_awaited_once()


@pytest.mark.asyncio
async def test_format_retry_does_not_retry_owner_failure(monkeypatch):
    pipeline, record, _, response = _format_retry_execution(monkeypatch)
    pipeline.adapter.invoke.return_value = response('{"action":"no_action"}')
    pipeline._finalization.finalize.side_effect = CandidateViolation("CANDIDATE-STALE")
    await pipeline._execute(cast(Any, record))
    pipeline.adapter.invoke.assert_awaited_once()
    pipeline._repository.fail_episode.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code", ["MODEL-RESPONSE-INCOMPLETE", "MODEL-RESPONSE-FORBIDDEN"]
)
async def test_text_protocol_failure_is_not_a_format_retry(monkeypatch, code):
    from dataclasses import replace

    pipeline, record, _, response = _format_retry_execution(monkeypatch)
    pipeline.adapter.invoke.return_value = replace(
        response("invalid"), response_error_code=code
    )
    await pipeline._execute(cast(Any, record))
    pipeline.adapter.invoke.assert_awaited_once()
    pipeline._repository.fail_episode.assert_awaited_once()
    pipeline._finalization.finalize.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_transport_failure_after_invalid_response_ends_retries(
    monkeypatch, unknown
):
    pipeline, record, _, response = _format_retry_execution(monkeypatch)
    failure = ModelInvocationResult(
        ModelResultStatus.OUTCOME_UNKNOWN
        if unknown
        else ModelResultStatus.PROVIDER_FAILED,
        None,
        None,
        None,
        None,
        error_code="MODEL-OUTCOME-UNKNOWN" if unknown else "MODEL-CONNECTION",
    )
    pipeline.adapter.invoke.side_effect = [response("invalid"), failure]
    await pipeline._execute(cast(Any, record))
    assert pipeline.adapter.invoke.await_count == 2
    pipeline._repository.settle_failure.assert_awaited_once()
    pipeline._finalization.finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_after_invalid_response_prevents_next_generation(monkeypatch):
    pipeline, record, _, response = _format_retry_execution(monkeypatch)
    pipeline.adapter.invoke.return_value = response("invalid")
    pipeline._repository.settle_success.side_effect = lambda *_a, **_k: pipeline.stop()
    await pipeline._execute(cast(Any, record))
    pipeline.adapter.invoke.assert_awaited_once()
    pipeline._repository.prepare_attempt.assert_awaited_once()
    pipeline._finalization.finalize.assert_not_awaited()


@pytest.mark.asyncio
async def test_regeneration_usage_is_bound_to_each_attempt(monkeypatch):
    pipeline, record, _, response = _format_retry_execution(monkeypatch)
    pipeline._factory.provider_usage_unit_of_work = lambda **_kwargs: _unit()
    pipeline._repository.record_provider_call = AsyncMock()
    results = iter([response("invalid"), response('{"action":"no_action"}')])

    async def invoke(_request):
        async with provider_call(
            provider="deepseek", model="deepseek-flash", service="generation"
        ) as call:
            await call.capture(usage={"input_tokens": 20, "output_tokens": 10})
        return next(results)

    pipeline.adapter.invoke.side_effect = invoke
    await pipeline._execute(cast(Any, record))
    attempts = [
        item.kwargs["attempt_id"]
        for item in pipeline._repository.settle_success.await_args_list
    ]
    receipts = pipeline._repository.record_provider_call.await_args_list
    registrations = [item for item in receipts if item.kwargs["receipt"].registration]
    assert [item.kwargs["attempt_id"] for item in registrations] == attempts
    assert len({item.kwargs["receipt"].call_id for item in registrations}) == 2
    assert all(
        any(
            item.kwargs["attempt_id"] == attempt
            and item.kwargs["receipt"].raw_usage is not None
            for item in receipts
        )
        for attempt in attempts
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("stop", [False, True])
async def test_cancellation_during_second_generation_never_finalizes(monkeypatch, stop):
    pipeline, record, _, response = _format_retry_execution(monkeypatch)
    record.lease = SimpleNamespace(attempt_id=uuid7())
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def invoke(_request):
        if pipeline.adapter.invoke.await_count == 1:
            return response("invalid")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def renew(lease, **_kwargs):
        if entered.is_set() and not stop:
            raise WorkViolation("WORK-LEASE-LOST")
        return lease

    pipeline._work = cast(Any, SimpleNamespace(renew=AsyncMock(side_effect=renew)))
    monkeypatch.setattr(model, "_RENEW_SECONDS", 0.01)
    pipeline.adapter.invoke.side_effect = invoke
    task = asyncio.create_task(pipeline._execute_with_renewal(cast(Any, record)))
    await asyncio.wait_for(entered.wait(), 1)
    if stop:
        pipeline.stop()
    await asyncio.wait_for(task, 1)
    assert cancelled.is_set()
    assert pipeline.adapter.invoke.await_count == 2
    pipeline._repository.settle_success.assert_awaited_once()
    pipeline._finalization.finalize.assert_not_awaited()
    pipeline._failure_notification.assert_not_awaited()


class _Renewal(model.ModelPipeline):
    def __init__(self):
        self._stop = asyncio.Event()
        self._wakeups = model._LocalWakeups()
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
