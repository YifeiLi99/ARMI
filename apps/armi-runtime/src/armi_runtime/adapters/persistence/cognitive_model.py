"""PostgreSQL ownership for S024 model attempts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    ModelAttemptId,
    ModelBinding,
    ModelInvocationResult,
    ModelResultStatus,
    ModelUsage,
    ModelViolation,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
)
from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    Purpose,
    SubjectId,
    TraceId,
)

from .unit_of_work import PostgreSQLUnitOfWork

_WORK_KIND = "cognition.model.invoke"
_VALIDATION_WORK_KIND = "cognition.candidate.validate"


@dataclass(frozen=True, slots=True)
class ModelEpisodeSnapshot:
    episode_id: UUID
    subject_id: UUID
    base_subject_version: int
    base_state_epoch: int
    bundle_activation_id: UUID
    context_digest: Digest
    compiled_context: ArtifactRef
    included_context_refs: tuple[dict[str, object], ...]
    trace_id: TraceId


class PostgreSQLCognitiveModelRepository:
    """Own attempt preparation, dispatch, and settlement SQL."""

    __slots__ = ()

    async def snapshot(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
    ) -> ModelEpisodeSnapshot:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT
                    episode.cognitive_episode_id,
                    episode.subject_id,
                    episode.base_subject_version,
                    episode.base_state_epoch,
                    episode.bundle_activation_id,
                    episode.context_digest,
                    episode.compiled_context_artifact_id,
                    episode.trace_id
                FROM armi.durable_work AS work
                JOIN armi.cognitive_episodes AS episode
                  ON episode.cognitive_episode_id = work.owner_ref
                WHERE work.work_id = %s
                  AND work.work_kind = 'cognition.model.invoke'
                  AND work.owner_kind = 'cognitive_episode'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at > statement_timestamp()
                  AND episode.status IN ('prepared', 'calling_model')
                FOR UPDATE OF work
                """,
                (
                    lease.work_id.value,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
            )
        ).fetchone()
        if row is None:
            raise ModelViolation("MODEL-WORK-STALE")
        refs = await (
            await connection.execute(
                """
                SELECT ordinal, section, item_kind
                FROM armi.cognitive_context_items
                WHERE cognitive_episode_id = %s
                  AND disposition = 'included'
                ORDER BY ordinal
                """,
                (row[0],),
            )
        ).fetchall()
        return ModelEpisodeSnapshot(
            row[0],
            row[1],
            int(row[2]),
            int(row[3]),
            row[4],
            Digest(str(row[5])),
            await self._artifact_ref(connection, row[6]),
            tuple(
                {
                    "ref": f"ctx:{int(item[0])}",
                    "section": str(item[1]),
                    "item_kind": str(item[2]),
                }
                for item in refs
            ),
            TraceId(str(row[7])),
        )

    async def prepare_attempt(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        binding: ModelBinding,
        request_artifact_id: ArtifactId,
        request_digest: Digest,
    ) -> ModelAttemptId:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await self._assert_lease(connection, lease, snapshot.episode_id)
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
        if attempt_no > binding.max_attempts:
            raise ModelViolation("MODEL-ATTEMPTS-EXHAUSTED")
        attempt_id = ModelAttemptId(uuid7())
        await connection.execute(
            """
            INSERT INTO armi.cognitive_attempts (
                model_attempt_id,
                cognitive_episode_id,
                work_id,
                work_attempt_id,
                attempt_no,
                binding_digest,
                provider,
                model_id,
                version_policy,
                profile,
                request_schema_version,
                candidate_schema_version,
                pricing_snapshot_id,
                credential_identity,
                request_artifact_id,
                request_digest,
                dispatch_status,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, 'prepared', 1
            )
            """,
            (
                attempt_id.value,
                snapshot.episode_id,
                lease.work_id.value,
                lease.attempt_id.value,
                attempt_no,
                binding.digest.value,
                binding.provider,
                binding.model_id,
                binding.version_policy,
                binding.profile,
                binding.request_contract_version,
                binding.response_contract_version,
                binding.pricing_snapshot_id,
                binding.credential_identity,
                request_artifact_id.value,
                request_digest.value,
            ),
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'calling_model'
                WHERE cognitive_episode_id = %s
                  AND status IN ('prepared', 'calling_model')
                RETURNING cognitive_episode_id
                """,
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
                request_digest=request_digest,
                details_digest=binding.digest,
            )
        )
        return attempt_id

    async def mark_dispatched(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        attempt_id: ModelAttemptId,
        episode_id: UUID,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await self._assert_lease(connection, lease, episode_id)
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
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        attempt_id: ModelAttemptId,
        response_artifact_id: ArtifactId,
        result: ModelInvocationResult,
    ) -> None:
        assert result.status is ModelResultStatus.SUCCEEDED
        assert result.usage is not None
        assert result.provider_request_id is not None
        assert result.provider_model_id is not None
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await self._assert_lease(connection, lease, snapshot.episode_id)
        await self._settle_attempt(
            connection,
            attempt_id=attempt_id,
            result=result,
            response_artifact_id=response_artifact_id,
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'model_returned',
                    model_returned_at = statement_timestamp()
                WHERE cognitive_episode_id = %s
                  AND status = 'calling_model'
                RETURNING cognitive_episode_id
                """,
                (snapshot.episode_id,),
            )
        ).fetchone()
        if updated is None:
            raise ModelViolation("MODEL-EPISODE-STATE")
        now_row = await (
            await connection.execute("SELECT statement_timestamp()")
        ).fetchone()
        if now_row is None or result.response_digest is None:
            raise ModelViolation("MODEL-DATABASE")
        now = Instant(now_row[0])
        await unit_of_work.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                _VALIDATION_WORK_KIND,
                WorkOwner("cognitive_episode", snapshot.episode_id),
                IdempotencyKey(f"candidate:{snapshot.episode_id}"),
                result.response_digest,
                50,
                now,
                Instant(now.value + timedelta(seconds=3600)),
                2,
                snapshot.trace_id,
                SubjectId(snapshot.subject_id),
                WorkPayloadRef("model_attempt", attempt_id.value),
            )
        )
        await unit_of_work.work.complete(
            lease,
            WorkResultRef("model_attempt", attempt_id.value),
        )
        await unit_of_work.audit.append(
            _settlement_audit(
                unit_of_work,
                snapshot,
                attempt_id,
                AuditResultStatus.COMPLETED,
                result.response_digest,
            )
        )
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.candidate"),
                "cognition.candidate.queued",
                AuditReference("cognitive_episode", snapshot.episode_id),
                AuditResultStatus.WAITING,
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
                request_digest=result.response_digest,
            )
        )

    async def settle_failure(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        attempt_id: ModelAttemptId,
        result: ModelInvocationResult,
        retryable: bool,
    ) -> None:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await self._assert_lease(connection, lease, snapshot.episode_id)
        await self._settle_attempt(
            connection,
            attempt_id=attempt_id,
            result=result,
            response_artifact_id=None,
        )
        code = result.error_code or "MODEL-PROVIDER-FAILED"
        retry_row = await (
            await connection.execute(
                """
                SELECT
                    work.attempt_count < work.max_attempts
                    AND work.deadline_at > statement_timestamp()
                FROM armi.durable_work AS work
                WHERE work.work_id = %s
                """,
                (lease.work_id.value,),
            )
        ).fetchone()
        may_retry = bool(retry_row and retry_row[0])
        if retryable and may_retry:
            now_row = await (
                await connection.execute("SELECT statement_timestamp()")
            ).fetchone()
            if now_row is None:
                raise ModelViolation("MODEL-DATABASE")
            await unit_of_work.work.release(
                lease,
                not_before=Instant(now_row[0] + timedelta(seconds=1)),
                error_code=code,
            )
            audit_status = AuditResultStatus.WAITING
        else:
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'failed', failure_code = %s
                WHERE cognitive_episode_id = %s
                  AND status = 'calling_model'
                """,
                (code, snapshot.episode_id),
            )
            await unit_of_work.work.fail(lease, error_code=code)
            audit_status = AuditResultStatus.FAILED
        await unit_of_work.audit.append(
            _settlement_audit(
                unit_of_work,
                snapshot,
                attempt_id,
                audit_status,
                None,
            )
        )

    async def fail_before_attempt(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ModelEpisodeSnapshot,
        code: str,
    ) -> None:
        if not code.startswith("MODEL-"):
            raise ModelViolation("MODEL-RESULT")
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        await self._assert_lease(connection, lease, snapshot.episode_id)
        updated = await (
            await connection.execute(
                """
                UPDATE armi.cognitive_episodes
                SET status = 'failed', failure_code = %s
                WHERE cognitive_episode_id = %s
                  AND status IN ('prepared', 'calling_model')
                RETURNING cognitive_episode_id
                """,
                (code, snapshot.episode_id),
            )
        ).fetchone()
        if updated is None:
            raise ModelViolation("MODEL-EPISODE-STATE")
        await unit_of_work.work.fail(lease, error_code=code)
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

    async def _settle_attempt(
        self,
        connection: Any,
        *,
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
                ),
            )
        ).fetchone()
        if updated is None:
            raise ModelViolation("MODEL-ATTEMPT-STATE")

    async def _assert_lease(
        self,
        connection: Any,
        lease: WorkLease,
        episode_id: UUID,
    ) -> None:
        row = await (
            await connection.execute(
                """
                SELECT work_id
                FROM armi.durable_work
                WHERE work_id = %s
                  AND work_kind = 'cognition.model.invoke'
                  AND owner_kind = 'cognitive_episode'
                  AND owner_ref = %s
                  AND status = 'leased'
                  AND current_attempt_id = %s
                  AND lease_owner = %s
                  AND lease_token = %s
                  AND lease_expires_at > statement_timestamp()
                FOR UPDATE
                """,
                (
                    lease.work_id.value,
                    episode_id,
                    lease.attempt_id.value,
                    lease.owner,
                    lease.token,
                ),
            )
        ).fetchone()
        if row is None:
            raise ModelViolation("MODEL-WORK-STALE")

    async def _artifact_ref(self, connection: Any, artifact_id: UUID) -> ArtifactRef:
        row = await (
            await connection.execute(
                """
                SELECT
                    artifact_id,
                    content_digest,
                    media_type,
                    byte_size,
                    logical_kind,
                    privacy_scope,
                    integrity_status
                FROM armi.artifacts
                WHERE artifact_id = %s
                  AND retention_status = 'retained'
                """,
                (artifact_id,),
            )
        ).fetchone()
        if row is None:
            raise ModelViolation("MODEL-CONTEXT")
        return ArtifactRef(
            ArtifactId(row[0]),
            Digest(str(row[1])),
            int(row[3]),
            str(row[2]),
            str(row[4]),
            ArtifactPrivacyScope(str(row[5])),
            ArtifactIntegrityStatus(str(row[6])),
            1,
        )


def _settlement_audit(
    unit_of_work: PostgreSQLUnitOfWork,
    snapshot: ModelEpisodeSnapshot,
    attempt_id: ModelAttemptId,
    status: AuditResultStatus,
    response_digest: Digest | None,
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
        response_digest=response_digest,
    )


__all__ = ("ModelEpisodeSnapshot", "PostgreSQLCognitiveModelRepository")
