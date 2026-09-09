"""The half-duplex real-time voice application service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from uuid import UUID, uuid7

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
    VoiceTurnSnapshot,
)


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
    ) -> None:
        self._audio = audio
        self._asr = asr
        self._model = model
        self._tts = tts
        self._inputs = inputs
        self._expression = expression
        self._journal = journal
        self._binding = binding
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
                self._model.prepare(),
                self._tts.prepare(),
            )
            await self._transition(
                LiveVoiceSessionState.LISTENING,
                context_version="armi.creator-voice-act-candidate.v3",
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
            context_version="armi.creator-voice-act-candidate.v3",
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

    async def _execute_turn(self, turn_id: UUID) -> tuple[AttemptOutcome, str, bool]:
        await self._transition(LiveVoiceSessionState.RECOGNIZING)
        asr_attempt = await self._journal.begin_provider_attempt(
            turn_id=turn_id, binding=self._binding.asr
        )
        transcript = ""
        received_asr = False
        try:
            await self._journal.mark_provider_dispatched(attempt_id=asr_attempt)
            async for event in self._asr.recognize(self._audio.capture()):
                if not received_asr:
                    await self._journal.mark_provider_first_result(
                        attempt_id=asr_attempt
                    )
                    received_asr = True
                transcript = event.text
                if event.utterance_ended:
                    break
        except asyncio.CancelledError:
            await self._journal.settle_provider_attempt(
                attempt_id=asr_attempt,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-ASR-CANCELLED",
            )
            raise
        except LiveVoiceViolation as error:
            await self._journal.settle_provider_attempt(
                attempt_id=asr_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if received_asr else AttemptOutcome.FAILED
                ),
                error_code=error.code,
            )
            raise
        except Exception as error:
            await self._journal.settle_provider_attempt(
                attempt_id=asr_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if received_asr else AttemptOutcome.UNKNOWN
                ),
                error_code="VOICE-ASR-UNKNOWN",
            )
            raise LiveVoiceViolation(
                "VOICE-ASR-UNKNOWN", "speech recognition failed"
            ) from error
        await self._journal.settle_provider_attempt(
            attempt_id=asr_attempt, outcome=AttemptOutcome.COMPLETED
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
            await self._expression.seal(turn_id=turn_id)
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

    async def _speak(self, turn_id: UUID, fragments: AsyncIterator[str]) -> str:
        spoken: list[str] = []
        tts_attempt = await self._journal.begin_provider_attempt(
            turn_id=turn_id, binding=self._binding.tts
        )
        playback_attempt = await self._journal.begin_playback(turn_id=turn_id)
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
                    await self._journal.mark_provider_first_result(
                        attempt_id=tts_attempt
                    )
                tts_frames += 1
                yield frame

        async def frame_written() -> None:
            nonlocal written_frames
            if written_frames == 0:
                written_frames += 1
                await self._journal.mark_playback_first_frame(
                    attempt_id=playback_attempt
                )
            else:
                written_frames += 1

        try:
            await self._journal.mark_provider_dispatched(attempt_id=tts_attempt)
            await self._journal.mark_playback_dispatched(attempt_id=playback_attempt)
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
            await self._journal.settle_provider_attempt(
                attempt_id=tts_attempt,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-TTS-CANCELLED",
            )
            await self._journal.settle_playback(
                attempt_id=playback_attempt,
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
            await self._journal.settle_provider_attempt(
                attempt_id=tts_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if tts_frames else AttemptOutcome.FAILED
                ),
                error_code=error.code,
            )
            await self._journal.settle_playback(
                attempt_id=playback_attempt,
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
            await self._journal.settle_provider_attempt(
                attempt_id=tts_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if tts_frames else AttemptOutcome.UNKNOWN
                ),
                error_code="VOICE-TTS-UNKNOWN",
            )
            await self._journal.settle_playback(
                attempt_id=playback_attempt,
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
        await self._journal.settle_provider_attempt(
            attempt_id=tts_attempt, outcome=AttemptOutcome.COMPLETED
        )
        await self._journal.settle_playback(
            attempt_id=playback_attempt,
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
