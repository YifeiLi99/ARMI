"""Creator hot branches keep expression and subjective appraisal separate."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import pytest
from armi_cognition import _model_application
from armi_cognition._creator_branch_contract import (
    CreatorDialogueAggregate,
    parse_creator_appraisal,
    parse_creator_response,
)
from armi_cognition._model_application import ModelPipeline, _hot_aggregate_outcome
from armi_kernel.application import (
    ModelInvocationResult,
    ModelResultStatus,
    ModelUsage,
)
from pydantic import ValidationError


def _success(label: str) -> ModelInvocationResult:
    return ModelInvocationResult(
        ModelResultStatus.SUCCEEDED,
        label,
        "model",
        b"{}",
        ModelUsage(1, 1, 0, 0),
        None,
    )


def test_response_branch_rejects_subject_state() -> None:
    with pytest.raises(ValidationError):
        parse_creator_response(
            {
                "kind": "reply",
                "content": "知道了。",
                "experience": {"first_person_gist": "我听见了"},
            }
        )


def test_appraisal_memory_requires_explicit_remember_shape() -> None:
    with pytest.raises(ValidationError):
        parse_creator_appraisal(
            {
                "experience": {
                    "first_person_gist": "Creator 告诉了我一件事。",
                    "remember": False,
                    "memory_summary": "永久记住",
                }
            },
            allowed_context_refs=frozenset(),
        )


def test_aggregate_shape_is_determined_by_available_branches() -> None:
    response = parse_creator_response({"kind": "reply", "content": "我知道了。"})
    aggregate = CreatorDialogueAggregate(
        schema_version="armi.creator-dialogue-aggregate.v1",
        outcome="response_only",
        response=response,
    )
    assert aggregate.appraisal is None
    with pytest.raises(ValidationError):
        CreatorDialogueAggregate(
            schema_version="armi.creator-dialogue-aggregate.v1",
            outcome="complete",
            response=response,
        )


@pytest.mark.parametrize(
    ("response_succeeded", "appraisal_succeeded", "expected"),
    (
        (True, True, "complete"),
        (True, False, "response_only"),
        (False, True, "internal_only"),
        (False, False, None),
    ),
)
def test_hot_branch_failure_matrix_is_fixed(
    response_succeeded: bool,
    appraisal_succeeded: bool,
    expected: str | None,
) -> None:
    assert _hot_aggregate_outcome(response_succeeded, appraisal_succeeded) == expected


def test_hot_model_calls_overlap() -> None:
    async def run() -> tuple[ModelInvocationResult, ModelInvocationResult]:
        entered = 0
        both_entered = asyncio.Event()

        async def invoke(label: str) -> ModelInvocationResult:
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=0.2)
            return _success(label)

        pipeline = object.__new__(ModelPipeline)
        pipeline._work = cast(Any, SimpleNamespace())
        first = asyncio.create_task(invoke("response"))
        second = asyncio.create_task(invoke("appraisal"))
        response, appraisal, _ = await pipeline._await_hot_branches(
            first, second, cast(Any, SimpleNamespace())
        )
        return response, appraisal

    response, appraisal = asyncio.run(run())
    assert response.provider_request_id == "response"
    assert appraisal.provider_request_id == "appraisal"


def test_appraisal_is_cancelled_after_response_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_model_application, "_APPRAISAL_GRACE_SECONDS", 0.01)

    async def run() -> ModelInvocationResult:
        async def response() -> ModelInvocationResult:
            return _success("response")

        async def appraisal() -> ModelInvocationResult:
            await asyncio.sleep(1)
            return _success("late")

        pipeline = object.__new__(ModelPipeline)
        pipeline._work = cast(Any, SimpleNamespace())
        _, result, _ = await pipeline._await_hot_branches(
            asyncio.create_task(response()),
            asyncio.create_task(appraisal()),
            cast(Any, SimpleNamespace()),
        )
        return result

    result = asyncio.run(run())
    assert result.status is ModelResultStatus.TIMED_OUT
    assert result.error_code == "MODEL-APPRAISAL-TIMEOUT"


def test_uncertain_appraisal_cancellation_does_not_block_or_enter_aggregate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_model_application, "_APPRAISAL_GRACE_SECONDS", 0.01)

    async def run() -> tuple[ModelInvocationResult, ModelInvocationResult]:
        release_late = asyncio.Event()
        late_tasks: list[asyncio.Task[ModelInvocationResult]] = []

        async def response() -> ModelInvocationResult:
            return _success("response")

        async def appraisal() -> ModelInvocationResult:
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                await release_late.wait()
                return _success("late-appraisal")
            raise AssertionError("appraisal should have been cancelled")

        pipeline = object.__new__(ModelPipeline)
        pipeline._work = cast(Any, SimpleNamespace())
        _, timed_out, _ = await pipeline._await_hot_branches(
            asyncio.create_task(response()),
            asyncio.create_task(appraisal()),
            cast(Any, SimpleNamespace()),
            late_appraisal=late_tasks.append,
        )
        assert len(late_tasks) == 1
        release_late.set()
        late = await late_tasks[0]
        return timed_out, late

    uncertain, late = asyncio.run(run())
    assert uncertain.status is ModelResultStatus.OUTCOME_UNKNOWN
    assert uncertain.error_code == "MODEL-OUTCOME-UNKNOWN"
    assert late.provider_request_id == "late-appraisal"
