"""Creator commands shared by authenticated Web and machine transports."""

from __future__ import annotations

import hashlib
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

from .artifact_transfer import ArtifactChunk, ArtifactReadWindow
from .creator_projection import creator_visible_codex_artifact


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

    async def artifact_chunk(
        self,
        effect_id: str,
        creator_party_id: UUID,
        kind: EffectArtifactKind,
        window: ArtifactReadWindow,
    ) -> tuple[ArtifactChunk, bytes, str]:
        artifact = await self.artifact(effect_id, creator_party_id, kind)
        content, media_type = creator_visible_codex_artifact(
            kind, artifact.content, artifact.media_type
        )
        if window.offset > len(content):
            raise ValueError("INTERACTION-ARTIFACT-RANGE")
        chunk = content[window.offset : window.offset + window.length]
        end = window.offset + len(chunk)
        return (
            ArtifactChunk(
                offset=window.offset,
                byte_count=len(chunk),
                total_bytes=len(content),
                digest="sha256:" + hashlib.sha256(content).hexdigest(),
                next_offset=None if end == len(content) else end,
            ),
            chunk,
            media_type,
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
