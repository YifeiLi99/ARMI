from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import pytest
from armi_activity.bootstrap import bootstrap_activity
from armi_kernel.application import RuntimeFence, RuntimeInstanceId
from armi_material.bootstrap import bootstrap_material
from armi_opportunity._postgresql import (
    PostgreSQLLifeOpportunityRepository,
)
from armi_opportunity.api import (
    CreatorOutreachPolicy,
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_opportunity.bootstrap import (
    bootstrap_opportunity_admission,
    bootstrap_opportunity_transition,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWork
from armi_subject_state.api import LifeModeHead


class _Relationships:
    def __init__(self, *, boundary: bool = False) -> None:
        self._boundary = boundary

    async def current_for_party(
        self, *_args: object, **_kwargs: object
    ) -> object | None:
        return object() if self._boundary else None


class _RelationshipPolicy:
    def allows_snapshot_outreach(self, _relationship: object) -> bool:
        return False


class _SleepRead:
    async def active_maintenance(self, *_args: object, **_kwargs: object) -> None:
        return None


class _SubjectState:
    async def active_activity_ids(
        self, transaction: object, *, subject_id: UUID
    ) -> tuple[UUID, ...]:
        return (
            await self.life_mode(transaction, subject_id=subject_id)
        ).active_activity_ids

    async def life_mode(self, transaction: object, *, subject_id: UUID) -> LifeModeHead:
        del subject_id
        active_activity = getattr(transaction, "_activity_id", None)
        return LifeModeHead(
            uuid7(),
            1,
            () if active_activity is None else (cast(UUID, active_activity),),
        )


def _repository(*, boundary: bool = False) -> PostgreSQLLifeOpportunityRepository:
    activity = bootstrap_activity(
        "postgresql://unused",
        expected_role="unused",
        creator_party_id=uuid7(),
        pool_timeout_seconds=1,
        focus=cast(Any, _SubjectState()),
    )
    material = bootstrap_material(
        "postgresql://unused",
        expected_role="unused",
        creator_party_id=uuid7(),
        data_root=Path.cwd(),
        max_object_bytes=1_000_000,
        pool_timeout_seconds=1,
    )
    return PostgreSQLLifeOpportunityRepository(
        cast(Any, _Relationships(boundary=boundary)),
        cast(Any, _RelationshipPolicy()),
        cast(Any, _SleepRead()),
        activity.read,
        material.read,
        cast(Any, _SubjectState()),
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


def test_reconsideration_sql_is_owned_by_opportunity_port() -> None:
    owner = bootstrap_opportunity_transition()
    connection = _TransitionConnection()
    activity = asyncio.run(
        owner.reconsider_activity(
            cast(Any, connection),
            subject_id=uuid7(),
            root_opportunity_id=uuid7(),
            predecessor_opportunity_id=uuid7(),
            source_ref=uuid7(),
            source_version=2,
            activity_id=uuid7(),
        )
    )
    sleep = asyncio.run(
        owner.reconsider_sleep(
            cast(Any, connection),
            predecessor_opportunity_id=uuid7(),
        )
    )
    assert activity is not None
    assert sleep is not None
    assert all("INSERT INTO armi.opportunities" in sql for sql in connection.statements)


class _Connection:
    def __init__(
        self,
        *,
        material_id: UUID,
        revision_id: UUID,
    ) -> None:
        self._material_id = material_id
        self._revision_id = revision_id
        self._opportunity_id: UUID | None = None
        self.insert_parameters: tuple[object, ...] | None = None

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
        if "FROM armi.life_materials AS material" in statement:
            return _Cursor(
                (
                    self._material_id,
                    self._revision_id,
                    1,
                )
            )
        if "INSERT INTO armi.opportunities" in statement:
            self.insert_parameters = parameters
            if self._opportunity_id is None:
                self._opportunity_id = cast(UUID, parameters[0])
                return _Cursor((self._opportunity_id,))
            return _Cursor(None)
        if "SELECT opportunity_id" in statement:
            assert self._opportunity_id is not None
            return _Cursor((self._opportunity_id,))
        raise AssertionError(statement)


class _Audit:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def append(self, event: object) -> None:
        self.events.append(event)


class _UnitOfWork:
    def __init__(self, connection: _Connection) -> None:
        self.environment_id = uuid7()
        self.runtime_fence = RuntimeFence(
            RuntimeInstanceId(uuid7()),
            uuid7(),
            uuid7(),
            uuid7(),
            1,
        )
        self.audit = _Audit()
        self._connection = connection

    @property
    def transaction(self) -> _Connection:
        return self._connection

    def _connection_for_repository(self) -> _Connection:
        return self._connection


def test_current_active_material_admits_one_idempotent_autonomous_opportunity() -> None:
    revision_id = uuid7()
    connection = _Connection(
        material_id=uuid7(),
        revision_id=revision_id,
    )
    unit_of_work = _UnitOfWork(connection)
    repository = _repository()

    first = asyncio.run(
        repository.admit_life_material_revision(
            cast(PostgreSQLUnitOfWork, unit_of_work)
        )
    )
    replay = asyncio.run(
        repository.admit_life_material_revision(
            cast(PostgreSQLUnitOfWork, unit_of_work)
        )
    )

    assert first.status is OpportunityAdmissionStatus.ADMITTED
    assert replay.status is OpportunityAdmissionStatus.DUPLICATE
    assert replay.opportunity_id == first.opportunity_id
    assert connection.insert_parameters is not None
    assert connection.insert_parameters[3:] == (
        revision_id,
        1,
    )
    assert len(unit_of_work.audit.events) == 1


class _InternalWorkConnection:
    def __init__(self, *, activity_id: UUID, revision_id: UUID) -> None:
        self._activity_id = activity_id
        self._revision_id = revision_id
        self._opportunity_id: UUID | None = None

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
        if (
            "SELECT EXISTS (" in statement
            and "purpose = 'consider_activity_internal_work'" in statement
        ):
            return _Cursor((False, 0))
        if "SELECT revision.semantic_payload" in statement:
            return _Cursor(
                (
                    {"active_activities": [str(self._activity_id)]},
                    False,
                    0,
                    False,
                )
            )
        if "AND revision.status = 'in_progress'" in statement:
            return _Cursor(
                (
                    self._activity_id,
                    self._revision_id,
                    2,
                    "in_progress",
                    "write one bounded essay",
                    "an outline exists",
                    "draft one section",
                )
            )
        if "INSERT INTO armi.opportunities" in statement:
            if self._opportunity_id is None:
                self._opportunity_id = cast(UUID, parameters[0])
                return _Cursor((self._opportunity_id,))
            return _Cursor(None)
        if "SELECT opportunity_id" in statement:
            assert self._opportunity_id is not None
            return _Cursor((self._opportunity_id,))
        raise AssertionError(statement)


def test_active_in_progress_activity_admits_one_durable_internal_work_step() -> None:
    connection = _InternalWorkConnection(
        activity_id=uuid7(),
        revision_id=uuid7(),
    )
    unit_of_work = _UnitOfWork(cast(_Connection, connection))
    repository = _repository()

    first = asyncio.run(
        repository.admit_activity_internal_work(
            cast(PostgreSQLUnitOfWork, unit_of_work),
            model_concurrency=2,
        )
    )
    replay = asyncio.run(
        repository.admit_activity_internal_work(
            cast(PostgreSQLUnitOfWork, unit_of_work),
            model_concurrency=2,
        )
    )

    assert first.status is OpportunityAdmissionStatus.ADMITTED
    assert replay.status is OpportunityAdmissionStatus.DUPLICATE
    assert replay.opportunity_id == first.opportunity_id
    assert len(unit_of_work.audit.events) == 1


class _AttentionRetryConnection:
    def __init__(self, *, activity_id: UUID, revision_id: UUID) -> None:
        self.activity_id = activity_id
        self.revision_id = revision_id
        self.root_id = uuid7()
        self.retry_id: UUID | None = None
        self.saw_signal_query = False
        self.insert_count = 0

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
        if (
            "SELECT EXISTS (" in statement
            and "purpose = 'consider_activity_attention'" in statement
        ):
            return _Cursor((False, 0))
        if "SELECT revision.semantic_payload" in statement:
            return _Cursor(({"active_activities": []}, False, 0, False))
        if "max(previous.available_after)" in statement:
            self.saw_signal_query = (
                "decision.decision_kind = 'need_information'" in statement
                and "input.received_at > decision.decided_at" in statement
            )
            return _Cursor(
                (
                    self.activity_id,
                    self.revision_id,
                    1,
                    "ready",
                    datetime.now(UTC) - timedelta(minutes=2),
                    datetime.now(UTC) - timedelta(minutes=1),
                    None,
                    None,
                    False,
                    "review evidence over time",
                    None,
                    "classify one example",
                    None,
                    None,
                )
            )
        if "INSERT INTO armi.opportunities" in statement:
            self.insert_count += 1
            if self.insert_count == 1:
                return _Cursor(None)
            self.retry_id = cast(UUID, parameters[0])
            return _Cursor((self.retry_id,))
        if "SELECT root.opportunity_id" in statement:
            return _Cursor((self.root_id, "resolved", True, None))
        raise AssertionError(statement)


def test_attention_need_information_retries_after_new_creator_input() -> None:
    connection = _AttentionRetryConnection(activity_id=uuid7(), revision_id=uuid7())
    unit_of_work = _UnitOfWork(cast(_Connection, connection))

    outcome = asyncio.run(
        _repository().admit_activity_attention(
            cast(PostgreSQLUnitOfWork, unit_of_work),
            model_concurrency=2,
        )
    )

    assert outcome.status is OpportunityAdmissionStatus.ADMITTED
    assert outcome.opportunity_id == connection.retry_id
    assert connection.saw_signal_query
    assert len(unit_of_work.audit.events) == 1


class _OutreachConnection:
    def __init__(self, *, boundary: bool = False, awaiting: bool = False) -> None:
        self.now = datetime(2026, 8, 6, 12, tzinfo=UTC)
        self.scene_id = uuid7()
        self.creator_party_id = uuid7()
        self.interaction_id = uuid7()
        self.generation_id = uuid7()
        self._opportunity_id: UUID | None = None
        self.boundary = boundary
        self.awaiting = awaiting

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
        if "FROM armi.interaction_scenes AS scene" in statement:
            return _Cursor(
                (
                    self.scene_id,
                    self.creator_party_id,
                    self.interaction_id,
                    self.now - timedelta(days=4),
                    self.generation_id,
                    1,
                    self.now - timedelta(days=30),
                    self.now,
                )
            )
        if "FROM armi.relationships AS relationship" in statement and (
            "SELECT EXISTS" in statement
        ):
            return _Cursor((self.boundary,))
        if "FROM armi.opportunities AS opportunity" in statement and (
            "max(episode.created_at)" in statement
        ):
            return _Cursor((self.awaiting, None, self.now - timedelta(days=4)))
        if "SELECT 'creator_outreach_relationship'" in statement:
            return _Cursor(None)
        if (
            "SELECT 'creator_outreach_activity'" in statement
            or "FROM armi.activities AS activity" in statement
        ):
            return _Cursor(None)
        if "INSERT INTO armi.opportunities" in statement:
            if self._opportunity_id is None:
                self._opportunity_id = cast(UUID, parameters[0])
                return _Cursor((self._opportunity_id,))
            return _Cursor(None)
        if "SELECT opportunity_id" in statement:
            assert self._opportunity_id is not None
            return _Cursor((self._opportunity_id,))
        raise AssertionError(statement)


def test_long_absence_admits_one_scene_bound_creator_outreach_condition() -> None:
    connection = _OutreachConnection()
    unit_of_work = _UnitOfWork(cast(_Connection, connection))
    unit_of_work.runtime_fence = RuntimeFence(
        unit_of_work.runtime_fence.runtime_instance_id,
        unit_of_work.runtime_fence.subject_id,
        connection.generation_id,
        unit_of_work.runtime_fence.bundle_activation_id,
        1,
    )
    repository = _repository()
    policy = CreatorOutreachPolicy(259_200, 86_400)

    first = asyncio.run(
        repository.admit_creator_outreach(
            cast(PostgreSQLUnitOfWork, unit_of_work), policy=policy
        )
    )
    replay = asyncio.run(
        repository.admit_creator_outreach(
            cast(PostgreSQLUnitOfWork, unit_of_work), policy=policy
        )
    )

    assert first.status is OpportunityAdmissionStatus.ADMITTED
    assert replay.status is OpportunityAdmissionStatus.DUPLICATE
    assert replay.opportunity_id == first.opportunity_id
    assert len(unit_of_work.audit.events) == 1


@pytest.mark.parametrize(
    ("boundary", "awaiting", "reason"),
    [
        (True, False, "LIFE-OUTREACH-RELATIONSHIP-BOUNDARY"),
        (False, True, "LIFE-OUTREACH-AWAITING-CREATOR"),
    ],
)
def test_creator_outreach_stops_at_relationship_and_unanswered_boundaries(
    boundary: bool,
    awaiting: bool,
    reason: str,
) -> None:
    connection = _OutreachConnection(boundary=boundary, awaiting=awaiting)
    unit_of_work = _UnitOfWork(cast(_Connection, connection))
    unit_of_work.runtime_fence = RuntimeFence(
        unit_of_work.runtime_fence.runtime_instance_id,
        unit_of_work.runtime_fence.subject_id,
        connection.generation_id,
        unit_of_work.runtime_fence.bundle_activation_id,
        1,
    )

    result = asyncio.run(
        _repository(boundary=boundary).admit_creator_outreach(
            cast(PostgreSQLUnitOfWork, unit_of_work),
            policy=CreatorOutreachPolicy(259_200, 86_400),
        )
    )

    assert result.status is OpportunityAdmissionStatus.REJECTED
    assert result.reason_code == reason
    assert unit_of_work.audit.events == []
