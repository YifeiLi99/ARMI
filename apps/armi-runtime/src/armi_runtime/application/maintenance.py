"""Runtime-owned facts needed by the Sleep maintenance coordinator."""

from __future__ import annotations

from armi_cognition.api import CognitionOperationReadPort
from armi_effect.api import EffectObservationPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork
from armi_sleep.api import SleepRuntimeFactsPort, SleepRuntimeSnapshot


class RuntimeSleepFacts(SleepRuntimeFactsPort):
    __slots__ = ("_cognition", "_effects")

    def __init__(
        self,
        *,
        cognition: CognitionOperationReadPort,
        effects: EffectObservationPort,
    ) -> None:
        self._cognition = cognition
        self._effects = effects

    async def snapshot(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> SleepRuntimeSnapshot:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise RuntimeError("SLEEP-FENCE-REQUIRED")
        row = await (
            await unit_of_work.transaction.execute(
                """SELECT generation.created_at, generation.generation_no,
                          subject.subject_version, subject.state_epoch
                   FROM armi.life_generations AS generation
                   JOIN armi.subjects AS subject ON subject.subject_id=generation.subject_id
                   WHERE generation.life_generation_id=%s AND generation.subject_id=%s
                     AND generation.status='active' AND subject.status='active'""",
                (fence.life_generation_id, fence.subject_id),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("SLEEP-SOURCE-STALE")
        return SleepRuntimeSnapshot(row[0], int(row[1]), int(row[2]), int(row[3]))

    async def safe_for_maintenance(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> bool:
        fence = unit_of_work.runtime_fence
        if fence is None:
            return False
        transaction = unit_of_work.transaction
        leased = await (
            await transaction.execute(
                "SELECT count(*) FROM armi.durable_work WHERE subject_id=%s AND status='leased'",
                (fence.subject_id,),
            )
        ).fetchone()
        cognition = await self._cognition.active_count(
            transaction, subject_id=fence.subject_id
        )
        effects = await self._effects.observe(transaction)
        active_effects = sum(
            count
            for status, count in effects.counts
            if status in {"registered", "dispatching"}
        )
        return (
            int(leased[0] if leased is not None else 0) == 0
            and cognition == 0
            and active_effects == 0
        )


__all__ = ("RuntimeSleepFacts",)
