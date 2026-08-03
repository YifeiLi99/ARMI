"""Fenced T-02 coordination for durable Creator input acceptance."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID, uuid7

import psycopg
import rfc8785
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
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorOperation,
    CreatorOperationQueryPort,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    LockPlan,
    LockTarget,
    OpportunityId,
    PublishedArtifact,
    RuntimeFence,
    SceneKey,
    SubjectSummary,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.creator_input import (
    CreatorInputContext,
    CreatorInputRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import OPPORTUNITY_AVAILABLE, WorkWakeupBus

_PURPOSE: Final = "creator_message"
Diagnostic = Callable[[str], None]
FaultInjector = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


class EvidenceAcceptanceTransaction(
    CreatorInputAcceptancePort,
    CreatorOperationQueryPort,
):
    """Publish exact bytes, then atomically establish all T-02 database facts."""

    __slots__ = (
        "_catalog",
        "_creator_party_id",
        "_diagnostic",
        "_fault_injector",
        "_notifier",
        "_repository",
        "_storage",
        "_uow_factory",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        creator_party_id: UUID,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogRepository,
        repository: CreatorInputRepository,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
        notifier: CreatorProjectionNotifier | None,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        if creator_party_id.version != 7:
            raise CreatorInputViolation("CON-INPUT-CREATOR")
        self._creator_party_id = creator_party_id
        self._storage = storage
        self._catalog = catalog
        self._repository = repository
        self._uow_factory = unit_of_work_factory
        self._notifier = notifier
        self._wakeups = wakeups or WorkWakeupBus()
        self._diagnostic = diagnostic or _ignore_diagnostic
        self._fault_injector = fault_injector or _ignore_diagnostic

    async def accept(self, command: CreatorInputCommand) -> CreatorInputAcceptance:
        if type(command) is not CreatorInputCommand:
            raise CreatorInputViolation("CON-INPUT-COMMAND")
        context = await self._read_context(command.scene_key)
        content_digest = Digest.from_bytes(command.message_bytes)
        request_digest = self._request_digest(context, content_digest)
        existing = await self._read_existing(command, context, request_digest)
        if existing is not None:
            return existing
        try:
            published = await self._storage.publish(
                await self._storage.stage(
                    _one_chunk(command.message_bytes),
                    ArtifactPolicy(
                        media_type="text/plain",
                        logical_kind="creator.input.text",
                        producer_kind="creator",
                        producer_trace_id=command.trace_id,
                        privacy_scope=ArtifactPrivacyScope.CREATOR_VISIBLE,
                    ),
                )
            )
        except ArtifactViolation, OSError:
            raise CreatorInputViolation("ART-INPUT-PUBLISH") from None
        if published.content_digest != content_digest:
            raise CreatorInputViolation("ART-INPUT-DIGEST")
        self._fault_injector("artifact_after_publish_before_commit")
        try:
            acceptance = await self._attempt(
                command,
                context,
                request_digest,
                published,
            )
        except DatabaseTransactionError as error:
            if error.code in {"DB-TX-UNIQUE", "DB-TX-COMMIT-UNKNOWN"}:
                recovered = await self._read_existing(
                    command,
                    context,
                    request_digest,
                )
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
            self._wakeups.notify(OPPORTUNITY_AVAILABLE)
            await self._notify(command.scene_key)
        return acceptance

    async def open(self) -> None:
        try:
            await self._uow_factory.open()
        except DatabaseTransactionError:
            raise CreatorInputViolation("DB-INPUT-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._uow_factory.close()

    async def get(self, opportunity_id: OpportunityId) -> CreatorOperation:
        if type(opportunity_id) is not OpportunityId:
            raise CreatorInputViolation("CON-INPUT-OPPORTUNITY-ID")
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(),
                read_only=True,
            ) as unit_of_work:
                return await self._repository.operation(
                    unit_of_work,
                    opportunity_id=opportunity_id,
                    creator_party_id=self._creator_party_id,
                )
        except CreatorInputViolation:
            raise
        except DatabaseTransactionError:
            raise CreatorInputViolation("DB-INPUT-UNAVAILABLE") from None

    async def get_subject_summary(self) -> SubjectSummary:
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(),
                read_only=True,
            ) as unit_of_work:
                return await self._repository.subject_summary(
                    unit_of_work,
                    creator_party_id=self._creator_party_id,
                )
        except CreatorInputViolation:
            raise
        except DatabaseTransactionError:
            raise CreatorInputViolation("DB-SUBJECT-SUMMARY") from None

    async def _attempt(
        self,
        command: CreatorInputCommand,
        expected_context: CreatorInputContext,
        request_digest: Digest,
        published: PublishedArtifact,
    ) -> CreatorInputAcceptance:
        if type(published) is not PublishedArtifact:
            raise CreatorInputViolation("ART-INPUT-PUBLISH")
        async with self._uow_factory.unit_of_work(LockPlan()) as unit_of_work:
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
                    request_digest=request_digest,
                    artifact_digest=registration.ref.content_digest,
                )
            )
            return acceptance

    async def _read_context(self, scene_key: str) -> CreatorInputContext:
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(),
                read_only=True,
            ) as unit_of_work:
                return await self._repository.context(
                    unit_of_work,
                    scene_key=scene_key,
                    creator_party_id=self._creator_party_id,
                )
        except CreatorInputViolation:
            raise
        except DatabaseTransactionError:
            raise CreatorInputViolation("DB-INPUT-UNAVAILABLE") from None

    async def _read_existing(
        self,
        command: CreatorInputCommand,
        context: CreatorInputContext,
        request_digest: Digest,
    ) -> CreatorInputAcceptance | None:
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(),
                read_only=True,
            ) as unit_of_work:
                return await self._repository.existing(
                    unit_of_work,
                    context=context,
                    idempotency_key=command.idempotency_key.value,
                    request_digest=request_digest,
                )
        except CreatorInputViolation:
            raise
        except DatabaseTransactionError:
            return None

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
        unit_of_work: PostgreSQLUnitOfWork,
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
            artifact_digest=content_digest,
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
                    projection_version="scene-timeline.v3",
                )
            )
        except Exception:
            self._diagnostic("creator.input.notification_failed")


async def _unused_lock_acquirer(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
    target: LockTarget,
) -> None:
    del connection, target
    raise CreatorInputViolation("DB-INPUT-LOCK")


def build_evidence_acceptance_transaction(
    conninfo: str,
    *,
    environment_id: UUID,
    creator_party_id: UUID,
    data_root: Path,
    max_object_bytes: int,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    notifier: CreatorProjectionNotifier | None,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
    fault_injector: FaultInjector | None = None,
) -> EvidenceAcceptanceTransaction:
    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        lock_acquirer=_unused_lock_acquirer,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return EvidenceAcceptanceTransaction(
        creator_party_id=creator_party_id,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        catalog=ArtifactCatalogRepository(),
        repository=CreatorInputRepository(),
        unit_of_work_factory=factory,
        notifier=notifier,
        wakeups=wakeups,
        diagnostic=diagnostic,
        fault_injector=fault_injector,
    )


__all__ = (
    "EvidenceAcceptanceTransaction",
    "build_evidence_acceptance_transaction",
)
