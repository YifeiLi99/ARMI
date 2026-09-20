"""PostgreSQL ownership for autonomous life opportunity admission."""

from __future__ import annotations

from datetime import UTC, datetime

from armi_activity.api import (
    ActivityReadPort,
    ActivityScheduler,
    ActivitySchedulingSnapshot,
    ActivityStatus,
)
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
)
from armi_sleep.api import SleepReadPort
from armi_subject_state.api import SubjectStateReadPort

from ._autonomy_postgresql import PostgreSQLAutonomyOwner
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
    ) -> OpportunityAdmissionOutcome:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise LifeViolation("LIFE-FENCE-REQUIRED")
        transaction = unit_of_work.transaction
        owner = PostgreSQLAutonomyOwner()
        await owner.ensure_plan(
            transaction,
            subject_id=fence.subject_id,
            policy=policy,
            state_epoch=await self._facts.state_epoch(
                transaction, subject_id=fence.subject_id
            ),
        )
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET model_configuration_revision=%s,
                   phase=CASE WHEN phase='blocked' THEN 'waiting' ELSE phase END,
                   blocked_reason_code=NULL,failure_streak=0,
                   next_consideration_at=CASE WHEN phase='blocked'
                     THEN statement_timestamp()+interval '60 seconds' ELSE next_consideration_at END
               WHERE subject_id=%s AND model_configuration_revision IS DISTINCT FROM %s""",
            (model_revision, fence.subject_id, model_revision),
        )
        outlet = await self._facts.outreach(unit_of_work, outlet=policy.outlet)
        outlet_state, outlet_reason = outlet_health
        if outlet is None:
            outlet_state, outlet_reason = "unbound", "LIFE-AUTONOMY-OUTLET-UNBOUND"
        await transaction.execute(
            """UPDATE armi.autonomy_plans SET outlet_state=%s,outlet_reason_code=%s,
                      outlet_observed_at=statement_timestamp() WHERE subject_id=%s""",
            (outlet_state, outlet_reason, fence.subject_id),
        )
        if await self._sleep.active_maintenance(
            transaction, subject_id=fence.subject_id
        ):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-MAINTENANCE",
            )
        active = await self._facts.active_cognition_count(
            transaction, subject_id=fence.subject_id
        )
        if active > 0:
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-COGNITION-CAPACITY",
            )
        if not await self._facts.autonomy_idle(
            transaction, subject_id=fence.subject_id
        ):
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
        heads = await self._activities.scheduling_heads(
            transaction, subject_id=fence.subject_id
        )
        # An activity's deadline is a stable event, unlike periodic scheduler
        # refreshes. Consume its timestamp once so a waiting task cannot keep
        # resetting the backoff every tick.
        due_at = max(
            (
                head.resume_not_before
                for head in heads
                if head.resume_not_before is not None
                and head.resume_not_before <= datetime.now(UTC)
                and head.status in {ActivityStatus.WAITING, ActivityStatus.IN_PROGRESS}
            ),
            default=None,
        )
        if due_at is not None:
            await transaction.execute(
                """UPDATE armi.autonomy_plans SET last_event_at=%s,idle_streak=0,
                       next_consideration_at=LEAST(next_consideration_at,
                         statement_timestamp()+interval '60 seconds')
                   WHERE subject_id=%s AND opportunity_id IS NULL AND phase='waiting'
                     AND (last_event_at IS NULL OR last_event_at<%s)""",
                (due_at, fence.subject_id, due_at),
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
        if selected is None:
            selection = ActivityScheduler().select(
                ActivitySchedulingSnapshot(
                    datetime.now(UTC),
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
        return await owner.admit_due(
            transaction,
            subject_id=fence.subject_id,
            policy=policy,
            scene_id=None if outlet is None else outlet.scene_id,
            creator_party_id=None if outlet is None else outlet.creator_party_id,
            activity_id=None if selected is None else selected.activity_id.value,
            signals=signals,
        )


__all__ = ("PostgreSQLLifeOpportunityRepository",)
