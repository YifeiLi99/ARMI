"""Interaction-owned startup recovery contribution."""

from uuid import UUID

from armi_runtime_foundation import (
    OwnerReconciliationContext,
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class InteractionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("interaction")
    work_scopes = (("external_message", "external.content.finalize"),)

    async def end_interrupted_work(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        await transaction.execute(
            """UPDATE armi.interaction_scenes
               SET last_voice_ended_at=statement_timestamp(),
                   voice_provider_calls=(
                     SELECT jsonb_object_agg(key, CASE WHEN value->>'outcome'='pending'
                       THEN value || jsonb_build_object('outcome','unknown',
                            'finished_at',statement_timestamp(),
                            'error_code','VOICE-RUNTIME-RESTARTED')
                       ELSE value END)
                     FROM jsonb_each(voice_provider_calls))
               WHERE subject_id=%s AND EXISTS (
                 SELECT 1 FROM jsonb_each(voice_provider_calls)
                 WHERE value->>'outcome'='pending')""",
            (scope.subject_id,),
        )
        rows = await (
            await transaction.execute(
                """UPDATE armi.party_input_interactions SET recognition_status='failed'
                   WHERE subject_id=%s AND purpose='creator_message'
                     AND recognition_status='pending' RETURNING interaction_id""",
                (scope.subject_id,),
            )
        ).fetchall()
        input_ids: list[UUID] = [row[0] for row in rows]
        await transaction.execute(
            """UPDATE armi.external_message_parts SET processing_status=CASE WHEN recognition_request_artifact_id IS NULL THEN 'failed' ELSE 'unknown' END,
                   failure_code='RECOGNITION-RUNTIME-INTERRUPTED',settled_at=statement_timestamp()
               WHERE interaction_id=ANY(%s::uuid[]) AND processing_status='pending'""",
            (input_ids,),
        )
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        for item in work:
            if item.owner_ref in input_ids and item.status in {"ready", "leased"}:
                await reconciliation.cancel(
                    item.work_id, reason_code="REC-CONVERSATION-INTERRUPTED"
                )

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        await self.end_interrupted_work(transaction, scope, work)
        row = await (
            await transaction.execute(
                """
            SELECT count(*) FROM armi.interaction_scenes AS scene
            JOIN armi.parties AS creator ON creator.party_id=scene.primary_party_id
            WHERE scene.subject_id=%s AND scene.scene_key='default'
              AND scene.scene_kind='creator_dialogue' AND scene.current_status='open'
              AND creator.party_kind='creator' AND creator.status='active'
        """,
                (scope.subject_id,),
            )
        ).fetchone()
        count = 0 if row is None else int(row[0])
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if count == 1
            else (
                RecoveryFindingContribution(
                    "creator_scene",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-INTERACTION-INVALID",
                ),
            ),
            metrics=(
                RecoveryMetricContribution("interaction.creator_scene_count", count),
            ),
        )
