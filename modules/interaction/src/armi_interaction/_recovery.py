"""Interaction-owned startup recovery contribution."""

from armi_runtime_foundation import (
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
    work_scopes: tuple[tuple[str, str], ...] = ()

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del work
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
