"""Runtime coordination facts for owner-only Opportunity admission."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from armi_activity.api import ActivityReadPort
from armi_capability.api import CapabilityOperationReadPort
from armi_cognition.api import CognitionOperationReadPort
from armi_effect.api import EffectOperationReadPort
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import InteractionIdentityPort
from armi_opportunity.api import (
    AttentionRetryFacts,
    CreatorOutreachFacts,
    LifeGenerationFacts,
    LifeOpportunityFactsPort,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork, PostgreSQLTransaction


class RuntimeLifeOpportunityFacts(LifeOpportunityFactsPort):
    __slots__ = (
        "_activities",
        "_capabilities",
        "_cognition",
        "_effects",
        "_expression",
        "_interaction",
    )

    def __init__(
        self,
        *,
        activities: ActivityReadPort,
        capabilities: CapabilityOperationReadPort,
        cognition: CognitionOperationReadPort,
        effects: EffectOperationReadPort,
        expression: ExpressionIntentReadPort,
        interaction: InteractionIdentityPort,
    ) -> None:
        self._activities = activities
        self._capabilities = capabilities
        self._cognition = cognition
        self._effects = effects
        self._expression = expression
        self._interaction = interaction

    async def generation(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> LifeGenerationFacts:
        fence = unit_of_work.runtime_fence
        if fence is None:
            raise RuntimeError("LIFE-FENCE-REQUIRED")
        row = await (
            await unit_of_work.transaction.execute(
                """SELECT generation_no,activation_reason,created_at
                   FROM armi.life_generations
                   WHERE life_generation_id=%s AND subject_id=%s AND status='active'""",
                (fence.life_generation_id, fence.subject_id),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError("LIFE-SOURCE-STALE")
        return LifeGenerationFacts(int(row[0]), str(row[1]), row[2])

    async def active_cognition_count(
        self, transaction: PostgreSQLTransaction, *, subject_id: UUID
    ) -> int:
        return await self._cognition.active_count(transaction, subject_id=subject_id)

    async def attention_retry(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        root_opportunity_id: UUID,
        resolved_at: datetime | None,
    ) -> AttentionRetryFacts:
        episodes = await self._cognition.opportunity_episode_states(
            transaction, opportunity_id=root_opportunity_id
        )
        failed = (
            any(status in {"failed", "candidate_rejected"} for _, status in episodes)
            and resolved_at is not None
            and resolved_at + timedelta(seconds=60) <= datetime.now(UTC)
        )
        completed = tuple(
            episode_id for episode_id, status in episodes if status == "completed"
        )
        need_at = await self._activities.need_information_after(
            transaction, episode_ids=completed
        )
        creator_input = False
        if need_at is not None:
            scenes = await self._interaction.outreach_scenes(
                transaction,
                subject_id=subject_id,
            )
            creator_input = any(
                scene.latest_input_at is not None and scene.latest_input_at > need_at
                for scene in scenes
            )
        return AttentionRetryFacts(failed, need_at, creator_input)

    async def outreach(
        self, unit_of_work: PostgreSQLRuntimeUnitOfWork
    ) -> CreatorOutreachFacts | None:
        fence = unit_of_work.runtime_fence
        if fence is None:
            return None
        transaction = unit_of_work.transaction
        generation = await self.generation(unit_of_work)
        scenes = await self._interaction.outreach_scenes(
            transaction, subject_id=fence.subject_id
        )
        if not scenes:
            return None
        selected = scenes[0]
        for scene in scenes:
            if await self._capabilities.has_scene_reply_grant(
                transaction,
                subject_id=fence.subject_id,
                scene_id=scene.scene_id,
                creator_party_id=scene.creator_party_id,
            ):
                selected = scene
                break
        awaiting = False
        intents = await self._expression.outreach_intents(
            transaction,
            subject_id=fence.subject_id,
            scene_id=selected.scene_id,
            context_party_id=selected.creator_party_id,
        )
        for intent in intents:
            if await self._interaction.input_after(
                transaction,
                scene_id=selected.scene_id,
                party_id=selected.creator_party_id,
                after=intent.created_at,
            ):
                continue
            policy = await self._capabilities.policy_for_revision(
                transaction,
                action_intent_revision_id=intent.action_intent_revision_id,
            )
            if policy is None:
                awaiting = True
                break
            if policy.outcome.value == "allowed":
                effect = await self._effects.by_action_intent(
                    transaction, action_intent_id=intent.action_intent_id
                )
                if effect is None or effect.status.value in {
                    "registered",
                    "dispatching",
                    "unknown",
                }:
                    awaiting = True
                    break
        return CreatorOutreachFacts(
            selected.scene_id,
            selected.creator_party_id,
            selected.latest_input_id,
            selected.latest_input_at,
            fence.life_generation_id,
            generation.generation_no,
            generation.created_at,
            datetime.now(UTC),
            awaiting,
            await self._cognition.last_purpose_created_at(
                transaction,
                subject_id=fence.subject_id,
                purpose="consider_creator_outreach",
            ),
            selected.latest_timeline_at,
        )


__all__ = ("RuntimeLifeOpportunityFacts",)
