"""PostgreSQL ownership for Prompt documents and subject revisions."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid7

from armi_kernel.application import ArtifactRef
from armi_kernel.contracts import Digest
from armi_runtime_foundation import PostgreSQLAdminTransaction, PostgreSQLTransaction

from ._application import PromptApplication
from .api import (
    CandidatePromptDraft,
    PromptContextSource,
    PromptContextSources,
    PromptContinuityCounts,
    PromptRecoveryState,
    PromptViolation,
    SubjectPromptHead,
)


class PostgreSQLPromptOwner:
    __slots__ = ("_application",)

    def __init__(self, application: PromptApplication) -> None:
        self._application = application

    def continuity(
        self, transaction: PostgreSQLAdminTransaction, *, subject_id: UUID | None
    ) -> PromptContinuityCounts:
        if subject_id is None:
            row = transaction.execute(
                "SELECT count(DISTINCT prompt_document_id),count(*) FROM armi.prompt_revisions"
            ).fetchone()
        else:
            row = transaction.execute(
                "SELECT count(DISTINCT prompt_document_id),count(*) FROM armi.prompt_revisions "
                "WHERE subject_id=%s",
                (subject_id,),
            ).fetchone()
        if row is None:
            raise PromptViolation("PROMPT-CONTINUITY-INTEGRITY")
        return PromptContinuityCounts(int(cast(int, row[0])), int(cast(int, row[1])))

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def _drafts(
        self, drafts: tuple[CandidatePromptDraft, ...]
    ) -> tuple[CandidatePromptDraft, ...]:
        return drafts

    async def context_sources(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> PromptContextSources:
        rows = await (
            await transaction.execute(
                """
                SELECT revision.prompt_kind, revision.status,
                       revision.prompt_revision_id, revision.revision_no,
                       revision.content_artifact_id
                FROM armi.prompt_revisions AS revision
                WHERE revision.subject_id = %s AND revision.is_current
                ORDER BY revision.prompt_kind
                """,
                (subject_id,),
            )
        ).fetchall()
        by_kind = {str(row[0]): row for row in rows}
        if "personality_anchor" not in by_kind:
            raise PromptViolation("PROMPT-CONTEXT-MISSING")
        fixed = by_kind["personality_anchor"]
        if fixed[1] != "active" or any(value is None for value in fixed[2:]):
            raise PromptViolation("PROMPT-CONTEXT-MISSING")

        def optional(kind: str) -> PromptContextSource | None:
            row = by_kind.get(kind)
            if row is None or row[1] == "inactive":
                return None
            if row[1] != "active":
                raise PromptViolation("PROMPT-CONTEXT-INTEGRITY")
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
                SELECT prompt_document_id, prompt_revision_id, revision_no, status
                FROM armi.prompt_revisions
                WHERE subject_id = %s AND prompt_kind = 'subject_guidance'
                  AND is_current
                """,
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            if expected_revision_id is not None or expected_revision_no is not None:
                raise PromptViolation("PROMPT-CANDIDATE-CONTEXT")
            return SubjectPromptHead(uuid7(), None, 0)
        if row[3] != "active":
            raise PromptViolation("PROMPT-CANDIDATE-CONTEXT")
        current_id = row[1]
        current_no = int(row[2])
        if current_id != expected_revision_id or current_no != expected_revision_no:
            raise PromptViolation("PROMPT-CANDIDATE-CONTEXT")
        return SubjectPromptHead(row[0], current_id, current_no)

    async def recovery_state(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> PromptRecoveryState:
        rows = await (
            await transaction.execute(
                """
                SELECT revision.prompt_kind,revision.status,
                       revision.prompt_revision_id,
                       revision.content_artifact_id,
                       (SELECT count(*) FROM armi.prompt_revisions AS history
                        WHERE history.prompt_document_id=revision.prompt_document_id)
                FROM armi.prompt_revisions AS revision
                WHERE revision.subject_id=%s AND revision.is_current
                ORDER BY revision.prompt_kind
                """,
                (subject_id,),
            )
        ).fetchall()
        if not any(row[0] == "personality_anchor" for row in rows):
            raise PromptViolation("PROMPT-RECOVERY-MISSING")
        fixed = next(row for row in rows if row[0] == "personality_anchor")
        if fixed[1] != "active" or fixed[3] is None:
            raise PromptViolation("PROMPT-RECOVERY-MISSING")
        active_artifacts: list[UUID] = []
        for row in rows:
            if row[1] == "active":
                if row[3] is None:
                    raise PromptViolation("PROMPT-RECOVERY-MISSING")
                active_artifacts.append(row[3])
            elif row[1] != "inactive":
                raise PromptViolation("PROMPT-RECOVERY-MISSING")
        return PromptRecoveryState(
            tuple(active_artifacts),
            len(rows),
            int(fixed[4]),
        )

    async def heads_match(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        drafts: tuple[CandidatePromptDraft, ...],
    ) -> bool:
        selected = self._drafts(drafts)
        if len(selected) > 1:
            raise PromptViolation("PROMPT-DRAFT-COUNT")
        if not selected:
            return True
        draft = selected[0]
        # Also serialize the first revision, when no current row exists yet.
        await transaction.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (f"prompt:{subject_id}:subject_guidance",),
        )
        row = await (
            await transaction.execute(
                """
                SELECT prompt_revision_id,revision_no,prompt_document_id,status
                FROM armi.prompt_revisions
                WHERE subject_id = %s AND prompt_kind = 'subject_guidance'
                  AND is_current
                FOR UPDATE
                """,
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            return draft.current_revision_id is None and draft.expected_revision_no == 0
        return (
            row[2] == draft.prompt_document_id
            and row[3] == "active"
            and (row[0], int(row[1]))
            == (
                draft.current_revision_id,
                draft.expected_revision_no,
            )
        )

    async def commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        validation_id: UUID,
        subject_id: UUID,
        author_party_id: UUID,
        commit_id: UUID,
        drafts: tuple[CandidatePromptDraft, ...],
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
        if not await self.heads_match(
            transaction, subject_id=subject_id, drafts=selected
        ):
            raise PromptViolation("PROMPT-HEAD-STALE")
        await transaction.execute(
            "UPDATE armi.prompt_revisions SET is_current=false "
            "WHERE prompt_revision_id=%s AND is_current",
            (draft.current_revision_id,),
        )
        revision_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.prompt_revisions (
                prompt_revision_id, prompt_document_id, revision_no,
                previous_revision_id, content_artifact_id, content_digest,
                author_party_id, subject_commit_id, change_reason,
                subject_id, prompt_kind, is_current
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'subject_guidance', true)
            """,
            (
                revision_id,
                draft.prompt_document_id,
                draft.expected_revision_no + 1,
                draft.current_revision_id,
                artifact.artifact_id.value,
                artifact.content_digest.value,
                author_party_id,
                commit_id,
                "subject_created"
                if draft.current_revision_id is None
                else "subject_revised",
                subject_id,
            ),
        )
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
        anchor_revision_id = uuid7()
        await transaction.execute(
            """
            INSERT INTO armi.prompt_revisions (
                prompt_revision_id, prompt_document_id, revision_no,
                content_artifact_id, content_digest, author_party_id, change_reason,
                subject_id, prompt_kind, is_current
            ) VALUES (%s, %s, 1, %s, %s, %s, 'birth', %s, 'personality_anchor', true)
            """,
            (
                anchor_revision_id,
                anchor_document_id,
                anchor_artifact_id,
                anchor_content_digest.value,
                creator_party_id,
                subject_id,
            ),
        )


class PostgreSQLPromptAdmin:
    __slots__ = ()

    def references_artifact(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: str
    ) -> bool:
        row = transaction.execute(
            "SELECT EXISTS (SELECT 1 FROM armi.prompt_revisions WHERE content_artifact_id = %s)",
            (artifact_id,),
        ).fetchone()
        return row is not None and bool(row[0])


__all__ = ("PostgreSQLPromptAdmin", "PostgreSQLPromptOwner")
