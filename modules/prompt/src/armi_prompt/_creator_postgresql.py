"""PostgreSQL ownership for Creator-maintained Prompt revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import ArtifactId, ArtifactRef
from armi_kernel.contracts import Digest, Instant
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import (
    CreatorPromptViolation,
    PromptDocumentStatus,
    PromptKind,
    PromptRevisionKind,
)


@dataclass(frozen=True, slots=True)
class CreatorPromptSnapshot:
    prompt_document_id: UUID | None
    subject_id: UUID
    status: PromptDocumentStatus
    current_revision_id: UUID | None
    revision_no: int | None
    previous_revision_id: UUID | None
    revision_kind: PromptRevisionKind | None
    artifact: ArtifactRef | None
    content_digest: Digest | None
    activated_at: Instant | None


class CreatorPromptRepository:
    """Select one authority-scoped document and append immutable revisions."""

    __slots__ = ("_catalog",)

    def __init__(self, catalog: Any) -> None:
        self._catalog = catalog

    async def get(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_id: UUID,
        creator_party_id: UUID,
        prompt_kind: PromptKind,
        for_update: bool = False,
    ) -> CreatorPromptSnapshot:
        if prompt_kind is not PromptKind.CREATOR_GUIDANCE:
            raise CreatorPromptViolation("SCOPE-PROMPT-NOT-WRITABLE")
        suffix = " FOR UPDATE" if for_update else ""
        connection = unit_of_work.transaction
        if for_update:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"prompt:{subject_id}:creator_guidance",),
            )
        row = await (
            await connection.execute(
                f"""
                SELECT revision.prompt_document_id,
                       revision.subject_id,
                       revision.status,
                       revision.prompt_revision_id,
                       revision.revision_no,
                       revision.previous_revision_id,
                       revision.change_reason,
                       revision.content_artifact_id,
                       revision.content_digest,
                       revision.activated_at
                FROM armi.prompt_revisions AS revision
                WHERE revision.subject_id = %s
                  AND revision.prompt_kind = %s AND revision.is_current
                {suffix}
                """,
                (subject_id, prompt_kind.value),
            )
        ).fetchone()
        if row is None:
            return CreatorPromptSnapshot(
                None,
                subject_id,
                PromptDocumentStatus.ACTIVE,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
        if (row[3] is None) != (row[7] is None):
            raise CreatorPromptViolation("DB-PROMPT-INTEGRITY")
        artifact = (
            None
            if row[7] is None
            else await self._catalog.get(unit_of_work, ArtifactId(row[7]))
        )
        try:
            return CreatorPromptSnapshot(
                prompt_document_id=row[0],
                subject_id=row[1],
                status=PromptDocumentStatus(str(row[2])),
                current_revision_id=row[3],
                revision_no=None if row[4] is None else int(row[4]),
                previous_revision_id=row[5],
                revision_kind=(
                    None if row[6] is None else PromptRevisionKind(str(row[6]))
                ),
                artifact=artifact,
                content_digest=(None if row[8] is None else Digest(str(row[8]))),
                activated_at=(None if row[9] is None else Instant(row[9])),
            )
        except TypeError, ValueError:
            raise CreatorPromptViolation("DB-PROMPT-INTEGRITY") from None

    async def append_revision(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        current: CreatorPromptSnapshot,
        prompt_revision_id: UUID,
        artifact: ArtifactRef,
        author_party_id: UUID,
        revision_kind: PromptRevisionKind,
    ) -> CreatorPromptSnapshot:
        if (
            revision_kind is PromptRevisionKind.CREATED
            and current.current_revision_id is not None
        ) or (
            revision_kind is not PromptRevisionKind.CREATED
            and current.current_revision_id is None
        ):
            raise CreatorPromptViolation("CON-PROMPT-COMMAND")
        next_revision = (current.revision_no or 0) + 1
        next_status = (
            PromptDocumentStatus.INACTIVE
            if revision_kind is PromptRevisionKind.DEACTIVATED
            else PromptDocumentStatus.ACTIVE
        )
        connection = unit_of_work.transaction
        document_id = current.prompt_document_id or uuid7()
        if current.current_revision_id is not None:
            cursor = await connection.execute(
                "UPDATE armi.prompt_revisions SET is_current=false "
                "WHERE prompt_revision_id=%s AND is_current",
                (current.current_revision_id,),
            )
            if cursor.rowcount != 1:
                raise CreatorPromptViolation("CONFLICT-PROMPT-REVISION")
        activated = await (
            await connection.execute(
                """
                INSERT INTO armi.prompt_revisions (
                    prompt_revision_id, prompt_document_id, revision_no,
                    previous_revision_id, content_artifact_id, content_digest,
                    author_party_id, change_reason, subject_id, prompt_kind, status, is_current
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'creator_guidance', %s, true)
                RETURNING activated_at
                """,
                (
                    prompt_revision_id,
                    document_id,
                    next_revision,
                    current.current_revision_id,
                    artifact.artifact_id.value,
                    artifact.content_digest.value,
                    author_party_id,
                    revision_kind.value,
                    current.subject_id,
                    next_status.value,
                ),
            )
        ).fetchone()
        if activated is None:
            raise CreatorPromptViolation("DB-PROMPT-INTEGRITY")
        return CreatorPromptSnapshot(
            prompt_document_id=document_id,
            subject_id=current.subject_id,
            status=next_status,
            current_revision_id=prompt_revision_id,
            revision_no=next_revision,
            previous_revision_id=current.current_revision_id,
            revision_kind=revision_kind,
            artifact=artifact,
            content_digest=artifact.content_digest,
            activated_at=Instant(activated[0]),
        )


__all__ = ("CreatorPromptRepository", "CreatorPromptSnapshot")
