"""Local T-02 coordination for caller-declared other-human input."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.content_store import ContentAddressedArtifactStore
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
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    OtherHumanInputAcceptance,
    OtherHumanInputCommand,
    OtherHumanInputPort,
    OtherHumanInputViolation,
    OtherHumanPartyView,
    OtherHumanSceneCommand,
    OtherHumanSceneView,
    PublishedArtifact,
    RegisterOtherHumanPartyCommand,
    RuntimeFence,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId

from armi_runtime.adapters.persistence.artifact_catalog import ArtifactCatalogRepository
from armi_runtime.adapters.persistence.data_rights import DataRightsOrderRepository
from armi_runtime.adapters.persistence.other_human_input import (
    OtherHumanInputContext,
    OtherHumanInputRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import OPPORTUNITY_AVAILABLE, WorkWakeupBus


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


class OtherHumanInputService(OtherHumanInputPort):
    __slots__ = (
        "_catalog",
        "_data_rights",
        "_notifier",
        "_repository",
        "_storage",
        "_uow_factory",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogRepository,
        repository: OtherHumanInputRepository,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
        wakeups: WorkWakeupBus | None = None,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        self._storage = storage
        self._data_rights = DataRightsOrderRepository()
        self._catalog = catalog
        self._repository = repository
        self._uow_factory = unit_of_work_factory
        self._wakeups = wakeups or WorkWakeupBus()
        self._notifier = notifier

    async def open(self) -> None:
        try:
            await self._uow_factory.open()
        except DatabaseTransactionError:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._uow_factory.close()

    async def register_party(
        self, command: RegisterOtherHumanPartyCommand
    ) -> OtherHumanPartyView:
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                view = await self._repository.register_party(
                    unit_of_work,
                    party_key=command.party_key,
                    display_label=command.display_label,
                )
                await unit_of_work.audit.append(
                    AuditDraft(
                        audit_event_id=AuditEventId(uuid7()),
                        actor=AuditReference(
                            "runtime", self._uow_factory.environment_id
                        ),
                        purpose=Purpose("other_human.party"),
                        operation="other_human.party.registered",
                        target=AuditReference("other_human_party", view.party_id),
                        result_status=AuditResultStatus.APPLIED,
                        trace_id=command.trace_id,
                        sensitivity=AuditSensitivity.PRIVATE,
                    )
                )
                return view
        except OtherHumanInputViolation:
            raise
        except DatabaseTransactionError:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-UNAVAILABLE") from None

    async def set_scene(self, command: OtherHumanSceneCommand) -> OtherHumanSceneView:
        try:
            async with self._uow_factory.unit_of_work() as unit_of_work:
                view = await self._repository.set_scene(
                    unit_of_work,
                    party_key=command.party_key,
                    scene_key=command.scene_key,
                    target_status=command.target_status,
                )
                await unit_of_work.audit.append(
                    AuditDraft(
                        audit_event_id=AuditEventId(uuid7()),
                        actor=AuditReference("other_human", view.party_id),
                        purpose=Purpose("other_human.scene"),
                        operation="other_human.scene.status_set",
                        target=AuditReference("interaction_scene", view.scene_id),
                        result_status=AuditResultStatus.APPLIED,
                        trace_id=command.trace_id,
                        sensitivity=AuditSensitivity.PRIVATE,
                    )
                )
                return view
        except OtherHumanInputViolation:
            raise
        except DatabaseTransactionError:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-UNAVAILABLE") from None

    async def accept(
        self, command: OtherHumanInputCommand
    ) -> OtherHumanInputAcceptance:
        context = await self._context(command, lock=False)
        try:
            staged = await self._storage.stage(
                _one_chunk(command.message_bytes),
                ArtifactPolicy(
                    media_type="text/plain",
                    logical_kind="other_human.input.text",
                    producer_kind="other_human",
                    producer_trace_id=command.trace_id,
                    privacy_scope=ArtifactPrivacyScope.PRIVATE,
                ),
            )
        except ArtifactViolation, OSError:
            raise OtherHumanInputViolation("ART-OTHER-HUMAN-PUBLISH") from None
        content_digest = staged.content_digest
        request_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "environment_id": str(self._uow_factory.environment_id),
                    "subject_id": str(context.subject_id),
                    "party_id": str(context.party_id),
                    "scene_id": str(context.scene_id),
                    "purpose": "other_human_message",
                    "content_digest": content_digest.value,
                }
            )
        )
        try:
            existing = await self._existing(command, context, request_digest)
        except Exception:
            await self._storage.discard(staged)
            raise
        if existing is not None:
            await self._storage.discard(staged)
            return existing
        try:
            published = await self._storage.publish(staged)
        except ArtifactViolation, OSError:
            raise OtherHumanInputViolation("ART-OTHER-HUMAN-PUBLISH") from None
        try:
            acceptance = await self._commit(command, context, request_digest, published)
        except DatabaseTransactionError as error:
            if error.code in {"DB-TX-UNIQUE", "DB-TX-COMMIT-UNKNOWN"}:
                recovered = await self._existing(command, context, request_digest)
                if recovered is not None:
                    return recovered
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-UNAVAILABLE") from None
        if acceptance.newly_accepted:
            self._wakeups.notify(OPPORTUNITY_AVAILABLE)
            await self._notify(context.party_id)
        return acceptance

    async def _notify(self, party_id: UUID) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorEventResourceKind.OTHER_HUMAN_RECORD,
                    str(party_id),
                    Instant(datetime.now(UTC)),
                    "other-human-record.v1",
                )
            )
        except Exception:
            return

    async def _context(
        self, command: OtherHumanInputCommand, *, lock: bool
    ) -> OtherHumanInputContext:
        try:
            async with self._uow_factory.unit_of_work(
                read_only=not lock
            ) as unit_of_work:
                return await self._repository.context(
                    unit_of_work,
                    party_key=command.party_key,
                    scene_key=command.scene_key,
                    lock=lock,
                )
        except OtherHumanInputViolation:
            raise
        except DatabaseTransactionError:
            raise OtherHumanInputViolation("DB-OTHER-HUMAN-UNAVAILABLE") from None

    async def _existing(
        self,
        command: OtherHumanInputCommand,
        context: OtherHumanInputContext,
        request_digest: Digest,
    ) -> OtherHumanInputAcceptance | None:
        try:
            async with self._uow_factory.unit_of_work(read_only=True) as unit_of_work:
                return await self._repository.existing(
                    unit_of_work,
                    context=context,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                )
        except OtherHumanInputViolation:
            raise
        except DatabaseTransactionError:
            return None

    async def _commit(
        self,
        command: OtherHumanInputCommand,
        expected: OtherHumanInputContext,
        request_digest: Digest,
        published: PublishedArtifact,
    ) -> OtherHumanInputAcceptance:
        async with self._uow_factory.unit_of_work() as unit_of_work:
            current = await self._repository.context(
                unit_of_work,
                party_key=command.party_key,
                scene_key=command.scene_key,
                lock=True,
            )
            if current != expected:
                raise OtherHumanInputViolation("SCOPE-OTHER-HUMAN-SCENE-NOT-VISIBLE")
            existing = await self._repository.existing(
                unit_of_work,
                context=current,
                idempotency_key=command.idempotency_key.value,
                request_digest=request_digest,
            )
            if existing is not None:
                return existing
            if await self._data_rights.blocks_new_interaction(
                unit_of_work, current.party_id
            ):
                raise OtherHumanInputViolation("SCOPE-DATA-RIGHTS-BLOCKED")
            registration = await self._catalog.register(
                unit_of_work, ArtifactId(uuid7()), published
            )
            if registration.inserted:
                await unit_of_work.audit.append(
                    AuditDraft(
                        audit_event_id=AuditEventId(uuid7()),
                        actor=AuditReference(
                            "runtime", self._uow_factory.environment_id
                        ),
                        purpose=Purpose("other_human.input"),
                        operation="artifact.catalog.registered",
                        target=AuditReference(
                            "artifact", registration.ref.artifact_id.value
                        ),
                        result_status=AuditResultStatus.APPLIED,
                        trace_id=command.trace_id,
                        sensitivity=AuditSensitivity.PRIVATE,
                    )
                )
            acceptance = await self._repository.create(
                unit_of_work,
                context=current,
                idempotency_key=command.idempotency_key.value,
                request_digest=request_digest,
                content_digest=registration.ref.content_digest,
                artifact_id=registration.ref.artifact_id.value,
                trace_id=command.trace_id.value,
            )
            await unit_of_work.audit.append(
                AuditDraft(
                    audit_event_id=AuditEventId(uuid7()),
                    actor=AuditReference("other_human", current.party_id),
                    purpose=Purpose("other_human.input"),
                    operation="other_human.input.accepted",
                    target=AuditReference(
                        "opportunity", acceptance.opportunity_id.value
                    ),
                    result_status=AuditResultStatus.ACCEPTED,
                    trace_id=command.trace_id,
                    sensitivity=AuditSensitivity.PRIVATE,
                    subject_id=SubjectId(current.subject_id),
                    request=AuditReference(
                        "other_human_input", acceptance.interaction_id.value
                    ),
                )
            )
            return acceptance


def build_other_human_input_service(
    conninfo: str,
    *,
    environment_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    notifier: CreatorProjectionNotifier | None = None,
) -> OtherHumanInputService:
    return OtherHumanInputService(
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        catalog=ArtifactCatalogRepository(),
        repository=OtherHumanInputRepository(),
        unit_of_work_factory=PostgreSQLUnitOfWorkFactory(
            conninfo,
            environment_id=environment_id,
            pool_min=pool_min,
            pool_max=pool_max,
            acquire_timeout_seconds=acquire_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            authority_admission=authority_admission,
        ),
        wakeups=wakeups,
        notifier=notifier,
    )


__all__ = ("OtherHumanInputService", "build_other_human_input_service")
