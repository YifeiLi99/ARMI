"""Business-neutral contracts for owner-authored startup recovery."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
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
    reconciliation_required: bool = False
    generation: int = 1
    predecessor_work_id: UUID | None = None
    deadline_at: datetime | None = None
    current_attempt_id: UUID | None = None
    lease_owner: UUID | None = None
    lease_expires_at: datetime | None = None
    lease_token: int = 0
    result_kind: str | None = None
    result_ref: UUID | None = None
    last_error_code: str | None = None
    subject_id: UUID | None = None
    idempotency_key: str | None = None

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
        if type(self.reconciliation_required) is not bool:
            raise ValueError("recovery work reconciliation state is invalid")
        if type(self.generation) is not int or self.generation < 1:
            raise ValueError("recovery work generation is invalid")
        if (self.generation == 1) != (self.predecessor_work_id is None):
            raise ValueError("recovery work predecessor is invalid")
        if self.predecessor_work_id is not None:
            _uuid7(self.predecessor_work_id)
        for value in (
            self.current_attempt_id,
            self.lease_owner,
            self.result_ref,
            self.subject_id,
        ):
            if value is not None:
                _uuid7(value)
        if type(self.lease_token) is not int or self.lease_token < 0:
            raise ValueError("recovery work lease token is invalid")


class OwnerReconciliationContext:
    """Fence work settlement to the participant's declared owner scope."""

    __slots__ = ("_by_id", "_owner", "_transaction")

    def __init__(
        self,
        transaction: PostgreSQLTransaction,
        owner: RecoveryOwnerIdentity,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None:
        self._transaction = transaction
        self._owner = owner
        self._by_id = {item.work_id: item for item in work}
        if len(self._by_id) != len(work):
            raise ValueError("reconciliation work is duplicated")

    async def complete(
        self, work_id: UUID, *, result_kind: str, result_ref: UUID
    ) -> None:
        _token(result_kind, _TOKEN, "reconciliation result kind is invalid")
        _uuid7(result_ref)
        await self._settle(
            work_id,
            status="completed",
            reason_code=None,
            result_kind=result_kind,
            result_ref=result_ref,
        )

    async def fail(self, work_id: UUID, *, reason_code: str) -> None:
        _token(reason_code, _REASON, "reconciliation reason is invalid")
        await self._settle(
            work_id,
            status="failed",
            reason_code=reason_code,
            result_kind=None,
            result_ref=None,
        )

    async def fail_with_successor(
        self,
        work_id: UUID,
        *,
        successor_work_id: UUID,
        reason_code: str,
        not_before: datetime,
        deadline_at: datetime,
        max_attempts: int,
    ) -> None:
        _uuid7(successor_work_id)
        _token(reason_code, _REASON, "reconciliation reason is invalid")
        if deadline_at <= not_before or type(max_attempts) is not int:
            raise ValueError("reconciliation successor declaration is invalid")
        snapshot = self._by_id.get(work_id)
        if snapshot is None or not snapshot.reconciliation_required:
            raise ValueError("reconciliation work is outside owner custody")
        row = await (
            await self._transaction.execute(
                """WITH predecessor AS (
                     UPDATE armi.durable_work
                     SET status='failed',reconciliation_required=false,
                         current_attempt_id=NULL,lease_owner=NULL,
                         lease_expires_at=NULL,last_error_code=%s,
                         updated_at=clock_timestamp()
                     WHERE work_id=%s AND owner_kind=%s AND work_kind=%s
                       AND status IN ('ready','leased')
                       AND reconciliation_required=true
                     RETURNING *
                   )
                   INSERT INTO armi.durable_work (
                     work_id,work_kind,generation,predecessor_work_id,
                     owner_kind,owner_ref,subject_id,idempotency_key,
                     payload_kind,payload_ref,payload_digest,priority,
                     not_before,deadline_at,status,reconciliation_required,
                     max_attempts,attempt_count,lease_token,trace_id)
                   SELECT %s,work_kind,generation+1,work_id,owner_kind,owner_ref,
                          subject_id,idempotency_key,payload_kind,payload_ref,
                          payload_digest,priority,%s,%s,'ready',false,%s,0,0,trace_id
                   FROM predecessor RETURNING work_id""",
                (
                    reason_code,
                    snapshot.work_id,
                    snapshot.owner_kind,
                    snapshot.work_kind,
                    successor_work_id,
                    not_before,
                    deadline_at,
                    max_attempts,
                ),
            )
        ).fetchone()
        if row is None:
            raise ValueError("reconciliation successor custody is stale")

    async def cancel(self, work_id: UUID, *, reason_code: str) -> None:
        _token(reason_code, _REASON, "reconciliation reason is invalid")
        await self._settle(
            work_id,
            status="cancelled",
            reason_code=reason_code,
            result_kind=None,
            result_ref=None,
        )

    async def _settle(
        self,
        work_id: UUID,
        *,
        status: str,
        reason_code: str | None,
        result_kind: str | None,
        result_ref: UUID | None,
    ) -> None:
        snapshot = self._by_id.get(work_id)
        if snapshot is None or (
            not snapshot.reconciliation_required and status != "cancelled"
        ):
            raise ValueError("reconciliation work is outside owner custody")
        result = await self._transaction.execute(
            """UPDATE armi.durable_work
               SET status=%s,reconciliation_required=false,
                   current_attempt_id=NULL,lease_owner=NULL,
                   lease_expires_at=NULL,result_kind=%s,result_ref=%s,
                   last_error_code=%s,updated_at=clock_timestamp()
               WHERE work_id=%s AND owner_kind=%s AND work_kind=%s
                 AND status IN ('ready','leased')
                 AND (reconciliation_required=true OR %s='cancelled')""",
            (
                status,
                result_kind,
                result_ref,
                reason_code,
                snapshot.work_id,
                snapshot.owner_kind,
                snapshot.work_kind,
                status,
            ),
        )
        if result.rowcount != 1:
            raise ValueError("reconciliation work custody is stale")


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


@dataclass(frozen=True, slots=True)
class RecoveryContribution:
    owner: RecoveryOwnerIdentity
    findings: tuple[RecoveryFindingContribution, ...] = ()
    metrics: tuple[RecoveryMetricContribution, ...] = ()
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
class InterruptedWorkEndParticipant(Protocol):
    """Existing owner lifecycle hook for ending ephemeral conversation work."""

    async def end_interrupted_work(
        self,
        transaction: PostgreSQLTransaction,
        scope: RecoveryScope,
        work: tuple[RecoveryWorkSnapshot, ...],
    ) -> None: ...


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
    "InterruptedWorkEndParticipant",
    "OwnerReconciliationContext",
    "RecoveryAuditContribution",
    "RecoveryContribution",
    "RecoveryDependentParticipant",
    "RecoveryFindingContribution",
    "RecoveryFindingDecision",
    "RecoveryMetricContribution",
    "RecoveryOwnerIdentity",
    "RecoveryParticipant",
    "RecoveryScope",
    "RecoveryWorkSnapshot",
)
