"""Persistence custody for durable external content recognition."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from armi_attention.api import (
    ExternalEvidenceOpportunityDraft,
    OpportunityAdmissionPort,
    OpportunityAdmissionStatus,
    OpportunityPurpose,
)
from armi_evidence.api import (
    EvidenceDraft,
    EvidenceId,
    EvidencePrivacyScope,
    EvidenceReadPort,
    EvidenceSourceKind,
    EvidenceWritePort,
)
from armi_interaction.api import (
    ExternalContentPartSnapshot,
    ExternalFinalizationPart,
    ExternalFinalizationSnapshot,
    ExternalMessageViolation,
    ExternalRecognitionSnapshot,
    InteractionPerceptionPort,
)
from armi_kernel.application import (
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import ExternalContentRecognitionResult


class PostgreSQLExternalContentRepository:
    __slots__ = ("_evidence", "_evidence_read", "_interaction", "_opportunity")

    def __init__(
        self,
        evidence: EvidenceWritePort,
        evidence_read: EvidenceReadPort,
        opportunity: OpportunityAdmissionPort,
        interaction: InteractionPerceptionPort,
    ) -> None:
        self._evidence = evidence
        self._evidence_read = evidence_read
        self._opportunity = opportunity
        self._interaction = interaction

    async def recover_terminal_recognition(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        interaction_ids: tuple[UUID, ...],
    ) -> int:
        connection = unit.transaction
        rows = await self._interaction.recover_terminal(connection, interaction_ids)
        for recovered in rows:
            await connection.execute(
                """UPDATE armi.external_content_recognition_attempts
                   SET dispatch_status='settled',result_status='unknown',
                       error_code='EXTERNAL-MESSAGE-RECOGNITION-INTERRUPTED',
                       settled_at=statement_timestamp()
                   WHERE external_message_part_id=ANY(%s)
                     AND dispatch_status='dispatched'""",
                (recovered.part_ids,),
            )
            now = Instant(datetime.now(UTC))
            await unit.work.enqueue(
                WorkDraft(
                    WorkId(uuid7()),
                    "external.content.finalize",
                    WorkOwner("external_message", recovered.interaction_id),
                    IdempotencyKey(f"external-finalize:{recovered.interaction_id}"),
                    Digest.from_bytes(str(recovered.interaction_id).encode("ascii")),
                    80,
                    now,
                    Instant(now.value + timedelta(hours=1)),
                    3,
                    recovered.trace_id,
                    subject_id=SubjectId(recovered.subject_id),
                    payload=WorkPayloadRef(
                        "external_message", recovered.interaction_id
                    ),
                )
            )
        return len(rows)

    async def recognition_snapshot(
        self, unit: PostgreSQLRuntimeUnitOfWork, interaction_id: UUID
    ) -> ExternalRecognitionSnapshot:
        return await self._interaction.recognition_snapshot(
            unit.transaction, interaction_id
        )

    async def attach_raw(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        part_id: UUID,
        raw_artifact_id: UUID,
    ) -> None:
        await self._interaction.attach_raw(
            unit.transaction, part_id=part_id, artifact_id=raw_artifact_id
        )

    async def attach_visual_detection(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        part_id: UUID,
        media_type: str,
        pixel_width: int,
        pixel_height: int,
        frame_count: int,
    ) -> None:
        await self._interaction.attach_visual_detection(
            unit.transaction,
            part_id=part_id,
            media_type=media_type,
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            frame_count=frame_count,
        )

    async def begin_attempt(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        part_id: UUID,
        raw_artifact_id: UUID,
        request_artifact_id: UUID,
        provider: str,
        model_id: str,
    ) -> UUID:
        await self.attach_raw(unit, part_id=part_id, raw_artifact_id=raw_artifact_id)
        connection = unit.transaction
        attempt_id = uuid7()
        inserted = await connection.execute(
            """
            INSERT INTO armi.external_content_recognition_attempts (
                recognition_attempt_id, external_message_part_id, work_id,
                work_attempt_id, provider, model_id, request_artifact_id,
                dispatch_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'dispatched')
            ON CONFLICT (external_message_part_id) DO NOTHING
            """,
            (
                attempt_id,
                part_id,
                lease.work_id.value,
                lease.attempt_id.value,
                provider,
                model_id,
                request_artifact_id,
            ),
        )
        if inserted.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-ATTEMPT-EXISTS")
        return attempt_id

    async def settle_success(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        part_id: UUID,
        raw_artifact_id: UUID,
        interpretation_artifact_id: UUID,
        interpretation_text: str,
        attempt_id: UUID | None = None,
        response_artifact_id: UUID | None = None,
        result: ExternalContentRecognitionResult | None = None,
    ) -> None:
        connection = unit.transaction
        await self._interaction.settle_part_success(
            connection,
            part_id=part_id,
            raw_artifact_id=raw_artifact_id,
            interpretation_artifact_id=interpretation_artifact_id,
            interpretation_text=interpretation_text,
        )
        if attempt_id is not None:
            assert result is not None and response_artifact_id is not None
            settled = await connection.execute(
                """
                UPDATE armi.external_content_recognition_attempts
                SET dispatch_status = 'settled', provider_request_id = %s,
                    provider_model_id = %s, response_artifact_id = %s,
                    input_tokens = %s, output_tokens = %s,
                    result_status = 'succeeded', settled_at = statement_timestamp()
                WHERE recognition_attempt_id = %s AND dispatch_status = 'dispatched'
                """,
                (
                    result.provider_request_id,
                    result.response_model_id,
                    response_artifact_id,
                    result.input_tokens,
                    result.output_tokens,
                    attempt_id,
                ),
            )
            if settled.rowcount != 1:
                raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")

    async def settle_failure(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        part_id: UUID,
        status: str,
        error_code: str,
        attempt_id: UUID | None = None,
        result: ExternalContentRecognitionResult | None = None,
    ) -> None:
        if status not in {"failed", "unknown"}:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-RECOGNITION")
        connection = unit.transaction
        await self._interaction.settle_part_failure(
            connection, part_id=part_id, status=status, error_code=error_code
        )
        if attempt_id is not None:
            settled = await connection.execute(
                """
                UPDATE armi.external_content_recognition_attempts
                SET dispatch_status = 'settled', provider_request_id = %s,
                    provider_model_id = %s, input_tokens = %s, output_tokens = %s,
                    result_status = %s, error_code = %s,
                    settled_at = statement_timestamp()
                WHERE recognition_attempt_id = %s AND dispatch_status = 'dispatched'
                """,
                (
                    None if result is None else result.provider_request_id,
                    None if result is None else result.response_model_id,
                    None if result is None else result.input_tokens,
                    None if result is None else result.output_tokens,
                    status,
                    error_code,
                    attempt_id,
                ),
            )
            if settled.rowcount != 1:
                raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")

    async def finish_recognition(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ExternalRecognitionSnapshot,
    ) -> None:
        connection = unit.transaction
        if await self._interaction.has_pending_parts(
            connection, snapshot.interaction_id
        ):
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-PARTS-PENDING")
        now = Instant(datetime.now(UTC))
        await unit.work.enqueue(
            WorkDraft(
                WorkId(uuid7()),
                "external.content.finalize",
                WorkOwner("external_message", snapshot.interaction_id),
                IdempotencyKey(f"external-finalize:{snapshot.interaction_id}"),
                Digest.from_bytes(str(snapshot.interaction_id).encode("ascii")),
                80,
                now,
                Instant(now.value + timedelta(hours=1)),
                3,
                snapshot.trace_id,
                subject_id=SubjectId(snapshot.subject_id),
                payload=WorkPayloadRef("external_message", snapshot.interaction_id),
            )
        )
        await unit.work.complete(
            lease, WorkResultRef("external_message", snapshot.interaction_id)
        )

    async def finalization_snapshot(
        self, unit: PostgreSQLRuntimeUnitOfWork, interaction_id: UUID
    ) -> ExternalFinalizationSnapshot:
        return await self._interaction.finalization_snapshot(
            unit.transaction, interaction_id
        )

    async def existing_evidence(
        self, unit: PostgreSQLRuntimeUnitOfWork, interaction_id: UUID
    ) -> UUID | None:
        result = await self._evidence_read.find_by_interaction(
            unit, interaction_id=interaction_id
        )
        return None if result is None else result.value

    async def finalize(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ExternalFinalizationSnapshot,
        artifact_id: UUID | None = None,
        content_digest: Digest | None = None,
    ) -> UUID:
        if artifact_id is None or content_digest is None:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-FINALIZATION")
        connection = unit.transaction
        evidence_id = uuid7()
        creator = snapshot.purpose == "creator_message"
        await self._evidence.accept(
            unit,
            EvidenceDraft(
                evidence_id=EvidenceId(evidence_id),
                subject_id=snapshot.subject_id,
                scene_id=snapshot.scene_id,
                context_party_id=snapshot.source_party_id,
                artifact_id=artifact_id,
                source_kind=(
                    EvidenceSourceKind.CREATOR_INPUT
                    if creator
                    else EvidenceSourceKind.OTHER_HUMAN_INPUT
                ),
                privacy_scope=(
                    EvidencePrivacyScope.CREATOR_VISIBLE
                    if creator
                    else EvidencePrivacyScope.PRIVATE
                ),
                interaction_id=snapshot.interaction_id,
            ),
        )
        admitted = await self._opportunity.admit_external_evidence(
            connection,
            ExternalEvidenceOpportunityDraft(
                evidence_id=evidence_id,
                subject_id=snapshot.subject_id,
                scene_id=snapshot.scene_id,
                context_party_id=snapshot.source_party_id,
                purpose=(
                    OpportunityPurpose.CONSIDER_CREATOR_INPUT
                    if creator
                    else OpportunityPurpose.CONSIDER_OTHER_HUMAN_INPUT
                ),
            ),
        )
        if admitted.status is OpportunityAdmissionStatus.REJECTED:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-FINALIZATION")
        await self._interaction.complete_finalization(
            connection, snapshot=snapshot, content_digest=content_digest
        )
        await unit.work.complete(lease, WorkResultRef("external_evidence", evidence_id))
        return evidence_id


__all__ = (
    "ExternalContentPartSnapshot",
    "ExternalFinalizationPart",
    "ExternalFinalizationSnapshot",
    "ExternalRecognitionSnapshot",
    "PostgreSQLExternalContentRepository",
)
