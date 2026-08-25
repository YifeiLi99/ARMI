"""Expression-owned startup recovery contribution."""

from armi_runtime_foundation import (
    OwnerReconciliationContext,
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class ExpressionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("expression")
    work_scopes = (("action_intent", "cognition.response.admit"),)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        for item in work:
            if not item.reconciliation_required:
                continue
            row = await (
                await transaction.execute(
                    """SELECT response_admission_id,operation_ref,status
                       FROM armi.response_admissions WHERE work_id=%s FOR UPDATE""",
                    (item.work_id,),
                )
            ).fetchone()
            if row is None:
                raise ValueError("response admission responsibility is missing")
            if str(row[2]) == "pending":
                await transaction.execute(
                    """UPDATE armi.response_admissions
                       SET status='failed',reason_code='RESPONSE-WORK-EXHAUSTED',
                           attempt_count=attempt_count+1,
                           settled_at=statement_timestamp()
                       WHERE response_admission_id=%s""",
                    (row[0],),
                )
                await reconciliation.fail(
                    item.work_id,
                    reason_code="REC-RESPONSE-WORK-EXHAUSTED",
                )
            else:
                await reconciliation.complete(
                    item.work_id,
                    result_kind="creator_response_operation",
                    result_ref=row[1],
                )
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
              AND purpose='respond_to_creator'
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
