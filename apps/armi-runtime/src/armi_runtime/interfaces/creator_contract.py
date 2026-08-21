"""Strict Creator wire models and deterministic schema-only OpenAPI export."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

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
_DIGEST_PATTERN = r"sha256:[0-9a-f]{64}"
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
    modality: Literal["text", "media_file", "live_voice"] = "text"


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
    "reflect_self",
    "reflect_mind",
    "reflect_mood",
    "reflect_prompt",
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
    "reflection_changed",
    "reflection_unchanged",
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
        "creator-operation.v2",
        "other-human-record.v1",
        "creator-effect.v3",
        "subject-summary.v1",
        "data-rights-order-detail.v1",
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


class RuntimeComponentHealthResponse(_StrictWireModel):
    component: Literal["database", "runtime", "creator_web"]
    state: Literal["ready", "degraded", "unavailable"]
    reason_codes: Annotated[list[ReasonCode], Field(max_length=16)]


class RuntimeStatusResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    environment_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    runtime_state: RuntimeState
    readiness: Readiness
    reason_codes: Annotated[list[ReasonCode], Field(max_length=32)]
    components: Annotated[
        list[RuntimeComponentHealthResponse],
        Field(min_length=3, max_length=3),
    ]
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]


class QQChannelHealthResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-channel-health.v2"]
    channel: Literal["qq"]
    driver: Literal["napcat"]
    configured: bool
    enabled: bool
    state: Literal[
        "disabled",
        "starting",
        "login_required",
        "ready",
        "unavailable",
        "misconfigured",
    ]
    ingress_ready: bool
    api_reachable: bool
    account_online: bool | None
    account_matches: bool | None
    webui_url: (
        Annotated[
            str,
            Field(pattern=r"^http://127\.0\.0\.1:[1-9][0-9]{0,4}/webui/$"),
        ]
        | None
    )
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    reason_codes: Annotated[list[ReasonCode], Field(max_length=16)]


class LiveVoiceStatusResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-live-voice-status.v1"]
    state: Literal[
        "disabled",
        "idle",
        "starting",
        "listening",
        "recognizing",
        "thinking",
        "speaking",
        "waiting_slow",
        "unavailable",
    ]
    enabled: bool
    input_device: str | None
    output_device: str | None
    asr_ready: bool
    llm_ready: bool
    tts_ready: bool
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    reason_codes: Annotated[list[ReasonCode], Field(max_length=16)]


class LiveVisionStatusResponse(_StrictWireModel):
    contract_version: Literal["1.0"]
    projection_version: Literal["creator-live-vision-status.v1"]
    state: Literal[
        "disabled",
        "idle",
        "starting",
        "observing",
        "degraded",
        "unavailable",
        "stopping",
    ]
    enabled: bool
    expected_running: bool
    device: str | None
    capture_ready: bool
    perception_ready: bool
    last_frame_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None
    last_observation_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)] | None
    observations_last_hour: Annotated[int, Field(ge=0)]
    hourly_limit: Annotated[int, Field(ge=1)]
    observed_at: Annotated[str, Field(pattern=_INSTANT_PATTERN)]
    reason_codes: Annotated[list[ReasonCode], Field(max_length=16)]


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


class CreatorCodexExecutionDetails(_StrictWireModel):
    task_source_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    verification_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    execution_status: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    model_id: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    sdk_identity: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    validator_id: Annotated[str, Field(min_length=1, max_length=128)]
    source_tree_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    final_tree_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)] | None = None


class CreatorOperationDetails(_StrictWireModel):
    projection_version: Literal["creator-operation.v2"]
    operation_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    operation_kind: Literal[
        "cognition",
        "subject_change",
        "creator_response",
        "other_human_response",
        "codex_delegation",
        "formal_dialogue",
    ]
    intent_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    dialogue_decision_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    policy_decision_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    effect_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    work_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
    stage: Literal[
        "accepted",
        "context_preparing",
        "model_pending",
        "candidate_validating",
        "subject_committing",
        "candidate_rejected",
        "applied",
        "no_change",
        "need_information",
        "stale",
        "no_action",
        "declined",
        "deferred",
        "ended",
        "awaiting_authorization",
        "confirmation_required",
        "authorization_denied",
        "unavailable",
        "registering_effect",
        "registered",
        "dispatching",
        "completed",
        "failed",
        "unknown",
        "cancelled",
    ]
    outcome: Literal[
        "pending",
        "applied",
        "completed",
        "rejected",
        "unavailable",
        "failed",
        "unknown",
        "cancelled",
        "no_action",
        "deferred",
        "stale",
    ]
    reason_code: Annotated[str, Field(min_length=1, max_length=128)] | None = None
    codex_execution: CreatorCodexExecutionDetails | None = None


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
    schema_version: Literal["armi.self.v1", "armi.mind.v2", "armi.life-mode.v1"]
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
    projection_version: Literal["creator-effect.v3"]
    effect_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    action_intent_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    action_intent_revision_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    policy_decision_ref: Annotated[str, Field(pattern=_UUIDV7_PATTERN)] | None = None
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
    projection_version: Literal["creator-export.v2"]
    export_id: Annotated[str, Field(pattern=_UUIDV7_PATTERN)]
    status: Literal["running", "completed", "partial", "failed"]
    directory_name: Annotated[str, Field(min_length=1, max_length=64)]
    destination_path: Annotated[str, Field(min_length=1, max_length=4096)]
    segment_count: Annotated[int, Field(ge=0)]
    record_count: Annotated[int, Field(ge=0)]
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
    projection_version: Literal["data-rights-order-summary.v1"]
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
    projection_version: Literal["data-rights-order-detail.v1"]
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
    projection_version: Literal["data-rights-order-collection.v1"]
    orders: list[DataRightsOrderDetailResponse]


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
    "LiveVisionStatusResponse",
    "LiveVoiceStatusResponse",
    "OperationOutcomeResponse",
    "OtherHumanPartyRecordPageResponse",
    "OtherHumanPartyRecordResponse",
    "OtherHumanSceneRecordPageResponse",
    "OtherHumanSceneRecordResponse",
    "OtherHumanTimelineRecordPageResponse",
    "OtherHumanTimelineRecordResponse",
    "QQChannelHealthResponse",
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
)
