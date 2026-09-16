from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid7

import pytest
from armi_attention._postgresql import (
    PostgreSQLLifeOpportunityRepository,
)
from armi_attention.api import (
    AutonomyPolicy,
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_attention.bootstrap import (
    bootstrap_opportunity_admission,
    bootstrap_opportunity_transition,
)


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row

    async def fetchall(self) -> list[tuple[object, ...]]:
        return [] if self._row is None else [self._row]


class _AdmissionConnection:
    def __init__(self) -> None:
        self.opportunity_id: UUID | None = None

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
        if "INSERT INTO armi.opportunities" in statement:
            if self.opportunity_id is not None:
                return _Cursor(None)
            self.opportunity_id = cast(UUID, parameters[0])
            return _Cursor((self.opportunity_id,))
        if "SELECT opportunity_id" in statement:
            return _Cursor(
                None if self.opportunity_id is None else (self.opportunity_id,)
            )
        raise AssertionError(statement)


def test_external_evidence_admission_port_is_typed_and_idempotent() -> None:
    owner = bootstrap_opportunity_admission()
    assert isinstance(owner, OpportunityAdmissionPort)
    transaction = _AdmissionConnection()
    draft = ExternalEvidenceOpportunityDraft(
        evidence_id=uuid7(),
        subject_id=uuid7(),
        scene_id=uuid7(),
        context_party_id=uuid7(),
        purpose=OpportunityPurpose.CONSIDER_CREATOR_INPUT,
    )

    first = asyncio.run(owner.admit_external_evidence(cast(Any, transaction), draft))
    replay = asyncio.run(owner.admit_external_evidence(cast(Any, transaction), draft))

    assert first.status is OpportunityAdmissionStatus.ADMITTED
    assert replay.status is OpportunityAdmissionStatus.DUPLICATE
    assert replay.opportunity_id == first.opportunity_id


class _TransitionConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
        self.statements.append(statement)
        return _Cursor((parameters[0],))


@pytest.mark.asyncio
async def test_stale_autonomy_ends_without_a_successor_using_the_old_plan() -> None:
    owner = bootstrap_opportunity_transition()
    operation = uuid7()
    transaction = AsyncMock()
    with (
        patch.object(
            owner,
            "subject_commit_snapshot",
            AsyncMock(
                return_value=SimpleNamespace(
                    reconsideration_no=0, source_kind="autonomy_plan"
                )
            ),
        ),
        patch.object(owner, "resolve_subject_commit", AsyncMock()) as resolve,
    ):
        successor = await owner.supersede_subject_commit(
            transaction, opportunity_id=operation
        )
    assert successor is None
    transaction.execute.assert_not_awaited()
    resolve.assert_awaited_once_with(
        transaction, opportunity_id=operation, disposition="superseded"
    )


def test_reconsideration_sql_is_owned_by_opportunity_port() -> None:
    owner = bootstrap_opportunity_transition()
    connection = _TransitionConnection()
    sleep = asyncio.run(
        owner.reconsider_sleep(
            cast(Any, connection),
            predecessor_opportunity_id=uuid7(),
        )
    )
    assert sleep is not None
    assert all("INSERT INTO armi.opportunities" in sql for sql in connection.statements)


@pytest.mark.asyncio
@pytest.mark.parametrize("awaiting_creator", [False, True])
@pytest.mark.parametrize(
    "outlet_health", [("ready", None), ("unavailable", "QQ-OFFLINE")]
)
async def test_autonomy_uses_idle_single_slot_regardless_of_unanswered_contact(
    awaiting_creator: bool,
    outlet_health: tuple[str, str | None],
) -> None:
    facts = AsyncMock()
    facts.active_cognition_count.return_value = 0
    scene, creator, subject = uuid7(), uuid7(), uuid7()
    facts.outreach.return_value = SimpleNamespace(
        scene_id=scene,
        creator_party_id=creator,
        awaiting_creator=awaiting_creator,
    )
    sleep = AsyncMock()
    sleep.active_maintenance.return_value = None
    activities = AsyncMock()
    activities.scheduling_heads.return_value = ()
    state = AsyncMock()
    state.life_mode.return_value = SimpleNamespace(active_activity_ids=())
    repository = PostgreSQLLifeOpportunityRepository(
        sleep,
        activities,
        state,
        facts,
    )
    unit = SimpleNamespace(
        transaction=AsyncMock(), runtime_fence=SimpleNamespace(subject_id=subject)
    )
    with patch("armi_attention._postgresql.PostgreSQLAutonomyOwner") as constructor:
        owner = AsyncMock()
        constructor.return_value = owner
        owner.admit_due.return_value = OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, uuid7()
        )
        result = await repository.admit_autonomy(
            cast(Any, unit),
            policy=AutonomyPolicy(),
            model_concurrency=1,
            outlet_health=outlet_health,
        )
        assert result.status is OpportunityAdmissionStatus.ADMITTED
        owner.admit_due.assert_awaited_once_with(
            unit.transaction,
            subject_id=subject,
            policy=AutonomyPolicy(),
            scene_id=scene,
            creator_party_id=creator,
            activity_id=None,
        )
        owner.consider_psychological_attention.assert_awaited_once_with(
            unit.transaction, subject_id=subject, policy=AutonomyPolicy(), facts=facts
        )
    facts.outreach.assert_awaited_once_with(unit, outlet="qq")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sleeping,busy,reason",
    [
        (True, 0, "LIFE-BACKPRESSURE-MAINTENANCE"),
        (False, 1, "LIFE-BACKPRESSURE-COGNITION-CAPACITY"),
    ],
)
async def test_runtime_blockers_do_not_become_subjective_silence(
    sleeping: bool, busy: int, reason: str
) -> None:
    facts = AsyncMock()
    facts.active_cognition_count.return_value = busy
    sleep = AsyncMock()
    sleep.active_maintenance.return_value = object() if sleeping else None
    repository = PostgreSQLLifeOpportunityRepository(
        sleep,
        AsyncMock(),
        AsyncMock(),
        facts,
    )
    unit = SimpleNamespace(
        transaction=AsyncMock(), runtime_fence=SimpleNamespace(subject_id=uuid7())
    )
    with patch("armi_attention._postgresql.PostgreSQLAutonomyOwner") as constructor:
        owner = AsyncMock()
        constructor.return_value = owner
        result = await repository.admit_autonomy(
            cast(Any, unit),
            policy=AutonomyPolicy(),
            model_concurrency=1,
            outlet_health=("ready", None),
        )
        assert result.reason_code == reason
        assert result.status is OpportunityAdmissionStatus.REJECTED
        owner.admit_due.assert_not_awaited()
        facts.outreach.assert_awaited_once()
