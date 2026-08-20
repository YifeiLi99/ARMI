"""Runtime bridges from live voice into authoritative owner ports."""

from __future__ import annotations

import json
from uuid import UUID, uuid7

import rfc8785
from armi_artifact_store.api import ArtifactCatalogPort
from armi_artifact_store.content_store import ContentAddressedArtifactStore
from armi_interaction.api import (
    CreatorVoiceInputAcceptance,
    CreatorVoiceInputAcceptancePort,
    CreatorVoiceInputCommand,
    CreatorVoiceInputSuccessorPort,
)
from armi_kernel.application import ArtifactId, ArtifactRef, ArtifactViolation
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId
from armi_live_voice.api import (
    AcceptedVoiceInput,
    LiveVoiceViolation,
    VoiceContext,
)
from armi_mood.api import MoodReadPort
from armi_prompt.api import PromptReadPort
from armi_relationship.api import RelationshipReadPort
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory
from armi_subject_state.api import SubjectStateReadPort


class RuntimeLiveVoiceInteraction:
    """Translate provider-neutral voice calls into the official Creator intake."""

    __slots__ = ("_acceptance", "_scene_key", "_successor")

    def __init__(
        self,
        *,
        acceptance: CreatorVoiceInputAcceptancePort,
        successor: CreatorVoiceInputSuccessorPort,
        scene_key: str,
    ) -> None:
        self._acceptance = acceptance
        self._successor = successor
        self._scene_key = scene_key

    async def accept_once(
        self, *, transcript: str, session_id: UUID, turn_id: UUID
    ) -> AcceptedVoiceInput:
        accepted = await self._acceptance.accept_voice(
            CreatorVoiceInputCommand(
                scene_key=self._scene_key,
                transcript=transcript,
                idempotency_key=IdempotencyKey(
                    f"voice:{session_id.hex}:{turn_id.hex}"
                ),
                trace_id=TraceId(uuid7().hex),
            )
        )
        return AcceptedVoiceInput(
            interaction_id=accepted.interaction_id.value,
            evidence_id=accepted.evidence_id.value,
            request_digest=accepted.request_digest.value,
            content_digest=accepted.content_digest.value,
            newly_accepted=accepted.newly_accepted,
        )

    async def enqueue_appraisal(self, accepted: AcceptedVoiceInput) -> None:
        await self._successor.release_voice_appraisal(_typed_acceptance(accepted))

    async def run_slow(self, accepted: AcceptedVoiceInput) -> None:
        await self._successor.release_voice_slow(_typed_acceptance(accepted))


