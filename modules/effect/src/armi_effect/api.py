"""Technology-neutral T-05/T-06 effect ledger and execution contracts."""

from __future__ import annotations

import re
from asyncio import Event
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, cast, runtime_checkable
from uuid import UUID

from armi_expression.api import ResponseAdmissionPort
from armi_kernel.application import ArtifactPort, WorkRecord
from armi_kernel.contracts import Digest, Instant, TraceId
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)


@dataclass(frozen=True, slots=True)
class EffectAdminSnapshot:
    effect_id: UUID
    status: str
    attempt_id: UUID | None
    payload_digest: str
    action_intent_id: UUID
    outbox_id: UUID
    delivery_id: UUID | None
    receipt_digest: str | None


@runtime_checkable
class EffectAdminPort(Protocol):
    def snapshot(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        effect_id: UUID,
        for_update: bool = False,
    ) -> EffectAdminSnapshot | None: ...
    def reconcile(
        self,
        transaction: PostgreSQLAdminTransaction,
        *,
        snapshot: EffectAdminSnapshot,
        observation_id: UUID,
        observation_digest: str,
        completed: bool,
    ) -> bool: ...
    def current_state(
        self, transaction: PostgreSQLAdminTransaction, *, effect_id: UUID
    ) -> tuple[str, UUID | None, str | None] | None: ...
    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]: ...
    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int: ...


class EffectStatus(StrEnum):
    REGISTERED = "registered"
    DISPATCHING = "dispatching"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


class EffectVerificationStatus(StrEnum):
    NOT_STARTED = "not_started"
    PENDING = "pending"
    VERIFIED = "verified"
    INCONCLUSIVE = "inconclusive"


class EffectObservationKind(StrEnum):
    RECEIPT = "receipt"
    QUERY = "query"
    REJECTION = "rejection"
    AMBIGUOUS = "ambiguous"
    RUNNER_VERIFIED = "runner_verified"
    RUNNER_FAILED = "runner_failed"
    RUNNER_UNKNOWN = "runner_unknown"
    RUNNER_CANCELLED = "runner_cancelled"


class EffectObservationReliability(StrEnum):
    RELIABLE = "reliable"
    INCONCLUSIVE = "inconclusive"


class EffectArtifactKind(StrEnum):
    PATCH = "patch"
    FINAL_RESULT = "final_result"
    VALIDATION_REPORT = "validation_report"


@dataclass(frozen=True, slots=True)
class EffectArtifactContent:
    kind: EffectArtifactKind
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        if self.media_type not in {"application/json", "text/plain"}:
            raise EffectViolation("CON-EFFECT-ARTIFACT")
        if not self.content or len(self.content) > 20 * 1024 * 1024:
            raise EffectViolation("CON-EFFECT-ARTIFACT")


@dataclass(frozen=True, slots=True)
class EffectDispatchBoundaryResult:
    allowed: bool
    grant_id: UUID | None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise EffectViolation("CON-EFFECT-DISPATCH-BOUNDARY")
        if self.grant_id is not None:
            _uuid7(self.grant_id)
        if self.reason_code is not None and (
            type(self.reason_code) is not str or not self.reason_code
        ):
            raise EffectViolation("CON-EFFECT-DISPATCH-BOUNDARY")


@dataclass(frozen=True, slots=True)
class PolicyDecisionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value)


@dataclass(frozen=True, slots=True)
class EffectId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value)


@dataclass(frozen=True, slots=True)
class EffectAttemptId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value)


@dataclass(frozen=True, slots=True)
class EffectObservationId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value)


@dataclass(frozen=True, slots=True)
class EffectDeliveryId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value)


