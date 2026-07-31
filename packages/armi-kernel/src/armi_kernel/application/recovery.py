"""Technology-neutral startup recovery contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest

_REASON = re.compile(r"^REC-[A-Z0-9-]{1,123}$", re.ASCII)
_KIND = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


class RecoveryViolation(RuntimeError):
    """Expose a stable recovery code without database or filesystem detail."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _REASON.fullmatch(code) is None:
            raise ValueError("recovery violation code is invalid")
        self.code = code
        super().__init__("runtime recovery failed")

    def __str__(self) -> str:
        return f"{self.code}: runtime recovery failed"


def _require_uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise RecoveryViolation("REC-DECLARATION")


@dataclass(frozen=True, slots=True)
class RecoveryRunId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value)

    def __str__(self) -> str:
        return str(self.value)


class RecoveryStatus(StrEnum):
    RUNNING = "running"
    SAFE = "safe"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"


class RecoveryDecision(StrEnum):
    REQUEUED = "requeued"
    TERMINAL = "terminal"
    RESUMABLE = "resumable"
    VERIFIED = "verified"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RecoveryFinding:
    kind: str
    decision: RecoveryDecision
    reason_code: str
    reference: UUID | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or _KIND.fullmatch(self.kind) is None:
            raise RecoveryViolation("REC-DECLARATION")
        if type(self.decision) is not RecoveryDecision:
            raise RecoveryViolation("REC-DECLARATION")
        if (
            type(self.reason_code) is not str
            or _REASON.fullmatch(self.reason_code) is None
        ):
            raise RecoveryViolation("REC-DECLARATION")
        if self.reference is not None:
            _require_uuid7(self.reference)


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    recovery_run_id: RecoveryRunId
    status: RecoveryStatus
    requeued_work_count: int
    terminal_work_count: int
    requeued_outbox_count: int
    dead_outbox_count: int
    resumable_work_count: int
    resumable_outbox_count: int
    resumable_opportunity_count: int
    resumable_cognitive_episode_count: int
    resumable_model_attempt_count: int
    resumable_candidate_validation_count: int
    critical_artifact_count: int
    blocker_count: int
    summary_digest: Digest | None
    findings: tuple[RecoveryFinding, ...] = ()

    def __post_init__(self) -> None:
        if type(self.recovery_run_id) is not RecoveryRunId:
            raise RecoveryViolation("REC-DECLARATION")
        if type(self.status) is not RecoveryStatus:
            raise RecoveryViolation("REC-DECLARATION")
        for value in (
            self.requeued_work_count,
            self.terminal_work_count,
            self.requeued_outbox_count,
            self.dead_outbox_count,
            self.resumable_work_count,
            self.resumable_outbox_count,
            self.resumable_opportunity_count,
            self.resumable_cognitive_episode_count,
            self.resumable_model_attempt_count,
            self.resumable_candidate_validation_count,
            self.critical_artifact_count,
            self.blocker_count,
        ):
            if type(value) is not int or value < 0:
                raise RecoveryViolation("REC-DECLARATION")
        if self.status is RecoveryStatus.RUNNING:
            if self.summary_digest is not None:
                raise RecoveryViolation("REC-STATE")
        elif type(self.summary_digest) is not Digest:
            raise RecoveryViolation("REC-STATE")
        if self.status is RecoveryStatus.SAFE and self.blocker_count != 0:
            raise RecoveryViolation("REC-STATE")
        if self.status is RecoveryStatus.BLOCKED and self.blocker_count == 0:
            raise RecoveryViolation("REC-STATE")
        if type(self.findings) is not tuple or any(
            type(value) is not RecoveryFinding for value in self.findings
        ):
            raise RecoveryViolation("REC-DECLARATION")


@runtime_checkable
class RecoveryPort(Protocol):
    async def recover(self) -> RecoverySummary:
        """Rebuild only currently manifested durable responsibilities."""
        ...


__all__ = (
    "RecoveryDecision",
    "RecoveryFinding",
    "RecoveryPort",
    "RecoveryRunId",
    "RecoveryStatus",
    "RecoverySummary",
    "RecoveryViolation",
)