class RuntimeLiveVoiceContext:
    """Compile a small current-subject prefix for the latency-sensitive model."""

    __slots__ = (
        "_catalog",
        "_factory",
        "_mood",
        "_prompt",
        "_relationship",
        "_storage",
        "_subject_id",
        "_subject_state",
    )

    def __init__(
        self,
        *,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        subject_id: UUID,
        subject_state: SubjectStateReadPort,
        mood: MoodReadPort,
        prompt: PromptReadPort,
        relationship: RelationshipReadPort,
        catalog: ArtifactCatalogPort,
        storage: ContentAddressedArtifactStore,
    ) -> None:
        self._factory = factory
        self._subject_id = subject_id
        self._subject_state = subject_state
        self._mood = mood
        self._prompt = prompt
        self._relationship = relationship
        self._catalog = catalog
        self._storage = storage

    async def compile(self) -> VoiceContext:
        await self._storage.prepare()
        try:
            async with self._factory.unit_of_work(read_only=True) as unit:
                heads = await self._subject_state.current_heads(
                    unit.transaction, subject_id=self._subject_id
                )
                mood = await self._mood.snapshot(
                    unit.transaction, subject_id=self._subject_id
                )
                prompt_sources = await self._prompt.context_sources(
                    unit.transaction, subject_id=self._subject_id
                )
                ordered_sources = tuple(
                    source
                    for source in (
                        prompt_sources.fixed,
                        prompt_sources.creator,
                        prompt_sources.subject,
                    )
                    if source is not None
                )
                refs_list: list[ArtifactRef] = []
                for source in ordered_sources:
                    refs_list.append(
                        await self._catalog.get(unit, ArtifactId(source.artifact_id))
                    )
                refs = tuple(refs_list)
            prompt_value_list: list[str] = []
            for ref in refs:
                prompt_value_list.append(await self._read_prompt(ref))
            prompt_values = tuple(prompt_value_list)
            relationship = await self._relationship.current()
        except LiveVoiceViolation:
            raise
        except Exception:
            raise LiveVoiceViolation(
                "VOICE-CONTEXT-UNAVAILABLE", "voice context is unavailable"
            ) from None

        state_values: list[dict[str, object]] = []
        for head in heads:
            try:
                state = json.loads(head.canonical_state)
            except UnicodeDecodeError, json.JSONDecodeError:
                raise LiveVoiceViolation(
                    "VOICE-CONTEXT-STATE", "subject state is invalid"
                ) from None
            state_values.append(
                {"kind": head.kind.value, "version": head.version, "state": state}
            )
        relationship_value: dict[str, object] | None = None
        if relationship is not None:
            relationship_value = {
                "version": relationship.head_version,
                "status": relationship.current.status.value,
                "interpretation": relationship.current.interpretation,
                "facts": [item.summary for item in relationship.current.facts],
                "boundaries": [
                    {
                        "party": item.party_role.value,
                        "kind": item.kind.value,
                        "action": item.action.value,
                        "summary": item.summary,
                    }
                    for item in relationship.current.boundaries
                ],
                "commitments": [
                    {
                        "party": item.party_role.value,
                        "scope": item.scope,
                        "content": item.content,
                        "status": item.status.value,
                    }
                    for item in relationship.current.commitments
                ],
            }
        mood_value = {
            "version": mood.version,
            "vad": {
                "valence": mood.current.valence,
                "arousal": mood.current.arousal,
                "dominance": mood.current.dominance,
            },
            "emotions": [
                {
                    "family": item.family.value,
                    "nuance": item.nuance,
                    "intensity": item.intensity,
                }
                for item in mood.active_emotions
            ],
            "episodes": [
                {
                    "gist": item.gist,
                    "phase": item.phase.value,
                    "intensity": item.intensity,
                }
                for item in mood.active_episodes
            ],
        }
        version = Digest.from_bytes(
            rfc8785.dumps(
                {
                    "subject": [
                        [head.kind.value, head.version, str(head.current_revision_id)]
                        for head in heads
                    ],
                    "mood": [mood.version, str(mood.current_revision_id)],
                    "prompts": [
                        [source.source_version, str(source.artifact_id)]
                        for source in ordered_sources
                    ],
                    "relationship": None
                    if relationship is None
                    else [
                        relationship.head_version,
                        str(relationship.current_revision_id),
                    ],
                }
            )
        ).value
        sections: list[str] = [
            "你是唯一的 ARMI。实时语音只做当前这一轮的低延迟表达;不要假装工具、外部动作或慢速认知已经完成。",
            *prompt_values,
            "当前主体状态:" + json.dumps(state_values, ensure_ascii=False),
            "当前心境:" + json.dumps(mood_value, ensure_ascii=False),
        ]
        if relationship_value is not None:
            sections.append(
                "与 Creator 的当前关系:"
                + json.dumps(relationship_value, ensure_ascii=False)
            )
        return VoiceContext(version=version, prompt="\n\n".join(sections))

    async def _read_prompt(self, ref: ArtifactRef) -> str:
        value = b""
        try:
            async with await self._storage.open_verified(ref) as stream:
                value = await stream.read()
            text = value.decode("utf-8", errors="strict")
        except ArtifactViolation, OSError, UnicodeError:
            raise LiveVoiceViolation(
                "VOICE-CONTEXT-PROMPT", "voice prompt is unavailable"
            ) from None
        if not text.strip():
            raise LiveVoiceViolation("VOICE-CONTEXT-PROMPT", "voice prompt is empty")
        return text


def _typed_acceptance(value: AcceptedVoiceInput) -> CreatorVoiceInputAcceptance:
    from armi_evidence.api import EvidenceId
    from armi_interaction.api import CreatorInteractionId

    return CreatorVoiceInputAcceptance(
        interaction_id=CreatorInteractionId(value.interaction_id),
        evidence_id=EvidenceId(value.evidence_id),
        request_digest=Digest(value.request_digest),
        content_digest=Digest(value.content_digest),
        newly_accepted=value.newly_accepted,
    )


__all__ = ("RuntimeLiveVoiceContext", "RuntimeLiveVoiceInteraction")
