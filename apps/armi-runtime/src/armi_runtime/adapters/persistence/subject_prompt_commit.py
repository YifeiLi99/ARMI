"""Subject-owned Prompt revisions applied only inside T-03."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactRef,
    CandidateSubjectPromptDraft,
    SubjectCommitViolation,
)

SubjectPromptHead = tuple[UUID | None, int]


async def lock_subject_prompt_heads(
    connection: Any,
    *,
    subject_id: UUID,
    prompts: tuple[CandidateSubjectPromptDraft, ...],
) -> dict[UUID, SubjectPromptHead]:
    result: dict[UUID, SubjectPromptHead] = {}
    for document_id in sorted({item.prompt_document_id for item in prompts}, key=str):
        row = await (
            await connection.execute(
                """
                SELECT document.current_revision_id,
                       COALESCE(revision.revision_no, 0)
                FROM armi.prompt_documents AS document
                LEFT JOIN armi.prompt_revisions AS revision
                  ON revision.prompt_revision_id = document.current_revision_id
                 AND revision.prompt_document_id = document.prompt_document_id
                WHERE document.prompt_document_id = %s
                  AND document.subject_id = %s
                  AND document.prompt_kind = 'subject_guidance'
                  AND document.write_authority = 'subject'
                  AND document.status = 'active'
                FOR UPDATE OF document
                """,
                (document_id, subject_id),
            )
        ).fetchone()
        if row is None:
            raise SubjectCommitViolation("SUBJECT-PROMPT-HEAD-MISSING")
        result[document_id] = (row[0], int(row[1]))
    return result


def subject_prompt_heads_are_stale(
    heads: dict[UUID, SubjectPromptHead],
    prompts: tuple[CandidateSubjectPromptDraft, ...],
) -> bool:
    return any(
        heads.get(prompt.prompt_document_id)
        != (prompt.current_revision_id, prompt.expected_revision_no)
        for prompt in prompts
    )


async def apply_subject_prompts(
    connection: Any,
    *,
    validation_id: UUID,
    subject_id: UUID,
    commit_id: UUID,
    prompts: tuple[CandidateSubjectPromptDraft, ...],
    artifacts: dict[str, ArtifactRef],
) -> tuple[UUID, ...]:
    if len(prompts) > 1:
        raise SubjectCommitViolation("SUBJECT-PROMPT-COUNT")
    if not prompts:
        return ()
    party_row = await (
        await connection.execute(
            """
            SELECT party_id
            FROM armi.parties
            WHERE party_kind = 'subject'
              AND represented_subject_id = %s
            """,
            (subject_id,),
        )
    ).fetchone()
    if party_row is None:
        raise SubjectCommitViolation("SUBJECT-PROMPT-AUTHOR")
    author_party_id = party_row[0]
    revision_ids: list[UUID] = []
    for prompt in prompts:
        artifact = artifacts.get(prompt.proposal_ref)
        if artifact is None:
            raise SubjectCommitViolation("SUBJECT-PROMPT-ARTIFACT")
        accepted = await (
            await connection.execute(
                """
                SELECT 1
                FROM armi.cognitive_candidate_validation_items
                WHERE candidate_validation_id = %s
                  AND proposal_ref = %s
                  AND owner_kind = 'prompt'
                  AND validation_status = 'accepted'
                """,
                (validation_id, prompt.proposal_ref),
            )
        ).fetchone()
        if accepted is None:
            raise SubjectCommitViolation("SUBJECT-PROMPT-CANDIDATE")
        if (
            artifact.media_type != "application/json"
            or artifact.privacy_scope.value != "private"
        ):
            raise SubjectCommitViolation("SUBJECT-PROMPT-ARTIFACT")
        revision_id = uuid7()
        revision_ids.append(revision_id)
        await connection.execute(
            """
            INSERT INTO armi.prompt_revisions (
                prompt_revision_id, prompt_document_id, revision_no,
                previous_revision_id, content_artifact_id, content_digest,
                author_party_id, subject_commit_id, change_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                revision_id,
                prompt.prompt_document_id,
                prompt.expected_revision_no + 1,
                prompt.current_revision_id,
                artifact.artifact_id.value,
                artifact.content_digest.value,
                author_party_id,
                commit_id,
                (
                    "subject_created"
                    if prompt.current_revision_id is None
                    else "subject_revised"
                ),
            ),
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.prompt_documents
                SET current_revision_id = %s
                WHERE prompt_document_id = %s
                  AND subject_id = %s
                  AND current_revision_id IS NOT DISTINCT FROM %s
                  AND status = 'active'
                RETURNING prompt_document_id
                """,
                (
                    revision_id,
                    prompt.prompt_document_id,
                    subject_id,
                    prompt.current_revision_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise SubjectCommitViolation("SUBJECT-PROMPT-HEAD-STALE")
    return tuple(revision_ids)


__all__ = (
    "SubjectPromptHead",
    "apply_subject_prompts",
    "lock_subject_prompt_heads",
    "subject_prompt_heads_are_stale",
)
