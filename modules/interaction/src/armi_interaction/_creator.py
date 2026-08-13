"""Fenced T-02 coordination for durable Creator input acceptance."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Final
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    AuditViolation,
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)
from armi_subject_state.api import (
    SubjectStateReadPort,
    SubjectStateViolation,
    SubjectSummary,
)

from ._creator_contract import (
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
)
from ._creator_postgresql import (
    CreatorInputContext,
    CreatorInputRepository,
)
from ._dependencies import NullInteractionWakeup
from ._scene_contract import SceneKey
from .api import (
    InteractionArtifactCatalogPort,
    InteractionDataRightsGate,
    InteractionWakeupPort,
)

_PURPOSE: Final = "creator_message"
_OPPORTUNITY_AVAILABLE: Final = "opportunity.available"
Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


class EvidenceAcceptanceTransaction(CreatorInputAcceptancePort):
    """Publish exact bytes, then atomically establish all T-02 database facts."""

    __slots__ = (
        "_catalog",
        "_creator_party_id",
        "_data_rights",
        "_diagnostic",
        "_fault_injector",
        "_notifier",
        "_repository",
        "_storage",
        "_subject_state",
        "_uow_factory",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        storage: ContentAddressedArtifactStore,
        catalog: InteractionArtifactCatalogPort,
        repository: CreatorInputRepository,
        unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
        data_rights: InteractionDataRightsGate,
        notifier: CreatorProjectionNotifier | None,
        subject_state: SubjectStateReadPort,
        wakeups: InteractionWakeupPort | None = None,
        diagnostic: Diagnostic | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        if creator_party_id.version != 7:
            raise CreatorInputViolation("CON-INPUT-CREATOR")
        self._creator_party_id = creator_party_id
        self._data_rights = data_rights
        self._storage = storage
        self._catalog = catalog
        self._repository = repository
        self._uow_factory = unit_of_work_factory
        self._notifier = notifier
        self._subject_state = subject_state
        self._wakeups = wakeups or NullInteractionWakeup()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._fault_injector = fault_injector or _ignore_diagnostic

    async def accept(self, command: CreatorInputCommand) -> CreatorInputAcceptance:
        context = await self._read_context(command.scene_key)
        try:
            staged = await self._storage.stage(
                _one_chunk(command.message_bytes),
                ArtifactPolicy(
                    media_type="text/plain",
                    logical_kind="creator.input.text",
                    producer_kind="creator",
                    producer_trace_id=command.trace_id,
                    privacy_scope=ArtifactPrivacyScope.CREATOR_VISIBLE,
                ),
            )
        except ArtifactViolation, OSError:
            raise CreatorInputViolation("ART-INPUT-PUBLISH") from None
        content_digest = staged.content_digest
        request_digest = self._request_digest(context, content_digest)
        try:
            existing = await self._read_existing(command, context, request_digest)
        except RuntimeTransactionFailure:
            await self._storage.discard(staged)
            raise CreatorInputViolation("DB-INPUT-UNAVAILABLE") from None
        except Exception:
            await self._storage.discard(staged)
            raise
        if existing is not None:
            await self._storage.discard(staged)
            return existing
        try:
            published = await self._storage.publish(staged)
        except ArtifactViolation, OSError:
            raise CreatorInputViolation("ART-INPUT-PUBLISH") from None
        self._fault_injector("artifact_after_publish_before_commit")
        try:
            acceptance = await self._attempt(
                command,
                context,
                request_digest,
                published,
            )
        except RuntimeTransactionFailure as error:
            if error.code in {"DB-TX-UNIQUE", "DB-TX-COMMIT-UNKNOWN"}:
                try:
                    recovered = await self._read_existing(
                        command,
                        context,
                        request_digest,
                    )
                except RuntimeTransactionFailure:
                    code = (
                        "DB-INPUT-COMMIT-UNKNOWN"
                        if error.code == "DB-TX-COMMIT-UNKNOWN"
                        else "DB-INPUT-UNAVAILABLE"
                    )
                    raise CreatorInputViolation(code) from None
                if recovered is not None:
                    return recovered
                code = (
                    "DB-INPUT-COMMIT-UNKNOWN"
                    if error.code == "DB-TX-COMMIT-UNKNOWN"
                    else "DB-INPUT-CONFLICT"
                )
                raise CreatorInputViolation(code) from None
            raise CreatorInputViolation("DB-INPUT-UNAVAILABLE") from None
        except AuditViolation:
            raise CreatorInputViolation("DB-INPUT-AUDIT") from None
        except ArtifactViolation:
            raise CreatorInputViolation("ART-INPUT-CATALOG") from None
        if acceptance.newly_accepted:
            self._wakeups.notify(_OPPORTUNITY_AVAILABLE)
            await self._notify(command.scene_key)
        return acceptance

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def get_subject_summary(self) -> SubjectSummary:
        try:
            async with self._uow_factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                return await self._subject_state.creator_summary(
                    unit_of_work.transaction,
                    creator_party_id=self._creator_party_id,
                )
        except CreatorInputViolation, SubjectStateViolation:
            raise
        except RuntimeTransactionFailure:
            raise CreatorInputViolation("DB-SUBJECT-SUMMARY") from None

    async def _attempt(
        self,
        command: CreatorInputCommand,
        expected_context: CreatorInputContext,
        request_digest: Digest,
        published: PublishedArtifact,
    ) -> CreatorInputAcceptance:
        async with self._uow_factory.unit_of_work() as unit_of_work:
            await self._repository.lock_scene(
                unit_of_work,
                scene_id=expected_context.scene_id,
            )
            context = await self._repository.context(
                unit_of_work,
                scene_key=command.scene_key,
                creator_party_id=self._creator_party_id,
            )
            if context != expected_context:
                raise CreatorInputViolation("SCOPE-SCENE-NOT-VISIBLE")
            existing = await self._repository.existing(
                unit_of_work,
                context=context,
                idempotency_key=command.idempotency_key.value,
                request_digest=request_digest,
            )
            if existing is not None:
                return existing
            if await self._data_rights.blocks_new_interaction(
                unit_of_work, self._creator_party_id
            ):
                raise CreatorInputViolation("SCOPE-DATA-RIGHTS-BLOCKED")
            registration = await self._catalog.register(
                unit_of_work,
                ArtifactId(uuid7()),
                published,
            )
            if registration.inserted:
                await unit_of_work.audit.append(
                    self._artifact_audit(
                        unit_of_work,
                        registration.ref.artifact_id.value,
                        registration.ref.content_digest,
                        command,
                    )
                )
            acceptance = await self._repository.create(
                unit_of_work,
                context=context,
                idempotency_key=command.idempotency_key.value,
                request_digest=request_digest,
                content_digest=registration.ref.content_digest,
                artifact_id=registration.ref.artifact_id.value,
                trace_id=command.trace_id.value,
            )
            await unit_of_work.audit.append(
                AuditDraft(
                    audit_event_id=AuditEventId(uuid7()),
                    actor=AuditReference("creator", context.creator_party_id),
                    purpose=Purpose("creator.input"),
                    operation="creator.input.accepted",
                    target=AuditReference(
                        "opportunity",
                        acceptance.opportunity_id.value,
                    ),
                    result_status=AuditResultStatus.ACCEPTED,
                    trace_id=command.trace_id,
                    sensitivity=AuditSensitivity.PRIVATE,
                    subject_id=SubjectId(context.subject_id),
                    request=AuditReference(
                        "creator_input",
                        acceptance.interaction_id.value,
                    ),
                )
            )
            return acceptance

    async def _read_context(self, scene_key: str) -> CreatorInputContext:
        try:
            async with self._uow_factory.unit_of_work(
                read_only=True,
            ) as unit_of_work:
                return await self._repository.context(
                    unit_of_work,
                    scene_key=scene_key,
                    creator_party_id=self._creator_party_id,
                )
        except CreatorInputViolation:
            raise
        except RuntimeTransactionFailure:
            raise CreatorInputViolation("DB-INPUT-UNAVAILABLE") from None

    async def _read_existing(
        self,
        command: CreatorInputCommand,
        context: CreatorInputContext,
        request_digest: Digest,
    ) -> CreatorInputAcceptance | None:
        async with self._uow_factory.unit_of_work(
            read_only=True,
        ) as unit_of_work:
            return await self._repository.existing(
                unit_of_work,
                context=context,
                idempotency_key=command.idempotency_key.value,
                request_digest=request_digest,
            )

    def _request_digest(
        self,
        context: CreatorInputContext,
        content_digest: Digest,
    ) -> Digest:
        return Digest.from_bytes(
            rfc8785.dumps(
                {
                    "environment_id": str(self._uow_factory.environment_id),
                    "subject_id": str(context.subject_id),
                    "creator_party_id": str(context.creator_party_id),
                    "scene_id": str(context.scene_id),
                    "purpose": _PURPOSE,
                    "content_digest": content_digest.value,
                }
            )
        )

    def _artifact_audit(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        artifact_id: UUID,
        content_digest: Digest,
        command: CreatorInputCommand,
    ) -> AuditDraft:
        return AuditDraft(
            audit_event_id=AuditEventId(uuid7()),
            actor=AuditReference("runtime", unit_of_work.environment_id),
            purpose=Purpose("creator.input"),
            operation="artifact.catalog.registered",
            target=AuditReference("artifact", artifact_id),
            result_status=AuditResultStatus.APPLIED,
            trace_id=command.trace_id,
            sensitivity=AuditSensitivity.PRIVATE,
        )

    async def _notify(self, scene_key: str) -> None:
        if self._notifier is None:
            self._diagnostic("creator.input.notification_unavailable")
            return
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    resource_kind=CreatorEventResourceKind.SCENE_TIMELINE,
                    resource_ref=SceneKey(scene_key).value,
                    occurred_at=Instant(datetime.now(UTC)),
                    projection_version="scene-timeline.v5",
                )
            )
        except Exception:
            self._diagnostic("creator.input.notification_failed")


__all__ = ("EvidenceAcceptanceTransaction",)
