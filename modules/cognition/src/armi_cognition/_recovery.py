"""Cognition-owned startup repair and recovery metrics."""

from uuid import UUID

from armi_attention.api import OpportunityCognitionPort
from armi_runtime_foundation import (
    OwnerReconciliationContext,
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkSnapshot,
)


class CognitionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("cognition")
    work_scopes = (
        ("cognitive_episode", "cognition.context.prepare"),
        ("cognitive_episode", "cognition.execute"),
        ("exact_life_query_intent", "life.query.execute"),
    )

    def __init__(self, opportunity: OpportunityCognitionPort) -> None:
        self._opportunity = opportunity

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
        *,
        conversation_only: bool = False,
    ) -> RecoveryContribution:
        interrupted_opportunities = await self._opportunity.interrupt_conversations(
            transaction, subject_id=scope.subject_id
        )
        active = await (
            await transaction.execute(
                """SELECT cognitive_episode_id,opportunity_id FROM armi.cognitive_episodes
                   WHERE subject_id=%s
                     AND status NOT IN ('completed','failed','stale','candidate_rejected','cancelled')""",
                (scope.subject_id,),
            )
        ).fetchall()
        await self._opportunity.interrupt_cognition(
            transaction, opportunity_ids=tuple(row[1] for row in active)
        )
        episode_rows = await (
            await transaction.execute(
                """SELECT cognitive_episode_id FROM armi.cognitive_episodes
                   WHERE opportunity_id=ANY(%s::uuid[])""",
                (list(interrupted_opportunities),),
            )
        ).fetchall()
        interrupted_episodes: set[UUID] = {row[0] for row in (*episode_rows, *active)}
        await transaction.execute(
            """UPDATE armi.cognitive_attempts
               SET dispatch_status='settled',
                   result_status=CASE dispatch_status WHEN 'prepared' THEN 'cancelled'
                     ELSE 'outcome_unknown' END,
                   error_code='MODEL-RUNTIME-INTERRUPTED',settled_at=statement_timestamp()
               WHERE cognitive_episode_id=ANY(%s::uuid[])
                 AND dispatch_status IN ('prepared','dispatched')""",
            (list(interrupted_episodes),),
        )
        await transaction.execute(
            """UPDATE armi.cognitive_episodes
               SET status='cancelled',failure_code='COGNITION-RUNTIME-INTERRUPTED'
               WHERE cognitive_episode_id=ANY(%s::uuid[])
                 AND status NOT IN ('completed','failed','stale','candidate_rejected','cancelled')""",
            (list(interrupted_episodes),),
        )
        query_rows = await (
            await transaction.execute(
                """UPDATE armi.exact_life_query_intents
                   SET status='failed',result_count=0,
                       failure_code='LIFE-QUERY-RUNTIME-INTERRUPTED',
                       completed_at=statement_timestamp()
                   WHERE source_opportunity_id=ANY(%s::uuid[]) AND status='pending'
                   RETURNING execution_work_id""",
                (list(interrupted_opportunities),),
            )
        ).fetchall()
        interrupted_query_work: set[UUID] = {row[0] for row in query_rows}
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        interrupted_work = {
            item.work_id
            for item in work
            if item.status in {"ready", "leased"}
            and (
                item.owner_ref in interrupted_episodes
                or item.work_id in interrupted_query_work
            )
        }
        for work_id in interrupted_work:
            await reconciliation.cancel(
                work_id, reason_code="REC-CONVERSATION-INTERRUPTED"
            )
        # Other durable responsibilities keep their own lifecycle. Only exhausted
        # exact-query work needs Cognition-owned settlement here.
        if not conversation_only:
            for item in work:
                if (
                    item.work_kind == "life.query.execute"
                    and item.work_id not in interrupted_work
                    and item.reconciliation_required
                ):
                    await transaction.execute(
                        """UPDATE armi.exact_life_query_intents
                           SET status='failed',result_count=0,
                               failure_code='LIFE-QUERY-WORK-EXHAUSTED',
                               completed_at=statement_timestamp()
                           WHERE execution_work_id=%s AND status='pending'""",
                        (item.work_id,),
                    )
                    await reconciliation.fail(
                        item.work_id, reason_code="REC-LIFE-QUERY-WORK-EXHAUSTED"
                    )
        return RecoveryContribution(self.owner_identity)

    async def end_interrupted_work(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        await self.recover(transaction, scope, work, conversation_only=True)
