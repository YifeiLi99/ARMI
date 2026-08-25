"""Cognition-owned startup repair and recovery metrics."""

from uuid import UUID

from armi_attention.api import OpportunityCognitionPort
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


class CognitionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("cognition")
    work_scopes = (
        ("cognitive_episode", "cognition.context.prepare"),
        ("cognitive_episode", "cognition.model.invoke"),
        ("cognitive_episode", "cognition.candidate.validate"),
        ("cognitive_episode", "cognition.subject.commit"),
        ("exact_life_query_intent", "life.query.execute"),
    )

    def __init__(self, opportunity: OpportunityCognitionPort) -> None:
        self._opportunity = opportunity

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope
        by_scope: dict[tuple[object, str], list[RecoveryWorkSnapshot]] = {}
        for item in work:
            by_scope.setdefault((item.owner_ref, item.work_kind), []).append(item)
        await transaction.execute(
            """
            UPDATE armi.cognitive_attempts SET dispatch_status='settled',
                result_status='cancelled', error_code='MODEL-RECOVERY-PRE-DISPATCH',
                settled_at=statement_timestamp()
            WHERE dispatch_status='prepared' AND work_id=ANY(%s::uuid[])
        """,
            ([item.work_id for item in work if item.status == "ready"],),
        )
        unknown = await (
            await transaction.execute("""
            UPDATE armi.cognitive_attempts SET dispatch_status='settled',
                result_status='outcome_unknown', error_code='MODEL-OUTCOME-UNKNOWN',
                settled_at=statement_timestamp()
            WHERE dispatch_status='dispatched'
            RETURNING cognitive_episode_id,work_id
        """)
        ).fetchall()
        if unknown:
            await transaction.execute(
                """
                UPDATE armi.cognitive_episodes SET status='failed',
                    failure_code='MODEL-OUTCOME-UNKNOWN'
                WHERE cognitive_episode_id=ANY(%s::uuid[]) AND status='calling_model'
            """,
                ([row[0] for row in unknown],),
            )
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        unknown_work: set[UUID] = {row[1] for row in unknown}
        for item in work:
            if not item.reconciliation_required:
                continue
            if item.work_kind == "life.query.execute":
                await transaction.execute(
                    """UPDATE armi.exact_life_query_intents
                       SET status='failed',result_count=0,
                           failure_code='LIFE-QUERY-WORK-EXHAUSTED',
                           completed_at=statement_timestamp()
                       WHERE execution_work_id=%s AND status='pending'""",
                    (item.work_id,),
                )
                await reconciliation.fail(
                    item.work_id,
                    reason_code="REC-LIFE-QUERY-WORK-EXHAUSTED",
                )
                continue
            if item.work_id in unknown_work:
                await reconciliation.complete(
                    item.work_id,
                    result_kind="cognitive_episode",
                    result_ref=item.owner_ref,
                )
                continue
            if item.work_kind == "cognition.subject.commit":
                commit = await (
                    await transaction.execute(
                        """SELECT subject_commit_id
                           FROM armi.cognitive_candidate_applications
                           WHERE cognitive_episode_id=%s
                             AND subject_commit_id IS NOT NULL
                           ORDER BY decided_at DESC LIMIT 1""",
                        (item.owner_ref,),
                    )
                ).fetchone()
                if commit is not None:
                    await reconciliation.complete(
                        item.work_id,
                        result_kind="subject_commit",
                        result_ref=commit[0],
                    )
                    continue
            await transaction.execute(
                """UPDATE armi.cognitive_episodes
                   SET status='failed',failure_code='COGNITION-WORK-EXHAUSTED'
                   WHERE cognitive_episode_id=%s
                     AND status NOT IN ('completed','failed','stale',
                                        'candidate_rejected','cancelled')""",
                (item.owner_ref,),
            )
            episode = await (
                await transaction.execute(
                    """SELECT opportunity_id FROM armi.cognitive_episodes
                       WHERE cognitive_episode_id=%s""",
                    (item.owner_ref,),
                )
            ).fetchone()
            if episode is not None:
                await self._opportunity.resolve_cognition_failure(
                    transaction, opportunity_id=episode[0]
                )
            await reconciliation.fail(
                item.work_id, reason_code="REC-COGNITION-WORK-EXHAUSTED"
            )
        exhausted_model_episodes = [
            item.owner_ref
            for item in work
            if item.work_kind == "cognition.model.invoke"
            and item.status == "failed"
            and item.attempt_count >= item.max_attempts
        ]
        if exhausted_model_episodes:
            await transaction.execute(
                """UPDATE armi.cognitive_episodes
                   SET status='failed',
                       failure_code='MODEL-WORK-ATTEMPTS-EXHAUSTED'
                   WHERE cognitive_episode_id=ANY(%s::uuid[])
                     AND status IN ('prepared','calling_model')""",
                (exhausted_model_episodes,),
            )
        terminal_opportunities = await (
            await transaction.execute(
                """
                SELECT opportunity_id, status
                FROM armi.cognitive_episodes
                WHERE status IN ('candidate_rejected', 'failed', 'cancelled')
                ORDER BY opportunity_id
                """
            )
        ).fetchall()
        rows = await (
            await transaction.execute("""
            SELECT cognitive_episode_id, status FROM armi.cognitive_episodes
            WHERE status NOT IN ('completed','failed','stale','candidate_rejected','cancelled')
        """)
        ).fetchall()
        expected_kind = {
            "preparing": "cognition.context.prepare",
            "prepared": "cognition.model.invoke",
            "calling_model": "cognition.model.invoke",
            "model_returned": "cognition.candidate.validate",
            "validating": "cognition.candidate.validate",
            "candidate_validated": "cognition.subject.commit",
            "committing": "cognition.subject.commit",
        }
        invalid = [
            row[0]
            for row in rows
            if not any(
                item.status in {"ready", "leased"}
                for item in by_scope.get(
                    (row[0], expected_kind.get(str(row[1]), "")), ()
                )
            )
        ]
        terminal_findings = tuple(
            RecoveryFindingContribution(
                (
                    "opportunity_terminal_cancelled"
                    if str(status) == "cancelled"
                    else "opportunity_terminal_resolved"
                ),
                RecoveryFindingDecision.TERMINAL,
                (
                    "REC-COGNITION-OPPORTUNITY-CANCELLED"
                    if str(status) == "cancelled"
                    else "REC-COGNITION-OPPORTUNITY-RESOLVED"
                ),
                opportunity_id,
            )
            for opportunity_id, status in terminal_opportunities
        )
        blocker_findings = (
            ()
            if not invalid and not unknown
            else (
                RecoveryFindingContribution(
                    "cognitive_episode",
                    RecoveryFindingDecision.BLOCKED,
                    (
                        "REC-COGNITION-INVALID"
                        if invalid
                        else "REC-COGNITION-OUTCOME-UNKNOWN"
                    ),
                    invalid[0] if invalid else unknown[0][0],
                ),
            )
        )
        return RecoveryContribution(
            self.owner_identity,
            findings=(*terminal_findings, *blocker_findings),
            metrics=(
                RecoveryMetricContribution(
                    "cognition.resumable_episode_count", len(rows)
                ),
                RecoveryMetricContribution(
                    "cognition.unknown_attempt_count", len(unknown)
                ),
            ),
        )
