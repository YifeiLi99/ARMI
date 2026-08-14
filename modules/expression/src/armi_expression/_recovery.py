"""Expression-owned startup recovery contribution."""

from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class ExpressionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("expression")
    work_scopes = (("action_intent", "effect.register"),)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        active = {
            item.owner_ref
            for item in work
            if item.status in {"ready", "leased", "completed"}
        }
        rows = await (
            await transaction.execute(
                """
            SELECT action_intent_id FROM armi.action_intents
            WHERE subject_id=%s AND current_revision_id IS NOT NULL
        """,
                (scope.subject_id,),
            )
        ).fetchall()
        missing = [row[0] for row in rows if row[0] not in active]
        return RecoveryContribution(
            self.owner_identity,
            metrics=(
                RecoveryMetricContribution(
                    "expression.intent_without_registration_work_count",
                    len(missing),
                ),
            ),
        )
