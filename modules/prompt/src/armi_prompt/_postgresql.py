"""PostgreSQL ownership for Prompt documents and subject revisions."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import ArtifactRef, CandidateOwnerDraft
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLTransaction

from ._application import PromptApplication
from .api import (
    PromptContextSource,
    PromptContextSources,
    PromptRecoveryState,
    PromptViolation,
    SubjectPromptHead,
)


class PostgreSQLPromptOwner:
    __slots__ = ("_application",)

    def __init__(self, application: PromptApplication) -> None:
        self._application = application

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _drafts(self, drafts: tuple[CandidateOwnerDraft, ...]) -> tuple[Any, ...]:
        return tuple(
            self._application.decode(item.canonical_payload)
            for item in drafts
            if item.owner == "prompt"
        )

    async def context_sources(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> PromptContextSources:
        rows = await (
            await transaction.execute(
                """
                SELECT document.prompt_kind, document.status,
                       revision.prompt_revision_id, revision.revision_no,
                       revision.content_artifact_id
                FROM armi.prompt_documents AS document
                LEFT JOIN armi.prompt_revisions AS revision
                  ON revision.prompt_revision_id = document.current_revision_id
                 AND revision.prompt_document_id = document.prompt_document_id
                WHERE document.subject_id = %s
                ORDER BY document.prompt_kind
                """,
                (subject_id,),
            )
        ).fetchall()
        by_kind = {str(row[0]): row for row in rows}
        if set(by_kind) != {
            "personality_anchor",
            "creator_guidance",
            "subject_guidance",
        }:
            raise PromptViolation("PROMPT-CONTEXT-MISSING")
        fixed = by_kind["personality_anchor"]
        if fixed[1] != "active" or any(value is None for value in fixed[2:]):
            raise PromptViolation("PROMPT-CONTEXT-MISSING")

        def optional(kind: str) -> PromptContextSource | None:
            row = by_kind[kind]
            if kind == "creator_guidance" and row[1] == "inactive":
                return None
            if row[1] != "active":
                raise PromptViolation("PROMPT-CONTEXT-INTEGRITY")
            if all(value is None for value in row[2:]):
                return None
            if any(value is None for value in row[2:]):
                raise PromptViolation("PROMPT-CONTEXT-INTEGRITY")
            return PromptContextSource(row[2], int(row[3]), row[4])

        return PromptContextSources(
            PromptContextSource(fixed[2], int(fixed[3]), fixed[4]),
            optional("creator_guidance"),
            optional("subject_guidance"),
        )

    async def candidate_subject(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        expected_revision_id: UUID | None,
        expected_revision_no: int | None,
    ) -> SubjectPromptHead:
        row = await (
            await transaction.execute(
                """
                SELECT document.prompt_document_id,
                       document.current_revision_id,
                       COALESCE(revision.revision_no, 0)
                FROM armi.prompt_documents AS document
                LEFT JOIN armi.prompt_revisions AS revision
                  ON revision.prompt_revision_id = document.current_revision_id
                 AND revision.prompt_document_id = document.prompt_document_id
                WHERE document.subject_id = %s
                  AND document.prompt_kind = 'subject_guidance'
                  AND document.write_authority = 'subject'
                  AND document.status = 'active'
                """,
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise PromptViolation("PROMPT-CANDIDATE-CONTEXT")
        current_id = row[1]
        current_no = int(row[2])
        if current_id is None:
            if expected_revision_id is not None or expected_revision_no is not None:
                raise PromptViolation("PROMPT-CANDIDATE-CONTEXT")
        elif current_id != expected_revision_id or current_no != expected_revision_no:
            raise PromptViolation("PROMPT-CANDIDATE-CONTEXT")
        return SubjectPromptHead(row[0], current_id, current_no)

    async def recovery_state(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> PromptRecoveryState:
        row = await (
            await transaction.execute(
                """
                SELECT
                    (SELECT count(*) FROM armi.prompt_documents
                     WHERE subject_id = %s),
                    (SELECT count(*)
                     FROM armi.prompt_revisions AS revision
                     JOIN armi.prompt_documents AS document
                       ON document.prompt_document_id = revision.prompt_document_id
                     WHERE document.subject_id = %s
                       AND document.prompt_kind = 'personality_anchor'),
                    (SELECT revision.content_artifact_id
                     FROM armi.prompt_documents AS document
                     JOIN armi.prompt_revisions AS revision
                       ON revision.prompt_revision_id = document.current_revision_id
                      AND revision.prompt_document_id = document.prompt_document_id
                     WHERE document.subject_id = %s
                       AND document.prompt_kind = 'personality_anchor'
                       AND document.write_authority = 'fixed'
                       AND document.status = 'active')
                """,
                (subject_id, subject_id, subject_id),
            )
        ).fetchone()
        if row is None or row[2] is None:
            raise PromptViolation("PROMPT-RECOVERY-MISSING")
        return PromptRecoveryState(row[2], int(row[0]), int(row[1]))

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
    ) -> bool:
        selected = self._drafts(drafts)
        if len(selected) > 1:
            raise PromptViolation("PROMPT-DRAFT-COUNT")
        if not selected:
            return True
        draft = selected[0]
        row = await (
            await transaction.execute(
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
                (draft.prompt_document_id, subject_id),
            )
        ).fetchone()
        return row is not None and (row[0], int(row[1])) == (
            draft.current_revision_id,
            draft.expected_revision_no,
        )

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        validation_id: UUID,
        subject_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidateOwnerDraft, ...],
        artifacts: dict[str, ArtifactRef],
    ) -> tuple[UUID, ...]:
        selected = self._drafts(drafts)
        if len(selected) > 1:
            raise PromptViolation("PROMPT-DRAFT-COUNT")
        if not selected:
            return ()
        draft = selected[0]
        artifact = artifacts.get(draft.proposal_ref)
        if artifact is None:
            raise PromptViolation("PROMPT-ARTIFACT")
        if (
            artifact.media_type != "application/json"
            or artifact.privacy_scope.value != "private"
        ):
            raise PromptViolation("PROMPT-ARTIFACT")
        author = await (
            await transaction.execute(
                """SELECT party_id FROM armi.parties
                   WHERE party_kind = 'subject' AND represented_subject_id = %s""",
                (subject_id,),
            )
        ).fetchone()
        if author is None:
            raise PromptViolation("PROMPT-AUTHOR")
        revision_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.prompt_revisions (
                prompt_revision_id, prompt_document_id, revision_no,
                previous_revision_id, content_artifact_id, content_digest,
                author_party_id, subject_commit_id, change_reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                revision_id,
                draft.prompt_document_id,
                draft.expected_revision_no + 1,
                draft.current_revision_id,
                artifact.artifact_id.value,
                artifact.content_digest.value,
                author[0],
                commit_id,
                "subject_created"
                if draft.current_revision_id is None
                else "subject_revised",
            ),
        )
        updated = await (
            await transaction.execute(
                """
                UPDATE armi.prompt_documents SET current_revision_id = %s
                WHERE prompt_document_id = %s AND subject_id = %s
                  AND current_revision_id IS NOT DISTINCT FROM %s
                  AND status = 'active'
                RETURNING prompt_document_id
                """,
                (
                    revision_id,
                    draft.prompt_document_id,
                    subject_id,
                    draft.current_revision_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise PromptViolation("PROMPT-HEAD-STALE")
        return (draft.prompt_document_id,)

    async def initialize(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        creator_party_id: UUID,
        anchor_artifact_id: UUID,
        anchor_content_digest: Digest,
    ) -> None:
        anchor_document_id = uuid7()
        creator_document_id = uuid7()
        subject_document_id = uuid7()
        anchor_revision_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.prompt_documents (
                prompt_document_id, subject_id, prompt_kind,
                write_authority, current_revision_id
            ) VALUES
                (%s, %s, 'personality_anchor', 'fixed', %s),
                (%s, %s, 'creator_guidance', 'creator', NULL),
                (%s, %s, 'subject_guidance', 'subject', NULL)
            """,
            (
                anchor_document_id,
                subject_id,
                anchor_revision_id,
                creator_document_id,
                subject_id,
                subject_document_id,
                subject_id,
            ),
        )
        await transaction.execute(
            """
            INSERT INTO armi.prompt_revisions (
                prompt_revision_id, prompt_document_id, revision_no,
                content_artifact_id, content_digest, author_party_id, change_reason
            ) VALUES (%s, %s, 1, %s, %s, %s, 'birth')
            """,
            (
                anchor_revision_id,
                anchor_document_id,
                anchor_artifact_id,
                anchor_content_digest.value,
                creator_party_id,
            ),
        )


class PostgreSQLPromptAdmin:
    __slots__ = ()

    def references_artifact(self, transaction: Any, *, artifact_id: str) -> bool:
        row = transaction.execute(
            "SELECT EXISTS (SELECT 1 FROM armi.prompt_revisions WHERE content_artifact_id = %s)",
            (artifact_id,),
        ).fetchone()
        return row is not None and bool(row[0])


__all__ = ("PostgreSQLPromptAdmin", "PostgreSQLPromptOwner")
