"""Stable public contract of the accepted-experience owner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable
from uuid import UUID

from armi_kernel.application import CandidateFactClass, ExperienceId
from armi_runtime_foundation import PostgreSQLTransaction

_PROPOSAL = re.compile(r"^proposal:[1-9][0-9]{0,2}$", re.ASCII)


class ExperienceViolation(RuntimeError):
    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or not code.startswith("EXPERIENCE-"):
            raise ValueError("experience violation code is invalid")
        self.code = code
        super().__init__("experience operation failed")

    def __str__(self) -> str:
        return f"{self.code}: experience operation failed"


class ExperienceKind(StrEnum):
    CREATOR_INPUT = "creator_input"
    WEB_OBSERVATION = "web_observation"
    CODEX_OBSERVATION = "codex_observation"
    OTHER_HUMAN_INPUT = "other_human_input"


class ExperienceSourcePerspective(StrEnum):
    CREATOR_CLAIM = "creator_claim"
    WEB_CLAIM = "web_claim"
    CODEX_OBSERVATION = "codex_observation"
    OTHER_HUMAN_CLAIM = "other_human_claim"


def _uuid7(value: object) -> bool:
    return type(value) is UUID and value.version == 7


def _text(value: object, maximum: int, *, optional: bool = False) -> bool:
    if value is None:
        return optional
    return type(value) is str and 1 <= len(value) <= maximum and "\x00" not in value


@dataclass(frozen=True, slots=True)
class AcceptedExperienceDraft:
    experience_id: ExperienceId
    subject_id: UUID
    subject_commit_id: UUID
    cognitive_episode_id: UUID
    proposal_ref: str
    experience_kind: ExperienceKind
    fact_class: CandidateFactClass
    first_person_gist: str
    scene_id: UUID
    occurred_at: datetime
    source_perspective: ExperienceSourcePerspective
    uncertainty: str | None

    def __post_init__(self) -> None:
        expected_source = {
            ExperienceKind.CREATOR_INPUT: ExperienceSourcePerspective.CREATOR_CLAIM,
            ExperienceKind.WEB_OBSERVATION: ExperienceSourcePerspective.WEB_CLAIM,
            ExperienceKind.CODEX_OBSERVATION: (
                ExperienceSourcePerspective.CODEX_OBSERVATION
            ),
            ExperienceKind.OTHER_HUMAN_INPUT: (
                ExperienceSourcePerspective.OTHER_HUMAN_CLAIM
            ),
        }
        if (
            type(self.experience_id) is not ExperienceId
            or not _uuid7(self.subject_id)
            or not _uuid7(self.subject_commit_id)
            or not _uuid7(self.cognitive_episode_id)
            or _PROPOSAL.fullmatch(self.proposal_ref) is None
            or type(self.experience_kind) is not ExperienceKind
            or type(self.fact_class) is not CandidateFactClass
            or not _text(self.first_person_gist, 1024)
            or not _uuid7(self.scene_id)
            or type(self.occurred_at) is not datetime
            or self.occurred_at.tzinfo is None
            or type(self.source_perspective) is not ExperienceSourcePerspective
            or expected_source.get(self.experience_kind) is not self.source_perspective
            or not _text(self.uncertainty, 512, optional=True)
        ):
            raise ExperienceViolation("EXPERIENCE-DRAFT")


@dataclass(frozen=True, slots=True)
class AcceptedExperienceSnapshot:
    experience_id: ExperienceId
    fact_class: CandidateFactClass
    first_person_gist: str
    occurred_at: datetime
    accepted_at: datetime
    source_perspective: ExperienceSourcePerspective
    uncertainty: str | None


@dataclass(frozen=True, slots=True)
class ExperienceLifeRecordItem:
    experience_id: UUID
    summary: str
    source_kind: str
    occurred_at: datetime


@runtime_checkable
class ExperienceCommitPort(Protocol):
    async def record(
        self,
        transaction: PostgreSQLTransaction,
        draft: AcceptedExperienceDraft,
    ) -> None: ...


@runtime_checkable
class ExperienceReadPort(Protocol):
    async def recent(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        limit: int,
    ) -> tuple[AcceptedExperienceSnapshot, ...]: ...

    async def accepted_after(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        after_experience_id: UUID | None,
        since: datetime,
        limit: int,
    ) -> tuple[AcceptedExperienceSnapshot, ...]: ...

    async def by_ids(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        experience_ids: tuple[UUID, ...],
    ) -> tuple[AcceptedExperienceSnapshot, ...]: ...


@runtime_checkable
class ExperienceLifeRecordPort(Protocol):
    async def life_record_branch(
        self,
        transaction: PostgreSQLTransaction,
        *,
        subject_id: UUID,
        query_text: str | None,
        before: tuple[datetime, str, UUID] | None,
        limit: int,
    ) -> tuple[ExperienceLifeRecordItem, ...]: ...


@runtime_checkable
class ExperienceOwnerPort(
    ExperienceCommitPort,
    ExperienceReadPort,
    ExperienceLifeRecordPort,
    Protocol,
):
    """Complete shared read/commit surface of the active Experience repository."""


__all__ = (
    "AcceptedExperienceDraft",
    "AcceptedExperienceSnapshot",
    "ExperienceCommitPort",
    "ExperienceKind",
    "ExperienceLifeRecordItem",
    "ExperienceLifeRecordPort",
    "ExperienceOwnerPort",
    "ExperienceReadPort",
    "ExperienceSourcePerspective",
    "ExperienceViolation",
)
