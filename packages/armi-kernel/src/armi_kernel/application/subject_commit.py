"""Technology-neutral T-03 subject commit contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.contracts import Digest

_CODE = re.compile(r"^(?:CON|SUBJECT|CONFLICT|DB)-[A-Z0-9-]+$", re.ASCII)


class CandidateApplicationStatus(StrEnum):
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    DEFERRED = "deferred"
    DECLINED = "declined"
    NO_ACTION = "no_action"
    NEED_INFORMATION = "need_information"
    STALE = "stale"


class SubjectComponentKind(StrEnum):
    SELF = "self"
    MIND = "mind"
    LIFE_MODE = "life_mode"


class SubjectCommitViolation(RuntimeError):
    """Expose a stable T-03 failure without private subject content."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or _CODE.fullmatch(code) is None:
            raise ValueError("subject commit violation code is invalid")
        self.code = code
        super().__init__("subject commit failed")

    def __str__(self) -> str:
        return f"{self.code}: subject commit failed"


@dataclass(frozen=True, slots=True)
class SubjectCommitId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-SUBJECT-COMMIT-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ExperienceId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-SUBJECT-EXPERIENCE-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class CandidateApplicationId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid7(self.value, "CON-SUBJECT-APPLICATION-ID")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class SubjectComponentSummary:
    kind: SubjectComponentKind
    version: int
    schema_version: str
    content_visibility: str = "private"

    def __post_init__(self) -> None:
        if (
            type(self.kind) is not SubjectComponentKind
            or type(self.version) is not int
            or self.version <= 0
            or self.schema_version
            not in {"armi.self.v1", "armi.mind.v1", "armi.life-mode.v1"}
            or self.content_visibility != "private"
        ):
            raise SubjectCommitViolation("CON-SUBJECT-SUMMARY")
        expected = {
            SubjectComponentKind.SELF: "armi.self.v1",
            SubjectComponentKind.MIND: "armi.mind.v1",
            SubjectComponentKind.LIFE_MODE: "armi.life-mode.v1",
        }[self.kind]
        if self.schema_version != expected:
            raise SubjectCommitViolation("CON-SUBJECT-SUMMARY")


@dataclass(frozen=True, slots=True)
class SubjectSummary:
    subject_version: int
    components: tuple[SubjectComponentSummary, ...]
    latest_commit_ref: SubjectCommitId | None
    observed_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.subject_version) is not int
            or self.subject_version < 0
            or type(self.components) is not tuple
            or tuple(component.kind for component in self.components)
            != (
                SubjectComponentKind.SELF,
                SubjectComponentKind.MIND,
                SubjectComponentKind.LIFE_MODE,
            )
            or (
                self.latest_commit_ref is not None
                and type(self.latest_commit_ref) is not SubjectCommitId
            )
            or type(self.observed_at) is not datetime
            or self.observed_at.tzinfo is None
        ):
            raise SubjectCommitViolation("CON-SUBJECT-SUMMARY")


@dataclass(frozen=True, slots=True)
class SubjectCommitResult:
    application_id: CandidateApplicationId
    status: CandidateApplicationStatus
    completion_digest: Digest
    subject_commit_id: SubjectCommitId | None = None
    subject_version: int | None = None
    successor_opportunity_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            type(self.application_id) is not CandidateApplicationId
            or type(self.status) is not CandidateApplicationStatus
            or type(self.completion_digest) is not Digest
            or (
                self.subject_version is not None
                and (type(self.subject_version) is not int or self.subject_version < 0)
            )
            or (
                self.successor_opportunity_id is not None
                and (
                    type(self.successor_opportunity_id) is not UUID
                    or self.successor_opportunity_id.version != 7
                )
            )
        ):
            raise SubjectCommitViolation("CON-SUBJECT-COMMIT-RESULT")
        applied = self.status is CandidateApplicationStatus.APPLIED
        if applied != (self.subject_commit_id is not None):
            raise SubjectCommitViolation("CON-SUBJECT-COMMIT-RESULT")
        if applied != (self.subject_version is not None):
            raise SubjectCommitViolation("CON-SUBJECT-COMMIT-RESULT")
        if (
            self.successor_opportunity_id is not None
            and self.status is not CandidateApplicationStatus.STALE
        ):
            raise SubjectCommitViolation("CON-SUBJECT-COMMIT-RESULT")


@runtime_checkable
class SubjectCommitPort(Protocol):
    async def commit_once(self) -> bool:
        """Claim and settle at most one validated T-03 responsibility."""
        ...


def _require_uuid7(value: UUID, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise SubjectCommitViolation(code)


__all__ = (
    "CandidateApplicationId",
    "CandidateApplicationStatus",
    "ExperienceId",
    "SubjectCommitId",
    "SubjectCommitPort",
    "SubjectCommitResult",
    "SubjectCommitViolation",
    "SubjectComponentKind",
    "SubjectComponentSummary",
    "SubjectSummary",
)
