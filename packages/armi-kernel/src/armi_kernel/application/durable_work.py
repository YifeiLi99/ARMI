"""Technology-neutral durable-work custody contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import (
    Digest,
    IdempotencyKey,
    Instant,
    SubjectId,
    TraceId,
)

_TOKEN = re.compile(r"^[a-z][a-z0-9._-]{0,63}$", re.ASCII)


def _require_token(value: object) -> None:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise WorkViolation("WORK-DECLARATION")


class WorkStatus(StrEnum):
    READY = "ready"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkType(StrEnum):
    """Closed set of durable responsibilities admitted by this Runtime."""

    COGNITION_CONTEXT_PREPARE = "cognition.context.prepare"
    COGNITION_MODEL_INVOKE = "cognition.model.invoke"
    COGNITION_CANDIDATE_VALIDATE = "cognition.candidate.validate"
    COGNITION_SUBJECT_COMMIT = "cognition.subject.commit"
    COGNITION_RESPONSE_ADMIT = "cognition.response.admit"
    EFFECT_REGISTER = "effect.register"
    WEB_OBSERVATION_ADMIT = "web.observation.admit"
    WEB_SEARCH_INVOKE = "web.search.invoke"
    EXTERNAL_CONTENT_RECOGNIZE = "external.content.recognize"
    EXTERNAL_CONTENT_FINALIZE = "external.content.finalize"
    LIFE_QUERY_EXECUTE = "life.query.execute"
    CONTEXT_EMBEDDING_PROJECT = "context.embedding.project"
    ARTIFACT_OBJECT_DELETE = "artifact.object.delete"
    LIVE_VISION_OBSERVE = "live.vision.observe"


@dataclass(frozen=True, slots=True)
class ResponsibilityBinding:
    owner_kind: str
    work_type: WorkType
    reconciliation_owner: str

    def __post_init__(self) -> None:
        _require_token(self.owner_kind)
        if type(self.work_type) is not WorkType:
            raise WorkViolation("WORK-RESPONSIBILITY-REGISTRY")
        _require_token(self.reconciliation_owner)


RESPONSIBILITY_BINDINGS: tuple[ResponsibilityBinding, ...] = (
    ResponsibilityBinding(
        "cognitive_episode", WorkType.COGNITION_CONTEXT_PREPARE, "cognition"
    ),
    ResponsibilityBinding(
        "cognitive_episode", WorkType.COGNITION_MODEL_INVOKE, "cognition"
    ),
    ResponsibilityBinding(
        "cognitive_episode", WorkType.COGNITION_CANDIDATE_VALIDATE, "cognition"
    ),
    ResponsibilityBinding(
        "cognitive_episode", WorkType.COGNITION_SUBJECT_COMMIT, "cognition"
    ),
    ResponsibilityBinding(
        "action_intent", WorkType.COGNITION_RESPONSE_ADMIT, "expression"
    ),
    ResponsibilityBinding("action_intent", WorkType.EFFECT_REGISTER, "effect"),
    ResponsibilityBinding(
        "web_research_intent", WorkType.WEB_OBSERVATION_ADMIT, "web-observation"
    ),
    ResponsibilityBinding(
        "web_observation", WorkType.WEB_SEARCH_INVOKE, "web-observation"
    ),
    ResponsibilityBinding(
        "external_message", WorkType.EXTERNAL_CONTENT_RECOGNIZE, "perception"
    ),
    ResponsibilityBinding(
        "external_message", WorkType.EXTERNAL_CONTENT_FINALIZE, "interaction"
    ),
    ResponsibilityBinding(
        "exact_life_query_intent", WorkType.LIFE_QUERY_EXECUTE, "cognition"
    ),
    ResponsibilityBinding(
        "life_material", WorkType.CONTEXT_EMBEDDING_PROJECT, "context"
    ),
    ResponsibilityBinding(
        "subjective_memory", WorkType.CONTEXT_EMBEDDING_PROJECT, "context"
    ),
    ResponsibilityBinding(
        "artifact_object_deletion", WorkType.ARTIFACT_OBJECT_DELETE, "artifact-store"
    ),
    ResponsibilityBinding(
        "live_vision_observation", WorkType.LIVE_VISION_OBSERVE, "live-vision"
    ),
)

_RESPONSIBILITY_BY_SCOPE = {
    (binding.owner_kind, binding.work_type): binding
    for binding in RESPONSIBILITY_BINDINGS
}
if len(_RESPONSIBILITY_BY_SCOPE) != len(RESPONSIBILITY_BINDINGS):
    raise RuntimeError("WORK-RESPONSIBILITY-REGISTRY")


def responsibility_binding(
    owner_kind: str, work_type: WorkType
) -> ResponsibilityBinding:
    """Resolve the unique owner-bound reconciliation contract."""

    try:
        return _RESPONSIBILITY_BY_SCOPE[(owner_kind, work_type)]
    except KeyError:
        raise WorkViolation("WORK-RESPONSIBILITY-UNKNOWN") from None


@dataclass(frozen=True, slots=True)
class WorkId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value)

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class WorkAttemptId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value)

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class WorkOwner:
    kind: str
    reference: UUID

    def __post_init__(self) -> None:
        _require_token(self.kind)
        _require_uuid7(self.reference)


@dataclass(frozen=True, slots=True)
class WorkPayloadRef:
    kind: str
    reference: UUID

    def __post_init__(self) -> None:
        _require_token(self.kind)
        _require_uuid7(self.reference)


@dataclass(frozen=True, slots=True)
class WorkResultRef:
    kind: str
    reference: UUID

    def __post_init__(self) -> None:
        _require_token(self.kind)
        _require_uuid7(self.reference)


@dataclass(frozen=True, slots=True)
class WorkDraft:
    work_id: WorkId
    work_kind: WorkType
    owner: WorkOwner
    idempotency_key: IdempotencyKey
    payload_digest: Digest
    priority: int
    not_before: Instant
    deadline_at: Instant
    max_attempts: int
    trace_id: TraceId
    subject_id: SubjectId | None = None
    payload: WorkPayloadRef | None = None
    generation: int = 1
    predecessor_work_id: WorkId | None = None

    def __post_init__(self) -> None:
        if type(self.work_id) is not WorkId:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.work_kind) is not WorkType:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.owner) is not WorkOwner:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.idempotency_key) is not IdempotencyKey:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.payload_digest) is not Digest:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.priority) is not int or not 0 <= self.priority <= 100:
            raise WorkViolation("WORK-DECLARATION")
        if (
            type(self.not_before) is not Instant
            or type(self.deadline_at) is not Instant
        ):
            raise WorkViolation("WORK-DECLARATION")
        if self.deadline_at.value <= self.not_before.value:
            raise WorkViolation("WORK-DEADLINE")
        if (self.deadline_at.value - self.not_before.value).total_seconds() > 3600:
            raise WorkViolation("WORK-DEADLINE")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 100:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.trace_id) is not TraceId:
            raise WorkViolation("WORK-DECLARATION")
        if self.subject_id is not None and type(self.subject_id) is not SubjectId:
            raise WorkViolation("WORK-DECLARATION")
        if self.payload is not None and type(self.payload) is not WorkPayloadRef:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.generation) is not int or self.generation < 1:
            raise WorkViolation("WORK-DECLARATION")
        if self.predecessor_work_id is not None:
            if type(self.predecessor_work_id) is not WorkId or self.generation == 1:
                raise WorkViolation("WORK-DECLARATION")
        elif self.generation != 1:
            raise WorkViolation("WORK-DECLARATION")
        responsibility_binding(self.owner.kind, self.work_kind)


@dataclass(frozen=True, slots=True)
class WorkLease:
    work_id: WorkId
    attempt_id: WorkAttemptId
    owner: UUID
    expires_at: Instant
    token: int
    work_kind: WorkType
    work_owner: WorkOwner
    generation: int

    def __post_init__(self) -> None:
        if (
            type(self.work_id) is not WorkId
            or type(self.attempt_id) is not WorkAttemptId
            or type(self.work_kind) is not WorkType
            or type(self.work_owner) is not WorkOwner
            or type(self.generation) is not int
            or self.generation < 1
        ):
            raise WorkViolation("WORK-DECLARATION")
        _require_uuid7(self.owner)
        if type(self.expires_at) is not Instant:
            raise WorkViolation("WORK-DECLARATION")
        if type(self.token) is not int or self.token <= 0:
            raise WorkViolation("WORK-DECLARATION")


@dataclass(frozen=True, slots=True)
class WorkRecord:
    draft: WorkDraft
    status: WorkStatus
    attempt_count: int
    lease: WorkLease | None = None
    result: WorkResultRef | None = None
    last_error_code: str | None = None
    reconciliation_required: bool = False

    def __post_init__(self) -> None:
        if type(self.draft) is not WorkDraft or type(self.status) is not WorkStatus:
            raise WorkViolation("WORK-DECLARATION")
        if (
            type(self.attempt_count) is not int
            or not 0 <= self.attempt_count <= self.draft.max_attempts
        ):
            raise WorkViolation("WORK-DECLARATION")
        if type(self.reconciliation_required) is not bool:
            raise WorkViolation("WORK-DECLARATION")
        if (
            self.status
            in (
                WorkStatus.COMPLETED,
                WorkStatus.FAILED,
                WorkStatus.CANCELLED,
            )
            and self.reconciliation_required
        ):
            raise WorkViolation("WORK-STATE")
        if self.status is WorkStatus.LEASED:
            if type(self.lease) is not WorkLease:
                raise WorkViolation("WORK-STATE")
        elif self.lease is not None:
            raise WorkViolation("WORK-STATE")
        if self.result is not None and type(self.result) is not WorkResultRef:
            raise WorkViolation("WORK-DECLARATION")
        if self.status is WorkStatus.COMPLETED and self.result is None:
            raise WorkViolation("WORK-STATE")
        if self.status is not WorkStatus.COMPLETED and self.result is not None:
            raise WorkViolation("WORK-STATE")
        if (
            self.last_error_code is not None
            and re.fullmatch(r"[A-Z][A-Z0-9-]{0,127}", self.last_error_code) is None
        ):
            raise WorkViolation("WORK-DECLARATION")


class WorkViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if (
            type(code) is not str
            or re.fullmatch(r"(?:WORK|OUTBOX)-[A-Z0-9-]+", code) is None
        ):
            raise ValueError("work violation code is invalid")
        self.code = code
        super().__init__("durable work operation failed")

    def __str__(self) -> str:
        return f"{self.code}: durable work operation failed"


@runtime_checkable
class DurableWorkWriter(Protocol):
    async def enqueue(self, draft: WorkDraft) -> WorkRecord:
        """Create or idempotently return one work item in the active transaction."""
        ...

    async def successor(
        self,
        *,
        owner: WorkOwner,
        work_kind: WorkType,
        not_before: Instant,
        deadline_at: Instant,
        max_attempts: int,
    ) -> WorkRecord:
        """Create the next generation from the latest terminal owner work."""
        ...

    async def validate_lease(self, lease: WorkLease) -> None:
        """Fence business writes with the caller's live work custody."""
        ...

    async def release(
        self,
        lease: WorkLease,
        *,
        not_before: Instant,
        error_code: str | None = None,
    ) -> WorkRecord:
        """Release the caller's current lease inside the active transaction."""
        ...

    async def complete(
        self,
        lease: WorkLease,
        result: WorkResultRef,
    ) -> WorkRecord:
        """Complete the caller's current lease inside the active transaction."""
        ...

    async def fail(self, lease: WorkLease, *, error_code: str) -> WorkRecord:
        """Fail the caller's current lease inside the active transaction."""
        ...


