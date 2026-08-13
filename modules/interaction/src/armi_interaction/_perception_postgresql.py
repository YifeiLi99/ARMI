"""Interaction-owned persistence used by the Perception workflow."""

from __future__ import annotations

from uuid import UUID, uuid7

from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    ExternalContentPartSnapshot,
    ExternalFinalizationPart,
    ExternalFinalizationSnapshot,
    ExternalMessagePartKind,
    ExternalMessageViolation,
    ExternalRecognitionRecovery,
    ExternalRecognitionSnapshot,
    ExternalVisualRole,
)


class PostgreSQLInteractionPerception:
    async def recover_terminal(
        self,
        transaction: PostgreSQLTransaction,
        interaction_ids: tuple[UUID, ...],
    ) -> tuple[ExternalRecognitionRecovery, ...]:
        if not interaction_ids:
            return ()
        rows = await (
            await transaction.execute(
                """SELECT interaction_id,subject_id,trace_id
                   FROM armi.party_input_interactions
                   WHERE interaction_id=ANY(%s) AND recognition_status='pending'
                   FOR UPDATE""",
                (list(interaction_ids),),
            )
        ).fetchall()
        recovered: list[ExternalRecognitionRecovery] = []
        for interaction_id, subject_id, trace_id in rows:
            parts = await (
                await transaction.execute(
                    """UPDATE armi.external_message_parts
                       SET processing_status='unknown',
                           failure_code='EXTERNAL-MESSAGE-RECOGNITION-INTERRUPTED',
                           settled_at=statement_timestamp()
                       WHERE interaction_id=%s AND processing_status='pending'
                       RETURNING external_message_part_id""",
                    (interaction_id,),
                )
            ).fetchall()
            if parts:
                recovered.append(
                    ExternalRecognitionRecovery(
                        interaction_id,
                        subject_id,
                        TraceId(str(trace_id)),
                        tuple(part[0] for part in parts),
                    )
                )
        return tuple(recovered)

    async def recognition_snapshot(
        self, transaction: PostgreSQLTransaction, interaction_id: UUID
    ) -> ExternalRecognitionSnapshot:
        interaction = await (
            await transaction.execute(
                """SELECT input.interaction_id,input.subject_id,input.scene_id,
                          input.source_party_id,input.purpose,binding.channel_kind,
                          binding.account_key,input.trace_id
                   FROM armi.party_input_interactions AS input
                   JOIN armi.external_channel_bindings AS binding
                     ON binding.external_binding_id=input.external_binding_id
                   WHERE input.interaction_id=%s AND input.recognition_status='pending'""",
                (interaction_id,),
            )
        ).fetchone()
        if interaction is None:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
        rows = await (
            await transaction.execute(
                """SELECT external_message_part_id,ordinal,part_kind,
                          external_locator,declared_file_name,declared_media_type,
                          declared_byte_size,visual_role,source_kind,source_summary,
                          processing_status
                   FROM armi.external_message_parts
                   WHERE interaction_id=%s
                     AND part_kind IN ('image','audio','video','file')
                   ORDER BY ordinal""",
                (interaction_id,),
            )
        ).fetchall()
        return ExternalRecognitionSnapshot(
            interaction[0],
            interaction[1],
            interaction[2],
            interaction[3],
            str(interaction[4]),
            str(interaction[5]),
            str(interaction[6]),
            TraceId(str(interaction[7])),
            tuple(
                ExternalContentPartSnapshot(
                    row[0],
                    int(row[1]),
                    ExternalMessagePartKind(str(row[2])),
                    str(row[3]),
                    None if row[4] is None else str(row[4]),
                    None if row[5] is None else str(row[5]),
                    None if row[6] is None else int(row[6]),
                    None if row[7] is None else ExternalVisualRole(str(row[7])),
                    None if row[8] is None else str(row[8]),
                    None if row[9] is None else str(row[9]),
                    str(row[10]),
                )
                for row in rows
            ),
        )

    async def attach_raw(
        self, transaction: PostgreSQLTransaction, *, part_id: UUID, artifact_id: UUID
    ) -> None:
        result = await transaction.execute(
            """UPDATE armi.external_message_parts SET raw_artifact_id=%s
               WHERE external_message_part_id=%s AND processing_status='pending'""",
            (artifact_id, part_id),
        )
        if result.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")

    async def attach_visual_detection(
        self,
        transaction: PostgreSQLTransaction,
        *,
        part_id: UUID,
        media_type: str,
        pixel_width: int,
        pixel_height: int,
        frame_count: int,
    ) -> None:
        result = await transaction.execute(
            """UPDATE armi.external_message_parts
               SET detected_media_type=%s,pixel_width=%s,pixel_height=%s,frame_count=%s
               WHERE external_message_part_id=%s AND part_kind='image'
                 AND processing_status='pending'""",
            (media_type, pixel_width, pixel_height, frame_count, part_id),
        )
        if result.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")

    async def settle_part_success(
        self,
        transaction: PostgreSQLTransaction,
        *,
        part_id: UUID,
        raw_artifact_id: UUID,
        interpretation_artifact_id: UUID,
        interpretation_text: str,
    ) -> None:
        result = await transaction.execute(
            """UPDATE armi.external_message_parts
               SET processing_status='succeeded',raw_artifact_id=%s,
                   interpretation_artifact_id=%s,interpretation_text=%s,
                   settled_at=statement_timestamp()
               WHERE external_message_part_id=%s AND processing_status='pending'""",
            (raw_artifact_id, interpretation_artifact_id, interpretation_text, part_id),
        )
        if result.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")

    async def settle_part_failure(
        self,
        transaction: PostgreSQLTransaction,
        *,
        part_id: UUID,
        status: str,
        error_code: str,
    ) -> None:
        if status not in {"failed", "unknown"}:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-RECOGNITION")
        result = await transaction.execute(
            """UPDATE armi.external_message_parts
               SET processing_status=%s,failure_code=%s,settled_at=statement_timestamp()
               WHERE external_message_part_id=%s AND processing_status='pending'""",
            (status, error_code, part_id),
        )
        if result.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")

    async def has_pending_parts(
        self, transaction: PostgreSQLTransaction, interaction_id: UUID
    ) -> bool:
        row = await (
            await transaction.execute(
                """SELECT 1 FROM armi.external_message_parts
                   WHERE interaction_id=%s AND processing_status='pending' LIMIT 1""",
                (interaction_id,),
            )
        ).fetchone()
        return row is not None

    async def finalization_snapshot(
        self, transaction: PostgreSQLTransaction, interaction_id: UUID
    ) -> ExternalFinalizationSnapshot:
        row = await (
            await transaction.execute(
                """SELECT interaction_id,subject_id,scene_id,source_party_id,purpose,trace_id
                   FROM armi.party_input_interactions WHERE interaction_id=%s""",
                (interaction_id,),
            )
        ).fetchone()
        if row is None:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
        parts = await (
            await transaction.execute(
                """SELECT ordinal,part_kind,text_value,target_key,declared_file_name,
                          visual_role,source_kind,source_summary,detected_media_type,
                          pixel_width,pixel_height,frame_count,processing_status,
                          interpretation_text,failure_code
                   FROM armi.external_message_parts WHERE interaction_id=%s ORDER BY ordinal""",
                (interaction_id,),
            )
        ).fetchall()
        return ExternalFinalizationSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            str(row[4]),
            TraceId(str(row[5])),
            tuple(
                ExternalFinalizationPart(
                    int(part[0]),
                    ExternalMessagePartKind(str(part[1])),
                    None if part[2] is None else str(part[2]),
                    None if part[3] is None else str(part[3]),
                    None if part[4] is None else str(part[4]),
                    None if part[5] is None else ExternalVisualRole(str(part[5])),
                    None if part[6] is None else str(part[6]),
                    None if part[7] is None else str(part[7]),
                    None if part[8] is None else str(part[8]),
                    None if part[9] is None else int(part[9]),
                    None if part[10] is None else int(part[10]),
                    None if part[11] is None else int(part[11]),
                    str(part[12]),
                    None if part[13] is None else str(part[13]),
                    None if part[14] is None else str(part[14]),
                )
                for part in parts
            ),
        )

    async def complete_finalization(
        self,
        transaction: PostgreSQLTransaction,
        *,
        snapshot: ExternalFinalizationSnapshot,
        content_digest: Digest,
    ) -> None:
        statuses = {part.status for part in snapshot.parts}
        recognition_status = (
            "unknown"
            if "unknown" in statuses
            else "failed"
            if "failed" in statuses
            else "succeeded"
        )
        result = await transaction.execute(
            """UPDATE armi.party_input_interactions
               SET cognition_content_digest=%s,recognition_status=%s
               WHERE interaction_id=%s AND recognition_status='pending'""",
            (content_digest.value, recognition_status, snapshot.interaction_id),
        )
        if result.rowcount != 1:
            raise ExternalMessageViolation("EXTERNAL-MESSAGE-WORK-STALE")
        timeline_id = uuid7()
        source_kind = (
            "creator_input"
            if snapshot.purpose == "creator_message"
            else "other_human_input"
        )
        await transaction.execute(
            """INSERT INTO armi.scene_timeline_items
               (timeline_item_id,scene_id,source_kind,source_ref,source_event_no,
                result_status,occurred_at)
               VALUES (%s,%s,%s,%s,1,'accepted',statement_timestamp())""",
            (timeline_id, snapshot.scene_id, source_kind, snapshot.interaction_id),
        )
        await transaction.execute(
            """UPDATE armi.interaction_scenes
               SET recent_context_boundary=%s,scene_version=scene_version+1
               WHERE scene_id=%s AND current_status='open'""",
            (timeline_id, snapshot.scene_id),
        )


__all__ = ("PostgreSQLInteractionPerception",)
