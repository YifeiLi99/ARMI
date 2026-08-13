"""Web-observation-owned startup recovery contribution."""

from armi_runtime_foundation import (
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryFindingContribution,
    RecoveryFindingDecision,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
    RecoveryWorkCommand,
    RecoveryWorkCommandKind,
    RecoveryWorkSnapshot,
)


class WebObservationRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("web-observation")
    work_scopes = (
        ("web_observation", "web.search.invoke"),
        ("web_research_intent", "web.research.admit"),
    )

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        ready_ids = [item.work_id for item in work if item.status == "ready"]
        await transaction.execute(
            """
            UPDATE armi.observation_attempts SET dispatch_state='settled',
                result_status='cancelled', error_code='WEB-RECOVERY-PRE-DISPATCH',
                settled_at=statement_timestamp()
            WHERE dispatch_state='prepared' AND work_id=ANY(%s::uuid[])
        """,
            (ready_ids,),
        )
        unknown = await (
            await transaction.execute("""
            UPDATE armi.observation_attempts SET dispatch_state='settled',
                result_status='outcome_unknown',
                error_code='WEB-RECOVERY-OUTCOME-UNKNOWN',
                settled_at=statement_timestamp()
            WHERE dispatch_state='dispatched'
            RETURNING web_observation_request_id, work_id
        """)
        ).fetchall()
        if unknown:
            await transaction.execute(
                """
                UPDATE armi.web_observation_requests SET status='unknown',
                    last_error_code='WEB-RECOVERY-OUTCOME-UNKNOWN',
                    completed_at=statement_timestamp()
                WHERE web_observation_request_id=ANY(%s::uuid[])
                  AND status IN ('pending','running')
            """,
                ([row[0] for row in unknown],),
            )
        row = await (
            await transaction.execute(
                """
            SELECT count(*) FROM armi.web_observation_requests
            WHERE subject_id=%s AND status IN ('pending','running')
        """,
                (scope.subject_id,),
            )
        ).fetchone()
        by_id = {item.work_id: item for item in work}
        commands = tuple(
            RecoveryWorkCommand(
                RecoveryWorkCommandKind.FAIL,
                item.work_id,
                item.work_kind,
                item.owner_kind,
                item.owner_ref,
                "REC-WEB-OUTCOME-UNKNOWN",
            )
            for result in unknown
            if (item := by_id.get(result[1])) is not None
            and item.status in {"ready", "leased"}
        )
        return RecoveryContribution(
            self.owner_identity,
            findings=()
            if not unknown
            else (
                RecoveryFindingContribution(
                    "observation_attempt",
                    RecoveryFindingDecision.BLOCKED,
                    "REC-WEB-OUTCOME-UNKNOWN",
                    unknown[0][0],
                ),
            ),
            metrics=(
                RecoveryMetricContribution(
                    "web_observation.resumable_request_count", int(row[0]) if row else 0
                ),
                RecoveryMetricContribution(
                    "web_observation.unknown_attempt_count", len(unknown)
                ),
            ),
            work_commands=commands,
        )
