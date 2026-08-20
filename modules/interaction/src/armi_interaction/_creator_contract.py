"""Technology-neutral contracts for durable Creator input acceptance."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_attention.api import OpportunityId
from armi_evidence.api import EvidenceId
from armi_kernel.contracts import Digest, IdempotencyKey, TraceId

_CODE = re.compile(
    r"^(?:CON-INPUT|INPUT|IDEMPOTENCY|SCOPE|AUTHORITY|ART|DB)-[A-Z0-9-]+$",
    re.ASCII,
)
_MAX_MESSAGE_BYTES = 256 * 1024


class CreatorInputViolation(RuntimeError):
    """Expose a stable input-acceptance code without message or adapter detail."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("creator input violation code is invalid")
        self.code = code
        super().__init__("creator input acceptance failed")

    def __str__(self) -> str:
        return f"{self.code}: creator input acceptance failed"


def _require_uuid7(value: object, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise CreatorInputViolation(code)


@dataclass(frozen=True, slots=True)
class CreatorInteractionId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-INPUT-INTERACTION-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CreatorInputContext:
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.subject_id, "CON-INPUT-SUBJECT-ID")
        _require_uuid7(self.scene_id, "CON-INPUT-SCENE-ID")
        _require_uuid7(self.creator_party_id, "CON-INPUT-CREATOR")


@dataclass(frozen=True, slots=True)
class CreatorInputCommand:
    scene_key: str
    message: str
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        if (
            type(self.scene_key) is not str
            or re.fullmatch(
                r"[a-z0-9][a-z0-9._-]{0,63}",
                self.scene_key,
                re.ASCII,
            )
            is None
        ):
            raise CreatorInputViolation("CON-INPUT-SCENE")
        if type(self.message) is not str or "\x00" in self.message:
            raise CreatorInputViolation("CON-INPUT-MESSAGE")
        try:
            encoded = self.message.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise CreatorInputViolation("CON-INPUT-UNICODE") from None
        if not encoded or len(encoded) > _MAX_MESSAGE_BYTES:
            raise CreatorInputViolation("CON-INPUT-SIZE")
        if not any(not character.isspace() for character in self.message):
            raise CreatorInputViolation("CON-INPUT-MESSAGE")
        if type(self.idempotency_key) is not IdempotencyKey:
            raise CreatorInputViolation("CON-INPUT-IDEMPOTENCY")
        if type(self.trace_id) is not TraceId:
            raise CreatorInputViolation("CON-INPUT-TRACE")

    @property
    def message_bytes(self) -> bytes:
        return self.message.encode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class CreatorVoiceInputCommand:
    """A final local live-voice transcript awaiting a fast-route decision."""

    scene_key: str
    transcript: str
    idempotency_key: IdempotencyKey
    trace_id: TraceId

    def __post_init__(self) -> None:
        CreatorInputCommand(
            scene_key=self.scene_key,
            message=self.transcript,
            idempotency_key=self.idempotency_key,
            trace_id=self.trace_id,
        )

    @property
    def transcript_bytes(self) -> bytes:
        return self.transcript.encode("utf-8", errors="strict")


@dataclass(frozen=True, slots=True)
class CreatorVoiceInputAcceptance:
    interaction_id: CreatorInteractionId
    evidence_id: EvidenceId
    request_digest: Digest
    content_digest: Digest
    newly_accepted: bool = field(compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.interaction_id) is not CreatorInteractionId
            or type(self.evidence_id) is not EvidenceId
            or type(self.request_digest) is not Digest
            or type(self.content_digest) is not Digest
            or type(self.newly_accepted) is not bool
        ):
            raise CreatorInputViolation("CON-INPUT-ACCEPTANCE")


@dataclass(frozen=True, slots=True)
class CreatorInputAcceptance:
    interaction_id: CreatorInteractionId
    evidence_id: EvidenceId
    opportunity_id: OpportunityId
    request_digest: Digest
    content_digest: Digest
    newly_accepted: bool = field(compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.interaction_id) is not CreatorInteractionId
            or type(self.evidence_id) is not EvidenceId
            or type(self.opportunity_id) is not OpportunityId
            or type(self.request_digest) is not Digest
            or type(self.content_digest) is not Digest
            or type(self.newly_accepted) is not bool
        ):
            raise CreatorInputViolation("CON-INPUT-ACCEPTANCE")


