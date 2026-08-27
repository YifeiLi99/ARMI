from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

from armi_cognition._context_postgresql import PostgreSQLCognitionContextLifecycle
from armi_cognition._subject_commit import PostgreSQLCognitionSubjectCommit
from armi_cognition.api import CognitionContextEpisodeDraft
from armi_experience.api import (
    AcceptedExperienceSnapshot,
    ExperienceSourcePerspective,
)
from armi_kernel.application import CandidateFactClass, ExperienceId
from armi_kernel.contracts import TraceId


class _Result:
    def __init__(self, rows: tuple[tuple[object, ...], ...] = ()) -> None:
        self.rows = rows

    async def fetchone(self) -> tuple[object, ...] | None:
        return None if not self.rows else self.rows[0]

    async def fetchall(self) -> tuple[tuple[object, ...], ...]:
        return self.rows


class _Transaction:
    def __init__(self, *results: _Result) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, object | None]] = []

    async def execute(self, statement: str, params: object | None = None) -> _Result:
        self.calls.append((statement, params))
        return self.results.pop(0) if self.results else _Result()


class _Experiences:
    def __init__(self, snapshots: tuple[AcceptedExperienceSnapshot, ...]) -> None:
        self.snapshots = snapshots
        self.recent_limit: int | None = None
        self.requested_ids: tuple[UUID, ...] = ()
        self.window: tuple[int, int, int] | None = None

    async def recent(self, transaction, *, subject_id, limit):
        self.recent_limit = limit
        return self.snapshots

    async def accepted_in_ordinal_window(
        self,
        transaction,
        *,
        subject_id,
        after_ordinal,
        through_ordinal,
        limit,
    ):
        self.window = (after_ordinal, through_ordinal, limit)
        return self.snapshots[:limit]

    async def by_ids(self, transaction, *, subject_id, experience_ids):
        self.requested_ids = experience_ids
        by_id = {item.experience_id.value: item for item in self.snapshots}
        return tuple(by_id[value] for value in experience_ids)


def _snapshot(experience_id: UUID, minute: int) -> AcceptedExperienceSnapshot:
    accepted_at = datetime(2026, 8, 17, 12, tzinfo=UTC) + timedelta(minutes=minute)
    return AcceptedExperienceSnapshot(
        minute + 1,
        ExperienceId(experience_id),
        CandidateFactClass.EXTERNAL_CLAIM,
        f"经历 {minute}",
        accepted_at - timedelta(minutes=1),
        accepted_at,
        ExperienceSourcePerspective.CREATOR_CLAIM,
        None,
    )


def _episode_row(purpose: str) -> tuple[object, ...]:
    return (
        uuid7(),
        uuid7(),
        uuid7(),
        uuid7(),
        uuid7(),
        purpose,
        3,
        4,
        uuid7(),
        "mechanism-v1",
        "0123456789abcdef0123456789abcdef",
    )


def _maintenance_draft() -> CognitionContextEpisodeDraft:
    return CognitionContextEpisodeDraft(
        episode_id=uuid7(),
        opportunity_id=uuid7(),
        subject_id=uuid7(),
        generation_id=uuid7(),
        scene_id=None,
        context_party_id=None,
        purpose="maintain_subjective_memory",
        base_subject_version=3,
        base_state_epoch=4,
        bundle_activation_id=uuid7(),
        mechanism_identity="armi.context-compiler.layered-v3",
        trace_id=TraceId("0123456789abcdef0123456789abcdef"),
        maintenance_trigger_kind="runtime_idle",
    )


