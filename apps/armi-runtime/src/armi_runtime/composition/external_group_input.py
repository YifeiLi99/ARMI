"""Channel-neutral coordination for observed external group messages."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
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
    CreatorEventResourceKind,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    EnsureExternalGroupCommand,
    ExternalGroupInputAcceptance,
    ExternalGroupInputPort,
    ExternalGroupView,
    ExternalGroupViolation,
    LockPlan,
    LockTarget,
    ObservedExternalGroupMessage,
    OtherHumanInputAcceptance,
    PublishedArtifact,
    RuntimeFence,
    SceneKey,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, Purpose, SubjectId

from armi_runtime.adapters.artifacts.content_store import ContentAddressedArtifactStore
from armi_runtime.adapters.persistence.artifact_catalog import ArtifactCatalogRepository
from armi_runtime.adapters.persistence.data_rights import DataRightsOrderRepository
from armi_runtime.adapters.persistence.external_group_input import (
    ExternalGroupInputContext,
    ExternalGroupInputRepository,
)
from armi_runtime.adapters.persistence.other_human_input import (
    OtherHumanInputRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import OPPORTUNITY_AVAILABLE, WorkWakeupBus


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


class ExternalGroupInputService(ExternalGroupInputPort):
    __slots__ = (
        "_catalog",
        "_data_rights",
        "_factory",
        "_groups",
        "_inputs",
        "_notifier",
        "_storage",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogRepository,
        groups: ExternalGroupInputRepository,
        inputs: OtherHumanInputRepository,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
        wakeups: WorkWakeupBus | None = None,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        self._storage = storage
        self._catalog = catalog
        self._groups = groups
        self._inputs = inputs
        self._data_rights = DataRightsOrderRepository()
        self._factory = unit_of_work_factory
        self._wakeups = wakeups or WorkWakeupBus()
        self._notifier = notifier

    async def open(self) -> None:
        try:
            await self._factory.open()
        except DatabaseTransactionError:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-UNAVAILABLE") from None

    async def close(self) -> None:
        await self._factory.close()

    async def ensure_group(
        self, command: EnsureExternalGroupCommand
    ) -> ExternalGroupView:
        if type(command) is not EnsureExternalGroupCommand:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-ENSURE")
        identity = _identity(
            command.channel.value,
            command.account_key.value,
            "group",
            command.conversation_key.value,
        )
        scene_key = SceneKey(f"group-{identity.removeprefix('external-group:')[:32]}")
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                view = await self._groups.ensure_group(
                    unit_of_work,
                    channel=command.channel,
                    account_key=command.account_key,
                    conversation_key=command.conversation_key,
                    display_label=command.display_label,
                    identity_key=identity,
                    scene_key=scene_key,
                )
                await unit_of_work.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference("runtime", self._factory.environment_id),
                        Purpose("external_group.binding"),
                        "external_group.binding.ensured",
                        AuditReference("external_channel_binding", view.binding_id),
                        AuditResultStatus.APPLIED,
                        command.trace_id,
                        AuditSensitivity.PRIVATE,
                    )
                )
                return view
        except ExternalGroupViolation:
            raise
        except DatabaseTransactionError:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-UNAVAILABLE") from None

    async def accept(
        self, command: ObservedExternalGroupMessage
    ) -> ExternalGroupInputAcceptance:
        if type(command) is not ObservedExternalGroupMessage:
            raise ExternalGroupViolation("CON-EXTERNAL-GROUP-INPUT")
        context = await self._bind(command)
        content_digest = Digest.from_bytes(command.message_bytes)
        request_digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "schema_version": "armi.external-group-input.v1",
                    "environment_id": str(self._factory.environment_id),
                    "subject_id": str(context.input.subject_id),
                    "scene_id": str(context.input.scene_id),
                    "sender_party_id": str(context.input.party_id),
                    "binding_id": str(context.binding_id),
                    "channel": command.channel.value,
                    "account_key": command.account_key.value,
                    "conversation_key": command.conversation_key.value,
                    "message_key": command.message_key.value,
                    "observed_at": command.observed_at.to_wire(),
                    "addressed_to_subject": command.addressed_to_subject,
                    "content_digest": content_digest.value,
                }
            )
        )
        idempotency_key = _idempotency_key(command)
        existing = await self._existing(context, idempotency_key, request_digest)
        if existing is not None:
            return existing
        try:
            published = await self._storage.publish(
                await self._storage.stage(
                    _one_chunk(command.message_bytes),
                    ArtifactPolicy(
                        "text/plain",
                        "other_human.input.text",
                        "external.channel",
                        command.trace_id,
                        ArtifactPrivacyScope.PRIVATE,
                    ),
                )
            )
        except ArtifactViolation, OSError:
            raise ExternalGroupViolation("ART-EXTERNAL-GROUP-PUBLISH") from None
        if published.content_digest != content_digest:
            raise ExternalGroupViolation("ART-EXTERNAL-GROUP-DIGEST")
        try:
            acceptance = await self._commit(
                command,
                context,
                idempotency_key,
                request_digest,
                published,
            )
        except DatabaseTransactionError as error:
            if error.code in {"DB-TX-UNIQUE", "DB-TX-COMMIT-UNKNOWN"}:
                recovered = await self._existing(
                    context, idempotency_key, request_digest
                )
                if recovered is not None:
                    return recovered
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-UNAVAILABLE") from None
        if acceptance.newly_accepted:
            self._wakeups.notify(OPPORTUNITY_AVAILABLE)
            await self._notify(acceptance.sender_party_id)
        return acceptance

    async def _bind(
        self, command: ObservedExternalGroupMessage
    ) -> ExternalGroupInputContext:
        identity = _identity(
            command.channel.value,
            command.account_key.value,
            "person",
            command.sender_key.value,
        )
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._groups.bind_sender(
                    unit_of_work,
                    channel=command.channel,
                    account_key=command.account_key,
                    conversation_key=command.conversation_key,
                    sender_key=command.sender_key,
                    sender_display_label=command.sender_display_label,
                    identity_key=identity,
                )
        except ExternalGroupViolation:
            raise
        except DatabaseTransactionError:
            raise ExternalGroupViolation("DB-EXTERNAL-GROUP-UNAVAILABLE") from None

    async def _existing(
        self,
        context: ExternalGroupInputContext,
        idempotency_key: IdempotencyKey,
        request_digest: Digest,
    ) -> ExternalGroupInputAcceptance | None:
        try:
            async with self._factory.unit_of_work(
                LockPlan(), read_only=True
            ) as unit_of_work:
                existing = await self._inputs.existing(
                    unit_of_work,
                    context=context.input,
                    idempotency_key=idempotency_key.value,
                    request_digest=request_digest,
                )
        except DatabaseTransactionError:
            return None
        return None if existing is None else _acceptance(context.binding_id, existing)

    async def _commit(
        self,
        command: ObservedExternalGroupMessage,
        expected: ExternalGroupInputContext,
        idempotency_key: IdempotencyKey,
        request_digest: Digest,
        published: PublishedArtifact,
    ) -> ExternalGroupInputAcceptance:
        async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
            current = await self._groups.bind_sender(
                unit_of_work,
                channel=command.channel,
                account_key=command.account_key,
                conversation_key=command.conversation_key,
                sender_key=command.sender_key,
                sender_display_label=command.sender_display_label,
                identity_key=_identity(
                    command.channel.value,
                    command.account_key.value,
                    "person",
                    command.sender_key.value,
                ),
            )
            if current != expected:
                raise ExternalGroupViolation("SCOPE-EXTERNAL-GROUP-NOT-ALLOWED")
            existing = await self._inputs.existing(
                unit_of_work,
                context=current.input,
                idempotency_key=idempotency_key.value,
                request_digest=request_digest,
            )
            if existing is not None:
                return _acceptance(current.binding_id, existing)
            if await self._data_rights.blocks_new_interaction(
                unit_of_work, current.input.party_id
            ):
                raise ExternalGroupViolation("SCOPE-EXTERNAL-GROUP-DATA-RIGHTS")
            registration = await self._catalog.register(
                unit_of_work, ArtifactId(uuid7()), published
            )
            accepted = await self._inputs.create(
                unit_of_work,
                context=current.input,
                idempotency_key=idempotency_key.value,
                request_digest=request_digest,
                content_digest=registration.ref.content_digest,
                artifact_id=registration.ref.artifact_id.value,
                trace_id=command.trace_id.value,
                external_binding_id=current.binding_id,
                external_message_key=command.message_key.value,
                addressed_to_subject=command.addressed_to_subject,
            )
            await unit_of_work.audit.append(
                AuditDraft(
                    AuditEventId(uuid7()),
                    AuditReference("other_human", current.input.party_id),
                    Purpose("external_group.input"),
                    "external_group.input.accepted",
                    AuditReference("opportunity", accepted.opportunity_id.value),
                    AuditResultStatus.ACCEPTED,
                    command.trace_id,
                    AuditSensitivity.PRIVATE,
                    subject_id=SubjectId(current.input.subject_id),
                    request=AuditReference(
                        "external_group_input", accepted.interaction_id.value
                    ),
                    request_digest=request_digest,
                    artifact_digest=registration.ref.content_digest,
                )
            )
            return _acceptance(current.binding_id, accepted)

    async def _notify(self, party_id: UUID) -> None:
        if self._notifier is None:
            return
        try:
            from datetime import UTC, datetime

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


def _identity(channel: str, account: str, kind: str, external_key: str) -> str:
    digest = Digest.from_bytes(
        rfc8785.dumps(
            {
                "channel": channel,
                "account": account,
                "kind": kind,
                "external_key": external_key,
            }
        )
    ).value.removeprefix("sha256:")
    return f"external-{kind}:{digest}"


def _idempotency_key(command: ObservedExternalGroupMessage) -> IdempotencyKey:
    digest = Digest.from_bytes(
        rfc8785.dumps(
            {
                "channel": command.channel.value,
                "account": command.account_key.value,
                "conversation": command.conversation_key.value,
                "message": command.message_key.value,
            }
        )
    ).value.removeprefix("sha256:")
    return IdempotencyKey(f"external:{digest}")


def _acceptance(
    binding_id: UUID, value: OtherHumanInputAcceptance
) -> ExternalGroupInputAcceptance:
    return ExternalGroupInputAcceptance(
        binding_id,
        value.party_id,
        value.scene_id,
        value.interaction_id,
        value.evidence_id,
        value.opportunity_id,
        value.request_digest,
        value.content_digest,
        value.newly_accepted,
    )


async def _unused_lock_acquirer(
    connection: psycopg.AsyncConnection[tuple[Any, ...]], target: LockTarget
) -> None:
    del connection, target
    raise ExternalGroupViolation("DB-EXTERNAL-GROUP-LOCK")


def build_external_group_input_service(
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
) -> ExternalGroupInputService:
    return ExternalGroupInputService(
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts", max_object_bytes=max_object_bytes
        ),
        catalog=ArtifactCatalogRepository(),
        groups=ExternalGroupInputRepository(),
        inputs=OtherHumanInputRepository(),
        unit_of_work_factory=PostgreSQLUnitOfWorkFactory(
            conninfo,
            environment_id=environment_id,
            lock_acquirer=_unused_lock_acquirer,
            pool_min=pool_min,
            pool_max=pool_max,
            acquire_timeout_seconds=acquire_timeout_seconds,
            statement_timeout_seconds=statement_timeout_seconds,
            authority_admission=authority_admission,
        ),
        wakeups=wakeups,
        notifier=notifier,
    )


__all__ = ("ExternalGroupInputService", "build_external_group_input_service")
