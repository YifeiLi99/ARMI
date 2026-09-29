"""Attention-owned idle checks and their single-use execution opportunities."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import timedelta
from random import random
from uuid import UUID, uuid7

from armi_kernel.application import AutonomyCategory, ConsiderationSignal, business_now
from armi_runtime_foundation import PostgreSQLTransaction, active_runtime_seconds

from ._activation import Activation
from ._autonomy_schedule import AutonomySchedule
from ._signals import signal_metadata, unconsumed_signals
from ._social_cycle import SocialCycle
from .api import (
    AutonomyPlan,
    AutonomyPolicy,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)


class PostgreSQLAutonomyOwner:
    async def activation_state(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        policy: AutonomyPolicy,
        idling: bool,
        need: float,
        runtime_ref: str,
    ) -> Activation:
        row = await (
            await transaction.execute(
                "SELECT activation FROM armi.autonomy_plans WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            )
        ).fetchone()
        assert row is not None
        active = await active_runtime_seconds(transaction, subject_id=subject_id)
        previous = None if row[0] is None else Activation.model_validate(row[0])
        state = previous or Activation.begin(cycle=0, active=active, policy=policy)
        state = state.changed(active=active, idling=idling, need=need, policy=policy)
        state = state.model_copy(update={"runtime_ref": runtime_ref})
        if state != previous:
            await transaction.execute(
                """UPDATE armi.autonomy_plans SET activation=%s::jsonb,
                   next_consideration_at=%s WHERE subject_id=%s""",
                (
                    state.model_dump_json(),
                    business_now() + timedelta(seconds=state.remaining(active, policy)),
                    subject_id,
                ),
            )
        return state

    async def reset_activation(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        policy: AutonomyPolicy,
        delay_seconds: int = 0,
    ) -> None:
        row = await (
            await transaction.execute(
                "SELECT activation FROM armi.autonomy_plans WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            )
        ).fetchone()
        assert row is not None
        cycle = 0 if row[0] is None else int(row[0]["cycle"]) + 1
        state = Activation.begin(
            cycle=cycle,
            active=await active_runtime_seconds(transaction, subject_id=subject_id),
            policy=policy,
        )
        state = state.model_copy(
            update={"retry_after": state.anchor_seconds + delay_seconds}
        )
        await transaction.execute(
            "UPDATE armi.autonomy_plans SET activation=%s::jsonb WHERE subject_id=%s",
            (state.model_dump_json(), subject_id),
        )

    async def commit_social_decision(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        opportunity_id: UUID,
        decision: tuple[str, str] | None,
    ) -> None:
        from armi_runtime_foundation import active_runtime_seconds

        row = await (
            await transaction.execute(
                "SELECT social_cycle FROM armi.autonomy_plans WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-MISSING")
        cycle = None if row[0] is None else SocialCycle.model_validate(row[0])
        expected = (
            cycle is not None
            and cycle.phase == "cognition"
            and cycle.episode_ref == str(opportunity_id)
        )
        if expected != (decision is not None):
            raise LifeViolation("LIFE-SOCIAL-DECISION-REQUIRED")
        if decision is not None:
            assert cycle is not None
            outcome, reason = decision
            if outcome not in {"express", "defer", "release"}:
                raise LifeViolation("LIFE-SOCIAL-DECISION")
            from typing import Literal, cast

            cycle = cycle.decided(
                outcome=cast(Literal["express", "defer", "release"], outcome),
                reason=reason,
                episode_ref=str(opportunity_id),
                active_seconds=await active_runtime_seconds(
                    transaction, subject_id=subject_id
                ),
            )
            await transaction.execute(
                "UPDATE armi.autonomy_plans SET social_cycle=%s::jsonb WHERE subject_id=%s",
                (cycle.model_dump_json(), subject_id),
            )

    async def social_cycle(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        input_ref: str | None,
        target_ref: str,
        active_seconds: float,
        delivery_status: Callable[[UUID], Awaitable[str]],
    ) -> SocialCycle:
        row = await (
            await transaction.execute(
                "SELECT social_cycle FROM armi.autonomy_plans WHERE subject_id=%s FOR UPDATE",
                (subject_id,),
            )
        ).fetchone()
        if row is None:
            raise LifeViolation("LIFE-AUTONOMY-PLAN-MISSING")
        prior = None if row[0] is None else SocialCycle.model_validate(row[0])
        cycle = prior
        if (
            cycle is None
            or cycle.input_ref != input_ref
            or cycle.target_ref != target_ref
        ):
            cycle = SocialCycle.begin(
                random, input_ref=input_ref, target_ref=target_ref
            )
        elif cycle.phase == "delivery":
            assert cycle.episode_ref is not None
            status = await delivery_status(UUID(cycle.episode_ref))
            if status == "delivered":
                cycle = cycle.delivered(active_seconds=active_seconds)
            elif status != "pending":
                cycle = cycle.interrupted(active_seconds=active_seconds, reason=status)
        elif cycle.phase == "cognition":
            pending = await (
                await transaction.execute(
                    "SELECT current_disposition FROM armi.opportunities WHERE opportunity_id=%s",
                    (UUID(str(cycle.episode_ref)),),
                )
            ).fetchone()
            if pending is None or pending[0] not in {"open", "selected"}:
                cycle = cycle.interrupted(
                    active_seconds=active_seconds, reason="interrupted"
                )
        elif (
            cycle.phase in {"waiting", "deferred", "released"}
            and active_seconds >= cycle.review_at
        ):
            cycle = SocialCycle.begin(
                random,
                input_ref=input_ref,
                unanswered=cycle.unanswered,
                target_ref=target_ref,
            )
        if cycle != prior:
            await transaction.execute(
                "UPDATE armi.autonomy_plans SET social_cycle=%s::jsonb WHERE subject_id=%s",
                (cycle.model_dump_json(), subject_id),
            )
        return cycle

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
        social_ready: bool = False,
        due_activity: bool = False,
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
                    "SELECT current_disposition,armi.business_time(statement_timestamp()) FROM armi.opportunities WHERE opportunity_id=%s",
                    (plan.opportunity_id,),
                )
            ).fetchone()
            if previous is None:
                raise LifeViolation("LIFE-AUTONOMY-OPPORTUNITY-MISSING")
            if previous[0] in {"open", "selected"}:
                return OpportunityAdmissionOutcome(
                    OpportunityAdmissionStatus.DUPLICATE, plan.opportunity_id
                )
            await self.reset_activation(
                transaction, subject_id=subject_id, policy=policy
            )
            # A failed/interrupted round cannot supply a subjective plan. Schedule
            # a fresh opportunity, preserving its terminal fact and original plan.
            await transaction.execute(
                """UPDATE armi.autonomy_plans
                   SET plan_version=plan_version+1,opportunity_id=NULL,
                       phase='waiting',next_consideration_at=armi.business_time(statement_timestamp()) + %s * interval '1 second',
                       updated_at=armi.business_time(statement_timestamp())
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
                """SELECT LEAST(next_consideration_at,%s::timestamptz) <= armi.business_time(statement_timestamp())
                     AND (last_check_started_at IS NULL OR
                          last_check_started_at<=armi.business_time(statement_timestamp())-interval '60 seconds')
                     AND phase<>'blocked'
                   FROM armi.autonomy_plans WHERE subject_id=%s""",
                (
                    business_now() if social_ready or due_activity else signal_at,
                    subject_id,
                ),
            )
        ).fetchone()
        if ready is None or not ready[0]:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED, None, "LIFE-AUTONOMY-NOT-DUE"
            )
        opportunity_id = uuid7()
        await transaction.execute(
            """INSERT INTO armi.opportunities
               (opportunity_id,subject_id,purpose,current_disposition,
                root_opportunity_id,source_kind,source_ref,source_version,scene_id,context_party_id,activity_id,consideration_signals)
               VALUES (%s,%s,%s,'open',%s,
                       'autonomy_plan',%s,%s,%s,%s,%s,%s::jsonb)""",
            (
                opportunity_id,
                subject_id,
                "consider_autonomy_check",
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
            """UPDATE armi.autonomy_plans SET opportunity_id=%s,phase=%s,
                      idle_streak=CASE WHEN %s THEN 0 ELSE idle_streak END,
                      last_check_started_at=armi.business_time(statement_timestamp())
               WHERE subject_id=%s""",
            (
                opportunity_id,
                "check",
                bool(signals),
                subject_id,
            ),
        )
        reasons = [
            signal.reason for signal in signals if signal.eligible_at <= business_now()
        ]
        if social_ready:
            reasons.append("social_need")
        if due_activity:
            reasons.append("activity_due")
        await transaction.execute(
            "UPDATE armi.autonomy_plans SET trigger_reasons=%s::jsonb WHERE subject_id=%s",
            (json.dumps(sorted(set(reasons)) or ["spontaneous"]), subject_id),
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
               VALUES (%s,1,armi.business_time(statement_timestamp()) + %s * interval '1 second',%s::jsonb,COALESCE(%s,0))
               ON CONFLICT (subject_id) DO UPDATE
               SET policy=excluded.policy,
                   observed_state_epoch=COALESCE(%s,autonomy_plans.observed_state_epoch),
                   next_consideration_at=CASE
                     WHEN NOT (autonomy_plans.policy->>'enabled')::boolean
                      AND (excluded.policy->>'enabled')::boolean
                     THEN excluded.next_consideration_at
                     ELSE autonomy_plans.next_consideration_at END,
                   updated_at=armi.business_time(statement_timestamp())
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
        category: AutonomyCategory,
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
        engage = category is not AutonomyCategory.REST
        successor = uuid7() if engage else None
        if successor is not None:
            await transaction.execute(
                """INSERT INTO armi.opportunities
                   (opportunity_id,subject_id,purpose,current_disposition,
                    root_opportunity_id,predecessor_opportunity_id,source_kind,source_ref,
                    source_version,scene_id,context_party_id,activity_id,consideration_signals,reconsideration_no,autonomy_category)
                   VALUES (%s,%s,'consider_autonomous_life','open',%s,%s,
                           'autonomy_plan',%s,%s,%s,%s,%s,%s::jsonb,1,%s)""",
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
                    category.value,
                ),
            )
        social = await (
            await transaction.execute(
                "SELECT social_cycle, trigger_reasons FROM armi.autonomy_plans WHERE subject_id=%s",
                (row[0],),
            )
        ).fetchone()
        if social is not None and social[0] is not None:
            cycle = SocialCycle.model_validate(social[0])
            active_seconds = await active_runtime_seconds(
                transaction, subject_id=row[0]
            )
            if category is AutonomyCategory.CONNECT:
                if cycle.phase != "considering" or active_seconds < cycle.review_at:
                    raise LifeViolation("LIFE-SOCIAL-NOT-AVAILABLE")
                cycle = cycle.model_copy(
                    update={
                        "phase": "cognition",
                        "episode_ref": str(successor),
                        "reason": "selected_connect",
                    }
                )
            elif "social_need" in social[1]:
                cycle = cycle.model_copy(
                    update={
                        "phase": "deferred",
                        "review_at": active_seconds + 3600,
                        "reason": "selected_" + category.value,
                    }
                )
            await transaction.execute(
                "UPDATE armi.autonomy_plans SET social_cycle=%s::jsonb WHERE subject_id=%s",
                (cycle.model_dump_json(), row[0]),
            )
        schedule = AutonomySchedule(int(row[2]))
        if not engage:
            schedule = schedule.settled(acted=False)
        await transaction.execute(
            """UPDATE armi.opportunities SET current_disposition='resolved',
                   resolved_at=armi.business_time(statement_timestamp()),resolution_reason_code=%s,autonomy_category=%s
               WHERE opportunity_id=%s""",
            (
                "LIFE-AUTONOMY-SCHEDULED" if engage else "LIFE-AUTONOMY-NOT-SCHEDULED",
                category.value,
                opportunity_id,
            ),
        )
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET plan_version=plan_version+1,
                   source_episode_id=%s,opportunity_id=%s,last_engage=%s,
                   idle_streak=%s,failure_streak=0,phase=%s,last_direction=%s,last_selection_result=%s,
                   next_consideration_at=armi.business_time(statement_timestamp())+%s*interval '1 second',
                   updated_at=armi.business_time(statement_timestamp()) WHERE subject_id=%s""",
            (
                episode_id,
                successor,
                engage,
                schedule.idle_streak,
                "execute" if engage else "waiting",
                category.value,
                "scheduled" if engage else "rest",
                schedule.interval_seconds,
                row[0],
            ),
        )

        if not engage:
            await self.reset_activation(transaction, subject_id=row[0], policy=policy)

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
                   next_consideration_at=armi.business_time(statement_timestamp()) + %s * interval '1 second',
                   opportunity_id=NULL,phase='waiting',idle_streak=%s,failure_streak=0,
                   updated_at=armi.business_time(statement_timestamp())
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
        await transaction.execute(
            "UPDATE armi.autonomy_plans SET last_selection_result=%s WHERE subject_id=%s",
            ("acted" if acted else "no_action", subject_id),
        )
        await self.reset_activation(transaction, subject_id=subject_id, policy=policy)
