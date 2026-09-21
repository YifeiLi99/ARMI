"""Admission waits before Cognition starts, including delegated result rounds."""

import asyncio
import os
import selectors
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import uuid7

import psycopg
import pytest
from armi_runtime.application.cognition_cycle import (
    RuntimeCognitionCycleSelector,
    RuntimeCognitionState,
)


@pytest.fixture(autouse=True)
def no_pending_raw_input(monkeypatch):
    monkeypatch.setattr(
        "armi_runtime.application.cognition_cycle.voice_activity",
        AsyncMock(return_value=(False, None)),
    )
    monkeypatch.setattr(
        "armi_runtime.application.cognition_cycle.human_input_activity",
        AsyncMock(return_value=(False, None)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("origin", "autonomy_enabled", "already_thinking", "selected"),
    [
        ("consider_autonomous_life", False, False, False),
        ("consider_autonomous_life", True, True, False),
        ("consider_autonomous_life", True, False, True),
        ("consider_visual_observation", False, False, False),
        ("reflect_self", False, False, False),
        ("consider_sleep", True, False, True),
        ("consider_visual_observation", True, True, False),
        ("consider_creator_input", False, True, False),
        ("consider_creator_input", False, False, True),
        ("consider_other_human_input", False, True, False),
        ("consider_other_human_input", False, False, True),
    ],
)
async def test_result_opportunity_waits_for_enablement_and_single_subject_round(
    origin, autonomy_enabled, already_thinking, selected
):
    subject, root, current = (uuid7() for _ in range(3))
    unit = SimpleNamespace(
        transaction=AsyncMock(),
        runtime_fence=SimpleNamespace(subject_id=subject),
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
    opportunities.has_pending_human_input.return_value = False
    opportunities.can_consider_autonomy.return_value = autonomy_enabled
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
    if already_thinking:
        opportunities.next_candidate.assert_not_awaited()
        # Once the previous round ends, freeze a fresh version for the waiting
        # message instead of reusing the old Context or replaying model output.
        episodes.active_opportunities.return_value = ()
        with patch.object(
            RuntimeCognitionState,
            "current_subject",
            AsyncMock(
                return_value=SimpleNamespace(
                    subject_version=39, state_epoch=0, bundle_activation_id=uuid7()
                )
            ),
        ):
            result = await selector.select_once()
        if autonomy_enabled or origin in {
            "consider_creator_input",
            "consider_other_human_input",
        }:
            assert result is not None
            assert (
                episodes.create_context_episode.call_args.args[1].base_subject_version
                == 39
            )
    if origin in {"consider_creator_input", "consider_other_human_input"}:
        opportunities.can_consider_autonomy.assert_not_awaited()
    elif not selected and not already_thinking:
        opportunities.select_for_cognition.assert_not_awaited()


@pytest.mark.postgresql
@pytest.mark.test_group("cognition", "context")
def test_simultaneous_selectors_admit_only_one_round(monkeypatch):
    asyncio.run(
        _simultaneous_selectors(monkeypatch),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
    )


async def _simultaneous_selectors(monkeypatch):
    """Real PostgreSQL transactions arbitrate two simultaneous runtime selectors."""
    dsn = os.environ.get("S009_ADMIN_DSN")
    if not dsn:
        pytest.skip("isolated PostgreSQL is not running")
    subject, opportunity = (uuid7() for _ in range(2))
    committed = []
    lock_requests = 0
    competing = asyncio.Event()

    @asynccontextmanager
    async def transaction():
        nonlocal lock_requests
        connection = await psycopg.AsyncConnection.connect(dsn)
        pending = []

        async def execute(statement, parameters=()):
            nonlocal lock_requests
            lock_requests += 1
            if lock_requests == 2:
                competing.set()
            return await connection.execute(statement, parameters)

        unit = SimpleNamespace(
            transaction=SimpleNamespace(execute=execute, pending=pending),
            runtime_fence=SimpleNamespace(subject_id=subject),
            work=AsyncMock(),
            audit=AsyncMock(),
            environment_id=uuid7(),
        )
        try:
            async with connection.transaction():
                yield unit
                committed.extend(pending)
        finally:
            await connection.close()

    async def active(_transaction, **_kwargs):
        # Ensure the competing selector has reached admission before continuing.
        await asyncio.wait_for(competing.wait(), timeout=5)
        return tuple(committed)

    async def create(tx, draft):
        tx.pending.append(draft)
        return True

    opportunities, episodes, sleep, origins = (AsyncMock() for _ in range(4))
    opportunities.next_candidate.return_value = SimpleNamespace(
        opportunity_id=opportunity,
        root_opportunity_id=opportunity,
        evidence_id=None,
        subject_id=subject,
        scene_id=None,
        context_party_id=None,
        purpose="consider_sleep",
        available_after=datetime.now(UTC),
        selection_priority=1,
    )
    opportunities.select_for_cognition.return_value = True
    opportunities.can_consider_autonomy.return_value = True
    episodes.active_opportunities.side_effect = active
    episodes.create_context_episode.side_effect = create
    sleep.active_maintenance.return_value = None
    origins.resolve.return_value = (opportunity, "consider_sleep")
    monkeypatch.setattr(
        RuntimeCognitionState,
        "current_subject",
        AsyncMock(
            return_value=SimpleNamespace(
                subject_version=38, state_epoch=0, bundle_activation_id=uuid7()
            )
        ),
    )
    selector = RuntimeCognitionCycleSelector(
        factory=cast(Any, SimpleNamespace(unit_of_work=transaction)),
        opportunities=opportunities,
        episodes=episodes,
        sleep=sleep,
        origins=origins,
        data_rights=AsyncMock(),
        evidence=AsyncMock(),
        interaction=AsyncMock(),
        codex_context=AsyncMock(),
        codex_sources=AsyncMock(),
        effects=AsyncMock(),
        expression=AsyncMock(),
    )
    results = await asyncio.wait_for(
        asyncio.gather(selector.select_once(), selector.select_once()), timeout=10
    )
    assert sum(result is not None for result in results) == 1
    assert len(committed) == 1
    opportunities.select_for_cognition.assert_awaited_once()
