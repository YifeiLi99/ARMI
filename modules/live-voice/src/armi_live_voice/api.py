"""Provider-neutral contracts and deterministic real-time voice mechanics."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
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


class VoiceProviderService(StrEnum):
    ASR = "asr"
    LLM = "llm"
    TTS = "tts"


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

    def __post_init__(self) -> None:
        if not self.version or len(self.version) > 128:
            raise LiveVoiceViolation("VOICE-CONTEXT-VERSION", "voice context is invalid")
        if not self.prompt.strip() or len(self.prompt.encode("utf-8")) > 262_144:
            raise LiveVoiceViolation("VOICE-CONTEXT-SIZE", "voice context is invalid")


@dataclass(frozen=True, slots=True)
class VoiceProviderBinding:
    service: VoiceProviderService
    provider: str
    resource_id: str
    model_identity: str | None = None

    def __post_init__(self) -> None:
        if type(self.service) is not VoiceProviderService:
            raise LiveVoiceViolation("VOICE-BINDING", "voice provider binding is invalid")
        for value, maximum in ((self.provider, 64), (self.resource_id, 128)):
            if value != value.strip() or not value or len(value) > maximum:
                raise LiveVoiceViolation(
                    "VOICE-BINDING", "voice provider binding is invalid"
                )
        if self.model_identity is not None and (
            self.model_identity != self.model_identity.strip()
            or not self.model_identity
            or len(self.model_identity) > 256
        ):
            raise LiveVoiceViolation("VOICE-BINDING", "voice provider binding is invalid")


@dataclass(frozen=True, slots=True)
class LiveVoiceBinding:
    input_host_api: str
    input_device_name: str
    output_host_api: str
    output_device_name: str
    asr: VoiceProviderBinding
    llm: VoiceProviderBinding
    tts: VoiceProviderBinding

    def __post_init__(self) -> None:
        for value, maximum in (
            (self.input_host_api, 128),
            (self.input_device_name, 512),
            (self.output_host_api, 128),
            (self.output_device_name, 512),
        ):
            if value != value.strip() or not value or len(value) > maximum:
                raise LiveVoiceViolation("VOICE-BINDING", "voice device binding is invalid")
        if (
            self.asr.service is not VoiceProviderService.ASR
            or self.llm.service is not VoiceProviderService.LLM
            or self.tts.service is not VoiceProviderService.TTS
        ):
            raise LiveVoiceViolation("VOICE-BINDING", "voice provider binding is invalid")


@dataclass(frozen=True, slots=True)
class AcceptedVoiceInput:
    interaction_id: UUID
    evidence_id: UUID
    request_digest: str
    content_digest: str
    newly_accepted: bool

    def __post_init__(self) -> None:
        if any(
            type(value) is not UUID or value.version != 7
            for value in (self.interaction_id, self.evidence_id)
        ):
            raise LiveVoiceViolation("VOICE-INPUT-ACCEPTANCE", "voice input is invalid")
        for value in (self.request_digest, self.content_digest):
            if (
                type(value) is not str
                or len(value) != 71
                or not value.startswith("sha256:")
                or not all(character in "0123456789abcdef" for character in value[7:])
            ):
                raise LiveVoiceViolation(
                    "VOICE-INPUT-ACCEPTANCE", "voice input is invalid"
                )
        if type(self.newly_accepted) is not bool:
            raise LiveVoiceViolation("VOICE-INPUT-ACCEPTANCE", "voice input is invalid")


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


@runtime_checkable
class VoiceJournalPort(Protocol):
    async def open_session(self, *, session_id: UUID) -> None: ...
    async def set_session_state(
        self,
        *,
        session_id: UUID,
        state: LiveVoiceSessionState,
        context_version: str | None = None,
    ) -> None: ...
    async def close_session(
        self, *, session_id: UUID, error_code: str | None = None
    ) -> None: ...
    async def begin_turn(
        self,
        *,
        session_id: UUID,
        turn_id: UUID,
        turn_no: int,
        context_version: str,
    ) -> None: ...
    async def record_transcript(
        self,
        *,
        turn_id: UUID,
        transcript: str | None,
        interaction_id: UUID | None,
    ) -> None: ...
    async def record_decision(
        self, *, turn_id: UUID, decision: FastReplyDecision
    ) -> None: ...
    async def settle_turn(
        self,
        *,
        turn_id: UUID,
        outcome: AttemptOutcome,
        spoken_text: str = "",
        error_code: str | None = None,
        silent: bool = False,
    ) -> None: ...
    async def begin_provider_attempt(
        self, *, turn_id: UUID, binding: VoiceProviderBinding
    ) -> UUID: ...
    async def mark_provider_first_result(self, *, attempt_id: UUID) -> None: ...
    async def settle_provider_attempt(
        self,
        *,
        attempt_id: UUID,
        outcome: AttemptOutcome,
        error_code: str | None = None,
    ) -> None: ...
    async def begin_playback(self, *, turn_id: UUID) -> UUID: ...
    async def mark_playback_first_frame(self, *, attempt_id: UUID) -> None: ...
    async def settle_playback(
        self,
        *,
        attempt_id: UUID,
        outcome: AttemptOutcome,
        frames_written: int,
        error_code: str | None = None,
    ) -> None: ...


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
    async def play(
        self,
        frames: AsyncIterator[bytes],
        *,
        on_frame_written: Callable[[], Awaitable[None]] | None = None,
    ) -> int: ...
    async def close(self) -> None: ...


@runtime_checkable
class StreamingAsrPort(Protocol):
    def recognize(
        self, frames: AsyncIterator[bytes]
    ) -> AsyncIterator[RecognitionEvent]: ...


@runtime_checkable
class StreamingFastModelPort(Protocol):
    async def prepare(self) -> None: ...
    def generate(
        self, context: VoiceContext, transcript: str
    ) -> AsyncIterator[str]: ...


@runtime_checkable
class StreamingTtsPort(Protocol):
    async def prepare(self) -> None: ...
    async def close(self) -> None: ...
    def synthesize(self, fragments: AsyncIterator[str]) -> AsyncIterator[bytes]: ...


@runtime_checkable
class LiveVoiceRuntimePort(Protocol):
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def status(self) -> LiveVoiceSessionState: ...
    @property
    def last_error(self) -> str | None: ...


__all__ = (
    "AcceptedVoiceInput",
    "AttemptOutcome",
    "AudioDevice",
    "AudioDevicePort",
    "AudioFormat",
    "FastReplyDecision",
    "FastReplyKind",
    "HalfDuplexStateMachine",
    "LiveVoiceBinding",
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
    "VoiceJournalPort",
    "VoiceProviderBinding",
    "VoiceProviderService",
    "VoiceSuccessorPort",
    "parse_fast_reply",
)
