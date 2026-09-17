"""Runtime coordination facts for owner-only Opportunity admission."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from armi_attention.api import (
    CreatorOutreachFacts,
    LifeOpportunityFactsPort,
)
from armi_cognition.api import CognitionOperationReadPort
from armi_interaction.api import InteractionIdentityPort
from armi_kernel.application import ConsiderationSignal
from armi_mood.api import MoodReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction
from armi_subject_state.api import SubjectStateReadPort

from armi_runtime.application.cognition_cycle import RuntimeCognitionState


class RuntimeLifeOpportunityFacts(LifeOpportunityFactsPort):
    __slots__ = (
        "_cognition",
        "_interaction",
        "_mood",
        "_outlet_health",
        "_subject_state",
    )

    def __init__(
        self,
        *,
        cognition: CognitionOperationReadPort,
        interaction: InteractionIdentityPort,
        mood: MoodReadPort,
        subject_state: SubjectStateReadPort,
        outlet_health: Callable[[str], Awaitable[tuple[str, str | None]]],
    ) -> None:
        self._cognition = cognition
        self._interaction = interaction
        self._mood = mood
        self._subject_state = subject_state
        self._outlet_health = outlet_health

    async def outlet_health(self, outlet: str) -> tuple[str, str | None]:
        return await self._outlet_health(outlet)

    async def consideration_signals(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        minimum_delay_seconds: int,
    ) -> tuple[ConsiderationSignal, ...]:
        mind = await self._subject_state.consideration_signals(
            transaction,
            subject_id=subject_id,
        )
        mood = await self._mood.consideration_signals(
            transaction,
            subject_id=subject_id,
            minimum_delay_seconds=minimum_delay_seconds,
        )
        own_commits = await self._cognition.autonomous_commit_ids(
            transaction,
            commit_ids=tuple(
                signal.source_commit_id
                for signal in mood
                if signal.source_commit_id is not None
            ),
        )
        return (
            *mind,
            *(signal for signal in mood if signal.source_commit_id not in own_commits),
        )

    async def state_epoch(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        state = await RuntimeCognitionState().current_subject(
            transaction, subject_id=subject_id
        )
        return state.state_epoch

    async def active_cognition_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        return await self._cognition.active_count(transaction, subject_id=subject_id)

    async def outreach(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork, *, outlet: str | None = None
    ) -> CreatorOutreachFacts | None:
        fence = unit_of_work.runtime_fence
        if fence is None:
            return None
        transaction = unit_of_work.transaction
        scenes = await self._interaction.outreach_scenes(
            transaction, subject_id=fence.subject_id
        )
        if outlet is not None:
            scenes = tuple(scene for scene in scenes if scene.outlet == outlet)
        if not scenes:
            return None
        selected = scenes[0]
        return CreatorOutreachFacts(
            selected.scene_id,
            selected.creator_party_id,
        )


__all__ = ("RuntimeLifeOpportunityFacts",)
