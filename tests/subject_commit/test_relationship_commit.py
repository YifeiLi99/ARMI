from __future__ import annotations

from uuid import UUID, uuid7

import pytest
from armi_kernel.application import (
    CandidateFactClass,
    CandidateRelationshipDraft,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipStatus,
)
from armi_runtime.adapters.persistence.relationship_commit import apply_relationships


class _Result:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _RelationshipConnection:
    def __init__(
        self,
        *,
        subject_id: UUID,
        subject_party_id: UUID,
        creator_party_id: UUID,
    ) -> None:
        self.subject_id = subject_id
        self.subject_party_id = subject_party_id
        self.creator_party_id = creator_party_id
        self.revision_parameters: tuple[object, ...] | None = None

    async def execute(
        self,
        query: str,
        params: tuple[object, ...] = (),
    ) -> _Result:
        assert query.count("%s") == len(params)
        if "FROM armi.cognitive_candidate_validation_items" in query:
            return _Result((1,))
        if "FROM armi.parties AS subject_party" in query:
            assert params == (
                self.creator_party_id,
                self.subject_party_id,
                self.subject_id,
            )
            return _Result((1,))
        if "FROM armi.relationships" in query:
            return _Result()
        if "INSERT INTO armi.relationship_revisions" in query:
            self.revision_parameters = params
        return _Result()


@pytest.mark.asyncio
async def test_relationship_commit_binds_every_revision_value() -> None:
    subject_id = uuid7()
    subject_party_id = uuid7()
    creator_party_id = uuid7()
    experience_id = uuid7()
    connection = _RelationshipConnection(
        subject_id=subject_id,
        subject_party_id=subject_party_id,
        creator_party_id=creator_party_id,
    )
    relationship = CandidateRelationshipDraft(
        "proposal:2",
        "group:1",
        (1,),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        uuid7(),
        subject_party_id,
        creator_party_id,
        None,
        0,
        "proposal:1",
        (
            RelationshipFact(
                RelationshipFactKind.SHARED_EXPERIENCE,
                "Creator 尊重我对记忆的自主选择。",
            ),
        ),
        "这次交流体现了对主体选择的尊重。",
        (),
        RelationshipStatus.ACTIVE,
    )

    await apply_relationships(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        generation_id=uuid7(),
        creator_party_id=creator_party_id,
        commit_id=uuid7(),
        relationships=(relationship,),
        experience_ids={"proposal:1": experience_id},
    )

    assert connection.revision_parameters is not None
    assert len(connection.revision_parameters) == 16
