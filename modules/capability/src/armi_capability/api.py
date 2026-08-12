"""Public contracts for capabilities, requests, and grants."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import TraceId
from armi_runtime_foundation import (
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)

_CODE = re.compile(r"^(?:CON|CAPABILITY|POLICY|CONFLICT|SCOPE)-[A-Z0-9-]+$", re.ASCII)


class CapabilityKind(StrEnum):
    CREATOR_SCENE_REPLY = "creator.scene.reply"
    CODEX_DELEGATED_WORK = "codex.delegated-work"


class CapabilityOperation(StrEnum):
    SEND = "send"
    EXECUTE = "execute"


class CapabilityAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class CapabilityRequestStatus(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    LIMITED = "limited"
    DENIED = "denied"
    REVOKED = "revoked"
    EXPIRED = "expired"


class CreatorGrantDecision(StrEnum):
    GRANT = "grant"
    LIMIT = "limit"
    DENY = "deny"
    REVOKE = "revoke"


class GrantStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class CapabilityAuthorizationOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class CapabilityViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("capability violation code is invalid")
        self.code = code
        super().__init__("capability policy failed")

    def __str__(self) -> str:
        return f"{self.code}: capability policy failed"


@dataclass(frozen=True, slots=True)
class CapabilityId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-CAPABILITY-ID")


@dataclass(frozen=True, slots=True)
class CapabilityRequestId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-CAPABILITY-REQUEST-ID")


@dataclass(frozen=True, slots=True)
class CapabilityDecisionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-CAPABILITY-DECISION-ID")


@dataclass(frozen=True, slots=True)
class PermissionGrantId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-CAPABILITY-GRANT-ID")


@dataclass(frozen=True, slots=True)
class CapabilityCommitContext:
    validation_id: UUID
    episode_id: UUID
    subject_id: UUID
    scene_id: UUID | None
    creator_party_id: UUID | None
    trace_id: TraceId

    def __post_init__(self) -> None:
        for value in (self.validation_id, self.episode_id, self.subject_id):
            _uuid7(value, "CON-CAPABILITY-COMMIT-CONTEXT")
        for value in (self.scene_id, self.creator_party_id):
            if value is not None:
                _uuid7(value, "CON-CAPABILITY-COMMIT-CONTEXT")
        if type(self.trace_id) is not TraceId:
            raise CapabilityViolation("CON-CAPABILITY-COMMIT-CONTEXT")


@dataclass(frozen=True, slots=True)
class CapabilityConsumptionRequest:
    capability_kind: str
    operation_class: str
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    purpose: str
    effect_kind: str
    payload_bytes: int

    def __post_init__(self) -> None:
        for value in (self.subject_id, self.scene_id, self.creator_party_id):
            _uuid7(value, "CON-CAPABILITY-CONSUMPTION")
        if (
            type(self.capability_kind) is not str
            or not self.capability_kind
            or self.operation_class not in {"send", "execute"}
            or type(self.purpose) is not str
            or not self.purpose
            or self.effect_kind not in {"creator_response", "codex_delegation"}
            or type(self.payload_bytes) is not int
            or self.payload_bytes < 0
        ):
            raise CapabilityViolation("CON-CAPABILITY-CONSUMPTION")


@dataclass(frozen=True, slots=True)
class CapabilityConsumptionResult:
    outcome: CapabilityAuthorizationOutcome
    reason_code: str
    grant_id: UUID | None = None
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        if (
            type(self.outcome) is not CapabilityAuthorizationOutcome
            or type(self.reason_code) is not str
            or _CODE.fullmatch(self.reason_code) is None
            or (self.grant_id is None) != (self.valid_until is None)
        ):
            raise CapabilityViolation("CON-CAPABILITY-CONSUMPTION")
        if self.grant_id is not None:
            _uuid7(self.grant_id, "CON-CAPABILITY-CONSUMPTION")
        if (self.outcome is CapabilityAuthorizationOutcome.ALLOWED) != (
            self.grant_id is not None
        ):
            raise CapabilityViolation("CON-CAPABILITY-CONSUMPTION")


@dataclass(frozen=True, slots=True)
class CreatorSceneReplyScope:
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    valid_for_seconds: int
    max_uses: int
    max_payload_bytes: int
    audience_scope: str = "creator"
    data_scope: str = "creator_visible_response"
    purpose: str = "respond_to_creator"

    def __post_init__(self) -> None:
        for value in (self.subject_id, self.scene_id, self.creator_party_id):
            _uuid7(value, "CON-CAPABILITY-REPLY-SCOPE")
        if (
            type(self.valid_for_seconds) is not int
            or not 60 <= self.valid_for_seconds <= 604800
            or type(self.max_uses) is not int
            or not 1 <= self.max_uses <= 16
            or type(self.max_payload_bytes) is not int
            or not 1 <= self.max_payload_bytes <= 65536
            or self.audience_scope != "creator"
            or self.data_scope != "creator_visible_response"
            or self.purpose != "respond_to_creator"
        ):
            raise CapabilityViolation("CON-CAPABILITY-REPLY-SCOPE")


@dataclass(frozen=True, slots=True)
class CodexDelegatedWorkScope:
    valid_for_seconds: int
    workspace_scope: str = "isolated_ephemeral"
    artifact_scope: str = "explicit_only"
    network_access: bool = False
    max_uses: int = 1

    def __post_init__(self) -> None:
        if (
            type(self.valid_for_seconds) is not int
            or not 60 <= self.valid_for_seconds <= 3600
            or self.workspace_scope != "isolated_ephemeral"
            or self.artifact_scope != "explicit_only"
            or self.network_access is not False
            or self.max_uses != 1
        ):
            raise CapabilityViolation("CON-CAPABILITY-CODEX-SCOPE")


type CapabilityScope = CreatorSceneReplyScope | CodexDelegatedWorkScope


@dataclass(frozen=True, slots=True)
class CapabilityRequestDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    capability: CapabilityKind
    operation: CapabilityOperation
    scope: CapabilityScope

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"proposal:[1-9][0-9]{0,2}", self.proposal_ref)
            or not re.fullmatch(r"group:[1-9][0-9]{0,2}", self.atomic_group_ref)
            or not self.basis_ordinals
            or len(self.basis_ordinals) > 8
            or len(set(self.basis_ordinals)) != len(self.basis_ordinals)
            or any(
                type(value) is not int or not 1 <= value <= 999
                for value in self.basis_ordinals
            )
            or type(self.capability) is not CapabilityKind
            or type(self.operation) is not CapabilityOperation
            or type(self.scope) not in {CreatorSceneReplyScope, CodexDelegatedWorkScope}
        ):
            raise CapabilityViolation("CON-CAPABILITY-REQUEST")
        if (
            self.capability is CapabilityKind.CREATOR_SCENE_REPLY
            and (
                self.operation is not CapabilityOperation.SEND
                or not isinstance(self.scope, CreatorSceneReplyScope)
            )
        ) or (
            self.capability is CapabilityKind.CODEX_DELEGATED_WORK
            and (
                self.operation is not CapabilityOperation.EXECUTE
                or not isinstance(self.scope, CodexDelegatedWorkScope)
            )
        ):
            raise CapabilityViolation("CON-CAPABILITY-REQUEST")


@dataclass(frozen=True, slots=True)
class CreatorGrantCommand:
    decision_id: CapabilityDecisionId
    request_id: CapabilityRequestId
    expected_version: int
    decision: CreatorGrantDecision
    valid_for_seconds: int | None = None
    max_uses: int | None = None
    max_payload_bytes: int | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.decision_id) is not CapabilityDecisionId
            or type(self.request_id) is not CapabilityRequestId
            or type(self.expected_version) is not int
            or self.expected_version <= 0
            or type(self.decision) is not CreatorGrantDecision
            or (
                self.reason_code is not None
                and _CODE.fullmatch(self.reason_code) is None
            )
        ):
            raise CapabilityViolation("CON-CAPABILITY-DECISION")
        if self.decision is CreatorGrantDecision.LIMIT:
            if all(
                value is None
                for value in (
                    self.valid_for_seconds,
                    self.max_uses,
                    self.max_payload_bytes,
                )
            ):
                raise CapabilityViolation("CON-CAPABILITY-DECISION")
        elif any(
            value is not None
            for value in (self.valid_for_seconds, self.max_uses, self.max_payload_bytes)
        ):
            raise CapabilityViolation("CON-CAPABILITY-DECISION")


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    grant_id: PermissionGrantId
    request_id: CapabilityRequestId
    capability: CapabilityKind
    operation: CapabilityOperation
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    scope: CapabilityScope
    valid_from: datetime
    valid_until: datetime
    consumed_uses: int
    status: GrantStatus

    def __post_init__(self) -> None:
        if (
            type(self.grant_id) is not PermissionGrantId
            or type(self.request_id) is not CapabilityRequestId
            or type(self.capability) is not CapabilityKind
            or type(self.operation) is not CapabilityOperation
            or any(
                type(value) is not UUID or value.version != 7
                for value in (
                    self.subject_id,
                    self.scene_id,
                    self.creator_party_id,
                )
            )
            or type(self.valid_from) is not datetime
            or type(self.valid_until) is not datetime
            or self.valid_from.tzinfo is None
            or self.valid_until.tzinfo is None
            or not self.valid_from < self.valid_until
            or type(self.consumed_uses) is not int
            or not 0 <= self.consumed_uses <= self.scope.max_uses
            or type(self.status) is not GrantStatus
        ):
            raise CapabilityViolation("CON-CAPABILITY-GRANT")
        if (
            self.capability is CapabilityKind.CREATOR_SCENE_REPLY
            and (
                self.operation is not CapabilityOperation.SEND
                or type(self.scope) is not CreatorSceneReplyScope
                or self.scope.subject_id != self.subject_id
                or self.scope.scene_id != self.scene_id
                or self.scope.creator_party_id != self.creator_party_id
                or self.valid_until - self.valid_from > timedelta(days=7)
            )
        ) or (
            self.capability is CapabilityKind.CODEX_DELEGATED_WORK
            and (
                self.operation is not CapabilityOperation.EXECUTE
                or type(self.scope) is not CodexDelegatedWorkScope
                or self.valid_until - self.valid_from > timedelta(hours=1)
            )
        ):
            raise CapabilityViolation("CON-CAPABILITY-GRANT")


@dataclass(frozen=True, slots=True)
class CreatorGrantResult:
    request_id: CapabilityRequestId
    request_version: int
    status: CapabilityRequestStatus
    grant: PermissionGrant | None = None

    def __post_init__(self) -> None:
        has_grant = self.status in {
            CapabilityRequestStatus.GRANTED,
            CapabilityRequestStatus.LIMITED,
        }
        if (
            type(self.request_id) is not CapabilityRequestId
            or type(self.request_version) is not int
            or self.request_version <= 1
            or type(self.status) is not CapabilityRequestStatus
            or has_grant != (self.grant is not None)
        ):
            raise CapabilityViolation("CON-CAPABILITY-RESULT")


class GrantMatcher:
    @staticmethod
    def permits(
        grant: PermissionGrant,
        *,
        now: datetime,
        subject_id: UUID,
        scene_id: UUID,
        creator_party_id: UUID,
        purpose: str,
        payload_bytes: int,
    ) -> bool:
        scope = grant.scope
        return (
            grant.capability is CapabilityKind.CREATOR_SCENE_REPLY
            and grant.operation is CapabilityOperation.SEND
            and isinstance(scope, CreatorSceneReplyScope)
            and grant.status is GrantStatus.ACTIVE
            and grant.valid_from <= now < grant.valid_until
            and grant.consumed_uses < scope.max_uses
            and grant.subject_id == subject_id
            and grant.scene_id == scene_id
            and grant.creator_party_id == creator_party_id
            and scope.subject_id == subject_id
            and scope.scene_id == scene_id
            and scope.creator_party_id == creator_party_id
            and scope.purpose == purpose
            and type(payload_bytes) is int
            and 0 <= payload_bytes <= scope.max_payload_bytes
        )

    @staticmethod
    def permits_codex(
        grant: PermissionGrant,
        *,
        now: datetime,
        subject_id: UUID,
        scene_id: UUID,
        creator_party_id: UUID,
        purpose: str,
    ) -> bool:
        scope = grant.scope
        return (
            grant.capability is CapabilityKind.CODEX_DELEGATED_WORK
            and grant.operation is CapabilityOperation.EXECUTE
            and isinstance(scope, CodexDelegatedWorkScope)
            and grant.status is GrantStatus.ACTIVE
            and grant.valid_from <= now < grant.valid_until
            and grant.consumed_uses == 0
            and grant.subject_id == subject_id
            and grant.scene_id == scene_id
            and grant.creator_party_id == creator_party_id
            and purpose == "delegate_codex_work"
            and scope.workspace_scope == "isolated_ephemeral"
            and scope.artifact_scope == "explicit_only"
            and scope.network_access is False
        )


@runtime_checkable
class CreatorGrantPolicyPort(Protocol):
    async def decide(self, command: CreatorGrantCommand) -> CreatorGrantResult: ...


@runtime_checkable
class CapabilityPolicyPort(CreatorGrantPolicyPort, Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def stop(self) -> None: ...
    async def run_expiry_reconciler(self) -> None: ...

    async def list_requests(
        self,
        *,
        creator_party_id: UUID,
        limit: int,
        cursor: str | None,
    ) -> dict[str, object]: ...

    async def expire_once(self, *, limit: int = 100) -> int: ...


@runtime_checkable
class CapabilityCommitPort(Protocol):
    async def commit_requests(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: CapabilityCommitContext,
        commit_id: UUID,
        requests: tuple[CapabilityRequestDraft, ...],
    ) -> None: ...


@runtime_checkable
class CapabilityReadPort(Protocol):
    async def request_ids_for_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        commit_id: UUID,
    ) -> tuple[UUID, ...]: ...


@runtime_checkable
class CapabilityGrantConsumptionPort(Protocol):
    async def authorize_and_consume(
        self,
        transaction: PostgreSQLTransaction,
        request: CapabilityConsumptionRequest,
    ) -> CapabilityConsumptionResult: ...


@runtime_checkable
class CapabilityEffectCancellationPort(Protocol):
    async def cancel_registered(
        self,
        transaction: PostgreSQLTransaction,
        *,
        grant_id: UUID,
        reason_code: str,
    ) -> tuple[tuple[UUID, UUID, UUID], ...]: ...


def _uuid7(value: UUID, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise CapabilityViolation(code)


__all__ = (
    "CapabilityAuthorizationOutcome",
    "CapabilityAvailability",
    "CapabilityCommitContext",
    "CapabilityCommitPort",
    "CapabilityConsumptionRequest",
    "CapabilityConsumptionResult",
    "CapabilityDecisionId",
    "CapabilityEffectCancellationPort",
    "CapabilityGrantConsumptionPort",
    "CapabilityId",
    "CapabilityKind",
    "CapabilityOperation",
    "CapabilityPolicyPort",
    "CapabilityReadPort",
    "CapabilityRequestDraft",
    "CapabilityRequestId",
    "CapabilityRequestStatus",
    "CapabilityScope",
    "CapabilityViolation",
    "CodexDelegatedWorkScope",
    "CreatorGrantCommand",
    "CreatorGrantDecision",
    "CreatorGrantPolicyPort",
    "CreatorGrantResult",
    "CreatorSceneReplyScope",
    "GrantMatcher",
    "GrantStatus",
    "PermissionGrant",
    "PermissionGrantId",
)
