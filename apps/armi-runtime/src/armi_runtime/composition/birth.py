"""Explicit composition for the one-time unique birth transaction."""

from __future__ import annotations

from collections.abc import AsyncIterator
from importlib.resources import files
from typing import Any, Final
from uuid import uuid7

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
    BirthManifest,
    BirthResult,
    BirthViolation,
    LockPlan,
    LockTarget,
    PublishedArtifact,
    TransactionIsolation,
)
from armi_kernel.contracts import Digest, Purpose, SubjectId, TraceId

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
    ArtifactRegistration,
)
from armi_runtime.adapters.persistence.birth import BirthArtifacts, BirthRepository
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .environment import PreparedEnvironment

_RESOURCE_PACKAGE: Final = "armi_runtime.composition.runtime_resources"


async def _bytes(value: bytes) -> AsyncIterator[bytes]:
    yield value


async def _unused_lock_acquirer(
    connection: psycopg.AsyncConnection[tuple[Any, ...]],
    target: LockTarget,
) -> None:
    del connection, target
    raise BirthViolation("BIRTH-STATE")


class BirthTransaction:
    """Publish immutable inputs, then atomically establish the unique subject."""

    __slots__ = ("_catalog", "_repository", "_storage", "_uow_factory")

    def __init__(
        self,
        storage: ContentAddressedArtifactStore,
        catalog: ArtifactCatalogRepository,
        repository: BirthRepository,
        unit_of_work_factory: PostgreSQLUnitOfWorkFactory,
    ) -> None:
        self._storage = storage
        self._catalog = catalog
        self._repository = repository
        self._uow_factory = unit_of_work_factory

    async def birth(self, manifest: BirthManifest) -> BirthResult:
        if type(manifest) is not BirthManifest:
            raise BirthViolation("BIRTH-MANIFEST")
        anchor_bytes = rfc8785.dumps(
            {
                "schema_version": manifest.personality_anchor.schema_version,
                "voice_style": manifest.personality_anchor.voice_style,
                "traits": list(manifest.personality_anchor.traits),
            }
        )
        composition_bytes = (
            files(_RESOURCE_PACKAGE)
            .joinpath("runtime-composition.manifest.json")
            .read_bytes()
        )
        trace_id = TraceId(manifest.birth_request_id.hex)
        try:
            anchor = await self._storage.publish(
                await self._storage.stage(
                    _bytes(anchor_bytes),
                    ArtifactPolicy(
                        media_type="application/json",
                        logical_kind="birth.personality_anchor",
                        producer_kind="bootstrap",
                        producer_trace_id=trace_id,
                        privacy_scope=ArtifactPrivacyScope.RESTRICTED,
                    ),
                )
            )
            activation = await self._storage.publish(
                await self._storage.stage(
                    _bytes(composition_bytes),
                    ArtifactPolicy(
                        media_type="application/json",
                        logical_kind="birth.bootstrap_activation",
                        producer_kind="bootstrap",
                        producer_trace_id=trace_id,
                        privacy_scope=ArtifactPrivacyScope.RESTRICTED,
                    ),
                )
            )
        except ArtifactViolation, OSError:
            raise BirthViolation("BIRTH-ARTIFACT") from None
        if (
            anchor.content_digest != manifest.personality_anchor_digest
            or activation.content_digest != manifest.composition_digest
        ):
            raise BirthViolation("BIRTH-PACKAGE-DRIFT")
        fixed_prompt_set_digest = Digest.from_bytes(
            rfc8785.dumps(
                {"personality_anchor": manifest.personality_anchor_digest.value}
            )
        )
        for attempt in range(3):
            try:
                return await self._attempt(
                    manifest,
                    anchor,
                    activation,
                    fixed_prompt_set_digest,
                    trace_id,
                )
            except DatabaseTransactionError as error:
                if error.code == "DB-TX-COMMIT-UNKNOWN":
                    recovered = await self._recover_existing(manifest)
                    if recovered is not None:
                        return recovered
                    raise BirthViolation("BIRTH-COMMIT-UNKNOWN") from None
                if error.code != "DB-TX-SERIALIZATION" or attempt == 2:
                    raise BirthViolation("BIRTH-DATABASE") from None
                recovered = await self._recover_existing(manifest)
                if recovered is not None:
                    return recovered
            except AuditViolation:
                raise BirthViolation("BIRTH-AUDIT") from None
            except ArtifactViolation:
                raise BirthViolation("BIRTH-ARTIFACT") from None
        raise BirthViolation("BIRTH-DATABASE")

    async def _attempt(
        self,
        manifest: BirthManifest,
        anchor: PublishedArtifact,
        activation: PublishedArtifact,
        fixed_prompt_set_digest: Digest,
        trace_id: TraceId,
    ) -> BirthResult:
        async with self._uow_factory.unit_of_work(
            LockPlan(),
            isolation=TransactionIsolation.SERIALIZABLE,
        ) as unit_of_work:
            await self._repository.lock_environment(
                unit_of_work,
                manifest.environment_id,
            )
            existing = await self._repository.existing(unit_of_work, manifest)
            if existing is not None:
                return existing
            anchor_registration = await self._register_artifact(
                unit_of_work,
                anchor,
                manifest,
                trace_id,
            )
            activation_registration = await self._register_artifact(
                unit_of_work,
                activation,
                manifest,
                trace_id,
            )
            result = await self._repository.create(
                unit_of_work,
                manifest,
                BirthArtifacts(
                    anchor_registration.ref.artifact_id.value,
                    activation_registration.ref.artifact_id.value,
                    fixed_prompt_set_digest,
                ),
            )
            await unit_of_work.audit.append(
                AuditDraft(
                    audit_event_id=AuditEventId(uuid7()),
                    actor=AuditReference("creator", manifest.creator_party_id),
                    purpose=Purpose("subject.birth"),
                    operation="subject.birth.completed",
                    target=AuditReference("subject", result.subject_id),
                    result_status=AuditResultStatus.COMPLETED,
                    trace_id=trace_id,
                    sensitivity=AuditSensitivity.RESTRICTED,
                    subject_id=SubjectId(result.subject_id),
                    request=AuditReference(
                        "birth_request",
                        manifest.birth_request_id,
                    ),
                    request_digest=manifest.request_digest,
                    bundle_digest=manifest.composition_digest,
                )
            )
            return result

    async def _register_artifact(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        published: PublishedArtifact,
        manifest: BirthManifest,
        trace_id: TraceId,
    ) -> ArtifactRegistration:
        registration = await self._catalog.register(
            unit_of_work,
            ArtifactId(uuid7()),
            published,
        )
        if registration.inserted:
            await unit_of_work.audit.append(
                AuditDraft(
                    audit_event_id=AuditEventId(uuid7()),
                    actor=AuditReference("runtime", manifest.environment_id),
                    purpose=Purpose("subject.birth"),
                    operation="artifact.catalog.registered",
                    target=AuditReference(
                        "artifact",
                        registration.ref.artifact_id.value,
                    ),
                    result_status=AuditResultStatus.APPLIED,
                    trace_id=trace_id,
                    sensitivity=AuditSensitivity.RESTRICTED,
                    request=AuditReference(
                        "birth_request",
                        manifest.birth_request_id,
                    ),
                    artifact_digest=registration.ref.content_digest,
                )
            )
        return registration

    async def _recover_existing(
        self,
        manifest: BirthManifest,
    ) -> BirthResult | None:
        try:
            async with self._uow_factory.unit_of_work(
                LockPlan(),
                read_only=True,
            ) as unit_of_work:
                return await self._repository.existing(unit_of_work, manifest)
        except DatabaseTransactionError:
            return None


async def run_birth_transaction(
    transaction: BirthTransaction,
    manifest: BirthManifest,
) -> BirthResult:
    return await transaction.birth(manifest)


async def execute_birth_with_conninfo(
    prepared: PreparedEnvironment,
    manifest: BirthManifest,
    conninfo: str,
) -> BirthResult:
    config = prepared.effective.config
    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=config.environment.environment_id,
        lock_acquirer=_unused_lock_acquirer,
        pool_min=config.database.pool_min,
        pool_max=config.database.pool_max,
        acquire_timeout_seconds=config.database.pool_acquire_timeout_seconds,
        statement_timeout_seconds=config.database.statement_timeout_seconds,
    )
    storage = ContentAddressedArtifactStore(
        prepared.data_root / "artifacts",
        max_object_bytes=config.artifacts.max_object_bytes,
    )
    transaction = BirthTransaction(
        storage,
        ArtifactCatalogRepository(),
        BirthRepository(),
        factory,
    )
    await factory.open()
    try:
        return await transaction.birth(manifest)
    finally:
        await factory.close()


__all__ = (
    "BirthTransaction",
    "execute_birth_with_conninfo",
    "run_birth_transaction",
)