@runtime_checkable
class DurableWorkPort(Protocol):
    async def claim(
        self,
        *,
        work_kind: WorkType,
        lease_owner: UUID,
        lease_seconds: int,
        limit: int = 1,
    ) -> tuple[WorkRecord, ...]: ...

    async def renew(self, lease: WorkLease, *, lease_seconds: int) -> WorkLease: ...

    async def release(
        self,
        lease: WorkLease,
        *,
        not_before: Instant,
        error_code: str | None = None,
    ) -> WorkRecord: ...

    async def complete(
        self,
        lease: WorkLease,
        result: WorkResultRef,
    ) -> WorkRecord: ...

    async def fail(self, lease: WorkLease, *, error_code: str) -> WorkRecord: ...

    async def cancel_ready(self, work_id: WorkId) -> WorkRecord: ...


def _require_uuid7(value: object) -> None:
    if type(value) is not UUID or value.version != 7:
        raise WorkViolation("WORK-DECLARATION")


__all__ = (
    "RESPONSIBILITY_BINDINGS",
    "DurableWorkPort",
    "DurableWorkWriter",
    "ResponsibilityBinding",
    "WorkAttemptId",
    "WorkDraft",
    "WorkId",
    "WorkLease",
    "WorkOwner",
    "WorkPayloadRef",
    "WorkRecord",
    "WorkResultRef",
    "WorkStatus",
    "WorkType",
    "WorkViolation",
    "responsibility_binding",
)
