from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid7

import pytest
import rfc8785
from armi_kernel.application import (
    ArtifactId,
    CandidateFactClass,
    CandidateSubjectPromptDraft,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest
from armi_runtime.adapters.persistence.subject_prompt_commit import (
    apply_subject_prompts,
    lock_subject_prompt_heads,
    subject_prompt_heads_are_stale,
)


class _Result:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _PromptConnection:
    def __init__(self, *, subject_id: UUID, document_id: UUID) -> None:
        self.subject_id = subject_id
        self.document_id = document_id
        self.subject_party_id = uuid7()
        self.current_revision_id: UUID | None = None
        self.revision_no = 0
        self.artifacts: dict[UUID, Digest] = {}
        self.revisions: list[tuple[object, ...]] = []

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> _Result:
        if "FOR UPDATE OF document" in query:
            if params != (self.document_id, self.subject_id):
                return _Result()
            return _Result((self.current_revision_id, self.revision_no))
        if "FROM armi.parties" in query:
            return _Result(
                (self.subject_party_id,) if params == (self.subject_id,) else None
            )
        if "FROM armi.cognitive_candidate_validation_items" in query:
            return _Result((1,))
        if "FROM armi.artifacts" in query:
            digest = self.artifacts.get(cast(UUID, params[0]))
            return _Result(
                None
                if digest is None
                else (digest.value, "application/json", "private")
            )
        if "INSERT INTO armi.prompt_revisions" in query:
            self.revisions.append(params)
            return _Result()
        if "UPDATE armi.prompt_documents" in query:
            if (
                params[1] != self.document_id
                or params[2] != self.subject_id
                or params[3] != self.current_revision_id
            ):
                return _Result()
            self.current_revision_id = cast(UUID, params[0])
            self.revision_no += 1
            return _Result((self.document_id,))
        raise AssertionError(f"unexpected SQL: {query}")


def _draft(
    document_id: UUID,
    *,
    current_revision_id: UUID | None = None,
    revision_no: int = 0,
    cognition_method: str = "先区分观察与推断",
) -> CandidateSubjectPromptDraft:
    content = rfc8785.dumps(
        cast(
            Any,
            {
                "schema_version": "armi.subject-prompt.v1",
                "cognition_method": cognition_method,
                "expression_method": "清楚表达确定与不确定的部分",
                "reflection_method": "在经历后回看方法是否仍然合适",
            },
        )
    )
    return CandidateSubjectPromptDraft(
        "proposal:2",
        "group:1",
        (2, 1) if current_revision_id is None else (2, 1, 6),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        document_id,
        current_revision_id,
        revision_no,
        content,
        Digest.from_bytes(content),
    )


@pytest.mark.asyncio
async def test_subject_prompt_commit_creates_then_revises_with_subject_commit() -> None:
    subject_id, document_id = uuid7(), uuid7()
    connection = _PromptConnection(subject_id=subject_id, document_id=document_id)
    created = _draft(document_id)
    heads = await lock_subject_prompt_heads(
        connection, subject_id=subject_id, prompts=(created,)
    )
    assert not subject_prompt_heads_are_stale(heads, (created,))
    first_artifact = ArtifactId(uuid7())
    first_commit = uuid7()
    connection.artifacts[first_artifact.value] = created.content_digest
    await apply_subject_prompts(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        commit_id=first_commit,
        prompts=(created,),
        artifact_ids={created.proposal_ref: first_artifact},
    )
    first_revision_id = connection.current_revision_id
    assert first_revision_id is not None
    assert connection.revision_no == 1
    assert connection.revisions[0][3] is None
    assert connection.revisions[0][7] == first_commit
    assert connection.revisions[0][8] == "subject_created"

    revised = _draft(
        document_id,
        current_revision_id=first_revision_id,
        revision_no=1,
        cognition_method="先核对经历证据再形成理解",
    )
    heads = await lock_subject_prompt_heads(
        connection, subject_id=subject_id, prompts=(revised,)
    )
    assert not subject_prompt_heads_are_stale(heads, (revised,))
    second_artifact = ArtifactId(uuid7())
    second_commit = uuid7()
    connection.artifacts[second_artifact.value] = revised.content_digest
    await apply_subject_prompts(
        connection,
        validation_id=uuid7(),
        subject_id=subject_id,
        commit_id=second_commit,
        prompts=(revised,),
        artifact_ids={revised.proposal_ref: second_artifact},
    )
    assert connection.revision_no == 2
    assert connection.revisions[1][3] == first_revision_id
    assert connection.revisions[1][7] == second_commit
    assert connection.revisions[1][8] == "subject_revised"


@pytest.mark.asyncio
async def test_subject_prompt_commit_rejects_stale_or_missing_artifact_without_head_change() -> (
    None
):
    subject_id, document_id = uuid7(), uuid7()
    connection = _PromptConnection(subject_id=subject_id, document_id=document_id)
    stale = _draft(document_id, current_revision_id=uuid7(), revision_no=1)
    heads = await lock_subject_prompt_heads(
        connection, subject_id=subject_id, prompts=(stale,)
    )
    assert subject_prompt_heads_are_stale(heads, (stale,))

    created = _draft(document_id)
    with pytest.raises(SubjectCommitViolation, match="SUBJECT-PROMPT-ARTIFACT"):
        await apply_subject_prompts(
            connection,
            validation_id=uuid7(),
            subject_id=subject_id,
            commit_id=uuid7(),
            prompts=(created,),
            artifact_ids={},
        )
    assert connection.current_revision_id is None
    assert connection.revisions == []
