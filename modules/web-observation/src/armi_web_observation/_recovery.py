"""Web-observation-owned startup recovery contribution."""

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


class WebObservationRecoveryParticipant:
    owner_identity = RecoveryOwnerIdentity("web-observation")
    work_scopes = (
        ("web_observation", "web.search.invoke"),
        ("web_research_intent", "web.observation.admit"),
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
            await transaction.execute(
                """UPDATE armi.web_research_intents AS intent
                   SET status='unknown',completed_at=statement_timestamp()
                   FROM armi.web_observation_requests AS request
                   WHERE request.web_observation_request_id=ANY(%s::uuid[])
                     AND request.web_research_intent_id=intent.web_research_intent_id
                     AND intent.status='admitted'""",
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
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        unknown_by_work: dict[UUID, UUID] = {result[1]: result[0] for result in unknown}
        for item in work:
            if not item.reconciliation_required:
                continue
            request_id = unknown_by_work.get(item.work_id)
            if request_id is not None:
                await reconciliation.complete(
                    item.work_id,
                    result_kind="web_observation_request",
                    result_ref=request_id,
                )
                continue
            if item.work_kind == "web.search.invoke":
                await transaction.execute(
                    """UPDATE armi.web_observation_requests
                       SET status='failed',last_error_code='WEB-WORK-EXHAUSTED',
                           completed_at=statement_timestamp()
                       WHERE work_id=%s AND status IN ('pending','running')""",
                    (item.work_id,),
                )
                await transaction.execute(
                    """UPDATE armi.web_research_intents AS intent
                       SET status='failed',completed_at=statement_timestamp()
                       FROM armi.web_observation_requests AS request
                       WHERE request.work_id=%s
                         AND request.web_research_intent_id=intent.web_research_intent_id
                         AND intent.status='admitted'""",
                    (item.work_id,),
                )
            else:
                await transaction.execute(
                    """UPDATE armi.web_research_intents
                       SET status='failed',completed_at=statement_timestamp()
                       WHERE admission_work_id=%s AND status='pending'""",
                    (item.work_id,),
                )
            await reconciliation.fail(
                item.work_id, reason_code="REC-WEB-WORK-EXHAUSTED"
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
        )