@dataclass(frozen=True, slots=True)
class FrozenEffectRequest:
    effect_id: EffectId
    attempt_id: EffectAttemptId
    subject_id: UUID
    scene_id: UUID
    destination_party_id: UUID
    destination_kind: Literal[
        "creator_inbox", "other_human_inbox", "external_group", "external_private"
    ]
    external_channel: str | None
    external_account_key: str | None
    external_conversation_key: str | None
    payload_digest: Digest
    payload_bytes: int
    trace_id: TraceId

    def __post_init__(self) -> None:
        if type(self.subject_id) is not UUID or self.subject_id.version != 7:
            raise EffectViolation("CON-EFFECT-SUBJECT")
        if type(self.scene_id) is not UUID or self.scene_id.version != 7:
            raise EffectViolation("CON-EFFECT-SCENE")
        if (
            type(self.destination_party_id) is not UUID
            or self.destination_party_id.version != 7
        ):
            raise EffectViolation("CON-EFFECT-DESTINATION")
        if self.destination_kind not in {
            "creator_inbox",
            "other_human_inbox",
            "external_group",
            "external_private",
        }:
            raise EffectViolation("CON-EFFECT-DESTINATION")
        route = (
            self.external_channel,
            self.external_account_key,
            self.external_conversation_key,
        )
        if self.destination_kind in {"external_group", "external_private"}:
            if any(
                type(value) is not str
                or re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", value) is None
                for value in route
            ):
                raise EffectViolation("CON-EFFECT-DESTINATION")
            external_channel = cast(str, self.external_channel)
            if re.fullmatch(r"^[a-z][a-z0-9._-]{0,63}$", external_channel) is None:
                raise EffectViolation("CON-EFFECT-DESTINATION")
        elif any(value is not None for value in route):
            raise EffectViolation("CON-EFFECT-DESTINATION")
        if not 1 <= self.payload_bytes <= 65536:
            raise EffectViolation("CON-EFFECT-PAYLOAD")


@dataclass(frozen=True, slots=True)
class EffectAdapterReceipt:
    delivery_id: EffectDeliveryId
    receipt_digest: Digest
    received_at: Instant
    duplicate: bool = False
    external_receiver_ref: str | None = None

    def __post_init__(self) -> None:
        if type(self.delivery_id) is not EffectDeliveryId:
            raise EffectViolation("CON-EFFECT-RECEIPT")
        if (
            type(self.receipt_digest) is not Digest
            or type(self.received_at) is not Instant
        ):
            raise EffectViolation("CON-EFFECT-RECEIPT")
        if type(self.duplicate) is not bool:
            raise EffectViolation("CON-EFFECT-RECEIPT")
        if self.external_receiver_ref is not None and (
            type(self.external_receiver_ref) is not str
            or re.fullmatch(
                r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
                self.external_receiver_ref,
            )
            is None
        ):
            raise EffectViolation("CON-EFFECT-RECEIPT")


@dataclass(frozen=True, slots=True)
class EffectObservation:
    observation_id: EffectObservationId
    attempt_id: EffectAttemptId
    kind: EffectObservationKind
    reliability: EffectObservationReliability
    digest: Digest
    observed_at: Instant
    receiver_ref: UUID | None = None

    def __post_init__(self) -> None:
        if (self.kind is EffectObservationKind.RECEIPT) != (
            self.receiver_ref is not None
        ):
            raise EffectViolation("CON-EFFECT-OBSERVATION")
        if self.receiver_ref is not None:
            _uuid7(self.receiver_ref)


@dataclass(frozen=True, slots=True)
class EffectRegistrationResult:
    effect_id: EffectId
    policy_decision_id: PolicyDecisionId
    status: EffectStatus
    verification_status: EffectVerificationStatus
    registration_digest: Digest
    registered_at: Instant


@dataclass(frozen=True, slots=True)
class EffectView:
    effect_id: EffectId
    action_intent_ref: UUID
    action_intent_revision_ref: UUID
    policy_decision_ref: UUID | None
    effect_kind: Literal["creator_response", "codex_delegation"]
    status: EffectStatus
    verification_status: EffectVerificationStatus
    registered_at: Instant
    capability_kind: Literal["creator.scene.reply", "codex.delegated-work"]
    cancelled_at: Instant | None = None
    attempt_count: int = 0
    last_observation_kind: EffectObservationKind | None = None
    last_observation_reliability: EffectObservationReliability | None = None
    verification_action: (
        Literal["verify_creator_inbox", "verify_codex_result"] | None
    ) = None
    settled_at: Instant | None = None
    response_text: str | None = None

    def __post_init__(self) -> None:
        _uuid7(self.action_intent_ref)
        _uuid7(self.action_intent_revision_ref)
        if self.policy_decision_ref is not None:
            _uuid7(self.policy_decision_ref)
        if self.effect_kind not in {"creator_response", "codex_delegation"}:
            raise EffectViolation("CON-EFFECT-KIND")
        if (
            self.effect_kind == "creator_response"
            and self.capability_kind != "creator.scene.reply"
        ) or (
            self.effect_kind == "codex_delegation"
            and self.capability_kind != "codex.delegated-work"
        ):
            raise EffectViolation("CON-EFFECT-CAPABILITY")
        if (self.status is EffectStatus.CANCELLED) != (self.cancelled_at is not None):
            raise EffectViolation("CON-EFFECT-STATE")
        if not 0 <= self.attempt_count <= 2:
            raise EffectViolation("CON-EFFECT-ATTEMPT")
        if (self.last_observation_kind is None) != (
            self.last_observation_reliability is None
        ):
            raise EffectViolation("CON-EFFECT-OBSERVATION")
        if (self.status is EffectStatus.UNKNOWN) != (
            self.verification_action is not None
        ):
            raise EffectViolation("CON-EFFECT-VERIFICATION")
        if self.status is not EffectStatus.COMPLETED and self.response_text is not None:
            raise EffectViolation("CON-EFFECT-VISIBILITY")
        if self.response_text is not None and (
            not self.response_text.strip() or "\x00" in self.response_text
        ):
            raise EffectViolation("CON-EFFECT-PAYLOAD")
        if self.effect_kind == "codex_delegation" and self.response_text is not None:
            raise EffectViolation("CON-EFFECT-VISIBILITY")


