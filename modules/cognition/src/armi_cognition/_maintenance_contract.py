"""Strict model contract for one bounded sleep-maintenance work step."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ._dialogue_contract import ContextRef
from ._text_contract import Text512

MAINTENANCE_WORK_CANDIDATE_VERSION = "armi.maintenance-work-candidate.v3"


class _StrictModel(BaseModel, frozen=True):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return MAINTENANCE_WORK_CANDIDATE_VERSION


class MemoryMaintenanceNoChange(_StrictModel, frozen=True):
    kind: Literal["memory_unchanged"]
    summary: Text512 = Field(...)


class MemoryRelation(_StrictModel, frozen=True):
    memory_ref: ContextRef
    kind: Literal["supports", "contradicts", "reinterprets"]


class MemoryMaintenanceChange(_StrictModel, frozen=True):
    kind: Literal["consolidate", "fade", "forget", "reinterpret"]
    memory_ref: ContextRef
    reason: Text512
    summary: Text512 | None
    uncertainty: Text512 | None = None
    relation: MemoryRelation | None = None

    @property
    def related_memory_ref(self) -> str | None:
        return self.relation.memory_ref if self.relation else None

    @property
    def relation_kind(self):
        return self.relation.kind if self.relation else None


class MemoryRetentionChange(MemoryMaintenanceChange, frozen=True):
    kind: Literal["consolidate", "fade", "forget"]
    summary: None = None
    relation: None = None


class MemoryReinterpretation(MemoryMaintenanceChange, frozen=True):
    kind: Literal["reinterpret"]
    summary: Text512 = Field(...)
    relation: MemoryRelation | None = None


class SelfCheckNoIssue(_StrictModel, frozen=True):
    kind: Literal["no_issue"]
    summary: Text512


class SelfCheckIssueFound(_StrictModel, frozen=True):
    kind: Literal["issue_found"]
    issue_kind: Literal[
        "self_mind_conflict",
        "relationship_conflict",
        "activity_stalled",
        "incomplete_internal_responsibility",
        "inconsistent_current_head",
    ]
    internal_summary: Text512
    creator_visible_summary: Text512
    issue_target: Literal["self", "mind", "prompt"]


MaintenanceWorkCandidate = Annotated[
    MemoryMaintenanceNoChange
    | MemoryRetentionChange
    | MemoryReinterpretation
    | SelfCheckNoIssue
    | SelfCheckIssueFound,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[MaintenanceWorkCandidate] = TypeAdapter(MaintenanceWorkCandidate)
_PURPOSE_ADAPTERS: dict[str, TypeAdapter[MaintenanceWorkCandidate]] = {
    "maintain_subjective_memory": TypeAdapter(
        Annotated[
            MemoryMaintenanceNoChange | MemoryRetentionChange | MemoryReinterpretation,
            Field(discriminator="kind"),
        ]
    ),
    "perform_subject_self_check": TypeAdapter(
        Annotated[SelfCheckNoIssue | SelfCheckIssueFound, Field(discriminator="kind")]
    ),
}


def maintenance_work_candidate_schema(*, purpose: str | None = None) -> dict[str, Any]:
    adapter = _ADAPTER if purpose is None else _PURPOSE_ADAPTERS[purpose]
    return adapter.json_schema()


def parse_maintenance_work_candidate(
    value: object, *, purpose: str | None = None
) -> MaintenanceWorkCandidate:
    adapter = _ADAPTER if purpose is None else _PURPOSE_ADAPTERS[purpose]
    return adapter.validate_python(value, strict=True)


__all__ = (
    "MAINTENANCE_WORK_CANDIDATE_VERSION",
    "MaintenanceWorkCandidate",
    "MemoryMaintenanceChange",
    "MemoryMaintenanceNoChange",
    "SelfCheckIssueFound",
    "SelfCheckNoIssue",
    "maintenance_work_candidate_schema",
    "parse_maintenance_work_candidate",
)
