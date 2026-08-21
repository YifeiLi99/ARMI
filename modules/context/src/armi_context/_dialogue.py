"""One owner-aware reader for recent observable scene dialogue."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from armi_artifact_store import ContentAddressedArtifactStore
from armi_effect.api import EffectOperationReadPort
from armi_evidence.api import EvidenceReadPort
from armi_expression.api import ExpressionIntentReadPort
from armi_interaction.api import InteractionContextReadPort, InteractionContextTurn
from armi_kernel.application import (
    ArtifactId,
    ArtifactIntegrityStatus,
    ArtifactPrivacyScope,
    ArtifactRef,
    ArtifactViolation,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWork

from .api import (
    ContextArtifactCatalogPort,
    ContextDialogueItem,
    ContextViolation,
    ContextVoiceResponseReadPort,
)


class PostgreSQLContextDialogueRead:
    def __init__(
        self,
        *,
        storage: ContentAddressedArtifactStore,
        catalog: ContextArtifactCatalogPort,
        evidence: EvidenceReadPort,
        interaction: InteractionContextReadPort,
        expression: ExpressionIntentReadPort,
        effects: EffectOperationReadPort,
        voice: ContextVoiceResponseReadPort,
    ) -> None:
        self._storage = storage
        self._catalog = catalog
        self._evidence = evidence
        self._interaction = interaction
        self._expression = expression
        self._effects = effects
        self._voice = voice

    async def recent_creator_dialogue(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
        before_interaction_id: UUID | None = None,
        before_time: datetime | None = None,
        limit: int = 8,
    ) -> tuple[ContextDialogueItem, ...]:
        return await self._recent(
            unit_of_work,
            scene_id=scene_id,
            before_interaction_id=before_interaction_id,
            before_time=before_time,
            source_kinds=("creator_input", "party_response", "live_voice_response"),
            human_speaker="creator",
            limit=limit,
        )

    async def recent_other_human_dialogue(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
        before_interaction_id: UUID | None = None,
        before_time: datetime | None = None,
        limit: int = 8,
    ) -> tuple[ContextDialogueItem, ...]:
        return await self._recent(
            unit_of_work,
            scene_id=scene_id,
            before_interaction_id=before_interaction_id,
            before_time=before_time,
            source_kinds=("other_human_input", "party_response"),
            human_speaker="other_human",
            limit=limit,
        )

    async def _recent(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        *,
        scene_id: UUID,
        before_interaction_id: UUID | None,
        before_time: datetime | None,
        source_kinds: tuple[str, ...],
        human_speaker: str,
        limit: int,
    ) -> tuple[ContextDialogueItem, ...]:
        await self._storage.prepare()
        turns = await self._interaction.recent_context_turns(
            unit.transaction,
            scene_id=scene_id,
            before_interaction_id=before_interaction_id,
            before_time=before_time,
            source_kinds=source_kinds,
            limit=limit,
        )
        items: list[ContextDialogueItem] = []
        for turn in turns:
            item = await self._resolve(unit, turn, human_speaker=human_speaker)
            if item is not None:
                items.append(item)
        return tuple(items[-limit:])

    async def _resolve(
        self,
        unit: PostgreSQLRuntimeUnitOfWork,
        turn: InteractionContextTurn,
        *,
        human_speaker: str,
    ) -> ContextDialogueItem | None:
        if turn.source_kind == "live_voice_response":
            response = await self._voice.completed_response_text(
                unit.transaction, turn_id=turn.source_ref
            )
            if response is None:
                return None
            return ContextDialogueItem(
                turn.timeline_item_id,
                turn.source_event_no,
                "armi",
                response,
                turn.occurred_at,
                "live_voice",
            )

        artifact_id: UUID | None = None
        speaker = "armi"
        modality = "text"
        if turn.source_kind in {"creator_input", "other_human_input"}:
            evidence_id = await self._evidence.find_by_interaction(
                unit.transaction, interaction_id=turn.source_ref
            )
            if evidence_id is not None:
                artifact_id = (
                    await self._evidence.snapshot(
                        unit.transaction, evidence_id=evidence_id
                    )
                ).artifact_id
            speaker = human_speaker
            modality = turn.modality or "text"
        elif turn.source_kind == "party_response":
            effect = await self._effects.by_effect_id(
                unit.transaction, effect_id=turn.source_ref
            )
            if effect is not None:
                intent = await self._expression.revision_snapshot(
                    unit.transaction,
                    action_intent_revision_id=effect.action_intent_revision_id,
                )
                artifact_id = intent.response_artifact_id
        if artifact_id is None:
            return None
        ref = await self._artifact_ref(unit, artifact_id)
        expected_kind = self._logical_kind(
            speaker=speaker, modality=modality, human_speaker=human_speaker
        )
        expected_privacy = (
            ArtifactPrivacyScope.CREATOR_VISIBLE
            if speaker == "creator"
            else ArtifactPrivacyScope.PRIVATE
        )
        text = await self._read_text(ref, expected_kind, expected_privacy)
        return ContextDialogueItem(
            turn.timeline_item_id,
            turn.source_event_no,
            speaker,
            text,
            turn.occurred_at,
            modality,
            turn.speaker_label,
        )

    @staticmethod
    def _logical_kind(*, speaker: str, modality: str, human_speaker: str) -> str:
        if speaker == "creator":
            return (
                "creator.input.live_voice.transcript"
                if modality == "live_voice"
                else "creator.input.text"
            )
        if speaker == "other_human":
            return "other_human.input.text"
        return (
            "creator.response.text"
            if human_speaker == "creator"
            else "other-human.response.text"
        )

    async def _artifact_ref(
        self, unit: PostgreSQLRuntimeUnitOfWork, artifact_id: UUID
    ) -> ArtifactRef:
        try:
            ref = await self._catalog.retained_ref(unit, ArtifactId(artifact_id))
        except ArtifactViolation:
            raise ContextViolation("CTX-SOURCE-INVALID") from None
        if ref is None:
            raise ContextViolation("CTX-SOURCE-MISSING")
        return ref

    async def _read_text(
        self,
        ref: ArtifactRef,
        logical_kind: str,
        privacy: ArtifactPrivacyScope,
    ) -> str:
        if (
            ref.integrity_status is not ArtifactIntegrityStatus.VERIFIED
            or ref.media_type != "text/plain"
            or ref.logical_kind != logical_kind
            or ref.privacy_scope is not privacy
        ):
            raise ContextViolation("CTX-SOURCE-READ-FAILED")
        value = b""
        text = ""
        try:
            async with await self._storage.open_verified(ref) as stream:
                value = await stream.read()
            text = value.decode("utf-8", errors="strict")
        except ArtifactViolation, OSError, UnicodeError:
            raise ContextViolation("CTX-SOURCE-READ-FAILED") from None
        if not value or len(value) > 65536 or "\x00" in text or not text.strip():
            raise ContextViolation("CTX-SOURCE-READ-FAILED")
        return text


__all__ = ("PostgreSQLContextDialogueRead",)
