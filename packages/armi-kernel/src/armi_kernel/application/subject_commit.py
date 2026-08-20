"""Technology-neutral T-03 subject commit contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

_CODE = re.compile(r"^(?:CON|SUBJECT|CONFLICT|DB)-[A-Z0-9-]+$", re.ASCII)


class CandidateApplicationStatus(StrEnum):
    APPLIED = "applied"
    NO_CHANGE = "no_change"
    DEFERRED = "deferred"
    DECLINED = "declined"
    NO_ACTION = "no_action"
    NEED_INFORMATION = "need_information"
    STALE = "stale"


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
class SubjectCommitResult:
    application_id: CandidateApplicationId
    status: CandidateApplicationStatus
    subject_commit_id: SubjectCommitId | None = None
    subject_version: int | None = None
    successor_opportunity_id: UUID | None = None

    def __post_init__(self) -> None:
        if (
            type(self.application_id) is not CandidateApplicationId
            or type(self.status) is not CandidateApplicationStatus
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


def _require_uuid7(value: UUID, code: str) -> None:
    if type(value) is not UUID or value.version != 7:
        raise SubjectCommitViolation(code)


__all__ = (
    "CandidateApplicationId",
    "CandidateApplicationStatus",
    "ExperienceId",
    "SubjectCommitId",
    "SubjectCommitResult",
    "SubjectCommitViolation",
)
