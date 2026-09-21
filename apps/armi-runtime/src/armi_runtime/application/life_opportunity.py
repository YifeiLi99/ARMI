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
from armi_live_voice.api import VoiceActivityState
from armi_mind.api import MindReadPort
from armi_mood.api import MoodReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction

from armi_runtime.application.cognition_cycle import RuntimeCognitionState


class RuntimeLifeOpportunityFacts(LifeOpportunityFactsPort):
    __slots__ = (
        "_cognition",
        "_interaction",
        "_mind",
        "_model_revision",
        "_mood",
        "_outlet_health",
        "_voice_activity",
    )

    def __init__(
        self,
        *,
        cognition: CognitionOperationReadPort,
        interaction: InteractionIdentityPort,
        mood: MoodReadPort,
        mind: MindReadPort,
        outlet_health: Callable[[str], Awaitable[tuple[str, str | None]]],
        model_revision: Callable[[], str],
        voice_activity_state: VoiceActivityState | None = None,
    ) -> None:
        self._cognition = cognition
        self._interaction = interaction
        self._mood = mood
        self._mind = mind
        self._outlet_health = outlet_health
        self._model_revision = model_revision
        self._voice_activity = voice_activity_state

    def model_configuration_revision(self) -> str:
        return self._model_revision()

    async def outlet_health(self, outlet: str) -> tuple[str, str | None]:
        return await self._outlet_health(outlet)

    async def consideration_signals(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        minimum_delay_seconds: int,
    ) -> tuple[ConsiderationSignal, ...]:
        mind = await self._mind.consideration_signals(
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

    async def autonomy_idle(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
    ) -> bool:
        from armi_attention.api import human_opportunity_pending
        from armi_effect.api import response_delivery_activity, response_intent_ids
        from armi_interaction.api import human_input_activity
        from armi_live_voice.api import voice_activity

        input_busy, input_at = await human_input_activity(
            transaction, subject_id=subject_id
        )
        voice_busy, voice_at = await voice_activity(
            transaction, subject_id=subject_id, activity=self._voice_activity
        )
        reply_busy, reply_at = await response_delivery_activity(
            transaction,
            action_intent_ids=await response_intent_ids(
                transaction, subject_id=subject_id
            ),
        )
        if (
            input_busy
            or voice_busy
            or reply_busy
            or await human_opportunity_pending(transaction, subject_id=subject_id)
        ):
            return False
        row = await (
            await transaction.execute("SELECT statement_timestamp()")
        ).fetchone()
        if row is None:
            return False
        times = [value for value in (input_at, voice_at, reply_at) if value is not None]
        return not times or (row[0] - max(times)).total_seconds() >= 60

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
