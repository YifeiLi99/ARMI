"""Public contracts for ARMI intention and expression."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import ArtifactRef, WorkRecord
from armi_kernel.contracts import Digest, TraceId
from armi_runtime_foundation import (
    PostgreSQLAdminTransaction,
    PostgreSQLRuntimeUnitOfWork,
    PostgreSQLTransaction,
)


@dataclass(frozen=True, slots=True)
class ExpressionAdminSnapshot:
    action_intent_id: UUID
    operation_ref: UUID
    root_opportunity_id: UUID


@runtime_checkable
class ExpressionAdminPort(Protocol):
    def operation(
        self, transaction: PostgreSQLAdminTransaction, *, operation_ref: UUID
    ) -> ExpressionAdminSnapshot | None: ...
    def intent(
        self, transaction: PostgreSQLAdminTransaction, *, action_intent_id: UUID
    ) -> ExpressionAdminSnapshot | None: ...
    def inspect_ids(
        self, transaction: PostgreSQLAdminTransaction, *, object_ids: tuple[UUID, ...]
    ) -> tuple[UUID, ...]: ...
    def artifact_reference_count(
        self, transaction: PostgreSQLAdminTransaction, *, artifact_id: UUID
    ) -> int: ...


_CODE = re.compile(
    r"^(?:CON|RESPONSE|ACTION|POLICY|SCOPE|SUBJECT)-[A-Z0-9-]+$", re.ASCII
)
_PROPOSAL = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)
_GROUP = re.compile(r"^group:[1-9][0-9]{0,2}$", re.ASCII)


class FormalNoActionKind(StrEnum):
    DECLINE = "decline"
    NO_ACTION = "no_action"


class FormalNoActionReason(StrEnum):
    SUBJECTIVE_REFUSAL = "subjective_refusal"
    SUBJECTIVE_SILENCE = "subjective_silence"


class ResponseAdmissionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    NO_ACTION = "no_action"
    UNAUTHORIZED = "unauthorized"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ResponseViolation(RuntimeError):
    """Expose a stable response failure without response content."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("response violation code is invalid")
        self.code = code
        super().__init__("Creator response admission failed")

    def __str__(self) -> str:
        return f"{self.code}: Creator response admission failed"


@dataclass(frozen=True, slots=True)
class ActionIntentId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-RESPONSE-ACTION-ID")


@dataclass(frozen=True, slots=True)
class FormalNoActionId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-RESPONSE-NO-ACTION-ID")


@dataclass(frozen=True, slots=True)
class CreatorResponseOperationId:
    value: UUID

    def __post_init__(self) -> None:
        _uuid7(self.value, "CON-RESPONSE-OPERATION-ID")


@dataclass(frozen=True, slots=True)
class ExpressionCommitContext:
    """Frozen subject-commit identity visible to the expression owner."""

    validation_id: UUID
    episode_id: UUID
    opportunity_id: UUID
    root_opportunity_id: UUID
    subject_id: UUID
    generation_id: UUID
    scene_id: UUID | None
    creator_party_id: UUID | None
    other_party_id: UUID | None
    opportunity_purpose: str
    trace_id: TraceId

    def __post_init__(self) -> None:
        for value in (
            self.validation_id,
            self.episode_id,
            self.opportunity_id,
            self.root_opportunity_id,
            self.subject_id,
            self.generation_id,
        ):
            _uuid7(value, "CON-RESPONSE-COMMIT-CONTEXT")
        for value in (self.scene_id, self.creator_party_id, self.other_party_id):
            if value is not None:
                _uuid7(value, "CON-RESPONSE-COMMIT-CONTEXT")
        if (
            type(self.opportunity_purpose) is not str
            or not self.opportunity_purpose
            or type(self.trace_id) is not TraceId
        ):
            raise ResponseViolation("CON-RESPONSE-COMMIT-CONTEXT")


