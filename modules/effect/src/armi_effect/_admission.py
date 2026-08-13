"""PostgreSQL owner for S028 Creator response admission."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid7

import rfc8785
from armi_expression.api import (
    ActionIntentId,
    CreatorResponseOperationId,
    ResponseAdmissionResult,
    ResponseAdmissionStatus,
    ResponseViolation,
)
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
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

_WORK_KIND = "cognition.response.admit"


@dataclass(frozen=True, slots=True)
class ResponseAdmissionSnapshot:
    operation_ref: UUID
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

    async def settle_current_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
    ) -> None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                    SELECT intent.operation_ref
                    FROM armi.durable_work AS work
                    JOIN armi.action_intents AS intent
                      ON intent.action_intent_id = work.owner_ref
                    WHERE work.work_id = %s
                      AND work.status = 'leased'
                      AND work.current_attempt_id = %s
                      AND work.lease_owner = %s
                      AND work.lease_token = %s
                      AND work.lease_expires_at > statement_timestamp()
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
            return
        await self._fail_locked(unit_of_work, lease, "RESPONSE-ADMISSION-STATE")

    async def fail_current_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
        *,
        code: str,
    ) -> None:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                    SELECT intent.operation_ref
                    FROM armi.durable_work AS work
                    JOIN armi.action_intents AS intent
                      ON intent.action_intent_id = work.owner_ref
                    WHERE work.work_id = %s
                      AND work.status = 'leased'
                      AND work.current_attempt_id = %s
                      AND work.lease_owner = %s
                      AND work.lease_token = %s
                      AND work.lease_expires_at > statement_timestamp()
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
            return
        await self._fail_locked(unit_of_work, lease, code)

    async def _fail_locked(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
        code: str,
    ) -> None:
        await unit_of_work.work.fail(lease, error_code=code)

    async def snapshot(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        lease: WorkLease,
    ) -> ResponseAdmissionSnapshot:
        connection = unit_of_work.transaction
        row = await (
            await connection.execute(
                """
                SELECT intent.operation_ref,
                       intent.action_intent_id, intent.subject_id,
                       intent.scene_id, intent.context_party_id,
                       revision.response_artifact_id, revision.response_digest,
                       revision.response_bytes, work.trace_id
                FROM armi.durable_work AS work
                JOIN armi.action_intents AS intent
                  ON intent.action_intent_id = work.owner_ref
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
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ResponseAdmissionSnapshot,
        integrity_ok: bool,
    ) -> ResponseAdmissionResult:
        connection = unit_of_work.transaction
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise ResponseViolation("RESPONSE-FENCE")
        locked = await (
            await connection.execute(
                """
                SELECT operation_ref
                FROM armi.action_intents
                WHERE action_intent_id = %s AND operation_ref = %s
                FOR UPDATE
                """,
                (snapshot.action_intent_id, snapshot.operation_ref),
            )
        ).fetchone()
        if locked is None:
            raise ResponseViolation("RESPONSE-WORK-STALE")
        if not integrity_ok:
            status = ResponseAdmissionStatus.FAILED
            grant_id = None
            reason = "RESPONSE-ARTIFACT-INTEGRITY"
        elif await _data_rights_block_response(connection, snapshot.creator_party_id):
            status = ResponseAdmissionStatus.UNAUTHORIZED
            grant_id = None
            reason = "DATA-RIGHTS-BLOCKED"
        else:
            capability = await (
                await connection.execute(
                    """
                    SELECT capability_id, availability_status
                    FROM armi.capabilities
                    WHERE capability_kind = 'creator.scene.reply'
                      AND operation_class = 'send'
                    """
                )
            ).fetchone()
            if capability is None or str(capability[1]) != "available":
                status = ResponseAdmissionStatus.UNAVAILABLE
                grant_id = None
                reason = "RESPONSE-CAPABILITY-UNAVAILABLE"
            else:
                grant = await (
                    await connection.execute(
                        """
                        SELECT permission.grant_id
                        FROM armi.permission_grants AS permission
                        WHERE permission.capability_id = %s
                          AND permission.subject_id = %s
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
                            capability[0],
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
        registration_work_digest = Digest.from_bytes(
            rfc8785.dumps(
                cast(
                    Any,
                    {
                        "schema_version": "armi.creator-response.v1",
                        "operation_ref": str(snapshot.operation_ref),
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
        if status is ResponseAdmissionStatus.ACCEPTED:
            registration_work_id = uuid7()
            now = datetime.now(UTC)
            await unit_of_work.work.enqueue(
                WorkDraft(
                    WorkId(registration_work_id),
                    "effect.register",
                    WorkOwner("action_intent", snapshot.action_intent_id),
                    IdempotencyKey(f"effect-register:{snapshot.action_intent_id}"),
                    registration_work_digest,
                    60,
                    Instant(now),
                    Instant(now + timedelta(seconds=3600)),
                    2,
                    snapshot.trace_id,
                    subject_id=SubjectId(snapshot.subject_id),
                    payload=WorkPayloadRef("action_intent", snapshot.action_intent_id),
                )
            )
        await unit_of_work.work.complete(
            lease,
            WorkResultRef("creator_response_operation", snapshot.operation_ref),
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
                AuditReference("creator_response_operation", snapshot.operation_ref),
                audit_status,
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
                grant=(
                    AuditReference("permission_grant", grant_id)
                    if grant_id is not None
                    else None
                ),
            )
        )
        return ResponseAdmissionResult(
            CreatorResponseOperationId(snapshot.operation_ref),
            status,
            ActionIntentId(snapshot.action_intent_id),
            grant_ref=grant_id,
            reason_code=reason,
        )


async def _data_rights_block_response(
    connection: Any,
    creator_party_id: UUID,
) -> bool:
    await connection.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"data-rights:{creator_party_id}",),
    )
    row = await (
        await connection.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM armi.deletion_orders
                WHERE requester_party_id = %s
                  AND status = 'effective'
                  AND order_kind IN (
                      'stop_contact', 'stop_use', 'delete_related'
                  )
            )
            """,
            (creator_party_id,),
        )
    ).fetchone()
    return bool(row is not None and row[0])


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
    )


__all__ = ("PostgreSQLResponseAdmissionRepository", "ResponseAdmissionSnapshot")
