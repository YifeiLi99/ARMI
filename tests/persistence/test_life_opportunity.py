from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid7

import pytest
from armi_kernel.application import (
    CreatorOutreachPolicy,
    OpportunityAdmissionStatus,
    RuntimeFence,
    RuntimeInstanceId,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.persistence.life_opportunity import (
    PostgreSQLLifeOpportunityRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWork


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _Connection:
    def __init__(
        self,
        *,
        material_id: UUID,
        revision_id: UUID,
        digest: Digest,
    ) -> None:
        self._material_id = material_id
        self._revision_id = revision_id
        self._digest = digest
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
                    self._digest.value,
                )
            )
        if "INSERT INTO armi.opportunities" in statement:
            self.insert_parameters = parameters
            if self._opportunity_id is None:
                self._opportunity_id = cast(UUID, parameters[0])
                return _Cursor((self._opportunity_id,))
            return _Cursor(None)
        if "SELECT opportunity_id, source_digest" in statement:
            assert self._opportunity_id is not None
            return _Cursor((self._opportunity_id, self._digest.value))
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

    def _connection_for_repository(self) -> _Connection:
        return self._connection


def test_current_active_material_admits_one_idempotent_autonomous_opportunity() -> None:
    digest = Digest.from_bytes(b"material revision")
    revision_id = uuid7()
    connection = _Connection(
        material_id=uuid7(),
        revision_id=revision_id,
        digest=digest,
    )
    unit_of_work = _UnitOfWork(connection)
    repository = PostgreSQLLifeOpportunityRepository()

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
        digest.value,
    )
    assert len(unit_of_work.audit.events) == 1


class _InternalWorkConnection:
    def __init__(self, *, activity_id: UUID, revision_id: UUID) -> None:
        self._activity_id = activity_id
        self._revision_id = revision_id
        self._opportunity_id: UUID | None = None
        self._source_digest: str | None = None

    async def execute(
        self,
        statement: str,
        parameters: tuple[object, ...] = (),
    ) -> _Cursor:
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
                self._source_digest = cast(str, parameters[5])
                return _Cursor((self._opportunity_id,))
            return _Cursor(None)
        if "SELECT opportunity_id, source_digest" in statement:
            assert self._opportunity_id is not None
            assert self._source_digest is not None
            return _Cursor((self._opportunity_id, self._source_digest))
        raise AssertionError(statement)


def test_active_in_progress_activity_admits_one_durable_internal_work_step() -> None:
    connection = _InternalWorkConnection(
        activity_id=uuid7(),
        revision_id=uuid7(),
    )
    unit_of_work = _UnitOfWork(cast(_Connection, connection))
    repository = PostgreSQLLifeOpportunityRepository()

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


class _OutreachConnection:
    def __init__(self, *, boundary: bool = False, awaiting: bool = False) -> None:
        self.now = datetime(2026, 8, 6, 12, tzinfo=UTC)
        self.scene_id = uuid7()
        self.creator_party_id = uuid7()
        self.interaction_id = uuid7()
        self.generation_id = uuid7()
        self._opportunity_id: UUID | None = None
        self._source_digest: str | None = None
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
        if "SELECT 'creator_outreach_activity'" in statement:
            return _Cursor(None)
        if "INSERT INTO armi.opportunities" in statement:
            self._source_digest = cast(str, parameters[9])
            if self._opportunity_id is None:
                self._opportunity_id = cast(UUID, parameters[0])
                return _Cursor((self._opportunity_id,))
            return _Cursor(None)
        if "SELECT opportunity_id, source_digest" in statement:
            assert self._opportunity_id is not None
            assert self._source_digest is not None
            return _Cursor((self._opportunity_id, self._source_digest))
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
    repository = PostgreSQLLifeOpportunityRepository()
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
        PostgreSQLLifeOpportunityRepository().admit_creator_outreach(
            cast(PostgreSQLUnitOfWork, unit_of_work),
            policy=CreatorOutreachPolicy(259_200, 86_400),
        )
    )

    assert result.status is OpportunityAdmissionStatus.REJECTED
    assert result.reason_code == reason
    assert unit_of_work.audit.events == []
