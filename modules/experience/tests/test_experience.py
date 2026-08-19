from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString, Never, cast
from uuid import uuid7

import pytest
from armi_data_rights.api import (
    DataRightsDiscoveryRequest,
    DataRightsExportScope,
    DataRightsRelatedRef,
)
from armi_experience._data_rights import PostgreSQLExperienceDataRightsParticipant
from armi_experience._postgresql import PostgreSQLExperienceOwner
from armi_experience.api import (
    AcceptedExperienceDraft,
    ExperienceKind,
    ExperienceSourcePerspective,
    ExperienceViolation,
)
from armi_kernel.application import CandidateFactClass, ExperienceId
from armi_runtime_foundation import (
    PostgreSQLParameters,
    PostgreSQLResult,
)


class _Result:
    def __init__(self, rows: tuple[tuple[object, ...], ...] = ()) -> None:
        self._rows = rows

    @property
    def rowcount(self) -> int:
        return len(self._rows)

    async def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self._rows

    async def fetchone(self) -> tuple[object, ...] | None:
        return None if not self._rows else self._rows[0]


class _Transaction:
    def __init__(self, *results: _Result) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, PostgreSQLParameters]] = []

    async def execute(
        self,
        statement: LiteralString,
        parameters: PostgreSQLParameters = (),
        /,
    ) -> PostgreSQLResult[tuple[Never, ...]]:
        self.calls.append((statement, parameters))
        result = self.results.pop(0) if self.results else _Result()
        return cast(PostgreSQLResult[tuple[Never, ...]], result)


def _draft() -> AcceptedExperienceDraft:
    return AcceptedExperienceDraft(
        ExperienceId(uuid7()),
        uuid7(),
        uuid7(),
        uuid7(),
        "proposal:1",
        ExperienceKind.CREATOR_INPUT,
        CandidateFactClass.EXTERNAL_CLAIM,
        "创造者告诉我今天会下雨。",
        uuid7(),
        datetime(2026, 8, 17, tzinfo=UTC),
        ExperienceSourcePerspective.CREATOR_CLAIM,
        None,
    )


def _row(experience_id: object, accepted_at: datetime) -> tuple[object, ...]:
    return (
        experience_id,
        "external_claim",
        "创造者告诉我今天会下雨。",
        accepted_at - timedelta(minutes=1),
        accepted_at,
        "creator_claim",
        None,
    )


def test_draft_rejects_mismatched_source_pair() -> None:
    draft = _draft()
    with pytest.raises(ExperienceViolation, match="EXPERIENCE-DRAFT"):
        AcceptedExperienceDraft(
            draft.experience_id,
            draft.subject_id,
            draft.subject_commit_id,
            draft.cognitive_episode_id,
            draft.proposal_ref,
            draft.experience_kind,
            draft.fact_class,
            draft.first_person_gist,
            draft.scene_id,
            draft.occurred_at,
            ExperienceSourcePerspective.WEB_CLAIM,
            draft.uncertainty,
        )


def test_record_writes_only_the_experience_owner_table() -> None:
    transaction = _Transaction()
    draft = _draft()

    asyncio.run(PostgreSQLExperienceOwner().record(transaction, draft))  # type: ignore[arg-type]

    assert len(transaction.calls) == 1
    statement, params = transaction.calls[0]
    assert "INSERT INTO armi.accepted_experiences" in statement
    assert "cognition_maintenance" not in statement
    assert params is not None


def test_read_ports_preserve_recent_and_requested_order() -> None:
    first, second = uuid7(), uuid7()
    now = datetime(2026, 8, 17, 12, tzinfo=UTC)
    transaction = _Transaction(
        _Result((_row(first, now), _row(second, now + timedelta(minutes=1)))),
        _Result((_row(second, now + timedelta(minutes=1)), _row(first, now))),
    )
    owner = PostgreSQLExperienceOwner()

    recent = asyncio.run(
        owner.recent(transaction, subject_id=uuid7(), limit=8)  # type: ignore[arg-type]
    )
    requested = asyncio.run(
        owner.by_ids(  # type: ignore[arg-type]
            transaction,
            subject_id=uuid7(),
            experience_ids=(second, first),
        )
    )

    assert tuple(item.experience_id.value for item in recent) == (first, second)
    assert tuple(item.experience_id.value for item in requested) == (second, first)


def test_accepted_after_requires_a_valid_processed_boundary() -> None:
    transaction = _Transaction(_Result())

    with pytest.raises(ExperienceViolation, match="EXPERIENCE-CURSOR"):
        asyncio.run(
            PostgreSQLExperienceOwner().accepted_after(  # type: ignore[arg-type]
                transaction,
                subject_id=uuid7(),
                after_experience_id=uuid7(),
                since=datetime(2026, 8, 17, tzinfo=UTC),
                limit=64,
            )
        )


def test_life_record_and_data_rights_are_experience_owned() -> None:
    experience_id = uuid7()
    accepted_at = datetime(2026, 8, 17, 12, tzinfo=UTC)
    owner = PostgreSQLExperienceOwner()
    life_transaction = _Transaction(
        _Result(((experience_id, "一段经历", "creator_claim", accepted_at),))
    )
    rows = asyncio.run(
        owner.life_record_branch(  # type: ignore[arg-type]
            life_transaction,
            subject_id=uuid7(),
            query_text="经历",
            before=None,
            limit=20,
        )
    )
    assert rows[0].experience_id == experience_id

    participant = PostgreSQLExperienceDataRightsParticipant()
    contribution = asyncio.run(
        participant.discover(  # type: ignore[arg-type]
            _Transaction(),
            DataRightsDiscoveryRequest(
                uuid7(),
                uuid7(),
                (DataRightsRelatedRef("experience", experience_id),),
            ),
        )
    )
    assert participant.owner_identity.value == "experience"
    assert contribution.targets[0].ref == experience_id

    export_transaction = _Transaction(_Result(((b'{"experience_id":"x"}\n',),)))
    segments = asyncio.run(
        participant.export(  # type: ignore[arg-type]
            export_transaction,
            DataRightsExportScope(uuid7()),
        )
    )
    assert segments[0].segment_name == "accepted_experiences"
    assert (asyncio.run(segments[0].records.read_batch()))[0].value.endswith(b"\n")


def test_public_protocols_are_structurally_usable() -> None:
    owner: Any = PostgreSQLExperienceOwner()
    assert callable(owner.record)
    assert callable(owner.recent)
    assert callable(owner.accepted_after)
    assert callable(owner.by_ids)
    assert callable(owner.life_record_branch)
