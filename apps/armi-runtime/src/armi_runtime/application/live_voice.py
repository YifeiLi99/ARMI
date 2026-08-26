"""Runtime bridges from live voice into authoritative owner ports."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid7

from armi_effect.api import (
    ActionAdapterPort,
    EffectAdapterReceipt,
    EffectDeliveryId,
    EffectViolation,
    FrozenEffectRequest,
)
from armi_interaction.api import (
    CreatorVoiceInputAcceptancePort,
    CreatorVoiceInputCommand,
)
from armi_kernel.contracts import Digest, IdempotencyKey, Instant, TraceId
from armi_live_voice.api import (
    AcceptedVoiceInput,
    LiveVoiceRuntimePort,
    LiveVoiceViolation,
    VoiceContextReadPort,
)
from armi_runtime_foundation import PostgreSQLRuntimeUnitOfWorkFactory


class RuntimeLiveVoiceInteraction:
    """Translate provider-neutral voice calls into the official Creator intake."""

    __slots__ = ("_acceptance", "_scene_key")

    def __init__(
        self,
        *,
        acceptance: CreatorVoiceInputAcceptancePort,
        scene_key: str,
    ) -> None:
        self._acceptance = acceptance
        self._scene_key = scene_key

    async def accept_once(
        self, *, transcript: str, session_id: UUID, turn_id: UUID
    ) -> AcceptedVoiceInput:
        accepted = await self._acceptance.accept_voice(
            CreatorVoiceInputCommand(
                scene_key=self._scene_key,
                transcript=transcript,
                idempotency_key=IdempotencyKey(f"voice:{session_id.hex}:{turn_id.hex}"),
                trace_id=TraceId(uuid7().hex),
            )
        )
        return AcceptedVoiceInput(
            interaction_id=accepted.interaction_id.value,
            evidence_id=accepted.evidence_id.value,
            opportunity_id=accepted.opportunity_id.value,
            request_digest=accepted.request_digest.value,
            content_digest=accepted.content_digest.value,
            newly_accepted=accepted.newly_accepted,
        )


class RuntimeLiveVoiceEffectAdapter(ActionAdapterPort):
    """Dispatch a registered live-voice effect and observe its durable playback."""

    def __init__(
        self,
        *,
        service: LiveVoiceRuntimePort,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        read: VoiceContextReadPort,
    ) -> None:
        self._service = service
        self._factory = factory
        self._read = read

    def validate(self, request: FrozenEffectRequest) -> None:
        if (
            request.destination_kind != "live_voice_audio"
            or request.live_voice_turn_id is None
        ):
            raise EffectViolation("EFFECT-VOICE-ROUTE")

    async def dispatch(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> EffectAdapterReceipt:
        self.validate(request)
        turn_id = request.live_voice_turn_id
        assert turn_id is not None
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeError:
            raise EffectViolation("EFFECT-VOICE-PAYLOAD") from None
        try:
            await self._service.play_effect(turn_id=turn_id, text=text)
        except LiveVoiceViolation as error:
            if error.code in {
                "VOICE-PLAYBACK-COUNT",
                "VOICE-PLAYBACK-UNKNOWN",
                "VOICE-PLAYBACK-CANCELLED",
                "VOICE-PLAYBACK-RESULT-UNKNOWN",
            }:
                raise EffectViolation("EFFECT-RESULT-UNKNOWN") from error
            raise EffectViolation("EFFECT-RECEIVER-NOT-DELIVERED") from error
        receipt = await self.observe(request)
        if receipt is None:
            raise EffectViolation("EFFECT-VOICE-RESULT-UNKNOWN")
        return replace(receipt, duplicate=False)

    async def observe(
        self, request: FrozenEffectRequest
    ) -> EffectAdapterReceipt | None:
        self.validate(request)
        turn_id = request.live_voice_turn_id
        assert turn_id is not None
        async with self._factory.unit_of_work(read_only=True) as unit:
            result = await self._read.completed_playback(
                unit.transaction, turn_id=turn_id
            )
        if result is None:
            return None
        attempt_id, text, settled_at = result
        return EffectAdapterReceipt(
            EffectDeliveryId(attempt_id),
            Digest.from_bytes(text.encode("utf-8")),
            Instant(settled_at),
            duplicate=True,
            external_receiver_ref=f"live_voice:{turn_id}",
        )


class RuntimeLiveVoiceResultObserver:
    """Release a voice turn only after its committed cognition has no reply."""

    def __init__(
        self,
        *,
        service: LiveVoiceRuntimePort,
        factory: PostgreSQLRuntimeUnitOfWorkFactory,
        read: VoiceContextReadPort,
    ) -> None:
        self._service = service
        self._factory = factory
        self._read = read

    async def committed(
        self,
        *,
        root_opportunity_id: UUID,
        has_reply: bool,
        awaits_followup: bool,
    ) -> None:
        if has_reply or awaits_followup:
            return
        async with self._factory.unit_of_work(read_only=True) as unit:
            turn_id = await self._read.turn_for_opportunity(
                unit.transaction, opportunity_id=root_opportunity_id
            )
        if turn_id is not None:
            await self._service.complete_silently(turn_id=turn_id)


__all__ = (
    "RuntimeLiveVoiceEffectAdapter",
    "RuntimeLiveVoiceInteraction",
    "RuntimeLiveVoiceResultObserver",
)