def test_creator_context_reads_recent_eight_through_experience_port() -> None:
    ids = (uuid7(), uuid7())
    experiences = _Experiences(
        tuple(_snapshot(value, index) for index, value in enumerate(ids))
    )
    transaction = _Transaction(
        _Result((_episode_row("consider_creator_input"),)), _Result()
    )

    result = asyncio.run(
        PostgreSQLCognitionContextLifecycle(experiences).context_episode(  # type: ignore[arg-type]
            transaction,  # type: ignore[arg-type]
            episode_id=uuid7(),
        )
    )

    assert experiences.recent_limit == 8
    assert tuple(item.experience_id for item in result.experience_context) == ids
    assert tuple(item.ordinal for item in result.experience_context) == (2, 1)
    assert not any(item.maintenance_source for item in result.experience_context)
    assert all("accepted_experiences" not in call[0] for call in transaction.calls)


def test_maintenance_context_keeps_batch_ownership_in_cognition() -> None:
    ids = (uuid7(), uuid7())
    experiences = _Experiences(
        tuple(_snapshot(value, index) for index, value in enumerate(ids))
    )
    transaction = _Transaction(
        _Result((_episode_row("maintain_subjective_memory"),)),
        _Result(),
        _Result(((ids[0], 1), (ids[1], 2))),
    )

    result = asyncio.run(
        PostgreSQLCognitionContextLifecycle(experiences).context_episode(  # type: ignore[arg-type]
            transaction,  # type: ignore[arg-type]
            episode_id=uuid7(),
        )
    )

    assert experiences.requested_ids == ids
    assert tuple(item.ordinal for item in result.experience_context) == (1, 2)
    assert all(item.maintenance_source for item in result.experience_context)
    statements = "\n".join(call[0] for call in transaction.calls)
    assert "cognition_maintenance_batch_sources" in statements
    assert "accepted_experiences" not in statements


def test_new_experience_only_marks_cognition_maintenance_cursor() -> None:
    transaction = _Transaction()
    asyncio.run(
        PostgreSQLCognitionSubjectCommit().note_accepted_experience(
            transaction,  # type: ignore[arg-type]
            subject_id=uuid7(),
            generation_id=uuid7(),
            acceptance_ordinal=1,
        )
    )

    assert len(transaction.calls) == 1
    assert "cognition_maintenance_cursors" in transaction.calls[0][0]
    assert "accepted_experiences" not in transaction.calls[0][0]


def test_maintenance_batch_freezes_sixty_four_of_sixty_five_visible_sources() -> None:
    experiences = _Experiences(tuple(_snapshot(uuid7(), index) for index in range(65)))
    draft = _maintenance_draft()
    transaction = _Transaction(
        _Result(((draft.episode_id,),)),
        _Result(((65, 0),)),
        _Result(),
    )

    assert asyncio.run(
        PostgreSQLCognitionContextLifecycle(experiences).create_context_episode(
            cast(Any, transaction),
            draft,
        )
    )

    assert experiences.window == (0, 65, 65)
    batch_call = next(
        call
        for call in transaction.calls
        if "INSERT INTO armi.cognition_maintenance_batches" in call[0]
    )
    assert batch_call[1][-3:] == (0, 64, 64)  # type: ignore[index]
    source_call = next(
        call
        for call in transaction.calls
        if "INSERT INTO armi.cognition_maintenance_batch_sources" in call[0]
    )
    assert len(source_call[1][1]) == 64  # type: ignore[index]


def test_hidden_tail_still_creates_an_empty_batch_with_frozen_coverage() -> None:
    experiences = _Experiences(())
    draft = _maintenance_draft()
    transaction = _Transaction(
        _Result(((draft.episode_id,),)),
        _Result(((5, 0),)),
        _Result(),
    )

    assert asyncio.run(
        PostgreSQLCognitionContextLifecycle(experiences).create_context_episode(
            cast(Any, transaction),
            draft,
        )
    )

    batch_call = next(
        call
        for call in transaction.calls
        if "INSERT INTO armi.cognition_maintenance_batches" in call[0]
    )
    assert batch_call[1][-3:] == (0, 5, 0)  # type: ignore[index]
    assert not any(
        "INSERT INTO armi.cognition_maintenance_batch_sources" in statement
        for statement, _params in transaction.calls
    )
