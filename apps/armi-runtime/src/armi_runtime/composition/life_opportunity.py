"""Active P0-S001 autonomous opportunity source pipeline."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from typing import Any
from uuid import UUID

from armi_kernel.application import (
    LifeOpportunitySourcePort,
    LifeViolation,
    LockPlan,
    LockTarget,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
    RuntimeFence,
)

from armi_runtime.adapters.persistence.life_opportunity import (
    PostgreSQLLifeOpportunityRepository,
)
from armi_runtime.adapters.persistence.unit_of_work import PostgreSQLUnitOfWorkFactory
from armi_runtime.adapters.transaction_errors import DatabaseTransactionError

from .work_wakeup import OPPORTUNITY_AVAILABLE, WorkWakeupBus


class LifeOpportunityPipeline(LifeOpportunitySourcePort):
    __slots__ = (
        "_factory",
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
    ) -> None:
        self._factory = factory
        self._repository = PostgreSQLLifeOpportunityRepository()
        self._stop = asyncio.Event()
        self._wakeups = wakeups or WorkWakeupBus()
        if type(model_concurrency) is not int or model_concurrency < 1:
            raise LifeViolation("LIFE-SCHEDULER-CONFIG")
        self._model_concurrency = model_concurrency

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
) -> LifeOpportunityPipeline:
    return LifeOpportunityPipeline(
        factory=factory,
        wakeups=wakeups,
        model_concurrency=model_concurrency,
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
    )


__all__ = (
    "LifeOpportunityPipeline",
    "build_life_opportunity_pipeline",
    "compose_life_opportunity_pipeline",
)