class CreatorOperationPhase(StrEnum):
    ACCEPTED = "accepted"
    CONTEXT_PREPARING = "context_preparing"
    CONTEXT_PREPARED = "context_prepared"
    MODEL_CALLING = "model_calling"
    MODEL_RETURNED = "model_returned"
    CANDIDATE_VALIDATING = "candidate_validating"
    CANDIDATE_VALIDATED = "candidate_validated"
    CANDIDATE_REJECTED = "candidate_rejected"
    SUBJECT_COMMITTING = "subject_committing"
    RESPONSE_ADMISSION = "response_admission"
    RESPONSE_ACCEPTED = "response_accepted"
    EFFECT_REGISTRATION = "effect_registration"
    EFFECT_REGISTERED = "effect_registered"
    EFFECT_DISPATCHING = "effect_dispatching"
    EFFECT_COMPLETED = "effect_completed"
    EFFECT_FAILED = "effect_failed"
    EFFECT_UNKNOWN = "effect_unknown"
    EFFECT_CANCELLED = "effect_cancelled"
    CODEX_CAPABILITY_DECISION = "codex_capability_decision"
    CODEX_DISPATCHING = "codex_dispatching"
    CODEX_VERIFYING = "codex_verifying"
    CODEX_RESULT_ACCEPTANCE = "codex_result_acceptance"
    CODEX_RESULT_REJECTED = "codex_result_rejected"
    CODEX_COMPLETED = "codex_completed"
    CODEX_FAILED = "codex_failed"
    CODEX_UNKNOWN = "codex_unknown"
    CODEX_CANCELLED = "codex_cancelled"
    FORMAL_DECLINED = "formal_declined"
    FORMAL_NO_ACTION = "formal_no_action"
    RESPONSE_UNAUTHORIZED = "response_unauthorized"
    RESPONSE_UNAVAILABLE = "response_unavailable"
    RESPONSE_FAILED = "response_failed"
    APPLIED = "applied"
    COMPLETED = "completed"
    DEFERRED = "deferred"
    NEED_INFORMATION = "need_information"
    STALE_CONFLICT = "stale_conflict"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CreatorCodexExecutionSummary:
    task_source_ref: UUID
    verification_ref: UUID | None
    execution_status: str | None
    model_id: str | None
    sdk_identity: str | None
    validator_id: str
    source_tree_digest: Digest
    final_tree_digest: Digest | None

    def __post_init__(self) -> None:
        if (
            type(self.task_source_ref) is not UUID
            or self.task_source_ref.version != 7
            or (
                self.verification_ref is not None
                and (
                    type(self.verification_ref) is not UUID
                    or self.verification_ref.version != 7
                )
            )
            or type(self.validator_id) is not str
            or not self.validator_id
            or type(self.source_tree_digest) is not Digest
            or (
                self.final_tree_digest is not None
                and type(self.final_tree_digest) is not Digest
            )
        ):
            raise CreatorInputViolation("CON-INPUT-OPERATION")
        for value in (self.execution_status, self.model_id, self.sdk_identity):
            if value is not None and (type(value) is not str or not value):
                raise CreatorInputViolation("CON-INPUT-OPERATION")