@dataclass(frozen=True, slots=True)
class CreatorReplyDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    content_bytes: bytes
    capability_kind: str = "creator.scene.reply"
    operation: str = "send"
    audience_scope: str = "creator"
    data_scope: str = "creator_visible_response"
    purpose: str = "respond_to_creator"
    media_type: str = "text/plain"

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        for value in (self.subject_id, self.scene_id, self.creator_party_id):
            _uuid7(value, "CON-RESPONSE-REPLY")
        if (
            type(self.content_bytes) is not bytes
            or not 1 <= len(self.content_bytes) <= 65536
            or b"\x00" in self.content_bytes
            or self.capability_kind != "creator.scene.reply"
            or self.operation != "send"
            or self.audience_scope != "creator"
            or self.data_scope != "creator_visible_response"
            or self.purpose != "respond_to_creator"
            or self.media_type != "text/plain"
        ):
            raise ResponseViolation("CON-RESPONSE-REPLY")
        try:
            text = self.content_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ResponseViolation("CON-RESPONSE-REPLY") from None
        if not text.strip():
            raise ResponseViolation("CON-RESPONSE-REPLY")


@dataclass(frozen=True, slots=True)
class OtherHumanReplyDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    subject_id: UUID
    scene_id: UUID
    other_party_id: UUID
    content_bytes: bytes
    capability_kind: str = "local.other-human-inbox.deliver"
    operation: str = "send"
    audience_scope: str = "other_human"
    data_scope: str = "declared_party_response"
    purpose: str = "respond_to_other_human"
    media_type: str = "text/plain"

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        for value in (self.subject_id, self.scene_id, self.other_party_id):
            _uuid7(value, "CON-RESPONSE-OTHER-HUMAN-REPLY")
        if (
            type(self.content_bytes) is not bytes
            or not 1 <= len(self.content_bytes) <= 65536
            or b"\x00" in self.content_bytes
            or self.capability_kind != "local.other-human-inbox.deliver"
            or self.operation != "send"
            or self.audience_scope != "other_human"
            or self.data_scope != "declared_party_response"
            or self.purpose != "respond_to_other_human"
            or self.media_type != "text/plain"
        ):
            raise ResponseViolation("CON-RESPONSE-OTHER-HUMAN-REPLY")
        try:
            text = self.content_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ResponseViolation("CON-RESPONSE-OTHER-HUMAN-REPLY") from None
        if not text.strip():
            raise ResponseViolation("CON-RESPONSE-OTHER-HUMAN-REPLY")


@dataclass(frozen=True, slots=True)
class OtherHumanEndConversationDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    subject_id: UUID
    scene_id: UUID
    other_party_id: UUID

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        for value in (self.subject_id, self.scene_id, self.other_party_id):
            _uuid7(value, "CON-RESPONSE-OTHER-HUMAN-END")


@dataclass(frozen=True, slots=True)
class FormalNoActionDraft:
    proposal_ref: str
    atomic_group_ref: str
    basis_ordinals: tuple[int, ...]
    kind: FormalNoActionKind
    reason: FormalNoActionReason

    def __post_init__(self) -> None:
        _proposal(self.proposal_ref, self.atomic_group_ref, self.basis_ordinals)
        expected = {
            FormalNoActionKind.DECLINE: FormalNoActionReason.SUBJECTIVE_REFUSAL,
            FormalNoActionKind.NO_ACTION: FormalNoActionReason.SUBJECTIVE_SILENCE,
        }
        if (
            type(self.kind) is not FormalNoActionKind
            or self.reason is not expected[self.kind]
        ):
            raise ResponseViolation("CON-RESPONSE-NO-ACTION")


type ResponseChoiceDraft = (
    CreatorReplyDraft
    | OtherHumanReplyDraft
    | OtherHumanEndConversationDraft
    | FormalNoActionDraft
)


