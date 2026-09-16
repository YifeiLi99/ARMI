"""Quota admission precedes dispatch and never prevents receipt settlement."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_attention.api import AutonomyPolicy, LifeViolation
from armi_kernel.application import (
    PriceCatalog,
    ProviderMeterScope,
    provider_call,
    provider_meter_scope,
)
from armi_runtime.application.autonomy_usage import (
    AutonomyAdmissionFailure,
    AutonomyRequestAdmission,
)


def admission(rows):
    transaction = AsyncMock()
    transaction.execute.return_value.fetchall.return_value = rows
    owner = AsyncMock()
    unit = SimpleNamespace(
        transaction=transaction, runtime_fence=SimpleNamespace(subject_id=uuid7())
    )
    origins = AsyncMock()
    origins.resolve.side_effect = lambda _transaction, operation: next(
        (row[0], row[2]) for row in rows if row[0] == operation
    )
    gate = AutonomyRequestAdmission(owner, AutonomyPolicy(), origins)

    async def save(receipt):
        await gate.admit(cast(Any, unit), receipt)

    return owner, transaction, save


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["generation", "web_search", "asr", "tts"])
async def test_exhausted_quota_prevents_every_paid_service_dispatch(service):
    owner, _, save = admission([(uuid7(), "cognition", "consider_autonomous_life")])
    owner.register_request.side_effect = LifeViolation("LIFE-AUTONOMY-QUOTA-EXHAUSTED")
    dispatch = AsyncMock()
    with (
        provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "autonomous")),
        pytest.raises(AutonomyAdmissionFailure, match="LIFE-AUTONOMY-QUOTA-EXHAUSTED"),
    ):
        async with provider_call(provider="test", model="test", service=service):
            await dispatch()
    dispatch.assert_not_awaited()
    owner.register_request.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("service", ["tokenization", "poll"])
async def test_auxiliary_requests_do_not_consume_another_quota_slot(service):
    owner, transaction, save = admission([])
    with provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "autonomous")):
        async with provider_call(provider="test", model="test", service=service):
            pass
    owner.register_request.assert_not_awaited()
    transaction.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["returned", "unknown", "failed"])
async def test_receipt_settlement_ignores_exhausted_or_disabled_quota(outcome):
    root = uuid7()
    # Voice and cognition may both project one physical model request.
    owner, _, save = admission(
        [
            (root, "cognition", "consider_autonomous_life"),
            (root, "voice_turn", "consider_autonomous_life"),
        ]
    )
    with provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "autonomous")):
        async with provider_call(
            provider="test", model="test", service="generation"
        ) as call:
            owner.register_request.side_effect = LifeViolation(
                "LIFE-AUTONOMY-QUOTA-EXHAUSTED"
            )
            await call.finish(outcome)
    owner.register_request.assert_awaited_once()
    assert owner.register_request.await_args.kwargs["root_opportunity_id"] == root


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "purpose",
    [
        "consider_creator_input",
        "consider_creator_voice_input",
        "consider_other_human_input",
        "consider_codex_task",
    ],
)
async def test_human_origin_and_derived_calls_do_not_consume_autonomous_quota(purpose):
    owner, _, save = admission([(uuid7(), "cognition", purpose)])
    with provider_meter_scope(
        ProviderMeterScope(save, PriceCatalog(()), "tool_result")
    ):
        async with provider_call(provider="test", model="test", service="generation"):
            pass
    owner.register_request.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [],
        [
            (uuid7(), "cognition", "consider_autonomous_life"),
            (uuid7(), "cognition", "consider_creator_input"),
        ],
    ],
)
async def test_missing_or_conflicting_authoritative_origin_blocks_dispatch(rows):
    owner, _, save = admission(rows)
    dispatch = AsyncMock()
    with (
        provider_meter_scope(ProviderMeterScope(save, PriceCatalog(()), "autonomous")),
        pytest.raises(AutonomyAdmissionFailure, match="LIFE-AUTONOMY-CALL-ORIGIN"),
    ):
        async with provider_call(provider="test", model="test", service="generation"):
            await dispatch()
    dispatch.assert_not_awaited()
    owner.register_request.assert_not_awaited()