@dataclass(frozen=True, slots=True)
class EffectRegistrationDraft:
    action_intent_revision_id: UUID
    action_intent_id: UUID
    policy_decision_id: UUID | None
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID
    payload_artifact_id: UUID
    payload_digest: Digest
    payload_bytes: int
    effect_kind: str
    capability_kind: str
    operation_class: str
    purpose: str
    authorization_basis: str
    destination_kind: str
    destination_party_id: UUID
    destination_binding_id: UUID | None
    trace_id: TraceId
    dispatch_deadline: Instant
    max_attempts: int


@dataclass(frozen=True, slots=True)
class EffectRegistrationContext:
    operation_ref: UUID
    root_opportunity_id: UUID
    action_intent_revision_id: UUID
    action_intent_id: UUID
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID
    payload_artifact_id: UUID
    payload_digest: Digest
    payload_bytes: int
    trace_id: TraceId
    effect_kind: str
    capability_kind: str
    operation_class: str
    purpose: str
    destination_party_id: UUID
    destination_kind: str
    destination_binding_id: UUID | None


@runtime_checkable
class EffectRegistrationContextPort(Protocol):
    async def resolve(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        work: WorkRecord,
    ) -> EffectRegistrationContext: ...


@runtime_checkable
class EffectCodexArtifactPort(Protocol):
    async def artifact_reference(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        effect_id: UUID,
        kind: str,
    ) -> tuple[UUID, Digest, int, str]: ...


@dataclass(frozen=True, slots=True)
class EffectLedgerSnapshot:
    effect_id: UUID
    action_intent_revision_id: UUID
    action_intent_id: UUID
    policy_decision_id: UUID | None
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID
    payload_artifact_id: UUID
    payload_digest: Digest
    payload_bytes: int
    effect_kind: str
    capability_kind: str
    status: EffectStatus
    verification_status: EffectVerificationStatus
    registered_at: Instant
    cancelled_at: Instant | None
    settled_at: Instant | None
    attempt_count: int
    current_observation_kind: EffectObservationKind | None
    current_observation_reliability: EffectObservationReliability | None


@dataclass(frozen=True, slots=True)
class EffectCodexClaim:
    outbox_id: UUID
    effect_id: UUID
    attempt_id: UUID
    claim_owner: UUID
    claim_token: int
    action_intent_id: UUID
    action_intent_revision_id: UUID
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID
    trace_id: TraceId


@runtime_checkable
class EffectCodexLifecyclePort(Protocol):
    async def claim_codex(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        claim_owner: UUID,
    ) -> EffectCodexClaim | None: ...

    async def mark_codex_dispatching(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        claim: EffectCodexClaim,
    ) -> bool: ...

    async def heartbeat_codex(
        self,
        transaction: PostgreSQLTransaction,
        claim: EffectCodexClaim,
    ) -> bool: ...

    async def settle_codex(
        self,
        transaction: PostgreSQLTransaction,
        *,
        claim: EffectCodexClaim,
        status: str,
        observation_digest: Digest,
        error_code: str | None,
    ) -> None: ...


@runtime_checkable
class EffectOperationReadPort(Protocol):
    async def by_action_intent(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
    ) -> EffectLedgerSnapshot | None: ...

    async def by_effect_id(
        self,
        transaction: PostgreSQLTransaction,
        *,
        effect_id: UUID,
    ) -> EffectLedgerSnapshot | None: ...


