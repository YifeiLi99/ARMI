"""Business-neutral contracts for owner-authored startup recovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from .transactions import PostgreSQLTransaction

_OWNER = re.compile(r"^[a-z][a-z0-9-]{0,63}$", re.ASCII)
_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$", re.ASCII)
_REASON = re.compile(r"^REC-[A-Z0-9-]{1,123}$", re.ASCII)


def _uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise ValueError("recovery UUID must be UUIDv7")


def _token(value: object, pattern: re.Pattern[str], message: str) -> None:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class RecoveryOwnerIdentity:
    value: str

    def __post_init__(self) -> None:
        _token(self.value, _OWNER, "recovery owner identity is invalid")


@dataclass(frozen=True, slots=True)
class RecoveryScope:
    environment_id: UUID
    subject_id: UUID
    life_generation_id: UUID
    bundle_activation_id: UUID
    runtime_instance_id: UUID
    fence_token: int

    def __post_init__(self) -> None:
        for value in (
            self.environment_id,
            self.subject_id,
            self.life_generation_id,
            self.bundle_activation_id,
            self.runtime_instance_id,
        ):
            _uuid7(value)
        if type(self.fence_token) is not int or self.fence_token <= 0:
            raise ValueError("recovery fence token is invalid")


@dataclass(frozen=True, slots=True)
class RecoveryWorkSnapshot:
    work_id: UUID
    work_kind: str
    owner_kind: str
    owner_ref: UUID
    status: str
    attempt_count: int
    max_attempts: int
    payload_kind: str | None = None
    payload_ref: UUID | None = None
    payload_digest: str | None = None

    def __post_init__(self) -> None:
        _uuid7(self.work_id)
        _uuid7(self.owner_ref)
        _token(self.work_kind, _TOKEN, "recovery work kind is invalid")
        _token(self.owner_kind, _TOKEN, "recovery work owner is invalid")
        _token(self.status, _TOKEN, "recovery work status is invalid")
        if (
            type(self.attempt_count) is not int
            or type(self.max_attempts) is not int
            or self.attempt_count < 0
            or self.max_attempts < 1
        ):
            raise ValueError("recovery work attempt count is invalid")


class RecoveryFindingDecision(StrEnum):
    REQUEUED = "requeued"
    TERMINAL = "terminal"
    RESUMABLE = "resumable"
    VERIFIED = "verified"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RecoveryFindingContribution:
    kind: str
    decision: RecoveryFindingDecision
    reason_code: str
    reference: UUID | None = None

    def __post_init__(self) -> None:
        _token(self.kind, _TOKEN, "recovery finding kind is invalid")
        if type(self.decision) is not RecoveryFindingDecision:
            raise ValueError("recovery finding decision is invalid")
        _token(self.reason_code, _REASON, "recovery finding reason is invalid")
        if self.reference is not None:
            _uuid7(self.reference)


@dataclass(frozen=True, slots=True)
class RecoveryMetricContribution:
    kind: str
    value: int

    def __post_init__(self) -> None:
        _token(self.kind, _TOKEN, "recovery metric kind is invalid")
        if type(self.value) is not int or self.value < 0:
            raise ValueError("recovery metric value is invalid")


@dataclass(frozen=True, slots=True)
class RecoveryAuditContribution:
    operation: str
    target_kind: str
    target_ref: UUID
    reason_code: str

    def __post_init__(self) -> None:
        _token(self.operation, _TOKEN, "recovery audit operation is invalid")
        _token(self.target_kind, _TOKEN, "recovery audit target is invalid")
        _uuid7(self.target_ref)
        _token(self.reason_code, _REASON, "recovery audit reason is invalid")


class RecoveryWorkCommandKind(StrEnum):
    ENQUEUE = "enqueue"
    FAIL = "fail"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class RecoveryWorkCommand:
    kind: RecoveryWorkCommandKind
    work_id: UUID
    work_kind: str
    owner_kind: str
    owner_ref: UUID
    reason_code: str
    payload_kind: str | None = None
    payload_ref: UUID | None = None
    payload_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not RecoveryWorkCommandKind:
            raise ValueError("recovery work command is invalid")
        _uuid7(self.work_id)
        _uuid7(self.owner_ref)
        _token(self.work_kind, _TOKEN, "recovery command work kind is invalid")
        _token(self.owner_kind, _TOKEN, "recovery command owner is invalid")
        _token(self.reason_code, _REASON, "recovery command reason is invalid")


@dataclass(frozen=True, slots=True)
class RecoveryContribution:
    owner: RecoveryOwnerIdentity
    findings: tuple[RecoveryFindingContribution, ...] = ()
    metrics: tuple[RecoveryMetricContribution, ...] = ()
    work_commands: tuple[RecoveryWorkCommand, ...] = ()
    audits: tuple[RecoveryAuditContribution, ...] = ()
    critical_artifact_ids: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if type(self.owner) is not RecoveryOwnerIdentity:
            raise ValueError("recovery contribution owner is invalid")
        if len({metric.kind for metric in self.metrics}) != len(self.metrics):
            raise ValueError("recovery metric kind is duplicated")
        for artifact_id in self.critical_artifact_ids:
            _uuid7(artifact_id)


@runtime_checkable
class RecoveryParticipant(Protocol):
    @property
    def owner_identity(self) -> RecoveryOwnerIdentity: ...

    @property
    def work_scopes(self) -> tuple[tuple[str, str], ...]: ...

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution: ...


@runtime_checkable
class RecoveryDependentParticipant(RecoveryParticipant, Protocol):
    """Owner participant that consumes earlier owner-authored contributions."""

    async def recover_with_prior(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
        prior: tuple[RecoveryContribution, ...],
    ) -> RecoveryContribution: ...


class EmptyRecoveryParticipant:
    """Explicit participant for an owner with no manifested startup repair."""

    __slots__ = ("_owner",)

    def __init__(self, owner: str) -> None:
        self._owner = RecoveryOwnerIdentity(owner)

    @property
    def owner_identity(self) -> RecoveryOwnerIdentity:
        return self._owner

    @property
    def work_scopes(self) -> tuple[tuple[str, str], ...]:
        return ()

    async def recover(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> RecoveryContribution:
        del transaction, scope, work
        return RecoveryContribution(self._owner)


__all__ = (
    "EmptyRecoveryParticipant",
    "RecoveryAuditContribution",
    "RecoveryContribution",
    "RecoveryDependentParticipant",
    "RecoveryFindingContribution",
    "RecoveryFindingDecision",
    "RecoveryMetricContribution",
    "RecoveryOwnerIdentity",
    "RecoveryParticipant",
    "RecoveryScope",
    "RecoveryWorkCommand",
    "RecoveryWorkCommandKind",
    "RecoveryWorkSnapshot",
)
