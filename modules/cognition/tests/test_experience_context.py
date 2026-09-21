from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import pytest
from armi_cognition._context_postgresql import PostgreSQLCognitionContextLifecycle
from armi_cognition._subject_commit import PostgreSQLCognitionSubjectCommit
from armi_cognition.api import CognitionContextEpisodeDraft
from armi_experience.api import (
    AcceptedExperienceSnapshot,
    ExperienceSourcePerspective,
)
from armi_kernel.application import CandidateFactClass, CandidateViolation, ExperienceId
from armi_kernel.contracts import Digest, TraceId


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


class _Maintenance:
    def __init__(self):
        self.accepted = []

    async def pending_window(self, transaction, *, subject_id):
        return await (
            await transaction.execute("pending_window", (subject_id,))
        ).fetchone()

    async def note_accepted_experience(
        self, transaction, *, subject_id, acceptance_ordinal
    ):
        self.accepted.append((subject_id, acceptance_ordinal))

    async def complete_window(
        self, transaction, *, subject_id, after_ordinal, through_ordinal
    ):
        raise AssertionError("Unexpected completion")


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
        PostgreSQLCognitionContextLifecycle(
            experiences, _Maintenance()
        ).context_episode(  # type: ignore[arg-type]
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
        PostgreSQLCognitionContextLifecycle(
            experiences, _Maintenance()
        ).context_episode(  # type: ignore[arg-type]
            transaction,  # type: ignore[arg-type]
            episode_id=uuid7(),
        )
    )

    assert experiences.requested_ids == ids
    assert tuple(item.ordinal for item in result.experience_context) == (1, 2)
    assert all(item.maintenance_source for item in result.experience_context)
    statements = "\n".join(call[0] for call in transaction.calls)
    assert "maintenance_experience_ids" in statements
    assert "accepted_experiences" not in statements


def test_new_experience_advances_subject_progress_through_owner_port() -> None:
    transaction = _Transaction()
    maintenance = _Maintenance()
    subject_id = uuid7()
    asyncio.run(
        PostgreSQLCognitionSubjectCommit(maintenance).note_accepted_experience(
            cast(Any, transaction),
            subject_id=subject_id,
            acceptance_ordinal=1,
        )
    )
    assert maintenance.accepted == [(subject_id, 1)]
    assert transaction.calls == []


def test_maintenance_batch_freezes_sixty_four_of_sixty_five_visible_sources() -> None:
    experiences = _Experiences(tuple(_snapshot(uuid7(), index) for index in range(65)))
    draft = _maintenance_draft()
    transaction = _Transaction(
        _Result(((draft.episode_id,),)),
        _Result(((65, 0),)),
        _Result(),
    )

    assert asyncio.run(
        PostgreSQLCognitionContextLifecycle(
            experiences, _Maintenance()
        ).create_context_episode(
            cast(Any, transaction),
            draft,
        )
    )

    assert experiences.window == (0, 65, 65)
    batch_call = next(
        call
        for call in transaction.calls
        if "maintenance_experience_ids=%s::uuid[]" in call[0]
    )
    params = cast(tuple[object, ...], batch_call[1])
    assert params[1:3] == (0, 64)
    assert params[3] == [
        item.experience_id.value for item in experiences.snapshots[:64]
    ]
    assert params[4] == draft.episode_id


def test_hidden_tail_still_creates_an_empty_batch_with_frozen_coverage() -> None:
    experiences = _Experiences(())
    draft = _maintenance_draft()
    transaction = _Transaction(
        _Result(((draft.episode_id,),)),
        _Result(((5, 0),)),
        _Result(),
    )

    assert asyncio.run(
        PostgreSQLCognitionContextLifecycle(
            experiences, _Maintenance()
        ).create_context_episode(
            cast(Any, transaction),
            draft,
        )
    )

    batch_call = next(
        call
        for call in transaction.calls
        if "maintenance_experience_ids=%s::uuid[]" in call[0]
    )
    params = cast(tuple[object, ...], batch_call[1])
    assert params[1:4] == (0, 5, [])
    assert params[4] == draft.episode_id


def _frozen_item() -> dict[str, object]:
    return {
        "context_item_id": str(uuid7()),
        "ordinal": 1,
        "section": "evidence",
        "item_kind": "creator_input",
        "source_kind": "external_evidence",
        "source_ref": str(uuid7()),
        "source_version": 1,
        "trust_class": "external_claim",
        "privacy_scope": "private",
        "disposition": "included",
        "reason_code": None,
        "content_bytes": 12,
    }


@pytest.mark.parametrize("duplicate_field", ["context_item_id", "ordinal"])
def test_freezing_context_rejects_ambiguous_reference_identity(
    duplicate_field: str,
) -> None:
    first, second = _frozen_item(), _frozen_item()
    second["ordinal"] = 2
    second[duplicate_field] = first[duplicate_field]
    transaction = _Transaction()
    owner = PostgreSQLCognitionContextLifecycle(
        cast(Any, _Experiences(())), cast(Any, _Maintenance())
    )
    with pytest.raises(CandidateViolation, match="CANDIDATE-CONTEXT-ITEMS"):
        asyncio.run(
            owner.mark_context_prepared(
                cast(Any, transaction),
                episode_id=uuid7(),
                manifest_artifact_id=uuid7(),
                compiled_artifact_id=uuid7(),
                compiled_digest=Digest("sha256:" + "2" * 64),
                context_items=(first, second),
            )
        )
    assert transaction.calls == []


def test_preparation_freezes_references_with_artifact_identity_in_one_write() -> None:
    episode_id, opportunity_id, subject_id = uuid7(), uuid7(), uuid7()
    transaction = _Transaction(
        _Result(
            (
                (
                    episode_id,
                    opportunity_id,
                    subject_id,
                    None,
                    None,
                    "consider_creator_input",
                    0,
                    0,
                    uuid7(),
                    "context-test",
                    "1" * 32,
                ),
            )
        )
    )
    owner = PostgreSQLCognitionContextLifecycle(
        cast(Any, _Experiences(())), cast(Any, _Maintenance())
    )
    item = _frozen_item()
    snapshot = asyncio.run(
        owner.mark_context_prepared(
            cast(Any, transaction),
            episode_id=episode_id,
            manifest_artifact_id=uuid7(),
            compiled_artifact_id=uuid7(),
            compiled_digest=Digest("sha256:" + "2" * 64),
            context_items=(item,),
        )
    )
    assert snapshot.episode_id == episode_id
    assert len(transaction.calls) == 1
    assert json.loads(str(cast(tuple[object, ...], transaction.calls[0][1])[-2])) == [
        item
    ]
