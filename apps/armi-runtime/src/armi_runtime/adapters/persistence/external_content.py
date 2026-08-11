"""Persistence custody for durable external content recognition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from armi_kernel.application import (
    ExternalContentRecognitionResult,
    ExternalMessagePartKind,
    ExternalMessageViolation,
    WorkDraft,
    WorkId,
    WorkLease,
    WorkOwner,
    WorkPayloadRef,
    WorkResultRef,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, SubjectId, TraceId

from .unit_of_work import PostgreSQLUnitOfWork


@dataclass(frozen=True, slots=True)
class ExternalContentPartSnapshot:
    part_id: UUID
    ordinal: int
    kind: ExternalMessagePartKind
    locator: str
    file_name: str | None
    media_type: str | None
    declared_byte_size: int | None
    status: str


@dataclass(frozen=True, slots=True)
class ExternalRecognitionSnapshot:
    interaction_id: UUID
    subject_id: UUID
    scene_id: UUID
    source_party_id: UUID
    purpose: str
    channel: str
    account_key: str
    trace_id: TraceId
    parts: tuple[ExternalContentPartSnapshot, ...]


@dataclass(frozen=True, slots=True)
class ExternalFinalizationPart:
    ordinal: int
    kind: ExternalMessagePartKind
    text_value: str | None
    target_key: str | None
    file_name: str | None
    status: str
    interpretation_text: str | None
    failure_code: str | None


@dataclass(frozen=True, slots=True)
class ExternalFinalizationSnapshot:
    interaction_id: UUID
    subject_id: UUID
    scene_id: UUID
    source_party_id: UUID
    purpose: str
    trace_id: TraceId
    existing_evidence_id: UUID | None
    parts: tuple[ExternalFinalizationPart, ...]


class PostgreSQLExternalContentRepository:
    __slots__ = ()

    async def recover_terminal_recognition(self, unit: PostgreSQLUnitOfWork) -> int:
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        rows = await (
            await connection.execute(
                """
                SELECT input.interaction_id, input.subject_id, input.trace_id
                FROM armi.party_input_interactions AS input
                JOIN armi.durable_work AS work
                  ON work.owner_kind = 'external_message'
                 AND work.owner_ref = input.interaction_id
                 AND work.work_kind = 'external.content.recognize'
                 AND work.status = 'failed'
                WHERE input.recognition_status = 'pending'
                  AND EXISTS (
                    SELECT 1 FROM armi.external_message_parts AS part
                    WHERE part.interaction_id = input.interaction_id
                      AND part.processing_status = 'pending'
                  )
                FOR UPDATE OF input
                """
            )
        ).fetchall()
        for interaction_id, subject_id, trace_id in rows:
            await connection.execute(
                """
                UPDATE armi.external_content_recognition_attempts AS attempt
                SET dispatch_status = 'settled', result_status = 'unknown',
                    error_code = 'EXTERNAL-MESSAGE-RECOGNITION-INTERRUPTED',
                    settled_at = statement_timestamp()
                FROM armi.external_message_parts AS part
                WHERE attempt.external_message_part_id = part.external_message_part_id
                  AND part.interaction_id = %s
                  AND attempt.dispatch_status = 'dispatched'
                """,
                (interaction_id,),
            )
            await connection.execute(
                """
                UPDATE armi.external_message_parts
                SET processing_status = 'unknown',
                    failure_code = 'EXTERNAL-MESSAGE-RECOGNITION-INTERRUPTED',
                    settled_at = statement_timestamp()
                WHERE interaction_id = %s AND processing_status = 'pending'
                """,
                (interaction_id,),
            )
            now = Instant(datetime.now(UTC))
            await unit.work.enqueue(
                WorkDraft(
                    WorkId(uuid7()),
                    "external.content.finalize",
                    WorkOwner("external_message", interaction_id),
                    IdempotencyKey(f"external-finalize:{interaction_id}"),
                    Digest.from_bytes(str(interaction_id).encode("ascii")),
                    80,
                    now,
                    Instant(now.value + timedelta(hours=1)),
                    3,
                    TraceId(str(trace_id)),
                    subject_id=SubjectId(subject_id),
                    payload=WorkPayloadRef("external_message", interaction_id),
                )
            )
        return len(rows)

    async def recognition_snapshot(
        self, unit: PostgreSQLUnitOfWork, lease: WorkLease
    ) -> ExternalRecognitionSnapshot:
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        interaction = await (
            await connection.execute(
                """
                SELECT input.interaction_id, input.subject_id, input.scene_id,
                       input.source_party_id, input.purpose, binding.channel_kind,
                       binding.account_key, input.trace_id
                FROM armi.durable_work AS work
                JOIN armi.party_input_interactions AS input
                  ON input.interaction_id = work.owner_ref
                JOIN armi.external_channel_bindings AS binding
                  ON binding.external_binding_id = input.external_binding_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'external.content.recognize'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                  AND input.recognition_status = 'pending'
                """,
                (lease.work_id.value, lease.attempt_id.value, lease.owner, lease.token),
            )
        ).fetchone()
        if interaction is None:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
        rows = await (
            await connection.execute(
                """
                SELECT external_message_part_id, ordinal, part_kind,
                       external_locator, declared_file_name, declared_media_type,
                       declared_byte_size, processing_status
                FROM armi.external_message_parts
                WHERE interaction_id = %s
                  AND part_kind IN ('image','audio','video','file')
                ORDER BY ordinal
                """,
                (interaction[0],),
            )
        ).fetchall()
        parts = tuple(
            ExternalContentPartSnapshot(
                row[0],
                int(row[1]),
                ExternalMessagePartKind(str(row[2])),
                str(row[3]),
                None if row[4] is None else str(row[4]),
                None if row[5] is None else str(row[5]),
                None if row[6] is None else int(row[6]),
                str(row[7]),
            )
            for row in rows
        )
        return ExternalRecognitionSnapshot(
            interaction[0],
            interaction[1],
            interaction[2],
            interaction[3],
            str(interaction[4]),
            str(interaction[5]),
            str(interaction[6]),
            TraceId(str(interaction[7])),
            parts,
        )

    async def attach_raw(
        self,
        unit: PostgreSQLUnitOfWork,
        *,
        part_id: UUID,
        raw_artifact_id: UUID,
    ) -> None:
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        updated = await connection.execute(
            """
            UPDATE armi.external_message_parts
            SET raw_artifact_id = %s
            WHERE external_message_part_id = %s AND processing_status = 'pending'
            """,
            (raw_artifact_id, part_id),
        )
        if updated.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")

    async def begin_attempt(
        self,
        unit: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        part_id: UUID,
        raw_artifact_id: UUID,
        request_artifact_id: UUID,
        provider: str,
        model_id: str,
    ) -> UUID:
        await self.attach_raw(unit, part_id=part_id, raw_artifact_id=raw_artifact_id)
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
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
        unit: PostgreSQLUnitOfWork,
        *,
        part_id: UUID,
        raw_artifact_id: UUID,
        interpretation_artifact_id: UUID,
        interpretation_text: str,
        attempt_id: UUID | None = None,
        response_artifact_id: UUID | None = None,
        result: ExternalContentRecognitionResult | None = None,
    ) -> None:
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        updated = await connection.execute(
            """
            UPDATE armi.external_message_parts
            SET processing_status = 'succeeded', raw_artifact_id = %s,
                interpretation_artifact_id = %s, interpretation_text = %s,
                settled_at = statement_timestamp()
            WHERE external_message_part_id = %s AND processing_status = 'pending'
            """,
            (raw_artifact_id, interpretation_artifact_id, interpretation_text, part_id),
        )
        if updated.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
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
        unit: PostgreSQLUnitOfWork,
        *,
        part_id: UUID,
        status: str,
        error_code: str,
        attempt_id: UUID | None = None,
        result: ExternalContentRecognitionResult | None = None,
    ) -> None:
        if status not in {"failed", "unknown"}:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-RECOGNITION")
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        updated = await connection.execute(
            """
            UPDATE armi.external_message_parts
            SET processing_status = %s, failure_code = %s,
                settled_at = statement_timestamp()
            WHERE external_message_part_id = %s AND processing_status = 'pending'
            """,
            (status, error_code, part_id),
        )
        if updated.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
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
        unit: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ExternalRecognitionSnapshot,
    ) -> None:
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        pending = await (
            await connection.execute(
                """
                SELECT 1 FROM armi.external_message_parts
                WHERE interaction_id = %s AND processing_status = 'pending'
                LIMIT 1
                """,
                (snapshot.interaction_id,),
            )
        ).fetchone()
        if pending is not None:
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

    async def requeue_finalization(
        self, unit: PostgreSQLUnitOfWork, lease: WorkLease
    ) -> bool:
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                UPDATE armi.durable_work
                SET status = CASE
                      WHEN attempt_count < max_attempts THEN 'ready'
                      ELSE 'failed'
                    END,
                    current_attempt_id = NULL, lease_owner = NULL,
                    lease_expires_at = NULL,
                    last_error_code = 'EXTERNAL-CONTENT-FINALIZATION',
                    updated_at = statement_timestamp()
                WHERE work_id = %s
                  AND work_kind = 'external.content.finalize'
                  AND status = 'leased'
                  AND current_attempt_id = %s
                  AND lease_owner = %s
                  AND lease_token = %s
                RETURNING status
                """,
                (lease.work_id.value, lease.attempt_id.value, lease.owner, lease.token),
            )
        ).fetchone()
        return row is not None and str(row[0]) == "ready"

    async def finalization_snapshot(
        self, unit: PostgreSQLUnitOfWork, lease: WorkLease
    ) -> ExternalFinalizationSnapshot:
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        row = await (
            await connection.execute(
                """
                SELECT input.interaction_id, input.subject_id, input.scene_id,
                       input.source_party_id, input.purpose, input.trace_id,
                       evidence.evidence_id
                FROM armi.durable_work AS work
                JOIN armi.party_input_interactions AS input
                  ON input.interaction_id = work.owner_ref
                LEFT JOIN armi.external_evidence AS evidence
                  ON evidence.interaction_id = input.interaction_id
                WHERE work.work_id = %s
                  AND work.work_kind = 'external.content.finalize'
                  AND work.status = 'leased'
                  AND work.current_attempt_id = %s
                  AND work.lease_owner = %s
                  AND work.lease_token = %s
                """,
                (lease.work_id.value, lease.attempt_id.value, lease.owner, lease.token),
            )
        ).fetchone()
        if row is None:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
        parts = await (
            await connection.execute(
                """
                SELECT ordinal, part_kind, text_value, target_key,
                       declared_file_name, processing_status,
                       interpretation_text, failure_code
                FROM armi.external_message_parts
                WHERE interaction_id = %s ORDER BY ordinal
                """,
                (row[0],),
            )
        ).fetchall()
        return ExternalFinalizationSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            str(row[4]),
            TraceId(str(row[5])),
            row[6],
            tuple(
                ExternalFinalizationPart(
                    int(part[0]),
                    ExternalMessagePartKind(str(part[1])),
                    None if part[2] is None else str(part[2]),
                    None if part[3] is None else str(part[3]),
                    None if part[4] is None else str(part[4]),
                    str(part[5]),
                    None if part[6] is None else str(part[6]),
                    None if part[7] is None else str(part[7]),
                )
                for part in parts
            ),
        )

    async def finalize(
        self,
        unit: PostgreSQLUnitOfWork,
        *,
        lease: WorkLease,
        snapshot: ExternalFinalizationSnapshot,
        artifact_id: UUID | None = None,
        content_digest: Digest | None = None,
    ) -> UUID:
        if snapshot.existing_evidence_id is not None:
            await unit.work.complete(
                lease, WorkResultRef("external_evidence", snapshot.existing_evidence_id)
            )
            return snapshot.existing_evidence_id
        if artifact_id is None or content_digest is None:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-FINALIZATION")
        connection = unit._connection_for_repository()  # pyright: ignore[reportPrivateUsage]
        statuses = {part.status for part in snapshot.parts}
        recognition_status = (
            "unknown"
            if "unknown" in statuses
            else "failed"
            if "failed" in statuses
            else "succeeded"
        )
        updated = await connection.execute(
            """
            UPDATE armi.party_input_interactions
            SET cognition_content_digest = %s, recognition_status = %s
            WHERE interaction_id = %s AND recognition_status = 'pending'
            """,
            (content_digest.value, recognition_status, snapshot.interaction_id),
        )
        if updated.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
        evidence_id, opportunity_id, timeline_id = uuid7(), uuid7(), uuid7()
        creator = snapshot.purpose == "creator_message"
        source_kind = "creator_input" if creator else "other_human_input"
        privacy = "creator_visible" if creator else "private"
        purpose = "consider_creator_input" if creator else "consider_other_human_input"
        await connection.execute(
            """
            INSERT INTO armi.external_evidence (
                evidence_id, interaction_id, subject_id, scene_id,
                context_party_id, artifact_id, source_kind, trust_status,
                privacy_scope, acceptance_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'external_claim',%s,'accepted')
            """,
            (
                evidence_id,
                snapshot.interaction_id,
                snapshot.subject_id,
                snapshot.scene_id,
                snapshot.source_party_id,
                artifact_id,
                source_kind,
                privacy,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.opportunities (
                opportunity_id, evidence_id, subject_id, scene_id,
                context_party_id, purpose, source_kind, source_ref,
                source_version, eligibility_status, current_disposition,
                root_opportunity_id, reconsideration_no)
            VALUES (%s,%s,%s,%s,%s,%s,'external_evidence',%s,1,
                    'eligible','open',%s,0)
            """,
            (
                opportunity_id,
                evidence_id,
                snapshot.subject_id,
                snapshot.scene_id,
                snapshot.source_party_id,
                purpose,
                evidence_id,
                opportunity_id,
            ),
        )
        await connection.execute(
            """
            INSERT INTO armi.scene_timeline_items (
                timeline_item_id, scene_id, source_kind, source_ref,
                source_event_no, result_status, occurred_at)
            VALUES (%s,%s,%s,%s,1,'accepted',statement_timestamp())
            """,
            (timeline_id, snapshot.scene_id, source_kind, snapshot.interaction_id),
        )
        await connection.execute(
            """
            UPDATE armi.interaction_scenes
            SET recent_context_boundary = %s, scene_version = scene_version + 1
            WHERE scene_id = %s AND current_status = 'open'
            """,
            (timeline_id, snapshot.scene_id),
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
