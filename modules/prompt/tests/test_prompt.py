from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid7

import pytest
import rfc8785
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    CandidateFactClass,
)
from armi_kernel.contracts import Digest, TraceId
from armi_prompt.api import (
    CandidatePromptDraft,
    CreatorPromptDeactivateCommand,
    CreatorPromptRevisionCommand,
    CreatorPromptViolation,
    PromptKind,
    PromptViolation,
    default_prompt_cognition,
)
from armi_prompt.bootstrap import bootstrap_prompt


def _draft(
    document_id: UUID,
    *,
    current_revision_id: UUID | None = None,
    revision_no: int = 0,
    cognition_method: str = "先区分观察与推断",
) -> CandidatePromptDraft:
    return CandidatePromptDraft(
        "proposal:2",
        "group:1",
        (2, 1) if current_revision_id is None else (2, 1, 6),
        CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        document_id,
        current_revision_id,
        revision_no,
        rfc8785.dumps(
            cast(
                Any,
                {
                    "schema_version": "armi.subject-prompt.v1",
                    "cognition_method": cognition_method,
                    "expression_method": "清楚表达确定与不确定的部分",
                    "reflection_method": "在经历后回看方法是否仍然合适",
                },
            )
        ),
    )


def _artifact(content: bytes) -> ArtifactRef:
    return ArtifactRef(
        ArtifactId(uuid7()),
        Digest.from_bytes(content),
        len(content),
        "application/json",
        "subject_prompt",
        ArtifactPrivacyScope.PRIVATE,
        ArtifactIntegrityStatus.VERIFIED,
    )


class _Result:
    def __init__(self, row: tuple[object, ...] | None = None) -> None:
        self._row = row

    async def fetchone(self) -> tuple[object, ...] | None:
        return self._row


class _PromptTransaction:
    def __init__(self, *, subject_id: UUID, document_id: UUID) -> None:
        self.subject_id = subject_id
        self.document_id = document_id
        self.subject_party_id = uuid7()
        self.current_revision_id: UUID | None = None
        self.revision_no = 0

    async def execute(self, query: str, params: tuple[object, ...] = ()) -> _Result:
        if "FOR UPDATE OF document" in query:
            return _Result((self.current_revision_id, self.revision_no))
        if "cognitive_candidate_validation_items" in query:
            return _Result((1,))
        if "FROM armi.parties" in query:
            return _Result((self.subject_party_id,))
        if "INSERT INTO armi.prompt_revisions" in query:
            return _Result()
        if "UPDATE armi.prompt_documents" in query:
            self.current_revision_id = cast(UUID, params[0])
            self.revision_no += 1
            return _Result((self.document_id,))
        raise AssertionError(query)


def test_prompt_owner_draft_round_trip_is_canonical() -> None:
    draft = _draft(uuid7())
    cognition = default_prompt_cognition()
    assert cognition.decode(cognition.bind(draft).canonical_payload) == draft


@pytest.mark.asyncio
async def test_subject_prompt_commit_uses_owner_draft_and_cas() -> None:
    subject_id, document_id = uuid7(), uuid7()
    transaction = _PromptTransaction(subject_id=subject_id, document_id=document_id)
    module = bootstrap_prompt()
    draft = _draft(document_id)
    owners = (module.cognition.bind(draft),)
    assert await module.commit.heads_match(
        transaction, subject_id=subject_id, drafts=owners
    )
    changed = await module.commit.commit(
        transaction,
        validation_id=uuid7(),
        subject_id=subject_id,
        commit_id=uuid7(),
        drafts=owners,
        artifacts={draft.proposal_ref: _artifact(draft.content_bytes)},
    )
    assert changed == (document_id,)
    assert transaction.revision_no == 1
    assert not await module.commit.heads_match(
        transaction, subject_id=subject_id, drafts=owners
    )


@pytest.mark.asyncio
async def test_subject_prompt_requires_published_artifact() -> None:
    subject_id, document_id = uuid7(), uuid7()
    transaction = _PromptTransaction(subject_id=subject_id, document_id=document_id)
    module = bootstrap_prompt()
    draft = _draft(document_id)
    with pytest.raises(PromptViolation, match="PROMPT-ARTIFACT"):
        await module.commit.commit(
            transaction,
            validation_id=uuid7(),
            subject_id=subject_id,
            commit_id=uuid7(),
            drafts=(module.cognition.bind(draft),),
            artifacts={},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prompt_kind", [PromptKind.PERSONALITY_ANCHOR, PromptKind.SUBJECT_GUIDANCE]
)
async def test_creator_prompt_rejects_cross_authority_before_io(
    prompt_kind: PromptKind,
) -> None:
    unavailable = cast(Any, object())
    module = bootstrap_prompt(
        creator_party_id=uuid7(),
        storage=unavailable,
        catalog=unavailable,
        unit_of_work_factory=unavailable,
    )
    service = module.creator
    assert service is not None
    with pytest.raises(CreatorPromptViolation, match="SCOPE-PROMPT-NOT-WRITABLE"):
        await service.revise(
            CreatorPromptRevisionCommand(
                prompt_kind, None, "不能越权写入", TraceId("1" * 32)
            )
        )
    with pytest.raises(CreatorPromptViolation, match="SCOPE-PROMPT-NOT-WRITABLE"):
        await service.deactivate(
            CreatorPromptDeactivateCommand(prompt_kind, uuid7(), TraceId("2" * 32))
        )
