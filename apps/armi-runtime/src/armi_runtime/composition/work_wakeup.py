"""Process-local wakeups for PostgreSQL-backed durable responsibilities."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

OPPORTUNITY_AVAILABLE = "opportunity.available"
CONTEXT_PREPARE = "cognition.context.prepare"
MODEL_INVOKE = "cognition.model.invoke"
CANDIDATE_VALIDATE = "cognition.candidate.validate"
SUBJECT_COMMIT = "cognition.subject.commit"
RESPONSE_ADMIT = "cognition.response.admit"
EFFECT_REGISTER = "effect.register"


@dataclass(frozen=True, slots=True)
class _Pulse:
    version: int
    event: asyncio.Event


class WorkWakeupBus:
    """Wake interested workers without becoming a responsibility source.

    Every pulse is deliberately payload-free. Consumers must re-read and claim
    PostgreSQL work; the timeout remains the recovery path when a pulse is lost.
    Versioned events avoid the clear/check/wait race of a shared ``Event``.
    """

    __slots__ = ("_pulses",)

    def __init__(self) -> None:
        self._pulses: dict[str, _Pulse] = {}

    def version(self, channel: str) -> int:
        return self._pulse(channel).version

    def notify(self, channel: str) -> None:
        current = self._pulse(channel)
        current.event.set()
        self._pulses[channel] = _Pulse(current.version + 1, asyncio.Event())

    async def wait(
        self,
        channel: str,
        after_version: int,
        *,
        stop: asyncio.Event,
        timeout_seconds: float,
    ) -> int:
        current = self._pulse(channel)
        if current.version != after_version or stop.is_set():
            return current.version
        pulse_wait = asyncio.create_task(current.event.wait())
        stop_wait = asyncio.create_task(stop.wait())
        try:
            await asyncio.wait(
                (pulse_wait, stop_wait),
                timeout=timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in (pulse_wait, stop_wait):
                if not task.done():
                    task.cancel()
            await asyncio.gather(pulse_wait, stop_wait, return_exceptions=True)
        return self.version(channel)

    def _pulse(self, channel: str) -> _Pulse:
        if not channel or not channel.isascii():
            raise ValueError("wakeup channel must be non-empty ASCII")
        current = self._pulses.get(channel)
        if current is None:
            current = _Pulse(0, asyncio.Event())
            self._pulses[channel] = current
        return current


__all__ = (
    "CANDIDATE_VALIDATE",
    "CONTEXT_PREPARE",
    "EFFECT_REGISTER",
    "MODEL_INVOKE",
    "OPPORTUNITY_AVAILABLE",
    "RESPONSE_ADMIT",
    "SUBJECT_COMMIT",
    "WorkWakeupBus",
)
