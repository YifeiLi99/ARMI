"""Channel-neutral coordination for observed external conversations."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    CreatorResourceKind,
    PublishedArtifact,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, Purpose, SubjectId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)

from ._creator_contract import CreatorInputAcceptance
from ._creator_postgresql import CreatorInputRepository
from ._dependencies import NullInteractionWakeup
from ._external_contract import (
    ConfigureExternalCreatorCommand,
    ExternalCreatorBinding,
    ExternalMessageInputAcceptance,
    ExternalMessageInputPort,
    ExternalMessageInteractionId,
    ExternalMessageViolation,
    ObservedExternalMessage,
)
from ._external_postgresql import (
    ExternalMessageInputContext,
    ExternalMessageInputRepository,
)
from ._other_human_contract import OtherHumanInputAcceptance
from ._other_human_postgresql import (
    OtherHumanInputRepository,
)
from .api import (
    InteractionArtifactCatalogPort,
    InteractionDataRightsGate,
    InteractionWakeupPort,
)

_EXTERNAL_CONTENT = "external.content"
_OPPORTUNITY_AVAILABLE = "opportunity.available"


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


class ExternalMessageInputService(ExternalMessageInputPort):
    __slots__ = (
        "_catalog",
        "_creator_inputs",
        "_data_rights",
        "_factory",
        "_messages",
        "_notifier",
        "_other_inputs",
        "_storage",
        "_subject_id",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        storage: ContentAddressedArtifactStore,
        catalog: InteractionArtifactCatalogPort,
        messages: ExternalMessageInputRepository,
        creator_inputs: CreatorInputRepository,
        other_inputs: OtherHumanInputRepository,
        unit_of_work_factory: PostgreSQLRuntimeUnitOfWorkFactory,
        data_rights: InteractionDataRightsGate,
        subject_id: UUID,
        wakeups: InteractionWakeupPort | None = None,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        self._storage = storage
        self._catalog = catalog
        self._messages = messages
        self._creator_inputs = creator_inputs
        self._other_inputs = other_inputs
        self._data_rights = data_rights
        self._subject_id = subject_id
        self._factory = unit_of_work_factory
        self._wakeups = wakeups or NullInteractionWakeup()
        self._notifier = notifier

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def configure_creator(
        self, command: ConfigureExternalCreatorCommand
    ) -> ExternalCreatorBinding:
        scene_key = _scene_key(
            command.channel.value,
            command.account_key.value,
            "direct",
            command.creator_key.value,
        )
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                binding = await self._messages.configure_creator(
                    unit_of_work,
                    subject_id=self._subject_id,
                    command=command,
                    scene_key=scene_key,
                )
                await unit_of_work.audit.append(
                    AuditDraft(
                        AuditEventId(uuid7()),
                        AuditReference("runtime", self._factory.environment_id),
                        Purpose("external_message.creator_binding"),
                        "external_message.creator_binding.configured",
                        AuditReference("external_channel_binding", binding.binding_id),
                        AuditResultStatus.APPLIED,
                        command.trace_id,
                        AuditSensitivity.PRIVATE,
                    )
                )
                return binding
        except ExternalMessageViolation:
            raise
        except RuntimeTransactionFailure:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-UNAVAILABLE") from None

    async def accept(
        self, command: ObservedExternalMessage
    ) -> ExternalMessageInputAcceptance:
        context = await self._bind(command)
        try:
            staged = await self._storage.stage(
                _one_chunk(command.message_bytes),
                ArtifactPolicy(
                    "text/plain",
                    (
                        "creator.input.text"
                        if context.sender_party_kind == "creator"
                        else "other_human.input.text"
                    ),
                    "external.channel",
                    command.trace_id,
                    (
                        ArtifactPrivacyScope.CREATOR_VISIBLE
                        if context.sender_party_kind == "creator"
                        else ArtifactPrivacyScope.PRIVATE
                    ),
                ),
            )
        except ArtifactViolation, OSError:
            raise ExternalMessageViolation("ART-EXTERNAL-MESSAGE-PUBLISH") from None
        request_digest = _request_digest(
            self._factory.environment_id, command, context, staged.content_digest
        )
        idempotency_key = _idempotency_key(command)
        try:
            existing = await self._existing(context, idempotency_key, request_digest)
        except Exception:
            await self._storage.discard(staged)
            raise
        if existing is not None:
            await self._storage.discard(staged)
            return existing
        deferred = _deferred_recognition(command)
        published = None
        if deferred is None:
            try:
                published = await self._storage.publish(staged)
            except ArtifactViolation, OSError:
                raise ExternalMessageViolation("ART-EXTERNAL-MESSAGE-PUBLISH") from None
        else:
            await self._storage.discard(staged)
        try:
            accepted = await self._commit(
                command,
                context,
                idempotency_key,
                request_digest,
                staged.content_digest,
                published,
                deferred,
            )
        except RuntimeTransactionFailure as error:
            if error.code in {"DB-TX-UNIQUE", "DB-TX-COMMIT-UNKNOWN"}:
                recovered = await self._existing(
                    context, idempotency_key, request_digest
                )
                if recovered is not None:
                    return recovered
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-UNAVAILABLE") from None
        if accepted.newly_accepted:
            self._wakeups.notify(
                _EXTERNAL_CONTENT
                if accepted.opportunity_id is None and command.has_media
                else _OPPORTUNITY_AVAILABLE
            )
            await self._notify(command, context)
        return accepted

    async def _notify(
        self,
        command: ObservedExternalMessage,
        context: ExternalMessageInputContext,
    ) -> None:
        if self._notifier is None:
            return
        if context.sender_party_kind == "creator":
            kind = CreatorResourceKind("scene_timeline")
            resource_ref = _scene_key(
                command.channel.value,
                command.account_key.value,
                command.conversation_kind.value,
                command.conversation_key.value,
            )
            projection = "scene-timeline.v5"
        else:
            kind = CreatorResourceKind("other_human_record")
            resource_ref = str(context.sender_party_id)
            projection = "other-human-record.v1"
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    kind,
                    resource_ref,
                    Instant(datetime.now(UTC)),
                    projection,
                )
            )
        except Exception:
            return

    async def _bind(
        self, command: ObservedExternalMessage
    ) -> ExternalMessageInputContext:
        person_identity = _identity(
            command.channel.value,
            command.account_key.value,
            "person",
            command.sender_key.value,
        )
        conversation_identity = _identity(
            command.channel.value,
            command.account_key.value,
            command.conversation_kind.value,
            command.conversation_key.value,
        )
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._messages.bind_message(
                    unit_of_work,
                    subject_id=self._subject_id,
                    command=command,
                    person_identity_key=person_identity,
                    conversation_identity_key=conversation_identity,
                    scene_key=_scene_key(
                        command.channel.value,
                        command.account_key.value,
                        command.conversation_kind.value,
                        command.conversation_key.value,
                    ),
                )
        except ExternalMessageViolation:
            raise
        except RuntimeTransactionFailure:
            raise ExternalMessageViolation("DB-EXTERNAL-MESSAGE-UNAVAILABLE") from None

    async def _existing(
        self,
        context: ExternalMessageInputContext,
        idempotency_key: IdempotencyKey,
        request_digest: Digest,
    ) -> ExternalMessageInputAcceptance | None:
        async with self._factory.unit_of_work(read_only=True) as unit_of_work:
            return await self._messages.existing_external(
                unit_of_work,
                context=context,
                idempotency_key=idempotency_key.value,
                request_digest=request_digest,
            )

    async def _commit(
        self,
        command: ObservedExternalMessage,
        expected: ExternalMessageInputContext,
        idempotency_key: IdempotencyKey,
        request_digest: Digest,
        content_digest: Digest,
        published: PublishedArtifact | None,
        deferred: str | None,
    ) -> ExternalMessageInputAcceptance:
        async with self._factory.unit_of_work() as unit_of_work:
            current = await self._messages.bind_message(
                unit_of_work,
                subject_id=self._subject_id,
                command=command,
                person_identity_key=_identity(
                    command.channel.value,
                    command.account_key.value,
                    "person",
                    command.sender_key.value,
                ),
                conversation_identity_key=_identity(
                    command.channel.value,
                    command.account_key.value,
                    command.conversation_kind.value,
                    command.conversation_key.value,
                ),
                scene_key=_scene_key(
                    command.channel.value,
                    command.account_key.value,
                    command.conversation_kind.value,
                    command.conversation_key.value,
                ),
            )
            if current != expected:
                raise ExternalMessageViolation("SCOPE-EXTERNAL-MESSAGE-NOT-ALLOWED")
            existing = await self._existing_in_unit(
                unit_of_work, current, idempotency_key, request_digest
            )
            if existing is not None:
                return existing
            if (
                current.sender_party_kind == "other_human"
                and await self._data_rights.blocks_new_interaction(
                    unit_of_work, current.sender_party_id
                )
            ):
                raise ExternalMessageViolation("SCOPE-EXTERNAL-MESSAGE-DATA-RIGHTS")
            if deferred is not None:
                acceptance = await self._messages.create_deferred(
                    unit_of_work,
                    context=current,
                    command=command,
                    idempotency_key=idempotency_key,
                    request_digest=request_digest,
                    content_digest=content_digest,
                    recognition_status=deferred,
                )
            else:
                assert published is not None
                registration = await self._catalog.register(
                    unit_of_work, ArtifactId(uuid7()), published
                )
                if current.creator_input is not None:
                    value = await self._creator_inputs.create(
                        unit_of_work,
                        context=current.creator_input,
                        idempotency_key=idempotency_key.value,
                        request_digest=request_digest,
                        content_digest=registration.ref.content_digest,
                        artifact_id=registration.ref.artifact_id.value,
                        trace_id=command.trace_id.value,
                        external_binding_id=current.conversation_binding_id,
                        external_message_key=command.message_key.value,
                        addressed_to_subject=command.addressed_to_subject,
                    )
                else:
                    assert current.other_input is not None
                    value = await self._other_inputs.create(
                        unit_of_work,
                        context=current.other_input,
                        idempotency_key=idempotency_key.value,
                        request_digest=request_digest,
                        content_digest=registration.ref.content_digest,
                        artifact_id=registration.ref.artifact_id.value,
                        trace_id=command.trace_id.value,
                        external_binding_id=current.conversation_binding_id,
                        external_message_key=command.message_key.value,
                        addressed_to_subject=command.addressed_to_subject,
                    )
                await self._messages.add_parts(
                    unit_of_work,
                    interaction_id=value.interaction_id.value,
                    command=command,
                    media_status="skipped" if command.has_media else "not_required",
                )
                acceptance = _acceptance(current, value)
            await unit_of_work.audit.append(
                AuditDraft(
                    AuditEventId(uuid7()),
                    AuditReference(current.sender_party_kind, current.sender_party_id),
                    Purpose("external_message.input"),
                    "external_message.input.accepted",
                    AuditReference(
                        "opportunity"
                        if acceptance.opportunity_id is not None
                        else "external_message_input",
                        acceptance.opportunity_id.value
                        if acceptance.opportunity_id is not None
                        else acceptance.interaction_id.value,
                    ),
                    AuditResultStatus.ACCEPTED,
                    command.trace_id,
                    AuditSensitivity.PRIVATE,
                    subject_id=SubjectId(current.subject_id),
                    request=AuditReference(
                        "external_message_input", acceptance.interaction_id.value
                    ),
                )
            )
            return acceptance

    async def _existing_in_unit(
        self,
        unit_of_work: object,
        context: ExternalMessageInputContext,
        idempotency_key: IdempotencyKey,
        request_digest: Digest,
    ) -> ExternalMessageInputAcceptance | None:
        return await self._messages.existing_external(
            unit_of_work,  # type: ignore[arg-type]
            context=context,
            idempotency_key=idempotency_key.value,
            request_digest=request_digest,
        )


def _request_digest(
    environment_id: UUID,
    command: ObservedExternalMessage,
    context: ExternalMessageInputContext,
    content_digest: Digest,
) -> Digest:
    return Digest.from_bytes(
        rfc8785.dumps(
            {
                "schema_version": "armi.external-message-input.v3",
                "environment_id": str(environment_id),
                "subject_id": str(context.subject_id),
                "scene_id": str(context.scene_id),
                "sender_party_id": str(context.sender_party_id),
                "sender_party_kind": context.sender_party_kind,
                "conversation_binding_id": str(context.conversation_binding_id),
                "channel": command.channel.value,
                "account_key": command.account_key.value,
                "conversation_kind": command.conversation_kind.value,
                "conversation_key": command.conversation_key.value,
                "message_key": command.message_key.value,
                "observed_at": command.observed_at.to_wire(),
                "addressed_to_subject": command.addressed_to_subject,
                "content_digest": content_digest.value,
                "parts": [
                    {
                        "kind": part.kind.value,
                        "text": part.text,
                        "target_key": part.target_key,
                        "locator": part.locator,
                        "file_name": part.file_name,
                        "media_type": part.media_type,
                        "byte_size": part.byte_size,
                        "visual_role": (
                            None if part.visual_role is None else part.visual_role.value
                        ),
                        "source_kind": part.source_kind,
                        "source_summary": part.source_summary,
                    }
                    for part in command.parts
                ],
            }
        )
    )


def _deferred_recognition(command: ObservedExternalMessage) -> str | None:
    if not command.has_media:
        return None
    if command.conversation_kind.value == "direct" or command.addressed_to_subject:
        return "pending"
    if not any(
        part.kind.value in {"text", "mention", "reply", "face"}
        for part in command.parts
    ):
        return "skipped"
    return None


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


def _scene_key(channel: str, account: str, kind: str, key: str) -> str:
    digest = Digest.from_bytes(
        rfc8785.dumps(
            {"channel": channel, "account": account, "kind": kind, "key": key}
        )
    ).value.removeprefix("sha256:")
    return f"external-{kind}-{digest[:32]}"


def _idempotency_key(command: ObservedExternalMessage) -> IdempotencyKey:
    digest = Digest.from_bytes(
        rfc8785.dumps(
            {
                "channel": command.channel.value,
                "account": command.account_key.value,
                "conversation_kind": command.conversation_kind.value,
                "conversation": command.conversation_key.value,
                "message": command.message_key.value,
            }
        )
    ).value.removeprefix("sha256:")
    return IdempotencyKey(f"external:{digest}")


def _acceptance(
    context: ExternalMessageInputContext,
    value: CreatorInputAcceptance | OtherHumanInputAcceptance,
) -> ExternalMessageInputAcceptance:
    return ExternalMessageInputAcceptance(
        context.conversation_binding_id,
        context.sender_party_id,
        context.sender_party_kind,
        context.scene_id,
        ExternalMessageInteractionId(value.interaction_id.value),
        value.evidence_id,
        value.opportunity_id,
        value.request_digest,
        value.content_digest,
        value.newly_accepted,
    )


__all__ = ("ExternalMessageInputService",)
