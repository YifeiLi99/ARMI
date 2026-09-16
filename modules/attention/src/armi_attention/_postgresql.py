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
        if active >= max(1, model_concurrency - 1):
            return OpportunityAdmissionOutcome(
                OpportunityAdmissionStatus.REJECTED,
                None,
                "LIFE-BACKPRESSURE-COGNITION-CAPACITY",
            )
        heads = await self._activities.scheduling_heads(
            transaction, subject_id=fence.subject_id
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
        )


__all__ = ("PostgreSQLLifeOpportunityRepository",)
