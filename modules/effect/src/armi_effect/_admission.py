"""Creator response admission coordinated exclusively through owner ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.api import ArtifactCatalogPort
from armi_capability.api import (
    CapabilityAdmissionPort,
    CapabilityAdmissionRequest,
    CapabilityAuthorizationOutcome,
)
from armi_data_rights.api import DataRightsEffectGate
from armi_expression.api import (
    ActionIntentId,
    CreatorResponseOperationId,
    ExpressionResponseAdmissionPort,
    ResponseAdmissionResult,
    ResponseAdmissionStatus,
    ResponseViolation,
)
from armi_kernel.application import (
    ArtifactId,
    ArtifactRef,
    AuditDraft,
    AuditEventId,
    AuditReference,
    AuditResultStatus,
    AuditSensitivity,
    WorkDraft,
    WorkId,
    WorkOwner,
    WorkPayloadRef,
    WorkRecord,
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
    """Coordinate admission while every owner retains its own SQL."""

    __slots__ = ("_artifacts", "_capability", "_data_rights", "_expression")

    def __init__(
        self,
        *,
        artifacts: ArtifactCatalogPort,
        capability: CapabilityAdmissionPort,
        data_rights: DataRightsEffectGate,
        expression: ExpressionResponseAdmissionPort,
    ) -> None:
        self._artifacts = artifacts
        self._capability = capability
        self._data_rights = data_rights
        self._expression = expression

    async def settle_current_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
    ) -> None:
        if work.lease is not None:
            await unit_of_work.work.fail(
                work.lease,
                error_code="RESPONSE-ADMISSION-STATE",
            )

    async def fail_current_work(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
        *,
        code: str,
    ) -> None:
        if work.lease is not None:
            await unit_of_work.work.fail(work.lease, error_code=code)

    async def snapshot(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        work: WorkRecord,
    ) -> ResponseAdmissionSnapshot:
        intent = await self._expression.response_admission_snapshot(
            unit_of_work.transaction,
            work=work,
        )
        if (
            intent.response_artifact_id is None
            or intent.response_digest is None
            or intent.response_bytes is None
        ):
            raise ResponseViolation("RESPONSE-ARTIFACT-INTEGRITY")
        artifact = await self._artifacts.retained_ref_in(
            unit_of_work.transaction,
            ArtifactId(intent.response_artifact_id),
        )
        if artifact is None or artifact.content_digest != intent.response_digest:
            raise ResponseViolation("RESPONSE-ARTIFACT-INTEGRITY")
        return ResponseAdmissionSnapshot(
            intent.operation_ref,
            intent.action_intent_id,
            intent.subject_id,
            intent.scene_id,
            intent.context_party_id,
            artifact,
            intent.response_digest,
            intent.response_bytes,
            work.draft.trace_id,
        )

    async def settle(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        work: WorkRecord,
        snapshot: ResponseAdmissionSnapshot,
        integrity_ok: bool,
    ) -> ResponseAdmissionResult:
        lease = work.lease
        if lease is None or unit_of_work.runtime_fence is None:
            raise ResponseViolation("RESPONSE-FENCE")
        current = await self._expression.response_admission_snapshot(
            unit_of_work.transaction,
            work=work,
        )
        if current.operation_ref != snapshot.operation_ref:
            raise ResponseViolation("RESPONSE-WORK-STALE")
        if not integrity_ok:
            status = ResponseAdmissionStatus.FAILED
            grant_id = None
            reason = "RESPONSE-ARTIFACT-INTEGRITY"
        elif await self._data_rights.blocks_effect(
            unit_of_work,
            requester_party_id=snapshot.creator_party_id,
        ):
            status = ResponseAdmissionStatus.UNAUTHORIZED
            grant_id = None
            reason = "DATA-RIGHTS-BLOCKED"
        else:
            admission = await self._capability.preflight(
                unit_of_work.transaction,
                CapabilityAdmissionRequest(
                    "creator.scene.reply",
                    "send",
                    snapshot.subject_id,
                    snapshot.scene_id,
                    snapshot.creator_party_id,
                    "respond_to_creator",
                    snapshot.content_bytes,
                    "creator_response",
                ),
            )
            grant_id = admission.grant_id
            reason = (
                None
                if admission.outcome is CapabilityAuthorizationOutcome.ALLOWED
                else admission.reason_code
            )
            status = (
                ResponseAdmissionStatus.ACCEPTED
                if admission.outcome is CapabilityAuthorizationOutcome.ALLOWED
                else ResponseAdmissionStatus.UNAVAILABLE
                if admission.outcome is CapabilityAuthorizationOutcome.UNAVAILABLE
                else ResponseAdmissionStatus.UNAUTHORIZED
            )
        digest = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "schema_version": "armi.creator-response.v1",
                    "operation_ref": str(snapshot.operation_ref),
                    "action_intent_id": str(snapshot.action_intent_id),
                    "content_digest": snapshot.content_digest.value,
                    "status": status.value,
                    "grant_ref": None if grant_id is None else str(grant_id),
                    "reason_code": reason,
                    "delivery_state": "not_started",
                }
            )
        )
        if status is ResponseAdmissionStatus.ACCEPTED:
            now = datetime.now(UTC)
            await unit_of_work.work.enqueue(
                WorkDraft(
                    WorkId(uuid7()),
                    "effect.register",
                    WorkOwner("action_intent", snapshot.action_intent_id),
                    IdempotencyKey(f"effect-register:{snapshot.action_intent_id}"),
                    digest,
                    60,
                    Instant(now),
                    Instant(now + timedelta(hours=1)),
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
        await unit_of_work.audit.append(
            AuditDraft(
                AuditEventId(uuid7()),
                AuditReference("runtime", unit_of_work.environment_id),
                Purpose("cognition.response"),
                "cognition.response.admitted",
                AuditReference("creator_response_operation", snapshot.operation_ref),
                {
                    ResponseAdmissionStatus.ACCEPTED: AuditResultStatus.ACCEPTED,
                    ResponseAdmissionStatus.UNAUTHORIZED: AuditResultStatus.REJECTED,
                    ResponseAdmissionStatus.UNAVAILABLE: AuditResultStatus.UNAVAILABLE,
                    ResponseAdmissionStatus.FAILED: AuditResultStatus.FAILED,
                }[status],
                snapshot.trace_id,
                AuditSensitivity.PRIVATE,
                subject_id=SubjectId(snapshot.subject_id),
                grant=(
                    None
                    if grant_id is None
                    else AuditReference("permission_grant", grant_id)
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


__all__ = ("PostgreSQLResponseAdmissionRepository", "ResponseAdmissionSnapshot")