@dataclass(frozen=True, slots=True)
class EffectObservationSnapshot:
    counts: tuple[tuple[str, int], ...]
    oldest_open_seconds: int | None


@runtime_checkable
class EffectObservationPort(Protocol):
    async def observe(
        self, transaction: PostgreSQLTransaction
    ) -> EffectObservationSnapshot: ...


@runtime_checkable
class EffectReadPort(EffectOperationReadPort, EffectObservationPort, Protocol): ...


class EffectViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or re.fullmatch(
                r"(?:CON-)?EFFECT-[A-Z0-9-]+|SCOPE-EFFECT-NOT-VISIBLE", code
            )
            is None
        ):
            raise ValueError("effect violation code is invalid")
        self.code = code
        super().__init__("effect ledger operation failed")

    def __str__(self) -> str:
        return f"{self.code}: effect ledger operation failed"


@runtime_checkable
class EffectLedgerPort(Protocol):
    async def register_once(self) -> bool: ...

    async def get_effect(
        self, effect_id: EffectId, *, creator_party_id: UUID
    ) -> EffectView: ...

    async def read_artifact(
        self,
        effect_id: EffectId,
        *,
        creator_party_id: UUID,
        kind: EffectArtifactKind,
    ) -> EffectArtifactContent: ...


@runtime_checkable
class EffectRuntimePort(EffectLedgerPort, Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def stop(self) -> None: ...
    async def run(self) -> None: ...
    async def dispatch_once(self) -> bool: ...
    async def recover_once(self) -> bool: ...


@runtime_checkable
class EffectArtifactStorePort(ArtifactPort, Protocol):
    async def prepare(self) -> None: ...


@runtime_checkable
class EffectGrantCancellationPort(Protocol):
    async def cancel_registered(
        self,
        transaction: PostgreSQLTransaction,
        *,
        policy_decision_ids: tuple[UUID, ...],
        reason_code: str,
    ) -> tuple[tuple[UUID, UUID, UUID], ...]: ...


@runtime_checkable
class EffectWakeupPort(Protocol):
    def version(self, channel: str) -> int: ...
    def notify(self, channel: str) -> None: ...

    async def wait(
        self,
        channel: str,
        after_version: int,
        *,
        stop: Event,
        timeout_seconds: float,
    ) -> int: ...


@runtime_checkable
class ResponseAdmissionRuntimePort(ResponseAdmissionPort, Protocol):
    async def open(self) -> None: ...
    async def close(self) -> None: ...
    def stop(self) -> None: ...
    async def run_worker(self) -> None: ...


@runtime_checkable
class ActionAdapterPort(Protocol):
    async def dispatch(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> EffectAdapterReceipt: ...

    async def observe(
        self, request: FrozenEffectRequest
    ) -> EffectAdapterReceipt | None: ...


@runtime_checkable
class EffectTimelinePort(Protocol):
    async def record_party_response(
        self,
        transaction: PostgreSQLTransaction,
        *,
        scene_id: UUID,
        effect_id: UUID,
        occurred_at: Instant,
    ) -> None: ...


def _uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise EffectViolation("CON-EFFECT-ID")


__all__ = (
    "ActionAdapterPort",
    "EffectAdapterReceipt",
    "EffectAdminPort",
    "EffectAdminSnapshot",
    "EffectArtifactContent",
    "EffectArtifactKind",
    "EffectArtifactStorePort",
    "EffectAttemptId",
    "EffectCodexArtifactPort",
    "EffectCodexClaim",
    "EffectCodexLifecyclePort",
    "EffectDeliveryId",
    "EffectDispatchBoundaryResult",
    "EffectGrantCancellationPort",
    "EffectId",
    "EffectLedgerPort",
    "EffectLedgerSnapshot",
    "EffectObservation",
    "EffectObservationId",
    "EffectObservationKind",
    "EffectObservationPort",
    "EffectObservationReliability",
    "EffectObservationSnapshot",
    "EffectOperationReadPort",
    "EffectReadPort",
    "EffectRegistrationContext",
    "EffectRegistrationContextPort",
    "EffectRegistrationDraft",
    "EffectRegistrationResult",
    "EffectRuntimePort",
    "EffectStatus",
    "EffectTimelinePort",
    "EffectVerificationStatus",
    "EffectView",
    "EffectViolation",
    "EffectWakeupPort",
    "FrozenEffectRequest",
    "PolicyDecisionId",
    "ResponseAdmissionRuntimePort",
)
