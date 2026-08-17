"""Strict model contract for one bounded sleep-maintenance work step."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

MAINTENANCE_WORK_CANDIDATE_VERSION = "armi.maintenance-work-candidate.v1"

_CONTEXT_REF = re.compile(r"^ctx:[1-9][0-9]{0,2}$", re.ASCII)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @property
    def schema_version(self) -> str:
        return MAINTENANCE_WORK_CANDIDATE_VERSION


class MemoryMaintenanceNoChange(_StrictModel):
    kind: Literal["memory_unchanged"]
    summary: str

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _text(value, 512)


class MemoryMaintenanceChange(_StrictModel):
    kind: Literal["consolidate", "fade", "forget", "reinterpret"]
    memory_ref: str
    reason: str
    summary: str | None = None
    uncertainty: str | None = None
    related_memory_ref: str | None = None
    relation_kind: Literal["supports", "contradicts", "reinterprets"] | None = None

    @field_validator("memory_ref", "related_memory_ref")
    @classmethod
    def _ref(cls, value: str | None) -> str | None:
        if value is not None and _CONTEXT_REF.fullmatch(value) is None:
            raise ValueError("memory reference must point to frozen Context")
        return value

    @field_validator("reason")
    @classmethod
    def _reason(cls, value: str) -> str:
        return _text(value, 512)

    @field_validator("summary", "uncertainty")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        return None if value is None else _text(value, 512)

    def model_post_init(self, _context: Any) -> None:
        reinterpret = self.kind == "reinterpret"
        if reinterpret != (self.summary is not None):
            raise ValueError("reinterpret requires a complete replacement summary")
        if (self.related_memory_ref is None) != (self.relation_kind is None):
            raise ValueError("memory relation is incomplete")
        if self.related_memory_ref is not None and not reinterpret:
            raise ValueError("only reinterpret may relate memories")


class SelfCheckNoIssue(_StrictModel):
    kind: Literal["no_issue"]
    summary: str

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _text(value, 512)


class SelfCheckIssueFound(_StrictModel):
    kind: Literal["issue_found"]
    issue_kind: Literal[
        "self_mind_conflict",
        "relationship_conflict",
        "activity_stalled",
        "incomplete_internal_responsibility",
        "inconsistent_current_head",
    ]
    internal_summary: str
    creator_visible_summary: str
    issue_target: Literal["self", "mind", "prompt"]

    @field_validator("internal_summary", "creator_visible_summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _text(value, 512)


MaintenanceWorkCandidate = Annotated[
    MemoryMaintenanceNoChange
    | MemoryMaintenanceChange
    | SelfCheckNoIssue
    | SelfCheckIssueFound,
    Field(discriminator="kind"),
]
_ADAPTER: TypeAdapter[MaintenanceWorkCandidate] = TypeAdapter(MaintenanceWorkCandidate)


def _text(value: str, maximum: int) -> str:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError("text must be strict UTF-8") from exc
    if not 1 <= len(encoded) <= maximum or b"\x00" in encoded or not value.strip():
        raise ValueError("text exceeds UTF-8 boundary")
    return value


def maintenance_work_candidate_schema() -> dict[str, Any]:
    return _ADAPTER.json_schema()


def parse_maintenance_work_candidate(value: object) -> MaintenanceWorkCandidate:
    return _ADAPTER.validate_python(value, strict=True)


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
