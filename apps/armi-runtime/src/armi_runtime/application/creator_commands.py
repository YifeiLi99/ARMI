"""Creator commands shared by authenticated Web and machine transports."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable
from uuid import UUID

from armi_codex.api import (
    CodexModel,
    CodexReasoningEffort,
    CreatorCodexTaskAdmissionPort,
    CreatorCodexTaskCommand,
)
from armi_effect.api import (
    EffectArtifactContent,
    EffectArtifactKind,
    EffectId,
    EffectLedgerPort,
    EffectView,
    EffectViolation,
)
from armi_interaction.api import (
    CreatorInputAcceptance,
    CreatorInputAcceptancePort,
    CreatorInputCommand,
    CreatorInputViolation,
    CreatorOperation,
    CreatorOperationQueryPort,
    CreatorSceneCollection,
    CreatorSceneCreateCommand,
    CreatorScenePort,
    CreatorSceneStatusCommand,
    CreatorSceneView,
    OpportunityId,
    SceneKey,
    SceneQueryViolation,
    SceneStatus,
)
from armi_kernel.contracts import IdempotencyKey, TraceId


class CreatorCommands:
    def __init__(
        self,
        *,
        inputs: CreatorInputAcceptancePort | None,
        scenes: CreatorScenePort | None,
        codex: CreatorCodexTaskAdmissionPort[CreatorInputAcceptance] | None,
        accepted: Callable[[CreatorInputAcceptance], Awaitable[None]],
        operations: CreatorOperationQueryPort | None = None,
        effects: EffectLedgerPort | None = None,
    ) -> None:
        self.inputs = inputs
        self.scenes = scenes
        self.codex = codex
        self._accepted = accepted
        self.operations = operations
        self.effects = effects

    async def operation(self, result_ref: str) -> CreatorOperation:
        if self.operations is None:
            raise CreatorInputViolation("INPUT-DEPENDENCY")
        return await self.operations.get(OpportunityId(UUID(result_ref)))

    async def effect(self, effect_id: str, creator_party_id: UUID) -> EffectView:
        if self.effects is None:
            raise EffectViolation("EFFECT-DEPENDENCY")
        return await self.effects.get_effect(
            EffectId(UUID(effect_id)), creator_party_id=creator_party_id
        )

    async def artifact(
        self, effect_id: str, creator_party_id: UUID, kind: EffectArtifactKind
    ) -> EffectArtifactContent:
        if self.effects is None:
            raise EffectViolation("EFFECT-DEPENDENCY")
        return await self.effects.read_artifact(
            EffectId(UUID(effect_id)), creator_party_id=creator_party_id, kind=kind
        )

    async def message(
        self,
        *,
        scene_key: str,
        message: str,
        idempotency_key: str,
        delegate_id: UUID | None,
    ) -> CreatorInputAcceptance:
        if self.inputs is None:
            raise CreatorInputViolation("INPUT-DEPENDENCY")
        result = await self.inputs.accept(
            CreatorInputCommand(
                scene_key=scene_key,
                message=message,
                idempotency_key=IdempotencyKey(idempotency_key),
                trace_id=TraceId(secrets.token_hex(16)),
                delegate_id=delegate_id,
            )
        )
        await self._accepted(result)
        return result

    async def list_scenes(self) -> CreatorSceneCollection:
        if self.scenes is None:
            raise SceneQueryViolation("SCENE-DEPENDENCY")
        return await self.scenes.list()

    async def create_scene(self, scene_key: str) -> CreatorSceneView:
        if self.scenes is None:
            raise SceneQueryViolation("SCENE-DEPENDENCY")
        return await self.scenes.create(
            CreatorSceneCreateCommand(
                SceneKey(scene_key),
                TraceId(secrets.token_hex(16)),
            )
        )

    async def transition_scene(
        self, scene_key: str, status: SceneStatus
    ) -> CreatorSceneView:
        if self.scenes is None:
            raise SceneQueryViolation("SCENE-DEPENDENCY")
        return await self.scenes.set_status(
            CreatorSceneStatusCommand(
                SceneKey(scene_key),
                status,
                TraceId(secrets.token_hex(16)),
            )
        )

    async def submit_codex(
        self,
        *,
        scene_key: str,
        objective: str,
        idempotency_key: str,
        model: CodexModel,
        reasoning: CodexReasoningEffort,
        web_search: bool,
        delegate_id: UUID | None,
    ) -> CreatorInputAcceptance:
        from armi_codex.api import CodexDelegationViolation

        if self.codex is None:
            raise CodexDelegationViolation("CODEX-TASK-DEPENDENCY")
        return await self.codex.accept(
            CreatorCodexTaskCommand(
                scene_key,
                objective,
                IdempotencyKey(idempotency_key),
                TraceId(secrets.token_hex(16)),
                model,
                reasoning,
                web_search,
                delegate_id,
            )
        )


__all__ = ("CreatorCommands",)