@dataclass(frozen=True, slots=True)
class DeclaredResponseEffectDraft:
    """Effect-registration facts frozen by the expression owner."""

    action_intent_revision_id: UUID
    action_intent_id: UUID
    operation_ref: UUID
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID
    payload_artifact_id: UUID
    payload_digest: Digest
    payload_bytes: int
    effect_kind: str
    capability_kind: str
    audience_scope: str
    authorization_basis: str
    destination_kind: str
    destination_party_id: UUID
    destination_binding_id: UUID | None
    trace_id: TraceId
    max_attempts: int

    def __post_init__(self) -> None:
        for value in (
            self.action_intent_revision_id,
            self.action_intent_id,
            self.operation_ref,
            self.subject_id,
            self.scene_id,
            self.context_party_id,
            self.payload_artifact_id,
            self.destination_party_id,
        ):
            _uuid7(value, "CON-RESPONSE-EFFECT")
        if self.destination_binding_id is not None:
            _uuid7(self.destination_binding_id, "CON-RESPONSE-EFFECT")
        if (
            type(self.payload_digest) is not Digest
            or type(self.trace_id) is not TraceId
            or type(self.payload_bytes) is not int
            or not 1 <= self.payload_bytes <= 65536
            or self.effect_kind
            not in {
                "external_group_delivery",
                "external_private_delivery",
                "local_inbox_delivery",
            }
            or type(self.capability_kind) is not str
            or not self.capability_kind
            or self.audience_scope not in {"social_group", "other_human"}
            or self.authorization_basis
            not in {"runtime_configuration", "runtime_builtin"}
            or self.destination_kind
            not in {"external_group", "external_private", "other_human_inbox"}
            or self.max_attempts not in {1, 2}
        ):
            raise ResponseViolation("CON-RESPONSE-EFFECT")


@dataclass(frozen=True, slots=True)
class ResponseAdmissionResult:
    operation_ref: CreatorResponseOperationId
    status: ResponseAdmissionStatus
    action_intent_id: ActionIntentId | None = None
    no_action_id: FormalNoActionId | None = None
    grant_ref: UUID | None = None
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if (
            type(self.operation_ref) is not CreatorResponseOperationId
            or type(self.status) is not ResponseAdmissionStatus
            or (
                self.grant_ref is not None
                and (type(self.grant_ref) is not UUID or self.grant_ref.version != 7)
            )
            or (
                self.reason_code is not None
                and _CODE.fullmatch(self.reason_code) is None
            )
        ):
            raise ResponseViolation("CON-RESPONSE-RESULT")
        if (self.status is ResponseAdmissionStatus.NO_ACTION) != (
            self.no_action_id is not None
        ):
            raise ResponseViolation("CON-RESPONSE-RESULT")
        if (
            self.status is ResponseAdmissionStatus.ACCEPTED
            and self.action_intent_id is None
        ):
            raise ResponseViolation("CON-RESPONSE-RESULT")


@runtime_checkable
class ResponseAdmissionPort(Protocol):
    async def admit_once(self) -> bool:
        """Claim and settle at most one durable response admission."""
        ...


@dataclass(frozen=True, slots=True)
class ExpressionIntentSnapshot:
    operation_ref: UUID
    action_intent_id: UUID
    action_intent_revision_id: UUID
    root_opportunity_id: UUID
    subject_id: UUID
    scene_id: UUID
    context_party_id: UUID
    action_kind: str
    capability_kind: str
    operation_class: str
    purpose: str
    response_artifact_id: UUID | None
    response_digest: Digest | None
    response_bytes: int | None
    codex_task_source_id: UUID | None
    task_manifest_digest: Digest | None
    validator_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ExpressionOperationSnapshot:
    operation_ref: UUID
    intent_id: UUID | None
    intent_revision_id: UUID | None
    dialogue_decision_id: UUID | None
    action_kind: str | None
    decision_kind: str | None
    reason_code: str | None


@dataclass(frozen=True, slots=True)
class DelegatedActionIntentDraft:
    operation_ref: UUID
    subject_id: UUID
    scene_id: UUID
    creator_party_id: UUID
    root_opportunity_id: UUID
    validation_id: UUID
    proposal_ref: str
    task_source_id: UUID
    task_manifest_digest: Digest
    validator_id: str


