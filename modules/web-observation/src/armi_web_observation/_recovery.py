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

    async def _end_conversations(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> set[UUID]:
        # Research intents are derived from Creator dialogue. Standalone Web
        # observations retain their own lifecycle.
        intents = await (
            await transaction.execute(
                """SELECT web_research_intent_id,admission_work_id
                   FROM armi.web_research_intents WHERE subject_id=%s
                     AND status IN ('pending','admitted')""",
                (scope.subject_id,),
            )
        ).fetchall()
        intent_ids = [row[0] for row in intents]
        requests = await (
            await transaction.execute(
                """SELECT web_observation_request_id,work_id
                   FROM armi.web_observation_requests
                   WHERE web_research_intent_id=ANY(%s::uuid[])
                     AND status IN ('pending','running')""",
                (intent_ids,),
            )
        ).fetchall()
        request_ids = [row[0] for row in requests]
        await transaction.execute(
            """UPDATE armi.observation_attempts
               SET dispatch_state='settled',result_status=CASE dispatch_state
                     WHEN 'prepared' THEN 'cancelled' ELSE 'outcome_unknown' END,
                   error_code='WEB-RUNTIME-INTERRUPTED',settled_at=statement_timestamp()
               WHERE web_observation_request_id=ANY(%s::uuid[])
                 AND dispatch_state IN ('prepared','dispatched')""",
            (request_ids,),
        )
        await transaction.execute(
            """UPDATE armi.web_observation_requests
               SET status='cancelled',last_error_code='WEB-RUNTIME-INTERRUPTED',
                   completed_at=statement_timestamp()
               WHERE web_observation_request_id=ANY(%s::uuid[])""",
            (request_ids,),
        )
        await transaction.execute(
            """UPDATE armi.web_research_intents
               SET status='cancelled',completed_at=statement_timestamp()
               WHERE web_research_intent_id=ANY(%s::uuid[])""",
            (intent_ids,),
        )
        work_ids: set[UUID] = {row[1] for row in (*intents, *requests)}
        reconciliation = OwnerReconciliationContext(
            transaction, self.owner_identity, work
        )
        for item in work:
            if item.work_id in work_ids and item.status in {"ready", "leased"}:
                await reconciliation.cancel(
                    item.work_id, reason_code="REC-CONVERSATION-INTERRUPTED"
                )

        return work_ids

    async def end_conversations(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        await self._end_conversations(transaction, scope, work)

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        cancelled = await self._end_conversations(transaction, scope, work)
        work = tuple(item for item in work if item.work_id not in cancelled)
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
