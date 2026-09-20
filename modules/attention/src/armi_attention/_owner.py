"""PostgreSQL owner ports for opportunity facts shared within a caller UoW."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from typing import cast
from uuid import UUID, uuid7

import rfc8785
from armi_kernel.application import ConsiderationSignal
from armi_runtime_foundation import PostgreSQLTransaction
from armi_sleep.api import (
    SleepOpportunityDraft,
    SleepOpportunityResult,
    SleepOpportunityState,
)

from ._autonomy_postgresql import PostgreSQLAutonomyOwner
from ._signals import freeze_signals, unconsumed_signals
from .api import (
    AutonomyPolicy,
    ExternalEvidenceOpportunityDraft,
    LifeQueryResultOpportunityDraft,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    OpportunityCognitionCandidate,
    OpportunityCognitionSelectionScope,
    OpportunityCommitSnapshot,
    OpportunityId,
    OpportunityOperationSnapshot,
    OpportunityPurpose,
    OpportunitySelectionCursor,
)


class PostgreSQLOpportunityOwner:
    async def unconsumed_signals(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        signals: tuple[ConsiderationSignal, ...],
    ) -> tuple[ConsiderationSignal, ...]:
        return await unconsumed_signals(
            transaction, subject_id=subject_id, signals=signals
        )

    async def freeze_signals(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        signals: tuple[ConsiderationSignal, ...],
        frozen_at: datetime,
    ) -> None:
        await freeze_signals(
            transaction,
            opportunity_id=opportunity_id,
            signals=signals,
            frozen_at=frozen_at,
        )

    def __init__(self, autonomy_policy: AutonomyPolicy | None = None) -> None:
        self._autonomy_policy = autonomy_policy or AutonomyPolicy()

    async def interrupt_cognition(
        self, transaction: PostgreSQLTransaction, *, opportunity_ids: tuple[UUID, ...]
    ) -> None:
        await transaction.execute(
            """UPDATE armi.opportunities
               SET current_disposition='cancelled',resolved_at=statement_timestamp(),
                   resolution_reason_code='REC-COGNITION-INTERRUPTED'
               WHERE opportunity_id=ANY(%s::uuid[])
                 AND current_disposition IN ('open','selected')""",
            (list(opportunity_ids),),
        )

    async def has_pending_human_input(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> bool:
        row = await (
            await transaction.execute(
                """SELECT EXISTS(SELECT 1 FROM armi.opportunities WHERE subject_id=%s
               AND purpose IN ('consider_creator_input','consider_creator_voice_input',
                               'consider_other_human_input','consider_codex_task')
               AND current_disposition IN ('open','selected') AND eligibility_status='eligible'
               AND available_after<=statement_timestamp())""",
                (subject_id,),
            )
        ).fetchone()
        return row is not None and bool(row[0])

    async def interrupt_autonomy(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> None:
        # Cancel queued decisions too: human input can arrive before an episode
        # exists. A later idle period creates a fresh check, never consumes this one.
        await transaction.execute(
            """UPDATE armi.opportunities SET current_disposition='cancelled',
                   resolved_at=statement_timestamp(),
                   resolution_reason_code='REC-COGNITION-INTERRUPTED'
               WHERE subject_id=%s AND source_kind='autonomy_plan'
                 AND current_disposition IN ('open','selected')""",
            (subject_id,),
        )
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET plan_version=plan_version+1,
                   opportunity_id=NULL,phase='waiting',idle_streak=0,failure_streak=0,
                   next_consideration_at=statement_timestamp()+interval '60 seconds',
                   updated_at=statement_timestamp()
               WHERE subject_id=%s AND opportunity_id IS NOT NULL AND phase<>'blocked'""",
            (subject_id,),
        )

    async def interrupt_conversations(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> tuple[UUID, ...]:
        rows = await (
            await transaction.execute(
                """SELECT item.opportunity_id
                   FROM armi.opportunities AS item
                   JOIN armi.opportunities AS root
                     ON root.opportunity_id=item.root_opportunity_id
                   WHERE root.subject_id=%s AND root.purpose IN (
                     'consider_creator_input','consider_creator_voice_input',
                     'consider_creator_outreach','consider_codex_task',
                     'consider_codex_result','consider_autonomy_check','consider_autonomous_life')""",
                (subject_id,),
            )
        ).fetchall()
        opportunity_ids = tuple(row[0] for row in rows)
        await transaction.execute(
            """UPDATE armi.opportunities
               SET current_disposition='cancelled',resolved_at=statement_timestamp(),
                   resolution_reason_code='REC-CONVERSATION-INTERRUPTED'
               WHERE opportunity_id=ANY(%s::uuid[])
                 AND current_disposition IN ('open','selected')""",
            (list(opportunity_ids),),
        )
        return opportunity_ids

    async def maintenance_work_state(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        source_ref: UUID,
        source_version: int,
        purpose: str,
    ) -> SleepOpportunityState | None:
        row = await (
            await transaction.execute(
                """SELECT opportunity_id,root_opportunity_id,
                          current_disposition,reconsideration_no
                   FROM armi.opportunities
                   WHERE subject_id=%s
                     AND source_kind='maintenance_phase_revision'
                     AND source_ref=%s AND source_version=%s AND purpose=%s
                   ORDER BY reconsideration_no DESC LIMIT 1""",
                (subject_id, source_ref, source_version, purpose),
            )
        ).fetchone()
        if row is None:
            return None
        return SleepOpportunityState(row[0], row[1], str(row[2]), int(row[3]))

    async def admit_sleep(
        self,
        transaction: PostgreSQLTransaction,
        draft: SleepOpportunityDraft,
    ) -> SleepOpportunityResult:
        opportunity_id = uuid7()
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id,evidence_id,subject_id,scene_id,context_party_id,
                    purpose,eligibility_status,current_disposition,root_opportunity_id,
                    predecessor_opportunity_id,reconsideration_no,available_after,
                    expires_at,source_kind,source_ref,source_version,activity_id)
                VALUES (%s,NULL,%s,NULL,NULL,%s,'eligible','open',%s,%s,%s,%s,%s,%s,%s,%s,NULL)
                ON CONFLICT (subject_id,source_kind,source_ref,source_version,purpose,reconsideration_no)
                DO NOTHING RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    draft.subject_id,
                    draft.purpose,
                    draft.root_id or opportunity_id,
                    draft.predecessor_id,
                    draft.reconsideration_no,
                    draft.available_after,
                    draft.expires_at,
                    draft.source_kind,
                    draft.source_ref,
                    draft.source_version,
                ),
            )
        ).fetchone()
        if row is not None:
            return SleepOpportunityResult(row[0], True)
        existing = await (
            await transaction.execute(
                """SELECT opportunity_id FROM armi.opportunities
                   WHERE subject_id=%s AND source_kind=%s AND source_ref=%s
                     AND source_version=%s AND purpose=%s AND reconsideration_no=%s""",
                (
                    draft.subject_id,
                    draft.source_kind,
                    draft.source_ref,
                    draft.source_version,
                    draft.purpose,
                    draft.reconsideration_no,
                ),
            )
        ).fetchone()
        return SleepOpportunityResult(None if existing is None else existing[0], False)

    async def cancel_sleep_source(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        source_kind: str,
        source_ref: UUID,
    ) -> None:
        await transaction.execute(
            """UPDATE armi.opportunities SET current_disposition='cancelled',
                      resolved_at=statement_timestamp(),
                      resolution_reason_code='SLEEP-SOURCE-CANCELLED'
               WHERE subject_id=%s AND source_kind=%s AND source_ref=%s
                 AND current_disposition IN ('open','selected')""",
            (subject_id, source_kind, source_ref),
        )

    async def next_candidate(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scope: OpportunityCognitionSelectionScope,
        after: OpportunitySelectionCursor | None = None,
    ) -> OpportunityCognitionCandidate | None:
        # Serialize autonomous selection with plan/request admission. The lock is
        # held only through Context-work registration, never through model I/O.
        await transaction.execute(
            "SELECT subject_id FROM armi.autonomy_plans WHERE subject_id=%s FOR UPDATE",
            (scope.subject_id,),
        )
        row = await (
            await transaction.execute(
                """
                SELECT opportunity_id, root_opportunity_id, evidence_id,
                       subject_id, scene_id, context_party_id, purpose,
                       source_kind, source_ref, source_version,
                       available_after, expires_at, activity_id
                FROM (
                    SELECT opportunities.*, CASE WHEN purpose IN (
                        'consider_creator_input','consider_creator_voice_input',
                        'consider_other_human_input','consider_codex_task'
                    ) THEN 0 ELSE 1 END AS selection_priority
                    FROM armi.opportunities
                ) AS candidates
                WHERE subject_id=%s AND eligibility_status='eligible'
                  AND current_disposition='open'
                  AND available_after <= transaction_timestamp()
                  AND (expires_at IS NULL OR expires_at > transaction_timestamp())
                  AND (%s::integer IS NULL OR
                       (selection_priority,available_after,opportunity_id) > (%s,%s,%s))
                  AND (%s::uuid IS NULL OR (
                       source_kind='maintenance_phase_revision'
                       AND source_ref=%s AND source_version=%s AND purpose=%s))
                ORDER BY selection_priority,available_after,opportunity_id
                FOR UPDATE SKIP LOCKED LIMIT 1
                """,
                (
                    scope.subject_id,
                    None if after is None else after.priority,
                    None if after is None else after.priority,
                    None if after is None else after.available_after,
                    None if after is None else after.opportunity_id,
                    scope.maintenance_source_ref,
                    scope.maintenance_source_ref,
                    scope.maintenance_source_version,
                    scope.maintenance_purpose,
                ),
            )
        ).fetchone()
        if row is None:
            return None
        return _cognition_candidate(row)

    async def can_consider_autonomy(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> bool:
        row = await (
            await transaction.execute(
                """SELECT (policy->>'enabled')::boolean
               FROM armi.autonomy_plans plan WHERE subject_id=%s""",
                (subject_id,),
            )
        ).fetchone()
        return row is not None and bool(row[0])

    async def context_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityCognitionCandidate:
        row = await (
            await transaction.execute(
                """SELECT o.opportunity_id, o.root_opportunity_id, o.evidence_id,
                          o.subject_id, o.scene_id, o.context_party_id, o.purpose,
                          o.source_kind, o.source_ref, o.source_version,
                          o.available_after, o.expires_at, COALESCE(o.activity_id,root.activity_id)
                   FROM armi.opportunities o JOIN armi.opportunities root
                     ON root.opportunity_id=o.root_opportunity_id
                   WHERE o.opportunity_id=%s""",
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        candidate = replace(
            _cognition_candidate(row),
            minimum_consideration_seconds=self._autonomy_policy.minimum_consideration_seconds,
        )
        if candidate.purpose not in {
            "consider_autonomous_life",
            "consider_autonomy_check",
        }:
            return candidate
        state = await (
            await transaction.execute(
                """SELECT statement_timestamp(),p.policy::text,p.phase,
                      p.outlet_state,p.outlet_reason_code,
                      (SELECT max(resolved_at) FROM armi.opportunities o
                       WHERE o.subject_id=p.subject_id AND o.purpose='consider_autonomous_life'),
                      p.idle_streak,p.last_engage,p.last_check_started_at
               FROM armi.autonomy_plans p WHERE p.subject_id=%s""",
                (candidate.subject_id,),
            )
        ).fetchone()
        if state is None:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-MISSING")
        return replace(
            candidate,
            autonomy_context=rfc8785.dumps(
                {
                    "current_time": state[0].isoformat(),
                    "timezone": "Asia/Shanghai",
                    "policy": json.loads(state[1]),
                    "phase": state[2],
                    "idle_streak": int(state[6]),
                    "last_engage": state[7],
                    "outlet_bound": candidate.scene_id is not None,
                    "outlet_state": state[3],
                    "outlet_reason_code": state[4],
                    "last_considered_at": None
                    if state[5] is None
                    else state[5].isoformat(),
                }
            ),
        )

    async def select_for_cognition(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> bool:
        # A positive check is single-use and tied to the state it actually saw.
        # Human input or another commit invalidates it before full Context starts.
        invalid = await (
            await transaction.execute(
                """UPDATE armi.opportunities o SET current_disposition='cancelled',
                   resolved_at=statement_timestamp(),
                   resolution_reason_code='LIFE-AUTONOMY-CHECK-STALE'
               WHERE o.opportunity_id=%s AND o.current_disposition='open'
                 AND o.purpose='consider_autonomous_life' AND o.source_kind='autonomy_plan'
                 AND NOT EXISTS (
                   SELECT 1 FROM armi.autonomy_plans p
                   WHERE p.opportunity_id=o.opportunity_id AND p.plan_version=o.source_version
                     AND p.phase='execute')
               RETURNING o.opportunity_id""",
                (opportunity_id,),
            )
        ).fetchone()
        if invalid is not None:
            return False
        row = await (
            await transaction.execute(
                """UPDATE armi.opportunities SET current_disposition='selected',
                      selected_at=transaction_timestamp()
               WHERE opportunity_id=%s AND current_disposition='open'
                 AND (expires_at IS NULL OR expires_at>transaction_timestamp())
               RETURNING opportunity_id""",
                (opportunity_id,),
            )
        ).fetchone()
        return row is not None

    async def resolve_autonomy_check(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        episode_id: UUID,
        engage: bool,
    ) -> None:
        await PostgreSQLAutonomyOwner().commit_check(
            transaction,
            opportunity_id=opportunity_id,
            episode_id=episode_id,
            engage=engage,
            policy=self._autonomy_policy,
        )

    async def mark_autonomy_check_started(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
    ) -> None:
        await transaction.execute(
            """UPDATE armi.autonomy_plans p SET last_check_started_at=statement_timestamp()
               WHERE p.opportunity_id=%s AND p.phase='check'""",
            (opportunity_id,),
        )

    async def resolve_cognition_failure(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        failure_code: str | None = None,
    ) -> bool:
        row = await (
            await transaction.execute(
                """UPDATE armi.opportunities SET current_disposition='resolved',
                      resolved_at=statement_timestamp(),
                      resolution_reason_code='COGNITION-FAILED'
               WHERE opportunity_id=%s AND current_disposition='selected'
               RETURNING opportunity_id""",
                (opportunity_id,),
            )
        ).fetchone()
        if row is not None:
            await transaction.execute(
                """UPDATE armi.autonomy_plans p SET
                       plan_version=plan_version+1,opportunity_id=NULL,
                       failure_streak=LEAST(failure_streak+1,3),
                       phase=CASE WHEN %s THEN 'blocked' ELSE 'waiting' END,
                       blocked_reason_code=%s,
                       next_consideration_at=statement_timestamp()+
                         CASE failure_streak WHEN 0 THEN interval '60 seconds'
                           WHEN 1 THEN interval '120 seconds' ELSE interval '300 seconds' END,
                       updated_at=statement_timestamp()
                   WHERE p.opportunity_id=%s""",
                (
                    bool(
                        failure_code
                        and failure_code.startswith(
                            ("MODEL-CREDENTIAL", "MODEL-BINDING", "MODEL-AUTH")
                        )
                    ),
                    failure_code
                    if failure_code
                    and failure_code.startswith(
                        ("MODEL-CREDENTIAL", "MODEL-BINDING", "MODEL-AUTH")
                    )
                    else None,
                    opportunity_id,
                ),
            )
        return row is not None

    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        root_opportunity_id: UUID,
        context_party_id: UUID,
    ) -> OpportunityOperationSnapshot | None:
        row = await (
            await transaction.execute(
                """
                SELECT root.opportunity_id, current.opportunity_id,
                       root.evidence_id, current.subject_id, current.scene_id,
                       current.context_party_id, root.purpose,
                       current.current_disposition, current.reconsideration_no
                FROM armi.opportunities AS root
                JOIN LATERAL (
                    SELECT item.* FROM armi.opportunities AS item
                    WHERE item.root_opportunity_id=root.opportunity_id
                    ORDER BY item.reconsideration_no DESC LIMIT 1
                ) AS current ON true
                WHERE root.opportunity_id=%s
                  AND root.root_opportunity_id=root.opportunity_id
                  AND (current.context_party_id=%s OR (
                    root.purpose IN ('consider_autonomous_life','consider_autonomy_check')
                    AND current.context_party_id IS NULL
                  ))
                  AND root.purpose IN ('consider_creator_input','consider_codex_task',
                                       'consider_codex_result','consider_autonomous_life','consider_autonomy_check')
                  AND current.eligibility_status='eligible'
                  AND current.expires_at IS NULL
                """,
                (root_opportunity_id, context_party_id),
            )
        ).fetchone()
        if row is None:
            return None
        return OpportunityOperationSnapshot(
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            str(row[6]),
            str(row[7]),
            int(row[8]),
        )

    async def origin_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> tuple[UUID, UUID | None, str]:
        row = await (
            await transaction.execute(
                """SELECT root_opportunity_id,evidence_id,purpose FROM armi.opportunities
               WHERE opportunity_id=%s""",
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        return row[0], row[1], str(row[2])

    async def subject_commit_snapshot(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityCommitSnapshot:
        row = await (
            await transaction.execute(
                """
                SELECT opportunity_id, root_opportunity_id, reconsideration_no,
                       evidence_id, subject_id, scene_id, context_party_id,
                       purpose, source_kind, source_ref, source_version, activity_id,
                       available_after, expires_at
                FROM armi.opportunities
                WHERE opportunity_id = %s
                  AND current_disposition = 'selected'
                """,
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        return OpportunityCommitSnapshot(
            opportunity_id=row[0],
            root_opportunity_id=row[1],
            reconsideration_no=int(row[2]),
            evidence_id=row[3],
            subject_id=row[4],
            scene_id=row[5],
            context_party_id=row[6],
            purpose=str(row[7]),
            source_kind=str(row[8]),
            source_ref=row[9],
            source_version=int(row[10]),
            activity_id=row[11],
            available_after=row[12],
            expires_at=row[13],
        )

    async def resolve_subject_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        disposition: str = "resolved",
        autonomy_acted: bool | None = None,
        source_episode_id: UUID | None = None,
    ) -> None:
        if disposition not in {"resolved", "superseded"}:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        row = await (
            await transaction.execute(
                """
                UPDATE armi.opportunities
                SET current_disposition = %s, resolved_at = statement_timestamp(),
                    resolution_reason_code = %s
                WHERE opportunity_id = %s AND current_disposition = 'selected'
                RETURNING opportunity_id, subject_id, source_version, source_kind,purpose
                """,
                (
                    disposition,
                    "SUBJECT-COMMIT-SUPERSEDED"
                    if disposition == "superseded"
                    else "SUBJECT-COMMIT-RESOLVED",
                    opportunity_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-OPPORTUNITY-STATE")
        if (
            row[3] == "autonomy_plan"
            and disposition == "resolved"
            and source_episode_id is not None
        ):
            if await self.has_pending_human_input(transaction, subject_id=row[1]):
                raise LifeViolation("LIFE-AUTONOMY-HUMAN-INPUT-PREEMPTED")
            if autonomy_acted is None:
                raise LifeViolation("LIFE-AUTONOMY-SCHEDULE-REQUIRED")
            await PostgreSQLAutonomyOwner().commit_plan(
                transaction,
                subject_id=row[1],
                expected_version=int(row[2]),
                episode_id=source_episode_id,
                opportunity_id=opportunity_id,
                acted=autonomy_acted,
                policy=self._autonomy_policy,
            )
        elif self._autonomy_policy.enabled and row[4] in {
            "consider_creator_input",
            "consider_creator_voice_input",
            "consider_other_human_input",
            "consider_codex_result",
            "consider_web_evidence",
            "consider_life_query_result",
            "consider_requested_visual_observation",
        }:
            # Only newly handled input/results reset idle backoff. Completing a
            # check, timer or maintenance step must never wake another full thought.
            await transaction.execute(
                """UPDATE armi.autonomy_plans
                   SET next_consideration_at=LEAST(next_consideration_at,
                       statement_timestamp() + %s * interval '1 second'),
                       idle_streak=0,last_event_at=statement_timestamp(),
                       updated_at=statement_timestamp()
                   WHERE subject_id=%s AND opportunity_id IS NULL""",
                (self._autonomy_policy.minimum_consideration_seconds, row[1]),
            )

    async def supersede_subject_commit(
        self, transaction: PostgreSQLTransaction, *, opportunity_id: UUID
    ) -> OpportunityId | None:
        source = await self.subject_commit_snapshot(
            transaction, opportunity_id=opportunity_id
        )
        successor: OpportunityId | None = None
        if source.reconsideration_no == 0 and source.source_kind != "autonomy_plan":
            successor_id = uuid7()
            row = await (
                await transaction.execute(
                    """
                    INSERT INTO armi.opportunities (
                        opportunity_id, evidence_id, subject_id, scene_id,
                        context_party_id, purpose, eligibility_status,
                        current_disposition, root_opportunity_id,
                        predecessor_opportunity_id, reconsideration_no,
                        source_kind, source_ref, source_version, activity_id
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, 'eligible', 'open',
                        %s, %s, 1, %s, %s, %s, %s
                    )
                    ON CONFLICT (predecessor_opportunity_id) DO NOTHING
                    RETURNING opportunity_id
                    """,
                    (
                        successor_id,
                        source.evidence_id,
                        source.subject_id,
                        source.scene_id,
                        source.context_party_id,
                        source.purpose,
                        source.root_opportunity_id,
                        source.opportunity_id,
                        source.source_kind,
                        source.source_ref,
                        source.source_version,
                        source.activity_id,
                    ),
                )
            ).fetchone()
            if row is None:
                raise LifeViolation("LIFE-ADMISSION-CONFLICT")
            successor = OpportunityId(row[0])
        await self.resolve_subject_commit(
            transaction,
            opportunity_id=opportunity_id,
            disposition=(
                "superseded"
                if successor is not None or source.source_kind == "autonomy_plan"
                else "resolved"
            ),
        )
        return successor

    async def admit_life_query_result(
        self,
        transaction: PostgreSQLTransaction,
        draft: LifeQueryResultOpportunityDraft,
    ) -> OpportunityId:
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    creator_party_id, purpose, source_kind, source_ref,
                    source_version, eligibility_status,
                    current_disposition, root_opportunity_id,
                    predecessor_opportunity_id, reconsideration_no)
                SELECT %s, NULL, %s, %s, %s, 'consider_life_query_result',
                       'life_query_result', %s, 1, 'eligible', 'open',
                       source.root_opportunity_id, %s,
                       source.reconsideration_no + 1
                FROM armi.opportunities AS source
                WHERE source.opportunity_id = %s
                RETURNING opportunity_id
                """,
                (
                    draft.opportunity_id,
                    draft.subject_id,
                    draft.scene_id,
                    draft.creator_party_id,
                    draft.intent_id,
                    draft.source_opportunity_id,
                    draft.source_opportunity_id,
                ),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-ADMISSION-CONFLICT")
        return OpportunityId(row[0])

    async def reconsider_sleep(
        self,
        transaction: PostgreSQLTransaction,
        *,
        predecessor_opportunity_id: UUID,
    ) -> OpportunityId | None:
        successor_id = uuid7()
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, eligibility_status,
                    current_disposition, available_after, expires_at,
                    root_opportunity_id, predecessor_opportunity_id,
                    reconsideration_no, source_kind, source_ref, source_version,
                    activity_id)
                SELECT %s, NULL, subject_id, NULL, NULL, purpose, 'eligible',
                       'open', statement_timestamp() + make_interval(secs => 3600),
                       expires_at, root_opportunity_id, opportunity_id, 1,
                       source_kind, source_ref, source_version, NULL
                FROM armi.opportunities
                WHERE opportunity_id = %s
                  AND statement_timestamp() + make_interval(secs => 3600)
                      < expires_at
                ON CONFLICT (predecessor_opportunity_id) DO NOTHING
                RETURNING opportunity_id
                """,
                (successor_id, predecessor_opportunity_id),
            )
        ).fetchone()
        return None if row is None else OpportunityId(row[0])

    async def admit_external_evidence(
        self,
        transaction: PostgreSQLTransaction,
        draft: ExternalEvidenceOpportunityDraft,
    ) -> OpportunityAdmissionOutcome:
        opportunity_id = uuid7()
        row = await (
            await transaction.execute(
                """
                INSERT INTO armi.opportunities (
                    opportunity_id, evidence_id, subject_id, scene_id,
                    context_party_id, purpose, source_kind, source_ref,
                    source_version, eligibility_status, current_disposition,
                    root_opportunity_id, reconsideration_no, expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,'external_evidence',%s,1,
                        'eligible','open',%s,0,
                        CASE WHEN %s='consider_visual_observation'
                             THEN statement_timestamp()+interval '5 minutes' END)
                ON CONFLICT (
                    subject_id, source_kind, source_ref, source_version,
                    purpose, reconsideration_no
                ) DO NOTHING
                RETURNING opportunity_id
                """,
                (
                    opportunity_id,
                    draft.evidence_id,
                    draft.subject_id,
                    draft.scene_id,
                    draft.context_party_id,
                    draft.purpose.value,
                    draft.evidence_id,
                    opportunity_id,
                    draft.purpose.value,
                ),
            )
        ).fetchone()
        if row is not None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.ADMITTED, row[0]
            )
        existing = await self.find_external_evidence(
            transaction,
            evidence_id=draft.evidence_id,
            purpose=draft.purpose,
        )
        if existing is None:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-ADMISSION-CONFLICT",
            )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.DUPLICATE, existing.value
        )

    async def find_external_evidence(
        self,
        transaction: PostgreSQLTransaction,
        *,
        evidence_id: UUID,
        purpose: OpportunityPurpose,
    ) -> OpportunityId | None:
        row = await (
            await transaction.execute(
                """
                SELECT opportunity_id
                FROM armi.opportunities
                WHERE evidence_id = %s
                  AND source_kind = 'external_evidence'
                  AND source_ref = %s
                  AND source_version = 1
                  AND purpose = %s
                  AND reconsideration_no = 0
                """,
                (evidence_id, evidence_id, purpose.value),
            )
        ).fetchone()
        return None if row is None else OpportunityId(row[0])


__all__ = ("PostgreSQLOpportunityOwner",)


def _cognition_candidate(row: tuple[object, ...]) -> OpportunityCognitionCandidate:
    return OpportunityCognitionCandidate(
        opportunity_id=cast(UUID, row[0]),
        root_opportunity_id=cast(UUID, row[1]),
        evidence_id=cast(UUID | None, row[2]),
        subject_id=cast(UUID, row[3]),
        scene_id=cast(UUID | None, row[4]),
        context_party_id=cast(UUID | None, row[5]),
        purpose=str(row[6]),
        source_kind=str(row[7]),
        source_ref=cast(UUID, row[8]),
        source_version=cast(int, row[9]),
        available_after=cast(datetime, row[10]),
        expires_at=cast(datetime | None, row[11]),
        activity_id=cast(UUID | None, row[12]),
    )
