"""Attention-owned idle checks and their single-use execution opportunities."""

from __future__ import annotations

import json
from dataclasses import asdict
from uuid import UUID, uuid7

from armi_kernel.application import ConsiderationSignal
from armi_runtime_foundation import PostgreSQLTransaction

from ._autonomy_schedule import AutonomySchedule
from ._signals import signal_metadata, unconsumed_signals
from .api import (
    AutonomyPlan,
    AutonomyPolicy,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)


class PostgreSQLAutonomyOwner:
    async def admit_due(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        policy: AutonomyPolicy,
        scene_id: UUID | None = None,
        creator_party_id: UUID | None = None,
        activity_id: UUID | None = None,
        signals: tuple[ConsiderationSignal, ...] = (),
    ) -> OpportunityAdmissionOutcome:
        if not policy.enabled:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED, None, "LIFE-AUTONOMY-DISABLED"
            )
        plan = await self.ensure_plan(transaction, subject_id=subject_id, policy=policy)
        signals = await unconsumed_signals(
            transaction, subject_id=subject_id, signals=signals
        )
        signal_at = min((signal.eligible_at for signal in signals), default=None)
        if plan.opportunity_id is not None:
            previous = await (
                await transaction.execute(
                    "SELECT current_disposition,statement_timestamp() FROM armi.opportunities WHERE opportunity_id=%s",
                    (plan.opportunity_id,),
                )
            ).fetchone()
            if previous is None:
                raise LifeViolation("LIFE-AUTONOMY-OPPORTUNITY-MISSING")
            if previous[0] in {"open", "selected"}:
                return OpportunityAdmissionOutcome(
                    OpportunityAdmissionStatus.DUPLICATE, plan.opportunity_id
                )
            # A failed/interrupted round cannot supply a subjective plan. Schedule
            # a fresh opportunity, preserving its terminal fact and original plan.
            await transaction.execute(
                """UPDATE armi.autonomy_plans
                   SET plan_version=plan_version+1,opportunity_id=NULL,
                       phase='waiting',next_consideration_at=statement_timestamp() + %s * interval '1 second',
                       updated_at=statement_timestamp()
                   WHERE subject_id=%s""",
                (policy.minimum_consideration_seconds, subject_id),
            )
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-AUTONOMY-RECONSIDERATION-SCHEDULED",
            )
        ready = await (
            await transaction.execute(
                """SELECT LEAST(next_consideration_at,%s::timestamptz) <= statement_timestamp()
                     AND (last_check_started_at IS NULL OR
                          last_check_started_at<=statement_timestamp()-interval '60 seconds')
                     AND phase<>'blocked'
                   FROM armi.autonomy_plans WHERE subject_id=%s""",
                (signal_at, subject_id),
            )
        ).fetchone()
        if ready is None or not ready[0]:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED, None, "LIFE-AUTONOMY-NOT-DUE"
            )
        opportunity_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.opportunities
               (opportunity_id,subject_id,purpose,eligibility_status,current_disposition,
                root_opportunity_id,source_kind,source_ref,source_version,scene_id,context_party_id,activity_id,consideration_signals)
               VALUES (%s,%s,'consider_autonomy_check','eligible','open',%s,
                       'autonomy_plan',%s,%s,%s,%s,%s,%s::jsonb)""",
            (
                opportunity_id,
                subject_id,
                opportunity_id,
                subject_id,
                plan.version,
                scene_id,
                creator_party_id,
                activity_id,
                signal_metadata(signals, frozen_at=None),
            ),
        )
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET opportunity_id=%s,phase='check',
                      idle_streak=CASE WHEN %s THEN 0 ELSE idle_streak END,
                      last_check_started_at=statement_timestamp()
               WHERE subject_id=%s""",
            (opportunity_id, bool(signals), subject_id),
        )
        return OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.ADMITTED, opportunity_id
        )

    async def ensure_plan(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        policy: AutonomyPolicy,
        state_epoch: int | None = None,
    ) -> AutonomyPlan:
        await transaction.execute(
            """INSERT INTO armi.autonomy_plans
               (subject_id,plan_version,next_consideration_at,policy,observed_state_epoch)
               VALUES (%s,1,statement_timestamp() + %s * interval '1 second',%s::jsonb,COALESCE(%s,0))
               ON CONFLICT (subject_id) DO UPDATE
               SET policy=excluded.policy,
                   observed_state_epoch=COALESCE(%s,autonomy_plans.observed_state_epoch),
                   next_consideration_at=CASE
                     WHEN NOT (autonomy_plans.policy->>'enabled')::boolean
                      AND (excluded.policy->>'enabled')::boolean
                     THEN excluded.next_consideration_at
                     ELSE autonomy_plans.next_consideration_at END,
                   updated_at=statement_timestamp()
               WHERE autonomy_plans.policy IS DISTINCT FROM excluded.policy
                  OR autonomy_plans.observed_state_epoch <> %s""",
            (
                subject_id,
                policy.minimum_consideration_seconds,
                json.dumps(asdict(policy)),
                state_epoch,
                state_epoch,
                state_epoch,
            ),
        )
        row = await (
            await transaction.execute(
                """SELECT subject_id,plan_version,next_consideration_at,
                          source_episode_id,opportunity_id
                   FROM armi.autonomy_plans WHERE subject_id=%s FOR UPDATE""",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-MISSING")
        return AutonomyPlan(row[0], int(row[1]), row[2], row[3], row[4])

    async def commit_check(
        self,
        transaction: PostgreSQLTransaction,
        *,
        opportunity_id: UUID,
        episode_id: UUID,
        engage: bool,
        policy: AutonomyPolicy,
    ) -> None:
        if not policy.enabled:
            raise LifeViolation("LIFE-AUTONOMY-DISABLED")
        row = await (
            await transaction.execute(
                """SELECT o.subject_id,p.plan_version,p.idle_streak,
                      o.scene_id,o.context_party_id,o.activity_id,o.consideration_signals
               FROM armi.opportunities o JOIN armi.autonomy_plans p
                 ON p.subject_id=o.subject_id AND p.opportunity_id=o.opportunity_id
               WHERE o.opportunity_id=%s AND o.purpose='consider_autonomy_check'
                 AND o.current_disposition='selected' AND o.source_version=p.plan_version
               FOR UPDATE OF o,p""",
                (opportunity_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-STALE")
        successor = uuid7() if engage else None
        if successor is not None:
            await transaction.execute(
                """INSERT INTO armi.opportunities
                   (opportunity_id,subject_id,purpose,eligibility_status,current_disposition,
                    root_opportunity_id,predecessor_opportunity_id,source_kind,source_ref,
                    source_version,scene_id,context_party_id,activity_id,consideration_signals,reconsideration_no)
                   VALUES (%s,%s,'consider_autonomous_life','eligible','open',%s,%s,
                           'autonomy_plan',%s,%s,%s,%s,%s,%s::jsonb,1)""",
                (
                    successor,
                    row[0],
                    opportunity_id,
                    opportunity_id,
                    row[0],
                    int(row[1]) + 1,
                    row[3],
                    row[4],
                    row[5],
                    json.dumps({**(row[6] or {}), "frozen_at": None}),
                ),
            )
        schedule = AutonomySchedule(int(row[2]))
        if not engage:
            schedule = schedule.settled(acted=False)
        await transaction.execute(
            """UPDATE armi.opportunities SET current_disposition='resolved',
                   resolved_at=statement_timestamp(),resolution_reason_code='LIFE-AUTONOMY-CHECKED'
               WHERE opportunity_id=%s""",
            (opportunity_id,),
        )
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET plan_version=plan_version+1,
                   source_episode_id=%s,opportunity_id=%s,last_engage=%s,
                   idle_streak=%s,failure_streak=0,phase=%s,
                   next_consideration_at=statement_timestamp()+%s*interval '1 second',
                   updated_at=statement_timestamp() WHERE subject_id=%s""",
            (
                episode_id,
                successor,
                engage,
                schedule.idle_streak,
                "execute" if engage else "waiting",
                schedule.interval_seconds,
                row[0],
            ),
        )

    async def commit_plan(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        expected_version: int,
        episode_id: UUID,
        opportunity_id: UUID,
        acted: bool,
        policy: AutonomyPolicy,
    ) -> None:
        if not policy.enabled:
            raise LifeViolation("LIFE-AUTONOMY-DISABLED")
        row = await (
            await transaction.execute(
                "SELECT idle_streak FROM armi.autonomy_plans WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-MISSING")
        schedule = AutonomySchedule(int(row[0])).settled(acted=acted)
        result = await transaction.execute(
            """UPDATE armi.autonomy_plans
               SET plan_version=plan_version+1,source_episode_id=%s,
                   next_consideration_at=statement_timestamp() + %s * interval '1 second',
                   opportunity_id=NULL,phase='waiting',idle_streak=%s,failure_streak=0,
                   updated_at=statement_timestamp()
               WHERE subject_id=%s AND plan_version=%s AND opportunity_id=%s""",
            (
                episode_id,
                schedule.interval_seconds,
                schedule.idle_streak,
                subject_id,
                expected_version,
                opportunity_id,
            ),
        )
        if result.rowcount != 1:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-STALE")
