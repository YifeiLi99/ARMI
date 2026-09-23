"""Active opportunity admission and attention pipeline."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime
from uuid import UUID

from armi_activity.api import ActivityReadPort
from armi_kernel.application import (
    CreatorEventViolation,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    CreatorResourceKind,
    record_diagnostic,
)
from armi_kernel.contracts import Instant
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWorkFactory,
    RuntimeTransactionFailure,
)
from armi_sleep.api import SleepMaintenancePort, SleepReadPort, SleepViolation
from armi_subject_state.api import SubjectStateReadPort

from ._postgresql import PostgreSQLLifeOpportunityRepository
from .api import (
    AutonomyPolicy,
    LifeOpportunityFactsPort,
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
        if (
            outcome.status is not OpportunityAdmissionStatus.DUPLICATE
            and outcome.reason_code
            not in {
                "LIFE-MAINTENANCE-NOT-DUE",
                "LIFE-MAINTENANCE-QUIET",
                "LIFE-MAINTENANCE-WAITING-SAFE-POINT",
            }
        ):
            record_diagnostic(
                "maintenance.check.completed",
                component="maintenance",
                session_id=session_id,
                opportunity_id=outcome.opportunity_id,
                outcome=outcome.status.value,
                result_code=outcome.reason_code,
            )
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
                    CreatorResourceKind("maintenance"),
                    str(session_id),
                    Instant(datetime.now(UTC)),
                    "creator-maintenance",
                )
            )
        except CreatorEventViolation:
            return


class OpportunityPipeline(LifeOpportunitySourcePort):
    __slots__ = (
        "_autonomy_policy",
        "_factory",
        "_facts",
        "_maintenance",
        "_model_concurrency",
        "_repository",
        "_stop",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        facts: LifeOpportunityFactsPort,
        activity_read: ActivityReadPort,
        sleep_maintenance: SleepMaintenancePort,
        sleep_read: SleepReadPort,
        subject_state_read: SubjectStateReadPort,
        wakeups: OpportunityWakeupPort | None = None,
        model_concurrency: int = 2,
        maintenance_consideration_seconds: int = 57_600,
        maintenance_deadline_seconds: int = 86_400,
        notifier: CreatorProjectionNotifier | None = None,
        autonomy_policy: AutonomyPolicy | None = None,
    ) -> None:
        self._autonomy_policy = autonomy_policy or AutonomyPolicy()
        self._factory = factory
        self._facts = facts
        self._repository = PostgreSQLLifeOpportunityRepository(
            sleep_read,
            activity_read,
            subject_state_read,
            facts,
        )
        self._stop = asyncio.Event()
        self._wakeups = wakeups or _NoopWakeups()
        self._model_concurrency = model_concurrency
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
        observations: dict[str, object] = {}
        try:
            # Local channel inspection may perform I/O and must precede the write transaction.
            outlet_health = await self._facts.outlet_health(
                self._autonomy_policy.outlet
            )
            model_revision = self._facts.model_configuration_revision()
            async with self._factory.unit_of_work() as unit_of_work:
                result = await self._repository.admit_autonomy(
                    unit_of_work,
                    policy=self._autonomy_policy,
                    model_concurrency=self._model_concurrency,
                    outlet_health=outlet_health,
                    model_revision=model_revision,
                    observations=observations,
                )
        except LifeViolation:
            raise
        except RuntimeTransactionFailure:
            raise LifeViolation("LIFE-DATABASE") from None
        if result.status is OpportunityAdmissionStatus.ADMITTED:
            self._wakeups.notify(OPPORTUNITY_AVAILABLE)
            record_diagnostic(
                "autonomy.admission.checked",
                component="autonomy",
                trigger="scheduler",
                opportunity_id=result.opportunity_id,
                outcome=result.status.value,
                reason=result.reason_code,
                conditions=observations,
            )
        return result

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                maintenance = await self.maintain_sleep_once()
                if maintenance.opportunity_id is not None:
                    self._wakeups.notify(OPPORTUNITY_AVAILABLE)
                await self.admit_once()
            except LifeViolation as exc:
                if not exc.code.startswith("LIFE-BACKPRESSURE-"):
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


def compose_opportunity_pipeline(
    *,
    factory: PostgreSQLRuntimeUnitOfWorkFactory,
    facts: LifeOpportunityFactsPort,
    activity_read: ActivityReadPort,
    sleep_maintenance: SleepMaintenancePort,
    sleep_read: SleepReadPort,
    subject_state_read: SubjectStateReadPort,
    wakeups: OpportunityWakeupPort | None = None,
    model_concurrency: int = 2,
    maintenance_consideration_seconds: int = 57_600,
    maintenance_deadline_seconds: int = 86_400,
    notifier: CreatorProjectionNotifier | None = None,
    autonomy_policy: AutonomyPolicy | None = None,
) -> OpportunityPipeline:
    return OpportunityPipeline(
        autonomy_policy=autonomy_policy,
        factory=factory,
        facts=facts,
        activity_read=activity_read,
        sleep_maintenance=sleep_maintenance,
        sleep_read=sleep_read,
        subject_state_read=subject_state_read,
        wakeups=wakeups,
        model_concurrency=model_concurrency,
        maintenance_consideration_seconds=maintenance_consideration_seconds,
        maintenance_deadline_seconds=maintenance_deadline_seconds,
        notifier=notifier,
    )


__all__ = (
    "MaintenanceCoordinator",
    "OpportunityPipeline",
    "compose_opportunity_pipeline",
)
