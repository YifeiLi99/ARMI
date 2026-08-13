"""Cognition-owned startup repair and recovery metrics."""

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


class CognitionRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("cognition")
    work_scopes = (
        ("cognitive_episode", "cognition.context.prepare"),
        ("cognitive_episode", "cognition.model.invoke"),
        ("cognitive_episode", "cognition.candidate.validate"),
        ("cognitive_episode", "cognition.subject.commit"),
    )

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del scope
        by_owner = {item.owner_ref: item for item in work}
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
            RETURNING cognitive_episode_id
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
            WHERE status NOT IN ('completed','failed','stale','candidate_rejected')
        """)
        ).fetchall()
        invalid = [row[0] for row in rows if row[0] not in by_owner]
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
