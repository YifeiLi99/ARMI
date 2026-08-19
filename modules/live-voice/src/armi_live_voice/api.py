"""Provider-neutral contracts and deterministic real-time voice mechanics."""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable
from uuid import UUID


class LiveVoiceViolation(ValueError):
    """A stable failure that can be exposed without provider secrets."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LiveVoiceSessionState(StrEnum):
    IDLE = "idle"
    STARTING = "starting"
    LISTENING = "listening"
    RECOGNIZING = "recognizing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    WAITING_SLOW = "waiting_slow"
    UNAVAILABLE = "unavailable"


class FastReplyKind(StrEnum):
    SPEAK = "SPEAK"
    WAIT = "WAIT"
    SILENT = "SILENT"


class AttemptOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AudioFormat:
    sample_rate_hz: int = 16_000
    channels: int = 1
    sample_width_bytes: int = 2
    frame_duration_ms: int = 20

    def __post_init__(self) -> None:
        if self.sample_rate_hz <= 0 or self.channels != 1:
            raise LiveVoiceViolation("VOICE-AUDIO-FORMAT", "unsupported audio format")
        if self.sample_width_bytes != 2 or self.frame_duration_ms <= 0:
            raise LiveVoiceViolation("VOICE-AUDIO-FORMAT", "unsupported audio format")

    @property
    def frame_bytes(self) -> int:
        return (
            self.sample_rate_hz
            * self.channels
            * self.sample_width_bytes
            * self.frame_duration_ms
            // 1000
        )


@dataclass(frozen=True, slots=True)
class AudioDevice:
    host_api: str
    name: str
    input_channels: int
    output_channels: int
    default_sample_rate: float


@dataclass(frozen=True, slots=True)
class FastReplyDecision:
    kind: FastReplyKind
    text: str = ""


@dataclass(frozen=True, slots=True)
class RecognitionEvent:
    text: str
    is_final: bool
    utterance_ended: bool = False


@dataclass(frozen=True, slots=True)
class VoiceContext:
    version: str
    prompt: str


@dataclass(frozen=True, slots=True)
class AcceptedVoiceInput:
    interaction_id: UUID
    evidence_id: UUID
    opportunity_id: UUID


@runtime_checkable
class VoiceInputAcceptancePort(Protocol):
    async def accept_once(
        self, *, transcript: str, session_id: UUID, turn_id: UUID
    ) -> AcceptedVoiceInput: ...


@runtime_checkable
class VoiceContextPort(Protocol):
    async def compile(self) -> VoiceContext: ...


@runtime_checkable
class VoiceExpressionPort(Protocol):
    async def register_fragment(
        self,
        *,
        turn_id: UUID,
        fragment_no: int,
        text: str,
    ) -> None: ...

    async def seal(self, *, turn_id: UUID, spoken_text: str) -> None: ...


@runtime_checkable
class VoiceSuccessorPort(Protocol):
    async def enqueue_appraisal(self, accepted: AcceptedVoiceInput) -> None: ...
    async def run_slow(self, accepted: AcceptedVoiceInput) -> None: ...


class BoundedAudioQueue:
    """A byte-bounded volatile queue; overflow is explicit, never silent."""

    def __init__(self, max_bytes: int) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._size = 0
        self._items: deque[bytes] = deque()

    @property
    def size_bytes(self) -> int:
        return self._size

    def put(self, frame: bytes) -> None:
        if not frame:
            return
        if self._size + len(frame) > self._max_bytes:
            raise LiveVoiceViolation("VOICE-AUDIO-BACKPRESSURE", "audio queue is full")
        self._items.append(frame)
        self._size += len(frame)

    def get(self) -> bytes | None:
        if not self._items:
            return None
        item = self._items.popleft()
        self._size -= len(item)
        return item


def parse_fast_reply(payload: str) -> FastReplyDecision:
    """Parse the exact first-line protocol without inventing fallback speech."""

    normalized = payload.replace("\r\n", "\n")
    first, separator, body = normalized.partition("\n")
    try:
        kind = FastReplyKind(first)
    except ValueError as error:
        raise LiveVoiceViolation(
            "VOICE-FAST-PROTOCOL", "unknown fast reply kind"
        ) from error
    if kind is FastReplyKind.SILENT:
        if separator and body.strip():
            raise LiveVoiceViolation("VOICE-FAST-PROTOCOL", "SILENT must not have text")
        return FastReplyDecision(kind)
    if not separator:
        raise LiveVoiceViolation("VOICE-FAST-PROTOCOL", "reply text is missing")
    text = body.strip()
    limit = 160 if kind is FastReplyKind.SPEAK else 24
    if not text or len(text) > limit or "\n" in text:
        raise LiveVoiceViolation("VOICE-FAST-PROTOCOL", "reply text is invalid")
    return FastReplyDecision(kind, text)


_BREAKS = frozenset("。\uff01\uff1f!?\uff1b;\uff0c,、\uff1a:\n")


def speech_chunks(
    text: str, *, first_target: int = 12, maximum: int = 48
) -> tuple[str, ...]:
    """Split completed text into short pronounceable chunks."""

    if first_target <= 0 or maximum < first_target:
        raise ValueError("invalid chunk limits")
    chunks: list[str] = []
    start = 0
    target = first_target
    for index, character in enumerate(text, start=1):
        length = index - start
        if (character in _BREAKS and length >= target) or length >= maximum:
            chunk = text[start:index].strip()
            if chunk:
                chunks.append(chunk)
            start = index
            target = maximum
    tail = text[start:].strip()
    if tail:
        chunks.append(tail)
    return tuple(chunks)


class HalfDuplexStateMachine:
    """The only legal first-version microphone/playback lifecycle."""

    _TRANSITIONS: ClassVar[dict[LiveVoiceSessionState, set[LiveVoiceSessionState]]] = {
        LiveVoiceSessionState.IDLE: {LiveVoiceSessionState.STARTING},
        LiveVoiceSessionState.UNAVAILABLE: {
            LiveVoiceSessionState.STARTING,
            LiveVoiceSessionState.IDLE,
        },
        LiveVoiceSessionState.STARTING: {
            LiveVoiceSessionState.LISTENING,
            LiveVoiceSessionState.UNAVAILABLE,
            LiveVoiceSessionState.IDLE,
        },
        LiveVoiceSessionState.LISTENING: {
            LiveVoiceSessionState.RECOGNIZING,
            LiveVoiceSessionState.IDLE,
            LiveVoiceSessionState.UNAVAILABLE,
        },
        LiveVoiceSessionState.RECOGNIZING: {
            LiveVoiceSessionState.THINKING,
            LiveVoiceSessionState.LISTENING,
            LiveVoiceSessionState.IDLE,
            LiveVoiceSessionState.UNAVAILABLE,
        },
        LiveVoiceSessionState.THINKING: {
            LiveVoiceSessionState.SPEAKING,
            LiveVoiceSessionState.WAITING_SLOW,
            LiveVoiceSessionState.LISTENING,
            LiveVoiceSessionState.IDLE,
            LiveVoiceSessionState.UNAVAILABLE,
        },
        LiveVoiceSessionState.SPEAKING: {
            LiveVoiceSessionState.LISTENING,
            LiveVoiceSessionState.IDLE,
            LiveVoiceSessionState.UNAVAILABLE,
        },
        LiveVoiceSessionState.WAITING_SLOW: {
            LiveVoiceSessionState.SPEAKING,
            LiveVoiceSessionState.LISTENING,
            LiveVoiceSessionState.IDLE,
            LiveVoiceSessionState.UNAVAILABLE,
        },
    }

    def __init__(self) -> None:
        self._state = LiveVoiceSessionState.IDLE

    @property
    def state(self) -> LiveVoiceSessionState:
        return self._state

    @property
    def microphone_open(self) -> bool:
        return self._state in {
            LiveVoiceSessionState.LISTENING,
            LiveVoiceSessionState.RECOGNIZING,
        }

    def transition(self, target: LiveVoiceSessionState) -> None:
        if target == self._state:
            if target in {LiveVoiceSessionState.IDLE, LiveVoiceSessionState.LISTENING}:
                return
            raise LiveVoiceViolation("VOICE-STATE-CONFLICT", "duplicate transition")
        if target not in self._TRANSITIONS[self._state]:
            raise LiveVoiceViolation(
                "VOICE-STATE-CONFLICT",
                f"illegal transition {self._state.value}->{target.value}",
            )
        self._state = target


@runtime_checkable
class AudioDevicePort(Protocol):
    def devices(self) -> tuple[AudioDevice, ...]: ...
    def capture(self) -> AsyncIterator[bytes]: ...
    async def play(self, frames: AsyncIterator[bytes]) -> None: ...
    async def close(self) -> None: ...


@runtime_checkable
class StreamingAsrPort(Protocol):
    def recognize(
        self, frames: AsyncIterator[bytes]
    ) -> AsyncIterator[RecognitionEvent]: ...


@runtime_checkable
class StreamingFastModelPort(Protocol):
    def generate(
        self, context: VoiceContext, transcript: str
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class StreamingTtsPort(Protocol):
    def synthesize(self, fragments: AsyncIterator[str]) -> AsyncIterator[bytes]: ...


@runtime_checkable
class LiveVoiceRuntimePort(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def status(self) -> LiveVoiceSessionState: ...


__all__ = (
    "AcceptedVoiceInput",
    "AttemptOutcome",
    "AudioDevice",
    "AudioDevicePort",
    "AudioFormat",
    "BoundedAudioQueue",
    "FastReplyDecision",
    "FastReplyKind",
    "HalfDuplexStateMachine",
    "LiveVoiceRuntimePort",
    "LiveVoiceSessionState",
    "LiveVoiceViolation",
    "RecognitionEvent",
    "StreamingAsrPort",
    "StreamingFastModelPort",
    "StreamingTtsPort",
    "VoiceContext",
    "VoiceContextPort",
    "VoiceExpressionPort",
    "VoiceInputAcceptancePort",
    "VoiceSuccessorPort",
    "parse_fast_reply",
    "speech_chunks",
)