@runtime_checkable
class ExpressionResponseAdmissionPort(Protocol):
    async def response_admission_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        work: WorkRecord,
    ) -> ExpressionIntentSnapshot: ...


@runtime_checkable
class ExpressionIntentReadPort(Protocol):
    async def outreach_intents(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        scene_id: UUID,
        context_party_id: UUID,
    ) -> tuple[ExpressionIntentSnapshot, ...]: ...

    async def intent_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
    ) -> ExpressionIntentSnapshot: ...

    async def revision_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_revision_id: UUID,
    ) -> ExpressionIntentSnapshot: ...

    async def delegation_for_commit(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_commit_id: UUID,
    ) -> ExpressionIntentSnapshot | None: ...

    async def operation_snapshot(
        self,
        transaction: PostgreSQLTransaction,
        *,
        operation_ref: UUID,
    ) -> ExpressionOperationSnapshot | None: ...


@runtime_checkable
class ExpressionEffectLinkPort(Protocol):
    async def link_effect(
        self,
        transaction: PostgreSQLTransaction,
        *,
        action_intent_id: UUID,
        effect_id: UUID,
    ) -> None: ...


@runtime_checkable
class ExpressionEffectRegistrationPort(Protocol):
    async def register_declared_response(
        self,
        transaction: PostgreSQLTransaction,
        draft: DeclaredResponseEffectDraft,
    ) -> UUID:
        """Register an effect inside the expression owner's transaction."""
        ...


@runtime_checkable
class ExpressionCommitPort(Protocol):
    async def commit(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        commit_id: UUID,
        choices: tuple[ResponseChoiceDraft, ...],
        response_artifact: ArtifactRef | None,
    ) -> None:
        """Commit an accepted expression inside the caller-owned transaction."""
        ...

    async def record_terminal(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        context: ExpressionCommitContext,
        application_id: UUID,
        application_status: str,
        choices: tuple[ResponseChoiceDraft, ...],
        activity_owned: bool,
    ) -> None:
        """Record a committed silence, refusal, or deferred social response."""
        ...

    async def commit_delegation(
        self,
        unit_of_work: PostgreSQLRuntimeUnitOfWork,
        *,
        commit_id: UUID,
        draft: DelegatedActionIntentDraft,
    ) -> None: ...


def _proposal(proposal_ref: str, group_ref: str, basis: tuple[int, ...]) -> None:
    if (
        type(proposal_ref) is not str
        or _PROPOSAL.fullmatch(proposal_ref) is None
        or type(group_ref) is not str
        or _GROUP.fullmatch(group_ref) is None
        or type(basis) is not tuple
        or not 1 <= len(basis) <= 8
        or len(set(basis)) != len(basis)
        or any(type(value) is not int or not 1 <= value <= 999 for value in basis)
    ):
        raise ResponseViolation("CON-RESPONSE-PROPOSAL")


def _uuid7(value: UUID, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise ResponseViolation(code)


__all__ = (
    "ActionIntentId",
    "CreatorReplyDraft",
    "CreatorResponseOperationId",
    "DeclaredResponseEffectDraft",
    "DelegatedActionIntentDraft",
    "ExpressionAdminPort",
    "ExpressionAdminSnapshot",
    "ExpressionCommitContext",
    "ExpressionCommitPort",
    "ExpressionEffectLinkPort",
    "ExpressionEffectRegistrationPort",
    "ExpressionIntentReadPort",
    "ExpressionIntentSnapshot",
    "ExpressionOperationSnapshot",
    "ExpressionResponseAdmissionPort",
    "FormalNoActionDraft",
    "FormalNoActionId",
    "FormalNoActionKind",
    "FormalNoActionReason",
    "OtherHumanEndConversationDraft",
    "OtherHumanReplyDraft",
    "ResponseAdmissionPort",
    "ResponseAdmissionResult",
    "ResponseAdmissionStatus",
    "ResponseChoiceDraft",
    "ResponseViolation",
)
