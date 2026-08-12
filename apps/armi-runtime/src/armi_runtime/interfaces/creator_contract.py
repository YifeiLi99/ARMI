"""Strict Creator wire models and deterministic schema-only OpenAPI export."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from armi_kernel.contracts import CONTRACT_VERSION
from fastapi import FastAPI, Header, Query, Security
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPBearer
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

_REASON_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{2,127}", flags=re.ASCII)
_UUIDV7_PATTERN = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
_TRACE_PATTERN = r"[0-9a-f]{32}"
_INSTANT_PATTERN = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:[0-5]\d\.\d{6}Z"
_ERROR_CODE_PATTERN = r"[A-Z][A-Z0-9_]{2,127}"
_SESSION_TOKEN_PATTERN = r"browser-v1\.[A-Za-z0-9_-]{43}"
_SCENE_KEY_PATTERN = r"[a-z0-9][a-z0-9._-]{0,63}"
_CURSOR_PATTERN = r"v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
_EVENT_ID_PATTERN = r"sse-v1\.[A-Za-z0-9_-]{22}\.[1-9][0-9]*"
_IDEMPOTENCY_KEY_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
type ReasonCode = Annotated[str, Field(pattern=_ERROR_CODE_PATTERN)]
type ErrorCategoryValue = Literal[
    "input",
    "auth",
    "scope",
    "state",
    "conflict",
    "idempotency",
    "policy",
    "capability",
    "dependency",
    "effect",
    "integrity",
    "admin",
    "internal",
]


class _StrictWireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RuntimeState(StrEnum):
    UNBORN = "unborn"
    STARTING = "starting"
    RECOVERING = "recovering"
    READY = "ready"
    DEGRADED = "degraded"
    DRAINING = "draining"
    STOPPED = "stopped"
    BLOCKED = "blocked"


class Readiness(StrEnum):
    READY = "ready"
    NOT_READY = "not_ready"


class LiveResponse(_StrictWireModel):
    status: Literal["alive"]


class ReadyResponse(_StrictWireModel):
    status: Readiness


class _BrowserSessionMetadataResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    environment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    creator_party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    default_scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]
    issued_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    expires_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class BrowserSessionResponse(_BrowserSessionMetadataResponse):
    browser_session_token: Annotated[str, Field(pattern=_SESSION_TOKEN_PATTERN)]


class BrowserSessionCurrentResponse(_BrowserSessionMetadataResponse):
    pass


type TimelineStatus = Literal[
    "accepted",
    "applied",
    "waiting",
    "rejected",
    "unavailable",
    "failed",
    "unknown",
    "completed",
]


class SceneTimelineItemResponse(_StrictWireModel):
    timeline_item_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    source_kind: Annotated[
        str,
        Field(pattern=r"[a-z][a-z0-9._-]{0,63}"),
    ]
    source_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: TimelineStatus
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    operation_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    effect_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    message: Annotated[str, Field(min_length=1, max_length=65536)] | None = None


class SceneTimelinePageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["scene-timeline.v5"]
    scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]
    items: Annotated[list[SceneTimelineItemResponse], Field(max_length=100)]
    next_cursor: (
        Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None
    ) = None


class OtherHumanPartyRecordResponse(_StrictWireModel):
    party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    party_key: Annotated[str, Field(min_length=1, max_length=128)]
    display_label: Annotated[str, Field(min_length=1, max_length=256)]
    scene_count: Annotated[int, Field(ge=0)]
    record_count: Annotated[int, Field(ge=0)]
    last_record_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None = None


class OtherHumanPartyRecordPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["other-human-record.v1"]
    items: Annotated[list[OtherHumanPartyRecordResponse], Field(max_length=100)]
    next_cursor: (
        Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None
    ) = None


class OtherHumanSceneRecordResponse(_StrictWireModel):
    scene_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]
    status: Literal["open", "closed"]
    record_count: Annotated[int, Field(ge=0)]
    last_record_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None = None


class OtherHumanSceneRecordPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["other-human-record.v1"]
    party: OtherHumanPartyRecordResponse
    items: Annotated[list[OtherHumanSceneRecordResponse], Field(max_length=100)]
    next_cursor: (
        Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None
    ) = None


class OtherHumanTimelineRecordResponse(_StrictWireModel):
    timeline_item_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    source_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    direction: Literal["received", "sent"]
    status: Literal["accepted", "completed", "failed", "unknown"]
    text: Annotated[str, Field(min_length=1, max_length=65536)]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class OtherHumanTimelineRecordPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["other-human-record.v1"]
    party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    scene_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    items: Annotated[list[OtherHumanTimelineRecordResponse], Field(max_length=100)]
    next_cursor: (
        Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None
    ) = None


class CreatorSceneCreateRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]

    @model_validator(mode="after")
    def reject_reserved_default(self) -> CreatorSceneCreateRequest:
        if self.scene_key == "default":
            raise ValueError("CON-SCENE-KEY: default is reserved")
        return self


class CreatorSceneResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-scenes.v1"]
    scene_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)]
    status: Literal["open", "closed"]
    opened_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    closed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None = None
    recent_context_boundary: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = (
        None
    )
    is_default: bool


class CreatorSceneCollectionResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-scenes.v1"]
    scenes: Annotated[list[CreatorSceneResponse], Field(min_length=1)]


type ActivityStatusValue = Literal[
    "considering",
    "ready",
    "in_progress",
    "waiting",
    "paused",
    "resuming",
    "completed",
    "abandoned",
    "failed",
]
type ActivityTransitionValue = Literal[
    "created",
    "engage",
    "progress",
    "wait",
    "pause",
    "resume",
    "complete",
    "abandon",
    "system_fail",
]
type ActivityTimelineKind = (
    ActivityTransitionValue | Literal["no_action", "defer", "need_information"]
)


class CreatorActivityItemResponse(_StrictWireModel):
    activity_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    activity_kind: Literal["self_directed"]
    status: ActivityStatusValue
    goal: Annotated[str, Field(min_length=1, max_length=8192)]
    progress_summary: Annotated[str, Field(min_length=1, max_length=8192)] | None
    waiting_kind: (
        Literal["time", "creator_input", "external_evidence", "scheduled_review"] | None
    )
    waiting_summary: Annotated[str, Field(min_length=1, max_length=8192)] | None
    resume_not_before: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None
    terminal_reason: Annotated[str, Field(min_length=1, max_length=8192)] | None
    revision_no: Annotated[int, Field(ge=1)]
    head_version: Annotated[int, Field(ge=1)]
    transition_kind: ActivityTransitionValue
    is_focused: bool
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    updated_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorActivityPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-activity.v1"]
    items: Annotated[list[CreatorActivityItemResponse], Field(max_length=100)]
    truncated: bool


class CreatorActivityTimelineItemResponse(_StrictWireModel):
    event_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    event_kind: ActivityTimelineKind
    resulting_status: ActivityStatusValue | None
    summary: Annotated[str, Field(min_length=1, max_length=8192)] | None
    review_not_before: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorActivityTimelineResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-activity.v1"]
    activity_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    items: Annotated[list[CreatorActivityTimelineItemResponse], Field(max_length=100)]
    truncated: bool


type RelationshipPartyRoleValue = Literal["subject", "other"]
type RelationshipBoundaryKindValue = Literal[
    "contact", "address", "privacy", "disclosure", "exit"
]
type RelationshipBoundaryActionValue = Literal["refuse", "restrict", "end_contact"]
type RelationshipCommitmentStatusValue = Literal[
    "active", "fulfilled", "withdrawn", "forgotten", "violated"
]
type RelationshipCommitmentEventKindValue = Literal[
    "established",
    "modified",
    "fulfilled",
    "withdrawn",
    "forgotten",
    "violated",
    "conflict_noted",
]


class CreatorRelationshipFactResponse(_StrictWireModel):
    fact_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    kind: Literal["shared_experience", "party_expression"]
    summary: Annotated[str, Field(min_length=1, max_length=512)]


class CreatorRelationshipBoundaryResponse(_StrictWireModel):
    party_role: RelationshipPartyRoleValue
    kind: RelationshipBoundaryKindValue
    action: RelationshipBoundaryActionValue
    summary: Annotated[str, Field(min_length=1, max_length=512)]


class CreatorRelationshipCommitmentResponse(_StrictWireModel):
    commitment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    party_role: RelationshipPartyRoleValue
    scope: Annotated[str, Field(min_length=1, max_length=512)]
    content: Annotated[str, Field(min_length=1, max_length=1024)]
    status: RelationshipCommitmentStatusValue
    last_event_kind: RelationshipCommitmentEventKindValue
    last_event_summary: Annotated[str, Field(min_length=1, max_length=512)]


class CreatorRelationshipIssueResponse(_StrictWireModel):
    issue_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    kind: Literal["contradictory_commitments", "commitment_violation"]
    commitment_ids: Annotated[list[str], Field(min_length=1, max_length=2)]
    summary: Annotated[str, Field(min_length=1, max_length=512)]
    status: Literal["open"]


class CreatorRelationshipCommitmentEventResponse(_StrictWireModel):
    commitment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    kind: RelationshipCommitmentEventKindValue
    summary: Annotated[str, Field(min_length=1, max_length=512)]
    related_commitment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None


class CreatorRelationshipIssueResolutionResponse(_StrictWireModel):
    issue_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: Literal["resolved"]
    resolution_summary: Annotated[str, Field(min_length=1, max_length=512)]


class CreatorRelationshipRevisionResponse(_StrictWireModel):
    relationship_revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    revision_no: Annotated[int, Field(ge=1)]
    facts: Annotated[
        list[CreatorRelationshipFactResponse], Field(min_length=1, max_length=64)
    ]
    interpretation: Annotated[str, Field(min_length=1, max_length=1024)]
    boundaries: Annotated[
        list[CreatorRelationshipBoundaryResponse], Field(max_length=16)
    ]
    commitments: Annotated[
        list[CreatorRelationshipCommitmentResponse], Field(max_length=16)
    ]
    open_issues: Annotated[list[CreatorRelationshipIssueResponse], Field(max_length=32)]
    commitment_event: CreatorRelationshipCommitmentEventResponse | None
    issue_resolution: CreatorRelationshipIssueResolutionResponse | None
    status: Literal["active", "ended"]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorRelationshipItemResponse(_StrictWireModel):
    relationship_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    current_revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    head_version: Annotated[int, Field(ge=1)]
    current: CreatorRelationshipRevisionResponse
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorRelationshipCurrentResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-relationship.v2"]
    relationship: CreatorRelationshipItemResponse | None


class CreatorRelationshipTimelineResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-relationship.v2"]
    relationship_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    items: Annotated[list[CreatorRelationshipRevisionResponse], Field(max_length=100)]
    truncated: bool


class CreatorRelationshipBoundaryRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    kind: RelationshipBoundaryKindValue
    action: RelationshipBoundaryActionValue
    summary: Annotated[str, Field(min_length=1, max_length=512)]

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("CON-RELATIONSHIP-BOUNDARY: summary is invalid")
        return value

    @model_validator(mode="after")
    def validate_boundary(self) -> CreatorRelationshipBoundaryRequest:
        if (self.action == "end_contact") != (self.kind == "exit"):
            raise ValueError("CON-RELATIONSHIP-BOUNDARY: boundary is inconsistent")
        return self


type LifeRecordKindValue = Literal[
    "activity",
    "conversation",
    "material",
    "memory",
    "relationship",
    "self_change",
]
type MemoryAccessibilityValue = Literal["available", "faded", "forgotten"]
type MemoryRevisionKindValue = Literal[
    "formed",
    "recalled",
    "faded",
    "forgotten",
    "reinterpreted",
]


class LifeRecordItemResponse(_StrictWireModel):
    record_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    record_kind: LifeRecordKindValue
    summary: Annotated[str, Field(min_length=1, max_length=16384)]
    source_kind: Annotated[str, Field(min_length=1, max_length=128)]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    naturally_recallable: bool | None
    retrieval_kind: Literal["exact_query", "creator_view"]


class LifeRecordPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["life-record-query.v2"]
    retrieval_kind: Literal["exact_query", "creator_view"]
    items: Annotated[list[LifeRecordItemResponse], Field(max_length=100)]
    next_cursor: Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None


class CreatorLifeMaterialResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-life-material.v1"]
    material_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    material_kind: Literal["diary", "work", "collection", "draft"]
    revision_no: Annotated[int, Field(ge=1)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    body: Annotated[str, Field(min_length=1, max_length=65536)]
    metadata: dict[
        Annotated[str, Field(pattern=r"[a-z][a-z0-9._-]{0,63}")],
        Annotated[str, Field(max_length=512)],
    ] = Field(max_length=32)
    material_status: Literal["active", "archived"]
    privacy_status: Literal["creator_visible"]
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    updated_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorMemoryItemResponse(_StrictWireModel):
    memory_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    summary: Annotated[str, Field(min_length=1, max_length=4096)]
    uncertainty: Annotated[str, Field(min_length=1, max_length=4096)] | None
    source_kind: Annotated[str, Field(min_length=1, max_length=64)]
    source_fact_class: Annotated[str, Field(min_length=1, max_length=64)]
    accessibility: MemoryAccessibilityValue
    revision_kind: MemoryRevisionKindValue
    revision_no: Annotated[int, Field(ge=1)]
    head_version: Annotated[int, Field(ge=1)]
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    updated_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorMemoryPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-memory.v1"]
    retrieval_kind: Literal["creator_view"]
    items: Annotated[list[CreatorMemoryItemResponse], Field(max_length=100)]
    next_cursor: Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None


class CreatorMemoryTimelineItemResponse(_StrictWireModel):
    revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    revision_no: Annotated[int, Field(ge=1)]
    revision_kind: MemoryRevisionKindValue
    accessibility: MemoryAccessibilityValue
    summary: Annotated[str, Field(min_length=1, max_length=4096)]
    uncertainty: Annotated[str, Field(min_length=1, max_length=4096)] | None
    source_kind: Annotated[str, Field(min_length=1, max_length=64)]
    source_fact_class: Annotated[str, Field(min_length=1, max_length=64)]
    relation_kind: Literal["supports", "contradicts", "reinterprets"] | None
    related_memory_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorMemoryTimelineResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-memory.v1"]
    retrieval_kind: Literal["creator_view"]
    memory_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    items: Annotated[list[CreatorMemoryTimelineItemResponse], Field(max_length=100)]
    next_cursor: Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None


type MaintenancePhaseValue = Literal[
    "preparing",
    "memory_maintenance",
    "self_check",
    "life_quiet",
    "resume_check",
    "completed",
]
type MaintenanceResultValue = Literal[
    "running",
    "completed",
    "interrupted",
    "failed",
]
type MaintenanceTransitionValue = Literal[
    "started",
    "advanced",
    "completed",
    "interrupted",
    "system_failed",
]
type MaintenanceWorkOutcomeValue = Literal[
    "memory_changed",
    "memory_unchanged",
    "issue_found",
    "no_issue",
]


class CreatorMaintenanceSessionResponse(_StrictWireModel):
    maintenance_session_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    trigger_kind: Literal["subject_choice", "system_deadline"]
    phase: MaintenancePhaseValue
    result_status: MaintenanceResultValue
    revision_no: Annotated[int, Field(ge=1)]
    head_version: Annotated[int, Field(ge=1)]
    wake_requested: bool
    started_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    updated_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    finished_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None


class CreatorMaintenanceStatusResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-maintenance.v2"]
    session: CreatorMaintenanceSessionResponse | None
    waiting_input_count: Annotated[int, Field(ge=0)]


class CreatorMaintenanceTimelineItemResponse(_StrictWireModel):
    revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    revision_no: Annotated[int, Field(ge=1)]
    phase: MaintenancePhaseValue
    result_status: MaintenanceResultValue
    transition_kind: MaintenanceTransitionValue
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    work_outcome: MaintenanceWorkOutcomeValue | None
    problem_summary: Annotated[str, Field(min_length=1, max_length=512)] | None


class CreatorMaintenanceTimelineResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-maintenance.v2"]
    maintenance_session_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    items: Annotated[
        list[CreatorMaintenanceTimelineItemResponse], Field(max_length=100)
    ]
    truncated: bool


class CreatorProjectionEventResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    event_id: Annotated[str, Field(pattern=_EVENT_ID_PATTERN, max_length=128)]
    event_kind: Literal[
        "activity.invalidated",
        "memory.invalidated",
        "maintenance.invalidated",
        "material.invalidated",
        "relationship.invalidated",
        "scene.timeline.invalidated",
        "capability.request.invalidated",
        "operation.invalidated",
        "other_human.record.invalidated",
        "effect.invalidated",
        "subject.summary.invalidated",
        "data.rights.invalidated",
    ]
    resource_kind: Literal[
        "activity",
        "memory",
        "maintenance",
        "material",
        "relationship",
        "scene_timeline",
        "capability_request",
        "operation",
        "other_human_record",
        "effect",
        "subject_summary",
        "data_rights",
    ]
    resource_ref: Annotated[str, Field(min_length=1, max_length=64)]
    projection_version: Literal[
        "creator-activity.v1",
        "creator-memory.v1",
        "creator-maintenance.v2",
        "life-record-query.v2",
        "creator-relationship.v2",
        "scene-timeline.v5",
        "capability-request.v4",
        "creator-operation.v1",
        "other-human-record.v1",
        "creator-effect.v2",
        "subject-summary.v1",
        "data-rights-order.v2",
    ]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class CreatorInputRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    message: Annotated[str, Field(min_length=1, max_length=262144)]


class CreatorCodexTaskRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    objective: Annotated[str, Field(min_length=1, max_length=16384)]
    model_id: Literal["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"] = "gpt-5.6-sol"
    reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    web_search: bool = False


class RuntimeStatusResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    environment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    runtime_state: RuntimeState
    readiness: Readiness
    reason_codes: Annotated[list[ReasonCode], Field(max_length=32)]
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class ErrorDescriptorResponse(_StrictWireModel):
    category: ErrorCategoryValue
    code: Annotated[str, Field(pattern=_ERROR_CODE_PATTERN)]
    details: dict[str, JsonValue] | None = None
    error_instance_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None


class _CommonOutcomeResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    trace_id: Annotated[str, Field(pattern=_TRACE_PATTERN)]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    message: Annotated[str, Field(min_length=1, max_length=4096)]


class CreatorInputAcceptanceDetails(_StrictWireModel):
    interaction_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    evidence_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    opportunity_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    operation_url: Annotated[
        str,
        Field(pattern=rf"^/v1/operations/{_UUIDV7_PATTERN}$"),
    ]


class AcceptedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["accepted"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    custodian: Literal["runtime"]
    details: CreatorInputAcceptanceDetails


class WaitingOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["waiting"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    waiting_for: Literal[
        "context_preparation",
        "model_attempt",
        "model_response",
        "candidate_validation",
        "subject_commit",
        "response_admission",
        "effect_registration",
        "effect_dispatch",
        "capability_decision",
        "codex_dispatch",
        "codex_verification",
        "codex_result_acceptance",
        "future_opportunity",
        "new_evidence",
    ]
    resume_condition: Literal[
        "context_prepared",
        "model_step_available",
        "model_returned",
        "candidate_validation_available",
        "candidate_validated",
        "subject_commit_available",
        "opportunity_available",
        "creator_evidence_accepted",
        "response_admitted",
        "effect_registered",
        "effect_settled",
        "codex_grant_resolved",
        "codex_dispatched",
        "codex_verified",
        "codex_result_accepted",
    ]


class AppliedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["applied"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    state_version: Annotated[int, Field(ge=0)]


class CompletedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["completed"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]


class FailedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["failed"]
    error: ErrorDescriptorResponse


class RejectedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["rejected"]
    error: ErrorDescriptorResponse
    details: dict[str, JsonValue] | None = None


class UnknownOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["unknown"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    custodian: Literal["runtime"]
    verification_action: Literal["verify_creator_inbox", "verify_codex_result"]


class UnavailableOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["unavailable"]
    error: ErrorDescriptorResponse
    details: dict[str, JsonValue] | None = None
    recovery_hint: Annotated[str, Field(min_length=1, max_length=4096)] | None = None


class CreatorOperationDetails(_StrictWireModel):
    projection_version: Literal["creator-operation.v1"]
    root_operation_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    completion_kind: Literal[
        "cognition",
        "subject_change",
        "formal_decline",
        "formal_no_action",
        "no_change",
        "response_effect",
        "codex_effect",
    ]
    delivery_state: (
        Literal[
            "not_started",
            "registered",
            "dispatching",
            "completed",
            "failed",
            "unknown",
            "cancelled",
        ]
        | None
    ) = None
    effect_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None


class OperationAcceptedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["accepted"]
    result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    custodian: Literal["runtime"]
    details: CreatorOperationDetails


class OperationAppliedOutcomeResponse(AppliedOutcomeResponse):
    details: CreatorOperationDetails


class OperationCompletedOutcomeResponse(CompletedOutcomeResponse):
    details: CreatorOperationDetails


class OperationWaitingOutcomeResponse(WaitingOutcomeResponse):
    details: CreatorOperationDetails


class OperationRejectedOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["rejected"]
    error: ErrorDescriptorResponse
    details: CreatorOperationDetails


class OperationUnavailableOutcomeResponse(_CommonOutcomeResponse):
    status: Literal["unavailable"]
    error: ErrorDescriptorResponse
    details: CreatorOperationDetails
    recovery_hint: Annotated[str, Field(min_length=1, max_length=4096)] | None = None


class OperationFailedOutcomeResponse(FailedOutcomeResponse):
    details: CreatorOperationDetails


class OperationUnknownOutcomeResponse(UnknownOutcomeResponse):
    details: CreatorOperationDetails


type OperationOutcomeResponse = Annotated[
    OperationAcceptedOutcomeResponse
    | OperationAppliedOutcomeResponse
    | OperationCompletedOutcomeResponse
    | OperationWaitingOutcomeResponse
    | OperationRejectedOutcomeResponse
    | OperationUnavailableOutcomeResponse
    | OperationFailedOutcomeResponse
    | OperationUnknownOutcomeResponse,
    Field(discriminator="status"),
]


class SubjectComponentSummaryResponse(_StrictWireModel):
    kind: Literal["self", "mind", "life_mode"]
    version: Annotated[int, Field(ge=1)]
    schema_version: Literal["armi.self.v1", "armi.mind.v1", "armi.life-mode.v1"]
    content_visibility: Literal["private"]


class SubjectSummaryResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["subject-summary.v1"]
    subject_version: Annotated[int, Field(ge=0)]
    components: Annotated[
        list[SubjectComponentSummaryResponse], Field(min_length=3, max_length=3)
    ]
    latest_commit_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class EffectResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-effect.v2"]
    effect_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    root_operation_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    capability_request_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    grant_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    capability_kind: Literal["creator.scene.reply", "codex.delegated-work"]
    effect_kind: Literal["creator_response", "codex_delegation"]
    status: Literal[
        "registered", "dispatching", "completed", "failed", "unknown", "cancelled"
    ]
    verification_status: Literal["not_started", "pending", "verified", "inconclusive"]
    registered_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    cancelled_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None = None
    attempt_count: Annotated[int, Field(ge=0, le=2)]
    last_observation_kind: (
        Literal[
            "receipt",
            "query",
            "rejection",
            "ambiguous",
            "runner_verified",
            "runner_failed",
            "runner_unknown",
            "runner_cancelled",
        ]
        | None
    ) = None
    last_observation_reliability: Literal["reliable", "inconclusive"] | None = None
    verification_action: (
        Literal["verify_creator_inbox", "verify_codex_result"] | None
    ) = None
    settled_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None = None
    response_text: Annotated[str, Field(min_length=1, max_length=65536)] | None = None
    model_id: Literal["gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"] | None = None
    sdk_identity: Literal["openai-codex==0.144.4"] | None = None
    source_tree_digest: Annotated[str, Field(pattern=r"sha256:[0-9a-f]{64}")] | None = (
        None
    )
    result_tree_digest: Annotated[str, Field(pattern=r"sha256:[0-9a-f]{64}")] | None = (
        None
    )
    patch_digest: Annotated[str, Field(pattern=r"sha256:[0-9a-f]{64}")] | None = None
    changed_path_count: Annotated[int, Field(ge=0, le=500)] | None = None
    validation_status: Literal["passed", "failed", "not_run"] | None = None
    cleanup_status: Literal["succeeded", "failed"] | None = None
    result_acceptance_status: Literal["pending", "accepted"] | None = None


class _EffectiveGrantResponseBase(_StrictWireModel):
    grant_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: Literal["active", "revoked", "expired"]
    valid_from: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    valid_until: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    ended_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None = None


class CreatorReplyEffectiveGrantResponse(_EffectiveGrantResponseBase):
    scope_kind: Literal["creator_scene_reply"]
    max_uses: Annotated[int, Field(ge=1, le=16)]
    consumed_uses: Annotated[int, Field(ge=0, le=16)]
    remaining_uses: Annotated[int, Field(ge=0, le=16)]
    max_payload_bytes: Annotated[int, Field(ge=1, le=65536)]


class CodexEffectiveGrantResponse(_EffectiveGrantResponseBase):
    scope_kind: Literal["codex_delegated_work"]
    max_uses: Literal[1]
    consumed_uses: Annotated[int, Field(ge=0, le=1)]
    remaining_uses: Annotated[int, Field(ge=0, le=1)]
    workspace_scope: Literal["isolated_ephemeral"]
    artifact_scope: Literal["explicit_only"]
    network_access: Literal[False]


type EffectiveGrantResponse = (
    CreatorReplyEffectiveGrantResponse | CodexEffectiveGrantResponse
)


class CapabilityRequestItemResponse(_StrictWireModel):
    capability_request_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    capability_kind: Literal["creator.scene.reply", "codex.delegated-work"]
    operation: Literal["send", "execute"]
    subject_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    scene_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    purpose: Literal["respond_to_creator", "delegate_codex_work"]
    audience_scope: Literal["creator"] | None = None
    data_scope: Literal["creator_visible_response"] | None = None
    workspace_scope: Literal["isolated_ephemeral"] | None = None
    artifact_scope: Literal["explicit_only"] | None = None
    network_access: Literal[False] | None = None
    valid_for_seconds: Annotated[int, Field(ge=60, le=604800)]
    max_uses: Annotated[int, Field(ge=1, le=16)]
    max_payload_bytes: Annotated[int, Field(ge=1, le=65536)] | None = None
    status: Literal["pending", "granted", "limited", "denied", "revoked", "expired"]
    capability_availability: Literal["available", "unavailable"]
    request_version: Annotated[int, Field(ge=1)]
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    status_changed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    resolution_reason_code: (
        Annotated[str, Field(pattern=r"[A-Z][A-Z0-9-]{2,127}")] | None
    ) = None
    effective_grant: EffectiveGrantResponse | None = None


class CapabilityRequestPageResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["capability-request.v4"]
    items: Annotated[list[CapabilityRequestItemResponse], Field(max_length=100)]
    next_cursor: (
        Annotated[str, Field(pattern=_CURSOR_PATTERN, max_length=2048)] | None
    ) = None


class CapabilityRequestDecisionRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    decision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    expected_request_version: Annotated[int, Field(ge=1)]
    decision: Literal["grant", "limit", "deny", "revoke"]
    valid_for_seconds: Annotated[int, Field(ge=60, le=604800)] | None = None
    max_uses: Annotated[int, Field(ge=1, le=16)] | None = None
    max_payload_bytes: Annotated[int, Field(ge=1, le=65536)] | None = None
    reason_code: (
        Annotated[
            str,
            Field(pattern=r"(?:CON|CAPABILITY|POLICY|CONFLICT|SCOPE)-[A-Z0-9-]{1,96}"),
        ]
        | None
    ) = None

    @field_validator("decision_id")
    @classmethod
    def validate_decision_id(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("CON-CAPABILITY-ID: decision identity must be UUIDv7")
        return value

    @model_validator(mode="after")
    def validate_decision_scope(self) -> CapabilityRequestDecisionRequest:
        limits = (
            self.valid_for_seconds,
            self.max_uses,
            self.max_payload_bytes,
        )
        if self.decision == "limit" and all(value is None for value in limits):
            raise ValueError("CON-CAPABILITY-LIMIT: limit must narrow scope")
        if self.decision != "limit" and any(value is not None for value in limits):
            raise ValueError("CON-CAPABILITY-LIMIT: only limit accepts scope fields")
        return self


class CreatorPromptRevisionRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    expected_revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None
    content: Annotated[str, Field(min_length=1, max_length=65_536)]

    @field_validator("expected_revision_id")
    @classmethod
    def validate_expected_revision_id(cls, value: str | None) -> str | None:
        if value is not None:
            parsed = UUID(value)
            if parsed.version != 7 or str(parsed) != value:
                raise ValueError("CON-PROMPT-ID: revision identity must be UUIDv7")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeError:
            raise ValueError("CON-PROMPT-CONTENT: content must be UTF-8") from None
        if not value.strip() or "\x00" in value or len(encoded) > 65_536:
            raise ValueError("CON-PROMPT-CONTENT: content is invalid")
        return value


class CreatorPromptDeactivateRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    expected_revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]

    @field_validator("expected_revision_id")
    @classmethod
    def validate_expected_revision_id(cls, value: str) -> str:
        parsed = UUID(value)
        if parsed.version != 7 or str(parsed) != value:
            raise ValueError("CON-PROMPT-ID: revision identity must be UUIDv7")
        return value


class CreatorPromptResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-prompt.v1"]
    prompt_document_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    prompt_kind: Literal["creator_guidance"]
    status: Literal["active", "inactive"]
    current_revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None
    revision_no: Annotated[int, Field(ge=1)] | None
    previous_revision_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None
    revision_kind: Literal["created", "revised", "deactivated"] | None
    content: Annotated[str, Field(min_length=1, max_length=65_536)] | None
    activated_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None


class CreatorExportRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    directory_name: Annotated[str, Field(pattern=r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")]

    @field_validator("directory_name")
    @classmethod
    def validate_directory_name(cls, value: str) -> str:
        if value in {".", ".."}:
            raise ValueError("CON-EXPORT-DIRECTORY: directory name is invalid")
        return value


class CreatorExportResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-export.v1"]
    export_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: Literal["running", "completed", "partial", "failed"]
    directory_name: Annotated[str, Field(min_length=1, max_length=64)]
    destination_path: Annotated[str, Field(min_length=1, max_length=4096)]
    table_count: Annotated[int, Field(ge=0)]
    row_count: Annotated[int, Field(ge=0)]
    artifact_count: Annotated[int, Field(ge=0)]
    missing_artifacts: Annotated[
        list[Annotated[str, Field(pattern=r"sha256:[0-9a-f]{64}")]],
        Field(max_length=100_000),
    ]
    error_code: Annotated[str, Field(min_length=1, max_length=128)] | None
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    completed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None
    newly_created: bool


class DataRightsOrderRequest(_StrictWireModel):
    contract_version: Literal["1.0"]
    order_kind: Literal["stop_contact", "stop_use", "delete_related"]


class DataRightsOrderResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["data-rights-order.v1"]
    order_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    requester_party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    requester_kind: Literal["creator", "other_human"]
    order_kind: Literal["stop_contact", "stop_use", "delete_related"]
    scope_kind: Literal["party_contact", "party_local_data"]
    scope_party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: Literal["effective"]
    execution_status: Literal[
        "not_required", "pending", "executing", "completed", "partial"
    ]
    request_digest: Annotated[str, Field(pattern=r"sha256:[0-9a-f]{64}")]
    effective_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    completed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None
    newly_created: bool


class DataRightsDeletionItemResponse(_StrictWireModel):
    item_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    target_kind: Literal[
        "interaction",
        "evidence",
        "experience",
        "memory",
        "relationship",
        "scene",
        "artifact",
        "effect",
    ]
    required_action: Literal["delete", "tombstone", "retain"]
    result_status: Literal["pending", "completed", "partial", "too_late", "unknown"]
    remaining_location: (
        Literal["shared_local_reference", "objective_history", "local_artifact_store"]
        | None
    )
    created_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    completed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None


class DataRightsTimelineItemResponse(_StrictWireModel):
    event_kind: Literal["order_effective", "item_status"]
    occurred_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    item_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None
    status: Literal[
        "effective", "pending", "completed", "partial", "too_late", "unknown"
    ]


class DataRightsOrderDetailResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["data-rights-order.v2"]
    order_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    requester_party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    requester_kind: Literal["creator", "other_human"]
    order_kind: Literal["stop_contact", "stop_use", "delete_related"]
    scope_kind: Literal["party_contact", "party_local_data"]
    scope_party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: Literal["effective"]
    execution_status: Literal[
        "not_required", "pending", "executing", "completed", "partial"
    ]
    request_digest: Annotated[str, Field(pattern=r"sha256:[0-9a-f]{64}")]
    effective_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    completed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None
    newly_created: bool
    items: list[DataRightsDeletionItemResponse]
    timeline: Annotated[list[DataRightsTimelineItemResponse], Field(min_length=1)]
    remaining_locations: Annotated[
        list[
            Literal[
                "shared_local_reference", "objective_history", "local_artifact_store"
            ]
        ],
        Field(max_length=3),
    ]


class DataRightsOrderCollectionResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["data-rights-order.v2"]
    orders: list[DataRightsOrderDetailResponse]


def build_creator_openapi() -> dict[str, object]:
    """Build the schema locally without exporting or starting an ASGI app."""

    app = FastAPI(
        title="ARMI Creator Interface",
        version=CONTRACT_VERSION,
        openapi_version="3.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    bearer = HTTPBearer(scheme_name="browserSessionBearer", auto_error=False)

    @app.get(
        "/health/live",
        operation_id="getHealthLive",
        response_model=LiveResponse,
    )
    async def health_live() -> LiveResponse:
        raise NotImplementedError

    @app.get(
        "/health/ready",
        operation_id="getHealthReady",
        response_model=ReadyResponse,
        responses={503: {"model": ReadyResponse}},
    )
    async def health_ready() -> ReadyResponse:
        raise NotImplementedError

    @app.post(
        "/v1/browser-sessions",
        operation_id="createBrowserSession",
        response_model=BrowserSessionResponse,
        responses={
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
    )
    async def create_browser_session() -> BrowserSessionResponse:
        raise NotImplementedError

    @app.get(
        "/v1/browser-sessions/current",
        operation_id="getCurrentBrowserSession",
        response_model=BrowserSessionCurrentResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def current_browser_session() -> BrowserSessionCurrentResponse:
        raise NotImplementedError

    @app.get(
        "/v1/runtime/status",
        operation_id="getRuntimeStatus",
        response_model=RuntimeStatusResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def runtime_status() -> RuntimeStatusResponse:
        raise NotImplementedError

    @app.get(
        "/v1/subject/summary",
        operation_id="getSubjectSummary",
        response_model=SubjectSummaryResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def subject_summary() -> SubjectSummaryResponse:
        raise NotImplementedError

    @app.get(
        "/v1/prompts/creator-guidance",
        operation_id="getCreatorPrompt",
        response_model=CreatorPromptResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_prompt() -> CreatorPromptResponse:
        raise NotImplementedError

    @app.put(
        "/v1/prompts/creator-guidance",
        operation_id="reviseCreatorPrompt",
        response_model=CreatorPromptResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def revise_creator_prompt(
        _request: CreatorPromptRevisionRequest,
    ) -> CreatorPromptResponse:
        del _request
        raise NotImplementedError

    @app.post(
        "/v1/prompts/creator-guidance/deactivation",
        operation_id="deactivateCreatorPrompt",
        response_model=CreatorPromptResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def deactivate_creator_prompt(
        _request: CreatorPromptDeactivateRequest,
    ) -> CreatorPromptResponse:
        del _request
        raise NotImplementedError

    @app.post(
        "/v1/exports",
        operation_id="createCreatorExport",
        status_code=201,
        response_model=CreatorExportResponse,
        responses={
            200: {"model": CreatorExportResponse},
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def create_creator_export(
        _request: CreatorExportRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> CreatorExportResponse:
        del _request, idempotency_key
        raise NotImplementedError

    @app.get(
        "/v1/exports/{export_id}",
        operation_id="getCreatorExport",
        response_model=CreatorExportResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_export(export_id: str) -> CreatorExportResponse:
        del export_id
        raise NotImplementedError

    @app.post(
        "/v1/data-rights/orders",
        operation_id="createDataRightsOrder",
        status_code=201,
        response_model=DataRightsOrderResponse,
        responses={
            200: {"model": DataRightsOrderResponse},
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def create_data_rights_order(
        _request: DataRightsOrderRequest,
        idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    ) -> DataRightsOrderResponse:
        del _request, idempotency_key
        raise NotImplementedError

    @app.get(
        "/v1/data-rights/orders",
        operation_id="listDataRightsOrders",
        response_model=DataRightsOrderCollectionResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_data_rights_orders() -> DataRightsOrderCollectionResponse:
        raise NotImplementedError

    del list_data_rights_orders

    @app.get(
        "/v1/data-rights/orders/{order_id}",
        operation_id="getDataRightsOrder",
        response_model=DataRightsOrderDetailResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_data_rights_order(order_id: str) -> DataRightsOrderDetailResponse:
        del order_id
        raise NotImplementedError

    @app.get(
        "/v1/capability-requests",
        operation_id="listCapabilityRequests",
        response_model=CapabilityRequestPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_capability_requests(
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[
            str | None,
            Query(pattern=_CURSOR_PATTERN, max_length=2048),
        ] = None,
    ) -> CapabilityRequestPageResponse:
        del limit, cursor
        raise NotImplementedError

    @app.post(
        "/v1/capability-requests/{capability_request_id}/decision",
        operation_id="decideCapabilityRequest",
        response_model=AppliedOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def decide_capability_request(
        capability_request_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
        _request: CapabilityRequestDecisionRequest,
    ) -> AppliedOutcomeResponse:
        del capability_request_id, _request
        raise NotImplementedError

    @app.get(
        "/v1/activities",
        operation_id="listCreatorActivities",
        response_model=CreatorActivityPageResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_creator_activities() -> CreatorActivityPageResponse:
        raise NotImplementedError

    @app.get(
        "/v1/activities/{activity_id}/timeline",
        operation_id="getCreatorActivityTimeline",
        response_model=CreatorActivityTimelineResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_activity_timeline(
        activity_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> CreatorActivityTimelineResponse:
        del activity_id
        raise NotImplementedError

    @app.get(
        "/v1/relationships/current",
        operation_id="getCreatorRelationshipCurrent",
        response_model=CreatorRelationshipCurrentResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_relationship_current() -> CreatorRelationshipCurrentResponse:
        raise NotImplementedError

    @app.get(
        "/v1/relationships/{relationship_id}/timeline",
        operation_id="getCreatorRelationshipTimeline",
        response_model=CreatorRelationshipTimelineResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_relationship_timeline(
        relationship_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> CreatorRelationshipTimelineResponse:
        del relationship_id
        raise NotImplementedError

    @app.post(
        "/v1/relationships/current/boundaries",
        operation_id="expressCreatorRelationshipBoundary",
        status_code=202,
        response_model=AcceptedOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def express_creator_relationship_boundary(
        _request: CreatorRelationshipBoundaryRequest,
        _idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                pattern=_IDEMPOTENCY_KEY_PATTERN,
                max_length=128,
            ),
        ],
    ) -> AcceptedOutcomeResponse:
        del _request, _idempotency_key
        raise NotImplementedError

    @app.get(
        "/v1/life-records",
        operation_id="queryCreatorLifeRecords",
        response_model=LifeRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def query_creator_life_records(
        kind: LifeRecordKindValue | None = None,
        q: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[
            str | None,
            Query(pattern=_CURSOR_PATTERN, max_length=2048),
        ] = None,
    ) -> LifeRecordPageResponse:
        del kind, q, limit, cursor
        raise NotImplementedError

    @app.get(
        "/v1/materials/{material_id}",
        operation_id="getCreatorLifeMaterial",
        response_model=CreatorLifeMaterialResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_life_material(
        material_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> CreatorLifeMaterialResponse:
        del material_id
        raise NotImplementedError

    @app.get(
        "/v1/memories",
        operation_id="listCreatorMemories",
        response_model=CreatorMemoryPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_creator_memories(
        q: Annotated[str | None, Query(min_length=1, max_length=1024)] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[
            str | None,
            Query(pattern=_CURSOR_PATTERN, max_length=2048),
        ] = None,
    ) -> CreatorMemoryPageResponse:
        del q, limit, cursor
        raise NotImplementedError

    @app.get(
        "/v1/memories/{memory_id}/timeline",
        operation_id="getCreatorMemoryTimeline",
        response_model=CreatorMemoryTimelineResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_memory_timeline(
        memory_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[
            str | None,
            Query(pattern=_CURSOR_PATTERN, max_length=2048),
        ] = None,
    ) -> CreatorMemoryTimelineResponse:
        del memory_id, limit, cursor
        raise NotImplementedError

    @app.get(
        "/v1/maintenance/status",
        operation_id="getCreatorMaintenanceStatus",
        response_model=CreatorMaintenanceStatusResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_maintenance_status() -> CreatorMaintenanceStatusResponse:
        raise NotImplementedError

    @app.get(
        "/v1/maintenance/{maintenance_session_id}/timeline",
        operation_id="getCreatorMaintenanceTimeline",
        response_model=CreatorMaintenanceTimelineResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_maintenance_timeline(
        maintenance_session_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> CreatorMaintenanceTimelineResponse:
        del maintenance_session_id
        raise NotImplementedError

    @app.post(
        "/v1/maintenance/{maintenance_session_id}/wake",
        operation_id="requestCreatorEmergencyWake",
        status_code=204,
        response_class=Response,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def request_creator_emergency_wake(
        maintenance_session_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> Response:
        del maintenance_session_id
        raise NotImplementedError

    @app.get(
        "/v1/scenes",
        operation_id="listCreatorScenes",
        response_model=CreatorSceneCollectionResponse,
        responses={
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_creator_scenes() -> CreatorSceneCollectionResponse:
        raise NotImplementedError

    @app.post(
        "/v1/scenes",
        operation_id="createCreatorScene",
        status_code=201,
        response_model=CreatorSceneResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def create_creator_scene(
        _request: CreatorSceneCreateRequest,
    ) -> CreatorSceneResponse:
        del _request
        raise NotImplementedError

    @app.post(
        "/v1/scenes/{scene_key}/close",
        operation_id="closeCreatorScene",
        response_model=CreatorSceneResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def close_creator_scene(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
    ) -> CreatorSceneResponse:
        del scene_key
        raise NotImplementedError

    @app.post(
        "/v1/scenes/{scene_key}/reopen",
        operation_id="reopenCreatorScene",
        response_model=CreatorSceneResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def reopen_creator_scene(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
    ) -> CreatorSceneResponse:
        del scene_key
        raise NotImplementedError

    @app.get(
        "/v1/scenes/{scene_key}/timeline",
        operation_id="getSceneTimeline",
        response_model=SceneTimelinePageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def scene_timeline(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=100)],
        cursor: Annotated[
            str | None,
            Query(pattern=_CURSOR_PATTERN, max_length=2048),
        ] = None,
    ) -> SceneTimelinePageResponse:
        del scene_key, limit, cursor
        raise NotImplementedError

    @app.get(
        "/v1/other-human-records",
        operation_id="listOtherHumanRecordParties",
        response_model=OtherHumanPartyRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_other_human_record_parties(
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        cursor: Annotated[
            str | None, Query(pattern=_CURSOR_PATTERN, max_length=2048)
        ] = None,
    ) -> OtherHumanPartyRecordPageResponse:
        del limit, cursor
        raise NotImplementedError

    @app.get(
        "/v1/other-human-records/{party_id}/scenes",
        operation_id="listOtherHumanRecordScenes",
        response_model=OtherHumanSceneRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def list_other_human_record_scenes(
        party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        cursor: Annotated[
            str | None, Query(pattern=_CURSOR_PATTERN, max_length=2048)
        ] = None,
    ) -> OtherHumanSceneRecordPageResponse:
        del party_id, limit, cursor
        raise NotImplementedError

    @app.get(
        "/v1/other-human-records/{party_id}/scenes/{scene_id}/timeline",
        operation_id="getOtherHumanRecordTimeline",
        response_model=OtherHumanTimelineRecordPageResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_other_human_record_timeline(
        party_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
        scene_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: Annotated[
            str | None, Query(pattern=_CURSOR_PATTERN, max_length=2048)
        ] = None,
    ) -> OtherHumanTimelineRecordPageResponse:
        del party_id, scene_id, limit, cursor
        raise NotImplementedError

    @app.post(
        "/v1/scenes/{scene_key}/messages",
        operation_id="acceptCreatorMessage",
        status_code=202,
        response_model=AcceptedOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def accept_creator_message(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
        _request: CreatorInputRequest,
        _idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                pattern=_IDEMPOTENCY_KEY_PATTERN,
                max_length=128,
            ),
        ],
    ) -> AcceptedOutcomeResponse:
        del scene_key, _request, _idempotency_key
        raise NotImplementedError

    @app.post(
        "/v1/scenes/{scene_key}/codex-tasks",
        operation_id="acceptCreatorCodexTask",
        status_code=202,
        response_model=AcceptedOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            413: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def accept_creator_codex_task(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
        _request: CreatorCodexTaskRequest,
        _idempotency_key: Annotated[
            str,
            Header(
                alias="Idempotency-Key",
                pattern=_IDEMPOTENCY_KEY_PATTERN,
                max_length=128,
            ),
        ],
    ) -> AcceptedOutcomeResponse:
        del scene_key, _request, _idempotency_key
        raise NotImplementedError

    @app.get(
        "/v1/operations/{result_ref}",
        operation_id="getCreatorOperation",
        response_model=OperationOutcomeResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_creator_operation(
        result_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> OperationOutcomeResponse:
        del result_ref
        raise NotImplementedError

    @app.get(
        "/v1/effects/{effect_id}",
        operation_id="getEffect",
        response_model=EffectResponse,
        responses={
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_effect(
        effect_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
    ) -> EffectResponse:
        del effect_id
        raise NotImplementedError

    @app.get(
        "/v1/effects/{effect_id}/artifacts/{artifact_kind}",
        operation_id="getEffectArtifact",
        response_class=Response,
        responses={
            200: {
                "description": "Explicit verified Codex result artifact.",
                "content": {
                    "text/plain": {"schema": {"type": "string"}},
                    "application/json": {"schema": {"type": "string"}},
                },
            },
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def get_effect_artifact(
        effect_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)],
        artifact_kind: Literal["patch", "final_result", "validation_report"],
    ) -> Response:
        del effect_id, artifact_kind
        raise NotImplementedError

    @app.get(
        "/v1/scenes/{scene_key}/events",
        operation_id="streamSceneEvents",
        response_class=StreamingResponse,
        responses={
            200: {
                "description": "Authenticated Creator projection invalidations.",
                "content": {
                    "text/event-stream": {
                        "schema": {
                            "type": "string",
                            "x-event-data-schema": {
                                "$ref": (
                                    "#/components/schemas/"
                                    "CreatorProjectionEventResponse"
                                )
                            },
                        }
                    }
                },
            },
            400: {"model": RejectedOutcomeResponse},
            401: {"model": RejectedOutcomeResponse},
            403: {"model": RejectedOutcomeResponse},
            404: {"model": RejectedOutcomeResponse},
            409: {"model": RejectedOutcomeResponse},
            429: {"model": RejectedOutcomeResponse},
            503: {"model": UnavailableOutcomeResponse},
        },
        dependencies=[Security(bearer)],
    )
    async def scene_events(
        scene_key: Annotated[str, Field(pattern=_SCENE_KEY_PATTERN)],
    ) -> StreamingResponse:
        del scene_key
        raise NotImplementedError

    schema_handlers = (
        health_live,
        health_ready,
        create_browser_session,
        current_browser_session,
        runtime_status,
        subject_summary,
        get_creator_prompt,
        revise_creator_prompt,
        deactivate_creator_prompt,
        create_creator_export,
        get_creator_export,
        create_data_rights_order,
        get_data_rights_order,
        list_creator_activities,
        get_creator_activity_timeline,
        get_creator_relationship_current,
        get_creator_relationship_timeline,
        express_creator_relationship_boundary,
        query_creator_life_records,
        get_creator_life_material,
        list_creator_memories,
        get_creator_memory_timeline,
        get_creator_maintenance_status,
        get_creator_maintenance_timeline,
        request_creator_emergency_wake,
        list_capability_requests,
        decide_capability_request,
        list_creator_scenes,
        create_creator_scene,
        close_creator_scene,
        reopen_creator_scene,
        scene_timeline,
        list_other_human_record_parties,
        list_other_human_record_scenes,
        get_other_human_record_timeline,
        accept_creator_message,
        accept_creator_codex_task,
        get_creator_operation,
        get_effect,
        get_effect_artifact,
        scene_events,
    )
    del schema_handlers
    schema = app.openapi()
    schema.pop("servers", None)
    schema["paths"]["/v1/scenes"]["post"]["responses"].pop("422", None)
    schema["paths"]["/v1/scenes/{scene_key}/close"]["post"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/scenes/{scene_key}/reopen"]["post"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/scenes/{scene_key}/timeline"]["get"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/other-human-records"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/other-human-records/{party_id}/scenes"]["get"][
        "responses"
    ].pop("422", None)
    schema["paths"]["/v1/other-human-records/{party_id}/scenes/{scene_id}/timeline"][
        "get"
    ]["responses"].pop("422", None)
    schema["paths"]["/v1/activities/{activity_id}/timeline"]["get"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/relationships/{relationship_id}/timeline"]["get"][
        "responses"
    ].pop("422", None)
    schema["paths"]["/v1/relationships/current/boundaries"]["post"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/prompts/creator-guidance"]["put"]["responses"].pop("422", None)
    schema["paths"]["/v1/prompts/creator-guidance/deactivation"]["post"][
        "responses"
    ].pop("422", None)
    schema["paths"]["/v1/exports"]["post"]["responses"].pop("422", None)
    schema["paths"]["/v1/exports/{export_id}"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/data-rights/orders"]["post"]["responses"].pop("422", None)
    schema["paths"]["/v1/data-rights/orders/{order_id}"]["get"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/life-records"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/materials/{material_id}"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/memories"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/memories/{memory_id}/timeline"]["get"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/maintenance/{maintenance_session_id}/timeline"]["get"][
        "responses"
    ].pop("422", None)
    schema["paths"]["/v1/maintenance/{maintenance_session_id}/wake"]["post"][
        "responses"
    ].pop("422", None)
    schema["paths"]["/v1/scenes/{scene_key}/events"]["get"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/scenes/{scene_key}/messages"]["post"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/scenes/{scene_key}/codex-tasks"]["post"]["responses"].pop(
        "422", None
    )
    schema["paths"]["/v1/operations/{result_ref}"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/effects/{effect_id}"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/effects/{effect_id}/artifacts/{artifact_kind}"]["get"][
        "responses"
    ].pop("422", None)
    schema["paths"]["/v1/capability-requests"]["get"]["responses"].pop("422", None)
    schema["paths"]["/v1/capability-requests/{capability_request_id}/decision"]["post"][
        "responses"
    ].pop("422", None)
    schemas = schema["components"]["schemas"]
    schemas["CreatorProjectionEventResponse"] = (
        CreatorProjectionEventResponse.model_json_schema(
            ref_template="#/components/schemas/{model}",
        )
    )
    return schema


__all__ = (
    "AcceptedOutcomeResponse",
    "AppliedOutcomeResponse",
    "BrowserSessionCurrentResponse",
    "BrowserSessionResponse",
    "CapabilityRequestDecisionRequest",
    "CapabilityRequestItemResponse",
    "CapabilityRequestPageResponse",
    "CompletedOutcomeResponse",
    "CreatorActivityItemResponse",
    "CreatorActivityPageResponse",
    "CreatorActivityTimelineItemResponse",
    "CreatorActivityTimelineResponse",
    "CreatorCodexTaskRequest",
    "CreatorExportRequest",
    "CreatorExportResponse",
    "CreatorInputRequest",
    "CreatorLifeMaterialResponse",
    "CreatorMaintenanceSessionResponse",
    "CreatorMaintenanceStatusResponse",
    "CreatorMaintenanceTimelineItemResponse",
    "CreatorMaintenanceTimelineResponse",
    "CreatorMemoryItemResponse",
    "CreatorMemoryPageResponse",
    "CreatorMemoryTimelineItemResponse",
    "CreatorMemoryTimelineResponse",
    "CreatorProjectionEventResponse",
    "CreatorPromptDeactivateRequest",
    "CreatorPromptResponse",
    "CreatorPromptRevisionRequest",
    "CreatorRelationshipBoundaryRequest",
    "CreatorRelationshipBoundaryResponse",
    "CreatorRelationshipCommitmentEventResponse",
    "CreatorRelationshipCommitmentResponse",
    "CreatorRelationshipCurrentResponse",
    "CreatorRelationshipFactResponse",
    "CreatorRelationshipIssueResolutionResponse",
    "CreatorRelationshipIssueResponse",
    "CreatorRelationshipItemResponse",
    "CreatorRelationshipRevisionResponse",
    "CreatorRelationshipTimelineResponse",
    "CreatorSceneCollectionResponse",
    "CreatorSceneCreateRequest",
    "CreatorSceneResponse",
    "DataRightsDeletionItemResponse",
    "DataRightsOrderCollectionResponse",
    "DataRightsOrderDetailResponse",
    "DataRightsOrderRequest",
    "DataRightsOrderResponse",
    "DataRightsTimelineItemResponse",
    "EffectResponse",
    "ErrorDescriptorResponse",
    "FailedOutcomeResponse",
    "LifeRecordItemResponse",
    "LifeRecordPageResponse",
    "LiveResponse",
    "OperationOutcomeResponse",
    "OtherHumanPartyRecordPageResponse",
    "OtherHumanPartyRecordResponse",
    "OtherHumanSceneRecordPageResponse",
    "OtherHumanSceneRecordResponse",
    "OtherHumanTimelineRecordPageResponse",
    "OtherHumanTimelineRecordResponse",
    "Readiness",
    "ReadyResponse",
    "RejectedOutcomeResponse",
    "RuntimeState",
    "RuntimeStatusResponse",
    "SceneTimelineItemResponse",
    "SceneTimelinePageResponse",
    "SubjectComponentSummaryResponse",
    "SubjectSummaryResponse",
    "UnavailableOutcomeResponse",
    "UnknownOutcomeResponse",
    "WaitingOutcomeResponse",
    "build_creator_openapi",
)
