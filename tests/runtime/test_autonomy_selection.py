"""Admission waits before Cognition starts, including delegated result rounds."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid7

import pytest
from armi_runtime.application.cognition_cycle import (
    RuntimeCognitionCycleSelector,
    RuntimeCognitionState,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "quota_available", "already_thinking", "selected"),
    [
        ("consider_autonomous_life", False, False, False),
        ("consider_autonomous_life", True, True, False),
        ("consider_autonomous_life", True, False, True),
        ("consider_visual_observation", False, False, False),
        ("reflect_self", False, False, False),
        ("consider_sleep", True, False, True),
        ("consider_visual_observation", True, True, False),
        ("consider_creator_input", False, True, True),
    ],
)
async def test_result_opportunity_waits_for_quota_and_single_autonomous_round(
    origin, quota_available, already_thinking, selected
):
    subject, generation, root, current = (uuid7() for _ in range(4))
    unit = SimpleNamespace(
        transaction=AsyncMock(),
        runtime_fence=SimpleNamespace(
            subject_id=subject, life_generation_id=generation
        ),
        work=AsyncMock(),
        audit=AsyncMock(),
        environment_id=uuid7(),
    )
    unit.transaction.execute.return_value.fetchone.return_value = (datetime.now(UTC),)

    @asynccontextmanager
    async def transaction():
        yield unit

    opportunities, episodes, sleep, rights, origins = (AsyncMock() for _ in range(5))
    opportunities.next_candidate.side_effect = [
        SimpleNamespace(
            opportunity_id=current,
            root_opportunity_id=root,
            evidence_id=None,
            subject_id=subject,
            scene_id=uuid7(),
            context_party_id=uuid7(),
            purpose="consider_codex_result",
            available_after=datetime.now(UTC),
            selection_priority=1,
        ),
        None,
    ]
    opportunities.can_consider_autonomy.return_value = quota_available
    opportunities.select_for_cognition.return_value = True
    episodes.active_opportunities.return_value = (uuid7(),) if already_thinking else ()
    episodes.create_context_episode.return_value = True
    sleep.active_maintenance.return_value = None
    rights.blocks_cognition.return_value = False
    origins.resolve.return_value = (root, origin)
    selector = RuntimeCognitionCycleSelector(
        factory=cast(Any, SimpleNamespace(unit_of_work=transaction)),
        opportunities=opportunities,
        episodes=episodes,
        sleep=sleep,
        data_rights=rights,
        origins=origins,
        evidence=AsyncMock(),
        interaction=AsyncMock(),
        web=AsyncMock(),
        codex_context=AsyncMock(),
        codex_sources=AsyncMock(),
        effects=AsyncMock(),
        expression=AsyncMock(),
    )
    with patch.object(
        RuntimeCognitionState,
        "current_subject",
        AsyncMock(
            return_value=SimpleNamespace(
                subject_version=0,
                state_epoch=0,
                bundle_activation_id=uuid7(),
            )
        ),
    ):
        result = await selector.select_once()
    assert (result is not None) == selected
    assert episodes.create_context_episode.await_count == int(selected)
    assert unit.work.enqueue.await_count == int(selected)
    if origin == "consider_creator_input":
        opportunities.can_consider_autonomy.assert_not_awaited()
    elif not selected:
        opportunities.select_for_cognition.assert_not_awaited()
