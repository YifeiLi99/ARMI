"""Active opportunity admission and attention pipeline."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import UUID

from armi_activity.api import ActivityReadPort
from armi_kernel.application import (
    CreatorEventResourceKind,
    CreatorEventViolation,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
)
from armi_kernel.contracts import Instant
from armi_material.api import MaterialReadPort
from armi_relationship.api import RelationshipPolicyPort, RelationshipReadPort
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)
from armi_sleep.api import SleepMaintenancePort, SleepReadPort, SleepViolation
from armi_subject_state.api import SubjectStateReadPort

from ._postgresql import PostgreSQLLifeOpportunityRepository
from .api import (
    CreatorOutreachPolicy,
    LifeOpportunitySourcePort,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    OpportunityWakeupPort,
)

OPPORTUNITY_AVAILABLE = "opportunity.available"


class _NoopWakeups:
    def notify(self, channel: str) -> None:
        del channel


class MaintenanceCoordinator:
    """Own one objective maintenance-window scan inside the Runtime loop."""

    __slots__ = (
        "_consideration_seconds",
        "_deadline_seconds",
        "_factory",
        "_notifier",
        "_quiet_seconds",
        "_repository",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        repository: SleepMaintenancePort,
        consideration_seconds: int,
        deadline_seconds: int,
        quiet_seconds: int = 60,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        if not 0 < consideration_seconds < deadline_seconds:
            raise LifeViolation("LIFE-MAINTENANCE-CONFIG")
        self._factory = factory
        self._repository = repository
        self._consideration_seconds = consideration_seconds
        self._deadline_seconds = deadline_seconds
        self._quiet_seconds = quiet_seconds
        self._notifier = notifier

    async def maintain_once(self) -> OpportunityAdmissionOutcome:
        session_id: UUID | None = None
        async with self._factory.unit_of_work() as unit_of_work:
            progress = await self._repository.maintain_active_session(
                unit_of_work,
                quiet_seconds=self._quiet_seconds,
            )
            if progress is not None:
                session_id = progress.session_id
                outcome = OpportunityAdmissionOutcome(
                    (
                        OpportunityAdmissionStatus.ADMITTED
                        if progress.opportunity_admitted
                        else OpportunityAdmissionStatus.DUPLICATE
                        if progress.opportunity_id is not None
                        else OpportunityAdmissionStatus.REJECTED
                    ),
                    progress.opportunity_id,
                    (
                        None
                        if progress.opportunity_id is not None
                        else progress.reason_code
                    ),
                )
            else:
                maintenance_outcome = await self._repository.maintain_window(
                    unit_of_work,
                    consideration_after_seconds=self._consideration_seconds,
                    deadline_after_seconds=self._deadline_seconds,
                )
                outcome = OpportunityAdmissionOutcome(
                    OpportunityAdmissionStatus(maintenance_outcome.status.value),
                    maintenance_outcome.opportunity_id,
                    maintenance_outcome.reason_code,
                )
                if outcome.reason_code == "LIFE-MAINTENANCE-DEADLINE":
                    session_id = await self._repository.active_session_id(unit_of_work)
        if session_id is not None:
            await self._notify(session_id)
        return outcome

    async def request_emergency_wake(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID:
        async with self._factory.unit_of_work() as unit_of_work:
            result = await self._repository.request_emergency_wake(
                unit_of_work,
                session_id=session_id,
                request_id=request_id,
            )
        await self._notify(result)
        return result

    async def _notify(self, session_id: UUID) -> None:
        if self._notifier is None:
            return
        try:
            await self._notifier.notify(
                CreatorProjectionInvalidation(
                    CreatorEventResourceKind.MAINTENANCE,
                    str(session_id),
                    Instant(datetime.now(UTC)),
                    "creator-maintenance.v2",
                )
            )
        except CreatorEventViolation:
            return


class OpportunityPipeline(LifeOpportunitySourcePort):
    __slots__ = (
        "_factory",
        "_maintenance",
        "_model_concurrency",
        "_outreach_policy",
        "_repository",
        "_stop",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        activity_read: ActivityReadPort,
        material_read: MaterialReadPort,
        relationship_read: RelationshipReadPort,
        relationship_policy: RelationshipPolicyPort,
        sleep_maintenance: SleepMaintenancePort,
        sleep_read: SleepReadPort,
        subject_state_read: SubjectStateReadPort,
        wakeups: OpportunityWakeupPort | None = None,
        model_concurrency: int = 2,
        maintenance_consideration_seconds: int = 57_600,
        maintenance_deadline_seconds: int = 86_400,
        creator_outreach_absence_seconds: int = 259_200,
        creator_outreach_minimum_interval_seconds: int = 86_400,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        self._factory = factory
        self._repository = PostgreSQLLifeOpportunityRepository(
            relationship_read,
            relationship_policy,
            sleep_read,
            activity_read,
            material_read,
            subject_state_read,
        )
        self._stop = asyncio.Event()
        self._wakeups = wakeups or _NoopWakeups()
        self._model_concurrency = model_concurrency
        self._outreach_policy = CreatorOutreachPolicy(
            creator_outreach_absence_seconds,
            creator_outreach_minimum_interval_seconds,
        )
        self._maintenance = MaintenanceCoordinator(
            factory=factory,
            repository=sleep_maintenance,
            consideration_seconds=maintenance_consideration_seconds,
            deadline_seconds=maintenance_deadline_seconds,
            notifier=notifier,
        )

    async def open(self) -> None:
        return None

    async def close(self) -> None:
        self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    async def admit_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                result = await self._repository.admit_generation_available(unit_of_work)
        except LifeViolation:
            raise
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None
        if result.status is OpportunityAdmissionStatus.ADMITTED:
            self._wakeups.notify(OPPORTUNITY_AVAILABLE)
        return result

    async def run(self) -> None:
        await self.admit_once()
        while not self._stop.is_set():
            try:
                maintenance = await self.maintain_sleep_once()
                if maintenance.opportunity_id is not None:
                    self._wakeups.notify(OPPORTUNITY_AVAILABLE)
                material = await self.admit_life_material_once()
                if material.status is OpportunityAdmissionStatus.ADMITTED:
                    self._wakeups.notify(OPPORTUNITY_AVAILABLE)
                outreach = await self.admit_creator_outreach_once()
                if outreach.status is OpportunityAdmissionStatus.ADMITTED:
                    self._wakeups.notify(OPPORTUNITY_AVAILABLE)
                internal_work = await self.admit_internal_work_once()
                if internal_work.status is OpportunityAdmissionStatus.ADMITTED:
                    self._wakeups.notify(OPPORTUNITY_AVAILABLE)
                result = await self.admit_attention_once()
                if result.status is OpportunityAdmissionStatus.ADMITTED:
                    self._wakeups.notify(OPPORTUNITY_AVAILABLE)
            except LifeViolation as exc:
                if not exc.code.startswith("LIFE-BACKPRESSURE-") and exc.code not in {
                    "LIFE-SCHEDULER-IDLE",
                    "LIFE-SCHEDULER-COOLDOWN",
                    "LIFE-OUTREACH-IDLE",
                    "LIFE-OUTREACH-COOLDOWN",
                    "LIFE-OUTREACH-AWAITING-CREATOR",
                    "LIFE-OUTREACH-RELATIONSHIP-BOUNDARY",
                    "LIFE-OUTREACH-SCENE-UNAVAILABLE",
                }:
                    raise
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=5)

    async def maintain_sleep_once(self) -> OpportunityAdmissionOutcome:
        try:
            return await self._maintenance.maintain_once()
        except LifeViolation:
            raise
        except SleepViolation as error:
            raise LifeViolation(f"LIFE-{error.code.removeprefix('SLEEP-')}") from None
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None

    async def admit_life_material_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._repository.admit_life_material_revision(unit_of_work)
        except LifeViolation:
            raise
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None

    async def admit_creator_outreach_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._repository.admit_creator_outreach(
                    unit_of_work,
                    policy=self._outreach_policy,
                )
        except LifeViolation:
            raise
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None

    async def request_emergency_wake(
        self,
        session_id: UUID,
        request_id: UUID,
    ) -> UUID:
        try:
            return await self._maintenance.request_emergency_wake(
                session_id,
                request_id,
            )
        except LifeViolation:
            raise
        except SleepViolation as error:
            raise LifeViolation(f"LIFE-{error.code.removeprefix('SLEEP-')}") from None
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None

    async def admit_attention_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._repository.admit_activity_attention(
                    unit_of_work,
                    model_concurrency=self._model_concurrency,
                )
        except LifeViolation:
            raise
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None

    async def admit_internal_work_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work() as unit_of_work:
                return await self._repository.admit_activity_internal_work(
                    unit_of_work,
                    model_concurrency=self._model_concurrency,
                )
        except LifeViolation:
            raise
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None


def compose_opportunity_pipeline(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    activity_read: ActivityReadPort,
    material_read: MaterialReadPort,
    relationship_read: RelationshipReadPort,
    relationship_policy: RelationshipPolicyPort,
    sleep_maintenance: SleepMaintenancePort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
    wakeups: OpportunityWakeupPort | None = None,
    model_concurrency: int = 2,
    maintenance_consideration_seconds: int = 57_600,
    maintenance_deadline_seconds: int = 86_400,
    creator_outreach_absence_seconds: int = 259_200,
    creator_outreach_minimum_interval_seconds: int = 86_400,
    notifier: CreatorProjectionNotifier | None = None,
) -> OpportunityPipeline:
    return OpportunityPipeline(
        factory=factory,
        activity_read=activity_read,
        material_read=material_read,
        relationship_read=relationship_read,
        relationship_policy=relationship_policy,
        sleep_maintenance=sleep_maintenance,
        sleep_read=sleep_read,
        subject_state_read=subject_state_read,
        wakeups=wakeups,
        model_concurrency=model_concurrency,
        maintenance_consideration_seconds=maintenance_consideration_seconds,
        maintenance_deadline_seconds=maintenance_deadline_seconds,
        creator_outreach_absence_seconds=creator_outreach_absence_seconds,
        creator_outreach_minimum_interval_seconds=(
            creator_outreach_minimum_interval_seconds
        ),
        notifier=notifier,
    )


__all__ = (
    "MaintenanceCoordinator",
    "OpportunityPipeline",
    "compose_opportunity_pipeline",
)
