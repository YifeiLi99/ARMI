"""Technology-neutral T-05/T-06 effect ledger and execution contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest, Instant, TraceId


class PolicyDecisionOutcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    CONFIRMATION_REQUIRED = "confirmation_required"
    UNAVAILABLE = "unavailable"


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


class EffectAttemptState(StrEnum):
    PREPARED = "prepared"
    DISPATCHING = "dispatching"
    SETTLED = "settled"


class EffectAttemptResult(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"


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
    destination_kind: Literal["creator_inbox", "other_human_inbox", "external_group"]
    external_channel: str | None
    external_account_key: str | None
    external_conversation_key: str | None
    payload_digest: Digest
    payload_bytes: int
    request_digest: Digest
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
        }:
            raise EffectViolation("CON-EFFECT-DESTINATION")
        route = (
            self.external_channel,
            self.external_account_key,
            self.external_conversation_key,
        )
        if self.destination_kind == "external_group":
            if any(
                type(value) is not str
                or re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$", value) is None
                for value in route
            ):
                raise EffectViolation("CON-EFFECT-DESTINATION")
            assert self.external_channel is not None
            if re.fullmatch(r"^[a-z][a-z0-9._-]{0,63}$", self.external_channel) is None:
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
class EffectSettlement:
    effect_id: EffectId
    status: EffectStatus
    verification_status: EffectVerificationStatus
    attempt_count: int
    observation: EffectObservation | None
    settlement_digest: Digest | None
    settled_at: Instant | None

    def __post_init__(self) -> None:
        if type(self.attempt_count) is not int or not 0 <= self.attempt_count <= 2:
            raise EffectViolation("CON-EFFECT-ATTEMPT")
        settled = self.status in {
            EffectStatus.COMPLETED,
            EffectStatus.FAILED,
            EffectStatus.UNKNOWN,
        } or (
            self.status is EffectStatus.CANCELLED
            and self.verification_status is EffectVerificationStatus.VERIFIED
        )
        if settled != (self.settlement_digest is not None):
            raise EffectViolation("CON-EFFECT-SETTLEMENT")
        if settled != (self.settled_at is not None):
            raise EffectViolation("CON-EFFECT-SETTLEMENT")


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
    root_operation_ref: UUID
    effect_kind: Literal["creator_response", "codex_delegation"]
    status: EffectStatus
    verification_status: EffectVerificationStatus
    registered_at: Instant
    capability_request_ref: UUID
    grant_ref: UUID
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
    model_id: Literal["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"] | None = None
    sdk_identity: Literal["openai-codex==0.144.4"] | None = None
    source_tree_digest: Digest | None = None
    result_tree_digest: Digest | None = None
    patch_digest: Digest | None = None
    changed_path_count: int | None = None
    validation_status: Literal["passed", "failed", "not_run"] | None = None
    cleanup_status: Literal["succeeded", "failed"] | None = None
    result_acceptance_status: Literal["pending", "accepted"] | None = None

    def __post_init__(self) -> None:
        _uuid7(self.root_operation_ref)
        _uuid7(self.capability_request_ref)
        _uuid7(self.grant_ref)
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
        codex_fields = (
            self.model_id,
            self.sdk_identity,
            self.source_tree_digest,
            self.result_tree_digest,
            self.patch_digest,
            self.changed_path_count,
            self.validation_status,
            self.cleanup_status,
            self.result_acceptance_status,
        )
        if self.effect_kind == "creator_response" and any(
            value is not None for value in codex_fields
        ):
            raise EffectViolation("CON-EFFECT-VISIBILITY")
        if self.effect_kind == "codex_delegation":
            if self.response_text is not None:
                raise EffectViolation("CON-EFFECT-VISIBILITY")
            if self.status in {
                EffectStatus.COMPLETED,
                EffectStatus.FAILED,
                EffectStatus.UNKNOWN,
            } and any(
                value is None
                for value in (
                    self.sdk_identity,
                    self.source_tree_digest,
                    self.validation_status,
                    self.cleanup_status,
                    self.result_acceptance_status,
                )
            ):
                raise EffectViolation("CON-EFFECT-VERIFICATION")
            if self.changed_path_count is not None and self.changed_path_count < 0:
                raise EffectViolation("CON-EFFECT-VERIFICATION")


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
class ActionAdapterPort(Protocol):
    async def dispatch(
        self, request: FrozenEffectRequest, payload: bytes
    ) -> EffectAdapterReceipt: ...

    async def observe(
        self, request: FrozenEffectRequest
    ) -> EffectAdapterReceipt | None: ...


def _uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise EffectViolation("CON-EFFECT-ID")


__all__ = (
    "ActionAdapterPort",
    "EffectAdapterReceipt",
    "EffectArtifactContent",
    "EffectArtifactKind",
    "EffectAttemptId",
    "EffectAttemptResult",
    "EffectAttemptState",
    "EffectDeliveryId",
    "EffectId",
    "EffectLedgerPort",
    "EffectObservation",
    "EffectObservationId",
    "EffectObservationKind",
    "EffectObservationReliability",
    "EffectRegistrationResult",
    "EffectSettlement",
    "EffectStatus",
    "EffectVerificationStatus",
    "EffectView",
    "EffectViolation",
    "FrozenEffectRequest",
    "PolicyDecisionId",
    "PolicyDecisionOutcome",
)