@dataclass(frozen=True, slots=True)
class CreatorOperation:
    acceptance: CreatorInputAcceptance
    phase: CreatorOperationPhase
    failure_code: str | None = None
    subject_version: int | None = None
    effect_ref: UUID | None = None
    intent_ref: UUID | None = None
    dialogue_decision_ref: UUID | None = None
    policy_decision_ref: UUID | None = None
    work_ref: UUID | None = None
    operation_kind: str = "cognition"
    codex_execution: CreatorCodexExecutionSummary | None = None

    def __post_init__(self) -> None:
        if (
            type(self.acceptance) is not CreatorInputAcceptance
            or type(self.phase) is not CreatorOperationPhase
        ):
            raise CreatorInputViolation("CON-INPUT-OPERATION")
        if self.phase is CreatorOperationPhase.APPLIED:
            if type(self.subject_version) is not int or self.subject_version <= 0:
                raise CreatorInputViolation("CON-INPUT-OPERATION")
        elif self.subject_version is not None:
            raise CreatorInputViolation("CON-INPUT-OPERATION")
        if (
            self.phase
            in {
                CreatorOperationPhase.EFFECT_REGISTERED,
                CreatorOperationPhase.EFFECT_DISPATCHING,
                CreatorOperationPhase.EFFECT_COMPLETED,
                CreatorOperationPhase.EFFECT_FAILED,
                CreatorOperationPhase.EFFECT_UNKNOWN,
                CreatorOperationPhase.EFFECT_CANCELLED,
                CreatorOperationPhase.CODEX_DISPATCHING,
                CreatorOperationPhase.CODEX_VERIFYING,
                CreatorOperationPhase.CODEX_RESULT_ACCEPTANCE,
                CreatorOperationPhase.CODEX_RESULT_REJECTED,
                CreatorOperationPhase.CODEX_COMPLETED,
                CreatorOperationPhase.CODEX_FAILED,
                CreatorOperationPhase.CODEX_UNKNOWN,
                CreatorOperationPhase.CODEX_CANCELLED,
            }
        ) != (self.effect_ref is not None):
            raise CreatorInputViolation("CON-INPUT-OPERATION")
        if self.effect_ref is not None and (
            type(self.effect_ref) is not UUID or self.effect_ref.version != 7
        ):
            raise CreatorInputViolation("CON-INPUT-OPERATION")
        for owner_ref in (
            self.intent_ref,
            self.dialogue_decision_ref,
            self.policy_decision_ref,
            self.work_ref,
        ):
            if owner_ref is not None and (
                type(owner_ref) is not UUID or owner_ref.version != 7
            ):
                raise CreatorInputViolation("CON-INPUT-OPERATION")
        if self.operation_kind not in {
            "cognition",
            "subject_change",
            "creator_response",
            "other_human_response",
            "codex_delegation",
            "formal_dialogue",
        }:
            raise CreatorInputViolation("CON-INPUT-OPERATION")
        if self.codex_execution is not None and (
            self.operation_kind != "codex_delegation"
            or type(self.codex_execution) is not CreatorCodexExecutionSummary
        ):
            raise CreatorInputViolation("CON-INPUT-OPERATION")
        if self.phase is CreatorOperationPhase.FAILED:
            if (
                type(self.failure_code) is not str
                or re.fullmatch(
                    r"(?:CTX|MODEL|CANDIDATE|SUBJECT|RESPONSE|POLICY|ACTION)-[A-Z0-9-]+",
                    self.failure_code,
                )
                is None
            ):
                raise CreatorInputViolation("CON-INPUT-OPERATION")
        elif self.phase in {
            CreatorOperationPhase.CANDIDATE_REJECTED,
            CreatorOperationPhase.CODEX_RESULT_REJECTED,
        }:
            if (
                type(self.failure_code) is not str
                or re.fullmatch(r"CANDIDATE-[A-Z0-9-]+", self.failure_code) is None
            ):
                raise CreatorInputViolation("CON-INPUT-OPERATION")
        elif self.phase is CreatorOperationPhase.STALE_CONFLICT:
            if self.failure_code != "CONFLICT_SUBJECT_STATE_STALE":
                raise CreatorInputViolation("CON-INPUT-OPERATION")
        elif self.phase in {
            CreatorOperationPhase.RESPONSE_UNAUTHORIZED,
            CreatorOperationPhase.RESPONSE_UNAVAILABLE,
            CreatorOperationPhase.RESPONSE_FAILED,
            CreatorOperationPhase.EFFECT_FAILED,
            CreatorOperationPhase.EFFECT_UNKNOWN,
            CreatorOperationPhase.CODEX_FAILED,
            CreatorOperationPhase.CODEX_UNKNOWN,
        }:
            if self.failure_code is None:
                raise CreatorInputViolation("CON-INPUT-OPERATION")
        elif self.failure_code is not None:
            raise CreatorInputViolation("CON-INPUT-OPERATION")


@runtime_checkable
class CreatorInputAcceptancePort(Protocol):
    async def accept(self, command: CreatorInputCommand) -> CreatorInputAcceptance:
        """Durably accept one Creator input through the authoritative owner."""
        ...


@runtime_checkable
class CreatorVoiceInputAcceptancePort(Protocol):
    async def accept_voice(
        self, command: CreatorVoiceInputCommand
    ) -> CreatorVoiceInputAcceptance:
        """Accept one final transcript without admitting the normal reply yet."""
        ...


@runtime_checkable
class CreatorVoiceInputSuccessorPort(Protocol):
    async def release_voice_appraisal(
        self, acceptance: CreatorVoiceInputAcceptance
    ) -> OpportunityId:
        """Admit only the private appraisal successor after a fast decision."""
        ...

    async def release_voice_slow(
        self, acceptance: CreatorVoiceInputAcceptance
    ) -> OpportunityId:
        """Admit the normal cognition successor for the same accepted evidence."""
        ...


@runtime_checkable
class CreatorOperationQueryPort(Protocol):
    async def get(self, opportunity_id: OpportunityId) -> CreatorOperation:
        """Return one authorized operation projection from authoritative facts."""
        ...


__all__ = (
    "CreatorCodexExecutionSummary",
    "CreatorInputAcceptance",
    "CreatorInputAcceptancePort",
    "CreatorInputCommand",
    "CreatorInputContext",
    "CreatorInputViolation",
    "CreatorInteractionId",
    "CreatorOperation",
    "CreatorOperationPhase",
    "CreatorOperationQueryPort",
    "CreatorVoiceInputAcceptance",
    "CreatorVoiceInputAcceptancePort",
    "CreatorVoiceInputCommand",
    "CreatorVoiceInputSuccessorPort",
    "OpportunityId",
)
