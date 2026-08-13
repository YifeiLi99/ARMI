"""PostgreSQL owner for S033 read-only web observation custody."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID, uuid7

from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    WorkId,
    WorkLease,
    WorkRecord,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, SubjectId, TraceId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from ._observation_contract import (
    WebObservationAttemptId,
    WebObservationInvocationResult,
    WebObservationRecord,
    WebObservationRequestId,
    WebObservationRequestStatus,
    WebObservationResultStatus,
    WebObservationToolCallId,
    WebObservationUsage,
    WebObservationViolation,
)
from .api import WebArtifactCatalogPort

_WORK_KIND = "web.search.invoke"
_BINDING = "armi.model-tool.volcengine-ark-web-search-v1"


@dataclass(frozen=True, slots=True)
class WebObservationSnapshot:
    request_id: WebObservationRequestId
    subject_id: SubjectId
    request_artifact: ArtifactRef
    request_digest: Digest
    trace_id: TraceId
    attempt_count: int
    research_intent_id: UUID | None


class PostgreSQLWebObservationRepository:
    """Own fixed SQL for request, attempt, tool-call, and result custody."""

    __slots__ = ("_catalog",)

    def __init__(self, catalog: WebArtifactCatalogPort) -> None:
        self._catalog = catalog

    async def existing(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        subject_id: SubjectId,
        idempotency_key: str,
        request_digest: Digest,
    ) -> WebObservationRecord | None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT web_observation_request_id, subject_id, status,
                       request_digest, request_artifact_id, work_id,
                       (SELECT count(*) FROM armi.observation_attempts AS attempt
                        WHERE attempt.web_observation_request_id = request.web_observation_request_id),
                       result_artifact_id, last_error_code
                FROM armi.web_observation_requests AS request
                WHERE subject_id = %s
                  AND purpose = 'public_web_research'
                  AND idempotency_key = %s
                """,
                (subject_id.value, idempotency_key),
            )
        ).fetchone()
        if row is None:
            return None
        if str(row[3]) != request_digest.value:
            raise WebObservationViolation("WEB-IDEMPOTENCY-CONFLICT")
        return _record(row)

    async def create(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        request_id: WebObservationRequestId,
        subject_id: SubjectId,
        idempotency_key: str,
        request_artifact_id: ArtifactId,
        request_digest: Digest,
        work_id: WorkId,
    ) -> WebObservationRecord:
        fence = unit_of_work.runtime_fence
        if fence is None or fence.subject_id != subject_id.value:
            raise WebObservationViolation("WEB-FENCE")
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                INSERT INTO armi.web_observation_requests (
                    web_observation_request_id, subject_id, runtime_instance_id,
                    fence_token, idempotency_key, purpose, operation_class,
                    request_artifact_id, request_digest, binding_id, work_id,
                    deadline_at, max_cost_microyuan, status)
                VALUES (
                    %s, %s, %s, %s, %s, 'public_web_research',
                    'search_read_public', %s, %s, %s, %s,
                    statement_timestamp() + interval '90 seconds', 1000000, 'pending')
                RETURNING web_observation_request_id, subject_id, status,
                          request_digest, request_artifact_id, work_id,
                          0, result_artifact_id, last_error_code
                """,
                (
                    request_id.value,
                    subject_id.value,
                    fence.runtime_instance_id.value,
                    fence.fence_token,
                    idempotency_key,
                    request_artifact_id.value,
                    request_digest.value,
                    _BINDING,
                    work_id.value,
                ),
            )
        ).fetchone()
        if row is None:
            raise WebObservationViolation("WEB-DATABASE")
        return _record(row)

    async def snapshot(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
    ) -> WebObservationSnapshot:
        lease = cast(WorkLease, work.lease)
        if (
            work.draft.work_kind != _WORK_KIND
            or work.draft.owner.kind != "web_observation"
        ):
            raise WebObservationViolation("WEB-WORK-STALE")
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT request.web_observation_request_id, request.subject_id,
                       request.request_artifact_id, request.request_digest,
                       (SELECT count(*) FROM armi.observation_attempts AS attempt
                        WHERE attempt.web_observation_request_id = request.web_observation_request_id),
                       request.web_research_intent_id
                FROM armi.web_observation_requests AS request
                WHERE request.web_observation_request_id = %s
                  AND request.work_id = %s
                  AND request.status IN ('pending', 'running')
                  AND request.deadline_at > statement_timestamp()
                FOR UPDATE OF request
                """,
                (
                    work.draft.owner.reference,
                    lease.work_id.value,
                ),
            )
        ).fetchone()
        if row is None:
            raise WebObservationViolation("WEB-WORK-STALE")
        return WebObservationSnapshot(
            WebObservationRequestId(row[0]),
            SubjectId(row[1]),
            await self._catalog.get(unit_of_work, ArtifactId(row[2])),
            Digest(str(row[3])),
            work.draft.trace_id,
            int(row[4]),
            row[5],
        )

    async def prepare_attempt(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: WebObservationSnapshot,
        credential_identity: Digest,
    ) -> WebObservationAttemptId | None:
        connection = unit_of_work.transaction
        self._assert_work(lease, snapshot.request_id)
        previous = await (
            await connection.execute(
                """
                SELECT observation_attempt_id, dispatch_state
                FROM armi.observation_attempts
                WHERE web_observation_request_id = %s
                  AND dispatch_state IN ('prepared', 'dispatched')
                ORDER BY attempt_no DESC
                LIMIT 1
                FOR UPDATE
                """,
                (snapshot.request_id.value,),
            )
        ).fetchone()
        if previous is not None:
            previous_id, dispatch_state = previous
            if str(dispatch_state) == "dispatched":
                await connection.execute(
                    """
                    UPDATE armi.observation_attempts
                    SET dispatch_state = 'settled',
                        result_status = 'outcome_unknown',
                        error_code = 'WEB-RECOVERY-OUTCOME-UNKNOWN',
                        settled_at = statement_timestamp()
                    WHERE observation_attempt_id = %s
                    """,
                    (previous_id,),
                )
                await connection.execute(
                    """
                    UPDATE armi.web_observation_requests
                    SET status = 'unknown',
                        last_error_code = 'WEB-RECOVERY-OUTCOME-UNKNOWN',
                        completed_at = statement_timestamp()
                    WHERE web_observation_request_id = %s
                      AND status IN ('pending', 'running')
                    """,
                    (snapshot.request_id.value,),
                )
                await unit_of_work.work.fail(
                    lease,
                    error_code="WEB-RECOVERY-OUTCOME-UNKNOWN",
                )
                return None
            await connection.execute(
                """
                UPDATE armi.observation_attempts
                SET dispatch_state = 'settled', result_status = 'cancelled',
                    error_code = 'WEB-RECOVERY-PRE-DISPATCH',
                    settled_at = statement_timestamp()
                WHERE observation_attempt_id = %s
                """,
                (previous_id,),
            )
        attempt_no = snapshot.attempt_count + 1
        attempt_id = WebObservationAttemptId(uuid7())
        await connection.execute(
            """
            INSERT INTO armi.observation_attempts (
                observation_attempt_id, web_observation_request_id, work_id,
                work_attempt_id, work_lease_token, attempt_no, binding_id,
                credential_identity, dispatch_state) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'prepared')
            """,
            (
                attempt_id.value,
                snapshot.request_id.value,
                lease.work_id.value,
                lease.attempt_id.value,
                lease.token,
                attempt_no,
                _BINDING,
                credential_identity.value,
            ),
        )
        return attempt_id

    async def fail_before_attempt(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: WebObservationSnapshot,
        code: str,
    ) -> None:
        connection = unit_of_work.transaction
        self._assert_work(lease, snapshot.request_id)
        updated = await (
            await connection.execute(
                """
                UPDATE armi.web_observation_requests
                SET status = 'failed', last_error_code = %s,
                    completed_at = statement_timestamp()
                WHERE web_observation_request_id = %s
                  AND status IN ('pending', 'running')
                RETURNING web_observation_request_id
                """,
                (code, snapshot.request_id.value),
            )
        ).fetchone()
        if updated is None:
            raise WebObservationViolation("WEB-REQUEST-STATE")
        await unit_of_work.work.fail(lease, error_code=code)

    async def mark_dispatched(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: WebObservationSnapshot,
        attempt_id: WebObservationAttemptId,
    ) -> None:
        connection = unit_of_work.transaction
        self._assert_work(lease, snapshot.request_id)
        row = await (
            await connection.execute(
                """
                UPDATE armi.observation_attempts
                SET dispatch_state = 'dispatched',
                    dispatched_at = statement_timestamp()
                WHERE observation_attempt_id = %s
                  AND web_observation_request_id = %s
                  AND dispatch_state = 'prepared'
                RETURNING observation_attempt_id
                """,
                (attempt_id.value, snapshot.request_id.value),
            )
        ).fetchone()
        if row is None:
            raise WebObservationViolation("WEB-ATTEMPT-STATE")
        await connection.execute(
            """
            UPDATE armi.web_observation_requests
            SET status = 'running'
            WHERE web_observation_request_id = %s AND status = 'pending'
            """,
            (snapshot.request_id.value,),
        )

    async def settle_success(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: WebObservationSnapshot,
        attempt_id: WebObservationAttemptId,
        result_artifact: ArtifactRef,
        result: WebObservationInvocationResult,
    ) -> None:
        if result.status is not WebObservationResultStatus.SUCCEEDED:
            raise WebObservationViolation("WEB-RESULT")
        connection = unit_of_work.transaction
        self._assert_work(lease, snapshot.request_id)
        for ordinal, action in enumerate(result.tool_actions, start=1):
            await connection.execute(
                """
                INSERT INTO armi.observation_tool_calls (
                    observation_tool_call_id, observation_attempt_id, call_no,
                    action_type, completion_status
                ) VALUES (%s, %s, %s, %s, 'completed')
                """,
                (
                    WebObservationToolCallId(uuid7()).value,
                    attempt_id.value,
                    ordinal,
                    action.value,
                ),
            )
        usage = cast(WebObservationUsage, result.usage)
        updated = await (
            await connection.execute(
                """
                UPDATE armi.observation_attempts
                SET dispatch_state = 'settled', provider_model_id = %s,
                    result_artifact_id = %s,
                    input_tokens = %s, output_tokens = %s,
                    web_search_calls = %s, citation_count = %s,
                    estimated_cost_microyuan = %s, result_status = 'succeeded',
                    settled_at = statement_timestamp()
                WHERE observation_attempt_id = %s AND dispatch_state = 'dispatched'
                RETURNING observation_attempt_id
                """,
                (
                    cast(str, result.provider_model_id),
                    result_artifact.artifact_id.value,
                    usage.input_tokens,
                    usage.output_tokens,
                    usage.web_search_calls,
                    usage.citation_count,
                    usage.estimated_cost_microyuan,
                    attempt_id.value,
                ),
            )
        ).fetchone()
        if updated is None:
            raise WebObservationViolation("WEB-ATTEMPT-STATE")
        await connection.execute(
            """
            UPDATE armi.web_observation_requests
            SET status = 'succeeded', result_artifact_id = %s,
                completed_at = statement_timestamp()
            WHERE web_observation_request_id = %s AND status = 'running'
            """,
            (
                result_artifact.artifact_id.value,
                snapshot.request_id.value,
            ),
        )
        await unit_of_work.work.complete(
            lease,
            WorkResultRef("web_observation", snapshot.request_id.value),
        )

    async def settle_failure(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: WebObservationSnapshot,
        attempt_id: WebObservationAttemptId,
        result: WebObservationInvocationResult,
    ) -> None:
        code = result.error_code or "WEB-PROVIDER-FAILED"
        status = (
            WebObservationRequestStatus.UNKNOWN
            if result.status is WebObservationResultStatus.OUTCOME_UNKNOWN
            else WebObservationRequestStatus.FAILED
        )
        connection = unit_of_work.transaction
        self._assert_work(lease, snapshot.request_id)
        await connection.execute(
            """
            UPDATE armi.observation_attempts
            SET dispatch_state = 'settled', result_status = %s, error_code = %s,
                settled_at = statement_timestamp()
            WHERE observation_attempt_id = %s AND dispatch_state = 'dispatched'
            """,
            (result.status.value, code, attempt_id.value),
        )
        await connection.execute(
            """
            UPDATE armi.web_observation_requests
            SET status = %s, last_error_code = %s,
                completed_at = statement_timestamp()
            WHERE web_observation_request_id = %s AND status = 'running'
            """,
            (status.value, code, snapshot.request_id.value),
        )
        await unit_of_work.work.fail(lease, error_code=code)

    def _assert_work(
        self, lease: WorkLease, request_id: WebObservationRequestId
    ) -> None:
        if lease.work_id.value.version != 7 or request_id.value.version != 7:
            raise WebObservationViolation("WEB-WORK-STALE")


def _record(row: tuple[Any, ...]) -> WebObservationRecord:
    try:
        return WebObservationRecord(
            WebObservationRequestId(row[0]),
            SubjectId(row[1]),
            WebObservationRequestStatus(str(row[2])),
            Digest(str(row[3])),
            ArtifactId(row[4]),
            WorkId(row[5]),
            int(row[6]),
            ArtifactId(row[7]) if row[7] is not None else None,
            str(row[8]) if row[8] is not None else None,
        )
    except TypeError, ValueError, WebObservationViolation:
        raise WebObservationViolation("WEB-DATABASE-STATE") from None


__all__ = ("PostgreSQLWebObservationRepository", "WebObservationSnapshot")
