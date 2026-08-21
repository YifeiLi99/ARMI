"""The half-duplex real-time voice application service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import suppress
from uuid import UUID, uuid7

from .api import (
    AttemptOutcome,
    AudioDevicePort,
    FastReplyDecision,
    FastReplyKind,
    HalfDuplexStateMachine,
    LiveVoiceBinding,
    LiveVoiceSessionState,
    LiveVoiceViolation,
    StreamingAsrPort,
    StreamingFastModelPort,
    StreamingTtsPort,
    VoiceContext,
    VoiceContextPort,
    VoiceExpressionPort,
    VoiceInputAcceptancePort,
    VoiceJournalPort,
    VoiceSuccessorPort,
    parse_fast_reply,
)


class LiveVoiceService:
    """Own one explicit local session; it never survives Runtime restart."""

    def __init__(
        self,
        *,
        audio: AudioDevicePort,
        asr: StreamingAsrPort,
        model: StreamingFastModelPort,
        tts: StreamingTtsPort,
        context: VoiceContextPort,
        inputs: VoiceInputAcceptancePort,
        expression: VoiceExpressionPort,
        successors: VoiceSuccessorPort,
        journal: VoiceJournalPort,
        binding: LiveVoiceBinding,
    ) -> None:
        self._audio = audio
        self._asr = asr
        self._model = model
        self._tts = tts
        self._context = context
        self._inputs = inputs
        self._expression = expression
        self._successors = successors
        self._journal = journal
        self._binding = binding
        self._machine = HalfDuplexStateMachine()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._session_id: UUID | None = None
        self._last_error: str | None = None
        self._turn_no = 0

    def status(self) -> LiveVoiceSessionState:
        return self._machine.state

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
            context, _, _ = await asyncio.gather(
                self._context.compile(),
                self._model.prepare(),
                self._tts.prepare(),
            )
            await self._transition(
                LiveVoiceSessionState.LISTENING, context_version=context.version
            )
            self._ready.set()
            while not self._stop.is_set():
                await self._one_turn(context)
                context = await self._context.compile()
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

    async def _one_turn(self, context: VoiceContext) -> None:
        assert self._session_id is not None
        self._turn_no += 1
        turn_id = uuid7()
        await self._journal.begin_turn(
            session_id=self._session_id,
            turn_id=turn_id,
            turn_no=self._turn_no,
            context_version=context.version,
        )
        try:
            outcome, spoken, silent = await self._execute_turn(turn_id, context)
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
            spoken_text=spoken,
            silent=silent,
        )
        await self._transition(LiveVoiceSessionState.LISTENING)

    async def _execute_turn(
        self, turn_id: UUID, context: VoiceContext
    ) -> tuple[AttemptOutcome, str, bool]:
        await self._transition(LiveVoiceSessionState.RECOGNIZING)
        asr_attempt = await self._journal.begin_provider_attempt(
            turn_id=turn_id, binding=self._binding.asr
        )
        transcript = ""
        received_asr = False
        try:
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
                turn_id=turn_id, transcript=None, interaction_id=None
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
        )
        llm_attempt = await self._journal.begin_provider_attempt(
            turn_id=turn_id, binding=self._binding.llm
        )
        stream = self._observed_model_stream(
            llm_attempt, self._model.generate(context, transcript)
        )
        try:
            kind, initial, remaining = await _read_route(stream)
        except LiveVoiceViolation:
            await stream.aclose()
            await self._transition(LiveVoiceSessionState.WAITING_SLOW)
            await self._successors.run_slow(accepted)
            return AttemptOutcome.COMPLETED, "", False
        if kind is FastReplyKind.SILENT:
            trailing = initial + await _collect_text(remaining)
            decision = parse_fast_reply("SILENT\n" + trailing)
            await self._journal.record_decision(turn_id=turn_id, decision=decision)
            await self._successors.enqueue_appraisal(accepted)
            return AttemptOutcome.COMPLETED, "", True
        if kind is FastReplyKind.WAIT:
            text = (initial + await _collect_text(remaining)).strip()
            decision = parse_fast_reply("WAIT\n" + text)
            await self._journal.record_decision(turn_id=turn_id, decision=decision)
            await self._transition(LiveVoiceSessionState.SPEAKING)
            spoken = await self._speak(turn_id, _single_fragment(decision.text))
            await self._expression.seal(turn_id=turn_id, spoken_text=spoken)
            await self._transition(LiveVoiceSessionState.WAITING_SLOW)
            await self._successors.run_slow(accepted)
            return AttemptOutcome.COMPLETED, spoken, False
        await self._journal.record_decision(
            turn_id=turn_id,
            decision=FastReplyDecision(FastReplyKind.SPEAK),
        )
        await self._transition(LiveVoiceSessionState.SPEAKING)
        fragments = _stream_speak_fragments(initial, remaining)
        spoken = await self._speak(turn_id, fragments)
        parse_fast_reply("SPEAK\n" + spoken)
        await self._expression.seal(turn_id=turn_id, spoken_text=spoken)
        await self._successors.enqueue_appraisal(accepted)
        return AttemptOutcome.COMPLETED, spoken, False

    async def _observed_model_stream(
        self, attempt_id: UUID, stream: AsyncIterator[str]
    ) -> AsyncGenerator[str]:
        received = False
        try:
            async for value in stream:
                if not received:
                    await self._journal.mark_provider_first_result(
                        attempt_id=attempt_id
                    )
                    received = True
                yield value
        except asyncio.CancelledError:
            await self._journal.settle_provider_attempt(
                attempt_id=attempt_id,
                outcome=AttemptOutcome.UNKNOWN,
                error_code="VOICE-LLM-CANCELLED",
            )
            raise
        except LiveVoiceViolation as error:
            await self._journal.settle_provider_attempt(
                attempt_id=attempt_id,
                outcome=AttemptOutcome.PARTIAL if received else AttemptOutcome.FAILED,
                error_code=error.code,
            )
            raise
        except GeneratorExit:
            await self._journal.settle_provider_attempt(
                attempt_id=attempt_id,
                outcome=AttemptOutcome.PARTIAL if received else AttemptOutcome.FAILED,
                error_code="VOICE-LLM-ABANDONED",
            )
            raise
        except Exception as error:
            await self._journal.settle_provider_attempt(
                attempt_id=attempt_id,
                outcome=AttemptOutcome.PARTIAL if received else AttemptOutcome.UNKNOWN,
                error_code="VOICE-LLM-UNKNOWN",
            )
            raise LiveVoiceViolation(
                "VOICE-LLM-UNKNOWN", "fast voice model failed"
            ) from error
        await self._journal.settle_provider_attempt(
            attempt_id=attempt_id, outcome=AttemptOutcome.COMPLETED
        )

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
            await self._journal.settle_provider_attempt(
                attempt_id=tts_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if tts_frames else AttemptOutcome.FAILED
                ),
                error_code=error.code,
            )
            await self._journal.settle_playback(
                attempt_id=playback_attempt,
                outcome=(
                    AttemptOutcome.PARTIAL if written_frames else AttemptOutcome.FAILED
                ),
                frames_written=written_frames,
                error_code=error.code,
            )
            raise
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
            raise LiveVoiceViolation(
                "VOICE-PLAYBACK-UNKNOWN", "audio playback failed"
            ) from error
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


async def _read_route(
    stream: AsyncIterator[str],
) -> tuple[FastReplyKind, str, AsyncIterator[str]]:
    prefix = ""
    async for delta in stream:
        prefix += delta
        if len(prefix) > 16 and "\n" not in prefix:
            raise LiveVoiceViolation("VOICE-FAST-PROTOCOL", "first line is invalid")
        if "\n" in prefix:
            first, initial = prefix.split("\n", 1)
            try:
                return FastReplyKind(first), initial, stream
            except ValueError as error:
                raise LiveVoiceViolation(
                    "VOICE-FAST-PROTOCOL", "unknown fast reply kind"
                ) from error
    raise LiveVoiceViolation("VOICE-FAST-PROTOCOL", "first line is incomplete")


async def _collect_text(stream: AsyncIterator[str]) -> str:
    return "".join([part async for part in stream])


async def _single_fragment(text: str) -> AsyncIterator[str]:
    yield text


async def _stream_speak_fragments(
    initial: str, stream: AsyncIterator[str]
) -> AsyncIterator[str]:
    queue: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

    async def produce() -> None:
        try:
            if initial:
                await queue.put(initial)
            async for delta in stream:
                await queue.put(delta)
        except BaseException as error:
            await queue.put(error)
        finally:
            await queue.put(None)

    producer = asyncio.create_task(produce())
    buffer = ""
    total = 0
    text_ended = False
    first_fragment = True
    breaks = frozenset("。\uff01\uff1f!?\uff1b;\uff0c,、\uff1a:")
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=0.08)
            except TimeoutError:
                item = ""
            if isinstance(item, BaseException):
                raise item
            if item is None:
                tail = buffer.strip()
                if tail:
                    yield tail
                return
            if text_ended:
                if item.strip():
                    raise LiveVoiceViolation(
                        "VOICE-FAST-PROTOCOL", "SPEAK text is invalid"
                    )
                continue
            buffer += item
            total += len(item)
            if "\n" in buffer:
                body, trailing = buffer.split("\n", 1)
                if trailing.strip():
                    raise LiveVoiceViolation(
                        "VOICE-FAST-PROTOCOL", "SPEAK text is invalid"
                    )
                buffer = body
                text_ended = True
            if total > 160:
                raise LiveVoiceViolation("VOICE-FAST-PROTOCOL", "SPEAK text is invalid")
            if buffer and (
                first_fragment
                or len(buffer) >= 48
                or (len(buffer) >= 12 and buffer[-1] in breaks)
                or item == ""
            ):
                fragment = buffer.strip()
                buffer = ""
                if fragment:
                    first_fragment = False
                    yield fragment
    finally:
        producer.cancel()
        with suppress(asyncio.CancelledError):
            await producer


__all__ = ("LiveVoiceService",)
