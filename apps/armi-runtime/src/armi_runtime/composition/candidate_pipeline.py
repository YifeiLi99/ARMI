"""Production S025 deterministic candidate validation pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
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
    CandidateViolation,
    LockPlan,
    LockTarget,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Digest, Instant, Purpose, SubjectId

from armi_runtime.adapters.artifacts.content_store import (
    ContentAddressedArtifactStore,
)
from armi_runtime.adapters.persistence.artifact_catalog import (
    ArtifactCatalogRepository,
)
from armi_runtime.adapters.persistence.candidate_validation import (
    CandidateEpisodeSnapshot,
    PostgreSQLCandidateValidationRepository,
)
from armi_runtime.adapters.persistence.durable_work import (
    PostgreSQLDurableWorkGateway,
)
from armi_runtime.adapters.persistence.unit_of_work import (
    PostgreSQLUnitOfWork,
    PostgreSQLUnitOfWorkFactory,
)
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .candidate_validator import (
    CANDIDATE_VALIDATOR_IDENTITY,
    CandidateValidationContext,
    DeterministicCandidateValidator,
)

_WORK_KIND = "cognition.candidate.validate"
_LEASE_SECONDS = 30
Diagnostic = Callable[[str], None]


async def _one_chunk(value: bytes) -> AsyncIterator[bytes]:
    yield value


def _ignore_diagnostic(_event: str) -> None:
    return None


class CandidateValidationPipeline:
    """Claim validation work without authority to apply subject changes."""

    __slots__ = (
        "_catalog",
        "_diagnostic",
        "_factory",
        "_lease_owner",
        "_policy_digest",
        "_repository",
        "_stop",
        "_storage",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        policy_digest: Digest,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._policy_digest = policy_digest
        self._catalog = ArtifactCatalogRepository()
        self._repository = PostgreSQLCandidateValidationRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._diagnostic = diagnostic or _ignore_diagnostic

    async def open(self) -> None:
        try:
            await self._factory.open()
            await self._storage.prepare()
        except DatabaseTransactionError:
            raise CandidateViolation("CANDIDATE-DATABASE") from None
        except ArtifactViolation:
            raise CandidateViolation("CANDIDATE-ARTIFACT") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def validate_once(self) -> bool:
        try:
            records = await self._work.claim(
                work_kind=_WORK_KIND,
                lease_owner=self._lease_owner,
                lease_seconds=_LEASE_SECONDS,
                limit=1,
            )
        except WorkViolation:
            raise CandidateViolation("CANDIDATE-DATABASE") from None
        if not records:
            return False
        lease = records[0].lease
        assert lease is not None
        try:
            snapshot = await self._snapshot(lease)
            response_bytes = await self._read_response(snapshot)
            candidate_bytes = _candidate_bytes(response_bytes)
            candidate_digest = Digest.from_bytes(candidate_bytes)
            validator = DeterministicCandidateValidator(
                CandidateValidationContext(
                    snapshot.subject_id,
                    snapshot.generation_id,
                    snapshot.episode_id,
                    snapshot.model_attempt_id,
                    snapshot.base_subject_version,
                    snapshot.base_state_epoch,
                    snapshot.bundle_activation_id,
                    snapshot.context_digest,
                    snapshot.scene_id,
                    snapshot.creator_party_id,
                    snapshot.current_components,
                )
            )
            result = validator.validate(candidate_bytes, bases=snapshot.bases)
            published = (
                await self._publish(result.change_set.canonical_bytes, snapshot)
                if result.change_set is not None
                else None
            )
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                artifact_id = None
                if published is not None:
                    registration = await self._catalog.register(
                        unit_of_work,
                        ArtifactId(uuid7()),
                        published,
                    )
                    artifact_id = registration.ref.artifact_id
                    if registration.inserted:
                        await unit_of_work.audit.append(
                            _artifact_audit(
                                unit_of_work,
                                registration.ref,
                                snapshot,
                            )
                        )
                await self._repository.settle(
                    unit_of_work,
                    lease=lease,
                    snapshot=snapshot,
                    result=result,
                    candidate_digest=candidate_digest,
                    policy_digest=self._policy_digest,
                    validator_identity=CANDIDATE_VALIDATOR_IDENTITY,
                    change_set_artifact_id=artifact_id,
                )
            return True
        except CandidateViolation as error:
            if error.code == "CANDIDATE-WORK-STALE":
                self._diagnostic("candidate.work.stale")
                return True
            await self._release(lease, error.code)
            return True
        except ArtifactViolation:
            await self._release(lease, "CANDIDATE-ARTIFACT")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("candidate.worker.transient_failure")
            return True

    async def run_worker(self) -> None:
        while not self._stop.is_set():
            try:
                worked = await self.validate_once()
            except CandidateViolation:
                if not self._stop.is_set():
                    self._diagnostic("candidate.worker.failed")
                worked = False
            if worked:
                await asyncio.sleep(0)
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1)

    async def _snapshot(self, lease: WorkLease) -> CandidateEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._repository.snapshot(unit_of_work, lease)
        except DatabaseTransactionError:
            raise CandidateViolation("CANDIDATE-DATABASE") from None

    async def _read_response(self, snapshot: CandidateEpisodeSnapshot) -> bytes:
        value = b""
        try:
            stream = await self._storage.open_verified(snapshot.response_artifact)
            async with stream:
                value = await stream.read()
        except ArtifactViolation:
            raise CandidateViolation("CANDIDATE-ARTIFACT") from None
        if (
            not value
            or Digest.from_bytes(value) != snapshot.response_artifact.content_digest
        ):
            raise CandidateViolation("CANDIDATE-ARTIFACT")
        return value

    async def _publish(
        self,
        value: bytes,
        snapshot: CandidateEpisodeSnapshot,
    ):
        staged = await self._storage.stage(
            _one_chunk(value),
            ArtifactPolicy(
                "application/json",
                "cognition.change_set",
                "candidate.validator",
                snapshot.trace_id,
                ArtifactPrivacyScope.RESTRICTED,
            ),
        )
        return await self._storage.publish(staged)

    async def _release(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                now = await (
                    await unit_of_work._connection_for_repository().execute(  # pyright: ignore[reportPrivateUsage]
                        "SELECT statement_timestamp()"
                    )
                ).fetchone()
                if now is None:
                    raise CandidateViolation("CANDIDATE-DATABASE")
                await unit_of_work.work.release(
                    lease,
                    not_before=Instant(now[0] + timedelta(seconds=1)),
                    error_code=code,
                )
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("candidate.settlement.deferred")


def _candidate_bytes(response_bytes: bytes) -> bytes:
    try:
        raw_response = json.loads(response_bytes)
        if not isinstance(raw_response, dict):
            raise CandidateViolation("CANDIDATE-CONTRACT")
        response = cast(dict[str, Any], raw_response)
        if (
            response.get("schema_version") != "armi.model-response-artifact.v1"
            or "candidate" not in response
        ):
            raise CandidateViolation("CANDIDATE-CONTRACT")
        return rfc8785.dumps(response["candidate"])
    except UnicodeDecodeError, json.JSONDecodeError, TypeError:
        raise CandidateViolation("CANDIDATE-CONTRACT") from None


def _artifact_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    ref: ArtifactRef,
    snapshot: CandidateEpisodeSnapshot,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.candidate"),
        "artifact.catalog.registered",
        AuditReference("artifact", ref.artifact_id.value),
        AuditResultStatus.APPLIED,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
        request=AuditReference("cognitive_episode", snapshot.episode_id),
        artifact_digest=ref.content_digest,
    )


def build_candidate_validation_pipeline(
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
    policy_digest: Digest,
    diagnostic: Diagnostic | None,
) -> CandidateValidationPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise CandidateViolation("CANDIDATE-LOCK")

    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        lock_acquirer=reject_dynamic_lock,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return CandidateValidationPipeline(
        factory=factory,
        storage=ContentAddressedArtifactStore(
            data_root / "artifacts",
            max_object_bytes=max_object_bytes,
        ),
        policy_digest=policy_digest,
        diagnostic=diagnostic,
    )


__all__ = (
    "CandidateValidationPipeline",
    "build_candidate_validation_pipeline",
)
