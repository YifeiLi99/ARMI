"""Active P0-S001 autonomous opportunity source pipeline."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from armi_kernel.application import (
    CreatorEventResourceKind,
    CreatorEventViolation,
    CreatorProjectionInvalidation,
    CreatorProjectionNotifier,
    LifeOpportunitySourcePort,
    LifeViolation,
    LockPlan,
    LockTarget,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    RuntimeFence,
)
from armi_kernel.contracts import Instant

from armi_runtime.adapters.persistence.life_opportunity import (
    PostgreSQLLifeOpportunityRepository,
)
from armi_runtime.adapters.persistence.maintenance import (
    PostgreSQLMaintenanceRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import OPPORTUNITY_AVAILABLE, WorkWakeupBus


class MaintenanceCoordinator:
    """Own one objective maintenance-window scan inside the Runtime loop."""

    __slots__ = (
        "_consideration_seconds",
        "_deadline_seconds",
        "_factory",
        "_notifier",
        "_opportunities",
        "_quiet_seconds",
        "_repository",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        repository: PostgreSQLMaintenanceRepository,
        opportunities: PostgreSQLLifeOpportunityRepository,
        consideration_seconds: int,
        deadline_seconds: int,
        quiet_seconds: int = 60,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        if not 0 < consideration_seconds < deadline_seconds:
            raise LifeViolation("LIFE-MAINTENANCE-CONFIG")
        self._factory = factory
        self._repository = repository
        self._opportunities = opportunities
        self._consideration_seconds = consideration_seconds
        self._deadline_seconds = deadline_seconds
        if type(quiet_seconds) is not int or quiet_seconds < 0:
            raise LifeViolation("LIFE-MAINTENANCE-CONFIG")
        self._quiet_seconds = quiet_seconds
        self._notifier = notifier

    async def maintain_once(self) -> OpportunityAdmissionOutcome:
        session_id: UUID | None = None
        async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
            progress = await self._repository.maintain_active_session(
                unit_of_work,
                quiet_seconds=self._quiet_seconds,
            )
            if progress is not None:
                session_id = progress.session_id
                outcome = OpportunityAdmissionOutcome(
                    OpportunityAdmissionStatus.REJECTED,
                    None,
                    progress.reason_code,
                )
            else:
                outcome = await self._opportunities.maintain_sleep_window(
                    unit_of_work,
                    consideration_after_seconds=self._consideration_seconds,
                    deadline_after_seconds=self._deadline_seconds,
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
        async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
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
                    "creator-maintenance.v1",
                )
            )
        except CreatorEventViolation:
            return


class LifeOpportunityPipeline(LifeOpportunitySourcePort):
    __slots__ = (
        "_factory",
        "_maintenance",
        "_model_concurrency",
        "_repository",
        "_stop",
        "_wakeups",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLUnitOfWorkFactory,
        wakeups: WorkWakeupBus | None = None,
        model_concurrency: int = 2,
        maintenance_consideration_seconds: int = 57_600,
        maintenance_deadline_seconds: int = 86_400,
        notifier: CreatorProjectionNotifier | None = None,
    ) -> None:
        self._factory = factory
        self._repository = PostgreSQLLifeOpportunityRepository()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
        if type(model_concurrency) is not int or model_concurrency < 1:
            raise LifeViolation("LIFE-SCHEDULER-CONFIG")
        self._model_concurrency = model_concurrency
        self._maintenance = MaintenanceCoordinator(
            factory=factory,
            repository=PostgreSQLMaintenanceRepository(),
            opportunities=self._repository,
            consideration_seconds=maintenance_consideration_seconds,
            deadline_seconds=maintenance_deadline_seconds,
            notifier=notifier,
        )

    async def open(self) -> None:
        try:
            await self._factory.open()
        except DatabaseTransactionError:
            raise LifeViolation("LIFE-DATABASE") from None

    async def close(self) -> None:
        self._stop.set()
        await self._factory.close()

    def stop(self) -> None:
        self._stop.set()

    async def admit_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                result = await self._repository.admit_generation_available(unit_of_work)
        except LifeViolation:
            raise
        except DatabaseTransactionError:
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
                result = await self.admit_attention_once()
                if result.status is OpportunityAdmissionStatus.ADMITTED:
                    self._wakeups.notify(OPPORTUNITY_AVAILABLE)
            except LifeViolation as exc:
                if not exc.code.startswith("LIFE-BACKPRESSURE-") and exc.code not in {
                    "LIFE-SCHEDULER-IDLE",
                    "LIFE-SCHEDULER-COOLDOWN",
                }:
                    raise
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=5)

    async def maintain_sleep_once(self) -> OpportunityAdmissionOutcome:
        try:
            return await self._maintenance.maintain_once()
        except LifeViolation:
            raise
        except DatabaseTransactionError:
            raise LifeViolation("LIFE-DATABASE") from None

    async def admit_life_material_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._repository.admit_life_material_revision(unit_of_work)
        except LifeViolation:
            raise
        except DatabaseTransactionError:
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
        except DatabaseTransactionError:
            raise LifeViolation("LIFE-DATABASE") from None

    async def admit_attention_once(self) -> OpportunityAdmissionOutcome:
        try:
            async with self._factory.unit_of_work(LockPlan()) as unit_of_work:
                return await self._repository.admit_activity_attention(
                    unit_of_work,
                    model_concurrency=self._model_concurrency,
                )
        except LifeViolation:
            raise
        except DatabaseTransactionError:
            raise LifeViolation("LIFE-DATABASE") from None


def compose_life_opportunity_pipeline(
    *,
    factory: PostgreSQLUnitOfWorkFactory,
    wakeups: WorkWakeupBus | None = None,
    model_concurrency: int = 2,
    maintenance_consideration_seconds: int = 57_600,
    maintenance_deadline_seconds: int = 86_400,
    notifier: CreatorProjectionNotifier | None = None,
) -> LifeOpportunityPipeline:
    return LifeOpportunityPipeline(
        factory=factory,
        wakeups=wakeups,
        model_concurrency=model_concurrency,
        maintenance_consideration_seconds=maintenance_consideration_seconds,
        maintenance_deadline_seconds=maintenance_deadline_seconds,
        notifier=notifier,
    )


def build_life_opportunity_pipeline(
    conninfo: str,
    *,
    environment_id: UUID,
    pool_min: int,
    pool_max: int,
    acquire_timeout_seconds: int,
    statement_timeout_seconds: int,
    authority_admission: Callable[[], RuntimeFence],
    wakeups: WorkWakeupBus | None = None,
    model_concurrency: int = 2,
    maintenance_consideration_seconds: int = 57_600,
    maintenance_deadline_seconds: int = 86_400,
    notifier: CreatorProjectionNotifier | None = None,
) -> LifeOpportunityPipeline:
    async def reject_dynamic_lock(connection: Any, target: LockTarget) -> None:
        del connection, target
        raise LifeViolation("LIFE-LOCK")

    factory = PostgreSQLUnitOfWorkFactory(
        conninfo,
        environment_id=environment_id,
        lock_acquirer=reject_dynamic_lock,
        pool_min=pool_min,
        pool_max=pool_max,
        acquire_timeout_seconds=acquire_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        authority_admission=authority_admission,
    )
    return LifeOpportunityPipeline(
        factory=factory,
        wakeups=wakeups,
        model_concurrency=model_concurrency,
        maintenance_consideration_seconds=maintenance_consideration_seconds,
        maintenance_deadline_seconds=maintenance_deadline_seconds,
        notifier=notifier,
    )


__all__ = (
    "LifeOpportunityPipeline",
    "MaintenanceCoordinator",
    "build_life_opportunity_pipeline",
    "compose_life_opportunity_pipeline",
)
