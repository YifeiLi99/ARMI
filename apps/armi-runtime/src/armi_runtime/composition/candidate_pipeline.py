"""Production S025 deterministic candidate validation pipeline."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.content_store import (
    ContentAddressedArtifactStore,
)
from armi_artifact_store.life_material_codec import (
    parse_life_material_artifact,
)
from armi_kernel.application import (
    ActivityStatus,
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPolicy,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CandidateFactClass,
    CandidateViolation,
    LifeMaterialKind,
    LifeMaterialPrivacyStatus,
    LifeMaterialStatus,
    MaintenancePhase,
    MemoryAccessibility,
    MemorySourceKind,
    RelationshipBoundary,
    RelationshipBoundaryAction,
    RelationshipBoundaryKind,
    RelationshipCommitment,
    RelationshipCommitmentEventKind,
    RelationshipCommitmentStatus,
    RelationshipFact,
    RelationshipFactKind,
    RelationshipIssue,
    RelationshipIssueKind,
    RelationshipIssueStatus,
    RelationshipPartyRole,
    RelationshipStatus,
    RuntimeFence,
    WorkLease,
    WorkViolation,
)
from armi_kernel.contracts import Purpose, SubjectId

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
    CandidateLifeMaterialContext,
    CandidateMemoryContext,
    CandidateRelationshipCommitmentContext,
    CandidateRelationshipContext,
    CandidateSubjectPromptContext,
    CandidateValidationContext,
    DeterministicCandidateValidator,
)
from .work_wakeup import CANDIDATE_VALIDATE, SUBJECT_COMMIT, WorkWakeupBus

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
        "_repository",
        "_stop",
        "_storage",
        "_wakeups",
        "_web_search_active",
        "_work",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        storage: ContentAddressedArtifactStore,
        web_search_active: bool = False,
        wakeups: WorkWakeupBus | None = None,
        diagnostic: Diagnostic | None = None,
    ) -> None:
        self._factory = factory
        self._storage = storage
        self._web_search_active = web_search_active
        self._catalog = ArtifactCatalogRepository()
        self._repository = PostgreSQLCandidateValidationRepository()
        self._work = PostgreSQLDurableWorkGateway(factory)
        self._lease_owner = uuid7()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
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
        lease = cast(WorkLease, records[0].lease)
        try:
            snapshot = await self._snapshot(lease)
            response_bytes = await self._read_response(snapshot)
            material_contexts = await self._read_material_contexts(
                snapshot.current_materials
            )
            candidate_bytes = _candidate_bytes(response_bytes)
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
                    snapshot.purpose,
                    self._web_search_active,
                    True,
                    snapshot.codex_task_sources,
                    snapshot.opportunity_id,
                    snapshot.current_activity_id,
                    snapshot.current_activity_revision_id,
                    snapshot.current_activity_head_version,
                    None
                    if snapshot.current_activity_status is None
                    else ActivityStatus(snapshot.current_activity_status),
                    tuple(
                        CandidateMemoryContext(
                            item[0],
                            item[1],
                            item[2],
                            CandidateFactClass(item[3]),
                            MemorySourceKind(item[4]),
                            item[5],
                            item[6],
                            MemoryAccessibility(item[7]),
                        )
                        for item in snapshot.current_memories
                    ),
                    subject_party_id=snapshot.subject_party_id,
                    current_relationship=(
                        None
                        if snapshot.current_relationship is None
                        else CandidateRelationshipContext(
                            snapshot.current_relationship[0],
                            snapshot.current_relationship[1],
                            snapshot.current_relationship[2],
                            tuple(
                                RelationshipFact(RelationshipFactKind(item[0]), item[1])
                                for item in snapshot.current_relationship[3]
                            ),
                            snapshot.current_relationship[4],
                            tuple(
                                RelationshipBoundary(
                                    RelationshipPartyRole(item[0]),
                                    RelationshipBoundaryKind(item[1]),
                                    RelationshipBoundaryAction(item[2]),
                                    item[3],
                                )
                                for item in snapshot.current_relationship[5]
                            ),
                            RelationshipStatus(snapshot.current_relationship[6]),
                            tuple(
                                CandidateRelationshipCommitmentContext(
                                    RelationshipCommitment(
                                        item[0],
                                        RelationshipPartyRole(item[1]),
                                        item[2],
                                        item[3],
                                        RelationshipCommitmentStatus(item[4]),
                                        RelationshipCommitmentEventKind(item[5]),
                                        item[6],
                                    )
                                )
                                for item in snapshot.current_relationship[7]
                            ),
                            tuple(
                                RelationshipIssue(
                                    item[0],
                                    RelationshipIssueKind(item[1]),
                                    item[2],
                                    item[3],
                                    RelationshipIssueStatus(item[4]),
                                )
                                for item in snapshot.current_relationship[8]
                            ),
                        )
                    ),
                    current_materials=material_contexts,
                    current_subject_prompt=(
                        None
                        if snapshot.current_subject_prompt is None
                        else CandidateSubjectPromptContext(
                            *snapshot.current_subject_prompt
                        )
                    ),
                    candidate_contract_version=snapshot.candidate_contract_version,
                    current_maintenance_session_id=(
                        snapshot.current_maintenance_session_id
                    ),
                    current_maintenance_revision_id=(
                        snapshot.current_maintenance_revision_id
                    ),
                    current_maintenance_head_version=(
                        snapshot.current_maintenance_head_version
                    ),
                    current_maintenance_phase=(
                        None
                        if snapshot.current_maintenance_phase is None
                        else MaintenancePhase(snapshot.current_maintenance_phase)
                    ),
                    other_party_id=snapshot.other_party_id,
                    scene_kind=snapshot.scene_kind,
                    sender_party_kind=snapshot.sender_party_kind,
                )
            )
            result = validator.validate(candidate_bytes, bases=snapshot.bases)
            published = (
                await self._publish(result.change_set.canonical_bytes, snapshot)
                if result.change_set is not None
                else None
            )
            async with self._factory.unit_of_work() as unit_of_work:
                change_set_artifact = None
                if published is not None:
                    registration = await self._catalog.register(
                        unit_of_work,
                        ArtifactId(uuid7()),
                        published,
                    )
                    change_set_artifact = registration.ref
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
                    validator_identity=CANDIDATE_VALIDATOR_IDENTITY,
                    change_set_artifact=change_set_artifact,
                )
            self._wakeups.notify(SUBJECT_COMMIT)
            return True
        except CandidateViolation as error:
            if error.code == "CANDIDATE-WORK-STALE":
                self._diagnostic("candidate.work.stale")
                return True
            await self._fail(lease, error.code)
            return True
        except ArtifactViolation:
            await self._fail(lease, "CANDIDATE-ARTIFACT")
            return True
        except DatabaseTransactionError, WorkViolation:
            self._diagnostic("candidate.worker.transient_failure")
            return True

    async def run_worker(self) -> None:
        observed = self._wakeups.version(CANDIDATE_VALIDATE)
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
            observed = await self._wakeups.wait(
                CANDIDATE_VALIDATE,
                observed,
                stop=self._stop,
                timeout_seconds=1,
            )

    async def _snapshot(self, lease: WorkLease) -> CandidateEpisodeSnapshot:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
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
        if not value:
            raise CandidateViolation("CANDIDATE-ARTIFACT")
        return value

    async def _read_material_contexts(
        self,
        values: tuple[
            tuple[
                UUID,
                UUID,
                int,
                UUID,
                str,
                str,
                tuple[tuple[str, str], ...],
                str,
                str,
                ArtifactRef,
            ],
            ...,
        ],
    ) -> tuple[CandidateLifeMaterialContext, ...]:
        result: list[CandidateLifeMaterialContext] = []
        try:
            for item in values:
                ref = item[9]
                if (
                    ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
                    or ref.media_type != "application/json"
                    or ref.logical_kind != "life.material.content"
                    or ref.privacy_scope is not ArtifactPrivacyScope.PRIVATE
                ):
                    raise CandidateViolation("CANDIDATE-MATERIAL-CONTEXT")
                artifact_bytes = b""
                async with await self._storage.open_verified(ref) as stream:
                    artifact_bytes = await stream.read()
                result.append(
                    CandidateLifeMaterialContext(
                        item[0],
                        item[1],
                        item[2],
                        item[3],
                        LifeMaterialKind(item[4]),
                        item[5],
                        parse_life_material_artifact(artifact_bytes),
                        item[6],
                        LifeMaterialStatus(item[7]),
                        LifeMaterialPrivacyStatus(item[8]),
                    )
                )
        except ArtifactViolation, ValueError, UnicodeError:
            raise CandidateViolation("CANDIDATE-MATERIAL-CONTEXT") from None
        return tuple(result)

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

    async def _fail(self, lease: WorkLease, code: str) -> None:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                await self._repository.fail(
                    unit_of_work,
                    lease=lease,
                    error_code=code,
                )
        except CandidateViolation, DatabaseTransactionError, WorkViolation:
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
    web_search_active: bool = False,
    wakeups: WorkWakeupBus | None = None,
    diagnostic: Diagnostic | None = None,
) -> CandidateValidationPipeline:
    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
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
        web_search_active=web_search_active,
        wakeups=wakeups,
        diagnostic=diagnostic,
    )


__all__ = (
    "CandidateValidationPipeline",
    "build_candidate_validation_pipeline",
)
