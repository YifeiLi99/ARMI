"""Attention-owned plans and atomic paid-request admission."""

from __future__ import annotations

import json
from dataclasses import asdict
from uuid import UUID, uuid7

from armi_runtime_foundation import PostgreSQLTransaction

from .api import (
    AutonomyPlan,
    AutonomyPolicy,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    quota_day,
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
    ) -> OpportunityAdmissionOutcome:
        if not policy.enabled:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED, None, "LIFE-AUTONOMY-DISABLED"
            )
        plan = await self.ensure_plan(transaction, subject_id=subject_id, policy=policy)
        if plan.opportunity_id is not None:
            previous = await (
                await transaction.execute(
                    "SELECT current_disposition FROM armi.opportunities WHERE opportunity_id=%s",
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
                       next_consideration_at=statement_timestamp() + %s * interval '1 second',
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
                """SELECT next_consideration_at <= statement_timestamp()
                   FROM armi.autonomy_plans WHERE subject_id=%s""",
                (subject_id,),
            )
        ).fetchone()
        if ready is None or not ready[0]:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED, None, "LIFE-AUTONOMY-NOT-DUE"
            )
        usage = await (
            await transaction.execute(
                """SELECT count(*) FROM armi.autonomy_request_admissions
                   WHERE subject_id=%s
                     AND quota_date=(statement_timestamp() AT TIME ZONE 'Asia/Shanghai')::date""",
                (subject_id,),
            )
        ).fetchone()
        if usage is None or int(usage[0]) >= policy.daily_request_limit:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-AUTONOMY-QUOTA-EXHAUSTED",
            )
        opportunity_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.opportunities
               (opportunity_id,subject_id,purpose,eligibility_status,current_disposition,
                root_opportunity_id,source_kind,source_ref,source_version,scene_id,context_party_id,activity_id)
               VALUES (%s,%s,'consider_autonomous_life','eligible','open',%s,
                       'autonomy_plan',%s,%s,%s,%s,%s)""",
            (
                opportunity_id,
                subject_id,
                opportunity_id,
                subject_id,
                plan.version,
                scene_id,
                creator_party_id,
                activity_id,
            ),
        )
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET opportunity_id=%s
               WHERE subject_id=%s""",
            (opportunity_id, subject_id),
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
                     WHEN autonomy_plans.observed_state_epoch <> %s
                     THEN LEAST(autonomy_plans.next_consideration_at,excluded.next_consideration_at)
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

    async def commit_plan(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        expected_version: int,
        episode_id: UUID,
        opportunity_id: UUID,
        delay_seconds: int,
        policy: AutonomyPolicy,
    ) -> None:
        if not policy.enabled:
            raise LifeViolation("LIFE-AUTONOMY-DISABLED")
        if (
            type(delay_seconds) is not int
            or not policy.minimum_consideration_seconds
            <= delay_seconds
            <= policy.maximum_consideration_seconds
        ):
            raise LifeViolation("LIFE-AUTONOMY-SCHEDULE-RANGE")
        result = await transaction.execute(
            """UPDATE armi.autonomy_plans
               SET plan_version=plan_version+1,source_episode_id=%s,
                   next_consideration_at=statement_timestamp() + %s * interval '1 second',
                   opportunity_id=NULL,updated_at=statement_timestamp()
               WHERE subject_id=%s AND plan_version=%s AND opportunity_id=%s""",
            (episode_id, delay_seconds, subject_id, expected_version, opportunity_id),
        )
        if result.rowcount != 1:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-STALE")

    async def register_request(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        root_opportunity_id: UUID | None,
        call_id: str,
        policy: AutonomyPolicy,
    ) -> bool:
        # The caller's owner receipt write shares this transaction. A rollback of
        # either write prevents the external request; settlement never calls here.
        await self.ensure_plan(transaction, subject_id=subject_id, policy=policy)
        existing = await (
            await transaction.execute(
                """SELECT subject_id,root_opportunity_id
                   FROM armi.autonomy_request_admissions WHERE call_id=%s""",
                (call_id,),
            )
        ).fetchone()
        if existing is not None:
            if existing != (subject_id, root_opportunity_id):
                raise LifeViolation("LIFE-AUTONOMY-CALL-CONFLICT")
            return False
        if not policy.enabled:
            raise LifeViolation("LIFE-AUTONOMY-DISABLED")
        clock = await (
            await transaction.execute("SELECT statement_timestamp()", ())
        ).fetchone()
        if clock is None:
            raise LifeViolation("LIFE-AUTONOMY-TIME")
        day = quota_day(clock[0])
        count = await (
            await transaction.execute(
                """SELECT count(*) FROM armi.autonomy_request_admissions
                   WHERE subject_id=%s AND quota_date=%s""",
                (subject_id, day),
            )
        ).fetchone()
        if count is None or int(count[0]) >= policy.daily_request_limit:
            raise LifeViolation("LIFE-AUTONOMY-QUOTA-EXHAUSTED")
        await transaction.execute(
            """INSERT INTO armi.autonomy_request_admissions
               (call_id,subject_id,root_opportunity_id,quota_date)
               VALUES (%s,%s,%s,%s)""",
            (call_id, subject_id, root_opportunity_id, day),
        )
        return True
