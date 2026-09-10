"""PostgreSQL ownership for S024 model attempts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid7

from armi_attention.api import OpportunityCognitionSelectionPort
from armi_context.api import ContextCognitionReadPort
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    ModelAttemptId,
    ModelBinding,
    ModelInvocationResult,
    ModelUsage,
    ModelViolation,
    WorkLease,
    WorkRecord,
    WorkStatus,
    WorkType,
    WorkViolation,
)
from armi_kernel.contracts import (
    Digest,
    Purpose,
    SubjectId,
    TraceId,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

from .api import CognitionArtifactCatalogPort

_WORK_KIND = WorkType.COGNITION_EXECUTE


@dataclass(frozen=True, slots=True)
class ModelEpisodeSnapshot:
    episode_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    context_party_id: UUID | None
    purpose: str
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    context_digest: Digest
    compiled_context: ArtifactRef
    included_context_refs: tuple[dict[str, object], ...]
    budget_exclusions: tuple[dict[str, object], ...]
    trace_id: TraceId


class PostgreSQLCognitiveModelRepository:
    """Own attempt preparation, dispatch, and settlement SQL."""

    def __init__(
        self,
        context: ContextCognitionReadPort,
        catalog: CognitionArtifactCatalogPort,
        opportunities: OpportunityCognitionSelectionPort,
    ) -> None:
        self._context = context
        self._catalog = catalog
        self._opportunities = opportunities

    async def snapshot(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
    ) -> ModelEpisodeSnapshot:
        connection = unit_of_work.transaction
        if (
            work.status is not WorkStatus.LEASED
            or work.lease is None
            or work.draft.work_kind != _WORK_KIND
            or work.draft.owner.kind != "cognitive_episode"
        ):
            raise ModelViolation("MODEL-WORK-STALE")
        row = await (
            await connection.execute(
                """
                SELECT
                    episode.cognitive_episode_id,
                    episode.subject_id,
                    episode.scene_id,
                    episode.context_party_id,
                    episode.purpose,
                    episode.base_subject_version,
                    episode.base_state_epoch,
                    episode.bundle_activation_id,
                    episode.compiled_context_digest,
                    episode.compiled_context_artifact_id,
                    episode.trace_id
                FROM armi.cognitive_episodes AS episode
                WHERE episode.cognitive_episode_id=%s
                  AND episode.status IN ('prepared', 'calling_model')
                FOR UPDATE OF episode
                """,
                (work.draft.owner.reference,),
            )
        ).fetchone()
        if row is None:
            raise ModelViolation("MODEL-WORK-STALE")
        included, excluded = await self._context.model_references(
            connection, episode_id=row[0]
        )
        return ModelEpisodeSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            str(row[4]),
            int(row[5]),
            int(row[6]),
            row[7],
            Digest(str(row[8])),
            await self._artifact_ref(unit_of_work, row[9]),
            tuple(
                {
                    "ref": f"ctx:{item.ordinal}",
                    "section": item.section,
                    "item_kind": item.item_kind,
                }
                for item in included
            ),
            tuple(
                {
                    "ref": f"ctx:{item.ordinal}",
                    "section": item.section,
                    "item_kind": item.item_kind,
                    "reason_code": item.reason_code,
                }
                for item in excluded
            ),
            TraceId(str(row[10])),
        )

    async def end_abandoned_finalization(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, work: WorkRecord
    ) -> bool:
        lease = cast(WorkLease, work.lease)
        await self._assert_lease(unit_of_work, lease, work.draft.owner.reference)
        row = await (
            await unit_of_work.transaction.execute(
                """UPDATE armi.cognitive_episodes
                   SET status='cancelled',failure_code='COGNITION-EXECUTION-INTERRUPTED'
                   WHERE cognitive_episode_id=%s AND status='finalizing'
                   RETURNING opportunity_id""",
                (work.draft.owner.reference,),
            )
        ).fetchone()
        if row is None:
            return False
        await self._opportunities.resolve_cognition_failure(
            unit_of_work.transaction, opportunity_id=row[0]
        )
        await unit_of_work.work.fail(
            lease, error_code="COGNITION-EXECUTION-INTERRUPTED"
        )
        return True

    async def prepare_attempt(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        binding: ModelBinding,
        request_artifact: ArtifactRef,
    ) -> ModelAttemptId | None:
        connection = unit_of_work.transaction
        await self._assert_lease(unit_of_work, lease, snapshot.episode_id)
        previous = await (
            await connection.execute(
                """
                SELECT model_attempt_id, dispatch_status
                FROM armi.cognitive_attempts
                WHERE cognitive_episode_id = %s
                  AND dispatch_status IN ('prepared', 'dispatched')
                ORDER BY attempt_no DESC
                LIMIT 1
                FOR UPDATE
                """,
                (snapshot.episode_id,),
            )
        ).fetchone()
        if previous is not None:
            previous_id = ModelAttemptId(previous[0])
            if str(previous[1]) == "dispatched":
                await connection.execute(
                    """
                    UPDATE armi.cognitive_attempts
                    SET dispatch_status = 'settled',
                        result_status = 'outcome_unknown',
                        error_code = 'MODEL-OUTCOME-UNKNOWN',
                        settled_at = statement_timestamp()
                    WHERE model_attempt_id = %s
                    """,
                    (previous_id.value,),
                )
                await connection.execute(
                    """UPDATE armi.cognitive_episodes
                       SET status='failed',failure_code='MODEL-OUTCOME-UNKNOWN'
                       WHERE cognitive_episode_id=%s
                         AND status IN ('prepared','calling_model')""",
                    (snapshot.episode_id,),
                )
                await unit_of_work.audit.append(
                    _settlement_audit(
                        unit_of_work,
                        snapshot,
                        previous_id,
                        AuditResultStatus.FAILED,
                    )
                )
                await self._resolve_selected_opportunity(
                    unit_of_work, snapshot.episode_id
                )
                await unit_of_work.work.fail(lease, error_code="MODEL-OUTCOME-UNKNOWN")
                return None
            await connection.execute(
                """
                UPDATE armi.cognitive_attempts
                SET dispatch_status = 'settled', result_status = 'cancelled',
                    error_code = 'MODEL-RECOVERY-PRE-DISPATCH',
                    settled_at = statement_timestamp()
                WHERE model_attempt_id = %s
                """,
                (previous_id.value,),
            )
            await connection.execute(
                """UPDATE armi.cognitive_episodes
                   SET status='cancelled',failure_code='COGNITION-EXECUTION-INTERRUPTED'
                   WHERE cognitive_episode_id=%s AND status IN ('prepared','calling_model')""",
                (snapshot.episode_id,),
            )
            await self._resolve_selected_opportunity(unit_of_work, snapshot.episode_id)
            await unit_of_work.work.fail(
                lease, error_code="COGNITION-EXECUTION-INTERRUPTED"
            )
            return None
        count_row = await (
            await connection.execute(
                """
                SELECT count(*)
                FROM armi.cognitive_attempts
                WHERE cognitive_episode_id = %s
                """,
                (snapshot.episode_id,),
            )
        ).fetchone()
        if count_row is None:
            raise ModelViolation("MODEL-DATABASE")
        attempt_no = int(count_row[0]) + 1
        attempt_id = ModelAttemptId(uuid7())
        await connection.execute(
            """
            INSERT INTO armi.cognitive_attempts (
                model_attempt_id,
                cognitive_episode_id,
                work_id,
                work_attempt_id,
                attempt_no,
                provider,
                model_id,
                version_policy,
                profile,
                request_schema_version,
                candidate_schema_version,
                pricing_snapshot_id,
                credential_identity,
                request_artifact_id,
                dispatch_status)
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, 'prepared')
            """,
            (
                attempt_id.value,
                snapshot.episode_id,
                lease.work_id.value,
                lease.attempt_id.value,
                attempt_no,
                binding.provider,
                binding.model_id,
                binding.version_policy,
                binding.profile,
                binding.request_contract_version,
                binding.response_contract_version,
                binding.pricing_snapshot_id,
                binding.credential_identity,
                request_artifact.artifact_id.value,
            ),
        )
        updated = await (
            await connection.execute(
                """UPDATE armi.cognitive_episodes SET status='calling_model'
               WHERE cognitive_episode_id=%s AND status IN ('prepared','calling_model')
               RETURNING cognitive_episode_id""",
                (snapshot.episode_id,),
            )
        ).fetchone()
        if updated is None:
            raise ModelViolation("MODEL-EPISODE-STATE")
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.model"),
                "cognition.model.attempt.prepared",
                AuditReference("model_attempt", attempt_id.value),
                AuditResultStatus.ACCEPTED,
                snapshot.trace_id,
                AuditSensitivity.RESTRICTED,
                subject_id=SubjectId(snapshot.subject_id),
            )
        )
        return attempt_id

    async def mark_dispatched(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        attempt_id: ModelAttemptId,
        episode_id: UUID,
    ) -> None:
        connection = unit_of_work.transaction
        await self._assert_lease(unit_of_work, lease, episode_id)
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_attempts
                SET dispatch_status = 'dispatched',
                    dispatched_at = statement_timestamp()
                WHERE model_attempt_id = %s
                  AND cognitive_episode_id = %s
                  AND work_id = %s
                  AND work_attempt_id = %s
                  AND dispatch_status = 'prepared'
                RETURNING model_attempt_id
                """,
                (
                    attempt_id.value,
                    episode_id,
                    lease.work_id.value,
                    lease.attempt_id.value,
                ),
            )
        ).fetchone()
        if updated is None:
            raise ModelViolation("MODEL-ATTEMPT-STATE")

    async def settle_success(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        attempt_id: ModelAttemptId,
        response_artifact: ArtifactRef,
        result: ModelInvocationResult,
    ) -> None:
        connection = unit_of_work.transaction
        await self._assert_lease(unit_of_work, lease, snapshot.episode_id)
        await self._settle_attempt(
            connection,
            lease=lease,
            attempt_id=attempt_id,
            result=result,
            response_artifact_id=response_artifact.artifact_id,
        )
        await unit_of_work.audit.append(
            _settlement_audit(
                unit_of_work,
                snapshot,
                attempt_id,
                AuditResultStatus.COMPLETED,
            )
        )

    async def settle_failure(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        attempt_id: ModelAttemptId,
        result: ModelInvocationResult,
    ) -> None:
        connection = unit_of_work.transaction
        await self._assert_lease(unit_of_work, lease, snapshot.episode_id)
        await self._settle_attempt(
            connection,
            lease=lease,
            attempt_id=attempt_id,
            result=result,
            response_artifact_id=None,
        )
        await unit_of_work.audit.append(
            _settlement_audit(
                unit_of_work,
                snapshot,
                attempt_id,
                AuditResultStatus.FAILED,
            )
        )

    async def fail_before_attempt(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        code: str,
    ) -> None:
        if not code.startswith("MODEL-"):
            raise ModelViolation("MODEL-RESULT")
        connection = unit_of_work.transaction
        await self._assert_lease(unit_of_work, lease, snapshot.episode_id)
        updated = await (
            await connection.execute(
                """UPDATE armi.cognitive_episodes SET status='failed',failure_code=%s
               WHERE cognitive_episode_id=%s AND status IN ('prepared','calling_model')
               RETURNING cognitive_episode_id""",
                (code, snapshot.episode_id),
            )
        ).fetchone()
        if updated is None:
            raise ModelViolation("MODEL-EPISODE-STATE")
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.model"),
                "cognition.model.request.rejected",
                AuditReference("cognitive_episode", snapshot.episode_id),
                AuditResultStatus.FAILED,
                snapshot.trace_id,
                AuditSensitivity.RESTRICTED,
                subject_id=SubjectId(snapshot.subject_id),
            )
        )

    async def finalize_primary_success(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        attempt_id: ModelAttemptId,
        response_artifact: ArtifactRef,
    ) -> None:
        await self._mark_episode_returned(unit_of_work, snapshot.episode_id)

    async def fail_episode(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        code: str,
    ) -> None:
        await self._assert_lease(unit_of_work, lease, snapshot.episode_id)
        row = await (
            await unit_of_work.transaction.execute(
                """UPDATE armi.cognitive_episodes
                   SET status='failed',failure_code=%s
                   WHERE cognitive_episode_id=%s
                     AND status IN ('prepared','calling_model','finalizing')
                   RETURNING cognitive_episode_id""",
                (code, snapshot.episode_id),
            )
        ).fetchone()
        if row is None:
            raise ModelViolation("MODEL-EPISODE-STATE")
        await self._resolve_selected_opportunity(unit_of_work, snapshot.episode_id)
        await unit_of_work.work.fail(lease, error_code=code)

    async def _mark_episode_returned(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        episode_id: UUID,
    ) -> None:
        row = await (
            await unit_of_work.transaction.execute(
                """UPDATE armi.cognitive_episodes
                   SET status='finalizing',model_returned_at=statement_timestamp()
                   WHERE cognitive_episode_id=%s AND status='calling_model'
                   RETURNING cognitive_episode_id""",
                (episode_id,),
            )
        ).fetchone()
        if row is None:
            raise ModelViolation("MODEL-EPISODE-STATE")

    async def _settle_attempt(
        self,
        connection: PostgreSQLTransaction,
        *,
        lease: WorkLease,
        attempt_id: ModelAttemptId,
        result: ModelInvocationResult,
        response_artifact_id: ArtifactId | None,
    ) -> None:
        usage: ModelUsage | None = result.usage
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_attempts
                SET dispatch_status = 'settled',
                    provider_request_id = %s,
                    provider_model_id = %s,
                    response_artifact_id = %s,
                    input_tokens = %s,
                    output_tokens = %s,
                    cached_input_tokens = %s,
                    estimated_cost_microyuan = %s,
                    result_status = %s,
                    error_code = %s,
                    settled_at = statement_timestamp()
                WHERE model_attempt_id = %s
                  AND work_id = %s
                  AND work_attempt_id = %s
                  AND dispatch_status = 'dispatched'
                RETURNING model_attempt_id
                """,
                (
                    result.provider_request_id,
                    result.provider_model_id,
                    response_artifact_id.value if response_artifact_id else None,
                    usage.input_tokens if usage else None,
                    usage.output_tokens if usage else None,
                    usage.cached_input_tokens if usage else None,
                    usage.estimated_cost_microyuan if usage else None,
                    result.status.value,
                    result.error_code,
                    attempt_id.value,
                    lease.work_id.value,
                    lease.attempt_id.value,
                ),
            )
        ).fetchone()
        if updated is None:
            raise ModelViolation("MODEL-ATTEMPT-STATE")

    async def _assert_lease(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
        episode_id: UUID,
    ) -> None:
        if (
            lease.work_kind is not _WORK_KIND
            or lease.work_owner.kind != "cognitive_episode"
            or lease.work_owner.reference != episode_id
        ):
            raise ModelViolation("MODEL-WORK-STALE")
        try:
            await unit_of_work.work.validate_lease(lease)
        except WorkViolation:
            raise ModelViolation("MODEL-WORK-STALE") from None

    async def _artifact_ref(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, artifact_id: UUID
    ) -> ArtifactRef:
        ref = await self._catalog.retained_ref(unit_of_work, ArtifactId(artifact_id))
        if ref is None:
            raise ModelViolation("MODEL-CONTEXT")
        return ref

    async def _resolve_selected_opportunity(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, episode_id: UUID
    ) -> None:
        row = await (
            await unit_of_work.transaction.execute(
                "SELECT opportunity_id FROM armi.cognitive_episodes "
                "WHERE cognitive_episode_id=%s",
                (episode_id,),
            )
        ).fetchone()
        if row is None or not await self._opportunities.resolve_cognition_failure(
            unit_of_work.transaction, opportunity_id=row[0]
        ):
            raise ModelViolation("MODEL-OPPORTUNITY-STATE")


def _settlement_audit(
    unit_of_work: PostgreSQLRuntimeUnitOfWork,
    snapshot: ModelEpisodeSnapshot,
    attempt_id: ModelAttemptId,
    status: AuditResultStatus,
) -> AuditDraft:
    return AuditDraft(
        AuditEventId(uuid7()),
        AuditReference("runtime", unit_of_work.environment_id),
        Purpose("cognition.model"),
        "cognition.model.attempt.settled",
        AuditReference("model_attempt", attempt_id.value),
        status,
        snapshot.trace_id,
        AuditSensitivity.RESTRICTED,
        subject_id=SubjectId(snapshot.subject_id),
    )


__all__ = (
    "ModelEpisodeSnapshot",
    "PostgreSQLCognitiveModelRepository",
)
