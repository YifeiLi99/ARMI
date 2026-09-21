"""The half-duplex real-time voice application service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from uuid import UUID, uuid7

from armi_kernel.application import (
    PriceCatalog,
    ProviderCallReceipt,
    ProviderMeterScope,
    provider_meter_scope,
)

from .api import (
    AttemptOutcome,
    AudioDevicePort,
    HalfDuplexStateMachine,
    LiveVoiceBinding,
    LiveVoiceSessionState,
    LiveVoiceViolation,
    StreamingAsrPort,
    StreamingTtsPort,
    VoiceExpressionPort,
    VoiceInputAcceptancePort,
    VoiceJournalPort,
    VoiceModelCompatibilityPort,
    VoiceProviderBinding,
    VoiceProviderDiagnostic,
    VoiceTurnSnapshot,
)


@dataclass(frozen=True, slots=True)
class _ProviderCall:
    identity: UUID
    turn_id: UUID | None
    session_id: UUID | None
    binding: VoiceProviderBinding


class LiveVoiceService:
    """Own one explicit local session; it never survives Runtime restart."""

    def __init__(
        self,
        *,
        audio: AudioDevicePort,
        asr: StreamingAsrPort,
        model: VoiceModelCompatibilityPort,
        tts: StreamingTtsPort,
        inputs: VoiceInputAcceptancePort,
        expression: VoiceExpressionPort,
        journal: VoiceJournalPort,
        binding: LiveVoiceBinding,
        prices: PriceCatalog,
        provider_diagnostic: Callable[[VoiceProviderDiagnostic], None] | None = None,
    ) -> None:
        self._audio = audio
        self._asr = asr
        self._model = model
        self._tts = tts
        self._inputs = inputs
        self._expression = expression
        self._journal = journal
        self._binding = binding
        self._prices = prices
        self._provider_diagnostic = provider_diagnostic
        self._machine = HalfDuplexStateMachine()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._session_id: UUID | None = None
        self._last_error: str | None = None
        self._turn_no = 0
        self._pending_effects: dict[
            UUID, asyncio.Future[tuple[AttemptOutcome, str, bool]]
        ] = {}

    def status(self) -> LiveVoiceSessionState:
        return self._machine.state

    async def recent_turn(self) -> VoiceTurnSnapshot | None:
        return await self._journal.recent_turn()

    @property
    def last_error(self) -> str | None:
        return self._last_error

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._machine.transition(LiveVoiceSessionState.STARTING)
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._session_id = uuid7()
        self._last_error = None
        self._turn_no = 0
        self._task = asyncio.create_task(self._run(), name="armi-live-voice")
        await self._ready.wait()

    async def stop(self) -> None:
        task = self._task
        if task is None:
            if self._machine.state is LiveVoiceSessionState.UNAVAILABLE:
                self._machine.transition(LiveVoiceSessionState.IDLE)
            return
        self._stop.set()
        await self._audio.close()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        await self._tts.close()
        assert self._session_id is not None
        await self._journal.close_session(session_id=self._session_id)
        self._task = None
        if self._machine.state is not LiveVoiceSessionState.IDLE:
            self._machine.transition(LiveVoiceSessionState.IDLE)

    async def _run(self) -> None:
        assert self._session_id is not None
        try:
            await self._journal.open_session(session_id=self._session_id)
            await asyncio.gather(
                self._prepare_model(),
                self._tts.prepare(),
            )
            await self._transition(
                LiveVoiceSessionState.LISTENING,
                context_version="armi.creator-voice-act-candidate.v7",
            )
            self._ready.set()
            while not self._stop.is_set():
                await self._one_turn()
        except asyncio.CancelledError:
            raise
        except LiveVoiceViolation as error:
            self._last_error = error.code
            self._machine.transition(LiveVoiceSessionState.UNAVAILABLE)
            with suppress(Exception):
                await self._journal.close_session(
                    session_id=self._session_id, error_code=error.code
                )
            self._ready.set()
        except Exception:
            self._last_error = "VOICE-RUNTIME-FAILED"
            self._machine.transition(LiveVoiceSessionState.UNAVAILABLE)
            with suppress(Exception):
                await self._journal.close_session(
                    session_id=self._session_id,
                    error_code="VOICE-RUNTIME-FAILED",
                )
            self._ready.set()

    async def _one_turn(self) -> None:
        assert self._session_id is not None
        self._turn_no += 1
        turn_id = uuid7()
        await self._journal.begin_turn(
            session_id=self._session_id,
            turn_id=turn_id,
            turn_no=self._turn_no,
            context_version="armi.creator-voice-act-candidate.v7",
        )
        try:
            outcome, _spoken, silent = await self._execute_turn(turn_id)
        except asyncio.CancelledError:
            await self._journal.settle_turn(
                turn_id=turn_id,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-TURN-CANCELLED",
            )
            raise
        except LiveVoiceViolation as error:
            await self._journal.settle_turn(
                turn_id=turn_id,
                outcome=AttemptOutcome.FAILED,
                error_code=error.code,
            )
            raise
        except Exception:
            await self._journal.settle_turn(
                turn_id=turn_id,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-TURN-UNKNOWN",
            )
            raise
        await self._journal.settle_turn(
            turn_id=turn_id,
            outcome=outcome,
            silent=silent,
        )
        await self._transition(LiveVoiceSessionState.LISTENING)

    def _begin_provider_call(
        self,
        *,
        turn_id: UUID | None,
        binding: VoiceProviderBinding,
        session_id: UUID | None = None,
    ) -> _ProviderCall:
        call = _ProviderCall(uuid7(), turn_id, session_id, binding)
        self._provider_event(call=call, event="prepared")
        return call

    def _provider_event(
        self,
        *,
        call: _ProviderCall,
        event: str,
        outcome: AttemptOutcome | None = None,
        error_code: str | None = None,
    ) -> None:
        if self._provider_diagnostic is not None:
            self._provider_diagnostic(
                VoiceProviderDiagnostic(
                    event,
                    str(call.identity),
                    None if call.turn_id is None else str(call.turn_id),
                    None if call.session_id is None else str(call.session_id),
                    call.binding.service.value,
                    call.binding.provider,
                    call.binding.resource_id,
                    call.binding.model_identity,
                    None if outcome is None else outcome.value,
                    error_code,
                )
            )

    def _meter_scope(self, call: _ProviderCall, purpose: str) -> ProviderMeterScope:
        async def save(receipt: ProviderCallReceipt) -> None:
            await self._journal.record_provider_call(
                turn_id=call.turn_id, session_id=call.session_id, receipt=receipt
            )

        return ProviderMeterScope(save, self._prices, purpose)

    async def _prepare_model(self) -> None:
        assert self._session_id is not None
        attempt = self._begin_provider_call(
            turn_id=None,
            session_id=self._session_id,
            binding=self._binding.llm,
        )
        try:
            self._provider_event(event="dispatched", call=attempt)
            with provider_meter_scope(
                self._meter_scope(attempt, "voice_compatibility")
            ):
                await self._model.prepare()
        except BaseException:
            self._provider_event(
                event="settled",
                call=attempt,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-LLM-PREPARE-FAILED",
            )
            raise
        self._provider_event(
            event="settled", call=attempt, outcome=AttemptOutcome.COMPLETED
        )

    async def _execute_turn(self, turn_id: UUID) -> tuple[AttemptOutcome, str, bool]:
        await self._transition(LiveVoiceSessionState.RECOGNIZING)
        asr_attempt = self._begin_provider_call(
            turn_id=turn_id, binding=self._binding.asr
        )
        transcript = ""
        received_asr = False
        try:
            self._provider_event(event="dispatched", call=asr_attempt)
            with provider_meter_scope(self._meter_scope(asr_attempt, "voice_asr")):
                async for event in self._asr.recognize(self._audio.capture()):
                    if not received_asr:
                        self._provider_event(event="first_result", call=asr_attempt)
                        received_asr = True
                    transcript = event.text
                    if event.utterance_ended:
                        break
        except asyncio.CancelledError:
            self._provider_event(
                event="settled",
                call=asr_attempt,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-ASR-CANCELLED",
            )
            raise
        except LiveVoiceViolation as error:
            self._provider_event(
                event="settled",
                call=asr_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if received_asr else AttemptOutcome.FAILED
                ),
                error_code=error.code,
            )
            raise
        except Exception as error:
            self._provider_event(
                event="settled",
                call=asr_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if received_asr else AttemptOutcome.UNKNOWN
                ),
                error_code="VOICE-ASR-UNKNOWN",
            )
            raise LiveVoiceViolation(
                "VOICE-ASR-UNKNOWN", "speech recognition failed"
            ) from error
        self._provider_event(
            event="settled", call=asr_attempt, outcome=AttemptOutcome.COMPLETED
        )
        if not transcript.strip():
            await self._journal.record_transcript(
                turn_id=turn_id,
                transcript=None,
                interaction_id=None,
                opportunity_id=None,
            )
            return AttemptOutcome.COMPLETED, "", False
        await self._transition(LiveVoiceSessionState.THINKING)
        assert self._session_id is not None
        accepted = await self._inputs.accept_once(
            transcript=transcript,
            session_id=self._session_id,
            turn_id=turn_id,
        )
        await self._journal.record_transcript(
            turn_id=turn_id,
            transcript=transcript.strip(),
            interaction_id=accepted.interaction_id,
            opportunity_id=accepted.opportunity_id,
        )
        completion = asyncio.get_running_loop().create_future()
        self._pending_effects[turn_id] = completion
        try:
            return await completion
        finally:
            self._pending_effects.pop(turn_id, None)

    async def play_effect(self, *, turn_id: UUID, text: str) -> int:
        """Play one committed live-voice effect exactly once."""
        completion = self._pending_effects.get(turn_id)
        if completion is None or completion.done():
            raise LiveVoiceViolation(
                "VOICE-EFFECT-UNAVAILABLE", "voice turn is not awaiting an effect"
            )
        if not text.strip() or len(text) > 60 or "\x00" in text:
            raise LiveVoiceViolation(
                "VOICE-EFFECT-PAYLOAD", "voice effect text is invalid"
            )
        await self._transition(LiveVoiceSessionState.SPEAKING)
        try:
            spoken = await self._speak(turn_id, _single_fragment(text))
            if spoken != text:
                raise LiveVoiceViolation(
                    "VOICE-PLAYBACK-RESULT-UNKNOWN",
                    "voice playback text could not be verified",
                )
            snapshot = await self._journal.recent_turn()
        except LiveVoiceViolation as error:
            completion.set_exception(error)
            raise
        except Exception as error:
            violation = LiveVoiceViolation(
                "VOICE-PLAYBACK-RESULT-UNKNOWN",
                "voice playback result could not be recorded",
            )
            completion.set_exception(violation)
            raise violation from error
        frames = (
            0
            if snapshot is None or snapshot.turn_id != turn_id
            else snapshot.frames_written
        )
        completion.set_result((AttemptOutcome.COMPLETED, spoken, False))
        return frames

    async def complete_silently(self, *, turn_id: UUID) -> None:
        completion = self._pending_effects.get(turn_id)
        if completion is not None and not completion.done():
            completion.set_result((AttemptOutcome.COMPLETED, "", True))

    async def fail_cognition(self, *, turn_id: UUID) -> None:
        completion = self._pending_effects.get(turn_id)
        if completion is not None and not completion.done() and not self._stop.is_set():
            completion.set_exception(
                LiveVoiceViolation(
                    "VOICE-COGNITION-FAILED",
                    "the accepted voice turn could not be completed",
                )
            )

    async def _speak(self, turn_id: UUID, fragments: AsyncIterator[str]) -> str:
        spoken: list[str] = []
        tts_attempt = self._begin_provider_call(
            turn_id=turn_id, binding=self._binding.tts
        )
        tts_frames = 0
        written_frames = 0

        async def registered() -> AsyncIterator[str]:
            fragment_no = 0
            async for fragment in fragments:
                fragment_no += 1
                await self._expression.register_fragment(
                    turn_id=turn_id,
                    fragment_no=fragment_no,
                    text=fragment,
                )
                spoken.append(fragment)
                yield fragment

        async def observed_audio() -> AsyncIterator[bytes]:
            nonlocal tts_frames
            async for frame in self._tts.synthesize(registered()):
                if not frame:
                    continue
                if tts_frames == 0:
                    self._provider_event(event="first_result", call=tts_attempt)
                tts_frames += 1
                yield frame

        async def frame_written() -> None:
            nonlocal written_frames
            if written_frames == 0:
                written_frames += 1
                await self._journal.mark_playback_first_frame(turn_id=turn_id)
            else:
                written_frames += 1

        await self._journal.mark_playback_dispatched(turn_id=turn_id)
        try:
            self._provider_event(event="dispatched", call=tts_attempt)
            with provider_meter_scope(self._meter_scope(tts_attempt, "voice_tts")):
                reported_frames = await self._audio.play(
                    observed_audio(), on_frame_written=frame_written
                )
            if reported_frames != written_frames:
                raise LiveVoiceViolation(
                    "VOICE-PLAYBACK-COUNT", "audio playback count is inconsistent"
                )
            if tts_frames == 0 or written_frames == 0:
                raise LiveVoiceViolation("VOICE-TTS-EMPTY", "TTS returned no audio")
        except asyncio.CancelledError:
            self._provider_event(
                event="settled",
                call=tts_attempt,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-TTS-CANCELLED",
            )
            await self._journal.settle_playback(
                turn_id=turn_id,
                outcome=AttemptOutcome.UNKNOWN,
                frames_written=written_frames,
                error_code="VOICE-PLAYBACK-CANCELLED",
            )
            raise
        except LiveVoiceViolation as error:
            playback_outcome = (
                AttemptOutcome.FAILED
                if written_frames == 0
                else AttemptOutcome.UNKNOWN
                if error.code == "VOICE-PLAYBACK-COUNT"
                else AttemptOutcome.PARTIAL
            )
            self._provider_event(
                event="settled",
                call=tts_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if tts_frames else AttemptOutcome.FAILED
                ),
                error_code=error.code,
            )
            await self._journal.settle_playback(
                turn_id=turn_id,
                outcome=playback_outcome,
                frames_written=written_frames,
                error_code=error.code,
            )
            code = (
                "VOICE-PLAYBACK-NOT-DELIVERED"
                if written_frames == 0
                else "VOICE-PLAYBACK-RESULT-UNKNOWN"
            )
            raise LiveVoiceViolation(code, "voice playback did not complete") from error
        except Exception as error:
            self._provider_event(
                event="settled",
                call=tts_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if tts_frames else AttemptOutcome.UNKNOWN
                ),
                error_code="VOICE-TTS-UNKNOWN",
            )
            await self._journal.settle_playback(
                turn_id=turn_id,
                outcome=(
                    AttemptOutcome.PARTIAL if written_frames else AttemptOutcome.UNKNOWN
                ),
                frames_written=written_frames,
                error_code="VOICE-PLAYBACK-UNKNOWN",
            )
            code = (
                "VOICE-PLAYBACK-NOT-DELIVERED"
                if written_frames == 0
                else "VOICE-PLAYBACK-RESULT-UNKNOWN"
            )
            raise LiveVoiceViolation(code, "audio playback failed") from error
        self._provider_event(
            event="settled", call=tts_attempt, outcome=AttemptOutcome.COMPLETED
        )
        await self._journal.settle_playback(
            turn_id=turn_id,
            outcome=AttemptOutcome.COMPLETED,
            frames_written=written_frames,
        )
        return "".join(spoken)

    async def _transition(
        self,
        state: LiveVoiceSessionState,
        *,
        context_version: str | None = None,
    ) -> None:
        self._machine.transition(state)
        assert self._session_id is not None
        await self._journal.set_session_state(
            session_id=self._session_id,
            state=state,
            context_version=context_version,
        )


async def _single_fragment(text: str) -> AsyncIterator[str]:
    yield text


__all__ = ("LiveVoiceService",)
