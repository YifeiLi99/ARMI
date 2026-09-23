"""Scheduling and choosing an action must not generate psychological events."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_kernel.application import WorkType
from armi_runtime.application import cognition_cycle as cycle


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("purpose", "expected"),
    [
        ("consider_autonomy_check", WorkType.COGNITION_CONTEXT_PREPARE),
        ("consider_autonomous_life", WorkType.COGNITION_CONTEXT_PREPARE),
        ("consider_creator_input", WorkType.EVENT_APPRAISE),
        ("consider_codex_result", WorkType.EVENT_APPRAISE),
    ],
)
async def test_selected_opportunity_appraises_only_actual_events(
    monkeypatch, purpose, expected
):
    subject_id, opportunity_id = uuid7(), uuid7()
    now = datetime.now(UTC)
    unit = SimpleNamespace(
        runtime_fence=SimpleNamespace(subject_id=subject_id),
        transaction=SimpleNamespace(
            execute=AsyncMock(
                return_value=SimpleNamespace(fetchone=AsyncMock(return_value=(now,)))
            )
        ),
        work=SimpleNamespace(enqueue=AsyncMock()),
        audit=SimpleNamespace(append=AsyncMock()),
        environment_id=uuid7(),
    )

    @asynccontextmanager
    async def unit_of_work():
        yield unit

    candidate = SimpleNamespace(
        purpose=purpose,
        source_kind="autonomy_plan",
        root_opportunity_id=opportunity_id,
        opportunity_id=opportunity_id,
        subject_id=subject_id,
        scene_id=uuid7() if expected == WorkType.EVENT_APPRAISE else None,
        context_party_id=None,
        evidence_id=None,
        available_after=now,
        selection_priority=1,
    )
    monkeypatch.setattr(
        cycle, "human_input_activity", AsyncMock(return_value=(False, None))
    )
    monkeypatch.setattr(cycle, "voice_activity", AsyncMock(return_value=(False, None)))
    monkeypatch.setattr(cycle, "autonomy_check_current", AsyncMock(return_value=True))
    monkeypatch.setattr(
        cycle.RuntimeCognitionState,
        "current_subject",
        AsyncMock(
            return_value=SimpleNamespace(
                subject_version=1, state_epoch=1, bundle_activation_id=uuid7()
            )
        ),
    )
    ports = SimpleNamespace(
        factory=SimpleNamespace(unit_of_work=unit_of_work),
        opportunities=SimpleNamespace(
            has_pending_human_input=AsyncMock(return_value=False),
            next_candidate=AsyncMock(return_value=candidate),
            can_consider_autonomy=AsyncMock(return_value=True),
            select_for_cognition=AsyncMock(return_value=True),
        ),
        episodes=SimpleNamespace(
            active_opportunities=AsyncMock(return_value=()),
            create_context_episode=AsyncMock(return_value=True),
        ),
        sleep=SimpleNamespace(active_maintenance=AsyncMock(return_value=None)),
        origins=SimpleNamespace(resolve=AsyncMock(return_value=(None, purpose))),
        data_rights=None,
        evidence=None,
        interaction=None,
        codex_context=None,
        codex_sources=None,
        effects=None,
        expression=None,
    )
    selector = cycle.RuntimeCognitionCycleSelector(**vars(ports))
    assert await selector.select_once() is not None
    unit.work.enqueue.assert_awaited_once()
    assert unit.work.enqueue.call_args.args[0].work_kind == expected
