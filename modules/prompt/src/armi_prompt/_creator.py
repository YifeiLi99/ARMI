"""Fenced T-04 coordination for Creator-maintained Prompt revisions."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._creator_postgresql import (
    CreatorPromptRepository,
    CreatorPromptSnapshot,
)
from .api import (
    CreatorPromptDeactivateCommand,
    CreatorPromptPort,
    CreatorPromptRevisionCommand,
    CreatorPromptView,
    CreatorPromptViolation,
    PromptDocumentStatus,
    PromptKind,
    PromptRevisionKind,
)


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


class CreatorPromptService(CreatorPromptPort):
    """Publish content outside the database transaction, then CAS one Prompt head."""

    __slots__ = (
        "_catalog",
        "_creator_party_id",
        "_repository",
        "_storage",
        "_uow_factory",
    )

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        storage: Any,
        catalog: Any,
        repository: CreatorPromptRepository,
        unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
    ) -> None:
        self._creator_party_id = creator_party_id
        self._storage = storage
        self._catalog = catalog
        self._repository = repository
        self._uow_factory = unit_of_work_factory

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get(self, prompt_kind: PromptKind) -> CreatorPromptView:
        self._require_creator_guidance(prompt_kind)
        snapshot = await self._read_snapshot(prompt_kind)
        return await self._view(snapshot)

    async def revise(
        self,
        command: CreatorPromptRevisionCommand,
    ) -> CreatorPromptView:
        self._require_creator_guidance(command.prompt_kind)
        observed = await self._read_snapshot(command.prompt_kind)
        self._require_expected(observed, command.expected_revision_id)
        try:
            staged = await self._storage.stage(
                _one_chunk(command.content_bytes),
                ArtifactPolicy(
                    media_type="text/plain",
                    logical_kind="creator.prompt.text",
                    producer_kind="creator",
                    producer_trace_id=command.trace_id,
                    privacy_scope=ArtifactPrivacyScope.CREATOR_VISIBLE,
                ),
            )
        except ArtifactViolation, OSError:
            raise CreatorPromptViolation("ART-PROMPT-PUBLISH") from None
        content_digest = staged.content_digest
        if (
            observed.status is PromptDocumentStatus.ACTIVE
            and observed.content_digest == content_digest
        ):
            await self._storage.discard(staged)
            raise CreatorPromptViolation("CONFLICT-PROMPT-NO-CHANGE")
        try:
            published = await self._storage.publish(staged)
        except ArtifactViolation, OSError:
            raise CreatorPromptViolation("ART-PROMPT-PUBLISH") from None
        revision_kind = (
            PromptRevisionKind.CREATED
            if command.expected_revision_id is None
            else PromptRevisionKind.REVISED
        )
        try:
            changed = await self._apply_revision(
                command=command,
                published=published,
                revision_kind=revision_kind,
            )
        except RuntimeTransactionFailure as error:
            recovered = await self._recover_revision(
                expected_revision_id=command.expected_revision_id,
                content_digest=content_digest,
                revision_kind=revision_kind,
            )
            if recovered is not None:
                return await self._view(recovered)
            code = (
                "DB-PROMPT-COMMIT-UNKNOWN"
                if error.code == "DB-TX-COMMIT-UNKNOWN"
                else "DB-PROMPT-UNAVAILABLE"
            )
            raise CreatorPromptViolation(code) from None
        except AuditViolation:
            raise CreatorPromptViolation("DB-PROMPT-AUDIT") from None
        except ArtifactViolation:
            raise CreatorPromptViolation("ART-PROMPT-CATALOG") from None
        return self._view_with_content(changed, command.content)

    async def deactivate(
        self,
        command: CreatorPromptDeactivateCommand,
    ) -> CreatorPromptView:
        self._require_creator_guidance(command.prompt_kind)
        observed = await self._read_snapshot(command.prompt_kind)
        self._require_expected(observed, command.expected_revision_id)
        if observed.status is PromptDocumentStatus.INACTIVE:
            raise CreatorPromptViolation("CONFLICT-PROMPT-INACTIVE")
        if observed.artifact is None or observed.content_digest is None:
            raise CreatorPromptViolation("CONFLICT-PROMPT-NOT-CREATED")
        try:
            changed = await self._apply_deactivation(command)
        except RuntimeTransactionFailure as error:
            recovered = await self._recover_revision(
                expected_revision_id=command.expected_revision_id,
                content_digest=observed.content_digest,
                revision_kind=PromptRevisionKind.DEACTIVATED,
            )
            if recovered is not None:
                return await self._view(recovered)
            code = (
                "DB-PROMPT-COMMIT-UNKNOWN"
                if error.code == "DB-TX-COMMIT-UNKNOWN"
                else "DB-PROMPT-UNAVAILABLE"
            )
            raise CreatorPromptViolation(code) from None
        except AuditViolation:
            raise CreatorPromptViolation("DB-PROMPT-AUDIT") from None
        except ArtifactViolation:
            raise CreatorPromptViolation("ART-PROMPT-READ") from None
        return await self._view(changed)

    async def _apply_revision(
        self,
        *,
        command: CreatorPromptRevisionCommand,
        published: PublishedArtifact,
        revision_kind: PromptRevisionKind,
    ) -> CreatorPromptSnapshot:
        async with self._uow_factory.unit_of_work() as unit_of_work:
            current = await self._repository.get(
                unit_of_work,
                creator_party_id=self._creator_party_id,
                prompt_kind=command.prompt_kind,
                for_update=True,
            )
            self._require_expected(current, command.expected_revision_id)
            if (
                current.status is PromptDocumentStatus.ACTIVE
                and current.content_digest == published.content_digest
            ):
                raise CreatorPromptViolation("CONFLICT-PROMPT-NO-CHANGE")
            registration = await self._catalog.register(
                unit_of_work,
                ArtifactId(uuid7()),
                published,
            )
            if registration.inserted:
                await unit_of_work.audit.append(
                    self._artifact_audit(
                        unit_of_work,
                        registration.ref,
                        command.trace_id,
                    )
                )
            changed = await self._repository.append_revision(
                unit_of_work,
                current=current,
                prompt_revision_id=uuid7(),
                artifact=registration.ref,
                author_party_id=self._creator_party_id,
                revision_kind=revision_kind,
            )
            await unit_of_work.audit.append(
                self._prompt_audit(
                    current=current,
                    changed=changed,
                    trace_id=command.trace_id,
                    request_digest=self._command_digest(
                        revision_kind,
                        command.expected_revision_id,
                        registration.ref.content_digest,
                    ),
                )
            )
            return changed

    async def _apply_deactivation(
        self,
        command: CreatorPromptDeactivateCommand,
    ) -> CreatorPromptSnapshot:
        async with self._uow_factory.unit_of_work() as unit_of_work:
            current = await self._repository.get(
                unit_of_work,
                creator_party_id=self._creator_party_id,
                prompt_kind=command.prompt_kind,
                for_update=True,
            )
            self._require_expected(current, command.expected_revision_id)
            if current.status is PromptDocumentStatus.INACTIVE:
                raise CreatorPromptViolation("CONFLICT-PROMPT-INACTIVE")
            if current.artifact is None or current.content_digest is None:
                raise CreatorPromptViolation("CONFLICT-PROMPT-NOT-CREATED")
            changed = await self._repository.append_revision(
                unit_of_work,
                current=current,
                prompt_revision_id=uuid7(),
                artifact=current.artifact,
                author_party_id=self._creator_party_id,
                revision_kind=PromptRevisionKind.DEACTIVATED,
            )
            await unit_of_work.audit.append(
                self._prompt_audit(
                    current=current,
                    changed=changed,
                    trace_id=command.trace_id,
                    request_digest=self._command_digest(
                        PromptRevisionKind.DEACTIVATED,
                        command.expected_revision_id,
                        current.content_digest,
                    ),
                )
            )
            return changed

    async def _read_snapshot(self, prompt_kind: PromptKind) -> CreatorPromptSnapshot:
        try:
            async with self._uow_factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                return await self._repository.get(
                    unit_of_work,
                    creator_party_id=self._creator_party_id,
                    prompt_kind=prompt_kind,
                )
        except CreatorPromptViolation:
            raise
        except ArtifactViolation:
            raise CreatorPromptViolation("ART-PROMPT-READ") from None
        except RuntimeTransactionFailure:
            raise CreatorPromptViolation("DB-PROMPT-UNAVAILABLE") from None

    async def _recover_revision(
        self,
        *,
        expected_revision_id: UUID | None,
        content_digest: Digest,
        revision_kind: PromptRevisionKind,
    ) -> CreatorPromptSnapshot | None:
        try:
            current = await self._read_snapshot(PromptKind.CREATOR_GUIDANCE)
        except CreatorPromptViolation as error:
            if error.code == "DB-PROMPT-UNAVAILABLE":
                return None
            raise
        if (
            current.previous_revision_id == expected_revision_id
            and current.content_digest == content_digest
            and current.revision_kind is revision_kind
        ):
            return current
        return None

    async def _view(self, snapshot: CreatorPromptSnapshot) -> CreatorPromptView:
        if snapshot.artifact is None:
            return self._view_with_content(snapshot, None)
        content_bytes: bytes | None = None
        try:
            async with await self._storage.open_verified(snapshot.artifact) as stream:
                content_bytes = await stream.read()
        except ArtifactViolation, OSError:
            raise CreatorPromptViolation("ART-PROMPT-READ") from None
        if content_bytes is None:
            raise CreatorPromptViolation("ART-PROMPT-READ")
        try:
            content = content_bytes.decode("utf-8", errors="strict")
        except UnicodeError:
            raise CreatorPromptViolation("ART-PROMPT-READ") from None
        return self._view_with_content(snapshot, content)

    @staticmethod
    def _view_with_content(
        snapshot: CreatorPromptSnapshot,
        content: str | None,
    ) -> CreatorPromptView:
        return CreatorPromptView(
            prompt_document_id=snapshot.prompt_document_id,
            prompt_kind=PromptKind.CREATOR_GUIDANCE,
            status=snapshot.status,
            current_revision_id=snapshot.current_revision_id,
            revision_no=snapshot.revision_no,
            previous_revision_id=snapshot.previous_revision_id,
            revision_kind=snapshot.revision_kind,
            content=content,
            activated_at=snapshot.activated_at,
        )

    @staticmethod
    def _require_creator_guidance(prompt_kind: PromptKind) -> None:
        if prompt_kind is not PromptKind.CREATOR_GUIDANCE:
            raise CreatorPromptViolation("SCOPE-PROMPT-NOT-WRITABLE")

    @staticmethod
    def _require_expected(
        current: CreatorPromptSnapshot,
        expected_revision_id: UUID | None,
    ) -> None:
        if current.current_revision_id != expected_revision_id:
            raise CreatorPromptViolation("CONFLICT-PROMPT-REVISION")

    @staticmethod
    def _command_digest(
        revision_kind: PromptRevisionKind,
        expected_revision_id: UUID | None,
        content_digest: Digest,
    ) -> Digest:
        return Digest.from_bytes(
            rfc8785.dumps(
                {
                    "prompt_kind": PromptKind.CREATOR_GUIDANCE.value,
                    "revision_kind": revision_kind.value,
                    "expected_revision_id": (
                        None
                        if expected_revision_id is None
                        else str(expected_revision_id)
                    ),
                    "content_digest": content_digest.value,
                }
            )
        )

    def _prompt_audit(
        self,
        *,
        current: CreatorPromptSnapshot,
        changed: CreatorPromptSnapshot,
        trace_id: TraceId,
        request_digest: Digest,
    ) -> AuditDraft:
        return AuditDraft(
            audit_event_id=AuditEventId(uuid7()),
            actor=AuditReference("creator", self._creator_party_id),
            purpose=Purpose("creator.prompt.manage"),
            operation=(
                f"creator.prompt.{cast(PromptRevisionKind, changed.revision_kind).value}"
            ),
            target=AuditReference("prompt_document", changed.prompt_document_id),
            result_status=AuditResultStatus.APPLIED,
            trace_id=trace_id,
            sensitivity=AuditSensitivity.RESTRICTED,
            subject_id=SubjectId(changed.subject_id),
            before_version=current.revision_no or 0,
            after_version=cast(int, changed.revision_no),
        )

    @staticmethod
    def _artifact_audit(
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact: ArtifactRef,
        trace_id: TraceId,
    ) -> AuditDraft:
        return AuditDraft(
            audit_event_id=AuditEventId(uuid7()),
            actor=AuditReference("runtime", unit_of_work.environment_id),
            purpose=Purpose("creator.prompt.manage"),
            operation="artifact.catalog.registered",
            target=AuditReference("artifact", artifact.artifact_id.value),
            result_status=AuditResultStatus.APPLIED,
            trace_id=trace_id,
            sensitivity=AuditSensitivity.RESTRICTED,
        )


__all__ = ("CreatorPromptService",)
