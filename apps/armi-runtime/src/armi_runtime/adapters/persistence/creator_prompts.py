"""PostgreSQL ownership for Creator-maintained Prompt revisions."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    CreatorPromptViolation,
    PromptDocumentStatus,
    PromptKind,
    PromptRevisionKind,
)
from armi_kernel.contracts import Digest, Instant

from .artifact_catalog import ArtifactCatalogRepository
from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class CreatorPromptSnapshot:
    prompt_document_id: UUID
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

    def __init__(self) -> None:
        self._catalog = ArtifactCatalogRepository()

    async def get(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        creator_party_id: UUID,
        prompt_kind: PromptKind,
        for_update: bool = False,
    ) -> CreatorPromptSnapshot:
        if (
            type(unit_of_work) is not PostgreSQLUnitOfWork
            or type(creator_party_id) is not UUID
            or creator_party_id.version != 7
            or type(prompt_kind) is not PromptKind
            or type(for_update) is not bool
        ):
            raise CreatorPromptViolation("CON-PROMPT-QUERY")
        suffix = " FOR UPDATE OF document" if for_update else ""
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                f"""
                SELECT document.prompt_document_id,
                       document.subject_id,
                       document.status,
                       revision.prompt_revision_id,
                       revision.revision_no,
                       revision.previous_revision_id,
                       revision.change_reason,
                       revision.content_artifact_id,
                       revision.content_digest,
                       revision.activated_at
                FROM armi.prompt_documents AS document
                JOIN armi.subjects AS subject
                  ON subject.subject_id = document.subject_id
                 AND subject.singleton_key = 1
                 AND subject.status = 'active'
                JOIN armi.parties AS creator
                  ON creator.party_id = %s
                 AND creator.party_kind = 'creator'
                 AND creator.creator_role = 'unique_primary_creator'
                 AND creator.status = 'active'
                LEFT JOIN armi.prompt_revisions AS revision
                  ON revision.prompt_revision_id = document.current_revision_id
                 AND revision.prompt_document_id = document.prompt_document_id
                WHERE document.prompt_kind = %s
                {suffix}
                """,
                (creator_party_id, prompt_kind.value),
            )
        ).fetchone()
        if row is None:
            raise CreatorPromptViolation("SCOPE-PROMPT-NOT-WRITABLE")
        if prompt_kind is not PromptKind.CREATOR_GUIDANCE:
            raise CreatorPromptViolation("SCOPE-PROMPT-NOT-WRITABLE")
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
        except (TypeError, ValueError):
            raise CreatorPromptViolation("DB-PROMPT-INTEGRITY") from None

    async def append_revision(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        current: CreatorPromptSnapshot,
        prompt_revision_id: UUID,
        artifact: ArtifactRef,
        author_party_id: UUID,
        revision_kind: PromptRevisionKind,
    ) -> CreatorPromptSnapshot:
        if (
            type(unit_of_work) is not PostgreSQLUnitOfWork
            or type(current) is not CreatorPromptSnapshot
            or type(prompt_revision_id) is not UUID
            or prompt_revision_id.version != 7
            or type(artifact) is not ArtifactRef
            or type(author_party_id) is not UUID
            or author_party_id.version != 7
            or type(revision_kind) is not PromptRevisionKind
            or (
                revision_kind is PromptRevisionKind.CREATED
                and current.current_revision_id is not None
            )
            or (
                revision_kind is not PromptRevisionKind.CREATED
                and current.current_revision_id is None
            )
        ):
            raise CreatorPromptViolation("CON-PROMPT-COMMAND")
        next_revision = (current.revision_no or 0) + 1
        next_status = (
            PromptDocumentStatus.INACTIVE
            if revision_kind is PromptRevisionKind.DEACTIVATED
            else PromptDocumentStatus.ACTIVE
        )
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        activated = await (
            await connection.execute(
                """
                INSERT INTO armi.prompt_revisions (
                    prompt_revision_id, prompt_document_id, revision_no,
                    previous_revision_id, content_artifact_id, content_digest,
                    author_party_id, change_reason
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING activated_at
                """,
                (
                    prompt_revision_id,
                    current.prompt_document_id,
                    next_revision,
                    current.current_revision_id,
                    artifact.artifact_id.value,
                    artifact.content_digest.value,
                    author_party_id,
                    revision_kind.value,
                ),
            )
        ).fetchone()
        if activated is None:
            raise CreatorPromptViolation("DB-PROMPT-INTEGRITY")
        cursor = await connection.execute(
            """
            UPDATE armi.prompt_documents
            SET current_revision_id = %s, status = %s
            WHERE prompt_document_id = %s
              AND prompt_kind = 'creator_guidance'
              AND write_authority = 'creator'
              AND current_revision_id IS NOT DISTINCT FROM %s
            """,
            (
                prompt_revision_id,
                next_status.value,
                current.prompt_document_id,
                current.current_revision_id,
            ),
        )
        if cursor.rowcount != 1:
            raise CreatorPromptViolation("CONFLICT-PROMPT-REVISION")
        return CreatorPromptSnapshot(
            prompt_document_id=current.prompt_document_id,
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
