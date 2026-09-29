"""PostgreSQL ownership for autonomous life opportunity admission."""

from __future__ import annotations

import json
from uuid import UUID

from armi_activity.api import (
    ActivityReadPort,
    ActivityScheduler,
    ActivitySchedulingSnapshot,
    ActivityStatus,
)
from armi_kernel.application import business_now
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    active_runtime_seconds,
)
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from ._autonomy_postgresql import PostgreSQLAutonomyOwner
from ._signals import unconsumed_signals
from .api import (
    AutonomyPolicy,
    LifeOpportunityFactsPort,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)


class PostgreSQLLifeOpportunityRepository:
    """Admit one source-backed root opportunity under the active Runtime fence."""

    __slots__ = (
        "_activities",
        "_facts",
        "_sleep",
        "_subject_state",
    )

    def __init__(
        self,
        sleep: SleepReadPort,
        activities: ActivityReadPort,
        subject_state: SubjectStateReadPort,
        facts: LifeOpportunityFactsPort,
    ) -> None:
        self._activities = activities
        self._sleep = sleep
        self._subject_state = subject_state
        self._facts = facts

    async def admit_autonomy(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        policy: AutonomyPolicy,
        model_concurrency: int,
        outlet_health: tuple[str, str | None],
        model_revision: str,
        observations: dict[str, object] | None = None,
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        transaction = unit_of_work.transaction
        owner = PostgreSQLAutonomyOwner()
        plan = await owner.ensure_plan(
            transaction,
            subject_id=fence.subject_id,
            policy=policy,
            state_epoch=await self._facts.state_epoch(
                transaction, subject_id=fence.subject_id
            ),
        )

        async def pause_activation() -> None:
            await owner.activation_state(
                transaction,
                subject_id=fence.subject_id,
                policy=policy,
                idling=False,
                need=0,
                runtime_ref=str(fence.runtime_instance_id.value),
            )

        if not policy.enabled:
            await pause_activation()
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED, None, "LIFE-AUTONOMY-DISABLED"
            )
        if observations is not None:
            observations.update(
                next_check_at=plan.next_consideration_at.isoformat(),
                schedule_observed="before_admission",
                activity_count=None,
                eligible_concern_count=None,
                eligible_motivation_count=None,
            )
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET model_configuration_revision=%s,
                   phase=CASE WHEN phase='blocked' THEN 'waiting' ELSE phase END,
                   blocked_reason_code=NULL,failure_streak=0,
                   next_consideration_at=CASE WHEN phase='blocked'
                     THEN armi.business_time(statement_timestamp())+interval '60 seconds' ELSE next_consideration_at END
               WHERE subject_id=%s AND model_configuration_revision IS DISTINCT FROM %s""",
            (model_revision, fence.subject_id, model_revision),
        )
        outlet = await self._facts.outreach(unit_of_work, outlet=policy.outlet)
        outlet_state, outlet_reason = outlet_health
        if outlet is None:
            outlet_state, outlet_reason = "unbound", "LIFE-AUTONOMY-OUTLET-UNBOUND"
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET outlet_state=%s,outlet_reason_code=%s,
                      outlet_observed_at=armi.business_time(statement_timestamp()) WHERE subject_id=%s
                      AND (outlet_state IS DISTINCT FROM %s OR outlet_reason_code IS DISTINCT FROM %s)""",
            (
                outlet_state,
                outlet_reason,
                fence.subject_id,
                outlet_state,
                outlet_reason,
            ),
        )
        if await self._sleep.active_maintenance(
            transaction, subject_id=fence.subject_id
        ):
            await pause_activation()
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-MAINTENANCE",
            )
        active = await self._facts.active_cognition_count(
            transaction, subject_id=fence.subject_id
        )
        if observations is not None:
            observations["active_cognition_count"] = active
        if active > 0:
            await pause_activation()
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-COGNITION-CAPACITY",
            )
        if not await self._facts.autonomy_idle(
            transaction, subject_id=fence.subject_id
        ):
            await pause_activation()
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-AUTONOMY-NOT-IDLE",
            )
        signals = await self._facts.consideration_signals(
            transaction,
            subject_id=fence.subject_id,
            minimum_delay_seconds=policy.minimum_consideration_seconds,
        )
        signals = await unconsumed_signals(
            transaction, subject_id=fence.subject_id, signals=signals
        )
        heads = await self._activities.scheduling_heads(
            transaction, subject_id=fence.subject_id
        )
        if observations is not None:
            observations.update(
                activity_count=len(heads),
                eligible_concern_count=sum(
                    signal.owner == "focus" for signal in signals
                ),
                eligible_motivation_count=sum(
                    signal.owner == "mind" for signal in signals
                ),
                signal_reasons=sorted({signal.reason for signal in signals}),
            )
        # Revisions identify owner conditions; unrelated input timestamps cannot
        # consume an activity deadline. Keep only currently live due conditions.
        due_conditions = sorted(
            str(head.revision_id)
            for head in heads
            if head.resume_not_before is not None
            and head.resume_not_before <= business_now()
            and head.status in {ActivityStatus.WAITING, ActivityStatus.IN_PROGRESS}
        )
        due_activity = False
        if due_conditions:
            previous_due = await (
                await transaction.execute(
                    "SELECT consumed_activity_conditions FROM armi.autonomy_plans WHERE subject_id=%s",
                    (fence.subject_id,),
                )
            ).fetchone()
            due_activity = previous_due is not None and bool(
                set(due_conditions) - set(previous_due[0])
            )
        focus = await self._subject_state.life_mode(
            transaction, subject_id=fence.subject_id
        )
        selected = next(
            (
                head
                for head in heads
                if head.activity_id.value in focus.active_activity_ids
                and head.status is ActivityStatus.IN_PROGRESS
            ),
            None,
        )
        focused = selected is not None
        social_ready = False
        if outlet is not None:

            async def delivery_status(root_id: UUID) -> str:
                return await self._facts.social_delivery_status(
                    transaction, root_opportunity_id=root_id
                )

            cycle = await owner.social_cycle(
                transaction,
                subject_id=fence.subject_id,
                target_ref=str(outlet.creator_party_id),
                input_ref=None
                if outlet.latest_input_id is None
                else str(outlet.latest_input_id),
                active_seconds=outlet.active_seconds,
                delivery_status=delivery_status,
            )
            social_ready = outlet_state == "ready" and cycle.ready(
                drive=outlet.contact_drive,
                active_seconds=outlet.active_seconds,
                focused=focused,
            )
        if selected is None:
            selection = ActivityScheduler().select(
                ActivitySchedulingSnapshot(
                    business_now(),
                    heads,
                    (),
                    False,
                    model_concurrency,
                    active,
                )
            )
            selected = next(
                (
                    head
                    for head in heads
                    if head.revision_id == selection.activity_revision_id
                ),
                None,
            )
        # The same owner state feeds live polling and the simulation deadline.
        state = await owner.activation_state(
            transaction,
            subject_id=fence.subject_id,
            policy=policy,
            idling=True,
            need=max(
                (
                    signal.priority
                    for signal in signals
                    if signal.eligible_at <= business_now()
                ),
                default=0,
            ),
            runtime_ref=str(fence.runtime_instance_id.value),
        )
        active_seconds = await active_runtime_seconds(
            transaction, subject_id=fence.subject_id
        )
        remaining = state.remaining(active_seconds, policy)
        quiet = (
            state.project(active_seconds, policy)[1] < policy.quiet_seconds
            or active_seconds < state.retry_after
        )
        if plan.opportunity_id is None and (
            quiet
            or (remaining > 0 and not signals and not social_ready and not due_activity)
        ):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED, None, "LIFE-AUTONOMY-NOT-DUE"
            )
        outcome = await owner.admit_due(
            transaction,
            subject_id=fence.subject_id,
            policy=policy,
            scene_id=None if outlet is None else outlet.scene_id,
            creator_party_id=None if outlet is None else outlet.creator_party_id,
            activity_id=None if selected is None else selected.activity_id.value,
            signals=signals,
            social_ready=social_ready,
            due_activity=due_activity,
        )
        if due_activity and outcome.status is OpportunityAdmissionStatus.ADMITTED:
            await transaction.execute(
                "UPDATE armi.autonomy_plans SET consumed_activity_conditions=%s::jsonb WHERE subject_id=%s",
                (json.dumps(due_conditions), fence.subject_id),
            )
        return outcome


__all__ = ("PostgreSQLLifeOpportunityRepository",)
