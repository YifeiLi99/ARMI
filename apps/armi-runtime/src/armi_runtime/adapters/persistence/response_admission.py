"""PostgreSQL owner for S028 Creator response admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import (
    ActionIntentId,
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    CreatorResponseOperationId,
    ResponseAdmissionResult,
    ResponseAdmissionStatus,
    ResponseViolation,
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

_WORK_KIND = "cognition.response.admit"


@dataclass(frozen=True, slots=True)
class ResponseAdmissionSnapshot:
    operation_id: UUID
    action_intent_id: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    artifact: ArtifactRef
    content_digest: Digest
    content_bytes: int
    trace_id: TraceId


class PostgreSQLResponseAdmissionRepository:
    """Settle one reply intent without executing an external effect."""

    __slots__ = ()

    async def snapshot(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        lease: WorkLease,
    ) -> ResponseAdmissionSnapshot:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT operation.creator_response_operation_id,
                       intent.action_intent_id, intent.subject_id,
                       intent.interaction_scene_id, intent.creator_party_id,
                       revision.response_artifact_id, revision.response_digest,
                       revision.response_bytes, work.trace_id
                FROM armi.durable_work AS work
                JOIN armi.creator_response_operations AS operation
                  ON operation.admission_work_id = work.work_id
                 AND operation.current_status = 'pending'
                JOIN armi.action_intents AS intent
                  ON intent.action_intent_id = operation.action_intent_id
                JOIN armi.action_intent_revisions AS revision
                  ON revision.action_intent_revision_id = intent.current_revision_id
                 AND revision.action_intent_id = intent.action_intent_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'cognition.response.admit'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND work.lease_expires_at > statement_timestamp()
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
            raise ResponseViolation("RESPONSE-WORK-STALE")
        return ResponseAdmissionSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            await _artifact_ref(connection, row[5]),
            Digest(str(row[6])),
            int(row[7]),
            TraceId(str(row[8])),
        )

    async def settle(
        self,
        unit_of_work: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ResponseAdmissionSnapshot,
        integrity_ok: bool,
    ) -> ResponseAdmissionResult:
        connection = unit_of_work._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise ResponseViolation("RESPONSE-FENCE")
        locked = await (
            await connection.execute(
                """
                SELECT current_status
                FROM armi.creator_response_operations
                WHERE creator_response_operation_id = %s
                FOR UPDATE
                """,
                (snapshot.operation_id,),
            )
        ).fetchone()
        if locked is None or str(locked[0]) != "pending":
            raise ResponseViolation("RESPONSE-WORK-STALE")
        if not integrity_ok:
            status = ResponseAdmissionStatus.FAILED
            grant_id = None
            reason = "RESPONSE-ARTIFACT-INTEGRITY"
        else:
            capability = await (
                await connection.execute(
                    """
                    SELECT availability_status
                    FROM armi.capabilities
                    WHERE capability_kind = 'creator.scene.reply'
                      AND operation_class = 'send'
                    """
                )
            ).fetchone()
            if capability is None or str(capability[0]) != "available":
                status = ResponseAdmissionStatus.UNAVAILABLE
                grant_id = None
                reason = "RESPONSE-CAPABILITY-UNAVAILABLE"
            else:
                grant = await (
                    await connection.execute(
                        """
                        SELECT permission.grant_id
                        FROM armi.permission_grants AS permission
                        WHERE permission.subject_id = %s
                          AND permission.interaction_scene_id = %s
                          AND permission.creator_party_id = %s
                          AND permission.operation_class = 'send'
                          AND permission.audience_scope = 'creator'
                          AND permission.data_scope = 'creator_visible_response'
                          AND permission.purpose = 'respond_to_creator'
                          AND permission.status = 'active'
                          AND permission.valid_from <= statement_timestamp()
                          AND statement_timestamp() < permission.valid_until
                          AND permission.consumed_uses < permission.max_uses
                          AND %s <= permission.max_payload_bytes
                        ORDER BY permission.valid_until, permission.grant_id
                        LIMIT 1
                        FOR UPDATE
                        """,
                        (
                            snapshot.subject_id,
                            snapshot.scene_id,
                            snapshot.creator_party_id,
                            snapshot.content_bytes,
                        ),
                    )
                ).fetchone()
                status = (
                    ResponseAdmissionStatus.ACCEPTED
                    if grant is not None
                    else ResponseAdmissionStatus.UNAUTHORIZED
                )
                grant_id = grant[0] if grant is not None else None
                reason = None if grant is not None else "POLICY-GRANT-NOT-CURRENT"
        completion = Digest.from_bytes(
            rfc8785.dumps(
                cast(
                    Any,
                    {
                        "schema_version": "armi.creator-response.v1",
                        "operation_id": str(snapshot.operation_id),
                        "action_intent_id": str(snapshot.action_intent_id),
                        "content_digest": snapshot.content_digest.value,
                        "status": status.value,
                        "grant_ref": str(grant_id) if grant_id is not None else None,
                        "reason_code": reason,
                        "delivery_state": "not_started",
                    },
                )
            )
        )
        updated = await (
            await connection.execute(
                """
                UPDATE armi.creator_response_operations
                SET current_status = %s, matched_grant_id = %s,
                    completion_digest = %s, reason_code = %s,
                    completed_at = statement_timestamp()
                WHERE creator_response_operation_id = %s
                  AND current_status = 'pending'
                RETURNING creator_response_operation_id
                """,
                (
                    status.value,
                    grant_id,
                    completion.value,
                    reason,
                    snapshot.operation_id,
                ),
            )
        ).fetchone()
        if updated is None:
            raise ResponseViolation("RESPONSE-WORK-STALE")
        if status is ResponseAdmissionStatus.ACCEPTED:
            registration_work_id = uuid7()
            now = datetime.now(UTC)
            await unit_of_work.work.enqueue(
                WorkDraft(
                    WorkId(registration_work_id),
                    "effect.register",
                    WorkOwner("creator_response_operation", snapshot.operation_id),
                    IdempotencyKey(f"effect-register:{snapshot.operation_id}"),
                    completion,
                    60,
                    Instant(now),
                    Instant(now + timedelta(seconds=3600)),
                    2,
                    snapshot.trace_id,
                    subject_id=SubjectId(snapshot.subject_id),
                    payload=WorkPayloadRef(
                        "creator_response_operation", snapshot.operation_id
                    ),
                )
            )
            await connection.execute(
                """
                UPDATE armi.creator_response_operations
                SET registration_work_id = %s
                WHERE creator_response_operation_id = %s
                  AND registration_work_id IS NULL
                """,
                (registration_work_id, snapshot.operation_id),
            )
        await unit_of_work.work.complete(
            lease,
            WorkResultRef("creator_response_operation", snapshot.operation_id),
        )
        audit_status = {
            ResponseAdmissionStatus.ACCEPTED: AuditResultStatus.ACCEPTED,
            ResponseAdmissionStatus.UNAUTHORIZED: AuditResultStatus.REJECTED,
            ResponseAdmissionStatus.UNAVAILABLE: AuditResultStatus.UNAVAILABLE,
            ResponseAdmissionStatus.FAILED: AuditResultStatus.FAILED,
        }[status]
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.response"),
                "cognition.response.admitted",
                AuditReference("creator_response_operation", snapshot.operation_id),
                audit_status,
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
                request_digest=snapshot.content_digest,
                response_digest=completion,
                grant=(
                    AuditReference("permission_grant", grant_id)
                    if grant_id is not None
                    else None
                ),
            )
        )
        return ResponseAdmissionResult(
            CreatorResponseOperationId(snapshot.operation_id),
            status,
            completion,
            ActionIntentId(snapshot.action_intent_id),
            grant_ref=grant_id,
            reason_code=reason,
        )


async def _artifact_ref(connection: Any, artifact_id: UUID) -> ArtifactRef:
    row = await (
        await connection.execute(
            """
            SELECT artifact_id, content_digest, media_type, byte_size,
                   logical_kind, privacy_scope, integrity_status
            FROM armi.artifacts
            WHERE artifact_id = %s AND retention_status = 'retained'
            """,
            (artifact_id,),
        )
    ).fetchone()
    if row is None:
        raise ResponseViolation("RESPONSE-ARTIFACT-INTEGRITY")
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


__all__ = ("PostgreSQLResponseAdmissionRepository", "ResponseAdmissionSnapshot")
