"""Process-local lifecycle state for the S008 Runtime steel frame."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock

from armi_kernel.contracts import Instant

from armi_runtime.interfaces.creator_contract import Readiness, RuntimeState

from .runtime_errors import RuntimeViolation

RUNTIME_BLOCKING_REASONS = ("CREATOR_SESSION_NOT_IMPLEMENTED",)
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$", re.ASCII)

_ALLOWED_TRANSITIONS = {
    RuntimeState.STOPPED: frozenset({RuntimeState.STARTING}),
    RuntimeState.STARTING: frozenset(
        {
            RuntimeState.UNBORN,
            RuntimeState.RECOVERING,
            RuntimeState.READY,
            RuntimeState.DEGRADED,
            RuntimeState.BLOCKED,
        }
    ),
    RuntimeState.RECOVERING: frozenset(
        {
            RuntimeState.READY,
            RuntimeState.DEGRADED,
            RuntimeState.BLOCKED,
            RuntimeState.DRAINING,
        }
    ),
    RuntimeState.UNBORN: frozenset({RuntimeState.DRAINING}),
    RuntimeState.READY: frozenset({RuntimeState.DEGRADED, RuntimeState.DRAINING}),
    RuntimeState.DEGRADED: frozenset({RuntimeState.DRAINING}),
    RuntimeState.BLOCKED: frozenset({RuntimeState.DRAINING}),
    RuntimeState.DRAINING: frozenset({RuntimeState.STOPPED}),
}


@dataclass(frozen=True, slots=True)
class RuntimeSnapshot:
    environment_id: str
    runtime_state: RuntimeState
    readiness: Readiness
    reason_codes: tuple[str, ...]
    observed_at: str


class LifecycleController:
    """Own the only mutable lifecycle state inside one Runtime process."""

    __slots__ = ("_clock", "_environment_id", "_lock", "_reasons", "_state")

    def __init__(
        self,
        *,
        environment_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._environment_id = environment_id
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = Lock()
        self._state = RuntimeState.STOPPED
        self._reasons: tuple[str, ...] = ()

    def start(self) -> RuntimeSnapshot:
        return self._transition(RuntimeState.STARTING, ())

    def complete_startup(
        self,
        blockers: tuple[str, ...] = RUNTIME_BLOCKING_REASONS,
    ) -> RuntimeSnapshot:
        with self._lock:
            degradations = self._reasons
        if blockers:
            return self._transition(
                RuntimeState.BLOCKED,
                (*blockers, *degradations),
            )
        if degradations:
            return self._transition(RuntimeState.DEGRADED, degradations)
        return self._transition(RuntimeState.READY, ())

    def block(
        self,
        reasons: tuple[str, ...] = RUNTIME_BLOCKING_REASONS,
    ) -> RuntimeSnapshot:
        return self.complete_startup(reasons)

    def mark_unborn(self) -> RuntimeSnapshot:
        return self._transition(RuntimeState.UNBORN, ())

    def begin_recovery(self) -> RuntimeSnapshot:
        return self._transition(RuntimeState.RECOVERING, ())

    def add_degradation(self, reason: str) -> RuntimeSnapshot:
        if type(reason) is not str or _REASON.fullmatch(reason) is None:
            raise RuntimeViolation("LIFE-REASON", "lifecycle reason is invalid")
        with self._lock:
            self._reasons = tuple(sorted({*self._reasons, reason}))
            if self._state is RuntimeState.READY:
                self._state = RuntimeState.DEGRADED
            return self._snapshot_unlocked()

    def drain(self) -> RuntimeSnapshot:
        with self._lock:
            if self._state in {RuntimeState.DRAINING, RuntimeState.STOPPED}:
                return self._snapshot_unlocked()
        return self._transition(RuntimeState.DRAINING, self._reasons)

    def stop(self) -> RuntimeSnapshot:
        with self._lock:
            if self._state is RuntimeState.STOPPED:
                return self._snapshot_unlocked()
        return self._transition(RuntimeState.STOPPED, ())

    def snapshot(self) -> RuntimeSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def _transition(
        self,
        target: RuntimeState,
        reasons: tuple[str, ...],
    ) -> RuntimeSnapshot:
        with self._lock:
            allowed = _ALLOWED_TRANSITIONS.get(self._state, frozenset())
            if target not in allowed:
                raise RuntimeViolation(
                    "LIFE-TRANSITION",
                    "the requested lifecycle transition is not allowed",
                )
            self._state = target
            self._reasons = tuple(sorted(set(reasons)))
            return self._snapshot_unlocked()

    def _snapshot_unlocked(self) -> RuntimeSnapshot:
        observed = Instant(self._clock().astimezone(UTC)).to_wire()
        readiness = (
            Readiness.READY
            if self._state in {RuntimeState.READY, RuntimeState.DEGRADED}
            else Readiness.NOT_READY
        )
        return RuntimeSnapshot(
            environment_id=self._environment_id,
            runtime_state=self._state,
            readiness=readiness,
            reason_codes=self._reasons,
            observed_at=observed,
        )


__all__ = (
    "RUNTIME_BLOCKING_REASONS",
    "LifecycleController",
    "RuntimeSnapshot",
)
