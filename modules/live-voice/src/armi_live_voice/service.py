"""The half-duplex real-time voice application service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import suppress
from uuid import UUID, uuid7

from .api import (
    AudioDevicePort,
    FastReplyKind,
    HalfDuplexStateMachine,
    LiveVoiceSessionState,
    LiveVoiceViolation,
    StreamingAsrPort,
    StreamingFastModelPort,
    StreamingTtsPort,
    VoiceContext,
    VoiceContextPort,
    VoiceExpressionPort,
    VoiceInputAcceptancePort,
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
    ) -> None:
        self._audio = audio
        self._asr = asr
        self._model = model
        self._tts = tts
        self._context = context
        self._inputs = inputs
        self._expression = expression
        self._successors = successors
        self._machine = HalfDuplexStateMachine()
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._ready = asyncio.Event()
        self._session_id: UUID | None = None
        self._last_error: str | None = None

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
        self._task = None
        if self._machine.state is not LiveVoiceSessionState.IDLE:
            self._machine.transition(LiveVoiceSessionState.IDLE)

    async def _run(self) -> None:
        try:
            context, _, _ = await asyncio.gather(
                self._context.compile(),
                self._model.prepare(),
                self._tts.prepare(),
            )
            self._machine.transition(LiveVoiceSessionState.LISTENING)
            self._ready.set()
            while not self._stop.is_set():
                await self._one_turn(context)
        except asyncio.CancelledError:
            raise
        except LiveVoiceViolation as error:
            self._last_error = error.code
            self._machine.transition(LiveVoiceSessionState.UNAVAILABLE)
            self._ready.set()
        except Exception:
            self._last_error = "VOICE-RUNTIME-FAILED"
            self._machine.transition(LiveVoiceSessionState.UNAVAILABLE)
            self._ready.set()

    async def _one_turn(self, context: VoiceContext) -> None:
        self._machine.transition(LiveVoiceSessionState.RECOGNIZING)
        transcript = ""
        async for event in self._asr.recognize(self._audio.capture()):
            transcript = event.text
            if event.utterance_ended:
                break
        if not transcript.strip():
            self._machine.transition(LiveVoiceSessionState.LISTENING)
            return
        self._machine.transition(LiveVoiceSessionState.THINKING)
        turn_id = uuid7()
        assert self._session_id is not None
        accepted = await self._inputs.accept_once(
            transcript=transcript,
            session_id=self._session_id,
            turn_id=turn_id,
        )
        stream = self._model.generate(context, transcript)
        try:
            kind, initial, remaining = await _read_route(stream)
        except LiveVoiceViolation:
            self._machine.transition(LiveVoiceSessionState.WAITING_SLOW)
            await self._successors.run_slow(accepted)
            self._machine.transition(LiveVoiceSessionState.LISTENING)
            return
        if kind is FastReplyKind.SILENT:
            trailing = initial + await _collect_text(remaining)
            parse_fast_reply("SILENT\n" + trailing)
            await self._successors.enqueue_appraisal(accepted)
            self._machine.transition(LiveVoiceSessionState.LISTENING)
            return
        if kind is FastReplyKind.WAIT:
            text = (initial + await _collect_text(remaining)).strip()
            decision = parse_fast_reply("WAIT\n" + text)
            self._machine.transition(LiveVoiceSessionState.SPEAKING)
            spoken = await self._speak(turn_id, _single_fragment(decision.text))
            await self._expression.seal(turn_id=turn_id, spoken_text=spoken)
            self._machine.transition(LiveVoiceSessionState.WAITING_SLOW)
            await self._successors.run_slow(accepted)
            self._machine.transition(LiveVoiceSessionState.LISTENING)
            return
        self._machine.transition(LiveVoiceSessionState.SPEAKING)
        fragments = _stream_speak_fragments(initial, remaining)
        spoken = await self._speak(turn_id, fragments)
        parse_fast_reply("SPEAK\n" + spoken)
        await self._expression.seal(turn_id=turn_id, spoken_text=spoken)
        await self._successors.enqueue_appraisal(accepted)
        self._machine.transition(LiveVoiceSessionState.LISTENING)

    async def _speak(self, turn_id: UUID, fragments: AsyncIterator[str]) -> str:
        spoken: list[str] = []

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

        await self._audio.play(self._tts.synthesize(registered()))
        return "".join(spoken)


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
